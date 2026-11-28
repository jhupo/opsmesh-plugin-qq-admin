# Commands & Programmatic API

## Slash Commands

### `/admin` Console (Global Admin / Group Owner)
- `/admin status [group_id]` — Group status, bot role, session mode, and daily counters
- `/admin on [group_id]` / `/admin off [group_id]` — Enable or disable group administration
- `/admin config get <module>[.<field>]` — Inspect module configuration for current group
- `/admin config set <module>.<field> <value>` — Update and persist module configuration online
- `/admin session [mode fresh|shared | reset]` — Switch or reset Agent session history
- `/admin log [n]` — Show recent audit records
- `/admin perm [member]` — Print authorization decision trace
- `/admin exempt <member>` / `/admin unexempt <member>` — Manage per-group exempt list
- `/admin undo <member>` — Clear warnings and lift mute

### Action Commands (Group Admin / Owner / Global Admin)
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

## Programmatic Usage

```python
from typesafe_sdk import AsyncTypeSafeClient
from openai import AsyncOpenAI
import qq_admin

manager = qq_admin.configure(
    jev_client=AsyncTypeSafeClient(api_key="ts-..."),
    openai_client=AsyncOpenAI(api_key="sk-..."),
)
```
