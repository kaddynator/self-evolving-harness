"""Tests for the Gemini adapter — no live API calls; all HTTP is mocked."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

import pytest

from src.ir.loader import load_harness
from src.ir.schema import Agent, AgentBudget
from src.gemini.agent_runner import (
    run_gemini_agent,
    make_gemini_runner,
    _build_prompt,
    _parse_artifacts,
)
from src.gemini.client import GeminiClient

EXAMPLE_SPEC = Path(__file__).parent.parent / "examples" / "organization_spec.yaml"


@pytest.fixture
def harness():
    return load_harness(EXAMPLE_SPEC)


@pytest.fixture
def mock_client():
    client = MagicMock(spec=GeminiClient)
    client.generate.return_value = (
        "## Acceptance Criteria\n- Rate limit to 5 req/min.\n\n"
        "## Constraints\n- Keep existing tests passing.\n\n"
        "## Risks\n- In-memory only."
    )
    return client


# ---------------------------------------------------------------------------
# GeminiClient — unit test the streaming parser without network
# ---------------------------------------------------------------------------

def _make_stream_response(text: str):
    """Build a fake response matching the Vertex AI JSON array format."""
    chunk = {
        "candidates": [
            {"content": {"parts": [{"text": text}]}}
        ]
    }
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = json.dumps([chunk])   # whole body is a JSON array
    return mock_resp


@patch("src.gemini.client.google.auth.default")
@patch("src.gemini.client.requests.post")
def test_generate_returns_text(mock_post, mock_auth):
    mock_auth.return_value = (MagicMock(token="fake-token"), "proj")
    mock_post.return_value = _make_stream_response("Paris")

    client = GeminiClient(project_id="test-proj", model_id="gemini-test")
    result = client.generate("What is the capital of France?")
    assert "Paris" in result


@patch("src.gemini.client.google.auth.default")
@patch("src.gemini.client.requests.post")
def test_generate_raises_on_http_error(mock_post, mock_auth):
    mock_auth.return_value = (MagicMock(token="fake-token"), "proj")
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403
    mock_resp.text = "Permission denied"
    mock_post.return_value = mock_resp

    client = GeminiClient(project_id="test-proj", model_id="gemini-test")
    with pytest.raises(RuntimeError, match="403"):
        client.generate("Hello")


@patch("src.gemini.client.google.auth.default")
@patch("src.gemini.client.requests.post")
def test_generate_sends_correct_payload(mock_post, mock_auth):
    mock_auth.return_value = (MagicMock(token="tok"), "proj")
    mock_post.return_value = _make_stream_response("ok")

    client = GeminiClient(project_id="my-proj", model_id="gemini-test")
    client.generate("test prompt", system_instruction="be helpful")

    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"][0]["text"] == "test prompt"
    assert "systemInstruction" in payload


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

def test_build_prompt_includes_role(harness):
    agent = harness.agent_by_id("requirements_agent")
    prompt = _build_prompt(agent, {})
    assert "Requirements Agent" in prompt

def test_build_prompt_includes_responsibilities(harness):
    agent = harness.agent_by_id("coder_agent")
    prompt = _build_prompt(agent, {})
    assert "smallest working patch" in prompt or "Implement" in prompt

def test_build_prompt_includes_output_contract(harness):
    agent = harness.agent_by_id("requirements_agent")
    prompt = _build_prompt(agent, {})
    assert "Acceptance Criteria" in prompt

def test_build_prompt_includes_shared_memory(harness):
    agent = harness.agent_by_id("coder_agent")
    mem = {"acceptance_criteria": "- rate limit: 5rpm"}
    prompt = _build_prompt(agent, mem)
    assert "acceptance_criteria" in prompt
    assert "5rpm" in prompt

def test_build_prompt_skips_execution_trace(harness):
    agent = harness.agent_by_id("coder_agent")
    mem = {"execution_trace": [{"event": "agent_started"}] * 100}
    prompt = _build_prompt(agent, mem)
    assert "execution_trace" not in prompt


# ---------------------------------------------------------------------------
# _parse_artifacts
# ---------------------------------------------------------------------------

def test_parse_requirements_agent(harness):
    agent = harness.agent_by_id("requirements_agent")
    arts = _parse_artifacts("## Acceptance Criteria\n- item", agent)
    assert "acceptance_criteria" in arts

def test_parse_coder_agent_diff(harness):
    agent = harness.agent_by_id("coder_agent")
    text = "Here is the patch:\n```diff\n+rate_limiter = {}\n```"
    arts = _parse_artifacts(text, agent)
    assert "code_patch" in arts
    assert "rate_limiter" in arts["code_patch"]

def test_parse_coder_agent_no_fence(harness):
    agent = harness.agent_by_id("coder_agent")
    arts = _parse_artifacts("No fenced block here, just text.", agent)
    assert "code_patch" in arts

def test_parse_tester_agent_pass(harness):
    agent = harness.agent_by_id("tester_agent")
    arts = _parse_artifacts("## Test Results\nAll 5 tests passed.", agent)
    assert arts["test_results"]["failed"] == 0

def test_parse_tester_agent_fail(harness):
    agent = harness.agent_by_id("tester_agent")
    arts = _parse_artifacts("## Failures\n1 test failed.", agent)
    assert arts["test_results"]["failed"] == 1

def test_parse_reviewer_approved(harness):
    agent = harness.agent_by_id("reviewer_agent")
    arts = _parse_artifacts("## Approval\nApproved. LGTM.", agent)
    assert arts["review_notes"] == "approved"

def test_parse_reviewer_not_approved(harness):
    agent = harness.agent_by_id("reviewer_agent")
    arts = _parse_artifacts("## Concerns\nThis needs rework.", agent)
    assert arts["review_notes"] != "approved"


# ---------------------------------------------------------------------------
# run_gemini_agent
# ---------------------------------------------------------------------------

def test_run_gemini_agent_success(harness, mock_client):
    agent = harness.agent_by_id("requirements_agent")
    result = run_gemini_agent(agent, mock_client)
    assert result["success"] is True
    assert "acceptance_criteria" in result["artifacts"]
    assert result["output_text"] != ""

def test_run_gemini_agent_uses_shared_memory(harness, mock_client):
    agent = harness.agent_by_id("coder_agent")
    mem = {"acceptance_criteria": "rate limit = 5rpm"}
    run_gemini_agent(agent, mock_client, shared_memory=mem)
    # Verify prompt included shared memory
    call_args = mock_client.generate.call_args
    prompt = call_args[0][0]
    assert "acceptance_criteria" in prompt

def test_run_gemini_agent_error_returns_failure(harness):
    bad_client = MagicMock(spec=GeminiClient)
    bad_client.generate.side_effect = RuntimeError("network timeout")
    agent = harness.agent_by_id("coder_agent")
    result = run_gemini_agent(agent, bad_client)
    assert result["success"] is False
    assert "Gemini error" in result["output_text"]


# ---------------------------------------------------------------------------
# make_gemini_runner
# ---------------------------------------------------------------------------

def test_make_gemini_runner_returns_callable(mock_client):
    runner = make_gemini_runner(mock_client)
    assert callable(runner)

def test_make_gemini_runner_updates_shared_memory(harness, mock_client):
    shared = {}
    runner = make_gemini_runner(mock_client, shared_memory_ref=shared)
    agent = harness.agent_by_id("requirements_agent")
    runner(agent)
    assert "acceptance_criteria" in shared

def test_make_gemini_runner_compatible_with_executor(harness, mock_client):
    """Runner must return the same dict shape as run_mock_agent."""
    from src.runtime.executor import RuntimeExecutor
    runner = make_gemini_runner(mock_client)
    executor = RuntimeExecutor(agent_runner=runner)
    run = executor.run(harness)
    assert run.success is True
    assert run.total_tool_calls > 0
