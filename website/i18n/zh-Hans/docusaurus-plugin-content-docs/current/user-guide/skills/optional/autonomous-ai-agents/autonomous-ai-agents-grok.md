---
title: "Grok — 将编码任务委派给 xAI Grok Build CLI（功能、PR）"
sidebar_label: "Grok"
description: "将编码任务委派给 xAI Grok Build CLI（功能、PR）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Grok

将编码任务委派给 xAI Grok Build CLI（功能、PR）。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 使用 `hermes skills install official/autonomous-ai-agents/grok` 安装 |
| 路径 | `optional-skills/autonomous-ai-agents/grok` |
| 版本 | `0.1.0` |
| 作者 | Matt Maximo (MattMaximo), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Coding-Agent`, `Grok`, `xAI`, `Code-Review`, `Refactoring`, `Automation` |
| 相关 skills | [`codex`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex), [`claude-code`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code), [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Grok Build CLI —— Hermes 编排指南

通过 Hermes 终端将编码任务委派给 [Grok Build](https://docs.x.ai/build/overview)（xAI 的
自主编码 agent CLI，即 `grok` 命令）。Grok 可以读取文件、编写代码、运行 shell 命令、
派生子 agent，并管理 git 工作流。它有三种运行方式：交互式 TUI、**无头**（`-p`），以及作为
**ACP agent** 通过 JSON-RPC 运行。

这是 `codex` 和 `claude-code` 的第三位同胞。编排模式几乎相同 —— **单次任务优先用无头
`-p`**，交互式会话用 PTY。

## 使用时机

- 构建功能
- 重构
- PR 审查
- 批量修复 issue
- 任何你原本会拿 Codex / Claude Code 来做、但想用 Grok 的任务

## 前提条件

- **安装（推荐）：** `npm install -g @xai-official/grok`
  - 官方安装脚本 `curl -fsSL https://x.ai/cli/install.sh | bash` 也可用，但 `x.ai`
    主机在某些环境中被 Cloudflare 墙掉。npm 路径完全避开该依赖。
- **认证 —— SuperGrok / X Premium+ 订阅（主要路径）：**
  - 运行一次 `grok login` → 打开浏览器进行 OAuth → 令牌缓存在 `~/.grok/auth.json`。
    这会使用你的 **SuperGrok 或 X Premium+** 订阅（无按令牌计费的 API 账单）。
  - 通过查找 `~/.grok/auth.json` 检查登录状态，或运行一次廉价的无头冒烟测试：
    `grok --no-auto-update -p "Say ok."`
  - 在 TUI 中，`/logout` 登出，`/login`（或重新启动）重新登录。
- **无需 git 仓库** —— 与 Codex 不同，Grok 在 git 目录之外也能正常运行（适合临时/一次性
  任务）。
- **与 Claude Code / AGENTS.md 零配置兼容** —— Grok 会自动读取 `CLAUDE.md`、`.claude/`
  （skills、agents、MCPs、hooks、rules）以及 `AGENTS.md` 家族。现有的项目上下文直接生效。

> **API 密钥回退（并非此用户的默认）：** Grok 也支持设置 `XAI_API_KEY` 环境变量，通过
> `api.x.ai` 按量计费。仅当 `grok login` / SuperGrok 认证不可用时才使用它。订阅路径
> （`grok login`）才是这里预期的设置。

## 两种编排模式

### 模式 1：无头（`-p`）—— 非交互式（推荐）

运行一次性任务，打印结果，然后退出。无 PTY，无需操纵交互式对话框。这是最干净的集成路径
—— 相当于 `claude -p` 和 `codex exec`。

```
terminal(command="grok --no-auto-update -p 'Add a dark mode toggle to settings'", workdir="/path/to/project", timeout=180)
```

在自动化中始终传入 `--no-auto-update` 以跳过后台更新检查。

**何时使用无头：**
- 一次性编码任务（修复 bug、添加功能、重构）
- CI/CD 自动化和脚本
- 用 `--output-format json` 进行结构化输出解析
- 任何不需要多轮对话的任务

### 模式 2：交互式 PTY —— 多轮 TUI 会话

TUI 是一个全屏、鼠标交互式的应用。用 `pty=true` 驱动它。要实现稳健的监控/输入，使用
tmux（与 `claude-code` skill 相同的模式）。

```
# 在 tmux 会话中启动以便用 capture-pane 监控
terminal(command="tmux new-session -d -s grok-work -x 140 -y 40")
terminal(command="tmux send-keys -t grok-work 'cd /path/to/project && grok' Enter")

# 等待启动，然后发送一个任务
terminal(command="sleep 5 && tmux send-keys -t grok-work 'Refactor the auth module to use JWT' Enter")

# 监控进度
terminal(command="sleep 15 && tmux capture-pane -t grok-work -p -S -50")

# 完成后退出
terminal(command="tmux send-keys -t grok-work '/quit' Enter && sleep 1 && tmux kill-session -t grok-work")
```

