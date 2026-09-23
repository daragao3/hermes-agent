---
sidebar_position: 2
title: "斜杠命令参考"
description: "交互式 CLI 和消息平台斜杠命令完整参考"
---

# 斜杠命令参考

Hermes 有两个斜杠命令入口，均由 `hermes_cli/commands.py` 中的中央 `COMMAND_REGISTRY` 驱动：

- **交互式 CLI 斜杠命令** — 由 `cli.py` 分发，支持从注册表自动补全
- **消息平台斜杠命令** — 由 `gateway/run.py` 分发，帮助文本和平台菜单均从注册表生成

已安装的 skill（技能）也会在两个入口以动态斜杠命令的形式暴露。（`/plan` 曾是其中之一；它现在是内置命令 — 见下方 Session 表。）

## 权限与管理员/用户分级 {#permissions-and-adminuser-split}

每个支持按用户白名单的消息平台（Telegram、Discord、Slack、Matrix、Mattermost、Signal 等）都支持两级斜杠命令分级：**管理员**可使用所有已注册命令，**普通用户**只能使用你在 `user_allowed_commands` 中列出的命令（以及始终允许的 `/help` 和 `/whoami`）。在 `~/.hermes/config.yaml` 中对应平台的 `extra:` 块内配置 `allow_admin_from` 和 `user_allowed_commands`（以及群组等效项 `group_allow_admin_from` / `group_user_allowed_commands`）。

各平台文档中有示例——结构在各平台间完全一致：

