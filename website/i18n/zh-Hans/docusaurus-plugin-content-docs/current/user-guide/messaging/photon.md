---
sidebar_position: 18
---

# Photon iMessage

通过 [Photon][photon] 将 Hermes 连接至 **iMessage**——这是一项托管服务，
负责处理 Apple 线路分配与滥用防护层，因此你无需自行运行
Mac 中继。

免费套餐使用 Photon 的共享 iMessage 线路池——不同收件人
可能看到不同的发送号码，但每个会话本身保持稳定。
付费的 Business 套餐为每位用户提供同一个专属号码；插件
两者都支持，推荐从免费套餐开始。

:::info 免费起步
Photon 的共享线路池是免费的。从 Hermes 发送第一条 iMessage
无需订阅——只需要一个可以绑定到你账户的手机号码。
:::

## 架构

Photon 是一种**长连接**通道，类似 Discord 或 Slack——
**没有 webhook，没有公网 URL，也没有需要管理的签名密钥。**

`spectrum-ts` SDK 会与 Photon 保持一条长期存活的 **gRPC 流**，
双向通信均走这条流。由于该 SDK 仅提供 TypeScript 版本，Hermes 会在一个
受监管的小型 **Node sidecar** 中运行它，并通过回环地址与之通信：

- **入站**——sidecar 消费 SDK 的 `app.messages` gRPC
  流，并通过回环的 `GET /inbound`（NDJSON）将每条消息转发给 Python 适配器。
  适配器会去重并分发给 agent，若流中断会自动重连。
- **出站**——回复通过回环 POST 发送给 sidecar，由它调用
  SDK 上的 `space.send(...)`。

Python 插件会自动启动、监管并关闭该 sidecar。

## 前提条件

- 一个 Photon 账户——在 [app.photon.codes][app] 注册
- PATH 中有 **Node.js 18.17 或更新版本**（`node --version`）
- 一个可以接收 iMessage 的手机号码（用于绑定你的账户）

就这些——无需设置任何公网 URL 或隧道。

## 首次设置

可以运行统一的网关向导并选择 **Photon iMessage**：

```bash
hermes gateway setup
```

……或者直接运行 Photon 的设置流程（向导调用的是同一套流程）：

```bash
# 设备码登录 + 项目 + 用户 + sidecar 依赖，一步到位
hermes photon setup --phone +15551234567
```

设置流程依次为：

1. **设备登录**（`client_id=photon-cli`）——打开
   `https://app.photon.codes/` 进行授权，并保存 bearer token。
2. **查找或创建**你账户下的 `Hermes Agent` 项目。
3. **启用 Spectrum**，读取该项目的 Spectrum id，并轮换
   项目密钥。
4. **注册你的手机号码**为 Spectrum 用户——如果已存在使用该号码的
   用户则跳过，因此重复运行是安全的。
5. **打印分配给你的 iMessage 线路**——即你发短信联系
   agent 时使用的号码。
6. **在插件的 sidecar 目录中运行 `npm install`**。

运行时凭据写入 `~/.hermes/.env`
（`PHOTON_PROJECT_ID` = Spectrum 项目 id，`PHOTON_PROJECT_SECRET`），
与其他所有通道保存 token 的位置相同。管理类元数据
（设备 token、控制台项目 id）保存在 `~/.hermes/auth.json` 的
`credential_pool.photon` / `credential_pool.photon_project` 之下。

## 授权用户

Photon 使用与其他所有 Hermes 通道相同的授权模型。
请选择一种方式：

**私聊配对（默认）。** 当一个未知号码向你的 Photon
线路发送消息时，Hermes 会回复一个配对码。使用以下命令批准：

```bash
hermes pairing approve photon <CODE>
```

使用 `hermes pairing list` 查看待处理的配对码和已批准的用户。

**预先授权指定号码**（在 `~/.hermes/.env` 中）：

```bash
PHOTON_ALLOWED_USERS=+15551234567,+15559876543
```

**开放访问**（仅限开发环境，在 `~/.hermes/.env` 中）：

```bash
PHOTON_ALLOW_ALL_USERS=true
```

设置了 `PHOTON_ALLOWED_USERS` 后，未知发送者会被静默
忽略，而不会收到配对码（允许列表表明你是
有意限制访问的）。

### 在群聊中要求提及

默认情况下，Hermes 会响应每一条已授权的私聊和群聊消息。
若要让群聊改为按需触发，请启用提及门控（私聊仍然
始终有效）：

```yaml
gateway:
  platforms:
    photon:
      enabled: true
      require_mention: true
```

