"""`/quota` command — show OpenRouter usage and free-tier limits.

Hits OpenRouter's GET /api/v1/auth/key endpoint and renders a compact
Russian summary. Daily request count for `:free` models isn't returned
by the API; the link to https://openrouter.ai/activity covers that.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.services.intent.llm_openrouter import fetch_quota

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
            text=(
                f"📊 Команда /quota работает только для OpenRouter.\n"
                f"Сейчас LLM_PROVIDER=<b>{settings.llm_provider}</b>."
            ),
        )
        return

    if settings.openrouter_api_key is None:
        await bot.send_message(
            chat_id=message.chat.id,
            text="⚠️ OPENROUTER_API_KEY не задан в .env.",
        )
        return

    try:
        info = await fetch_quota(settings.openrouter_api_key.get_secret_value())
    except Exception as exc:
        log.exception("quota: fetch failed")
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"⚠️ Не удалось получить квоту: {exc}",
        )
        return

    is_free_tier = bool(info.get("is_free_tier", True))
    daily_limit = 50 if is_free_tier else 1000
    usage_usd = float(info.get("usage", 0.0) or 0.0)
    limit_usd = info.get("limit")
    rate_limit = info.get("rate_limit") or {}
    rl_requests = rate_limit.get("requests", "—")
    rl_interval = rate_limit.get("interval", "—")

    lines = [
        "📊 <b>OpenRouter — квоты</b>",
        "",
        f"Модель: <code>{settings.llm_model or 'openai/gpt-oss-120b:free'}</code>",
        f"Free-tier: {'да' if is_free_tier else 'нет (есть кредиты)'}",
        f"Дневной лимит на :free: <b>{daily_limit}</b> запросов",
        "(сбрасывается в 00:00 UTC = 05:00 утра по Алматы)",
        "",
        f"Per-minute: {rl_requests} запросов / {rl_interval}",
    ]
    if limit_usd is not None:
        lines.append(f"Кредиты: ${usage_usd:.4f} использовано из ${float(limit_usd):.2f}")
    else:
        lines.append(f"Кредиты использовано: ${usage_usd:.4f}")
    lines.append("")
    lines.append("📈 Точный счётчик за день: https://openrouter.ai/activity")

    await bot.send_message(chat_id=message.chat.id, text="\n".join(lines))
