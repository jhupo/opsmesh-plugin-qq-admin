# Configuration

## Minimal Base `config.toml`

The default [config.toml](../src/qq_admin/resources/config.toml) defines one shared `[openai]` Responses API endpoint (`OpenAIConfig`) plus per-agent model configs (`DecisionAgentConfig` and `ReplyAgentConfig`, both inheriting `BaseAgentConfig`):

```toml
[jev]
api_key = ""
model = "jev-1"
timeout_seconds = 10.0

[openai]
api_key = ""
base_url = ""
timeout_seconds = 30.0

[decision_agent]
model = "gpt-5-mini"
reasoning_effort = "low"
temperature = 0.0
max_turns = 6

[reply_agent]
model = "gpt-5-mini"
reasoning_effort = "low"
temperature = 0.7
max_turns = 2
persona = ""
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
