
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration.

    Configuration is loaded from environment variables, with optional
    .env support for local development.

    This works with:
    - Local development (.env)
    - Render environment variables
    - AWS ECS environment variables + Secrets Manager

    Environment variables take precedence over .env values and defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------
    LLM_PROVIDER: str = "gemini"
    EMBEDDING_PROVIDER: str = "huggingface"
    VECTORDB_PROVIDER: str = "mongodb"

    # ------------------------------------------------------------------
    # LLM providers
    # Sensitive values should be supplied through environment variables.
    # ------------------------------------------------------------------
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "models/gemini-pro-latest"

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "groq/compound"

    # Optional provider; currently unused if OPENAI_API_KEY is not set.
    OPENAI_API_KEY: str = ""

    # ------------------------------------------------------------------
    # Local provider configuration
    # ------------------------------------------------------------------
    OLLAMA_URL: str = "http://localhost:11434"
    HUGGINGFACE_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    # ------------------------------------------------------------------
    # ChromaDB
    # ------------------------------------------------------------------
    CHROMA_PERSIST_DIR: str = "./chroma_data"

    # ------------------------------------------------------------------
    # MongoDB
    # ------------------------------------------------------------------
    # Production deployments MUST override MONGODB_URI through an
    # environment variable / secret.
    MONGODB_URI: str = "mongodb://localhost:27017"

    # Render and AWS production both use the existing "ChatBot" database.
    MONGODB_DB_NAME: str = "ChatBot"

    MONGODB_VECTOR_INDEX_NAME: str = "default_vector_index"

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    # Production MUST override JWT_SECRET through an environment variable.
    JWT_SECRET: str = "change-me-in-production"

    JWT_EXPIRY_HOURS: int = 24

    # Required to access /setup and create the first super admin.
    # Empty means setup is disabled.
    PLATFORM_SETUP_KEY: str = ""

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    GEMINI_RPM_LIMIT: int = 10
    GEMINI_DAILY_LIMIT: int = 250

    # ------------------------------------------------------------------
    # RAG enhancements
    # ------------------------------------------------------------------
    HYDE_ENABLED: bool = True
    RERANK_ENABLED: bool = True
    CACHE_ENABLED: bool = True

    CACHE_SIMILARITY_THRESHOLD: float = 0.85
    CACHE_TTL_HOURS: int = 24

    RETRIEVAL_CANDIDATES: int = 30
    RETRIEVAL_TOP_K: int = 8

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    # Comma-separated origins.
    #
    # Example:
    # ALLOWED_ORIGINS=http://localhost:3000,https://synap-desk.vercel.app
    #
    # Render and AWS can each provide their own value through their
    # environment configuration without changing this source file.
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        """Return configured CORS origins as a cleaned list."""
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]


settings = Settings()
