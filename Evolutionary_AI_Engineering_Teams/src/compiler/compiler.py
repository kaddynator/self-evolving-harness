from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

import yaml

from src.ir.loader import load_harness_from_dict
from src.ir.schema import OrganizationHarness
from src.compiler.prompt import (
    SYSTEM_INSTRUCTION,
    build_compilation_prompt,
    build_retry_prompt,
    tools_for_role,
)

# Default model stamped on every compiled agent so the UI/artifact reflects the
# real model rather than falling back to "mock".
DEFAULT_AGENT_MODEL = "gemini-3.5-flash"


class CompilationError(Exception):
    pass


class HarnessCompiler:
    """Compiles a natural language task description into a valid OrganizationHarness IR.

    Uses Gemini to synthesize the initial workflow; retries up to `max_retries`
    times if the output fails schema validation, feeding the error back so
    Gemini can self-correct.

    Pass client=None to use mock mode (returns a sensible default harness).
    """

    def __init__(
        self,
        client=None,          # GeminiClient or None for mock
        max_retries: int = 2,
        temperature: float = 0.3,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._temperature = temperature

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(
        self,
        task_description: str,
        constraints: List[str] | None = None,
        domain: str = "general",
        prior_lessons: List[Dict[str, Any]] | None = None,
        num_agents: Optional[int] = None,
        prompt_detail: str = "detailed",
        optimize_models: bool = True,
    ) -> OrganizationHarness:
        """Synthesize an OrganizationHarness from a task description.

        Falls back to mock_compile() when no Gemini client is set.

        prompt_detail ("brief" | "detailed" | "exhaustive") controls how much
        methodology each synthesized agent prompt carries. optimize_models, when
        True, lets the evolution engine explore the Gemini model pool per agent
        (it is recorded here so downstream consumers can honor it).
        """
        if self._client is None:
            return self._mock_compile(
                task_description, constraints or [], domain,
                num_agents=num_agents, prompt_detail=prompt_detail,
                optimize_models=optimize_models,
            )

        prompt = build_compilation_prompt(
            task_description,
            constraints=constraints,
            domain=domain,
            prior_lessons=prior_lessons,
            prompt_detail=prompt_detail,
        )

        last_error = ""
        last_raw = ""

        # Scale the output budget to the requested prompt detail: exhaustive
        # prompts (40-80 lines × several agents) easily overflow 8192 tokens and
        # truncate the YAML, which fails compilation. Give them ample headroom.
        _MAX_TOKENS_BY_DETAIL = {"brief": 8192, "detailed": 12288, "exhaustive": 32768}
        max_tokens = _MAX_TOKENS_BY_DETAIL.get(prompt_detail, 12288)

        for attempt in range(self._max_retries + 1):
            if attempt == 0:
                current_prompt = prompt
            else:
                current_prompt = build_retry_prompt(prompt, last_raw, last_error)

            raw = self._client.generate(
                current_prompt,
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=self._temperature,
                max_output_tokens=max_tokens,  # scaled by prompt_detail
                thinking_budget=0,             # disable thinking so output isn't truncated
            )

            harness, error = self._parse_and_validate(raw)
            if harness is not None:
                # Gemini designs the agents / prompts / phases / topology, but it
                # also invents its own evaluation metrics and artifact names that
                # the deterministic mock engine can't score. Normalize the
                # evaluation contract to the canonical one so runs produce
                # meaningful, comparable scores — then honour an explicit agent
                # count if one was requested.
                raw_dict = harness.model_dump(mode="python")
                raw_dict = _normalize_for_mock_scoring(raw_dict)
                # Normalize Gemini's invented org id to the short, stable scheme
                # (wf-<slug>) so it stays readable and constant across generations.
                raw_dict.setdefault("organization", {})["id"] = _make_short_id(task_description)
                if num_agents is not None and num_agents > 0:
                    raw_dict = _expand_agents(raw_dict, num_agents)
                harness = load_harness_from_dict(raw_dict)
                return harness

            last_raw = raw
            last_error = error

        raise CompilationError(
            f"Gemini failed to produce a valid harness after "
            f"{self._max_retries + 1} attempts.\n"
            f"Last error: {last_error}\n"
            f"Last output (first 800 chars):\n{last_raw[:800]}"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_and_validate(
        self, raw: str
    ) -> tuple[Optional[OrganizationHarness], str]:
        """Try to extract YAML and validate it. Returns (harness, "") or (None, error)."""
        yaml_text = self._extract_yaml(raw)
        if not yaml_text:
            return None, "Response contained no parseable YAML."

        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            return None, f"YAML parse error: {e}"

        if not isinstance(data, dict):
            return None, f"Expected a YAML mapping, got {type(data).__name__}."

        try:
            harness = load_harness_from_dict(data)
            return harness, ""
        except ValueError as e:
            return None, str(e)

    def _extract_yaml(self, text: str) -> str:
        """Pull YAML out of the response.

        Handles:
        - Raw YAML starting with 'organization:'
        - YAML wrapped in ```yaml ... ``` fences
        - YAML wrapped in ``` ... ``` fences
        """
        # Try fenced block first
        fenced = re.search(r"```(?:yaml)?\s*\n(.*?)```", text, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()

        # Try raw — find first line starting with 'organization:'
        lines = text.splitlines()
        start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("organization:"):
                start = i
                break

        if start is not None:
            return "\n".join(lines[start:]).strip()

        return ""

    # ------------------------------------------------------------------
    # Mock compiler — no Gemini needed
    # ------------------------------------------------------------------

    def _mock_compile(
        self,
        task_description: str,
        constraints: List[str],
        domain: str,
        num_agents: Optional[int] = None,
        prompt_detail: str = "detailed",
        optimize_models: bool = True,
    ) -> OrganizationHarness:
        """Generate a sensible default harness based on task keywords.

        prompt_detail / optimize_models are accepted for API parity with the
        Gemini path; the deterministic mock uses fixed template prompts so the
        detail level does not change its output (keeps tests deterministic).
        """
        slug = _make_slug(task_description)
        template = _pick_template(task_description, domain)
        data = template(slug, task_description, constraints)
        # Stamp the short, stable workflow id (wf-<slug>) over the template's id.
        data["organization"]["id"] = _make_short_id(task_description)
        if num_agents is not None and num_agents > 0:
            data = _expand_agents(data, num_agents)
        return load_harness_from_dict(data)


# ---------------------------------------------------------------------------
# Template helpers for mock mode
# ---------------------------------------------------------------------------

def _make_slug(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    return "_".join(words[:4]) if words else "task"


# Common filler words that add no signal to a short workflow id.
_STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "and", "or", "with", "in", "on",
    "per", "by", "implement", "add", "build", "create", "make", "fix",
    "write", "design", "develop", "support", "feature", "system", "new",
}


def _make_short_id(text: str) -> str:
    """Derive a short, stable workflow id from the task description.

    Produces ``wf-<slug>`` where ``<slug>`` is a 4-24 char kebab-case label
    built from the most meaningful words in the task. The id stays constant
    across generations — versioning is tracked by organization.version, not by
    appending ``_v2_v3`` suffixes.
    """
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    keep = [w for w in words if w not in _STOPWORDS]
    if not keep:
        keep = words
    slug = "".join(keep[:2]) if keep else "task"
    slug = slug[:24] or "task"
    return f"wf-{slug}"


def _pick_template(task: str, domain: str):
    # Explicit domain wins — this is the primary dispatch path.
    _DOMAIN_MAP = {
        "software_engineering": _software_engineering_template,
        "research":             _research_template,
        "data_pipeline":        _data_pipeline_template,
        "bloated_engineering":  _bloated_engineering_template,
    }
    if domain in _DOMAIN_MAP:
        return _DOMAIN_MAP[domain]
    # Fallback: infer from task keywords when domain="general".
    task_lower = task.lower()
    if any(w in task_lower for w in ("code", "implement", "fix", "build", "add", "refactor")):
        return _software_engineering_template
    if any(w in task_lower for w in ("research", "analyze", "compare", "report", "summarize")):
        return _research_template
    if any(w in task_lower for w in ("scrape", "fetch", "pipeline", "etl", "data")):
        return _data_pipeline_template
    return _general_template


def _software_engineering_template(slug, task, constraints):
    return {
        "organization": {
            "id": f"org_{slug}_v1",
            "name": "SoftwareEngineeringHarness",
            "version": 1,
            "parent_id": None,
            "objective": task,
            "domain": "software_engineering",
            "constraints": constraints or ["Keep existing tests passing."],
            "assumptions": ["The repository has a working test command."],
        },
        "task": {
            "id": f"task_{slug}",
            "title": task[:60],
            "description": task,
            "inputs": {"repo_path": "/workspace/repo", "test_command": "pytest"},
            "success_conditions": ["Existing tests pass.", "New feature works."],
            "artifacts_expected": ["code_patch", "test_results", "execution_trace"],
        },
        "agents": [
            {
                "id": "requirements_agent",
                "name": "Requirements Agent",
                "role": "Extract acceptance criteria from the task.",
                "responsibilities": ["Read task.", "Identify requirements.", "Identify constraints."],
                "prompt": "You are the Requirements Agent.\nExtract clear acceptance criteria.\nDo not write code.",
                "tools": ["read_files", "list_files"],
                "budget": {"max_tool_calls": 8, "max_runtime_seconds": 120},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Acceptance Criteria", "Constraints", "Risks"]},
            },
            {
                "id": "coder_agent",
                "name": "Coder Agent",
                "role": "Implement the required change with the smallest safe patch.",
                "responsibilities": ["Read acceptance criteria.", "Implement feature.", "Run tests."],
                "prompt": "You are the Coder Agent.\nImplement the smallest working patch.\nDo not change unrelated files.",
                "tools": ["read_files", "list_files", "edit_files", "run_tests", "git_diff"],
                "budget": {"max_tool_calls": 20, "max_runtime_seconds": 300},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "patch", "required_sections": ["Files Changed", "Patch Summary", "Risks"]},
            },
            {
                "id": "tester_agent",
                "name": "Tester Agent",
                "role": "Run the test suite and confirm the patch is correct.",
                "responsibilities": ["Run tests.", "Report failures."],
                "prompt": "You are the Tester Agent.\nVerify the patch. Report failures clearly.",
                "tools": ["read_files", "run_tests"],
                "budget": {"max_tool_calls": 10, "max_runtime_seconds": 180},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Test Results", "Failures", "Confidence"]},
            },
            {
                "id": "reviewer_agent",
                "name": "Reviewer Agent",
                "role": "Review the patch for quality and approve or reject it.",
                "responsibilities": ["Read the diff.", "Assess quality.", "Approve or request changes."],
                "prompt": "You are the Reviewer Agent.\nReview the patch for correctness and style.\nApprove if it meets the criteria.",
                "tools": ["read_files", "git_diff"],
                "budget": {"max_tool_calls": 5, "max_runtime_seconds": 120},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Approval", "Concerns", "Suggested Changes"]},
            },
        ],
        "communication": {
            "topology": "custom_graph",
            "edges": [
                {"from": "requirements_agent", "to": "coder_agent",  "type": "blocking", "artifact": "acceptance_criteria"},
                {"from": "coder_agent",         "to": "tester_agent", "type": "blocking", "artifact": "code_patch"},
                {"from": "tester_agent",        "to": "reviewer_agent", "type": "blocking", "artifact": "test_results"},
            ],
            "shared_memory": {"enabled": True, "store": ["acceptance_criteria", "code_patch", "test_results", "review_notes"]},
        },
        "execution": {
            "mode": "phased",
            "phases": [
                {"name": "understand", "agents": ["requirements_agent"], "parallel": False},
                {"name": "implement",  "agents": ["coder_agent"],        "parallel": False},
                {"name": "verify",     "agents": ["tester_agent"],       "parallel": False},
                {"name": "review",     "agents": ["reviewer_agent"],     "parallel": False},
            ],
            "retry_policy": {"max_retries": 1, "retry_on": ["tests_failed"]},
            "stopping_conditions": ["all_success_conditions_met"],
        },
        **_common_sections(),
    }


def _research_template(slug, task, constraints):
    return {
        "organization": {
            "id": f"org_{slug}_v1",
            "name": "ResearchHarness",
            "version": 1,
            "parent_id": None,
            "objective": task,
            "domain": "research",
            "constraints": constraints or ["Cite all sources.", "Be factually accurate."],
            "assumptions": ["Web search is available."],
        },
        "task": {
            "id": f"task_{slug}",
            "title": task[:60],
            "description": task,
            "inputs": {},
            "success_conditions": ["Report is complete.", "Sources are cited.", "Key findings are clear."],
            "artifacts_expected": ["research_notes", "final_report", "execution_trace"],
        },
        "agents": [
            {
                "id": "researcher_agent",
                "name": "Researcher Agent",
                "role": "Search for and collect relevant sources and information.",
                "responsibilities": ["Search the web.", "Fetch source content.", "Summarize findings."],
                "prompt": "You are the Researcher Agent.\nSearch for information relevant to the task.\nCollect sources and key facts. Do not write the final report.",
                "tools": ["web_search", "read_url"],
                "budget": {"max_tool_calls": 15, "max_runtime_seconds": 240},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Sources", "Key Facts", "Gaps"]},
            },
            {
                "id": "analyst_agent",
                "name": "Analyst Agent",
                "role": "Analyze collected research and extract insights.",
                "responsibilities": ["Read research notes.", "Identify patterns.", "Draw conclusions."],
                "prompt": "You are the Analyst Agent.\nAnalyze the research notes and extract key insights.\nIdentify patterns and draw evidence-backed conclusions.",
                "tools": ["read_files"],
                "budget": {"max_tool_calls": 5, "max_runtime_seconds": 120},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Insights", "Comparisons", "Conclusions"]},
            },
            {
                "id": "writer_agent",
                "name": "Writer Agent",
                "role": "Produce the final structured report.",
                "responsibilities": ["Read analysis.", "Write the report.", "Cite sources."],
                "prompt": "You are the Writer Agent.\nWrite a clear, structured report based on the analysis.\nCite all sources. Be concise.",
                "tools": ["write_file"],
                "budget": {"max_tool_calls": 3, "max_runtime_seconds": 120},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Summary", "Findings", "Sources"]},
            },
        ],
        "communication": {
            "topology": "custom_graph",
            "edges": [
                {"from": "researcher_agent", "to": "analyst_agent", "type": "blocking", "artifact": "research_notes"},
                {"from": "analyst_agent", "to": "writer_agent", "type": "blocking", "artifact": "analysis"},
            ],
            "shared_memory": {"enabled": True, "store": ["research_notes", "analysis", "final_report"]},
        },
        "execution": {
            "mode": "phased",
            "phases": [
                {"name": "research", "agents": ["researcher_agent"], "parallel": False},
                {"name": "analyze", "agents": ["analyst_agent"], "parallel": False},
                {"name": "write", "agents": ["writer_agent"], "parallel": False},
            ],
            "retry_policy": {"max_retries": 1, "retry_on": []},
            "stopping_conditions": ["all_success_conditions_met"],
        },
        **_common_sections(),
    }


def _data_pipeline_template(slug, task, constraints):
    return {
        "organization": {
            "id": f"org_{slug}_v1",
            "name": "DataPipelineHarness",
            "version": 1,
            "parent_id": None,
            "objective": task,
            "domain": "data_pipeline",
            "constraints": constraints or ["Handle errors gracefully.", "Log all steps."],
            "assumptions": ["Network and storage are available."],
        },
        "task": {
            "id": f"task_{slug}",
            "title": task[:60],
            "description": task,
            "inputs": {},
            "success_conditions": ["Data is fetched.", "Data is stored.", "Summary is produced."],
            "artifacts_expected": ["raw_data", "processed_data", "summary_report", "execution_trace"],
        },
        "agents": [
            {
                "id": "fetcher_agent",
                "name": "Fetcher Agent",
                "role": "Collect raw data from the source.",
                "responsibilities": ["Fetch data.", "Validate structure.", "Store raw output."],
                "prompt": "You are the Fetcher Agent.\nCollect raw data from the source.\nValidate its structure and store it.",
                "tools": ["web_search", "read_url", "run_command"],
                "budget": {"max_tool_calls": 15, "max_runtime_seconds": 240},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "json", "required_sections": ["Records", "Source", "Errors"]},
            },
            {
                "id": "processor_agent",
                "name": "Processor Agent",
                "role": "Clean, transform, and store the data.",
                "responsibilities": ["Read raw data.", "Clean and normalize.", "Store processed output."],
                "prompt": "You are the Processor Agent.\nClean and transform the raw data.\nStore the processed output.",
                "tools": ["python_repl", "write_file", "query_db"],
                "budget": {"max_tool_calls": 10, "max_runtime_seconds": 180},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "json", "required_sections": ["Processed Records", "Transformations", "Errors"]},
            },
            {
                "id": "reporter_agent",
                "name": "Reporter Agent",
                "role": "Produce a summary report of the pipeline run.",
                "responsibilities": ["Read processed data.", "Compute statistics.", "Write summary."],
                "prompt": "You are the Reporter Agent.\nProduce a concise summary of what was fetched and stored.",
                "tools": ["read_files", "write_file"],
                "budget": {"max_tool_calls": 5, "max_runtime_seconds": 60},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Summary", "Statistics", "Errors"]},
            },
        ],
        "communication": {
            "topology": "custom_graph",
            "edges": [
                {"from": "fetcher_agent", "to": "processor_agent", "type": "blocking", "artifact": "raw_data"},
                {"from": "processor_agent", "to": "reporter_agent", "type": "blocking", "artifact": "processed_data"},
            ],
            "shared_memory": {"enabled": True, "store": ["raw_data", "processed_data", "summary_report"]},
        },
        "execution": {
            "mode": "phased",
            "phases": [
                {"name": "fetch", "agents": ["fetcher_agent"], "parallel": False},
                {"name": "process", "agents": ["processor_agent"], "parallel": False},
                {"name": "report", "agents": ["reporter_agent"], "parallel": False},
            ],
            "retry_policy": {"max_retries": 2, "retry_on": ["fetch_failed"]},
            "stopping_conditions": ["all_success_conditions_met"],
        },
        **_common_sections(),
    }


