from pathlib import Path
import pytest
import mongomock

from src.ir.loader import load_harness
from src.ir.schema import OrganizationHarness
from src.runtime.executor import RuntimeExecutor, RunResult
from src.evaluation.scorer import score_run, EvaluationResult
from src.evaluation.gate import apply_validation_gate, GateDecision
from src.memory.store import MongoMemoryStore
from src.memory.serializers import harness_to_doc, run_to_doc, eval_to_doc

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


@pytest.fixture
def store() -> MongoMemoryStore:
    client = mongomock.MongoClient()
    return MongoMemoryStore(db=client["test_db"])


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

def test_save_and_get_organization(store, harness):
    org_id = store.save_organization(harness)
    assert org_id == harness.organization.id
    doc = store.get_organization(org_id)
    assert doc is not None
    assert doc["organization"]["id"] == harness.organization.id

def test_save_organization_idempotent(store, harness):
    store.save_organization(harness)
    store.save_organization(harness)  # upsert — should not error or duplicate
    # mongomock counts
    count = store._db["organizations"].count_documents({"_id": harness.organization.id})
    assert count == 1

def test_get_missing_organization(store):
    assert store.get_organization("does_not_exist") is None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def test_save_and_get_run(store, run_result):
    run_id = store.save_run(run_result)
    assert run_id == run_result.run_id
    doc = store.get_run(run_id)
    assert doc is not None
    assert doc["harness_id"] == run_result.harness_id

def test_run_doc_has_events(store, run_result):
    store.save_run(run_result)
    doc = store.get_run(run_result.run_id)
    assert len(doc["events"]) > 0

def test_run_doc_has_artifacts(store, run_result):
    store.save_run(run_result)
    doc = store.get_run(run_result.run_id)
    assert "code_patch" in doc["artifacts"]

def test_get_runs_for_harness(store, harness, run_result):
    store.save_run(run_result)
    runs = store.get_runs_for_harness(harness.organization.id)
    assert len(runs) == 1
    assert runs[0]["harness_id"] == harness.organization.id

def test_get_run_missing(store):
    assert store.get_run("no_such_run") is None


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------

def test_save_and_get_evaluation(store, eval_result):
    run_id = store.save_evaluation(eval_result)
    assert run_id == eval_result.run_id
    doc = store.get_evaluation(run_id)
    assert doc is not None
    assert doc["total_score"] == eval_result.total_score

def test_evaluation_doc_has_binary_checks(store, eval_result):
    store.save_evaluation(eval_result)
    doc = store.get_evaluation(eval_result.run_id)
    assert len(doc["binary_check_results"]) > 0

def test_get_best_score(store, harness, eval_result):
    store.save_evaluation(eval_result)
    best = store.get_best_score(harness.organization.id)
    assert best == eval_result.total_score

def test_get_best_score_missing(store):
    assert store.get_best_score("unknown_harness") is None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def test_save_accepted_mutation(store, harness, run_result, eval_result):
    decision = GateDecision(accepted=True, reason="improved", improvements=["total_score"])
    store.save_mutation(run_result.run_id, harness.organization.id, 1, decision)
    accepted = store.get_accepted_mutations(harness.organization.id)
    assert len(accepted) == 1
    assert accepted[0]["accepted"] is True

def test_save_rejected_mutation(store, harness, run_result):
    decision = GateDecision(accepted=False, reason="regression", regressions=["tests_pass"])
    store.save_mutation(run_result.run_id, harness.organization.id, 1, decision)
    rejected = store.get_rejected_mutations(harness.organization.id)
    assert len(rejected) == 1
    assert "tests_pass" in rejected[0]["regressions"]

def test_mutation_stores_parent_run_id(store, harness, run_result):
    decision = GateDecision(accepted=True, reason="ok", improvements=["total_score"])
    store.save_mutation(run_result.run_id, harness.organization.id, 1, decision, parent_run_id="parent-xyz")
    doc = store._db["mutations"].find_one({"_id": run_result.run_id})
    assert doc["parent_run_id"] == "parent-xyz"

def test_empty_mutations(store, harness):
    assert store.get_accepted_mutations(harness.organization.id) == []
    assert store.get_rejected_mutations(harness.organization.id) == []


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------

def test_save_and_get_lesson(store, harness, run_result):
    sigs = [{"verifier_cause": "tests_failed", "agent_behavior": "coder_overwrite", "mechanism": "missing_grounding"}]
    store.save_lesson(harness.organization.id, run_result.run_id, sigs, accepted=False)
    lessons = store.get_lessons(harness.organization.id)
    assert len(lessons) == 1
    assert lessons[0]["failure_signatures"] == sigs

def test_multiple_lessons_accumulate(store, harness, run_result):
    for i in range(3):
        store.save_lesson(harness.organization.id, f"run_{i}", [], accepted=True)
    lessons = store.get_lessons(harness.organization.id)
    assert len(lessons) == 3

def test_get_lessons_empty(store, harness):
    assert store.get_lessons(harness.organization.id) == []


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_run_summary(store, harness, run_result, eval_result):
    store.save_run(run_result)
    store.save_evaluation(eval_result)
    decision = GateDecision(accepted=True, reason="ok", improvements=["total_score"])
    store.save_mutation(run_result.run_id, harness.organization.id, 1, decision)
    store.save_lesson(harness.organization.id, run_result.run_id, [], accepted=True)

    summary = store.run_summary(harness.organization.id)
    assert summary["total_runs"] == 1
    assert summary["best_score"] == eval_result.total_score
    assert summary["accepted_mutations"] == 1
    assert len(summary["lessons"]) == 1

def test_run_summary_empty(store, harness):
    summary = store.run_summary(harness.organization.id)
    assert summary["total_runs"] == 0
    assert summary["best_score"] is None
    assert summary["accepted_mutations"] == 0


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def test_harness_to_doc_has_id(harness):
    doc = harness_to_doc(harness)
    assert doc["_id"] == harness.organization.id

def test_run_to_doc_shape(run_result):
    doc = run_to_doc(run_result)
    assert doc["_id"] == run_result.run_id
    assert "events" in doc
    assert "artifacts" in doc

def test_eval_to_doc_shape(eval_result):
    doc = eval_to_doc(eval_result)
    assert doc["_id"] == eval_result.run_id
    assert "metric_scores" in doc
    assert "binary_check_results" in doc
