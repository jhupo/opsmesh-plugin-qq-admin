# 02. `QQGroupAdmin` 与 `QQGroupScope` 完整 API 参考手册

所有公开类、依赖注入类型与辅助函数均可直接从顶层包 `qq_admin` 导入：

```python
from qq_admin import (
    QQGroupAdmin,
    QQGroupScope,
    GroupAdmin,
    CurrentGroup,
    MuteDuration,
    parse_mute_duration,
    can_manage_member,
    ensure_can_manage,
    extract_group_openid,
    QQAdminError,
    BotNotAdminError,
    HierarchyError,
    GroupTargetRequiredError,
)
```

---

## 1. 构造与单群绑定

| 方式 | 签名 | 说明 |
| :--- | :--- | :--- |
| 跨群管理实例 | `admin = QQGroupAdmin(gateway)` | 绑定 `qq.Gateway`，所有方法首参为 `group_openid` |
| 单群作用域实例 | `scope = admin.group(group_openid)` | 返回 `QQGroupScope`，后续所有调用省略 `group_openid` |
| 从入站群事件创建 | `scope = QQGroupAdmin.from_event(gateway, event)` | 自动从 `GroupMessageEvent` / `GroupNoticeEvent` / `InteractionCreateEvent` 提取 `group_openid`（非群事件抛 `GroupTargetRequiredError`） |
| OpsMesh 依赖注入 | `admin: GroupAdmin` / `group: CurrentGroup` | 在 `@matcher.handle()` 参数中直接声明即可自动注入 |

---

## 2. 全量群管理方法清单（`QQGroupAdmin` / `QQGroupScope` 一一对应）

下表列出 `QQGroupAdmin` 方法签名；在 `QQGroupScope` 上调用同名方法时省略首个 `group_openid` 参数即可：

### 2.1 群信息与机器人本群身份

| 方法 | 入参 | 返回类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `get_info` | `(group_openid)` | `GroupInfoReturn` | 查询群名称、人数 `group_member_num`、简介 `group_finger_memo`、分类与标签 |
| `get_bot_state` | `(group_openid)` | `GroupBotStateReturn` | 查询 Bot 在本群的 `member_role`（`member`/`admin`/`owner`）与主动消息状态 |
| `is_bot_admin` | `(group_openid)` | `bool` | 判断 Bot 在本群是否为 `admin` 或 `owner` |
| `ensure_bot_admin` | `(group_openid)` | `GroupBotStateReturn` | 若 Bot 仅为 `member` 则抛 `BotNotAdminError`，否则返回状态 |

### 2.2 群成员查询与自动翻页

| 方法 | 入参 | 返回类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `get_member` | `(group_openid, member_openid)` | `GroupMemberInfo` | 查询单个成员昵称、群内角色、入群时间与是否机器人 |
| `list_members` | `(group_openid, *, cursor=None, limit=None)` | `GroupMembersReturn` | 单页游标查询成员列表 |
| `list_members_by_index` | `(group_openid, *, start_index=None, limit=None)` | `PostGroupMembersReturn` | 索引分页查询成员列表 |
| `iter_members` | `(group_openid, *, limit=None)` | `AsyncIterator[GroupMemberInfo]` | 自动跟随 `next_cursor` 异步迭代全群成员 |
| `get_all_members` | `(group_openid, *, limit=None)` | `list[GroupMemberInfo]` | 一次性自动翻页拉取全群成员列表 |

### 2.3 禁言管理

`MuteDuration` 支持：`int`/`float` 秒数（如 `600`）、简写字符串（`"30s"` / `"10m"` / `"2h"` / `"7d"`）、`datetime.timedelta` 或 `datetime.datetime`。

