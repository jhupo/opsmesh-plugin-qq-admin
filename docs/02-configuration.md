# Configuration

## Minimal Base `config.toml`

The default [config.toml](../src/qq_admin/resources/config.toml) only defines base model settings:

```toml
[jev]
api_key = ""
model = "jev-1"
timeout_seconds = 10.0

[agent]
api_key = ""
decision_model = "gpt-5-mini"
reply_temperature = 0.7
session_mode = "fresh"          # "fresh" or "shared"
session_db_path = ":memory:"
```

## Module-Owned Online Configuration

Each module under `src/qq_admin/modules/` defines its own defaults (`IdentityConfig`, `SafeguardConfig`, `WarningConfig`, `EscalationConfig`, `AuditConfig`, `ModerationConfig`, `ApprovalConfig`).

Use `/admin` commands to enable groups and customize any module field online (validated via Pydantic and persisted to `config.toml`):

```text
/admin on
/admin config get safeguard
/admin config set safeguard.max_mute_duration 1800
/admin config set approval.enabled true
/admin config set approval.default_action approve
/admin session mode shared
/admin session reset
```
