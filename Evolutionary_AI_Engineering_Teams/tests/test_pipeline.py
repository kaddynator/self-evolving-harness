from pathlib import Path
from typing import List

import mongomock
import pytest

from src.ir.loader import load_harness
from src.ir.schema import OrganizationHarness
from src.memory.store import MongoMemoryStore
from src.pipeline import EvolutionPipeline, CycleResult
from src.weakness.signatures import Mechanism

EXAMPLE_SPEC = Path(__file__).parent.parent / "examples" / "organization_spec.yaml"


@pytest.fixture
def harness() -> OrganizationHarness:
    return load_harness(EXAMPLE_SPEC)


@pytest.fixture
def store() -> MongoMemoryStore:
    client = mongomock.MongoClient()
    return MongoMemoryStore(db=client["test_db"])


@pytest.fixture
def pipeline(store) -> EvolutionPipeline:
    return EvolutionPipeline(store)


@pytest.fixture
def cycle_result(pipeline, harness) -> CycleResult:
    return pipeline.run_cycle(harness)


# ---------------------------------------------------------------------------
# CycleResult structure
# ---------------------------------------------------------------------------

def test_cycle_result_type(cycle_result):
    assert isinstance(cycle_result, CycleResult)

def test_cycle_has_run(cycle_result):
    assert cycle_result.run is not None

def test_cycle_has_evaluation(cycle_result):
    assert cycle_result.evaluation is not None

def test_cycle_has_signatures_list(cycle_result):
    assert isinstance(cycle_result.signatures, list)

def test_cycle_has_proposals_list(cycle_result):
    assert isinstance(cycle_result.proposals, list)

def test_cycle_has_gate_decisions_list(cycle_result):
    assert isinstance(cycle_result.gate_decisions, list)

def test_proposals_and_decisions_same_length(cycle_result):
    assert len(cycle_result.proposals) == len(cycle_result.gate_decisions)


# ---------------------------------------------------------------------------
# MongoDB persistence after one cycle
# ---------------------------------------------------------------------------

def test_organization_persisted(cycle_result, store, harness):
    doc = store.get_organization(harness.organization.id)
    assert doc is not None

def test_run_persisted(cycle_result, store):
    doc = store.get_run(cycle_result.run.run_id)
    assert doc is not None

def test_evaluation_persisted(cycle_result, store):
    doc = store.get_evaluation(cycle_result.evaluation.run_id)
    assert doc is not None

def test_lesson_persisted(cycle_result, store, harness):
    lessons = store.get_lessons(harness.organization.id)
    assert len(lessons) >= 1

def test_mutations_persisted_when_proposals_exist(cycle_result, store):
    if not cycle_result.proposals:
        pytest.skip("no proposals generated this cycle")
    _, candidate = cycle_result.proposals[0]
    # Mutations stored under candidate harness id
    all_docs = list(store._db["mutations"].find({}))
    assert len(all_docs) >= 1


# ---------------------------------------------------------------------------
# Gate decisions
# ---------------------------------------------------------------------------

def test_gate_decision_has_accepted_field(cycle_result):
    for decision in cycle_result.gate_decisions:
        assert hasattr(decision, "accepted")

def test_accepted_candidate_is_harness_or_none(cycle_result):
    if cycle_result.accepted_candidate is not None:
        assert isinstance(cycle_result.accepted_candidate, OrganizationHarness)

def test_accepted_candidate_version_bumped(cycle_result, harness):
    if cycle_result.accepted_candidate is None:
        pytest.skip("no accepted candidate this cycle")
    assert cycle_result.accepted_candidate.organization.version > harness.organization.version

def test_accepted_candidate_parent_id(cycle_result, harness):
    if cycle_result.accepted_candidate is None:
        pytest.skip("no accepted candidate this cycle")
    assert cycle_result.accepted_candidate.organization.parent_id == harness.organization.id


# ---------------------------------------------------------------------------
# run_evolution
# ---------------------------------------------------------------------------

def test_evolution_returns_list(pipeline, harness):
    results = pipeline.run_evolution(harness, max_generations=2)
    assert isinstance(results, list)

def test_evolution_at_least_one_cycle(pipeline, harness):
    results = pipeline.run_evolution(harness, max_generations=1)
    assert len(results) == 1

def test_evolution_stops_without_improvement(pipeline, harness):
    # With mock agents, all runs succeed — if no candidate is accepted the loop ends.
    results = pipeline.run_evolution(harness, max_generations=5)
    assert len(results) >= 1  # at least the first cycle ran

def test_evolution_chains_accepted_candidate(pipeline, harness):
    results = pipeline.run_evolution(harness, max_generations=3)
    for i in range(1, len(results)):
        prev = results[i - 1]
        curr = results[i]
        if prev.accepted_candidate is not None:
            assert curr.harness.organization.id == prev.accepted_candidate.organization.id

def test_summary_after_evolution(pipeline, store, harness):
    pipeline.run_evolution(harness, max_generations=2)
    summary = store.run_summary(harness.organization.id)
    assert summary["total_runs"] >= 1
    assert summary["best_score"] is not None


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_cli_run_command(tmp_path):
    from cli import main
    rc = main(["run", str(EXAMPLE_SPEC)])
    assert rc == 0

def test_cli_evolve_command(tmp_path):
    from cli import main
    rc = main(["evolve", str(EXAMPLE_SPEC), "--generations", "1"])
    assert rc == 0

def test_cli_run_missing_file():
    from cli import main
    rc = main(["run", "nonexistent_harness.yaml"])
    assert rc == 1

def test_cli_evolve_missing_file():
    from cli import main
    rc = main(["evolve", "nonexistent.yaml"])
    assert rc == 1
