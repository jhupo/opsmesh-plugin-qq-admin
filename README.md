# opsmesh-plugin-qq-admin

Automatic Official QQ Bot v2 multi-group administration plugin for [OpsMesh](https://github.com/jhupo/OpsMesh), built around a **deterministic moderation planner + TypeSafe AI Jev (`Jev.execute`) + persona `ReplyAgent`**, target-group admin authorization, and direct global module singletons for downstream Agent/chat plugins.

## Architecture

- **Minimal Flat Config ([config.py](src/qq_admin/config.py))**: One flat `Config` (`jev_api_key`, `jev_model`, `openai_api_key`, `openai_base_url`, `model`, `reasoning_effort`, `timeout_seconds`, `default_group_enabled`, `config_path`).
- **Multi-Group Diff Overrides ([store.py](src/qq_admin/store.py))**: `CONFIG_STORE = ConfigStore()` persists global defaults merged with diff-only per-group overrides under `[groups."<group_openid>"]` via atomic file writes.
- **Dedicated Prompts Folder (`src/qq_admin/prompts/`)**:
  - `reply_agent.md`: Mature group-admin persona Markdown template rendered only when moderation or action replies are needed.
  - `jev.toml`: 11 fixed safety categories (`violence`, `sexual_content`, `suicide_self_harm`, `political_sensitive`, `jailbreak`, `non_violent_crime`, `pii`, `unethical_behavior`, `copyright_infringement`, `advertising`, `prompt_injection`) + `severity` (0–4) + join-request review instructions.
  - `notices.toml`: Deterministic ops console templates and 0ms output guardrail patterns.
- **Stateless Model Runners (`src/qq_admin/models/`)**:
  - `Jev.execute(text=..., images=..., urls=...) -> SafetyReport`: stateless multimodal risk classifier.
  - `ReplyAgent.execute(spec)`: stateless OpenAI Responses API reply composer guarded by pure-code anti-hallucination checks (`reply_guardrail`).
- **Direct Global Module Singletons (`src/qq_admin/modules/`)**:
  - `IDENTITY` & `GROUP_ADMIN`: Multi-bot `(self_id, group_id)` role cache, target-group admin authorization, and OpsMesh `Permission`.
  - `SAFEGUARD`: Role-aware 8-step safety guardrails (bypassed when Bot is group owner).
  - `WARNING`: Sliding-window categorized warnings (`spam`/`abuse`/`ad`) with automatic mute upgrade.
  - `ESCALATION`: Progressive punishment ladder (`mute` -> `kick` + `blacklist`).
  - `AUDIT`: Per-group isolated ring-buffer audit logs.
  - `MODERATION`: Fixed deterministic moderation pipeline (whitelist/empty/trusted-URL short-circuit -> flood/repeat rate limiter -> `Jev` -> deterministic action -> `ReplyAgent`) and target-authorized QQ v2 management methods.
  - `APPROVAL`: Event-driven `GroupJoinRequestEvent` review with pre-Jev quota/whitelist short-circuits.
- **Downstream Plugin Interoperability**:
  - Admin messages and normal chat pass silently (`block=False`) to downstream context-aware chat/Agent plugins, while prompt injections and violations are blocked upstream (`stop_propagation()`).
  - Downstream plugins import `MODERATION`, `APPROVAL`, `IDENTITY`, `GROUP_ADMIN`, `SAFEGUARD`, `AUDIT` directly — every write method enforces target-group `IDENTITY.is_admin` when `operator_id != "bot"`.

## Quick Start

```python
import opsmesh
import qq

opsmesh.init()
opsmesh.register_adapter(qq.Adapter)
opsmesh.load_plugin("qq_admin")
opsmesh.run()
```

Enable and customize per-group moderation online:

```text
/admin on
/admin groups
/admin config set safeguard.max_mute_duration 1800
/admin config reset safeguard.max_mute_duration
/admin status
```

## Documentation

- [Architecture](docs/01-architecture.md)
- [Configuration](docs/02-configuration.md)
- [Commands & API](docs/03-commands-and-api.md)
