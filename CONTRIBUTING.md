# 贡献指南（Contributing）

## 开发环境准备

要求 **Python >= 3.11**：

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -e "../OpsMesh[fastapi,httpx,websockets]" -e "../opsmesh-adapter-qq" -e ".[dev]"
```

## 提交前验证

```bash
ruff check src tests examples
ruff format --check src tests examples
bandit -r src/qq_admin -ll -ii
pytest -v
```

## 架构红线

1. **纯对外独立异步函数 API（零自定义 Tool 框架耦合）**：`src/qq_admin/api/` 下每个对外能力必须是独立文件中的顶层 `async def` 函数，不内置 `ToolDefinition` / `BaseAdminTool` / `register_tool` 或 `build_*` 闭包工厂，由上游依赖方按需自行封装给 OpenAI Agents SDK 等框架。
2. **命令与对外 API 共享单一领域服务层**：斜杠命令响应器（`matchers/`）与对外异步函数（`api/`）统一委托 `services/` 执行权限判定、安全护栏、配额扣减、阶梯升级与审计落盘，禁止复制业务逻辑或绕过护栏裸调适配器 API。
3. **严格对齐官方 v2 协议边界**：所有标识统一使用官方 `group_openid` / `member_openid`，仅封装官方 v2 真实支持的 12 项群管原子能力，不混入非官方协议私有概念。
