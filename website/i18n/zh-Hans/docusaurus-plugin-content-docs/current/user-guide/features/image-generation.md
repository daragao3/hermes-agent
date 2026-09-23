---
sidebar_position: 6
title: 文生图（Image Generation）
sidebar_label: 文生图
description: 通过 FAL.ai 文生图——支持 11 个模型，含 FLUX 2、GPT Image（1.5 与 2）、Nano Banana Pro、Ideogram、Recraft V4 Pro、Krea 2 等，可通过 `hermes tools` 选择。
---

# 文生图（Image Generation）

Hermes Agent 通过 FAL.ai 根据文字提示生成图像。开箱即支持 11 个模型，在速度、画质与成本上各有取舍。当前模型可通过 `hermes tools` 由用户配置，并持久化在 `config.yaml` 中。

## 支持的模型 {#supported-models}

| 模型 | 速度 | 特点 | 价格 |
|---|---|---|---|
| `fal-ai/flux-2/klein/9b` *（默认）* | `<1s` | 快、文字清晰 | $0.006/MP |
| `fal-ai/flux-2-pro` | ~6s | 棚拍级写实 | $0.03/MP |
| `fal-ai/z-image/turbo` | ~2s | 中英双语，6B 参数 | $0.005/MP |
| `fal-ai/nano-banana-pro` | ~8s | Gemini 3 Pro、推理深度、文字渲染 | $0.15/张（1K） |
| `fal-ai/gpt-image-1.5` | ~15s | 提示词遵循度高 | $0.034/张 |
| `fal-ai/gpt-image-2` | ~20s | SOTA 级文字渲染 + 中日韩文字、具世界认知的写实 | $0.04–0.06/张 |
| `fal-ai/ideogram/v3` | ~5s | 排版最佳 | $0.03–0.09/张 |
| `fal-ai/recraft/v4/pro/text-to-image` | ~8s | 设计、品牌系统、可直接用于生产 | $0.25/张 |
| `fal-ai/qwen-image` | ~12s | 基于 LLM、复杂文字 | $0.02/MP |
| `fal-ai/krea/v2/medium/text-to-image` | ~15-25s | 插画、动漫、绘画、富有表现力的艺术风格 | $0.030–0.035/张 |
| `fal-ai/krea/v2/large/text-to-image` | ~25-60s | 写实、粗粝质感（运动模糊、颗粒、胶片） | $0.060–0.065/张 |

