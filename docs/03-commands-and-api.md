# Commands & Programmatic API

All management commands are directly registered via `opsmesh.on_command(...)` and enforce target-group admin authorization (`IDENTITY.is_admin(gateway, target_group_id, operator_id)`).

## Slash Commands

### `/admin` Console (Deterministic Text Output)
- `/admin status [group_id]` — Target group status, bot role, and daily counters
- `/admin groups` — Multi-group overview of managed groups visible to the operator
- `/admin on [group_id]` / `/admin off [group_id]` — Enable or disable target group administration
- `/admin config get <module>[.<field>]` — Inspect effective module configuration for current group
- `/admin config set <module>.<field> <value>` — Persist diff-only per-group override online
- `/admin config reset <module>[.<field>]` — Reset field or module override back to global defaults
- `/admin log [n]` — Show recent per-group audit records
- `/admin perm [member]` — Print target-group admin status trace
- `/admin exempt <member>` / `/admin unexempt <member>` — Manage per-group exempt list
- `/admin undo <member>` — Clear member warnings/flood state and lift mute

### Action & Query Commands
- `/warn <member> [spam|abuse|ad] [reason]`
- `/mute <member> [10m|2h|1d] [reason]` / `/unmute <member>`
- `/kick <member> [reason]`
- `/ban <member> [reason]` / `/unban <member>`
- `/recall [message_id] [reason]`
- `/approve <member> [join_request_id]` / `/reject <member> [reason]`
- `/shutlist` | `/blacklist` | `/requests` | `/member <member>`

## Programmatic API for Downstream Plugins

Downstream context-aware chat or Agent plugins can import the global module singletons directly (`from qq_admin import MODERATION, APPROVAL, IDENTITY, GROUP_ADMIN, SAFEGUARD, AUDIT` or via `opsmesh.require("qq_admin")`):

```python
from qq_admin import GROUP_ADMIN, IDENTITY, MODERATION

# Every write action enforces target-group admin authorization when operator_id != "bot"
outcome = await MODERATION.mute(
    gateway,
    group_id,
    target_member_id,
    duration="10m",
    reason="spam in chat context",
    operator_id=event.get_user_id(),
)
```
