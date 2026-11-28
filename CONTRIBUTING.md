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

1. **纯对外异步函数 API（零多余转发层与 Tool 框架耦合）**：所有 19 个对外群管函数直接定义在 `services/moderation.py` 并通过 `qq_admin/__init__.py` 采用 `from ... import X as X` 显式导出，不内置 `ToolDefinition` / `BaseAdminTool` / `register_tool` 或 `build_*` 闭包工厂。
2. **命令与对外函数共享单一领域服务层**：斜杠命令响应器（`matchers/`）与对外异步函数统一委托 `services/` 执行权限判定、安全护栏、配额扣减、阶梯升级与审计落盘。
3. **严格对齐官方 v2 协议边界**：所有标识统一使用官方 `group_openid` / `member_openid`，仅封装官方 v2 真实支持的 12 项群管原子能力，不混入非官方协议私有概念。
