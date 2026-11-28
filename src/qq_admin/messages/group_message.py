"""Direct OpsMesh group message entry: admins -> @Bot control, users -> moderation."""

import re

from opsmesh import on_message
from opsmesh.log import logger
from opsmesh.matcher import Matcher
from qq import Gateway, GroupMessageEvent

from qq_admin.manager import MANAGER
from qq_admin.modules import IDENTITY, MODERATION

group_msg = on_message(priority=5, block=False)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


async def download_images(gateway: Gateway, event: GroupMessageEvent) -> list[bytes]:
    cfg = MODERATION.config(event.group_openid)
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
    gateway: Gateway, event: GroupMessageEvent
) -> tuple[bool, str | None]:
    """Return (handled, reply). Admins are never moderated; safe chat is silent."""
    group_id = event.group_openid
    member_id = event.get_user_id()
    if not group_id or not MANAGER.is_group_enabled(group_id):
        return False, None
    text = event.get_plaintext().strip() or (event.content or "").strip()
    if text.startswith("/"):
        return False, None

    if await IDENTITY.is_admin(gateway, group_id, member_id):
        if event.is_tome() and text:
            sender_role = await IDENTITY.member_role(gateway, group_id, member_id)
            return await MODERATION.follow_admin_instruction(
                gateway,
                group_id=group_id,
                member_id=member_id,
                message_id=event.id,
                text=text,
                sender_role=sender_role,
            )
        return False, None

    urls = _URL_RE.findall(text)
    return await MODERATION.moderate_message(
        gateway,
        group_id=group_id,
        member_id=member_id,
        message_id=event.id,
        text=text,
        sender_role="member",
        images=await download_images(gateway, event),
        urls=urls or None,
    )


@group_msg.handle()
async def handle_group_message(
    gateway: Gateway, event: GroupMessageEvent, matcher: Matcher
) -> None:
    handled, reply = await process_group_message(gateway, event)
    if reply:
        await gateway.send(event, reply)
    if handled and MODERATION.config(event.group_openid).stop_on_violation:
        matcher.stop_propagation()


__all__ = [
    "download_images",
    "group_msg",
    "handle_group_message",
    "process_group_message",
]