| 方法 | 入参 | 返回类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `get_mute_setting` | `(group_openid)` | `GroupRestrictChatSettingReturn` | 查询全体禁言规则与被禁言成员列表 |
| `get_global_mute_rule` | `(group_openid)` | `GlobalMuteRule` | 仅获取本群全体禁言规则（`mode`: `"none"\|"always"\|"schedule"`） |
| `list_muted_members` | `(group_openid)` | `list[MemberMuteState]` | 仅获取当前正被禁言的成员及解封时间列表 |
| `mute` | `(group_openid, member_openid, duration=600, *, op="add")` | `None` | 禁言单个成员（已禁言成员改时长传 `op="update"`） |
| `mute_many` | `(group_openid, member_openids, duration=600, *, op="add")` | `None` | 批量禁言多个成员 |
| `unmute` | `(group_openid, member_openid)` | `None` | 解除单个成员禁言 |
| `unmute_many` | `(group_openid, member_openids)` | `None` | 批量解除多个成员禁言 |

### 2.4 踢出群成员

| 方法 | 入参 | 返回类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `kick` | `(group_openid, member_openid, *, add_to_blacklist=False)` | `BatchRemoveMembersReturn` | 移出单个群成员，可选同时拉黑 |
| `kick_many` | `(group_openid, member_openids, *, add_to_blacklist=False)` | `BatchRemoveMembersReturn` | 批量移出群成员，可选同时拉黑 |

### 2.5 群黑名单管理

| 方法 | 入参 | 返回类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `list_blacklist` | `(group_openid, *, cursor=None, limit=None)` | `GroupMemberBlacklistReturn` | 单页查询群黑名单 |
| `iter_blacklist` | `(group_openid, *, limit=None)` | `AsyncIterator[BlacklistUser]` | 自动翻页迭代全量黑名单成员 |
| `get_all_blacklist` | `(group_openid, *, limit=None)` | `list[BlacklistUser]` | 一次性拉取全量群黑名单成员 |
| `ban` / `ban_many` | `(group_openid, member_openid \| member_openids)` | `MemberBlacklistOpReturn` | 单人或批量移入群黑名单 |
| `unban` / `unban_many` | `(group_openid, member_openid \| member_openids)` | `MemberBlacklistOpReturn` | 单人或批量移出群黑名单 |

### 2.6 入群申请审批与消息撤回

| 方法 | 入参 | 返回类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `list_join_requests` | `(group_openid, *, cursor=None, limit=None)` | `JoinRequestListReturn` | 单页查询入群申请单（含 `verify_info.review_qa_list` 与 `risk_tips`） |
| `iter_join_requests` | `(group_openid, *, limit=None)` | `AsyncIterator[JoinRequest]` | 自动翻页迭代入群申请列表 |
| `get_all_join_requests` | `(group_openid, *, limit=None)` | `list[JoinRequest]` | 一次性拉取全部待审入群申请 |
| `approve_join` | `(group_openid, member_openid, *, join_request_id=None)` | `None` | 同意入群申请 |
| `reject_join` | `(group_openid, member_openid, *, join_request_id=None, reason=None, add_to_blacklist=False)` | `None` | 拒绝入群申请，可选填拒绝理由并拉黑 |
| `recall` | `(group_openid, message_id)` | `None` | 撤回 2 分钟以内的群消息 |

---

## 3. 辅助函数与异常类

- **`parse_mute_duration(duration)`**：将秒数、`"10m"` 等字符串或 `timedelta` 规范化为 `timedelta | datetime`。
- **`can_manage_member(operator_role, target_role) -> bool`**：按官方层级（`owner > admin > member`，且不可操作 `owner`）返回是否允许管理。
- **`ensure_can_manage(operator_role, target_role)`**：层级不足时抛出 `HierarchyError`。
- **`extract_group_openid(event) -> str`**：从入站群事件提取 `group_openid`，非群事件抛 `GroupTargetRequiredError`。

---

## 4. 在上游依赖项目中封装 OpenAI Agents SDK 工具示例

```python
from agents import RunContextWrapper, function_tool
from qq_admin import QQGroupScope


@function_tool
async def mute_group_member(
    ctx: RunContextWrapper[QQGroupScope],
    member_openid: str,
    duration: str = "10m",
) -> str:
    """Mute a QQ group member for the specified duration (e.g. '10m', '2h', '1d')."""
    await ctx.context.mute(member_openid, duration)
    return f"Muted {member_openid} for {duration}."
```
