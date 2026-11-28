# Changelog

## 0.2.0

- 按领域清晰拆分为 `jev/`、`moderation/`、`agents/`、`handlers/`、`resources/` 五大子包，彻底移除扁平堆砌与脆弱的正则规则快筛（FastGate）。
- 封装可注入的 `JevClient`（`qq_admin.jev.JevClient`），所有评估器与 Guardrail 通过参数显式接收客户端实例，不写死全局单例。
- 引入 **双 OpenAI Agents SDK 架构**：
  - `DecisionAgent`（`agents/decision_agent.py`）：`temperature=0.0`，负责调用 9 个官方 QQ v2 `@function_tool` 并输出结构化 `ExecutionReport`；
  - `ReplyAgent`（`agents/reply_agent.py`）：接收实时状态快照、角色人设提示词与执行事实，自由生成自然、不重复的群管回复（违规处理、权限拒绝、护栏拦截、命令反馈）。
- 全部中文提示词、Jev 评判标准、角色人设与兜底模板外置至 `src/qq_admin/resources/prompts.toml`，全部 `.py` 源码严格保持 0 中文字符。

## 0.1.0

- 初始版本与官方 QQ Bot v2 协议对齐。
