"""Durable metadata registries; executable capabilities remain application-owned."""
from .service import RegistryService, Scope, get_registry

__all__ = ['RegistryService', 'Scope', 'get_registry']
