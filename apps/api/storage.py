import uuid
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import boto3

load_dotenv(".env.local")
class Settings(BaseSettings):
    S3_ENDPOINT: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET: str

settings = Settings()

s3 = boto3.client(
    "s3",
    endpoint_url=settings.S3_ENDPOINT,
    aws_access_key_id=settings.S3_ACCESS_KEY,
    aws_secret_access_key=settings.S3_SECRET_KEY,
)

def put_object(org_id: str, filename: str, content_type: str, body: bytes) -> str:
    safe_name = filename.replace("/", "_")
    key = f"org/{org_id}/uploads/{uuid.uuid4()}/{safe_name}"
    s3.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=body, ContentType=content_type)
    return key

def s3_ok() -> bool:
    try:
        s3.list_buckets()
        return True
    except Exception:
        return False