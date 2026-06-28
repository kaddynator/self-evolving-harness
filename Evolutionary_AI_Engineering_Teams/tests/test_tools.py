"""Tests for the sandboxed tool backends (no network, no Gemini)."""

import pytest

from src.runtime.tools import ToolSandbox, tool_declarations_for, PARAM_SCHEMAS


@pytest.fixture
def sandbox():
    sb = ToolSandbox(command_timeout=10)
    yield sb
    sb.cleanup()


def test_write_then_read(sandbox):
    sandbox.dispatch("write_file", {"path": "a.py", "content": "x = 1\n"})
    out = sandbox.dispatch("read_files", {"paths": ["a.py"]})
    assert out["files"]["a.py"].strip() == "x = 1"


def test_list_files(sandbox):
    sandbox.dispatch("write_file", {"path": "a.py", "content": "1"})
    sandbox.dispatch("write_file", {"path": "pkg/b.py", "content": "2"})
    entries = sandbox.dispatch("list_files", {"path": "."})["entries"]
    assert "a.py" in entries
    assert any("b.py" in e for e in entries)


def test_edit_files(sandbox):
    sandbox.dispatch("write_file", {"path": "a.py", "content": "x = 1"})
    res = sandbox.dispatch("edit_files", {"path": "a.py", "old_str": "1", "new_str": "2"})
    assert res["replaced"] == 1
    assert "x = 2" in sandbox.dispatch("read_files", {"paths": ["a.py"]})["files"]["a.py"]


def test_edit_missing_old_str(sandbox):
    sandbox.dispatch("write_file", {"path": "a.py", "content": "x = 1"})
    res = sandbox.dispatch("edit_files", {"path": "a.py", "old_str": "zzz", "new_str": "2"})
    assert res["error"] == "old_str_not_found"


def test_path_traversal_blocked(sandbox):
    out = sandbox.dispatch("read_files", {"paths": ["../../../etc/passwd"]})
    assert "error" in out["files"]["../../../etc/passwd"]


def test_absolute_path_blocked(sandbox):
    out = sandbox.dispatch("read_files", {"paths": ["/etc/passwd"]})
    assert "error" in out["files"]["/etc/passwd"]


def test_run_command(sandbox):
    res = sandbox.dispatch("run_command", {"command": "echo hello"})
    assert res["exit_code"] == 0
    assert "hello" in res["stdout"]


def test_python_repl(sandbox):
    res = sandbox.dispatch("python_repl", {"code": "print(6 * 7)"})
    assert res["exit_code"] == 0
    assert "42" in res["stdout"]


def test_command_timeout(sandbox):
    sb = ToolSandbox(command_timeout=1)
    res = sb.dispatch("run_command", {"command": "sleep 5"})
    sb.cleanup()
    assert res.get("error") == "timeout"


def test_stub_tools_not_configured(sandbox):
    for name in ("web_search", "read_url", "query_db", "send_message"):
        res = sandbox.dispatch(name, {"query": "x", "url": "x", "body": "x"})
        assert res["error"] == "not_configured"


def test_unknown_tool(sandbox):
    assert sandbox.dispatch("frobnicate", {})["error"] == "unknown_tool"


def test_output_capped():
    sb = ToolSandbox(output_cap=50)
    res = sb.dispatch("run_command", {"command": "printf 'x%.0s' {1..500}"})
    sb.cleanup()
    assert len(res["stdout"]) <= 80  # cap + truncation marker


def test_tool_declarations_filter():
    decls = tool_declarations_for(["read_files", "run_tests", "not_a_tool"])
    names = [d["name"] for d in decls]
    assert names == ["read_files", "run_tests"]
    for d in decls:
        assert "parameters" in d and "description" in d


def test_every_registry_param_schema_valid():
    for name, schema in PARAM_SCHEMAS.items():
        assert schema["type"] == "object"
