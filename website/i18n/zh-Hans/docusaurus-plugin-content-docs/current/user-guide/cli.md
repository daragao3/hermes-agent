---
sidebar_position: 1
title: "CLI 界面"
description: "掌握 Hermes Agent 终端界面——命令、快捷键、人格设定等"
---

# CLI 界面

Hermes Agent 的 CLI 是一个完整的终端用户界面（TUI），而非 Web UI。它支持多行编辑、斜杠命令自动补全、对话历史、中断并重定向，以及流式工具输出。专为常驻终端的用户而生。

:::tip 首次设置
一条命令——`hermes setup --portal`——即可开始 `hermes chat`。参见 [Nous Portal](/integrations/nous-portal)。
:::

:::tip
Hermes 还提供了一个现代 TUI，支持模态覆盖层、鼠标选择和非阻塞输入。使用 `hermes --tui` 启动——参见 [TUI](tui.md) 指南。
:::

## 运行 CLI

```bash
# 启动交互式会话（默认）
hermes

# 单次查询模式（非交互式）
hermes chat -q "Hello"

# 从文件或 stdin 读取单次查询——不经过任何 shell 解释，因此
# 任意文本（引号、$(...)、反引号）都会原样传入
hermes chat --query-file prompt.txt
hermes chat --query-file - < prompt.txt

# 使用指定模型
hermes chat --model "anthropic/claude-sonnet-4"

# 使用指定提供商
hermes chat --provider nous        # 使用 Nous Portal
hermes chat --provider openrouter  # 强制使用 OpenRouter

# 使用指定工具集
hermes chat --toolsets "web,terminal,skills"

# 启动时预加载一个或多个 skill
hermes -s hermes-agent-dev,github-auth
hermes chat -s github-pr-workflow -q "open a draft PR"

# 恢复之前的会话
hermes --continue             # 恢复最近的 CLI 会话（-c）
hermes --resume <session_id>  # 通过 ID 恢复指定会话（-r）
hermes --resume latest        # 恢复最近的会话（等同于 -c）
hermes --resume latest --in ./dir  # 恢复 ./dir 的最近会话，并停留在 ./dir

# 详细模式（调试输出）
hermes chat --verbose

# 隔离的 git worktree（用于并行运行多个 agent）
hermes -w                         # 在 worktree 中以交互模式运行
hermes -w -z "Fix issue #123"     # 在 worktree 中以单次查询模式运行
```

### Worktree 清理 {#worktree-cleanup}

`hermes -w` 会话会在 `<repo>/.worktrees/` 下创建一次性 worktree。
启动时会自动运行一个保守的清理器（它只会移除干净的、已完全合并且超过年龄阈值的临时 worktree），但在繁忙的机器上，被保留的 worktree 和已合并的本地分支仍会不断累积。可以显式回收它们：

```bash
hermes worktree list              # 审计：每个 worktree 的年龄、大小、结论、原因
hermes worktree prune             # 移除安全的 worktree + 删除已合并分支
hermes worktree prune --dry-run   # 只显示计划，不做任何更改
hermes worktree prune --trees-only     # 不动本地分支
hermes worktree prune --branches-only  # 不动 worktree
```

在会话内，`/worktree prune [--dry-run]` 效果相同（且永远不会触碰会话正在运行的那个 worktree）。

安全保证（所有模式、任何年龄均适用）：

- 未提交的**已跟踪**更改永远不会被删除。
- **独有的未推送提交**永远不会被删除——已在上游被 rebase/squash 合并的提交会通过 `git cherry` 的补丁等价性检测出来并计为已合并，正是这一点让最常见的"PR 已合并、worktree 永久保留"泄漏终于能被回收。
- **已推送的开放 PR 分支可以释放磁盘而不丢失任何内容**：当一个干净 worktree 的分支头与 `origin` 上的完全一致时（每次清理只执行一次 `git ls-remote` 检查），这个检出就是冗余的——worktree 会被移除，但其**分支引用会保留**，只需一条 `git worktree add .worktrees/<name> <branch>` 即可恢复。如果远程不可达，worktree 会被保留。
- **正被运行中的 hermes 会话使用**的 worktree 永远不会被触碰。
- **只含未跟踪文件的临时内容**（PR 正文草稿、笔记）会在其 worktree 被移除前归档到 `~/.hermes/archive/worktree-prune/`——绝不销毁。
- 分支删除按内容判定，而非按名称判定：任何提交全部位于上游的本地分支都可以安全删除；含独有工作的分支、已检出的分支，以及 `main`/`master`/`develop` 始终保留。

