---
sidebar_position: 7
title: "Sessions（会话）"
description: "会话持久化、恢复、搜索、管理及各平台会话跟踪"
---

import useBaseUrl from '@docusaurus/useBaseUrl';

# Sessions（会话）

Hermes Agent 自动将每次对话保存为一个 session。Session 支持对话恢复、跨 session 搜索以及完整的对话历史管理。

## Session 的工作原理

每次对话——无论来自 CLI、Telegram、Discord、Slack、WhatsApp、Signal、Matrix、Teams 还是其他任何消息平台——都会以完整消息历史的形式存储为一个 session。Session 记录在：

1. **SQLite 数据库**（`~/.hermes/state.db`）——包含 FTS5 全文搜索的结构化 session 元数据，以及完整消息历史

SQLite 数据库存储：
- Session ID、来源平台、用户 ID
- **Session 标题**（唯一、人类可读的名称）
- 模型名称和配置
- 系统 prompt（提示词）快照
- 完整消息历史（角色、内容、工具调用、工具结果）
- Token 计数（输入/输出）
- 时间戳（started_at、ended_at）
- 父 session ID（用于压缩触发的 session 分割）

### 哪些内容计入上下文

Hermes 存储 session 历史以便恢复对话，但不会在每次对话时重新发送所有历史字节。每轮对话中，模型看到的是：所选系统 prompt、当前对话窗口，以及 Hermes 为该轮显式注入的内容。

媒体附件作为轮次范围内的输入处理：

- 图片可以原生附加到下一次模型调用，或在当前模型不支持原生视觉时预先分析为文字描述。
- 音频在配置了语音转文字时会被转录为文本。
- 文本文档可以将提取的文本包含在内；其他文档类型通常以本地保存路径和简短说明来表示。
- 附件路径和提取/派生的文本可能出现在对话记录中，但原始图片、音频或二进制文件字节不会被反复复制到后续 prompt 中。

例如，如果用户发送一张图片并要求 Hermes 制作表情包，Hermes 可能会用视觉能力检查该图片一次并运行图像处理脚本。后续轮次不会自动将原始 JPEG 带入上下文，只携带写入对话的内容，例如用户的请求、简短的图片描述、本地缓存路径或最终的助手回复。

上下文增长最常见的原因不是媒体文件本身，而是冗长的文本：粘贴的转录、完整日志、大型工具输出、长 diff、重复的状态报告以及详细的证明转储。优先使用摘要、文件路径、重点摘录和工具支持的查找，而不是将大型内容复制到聊天中。

:::tip
当 session 变长时使用 `/compress`，用 `/new` 开启新线程，仅在需要从存储中删除旧的已结束 session 时才使用 `hermes sessions prune`。如果只是 `state.db` 变得很大，请先尝试非破坏性的选项：`hermes sessions optimize` 会合并 FTS5 索引段并对数据库执行 VACUUM，不会触碰任何 session 数据。压缩会减少活跃上下文，而不是隐私删除。向 `/new` 传入名称（例如 `/new payments-refactor`）可以预先设置新 session 的初始标题——便于之后通过 `/resume <name>` 或 `/sessions` 选择器找到它。
:::

### Session 来源

每个 session 都标记了其来源平台：

| 来源 | 描述 |
|--------|-------------|
| `cli` | 交互式 CLI（`hermes` 或 `hermes chat`） |
| `telegram` | Telegram 消息 |
| `discord` | Discord 服务器/私信 |
| `slack` | Slack 工作区 |
| `whatsapp` | WhatsApp 消息 |
| `signal` | Signal 消息 |
| `matrix` | Matrix 房间和私信 |
| `mattermost` | Mattermost 频道 |
| `email` | 电子邮件（IMAP/SMTP） |
| `sms` | 通过 Twilio 的短信 |
| `dingtalk` | 钉钉消息 |
| `feishu` | 飞书/Lark 消息 |
| `wecom` | 企业微信 |
| `weixin` | 微信（个人版） |
| `bluebubbles` | 通过 BlueBubbles macOS 服务器的 Apple iMessage |
| `qqbot` | QQ Bot（腾讯 QQ）通过官方 API v2 |
| `homeassistant` | Home Assistant 对话 |
| `webhook` | 传入 webhook |
| `api-server` | API 服务器请求 |
| `acp` | ACP 编辑器集成 |
| `cron` | 定时 cron 任务 |
| `batch` | 批处理运行 |

## CLI Session 恢复

使用 `--continue` 或 `--resume` 从 CLI 恢复之前的对话：

### 继续上次 Session

```bash
# 恢复最近的 CLI session
hermes --continue
hermes -c

# 或使用 chat 子命令
hermes chat --continue
hermes chat -c
```

这会从 SQLite 数据库中查找最近的 `cli` session 并加载其完整对话历史。

#### 按终端继续 {#per-terminal-continue}

不带参数的 `-c` 能感知终端：每个 CLI session 都会在 `~/.hermes/terminal-sessions/` 下留下一个小的面包屑文件，以其所在的终端为键（tty 设备、tmux 窗格、kitty 窗口、wezterm 窗格、Zellij 窗格、Windows Terminal session 等）。当你在*同一个*终端中再次运行 `hermes -c` 时，Hermes 会恢复该终端自己的 session——因此并排的两个窗格会各自继续自己的对话，而不是都抢占全局最近的那一个。如果该终端没有面包屑（首次使用、session 已删除，或面包屑已超过 30 天而过期），`-c` 会回退到恢复最近 session 的行为。`-c "name"` 和 `--resume` 不受影响。在 `config.yaml` 中设置 `session.terminal_continue: false` 可禁用此功能。

### 按名称恢复

