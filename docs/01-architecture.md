# 01. 架构设计与协作者职责

## 1. 核心数据流（纯群管控制，不抢闲聊）

```mermaid
flowchart TD
    IN["群消息入站 (EventRouter.handle_message)"] --> POL["SafeguardPolicy 节流刷新 Bot/发言者角色"]
    POL --> JEV["JevEvaluator.assess_message() (AsyncTypeSafeClient)<br/>文本+图片违规分类 / 友善玩梗豁免 / 严重度(0~4) / 提示词注入检测"]
    JEV --> TIER{"enforcement_tier"}
    TIER -- "none / 注入拦截" --> PASS["静默返回 False（不干扰正常聊天）"]
    TIER -- "warn / enforce / severe" --> PLN["DecisionPlanner.execute() (temperature=0.0)<br/>调用 9 个官方 QQ v2 @function_tool + 三层 Guardrails<br/>输出结构化 DecisionOutcome"]
    PLN --> CMP["ReplyComposer.compose() (temperature=0.7)<br/>注入实时状态 + 角色人设 + DecisionOutcome<br/>自由生成自然不重复的回复 + reply_guardrail 守门"]
    CMP --> OUT["发送群管反馈并按需 stop_propagation()"]
```

## 2. 核心协作者组件对照

| 组件 | 位置 | 单一职责 |
| :--- | :--- | :--- |
| `PromptCatalog` | `resources/__init__.py` | 读取外置 `prompts.toml` 并渲染兜底模板 |
| `GroupStateStore` | `state.py` | 内存态角色 TTL 缓存、日配额、冷却、警告滑窗、近期上下文与审计日志 |
| `JevEvaluator` | `jev/evaluator.py` | 持有外部注入或自托管的 `AsyncTypeSafeClient`，提供多模态消息/入群评估与 3 项安全复核 |
| `SafeguardPolicy` | `moderation/policy.py` | 三级命令鉴权、权限决策链追踪与角色感知 8 步硬护栏 |
| `GroupModerator` | `moderation/moderator.py` | 官方 QQ v2 唯一写接口执行器与确定性处罚阶梯 |
| `JoinApprover` | `moderation/approver.py` | 入群申请审批与定时轮询 |
| `DecisionPlanner` | `agents/planner.py` | Agent 1：复用共享 `AsyncOpenAI`，精准编排工具调用 |
| `ReplyComposer` | `agents/composer.py` | Agent 2：结合实时状态与角色提示词自由组织自然回复 |
| `CommandRoute` / `@command` | `commands/registry.py` | 声明式正则命令路由，消除 21 个命令的重复鉴权与切词样板 |
| `AdminRuntime` | `runtime.py` | 组合根，统一管理外部客户端与后台协程的 `startup()` / `shutdown()` |
