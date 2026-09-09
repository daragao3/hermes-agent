---
title: "Hermes Agent — 配置、扩展或贡献 Hermes Agent"
sidebar_label: "Hermes Agent"
description: "配置、扩展或贡献 Hermes Agent"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Hermes Agent

配置、扩展或贡献 Hermes Agent。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/autonomous-ai-agents/hermes-agent` |
| 版本 | `2.3.0` |
| 作者 | Hermes Agent + Teknium |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `hermes`, `setup`, `configuration`, `multi-agent`, `spawning`, `cli`, `gateway`, `development` |
| 相关 skill | [`claude-code`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code), [`codex`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex), [`opencode`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-opencode) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时看到的指令内容。
:::

# Hermes Agent

Hermes Agent 是 Nous Research 开发的开源 AI agent 框架，可在终端、原生桌面应用、消息平台和 IDE 中运行。它与 Claude Code（Anthropic）、Codex（OpenAI）和 OpenClaw 同属一类——使用工具调用（tool calling）与系统交互的自主编码和任务执行 agent。Hermes 支持任意 LLM 提供商（OpenRouter、Anthropic、OpenAI、Google、DeepSeek、xAI、本地模型及 20+ 其他提供商），可在 Linux、macOS、Windows 和 WSL 上运行。

Hermes 的差异化特性：

- **通过 skill 自我提升** — Hermes 通过将可复用流程保存为 skill 来从经验中学习。当它解决复杂问题、发现工作流或被纠正时，可以将该知识持久化为 skill 文档，加载到未来的会话中。skill 随时间积累，使 agent 在你的特定任务和环境中表现越来越好。
- **跨会话持久记忆** — 记住你是谁、你的偏好、环境细节和经验教训。可插拔的记忆后端（内置、Honcho、Mem0 等）让你选择记忆的工作方式。
- **多平台 gateway** — 同一个 agent 在 Telegram、Discord、Slack、WhatsApp、iMessage、Signal、Matrix、Teams、Email 及十余个其他平台上运行，具备完整工具访问权限，而不仅仅是聊天。
- **多种交互界面** — 同一个 agent 内核驱动 CLI、Ink TUI、原生 Electron 桌面应用、Web 仪表盘，以及面向 IDE（VS Code / Zed / JetBrains）的 ACP 服务器。
- **提供商无关** — 在工作流中途切换模型和提供商，无需更改其他任何内容。凭证池自动轮换多个 API key。
- **Profiles（配置文件）** — 运行多个独立的 Hermes 实例，各自拥有隔离的配置、会话、skill 和记忆。
- **可扩展** — 插件、MCP 服务器、自定义工具、webhook 触发器、cron 调度以及完整的 Python 生态系统。

人们将 Hermes 用于软件开发、研究、系统管理、数据分析、内容创作、家庭自动化，以及任何受益于具有持久上下文和完整系统访问权限的 AI agent 的场景。

**此 skill 帮助你高效使用 Hermes Agent** — 包括设置、配置功能、生成额外的 agent 实例、排查问题、找到正确的命令和设置，以及在需要扩展或贡献时理解系统的工作原理。

**文档：** https://hermes-agent.nousresearch.com/docs/

## 范围与核实

此 skill 是一份精简的操作指南，并非涵盖每个 Hermes 功能的完整事实来源。如果某个 Hermes 功能、命令或设置没有在这里出现，不要把这种缺失当作它不存在的证据。在给出否定回答之前，请先核对实际仓库和官方文档。

合适的核实途径：

- CLI 命令：`hermes --help`、`hermes <command> --help`，以及 `hermes_cli/main.py`
- 用户文档：https://hermes-agent.nousresearch.com/docs/
- 源码树：https://github.com/NousResearch/hermes-agent

## 快速开始

```bash
# 安装（shell 安装器——负责配置 uv、Python、venv 和启动器）
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 或通过 PyPI 安装（附带 TUI bundle 和 shell 启动器）
pip install hermes-agent       # 或：uv pip install hermes-agent

# 交互式聊天（默认界面；设置 display.interface: tui 可改为启动 Ink TUI）
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

---

## CLI 参考

### 全局标志

```
hermes [flags] [command]

  --version, -V             Show version
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --pass-session-id         Include session ID in system prompt
```

无子命令时默认为 `chat`。

### Chat

```
hermes chat [flags]
  -q, --query TEXT          Single query, non-interactive
  -m, --model MODEL         Model (e.g. anthropic/claude-sonnet-4)
  -t, --toolsets LIST       Comma-separated toolsets
  --provider PROVIDER       Force provider (openrouter, anthropic, nous, etc.)
  -v, --verbose             Verbose output
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --source TAG              Session source tag (default: cli)
```

### 配置

```
hermes setup [section]      Interactive wizard (model|terminal|gateway|tools|agent)
hermes model                Interactive model/provider picker
hermes config               View current config
hermes config edit          Open config.yaml in $EDITOR
hermes config set KEY VAL   Set a config value
hermes config path          Print config.yaml path
hermes config env-path      Print .env path
hermes config check         Check for missing/outdated config
hermes config migrate       Update config with new options
hermes doctor [--fix]       Check dependencies and config
hermes status [--all]       Show component status
```

凭据（OAuth + API key，支持池化）统一在 `hermes auth` 下管理——参见下方"凭据与凭证池"一节。

### 工具与 Skill

```
hermes tools                Interactive tool enable/disable (curses UI)
hermes tools list           Show all tools and status
hermes tools enable NAME    Enable a toolset
hermes tools disable NAME   Disable a toolset

hermes skills list          List installed skills
hermes skills search QUERY  Search the skills hub
hermes skills install ID    Install a skill (ID can be a hub identifier OR a direct https://…/SKILL.md URL; pass --name to override when frontmatter has no name)
hermes skills inspect ID    Preview without installing
hermes skills config        Enable/disable skills per platform
hermes skills check         Check for updates
hermes skills update        Update outdated skills
hermes skills uninstall N   Remove a hub skill
hermes skills publish PATH  Publish to registry
hermes skills browse        Browse all available skills
hermes skills tap add REPO  Add a GitHub repo as skill source
```

### MCP 服务器

