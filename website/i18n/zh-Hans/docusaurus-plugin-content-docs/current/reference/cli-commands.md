---
sidebar_position: 1
title: "CLI 命令参考"
description: "Hermes 终端命令及命令族的权威参考"
---

# CLI 命令参考

本页介绍从 shell 运行的**终端命令**。

关于聊天内斜杠命令，请参阅 [斜杠命令参考](./slash-commands.md)。

## 全局入口

```bash
hermes [global-options] <command> [subcommand/options]
```

### 全局选项

| 选项 | 说明 |
|--------|-------------|
| `--version`, `-V` | 显示版本并退出。 |
| `--profile <name>`, `-p <name>` | 选择本次调用使用的 Hermes profile（配置文件）。覆盖 `hermes profile use` 设置的粘性默认值。 |
| `--resume <session>`, `-r <session>` | 通过 ID 或标题恢复之前的会话。关键字 `latest` 会恢复最近的会话（按工作区范围，查找方式与 `-c` 相同）。 |
| `--continue [name]`, `-c [name]` | 恢复最近的会话，或恢复最近一个匹配标题的会话。 |
| `--in <dir>` | 在启动或恢复之前切换到 `<dir>`。将 `--resume latest` / `-c` 的查找范围限定在该目录的工作区，并让会话留在那里（跳过恢复已记录的 cwd）。 |
| `--worktree`, `-w` | 在隔离的 git worktree 中启动，用于并行 agent 工作流。 |
| `--yolo` | 跳过危险命令的审批提示。 |
| `--pass-session-id` | 在 agent 的 system prompt（系统提示词）中包含会话 ID。 |
| `--ignore-user-config` | 忽略 `~/.hermes/config.yaml`，回退到内置默认值。`.env` 中的凭据仍会加载。 |
| `--ignore-rules` | 跳过 `AGENTS.md`、`SOUL.md`、`.cursorrules`、memory（记忆）和预加载 skill 的自动注入。 |
| `--tui` | 启动 [TUI](../user-guide/tui.md) 而非经典 CLI。等同于 `HERMES_TUI=1`。始终优先于 `display.interface`。 |
| `--cli` | 强制使用经典的 prompt_toolkit REPL。用它在单次调用中覆盖 `display.interface: tui`。 |
| `--dev` | 与 `--tui` 配合使用：通过 `tsx` 直接运行 TypeScript 源码而非预构建包（供 TUI 贡献者使用）。 |

## 顶级命令

