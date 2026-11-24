import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator, Optional

import httpx

from app.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger("GroqProvider")

# ── Ordered by quality & throughput ─────────────────────────────────────────────
# This list is refreshed automatically at startup via /v1/models if possible.
# Keep it up-to-date as a static fallback whenever Groq deprecates a model.
PREFERRED_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "allam-2-7b",
]

# Models that have been retired — skip them immediately if configured.
DEPRECATED_MODELS = {
    "llama-3.3-70b-versatile",
    "groq/compound",
    "groq/compound-mini",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "qwen/qwen3.6-27b",
}


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> scratchpads from thinking models."""
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return cleaned if cleaned else text.strip()


class GroqProvider(LLMProvider):
    _available_models_cache: list[str] | None = None
    _cache_ts: float = 0

    def __init__(
        self,
        api_key: str,
        model: str = "qwen/qwen3.8-27b",
    ):
        self._api_key = api_key
        self._base_url = "https://api.groq.com/openai/v1"
        # If the configured model is known-deprecated, swap to best available
        if model in DEPRECATED_MODELS or not model:
            logger.warning(
                "Configured Groq model '%s' is deprecated/empty — switching to '%s'",
                model, PREFERRED_MODELS[0],
            )
            self._model = PREFERRED_MODELS[0]
        else:
            self._model = model

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _messages(self, prompt: str, system_prompt: Optional[str]) -> list:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def _get_available_chat_models(self) -> list[str]:
        """
        Fetch the live list of chat-capable models from Groq's /v1/models endpoint.
        Cached for 1 hour to avoid hitting the API on every request.
        """
        now = time.time()
        if self._available_models_cache and (now - self._cache_ts) < 3600:
            return self._available_models_cache

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    all_ids = [m["id"] for m in data.get("data", [])]
                    # Filter to chat-capable models (exclude whisper, guard, orpheus)
                    skip_prefixes = ("whisper", "meta-llama/llama-prompt-guard", "canopylabs/orpheus")
                    chat_models = [mid for mid in all_ids if not any(mid.startswith(p) or mid.startswith(p) for p in skip_prefixes)]
                    if chat_models:
                        GroqProvider._available_models_cache = chat_models
                        GroqProvider._cache_ts = now
                        logger.info("Groq live models refreshed: %s", chat_models)
                        return chat_models
        except Exception as e:
            logger.debug("Could not fetch Groq models list: %s", e)

        return PREFERRED_MODELS

    def _build_fallback_chain(self) -> list[str]:
        """
        Build an ordered list of models to try: configured model first,
        then preferred models as fallbacks.
        """
        chain = [self._model]
        for m in PREFERRED_MODELS:
            if m != self._model:
                chain.append(m)
        return chain

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 768,
    ) -> LLMResponse:
        # Build fallback chain, enriched with live models if available
        live_models = await self._get_available_chat_models()
        models_to_try = [self._model]
        for m in PREFERRED_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)
        for m in live_models:
            if m not in models_to_try and m not in DEPRECATED_MODELS:
                models_to_try.append(m)

        last_exception = None

        for model in models_to_try:
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        response = await client.post(
                            f"{self._base_url}/chat/completions",
                            headers=self._headers(),
                            json={
                                "model": model,
                                "messages": self._messages(prompt, system_prompt),
                                "temperature": temperature,
                                "max_tokens": max_tokens,
                            },
                        )

                        # Rate limited — back off and retry
                        if response.status_code in (429, 503):
                            retry_after = response.headers.get("retry-after")
                            try:
                                delay = float(retry_after) if retry_after else min(1.5 * (attempt + 1), 4.0)
                            except (ValueError, TypeError):
                                delay = 2.0
                            logger.warning(
                                "Groq rate limited (status %d) on model '%s'. Sleeping %.2fs (attempt %d/3)...",
                                response.status_code, model, delay, attempt + 1,
                            )
                            await asyncio.sleep(delay)
                            continue

                        # Model not found — skip to next model immediately
                        if response.status_code == 404:
                            logger.warning("Groq model '%s' not found (404) — trying next model", model)
                            break

                        response.raise_for_status()
                        data = response.json()

                        raw_content = data["choices"][0]["message"].get("content") or ""
                        choice = _strip_thinking_tags(raw_content)
                        usage = data.get("usage", {})

                        # If we succeeded with a different model than configured, update
                        if model != self._model:
                            logger.info("Groq auto-fallback: '%s' -> '%s' succeeded", self._model, model)

                        return LLMResponse(
                            text=choice,
                            usage={
                                "input_tokens": usage.get("prompt_tokens", 0),
                                "output_tokens": usage.get("completion_tokens", 0),
                            },
                            model=model,
                        )

                except httpx.HTTPStatusError as e:
                    last_exception = e
                    if e.response.status_code == 404:
                        logger.warning("Groq model '%s' not found — skipping", model)
                        break
                    if e.response.status_code in (429, 503) and attempt < 2:
                        continue
                    break
                except Exception as e:
                    last_exception = e
                    logger.warning("Groq call failed on model '%s' (attempt %d): %s", model, attempt + 1, e)
                    await asyncio.sleep(1.0)

        if last_exception:
            raise last_exception
        raise RuntimeError("GroqProvider generation failed across all models.")

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 768,
    ) -> AsyncIterator[str]:
        models_to_try = self._build_fallback_chain()

        for model in models_to_try:
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=60) as client:
                        async with client.stream(
                            "POST",
                            f"{self._base_url}/chat/completions",
                            headers=self._headers(),
                            json={
                                "model": model,
                                "messages": self._messages(prompt, system_prompt),
                                "temperature": temperature,
                                "max_tokens": max_tokens,
                                "stream": True,
                            },
                        ) as response:
                            if response.status_code in (429, 503):
                                retry_after = response.headers.get("retry-after")
                                try:
                                    delay = float(retry_after) if retry_after else min(1.5 * (attempt + 1), 4.0)
                                except (ValueError, TypeError):
                                    delay = 2.0
                                logger.warning(
                                    "Groq stream rate limited (status %d) on model '%s'. Sleeping %.2fs...",
                                    response.status_code, model, delay,
                                )
                                await asyncio.sleep(delay)
                                continue

                            if response.status_code == 404:
                                logger.warning("Groq stream model '%s' not found (404) — trying next", model)
                                break

                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                payload = line[6:].strip()
                                if payload == "[DONE]":
                                    break
                                try:
                                    data = json.loads(payload)
                                    text = data["choices"][0]["delta"].get("content", "")
                                    if text:
                                        yield text
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                            return

                except Exception as e:
                    logger.warning("Groq stream failed on '%s': %s", model, e)
                    if attempt < 2:
                        await asyncio.sleep(1.5)
                        continue
                    break

    def get_model_name(self) -> str:
        return self._model
