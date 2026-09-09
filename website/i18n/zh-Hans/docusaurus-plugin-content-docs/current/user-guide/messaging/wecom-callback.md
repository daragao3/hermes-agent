---
sidebar_position: 15
---

# WeCom 回调（自建应用）

通过回调/webhook 模式，将 Hermes 作为企业自建应用接入企业微信（WeCom）。

:::info WeCom Bot 与 WeCom 回调
Hermes 支持两种企业微信集成模式：
- **[WeCom Bot](wecom.md)** — Bot 风格，通过 WebSocket 连接。配置简单，支持群聊。
- **WeCom 回调**（本页）— 自建应用，接收加密 XML 回调。在用户企业微信侧边栏中显示为一级应用，支持多企业路由。
:::

另请参阅：[WeCom Bot](./wecom.md) 了解 Bot 风格的集成方式。

> 运行 `hermes gateway setup` 并选择 **WeCom Callback**，即可获得引导式配置流程。

## 工作原理

1. 在企业微信管理后台注册自建应用
2. 企业微信将加密 XML 推送至你的 HTTP 回调端点
3. Hermes 解密消息，将其加入 agent 处理队列
4. 立即确认（静默——不向用户显示任何内容）
5. Agent 处理请求（通常需要 3–30 分钟）
6. 通过企业微信 `message/send` API 主动下发回复

## 前置条件

- 具有管理员权限的企业微信账号
- `aiohttp` 和 `httpx` Python 包（默认安装已包含）
- 可公网访问的服务器用于回调 URL（或使用 ngrok 等隧道工具）

## 配置步骤

### 1. 在企业微信中创建自建应用

1. 进入[企业微信管理后台](https://work.weixin.qq.com/) → **应用管理** → **创建应用**
2. 记录你的 **Corp ID**（显示在管理后台顶部）
3. 在应用设置中创建 **Corp Secret**
4. 在应用概览页记录 **Agent ID**
5. 在**接收消息**下配置回调 URL：
   - URL：`http://YOUR_PUBLIC_IP:8645/wecom/callback`
   - Token：生成一个随机 token（企业微信会提供）
   - EncodingAESKey：生成一个密钥（企业微信会提供）

### 2. 配置环境变量

在 `.env` 文件中添加：

```bash
WECOM_CALLBACK_CORP_ID=your-corp-id
WECOM_CALLBACK_CORP_SECRET=your-corp-secret
WECOM_CALLBACK_AGENT_ID=1000002
WECOM_CALLBACK_TOKEN=your-callback-token
WECOM_CALLBACK_ENCODING_AES_KEY=your-43-char-aes-key

# 可选
WECOM_CALLBACK_HOST=0.0.0.0
WECOM_CALLBACK_PORT=8645
WECOM_CALLBACK_ALLOWED_USERS=user1,user2
```

### 3. 启动 Gateway

```bash
hermes gateway
```

（仅在通过 `hermes gateway install` 注册 systemd/launchd 服务后，才使用 `hermes gateway start`。）

回调适配器会在配置的端口上启动 HTTP 服务器。企业微信将通过 GET 请求验证回调 URL，随后开始通过 POST 发送消息。

## 配置参考

在 `config.yaml` 的 `platforms.wecom_callback.extra` 下设置，或使用环境变量：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `corp_id` | — | 企业微信 Corp ID（必填） |
| `corp_secret` | — | 自建应用的 Corp Secret（必填） |
| `agent_id` | — | 自建应用的 Agent ID（必填） |
| `token` | — | 回调验证 token（必填） |
| `encoding_aes_key` | — | 43 字符的 AES 密钥，用于回调加密（必填） |
| `host` | `0.0.0.0` | HTTP 回调服务器绑定地址 |
| `port` | `8645` | HTTP 回调服务器端口 |
| `path` | `/wecom/callback` | 回调端点的 URL 路径 |

## 多应用路由

对于运行多个自建应用的企业（例如跨部门或子公司），在 `config.yaml` 中配置 `apps` 列表：

```yaml
platforms:
  wecom_callback:
    enabled: true
    extra:
      host: "0.0.0.0"
      port: 8645
      apps:
        - name: "dept-a"
          corp_id: "ww_corp_a"
          corp_secret: "secret-a"
          agent_id: "1000002"
          token: "token-a"
          encoding_aes_key: "key-a-43-chars..."
        - name: "dept-b"
          corp_id: "ww_corp_b"
          corp_secret: "secret-b"
          agent_id: "1000003"
          token: "token-b"
          encoding_aes_key: "key-b-43-chars..."
```

用户以 `corp_id:user_id` 为作用域，防止跨企业冲突。当用户发送消息时，适配器会记录其所属应用（企业），并通过对应应用的 access token 路由回复。

## 访问控制

限制哪些用户可以与应用交互：

```bash
# 白名单指定用户
WECOM_CALLBACK_ALLOWED_USERS=zhangsan,lisi,wangwu

# 或允许所有用户
WECOM_CALLBACK_ALLOW_ALL_USERS=true
```

## 端点

适配器暴露以下端点：

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/wecom/callback` | URL 验证握手（企业微信在配置时发送） |
| POST | `/wecom/callback` | 加密消息回调（企业微信将用户消息发送至此） |
| GET | `/health` | 健康检查——返回 `{"status": "ok"}` |

## 加密

所有回调载荷均使用 EncodingAESKey 通过 AES-CBC 加密。适配器处理：

- **入站**：解密 XML 载荷，验证 SHA1 签名
- **出站**：通过主动调用 API 发送回复（非加密回调响应）

加密实现与腾讯官方 WXBizMsgCrypt SDK 兼容。

## 限制

- **不支持流式输出** — 回复在 agent 完成处理后以完整消息形式送达
- **不支持正在输入提示** — 回调模式不支持输入状态
- **仅支持文本** — 目前仅支持文本消息输入；图片/文件/语音输入尚未实现。Agent 可通过企业微信平台提示感知出站媒体能力（图片、文档、视频、语音）。
- **响应延迟** — Agent 会话需要 3–30 分钟；用户在处理完成后收到回复

## 故障排查

**签名验证失败。**
企业微信会用你在管理后台注册的 **Token** 对每个请求签名。Hermes 中配置的
token 与管理后台期望的 token 不一致是最常见的原因。请重新从管理后台复制
**Token** 和 **EncodingAESKey**——它们很容易被截断。`~/.hermes/.env` 中
`=` 两侧的空白字符同样会破坏签名校验。修复后请重启 `hermes gateway run`。

**回调 URL 不可达 / 验证步骤失败。**
企业微信会访问你注册的公网 URL。请确认：
1. 你的反向代理／隧道已将 `/wecom/callback` 转发到 gateway 的端口。
2. 管理后台中的 URL 是 HTTPS（企业微信拒绝纯 HTTP）。
3. 从你的网络外部执行 `curl -i https://<your-domain>/wecom/callback`
   返回的不是超时（不带查询参数时返回 4xx 也没问题——这只说明监听器可达）。

**端口不可达 / 监听器未绑定。**
检查 `hermes gateway run` 日志中绑定的 host/port。如果适配器绑定到了
`127.0.0.1`，你必须在前面加一层反向代理或隧道——企业微信的服务器无法访问
回环地址。请在 `config.yaml` 中设置 `extra.host: 0.0.0.0`（如果直接暴露，
还需设置 `allowed_source_cidrs`），或者保持回环地址并使用
Cloudflare Tunnel / nginx 之类的隧道。
