from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Standard tool registry — compiler picks from these
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    "read_files":    "Read the contents of one or more files.",
    "list_files":    "List files and directories in a path.",
    "edit_files":    "Replace a string in an existing file (targeted edit).",
    "write_file":    "Write content to a new or existing file.",
    "delete_file":   "Delete a file.",
    "run_tests":     "Execute the project test suite and return results.",
    "run_command":   "Run an arbitrary shell command and return stdout/stderr.",
    "python_repl":   "Execute Python code and return the output.",
    "git_diff":      "Show the current git diff of staged/unstaged changes.",
    "git_log":       "Show recent git commit history.",
    "web_search":    "Search the web and return a list of results with snippets.",
    "read_url":      "Fetch and return the content of a URL.",
    "query_db":      "Execute a database query and return results.",
    "send_message":  "Send a message or notification (email, Slack, etc.).",
}


# Default per-role tool assignment. Used by the compiler to give each agent a
# realistic toolset based on its role keyword, instead of a bare read_files.
ROLE_TOOLSETS = {
    "requirements": ["read_files", "list_files", "web_search", "read_url"],
    "analyst":      ["read_files", "list_files", "web_search", "read_url"],
    "architect":    ["read_files", "list_files", "web_search", "read_url"],
    "coder":        ["read_files", "list_files", "edit_files", "write_file", "run_command", "git_diff"],
    "developer":    ["read_files", "list_files", "edit_files", "write_file", "run_command", "git_diff"],
    "tester":       ["read_files", "list_files", "run_tests", "run_command", "python_repl"],
    "reviewer":     ["read_files", "git_diff", "git_log"],
    "db":           ["read_files", "list_files", "query_db"],
    "approval":     ["read_files", "send_message"],
    "compliance":   ["read_files", "send_message"],
}
_DEFAULT_TOOLSET = ["read_files", "list_files", "web_search"]


def tools_for_role(agent_id: str, role: str = "") -> list:
    """Pick a default toolset for an agent based on its id/role keywords."""
    hay = (agent_id + " " + (role or "")).lower()
    for key, tools in ROLE_TOOLSETS.items():
        if key in hay:
            return list(tools)
    return list(_DEFAULT_TOOLSET)

# ---------------------------------------------------------------------------
# IR schema — compact reference for Gemini
# ---------------------------------------------------------------------------