价格为撰写时 FAL 的定价；最新价格请以 [fal.ai](https://fal.ai/) 为准。

## 配置 {#setup}

:::tip Nous 订阅用户
若你持有付费 [Nous Portal](https://portal.nousresearch.com) 订阅，可通过 **[Tool Gateway](tool-gateway.md)** 使用文生图，无需 FAL API Key。你的模型选择在两条路径下保持一致。新安装可运行 `hermes setup --portal` 登录并一次性启用所有网关工具；已有安装可在 `hermes tools` 中选择 **Nous Subscription** 作为文生图后端。

若托管网关对某一模型返回 `HTTP 4xx`，说明该模型尚未在 Portal 侧代理——智能体会告知你，并给出处理步骤（在 `hermes tools` 中切换到 FAL.ai 并使用你自己的 `FAL_KEY` 直连，或换用其他模型）。
:::

### 获取 FAL API Key {#get-a-fal-api-key}

1. 在 [fal.ai](https://fal.ai/) 注册
2. 在控制台生成 API Key

### 配置并选择模型 {#configure-and-pick-a-model}

运行 tools 命令：

```bash
hermes tools
```

进入 **🎨 Image Generation**，选择后端（Nous Subscription 或 FAL.ai），随后选择器会以列对齐的表格列出所有支持的模型——用方向键移动，回车确认：

```
  Model                          Speed    Strengths                    Price
  fal-ai/flux-2/klein/9b         <1s      Fast, crisp text             $0.006/MP   ← currently in use
  fal-ai/flux-2-pro              ~6s      Studio photorealism          $0.03/MP
  fal-ai/z-image/turbo           ~2s      Bilingual EN/CN, 6B          $0.005/MP
  ...
```

你的选择会保存到 `config.yaml`：

```yaml
image_gen:
  provider: fal                 # 选 Nous Subscription 时为 `nous`
  model: fal-ai/flux-2/klein/9b
  max_parallel_requests: 4      # 单次工具调用批次中的并发图像数
```

`image_gen.provider` 是唯一的选择键：`nous` 经由托管的 Tool Gateway 路由；厂商名（`fal`、`openai`、`xai`、`krea` 等）则使用你自己的密钥直连。运行时始终遵循这一已保存的选择——`provider: nous` 时 `.env` 中的 `FAL_KEY` 会被忽略；`provider: fal` 而缺少 `FAL_KEY` 时会报错 `image_gen is configured to use fal (set via hermes tools), but FAL_KEY is not set. Run 'hermes tools' to change it.`，而不会静默改道。请通过 `hermes tools` 切换提供方，而不是靠增删密钥。（旧的 `use_gateway` 布尔值属于遗留配置——为 `true` 时仍按 `nous` 读取，但不会再被写入。）

`max_parallel_requests` 默认为 `4`。Hermes 会将其限制为至少 1，且不超过全局工具 worker 上限，因此图像提供方收到的并行请求是有界的，图像批次也无法绕过智能体的并发上限。

### OpenRouter：完整的 Image API 目录 {#openrouter-the-full-image-api-catalog}

设置 `image_gen.provider: openrouter` 时，模型选择器会列出 OpenRouter 完整的实时图像目录——专用
[Image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)
模型（Seedream、FLUX.2、Recraft、Qwen Image、MAI、Krea、Riverflow、Grok
Imagine 等，40 多个 id）与 chat-completions 图像模型合并在一起。
目录通过 `GET /images/models` 与 `GET /models` 实时拉取，因此 OpenRouter 一上线新模型，它就会出现在选择器中，无需更新 Hermes。
生成时会自动把每个模型路由到提供它的接口（专用的 `POST /images/generations` 或 chat-completions）。
Nous Portal 只代理 chat-completions 协议，因此其选择器提供的是经由 chat 提供的模型。

Image API 模型的可选单请求参数写在对应的作用域配置段下（或使用 `OPENROUTER_IMAGE_API_*` 环境变量）：

```yaml
image_gen:
  provider: openrouter
  model: bytedance-seed/seedream-4.5
  openrouter:
    resolution: 2K        # 取决于模型：1K / 2K / 4K
    quality: high         # gpt-image 模型
    output_format: png
```

### GPT-Image 画质 {#gpt-image-quality}

`fal-ai/gpt-image-1.5` 与 `fal-ai/gpt-image-2` 的请求画质固定为 `medium`（1024×1024 下约 $0.034–$0.06/张）。我们不向用户开放 `low` / `high` 档位，以便 Nous Portal 的计费在所有用户之间保持可预期——各档位之间的成本差距达 3–22×。若想要更便宜的选项，请选 Klein 9B 或 Z-Image Turbo；若想要更高画质，请使用 Nano Banana Pro 或 Recraft V4 Pro。

### Meta Model API：Muse Image {#meta-model-api-muse-image}

设置 `image_gen.provider: meta-ai` 时，图像通过
[Meta Model API](https://api.meta.ai)（`https://api.meta.ai/v1`）生成，这与提供 Muse Spark 聊天模型的是同一个 OpenAI 兼容端点。它是内置 `meta-ai` 聊天提供方的文生图搭档。

| 模型 | 速度 | 特点 | 价格 |
|---|---|---|---|
| `muse-image-1.0` *（默认）* | ~10s | Meta Model API 图像生成 | $0.01/张 |

```yaml
image_gen:
  provider: meta-ai
  model: muse-image-1.0
```

认证复用 Meta 聊天提供方的同一组环境变量——`MODEL_API_KEY`（Meta 文档中的名称），同时接受 `META_API_KEY` / `META_MODEL_API_KEY` 作为别名。设置 `META_BASE_URL` 可指向代理或其他主机。目前仅支持文生图；响应会保存到 `$HERMES_HOME/cache/images/`。

## FAL：GPT Image 2.5 {#fal-gpt-image-25}

在 `hermes tools` → Image Generation → FAL.ai 下选择 **GPT Image 2.5 Flare** 或 **GPT Image 2.5 Sunburst**。模型 ID 为：

- `openai/gpt-image-2.5/flare/text-to-image`
- `openai/gpt-image-2.5/sunburst/text-to-image`

例如：

```bash
hermes config set image_gen.provider fal
hermes config set image_gen.model openai/gpt-image-2.5/flare/text-to-image
```

提供 `image_url` 或参考图时，会自动选择对应的
`openai/gpt-image-2.5/flare/edit` 或 `openai/gpt-image-2.5/sunburst/edit` 端点。
两者都最多接受 16 张源图。Hermes 将画质固定为 `medium`，与其现有的 FAL GPT Image 策略一致，而非采用 FAL 成本更高的 `high` 默认值。
横向与纵向使用 4:3 预设以满足最小像素数要求；方形使用 `square_hd`。除非明确请求，否则不做超分。

FAL 按 token 计费，而非固定的单张价格：文本输入 $5/M，缓存文本输入 $1.25/M，文本输出 $10/M，图像输入 $8/M，缓存图像输入 $2/M，图像输出 $30/M，每次请求向上取整到 $0.0001。详见
[Flare](https://fal.ai/models/openai/gpt-image-2.5/flare/text-to-image) 与
[Sunburst](https://fal.ai/models/openai/gpt-image-2.5/sunburst/text-to-image)
页面。直连 FAL 需要已充值的 `FAL_KEY`；托管网关是否可用取决于该网关的端点白名单，FAL 上可用并不意味着网关可用。
现有的提供方与模型默认值保持不变。

## OpenAI API：GPT Image 2.5 {#openai-api-gpt-image-25}

**OpenAI** 提供方支持 GPT Image 2.5 Flare（快速日常创作）与 Sunburst（精准生成与编辑），使用 `OPENAI_API_KEY`。
可通过 `hermes tools` → Image Generation → OpenAI 选择，或设置：

```bash
hermes config set image_gen.provider openai
hermes config set image_gen.openai.model gpt-image-2.5-flare
```

`gpt-image-2.5-flare` 与 `gpt-image-2.5-sunburst` 使用自动画质。
追加 `-low`、`-medium`、`-high`、`-xhigh` 或 `-max` 可指定固定画质，例如 `gpt-image-2.5-sunburst-high`。两者都支持生成与编辑，最多可用 16 张参考图。现有的 GPT Image 2 选择以及
`gpt-image-2-medium` 默认值保持不变。

这属于付费 API 用量，与 ChatGPT/Codex 订阅无关。两个模型的价格均为：文本输入每百万 token $5，图像输入每百万 token $8，图像输出每百万 token $30（缓存输入分别为 $1.25 和 $2）。单张成本随用量而变；GPT Image 2 计算器不会估算 2.5 的 token 消耗。详见官方
[Flare](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare) 与
[Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst) 文档。

**OpenAI（Codex 认证）** 提供方仍是独立的：其后端可能接受某个图像模型取值却并不遵循该选择，因此仅凭成功生成一张图，并不能验证请求确实路由到了 Flare 或 Sunburst。这些选项通过直连 OpenAI API 提供方和 FAL 提供，而不是经过验证的 Codex 认证选项。

## 使用方式 {#usage}

面向智能体的 schema 刻意保持精简——模型会采用你配置好的任何设置：

```
Generate an image of a serene mountain landscape with cherry blossoms
```

```
Create a square portrait of a wise old owl — use the typography model
```

```
Make me a futuristic cityscape, landscape orientation
```

## 图生图 / 编辑 {#image-to-image--editing}

当所选模型支持时，同一个 `image_generate` 工具也能**编辑已有图像**——传入一张源图，后端会自动路由到其编辑端点（与 `video_generate` 处理图生视频的方式一致）。不传源图时，就是普通的文生图。

```
Take this photo and make it a rainy Tokyo street at night → <image>
```

```
Blend these two product shots into one hero image → <image1> <image2>
```

有两个输入驱动编辑：

- **`image_url`** —— 要编辑 / 变换的主源图（公开 URL 或本地路径）。
- **`reference_image_urls`** —— 额外的风格 / 构图参考图（按模型设有上限）。

### 哪些后端支持编辑 {#which-backends-support-editing}

| 后端 | 图生图 | 参考图上限 | 方式 |
|---|---|---|---|
| **FAL.ai**（下列支持编辑的模型） | ✓ | 最多 16 张（按模型） | 路由到该模型的 `/edit` 端点 |
| **OpenAI**（GPT Image 2 / 2.5 Flare / Sunburst） | ✓ | 最多 16 张 | `images.edit()` |
| **xAI**（Grok Imagine） | ✓ | 1 张 | `/v1/images/edits`（`grok-imagine-image-quality`） |
| **Krea**（`Krea 2`） | ✓ | 最多 10 张 | 参考图引导生成（`image_style_references`） |
| **OpenAI（Codex 认证）** | ✓ | 最多 16 张 | Codex Responses 的 `image_generation` 工具，配合 `input_image` 内容块 |
| **OpenRouter**（Image API 模型） | ✓ | 最多 14–16 张（按模型） | `POST /images/generations` 上的 `input_references`；经由 chat 提供的模型使用 `image_url` 内容块（最多 3 张） |

具备编辑端点的 FAL 模型：`flux-2/klein/9b`、`flux-2-pro`、
`nano-banana-pro`、`gpt-image-1.5`、`gpt-image-2`、`ideogram/v3` 和
`qwen-image`，以及上文的 GPT Image 2.5 Flare 与 Sunburst。纯文生图的 FAL 模型（`z-image/turbo`、`recraft`、
`krea/*`）会拒绝图像输入，并给出明确错误，引导你换用支持编辑的模型。

:::note OpenAI（Codex 认证）为尽力而为

Codex 接口（`chatgpt.com/backend-api/codex`）将 `image_generation` 作为聊天模型*可以*调用的工具托管，Hermes 无法强制其调用——对于托管工具，后端会拒绝任何形式的 `tool_choice`，因此请求只能依靠指令来引导模型。当宿主模型拒绝调用该工具时，调用会以 `empty_response` 失败。另有报告称，托管图像工具能否访问也因账户而异。如果你需要图像生成稳定可靠，请改为配置 **OpenAI**（API Key）、**FAL** 或 **xAI** 后端。

:::

当前模型的编辑能力会在运行时体现在工具描述中，因此智能体在调用工具之前就知道 `image_url` 是否会被采用。

## 宽高比 {#aspect-ratios}

从智能体视角，所有模型都接受同样的三种宽高比。在内部，各模型的原生尺寸参数会被自动填入：

| 智能体输入 | image_size（flux/z-image/qwen/recraft/ideogram） | aspect_ratio（nano-banana-pro） | image_size（gpt-image-1.5） | image_size（gpt-image-2） |
|---|---|---|---|---|
| `landscape` | `landscape_16_9` | `16:9` | `1536x1024` | `landscape_4_3`（1024×768） |
| `square` | `square_hd` | `1:1` | `1024x1024` | `square_hd`（1024×1024） |
| `portrait` | `portrait_16_9` | `9:16` | `1024x1536` | `portrait_4_3`（768×1024） |

GPT Image 2 映射到 4:3 预设而非 16:9，因为它的最小像素数为 655,360——`landscape_16_9` 预设（1024×576 = 589,824）会被拒绝。

该转换在 `_build_fal_payload()` 中完成——智能体代码无需了解各模型 schema 的差异。

## 超分（Upscaling） {#upscaling}

### 仅按需启用 {#opt-in-only}

默认情况下没有任何模型会做超分。现代图像模型原生输出即为最佳质量，而可用的超分器属于*创意*增强器（扩散重绘），可能细微地重绘内容——损伤渲染的文字、人脸与细节。仅当智能体显式请求时才会执行超分。

### `upscale` 参数（按调用启用） {#the-upscale-parameter-per-call-opt-in}

- `upscale: true` —— 在生成后串接一次高分辨率处理：

| 后端 | 超分器 |
|---|---|
| **FAL.ai** | Clarity Upscaler（2×，+$0.03/MP） |
| **Krea** | Krea Enhance（2×，上限 8K） |
| 其他后端 | 无超分器；返回原生分辨率 |

- `upscale: false` / 省略 —— 原生分辨率（默认）

`video_generate` 在 FAL 后端上也接受 `upscale: true`，会在生成后串接字节跳动的 **SeedVR2** 视频超分器（2×，输出视频 $0.001/MP）。

FAL 图像超分运行时使用以下设置：

| 设置 | 值 |
|---|---|
| 放大倍数 | 2× |
| Creativity | 0.35 |
| Resemblance | 0.6 |
| Guidance scale | 4 |
| Inference steps | 18 |

若超分失败（网络问题、限流），会自动返回原始图像。响应中会报告 `upscaled: true/false`，让智能体知道拿到的是哪种分辨率。

## 内部工作原理 {#how-it-works-internally}

1. **模型解析** —— `_resolve_fal_model()` 读取 `config.yaml` 中的 `image_gen.model`，否则回退到 `FAL_IMAGE_MODEL` 环境变量，再否则使用 `fal-ai/flux-2/klein/9b`。
2. **构造请求体** —— `_build_fal_payload()` 将你的 `aspect_ratio` 转换为模型的原生格式（预设枚举、宽高比枚举或 GPT 字面量），合并模型的默认参数，应用调用方的覆盖，再按模型的 `supports` 白名单过滤，确保不会发送不支持的键。
3. **提交** —— `_submit_fal_request()` 根据已保存的 `image_gen.provider` 选择，经由直连 FAL 凭据或托管的 Nous 网关路由。
4. **超分** —— 仅当智能体传入 `upscale: true` 时执行；所有模型的目录默认值均为关闭。
5. **交付** —— 最终图像 URL 返回给智能体，智能体发出 `MEDIA:<url>` 标签，由各平台适配器转换为原生媒体。

## 调试 {#debugging}

启用调试日志：

```bash
export IMAGE_TOOLS_DEBUG=true
```

调试日志写入 `./logs/image_tools_debug_<session_id>.json`，包含每次调用的详细信息（模型、参数、耗时、错误）。

## 平台投递 {#platform-delivery}

| 平台 | 投递方式 |
|---|---|
| **CLI** | 图像 URL 以 Markdown `![](url)` 打印——点击即可打开 |
| **Telegram** | 图片消息，以提示词作为说明文字 |
| **Discord** | 嵌入在消息中 |
| **Slack** | URL 由 Slack 展开预览 |
| **WhatsApp** | 媒体消息 |
| **其他** | 纯文本中的 URL |

## 限制 {#limitations}

- **需要当前后端对应的凭据**（FAL `FAL_KEY` / Nous 订阅、`OPENAI_API_KEY`、xAI OAuth、`KREA_API_KEY`）
- **编辑能力取决于模型** —— 图生图仅在支持编辑的模型上可用（见上表）；纯文生图模型会拒绝图像输入并给出明确错误
- **临时 URL** —— 后端返回的托管链接会在数小时至数天后过期；Hermes 会将其落盘到本地缓存，因此过期后仍可正常投递
- **按模型的限制** —— 部分模型不支持 `seed`、`num_inference_steps` 等参数。`supports` / `edit_supports` 过滤器会静默丢弃不支持的参数；这是预期行为