**无头但内联输出的技巧：** 如果你想要 TUI 风格的输出但不带全屏 alt-screen 接管
（例如为了更干净的日志），加上 `--no-alt-screen`。对于纯自动化，无头 `-p` 仍比 TUI
更干净。

## 无头深入

### 常用标志

| 标志 | 效果 |
|------|--------|
| `-p, --single <PROMPT>` | 发送一个 prompt，无头运行，退出 |
| `-m, --model <MODEL>` | 选择模型 |
| `-s, --session-id <ID>` | 创建或恢复一个命名的无头会话 |
| `-r, --resume <ID>` | 恢复一个现有会话 |
| `-c, --continue` | 继续当前目录中最近的会话 |
| `--cwd <PATH>` | 设置工作目录 |
| `--output-format <FMT>` | `plain`（默认）、`json` 或 `streaming-json` |
| `--always-approve` | 自动批准所有工具执行（`--full-auto` / `--yolo` 的等价物） |
| `--no-alt-screen` | 内联运行，无全屏 TUI 接管 |
| `--no-auto-update` | 跳过后台更新检查（在所有自动化中使用） |

### 输出格式

- `plain` —— 人类可读文本（默认）
- `json` —— 运行结束时输出一个 JSON 对象（干净地解析结果）
- `streaming-json` —— 随事件到达输出以换行分隔的 JSON

```
# 用于解析的结构化结果
terminal(command="grok --no-auto-update -p 'List all TODO comments in src/' --output-format json", workdir="/project", timeout=120)

# 自主构建的自动批准
terminal(command="grok --no-auto-update --always-approve -p 'Refactor the database layer and run the tests'", workdir="/project", timeout=300)
```

### 后台模式（长任务）

```
# 在后台启动无头
terminal(command="grok --no-auto-update --always-approve -p 'Refactor the auth module'", workdir="/project", background=true, notify_on_complete=true)
# 返回 session_id

# 监控
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# 需要时终止
process(action="kill", session_id="<id>")
```

对于交互式（TUI）后台会话，使用 `pty=true` + tmux，并用 `tmux capture-pane` 监控，
与 `claude-code` / `codex` skill 完全一样。

### 会话延续

```
# 启动一个命名会话
terminal(command="grok --no-auto-update -s refactor-db -p 'Start refactoring the database layer' --always-approve", workdir="/project", timeout=240)

# 稍后恢复它
terminal(command="grok --no-auto-update -r refactor-db -p 'Now add connection pooling' --always-approve", workdir="/project", timeout=180)

# 或继续此目录中最近的会话
terminal(command="grok --no-auto-update -c -p 'What did you change last time?'", workdir="/project", timeout=60)
```

## 只读审计 → Markdown 笔记模式

要让 Grok 审查本地产物并返回一份干净的 markdown 笔记（用于 Obsidian 或某个仓库）而不
改动任何东西：

1. 先用 Hermes 工具（`read_file`、`write_file`）准备好稳定的输入文件。只把相关上下文快照
   进一个临时文件，而不是倾倒原始路径。
2. **不带** `--always-approve` 运行 Grok 无头，使其无法自动写入，并要求
   `markdown only, no preamble`。
3. 用 `write_file()` 将 Grok 的标准输出直接保存进目标笔记。

```
grok --no-auto-update -p "Read /tmp/current.md and /tmp/inventory.md. Produce markdown only, no preamble. Output a clean note titled 'Cleanup Review'." --output-format plain
```

**陷阱（与 Claude Code 相同）：** 对于文档重写，一个宽松的"rewrite this"提示可能返回一份
变更摘要而非完整文件。改为：把文件通过管道输入，并要求 `Return ONLY the full revised
markdown document. No intro, no explanation, no code fences. Start immediately with
'# Title'.`。在覆盖目标之前用 `read_file()` 核对前几行。

## PR 审查模式

### 快速审查（无头）

```
terminal(command="cd /path/to/repo && git diff main...feature-branch | grok --no-auto-update -p 'Review this diff for bugs, security issues, and style problems. Be thorough.'", timeout=120)
```

### 克隆到临时目录审查（安全，不改动仓库）

```
terminal(command="REVIEW=$(mktemp -d) && git clone https://github.com/user/repo.git $REVIEW && cd $REVIEW && gh pr checkout 42 && grok --no-auto-update -p 'Review the changes vs origin/main. Check bugs, security, race conditions, missing tests.'", pty=true, timeout=300)
```

### 发布审查

```
terminal(command="gh pr comment 42 --body '<review text>'", workdir="/path/to/repo")
```

## 用 Worktree 并行修复 Issue

