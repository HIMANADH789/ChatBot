from typing import Optional

from app.config import settings
from app.providers.base import EmbeddingProvider, LLMProvider, VectorStoreProvider

_llm_instance: LLMProvider | None = None
_embedding_instance: EmbeddingProvider | None = None
_vectordb_instance: VectorStoreProvider | None = None


def create_llm_provider(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    site_url: Optional[str] = None,
    app_name: Optional[str] = None,
) -> LLMProvider:
    """
    Factory to instantiate an LLM provider based on explicit parameters or app settings.
    Supported providers: 'gemini', 'groq', 'openrouter' (or 'open_router'), 'ollama'.
    """
    selected_provider = (provider or settings.LLM_PROVIDER or "").lower().strip().replace("-", "_")

    match selected_provider:
        case "gemini":
            from app.providers.llm.gemini import GeminiProvider
            return GeminiProvider(
                api_key=api_key if api_key is not None else settings.GEMINI_API_KEY,
                model=model if model is not None else settings.GEMINI_MODEL,
            )

        case "groq":
            from app.providers.llm.groq import GroqProvider
            return GroqProvider(
                api_key=api_key if api_key is not None else settings.GROQ_API_KEY,
                model=model if model is not None else settings.GROQ_MODEL,
            )

        case "openrouter" | "open_router":
            from app.providers.llm.openrouter import OpenRouterProvider
            return OpenRouterProvider(
                api_key=api_key if api_key is not None else settings.OPENROUTER_API_KEY,
                model=model if model is not None else settings.OPENROUTER_MODEL,
                base_url=base_url if base_url is not None else settings.OPENROUTER_BASE_URL,
                site_url=site_url if site_url is not None else settings.OPENROUTER_SITE_URL,
                app_name=app_name if app_name is not None else settings.OPENROUTER_APP_NAME,
            )

        case "ollama":
            from app.providers.llm.ollama import OllamaProvider
            return OllamaProvider(
                base_url=base_url if base_url is not None else settings.OLLAMA_URL,
                model=model if model is not None else "llama3.2",
            )

        case _:
            raise ValueError(
                f"Unknown LLM provider: '{selected_provider}'. "
                f"Supported providers are: 'gemini', 'groq', 'openrouter', 'ollama'."
            )


def get_llm_provider(reload: bool = False) -> LLMProvider:
    """Return the cached default LLM provider singleton, re-instantiating if reload=True."""
    global _llm_instance
    if _llm_instance is None or reload:
        _llm_instance = create_llm_provider()
    return _llm_instance


def get_embedding_provider() -> EmbeddingProvider:
    global _embedding_instance
    if _embedding_instance is None:
        match settings.EMBEDDING_PROVIDER:
            case "huggingface":
                from app.providers.embeddings.huggingface import HuggingFaceEmbeddingProvider
                _embedding_instance = HuggingFaceEmbeddingProvider(
                    model_name=settings.HUGGINGFACE_MODEL
                )
            case "google":
                from app.providers.embeddings.google import GoogleEmbeddingProvider
                _embedding_instance = GoogleEmbeddingProvider(
                    api_key=settings.GEMINI_API_KEY
                )
            case _:
                raise ValueError(f"Unknown embedding provider: {settings.EMBEDDING_PROVIDER}")
    return _embedding_instance


def get_vectordb_provider() -> VectorStoreProvider:
    global _vectordb_instance
    if _vectordb_instance is None:
        match settings.VECTORDB_PROVIDER:
            case "chromadb":
                from app.providers.vectordb.chromadb import ChromaDBProvider
                _vectordb_instance = ChromaDBProvider(
                    persist_dir=settings.CHROMA_PERSIST_DIR
                )
            case "mongodb":
                from app.providers.vectordb.mongodb import MongoDBVectorProvider
                _vectordb_instance = MongoDBVectorProvider(
                    index_name=settings.MONGODB_VECTOR_INDEX_NAME
                )
            case _:
                raise ValueError(f"Unknown vector DB provider: {settings.VECTORDB_PROVIDER}")
    return _vectordb_instance