IR_SCHEMA_REFERENCE = """
Organization Harness IR — required top-level sections:

organization:
  id: string          # e.g. "org_<task_slug>_v1"
  name: string
  version: 1
  parent_id: null
  objective: string   # one-sentence goal
  domain: string      # e.g. software_engineering, research, data_pipeline
  constraints: []     # list of hard constraints
  assumptions: []

task:
  id: string
  title: string
  description: string
  inputs: {}          # key-value pairs the agents receive
  success_conditions: []   # list of verifiable conditions
  artifacts_expected: []   # artifact names agents must produce

agents:               # 2-5 agents; each must have a clear, non-overlapping role
  - id: string        # snake_case, ends in _agent
    name: string
    role: string      # one-sentence role description
    responsibilities: []
    prompt: |         # multi-line instruction to the agent
    tools: []         # subset of the tool registry
    budget:
      max_tool_calls: int
      max_runtime_seconds: int
    memory_policy:
      read_shared: true
      write_shared: true
    output_contract:
      type: string    # markdown, patch, json, text
      required_sections: []

communication:
  topology: custom_graph   # or linear, pipeline
  edges:
    - from: agent_id
      to: agent_id
      type: blocking       # or feedback
      artifact: string     # artifact name passed on this edge
  shared_memory:
    enabled: true
    store: []             # artifact keys stored in shared memory

execution:
  mode: phased
  phases:
    - name: string
      agents: []          # agent ids
      parallel: false
  retry_policy:
    max_retries: 1
    retry_on: []
  stopping_conditions:
    - all_success_conditions_met

runtime_policies:
  max_repeated_tool_errors: 2
  max_tool_calls_before_reflection: 20
  require_artifact_before_finish: true
  verify_before_conclude: true
  prevent_identical_retry: true
  exploration_to_implementation_threshold: 12

failure_recovery:
  on_tool_error: "Inspect the error, change strategy, do not repeat."
  on_missing_artifact: "Create the required artifact immediately."
  on_test_failure: "Read the failing assertion and make the smallest fix."
  on_timeout_risk: "Stop exploration and produce the best verified artifact."

evaluation:
  metrics:
    - name: string
      type: boolean | numeric
      source: string
      weight: float     # positive = good, negative = penalise
  binary_checks:
    - id: string
      question: string
      verifier: string
  scoring:
    formula: weighted_sum
    success_threshold: 70.0
  validation_gate:
    require_no_regression: []
    require_improvement_any: [total_score, tool_calls]
    max_runtime_seconds: 600

weakness_mining:
  enabled: true
  failure_signature_fields: [verifier_cause, agent_behavior, mechanism]
  clustering:
    method: exact_signature
    min_cluster_size: 1

mutation_policy:
  allowed_mutations:
    - add_agent
    - remove_agent
    - modify_prompt
    - modify_tools
    - reorder_edges
    - adjust_budget
    - modify_runtime_policy
    - modify_failure_recovery
  protected_components:
    - task.success_conditions
    - evaluation.validation_gate
  proposal_width: 3
  exploration_strategy: validation_gated_mutate_winner

observability:
  trace_level: detailed
  log_events:
    - agent_started
    - agent_finished
    - tool_called
    - artifact_created
    - evaluation_completed
  collect_artifacts: true
"""

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """\
You are a Harness Compiler for an AI organization optimizer.

Your job: given a task description, design the most efficient multi-agent workflow to accomplish it.

Rules:
- Use between 2 and 5 agents. More agents is NOT better — each must earn its place.
- Every agent must have a distinct, non-overlapping role.
- Assign only the tools each agent genuinely needs.
- Keep budgets tight: over-generous budgets hide inefficiency.
- The workflow must be executable end-to-end with no manual steps.
- Prefer linear pipelines unless parallelism is truly justified.
- Write a DETAILED, specialized `prompt` for each agent (aim for 15-40 lines):
  state the agent's identity, a concrete step-by-step methodology, the exact
  output format it must produce, edge cases to handle, and explicit do / don't
  rules. A one-line prompt is unacceptable — each agent should read like a
  focused operating manual for its role.
- Output ONLY valid YAML — no prose, no explanation, no markdown fences.
"""


# Per-domain hints so the synthesized workflow covers the responsibilities the
# evaluator scores. For software engineering the scorer rewards a passing test
# suite and an explicit code review, so the design should always include a
# testing agent and a review/approval agent (named clearly).
_DOMAIN_GUIDANCE = {
    "software_engineering": (
        "This is a software engineering task. The workflow MUST cover four core "
        "responsibilities, each as its own agent named accordingly:\n"
        "- requirements analysis (e.g. requirements_agent)\n"
        "- implementation / coding (e.g. coder_agent)\n"
        "- testing / verification (e.g. tester_agent)\n"
        "- code review and approval (e.g. reviewer_agent)\n"
        "You may add extra specialist agents, but these four roles must be present "
        "so the work can be implemented, tested, and reviewed end-to-end."
    ),
}


# Per-agent prompt detail levels. Threaded from RunRequest.prompt_detail so the
# operator can dial how much methodology each synthesized agent prompt carries.
PROMPT_DETAIL_LEVELS = ("brief", "detailed", "exhaustive")

_PROMPT_DETAIL_GUIDANCE = {
    "brief": (
        "Write a CONCISE `prompt` for each agent (aim for ~5-10 lines): state the "
        "agent's identity, its core responsibility, and 1-2 do/don't rules. Keep it "
        "tight — no extended methodology."
    ),
    "detailed": (
        "Write a DETAILED, specialized `prompt` for each agent (aim for ~15-40 lines): "
        "state the agent's identity, a concrete step-by-step methodology, the exact "
        "output format it must produce, edge cases to handle, and explicit do / don't "
        "rules. A one-line prompt is unacceptable — each agent should read like a "
        "focused operating manual for its role."
    ),
    "exhaustive": (
        "Write an EXHAUSTIVE, expert-level `prompt` for each agent (aim for ~40-80 lines): "
        "state the agent's identity and operating philosophy, a deep step-by-step "
        "methodology with rationale for each step, the exact output format with a "
        "worked example, an enumerated list of edge cases and how to handle each, "
        "explicit failure-handling and recovery procedures, and a comprehensive set of "
        "do / don't rules. Treat the prompt as a complete operating manual that a new "
        "specialist could follow with zero additional context."
    ),
}