def _general_template(slug, task, constraints):
    return {
        "organization": {
            "id": f"org_{slug}_v1",
            "name": "GeneralHarness",
            "version": 1,
            "parent_id": None,
            "objective": task,
            "domain": "general",
            "constraints": constraints or [],
            "assumptions": [],
        },
        "task": {
            "id": f"task_{slug}",
            "title": task[:60],
            "description": task,
            "inputs": {},
            "success_conditions": ["Task is completed.", "Output artifact is produced."],
            "artifacts_expected": ["output", "execution_trace"],
        },
        "agents": [
            {
                "id": "planner_agent",
                "name": "Planner Agent",
                "role": "Break the task into clear subtasks.",
                "responsibilities": ["Read the task.", "Identify subtasks.", "Define success criteria."],
                "prompt": "You are the Planner Agent.\nBreak the task into clear, actionable subtasks.\nDo not execute anything yet.",
                "tools": ["read_files"],
                "budget": {"max_tool_calls": 5, "max_runtime_seconds": 60},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Plan", "Subtasks", "Success Criteria"]},
            },
            {
                "id": "executor_agent",
                "name": "Executor Agent",
                "role": "Execute the plan and produce the output.",
                "responsibilities": ["Follow the plan.", "Produce the output artifact."],
                "prompt": "You are the Executor Agent.\nFollow the plan and complete the task.\nProduce the required output artifact.",
                "tools": ["read_files", "write_file", "run_command", "web_search"],
                "budget": {"max_tool_calls": 20, "max_runtime_seconds": 300},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "text", "required_sections": ["Output", "Steps Taken"]},
            },
            {
                "id": "verifier_agent",
                "name": "Verifier Agent",
                "role": "Confirm the output meets the success criteria.",
                "responsibilities": ["Read the output.", "Check success criteria.", "Flag failures."],
                "prompt": "You are the Verifier Agent.\nCheck that the output meets all success criteria.\nBe strict.",
                "tools": ["read_files"],
                "budget": {"max_tool_calls": 5, "max_runtime_seconds": 60},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Verdict", "Checks", "Issues"]},
            },
        ],
        "communication": {
            "topology": "custom_graph",
            "edges": [
                {"from": "planner_agent", "to": "executor_agent", "type": "blocking", "artifact": "plan"},
                {"from": "executor_agent", "to": "verifier_agent", "type": "blocking", "artifact": "output"},
            ],
            "shared_memory": {"enabled": True, "store": ["plan", "output"]},
        },
        "execution": {
            "mode": "phased",
            "phases": [
                {"name": "plan", "agents": ["planner_agent"], "parallel": False},
                {"name": "execute", "agents": ["executor_agent"], "parallel": False},
                {"name": "verify", "agents": ["verifier_agent"], "parallel": False},
            ],
            "retry_policy": {"max_retries": 1, "retry_on": []},
            "stopping_conditions": ["all_success_conditions_met"],
        },
        **_common_sections(),
    }


