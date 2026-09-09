---
title: "Nous Tool Gateway（工具网关）"
description: "一份订阅，覆盖全部工具。网页搜索、文生图、TTS 与云端浏览器——全部通过 Nous Portal 路由，无需额外 API Key。"
sidebar_label: "Tool Gateway"
sidebar_position: 2
---

# Nous Tool Gateway（工具网关）

**一份订阅，内置全部工具。**

Tool Gateway 包含在每一份付费 [Nous Portal](https://portal.nousresearch.com) 订阅中。它会把 Hermes 的工具调用——网页搜索、文生图、语音合成与云端浏览器自动化——路由到 Nous 已经在运行的基础设施上，因此你不必仅仅为了让智能体好用，就去分别注册 Firecrawl、FAL、OpenAI、Browser Use 或其他任何服务。

<div style={{display: 'flex', gap: '1rem', flexWrap: 'wrap', margin: '1.5rem 0'}}>
  <a href="https://portal.nousresearch.com/manage-subscription" style={{background: 'var(--ifm-color-primary)', color: 'white', padding: '0.75rem 1.5rem', borderRadius: '6px', textDecoration: 'none', fontWeight: 'bold'}}>开通或管理订阅 →</a>
</div>

## 包含能力

| | 工具 | 你能得到什么 |
|---|---|---|
| 🔍 | **网页搜索与抽取** | 通过 Firecrawl 提供智能体级别的网页搜索与整页内容抽取。无需担心速率限制——扩缩容由网关负责。 |
| 🎨 | **文生图** | 同一个端点下的九个模型：**FLUX 2 Klein 9B**、**FLUX 2 Pro**、**Z-Image Turbo**、**Nano Banana Pro**（Gemini 3 Pro Image）、**GPT Image 1.5**、**GPT Image 2**、**Ideogram V3**、**Recraft V4 Pro**、**Qwen Image**。可用参数逐次指定，也可让 Hermes 默认使用 FLUX 2 Klein。 |
| 🔊 | **语音合成** | 将 OpenAI TTS 音色接入 `text_to_speech` 工具。可在 Telegram 中发送语音条、为流水线生成音频、为任意内容配音。 |
| 🌐 | **云端浏览器自动化** | 通过 Browser Use 提供无头 Chromium 会话。`browser_navigate`、`browser_click`、`browser_type`、`browser_vision`——全部智能体驱动原语齐备，无需 Browserbase 账号。 |

这四类能力均按用量计入你的 Nous 订阅账单。你可以任意组合——例如网页与文生图走网关，而 TTS 继续使用自己的 ElevenLabs Key；也可以把全部流量都交给 Nous。

## 为什么需要它

要构建一个真正*能做事*的智能体，通常意味着拼接 5 个以上的 API 订阅——每个都有各自的注册流程、速率限制、计费方式和怪癖。网关把这一切收敛到一个账号：

- **一份账单。** 只付给 Nous，其余由我们处理。
- **一次注册。** 无需管理 Firecrawl、FAL、Browser Use 或 OpenAI Audio 账号。
- **一把钥匙。** 你的 Nous Portal OAuth 覆盖所有工具。
- **同样的质量。** 与直连 Key 路径使用相同的后端——只是由我们代为承接。

你随时可以改用自己的 Key——按工具、随时切换。网关不是锁定，而是捷径。

## 快速开始

有三条入口——挑一条最符合你当前状态的：

```bash
hermes setup --portal     # 全新安装：Nous OAuth + 将 Nous 设为提供商 + 一次性打开 Tool Gateway
```

```bash
hermes model              # 将推理提供商切换为 Nous Portal——随后 Hermes 会询问是否为所有工具打开网关
```

```bash
hermes tools              # 按工具启用网关——为任意工具选择 “Nous Subscription”
```

`hermes setup --portal` 与 `hermes model` 是“一次搞定”的路径：登录一次，并可选择把所有工具都切到网关。`hermes tools` 则是“按需点单”的路径——只打开你想要的工具，一次一个。

**你不必先登录。** 使用 `hermes tools` 时，Nous 托管的后端（Web search、Image、Video、TTS、Browser）始终会列出，即使你从未登录过 Nous Portal。选中其中一个后，如果你尚未认证，Hermes 会当场执行 Portal 登录——无需事先运行 `hermes model`。如果你的 Nous OAuth 已经生效，选中该后端会立即启用，不再有额外提示。这条路径只会为你完成登录并打开你选中的那一个工具——它**不会**切换你的推理提供商，也**不会**提示你为其他所有工具启用网关。

随时查看当前生效的配置：

```bash
hermes portal info        # Portal 认证状态 + Tool Gateway 路由摘要
hermes portal tools       # 网关工具目录及每个工具的当前路由
hermes status             # 完整系统状态（Tool Gateway 是其中一节）
```

`hermes portal info` 会显示类似这样的小节：

```
◆ Nous Tool Gateway
  Nous Portal     ✓ managed tools available
  Web tools       ✓ active via Nous subscription
  Image gen       ✓ active via Nous subscription
  TTS             ✓ active via Nous subscription
  Browser         ○ active via Browser Use key
```

标记为 “active via Nous subscription” 的工具即经网关路由，其余则使用你自己的 Key。

## 资格

Tool Gateway 是**付费订阅**功能。免费档的 Nous 账号可以使用 Portal 进行推理，但不含托管工具——请 [升级你的套餐](https://portal.nousresearch.com/manage-subscription) 以解锁网关。

部分账号还可享有**免费工具额度池**——一小份托管工具用量，可在没有付费订阅的情况下覆盖网关工具调用。当存在免费额度池时，网关会将其显示出来，并在首次使用时给出设置提示，你可以选择加入并立即开始使用托管工具。

## 自由组合

网关是按工具生效的。你可以只为需要的部分打开：

- **所有工具都走 Nous** —— 最省事；一份订阅，全部搞定。
- **网页与文生图走网关，TTS 自备** —— 保留你自己的 ElevenLabs 音色，其余交给 Nous。
- **只为没有 Key 的能力启用网关** —— “我已经付费买了 Browserbase，但不想再开一个 Firecrawl 账号”，完全可行。

随时通过以下命令切换任意工具：

```bash
hermes tools          # 各工具类别的交互式选择器
```

选择工具，并将提供商选为 **Nous Subscription**（或任意你偏好的直连提供商）。无需编辑配置文件。如果你还没有登录 Nous Portal，选择 **Nous Subscription** 会就地触发 Portal 登录——不需要先通过 `hermes model` 完成认证。

## 使用单个图像模型

文生图默认使用 FLUX 2 Klein 9B 以追求速度。可在调用时向 `image_generate` 工具传入模型 ID 来逐次覆盖：

| 模型 | ID | 适用场景 |
|---|---|---|
| FLUX 2 Klein 9B | `fal-ai/flux-2/klein/9b` | 快速，良好的默认选择 |
| FLUX 2 Pro | `fal-ai/flux-2-pro` | 更高保真度的 FLUX |
| Z-Image Turbo | `fal-ai/z-image/turbo` | 风格化，速度快 |
| Nano Banana Pro | `fal-ai/nano-banana-pro` | Google Gemini 3 Pro Image |
| GPT Image 1.5 | `fal-ai/gpt-image-1.5` | OpenAI 图像生成，文本+图像 |
| GPT Image 2 | `fal-ai/gpt-image-2` | OpenAI 最新版 |
| Ideogram V3 | `fal-ai/ideogram/v3` | 提示词遵循度强 + 排版出色 |
| Recraft V4 Pro | `fal-ai/recraft/v4/pro/text-to-image` | 矢量风格，平面设计 |
| Qwen Image | `fal-ai/qwen-image` | 阿里多模态 |

模型集合会不断演进——`hermes tools` → Image Generation 中显示的是当前的实时列表。

---

## 配置参考

大多数用户完全不需要碰这一节——`hermes model` 与 `hermes tools` 已经以交互方式覆盖了所有工作流。本节面向直接编写 config.yaml 或脚本化部署的场景。

### 按工具的 `use_gateway` 开关

每个工具的配置块都接受一个 `use_gateway` 布尔值：

```yaml
web:
  backend: firecrawl
  use_gateway: true

image_gen:
  use_gateway: true

tts:
  provider: openai
  use_gateway: true

browser:
  cloud_provider: browser-use
  use_gateway: true
```

优先级：`use_gateway: true` 会强制走 Nous，无论 `.env` 中是否还有直连 Key。`use_gateway: false`（或未设置）时，若有直连 Key 则优先使用，仅在完全没有直连凭据时才回退到网关。

### 关闭网关

```yaml
web:
  use_gateway: false   # Hermes 此时会使用 .env 中的 FIRECRAWL_API_KEY
```

当你在 `hermes tools` 中选择非网关提供商时，该标志会被自动清除，因此通常无需手动处理。

### 自建网关（进阶）

在自行运行兼容 Nous 的网关？可在 `~/.hermes/.env` 中覆盖端点：

```bash
TOOL_GATEWAY_DOMAIN=your-domain.example.com
TOOL_GATEWAY_SCHEME=https
TOOL_GATEWAY_USER_TOKEN=your-token        # 通常由 Portal 登录自动填充
FIRECRAWL_GATEWAY_URL=https://...         # 单独覆盖某一个端点
```

这些开关是为定制基础设施场景（企业部署、开发环境）准备的。普通订阅用户永远不需要设置它们。

## 常见问题

### 它能配合 Telegram / Discord / 其他消息网关使用吗？

可以。Tool Gateway 作用于工具执行层，而非 CLI。任何能调用工具的入口——CLI、Telegram、Discord、Slack、IRC、Teams、API 服务器等——都会透明地受益于它。

### 订阅到期会怎样？

经网关路由的工具会停止工作，直到你续订，或通过 `hermes tools` 换成直连 API Key。Hermes 会给出明确的错误提示并指向 Portal。

### 能否按工具查看用量或费用？

可以——[Nous Portal 控制台](https://portal.nousresearch.com) 会按工具拆分用量，让你看清账单由什么驱动。

### Modal（无服务器终端）包含在内吗？

Modal 作为 Nous 订阅的**可选附加能力**提供，并不属于默认的 Tool Gateway 组合。当你需要一个用于 shell 执行的远程沙箱时，可通过 `hermes setup terminal` 或直接在 `config.yaml` 中配置它。

### 启用网关时需要删掉已有的 API Key 吗？

不需要——把它们留在 `.env` 即可。当 `use_gateway: true` 时，Hermes 会跳过直连 Key 而使用网关。把该标志改回 `false`，你的 Key 就重新成为来源。网关不是锁定。
