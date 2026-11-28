"""Automatic Official QQ Bot v2 group administration plugin for OpsMesh."""

from importlib.metadata import PackageNotFoundError, version

from opsmesh import get_driver
from opsmesh.plugin import PluginMetadata, get_plugin_config

from .config import Config as _Config
from .manager import manager

try:
    __version__: str | None = version("opsmesh-plugin-qq-admin")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.2.0"

__plugin_meta__ = PluginMetadata(
    name="QQ Group Admin",
    description=(
        "Automatic Official QQ Bot v2 group administration plugin powered by "
        "TypeSafe AI Jev and dual OpenAI Agents SDK controllers"
    ),
    usage=(
        "/admin <status|on|off|config|log|perm|exempt|unexempt|undo> | "
        "/warn | /mute | /unmute | /kick | /ban | /unban | /recall | "
        "/approve | /reject | /shutlist | /blacklist | /requests | /member"
    ),
    type="application",
    homepage="https://github.com/jhupo/opsmesh-plugin-qq-admin",
    config=_Config,
    supported_adapters={"qq"},
)


try:
    _driver = get_driver()
except ValueError:
    pass
else:
    manager.setup(get_plugin_config(_Config))
    from . import commands as _commands  # noqa: F401
    from . import messages as _messages  # noqa: F401

    @_driver.on_shutdown
    async def _on_shutdown() -> None:
        await manager.shutdown()


from .config import Config as Config
from .config import ReasoningEffort as ReasoningEffort
from .exception import BotNotAdminError as BotNotAdminError
from .exception import ConfigError as ConfigError
from .exception import PermissionDeniedError as PermissionDeniedError
from .exception import QQAdminError as QQAdminError
from .exception import SafeguardBlockedError as SafeguardBlockedError
from .manager import ServiceManager as ServiceManager
from .manager import manager as manager
from .models import GROUP_ADMIN_TOOLS as GROUP_ADMIN_TOOLS
from .models import AsyncTypeSafeClient as AsyncTypeSafeClient
from .models import DecisionAgent as DecisionAgent
from .models import DecisionOutcome as DecisionOutcome
from .models import Jev as Jev
from .models import ReplyAgent as ReplyAgent
from .models import ReplySpec as ReplySpec
from .models import TurnContext as TurnContext
from .models import ban_member as ban_member
from .models import get_member as get_member
from .models import kick_member as kick_member
from .models import list_muted_members as list_muted_members
from .models import mute_member as mute_member
from .models import recall_message as recall_message
from .models import unban_member as unban_member
from .models import unmute_member as unmute_member
from .models import warn_member as warn_member
from .modules import ActionOutcome as ActionOutcome
from .modules import ApprovalConfig as ApprovalConfig
from .modules import ApprovalModule as ApprovalModule
from .modules import AuditConfig as AuditConfig
from .modules import AuditModule as AuditModule
from .modules import AuditRecord as AuditRecord
from .modules import EscalationConfig as EscalationConfig
from .modules import EscalationModule as EscalationModule
from .modules import EscalationRule as EscalationRule
from .modules import IdentityConfig as IdentityConfig
from .modules import IdentityModule as IdentityModule
from .modules import MessageAssessment as MessageAssessment
from .modules import MessageSnapshot as MessageSnapshot
from .modules import ModerationConfig as ModerationConfig
from .modules import ModerationModule as ModerationModule
from .modules import MuteDuration as MuteDuration
from .modules import PermissionTrace as PermissionTrace
from .modules import PolicyVerdict as PolicyVerdict
from .modules import SafeguardConfig as SafeguardConfig
from .modules import SafeguardModule as SafeguardModule
from .modules import WarningConfig as WarningConfig
from .modules import WarningModule as WarningModule
from .modules import format_duration as format_duration
from .modules import parse_duration as parse_duration
from .prompts import PROMPTS_DIR as PROMPTS_DIR
from .prompts import PromptCatalog as PromptCatalog
from .store import ConfigStore as ConfigStore
