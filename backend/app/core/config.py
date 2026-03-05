from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI News Platform API"
    environment: str = "development"
    database_url: str = "sqlite+pysqlite:///./ai_news.db"
    api_prefix: str = "/v1"
    internal_api_key: str = "dev-internal-key"
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    summary_model: str = "gpt-4o-mini"
    openai_timeout_seconds: int = 30
    openai_embedding_dimensions: Optional[int] = None

    publish_interval_minutes: int = 10
    crawl_interval_minutes: int = 5
    clustering_window_hours: int = 72
    clustering_min_confidence: float = 0.58
    clustering_exception_floor: float = 0.45

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
