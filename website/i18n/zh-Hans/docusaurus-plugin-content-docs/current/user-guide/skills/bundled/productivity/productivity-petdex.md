---
title: "Petdex —— 为 Hermes 安装并选择动画 petdex 吉祥物"
sidebar_label: "Petdex"
description: "为 Hermes 安装并选择动画 petdex 吉祥物"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Petdex

为 Hermes 安装并选择动画 petdex 吉祥物。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/petdex` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `petdex`, `mascot`, `display`, `cli`, `tui`, `desktop` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Petdex Skill

从公开的 [petdex](https://github.com/crafter-station/petdex) 图库中浏览、安装并选择
动画“宠物”吉祥物。已安装的宠物会在 Hermes CLI、TUI 和桌面应用中
对 agent 活动（空闲、执行工具、审阅、错误、完成）作出反应。
本 skill 驱动 `hermes pets` CLI 和 `display.pet` 配置 —— 它不会生成精灵图。

## 使用场景

- 用户想要一个桌面/终端吉祥物，或询问“pets”/petdex 相关内容。
- 用户想要更换、预览或禁用当前激活的宠物。
- 诊断宠物为何没有显示（终端图形支持、配置）。

## 前置条件

- 可访问 `petdex.dev` 网络以获取图库/清单（只读，无需鉴权）。
- 用于精灵图解码的 Pillow（Hermes 的核心依赖）—— 已随附安装。
- 若需完整保真的终端渲染：需要支持图形的终端（kitty、
  Ghostty、WezTerm、iTerm2 或 sixel）。否则会自动回退到
  truecolor Unicode 半块字符渲染。

## 如何运行

使用 `terminal` 工具运行 `hermes pets <subcommand>`。

## 快速参考

| 目标 | 命令 |
| --- | --- |
| 浏览图库 | `hermes pets list`（添加子串进行过滤：`hermes pets list cat`） |
| 列出已安装的宠物 | `hermes pets list --installed` |
| 安装宠物 | `hermes pets install <slug>`（加上 `--select` 使其激活） |
| 设置激活的宠物 | `hermes pets select <slug>`（省略 slug 可打开选择器） |
| 在所有界面调整宠物大小 | `hermes pets scale <factor>`（例如 `0.5`，取值范围限制在 0.1–3.0） |
| 在终端中预览/播放动画 | `hermes pets show [slug] [--cycle] [--state run]` |
| 禁用宠物 | `hermes pets off` |
| 移除宠物 | `hermes pets remove <slug>` |
| 诊断配置 | `hermes pets doctor` |

## 操作步骤

1. 查找宠物：`hermes pets list <query>`，记下它的 `slug`。
2. 安装并激活：`hermes pets install <slug> --select`。
3. 预览效果：`hermes pets show`（Ctrl+C 停止）。
4. 确认配置：`hermes pets doctor` —— 会显示解析出的宠物、配置的
   渲染模式、检测到的终端图形协议以及实际生效的模式。

宠物会安装到 `<HERMES_HOME>/pets/<slug>/`（区分 profile）。选择某个宠物会
将 `display.pet.slug` 和 `display.pet.enabled` 写入 `config.yaml`。

## 配置

位于 `config.yaml` 的 `display.pet` 之下：

- `enabled`（bool）—— 总开关。
- `slug`（str）—— 激活的宠物；为空表示使用第一个已安装的宠物。
- `render_mode` —— `auto`（自动检测）| `kitty` | `iterm` | `sixel` | `unicode` | `off`。
- `scale`（float）—— 原生 192×208 帧在屏幕上的显示尺寸（默认 0.33，
  取值范围限制在 0.1–3.0）。一个参数即可调整所有界面的尺寸；可通过
  `hermes pets scale <factor>`、`/pet scale` 斜杠命令或桌面端的
  外观（Appearance）滑块进行设置。
- `unicode_cols`（int）—— Unicode 回退渲染的列宽。

## 注意事项

- 只有在安装并选择了宠物（`enabled: true`）之后，宠物才会显示。
- 在管道/重定向中（无 TTY）终端渲染会被有意禁用。
- petdex 的 npm CLI 会安装到 `~/.codex/pets`；Hermes 使用自己的
  按 profile 划分的 `<HERMES_HOME>/pets/` —— 请通过 `hermes pets` 安装。

## 验证

- 当宠物已安装、已选择、已启用且 Pillow 可导入时，`hermes pets doctor`
  会报告 `✓ ready`。
