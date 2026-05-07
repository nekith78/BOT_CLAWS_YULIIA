"""Inline keyboard for the smart-fallback «какую запись?» question.

Renders one button per appointment option (label encodes name + date +
time), plus an «❌ Отмена» footer that cancels the whole intake. The
chosen index is sent back in `IntakeCD(action="sb_pick", index=N)`; the
bot reads `sb_question_options` from FSM data to recover the value."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import IntakeCD

if TYPE_CHECKING:
    from src.services.intent.text_normalizer import ClarifyOption


def appointment_picker_kb(
    *, options: list[ClarifyOption], tag: str
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, opt in enumerate(options):
        rows.append(
            [
                InlineKeyboardButton(
                    text=opt.label,
                    callback_data=IntakeCD(
                        action="sb_pick", tag=tag, index=idx
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=IntakeCD(action="cancel_edit", tag=tag).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
