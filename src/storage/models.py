"""SQLAlchemy declarative models.

Models stay dumb — pure schema, no business logic. Validation and queries
live in repositories and services.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text, func
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
