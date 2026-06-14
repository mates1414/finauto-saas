from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App Settings
    app_name: str = "FinAuto SaaS API"
    debug: bool = False

    # Security & Auth
    jwt_secret: str = "change-this-in-production-use-a-strong-random-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Database
    database_url: str = "sqlite:///./finauto_saas.db"

    # Queue/Task Runner: "in_memory" or "arq"
    queue_provider: str = "in_memory"
    redis_url: Optional[str] = "redis://localhost:6379"

    # Storage: "local" or "s3"
    storage_provider: str = "local"
    storage_local_path: str = "./storage_data"

    # S3 Credentials
    s3_bucket: Optional[str] = None
    s3_endpoint_url: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None

    # LLM Settings (will fall back to environment variables or finauto's keys)
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # Path to Damodaran's emerging-markets industry-beta workbook (betaemerg.xls).
    # If unset, it is auto-located next to the installed finauto package.
    damodaran_beta_path: Optional[str] = None

    # CORS: comma-separated list of allowed frontend origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
