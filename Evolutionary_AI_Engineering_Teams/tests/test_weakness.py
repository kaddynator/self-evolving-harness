from pathlib import Path
from copy import deepcopy
from typing import Any, Dict, List

import pytest

from src.ir.loader import load_harness
from src.ir.schema import OrganizationHarness
from src.runtime.executor import RuntimeExecutor, RunResult
from src.runtime.events import EventType, TraceEvent
from src.evaluation.scorer import score_run, EvaluationResult
from src.weakness.miner import mine_weaknesses
from src.weakness.signatures import FailureSignature, Mechanism

EXAMPLE_SPEC = Path(__file__).parent.parent / "examples" / "organization_spec.yaml"


@pytest.fixture
def harness() -> OrganizationHarness:
    return load_harness(EXAMPLE_SPEC)


@pytest.fixture
def run_result(harness) -> RunResult:
    return RuntimeExecutor().run(harness)


@pytest.fixture
def eval_result(run_result, harness) -> EvaluationResult:
    return score_run(run_result, harness.evaluation)


# ---------------------------------------------------------------------------
# Happy path — clean run produces no signatures
# ---------------------------------------------------------------------------

def test_clean_run_no_signatures(run_result, eval_result, harness):
    sigs = mine_weaknesses(run_result, eval_result, harness)
    # Mock run succeeds and produces all artifacts — no failures expected
    for sig in sigs:
        assert sig.mechanism not in (
            Mechanism.MISSING_REQUIRED_ARTIFACT,
            Mechanism.REPEATED_FAILED_TOOL_CALL,
            Mechanism.WEAK_REQUIREMENTS_GROUNDING,
        )


def test_returns_list(run_result, eval_result, harness):
    result = mine_weaknesses(run_result, eval_result, harness)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests-failed classifier
# ---------------------------------------------------------------------------

def test_detects_tests_failed(run_result, eval_result, harness):
    bad_eval = deepcopy(eval_result)
    bad_eval.raw_metrics["tests_pass"] = False
    sigs = mine_weaknesses(run_result, bad_eval, harness)
    mechanisms = [s.mechanism for s in sigs]
    assert Mechanism.WEAK_REQUIREMENTS_GROUNDING in mechanisms


def test_no_tests_failed_signature_on_pass(run_result, eval_result, harness):
    sigs = mine_weaknesses(run_result, eval_result, harness)
    causes = [s.verifier_cause for s in sigs]
    assert "tests_failed" not in causes


# ---------------------------------------------------------------------------
# Missing artifact classifier
# ---------------------------------------------------------------------------

def test_detects_missing_artifact(harness, eval_result):
    run = RuntimeExecutor().run(harness)
    run.artifacts.pop("code_patch", None)
    sigs = mine_weaknesses(run, eval_result, harness)
    mechanisms = [s.mechanism for s in sigs]
    assert Mechanism.MISSING_REQUIRED_ARTIFACT in mechanisms


def test_missing_artifact_detail_names_artifact(harness, eval_result):
    run = RuntimeExecutor().run(harness)
    run.artifacts.pop("code_patch", None)
    sigs = mine_weaknesses(run, eval_result, harness)
    sig = next(s for s in sigs if s.mechanism == Mechanism.MISSING_REQUIRED_ARTIFACT)
    assert "code_patch" in sig.detail


def test_no_missing_artifact_when_all_present(run_result, eval_result, harness):
    sigs = mine_weaknesses(run_result, eval_result, harness)
    assert not any(s.mechanism == Mechanism.MISSING_REQUIRED_ARTIFACT for s in sigs)


# ---------------------------------------------------------------------------
# Repeated tool error classifier
# ---------------------------------------------------------------------------

def test_detects_repeated_tool_error(run_result, eval_result, harness):
    run = deepcopy(run_result)
    for _ in range(2):
        run.events.append(TraceEvent(
            event_type=EventType.tool_error,
            agent_id="coder_agent",
            phase="implement",
            data={"tool": "edit_files", "result": {"error": "permission_denied"}},
        ))
    sigs = mine_weaknesses(run, eval_result, harness)
    assert any(s.mechanism == Mechanism.REPEATED_FAILED_TOOL_CALL for s in sigs)


def test_single_tool_error_not_flagged(run_result, eval_result, harness):
    run = deepcopy(run_result)
    run.events.append(TraceEvent(
        event_type=EventType.tool_error,
        agent_id="coder_agent",
        phase="implement",
        data={"tool": "edit_files", "result": {"error": "permission_denied"}},
    ))
    sigs = mine_weaknesses(run, eval_result, harness)
    assert not any(s.mechanism == Mechanism.REPEATED_FAILED_TOOL_CALL for s in sigs)


