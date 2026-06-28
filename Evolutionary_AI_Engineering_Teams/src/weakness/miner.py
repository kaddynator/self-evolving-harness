from __future__ import annotations

from collections import Counter
from typing import List

from src.ir.schema import OrganizationHarness
from src.runtime.executor import RunResult
from src.runtime.events import EventType
from src.evaluation.scorer import EvaluationResult
from src.weakness.signatures import FailureSignature, Mechanism


def mine_weaknesses(
    run: RunResult,
    ev: EvaluationResult,
    harness: OrganizationHarness,
) -> List[FailureSignature]:
    """Apply all rule-based classifiers and return deduplicated failure signatures."""
    sigs: List[FailureSignature] = []

    sigs.extend(_check_tests_failed(ev))
    sigs.extend(_check_missing_artifacts(run, harness))
    sigs.extend(_check_repeated_tool_errors(run))
    sigs.extend(_check_excessive_exploration(run, harness))
    sigs.extend(_check_wrong_tool_permission(run))
    sigs.extend(_check_oversized_patch(ev))
    sigs.extend(_check_unverified_completion(run, harness))
    sigs.extend(_check_late_testing(run, harness))
    sigs.extend(_check_redundant_agents(run, harness))

    return _deduplicate(sigs)


# ---------------------------------------------------------------------------
# Rule classifiers
# ---------------------------------------------------------------------------

def _check_tests_failed(ev: EvaluationResult) -> List[FailureSignature]:
    if ev.raw_metrics.get("tests_pass") is False:
        return [FailureSignature(
            verifier_cause="tests_failed",
            agent_behavior="implementation_produced_failing_tests",
            mechanism=Mechanism.WEAK_REQUIREMENTS_GROUNDING,
            detail="test_runner reported failures",
        )]
    return []


def _check_missing_artifacts(run: RunResult, harness: OrganizationHarness) -> List[FailureSignature]:
    sigs = []
    for expected in harness.task.artifacts_expected:
        if expected not in run.artifacts:
            sigs.append(FailureSignature(
                verifier_cause="missing_required_file",
                agent_behavior="agent_did_not_produce_artifact",
                mechanism=Mechanism.MISSING_REQUIRED_ARTIFACT,
                detail=f"artifact '{expected}' not found in run output",
            ))
    return sigs


def _check_repeated_tool_errors(run: RunResult) -> List[FailureSignature]:
    """Flag any agent that triggered the same tool error more than once."""
    sigs = []
    # group error events by (agent_id, tool_name)
    error_counts: Counter = Counter()
    for evt in run.events:
        if evt.event_type == EventType.tool_error:
            tool = evt.data.get("tool", "unknown")
            error_counts[(evt.agent_id, tool)] += 1

    for (agent_id, tool), count in error_counts.items():
        if count > 1:
            sigs.append(FailureSignature(
                verifier_cause="tool_error_repeated",
                agent_behavior=f"agent_retried_same_failing_tool:{tool}",
                mechanism=Mechanism.REPEATED_FAILED_TOOL_CALL,
                agent_id=agent_id,
                detail=f"{tool} failed {count} times for {agent_id}",
            ))
    return sigs


def _check_excessive_exploration(run: RunResult, harness: OrganizationHarness) -> List[FailureSignature]:
    """Flag if total tool calls crossed the reflection threshold.

    Fires regardless of whether a patch was produced — an existing patch does
    not excuse an inefficient workflow; the budget mutation will tighten the
    coder's tool allowance to bring total_tool_calls below the threshold.
    """
    threshold = harness.runtime_policies.exploration_to_implementation_threshold
    if run.total_tool_calls > threshold:
        return [FailureSignature(
            verifier_cause="tool_budget_exceeded",
            agent_behavior="excessive_tool_calls_in_workflow",
            mechanism=Mechanism.EXCESSIVE_EXPLORATION,
            detail=f"tool_calls={run.total_tool_calls} exceeds threshold {threshold}",
        )]
    return []


