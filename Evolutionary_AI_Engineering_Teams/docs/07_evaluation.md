# Evaluation

Evaluation produces the score that drives selection and the validation gate.
There are **two modes**, plus a real **LLM-as-judge** that is on by default.

## Two evaluation modes

1. **Reference / ground-truth grading** — when an expected output exists for an
   input. The eval case carries `input` + `expected_output`; the agent's
   `actual_output` is graded *against the expected output*. Expected outputs
   come from the user up front, or from the feedback flywheel
   (capture → human label). See `docs/14_feedback_flywheel.md`.
   Implemented by `GeminiJudge.grade_against_expected()` in
   `src/evaluation/judge.py`, returning
   `{"match": bool, "score": 0.0-1.0, "missing": [...], "rationale": str}`.

2. **LLM-as-judge (label-free)** — when no expected output exists. The run is
   judged against the harness's success conditions and binary-check questions,
   returning boolean verdicts (`tests_pass`, `feature_works`,
   `reviewer_acceptance`, plus each binary check) that feed the existing
   weighted-sum scorer. Implemented by `GeminiJudge.grade()`.

## The LLM judge is real and ON by default

When agents execute for real there is no deterministic mock signal to read, so a
real LLM judge grades the run. It is wired in `cli._build_default_judge()` and is
**independent of the agent backend** — the judge backend is chosen separately
from whatever runs the agents.

Judge backends (`src/llm/clients.py`, selected by `build_judge_client()`):

- **AnthropicVertexClient** — Claude Sonnet 4.6 via Vertex AI (ADC auth).
  Preferred.
- **GeminiAPIClient** — Gemini 3.5 Flash via the Generative Language API key.
  Fallback when GCP credentials are absent.

If neither backend is available, the system prints a notice and falls back to the
deterministic/heuristic scorer. (Note: `GeminiJudge` accepts any client exposing
`.generate()`; its type hint still names the legacy `GeminiClient`, but the
client it actually receives comes from `build_judge_client()`.)

## Primary metrics

- Task success
- Tests passing
- Runtime
- Tool calls
- Diff size (if coding)

These remain the cost/efficiency metrics. The LLM judge supplies the
*correctness* verdicts (and, in reference mode, a 0.0–1.0 match score) that the
deterministic mock used to fake.

## Notes

- BINEVAL-style binary checks are already in use: the judge returns
  interpretable per-check booleans, not a single opaque number.