- [Telegram](../user-guide/messaging/telegram.md#slash-command-access-control)
- [Discord](../user-guide/messaging/discord.md)
- [Slack](../user-guide/messaging/slack.md)
- [Matrix](../user-guide/messaging/matrix.md)
- [Mattermost](../user-guide/messaging/mattermost.md)
- [Signal](../user-guide/messaging/signal.md)

如果某个作用域未设置 `allow_admin_from`，该作用域将保持不受限的向后兼容模式——所有允许的用户均可运行所有命令。

### DevFlow 审批命令 {#devflow-approval-commands}

DevFlow 委派平面（DevFlow Delegation Plane，DDP）的生命周期决策刻意比通用兼容规则更严格：除非发送方平台与聊天作用域配置了非空的显式 `allow_admin_from`（或 `group_allow_admin_from`）列表，否则 `/ddp-approve` 和 `/ddp-decline` 处于禁用状态。gateway 会根据已认证的平台用户 ID 推导出记录在案的操作者；绝不要把操作者 ID 写进命令参数里。

```yaml
platforms:
  telegram:
    extra:
      allow_admin_from: ["YOUR_TELEGRAM_USER_ID"]
```

群组场景请使用对应的 `group_allow_admin_from`。配置变更属于由运维人员控制的部署步骤；没有任何命令会自行启用自己。每个暂存命令都要求提供可见的理由/证据引用，并返回一个绑定到同一账户、五分钟内一次性有效的确认令牌。确认令牌是进程本地的：重启 gateway 会使所有未确认的令牌失效，因此重启后需要重新暂存该决策并确认新令牌。唯一合法的结果是：批准为 `TRIAGED → PLANNED`，拒绝为 `TRIAGED → DECLINED`。持久化的 DDP 账本会原子性地记录决策与生命周期转换；已提交的决策在重启后依然持久有效并受重放保护。这些命令不会调用执行器，也不会创建 PR、合并、部署、重启服务或管理 cron。

在 Slack 上请使用旧式的通配形式，因为这四个 DDP 命令刻意不占用 Slack 仅有的 50 个原生斜杠命令名额：`/hermes ddp-approve <request-id> <evidence>`，然后 `/hermes ddp-approve-confirm <token>`（`ddp-decline` 同理）。Telegram、Discord 和 CLI 使用下文所示的直接形式。在 Slack 的线程回复中，请使用 `!ddp-approve …`，然后 `!ddp-approve-confirm <token>`，而不是斜杠命令。

## 交互式 CLI 斜杠命令 {#interactive-cli-slash-commands}

在 CLI 中输入 `/` 可打开自动补全菜单。内置命令不区分大小写。

### 会话 {#session}

| 命令 | 描述 |
|---------|-------------|
| `/new [name]`（别名：`/reset`） | 开始新会话（全新会话 ID + 历史记录）。可选的 `[name]` 设置初始会话标题——例如 `/new my-experiment` 打开一个已命名为 `my-experiment` 的新会话，便于之后用 `/resume` 或 `/sessions` 查找。追加 `now`、`--yes` 或 `-y` 可跳过确认弹窗——例如 `/reset now`、`/new --yes my-experiment`。 |
| `/clear` | 清屏并开始新会话 |
| `/history` | 显示对话历史（遵循 `/timestamps` 设置） |
| `/save` | 保存当前对话 |
| `/prompt`（别名：`/compose`） | 在 `$EDITOR` 中撰写下一条 prompt（markdown），而不是使用内联输入框——适合长篇、多行或需要精心排版的 prompt。 |
| `/retry` | 重试最后一条消息（重新发送给 agent） |
| `/undo` | 移除最后一轮用户/助手对话 |
| `/title` | 为当前会话设置标题（用法：/title My Session Name） |
| `/compress [here [N] \| focus topic]` | 手动压缩对话上下文（刷新记忆 + 摘要）。`/compress here [N]` 会对除最近 N 轮对话（默认 2 轮）之外的所有内容做摘要，被保留的部分保持原文——由你自己决定压缩边界。焦点主题则可缩小完整摘要所保留的范围。 |
| `/rollback` | 列出或恢复文件系统检查点（用法：/rollback [number]） |
| `/diff [staged\|all\|session] [--stat] [path...]` | 显示工作目录中的 git 变更。默认：未暂存的变更加上未跟踪的文件。`staged` 显示已暂存待提交的内容，`all` 显示自 HEAD 以来的全部变更，`session` 显示 Hermes 在此处所做全部更改的累计 diff（从最早保留的检查点基线算起——需要启用检查点；与 `/rollback diff <N>` 互补）。`--stat` 只打印变更文件摘要；路径参数可限定 diff 范围。 |
| `/snapshot [create\|restore <id>\|prune]`（别名：`/snap`） | 创建或恢复 Hermes 配置/状态的快照。`create [label]` 保存快照，`restore <id>` 回滚到该快照，`prune [N]` 删除旧快照，不带参数则列出所有快照。数据库恢复通过 SQLite 的 backup API 写入，因此正在运行的进程（gateway、仪表板）能安全地看到恢复后的数据；如果该路径失败且另一个进程仍打开着数据库，恢复会直接拒绝而不是冒损坏的风险——停止占用者后重试即可。 |
| `/stop` | 终止所有正在运行的后台进程 |
| `/queue <prompt>`（别名：`/q`） | 将 prompt（提示词）加入队列等待下一轮处理（不会中断当前 agent 响应）。 |
| `/steer <prompt>` | 在**下一次工具调用之后**向 agent 注入一条中途说明——不中断、不产生新的用户轮次。当前工具完成后，该文本会追加到最后一条工具结果的内容中，在不打断当前工具调用循环的情况下为 agent 提供新上下文。可用于在任务进行中调整方向（例如在 agent 运行测试时说"专注于 auth 模块"）。 |
| `/goal <text>` | 设置一个持续目标，Hermes 将跨轮次持续推进——这是我们对 Ralph loop 的实现。每轮结束后，辅助裁判模型会判断目标是否完成；若未完成，Hermes 自动继续。子命令：`/goal status`、`/goal pause`、`/goal resume`、`/goal clear`。预算默认为 20 轮（`goals.max_turns`）；任何真实用户消息都会抢占继续循环，状态在 `/resume` 后保留。完整说明见 [持续目标](/user-guide/features/goals)。 |
| `/subgoal <text>` | 在循环进行中向活动目标追加一个用户自定义条件。继续 prompt 会将所有子目标原文呈现给 agent，裁判也会将其纳入 DONE/CONTINUE 判断——因此只有原始目标**和**所有子目标都满足时，目标才会被标记为完成。子命令：`/subgoal`（列出）、`/subgoal remove <N>`、`/subgoal clear`。需要有活动的 `/goal`。 |
| `/heartbeat every <interval> <prompt>`（别名：`/hb`） | 设置一个周期性 prompt：每当**本会话**空闲且间隔已到时，它会作为普通用户轮次重新进入会话（最小 60 秒；错过的触发会合并）。子命令：`/heartbeat status`、`/heartbeat pause`、`/heartbeat resume`、`/heartbeat clear`。作用域为会话且在进程内运行——需要持久、隔离的调度请使用 `hermes cron`。见 [会话心跳](/user-guide/features/heartbeat)。 |
| `/refine [focus]` | **立即**运行后台 memory/skill 自我改进审查，而不是等待每轮结束后的自动触发。可选的焦点文本可引导审查方向（例如 `/refine save the deploy workflow as a skill`）。它在后台 fork 中针对对话快照运行——实时会话和 prompt 缓存不受影响；完成后报告结果。 |
| `/review [instructions]` | 生成一个独立的、拥有完整权限的审查子 agent，审查刚刚讨论的工作——PR、代码、文档，以及最近 10 条聊天消息中引用的任何产物。它在后台调查（打开 PR、阅读 diff、运行代码），完整的审查结果会作为后台子 agent 完成事件重新进入本会话，供主 agent 据此行动。可通过 config.yaml 中的 `auxiliary.review` 固定一个专用审查模型（默认使用你的主模型）。见 [子 agent 委派](/user-guide/features/delegation#the-review-command)。 |
| `/moa <prompt>` | 用默认的 [Mixture of Agents](/user-guide/features/mixture-of-agents) 预设跑一条 prompt，然后恢复你当前的模型。一次性生效——不会更改会话所用的模型。 |
| `/resume [name]` | 恢复之前命名的会话 |
| `/sessions`（TUI 别名：`/switch`） | 经典 CLI：在交互式选择器中浏览并恢复历史会话。TUI：打开实时会话切换器，列出当前打开的 TUI 会话。在 TUI 中使用 `/sessions new` 可立即开启另一个实时会话。 |
| `/egress [status]` | 显示 Docker 出站代理状态——启用/配置/运行状态、凭据来源、token 映射、未覆盖的提供商，以及下一步修复建议。可在 CLI、TUI、桌面端聊天和消息 gateway 中使用。 |
| `/redraw` | 强制完整重绘 UI（在 tmux 调整大小、鼠标选择产生残影等导致终端错位后恢复） |
| `/status` | 显示会话信息——模型、提供商、profile、会话 ID、工作目录、标题、创建/更新时间戳、token 总量、agent 运行状态——随后显示本地**会话摘要**块（近期用户/助手轮次数、工具结果数、最常用工具、最近访问的文件、最新用户 prompt 和最新助手回复）。摘要从内存中的对话本地计算，不调用 LLM，不影响 prompt 缓存。 |
| `/context [all]`（别名：`/ctx`） | 可视化的上下文窗口分解。在 CLI/TUI 中：一个 5×20 的字形方块网格（每格约占模型窗口的 1%），外加一张按类别估算的表格——system prompt、工具定义、规则、skill 索引、MCP、子 agent、memory、对话——与剩余空间对比。在消息平台上：一个用量仪表，包含自动压缩阈值/余量、压缩统计、累计吞吐量，以及同一张纯文本类别表。`/context all` 会追加每个 skill 和每个工具集的开销列表（索引开销 vs SKILL.md 加载开销；每个工具集的 schema token 数）。只读且本地计算——不调用 LLM，不影响 prompt 缓存。 |
| `/agents`（别名：`/tasks`） | 显示当前会话中的活动 agent 和运行中的任务。 |
| `/bg <prompt>` | 在独立的后台会话中运行 prompt。agent 独立处理你的 prompt——当前会话保持空闲可继续其他工作。任务完成后结果以面板形式显示。见 [CLI 后台会话](/user-guide/cli#background-sessions)。 |
| `/btw <question>` | 在不打断当前工作的情况下，就**当前对话**提出一个快速的顺带问题。由一次一次性辅助 LLM 调用根据对话快照作答——实时会话的历史和提示缓存不受影响，当前回合继续运行。需要全新上下文的独立任务请使用 `/bg`。 |
| `/branch [name]`（别名：`/fork`） | 分支当前会话（探索不同路径） |
| `/worktree [new [name]\|list]` | **仅限 CLI。** 在会话中途查看或创建隔离的 git worktree（灵感来自 Copilot CLI 的 `/worktree new`）。裸 `/worktree` 显示当前 worktree；`/worktree list` 列出仓库的所有 worktree；`/worktree new [name]` 在 `.worktrees/` 下创建一个 worktree（从刚拉取的远程最新提交分出，遵循 `worktree_sync`），并将会话的终端和文件工具重新指向它。命名的 worktree 使用你给的名字（`hermes/<name>` 分支）；未命名的则得到随机的 `hermes-<id>`。退出时，只有含未推送提交的 worktree 才会被保留——与 `hermes -w` 的生命周期相同。见 [Git Worktrees](/user-guide/git-worktrees)。 |
| `/handoff <platform>` | **仅限 CLI。** 将当前会话移交给消息平台（Telegram、Discord、Slack、WhatsApp、Signal、Matrix）。gateway 立即接管，在支持线程的平台上创建新线程（Telegram 话题、Discord 文字频道线程、Slack 消息锚定线程），将目标重新绑定到你的 CLI session_id 以重放完整的角色感知转录，并伪造一条合成用户轮次让 agent 确认已在新位置工作。成功后 CLI 干净退出并提示 `/resume`；随时可用 `/resume <title>` 在本地恢复。轮次进行中拒绝执行。需要 gateway 正在运行且目标平台已配置 home 频道（从目标聊天中执行 `/sethome`）。见 [跨平台移交](/user-guide/sessions#cross-platform-handoff)。 |
| `/journey [list\|delete <id>\|edit <id>]`（别名：`/learning`、`/memory-graph`） | 打开已学习 skill + memory 的学习历程时间线。可在经典 CLI、TUI 覆盖层以及桌面应用（Star Map 面板）中使用。消息平台不可用。见 [学习历程](/user-guide/features/memory#learning-journey-journey)。 |

### 配置 {#configuration}

| 命令 | 描述 |
|---------|-------------|
| `/config` | 显示当前配置 |
| `/model [model-name]` | 显示或更改当前模型。支持：`/model claude-sonnet-4`、`/model provider:model`（切换提供商）、`/model custom:model`（自定义端点）、`/model custom:name:model`（命名自定义提供商）、`/model custom`（从端点自动检测），以及用户自定义别名（`/model fav`、`/model grok`——见[自定义模型别名](#custom-model-aliases)）。标志：`--global` 将更改持久化到 config.yaml；`--session` 强制仅对当前会话生效；`--once` 仅对下一轮生效；`--refresh` 重新拉取提供商的模型列表；`--provider <name>` 切换后端（除非加 `--global`，否则仅对当前会话生效）。普通的 `/model <name>` 仅对当前会话生效，除非设置了 `model.persist_switch_by_default: true`——例外是尚未配置任何 `model.default`/`model.provider` 时，第一次选择会被持久化，让该 profile 拥有一个真正的默认值。桌面端输入框的选择器遵循同样的规则。**交互式选择器：** 不带参数运行 `/model` 会打开 提供商→模型 选择器；在模型列表中你可以**直接输入进行模糊过滤**（例如输入 `grok` 只保留匹配的模型），Backspace 删减过滤词，Esc 清空过滤（或关闭选择器）。选择结果始终解析为一个具体的模型——过滤只会缩小列表，绝不会猜测。**注意：** `/model` 只能在已配置的提供商之间切换。如需添加新提供商，请退出会话后在终端运行 `hermes model`。**费用提示：** 在对话中途切换模型会重置 prompt 缓存——缓存键包含模型名，因此你的下一轮会以完整输入价格重新读取整段对话，而不是享受约 75% 折扣的缓存价。这是预期且无法避免的，但在长会话中值得留意。 |
| `/codex-runtime [auto\|codex_app_server\|on\|off]` | 切换 OpenAI/Codex 模型的可选 [Codex app-server runtime](../user-guide/features/codex-app-server-runtime)。`auto`（默认）使用 Hermes 标准 chat completions；`codex_app_server` 将轮次交给 `codex app-server` 子进程，支持原生 shell、apply_patch、ChatGPT 订阅认证和迁移的 Codex 插件。下次会话生效。 |
| `/personality` | 设置预定义的 personality（人格）。`/personality none`（或 `default` / `neutral`）会清除覆盖层，恢复基础行为。 |
| `/verbose` | 循环切换工具进度显示：off → new → all → verbose。可通过配置[为消息平台启用](#notes)。 |
| `/focus [on\|off\|status]` | 切换**专注视图**——一种仅影响显示的精简输出模式，只显示你的 prompt 和最终回复。它与 `/verbose` 协同：开启时会把工具进度切到 `off` 并记住你之前的模式，`/focus off` 会恢复它。每轮结束时会显示一行暗色的恢复提示（`⋯ 7 tool lines hidden · /focus off to show`），状态栏中还会常驻一个 `◉ focus` 徽章，让你始终知道自己处于精简视图。发送给模型的内容没有任何不同——细节只是被隐藏，从不丢弃。 |
| `/fast [normal\|fast\|auto\|cold\|status]` | 快速模式——OpenAI Priority Processing / Anthropic Fast Mode。`fast` = 每个请求都使用；`auto` = 仅在每轮的前 `agent.fast_auto_seconds`（默认 60 秒）内的请求使用；`cold` = 同样的时间窗口，但仅限会话的第一轮。默认 `normal`（关闭）。见 [快速模式](../user-guide/configuration.md#fast-mode)。 |
| `/reasoning [level\|show\|hide\|full\|clamp] [--global]` | 管理推理力度和显示。级别包括 `none` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max` / `ultra`。`show` / `hide`（或 `on` / `off`）切换推理显示；`full` 和 `clamp` 调整推理的显示方式。`--global` 将力度持久化到配置。 |
| `/skin` | 显示或更改显示皮肤/主题 |
| `/export [profile] [-o out.tar.gz]` | **仅限 CLI。** 将 profile 打包成可分享的 `.tar.gz`——包含 skill、memory、人格、cron、插件、设置，以及（从桌面端导出时）主题和布局。凭据（`auth.json`、`.env`）会被剔除。默认导出当前活动 profile，输出到当前目录下的 `<name>.tar.gz`。与 `hermes profile export` 生成的归档相同；如需带版本、可更新的分享方式，请改用 [profile 发行版](../user-guide/profile-distributions.md)。 |
| `/import <archive.tar.gz> [--name <name>]` | **仅限 CLI。** 将 profile 归档安装为一个新 profile，名称从归档推断，除非给出 `--name`。拒绝覆盖已有 profile，也不能以 `default` 的名义导入。名称未被占用时会创建 shell 包装脚本。见 [导出和导入 profile 文件](../user-guide/profile-distributions.md#export-and-import-a-profile-file)。 |
| `/statusbar`（别名：`/sb`） | 切换上下文/模型状态栏的显示与隐藏 |
| `/battery [on\|off\|status]` | 切换状态栏第一个元素处带颜色编码的电量读数（默认关闭；没有电池时不起作用）。 |
| `/voice [on\|off\|tts\|status]` | 切换 CLI 语音模式和语音播放。录音使用 `voice.record_key`（默认：`Ctrl+B`）。 |
| `/yolo` | 切换 YOLO 模式——跳过所有危险命令审批提示。 |
| `/approvals [manual\|smart\|off]` | 显示或设置持久化的危险命令审批模式。 |
| `/footer [on\|off\|status]` | 切换最终回复中的 gateway 运行时元数据页脚（显示模型、上下文占用百分比和 cwd）。 |
| `/busy [queue\|steer\|interrupt\|status]` | 控制 Hermes 工作时发送消息的行为——将新消息加入队列、中途引导，或立即中断。支持 CLI 和消息 gateway。 |
| `/indicator [kaomoji\|emoji\|unicode\|ascii]` | 仅限 CLI：选择 TUI 忙碌指示器样式。 |
| `/timestamps [on\|off\|status]` | 仅限 CLI：切换消息以及 `/history` 中的 `[HH:MM]` 时间戳。 |
| `/wake [on\|off\|status]` | 仅限 CLI：切换 "Hey Hermes" 唤醒词监听器。 |

### 工具与 Skill {#tools--skills}

| 命令 | 描述 |
|---------|-------------|
| `/tools [list\|disable\|enable] [name...]` | 管理工具：列出可用工具，或为当前会话禁用/启用特定工具。禁用工具会将其从 agent 工具集中移除并触发会话重置。 |
| `/toolsets` | 列出可用工具集 |
| `/browser [connect\|disconnect\|status]` | 管理本地 Chromium 系浏览器的 CDP 连接。`connect` 将浏览器工具附加到正在运行的 Chrome、Brave、Chromium 或 Edge 实例（默认：`http://127.0.0.1:9222`）。`disconnect` 断开连接。`status` 显示当前连接状态。若未检测到调试器，则自动启动支持的 Chromium 系浏览器。 |
| `/skills` | 从在线注册表搜索、安装、检查或管理 skill。同时也是 skill 写入审批门控的审核入口：`/skills pending`、`/skills diff <id>`、`/skills approve <id>`、`/skills reject <id>`、`/skills approval on\|off`。见 [为 agent 的 skill 写入加门控](/user-guide/features/skills#gating-agent-skill-writes-skillswrite_approval)。 |
| `/memory [pending\|approve\|reject\|approval]` | 审核由写入审批门控（`memory.write_approval`）暂存的待处理 memory 写入，并切换该门控。见 [控制 memory 写入](/user-guide/features/memory#controlling-memory-writes-write_approval)。 |
| `/bundles` | 列出已配置的 skill bundle——即一次预加载多个 skill 的 `/<name>` 斜杠别名。在 `~/.hermes/config.yaml` 的 `bundles:` 下配置。见 [Skill Bundles](/user-guide/features/skills#skill-bundles)。 |
| `/learn <what to learn from>` | 从你描述的任何东西中提炼出一个可复用的 skill——一个目录、一个 URL、你刚刚带着 agent 走过的工作流，或是粘贴进来的笔记。它是开放式的：agent 会用自己的工具收集这些来源，并按内部的编写规范撰写一份 `SKILL.md`。可在 CLI、消息 gateway、TUI 以及仪表板的 Skills 页面使用。 |
| `/plan [task]` | 将一份 markdown 实施计划写入当前工作区的 `.hermes/plans/`——只做规划，不执行。参数为空时会从对话中推断任务。（以前是内置的 `plan` skill；现在改为内置命令，以免被 Telegram/Discord 命令菜单的数量上限挤掉。） |
| `/init [notes]` | 通过扫描仓库生成或更新 `AGENTS.md` 项目说明（移植自 Codex 的 `/init`）。agent 会用只读工具检查清单文件、目录布局和工具链配置，然后写出一份简洁的 `AGENTS.md`——若已存在，则以合并方式更新并保留你的内容。可选的 notes 用于引导侧重点。可在 CLI、消息 gateway 和 TUI 中使用。 |
| `/cron` | 管理定时任务（列出、添加/创建、编辑、暂停、恢复、运行、删除） |
| `/suggestions [accept\|dismiss N\|catalog\|clear]`（别名：`/suggest`） | 审核建议的自动化。使用 `/suggestions` 列出待处理建议，`/suggestions accept <id>` 接受并创建建议任务，`/suggestions dismiss <id>` 拒绝单条建议，`/suggestions catalog` 添加精选起步自动化，`/suggestions clear` 清理已解决的建议记录。被接受的任务会保留当前表面作为投递来源。 |
| `/blueprint [name] [slot=value ...]`（别名：`/bp`） | 通过 blueprint 模板设置自动化。裸 `/blueprint` 列出目录；`/blueprint <name>` 会在下一次 agent 轮次启动引导式填槽流程；`/blueprint <name> slot=value ...` 直接创建任务。 |
| `/curator` | 后台 skill 维护——`status`、`run`、`pin`、`archive`。见 [Curator](/user-guide/features/curator)。 |
| `/kanban <action>` | 无需离开聊天即可操作多 profile、多项目协作看板。完整的 `hermes kanban` 命令面均可用：`/kanban list`、`/kanban show t_abc`、`/kanban create "title" --assignee X`、`/kanban comment t_abc "text"`、`/kanban unblock t_abc`、`/kanban dispatch` 等。支持多看板：`/kanban boards list`、`/kanban boards create <slug>`、`/kanban boards switch <slug>`、`/kanban --board <slug> <action>`。见 [Kanban 斜杠命令](/user-guide/features/kanban#kanban-slash-command)。 |
| `/reload-mcp`（别名：`/reload_mcp`） | 从 config.yaml 重新加载 MCP 服务器，并重新探测工具可用性（会话中途才出现的凭据/守护进程） |
| `/reload-skills`（别名：`/reload_skills`） | 重新扫描 `~/.hermes/skills/` 以发现新安装或已删除的 skill |
| `/reload` | 将 `.env` 变量重新加载到运行中的会话（无需重启即可获取新 API 密钥） |
| `/plugins` | 列出已安装的插件及其状态 |
| `/pet [list\|<slug>]` | 切换或领养一只 [petdex](/user-guide/features/pets) 吉祥物。`/pet` 切换面板，`/pet list` 显示已安装的宠物，`/pet <slug>` 领养指定的一只。 |
| `/hatch <description>`（别名：`/generate-pet`） | 根据文字描述生成一只全新的 petdex 宠物，使用已配置的图像后端（OpenRouter / Nous Portal）。见 [Pets](/user-guide/features/pets)。 |

### 信息 {#info}

| 命令 | 描述 |
|---------|-------------|
| `/help` | 按类别分组显示可用命令。默认显示核心命令，skill 命令折叠为一行计数；`/help skills` 列出所有 skill 命令，`/help <text>` 按子串过滤命令（及匹配的 skill）。 |
| `/palette` | 打开模糊命令面板（也可按 **Ctrl+P**）——输入以过滤所有命令 + skill，↑/↓ 移动，Enter 将选中的命令插入输入框（从不自动运行），Esc 取消。匹配优先按命令名排序，因此简短的查询也能保持精确。 |
| `/version` | 显示 Hermes Agent 版本、构建及环境信息。 |
| `/whoami` | 显示你的斜杠命令访问级别（admin / user）。 |
| `/usage` | 显示 token 用量、费用明细、会话时长，以及——当活动提供商支持时——从提供商 API 实时拉取的**账户限额**部分，包含剩余配额/积分/套餐用量。 |
| `/topup` | 显示你的 Nous 余额并在 portal 上管理计费（取代旧的 `/credits` 和 `/billing` 命令）。 |
| `/subscription`（别名：`/upgrade`） | **仅限 CLI。** 查看你的 Nous 套餐并在浏览器中更改。 |
| `/insights` | 显示用量洞察和分析（最近 30 天） |
| `/update` | 将 Hermes Agent 更新到最新版本。 |
| `/platforms`（别名：`/gateway`） | 显示 gateway/消息平台状态（仅限 CLI 摘要视图）。 |
| `/paste` | 附加剪贴板图片 |
| `/copy [number]` | 将最后一条助手回复复制到剪贴板（或用数字指定倒数第 N 条）。仅限 CLI。 |
| `/image <path>` | 为下一条 prompt 附加本地图片文件。 |
| `/debug` | 上传调试报告（系统信息 + 日志）并获取可分享链接。消息平台中也可用。 |
| `/update` | 将 Hermes Agent 更新到最新版本。 |
| `/profile` | 显示活动 profile 名称和主目录 |

### 退出 {#exit}

| 命令 | 描述 |
|---------|-------------|
| `/quit` | 退出 CLI（也可用：`/exit`）。 |

### 动态 CLI 斜杠命令 {#dynamic-cli-slash-commands}

| 命令 | 描述 |
|---------|-------------|
| `/<skill-name>` | 将任意已安装的 skill 作为按需命令加载。示例：`/gif-search`、`/github-pr-workflow`、`/excalidraw`。 |
| `/skills ...` | 从注册表和官方可选 skill 目录搜索、浏览、检查、安装、审计、发布和配置 skill。 |

### 快捷命令 {#quick-commands}

用户自定义快捷命令将一个短斜杠命令映射到 shell 命令或另一个斜杠命令。在 `~/.hermes/config.yaml` 中配置：

```yaml
quick_commands:
  status:
    type: exec
    command: systemctl status hermes-agent
  deploy:
    type: exec
    command: scripts/deploy.sh
  inbox:
    type: alias
    target: /gmail unread
```

然后在 CLI 或消息平台中输入 `/status`、`/deploy` 或 `/inbox`。快捷命令在分发时解析，可能不会出现在所有内置自动补全/帮助表中。

不支持将纯字符串 prompt 快捷方式作为快捷命令。较长的可复用 prompt 请放入 skill，或使用 `type: alias` 指向现有斜杠命令。

### 自定义模型别名 {#custom-model-aliases}

为常用模型定义自己的短名称，然后在运行中的会话里通过 `/model <alias>`、在启动时通过 `hermes chat --model <alias>`，或在任意消息平台中调用。别名在这些路径中的行为完全一致，支持仅会话（默认）和 `--global` 切换。

支持两种配置格式：

**完整格式** — 固定精确的模型、提供商，以及可选的 base URL。写入 `~/.hermes/config.yaml`：

```yaml
model_aliases:
  fav:
    model: claude-sonnet-4.6
    provider: anthropic
  grok:
    model: grok-4
    provider: x-ai
  ollama-qwen:
    model: qwen3-coder:30b
    provider: custom
    base_url: http://localhost:11434/v1
  theta:
    model: theta-1
    provider: custom
    base_url: https://theta.example.com/v1
    key_env: THETA_API_KEY        # 或：api_key: "${THETA_API_KEY}"
```

带有自己 `base_url` 的别名可以通过 `api_key`（字面值，或 `"${VAR}"` 引用）或 `key_env`（环境变量名）携带该端点的凭据；两者都设置时以 `api_key` 为准。两者都未设置时，密钥会根据别名的**主机**解析，绝不会从切换前处于活动状态的提供商继承。

**简短格式** — 用一个字符串表示 `provider/model`。无需编辑 YAML，直接从 shell 设置：

```bash
hermes config set model.aliases.fav anthropic/claude-opus-4.6
hermes config set model.aliases.grok x-ai/grok-4
```

然后在聊天中：

```
/model fav            # 仅当前会话
/model grok --global  # 同时将当前模型更改持久化到 config.yaml
```

用户别名优先于内置短名称，因此将别名命名为 `sonnet`、`kimi`、`opus` 等会覆盖内置名称。别名名称不区分大小写。

### 别名解析 {#alias-resolution}

命令支持前缀匹配：输入 `/h` 解析为 `/help`，`/mod` 解析为 `/model`。当前缀有歧义（匹配多个命令）时，注册表顺序中的第一个匹配项优先。完整命令名和已注册别名始终优先于前缀匹配。

## 消息平台斜杠命令 {#messaging-slash-commands}

> **Slack 线程命令（`!` 前缀）：**
> Slack 本身会在消息线程中拦截原生斜杠命令（"/queue is not supported in threads. Sorry!"），根本不会把它们投递给 Hermes。在 Slack 线程中，请改用 `!` 前缀——`!stop`、`!new`、`!status`——gateway 会像处理斜杠形式一样分发它。`@Hermes !stop` 和 `@Hermes /stop` 在线程中同样有效。只有第一个 token 会与已知命令列表比对，因此像 `!nice work` 这样的消息会原样传给 agent。详情见 [在线程中使用命令](/user-guide/messaging/slack#using-commands-inside-threads-the-cmd-prefix)。

消息 gateway 在 Telegram、Discord、Slack、WhatsApp、Signal、Email、Home Assistant 和 Teams 聊天中支持以下内置命令：

| 命令 | 描述 |
|---------|-------------|
| `/start` | 平台协议命令。许多聊天平台（Telegram、Discord 等）会在用户首次打开 bot 对话时自动发送 `/start`。Hermes 会静默确认这个 ping——不触发 agent 回复，也不消耗会话轮次——因此首次握手不会浪费一次对话。你也可以显式发送它来确认 gateway 可达。 |
| `/new [name]`（别名：`/reset`） | 开始新会话（全新会话 ID + 历史记录）。可选的 `[name]` 设置初始会话标题。追加 `now`、`--yes` 或 `-y` 可跳过确认弹窗——例如 `/reset now`、`/new --yes my-experiment`。 |
| `/status` | 显示会话信息，随后显示本地**会话摘要**块（近期轮次数、最常用工具、访问的文件、最新 prompt + 回复）。 |
| `/stop` | 终止所有正在运行的后台进程并中断运行中的 agent。 |
| `/model [provider:model]` | 显示或更改模型。支持提供商切换（`/model zai:glm-5`）、自定义端点（`/model custom:model`）、命名自定义提供商（`/model custom:local:qwen`）、自动检测（`/model custom`），以及用户自定义别名（`/model fav`、`/model grok`——见[自定义模型别名](#custom-model-aliases)）。使用 `--global` 将更改持久化到 config.yaml。**注意：** `/model` 只能在已配置的提供商之间切换。如需添加新提供商或设置 API 密钥，请在终端（聊天会话外）运行 `hermes model`。**费用提示：** 会话中途切换模型会重置 prompt 缓存（缓存键包含模型名），因此下一条消息会以完整输入价格重新读取整段对话。 |
| `/codex-runtime [auto\|codex_app_server\|on\|off]` | 切换可选的 [Codex app-server runtime](../user-guide/features/codex-app-server-runtime)。持久化到 config.yaml 中的 `model.openai_runtime` 并驱逐缓存的 agent，使下一条消息使用新 runtime。下次会话生效。 |
| `/personality [name]` | 为会话设置 personality 覆盖层。`/personality none`（或 `default` / `neutral`）会清除它。 |
| `/fast [normal\|fast\|auto\|cold\|status]` | 快速模式——OpenAI Priority Processing / Anthropic Fast Mode。`auto`/`cold` 会按轮次 / 按会话开启一个有时限的快速窗口。 |
| `/retry` | 重试最后一条消息。 |
| `/undo` | 移除最后一轮对话。 |
| `/sethome`（别名：`/set-home`） | 将当前聊天标记为该平台的 home 频道，用于消息投递。 |
| `/compress [here [N] \| focus topic]` | 手动压缩对话上下文。`/compress here [N]` 会原样保留最近 N 轮对话（默认 2 轮），并对其余内容做摘要。焦点主题则可缩小完整摘要所保留的范围。 |
| `/topic [off\|help\|session-id]` | **仅限 Telegram DM。** 管理用户自主的多会话话题模式。`/topic` 启用或显示状态；`/topic off` 禁用并清除绑定；`/topic help` 显示用法；在话题中执行 `/topic <session-id>` 可恢复之前的会话。见 [多会话 DM 模式](/user-guide/messaging/telegram#multi-session-dm-mode-topic)。 |
| `/title [name]` | 设置或显示会话标题。 |
| `/resume [name]` | 恢复之前命名的会话。 |
| `/sessions [all] [search <query>]` | 列出本聊天的历史会话；活动会话带有 `(current)` 标记。`/sessions search <query>` 按标题/ID 匹配过滤（最近活跃的排在前面）；`/sessions all` 跨来源列出（仅限管理员——非管理员会收到提示并看到本聊天范围的列表）。 |
| `/usage` | 显示 token 用量、估算费用明细（输入/输出）、上下文窗口状态、会话时长，以及——当活动提供商支持时——从提供商 API 实时拉取的**账户限额**部分，包含剩余配额/积分。 |
| `/topup` | 显示你的 Nous 余额并在 portal 上管理计费。 |
| `/whoami` | 显示你的斜杠命令访问级别（admin / user）。 |
| `/insights [days]` | 显示用量分析。 |
| `/reasoning [level\|show\|hide\|full\|clamp] [--global]` | 更改推理力度（级别最高到 `max` / `ultra`）或切换推理显示（包括 `full` / `clamp`）。`--global` 持久化到配置。 |
| `/voice [on\|off\|tts\|join\|channel\|leave\|status]` | 控制聊天中的语音回复。`join`/`channel`/`leave` 管理 Discord 语音频道模式。 |
| `/rollback [number]` | 列出或恢复文件系统检查点。 |
| `/diff [staged\|all\|session] [--stat]` | 显示工作目录中的 git 变更（用代码围栏包裹，并按平台消息长度限制截断）。`session` 显示 Hermes 所做全部更改的累计 diff；`--stat` 只显示摘要。 |
| `/bg <prompt>` | 在独立的后台会话中运行 prompt。任务完成后结果投递回同一聊天。见 [消息平台后台会话](/user-guide/messaging/#background-sessions)。 |
| `/btw <question>` | 在不打断当前对话的情况下，就当前对话提出顺带问题。根据对话快照作答；答案就绪后发送到聊天中。 |
| `/queue <prompt>`（别名：`/q`） | 将 prompt 加入队列等待下一轮处理，不中断当前轮次。 |
| `/steer <prompt>` | 在下一次工具调用后注入一条消息，不中断——模型在下一次迭代时获取，而非作为新轮次。 |
| `/goal <text>` | 设置一个持续目标，Hermes 将跨轮次持续推进——这是我们对 Ralph loop 的实现。裁判模型在每轮后检查；若未完成，Hermes 自动继续，直到完成、你暂停/清除，或达到轮次预算（默认 20）。子命令：`/goal status`、`/goal pause`、`/goal resume`、`/goal clear`。agent 运行中可安全执行 status/pause/clear；设置新目标需先执行 `/stop`。见 [持续目标](/user-guide/features/goals)。 |
| `/subgoal <text>` | 在循环进行中向活动的 `/goal` 追加条件（`/subgoal`、`/subgoal remove <N>`、`/subgoal clear`）。 |
| `/heartbeat every <interval> <prompt>`（别名：`/hb`） | 设置一个周期性 prompt，在本会话空闲时重新进入会话。子命令：`status`、`pause`、`resume`、`clear`。在 Slack 上请使用 `/hermes heartbeat …`。 |
| `/refine [focus]` | 立即运行 memory/skill 自我改进审查，可附带焦点说明。在 Slack 上请使用 `/hermes refine …`。 |
| `/review [instructions]` | 为刚刚讨论的工作（PR、代码、文档）生成一个独立的审查子 agent；审查完成后结果会重新进入本聊天。在 Slack 上请使用 `/hermes review …`。 |
| `/moa <prompt>` | 用默认的 [Mixture of Agents](/user-guide/features/mixture-of-agents) 预设跑一条 prompt，然后恢复会话模型。 |
| `/branch [name]`（别名：`/fork`） | 分支当前会话（探索不同路径）。 |
| `/agents`（别名：`/tasks`） | 显示活动 agent 和运行中的任务。 |
| `/sessions` | 浏览并恢复历史会话。 |
| `/context [all]`（别名：`/ctx`） | 上下文窗口用量仪表和类别分解（适合消息平台的文本形式）。`/context all` 会追加每个 skill / 每个工具集的开销明细。 |
| `/egress [status]` | 显示 Docker 出站代理状态。 |
| `/init [notes]` | 通过扫描仓库生成或更新 `AGENTS.md`。 |
| `/learn <what to learn from>` | 从你描述的任何东西中提炼出一个可复用的 skill。 |
| `/plan [task]` | 将一份 markdown 实施计划写入 `.hermes/plans/`；不执行。 |
| `/bundles` | 列出已配置的 skill bundle（一次预加载多个 skill 的 `/<name>` 别名）。 |
| `/reload-skills`（别名：`/reload_skills`） | 重新扫描 `~/.hermes/skills/` 以发现新安装或已删除的 skill。 |
| `/footer [on\|off\|status]` | 切换最终回复中的运行时元数据页脚（显示模型、上下文占用百分比和 cwd）。 |
| `/curator [status\|run\|pin\|archive]` | 后台 skill 维护控制。 |
| `/suggestions [accept\|dismiss N\|catalog\|clear]` | 直接在聊天中审核建议的自动化。`/suggestions` 列出待处理建议，`catalog` 添加精选起步自动化，`clear` 清理已解决的建议记录。被接受的建议会保留当前聊天/线程作为任务投递来源。 |
| `/blueprint [name] [slot=value ...]` | 浏览 cron blueprint、启动引导式填槽对话，或直接创建 blueprint 任务。直接创建的任务会回投到当前聊天/线程。 |
| `/memory [pending\|approve\|reject\|approval]` | 审核由写入审批门控（`memory.write_approval`）暂存的待处理 memory 写入——可直接在聊天中批准或拒绝——并通过 `/memory approval on\|off` 切换门控。见 [控制 memory 写入](/user-guide/features/memory#controlling-memory-writes-write_approval)。 |
| `/skills [pending\|approve\|reject\|diff\|approval]` | 审核由写入审批门控（`skills.write_approval`）暂存的待处理 **skill** 写入。每条待写入会显示一行摘要；`/skills diff <id>` 在聊天中会截断——完整 diff 请在 CLI 或 `~/.hermes/pending/skills/<id>.json` 中查看。仅当门控开启（或仍有待处理写入）时出现；搜索/安装仍然是 CLI-only。 |
| `/kanban <action>` | 从聊天中操作多 profile、多项目协作看板——参数与 CLI 完全一致。绕过运行中 agent 的保护，因此 `/kanban unblock t_abc`、`/kanban comment t_abc "…"`、`/kanban list --mine`、`/kanban boards switch <slug>` 等均可在轮次进行中使用。`/kanban create …` 会自动将发起聊天订阅到新任务的终态事件。见 [Kanban 斜杠命令](/user-guide/features/kanban#kanban-slash-command)。 |
| `/platform <list\|pause\|resume> [name]` | 直接在聊天中操作正在运行的 gateway 平台。`/platform list` 列出所有适配器及其状态（运行中、熔断器暂停、手动暂停）；`/platform pause <name>` 停止向该适配器分发新消息但不卸载它；`/platform resume <name>` 重新启用它，并在上游恢复健康后清除已触发的熔断器。 |
| `/reload-mcp`（别名：`/reload_mcp`） | 从配置重新加载 MCP 服务器，并重新探测工具可用性。 |
| `/verbose` | 循环切换工具进度显示。**在消息平台上默认关闭**——在 `config.yaml` 中设置 `display.tool_progress_command: true` 即可启用。 |
| `/yolo` | 切换 YOLO 模式——跳过所有危险命令审批提示。 |
| `/commands [page]` | 浏览所有命令和 skill（分页）。 |
| `/approve [session\|always]` | 审批并执行待处理的危险命令。`session` 仅为本次会话审批；`always` 添加到永久白名单。 |
| `/deny` | 拒绝待处理的危险命令。 |
| `/ddp-approve <request-id> <evidence>` | **仅限管理员，需显式开启。** 暂存对恰好一个处于 `TRIAGED` 状态的 DevFlow 请求的批准；用同一个已认证账户回复返回的 `/ddp-approve-confirm <token>`，即可将其转为 `PLANNED`。 |
| `/ddp-decline <request-id> <evidence>` | **仅限管理员，需显式开启。** 暂存对恰好一个处于 `TRIAGED` 状态的 DevFlow 请求的拒绝；用同一个已认证账户回复返回的 `/ddp-decline-confirm <token>`，即可将其转为 `DECLINED`。 |
| `/ddp-approve-confirm <token>` / `/ddp-decline-confirm <token>` | 执行一次对应的已暂存 DDP 决策。令牌与操作者绑定、五分钟后过期，并具备持久化的重放保护。这些命令无法构建、开 PR、合并、部署、重启服务或更改 cron 配置。Telegram 也接受下划线写法，例如 `/ddp_approve`。 |
| `/update` | 将 Hermes Agent 更新到最新版本。 |
| `/restart` | 在排空活动运行后优雅重启 gateway。gateway 重新上线后，会向请求者的聊天/线程发送确认消息。 |
| `/debug` | 上传调试报告（系统信息 + 日志）并获取可分享链接。 |
| `/help` | 显示消息平台帮助。 |
| `/<skill-name>` | 按名称调用任意已安装的 skill。 |

## 注意事项 {#notes}

- `/skin`、`/snapshot`、`/export`、`/import`、`/reload`、`/tools`、`/toolsets`、`/browser`、`/config`、`/cron`、`/platforms`、`/paste`、`/image`、`/statusbar`、`/battery`、`/focus`、`/plugins`、`/indicator`、`/wake`、`/journey`、`/redraw`、`/clear`、`/history`、`/save`、`/copy`、`/handoff`、`/prompt`、`/pet`、`/hatch`、`/timestamps`、`/subscription` 和 `/quit` 是**仅限 CLI** 的命令。
- `/skills` **仅在搜索/浏览/安装时属于 CLI-only**；其写入审批子命令（`pending`、`approve`、`reject`、`diff`、`approval`）在 `skills.write_approval` 开启时也可在消息平台使用。`/memory` 可在**两个表面**使用。
- `/verbose` **默认仅限 CLI**，但可通过在 `config.yaml` 中设置 `display.tool_progress_command: true` 为消息平台启用。启用后，它会循环切换 `display.tool_progress` 模式并保存到配置。
- `/focus` 和 `/verbose` 共用同一条抑制路径（`display.tool_progress`），因此二者永远不会相互矛盾：`/focus on` 将工具进度固定为 `off`，并把你的模式暂存到 `display.focus_saved_tool_progress` 下；`/focus off` 将其恢复；在专注模式开启时循环切换 `/verbose` 会取回该模式并清除专注徽章。专注视图仅影响显示——它从不改变对话历史、system prompt 或任何发送给模型的内容，因此对 prompt 缓存零影响。
- `/sethome`、`/restart`、`/approve`、`/deny`、`/topic`、`/platform` 和 `/commands` 是**仅限消息平台**的命令。
- `/status`、`/egress`、`/version`、`/whoami`、`/bg`、`/btw`、`/queue`、`/steer`、`/voice`、`/reload-mcp`、`/reload-skills`、`/rollback`、`/diff`、`/debug`、`/fast`、`/approvals`、`/busy`、`/footer`、`/curator`、`/kanban`、`/topup`、`/suggestions`、`/blueprint`、`/learn`、`/init`、`/sessions` 和 `/yolo` 在 **CLI 和消息 gateway 中均可使用**。
- `/voice join`、`/voice channel` 和 `/voice leave` 仅在 Discord 上有意义。
- 在 TUI 中，`/sessions` 显示的是当前 TUI 进程内的实时会话。对于已保存或已关闭的转录，请使用 `/resume [name]` 或 `hermes --tui --resume <id-or-title>`。

## 破坏性命令的确认提示 {#confirmation-prompts-for-destructive-commands}

CLI 在执行会丢弃未保存会话状态的斜杠命令前会提示确认。当前破坏性命令集为：

| 命令 | 销毁的内容 |
|---------|------------------|
| `/clear` | 清屏并开始新会话——当前会话 ID 和内存中的历史记录将丢失。 |
| `/new` / `/reset` | 开始新会话（新会话 ID + 空历史记录）。 |
| `/undo` | 从历史记录中移除最后一轮用户/助手对话。 |
| `/exit --delete` / `/quit --delete` | 退出**并**永久删除当前会话的 SQLite 历史记录和磁盘上的转录文件。 |

对于上述每个命令，CLI 会打开一个三选项弹窗：**Approve Once**（本次执行）、**Always Approve**（执行并持久化 `approvals.destructive_slash_confirm: false`，使未来的破坏性命令无需提示直接运行），或 **Cancel**。

**内联跳过：** 追加 `now`、`--yes` 或 `-y` 可为单次调用绕过弹窗——例如 `/reset now`、`/new --yes my-session`、`/clear -y`、`/undo -y`。适用于弹窗在你的终端无法正常渲染的情况（见 [issue #30768](https://github.com/NousResearch/hermes-agent/issues/30768)，原生 Windows PowerShell）或对 CLI 进行脚本化操作时。

在 `~/.hermes/config.yaml` 中设置 `approvals.destructive_slash_confirm: false` 可全局禁用提示；设置回 `true` 可重新启用。背景说明见 [安全——破坏性斜杠命令确认](../user-guide/security.md#dangerous-command-approval)。
