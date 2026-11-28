"""Declarative command router eliminating repetitive auth and parsing boilerplate."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import re
from typing import Any

from opsmesh import on_message
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.agents import ReplySpec
from qq_admin.moderation import ActionOutcome, MinimumRole
from qq_admin.runtime import AdminRuntime


@dataclass(slots=True)
class CommandContext:
    """Execution context supplied to every declarative command function."""

    gateway: Gateway
    event: GroupMessageEvent
    runtime: AdminRuntime

    @property
    def group_id(self) -> str:
        return self.event.group_openid

    @property
    def operator_id(self) -> str:
        return self.event.get_user_id()

    async def compose_reply(
        self,
        *,
        scenario: str,
        fallback: str,
        target_id: str = "",
        executed_actions: list[str] | None = None,
        facts: dict[str, Any] | None = None,
    ) -> str:
        if not self.runtime.config.agent.enabled:
            return fallback
        bot_role = await self.runtime.policy.bot_role(self.gateway, self.group_id)
        actor_role = await self.runtime.policy.member_role(
            self.gateway, self.group_id, self.operator_id
        )
        return await self.runtime.composer.compose(
            ReplySpec(
                runtime=self.runtime,
                group_id=self.group_id,
                bot_role=bot_role,
                scenario=scenario,
                actor_id=self.operator_id,
                actor_role=actor_role,
                target_id=target_id,
                executed_actions=executed_actions or [],
                facts=facts or {},
                fallback=fallback,
            )
        )


CommandHandler = Callable[..., Awaitable[ActionOutcome | str]]


@dataclass(frozen=True, slots=True)
class CommandRoute:
    """Declarative specification for one slash command."""

    name: str
    prefix_regex: re.Pattern[str]
    arg_regex: re.Pattern[str]
    role: MinimumRole
    usage: str
    handler: CommandHandler


COMMAND_ROUTES: list[CommandRoute] = []


def command(
    name: str,
    *,
    prefix: str,
    pattern: str,
    role: MinimumRole = "admin",
    usage: str = "",
) -> Callable[[CommandHandler], CommandHandler]:
    """Register a top-level async function as a declarative group command."""
    prefix_re = re.compile(rf"^{prefix}(?:\s+|$)", re.IGNORECASE)
    arg_re = re.compile(pattern, re.IGNORECASE)

    def _decorator(fn: CommandHandler) -> CommandHandler:
        COMMAND_ROUTES.append(
            CommandRoute(
                name=name,
                prefix_regex=prefix_re,
                arg_regex=arg_re,
                role=role,
                usage=usage or prefix,
                handler=fn,
            )
        )
        return fn

    return _decorator


def _clean_kwargs(groups: dict[str, str | None]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, val in groups.items():
        if val is None:
            continue
        text = val.strip()
        if key == "member":
            text = text.lstrip("@")
        cleaned[key] = text
    return cleaned


async def _render_outcome(
    ctx: CommandContext, outcome: ActionOutcome, target_id: str
) -> str:
    scenario = (
        "guard_blocked"
        if outcome.blocked_by
        else ("command_executed" if outcome.succeeded else "command_failed")
    )
    return await ctx.compose_reply(
        scenario=scenario,
        fallback=outcome.message,
        target_id=target_id,
        executed_actions=[outcome.action] if outcome.succeeded else [],
        facts={
            "action": outcome.action,
            "succeeded": outcome.succeeded,
            "blocked_by": outcome.blocked_by,
            "detail": outcome.message,
        },
    )


async def dispatch_command(
    gateway: Gateway,
    event: GroupMessageEvent,
    runtime: AdminRuntime,
) -> tuple[bool, str | None]:
    """Match and execute a registered command.

    Returns (matched, reply_text_or_none).
    """
    text = event.get_plaintext().strip() or (event.content or "").strip()
    if not text.startswith("/"):
        return False, None

    route = next((r for r in COMMAND_ROUTES if r.prefix_regex.match(text)), None)
    if route is None:
        return False, None

    ctx = CommandContext(gateway=gateway, event=event, runtime=runtime)
    allowed, trace = await runtime.policy.authorize(
        gateway,
        ctx.group_id,
        ctx.operator_id,
        minimum_role=route.role,
        command=route.name,
    )
    if not allowed:
        if runtime.config.admin.deny_response != "reply":
            return True, None
        reply = await ctx.compose_reply(
            scenario="permission_denied",
            fallback=runtime.catalog.format_fallback("denied"),
            facts={"command": route.name, "reason": trace.reason},
        )
        return True, reply

    match = route.arg_regex.match(text)
    if match is None:
        return True, f"Usage: {route.usage}"

    kwargs = _clean_kwargs(match.groupdict())
    result = await route.handler(ctx, **kwargs)
    if isinstance(result, ActionOutcome):
        return True, await _render_outcome(ctx, result, kwargs.get("member", ""))
    return True, result


def bind_commands(runtime: AdminRuntime) -> None:
    """Bind the declarative command table onto OpsMesh message routing."""
    cmd_matcher = on_message(priority=1, block=False)

    @cmd_matcher.handle()
    async def _route_command(
        gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
    ) -> None:
        matched, reply = await dispatch_command(gateway, event, runtime)
        if not matched:
            return
        matcher.stop_propagation()
        if reply:
            await matcher.finish(reply)
        await matcher.finish()


__all__ = [
    "COMMAND_ROUTES",
    "CommandContext",
    "CommandRoute",
    "bind_commands",
    "command",
    "dispatch_command",
]