_SPECIALIST_POOL = [
    ("analyst_agent",      "Analysis Agent",      "Analyse context and surface key patterns."),
    ("risk_agent",         "Risk Agent",           "Identify and assess implementation risks."),
    ("security_agent",     "Security Agent",       "Review security implications of the change."),
    ("performance_agent",  "Performance Agent",    "Assess performance impact of the implementation."),
    ("integration_agent",  "Integration Agent",    "Verify integration points with existing systems."),
    ("docs_agent",         "Documentation Agent",  "Ensure documentation is updated for the change."),
    ("architect_agent",    "Architect Agent",      "Evaluate the high-level design decisions."),
    ("ux_agent",           "UX Agent",             "Review usability and user-facing impacts."),
    ("compliance_agent",   "Compliance Agent",     "Check that the change meets compliance requirements."),
    ("db_agent",           "Database Agent",       "Review database schema and query impacts."),
    ("config_agent",       "Config Agent",         "Review configuration and environment changes."),
    ("api_designer_agent", "API Designer Agent",   "Design and validate the public API contract."),
    ("observability_agent","Observability Agent",  "Ensure adequate logging, metrics, and tracing."),
    ("deployment_agent",   "Deployment Agent",     "Review deployment and rollout strategy."),
    ("senior_reviewer_agent","Senior Reviewer Agent","Provide senior-level code review."),
    ("load_tester_agent",  "Load Test Agent",      "Define load and stress test scenarios."),
    ("e2e_tester_agent",   "E2E Tester Agent",     "Design end-to-end test scenarios."),
    ("approval_agent",     "Approval Agent",       "Final approval sign-off from product perspective."),
    ("stakeholder_agent",  "Stakeholder Agent",    "Capture stakeholder priorities and business value."),
    ("feasibility_agent",  "Feasibility Agent",    "Assess technical feasibility of the approach."),
    ("dependency_agent",   "Dependency Agent",     "Audit dependency changes and version compatibility."),
    ("rollback_agent",     "Rollback Agent",       "Define rollback plan and recovery steps."),
    ("monitoring_agent",   "Monitoring Agent",     "Set up dashboards and alerting for the change."),
    ("code_quality_agent", "Code Quality Agent",   "Check code style, complexity, and coverage."),
    ("domain_expert_agent","Domain Expert Agent",  "Provide domain-specific knowledge and constraints."),
    ("unit_tester_agent",  "Unit Tester Agent",    "Write and validate unit tests for the patch."),
]


