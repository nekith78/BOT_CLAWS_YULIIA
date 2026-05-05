"""Repository-layer tests (using in-memory SQLite from conftest)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


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
