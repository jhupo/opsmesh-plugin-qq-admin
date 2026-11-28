# 安全策略（Security Policy）

## 安全设计基线

- **路径安全继承**：所有 `group_openid` / `member_openid` / `message_id` 参数均经底层 `opsmesh-adapter-qq` 的 `validate_qq_identifier()` 严格校验，阻断路径注入。
- **权限层级辅助**：提供 `ensure_bot_admin()` 与 `ensure_can_manage(operator_role, target_role)`，便于调用方在执行踢人、禁言、拉黑前核验群内角色层级。

## 漏洞上报

请通过 GitHub Security Advisories 私密上报潜在安全问题。
