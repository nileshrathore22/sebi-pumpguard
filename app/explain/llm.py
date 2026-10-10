"""LLM provider abstraction. The system works with no provider (template fallback)."""

import json
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.core.config import Settings

SYSTEM_PROMPT = (
    "You explain precomputed statistical anomaly scores for Indian stocks to a non-expert. "
    "Use ONLY the numbers and dates present in the JSON you are given; do not compute new "
    "numbers, do not round differently, do not add facts. Never say or imply manipulation, "
    "fraud, wrongdoing or guarantees, and never give buy/sell advice. Write 3-5 plain sentences."
)


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class FakeLLMClient:
    """Test double: returns a fixed string or the result of a callable(payload_json)."""

    name = "fake"

    def __init__(self, response: str | Callable[[str], str]) -> None:
        self.response = response
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.response(user) if callable(self.response) else self.response


class OpenAICompatibleClient:
    """Any OpenAI-compatible /chat/completions endpoint."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 20.0) -> None:
        self.api_key, self.model, self.base_url, self.timeout = api_key, model, base_url, timeout

    def complete(self, system: str, user: str) -> str:
        resp = httpx.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"]).strip()


def build_user_prompt(payload: dict[str, Any]) -> str:
    return "Explain this anomaly score payload:\n" + json.dumps(payload, indent=2)


def get_llm_client(settings: Settings) -> LLMClient | None:
    if settings.llm_provider == "openai" and settings.llm_api_key:
        return OpenAICompatibleClient(
            settings.llm_api_key,
            settings.llm_model,
            settings.llm_base_url,
            settings.llm_timeout_seconds,
        )
    return None
