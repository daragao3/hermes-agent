# SimpleX Chat

[SimpleX Chat](https://simplex.chat/) 是一个私密的去中心化即时通讯平台，用户完全掌控自己的联系人和群组。与其他平台不同，SimpleX 不分配任何持久用户 ID——每个联系人在建立连接时由系统生成一个不透明的内部 ID，这使其成为目前隐私性最强的即时通讯工具之一。

## 前提条件

- 已安装并以守护进程方式运行的 **simplex-chat** CLI
- Python 包 **websockets**（`pip install websockets`）

## 安装 simplex-chat

从 [simplex-chat GitHub releases](https://github.com/simplex-chat/simplex-chat/releases) 页面下载最新版本：

```bash
# Linux / macOS binary
curl -L https://github.com/simplex-chat/simplex-chat/releases/latest/download/simplex-chat-ubuntu-22_04-x86_64 -o simplex-chat
chmod +x simplex-chat
```

SimpleX Chat 项目未发布聊天客户端的预构建 Docker 镜像；如需在 Docker 下运行，请从 [simplex-chat 仓库](https://github.com/simplex-chat/simplex-chat) 源码构建。

## 启动守护进程

```bash
simplex-chat -p 5225
```

守护进程默认在 `ws://127.0.0.1:5225` 上监听 WebSocket 连接。

## 配置 Hermes

### 通过设置向导

```bash
hermes gateway setup
```

选择 **SimpleX Chat** 并按提示操作。

### 通过环境变量

将以下内容添加到 `~/.hermes/.env`：

```
SIMPLEX_WS_URL=ws://127.0.0.1:5225
SIMPLEX_ALLOWED_USERS=<contact-id-1>,<contact-id-2>
SIMPLEX_HOME_CHANNEL=<contact-id>
```

| 变量 | 是否必填 | 说明 |
|---|---|---|
| `SIMPLEX_WS_URL` | 是 | simplex-chat 守护进程的 WebSocket URL |
| `SIMPLEX_ALLOWED_USERS` | 建议填写 | 以逗号分隔的允许列表。每个条目可以是数字 `contactId`**或**显示名称——两种形式均可。 |
| `SIMPLEX_ALLOW_ALL_USERS` | 可选 | 设为 `true` 以允许所有联系人（请谨慎使用） |
| `SIMPLEX_AUTO_ACCEPT` | 可选 | 自动接受传入的联系人请求（默认：`true`） |
| `SIMPLEX_GROUP_ALLOWED` | 可选 | 以逗号分隔的、Bot 参与的群组 ID，或用 `*` 表示任意群组。省略则完全忽略群组消息 |
| `SIMPLEX_HOME_CHANNEL` | 可选 | cron 任务投递的默认联系人/群组 ID |
| `SIMPLEX_HOME_CHANNEL_NAME` | 可选 | 主频道的可读标签 |
| `HERMES_SIMPLEX_TEXT_BATCH_DELAY` | 可选 | 静默期秒数（默认：`0.8`），用于把快速连发的入站文本消息拼接为一个事件 |

## 查找联系人 ID 或显示名称

启动守护进程后，与你的 Agent 联系人开启一段对话。数字形式的 `contactId` 会出现在会话日志中。如果你更愿意使用 SimpleX 界面中显示的名称，也同样可行——`SIMPLEX_ALLOWED_USERS` 接受两种形式。

## 授权

默认情况下**所有联系人均被拒绝访问**。你必须选择以下方式之一：

1. 将 `SIMPLEX_ALLOWED_USERS` 设置为以逗号分隔的 `contactId` 和/或显示名称列表（例如 `SIMPLEX_ALLOWED_USERS=4,alice` 会匹配 contactId 为 4 的联系人，或显示名称为 "alice" 的联系人），或
2. 使用 **DM 配对**——向 Bot 发送任意消息，Bot 将回复一个配对码。通过 `hermes pairing approve simplex <CODE>` 输入该配对码。

## 群聊

默认情况下适配器会忽略群组消息——否则群里的 Bot
会处理每个成员的全部流量。请显式选择加入：

```
SIMPLEX_GROUP_ALLOWED=12,34          # specific group IDs
# or
SIMPLEX_GROUP_ALLOWED=*              # any group the bot is in
```

给群组寻址时，在聊天 ID 前加上 `group:` 前缀，例如
在 cron 的 `deliver=` 目标中或 `hermes send` 调用中使用 `simplex:group:12`。

## 附件

适配器在两个方向上都支持 SimpleX 原生附件：

- **入站**——传入的图片、语音消息和文件通过守护进程的
  XFTP 流程（`rcvFileDescrReady` → `/freceive` → 等待
  `rcvFileComplete`）被接收，并以对应的 `MessageType`
  （`PHOTO`、`VOICE`、`TEXT` + 文档）呈现为 `MessageEvent.media_urls`。
- **出站**——`send_image_file`、`send_voice`、`send_document` 和
  `send_video` 都使用带 `filePath` 的结构化 `/_send` 形式，因此
  接收方的 SimpleX 客户端会内联渲染图片、内联播放语音消息，
  而不是把它们当作下载项提供。

Agent 的回复还可以在纯文本中嵌入 `MEDIA:/path/to/file` 标记——
适配器会从正文中剥离该标记，并按语音消息（音频扩展名）或文档的形式发送该文件。

## 在 cron 任务中使用 SimpleX

```python
cronjob(
    action="create",
    schedule="every 1h",
    deliver="simplex",          # uses SIMPLEX_HOME_CHANNEL
    prompt="Check for alerts and summarise."
)
```

或者通过 cron 任务的 `deliver:` 字段指定特定联系人，也可以在 shell 脚本中使用 [`hermes send` CLI](/guides/pipe-script-output)：

```bash
hermes send simplex:<contact-id> "Done!"
```

## 隐私说明

- SimpleX 从不暴露手机号或电子邮件地址——联系人使用不透明 ID 标识
- Hermes 与守护进程之间的连接为本地 WebSocket（`ws://127.0.0.1:5225`）——数据不会离开你的机器
- 消息在到达守护进程之前已由 SimpleX 协议进行端到端加密

## 故障排查

**"Cannot reach daemon"** — 确保 `simplex-chat -p 5225` 正在运行，且端口与 `SIMPLEX_WS_URL` 一致。

**"websockets not installed"** — 运行 `pip install websockets`。

**消息未收到** — 检查该联系人的 ID 是否已加入 `SIMPLEX_ALLOWED_USERS`，或通过 DM 配对方式批准该联系人。