同一个保守清理器也会由 cron 调度器运行（最多每 6 小时一次，在后台执行），因此只运行 gateway 的机器——那里可能连续几天没人启动 `hermes -w`——在 CLI 会话之间也不会再累积已合并的临时 worktree。

当 `.worktrees/` 超过 10 个 worktree 或 5 GB 时，启动时会打印一行提示，指向这些命令。

### 插件管理 {#plugin-management}

`hermes plugins` 命令通过同一套选择启用（opt-in）流程管理原生 Hermes 插件和可移植的 Agent Plugins v1 包：

```bash
hermes plugins install owner/repository --no-enable
hermes plugins list
hermes plugins enable <plugin-name>
hermes plugins disable <plugin-name>
hermes plugins update <plugin-name>
hermes plugins remove <plugin-name>
```

可移植包在被显式启用之前保持禁用状态。Hermes 目前会加载可移植的 Agent Skills 和 stdio MCP 条目。确切的支持子集和信任边界参见[插件开发者指南](/developer-guide/plugins#portable-agent-plugins-v1-packages)。

## 界面布局

<img className="docs-terminal-figure" src="/docs/img/docs/cli-layout.svg" alt="Hermes CLI 布局的风格化预览，展示了横幅、对话区域和固定输入提示符。" />
<p className="docs-figure-caption">Hermes CLI 横幅、对话流和固定输入提示符，以稳定的文档图示形式呈现，而非脆弱的文字艺术。</p>

欢迎横幅一目了然地显示当前模型、终端后端、工作目录、可用工具和已安装的 skill。

### 状态栏

一个持久状态栏位于输入区域上方，实时更新：

```
 ⚕ claude-sonnet-4-20250514 │ 12.4K/200K │ [██████░░░░] 6% │ $0.06 │ 15m
```

| 元素 | 描述 |
|---------|-------------|
| 模型名称 | 当前模型（超过 26 个字符时截断） |
| Token 计数 | 已使用的上下文 token 数 / 最大上下文窗口；`~` 表示估算值 |
| 上下文进度条 | 带颜色阈值编码的可视填充指示器 |
| 费用 | 预估会话费用（未知或零价格模型显示 `n/a`） |
| 🗜️ N | **上下文压缩次数**——当前运行会话被自动压缩的次数。首次压缩触发后显示。 |
| ▶ N | **活跃后台任务数**——当前会话中仍在运行的 `/bg` prompt（提示词）数量。至少有一个任务进行中时显示。 |
| 时长 | 会话已用时间 |
| 会话标题 | 会话有标题后，会以金色徽章的形式固定在最右侧。标题过长时会先被截断，而不会挤占模型和上下文这些关键字段。 |
| ⚠ YOLO | **YOLO 模式警告**——当 `HERMES_YOLO_MODE` 开启时显示（通过启动时的 `hermes --yolo` 或会话中的 `/yolo` 切换）。与横幅行警告保持同步，确保你不会忘记自己处于自动批准模式。 |

上下文计数或百分比前的 `~` 表示其中包含本地估算。这同样适用于 gateway 的 `/status` 和 `/context`、TUI 以及桌面端的上下文仪表。未变化的 provider 用量读数不带 `~`；provider 锚点加上尚未计价的新消息则带 `~`。`/context` 会报告所选的数据来源。分类、剩余空间、skill 和工具集的分解始终是本地估算，即使整体占用来自 provider 用量。这些显示标记不会改变压缩决策，也不会产生额外的 provider 请求。

状态栏会根据终端宽度自适应——≥ 76 列时显示完整布局，52–75 列时显示紧凑布局，低于 52 列时显示最简布局（模型 + 时长，以及 YOLO 徽章（如已激活））。

**上下文颜色编码：**

| 颜色 | 阈值 | 含义 |
|-------|-----------|---------|
| 绿色 | < 50% | 空间充足 |
| 黄色 | 50–80% | 趋于饱满 |
| 橙色 | 80–95% | 接近上限 |
| 红色 | ≥ 95% | 即将溢出——考虑使用 `/compress` |

使用 `/usage` 查看详细分解，包括各类别费用（输入 vs 输出 token）。

在 `openai-codex` provider 上，`/usage` 还会显示你的 ChatGPT 账户中已存入的用量限额重置次数（"You have N resets banked - use /usage reset to activate"）。`/usage reset` 会兑换一次已存入的重置，完全恢复你的 5 小时和每周限额。当你的限额尚未耗尽时，Hermes 会拒绝兑换（一次已存入的重置会恢复全部额度，提前使用会造成浪费）——传入 `/usage reset --force` 可强制兑换。

### 会话恢复显示

恢复之前的会话时（`hermes -c` 或 `hermes --resume <id>`），横幅与输入提示符之间会出现一个"Previous Conversation"面板，显示对话历史的简洁摘要。详情及配置说明参见[会话——恢复时的对话摘要](sessions.md#conversation-recap-on-resume)。

## 快捷键 {#keybindings}

| 按键 | 操作 |
|-----|--------|
| `Enter` | 发送消息 |
| `Alt+Enter`、`Ctrl+J` 或 `Shift+Enter` | 换行（多行输入）。`Shift+Enter` 需要终端能够将其与 `Enter` 区分——见下文。在 Windows Terminal 中，`Alt+Enter` 被终端捕获（切换全屏）；请改用 `Ctrl+Enter` 或 `Ctrl+J`。 |
| `Alt+V` | 在终端支持时从剪贴板粘贴图片 |
| `Ctrl+V` | 粘贴文本，并尝试附加剪贴板中的图片 |
| `Ctrl+B` | 语音模式启用时开始/停止录音（`voice.record_key`，默认：`ctrl+b`） |
| `Ctrl+G` | 在 `$EDITOR`（vim/nvim/nano/VS Code 等）中打开当前输入缓冲区。保存并退出后，编辑后的文本将作为下一条 prompt 发送——适合编写长篇多段落 prompt。 |
| `Ctrl+X Ctrl+E` | 外部编辑器的 Emacs 风格备用绑定（与 `Ctrl+G` 行为相同）。 |
| `Ctrl+S` | **暂存 prompt。** 搁置当前草稿并清空输入框，让你可以先发送别的内容。在输入框为空时再次按 `Ctrl+S` 即可取回草稿（光标位于末尾，附带的图片也会恢复）。重复按下会构建一个栈而不是覆盖，因此较早的草稿永远不会被悄悄丢失——暂存两条或更多时，`Ctrl+S` 会打开浏览面板（`↑`/`↓` 导航，`Enter` 恢复，`D` 丢弃，`Esc` 或 `Ctrl+S` 关闭）。状态栏中的 `📌 N` 徽章显示当前搁置的草稿数量。多行草稿会原样往返，包括空行。暂存只保存在本会话的内存中——不会写入磁盘，因为草稿中常常含有机密信息。 |
| `Ctrl+C` | 中断 agent（2 秒内双击强制退出） |
| `Ctrl+T` / `F6` | 打开全屏实时子智能体监视器，保留输入草稿。实时栏会自动出现在状态栏上方；方向键选择一个 worker，`Enter` 查看其近期日志，`s` 引导，`x` 请求停止并确认。参见[监控子智能体](/user-guide/features/delegation#monitoring-running-subagents-agents)。 |
| `F7` | 将实时子智能体栏切换为单行摘要或恢复多行预览，不改变输入焦点。 |
| `Ctrl+D` | 退出 |
| `Ctrl+Z` | 将 Hermes 挂起到后台（仅 Unix）。在 shell 中运行 `fg` 恢复。 |
| `Tab` | 接受自动建议（ghost text）或自动补全斜杠命令 |
| `!<command>` | **Shell 模式**——自己运行一条 shell 命令，不消耗模型轮次（例如 `!git status`、`!pytest -x`）。见下文。 |

**多行粘贴预览。** 粘贴多行内容时，CLI 会显示一行简洁的单行预览（`[pasted: 47 lines, 1,842 chars — press Enter to send]`），而非将全部内容倾倒到滚动缓冲区。实际发送的仍是完整内容；这只是显示上的优化。

### `!` Shell 模式 {#shell-mode}

以 `!` 开头的行会作为 shell 命令运行，而不是发送给 agent：

```
> !git status
> !ls -la
> !pytest -x tests/cli
```

- **零成本。** 完全不调用模型——没有 API 调用、没有 token、没有延迟。
- **不会进入对话。** 命令及其输出不会加入历史，因此上下文保持干净，prompt 缓存也不受影响。
- **在 agent 的 `terminal` 工具运行的地方运行。** 使用会话的工作目录，因此 `!pwd` 与 agent 看到的一致。
- **审批依然生效。** 危险命令（`rm -rf`、写入 `~/.hermes/config.yaml` 等）会经过与 agent 的 `terminal` 工具相同的审批提示。`!` 是节省成本/延迟的捷径，而不是绕过安全机制。
- **显示非零退出码。** 失败的命令会在输出后打印 `! exited <code>`。
- 单独输入 `!` 会打印一行用法提示。

Shell 模式仅限 CLI。Gateway 平台（Discord、Telegram、Slack）和 cron 运行会忽略它——这些用户本来就有自己的 shell。

**最终响应中的 Markdown 剥离。** CLI 会从 agent 的*最终*回复中剥离最冗长的 Markdown 围栏以及 `**bold**`（粗体） / `*italic*`（斜体） 包装，使其在终端中呈现为可读的纯文本，而非原始源码。代码块和列表会被保留。这不影响 gateway 平台或工具结果——它们保留 Markdown 以供原生渲染。

## 斜杠命令

输入 `/` 查看自动补全下拉菜单。Hermes 支持大量 CLI 斜杠命令、动态 skill 命令和用户自定义快捷命令。

常用示例：

| 命令 | 描述 |
|---------|-------------|
| `/help` | 显示命令帮助 |
| `/model` | 显示或更改当前模型 |
| `/tools` | 列出当前可用工具 |
| `/skills browse` | 浏览 skill 中心和官方可选 skill |
| `/bg <prompt>` | 在独立后台会话中运行一个 prompt |
| `/btw <question>` | 在不打断当前对话的情况下，就当前对话提出顺带问题 |
| `/skin` | 显示或切换当前 CLI 皮肤 |
| `/voice on` | 启用 CLI 语音模式（按 `Ctrl+B` 录音） |
| `/voice tts` | 切换 Hermes 回复的语音播放 |
| `/reasoning high` | 提高推理强度 |
| `/title My Session` | 为当前会话命名 |
| `/status` | 显示会话信息——模型/配置/token/时长——以及本地**会话摘要**块（近期轮次数、常用工具、涉及文件、最新用户 prompt + 助手回复）。纯本地计算，不调用 LLM。 |
| `/context [all]` | 可视化的上下文用量分解——字形方块网格 + 按类别的 token 表（system prompt / tools / skills / memory / conversation / 剩余空间）。`/context all` 还会显示每个 skill 和每个工具集的开销。 |
| `/sessions` | 在经典 CLI 中直接打开交互式会话选择器（与 TUI 使用同一界面）。输入过滤，方向键导航，Enter 恢复。 |

完整的内置 CLI 和消息列表，参见[斜杠命令参考](../reference/slash-commands.md)。

语音模式的设置、提供商、静音调节以及消息/Discord 语音用法，参见[语音模式](features/voice-mode.md)。

:::tip
命令不区分大小写——`/HELP` 与 `/help` 效果相同。已安装的 skill 也会自动成为斜杠命令。
:::

## 快捷命令

你可以定义自定义命令，无需调用 LLM 即可立即执行 shell 命令。这些命令在 CLI 和消息平台（Telegram、Discord 等）中均可使用。

```yaml
# ~/.hermes/config.yaml
quick_commands:
  status:
    type: exec
    command: systemctl status hermes-agent
  gpu:
    type: exec
    command: nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
  restart:
    type: alias
    target: /gateway restart
```

然后在任意聊天中输入 `/status`、`/gpu` 或 `/restart`。更多示例参见[配置指南](/user-guide/configuration#quick-commands)。

## 启动时预加载 Skill

如果你已知道本次会话需要哪些 skill，可在启动时传入：

```bash
hermes -s hermes-agent-dev,github-auth
hermes chat -s github-pr-workflow -s github-auth
```

Hermes 会在第一轮对话前将每个指定的 skill 加载到会话 prompt 中。该标志在交互模式和单次查询模式下均有效。

## Skill 斜杠命令

`~/.hermes/skills/` 中每个已安装的 skill 都会自动注册为斜杠命令。skill 名称即为命令名：

```
/gif-search funny cats
/axolotl help me fine-tune Llama 3 on my dataset
/github-pr-workflow create a PR for the auth refactor

# 仅输入 skill 名称即可加载它，让 agent 询问你的需求：
/excalidraw
```

## 人格设定

设置预定义人格以改变 agent 的语气：

```
/personality pirate
/personality kawaii
/personality concise
```

内置人格包括：`helpful`、`concise`、`technical`、`creative`、`teacher`、`kawaii`、`catgirl`、`pirate`、`shakespeare`、`surfer`、`noir`、`uwu`、`philosopher`、`hype`。

要恢复默认（无覆盖层），请使用 `/personality none`——`default` 和 `neutral` 也可以。

你也可以在 `~/.hermes/config.yaml` 中定义自定义人格：

```yaml
personalities:
  helpful: "You are a helpful, friendly AI assistant."
  kawaii: "You are a kawaii assistant! Use cute expressions..."
  pirate: "Arrr! Ye be talkin' to Captain Hermes..."
  # 添加你自己的！
```

## 多行输入

有两种方式输入多行消息：

1. **`Alt+Enter`、`Ctrl+J` 或 `Shift+Enter`** — 插入新行
2. **反斜杠续行** — 在行尾加 `\` 继续输入：

```
❯ Write a function that:\
  1. Takes a list of numbers\
  2. Returns the sum
```

`Ctrl+J` 和反斜杠续行默认启用，与 Claude Code / Codex / OpenCode 的多行快捷键一致。在 iTerm2 等受支持的终端上，Hermes 还会请求扩展按键报告，使 `Shift+Enter` 作为一个独立的换行键到达。如果你的终端对普通 `Enter` 发送 LF，而你需要旧版的"`Ctrl+J` 即提交"回退行为，可以选择关闭：

```yaml
# ~/.hermes/config.yaml
display:
  cli_multiline_shortcuts: false
```

:::info
支持粘贴多行文本——使用上述任意换行键，或直接粘贴内容。

在使用 Kitty 键盘协议的终端中，数字小键盘上的 `Alt+Enter` 也会插入换行符，即使光标紧邻折叠的粘贴内容。带修饰键的小键盘导航键与对应的非小键盘按键行为一致。
:::

### Shift+Enter 兼容性

大多数终端默认对 `Enter` 和 `Shift+Enter` 发送相同的字节序列，因此应用程序无法区分它们。Hermes 仅在终端通过 [Kitty 键盘协议](https://sw.kovidgoyal.net/kitty/keyboard-protocol/)或 xterm 的 `modifyOtherKeys` 模式发送不同序列时才能识别 `Shift+Enter`。

| 终端 | 状态 |
|---|---|
| Kitty、foot、WezTerm、Ghostty | 默认启用独立的 `Shift+Enter` |
| iTerm2（近期版本）、Alacritty、VS Code terminal、Warp | 在设置中启用 Kitty 协议后支持 |
| Windows Terminal Preview 1.25+ | 在设置中启用 Kitty 协议后支持 |
| macOS Terminal.app、Windows Terminal 稳定版 | 不支持——`Shift+Enter` 与 `Enter` 无法区分 |

当终端无法区分时，`Alt+Enter` 和 `Ctrl+J` 默认仍可正常使用。**特别是在 Windows Terminal 中，`Alt+Enter` 被终端捕获（切换全屏），永远不会传递给 Hermes——请直接使用 `Ctrl+Enter`（传递为 `Ctrl+J`）或 `Ctrl+J` 来换行。**

## 在轮次中途重定向 Agent {#redirecting-the-agent-mid-turn}

在 agent 工作时，你可以发送更正而无需开启新轮次：

- **输入新消息 + Enter**——用你的更正重定向当前轮次
- **`Ctrl+C`**——中断当前操作（2 秒内双击强制退出）
- 已完成的工具工作和已显示的推理会保留在上下文中
- 正在运行的工具会先到达其安全边界，然后才应用更正

### 繁忙输入模式

`display.busy_input_mode` 配置项控制在 agent 工作时按下 Enter 的行为：

| 模式 | 行为 |
|------|----------|
| `"interrupt"`（默认） | 你的消息会重定向当前轮次。模型生成会重新开始，已显示的推理和已完成的工作会被保留。正在运行的前台终端命令会被移到后台（不会被终止——完成时你会收到通知），以便立即读取你的消息；其他正在运行的工具会先完成 |
| `"queue"` | 你的消息被静默排队，在 agent 完成后作为下一轮发送 |
| `"steer"` | 你的消息通过 `/steer` 注入当前运行，在下一次工具调用后到达 agent——不中断，不开启新轮次 |

```yaml
# ~/.hermes/config.yaml
display:
  busy_input_mode: "steer"   # 或 "queue" 或 "interrupt"（默认）
```

`"queue"` 模式会准备一个独立的后续轮次。`"steer"` 始终等待下一个工具结果边界。默认的 `"interrupt"` 模式在模型生成期间响应更快，同时避免取消正在运行的工具；较长的前台 `terminal` 命令（构建、轮询器）会被交给后台，使 agent 立即看到你的消息，而不是等命令退出之后。想取消该轮次及其前台工作时，请使用 `/stop`。未知值会回退到 `"interrupt"`。

`"steer"` 有两个自动回退：如果 agent 尚未启动，或附有图片，消息会回退到 `"queue"` 行为，确保内容不丢失。

你也可以在 CLI 中动态更改：

```text
/busy queue
/busy steer
/busy interrupt
/busy status
```

:::tip 首次提示
第一次在 Hermes 工作时按下 Enter，Hermes 会打印一行提示，说明 `/busy` 选项。每次安装只触发一次；`config.yaml` 中的 `onboarding.seen.busy_input_prompt` 记录了它已显示过。删除该键可再次看到提示。
:::

### 挂起到后台

在 Unix 系统上，按 **`Ctrl+Z`** 将 Hermes 挂起到后台——与任何终端进程一样。shell 会打印确认信息：

```
Hermes Agent has been suspended. Run `fg` to bring Hermes Agent back.
```

在 shell 中输入 `fg` 即可从中断处恢复会话。Windows 不支持此功能。

## 工具进度显示

CLI 在 agent 工作时显示动态反馈：

**思考动画**（API 调用期间）：
```
  ◜ (｡•́︿•̀｡) pondering... (1.2s)
  ◠ (⊙_⊙) contemplating... (2.4s)
  ✧٩(ˊᗜˋ*)و✧ got it! (3.1s)
```

**工具执行信息流：**
```
  ┊ 💻 terminal `ls -la` (0.3s)
  ┊ 🔍 web_search (1.2s)
  ┊ 📄 web_extract (2.1s)
```

使用 `/verbose` 循环切换显示模式：`off → new → all → verbose`。该命令也可为消息平台启用——参见[配置](/user-guide/configuration#display-settings)。

### 工具预览长度

`display.tool_preview_length` 配置项控制工具调用预览行（如文件路径、终端命令）中显示的最大字符数。默认值为 `0`，表示无限制——显示完整路径和命令。

```yaml
# ~/.hermes/config.yaml
display:
  tool_preview_length: 80   # 将工具预览截断为 80 个字符（0 = 无限制）
```

这在终端较窄或工具参数包含很长文件路径时非常有用。

## 会话管理

### 恢复会话

退出 CLI 会话时，会打印恢复命令：

```
Resume this session with:
  hermes --resume 20260225_143052_a1b2c3

Session:        20260225_143052_a1b2c3
Duration:       12m 34s
Messages:       28 (5 user, 18 tool calls)
```

恢复选项：

```bash
hermes --continue                          # 恢复最近的 CLI 会话
hermes -c                                  # 简写形式
hermes -c "my project"                     # 恢复命名会话（谱系中最新的）
hermes --resume 20260225_143052_a1b2c3     # 通过 ID 恢复指定会话
hermes --resume "refactoring auth"         # 通过标题恢复
hermes --resume latest                     # 恢复最近的会话（等同于 -c）
hermes --resume latest --in ./my-project   # ./my-project 工作区的最近会话
hermes -r 20260225_143052_a1b2c3           # 简写形式
```

恢复会从 SQLite 中还原完整的对话历史。agent 能看到所有之前的消息、工具调用和响应——就像从未离开一样。

在聊天中使用 `/title My Session Name` 为当前会话命名，或从命令行使用 `hermes sessions rename <id> <title>`。使用 `hermes sessions list` 浏览历史会话。

### 会话存储

CLI 会话存储在 Hermes 的 SQLite 状态数据库 `~/.hermes/state.db` 中。数据库保存：

- 会话元数据（ID、标题、时间戳、token 计数器）
- 消息历史
- 跨压缩/恢复会话的谱系
- `session_search` 使用的全文搜索索引

部分消息适配器还会在数据库旁保存各平台的转录文件，但 CLI 本身从 SQLite 会话存储中恢复。

### 上下文压缩

长对话在接近上下文限制时会自动摘要：

```yaml
# 在 ~/.hermes/config.yaml 中
compression:
  enabled: true
  threshold: 0.50    # 默认在上下文限制的 50% 时压缩

# 摘要模型在 auxiliary 下配置：
auxiliary:
  compression:
    model: ""  # 留空则使用主聊天模型（默认）。或指定一个廉价快速的模型，如 "google/gemini-3-flash-preview"。
```

压缩触发时，中间轮次会被摘要，同时始终保留前 3 轮和后 20 轮。

## 后台会话 {#background-sessions}

在独立的后台会话中运行 prompt，同时继续使用 CLI 进行其他工作：

```
/bg Analyze the logs in /var/log and summarize any errors from today
```

Hermes 立即确认任务并将提示符还给你：

```
🔄 Background task #1 started: "Analyze the logs in /var/log and summarize..."
   Task ID: bg_143022_a1b2c3
```

### 工作原理

每个 `/bg` prompt 会在守护线程中生成一个**完全独立的 agent 会话**：

- **隔离对话**——后台 agent 不了解当前会话的历史。它只接收你提供的 prompt。
- **相同配置**——后台 agent 继承当前会话的模型、提供商、工具集、推理设置和回退模型。
- **非阻塞**——前台会话保持完全交互。你可以聊天、运行命令，甚至启动更多后台任务。
- **多任务**——你可以同时运行多个后台任务。每个任务都有编号 ID。

### 结果

后台任务完成时，结果会以面板形式出现在终端中：

```
╭─ ⚕ Hermes (background #1) ──────────────────────────────────╮
│ Found 3 errors in syslog from today:                         │
│ 1. OOM killer invoked at 03:22 — killed process nginx        │
│ 2. Disk I/O error on /dev/sda1 at 07:15                      │
│ 3. Failed SSH login attempts from 192.168.1.50 at 14:30      │
╰──────────────────────────────────────────────────────────────╯
```

如果任务失败，你会看到错误通知。如果配置中启用了 `display.bell_on_complete`，任务完成时终端会响铃。

### 使用场景

- **长时间研究**——"/bg research the latest developments in quantum error correction"，同时继续编写代码
- **文件处理**——"/bg analyze all Python files in this repo and list any security issues"，同时继续对话
- **并行调查**——同时启动多个后台任务，从不同角度探索问题

:::info
后台会话不会出现在主对话历史中。它们是独立会话，拥有各自的任务 ID（如 `bg_143022_a1b2c3`）。
:::

## 静默模式

默认情况下，CLI 以静默模式运行，该模式会：
- 抑制工具的详细日志
- 启用 kawaii 风格的动态反馈
- 保持输出简洁易读

如需调试输出：
```bash
hermes chat --verbose
```