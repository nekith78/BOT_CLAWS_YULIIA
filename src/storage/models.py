"""SQLAlchemy declarative models.

Models stay dumb — pure schema, no business logic. Validation and queries
live in repositories and services.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Setting(Base):
    """Global key/value store. Used for timezone, notify_preset, default_duration_min."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=func.now(), onupdate=func.now()
    )


class Client(Base):
    """Постоянные данные клиента. Один клиент = много appointments."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    instagram: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_clients_name_lower", func.lower(name)),
    )


class Appointment(Base):
    """Один визит. Длительность по умолчанию 60 мин — для проверки конфликтов."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    visit_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_appt_starts_status", "starts_at", "status"),
        Index("idx_appt_client", "client_id"),
    )


class NotifyRule(Base):
    """Правило уведомлений (UI-настраиваемое).

    kind: time_day_before | time_same_day | offset_before
    value: для time_* — "HH:MM"; для offset_before — "60m" / "24h" / "2d"
    """

    __tablename__ = "notify_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())


class ScheduledJob(Base):
    """Запланированный пуш. Сохраняется в БД, чтобы переживать рестарты."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("notify_rules.id", ondelete="SET NULL"), nullable=True
    )
    fire_at: Mapped[datetime] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("idx_jobs_fire_sent", "fire_at", "sent_at"),
    )
