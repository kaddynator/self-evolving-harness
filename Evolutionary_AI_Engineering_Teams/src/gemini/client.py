from __future__ import annotations

import json
from typing import Any, Dict, Iterator, Optional

import requests
import google.auth
import google.auth.transport.requests

MODEL_ID = "gemini-2.5-flash"
PROJECT_ID = "ai-hack-sf26sfo-7208"
ENDPOINT = (
    f"https://aiplatform.googleapis.com/v1/projects/{PROJECT_ID}"
    f"/locations/global/publishers/google/models/{MODEL_ID}:streamGenerateContent"
)


class GeminiClient:
    """Thin wrapper around the Vertex AI streamGenerateContent REST endpoint.

    Uses Application Default Credentials (ADC) — run
    `gcloud auth application-default login` once to configure.
    """

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        model_id: str = MODEL_ID,
        timeout: int = 120,
    ) -> None:
        self._project_id = project_id
        self._model_id = model_id
        self._timeout = timeout
        self._endpoint = (
            f"https://aiplatform.googleapis.com/v1/projects/{project_id}"
            f"/locations/global/publishers/google/models/{model_id}:streamGenerateContent"
        )
        self._creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    def _get_token(self) -> str:
        auth_req = google.auth.transport.requests.Request()
        self._creds.refresh(auth_req)
        return self._creds.token

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        thinking_budget: int = 0,
    ) -> str:
        """Send a single prompt and return the full concatenated response text.

        thinking_budget: token budget for the model's internal "thinking" pass.
        gemini-2.5-flash is a thinking model that, by default, spends output
        tokens on reasoning — which truncates structured output like our harness
        YAML. We default to 0 (thinking disabled) so the full token budget is
        available for the actual response.
        """
        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        }
        if thinking_budget is not None:
            gen_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}

        payload: Dict[str, Any] = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "generationConfig": gen_config,
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            self._endpoint,
            headers=headers,
            json=payload,
            timeout=self._timeout,
        )

        if not response.ok:
            raise RuntimeError(
                f"Gemini API error {response.status_code}: {response.text[:500]}"
            )

        return self._collect_stream(response)

    # ------------------------------------------------------------------
    # Function-calling (tool-use) support
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
        """Multi-turn generation that supports Gemini function calling.

        `contents` is the full conversation so far (caller-managed), a list of
        {"role": "user"|"model", "parts": [...]} turns. Parts may carry text,
        functionCall, or functionResponse entries.

        Returns {"text": str, "function_calls": [{"name", "args"}], "raw_parts": [...]}
        where raw_parts is the model turn's parts verbatim (so the caller can
        append it back into `contents` before sending tool results).
        """
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

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            self._endpoint, headers=headers, json=payload, timeout=self._timeout
        )
        if not response.ok:
            raise RuntimeError(
                f"Gemini API error {response.status_code}: {response.text[:500]}"
            )

        chunks = self._load_chunks(response.text.strip())
        return self._parse_parts(chunks)

    @staticmethod
    def _load_chunks(body: str) -> list:
        """Parse a Vertex streamGenerateContent body into a list of chunk dicts.

        Handles both the whole-body JSON array and line-by-line streaming forms.
        """
        try:
            data = json.loads(body)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

        chunks = []
        for raw_line in body.splitlines():
            line = raw_line.strip().lstrip(",").lstrip("[").rstrip("]").strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return chunks

    def _parse_parts(self, chunks: list) -> Dict[str, Any]:
        """Collect text AND functionCall parts from response chunks."""
        texts: List[str] = []
        calls: List[Dict[str, Any]] = []
        raw: List[Dict[str, Any]] = []
        for chunk in chunks:
            for candidate in chunk.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    raw.append(part)
                    text = part.get("text", "")
                    if text:
                        texts.append(text)
                    fc = part.get("functionCall")
                    if fc:
                        calls.append({"name": fc.get("name"), "args": fc.get("args", {}) or {}})
        return {"text": "".join(texts), "function_calls": calls, "raw_parts": raw}

    def _collect_stream(self, response: requests.Response) -> str:
        """Collect the Vertex AI response and concatenate text parts.

        The endpoint returns a JSON array even in streaming mode:
        [ { "candidates": [...] }, { "candidates": [...] }, ... ]
        We read the full body and parse it as a JSON array.
        """
        body = response.text.strip()

        # Try parsing the whole body as a JSON array first (normal case)
        try:
            chunks_list = json.loads(body)
            if isinstance(chunks_list, list):
                return self._extract_text(chunks_list)
            # Single object (shouldn't happen but handle it)
            if isinstance(chunks_list, dict):
                return self._extract_text([chunks_list])
        except json.JSONDecodeError:
            pass

        # Fallback: line-by-line for true streaming responses
        texts = []
        for raw_line in body.splitlines():
            line = raw_line.strip().lstrip(",").lstrip("[").rstrip("]").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                texts.extend(self._extract_text_from_chunk(chunk))
            except json.JSONDecodeError:
                pass
        return "".join(texts)

    def _extract_text(self, chunks: list) -> str:
        parts = []
        for chunk in chunks:
            parts.extend(self._extract_text_from_chunk(chunk))
        return "".join(parts)

    def _extract_text_from_chunk(self, chunk: dict) -> list:
        texts = []
        for candidate in chunk.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text = part.get("text", "")
                if text:
                    texts.append(text)
        return texts
