from pathlib import Path
from typing import Dict, Any

import pytest

from src.ir.loader import load_harness
from src.ir.schema import Agent, OrganizationHarness
from src.runtime.executor import RuntimeExecutor, RunResult
from src.runtime.events import EventType
from src.runtime.mock_agents import run_mock_agent, simulate_tool_call

EXAMPLE_SPEC = Path(__file__).parent.parent / "examples" / "organization_spec.yaml"


@pytest.fixture
def harness() -> OrganizationHarness:
    return load_harness(EXAMPLE_SPEC)


@pytest.fixture
def result(harness) -> RunResult:
    return RuntimeExecutor().run(harness)


# ---------------------------------------------------------------------------
# RunResult basics
# ---------------------------------------------------------------------------

def test_run_returns_result(result):
    assert isinstance(result, RunResult)

def test_run_id_set(result):
    assert result.run_id and len(result.run_id) > 0

def test_run_succeeds(result):
    assert result.success is True

def test_stop_reason_completed(result):
    assert result.stop_reason == "completed"

def test_elapsed_positive(result):
    assert result.elapsed_seconds >= 0

def test_total_tool_calls_positive(result):
    assert result.total_tool_calls > 0


# ---------------------------------------------------------------------------
# Trace events
# ---------------------------------------------------------------------------

def test_run_started_event(result):
    types = [e.event_type for e in result.events]
    assert EventType.run_started in types

def test_run_finished_event(result):
    types = [e.event_type for e in result.events]
    assert EventType.run_finished in types

def test_all_agents_started(result, harness):
    started_ids = {
        e.agent_id for e in result.events if e.event_type == EventType.agent_started
    }
    agent_ids = {a.id for a in harness.agents}
    assert started_ids == agent_ids

def test_all_agents_finished(result, harness):
    finished_ids = {
        e.agent_id for e in result.events if e.event_type == EventType.agent_finished
    }
    agent_ids = {a.id for a in harness.agents}
    assert agent_ids.issubset(finished_ids)

def test_phase_events_emitted(result):
    types = [e.event_type for e in result.events]
    assert EventType.phase_started in types
    assert EventType.phase_finished in types

def test_phase_names_correct(result, harness):
    started_phases = {
        e.phase for e in result.events if e.event_type == EventType.phase_started
    }
    expected = {p.name for p in harness.execution.phases}
    assert started_phases == expected

def test_tool_called_events(result):
    types = [e.event_type for e in result.events]
    assert EventType.tool_called in types

def test_artifact_created_events(result):
    types = [e.event_type for e in result.events]
    assert EventType.artifact_created in types

def test_run_started_is_first_event(result):
    assert result.events[0].event_type == EventType.run_started

def test_run_finished_is_last_event(result):
    assert result.events[-1].event_type == EventType.run_finished


# ---------------------------------------------------------------------------
# Artifacts and shared memory
# ---------------------------------------------------------------------------

def test_artifacts_populated(result):
    assert len(result.artifacts) > 0

def test_code_patch_in_artifacts(result):
    assert "code_patch" in result.artifacts

def test_test_results_in_artifacts(result):
    assert "test_results" in result.artifacts

def test_shared_memory_matches_artifacts(result):
    for key in result.artifacts:
        assert key in result.shared_memory

def test_agent_results_keyed_by_id(result, harness):
    for agent in harness.agents:
        assert agent.id in result.agent_results


# ---------------------------------------------------------------------------
# Phase ordering — understand before implement before verify
# ---------------------------------------------------------------------------

def test_phase_order_respected(result, harness):
    phase_names = [p.name for p in harness.execution.phases]
    phase_start_events = [
        e for e in result.events if e.event_type == EventType.phase_started
    ]
    observed_order = [e.phase for e in phase_start_events]
    assert observed_order == phase_names


# ---------------------------------------------------------------------------
# Parallel phase — tester and reviewer both run in verify phase
# ---------------------------------------------------------------------------

def test_parallel_agents_both_run(result):
    finished = {
        e.agent_id for e in result.events
        if e.event_type == EventType.agent_finished and e.phase == "verify"
    }
    assert "tester_agent" in finished
    assert "reviewer_agent" in finished


# ---------------------------------------------------------------------------
# Custom agent runner injection
# ---------------------------------------------------------------------------

def test_injectable_agent_runner(harness):
    calls = []

    def tracking_runner(agent: Agent) -> Dict[str, Any]:
        calls.append(agent.id)
        return run_mock_agent(agent)

    RuntimeExecutor(agent_runner=tracking_runner).run(harness)
    assert set(calls) == {a.id for a in harness.agents}


# ---------------------------------------------------------------------------
# Mock agent internals
# ---------------------------------------------------------------------------

def test_simulate_tool_budget_exceeded():
    agent = Agent(
        id="x", name="X", role="coder", prompt="go",
        tools=["read_files"],
        budget={"max_tool_calls": 2, "max_runtime_seconds": 60},
    )
    result = simulate_tool_call("read_files", agent, tool_calls_so_far=5)
    assert "error" in result

def test_simulate_tool_known_output():
    agent = Agent(
        id="x", name="X", role="coder", prompt="go",
        tools=["run_tests"],
        budget={"max_tool_calls": 20, "max_runtime_seconds": 60},
    )
    result = simulate_tool_call("run_tests", agent, tool_calls_so_far=0)
    assert "output" in result
    assert result["output"]["passed"] == 5
