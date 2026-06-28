from __future__ import annotations

import time
from typing import Any, Dict, List

from src.ir.schema import Agent


# ---------------------------------------------------------------------------
# Tool simulation
# ---------------------------------------------------------------------------

_TOOL_OUTPUTS: Dict[str, Any] = {
    "read_files": "# mock file content\nclass App: pass\n",
    "list_files": ["app.py", "routes.py", "tests/test_app.py"],
    "edit_files": "ok",
    "run_tests": {"passed": 5, "failed": 0, "output": "5 passed in 0.4s"},
    "git_diff": "diff --git a/routes.py b/routes.py\n+rate_limiter = {}\n",
}

# Seconds of simulated work per tool call — makes events stream in visibly.
_TOOL_LATENCY: Dict[str, float] = {
    "read_files":  0.25,
    "list_files":  0.15,
    "edit_files":  0.40,
    "run_tests":   0.60,
    "git_diff":    0.20,
}
_DEFAULT_LATENCY = 0.18


def simulate_tool_call(tool_name: str, agent: Agent, tool_calls_so_far: int) -> Dict[str, Any]:
    """Return a mock tool result after a short simulated delay."""
    if tool_calls_so_far >= agent.budget.max_tool_calls:
        return {"error": "budget_exceeded", "tool": tool_name}

    latency = _TOOL_LATENCY.get(tool_name, _DEFAULT_LATENCY)
    time.sleep(latency)

    output = _TOOL_OUTPUTS.get(tool_name, f"mock output for {tool_name}")
    return {"output": output, "tool": tool_name}


# ---------------------------------------------------------------------------
# Mock agent executor
# ---------------------------------------------------------------------------

_AGENT_OUTPUTS: Dict[str, Dict[str, Any]] = {
    "requirements": {
        "text": (
            "## Acceptance Criteria\n- API returns 429 after 5 req/min per user.\n"
            "- Existing tests must pass.\n\n"
            "## Constraints\n- No public API contract changes.\n\n"
            "## Risks\n- In-memory store lost on restart."
        ),
        "artifacts": {"acceptance_criteria": "rate_limit=5rpm, return_429"},
        "tool_sequence": ["read_files", "list_files"],
    },
    "coder": {
        "text": (
            "## Files Changed\n- routes.py\n\n"
            "## Patch Summary\nAdded in-memory rate limiter dict keyed by user_id.\n\n"
            "## Risks\nNot persistent across restarts."
        ),
        "artifacts": {
            "code_patch": "diff --git a/routes.py b/routes.py\n+rate_limiter = {}",
        },
        "tool_sequence": ["read_files", "list_files", "edit_files", "run_tests", "git_diff"],
    },
    "tester": {
        "text": (
            "## Test Results\n5 existing + 2 new tests passed.\n\n"
            "## Failures\nNone.\n\n"
            "## Confidence\nHigh."
        ),
        "artifacts": {"test_results": {"passed": 7, "failed": 0}},
        "tool_sequence": ["read_files", "run_tests"],
    },
    "reviewer": {
        "text": (
            "## Approval\nApproved.\n\n"
            "## Concerns\nIn-memory store; acceptable for MVP.\n\n"
            "## Suggested Changes\nNone."
        ),
        "artifacts": {"review_notes": "approved"},
        "tool_sequence": ["read_files", "git_diff"],
    },
}

_DEFAULT_OUTPUT = {
    "text": "## Output\nTask completed.\n",
    "artifacts": {},
    "tool_sequence": ["read_files"],
}

# Non-core "specialist" agents all use the same minimal template:
# one read_files call so they contribute tool calls but don't dominate.
_SPECIALIST_OUTPUT = {
    "text": "## Assessment\nContext reviewed. No blocking concerns identified.\n",
    "artifacts": {},
    "tool_sequence": ["read_files"],
}

_SPECIALIST_KEYWORDS = (
    "stakeholder", "domain_expert", "feasibility", "risk_analyst",
    "architect", "security", "performance", "ux", "api_designer",
    "senior_coder", "integration", "db", "config",
    "unit_tester", "e2e_tester", "performance_tester", "security_tester",
    "senior_reviewer", "docs", "approval", "compliance",
)


# Synonyms that map an arbitrary (e.g. Gemini-designed) agent to one of the
# four core execution templates. Ordered by priority: the first core role whose
# synonym appears in the agent id/role wins. This lets semantically-named agents
# (developer_agent, architect_agent, qa_engineer…) produce the right artifacts so
# the scorer gets meaningful tests_pass / reviewer_acceptance signals.
_ROLE_SYNONYMS = [
    ("reviewer",     ("review", "approv", "sign-off", "signoff", "audit")),
    ("tester",       ("test", "qa ", "quality assur", "verif", "validat")),
    ("coder",        ("cod", "develop", "implement", "engineer", "program", "build")),
    ("requirements", ("requirement", "analy", "architect", "design", "plan",
                      "spec", "research", "scope")),
]


def _pick_template(agent: Agent) -> Dict[str, Any]:
    agent_id_lower = agent.id.lower()
    role_lower = (agent.role or "").lower()

    # 1. Exact core-template match by ID (requirements/coder/tester/reviewer).
    for key in _AGENT_OUTPUTS:
        if key in agent_id_lower:
            return _AGENT_OUTPUTS[key]

    # 2. Known specialist keyword in ID → minimal specialist template.
    for kw in _SPECIALIST_KEYWORDS:
        if kw in agent_id_lower:
            return _SPECIALIST_OUTPUT

    # 3. Synonym mapping against id + role → core template (handles
    #    Gemini-designed agents like developer_agent / qa_engineer / architect).
    haystack = agent_id_lower + " " + role_lower
    for core_key, synonyms in _ROLE_SYNONYMS:
        if any(syn in haystack for syn in synonyms):
            return _AGENT_OUTPUTS[core_key]

    # 4. Nothing matched → minimal specialist output (1 read_files).
    return _SPECIALIST_OUTPUT


def run_mock_agent(agent: Agent, on_tool_call=None) -> Dict[str, Any]:
    """Simulate a single agent execution with realistic per-tool latency.

    Honors agent.budget.max_tool_calls — mutations that tighten the budget
    genuinely reduce the number of tool calls made, which the gate can detect
    as an improvement and accept the candidate.

    on_tool_call: optional callable(tool_name, success) invoked immediately
    after each tool completes — lets the executor emit SSE events in real-time
    rather than in a burst after the whole agent returns.
    """
    template = _pick_template(agent)
    # Honour budget: truncate the tool sequence to the agent's allowed limit.
    # This means a budget-tightening mutation produces fewer tool calls → gate
    # sees improvement → accepts the candidate → next generation advances.
    max_calls = agent.budget.max_tool_calls
    full_sequence = template["tool_sequence"]
    tool_sequence = full_sequence[:max_calls]

    tool_calls: List[Dict[str, Any]] = []

    for i, tool_name in enumerate(tool_sequence):
        if tool_name not in agent.tools:
            tc = {"tool": tool_name, "result": {"error": "tool_not_permitted"}}
            tool_calls.append(tc)
            if on_tool_call:
                on_tool_call(tool_name, False)
            continue
        result = simulate_tool_call(tool_name, agent, i)
        tool_calls.append({"tool": tool_name, "result": result})
        if on_tool_call:
            on_tool_call(tool_name, "error" not in result)

    return {
        "tool_calls": tool_calls,
        "tool_call_count": len(tool_calls),
        "artifacts": template["artifacts"],
        "output_text": template["text"],
        "success": True,
    }
