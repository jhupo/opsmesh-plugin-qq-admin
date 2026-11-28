# Commands & Programmatic API

All management commands are directly registered via `opsmesh.on_command(...)` and open exclusively to administrators (configured global admins, group owners, and group admins).

## Slash Commands

### `/admin` Console
- `/admin status [group_id]` — Group status, bot role, and daily counters
- `/admin on [group_id]` / `/admin off [group_id]` — Enable or disable group administration
- `/admin config get <module>[.<field>]` — Inspect module configuration for current group
- `/admin config set <module>.<field> <value>` — Update and persist module configuration online
- `/admin log [n]` — Show recent audit records
- `/admin perm [member]` — Print admin status trace
- `/admin exempt <member>` / `/admin unexempt <member>` — Manage per-group exempt list
- `/admin undo <member>` — Clear warnings and lift mute

### Action Commands
- `/warn <member> [spam|abuse|ad] [reason]`
- `/mute <member> [10m|2h|1d] [reason]` / `/unmute <member>`
- `/kick <member> [reason]`
- `/ban <member> [reason]` / `/unban <member>`
- `/recall [message_id] [reason]`
- `/approve <member> [join_request_id]` / `/reject <member> [reason]`

### Query Commands
- `/shutlist` — Active muted members
- `/blacklist` — Group blacklist
- `/requests` — Pending join requests
- `/member <member>` — Member role and join timestamp
