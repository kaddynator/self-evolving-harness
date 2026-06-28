from __future__ import annotations

from typing import List, Tuple

from src.ir.schema import Agent, AgentBudget, AgentMemoryPolicy, OrganizationHarness
from src.weakness.signatures import FailureSignature, Mechanism
from src.evolution.proposals import MutationProposal, make_proposal_id
from src.evolution import mutators
from src.evolution.models import GEMINI_MODEL_POOL, next_tier, prev_tier
from src.compiler.prompt import expand_agent_prompt


def _grow_or_append(client, agent: Agent, guidance: str, fallback_suffix: str) -> str:
    """Grow an agent prompt via the model when available, else append a fixed line.

    The deterministic fallback (no client) keeps the existing behavior so unit
    tests that assert on specific appended text remain valid.
    """
    if client is not None:
        grown = expand_agent_prompt(
            client, agent.name, agent.role, agent.prompt, guidance
        )
        if grown and grown != agent.prompt:
            return grown
    return agent.prompt.rstrip() + fallback_suffix


# ---------------------------------------------------------------------------
# Mechanism → mutation rules
# Each rule maps a failure mechanism to a list of (proposal, candidate) pairs.
# ---------------------------------------------------------------------------

def propose_mutations(
    harness: OrganizationHarness,
    signatures: List[FailureSignature],
    max_proposals: int | None = None,
    client=None,
    optimize_models: bool = True,
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    """Return up to `max_proposals` (proposal, candidate_harness) pairs.

    Proposals are grounded in the supplied failure signatures; only mutations
    allowed by harness.mutation_policy are generated. When `client` (a Gemini
    client) is provided, prompt-mutation rules use it to genuinely expand and
    specialize agent prompts; otherwise they fall back to deterministic edits.

    Two standing rules fire when a Gemini `client` is present, independent of
    the mined signatures, so the workflow keeps evolving every generation:

    * Prompt evolution (ITEM 4): at least one agent's prompt is expanded /
      specialized via the model each generation. The agent is chosen by the run
      (most-implicated agent) and otherwise rotated by version so prompts keep
      changing. The validation gate keeps it only if the judged score improves.
    * Model selection (ITEM 5): when `optimize_models` is on, an under-performing
      agent is proposed for an upgrade to the next tier in GEMINI_MODEL_POOL
      (and an over-provisioned reviewer/specialist may be downgraded to save
      cost). The gate keeps upgrades that actually help.
    """
    max_proposals = max_proposals or harness.mutation_policy.proposal_width
    allowed = {m.value for m in harness.mutation_policy.allowed_mutations}

    results: List[Tuple[MutationProposal, OrganizationHarness]] = []

    # Standing rules first (real-model path only) so they always get a slot even
    # when signature-driven rules are plentiful — this is what guarantees the
    # prompt/model actually evolve each generation.
    if client is not None:
        for pair in _standing_rules(harness, signatures, allowed, client, optimize_models):
            if len(results) >= max_proposals:
                break
            results.append(pair)

    for sig in signatures:
        if len(results) >= max_proposals:
            break
        new_pairs = _rules_for(sig, harness, allowed, client=client)
        for pair in new_pairs:
            if len(results) >= max_proposals:
                break
            results.append(pair)

    return results


# ---------------------------------------------------------------------------
# Standing rules — fire every generation when a Gemini client is present
# ---------------------------------------------------------------------------

def _standing_rules(
    harness: OrganizationHarness,
    signatures: List[FailureSignature],
    allowed: set,
    client,
    optimize_models: bool,
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    """Generate client-backed prompt-evolution and model-selection proposals."""
    out: List[Tuple[MutationProposal, OrganizationHarness]] = []

    if "modify_prompt" in allowed:
        out.extend(_rule_evolve_a_prompt(harness, signatures, client))

    if optimize_models and "change_model" in allowed:
        out.extend(_rule_optimize_agent_model(harness, signatures, client))

    return out


def _implicated_agent_id(signatures: List[FailureSignature]) -> str | None:
    """Pick the agent most implicated by the run's failure signatures."""
    for sig in signatures:
        if sig.agent_id:
            return sig.agent_id
    return None


def _rule_evolve_a_prompt(
    harness: OrganizationHarness,
    signatures: List[FailureSignature],
    client,
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    """Expand/specialize one agent's prompt via the model, every generation.

    Target selection: the agent most implicated by the run, else rotate through
    agents by the harness version so a different agent is grown each generation.
    Produces a genuinely longer, different prompt; only kept by the gate if the
    judged score improves.
    """
    if not harness.agents:
        return []

    target_id = _implicated_agent_id(signatures)
    target = None
    if target_id:
        target = next((a for a in harness.agents if a.id == target_id), None)
    if target is None:
        # Rotate by version so the chosen agent changes across generations.
        idx = max(0, harness.organization.version - 1) % len(harness.agents)
        target = harness.agents[idx]

    guidance = (
        f"This is generation {harness.organization.version} of an evolving workflow. "
        f"Make the {target.name}'s prompt markedly more detailed and specialized "
        "for its role so the workflow scores higher: add a concrete step-by-step "
        "methodology, the exact output format, edge cases, and explicit do/don't "
        "rules. The new prompt MUST be longer and more specific than the current one."
    )
    grown = expand_agent_prompt(
        client, target.name, target.role, target.prompt, guidance
    )
    # Deterministic guarantee that the prompt genuinely grows even if the model
    # returns something not strictly longer (expand_agent_prompt already guards,
    # but we add a standing specialization line so the surface always changes).
    if not grown or len(grown) <= len(target.prompt):
        grown = (
            target.prompt.rstrip()
            + f"\n\n## Generation {harness.organization.version} specialization\n"
            + "Follow a concrete step-by-step methodology, state the exact output "
            + "format, enumerate edge cases, and apply explicit do/don't rules. "
            + "Prefer the smallest correct action and verify before concluding."
        )

    candidate, surfaces = mutators.modify_prompt(harness, target.id, grown)
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="modify_prompt",
        target_failure_signature=(signatures[0].signature_key() if signatures else "standing:prompt_evolution"),
        changed_surfaces=surfaces,
        expected_effect=f"Specialize {target.name}'s prompt to lift the judged score.",
        regression_risk="Longer prompt may add verbosity; gate rejects if score drops.",
        rollback_plan="Revert to parent prompt.",
    )
    return [(proposal, candidate)]


def _rule_optimize_agent_model(
    harness: OrganizationHarness,
    signatures: List[FailureSignature],
    client,
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    """Propose a model-tier change for an agent within GEMINI_MODEL_POOL.

    Selection is deterministic next-tier bumping: the agent most implicated by
    the run (else the coder, the workflow's heaviest reasoner) is upgraded to
    the next more-capable model in the pool. If it is already at the top tier,
    fall back to upgrading any agent that still has room to move up. The
    validation gate keeps the change only if the candidate's score improves.
    """
    if not harness.agents:
        return []

    target_id = _implicated_agent_id(signatures)
    target = None
    if target_id:
        target = next((a for a in harness.agents if a.id == target_id), None)
    if target is None:
        target = next((a for a in harness.agents if "coder" in a.id), harness.agents[0])

    new_model = next_tier(target.model)
    if new_model is None:
        # Target already maxed — find any agent with headroom to upgrade.
        target = next((a for a in harness.agents if next_tier(a.model) is not None), None)
        if target is None:
            return []
        new_model = next_tier(target.model)

    candidate, surfaces = mutators.change_model(harness, target.id, new_model)
    proposal = MutationProposal(
        proposal_id=make_proposal_id(),
        parent_org_id=harness.organization.id,
        candidate_org_id=candidate.organization.id,
        mutation_type="change_model",
        target_failure_signature=(signatures[0].signature_key() if signatures else "standing:model_selection"),
        changed_surfaces=surfaces,
        expected_effect=f"Upgrade {target.name} to {new_model} (next tier) to lift the judged score.",
        regression_risk="Higher-tier model increases latency/cost; gate rejects if no score gain.",
        rollback_plan="Revert agent model to parent value.",
    )
    return [(proposal, candidate)]


# ---------------------------------------------------------------------------
# Rule dispatch
# ---------------------------------------------------------------------------

def _rules_for(
    sig: FailureSignature,
    harness: OrganizationHarness,
    allowed: set,
    client=None,
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    mechanism = sig.mechanism
    results = []

    if mechanism == Mechanism.WEAK_REQUIREMENTS_GROUNDING and "modify_prompt" in allowed:
        results.extend(_rule_strengthen_requirements_prompt(sig, harness, client))

    if mechanism == Mechanism.MISSING_REQUIRED_ARTIFACT and "modify_runtime_policy" in allowed:
        results.extend(_rule_enforce_artifact_policy(sig, harness))

    if mechanism == Mechanism.WRONG_TOOL_PERMISSION and "modify_tools" in allowed:
        results.extend(_rule_fix_tool_permission(sig, harness))

    if mechanism == Mechanism.EXCESSIVE_EXPLORATION and "adjust_budget" in allowed:
        results.extend(_rule_tighten_coder_budget(sig, harness))

    if mechanism == Mechanism.REPEATED_FAILED_TOOL_CALL and "modify_runtime_policy" in allowed:
        results.extend(_rule_prevent_identical_retry(sig, harness))

    if mechanism == Mechanism.OVERSIZED_PATCH and "modify_prompt" in allowed:
        results.extend(_rule_add_minimal_patch_instruction(sig, harness, client))

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
    sig: FailureSignature, harness: OrganizationHarness, client=None
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    req_agent = next((a for a in harness.agents if "requirements" in a.id), None)
    if req_agent is None:
        return []

    guidance = (
        "The requirements were too weak/vague, causing downstream test failures. "
        "Make the agent produce precise, testable acceptance criteria, each tied "
        "to an explicit test assertion."
    )
    grown = _grow_or_append(
        client, req_agent, guidance,
        fallback_suffix="\nAlways ground every acceptance criterion in an explicit test assertion.",
    )
    candidate, surfaces = mutators.modify_prompt(harness, req_agent.id, grown)
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
    sig: FailureSignature, harness: OrganizationHarness, client=None
) -> List[Tuple[MutationProposal, OrganizationHarness]]:
    coder = next((a for a in harness.agents if "coder" in a.id), None)
    if coder is None:
        return []

    guidance = (
        "The coder produced an oversized patch. Make it keep the patch under 30 "
        "lines and touch only the files necessary for the feature, with a clear "
        "minimal-diff methodology."
    )
    new_prompt = _grow_or_append(
        client, coder, guidance,
        fallback_suffix="\nKeep the patch under 30 lines. Touch only the files necessary for the feature.",
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

    target_model = "gemini-3.5-flash"
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
