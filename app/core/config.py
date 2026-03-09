"""
Core configuration module using Pydantic Settings for environment variable management.
"""
from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from functools import lru_cache
import secrets


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "Gmail Calendar Event Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development, staging, production

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gmail_calendar"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Encryption (for OAuth tokens)
    ENCRYPTION_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"
    
    # Google API Scopes (minimal - least privilege)
    GOOGLE_SCOPES: List[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]

    # JWT Settings
    JWT_SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Gmail Polling Settings
    GMAIL_POLL_INTERVAL_SECONDS: int = 300  # 5 minutes
    GMAIL_MAX_MESSAGES_PER_POLL: int = 50
    GMAIL_HISTORY_LOOKUP_DAYS: int = 7

    # Google Pub/Sub (optional, for production)
    GOOGLE_PUB_SUB_TOPIC: Optional[str] = None
    GOOGLE_PUB_SUB_SUBSCRIPTION: Optional[str] = None

    # LLM Settings
    LLM_PROVIDER: str = "openai"  # openai, anthropic, local
    LLM_API_KEY: str = ""
    LLM_API_URL: Optional[str] = None
    LLM_MODEL: str = "gpt-4"
    LLM_MAX_TOKENS: int = 1000
    LLM_TEMPERATURE: float = 0.3

    # Event Extraction Settings
    EVENT_MIN_CONFIDENCE_THRESHOLD: float = 0.5
    EVENT_AUTO_ADD_THRESHOLD: float = 0.8
    EVENT_HEURISTIC_KEYWORDS: List[str] = [
        "meeting", "appointment", "event", "call", "conference",
        "webinar", "workshop", "schedule", "reservation", "booking"
    ]

    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD_SECONDS: int = 60

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @validator("DATABASE_URL")
    def validate_database_url(cls, v):
        if not v:
            raise ValueError("DATABASE_URL is required")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience export
settings = get_settings()
