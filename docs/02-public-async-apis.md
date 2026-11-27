# 02. 对外独立异步函数 API 清单（`src/qq_admin/api/`）

本插件不内置任何第三方 Agent/Tool 封装框架（无 `ToolDefinition` / `ToolResult` / `BaseAdminTool` / `register_tool` / `build_*` 闭包），仅通过 `src/qq_admin/api/` 暴露 **18 个纯独立、强类型的异步函数 API**（1 函数 = 1 独立文件），由上游依赖项目按需自由封装为 OpenAI Agents SDK `@function_tool`、MCP Tool 或 HTTP 接口。

---

## 1. 全量 18 个独立函数 API 清单

所有函数均支持直接 `from qq_admin import <fn>` 或 `from qq_admin.api import <fn>` 导入，统一接收 `ctx: AdminContext` 与可选 `services: AdminServices | None = None`，返回 `ModerationOutcome`（遇到权限/护栏拦截时抛出结构化 `QQAdminError` 子类）：

| 独立模块 (`src/qq_admin/api/`) | 函数签名核心入参 | 需 Bot 管理员 | 底层调用的 `qq.Gateway` / 服务 |
| :--- | :--- | :---: | :--- |
| `warn_member.py` | `warn_member(ctx, *, member_openid, violation_type=OTHER, reason="")` | 按升级 | `WarningService` -> 达阈值联动 `mute`/`kick` |
| `clear_warnings.py` | `clear_warnings(ctx, *, member_openid)` | 否 | `WarningService.clear_warnings` |
| `mute_member.py` | `mute_member(ctx, *, member_openid, duration_seconds=600, reason="")` | 是 | `set_group_members_mute(op="add")` |
| `unmute_member.py` | `unmute_member(ctx, *, member_openid)` | 是 | `set_group_members_mute(op="del")` |
| `get_mute_setting.py` | `get_mute_setting(ctx)` | 否 | `get_group_mute_setting` |
| `kick_member.py` | `kick_member(ctx, *, member_openid, add_to_blacklist=False, reason="")` | 是 | `get_group_member` + `batch_remove_group_members` |
| `recall_message.py` | `recall_message(ctx, *, message_id)` | 是 | `delete_group_message`（2 分钟内） |
| `list_blacklist.py` | `list_blacklist(ctx, *, cursor=None, limit=50)` | 是 | `get_group_member_blacklist` |
| `add_blacklist.py` | `add_blacklist(ctx, *, member_openids)` | 是 | `post_group_member_blacklist(op="add")` |
| `remove_blacklist.py` | `remove_blacklist(ctx, *, member_openids)` | 是 | `post_group_member_blacklist(op="del")` |
| `get_member.py` | `get_member(ctx, *, member_openid)` | 否 | `get_group_member` |
| `list_members.py` | `list_members(ctx, *, cursor=None, limit=50)` | 否 | `get_group_members` |
| `list_join_requests.py` | `list_join_requests(ctx, *, cursor=None, limit=50)` | 是 | `get_group_join_request_list` |
| `approve_join_request.py` | `approve_join_request(ctx, *, member_openid, join_request_id=None)` | 是 | `approval_join_request(op="approve")` |
| `decline_join_request.py` | `decline_join_request(ctx, *, member_openid, join_request_id=None, reject_reason=None, add_to_blacklist=False)` | 是 | `approval_join_request(op="decline")` |
| `get_group_info.py` | `get_group_info(ctx)` | 否 | `get_group_info` |
| `get_bot_state.py` | `get_bot_state(ctx, *, force_refresh=False)` | 否 | `get_group_bot_state` |
| `get_audit_log.py` | `get_audit_log(ctx, *, limit=20, source=None, action=None)` | 否 | `AuditService.query` |

---

## 2. 上游依赖方封装 OpenAI Agents SDK `@function_tool` 示例

依赖方只需几行薄包装即可把任意群管 API 暴露给 OpenAI Agents SDK，同时自动享受全部六阶安全护栏与审计日志：

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
    """对指定 QQ 群成员执行定时禁言。"""
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
