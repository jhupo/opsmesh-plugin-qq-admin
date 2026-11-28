# 02. 对外异步函数 API 完整参考手册（19 项全量接口）

本插件不内置任何第三方 Agent/Tool 框架包装，直接通过顶层包 `qq_admin`（采用 OpsMesh 风格的 `from ... import X as X` 显式导出）暴露 **19 个强类型异步函数 API**。上游业务代码、OpenAI Agents SDK `@function_tool`、MCP Server 或 HTTP 服务均可直接导入调用。

```python
from qq_admin import (
    AdminContext,
    OperatorIdentity,
    RoleTier,
    mute_member,
    kick_member,
    # ... 任意 19 个接口均可直接从 qq_admin 顶层导入
)
```

---

## 1. 通用上下文、返回模型与异常码

### 1.1 入参上下文 `AdminContext`

| 字段 | 类型 | 必填 | 说明 |
| :--- | :--- | :---: | :--- |
| `gateway` | `qq.Gateway` | 是 | `opsmesh-adapter-qq` 网关实例 |
| `group_openid` | `str` | 是 | 目标 QQ 群 `group_openid` |
| `operator` | `OperatorIdentity` | 是 | 操作者身份（`openid`、`role: RoleTier`、`is_superuser: bool`） |
| `source` | `AuditSource` | 否 | 调用来源（默认 `AuditSource.API`，可选 `COMMAND` / `AUTO`） |
| `trace_id` | `str` | 否 | 审计追踪 ID（默认自动生成 12 位 hex） |

### 1.2 统一返回模型 `ModerationOutcome`

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `action` | `str` | 动作标识名（如 `"mute_member"`） |
| `group_openid` | `str` | 目标群 OpenID |
| `summary` | `str` | 简洁可读的英文执行摘要 |
| `data` | `dict[str, Any]` | 结构化结果载荷（见下方各接口说明） |

### 1.3 结构化异常族（均继承 `QQAdminError`）

| 异常类 | `exc.code` | 触发条件 |
| :--- | :--- | :--- |
| `GroupAdminDisabledError` | `GROUP_ADMIN_DISABLED` | 目标群已关闭群管功能 |
| `PermissionDeniedError` | `PERMISSION_DENIED` | 操作者角色低于最低要求（如普通群员调写接口） |
| `BotRoleInsufficientError` | `BOT_ROLE_INSUFFICIENT` | 机器人在本群仅为 `member`，未被设为管理员 |
| `TargetProtectedError` | `TARGET_PROTECTED` | 目标为机器人自身、操作者自身、受保护白名单成员、群主或同级/上级管理员 |
| `CooldownActiveError` | `COOLDOWN_ACTIVE` | 同一目标处于防抖冷却期内 |
| `QuotaExceededError` | `QUOTA_EXCEEDED` | 本群当日对应高危操作配额已耗尽（`SUPERUSER` 豁免） |

---

## 2. 群管控与状态查询接口（4 项）

