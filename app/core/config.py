"""Application configuration, loaded from environment variables (12-factor)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://pumpguard:pumpguard@localhost:5432/pumpguard"
    redis_url: str = "redis://localhost:6379/0"
    data_source: Literal["synthetic", "yahoo"] = "synthetic"
    universe_path: Path = ROOT_DIR / "config" / "universe.yaml"
    benchmark_path: Path = ROOT_DIR / "data" / "benchmark" / "cases_template.csv"
    synthetic_cases_path: Path = ROOT_DIR / "data" / "benchmark" / "synthetic_cases.csv"
    artifacts_dir: Path = ROOT_DIR / "artifacts"

    llm_provider: Literal["none", "fake", "openai"] = "none"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 20.0

    cache_ttl_seconds: int = 300
    rate_limit_per_minute: int = 60
    default_alert_threshold: float = 90.0
    model_version: str = "iforest-pooled-v1"
    ingestion_lookback_days: int = 3 * 365
    scheduler_cron_hour: int = 18
    scheduler_cron_minute: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
