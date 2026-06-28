"""Tests for real-Gemini execution path: function calling, tool runner, judge.

All Gemini I/O is mocked — no network, no credentials.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.gemini.client import GeminiClient
from src.gemini.agent_runner import run_gemini_agent_with_tools, make_gemini_tool_runner
from src.ir.schema import Agent, AgentBudget
from src.runtime.tools import ToolSandbox
from src.runtime.executor import RuntimeExecutor
from src.ir.loader import load_harness
from src.evaluation.scorer import score_run
from pathlib import Path

EXAMPLE_SPEC = Path(__file__).parent.parent / "examples" / "organization_spec.yaml"


# ---------------------------------------------------------------------------
# GeminiClient.generate_with_tools — parse text + functionCall parts
# ---------------------------------------------------------------------------

def _resp(parts):
    r = MagicMock()
    r.ok = True
    r.text = json.dumps([{"candidates": [{"content": {"parts": parts}}]}])
    return r


@patch("src.gemini.client.google.auth.default")
@patch("src.gemini.client.requests.post")
def test_generate_with_tools_parses_function_call(mock_post, mock_auth):
    mock_auth.return_value = (MagicMock(token="t"), "proj")
    mock_post.return_value = _resp([
        {"functionCall": {"name": "read_files", "args": {"paths": ["a.py"]}}}
    ])
    client = GeminiClient(project_id="p", model_id="m")
    out = client.generate_with_tools([{"role": "user", "parts": [{"text": "go"}]}],
                                     tool_declarations=[{"name": "read_files"}])
    assert out["function_calls"] == [{"name": "read_files", "args": {"paths": ["a.py"]}}]
    assert out["raw_parts"]


@patch("src.gemini.client.google.auth.default")
@patch("src.gemini.client.requests.post")
def test_generate_with_tools_parses_text(mock_post, mock_auth):
    mock_auth.return_value = (MagicMock(token="t"), "proj")
    mock_post.return_value = _resp([{"text": "all done"}])
    client = GeminiClient(project_id="p", model_id="m")
    out = client.generate_with_tools([{"role": "user", "parts": [{"text": "go"}]}])
    assert out["text"] == "all done"
    assert out["function_calls"] == []


# ---------------------------------------------------------------------------
# Tool-use runner loop — model calls a tool, then returns final text
# ---------------------------------------------------------------------------

def _coder_agent():
    return Agent(
        id="coder_agent", name="Coder", role="Implement the change.",
        prompt="Write code.", tools=["read_files", "write_file"],
        budget=AgentBudget(max_tool_calls=5),
    )


def test_tool_runner_executes_loop():
    client = MagicMock(spec=GeminiClient)
    # First call: request a write_file. Second call: final text.
    client.generate_with_tools.side_effect = [
        {"text": "", "function_calls": [{"name": "write_file", "args": {"path": "a.py", "content": "x=1"}}],
         "raw_parts": [{"functionCall": {"name": "write_file", "args": {"path": "a.py", "content": "x=1"}}}]},
        {"text": "Done implementing.", "function_calls": [], "raw_parts": []},
    ]
    sandbox = ToolSandbox()
    seen = []
    result = run_gemini_agent_with_tools(
        _coder_agent(), client, sandbox,
        on_tool_call=lambda name, ok: seen.append((name, ok)),
    )
    sandbox.cleanup()
    assert result["success"] is True
    assert result["tool_call_count"] == 1
    assert seen == [("write_file", True)]
    assert "a.py" in str(result["tool_calls"])


def test_tool_runner_respects_budget():
    client = MagicMock(spec=GeminiClient)
    # Always ask for a tool; budget should cap executions.
    client.generate_with_tools.return_value = {
        "text": "", "function_calls": [{"name": "read_files", "args": {"paths": ["a.py"]}}],
        "raw_parts": [{"functionCall": {"name": "read_files", "args": {"paths": ["a.py"]}}}],
    }
    agent = Agent(id="x_agent", name="X", role="r", prompt="p",
                  tools=["read_files"], budget=AgentBudget(max_tool_calls=2))
    sandbox = ToolSandbox()
    result = run_gemini_agent_with_tools(agent, client, sandbox)
    sandbox.cleanup()
    assert result["tool_call_count"] <= 2


def test_tool_runner_no_tools_falls_back_to_text():
    client = MagicMock(spec=GeminiClient)
    client.generate.return_value = "## Output\nplain text"
    agent = Agent(id="x_agent", name="X", role="r", prompt="p", tools=[],
                  budget=AgentBudget(max_tool_calls=3))
    sandbox = ToolSandbox()
    result = run_gemini_agent_with_tools(agent, client, sandbox)
    sandbox.cleanup()
    assert result["success"] is True


def test_make_gemini_tool_runner_has_new_run_and_isolates():
    client = MagicMock(spec=GeminiClient)
    client.generate_with_tools.return_value = {"text": "done", "function_calls": [], "raw_parts": []}
    runner = make_gemini_tool_runner(client)
    assert hasattr(runner, "new_run")
    runner.new_run()
    out = runner(_coder_agent(), on_tool_call=None)
    assert out["success"] is True


def test_tool_runner_injectable_into_executor():
    client = MagicMock(spec=GeminiClient)
    client.generate_with_tools.return_value = {"text": "ok", "function_calls": [], "raw_parts": []}
    runner = make_gemini_tool_runner(client)
    harness = load_harness(EXAMPLE_SPEC)
    ex = RuntimeExecutor(agent_runner=runner)
    run = ex.run(harness)
    assert run.success is True


# ---------------------------------------------------------------------------
# Scorer with a judge — verdicts override boolean signals
# ---------------------------------------------------------------------------

class _FakeJudge:
    def __init__(self, verdicts):
        self._v = verdicts

    def grade(self, run, harness):
        return {"verdicts": self._v, "scores": {}, "rationale": "x"}


def test_score_run_judge_overrides(monkeypatch):
    harness = load_harness(EXAMPLE_SPEC)
    runner = MagicMock()
    # Build a real run via mock executor so artifacts exist.
    from src.runtime.mock_agents import run_mock_agent
    run = RuntimeExecutor(agent_runner=run_mock_agent).run(harness)

    # Judge says reviewer_acceptance is False — should pull score down vs no judge.
    base = score_run(run, harness.evaluation)
    judged = score_run(run, harness.evaluation,
                       judge=_FakeJudge({"reviewer_acceptance": False}),
                       harness=harness)
    assert judged.raw_metrics["reviewer_acceptance"] is False
    assert judged.total_score <= base.total_score


def test_score_run_no_judge_unchanged():
    harness = load_harness(EXAMPLE_SPEC)
    from src.runtime.mock_agents import run_mock_agent
    run = RuntimeExecutor(agent_runner=run_mock_agent).run(harness)
    a = score_run(run, harness.evaluation)
    b = score_run(run, harness.evaluation, judge=None, harness=None)
    assert a.total_score == b.total_score
