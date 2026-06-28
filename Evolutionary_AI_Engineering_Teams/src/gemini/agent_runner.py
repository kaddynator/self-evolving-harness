from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from src.ir.schema import Agent
from src.gemini.client import GeminiClient
from src.runtime.tools import ToolSandbox, tool_declarations_for


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


# ---------------------------------------------------------------------------
# Tool-using agent runner (real Gemini function calling against a sandbox)
# ---------------------------------------------------------------------------

def _function_response_part(name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"functionResponse": {"name": name, "response": {"result": result}}}


def _artifacts_from_sandbox(
    agent: Agent,
    sandbox: ToolSandbox,
    text: str,
    last_results: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Augment text-parsed artifacts with real signals from sandbox state.

    Real signals (a git diff, a test exit code) override the text heuristics so
    the scorer/judge get something concrete.
    """
    artifacts: Dict[str, Any] = {}
    agent_id = agent.id.lower()

    if "coder" in agent_id or "develop" in agent_id:
        # Prefer an actual diff from the workspace over a fenced block in text.
        if "```" not in text:
            diff = sandbox.dispatch("git_diff", {}).get("diff", "")
            if diff:
                artifacts["code_patch"] = diff

    if "tester" in agent_id or "qa" in agent_id:
        rt = last_results.get("run_tests")
        if isinstance(rt, dict) and "exit_code" in rt:
            artifacts["test_results"] = {
                "passed": "ok" if rt["exit_code"] == 0 else "fail",
                "failed": 0 if rt["exit_code"] == 0 else 1,
                "output": (rt.get("stdout", "") or rt.get("stderr", ""))[:400],
            }

    return artifacts


def run_gemini_agent_with_tools(
    agent: Agent,
    client: GeminiClient,
    sandbox: ToolSandbox,
    shared_memory: Dict[str, Any] | None = None,
    on_tool_call: Optional[Callable[[str, bool], None]] = None,
) -> Dict[str, Any]:
    """Execute one agent via a Gemini function-calling loop against the sandbox.

    Returns the same result dict shape as run_mock_agent / run_gemini_agent.
    """
    shared_memory = shared_memory or {}
    declarations = tool_declarations_for(agent.tools)

    # No tools assigned → fall back to the plain text runner.
    if not declarations:
        return run_gemini_agent(agent, client, shared_memory=shared_memory)

    contents: List[Dict[str, Any]] = [
        {"role": "user", "parts": [{"text": _build_prompt(agent, shared_memory)}]}
    ]
    cap = max(1, agent.budget.max_tool_calls)
    max_iters = cap + 2

    tool_calls: List[Dict[str, Any]] = []
    tool_count = 0
    last_results: Dict[str, Dict[str, Any]] = {}
    final_text = ""

    for iteration in range(max_iters):
        force_final = tool_count >= cap
        try:
            resp = client.generate_with_tools(
                contents,
                tool_declarations=declarations,
                system_instruction=_HARNESS_SYSTEM,
                tool_mode="NONE" if force_final else "AUTO",
            )
        except Exception as exc:
            return {
                "tool_calls": tool_calls,
                "tool_call_count": tool_count,
                "artifacts": {},
                "output_text": f"[Gemini error] {exc}",
                "success": False,
            }

        calls = resp.get("function_calls") or []
        if not calls or force_final:
            final_text = resp.get("text", "")
            break

        # Record the model's turn verbatim, then execute its tool calls.
        contents.append({"role": "model", "parts": resp.get("raw_parts", [])})
        fr_parts: List[Dict[str, Any]] = []
        for call in calls:
            name = call.get("name", "")
            if tool_count >= cap:
                result = {"error": "budget_exceeded"}
                if on_tool_call:
                    on_tool_call(name, False)
            else:
                result = sandbox.dispatch(name, call.get("args", {}))
                tool_count += 1
                ok = "error" not in result
                last_results[name] = result
                tool_calls.append({"tool": name, "result": result})
                if on_tool_call:
                    on_tool_call(name, ok)
            fr_parts.append(_function_response_part(name, result))
        contents.append({"role": "user", "parts": fr_parts})

    artifacts = _parse_artifacts(final_text, agent)
    artifacts.update(_artifacts_from_sandbox(agent, sandbox, final_text, last_results))

    return {
        "tool_calls": tool_calls,
        "tool_call_count": tool_count,
        "artifacts": artifacts,
        "output_text": final_text,
        "success": True,
    }


def make_gemini_tool_runner(client: GeminiClient, task=None):
    """Return an AgentRunner with a `new_run()` hook for per-run isolation.

    RuntimeExecutor.run() calls runner.new_run() (if present) at the start of
    every run, so each run gets a fresh shared-memory dict and a fresh
    ToolSandbox (the prior one is cleaned up). This avoids the cross-run leak of
    the closure-based runner.
    """
    test_command = "pytest -q"
    if task is not None:
        try:
            test_command = task.inputs.get("test_command", test_command)
        except Exception:
            pass

    state: Dict[str, Any] = {"mem": {}, "sandbox": None}

    def new_run() -> None:
        old = state.get("sandbox")
        if old is not None:
            old.cleanup()
        state["mem"] = {}
        state["sandbox"] = ToolSandbox(test_command=test_command)

    def _runner(agent: Agent, on_tool_call=None) -> Dict[str, Any]:
        if state["sandbox"] is None:
            new_run()
        result = run_gemini_agent_with_tools(
            agent, client, state["sandbox"],
            shared_memory=state["mem"], on_tool_call=on_tool_call,
        )
        state["mem"].update(result.get("artifacts", {}))
        return result

    _runner.new_run = new_run  # type: ignore[attr-defined]
    return _runner
