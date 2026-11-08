import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.providers.registry import create_llm_provider
from app.providers.llm.openrouter import OpenRouterProvider, _strip_thinking_tags


def test_thinking_tag_removal():
    raw = "<think>Let me reason about this...</think>Hello, how can I help you today?"
    cleaned = _strip_thinking_tags(raw)
    assert cleaned == "Hello, how can I help you today?"


def test_openrouter_instantiation():
    provider = OpenRouterProvider(
        api_key="sk-or-v1-fake-key",
        model="meta-llama/llama-3.3-70b-instruct",
        site_url="https://svprofessionals.click",
        app_name="SVBot",
    )
    assert provider.get_model_name() == "meta-llama/llama-3.3-70b-instruct"
    headers = provider._headers()
    assert headers["Authorization"] == "Bearer sk-or-v1-fake-key"
    assert headers["HTTP-Referer"] == "https://svprofessionals.click"
    assert headers["X-Title"] == "SVBot"


def test_registry_factory():
    provider = create_llm_provider(
        provider="openrouter",
        api_key="sk-or-v1-dummy",
        model="openai/gpt-4o-mini",
    )
    assert isinstance(provider, OpenRouterProvider)
    assert provider.get_model_name() == "openai/gpt-4o-mini"

    provider2 = create_llm_provider(
        provider="open_router",
        api_key="sk-or-v1-dummy",
        model="deepseek/deepseek-chat",
    )
    assert isinstance(provider2, OpenRouterProvider)
    assert provider2.get_model_name() == "deepseek/deepseek-chat"


async def test_openrouter_generate_mock():
    provider = OpenRouterProvider(
        api_key="sk-or-v1-dummy",
        model="meta-llama/llama-3.3-70b-instruct",
    )

    mock_resp_json = {
        "id": "gen-1234",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "<think>thinking here</think>Welcome to SV Professionals!",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 10,
            "total_tokens": 25,
        },
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_resp_json
    mock_response.raise_for_status.return_value = None

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await provider.generate(prompt="Hello", system_prompt="You are helpful.")
        assert result.text == "Welcome to SV Professionals!"
        assert result.model == "meta-llama/llama-3.3-70b-instruct"
        assert result.usage["input_tokens"] == 15
        assert result.usage["output_tokens"] == 10


if __name__ == "__main__":
    test_thinking_tag_removal()
    test_openrouter_instantiation()
    test_registry_factory()
    asyncio.run(test_openrouter_generate_mock())
    print("All OpenRouter tests passed successfully!")
