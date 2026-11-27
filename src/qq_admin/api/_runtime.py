"""Shared runtime AdminServices holder used by standalone public API functions."""

from qq_admin.services import AdminServices

_services: AdminServices | None = None


def set_services(services: AdminServices) -> None:
    """Bind the active AdminServices instance for standalone API calls."""
    global _services
    _services = services


def get_services() -> AdminServices:
    """Return the bound AdminServices instance (lazily created if unset)."""
    global _services
    if _services is None:
        _services = AdminServices.create()
    return _services


def resolve_services(services: AdminServices | None) -> AdminServices:
    return services if services is not None else get_services()


__all__ = ["get_services", "resolve_services", "set_services"]