def _normalize_for_mock_scoring(data: dict) -> dict:
    """Swap a (Gemini-designed) harness's evaluation contract for the canonical
    one the deterministic mock engine understands.

    Gemini freely invents metric names (code_quality, test_coverage…) and
    artifact filenames (webhook_handler.py…) that the mock scorer can't map to
    its fixed raw metrics, producing a 0.0 score. We preserve everything that
    makes the workflow interesting — agents, prompts, responsibilities, phases,
    topology, edges — and only standardize the scoring surfaces so runs are
    scorable and comparable across generations.
    """
    import copy
    data = copy.deepcopy(data)

    # Canonical artifacts the mock executor actually emits.
    data.setdefault("task", {})
    data["task"]["artifacts_expected"] = ["code_patch", "test_results", "execution_trace"]

    # Canonical evaluation block (same as the software_engineering template).
    data["evaluation"] = {
        "metrics": [
            {"name": "tests_pass",          "type": "boolean", "source": "tester_agent",   "weight": 50},
            {"name": "reviewer_acceptance", "type": "boolean", "source": "reviewer_agent", "weight": 30},
            {"name": "tool_calls",          "type": "numeric", "source": "runtime_trace",  "weight": -1},
        ],
        "binary_checks": [
            {"id": "output_produced",      "question": "Was the required output artifact produced?", "verifier": "artifact_check"},
            {"id": "success_criteria_met", "question": "Do all success conditions pass?",            "verifier": "llm_judge"},
        ],
        "scoring": {"formula": "weighted_sum", "success_threshold": 70.0},
        "validation_gate": {
            "require_no_regression": ["tests_pass"],
            "require_improvement_any": ["total_score", "tool_calls"],
            "max_runtime_seconds": 600,
        },
    }

    # Ensure the evolution operators we rely on are permitted.
    mp = data.setdefault("mutation_policy", {})
    allowed = set(mp.get("allowed_mutations", []) or [])
    allowed.update({
        "remove_agent", "modify_prompt", "adjust_budget",
        "modify_tools", "modify_runtime_policy", "change_model",
    })
    mp["allowed_mutations"] = sorted(allowed)
    mp.setdefault("protected_components", ["task.success_conditions", "evaluation.validation_gate"])
    mp.setdefault("proposal_width", 3)
    mp.setdefault("exploration_strategy", "validation_gated_mutate_winner")

    # Stamp the real model on every agent and guarantee each has at least its
    # role's core toolset (union with whatever the model already assigned), so
    # no agent is left under-equipped (e.g. a coder with only write_file).
    for agent in data.get("agents", []):
        if not agent.get("model"):
            agent["model"] = DEFAULT_AGENT_MODEL
        role_tools = tools_for_role(agent.get("id", ""), agent.get("role", ""))
        existing = agent.get("tools") or []
        merged = list(existing)
        for t in role_tools:
            if t not in merged:
                merged.append(t)
        agent["tools"] = merged

    return data


