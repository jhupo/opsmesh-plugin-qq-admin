"""Official QQ Bot v2 group administration plugin and public async function APIs."""

from importlib.metadata import PackageNotFoundError, version

from opsmesh.plugin import PluginMetadata, get_plugin_config

from .config import AuditConfig as AuditConfig
from .config import AutoApproveConfig as AutoApproveConfig
from .config import GroupSwitchConfig as GroupSwitchConfig
from .config import QQAdminConfig as QQAdminConfig
from .config import SafeguardConfig as SafeguardConfig
from .config import WarningPolicyConfig as WarningPolicyConfig
from .context import AdminContext as AdminContext
from .context import ModerationOutcome as ModerationOutcome
from .context import OperatorIdentity as OperatorIdentity
from .exception import BotRoleInsufficientError as BotRoleInsufficientError
from .exception import CooldownActiveError as CooldownActiveError
from .exception import GroupAdminDisabledError as GroupAdminDisabledError
from .exception import PermissionDeniedError as PermissionDeniedError
from .exception import QQAdminError as QQAdminError
from .exception import QuotaExceededError as QuotaExceededError
from .exception import TargetProtectedError as TargetProtectedError
from .matchers import register_all_matchers as register_all_matchers
from .services import AdminServices as AdminServices
from .services import add_blacklist as add_blacklist
from .services import approve_join_request as approve_join_request
from .services import clear_warnings as clear_warnings
from .services import decline_join_request as decline_join_request
from .services import get_audit_log as get_audit_log
from .services import get_bot_state as get_bot_state
from .services import get_group_info as get_group_info
from .services import get_member as get_member
from .services import get_mute_setting as get_mute_setting
from .services import get_services as get_services
from .services import kick_member as kick_member
from .services import list_blacklist as list_blacklist
from .services import list_join_requests as list_join_requests
from .services import list_members as list_members
from .services import mute_member as mute_member
from .services import recall_message as recall_message
from .services import remove_blacklist as remove_blacklist
from .services import set_group_enabled as set_group_enabled
from .services import set_services as set_services
from .services import unmute_member as unmute_member
from .services import warn_member as warn_member
from .store import InMemoryStateStore as InMemoryStateStore
from .store import StateStoreProtocol as StateStoreProtocol
from .typing import AuditSource as AuditSource
from .typing import AuditStatus as AuditStatus
from .typing import EscalationAction as EscalationAction
from .typing import RoleTier as RoleTier
from .typing import ViolationType as ViolationType

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
