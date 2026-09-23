---
sidebar_position: 30
title: "Hermes Relay"
description: "通过一个持有平台凭据的 relay 连接器将 Hermes 接入消息平台——注册、能力、配置与故障排查"
---

# Hermes Relay（连接器）

:::warning 实验性功能
Relay 目前是**实验性**功能。在系统验证期间，线路协议、认证方案和配置
可能会在没有弃用周期的情况下发生变化。
:::

Hermes Relay 本身并不是一个聊天平台——它是一个**连接器系统**，
让你的网关可以对接一个或多个真实的消息平台（Discord、
Telegram、Slack、WhatsApp……），而**无需持有任何平台凭据**。一个
独立的服务，即*连接器*（connector），持有平台的 bot token 和套接字。
你的网关通过单条经过认证的 WebSocket **主动向外**连接到连接器，在握手时收到一份能力描述符，
随后通过该套接字交换规范化的消息事件（入站）和动作（出站）。

关键特性：

- **仅出站网络。** 网关从不开放入站端口。
  入站消息沿着网关自己拨出的同一条 WebSocket 回传，因此
  relay 可以在 NAT 之后以及没有公网 IP 的主机上工作。
- **网关上没有平台密钥。** Bot token 保存在连接器上。
  需要认证的平台媒体 URL 会在连接器侧重新托管，因此平台
  凭据永远不会经过线路传输。
- **与平台无关。** 网关通过握手描述符了解所对接的平台能做什么
  （消息长度限制、markdown 方言、编辑/线程/流式支持，以及
  所支持操作的确切集合），而不是依赖硬编码的平台逻辑。

正式的网关 ⇄ 连接器接口定义位于仓库中的
`docs/relay-connector-contract.md`。

## 何时使用 Relay {#when-to-use-relay}

Relay 适用于由托管或共享的连接器服务管理平台侧的部署——
例如多租户托管场景，一个共享 bot 为许多用户的 agent 提供前端；
或者你不希望 bot token 出现在网关机器上的部署。如果你直接运行自己的 bot，
请改用原生平台适配器（[Telegram](/user-guide/messaging/telegram)、
[Discord](/user-guide/messaging/discord) 等）。

## 注册 {#enrollment}

自托管的网关使用每个网关独有的密钥向连接器进行认证。
`hermes gateway enroll` 会用一个**一次性注册 token**
（由连接器在为你的租户开通路由时签发，并随你的网关配置一同交付）
兑换该密钥：

```bash
hermes gateway enroll \
  --token <enrollment-token> \
  --connector-url wss://connector.example.com/relay
```

它会执行以下操作：

1. 从你现有的登录状态（`~/.hermes/auth.json`）解析出一个新的 Nous Portal 访问 token
   ——这用于证明你拥有哪个 Nous 组织（租户）。如果
   配置了 `gateway.idp.token_url`，则改用你自己的 IdP（即
   气隙隔离 / 自托管 IdP 路径，完全不涉及 Nous Portal）：若
   配置了 `client_id`/`client_secret`，它会执行通用的 OAuth2
   client-credentials 授权；若两者都未配置，该 URL 会被视为一个
   环境 token 端点（一个普通 GET 请求，其响应体就是 token——即
   元数据服务器模式，例如 Domino 的 `$DOMINO_API_PROXY/access-token`）。
   只配置两个凭据中的一个会报错。
2. 通过 TLS 将注册 token 和网关 id POST 到连接器的
   `/relay/enroll` 端点。
3. 连接器校验该 token（签名、一次性、租户匹配），
   签发一个每网关密钥和一个每租户投递密钥，并仅返回一次。
4. 将凭据持久化到 `~/.hermes/.env`：
   `GATEWAY_RELAY_ID`、`GATEWAY_RELAY_SECRET`、`GATEWAY_RELAY_DELIVERY_KEY`
   （提供时还包括 `GATEWAY_RELAY_URL` / `GATEWAY_RELAY_WAKE_URL`）。

之后重启网关，以加载新的环境变量。

参数：

| 参数 | 说明 |
|------|-------------|
| `--token` | 一次性注册 token。也可通过 `GATEWAY_RELAY_ENROLL_TOKEN` 设置。 |
| `--connector-url` | 连接器的基础 URL 或 relay URL（`wss://…/relay` 或 `https://…`）。也可通过 `GATEWAY_RELAY_URL` 或 `config.yaml` 中的 `gateway.relay_url` 设置。 |
| `--gateway-id` | 此网关实例的稳定 id（用于紧急停用开关的粒度控制）。默认为 `gw-<hostname>`。 |
| `--wake-url` | 可选的可达 URL，当网关空闲时有缓冲的工作到达，连接器会访问它（无负载的 GET）来唤醒此网关。持久化为 `GATEWAY_RELAY_WAKE_URL`。没有它时，网关仍会在下次重连时取出缓冲的消息。 |

:::note 托管安装
`hermes gateway enroll` 在托管/受管安装中会拒绝运行——在那里，
托管平台会直接把 relay 密钥注入容器环境。
:::

## 配置 {#configuration}

只要配置了连接器 relay URL，Relay 就会启用——没有
单独的功能开关。未设置它的部署不受影响。

