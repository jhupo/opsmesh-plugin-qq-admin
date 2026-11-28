"""Automatic Official QQ Bot v2 group administration plugin for OpsMesh."""

from importlib.metadata import PackageNotFoundError, version

from openai import AsyncOpenAI as _AsyncOpenAI
from opsmesh import get_driver, get_gateways
from opsmesh.plugin import PluginMetadata, get_plugin_config
from qq import Gateway as _QQGateway
from typesafe_sdk import AsyncTypeSafeClient as _AsyncTypeSafeClient

from .config import Config as _Config
from .config import ConfigStore as _ConfigStore
from .config import DecisionAgentConfig as _DecisionAgentConfig
from .config import JevConfig as _JevConfig
from .config import OpenAIConfig as _OpenAIConfig
from .config import ReplyAgentConfig as _ReplyAgentConfig
from .manager import ServiceManager as _ServiceManager
from .manager import get_manager as _get_manager
from .manager import set_manager as _set_manager

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


def _qq_gateways() -> list[_QQGateway]:
    return [gw for gw in get_gateways().values() if isinstance(gw, _QQGateway)]


def configure(
    *,
    jev_config: _JevConfig | None = None,
    openai_config: _OpenAIConfig | None = None,
    decision_config: _DecisionAgentConfig | None = None,
    reply_config: _ReplyAgentConfig | None = None,
    store: _ConfigStore | None = None,
    prompts_path: str | None = None,
    jev_client: _AsyncTypeSafeClient | None = None,
    openai_client: _AsyncOpenAI | None = None,
) -> _ServiceManager:
    """Initialize or replace the active ServiceManager with injectable SDK clients."""
    if (
        jev_config is None
        and openai_config is None
        and decision_config is None
        and reply_config is None
        and store is None
    ):
        try:
            plugin_cfg = get_plugin_config(_Config)
            (
                jev_config,
                openai_config,
                decision_config,
                reply_config,
                store,
            ) = plugin_cfg.build_store()
            prompts_path = prompts_path or plugin_cfg.qq_admin_prompts or None
        except ValueError:
            jev_config = _JevConfig()
            openai_config = _OpenAIConfig()
            decision_config = _DecisionAgentConfig()
            reply_config = _ReplyAgentConfig()
            store = _ConfigStore()

    return _set_manager(
        _ServiceManager(
            jev_config=jev_config,
            openai_config=openai_config,
            decision_config=decision_config,
            reply_config=reply_config,
            store=store,
            prompts_path=prompts_path,
            jev_client=jev_client,
            openai_client=openai_client,
        )
    )


def get_manager() -> _ServiceManager:
    """Return the active ServiceManager, creating a default instance if needed."""
    return _get_manager()


# Auto-register direct on_command / on_message / on_notice handlers under OpsMesh.
try:
    _driver = get_driver()
except ValueError:
    pass
else:
    _active = configure()
    from . import commands as _commands  # noqa: F401
    from . import messages as _messages  # noqa: F401

    @_driver.on_startup
    async def _on_startup() -> None:
        _active.start(_qq_gateways)

    @_driver.on_shutdown
    async def _on_shutdown() -> None:
        await _active.shutdown()


from .config import BaseAgentConfig as BaseAgentConfig
from .config import Config as Config
from .config import ConfigStore as ConfigStore
from .config import DecisionAgentConfig as DecisionAgentConfig
from .config import JevConfig as JevConfig
from .config import OpenAIConfig as OpenAIConfig
from .config import ReasoningEffort as ReasoningEffort
from .config import ReplyAgentConfig as ReplyAgentConfig
from .exception import BotNotAdminError as BotNotAdminError
from .exception import ConfigError as ConfigError
from .exception import PermissionDeniedError as PermissionDeniedError
from .exception import QQAdminError as QQAdminError
from .exception import SafeguardBlockedError as SafeguardBlockedError
from .manager import ServiceManager as ServiceManager
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
from .resources import DEFAULT_CONFIG_PATH as DEFAULT_CONFIG_PATH
from .resources import DEFAULT_PROMPTS_PATH as DEFAULT_PROMPTS_PATH
from .resources import PromptCatalog as PromptCatalog
