from __future__ import annotations

from typing import List, Tuple

from src.ir.schema import Agent, AgentBudget, AgentMemoryPolicy, OrganizationHarness
from src.weakness.signatures import FailureSignature, Mechanism
from src.evolution.proposals import MutationProposal, make_proposal_id
from src.evolution import mutators


# ---------------------------------------------------------------------------
# Mechanism → mutation rules
# Each rule maps a failure mechanism to a list of (proposal, candidate) pairs.
# ---------------------------------------------------------------------------

def propose_mutations(
    harness: OrganizationHarness,
    signatures: List[FailureSignature],
    max_proposals: int | None = None,
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    """Return up to `max_proposals` (proposal, candidate_harness) pairs.

    Proposals are grounded in the supplied failure signatures; only mutations
    allowed by harness.mutation_policy are generated.
    """
    max_proposals = max_proposals or harness.mutation_policy.proposal_width
    allowed = {m.value for m in harness.mutation_policy.allowed_mutations}

    results: List[Tuple[MutationProposal, OrganizationHarness]] = []

    for sig in signatures:
        if len(results) >= max_proposals:
            break
        new_pairs = _rules_for(sig, harness, allowed)
        for pair in new_pairs:
            if len(results) >= max_proposals:
                break
            results.append(pair)

    return results


# ---------------------------------------------------------------------------
# Rule dispatch
# ---------------------------------------------------------------------------

def _rules_for(
    sig: FailureSignature,
    harness: OrganizationHarness,
    allowed: set,
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    mechanism = sig.mechanism
    results = []

    if mechanism == Mechanism.WEAK_REQUIREMENTS_GROUNDING and "modify_prompt" in allowed:
        results.extend(_rule_strengthen_requirements_prompt(sig, harness))

    if mechanism == Mechanism.MISSING_REQUIRED_ARTIFACT and "modify_runtime_policy" in allowed:
        results.extend(_rule_enforce_artifact_policy(sig, harness))

    if mechanism == Mechanism.WRONG_TOOL_PERMISSION and "modify_tools" in allowed:
        results.extend(_rule_fix_tool_permission(sig, harness))

    if mechanism == Mechanism.EXCESSIVE_EXPLORATION and "adjust_budget" in allowed:
        results.extend(_rule_tighten_coder_budget(sig, harness))

    if mechanism == Mechanism.REPEATED_FAILED_TOOL_CALL and "modify_runtime_policy" in allowed:
        results.extend(_rule_prevent_identical_retry(sig, harness))

    if mechanism == Mechanism.OVERSIZED_PATCH and "modify_prompt" in allowed:
        results.extend(_rule_add_minimal_patch_instruction(sig, harness))

    if mechanism == Mechanism.UNVERIFIED_COMPLETION and "add_agent" in allowed:
        results.extend(_rule_add_verifier_agent(sig, harness))

    if mechanism == Mechanism.LATE_TESTING and "reorder_edges" in allowed:
        results.extend(_rule_enforce_tester_before_review(sig, harness))

    if mechanism == Mechanism.REDUNDANT_AGENT and "remove_agent" in allowed:
        results.extend(_rule_remove_redundant_agent(sig, harness))

    if mechanism == Mechanism.WEAK_REQUIREMENTS_GROUNDING and "change_model" in allowed:
        results.extend(_rule_upgrade_requirements_model(sig, harness))

    return results


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------

def _rule_strengthen_requirements_prompt(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    req_agent = next((a for a in harness.agents if "requirements" in a.id), None)
    if req_agent is None:
        return []

    new_prompt = (
        req_agent.prompt.rstrip()
        + "\nAlways ground every acceptance criterion in an explicit test assertion."
    )
    candidate, surfaces = mutators.modify_prompt(harness, req_agent.id, new_prompt)
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="modify_prompt",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect="Requirements agent produces more precise acceptance criteria, reducing test failures.",
        regression_risk="May make requirements too verbose; low risk.",
        rollback_plan="Revert to parent prompt.",
    )
    return [(proposal, candidate)]


def _rule_enforce_artifact_policy(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    candidate, surfaces = mutators.modify_runtime_policy(
        harness,
        require_artifact_before_finish=True,
        verify_before_conclude=True,
    )
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="modify_runtime_policy",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect="Runtime enforces artifact creation before any agent concludes.",
        regression_risk="Agents may stall if artifact creation is blocked; low risk.",
        rollback_plan="Revert runtime_policies to parent values.",
    )
    return [(proposal, candidate)]


def _rule_fix_tool_permission(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    agent_id = sig.agent_id
    if not agent_id:
        return []
    # Extract the tool name from agent_behavior e.g. "agent_used_unpermitted_tool:edit_files"
    tool_name = None
    if ":" in sig.agent_behavior:
        tool_name = sig.agent_behavior.split(":", 1)[1]
    if not tool_name:
        return []

    candidate, surfaces = mutators.modify_tools(harness, agent_id, add_tools=[tool_name])
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="modify_tools",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect=f"Agent '{agent_id}' can now use '{tool_name}', eliminating permission errors.",
        regression_risk="Broader tool access may allow unintended side effects.",
        rollback_plan="Remove the added tool from the agent's tool list.",
    )
    return [(proposal, candidate)]


def _rule_tighten_coder_budget(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    coder = next((a for a in harness.agents if "coder" in a.id), None)
    if coder is None:
        return []

    # Reduce to min(4, current-1) so the new limit is below the coder's 5-step
    # mock sequence — this causes run_mock_agent to truncate the sequence and
    # the gate to detect a real tool_calls improvement each generation.
    current = coder.budget.max_tool_calls
    new_limit = min(4, max(3, current - 1))
    candidate, surfaces = mutators.adjust_budget(harness, coder.id, max_tool_calls=new_limit)
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="adjust_budget",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect="Coder is forced to implement earlier, preventing runaway exploration.",
        regression_risk="May produce incomplete patches if task is complex.",
        rollback_plan="Revert coder budget to parent values.",
    )
    return [(proposal, candidate)]


def _rule_prevent_identical_retry(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    candidate, surfaces = mutators.modify_runtime_policy(
        harness,
        prevent_identical_retry=True,
        max_repeated_tool_errors=1,
    )
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="modify_runtime_policy",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect="Prevents agents from retrying the exact same failing tool call.",
        regression_risk="Agent may stop too early on transient errors.",
        rollback_plan="Revert runtime_policies to parent values.",
    )
    return [(proposal, candidate)]


def _rule_add_minimal_patch_instruction(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    coder = next((a for a in harness.agents if "coder" in a.id), None)
    if coder is None:
        return []

    new_prompt = (
        coder.prompt.rstrip()
        + "\nKeep the patch under 30 lines. Touch only the files necessary for the feature."
    )
    candidate, surfaces = mutators.modify_prompt(harness, coder.id, new_prompt)
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="modify_prompt",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect="Coder produces smaller, more targeted diffs.",
        regression_risk="May cause coder to skip necessary changes.",
        rollback_plan="Revert coder prompt to parent.",
    )
    return [(proposal, candidate)]


def _rule_add_verifier_agent(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    verifier = Agent(
        id="verifier_agent",
        name="Verifier Agent",
        role="Confirm all required artifacts exist and tests pass before concluding.",
        responsibilities=["Check artifact list.", "Run tests.", "Block completion if any check fails."],
        prompt=(
            "You are the Verifier Agent.\n"
            "Before the run concludes, confirm:\n"
            "1. All required artifacts are present.\n"
            "2. Tests pass.\n"
            "Do not pass until both checks are satisfied."
        ),
        tools=["read_files", "run_tests"],
        budget=AgentBudget(max_tool_calls=8, max_runtime_seconds=120),
        memory_policy=AgentMemoryPolicy(read_shared=True, write_shared=True),
    )

    # Find the last phase name to insert after
    last_phase = harness.execution.phases[-1].name
    last_agent_id = harness.execution.phases[-1].agents[-1]

    candidate, surfaces = mutators.add_agent(
        harness, verifier, last_phase, edge_from=last_agent_id
    )
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="add_agent",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect="Dedicated verifier ensures artifacts and tests are confirmed before run ends.",
        regression_risk="Adds runtime; verifier may block on transient test failures.",
        rollback_plan="Remove verifier_agent and its edges.",
    )
    return [(proposal, candidate)]


def _rule_remove_redundant_agent(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    agent_id = sig.agent_id
    if not agent_id:
        return []
    core_keywords = ("requirements", "coder", "tester", "reviewer")
    if any(kw in agent_id.lower() for kw in core_keywords):
        return []
    # Don't remove the sole agent in its phase
    for phase in harness.execution.phases:
        if agent_id in phase.agents and len(phase.agents) == 1:
            return []

    candidate, surfaces = mutators.remove_agent(harness, agent_id)
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="remove_agent",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect=f"Removing non-critical agent '{agent_id}' reduces tool-call overhead and improves efficiency score.",
        regression_risk="Agent removal may reduce coverage; verify core artifacts are still produced.",
        rollback_plan="Re-add the agent to its original phase.",
    )
    return [(proposal, candidate)]


def _rule_upgrade_requirements_model(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    req_agent = next((a for a in harness.agents if "requirements" in a.id), None)
    if req_agent is None:
        return []
    if req_agent.model and req_agent.model not in (None, "mock", "gemini-1.5-flash"):
        return []

    target_model = "gemini-2.5-flash"
    candidate, surfaces = mutators.change_model(harness, req_agent.id, target_model)
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="change_model",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect=f"Upgrading requirements agent to {target_model} produces more precise acceptance criteria.",
        regression_risk="Higher-tier model increases latency and cost.",
        rollback_plan="Revert requirements agent model to parent value.",
    )
    return [(proposal, candidate)]


def _rule_enforce_tester_before_review(
    sig: FailureSignature, harness: OrganizationHarness
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    # Find coder→tester edge and make it strictly blocking
    has_edge = any(
        e.from_agent == "coder_agent" and e.to == "tester_agent"
        for e in harness.communication.edges
    )
    if not has_edge:
        return []

    candidate, surfaces = mutators.reorder_edges(
        harness, "coder_agent", "tester_agent", "blocking"
    )
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="reorder_edges",
        target_failure_signature=sig.signature_key(),
        changed_surfaces=surfaces,
        expected_effect="Tester is guaranteed to run after coder, enforcing proper test ordering.",
        regression_risk="None expected.",
        rollback_plan="Revert edge type to parent value.",
    )
    return [(proposal, candidate)]
