"""Tests for HarnessCompiler — no live Gemini calls."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import yaml

from src.compiler.compiler import HarnessCompiler, CompilationError
from src.gemini.client import GeminiClient
from src.ir.schema import OrganizationHarness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_harness_yaml() -> str:
    """A valid minimal harness for mocking Gemini responses."""
    data = {
        "organization": {
            "id": "org_test_task_v1",
            "name": "TestHarness",
            "version": 1,
            "parent_id": None,
            "objective": "Test task",
            "domain": "software_engineering",
            "constraints": [],
            "assumptions": [],
        },
        "task": {
            "id": "task_test",
            "title": "Test task",
            "description": "A simple test task",
            "inputs": {},
            "success_conditions": ["Output is produced."],
            "artifacts_expected": ["output", "execution_trace"],
        },
        "agents": [
            {
                "id": "planner_agent",
                "name": "Planner Agent",
                "role": "Plan the work.",
                "responsibilities": ["Read the task.", "Make a plan."],
                "prompt": "You are the Planner Agent. Make a plan.",
                "tools": ["read_files"],
                "budget": {"max_tool_calls": 5, "max_runtime_seconds": 60},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "markdown", "required_sections": ["Plan"]},
            },
            {
                "id": "executor_agent",
                "name": "Executor Agent",
                "role": "Execute the plan.",
                "responsibilities": ["Follow the plan.", "Produce output."],
                "prompt": "You are the Executor Agent. Execute the plan.",
                "tools": ["read_files", "write_file"],
                "budget": {"max_tool_calls": 10, "max_runtime_seconds": 120},
                "memory_policy": {"read_shared": True, "write_shared": True},
                "output_contract": {"type": "text", "required_sections": ["Output"]},
            },
        ],
        "communication": {
            "topology": "custom_graph",
            "edges": [
                {"from": "planner_agent", "to": "executor_agent", "type": "blocking", "artifact": "plan"},
            ],
            "shared_memory": {"enabled": True, "store": ["plan", "output"]},
        },
        "execution": {
            "mode": "phased",
            "phases": [
                {"name": "plan", "agents": ["planner_agent"], "parallel": False},
                {"name": "execute", "agents": ["executor_agent"], "parallel": False},
            ],
            "retry_policy": {"max_retries": 1, "retry_on": []},
            "stopping_conditions": ["all_success_conditions_met"],
        },
        "runtime_policies": {
            "max_repeated_tool_errors": 2,
            "max_tool_calls_before_reflection": 20,
            "require_artifact_before_finish": True,
            "verify_before_conclude": True,
            "prevent_identical_retry": True,
            "exploration_to_implementation_threshold": 12,
        },
        "failure_recovery": {
            "on_tool_error": "Change strategy.",
            "on_missing_artifact": "Create it.",
            "on_test_failure": "Fix it.",
            "on_timeout_risk": "Stop and produce best output.",
        },
        "evaluation": {
            "metrics": [
                {"name": "task_success", "type": "boolean", "source": "executor_agent", "weight": 60},
                {"name": "tool_calls", "type": "numeric", "source": "runtime_trace", "weight": -1},
            ],
            "binary_checks": [
                {"id": "output_produced", "question": "Was output produced?", "verifier": "artifact_check"},
            ],
            "scoring": {"formula": "weighted_sum", "success_threshold": 70.0},
            "validation_gate": {
                "require_no_regression": ["task_success"],
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
            "allowed_mutations": ["add_agent", "remove_agent", "modify_prompt"],
            "protected_components": ["task.success_conditions"],
            "proposal_width": 3,
            "exploration_strategy": "validation_gated_mutate_winner",
        },
        "observability": {
            "trace_level": "detailed",
            "log_events": ["agent_started", "agent_finished"],
            "collect_artifacts": True,
        },
    }
    return yaml.dump(data, sort_keys=False)


# ---------------------------------------------------------------------------
# Mock mode (no Gemini client)
# ---------------------------------------------------------------------------

class TestMockMode:
    def test_compile_software_task_returns_harness(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Implement a rate limiter for the API")
        assert isinstance(harness, OrganizationHarness)

    def test_compile_research_task_returns_harness(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Research the best practices for database indexing")
        assert isinstance(harness, OrganizationHarness)

    def test_compile_data_pipeline_task_returns_harness(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Build a data pipeline to scrape and store news articles")
        assert isinstance(harness, OrganizationHarness)

    def test_compile_general_task_returns_harness(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Generate a weekly status report")
        assert isinstance(harness, OrganizationHarness)

    def test_compile_returns_correct_agent_count(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Fix the authentication bug in the login flow")
        assert 2 <= len(harness.agents) <= 5

    def test_compile_with_constraints(self):
        compiler = HarnessCompiler()
        harness = compiler.compile(
            "Refactor the database module",
            constraints=["Do not change the public API.", "Keep all tests passing."],
        )
        assert isinstance(harness, OrganizationHarness)
        assert len(harness.organization.constraints) > 0

    def test_compile_sets_domain(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Analyze market trends", domain="finance")
        assert isinstance(harness, OrganizationHarness)

    def test_compiled_harness_has_valid_edges(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Implement a new endpoint")
        agent_ids = {a.id for a in harness.agents}
        for edge in harness.communication.edges:
            assert edge.from_agent in agent_ids, f"Edge source {edge.from_agent} not in agents"
            assert edge.to in agent_ids, f"Edge target {edge.to} not in agents"

    def test_compiled_harness_has_evaluation(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Write unit tests for the payment module")
        assert len(harness.evaluation.metrics) >= 1
        assert harness.evaluation.scoring.success_threshold > 0

    def test_compiled_harness_has_mutation_policy(self):
        compiler = HarnessCompiler()
        harness = compiler.compile("Deploy the application to production")
        assert len(harness.mutation_policy.allowed_mutations) > 0


# ---------------------------------------------------------------------------
# Gemini-backed mode (mocked client)
# ---------------------------------------------------------------------------

class TestGeminiMode:
    @pytest.fixture
    def mock_client(self):
        client = MagicMock(spec=GeminiClient)
        client.generate.return_value = _minimal_harness_yaml()
        return client

    def test_compile_calls_gemini(self, mock_client):
        compiler = HarnessCompiler(client=mock_client)
        harness = compiler.compile("Add a search feature to the product catalog")
        mock_client.generate.assert_called_once()
        assert isinstance(harness, OrganizationHarness)

    def test_compile_uses_system_instruction(self, mock_client):
        compiler = HarnessCompiler(client=mock_client)
        compiler.compile("Add a search feature")
        _, kwargs = mock_client.generate.call_args
        assert "system_instruction" in kwargs
        assert kwargs["system_instruction"] != ""

    def test_compile_passes_task_in_prompt(self, mock_client):
        compiler = HarnessCompiler(client=mock_client)
        compiler.compile("Deploy the shipping microservice")
        prompt = mock_client.generate.call_args[0][0]
        assert "shipping microservice" in prompt.lower() or "Deploy" in prompt

    def test_compile_passes_prior_lessons(self, mock_client):
        lessons = [{"failure_signatures": [{"mechanism": "TOOL_OVERUSE", "agent_behavior": "loops", "verifier_cause": "timeout"}]}]
        compiler = HarnessCompiler(client=mock_client)
        compiler.compile("Write a scraper", prior_lessons=lessons)
        prompt = mock_client.generate.call_args[0][0]
        assert "TOOL_OVERUSE" in prompt

    def test_compile_retries_on_invalid_yaml(self, mock_client):
        mock_client.generate.side_effect = [
            "this is not yaml at all !!!",
            _minimal_harness_yaml(),
        ]
        compiler = HarnessCompiler(client=mock_client, max_retries=1)
        harness = compiler.compile("Fix a bug")
        assert mock_client.generate.call_count == 2
        assert isinstance(harness, OrganizationHarness)

    def test_compile_retry_includes_error_in_prompt(self, mock_client):
        mock_client.generate.side_effect = [
            "this: is: bad: yaml: [[[",
            _minimal_harness_yaml(),
        ]
        compiler = HarnessCompiler(client=mock_client, max_retries=1)
        compiler.compile("Fix a bug")
        retry_prompt = mock_client.generate.call_args[0][0]
        assert "failed validation" in retry_prompt.lower() or "error" in retry_prompt.lower()

    def test_compile_raises_after_max_retries_exceeded(self, mock_client):
        mock_client.generate.return_value = "definitely: not: valid: ir: yaml"
        compiler = HarnessCompiler(client=mock_client, max_retries=1)
        with pytest.raises(CompilationError, match="failed to produce"):
            compiler.compile("Impossible task")
        assert mock_client.generate.call_count == 2  # initial + 1 retry


# ---------------------------------------------------------------------------
# YAML extraction helpers
# ---------------------------------------------------------------------------

class TestYamlExtraction:
    def setup_method(self):
        self.compiler = HarnessCompiler()

    def test_extracts_raw_yaml(self):
        text = "organization:\n  id: test\n  name: X\n"
        result = self.compiler._extract_yaml(text)
        assert result.startswith("organization:")

    def test_extracts_fenced_yaml(self):
        text = "Here is your harness:\n```yaml\norganization:\n  id: test\n```\nDone."
        result = self.compiler._extract_yaml(text)
        assert result.startswith("organization:")

    def test_extracts_fenced_without_language(self):
        text = "Result:\n```\norganization:\n  id: test\n```"
        result = self.compiler._extract_yaml(text)
        assert result.startswith("organization:")

    def test_returns_empty_string_when_no_yaml(self):
        text = "No YAML here, just prose."
        result = self.compiler._extract_yaml(text)
        assert result == ""

    def test_prefers_fence_over_raw(self):
        text = (
            "organization:\n  id: raw\n"
            "```yaml\norganization:\n  id: fenced\n```"
        )
        result = self.compiler._extract_yaml(text)
        assert "fenced" in result
