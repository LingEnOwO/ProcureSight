from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pathlib import Path

# Load .env.local from project root (two levels up from apps/api)
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env.local")

class Settings(BaseSettings):
    DATABASE_URL: str
    S3_ENDPOINT: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str
    NEXTAUTH_SECRET: str  # Required for decoding NextAuth JWTs

settings = Settings()