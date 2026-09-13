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

选择工具类别（Web、Browser、Image Generation、TTS），再将提供商选为 **Nous Subscription**。这会把该类别的选择键写为 `nous`（例如 `image_gen.provider: nous`）。

`hermes setup --portal` 与 `hermes model` 是“一次搞定”的路径：登录一次，并可选择把所有工具都切到网关。`hermes tools` 则是“按需点单”的路径——只打开你想要的工具，一次一个。

每个工具类别只有一个选择键，选 **Nous Subscription** 即写入 `nous`：

```yaml
web:
  backend: nous          # 网页搜索/抓取走 Tool Gateway

image_gen:
  provider: nous

tts:
  provider: nous

stt:
  provider: nous

browser:
  cloud_provider: nous
```

优先级：`use_gateway: true` 会强制走 Nous，无论 `.env` 中是否还有直连 Key。`use_gateway: false`（或未设置）时，若有直连 Key 则优先使用，仅在完全没有直连凭据时才回退到网关。

当某工具类别的选择键为 `nous` 时，运行时会把 API 调用路由到 Nous Tool Gateway，而不是使用直连 Key：

1. **网页工具** — `web_search` / `web_extract` 走网关的 Firecrawl 端点  
2. **文生图** — `image_generate` 走网关的 FAL 端点  
3. **TTS** — `text_to_speech` 走网关的 OpenAI Audio 端点  
4. **浏览器** — `browser_navigate` 等走网关的 Browser Use 端点  

网关使用 Nous Portal 凭据认证（在 `hermes model` 完成后写入 `~/.hermes/auth.json`）。

### 优先级

运行时**始终使用已保存的选择**，凭据是否存在不会影响路由：

- **选择为 `nous`** → 走网关，即使 `.env` 里仍有直连 Key（例如 `FAL_KEY` 会被忽略）
- **选择为具体厂商**（如 `fal`、`firecrawl`）→ 直连；若对应 Key 缺失则报错并提示运行 `hermes tools`，**不会**静默回退到网关
- **从未配置过的类别** → 按可用凭据自动检测（行为不变）；但一旦存在选择，仅往 `.env` 加 Key 不会改变路由

（旧版的 `use_gateway` 布尔键已废弃：不再写入，读取时 `use_gateway: true` 等同于 `nous`。请改用 `hermes tools` 选择提供商。）

## 切回直连 Key

对单个工具停用网关：

```bash
hermes tools    # 选择该工具 → 选直连提供商
```

或在配置中把选择键改回具体厂商：

```yaml
web:
  backend: firecrawl  # 此时使用 .env 中的 FIRECRAWL_API_KEY
```

在 `hermes tools` 中选择非网关提供商时，选择键会被改写为该厂商名（旧的 `use_gateway` 键若存在会被一并移除），避免配置自相矛盾。

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

不需要。类别选择为 **Nous Subscription**（`nous`）时，运行时会忽略该类别的直连 Key；Key 仍保留在 `.env`。之后在 `hermes tools` 里改回直连提供商，Key 即恢复生效。

### 能否部分工具走网关、部分走直连？

可以。选择按工具类别独立配置。例如：网页与文生图选 Nous Subscription，TTS 用 ElevenLabs，浏览器用 Browserbase。

### 订阅到期会怎样？

经网关路由的工具会停止工作，直到你续订，或通过 `hermes tools` 换成直连 API Key。Hermes 会给出明确的错误提示并指向 Portal。

### 能否按工具查看用量或费用？

可以——[Nous Portal 控制台](https://portal.nousresearch.com) 会按工具拆分用量，让你看清账单由什么驱动。

### Modal（无服务器终端）包含在内吗？

Modal 作为 Nous 订阅的**可选附加能力**提供，并不属于默认的 Tool Gateway 组合。当你需要一个用于 shell 执行的远程沙箱时，可通过 `hermes setup terminal` 或直接在 `config.yaml` 中配置它。

### 启用网关时需要删掉已有的 API Key 吗？

不需要——把它们留在 `.env` 即可。当 `use_gateway: true` 时，Hermes 会跳过直连 Key 而使用网关。把该标志改回 `false`，你的 Key 就重新成为来源。网关不是锁定。