### 2.1 `set_group_enabled`
- **签名**：`async def set_group_enabled(ctx: AdminContext, *, enabled: bool, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `OWNER` 或 `SUPERUSER`；写入成功审计。
- **返回 `data`**：`{"enabled": bool}`
- **示例**：`await set_group_enabled(ctx, enabled=True)`

### 2.2 `get_group_info`
- **签名**：`async def get_group_info(ctx: AdminContext, *, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `ADMIN+`；底层调用 `GET /v2/groups/{group_openid}`。
- **返回 `data`**：`GroupInfoReturn` 字典（`group_openid`, `group_name`, `member_count`, `max_member_count`, `description`, `tags`）。

### 2.3 `get_bot_state`
- **签名**：`async def get_bot_state(ctx: AdminContext, *, force_refresh: bool = False, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `ADMIN+`；调用 `GET /v2/groups/{group_openid}/bot` 并自动刷新本群 Bot 角色缓存。
- **返回 `data`**：`GroupBotStateReturn` 字典（`member_role`, `allow_proactive_msg`, `recv_msg_setting`）。

### 2.4 `get_audit_log`
- **签名**：`async def get_audit_log(ctx: AdminContext, *, limit: int = 20, source: AuditSource | None = None, action: str | None = None, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `ADMIN+`；纯本地状态查询，无外部 HTTP 调用。
- **返回 `data`**：`{"records": list[AuditRecordDict]}`（按时间倒序）。

---

## 3. 成员信息查询接口（2 项）

### 3.1 `get_member`
- **签名**：`async def get_member(ctx: AdminContext, *, member_openid: str, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `ADMIN+`；底层调用 `GET /v2/groups/{group_openid}/members/{member_openid}`。
- **返回 `data`**：`GroupMemberInfo` 字典（`member_openid`, `username`, `member_role`, `joined_at`, `bot`）。

### 3.2 `list_members`
- **签名**：`async def list_members(ctx: AdminContext, *, cursor: str | None = None, limit: int | None = 50, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `ADMIN+`；底层调用 `GET /v2/groups/{group_openid}/members`。
- **返回 `data`**：`GroupMembersReturn` 字典（`members`, `next_cursor`, `is_end`）。

---

## 4. 违规警告与阶梯升级接口（2 项）

### 4.1 `warn_member`
- **签名**：`async def warn_member(ctx: AdminContext, *, member_openid: str, violation_type: ViolationType = ViolationType.OTHER, reason: str = "", services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：需群管开启、操作者 `ADMIN+`、目标非受保护/群主/同级管理员；窗口内累计次数达到 `mute_threshold` 自动联动 `mute_member`，达到 `kick_threshold` 自动联动 `kick_member`。
- **返回 `data`**：`{"member_openid": str, "active_count": int, "escalation": "warn_only" | "auto_mute" | "auto_kick"}`。

### 4.2 `clear_warnings`
- **签名**：`async def clear_warnings(ctx: AdminContext, *, member_openid: str, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `ADMIN+`；清空指定成员在滑动窗口内的历史违规记录并写入审计。
- **返回 `data`**：`{"member_openid": str, "cleared": int}`。

---

## 5. 禁言、踢人与撤回接口（5 项）

### 5.1 `get_mute_setting`
- **签名**：`async def get_mute_setting(ctx: AdminContext, *, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者需 `ADMIN+`；底层调用 `GET /v2/groups/{group_openid}/restrict_chat_setting`。
- **返回 `data`**：`GroupRestrictChatSettingReturn` 字典（`all_muted`, `muted_members`）。

### 5.2 `mute_member`
- **签名**：`async def mute_member(ctx: AdminContext, *, member_openid: str, duration_seconds: int = 600, reason: str = "", services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：六阶全护栏（群管开启 + 操作者 `ADMIN+` + Bot `admin/owner` + 目标层级/白名单 + 目标冷却 + 每日禁言配额 + 时长截断 `[min_mute_seconds, max_mute_seconds]`）；底层调用 `POST /v2/groups/{group_openid}/restrict_chat_setting`（`op="add"`）。
- **返回 `data`**：`{"member_openid": str, "duration_seconds": int, "remaining_quota": int | None}`。

### 5.3 `unmute_member`
- **签名**：`async def unmute_member(ctx: AdminContext, *, member_openid: str, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：需群管开启、操作者 `ADMIN+`、Bot `admin/owner`；底层调用 `set_group_members_mute(op="del")`。
- **返回 `data`**：`{"member_openid": str}`。

### 5.4 `kick_member`
- **签名**：`async def kick_member(ctx: AdminContext, *, member_openid: str, add_to_blacklist: bool = False, reason: str = "", services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：六阶全护栏（含踢前查成员角色 + 每日踢人配额）；默认 `add_to_blacklist=False`；底层调用 `POST /v2/groups/{group_openid}/batch_remove_members`。
- **返回 `data`**：`BatchRemoveMembersReturn` 字段 + `"remaining_quota"`。

### 5.5 `recall_message`
- **签名**：`async def recall_message(ctx: AdminContext, *, message_id: str, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：需群管开启、操作者 `ADMIN+`、Bot `admin/owner`；底层调用 `DELETE /v2/groups/{group_openid}/messages/{message_id}`（官方 2 分钟内有效）。
- **返回 `data`**：`{"message_id": str}`。

---

## 6. 群黑名单管理接口（3 项）

### 6.1 `list_blacklist`
- **签名**：`async def list_blacklist(ctx: AdminContext, *, cursor: str | None = None, limit: int | None = 50, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者 `ADMIN+` + Bot `admin/owner`；底层调用 `GET /v2/groups/{group_openid}/member_blacklist`。
- **返回 `data`**：`GroupMemberBlacklistReturn` 字典（`members`, `next_cursor`, `is_end`）。

### 6.2 `add_blacklist`
- **签名**：`async def add_blacklist(ctx: AdminContext, *, member_openids: list[str], services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：群管开启 + 操作者 `ADMIN+` + Bot `admin/owner` + 逐个检查受保护白名单 + 每日黑名单配额；底层调用 `POST /v2/groups/{group_openid}/member_blacklist`（`op="add"`）。
- **返回 `data`**：`MemberBlacklistOpReturn` 字典（`success_member_openids`, `failed_member_openids`）。

### 6.3 `remove_blacklist`
- **签名**：`async def remove_blacklist(ctx: AdminContext, *, member_openids: list[str], services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：群管开启 + 操作者 `ADMIN+` + Bot `admin/owner`；底层调用 `post_group_member_blacklist(op="del")`。
- **返回 `data`**：`MemberBlacklistOpReturn` 字典。

---

## 7. 入群申请管理接口（3 项）

### 7.1 `list_join_requests`
- **签名**：`async def list_join_requests(ctx: AdminContext, *, cursor: str | None = None, limit: int | None = 50, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：操作者 `ADMIN+` + Bot `admin/owner`；底层调用 `GET /v2/groups/{group_openid}/join_request_list`。
- **返回 `data`**：`JoinRequestListReturn` 字典（`join_requests`, `next_cursor`, `is_end`）。

### 7.2 `approve_join_request`
- **签名**：`async def approve_join_request(ctx: AdminContext, *, member_openid: str, join_request_id: str | None = None, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：群管开启 + 操作者 `ADMIN+` + Bot `admin/owner` + 冷却与每日审批配额；底层调用 `POST /v2/groups/{group_openid}/approval_join_request/{member_openid}`（`op="approve"`）。
- **返回 `data`**：`{"member_openid": str, "op": "approve", "join_request_id": str | None}`。

### 7.3 `decline_join_request`
- **签名**：`async def decline_join_request(ctx: AdminContext, *, member_openid: str, join_request_id: str | None = None, reject_reason: str | None = None, add_to_blacklist: bool = False, services: AdminServices | None = None) -> ModerationOutcome`
- **权限与护栏**：群管开启 + 操作者 `ADMIN+` + Bot `admin/owner` + 冷却与每日审批配额；底层调用 `approval_join_request(op="decline", ...)`。
- **返回 `data`**：`{"member_openid": str, "op": "decline", "join_request_id": str | None}`。

---

## 8. 上游依赖方封装 OpenAI Agents SDK `@function_tool` 示例

```python
from agents import RunContextWrapper, function_tool
from qq_admin import AdminContext, QQAdminError, mute_member


@function_tool
async def qq_group_mute_member(
    run_ctx: RunContextWrapper[AdminContext],
    member_openid: str,
    duration_seconds: int = 600,
    reason: str = "",
) -> str:
    """Mute a QQ group member for the specified duration."""
    try:
        res = await mute_member(
            run_ctx.context,
            member_openid=member_openid,
            duration_seconds=duration_seconds,
            reason=reason,
        )
        return res.summary
    except QQAdminError as exc:
        return f"[{exc.code}] {exc.message}"
```
