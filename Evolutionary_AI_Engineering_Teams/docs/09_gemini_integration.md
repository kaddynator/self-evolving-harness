# LLM Integration

## Working LLM backends (judge / generation)

`src/llm/clients.py` exposes the live text-generation backends behind a common
`.generate()` interface. `build_judge_client()` returns the best available one:

- **AnthropicVertexClient** — Claude Sonnet 4.6 via Vertex AI Model Garden
  (ADC / bearer-token auth). Preferred.
- **GeminiAPIClient** — Gemini 3.5 Flash via the Generative Language API
  (API-key auth, no GCP creds needed). Fallback.

These power the **real LLM-as-judge** (see `docs/07_evaluation.md`), which is on
by default and independent of the agent execution backend.

## Deprecated: legacy Vertex Gemini publisher client

`src/gemini/client.py` (`GeminiClient`) targets the Vertex AI
`publishers/google/models/{model}:streamGenerateContent` endpoint. **This path
is deprecated** — the publisher endpoint **404s on the current project**, so it
is not a reliable execution path. Do not route the judge through it; use the
backends in `src/llm/clients.py`.

It is still referenced by the optional Gemini *agent* runner
(`src/gemini/agent_runner.py`, selected by the `gemini` backend in `cli.py`), but
that path inherits the same 404 limitation and should be treated as legacy.

## Roles for LLMs in the system

- Grade runs (LLM-as-judge: label-free and reference modes)
- Generate / grow prompts during evolution
- Propose mutations
- Summarize lessons and weaknesses

## Gemini Computer Use

Optional, future demos only.
