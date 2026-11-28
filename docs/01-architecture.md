# 01. 架构设计与官方 QQ 群管 v2 能力边界

本文档定义 `opsmesh-plugin-qq-admin` 与 `opsmesh-adapter-qq` 的分工边界及类关系设计。

---

## 1. 双仓分层职责边界

```mermaid
flowchart LR
    BIZ["业务插件 / AI Agent (@function_tool)"] --> CLS["qq_admin (QQGroupAdmin / QQGroupScope / CurrentGroup)"]
    CLS --> GW["qq.Gateway (opsmesh-adapter-qq: 1:1 原始协议接口)"]
    GW --> TX["腾讯 QQ 开放平台 OpenAPI v2"]
```

| 仓库 | 定位 | 负责内容 |
| :--- | :--- | :--- |
| **`opsmesh-adapter-qq`** | 底层协议层 | 连接保活、鉴权 Token、OpenID 校验、1:1 官方 HTTP 接口映射 |
| **`opsmesh-plugin-qq-admin`** | 群管理接口类层 | 无状态 `QQGroupAdmin` 与单群视图 `QQGroupScope`、单人/批量语义封装、时长字符串归一化、自动 `next_cursor` 游标翻页、角色层级校验与 OpsMesh `Depends` 注入 |

---

## 2. 核心类关系图

```mermaid
classDiagram
    class QQGroupAdmin {
        +Gateway gateway
        +group(group_openid) QQGroupScope
        +from_event(gateway, event)$ QQGroupScope
        +get_info(group_openid)
        +get_bot_state(group_openid)
        +is_bot_admin(group_openid)
        +ensure_bot_admin(group_openid)
        +get_member(group_openid, member_openid)
        +list_members(group_openid, cursor, limit)
        +list_members_by_index(group_openid, start_index, limit)
        +iter_members(group_openid, limit)
        +get_all_members(group_openid, limit)
        +get_mute_setting(group_openid)
        +get_global_mute_rule(group_openid)
        +list_muted_members(group_openid)
        +mute(group_openid, member_openid, duration, op)
        +mute_many(group_openid, member_openids, duration, op)
        +unmute(group_openid, member_openid)
        +unmute_many(group_openid, member_openids)
        +kick(group_openid, member_openid, add_to_blacklist)
        +kick_many(group_openid, member_openids, add_to_blacklist)
        +list_blacklist(group_openid, cursor, limit)
        +iter_blacklist(group_openid, limit)
        +get_all_blacklist(group_openid, limit)
        +ban(group_openid, member_openid)
        +ban_many(group_openid, member_openids)
        +unban(group_openid, member_openid)
        +unban_many(group_openid, member_openids)
        +list_join_requests(group_openid, cursor, limit)
        +iter_join_requests(group_openid, limit)
        +get_all_join_requests(group_openid, limit)
        +approve_join(group_openid, member_openid, join_request_id)
        +reject_join(group_openid, member_openid, join_request_id, reason, add_to_blacklist)
        +recall(group_openid, message_id)
    }

    class QQGroupScope {
        +QQGroupAdmin admin
        +str group_openid
        +同名全部单群方法(免传 group_openid)
    }

    QQGroupAdmin "1" --> "*" QQGroupScope : group(group_openid)
```
