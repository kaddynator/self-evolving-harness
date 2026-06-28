from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from src.ir.schema import OrganizationHarness
from src.runtime.executor import RunResult
from src.runtime.events import TraceEvent
from src.evaluation.scorer import EvaluationResult
from src.evaluation.gate import GateDecision


def harness_to_doc(harness: OrganizationHarness) -> Dict[str, Any]:
    doc = harness.model_dump(mode="json")
    doc["_id"] = harness.organization.id
    return doc


def run_to_doc(run: RunResult) -> Dict[str, Any]:
    return {
        "_id": run.run_id,
        "harness_id": run.harness_id,
        "harness_version": run.harness_version,
        "success": run.success,
        "stop_reason": run.stop_reason,
        "total_tool_calls": run.total_tool_calls,
        "elapsed_seconds": run.elapsed_seconds,
        "artifacts": run.artifacts,
        "events": [_event_to_dict(e) for e in run.events],
    }


def eval_to_doc(ev: EvaluationResult) -> Dict[str, Any]:
    return {
        "_id": ev.run_id,
        "harness_id": ev.harness_id,
        "harness_version": ev.harness_version,
        "raw_metrics": ev.raw_metrics,
        "metric_scores": ev.metric_scores,
        "binary_check_results": [asdict(r) for r in ev.binary_check_results],
        "total_score": ev.total_score,
        "passed_threshold": ev.passed_threshold,
        "success_threshold": ev.success_threshold,
    }


def gate_decision_to_doc(
    run_id: str,
    harness_id: str,
    harness_version: int,
    decision: GateDecision,
    parent_run_id: str | None = None,
) -> Dict[str, Any]:
    return {
        "_id": run_id,
        "harness_id": harness_id,
        "harness_version": harness_version,
        "parent_run_id": parent_run_id,
        "accepted": decision.accepted,
        "reason": decision.reason,
        "regressions": decision.regressions,
        "improvements": decision.improvements,
    }


def lesson_doc(
    harness_id: str,
    run_id: str,
    failure_signatures: List[Dict[str, Any]],
    accepted: bool,
) -> Dict[str, Any]:
    return {
        "harness_id": harness_id,
        "run_id": run_id,
        "failure_signatures": failure_signatures,
        "accepted": accepted,
    }


def _event_to_dict(e: TraceEvent) -> Dict[str, Any]:
    return {
        "event_type": e.event_type.value,
        "agent_id": e.agent_id,
        "phase": e.phase,
        "elapsed_seconds": e.elapsed_seconds,
        "data": e.data,
    }
