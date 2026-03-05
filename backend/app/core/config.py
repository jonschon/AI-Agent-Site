from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI News Platform API"
    environment: str = "development"
    database_url: str = "sqlite+pysqlite:///./ai_news.db"
    api_prefix: str = "/v1"
    internal_api_key: str = "dev-internal-key"

    publish_interval_minutes: int = 10
    crawl_interval_minutes: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
