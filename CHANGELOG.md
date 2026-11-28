# 变更日志（Changelog）

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循 [语义化版本（Semantic Versioning）](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 实现面向官方 QQ 机器人 v2 全量群管理 API 的无状态高内聚接口类 `QQGroupAdmin` 与单群绑定视图 `QQGroupScope`。
- 支持秒数、简写字符串（`"30s"`/`"10m"`/`"2h"`/`"1d"`）、`timedelta` 与 `datetime` 禁言时长归一化。
- 支持群成员、群黑名单与入群申请列表的 `next_cursor` 自动游标翻页迭代（`iter_*` / `get_all_*`）。
- 提供 OpsMesh 原生依赖注入注解 `GroupAdmin` 与 `CurrentGroup`。
