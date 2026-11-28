"""Direct OpsMesh group message entry: admins -> @Bot control, users -> moderation."""

from opsmesh import on_message
from opsmesh.log import logger
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.manager import ServiceManager, manager

group_msg = on_message(priority=5, block=False)


async def download_images(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> list[bytes]:
    cfg = manager.moderation.config(event.group_openid)
    if not cfg.enable_image_review:
        return []
    images: list[bytes] = []
    for attachment in event.attachments[: cfg.max_images]:
        content_type = (attachment.content_type or "").lower()
        if not attachment.url or (
            content_type and not content_type.startswith("image/")
        ):
            continue
        try:
            images.append(await gateway.download_attachment(attachment.url))
        except Exception as exc:
            logger.debug(f"qq_admin skipped image download: {exc}")
    return images


async def process_group_message(
    gateway: Gateway, event: GroupMessageEvent, manager: ServiceManager
) -> tuple[bool, str | None]:
    """Return (handled, reply). Admins are never moderated; safe chat is silent."""
    group_id = event.group_openid
    member_id = event.get_user_id()
    if not group_id or not manager.is_group_enabled(group_id):
        return False, None
    text = event.get_plaintext().strip() or (event.content or "").strip()
    if text.startswith("/"):
        return False, None

    manager.moderation.remember(group_id, event.id, member_id, text)
    if await manager.identity.is_admin(gateway, group_id, member_id):
        if event.is_tome() and text:
            sender_role = await manager.identity.member_role(
                gateway, group_id, member_id
            )
            return await manager.moderation.follow_admin_instruction(
                gateway,
                group_id=group_id,
                member_id=member_id,
                message_id=event.id,
                text=text,
                sender_role=sender_role,
            )
        return False, None

    return await manager.moderation.moderate_message(
        gateway,
        group_id=group_id,
        member_id=member_id,
        message_id=event.id,
        text=text,
        sender_role="member",
        images=await download_images(gateway, event, manager),
    )


@group_msg.handle()
async def handle_group_message(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    handled, reply = await process_group_message(gateway, event, manager)
    if reply:
        await gateway.send(event, reply)
    if handled and manager.moderation.config(event.group_openid).stop_on_violation:
        matcher.stop_propagation()


__all__ = [
    "download_images",
    "group_msg",
    "handle_group_message",
    "process_group_message",
]
