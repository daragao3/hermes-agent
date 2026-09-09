---
title: "Antigravity Cli — 操作 Antigravity CLI（agy）：插件、认证、沙箱"
sidebar_label: "Antigravity Cli"
description: "操作 Antigravity CLI（agy）：插件、认证、沙箱"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Antigravity Cli

操作 Antigravity CLI（agy）：插件、认证、沙箱。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/autonomous-ai-agents/antigravity-cli` 安装 |
| 路径 | `optional-skills/autonomous-ai-agents/antigravity-cli` |
| 版本 | `0.1.0` |
| 作者 | Tony Simons (asimons81), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Coding-Agent`, `Antigravity`, `CLI`, `Auth`, `Plugins`, `Sandbox` |
| 相关 skills | [`grok`](/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-grok), [`codex`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex), [`claude-code`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code), [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Antigravity CLI（`agy`）

Antigravity CLI 的操作指南，命令名为 `agy`。所有 `agy` 命令都通过 Hermes 的
`terminal` 工具运行；用 `read_file` 检查它的配置和日志。此 skill 是参考 + 操作步骤
—— 它并不封装任何网络 API，因此 Hermes 自身无需进行认证。

## 使用场景

- 安装、更新或冒烟测试 `agy` 二进制文件
- 驱动非交互式的 `agy --print` / `agy -p` 一次性调用
- 调试 Antigravity 的认证、沙箱、权限或插件状态
- 读取 Antigravity 的设置、快捷键、会话记录或日志

## 心智模型

Antigravity 有两个层次 —— 必须区分清楚，否则指导会出错：

1. **Shell 包装器命令** —— `agy help`、`agy install`、`agy plugin`、
   `agy update`、`agy changelog`。这些通过 `terminal` 工具运行。
2. **会话内的交互式斜杠命令** —— `/config`、`/permissions`、
   `/skills`、`/agents` 等。它们只存在于正在运行的 `agy` TUI
   会话中，而不在 shell 包装器上。

`agy help` 展示的是 shell 包装器的命令面，而不是会话内的斜杠命令。

## 前置条件

- PATH 上有 `agy` 二进制文件。通过 `terminal` 工具验证：
  `command -v agy && agy --version`。
- 此 skill 不需要任何环境变量或 API key —— Antigravity 通过操作系统钥匙串 /
  浏览器登录自行管理认证（参见下文的认证行为）。

## 如何运行

每一条 `agy` 命令都通过 `terminal` 工具调用。示例：

```
terminal(command="agy --version")
terminal(command="agy help")
terminal(command="agy plugin list")
terminal(command="agy --print 'Summarize the repo in 3 bullets'", workdir="/path/to/project")
```

若需要交互式的多轮 TUI 会话，用 `pty=true` 启动 `agy`（并配合 tmux 做捕获/监控），
与 `codex` / `claude-code` skill 采用的模式相同。对于一次性冒烟测试和脚本化提示词，
优先使用 `agy --print`（非交互式）。

要检查 Antigravity 自己的文件，请对下方"核心路径"中的路径使用 `read_file`
—— 不要通过终端 `cat` 它们。

## 核心路径

- 二进制 / 入口：`agy`
- 应用数据目录：`~/.gemini/antigravity-cli/`
- 设置文件：`~/.gemini/antigravity-cli/settings.json`
- 快捷键文件：`~/.gemini/antigravity-cli/keybindings.json`
- 日志：`~/.gemini/antigravity-cli/log/cli-*.log`
- 会话记录：`~/.gemini/antigravity-cli/conversations/`
- Brain 产物：`~/.gemini/antigravity-cli/brain/`
- 历史：`~/.gemini/antigravity-cli/history.jsonl`
- 插件暂存目录：`~/.gemini/antigravity-cli/plugins/<plugin_name>/`

## 快速参考

### 包装器命令
- `agy changelog`
- `agy help`
- `agy install`
- `agy plugin` / `agy plugins`
- `agy update`

### 常用参数
- `--add-dir`
- `--continue` / `-c`
- `--conversation`
- `--dangerously-skip-permissions`
- `--print` / `-p`
- `--print-timeout`
- `--prompt`
- `--prompt-interactive` / `-i`
- `--sandbox`
- `--log-file`
- `--version`

### 插件子命令（`agy plugin --help`）
- `list`、`import [source]`、`install <target>`、`uninstall <name>`、
  `enable <name>`、`disable <name>`、`validate [path]`、`link <mp> <target>`、
  `help`

### 安装参数（`agy install --help`）
- `--dir`、`--skip-aliases`、`--skip-path`

### 会话内斜杠命令
- **会话控制：** `/resume`（`/switch`）、`/rewind`（`/undo`）、
  `/rename <name>`、`/clear`、`/fork`、`/reset`、`/new`
- **设置与工具：** `/config`、`/settings`、`/permissions`、`/model`、
  `/keybindings`、`/statusline`、`/tasks`、`/skills`、`/mcp`、`/open <path>`、
  `/usage`、`/logout`、`/agents`
- **提示词辅助：** `@` 路径自动补全，`esc esc` 清空提示词（未在流式输出时），
  `!` 直接运行一条终端命令，`?` 打开帮助

## 设置与权限

### 常见设置项（`settings.json`）
- `allowNonWorkspaceAccess`
- `colorScheme`
- `permissions.allow`
- `trustedWorkspaces`

### 权限模式
`request-review`、`always-proceed`、`strict`、`proceed-in-sandbox`。

### 沙箱行为
- `enableTerminalSandbox` 是 `settings.json` 中的一个布尔值；默认为 `false`。
- 启动时的覆盖项（`--sandbox`、`--dangerously-skip-permissions`）可以在当前会话中
  覆盖持久化设置。

## 认证行为

- CLI 会优先尝试操作系统的安全钥匙串。
- 如果没有已保存的会话，它会回退到基于浏览器的 Google 登录。
- 在本地它会打开默认浏览器；通过 SSH 时它会打印一个授权 URL，
  并等待你把授权码粘贴回来。
- `/logout` 会移除已保存的凭证。

## 插件

- 插件暂存于 `~/.gemini/antigravity-cli/plugins/<plugin_name>/`。
- 它们可以打包 skill、agent、规则、MCP 服务器和 hook。
- `agy plugin list` 返回没有已导入的插件是一种有效的空状态。

## 常见陷阱

- `agy help` 展示的是包装器命令，而不是交互式斜杠命令。
- `agy --version` 是安全的非交互式版本检查；`agy version` 是
  交互式的，在没有真实 TTY 时可能失败。
- 排查失败的第一处位置：`~/.gemini/antigravity-cli/log/cli-*.log`
  （用 `read_file` 读取）。
- 不要把持久化的 JSON 设置与启动时的覆盖项混为一谈。
- `~/.gemini/antigravity-cli/bin/agentapi` 只是 `agy agentapi` 的一层薄包装。
- 在 WSL 上，令牌存储是基于文件的，因此认证问题通常是本地文件 /
  会话状态的问题，而不是仅与浏览器相关的问题。
- 工作区身份可能取决于启动目录以及 `.antigravitycli`
  项目标记文件。

## 验证

确认安装真实可用，全部通过 `terminal` 工具完成（文件用 `read_file` 读取）：

1. `terminal(command="command -v agy")`
2. `terminal(command="agy --version")`
3. `terminal(command="agy help")`
4. `terminal(command="agy plugin list")`
5. 对 `~/.gemini/antigravity-cli/settings.json` 使用 `read_file`
6. 对最新的 `~/.gemini/antigravity-cli/log/cli-*.log` 使用 `read_file`
7. 如有需要，对 `~/.gemini/antigravity-cli/keybindings.json` 使用 `read_file`

## 支持文件

- `references/cli-docs.md` —— 来自入门、使用和功能文档的浓缩笔记。
