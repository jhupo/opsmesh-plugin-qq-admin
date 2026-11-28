"""Official QQ Bot v2 group administration client plugin for OpsMesh."""

from importlib.metadata import PackageNotFoundError, version

from opsmesh.plugin import PluginMetadata

try:
    __version__: str | None = version("opsmesh-plugin-qq-admin")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.1.0"

__plugin_meta__ = PluginMetadata(
    name="QQ Official Group Admin",
    description=(
        "High-cohesion QQGroupAdmin and QQGroupScope client classes "
        "covering all Official QQ Bot v2 group management APIs"
    ),
    usage=("from qq_admin import QQGroupAdmin, QQGroupScope, GroupAdmin, CurrentGroup"),
    type="library",
    homepage="https://github.com/jhupo/opsmesh-plugin-qq-admin",
    supported_adapters={"qq"},
)


from .client import MuteDuration as MuteDuration
from .client import QQGroupAdmin as QQGroupAdmin
from .client import QQGroupScope as QQGroupScope
from .client import can_manage_member as can_manage_member
from .client import ensure_can_manage as ensure_can_manage
from .client import extract_group_openid as extract_group_openid
from .client import parse_mute_duration as parse_mute_duration
from .exception import BotNotAdminError as BotNotAdminError
from .exception import GroupTargetRequiredError as GroupTargetRequiredError
from .exception import HierarchyError as HierarchyError
from .exception import QQAdminError as QQAdminError
from .params import CurrentGroup as CurrentGroup
from .params import GroupAdmin as GroupAdmin
from .params import get_current_group as get_current_group
from .params import get_group_admin as get_group_admin
