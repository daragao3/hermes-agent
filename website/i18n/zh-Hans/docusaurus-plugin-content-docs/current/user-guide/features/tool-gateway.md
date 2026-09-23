---
sidebar_position: 2
title: "Nous Tool Gateway（工具网关）"
sidebar_label: "Tool Gateway"
description: "一份订阅，覆盖全部工具。网页搜索、文生图、TTS 与云端浏览器——全部通过 Nous Portal 路由，无需额外 API Key。"
---

# Nous Tool Gateway（工具网关）

**一份订阅，内置全部工具。**

Tool Gateway 包含在每一份付费 [Nous Portal](https://portal.nousresearch.com) 订阅中。它会把 Hermes 的工具调用——网页搜索、文生图、语音合成与云端浏览器自动化——路由到 Nous 已经在运行的基础设施上，因此你不必仅仅为了让智能体好用，就去分别注册 Firecrawl、FAL、OpenAI、Browser Use 或其他任何服务。

<div style={{display: 'flex', gap: '1rem', flexWrap: 'wrap', margin: '1.5rem 0'}}>
  <a href="https://portal.nousresearch.com/manage-subscription" style={{background: 'var(--ifm-color-primary)', color: 'white', padding: '0.75rem 1.5rem', borderRadius: '6px', textDecoration: 'none', fontWeight: 'bold'}}>开通或管理订阅 →</a>
</div>

## 包含能力 {#whats-included}

| | 工具 | 你能得到什么 |
|---|---|---|
| 🔍 | **网页搜索与抽取** | 通过 Firecrawl 提供智能体级别的网页搜索与整页内容抽取。无需担心速率限制——扩缩容由网关负责。 |
| 🎨 | **文生图** | 同一个端点下的九个模型：**FLUX 2 Klein 9B**、**FLUX 2 Pro**、**Z-Image Turbo**、**Nano Banana Pro**（Gemini 3 Pro Image）、**GPT Image 1.5**、**GPT Image 2**、**Ideogram V3**、**Recraft V4 Pro**、**Qwen Image**。可用参数逐次指定，也可让 Hermes 默认使用 FLUX 2 Klein。 |
| 🔊 | **语音合成** | 将 OpenAI TTS 音色接入 `text_to_speech` 工具。可在 Telegram 中发送语音条、为流水线生成音频、为任意内容配音。 |
| 🌐 | **云端浏览器自动化** | 通过 Browser Use 提供无头 Chromium 会话。`browser_navigate`、`browser_click`、`browser_type`、`browser_vision`——全部智能体驱动原语齐备，无需 Browserbase 账号。 |

这四类能力均按用量计入你的 Nous 订阅账单。你可以任意组合——例如网页与文生图走网关，而 TTS 继续使用自己的 ElevenLabs Key；也可以把全部流量都交给 Nous。

## 为什么需要它 {#why-its-here}

要构建一个真正*能做事*的智能体，通常意味着拼接 5 个以上的 API 订阅——每个都有各自的注册流程、速率限制、计费方式和怪癖。网关把这一切收敛到一个账号：

- **一份账单。** 只付给 Nous，其余由我们处理。
- **一次注册。** 无需管理 Firecrawl、FAL、Browser Use 或 OpenAI Audio 账号。
- **一把钥匙。** 你的 Nous Portal OAuth 覆盖所有工具。
- **同样的质量。** 与直连 Key 路径使用相同的后端——只是由我们代为承接。

你随时可以改用自己的 Key——按工具、随时切换。网关不是锁定，而是捷径。

## 快速开始 {#get-started}

有三条入口——挑一条最符合你当前状态的：

```bash
hermes setup --portal     # 全新安装：Nous OAuth + 将 Nous 设为提供商 + 一次性打开 Tool Gateway
```

```bash
hermes model              # 将推理提供商切换为 Nous Portal——随后 Hermes 会询问是否为所有工具打开网关
```

```bash
hermes tools              # 按工具启用网关——对任何想用的工具选择 "Nous Subscription"
```

`hermes setup --portal` 与 `hermes model` 是“一次搞定”的路径：登录一次，并可选择把所有工具都切到网关。`hermes tools` 则是“按需点单”的路径——只打开你想要的工具，一次一个。

**你不必先登录。** 在 `hermes tools` 中，Nous 托管的后端（Web search、Image、Video、TTS、Browser）总会列出，即使你从未登录过 Nous Portal。选中其中一个时，若你尚未认证，Hermes 会当场执行 Portal 登录——无需事先运行 `hermes model`。如果你的 Nous OAuth 已处于有效状态，选择该后端会立即启用，不再额外提示。这条路径只会让你登录并打开你选中的那一个工具——它**不会**切换你的推理提供商，也**不会**提示你为其他所有工具启用网关。

随时查看当前生效的配置：

```bash
hermes portal info        # Portal 认证 + Tool Gateway 路由概要
hermes portal tools       # 网关目录及每个工具当前的路由
hermes status             # 完整系统状态（Tool Gateway 是其中一节）
```

`hermes portal info` 会显示类似下面的一节：

```
◆ Nous Tool Gateway
  Nous Portal     ✓ managed tools available
  Web tools       ✓ active via Nous subscription
  Image gen       ✓ active via Nous subscription
  TTS             ✓ active via Nous subscription
  Browser         ○ active via Browser Use key
```

标记为 “active via Nous subscription” 的工具正经由网关运行，其余则使用你自己的 Key。

## 资格要求 {#eligibility}

Tool Gateway 是**付费订阅**功能。免费档的 Nous 账号可以使用 Portal 做推理，但不包含托管工具——[升级你的套餐](https://portal.nousresearch.com/manage-subscription) 即可解锁网关。

部分账号还享有**免费工具额度池**——一小份托管工具配额，无需付费订阅即可覆盖网关工具调用。当有免费额度池可用时，网关会将其展示出来，并在首次使用时给出设置提示，让你选择加入并立即开始使用托管工具。

## 启用清单 {#the-enablement-checklist}

选择 Nous 模型（`hermes model`）时，会提供一份按工具列出的网关后端清单。它的行为会尊重你已有的配置：

- 你已明确指向其他后端的工具（例如 `web.backend: searxng`、`browser.cloud_provider: camofox`）**永远不会出现在清单中**——你的选择不会被意外覆盖。
- 仅通过环境变量配置的工具（例如 `SEARXNG_URL`、`CAMOFOX_URL`）会以**未勾选**状态出现，并标注为保留你自己的后端。
- 只有真正未配置的工具才会被预先勾选。
- 拒绝会被记住：如果你提交清单时某个工具未勾选，之后再切换 Nous 模型时它不会被预先勾选（记录在 `config.yaml` 的 `tool_gateway_declined_tools` 中；之后再勾选它即可清除该拒绝记录）。

## 自由组合 {#mix-and-match}

网关按工具生效。只为你想要的工具打开它：

- **所有工具都走 Nous** —— 最省事；一份订阅，搞定。
- **网页 + 文生图走网关，TTS 自带** —— 保留你的 ElevenLabs 音色，其余交给 Nous。
- **只对你没有 Key 的服务使用网关** —— “我已经在为 Browserbase 付费，但不想再开一个 Firecrawl 账号”完全可行。

随时切换任意工具：

```bash
hermes tools          # 每个工具类别的交互式选择器
```

选中工具，将提供商选为 **Nous Subscription**（或你偏好的任意直连提供商）。无需编辑配置。如果你尚未登录 Nous Portal，选择 **Nous Subscription** 会就地启动 Portal 登录——无需先通过 `hermes model` 认证。

## 使用单个图像模型 {#using-individual-image-models}

为追求速度，文生图默认使用 FLUX 2 Klein 9B。可在每次调用时向 `image_generate` 工具传入模型 ID 进行覆盖：

| 模型 | ID | 适用场景 |
|---|---|---|
| FLUX 2 Klein 9B | `fal-ai/flux-2/klein/9b` | 快速，默认之选 |
| FLUX 2 Pro | `fal-ai/flux-2-pro` | 更高保真度的 FLUX |
| Z-Image Turbo | `fal-ai/z-image/turbo` | 风格化、快速 |
| Nano Banana Pro | `fal-ai/nano-banana-pro` | Google Gemini 3 Pro Image |
| GPT Image 1.5 | `fal-ai/gpt-image-1.5` | OpenAI 图像生成，文字 + 图像 |
| GPT Image 2 | `fal-ai/gpt-image-2` | OpenAI 最新模型 |
| Ideogram V3 | `fal-ai/ideogram/v3` | 提示词遵循度高 + 排版 |
| Recraft V4 Pro | `fal-ai/recraft/v4/pro/text-to-image` | 矢量风格、平面设计 |
| Qwen Image | `fal-ai/qwen-image` | 阿里巴巴多模态 |

模型集合会持续变化——`hermes tools` → Image Generation 会显示当前的实时列表。

---

## 配置参考 {#configuration-reference}

大多数用户永远不需要碰这里——`hermes model` 与 `hermes tools` 以交互方式覆盖了所有工作流。本节面向直接编写 config.yaml 或以脚本方式完成配置的场景。

### 每个工具类别一个选择键 {#one-selection-key-per-tool-category}

每个工具类别只有一个提供方选择键，由 `hermes tools` 选择器（或桌面 GUI）写入。选择 **Nous Subscription** 一行会写入值 `nous`，使该类别经由托管的 Tool Gateway 路由。选择 BYOK（自带 Key）一行则写入厂商名（`fal`、`openai`、`firecrawl`、`browser-use` 等），使用你自己的凭据直连：

```yaml
web:
  backend: nous          # 网页搜索/抽取走 Tool Gateway

image_gen:
  provider: nous         # 文生图走 Tool Gateway

tts:
  provider: nous         # TTS 走 Tool Gateway

stt:
  provider: nous         # 语音转文字走 Tool Gateway

browser:
  cloud_provider: nous   # 云端浏览器走 Tool Gateway
```

运行时**始终使用已保存的选择**——凭据是否存在永远不会选择或改道某个类别。`image_gen.provider: nous` 时，`.env` 里的 `FAL_KEY` 会被忽略；反之，`image_gen.provider: fal` 而未设置 `FAL_KEY` 时，会给出明确错误，而不是静默回退到网关：

```
image_gen is configured to use fal (set via hermes tools), but FAL_KEY is not set. Run 'hermes tools' to change it.
```

**从未配置过**的类别（从未写入选择键）仍像以前一样按可用凭据自动检测。但一旦存在选择，往 `.env` 中添加 Key 不会改变路由——只有 `hermes tools`（或编辑选择键）才会。

### 切回自己的 Key {#switching-back-to-your-own-keys}

```bash
hermes tools    # 选择该工具 → 选一个直连提供商（例如 Firecrawl）
```

或直接设置选择键：

```yaml
web:
  backend: firecrawl   # Hermes 此时使用 .env 中的 FIRECRAWL_API_KEY
```

### 旧版 `use_gateway` 标志（已废弃） {#legacy-use_gateway-flag-deprecated}

旧版 Hermes 使用按工具的 `use_gateway: true` 布尔值来经由网关路由。该标志属于**遗留配置**：它不会再被写入，且 `hermes tools` 选择器在改写某类别的选择时会将其从配置中移除。仍包含 `use_gateway: true` 的旧配置在读取时会被解释为 `nous` 选择，因此已有配置可继续工作。不要在新配置中设置 `use_gateway`——请改在 `hermes tools` 中选择提供方。

### 自建网关（进阶） {#self-hosted-gateway-advanced}

在自行运行兼容 Nous 的网关？可在 `~/.hermes/.env` 中覆盖端点：

```bash
TOOL_GATEWAY_DOMAIN=your-domain.example.com
TOOL_GATEWAY_SCHEME=https
TOOL_GATEWAY_USER_TOKEN=your-token        # 通常由 Portal 登录自动填充
FIRECRAWL_GATEWAY_URL=https://...         # 单独覆盖某一个端点
```

这些开关是为定制基础设施场景（企业部署、开发环境）准备的。普通订阅用户永远不需要设置它们。

## 常见问题 {#faq}

### 它能配合 Telegram / Discord / 其他消息网关使用吗？ {#does-it-work-with-telegram--discord--the-other-messaging-gateways}

可以。Tool Gateway 工作在工具执行层，而不是 CLI 层。任何能调用工具的界面——CLI、Telegram、Discord、Slack、IRC、Teams、API 服务器等等——都会透明地受益。

### 订阅到期会怎样？ {#what-happens-if-my-subscription-expires}

经网关路由的工具会停止工作，直到你续订，或通过 `hermes tools` 换成直连 API Key。Hermes 会给出明确的错误提示并指向 Portal。

### 能否按工具查看用量或费用？ {#can-i-see-usage-or-costs-per-tool}

可以——[Nous Portal 控制台](https://portal.nousresearch.com) 会按工具拆分用量，让你看清账单由什么驱动。

### Modal（无服务器终端）包含在内吗？ {#is-modal-serverless-terminal-included}

Modal 作为 Nous 订阅的**可选附加能力**提供，并不属于默认的 Tool Gateway 组合。当你需要一个用于 shell 执行的远程沙箱时，可通过 `hermes setup terminal` 或直接在 `config.yaml` 中配置它。

### 启用网关时需要删掉已有的 API Key 吗？ {#do-i-need-to-delete-my-existing-api-keys-when-i-enable-the-gateway}

不需要——把它们留在 `.env` 即可。当某个工具的选择为 **Nous Subscription** 时，该工具的直连 Key 只会被忽略。在 `hermes tools` 中重新选择直连提供商，你的 Key 就会重新成为来源。网关不是锁定。
