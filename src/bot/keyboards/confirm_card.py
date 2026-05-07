"""Confirm-card keyboard for voice/text intake destructive actions.

Layout adapts to the action:

    [<confirm_label>]
    [✏️ Изменить]   [<cancel_label>]              ← show_edit=True
    [<cancel_label>]                                ← show_edit=False

`confirm_label` and `cancel_label` come from the action class
(`CreateAppointmentAction.confirm_label` etc.). Destructive actions
like delete/cancel use «🗑 Удалить» / «✅ Отменить запись» instead of
the save-style defaults.

Per-field edit lives behind «✏️ Изменить» — a separate sub-menu shows
which fields are editable. For actions with no editable fields
(cancel_appointment, delete_client) we drop the «Изменить» button.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import IntakeCD


def confirm_card_kb(
    *,
    tag: str,
    confirm_label: str = "✅ Сохранить",
    cancel_label: str = "❌ Отменить",
    show_edit: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=confirm_label,
                callback_data=IntakeCD(action="confirm", tag=tag).pack(),
            )
        ]
    ]
    if show_edit:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=IntakeCD(action="edit", tag=tag).pack(),
                ),
                InlineKeyboardButton(
                    text=cancel_label,
                    callback_data=IntakeCD(action="cancel", tag=tag).pack(),
                ),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text=cancel_label,
                    callback_data=IntakeCD(action="cancel", tag=tag).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
