"""Repository layer — typed accessors for models."""

from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.notify_rules import NotifyRuleRepository

__all__ = ["AppointmentRepository", "ClientRepository", "NotifyRuleRepository"]
