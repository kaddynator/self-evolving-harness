from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.ir.schema import BinaryCheck, Evaluation, Metric, MetricType
from src.runtime.executor import RunResult


@dataclass
class BinaryCheckResult:
    check_id: str
    question: str
    verifier: str
    passed: bool
    detail: str = ""


@dataclass
class EvaluationResult:
    run_id: str
    harness_id: str
    harness_version: int
    raw_metrics: Dict[str, Any] = field(default_factory=dict)
    metric_scores: Dict[str, float] = field(default_factory=dict)
    binary_check_results: List[BinaryCheckResult] = field(default_factory=list)
    total_score: float = 0.0
    passed_threshold: bool = False
    success_threshold: float = 70.0


# ---------------------------------------------------------------------------
# Raw metric extraction
# ---------------------------------------------------------------------------

def _extract_raw_metrics(run: RunResult) -> Dict[str, Any]:
    """Pull concrete values out of the run result for each known metric."""
    test_results = run.artifacts.get("test_results", {})
    tests_passed = isinstance(test_results, dict) and test_results.get("failed", 1) == 0

    code_patch = run.artifacts.get("code_patch", "")
    diff_size = len(code_patch.splitlines()) if code_patch else 0

    review_notes = run.artifacts.get("review_notes", "")
    reviewer_accepted = isinstance(review_notes, str) and "approved" in review_notes.lower()

    return {
        "tests_pass": tests_passed,
        "feature_works": tests_passed,          # mock: proxy via test pass
        "reviewer_acceptance": reviewer_accepted,
        "tool_calls": run.total_tool_calls,
        "diff_size": diff_size,
        "runtime_seconds": run.elapsed_seconds,
    }


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

def _score_metric(metric: Metric, raw: Dict[str, Any]) -> float:
    value = raw.get(metric.name)
    if value is None:
        return 0.0

    if metric.type == MetricType.boolean:
        base = 1.0 if value else 0.0
    else:
        # numeric: raw count; weight handles direction (positive = better, negative = penalise)
        base = float(value)

    return base * metric.weight


def _run_binary_check(
    check: BinaryCheck,
    raw: Dict[str, Any],
    judge_verdicts: Optional[Dict[str, Any]] = None,
) -> BinaryCheckResult:
    """Binary checks. Uses LLM-judge verdicts when provided, else deterministic."""
    if check.verifier == "test_runner":
        passed = bool(raw.get("tests_pass", False))
        detail = "tests_pass metric" if passed else "tests failed"

    elif check.verifier == "generated_tests":
        passed = bool(raw.get("feature_works", False))
        detail = "feature_works metric" if passed else "feature did not work"

    elif check.verifier == "llm_judge":
        if judge_verdicts is not None and check.id in judge_verdicts:
            passed = bool(judge_verdicts[check.id])
            detail = f"llm_judge verdict: {'pass' if passed else 'fail'}"
        else:
            # Deterministic fallback: patch is minimal if diff_size <= 30 lines
            diff_size = raw.get("diff_size", 999)
            passed = diff_size <= 30
            detail = f"diff_size={diff_size} ({'ok' if passed else 'too large'})"

    else:
        passed = False
        detail = f"unknown verifier: {check.verifier}"

    return BinaryCheckResult(
        check_id=check.id,
        question=check.question,
        verifier=check.verifier,
        passed=passed,
        detail=detail,
    )


def score_against_expected(
    judge: Any,
    input_text: str,
    actual_output: str,
    expected_output: Optional[str],
) -> Dict[str, Any]:
    """Reference-grade an actual output against a human-approved expected output.

    Delegates to ``judge.grade_against_expected`` and returns its dict
    ``{"match", "score", "missing", "rationale"}``. Pure / side-effect free.

    Guard: if `judge` is None or `expected_output` is falsy (no reference to grade
    against), returns ``{"match": None, "score": None, "missing": [],
    "rationale": "no reference"}`` without calling the judge.
    """
    if judge is None or not expected_output:
        return {"match": None, "score": None, "missing": [], "rationale": "no reference"}

    return judge.grade_against_expected(input_text, actual_output, expected_output)


def score_run(
    run: RunResult,
    evaluation: Evaluation,
    *,
    judge: Any = None,
    harness: Any = None,
) -> EvaluationResult:
    """Compute metrics, binary checks, and weighted total score for a run.

    When `judge` and `harness` are provided, the judge's verdicts override the
    boolean signals the deterministic extractor cannot truly verify
    (feature_works, reviewer_acceptance, tests_pass) and drive llm_judge checks.
    With judge=None the behavior is unchanged (deterministic) — tests rely on this.
    """
    raw = _extract_raw_metrics(run)

    judge_verdicts: Optional[Dict[str, Any]] = None
    if judge is not None and harness is not None:
        try:
            verdict = judge.grade(run, harness)
            judge_verdicts = verdict.get("verdicts", {}) or {}
            for k in ("tests_pass", "feature_works", "reviewer_acceptance"):
                if k in judge_verdicts:
                    raw[k] = bool(judge_verdicts[k])
        except Exception:
            judge_verdicts = None

    metric_scores: Dict[str, float] = {}
    for metric in evaluation.metrics:
        metric_scores[metric.name] = _score_metric(metric, raw)

    total = sum(metric_scores.values())

    binary_results = [
        _run_binary_check(check, raw, judge_verdicts)
        for check in evaluation.binary_checks
    ]

    passed_threshold = total >= evaluation.scoring.success_threshold

    return EvaluationResult(
        run_id=run.run_id,
        harness_id=run.harness_id,
        harness_version=run.harness_version,
        raw_metrics=raw,
        metric_scores=metric_scores,
        binary_check_results=binary_results,
        total_score=total,
        passed_threshold=passed_threshold,
        success_threshold=evaluation.scoring.success_threshold,
    )
