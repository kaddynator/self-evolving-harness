from pathlib import Path
from copy import deepcopy
from typing import List

import pytest

from src.ir.loader import load_harness
from src.ir.schema import OrganizationHarness
from src.runtime.executor import RuntimeExecutor, RunResult
from src.evaluation.scorer import score_run, EvaluationResult
from src.weakness.miner import mine_weaknesses
from src.weakness.signatures import FailureSignature, Mechanism
from src.evolution.engine import propose_mutations
from src.evolution.proposals import MutationProposal
from src.evolution import mutators

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


def _sig(mechanism: str, agent_id: str = None, behavior: str = "some_behavior") -> FailureSignature:
    return FailureSignature(
        verifier_cause="vc",
        agent_behavior=behavior,
        mechanism=mechanism,
        agent_id=agent_id,
    )


# ---------------------------------------------------------------------------
# propose_mutations basics
# ---------------------------------------------------------------------------

def test_returns_list(harness):
    pairs = propose_mutations(harness, [])
    assert isinstance(pairs, list)

def test_no_signatures_no_proposals(harness):
    pairs = propose_mutations(harness, [])
    assert pairs == []

def test_proposal_width_respected(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)] * 10
    pairs = propose_mutations(harness, sigs)
    assert len(pairs) <= harness.mutation_policy.proposal_width

def test_max_proposals_override(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)] * 10
    pairs = propose_mutations(harness, sigs, max_proposals=1)
    assert len(pairs) == 1

def test_returns_tuple_pairs(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)]
    pairs = propose_mutations(harness, sigs)
    assert len(pairs) > 0
    proposal, candidate = pairs[0]
    assert isinstance(proposal, MutationProposal)
    assert isinstance(candidate, OrganizationHarness)


# ---------------------------------------------------------------------------
# Candidate harness validity
# ---------------------------------------------------------------------------

def test_candidate_version_bumped(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)]
    _, candidate = propose_mutations(harness, sigs)[0]
    assert candidate.organization.version == harness.organization.version + 1

def test_candidate_parent_id_set(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)]
    _, candidate = propose_mutations(harness, sigs)[0]
    assert candidate.organization.parent_id == harness.organization.id

def test_candidate_is_valid_harness(harness):
    sigs = [_sig(Mechanism.WRONG_TOOL_PERMISSION, agent_id="requirements_agent",
                 behavior="agent_used_unpermitted_tool:edit_files")]
    pairs = propose_mutations(harness, sigs)
    for _, candidate in pairs:
        assert isinstance(candidate, OrganizationHarness)


# ---------------------------------------------------------------------------
# Proposal metadata
# ---------------------------------------------------------------------------

def test_proposal_has_id(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)]
    proposal, _ = propose_mutations(harness, sigs)[0]
    assert proposal.proposal_id.startswith("proposal_")

def test_proposal_links_parent_and_candidate(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    assert proposal.parent_org_id == harness.organization.id
    assert proposal.candidate_org_id == candidate.organization.id

def test_proposal_to_dict_shape(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)]
    proposal, _ = propose_mutations(harness, sigs)[0]
    d = proposal.to_dict()
    for key in ("proposal_id", "parent_org_id", "candidate_org_id",
                "mutation_type", "target_failure_signature",
                "changed_surfaces", "expected_effect",
                "regression_risk", "rollback_plan"):
        assert key in d


# ---------------------------------------------------------------------------
# Per-mechanism rules
# ---------------------------------------------------------------------------

def test_weak_requirements_modifies_prompt(harness):
    sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING)]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    req_parent = harness.agent_by_id("requirements_agent").prompt
    req_candidate = candidate.agent_by_id("requirements_agent").prompt
    assert req_candidate != req_parent
    assert proposal.mutation_type == "modify_prompt"

def test_missing_artifact_modifies_runtime_policy(harness):
    sigs = [_sig(Mechanism.MISSING_REQUIRED_ARTIFACT)]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    assert proposal.mutation_type == "modify_runtime_policy"
    assert candidate.runtime_policies.require_artifact_before_finish is True

def test_wrong_tool_permission_adds_tool(harness):
    sigs = [_sig(Mechanism.WRONG_TOOL_PERMISSION,
                 agent_id="requirements_agent",
                 behavior="agent_used_unpermitted_tool:edit_files")]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    assert proposal.mutation_type == "modify_tools"
    assert "edit_files" in candidate.agent_by_id("requirements_agent").tools

