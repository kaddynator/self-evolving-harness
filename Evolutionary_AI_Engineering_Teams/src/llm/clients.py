"""Working LLM clients with a common ``.generate()`` interface.

Both expose::

    generate(prompt, *, system_instruction=None, temperature=0.2,
             max_output_tokens=2048) -> str

so they are drop-in for GeminiJudge (and anything else that only needs text
generation). ``build_judge_client()`` returns the best backend available in the
current environment: Claude Sonnet 4.6 over Vertex when GCP credentials are
present, otherwise Gemini 3.5 Flash over the Generative Language API key.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


# ---------------------------------------------------------------------------
# Claude Sonnet 4.6 via Vertex AI Model Garden (ADC / bearer-token auth)
# ---------------------------------------------------------------------------

class AnthropicVertexClient:
    label = "claude-sonnet-4-6 (Vertex)"

    def __init__(
        self,
        project_id: Optional[str] = None,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        import google.auth  # lazy
        from anthropic import AnthropicVertex  # lazy: requires anthropic[vertex]

        self._model = model_id or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        self._project = project_id or os.environ.get("VERTEX_PROJECT", "ai-hack-sf26sfo-7208")
        self._region = region or os.environ.get("VERTEX_REGION", "global")
        self.label = f"{self._model} (Vertex)"
        # AnthropicVertex defers auth to the first request, which would make a
        # creds-less environment *look* available and then fail silently inside
        # the judge. Force the ADC check now so build_judge_client() can fall
        # back to the Gemini API-key client when there are no GCP credentials.
        google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self._client = AnthropicVertex(
            region=self._region, project_id=self._project, timeout=timeout
        )

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        **_: object,
    ) -> str:
        kwargs = {
            "model": self._model,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_instruction:
            kwargs["system"] = system_instruction
        msg = self._client.messages.create(**kwargs)
        return "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )


# ---------------------------------------------------------------------------
# Gemini via the Generative Language API (API-key auth — no GCP creds needed)
# ---------------------------------------------------------------------------

class GeminiAPIClient:
    label = "gemini-3.5-flash (API key)"

    def __init__(
        self,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        self._model = model_id or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
        self._key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._timeout = timeout
        self.label = f"{self._model} (API key)"
        if not self._key:
            raise RuntimeError("GEMINI_API_KEY not set")

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        **_: object,
    ) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._key}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        resp = requests.post(url, json=payload, timeout=self._timeout)
        if not resp.ok:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        return "".join(p.get("text", "") for p in parts)

    # ------------------------------------------------------------------
    # Function-calling (tool-use) support — mirrors GeminiClient's shape
    # ------------------------------------------------------------------

    def generate_with_tools(
        self,
        contents: List[Dict[str, Any]],
        tool_declarations: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        thinking_budget: int = 0,
        tool_mode: str = "AUTO",
    ) -> Dict[str, Any]:
        """Multi-turn generation with Gemini function calling over the GL API.

        `contents` is the full conversation so far (caller-managed), a list of
        {"role": "user"|"model", "parts": [...]} turns. Parts may carry text,
        functionCall, or functionResponse entries.

        Returns {"text": str, "function_calls": [{"name", "args"}], "raw_parts": [...]}
        where raw_parts is the model turn's parts verbatim (so the caller can
        append it back into `contents` before sending tool results).
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._key}"
        )
        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        }
        if thinking_budget is not None:
            gen_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": gen_config,
        }
        if tool_declarations:
            payload["tools"] = [{"functionDeclarations": tool_declarations}]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": tool_mode}}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        resp = requests.post(url, json=payload, timeout=self._timeout)
        if not resp.ok:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return self._parse_parts(data.get("candidates", []))

    @staticmethod
    def _parse_parts(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Collect text AND functionCall parts from response candidates."""
        texts: List[str] = []
        calls: List[Dict[str, Any]] = []
        raw: List[Dict[str, Any]] = []
        for candidate in candidates:
            for part in candidate.get("content", {}).get("parts", []):
                raw.append(part)
                text = part.get("text", "")
                if text:
                    texts.append(text)
                fc = part.get("functionCall")
                if fc:
                    calls.append({"name": fc.get("name"), "args": fc.get("args", {}) or {}})
        return {"text": "".join(texts), "function_calls": calls, "raw_parts": raw}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_judge_client(prefer: str = "claude"):
    """Return the best available text-generation client, or raise if none work.

    Order: Claude Sonnet 4.6 (Vertex) first, then Gemini 3.5 Flash (API key).
    Set prefer="gemini" to flip the order.
    """
    order = ["claude", "gemini"] if prefer == "claude" else ["gemini", "claude"]
    errors = []
    for backend in order:
        try:
            return AnthropicVertexClient() if backend == "claude" else GeminiAPIClient()
        except Exception as exc:  # missing creds / key / import
            errors.append(f"{backend}: {type(exc).__name__}: {exc}")
    raise RuntimeError("no LLM judge backend available — " + " | ".join(errors))