```
hermes mcp serve            Run Hermes as an MCP server
hermes mcp add NAME         Add an MCP server (--url or --command)
hermes mcp remove NAME      Remove an MCP server
hermes mcp list             List configured servers
hermes mcp test NAME        Test connection
hermes mcp configure NAME   Toggle tool selection
```

内置 MCP 客户端如何连接服务器（stdio/HTTP）、自动发现
其工具并将它们暴露为一等工具，以及目录安装
（`hermes mcp install <name>`）：`skill_view(name="hermes-agent", file_path="references/native-mcp.md")`。

### Gateway（消息平台）

```
hermes gateway run          Start gateway foreground
hermes gateway install      Install as background service
hermes gateway start/stop   Control the service
hermes gateway restart      Restart the service
hermes gateway status       Check status
hermes gateway setup        Configure platforms
```

支持的平台（20+）：Telegram、Discord、Slack、WhatsApp（Baileys 桥接 + 官方 Business Cloud API）、iMessage（Photon——`hermes photon setup`，BlueBubbles 的继任者，无需 Mac 中继）、Signal、Email、SMS、Matrix、Mattermost、Microsoft Teams、LINE、SimpleX、ntfy、Google Chat、Home Assistant、DingTalk、Feishu、WeCom、Weixin（WeChat）、Raft（agent 网络）、API Server、Webhooks。Open WebUI 通过 API Server 适配器连接。大多数适配器位于 `plugins/platforms/` 之下，因此新增平台无需改动核心。

平台文档：https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### 会话

```
hermes sessions list        List recent sessions
hermes sessions browse      Interactive picker
hermes sessions export OUT  Export to JSONL
hermes sessions rename ID T Rename a session
hermes sessions delete ID   Delete a session
hermes sessions prune       Clean up old sessions (--older-than N days)
hermes sessions stats       Session store statistics
```

### Cron 任务

```
hermes cron list            List jobs (--all for disabled)
hermes cron create SCHED    Create: '30m', 'every 2h', '0 9 * * *'
hermes cron edit ID         Edit schedule, prompt, delivery
hermes cron pause/resume ID Control job state
hermes cron run ID          Trigger on next tick
hermes cron remove ID       Delete a job
hermes cron status          Scheduler status
```

### Webhook

```
hermes webhook subscribe N  Create route at /webhooks/<name>
hermes webhook list         List subscriptions
hermes webhook remove NAME  Remove a subscription
hermes webhook test NAME    Send a test POST
```

完整的设置、路由配置、payload 模板化以及事件驱动的 agent 运行
模式：`skill_view(name="hermes-agent", file_path="references/webhooks.md")`。

### Profiles

```
hermes profile list         List all profiles
hermes profile create NAME  Create (--clone, --clone-all, --clone-from)
hermes profile use NAME     Set sticky default
hermes profile delete NAME  Delete a profile
hermes profile show NAME    Show details
hermes profile alias NAME   Manage wrapper scripts
hermes profile rename A B   Rename a profile
hermes profile export NAME  Export to tar.gz
hermes profile import FILE  Import from archive
```

### 凭据与凭证池

```
hermes auth                 Interactive credential manager
hermes auth add [PROVIDER]  Add OAuth or API-key credential
                            (e.g. nous, openai-codex, qwen-oauth, anthropic)
hermes auth list [PROVIDER] List pooled credentials
hermes auth remove P INDEX  Remove by provider + index
hermes auth reset PROVIDER  Clear exhaustion status
```

同一提供商下的多个凭据会组成一个凭证池，自动轮换并跳过已耗尽的 key。

### 其他

```
hermes insights [--days N]  Usage analytics
hermes update               Update to latest version
hermes desktop / gui        Launch the native desktop app
hermes dashboard            Web admin panel + embedded chat
hermes proxy                OpenAI-compatible local proxy backed by an OAuth provider
hermes portal               Quick setup / sign in via Nous Portal
hermes kanban <verb>        Multi-agent work-queue board (init/create/list/show/assign/…)
hermes pairing list/approve/revoke  DM authorization
hermes plugins list/install/remove  Plugin management
hermes secrets bitwarden …  External secret store (Bitwarden Secrets Manager)
hermes memory setup/status/off  Memory provider config
hermes send                 Send a one-off message through a gateway platform
hermes completion bash|zsh  Shell completions
hermes acp                  ACP server (IDE integration)
hermes claw migrate         Migrate from OpenClaw
hermes uninstall            Uninstall Hermes
```

完整且权威的命令清单请运行 `hermes --help`（以及 `hermes <command> --help`）。由插件和提供商提供的子命令（例如用于 iMessage 的 `hermes photon setup`）只有在其插件安装/启用后才会出现。

---

## 斜杠命令（会话内）