# ---------------------------------------------------------------------------
# Excessive exploration classifier
# ---------------------------------------------------------------------------

def test_detects_excessive_exploration(harness, eval_result):
    run = RuntimeExecutor().run(harness)
    run.total_tool_calls = harness.runtime_policies.exploration_to_implementation_threshold + 5
    run.artifacts.pop("code_patch", None)
    sigs = mine_weaknesses(run, eval_result, harness)
    assert any(s.mechanism == Mechanism.EXCESSIVE_EXPLORATION for s in sigs)


def test_excessive_exploration_fires_even_with_patch(run_result, eval_result, harness):
    # Efficiency is flagged regardless of whether a patch was produced —
    # the budget mutation will tighten tool allowances to bring calls back down.
    run = deepcopy(run_result)
    run.total_tool_calls = harness.runtime_policies.exploration_to_implementation_threshold + 5
    sigs = mine_weaknesses(run, eval_result, harness)
    assert any(s.mechanism == Mechanism.EXCESSIVE_EXPLORATION for s in sigs)


# ---------------------------------------------------------------------------
# Wrong tool permission classifier
# ---------------------------------------------------------------------------

def test_detects_wrong_tool_permission(run_result, eval_result, harness):
    run = deepcopy(run_result)
    run.events.append(TraceEvent(
        event_type=EventType.tool_error,
        agent_id="requirements_agent",
        phase="understand",
        data={"tool": "edit_files", "result": {"error": "tool_not_permitted"}},
    ))
    sigs = mine_weaknesses(run, eval_result, harness)
    assert any(s.mechanism == Mechanism.WRONG_TOOL_PERMISSION for s in sigs)


def test_wrong_tool_permission_names_agent(run_result, eval_result, harness):
    run = deepcopy(run_result)
    run.events.append(TraceEvent(
        event_type=EventType.tool_error,
        agent_id="requirements_agent",
        phase="understand",
        data={"tool": "edit_files", "result": {"error": "tool_not_permitted"}},
    ))
    sigs = mine_weaknesses(run, eval_result, harness)
    # requirements_agent using edit_files is the injected sig we care about
    sig = next(
        s for s in sigs
        if s.mechanism == Mechanism.WRONG_TOOL_PERMISSION and s.agent_id == "requirements_agent"
    )
    assert sig.agent_id == "requirements_agent"


# ---------------------------------------------------------------------------
# Oversized patch classifier
# ---------------------------------------------------------------------------

def test_detects_oversized_patch(run_result, harness):
    from src.evaluation.scorer import EvaluationResult
    big_eval = EvaluationResult(
        run_id=run_result.run_id,
        harness_id=run_result.harness_id,
        harness_version=run_result.harness_version,
        raw_metrics={"diff_size": 200, "tests_pass": True, "feature_works": True,
                     "runtime_seconds": 1.0, "tool_calls": 5},
        total_score=90.0,
        passed_threshold=True,
    )
    sigs = mine_weaknesses(run_result, big_eval, harness)
    assert any(s.mechanism == Mechanism.OVERSIZED_PATCH for s in sigs)


def test_small_patch_not_flagged(run_result, eval_result, harness):
    sigs = mine_weaknesses(run_result, eval_result, harness)
    assert not any(s.mechanism == Mechanism.OVERSIZED_PATCH for s in sigs)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_signatures_are_deduplicated(harness, eval_result):
    run = RuntimeExecutor().run(harness)
    # inject three identical permission errors for the same agent + tool
    for _ in range(3):
        run.events.append(TraceEvent(
            event_type=EventType.tool_error,
            agent_id="requirements_agent",
            phase="understand",
            data={"tool": "edit_files", "result": {"error": "tool_not_permitted"}},
        ))
    sigs = mine_weaknesses(run, eval_result, harness)
    # requirements_agent + edit_files should collapse to exactly one signature
    perm_sigs = [
        s for s in sigs
        if s.mechanism == Mechanism.WRONG_TOOL_PERMISSION and s.agent_id == "requirements_agent"
    ]
    assert len(perm_sigs) == 1


# ---------------------------------------------------------------------------
# FailureSignature helpers
# ---------------------------------------------------------------------------

def test_signature_key_stable():
    sig = FailureSignature(
        verifier_cause="tests_failed",
        agent_behavior="coder_did_nothing",
        mechanism=Mechanism.WEAK_REQUIREMENTS_GROUNDING,
    )
    assert sig.signature_key() == "tests_failed|coder_did_nothing|weak_requirements_grounding"


def test_signature_to_dict():
    sig = FailureSignature(
        verifier_cause="vc", agent_behavior="ab", mechanism="m", agent_id="a1", detail="d"
    )
    d = sig.to_dict()
    assert d["verifier_cause"] == "vc"
    assert d["agent_id"] == "a1"
