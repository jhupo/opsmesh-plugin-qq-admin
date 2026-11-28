"""Automatic QQ Official Bot v2 group administration plugin for OpsMesh."""

from importlib.metadata import PackageNotFoundError, version

from opsmesh import get_driver
from opsmesh.plugin import PluginMetadata, get_plugin_config
from typesafe_sdk import AsyncTypeSafeClient as _AsyncTypeSafeClient

from .config import (
    QQAdminConfig as _QQAdminConfig,
)
from .config import (
    _OpsMeshPluginConfigWrapper,
)
from .config import (
    load_prompts as _load_prompts,
)
from .handlers import register_commands, register_event_handlers
from .state import AdminState as _AdminState
from .state import PluginRuntime as _PluginRuntime

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
    config=_OpsMeshPluginConfigWrapper,
    supported_adapters={"qq"},
)

_runtime: _PluginRuntime | None = None


def configure(
    config: _QQAdminConfig | None = None,
    *,
    jev_client: _AsyncTypeSafeClient | None = None,
) -> _PluginRuntime:
    """Create or replace PluginRuntime with an optional AsyncTypeSafeClient."""
    global _runtime
    cfg = config
    if cfg is None:
        try:
            cfg = get_plugin_config(_OpsMeshPluginConfigWrapper).qq_admin
        except ValueError:
            cfg = _QQAdminConfig()
    prompts = _load_prompts(cfg.prompts_path)
    _runtime = _PluginRuntime(
        config=cfg,
        state=_AdminState(cfg),
        jev_client=jev_client,
        owns_jev_client=False,
        prompts=prompts,
    )
    return _runtime


def get_runtime() -> _PluginRuntime:
    """Return the active PluginRuntime, creating a default one if uninitialized."""
    global _runtime
    if _runtime is None:
        return configure()
    return _runtime


# Auto-register handlers and commands when loaded under an active OpsMesh driver.
try:
    get_driver()
except ValueError:
    pass
else:
    _active_runtime = configure()
    if _active_runtime.config.enabled:
        register_event_handlers(_active_runtime)
        register_commands(_active_runtime)


from .agents import MODERATION_TOOLS as MODERATION_TOOLS
from .agents import ExecutionReport as ExecutionReport
from .agents import ModerationContext as ModerationContext
from .agents import ReplyContext as ReplyContext
from .agents import build_decision_agent as build_decision_agent
from .agents import build_reply_agent as build_reply_agent
from .agents import generate_reply as generate_reply
from .agents import run_decision_agent as run_decision_agent
from .config import AdminConfig as AdminConfig
from .config import AutoApproveConfig as AutoApproveConfig
from .config import AutoModerateConfig as AutoModerateConfig
from .config import EscalationConfig as EscalationConfig
from .config import EscalationStep as EscalationStep
from .config import GroupApproveOverride as GroupApproveOverride
from .config import JevConfig as JevConfig
from .config import LLMConfig as LLMConfig
from .config import LoggingConfig as LoggingConfig
from .config import QQAdminConfig as QQAdminConfig
from .config import SafeguardConfig as SafeguardConfig
from .config import WarningConfig as WarningConfig
from .config import load_prompts as load_prompts
from .config import render_fallback_message as render_fallback_message
from .exception import BotNotAdminError as BotNotAdminError
from .exception import GuardBlockedError as GuardBlockedError
from .exception import PermissionDeniedError as PermissionDeniedError
from .exception import QQAdminError as QQAdminError
from .handlers import handle_group_message_event as handle_group_message_event
from .handlers import handle_group_notice_event as handle_group_notice_event
from .jev import AsyncTypeSafeClient as AsyncTypeSafeClient
from .jev import GuardVerdict as GuardVerdict
from .jev import JoinRiskEvaluation as JoinRiskEvaluation
from .jev import MessageEvaluation as MessageEvaluation
from .jev import close_jev_client as close_jev_client
from .jev import create_jev_client as create_jev_client
from .jev import evaluate_join_request as evaluate_join_request
from .jev import evaluate_message as evaluate_message
from .moderation import ActionResult as ActionResult
from .moderation import GuardDecision as GuardDecision
from .moderation import MuteDuration as MuteDuration
from .moderation import PermissionTrace as PermissionTrace
from .moderation import approve_join as approve_join
from .moderation import ban_member as ban_member
from .moderation import check_action_guard as check_action_guard
from .moderation import enforce_escalation_violation as enforce_escalation_violation
from .moderation import (
    evaluate_and_handle_join_request as evaluate_and_handle_join_request,
)
from .moderation import evaluate_command_permission as evaluate_command_permission
from .moderation import is_group_enabled as is_group_enabled
from .moderation import kick_member as kick_member
from .moderation import mute_member as mute_member
from .moderation import parse_mute_duration as parse_mute_duration
from .moderation import recall_message as recall_message
from .moderation import reject_join as reject_join
from .moderation import scan_join_requests_once as scan_join_requests_once
from .moderation import unban_member as unban_member
from .moderation import unmute_member as unmute_member
from .moderation import warn_member as warn_member
from .state import AdminState as AdminState
from .state import OpLogEntry as OpLogEntry
from .state import PluginRuntime as PluginRuntime
from .state import RecentMessage as RecentMessage
