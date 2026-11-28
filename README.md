# opsmesh-plugin-qq-admin

面向 **[OpsMesh](https://github.com/jhupo/OpsMesh)** 与 **[opsmesh-adapter-qq](https://github.com/jhupo/opsmesh-adapter-qq)** 的腾讯官方 QQ 机器人 v2 群管理接口类插件（顶层导入包名：`qq_admin`）。

本项目保持**零存储、零全局单例、零第三方 Agent 框架耦合**，将官方 QQ 群聊 v2 全部 **6 大域 12 项群管接口** 封装为高内聚、易调用的面向对象接口类 **`QQGroupAdmin`** 与单群绑定视图 **`QQGroupScope`**，并原生提供 OpsMesh `Depends` 依赖注入参数（`GroupAdmin` / `CurrentGroup`）。

---

## 核心特性

- **双粒度面向对象接口类**：
  - **`QQGroupAdmin(gateway)`**：跨群管理客户端，直接传入 `qq.Gateway` 即可管理任意群；
  - **`QQGroupScope`**：通过 `admin.group(group_openid)`、`QQGroupAdmin.from_event(gateway, event)` 或 `CurrentGroup` 注入获取，绑定当前群后所有方法免传 `group_openid`。
- **完整覆盖官方 v2 全部 6 大群管能力**：
  1. **群资料与 Bot 状态**：`get_info`、`get_bot_state`、`is_bot_admin`、`ensure_bot_admin`；
  2. **群成员查询与自动翻页**：`get_member`、`list_members`、`list_members_by_index`、`iter_members`、`get_all_members`；
  3. **禁言管理（支持秒数/`"10m"`/`"2h"`/`"1d"`/`timedelta`/`datetime`）**：`get_mute_setting`、`get_global_mute_rule`、`list_muted_members`、`mute`、`mute_many`、`unmute`、`unmute_many`；
  4. **踢出群成员**：`kick`、`kick_many`（可选同时拉黑）；
  5. **群黑名单管理与自动翻页**：`list_blacklist`、`iter_blacklist`、`get_all_blacklist`、`ban`、`ban_many`、`unban`、`unban_many`；
  6. **入群申请审批与消息撤回**：`list_join_requests`、`iter_join_requests`、`get_all_join_requests`、`approve_join`、`reject_join`、`recall`。
- **原生 OpsMesh 依赖注入**：提供 `GroupAdmin` 与 `CurrentGroup` 注解类型，响应器一行声明即可直接操作当前群。

---

## 快速上手

### 1. 直接实例化 `QQGroupAdmin` 调用

```python
from qq_admin import QQGroupAdmin

admin = QQGroupAdmin(gateway)

await admin.mute("GROUP_OPENID", "MEMBER_OPENID", "10m")
await admin.kick("GROUP_OPENID", "MEMBER_OPENID", add_to_blacklist=False)
members = await admin.get_all_members("GROUP_OPENID")  # 自动游标翻页拉取全量成员
```

### 2. 在 OpsMesh 响应器中通过 `CurrentGroup` 依赖注入

```python
from opsmesh import on_command
from qq import GROUP_ADMIN, GROUP_OWNER
from qq_admin import CurrentGroup

mute_cmd = on_command("mute", permission=GROUP_OWNER | GROUP_ADMIN)

@mute_cmd.handle()
async def _(group: CurrentGroup) -> None:
    await group.mute("MEMBER_OPENID", "10m")
    info = await group.get_info()
    await mute_cmd.finish(f"{info.group_name}: muted.")
```

---

## 目录结构

```text
opsmesh-plugin-qq-admin/
├── docs/
│   ├── 01-architecture.md          # 职责边界、类关系图与官方能力对照
│   └── 02-api-reference.md         # QQGroupAdmin & QQGroupScope 全量方法参考手册
├── examples/admin_bot/main.py      # 最小依赖注入示例
├── src/qq_admin/
│   ├── __init__.py                 # PluginMetadata 与底部显式导出
│   ├── py.typed                    # PEP 561 标记
│   ├── exception.py                # QQAdminError · BotNotAdminError · HierarchyError
│   ├── client.py                   # 核心接口类 QQGroupAdmin & QQGroupScope + 辅助函数
│   └── params.py                   # OpsMesh Depends 注入: GroupAdmin · CurrentGroup
└── tests/unit/                     # 单元测试套件
```

---

## 文档导航

1. **[01-architecture.md](docs/01-architecture.md)** — 适配器与群管插件职责边界、官方 v2 群管能力全集与类结构图。
2. **[02-api-reference.md](docs/02-api-reference.md)** — `QQGroupAdmin`、`QQGroupScope`、依赖注入与辅助函数完整参考手册。

---

## 开源许可

本项目采用 [MIT License](LICENSE) 开源。
