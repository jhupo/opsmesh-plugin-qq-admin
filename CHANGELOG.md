# 变更日志（Changelog）

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循 [语义化版本（Semantic Versioning）](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 初始化 `opsmesh-plugin-qq-admin` 项目骨架（顶层包名 `qq_admin`）与跨平台 CI / CodeQL / 安全扫描流水线。
- 完成基于腾讯官方 QQ 机器人 v2 全量群管 API 的四层插件架构设计：有状态安全护栏、滑动窗口警告阶梯升级、入群申请自动审批与独立类模块化的 LLM 群管工具体系（零 `build_*` 闭包工厂）。