def _expand_agents(data: dict, target: int) -> dict:
    """Pad or trim the harness so it has exactly `target` agents.

    Core agents (requirements, coder, tester, reviewer) are never removed.
    Specialist agents are added from _SPECIALIST_POOL or trimmed if there are
    already more than target.
    """
    import copy
    data = copy.deepcopy(data)
    agents: list = data.get("agents", [])
    phases: list = data.get("execution", {}).get("phases", [])

    core_ids = {a["id"] for a in agents if any(
        kw in a["id"] for kw in ("requirements", "coder", "tester", "reviewer")
    )}

    current = len(agents)
    if current == target:
        return data

    # Need to add specialists
    if target > current:
        existing_ids = {a["id"] for a in agents}
        pool = [(aid, name, role) for aid, name, role in _SPECIALIST_POOL if aid not in existing_ids]
        to_add = target - current
        # Distribute across existing phases (round-robin)
        phase_names = [p["name"] for p in phases] if phases else ["implement"]
        for i, (aid, name, role) in enumerate(pool[:to_add]):
            agents.append(_minimal_agent(aid, name, role))
            # Add to a phase (round-robin across phases)
            phase = phases[i % len(phases)] if phases else None
            if phase:
                phase["agents"].append(aid)
        data["agents"] = agents

    # Need to remove non-core specialists
    elif target < current:
        non_core = [a for a in agents if a["id"] not in core_ids]
        to_remove = current - target
        remove_ids = {a["id"] for a in non_core[:to_remove]}
        data["agents"] = [a for a in agents if a["id"] not in remove_ids]
        for phase in phases:
            phase["agents"] = [aid for aid in phase.get("agents", []) if aid not in remove_ids]
        # Remove edges referencing removed agents
        edges = data.get("communication", {}).get("edges", [])
        data["communication"]["edges"] = [
            e for e in edges
            if e.get("from_agent") not in remove_ids and e.get("to") not in remove_ids
        ]

    return data