如果你已为 session 设置了标题（见下方[Session 命名](#session-naming)），可以按名称恢复：

```bash
# 恢复一个命名 session
hermes -c "my project"

# 如果存在谱系变体（my project、my project #2、my project #3），
# 会自动恢复最新的一个
hermes -c "my project"   # → 恢复 "my project #3"
```

### 恢复特定 Session

```bash
# 按 ID 恢复特定 session
hermes --resume 20250305_091523_a1b2c3d4
hermes -r 20250305_091523_a1b2c3d4

# 按标题恢复
hermes --resume "refactoring auth"

# 恢复最近的 session——与 -c 的查找方式相同
hermes --resume latest

# 或使用 chat 子命令
hermes chat --resume 20250305_091523_a1b2c3d4
```

Session ID 在退出 CLI session 时显示，也可通过 `hermes sessions list` 查找。

:::note
`latest` 是 `--resume` 的保留关键字。标题恰好为 "latest" 的 session 仍可通过其 ID 或 `-c latest`（按标题匹配）访问。
:::

### 在指定目录中恢复 {#resume-in-a-specific-directory}

传入 `--in <dir>` 可在启动或恢复前切换到某个目录。与 `--resume latest`（或 `-c`）组合使用时，会选取该目录所属工作区的最近 session——无需先 `cd`，也不必记住 session ID：

```bash
# 恢复属于 ./my-project 的最近 session
hermes --resume latest --in ./my-project

# 同样适用于 TUI
hermes --tui --resume latest --in ./my-project
```

`--in` 还会把 session 固定在该目录：被恢复 session 记录的工作目录不会被还原（等同于传入了 `--no-restore-cwd`）。

### 恢复时还原工作目录 {#resume-restores-the-working-directory}

恢复 CLI session 时，Hermes 还会 `cd` 回该 session 记录的工作目录（其 git 仓库根目录或项目目录），使对话在它所属的工作区中继续。如果你想留在当前目录，请传入 `--no-restore-cwd`：

```bash
hermes --resume 20250305_091523_a1b2c3 --no-restore-cwd
```

一行 `↪ restored workspace dir: …` 会确认目录已切换。还原失败绝不会导致恢复本身失败。

### 按工作区过滤 Session {#filtering-sessions-by-workspace}

`hermes sessions list` 接受 `--workspace <needle>`，只显示工作区键（git 仓库根目录，否则为 cwd）匹配的 session——按路径子串或精确的目录名匹配：

```bash
hermes sessions list --workspace my-project
hermes sessions list --workspace ~/code/hermes-agent
```

### 恢复时的对话摘要 {#conversation-recap-on-resume}

恢复 session 时，Hermes 会在输入提示符前以样式化面板显示之前对话的紧凑摘要：

<img className="docs-terminal-figure" src={useBaseUrl('/img/docs/session-recap.svg')} alt="恢复 Hermes session 时显示的「上次对话」摘要面板的样式化预览。" />
<p className="docs-figure-caption">恢复模式会在返回实时提示符前显示一个紧凑摘要面板，包含最近的用户和助手轮次。</p>

摘要内容：
- 显示**用户消息**（金色 `●`）和**助手回复**（绿色 `◆`）
- **截断**长消息（用户 300 字符，助手 200 字符/3 行）
- **折叠工具调用**为带工具名称的计数（例如 `[3 tool calls: terminal, web_search]`）
- **隐藏**系统消息、工具结果和内部推理
- **最多**显示最近 10 轮，并以"... N earlier messages ..."指示器标注
- 使用**暗色样式**与活跃对话区分

要禁用摘要并保留最简单的单行行为，在 `~/.hermes/config.yaml` 中设置：

```yaml
display:
  resume_display: minimal   # 默认值: full
```

:::tip
Session ID 格式为 `YYYYMMDD_HHMMSS_<hex>`——CLI/TUI session 使用 6 位十六进制后缀（例如 `20250305_091523_a1b2c3`），gateway session 使用 8 位后缀（例如 `20250305_091523_a1b2c3d4`）。可以按 ID（完整或唯一前缀）或按标题恢复——`-c` 和 `-r` 均支持两种方式。
:::

## 跨平台切换 {#cross-platform-handoff}

在 CLI session 中使用 `/handoff <platform>` 将实时对话转移到消息平台的主频道。Agent 会从 CLI 停止的地方精确接续——相同的 session id、完整的角色感知对话记录、工具调用一并保留。

```bash
# 在 CLI session 内
/handoff telegram
```

执行过程：

1. CLI 验证 `<platform>` 已启用且已设置主频道（在目标聊天中运行一次 `/sethome` 即可配置）。
2. CLI 将 session 标记为待处理并**阻塞轮询 gateway**。如果 agent 正在处理轮次，则拒绝操作——请等待当前响应完成后再执行。
3. Gateway 监视器认领切换请求，并向目标适配器请求新线程：
   - **Telegram** — 开启新的论坛话题（如果在聊天中启用了 Bot API 9.4+ Topics 模式则为私信话题，或论坛超级群组话题）。
   - **Discord** — 在主文字频道下创建 1440 分钟自动归档的线程。
   - **Slack** — 发布一条种子消息并使用其 `ts` 作为线程锚点。
   - **WhatsApp / Signal / Matrix / SMS** — 无原生线程，回退到直接使用主频道。
4. Gateway 将目标键重新绑定到你现有的 CLI session id，然后伪造一个合成用户轮次，要求 agent 确认并总结。回复会出现在新线程中。
5. Gateway 确认成功后，CLI 打印 `/resume` 提示并干净退出：

   ```
   ↻ Handoff complete. The session is now active on telegram.
     Resume it on this CLI later with: /resume my-session-title
   ```

6. 从此时起，对话在该平台上继续。在新线程中回复——该频道中任何已授权的用户共享同一 session，之后线程中任何真实用户消息都能无缝加入，因为线程 session 的键不含 `user_id`。

**恢复到 CLI：** 当你想回到桌面时，只需运行 `/resume <title>`（或在 shell 中运行 `hermes -r "<title>"`），从平台停止的地方继续。

**故障模式：**
- 未配置主频道 → CLI 拒绝并提示 `/sethome`。
- Gateway 未运行（没有任何进程认领该请求）→ CLI 在 60 秒后超时并显示明确消息，CLI session 保持完整。
- 传输缓慢：gateway 一旦认领切换，就会通过一次真实的 agent 轮次重放你的完整 session，对于很长的 session 可能需要几分钟。CLI 会显示 "Still transferring..." 心跳并最多等待 15 分钟——它绝不会把缓慢的传输误报为 "gateway not running"。
- 线程创建失败（权限不足、话题模式未开启）→ 直接回退到主频道并仍然完成切换；没有线程隔离，但切换本身有效。
- `adapter.send` 失败（速率限制、临时 API 错误）→ 切换标记为失败并附带原因；行被清除以便重试。

**值得注意的限制：** 对于无线程能力的多用户群组主频道平台，合成轮次以私信风格 session 为键。这对自私信主频道（典型设置）有效，但对真正的共享群聊并不理想。线程支持覆盖 Telegram / Discord / Slack——这是最常见的情况——因此大多数设置不会遇到此问题。

## Session 命名 {#session-naming}

为 session 设置人类可读的标题，便于查找和恢复。

### 自动生成标题

Hermes 在第一次交换后自动为每个 session 生成简短的描述性标题（3–7 个词）。这在后台线程中使用快速辅助模型运行，不增加延迟。浏览 `hermes sessions list` 或 `hermes sessions browse` 时可以看到自动生成的标题。

自动命名每个 session 只触发一次，如果你已手动设置标题则跳过。

### 手动设置标题

在任何聊天 session（CLI 或 gateway）中使用 `/title` 斜杠命令：

```
/title my research project
```

标题立即生效。如果 session 尚未在数据库中创建（例如在发送第一条消息之前运行 `/title`），则会排队等待 session 启动后应用。

也可以从命令行重命名现有 session：

```bash
hermes sessions rename 20250305_091523_a1b2c3d4 "refactoring auth module"
```

### 标题规则

- **唯一**——不能有两个 session 共享同一标题
- **最多 100 个字符**——保持列表输出整洁
- **净化处理**——控制字符、零宽字符和 RTL 覆盖字符会被自动去除
- **普通 Unicode 均可**——emoji、CJK 字符、带重音字符均支持

### 压缩时的自动谱系

当 session 的上下文被压缩（通过 `/compress` 手动或自动触发）时，Hermes 会创建一个新的续接 session。如果原 session 有标题，新 session 会自动获得带编号的标题：

```
"my project" → "my project #2" → "my project #3"
```

按名称恢复时（`hermes -c "my project"`），会自动选取谱系中最新的 session。

### 在消息平台中使用 /title

`/title` 命令在所有 gateway 平台（Telegram、Discord、Slack、WhatsApp）中均可使用：

- `/title My Research` — 设置 session 标题
- `/title` — 显示当前标题

## Session 管理命令

Hermes 通过 `hermes sessions` 提供完整的 session 管理命令集：

### 列出 Session

```bash
# 列出最近的 session（默认：最近 20 个）
hermes sessions list

# 按平台过滤
hermes sessions list --source telegram

# 显示更多 session
hermes sessions list --limit 50
```

当 session 有标题时，输出显示标题、预览和相对时间戳：

```
Title                  Preview                                  Last Active   ID
────────────────────────────────────────────────────────────────────────────────────────────────
refactoring auth       Help me refactor the auth module please   2h ago        20250305_091523_a
my project #3          Can you check the test failures?          yesterday     20250304_143022_e
—                      What's the weather in Las Vegas?          3d ago        20250303_101500_f
```

当没有 session 有标题时，使用更简单的格式：

```
Preview                                            Last Active   Src    ID
──────────────────────────────────────────────────────────────────────────────────────
Help me refactor the auth module please             2h ago        cli    20250305_091523_a
What's the weather in Las Vegas?                    3d ago        tele   20250303_101500_f
```

### 导出 Session

`hermes sessions export` 是所有导出格式的统一入口，用 `--format` 选择：

| 格式 | 输出 | 适用场景 |
|------|------|----------|
| `jsonl`（默认） | 每个 session 一个 JSON 对象 | 备份、机器可读的往返格式 |
| `md` / `qmd` | 每个 session 一个 Markdown/Quarto 文件 + manifest | 可读归档、笔记 |
| `html` | 单个独立页面（多 session 带侧边栏） | 分享、浏览 |
| `trace` | Claude Code JSONL | HF Agent Trace Viewer、`--upload` |

另有 `--only user-prompts` 只导出你的 prompt（jsonl 或 md）。

所有格式共享同一套选择方式：`--session-id` 导出单个 session，或使用与 `prune` / `archive` 相同的完整过滤器进行批量导出 — `--older-than` / `--newer-than` / `--before` / `--after`（时长如 `5h`/`2d`/`1w`、纯数字天数或 ISO 时间戳）、`--source`、`--title`、`--model`、`--provider`、`--cwd`、`--min/--max-messages`、`--min/--max-tokens`、`--min/--max-cost`、`--min/--max-tool-calls`、`--user`、`--chat-id`、`--chat-type`、`--branch`、`--end-reason`。`--dry-run` 可预览匹配集而不写入。`--redact` 在任意格式下从导出内容中清除密钥（API key、token、凭据）— 任何打算分享的导出都建议加上。注意：带过滤器的批量导出只匹配*已结束*的 session；不带过滤器的 `export` 会导出所有 session（包括活跃的）。

#### JSONL（默认）

```bash
# 将所有 session 导出到 JSONL 文件
hermes sessions export backup.jsonl

# 导出特定平台的 session
hermes sessions export telegram-history.jsonl --source telegram

# 导出单个 session
hermes sessions export session.jsonl --session-id 20250305_091523_a1b2c3d4

# 从导出内容中脱敏 API key/token/凭据
hermes sessions export backup.jsonl --redact
```

导出文件每行包含一个 JSON 对象，包含完整的 session 元数据和所有消息。

#### HTML

`--format html` 生成一个完全独立的 HTML 文件 — 无远程依赖 — 带样式化的消息气泡、可折叠的工具输出，多 session 导出时还带侧边栏导航：

```bash
# 将一个 session 导出为独立 HTML 页面
hermes sessions export --format html --session-id 20250305_091523_a1b2c3d4 transcript.html

# 将最近一周的所有 Telegram session 导出到一个文件，并脱敏
hermes sessions export --format html --newer-than 1w --source telegram --redact archive.html
```

#### 只导出 Prompt

`--only user-prompts` 只导出你写的 prompt — 不含助手回复、工具输出或系统上下文。适合构建 prompt 库或回顾你问过什么：

```bash
# 每个 prompt 一条 JSONL 记录（session id、序号、时间戳、文本）
hermes sessions export prompts.jsonl --session-id 20250305_091523_a1b2c3d4 --only user-prompts

# Markdown 格式，直接输出到 stdout
hermes sessions export - --session-id 20250305_091523_a1b2c3d4 --only user-prompts --format md
```

支持 `--format jsonl`（默认）或 `md`，批量导出时同样支持全部过滤器，也可与 `--redact` 组合。

#### Trace（HF Agent Trace Viewer）

`--format trace` 生成 Claude Code JSONL — Hugging Face Hub 的 [Agent Trace Viewer](https://huggingface.co/docs/hub/agent-traces) 可自动识别的转录格式。可以写入本地文件，或加 `--upload` 推送到你自己的私有 `hermes-traces` 数据集（读取 `HF_TOKEN`）：

```bash
# 最近一个 session 的 trace，输出到 stdout
hermes sessions export --format trace

# 将一个 session 导出为本地 trace 文件
hermes sessions export --format trace --session-id 20250305_091523_a1b2c3d4 trace.jsonl

# 直接上传到你的私有 HF traces 数据集
hermes sessions export --format trace --session-id 20250305_091523_a1b2c3d4 --upload
```

Trace 导出默认强制脱敏（它们本来就是要离开本机的）；`--no-redact` 需人工审查后才建议使用。`--upload` 默认私有，除非加 `--public`。带过滤器的批量 trace 导出会为每个 session 写一个 `<id>.trace.jsonl`。

#### Markdown / QMD

当你想在隐藏或删除旧 session 之前保留一份可读的文件归档时，传入 `--format md` 或 `--format qmd`。Markdown/QMD 导出会为每个 session 写入一个文件到目录中（默认：`~/.hermes/session-exports`）。

```bash
# 将单个 session 导出为 Markdown
hermes sessions export --format md --session-id 20250305_091523_a1b2c3d4

# 将压缩链（compression lineage）导出为一个逻辑文档
hermes sessions export --format md --session-id 20250305_091523_a1b2c3d4 --lineage logical

# 预览 90 天前已结束的 session，不写入文件
hermes sessions export --format md --older-than 90 --dry-run

# 将 2 周前已结束的 Telegram session 导出为 QMD 文件
hermes sessions export --format qmd --older-than 2w --source telegram

# 导出长的 Claude session，并脱敏
hermes sessions export --format md --model sonnet --min-messages 50 --redact

# 导出并在校验通过后删除一个明确指定的 session
hermes sessions export --format md --session-id 20250305_091523_a1b2c3d4 --delete-after-verified --yes
```

Markdown/QMD 导出为每个 session 写入一个 `.md` 或 `.qmd` 文件，并附带一个 `manifest.jsonl`，记录文件路径、消息数量、lineage id 和 SHA-256。批量导出必须带至少一个过滤条件，不带过滤条件的批量导出会被拒绝。`--delete-after-verified` 仅限与 `--session-id` 搭配使用，且必须加 `--yes`。由于删除父 session 也会删除其委派/子 agent session，此模式会先将每个委派 session 导出到单独的文件并校验，然后才删除任何内容。如果导出期间委派集合发生变化，删除将被拒绝。`--redact` 会在写入前从消息内容和工具输出中清除密钥（API key、token、凭据）— 任何打算分享的导出都建议加上。

### 删除 Session

```bash
# 删除特定 session（需确认）
hermes sessions delete 20250305_091523_a1b2c3d4

# 不需确认直接删除
hermes sessions delete 20250305_091523_a1b2c3d4 --yes
```

### 重命名 Session

```bash
# 设置或更改 session 的标题
hermes sessions rename 20250305_091523_a1b2c3d4 "debugging auth flow"

# 多词标题在 CLI 中不需要引号
hermes sessions rename 20250305_091523_a1b2c3d4 debugging auth flow
```

如果标题已被另一个 session 使用，则显示错误。

### 固定 Session {#pin-a-session}

固定会设置一个持久的“保留”标志：被固定的 session 不受
`sessions.auto_archive` 过期清扫影响，并且总是出现在列表中。它与 Desktop
侧边栏 Pinned 分区使用的是同一个标志——从任一界面固定，两边都能看到。

```bash
# 固定一个或多个 session（唯一 ID 前缀即可）
hermes sessions pin 20250305_091523_a1b2c3d4
hermes sessions pin 20250305 20250306

# 取消固定
hermes sessions unpin 20250305_091523_a1b2c3d4

# 列出已固定的 session
hermes sessions pinned

# 机器可读输出，例如用于每晚备份你的固定集合
hermes sessions pinned --json > pinned-sessions.json
```

### 清理旧 Session

```bash
# 删除已不活跃 90 天的已结束 session（默认）
hermes sessions prune

# 自定义时间阈值——裸数字表示天数
hermes sessions prune --older-than 30

# 也支持时长写法：5h、30m、2d、1w
hermes sessions prune --older-than 12h

# 仅删除特定时间窗口内的 session（例如最近 5 小时内
# 创建的一批测试 session）
hermes sessions prune --newer-than 5h

# 使用绝对时间戳指定明确的窗口
hermes sessions prune --after "2026-07-05 09:00" --before "2026-07-05 14:30"

# 仅清理特定平台的 session（不限时间——任何过滤器都会
# 禁用隐式的 90 天默认值）
hermes sessions prune --source telegram
hermes sessions prune --source cron --older-than 60   # 加上时间标志以收窄范围

# 更多过滤器——全部按 AND 组合
hermes sessions prune --newer-than 5h --title "smoke test"   # 标题子串
hermes sessions prune --older-than 30 --max-messages 3        # 很小的 session
hermes sessions prune --cwd ~/scratch --end-reason done       # 按 cwd / 结束原因
hermes sessions prune --model gpt-5 --older-than 1w           # 按模型（子串）
hermes sessions prune --provider openrouter --older-than 60   # 按计费提供商
hermes sessions prune --branch feature/old-experiment         # 按 git 分支
hermes sessions prune --user 12345678 --chat-type group       # 按消息来源
hermes sessions prune --max-tokens 500 --older-than 7         # 按 token 用量
hermes sessions prune --max-cost 0.01 --max-tool-calls 0      # 廉价且无工具调用的运行

# 预览将被删除的内容，不实际删除任何东西
hermes sessions prune --newer-than 5h --dry-run

# 跳过确认
hermes sessions prune --older-than 30 --yes
```

时间值（`--older-than`、`--newer-than`、`--before`、`--after`）接受时长
（`5h`、`30m`、`2d`、`1w`）、裸数字天数，或 ISO
时间戳（`2026-07-05`、`2026-07-05 14:30`）。`--older-than`/`--before` 设定
上界；`--newer-than`/`--after` 设定下界。`--older-than`/`--newer-than`
这一对使用最近的消息活动时间（空 session 则回退到 session 开始时间）；
`--before`/`--after` 明确使用 session 开始时间。组合任一对即可构成一个窗口。

属性过滤器：`--source`（平台，精确匹配）、`--title` / `--model` /
`--branch`（不区分大小写的子串）、`--provider`（计费提供商，
精确匹配）、`--end-reason`、`--user`、`--chat-id`、`--chat-type`（精确匹配）、
`--cwd`（路径前缀），以及数值范围 `--min/--max-messages`、
`--min/--max-tokens`（输入+输出）、`--min/--max-cost`（美元，优先取实际值，
否则取估算值）和 `--min/--max-tool-calls`。使用任何过滤器都会禁用
隐式的 90 天默认值，因此 `hermes sessions prune --source cron` 或
`--model gpt-4o` 会匹配所有时间的 session——加上时间标志以收窄范围。只有
完全不带任何参数的 `hermes sessions prune` 才会保留 90 天的截止时间。每次
未带 `--yes` 的运行都会在请求确认前显示匹配数量以及最旧和最新的匹配
session。

已归档的 session 默认会被跳过；传入 `--include-archived` 可一并删除。

:::info
清理仅删除**已结束**的 session（已被显式结束或自动重置的 session）。活跃 session 永远不会被清理。
:::

### 批量归档 Session

如果你只是想让某些 session 从列表中消失而不删除任何内容，
`hermes sessions archive` 接受与 `prune` 相同的过滤器，但改为软隐藏
匹配的 session（设置与在 Desktop/Dashboard UI 中归档单个 session 相同的
归档标志——消息与搜索均保持完好）：

```bash
# 归档最近 5 小时内的所有内容（例如 75 个 CI 冒烟测试 session）
hermes sessions archive --newer-than 5h

# 按标题子串归档，先预览
hermes sessions archive --title "dry run" --dry-run
hermes sessions archive --title "dry run" --yes
```

至少需要一个过滤器——不带任何参数的 `hermes sessions archive` 会拒绝
归档你的全部历史。已归档的 session 会从 `hermes sessions list` 和
`/resume` 中隐藏，但仍保留在数据库中，可在 Desktop/Dashboard 的 session
列表中取消归档。

### Session 统计

```bash
hermes sessions stats
```

输出：

```
Total sessions: 142
Total messages: 3847
  cli: 89 sessions
  telegram: 38 sessions
  discord: 15 sessions
Database size: 12.4 MB
```

如需更深入的分析——token 用量、费用估算、工具分解和活动模式——请使用 [`hermes insights`](/reference/cli-commands#hermes-insights)。

### 修复滞留的 Gateway Session {#repair-stranded-gateway-sessions}

如果某个 gateway 对话在重启后“回到过去”——像最近的消息从未发生过一样
恢复了几天前的话题——那么实时对话可能滞留在一个丢失了路由身份的 session 行中
（这类损坏已在 v0.21 的 session 连续性工作中修复；当前版本从构造上防止它发生，
并会在运行时自愈）。

`hermes sessions repair-routing` 会找出含有消息但没有路由身份的 session 行，
并将每一行重新挂接到它所延续的对话上——但仅在证据明确无歧义时才这样做：

```bash
# 仅报告——显示每个孤立行、拟采纳的关系以及证据
hermes sessions repair-routing

# 执行采纳（先停止 gateway——运行中的 gateway 在内存中持有
# 旧的路由，并会把它写回覆盖修复结果）
hermes sessions repair-routing --apply

# 放宽/收窄连续性窗口（默认 900 秒）
hermes sessions repair-routing --max-gap-seconds 300
```

证据规则：

- **lineage（谱系）**——孤立行的 `parent_session_id` 指向同一平台上一个带键的行
  （这是记录下来的事实；不适用时间窗口）
- **contiguity（连续性）**——恰好有一个同平台的带键行在孤立行开始时间的
  窗口内变为静默

任何有歧义的情况（两个候选前驱、两个孤立行争夺同一前驱）都会附带原因报告，
并保持不动——错误的采纳会把一个对话拼接到另一个聊天中。被取代的行会以
`superseded_by_repair` 退役，因此重启恢复永远不会让它复活。

修复刻意**不是自动的**：如果该聊天此后已经积累了第二段历史，选择它延续哪条线程
由你决定。无论哪种情况，滞留的对话都仍可通过 `/resume` 和 session 搜索读取——
修复唯一改变的是路由。请先备份
（`cp ~/.hermes/state.db ~/.hermes/state.db.bak`）。


## 从 Claude Code 和 Codex CLI 导入 Session {#importing-sessions-from-claude-code-and-codex-cli}

在另一个 agent CLI 中开始了对话？你可以把它导入 Hermes 并在这里继续。
Hermes 读取 Claude Code 的 session 日志（`~/.claude/projects/`）和 Codex CLI 的
rollout（`~/.codex/sessions/`）——这些外部文件只会被读取，绝不会被修改。

```bash
# 跨两个工具的交互式选择器，最新的在前
hermes sessions import

# 限定为一个工具，或指向特定文件
hermes sessions import --from claude
hermes sessions import --from codex ~/.codex/sessions/2026/08/15/rollout-....jsonl

# 一步完成导入并恢复
hermes --resume @claude
hermes --resume @codex
```

`hermes sessions import` 会创建一个标题为
`Imported from Claude Code: <first user message>`（或 Codex CLI）的新 Hermes session，
并打印其 id 以及一条可直接粘贴的 `hermes --resume <id>` 命令。
`--resume @claude` / `--resume @codex` 显示同样的选择器，并直接把你带入
导入的对话。

**Hermes Desktop** 的命令面板中也有同样的导入器（**Import
session**）。它列出的是所连接后端所在机器上的日志——而不是运行该应用的
电脑——并显示只读预览，**Continue in Hermes** 会将对话复制到所选的
profile 中。浏览绝不会写入你的 session 存储，导入绝不会触碰源文件，
而且同一个日志导入两次会打开已有的副本，而不是再创建一份。

会被带过来的内容：按顺序排列的用户/助手对话，工具活动会被压缩成助手轮次中
简短的 `[ran tool: …]` 注释。系统 prompt、注入的上下文、推理过程和原始工具
输出都会被舍弃——导入的是一份干净的对话记录，而不是逐字节的重放。


## Session 搜索工具 {#session-search-tool}

Agent 内置了 `session_search` 工具，使用 SQLite 的 FTS5 引擎对所有历史对话进行全文搜索，并允许 agent 滚动浏览找到的任何 session。它不调用 LLM，返回的是数据库中实际消息的视图，而不是生成的摘要。

### 四种调用形式 {#four-calling-shapes}

工具根据你设置的参数推断意图，没有 `mode` 参数。

**1. 发现——传入 `query`：**

```python
session_search(query="auth refactor", limit=3)
```

运行 FTS5，按 session 谱系去重，并返回前 N 个 session。发现模式默认使用自适应详细度：排名最高的结果包含完整的上下文窗口和首尾消息，排名较低的结果则保持精简。传入 `detail="full"` 可完整填充每个结果。

每个结果包含：

- `session_id`、`title`、`when`、`source`
- `snippet` — FTS5 高亮的匹配摘录
- `detail` — `full` 或 `compact`
- `bookend_start` / `bookend_end` — 完整结果中为 session 的前/后 3 条用户+助手消息；精简结果中为空列表
- `messages` — 完整结果中为 FTS5 匹配点前后各 ±5 条消息；精简结果中仅为带标记的锚点消息
- `match_message_id`、`messages_before`、`messages_after`

排名第一的结果可以立即重建目标→命中→结论。如果另一个精简结果看起来更有希望，使用它的 session ID 和消息 ID 调用滚动形式。在真实 session 数据库上的典型耗时为几十毫秒。

**2. 滚动——传入 `session_id` + `around_message_id`：**

```python
session_search(session_id="20260510_174648_805cc2", around_message_id=590803, window=10)
```

返回以锚点为中心的 ±`window` 条消息窗口。无 FTS5，无书签——只是切片。在发现调用后需要比默认 ±5 窗口更多上下文时使用。

- 向**前**滚动：将 `messages[-1].id` 作为 `around_message_id` 传回
- 向**后**滚动：将 `messages[0].id` 作为 `around_message_id` 传回
- 边界消息在两个窗口中均出现，作为定向标记
- 当 `messages_before` 或 `messages_after` 小于 `window` 时，表示已到达 session 的开头或结尾

每次滚动调用的典型耗时：1–2ms。

**3. 读取——传入 `session_id` 但不带锚点：**

```python
session_search(session_id="20260510_174648_805cc2")
```

返回整个 session；对于大型 session，则返回有界的首部/尾部视图。解析 `@session:<profile>/<id>` 链接时也使用此形式。

**4. 浏览——无参数：**

```python
session_search()
```

按时间顺序返回最近的 session（标题、预览、时间戳）。当用户询问"我在做什么"而未指定主题时很有用。

### FTS5 查询语法

关键词模式支持标准 FTS5 查询语法：

- 简单关键词：`docker deployment`（FTS5 默认为 AND）
- 短语：`"exact phrase"`
- 布尔：`docker OR kubernetes`、`python NOT java`
- 前缀：`deploy*`

### 可选参数

- `sort` — `newest` 或 `oldest`，在 FTS5 排名之上排序。省略则仅按相关性排序（默认；适合探索性召回）。对于"我们在哪里停下了 X"的问题使用 `newest`，对于"X 是怎么开始的"的问题使用 `oldest`。
- `detail` — `adaptive`（默认）仅完整填充排名第一的发现结果；`full` 完整填充每个发现结果。
- `role_filter` — 逗号分隔的角色列表。发现模式默认为 `user,assistant`（工具输出通常是噪音）。传入 `user,assistant,tool` 以包含工具输出（调试工具行为），或传入 `tool` 仅搜索工具输出。

### 使用时机

Agent 被提示在以下情况自动使用 session 搜索：

> *"当用户引用过去对话中的内容，或你怀疑存在相关的先前上下文时，在要求用户重复之前先使用 session_search 召回。"*

典型触发词：「我们之前做过这个」、「还记得吗」、「上次」、「正如我提到的」，或任何当前窗口中没有的项目/人物/概念的引用。

## 各平台 Session 跟踪

### Gateway Session

在消息平台上，session 通过从消息来源构建的确定性 session 键来标识：

| 聊天类型 | 默认键格式 | 行为 |
|-----------|--------------------|----------|
| Telegram 私信 | `agent:main:telegram:dm:<chat_id>` | 每个私信聊天一个 session |
| Discord 私信 | `agent:main:discord:dm:<chat_id>` | 每个私信聊天一个 session |
| WhatsApp 私信 | `agent:main:whatsapp:dm:<canonical_identifier>` | 每个私信用户一个 session（存在映射时 LID/手机号别名合并为一个身份） |
| 群聊 | `agent:main:<platform>:group:<chat_id>:<user_id>` | 当平台暴露用户 ID 时，群内每用户独立 session |
| 群组线程/话题 | `agent:main:<platform>:group:<chat_id>:<thread_id>` | 所有线程参与者共享 session（默认）。设置 `thread_sessions_per_user: true` 则每用户独立。 |
| 频道 | `agent:main:<platform>:channel:<chat_id>:<user_id>` | 当平台暴露用户 ID 时，频道内每用户独立 session |

当 Hermes 无法获取共享聊天的参与者标识符时，回退为该房间共享一个 session。

### 共享与隔离的群组 Session

默认情况下，Hermes 在 `config.yaml` 中使用 `group_sessions_per_user: true`。这意味着：

- Alice 和 Bob 可以在同一个 Discord 频道中与 Hermes 对话，而不共享对话历史
- 一个用户的长时间工具密集型任务不会污染另一个用户的上下文窗口
- 中断处理也保持每用户独立，因为运行中的 agent 键与隔离的 session 键匹配

如果你想要一个共享的"房间大脑"，设置：

```yaml
group_sessions_per_user: false
```

这会将群组/频道恢复为每个房间一个共享 session，保留共享的对话上下文，但也共享 token 费用、中断状态和上下文增长。

### 会话连续性

Gateway 不会因空闲时间或每日时间边界而重置对话。需要新对话时使用 `/new`
或 `/reset`；上下文压缩仍会自动运行。旧的 `session_reset` 配置、重置策略覆盖和
重置计时环境变量均被忽略。缓存中的 agent 可以释放资源，但不会替换持久化对话。
重启恢复的新鲜度限制仅约束自动继续执行，不会清除用户发送消息时加载的历史。


### 崩溃和重启后的连续性 {#continuity-after-crashes-and-restarts}

一个 gateway 聊天被设计为**一个连续的 session**——随着增长被反复压缩——
直到你显式运行 `/new`（或 `/reset`）。这一点在 gateway 崩溃、重启和更新后
依然成立：

- Session 身份（路由键、聊天、来源）在创建 session 行时**原子地**写入，
  覆盖每一条创建路径（`/new`、第一条消息、`/branch` 子 session）。如果这次写入
  失败，下一轮的路由刷新会自动修复该行。
- 重启后，gateway 会将每个聊天重新解析到**实际活动**最近的 session——
  较旧的过期行永远不会压过你实际在进行的对话。
- 恢复**尊重 `/new` 边界**：如果某个聊天最近的事件是一次有意的重置，
  恢复会从头开始，而不会越过该重置去复活更早的 session。仅凭经过的时间
  绝不会阻止恢复一个持久化的对话。


## 存储位置

| 内容 | 路径 | 描述 |
|------|------|-------------|
| SQLite 数据库 | `~/.hermes/state.db` | 所有 session 元数据 + 带 FTS5 的消息 |
| Gateway 消息 | `~/.hermes/state.db` | SQLite——所有 session 消息的权威存储 |
| Gateway 路由索引 | `~/.hermes/state.db` 中的 `gateway_routing` 表 | 将 session 键映射到活跃 session ID（来源元数据、过期标志） |
| 遗留路由镜像 | `~/.hermes/sessions/sessions.json` | 路由索引的向后兼容镜像，在 `gateway.write_sessions_json: true`（默认）时写入 |

SQLite 数据库使用 WAL 模式支持并发读取和单写入，非常适合 gateway 的多平台架构。

:::warning `sessions.json` 不是 session 列表
Gateway 路由索引位于 `state.db` 内的 `gateway_routing` 表中；
`~/.hermes/sessions/sessions.json` 是它的**遗留镜像**，为向后兼容而保留
（可用 `gateway.write_sessions_json: false` 禁用）。它将
消息 session 键（`agent:main:<platform>:...`）映射到活跃的 session ID。
它只会包含 gateway/消息类条目，因此如果你运行了某个消息
平台，你只会看到这些条目（例如 `agent:main:whatsapp:dm:...`）。

这是**预期行为**，并**不**意味着你的 CLI session 丢失了。
`hermes sessions list`、`/sessions` 和仪表盘都读取 `state.db`，
其中保存着**所有** session（CLI、TUI 和 gateway）。`~/.hermes/sessions/saved/*.json`
下的 `/save` 快照是便捷导出文件，而不是索引。

如果 CLI session 确实没有出现在 `hermes sessions list` 中，原因是
`state.db` 没有接收到它们——运行 `hermes sessions repair`，并留意 CLI 启动时的
`⚠ Session store unavailable` 警告，它意味着该次运行的 SQLite
持久化失败了。
:::

:::note 遗留 JSONL 对话记录
在 state.db 成为权威存储之前创建的 session 可能在 `~/.hermes/sessions/` 中留有
`*.jsonl` 文件。Hermes 不再写入或读取这些文件。在确认对应 session 存在于
state.db 后可安全删除。
:::

### 数据库 Schema

`state.db` 中的关键表：

- **sessions** — session 元数据（id、source、user_id、model、title、时间戳、token 计数）。标题有唯一索引（允许 NULL 标题，只有非 NULL 标题必须唯一）。
- **messages** — 完整消息历史（role、content、tool_calls、tool_name、token_count）
- **messages_fts** — 用于跨消息内容全文搜索的 FTS5 虚拟表

## Session 过期与清理

### 自动清理 {#automatic-cleanup}

- Gateway 对话在空闲期间持续保留；使用 `/new` 或 `/reset` 设定显式边界
- 重置前，agent 保存即将过期 session 中的记忆和技能
- 自动清理（自 #54189 起**默认开启**）：当 `sessions.auto_prune` 为 `true` 时，在 CLI/gateway/cron 启动时清理已不活跃达 `sessions.retention_days`（默认 90）天的已结束 session
- 实际删除了行的清理操作完成后，仅当**两个**条件都满足时才会对 `state.db` 执行 `VACUUM` 以回收磁盘空间：距离上次成功执行 `VACUUM` 至少已过 `sessions.min_vacuum_interval_days`（默认 30）天，**并且**文件中超过 25% 的页可回收（`PRAGMA freelist_count / page_count`）。紧凑的数据库永远不会为了回收几 MB 而付出完整重写的代价（SQLite 在普通 DELETE 后不会缩小文件）
- 清理最多每 `sessions.min_interval_hours`（默认 24）小时运行一次；上次运行时间戳记录在 `state.db` 内部，因此在同一 `HERMES_HOME` 下的所有 Hermes 进程间共享

不进行清理的话，`state.db` 会无限增长——在 gateway + cron 部署上曾有报告在几周内增长到数 GB。如果你更希望永久保留每个已结束的 session（#54189 之前的行为），请在 `~/.hermes/config.yaml` 中关闭它：

```yaml
sessions:
  auto_prune: false         # 默认为 true——设为 false 以保留全部历史
  retention_days: 90        # 保留在此窗口内仍有活动的已结束 session
  vacuum_after_prune: true  # 清理后回收磁盘空间
  min_vacuum_interval_days: 30 # 数据库重写的最短间隔天数
  min_interval_hours: 24    # 清理间隔不短于此值
```

已显式设置了其中任何键的现有安装会保留其值；只有未设置的键才会采用新的默认值。

只有**已结束**的 session 才会被删除。活跃 session 永远不会被自动清理，
无论时间多长。已结束 session 的时长从其最新消息算起，因此最近仍在使用的
长期对话不会仅仅因为它开始于保留窗口之前而被删除。

**来自自动化的过期未结束 session。** 一些生产者——cron 任务、kanban
worker、子 agent、一次性 CLI 运行——可能在从未将其 session 标记为结束的情况下
就终止了，而清理只会删除*已结束*的行。为了避免这些 session 永远堆积，
每次自动清理还会*关闭*来自这些状态自有来源（`cli`、`cron`、`kanban`、`acp`、
`api_server`、`subagent`、`tool`）且最近活动早于 `retention_days` 的未结束 session
（`end_reason: startup_orphan_reap`）。关闭是非破坏性的——session 仍可恢复——
并且该行的时长从关闭时算起，因此只有在再经过一个完整保留窗口后，才会被
*之后*的某次清理删除。消息平台 session（Telegram、Discord 等）、TUI/desktop
session、已固定的 session，以及正在进行实时轮次或压缩的 session，永远不会
被此清扫关闭。

### 超大对话记录保护 {#oversized-transcript-guards}

两个限制可防止失控的对话记录被一次性全部加载到内存中
（两者默认均为 `20000` 条活跃消息；`0` 表示禁用该保护）：

```yaml
sessions:
  max_resume_messages: 20000   # 交互式恢复（CLI / TUI / Desktop）
  max_export_messages: 20000   # 单个 session 的一次性内存导出
```

`max_resume_messages` 限制的是**恢复实际加载的内容**，而不是对话的全部历史：

- 普通的交互式恢复（CLI `--resume`、TUI）会实体化完整的压缩谱系——
  每个已压缩的分段加上实时尾段——因此它按整个谱系计数限制。
- Desktop 的冷恢复通过 REST 分页加载对话记录，内存中只保留实时尾段，
  因此只受尾段限制。一个被多次压缩的长期聊天（几十个分段、小尾段背后有
  数万条归档行）正是压缩所要产生的结果，可以正常打开；其页脚的消息计数
  反映的是存储的谱系，而不是实时 prompt。

当恢复被拒绝时，客户端会收到错误代码 `4130`，附带计数以及测量所依据的范围
（`across its lineage` 或 `in its tip segment`）。对这类 session，
`hermes sessions export` 仍然可用。

### 回收磁盘空间 {#reclaiming-disk-space}

`VACUUM` 会重写整个数据库，并在整个过程中持有独占锁，因此它只能是**按需、在
gateway 停止时**执行的操作，永远不会自动运行。请使用 session 浏览器中的
`optimize` 操作，它会先合并 FTS5 段，然后执行 VACUUM。

开始前请预估成本：在一个 5.1 GB 的 `state.db` 上，实测 `VACUUM` 持有独占锁约
**19.8 分钟**，仅回收了约 **3.0%** 的文件体积。更激进的清理（降低
`retention_days`）通常比 VACUUM 更有效。

### 手动清理

```bash
# 清理 90 天前的 session
hermes sessions prune

# 删除特定 session
hermes sessions delete <session_id>

# 清理前先导出（备份）
hermes sessions export backup.jsonl
hermes sessions prune --older-than 30 --yes
```

:::tip
自动清理**默认开启**：已不活跃达 `sessions.retention_days`（默认 90）天的已结束 session 会在启动时被删除，活跃 session 永远不会被触碰（见上方[自动清理](#automatic-cleanup)）。Session 历史为跨历史对话的 `session_search` 召回提供支持，因此如果你想永久保留每个已结束的 session，请在 `config.yaml` 中设置 `sessions.auto_prune: false`，或调大 `retention_days`。关闭自动清理后，`hermes sessions prune` 仍可用于一次性清理（完全不清理时已观察到的故障模式：约 1000 个 session 的 384 MB `state.db` 导致 FTS5 插入和 `/resume` 列表变慢）。
:::