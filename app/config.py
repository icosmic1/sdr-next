from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "SDR Next"
    database_url: str = "sqlite:///./data/sdr_next.db"
    research_interval_minutes: int = 360
    request_timeout_seconds: int = 12
    max_research_pages: int = 5
    user_agent: str = "SDRNextResearchBot/1.0 (+local-development)"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
