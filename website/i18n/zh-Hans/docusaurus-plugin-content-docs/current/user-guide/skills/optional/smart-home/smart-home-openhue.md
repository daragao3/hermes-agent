---
title: "Openhue —— 通过 OpenHue CLI 控制飞利浦 Hue 灯光、场景和房间"
sidebar_label: "Openhue"
description: "通过 OpenHue CLI 控制飞利浦 Hue 灯光、场景和房间"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Openhue

通过 OpenHue CLI 控制飞利浦 Hue 灯光、场景和房间。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/smart-home/openhue` 安装 |
| 路径 | `optional-skills/smart-home/openhue` |
| 版本 | `1.0.1` |
| 作者 | community |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Smart-Home`, `Hue`, `Lights`, `IoT`, `Automation` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# OpenHue CLI

在终端中通过 Hue Bridge 控制飞利浦 Hue 灯光和场景。

## 前置条件 {#prerequisites}

```bash
# Linux（预编译二进制——发行版提供的是 tar 包，而不是裸二进制文件）
curl -sL "https://github.com/openhue/openhue-cli/releases/latest/download/openhue_Linux_x86_64.tar.gz" \
  | tar -xz -C /tmp openhue \
  && install -m 0755 /tmp/openhue ~/.local/bin/openhue
# （ARM64 上请使用 openhue_Linux_arm64.tar.gz）

# macOS
brew install openhue/cli/openhue-cli
```

首次运行时需要按下 Hue Bridge 上的按钮进行配对。Bridge 必须处于同一局域网中。

## 使用时机 {#when-to-use}

- "开/关灯"
- "把客厅的灯调暗"
- "设置一个场景"或"观影模式"
- 控制特定的 Hue 房间、区域或单个灯泡
- 调整亮度、颜色或色温

## 常用命令 {#common-commands}

### 列出资源 {#list-resources}

```bash
openhue get light       # 列出所有灯
openhue get room        # 列出所有房间
openhue get scene       # 列出所有场景
```

### 控制灯光 {#control-lights}

```bash
# 开/关
openhue set light "Bedroom Lamp" --on
openhue set light "Bedroom Lamp" --off

# 亮度（0-100）
openhue set light "Bedroom Lamp" --on --brightness 50

# 色温（暖到冷：153-500 mirek）
openhue set light "Bedroom Lamp" --on --temperature 300

# 颜色（按名称或十六进制）
openhue set light "Bedroom Lamp" --on --color red
openhue set light "Bedroom Lamp" --on --rgb "#FF5500"
```

### 控制房间 {#control-rooms}

```bash
# 关闭整个房间
openhue set room "Bedroom" --off

# 设置房间亮度
openhue set room "Bedroom" --on --brightness 30
```

### 场景 {#scenes}

```bash
openhue set scene "Relax" --room "Bedroom"
openhue set scene "Concentrate" --room "Office"
```

## 快速预设 {#quick-presets}

```bash
# 就寝（暗、暖）
openhue set room "Bedroom" --on --brightness 20 --temperature 450

# 工作模式（亮、冷）
openhue set room "Office" --on --brightness 100 --temperature 250

# 观影模式（暗）
openhue set room "Living Room" --on --brightness 10

# 全部关闭
openhue set room "Bedroom" --off
openhue set room "Office" --off
openhue set room "Living Room" --off
```

## 说明 {#notes}

- Bridge 必须与运行 Hermes 的机器处于同一局域网
- 首次运行需要实际按下 Hue Bridge 上的按钮进行授权
- 颜色仅对支持彩色的灯泡有效（纯白光型号不支持）
- 灯和房间名称区分大小写——使用 `openhue get light` 查看准确名称
- 非常适合配合 cron 任务实现定时灯光（例如就寝时调暗、起床时调亮）
