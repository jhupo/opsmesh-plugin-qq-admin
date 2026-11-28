# Changelog

## 0.2.0

- **Modular Self-Owned Config Architecture**:
  - Removed `PluginSettings`, `commands/registry.py`, and dynamic module registration in favor of a minimal base config (`[jev]` + `[agent]`), a module-agnostic `ConfigStore`, and a single strongly-typed `ServiceManager`.
  - Every feature module under `src/qq_admin/modules/` (`identity`, `safeguard`, `warning`, `escalation`, `audit`, `moderation`, `approval`) now owns its own Pydantic config model, defaults, and online per-group `update_config(...)`.
- **Independent Model Runners with `execute(...)` & Session Modes**:
  - Split `models/` into `Jev`, `DecisionAgent`, and `ReplyAgent`, all exposing clean `execute(...)` APIs.
  - Added configurable `session_mode` (`"fresh"` per call or `"shared"` via `openai-agents` `SQLiteSession`) plus online `/admin session mode <fresh|shared>` and `/admin session reset`.
- **Direct Command & Message/Lifecycle Entrypoints**:
  - `commands/` (`admin.py`, `actions.py`, `queries.py`) register directly onto OpsMesh without an intermediate registry layer, including `/admin config get|set`.
  - `messages/` (`group_message.py`, `group_events.py`) handle group messages, join requests, member join/leave, and bot join/leave events.
- **Zero Chinese in Python Source**: All localized prompts, Jev criteria, and fallback notices live strictly in `src/qq_admin/resources/prompts.toml`.
