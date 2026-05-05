"""Repository-layer tests (using in-memory SQLite from conftest)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.notify_rules import NotifyRuleRepository
from src.storage.repositories.settings import SettingRepository


@pytest.mark.asyncio
async def test_create_and_get_by_id(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Олег", instagram="oleg_insta", notes="любит чай")

    fetched = await repo.get(client.id)
    assert fetched is not None
    assert fetched.name == "Олег"
    assert fetched.instagram == "oleg_insta"


@pytest.mark.asyncio
async def test_search_by_name_case_insensitive(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Анна Петрова")
    await repo.create(name="Олег Иванов")
    await repo.create(name="анна сидорова")

    results = await repo.search_by_name("анн")
    names = [c.name for c in results]
    assert "Анна Петрова" in names
    assert "анна сидорова" in names
    assert "Олег Иванов" not in names


@pytest.mark.asyncio
async def test_list_recent(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    for n in ["a", "b", "c", "d", "e"]:
        await repo.create(name=n)

    recent = await repo.list_recent(limit=3)
    assert len(recent) == 3


@pytest.mark.asyncio
async def test_update_partial(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Олег")
    updated = await repo.update(client.id, instagram="oleg2", notes="VIP")

    assert updated is not None
    assert updated.instagram == "oleg2"
    assert updated.notes == "VIP"
    assert updated.name == "Олег"  # не изменилось


@pytest.mark.asyncio
async def test_delete(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Tmp")
    deleted = await repo.delete(client.id)
    assert deleted is True

    fetched = await repo.get(client.id)
    assert fetched is None


def _utc(year: int, month: int, day: int, hh: int, mm: int = 0) -> datetime:
    # Return naive UTC datetime for SQLite storage
    return datetime(year, month, day, hh, mm)


@pytest.mark.asyncio
async def test_create_appointment_for_client(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="Олег")

    appt = await appts.create(
        client_id=client.id,
        starts_at=_utc(2026, 5, 6, 14),
        duration_min=60,
        visit_note="маникюр",
    )
    assert appt.id is not None
    assert appt.status == "scheduled"


@pytest.mark.asyncio
async def test_find_overlap_includes_partial(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    await appts.create(
        client_id=client.id, starts_at=_utc(2026, 5, 6, 14), duration_min=60
    )

    # Новый слот 14:30-15:30 пересекается с 14:00-15:00
    conflict = await appts.find_overlap(
        starts_at=_utc(2026, 5, 6, 14, 30), duration_min=60
    )
    assert len(conflict) == 1


@pytest.mark.asyncio
async def test_find_overlap_excludes_back_to_back(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    await appts.create(
        client_id=client.id, starts_at=_utc(2026, 5, 6, 14), duration_min=60
    )

    # 15:00-16:00 — впритык, не пересекается
    conflict = await appts.find_overlap(
        starts_at=_utc(2026, 5, 6, 15), duration_min=60
    )
    assert conflict == []


@pytest.mark.asyncio
async def test_find_overlap_excludes_cancelled(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    a = await appts.create(
        client_id=client.id, starts_at=_utc(2026, 5, 6, 14), duration_min=60
    )
    await appts.update_status(a.id, "cancelled")

    conflict = await appts.find_overlap(
        starts_at=_utc(2026, 5, 6, 14, 30), duration_min=60
    )
    assert conflict == []


@pytest.mark.asyncio
async def test_list_in_range(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 9))
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 18))
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 7, 10))

    result = await appts.list_in_range(
        start=_utc(2026, 5, 6, 0), end=_utc(2026, 5, 7, 0)
    )
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_for_client_returns_newest_first(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    a = await clients.create(name="A")
    b = await clients.create(name="B")
    await appts.create(client_id=a.id, starts_at=_utc(2026, 5, 6, 10))
    await appts.create(client_id=a.id, starts_at=_utc(2026, 5, 8, 14))
    await appts.create(client_id=b.id, starts_at=_utc(2026, 5, 6, 11))

    result = await appts.list_for_client(a.id)
    assert [appt.starts_at for appt in result] == [
        _utc(2026, 5, 8, 14),
        _utc(2026, 5, 6, 10),
    ]


@pytest.mark.asyncio
async def test_list_for_client_filters_by_window(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 1, 10))
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 14))
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 10, 9))

    result = await appts.list_for_client(
        client.id, start=_utc(2026, 5, 5, 0), end=_utc(2026, 5, 9, 0)
    )
    assert [appt.starts_at for appt in result] == [_utc(2026, 5, 6, 14)]


@pytest.mark.asyncio
async def test_update_visit_note(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    appt = await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 10))
    updated = await appts.update_visit_note(appt.id, "новая заметка")
    assert updated is not None
    assert updated.visit_note == "новая заметка"
    assert (await appts.get(appt.id)).visit_note == "новая заметка"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_update_visit_note_returns_none_for_missing(session: AsyncSession) -> None:
    appts = AppointmentRepository(session)
    assert await appts.update_visit_note(9999, "x") is None


@pytest.mark.asyncio
async def test_notify_rule_create_and_list_enabled(session: AsyncSession) -> None:
    repo = NotifyRuleRepository(session)
    await repo.create(kind="time_day_before", value="20:00", enabled=True)
    await repo.create(kind="time_same_day", value="09:00", enabled=True)
    await repo.create(kind="offset_before", value="60m", enabled=False)

    enabled = await repo.list_enabled()
    assert len(enabled) == 2
    kinds = {r.kind for r in enabled}
    assert kinds == {"time_day_before", "time_same_day"}


@pytest.mark.asyncio
async def test_notify_rule_toggle(session: AsyncSession) -> None:
    repo = NotifyRuleRepository(session)
    rule = await repo.create(kind="offset_before", value="60m", enabled=False)

    toggled = await repo.set_enabled(rule.id, True)
    assert toggled is not None
    assert toggled.enabled is True


@pytest.mark.asyncio
async def test_notify_rule_replace_all(session: AsyncSession) -> None:
    repo = NotifyRuleRepository(session)
    await repo.create(kind="offset_before", value="60m")
    await repo.create(kind="offset_before", value="24h")

    await repo.replace_all([
        ("time_day_before", "20:00", True),
        ("time_same_day", "09:00", True),
    ])

    all_rules = await repo.list_all()
    assert len(all_rules) == 2
    assert {r.kind for r in all_rules} == {"time_day_before", "time_same_day"}


@pytest.mark.asyncio
async def test_setting_get_returns_none_when_missing(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    assert await repo.get("missing") is None


@pytest.mark.asyncio
async def test_setting_set_then_get(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    await repo.set("timezone", "Asia/Almaty")

    val = await repo.get("timezone")
    assert val == "Asia/Almaty"


@pytest.mark.asyncio
async def test_setting_set_overwrites(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    await repo.set("preset", "eve_morning")
    await repo.set("preset", "eve_only")

    assert await repo.get("preset") == "eve_only"


@pytest.mark.asyncio
async def test_setting_get_int(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    await repo.set("default_duration_min", "60")
    assert await repo.get_int("default_duration_min") == 60
    assert await repo.get_int("missing", default=15) == 15
