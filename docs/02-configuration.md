# 02. 配置指南

全部配置通过 `QQ_ADMIN__<SECTION>__<FIELD>` 环境变量或 `.env` 自动加载（Pydantic v2 校验）。

| 分区 | 关键配置项 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| 顶层 | `QQ_ADMIN__ENABLED` | `true` | 插件总开关 |
| 顶层 | `QQ_ADMIN__PROMPTS_PATH` | `""` | 外部自定义 `prompts.toml` 路径（默认使用内置 `resources/prompts.toml`） |
| `admin` | `QQ_ADMIN__ADMIN__ADMINS` | `[]` | 全局管理员 `member_openid` 列表 |
| `admin` | `QQ_ADMIN__ADMIN__ALLOW_GROUP_OWNER` | `true` | 允许本群群主执行 `/admin` 命令 |
| `admin` | `QQ_ADMIN__ADMIN__DENY_RESPONSE` | `"silent"` | 无权限响应策略：`silent` / `reply`（开启 LLM 时由 `ReplyAgent` 自然回复） |
| `auto_moderate` | `QQ_ADMIN__AUTO_MODERATE__ENABLED` | `true` | 启用自动群管巡检 |
| `auto_moderate` | `QQ_ADMIN__AUTO_MODERATE__ENABLED_GROUPS` | `[]` | 启用群白名单（留空表示全部群生效） |
| `auto_moderate` | `QQ_ADMIN__AUTO_MODERATE__STOP_ON_VIOLATION` | `true` | 违规处置后阻断下游聊天插件 |
| `auto_moderate` | `QQ_ADMIN__AUTO_MODERATE__ALLOW_ADMIN_NL_CONTROL` | `true` | 允许群主/管理员 `@Bot` 自然语言控群 |
| `jev` | `QQ_ADMIN__JEV__ENABLED` | `true` | 启用 TypeSafe AI Jev System 1 检测 |
| `jev` | `QQ_ADMIN__JEV__API_KEY` | `""` | TypeSafe API Key |
| `jev` | `QQ_ADMIN__JEV__MODEL` | `"jev-1"` | TypeSafe 决策模型名 |
| `jev` | `QQ_ADMIN__JEV__PROXY` | `""` | 可选 HTTP/SOCKS5 代理 |
| `jev` | `QQ_ADMIN__JEV__ENABLE_IMAGE_REVIEW` | `true` | 启用图片附件多模态检测 |
| `jev` | `QQ_ADMIN__JEV__ENABLE_ACTION_GUARDRAIL` | `true` | 启用工具执行前 Jev 证据二审 |
| `llm` | `QQ_ADMIN__LLM__ENABLED` | `false` | 启用双 OpenAI Agents SDK（DecisionAgent + ReplyAgent） |
| `llm` | `QQ_ADMIN__LLM__API_KEY` | `""` | OpenAI 或兼容接口 Key |
| `llm` | `QQ_ADMIN__LLM__BASE_URL` | `""` | 可选兼容端点 Base URL |
| `llm` | `QQ_ADMIN__LLM__DECISION_MODEL` | `"gpt-5-mini"` | Agent 1 裁决执行模型 |
| `llm` | `QQ_ADMIN__LLM__REPLY_MODEL` | `""` | Agent 2 回复生成模型（留空复用 `decision_model`） |
| `llm` | `QQ_ADMIN__LLM__REPLY_TEMPERATURE` | `0.7` | Agent 2 回复自由发挥温度 |
| `llm` | `QQ_ADMIN__LLM__REPLY_PERSONA` | `""` | 覆盖 `prompts.toml` 中 `[reply_agent].persona` 角色人设 |
| `safeguard` | `QQ_ADMIN__SAFEGUARD__MAX_MUTE_DURATION` | `3600` | 单次最大禁言秒数（Bot 管理员角色） |
| `safeguard` | `QQ_ADMIN__SAFEGUARD__MUTE_COOLDOWN` | `300` | 同用户禁言冷却秒数 |
| `safeguard` | `QQ_ADMIN__SAFEGUARD__DAILY_MUTE_LIMIT` | `10` | 每群每日禁言上限 |
| `safeguard` | `QQ_ADMIN__SAFEGUARD__DAILY_KICK_LIMIT` | `3` | 每群每日踢人上限 |
| `auto_approve` | `QQ_ADMIN__AUTO_APPROVE__ENABLED` | `false` | 启用入群申请自动审批 |
| `auto_approve` | `QQ_ADMIN__AUTO_APPROVE__DEFAULT_ACTION` | `"ignore"` | 默认策略：`ignore` / `approve` / `reject` |
| `auto_approve` | `QQ_ADMIN__AUTO_APPROVE__REJECT_ON_RISK_TIPS` | `true` | 命中官方 `risk_tips` 自动拒绝 |
| `auto_approve` | `QQ_ADMIN__AUTO_APPROVE__USE_JEV_REVIEW` | `true` | 启用 Jev 入群风险评估 |
