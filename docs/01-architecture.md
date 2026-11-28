# Architecture

`opsmesh-plugin-qq-admin` is structured into five clean layers with zero circular abstractions:

```text
src/qq_admin/
├── __init__.py          # PluginMetadata(supported_adapters={"qq"}), configure(), auto-bind
├── config.py            # JevConfig, AgentConfig, ConfigStore (module-agnostic TOML store)
├── manager.py           # ServiceManager holding models and feature modules directly
├── prompts/             # Jev text/image safety prompts, guardrails, agent prompts, notices
├── models/              # Jev, DecisionAgent, ReplyAgent, 9 @function_tool, 3 guardrails
├── modules/             # Self-contained modules (identity, safeguard, warning, escalation, audit, moderation, approval)
├── commands/            # Direct OpsMesh slash commands (admin, actions, queries)
└── messages/            # Direct OpsMesh entries (group_message, group_events)
```

## Event Flow

1. **Commands (`priority=1`)**: `/admin`, `/warn`, `/mute`, `/kick`, `/ban`, `/recall`, `/approve`, `/reject`, `/shutlist`, `/blacklist`, `/requests`, `/member` authorize via `IdentityModule` and execute directly.
2. **Group Messages (`priority=5, block=False`)**:
   - Checks `manager.is_group_enabled(group_id)` first; disabled groups return silently.
   - Owner/admin `@Bot` instructions route to `DecisionAgent` → `ReplyAgent`.
   - Member messages run `Jev.execute()` → if safe/banter, return silently; if violating, run `DecisionAgent` (or direct ladder fallback) → `ReplyAgent`.
3. **Group Lifecycle Notices (`priority=5, block=False`)**:
   - `GroupAddRobotEvent` / `GroupDelRobotEvent` refresh or clear group caches and sessions.
   - `GroupJoinRequestEvent`, `GroupMemberAddEvent`, `GroupMemberRemoveEvent` run when the group is enabled.
