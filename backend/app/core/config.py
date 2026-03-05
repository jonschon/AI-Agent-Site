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
    story_merge_window_hours: int = 72
    story_merge_min_confidence: float = 0.72
    story_merge_max_candidates: int = 80
    ranking_weight_authority: float = 0.30
    ranking_weight_diversity: float = 0.27
    ranking_weight_recency: float = 0.23
    ranking_weight_discussion: float = 0.12
    ranking_weight_entity: float = 0.08
    ranking_lead_min_source_diversity: int = 2
    ops_max_publish_staleness_minutes: int = 20
    ops_max_open_high_exceptions: int = 10
    ops_min_bullet_compliance: float = 0.95

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
