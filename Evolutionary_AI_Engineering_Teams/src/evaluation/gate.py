from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.ir.schema import ValidationGate
from src.evaluation.scorer import EvaluationResult


@dataclass
class GateDecision:
    accepted: bool
    reason: str
    regressions: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)


def apply_validation_gate(
    candidate: EvaluationResult,
    parent: Optional[EvaluationResult],
    gate: ValidationGate,
) -> GateDecision:
    """Decide whether to accept a candidate harness mutation.

    Rules (from the IR spec):
    1. No regression on any require_no_regression metric.
    2. At least one require_improvement_any metric must improve.
    3. Candidate must finish within max_runtime_seconds.

    If parent is None (first run), we only check the threshold — there is
    nothing to regress against yet.
    """
    # --- Runtime budget ---
    runtime = candidate.raw_metrics.get("runtime_seconds", 0.0)
    if runtime > gate.max_runtime_seconds:
        return GateDecision(
            accepted=False,
            reason=f"runtime {runtime:.1f}s exceeded limit {gate.max_runtime_seconds}s",
        )

    # --- First run: accept if it passes threshold ---
    if parent is None:
        if candidate.passed_threshold:
            return GateDecision(
                accepted=True,
                reason="first run; passed success threshold",
                improvements=["total_score"],
            )
        return GateDecision(
            accepted=False,
            reason=f"first run; score {candidate.total_score:.1f} below threshold {candidate.success_threshold}",
        )

    # --- Regression check ---
    regressions: List[str] = []
    for metric_name in gate.require_no_regression:
        parent_val = _get_comparable(parent, metric_name)
        cand_val = _get_comparable(candidate, metric_name)
        if cand_val is not None and parent_val is not None and cand_val < parent_val:
            regressions.append(metric_name)

    if regressions:
        return GateDecision(
            accepted=False,
            reason=f"regression detected on: {', '.join(regressions)}",
            regressions=regressions,
        )

    # --- Improvement check ---
    improvements: List[str] = []
    for metric_name in gate.require_improvement_any:
        parent_val = _get_comparable(parent, metric_name)
        cand_val = _get_comparable(candidate, metric_name)
        if cand_val is not None and parent_val is not None:
            # For tool_calls and runtime_seconds, lower is better
            if metric_name in ("tool_calls", "runtime_seconds"):
                if cand_val < parent_val:
                    improvements.append(metric_name)
            else:
                if cand_val > parent_val:
                    improvements.append(metric_name)

    if not improvements:
        return GateDecision(
            accepted=False,
            reason="no improvement detected on any required metric",
            regressions=[],
            improvements=[],
        )

    return GateDecision(
        accepted=True,
        reason=f"no regressions; improved: {', '.join(improvements)}",
        regressions=[],
        improvements=improvements,
    )


def _get_comparable(ev: EvaluationResult, metric_name: str) -> Optional[float]:
    """Return a float value for gate comparison.

    Booleans become 1.0/0.0; numeric metrics return raw value.
    total_score is handled specially.
    """
    if metric_name == "total_score":
        return ev.total_score

    raw = ev.raw_metrics.get(metric_name)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    return float(raw)