| 设置 | 位置 | 含义 |
|---------|-------|---------|
| `GATEWAY_RELAY_URL` | 环境变量（`~/.hermes/.env`） | 连接器 relay 的 WebSocket URL。存在即启用 relay 平台。 |
| `gateway.relay_url` | `config.yaml` | 同上，配置文件形式（环境变量优先）。 |
| `GATEWAY_RELAY_ID` | 环境变量 | 此网关实例的 id（由 `enroll` 写入）。 |
| `GATEWAY_RELAY_SECRET` | 环境变量 | 用于认证 WebSocket 升级请求的每网关密钥（由 `enroll` 写入）。 |
| `GATEWAY_RELAY_DELIVERY_KEY` | 环境变量 | 每租户投递密钥（由 `enroll` 写入；为向前兼容而保留）。 |
| `GATEWAY_RELAY_WAKE_URL` / `gateway.relay_wake_url` | 环境变量 / `config.yaml` | 可选的唤醒目标，用于空闲/挂起的网关。 |
| `GATEWAY_RELAY_PLATFORMS` | 环境变量 | 以逗号分隔的平台列表，此网关通过一条连接对接这些平台（例如 `discord,telegram`）。通常由部署/编排器写入。 |
| `GATEWAY_RELAY_BOT_IDS` | 环境变量 | 各平台 bot 身份的 JSON 映射，例如 `{"discord": {"botId": "…"}}`。与 `GATEWAY_RELAY_PLATFORMS` 配对使用。 |
| `gateway.idp.token_url` | `config.yaml` | 设置后，注册/开通会改为向你自己的 IdP 认证，而不是 Nous Portal：若同时设置了 `gateway.idp.client_id`/`client_secret`，则使用 OAuth2 client-credentials；否则视为环境 token 端点（普通 GET，返回原始 token 或 `{"access_token": …}`）。 |

## 支持的能力 {#supported-capabilities}

通过 relay 连接实际能用哪些功能，是在握手时协商的：
连接器会公布一个 `supported_ops` 列表，网关只会使用连接器明确公布的
操作（较旧的连接器会回退到旧版的
`send`/`edit`/`typing`/`follow_up` 集合）。各平台的能力标志
（基于编辑的流式输出、线程、草稿流式、markdown 方言、消息
长度限制）同样来自握手描述符。在该协商的前提下，relay 支持：

- **文本消息与流式输出**——发送、回复，以及在所对接平台支持编辑消息时
  基于编辑的渐进式流式输出；否则输出会降级为每个片段一条消息。
- **双向媒体**——出站的图片、语音、音频、视频和
  文档会上传到连接器（或通过公开 URL 引用），并
  通过各平台原生的上传通道连同说明文字一起投递。
  入站附件会被本地化为文件供 agent 使用；需要认证的
  平台 URL 会在连接器侧重新托管，因此平台凭据永远不会
  到达网关。重新托管的媒体上限为 25 MB，并会过期（约 1 小时）。
- **原生交互式提示**——执行审批、确认和澄清
  问题会以**平台原生控件**呈现（Discord 按钮、
  Telegram 内联键盘、Slack Block Kit 动作、WhatsApp 按钮/列表
  消息），而不是回退为编号文本。按钮点击会作为来自
  实际点击用户的已认证提示响应返回，因此网关的授权关卡
  与对待键入回复时完全一致地生效。提示的过期由网关侧强制执行。
- **表情回应确认生命周期**——bot 表示处理状态的表情回应
  （处理中为 👀，完成时为 ✅/❌）可以通过 relay 工作。表情回应是
  尽力而为的：表情回应失败永远不会导致一轮对话失败。
- **线程生命周期**——通过与平台无关的
  `thread_create` / `thread_rename` 操作创建交接线程和重命名线程
  （包括由 LLM 生成标题的语义化重命名），并带有防覆盖保护，确保
  人工手动重命名优先。是否可用取决于平台（例如
  Slack 线程无法重命名；WhatsApp 没有线程）。
- **输入状态指示**——网关在处理期间通过连接器
  发出"正在输入"（及停止输入）状态。
- **聊天元数据**——在连接器公布该能力时，`get_chat_info` 查询会被代理到
  连接器。
- **缓冲投递与唤醒**——当网关空闲或断开连接时，
  连接器会持久地缓冲入站消息，并在重连时按顺序重放
  （以确认为准，不丢失也不重复）。如果注册了唤醒 URL，
  当有缓冲的工作到达一个处于休眠的网关时，连接器会访问该 URL。

支持多平台对接：一个网关可以通过单条 relay 连接对接多个平台
（例如 Discord *和* Telegram），每条出站消息都会标记其目标平台。

## 故障排查 {#troubleshooting}

**注册失败并返回 401**——连接器无法验证你的身份
token。使用 `hermes auth add nous`（或 `hermes setup`）重新登录后重试。

**注册失败并返回 403**——注册 token 无效、已过期、
已被使用，或属于另一个租户。注册 token 是
一次性的；请向为你开通租户路由的人申请一个新的。

**"Could not reach the connector"**——检查连接器 URL。你既可以粘贴
`wss://…/relay` 拨号 URL，也可以粘贴 `https://…` 基础 URL；CLI 会自动
在两者之间转换。

**`enroll` 拒绝运行**——你处于托管/受管安装中，那里的
relay 密钥由托管平台开通。自助注册仅适用于
自托管的网关。

**Relay 平台之前能用，之后显示为已禁用**——在握手成功*之后*
以代码 4401 关闭 WebSocket，意味着网关的密钥
已被吊销（例如该实例已被注销）。网关会有意
停止重连并报告 relay 已禁用，而不是继续重试。在任何握手成功*之前*
出现的 4401 会被视为暂时性的"尚未开通"竞态，并按正常方式重试。

**注册之后没有任何变化**——网关在启动时读取 `GATEWAY_RELAY_*`。
重启它（`hermes gateway restart`）。

**某个功能（按钮、媒体、线程……）悄悄降级为纯文本**——你所用平台的
连接器没有在握手的 `supported_ops` 中公布该操作。
网关会有意回退到文本行为，而不是发送一个连接器无法处理的操作。
