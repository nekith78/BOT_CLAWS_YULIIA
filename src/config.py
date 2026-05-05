"""Application configuration loaded from environment variables.

Все секреты и настройки приходят из `.env` или окружения. На старте бот падает
с понятной ошибкой, если обязательная переменная не задана или провайдер STT
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
    stt_provider: Literal["openai", "yandex"] = "openai"
    openai_api_key: SecretStr | None = None
    yandex_api_key: SecretStr | None = None
    yandex_folder_id: str | None = None

    # --- LLM parser --------------------------------------------------------
    llm_model: str = "gpt-4o-mini"
    llm_api_key: SecretStr | None = None  # fallback на openai_api_key

    # --- Infra -------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    db_path: str = "/data/bot.db"

    # --- UX ----------------------------------------------------------------
    fsm_ttl_minutes: int = 30
    log_level: str = "INFO"

    @property
    def effective_llm_key(self) -> SecretStr | None:
        return self.llm_api_key or self.openai_api_key

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @model_validator(mode="after")
    def _validate_provider_keys(self) -> Settings:
        if self.stt_provider == "openai" and not self.openai_api_key:
            raise ValueError("STT_PROVIDER=openai requires OPENAI_API_KEY")
        if self.stt_provider == "yandex" and not (
            self.yandex_api_key and self.yandex_folder_id
        ):
            raise ValueError(
                "STT_PROVIDER=yandex requires YANDEX_API_KEY and YANDEX_FOLDER_ID"
            )
        if self.effective_llm_key is None:
            raise ValueError(
                "LLM key is required: set LLM_API_KEY or OPENAI_API_KEY"
            )
        return self


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def ensure_data_dir(settings: Settings) -> None:
    """Create the parent directory of db_path if it does not exist."""
    db_dir = Path(settings.db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
