---
sidebar_position: 6
title: "WhatsApp Business（Cloud API）"
description: "通过 Meta 官方 Business Cloud API 将 Hermes Agent 配置为 WhatsApp 机器人"
---

# WhatsApp Business Cloud API 配置

Hermes 可以通过 Meta **官方**的 WhatsApp Business Cloud API 连接 WhatsApp。这是生产级方案：没有 Node.js 桥接子进程，没有二维码，也没有账号封禁风险。

相应地：

- 你需要一个 **Meta Business 账号**（不是个人 WhatsApp）。
- 机器人运行在专用的商业手机号上，而不是你的个人号码。
- Hermes 网关需要一个**公网 HTTPS URL**，以便 Meta 通过 webhook 投递入站消息。
- 在用户最后一条消息之后超过 24 小时的回复需要使用预先审核通过的**模板**（这是 Meta 的“客服窗口”规则，而非 Hermes 的限制）。

如果这些约束不适合你的使用场景，[Baileys 桥接集成](./whatsapp.md)是备选方案——使用个人账号，无需公网 URL，但属于非官方方式且容易被封号。

:::tip 我该用哪一个？
- **Cloud API（本指南）** —— 运行真正的商业机器人、追求稳定性、能接受 Meta 的验证 + 模板审核流程
- **[Baileys 桥接](./whatsapp.md)** —— 个人项目、快速演示、单用户场景，愿意承担机器人手机号被封的风险
:::

---

## 快速开始

```bash
hermes whatsapp-cloud
```

该向导会带你走完每一项凭据的配置，在你粘贴时逐项校验（可以捕获排名第一的配置陷阱——把手机号粘贴到 Phone Number ID 字段），并针对需要在向导之外完成的部分（启动 cloudflared、配置 Meta 的 webhook 仪表板）打印精确的后续说明。

本页余下内容是手动配置参考。

---

## 前提条件

