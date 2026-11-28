# 03. 声明式命令、Agent 工具与编程接口

## 1. 21 个声明式群管命令（`qq_admin/commands/`）

### `/admin` 控制台（`commands/console.py`，全局管理员 / 群主）
- `/admin status` — 查看运行状态、Bot 角色与今日配额计数
- `/admin on` / `/admin off` — 开启或暂停本群自动群管
- `/admin log [count]` — 查看最近 `count` 条操作审计日志
- `/admin perm [member_openid]` — 渲染目标成员的完整权限决策链
- `/admin exempt <member_openid>` / `/admin unexempt <member_openid>` — 管理本群豁免名单
- `/admin undo <member_openid>` — 强制解禁并移出豁免名单

### 群管写操作（`commands/actions.py`，全局管理员 / 群主 / 群管理员）
- `/warn <member_openid> <spam|abuse|ad> [reason]`
- `/mute <member_openid> <10m|1h|600> [reason]`
- `/unmute <member_openid>`
- `/kick <member_openid> [--ban] [reason]`
- `/ban <member_openid> [reason]`
- `/unban <member_openid>`
- `/recall <message_id>`
- `/approve <member_openid> <join_request_id>`
- `/reject <member_openid> <join_request_id> [reason]`

### 状态查询（`commands/queries.py`，全局管理员 / 群主 / 群管理员）
- `/shutlist`、`/blacklist`、`/requests`、`/member [member_openid]`

## 2. `DecisionPlanner` 工具集（`GROUP_ADMIN_TOOLS`）

无冗余前缀，直接以领域意图命名：
- 查询：`get_member`、`list_muted_members`
- 执行（受 `action_guardrail` 8 步硬护栏 + Jev 动作二审保护）：`warn_member`、`mute_member`、`unmute_member`、`kick_member`、`ban_member`、`unban_member`、`recall_message`

## 3. 编程调用示例

```python
from qq import Gateway
from qq_admin import get_runtime

async def mute_spammer(gateway: Gateway, group_id: str, member_id: str) -> None:
    rt = get_runtime()
    outcome = await rt.moderator.mute(
        gateway, group_id, member_id, duration="15m", reason="external alert"
    )
    print(outcome.succeeded, outcome.message)
```
