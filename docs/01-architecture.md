# Architecture

`opsmesh-plugin-qq-admin` separates deterministic group governance from downstream conversational agents:

```text
src/qq_admin/
├── __init__.py          # PluginMetadata(supported_adapters={"qq"}) and public exports
├── config.py            # Flat startup Config (Jev, OpenAI Responses API, default_group_enabled)
├── store.py             # Thread-safe CONFIG_STORE with diff-only per-group TOML overrides
├── manager.py           # Global MANAGER holding shared Jev & ReplyAgent clients
├── prompts/             # reply_agent.md, jev.toml, notices.toml
├── models/              # Stateless Jev, ReplyAgent, and pure-code reply_guardrail
├── modules/             # Global singletons: IDENTITY, SAFEGUARD, WARNING, ESCALATION, AUDIT, MODERATION, APPROVAL
├── commands/            # Direct OpsMesh slash commands (admin, actions, queries)
└── messages/            # Group message firewall & lifecycle notice handlers
```

## Event Flow

1. **Slash Commands (`priority=1, block=True`)**:
   - `/admin <status|groups|on|off|config|log|perm|exempt|unexempt|undo>` returns deterministic ops text and validates `IDENTITY.is_admin` against the **target** `group_id`.
   - `/warn`, `/mute`, `/unmute`, `/kick`, `/ban`, `/unban`, `/recall`, `/approve`, `/reject` execute Official QQ v2 actions and compose replies via `ReplyAgent`.
2. **Group Messages (`priority=5, block=False`)**:
   - Disabled groups, whitelisted users, and group/global admins pass silently (`False, None`) to downstream conversational/Agent plugins.
   - Regular member messages run deterministic flood/repeat checks -> stateless `Jev.execute()` -> deterministic punishment (`warn` auto-mute upgrade + `ESCALATION` kick upgrade + `SAFEGUARD` 8-step checks) -> `ReplyAgent` persona reply -> `stop_propagation()`.
   - Prompt-injection / jailbreak hits are audited and stopped upstream without sending noise.
3. **Group Lifecycle Notices (`priority=5, block=False`)**:
   - `GroupAddRobotEvent` / `GroupDelRobotEvent` refresh or clear all per-group module caches.
   - `GroupJoinRequestEvent`, `GroupMemberAddEvent`, `GroupMemberRemoveEvent` run when the group is enabled.
