---
sidebar_position: 4
title: "Slack"
description: "使用 Socket Mode 将 Hermes Agent 设置为 Slack 机器人"
---

# Slack 设置

使用 Socket Mode 将 Hermes Agent 作为机器人连接到 Slack。Socket Mode 使用 WebSocket 而非公开 HTTP 端点，因此你的 Hermes 实例无需公开访问——它可以在防火墙后、笔记本电脑上或私有服务器上正常运行。

:::warning 经典 Slack 应用已弃用
使用 RTM API 的经典 Slack 应用已于 **2025 年 3 月完全弃用**。Hermes 使用带有 Socket Mode 的现代 Bolt SDK。如果你有旧的经典应用，必须按照以下步骤创建新应用。
:::

## 概述

| 组件 | 值 |
|-----------|-------|
| **库** | Python 的 `slack-bolt` / `slack_sdk`（Socket Mode） |
| **连接方式** | WebSocket——无需公开 URL |
| **所需认证令牌** | Bot Token（`xoxb-`）+ App-Level Token（`xapp-`） |
| **用户标识** | Slack Member ID（例如 `U01ABC2DEF3`） |

---

## 第一步：创建 Slack 应用

最快的方式是粘贴 Hermes 为你生成的 manifest（清单文件）。它会一次性声明所有内置斜杠命令（`/btw`、`/stop`、`/model`……）、所有必需的 OAuth 权限范围、所有事件订阅，并启用 Socket Mode。

### 方式 A：使用 Hermes 生成的 manifest（推荐）

1. 生成 manifest。新建的 Slack 应用必须使用 Agent view：
   ```bash
   hermes slack manifest --agent-view --write
   ```
   此命令会将 `~/.hermes/slack-manifest.json` 写入磁盘并打印粘贴说明。仍在使用
   Slack 旧版 Assistant view 的现有应用，可以在准备好迁移之前省略
   `--agent-view`。

   如需用现有的 UTF-8 文本或 Markdown 文件填充 Slack 的应用长描述，请添加 `--long-description-file`：

   ```bash
   hermes slack manifest --agent-view \
     --long-description-file AGENTS.md --write
   ```

   在 Slack 允许的 175–4,000 字符范围内，文件内容会被原样保留。如需内联文本，请改用 `--long-description "..."`；内联选项和文件选项互斥，并且都不能与
   `--slashes-only` 同时使用。
