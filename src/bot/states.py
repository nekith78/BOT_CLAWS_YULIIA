"""FSM state groups for multi-step flows."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddAppointment(StatesGroup):
    choosing_client = State()
    searching_client = State()
    creating_client_name = State()
    creating_client_instagram = State()
    confirming_delete = State()  # confirm-delete dialog within wizard
    choosing_date = State()
    entering_date = State()
    choosing_time = State()
    entering_time = State()
    entering_note = State()
    confirming = State()
    resolving_conflict = State()


class EditAppointment(StatesGroup):
    entering_note = State()
    choosing_new_date = State()
    choosing_new_time = State()


class EditClient(StatesGroup):
    editing_name = State()
    editing_instagram = State()
    editing_notes = State()


class HistoryFilter(StatesGroup):
    entering_date = State()


class ListsFilter(StatesGroup):
    choosing_date = State()  # calendar is open in lists scope


class BrowseClients(StatesGroup):
    searching = State()
    confirming_delete = State()


class IntakePending(StatesGroup):
    """Voice/text intake — pending user decision after Action.plan.

    confirming: action.plan returned CONFIRM, waiting for ✅/✏️/❌.
    clarifying: action.plan returned CLARIFY, waiting for option pick.
    editing_field_text: user tapped «✏️ Изменить <text-field>» on the
        confirm-card; the bot is waiting for the next message (text or
        voice) to use as the new field value.
    """

    confirming = State()
    clarifying = State()
    editing_field_text = State()


class NotifySettings(StatesGroup):
    """Per-appointment notify-rule editor flow.

    Started from ⚙️ Настройки → 🔔 Настройка уведомлений.
    """

    choosing_period = State()      # which slice of appointments to list
    choosing_date = State()        # calendar open in notify-settings scope
    listing_appointments = State()
    viewing_rules = State()        # the per-appointment screen
    adding_rule_kind = State()     # picking time_day_before / time_same_day / offset_before
    adding_rule_time = State()     # entering HH:MM
    adding_rule_offset = State()   # entering "60m" / "2h" / "1d"