在交互式聊天会话中输入这些命令。新命令会不定期上线；如果以下内容看起来过时，请在会话内运行 `/help` 获取权威列表，或查看[实时斜杠命令参考](https://hermes-agent.nousresearch.com/docs/reference/slash-commands)。命令注册表的权威来源是 `hermes_cli/commands.py` — 每个消费方（自动补全、Telegram 菜单、Slack 映射、`/help`）均从中派生。

### 会话控制
```
/new (/reset)        Fresh session
/clear               Clear screen + new session (CLI)
/retry               Resend last message
/undo                Remove last exchange
/title [name]        Name the session
/compress            Manually compress context
/stop                Kill background processes
/rollback [N]        Restore filesystem checkpoint
/snapshot [sub]      Create or restore state snapshots of Hermes config/state (CLI)
/background <prompt> Run prompt in background
/queue <prompt>      Queue for next turn
/steer <prompt>      Inject a message after the next tool call without interrupting
/agents (/tasks)     Show active agents and running tasks
/resume [name]       Resume a named session
/goal [text|sub]     Set a standing goal Hermes works on across turns until achieved
                     (subcommands: status, pause, resume, clear)
/redraw              Force a full UI repaint (CLI)
```

### 配置
```
/config              Show config (CLI)
/model [name]        Show or change model
/personality [name]  Set personality
/reasoning [level]   Set reasoning (none|minimal|low|medium|high|xhigh|max|ultra|show|hide)
/verbose             Cycle: off → new → all → verbose
/voice [on|off|tts]  Voice mode
/yolo                Toggle approval bypass
/busy [sub]          Control what Enter does while Hermes is working (CLI)
                     (subcommands: queue, steer, interrupt, status)
/indicator [style]   Pick the TUI busy-indicator style (CLI)
                     (styles: kaomoji, emoji, unicode, ascii)
/footer [on|off]     Toggle gateway runtime-metadata footer on final replies
/skin [name]         Change theme (CLI)
/statusbar           Toggle status bar (CLI)
```

### 工具与 Skill
```
/tools               Manage tools (CLI)
/toolsets            List toolsets (CLI)
/skills              Search/install skills (CLI)
/skill <name>        Load a skill into session
/reload-skills       Re-scan ~/.hermes/skills/ for added/removed skills
/reload              Reload .env variables into the running session (CLI)
/reload-mcp          Reload MCP servers
/cron                Manage cron jobs (CLI)
/curator [sub]       Background skill maintenance (status, run, pin, archive, …)
/kanban [sub]        Multi-profile collaboration board (tasks, links, comments)
/plugins             List plugins (CLI)
```

### Gateway
```
/approve             Approve a pending command (gateway)
/deny                Deny a pending command (gateway)
/restart             Restart gateway (gateway)
/sethome             Set current chat as home channel (gateway)
/update              Update Hermes to latest (gateway)
/topic [sub]         Enable or inspect Telegram DM topic sessions (gateway)
/platforms (/gateway) Show platform connection status (gateway)
```

### 实用工具
```
/branch (/fork)      Branch the current session
/handoff <platform>  Hand the live session off to a messaging platform (CLI)
/fast                Toggle priority/fast processing
/browser             Open CDP browser connection
/history             Show conversation history (CLI)
/save                Save conversation to file (CLI)
/copy [N]            Copy the last assistant response to clipboard (CLI)
/paste               Attach clipboard image (CLI)
/image               Attach local image file (CLI)
```

### 信息
```
/help                Show commands
/commands [page]     Browse all commands (gateway)
/usage               Token usage
/insights [days]     Usage analytics
/status              Session info (gateway)
/profile             Active profile info
/debug               Upload debug report (system info + logs) and get shareable links
```

### 退出
```
/quit (/exit, /q)    Exit CLI
```

---

## 关键路径与配置

```
~/.hermes/config.yaml       Main configuration
~/.hermes/.env              API keys and secrets (under $HERMES_HOME if set)
$HERMES_HOME/skills/        Installed skills
~/.hermes/sessions/         Session transcripts
~/.hermes/logs/             Gateway and error logs
~/.hermes/auth.json         OAuth tokens and credential pools
~/.hermes/hermes-agent/     Source code (if git-installed)
```

Profiles 使用 `~/.hermes/profiles/<name>/`，布局相同。

### 配置节

使用 `hermes config edit` 或 `hermes config set section.key value` 编辑。

| 节 | 键选项 |
|---------|-------------|
| `model` | `default`, `provider`, `base_url`, `api_key`, `context_length` |
| `agent` | `max_turns` (90), `tool_use_enforcement` |
| `terminal` | `backend` (local/docker/ssh/modal), `cwd`, `timeout` (180) |
| `compression` | `enabled`, `threshold` (0.50), `target_ratio` (0.20) |
| `display` | `skin`, `interface` (cli/tui), `tool_progress`, `show_reasoning`, `show_cost`, `language` |
| `stt` | `enabled`, `provider` (local/groq/openai/mistral) |
| `tts` | `provider` (edge/elevenlabs/openai/minimax/mistral/neutts) |
| `memory` | `memory_enabled`, `user_profile_enabled`, `provider` |
| `security` | `tirith_enabled`, `website_blocklist` |
| `delegation` | `model`, `provider`, `base_url`, `api_key`, `max_iterations` (50), `reasoning_effort` |
| `checkpoints` | `enabled`, `max_snapshots` (50) |
| `curator` | `enabled`, `consolidate`（false——需显式开启的辅助模型 skill 合并）, `interval_hours`, `stale_after_days` |

完整配置参考：https://hermes-agent.nousresearch.com/docs/user-guide/configuration

### 提供商

支持 20+ 个提供商。通过 `hermes model` 或 `hermes setup` 设置。

| 提供商 | 认证方式 | Key 环境变量 |
|----------|------|-------------|
| OpenRouter | API key | `OPENROUTER_API_KEY` |
| Anthropic | API key | `ANTHROPIC_API_KEY` |
| Nous Portal | OAuth | `hermes auth` |
| OpenAI Codex | OAuth | `hermes auth` |
| GitHub Copilot | Token | `COPILOT_GITHUB_TOKEN` |
| Google Gemini | API key | `GOOGLE_API_KEY` 或 `GEMINI_API_KEY` |
| DeepSeek | API key | `DEEPSEEK_API_KEY` |
| xAI / Grok | API key | `XAI_API_KEY` |
| Hugging Face | Token | `HF_TOKEN` |
| Z.AI / GLM | API key | `GLM_API_KEY` |
| MiniMax | API key | `MINIMAX_API_KEY` |
| MiniMax CN | API key | `MINIMAX_CN_API_KEY` |
| Kimi / Moonshot | API key | `KIMI_API_KEY` |
| Alibaba / DashScope | API key | `DASHSCOPE_API_KEY` |
| Xiaomi MiMo | API key | `XIAOMI_API_KEY` |
| Kilo Code | API key | `KILOCODE_API_KEY` |
| OpenCode Zen | API key | `OPENCODE_ZEN_API_KEY` |
| OpenCode Go | API key | `OPENCODE_GO_API_KEY` |
| Qwen OAuth | OAuth | `hermes auth add qwen-oauth` |
| 自定义端点 | 配置 | `config.yaml` 中的 `model.base_url` + `model.api_key` |
| GitHub Copilot ACP | 外部 | `COPILOT_CLI_PATH` 或 Copilot CLI |

完整提供商文档：https://hermes-agent.nousresearch.com/docs/integrations/providers

### Toolset

通过 `hermes tools`（交互式）或 `hermes tools enable/disable NAME` 启用/禁用。

| Toolset | 提供的功能 |
|---------|-----------------|
| `web` | 网页搜索和内容提取 |
| `search` | 仅网页搜索（`web` 的子集） |
| `browser` | 浏览器自动化（Browserbase、Camofox 或本地 Chromium） |
| `terminal` | Shell 命令和进程管理 |
| `file` | 文件读/写/搜索/补丁 |
| `code_execution` | 沙箱 Python 执行 |
| `vision` | 图像分析 |
| `image_gen` | AI 图像生成与图生图编辑 |
| `video` | 视频分析（`video_analyze`）与生成 |
| `x_search` | 一等公民的 X（Twitter）搜索（X OAuth 或 API key） |
| `tts` | 文字转语音 |
| `skills` | Skill 浏览和管理 |
| `memory` | 跨会话持久记忆 |
| `session_search` | 搜索历史对话 |
| `delegation` | 子 agent 任务委派 |
| `cronjob` | 定时任务管理 |
| `clarify` | 向用户提问澄清 |
| `messaging` | 跨平台消息发送 |
| `todo` | 会话内任务规划和跟踪 |
| `kanban` | 多 agent 工作队列工具（仅限 worker） |
| `debugging` | 额外的内省/调试工具（默认关闭） |
| `safe` | 最小化、低风险工具集，用于受限会话 |
| `spotify` | Spotify 播放和播放列表控制 |
| `homeassistant` | 智能家居控制（默认关闭） |
| `discord` | Discord 集成工具 |
| `discord_admin` | Discord 管理/审核工具 |
| `feishu_doc` | 飞书文档工具 |
| `feishu_drive` | 飞书云盘工具 |
| `yuanbao` | 元宝集成工具 |
| `rl` | 强化学习工具（默认关闭） |

完整枚举位于 `toolsets.py` 的 `TOOLSETS` 字典中；`_HERMES_CORE_TOOLS` 是大多数平台继承的默认工具包。

工具变更在 `/reset`（新会话）后生效。为保留 prompt 缓存，变更**不会**在对话中途生效。

---

## 项目上下文文件

Hermes 会读取工作目录中的上下文文件，把项目级指令注入系统 prompt。发现顺序为**首个匹配者胜出**——每个会话只加载一个项目上下文来源。

| 文件（按优先级排列） | 发现方式 | 适用场景 |
|---|---|---|
| `.hermes.md` / `HERMES.md` | 向上遍历父目录直到 git 根目录为止 | 你想要分层的项目规则（根目录 + 各子包覆盖） |
| `AGENTS.md` / `agents.md` | **仅当前目录**——子目录和父目录中的副本会被忽略 | 你想要可移植的 agent 指令，在 Hermes、Claude Code、Codex 等中表现一致 |
| `CLAUDE.md` / `claude.md` | 仅当前目录 | 同 AGENTS.md，Claude 风格 |
| `.cursorrules` / `.cursor/rules/*.mdc` | 仅当前目录 | 从 Cursor 迁移 |

`SOUL.md`（位于 `$HERMES_HOME`）是独立的，只要存在就总会加载——它设定 agent 的身份，而不是项目规则。

### 选择合适的文件

- 当你需要位于当前目录之上（根目录 + 子树）的 Hermes 专属行为，或希望规则从父目录继承时，**使用 `.hermes.md`**。父目录遍历在 git 根目录处停止，因此放在 home 目录下的 `.hermes.md` 不会渗漏到每个项目里（git 仓库的根目录就是边界）。
- 当同一个项目还会被其他 agent（Codex、Claude Code、OpenCode）处理时，**使用 `AGENTS.md`**。这些工具都有各自关于 `AGENTS.md` 的约定，而"仅当前目录"的契约让这个文件保持可移植。
- **不要把项目规则放在 `~/.hermes/AGENTS.md`**（或任何 home 级位置）。当 Hermes 以该目录作为当前目录运行时，这个文件确实会加载——但也仅限于那一个目录。跨项目的上下文请使用 `SOUL.md`（位于 `$HERMES_HOME`，仅用于身份）或通过 `hermes skills install` 安装一个 skill。

### 大小与截断

每个上下文文件上限为 20,000 个字符。超出部分会被**首尾保留**式截断（丢弃中间内容，并留下 `[...truncated...]` 标记）。对于篇幅较大的项目规则，优先拆分成多个 skill，而不是把内容硬塞进一个文件。

### 安全

所有上下文文件在进入系统 prompt 之前都会经过威胁模式扫描器。匹配到 prompt 注入或 promptware 的内容会被替换为 `[BLOCKED: ...]` 占位符。这意味着含有明显注入企图的 `AGENTS.md` 不会到达模型——扫描器拦截的是内容而不是整个文件，因此文件的其余部分仍会加载。

### 为单次会话禁用

`hermes --ignore-rules` 会跳过所有项目上下文文件（`.hermes.md`、`AGENTS.md`、`CLAUDE.md`、`.cursorrules`）**以及** `SOUL.md` 身份的自动注入，同时跳过用户配置、插件和 MCP 服务器。用它来判断问题出在你的配置上还是 Hermes 本身。

### 示例：一个小型 `.hermes.md`

```markdown
# My Project

Hermes: when working in this repo, follow these rules.

## Build
- Always run `make test` before declaring a change done.
- Use `uv run` for Python, not `pip install`.

## Style
- Prefer `pathlib.Path` over `os.path`.
- No `print()` in production code — use the `logger`.
```

位于 `/home/me/projects/myrepo/.hermes.md` 的该文件，会在 Hermes 于 `/home/me/projects/myrepo` 的任意子目录中运行时自动加载，但在 `/home/me/other-project` 中运行时不会加载。

## 安全与隐私开关

常见的"为什么 Hermes 对我的输出/工具调用/命令做了 X？"开关——以及更改它们的确切命令。其中大多数需要新会话（聊天中的 `/reset`，或启动新的 `hermes` 调用），因为它们在启动时只读取一次。

### 工具输出中的密钥脱敏

密钥脱敏**默认开启** — 工具输出（终端 stdout、`read_file`、网页内容、子 agent 摘要等）在进入对话上下文和日志之前，会被扫描是否包含形似 API key、token 和密钥的字符串。日常使用请保持启用：

```bash
hermes config set security.redact_secrets true       # 保持全局启用
```

**需要重启。** `security.redact_secrets` 在导入时快照 — 在会话中途切换（例如通过工具调用执行 `export HERMES_REDACT_SECRETS=false`）对正在运行的进程**不会**生效。告知用户从终端在配置中更改它，然后启动新会话。这是有意为之——防止 LLM 在任务中途自行切换该开关。

仅当你确实需要原始的、形似凭据的字符串来做调试或开发脱敏器时才禁用：
```bash
hermes config set security.redact_secrets false
```

### Gateway 消息中的 PII 脱敏

与密钥脱敏分开。启用后，gateway 在上下文到达模型之前对用户 ID 进行哈希处理并从会话上下文中去除电话号码：

```bash
hermes config set privacy.redact_pii true    # 启用
hermes config set privacy.redact_pii false   # 禁用（默认）
```

### 命令审批提示

默认情况下（`approvals.mode: smart`），Hermes 会让辅助 LLM 评估被标记为破坏性的 shell 命令（`rm -rf`、`git reset --hard` 等）。模式如下：

- `smart` — 低风险命令仅批准一次，高风险命令拒绝，不确定时提示（默认）
- `manual` — 始终提示
- `off` — 跳过所有审批提示（等同于 `--yolo`）

```bash
hermes config set approvals.mode smart       # 推荐的折中方案
hermes config set approvals.mode off         # 绕过一切（不推荐）
```

单次调用绕过（不更改配置）：
- `hermes --yolo …`
- `export HERMES_YOLO_MODE=1`

注意：YOLO / `approvals.mode: off` **不会**关闭密钥脱敏。两者相互独立。

### Shell hook 允许列表

某些 shell hook 集成在触发前需要明确加入允许列表。通过 `~/.hermes/shell-hooks-allowlist.json` 管理——在 hook 首次尝试运行时以交互方式提示。

### 禁用 web/browser/image-gen 工具

要完全阻止模型访问网络或媒体工具，打开 `hermes tools` 并按平台切换。在下次会话（`/reset`）后生效。参见上方的工具与 Skill 部分。

---

## 语音与转录

### STT（语音 → 文字）

来自消息平台的语音消息会自动转录。

提供商优先级（自动检测）：
1. **本地 faster-whisper** — 免费，无需 API key：`pip install faster-whisper`
2. **Groq Whisper** — 免费套餐：设置 `GROQ_API_KEY`
3. **OpenAI Whisper** — 付费：设置 `VOICE_TOOLS_OPENAI_KEY`
4. **Mistral Voxtral** — 设置 `MISTRAL_API_KEY`

配置：
```yaml
stt:
  enabled: true
  provider: local        # local, groq, openai, mistral
  local:
    model: base          # tiny, base, small, medium, large-v3
```

### TTS（文字 → 语音）

| 提供商 | 环境变量 | 免费？ |
|----------|---------|-------|
| Edge TTS | 无 | 是（默认） |
| ElevenLabs | `ELEVENLABS_API_KEY` | 免费套餐 |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | 付费 |
| MiniMax | `MINIMAX_API_KEY` | 付费 |
| Mistral (Voxtral) | `MISTRAL_API_KEY` | 付费 |
| NeuTTS（本地） | 无（`pip install neutts[all]` + `espeak-ng`） | 免费 |

语音命令：`/voice on`（语音对语音）、`/voice tts`（始终语音）、`/voice off`。

---

## 生成额外的 Hermes 实例

将额外的 Hermes 进程作为完全独立的子进程运行——拥有独立的会话、工具和环境。

### 何时使用此方式 vs delegate_task

| | `delegate_task` | 生成 `hermes` 进程 |
|-|-----------------|--------------------------|
| 隔离性 | 独立对话，共享进程 | 完全独立进程 |
| 持续时间 | 分钟级（受父循环限制） | 小时/天 |
| 工具访问 | 父工具的子集 | 完整工具访问 |
| 交互性 | 否 | 是（PTY 模式） |
| 使用场景 | 快速并行子任务 | 长时间自主任务 |

### 单次模式

```
terminal(command="hermes chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)

# 长任务后台运行：
terminal(command="hermes chat -q 'Set up CI/CD for ~/myapp'", background=true)
```

### 交互式 PTY 模式（通过 tmux）

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

### 多 Agent 协调

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

### 会话恢复

```
# 恢复最近的会话
terminal(command="tmux new-session -d -s resumed 'hermes --continue'", timeout=10)

# 恢复特定会话
terminal(command="tmux new-session -d -s resumed 'hermes --resume 20260225_143052_a1b2c3'", timeout=10)
```

### 提示

- **快速子任务优先使用 `delegate_task`** — 比生成完整进程开销更小
- **生成编辑代码的 agent 时使用 `-w`（worktree 模式）** — 防止 git 冲突
- **为单次模式设置超时** — 复杂任务可能需要 5-10 分钟
- **fire-and-forget 使用 `hermes chat -q`** — 无需 PTY
- **交互式会话使用 tmux** — 原始 PTY 模式与 prompt_toolkit 存在 `\r` vs `\n` 问题
- **定时任务使用 `cronjob` 工具而非生成进程** — 处理投递和重试

---

## 持久化与后台系统

四个系统与主对话循环并行运行。此处为快速参考；完整开发者说明位于 `AGENTS.md`，面向用户的文档位于 `website/docs/user-guide/features/`。

### 委派（`delegate_task`）

生成一个拥有隔离上下文和终端会话的子 agent。

- **单个：** `delegate_task(goal, context)`。
- **批量：** `delegate_task(tasks=[{goal, ...}, ...])` 并行运行子任务，上限由 `delegation.max_concurrent_children`（默认 3）控制。
- **后台：** `delegate_task(background=true)` 立即返回一个句柄并让父 agent 的循环继续；子 agent 的结果会在完成时作为新的一轮重新进入对话。
- **角色：** `leaf`（默认；不能再委派）vs `orchestrator`（可以生成自己的 worker，受 `delegation.max_spawn_depth` 限制）。
- **非持久化。** 后台运行的子 agent 仍然是进程内的——如果父进程退出，子 agent 就会丢失。对于必须在进程之外继续存活的工作，使用 `cronjob` 或 `terminal(background=True, notify_on_complete=True)`。

配置：`config.yaml` 中的 `delegation.*`。

### Cron（定时任务）

持久化调度器——`cron/jobs.py` + `cron/scheduler.py`。通过 `cronjob` 工具、`hermes cron` CLI（`list`、`add`、`edit`、`pause`、`resume`、`run`、`remove`）或 `/cron` 斜杠命令驱动。

- **调度格式：** 持续时间（`"30m"`、`"2h"`）、"every" 短语（`"every monday 9am"`）、5 字段 cron（`"0 9 * * *"`）或 ISO 时间戳。
- **每任务选项：** `skills`、`model`/`provider` 覆盖、`script`（预运行数据收集；`no_agent=True` 使脚本成为整个任务）、`context_from`（将任务 A 的输出链接到任务 B）、`workdir`（在特定目录中运行，加载其 `AGENTS.md` / `CLAUDE.md`）、多平台投递。
- **不变量：** 每次运行 3 分钟硬中断，`.tick.lock` 文件防止跨进程重复 tick，cron 会话默认传递 `skip_memory=True`，cron 投递使用页眉/页脚框架而非镜像到目标 gateway 会话（保持角色交替完整）。

用户文档：https://hermes-agent.nousresearch.com/docs/user-guide/features/cron

### Curator（skill 生命周期）

agent 创建的 skill 的后台维护。跟踪使用情况，将闲置 skill 标记为过时，归档过时的 skill，保留运行前的 tar.gz 备份以防数据丢失。

- **CLI：** `hermes curator <verb>` — `status`、`run`、`pause`、`resume`、`pin`、`unpin`、`archive`、`restore`、`prune`、`backup`、`rollback`。
- **斜杠命令：** `/curator <subcommand>` 与 CLI 对应。
- **范围：** 仅处理 `created_by: "agent"` 来源的 skill。内置和 hub 安装的 skill 不在范围内。**从不删除** — 最具破坏性的操作是归档。已固定的 skill 不受任何自动转换和任何 LLM 审查的影响。
- **成本：** 确定性的闲置/裁剪扫描是免费的。使用辅助模型"把重叠的 skill 合并为伞形 skill"的过程**默认关闭**——通过 `curator.consolidate: true` 或 `hermes curator run --consolidate` 显式开启。日常的后台维护不消耗 token。
- **遥测：** `~/.hermes/skills/.usage.json` 中的 sidecar 保存每个 skill 的 `use_count`、`view_count`、`patch_count`、`last_activity_at`、`state`、`pinned`。

配置：`curator.*`（`enabled`、`interval_hours`、`min_idle_hours`、`stale_after_days`、`archive_after_days`、`backup.*`）。
用户文档：https://hermes-agent.nousresearch.com/docs/user-guide/features/curator

### Kanban（多 agent 工作队列）

用于多 profile/多 worker 协作的持久化 SQLite 看板（kanban）。用户通过 `hermes kanban <verb>` 驱动；调度器生成的 worker 看到由 `HERMES_KANBAN_TASK` 控制的专注 `kanban_*` toolset，orchestrator profile 可以选择加入更广泛的 `kanban` toolset。普通会话除非配置，否则没有任何 `kanban_*` schema 占用。

- **CLI 动词（常用）：** `init`、`create`、`list`（别名 `ls`）、`show`、`assign`、`link`、`unlink`、`comment`、`complete`、`block`、`unblock`、`archive`、`tail`。不常用：`watch`、`stats`、`runs`、`log`、`dispatch`、`daemon`、`gc`。
- **Worker/orchestrator toolset：** `kanban_show`、`kanban_complete`、`kanban_block`、`kanban_heartbeat`、`kanban_comment`、`kanban_create`、`kanban_link`；在调度器生成的任务之外显式启用 `kanban` toolset 的 profile 还可获得 `kanban_list` 和 `kanban_unblock` 用于看板路由。
- **调度器** 默认在 gateway 内运行（`kanban.dispatch_in_gateway: true`）——回收过期认领、推进就绪任务、原子认领、生成已分配的 profile。在 `failure_limit` 次连续生成失败后自动阻塞任务（默认 2；可通过 `kanban.failure_limit` 或按任务的 `max_retries` 配置）。
- **隔离：** 看板是硬边界（worker 在环境中固定 `HERMES_KANBAN_BOARD`）；租户是看板内用于工作区路径和记忆键隔离的软命名空间。

用户文档：https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban

---

## 交互界面与其他能力

除了 CLI 和 gateway，还有几点值得了解：

- **桌面应用**（`hermes desktop` / `hermes gui`）——面向 macOS/Linux/Windows 的
  原生 Electron 应用：流式聊天、会话列表、拖放与剪贴板粘贴文件、Cmd+K 命令面板、
  状态栏模型选择器、可重新绑定的快捷键、原生通知、子 agent 实时观察窗口、
  VS Code Marketplace 主题，以及按 profile 的远程 gateway 登录（OAuth 或用户名/密码），
  让轻量的本地 GUI 可以驱动一个重量级的远程 agent。
- **Web 仪表盘**（`hermes dashboard`）——完整的管理面板：在浏览器中配置每个消息渠道、
  MCP 目录、webhook/hook、记忆，以及完整的 profile 构建器（模型 + skill + MCP），
  另外还内嵌了 `hermes --tui` 聊天。由 OAuth/token 网关保护。
- **OpenAI 兼容代理**（`hermes proxy`）——暴露一个 `http://localhost:port` 的 OpenAI API，
  由你已登录的 OAuth 提供商（Claude Pro、ChatGPT Pro、SuperGrok）支撑。把 Codex CLI、
  Aider、Cline、Continue 或任意脚本指向它——无需 API key。
- **Automation Blueprints（自动化蓝图）**——选择一个具名自动化，Hermes 会询问它所需的信息
  （无需编写 cron 语法）。同一份定义会渲染为仪表盘表单、斜杠命令、agent 对话，
  以及文档目录条目。
- **`memory` 工具的批量操作**——传入一个由 add/replace/remove 编辑组成的 `operations` 数组，
  这些编辑会针对最终的字符预算原子地应用，因此即便单独的 add 会超出预算，
  一次调用也能同时腾出空间并新增条目。
- **`session_search`**——基于 FTS5，不使用辅助 LLM，几乎零成本。一个工具，三种模式，
  由传入哪些参数推断：检索（`query`）、滚动（`session_id` + `around_message_id`）、
  浏览（不传参数）。
- **通过 SuperGrok OAuth 使用 xAI Grok**——用你的 xAI 账号登录（无需 API key）；
  包含 Cursor 的 `grok-composer-2.5-fast` 编码模型。

---

## Windows 特有问题

Hermes 在 Windows 上原生运行（PowerShell、cmd、Windows Terminal、git-bash mintty、VS Code 集成终端）。大多数功能开箱即用，但 Win32 和 POSIX 之间有一些差异曾给我们带来麻烦——遇到新问题时请在此记录，以免下一个人（或下一个会话）重新踩坑。

### 输入/键绑定

**Alt+Enter 不插入换行**——Windows Terminal（以及 mintty）会在 prompt_toolkit 看到它之前
把它用于切换全屏。请改用 **Ctrl+Enter**（CLI 在 Windows 上把它绑定为换行；原始的 Ctrl+J
效果相同，且无害）。要查看你的终端如何上报某个按键，请在仓库根目录运行
`python scripts/keystroke_diagnostic.py`。

### 配置/文件

**首次运行时 HTTP 400 "No models provided"**——`config.yaml` 保存时带了 UTF-8 BOM
（记事本会这样做）。请重新保存为不带 BOM 的 UTF-8；`hermes config edit` 写入方式是正确的。

### `execute_code` / 沙箱

**WinError 10106** 来自沙箱子进程——它无法创建 `AF_INET` socket。根本原因通常是
Hermes 自身的环境清理器删除了 `SYSTEMROOT`/`WINDIR`/`COMSPEC`（Python 的 `socket` 需要
`SYSTEMROOT` 来找到 `mswsock.dll`），而不是损坏的 Winsock LSP。`tools/code_execution_tool.py`
中的 `_WINDOWS_ESSENTIAL_ENV_VARS` 允许列表已覆盖该问题；如果仍然遇到，请在 `execute_code`
块内 echo `os.environ` 以确认 `SYSTEMROOT` 已设置。

### 在 Windows 上测试

`scripts/run_tests.sh` 仅适用于 POSIX（它期望 `.venv/bin/activate`）；Hermes 安装的
`venv/Scripts/` 中没有 pip/pytest（为减小体积而精简）。请把 pytest 安装到系统 Python，
然后用 `-n 0` 直接运行（`pyproject.toml` 的 `addopts` 已经设置了 `-n`）：

```bash
"/c/Program Files/Python311/python" -m pip install --user pytest pytest-xdist pyyaml
export PYTHONPATH="$(pwd)"
"/c/Program Files/Python311/python" -m pytest tests/foo/test_bar.py -v --tb=short -n 0
```

（仅 POSIX 的测试需要跳过守卫——参见下方贡献者一节中的跨平台守卫列表。）

### 路径/文件系统

**行尾。** Git 可能警告 `LF will be replaced by CRLF`。这是外观问题——仓库的
`.gitattributes` 会规范化。不要让编辑器自动将已提交的 POSIX 换行文件转换为 CRLF。

**正斜杠几乎在所有地方都有效。** `C:/Users/...` 被每个 Hermes 工具和大多数 Windows API 接受。在代码和日志中优先使用正斜杠——避免在 bash 中转义反斜杠。

---

## 故障排查

### 语音不工作
1. 检查 `config.yaml` 中 `stt.enabled: true`
2. 验证提供商：`pip install faster-whisper` 或设置 API key
3. 在 gateway 中：`/restart`。在 CLI 中：退出并重新启动。

### 工具不可用
1. `hermes tools` — 检查 toolset 是否为你的平台启用
2. 某些工具需要环境变量（检查 `.env`）
3. 启用工具后执行 `/reset`

### 模型/提供商问题
1. `hermes doctor` — 检查配置和依赖
2. `hermes auth` — 重新认证 OAuth 提供商（或 `hermes auth add <provider>`）
3. 检查 `.env` 中是否有正确的 API key
4. **Copilot 403**：`gh auth login` 的 token **不适用于** Copilot API。必须通过 `hermes model` → GitHub Copilot 使用 Copilot 专用 OAuth 设备码流程。

### 变更未生效
- **工具/skill：** `/reset` 以更新后的 toolset 启动新会话
- **配置变更：** 在 gateway 中：`/restart`。在 CLI 中：退出并重新启动。
- **代码变更：** 重启 CLI 或 gateway 进程

### Skill 未显示
1. `hermes skills list` — 验证已安装
2. `hermes skills config` — 检查平台启用状态
3. 显式加载：`/skill name` 或 `hermes -s name`

### Gateway 问题
首先检查日志：
```bash
grep -i "failed to send\|error" ~/.hermes/logs/gateway.log | tail -20
```

常见 gateway 问题：
- **SSH 注销后 gateway 停止**：启用 linger：`sudo loginctl enable-linger $USER`
- **WSL2 关闭后 gateway 停止**：WSL2 需要 `/etc/wsl.conf` 中的 `systemd=true` 才能使 systemd 服务工作。没有它，gateway 回退到 `nohup`（会话关闭时停止）。
- **Gateway 崩溃循环**：重置失败状态：`systemctl --user reset-failed hermes-gateway`

### 平台特定问题
- **Discord bot 静默**：必须在 Bot → Privileged Gateway Intents 中启用 **Message Content Intent**。
- **Slack bot 仅在私信中工作**：必须订阅 `message.channels` 事件。没有它，bot 会忽略公共频道。
- **Windows 特有问题**（`Alt+Enter` 换行、WinError 10106、UTF-8 BOM 配置、测试套件、行尾）：参见上方专门的 **Windows 特有问题** 部分。

### 辅助模型不工作
如果 `auxiliary` 任务（视觉、压缩）静默失败，`auto` 提供商找不到后端。请设置 `OPENROUTER_API_KEY` 或 `GOOGLE_API_KEY`，或显式配置每个辅助任务的提供商：
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <model_name>
```

---

## 查找资源

| 查找内容... | 位置 |
|----------------|----------|
| 配置选项 | `hermes config edit` 或[配置文档](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| 可用工具 | `hermes tools list` 或[工具参考](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| 斜杠命令 | 会话内 `/help` 或[斜杠命令参考](https://hermes-agent.nousresearch.com/docs/reference/slash-commands) |
| Skill 目录 | `hermes skills browse` 或[Skill 目录](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| 提供商设置 | `hermes model` 或[提供商指南](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| 平台设置 | `hermes gateway setup` 或[消息文档](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/) |
| MCP 服务器 | `hermes mcp list` 或[MCP 指南](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) |
| Profiles | `hermes profile list` 或[Profiles 文档](https://hermes-agent.nousresearch.com/docs/user-guide/profiles) |
| Cron 任务 | `hermes cron list` 或[Cron 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron) |
| 记忆 | `hermes memory status` 或[记忆文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory) |
| 环境变量 | `hermes config env-path` 或[环境变量参考](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| CLI 命令 | `hermes --help` 或[CLI 参考](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) |
| Gateway 日志 | `~/.hermes/logs/gateway.log` |
| 会话文件 | `~/.hermes/sessions/` 或 `hermes sessions browse` |
| 源代码 | `~/.hermes/hermes-agent/` |

---

## 贡献者快速参考

面向偶尔贡献者和 PR 作者。完整开发者文档：https://hermes-agent.nousresearch.com/docs/developer-guide/

### 项目结构

<!-- ascii-guard-ignore -->
```
hermes-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions
├── cli.py                # Interactive CLI (HermesCLI)
├── hermes_state.py       # SQLite session store
├── agent/                # Prompt builder, context compression, memory, model routing, credential pooling, skill dispatch
├── hermes_cli/           # CLI subcommands, config, setup, commands
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point and argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, etc.)
├── cron/                 # Job scheduler
├── tests/                # Extensive pytest suite (run via scripts/run_tests.sh)
└── website/              # Docusaurus docs site
```
<!-- ascii-guard-ignore-end -->

配置：`~/.hermes/config.yaml`（设置）、`~/.hermes/.env`（API key）——设置了 `$HERMES_HOME` 时两者都位于其下。

### 添加工具

两个文件。自动发现会导入任何包含顶层 `registry.register()` 调用的 `tools/*.py`，
但只有当工具名出现在某个 toolset 中时，它才会真正**暴露**给 agent。

**1. 创建 `tools/your_tool.py`：**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(
        param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. 在 `toolsets.py` 中把它接入某个 toolset**——把工具名加入
`_HERMES_CORE_TOOLS`（所有平台）或某个特定的 toolset。

所有处理器必须返回 JSON 字符串。路径使用 `get_hermes_home()`，永远不要硬编码
`~/.hermes`。对于自定义或仅本地使用的工具，请在 `~/.hermes/plugins/` 中编写插件，
而不是修改核心——参见开发者文档。

### 添加斜杠命令

1. 在 `hermes_cli/commands.py` 的 `COMMAND_REGISTRY` 中添加 `CommandDef`
2. 在 `cli.py` → `process_command()` 中添加处理器
3. （可选）在 `gateway/run.py` 中添加 gateway 处理器

所有消费方（帮助文本、自动补全、Telegram 菜单、Slack 映射）均自动从中央注册表派生。

### Agent 循环（高层概述）

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. If tool_calls → dispatch each via handle_function_call() → append results → continue
     c. If text response → return
  3. Context compression triggers automatically near token limit
```

### 测试

使用标准运行器——它保证与 CI 一致（隔离环境、清空凭据、TZ=UTC、xdist worker、
每个测试的子进程隔离）：

```bash
scripts/run_tests.sh                          # 完整套件
scripts/run_tests.sh tests/tools/             # 单个目录
scripts/run_tests.sh tests/tools/test_x.py    # 单个文件
scripts/run_tests.sh -v --tb=long             # 透传 pytest 标志
```

- 测试自动将 `HERMES_HOME` 重定向到临时目录——永远不会触及真实的 `~/.hermes/`。
- 该脚本会依次探测 `.venv`、`venv`，然后是共享 worktree venv。
- **Windows：** 该 wrapper 仅适用于 POSIX；直接调用 pytest 的替代方案参见上方的
  **Windows 特有问题**一节。

**跨平台测试守卫：** 使用仅 POSIX 系统调用的测试需要跳过标记。代码库中已有的常见标记：
- 符号链接创建 → `@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")`（参见 `tests/cron/test_cron_script.py`）
- POSIX 文件模式（0o600 等）→ `@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX mode bits not enforced on Windows")`（参见 `tests/hermes_cli/test_auth_toctou_file_modes.py`）
- `signal.SIGALRM` → 仅 Unix（参见 `tests/conftest.py::_enforce_test_timeout`）
- 实时 Winsock / Windows 特有回归测试 → `@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific regression")`

**仅 monkeypatch `sys.platform` 是不够的**，当被测代码还调用 `platform.system()` / `platform.release()` / `platform.mac_ver()` 时。这些函数独立重新读取真实 OS，因此在 Windows runner 上将 `sys.platform = "linux"` 的测试仍会看到 `platform.system() == "Windows"` 并走 Windows 分支。需要同时 patch 三者：

```python
monkeypatch.setattr(sys, "platform", "linux")
monkeypatch.setattr(platform, "system", lambda: "Linux")
monkeypatch.setattr(platform, "release", lambda: "6.8.0-generic")
```

参见 `tests/agent/test_prompt_builder.py::TestEnvironmentHints` 中的完整示例。

### 系统 prompt 的执行环境块

关于宿主/后端的事实性指导（OS、`$HOME`、cwd、终端后端、shell）由
`agent/prompt_builder.py::build_environment_hints()` 输出。对 prompt 编写者而言的关键
不变量是：使用**远程**终端后端时（`docker, singularity, modal, daytona, ssh, managed_modal`），
宿主信息会被抑制，并且*每个*文件工具都在后端容器内运行——prompt 绝不能描述
agent 无法触及的那台宿主。

### 提交约定

```
type: concise subject line

Optional body.
```

类型：`fix:`、`feat:`、`refactor:`、`docs:`、`chore:`

### 关键规则

- **永远不要破坏 prompt 缓存** — 不要在对话中途更改上下文、工具或系统 prompt
- **消息角色交替** — 永远不要连续出现两条 assistant 或两条 user 消息
- 所有路径使用 `hermes_constants` 中的 `get_hermes_home()`（profile 安全）
- 配置值放入 `config.yaml`，密钥放入 `.env`
- 新工具需要 `check_fn`，以便仅在满足要求时才显示