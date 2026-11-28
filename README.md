# opsmesh-plugin-qq-admin

Automatic Official QQ Bot v2 group administration plugin for [OpsMesh](https://github.com/jhupo/OpsMesh), built on **TypeSafe AI Jev** (`typesafe-sdk`) and **dual OpenAI Agents SDK** (`DecisionAgent` + `ReplyAgent`) with **module-owned online configuration**.

## Architecture

- **Minimal Base Config ([config.toml](src/qq_admin/resources/config.toml))**: Only `[jev]`, `[decision_agent]`, and `[reply_agent]` (`DecisionAgentConfig` and `ReplyAgentConfig` inherit `BaseAgentConfig` with `api_key`, `base_url`, `model`, `reasoning_effort`, `temperature`, `max_turns`, `timeout_seconds`). Every feature module owns its own defaults and writes per-group overrides only when customized online via `/admin`.
- **Stateless Model Runners (`src/qq_admin/models/`)**:
  - `Jev.execute(inputs, outputs, images=...)`: thin wrapper over official `typesafe-sdk` `AsyncTypeSafeClient`.
  - `DecisionAgent.execute(prompt, context=...)`: stateless tool-calling moderation decision agent (`temperature=0.0`).
  - `ReplyAgent.execute(spec)`: stateless persona-driven reply composer (`temperature=0.7`) with hallucination/safety guardrails.
- **Self-Contained Feature Modules (`src/qq_admin/modules/`)**:
  - `identity` (`IdentityConfig` + `IdentityModule`): Bot/member role cache, authorization, `/admin perm` trace.
  - `safeguard` (`SafeguardConfig` + `SafeguardModule`): Role-aware 8-step safety guardrails (bypassed when Bot is group owner).
  - `warning` (`WarningConfig` + `WarningModule`): Sliding-window categorized warnings (`spam`/`abuse`/`ad`).
  - `escalation` (`EscalationConfig` + `EscalationModule`): Progressive punishment ladder (`mute` → `kick/ban`).
  - `audit` (`AuditConfig` + `AuditModule`): Per-group moderation & lifecycle audit logs.
  - `moderation` (`ModerationConfig` + `ModerationModule`): Jev → DecisionAgent → ReplyAgent pipeline and QQ v2 actions.
  - `approval` (`ApprovalConfig` + `ApprovalModule`): Join-request risk review (`risk_tips` + Jev) and background polling.
- **Single Typed Container ([manager.py](src/qq_admin/manager.py))**: `ServiceManager` holds `store`, `jev`, `decision_agent`, `reply_agent`, and all 7 feature modules directly.
- **Direct Entrypoints**:
  - `commands/` (`admin.py`, `actions.py`, `queries.py`): Directly registered OpsMesh slash commands.
  - `messages/` (`group_message.py`, `group_events.py`): Group message & lifecycle entries (`GroupJoinRequestEvent`, `GroupMemberAddEvent`, `GroupMemberRemoveEvent`, `GroupAddRobotEvent`, `GroupDelRobotEvent`).

## Quick Start

```python
import opsmesh
import qq

opsmesh.init()
opsmesh.register_adapter(qq.Adapter)
opsmesh.load_plugin("qq_admin")
opsmesh.run()
```

Enable group moderation online in any group (by group owner or configured global admin):

```text
/admin on
/admin config set safeguard.max_mute_duration 1800
/admin status
```

## Documentation

- [Architecture](docs/01-architecture.md)
- [Configuration](docs/02-configuration.md)
- [Commands & API](docs/03-commands-and-api.md)
