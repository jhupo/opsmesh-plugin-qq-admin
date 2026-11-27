# 03. 双重权限矩阵、六阶安全护栏与核心业务时序图

本文档定义 `qq_admin.services` 的双重身份判定逻辑、高危写操作安全护栏管线、违规警告阶梯升级状态机，以及命令/Tool 统一执行与自动入群审批的完整时序流程。

---

## 1. 双重身份权限矩阵（`Operator Role × Bot Role`）

所有群管动作必须同时满足**发起人权限**与**机器人本群权限**：

| 动作分级 | 代表操作 | 发起人最低要求 (`OperatorIdentity`) | Bot 本群最低角色 (`get_group_bot_state`) | 配额与冷却约束 |
| :--- | :--- | :--- | :--- | :--- |
| **P0 系统管控** | `/admin on\|off` · 清空配额 · 豁免护栏 | `SUPERUSER` 或 `GROUP_OWNER` | `member` | 不受配额限制 |
| **P1 高危写操作** | `kick` · `add_blacklist` · `remove_blacklist` | `SUPERUSER \| GROUP_OWNER \| GROUP_ADMIN` | `admin` 或 `owner` | 强制走六阶护栏 + 每日配额 |
| **P2 常规写操作** | `mute` · `unmute` · `recall` · `approve/decline` | `SUPERUSER \| GROUP_OWNER \| GROUP_ADMIN` | `admin` 或 `owner` | 强制走六阶护栏 + 每日配额 |
| **P3 只读与审计** | `groupinfo` · `member` · `shutlist` · `audit_log` | `SUPERUSER \| GROUP_OWNER \| GROUP_ADMIN` | `member`（`banlist`/`requests` 需 `admin`） | 无配额扣减 |

---

## 2. 六阶高危动作安全护栏流程图（`SafeguardService`）

```mermaid
flowchart TD
    REQ["收到写操作请求 (来自斜杠命令或独立 LLM Tool)"] --> S1{"1. 分群开关检查: is_group_enabled?"}
    S1 -- "已关闭" --> REJ1["拦截: GroupAdminDisabledError + 记录审计"]
    S1 -- "已开启" --> S2{"2. 发起人权限检查: SUPERUSER / OWNER / ADMIN?"}
    S2 -- "普通群员" --> REJ2["拦截: PermissionDeniedError + 记录审计"]
    S2 -- "通过" --> S3{"3. Bot 本群身份检查: bot_role in {admin, owner}?"}
    S3 -- "Bot 仅为 member" --> REJ3["拦截: BotRoleInsufficientError + 提示设管理员"]
    S3 -- "通过" --> S4{"4. 目标保护与层级压制检查"}
    S4 -- "目标为 Bot 自身 / protected_openids / 群主 / 同级管理员" --> REJ4["拦截: TargetProtectedError + 记录审计"]
    S4 -- "通过" --> S5{"5. 目标冷却锁检查: acquire_target_cooldown?"}
    S5 -- "冷却中" --> REJ5["拦截: CooldownActiveError (防并发重复触发)"]
    S5 -- "通过" --> S6{"6. 单群自然日配额检查: consume_daily_quota?"}
    S6 -- "超出当日上限" --> REJ6["拦截: QuotaExceededError + 记录审计"]
    S6 -- "通过 (裁剪禁言时长至合法区间)" --> EXEC["调用 qq.Gateway 官方 v2 原子接口并写入成功审计"]
```

---

## 3. 滑动窗口违规警告与阶梯升级状态机（`WarningService`）

针对刷屏（`spam`）、辱骂（`abuse`）、广告（`ad`）等违规记录，在滑动时间窗 `window_seconds`（默认 24h）内自动计算有效次数并执行阶梯升级：

```mermaid
stateDiagram-v2
    [*] --> Clean: 窗口内有效违规数 = 0
    Clean --> Warned: 触发 warn_member (计数 < mute_threshold)
    Warned --> Warned: 再次触发但未达禁言阈值 (仅发送警告提示)
    Warned --> AutoMuted: 计数 >= mute_threshold (默认第 2 次 -> 自动定时禁言)
    AutoMuted --> AutoMuted: 计数介于 mute_threshold 与 kick_threshold 之间
    AutoMuted --> AutoKicked: 计数 >= kick_threshold (默认第 4 次 -> 自动踢出群聊)
    Warned --> Clean: 超过滑动窗口自动过期 / 执行 clear_warnings
    AutoMuted --> Clean: 执行 clear_warnings
    AutoKicked --> [*]
```

---

## 4. 斜杠命令与对外函数 API 统一执行时序图

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 群管理员 / 上游调用方
    participant Entry as matchers/moderation.py 或 qq_admin.api.mute_member
    participant Mod as ModerationService
    participant Idn as IdentityService
    participant Sfg as SafeguardService
    participant GW as qq.Gateway (opsmesh-adapter-qq)
    participant Aud as AuditService

    Admin->>Entry: "/mute @目标 10m 刷屏" 或 await mute_member(ctx, member_openid=..., duration_seconds=600)
    Entry->>Mod: mute_member(ctx, member_openid, duration=600, reason="刷屏")
    Mod->>Idn: ensure_operator_and_bot_admin(ctx)
    alt 缓存未命中 Bot 角色
        Idn->>GW: get_group_bot_state(group_openid)
        GW-->>Idn: GroupBotStateReturn(member_role="admin")
    end
    Mod->>GW: get_group_member(group_openid, member_openid)
    GW-->>Mod: GroupMemberInfo(member_role="member")
    Mod->>Sfg: verify_and_consume(group_openid, target, action="mute", target_role="member")
    Sfg-->>Mod: SafeguardPass(clamped_duration=600, remaining_quota=29)
    Mod->>GW: set_group_members_mute(group_openid, [SetMemberMuteState(op="add", ...)])
    GW-->>Mod: HTTP 200 OK
    Mod->>Aud: record_success(ctx, action="mute", target=member_openid)
    Mod-->>Entry: ModerationOutcome(summary="已禁言 10 分钟，今日剩余配额 29")
    Entry-->>Admin: 被动回复群消息 或 返回 ModerationOutcome
```

---

## 5. 入群申请事件驱动 + 巡检补偿自动审批时序图（`AutoApproveService`）

```mermaid
sequenceDiagram
    autonumber
    participant TX as 腾讯 QQ 开放平台
    participant ADP as qq.Adapter
    participant APR as AutoApproveService
    participant MOD as ModerationService
    participant GW as qq.Gateway

    TX->>ADP: GROUP_JOIN_REQUEST 事件推送
    ADP->>APR: on_type(GroupJoinRequestEvent)
    alt auto_approved == True (平台侧已自动通过)
        APR-->>APR: 仅记录审计日志并跳过重复审批
    else 命中本地黑名单 或 (存在 risk_tips 且配置自动拒绝)
        APR->>MOD: decline_join_request(join_request_id, reason, blacklist)
        MOD->>GW: approval_join_request(op="decline", ...)
    else verify_info 命中 pass_keywords 或 invited_by 命中受信任成员
        APR->>MOD: approve_join_request(join_request_id)
        MOD->>GW: approval_join_request(op="approve", ...)
    else 未命中自动规则 (转人工待审)
        APR->>GW: 可选在群内或管理渠道提示待审单号 (/approve /reject)
    end

    opt poll_interval_seconds > 0 (断线期间漏单定时对账)
        APR->>GW: get_group_join_request_list(group_openid)
        GW-->>APR: JoinRequestListReturn (过滤未处理申请单逐一复用上述规则)
    end
```