| 命令 | 用途 |
|---------|---------|
| `hermes chat` | 与 agent 进行交互式或单次聊天。 |
| `hermes model` | 交互式选择默认 provider 和模型。 |
| `hermes moa` | 配置可从模型选择器中选中的具名 Mixture of Agents 预设。 |
| `hermes fallback` | 管理主模型出错时依次尝试的 fallback provider。 |
| `hermes gateway` | 运行或管理消息 gateway 服务。 |
| `hermes proxy` | 本地 OpenAI 兼容代理，附加 OAuth provider 凭据。参见 [订阅代理](../user-guide/features/subscription-proxy.md)。 |
| `hermes egress` | 面向远程终端沙箱的出站凭据注入防火墙（iron-proxy）。默认禁用。参见 [出站代理](../user-guide/egress/iron-proxy.md)。 |
| `hermes lsp` | 管理 Language Server Protocol 集成（为 write_file/patch 提供语义诊断）。 |
| `hermes setup` | 全部或部分配置的交互式设置向导。 |
| `hermes whatsapp` | 配置并配对 WhatsApp 桥接。 |
| `hermes whatsapp-cloud` | 配置官方 Meta WhatsApp Business Cloud API 适配器（需要 Business 账号 + 公网 webhook）。与 `hermes whatsapp`（Baileys 个人账号桥接）不同。 |
| `hermes slack` | Slack 辅助工具（当前功能：生成将每条命令注册为原生斜杠命令的 app manifest）。 |
| `hermes auth` | 管理凭据——添加、列出、删除、重置、查看状态、登出。处理 Codex/Nous/Anthropic 的 OAuth 流程。 |
| `hermes login` / `logout` | **已弃用** — 请改用 `hermes auth`。 |
| `hermes send` | 向已配置的消息平台（Telegram、Discord、Slack、Signal、SMS……）发送单条消息。适合在 shell 脚本、cron 任务、CI hook 和监控守护进程中使用——无 agent 循环，无 LLM。 |
| `hermes peer` | 注册其他机器上的对等 Hermes gateway，并私信其 agent 的规范 Bot Chat（`hermes peer dm <peer>[/<agent>] "…"`）。这是跨机器 bot 间消息传递背后的传输层。 |
| `hermes secrets` | 管理外部密钥源（目前为 Bitwarden Secrets Manager），在进程启动时拉取 API key，而不是从 `~/.hermes/.env` 读取。 |
| `hermes migrate` | 诊断并（可选）重写 `config.yaml`，替换对已下线模型或已弃用设置的引用（例如 `migrate xai`）。 |
| `hermes status` | 显示 agent、auth 和平台状态。 |
| `hermes cron` | 检查并触发 cron 调度器。 |
| `hermes kanban` | 多 profile 协作看板（任务、链接、调度器）。 |
| `hermes project` | 管理具名的多文件夹工作区（project）。它为桌面会话分组提供锚点，并在绑定看板后为任务提供确定的 worktree + 分支约定。状态按 profile 隔离。 |
| `hermes webhook` | 管理用于事件驱动激活的动态 webhook 订阅。 |
| `hermes hooks` | 检查、审批或删除 `config.yaml` 中声明的 shell 脚本 hook。 |
| `hermes doctor` | 诊断配置和依赖问题。 |
| `hermes security audit` | 对 venv、plugin 依赖和固定 MCP 服务器进行按需供应链审计（OSV.dev）。 |
| `hermes approvals` | 审批提示工具——从审批历史中挖掘出允许列表提案。 |
| `hermes dump` | 可直接复制粘贴的设置摘要，用于支持/调试。 |
| `hermes prompt-size` | 显示系统 prompt + 工具 schema（skill 索引、记忆、profile）的字节构成。离线运行。 |
| `hermes debug` | 调试工具——上传日志和系统信息以获取支持。 |
| `hermes backup` | 将 Hermes 主目录备份为 zip 文件。 |
| `hermes checkpoints` | 检查/修剪/清除 `~/.hermes/checkpoints/`（`/rollback` 使用的影子存储）。不带参数运行可查看状态概览。 |
| `hermes import` | 从 zip 文件恢复 Hermes 备份。 |
| `hermes logs` | 查看、跟踪和过滤 agent/gateway/错误日志文件。 |
| `hermes config` | 显示、编辑、迁移和查询配置文件。 |
| `hermes skin` | 列出、切换和微调显示皮肤。 |
| `hermes console` | 打开安全的 Hermes 命令控制台。 |
| `hermes pairing` | 审批或撤销消息配对码。 |
| `hermes skills` | 浏览、安装、发布、审计和配置 skill。 |
| `hermes bundles` | 将多个 skill 归组到单个 `/<name>` 斜杠命令下。参见 [Skill Bundles](../user-guide/features/skills.md#skill-bundles)。 |
| `hermes curator` | 后台 skill 维护——状态、运行、暂停、固定。参见 [Curator](../user-guide/features/curator.md)。 |
| `hermes journey`（别名 `learning`、`memory-graph`） | 随时间推移已学习 skill + 记忆的时间线。 |
| `hermes memory` | 配置外部 memory provider。当对应 provider 激活时，特定于 plugin 的子命令（如 `hermes honcho`）会自动注册。 |
| `hermes acp` | 将 Hermes 作为 ACP 服务器运行，用于编辑器集成。 |
| `hermes mcp` | 管理 MCP 服务器配置，并将 Hermes 作为 MCP 服务器运行。 |
| `hermes plugins` | 管理 Hermes Agent plugin（安装、启用、禁用、删除）。 |
| `hermes portal` | Nous Portal 状态、订阅链接和 Tool Gateway 路由。参见 [Tool Gateway](../user-guide/features/tool-gateway.md)。 |
| `hermes tools` | 按平台配置已启用的工具。 |
| `hermes computer-use` | 安装或检查 Computer Use（cua-driver）后端（macOS/Windows/Linux）。 |
| `hermes pets` | 浏览、安装并选择 [petdex](../user-guide/features/pets.md) 动画宠物，它们会在 CLI、TUI 和桌面应用中显示。子命令：`list`、`install`、`select`、`show`、`off`、`scale`、`remove`、`doctor`。 |
| `hermes sessions` | 浏览、导出、修剪、重命名和删除会话。 |
| `hermes insights` | 显示 token/费用/活动分析。 |
| `hermes claw` | OpenClaw 迁移辅助工具。 |
| `hermes import-agent` | 导入 Claude Code（`~/.claude`）或 Codex CLI（`~/.codex`）的配置。 |
| `hermes dashboard` | 启动用于管理配置、API 密钥和会话的 Web 控制台。 |
| `hermes serve` | 启动 Hermes 后端服务器（无界面；为桌面应用和远程后端提供支持）。 |
| `hermes desktop`（别名 `gui`） | 构建并启动原生 Electron 桌面应用。 |
| `hermes profile` | 管理 profile——多个隔离的 Hermes 实例。 |
| `hermes completion` | 打印 shell 补全脚本（bash/zsh/fish）。 |
| `hermes --version` | 显示版本信息。 |
| `hermes update` | 拉取最新代码并重新安装依赖。`--check` 预览而不安装；`--backup` 在拉取前对 `HERMES_HOME` 进行快照。 |
| `hermes uninstall` | 从系统中删除 Hermes。 |

## `hermes chat`

```bash
hermes chat [options]
```

常用选项：

| 选项 | 说明 |
|--------|-------------|
| `-q`, `--query "..."` | 用一个 prompt 作为会话的开头。在真实 TTY 上，该 prompt 会作为普通交互式会话的第一轮被**原样**提交（永远不会被解析为斜杠命令或 `!` shell 转义），并且会话保持打开——非常适合操作系统启动器和桌面集成。配合 `--oneshot`、`-Q` 或非 TTY 的标准输入输出时，它会回答后退出。 |
| `--query-file PATH` | 从文件读取查询（`-` 表示 stdin）。内容不会经过 shell 解释，因此引号、`$(...)` 和反引号都会原样到达——用于程序化或不受信任的消息正文（Bot Mode 队友私信使用它）。与 `-q` 互斥。 |
| `--oneshot` | 与 `-q`/`--query-file` 配合使用：回答查询后退出（0.21 之前的单次查询行为），而不是开启一个交互式会话。在非 TTY 标准输入输出下以及使用 `-Q` 时默认隐含。 |
| `-m`, `--model <model>` | 覆盖本次运行的模型。 |
| `-t`, `--toolsets <csv>` | 启用逗号分隔的 toolset 集合。 |
| `--provider <provider>` | 强制指定 provider：`auto`、`openrouter`、`nous`、`openai-codex`、`copilot-acp`、`copilot`、`anthropic`、`gemini`、`huggingface`、`novita`（别名 `novita-ai`、`novitaai`）、`openai-api`、`zai`、`kimi-coding`、`kimi-coding-cn`、`minimax`、`minimax-cn`、`minimax-oauth`、`kilocode`、`xiaomi`、`arcee`、`gmi`、`upstage`（别名 `solar`）、`alibaba`、`alibaba-cn`、`alibaba-coding-plan`（别名 `alibaba_coding`）、`alibaba-coding-plan-cn`、`alibaba-token-plan`、`alibaba-token-plan-cn`、`deepseek`、`nvidia`、`ollama-cloud`、`xai`（别名 `grok`）、`xai-oauth`（别名 `grok-oauth`）、`qwen-oauth`、`bedrock`、`opencode-zen`、`opencode-go`、`opencode-free`（别名 `free`、`opencode_free`；无需密钥）、`commandcode`、`commandcode-anthropic`、`ai-gateway`、`azure-foundry`、`lmstudio`、`stepfun`、`tencent-tokenhub`（别名 `tencent`、`tokenhub`）、`router`（别名 `ramp-router`、`ramp`）、`nebius-token-factory`（别名 `nebius`、`nebius-tf`、`tokenfactory`）、`tencent-tokenplan`（别名 `tokenplan`、`tencent-lkeap`）。 |
| `-s`, `--skills <name>` | 为会话预加载一个或多个 skill（可重复或逗号分隔）。 |
| `-v`, `--verbose` | 详细输出。 |
| `-Q`, `--quiet` | 程序化模式：抑制横幅/spinner/工具预览。 |
| `--image <path>` | 为单次查询附加本地图片。 |
| `--resume <session>` / `--continue [name]` | 直接从 `chat` 恢复会话。 |
| `--worktree` | 为本次运行创建隔离的 git worktree。 |
| `--checkpoints` | 在破坏性文件变更前启用文件系统 checkpoint。 |
| `--yolo` | 跳过审批提示。 |
| `--pass-session-id` | 将会话 ID 传入 system prompt。 |
| `--ignore-user-config` | 忽略 `~/.hermes/config.yaml`，使用内置默认值。`.env` 中的凭据仍会加载。适用于隔离的 CI 运行、可复现的 bug 报告和第三方集成。 |
| `--ignore-rules` | 跳过 `AGENTS.md`、`SOUL.md`、`.cursorrules`、持久 memory 和预加载 skill 的自动注入。与 `--ignore-user-config` 组合可实现完全隔离的运行。 |
| `--safe-mode` | 排障模式：禁用全部自定义——用户配置、rules/memory 注入、plugin、shell hook 和 MCP 服务器（隐含 `--ignore-user-config` 和 `--ignore-rules`）。用它来判断问题出在你的配置还是 Hermes 本身。 |
| `--source <tag>` | 用于过滤的会话来源标签（默认：`cli`）。对于不应出现在用户会话列表中的第三方集成，使用 `tool`。 |
| `--max-turns <N>` | 每个对话轮次的最大工具调用迭代次数（默认：500，或 config 中的 `agent.max_turns`）。 |

示例：

```bash
hermes
hermes chat -q "Summarize the latest PRs"          # 开启一个交互式会话
hermes chat --oneshot -q "Summarize the latest PRs"  # 回答后退出
hermes chat --provider openrouter --model anthropic/claude-sonnet-4.6
hermes chat --toolsets web,terminal,skills
hermes chat --quiet -q "Return only JSON"
hermes chat --worktree -q "Review this repo and open a PR"
hermes chat --ignore-user-config --ignore-rules -q "Repro without my personal setup"
hermes chat --safe-mode -q "Is this bug mine or Hermes'?"
```

### `hermes -z <prompt>` — 脚本化单次调用

对于程序化调用方（shell 脚本、CI、cron、通过管道传入 prompt 的父进程），`hermes -z` 是最纯粹的单次入口：**单个 prompt 输入，最终响应文本输出，stdout 和 stderr 上不输出任何其他内容。** 无横幅、无 spinner、无工具预览、无 `Session:` 行——只有 agent 的最终回复纯文本。

```bash
hermes -z "What's the capital of France?"
# → Paris.

# 父脚本可以干净地捕获响应：
answer=$(hermes -z "summarize this" < /path/to/file.txt)
```

单次运行覆盖（不修改 `~/.hermes/config.yaml`）：

| 标志 | 等效环境变量 | 用途 |
|---|---|---|
| `-m` / `--model <model>` | `HERMES_INFERENCE_MODEL` | 覆盖本次运行的模型 |
| `--provider <provider>` | _(无)_ | 覆盖本次运行的 provider |
| `--usage-file <path>` | _(无)_ | 运行结束后写入一份 JSON 用量报告（见下文） |

```bash
hermes -z "…" --provider openrouter --model openai/gpt-5.5
# 或：
HERMES_INFERENCE_MODEL=anthropic/claude-sonnet-4.6 hermes -z "…"
```

相同的 agent、相同的工具、相同的 skill——只是剥离了所有交互式/装饰性层。如果你还需要在记录中包含工具输出，请改用 `hermes chat --oneshot -q`；`-z` 专门用于"我只需要最终答案"的场景。

#### `--usage-file` — 面向流水线的 JSON 用量报告 {#--usage-file--json-usage-report-for-pipelines}

`hermes -z "…" --usage-file /path/report.json` 会在运行结束后写入一份机器可读的用量报告：`estimated_cost_usd`、`input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens` / `reasoning_tokens` / `total_tokens`、`api_calls`、`model`、`provider`、`session_id`、`service_tier`，以及 `completed` / `failed` 标志。**即使运行失败**也会写入该报告，因此批处理流水线始终可以统计花费。它在 `-z`/`--oneshot` 之外不起作用，并且用量写入失败永远不会掩盖运行本身的结果。

```bash
hermes -z "summarize this repo" --usage-file /tmp/usage.json
jq .estimated_cost_usd /tmp/usage.json
```

## `hermes model`

交互式 provider + 模型选择器。**这是添加新 provider、设置 API 密钥和运行 OAuth 流程的命令。** 从终端运行——不要在活跃的 Hermes 聊天会话内部运行。

```bash
hermes model
```

在以下情况使用此命令：
- **添加新 provider**（OpenRouter、Anthropic、Copilot、DeepSeek、自定义等）
- 登录基于 OAuth 的 provider（Anthropic、Copilot、Codex、Nous Portal）
- 输入或更新 API 密钥
- 从 provider 特定的模型列表中选择
- 配置自定义/自托管端点
- 将新默认值保存到 config

:::warning hermes model 与 /model——了解区别
**`hermes model`**（从终端运行，在任何 Hermes 会话外部）是**完整的 provider 设置向导**。它可以添加新 provider、运行 OAuth 流程、提示输入 API 密钥并配置端点。

**`/model`**（在活跃的 Hermes 聊天会话中输入）只能**在已设置好的 provider 和模型之间切换**。它无法添加新 provider、运行 OAuth 或提示输入 API 密钥。

**如果需要添加新 provider：** 先退出 Hermes 会话（`Ctrl+C` 或 `/quit`），然后从终端提示符运行 `hermes model`。
:::

### `/model` 斜杠命令（会话中途）

无需离开会话即可在已配置的模型之间切换：

```
/model                              # 显示当前模型和可用选项
/model claude-sonnet-4              # 切换模型（自动检测 provider）
/model zai:glm-5                    # 切换 provider 和模型
/model custom:qwen-2.5              # 在自定义端点上使用模型
/model custom                       # 从自定义端点自动检测模型
/model custom:local:qwen-2.5        # 使用命名的自定义 provider
/model openrouter:anthropic/claude-sonnet-4  # 切换回云端
```

默认情况下，`/model` 的更改**仅对当前会话生效**。添加 `--global` 可将更改持久化到 `config.yaml`（或设置 `model.persist_switch_by_default: true` 使每次切换都持久化）：

```
/model claude-sonnet-4 --global     # 切换并保存为新默认值
```

:::info 如果我只看到 OpenRouter 模型怎么办？
如果你只配置了 OpenRouter，`/model` 将只显示 OpenRouter 模型。要添加其他 provider（Anthropic、DeepSeek、Copilot 等），请退出会话并从终端运行 `hermes model`。
:::

在 `--global` 切换时，provider 和 base URL 的更改会连同模型一起持久化到 `config.yaml`。从自定义端点切换走时，过时的 base URL 会被清除，以防止其泄漏到其他 provider。

## `hermes gateway`

```bash
hermes gateway <subcommand>
```

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `run` | 在前台运行 gateway。推荐用于 WSL、Docker 和 Termux。 |
| `start` | 启动已安装的 systemd/launchd 后台服务。 |
| `stop` | 停止服务（或前台进程）。 |
| `restart` | 重启服务。 |
| `status` | 显示服务状态。 |
| `list` | 列出**所有 profile** 及每个 profile 的 gateway 当前是否运行（有 PID 时显示）。当你并行运行多个 profile 并需要单一概览时很方便。 |
| `install` | 安装为 systemd（Linux）或 launchd（macOS）后台服务。 |
| `uninstall` | 删除已安装的服务。 |
| `setup` | 交互式消息平台设置。 |
| `migrate-legacy` | 删除重命名前安装遗留的旧版 `hermes.service` 单元。profile 单元（`hermes-gateway-<profile>.service`）和无关服务永远不会被触及。参数：`--dry-run`、`-y`/`--yes`。 |
| `enroll` | 实验性：将此 gateway 注册到中继连接器，并为基于连接器的平台保存中继凭据。参见 [Hermes Relay](/user-guide/messaging/relay)。 |

选项：

| 选项 | 说明 |
|--------|-------------|
| `--all` | 在 `start` / `restart` / `stop` 时：对**每个 profile** 的 gateway 执行操作，而不仅限于活跃的 `HERMES_HOME`。当你并行运行多个 profile 并希望在 `hermes update` 后全部重启时很有用。 |
| `--no-supervise` | 在 `run` 时：在 s6-overlay Docker 镜像内部，跳过 s6 自动监管，退回到 pre-s6 前台语义——gateway 作为容器主进程运行，无自动重启。在 s6 镜像之外为空操作。等同于设置 `HERMES_GATEWAY_NO_SUPERVISE=1`。 |
| `--external-supervisor` | 在 `run` 时：声明由包装层提供的进程管理器拥有前台 gateway。当 `sudo`、`env -i` 或其他包装层去掉了 launchd/systemd 的原生环境标记时使用它。聊天内重启和更新会退回给该管理器，而不是另行启动一个分离的替代进程。 |

`--external-supervisor` 是一份重启策略契约：聊天内重启或服务重启式更新会以状态码 `75` 退出，因此包装层的监管器必须在该非零退出后重新拉起 gateway。对于 systemd，请使用
`Restart=on-failure` 或 `Restart=always`，并不要将 `75` 写入
`RestartPreventExitStatus`；对于 launchd，请配置 `KeepAlive` 以在失败退出后重新拉起。没有这份策略，一次请求的重启会使 gateway 停留在停止状态。

`hermes gateway enroll` 接受 `--token`、`--connector-url`、`--gateway-id` 和 `--wake-url`。它会将注册 token 与连接器交换，并将得到的 `GATEWAY_RELAY_ID`、`GATEWAY_RELAY_SECRET`、`GATEWAY_RELAY_DELIVERY_KEY`、可选的 `GATEWAY_RELAY_URL`，以及（当给出 `--wake-url` 时）`GATEWAY_RELAY_WAKE_URL` 写入当前 profile 的 `.env`。

:::tip WSL 用户
使用 `hermes gateway run` 而非 `hermes gateway start`——WSL 的 systemd 支持不稳定。用 tmux 包裹以保持持久运行：`tmux new -s hermes 'hermes gateway run'`。详见 [WSL FAQ](/reference/faq#wsl-gateway-keeps-disconnecting-or-hermes-gateway-start-fails)。
:::

## `hermes lsp`

```bash
hermes lsp <subcommand>
```

管理 Language Server Protocol 集成。LSP 在后台运行真实的语言服务器（pyright、gopls、rust-analyzer 等），并将其诊断信息输入 `write_file` 和 `patch` 使用的写后检查。受 git 工作区检测限制——仅当 cwd 或编辑的文件位于 git worktree 内时，LSP 才会运行。

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `status` | 显示服务状态、已配置的服务器、安装状态。 |
| `list` | 打印支持的服务器注册表。传入 `--installed-only` 可跳过缺失的服务器。 |
| `install <id>` | 主动安装某个服务器的二进制文件。 |
| `install-all` | 安装所有具有已知自动安装方案的服务器。 |
| `restart` | 关闭正在运行的客户端，以便下次编辑时重新启动。 |
| `which <id>` | 打印某个服务器的已解析二进制路径。 |

完整指南、支持的语言和配置项，请参阅 [LSP — 语义诊断](/user-guide/features/lsp)。

## `hermes setup`

```bash
hermes setup [model|tts|terminal|gateway|tools|agent] [--non-interactive] [--reset] [--quick] [--reconfigure] [--portal]
```

**最简路径：** `hermes setup --portal` —— 一步完成 Nous Portal 的 OAuth 登录并启用 [Tool Gateway](../user-guide/features/tool-gateway.md)。

**首次运行：** 启动首次使用向导。

**已配置用户：** 直接进入完整重新配置向导——每个提示都以当前值作为默认值，按 Enter 保留或输入新值。无菜单。

跳转到某个部分而非完整向导：

| 部分 | 说明 |
|---------|-------------|
| `model` | Provider 和模型设置。 |
| `terminal` | 终端后端和沙箱设置。 |
| `gateway` | 消息平台设置。 |
| `tools` | 按平台启用/禁用工具。 |
| `agent` | Agent 行为设置。 |

选项：

| 选项 | 说明 |
|--------|-------------|
| `--quick` | 在已配置用户运行时：仅提示缺失或未设置的项目，跳过已配置的项目。 |
| `--non-interactive` | 使用默认值/环境变量，不显示提示。 |
| `--reset` | 在设置前将配置重置为默认值。 |
| `--reconfigure` | 向后兼容别名——在已有安装上裸运行 `hermes setup` 现在默认执行此操作。 |
| `--portal` | 一键 Nous Portal 设置：通过 OAuth 登录，将 Nous 设为推理 provider，并选择加入 [Tool Gateway](../user-guide/features/tool-gateway.md)。跳过向导其余部分。 |

## `hermes portal`

```bash
hermes portal [status|open|tools]
```

检查 Nous Portal 认证、Tool Gateway 路由，并访问订阅页面。不带子命令时运行 `status`。

| 子命令 | 说明 |
|------------|-------------|
| `status`（默认） | Portal 认证状态 + 每个工具的 Tool Gateway 路由摘要。不带子命令时也会显示。 |
| `open` | 在默认浏览器中打开 `portal.nousresearch.com/manage-subscription`。 |
| `tools` | 列出每个 Tool Gateway 合作伙伴（Firecrawl、FAL、OpenAI TTS、Browser Use、Modal）及哪些通过 Nous 路由。 |

关于 gateway 本身的配置，请参阅 [Tool Gateway](../user-guide/features/tool-gateway.md)。关于一键设置路径，请参阅上方的 `hermes setup --portal`。

## `hermes whatsapp`

```bash
hermes whatsapp
```

运行 WhatsApp 配对/设置流程，包括模式选择和二维码配对。

## `hermes slack`

```bash
hermes slack manifest              # 将 manifest 打印到 stdout
hermes slack manifest --write      # 写入 ~/.hermes/slack-manifest.json
hermes slack manifest --long-description-file AGENTS.md --write
hermes slack manifest --slashes-only  # 仅输出 features.slash_commands 数组
```

生成一个 Slack app manifest，将 `COMMAND_REGISTRY` 中的每条 gateway 命令（`/btw`、`/stop`、`/model` 等）注册为一等公民 Slack 斜杠命令——与 Discord 和 Telegram 保持一致。将输出粘贴到你的 Slack app 配置中：[https://api.slack.com/apps](https://api.slack.com/apps) → 你的 app → **Features → App Manifest → Edit**，然后点击 **Save**。如果 scope 或斜杠命令有变化，Slack 会提示重新安装。

| 标志 | 默认值 | 用途 |
|------|---------|---------|
| `--write [PATH]` | stdout | 写入文件而非 stdout。裸 `--write` 写入 `$HERMES_HOME/slack-manifest.json`。 |
| `--name NAME` | `Hermes` | Slack 中的机器人显示名称。 |
| `--description DESC` | 默认简介 | Slack app 目录中显示的机器人描述。 |
| `--long-description TEXT` | 未设置 | 以内联方式设置 `display_information.long_description`（175–4,000 个字符）。与 `--slashes-only` 不兼容。 |
| `--long-description-file PATH` | 未设置 | 从 UTF-8 文本文件读取长描述，并原样保留其内容。与 `--long-description` 互斥，且与 `--slashes-only` 不兼容。 |
| `--slashes-only` | 关闭 | 仅输出 `features.slash_commands`，用于合并到手动维护的 manifest 中。 |

`hermes update` 后重新运行 `hermes slack manifest --write` 以获取新增命令。


## `hermes send`

```bash
hermes send --to <target> "message text"
hermes send --to <target> --file <path>
echo "message" | hermes send --to <target>
hermes send --list [platform]
```

向已配置的消息平台发送单条消息，无需启动 agent 或 gateway 循环。它复用 gateway 已配置好的凭据（`~/.hermes/.env` + `~/.hermes/config.yaml`），因此运维脚本、cron 任务、CI hook 和监控守护进程无需为每个平台重新实现 REST 客户端即可发布状态更新。

对于使用 bot token 的平台（Telegram、Discord、Slack、Signal、SMS、WhatsApp-CloudAPI），不需要正在运行的 gateway —— `hermes send` 会直接与平台的 REST 端点通信。需要常驻适配器的 plugin 平台仍然需要一个活跃的 gateway。

| 选项 | 说明 |
|--------|-------------|
| `-t`, `--to <TARGET>` | 投递目标。格式：`platform`（使用主频道）、`platform:chat_id`、`platform:chat_id:thread_id` 或 `platform:#channel-name`。示例：`telegram`、`telegram:-1001234567890`、`discord:#ops`、`slack:C0123ABCD`、`signal:+15551234567`。 |
| `-f`, `--file <PATH>` | 从 `PATH` 读取消息正文（仅限文本文件——日志、报告、markdown）。传入 `-` 可强制从 stdin 读取。要发送图片或其他二进制文件，请使用 `MEDIA:<path>`（见下文）。 |
| `-s`, `--subject <LINE>` | 在消息正文前加上一行主题/标题。 |
| `-l`, `--list [platform]` | 列出所有平台（或仅指定平台）上已配置的目标。 |
| `-q`, `--quiet` | 成功时不输出到 stdout —— 适合脚本使用（仅依赖退出码）。 |
| `--json` | 输出原始 JSON 结果，而非人类可读的输出。 |

如果既没有位置参数 `message` 也没有 `--file`，`hermes send` 会在 stdin 不是 TTY 时从 stdin 读取。退出码：成功为 `0`，投递/后端失败为 `1`，用法错误为 `2`。

### 发送图片和其他媒体

`--file` 只用于*文本*正文。要以平台原生附件形式投递图片、文档、视频或音频文件，请在消息文本中用 `MEDIA:<local_path>` 指令引用它：

```bash
hermes send --to telegram "MEDIA:/tmp/screenshot.png"
hermes send --to telegram "Build chart for today MEDIA:/tmp/chart.png"   # 带说明文字
hermes send --to discord:#ops "MEDIA:/tmp/report.pdf"
```

默认情况下，图片文件会以照片形式发送（Telegram 等平台会对其重新压缩）。在消息中加入 `[[as_document]]` 可改为以未压缩的文件附件形式投递：

```bash
hermes send --to telegram "[[as_document]] MEDIA:/tmp/screenshot.png"
```

示例：

```bash
hermes send --to telegram "deploy finished"
echo "RAM 92%" | hermes send --to telegram:-1001234567890
hermes send --to discord:#ops --file /tmp/report.md
hermes send --to slack:#eng --subject "[CI]" --file build.log
hermes send --list                  # 所有平台
hermes send --list telegram         # 按平台过滤
```



## `hermes peer`

```bash
hermes peer add <name> --url http://host:port --key <API_SERVER_KEY>
hermes peer list
hermes peer dm <peer>[/<agent>] "message"
hermes peer run <peer>[/<agent>] --idempotency-key <key> "message"
hermes peer status <peer>[/<agent>] <run_id>
hermes peer stop <peer>[/<agent>] <run_id>
hermes peer remove <name>
```

跨机器的 bot 间私信。把另一个 Hermes gateway（任何运行 `api_server` 平台的机器）注册为*对等方（peer）*，然后向它的 agent 发消息：
`hermes peer dm` 会通过对等方的 API 服务器解析远程 agent 的规范 **Bot Chat** 会话，在那里运行一轮 agent，并在 stdout 上打印回复——它是本地
`hermes -p <bot> chat --in ~ -c "Bot Chat" …` bot 消息命令的跨机器版本。

单独的 `<peer>` 指向对等 gateway 的主 agent；
`<peer>/<agent>` 指向多路复用对等方上的某个具名 profile（通过其 `/p/<profile>/` 镜像路由）。

| 子命令 | 说明 |
|--------|-------------|
| `add <name> --url <URL> [--key <KEY>] [--note TEXT]` | 注册或更新一个对等方。URL 写入 `config.yaml`（`bot_peers`）；密钥以 `HERMES_PEER_<NAME>_KEY` 的形式保存在 `~/.hermes/.env` 中。 |
| `list` | 列出对等方以及每个对等方是否已配置密钥。 |
| `dm <peer>[/<agent>] [message]` | 向对等 agent 的规范 Bot Chat 发送消息并打印回复（`--json` 输出机器可读格式；未给出消息时回退到 stdin）。 |
| `run <peer>[/<agent>] [message]` | 异步启动一个较长的规范 Bot Chat 轮次，并返回其 `run_id`、会话 ID 和幂等键（支持 `--json`）。重试同一请求时请复用 `--idempotency-key`。 |
| `status <peer>[/<agent>] <run_id>` | 轮询一个异步的对等运行，并在完成时打印其最终输出（支持 `--json`）。 |
| `stop <peer>[/<agent>] <run_id>` | 精确停止该异步对等运行，而不会影响其他轮次（支持 `--json`）。 |
| `remove <name>` | 从注册表中删除对等方（`.env` 中的密钥条目保持不变）。 |

只要注册了至少一个对等方，向每个规范 Bot Chat 传授的 Bot Mode 消息协议
（`agent.bot_mode_protocol`）就会自动包含对等方名单和 `hermes peer dm` 用法，因此 agent 无需修改 SOUL 即可发现跨机器的队友。参见
[Bot Mode](../user-guide/bot-mode.md)。

退出码：成功为 `0`，投递/对等方失败为 `1`，用法错误为 `2`。

## `hermes secrets`

```bash
hermes secrets bitwarden <subcommand>
hermes secrets bw <subcommand>          # 简写别名
```

在进程启动时从外部密钥管理器拉取 API key，而不是把它们存放在 `~/.hermes/.env` 中。目前支持 **Bitwarden Secrets Manager**。完整指南参见 [Bitwarden 集成](../user-guide/secrets/bitwarden.md)。

`bitwarden`（别名 `bw`）子命令：

| 子命令 | 说明 |
|------------|-------------|
| `setup` | 交互式向导：安装固定版本的 `bws` 二进制文件、保存访问 token 并选择一个 project。支持 `--project-id`、`--access-token` 和 `--server-url` 以便非交互式使用。 |
| `status` | 显示当前配置、二进制文件路径/版本以及 token 校验状态。 |
| `token` | 轮换访问 token：在将新 token 存入 `.env` 之前先向 Bitwarden 校验它（被拒绝的 token 不会改变任何内容）。支持 `--access-token` 以便非交互式使用，`--no-verify` 可跳过探测。 |
| `sync` | 立即拉取密钥并报告变化。加上 `--apply` 才会真正把密钥导出到当前 shell 的环境中（默认为 dry-run）。 |
| `install` | 下载并校验固定版本的 `bws` 二进制文件。`--force` 会在已存在托管副本时仍重新下载。 |
| `disable` | 关闭 Bitwarden 集成。 |


## `hermes migrate`

```bash
hermes migrate <type>
```

诊断并（可选）重写当前的 `config.yaml`，替换对已下线模型或已弃用设置的引用。在任何重写之前都会为原始 `config.yaml` 生成带时间戳的备份（用 `--no-backup` 跳过）。

| 子命令 | 说明 |
|------------|-------------|
| `xai` | 扫描 `config.yaml` 中对将于 2026 年 5 月 15 日下线的 xAI 模型的引用，并（配合 `--apply`）按照 xAI 迁移指南就地重写为官方替代模型。默认为 dry-run。 |

迁移子命令的通用参数：

| 参数 | 说明 |
|------|-------------|
| `--apply` | 就地重写 `config.yaml`（默认：dry-run，不写入）。 |
| `--no-backup` | 应用时跳过 `config.yaml` 的带时间戳备份。 |

> 不要与 `hermes claw migrate`（将 OpenClaw 配置一次性导入 Hermes）混淆——`hermes migrate` 是顶级的配置重写命令。


## `hermes proxy`

```bash
hermes proxy <subcommand>
```

运行一个本地的 OpenAI 兼容 HTTP 服务器，把请求转发给经过 OAuth 认证的上游 provider（例如 Nous Portal、xAI）。外部应用可以用任意 bearer token 指向该代理；代理会在向外发送时附加你真实的 OAuth 凭据。完整指南参见 [订阅代理](../user-guide/features/subscription-proxy.md)。

| 子命令 | 说明 |
|------------|-------------|
| `start` | 在前台运行代理。参数：`--provider <nous\|xai>`（默认 `nous`）、`--host <addr>`（默认 `127.0.0.1`；用 `0.0.0.0` 可在局域网暴露）、`--port <int>`（默认 `8645`）。 |
| `status` | 显示哪些代理上游已就绪（凭据存在、OAuth 有效）。 |
| `providers` | 列出可用的代理上游 provider。 |


## `hermes security`

```bash
hermes security <subcommand>
```

针对 [OSV.dev](https://osv.dev) 的按需漏洞扫描。覆盖 Hermes venv（已安装的 PyPI 发行包）、`~/.hermes/plugins/` 下 plugin 声明的 Python 依赖，以及 `config.yaml` 中固定的 `npx`/`uvx` MCP 服务器。**不会**扫描全局安装的包或编辑器/浏览器扩展。

| 子命令 | 说明 |
|------------|-------------|
| `audit` | 运行一次性的供应链审计。 |

`audit` 参数：

| 参数 | 默认值 | 说明 |
|------|---------|-------------|
| `--json` | 关闭 | 输出机器可读的 JSON，而非人类可读的文本。 |
| `--fail-on <level>` | `critical` | 当有发现达到该严重级别（`low`、`moderate`、`high`、`critical`）时以非零码退出。 |
| `--skip-venv` | 关闭 | 跳过对 Hermes Python venv 的扫描。 |
| `--skip-plugins` | 关闭 | 跳过对 plugin 依赖文件的扫描。 |
| `--skip-mcp` | 关闭 | 跳过对 `config.yaml` 中固定 MCP 服务器的扫描。 |


## `hermes login` / `hermes logout` *（已弃用）*

:::caution
`hermes login` 已被移除。请使用 `hermes auth` 管理 OAuth 凭据，使用 `hermes model` 选择 provider，或使用 `hermes setup` 进行完整的交互式设置。
:::

## `hermes auth`

管理同一 provider 的密钥轮换凭据池。完整文档请参阅 [凭据池](/user-guide/features/credential-pools)。

```bash
hermes auth                                              # 交互式向导
hermes auth list                                         # 显示所有池
hermes auth list openrouter                              # 显示特定 provider
hermes auth add openrouter --api-key sk-or-v1-xxx        # 添加 API 密钥
hermes auth add anthropic --type oauth                   # 添加 OAuth 凭据
hermes auth add openai-codex --type oauth --priority 0   # 添加账号并优先尝试它
hermes auth remove openrouter 2                          # 按索引删除
hermes auth priority openrouter backup-key 0             # 将某个凭据移到 fill_first 顺序的最前面
hermes auth reset openrouter                             # 清除冷却时间
hermes auth reset openrouter 2                           # 清除单个凭据的冷却时间
hermes auth refresh openai-codex work                    # 刷新一个 OAuth 凭据并清除其冷却时间
hermes auth status anthropic                             # 显示某 provider 的认证状态
hermes auth logout anthropic                             # 登出并清除已存储的认证状态
hermes auth spotify                                      # 通过 PKCE 将 Hermes 与 Spotify 认证
```

子命令：`add`、`list`、`remove`、`reset`、`priority`、`refresh`、`status`、`logout`、`spotify`。不带子命令调用时，启动交互式管理向导。

## `hermes status`

```bash
hermes status [--all] [--deep]
```

| 选项 | 说明 |
|--------|-------------|
| `--all` | 以可分享的脱敏格式显示所有详情。 |
| `--deep` | 运行可能耗时更长的深度检查。 |

## `hermes cron`

```bash
hermes cron <list|create|edit|pause|resume|run|remove|status|runs|incidents|doctor|tick>
```

| 子命令 | 说明 |
|------------|-------------|
| `list` | 显示已调度的任务。 |
| `create` / `add` | 从 prompt 创建调度任务，可通过重复 `--skill` 附加一个或多个 skill。支持通过 `--reasoning-effort <none\|minimal\|low\|medium\|high\|xhigh\|max\|ultra>` 为单个任务固定推理强度。 |
| `edit` | 更新任务的调度、prompt、名称、投递方式、重复次数或附加的 skill。支持 `--clear-skills`、`--add-skill` 和 `--remove-skill`，以及 `--reasoning-effort`（空字符串会清除固定值）。 |
| `pause` | 暂停任务而不删除。 |
| `resume` | 恢复已暂停的任务并计算下次未来运行时间。 |
| `run` | 在下次调度器 tick 时触发任务。 |
| `remove` | 删除调度任务。 |
| `status` | 检查 cron 调度器是否正在运行。 |
| `doctor` | 只读的整体健康检查：失败的运行、失败的投递、已逾期/缺失的 `next_run_at`、缺失的脚本或工作目录。发现问题时以非零码退出。 |
| `tick` | 运行到期任务一次后退出。 |

cron **触发器**可通过 `cron.provider` 配置项替换。为空（默认）时使用内置的进程内 ticker。将其设为 `chronos`（面向缩容至零的托管 gateway 的 NAS 托管 provider）——通过
`cron.chronos.*` 配置项（`portal_url`、`callback_url`、`expected_audience`、
`nas_jwks_url`）配置——或在 `plugins/cron/<name>/` 或
`$HERMES_HOME/plugins/<name>/` 下指定自定义 provider。未知或不可用的 provider 会回退到内置实现，因此 cron 永远不会失去触发器。参见
[cron 内部机制](../developer-guide/cron-internals.md#gateway-integration) 文档。

## `hermes kanban`

```bash
hermes kanban [--board <slug>] <action> [options]
```

多 profile、多项目协作看板。每个安装可托管多个看板（每个项目、仓库或领域一个）；每个看板是独立的队列，拥有自己的 SQLite 数据库和调度器作用域。新安装从名为 `default` 的单个看板开始，其数据库为 `~/.hermes/kanban.db`（向后兼容）；其他看板位于 `~/.hermes/kanban/boards/<slug>/kanban.db`。嵌入在 gateway 中的调度器每次 tick 扫描所有看板。

**全局标志（适用于以下所有操作）：**

| 标志 | 用途 |
|------|---------|
| `--board <slug>` | 操作特定看板。默认为当前看板（通过 `hermes kanban boards switch`、`HERMES_KANBAN_BOARD` 环境变量或 `default` 设置）。 |

**这是人工/脚本操作界面。** 调度器生成的 agent worker 通过专用的 `kanban_*` [toolset](/user-guide/features/kanban#how-workers-interact-with-the-board)（`kanban_show`、`kanban_complete`、`kanban_request_review`、`kanban_request_changes`、`kanban_block`、`kanban_create`、`kanban_link`、`kanban_comment`、`kanban_heartbeat`；编排器 profile 还可使用 `kanban_list` 和 `kanban_unblock`）驱动看板，而非调用 `hermes kanban`。Worker 的环境中固定了 `HERMES_KANBAN_BOARD`，因此物理上无法看到其他看板。

| 操作 | 用途 |
|--------|---------|
| `init` | 如果缺少则创建 `kanban.db`。幂等操作。 |
| `boards list` / `boards ls` | 列出所有看板及任务数量。支持 `--json`、`--all`（包含已归档）。 |
| `boards create <slug>` | 创建新看板。标志：`--name`、`--description`、`--icon`、`--color`、`--switch`（设为活跃）。Slug 为 kebab-case，自动转小写。 |
| `boards switch <slug>` / `boards use` | 将 `<slug>` 持久化为活跃看板（写入 `~/.hermes/kanban/current`）。 |
| `boards show` / `boards current` | 打印当前活跃看板的名称、数据库路径和任务数量。 |
| `boards rename <slug> "<name>"` | 更改看板的显示名称。Slug 不可变。 |
| `boards rm <slug>` | 归档（默认）或硬删除看板。`--delete` 跳过归档步骤。已归档看板移至 `boards/_archived/<slug>-<ts>/`。`default` 看板拒绝此操作。 |
| `create "<title>"` | 在活跃看板上创建新任务。标志：`--body`、`--assignee`、`--parent`（可重复）、`--workspace scratch\|worktree\|dir:<path>`、`--tenant`、`--priority`、`--triage`、`--idempotency-key`、`--max-runtime`、`--max-retries`、`--skill`（可重复）。 |
| `list` / `ls` | 列出活跃看板上的任务。可用 `--mine`、`--assignee`、`--status`、`--tenant`、`--archived`、`--json` 过滤。 |
| `show <id>` | 显示任务及其评论和事件。`--json` 用于机器输出。 |
| `assign <id> <profile>` | 分配或重新分配。使用 `none` 取消分配。任务运行时拒绝此操作。 |
| `link <parent> <child>` | 添加依赖关系。检测循环依赖。两个任务必须在同一看板上。 |
| `unlink <parent> <child>` | 删除依赖关系。 |
| `claim <id>` | 原子性地认领就绪任务。打印已解析的工作区路径。 |
| `comment <id> "<text>"` | 追加评论。下一个认领该任务的 worker 会在其 `kanban_show()` 响应中读取到它。 |
| `complete <id>` | 将任务标记为完成。标志：`--result`、`--summary`、`--metadata`。 |
| `block <id> "<reason>"` | 将任务标记为等待人工输入。同时将原因追加为评论。 |
| `request-review <id>` | 将任务移入 `review` 并交给审查者——这**不是**阻塞。标志：`--summary`、`--metadata`、`--reviewer`（在分派审查前重新分配）。 |
| `request-changes <id> <reason>` | 审查者对进行中的审查运行给出的结论：结束该次审查尝试，并将任务退回给原实现者。 |
| `reopen-review <id>...` | 将处于审查中的任务退回修改（`review` → ready/todo）。标志：`--reason`（作为评论追加）。 |
| `schedule <id> "<reason>"` | 将时间延迟/后续工作停放到 `scheduled` 状态，使其不显示为人工阻塞项。 |
| `unblock <id>` | 将已阻塞的任务恢复到其来源阶段（`review` 或 `ready`），如果依赖仍未完成则恢复为 `todo`。 |
| `archive <id>` | 从默认列表中隐藏。`gc` 将删除 scratch 工作区。 |
| `tail <id>` | 跟踪任务的事件流。 |
| `dispatch` | 对活跃看板执行一次调度器扫描。标志：`--dry-run`、`--max N`、`--failure-limit N`、`--json`。 |
| `context <id>` | 打印 worker 将看到的完整上下文（标题 + 正文 + 父任务结果 + 评论）。 |
| `specify <id>` / `specify --all` | 通过辅助 LLM 将 triage 列中的任务细化为具体规格（标题 + 包含目标、方案、验收标准的正文），然后将其提升到 `todo`。标志：`--tenant`（将 `--all` 限定到一个 tenant）、`--author`、`--json`。在 `config.yaml` 的 `auxiliary.triage_specifier` 下配置模型。 |
| `decompose <id>` / `decompose --all` | 将 triage 列中的任务按描述拆分为子任务图，路由到专业 profile。当 LLM 判断任务不适合拆分时，回退到 specify 风格的单任务提升。与 `specify` 相同的标志。在 `config.yaml` 的 `auxiliary.kanban_decomposer` 下配置拆分器模型；`kanban.orchestrator_profile` 仅决定拆分后由谁拥有根/编排任务。当 `kanban.auto_decompose: true`（默认）时，每次调度器 tick 也会自动运行。参见 [自动与手动编排](/user-guide/features/kanban#auto-vs-manual-orchestration)。 |
| `gc` | 删除已归档任务的 scratch 工作区。 |

示例：

```bash
# 创建第二个看板并在不切换的情况下向其添加任务。
hermes kanban boards create atm10-server --name "ATM10 Server" --icon 🎮
hermes kanban --board atm10-server create "Restart server" --assignee ops

# 切换活跃看板以供后续调用使用。
hermes kanban boards switch atm10-server
hermes kanban list                  # 显示 atm10-server 的任务

# 归档看板（可恢复）或硬删除。
hermes kanban boards rm atm10-server
hermes kanban boards rm atm10-server --delete
```

看板解析顺序（优先级从高到低）：`--board <slug>` 标志 → `HERMES_KANBAN_BOARD` 环境变量 → `~/.hermes/kanban/current` 文件 → `default`。

所有操作也可作为 gateway 中的斜杠命令使用（`/kanban …`），参数界面相同——包括 `boards` 子命令和 `--board` 标志。

完整设计——与 Cline Kanban / Paperclip / NanoClaw / Gemini Enterprise 的对比、八种协作模式、四个用户故事、并发正确性证明——请参阅仓库中的 `docs/hermes-kanban-v1-spec.pdf` 或 [Kanban 用户指南](/user-guide/features/kanban)。

## `hermes egress`

面向远程终端沙箱的出站凭据注入防火墙。它封装了 [iron-proxy](https://github.com/ironsh/iron-proxy) 守护进程——一个进行 TLS 拦截的代理，会在网络边界把不透明的代理 token 替换为真实的上游 API 凭据，因此沙箱永远不会持有真实密钥。默认禁用；设置方法与架构请参阅完整的 [出站代理](../user-guide/egress/iron-proxy.md) 页面。

```bash
hermes egress install                  # 下载固定版本的 iron-proxy 二进制文件
hermes egress install --force          # 即使已安装也重新下载

hermes egress setup                    # 交互式向导：CA、映射、配置
hermes egress setup --tunnel-port N    # 覆盖隧道监听端口（默认 9090）
hermes egress setup --from-bitwarden   # 使用 Bitwarden Secrets Manager 作为凭据来源
hermes egress setup --no-bitwarden     # 显式切换回基于环境变量的凭据
hermes egress setup --rotate-tokens    # 生成新的代理 token（默认保留现有 token）

hermes egress start                    # 启动托管的代理守护进程
hermes egress stop                     # SIGTERM（5 秒宽限期后 SIGKILL）
hermes egress restart                  # 先停止（如在运行）再启动——密钥变更时需要
hermes egress reload                   # 通过回环管理 API 就地热重载规则集（不重启，
                                       #   不中断连接）

hermes egress status                   # 二进制 + 配置 + pid + 监听 + 映射
hermes egress status --show-tokens     # 完整打印代理 token（默认：脱敏）

hermes egress disable                  # 将 proxy.enabled 设为 false（不会停止正在运行的代理）
hermes egress config                   # 打印 proxy.yaml 的路径以便检查
```

### 常见流程 {#common-flows}

```bash
# 首次设置
export OPENROUTER_API_KEY=…
hermes egress setup && hermes egress start
hermes config set terminal.backend docker   # 如果尚未设置

# 事后切换凭据来源
hermes egress setup --from-bitwarden       # env → bitwarden
hermes egress setup --no-bitwarden         # bitwarden → env
# （不带这两个标志的 `setup` 会保留现有模式）

# 轮换所有 token（例如怀疑 token 泄露后）
hermes egress setup --rotate-tokens    # setup 会主动提出替你重启正在运行的守护进程
# （正在运行的沙箱仍持有旧 token；也要重启它们）

# 添加新的上游
# 编辑 ~/.hermes/config.yaml proxy.extra_allowed_hosts: [api.example.com]
hermes egress setup
hermes egress restart                  # 一条命令应用（stop + start）
```

### 诊断快捷方式 {#diagnostic-shortcuts}

```bash
hermes egress status                     # 在一个视图中查看当前状态
cat ~/.hermes/proxy/proxy.yaml           # 渲染后的 iron-proxy 配置
tail -20 ~/.hermes/proxy/iron-proxy.log  # 守护进程级诊断
tail -f ~/.hermes/proxy/iron-proxy.log | jq  # 守护进程 + 每请求日志（按行分隔的 JSON；v0.39 合并了两种流）
```

常见故障模式及恢复方法请参阅 [出站代理 → 故障排查](../user-guide/egress/iron-proxy.md#troubleshooting)。

## `hermes project`

```bash
hermes project <create|list|show|add-folder|remove-folder|rename|set-primary|use|archive|restore|bind-board>
```

project 是由人命名的工作区，可以跨越多个文件夹 / 仓库。它为桌面会话分组提供锚点，并在绑定看板后为任务提供确定的 worktree + 分支约定。状态按 profile 隔离。

| 子命令 | 说明 |
|------------|-------------|
| `create` | 创建新 project。 |
| `list`（别名 `ls`） | 列出 project。 |
| `show` | 显示某个 project 的详情。 |
| `add-folder` | 向 project 添加文件夹 / 仓库。 |
| `remove-folder` | 从 project 中移除文件夹。 |
| `rename` | 重命名 project。 |
| `set-primary` | 设置主文件夹。 |
| `use` | 设置活跃 project。 |
| `archive` | 归档 project（可恢复）。 |
| `restore` | 恢复已归档的 project。 |
| `bind-board` | 将看板绑定到此 project。 |

## `hermes webhook`

```bash
hermes webhook <subscribe|list|remove|test>
```

管理用于事件驱动 agent 激活的动态 webhook 订阅。需要在 config 中启用 webhook 平台——如未配置，将打印设置说明。

| 子命令 | 说明 |
|------------|-------------|
| `subscribe` / `add` | 创建 webhook 路由。返回要在你的服务上配置的 URL 和 HMAC 密钥。 |
| `list` / `ls` | 显示所有 agent 创建的订阅。 |
| `remove` / `rm` | 删除动态订阅。不影响 config.yaml 中的静态路由。 |
| `test` | 发送测试 POST 以验证订阅是否正常工作。 |

### `hermes webhook subscribe`

```bash
hermes webhook subscribe <name> [options]
```

| 选项 | 说明 |
|--------|-------------|
| `--prompt` | 带有 `{dot.notation}` payload 引用的 prompt 模板。 |
| `--events` | 要接受的逗号分隔事件类型（如 `issues,pull_request`）。为空则接受所有。 |
| `--description` | 人类可读的描述。 |
| `--skills` | 为 agent 运行加载的逗号分隔 skill 名称。 |
| `--deliver` | 投递目标：`log`（默认）、`telegram`、`discord`、`slack`、`github_comment`。 |
| `--deliver-chat-id` | 跨平台投递的目标聊天/频道 ID。 |
| `--secret` | 自定义 HMAC 密钥。省略时自动生成。 |
| `--deliver-only` | 跳过 agent——将渲染后的 `--prompt` 作为字面消息投递。零 LLM 成本，亚秒级投递。要求 `--deliver` 为真实目标（非 `log`）。 |
| `--script` | 位于 `~/.hermes/scripts/` 下的过滤/转换脚本。webhook payload 以 JSON 形式通过 stdin 传入；JSON stdout 会替换 payload，空 stdout、`[SILENT]` 或非零退出码会忽略该 webhook。参见[脚本过滤与转换](../user-guide/messaging/webhooks.md#script-filters-and-transforms)。 |

订阅持久化到 `~/.hermes/webhook_subscriptions.json`，webhook 适配器无需重启 gateway 即可热重载。

## `hermes doctor`

```bash
hermes doctor [--fix]
```

| 选项 | 说明 |
|--------|-------------|
| `--fix` | 尽可能尝试自动修复。 |

## `hermes dump`

```bash
hermes dump [--show-keys]
```

输出整个 Hermes 设置的紧凑纯文本摘要。专为复制粘贴到 Discord、GitHub issue 或 Telegram 寻求支持而设计——无 ANSI 颜色、无特殊格式，只有数据。

| 选项 | 说明 |
|--------|-------------|
| `--show-keys` | 显示脱敏的 API 密钥前缀（首尾各 4 个字符），而非仅显示 `set`/`not set`。 |

### 包含内容

| 部分 | 详情 |
|---------|---------|
| **Header** | Hermes 版本、发布日期、git commit hash |
| **Environment** | 操作系统、Python 版本、OpenAI SDK 版本 |
| **Identity** | 活跃 profile 名称、HERMES_HOME 路径 |
| **Model** | 已配置的默认模型和 provider |
| **Terminal** | 后端类型（local、docker、ssh 等） |
| **API keys** | 所有 22 个 provider/工具 API 密钥的存在性检查 |
| **Features** | 已启用的 toolset、MCP 服务器数量、memory provider |
| **Services** | Gateway 状态、已配置的消息平台 |
| **Workload** | Cron 任务数量、已安装 skill 数量 |
| **Config overrides** | 与默认值不同的所有 config 值 |

### 示例输出

```
--- hermes dump ---
version:          0.8.0 (2026.4.8) [af4abd2f]
os:               Linux 6.14.0-37-generic x86_64
python:           3.11.14
openai_sdk:       2.24.0
profile:          default
hermes_home:      ~/.hermes
model:            anthropic/claude-opus-4.6
provider:         openrouter
terminal:         local

api_keys:
  openrouter           set
  openai               not set
  anthropic            set
  nous                 not set
  firecrawl            set
  ...

features:
  toolsets:           all
  mcp_servers:        0
  memory_provider:    built-in
  gateway:            running (systemd)
  platforms:          telegram, discord
  cron_jobs:          3 active / 5 total
  skills:             42

config_overrides:
  agent.max_turns: 250
  compression.threshold: 0.85
  display.streaming: True
--- end dump ---
```

### 使用场景

- 在 GitHub 上报告 bug——将 dump 粘贴到 issue 中
- 在 Discord 中寻求帮助——在代码块中分享
- 与他人对比设置
- 出现问题时快速进行健全性检查

:::tip
`hermes dump` 专为分享而设计。交互式诊断请使用 `hermes doctor`。可视化概览请使用 `hermes status`。
:::

## `hermes debug`

```bash
hermes debug share [options]
```

将调试报告（系统信息 + 近期日志）上传到粘贴服务并获取可分享的 URL。适用于快速支持请求——包含帮助者诊断问题所需的一切信息。

| 选项 | 说明 |
|--------|-------------|
| `--lines <N>` | 每个日志文件包含的日志行数（默认：200）。 |
| `--expire <days>` | 粘贴过期天数（默认：7）。 |
| `--nous` | 上传到 Nous 内部诊断存储，而非公开粘贴服务。当 Nous 支持团队要求提供私有诊断包时使用。 |
| `--local` | 在本地打印报告而非上传。 |
| `--no-redact` | 关闭上传时的密钥脱敏。默认情况下上传内容会被脱敏。 |

报告包含系统信息（操作系统、Python 版本、Hermes 版本）、近期的 agent、gateway、GUI/控制台和桌面日志（每文件 512 KB 限制）以及脱敏的 API 密钥状态。默认情况下上传内容会被脱敏，因此不会包含密钥。

默认上传使用公开粘贴服务，依次尝试：paste.rs、dpaste.com。`--nous` 则将同一份调试包上传到私有的 Nous 诊断存储；返回的查看链接供 Nous 团队使用，并会在 14 天后自动删除。

### 示例

```bash
hermes debug share              # 上传调试报告，打印 URL
hermes debug share --lines 500  # 包含更多日志行
hermes debug share --expire 30  # 粘贴保留 30 天
hermes debug share --nous       # 为 Nous 支持上传私有诊断包
hermes debug share --local      # 在终端打印报告（不上传）
```

## `hermes backup`

```bash
hermes backup [options]
```

创建 Hermes 配置、skill、会话和数据的 zip 归档。备份不包含 hermes-agent 代码库本身，也不会嵌套之前的备份产物（`backups/`、`state-snapshots/`）——它们各自已经包含一份 `state.db` 副本。

| 选项 | 说明 |
|--------|-------------|
| `-o`, `--output <path>` | zip 文件的输出路径（默认：`~/hermes-backup-<timestamp>.zip`）。 |
| `-q`, `--quick` | 快速快照：仅包含关键状态文件（config.yaml、state.db、.env、auth、cron 任务）。比完整备份快得多。 |
| `-l`, `--label <name>` | 快照标签（仅与 `--quick` 配合使用）。 |
| `-k`, `--keep <N>` | 完整备份完成后，删除输出目录中超出最新 N 个的较旧 `hermes-backup-*.zip` 文件（默认 3；`0` 表示全部保留）。自定义命名的 zip 永远不会被触及。 |

备份使用 SQLite 的 `backup()` API 进行安全复制，因此即使 Hermes 正在运行也能正确工作（WAL 模式安全）。

**zip 中排除的内容：**

- `*.db-wal`、`*.db-shm`、`*.db-journal` — SQLite 的 WAL/共享内存/日志附属文件。`*.db` 文件已通过 `sqlite3.backup()` 获得一致快照；将活跃附属文件一并打包会导致恢复时看到半提交状态。
- `checkpoints/` — 每会话轨迹缓存。以 hash 为键，每次会话重新生成；无论如何都无法干净地移植到其他安装。
- `hermes-agent` 代码本身（这是用户数据备份，不是仓库快照）。

### 示例

```bash
hermes backup                           # 完整备份到 ~/hermes-backup-*.zip
hermes backup -o /tmp/hermes.zip        # 完整备份到指定路径
hermes backup --quick                   # 仅状态快速快照
hermes backup --quick --label "pre-upgrade"  # 带标签的快速快照
```

## `hermes checkpoints`

```bash
hermes checkpoints [COMMAND]
```

检查和管理 `~/.hermes/checkpoints/` 处的影子 git 存储——会话内 `/rollback` 命令的存储层。可随时安全运行；不需要 agent 正在运行。

| 子命令 | 说明 |
|------------|-------------|
| `status`（默认） | 显示总大小、项目数量和每个项目的详情。裸 `hermes checkpoints` 等同于此。 |
| `list` | `status` 的别名。 |
| `prune` | 强制执行清理——删除孤立和过期项目，GC 存储，强制执行大小上限。忽略 24 小时幂等性标记。 |
| `clear` | 删除整个 checkpoint 基础存储。不可逆；除非使用 `-f` 否则要求确认。 |
| `clear-legacy` | 仅删除 v1→v2 迁移产生的 `legacy-<timestamp>/` 归档。 |

### 选项

| 选项 | 子命令 | 说明 |
|--------|------------|-------------|
| `--limit N` | `status`、`list` | 最多列出的项目数（默认 20）。 |
| `--retention-days N` | `prune` | 删除 `last_touch` 早于 N 天的项目（默认 7）。 |
| `--max-size-mb N` | `prune` | 在孤立/过期清理后，删除每个项目最旧的 commit，直到总存储大小 ≤ N MB（默认 500）。 |
| `--keep-orphans` | `prune` | 跳过删除工作目录不再存在的项目。 |
| `-f`, `--force` | `clear`、`clear-legacy` | 跳过确认提示。 |

### 示例

```bash
hermes checkpoints                                  # 状态概览
hermes checkpoints prune --retention-days 3         # 激进清理
hermes checkpoints prune --max-size-mb 200          # 一次性收紧大小上限
hermes checkpoints clear-legacy -f                  # 删除 v1 归档目录
hermes checkpoints clear -f                         # 清除所有内容
```

完整架构和会话内命令，请参阅 [Checkpoints 与 `/rollback`](../user-guide/checkpoints-and-rollback.md)。

## `hermes import`

```bash
hermes import <zipfile> [options]
```

将之前创建的 Hermes 备份恢复到 Hermes 主目录。归档中的所有文件会覆盖 Hermes 主目录中的现有文件；`--force` 仅跳过当目标已有 Hermes 安装时触发的确认提示。

| 选项 | 说明 |
|--------|-------------|
| `-f`, `--force` | 跳过已有安装的确认提示。 |

:::warning
导入前请停止 gateway，以避免与正在运行的进程冲突。
:::

### SQLite 数据库 {#sqlite-databases}

`.db` 成员（`state.db`、`kanban.db`、`response_store.db`……）不会像普通文件那样通过重命名来发布。重命名会替换文件的 inode，而 gateway、控制台或 WebUI 进程可能仍然打开着旧的 inode：该进程会继续读取导入前的页面，并继续写入其他人都看不到的会话，而这些会话在下一次所有人打开的数据库中会直接消失——并且不会留下任何日志。因此，导入的页面会**写入现有的数据库文件中**，方式与 `/snapshot restore` 相同，这样每个已打开的连接都会收敛到导入的数据上。

如果无法安全地替换正在使用的数据库——页面复制失败，*并且*另一个进程仍然打开着该文件——导入会保持该数据库不变，并将其列在 `Warnings (N files skipped)` 下。停止占用它的进程后重新运行即可。

用较旧的备份覆盖较新的工作仍然是允许的，但不再是静默进行。当导入的 `state.db` 包含的消息少于被替换的数据库时，摘要会报告这一点：

```
  ⚠ Session data replaced by older backup contents:
    state.db: 12 session(s) / 8912 message(s) -> 3 / 24
    Anything recorded after the backup was taken is not in it.
    Recover from a newer backup or snapshot: hermes snapshot list
```

### 示例
```bash
hermes import ~/hermes-backup-20260423.zip           # 覆盖现有配置前提示确认
hermes import ~/hermes-backup-20260423.zip --force   # 不提示直接覆盖
```

## `hermes logs`

```bash
hermes logs [log_name] [options]
```

查看、跟踪和过滤 Hermes 日志文件。所有日志存储在 `~/.hermes/logs/`（非默认 profile 存储在 `<profile>/logs/`）。

### 日志文件

| 名称 | 文件 | 记录内容 |
|------|------|-----------------|
| `agent`（默认） | `agent.log` | 所有 agent 活动——API 调用、工具调度、会话生命周期（INFO 及以上） |
| `errors` | `errors.log` | 仅警告和错误——agent.log 的过滤子集 |
| `gateway` | `gateway.log` | 消息 gateway 活动——平台连接、消息调度、webhook 事件 |
| `gui` | `gui.log` | 控制台 / TUI-gateway / PTY 桥接 / websocket 事件 |
| `desktop` | `desktop.log` | Electron 桌面应用——启动、后端进程输出以及近期的 Python traceback |

### 选项

| 选项 | 说明 |
|--------|-------------|
| `log_name` | 要查看的日志：`agent`（默认）、`errors`、`gateway`，或 `list` 以显示可用文件及大小。 |
| `-n`, `--lines <N>` | 显示的行数（默认：50）。 |
| `-f`, `--follow` | 实时跟踪日志，类似 `tail -f`。按 Ctrl+C 停止。 |
| `--level <LEVEL>` | 显示的最低日志级别：`DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`。 |
| `--session <ID>` | 过滤包含会话 ID 子字符串的行。 |
| `--since <TIME>` | 显示相对时间之前的行：`30m`、`1h`、`2d` 等。支持 `s`（秒）、`m`（分钟）、`h`（小时）、`d`（天）。 |
| `--component <NAME>` | 按组件过滤：`gateway`、`agent`、`tools`、`cli`、`cron`。 |

### 示例

```bash
# 查看 agent.log 的最后 50 行（默认）
hermes logs

# 实时跟踪 agent.log
hermes logs -f

# 查看 gateway.log 的最后 100 行
hermes logs gateway -n 100

# 仅显示最近一小时的警告和错误
hermes logs --level WARNING --since 1h

# 按特定会话过滤
hermes logs --session abc123

# 从 30 分钟前开始跟踪 errors.log
hermes logs errors --since 30m -f

# 列出所有日志文件及其大小
hermes logs list
```

### 过滤

过滤器可以组合使用。当多个过滤器同时激活时，日志行必须通过**所有**过滤器才会显示：

```bash
# 最近 2 小时内包含会话 "tg-12345" 的 WARNING+ 行
hermes logs --level WARNING --since 2h --session tg-12345
```

当 `--since` 激活时，没有可解析时间戳的行会被包含（它们可能是多行日志条目的续行）。当 `--level` 激活时，没有可检测级别的行会被包含。

### 日志轮转

Hermes 使用 Python 的 `RotatingFileHandler`。旧日志会自动轮转——查找 `agent.log.1`、`agent.log.2` 等。`hermes logs list` 子命令显示所有日志文件，包括已轮转的。


## `hermes prompt-size`

```bash
hermes prompt-size [--platform <name>] [--json]
```

报告一个全新会话的固定 prompt 预算——即在任何对话内容*之前*，每次 API 调用都会发送的部分。当下游适配器或代理的 prompt 预算比模型上下文窗口更紧张时，或你想看清哪一块（skill 索引、记忆、profile）占主导时，它很有用。

它会构建与 agent 相同的系统 prompt，然后拆解它：

- **系统 prompt 总计** —— 完整拼装后的 prompt（身份、指导、skill 索引、上下文文件、记忆、profile、时间戳）。
- **Skill 索引** —— `<available_skills>` 块。安装很多 skill 时，它往往是最大的单一块。
- **记忆**和**用户 profile** —— 你的 `MEMORY.md` / `USER.md` 快照。
- **Prompt 层级** —— stable / context / volatile，对应 Hermes 为缓存友好而分层 prompt 的方式。
- **工具 schema** —— 所有已启用工具的 JSON（固定每次调用负载的另一半）。

完全离线运行——不调用 API，即使未配置任何凭据也能工作。

```bash
# 面向 CLI 平台的人类可读拆解（默认）
hermes prompt-size

# 模拟某个消息平台的 prompt（不同平台提示）
hermes prompt-size --platform telegram

# 供脚本使用的机器可读输出
hermes prompt-size --json
```

:::tip
skill 索引和工具 schema 会随你启用的 skill 和工具数量而增长。要缩小 prompt，可禁用用不到的工具集（`hermes tools`）或卸载不需要的 skill（`hermes skills`）。当前目录中的上下文文件（AGENTS.md、.cursorrules）也计入总量。
:::

## `hermes config`

```bash
hermes config <subcommand>
```

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `show` | 显示当前 config 值。 |
| `edit` | 在编辑器中打开 `config.yaml`。 |
| `get <key> [--json]` | 按点分隔的键打印单个 config 值（例如 `hermes config get model.default`）。`--json` 输出机器可读格式。 |
| `set <key> <value>` | 设置 config 值。 |
| `unset <key>` | 删除某个 config 键，使其恢复为内置默认值。 |
| `path` | 打印 config 文件路径。 |
| `env-path` | 打印 `.env` 文件路径。 |
| `check` | 检查缺失或过期的 config。 |
| `migrate` | 交互式添加新引入的选项。 |

### 键名中的点号 {#dots-inside-key-names}

`hermes config set/get/unset` 使用 `.` 作为嵌套分隔符，但很多真实的键名本身就包含字面点号——模型 ID（`grok-4.6`、`glm-5.3-flash`）、Matrix 房间 ID（`!room:example.org`）、带版本号的 provider 名称。以下两条规则让这些键可以被寻址：

- **已存在的键直接可用。** 在已存在的映射中导航时，与剩余的点分路径相匹配的已有字面键优先于拆分。`hermes config set providers.p.models.grok-4.6.supports_vision true`
  会更新真实的 `grok-4.6` 条目（`get`/`unset` 的解析方式相同）。
- **创建新的带点号的键需要转义。** 用反斜杠转义字面点号：`hermes config set 'providers.p.models.grok-4\.7.context_length' 128000`
  会创建字面键 `grok-4.7`。（请给键加上引号，以便 shell 保留反斜杠。）

如果一次未转义的写入会创建一个遮蔽已有带点号同级键的嵌套映射（例如在已有的 `grok-4.6` 旁边创建 `grok-4`），命令会报错失败，而不是静默写入一个运行时永远不会读取的幽灵条目。

## `hermes pairing`

```bash
hermes pairing <list|approve|revoke|clear-pending>
```

| 子命令 | 说明 |
|------------|-------------|
| `list` | 显示待处理和已审批的用户。 |
| `approve <platform> <code>` | 审批配对码。 |
| `revoke <platform> <user-id>` | 撤销用户的访问权限。 |
| `clear-pending` | 清除待处理的配对码。 |

## `hermes skills`

```bash
hermes skills <subcommand>
```

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `browse` | 分页浏览 skill 注册表。 |
| `search` | 搜索 skill 注册表。 |
| `install` | 安装 skill。 |
| `inspect` | 预览 skill 而不安装。 |
| `list` | 列出已安装的 skill。 |
| `check` | 检查已安装的 hub skill 是否有上游更新。 |
| `update` | 在有上游变更时重新安装 hub skill。 |
| `audit` | 重新扫描已安装的 hub skill。 |
| `uninstall` | 删除通过 hub 安装的 skill。 |
| `reset` | 通过清除 manifest 条目，取消将捆绑 skill 标记为 `user_modified` 的状态。使用 `--restore` 时，还会将用户副本替换为捆绑版本。 |
| `opt-out` | 阻止将捆绑 skill 播种到当前 profile。它会写入一个 `.no-bundled-skills` 标记，使安装程序、`hermes update` 以及任何同步都跳过捆绑 skill 的播种。默认是安全的——磁盘上的任何内容都不会被触及。加上 `--remove` 时，还会删除已存在且**未被修改**的捆绑 skill（用户编辑过的、从 hub 安装的和手写的 skill 永远不会被删除；会先预览并确认，用 `--yes` 可跳过）。 |
| `opt-in` | 通过删除 `.no-bundled-skills` 标记来撤销 `opt-out`，使捆绑 skill 在下一次 `hermes update` 时重新播种。加上 `--sync` 可立即重新播种。 |
| `publish` | 将 skill 发布到注册表。 |
| `snapshot` | 导出/导入 skill 配置。 |
| `tap` | 管理自定义 skill 来源。 |
| `config` | 按平台交互式启用/禁用 skill 配置。 |

常用示例：

```bash
hermes skills browse
hermes skills browse --source official
hermes skills search react --source skills-sh
hermes skills search https://mintlify.com/docs --source well-known
hermes skills inspect official/security/1password
hermes skills inspect skills-sh/vercel-labs/json-render/json-render-react
hermes skills install official/migration/openclaw-migration
hermes skills install skills-sh/anthropics/skills/pdf --force
hermes skills install https://sharethis.chat/SKILL.md                     # 直接 URL（含引用的支持文件）
hermes skills install https://example.com/SKILL.md --name my-skill        # frontmatter 无名称时覆盖名称
hermes skills check
hermes skills update
hermes skills config
hermes skills reset google-workspace
hermes skills reset google-workspace --restore --yes
hermes skills opt-out                  # 停止今后的捆绑 skill 播种（不删除任何内容）
hermes skills opt-out --remove --yes   # 同时删除未修改的捆绑 skill
hermes skills opt-in --sync            # 撤销：删除标记并立即重新播种
```

注意：
- `--force` 可以覆盖第三方/社区 skill 的非危险性策略阻止。
- `--force` 不覆盖 `dangerous` 扫描结论。
- `--source skills-sh` 搜索公共 `skills.sh` 目录。
- `--source well-known` 允许你将 Hermes 指向暴露 `/.well-known/skills/index.json` 的站点。
- `--source browse-sh` 搜索 [browse.sh](https://browse.sh) 包含 200+ 站点特定浏览器自动化 skill 的目录。标识符形如 `browse-sh/airbnb.com/search-listings-ddgioa`。
- 传入 `http(s)://…/*.md` URL 可安装 `SKILL.md`，以及其中明确引用且位于 `references/`、`templates/`、`scripts/`、`assets/` 和 `examples/` 下的文件。当 frontmatter 没有 `name:` 且 URL slug 不是有效标识符时，交互式终端会提示输入名称；非交互式界面（TUI 内的 `/skills install`、gateway 平台）需要改用 `--name <x>`。

## `hermes bundles`

```bash
hermes bundles <subcommand>
```

Skill bundle 将多个 skill 归组到一个 `/<bundle-name>` 斜杠命令下。调用 bundle 会将每个引用的 skill 加载到单个合并的用户消息中。存储位置：`~/.hermes/skill-bundles/<slug>.yaml`。YAML schema 和行为请参阅 [Skill Bundles](../user-guide/features/skills.md#skill-bundles)。

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `list` | 列出已安装的 bundle（不带子命令时的默认行为） |
| `show <name>` | 显示某个 bundle 的名称、描述、skill 和文件路径 |
| `create <name>` | 创建新 bundle。传入 `--skill <id>`（可重复）或省略以进行交互式输入。支持 `--description`、`--instruction`、`--force`。 |
| `delete <name>` | 删除 bundle 文件 |
| `reload` | 重新扫描 `~/.hermes/skill-bundles/` 并报告新增/删除的 bundle |

示例：

```bash
hermes bundles create backend-dev \
  --skill github-code-review \
  --skill test-driven-development \
  --skill github-pr-workflow \
  -d "Backend feature work"

hermes bundles list
hermes bundles show backend-dev
hermes bundles delete backend-dev
```

在聊天会话中，`/bundles` 列出已安装的 bundle，`/<bundle-name>` 加载某个 bundle。

## `hermes curator`

```bash
hermes curator <subcommand>
```

Curator 是一个辅助模型后台任务，定期审查 agent 创建的 skill，修剪过期的，合并重叠的，并归档过时的。捆绑和通过 hub 安装的 skill 不会被触及。归档可恢复；不会发生自动删除。

| 子命令 | 说明 |
|------------|-------------|
| `status` | 显示 curator 状态和 skill 统计 |
| `run` | 立即触发 curator 审查（阻塞直到 LLM 处理完成） |
| `run --background` | 在后台线程中启动 LLM 处理并立即返回 |
| `run --dry-run` | 仅预览——生成审查报告但不进行任何修改 |
| `backup` | 手动对 `~/.hermes/skills/` 进行 tar.gz 快照（curator 在每次真实运行前也会自动快照） |
| `rollback` | 从快照恢复 `~/.hermes/skills/`（默认使用最新快照） |
| `rollback --list` | 列出可用快照 |
| `rollback --id <ts>` | 按 id 恢复特定快照 |
| `rollback -y` | 跳过确认提示 |
| `pause` | 暂停 curator 直到恢复 |
| `resume` | 恢复已暂停的 curator |
| `pin <skill>` | 固定 skill，使 curator 永不自动转换其状态 |
| `unpin <skill>` | 取消固定 skill |
| `restore <skill>` | 恢复已归档的 skill |
| `archive <skill>` | 手动归档 skill |
| `prune` | 手动修剪 curator 通常会清理的 skill |
| `list-archived` | 列出已归档的 skill（可通过 `restore` 恢复） |

在全新安装时，第一次计划运行会延迟一个完整的 `interval_hours`（默认 7 天）——gateway 不会在 `hermes update` 后的第一次 tick 时立即执行 curator。使用 `hermes curator run --dry-run` 在此之前预览。

行为和配置请参阅 [Curator](../user-guide/features/curator.md)。

## `hermes moa`

配置具名的 Mixture of Agents 预设。预设会作为可选模型出现在每个模型选择器的 `Mixture of Agents` provider 下；`/moa <prompt>` 会用默认预设运行一次 prompt。

```bash
hermes moa list
hermes moa configure [name]
hermes moa delete <name>
```

`hermes moa configure` 会为每个参考模型和聚合器复用 Hermes 的 provider → 模型选择器。预设是一种执行模式配置，而不是主模型或 provider。

## `hermes fallback`

```bash
hermes fallback <subcommand>
```

管理 fallback provider 链。当主模型因速率限制、过载或连接错误而失败时，按顺序尝试 fallback provider。

| 子命令 | 说明 |
|------------|-------------|
| `list`（别名：`ls`） | 显示当前 fallback 链（不带子命令时的默认行为） |
| `add` | 选择 provider + 模型（与 `hermes model` 相同的选择器）并追加到链末尾 |
| `remove`（别名：`rm`） | 选择要从链中删除的条目 |
| `clear` | 删除所有 fallback 条目 |

参见 [Fallback Providers](../user-guide/features/fallback-providers.md)。

## `hermes hooks`

```bash
hermes hooks <subcommand>
```

检查 `~/.hermes/config.yaml` 中声明的 shell 脚本 hook，针对合成 payload 测试它们，并管理 `~/.hermes/shell-hooks-allowlist.json` 处的首次使用同意许可名单。

| 子命令 | 说明 |
|------------|-------------|
| `list`（别名：`ls`） | 列出已配置的 hook 及其匹配器、超时和同意状态 |
| `test <event>` | 针对合成 payload 触发匹配 `<event>` 的所有 hook |
| `revoke`（别名：`remove`、`rm`） | 删除某个命令的许可名单条目（下次重启后生效） |
| `doctor` | 检查每个已配置的 hook：可执行位、许可名单、mtime 漂移、JSON 有效性和合成运行计时 |

事件签名和 payload 格式请参阅 [Hooks](../user-guide/features/hooks.md)。

## `hermes memory`

```bash
hermes memory <subcommand>
```

设置和管理外部 memory provider plugin。可用 provider：honcho、openviking、mem0、hindsight、holographic、retaindb、byterover、supermemory。同一时间只能有一个外部 provider 处于活跃状态。内置 memory（MEMORY.md/USER.md）始终处于活跃状态。

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `setup` | 交互式 provider 选择和配置。 |
| `status` | 显示当前 memory provider 配置。 |
| `off` | 禁用外部 provider（仅使用内置）。 |

:::info Provider 特定子命令
当外部 memory provider 处于活跃状态时，它可能会注册自己的顶级 `hermes <provider>` 命令用于 provider 特定管理（例如 Honcho 激活时的 `hermes honcho`）。未激活的 provider 不暴露其子命令。运行 `hermes --help` 查看当前已连接的命令。
:::

## `hermes acp`

```bash
hermes acp
```

将 Hermes 作为 ACP（Agent Client Protocol）stdio 服务器启动，用于编辑器集成。

相关入口：

```bash
hermes-acp
python -m acp_adapter
```

首先安装支持：

```bash
cd ~/.hermes/hermes-agent && uv pip install -e '.[acp]'
```

参见 [ACP 编辑器集成](../user-guide/features/acp.md) 和 [ACP 内部原理](../developer-guide/acp-internals.md)。

## `hermes mcp`

```bash
hermes mcp <subcommand>
```

管理 MCP（Model Context Protocol）服务器配置，并将 Hermes 作为 MCP 服务器运行。

| 子命令 | 说明 |
|------------|-------------|
| *（无）* 或 `picker` | 交互式目录选择器——浏览 Nous 认可的 MCP 并安装/启用/禁用。 |
| `catalog` | 列出 Nous 认可的 MCP（纯文本，可脚本化）。 |
| `install <name>` | 安装一个目录条目（例如 `hermes mcp install n8n`）。 |
| `serve [-v\|--verbose]` | 将 Hermes 作为 MCP 服务器运行——向其他 agent 暴露对话。 |
| `add <name> [--url URL] [--command CMD] [--auth oauth\|header] [--args ...]` | 添加自定义 MCP 服务器并自动发现工具。`--args` 会把其余 argv 传给 stdio 命令，因此请把它放在最后。 |
| `remove <name>`（别名：`rm`） | 从 config 中删除 MCP 服务器。 |
| `list`（别名：`ls`） | 列出已配置的 MCP 服务器。 |
| `test <name>` | 测试与 MCP 服务器的连接。 |
| `configure <name>`（别名：`config`） | 切换服务器的工具选择。 |
| `login <name>` | 强制重新认证基于 OAuth 的 MCP 服务器。 |

参见 [MCP 配置参考](./mcp-config-reference.md)、[在 Hermes 中使用 MCP](../guides/use-mcp-with-hermes.md) 和 [MCP 服务器模式](../user-guide/features/mcp.md#running-hermes-as-an-mcp-server)。

## `hermes plugins`

```bash
hermes plugins [subcommand]
```

统一的 plugin 管理——通用 plugin、memory provider 和 context engine 集于一处。不带子命令运行 `hermes plugins` 会打开包含两个部分的复合交互界面：

- **General Plugins** — 多选复选框，用于启用/禁用已安装的 plugin
- **Provider Plugins** — 单选配置，用于 Memory Provider 和 Context Engine。在某个类别上按 ENTER 打开单选选择器。

| 子命令 | 说明 |
|------------|-------------|
| *（无）* | 复合交互界面——通用 plugin 切换 + provider plugin 配置。 |
| `install <identifier> [--force] [--ref COMMIT_SHA] [--allow-removed]` | 从 Hermes plugin 目录（裸条目名）、Git URL 或 `owner/repo` 简写安装 plugin。目录名称会解析为该条目的仓库及其固定的 40 位十六进制 commit SHA，显示声明的能力摘要，并在 `.hermes-catalog.json` 附属文件中记录目录来源。原始 URL 会被标记为自定义（未经审核）来源；`--ref`（完整的 40 字符 commit SHA）可将其固定。`--allow-removed`（危险）会绕过已移除 plugin 的阻止列表。 |
| `search [term] [--json]` | 搜索 Hermes plugin 目录（匹配条目名称、描述和声明的工具；省略 `term` 则列出全部）。目录在仓库内维护（`plugin-catalog/`），从线上仓库刷新并缓存 6 小时，离线时回退到仓库内的副本。收录进目录 ≠ 经过审计——收录审核的是条目，而不是代码。 |
| `update <name>` | 为未固定版本的已安装 plugin 拉取最新变更。已固定版本的 plugin 必须用 `--force --ref <new-commit>` 重新安装才能变更版本。 |
| `remove <name>`（别名：`rm`、`uninstall`） | 删除已安装的 plugin。 |
| `enable <name>` | 启用已禁用的 plugin。 |
| `disable <name>` | 禁用 plugin 而不删除。 |
| `list`（别名：`ls`） | 列出已安装的 plugin 及启用/禁用状态。 |
| `doctor [path-or-id] [--ci]` | 通过真实的 manifest 解析器、加载器和注册路径校验原生 plugin。`--ci` 在出错时以 1 退出。 |
| `pack install <path-or-url> [--force]` | 安装一个 plugin 包（`hermes-pack.yaml`）——一组声明式的 plugin，每个都固定到精确的 40 字符 commit SHA。会显示强制性的审查界面（每个 plugin、来源、固定的 ref、声明的能力），对包内容请求一次确认，然后执行常规的固定版本安装。每个 plugin 声明的能力仍需经过标准的逐个 plugin 同意流程——包永远不会批量授权。部分失败会按 plugin 逐一报告；任何 plugin 失败时以非零码退出。仅支持交互式（没有 `--yes`）。 |
| `pack export [--enabled-only] [--name NAME]` | 根据当前安装在 stdout 上输出一个包 YAML：每个通过 git 安装的 plugin 的仓库 + 精确 SHA，以及经过清理的非机密 `plugins.entries` 配置。仅本地的 plugin（没有 git 来源）会以警告注释的形式列出，永远不会作为可安装条目。机密、能力授权和 `allow_*` 开关总是会被剥离。 |
| `pack show <path-or-url>` | 空运行：解析、校验并显示一个包，而不安装任何内容。 |

Provider plugin 选择保存到 `config.yaml`：
- `memory.provider` — 活跃 memory provider（为空 = 仅内置）
- `context.engine` — 活跃 context engine（`"compressor"` = 内置默认值）

通用 plugin 禁用列表存储在 `config.yaml` 的 `plugins.disabled` 下。
Git 安装还会在 profile 本地的 `plugins/.install-metadata.json` 附属文件中仅记录其规范来源、精确的已安装修订版本以及固定状态。它不包含 plugin 配置、环境变量值、机密或能力授权。

参见 [Plugins](../user-guide/features/plugins.md) 和 [构建 Hermes Plugin](../developer-guide/plugins/index.md)。

## `hermes tools`

```bash
hermes tools [--summary]
```

| 选项 | 说明 |
|--------|-------------|
| `--summary` | 打印当前已启用工具摘要并退出。 |

不带 `--summary` 时，启动交互式按平台工具配置界面。

## `hermes computer-use`

```bash
hermes computer-use <subcommand>
```

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `install` | 运行上游 cua-driver 安装程序（macOS、Windows 和 Linux）。 |
| `install --upgrade` | 即使 cua-driver 已在 PATH 中也重新运行安装程序。上游脚本始终拉取最新版本，因此这会执行原地升级。 |
| `status` | 打印 `cua-driver` 是否在 `$PATH` 中以及已安装的版本。 |
| `doctor [--include CHECK] [--skip CHECK] [--json]` | 运行 cua-driver 的健康报告并显示其平台检查项。 |
| `permissions status [--json]` | 报告 macOS 辅助功能和屏幕录制授权情况。 |
| `permissions grant` | 请求 macOS 为 Cua Driver 授予辅助功能和屏幕录制权限。 |

`hermes computer-use install` 是安装
`computer_use` toolset 所使用的 [cua-driver](https://github.com/trycua/cua) 二进制文件的稳定入口。它运行与首次启用 Computer Use 时 `hermes tools` 调用的相同上游安装程序，因此如果 toolset 切换未触发安装（例如在已配置用户的设置中），可以安全地用于重新运行安装。

如果 cua-driver 已经存在，Hermes 会检查其版本和运行时清单。兼容的 0.20.0 或更新版本的安装会保持不变。过旧或不完整的标准安装会通过当前的上游安装程序修复。Hermes 永远不会替换通过
`HERMES_CUA_DRIVER_CMD` 选定的自定义二进制文件；请直接更新该二进制文件，或移除该覆盖设置。
`hermes computer-use status` 会报告何时需要修复。

内置的 `computer_use` toolset 是推荐的 Hermes 集成方式。当你需要 Cua 的底层工具词汇时，注册原始的 Cua MCP 工具是一种替代方案。`cua-driver skills install` 会检测 Hermes，并自动将 Cua 的技能包链接到 Hermes 的 skills 目录中。

权限模式和能力清单审批属于运行时启动的范畴。在 bounded 模式下，Hermes 会传入 Cua 规范的
`--capability-manifest` 和 `--approve-capability-manifest` 标志。每个 MCP 传输在其运行时内部拥有一个私有的生命周期会话。公开的会话名称只用于标记光标和会话状态；它们并不拥有或共享运行时。

`hermes update` 在更新结束时，如果 cua-driver 在 PATH 中，会自动重新运行上游安装程序，因此大多数用户不需要手动调用 `--upgrade`。当上游发布了你现在就想要的修复，而不想等待下次 Hermes 更新时，使用此选项。

## `hermes pets`

```bash
hermes pets <list|install|select|show|off|scale|remove|doctor>
```

[Petdex](https://github.com/crafter-station/petdex) 是一个面向编码 agent 的动画像素宠物公共图库。安装一只之后，Hermes 会在 CLI、TUI 和桌面应用中展示它对 agent 活动的反应。

| 子命令 | 说明 |
|------------|-------------|
| `list` | 浏览 petdex 图库。 |
| `install` | 从图库安装一只宠物。 |
| `select` | 设置活跃宠物（写入 `display.pet.*`）。 |
| `show` | 在终端中播放活跃宠物的动画。 |
| `off` | 禁用宠物显示。 |
| `scale` | 在所有位置调整宠物大小（`display.pet.scale`）。 |
| `remove` | 删除已安装的宠物。 |
| `doctor` | 检查宠物设置与终端图形支持。 |

你也可以用 `/hatch` 斜杠命令从一段文字描述生成一只全新的宠物。参见 [宠物](../user-guide/features/pets.md)。

## `hermes sessions`

```bash
hermes sessions <subcommand>
```

子命令：

| 子命令 | 说明 |
|------------|-------------|
| `list` | 列出最近的会话。 |
| `browse` | 带搜索和恢复功能的交互式会话选择器。每一行都会显示一个生命周期状态标签（`done` / `intr` / `err` / `empty`，由会话的最后一条消息推导得出）及其消息数量。在高亮的行上按 `d`（搜索过滤为空时）会在 y/N 确认后删除该会话；过滤条件生效时，`d` 则会输入到搜索框中。 |
| `export <output> [--session-id ID]` | 将会话导出为 JSONL。 |
| `delete <session-id>` | 删除单个会话。 |
| `prune` | 删除匹配过滤条件的会话：时间范围 `--older-than`/`--newer-than`/`--before`/`--after`（如 `5h`/`2d` 这样的时长、裸天数或 ISO 时间戳）；属性 `--source`、`--title`、`--model`、`--provider`、`--branch`、`--end-reason`、`--user`、`--chat-id`、`--chat-type`、`--cwd`；数值范围 `--min/--max-messages`、`--min/--max-tokens`、`--min/--max-cost`、`--min/--max-tool-calls`；以及 `--include-archived`、`--dry-run`、`--yes`。默认：早于 90 天。 |
| `archive` | 批量归档（软隐藏，不删除）匹配与 `prune` 相同过滤条件的会话。至少需要一个过滤条件。 |
| `stats` | 显示会话存储统计信息。 |
| `rename <session-id> <title>` | 设置或更改会话标题。 |
| `optimize` | 回收磁盘空间：合并 FTS5 索引段 + VACUUM。非破坏性——不会更改任何会话数据。 |
| `optimize-storage` | 将全文搜索索引迁移到紧凑的 v23 外部内容布局；在大型数据库上，这可以回收 `state.db` 的很大一部分空间。 |
| `repair` | 修复格式错误的 `state.db` schema（例如 `table messages_fts already exists`），让被隐藏的会话重新出现；修复前会先创建备份。 |
| `repair-routing` | 重新挂接那些滞留在已丢失路由身份的会话行中的 gateway 对话（即重启后聊天"回到过去"的现象）。默认是 dry-run；`--apply` 执行接管（请先停止 gateway）；`--max-gap-seconds N` 调整连续性窗口。只修复没有歧义的情况。参见 [会话 → 修复滞留的 Gateway 会话](../user-guide/sessions.md#repair-stranded-gateway-sessions)。 |
| `recover` | 以离线、非破坏性的方式把损坏的 `state.db` 恢复到一个独立的干净数据库中。 |
| `retitle-skills` | 根据用户实际输入的内容，为以 `/skill` 开启的会话重新生成标题；除非传入 `--apply`，否则只列出变更。 |

## `hermes insights`

```bash
hermes insights [--days N] [--source platform]
```

| 选项 | 说明 |
|--------|-------------|
| `--days <n>` | 分析最近 `n` 天（默认：30）。 |
| `--source <platform>` | 按来源过滤，如 `cli`、`telegram` 或 `discord`。 |

## `hermes claw`

```bash
hermes claw migrate [options]
```

将 OpenClaw 设置迁移到 Hermes。从 `~/.openclaw`（或自定义路径）读取并写入 `~/.hermes`。自动检测旧版目录名（`~/.clawdbot`、`~/.moltbot`）和配置文件名（`clawdbot.json`、`moltbot.json`）。

| 选项 | 说明 |
|--------|-------------|
| `--dry-run` | 预览将迁移的内容而不写入任何内容。 |
| `--preset <name>` | 迁移预设：`full`（所有兼容设置）或 `user-data`（排除基础设施配置）。两种预设都不导入密钥——需要显式传入 `--migrate-secrets`。 |
| `--overwrite` | 在冲突时覆盖现有 Hermes 文件（默认：当计划有冲突时拒绝应用）。 |
| `--migrate-secrets` | 在迁移中包含 API 密钥。即使在 `--preset full` 下也需要显式指定。 |
| `--no-backup` | 跳过迁移前对 `~/.hermes/` 的 zip 快照（默认情况下，在应用前会将单个还原点归档写入 `~/.hermes/backups/pre-migration-*.zip`；可用 `hermes import` 恢复）。 |
| `--source <path>` | 自定义 OpenClaw 目录（默认：`~/.openclaw`）。 |
| `--workspace-target <path>` | 工作区说明（AGENTS.md）的目标目录。 |
| `--skill-conflict <mode>` | 处理 skill 名称冲突：`skip`（默认）、`overwrite` 或 `rename`。 |
| `--yes` | 跳过确认提示。 |

### 迁移内容

迁移涵盖 30+ 个类别，包括 persona、memory、skill、模型 provider、消息平台、agent 行为、会话策略、MCP 服务器、TTS 等。条目要么**直接导入**到 Hermes 等效项，要么**归档**以供手动审查。

**直接导入：** SOUL.md、MEMORY.md、USER.md、AGENTS.md、skill（4 个源目录）、默认模型、自定义 provider、MCP 服务器、消息平台 token 和许可名单（Telegram、Discord、Slack、WhatsApp、Signal、Matrix、Mattermost）、agent 默认值（推理努力程度、压缩、人工延迟、时区、沙箱）、审批规则、TTS 配置、浏览器设置、工具设置、执行超时、命令许可名单、gateway 配置以及来自 3 个来源的 API 密钥。

**归档以供手动审查：** Cron 任务、plugin、hook/webhook、memory 后端（QMD）、skill 注册表配置、UI/身份、日志、多 agent 设置、频道绑定、IDENTITY.md、TOOLS.md、HEARTBEAT.md、BOOTSTRAP.md。

**API 密钥解析**按优先级顺序检查三个来源：config 值 → `~/.openclaw/.env` → `auth-profiles.json`。所有 token 字段处理纯字符串、环境变量模板（`${VAR}`）和 SecretRef 对象。

完整的 config 键映射、SecretRef 处理详情和迁移后检查清单，请参阅**[完整迁移指南](../guides/migrate-from-openclaw.md)**。

### 示例

```bash
# 预览将迁移的内容
hermes claw migrate --dry-run

# 完整迁移（所有兼容设置，不含密钥）
hermes claw migrate --preset full

# 包含 API 密钥的完整迁移
hermes claw migrate --preset full --migrate-secrets

# 仅迁移用户数据（不含密钥），覆盖冲突
hermes claw migrate --preset user-data --overwrite

# 从自定义 OpenClaw 路径迁移
hermes claw migrate --source /home/user/old-openclaw
```

## `hermes import-agent`

```bash
hermes import-agent [claude-code|codex] [options]
```

将 **Claude Code**（`~/.claude`）或 **OpenAI Codex CLI**（`~/.codex`）的配置导入 Hermes。它会把 `CLAUDE.md`/`AGENTS.md` 指令映射为记忆条目，把 `Bash(...)` 权限的允许/拒绝规则映射为 `command_allowlist`/`approvals.deny`，把 MCP 服务器映射为 `config.yaml` 中的 `mcp_servers`，并把 skill 目录导入 `~/.hermes/skills/`。应用前总会先预览；API 密钥和凭据永远不会被导入。

| 选项 | 说明 |
| --- | --- |
| `agent` | `claude-code` 或 `codex`（默认：自动检测）。 |
| `--source <path>` | 自定义源目录（默认：`~/.claude` 或 `~/.codex`）。 |
| `--dry-run` | 仅预览——不写入任何内容。 |
| `--overwrite` | 替换冲突的 MCP 服务器 / skill（默认：跳过）。 |
| `--yes`, `-y` | 跳过确认提示。 |

完整的映射表请参阅**[导入指南](../user-guide/import-from-other-agents.md)**。

## `hermes serve`

```bash
hermes serve [options]
```

启动 Hermes **后端服务器**——[桌面应用](/user-guide/desktop)和远程客户端连接的 JSON-RPC/WebSocket gateway。它与 `hermes dashboard` 运行的是同一个服务器，但是**无界面的**：它从不打开浏览器 UI。桌面应用会自行启动它自己的 `hermes serve` 后端；当你想在远程主机上运行一个无界面后端时，直接使用此命令。它接受与下面 `hermes dashboard` 相同的 `--host` / `--port` / `--insecure` / `--skip-build` / `--stop` / `--status` 选项（绑定到非回环地址同样会启用鉴权门控）。需要 `[web]` extra；内嵌的 Chat socket 在 POSIX 主机上还额外需要 `[pty]`。

**端口冲突：** 如果请求的端口（默认 `9119`）已被另一个进程占用（例如第二个 `hermes serve` 或 gateway），该命令会向 stdout 打印一行机器可读的哨兵信息 `BACKEND_PORT_IN_USE port=<port>`，以及一条指出可能占用者的人类可读提示，并以退出码 **75**（`EX_TEMPFAIL`）退出，而不是报一个通用错误——这样脚本和桌面应用就能区分"端口被占用"和"后端故障"。传入 `--port 0` 可绑定一个空闲的临时端口（成功启动时会通过 `HERMES_BACKEND_READY port=<port>` 公布所选端口）。

## `hermes dashboard`

```bash
hermes dashboard [options]
```

启动 Web 控制台——基于浏览器的界面，用于管理配置、API 密钥和监控会话。（若需要没有浏览器 UI 的无界面后端——例如桌面应用所启动的那个——请使用上面的 [`hermes serve`](#hermes-serve)。）需要 `cd ~/.hermes/hermes-agent && uv pip install -e ".[web]"`（FastAPI + Uvicorn）。内嵌浏览器 Chat 标签页始终可用，但额外需要 `pty` extra（`cd ~/.hermes/hermes-agent && uv pip install -e ".[web,pty]"`）以及 POSIX PTY 环境（如 Linux、macOS 或 WSL2）。完整文档请参阅 [Web 控制台](/user-guide/features/web-dashboard)。

| 选项 | 默认值 | 说明 |
|--------|---------|-------------|
| `--port` | `9119` | Web 服务器运行端口 |
| `--host` | `127.0.0.1` | 绑定地址 |
| `--no-open` | — | 不自动打开浏览器 |
| `--insecure` | 关闭 | **已弃用 / 空操作。** 以前用于在绑定非回环地址时绕过鉴权。自 2026 年 6 月的加固起，公网绑定*始终*需要一个鉴权提供方（密码或 OAuth）。绑定 `127.0.0.1` 并通过隧道访问以保持本地化。 |
| `--skip-build` | 关闭 | 跳过 Web UI 构建步骤，直接提供已有的 `dist` 目录。适用于 npm 不可用的非交互场景（Windows 计划任务、CI）。请先用 `cd web && npm run build` 预构建。 |
| `--isolated` | 关闭 | 从具名 profile 启动时（`worker dashboard`），运行一个专用的 per-profile 服务器，而不是路由到机器级 dashboard。 |
| `--stop` | — | 停止正在运行的 `hermes dashboard` 进程并退出。 |
| `--status` | — | 列出正在运行的 `hermes dashboard` 进程并退出。 |

### `hermes dashboard register`

将本次安装注册为与你的 Nous Portal 账户关联的自托管 dashboard。它会创建一个 OAuth 客户端，把 `HERMES_DASHBOARD_OAUTH_CLIENT_ID` 写入 `~/.hermes/.env`，并打印如何启用登录门控。需要已登录（`hermes setup`）。

| 选项 | 说明 |
|--------|-------------|
| `--name` | dashboard 的可读标签（默认：自动生成）。 |
| `--redirect-uri` | 公网 HTTPS OAuth 重定向 URI（例如 `https://hermes.example.com/auth/callback`）。仅本机使用时可省略。 |
| `--portal-url` | 覆盖注册所用的 Nous Portal 基础 URL（默认：你登录的那个 portal）。也可通过 `HERMES_DASHBOARD_PORTAL_URL` 设置。 |

```bash
# 默认——在浏览器中打开 http://127.0.0.1:9119
hermes dashboard

# 自定义端口，不打开浏览器
hermes dashboard --port 8080 --no-open

# 从 profile 别名启动——路由到机器级 dashboard，并在侧边栏
# 切换器中预选该 profile（若已在运行则直接附着）
worker dashboard
```

## `hermes profile`

```bash
hermes profile <subcommand>
```

管理 profile——多个隔离的 Hermes 实例，每个实例拥有自己的 config、会话、skill 和主目录。

| 子命令 | 说明 |
|------------|-------------|
| `list` | 列出所有 profile。 |
| `use <name>` | 设置粘性默认 profile。 |
| `create <name> [--clone] [--clone-all] [--clone-from <source>] [--no-alias]` | 创建新 profile。`--clone` 从活跃 profile 复制 config、`.env`、`SOUL.md` 和 skills。`--clone-all` 复制所有状态。`--clone-from` 指定源 profile，除非与 `--clone-all` 配合使用，否则会隐含 config 克隆。 |
| `delete <name> [-y]` | 删除 profile。 |
| `show <name>` | 显示 profile 详情（主目录、config 等）。 |
| `alias <name> [--remove] [--name NAME]` | 管理快速访问 profile 的包装脚本。 |
| `rename <old> <new>` | 重命名 profile。 |
| `export <name> [-o FILE]` | 将 profile 导出为 `.tar.gz` 归档（本地备份）。 |
| `import <archive> [--name NAME]` | 从 `.tar.gz` 归档导入 profile（本地恢复）。 |
| `install <source> [--name N] [--alias] [--force] [-y]` | 从 git URL 或本地目录安装 profile 发行版。 |
| `update <name> [--force-config] [-y]` | 重新拉取发行版；保留用户数据（memory、会话、auth）。 |
| `info <name>` | 显示 profile 的发行版 manifest（版本、依赖、来源）。 |

示例：

```bash
hermes profile list
hermes profile create work --clone
hermes profile use work
hermes profile alias work --name h-work
hermes profile export work -o work-backup.tar.gz
hermes profile import work-backup.tar.gz --name restored
hermes profile install github.com/user/my-distro --alias
hermes profile update work
hermes -p work chat -q "Hello from work profile"
```

## `hermes completion`

```bash
hermes completion [bash|zsh|fish]
```

将 shell 补全脚本打印到 stdout。在 shell profile 中 source 输出内容，即可对 Hermes 命令、子命令和 profile 名称进行 Tab 补全。

示例：

```bash
# Bash
hermes completion bash >> ~/.bashrc

# Zsh
hermes completion zsh >> ~/.zshrc

# Fish
hermes completion fish > ~/.config/fish/completions/hermes.fish
```

## `hermes update`

```bash
hermes update [--gateway] [--check] [--plan] [--no-backup] [--backup] [--yes]
```

拉取最新的 `hermes-agent` 代码并在受管理的 venv 中重新安装依赖，然后重新运行安装后 hook（MCP 服务器、skill 同步、补全安装）。可在运行中的安装上安全执行。使用 `--check` 查看你的检出是否落后于 `origin/main`，而不安装。

`hermes update` 拉取所配置的更新分支（默认：`main`）。如果你的检出位于其他分支，Hermes 可能会在拉取前先检出更新分支。若你希望分支上的工作不进入更新的 autostash 流程，请在更新前先提交。

| 选项 | 说明 |
|--------|-------------|
| `--gateway` | 消息平台 `/update` 命令使用的内部模式。使用基于文件的 IPC 进行提示和进度流式传输，而不是从终端 stdin 读取。它不是 gateway 重启标志。 |
| `--check` | 检查是否有可用更新，不拉取、不安装依赖、不重启任何内容。 |
| `--plan` | 打印更新计划后退出，不做任何更改：安装类型（git/Docker/Nix/apt）、所有 profile 中每个正在运行的 Hermes 服务及其监管器和正在运行的代码版本，以及每个服务将如何被重启。对于由镜像或软件包管理的安装，则会报告正确的外部更新命令。只读。 |
| `--no-backup` | 本次运行跳过所有更新前备份（轻量状态快照和完整 zip 都跳过），无论 `updates.pre_update_backup` 如何设置。 |
| `--backup` | 本次运行强制执行**完整**的更新前备份：轻量状态快照加上 `HERMES_HOME` 的完整 zip（config、auth、会话、skill、配对数据）。默认模式是 `quick`——仅做轻量状态快照。通过 `config.yaml` 中的 `updates.pre_update_backup: quick \| full \| off` 设置永久模式。 |
| `--yes`, `-y` | 对配置迁移、stash 恢复等交互提示一律按"是"处理。API key 录入会被跳过；这类操作请单独运行 `hermes config migrate`。 |

附加行为：

- **Gateway 重启。** 更新成功后，Hermes 会尝试自动重启所有运行中的 gateway profile，让它们加载新代码。若你只想重启 gateway 而不应用更新，请使用 `hermes gateway restart`。
- **重启阶段恢复。** 如果进程内的重启阶段在导入刚拉取的代码树时中止，受监管的 gateway profile 会通过一个干净的 Python 进程重试。只有经 systemd 独立确认（`systemctl --user is-active`）的重启才会被报告为已验证；仅以 0 退出的重新拉起会被记录为 `relaunch_attempted`，并仍会保守地判定更新失败。手动启动的 gateway 以及 serve/dashboard 运行时，在没有重新拉起权限的情况下永远不会被杀掉；它们会被记录为已跳过并附带原因，并连同确切的重启命令保留在未完成更新的报告中。
- **更新回执 + 整体版本检查。** 每次运行都会在 `~/.hermes/logs/update_receipts/` 中写入一份机器可读的回执（更新前的整体计划、步骤、跳过项及原因、重启结果；`latest.json` 指向最新一份）。重启阶段之后，更新程序会将每个在线 gateway 正在运行的代码与更新后的检出进行比对，并打印逐个 profile 的版本矩阵；仍在运行更新前代码的 gateway 会使更新失败（退出码 1），并给出确切的重启命令。
- **本地源码改动。** 对于 git 安装，脏的已跟踪文件和未跟踪文件会在检出分支或拉取之前自动 stash（`git stash push --include-untracked`）。交互式终端更新会在恢复 stash 前询问。非交互式更新默认会恢复它；仅在成功拉取后应当丢弃本地源码编辑的受管安装上，才设置 `updates.non_interactive_local_changes: discard`。如果 stash 恢复发生冲突或拉取失败，stash 会被保留以便手动恢复。
- **npm lockfile 抖动。** 在 stash 或切换分支之前，Hermes 会尽力清理由 npm install/build 步骤产生的已跟踪 `package-lock.json` 差异。请在运行 `hermes update` 之前提交或手动 stash 有意为之的 lockfile 编辑。
- **配对数据快照。** 即使 `--backup` 关闭，`hermes update` 也会在 `git pull` 前对 `~/.hermes/pairing/` 和 Feishu 评论规则进行轻量快照。如果拉取覆盖了你正在编辑的文件，可以用 `hermes backup restore --state pre-update` 回滚。
- **旧版 `hermes.service` 警告。** 如果 Hermes 检测到预重命名的 `hermes.service` systemd 单元（而非当前的 `hermes-gateway.service`），会打印一次性迁移提示，帮助你避免循环重启问题。
- **退出码。** 成功时为 `0`，拉取/安装/安装后错误时为 `1`，阻止 `git pull` 的意外工作树变更时为 `2`。

## 维护命令

| 命令 | 说明 |
|---------|-------------|
| `hermes --version` | 打印版本信息。 |
| `hermes update` | 拉取最新变更并重新安装依赖。 |

| `hermes uninstall [--full] [--gui] [--dry-run] [--yes]` | 删除 Hermes，可选择删除所有 config/数据。`--gui` 只删除桌面 Chat GUI，保留 agent 本体；`--full` 还会删除 config/数据；`--dry-run` 打印将被删除的内容而不做任何更改；`--yes` 跳过提示。 |

## 另请参阅

- [斜杠命令参考](./slash-commands.md)
- [CLI 界面](../user-guide/cli.md)
- [会话](../user-guide/sessions.md)
- [Skill 系统](../user-guide/features/skills.md)
- [皮肤与主题](../user-guide/features/skins.md)
