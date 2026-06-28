from __future__ import annotations

import os
from typing import Optional

import requests

DOAI_BASE_URL = "https://inference.do-ai.run/v1"
DEFAULT_MODEL = "anthropic-claude-4.6-sonnet"


class DOAIClient:
    """Thin wrapper around the DigitalOcean AI inference REST endpoint (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: int = 120,
    ) -> None:
        self._api_key = api_key or os.environ.get("DO_AI_API_KEY", "")
        if not self._api_key:
            raise ValueError("DO_AI_API_KEY must be set or passed as api_key")
        self._model = model
        self._timeout = timeout

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
            f"{DOAI_BASE_URL}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            json={
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self._timeout,
        )

        if not response.ok:
            raise RuntimeError(
                f"DO AI error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        return data["choices"][0]["message"]["content"]
