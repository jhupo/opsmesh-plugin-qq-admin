# Configuration

## Flat Base `Config`

The plugin defines a single minimal `Config` ([config.py](../src/qq_admin/config.py)) and [config.toml](../src/qq_admin/resources/config.toml) for Jev and the OpenAI Responses API:

```toml
jev_api_key = ""
jev_model = "jev-1"
openai_api_key = ""
openai_base_url = ""
model = "gpt-5-mini"
reasoning_effort = "low"
timeout_seconds = 30.0
```

## Module-Owned Online Configuration

Each module under `src/qq_admin/modules/` owns its own defaults (`IdentityConfig`, `SafeguardConfig`, `WarningConfig`, `EscalationConfig`, `AuditConfig`, `ModerationConfig`, `ApprovalConfig`).

Use `/admin` commands (available to group/global admins) to enable groups and customize any module field online:

```text
/admin on
/admin config get safeguard
/admin config set safeguard.max_mute_duration 1800
/admin config set approval.enabled true
/admin config set approval.default_action approve
```
