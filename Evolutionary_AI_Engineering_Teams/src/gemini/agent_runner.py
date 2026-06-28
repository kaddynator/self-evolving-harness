from __future__ import annotations

import re
from typing import Any, Dict, List

from src.ir.schema import Agent
from src.gemini.client import GeminiClient


# System instruction handed to every agent role
_HARNESS_SYSTEM = (
    "You are an AI agent operating inside an automated software engineering harness.\n"
    "Follow your role and responsibilities exactly.\n"
    "Produce only what your output contract requires.\n"
    "Do not invent information outside the task description."
)


def _build_prompt(agent: Agent, shared_memory: Dict[str, Any]) -> str:
    """Construct the full user prompt from the agent IR and current shared memory."""
    lines = [
        f"# Role: {agent.name}",
        f"## Responsibilities",
        *[f"- {r}" for r in agent.responsibilities],
        "",
        "## Your prompt",
        agent.prompt.strip(),
        "",
    ]

    if agent.output_contract:
        lines += [
            "## Output contract",
            f"Type: {agent.output_contract.type}",
            "Required sections:",
            *[f"- {s}" for s in agent.output_contract.required_sections],
            "",
        ]

    if shared_memory:
        lines += ["## Shared memory (from prior agents)", ""]
        for key, value in shared_memory.items():
            if key == "execution_trace":
                continue  # skip verbose trace blob
            lines.append(f"### {key}")
            lines.append(str(value)[:800])  # cap per-item size
            lines.append("")

    lines += [
        "## Available tools",
        ", ".join(agent.tools) if agent.tools else "none",
        "",
        "## Budget",
        f"Max tool calls: {agent.budget.max_tool_calls}",
        f"Max runtime (s): {agent.budget.max_runtime_seconds}",
        "",
        "Produce your output now, strictly following the output contract above.",
    ]
    return "\n".join(lines)


def _parse_artifacts(text: str, agent: Agent) -> Dict[str, Any]:
    """Extract artifacts from the agent's free-text response.

    For mock compatibility we produce the same artifact keys the mock does:
    - requirements_agent  → acceptance_criteria
    - coder_agent         → code_patch
    - tester_agent        → test_results
    - reviewer_agent      → review_notes
    """
    artifacts: Dict[str, Any] = {}

    agent_id = agent.id.lower()

    if "requirements" in agent_id:
        artifacts["acceptance_criteria"] = text

    elif "coder" in agent_id:
        # Extract fenced diff block if present, else use full text
        diff_match = re.search(r"```(?:diff)?\n(.*?)```", text, re.DOTALL)
        artifacts["code_patch"] = diff_match.group(1) if diff_match else text

    elif "tester" in agent_id:
        passed = "fail" not in text.lower() and "error" not in text.lower()
        artifacts["test_results"] = {
            "passed": "unknown (gemini)",
            "failed": 0 if passed else 1,
            "output": text[:400],
        }

    elif "reviewer" in agent_id:
        approved = any(w in text.lower() for w in ("approved", "accept", "lgtm", "looks good", "approval\napproved", "## approval\napproved"))
        # Also check: if the Approval section says "Approved" (case-insensitive)
        import re as _re
        approval_match = _re.search(r"##\s*Approval\s*\n([^\n]+)", text, _re.IGNORECASE)
        if approval_match:
            approval_text = approval_match.group(1).strip().lower()
            approved = approved or ("approved" in approval_text and "not" not in approval_text)
        artifacts["review_notes"] = "approved" if approved else text[:200]

    return artifacts


def run_gemini_agent(
    agent: Agent,
    client: GeminiClient,
    shared_memory: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Execute one agent role via Gemini and return the standard result dict.

    Return shape is identical to run_mock_agent so RuntimeExecutor needs no changes.
    """
    shared_memory = shared_memory or {}
    prompt = _build_prompt(agent, shared_memory)

    try:
        text = client.generate(prompt, system_instruction=_HARNESS_SYSTEM)
    except Exception as exc:
        return {
            "tool_calls": [],
            "tool_call_count": 0,
            "artifacts": {},
            "output_text": f"[Gemini error] {exc}",
            "success": False,
        }

    artifacts = _parse_artifacts(text, agent)

    return {
        "tool_calls": [],           # REST adapter has no live tool execution yet
        "tool_call_count": 1,       # count the single Gemini call
        "artifacts": artifacts,
        "output_text": text,
        "success": True,
    }


def make_gemini_runner(
    client: GeminiClient,
    shared_memory_ref: Dict[str, Any] | None = None,
):
    """Return an AgentRunner closure compatible with RuntimeExecutor's injection point."""
    mem = shared_memory_ref if shared_memory_ref is not None else {}

    def _runner(agent: Agent) -> Dict[str, Any]:
        result = run_gemini_agent(agent, client, shared_memory=mem)
        # Feed artifacts back into shared memory for subsequent agents
        mem.update(result.get("artifacts", {}))
        return result

    return _runner
