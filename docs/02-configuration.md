# 02. 配置指南（`config.toml` 与环境变量）

插件同时支持 **TOML 配置文件**（推荐，完整模板见 [src/qq_admin/resources/config.toml](../src/qq_admin/resources/config.toml)）与 **OpsMesh `.env` 嵌套环境变量**。

## 1. TOML 配置加载

在 `.env` 中指定路径：

```dotenv
QQ_ADMIN_CONFIG="config.toml"
```

或在代码中直接加载：

```python
from qq_admin import AdminConfig, configure

configure(AdminConfig.from_toml("config.toml"))
```

## 2. 11 个对称配置分区（`AdminConfig`）

| 分区字段 | 模型类 | 核心配置项 |
| :--- | :--- | :--- |
| `[plugin]` | `PluginSettings` | `enabled`、`prompts_path` |
| `[admin]` | `AdminSettings` | `admins`、`allow_group_owner`、`owner_allowed_commands`、`deny_response` |
| `[identity]` | `IdentitySettings` | `role_cache_ttl_seconds`、`bot_role_refresh_seconds`、`sender_role_refresh_seconds` |
| `[moderation]` | `ModerationSettings` | `enabled`、`enabled_groups`、`stop_on_violation`、`allow_admin_nl_control`、`recent_context_size` |
| `[jev]` | `JevSettings` | `enabled`、`api_key`（`SecretStr`）、`model`、`proxy`、`warn_confidence`、`enforce_confidence`、`enable_image_review`、`enable_action_guardrail` |
| `[agent]` | `AgentSettings` | `enabled`、`api_key`（`SecretStr`）、`base_url`、`decision_model`、`reply_model`、`reply_temperature`、`reply_persona`、`use_chat_completions` |
| `[safeguard]` | `SafeguardSettings` | `max_mute_duration`、`mute_cooldown`、`daily_mute_limit`、`daily_kick_limit`、`protected_users`、`exempt_users`、`auto_exempt_admins`、`kick_require_confirm` |
| `[warning]` | `WarningSettings` | `enabled`、`spam_threshold/window_seconds`、`abuse_threshold/window_seconds`、`ad_threshold/window_seconds` |
| `[escalation]` | `EscalationSettings` | `enabled`、`steps`（`within_hours` / `count` / `action` / `mute_seconds` / `blacklist`） |
| `[approval]` | `ApprovalSettings` | `enabled`、`default_action`、`reject_on_risk_tips`、`use_jev_review`、`max_pending_seconds`、`check_interval_seconds`、`groups` |
| `[logging]` | `LoggingSettings` | `max_log_entries`、`default_log_lines` |
