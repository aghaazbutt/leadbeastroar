from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "staging", "prod"] = Field("dev", alias="LB_ENV")
    secret_key: str = Field("insecure-dev-key", alias="LB_SECRET_KEY")
    api_token: str = Field("operator-token-change-me", alias="LB_API_TOKEN")
    operator_email: str = Field("you@example.com", alias="LB_OPERATOR_EMAIL")
    timezone: str = Field("Asia/Karachi", alias="LB_TIMEZONE")
    log_level: str = Field("INFO", alias="LB_LOG_LEVEL")
    dry_run: bool = Field(True, alias="LB_DRY_RUN")

    database_url: PostgresDsn = Field(
        "postgresql+psycopg://leadbeast:change-me-in-production@postgres:5432/leadbeast",
        alias="DATABASE_URL",
    )
    procrastinate_dsn: str = Field(
        "postgresql://leadbeast:change-me-in-production@postgres:5432/leadbeast",
        alias="PROCRASTINATE_DSN",
    )

    cap_per_run_cents: int = Field(500, alias="LB_CAP_PER_RUN")
    cap_per_day_cents: int = Field(2000, alias="LB_CAP_PER_DAY")
    cap_per_month_cents: int = Field(30000, alias="LB_CAP_PER_MONTH")

    model_provider: Literal["ollama", "anthropic", "openai"] = Field(
        "ollama", alias="LB_MODEL_PROVIDER"
    )
    ollama_host: str = Field("http://ollama:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field("llama3.1:8b", alias="OLLAMA_MODEL")
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    google_places_api_key: str = Field("", alias="GOOGLE_PLACES_API_KEY")
    osm_user_agent: str = Field("leadbeast/0.1", alias="OSM_USER_AGENT")

    channel_provider: Literal["listmonk", "ses", "null"] = Field(
        "null", alias="LB_CHANNEL_PROVIDER"
    )
    aws_access_key_id: str = Field("", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field("", alias="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field("us-east-1", alias="AWS_REGION")
    ses_from_email: str = Field("", alias="SES_FROM_EMAIL")
    listmonk_url: str = Field("", alias="LISTMONK_URL")
    listmonk_user: str = Field("", alias="LISTMONK_USER")
    listmonk_password: str = Field("", alias="LISTMONK_PASSWORD")

    crm_provider: Literal["espo", "null"] = Field("null", alias="LB_CRM_PROVIDER")
    espocrm_url: str = Field("", alias="ESPOCRM_URL")
    espocrm_api_key: str = Field("", alias="ESPOCRM_API_KEY")

    twilio_account_sid: str = Field("", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field("", alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: str = Field("", alias="TWILIO_FROM_NUMBER")

    map_provider: Literal["mapbox", "google", "none"] = Field("none", alias="LB_MAP_PROVIDER")
    mapbox_token: str = Field("", alias="MAPBOX_TOKEN")
    google_maps_api_key: str = Field("", alias="GOOGLE_MAPS_API_KEY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
