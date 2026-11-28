"""Automatic Official QQ Bot v2 group administration plugin for OpsMesh."""

from importlib.metadata import PackageNotFoundError, version

from openai import AsyncOpenAI as _AsyncOpenAI
from opsmesh import get_driver
from opsmesh.plugin import PluginMetadata, get_plugin_config
from typesafe_sdk import AsyncTypeSafeClient as _AsyncTypeSafeClient

from .commands import bind_commands
from .config import AdminConfig as _AdminConfig
from .config import Config as _Config
from .events import bind_events
from .runtime import AdminRuntime as _AdminRuntime

try:
    __version__: str | None = version("opsmesh-plugin-qq-admin")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.2.0"

__plugin_meta__ = PluginMetadata(
    name="QQ Group Admin",
    description=(
        "Automatic Official QQ Bot v2 group administration plugin powered by "
        "typesafe-sdk (Jev) and dual OpenAI Agents SDK controllers"
    ),
    usage=(
        "/admin <status|on|off|log|perm|exempt|unexempt|undo> | "
        "/warn | /mute | /unmute | /kick | /ban | /unban | /recall | "
        "/approve | /reject | /shutlist | /blacklist | /requests | /member"
    ),
    type="application",
    homepage="https://github.com/jhupo/opsmesh-plugin-qq-admin",
    config=_Config,
    supported_adapters={"qq"},
)

_runtime: _AdminRuntime | None = None


def configure(
    config: _AdminConfig | None = None,
    *,
    jev_client: _AsyncTypeSafeClient | None = None,
    openai_client: _AsyncOpenAI | None = None,
) -> _AdminRuntime:
    """Create or replace the active AdminRuntime with injectable SDK clients."""
    global _runtime
    cfg = config
    if cfg is None:
        try:
            cfg = get_plugin_config(_Config).resolve()
        except ValueError:
            cfg = _AdminConfig()
    _runtime = _AdminRuntime(
        cfg,
        jev_client=jev_client,
        openai_client=openai_client,
    )
    return _runtime


def get_runtime() -> _AdminRuntime:
    """Return the active AdminRuntime, creating a default instance if needed."""
    global _runtime
    if _runtime is None:
        return configure()
    return _runtime


# Auto-bind commands and event listeners when loaded under an active OpsMesh driver.
try:
    get_driver()
except ValueError:
    pass
else:
    _active = configure()
    if _active.config.plugin.enabled:
        bind_commands(_active)
        bind_events(_active)


from .agents import GROUP_ADMIN_TOOLS as GROUP_ADMIN_TOOLS
from .agents import DecisionOutcome as DecisionOutcome
from .agents import DecisionPlanner as DecisionPlanner
from .agents import ReplyComposer as ReplyComposer
from .agents import ReplySpec as ReplySpec
from .agents import TurnContext as TurnContext
from .agents import ban_member as ban_member
from .agents import get_member as get_member
from .agents import kick_member as kick_member
from .agents import list_muted_members as list_muted_members
from .agents import mute_member as mute_member
from .agents import recall_message as recall_message
from .agents import unban_member as unban_member
from .agents import unmute_member as unmute_member
from .agents import warn_member as warn_member
from .commands import COMMAND_ROUTES as COMMAND_ROUTES
from .commands import CommandContext as CommandContext
from .commands import CommandRoute as CommandRoute
from .commands import command as command
from .commands import dispatch_command as dispatch_command
from .config import AdminConfig as AdminConfig
from .config import AdminSettings as AdminSettings
from .config import AgentSettings as AgentSettings
from .config import ApprovalSettings as ApprovalSettings
from .config import Config as Config
from .config import EscalationRule as EscalationRule
from .config import EscalationSettings as EscalationSettings
from .config import GroupApprovalPolicy as GroupApprovalPolicy
from .config import IdentitySettings as IdentitySettings
from .config import JevSettings as JevSettings
from .config import LoggingSettings as LoggingSettings
from .config import ModerationSettings as ModerationSettings
from .config import PluginSettings as PluginSettings
from .config import SafeguardSettings as SafeguardSettings
from .config import WarningSettings as WarningSettings
from .events import EventRouter as EventRouter
from .exception import BotNotAdminError as BotNotAdminError
from .exception import PermissionDeniedError as PermissionDeniedError
from .exception import QQAdminError as QQAdminError
from .exception import SafeguardBlockedError as SafeguardBlockedError
from .jev import AsyncTypeSafeClient as AsyncTypeSafeClient
from .jev import JevEvaluator as JevEvaluator
from .jev import JoinRiskAssessment as JoinRiskAssessment
from .jev import MessageAssessment as MessageAssessment
from .jev import SafetyVerdict as SafetyVerdict
from .moderation import ActionOutcome as ActionOutcome
from .moderation import GroupModerator as GroupModerator
from .moderation import JoinApprover as JoinApprover
from .moderation import MuteDuration as MuteDuration
from .moderation import PermissionTrace as PermissionTrace
from .moderation import PolicyVerdict as PolicyVerdict
from .moderation import SafeguardPolicy as SafeguardPolicy
from .moderation import format_duration as format_duration
from .moderation import parse_duration as parse_duration
from .resources import DEFAULT_CONFIG_PATH as DEFAULT_CONFIG_PATH
from .resources import DEFAULT_PROMPTS_PATH as DEFAULT_PROMPTS_PATH
from .resources import PromptCatalog as PromptCatalog
from .runtime import AdminRuntime as AdminRuntime
from .state import AuditRecord as AuditRecord
from .state import GroupStateStore as GroupStateStore
from .state import MessageSnapshot as MessageSnapshot