2. 前往 [https://api.slack.com/apps](https://api.slack.com/apps) →
   **Create New App** → **From an app manifest**
3. 选择你的工作区，粘贴 JSON 内容，检查后点击 **Next** → **Create**
4. 直接跳至**第六步：将应用安装到工作区**。manifest 已为你处理好权限范围、事件和斜杠命令。

### 方式 B：从头手动创建

1. 前往 [https://api.slack.com/apps](https://api.slack.com/apps)
2. 点击 **Create New App**
3. 选择 **From scratch**
4. 输入应用名称（例如 "Hermes Agent"）并选择你的工作区
5. 点击 **Create App**

你将进入应用的 **Basic Information** 页面。继续执行下方第 2–6 步。

---

## 第二步：配置 Bot Token 权限范围

在侧边栏导航至 **Features → OAuth & Permissions**。向下滚动至 **Scopes → Bot Token Scopes**，添加以下权限：

| 权限范围 | 用途 |
|-------|---------|
| `chat:write` | 以机器人身份发送消息 |
| `app_mentions:read` | 检测在频道中被 @ 提及的情况 |
| `channels:history` | 读取机器人所在公开频道的消息 |
| `channels:read` | 列出并获取公开频道信息 |
| `groups:history` | 读取机器人被邀请加入的私有频道消息 |
| `im:history` | 读取私信历史记录 |
| `im:read` | 查看基本私信信息 |
| `im:write` | 打开并管理私信 |
| `mpim:history` | 读取群组私信（多人私信）历史记录 |
| `mpim:read` | 查看基本群组私信信息 |
| `users:read` | 查询用户信息 |
| `files:read` | 读取并下载附件文件，包括语音备忘录/音频 |
| `files:write` | 上传文件（图片、音频、文档） |

:::caution 缺少权限范围 = 功能缺失
没有 `channels:history` 和 `groups:history`，机器人**将无法接收频道消息**——它只能在私信中工作。没有 `files:read`，Hermes 可以聊天，但**无法可靠读取用户上传的附件**。这是最常被遗漏的权限范围。
:::

**可选权限范围：**

| 权限范围 | 用途 |
|-------|---------|
| `groups:read` | 列出并获取私有频道信息 |
| `assistant:write` | 在机器人处理消息时，于机器人名称旁渲染工作状态提示行（"is thinking…"）。缺少此权限范围时，`assistant.threads.setStatus` 调用会静默失败，Slack 转而显示它自己轮换的通用占位文本（"Finding answers…"、"Reviewing findings…" 等）——Hermes 完全无法控制该文本。`typing_status_text` 要产生任何可见效果都需要此权限范围。 |

---

## 第三步：启用 Socket Mode

Socket Mode 让机器人通过 WebSocket 连接，无需公开 URL。

1. 在侧边栏前往 **Settings → Socket Mode**
2. 将 **Enable Socket Mode** 切换为开启
3. 系统会提示你创建一个 **App-Level Token**：
   - 命名为类似 `hermes-socket` 的名称（名称不重要）
   - 添加 **`connections:write`** 权限范围
   - 点击 **Generate**
4. **复制该令牌**——它以 `xapp-` 开头。这就是你的 `SLACK_APP_TOKEN`

:::tip
你随时可以在 **Settings → Basic Information → App-Level Tokens** 下找到或重新生成 App-Level Token。
:::

---

## 第四步：订阅事件

此步骤至关重要——它控制机器人能看到哪些消息。

1. 在侧边栏前往 **Features → Event Subscriptions**
2. 将 **Enable Events** 切换为开启
3. 展开 **Subscribe to bot events** 并添加：

| 事件 | 是否必需 | 用途 |
|-------|-----------|---------|
| `message.im` | **必需** | 机器人接收私信 |
| `message.mpim` | **必需** | 机器人接收其加入的**群组私信**（多人私信）消息 |
| `message.channels` | **必需** | 机器人接收其加入的**公开**频道消息 |
| `message.groups` | **推荐** | 机器人接收被邀请加入的**私有**频道消息 |
| `app_mention` | **必需** | 防止机器人被 @ 提及时出现 Bolt SDK 错误 |

4. 点击页面底部的 **Save Changes**

:::danger 缺少事件订阅是第一大设置问题
如果机器人在私信中正常工作但**在频道中不响应**，你几乎肯定忘记添加 `message.channels`（公开频道）和/或 `message.groups`（私有频道）。没有这些事件，Slack 根本不会将频道消息传递给机器人。
:::

---

## 第五步：启用 Messages Tab

此步骤启用对机器人的私信功能。没有它，用户在尝试私信机器人时会看到**"向此应用发送消息已被关闭"**的提示。

1. 在侧边栏前往 **Features → App Home**
2. 向下滚动至 **Show Tabs**
3. 将 **Messages Tab** 切换为开启
4. 勾选 **"Allow users to send Slash commands and messages from the messages tab"**

:::danger 没有此步骤，私信将被完全屏蔽
即使拥有所有正确的权限范围和事件订阅，除非启用 Messages Tab，否则 Slack 不允许用户向机器人发送私信。这是 Slack 平台的要求，而非 Hermes 的配置问题。
:::

---

## 第六步：将应用安装到工作区

1. 在侧边栏前往 **Settings → Install App**
2. 点击 **Install to Workspace**
3. 检查权限并点击 **Allow**
4. 授权后，你将看到一个以 `xoxb-` 开头的 **Bot User OAuth Token**
5. **复制此令牌**——这就是你的 `SLACK_BOT_TOKEN`

:::tip
如果你之后更改了权限范围或事件订阅，**必须重新安装应用**才能使更改生效。Install App 页面会显示提示横幅。
:::

---

## 第七步：查找用于白名单的用户 ID

Hermes 使用 Slack **Member ID**（而非用户名或显示名称）作为白名单。

查找 Member ID 的方法：

1. 在 Slack 中点击用户的名称或头像
2. 点击 **View full profile**
3. 点击 **⋮**（更多）按钮
4. 选择 **Copy member ID**

Member ID 格式类似 `U01ABC2DEF3`。你至少需要自己的 Member ID。

---

## 第八步：配置 Hermes

将以下内容添加到你的 `~/.hermes/.env` 文件：

```bash
# 必需
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_APP_TOKEN=xapp-your-app-token-here
SLACK_ALLOWED_USERS=U01ABC2DEF3              # 逗号分隔的 Member ID

# 可选
SLACK_HOME_CHANNEL=C01234567890              # 定时/计划消息的默认频道
SLACK_HOME_CHANNEL_NAME=general              # 主频道的可读名称（可选）
```

或运行交互式设置：

```bash
hermes gateway setup    # 提示时选择 Slack
```

然后启动 gateway：

```bash
hermes gateway              # 前台运行
hermes gateway install      # 安装为用户服务
sudo hermes gateway install --system   # 仅 Linux：开机启动系统服务
```

:::tip Codex reasoning-effort 安全提示
对于由 Codex 驱动的 Slack peer-agent 频道，建议使用 `agent.reasoning_effort: high` 或更低值。
`xhigh` 可能会把整轮时间都花在隐藏推理上，从而始终不产生可见的 assistant 文本；Hermes 现在
会在话题中抑制这类"轮次未完成"警告，并把诊断信息保留在 gateway 日志中。
:::

---

## 第九步：将机器人邀请到频道

启动 gateway 后，你需要**邀请机器人**加入希望它响应的频道：

```
/invite @Hermes Agent
```

机器人**不会**自动加入频道。你必须逐个频道邀请它。

---

## 斜杠命令

大多数 Hermes 命令（`/btw`、`/stop`、`/new`、`/model`、`/help`……）都是原生 Slack 斜杠命令，与 Telegram 和 Discord 保持一致。在 Slack 中输入 `/`，自动补全选择器会列出这些命令及其描述。

Slack 只允许每个应用注册 50 个斜杠命令。被有意排除在这一原生名额之外的命令，仍可通过 `/hermes <命令>` 使用。目前这包括对确认较为敏感的 DevFlow 决策流程：使用 `/hermes ddp-approve <request-id> <evidence>`，随后使用 `/hermes ddp-approve-confirm <token>`（或对应的拒绝形式）。在没有 Slack manifest 数量限制的平台上，可以直接使用不带前缀的 `/ddp-approve` 语法。

底层实现：Hermes 附带一个生成的 Slack 应用 manifest（见第一步，方式 A），它将 [`COMMAND_REGISTRY`](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/commands.py) 中的原生子集声明为斜杠命令。在 Socket Mode 下，无论 manifest 的 `url` 字段如何，Slack 都会通过 WebSocket 路由命令事件。

### Agent 消息体验

新建的 Slack 应用使用 Slack 的 **Agent** 消息体验。现有的 Hermes Assistant 应用可以通过使用 `--agent-view` 重新生成 manifest 来迁移：

```bash
hermes slack manifest --agent-view --write
```

在 **Features → App Manifest** 中更新 manifest，如果 Slack 提示，请重新安装应用。Agent view 无法回退到 Assistant view，切换后用户可能需要强制刷新 Slack。生成的 Agent manifest 会订阅 `message.im`、`app_home_opened` 和 `app_context_changed`，使 Hermes 能够识别 Messages 标签页中的私信，并随每一轮接收用户当前的 Slack 上下文。Hermes 只把该上下文作为标签使用；它不会读取所查看频道的历史记录。

### 更新后刷新斜杠命令

当 Hermes 添加新命令时（例如执行 `hermes update` 后），重新生成 manifest 并更新你的 Slack 应用：

```bash
hermes slack manifest --write
```

然后在 Slack 中：
1. 打开 [https://api.slack.com/apps](https://api.slack.com/apps) →
   你的 Hermes 应用
2. **Features → App Manifest → Edit**
3. 粘贴 `~/.hermes/slack-manifest.json` 的新内容
4. **保存**。如果权限范围或斜杠命令有变化，Slack 会提示重新安装应用。

### 旧版 `/hermes <子命令>` 仍然有效

为了向后兼容旧版 manifest，你仍然可以输入 `/hermes bg run the tests`——Hermes 会以与 `/bg
run the tests` 相同的方式路由它。自由形式的问题也有效：`/hermes what's the weather?` 会被当作普通消息处理。

### 在话题（thread）中使用命令（`!cmd` 前缀） {#using-commands-inside-threads-the-cmd-prefix}

Slack 本身会阻止在话题回复中使用原生斜杠命令——在话题中尝试 `/queue`，Slack 会回复 *"/queue is not supported in threads. Sorry!"*。没有任何应用端设置可以重新启用它们；Slack 从不将它们传递给 Hermes。

作为解决方案，Hermes 识别前导 `!` 作为在话题（以及任何其他地方）中有效的替代命令前缀。在话题回复中输入 `!queue`、`!stop`、`!model gpt-5.4` 等普通回复——Hermes 会以与斜杠形式完全相同的方式处理，并在同一话题中回复。

只有第一个 token（词元）会与已知命令列表进行匹配，因此像 `!nice work` 这样的随意消息会原样传递给 agent。感叹号形式在提及之后（`@Hermes !stop`）以及带有前导空白时同样有效——两者都会在话题中作为命令分发。

审批提示（危险命令 / `execute_code` 审批）通常渲染为交互式按钮。当按钮无法送达、Hermes 回退到文本提示时，该提示会指示你回复 `!approve` / `!deny`——这是在话题中可用的形式。

### 斜杠命令的回复是临时消息 {#slash-replies-are-ephemeral}

对原生斜杠命令（例如 `/status`、`/help`）的回复以**临时消息（ephemeral）**形式投递——"仅你可见"——因此命令输出永远不会刷屏频道。"Running /cmd…" 占位消息会被替换为真实回复；较长的回复会被拆分成后续的临时消息。Slack 将回复流程限制在 5 条消息以内，因此超长输出会以明确的截断提示结束，而不是被静默丢弃。如果主临时消息路径失败，Hermes 会通过第二条临时消息 API 路径重试——斜杠命令的回复永远不会作为回退方案公开发布到频道中。（以普通消息形式输入的命令——话题中的 `!cmd`、`@Hermes /cmd`——则会以普通的可见消息回复。）

### 澄清提示（一键按钮） {#clarify-prompts-one-tap-buttons}

当 agent 需要向你提出一个多选问题（`clarify` 工具）时，Slack 会将其渲染为 **Block Kit 按钮**——每个选项一次点击即可，另有一个 "✏️ Other…" 按钮用于切换到自由文本模式（你输入的下一条消息即为答案）。点击后，该消息会原地更新，显示是谁回答以及选择了什么；之后对同一提示的点击会被忽略。按钮点击遵循与消息相同的用户授权，已过期的提示（gateway 重启、超时）会提示你重新提问，而不是静默吞掉这次点击。开放式的澄清问题会渲染为普通问题，并接受你输入的下一条回复。无需任何配置——无论 `rich_blocks` 如何设置都能工作。

### 高级：仅输出斜杠命令数组

如果你手动维护 Slack manifest 并只需要斜杠命令列表：

```bash
hermes slack manifest --slashes-only > /tmp/slashes.json
```

将该数组粘贴到现有 manifest 的 `features.slash_commands` 键中。

---

## 机器人的响应方式

了解 Hermes 在不同场景下的行为：

| 场景 | 行为 |
|---------|----------|
| **私信** | 机器人响应每条消息——无需 @ 提及 |
| **频道** | 机器人**仅在被 @ 提及时响应**（例如 `@Hermes Agent what time is it?`）。在频道中，Hermes 在该消息附带的话题中回复。 |
| **话题** | 如果你在现有话题中 @ 提及 Hermes，它会在同一话题中回复。一旦机器人在话题中有活跃会话，**该话题中的后续回复无需 @ 提及**——机器人会自然跟进对话。 |

:::tip
在频道中，始终 @ 提及机器人来开始对话。一旦机器人在话题中活跃，你可以在该话题中回复而无需提及它。话题之外，没有 @ 提及的消息会被忽略，以防止在繁忙频道中产生噪音。
:::

---

## 配置选项

除了第八步中的必需环境变量外，你还可以通过 `~/.hermes/config.yaml` 自定义 Slack 机器人行为。

### 话题与回复行为

```yaml
platforms:
  slack:
    # 控制多部分响应的话题方式
    # "off"   — 永不将回复串入原始消息的话题
    # "first" — 第一个分块串入用户消息（默认）
    # "all"   — 所有分块串入用户消息
    reply_to_mode: "first"

    extra:
      # 是否在话题中回复（默认：true）。
      # 为 false 时，频道消息直接在频道中回复，而非话题。
      # 已在话题中的消息仍在话题中回复。
      reply_in_thread: true

      # 同时将话题回复发布到主频道
      # （Slack 的"同时发送到频道"功能）。
      # 仅广播第一条回复的第一个分块。
      reply_broadcast: false

      # 控制 Slack 自动生成的链接预览卡片，而不修改或移除消息文本中
      # 可点击的链接。省略任一键即对该预览类型保留 Slack 的默认行为。
      unfurl_links: false
      unfurl_media: false

      # 将 Agent 消息渲染为 Slack Block Kit 区块（默认：false）。
      # 为 true 时，最终的 Agent 消息会以结构化区块发送——包括
      # 章节标题、分隔线、真正的嵌套列表（通过 rich_text）以及
      # 原生 Block Kit 表格——而非扁平的 mrkdwn 文本。同时始终附带
      # 纯文本回退内容，用于通知和无障碍访问。超出 Slack 限制
      # （100 行 / 20 列 / 1 万字符）的表格会优雅地回退为对齐的等宽文本。
      rich_blocks: false

      # 为最终的 Block Kit 回复追加 Slack 原生反馈控件。
      # 需要 rich_blocks: true。默认：false。
      feedback_buttons: false

      # 将实时工具调用渲染为 Slack 原生的计划/任务卡片。这一显式选项
      # 即使在文本 tool_progress 关闭时也会启用原生进度。
      # 如果 Slack 拒绝原生流，Hermes 会在本轮剩余时间内保持一条可编辑的
      # 文本回退消息为最新状态。
      native_task_cards: false

      # 固定在 Agent view Messages 标签页顶部的建议提示。
      # 可以是 {title, message} 行的列表，或带标题的对象：
      # {title: "Start here", prompts: [{title: "Plan", message: "..."}]}
      suggested_prompts: []

      # 根据用户的第一条消息为 Agent/Assistant 私信话题命名。
      # 默认：true。设为 false 则保留 Slack 的默认话题标题。
      assistant_thread_titles: true

      # 接受由其他 Slack 机器人发布的消息（默认："none"）。
      # "none" 忽略机器人，"mentions" 仅当该机器人消息本身 @提及 Hermes
      # 时才接受，"all" 接受所有其他机器人。Hermes 始终忽略自己的
      # 机器人用户，以防止自我回声。
      allow_bots: "none"

      # 可继续 cron 任务的投递方式（默认："thread"）。
      # "in_channel" 将可继续的 cron 任务直接平铺投递到频道中
      # （不新建话题）；需与 reply_in_thread: false（及
      # require_mention: false）搭配，纯文本回复即可继续任务。
      # 详见 cron 指南 →“平铺频道内继续”。
      cron_continuable_surface: thread
```

| 键 | 默认值 | 描述 |
|-----|---------|-------------|
| `platforms.slack.reply_to_mode` | `"first"` | 多部分消息的话题模式：`"off"`、`"first"` 或 `"all"` |
| `platforms.slack.extra.reply_in_thread` | `true` | 为 `false` 时，频道消息直接回复而非话题。已在话题中的消息仍在话题中回复。 |
| `platforms.slack.extra.reply_broadcast` | `false` | 为 `true` 时，话题回复也会发布到主频道。仅广播第一个分块。 |
| `platforms.slack.extra.unfurl_links` | Slack 默认值 | 设为 `false` 可抑制对链接网页的自动预览，同时保留可点击的链接。设置任一 unfurl 键后，媒体说明文字会在文件*之前*作为单独的消息发布（Slack 的上传 API 无法携带 unfurl 控制），并且原生草稿流式输出会回退为基于编辑的投递。 |
| `platforms.slack.extra.unfurl_media` | Slack 默认值 | 设为 `false` 可抑制自动媒体预览，同时保留可点击的链接。说明文字顺序和流式输出方面的注意事项与 `unfurl_links` 相同。 |
| `platforms.slack.extra.rich_blocks` | `false` | 为 `true` 时，Agent 消息会渲染为 [Block Kit](https://docs.slack.dev/block-kit/) 区块（标题、分隔线、真正的嵌套列表以及原生表格）。始终附带纯文本回退。超出 Slack 限制的表格会回退为对齐的等宽文本。无需重新安装应用——这仅是发送端的改动。 |
| `platforms.slack.extra.feedback_buttons` | `false` | 与 `rich_blocks` 同时为 `true` 时，会在最终回复中追加 Slack 原生反馈控件。 |
| `platforms.slack.extra.native_task_cards` | `false` | 为 `true` 时，将实时工具调用渲染为 Slack 原生的计划/任务卡片。这是一个显式的进度选项，独立于 Slack 默认的 `tool_progress: off`；原生 API 失败时会回退为一条持续编辑的文本更新。 |
| `platforms.slack.extra.suggested_prompts` | `[]` | 用于 Agent/Assistant 私信入口的最多四条 `{title, message}` 提示；可接受列表或 `{title, prompts}` 形式。 |
| `platforms.slack.extra.assistant_thread_titles` | `true` | 为 `true` 时，根据用户的第一条消息为 Agent/Assistant 私信话题命名。 |
| `platforms.slack.extra.allow_bots` | `"none"` | 控制来自其他 Slack 机器人的消息：`"none"` 忽略它们，`"mentions"` 仅当**该条消息本身** @提及 Hermes 时才接受该机器人消息，`"all"` 全部接受。最安全的机器人间协作模式请使用 `"mentions"`。参见[接受来自其他机器人的消息](#accepting-messages-from-other-bots-allow_bots)。 |
| `platforms.slack.extra.api_human_users` | `[]` | 其 **Web API（用户令牌）消息被视为人类消息**的 Slack 用户 ID。这类消息带有发布方的 `app_id` 且没有 `client_msg_id`，因此默认会被当作应用流量丢弃；请在此处把你自己前端的用户加入白名单，而不是使用 `allow_bots: all`。参见[将你自己应用的用户令牌消息视为人类消息](#treating-your-own-apps-user-token-posts-as-human-api_human_users)。 |
| `platforms.slack.extra.cron_continuable_surface` | `"thread"` | [可继续 cron 任务](../features/cron.md#flat-in-channel-continuation-slack)的投递方式。`"thread"` 为每次投递新建专用话题（默认）；`"in_channel"` 直接平铺投递到频道时间线。使用 `in_channel` 时需搭配 `reply_in_thread: false`（及 `require_mention: false`），纯文本回复即可继续任务。 |

对应的环境变量是 `SLACK_ALLOW_BOTS=none|mentions|all`。两者都设置时，以 `platforms.slack.extra.allow_bots` 为准。当对等机器人无需显式提及就能互相回答时，请避免使用 `all`，因为它们各自的回复策略仍可能形成循环。

### 工作状态提示行

在 agent 处理消息期间，Slack 会在话题中的机器人名称旁显示一行状态提示。Hermes 默认将其设为 `is thinking...`；可用 `typing_status_text` 自定义——例如一只名为 Ada 的小猫助手：

```yaml
platforms:
  slack:
    # 自定义工作状态提示行（默认："is thinking..."）。
    typing_status_text: "is pouncing… 🐾"
```

| 键 | 默认值 | 描述 |
|-----|---------|-------------|
| `platforms.slack.typing_status_text` | `"is thinking..."` | agent 处理消息期间显示的工作状态提示行文本。需要 `assistant:write` 权限范围——缺少该权限时，状态调用会静默失败，无论此处设置为何，Slack 都会渲染它自己的通用占位文本。设置 `typing_indicator: false` 可完全禁用状态提示行。 |

:::note 状态显示在哪里
自定义状态出现在**回复输入框下方的页脚**中（"*BotName* is thinking…"），而不是消息列表中的行内位置。AI 应用工作时 Slack 在消息区域显示的行内 "Generating response…" / "Finding answers…" 是 **Slack 自己的轮换指示器**——`assistant.threads.setStatus` 不控制它们，且两者可能同时出现。
:::

同一个键也用于自定义 Google Chat 的可见工作状态标记消息（`platforms.google_chat.typing_status_text`，默认 `"Hermes is thinking…"`）——注意在 Google Chat 上它是一条真实发布的消息，随后会被修补为回复内容，而非临时状态。

### 实时状态（按工具）

默认情况下，状态提示行会**随 agent 的工作实时更新**：它显示的不是静态的 `is thinking...`，而是 agent 当前正在做什么——`is running pytest tests/…`、`is reading docs/api.md…`、`is searching the web for slack api limits…`。在两次工具调用之间，它会回到静态文本。它复用已有的状态刷新节奏，因此不会产生额外的 Slack API 调用；即使 `tool_progress: off`（Slack 的默认值）它同样有效——与进度气泡不同，状态提示行是临时的，不会在频道中留下任何内容。

通过 `display.live_status`（全局或按平台）控制：

```yaml
display:
  platforms:
    slack:
      # full = 动词 + 参数（"is running pytest…"）   [默认]
      # verb = 仅动词（"is running…"）——隐藏命令/路径，
      #        适用于共享或面向客户的频道
      # off  = 静态文本（typing_status_text 或 "is thinking..."）
      live_status: full
```

| 键 | 默认值 | 描述 |
|-----|---------|-------------|
| `display.live_status` | `"full"` | 按工具的实时状态提示行。`full` 显示动词 + 参数预览；`verb` 仅显示动词（避免把文件路径和命令暴露到共享频道）；`off` 恢复静态文本。与静态状态提示行一样，需要 `assistant:write` 权限范围。 |

### 原生流式输出（实时打字式回复） {#native-streaming-live-typing-replies}

Slack 的 [Agents & AI Apps](https://docs.slack.dev/ai/) 功能提供了原生流式输出界面（`chat.startStream` / `chat.appendStream` /
`chat.stopStream`），会把回复渲染为实时打字的消息——比其他情况下使用的基于编辑的渐进式更新流畅得多。当 `streaming.enabled` 开启（传输方式为 `auto` 或 `draft`）时，Hermes 会在可用的地方自动使用原生流式输出：

- 流在第一帧开始，并且只追加增量（该 API 只能追加）。流式输出的消息**就是**最终消息——Hermes 通过 `chat.stopStream` 将其封存，而不是再发布一条重复的最终回复。
- 如果你的 Slack 应用没有启用 AI 功能（或缺少 `assistant:write` 权限范围），第一次失败会被缓存，Hermes 会回退到基于编辑的流式输出，并记录一条指明修复方法的警告日志。
- 可选的 Block Kit（`rich_blocks: true`）会应用到封存后的消息上，与基于编辑的收尾路径相同。

除了启用流式输出外，无需额外配置：

```yaml
streaming:
  enabled: true       # 传输方式 auto/draft 会启用 Slack 原生流式输出
```

### 原生任务卡片（实时工具进度） {#native-task-cards-live-tool-progress}

设置 `platforms.slack.extra.native_task_cards: true` 后，实时工具调用会渲染为 Slack 原生的**计划/任务卡片**（与 Slack 自己的 AI 功能使用的界面相同），而不是文本进度气泡：每轮一张卡片，每次工具调用一行，每个任务的运行中/完成/错误状态会原地更新。

```yaml
platforms:
  slack:
    extra:
      native_task_cards: true
```

- 这是一个显式的进度选项——即使 Slack 的默认值是 `tool_progress: off`，它也能工作（文本气泡会刷屏频道；原生卡片不会）。
- 对同一工具的并发调用会按真实的工具调用 ID 关联，因此并行的 `web_search` 调用各自拥有一行并显示正确的状态。
- 如果原生流无法启动或更新，Hermes 会回退为一条持续编辑的文本消息，让进度在整轮中保持实时。
- 卡片流在本轮收尾时恰好停止一次，包括中断/断开连接的情况，因此不会残留悬空的实时指示器。

### 会话隔离

```yaml
# 全局设置——适用于 Slack 和所有其他平台
group_sessions_per_user: true
```

为 `true`（默认值）时，共享频道中的每个用户都有自己独立的对话会话。在 `#general` 中与 Hermes 对话的两个人将有各自独立的历史记录和上下文。

设为 `false` 可启用协作模式，整个频道共享一个对话会话。请注意，这意味着用户共享上下文增长和 token 成本，且一个用户的 `/reset` 会清除所有人的会话。

### 提及与触发行为

```yaml
slack:
  # 在频道中要求 @mention（这是默认行为；
  # Slack 适配器无论如何都会在频道中强制执行 @mention 门控，
  # 但你可以明确设置此项以与其他平台保持一致）
  require_mention: true

  # 防止话题自动参与：仅回复包含明确 @mention 的频道消息。
  # 关闭此项（默认），Slack 可以"自动参与"——记住话题中的过去提及，
  # 跟进机器人消息的回复，并在无需新提及的情况下恢复活跃会话。
  # 开启 strict_mention 后，每条新频道消息都必须 @mention 机器人，
  # Hermes 才会响应。
  strict_mention: false

  # 忽略发给其他用户的消息：当频道或话题消息以 @提及机器人以外的人
  # *开头*时（例如 "@rasha can you take this?"），除非同时提及了机器人，
  # 否则保持沉默。只有*开头*的提及才算"发给某人"——在句中提到某人的
  # 消息（"loop in @rasha"）仍会送达机器人。优先于 free_response_channels
  # 和话题自动参与。需手动启用；默认关闭。环境变量：SLACK_IGNORE_OTHER_USER_MENTIONS。
  ignore_other_user_mentions: false

  # 对话题回复要求明确的 @mention，而顶层频道消息仍由 require_mention /
  # free_response_channels 控制。比 strict_mention 范围更窄：当一个自由响应的
  # 机器人不应加入繁忙话题中的每一条后续消息时使用。
  # 需手动启用；默认关闭。环境变量：SLACK_THREAD_REQUIRE_MENTION。
  thread_require_mention: false

  # 按频道强制要求提及——与 free_response_channels 方向相反。
  # 此处列出的频道始终需要明确的 @mention，即使全局 require_mention 为 false。
  # 进行中的对话仍会自动跟进（被提及的话题、活跃会话、机器人发起的话题）。
  # 逗号分隔的 ID 或列表。
  # 环境变量：SLACK_REQUIRE_MENTION_CHANNELS。
  require_mention_channels: ""

  # 触发机器人的自定义提及模式
  # （除默认 @mention 检测外）
  mention_patterns:
    - "hey hermes"
    - "hermes,"

  # 每条发出消息前添加的文本
  reply_prefix: ""
```

:::tip 何时使用 `strict_mention`
在繁忙工作区中，如果 Slack 默认的"机器人记住此话题"行为让用户感到意外，请将此项设为 `true`——例如，在一个长技术支持话题中，机器人在开始时提供了帮助，而你希望它保持沉默，除非被明确 @ 提及。私信和活跃的交互会话不受影响。
:::

:::tip 何时使用 `ignore_other_user_mentions`
当机器人跟进繁忙话题（通过话题自动参与或 `free_response_channels`）并插话到人与人之间的对话时，请将此项设为 `true`。它比 `strict_mention` 更有针对性：已参与话题中的普通后续消息仍会得到回复；只有以 @提及另一个人开头的消息才会被跳过。**一对一私信不受影响**；群组私信（MPIM）和频道都会应用它，与下文的共享场所策略一致。广播 token（`@here`、`@channel`）和频道引用针对的是整个房间而不是某个人，因此永远不会被跳过。
:::

:::info
Slack 支持两种模式：默认情况下需要 `@mention` 才能开始对话，但你可以通过 `SLACK_FREE_RESPONSE_CHANNELS`（逗号分隔的频道 ID）或 `config.yaml` 中的 `slack.free_response_channels` 为特定频道取消此限制。一旦机器人在话题中有活跃会话，后续话题回复无需提及。在**一对一私信**中，机器人始终响应，无需提及。
:::

:::caution 群组私信（MPIM）是共享场所，而非一对一私信
**一对一私信**是与单个人的私密对话，因此豁免提及要求。**群组私信（MPIM / 多人私信）**是*共享场所*——多个人都能看到并触发机器人——因此它遵循与频道相同的运维控制：`require_mention`、`strict_mention`、`free_response_channels` 和 `allowed_channels` 全部适用，并且只有在真正被 `@mentioned`（@ 提及）时，机器人才会添加 `:eyes:`/`:white_check_mark:` 反应。若要让机器人在某个特定群组私信中自由响应，请把它的频道 ID（以 `G` 开头）加入 `free_response_channels`。
:::

#### 我该用哪个提及选项？ {#which-mention-option-do-i-want}

这些门控选项可以组合使用——每个选项回答的是不同的问题：

| 选项 | 它回答的问题 | 默认值 | 作用范围 |
|--------|--------------------|---------|-------|
| `require_mention` | **顶层频道消息**是否需要 @mention？ | `true` | 所有频道 |
| `free_response_channels` | 哪些频道豁免 `require_mention`？ | 无 | 列出的频道 |
| `require_mention_channels` | 哪些频道始终需要 @mention，即使 `require_mention` 为 `false` 或该频道是自由响应频道？优先于前两者。 | 无 | 列出的频道 |
| `thread_require_mention` | 即使顶层消息不需要，**话题回复**是否需要 @mention？被提及的话题不会被记住。 | `false` | 仅话题 |
| `strict_mention` | **每一条**频道消息（顶层和话题）是否都需要新的 @mention？会禁用所有自动跟进：被提及话题的记忆、机器人回复的跟进、活跃会话的恢复。 | `false` | 所有频道 + 话题 |
| `ignore_other_user_mentions` | 以 **@提及其他人开头**的消息（`@rasha can you take this?`）是否应被跳过？优先于自由响应和话题自动跟进；句中提及仍会送达机器人。 | `false` | 频道 + 群组私信 |

经验法则：`strict_mention` 是覆盖面最广的"大锤"；`thread_require_mention` 让繁忙话题安静下来，而不影响顶层门控；`require_mention_channels` 在原本自由响应的机器人上重新收紧个别频道；`ignore_other_user_mentions` 只跳过明确发给另一个人的消息。一对一私信始终会响应，不受以上任何选项影响。

### 接受来自其他机器人的消息（`allow_bots`） {#accepting-messages-from-other-bots-allow_bots}

默认情况下，Hermes 会忽略由其他 Slack 机器人或应用发出的每一条消息（包括 Workflow Builder 发布的消息）。对于多智能体工作区——多个 Hermes 实例或对等机器人在同一频道中协作——可通过 `allow_bots` 选择启用：

```yaml
platforms:
  slack:
    extra:
      # "none"（默认）— 忽略所有由机器人/应用发出的消息
      # "mentions"      — 仅当该条消息本身 @提及本机器人时
      #                    才接受该机器人消息
      # "all"           — 接受所有机器人消息（机器人自身的消息除外）
      allow_bots: mentions
```

对应的环境变量：`SLACK_ALLOW_BOTS=none|mentions|all`（两者都设置时以配置键为准）。未知值按 `none` 处理。

`mentions` 模式的门控方式：

- 对等机器人的消息**只有在该消息本身包含对本机器人的当前 `@mention` 时**才会被接受——无论是在文本中还是在其 Block Kit 区块中。话题历史不算数：机器人此前在话题中被提及过、对机器人自身消息的回复、活跃的话题会话，都**不会**让之后未提及的对等机器人消息被接受。这是有意为之——正是这一点打破了智能体之间的确认/状态循环。
- 人类消息不受影响；对它们适用常规的提及门控。
- 在任何模式下，Hermes 始终会忽略自己的消息，以防止自我回声循环。

`mentions` 是机器人之间协作的推荐模式：每个智能体都必须在每一轮中显式召唤对方。除非每个对等机器人自身的回复策略都能避免循环，否则不要使用 `all`——两个对所有消息都回复的机器人会永远互相回复下去。检测范围涵盖带标记的机器人消息（`bot_id`、`subtype: bot_message`）、应用发出的事件，以及未带标记的机器人*用户*（通过 `users.info` 探测），因此对等的 Hermes 智能体会在各个工作区中被一致地过滤。

对于严格的多机器人部署，请搭配 `require_mention: true` 和 `strict_mention: true`——参见下文的冒烟检查配置。

### 将你自己应用的用户令牌消息视为人类消息（`api_human_users`） {#treating-your-own-apps-user-token-posts-as-human-api_human_users}

通过 Web API 使用**用户令牌**（`xoxp-`）发布的消息是由真人发出的，但它到达时带有发布方的 `app_id`，且没有 `client_msg_id`——这正是 Hermes 用来识别应用消息的特征——因此它会被当作机器人流量丢弃。这会阻断一种常见模式：自定义前端（内部仪表盘、移动端外壳、自助终端）*以*已登录用户的身份向 Hermes 发送消息。

`allow_bots: all` 可以让这些消息通过，但它会向频道中的所有机器人敞开大门，并削弱循环防护。更好的做法是只把使用你前端的人加入白名单：

```yaml
platforms:
  slack:
    extra:
      api_human_users: ["U0AAAAAAA", "U0BBBBBBB"]
```

对应的环境变量是 `SLACK_API_HUMAN_USERS`（逗号分隔）。

范围与安全性：

- 该白名单**仅限用户**。刻意没有提供按应用 ID 的变体：现代 bot token（`xoxb-`）发布消息时具有同样的 `user` + `app_id` 形态，因此信任某个应用也会放行它自己的机器人消息，从而让循环防护失效。
- 带有 `bot_id` 或 `subtype: bot_message`、或者完全没有 `user` 的事件，无论白名单如何，始终被视为机器人消息。
- 流水线的其余部分保持不变：提及门控、`allowed_channels` 和 `SLACK_ALLOWED_USERS` 仍然适用于（现在被视为人类的）发送者。

### 表情回应触发（`reaction_triggers`） {#reaction-triggers-reaction_triggers}

默认情况下，表情回应只会被确认然后丢弃——对机器人消息点一个 👍 不会产生任何效果。设置 `slack.reaction_triggers` 可将表情回应路由到 agent 循环中（需要 `reactions:read` 权限范围，以及 Slack 应用 manifest 中的 `reaction_added`/`reaction_removed` 机器人事件订阅——可用 `hermes slack manifest` 重新生成）：

```yaml
slack:
  # 需手动启用。false/未设置（默认）= 表情回应被确认后丢弃。
  # true = 对机器人自身消息的任何表情回应都会路由到 agent。
  reaction_triggers: true
  # 或者显式的表情白名单——只有这些名称会被路由，且可以针对
  # 任意消息（表情交接工作流，例如用 :task: 进行捕获）：
  # reaction_triggers: [white_check_mark, thumbsup, task]
  # 可选的交接目标：在此频道（顶层）或话题（C123:<thread_ts>）中响应，
  # 而不是在被回应消息所在的话题中响应。
  # reaction_trigger_target: C0123456789
```

对应的环境变量：`SLACK_REACTION_TRIGGERS`（`true`/`all` 或逗号分隔的列表）和 `SLACK_REACTION_TRIGGER_TARGET`。

行为说明：

- 表情回应会作为一次普通的 agent 轮次到达，文本为 `reaction:added:👍` / `reaction:removed:👍`（常见的 Slack 名称会被转换为 unicode；未知名称原样传递，例如 `reaction:added:custom-emoji`），并串在被回应的消息之下，这样 agent 能看到被回应的是什么，这一轮也会落在与回复相同的会话中。
- 做出回应的人会成为该消息的用户，因此**用户授权和 `allowed_channels` 门控的适用方式与输入消息完全相同**——任意用户的表情回应无法在其消息本来无法触发 agent 的地方触发 agent。
- 使用 `reaction_triggers: true` 时，只有对机器人**自身**消息的表情回应才会被路由（审批/确认流程）。使用显式表情白名单时，列出的表情可以从任意消息路由。
- 机器人自己的生命周期表情回应（`:eyes:` 等）永远不会回流。
- 与该选项无关，每一次人类表情回应都会触发 `reaction:added`/`reaction:removed` [gateway hook](../features/hooks.md#available-events)，供不需要 agent 轮次的观察者使用。

### 对等智能体冒烟检查 {#peer-agent-smoke-check}

对于依赖严格按轮提及的多机器人 Slack 部署，请保持以下配置：

```yaml
slack:
  require_mention: true
  strict_mention: true
  allow_bots: mentions
  allowed_channels: ""
```

在 gateway 配置变更、部署或重启之后，运行以下合成冒烟测试目标：

```bash
uv run --frozen pytest -q tests/gateway/test_slack_peer_agent_smoke.py -o addopts=''
```

该目标只使用进程内合成的 Slack 事件。它不会发送真实的 Slack 消息，默认也不需要真实的 bot token。

失败类别：

- `config:` `test_peer_agent_smoke_preflight_contract` 捕获到配置不匹配（`require_mention`、`strict_mention`、`allow_bots` 或 `allowed_channels`）。
- `platform_connectivity:` 适配器/客户端未初始化，因此路由冒烟结果尚不可信。
- `bot_identity:` 适配器始终没有解析出其机器人用户 ID，因此针对当前消息的提及检查无法工作。
- `routing_logic:` Slack 适配器在某个对等智能体不变式上出现回归（人类提及路由、忽略对等机器人、接受显式的对等提及，或抑制被动的确认/状态/错误消息）。

如果该目标通过但真实工作区中仍然错误路由消息，请排查 Slack token/工作区连通性以及路由逻辑之外的运行时部署状态。

### 频道白名单（`allowed_channels`）

将机器人限制在固定的 Slack 频道集合中——当机器人被邀请到许多频道但只应在少数频道中响应时很有用。设置后，不在此列表中的频道消息将被**静默忽略**，即使机器人被 `@mentioned`（@ 提及）。

**一对一私信不受此过滤器影响**，因此授权用户始终可以通过私信联系机器人。**群组私信（MPIM）不豁免**——与频道一样，MPIM 必须在白名单中（其 ID 以 `G` 开头），否则其消息会被丢弃。

```yaml
slack:
  allowed_channels:
    - "C0123456789"   # #ops
    - "C0987654321"   # #incident-response
```

或通过环境变量（逗号分隔）：

```bash
SLACK_ALLOWED_CHANNELS="C0123456789,C0987654321"
```

行为说明：

- 空/未设置 → 无限制（完全向后兼容）。
- 非空 → 频道 ID 必须在列表中，否则消息在任何其他门控（提及要求、`free_response_channels` 等）运行之前被丢弃。
- Slack 频道 ID 以 `C`（公开）、`G`（私有）或 `D`（私信）开头。可通过 Slack UI 的"打开频道详情"→"关于"面板或 API 查找。

另见：[管理员/用户斜杠命令分离](../../reference/slash-commands.md#permissions-and-adminuser-split)。

### 未授权用户处理

```yaml
slack:
  # 当未授权用户（不在 SLACK_ALLOWED_USERS 中）私信机器人时的处理方式
  # "pair"   — 提示他们输入配对码（默认）
  # "ignore" — 静默丢弃消息
  unauthorized_dm_behavior: "pair"
```

你也可以为所有平台全局设置：

```yaml
unauthorized_dm_behavior: "pair"
```

`slack:` 下的平台特定设置优先于全局设置。

### 语音转录

```yaml
# 全局设置——启用/禁用传入语音消息的自动转录
stt_enabled: true
```

为 `true`（默认值）时，传入的音频消息会在被 agent 处理之前，使用配置的 STT 提供商自动转录。

### 完整示例

```yaml
# 全局 gateway 设置
group_sessions_per_user: true
unauthorized_dm_behavior: "pair"
stt_enabled: true

# Slack 特定设置
slack:
  require_mention: true
  unauthorized_dm_behavior: "pair"

# 平台配置
platforms:
  slack:
    reply_to_mode: "first"
    extra:
      reply_in_thread: true
      reply_broadcast: false
```

---

## 主频道

将 `SLACK_HOME_CHANNEL` 设置为频道 ID，Hermes 将在此频道发送计划消息、定时任务结果和其他主动通知。查找频道 ID 的方法：

1. 在 Slack 中右键点击频道名称
2. 点击 **View channel details**
3. 向下滚动——频道 ID 显示在底部

```bash
SLACK_HOME_CHANNEL=C01234567890
```

确保机器人已被**邀请到该频道**（`/invite @Hermes Agent`）。

### Cron 投递目标 {#cron-delivery-targeting}

Cron 任务（参见 [cron 指南](../features/cron.md#delivery-options)）可以通过三种方式将 Slack 作为目标：

| `deliver:` 值 | 投递位置 |
|------------------|----------------|
| `slack` | 主频道（`SLACK_HOME_CHANNEL`） |
| `slack:C0123456789` | 按 ID 指定的特定频道 |
| `slack:U0123456789` | 该用户的**私信**——裸用户 ID 会被自动解析为私信会话（需要 `im:write` 权限范围） |

即使 cron 进程与 gateway 不在同一处运行，投递也能正常工作——Hermes 会回退到使用 `SLACK_BOT_TOKEN` 的独立 Web API 发送器。cron 输出中的 `MEDIA:` 附件会以原生 Slack 文件分享的形式上传到同一目标。

### 发送消息与媒体（`send_message`） {#sending-messages-and-media-send_message}

agent 的 `send_message` 工具接受同样的目标形式：频道 ID（`C…`/`G…`）、私信会话（`D…`），或裸用户 ID（`U…`/`W…`）——后者在每条发送路径上都会被解析为该用户的私信，无论是文本、媒体还是交互式提示。`MEDIA:<path>` 附件（图片、PDF、文档）以原生文件分享的形式上传；当一条简短消息伴随单个附件时，它会作为该文件的说明文字，而不是单独发送一条消息。缺失的文件会按文件逐一报告为警告，而不会让整次发送失败。

---

## 多工作区支持

Hermes 可以使用单个 gateway 实例**同时连接多个 Slack 工作区**。每个工作区使用其自己的机器人用户 ID 独立认证。

### 配置

在 `SLACK_BOT_TOKEN` 中以**逗号分隔列表**的形式提供多个 bot token：

```bash
# 多个 bot token——每个工作区一个
SLACK_BOT_TOKEN=xoxb-workspace1-token,xoxb-workspace2-token,xoxb-workspace3-token

# Socket Mode 仍使用单个 app-level token
SLACK_APP_TOKEN=xapp-your-app-token
```

或在 `~/.hermes/config.yaml` 中：

```yaml
platforms:
  slack:
    token: "xoxb-workspace1-token,xoxb-workspace2-token"
```

### OAuth Token 文件

除了环境变量或配置中的 token 外，Hermes 还会从以下位置的 **OAuth token 文件**加载 token：

```
~/.hermes/slack_tokens.json
```

此文件是一个将团队 ID 映射到 token 条目的 JSON 对象：

```json
{
  "T01ABC2DEF3": {
    "token": "xoxb-workspace-token-here",
    "team_name": "My Workspace"
  }
}
```

此文件中的 token 会与通过 `SLACK_BOT_TOKEN` 指定的 token 合并。重复的 token 会自动去重。

### 工作原理

- 列表中的**第一个 token** 是主 token，用于 Socket Mode 连接（AsyncApp）。
- 每个 token 在启动时通过 `auth.test` 进行认证。gateway 将每个 `team_id` 映射到其自己的 `WebClient` 和 `bot_user_id`。
- 消息到达时，Hermes 使用正确的工作区特定客户端进行响应。
- 主 `bot_user_id`（来自第一个 token）用于向后兼容期望单一机器人身份的功能。

---

## 语音消息

Hermes 支持 Slack 上的语音功能：

- **传入：** 语音/音频消息使用配置的 STT 提供商自动转录：本地 `faster-whisper`、Groq Whisper（`GROQ_API_KEY`）或 OpenAI Whisper（`VOICE_TOOLS_OPENAI_KEY`）
- **传出：** TTS 响应以音频文件附件形式发送

---

## 按频道设置 Prompt

为特定 Slack 频道分配临时系统 prompt（提示词）。该 prompt 在运行时每轮注入——从不持久化到对话历史——因此更改立即生效。

```yaml
slack:
  channel_prompts:
    "C01RESEARCH": |
      You are a research assistant. Focus on academic sources,
      citations, and concise synthesis.
    "C02ENGINEERING": |
      Code review mode. Be precise about edge cases and
      performance implications.
```

键为 Slack 频道 ID（通过频道详情 → "关于" → 滚动到底部查找）。匹配频道中的所有消息都会将该 prompt 作为临时系统指令注入。

## 按频道绑定技能

在特定频道或私信中新会话开始时自动加载技能。与按频道设置 prompt（每轮注入）不同，技能绑定在**会话开始时**将技能内容作为用户消息注入——它成为对话历史的一部分，后续轮次无需重新加载。

这非常适合有专用用途的私信或频道（闪卡、特定领域问答机器人、支持分类频道等），在这些场景中你不希望模型自己的技能选择器在每次简短回复时决定是否加载。

```yaml
slack:
  channel_skill_bindings:
    # 私信频道——始终以"german-flashcards"模式运行
    - id: "D0ATH9TQ0G6"
      skills:
        - german-flashcards
    # 研究频道——按顺序预加载多个技能
    - id: "C01RESEARCH"
      skills:
        - arxiv
        - writing-plans
    # 简写形式：单个技能作为字符串
    - id: "C02SUPPORT"
      skill: hubspot-on-demand
```

注意事项：
- 绑定按频道 ID 匹配。对于绑定频道中的话题消息，话题继承父频道的绑定。
- 技能仅在会话开始时加载（新会话开始时）。如果更改绑定，请运行 `/new` 使其生效。
- 与 `channel_prompts` 结合使用，可在技能指令之上为每个频道设置语气/约束。

## 故障排除

| 问题 | 解决方案 |
|---------|----------|
| 机器人不响应私信 | 验证 `message.im` 在事件订阅中，且应用已重新安装 |
| 机器人在私信中正常但在频道中不响应 | **最常见问题。** 将 `message.channels` 和 `message.groups` 添加到事件订阅，重新安装应用，并用 `/invite @Hermes Agent` 邀请机器人加入频道 |
| 机器人不响应频道中的 @mention | 1) 检查 `message.channels` 事件是否已订阅。2) 机器人必须被邀请到频道。3) 确保已添加 `channels:history` 权限范围。4) 更改权限范围/事件后重新安装应用 |
| 机器人忽略私有频道中的消息 | 添加 `message.groups` 事件订阅和 `groups:history` 权限范围，然后重新安装应用并 `/invite` 机器人 |
| 机器人不响应群组私信（多人私信） | 添加 `message.mpim` 事件订阅和 `mpim:history` 权限范围（以及 `mpim:read`），然后**重新安装**应用。没有 `message.mpim`，即使 1:1 私信正常，Slack 也永远不会向机器人投递群组私信消息。 |
| 私信中出现"向此应用发送消息已被关闭" | 在 App Home 设置中启用 **Messages Tab**（见第五步） |
| "not_authed" 或 "invalid_auth" 错误 | 重新生成 Bot Token 和 App Token，更新 `.env` |
| 机器人响应但无法在频道中发帖 | 用 `/invite @Hermes Agent` 邀请机器人加入频道 |
| 机器人可以聊天但无法读取上传的图片/文件 | 添加 `files:read`，然后**重新安装**应用。当 Slack 返回权限范围/认证/权限失败时，Hermes 现在会在聊天中显示附件访问诊断信息。 |
| `missing_scope` 错误 | 在 OAuth & Permissions 中添加所需权限范围，然后**重新安装**应用 |
| Socket 频繁断开 | 检查你的网络；Bolt 会自动重连，但不稳定的连接会导致延迟 |
| 更改了权限范围/事件但没有任何变化 | 更改任何权限范围或事件订阅后，**必须重新安装**应用到工作区 |

### 快速检查清单

如果机器人在频道中不工作，请验证以下**所有**项目：

1. ✅ 已订阅 `message.channels` 事件（公开频道）
2. ✅ 已订阅 `message.groups` 事件（私有频道）
3. ✅ 已订阅 `app_mention` 事件
4. ✅ 已添加 `channels:history` 权限范围（公开频道）
5. ✅ 已添加 `groups:history` 权限范围（私有频道）
6. ✅ 添加权限范围/事件后已**重新安装**应用
7. ✅ 已**邀请**机器人加入频道（`/invite @Hermes Agent`）
8. ✅ 你在消息中**@mention** 了机器人

---

## 安全

:::warning
**始终设置 `SLACK_ALLOWED_USERS`**，填入授权用户的 Member ID。没有此设置，gateway 默认会**拒绝所有消息**作为安全措施。切勿分享你的 bot token——像密码一样对待它们。
:::

- Token 应存储在 `~/.hermes/.env` 中（文件权限 `600`）
- 定期通过 Slack 应用设置轮换 token
- 审计谁有权访问你的 Hermes 配置目录
- Socket Mode 意味着不暴露公开端点——减少一个攻击面