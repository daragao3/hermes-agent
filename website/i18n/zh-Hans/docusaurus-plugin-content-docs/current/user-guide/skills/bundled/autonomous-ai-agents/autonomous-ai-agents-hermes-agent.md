---
title: "Hermes Agent —— 使用、配置、主题化、扩展和编排 Hermes Agent"
sidebar_label: "Hermes Agent"
description: "使用、配置、主题化、扩展和编排 Hermes Agent"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Hermes Agent

使用、配置、主题化、扩展和编排 Hermes Agent。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/autonomous-ai-agents/hermes-agent` |
| 版本 | `3.2.0` |
| 作者 | Hermes Agent + Teknium |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `hermes`, `setup`, `configuration`, `multi-agent`, `spawning`, `cli`, `gateway`, `bots`, `bot-mode`, `features`, `themes`, `skins`, `desktop-plugins`, `tui-widgets`, `petdex`, `development` |
| 相关 skill | [`claude-code`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code), [`codex`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex), [`opencode`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-opencode) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时看到的指令内容。
:::

# Hermes Agent

Hermes Agent 是 Nous Research 开发的开源 AI agent 框架，可在终端、原生桌面应用、消息平台和 IDE 中运行。它与 Claude Code（Anthropic）、Codex（OpenAI）和 OpenClaw 同属一类——使用工具调用（tool calling）与系统交互的自主编码和任务执行 agent。Hermes 支持任意 LLM 提供商（OpenRouter、Anthropic、OpenAI、Google、DeepSeek、xAI、本地模型及 20+ 其他提供商），可在 Linux、macOS、Windows 和 WSL 上运行。

Hermes 的差异化特性：

- **通过 skill 自我提升** —— Hermes 通过将可复用流程保存为 skill 来从经验中学习，这些 skill 会加载到未来的会话中。
- **跨会话持久记忆** —— 记住你是谁、你的偏好、环境细节和经验教训。记忆后端可插拔。
- **多平台 gateway** —— 同一个 agent 在 Telegram、Discord、Slack、WhatsApp、iMessage、Signal、Matrix、Teams、Email 及十几个其他平台上运行，具备完整工具访问权限，而不仅仅是聊天。
- **多种界面** —— 同一个 agent 核心驱动 CLI、Ink TUI、原生 Electron 桌面应用、Web 仪表盘，以及面向 IDE（VS Code / Zed / JetBrains）的 ACP 服务器。
- **提供商无关** —— 在工作流中途切换模型和提供商；凭证池自动在多个 API key 之间轮换。
- **Profiles（配置文件）** —— 运行多个独立的 Hermes 实例，各自拥有隔离的配置、会话、skill 和记忆。
- **可扩展、可主题化** —— 插件、MCP 服务器、自定义工具、webhook 触发器、cron 调度、为所有界面换肤的皮肤（skin）、桌面 UI 插件、TUI 小组件，以及宠物吉祥物。

**此 skill 是一个枢纽。** 正文涵盖身份介绍、快速开始、生成/编排以及硬性不变量。其余内容都在参考文件中——**回答之前先加载匹配的参考文件（见下文）**；不要仅凭正文回答细节问题。

**文档：** https://hermes-agent.nousresearch.com/docs/

## 范围与验证 {#scope--verification}

此 skill 是一份简明的操作指南，并非每个 Hermes 功能的完整事实来源。如果某个 Hermes 功能、命令或设置在此处或参考文件中没有提到，不要把这种缺失当作它不存在的证据。在给出否定回答之前，先查看线上仓库和官方文档。

较好的验证目标，按成本从低到高：

- **每个已发布的功能，每项一行：https://hermes-agent.nousresearch.com/docs/llms.txt。** 任何"Hermes 能做 X 吗？"或"我该如何做 X？"的问题都从这里开始——它为整个文档集建立了索引，并链接到给出答案的页面。它在每次构建时由文档树生成，因此永远不会落后于产品。用 `web_extract` 获取，或在 web 工具关闭时用 `curl -s https://hermes-agent.nousresearch.com/docs/llms.txt`。完整文档集的单文件版本位于 `/docs/llms-full.txt`。
- CLI 命令：`hermes --help`、`hermes <command> --help` 以及 `hermes_cli/main.py`
- 源码树：https://github.com/NousResearch/hermes-agent

永远不要凭记忆回答"Hermes 做不到"。Hermes 发布的功能远多于此 skill 正文所描述的，而索引的存在正是为了让否定回答始终可以核查。

## 快速开始 {#quick-start}

```bash
# 安装（shell 安装器——配置 uv、Python、venv 和启动器）
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 交互式聊天（默认界面；设置 display.interface: tui 则改为启动 Ink TUI）
hermes

# 单次查询
hermes chat -q "What is the capital of France?"

# 设置向导  /  选择模型+提供商  /  健康检查
hermes setup
hermes model
hermes doctor

# 其他界面
hermes desktop                 # 启动原生桌面应用（别名：hermes gui）
hermes dashboard               # Web 管理面板 + 内嵌聊天
hermes proxy                   # 由你的 OAuth 提供商支撑的 OpenAI 兼容本地代理
```