设置 `require_mention: true` 后，群聊消息除非匹配到唤醒词模式，
否则会被忽略。默认模式匹配 `Hermes` 和
`@Hermes agent` 等变体。若使用自定义 agent 名称，请设置正则模式：

```yaml
gateway:
  platforms:
    photon:
      require_mention: true
      mention_patterns:
        - '(?<![\w@])@?amos\b[,:\-]?'
```

这两个键也支持环境变量（`PHOTON_REQUIRE_MENTION`、
`PHOTON_MENTION_PATTERNS`）。这与 BlueBubbles iMessage 通道
所用的提及门控模型相同。

## 启动网关

```bash
hermes gateway start
```

你会看到类似这样的输出：

```
[photon] connected — sidecar on 127.0.0.1:8789, streaming inbound over gRPC
```

向分配给你的号码发送一条 iMessage，Hermes 就会回复。

## 状态与故障排查

```bash
hermes photon status
```

会打印已保存的凭据、sidecar 健康状况、你注册的号码，以及
Hermes 使用的已分配 iMessage 线路。当 Photon token 与控制台项目
均可用时，`status` 会从控制台刷新缺失的号码行，
而不会新开线路。

```
Photon iMessage status
──────────────────────
  device token        : ✓ stored
  dashboard project   : 3c90c3cc-0d44-4b50-...
  spectrum project id : sp-...
  project secret      : ✓ stored
  my number           : +15551234567
  assigned number     : +16282679185
  node binary         : /usr/bin/node
  sidecar deps        : ✓ installed
```

常见问题：

- **`sidecar deps : ✗ run hermes photon install-sidecar`**——Node 已
  安装，但缺少 `spectrum-ts`。请运行提示中的命令。
- **`device token : ✗ missing`**——运行 `hermes photon setup` 登录。
- **`No iMessage line assigned yet`**——Spectrum 已启用但尚未
  分配线路；请重新运行 `hermes photon setup` 或查看
  [控制台][app]。
- **sidecar 无法启动**——确认 `node --version` 为 18.17+，并且
  `hermes photon install-sidecar` 已无错误完成。

## 当前限制

- **入站附件仅有元数据。** 入站事件携带
  文件名 + MIME 类型；agent 会看到一个标记，但暂时无法读取
  字节内容。SDK 通过 `content.read()` 暴露附件字节，因此这
  属于 sidecar 的后续工作。
- **出站附件已支持。** Hermes 通过 sidecar 的 `/send-attachment`
  端点，使用 spectrum-ts 的 `attachment()` / `voice()` 内容构造器
  发送图片、语音留言、视频和文档。
  说明文字会在媒体之后以单独的 iMessage 气泡送达。
- **Photon 的免费配额：** 每台服务器每天 5,000 条消息，
  每条共享线路每天发起 50 个新会话。可申请提额——
  发送邮件至 `help@photon.codes`。

## 环境变量

| 变量                      | 默认值             | 说明                                       |
|---------------------------|--------------------|--------------------------------------------|
| `PHOTON_PROJECT_ID`       | 来自 `.env`        | Spectrum 项目 id（SDK 的 `projectId`）；由设置流程写入 |
| `PHOTON_PROJECT_SECRET`   | 来自 `.env`        | 项目密钥；由设置流程写入                   |
| `PHOTON_SIDECAR_PORT`     | `8789`             | sidecar 控制与入站通道使用的回环端口       |
| `PHOTON_SIDECAR_AUTOSTART`| `true`             | 适配器是否负责拉起 sidecar                 |
| `PHOTON_NODE_BIN`         | `which node`       | 覆盖 Node 可执行文件路径                   |
| `PHOTON_HOME_CHANNEL`     | （未设置）         | 用于 cron / 通知的默认 space id            |
| `PHOTON_HOME_CHANNEL_NAME`| （未设置）         | 主频道的可读名称                           |
| `PHOTON_ALLOWED_USERS`    | （未设置）         | 逗号分隔的 E.164 允许列表                  |
| `PHOTON_ALLOW_ALL_USERS`  | `false`            | 仅限开发——接受任意发送者                  |
| `PHOTON_REQUIRE_MENTION`  | `false`            | 在群聊中响应前要求唤醒词                   |
| `PHOTON_MENTION_PATTERNS` | Hermes 唤醒词      | 群聊提及的正则模式，支持 JSON 列表 / 逗号 / 换行分隔 |
| `PHOTON_DASHBOARD_HOST`   | `app.photon.codes` | 覆盖控制台 / 设备登录主机                  |
| `PHOTON_SPECTRUM_HOST`    | `spectrum.photon.codes` | 覆盖 Spectrum API 主机                |

[photon]: https://photon.codes/
[app]: https://app.photon.codes/
