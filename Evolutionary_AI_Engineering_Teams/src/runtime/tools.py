"""Sandboxed tool backends for real agent execution.

Each run gets its own ToolSandbox rooted in a fresh temp directory. Agents
(driven by Gemini function calling) invoke tools through `dispatch()`; every
backend returns a JSON-safe dict.

SECURITY NOTE
-------------
`run_command` / `run_tests` / `python_repl` execute model-chosen commands via
`subprocess` with `shell=True`. This is intentional (the model emits full
command lines) but is the main risk surface. It is bounded by:
  - cwd confinement to the sandbox temp dir (no access to the host repo)
  - a hard wall-clock timeout (SIGKILL on overrun)
  - an output cap (prevents context/memory blowups)
  - a minimal environment (credentials/tokens stripped)
  - the per-agent tool-call budget (caps total executions)
This is NOT a true container/jail. For production, swap the subprocess backend
for a container behind this same interface.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.compiler.prompt import TOOL_REGISTRY


class ToolError(Exception):
    """Raised for sandbox-policy violations (e.g. path traversal)."""


# ---------------------------------------------------------------------------
# Per-tool parameter schemas (OpenAPI subset Vertex accepts)
# ---------------------------------------------------------------------------

PARAM_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "read_files": {
        "type": "object",
        "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
        "required": ["paths"],
    },
    "list_files": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    },
    "edit_files": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_str": {"type": "string"},
            "new_str": {"type": "string"},
        },
        "required": ["path", "old_str", "new_str"],
    },
    "write_file": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
    "delete_file": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    "run_tests": {
        "type": "object",
        "properties": {"test_command": {"type": "string"}},
    },
    "run_command": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    "python_repl": {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
    },
    "git_diff": {"type": "object", "properties": {}},
    "git_log": {"type": "object", "properties": {"max_count": {"type": "integer"}}},
    "web_search": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    "read_url": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    "query_db": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    "send_message": {
        "type": "object",
        "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
        "required": ["body"],
    },
}

# Tools that hit external services we have not wired up — safe stubs.
_STUB_TOOLS = {"web_search", "read_url", "query_db", "send_message"}


def tool_declarations_for(agent_tools: List[str]) -> List[Dict[str, Any]]:
    """Build Gemini functionDeclarations for the subset of tools an agent has."""
    decls: List[Dict[str, Any]] = []
    for name in agent_tools:
        if name not in PARAM_SCHEMAS:
            continue
        decls.append({
            "name": name,
            "description": TOOL_REGISTRY.get(name, name),
            "parameters": PARAM_SCHEMAS[name],
        })
    return decls


class ToolSandbox:
    """A temp-dir-confined workspace exposing the tool backends."""

    def __init__(
        self,
        root: Optional[Path] = None,
        command_timeout: int = 20,
        output_cap: int = 8000,
        test_command: str = "pytest -q",
    ) -> None:
        self._root = Path(root) if root else Path(tempfile.mkdtemp(prefix="harness_ws_"))
        self._root.mkdir(parents=True, exist_ok=True)
        # Resolve symlinks up-front (macOS /var → /private/var) so relative_to()
        # comparisons against rglob results are consistent.
        self._root = self._root.resolve()
        self._command_timeout = command_timeout
        self._output_cap = output_cap
        self._test_command = test_command
        self._git_inited = False

    @property
    def root(self) -> Path:
        return self._root

    def cleanup(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)

    # -- path safety -------------------------------------------------------

    def _resolve(self, rel: str) -> Path:
        if rel is None:
            raise ToolError("missing_path")
        if os.path.isabs(rel):
            raise ToolError("absolute_path_not_allowed")
        p = (self._root / rel).resolve()
        root_resolved = self._root.resolve()
        if p != root_resolved and not str(p).startswith(str(root_resolved) + os.sep):
            raise ToolError("path_outside_sandbox")
        return p

    def _cap(self, text: str) -> str:
        if text is None:
            return ""
        return text if len(text) <= self._output_cap else text[: self._output_cap] + "\n…[truncated]"

    def _safe_env(self) -> Dict[str, str]:
        # Minimal environment — strip anything credential-like.
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self._root),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONIOENCODING": "utf-8",
        }

    # -- dispatch ----------------------------------------------------------

    def dispatch(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        args = args or {}
        try:
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                if name in _STUB_TOOLS:
                    return {"error": "not_configured", "tool": name,
                            "detail": "no backend wired in this environment"}
                return {"error": "unknown_tool", "tool": name}
            return handler(args)
        except ToolError as e:
            return {"error": str(e), "tool": name}
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "tool": name, "timeout_s": self._command_timeout}
        except Exception as e:  # never let a tool crash the run
            return {"error": f"{type(e).__name__}: {e}", "tool": name}

    # -- filesystem tools --------------------------------------------------

    def _tool_read_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, str] = {}
        for rel in args.get("paths", []):
            try:
                p = self._resolve(rel)
                out[rel] = self._cap(p.read_text(errors="replace")) if p.is_file() else "[not a file]"
            except ToolError as e:
                out[rel] = f"[error: {e}]"
            except FileNotFoundError:
                out[rel] = "[not found]"
        return {"files": out}

    def _tool_list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        base = self._resolve(args.get("path", ".") or ".")
        if not base.exists():
            return {"entries": []}
        entries: List[str] = []
        for child in sorted(base.rglob("*")):
            if ".git" in child.parts:
                continue
            entries.append(str(child.relative_to(self._root)) + ("/" if child.is_dir() else ""))
            if len(entries) >= 200:
                break
        return {"entries": entries}

    def _tool_edit_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        p = self._resolve(args["path"])
        if not p.is_file():
            return {"error": "file_not_found", "path": args["path"]}
        content = p.read_text(errors="replace")
        old, new = args.get("old_str", ""), args.get("new_str", "")
        count = content.count(old) if old else 0
        if count == 0:
            return {"error": "old_str_not_found", "path": args["path"]}
        p.write_text(content.replace(old, new))
        return {"path": args["path"], "replaced": count}

    def _tool_write_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        p = self._resolve(args["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        data = args.get("content", "")
        p.write_text(data)
        return {"path": args["path"], "bytes": len(data.encode("utf-8"))}

    def _tool_delete_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        p = self._resolve(args["path"])
        if p.is_file():
            p.unlink()
            return {"path": args["path"], "deleted": True}
        return {"error": "file_not_found", "path": args["path"]}

    # -- execution tools ---------------------------------------------------

    def _run(self, command: str) -> Dict[str, Any]:
        proc = subprocess.run(
            command, shell=True, cwd=str(self._root),
            capture_output=True, text=True,
            timeout=self._command_timeout, env=self._safe_env(),
        )
        return {
            "exit_code": proc.returncode,
            "stdout": self._cap(proc.stdout),
            "stderr": self._cap(proc.stderr),
        }

    def _tool_run_command(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._run(args["command"])

    def _tool_run_tests(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cmd = args.get("test_command") or self._test_command
        result = self._run(cmd)
        result["test_command"] = cmd
        return result

    def _tool_python_repl(self, args: Dict[str, Any]) -> Dict[str, Any]:
        script = self._root / "_repl_snippet.py"
        script.write_text(args.get("code", ""))
        # Use the current interpreter's path so it works regardless of whether
        # `python` vs `python3` is on PATH.
        interpreter = sys.executable or "python3"
        return self._run(f"{interpreter} {script.name}")

    # -- VCS tools ---------------------------------------------------------

    def _ensure_git(self) -> bool:
        if self._git_inited:
            return True
        try:
            r = subprocess.run("git --version", shell=True, capture_output=True,
                               text=True, timeout=10, env=self._safe_env())
            if r.returncode != 0:
                return False
            for cmd in ("git init -q", "git add -A",
                        "git -c user.email=a@b.c -c user.name=h commit -q -m base --allow-empty"):
                subprocess.run(cmd, shell=True, cwd=str(self._root), capture_output=True,
                               text=True, timeout=15, env=self._safe_env())
            self._git_inited = True
            return True
        except Exception:
            return False

    def _tool_git_diff(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._ensure_git():
            return {"diff": "", "note": "git not available"}
        subprocess.run("git add -A", shell=True, cwd=str(self._root),
                       capture_output=True, text=True, timeout=15, env=self._safe_env())
        r = subprocess.run("git diff --cached", shell=True, cwd=str(self._root),
                           capture_output=True, text=True, timeout=15, env=self._safe_env())
        return {"diff": self._cap(r.stdout)}

    def _tool_git_log(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._ensure_git():
            return {"log": "", "note": "git not available"}
        n = int(args.get("max_count", 10) or 10)
        r = subprocess.run(f"git log --oneline -{n}", shell=True, cwd=str(self._root),
                           capture_output=True, text=True, timeout=15, env=self._safe_env())
        return {"log": self._cap(r.stdout)}
