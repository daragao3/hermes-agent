---
title: "LLM 与模型提供商"
sidebar_label: "AI 提供商"
description: "为 Hermes 配置推理提供商：云端 API、自托管端点，以及带回退的路由策略"
---

# LLM 与模型提供商

本页介绍如何为 Hermes Agent 配置推理提供商——从 OpenRouter、Anthropic 等云端 API，到 Ollama、vLLM 等自托管端点，再到高级路由与故障转移配置。使用 Hermes 至少需要配置一个提供商。

## 推理提供商

你需要至少一种方式连接到 LLM。使用 `hermes model` 交互式切换提供商和模型，或直接配置：

| 提供商 | 配置方式 |
|----------|-------|
| **Nous Portal** | `hermes model`（OAuth，订阅制） |
| **OpenAI Codex** | `hermes model` → **ChatGPT or Codex Subscription**（ChatGPT OAuth，使用 Codex 模型） |
| **GitHub Copilot** | `hermes model`（OAuth 设备码流程，`COPILOT_GITHUB_TOKEN`、`GH_TOKEN` 或 `gh auth token`） |
| **GitHub Copilot ACP** | `hermes model`（在本地生成 `copilot --acp --stdio` 子进程） |
| **Anthropic** | `hermes model`（Claude Max + 额外用量积分，通过 OAuth；也支持 Anthropic API key 或手动 setup-token——见下方说明） |
| **OpenRouter** | `~/.hermes/.env` 中的 `OPENROUTER_API_KEY` |
| **Ramp Router** | `~/.hermes/.env` 中的 `RAMP_ROUTER_API_KEY`（provider: `router`；别名：`ramp-router`、`ramp`、`router.com`；原生 Responses 网关，按账户范围提供实时目录） |
| **Fireworks AI** | `~/.hermes/.env` 中的 `FIREWORKS_API_KEY`（provider: `fireworks`；别名：`fireworks-ai`、`fw`） |
| **NovitaAI** | `~/.hermes/.env` 中的 `NOVITA_API_KEY`（provider: `novita`，200+ 模型，Model API、Agent Sandbox、GPU Cloud） |
| **AI Gateway** | `~/.hermes/.env` 中的 `AI_GATEWAY_API_KEY`（provider: `ai-gateway`） |
| **z.ai / GLM** | `~/.hermes/.env` 中的 `GLM_API_KEY`（provider: `zai`） |
| **Kimi / Moonshot** | `~/.hermes/.env` 中的 `KIMI_API_KEY`（provider: `kimi-coding`） |
| **Kimi / Moonshot（中国）** | `~/.hermes/.env` 中的 `KIMI_CN_API_KEY`（provider: `kimi-coding-cn`；别名：`kimi-cn`、`moonshot-cn`） |
| **Arcee AI** | `~/.hermes/.env` 中的 `ARCEEAI_API_KEY`（provider: `arcee`；别名：`arcee-ai`、`arceeai`） |
| **GMI Cloud** | `~/.hermes/.env` 中的 `GMI_API_KEY`（provider: `gmi`；别名：`gmi-cloud`、`gmicloud`） |
| **Nebius Token Factory** | `~/.hermes/.env` 中的 `NEBIUS_API_KEY`（provider: `nebius-token-factory`；别名：`nebius`、`nebius-tf`、`tokenfactory`） |
| **Actual Computer** | 托管中继使用 `~/.hermes/.env` 中的 `ACTUAL_API_KEY`，本地守护进程使用 `ACTUAL_BASE_URL=http://127.0.0.1:8080`——回环地址无需 key（provider: `actual`；别名：`actual-computer`、`actualcomputer`、`aci`） |
| **MiniMax** | `~/.hermes/.env` 中的 `MINIMAX_API_KEY`（provider: `minimax`） |
| **MiniMax 中国** | `~/.hermes/.env` 中的 `MINIMAX_CN_API_KEY`（provider: `minimax-cn`） |
| **xAI（Grok）— Responses API** | `~/.hermes/.env` 中的 `XAI_API_KEY`（provider: `xai`） |
| **xAI Grok OAuth（SuperGrok）** | `hermes model` → "xAI Grok OAuth (SuperGrok / Premium+)"——浏览器登录，无需 API key。参见[指南](../guides/xai-grok-oauth.md) |
| **Qwen Cloud（阿里 DashScope）** | `~/.hermes/.env` 中的 `DASHSCOPE_API_KEY`（provider: `alibaba`；中国大陆端点：`alibaba-cn`） |
| **阿里云（Coding Plan）** | `ALIBABA_CODING_PLAN_API_KEY`（回退到 `DASHSCOPE_API_KEY`）（provider: `alibaba-coding-plan`，别名：`alibaba_coding`；中国大陆端点：`alibaba-coding-plan-cn`，使用 `ALIBABA_CODING_PLAN_CN_API_KEY`，并回退到共享 key）——独立计费 SKU，不同端点 |
| **阿里云（Token Plan）** | `~/.hermes/.env` 中的 `ALIBABA_TOKEN_PLAN_API_KEY`（provider: `alibaba-token-plan`；中国大陆端点：`alibaba-token-plan-cn`，使用 `ALIBABA_TOKEN_PLAN_CN_API_KEY`，并回退到共享 key）——百炼（Model Studio）固定 token 档位 |
| **Kilo Code** | `~/.hermes/.env` 中的 `KILOCODE_API_KEY`（provider: `kilocode`） |
| **小米 MiMo** | `~/.hermes/.env` 中的 `XIAOMI_API_KEY`（provider: `xiaomi`，别名：`mimo`、`xiaomi-mimo`） |
| **腾讯 TokenHub** | `~/.hermes/.env` 中的 `TOKENHUB_API_KEY`（provider: `tencent-tokenhub`，别名：`tencent`、`tokenhub`、`tencentmaas`） |
| **腾讯 TokenPlan** | `~/.hermes/.env` 中的 `TOKENPLAN_API_KEY`（provider: `tencent-tokenplan`，别名：`tokenplan`、`tencent-lkeap`；Anthropic Messages 端点） |
| **OpenCode Zen** | `~/.hermes/.env` 中的 `OPENCODE_ZEN_API_KEY`（provider: `opencode-zen`） |
| **CommandCode** | `~/.hermes/.env` 中的 `COMMANDCODE_API_KEY`（provider: `commandcode`，别名：`commandcode-chat`；Claude 模型通过 `commandcode-anthropic`，别名：`commandcode-claude`）。适用于 GOAT/Pro/Max/Provider 计划（不适用于 $1 的 Go 计划——无 API 访问权限）。 |
| **OpenCode Go** | `~/.hermes/.env` 中的 `OPENCODE_GO_API_KEY`（provider: `opencode-go`） |
| **OpenCode Free** | 无需 key——不需要 API key 或账户（provider: `opencode-free`，别名：`free`、`opencode_free`）。通过 `hermes model` 或 `/model free` 选择；请求以匿名方式发送。模型列表会从 OpenCode 的实时目录自动刷新，因此轮换的免费推广模型会自动出现（下架的会自动消失），无需更新 Hermes |
| **DeepSeek** | `~/.hermes/.env` 中的 `DEEPSEEK_API_KEY`（provider: `deepseek`） |
| **Hugging Face** | `~/.hermes/.env` 中的 `HF_TOKEN`（provider: `huggingface`，别名：`hf`） |
| **Google / Gemini** | `~/.hermes/.env` 中的 `GOOGLE_API_KEY`（或 `GEMINI_API_KEY`）（provider: `gemini`） |
| **Google Vertex AI** | `hermes model` → "Google Vertex AI"（provider: `vertex`；通过服务账号 JSON 或 ADC 进行 OAuth2，使用 GCP 计费） |
| **OpenAI API（直连）** | `~/.hermes/.env` 中的 `OPENAI_API_KEY`（provider: `openai-api`，可选 `OPENAI_BASE_URL`） |
| **Azure AI Foundry** | `hermes model` → "Azure AI Foundry"（provider: `azure-foundry`；使用 Azure OpenAI / Foundry 端点和密钥） |
| **AWS Bedrock** | `hermes model` → "AWS Bedrock"（provider: `bedrock`；通过 boto3 使用标准 AWS 凭据链） |
| **NVIDIA Build** | `~/.hermes/.env` 中的 `NVIDIA_API_KEY`（provider: `nvidia`；build.nvidia.com 上的 NIM 托管模型） |
| **Ollama Cloud** | `hermes model` → "Ollama Cloud"（provider: `ollama-cloud`；云托管的 Ollama API） |
| **Qwen OAuth** | `hermes model` → "Qwen OAuth"（provider: `qwen-oauth`；浏览器 PKCE 登录） |
| **MiniMax OAuth** | `hermes model` → "MiniMax (OAuth)"（provider: `minimax-oauth`；浏览器 PKCE 登录） |
| **StepFun** | `~/.hermes/.env` 中的 `STEPFUN_API_KEY`（provider: `stepfun`） |
| **LM Studio** | `hermes model` → "LM Studio"（provider: `lmstudio`，可选 `LM_API_KEY`） |
| **自定义端点** | `hermes model` → 选择"Custom endpoint"（保存在 `config.yaml`） |

三个 OpenCode 提供商都会在每个请求上发送一个不透明的、按对话生成的 `x-opencode-session` 请求头（所有传输上的主轮次，以及压缩、标题生成等辅助调用）。OpenCode 用它把一次对话固定到同一个后端，从而保持 prompt 缓存处于热状态；该值由 Hermes 会话 ID 派生，不包含任何个人数据。

官方 API key 路径请参见专属的 [Google Gemini 指南](/guides/google-gemini)。

:::tip 模型 key 别名
在 `model:` 配置节中，可以使用 `default:` 或 `model:` 作为模型 ID 的键名。`model: { default: my-model }` 和 `model: { model: my-model }` 效果完全相同。
:::


### Nous Portal

