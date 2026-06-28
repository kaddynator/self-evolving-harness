from pathlib import Path
import pytest

from src.ir.loader import load_harness
from src.ir.schema import OrganizationHarness
from src.runtime.executor import RuntimeExecutor, RunResult
from src.evaluation.scorer import score_run, EvaluationResult
from src.evaluation.gate import apply_validation_gate, GateDecision

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
# Scorer — structure
# ---------------------------------------------------------------------------

def test_eval_result_type(eval_result):
    assert isinstance(eval_result, EvaluationResult)

def test_run_id_propagated(run_result, eval_result):
    assert eval_result.run_id == run_result.run_id

def test_harness_id_propagated(eval_result, harness):
    assert eval_result.harness_id == harness.organization.id

def test_all_metrics_scored(eval_result, harness):
    for metric in harness.evaluation.metrics:
        assert metric.name in eval_result.metric_scores

def test_all_binary_checks_run(eval_result, harness):
    check_ids = {r.check_id for r in eval_result.binary_check_results}
    expected_ids = {c.id for c in harness.evaluation.binary_checks}
    assert check_ids == expected_ids

def test_total_score_is_sum(eval_result):
    expected = sum(eval_result.metric_scores.values())
    assert abs(eval_result.total_score - expected) < 1e-9


# ---------------------------------------------------------------------------
# Scorer — values
# ---------------------------------------------------------------------------

def test_tests_pass_boolean_score(eval_result):
    # Mock run passes tests → tests_pass metric weight=50, score=50
    assert eval_result.metric_scores["tests_pass"] == 50.0

def test_feature_works_score(eval_result):
    assert eval_result.metric_scores["feature_works"] == 30.0

def test_reviewer_acceptance_score(eval_result):
    assert eval_result.metric_scores["reviewer_acceptance"] == 20.0

def test_tool_calls_penalised(eval_result):
    # weight=-1, tool_calls > 0  →  score is negative
    assert eval_result.metric_scores["tool_calls"] < 0

def test_diff_size_penalised(eval_result):
    assert eval_result.metric_scores["diff_size"] < 0

def test_raw_metrics_populated(eval_result):
    assert "tests_pass" in eval_result.raw_metrics
    assert "tool_calls" in eval_result.raw_metrics
    assert "runtime_seconds" in eval_result.raw_metrics

def test_passed_threshold(eval_result, harness):
    expected = eval_result.total_score >= harness.evaluation.scoring.success_threshold
    assert eval_result.passed_threshold == expected


# ---------------------------------------------------------------------------
# Binary checks
# ---------------------------------------------------------------------------

def test_binary_check_test_runner(eval_result):
    result = next(r for r in eval_result.binary_check_results if r.verifier == "test_runner")
    assert result.passed is True

def test_binary_check_generated_tests(eval_result):
    result = next(r for r in eval_result.binary_check_results if r.verifier == "generated_tests")
    assert result.passed is True

def test_binary_check_llm_judge_small_patch(eval_result):
    result = next(r for r in eval_result.binary_check_results if r.verifier == "llm_judge")
    # mock diff is ~3 lines — should be considered minimal
    assert result.passed is True


# ---------------------------------------------------------------------------
# Validation gate — first run
# ---------------------------------------------------------------------------

def test_gate_first_run_accepted(eval_result, harness):
    decision = apply_validation_gate(eval_result, parent=None, gate=harness.evaluation.validation_gate)
    assert isinstance(decision, GateDecision)
    assert decision.accepted is True

def test_gate_first_run_below_threshold_rejected(harness):
    from src.evaluation.scorer import EvaluationResult
    low_score = EvaluationResult(
        run_id="x", harness_id="y", harness_version=1,
        raw_metrics={"runtime_seconds": 1.0},
        total_score=10.0,
        passed_threshold=False,
        success_threshold=70.0,
    )
    decision = apply_validation_gate(low_score, parent=None, gate=harness.evaluation.validation_gate)
    assert decision.accepted is False


# ---------------------------------------------------------------------------
# Validation gate — candidate vs parent
# ---------------------------------------------------------------------------

def test_gate_improvement_accepted(eval_result, harness):
    # Candidate has higher total_score than parent — should be accepted
    from copy import deepcopy
    parent = deepcopy(eval_result)
    parent.total_score = eval_result.total_score - 5
    candidate = eval_result
    decision = apply_validation_gate(candidate, parent=parent, gate=harness.evaluation.validation_gate)
    assert decision.accepted is True
    assert "total_score" in decision.improvements

def test_gate_regression_rejected(eval_result, harness):
    from copy import deepcopy
    parent = deepcopy(eval_result)
    # Make candidate look like it broke tests
    candidate = deepcopy(eval_result)
    candidate.raw_metrics["tests_pass"] = False  # regression
    # Force parent to True
    parent.raw_metrics["tests_pass"] = True
    decision = apply_validation_gate(candidate, parent=parent, gate=harness.evaluation.validation_gate)
    assert decision.accepted is False
    assert "tests_pass" in decision.regressions

def test_gate_no_improvement_rejected(eval_result, harness):
    from copy import deepcopy
    parent = deepcopy(eval_result)
    candidate = deepcopy(eval_result)
    # Same score, same tool_calls, same runtime → no improvement
    decision = apply_validation_gate(candidate, parent=parent, gate=harness.evaluation.validation_gate)
    assert decision.accepted is False

def test_gate_runtime_exceeded_rejected(eval_result, harness):
    from copy import deepcopy
    candidate = deepcopy(eval_result)
    candidate.raw_metrics["runtime_seconds"] = 9999.0
    decision = apply_validation_gate(candidate, parent=eval_result, gate=harness.evaluation.validation_gate)
    assert decision.accepted is False
    assert "runtime" in decision.reason

def test_gate_tool_calls_improvement(eval_result, harness):
    from copy import deepcopy
    parent = deepcopy(eval_result)
    parent.raw_metrics["tool_calls"] = eval_result.raw_metrics["tool_calls"] + 5
    candidate = eval_result
    decision = apply_validation_gate(candidate, parent=parent, gate=harness.evaluation.validation_gate)
    assert decision.accepted is True
    assert "tool_calls" in decision.improvements
