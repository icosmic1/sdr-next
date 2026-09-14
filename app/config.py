from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "SDR Next"
    database_url: str = "sqlite:///./data/sdr_next.db"
    research_interval_minutes: int = 30
    startup_refresh_enabled: bool = True
    research_worker_count: int = 1
    company_freshness_minutes: int = 5
    person_refresh_cooldown_minutes: int = 5
    request_timeout_seconds: int = 12
    max_research_pages: int = 5
    google_news_enabled: bool = True
    hacker_news_enabled: bool = True
    max_external_news_results: int = 8
    user_agent: str = "SDRNextResearchBot/1.0 (+local-development)"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    gemini_timeout_seconds: int = 30
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