[Nous Portal](https://portal.nousresearch.com) 是 Nous Research 的统一订阅网关，也是**运行 Hermes Agent 的推荐方式**。一次 OAuth 登录即可访问 300+ 前沿智能体模型（Claude、GPT、Gemini、DeepSeek、Qwen、Kimi、GLM、MiniMax、Grok 等）以及 [Tool Gateway](/user-guide/features/tool-gateway)（网页搜索、图像生成、TTS、浏览器自动化）——费用从你的 Nous 订阅中扣除，无需单独管理各提供商账户。

```bash
hermes setup --portal     # 全新安装——一条命令完成 OAuth + 提供商 + 网关配置
hermes model              # 已有安装——从列表中选择"Nous Portal"
hermes portal info        # 随时查看登录状态和路由信息
```

还没有订阅？前往 [portal.nousresearch.com/manage-subscription](https://portal.nousresearch.com/manage-subscription) 购买。

**完整详情：** 参见专属的 [Nous Portal 集成页面](/integrations/nous-portal)（订阅内容、模型目录、故障排查）以及分步指南[使用 Nous Portal 运行 Hermes Agent](/guides/run-hermes-with-nous-portal)。

**客户端标识。** Hermes Agent 发出的每一个 Portal 请求都会携带 `client=hermes-client-v<version>` 标签（例如 `client=hermes-client-v0.13.0`），并自动与你安装的版本对齐。所有 Portal 路径都会发送该标签——主聊天循环、辅助调用、压缩摘要器、网页提取——从而让 Portal 端的遥测能够把 Hermes 流量与其他客户端区分开。无需任何配置；执行 `hermes update` 后标签会自动更新。

**JWT 认证（自动）。** Hermes 在 Portal 请求中优先使用带 `inference:invoke` 作用域的 JWT，并以旧版不透明会话密钥路径作为回退。无需任何配置——凭据由 OAuth 流程管理并透明轮换。被撤销的刷新 token 会被隔离，以避免重放循环。


:::info Codex 说明
OpenAI Codex 提供商通过设备码（device code）认证——打开一个 URL 并输入验证码。Hermes 将生成的凭据存储在 `~/.hermes/auth.json` 的自有认证存储中，并在存在 `~/.codex/auth.json` 时可导入现有的 Codex CLI 凭据。无需安装 Codex CLI。

如果 token 刷新因终端错误（HTTP 4xx、`invalid_grant`、授权被撤销等）失败，Hermes 会将该刷新 token 标记为失效并停止重试，避免出现大量重复的认证失败。下一次请求会显示类型化的重新认证提示。运行 `hermes auth add openai-codex`（或 `hermes model` → **ChatGPT or Codex Subscription**）开始新的设备码登录；成功交换后隔离状态自动解除。

在 Python/OpenSSL 3.5+ 上，如果网络中间设备拒绝 X25519MLKEM768 等后量子密钥交换组，设备码登录可能报 `[SSL: UNEXPECTED_EOF_WHILE_READING]` 或 TLS 握手超时（此时 curl 仍可能正常）。Hermes 不会修改默认 TLS 策略。请在运行 `hermes model` 前将 `OPENSSL_CONF` 指向一个把 `Groups` 限制为经典曲线的配置文件，或用 TLS 1.2 进行诊断：

```ini
openssl_conf = openssl_init

[openssl_init]
ssl_conf = ssl_sect

[ssl_sect]
system_default = system_default_sect

[system_default_sect]
Groups = x25519:secp256r1:secp384r1:x448
```
:::

:::warning
即使使用 Nous Portal、Codex 或自定义端点，某些工具（视觉、网页摘要、MoA）仍会使用单独的"辅助"模型。默认情况下（`auxiliary.*.provider: "auto"`），Hermes 将这些任务路由到你的**主聊天模型**——即你在 `hermes model` 中选择的同一模型。你可以单独覆盖每个任务，将其路由到更便宜/更快的模型（例如 OpenRouter 上的 Gemini Flash）——参见[辅助模型](/user-guide/configuration#auxiliary-models)。
:::

:::tip Nous Tool Gateway
付费 Nous Portal 订阅者还可访问 **[Tool Gateway](/user-guide/features/tool-gateway)**——网页搜索、图像生成、TTS 和浏览器自动化，均通过你的订阅路由。无需额外 API key。全新安装时，`hermes setup --portal` 一条命令即可完成登录、设置 Nous 为提供商并开启网关。现有用户可通过 `hermes model` 或 `hermes tools` 按工具启用。随时使用 `hermes portal info` 查看路由状态。
:::

### 模型管理的两个命令

Hermes 有**两个**模型命令，用途不同：

| 命令 | 运行位置 | 功能 |
|---------|-------------|--------------|
| **`hermes model`** | 终端（任何会话之外） | 完整配置向导——添加提供商、运行 OAuth、输入 API key、配置端点 |
| **`/model`** | Hermes 聊天会话内部 | 在**已配置的**提供商和模型之间快速切换 |

如果你想切换到尚未配置的提供商（例如你只配置了 OpenRouter，想使用 Anthropic），需要使用 `hermes model`，而不是 `/model`。先退出会话（`Ctrl+C` 或 `/quit`），运行 `hermes model`，完成提供商配置，然后开启新会话。


### 订阅计划：你的计划为哪些用量付费 {#subscription-plans-what-your-plan-pays-for}

有几个提供商允许你用**消费级订阅**（Claude Max、ChatGPT、SuperGrok / X Premium+ 等）而非 API key 登录 Hermes。这些订阅实际覆盖什么、不覆盖什么，因提供商而异，这也是最常见的账单意外来源。下表是简要版本；各提供商自己的章节有详细说明。

> 标记为*当前未记录*的单元格正是字面意思：Hermes 文档尚未说明该行为。不要自行假设——请查看提供商的账单面板，并将这些视为待解问题。

| 计划 / 路径 | Hermes 能否使用？ | 会消耗什么 | 不会消耗什么 | 常见意外 |
|---|---|---|---|---|
| **Anthropic — Claude Max + OAuth** | ✅ 可以——`hermes model` → Anthropic OAuth。需要 Max **且**已购买额外用量积分 | 你在 Max 计划之上额外购买的**额外/超额积分** | **Max 基础计划配额**（Claude Code 默认包含的用量） | 即使 Max 包含的配额原封未动，所有 Hermes 用量也都按"额外用量"计费 |
| **Anthropic — Claude Pro** | ❌ 不可以——Pro 订阅者无法使用 OAuth 路径 | 无（路径不可用） | 你的 Pro 订阅 | Pro 看起来应该能用，但实际不行。请改用 `ANTHROPIC_API_KEY`（按 token 计费，与任何 Claude 订阅无关） |
| **OpenAI Codex — ChatGPT 计划 OAuth** | ✅ 可以——`hermes model` → **ChatGPT or Codex Subscription**（ChatGPT OAuth 设备码登录，使用 Codex 模型） | *当前未记录* | *当前未记录* | 文档只涵盖认证和 token 刷新；计划配额语义尚未记录 |
| **xAI — SuperGrok / X Premium+ OAuth** | ✅ 可以——浏览器 OAuth，无需 API key | 你的**订阅配额**（X Search 有明确记录：OAuth 优先于 API key，并且"使用你的订阅配额而非 API 支出"）。除此之外的推理配额语义：*当前未记录* | 配置了 OAuth 凭据并优先使用时，不消耗 `XAI_API_KEY` / 按 token 计费的 API 支出 | 登录成功后出现 `HTTP 403`——尽管应用内订阅有效，xAI 仍将 OAuth API 访问限制在特定的 SuperGrok 档位 |
| **Google — Gemini 消费级计划（Google AI Pro / Ultra）** | ❌ 没有已记录的路径——`gemini` 提供商仅支持 API key（`GOOGLE_API_KEY` / `GEMINI_API_KEY`）；Vertex AI 使用 GCP 计费 | 你的 **API key 配额**（免费档或已启用计费的 Google Cloud 项目）——*消费级计划的消耗当前未记录* | *当前未记录* | 免费档 key 可能在几轮智能体交互后就被耗尽，因为 Hermes 每个用户轮次可能发起多次模型调用 |

**Anthropic。** OAuth 路径以 Claude Code 身份路由到你的 Anthropic 账户，**仅在 Claude Max 计划且已购买额外用量积分时有效**——Hermes 永远不会消耗 Max 基础配额，只会消耗在其之上的额外/超额积分。Claude Pro 订阅者无法使用此路径；受支持的替代方案是 `ANTHROPIC_API_KEY`，按标准 API 定价按 token 计费，从该 key 所属组织扣费。参见下方的 [Anthropic（原生）](#anthropic-native)。

**OpenAI Codex。** Hermes 通过 ChatGPT 设备码 OAuth 认证，将凭据存储在 `~/.hermes/auth.json`，并可从 `~/.codex/auth.json` 导入现有的 Codex CLI 凭据。哪些 ChatGPT 计划档位符合条件、Hermes 用量如何计入你计划的 Codex 限额，**当前均未记录**——[Nous Portal](#nous-portal) 下的 Codex 说明只涵盖认证和 token 刷新行为。

**xAI（SuperGrok / X Premium+）。** 浏览器 OAuth 适用于有效的 SuperGrok 订阅，或关联 X 账户上的 X Premium+ 订阅；同一 bearer token 会被 xAI 直连工具（TTS、图像生成、视频生成、转录、X Search）复用。如果登录成功后推理返回 `HTTP 403`，那是 xAI 端的档位/权益限制，而不是 token 过期——变通方法是改用 `XAI_API_KEY`。参见下方的 [xAI（Grok）](#xai-grok--responses-api--prompt-caching) 以及 [xAI Grok OAuth 指南](../guides/xai-grok-oauth.md)。

**Google Gemini。** 目前无法用 Gemini 消费级订阅登录 Hermes——`gemini` 提供商使用 API key，而 [Google Vertex AI](#google-vertex-ai) 计费到你的 GCP 项目。智能体使用建议启用计费的 Google Cloud 项目；免费档配额对长时间运行的智能体会话来说太小。参见 [Google Gemini 指南](/guides/google-gemini)。

:::tip 一个订阅代替五个
如果你完全不想追踪各提供商的计划语义，[Nous Portal](#nous-portal) 用一个订阅、一次 OAuth 登录即可覆盖 300+ 模型。
:::

### Anthropic（原生） {#anthropic-native}

通过 Anthropic API 直接使用 Claude 模型——无需 OpenRouter 代理。支持三种认证方式：

当未选择显式的环境凭据时，凭据池中由 Hermes 自有的 OAuth 授权优先于借用的 Claude Code 登录。当没有可用的自有 OAuth 授权时，借用的登录仍作为回退。辅助认证恢复会刷新失败请求所使用的那个凭据，而不是某个无关的环境登录；否则轮换借用的登录可能会使其所有者的刷新 token 失效。

:::caution 需要 Claude Max"额外用量"积分
通过 `hermes model` → Anthropic OAuth（或 `hermes auth add anthropic --type oauth`）认证时，Hermes 以 Claude Code 身份路由到你的 Anthropic 账户。**仅当你订阅了 Claude Max 计划且购买了额外用量积分时才有效。** Claude Max 基础计划的配额（Claude Code 默认包含的用量）不会被 Hermes 消耗——只有你额外购买的超额积分才会被使用。Claude Pro 订阅者无法使用此路径。

如果你没有 Max + 额外积分，请改用 `ANTHROPIC_API_KEY`——请求将按 token 计费，从该 key 所属组织扣费（标准 API 定价，与任何 Claude 订阅无关）。
:::

```bash
# 使用 API key（按 token 计费）
export ANTHROPIC_API_KEY=***
hermes chat --provider anthropic --model claude-sonnet-4-6

# 推荐：通过 `hermes model` 认证
# 如果已使用 Claude Code，Hermes 会直接使用其凭据存储
hermes model

# 使用 setup-token 手动覆盖（备用/旧版）
export ANTHROPIC_TOKEN=***  # setup-token 或手动 OAuth token
hermes chat --provider anthropic

# 自动检测 Claude Code 凭据（如果你已使用 Claude Code）
hermes chat --provider anthropic  # 自动读取 Claude Code 凭据文件
```

通过 `hermes model` 选择 Anthropic OAuth 时，Hermes 优先使用 Claude Code 自身的凭据存储，而不是将 token 复制到 `~/.hermes/.env`。这样可以保持 Claude 凭据的可刷新性。

或永久设置：
```yaml
model:
  provider: "anthropic"
  default: "claude-sonnet-4-6"
```

:::tip 别名
`--provider claude` 和 `--provider claude-code` 也可作为 `--provider anthropic` 的简写。
:::

### GitHub Copilot

Hermes 以一等提供商身份支持 GitHub Copilot，提供两种模式：

**`copilot` — 直连 Copilot API**（推荐）。使用你的 GitHub Copilot 订阅，通过 Copilot API 访问 GPT-5.x、Claude、Gemini 等模型。

```bash
hermes chat --provider copilot --model gpt-5.4
```

**认证选项**（按以下顺序检查）：

1. `COPILOT_GITHUB_TOKEN` 环境变量
2. `GH_TOKEN` 环境变量
3. `GITHUB_TOKEN` 环境变量
4. `gh auth token` CLI 回退

如果未找到 token，`hermes model` 会提供 **OAuth 设备码登录**——与 Copilot CLI 和 opencode 使用的流程相同。

:::warning Token 类型
Copilot API **不**支持经典个人访问 token（`ghp_*`）。支持的 token 类型：

| 类型 | 前缀 | 获取方式 |
|------|--------|------------|
| OAuth token | `gho_` | `hermes model` → GitHub Copilot → 使用 GitHub 登录 |
| 细粒度 PAT | `github_pat_` | GitHub 设置 → 开发者设置 → 细粒度 token（需要 **Copilot Requests** 权限） |
| GitHub App token | `ghu_` | 通过 GitHub App 安装获取 |

如果你的 `gh auth token` 返回 `ghp_*` token，请使用 `hermes model` 通过 OAuth 认证。
:::

:::info Hermes 中的 Copilot 认证行为
Hermes 将支持的 GitHub token（`gho_*`、`github_pat_*` 或 `ghu_*`）直接发送到 `api.githubcopilot.com`，并附带 Copilot 专用请求头（`Editor-Version`、`Copilot-Integration-Id`、`Openai-Intent`、`x-initiator`）。

收到 HTTP 401 时，Hermes 在回退前会执行一次性凭据恢复：

1. 通过正常优先级链重新解析 token（`COPILOT_GITHUB_TOKEN` → `GH_TOKEN` → `GITHUB_TOKEN` → `gh auth token`）
2. 使用刷新后的请求头重建共享 OpenAI 客户端
3. 重试请求一次

部分旧版社区代理使用 `api.github.com/copilot_internal/v2/token` 交换流程。该端点对某些账户类型可能不可用（返回 404）。因此 Hermes 以直接 token 认证为主路径，依靠运行时凭据刷新 + 重试保证健壮性。
:::

**API 路由**：GPT-5+ 模型（`gpt-5-mini` 除外）自动使用 Responses API。其他所有模型（GPT-4o、Claude、Gemini 等）使用 Chat Completions。模型从 Copilot 实时目录自动检测。

**`copilot-acp` — Copilot ACP 智能体后端**。将本地 Copilot CLI 作为子进程启动：

```bash
hermes chat --provider copilot-acp --model copilot-acp
# 需要 PATH 中存在 GitHub Copilot CLI 且已完成 `copilot login`
```

**永久配置：**
```yaml
model:
  provider: "copilot"
  default: "gpt-5.4"
```

| 环境变量 | 说明 |
|---------------------|-------------|
| `COPILOT_GITHUB_TOKEN` | Copilot API 的 GitHub token（最高优先级） |
| `HERMES_COPILOT_ACP_COMMAND` | 覆盖 Copilot CLI 二进制路径（默认：`copilot`） |
| `HERMES_COPILOT_ACP_ARGS` | 覆盖 ACP 参数（默认：`--acp --stdio`） |

### 一等 API Key 提供商

这些提供商内置支持，具有专属提供商 ID。设置 API key 后使用 `--provider` 选择：

```bash
# Fireworks AI
hermes chat --provider fireworks --model accounts/fireworks/models/kimi-k2p6
# 需要：~/.hermes/.env 中的 FIREWORKS_API_KEY

# NovitaAI Model API
hermes chat --provider novita --model moonshotai/kimi-k2.5
# 需要：~/.hermes/.env 中的 NOVITA_API_KEY

# Ramp Router（模型 ID 来自你账户的实时目录）
hermes chat --provider router --model gpt-5.4-mini
# 需要：~/.hermes/.env 中的 RAMP_ROUTER_API_KEY

# z.ai / ZhipuAI GLM
hermes chat --provider zai --model glm-5
# 需要：~/.hermes/.env 中的 GLM_API_KEY

# Kimi / Moonshot AI（国际版：api.moonshot.ai）
hermes chat --provider kimi-coding --model kimi-for-coding
# 需要：~/.hermes/.env 中的 KIMI_API_KEY

# Kimi / Moonshot AI（中国版：api.moonshot.cn）
hermes chat --provider kimi-coding-cn --model kimi-k2.5
# 需要：~/.hermes/.env 中的 KIMI_CN_API_KEY

# MiniMax（全球端点）
hermes chat --provider minimax --model MiniMax-M2.7
# 需要：~/.hermes/.env 中的 MINIMAX_API_KEY

# MiniMax（中国端点）
hermes chat --provider minimax-cn --model MiniMax-M2.7
# 需要：~/.hermes/.env 中的 MINIMAX_CN_API_KEY

# Qwen Cloud / DashScope（Qwen 模型）
hermes chat --provider alibaba --model qwen3.5-plus
# 需要：~/.hermes/.env 中的 DASHSCOPE_API_KEY

# 小米 MiMo
hermes chat --provider xiaomi --model mimo-v2-pro
# 需要：~/.hermes/.env 中的 XIAOMI_API_KEY

# 腾讯 TokenHub（Hy4 preview）
hermes chat --provider tencent-tokenhub --model hy4-preview
# 需要：~/.hermes/.env 中的 TOKENHUB_API_KEY

# 腾讯 TokenPlan（通过 Anthropic Messages 端点使用 Hy4 preview）
hermes chat --provider tencent-tokenplan --model hy4-preview
# 需要：~/.hermes/.env 中的 TOKENPLAN_API_KEY

# Arcee AI（Trinity 模型）
hermes chat --provider arcee --model trinity-large-thinking
# 需要：~/.hermes/.env 中的 ARCEEAI_API_KEY

# Meta Model API（Muse Spark 系列）
hermes chat --provider meta-ai --model muse-spark-1.2
# 需要：~/.hermes/.env 中的 MODEL_API_KEY

# GMI Cloud
# 使用 GMI /v1/models 端点返回的精确模型 ID。
hermes chat --provider gmi --model zai-org/GLM-5.1-FP8
# 需要：~/.hermes/.env 中的 GMI_API_KEY

# Nebius Token Factory
hermes chat --provider nebius --model deepseek-ai/DeepSeek-V4-Pro
# 需要：~/.hermes/.env 中的 NEBIUS_API_KEY
```

Fireworks 使用其原生的斜杠形式目录 ID，例如 `accounts/fireworks/models/kimi-k2p6`。运行 `hermes model`，选择 **Fireworks AI**，然后从实时目录中选择，或输入另一个 Fireworks 模型 ID。默认端点是 `https://api.fireworks.ai/inference/v1`；如需配置其他端点，请通过 `config.yaml` 中的 `model.base_url`，而不是 `.env`。

或在 `config.yaml` 中永久设置提供商：
```yaml
model:
  provider: "gmi"
  default: "zai-org/GLM-5.1-FP8"
```

基础 URL 可通过 `NOVITA_BASE_URL`、`GLM_BASE_URL`、`KIMI_BASE_URL`、`MINIMAX_BASE_URL`、`MINIMAX_CN_BASE_URL`、`DASHSCOPE_BASE_URL`、`XIAOMI_BASE_URL`、`GMI_BASE_URL`、`META_BASE_URL` 或 `TOKENHUB_BASE_URL` 环境变量覆盖。

:::note Meta 贡献者档位
`muse-spark-1.2-contributor` 和 `muse-spark-1.3-contributor` 是 Meta 的贡献者档位——Meta 可能会用你的提示和补全内容进行训练，因此在使用其中任何一个之前，[交互式模型选择会要求确认](../user-guide/configuring-models.md)。当前定价和速率限制请参见 [Meta Model API 定价与速率限制](https://dev.meta.ai/docs/pricing-rate-limits/)。处理机密工作时，请使用标准的 `muse-spark-1.2` / `muse-spark-1.3`（不用于训练）。
:::

:::note Z.AI 端点自动检测
使用 Z.AI / GLM 提供商时，Hermes 会自动探测多个端点（全球版、中国版、编程版）以找到接受你 API key 的端点。无需手动设置 `GLM_BASE_URL`——可用端点会被自动检测并缓存。
:::

### xAI（Grok）— Responses API + Prompt 缓存 {#xai-grok--responses-api--prompt-caching}

xAI 通过 Responses API（`codex_responses` 传输）接入，自动支持 Grok 4 模型的推理——无需 `reasoning_effort` 参数，服务端默认进行推理。在 `~/.hermes/.env` 中设置 `XAI_API_KEY` 并在 `hermes model` 中选择 xAI，或直接用 `grok` 作为快捷方式输入 `/model grok-4-fast-reasoning`。

SuperGrok 和 X Premium+ 订阅者可以用浏览器 OAuth 登录，无需 API key——在 `hermes model` 中选择 **xAI Grok OAuth (SuperGrok / Premium+)**，或运行 `hermes auth add xai-oauth`。同一 OAuth bearer token 会被 xAI 直连工具（TTS、图像生成、视频生成、转录）自动复用。完整流程参见 [xAI Grok OAuth 指南](../guides/xai-grok-oauth.md)——如果 Hermes 运行在远程主机上，还需参见 [SSH / 远程主机上的 OAuth](../guides/oauth-over-ssh.md) 了解所需的 `ssh -L` 隧道配置。

使用 xAI 作为提供商时（任何包含 `x.ai` 的基础 URL），Hermes 会在每次 API 请求中自动发送 `x-grok-conv-id` 请求头以启用 prompt（提示词）缓存。这会将同一会话的请求路由到同一服务器，使 xAI 基础设施能够复用已缓存的系统 prompt 和对话历史。

无需任何配置——检测到 xAI 端点且存在会话 ID 时，缓存自动激活。这可降低多轮对话的延迟和成本。

xAI 还提供专属 TTS 端点（`/v1/tts`）。在 `hermes tools` → 语音与 TTS 中选择 **xAI TTS**，或参见[语音与 TTS](../user-guide/features/tts.md#text-to-speech) 页面了解配置。

**已退役 xAI 模型的迁移（2026 年 5 月 15 日）：** xAI 将于 2026-05-15 退役 `grok-4*`、`grok-3`、`grok-code-fast-1` 和 `grok-imagine-image-pro`。`hermes doctor` 和 `hermes chat` 启动时都会检测仍指向已退役引用的配置，并打印推荐的替代项。使用 `hermes migrate xai` 可一次性重写配置——默认是 dry-run，加上 `--apply` 才会写入更改（会先将旧配置的带时间戳副本写入 `backups/config/`）。

```bash
hermes migrate xai          # preview replacements
hermes migrate xai --apply  # rewrite ~/.hermes/config.yaml in place
```

**xAI 网页搜索后端。**启用[网页搜索](../user-guide/features/web-search.md)工具集后，`web.backend: xai` 会使用相同的 `XAI_API_KEY` / OAuth 凭据，把搜索路由到 xAI 托管的搜索端点。如果 xAI 已配置为提供商，则无需额外设置。

### NovitaAI

[NovitaAI](https://novita.ai) 是面向开发者和智能体的 AI 原生云平台。三条产品线：200+ 模型的 Model API、用于构建和运行 AI 智能体的 Agent Sandbox，以及可扩展计算的 GPU Cloud，均可从同一平台访问。

```bash
# 使用任意可用模型
hermes chat --provider novita --model moonshotai/kimi-k2.5
# 需要：~/.hermes/.env 中的 NOVITA_API_KEY

# 短别名
hermes chat --provider novita-ai --model deepseek/deepseek-v3-0324
```

或在 `config.yaml` 中永久设置：
```yaml
model:
  provider: "novita"
  default: "moonshotai/kimi-k2.5"
  base_url: "https://api.novita.ai/openai/v1"
```

在 [novita.ai/settings/key-management](https://novita.ai/settings/key-management) 获取 API key。基础 URL 可通过 `NOVITA_BASE_URL` 覆盖。

### Ollama Cloud — 托管 Ollama 模型，OAuth + API Key

[Ollama Cloud](https://ollama.com/cloud) 托管与本地 Ollama 相同的开源模型目录，无需 GPU。在 `hermes model` 中选择 **Ollama Cloud**，粘贴来自 [ollama.com/settings/keys](https://ollama.com/settings/keys) 的 API key，Hermes 会自动发现可用模型。

```bash
hermes model
# → 选择"Ollama Cloud"
# → 粘贴你的 OLLAMA_API_KEY
# → 从已发现的模型中选择（gpt-oss:120b、glm-4.6:cloud、qwen3-coder:480b-cloud 等）
```

或直接编辑 `config.yaml`：
```yaml
model:
  provider: "ollama-cloud"
  default: "gpt-oss:120b"
```

模型目录从 `ollama.com/v1/models` 动态获取，缓存一小时。`model:tag` 格式（如 `qwen3-coder:480b-cloud`）在规范化过程中保留——不要使用连字符。

:::tip Ollama Cloud 与本地 Ollama
两者使用相同的 OpenAI 兼容 API。Cloud 是一等提供商（`--provider ollama-cloud`，`OLLAMA_API_KEY`）；本地 Ollama 通过自定义端点流程访问（基础 URL `http://localhost:11434/v1`，无需 key）。对于无法在本地运行的大模型使用 Cloud；对于隐私保护或离线工作使用本地。
:::

### AWS Bedrock

通过 AWS Bedrock 使用 Anthropic Claude、Amazon Nova、DeepSeek v3.2、Meta Llama 4 等模型。使用 AWS SDK（`boto3`）凭据链——无需 API key，使用标准 AWS 认证即可。

```bash
# 最简方式——~/.aws/credentials 中的命名 profile
hermes chat --provider bedrock --model us.anthropic.claude-sonnet-4-6

# 或使用显式环境变量
AWS_PROFILE=myprofile AWS_REGION=us-east-1 hermes chat --provider bedrock --model us.anthropic.claude-sonnet-4-6
```

或在 `config.yaml` 中永久设置：
```yaml
model:
  provider: "bedrock"
  default: "us.anthropic.claude-sonnet-4-6"
bedrock:
  region: "us-east-1"          # 或设置 AWS_REGION
  # profile: "myprofile"       # 或设置 AWS_PROFILE
  # discovery: true            # 从 IAM 自动发现区域
  # guardrail:                 # 可选的 Bedrock Guardrails
  #   guardrail_identifier: "your-guardrail-id"
  #   guardrail_version: "DRAFT"
```

认证使用标准 boto3 链：显式 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`、`~/.aws/credentials` 中的 `AWS_PROFILE`、EC2/ECS/Lambda 上的 IAM 角色、IMDS 或 SSO。如果已通过 AWS CLI 认证，无需设置任何环境变量。

Bedrock 底层使用 **Converse API**——请求被转换为 Bedrock 的模型无关格式，因此同一配置适用于 Claude、Nova、DeepSeek 和 Llama 模型。仅在调用非默认区域端点时才需设置 `BEDROCK_BASE_URL`。

参见 [AWS Bedrock 指南](/guides/aws-bedrock)，了解 IAM 配置、区域选择和跨区域推理的详细步骤。

### Google Vertex AI

通过 Vertex 的 OpenAI 兼容端点使用 Google Cloud Vertex AI 上的 Gemini 模型。认证方式为 **OAuth2**——由服务账号 JSON 或应用默认凭据（ADC）签发的短期访问 token（约 1 小时）。**没有静态 API key**；Hermes 会为你签发并自动刷新 token，包括在会话中途遇到 `401` 时重新签发。

```bash
# Service account JSON (recommended for servers / gateways)
echo "VERTEX_CREDENTIALS_PATH=/path/to/service-account.json" >> ~/.hermes/.env
# or Application Default Credentials
gcloud auth application-default login

hermes model   # → "Google Vertex AI" → project → region → model
```

或在 `config.yaml` 中配置（project/region 属于非机密信息，放在这里；凭据路径仍留在 `.env` 中）：
```yaml
model:
  provider: "vertex"
  default: "google/gemini-3-flash-preview"   # Vertex requires the google/ prefix
vertex:
  project_id: "my-gcp-project"   # blank → use the project embedded in the credentials
  region: "global"               # required for the Gemini 3.x previews
```

`VERTEX_PROJECT_ID` / `VERTEX_REGION` 环境变量会覆盖 `config.yaml` 中的值。Hermes 会在首次使用时惰性安装 `google-auth`；如果托管安装需要修复，请运行 `hermes setup`。完整步骤参见 [Google Vertex AI 指南](/guides/google-vertex)；若想改用静态 API key 的 AI Studio 路径，请参见 [Google Gemini 指南](/guides/google-gemini)。

### Qwen Portal（OAuth）

阿里巴巴 Qwen Portal，支持基于浏览器的 OAuth 登录。在 `hermes model` 中选择 **Qwen OAuth (Portal)**，通过浏览器登录，Hermes 会持久化刷新 token。

```bash
hermes model
# → 选择"Qwen OAuth (Portal)"
# → 浏览器打开；使用阿里巴巴账户登录
# → 确认——凭据保存到 ~/.hermes/auth.json

hermes chat   # 使用 portal.qwen.ai/v1 端点
```

或配置 `config.yaml`：
```yaml
model:
  provider: "qwen-oauth"
  default: "qwen3-coder-plus"
```

仅在 portal 端点迁移时才需设置 `HERMES_QWEN_BASE_URL`（默认：`https://portal.qwen.ai/v1`）。

:::tip Qwen OAuth 与 Qwen Cloud（阿里 DashScope）
`qwen-oauth` 使用面向消费者的 Qwen Portal，通过 OAuth 登录——适合个人用户。`alibaba` 提供商使用 Qwen Cloud（阿里 DashScope），需要 `DASHSCOPE_API_KEY`——适合程序化/生产工作负载。两者都路由到 Qwen 系列模型，但端点不同。
:::

### 阿里云（Coding Plan）

如果你订阅了阿里巴巴的 **Coding Plan**（独立于标准 DashScope API 访问的计费 SKU），Hermes 将其作为独立的一等提供商暴露：`alibaba-coding-plan`。端点：`https://coding-intl.dashscope.aliyuncs.com/v1`。与常规 `alibaba` 提供商一样兼容 OpenAI，但基础 URL 和计费面不同。

```yaml
model:
  provider: alibaba_coding     # alibaba-coding-plan 的别名
  model: qwen3-coder-plus
```

或通过 CLI：

```bash
hermes chat --provider alibaba_coding --model qwen3-coder-plus
```

`alibaba_coding` 使用与 `alibaba` 条目相同的 `DASHSCOPE_API_KEY`——无需单独的 key，只是路由目标不同。在此提供商注册之前，在 `config.yaml` 中设置 `provider: alibaba_coding` 的用户会静默回退到 OpenRouter 路由。

如需使用中国大陆端点（`alibaba-coding-plan-cn`，`https://coding.dashscope.aliyuncs.com/v1`），请设置 `ALIBABA_CODING_PLAN_CN_API_KEY`。CN 提供商仍会回退到 `ALIBABA_CODING_PLAN_API_KEY` / `DASHSCOPE_API_KEY`，但如果只设置了共享 key，`/model` 选择器只会列出国际版条目——设置 CN key（或在 `config.yaml` 中设置 `provider: alibaba-coding-plan-cn`）才会显示 CN 条目。`alibaba-token-plan-cn` 与 `ALIBABA_TOKEN_PLAN_CN_API_KEY` 同理。

### MiniMax（OAuth）

通过浏览器 OAuth 登录使用 MiniMax-M2.7——无需 API key。在 `hermes model` 中选择 **MiniMax (OAuth)**，通过浏览器登录，Hermes 会持久化访问 token 和刷新 token。底层使用 Anthropic Messages 兼容端点（`/anthropic`）。

```bash
hermes model
# → 选择"MiniMax (OAuth)"
# → 浏览器打开；使用 MiniMax 账户登录（全球或中国区）
# → 确认——凭据保存到 ~/.hermes/auth.json

hermes chat   # 使用 api.minimax.io/anthropic 端点
```

或配置 `config.yaml`：
```yaml
model:
  provider: "minimax-oauth"
  default: "MiniMax-M2.7"
```

支持的模型：`MiniMax-M2.7`（主模型）和 `MiniMax-M2.7-highspeed`（默认辅助模型）。OAuth 路径忽略 `MINIMAX_API_KEY` / `MINIMAX_BASE_URL`。

:::tip MiniMax OAuth 与 API key
`minimax-oauth` 使用 MiniMax 面向消费者的 portal，通过 OAuth 登录——无需设置计费。`minimax` 和 `minimax-cn` 提供商使用 `MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY`——用于程序化访问。完整流程参见 [MiniMax OAuth 指南](/guides/minimax-oauth)。
:::

### NVIDIA NIM

通过 [build.nvidia.com](https://build.nvidia.com)（免费 API key）或本地 NIM 端点使用 Nemotron 及其他开源模型。

```bash
# 云端（build.nvidia.com）
hermes chat --provider nvidia --model nvidia/nemotron-3-super-120b-a12b
# 需要：~/.hermes/.env 中的 NVIDIA_API_KEY

# 本地 NIM 端点——覆盖基础 URL
NVIDIA_BASE_URL=http://localhost:8000/v1 hermes chat --provider nvidia --model nvidia/nemotron-3-super-120b-a12b
```

或在 `config.yaml` 中永久设置：
```yaml
model:
  provider: "nvidia"
  default: "nvidia/nemotron-3-super-120b-a12b"
```

:::tip 本地 NIM
对于本地部署（DGX Spark、本地 GPU），设置 `NVIDIA_BASE_URL=http://localhost:8000/v1`。NIM 暴露与 build.nvidia.com 相同的 OpenAI 兼容 chat completions API，因此在云端和本地之间切换只需修改一行环境变量。
:::

Hermes 会在每次向 `build.nvidia.com` 发送请求时自动附加 NIM 计费来源请求头——无需任何配置。这会在 NVIDIA 计费仪表板中将消耗路由到正确的来源。

### GMI Cloud

通过 [GMI Cloud](https://www.gmicloud.ai/) 使用开源和推理模型——OpenAI 兼容 API，API key 认证。

```bash
# GMI Cloud
hermes chat --provider gmi --model deepseek-ai/DeepSeek-V3.2
# 需要：~/.hermes/.env 中的 GMI_API_KEY
```

或在 `config.yaml` 中永久设置：
```yaml
model:
  provider: "gmi"
  default: "deepseek-ai/DeepSeek-V3.2"
```

基础 URL 可通过 `GMI_BASE_URL` 覆盖（默认：`https://api.gmi-serving.com/v1`）。

### Actual Computer

通过 [Actual Computer](https://actual.inc) 把你自己的硬件变成私有推理集群。两种服务模式均兼容 OpenAI（Hermes 使用 Responses API 传输）：

- **托管中继**——`https://api.actual.inc`，端到端加密，路由到*你自己的*集群。使用从 [actual.inc/user/keys](https://actual.inc/user/keys) 获取的 `ac_` 推理 key 认证。
- **本地守护进程**——在本机 `http://127.0.0.1:8080` 运行，完全离线。无需 API key：Hermes 会检测到回环基础 URL，并自动使用内部占位凭据认证。

```bash
# 托管中继（~/.hermes/.env 中设置 ACTUAL_API_KEY）
hermes chat --provider actual --model <model-id-from-your-cluster>

# 本地守护进程（~/.hermes/.env 中设置 ACTUAL_BASE_URL=http://127.0.0.1:8080，无需 key）
hermes chat --provider actual --model <installed-model-name>
```

或在 `config.yaml` 中永久设置：
```yaml
model:
  provider: "actual"
  default: "<model-id>"
```

说明：
- 模型 ID 来自你集群的 `GET /v1/models`——可通过 `hermes model` 或 `curl -s https://api.actual.inc/v1/models -H "Authorization: Bearer $ACTUAL_API_KEY"` 查看。
- 裸主机地址会被规范化：`ACTUAL_BASE_URL=http://127.0.0.1:8080` 会自动变为 `http://127.0.0.1:8080/v1`。
- 推理强度会被限制在 Actual 支持的范围内（`none/low/medium/high/max`）——全局的 `xhigh`/`ultra` 设置不会导致请求返回 400。
- 小型本地模型：Hermes 完整的默认工具集加上系统 prompt 可能超过 32k 上下文窗口，导致 llama.cpp 系列服务器报空流错误。请限制工具集（`-t file,web`），或以更大的上下文加载模型。可选的 `actual-setup` 技能（`hermes skills install official/devops/actual-setup`）详细介绍了安装与故障排查。
- 别名：`actual-computer`、`actualcomputer`、`aci`。

### StepFun

通过 [StepFun](https://platform.stepfun.com) 使用 Step 系列模型——OpenAI 兼容 API，API key 认证。

```bash
# StepFun
hermes chat --provider stepfun --model step-3.5-flash
# 需要：~/.hermes/.env 中的 STEPFUN_API_KEY
```

或在 `config.yaml` 中永久设置：
```yaml
model:
  provider: "stepfun"
  default: "step-3.5-flash"
```

基础 URL 可通过 `STEPFUN_BASE_URL` 覆盖（默认：`https://api.stepfun.com/v1`）。

### Hugging Face 推理提供商

[Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers) 通过统一的 OpenAI 兼容端点（`router.huggingface.co/v1`）路由到 20+ 开源模型。请求自动路由到最快的可用后端（Groq、Together、SambaNova 等），并支持自动故障转移。

```bash
# 使用任意可用模型
hermes chat --provider huggingface --model Qwen/Qwen3.5-397B-A17B
# 需要：~/.hermes/.env 中的 HF_TOKEN

# 短别名
hermes chat --provider hf --model deepseek-ai/DeepSeek-V3.2
```

或在 `config.yaml` 中永久设置：
```yaml
model:
  provider: "huggingface"
  default: "Qwen/Qwen3.5-397B-A17B"
```

在 [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) 获取 token——确保启用"Make calls to Inference Providers"权限。包含免费层（每月 $0.10 积分，不加价）。

可在模型名称后附加路由后缀：`:fastest`（默认）、`:cheapest`，或 `:provider_name` 强制指定后端。

基础 URL 可通过 `HF_BASE_URL` 覆盖。

## 自定义与自托管 LLM 提供商

Hermes Agent 可与**任何 OpenAI 兼容 API 端点**配合使用。只要服务器实现了 `/v1/chat/completions`，就可以将 Hermes 指向它。这意味着你可以使用本地模型、GPU 推理服务器、多提供商路由器或任何第三方 API。

### 通用配置

配置自定义端点的三种方式：

**交互式配置（推荐）：**
```bash
hermes model
# 选择"Custom endpoint (self-hosted / VLLM / etc.)"
# 输入：API 基础 URL、API key、模型名称
```

**手动配置（`config.yaml`）：**
```yaml
# 在 ~/.hermes/config.yaml 中
model:
  default: your-model-name
  provider: custom
  base_url: http://localhost:8000/v1
  api_key: your-key-or-leave-empty-for-local
```

:::warning 旧版环境变量
`.env` 中的 `LLM_MODEL` 已**移除**——`config.yaml` 是模型和端点配置的唯一来源。`OPENAI_BASE_URL` 仍然被读取，但**仅**对 `openai-api` 提供商有效（它会覆盖直连 API key 访问时的 OpenAI 端点）。对于其他提供商和自定义端点，请使用 `hermes model` 或直接在 `config.yaml` 中设置 `model.base_url`。如果你的 `.env` 中有过时条目，下次运行 `hermes setup` 或配置迁移时会自动清除。
:::

两种方式都会持久化到 `config.yaml`，该文件是模型、提供商和基础 URL 的唯一来源。

### 使用 `/model` 切换模型

:::warning hermes model 与 /model
**`hermes model`**（在终端中运行，任何聊天会话之外）是**完整的提供商配置向导**。用于添加新提供商、运行 OAuth 流程、输入 API key 和配置自定义端点。

**`/model`**（在活跃的 Hermes 聊天会话中输入）只能在**已配置的**提供商和模型之间**切换**。它无法添加新提供商、运行 OAuth 或提示输入 API key。如果你只配置了一个提供商（如 OpenRouter），`/model` 只会显示该提供商的模型。

**添加新提供商：** 退出会话（`Ctrl+C` 或 `/quit`），运行 `hermes model`，配置新提供商，然后开启新会话。
:::

配置好至少一个自定义端点后，可以在会话中途切换模型：

```
/model custom:qwen-2.5          # 切换到自定义端点上的某个模型
/model custom                    # 从端点自动检测模型
/model openrouter:claude-sonnet-4 # 切换回云端提供商
```

如果你配置了**命名自定义提供商**（见下文），使用三段式语法：

```
/model custom:local:qwen-2.5    # 使用"local"自定义提供商和 qwen-2.5 模型
/model custom:work:llama3       # 使用"work"自定义提供商和 llama3
```

切换提供商时，Hermes 会将基础 URL 和提供商持久化到配置中，使更改在重启后保留。从自定义端点切换到内置提供商时，过时的基础 URL 会自动清除。

:::tip
`/model custom`（不带模型名称）会查询端点的 `/models` API，如果只加载了一个模型则自动选择。适用于运行单个模型的本地服务器。
:::

以下所有内容遵循相同模式——只需更改 URL、key 和模型名称。

---

### Ollama — 本地模型，零配置

[Ollama](https://ollama.com/) 用一条命令在本地运行开源模型。最适合：快速本地实验、隐私敏感工作、离线使用。通过 OpenAI 兼容 API 支持工具调用。

```bash
# 安装并运行模型
ollama pull qwen2.5-coder:32b
ollama serve   # 在端口 11434 启动
```

然后配置 Hermes：

```bash
hermes model
# 选择"Custom endpoint (self-hosted / VLLM / etc.)"
# 输入 URL：http://localhost:11434/v1
# 跳过 API key（Ollama 不需要）
# 输入模型名称（如 qwen2.5-coder:32b）
```

或直接配置 `config.yaml`：

```yaml
model:
  default: qwen2.5-coder:32b
  provider: custom
  base_url: http://localhost:11434/v1
  context_length: 64000   # 见下方警告
```

:::caution Ollama 默认上下文长度非常短
Ollama **默认不使用**模型的完整上下文窗口。根据你的显存，默认值为：

| 可用显存 | 默认上下文 |
|----------------|----------------|
| 小于 24 GB | **4,096 tokens** |
| 24–48 GB | 32,768 tokens |
| 48+ GB | 256,000 tokens |

Hermes Agent 在带工具的智能体使用中至少需要 **64,000 tokens** 的上下文。更小的窗口会在启动时被拒绝，因为系统 prompt、工具 schema 和工作中的对话状态需要足够的空间，才能可靠地完成多步工作流。

**如何增加**（选择其一）：

```bash
# 方式 1：通过环境变量设置服务器全局值（推荐）
OLLAMA_CONTEXT_LENGTH=64000 ollama serve

# 方式 2：对于 systemd 管理的 Ollama
sudo systemctl edit ollama.service
# 添加：Environment="OLLAMA_CONTEXT_LENGTH=64000"
# 然后：sudo systemctl daemon-reload && sudo systemctl restart ollama

# 方式 3：烘焙到自定义模型中（每个模型持久生效）
echo -e "FROM qwen2.5-coder:32b\nPARAMETER num_ctx 64000" > Modelfile
ollama create qwen2.5-coder-64k -f Modelfile
```

**无法通过 OpenAI 兼容 API**（`/v1/chat/completions`）设置上下文长度。必须在服务端或通过 Modelfile 配置。这是将 Ollama 与 Hermes 等工具集成时最常见的困惑来源。
:::

**验证上下文设置是否正确：**

```bash
ollama ps
# 查看 CONTEXT 列——应显示你配置的值
```

:::tip
使用 `ollama list` 列出可用模型。使用 `ollama pull <model>` 从 [Ollama 库](https://ollama.com/library) 拉取任意模型。Ollama 自动处理 GPU 卸载——大多数配置无需手动设置。
:::

---

### vLLM — 高性能 GPU 推理

[vLLM](https://docs.vllm.ai/) 是生产 LLM 服务的标准方案。最适合：GPU 硬件上的最大吞吐量、大模型服务、连续批处理。

```bash
pip install vllm
vllm serve meta-llama/Llama-3.1-70B-Instruct \
  --port 8000 \
  --max-model-len 65536 \
  --tensor-parallel-size 2 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

然后配置 Hermes：

```bash
hermes model
# 选择"Custom endpoint (self-hosted / VLLM / etc.)"
# 输入 URL：http://localhost:8000/v1
# 跳过 API key（或输入你配置 vLLM 时设置的 --api-key）
# 输入模型名称：meta-llama/Llama-3.1-70B-Instruct
```

**上下文长度：** vLLM 默认读取模型的 `max_position_embeddings`。如果超出显存，会报错并要求降低 `--max-model-len`。也可使用 `--max-model-len auto` 自动找到能放入显存的最大值。设置 `--gpu-memory-utilization 0.95`（默认 0.9）可将更多上下文放入显存。

**工具调用需要显式标志：**

| 标志 | 用途 |
|------|---------|
| `--enable-auto-tool-choice` | `tool_choice: "auto"` 所必需（Hermes 的默认值） |
| `--tool-call-parser <name>` | 模型工具调用格式的解析器 |

支持的解析器：`hermes`（Qwen 2.5、Hermes 2/3）、`llama3_json`（Llama 3.x）、`mistral`、`deepseek_v3`、`deepseek_v31`、`xlam`、`pythonic`。没有这些标志，工具调用将无法工作——模型会将工具调用以文本形式输出。

**Qwen 推理解析器：** 当 OpenAI 兼容服务器返回 `reasoning`、`reasoning_content` 以及流式推理增量等结构化推理元数据时，Hermes 会予以保留。这些元数据被视为推理/思考轨迹数据，而不是助手可见回答的替代品。对于由 vLLM 提供服务的 Qwen 推理模型，请确保最终对用户可见的响应仍然出现在 `content` 中。如果在你的部署中 `--reasoning-parser qwen3` 使 `content` 为空，可以禁用该解析器，或通过 `extra_body` 传入服务器支持的请求选项，例如 `chat_template_kwargs.enable_thinking: false`。

:::tip
vLLM 支持人类可读的大小：`--max-model-len 64k`（小写 k = 1000，大写 K = 1024）。
:::

---

### SGLang — 带 RadixAttention 的快速服务

[SGLang](https://github.com/sgl-project/sglang) 是 vLLM 的替代方案，具有用于 KV 缓存复用的 RadixAttention。最适合：多轮对话（前缀缓存）、约束解码、结构化输出。

```bash
pip install "sglang[all]"
python -m sglang.launch_server \
  --model meta-llama/Llama-3.1-70B-Instruct \
  --port 30000 \
  --context-length 65536 \
  --tp 2 \
  --tool-call-parser qwen
```

然后配置 Hermes：

```bash
hermes model
# 选择"Custom endpoint (self-hosted / VLLM / etc.)"
# 输入 URL：http://localhost:30000/v1
# 输入模型名称：meta-llama/Llama-3.1-70B-Instruct
```

**上下文长度：** SGLang 默认从模型配置读取。使用 `--context-length` 覆盖。如果需要超过模型声明的最大值，设置 `SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1`。

**工具调用：** 使用 `--tool-call-parser` 并选择适合你模型系列的解析器：`qwen`（Qwen 2.5）、`llama3`、`llama4`、`deepseekv3`、`mistral`、`glm`。没有此标志，工具调用将以纯文本返回。

:::caution SGLang 默认最大输出 128 tokens
如果响应看起来被截断，请检查服务器的生成默认值，并在服务器上进行配置（例如 SGLang 的 `--default-max-tokens`）。Hermes 不提供输出 token 上限设置。
:::

---

### llama.cpp / llama-server — CPU 与 Metal 推理

[llama.cpp](https://github.com/ggml-org/llama.cpp) 在 CPU、Apple Silicon（Metal）和消费级 GPU 上运行量化模型。最适合：无数据中心 GPU 的模型运行、Mac 用户、边缘部署。

```bash
# 构建并启动 llama-server
cmake -B build && cmake --build build --config Release
./build/bin/llama-server \
  --jinja -fa \
  -c 64000 \
  -ngl 99 \
  -m models/qwen2.5-coder-32b-instruct-Q4_K_M.gguf \
  --port 8080 --host 0.0.0.0
```

**上下文长度（`-c`）：** 近期版本默认为 `0`，从 GGUF 元数据读取模型的训练上下文。对于训练上下文超过 128k 的模型，这可能因尝试分配完整 KV 缓存而导致 OOM。请为 Hermes 显式将 `-c` 设置为至少 64,000 tokens。如果使用并行槽（`-np`），总上下文在槽之间分配——`-c 64000 -np 4` 时每个槽只有 16k，低于 Hermes 对每个活动会话的最低要求。

然后配置 Hermes 指向它：

```bash
hermes model
# 选择"Custom endpoint (self-hosted / VLLM / etc.)"
# 输入 URL：http://localhost:8080/v1
# 跳过 API key（本地服务器不需要）
# 输入模型名称——或留空以在只加载一个模型时自动检测
```

这会将端点保存到 `config.yaml`，在会话间持久保留。

:::caution `--jinja` 是工具调用的必要条件
没有 `--jinja`，llama-server 会完全忽略 `tools` 参数。模型会尝试在响应文本中写入 JSON 来调用工具，但 Hermes 不会将其识别为工具调用——你会看到原始 JSON（如 `{"name": "web_search", ...}`）作为消息打印出来，而不是实际执行搜索。

原生工具调用支持（最佳性能）：Llama 3.x、Qwen 2.5（包括 Coder）、Hermes 2/3、Mistral、DeepSeek、Functionary。其他所有模型使用通用处理器，可以工作但效率可能较低。完整列表参见 [llama.cpp 函数调用文档](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)。

可通过检查 `http://localhost:8080/props` 验证工具支持是否已激活——`chat_template` 字段应存在。
:::

:::tip
从 [Hugging Face](https://huggingface.co/models?library=gguf) 下载 GGUF 模型。Q4_K_M 量化在质量与内存使用之间提供最佳平衡。
:::

---

### LM Studio — 带本地模型的桌面应用

[LM Studio](https://lmstudio.ai/) 是一款带 GUI 的本地模型运行桌面应用。最适合：偏好可视化界面的用户、快速模型测试、macOS/Windows/Linux 开发者。

从 LM Studio 应用启动服务器（开发者标签页 → 启动服务器），或使用 CLI：

```bash
lms server start                        # 在端口 1234 启动
lms load qwen2.5-coder --context-length 64000
```

然后配置 Hermes：

```bash
hermes model
# 选择"LM Studio"
# 按 Enter 使用 http://localhost:1234/v1
# 从已发现的模型中选择
# 如果启用了 LM Studio 服务器认证，在提示时输入 LM_API_KEY
```

Hermes 会保留已加载的 LM Studio 实例的上下文。对于尚未加载的模型，在默认的显式模式下，除非你在 Hermes 中配置了 `context_length`，否则 Hermes 会省略该参数，让 LM Studio 应用它自己的模型设置。之后 Hermes 只使用 LM Studio 在加载后报告的上下文长度。

在 LM Studio 中更改上下文长度：

1. 点击模型选择器旁的齿轮图标
2. 将"Context Length"设置为至少 64000 以获得流畅体验
3. 重新加载模型使更改生效
4. 如果你的机器无法容纳 64000，考虑使用上下文长度更大的小模型。

或使用 CLI：`lms load model-name --context-length 64000`

可使用 CLI 估算模型是否能放入内存：`lms load model-name --context-length 64000 --estimate-only`

设置每个模型的持久默认值：我的模型标签页 → 模型上的齿轮图标 → 设置上下文大小。
:::

如果你使用 LM Studio 的即时加载（Just-In-Time loading）/ 自动驱逐（Auto-Evict）功能，并希望由 LM Studio 从常规聊天请求中管理模型的加载与驱逐，可以跳过 Hermes 的显式预加载步骤：

```bash
hermes config set model.lmstudio_load_mode jit
```

用以下命令改回默认的显式预加载行为：

```bash
hermes config set model.lmstudio_load_mode explicit
```

**工具调用：** 自 LM Studio 0.3.6 起支持。具有原生工具调用训练的模型（Qwen 2.5、Llama 3.x、Mistral、Hermes）会被自动检测并显示工具徽章。其他模型使用通用回退，可靠性可能较低。

---

### WSL2 网络（Windows 用户） {#wsl2-networking-windows-users}

由于 Hermes Agent 需要 Unix 环境，Windows 用户在 WSL2 内运行它。如果你的模型服务器（Ollama、LM Studio 等）运行在 **Windows 主机**上，需要桥接网络——WSL2 使用具有独立子网的虚拟网络适配器，因此 WSL2 内的 `localhost` 指向 Linux 虚拟机，**而非** Windows 主机。

:::tip 都在 WSL2 内？没问题。
如果你的模型服务器也在 WSL2 内运行（vLLM、SGLang 和 llama-server 的常见情况），`localhost` 可以正常工作——它们共享同一网络命名空间。跳过本节。
:::

#### 方式 1：镜像网络模式（推荐）

适用于 **Windows 11 22H2+**，镜像模式使 `localhost` 在 Windows 和 WSL2 之间双向工作——最简单的解决方案。

1. 创建或编辑 `%USERPROFILE%\.wslconfig`（如 `C:\Users\YourName\.wslconfig`）：
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```

2. 从 PowerShell 重启 WSL：
   ```powershell
   wsl --shutdown
   ```

3. 重新打开 WSL2 终端。`localhost` 现在可以访问 Windows 服务：
   ```bash
   curl http://localhost:11434/v1/models   # Windows 上的 Ollama——正常工作
   ```

:::note Hyper-V 防火墙
在某些 Windows 11 版本上，Hyper-V 防火墙默认阻止镜像连接。如果启用镜像模式后 `localhost` 仍无法工作，在**管理员 PowerShell** 中运行：
```powershell
Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow
```
:::

#### 方式 2：使用 Windows 主机 IP（Windows 10 / 旧版本）

如果无法使用镜像模式，从 WSL2 内部找到 Windows 主机 IP 并使用它代替 `localhost`：

```bash
# 获取 Windows 主机 IP（WSL2 虚拟网络的默认网关）
ip route show | grep -i default | awk '{ print $3 }'
# 示例输出：172.29.192.1
```

在 Hermes 配置中使用该 IP：

```yaml
model:
  default: qwen2.5-coder:32b
  provider: custom
  base_url: http://172.29.192.1:11434/v1   # Windows 主机 IP，非 localhost
```

:::tip 动态获取
WSL2 重启后主机 IP 可能变化。可在 shell 中动态获取：
```bash
export WSL_HOST=$(ip route show | grep -i default | awk '{ print $3 }')
echo "Windows host at: $WSL_HOST"
curl http://$WSL_HOST:11434/v1/models   # 测试 Ollama
```

或使用机器的 mDNS 名称（需要 WSL2 中的 `libnss-mdns`）：
```bash
sudo apt install libnss-mdns
curl http://$(hostname).local:11434/v1/models
```
:::

#### 服务器绑定地址（NAT 模式必需）

如果使用**方式 2**（NAT 模式加主机 IP），Windows 上的模型服务器必须接受来自 `127.0.0.1` 以外的连接。默认情况下，大多数服务器只监听 localhost——NAT 模式下 WSL2 的连接来自不同的虚拟子网，会被拒绝。在镜像模式下，`localhost` 直接映射，因此默认的 `127.0.0.1` 绑定可以正常工作。

| 服务器 | 默认绑定 | 修复方式 |
|--------|-------------|------------|
| **Ollama** | `127.0.0.1` | 启动 Ollama 前设置 `OLLAMA_HOST=0.0.0.0` 环境变量（Windows 系统设置 → 环境变量，或编辑 Ollama 服务） |
| **LM Studio** | `127.0.0.1` | 在开发者标签页 → 服务器设置中启用**"Serve on Network"** |
| **llama-server** | `127.0.0.1` | 在启动命令中添加 `--host 0.0.0.0` |
| **vLLM** | `0.0.0.0` | 默认已绑定所有接口 |
| **SGLang** | `127.0.0.1` | 在启动命令中添加 `--host 0.0.0.0` |

**Windows 上的 Ollama（详细步骤）：** Ollama 作为 Windows 服务运行。设置 `OLLAMA_HOST`：
1. 打开**系统属性** → **环境变量**
2. 添加新的**系统变量**：`OLLAMA_HOST` = `0.0.0.0`
3. 重启 Ollama 服务（或重启电脑）

#### Windows 防火墙

Windows 防火墙将 WSL2 视为独立网络（在 NAT 和镜像模式下均如此）。如果按上述步骤操作后连接仍然失败，为模型服务器端口添加防火墙规则：

```powershell
# 在管理员 PowerShell 中运行——将 PORT 替换为你服务器的端口
New-NetFirewallRule -DisplayName "Allow WSL2 to Model Server" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434
```

常用端口：Ollama `11434`、vLLM `8000`、SGLang `30000`、llama-server `8080`、LM Studio `1234`。

#### 快速验证

从 WSL2 内部测试是否能访问模型服务器：

```bash
# 将 URL 替换为你服务器的地址和端口
curl http://localhost:11434/v1/models          # 镜像模式
curl http://172.29.192.1:11434/v1/models       # NAT 模式（使用你的实际主机 IP）
```

如果收到列出模型的 JSON 响应，说明配置正确。在 Hermes 配置中使用相同的 URL 作为 `base_url`。

---

### 本地模型故障排查

以下问题影响与 Hermes 配合使用的**所有**本地推理服务器。

#### 从 WSL2 连接 Windows 托管模型服务器时"连接被拒绝"

如果你在 WSL2 内运行 Hermes 而模型服务器在 Windows 主机上，在 WSL2 默认 NAT 网络模式下 `http://localhost:<port>` 无法工作。参见上方的 [WSL2 网络](#wsl2-networking-windows-users) 了解解决方案。

#### 工具调用以文本形式出现而非执行 {#tool-calls-appear-as-text-instead-of-executing}

模型输出类似 `{"name": "web_search", "arguments": {...}}` 的消息，而不是实际调用工具。

**原因：** 你的服务器未启用工具调用，或模型不支持通过服务器的工具调用实现。

| 服务器 | 修复方式 |
|--------|-----|
| **llama.cpp** | 在启动命令中添加 `--jinja` |
| **vLLM** | 添加 `--enable-auto-tool-choice --tool-call-parser hermes` |
| **SGLang** | 添加 `--tool-call-parser qwen`（或适当的解析器） |
| **Ollama** | 工具调用默认启用——确保你的模型支持（使用 `ollama show model-name` 检查） |
| **LM Studio** | 更新到 0.3.6+ 并使用具有原生工具支持的模型 |

#### 模型似乎忘记上下文或给出不连贯的响应

**原因：** 上下文窗口太小。当对话超过上下文限制时，大多数服务器会静默丢弃较早的消息。Hermes 的系统 prompt 加工具 schema 单独就可能占用 4k–8k tokens。

**诊断：**

```bash
# 检查 Hermes 认为的上下文大小
# 查看启动行："Context limit: X tokens"

# 检查服务器的实际上下文
# Ollama：ollama ps（CONTEXT 列）
# llama.cpp：curl http://localhost:8080/props | jq '.default_generation_settings.n_ctx'
# vLLM：检查启动参数中的 --max-model-len
```

**修复：** 将上下文设置为至少 **64,000 tokens** 用于智能体使用。参见上方各服务器章节了解具体标志。

#### 启动时显示"Context limit: 2048 tokens"

Hermes 从服务器的 `/v1/models` 端点自动检测上下文长度。如果服务器报告的值较低（或根本不报告），Hermes 使用模型声明的限制，该值可能不正确。

**修复：** 在 `config.yaml` 中显式设置：

```yaml
model:
  default: your-model
  provider: custom
  base_url: http://localhost:11434/v1
  context_length: 64000
```

#### 响应在句子中间被截断

**可能原因：**
1. **服务器上的输出限制过低** — 配置服务器的生成默认值（例如 SGLang 的 `--default-max-tokens`）。Hermes 不提供输出 token 上限设置。响应长度与对话的上下文窗口（`context_length`）是两回事。
2. **上下文耗尽** — 模型填满了上下文窗口。增加 `model.context_length` 或在 Hermes 中启用[上下文压缩](/user-guide/configuration#context-compression)。

---

### LiteLLM Proxy — 多提供商网关

[LiteLLM](https://docs.litellm.ai/) 是一个 OpenAI 兼容代理，将 100+ LLM 提供商统一在单一 API 后面。最适合：无需更改配置即可切换提供商、负载均衡、故障转移链、预算控制。

```bash
# 安装并启动
pip install "litellm[proxy]"
litellm --model anthropic/claude-sonnet-4 --port 4000

# 或使用配置文件支持多个模型：
litellm --config litellm_config.yaml --port 4000
```

然后通过 `hermes model` → 自定义端点 → `http://localhost:4000/v1` 配置 Hermes。

带故障转移的 `litellm_config.yaml` 示例：
```yaml
model_list:
  - model_name: "best"
    litellm_params:
      model: anthropic/claude-sonnet-4
      api_key: sk-ant-...
  - model_name: "best"
    litellm_params:
      model: openai/gpt-4o
      api_key: sk-...
router_settings:
  routing_strategy: "latency-based-routing"
```

---

### ClawRouter — 成本优化路由

[ClawRouter](https://github.com/BlockRunAI/ClawRouter) 由 BlockRunAI 开发，是一个本地路由代理，根据查询复杂度自动选择模型。它从 14 个维度对请求进行分类，并路由到能处理该任务的最便宜模型。支付方式为 USDC 加密货币（无需 API key）。

```bash
# 安装并启动
npx @blockrun/clawrouter    # 在端口 8402 启动
```

然后通过 `hermes model` → 自定义端点 → `http://localhost:8402/v1` → 模型名称 `blockrun/auto` 配置 Hermes。

路由配置文件：
| 配置文件 | 策略 | 节省 |
|---------|----------|---------|
| `blockrun/auto` | 质量/成本均衡 | 74-100% |
| `blockrun/eco` | 尽可能便宜 | 95-100% |
| `blockrun/premium` | 最佳质量模型 | 0% |
| `blockrun/free` | 仅免费模型 | 100% |
| `blockrun/agentic` | 针对工具使用优化 | 不定 |

:::note
ClawRouter 需要在 Base 或 Solana 上有 USDC 充值的钱包用于支付。所有请求通过 BlockRun 的后端 API 路由。运行 `npx @blockrun/clawrouter doctor` 检查钱包状态。
:::

---

### 其他兼容提供商 {#other-compatible-providers}

任何具有 OpenAI 兼容 API 的服务均可使用。一些常用选项：

| 提供商 | 基础 URL | 说明 |
|----------|----------|-------|
| [Together AI](https://together.ai) | `https://api.together.xyz/v1` | 云托管开源模型 |
| [Groq](https://groq.com) | `https://api.groq.com/openai/v1` | 超快推理 |
| [DeepSeek](https://deepseek.com) | `https://api.deepseek.com/v1` | DeepSeek 模型 |
| [Fireworks AI](https://fireworks.ai) | `https://api.fireworks.ai/inference/v1` | 快速开源模型托管 |
| [GMI Cloud](https://www.gmicloud.ai/) | `https://api.gmi-serving.com/v1` | 托管 OpenAI 兼容推理 |
| [Actual Computer](https://actual.inc) | `https://api.actual.inc/v1` | 通往你自有集群的私有中继；本地守护进程位于 `http://127.0.0.1:8080/v1` |
| [Cerebras](https://cerebras.ai) | `https://api.cerebras.ai/v1` | 晶圆级芯片推理 |
| [Mistral AI](https://mistral.ai) | `https://api.mistral.ai/v1` | Mistral 模型 |
| [OpenAI](https://openai.com) | `https://api.openai.com/v1` | 直连 OpenAI |
| [Azure OpenAI](https://azure.microsoft.com) | `https://YOUR.openai.azure.com/` | 企业级 OpenAI |
| [LocalAI](https://localai.io) | `http://localhost:8080/v1` | 自托管，多模型 |
| [Jan](https://jan.ai) | `http://localhost:1337/v1` | 带本地模型的桌面应用 |

通过 `hermes model` → 自定义端点，或在 `config.yaml` 中配置任意上述服务：

```yaml
model:
  default: meta-llama/Llama-3.1-70B-Instruct-Turbo
  provider: custom
  base_url: https://api.together.xyz/v1
  api_key: your-together-key
```

---

### 上下文长度检测 {#context-length-detection}

:::note 上下文窗口与输出限制是两回事
**`context_length`** 是**总上下文窗口**——输入和输出 token 的合计预算（例如 Claude Opus 4.6 为 200,000）。Hermes 用它来决定何时压缩历史记录以及验证 API 请求。

输出限制约束的是单次生成的响应，而非对话历史。Hermes 不再读取 `model.max_tokens`、`HERMES_MAX_TOKENS`、提供商输出上限设置或 `model_overrides.*.*.max_output_tokens`。请删除这些旧设置。自定义 OpenAI 兼容端点不会收到按目录大小自动设定的输出上限，而是适用其服务器默认值；这些默认值可能低于模型最大值。

原生 Anthropic Messages（包括原生 Anthropic Bedrock 路径）要求提供 `max_tokens`，因此 Hermes 会提供一个内部值。Bedrock Converse 是另一种协议：它可选的 `inferenceConfig.maxTokens` 默认被省略，[AWS 文档说明此时使用模型最大值](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InferenceConfiguration.html)。内部有界任务和提供商特定的协议要求仍属于实现细节。省略并不普遍意味着选择模型的最大输出。

当自动检测获取的窗口大小不正确时，设置 `context_length`。

:::

Hermes 使用多源解析链来检测模型和提供商的正确上下文窗口：

1. **配置覆盖** — config.yaml 中的 `model.context_length`（最高优先级）
2. **自定义提供商按模型** — `providers.<name>.models.<id>.context_length`
3. **持久缓存** — 之前发现的值（重启后保留）
4. **端点 `/models`** — 查询服务器 API（本地/自定义端点）
5. **Anthropic `/v1/models`** — 查询 Anthropic API 获取 `max_input_tokens`（仅 API key 用户）
6. **OpenRouter API** — 来自 OpenRouter 的实时模型元数据
7. **Nous Portal** — 将 Nous 模型 ID 后缀匹配到 OpenRouter 元数据
8. **[models.dev](https://models.dev)** — 社区维护的注册表，包含 100+ 提供商 3800+ 模型的提供商特定上下文长度
9. **回退默认值** — 广泛的模型系列模式（默认 128K）

大多数配置开箱即用。该系统具有提供商感知能力——同一模型在不同服务商处可能有不同的上下文限制（例如 `claude-opus-4.6` 在 Anthropic 直连时为 1M，在 GitHub Copilot 上为 128K）。

要显式设置上下文长度，在模型配置中添加 `context_length`：

```yaml
model:
  default: "qwen3.5:9b"
  base_url: "http://localhost:8080/v1"
  context_length: 131072  # tokens
```

对于自定义端点，也可以按模型设置上下文长度：

```yaml
providers:
  my-local-llm:
    api: "http://localhost:11434/v1"
    models:
      qwen3.5:27b:
        context_length: 64000
      deepseek-r1:70b:
        context_length: 65536
```

`hermes model` 在配置自定义端点时会提示输入上下文长度。留空则自动检测。

:::tip 何时手动设置
- 你使用的 Ollama 自定义 `num_ctx` 低于模型最大值
- 你想将上下文限制在模型最大值以下（例如在 128k 模型上使用 8k 以节省显存）
- 你在不暴露 `/v1/models` 的代理后面运行
:::

---

### 命名自定义提供商

如果你使用多个自定义端点（例如本地开发服务器和远程 GPU 服务器），可以在 `config.yaml` 的 `providers:` 字典下将它们定义为命名自定义提供商，以提供商名称为键：

```yaml
providers:
  local:
    api: http://localhost:8080/v1
    # api_key 省略——Hermes 对无 key 的本地服务器使用"no-key-required"
  work:
    api: https://gpu-server.internal.corp/v1
    key_env: CORP_API_KEY
    transport: chat_completions   # 由 `hermes model` → 自定义端点向导显式设置；自动检测仍作为回退
  anthropic-proxy:
    api: https://proxy.example.com/anthropic
    key_env: ANTHROPIC_PROXY_KEY
    transport: anthropic_messages  # 用于 Anthropic 兼容代理
```

每个条目接受：`api`（端点基础 URL——也接受别名 `base_url`/`url`）、`name`（可选的显示名称；默认为字典键）、`key_env` 或内联 `api_key` 或 `key_cmd`（见下文）、`transport`（`chat_completions` / `anthropic_messages` / `codex_responses`）、`default_model`、`models`、`context_length`、`discover_models`、`extra_body`、`extra_headers`、`ssl_ca_cert` / `ssl_verify`，以及用于隐藏条目而不删除它的 `enabled: false`。

#### 命令生成的凭据（`key_cmd`） {#command-minted-credentials-key_cmd}

视觉、思考和原生本地模型能力探测在构建认证请求头之前，会先实例化与聊天相同的可调用凭据。它们复用命令 token 缓存，但不会替换聊天客户端的可调用对象。如果命令无法生成字符串 token，这些尽力而为的探测不会发送 bearer，而不是发送对象表示或优先级更低的已配置凭据。当显式的可调用凭据失败时，原生本地模型探测会移除继承的 Authorization 请求头，同时保留无关的已配置请求头。聊天保持其正常的错误处理。

企业网关通常签发短期 bearer token（SSO/OIDC 代理、云 IAM、内部认证代理），而非静态 API key，因此复制到 `.env` 中的 token 会在会话中途过期，请求开始返回 401。`key_cmd` 指定一个*打印* token 的命令；Hermes 会运行它并缓存结果，直到临近过期前，因此长会话无需重启即可持续工作：

```yaml
providers:
  my-gateway:
    base_url: "https://gateway.internal.example.com/v1"
    api_mode: chat_completions
    key_cmd: "my-auth-cli print-token --profile prod"
```

适用于任何打印 token 的辅助工具——`databricks auth token`、`gcloud auth print-access-token`、`az account get-access-token`、`vault read`，或 Claude Code 风格的 `apiKeyHelper` 脚本。

该命令必须在 stdout 上**只**打印 token：可以是裸 token，也可以是带 `access_token` 字段的 JSON（会遵循 `expires_in`；绝对时间的 `expiry`/`expiresOn` ISO 时间戳同样支持）。多行输出会被拒绝，而不是去猜测。如果没有给出过期时间，token 会在一个有界的时间窗口内重新生成。

优先级：显式的 `--api-key` 标志仍然优先；否则在同一条目上，`key_cmd` 优先于静态的 `api_key`/`key_env`。生成的凭据同样适用于主智能体轮次和辅助任务（标题生成、压缩、视觉、嵌入）。

模型发现同样遵循 `key_cmd`，对 `providers:` 和旧版 `custom_providers:` 条目都有效，包括 `hermes model` 配置流程。辅助工具仅在需要经过认证的实时目录探测时才运行：禁用发现和读取热目录缓存都不会生成 token。目录按命令身份划分范围，因此轮换 bearer 不会使目录失效。探测辅助工具使用自己的短期 token 来源，而不是推理客户端的 token 缓存；生成的 bearer 永远不会保存到 `config.yaml`。如果辅助工具失败，发现会回退到已配置的模型，且不会暴露辅助工具的输出。

不要与 `secrets.command` 混淆，后者会在**启动时运行一次**辅助工具，为整个进程填充环境变量。如果是返回多个密钥的 vault/钥匙串辅助工具，请用它；如果某个提供商的凭据必须在会话*期间*重新生成，请用 `key_cmd`。

:::note 旧版格式
较旧的配置使用顶层 `custom_providers:` 列表。它仍然有效——Hermes 两种都会读取——并且 `hermes update` 会自动将其迁移为 `providers:` 字典（config v12）。字典格式中的字段名略有不同：旧版的 `model` 对应 `default_model`，旧版的 `api_mode` 对应 `transport`。
:::

某些 OpenAI 兼容端点需要特定于提供商的请求体字段。在对应的自定义提供商中添加 `extra_body` 映射，Hermes 会将其合并到该端点的每个 chat-completions 请求中：

```yaml
providers:
  gemma-local:
    api: http://localhost:8080/v1
    default_model: google/gemma-4-31b-it
    extra_body:
      enable_thinking: true
      reasoning_effort: high
```

使用你服务器文档中的格式。例如，vLLM Gemma 部署和某些 NVIDIA NIM 端点期望 `enable_thinking` 在 `chat_template_kwargs` 下，而不是作为顶级 `extra_body` 字段：

```yaml
extra_body:
  chat_template_kwargs:
    enable_thinking: true
```

对于由 vLLM 提供服务的 Qwen 推理模型，当某个推理解析器把全部生成文本都分离到推理字段、使助手的 `content` 为空时，可以用同样的形式来禁用思考：

```yaml
extra_body:
  chat_template_kwargs:
    enable_thinking: false
```

配置的 `extra_body` 会随提供商生效于所有场景：它在智能体构建时合并，**在每个网关轮次中都会保留**（包括 `/fast` 在其上叠加 `service_tier`/`speed` 覆盖的轮次——这些覆盖会合并到你的 `extra_body` 之上，而不是替换它），并且**在 `/model` 切换时重新推导**——切换到某个命名自定义提供商会应用它的 `extra_body`，切换离开时会清除它，因此不会泄漏到其他提供商。

`hermes model` → 自定义端点向导现在会显式提示 API 模式，并将你的答案持久化到 `config.yaml`（作为提供商条目上的 `transport`）。当字段留空时，基于 URL 的自动检测（例如 `/anthropic` 路径 → `anthropic_messages`）仍作为回退。

**自定义提供商模型的原生视觉支持。**如果你的自定义端点提供了一个支持视觉、但不在 models.dev 中的模型，可设置 `model.supports_vision: true`，让 Hermes 以原生方式（作为 `image_url` 片段）路由附加的图像，而不是先经由 `vision_analyze` 预处理。只需这一个开关——无需再设置 `agent.image_input_mode: native`。

```yaml
model:
  provider: custom
  base_url: http://localhost:8080/v1
  default: qwen3.6-35b-a3b
  supports_vision: true   # send images natively; otherwise vision_analyze pre-describes them
```

同一个键在按名称配置的提供商模型上也同样生效（`providers.<name>.models.<id>.supports_vision`），并接受标准 YAML 布尔值（`true/false/yes/no/on/off/1/0`）。

使用三段式语法在会话中途切换：

```
/model custom:local:qwen-2.5       # 使用"local"端点和 qwen-2.5
/model custom:work:llama3-70b      # 使用"work"端点和 llama3-70b
/model custom:anthropic-proxy:claude-sonnet-4  # 使用代理
```

也可以从交互式 `hermes model` 菜单中选择命名自定义提供商。

---

### 实战配置：Together AI、Groq、Perplexity

[其他兼容提供商](#other-compatible-providers) 中列出的云提供商都使用 OpenAI 的 REST 方言，因此在 `providers:` 字典下的接入方式相同。以下是三个可直接使用的配置示例。每个示例放入 `~/.hermes/config.yaml`，对应的 API key 放入 `~/.hermes/.env`。

#### Together AI

托管开源模型（Llama、MiniMax、Gemma、DeepSeek、Qwen），价格显著低于一方 API。适合多模型场景的默认选择。

```yaml
# ~/.hermes/config.yaml
providers:
  together:
    api: https://api.together.xyz/v1
    key_env: TOGETHER_API_KEY
    # transport: chat_completions  # 默认——无需设置

model:
  default: MiniMaxAI/MiniMax-M2.7   # 或 together.ai/models 中的任意模型
  provider: custom:together
```

```bash
# ~/.hermes/.env
TOGETHER_API_KEY=your-together-key
```

会话中途切换模型：

```
/model custom:together:meta-llama/Llama-3.3-70B-Instruct-Turbo
/model custom:together:google/gemma-4-31b-it
/model custom:together:deepseek-ai/DeepSeek-V3
```

Together 的 `/v1/models` 端点可用，因此 `hermes model` 可以自动发现可用模型。

#### Groq

超快推理（Llama-3.3-70B 约 500 tok/s）。模型目录较小，但对延迟敏感的交互式使用效果出色。

```yaml
# ~/.hermes/config.yaml
providers:
  groq:
    api: https://api.groq.com/openai/v1
    key_env: GROQ_API_KEY

model:
  default: llama-3.3-70b-versatile
  provider: custom:groq
```

```bash
# ~/.hermes/.env
GROQ_API_KEY=your-groq-key
```

#### Perplexity

当你需要自动进行实时网页搜索和引用的模型时很有用。对可用模型有严格限制——查看 [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) 获取当前列表。

```yaml
# ~/.hermes/config.yaml
providers:
  perplexity:
    api: https://api.perplexity.ai
    key_env: PERPLEXITY_API_KEY

model:
  default: sonar
  provider: custom:perplexity
```

```bash
# ~/.hermes/.env
PERPLEXITY_API_KEY=your-perplexity-key
```

#### 在单个配置中使用多个提供商

三个示例可以组合使用——同时使用所有提供商，并通过 `/model custom:<name>:<model>` 按轮次切换：

```yaml
providers:
  together:
    api: https://api.together.xyz/v1
    key_env: TOGETHER_API_KEY
  groq:
    api: https://api.groq.com/openai/v1
    key_env: GROQ_API_KEY
  perplexity:
    api: https://api.perplexity.ai
    key_env: PERPLEXITY_API_KEY

model:
  default: MiniMaxAI/MiniMax-M2.7
  provider: custom:together      # 启动时使用 Together；之后可自由切换
```

:::tip 故障排查
- `hermes doctor` 对于上述任何名称都不应打印 `Unknown provider` 警告（在 #15083 的 CLI 验证器修复之后）。
- 如果某个提供商的 `/v1/models` 端点不可达（Perplexity 是常见情况），`hermes model` 会在警告后持久化模型而不是硬性拒绝——参见 #15136。
- 要完全跳过命名提供商并使用带 `CUSTOM_BASE_URL` 环境变量的裸 `provider: custom`，参见 #15103。
:::

---

### 选择合适的配置

| 使用场景 | 推荐方案 |
|----------|-------------|
| **只想让它工作** | OpenRouter（默认）或 Nous Portal |
| **本地模型，简单配置** | Ollama |
| **生产 GPU 服务** | vLLM 或 SGLang |
| **Mac / 无 GPU** | Ollama 或 llama.cpp |
| **多提供商路由** | LiteLLM Proxy 或 OpenRouter |
| **成本优化** | ClawRouter 或带 `sort: "price"` 的 OpenRouter |
| **最大隐私保护** | Ollama、vLLM 或 llama.cpp（完全本地） |
| **企业 / Azure** | Azure OpenAI 加自定义端点 |
| **中国 AI 模型** | z.ai（GLM）、Kimi/Moonshot（`kimi-coding` 或 `kimi-coding-cn`）、MiniMax、小米 MiMo 或腾讯 TokenHub（一等提供商） |

:::tip
可以随时使用 `hermes model` 切换提供商——无需重启。无论使用哪个提供商，你的对话历史、记忆和技能都会保留。
:::

## 可选 API Key

| 功能 | 提供商 | 环境变量 |
|---------|----------|--------------|
| 网页抓取 | [Firecrawl](https://firecrawl.dev/) | `FIRECRAWL_API_KEY`、`FIRECRAWL_API_URL` |
| 浏览器自动化 | [Browserbase](https://browserbase.com/) | `BROWSERBASE_API_KEY`、`BROWSERBASE_PROJECT_ID` |
| 图像生成 | [FAL](https://fal.ai/) | `FAL_KEY` |
| 高级 TTS 语音 | [ElevenLabs](https://elevenlabs.io/) | `ELEVENLABS_API_KEY` |
| OpenAI TTS + 语音转录 | [OpenAI](https://platform.openai.com/api-keys) | `VOICE_TOOLS_OPENAI_KEY` |
| Mistral TTS + 语音转录 | [Mistral](https://console.mistral.ai/) | `MISTRAL_API_KEY` |
| 跨会话用户建模 | [Honcho](https://honcho.dev/) | `HONCHO_API_KEY` |
| 语义长期记忆 | [Supermemory](https://supermemory.ai) | `SUPERMEMORY_API_KEY` |

### 自托管 Firecrawl

默认情况下，Hermes 使用 [Firecrawl 云 API](https://firecrawl.dev/) 进行网页搜索和抓取。如果你希望在本地运行 Firecrawl，可以将 Hermes 指向自托管实例。完整配置说明参见 Firecrawl 的 [SELF_HOST.md](https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md)。

**优势：** 无需 API key，无速率限制，无按页计费，完全数据主权。

**劣势：** 云版本使用 Firecrawl 专有的"Fire-engine"进行高级反爬虫绕过（Cloudflare、CAPTCHA、IP 轮换）。自托管版本使用基础 fetch + Playwright，某些受保护的网站可能失败。搜索使用 DuckDuckGo 而非 Google。

**配置步骤：**

1. 克隆并启动 Firecrawl Docker 栈（5 个容器：API、Playwright、Redis、RabbitMQ、PostgreSQL——需要约 4-8 GB RAM）：
   ```bash
   git clone https://github.com/firecrawl/firecrawl
   cd firecrawl
   # 在 .env 中设置：USE_DB_AUTHENTICATION=false, HOST=0.0.0.0, PORT=3002
   docker compose up -d
   ```

2. 将 Hermes 指向你的实例（无需 API key）：
   ```bash
   hermes config set FIRECRAWL_API_URL http://localhost:3002
   ```

如果你的自托管实例启用了认证，也可以同时设置 `FIRECRAWL_API_KEY` 和 `FIRECRAWL_API_URL`。

## OpenRouter 提供商路由

使用 OpenRouter 时，可以控制请求如何在提供商之间路由。在 `~/.hermes/config.yaml` 中添加 `provider_routing` 节：

```yaml
provider_routing:
  sort: "throughput"          # "price"（默认）、"throughput" 或 "latency"
  # only: ["anthropic"]      # 仅使用这些提供商
  # ignore: ["deepinfra"]    # 跳过这些提供商
  # order: ["anthropic", "google"]  # 按此顺序尝试提供商
  # require_parameters: true  # 仅使用支持所有请求参数的提供商
  # data_collection: "deny"   # 排除可能存储/训练数据的提供商
  # models:                   # 按模型固定（相同的键；未设置的键沿用上层配置）
  #   "openai/gpt-6-astra": {only: ["openai"]}
  #   "anthropic/claude-fable-5.1": {only: ["anthropic"]}
```

**快捷方式：** 在任意模型名称后附加 `:nitro` 进行吞吐量排序（如 `anthropic/claude-sonnet-4:nitro`），或附加 `:floor` 进行价格排序。按模型配置详情：[提供商路由](/user-guide/features/provider-routing#per-model-overrides-models)。

## OpenRouter Pareto Code 路由器 {#openrouter-pareto-code-router}

OpenRouter 提供一个实验性编程模型路由器 `openrouter/pareto-code`，自动将请求路由到满足编程质量标准的最便宜模型（按 [Artificial Analysis](https://artificialanalysis.ai/) 排名）。选择此模型并在 `~/.hermes/config.yaml` 中调整 `min_coding_score` 参数：

```yaml
model:
  provider: openrouter
  model: openrouter/pareto-code

openrouter:
  min_coding_score: 0.65   # 0.0–1.0；越高 = 越强（越贵）的编程模型。默认 0.65。
```

说明：

- `min_coding_score` **仅**在 `model.model` 为 `openrouter/pareto-code` 时发送。对其他任何模型该值无效。
- 设置为空字符串（或删除该行）让 OpenRouter 选择最强的可用编程模型——这是省略 plugins 块时的文档行为。
- 在给定日期内，按分数选择是确定性的，但随着 Pareto 前沿移动（新模型、基准更新），实际选择的模型可能变化。
- 参见 OpenRouter 的 [Pareto Router 文档](https://openrouter.ai/docs/guides/routing/routers/pareto-router) 了解完整路由器行为。
- 要将 Pareto Code 路由器用于特定**辅助任务**（压缩、视觉等）而非主智能体，在该任务下设置 `extra_body.plugins`——参见[辅助模型 → OpenRouter 路由与辅助任务的 Pareto Code](/user-guide/configuration#openrouter-routing--pareto-code-for-auxiliary-tasks)。

## 故障转移提供商 {#fallback-providers}

配置一个备用提供商链，当主模型失败时（速率限制、服务器错误、认证失败）Hermes 按顺序尝试。规范格式是顶级 `fallback_providers:` 列表：

```yaml
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-sonnet-4
  - provider: anthropic
    model: claude-sonnet-4
    # base_url: http://localhost:8000/v1    # 可选，用于自定义端点
    # api_mode: chat_completions           # 可选覆盖
```

为向后兼容，旧版单对 `fallback_model:` 字典仍被接受：

```yaml
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

激活时，故障转移在不丢失对话的情况下中途切换模型和提供商。链按条目逐一尝试；每个会话激活一次。

支持的提供商：`openrouter`、`nous`、`novita`、`openai-codex`、`copilot`、`copilot-acp`、`anthropic`、`gemini`、`qwen-oauth`、`huggingface`、`zai`、`kimi-coding`、`kimi-coding-cn`、`minimax`、`minimax-cn`、`minimax-oauth`、`deepseek`、`nvidia`、`xai`、`xai-oauth`、`ollama-cloud`、`bedrock`、`ai-gateway`、`azure-foundry`、`opencode-zen`、`opencode-go`、`commandcode`、`commandcode-anthropic`、`kilocode`、`xiaomi`、`arcee`、`gmi`、`actual`、`stepfun`、`lmstudio`、`alibaba`、`alibaba-coding-plan`、`tencent-tokenhub`、`tencent-tokenplan`、`nebius-token-factory`、`router`、`custom`。

:::tip
故障转移仅通过 `config.yaml` 配置——或通过 `hermes fallback` 交互式配置。有关触发时机、链推进方式以及与辅助任务和委托的交互，参见[故障转移提供商](/user-guide/features/fallback-providers)。
:::

---

## 另请参阅

- [配置](/user-guide/configuration) — 通用配置（目录结构、配置优先级、终端后端、记忆、压缩等）
- [环境变量](/reference/environment-variables) — 所有环境变量的完整参考