def _check_wrong_tool_permission(run: RunResult) -> List[FailureSignature]:
    """Flag tool errors caused by a permission denial (tool_not_permitted)."""
    sigs = []
    seen = set()
    for evt in run.events:
        if evt.event_type == EventType.tool_error:
            result = evt.data.get("result", {})
            if result.get("error") == "tool_not_permitted":
                tool = evt.data.get("tool", "unknown")
                key = (evt.agent_id, tool)
                if key not in seen:
                    seen.add(key)
                    sigs.append(FailureSignature(
                        verifier_cause="tool_permission_denied",
                        agent_behavior=f"agent_used_unpermitted_tool:{tool}",
                        mechanism=Mechanism.WRONG_TOOL_PERMISSION,
                        agent_id=evt.agent_id,
                        detail=f"agent '{evt.agent_id}' tried to use '{tool}' without permission",
                    ))
    return sigs


def _check_oversized_patch(ev: EvaluationResult) -> List[FailureSignature]:
    diff_size = ev.raw_metrics.get("diff_size", 0)
    if diff_size > 100:
        return [FailureSignature(
            verifier_cause="patch_too_large",
            agent_behavior="coder_produced_oversized_diff",
            mechanism=Mechanism.OVERSIZED_PATCH,
            detail=f"diff_size={diff_size} lines",
        )]
    return []


def _check_unverified_completion(run: RunResult, harness: OrganizationHarness) -> List[FailureSignature]:
    """Flag if no tests_run event was emitted but the run finished successfully."""
    if not run.success:
        return []
    if not harness.runtime_policies.verify_before_conclude:
        return []
    has_tests_run = any(e.event_type == EventType.tests_run for e in run.events)
    if not has_tests_run and "test_results" not in run.artifacts:
        return [FailureSignature(
            verifier_cause="no_verification_step",
            agent_behavior="run_concluded_without_test_evidence",
            mechanism=Mechanism.UNVERIFIED_COMPLETION,
            detail="no tests_run event and no test_results artifact",
        )]
    return []


def _check_late_testing(run: RunResult, harness: OrganizationHarness) -> List[FailureSignature]:
    """Flag if a coder agent ran tests before a dedicated tester agent did."""
    phase_order = {p.name: i for i, p in enumerate(harness.execution.phases)}
    coder_test_phase: int | None = None
    tester_phase: int | None = None

    for evt in run.events:
        if evt.event_type == EventType.tool_called and evt.data.get("tool") == "run_tests":
            phase_idx = phase_order.get(evt.phase or "", 999)
            agent_id = evt.agent_id or ""
            if "coder" in agent_id and (coder_test_phase is None or phase_idx < coder_test_phase):
                coder_test_phase = phase_idx
        if evt.event_type == EventType.agent_started:
            agent_id = evt.agent_id or ""
            if "tester" in agent_id:
                phase_idx = phase_order.get(evt.phase or "", 999)
                if tester_phase is None or phase_idx < tester_phase:
                    tester_phase = phase_idx

    if (
        coder_test_phase is not None
        and tester_phase is not None
        and coder_test_phase < tester_phase
    ):
        return [FailureSignature(
            verifier_cause="test_order_violation",
            agent_behavior="coder_ran_tests_before_tester_agent",
            mechanism=Mechanism.LATE_TESTING,
            detail="coder tested before dedicated tester phase",
        )]
    return []


def _check_redundant_agents(run: RunResult, harness: OrganizationHarness) -> List[FailureSignature]:
    """Flag non-core agents when total agent count exceeds 5 and tool calls are high."""
    agent_count = len(harness.agents)
    if agent_count <= 5:
        return []
    threshold = harness.runtime_policies.exploration_to_implementation_threshold
    if run.total_tool_calls <= threshold:
        return []

    core_keywords = ("requirements", "coder", "tester", "reviewer")
    sigs = []
    for agent in harness.agents:
        if any(kw in agent.id.lower() for kw in core_keywords):
            continue
        # Only flag first non-core agent to produce one proposal at a time
        sigs.append(FailureSignature(
            verifier_cause="agent_count_high",
            agent_behavior=f"workflow_has_{agent_count}_agents_exceeding_optimal",
            mechanism=Mechanism.REDUNDANT_AGENT,
            agent_id=agent.id,
            detail=f"{agent_count} agents; '{agent.id}' is a non-core candidate for removal",
        ))
        break  # one signature per cycle — gate will confirm if it helps

    return sigs


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(sigs: List[FailureSignature]) -> List[FailureSignature]:
    seen: set = set()
    result = []
    for sig in sigs:
        key = sig.signature_key()
        if key not in seen:
            seen.add(key)
            result.append(sig)
    return result
