# Configuration

## Minimal Base `config.toml`

The default [config.toml](../src/qq_admin/resources/config.toml) defines `[jev]`, `[decision_agent]`, and `[reply_agent]` (`DecisionAgentConfig` and `ReplyAgentConfig` both inherit from `BaseAgentConfig`):

```toml
[jev]
api_key = ""
model = "jev-1"
timeout_seconds = 10.0

[decision_agent]
api_key = ""
model = "gpt-5-mini"
reasoning_effort = "low"
temperature = 0.0
max_turns = 6

[reply_agent]
api_key = ""
model = "gpt-5-mini"
reasoning_effort = "low"
temperature = 0.7
persona = ""
max_turns = 2
```

## Module-Owned Online Configuration

Each module under `src/qq_admin/modules/` defines its own defaults (`IdentityConfig`, `SafeguardConfig`, `WarningConfig`, `EscalationConfig`, `AuditConfig`, `ModerationConfig`, `ApprovalConfig`).

Use `/admin` commands (available to group/global admins) to enable groups and customize any module field online:

```text
/admin on
/admin config get safeguard
/admin config set safeguard.max_mute_duration 1800
/admin config set approval.enabled true
/admin config set approval.default_action approve
```
