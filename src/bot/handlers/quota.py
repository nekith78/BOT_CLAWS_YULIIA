"""`/quota` command — compact OpenRouter remaining-budget display.

Three lines: model, daily limit, remaining. The remaining number comes
from a counter the OpenRouterLLM instance maintains across calls (resets
at 00:00 UTC). The free-tier vs paid distinction (50 vs 1000 daily) is
read from OpenRouter's GET /api/v1/auth/key on every /quota.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.services.intent.llm_openrouter import OpenRouterLLM, fetch_quota

log = logging.getLogger(__name__)
router = Router(name="quota")


@router.message(Command("quota"))
async def handle_quota(message: Message, bot: Bot, **data: Any) -> None:
    settings = data.get("settings")
    if settings is None:
        return

    if settings.llm_provider != "openrouter":
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"/quota работает только для OpenRouter (сейчас {settings.llm_provider}).",
        )
        return

    if settings.openrouter_api_key is None:
        await bot.send_message(
            chat_id=message.chat.id, text="OPENROUTER_API_KEY не задан."
        )
        return

    try:
        info = await fetch_quota(settings.openrouter_api_key.get_secret_value())
    except Exception as exc:
        log.exception("quota: fetch failed")
        await bot.send_message(
            chat_id=message.chat.id, text=f"⚠️ Не удалось получить квоту: {exc}"
        )
        return

    is_free_tier = bool(info.get("is_free_tier", True))
    daily_limit = 50 if is_free_tier else 1000

    llm = data.get("llm")
    used = llm.daily_used() if isinstance(llm, OpenRouterLLM) else 0
    remaining = max(0, daily_limit - used)

    model = settings.llm_model or "openai/gpt-oss-120b:free"
    text = (
        f"📊 Модель: <code>{model}</code>\n"
        f"Квота: <b>{daily_limit}</b> в день\n"
        f"Осталось: <b>{remaining}</b>"
    )
    await bot.send_message(chat_id=message.chat.id, text=text)
