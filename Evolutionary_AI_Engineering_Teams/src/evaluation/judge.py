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


_REFERENCE_JUDGE_SYSTEM = (
    "You are a strict, fair reference grader for AI agent outputs.\n"
    "You compare an agent's ACTUAL output against a human-approved EXPECTED output.\n"
    "Judge ONLY on semantic correctness and coverage of the actual relative to the "
    "expected. Respond with a single JSON object."
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

    def grade_against_expected(
        self,
        input_text: str,
        actual_output: str,
        expected_output: str,
    ) -> Dict[str, Any]:
        """Reference-grade an actual output against a human-approved expected output.

        Compares the agent's ACTUAL output against the EXPECTED output for the
        given user input, returning a dict:
            {"match": bool, "score": 0.0-1.0, "missing": [...], "rationale": str}
        where `score` is the semantic correctness/coverage of actual vs expected
        (1.0 = fully matches expected intent & key facts; partial credit allowed)
        and `missing` lists key expected points the actual output omitted.

        Falls back to a non-matching verdict on unparseable output, and to a
        ``judge_unavailable`` verdict if the client raises.
        """
        prompt = self._build_reference_prompt(input_text, actual_output, expected_output)

        try:
            text = self._client.generate(
                prompt,
                system_instruction=_REFERENCE_JUDGE_SYSTEM,
                max_output_tokens=1024,
            )
        except Exception:
            return {
                "match": False,
                "score": 0.0,
                "missing": [],
                "rationale": "judge_unavailable",
            }

        data = _extract_json(text)
        if not data:
            return {
                "match": False,
                "score": 0.0,
                "missing": [],
                "rationale": "unparseable",
            }

        match = data.get("match", False)
        if isinstance(match, str):
            match = match.strip().lower() in ("true", "yes", "pass", "passed", "1")
        else:
            match = bool(match)

        try:
            score = float(data.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))

        missing_raw = data.get("missing", [])
        missing = (
            [str(m) for m in missing_raw] if isinstance(missing_raw, list) else []
        )

        return {
            "match": match,
            "score": score,
            "missing": missing,
            "rationale": str(data.get("rationale", ""))[:500],
        }

    def _build_reference_prompt(
        self, input_text: str, actual_output: str, expected_output: str
    ) -> str:
        lines = [
            "# Reference grading",
            "Grade the agent's ACTUAL output against the human-approved EXPECTED "
            "output for the user input below.",
            "",
            "## User input",
            _cap(input_text),
            "",
            "## EXPECTED output (human-approved reference)",
            _cap(expected_output),
            "",
            "## ACTUAL output (agent produced)",
            _cap(actual_output),
            "",
            "## Grading rules",
            "- score (0.0-1.0): semantic correctness and coverage of ACTUAL vs "
            "EXPECTED. 1.0 = fully matches expected intent & key facts; partial "
            "credit allowed for partial coverage.",
            "- match: true only if the actual output substantially matches the "
            "expected intent and key facts.",
            "- missing: list the key expected points the actual output omitted.",
            "",
            "## Respond with ONLY this JSON:",
            '{"match": true|false, "score": 0.0-1.0, '
            '"missing": ["..."], "rationale": "<one sentence>"}',
        ]
        return "\n".join(lines)

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
