from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(".env.local")

class Settings(BaseSettings):
    DATABASE_URL: str
    S3_ENDPOINT: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str
    ORG_ID: str
    UPLOADER_ID: str | None = None

settings = Settings()