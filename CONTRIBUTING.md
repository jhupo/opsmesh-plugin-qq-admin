# 贡献指南（Contributing）

## 开发环境准备

要求 **Python >= 3.11**：

```bash
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

## 设计准则

1. **保持无状态高内聚接口类定位**：`QQGroupAdmin` 与 `QQGroupScope` 仅封装官方 QQ 群聊 v2 全部管理能力、参数归一化与自动翻页，不夹带业务存储或第三方 Agent 框架耦合。
2. **代码纯英文**：`.py` 源码中的注释、日志与异常文本统一使用简洁英文。
