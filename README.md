# opsmesh-plugin-qq-admin

基于 [OpsMesh](https://github.com/jhupo/OpsMesh) 与 [opsmesh-adapter-qq](https://github.com/jhupo/opsmesh-adapter-qq) 的**开箱即用 QQ 官方 Bot v2 自动群管控制插件（`type="application"`）**。

插件采用 **TypeSafe AI Jev（System 1 校准检测） + 双 OpenAI Agents SDK（System 2 裁决执行 Agent + 角色化回复 Agent）** 架构，**不依赖脆弱的正则/规则快筛，绝不参与日常闲聊**：正常群聊消息经 Jev 判定安全后静默放行（`block=False`）；仅在违规处置、护栏拦截、权限拒绝或管理员指令执行时，由专职 `ReplyAgent` 结合当前真实状态与角色提示词自由组织自然、不重复的回复。

## 模块分层

```text
src/qq_admin/
├── __init__.py               # 插件元数据、自动加载注册、底部显式重导出
├── config.py                 # Pydantic v2 分区配置与外部 TOML 提示词加载
├── exception.py              # 4 个语义异常类
├── state.py                  # 内存态运行时状态（角色缓存/计数/审计日志/近期消息）与 PluginRuntime
├── resources/
│   └── prompts.toml          # 全部中文提示词、Jev 评判标准、角色人设与兜底文案（.py 零中文）
├── jev/                      # System 1：可注入的 JevClient 与校准评估器
│   ├── client.py             # JevClient 封装（支持外部传入/注入，不写死全局单例）
│   ├── evaluators.py         # evaluate_message / evaluate_join_request / check_* 三项 Guardrail
│   └── schemas.py            # MessageEvaluation / JoinRiskEvaluation / GuardVerdict
├── moderation/               # 硬护栏与官方 QQ v2 直接执行层
│   ├── guard.py              # 角色感知 8 步硬护栏、权限决策链、处罚阶梯
│   └── actions.py            # 官方 QQ v2 唯一直接执行函数 + Jev 入群自动审批
├── agents/                   # System 2：双 OpenAI Agents SDK 架构
│   ├── context.py            # ModerationContext / ExecutionReport / ReplyContext
│   ├── guardrails.py         # 三层 SDK Guardrails（均显式调用传入的 JevClient）
│   ├── tools.py              # 9 个官方 QQ v2 原子 @function_tool
│   ├── decision_agent.py     # Agent 1：专注裁决与调用工具，输出结构化 ExecutionReport
│   └── reply_agent.py        # Agent 2：专注根据实时状态与角色提示词自由生成自然回复
└── handlers/                 # OpsMesh 接入层
    ├── events.py             # on_message / on_notice 自动事件流与后台任务
    └── commands.py           # 21 个分级管理命令控制台
```

## 快速开始

```python
import opsmesh
import qq

opsmesh.init()
opsmesh.register_adapter(qq.Adapter)
opsmesh.load_plugin("qq_admin")
opsmesh.run()
```

支持注入自定义 `JevClient`（例如共享宿主代理或测试 Mock 客户端）：

```python
from qq_admin import JevClient, JevConfig, QQAdminConfig, configure

jev = JevClient(JevConfig(enabled=True, api_key="ts-your-key", model="jev-1"))
configure(QQAdminConfig(), jev_client=jev)
```

## 文档导航

- [01-architecture.md](docs/01-architecture.md) — Jev + 双 Agent 架构设计与角色护栏说明
- [02-configuration.md](docs/02-configuration.md) — 全部分区配置项与外部 `prompts.toml` 定制
- [03-commands-and-api.md](docs/03-commands-and-api.md) — 21 个内置命令、9 个 Agent 工具与直接调用接口
