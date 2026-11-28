# Configuration

## Flat Base `Config`

The plugin defines a single minimal `Config` ([config.py](../src/qq_admin/config.py)) for TypeSafe Jev, the OpenAI Responses API, and multi-group onboarding:

```toml
jev_api_key = ""
jev_model = "jev-1"
openai_api_key = ""
openai_base_url = ""
model = "gpt-5-mini"
reasoning_effort = "low"
timeout_seconds = 30.0
default_group_enabled = false
config_path = "config.toml"
```

## Diff-Only Multi-Group Online Configuration

Each module under `src/qq_admin/modules/` owns its own defaults (`IdentityConfig`, `SafeguardConfig`, `WarningConfig`, `EscalationConfig`, `AuditConfig`, `ModerationConfig`, `ApprovalConfig`). Per-group changes made online store **only the modified fields** under `[groups."<group_openid>".<module>]`, inheriting all other fields from global defaults:

```text
/admin on
/admin groups
/admin config get safeguard
/admin config set safeguard.max_mute_duration 1800
/admin config set moderation.group_rule_hint Rust and Python discussions only
/admin config reset safeguard.max_mute_duration
```
