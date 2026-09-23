---
title: Buzz
description: "将 Hermes 连接到基于 Nostr 协议的 Buzz 社区，并中转频道消息和私信"
---

# Buzz

Buzz 适配器将 Hermes 连接到一个 [Buzz](https://github.com/block/buzz) 社区——Buzz 是 Block 基于 Nostr 协议构建的开源人机协作平台——并在 Buzz 频道（或私信）与 agent 之间中转消息。出站流量通过调用 `buzz` CLI 二进制完成（“JSON 进，JSON 出”）；入站使用原生 Nostr WebSocket 订阅（借助已内置的 `websockets` 包），并以 CLI 轮询作为后备。**无需额外的 Python 包**——只需要 `buzz` 二进制。

Buzz 会渲染 markdown，因此 agent 的回复能保留格式。图片以上传（本地文件）或链接（URL）的形式发送。回复可以通过事件 id 挂到已有消息的线程下。启用进度或状态消息时，它们会继承触发它们的 Buzz 事件作为回复锚点，而不是以无关的频道顶层帖子出现。

发送**给** agent 的文件会以 agent 的已认证身份从中继取回并缓存在本地，因此工具拿到的是真实文件路径，而不是匿名请求无法读取的 `/media/…` URL。图片、音频、视频和文档（PDF 等）都能处理。

入站消息默认通过持久的、经 NIP-42 认证的 Nostr WebSocket 订阅到达（几乎即时送达），当无法建立 WebSocket 时自动回退到 CLI 轮询。出站消息始终通过 `buzz` CLI 发送。用 `transport` / `BUZZ_TRANSPORT` 控制：`auto`（默认）、`websocket`（必须使用 WS，否则失败）或 `poll`。如果你的中继成员资格使用 NIP-OA 所有者证明，请将 `BUZZ_AUTH_TAG` 设置为由四个字符串组成的 auth tag JSON。

> 运行 `hermes gateway setup` 并选择 **Buzz**，即可获得引导式配置。

## 前置条件 {#prerequisites}

- `PATH` 中有 `buzz` CLI 二进制（或用 `BUZZ_CLI_PATH` 指向它）——在 [Buzz 仓库](https://github.com/block/buzz)中用 `cargo build --release -p buzz-cli` 构建
- 一个 Buzz 社区中继 URL（例如 `https://mycommunity.communities.buzz.xyz`）
- 一个 Nostr 私钥（nsec 或 hex），其身份已是该社区的**成员**

## 配置 Hermes {#configure-hermes}

你可以用两种方式配置 Buzz——`config.yaml` 中的 `gateway` 块（规范方式）或环境变量（会覆盖前者）。私钥是**机密**，始终应放在 `~/.hermes/.env` 中。

### 方式 A —— config.yaml {#option-a--configyaml}

```yaml
gateway:
  platforms:
    buzz:
      enabled: true
      extra:
        relay_url: https://mycommunity.communities.buzz.xyz
        attachment_hosts: []         # 入站文件额外允许的精确 HTTPS host[:port] 源
        channels:                  # 要监听的频道 UUID（留空 = 所有已加入频道）
          - ccc2bc1a-7a82-5a8f-8c4e-57a070cbe7cd
        home_channel: ccc2bc1a-7a82-5a8f-8c4e-57a070cbe7cd
        poll_interval: 4           # 入站轮询间隔秒数
        cli_path: ""               # buzz 二进制（默认：PATH，其次 ~/bin/buzz）
        credentials_file: ""       # 存放 nsec 的 JSON 文件（BUZZ_PRIVATE_KEY 的后备）
        allowed_users: []          # 留空 = 允许所有人；hex 公钥或 npub
```

另外，在 `~/.hermes/.env` 中：

```
BUZZ_PRIVATE_KEY=nsec1...
```

### 方式 B —— 环境变量 {#option-b--environment-variables}

| 变量 | 必填 | 说明 |
|----------|:--------:|-------------|
| `BUZZ_RELAY_URL` | ✅ | 社区中继的基础 URL |
| `BUZZ_PRIVATE_KEY` | ✅ | Nostr 私钥（nsec 或 hex）——唯一的机密 |
| `BUZZ_CHANNELS` | — | 要监听的频道 UUID，逗号分隔（默认：所有已加入的频道） |
| `BUZZ_HOME_CHANNEL` | — | 用于 cron / 通知投递的频道 UUID（默认为第一个被监听的频道） |
| `BUZZ_ALLOWED_USERS` | — | 允许与 agent 对话的 npub 或 hex 公钥，逗号分隔 |
| `BUZZ_ALLOW_ALL_USERS` | — | 允许任何社区成员与 agent 对话 |
| `BUZZ_POLL_INTERVAL` | — | 入站轮询间隔秒数（默认：4） |
| `BUZZ_CLI_PATH` | — | `buzz` 二进制的路径（默认：PATH 中的 `buzz`，其次 `~/bin/buzz`） |
| `BUZZ_CREDENTIALS_FILE` | — | 存放 nsec 的 JSON 凭据文件，在未设置 `BUZZ_PRIVATE_KEY` 时使用 |

## 推荐的默认设置 {#recommended-default-settings}

接入 Buzz 时，请在 `config.yaml` 中设置以下默认值，让频道保持整洁，让 agent 聚焦于最终结果，而不是其内部工具执行日志。这与 Telegram 和电子邮件上的行为一致，它们已经会隐藏中间工具输出。

```yaml
display:
  platforms:
    buzz:
      interim_assistant_messages: false   # 隐藏中间工具结果、推理注释和进度更新——只有最终回复会进入频道
      tool_progress: off                  # 隐藏工具进度气泡（例如 "Running terminal command..."、"Reading file..."）
gateway:
  platforms:
    buzz:
      enabled: true
      extra:
        relay_url: https://mycommunity.communities.buzz.xyz
        attachment_hosts: []         # 入站文件额外允许的精确 HTTPS host[:port] 源
        channels:                         # 要监听的频道 UUID（留空 = 所有已加入频道）
          - ccc2bc1a-7a82-5a8f-8c4e-57a070cbe7cd
        home_channel: ccc2bc1a-7a82-5a8f-8c4e-57a070cbe7cd
        poll_interval: 4                  # 入站轮询间隔秒数（默认 4——在延迟与中继负载之间取得平衡）
        cli_path: ""                      # buzz 二进制（默认：PATH，其次 ~/bin/buzz）
        credentials_file: ""              # 存放 nsec 的 JSON 文件（BUZZ_PRIVATE_KEY 的后备）
        allowed_users: []                 # 若 allow_all_users 为 true，留空 = 允许所有人；否则仅限列出的 npub/hex 公钥
        require_mention: true             # 在频道中：仅在被点名（@name、npub 或 hex 公钥）时回复；私信无论如何都会分派
        allow_all_users: false            # 设为 true 为社区模式（人人可聊，仅所有者是管理员）；false 为私有模式（仅 allowed_users）
```

**为什么选择这些默认值：**

- `interim_assistant_messages: false`——防止中间工具结果、推理注释和进度更新作为单独消息发布到频道。只有最终回复会进入频道。
- `tool_progress: off`——隐藏工具进度气泡（例如 "Running terminal command..."、"Reading file..."）。让频道聚焦于实际结果，而不是过程。
- `poll_interval: 4`——在入站延迟（最多 4 秒）与中继负载之间取得平衡。数值越低轮询越频繁；数值越高轮询越少。
- `allowed_users: []` + `allow_all_users: false`——默认私有模式。只有列出的用户可以交互。设置 `allow_all_users: true` 即为社区模式，人人都可以聊天（管理员层级仍仅限所有者）。
- `require_mention: true`——在频道中，agent 仅在被点名时回复。私信无论此设置如何都会分派。

**理由：** 频道用于展示最终结果和对话，而不是 agent 的内部工具执行日志。用户看到的是最终答案，而不是得出答案所经历的步骤。这与 Telegram 和电子邮件上的行为一致，它们已经采用这些默认值。

**例外：** 如果你希望用户看到工具进度（例如针对长时间运行的操作），请设置 `tool_progress: all`——但 `interim_assistant_messages` 仍应为 `false`，以免每个工具结果都刷屏。

## 提及、频道与私信 {#mentions-channels-and-dms}

- 在共享频道中，agent 仅在被**点名**时回复——通过 `@name`、它的 npub 或它的 hex 公钥。其他一切都会被忽略。
- 私信总能到达 agent，无需提及。
- agent 自己的消息永远不会被分派回给它（按公钥抑制自回声），并且每个事件都会按事件 id、对照每个频道的高水位标记进行去重。

## 回复线程 {#reply-threading}

回复默认以线程形式呈现：agent 的回答（以及任何已启用的进度/状态消息）会锚定到触发它的消息上。锚定遵循 NIP-10——当触发消息本身已经位于某个线程**之中**时，agent 会回复该线程的*根消息*，因此回答会加入现有线程，而不是在每一轮下面嵌套一个新的单消息子线程。

如果想改为在频道层级平铺发布回复，请设置以下任一项（两者等效；`reply_in_thread` 与 Slack 使用的键名一致）：

```yaml
gateway:
  platforms:
    buzz:
      reply_to_mode: off          # PlatformConfig 级别，与 Discord/Telegram 相同
      extra:
        reply_in_thread: false    # Slack 风格的键名；环境变量：BUZZ_REPLY_IN_THREAD
```

这一退出选项适用于**所有**发送路径——最终回答、流式更新、中间注释、工具进度气泡，以及进程外的 cron 投递（`deliver=buzz`）。

## 访问控制 {#access-control}

默认情况下白名单为空，这意味着只有在 `BUZZ_ALLOW_ALL_USERS=true` 时，每个提及 agent 的社区成员才会得到回复；否则请在 `BUZZ_ALLOWED_USERS`（或 config.yaml 中的 `allowed_users`）中列出 npub 或 hex 公钥来限制访问。社区成员资格本身由中继强制执行——只有成员才能发帖。

白名单同样管控**入站附件**：中继媒体是用 agent 自己的 Buzz 凭据获取的，因此只有 gateway 明确授权的发送者才会触发下载。授权被拒绝、缺失或失败时，消息文本保持不变，也不会发出任何带凭据的请求。

Cron 任务和通知（`deliver=buzz`）会投递到**主频道**——若设置了 `BUZZ_HOME_CHANNEL` 则为它，否则为第一个被监听的频道——即使 cron 在 gateway 进程之外运行也能正常工作。

## 入站附件 {#inbound-attachments}

带有原生 NIP-94 `imeta` 标签的 Buzz 消息可以向 agent 投递图片、音频、视频和文档。Hermes 只有在消息通过自回声、点名和发送者授权检查之后才会下载附件。每个文件必须使用 HTTPS，并声明确切的字节大小和 SHA-256 摘要；重定向、URL 中的凭据、片段、超大负载以及完整性不匹配都会被拒绝。

中继自身的 HTTPS 源会被自动信任。如果某个社区把媒体存放在另一个公开源上，请将其确切的 `host` 或 `host:port` 添加到 `gateway.platforms.buzz.extra` 下的 `attachment_hosts`。非默认端口必须显式列出。需要通过 Buzz CLI 进行认证获取的受保护媒体，不由这条原生公开 URL 路径处理。

## 运行 gateway {#run-the-gateway}

```bash
hermes gateway start
```

用 `hermes gateway status` 检查状态——Buzz 连接状态会在那里报告，仅使用环境变量的配置也不例外。

## 注意事项与限制 {#notes-and-limitations}

- **在 Buzz 会话中，终端工具子进程可以使用 `BUZZ_*` 环境变量**——agent 可以直接调用 `buzz` CLI（例如 `buzz messages send ...`），因为当会话平台为 `buzz`，或进程是 Buzz Desktop 托管的 agent（`BUZZ_MANAGED_AGENT`）时，`BUZZ_PRIVATE_KEY`、`BUZZ_AUTH_TAG`、`BUZZ_RELAY_URL` 以及其他 `BUZZ_*` 变量会传递给终端子进程。同一主机上的非 Buzz 会话、`execute_code` 以及其他非终端派生进程仍然保持隔离。
- **入站是轮询的，而不是流式的。** `buzz` CLI 是请求/响应式的，因此适配器会每隔 `poll_interval` 秒（默认 4）对每个被监听的频道轮询 `buzz messages get`。入站消息预计会有最多一个轮询间隔的延迟。未来的一项优化是 websocket 传输（Buzz 仓库提供了用于真正流式传输的 `buzz-ws-client`）。
- 在（重新）连接时，适配器会根据最新的事件初始化其高水位标记，因此频道历史永远不会被重放给 agent。
- 新的私信会话会被自动发现（每隔几轮轮询）。
- 私钥通过子进程环境变量传给 CLI——它永远不会出现在 argv 或日志中。