```
# 创建 worktree
terminal(command="git worktree add -b fix/issue-78 /tmp/issue-78 main", workdir="~/project")
terminal(command="git worktree add -b fix/issue-99 /tmp/issue-99 main", workdir="~/project")

# 在每个 worktree 中启动 Grok 无头（后台）
terminal(command="grok --no-auto-update --always-approve -p 'Fix issue #78: <description>. Commit when done.'", workdir="/tmp/issue-78", background=true, notify_on_complete=true)
terminal(command="grok --no-auto-update --always-approve -p 'Fix issue #99: <description>. Commit when done.'", workdir="/tmp/issue-99", background=true, notify_on_complete=true)

# 监控
process(action="list")

# 完成后：推送并开 PR
terminal(command="cd /tmp/issue-78 && git push -u origin fix/issue-78")
terminal(command="gh pr create --repo user/repo --head fix/issue-78 --title 'fix: ...' --body '...'")

# 清理
terminal(command="git worktree remove /tmp/issue-78", workdir="~/project")
```

## 有用的子命令与 TUI 命令

| 命令 | 用途 |
|---------|---------|
| `grok` | 启动交互式 TUI |
| `grok -p "query"` | 无头一次性 |
| `grok login` / `grok logout` | 登入 / 登出（SuperGrok / X Premium+ OAuth） |
| `grok inspect` | 显示 Grok 在 cwd 中发现的内容：配置来源、指令、skills、plugins、hooks、MCP 服务器 |
| `grok agent stdio` | 作为 ACP agent 通过 JSON-RPC 运行（用于 IDE/工具集成） |
| `grok update` | 更新 CLI（需要 `x.ai` 主机；在自动化中跳过） |

TUI 斜杠命令（仅交互式）：`/model <name>`、`/always-approve`、`/plan`、`/context`、
`/compact`、`/resume`、`/sessions`、`/fork`、`/usage`、`/quit`。`Shift+Tab` 循环切换会话
模式（包括 Plan 模式，它会阻止除会话计划文件之外的写工具）。

## 配置（`~/.grok/config.toml`）

```toml
[cli]
auto_update = false          # 持久地跳过后台更新检查

[ui]
permission_mode = "ask"      # 或 "always-approve" 以默认跳过工具提示

[models]
default = "grok-build-0.1"
```

把全局偏好放进 `~/.grok/config.toml`（而非项目作用域的 `.grok/config.toml`）。
`permission_mode` 取代旧版的 `approval_mode` / `yolo = true` 键。

## 陷阱与坑

1. **认证受订阅门控。** `grok login` 需要 SuperGrok 或 X Premium+ 订阅。如果登录失败或
   没有 `~/.grok/auth.json`，在回退到 `XAI_API_KEY` 之前先确认订阅处于活跃状态。
2. **不要混淆 Hermes 的 xAI 认证与 `grok` CLI 的认证。** Hermes 的 `x_search` 运行在它
   自己的 xAI OAuth 上；独立的 `grok` CLI 在 `~/.grok/auth.json` 中有一个单独的令牌。一个
   可用的 `x_search` **并不**意味着 `grok` 已登录。
3. **在自动化中始终传入 `--no-auto-update`** —— 否则 Grok 会为更新检查而联网（且
   `x.ai`/`storage.googleapis.com` 可能不可达）。
4. **优先用 npm 安装而非 curl 安装脚本** —— `npm install -g @xai-official/grok` 避开被
   Cloudflare 墙掉的 `x.ai` 主机。
5. **`--always-approve` 是自主构建开关。** 没有它，无头运行可能会停下来等待工具批准提示。
   在只读审查/审计工作中刻意省略它，好让 Grok 无法改动文件。
6. **无头 `-p` 会跳过 TUI 对话框**；TUI 需要 `pty=true`（并用 tmux 监控），与 Claude Code
   一样。
7. **使用 `--no-alt-screen`**，如果你内联运行 TUI 而全屏 alt-screen 接管弄乱了捕获的输出。
8. **无需 git 仓库**，但对于 PR/提交工作流你仍然需要一个 —— 对临时提交任务使用
   `mktemp -d && git init`。
9. 完成后用 `tmux kill-session -t <name>` **清理 tmux 会话**。

## Hermes Agent 的规则

1. **对单个任务优先用无头 `-p`** —— 最干净的集成，通过 `--output-format json` 获得结构化
   输出。
2. **始终设置 `workdir`**（或 `--cwd`），使 Grok 针对正确的项目。
3. 在每次自动化调用中**传入 `--no-auto-update`**。
4. **仅当 Grok 应自主写入时才使用 `--always-approve`**；对于只读审查和审计省略它。
5. 用 `background=true, notify_on_complete=true` **后台运行长任务**，并通过 `process`
   工具监控。
6. **对多轮交互式工作使用 tmux**，并用 `tmux capture-pane -t <session> -p -S -50` 监控。
7. **在依赖认证之前先验证它** —— 检查 `~/.grok/auth.json` 或运行一次廉价的
   `grok -p "Say ok."` 冒烟测试；不要假定 Hermes 的 xAI 认证会带过来。
8. **向用户报告结果** —— 总结 Grok 改动了什么以及还剩什么。
