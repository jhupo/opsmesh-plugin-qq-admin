"""Official QQ Bot v2 group administration plugin and public async function APIs."""

from importlib.metadata import PackageNotFoundError, version

from opsmesh.plugin import PluginMetadata, get_plugin_config

from .api import (
    add_blacklist,
    approve_join_request,
    clear_warnings,
    decline_join_request,
    get_audit_log,
    get_bot_state,
    get_group_info,
    get_member,
    get_mute_setting,
    get_services,
    kick_member,
    list_blacklist,
    list_join_requests,
    list_members,
    mute_member,
    recall_message,
    remove_blacklist,
    set_services,
    unmute_member,
    warn_member,
)
from .config import (
    AuditConfig,
    AutoApproveConfig,
    GroupSwitchConfig,
    QQAdminConfig,
    SafeguardConfig,
    WarningPolicyConfig,
)
from .context import AdminContext, ModerationOutcome, OperatorIdentity
from .exception import (
    BotRoleInsufficientError,
    CooldownActiveError,
    GroupAdminDisabledError,
    PermissionDeniedError,
    QQAdminError,
    QuotaExceededError,
    TargetProtectedError,
)
from .matchers import register_all_matchers
from .services import AdminServices
from .store import InMemoryStateStore, StateStoreProtocol
from .typing import (
    AuditSource,
    AuditStatus,
    EscalationAction,
    RoleTier,
    ViolationType,
)

try:
    __version__: str | None = version("opsmesh-plugin-qq-admin")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.1.0"

__plugin_meta__ = PluginMetadata(
    name="QQ Official Group Admin",
    description=(
        "Official QQ Bot v2 group admin commands, auto-approval, "
        "and standalone async function APIs"
    ),
    usage="/admin status | /warn | /mute | /unmute | /kick | /ban | /requests",
    type="application",
    homepage="https://github.com/jhupo/opsmesh-plugin-qq-admin",
    config=QQAdminConfig,
    supported_adapters={"qq"},
)


def init_plugin(
    config: QQAdminConfig | None = None,
    *,
    store: StateStoreProtocol | None = None,
    register_matchers: bool = True,
) -> AdminServices:
    """Initialize plugin services and register OpsMesh command/notice matchers."""
    cfg = config
    if cfg is None:
        try:
            cfg = get_plugin_config(QQAdminConfig)
        except ValueError:
            cfg = QQAdminConfig()

    services = AdminServices.create(cfg, store=store)
    set_services(services)
    if register_matchers:
        register_all_matchers(services)
    return services


__all__ = [
    "AdminContext",
    "AdminServices",
    "AuditConfig",
    "AuditSource",
    "AuditStatus",
    "AutoApproveConfig",
    "BotRoleInsufficientError",
    "CooldownActiveError",
    "EscalationAction",
    "GroupAdminDisabledError",
    "GroupSwitchConfig",
    "InMemoryStateStore",
    "ModerationOutcome",
    "OperatorIdentity",
    "PermissionDeniedError",
    "QQAdminConfig",
    "QQAdminError",
    "QuotaExceededError",
    "RoleTier",
    "SafeguardConfig",
    "StateStoreProtocol",
    "TargetProtectedError",
    "ViolationType",
    "WarningPolicyConfig",
    "__plugin_meta__",
    "__version__",
    "add_blacklist",
    "approve_join_request",
    "clear_warnings",
    "decline_join_request",
    "get_audit_log",
    "get_bot_state",
    "get_group_info",
    "get_member",
    "get_mute_setting",
    "get_services",
    "init_plugin",
    "kick_member",
    "list_blacklist",
    "list_join_requests",
    "list_members",
    "mute_member",
    "recall_message",
    "remove_blacklist",
    "set_services",
    "unmute_member",
    "warn_member",
]
