# 03. 命令参考、双 Agent 接口与外部调用

## 1. `/admin` 控制台（8 个，全局管理员 / 群主可用）

| 命令 | 说明 |
| :--- | :--- |
| `/admin status` | 查看当前群状态、Bot 角色、今日禁言/踢人/审批计数与配额 |
| `/admin on` / `/admin off` | 动态开启或暂停当前群自动群管 |
| `/admin log [n]` | 查看最近 `n` 条群管操作审计日志 |
| `/admin perm [member_openid]` | 逐步展示目标成员的完整权限决策链 |
| `/admin exempt <member>` / `/admin unexempt <member>` | 管理本群临时豁免名单 |
| `/admin undo <member>` | 强制解除禁言 |

## 2. 日常群管与查询命令（13 个，全局管理员 / 群主 / 群管理员可用）

- 管控执行：`/warn <member> <spam|abuse|ad> [reason]`、`/mute <member> <10m|1h|600> [reason]`、`/unmute <member>`、`/kick <member> [--ban] [reason]`、`/ban <member> [reason]`、`/unban <member>`、`/recall <message_id>`、`/approve <member> <req_id>`、`/reject <member> <req_id> [reason]`
- 状态查询：`/shutlist`、`/blacklist`、`/requests`、`/member [member]`

> 当 `QQ_ADMIN__LLM__ENABLED=true` 时，管控命令的执行结果、护栏拦截与权限拒绝均交由 `ReplyAgent` 结合实时状态与角色提示词自然回复；关闭 LLM 时回退到 `resources/prompts.toml` 的 `[fallback_messages]`。

## 3. 外部注入 `JevClient` 与直接调用

```python
from qq import Gateway
from qq_admin import JevClient, JevConfig, QQAdminConfig, configure, get_runtime, mute_member

jev = JevClient(JevConfig(enabled=True, api_key="ts-your-key"))
configure(QQAdminConfig(), jev_client=jev)

async def mute_from_hook(gateway: Gateway, group_openid: str, member_openid: str) -> None:
    res = await mute_member(
        gateway,
        get_runtime(),
        group_openid=group_openid,
        member_openid=member_openid,
        duration="10m",
        reason="external risk trigger",
    )
    print(res.ok, res.summary)
```
