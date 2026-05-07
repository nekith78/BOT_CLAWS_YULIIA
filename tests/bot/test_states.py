"""States are just StatesGroup containers — verify they exist with right names."""

from __future__ import annotations

from src.bot.states import (
    AddAppointment,
    BrowseClients,
    EditAppointment,
    EditClient,
    HistoryFilter,
    IntakePending,
)


def test_add_appointment_states() -> None:
    assert AddAppointment.choosing_client.state == "AddAppointment:choosing_client"
    assert AddAppointment.searching_client.state == "AddAppointment:searching_client"
    assert AddAppointment.creating_client_name.state == "AddAppointment:creating_client_name"
    assert (
        AddAppointment.creating_client_instagram.state
        == "AddAppointment:creating_client_instagram"
    )
    assert AddAppointment.choosing_date.state == "AddAppointment:choosing_date"
    assert AddAppointment.entering_date.state == "AddAppointment:entering_date"
    assert AddAppointment.choosing_time.state == "AddAppointment:choosing_time"
    assert AddAppointment.entering_time.state == "AddAppointment:entering_time"
    assert AddAppointment.entering_note.state == "AddAppointment:entering_note"
    assert AddAppointment.confirming.state == "AddAppointment:confirming"
    assert AddAppointment.resolving_conflict.state == "AddAppointment:resolving_conflict"


def test_edit_appointment_states() -> None:
    assert EditAppointment.entering_note.state == "EditAppointment:entering_note"
    assert EditAppointment.choosing_new_date.state == "EditAppointment:choosing_new_date"
    assert EditAppointment.choosing_new_time.state == "EditAppointment:choosing_new_time"


def test_edit_client_states() -> None:
    assert EditClient.editing_name.state == "EditClient:editing_name"
    assert EditClient.editing_instagram.state == "EditClient:editing_instagram"
    assert EditClient.editing_notes.state == "EditClient:editing_notes"


def test_history_filter_states() -> None:
    assert HistoryFilter.entering_date.state == "HistoryFilter:entering_date"


def test_browse_clients_states() -> None:
    assert BrowseClients.searching.state == "BrowseClients:searching"


def test_intake_pending_smart_brain_states() -> None:
    """Plan #6 — second-brain question loop adds two states."""
    assert IntakePending.smart_brain_pick.state == "IntakePending:smart_brain_pick"
    assert IntakePending.smart_brain_text.state == "IntakePending:smart_brain_text"
