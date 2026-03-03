from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pathlib import Path

# Load .env.local from project root (two levels up from apps/api)
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env.local")

class Settings(BaseSettings):
    DATABASE_URL: str          # Superuser URL — for migrations/seeding only
    DATABASE_APP_URL: str = "" # Non-superuser URL — used by FastAPI so RLS is enforced
    S3_ENDPOINT: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str

    @property
    def app_db_url(self) -> str:
        """Return DATABASE_APP_URL if set, else fall back to DATABASE_URL."""
        return self.DATABASE_APP_URL or self.DATABASE_URL

settings = Settings()