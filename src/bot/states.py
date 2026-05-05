"""FSM state groups for multi-step flows."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddAppointment(StatesGroup):
    choosing_client = State()
    searching_client = State()
    creating_client_name = State()
    creating_client_instagram = State()
    choosing_date = State()
    entering_date = State()
    choosing_time = State()
    entering_time = State()
    entering_note = State()
    confirming = State()


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
