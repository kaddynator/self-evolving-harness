"""LLM-as-judge scoring for real Gemini runs.

When agents execute for real, there is no deterministic mock signal to read.
The GeminiJudge grades a run's output/artifacts against the harness's success
conditions and binary-check questions, returning boolean verdicts that feed
into the existing weighted-sum scorer (via raw_metrics / binary checks).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from src.gemini.client import GeminiClient
from src.ir.schema import OrganizationHarness
from src.runtime.executor import RunResult


_JUDGE_SYSTEM = (
    "You are a strict, fair evaluator of AI agent workflow runs.\n"
    "Judge ONLY on the evidence provided. Respond with a single JSON object."
)


def _cap(value: Any, n: int = 1200) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s if len(s) <= n else s[:n] + "…"


def _extract_json(text: str) -> Dict[str, Any]:
    """Tolerant JSON extraction from a model response."""
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # Fall back to the first {...} block.
    if not fenced:
        brace = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace:
            candidate = brace.group(0)
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


class GeminiJudge:
    """Grades a run with Gemini, returning verdicts the scorer can consume."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def grade(self, run: RunResult, harness: OrganizationHarness) -> Dict[str, Any]:
        checks = [
            {"id": c.id, "question": c.question}
            for c in harness.evaluation.binary_checks
        ]
        # Surface the artifacts the deterministic scorer cares about, plus output.
        artifact_summary = {
            k: _cap(v) for k, v in run.artifacts.items() if k != "execution_trace"
        }

        prompt = self._build_prompt(harness, checks, artifact_summary)

        try:
            text = self._client.generate(
                prompt, system_instruction=_JUDGE_SYSTEM, max_output_tokens=1024
            )
        except Exception:
            return {"verdicts": {}, "scores": {}, "rationale": "judge_unavailable"}

        data = _extract_json(text)
        verdicts_raw = data.get("verdicts", {}) if isinstance(data, dict) else {}
        verdicts: Dict[str, bool] = {}
        for k, v in verdicts_raw.items():
            if isinstance(v, bool):
                verdicts[k] = v
            elif isinstance(v, str):
                verdicts[k] = v.strip().lower() in ("true", "yes", "pass", "passed", "1")
        return {
            "verdicts": verdicts,
            "scores": data.get("scores", {}) if isinstance(data, dict) else {},
            "rationale": str(data.get("rationale", ""))[:500],
        }

    def _build_prompt(self, harness, checks, artifact_summary) -> str:
        keys = [
            "tests_pass — do the produced tests/code indicate a passing, working solution?",
            "feature_works — does the output actually satisfy the task's success conditions?",
            "reviewer_acceptance — would a senior reviewer approve this work as-is?",
        ]
        lines = [
            "# Task",
            harness.task.description or harness.task.title,
            "",
            "## Success conditions",
            *[f"- {c}" for c in harness.task.success_conditions],
            "",
            "## Binary checks to judge",
            *[f"- {c['id']}: {c['question']}" for c in checks],
            "",
            "## Standard verdict keys (also judge these)",
            *[f"- {k}" for k in keys],
            "",
            "## Produced artifacts",
        ]
        for k, v in artifact_summary.items():
            lines.append(f"### {k}")
            lines.append(v)
        lines += [
            "",
            "## Respond with ONLY this JSON:",
            '{"verdicts": {"<key>": true|false, ...}, '
            '"scores": {"<metric>": 0.0-1.0}, "rationale": "<one sentence>"}',
            "Include verdicts for tests_pass, feature_works, reviewer_acceptance and every binary check id above.",
        ]
        return "\n".join(lines)
