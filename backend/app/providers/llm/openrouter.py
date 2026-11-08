import asyncio
import json
import logging
import re
from typing import AsyncIterator, Optional

import httpx

from app.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger("OpenRouterProvider")


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> scratchpads from thinking models (e.g. DeepSeek R1, Qwen)."""
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return cleaned if cleaned else text.strip()


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter LLM Provider:
    Supports all models routed through OpenRouter (OpenAI, Anthropic, Meta Llama, DeepSeek, Google, etc.)
    using OpenRouter's OpenAI-compatible completions and streaming API.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/llama-3.3-70b-instruct",
        base_url: str = "https://openrouter.ai/api/v1",
        site_url: str = "",
        app_name: str = "ChatX",
    ):
        self._api_key = (api_key or "").strip()
        self._model = (model or "meta-llama/llama-3.3-70b-instruct").strip()
        self._base_url = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self._site_url = site_url.strip() if site_url else ""
        self._app_name = app_name.strip() if app_name else "ChatX"

    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._site_url:
            headers["HTTP-Referer"] = self._site_url
        if self._app_name:
            headers["X-Title"] = self._app_name
        return headers

    def _messages(self, prompt: str, system_prompt: Optional[str]) -> list:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self._api_key:
            raise ValueError("OpenRouter API key is missing. Please set OPENROUTER_API_KEY.")

        last_exception = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=self._headers(),
                        json={
                            "model": self._model,
                            "messages": self._messages(prompt, system_prompt),
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )

                    if response.status_code in (429, 502, 503, 504):
                        retry_after = response.headers.get("retry-after")
                        try:
                            delay = float(retry_after) if retry_after else min(1.5 * (attempt + 1), 5.0)
                        except (ValueError, TypeError):
                            delay = 2.0
                        logger.warning(
                            "OpenRouter temporary error (status %d) on model '%s'. Retrying in %.2fs (attempt %d/3)...",
                            response.status_code,
                            self._model,
                            delay,
                            attempt + 1,
                        )
                        await asyncio.sleep(delay)
                        continue

                    response.raise_for_status()
                    data = response.json()

                    choices = data.get("choices", [])
                    raw_content = ""
                    if choices:
                        raw_content = choices[0].get("message", {}).get("content") or ""

                    choice = _strip_thinking_tags(raw_content)
                    usage = data.get("usage", {})

                    return LLMResponse(
                        text=choice,
                        usage={
                            "input_tokens": usage.get("prompt_tokens", 0),
                            "output_tokens": usage.get("completion_tokens", 0),
                        },
                        model=data.get("model", self._model),
                    )

            except httpx.HTTPStatusError as e:
                last_exception = e
                logger.error(
                    "OpenRouter HTTPStatusError: status %d body=%s",
                    e.response.status_code,
                    e.response.text[:300],
                )
                if e.response.status_code in (429, 502, 503, 504) and attempt < 2:
                    continue
                break
            except Exception as e:
                last_exception = e
                logger.warning("OpenRouter call failed on model '%s' (attempt %d): %s", self._model, attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(1.0)
                    continue
                break

        if last_exception:
            raise last_exception
        raise RuntimeError(f"OpenRouterProvider generation failed for model '{self._model}'.")

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        if not self._api_key:
            raise ValueError("OpenRouter API key is missing. Please set OPENROUTER_API_KEY.")

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST",
                        f"{self._base_url}/chat/completions",
                        headers=self._headers(),
                        json={
                            "model": self._model,
                            "messages": self._messages(prompt, system_prompt),
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": True,
                        },
                    ) as response:
                        if response.status_code in (429, 502, 503, 504):
                            retry_after = response.headers.get("retry-after")
                            try:
                                delay = float(retry_after) if retry_after else min(1.5 * (attempt + 1), 5.0)
                            except (ValueError, TypeError):
                                delay = 2.0
                            logger.warning(
                                "OpenRouter stream rate limited (status %d). Retrying in %.2fs...",
                                response.status_code,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue

                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                data = json.loads(payload)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    yield text
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
                        return

            except Exception as e:
                logger.warning("OpenRouter stream failed on '%s': %s", self._model, e)
                if attempt < 2:
                    await asyncio.sleep(1.5)
                    continue
                break

    def get_model_name(self) -> str:
        return self._model
