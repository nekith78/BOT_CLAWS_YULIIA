"""Application configuration loaded from environment variables.

Все секреты и настройки приходят из `.env` или окружения. На старте бот падает
с понятной ошибкой, если обязательная переменная не задана или провайдер STT/LLM
выбран без соответствующих ключей.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ----------------------------------------------------------
    bot_token: SecretStr
    owner_chat_id: int
    owner_tz: str = "Asia/Almaty"

    # --- STT provider ------------------------------------------------------
    # faster_whisper: локальный, FREE, +500 МБ к Docker-образу.
    # openai_whisper: облачный fallback, $0.006/мин, ключ в OPENAI_API_KEY.
    stt_provider: Literal["faster_whisper", "openai_whisper"] = "faster_whisper"
    whisper_model_size: str = "small"  # tiny | base | small | medium | large-v3
    voice_max_duration_sec: int = 60

    # --- LLM provider ------------------------------------------------------
    # groq: Groq Cloud (llama-3.3-70b), FREE 6000 RPD, ключ в GROQ_API_KEY.
    # gemini: Gemini Flash, FREE 1500 RPD, ключ в GEMINI_API_KEY.
    # openai_mini: gpt-4o-mini, ~$0.30/1k команд, ключ в OPENAI_API_KEY.
    # anthropic_haiku: Claude Haiku 4.5, ~$3/1k команд, ключ в ANTHROPIC_API_KEY.
    llm_provider: Literal["groq", "gemini", "openai_mini", "anthropic_haiku"] = "groq"
    llm_model: str | None = None  # optional override; each provider has a default

    # --- API keys ----------------------------------------------------------
    openai_api_key: SecretStr | None = None       # openai_whisper STT + openai_mini LLM
    gemini_api_key: SecretStr | None = None       # gemini LLM
    groq_api_key: SecretStr | None = None         # groq LLM
    anthropic_api_key: SecretStr | None = None    # anthropic_haiku LLM

    # --- Infra -------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    db_path: str = "/data/bot.db"

    # --- UX ----------------------------------------------------------------
    fsm_ttl_minutes: int = 30
    log_level: str = "INFO"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @model_validator(mode="after")
    def _validate_provider_keys(self) -> Settings:
        # STT validation. faster_whisper requires no key — runs locally.
        if self.stt_provider == "openai_whisper" and not self.openai_api_key:
            raise ValueError("STT_PROVIDER=openai_whisper requires OPENAI_API_KEY")

        # LLM validation. Each provider requires its own key.
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise ValueError("LLM_PROVIDER=groq requires GROQ_API_KEY")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
        if self.llm_provider == "openai_mini" and not self.openai_api_key:
            raise ValueError("LLM_PROVIDER=openai_mini requires OPENAI_API_KEY")
        if self.llm_provider == "anthropic_haiku" and not self.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic_haiku requires ANTHROPIC_API_KEY")
        return self


def load_settings() -> Settings:
    return Settings()


def ensure_data_dir(settings: Settings) -> None:
    """Create the parent directory of db_path if it does not exist."""
    db_dir = Path(settings.db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
