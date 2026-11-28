# Changelog

## 0.2.0

- 按《代码整洁之道》全面重构组件命名与职责边界：
  - 协作者类职责单一、参数精简：`PromptCatalog`、`GroupStateStore`、`JevEvaluator`、`SafeguardPolicy`、`GroupModerator`、`JoinApprover`、`DecisionPlanner`、`ReplyComposer`、`EventRouter`、`AdminRuntime`。
  - 移除 Agent 工具函数的冗余 `tool_` 前缀与 `name_override`，直接以领域动词命名（`get_member`、`list_muted_members`、`warn_member`、`mute_member`、`unmute_member`、`kick_member`、`ban_member`、`unban_member`、`recall_message`）。
  - 重构 `commands/` 为声明式 `@command(name, prefix=..., pattern=..., role=..., usage=...)` 正则路由，拆分为 `console.py`、`actions.py`、`queries.py` 21 个短小顶层函数，消除嵌套闭包与重复鉴权/切词样板。
  - 重构 `config.py` 为对称 `*Settings` 模型（`SecretStr` 保护密钥），内置完整 `resources/config.toml` 默认模板并支持 `AdminConfig.from_toml()` 与 `QQ_ADMIN_CONFIG` 加载。
  - `AdminRuntime` 统一托管并复用 `AsyncTypeSafeClient` 与 `AsyncOpenAI` 连接池生命周期。
- 全部中文提示词、Jev 评判标准、角色人设与兜底文案独立存放在 `src/qq_admin/resources/prompts.toml`，全仓 `.py` 保持 0 中文字符。

## 0.1.0

- 初始版本与官方 QQ Bot v2 协议对齐。
