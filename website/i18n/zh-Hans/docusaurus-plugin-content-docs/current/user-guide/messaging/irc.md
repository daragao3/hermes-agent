---
sidebar_position: 20
title: "IRC"
description: "使用零依赖的 IRC gateway 适配器，把 Hermes 连接到任意 IRC 服务器或网络。"
---

# IRC

IRC 适配器将 Hermes 连接到任意 IRC 服务器，并在 IRC 频道（或私聊）与 agent 之间转发消息。它基于 Python 标准库 `asyncio` 直接实现 IRC 协议——**无外部依赖、无 SDK、无守护进程**。它可用于 [Libera.Chat](https://libera.chat/) 等公共网络，也可用于任何自建 ircd。

IRC 是纯文本协议：不支持语音、图片、文件、线程、表情回应、正在输入提示或流式输出——回复以 `PRIVMSG` 行发送，过长的消息会被切分以符合 IRC 行长度限制。

> 运行 `hermes gateway setup` 并选择 **IRC**，即可获得引导式配置流程。

## 前提条件

- 一个可连接的 IRC 服务器（例如 `irc.libera.chat`）
- 一个要加入的频道（例如 `#hermes`）——用逗号分隔可加入多个
- 机器人的昵称（默认：`hermes-bot`）
- 可选：如果你的网络要求身份认证，需要已注册的昵称 + NickServ 密码

## 配置 Hermes

配置 IRC 有两种方式——环境变量（适合快速的纯 env 配置）或 `~/.hermes/gateway-config.yaml` 中的 `gateway` 块。

### 方式 A —— gateway-config.yaml

```yaml
gateway:
  platforms:
    irc:
      enabled: true
      extra:
        server: irc.libera.chat
        port: 6697
        nickname: hermes-bot
        channel: "#hermes"
        use_tls: true
        server_password: ""       # optional server password
        nickserv_password: ""     # optional NickServ identification
        allowed_users: []         # empty = allow all, or list of nicks
        max_message_length: 450   # IRC line limit (safe default)
```

### 方式 B —— 环境变量

| 变量 | 必填 | 说明 |
|----------|:--------:|-------------|
| `IRC_SERVER` | ✅ | IRC 服务器主机名（例如 `irc.libera.chat`） |
| `IRC_CHANNEL` | ✅ | 要加入的频道——多个频道用逗号分隔 |
| `IRC_NICKNAME` | ✅ | 机器人昵称（默认：`hermes-bot`） |
| `IRC_PORT` | —— | 服务器端口（默认：启用 TLS 时为 `6697`，否则为 `6667`） |
| `IRC_USE_TLS` | —— | 是否使用 TLS（`true`/`false`；端口 6697 上默认为 `true`） |
| `IRC_SERVER_PASSWORD` | —— | 用于 `PASS` 命令的服务器密码 |
| `IRC_NICKSERV_PASSWORD` | —— | 连接时自动 IDENTIFY 所用的 NickServ 密码 |
| `IRC_ALLOWED_USERS` | —— | 允许与机器人对话的昵称，逗号分隔 |
| `IRC_ALLOW_ALL_USERS` | —— | 允许频道内任何人与机器人对话（仅限开发环境） |
| `IRC_HOME_CHANNEL` | —— | 用于 cron / 通知投递的频道（默认为 `IRC_CHANNEL`） |

## 访问控制

默认情况下，只有列在 `allowed_users`（或 `IRC_ALLOWED_USERS`）中的昵称才能与机器人对话。将该列表留空**并且**设置 `IRC_ALLOW_ALL_USERS=true`，即可让频道中的任何人与 Hermes 聊天——这在测试时很有用，但不建议在公共网络上使用，因为除非网络强制启用 NickServ，否则 IRC 昵称并不经过认证。

如果你的网络支持昵称注册，请设置 `IRC_NICKSERV_PASSWORD`（或 `nickserv_password`），这样机器人在连接时会向 NickServ 认证并保住其已注册的昵称。

## 频道 vs. 私聊

- 已加入频道中的消息被视为**群组**会话。
- 发给机器人的私聊消息被视为**私信**。

Cron 任务和通知会投递到**主频道**——如果设置了 `IRC_HOME_CHANNEL` 则使用它，否则使用 `IRC_CHANNEL` 中的第一个频道。

## 运行 gateway

```bash
hermes gateway start
```

用 `hermes gateway status` 查看状态——IRC 连接状态会在其中报告，纯 env 配置的场景同样适用。

## 注意事项

- 过长的 agent 回复会自动切分为多条 `PRIVMSG` 行，以符合 IRC 行长度限制（`max_message_length`，扣除协议开销后默认为 450 字节）。
- 适配器会按 服务器+昵称 获取一个作用域凭证锁，因此两个 Hermes profile 不会争抢同一个 IRC 身份。
