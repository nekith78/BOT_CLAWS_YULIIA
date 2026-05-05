"""Repository layer — typed accessors for models."""

from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

__all__ = ["AppointmentRepository", "ClientRepository"]
