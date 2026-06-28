# Evolutionary AI Engineering Teams

## Vision
A **self-evolving harness for agentic workflows** with a **production feedback
flywheel**.

Instead of manually defining a fixed agent workflow, the system automatically decides:
- Which agents should exist
- What each agent should do
- Which tools each agent receives
- How agents communicate
- Which workflow is most effective

…and then keeps improving that workflow from real production usage.

## Evaluation
Two modes drive the score:
- **Reference / ground-truth grading** — when an input has an expected output
  (user-provided, or captured-and-labeled by the flywheel), the agent's output
  is graded against it.
- **LLM-as-judge (label-free)** — when no expected output exists, a real LLM
  grades the run against success conditions and binary checks.

The LLM judge is **real and on by default**, independent of the agent backend.
Backends (`src/llm/clients.py`): Claude Sonnet 4.6 via Vertex AI (preferred),
falling back to Gemini 3.5 Flash via the Generative Language API. See
`docs/07_evaluation.md`.

## Feedback flywheel
Every served workflow is wrapped by a platform-level sentiment sentinel (exempt
from evolution). Negative sentiment captures an eval case → a human labels the
expected output → once a batch of labels accrues, evolution re-runs against the
enriched dataset, grades candidates reference-against the labels, gates on
no-regression over the full labeled set, and redeploys. Eval cases are stored in
the MongoDB `eval_cases` collection. See `docs/14_feedback_flywheel.md`.

## Hackathon Theme
Primary: Self-Improvement Stack
Secondary: Continual Learning

## Available Resources
- LLM judge: Claude Sonnet 4.6 (Vertex AI) / Gemini 3.5 Flash (API key)
- MCP tools
- MongoDB
- DigitalOcean
- Public GitHub repositories for demo

> Note: the legacy Vertex Gemini publisher client (`src/gemini/client.py`) is
> deprecated (404s on the current project). The working LLM path is
> `src/llm/clients.py`. See `docs/09_gemini_integration.md`.

See docs/ for the full design.