1. **一个 Meta Business 账号**。在 [business.facebook.com](https://business.facebook.com/) 创建。
2. **一个启用了 WhatsApp 的 Meta 应用**。参见下文“创建 Meta 应用”。
3. **一种将本地端口以 HTTPS 暴露到公网的方式**。推荐使用 Cloudflare Tunnel（`cloudflared`）——免费、无需端口转发、无需域名。ngrok、带反向代理 + TLS 的自有域名，或将网关直接绑定到公网 IP 的 VPS 也都可行。
4. **可选但推荐**：在 `PATH` 上安装 ffmpeg，这样出站语音消息会呈现为 WhatsApp 原生语音条（绿色波形），而不是 MP3 音频附件。若未安装，Hermes 会优雅降级。

---

## 创建 Meta 应用

1. 前往 [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create App**。
2. 选择用例：**“Connect with customers through WhatsApp”** → **Next**。
3. 选择或创建一个商业组合（business portfolio）。查看发布要求。确认 → **Create app**。
4. 创建完成后你会进入 **Customize use case → Connect on WhatsApp → Quickstart**。点击 **Start using the API** → 现在你就到了 **API Setup** 页面。
5. 确保已关联一个 WhatsApp Business Account（WABA）。如果你在第 3 步创建了新的组合，系统会自动创建一个。请在 API Setup 页面确认。

你需要从仪表板中获取以下值——向导会按此顺序提示你输入：

| 值 | 在仪表板中的位置 | 字段形态 | 说明 |
|---|---|---|---|
| **Phone Number ID** | App Dashboard → WhatsApp → API Setup → 位于 "From" 下拉框下方 | 数字，15-17 位 | **不是**手机号本身。排名第一的配置错误就是把真实手机号粘贴到这里。 |
| **Access Token** | App Dashboard → WhatsApp → API Setup → "Generate access token" | 以 `EAA` 开头，100+ 字符 | 临时令牌有效期 24 小时——生产环境请参见下文“永久令牌”。 |
| **App Secret** | App Dashboard → Settings → Basic → 点击 App secret 旁的 "Show" | 32 位小写十六进制 | 用于校验入站 webhook 签名。没有它，入站投递会被拒绝并返回 503。 |
| **App ID**（可选） | App Dashboard → Settings → Basic | 数字，15-16 位 | 消息收发不需要，用于分析统计。 |
| **WABA ID**（可选） | App Dashboard → WhatsApp → API Setup → 靠近页面顶部 | 数字，15+ 位 | 消息收发不需要，用于分析统计。 |

---

## 永久令牌（生产环境）

临时访问令牌会在 **24 小时**后过期，也就是说今天生成的令牌明天就失效了。生产部署请使用 **System User 永久令牌**：

1. 前往 [business.facebook.com/latest/settings](https://business.facebook.com/latest/settings) → **System users**（左侧边栏）。
2. **Add** → 名称（例如 `hermes-bot`）→ 角色：**Admin**。
3. 选中新用户 → **Assign Assets**：
   - 选择你的应用 → 在 Full control 下打开 **Manage app**。
   - 选择你的 WhatsApp 账号 → 在 Full control 下打开 **Manage WhatsApp Business Accounts**。
   - 点击 **Assign assets**。
4. 使用以下权限 **Generate token**：
   - `business_management`
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
5. 将 **token expiration** 设为 **Never**。
6. 复制令牌 → 更新 `~/.hermes/.env` 中的 `WHATSAPP_CLOUD_ACCESS_TOKEN` → 重启网关。

除非你显式吊销，否则 System User 令牌不会过期。

---

## 将 Hermes 暴露到公网

Cloud API 通过 HTTPS POST 把入站消息投递到你的 webhook URL——这意味着 Hermes 网关必须能被 Meta 的服务器访问到。三种常见方式：

### Cloudflare Tunnel（推荐）

免费、无需端口转发，在 Windows / macOS / Linux 上均可用。作为独立进程与网关并行运行。

**安装：**

```bash
# Windows
winget install Cloudflare.cloudflared

# macOS
brew install cloudflared

# Linux
# 从 https://github.com/cloudflare/cloudflared/releases 下载二进制文件
```

**运行快速隧道**（无需 Cloudflare 账号——会给你一个 `https://<random>.trycloudflare.com` URL）：

```bash
cloudflared tunnel --url http://localhost:8090
```

记下打印出的 URL——这就是你要提供给 Meta 的地址。

:::warning 快速隧道会轮换
免费快速隧道的 URL 每次重启 `cloudflared` 都会变化。要获得稳定 URL，请用 `cloudflared tunnel login` 登录并创建具名隧道。免费 Cloudflare 账号可获得无限量的具名隧道——具名隧道的工作流程请参见 [Cloudflare 文档](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)。
:::

### ngrok

```bash
ngrok http 8090
```

免费套餐每次重启都会显示不同的 URL。付费套餐提供稳定的子域名。

### 自有域名 + 反向代理

如果你已经有一台带 TLS 证书的服务器（Caddy、nginx 等），把某条路由指向 `localhost:8090`。这是生产环境中最稳定的方案，但需要既有的基础设施。

---

## 在 Meta 侧配置 webhook

隧道运行起来之后：

1. 记下隧道打印出的公网 URL——比如 `https://abc123.trycloudflare.com`。
2. 生成一个 **Verify Token** —— 向导会用 `secrets.token_urlsafe(32)` 帮你生成；如果你手动配置，请运行：
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   将其保存为 `~/.hermes/.env` 中的 `WHATSAPP_CLOUD_VERIFY_TOKEN`。
3. 启动 Hermes 网关：`hermes gateway`。
4. 在 Meta App Dashboard → **WhatsApp → Configuration**（取决于 UI 版本，也可能是 **Use cases → Customize → Configuration**）→ 在 Webhook 区域点击 **Edit**。
5. 填写：
   - **Callback URL**：`https://abc123.trycloudflare.com/whatsapp/webhook`
   - **Verify Token**：第 2 步得到的字符串（必须完全一致）
6. 点击 **Verify and save**。Meta 会用一个 GET 请求访问你的 URL，网关回显 challenge，随后 Meta 将该 webhook 标记为已验证。
7. 在 **Webhook fields** 下点击 **Manage** → 订阅 **messages** 字段。正是它告诉 Meta 真正把入站消息投递到你的 webhook。

**手动验证整个回路**（在第三个终端中）：

```bash
TUNNEL="https://abc123.trycloudflare.com"
VERIFY="<your verify token>"

# 应打印 HTTP 200，正文为 "hello"
curl -i "$TUNNEL/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=$VERIFY&hub.challenge=hello"

# 健康检查端点——应显示 verify_token_configured: true 和 app_secret_configured: true
curl "$TUNNEL/health"
```

---

## 收件人白名单（Meta 侧）

在开发模式下（你的应用通过 App Review 之前），Meta 会限制机器人可以给哪些号码发消息：

1. App Dashboard → WhatsApp → API Setup → **To** 下拉框。
2. 点击 **Manage phone number list**。
3. 添加你想发送消息的手机号（你自己的、团队的、友好的测试者）。Meta 会通过短信或 WhatsApp 向每个号码发送 6 位验证码。

开发模式下最多 5 个号码。通过 App Review 后即可解除此限制。

---

## 允许列表（Hermes 侧）

除了 Meta 的收件人白名单之外，Hermes 还有自己的按平台允许列表，用于控制**代理会处理哪些入站消息**。添加到 `~/.hermes/.env`：

```bash
# 逗号分隔的手机号，含国家代码，不含 '+' / 空格 / 短横线
WHATSAPP_CLOUD_ALLOWED_USERS=15551234567,15557654321

# 或者允许所有人（仅在与 Meta 的收件人白名单配合时才安全）
# WHATSAPP_CLOUD_ALLOW_ALL_USERS=true
```

向导会在第 6 步设置此项。没有允许列表时，**每一条入站消息都会被拒绝**——这是有意为之，这样即便收件人白名单被放宽，机器人也不会被随机号码调用。

---

## 完善机器人的 WhatsApp 资料

WhatsApp 会在聊天标题栏和联系人列表中显示机器人的**名称和头像**。这些无法通过 Cloud API 设置——它们位于 Meta 的 Business Manager 中。

机器人跑通之后，前往 **[business.facebook.com/wa/manage/phone-numbers](https://business.facebook.com/wa/manage/phone-numbers/)**，点击你的手机号，你会看到：

| 内容 | 位置 | 说明 |
|---|---|---|
| **显示名称** | 手机号页面顶部 | 修改需经过 Meta 的名称审核流程（约 24–48 小时）。 |
| **头像** | 手机号页面顶部 | 方形图片，建议 ≥640×640px。立即生效。 |
| **简介 / 描述 / 网站 / 邮箱 / 营业时间 / 类别** | “Edit profile” 按钮 | 用户点击机器人名称时会在信息面板中看到这些内容。纯装饰性。 |
| **认证徽章**（绿色对勾） | Business Manager → Security Center → Start Verification | 需要走 Meta 单独的企业验证流程。 |

`hermes whatsapp-cloud` 向导会在配置结束时打印这些链接。这些都不是机器人正常工作的必要条件——纯粹是让机器人在用户眼中更好看。

---

## 配置参考

所有设置都位于 `~/.hermes/.env`。必填项以**粗体**标出。

| 变量 | 默认值 | 描述 |
|---|---|---|
| **`WHATSAPP_CLOUD_PHONE_NUMBER_ID`** | — | 来自 API Setup 的 15-17 位 ID。**不是**手机号。 |
| **`WHATSAPP_CLOUD_ACCESS_TOKEN`** | — | Meta 访问令牌（以 `EAA` 开头）。24 小时临时令牌或 System User 永久令牌。 |
| **`WHATSAPP_CLOUD_APP_SECRET`** | — | 来自 Settings → Basic 的 32 位十六进制串。没有它，入站请求会被拒绝并返回 503。 |
| **`WHATSAPP_CLOUD_VERIFY_TOKEN`** | — | 用于 GET 握手的共享密钥。由向导自动生成。 |
| **`WHATSAPP_CLOUD_ALLOWED_USERS`** | — | 逗号分隔的、允许向机器人发消息的 wa_id。 |
| `WHATSAPP_CLOUD_ALLOW_ALL_USERS` | `false` | 设为 `true` 可绕过允许列表。 |
| `WHATSAPP_CLOUD_APP_ID` | — | 可选，供未来的分析统计集成使用。 |
| `WHATSAPP_CLOUD_WABA_ID` | — | 可选，供未来的分析统计集成使用。 |
| `WHATSAPP_CLOUD_WEBHOOK_HOST` | `0.0.0.0` | webhook 服务器绑定的网络接口。 |
| `WHATSAPP_CLOUD_WEBHOOK_PORT` | `8090` | webhook 服务器绑定的端口。必须与隧道转发的端口一致。 |
| `WHATSAPP_CLOUD_WEBHOOK_PATH` | `/whatsapp/webhook` | Meta 投递请求的 URL 路径。 |
| `WHATSAPP_CLOUD_API_VERSION` | `v20.0` | Meta Graph API 版本。仅当 Meta 文档推荐更新版本时才覆盖。 |
| `WHATSAPP_CLOUD_HOME_CHANNEL` | — | 用作机器人主频道的 wa_id（供 cron 任务等使用）。 |

你可以**同时**启用 Baileys（`whatsapp`）和 Cloud（`whatsapp_cloud`）两个适配器，分别对应不同的手机号。

---

## 功能特性

### 入站

- **文本消息** —— 直接传递给代理。
- **图片** —— 自动下载并附加到代理的输入中。具备原生视觉能力的模型（Claude、GPT-4o、Gemini 等）直接读取图片；不具备视觉能力的模型则收到自动生成的文字描述。
- **语音消息** —— 自动下载为 `.ogg`，通过你配置的 STT provider（本地 faster-whisper、OpenAI/Nous、Groq 等）转写，然后以文本形式交给代理。
- **文档** —— 自动下载。100KB 以内、可读为文本的小文件（`.txt`、`.md`、`.json`、`.py`、`.csv` 等）会被内联到代理的输入中，使其无需调用工具即可阅读。更大的文件会缓存在本地，供代理的其他工具访问。
- **按钮点击** —— 当用户点击机器人此前发送的按钮（澄清选项、命令审批、斜杠命令确认）时，该点击会被直接路由到对应的处理器。过期的点击则回退为按普通文本输入处理。
- **回复上下文** —— 当用户回复机器人之前的某条消息时，代理会看到原始消息作为上下文。

### 出站

- **文本** —— markdown 会自动转换为 WhatsApp 风格的语法（`**bold**` → `*bold*`、`~~strike~~` → `~strike~`、标题 → 粗体、`[link](url)` → `link (url)`）。长消息按每块 4096 字符切分。
- **图片** —— 支持代理生成的图片和本地图片文件，均以原生照片附件形式发送。
- **语音消息** —— 文本转语音的输出经 ffmpeg 转换为 WhatsApp 原生语音条（绿色波形）。未安装 ffmpeg 时，回退为 MP3 音频附件。参见下文“语音消息”。
- **视频 / 文档** —— 均支持，以原生附件形式发送。

### 交互式体验

当代理触发下列任一流程时，Hermes 会使用 WhatsApp 的原生交互消息——点击即可作答的按钮，而不是“回复数字”式的提示：

- **`clarify` 工具** —— 多选问题渲染为快速回复按钮（1–3 个选项）或点击打开的列表面板（4 个以上选项）。选择 “✏️ Other” 可让用户输入自由文本作为答案，代理会收到该答案作为结果。
- **危险命令审批** —— 当代理的终端/代码执行触及受限命令时，用户会看到 `✅ Approve` / `❌ Deny` 按钮，而无需输入 `/approve` 或 `/deny`。
- **斜杠命令确认** —— `/reload-mcp` 这类特权命令会显示 `✅ Approve Once` / `🔒 Always` / `❌ Cancel` 按钮。

如果按钮渲染失败（例如在旧版 WhatsApp 客户端上），所有交互式提示都会优雅降级为纯文本。

### 已读回执与输入指示

Hermes 会立即确认入站消息：

- 网关一收到消息，你的消息就会显示**蓝色双勾**。
- 代理准备回复期间，WhatsApp 聊天中机器人的名称下会显示**“正在输入…”**。
- 机器人的第一条响应消息到达时，输入指示会自动消失。

这样就能清楚区分机器人是否已看到你的消息，还是仍在准备回复。

### 语音消息

WhatsApp 区分“语音消息”（绿色波形气泡）和普通音频文件附件。差别纯粹在编码格式：语音消息必须是 `audio/ogg` 且使用 `opus` 编码。

Hermes 的 TTS 产出 MP3。有两条路径：

- **PATH 上有 ffmpeg**（推荐）—— 出站 TTS 会被转换并以正规语音消息形式送达。安装方式：
  - Windows：`winget install Gyan.FFmpeg`
  - macOS：`brew install ffmpeg`
  - Linux：使用包管理器
- **没有 ffmpeg** —— 出站 TTS 以 MP3 音频附件形式送达。播放正常，只是看起来不像语音消息。网关日志中会打印一次性警告以便你知晓。

你可以通过健康检查端点确认网关是否找到了 ffmpeg：

```bash
curl http://localhost:8090/health
# 查看 "ffmpeg_present": true
```

---

## 已知限制

### 24 小时会话窗口

Meta 只允许在用户最后一条入站消息之后的 24 小时窗口内发送**自由格式消息**。超出该窗口后，Meta 的 API 只接受预先审核通过的**消息模板**。

**这在实践中意味着：**

- 反应式聊天（用户私信 → 机器人在 24 小时内回复 → 用户再回复 → ……）可以永远运行。这覆盖了 >95% 的常规机器人用法。
- **向 WhatsApp 投递的 cron 任务**如果间隔超过 24 小时，会以 Graph 错误码 `131047`（"Re-engagement message"）失败。
- **长时间运行的 `delegate_task` 异步结果**如果耗时超过 24 小时，会以同样方式失败。
- **Webhook 订阅者**将外部事件路由到 WhatsApp 时，如果用户最近没有给机器人发过私信，也会失败。

Hermes 会在系统提示中就该窗口向代理发出提醒，因此模型在安排延迟消息时知道要提及它。

消息模板支持（窗口外发送的变通方案）在 Hermes 中尚未实现。如果你需要它，请[提交 issue](https://github.com/NousResearch/hermes-agent/issues)——它已在计划中，但在等待明确的需求信号。

### 群聊

Cloud API 的群组支持有限（能力层级由 Meta 控制）。Hermes 的 `whatsapp_cloud` 适配器在 v1 中目前**仅处理私聊消息**。如果你需要群聊，请使用 Baileys 桥接。

### 出站速率限制

Meta 的默认吞吐量为**每个商业手机号每秒 80 条消息**，可申请提升。Hermes 目前不在客户端强制执行该限制——极高频的发送可能触及 Meta 的上限。

---

## 故障排查

### Meta 仪表板中配置验证失败（“URL couldn't be validated”）

几乎总是以下原因之一：

- **隧道 URL 错误或已过期** —— cloudflared 快速隧道会轮换。获取新的 URL 并同时更新 `.env` 和 Meta 的仪表板。
- **Verify token 不匹配** —— `~/.hermes/.env` 中 `WHATSAPP_CLOUD_VERIFY_TOKEN` 的值必须与你在 Meta 仪表板中输入的完全一致。先运行上面的 curl 探测，确认网关的验证握手在本地可用。
- **网关未运行** —— 检查 `hermes gateway` 是否已启动。
- **未设置 App Secret** —— 没有它，Hermes 会以 503 拒绝入站 POST。Meta 会将其解读为“无法验证”。

### `graph error 100`：Object with ID '...' does not exist

你把手机号（10-11 位）粘贴到了 `WHATSAPP_CLOUD_PHONE_NUMBER_ID`，而不是 Phone Number ID（Meta 的 15-17 位内部 ID）。请重新检查 API Setup 页面——Phone Number ID 显示在 "From" 下拉框*下方*。

现在向导已通过校验器捕获此问题，但如果你手动配置，仍值得了解。

### `graph error 190`：Authentication Error

你的访问令牌无效。子错误码：

- `subcode 463` —— 令牌已过期。临时令牌有效期 24 小时。请重新生成，或改用 System User 永久令牌（见上文）。
- `subcode 467` —— 令牌已失效（被吊销或密码已更改）。
- 其他 190 —— 生成令牌时未包含所需权限。请确保三项权限（`business_management`、`whatsapp_business_messaging`、`whatsapp_business_management`）都已勾选。

### `graph error 131047`：Re-engagement message

24 小时会话窗口已过期（参见“已知限制”）。二选一：

- 让用户先给机器人发私信以重新打开窗口。
- 等待 Hermes 支持消息模板。

### 入站消息：`media metadata fetch failed (status=401)`

与出站（`graph error 190`）的 401 根因相同——访问令牌无效或已过期。请修复令牌。

### 机器人回复显示为原始 JSON / 工具调用泄漏

常见原因：为 `whatsapp_cloud` 配置的工具集缺少代理想要调用的工具。请检查 `hermes tools list`，并确认该平台使用的是 `hermes-whatsapp`（Cloud 适配器的默认工具集，与 Baileys 相同）。

如果模型输出的是形似工具调用的文本而非结构化调用，通常意味着工具集实际为空。平台 → 默认工具集的映射见 `hermes_cli/platforms.py`。

### STT（语音消息转写）返回空 / “could not transcribe”

默认的 `stt.provider: local` 需要 `pip install faster-whisper`。如果你是 Nous 订阅用户，可以改为通过 Meta 的托管音频网关来路由 STT：

```bash
hermes config set stt.provider openai
hermes config set stt.use_gateway true
hermes gateway restart
```

这会使用你的 Nous Portal 访问令牌，而无需单独的 OpenAI 密钥。

---

## 安全说明

- **把 App Secret 当作密码对待** —— 任何拿到它的人都能伪造 Hermes 会认可为真实的 webhook 载荷。
- **verify token 是共享密钥** —— 泄露的风险较低（最坏情况是有人把 Meta 的 webhook 重新订阅到他们自己的 URL），但仍应避免提交到代码库。
- **访问令牌就是机器人的身份** —— System User 令牌等同于长期有效的 API 密钥。一旦部署被攻破，请立即轮换。
- **设置了 `WHATSAPP_CLOUD_APP_SECRET` 时，webhook 端点只接受已签名的请求** —— 即便在开发环境也请保持设置。没有它，网关会以 HTTP 503 拒绝入站投递。
- **`/health` 端点未做鉴权** —— 它只报告配置是否存在的布尔值，而不是具体值，因此对外暴露是安全的。但如果你不想暴露它，可以在反向代理 / 隧道层限制访问。

---

## 与 Baileys 桥接的对比

| | Baileys（`hermes whatsapp`） | Cloud API（`hermes whatsapp-cloud`） |
|---|---|---|
| 账号类型 | 个人 | 商业 |
| 配置方式 | 扫描二维码 | Meta 应用 + WABA + 令牌 |
| 依赖 | Node.js + npm | 纯 Python（httpx + aiohttp） |
| 进程 | 受管的 Node 子进程 | aiohttp webhook 服务器 |
| 是否需要公网 URL？ | 否 | 是 |
| 账号封禁风险 | 有（非官方 API） | 无（官方支持） |
| 入站 | 轮询 Node 桥接 | 来自 Meta 的 Webhook POST |
| 出站 | 本地桥接 → Baileys | HTTPS 到 graph.facebook.com |
| 群组 | 完整支持 | 仅私聊（v1） |
| 24 小时窗口 | 无限制 | 硬性规则——超出后需使用模板 |
| 语音消息（出站） | 原生 | 有 ffmpeg 时原生，否则回退 MP3 |
| 已读回执 | 无 | 有（蓝色双勾） |
| 输入指示 | 无 | 有（响应时自动消失） |
| 交互式按钮 | 仅文本回退 | 原生（澄清、审批、斜杠确认） |
| 生产使用 | 有风险（Meta 可能封号） | 专为此设计 |

多数把 Hermes 用于个人项目的用户偏好 Baileys。多数运行面向客户机器人的用户偏好 Cloud API。

---

## 参见

- [Meta 官方 WhatsApp Business Cloud API 文档](https://developers.facebook.com/documentation/business-messaging/whatsapp/) —— 底层平台、定价、App Review 以及 Meta 侧速率限制的权威参考。
- [WhatsApp（Baileys 桥接）配置](whatsapp.md) —— 面向个人项目的备选集成方案。
- [消息平台总览](index.md) —— 一览所有消息平台集成。
