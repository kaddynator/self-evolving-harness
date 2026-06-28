from __future__ import annotations

import copy
from typing import List

from src.ir.schema import (
    Agent, AgentBudget, AgentMemoryPolicy, AgentOutputContract,
    Communication, Edge, EdgeType, OrganizationHarness,
)


def _clone(harness: OrganizationHarness) -> OrganizationHarness:
    """Deep-copy the harness and bump its version number.

    The organization.id stays short and constant across generations (e.g.
    ``wf-ratelimiter``); generations are tracked by the integer
    ``organization.version`` field instead of appending ``_vN`` suffixes to the
    id. parent_id records the lineage (the parent's id), which equals our own id
    since the slug is stable — this keeps the displayed id stable and readable.
    """
    raw = harness.model_dump(mode="python")
    raw["organization"]["version"] = harness.organization.version + 1
    raw["organization"]["parent_id"] = harness.organization.id
    # Keep the id constant — do NOT append _v<N>. Version increments separately.
    raw["organization"]["id"] = harness.organization.id
    return OrganizationHarness.model_validate(raw)


# ---------------------------------------------------------------------------
# Individual mutation operators
# Each returns (mutated_harness, changed_surfaces_list)
# ---------------------------------------------------------------------------

def add_agent(
    harness: OrganizationHarness,
    new_agent: Agent,
    insert_in_phase: str,
    edge_from: str,
) -> tuple[OrganizationHarness, List[str]]:
    """Insert a new agent into an existing phase and wire a blocking edge."""
    h = _clone(harness)

    raw = h.model_dump(mode="python")

    # Add agent
    raw["agents"].append(new_agent.model_dump(mode="python"))

    # Insert into phase
    for phase in raw["execution"]["phases"]:
        if phase["name"] == insert_in_phase:
            phase["agents"].append(new_agent.id)
            break

    # Wire blocking edge from edge_from → new_agent
    raw["communication"]["edges"].append({
        "from_agent": edge_from,
        "to": new_agent.id,
        "type": "blocking",
        "artifact": None,
        "max_rounds": None,
    })

    return OrganizationHarness.model_validate(raw), [
        f"agents.{new_agent.id}",
        f"execution.phases.{insert_in_phase}",
        "communication.edges",
    ]


def remove_agent(
    harness: OrganizationHarness,
    agent_id: str,
) -> tuple[OrganizationHarness, List[str]]:
    """Remove an agent, its edges, and its phase entries."""
    h = _clone(harness)
    raw = h.model_dump(mode="python")

    raw["agents"] = [a for a in raw["agents"] if a["id"] != agent_id]

    for phase in raw["execution"]["phases"]:
        phase["agents"] = [a for a in phase["agents"] if a != agent_id]

    # model_dump uses Python field name "from_agent", not alias "from"
    raw["communication"]["edges"] = [
        e for e in raw["communication"]["edges"]
        if e.get("from_agent") != agent_id and e.get("to") != agent_id
    ]

    return OrganizationHarness.model_validate(raw), [
        f"agents.{agent_id}",
        "communication.edges",
    ]


def modify_prompt(
    harness: OrganizationHarness,
    agent_id: str,
    new_prompt: str,
) -> tuple[OrganizationHarness, List[str]]:
    """Replace an agent's prompt."""
    h = _clone(harness)
    raw = h.model_dump(mode="python")

    for agent in raw["agents"]:
        if agent["id"] == agent_id:
            agent["prompt"] = new_prompt
            break

    return OrganizationHarness.model_validate(raw), [f"agents.{agent_id}.prompt"]


def modify_tools(
    harness: OrganizationHarness,
    agent_id: str,
    add_tools: List[str] | None = None,
    remove_tools: List[str] | None = None,
) -> tuple[OrganizationHarness, List[str]]:
    """Add or remove tools from an agent's tool list."""
    h = _clone(harness)
    raw = h.model_dump(mode="python")

    for agent in raw["agents"]:
        if agent["id"] == agent_id:
            tools = set(agent.get("tools", []))
            if add_tools:
                tools.update(add_tools)
            if remove_tools:
                tools -= set(remove_tools)
            agent["tools"] = sorted(tools)
            break

    return OrganizationHarness.model_validate(raw), [f"agents.{agent_id}.tools"]


def adjust_budget(
    harness: OrganizationHarness,
    agent_id: str,
    max_tool_calls: int | None = None,
    max_runtime_seconds: int | None = None,
) -> tuple[OrganizationHarness, List[str]]:
    """Tighten or relax an agent's budget."""
    h = _clone(harness)
    raw = h.model_dump(mode="python")

    for agent in raw["agents"]:
        if agent["id"] == agent_id:
            if max_tool_calls is not None:
                agent["budget"]["max_tool_calls"] = max_tool_calls
            if max_runtime_seconds is not None:
                agent["budget"]["max_runtime_seconds"] = max_runtime_seconds
            break

    return OrganizationHarness.model_validate(raw), [f"agents.{agent_id}.budget"]


def modify_runtime_policy(
    harness: OrganizationHarness,
    **policy_overrides,
) -> tuple[OrganizationHarness, List[str]]:
    """Override one or more runtime_policies fields."""
    h = _clone(harness)
    raw = h.model_dump(mode="python")

    for key, val in policy_overrides.items():
        if key in raw["runtime_policies"]:
            raw["runtime_policies"][key] = val

    return OrganizationHarness.model_validate(raw), [
        f"runtime_policies.{k}" for k in policy_overrides
    ]


def change_model(
    harness: OrganizationHarness,
    agent_id: str,
    model: str,
) -> tuple[OrganizationHarness, List[str]]:
    """Change the LLM model assigned to a specific agent."""
    h = _clone(harness)
    raw = h.model_dump(mode="python")

    for agent in raw["agents"]:
        if agent["id"] == agent_id:
            agent["model"] = model
            break

    return OrganizationHarness.model_validate(raw), [f"agents.{agent_id}.model"]


def reorder_edges(
    harness: OrganizationHarness,
    from_agent: str,
    to_agent: str,
    new_type: str,
) -> tuple[OrganizationHarness, List[str]]:
    """Change the type of an existing edge (e.g. feedback → blocking)."""
    h = _clone(harness)
    raw = h.model_dump(mode="python")

    for edge in raw["communication"]["edges"]:
        if edge.get("from_agent") == from_agent and edge.get("to") == to_agent:
            edge["type"] = new_type
            break

    return OrganizationHarness.model_validate(raw), ["communication.edges"]