def test_excessive_exploration_tightens_budget(harness):
    sigs = [_sig(Mechanism.EXCESSIVE_EXPLORATION)]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    assert proposal.mutation_type == "adjust_budget"
    coder = candidate.agent_by_id("coder_agent")
    assert coder.budget.max_tool_calls <= harness.runtime_policies.exploration_to_implementation_threshold

def test_repeated_tool_error_modifies_runtime_policy(harness):
    sigs = [_sig(Mechanism.REPEATED_FAILED_TOOL_CALL)]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    assert proposal.mutation_type == "modify_runtime_policy"
    assert candidate.runtime_policies.prevent_identical_retry is True

def test_oversized_patch_modifies_coder_prompt(harness):
    sigs = [_sig(Mechanism.OVERSIZED_PATCH)]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    assert proposal.mutation_type == "modify_prompt"
    assert "30 lines" in candidate.agent_by_id("coder_agent").prompt

def test_unverified_completion_adds_verifier_agent(harness):
    sigs = [_sig(Mechanism.UNVERIFIED_COMPLETION)]
    proposal, candidate = propose_mutations(harness, sigs)[0]
    assert proposal.mutation_type == "add_agent"
    agent_ids = {a.id for a in candidate.agents}
    assert "verifier_agent" in agent_ids

def test_late_testing_reorders_edge(harness):
    sigs = [_sig(Mechanism.LATE_TESTING)]
    pairs = propose_mutations(harness, sigs)
    assert len(pairs) > 0
    proposal, _ = pairs[0]
    assert proposal.mutation_type == "reorder_edges"


# ---------------------------------------------------------------------------
# Mutator unit tests
# ---------------------------------------------------------------------------

def test_modify_prompt_changes_only_target_agent(harness):
    candidate, surfaces = mutators.modify_prompt(harness, "coder_agent", "NEW PROMPT")
    assert candidate.agent_by_id("coder_agent").prompt == "NEW PROMPT"
    # Other agents unchanged
    assert candidate.agent_by_id("requirements_agent").prompt == harness.agent_by_id("requirements_agent").prompt

def test_modify_tools_add(harness):
    candidate, _ = mutators.modify_tools(harness, "requirements_agent", add_tools=["run_tests"])
    assert "run_tests" in candidate.agent_by_id("requirements_agent").tools

def test_modify_tools_remove(harness):
    candidate, _ = mutators.modify_tools(harness, "coder_agent", remove_tools=["git_diff"])
    assert "git_diff" not in candidate.agent_by_id("coder_agent").tools

def test_adjust_budget(harness):
    candidate, _ = mutators.adjust_budget(harness, "coder_agent", max_tool_calls=5)
    assert candidate.agent_by_id("coder_agent").budget.max_tool_calls == 5

def test_remove_agent_drops_from_phases(harness):
    candidate, _ = mutators.remove_agent(harness, "reviewer_agent")
    ids = {a.id for a in candidate.agents}
    assert "reviewer_agent" not in ids
    for phase in candidate.execution.phases:
        assert "reviewer_agent" not in phase.agents

def test_remove_agent_drops_edges(harness):
    candidate, _ = mutators.remove_agent(harness, "reviewer_agent")
    for edge in candidate.communication.edges:
        assert edge.from_agent != "reviewer_agent"
        assert edge.to != "reviewer_agent"

def test_modify_runtime_policy(harness):
    candidate, _ = mutators.modify_runtime_policy(harness, max_repeated_tool_errors=1)
    assert candidate.runtime_policies.max_repeated_tool_errors == 1

def test_reorder_edges(harness):
    candidate, _ = mutators.reorder_edges(harness, "coder_agent", "tester_agent", "blocking")
    edge = next(
        e for e in candidate.communication.edges
        if e.from_agent == "coder_agent" and e.to == "tester_agent"
    )
    assert edge.type.value == "blocking"

def test_clone_does_not_mutate_original(harness):
    original_prompt = harness.agent_by_id("coder_agent").prompt
    mutators.modify_prompt(harness, "coder_agent", "CHANGED")
    assert harness.agent_by_id("coder_agent").prompt == original_prompt