## 关键路径 {#key-paths}

```
~/.hermes/config.yaml       Main configuration (settings — never secrets)
~/.hermes/.env              API keys and secrets ONLY (under $HERMES_HOME if set)
$HERMES_HOME/skills/        Installed skills
~/.hermes/skins/            Custom themes (see references/themes.md)
~/.hermes/desktop-plugins/  Desktop app UI plugins (see references/desktop-plugins.md)
~/.hermes/tui-widgets/      TUI widget apps (see references/tui-widgets.md)
~/.hermes/pets/             Installed pet mascots (see references/petdex.md)
~/.hermes/state.db          Canonical session store (SQLite + FTS5)
~/.hermes/sessions/         Gateway routing index, request dumps, *.jsonl transcripts
~/.hermes/logs/             Gateway and error logs
~/.hermes/auth.json         OAuth tokens and credential pools
~/.hermes/hermes-agent/     Source code (if git-installed)
```

Profiles 使用 `~/.hermes/profiles/<name>/`，布局相同。当某个 profile 处于激活状态时，从 `$HERMES_HOME` 解析真实的 home 目录——永远不要硬编码 `~/.hermes`。

## 路由表——按任务加载参考文件 {#routing-table--load-the-reference-for-the-task}

| 用户想要…… | 加载 |
|---|---|
| **以下未列出的任何内容——"Hermes 能做 X 吗？"、"我该如何设置 X？"** | **https://hermes-agent.nousresearch.com/docs/llms.txt** |
| 能聊天、运行例行任务或互相发消息的 bot；Bots 标签页 | 文档：`/user-guide/bot-mode` |
| CLI 命令、子命令、标志、"我该如何运行 X" | `references/cli-reference.md` |
| 会话内斜杠命令 | `references/slash-commands.md` |
| 提供商设置、API key、OAuth | `references/providers-and-models.md` |
| config.yaml 各节、toolset、语音/STT/TTS | `references/configuration.md` |
| AGENTS.md / .hermes.md / CLAUDE.md 项目规则 | `references/project-context-files.md` |
| 密钥脱敏、PII、审批模式、"重置权限" | `references/security-privacy.md` |
| 委派、cron、curator、kanban | `references/background-systems.md` |
| MCP 服务器（添加、目录、`hermes mcp`） | `references/native-mcp.md` |
| Webhook 路由与事件驱动运行 | `references/webhooks.md` |
| 自定义主题/皮肤（"synthwave 主题"、"改掉金色的 ●"） | `references/themes.md` + `templates/skin.yaml` |
| 桌面应用 UI 元素（窗格、小组件、⌘K 命令、页面） | `references/desktop-plugins.md` + `templates/plugin.js` |
| 实时 TUI 面板或模态小组件（行情滚动条、时钟、仪表盘） | `references/tui-widgets.md` + `templates/clock.mjs` |
| 宠物吉祥物——安装、选择、缩放、诊断 | `references/petdex.md` |
| Windows 特有问题（键绑定、WinError 10106、BOM） | `references/windows-quirks.md` |
| 调试：语音、工具缺失、gateway、辅助模型 | `references/troubleshooting.md` |
| 贡献代码：添加工具、斜杠命令、测试 | `references/contributor-guide.md` |
| delegate_task"上限为 N"的报告 | `references/delegate-task-concurrency-diagnosis.md` |
| "应用 X 能使用我的 Nous Portal 订阅/OAuth 吗？" | `references/portal-auth-for-third-party-apps.md` |
| 接入消息平台（Telegram、Discord、Slack、WhatsApp……） | 文档：`/user-guide/messaging` |

上面的参考文件列表并不是功能列表——它是那些需要超出文档页面内容的主题集合。对于 Hermes 发布的其他所有功能，获取 `llms.txt`，它会把问题映射到给出答案的页面。

两条即使不加载参考文件也成立的主题规则：**皮肤由你自己应用**（`hermes config set display.skin <name>`——所有界面会在大约一秒内实时重绘；不要让用户去运行 `/skin`），以及**要调整某一种颜色，编辑当前激活的皮肤**（`hermes skin set <key> <hex>`）——永远不要 fork `default`，那样会丢掉调色板并重置背景。

## 生成额外的 Hermes 实例 {#spawning-additional-hermes-instances}

将额外的 Hermes 进程作为完全独立的子进程运行——拥有独立的会话、工具和环境。

### 何时使用此方式 vs delegate_task {#when-to-use-this-vs-delegate_task}

