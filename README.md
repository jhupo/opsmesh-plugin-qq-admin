# opsmesh-plugin-qq-admin

基于 [OpsMesh](https://github.com/jhupo/OpsMesh) 与 [opsmesh-adapter-qq](https://github.com/jhupo/opsmesh-adapter-qq) 的**开箱即用 QQ 官方 Bot v2 自动群管控制插件（`type="application"`）**。

插件按领域职责拆分为高内聚协作者组件，采用 **官方 `typesafe-sdk`（`JevEvaluator`） + 双 OpenAI Agents SDK（`DecisionPlanner` + `ReplyComposer`） + 声明式正则命令路由（`@command`）** 设计；专注群管控制，正常聊天 100% 静默放行（`block=False`）。

## 工程目录结构

```text
src/qq_admin/
├── __init__.py               # PluginMetadata、configure()、get_runtime()、底部显式重导出
├── config.py                 # 对称 *Settings 配置模型，支持 config.toml 与 QQ_ADMIN__* 环境变量
├── exception.py              # 语义异常类（QQAdminError / BotNotAdminError / PermissionDeniedError / SafeguardBlockedError）
├── state.py                  # GroupStateStore（角色缓存/每日配额/警告滑窗/近期上下文/审计日志）
├── runtime.py                # AdminRuntime 组合根与外部 SDK 生命周期管理（AsyncTypeSafeClient / AsyncOpenAI）
├── events.py                 # EventRouter（自动消息巡检、管理员 @Bot 指令、入群通知与后台任务）
├── resources/
│   ├── __init__.py           # PromptCatalog 模板加载器
│   ├── config.toml           # 完整默认 TOML 配置模板
│   └── prompts.toml          # 全部中文提示词、Jev 评判标准、角色人设与兜底文案（.py 零中文）
├── jev/
│   ├── schemas.py            # MessageAssessment / JoinRiskAssessment / SafetyVerdict
│   └── evaluator.py          # JevEvaluator（直接持有外部注入或托管的 AsyncTypeSafeClient）
├── moderation/
│   ├── duration.py           # MuteDuration、parse_duration()、format_duration()
│   ├── policy.py             # SafeguardPolicy（角色感知 8 步硬护栏、三级命令授权、权限决策链）
│   ├── moderator.py          # GroupModerator（官方 QQ v2 唯一写操作执行器与阶梯执行）
│   └── approver.py           # JoinApprover（入群申请审批与定时轮询）
├── agents/
│   ├── schemas.py            # TurnContext / ReplySpec / DecisionOutcome
│   ├── guardrails.py         # injection_guardrail / action_guardrail / reply_guardrail
│   ├── tools.py              # 9 个语义化 @function_tool（get_member / mute_member / kick_member 等）
│   ├── planner.py            # DecisionPlanner（Agent 1：低温度精准调用工具并输出 DecisionOutcome）
│   └── composer.py           # ReplyComposer（Agent 2：结合实时状态与角色人设自由组织自然回复）
└── commands/
    ├── registry.py           # @command 声明式正则路由（统一鉴权、参数提取、用法提示与回复合成）
    ├── console.py            # /admin status | on | off | log | perm | exempt | unexempt | undo
    ├── actions.py            # /warn | /mute | /unmute | /kick | /ban | /unban | /recall | /approve | /reject
    └── queries.py            # /shutlist | /blacklist | /requests | /member
```

## 快速开始

方式一：使用 `config.toml`（推荐，模板见 `src/qq_admin/resources/config.toml`）：

```dotenv
QQ_ADMIN_CONFIG="config.toml"
```

方式二：使用 `.env` 嵌套变量（见 [examples/admin_bot/.env.example](examples/admin_bot/.env.example)）：

```python
import opsmesh
import qq

opsmesh.init()
opsmesh.register_adapter(qq.Adapter)
opsmesh.load_plugin("qq_admin")
opsmesh.run()
```

支持外部直接注入 `AsyncTypeSafeClient` 与 `AsyncOpenAI`：

```python
from openai import AsyncOpenAI
from typesafe_sdk import AsyncTypeSafeClient
from qq_admin import AdminConfig, configure

cfg = AdminConfig.from_toml("config.toml")
configure(
    cfg,
    jev_client=AsyncTypeSafeClient(api_key="ts-xxx", model="jev-1"),
    openai_client=AsyncOpenAI(api_key="sk-xxx"),
)
```

## 文档导航

- [01-architecture.md](docs/01-architecture.md) — 协作者组件职责、Jev + 双 Agent 流程与 8 步护栏
- [02-configuration.md](docs/02-configuration.md) — `config.toml` 与 `.env` 全部分区配置详解
- [03-commands-and-api.md](docs/03-commands-and-api.md) — 21 个声明式命令、9 个 Agent 工具与编程接口
