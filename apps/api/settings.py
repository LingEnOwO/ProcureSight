import os

from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pathlib import Path

# Load .env.local from project root (two levels up from apps/api)
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env.local")

class Settings(BaseSettings):
    DATABASE_APP_URL: str  # Non-superuser URL — RLS is enforced on every request
    S3_ENDPOINT: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    SLACK_WEBHOOK_URL: str = ""
    APP_BASE_URL: str = ""
    OPENAI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    # ARQ worker tuning (previously read via scattered os.getenv calls).
    ARQ_DB_POOL_MAX_SIZE: int = 10
    ARQ_MAX_JOBS: int = 10

    @property
    def openai_api_key(self) -> str:
        """OpenAI key, read at call time (so tests can toggle the env var),
        falling back to the value loaded from .env.local.

        NOTE: only the *fallback-style* callers (embeddings, anomaly scoring's
        vector search) use this. ``llm_client`` and ``unstructured_extract``
        deliberately read ``os.getenv`` directly and raise when it is absent —
        that raise-on-missing behavior is what lets alert explanations and PDF
        extraction degrade to deterministic fallbacks. Unifying the two
        semantics is a behavior change, intentionally left out of this cleanup.
        """
        return os.getenv("OPENAI_API_KEY") or self.OPENAI_API_KEY

    @property
    def redis_settings(self):
        from arq.connections import RedisSettings
        return RedisSettings(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            password=self.REDIS_PASSWORD or None,
        )

settings = Settings()