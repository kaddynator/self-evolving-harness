import pytest
from pathlib import Path

from src.ir.loader import load_harness, load_harness_from_dict
from src.ir.schema import OrganizationHarness, EdgeType, MutationType

EXAMPLE_SPEC = Path(__file__).parent.parent / "examples" / "organization_spec.yaml"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_load_example_spec():
    harness = load_harness(EXAMPLE_SPEC)
    assert isinstance(harness, OrganizationHarness)

def test_organization_fields():
    h = load_harness(EXAMPLE_SPEC)
    assert h.organization.id == "org_rate_limiter_v1"
    assert h.organization.version == 1
    assert h.organization.parent_id is None

def test_agents_loaded():
    h = load_harness(EXAMPLE_SPEC)
    assert len(h.agents) == 4
    ids = {a.id for a in h.agents}
    assert ids == {"requirements_agent", "coder_agent", "tester_agent", "reviewer_agent"}

def test_agent_by_id():
    h = load_harness(EXAMPLE_SPEC)
    coder = h.agent_by_id("coder_agent")
    assert coder.name == "Coder Agent"
    assert "edit_files" in coder.tools

def test_agent_by_id_missing():
    h = load_harness(EXAMPLE_SPEC)
    with pytest.raises(KeyError):
        h.agent_by_id("nonexistent_agent")

def test_communication_edges():
    h = load_harness(EXAMPLE_SPEC)
    edge_types = {e.type for e in h.communication.edges}
    assert EdgeType.blocking in edge_types
    assert EdgeType.feedback in edge_types

def test_execution_phases():
    h = load_harness(EXAMPLE_SPEC)
    phase_names = [p.name for p in h.execution.phases]
    assert phase_names == ["understand", "implement", "verify"]
    verify = next(p for p in h.execution.phases if p.name == "verify")
    assert verify.parallel is True

def test_evaluation_metrics():
    h = load_harness(EXAMPLE_SPEC)
    metric_names = {m.name for m in h.evaluation.metrics}
    assert "tests_pass" in metric_names
    assert "tool_calls" in metric_names

def test_validation_gate_protected():
    h = load_harness(EXAMPLE_SPEC)
    gate = h.evaluation.validation_gate
    assert "tests_pass" in gate.require_no_regression
    assert "feature_works" in gate.require_no_regression

def test_mutation_policy():
    h = load_harness(EXAMPLE_SPEC)
    assert MutationType.add_agent in h.mutation_policy.allowed_mutations
    assert "task.success_conditions" in h.mutation_policy.protected_components
    assert "evaluation.validation_gate" in h.mutation_policy.protected_components

def test_runtime_policies():
    h = load_harness(EXAMPLE_SPEC)
    rp = h.runtime_policies
    assert rp.require_artifact_before_finish is True
    assert rp.prevent_identical_retry is True
    assert rp.max_repeated_tool_errors == 2

def test_weakness_mining_defaults():
    h = load_harness(EXAMPLE_SPEC)
    wm = h.weakness_mining
    assert wm.enabled is True
    assert "verifier_cause" in wm.failure_signature_fields


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_missing_file():
    with pytest.raises(FileNotFoundError):
        load_harness("does_not_exist.yaml")

def test_empty_agents_rejected():
    import yaml
    raw = yaml.safe_load(EXAMPLE_SPEC.read_text())
    raw["agents"] = []
    with pytest.raises(ValueError, match="agents list must not be empty"):
        load_harness_from_dict(raw)

def test_empty_phases_rejected():
    import yaml
    raw = yaml.safe_load(EXAMPLE_SPEC.read_text())
    raw["execution"]["phases"] = []
    with pytest.raises(ValueError, match="phases must not be empty"):
        load_harness_from_dict(raw)

def test_missing_required_field():
    import yaml
    raw = yaml.safe_load(EXAMPLE_SPEC.read_text())
    del raw["task"]["success_conditions"]
    with pytest.raises(ValueError):
        load_harness_from_dict(raw)

def test_unknown_agent_in_phase_rejected():
    import yaml
    raw = yaml.safe_load(EXAMPLE_SPEC.read_text())
    raw["execution"]["phases"][0]["agents"] = ["ghost_agent"]
    with pytest.raises(ValueError, match="unknown agent"):
        load_harness_from_dict(raw)

def test_unknown_agent_in_edge_rejected():
    import yaml
    raw = yaml.safe_load(EXAMPLE_SPEC.read_text())
    raw["communication"]["edges"][0]["from"] = "ghost_agent"
    with pytest.raises(ValueError, match="unknown agent"):
        load_harness_from_dict(raw)

def test_empty_metrics_rejected():
    import yaml
    raw = yaml.safe_load(EXAMPLE_SPEC.read_text())
    raw["evaluation"]["metrics"] = []
    with pytest.raises(ValueError, match="metrics must not be empty"):
        load_harness_from_dict(raw)
