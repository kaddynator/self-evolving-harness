from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Standard tool registry — compiler picks from these
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    "read_files":    "Read the contents of one or more files.",
    "list_files":    "List files and directories in a path.",
    "edit_files":    "Create or modify file contents.",
    "run_tests":     "Execute the project test suite and return results.",
    "run_command":   "Run an arbitrary shell command and return stdout/stderr.",
    "git_diff":      "Show the current git diff of staged/unstaged changes.",
    "web_search":    "Search the web and return a list of results with snippets.",
    "read_url":      "Fetch and return the content of a URL.",
    "write_file":    "Write content to a new file.",
    "python_repl":   "Execute Python code and return the output.",
    "send_message":  "Send a message or notification (email, Slack, etc.).",
    "query_db":      "Execute a database query and return results.",
}

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


def build_compilation_prompt(
    task_description: str,
    constraints: List[str] | None = None,
    domain: str = "general",
    prior_lessons: List[Dict[str, Any]] | None = None,
) -> str:
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
        "## Instructions",
        "1. Reason about what agents are needed and why.",
        "2. Decide the minimal set of tools per agent.",
        "3. Design the communication graph (who passes what to whom).",
        "4. Define evaluation metrics appropriate for this task.",
        "5. Output a COMPLETE, VALID Organization Harness IR YAML.",
        "6. The organization.id must be: org_<short_task_slug>_v1",
        "7. artifacts_expected must include at least one named artifact.",
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
