"""Tests for backend items: short ids, prompt detail, prompt evolution, model selection."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.compiler.compiler import HarnessCompiler
from src.compiler.prompt import build_compilation_prompt
from src.evolution.engine import propose_mutations
from src.evolution.models import GEMINI_MODEL_POOL, next_tier, prev_tier
from src.evolution import mutators
from src.gemini.client import GeminiClient
from src.ir.loader import load_harness
from src.ir.schema import OrganizationHarness
from src.weakness.signatures import FailureSignature, Mechanism

EXAMPLE_SPEC = Path(__file__).parent.parent / "examples" / "organization_spec.yaml"


@pytest.fixture
def harness() -> OrganizationHarness:
    return load_harness(EXAMPLE_SPEC)


@pytest.fixture
def harness_with_change_model() -> OrganizationHarness:
    """Example harness whose mutation_policy also permits change_model."""
    h = load_harness(EXAMPLE_SPEC)
    raw = h.model_dump(mode="python")
    allowed = set(raw["mutation_policy"]["allowed_mutations"])
    allowed.add("change_model")
    raw["mutation_policy"]["allowed_mutations"] = sorted(allowed)
    return OrganizationHarness.model_validate(raw)


def _sig(mechanism: str, agent_id: str = None, behavior: str = "some_behavior") -> FailureSignature:
    return FailureSignature(
        verifier_cause="vc", agent_behavior=behavior, mechanism=mechanism, agent_id=agent_id,
    )


# ---------------------------------------------------------------------------
# ITEM 6 — short, stable harness ids
# ---------------------------------------------------------------------------

class TestShortIds:
    def test_mock_compile_produces_short_wf_id(self):
        h = HarnessCompiler().compile("Implement a per-user rate limiter for the API")
        assert h.organization.id.startswith("wf-")
        assert "_v" not in h.organization.id
        assert len(h.organization.id) <= 28

    def test_id_is_stable_across_clones_and_version_bumps(self):
        h = HarnessCompiler().compile("Build a webhook handler")
        candidate, _ = mutators.modify_prompt(h, h.agents[0].id, "NEW PROMPT TEXT")
        # id unchanged, version incremented, parent recorded
        assert candidate.organization.id == h.organization.id
        assert candidate.organization.version == h.organization.version + 1
        assert candidate.organization.parent_id == h.organization.id
        # No _vN suffix accreting on the id
        assert "_v" not in candidate.organization.id

    def test_id_stable_across_multiple_generations(self):
        h = HarnessCompiler().compile("Add caching to the data layer")
        base_id = h.organization.id
        cur = h
        for _ in range(3):
            cur, _ = mutators.adjust_budget(cur, cur.agents[0].id, max_tool_calls=4)
        assert cur.organization.id == base_id
        assert cur.organization.version == h.organization.version + 3


# ---------------------------------------------------------------------------
# ITEM 2 — customizable prompt detail
# ---------------------------------------------------------------------------

class TestPromptDetail:
    def test_compile_default_no_prompt_detail_arg(self):
        # compile() must still work with no prompt_detail arg.
        h = HarnessCompiler().compile("Fix the login bug")
        assert isinstance(h, OrganizationHarness)

    def test_build_prompt_levels_differ(self):
        brief = build_compilation_prompt("task", prompt_detail="brief")
        detailed = build_compilation_prompt("task", prompt_detail="detailed")
        exhaustive = build_compilation_prompt("task", prompt_detail="exhaustive")
        assert "CONCISE" in brief
        assert "DETAILED" in detailed
        assert "EXHAUSTIVE" in exhaustive
        # exhaustive guidance is the longest of the three
        assert len(exhaustive) > len(detailed) > len(brief)

    def test_invalid_level_falls_back_to_detailed(self):
        p = build_compilation_prompt("task", prompt_detail="nonsense")
        assert "DETAILED" in p

    def test_gemini_compile_threads_prompt_detail(self):
        client = MagicMock(spec=GeminiClient)
        from test_compiler import _minimal_harness_yaml
        client.generate.return_value = _minimal_harness_yaml()
        HarnessCompiler(client=client).compile("Add search", prompt_detail="exhaustive")
        prompt = client.generate.call_args[0][0]
        assert "EXHAUSTIVE" in prompt


# ---------------------------------------------------------------------------
# ITEM 4 — prompts actually evolve each generation
# ---------------------------------------------------------------------------

class TestPromptEvolution:
    def test_client_yields_longer_prompt_proposal(self, harness):
        client = MagicMock(spec=GeminiClient)
        # Model returns a clearly longer, specialized prompt.
        client.generate.return_value = "EXPANDED PROMPT\n" + ("methodology line\n" * 40)

        pairs = propose_mutations(harness, signatures=[], client=client)
        modify_prompt_pairs = [
            (p, c) for (p, c) in pairs if p.mutation_type == "modify_prompt"
        ]
        assert modify_prompt_pairs, "expected at least one modify_prompt proposal"

        proposal, candidate = modify_prompt_pairs[0]
        # The candidate's targeted agent prompt is longer than the parent's.
        surface = proposal.changed_surfaces[0]  # e.g. "agents.<id>.prompt"
        agent_id = surface.split(".")[1]
        parent_prompt = harness.agent_by_id(agent_id).prompt
        cand_prompt = candidate.agent_by_id(agent_id).prompt
        assert len(cand_prompt) > len(parent_prompt)
        assert cand_prompt != parent_prompt

    def test_prompt_evolves_even_when_model_returns_short(self, harness):
        # If the model returns nothing useful, the deterministic specialization
        # line still guarantees a longer, changed prompt.
        client = MagicMock(spec=GeminiClient)
        client.generate.return_value = "x"  # shorter than current prompt
        pairs = propose_mutations(harness, signatures=[], client=client)
        mp = [(p, c) for (p, c) in pairs if p.mutation_type == "modify_prompt"]
        assert mp
        proposal, candidate = mp[0]
        agent_id = proposal.changed_surfaces[0].split(".")[1]
        assert len(candidate.agent_by_id(agent_id).prompt) > len(
            harness.agent_by_id(agent_id).prompt
        )

    def test_no_client_no_standing_prompt_rule(self, harness):
        # Deterministic path: no standing prompt-evolution proposal when client is None.
        pairs = propose_mutations(harness, signatures=[], client=None)
        assert pairs == []


# ---------------------------------------------------------------------------
# ITEM 5 — intelligent per-agent model selection
# ---------------------------------------------------------------------------

class TestModelSelection:
    def test_model_pool_order(self):
        assert GEMINI_MODEL_POOL == [
            "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro",
        ]
        assert next_tier("gemini-2.5-flash") == "gemini-2.5-pro"
        assert next_tier("gemini-2.5-pro") is None
        assert prev_tier("gemini-2.5-flash") == "gemini-2.5-flash-lite"
        assert prev_tier("gemini-2.5-flash-lite") is None
        # Unknown/None default to the flash tier.
        assert next_tier(None) == "gemini-2.5-pro"

    def test_change_model_proposal_for_weak_agent(self, harness_with_change_model):
        harness = harness_with_change_model
        client = MagicMock(spec=GeminiClient)
        client.generate.return_value = "longer prompt " * 20
        sigs = [_sig(Mechanism.WEAK_REQUIREMENTS_GROUNDING, agent_id="coder_agent")]
        pairs = propose_mutations(
            harness, sigs, client=client, optimize_models=True, max_proposals=10,
        )
        cm = [(p, c) for (p, c) in pairs if p.mutation_type == "change_model"]
        assert cm, "expected a change_model proposal"
        proposal, candidate = cm[0]
        agent_id = proposal.changed_surfaces[0].split(".")[1]
        new_model = candidate.agent_by_id(agent_id).model
        assert new_model in GEMINI_MODEL_POOL
        # Moved to a higher tier than the parent (default flash -> pro).
        parent_model = harness.agent_by_id(agent_id).model
        assert new_model != parent_model

    def test_optimize_models_off_skips_standing_model_rule(self, harness):
        client = MagicMock(spec=GeminiClient)
        client.generate.return_value = "longer prompt " * 20
        pairs = propose_mutations(
            harness, signatures=[], client=client, optimize_models=False, max_proposals=10,
        )
        # The standing model rule must not fire; only signature-driven change_model
        # rules could appear, and with no signatures there are none.
        cm = [p for (p, c) in pairs if p.mutation_type == "change_model"]
        assert cm == []

    def test_no_client_no_standing_model_rule(self, harness):
        pairs = propose_mutations(
            harness, signatures=[], client=None, optimize_models=True,
        )
        assert pairs == []