def _minimal_agent(agent_id: str, name: str, role: str) -> dict:
    """Helper for non-core specialist agents with a role-appropriate toolset."""
    return {
        "id": agent_id,
        "name": name,
        "role": role,
        "responsibilities": ["Read relevant context.", "Provide specialist input."],
        "prompt": f"You are the {name}.\n{role}\nRead the context and provide your specialist assessment.",
        "model": DEFAULT_AGENT_MODEL,
        "tools": tools_for_role(agent_id, role),
        "budget": {"max_tool_calls": 3, "max_runtime_seconds": 60},
        "memory_policy": {"read_shared": True, "write_shared": False},
        "output_contract": {"type": "markdown", "required_sections": ["Assessment"]},
    }


def _bloated_engineering_template(slug, task, constraints):
    """30-agent over-engineered harness for demonstrating agent-reduction evolution."""
    phases = [
        # Phase 1: Understand (5 agents)
        {
            "name": "understand",
            "agents": [
                "requirements_agent", "stakeholder_agent", "domain_expert_agent",
                "feasibility_agent", "risk_analyst_agent",
            ],
        },
        # Phase 2: Design (5 agents)
        {
            "name": "design",
            "agents": [
                "architect_agent", "security_agent", "performance_agent",
                "ux_agent", "api_designer_agent",
            ],
        },
        # Phase 3: Implement (5 agents)
        {
            "name": "implement",
            "agents": [
                "coder_agent", "senior_coder_agent", "integration_agent",
                "db_agent", "config_agent",
            ],
        },
        # Phase 4: Verify (5 agents)
        {
            "name": "verify",
            "agents": [
                "tester_agent", "unit_tester_agent", "e2e_tester_agent",
                "performance_tester_agent", "security_tester_agent",
            ],
        },
        # Phase 5: Review (5 agents)
        {
            "name": "review",
            "agents": [
                "reviewer_agent", "senior_reviewer_agent", "docs_agent",
                "approval_agent", "compliance_agent",
            ],
        },
    ]

    agents = [
        # Core agents
        {
            "id": "requirements_agent",
            "name": "Requirements Agent",
            "role": "Extract acceptance criteria from the task.",
            "responsibilities": ["Read task.", "Identify requirements.", "Identify constraints."],
            "prompt": "You are the Requirements Agent.\nExtract clear acceptance criteria.\nDo not write code.",
            "tools": ["read_files", "list_files"],
            "budget": {"max_tool_calls": 6, "max_runtime_seconds": 120},
            "memory_policy": {"read_shared": True, "write_shared": True},
            "output_contract": {"type": "markdown", "required_sections": ["Acceptance Criteria", "Constraints"]},
        },
        {
            "id": "coder_agent",
            "name": "Coder Agent",
            "role": "Implement the required change with the smallest safe patch.",
            "responsibilities": ["Read acceptance criteria.", "Implement feature.", "Run tests."],
            "prompt": "You are the Coder Agent.\nImplement the smallest working patch.\nDo not change unrelated files.",
            "tools": ["read_files", "list_files", "edit_files", "run_tests", "git_diff"],
            "budget": {"max_tool_calls": 20, "max_runtime_seconds": 300},
            "memory_policy": {"read_shared": True, "write_shared": True},
            "output_contract": {"type": "patch", "required_sections": ["Files Changed", "Patch Summary"]},
        },
        {
            "id": "tester_agent",
            "name": "Tester Agent",
            "role": "Run the test suite and confirm the patch is correct.",
            "responsibilities": ["Run tests.", "Report failures."],
            "prompt": "You are the Tester Agent.\nVerify the patch. Report failures clearly.",
            "tools": ["read_files", "run_tests"],
            "budget": {"max_tool_calls": 8, "max_runtime_seconds": 180},
            "memory_policy": {"read_shared": True, "write_shared": True},
            "output_contract": {"type": "markdown", "required_sections": ["Test Results", "Failures"]},
        },
        {
            "id": "reviewer_agent",
            "name": "Reviewer Agent",
            "role": "Review the patch for quality and approve or reject it.",
            "responsibilities": ["Read the diff.", "Assess quality.", "Approve or request changes."],
            "prompt": "You are the Reviewer Agent.\nReview the patch for correctness and style.\nApprove if it meets the criteria.",
            "tools": ["read_files", "git_diff"],
            "budget": {"max_tool_calls": 4, "max_runtime_seconds": 120},
            "memory_policy": {"read_shared": True, "write_shared": True},
            "output_contract": {"type": "markdown", "required_sections": ["Approval", "Concerns"]},
        },
        # Non-core agents (should be removed by evolution)
        _minimal_agent("stakeholder_agent", "Stakeholder Agent", "Capture stakeholder priorities and business value."),
        _minimal_agent("domain_expert_agent", "Domain Expert Agent", "Provide domain-specific knowledge and constraints."),
        _minimal_agent("feasibility_agent", "Feasibility Agent", "Assess technical feasibility of the proposed approach."),
        _minimal_agent("risk_analyst_agent", "Risk Analyst Agent", "Identify and assess implementation risks."),
        _minimal_agent("architect_agent", "Architect Agent", "Propose the high-level system design."),
        _minimal_agent("security_agent", "Security Agent", "Identify security concerns in the design."),
        _minimal_agent("performance_agent", "Performance Agent", "Assess performance implications of the design."),
        _minimal_agent("ux_agent", "UX Agent", "Review user experience considerations."),
        _minimal_agent("api_designer_agent", "API Designer Agent", "Design the public API contract."),
        _minimal_agent("senior_coder_agent", "Senior Coder Agent", "Provide senior engineering guidance on the implementation."),
        _minimal_agent("integration_agent", "Integration Agent", "Verify integration points with existing systems."),
        _minimal_agent("db_agent", "Database Agent", "Review database schema and query impacts."),
        _minimal_agent("config_agent", "Config Agent", "Review configuration and environment variable changes."),
        _minimal_agent("unit_tester_agent", "Unit Tester Agent", "Write and validate unit tests for the patch."),
        _minimal_agent("e2e_tester_agent", "E2E Tester Agent", "Design end-to-end test scenarios."),
        _minimal_agent("performance_tester_agent", "Performance Tester Agent", "Assess performance test coverage."),
        _minimal_agent("security_tester_agent", "Security Tester Agent", "Run security-focused test checks."),
        _minimal_agent("senior_reviewer_agent", "Senior Reviewer Agent", "Provide senior-level code review."),
        _minimal_agent("docs_agent", "Documentation Agent", "Update documentation for the change."),
        _minimal_agent("approval_agent", "Approval Agent", "Final approval sign-off from product owner perspective."),
        _minimal_agent("compliance_agent", "Compliance Agent", "Check that the change meets compliance requirements."),
    ]

    # Build edges: chain phases sequentially (last agent of each phase → first of next)
    edges = []
    for i in range(len(phases) - 1):
        from_phase_last = phases[i]["agents"][-1]
        to_phase_first = phases[i + 1]["agents"][0]
        edges.append({
            "from": from_phase_last,
            "to": to_phase_first,
            "type": "blocking",
            "artifact": None,
        })
    # Also wire core agent chain within phases
    core_chain = [
        ("requirements_agent", "coder_agent", "acceptance_criteria"),
        ("coder_agent", "tester_agent", "code_patch"),
        ("tester_agent", "reviewer_agent", "test_results"),
    ]
    for from_id, to_id, artifact in core_chain:
        edges.append({"from": from_id, "to": to_id, "type": "blocking", "artifact": artifact})

    shared_store = [
        "acceptance_criteria", "code_patch", "test_results", "review_notes",
        "design_notes", "risk_assessment", "execution_trace",
    ]

    return {
        "organization": {
            "id": f"org_{slug}_bloated_v1",
            "name": "BloatedEngineeringHarness",
            "version": 1,
            "parent_id": None,
            "objective": task,
            "domain": "software_engineering",
            "constraints": constraints or ["Keep existing tests passing.", "Minimize tool calls."],
            "assumptions": ["The repository has a working test command."],
        },
        "task": {
            "id": f"task_{slug}",
            "title": task[:60],
            "description": task,
            "inputs": {"repo_path": "/workspace/repo", "test_command": "pytest"},
            "success_conditions": ["Existing tests pass.", "New feature works.", "Minimal agent footprint."],
            "artifacts_expected": ["code_patch", "test_results", "execution_trace"],
        },
        "agents": agents,
        "communication": {
            "topology": "custom_graph",
            "edges": edges,
            "shared_memory": {"enabled": True, "store": shared_store},
        },
        "execution": {
            "mode": "phased",
            "phases": phases,
            "retry_policy": {"max_retries": 1, "retry_on": ["tests_failed"]},
            "stopping_conditions": ["all_success_conditions_met"],
        },
        "runtime_policies": {
            "max_repeated_tool_errors": 2,
            "max_tool_calls_before_reflection": 40,
            "require_artifact_before_finish": True,
            "verify_before_conclude": True,
            "prevent_identical_retry": True,
            "exploration_to_implementation_threshold": 15,
        },
        "failure_recovery": {
            "on_tool_error": "Inspect the error, change strategy, do not repeat.",
            "on_missing_artifact": "Create the required artifact immediately.",
            "on_test_failure": "Read the failing assertion and make the smallest fix.",
            "on_timeout_risk": "Stop exploration and produce the best verified artifact.",
        },
        "evaluation": {
            "metrics": [
                {"name": "tests_pass",          "type": "boolean", "source": "tester_agent",   "weight": 50},
                {"name": "reviewer_acceptance", "type": "boolean", "source": "reviewer_agent", "weight": 30},
                {"name": "tool_calls",          "type": "numeric", "source": "runtime_trace",  "weight": -1},
            ],
            "binary_checks": [
                {"id": "output_produced",      "question": "Was the required output artifact produced?", "verifier": "artifact_check"},
                {"id": "success_criteria_met", "question": "Do all success conditions pass?",            "verifier": "llm_judge"},
            ],
            "scoring": {"formula": "weighted_sum", "success_threshold": 70.0},
            "validation_gate": {
                "require_no_regression": ["tests_pass"],
                "require_improvement_any": ["total_score", "tool_calls"],
                "max_runtime_seconds": 600,
            },
        },
        "weakness_mining": {
            "enabled": True,
            "failure_signature_fields": ["verifier_cause", "agent_behavior", "mechanism"],
            "clustering": {"method": "exact_signature", "min_cluster_size": 1},
        },
        "mutation_policy": {
            "allowed_mutations": [
                "remove_agent", "modify_prompt", "adjust_budget",
                "modify_tools", "modify_runtime_policy", "change_model",
            ],
            "protected_components": ["task.success_conditions", "evaluation.validation_gate"],
            "proposal_width": 3,
            "exploration_strategy": "validation_gated_mutate_winner",
        },
        "observability": {
            "trace_level": "detailed",
            "log_events": ["agent_started", "agent_finished", "tool_called", "artifact_created", "evaluation_completed"],
            "collect_artifacts": True,
        },
    }