def build_compilation_prompt(
    task_description: str,
    constraints: List[str] | None = None,
    domain: str = "general",
    prior_lessons: List[Dict[str, Any]] | None = None,
    prompt_detail: str = "detailed",
) -> str:
    if prompt_detail not in _PROMPT_DETAIL_GUIDANCE:
        prompt_detail = "detailed"
    detail_guidance = _PROMPT_DETAIL_GUIDANCE[prompt_detail]
    lines = [
        f"## Task",
        f"{task_description.strip()}",
        "",
        f"## Domain",
        domain,
        "",
    ]

    guidance = _DOMAIN_GUIDANCE.get(domain)
    if guidance:
        lines += ["## Domain guidance", guidance, ""]

    if constraints:
        lines += ["## Constraints"]
        lines += [f"- {c}" for c in constraints]
        lines += [""]

    if prior_lessons:
        lines += ["## Lessons from prior runs (use these to avoid known failure patterns)"]
        for lesson in prior_lessons[:5]:  # cap at 5 to stay within context
            for sig in lesson.get("failure_signatures", []):
                lines.append(
                    f"- {sig.get('mechanism')}: {sig.get('agent_behavior')} "
                    f"(cause: {sig.get('verifier_cause')})"
                )
        lines += [""]

    lines += [
        "## Available tools",
        *[f"- {name}: {desc}" for name, desc in TOOL_REGISTRY.items()],
        "",
        "## IR Schema (you must produce a YAML that conforms exactly to this)",
        IR_SCHEMA_REFERENCE,
        "",
        "## Agent prompt detail",
        detail_guidance,
        "",
        "## Instructions",
        "1. Reason about what agents are needed and why.",
        "2. Decide the minimal set of tools per agent.",
        "3. Design the communication graph (who passes what to whom).",
        "4. Define evaluation metrics appropriate for this task.",
        "5. Output a COMPLETE, VALID Organization Harness IR YAML.",
        "6. The organization.id must be: org_<short_task_slug>_v1",
        "7. artifacts_expected must include at least one named artifact.",
        "8. Each agent `prompt` must follow the 'Agent prompt detail' guidance above.",
        "",
        "Output ONLY the YAML. No explanation. No fences. Start with 'organization:'",
    ]

    return "\n".join(lines)


def build_retry_prompt(
    original_prompt: str,
    bad_yaml: str,
    validation_error: str,
) -> str:
    return (
        f"{original_prompt}\n\n"
        f"## Previous attempt failed validation\n\n"
        f"Error:\n{validation_error}\n\n"
        f"Bad output (first 500 chars):\n{bad_yaml[:500]}\n\n"
        f"Fix the YAML and output ONLY the corrected version. "
        f"Start with 'organization:'"
    )


# ---------------------------------------------------------------------------
# Prompt evolution — grow/specialize an agent's prompt in response to a weakness
# ---------------------------------------------------------------------------

_PROMPT_GROWTH_SYSTEM = (
    "You rewrite AI agent system prompts to be more detailed and specialized.\n"
    "Return ONLY the rewritten prompt text — no commentary, no fences."
)


def expand_agent_prompt(
    client,
    agent_name: str,
    agent_role: str,
    current_prompt: str,
    guidance: str,
) -> str:
    """Use the model to expand and specialize an agent's prompt.

    `guidance` describes the weakness to address (derived from a failure
    signature). Returns a strictly longer, more specialized prompt. Falls back
    to the original prompt on any error so callers can guard with a deterministic
    alternative.
    """
    if client is None:
        return current_prompt

    request = (
        f"# Agent: {agent_name}\n"
        f"## Role\n{agent_role}\n\n"
        f"## Current prompt\n{current_prompt}\n\n"
        f"## Why it must improve\n{guidance}\n\n"
        "## Task\n"
        "Rewrite the prompt so it is markedly more detailed and specialized for "
        "this role. Keep everything still-valid from the current prompt, then add: "
        "a clear identity, a concrete step-by-step methodology, the exact output "
        "format, edge cases to handle, and explicit do/don't rules. Target 25-60 "
        "lines. Directly address the weakness above. Output ONLY the new prompt."
    )
    try:
        new_prompt = client.generate(
            request,
            system_instruction=_PROMPT_GROWTH_SYSTEM,
            max_output_tokens=2048,
        ).strip()
    except Exception:
        return current_prompt

    # Guard: only accept if the model genuinely expanded the prompt.
    if len(new_prompt) <= len(current_prompt):
        return current_prompt
    return new_prompt