| | `delegate_task` | 生成 `hermes` 进程 |
|-|-----------------|--------------------------|
| 隔离性 | 独立对话，共享进程 | 完全独立进程 |
| 持续时间 | 分钟级（受父循环限制） | 小时/天 |
| 工具访问 | 父工具的子集 | 完整工具访问 |
| 交互性 | 否 | 是（PTY 模式） |
| 使用场景 | 快速并行子任务 | 长时间自主任务 |

### 单次模式 {#one-shot-mode}

```
terminal(command="hermes chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)

# 长任务后台运行：
terminal(command="hermes chat -q 'Set up CI/CD for ~/myapp'", background=true)
```

### 交互式 PTY 模式（通过 tmux） {#interactive-pty-mode-via-tmux}

Hermes 使用 prompt_toolkit，需要真实终端。使用 tmux 进行交互式生成：

```
# 启动
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'hermes'", timeout=10)

# 等待启动，然后发送消息
terminal(command="sleep 8 && tmux send-keys -t agent1 'Build a FastAPI auth service' Enter", timeout=15)

# 读取输出
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)

# 发送后续消息
terminal(command="tmux send-keys -t agent1 'Add rate limiting middleware' Enter", timeout=5)

# 退出
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### 多 Agent 协调 {#multi-agent-coordination}

```
# Agent A：后端
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Build REST API for user management' Enter", timeout=15)

# Agent B：前端
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Build React dashboard for user management' Enter", timeout=15)

# 检查进度，在两者之间传递上下文
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)
terminal(command="tmux send-keys -t frontend 'Here is the API schema from the backend agent: ...' Enter", timeout=5)
```

### 会话恢复 {#session-resume}

```
# 恢复最近的会话
terminal(command="tmux new-session -d -s resumed 'hermes --continue'", timeout=10)

# 恢复特定会话
terminal(command="tmux new-session -d -s resumed 'hermes --resume 20260225_143052_a1b2c3'", timeout=10)
```

### 提示 {#tips}

- **快速子任务优先使用 `delegate_task`** —— 比生成完整进程开销更小
- **生成编辑代码的 agent 时使用 `-w`（worktree 模式）** —— 防止 git 冲突
- **为单次模式设置超时** —— 复杂任务可能需要 5-10 分钟
- **fire-and-forget 使用 `hermes chat -q`** —— 无需 PTY
- **交互式会话使用 tmux** —— 原始 PTY 模式与 prompt_toolkit 存在 `\r` vs `\n` 问题
- **定时任务使用 `cronjob` 工具而非生成进程** —— 处理投递和重试
- **"delegate_task 上限为 N"的报告** —— 参见 `references/delegate-task-concurrency-diagnosis.md`。Hermes 中存在三条真实的上限路径；如果都没有触发，那就是模型在自我限制，并把它合理化为"运行时有上限"。
- **"$external_app 能使用我的 Nous Portal 订阅 / OAuth 吗？"** —— 参见 `references/portal-auth-for-third-party-apps.md`。引导用户理解三个层面（插件还是应用、Portal 实际暴露了什么、本地代理转发（local-broker-proxy）选项）。

## 界面（快速导览） {#surfaces-quick-orientation}

- **桌面应用**（`hermes desktop` / `hermes gui`）—— 适用于 macOS/Linux/Windows 的原生 Electron 应用：流式聊天、会话列表、Cmd+K 命令面板、拖放文件、原生通知、按 profile 登录远程 gateway。可通过 UI 插件扩展——`references/desktop-plugins.md`。
- **Web 仪表盘**（`hermes dashboard`）—— 完整的管理面板：消息渠道、MCP 目录、webhook、记忆、profile 构建器，外加内嵌的 `hermes --tui` 聊天。受 OAuth/token 门禁保护。
- **Ink TUI**（`hermes --tui` 或 `display.interface: tui`）—— 带有停靠小组件应用的终端 UI——`references/tui-widgets.md`。
- **OpenAI 兼容代理**（`hermes proxy`）—— 一个本地 OpenAI API，由你当前登录的任意 OAuth 提供商支撑。可将 Codex CLI、Aider、Cline 或任何脚本指向它——无需 API key。

## 硬性不变量（无论加载了什么，都不得违反） {#hard-invariants-never-violate-regardless-of-what-you-loaded}

- **永远不要破坏 prompt 缓存** —— 不要在对话中途更改过去的上下文、toolset 或系统 prompt。唯一的例外是上下文压缩。
- **消息角色交替** —— 永远不要连续出现两条 assistant 或两条 user 消息；只有 `tool` 结果可以重复。
- **密钥放在 `.env`，设置放在 `config.yaml`** —— 永远不要让用户把非凭证类设置放进 `.env`。
- **profile 安全的路径** —— 代码中使用 `get_hermes_home()`，在会话中解析路径时使用 `$HERMES_HOME`。
- **永远不要替用户手动编辑 `config.yaml`** —— 使用 `hermes config set KEY VAL`；一个错位的缩进就可能损坏文件并让正在运行的 gateway 崩溃。