def _common_sections() -> dict:
    return {
        "runtime_policies": {
            "max_repeated_tool_errors": 2,
            "max_tool_calls_before_reflection": 20,
            "require_artifact_before_finish": True,
            "verify_before_conclude": True,
            "prevent_identical_retry": True,
            "exploration_to_implementation_threshold": 8,
        },
        "failure_recovery": {
            "on_tool_error": "Inspect the error, change strategy, do not repeat.",
            "on_missing_artifact": "Create the required artifact immediately.",
            "on_test_failure": "Read the failing assertion and make the smallest fix.",
            "on_timeout_risk": "Stop exploration and produce the best verified artifact.",
        },
        "evaluation": {
            "metrics": [
                # "tests_pass" and "reviewer_acceptance" map to keys extracted by
                # _extract_raw_metrics in scorer.py — names must match exactly.
                {"name": "tests_pass",          "type": "boolean", "source": "tester_agent",    "weight": 50},
                {"name": "reviewer_acceptance", "type": "boolean", "source": "reviewer_agent",  "weight": 30},
                {"name": "tool_calls",          "type": "numeric", "source": "runtime_trace",   "weight": -1},
            ],
            "binary_checks": [
                {"id": "output_produced",     "question": "Was the required output artifact produced?",    "verifier": "artifact_check"},
                {"id": "success_criteria_met","question": "Do all success conditions pass?",               "verifier": "llm_judge"},
            ],
            "scoring": {"formula": "weighted_sum", "success_threshold": 70.0},
            "validation_gate": {
                "require_no_regression": ["tests_pass"],
                "require_improvement_any": ["total_score", "tool_calls"],
                "max_runtime_seconds": 600,
            },
        },
        "weakness_mining": {
            "enabled": True,
            "failure_signature_fields": ["verifier_cause", "agent_behavior", "mechanism"],
            "clustering": {"method": "exact_signature", "min_cluster_size": 1},
        },
        "mutation_policy": {
            "allowed_mutations": [
                "add_agent", "remove_agent", "modify_prompt", "modify_tools",
                "reorder_edges", "adjust_budget", "modify_runtime_policy", "modify_failure_recovery",
            ],
            "protected_components": ["task.success_conditions", "evaluation.validation_gate"],
            "proposal_width": 3,
            "exploration_strategy": "validation_gated_mutate_winner",
        },
        "observability": {
            "trace_level": "detailed",
            "log_events": ["agent_started", "agent_finished", "tool_called", "artifact_created", "evaluation_completed"],
            "collect_artifacts": True,
        },
    }
