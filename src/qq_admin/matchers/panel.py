"""Admin panel commands (`/admin status|on|off|perm|quota|log`)."""

from opsmesh.params import CommandArg
from opsmesh.plugin import on_command
from qq import Gateway, GroupMessageEvent, Message

from qq_admin.exception import QQAdminError
from qq_admin.services import get_services

from . import ADMIN_PERMISSION, finish_outcome, make_command_context

admin_cmd = on_command("admin", permission=ADMIN_PERMISSION, priority=10, block=True)


@admin_cmd.handle()
async def handle_admin(
    gateway: Gateway,
    event: GroupMessageEvent,
    args: Message = CommandArg(),
) -> None:
    services = get_services()
    parts = args.extract_plain_text().strip().split()
    sub = parts[0].lower() if parts else "status"
    ctx = make_command_context(gateway, event, services=services)

    if sub in {"on", "off"}:
        await finish_outcome(
            admin_cmd, services.moderation.set_group_enabled(ctx, enabled=(sub == "on"))
        )
    if sub == "perm":
        await finish_outcome(
            admin_cmd, services.moderation.get_bot_state(ctx, force_refresh=True)
        )
    if sub == "log":
        limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        try:
            res = await services.moderation.get_audit_log(ctx, limit=limit)
        except QQAdminError as exc:
            await admin_cmd.finish(f"[{exc.code}] {exc.message}")
        lines = [
            res.summary,
            *(
                f"- [{r['source']}:{r['status']}] {r['action']} "
                f"target={r['target_openid'] or '-'}"
                for r in res.data.get("records", [])
            ),
        ]
        await admin_cmd.finish("\n".join(lines))

    enabled = await services.safeguard.is_group_enabled(event.group_openid)
    mute_used = await services.store.get_daily_quota_usage(event.group_openid, "mute")
    kick_used = await services.store.get_daily_quota_usage(event.group_openid, "kick")
    await admin_cmd.finish(
        f"Admin status: {'enabled' if enabled else 'disabled'}\n"
        f"Daily mute quota: {mute_used}/{services.config.safeguard.daily_mute_quota}\n"
        f"Daily kick quota: {kick_used}/{services.config.safeguard.daily_kick_quota}"
    )


__all__ = ["admin_cmd", "handle_admin"]
