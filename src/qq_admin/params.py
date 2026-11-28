"""OpsMesh dependency-injection helpers (`GroupAdmin` and `CurrentGroup`)."""

from typing import Annotated, TypeAlias

from opsmesh.adapters import Event
from opsmesh.params import Depends
from qq import Gateway

from .client import QQGroupAdmin, QQGroupScope


def get_group_admin(gateway: Gateway) -> QQGroupAdmin:
    """Inject a stateless QQGroupAdmin client bound to the active qq.Gateway."""
    return QQGroupAdmin(gateway)


def get_current_group(gateway: Gateway, event: Event) -> QQGroupScope:
    """Inject a QQGroupScope bound to the inbound group event's group_openid."""
    return QQGroupAdmin.from_event(gateway, event)


GroupAdmin: TypeAlias = Annotated[QQGroupAdmin, Depends(get_group_admin)]
CurrentGroup: TypeAlias = Annotated[QQGroupScope, Depends(get_current_group)]
