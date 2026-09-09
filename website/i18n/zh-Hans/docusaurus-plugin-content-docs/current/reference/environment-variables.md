---
sidebar_position: 2
title: "环境变量"
description: "Hermes Agent 使用的所有环境变量完整参考"
---

# 环境变量参考

Hermes 会从进程环境读取环境变量，对于用户自行管理的密钥则从 `~/.hermes/.env` 读取。请把 API 密钥、机器人 token、OAuth 密钥及其他凭据放在 `.env` 中；当存在对应的配置键时，非密钥类的行为设置更适合写在 `config.yaml` 中。下面有些变量只是进程级覆盖或内部桥接变量，不应仅仅因为在此处有文档就写入 `.env`。

## LLM 提供商

| 变量 | 描述 |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API 密钥（推荐，灵活性强） |
| `OPENROUTER_BASE_URL` | 覆盖 OpenRouter 兼容的 base URL |
| `FIREWORKS_API_KEY` | Fireworks AI API 密钥（[app.fireworks.ai](https://app.fireworks.ai/settings/users/api-keys)）。端点覆盖请在 `config.yaml` 中使用 `model.base_url` 配置。 |
| `HERMES_OPENROUTER_CACHE` | 启用 OpenRouter 响应缓存（`1`/`true`/`yes`/`on`）。覆盖 config.yaml 中的 `openrouter.response_cache`。参见 [Response Caching](https://openrouter.ai/docs/guides/features/response-caching)。 |
| `HERMES_OPENROUTER_CACHE_TTL` | 缓存 TTL（秒，1-86400）。覆盖 config.yaml 中的 `openrouter.response_cache_ttl`。 |
| `NOUS_BASE_URL` | 覆盖 Nous Portal base URL（极少使用；仅用于开发/测试） |
| `NOUS_INFERENCE_BASE_URL` | 直接覆盖 Nous 推理端点 |
| `OPENAI_API_KEY` | 自定义 OpenAI 兼容端点的 API 密钥（与 `OPENAI_BASE_URL` 配合使用） |
| `OPENAI_BASE_URL` | 自定义端点的 base URL（VLLM、SGLang 等） |
| `LM_API_KEY` | LM Studio（`lmstudio` provider）的 API 密钥。对本地服务器通常只是一个占位值 |
| `LM_BASE_URL` | LM Studio base URL（默认：`http://localhost:1234/v1`） |
| `COPILOT_GITHUB_TOKEN` | 用于 Copilot API 的 GitHub token——最高优先级（OAuth `gho_*` 或细粒度 PAT `github_pat_*`；经典 PAT `ghp_*` **不支持**） |
| `GH_TOKEN` | GitHub token——Copilot 第二优先级（也供 `gh` CLI 使用） |
| `GITHUB_TOKEN` | GitHub token——Copilot 第三优先级 |
| `HERMES_COPILOT_ACP_COMMAND` | 覆盖 Copilot ACP CLI 二进制路径（默认：`copilot`） |
| `COPILOT_CLI_PATH` | `HERMES_COPILOT_ACP_COMMAND` 的别名 |
| `HERMES_COPILOT_ACP_ARGS` | 覆盖 Copilot ACP 参数（默认：`--acp --stdio`） |
| `COPILOT_ACP_BASE_URL` | 覆盖 Copilot ACP base URL |
| `COPILOT_API_BASE_URL` | 覆盖 Copilot API base URL（`copilot` provider） |
| `GLM_API_KEY` | z.ai / ZhipuAI GLM API 密钥（[z.ai](https://z.ai)） |
| `ZAI_API_KEY` | `GLM_API_KEY` 的别名 |
| `Z_AI_API_KEY` | `GLM_API_KEY` 的别名 |
| `GLM_BASE_URL` | 覆盖 z.ai base URL（默认：`https://api.z.ai/api/paas/v4`） |
| `KIMI_API_KEY` | Kimi / Moonshot AI API 密钥（[moonshot.ai](https://platform.moonshot.ai)） |
| `KIMI_CODING_API_KEY` | `kimi-coding` provider 的别名密钥（与 `KIMI_API_KEY` 一并接受） |
| `KIMI_BASE_URL` | 覆盖 Kimi base URL（默认：`https://api.moonshot.ai/v1`） |
| `KIMI_CN_API_KEY` | Kimi / Moonshot 中国区 API 密钥（[moonshot.cn](https://platform.moonshot.cn)） |
| `ARCEEAI_API_KEY` | Arcee AI API 密钥（[chat.arcee.ai](https://chat.arcee.ai/)） |
| `ARCEE_BASE_URL` | 覆盖 Arcee base URL（默认：`https://api.arcee.ai/api/v1`） |
| `GMI_API_KEY` | GMI Cloud API 密钥（[gmicloud.ai](https://www.gmicloud.ai/)） |
| `GMI_BASE_URL` | 覆盖 GMI Cloud base URL（默认：`https://api.gmi-serving.com/v1`） |
| `MINIMAX_API_KEY` | MiniMax API 密钥——全球端点（[minimax.io](https://www.minimax.io)）。**`minimax-oauth` 不使用此变量**（OAuth 路径通过浏览器登录）。 |
| `MINIMAX_BASE_URL` | 覆盖 MiniMax base URL（默认：`https://api.minimax.io/anthropic`——Hermes 使用 MiniMax 的 Anthropic Messages 兼容端点）。**`minimax-oauth` 不使用此变量**。 |
| `MINIMAX_CN_API_KEY` | MiniMax API 密钥——中国区端点（[minimaxi.com](https://www.minimaxi.com)）。**`minimax-oauth` 不使用此变量**（OAuth 路径通过浏览器登录）。 |
| `MINIMAX_CN_BASE_URL` | 覆盖 MiniMax 中国区 base URL（默认：`https://api.minimaxi.com/anthropic`）。**`minimax-oauth` 不使用此变量**。 |
| `KILOCODE_API_KEY` | Kilo Code API 密钥（[kilo.ai](https://kilo.ai)） |
| `KILOCODE_BASE_URL` | 覆盖 Kilo Code base URL（默认：`https://api.kilo.ai/api/gateway`） |
| `XIAOMI_API_KEY` | 小米 MiMo API 密钥（[platform.xiaomimimo.com](https://platform.xiaomimimo.com)） |
| `XIAOMI_BASE_URL` | 覆盖小米 MiMo base URL（默认：`https://api.xiaomimimo.com/v1`） |
| `UPSTAGE_API_KEY` | 用于 Solar 模型的 Upstage API 密钥（[console.upstage.ai](https://console.upstage.ai/api-keys)） |
| `UPSTAGE_BASE_URL` | 覆盖 Upstage base URL（默认：`https://api.upstage.ai/v1`） |
| `TOKENHUB_API_KEY` | 腾讯 TokenHub API 密钥（[tokenhub.tencentmaas.com](https://tokenhub.tencentmaas.com)） |
| `TOKENHUB_BASE_URL` | 覆盖腾讯 TokenHub base URL（默认：`https://tokenhub.tencentmaas.com/v1`） |
| `AZURE_FOUNDRY_API_KEY` | Microsoft Foundry / Azure OpenAI API 密钥（[ai.azure.com](https://ai.azure.com/)）。当 `model.auth_mode: entra_id` 时不需要 |
| `AZURE_FOUNDRY_BASE_URL` | Microsoft Foundry 端点 URL（例如 OpenAI 风格：`https://<resource>.openai.azure.com/openai/v1`，Anthropic 风格：`https://<resource>.services.ai.azure.com/anthropic`） |
| `AZURE_ANTHROPIC_KEY` | 用于 `provider: anthropic` + `base_url` 指向 Microsoft Foundry Claude 部署的 Azure Anthropic API 密钥（当同时配置了 Anthropic 和 Azure Anthropic 时，作为 `ANTHROPIC_API_KEY` 的替代） |
| `AZURE_TENANT_ID` | Entra ID 租户 ID（服务主体流程；当 `model.auth_mode: entra_id` 时由 `azure-identity` 读取） |
| `AZURE_CLIENT_ID` | Entra ID 客户端 ID（服务主体、工作负载标识或用户分配的托管标识） |
| `AZURE_CLIENT_SECRET` | `EnvironmentCredential` 使用的服务主体密钥 |
| `AZURE_CLIENT_CERTIFICATE_PATH` | 服务主体证书（`AZURE_CLIENT_SECRET` 的替代方案） |
| `AZURE_FEDERATED_TOKEN_FILE` | AKS Workload Identity / OIDC 流程的联合 token 文件路径 |
| `AZURE_AUTHORITY_HOST` | 主权云 authority 覆盖（例如 Azure Government 使用 `https://login.microsoftonline.us`）。参见 [Azure Foundry 指南](/guides/azure-foundry#sovereign-clouds-government-china) |
| `IDENTITY_ENDPOINT` / `MSI_ENDPOINT` | App Service、Functions 和 Container Apps 的托管标识端点；VM 通常使用 IMDS 而不设置这些变量 |
| `HF_TOKEN` | Hugging Face Inference Providers token（[huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)） |
| `HF_BASE_URL` | 覆盖 Hugging Face base URL（默认：`https://router.huggingface.co/v1`） |
| `GOOGLE_API_KEY` | Google AI Studio API 密钥（[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)） |
| `GEMINI_API_KEY` | `GOOGLE_API_KEY` 的别名 |
| `GEMINI_BASE_URL` | 覆盖 Google AI Studio base URL |
| `ANTHROPIC_API_KEY` | Anthropic Console API 密钥（[console.anthropic.com](https://console.anthropic.com/)） |
| `ANTHROPIC_BASE_URL` | 覆盖 Anthropic API base URL |
| `ANTHROPIC_TOKEN` | 手动或旧版 Anthropic OAuth/setup-token 覆盖 |
| `DASHSCOPE_API_KEY` | Qwen Cloud（阿里巴巴 DashScope）Qwen 模型 API 密钥（[modelstudio.console.alibabacloud.com](https://modelstudio.console.alibabacloud.com/)） |
| `DASHSCOPE_BASE_URL` | 自定义 DashScope base URL（默认：`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`；中国大陆区域使用 `https://dashscope.aliyuncs.com/compatible-mode/v1`） |
| `ALIBABA_CODING_PLAN_API_KEY` | Qwen Coding Plan API 密钥（`alibaba-coding-plan` provider） |
| `ALIBABA_CODING_PLAN_BASE_URL` | 覆盖 Qwen Coding Plan base URL |
| `DEEPSEEK_API_KEY` | 直接访问 DeepSeek 的 API 密钥（[platform.deepseek.com](https://platform.deepseek.com/api_keys)） |
| `DEEPSEEK_BASE_URL` | 自定义 DeepSeek API base URL |
| `NOVITA_API_KEY` | NovitaAI API 密钥——面向 Model API、Agent Sandbox 和 GPU Cloud 的 AI 原生云（[novita.ai/settings/key-management](https://novita.ai/settings/key-management)） |
| `NOVITA_BASE_URL` | 覆盖 NovitaAI base URL（默认：`https://api.novita.ai/openai/v1`） |
| `NVIDIA_API_KEY` | NVIDIA NIM API 密钥——Nemotron 及开源模型（[build.nvidia.com](https://build.nvidia.com)） |
| `NVIDIA_BASE_URL` | 覆盖 NVIDIA base URL（默认：`https://integrate.api.nvidia.com/v1`；本地 NIM 端点设为 `http://localhost:8000/v1`） |
| `STEPFUN_API_KEY` | StepFun API 密钥——Step 系列模型（[platform.stepfun.com](https://platform.stepfun.com)） |
| `STEPFUN_BASE_URL` | 覆盖 StepFun base URL（默认：`https://api.stepfun.com/v1`） |
| `OLLAMA_API_KEY` | Ollama Cloud API 密钥——无需本地 GPU 的托管 Ollama 目录（[ollama.com/settings/keys](https://ollama.com/settings/keys)） |
| `OLLAMA_BASE_URL` | 覆盖 Ollama Cloud base URL（默认：`https://ollama.com/v1`） |
| `XAI_API_KEY` | xAI（Grok）API 密钥，支持聊天、TTS 和网络搜索（[console.x.ai](https://console.x.ai/)） |
| `XAI_BASE_URL` | 覆盖 xAI base URL（默认：`https://api.x.ai/v1`） |
| `MISTRAL_API_KEY` | Mistral API 密钥，用于 Voxtral TTS 和 Voxtral STT（[console.mistral.ai](https://console.mistral.ai)） |
| `AWS_REGION` | Bedrock 推理的 AWS 区域（例如 `us-east-1`、`eu-central-1`）。由 boto3 读取。 |
| `AWS_PROFILE` | Bedrock 认证的 AWS 命名配置文件（读取 `~/.aws/credentials`）。不设置则使用默认 boto3 凭证链。 |
| `BEDROCK_BASE_URL` | 覆盖 Bedrock runtime base URL（默认：`https://bedrock-runtime.us-east-1.amazonaws.com`；通常不设置，改用 `AWS_REGION`） |
| `HERMES_QWEN_BASE_URL` | Qwen Portal base URL 覆盖（默认：`https://portal.qwen.ai/v1`） |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen API 密钥——按需付费访问精选模型（[opencode.ai](https://opencode.ai/auth)） |
| `OPENCODE_ZEN_BASE_URL` | 覆盖 OpenCode Zen base URL |
| `OPENCODE_GO_API_KEY` | OpenCode Go API 密钥——$10/月订阅开源模型（[opencode.ai](https://opencode.ai/auth)） |
| `OPENCODE_GO_BASE_URL` | 覆盖 OpenCode Go base URL |
| `CLAUDE_CODE_OAUTH_TOKEN` | 手动导出时的显式 Claude Code token 覆盖 |
| `HERMES_MODEL` | 在进程级别覆盖模型名称（供 cron 调度器使用；正常使用请优先在 `config.yaml` 中配置） |
| `VOICE_TOOLS_OPENAI_KEY` | OpenAI 语音转文字和文字转语音提供商的首选 OpenAI 密钥 |
| `HERMES_LOCAL_STT_COMMAND` | 可选的本地语音转文字命令模板。支持 `{input_path}`、`{output_dir}`、`{language}` 和 `{model}` 占位符 |
| `HERMES_LOCAL_STT_LANGUAGE` | 传递给 `HERMES_LOCAL_STT_COMMAND` 或自动检测的本地 `whisper` CLI 回退的默认语言（默认：`en`） |
| `HERMES_HOME` | 覆盖 Hermes 配置目录（默认：`~/.hermes`）。同时限定 gateway PID 文件和 systemd 服务名称，允许多个安装并发运行 |
| `HERMES_GIT_BASH_PATH` | **仅 Windows。** 覆盖终端工具的 `bash.exe` 发现路径。可指向任意 bash——完整 Git-for-Windows 安装、通过符号链接的 WSL bash、MSYS2、Cygwin。安装程序会自动将其设置为所配置的 PortableGit。参见 [Windows（原生）指南](../user-guide/windows-native.md#how-hermes-runs-shell-commands-on-windows) |
| `HERMES_DISABLE_WINDOWS_UTF8` | **仅 Windows。** 设为 `1` 可禁用 UTF-8 stdio shim（`configure_windows_stdio()`），回退到控制台的本地代码页。用于排查编码问题；正常操作中极少需要 |
| `HERMES_KANBAN_HOME` | 覆盖锚定 kanban 看板（数据库 + 工作区 + 工作日志）的共享 Hermes 根目录。回退到 `get_default_hermes_root()`（任意活动 profile 的父目录）。适用于测试和非常规部署 |
| `HERMES_KANBAN_BOARD` | 为当前进程固定活动 kanban 看板。优先于 `~/.hermes/kanban/current`；调度器将其注入工作进程子进程环境，使工作进程无法看到其他看板上的任务。默认为 `default`。slug 验证：小写字母数字 + 连字符 + 下划线，1-64 字符 |
| `HERMES_KANBAN_DB` | 直接固定 kanban 数据库文件路径（最高优先级；优先于 `HERMES_KANBAN_BOARD` 和 `HERMES_KANBAN_HOME`）。调度器将其注入工作进程子进程环境，使 profile 工作进程收敛到调度器的看板 |
| `HERMES_KANBAN_WORKSPACES_ROOT` | 直接固定 kanban 工作区根目录（工作区最高优先级；优先于 `HERMES_KANBAN_HOME`）。调度器将其注入工作进程子进程环境 |
| `HERMES_KANBAN_DISPATCH_IN_GATEWAY` | `kanban.dispatch_in_gateway` 的运行时覆盖。设为 `0`、`false`、`no` 或 `off` 可阻止 gateway 启动内嵌 Kanban 调度器；任何其他非空值则启用。适用于独立调度器进程拥有看板的场景。 |

## 提供商认证（OAuth）

对于原生 Anthropic 认证，Hermes 在 Claude Code 自身凭证文件存在时优先使用，因为这些凭证可以自动刷新。**针对 Anthropic 的 OAuth 需要购买了额外使用额度的 Claude Max 计划**——Hermes 以 Claude Code 身份路由，仅消耗 Max 计划的额外/超额额度，不消耗基础 Max 配额，且不适用于 Claude Pro。没有 Max + 额外额度时，请改用 API 密钥。`ANTHROPIC_TOKEN` 等环境变量作为手动覆盖仍然有用，但不再是 Claude Max 登录的首选路径。

| 变量 | 描述 |
|----------|-------------|
| `HERMES_PORTAL_BASE_URL` | 覆盖 Nous Portal URL（用于开发/测试） |
| `NOUS_INFERENCE_BASE_URL` | 覆盖 Nous 推理 API URL |
| `HERMES_NOUS_MIN_KEY_TTL_SECONDS` | 重新铸造前的最小 agent 密钥 TTL（默认：1800 = 30 分钟） |
| `HERMES_NOUS_TIMEOUT_SECONDS` | Nous 凭证/token 流程的 HTTP 超时 |
| `HERMES_DUMP_REQUESTS` | 将 API 请求载荷转储到日志文件（`true`/`false`） |
| `HERMES_PREFILL_MESSAGES_FILE` | 包含在 API 调用时注入的临时预填消息的 JSON 文件路径 |
| `HERMES_TIMEZONE` | IANA 时区覆盖（例如 `America/New_York`） |

## 工具 API

| 变量 | 描述 |
|----------|-------------|
| `PARALLEL_API_KEY` | AI 原生网络搜索（[parallel.ai](https://parallel.ai/)） |
| `FIRECRAWL_API_KEY` | 网页抓取和云浏览器（[firecrawl.dev](https://firecrawl.dev/)） |
| `FIRECRAWL_API_URL` | 自托管实例的自定义 Firecrawl API 端点（可选） |
| `TAVILY_API_KEY` | Tavily API 密钥，用于 AI 原生网络搜索、提取和爬取（[app.tavily.com](https://app.tavily.com/home)） |
| `SEARXNG_URL` | 免费自托管网络搜索的 SearXNG 实例 URL——无需 API 密钥（[searxng.github.io](https://searxng.github.io/searxng/)） |
| `TAVILY_BASE_URL` | 覆盖 Tavily API 端点。适用于企业代理和自托管 Tavily 兼容搜索后端。与 `GROQ_BASE_URL` 模式相同。 |
| `EXA_API_KEY` | Exa API 密钥，用于 AI 原生网络搜索和内容获取（[exa.ai](https://exa.ai/)） |
| `BRAVE_SEARCH_API_KEY` | 用于网络搜索的 Brave Search API 订阅 token（提供免费额度）（[brave.com/search/api](https://brave.com/search/api/)） |
| `BROWSERBASE_API_KEY` | 浏览器自动化（[browserbase.com](https://browserbase.com/)） |
| `BROWSERBASE_PROJECT_ID` | Browserbase 项目 ID |
| `BROWSER_USE_API_KEY` | Browser Use 云浏览器 API 密钥（[browser-use.com](https://browser-use.com/)） |
| `FIRECRAWL_BROWSER_TTL` | Firecrawl 浏览器会话 TTL（秒，默认：300） |
| `BROWSER_CDP_URL` | 本地浏览器的 Chrome DevTools Protocol（CDP）URL（通过 `/browser connect` 设置，例如 `ws://localhost:9222`） |
| `CAMOFOX_URL` | Camofox 本地反检测浏览器 URL（默认：`http://localhost:9377`） |
| `CAMOFOX_USER_ID` | 可选的外部管理 Camofox 用户 ID，用于共享可见会话 |
| `CAMOFOX_SESSION_KEY` | 为 `CAMOFOX_USER_ID` 创建标签页时使用的可选 Camofox 会话密钥 |
| `CAMOFOX_ADOPT_EXISTING_TAB` | 设为 `true` 可在创建新标签页前复用现有 Camofox 标签页 |
| `BROWSER_INACTIVITY_TIMEOUT` | 浏览器会话不活动超时（秒） |
| `AGENT_BROWSER_ARGS` | 额外的 Chromium 启动标志（逗号或换行分隔）。以 root 身份运行或在 AppArmor 限制的非特权用户命名空间（Ubuntu 23.10+、DGX Spark、许多容器镜像）中运行时，Hermes 自动注入 `--no-sandbox,--disable-dev-shm-usage`；仅在需要覆盖或添加其他标志时手动设置。 |
| `AGENT_BROWSER_ENGINE` | 本地模式的浏览器引擎：`auto`（默认——通过 CDP 使用 Chromium 系浏览器），或指定引擎覆盖。 |
| `FAL_KEY` | 图像生成（[fal.ai](https://fal.ai/)） |
| `KREA_API_KEY` | 用于 Krea 2 图像生成的 Krea API 密钥（[krea.ai](https://krea.ai/)） |
| `GROQ_API_KEY` | Groq Whisper STT API 密钥（[groq.com](https://groq.com/)） |
| `ELEVENLABS_API_KEY` | ElevenLabs 高级 TTS 语音（[elevenlabs.io](https://elevenlabs.io/)） |
| `STT_GROQ_MODEL` | 覆盖 Groq STT 模型（默认：`whisper-large-v3-turbo`） |
| `GROQ_BASE_URL` | 覆盖 Groq OpenAI 兼容 STT 端点 |
| `STT_OPENAI_MODEL` | 覆盖 OpenAI STT 模型（默认：`whisper-1`） |
| `STT_OPENAI_BASE_URL` | 覆盖 OpenAI 兼容 STT 端点 |
| `GITHUB_TOKEN` | Skills Hub 的 GitHub token（更高 API 速率限制，技能发布） |
| `HONCHO_API_KEY` | 跨会话用户建模（[honcho.dev](https://honcho.dev/)） |
| `HONCHO_BASE_URL` | 自托管 Honcho 实例的 base URL（默认：Honcho 云）。本地实例无需 API 密钥 |
| `HINDSIGHT_TIMEOUT` | Hindsight 内存提供商 API 调用超时（秒，默认：`60`）。如果 Hindsight 实例在 `/sync` 或 `on_session_switch` 期间响应缓慢并出现超时，请增大此值，并检查 `errors.log`。 |
| `SUPERMEMORY_API_KEY` | 支持 profile 召回和会话摄取的语义长期记忆（[supermemory.ai](https://supermemory.ai)） |
| `DAYTONA_API_KEY` | Daytona 云沙箱（[daytona.io](https://daytona.io/)） |

### Skill API 密钥

由特定内置/可选技能使用的密钥。仅在你使用对应技能时才需要设置。

| 变量 | 使用它的技能 | 描述 |
|----------|---------------|-------------|
| `NOTION_API_KEY` | `notion` | Notion 集成 token。 |
| `LINEAR_API_KEY` | `linear` | Linear 个人 API 密钥。 |
| `AIRTABLE_API_KEY` | `airtable` | Airtable 个人访问 token。 |
| `TENOR_API_KEY` | `gif-search` | 用于 GIF 搜索的 Tenor API 密钥。 |

### Langfuse 可观测性

内置 [`observability/langfuse`](/user-guide/features/built-in-plugins#observabilitylangfuse) 插件的环境变量。在 `~/.hermes/.env` 中设置。在这些变量生效之前，还必须启用该插件（`hermes plugins enable observability/langfuse`，或在 `hermes plugins` 中勾选）。

| 变量 | 描述 |
|----------|-------------|
| `HERMES_LANGFUSE_PUBLIC_KEY` | Langfuse 项目公钥（`pk-lf-...`）。必填。 |
| `HERMES_LANGFUSE_SECRET_KEY` | Langfuse 项目密钥（`sk-lf-...`）。必填。 |
| `HERMES_LANGFUSE_BASE_URL` | Langfuse 服务器 URL（默认：`https://cloud.langfuse.com`）。自托管时设置。 |
| `HERMES_LANGFUSE_ENV` | trace 上的环境标签（`production`、`staging` 等） |
| `HERMES_LANGFUSE_RELEASE` | trace 上的发布/版本标签 |
| `HERMES_LANGFUSE_SAMPLE_RATE` | SDK 采样率 0.0–1.0（默认：`1.0`） |
| `HERMES_LANGFUSE_MAX_CHARS` | 序列化载荷的每字段截断长度（默认：`12000`） |
| `HERMES_LANGFUSE_DEBUG` | `true` 可将详细插件日志输出到 `agent.log` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL` | 标准 Langfuse SDK 变量名。当对应的 `HERMES_LANGFUSE_*` 未设置时作为回退。 |

### Nous Tool Gateway

这些变量为付费 Nous 订阅者或自托管 gateway 部署配置 [Tool Gateway](/user-guide/features/tool-gateway)。大多数用户无需设置——gateway 通过 `hermes model` 或 `hermes tools` 自动配置。

| 变量 | 描述 |
|----------|-------------|
| `TOOL_GATEWAY_DOMAIN` | Tool Gateway 路由的基础域名（默认：`nousresearch.com`） |
| `TOOL_GATEWAY_SCHEME` | gateway URL 的 HTTP 或 HTTPS 协议（默认：`https`） |
| `TOOL_GATEWAY_USER_TOKEN` | Tool Gateway 的认证 token（通常由 Nous 认证自动填充） |
| `FIRECRAWL_GATEWAY_URL` | 专门覆盖 Firecrawl gateway 端点的 URL |

## 终端后端

| 变量 | 描述 |
|----------|-------------|
| `TERMINAL_ENV` | 后端：`local`、`docker`、`ssh`、`singularity`、`modal`、`daytona` |
| `HERMES_DOCKER_BINARY` | 覆盖 Hermes 调用的容器二进制（例如 `podman`、`/usr/local/bin/docker`）。未设置时，Hermes 自动在 `PATH` 上发现 `docker` 或 `podman`。当两者都已安装且需要非默认选项，或二进制不在 `PATH` 中时使用。 |
| `TERMINAL_DOCKER_IMAGE` | Docker 镜像（默认：`nikolaik/python-nodejs:python3.11-nodejs20`） |
| `TERMINAL_DOCKER_FORWARD_ENV` | 显式转发到 Docker 终端会话的环境变量名 JSON 数组。注意：技能声明的 `required_environment_variables` 会自动转发——仅对未被任何技能声明的变量使用此项。 |
| `TERMINAL_DOCKER_VOLUMES` | 额外的 Docker 卷挂载（逗号分隔的 `host:container` 对） |
| `TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE` | 高级选项：将启动时的 cwd 挂载到 Docker `/workspace`（`true`/`false`，默认：`false`） |
| `TERMINAL_SINGULARITY_IMAGE` | Singularity 镜像或 `.sif` 路径 |
| `TERMINAL_MODAL_IMAGE` | Modal 容器镜像 |
| `TERMINAL_DAYTONA_IMAGE` | Daytona 沙箱镜像 |
| `TERMINAL_TIMEOUT` | 命令超时（秒） |
| `TERMINAL_LIFETIME_SECONDS` | 终端会话最大生命周期（秒） |
| `TERMINAL_CWD` | 针对 gateway/cron 终端会话的已弃用直接覆盖。请优先使用 `config.yaml` 中的 `terminal.cwd`；CLI 仍使用启动目录。 |
| `SUDO_PASSWORD` | 无需交互提示即可使用 sudo |

对于云沙箱后端，持久化以文件系统为导向。`TERMINAL_LIFETIME_SECONDS` 控制 Hermes 何时清理空闲终端会话，后续恢复可能会重新创建沙箱而非保持相同的活跃进程。

## SSH 后端

| 变量 | 描述 |
|----------|-------------|
| `TERMINAL_SSH_HOST` | 远程服务器主机名 |
| `TERMINAL_SSH_USER` | SSH 用户名 |
| `TERMINAL_SSH_PORT` | SSH 端口（默认：22） |
| `TERMINAL_SSH_KEY` | 私钥路径 |
| `TERMINAL_SSH_PERSISTENT` | 覆盖 SSH 的持久 shell（默认：跟随 `TERMINAL_PERSISTENT_SHELL`） |

## 容器资源（Docker、Singularity、Modal、Daytona）

| 变量 | 描述 |
|----------|-------------|
| `TERMINAL_CONTAINER_CPU` | CPU 核心数（默认：1） |
| `TERMINAL_CONTAINER_MEMORY` | 内存（MB，默认：5120） |
| `TERMINAL_CONTAINER_DISK` | 磁盘（MB，默认：51200） |
| `TERMINAL_CONTAINER_PERSISTENT` | 跨会话持久化容器文件系统（默认：`true`） |
| `TERMINAL_SANDBOX_DIR` | 工作区和 overlay 的宿主机目录（默认：`~/.hermes/sandboxes/`） |

## 持久 Shell

| 变量 | 描述 |
|----------|-------------|
| `TERMINAL_PERSISTENT_SHELL` | 为非本地后端启用持久 shell（默认：`true`）。也可通过 config.yaml 中的 `terminal.persistent_shell` 设置 |
| `TERMINAL_LOCAL_PERSISTENT` | 为本地后端启用持久 shell（默认：`false`） |
| `TERMINAL_SSH_PERSISTENT` | 覆盖 SSH 后端的持久 shell（默认：跟随 `TERMINAL_PERSISTENT_SHELL`） |

## 消息平台

| 变量 | 描述 |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token（来自 @BotFather） |
| `TELEGRAM_ALLOWED_USERS` | 允许使用 bot 的逗号分隔用户 ID（适用于私聊、群组和论坛） |
| `TELEGRAM_ALLOW_ALL_USERS` | 允许任何 Telegram 用户触发机器人（仅限开发环境）。 |
| `TELEGRAM_GROUP_ALLOWED_USERS` | 仅在群组/论坛中授权的逗号分隔发送者用户 ID（**不**授予私聊权限）。以 `-` 开头的聊天 ID 形式值仍作为聊天 ID 处理，以向后兼容 #17686 之前的配置，并显示弃用警告。 |
| `TELEGRAM_GROUP_ALLOWED_CHATS` | 逗号分隔的群组/论坛聊天 ID；任意成员均可授权 |
| `TELEGRAM_HOME_CHANNEL` | cron 投递的默认 Telegram 聊天/频道 |
| `TELEGRAM_HOME_CHANNEL_NAME` | Telegram 主频道的显示名称 |
| `TELEGRAM_CRON_THREAD_ID` | 接收 cron 投递的论坛话题 ID；仅对 cron 覆盖 `TELEGRAM_HOME_CHANNEL_THREAD_ID`。在话题模式下使用，使 cron 消息的回复开启新会话而非进入系统大厅（#24409）。 |
| `TELEGRAM_WEBHOOK_URL` | webhook 模式的公共 HTTPS URL（启用 webhook 而非轮询） |
| `TELEGRAM_WEBHOOK_PORT` | webhook 服务器本地监听端口（默认：`8443`） |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram 在每次更新中回传的密钥 token，用于验证。**设置 `TELEGRAM_WEBHOOK_URL` 时必填**——未设置时 gateway 拒绝启动（GHSA-3vpc-7q5r-276h）。使用 `openssl rand -hex 32` 生成。 |
| `TELEGRAM_REACTIONS` | 处理期间在消息上启用 emoji 反应（默认：`false`） |
| `TELEGRAM_REQUIRE_MENTION` | 在 Telegram 群组中响应前要求显式触发。等同于 `config.yaml` 中的 `telegram.require_mention`。 |
| `TELEGRAM_MENTION_PATTERNS` | 启用 Telegram 群组 mention 门控时接受的正则唤醒词模式，JSON 数组、换行分隔列表或逗号分隔列表。等同于 `telegram.mention_patterns`。 |
| `TELEGRAM_EXCLUSIVE_BOT_MENTIONS` | 启用后，Telegram 群组中的显式 `@...bot` mention 仅路由到被 mention 的 bot 用户名，然后再执行回复或唤醒词回退。默认：`true`。等同于 `telegram.exclusive_bot_mentions`。 |
| `TELEGRAM_REPLY_TO_MODE` | 回复引用行为：`off`、`first`（默认）或 `all`。与 Discord 模式一致。 |
| `TELEGRAM_IGNORED_THREADS` | bot 永不响应的逗号分隔 Telegram 论坛话题/线程 ID |
| `TELEGRAM_PROXY` | Telegram 连接的代理 URL——覆盖 `HTTPS_PROXY`。支持 `http://`、`https://`、`socks5://` |
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `DISCORD_ALLOWED_USERS` | 允许使用 bot 的逗号分隔 Discord 用户 ID |
| `DISCORD_ALLOW_ALL_USERS` | 允许任何 Discord 用户触发机器人（仅限开发环境）。 |
| `DISCORD_ALLOWED_ROLES` | 允许使用 bot 的逗号分隔 Discord 角色 ID（与 `DISCORD_ALLOWED_USERS` 取 OR）。自动启用 Members intent。适用于管理团队频繁变动的场景——角色授权自动传播。 |
| `DISCORD_ALLOWED_CHANNELS` | 逗号分隔的 Discord 频道 ID。设置后，bot 仅在这些频道（以及允许的私聊）中响应。覆盖 `config.yaml` 中的 `discord.allowed_channels`。 |
| `DISCORD_PROXY` | Discord 连接的代理 URL——覆盖 `HTTPS_PROXY`。支持 `http://`、`https://`、`socks5://` |
| `DISCORD_HOME_CHANNEL` | cron 投递的默认 Discord 频道 |
| `DISCORD_HOME_CHANNEL_NAME` | Discord 主频道的显示名称 |
| `DISCORD_COMMAND_SYNC_POLICY` | Discord 斜杠命令启动同步策略：`safe`（差异对比并协调）、`bulk`（旧版 `tree.sync()`）或 `off` |
| `DISCORD_REQUIRE_MENTION` | 在服务器频道中响应前要求 @mention |
| `DISCORD_FREE_RESPONSE_CHANNELS` | 不需要 mention 的逗号分隔频道 ID |
| `DISCORD_AUTO_THREAD` | 支持时自动将长回复转为线程 |
| `DISCORD_ALLOW_ANY_ATTACHMENT` | 设为 `true` 时接受任意文件类型的附件（不仅限于内置的 PDF/文本/zip/office 白名单）。未知类型被缓存并以本地路径形式提供给 agent，供其通过 `terminal`/`read_file`/`ffprobe` 检查。默认 `false`。 |
| `DISCORD_MAX_ATTACHMENT_BYTES` | gateway 缓存的每个附件最大字节数。默认 `33554432`（32 MiB）。设为 `0` 表示无上限（附件在写入时保存在内存中）。 |
| `DISCORD_REACTIONS` | 处理期间在消息上启用 emoji 反应（默认：`true`） |
| `DISCORD_IGNORED_CHANNELS` | bot 永不响应的逗号分隔频道 ID |
| `DISCORD_NO_THREAD_CHANNELS` | bot 不自动创建线程的逗号分隔频道 ID |
| `DISCORD_REPLY_TO_MODE` | 回复引用行为：`off`、`first`（默认）或 `all` |
| `DISCORD_ALLOW_MENTION_EVERYONE` | 允许 bot ping `@everyone`/`@here`（默认：`false`）。参见 [Mention 控制](../user-guide/messaging/discord.md#mention-control)。 |
| `DISCORD_ALLOW_MENTION_ROLES` | 允许 bot ping `@role` mention（默认：`false`）。 |
| `DISCORD_ALLOW_MENTION_USERS` | 允许 bot ping 单个 `@user` mention（默认：`true`）。 |
| `DISCORD_ALLOW_MENTION_REPLIED_USER` | 回复消息时 ping 原作者（默认：`true`）。 |
| `SLACK_BOT_TOKEN` | Slack bot token（`xoxb-...`） |
| `SLACK_APP_TOKEN` | Slack 应用级 token（`xapp-...`，Socket Mode 必需） |
| `SLACK_ALLOWED_USERS` | 逗号分隔的 Slack 用户 ID |
| `SLACK_ALLOW_ALL_USERS` | 允许任何 Slack 用户触发机器人（仅限开发环境）。 |
| `SLACK_HOME_CHANNEL` | cron 投递的默认 Slack 频道 |
| `SLACK_HOME_CHANNEL_NAME` | Slack 主频道的显示名称 |
| `GOOGLE_CHAT_PROJECT_ID` | 托管 Pub/Sub 话题的 GCP 项目（回退到 `GOOGLE_CLOUD_PROJECT`） |
| `GOOGLE_CHAT_SUBSCRIPTION_NAME` | 完整 Pub/Sub 订阅路径，`projects/{proj}/subscriptions/{sub}`（旧版别名：`GOOGLE_CHAT_SUBSCRIPTION`） |
| `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON` | Service Account JSON 文件路径，或内联 JSON（回退到 `GOOGLE_APPLICATION_CREDENTIALS`） |
| `GOOGLE_CHAT_ALLOWED_USERS` | 允许与 bot 聊天的逗号分隔用户邮箱 |
| `GOOGLE_CHAT_ALLOW_ALL_USERS` | 允许任意 Google Chat 用户触发 bot（仅用于开发） |
| `GOOGLE_CHAT_HOME_CHANNEL` | cron 投递的默认空间（例如 `spaces/AAAA...`） |
| `GOOGLE_CHAT_HOME_CHANNEL_NAME` | Google Chat 主空间的显示名称 |
| `GOOGLE_CHAT_MAX_MESSAGES` | Pub/Sub FlowControl 最大在途消息数（默认：`1`） |
| `GOOGLE_CHAT_MAX_BYTES` | Pub/Sub FlowControl 最大在途字节数（默认：`16777216`，16 MiB） |
| `GOOGLE_CHAT_BOOTSTRAP_SPACES` | 启动时探测以解析 bot 自身 `users/{id}` 的逗号分隔额外空间 ID |
| `GOOGLE_CHAT_DEBUG_RAW` | 设置任意值可在 DEBUG 级别记录脱敏的 Pub/Sub 信封（仅用于调试） |
| `WHATSAPP_ENABLED` | 启用 WhatsApp 桥接（`true`/`false`） |
| `WHATSAPP_MODE` | `bot`（独立号码）或 `self-chat`（给自己发消息） |
| `WHATSAPP_ALLOWED_USERS` | 逗号分隔的手机号码（含国家代码，不含 `+`），或 `*` 允许所有发送者 |
| `WHATSAPP_ALLOW_ALL_USERS` | 无需白名单允许所有 WhatsApp 发送者（`true`/`false`） |
| `WHATSAPP_HOME_CHANNEL` | 用于 cron / 通知投递的默认聊天 ID。 |
| `WHATSAPP_HOME_CHANNEL_NAME` | WhatsApp 主频道的显示名称。 |
| `WHATSAPP_DEBUG` | 在桥接中记录原始消息事件以供排查（`true`/`false`） |
| `WHATSAPP_CLOUD_PHONE_NUMBER_ID` | 来自 WhatsApp Business Cloud API 的 Meta Phone Number ID（15–17 位数字；**不是**电话号码本身） |
| `WHATSAPP_CLOUD_ACCESS_TOKEN` | Meta 访问 token（以 `EAA` 开头）；临时 token 24 小时后过期，System User token 为永久有效 |
| `WHATSAPP_CLOUD_APP_SECRET` | 用于校验入站 webhook 签名的 32 位十六进制 app secret |
| `WHATSAPP_CLOUD_VERIFY_TOKEN` | 用于 Meta webhook 验证握手的共享密钥（由配置向导自动生成） |
| `WHATSAPP_CLOUD_ALLOWED_USERS` | 允许向机器人发消息的 `wa_id` 逗号分隔列表（带国家码、不含 `+` 的电话号码） |
| `WHATSAPP_CLOUD_ALLOW_ALL_USERS` | 无需白名单即允许所有 WhatsApp Cloud 发送者（`true`/`false`） |
| `WHATSAPP_CLOUD_APP_ID` | 可选的 Meta App ID（用于未来的分析集成） |
| `WHATSAPP_CLOUD_WABA_ID` | 可选的 WhatsApp Business Account ID（用于未来的分析集成） |
| `WHATSAPP_CLOUD_WEBHOOK_HOST` | 入站 webhook 服务器绑定的网卡（默认 `0.0.0.0`） |
| `WHATSAPP_CLOUD_WEBHOOK_PORT` | 入站 webhook 服务器绑定的端口（默认 `8090`） |
| `WHATSAPP_CLOUD_WEBHOOK_PATH` | Meta 投递入站消息的 URL 路径（默认 `/whatsapp/webhook`） |
| `WHATSAPP_CLOUD_API_VERSION` | 调用的 Meta Graph API 版本（默认 `v20.0`） |
| `WHATSAPP_CLOUD_HOME_CHANNEL` | 用作机器人主频道的 `wa_id`（用于 cron 任务等） |
| `WHATSAPP_CLOUD_DM_POLICY` | Cloud 适配器的私信门控（`open`/`allowlist`/`disabled`）；未设置时回退到 `WHATSAPP_DM_POLICY` |
| `WHATSAPP_CLOUD_ALLOW_FROM` | `dm_policy: allowlist` 时允许的发送者逗号分隔列表（裸 `wa_id`；Baileys 风格的 JID 会被规范化） |
| `WHATSAPP_CLOUD_GROUP_POLICY` | Cloud 适配器的群组门控（`open`/`allowlist`/`disabled`）；未设置时回退到 `WHATSAPP_GROUP_POLICY` |
| `WHATSAPP_CLOUD_GROUP_ALLOW_FROM` | `group_policy: allowlist` 时允许的群聊 ID 逗号分隔列表 |
| `SIGNAL_HTTP_URL` | signal-cli 守护进程 HTTP 端点（例如 `http://127.0.0.1:8080`） |
| `SIGNAL_ACCOUNT` | E.164 格式的 bot 手机号码 |
| `SIGNAL_ALLOWED_USERS` | 逗号分隔的 E.164 手机号码或 UUID |
| `SIGNAL_GROUP_ALLOWED_USERS` | 逗号分隔的群组 ID，或 `*` 表示所有群组 |
| `SIGNAL_HOME_CHANNEL_NAME` | Signal 主频道的显示名称 |
| `SIGNAL_IGNORE_STORIES` | 忽略 Signal 故事/状态更新 |
| `SIGNAL_ALLOW_ALL_USERS` | 无需白名单允许所有 Signal 用户 |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID（与电话技能共享） |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token（与电话技能共享；也用于 webhook 签名验证） |
| `TWILIO_PHONE_NUMBER` | E.164 格式的 Twilio 手机号码（与电话技能共享） |
| `SMS_WEBHOOK_URL` | Twilio 签名验证的公共 URL——必须与 Twilio Console 中的 webhook URL 一致（必填） |
| `SMS_WEBHOOK_PORT` | 入站 SMS 的 webhook 监听端口（默认：`8080`） |
| `SMS_WEBHOOK_HOST` | webhook 绑定地址（默认：`0.0.0.0`） |
| `SMS_INSECURE_NO_SIGNATURE` | 设为 `true` 可禁用 Twilio 签名验证（仅用于本地开发——不适用于生产环境） |
| `SMS_ALLOWED_USERS` | 允许聊天的逗号分隔 E.164 手机号码 |
| `SMS_ALLOW_ALL_USERS` | 无需白名单允许所有 SMS 发送者 |
| `SMS_HOME_CHANNEL` | cron 任务/通知投递的手机号码 |
| `SMS_HOME_CHANNEL_NAME` | SMS 主频道的显示名称 |
| `EMAIL_ADDRESS` | Email gateway 适配器的邮箱地址 |
| `EMAIL_PASSWORD` | 邮箱账户的密码或应用密码 |
| `EMAIL_IMAP_HOST` | 邮件适配器的 IMAP 主机名 |
| `EMAIL_IMAP_PORT` | IMAP 端口 |
| `EMAIL_SMTP_HOST` | 邮件适配器的 SMTP 主机名 |
| `EMAIL_SMTP_PORT` | SMTP 端口 |
| `EMAIL_ALLOWED_USERS` | 允许向 bot 发送消息的逗号分隔邮箱地址 |
| `EMAIL_HOME_ADDRESS` | 主动邮件投递的默认收件人 |
| `EMAIL_HOME_ADDRESS_NAME` | 邮件主目标的显示名称 |
| `EMAIL_POLL_INTERVAL` | 邮件轮询间隔（秒） |
| `EMAIL_ALLOW_ALL_USERS` | 允许所有入站邮件发送者 |
| `DINGTALK_CLIENT_ID` | 来自开发者门户的钉钉 bot AppKey（[open.dingtalk.com](https://open.dingtalk.com)） |
| `DINGTALK_CLIENT_SECRET` | 来自开发者门户的钉钉 bot AppSecret |
| `DINGTALK_ALLOWED_USERS` | 允许向 bot 发送消息的逗号分隔钉钉用户 ID |
| `DINGTALK_WEBHOOK_URL` | 用于跨平台 / cron 投递的静态机器人 webhook URL。 |
| `DINGTALK_HOME_CHANNEL` | 用于 cron / 通知投递的默认会话 ID。 |
| `DINGTALK_HOME_CHANNEL_NAME` | 钉钉主频道的显示名称。 |
| `FEISHU_APP_ID` | 来自 [open.feishu.cn](https://open.feishu.cn/) 的飞书/Lark bot App ID |
| `FEISHU_APP_SECRET` | 飞书/Lark bot App Secret |
| `FEISHU_DOMAIN` | `feishu`（中国）或 `lark`（国际）。默认：`feishu` |
| `FEISHU_CONNECTION_MODE` | `websocket`（推荐）或 `webhook`。默认：`websocket` |
| `FEISHU_ENCRYPT_KEY` | webhook 模式的可选加密密钥 |
| `FEISHU_VERIFICATION_TOKEN` | webhook 模式的可选验证 token |
| `FEISHU_ALLOWED_USERS` | 允许向 bot 发送消息的逗号分隔飞书用户 ID |
| `FEISHU_ALLOW_BOTS` | `none`（默认）/`mentions`/`all`——接受来自其他 bot 的入站消息。参见 [bot 间消息传递](../user-guide/messaging/feishu.md#bot-to-bot-messaging) |
| `FEISHU_REQUIRE_MENTION` | `true`（默认）/`false`——群组消息是否必须 @mention bot。可通过 `group_rules.<chat_id>.require_mention` 按聊天覆盖。 |
| `FEISHU_HOME_CHANNEL` | cron 投递和通知的飞书聊天 ID |
| `FEISHU_HOME_CHANNEL_NAME` | 飞书主频道的显示名称。 |
| `FEISHU_ALLOW_ALL_USERS` | 允许任何飞书用户触发机器人（仅限开发环境）。 |
| `WECOM_BOT_ID` | 来自管理控制台的企业微信 AI Bot ID |
| `WECOM_SECRET` | 企业微信 AI Bot 密钥 |
| `WECOM_WEBSOCKET_URL` | 自定义 WebSocket URL（默认：`wss://openws.work.weixin.qq.com`） |
| `WECOM_ALLOWED_USERS` | 允许向 bot 发送消息的逗号分隔企业微信用户 ID |
| `WECOM_HOME_CHANNEL` | cron 投递和通知的企业微信聊天 ID |
| `WECOM_CALLBACK_CORP_ID` | 企业微信回调自建应用的企业 Corp ID |
| `WECOM_CALLBACK_CORP_SECRET` | 自建应用的企业密钥 |
| `WECOM_CALLBACK_AGENT_ID` | 自建应用的 Agent ID |
| `WECOM_CALLBACK_TOKEN` | 回调验证 token |
| `WECOM_CALLBACK_ENCODING_AES_KEY` | 回调加密的 AES 密钥 |
| `WECOM_CALLBACK_HOST` | 回调服务器绑定地址（默认：`0.0.0.0`） |
| `WECOM_CALLBACK_PORT` | 回调服务器端口（默认：`8645`） |
| `WECOM_CALLBACK_ALLOWED_USERS` | 白名单的逗号分隔用户 ID |
| `WECOM_CALLBACK_ALLOW_ALL_USERS` | 设为 `true` 可无需白名单允许所有用户 |
| `WEIXIN_ACCOUNT_ID` | 通过 iLink Bot API 扫码登录获取的微信账号 ID |
| `WEIXIN_TOKEN` | 通过 iLink Bot API 扫码登录获取的微信认证 token |
| `WEIXIN_BASE_URL` | 覆盖微信 iLink Bot API base URL（默认：`https://ilinkai.weixin.qq.com`） |
| `WEIXIN_CDN_BASE_URL` | 覆盖媒体的微信 CDN base URL（默认：`https://novac2c.cdn.weixin.qq.com/c2c`） |
| `WEIXIN_DM_POLICY` | 私信策略：`open`、`allowlist`、`pairing`、`disabled`（默认：`open`） |
| `WEIXIN_GROUP_POLICY` | 群消息策略：`open`、`allowlist`、`disabled`（默认：`disabled`） |
| `WEIXIN_ALLOWED_USERS` | 允许私信 bot 的逗号分隔微信用户 ID |
| `WEIXIN_GROUP_ALLOWED_USERS` | 允许与 bot 互动的逗号分隔微信**群聊 ID**（非成员用户 ID）。变量名为历史遗留——期望传入群 ID。仅当 iLink 实际投递群事件时生效；扫码登录的 iLink bot 身份（`...@im.bot`）通常不接收普通微信群消息。 |
| `WEIXIN_HOME_CHANNEL` | cron 投递和通知的微信聊天 ID |
| `WEIXIN_HOME_CHANNEL_NAME` | 微信主频道的显示名称 |
| `WEIXIN_ALLOW_ALL_USERS` | 无需白名单允许所有微信用户（`true`/`false`） |
| `BLUEBUBBLES_SERVER_URL` | BlueBubbles 服务器 URL（例如 `http://192.168.1.10:1234`） |
| `BLUEBUBBLES_PASSWORD` | BlueBubbles 服务器密码 |
| `BLUEBUBBLES_WEBHOOK_HOST` | webhook 监听绑定地址（默认：`127.0.0.1`） |
| `BLUEBUBBLES_WEBHOOK_PORT` | webhook 监听端口（默认：`8645`） |
| `BLUEBUBBLES_HOME_CHANNEL` | cron/通知投递的手机/邮箱 |
| `BLUEBUBBLES_ALLOWED_USERS` | 逗号分隔的授权用户 |
| `BLUEBUBBLES_ALLOW_ALL_USERS` | 允许所有用户（`true`/`false`） |
| `QQ_APP_ID` | 来自 [q.qq.com](https://q.qq.com) 的 QQ Bot App ID |
| `QQ_CLIENT_SECRET` | 来自 [q.qq.com](https://q.qq.com) 的 QQ Bot App Secret |
| `QQ_STT_API_KEY` | 外部 STT 回退提供商的 API 密钥（可选，当 QQ 内置 ASR 未返回文本时使用） |
| `QQ_STT_BASE_URL` | 外部 STT 提供商的 base URL（可选） |
| `QQ_STT_MODEL` | 外部 STT 提供商的模型名称（可选） |
| `QQ_ALLOWED_USERS` | 允许向 bot 发送消息的逗号分隔 QQ 用户 openID |
| `QQ_GROUP_ALLOWED_USERS` | 群 @消息访问的逗号分隔 QQ 群 ID |
| `QQ_ALLOW_ALL_USERS` | 允许所有用户（`true`/`false`，覆盖 `QQ_ALLOWED_USERS`） |
| `QQBOT_HOME_CHANNEL` | cron 投递和通知的 QQ 用户/群 openID |
| `QQBOT_HOME_CHANNEL_NAME` | QQ 主频道的显示名称 |
| `QQ_PORTAL_HOST` | 覆盖 QQ portal 主机（设为 `sandbox.q.qq.com` 可通过沙箱 gateway 路由；默认：`q.qq.com`）。 |
| `QQ_SANDBOX` | 为开发测试启用 QQ 沙箱模式（`true`/`false`） |
| `MATTERMOST_URL` | Mattermost 服务器 URL（例如 `https://mm.example.com`） |
| `MATTERMOST_TOKEN` | Mattermost 的 bot token 或个人访问 token |
| `MATTERMOST_ALLOWED_USERS` | 允许向 bot 发送消息的逗号分隔 Mattermost 用户 ID |
| `MATTERMOST_ALLOW_ALL_USERS` | 允许任何 Mattermost 用户触发机器人（仅限开发环境）。 |
| `MATTERMOST_ALLOWED_CHANNELS` | 设置后，机器人只在这些频道中响应（白名单）。 |
| `MATTERMOST_HOME_CHANNEL` | 主动消息投递（cron、通知）的频道 ID |
| `MATTERMOST_REQUIRE_MENTION` | 在频道中要求 `@mention`（默认：`true`）。设为 `false` 可响应所有消息。 |
| `MATTERMOST_FREE_RESPONSE_CHANNELS` | bot 无需 `@mention` 即可响应的逗号分隔频道 ID |
| `MATTERMOST_REPLY_MODE` | 回复风格：`thread`（线程回复）或 `off`（平铺消息，默认） |
| `MATRIX_HOMESERVER` | Matrix homeserver URL（例如 `https://matrix.org`） |
| `MATRIX_ACCESS_TOKEN` | bot 认证的 Matrix 访问 token |
| `MATRIX_USER_ID` | Matrix 用户 ID（例如 `@hermes:matrix.org`）——密码登录时必填，使用访问 token 时可选 |
| `MATRIX_PASSWORD` | Matrix 密码（访问 token 的替代方案） |
| `MATRIX_ALLOWED_USERS` | 允许向 bot 发送消息的逗号分隔 Matrix 用户 ID（例如 `@alice:matrix.org`） |
| `MATRIX_ALLOW_ALL_USERS` | 允许任何 Matrix 用户触发机器人（仅限开发环境）。 |
| `MATRIX_HOME_CHANNEL` | 用于 cron / 通知投递的默认房间 ID。 |
| `MATRIX_HOME_CHANNEL_NAME` | Matrix 主房间的显示名称。 |
| `MATRIX_ALLOWED_ROOMS` | 允许触发机器人响应的 Matrix 房间 ID 逗号分隔列表 |
| `MATRIX_HOME_ROOM` | 主动消息投递的房间 ID（例如 `!abc123:matrix.org`） |
| `MATRIX_ENCRYPTION` | 启用端到端加密（`true`/`false`，默认：`false`） |
| `MATRIX_E2EE_MODE` | Matrix 端到端加密行为：`off`、`optional` 或 `required`。设置后覆盖 `MATRIX_ENCRYPTION`。 |
| `MATRIX_DEVICE_ID` | 用于 E2EE 跨重启持久化的稳定 Matrix 设备 ID（例如 `HERMES_BOT`）。不设置时，E2EE 密钥每次启动都会轮换，历史房间解密将失败。 |
| `MATRIX_REACTIONS` | 对入站消息启用处理生命周期 emoji 反应（默认：`true`）。设为 `false` 可禁用。 |
| `MATRIX_REQUIRE_MENTION` | 在房间中要求 `@mention`（默认：`true`）。设为 `false` 可响应所有消息。 |
| `MATRIX_FREE_RESPONSE_ROOMS` | bot 无需 `@mention` 即可响应的逗号分隔房间 ID |
| `MATRIX_IGNORE_USER_PATTERNS` | 需要忽略的 Matrix 桥接/appservice 幽灵用户 ID 正则表达式逗号分隔列表 |
| `MATRIX_PROCESS_NOTICES` | 处理入站 Matrix `m.notice` 事件（默认：`false`） |
| `MATRIX_SESSION_SCOPE` | 项目房间的 Matrix 会话作用域：`auto`、`room` 或 `thread`（默认：`auto`） |
| `MATRIX_TOOLS_ALLOW_CROSS_ROOM` | 允许 Matrix 工具指向当前房间以外的显式房间（默认：`false`） |
| `MATRIX_TOOLS_ALLOW_CROSS_ROOM_DESTRUCTIVE` | 允许跨房间的 Matrix 撤回/邀请类工具；需要 `MATRIX_TOOLS_ALLOW_CROSS_ROOM=true`（默认：`false`） |
| `MATRIX_TOOLS_ALLOW_REDACTION` | 允许执行 Matrix 消息撤回工具（默认：`false`） |
| `MATRIX_TOOLS_ALLOW_INVITES` | 允许执行 Matrix 邀请工具（默认：`false`） |
| `MATRIX_TOOLS_ALLOW_ROOM_CREATE` | 允许执行 Matrix 房间创建工具（默认：`false`） |
| `MATRIX_ALLOW_ROOM_MENTIONS` | 允许出站 `@room` 提及以通知全部房间成员（默认：`false`） |
| `MATRIX_AUTO_THREAD` | 为房间消息自动创建线程（默认：`true`） |
| `MATRIX_DM_AUTO_THREAD` | 为 Matrix 私信消息自动创建话题（默认：`false`） |
| `MATRIX_DM_MENTION_THREADS` | 在私聊中被 `@mentioned` 时创建线程（默认：`false`） |
| `MATRIX_APPROVAL_REQUIRE_SENDER` | 在可知的情况下，要求审批/模型选择器的反应来自原始请求者（默认：`true`） |
| `MATRIX_APPROVAL_TIMEOUT_SECONDS` | Matrix 反应式审批/模型选择器提示的超时（默认：`300`） |
| `MATRIX_ALLOW_PUBLIC_ROOMS` | 允许 Matrix 房间创建工具创建公开房间（默认：`false`） |
| `MATRIX_MAX_MEDIA_BYTES` | Matrix 媒体上传/下载的最大字节数（默认：`104857600`） |
| `MATRIX_RECOVERY_KEY` | 设备密钥轮换后交叉签名验证的恢复密钥。推荐用于启用了交叉签名的 E2EE 设置。 |
| `MATRIX_RECOVERY_KEY_OUTPUT_FILE` | 用于写出所生成 Matrix 恢复密钥的可选一次性路径。以模式 `0600` 创建，且永不覆盖。 |
| `HASS_TOKEN` | Home Assistant 长期访问 token（启用 HA 平台 + 工具） |
| `HASS_URL` | Home Assistant URL（默认：`http://homeassistant.local:8123`） |
| `WEBHOOK_ENABLED` | 启用 webhook 平台适配器（`true`/`false`） |
| `WEBHOOK_PORT` | 接收 webhook 的 HTTP 服务器端口（默认：`8644`） |
| `WEBHOOK_SECRET` | webhook 签名验证的全局 HMAC 密钥（当路由未指定自己的密钥时作为回退） |
| `API_SERVER_ENABLED` | 启用 OpenAI 兼容 API 服务器（`true`/`false`）。与其他平台并行运行。 |
| `API_SERVER_KEY` | API 服务器认证的 Bearer token。非回环绑定时强制执行。 |
| `API_SERVER_CORS_ORIGINS` | 允许直接调用 API 服务器的逗号分隔浏览器来源（例如 `http://localhost:3000,http://127.0.0.1:3000`）。默认：禁用。 |
| `API_SERVER_PORT` | API 服务器端口（默认：`8642`） |
| `API_SERVER_HOST` | API 服务器主机/绑定地址（默认：`127.0.0.1`）。使用 `0.0.0.0` 开放网络访问——需要 `API_SERVER_KEY` 和严格的 `API_SERVER_CORS_ORIGINS` 白名单。 |
| `API_SERVER_MODEL_NAME` | `/v1/models` 上公告的模型名称。默认为 profile 名称（默认 profile 为 `hermes-agent`）。适用于 Open WebUI 等前端需要每个连接使用不同模型名称的多用户场景。 |
| `GATEWAY_PROXY_URL` | 将消息转发到的远程 Hermes API 服务器 URL（[代理模式](/user-guide/messaging/matrix#proxy-mode-e2ee-on-macos)）。设置后，gateway 仅处理平台 I/O——所有 agent 工作委托给远程服务器。也可通过 `config.yaml` 中的 `gateway.proxy_url` 配置。 |
| `GATEWAY_PROXY_KEY` | 代理模式下与远程 API 服务器认证的 Bearer token。必须与远程主机上的 `API_SERVER_KEY` 一致。 |
| `MESSAGING_CWD` | 消息模式下终端命令的工作目录（默认：`~`） |
| `GATEWAY_ALLOWED_USERS` | 跨所有平台允许的逗号分隔用户 ID |
| `GATEWAY_ALLOW_ALL_USERS` | 无需白名单允许所有用户（`true`/`false`，默认：`false`） |

### Web Dashboard 与 Hermes Desktop {#web-dashboard--hermes-desktop}

[Web dashboard](/user-guide/features/web-dashboard) 以及[将 Hermes Desktop 连接到远程后端](/user-guide/features/web-dashboard#connecting-hermes-desktop-to-a-remote-backend)所用的认证。按照"仅密钥"的约定，凭据应放在 `~/.hermes/.env` 中；OAuth 的 `client_id` 更适合写在 `config.yaml` 的 `dashboard.oauth` 下（同时设置时环境变量优先）。

内置了三种 dashboard 认证 provider。对于远程 Hermes Desktop 连接或任何面向公网的 dashboard，推荐的 provider 是 **OAuth（Nous Portal）**——设置 `HERMES_DASHBOARD_OAUTH_CLIENT_ID`（用 `hermes dashboard register` 申请）。内置的**用户名/密码** provider（`HERMES_DASHBOARD_BASIC_AUTH_*`）是可信局域网内或 VPN 后端最快捷的选项，但不适合直接暴露在公网。若要针对你自己的身份提供方进行认证，请使用**自托管 OIDC** provider（`HERMES_DASHBOARD_OIDC_*`）。无论哪种方式，非回环绑定（`hermes dashboard --host 0.0.0.0`）都会启用认证门控。完整说明见 [Web Dashboard → 认证](/user-guide/features/web-dashboard#authentication-gated-mode)。

| 变量 | 描述 |
|----------|-------------|
| `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` | 内置用户名/密码 dashboard 认证 provider（`plugins/dashboard_auth/basic`）的用户名。与密码同时设置时激活该 provider。覆盖 `dashboard.basic_auth.username`。 |
| `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` | basic provider 的明文密码（加载时在内存中哈希）。优先于配置中的 `password_hash`，因此可以通过环境变量轮换。覆盖 `dashboard.basic_auth.password`。 |
| `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` | basic provider 的 scrypt 密码哈希（推荐——静态存储中无明文）。用 `python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('PW'))"` 计算。覆盖 `dashboard.basic_auth.password_hash`。 |
| `HERMES_DASHBOARD_BASIC_AUTH_SECRET` | 用于签名 basic provider 无状态会话 token 的 HMAC 密钥（32+ 字节，base64/十六进制/原始）。请显式设置，使会话能在重启后保留并跨多个 worker 生效；留空则每个进程随机生成（每次重启都会被登出）。覆盖 `dashboard.basic_auth.secret`。 |
| `HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS` | basic provider 的访问 token 有效期（默认 12 小时）。覆盖 `dashboard.basic_auth.session_ttl_seconds`。 |
| `HERMES_DASHBOARD_OAUTH_CLIENT_ID` | 门控/公开 dashboard 的 OAuth client id（`agent:{instance_id}`），用于激活 Nous provider（`plugins/dashboard_auth/nous`）。覆盖 `dashboard.oauth.client_id`。用 `hermes dashboard register` 申请。 |
| `HERMES_DASHBOARD_PUBLIC_URL` | dashboard 实际可访问的完整公开 URL，用于反向代理后构造 OAuth 回调。覆盖 `dashboard.public_url`。 |
| `HERMES_DASHBOARD_OIDC_ISSUER` | 内置自托管 OIDC provider（`plugins/dashboard_auth/self_hosted`）的 OIDC issuer URL。激活该 provider 所必需。覆盖 `dashboard.oauth.self_hosted.issuer`。 |
| `HERMES_DASHBOARD_OIDC_CLIENT_ID` | 自托管 OIDC provider 的公开 OIDC client id（授权码 + PKCE）。激活该 provider 所必需。覆盖 `dashboard.oauth.self_hosted.client_id`。 |
| `HERMES_DASHBOARD_OIDC_SCOPES` | 自托管 OIDC provider 请求的 OIDC scope（默认 `openid profile email`）。覆盖 `dashboard.oauth.self_hosted.scopes`。 |
| `HERMES_DESKTOP_REMOTE_URL` | （Desktop 侧）远程后端的 base URL，例如 `http://host:9119`。设置后会覆盖应用内的 Gateway URL；你仍需在 Gateway 设置面板中登录（OAuth 重定向或用户名/密码，取决于后端所声明的方式）。 |
| `HERMES_DESKTOP_HERMES` | Desktop 后端命令覆盖。供打包方/Nix 或故障排查使用，在后端探测之后让 Electron 指向指定的 `hermes` 可执行文件。 |
| `HERMES_DESKTOP_HERMES_ROOT` | `hermes desktop --hermes-root` 使用的 Desktop 源码检出覆盖；优先于打包的首次启动安装或 `PATH` 上已有的 `hermes` 进行检查。 |
| `HERMES_DESKTOP_IGNORE_EXISTING` | 设为 `1` 可让 Desktop 在后端解析时忽略 `PATH` 上已有的 `hermes`。等同于 `hermes desktop --ignore-existing`。 |
| `HERMES_DESKTOP_CWD` | Desktop 聊天会话的初始项目目录。由 `hermes desktop --cwd` 设置。 |
| `HERMES_DESKTOP_PYTHON` | 后端所用 Python 解释器的绝对路径，优先于 Electron 为源码检出自动解析的解释器。worktree 开发辅助工具（见 [从 worktree 运行 TUI 与 Desktop](../developer-guide/worktree-ui-dev.md)）用它来复用共享 venv。 |
| `HERMES_DESKTOP_DEV_SERVER` | Electron 外壳加载的 Vite 开发服务器 URL，用于替代打包好的产物（例如 `http://127.0.0.1:5174`）。由 `npm run dev` 自动设置；仅在开发该应用时相关。 |

### Microsoft Graph（Teams 会议） {#microsoft-graph-teams-meetings}

用于即将推出的 Teams 会议摘要流水线的 Microsoft Graph REST 客户端的仅应用凭证。Azure 门户操作步骤和所需 API 权限详见[注册 Microsoft Graph 应用程序](/guides/microsoft-graph-app-registration)。

| 变量 | 描述 |
|----------|-------------|
| `MSGRAPH_TENANT_ID` | Graph 应用注册的 Azure AD 租户 ID（目录 GUID）。 |
| `MSGRAPH_CLIENT_ID` | Azure 应用注册的应用程序（客户端）ID。 |
| `MSGRAPH_CLIENT_SECRET` | 应用注册的客户端密钥值。存储在 `~/.hermes/.env` 中并设置 `chmod 600`；定期通过 Azure 门户轮换。 |
| `MSGRAPH_SCOPE` | 客户端凭证 token 请求的 OAuth2 范围（默认：`https://graph.microsoft.com/.default`）。 |
| `MSGRAPH_AUTHORITY_URL` | Microsoft 身份平台 authority（默认：`https://login.microsoftonline.com`）。仅对国家/主权云覆盖（例如 GCC High 使用 `https://login.microsoftonline.us`）。 |

### Microsoft Graph Webhook 监听器

Graph 事件（Teams 会议、日历、聊天等）的入站变更通知监听器。设置和安全加固详见 [Microsoft Graph Webhook 监听器](/user-guide/messaging/msgraph-webhook)。

| 变量 | 描述 |
|----------|-------------|
| `MSGRAPH_WEBHOOK_ENABLED` | 启用 `msgraph_webhook` gateway 平台（`true`/`1`/`yes`）。 |
| `MSGRAPH_WEBHOOK_PORT` | 监听器绑定端口（默认：`8646`）。 |
| `MSGRAPH_WEBHOOK_CLIENT_STATE` | Graph 在每次通知中回传的共享密钥；与 `hmac.compare_digest` 比较。使用 `openssl rand -hex 32` 生成。 |
| `MSGRAPH_WEBHOOK_ACCEPTED_RESOURCES` | 逗号分隔的 Graph 资源路径/模式白名单（例如 `communications/onlineMeetings,chats/*/messages`）。末尾 `*` 为前缀匹配。为空则接受所有。 |
| `MSGRAPH_WEBHOOK_ALLOWED_SOURCE_CIDRS` | 允许 POST 到监听器的逗号分隔 CIDR 范围（例如 `52.96.0.0/14,52.104.0.0/14`）。为空则允许所有（默认）。生产环境中应限制为 Microsoft Graph 公布的出口范围。 |

### Teams 会议摘要投递

仅在启用 [`teams_pipeline` 插件](/user-guide/messaging/msgraph-webhook)时使用。设置也可在 `config.yaml` 的 `platforms.teams.extra` 下配置——两者都设置时环境变量优先。参见 [Microsoft Teams → 会议摘要投递](/user-guide/messaging/teams#meeting-summary-delivery-teams-meeting-pipeline)。

| 变量 | 描述 |
|----------|-------------|
| `TEAMS_DELIVERY_MODE` | `graph` 或 `incoming_webhook`。 |
| `TEAMS_INCOMING_WEBHOOK_URL` | Teams 生成的 webhook URL；`TEAMS_DELIVERY_MODE=incoming_webhook` 时必填。 |
| `TEAMS_GRAPH_ACCESS_TOKEN` | Graph 投递的预获取委托访问 token。极少需要——未设置时 writer 回退到 `MSGRAPH_*` 应用凭证。 |
| `TEAMS_TEAM_ID` | 频道投递的目标 Team ID（`graph` 模式）。 |
| `TEAMS_CHANNEL_ID` | 目标频道 ID（与 `TEAMS_TEAM_ID` 配对）。 |
| `TEAMS_CHAT_ID` | 目标 1:1 或群聊 ID（`graph` 模式下 team+channel 的替代方案）。 |

### LINE Messaging API

由内置 LINE 平台插件（`plugins/platforms/line/`）使用。完整设置详见 [消息 Gateway → LINE](/user-guide/messaging/line)。

| 变量 | 描述 |
|----------|-------------|
| `LINE_CHANNEL_ACCESS_TOKEN` | 来自 LINE Developers Console（Messaging API 标签）的长期频道访问 token。必填。 |
| `LINE_CHANNEL_SECRET` | 频道密钥（Basic settings 标签）；用于 HMAC-SHA256 webhook 签名验证。必填。 |
| `LINE_HOST` | webhook 绑定主机（默认：`0.0.0.0`）。 |
| `LINE_PORT` | webhook 绑定端口（默认：`8646`）。 |
| `LINE_PUBLIC_URL` | 公共 HTTPS base URL（例如 `https://my-tunnel.example.com`）。发送图片/音频/视频时必填——LINE 仅接受 HTTPS 可访问的 URL。 |
| `LINE_ALLOWED_USERS` | 允许私信 bot 的逗号分隔用户 ID（`U` 前缀）。 |
| `LINE_ALLOWED_GROUPS` | bot 将在其中响应的逗号分隔群组 ID（`C` 前缀）。 |
| `LINE_ALLOWED_ROOMS` | bot 将在其中响应的逗号分隔房间 ID（`R` 前缀）。 |
| `LINE_ALLOW_ALL_USERS` | 仅用于开发的逃生舱——接受任意来源。默认：`false`。 |
| `LINE_HOME_CHANNEL` | `deliver: line` 的 cron 任务的默认投递目标。 |
| `LINE_SLOW_RESPONSE_THRESHOLD` | 慢速 LLM Template Buttons postback 触发前的等待秒数（默认：`45`）。设为 `0` 可禁用并始终使用 Push 回退。 |
| `LINE_PENDING_TEXT` | 与 postback 按钮一起显示的气泡文本。 |
| `LINE_BUTTON_LABEL` | Postback 按钮标签（默认：`Get answer`）。 |
| `LINE_DELIVERED_TEXT` | 再次点击已投递 postback 时的回复（默认：`Already replied ✅`）。 |
| `LINE_INTERRUPTED_TEXT` | 点击 `/stop` 孤立 postback 按钮时的回复（默认：`Run was interrupted before completion.`）。 |

### ntfy（推送通知）

[ntfy](https://ntfy.sh/) 是一个轻量级基于 HTTP 的推送通知服务。通过 [ntfy 移动应用](https://ntfy.sh/docs/subscribe/phone/)订阅话题，向该话题发布消息即可与 agent 交互。

| 变量 | 描述 |
|----------|-------------|
| `NTFY_TOPIC` | 订阅的话题（入站消息）。必填。 |
| `NTFY_SERVER_URL` | 服务器 URL（默认：`https://ntfy.sh`）。指向自托管 ntfy 以保护隐私。 |
| `NTFY_TOKEN` | 可选认证 token。Bearer token（例如 `tk_xyz`）或 `user:pass` 用于 Basic 认证。 |
| `NTFY_PUBLISH_TOPIC` | 出站回复的话题（默认为 `NTFY_TOPIC`）。 |
| `NTFY_MARKDOWN` | 设为 `true` 可使用 `X-Markdown: true` 头发送回复。默认：`false`。 |
| `NTFY_ALLOWED_USERS` | 白名单（视为用户 ID；在 ntfy 中即话题名称）。通常设为与 `NTFY_TOPIC` 相同的值。 |
| `NTFY_ALLOW_ALL_USERS` | 仅用于开发的逃生舱——仅在访问控制的私有话题上安全。默认：`false`。 |
| `NTFY_HOME_CHANNEL` | `deliver: ntfy` 的 cron 任务的默认投递目标。 |
| `NTFY_HOME_CHANNEL_NAME` | 主频道的人类可读标签（默认为话题名称）。 |

在使用不受信任的话题部署前，请参阅 [ntfy 消息指南](/user-guide/messaging/ntfy)——特别是**身份模型**部分。

### IRC

将 Hermes 连接到 IRC 服务器。无外部依赖。参见 [IRC 消息指南](/user-guide/messaging/irc)。

| 变量 | 描述 |
|----------|-------------|
| `IRC_SERVER` | IRC 服务器主机名（例如 `irc.libera.chat`）。必填。 |
| `IRC_CHANNEL` | 要加入的频道（例如 `#hermes`）；多个频道用逗号分隔。必填。 |
| `IRC_NICKNAME` | 机器人昵称（默认：`hermes-bot`）。必填。 |
| `IRC_PORT` | 服务器端口（默认：使用 TLS 时为 `6697`，否则为 `6667`）。 |
| `IRC_USE_TLS` | 是否使用 TLS（`true`/`false`；端口 6697 上默认为 `true`）。 |
| `IRC_SERVER_PASSWORD` | 用于 `PASS` 命令的服务器密码（可选）。 |
| `IRC_NICKSERV_PASSWORD` | 连接时自动 IDENTIFY 所用的 NickServ 密码（可选）。 |
| `IRC_ALLOWED_USERS` | 允许与机器人对话的昵称逗号分隔列表。 |
| `IRC_ALLOW_ALL_USERS` | 允许频道内任何人与机器人对话（仅限开发环境）。 |
| `IRC_HOME_CHANNEL` | 用于 cron / 通知投递的频道（默认为 `IRC_CHANNEL`）。 |

### SimpleX

通过本地 `simplex-chat` 守护进程将 Hermes 连接到 [SimpleX Chat](https://simplex.chat/) 网络。参见 [SimpleX 消息指南](/user-guide/messaging/simplex)。

| 变量 | 描述 |
|----------|-------------|
| `SIMPLEX_WS_URL` | simplex-chat 守护进程的 WebSocket URL（例如 `ws://127.0.0.1:5225`）。 |
| `SIMPLEX_ALLOWED_USERS` | 允许与机器人对话的 SimpleX 联系人 ID 逗号分隔列表。 |
| `SIMPLEX_ALLOW_ALL_USERS` | 允许任何联系人与机器人对话（仅限开发环境——会禁用白名单）。 |
| `SIMPLEX_AUTO_ACCEPT` | 自动接受入站联系人请求（默认：`true`）。 |
| `SIMPLEX_GROUP_ALLOWED` | 机器人应参与的 SimpleX 群组 ID 逗号分隔列表，或用 `*` 允许任意群组。省略则完全忽略群组消息（更安全的默认值——否则群组中的机器人会处理每位成员的流量）。 |
| `SIMPLEX_HOME_CHANNEL` | 用于 cron / 通知投递的默认联系人/群组 ID。 |
| `SIMPLEX_HOME_CHANNEL_NAME` | 主频道的可读标签（默认为该 ID）。 |

### Photon

通过 Node sidecar 将 Hermes 连接到 [Photon](https://photon.codes/) / Spectrum（iMessage 及其他 Spectrum 平台）。参见 [Photon 消息指南](/user-guide/messaging/photon)。

| 变量 | 描述 |
|----------|-------------|
| `PHOTON_PROJECT_ID` | Spectrum 项目 id（项目的 `spectrumProjectId`；由 `hermes photon setup` 设置）。 |
| `PHOTON_PROJECT_SECRET` | 与 Spectrum 项目 id 配对的项目密钥（由 `hermes photon setup` 设置）。 |
| `PHOTON_ALLOWED_USERS` | 允许与机器人对话的 E.164 电话号码逗号分隔列表。 |
| `PHOTON_ALLOW_ALL_USERS` | 允许任何发送者触发机器人（仅限开发环境——会禁用白名单）。 |
| `PHOTON_REQUIRE_MENTION` | 除非匹配提及唤醒词，否则忽略群聊消息（`true`/`false`，默认 `false`）。 |
| `PHOTON_MENTION_PATTERNS` | 群聊的提及唤醒词正则（JSON 列表或逗号/换行分隔；默认使用 Hermes 唤醒词）。 |
| `PHOTON_HOME_CHANNEL` | 用于 cron / 通知投递的默认 Photon 目标：Spectrum space id、私信 GUID 或裸 E.164 电话号码。 |
| `PHOTON_HOME_CHANNEL_NAME` | 主频道的可读标签。 |
| `PHOTON_MARKDOWN` | 以 markdown 发送 agent 回复——iMessage 原生渲染，其他 Spectrum 平台降级为纯文本（`true`/`false`，默认 `true`）。 |
| `PHOTON_REACTIONS` | 用 Tapback 👀/👍/👎 表示处理状态，并把机器人消息上的 tapback 路由给 agent（`true`/`false`，默认 `false`）。 |
| `PHOTON_TELEMETRY` | 在 sidecar 中启用 Spectrum SDK 遥测（`true`/`false`，默认 `false`；用 `hermes photon telemetry on|off` 切换）。 |
| `PHOTON_SIDECAR_PORT` | Node sidecar 控制 + 入站通道的回环端口（默认 `8789`）。 |
| `PHOTON_SIDECAR_AUTOSTART` | 连接时启动 Node sidecar（`true`/`false`，默认 `true`）。 |
| `PHOTON_NODE_BIN` | node 可执行文件路径（默认：`shutil.which('node')`）。 |
| `PHOTON_DASHBOARD_HOST` | Photon Dashboard API 主机（默认 `https://app.photon.codes`）。 |
| `PHOTON_SPECTRUM_HOST` | Photon Spectrum API 主机（默认 `https://spectrum.photon.codes`）。 |

### Microsoft Teams（适配器）

Microsoft Teams 平台适配器（Bot Framework / Azure AD），与上文的 [Microsoft Graph（Teams 会议）](#microsoft-graph-teams-meetings)集成不同。参见 [Teams 消息指南](/user-guide/messaging/teams)。

| 变量 | 描述 |
|----------|-------------|
| `TEAMS_CLIENT_ID` | Azure AD 应用（Bot Framework）client ID。 |
| `TEAMS_CLIENT_SECRET` | Azure AD 应用 client secret。 |
| `TEAMS_TENANT_ID` | 托管该机器人应用的 Azure AD 租户 ID。 |
| `TEAMS_PORT` | Webhook 监听端口（Bot Framework 默认：`3978`）。 |
| `TEAMS_ALLOWED_USERS` | 允许与机器人对话的 Teams 用户 ID / UPN 逗号分隔列表。 |
| `TEAMS_ALLOW_ALL_USERS` | 允许任何 Teams 用户触发机器人（仅限开发环境）。 |
| `TEAMS_HOME_CHANNEL` | 用于 cron / 通知投递的默认聊天/频道 ID。 |
| `TEAMS_HOME_CHANNEL_NAME` | Teams 主频道的显示名称。 |

### Raft

| 变量 | 描述 |
|----------|-------------|
| `RAFT_PROFILE` | Raft agent profile slug——设置后自动启用该适配器。 |

### 高级消息调优

用于限制出站消息批处理器的高级每平台旋钮。大多数用户无需调整；默认值已设置为在遵守各平台速率限制的同时不显得迟缓。

| 变量 | 描述 |
|----------|-------------|
| `HERMES_TELEGRAM_TEXT_BATCH_DELAY_SECONDS` | 刷新排队 Telegram 文本块前的宽限窗口（默认：`0.6`）。 |
| `HERMES_TELEGRAM_TEXT_BATCH_SPLIT_DELAY_SECONDS` | 单条 Telegram 消息超过长度限制时分块之间的延迟（默认：`2.0`）。 |
| `HERMES_SIMPLEX_TEXT_BATCH_DELAY` | 静默期秒数（默认：`0.8`），用于把快速连发的入站文本消息合并为单个 MessageEvent——与 Telegram 的文本批处理模式相同。 |
| `HERMES_TELEGRAM_MEDIA_BATCH_DELAY_SECONDS` | 刷新排队 Telegram 媒体前的宽限窗口（默认：`0.6`）。 |
| `HERMES_TELEGRAM_FOLLOWUP_GRACE_SECONDS` | agent 完成后发送后续消息前的延迟，以避免与最后一个流块竞争。 |
| `HERMES_TELEGRAM_HTTP_CONNECT_TIMEOUT` / `_READ_TIMEOUT` / `_WRITE_TIMEOUT` / `_POOL_TIMEOUT` | 覆盖底层 `python-telegram-bot` HTTP 超时（秒）。 |
| `HERMES_TELEGRAM_INIT_TIMEOUT` | gateway 启动期间 Telegram `initialize()` 连接链的每次尝试上限（秒），使不可达的备用 IP 链无法无限期阻塞启动（默认：`30`）。 |
| `HERMES_TELEGRAM_HTTP_POOL_SIZE` | 到 Telegram API 的最大并发 HTTP 连接数。 |
| `HERMES_TELEGRAM_DISABLE_FALLBACK_IPS` | 禁用 DNS 失败时使用的硬编码 Cloudflare 回退 IP（`true`/`false`）。 |
| `HERMES_DISCORD_TEXT_BATCH_DELAY_SECONDS` | 刷新排队 Discord 文本块前的宽限窗口（默认：`0.6`）。 |
| `HERMES_DISCORD_TEXT_BATCH_SPLIT_DELAY_SECONDS` | Discord 消息超过长度限制时分块之间的延迟（默认：`2.0`）。 |
| `HERMES_DISCORD_LIVENESS_INTERVAL_SECONDS` | `discord.websocket_liveness_interval_seconds` 的兼容/手动覆盖。采样活动 Discord Gateway WebSocket 的间隔（默认：`15`；设为 `0` 可禁用）。建议优先使用 `config.yaml` 键。 |
| `HERMES_DISCORD_LIVENESS_FAILURE_THRESHOLD` | `discord.websocket_liveness_failure_threshold` 的兼容/手动覆盖。强制重连前连续不健康的 WebSocket 采样次数（默认：`2`）。建议优先使用 `config.yaml` 键。 |
| `HERMES_MATRIX_TEXT_BATCH_DELAY_SECONDS` / `_SPLIT_DELAY_SECONDS` | Matrix 等同于 Telegram 批处理旋钮。 |
| `HERMES_FEISHU_TEXT_BATCH_DELAY_SECONDS` / `_SPLIT_DELAY_SECONDS` / `_MAX_CHARS` / `_MAX_MESSAGES` | 飞书批处理器调优——延迟、分块延迟、每条消息最大字符数、每批最大消息数。 |
| `HERMES_FEISHU_MEDIA_BATCH_DELAY_SECONDS` | 飞书媒体刷新延迟。 |
| `HERMES_FEISHU_DEDUP_CACHE_SIZE` | 飞书 webhook 去重缓存大小（默认：`1024`）。 |
| `HERMES_WECOM_TEXT_BATCH_DELAY_SECONDS` / `_SPLIT_DELAY_SECONDS` | 企业微信批处理器调优。 |
| `HERMES_VISION_DOWNLOAD_TIMEOUT` | 将图片交给视觉模型前下载的超时（秒，默认：`30`）。 |
| `HERMES_VISION_MAX_CONCURRENCY` | 全进程范围内并发图像**编码/缩放**批次的最大数量（`auxiliary.vision.max_concurrency` 的覆盖；默认：宿主机 CPU 核心数，无上限）。它只限制 CPU 密集的编码步骤，使视频帧的 fan-out 无法占满所有核心并饿死事件循环——LLM 调用仍保持完全并发。小于 `1` 的值会被忽略。 |
| `HERMES_RESTART_DRAIN_TIMEOUT` | Gateway：`/restart` 时等待活跃运行排空的秒数，超时后强制重启（默认：`900`）。 |
| `HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT` | gateway 启动和重连期间每个平台的连接超时（秒；`0`/负值表示无限等待）。同时作用于连接尝试*以及* Discord 适配器的 ready 等待，因此需要同步大量 slash 命令的账号不会在启动中途被终止。由 `config.yaml` 中的 `gateway.platform_connect_timeout` 桥接而来（默认 `30`）；此环境变量是手动覆盖项，显式设置时优先生效。 |
| `HERMES_GATEWAY_BUSY_INPUT_MODE` | 默认 gateway 繁忙输入行为：`queue`、`steer` 或 `interrupt`。可通过 `/busy` 按聊天覆盖。 |
| `HERMES_GATEWAY_BUSY_ACK_ENABLED` | gateway 是否在用户 agent 繁忙时发送确认消息（⚡/⏳/⏩）（默认：`true`）。设为 `false` 可完全抑制这些消息——输入仍会正常排队/引导/中断，只是聊天回复被静默。从 `config.yaml` 中的 `display.busy_ack_enabled` 桥接。 |
| `HERMES_GATEWAY_NO_SUPERVISE` | 在 s6-overlay Docker 镜像内部运行 `hermes gateway run` 时跳过 s6 自动监管，退回到 pre-s6 前台语义（无自动重启，gateway 作为容器主进程）。真值：`1`、`true`、`yes`。等同于 `--no-supervise` CLI 标志。在 s6 镜像之外为空操作。 |
| `HERMES_GATEWAY_BOOTSTRAP_STATE` | 在 s6-overlay Docker 镜像内部，为**全新卷**声明 gateway 的初始受监管状态。空白卷上不存在持久化的 `gateway_state.json`，因此启动协调器会注册 `gateway-default` 槽位但保持其**关闭**（只有上次记录状态为 `running` 时才会自动启动）。将此变量设为 `running` 后，首次启动 hook 会在协调器运行前预写入 `gateway_state.json`，从而让 gateway 在第一次启动时就自动拉起。仅字面值 `running` 生效。仅影响首次启动：若已有 `gateway_state.json`，绝不会被覆盖，因此被刻意停止的 gateway 在重启后仍保持停止。在 s6 镜像之外为空操作。 |
| `GATEWAY_RELAY_URL` | 实验性 relay 连接器 WebSocket base URL。设置后，gateway 会注册通用 `relay` 适配器并向外拨号连接器。对应 `config.yaml` 中的 `gateway.relay_url`。 |
| `GATEWAY_RELAY_ID` | 由 `hermes gateway enroll` 或托管式自助注册分配的 relay gateway 标识。对应 `gateway.relay_id`。 |
| `GATEWAY_RELAY_SECRET` | 用于认证 WebSocket 的每 gateway relay 密钥。如果已经配置，则跳过托管式自助注册。对应 `gateway.relay_secret`。 |
| `GATEWAY_RELAY_DELIVERY_KEY` | 连接器签发的投递密钥，为兼容 relay/passthrough 认证而保留。当前 relay 入站消息通过出站 WebSocket 到达，而非 gateway 侧的 HTTP 接收器。 |
| `GATEWAY_RELAY_ENROLL_TOKEN` | 未显式传入 `--token` 时，`hermes gateway enroll` 使用的注册 token。 |
| `GATEWAY_RELAY_PLATFORM` | 在 relay 能力描述符中声明的可选平台名称。 |
| `GATEWAY_RELAY_BOT_ID` | 在 relay 能力描述符中声明的可选 bot 标识。 |
| `GATEWAY_RELAY_ENDPOINT` | 为需要回调/passthrough URL 的连接器模式声明的可选 gateway 端点；默认的仅 WS 入站 relay 路径不需要它。对应 `gateway.relay_endpoint`。 |
| `GATEWAY_RELAY_ROUTE_KEYS` | 向连接器声明的 relay 路由键逗号分隔列表。对应 `gateway.relay_route_keys`。 |
| `HERMES_FILE_MUTATION_VERIFIER` | 启用每轮文件变更验证器页脚（默认：`true`）。启用后，Hermes 附加一个建议列表，列出本轮中失败且未被成功写入覆盖的 `write_file`/`patch` 调用。设为 `0`、`false`、`no` 或 `off` 可抑制。镜像 `config.yaml` 中的 `display.file_mutation_verifier`；设置时环境变量优先。 |
| `HERMES_CRON_TIMEOUT` | cron 任务 agent 运行的不活动超时（秒，默认：`600`）。agent 在主动调用工具或接收流 token 时可无限运行——仅在空闲时触发。设为 `0` 表示无限制。 |
| `HERMES_CRON_SCRIPT_TIMEOUT` | cron 任务附加的预运行脚本超时（秒，默认：`3600`）。仅约束脚本本身——skill/agent 任务使用独立的 `HERMES_CRON_TIMEOUT` 空闲预算。也可通过 `config.yaml` 中的 `cron.script_timeout_seconds` 配置。 |
| `HERMES_CRON_MAX_PARALLEL` | 每次 tick 并行运行的最大 cron 任务数（默认：`4`）。 |

## Agent 行为

| 变量 | 描述 |
|----------|-------------|
| `HERMES_MAX_ITERATIONS` | 每次对话的最大工具调用迭代次数（默认：90） |
| `HERMES_INFERENCE_MODEL` | 在进程级别覆盖模型名称（优先于本次会话的 `config.yaml`）。也可通过 `-m`/`--model` 标志设置。 |
| `HERMES_YOLO_MODE` | 设为 `1` 可绕过危险命令审批提示。等同于 `--yolo`。 |
| `HERMES_ACCEPT_HOOKS` | 无需 TTY 提示自动批准 `config.yaml` 中声明的任何未见过的 shell hook。等同于 `--accept-hooks` 或 `hooks_auto_accept: true`。 |
| `HERMES_IGNORE_USER_CONFIG` | 跳过 `~/.hermes/config.yaml` 并使用内置默认值（`.env` 中的凭证仍会加载）。等同于 `--ignore-user-config`。 |
| `HERMES_IGNORE_RULES` | 跳过 `AGENTS.md`、`SOUL.md`、`.cursorrules`、记忆和预加载技能的自动注入。等同于 `--ignore-rules`。 |
| `HERMES_SAFE_MODE` | 故障排查模式：禁用**所有**自定义项——跳过插件发现、MCP 服务器加载和 shell hook 注册。由 `--safe-mode` 自动设置（同时也会设置上面两个 flag）。 |
| `HERMES_TOOL_PROGRESS` | 工具进度显示的已弃用兼容变量。优先使用 `config.yaml` 中的 `display.tool_progress`。 |
| `HERMES_TOOL_PROGRESS_MODE` | 工具进度模式的已弃用兼容变量。优先使用 `config.yaml` 中的 `display.tool_progress`。 |
| `HERMES_HUMAN_DELAY_MODE` | 响应节奏：`off`/`natural`/`custom` |
| `HERMES_HUMAN_DELAY_MIN_MS` | 自定义延迟范围最小值（毫秒） |
| `HERMES_HUMAN_DELAY_MAX_MS` | 自定义延迟范围最大值（毫秒） |
| `HERMES_QUIET` | 抑制非必要输出（`true`/`false`） |
| `CODEX_HOME` | 启用 [Codex 应用服务器运行时](../user-guide/features/codex-app-server-runtime)时，覆盖 Codex CLI 读取其配置 + 认证的目录（默认：`~/.codex`）。Hermes 的迁移将托管块写入 `<CODEX_HOME>/config.toml`。 |
| `HERMES_KANBAN_TASK` | kanban 调度器生成工作进程时设置（任务 UUID）。工作进程和生成的 `hermes-tools` MCP 子进程继承它，以便 kanban 工具正确门控。请勿手动设置。 |
| `HERMES_API_TIMEOUT` | LLM API 调用超时（秒，默认：`1800`） |
| `HERMES_API_CALL_STALE_TIMEOUT` | 非流式过期调用超时（秒，默认：`90`）。未设置时对本地提供商自动禁用，并可能针对超大上下文向上调整。也可通过 `config.yaml` 中的 `providers.<id>.stale_timeout_seconds` 或 `providers.<id>.models.<model>.stale_timeout_seconds` 配置。 |
| `HERMES_STREAM_READ_TIMEOUT` | 流式 socket 读取超时（秒，默认：`120`）。对本地提供商自动增大到 `HERMES_API_TIMEOUT`。如果本地 LLM 在长代码生成期间超时，请增大此值。 |
| `HERMES_STREAM_STALE_TIMEOUT` | 过期流检测超时（秒，默认：`180`）。对本地提供商自动禁用。在此窗口内无块到达时触发连接终止。 |
| `HERMES_LOCAL_STREAM_STALE_TIMEOUT` | 本地提供商（Ollama、oMLX、llama-cpp）的过期流上限（秒，默认：`900`）。当基础过期超时保持默认值且检测到本地端点时，这一有限上限会取代此前的无限期禁用，使卡死的本地服务器最终会触发检测器，而不是永远挂起。也可通过 `config.yaml` 中的 `agent.local_stream_stale_timeout` 配置。 |
| `HERMES_STREAM_RETRIES` | 瞬时网络错误时的流中重连尝试次数（默认：`3`）。 |
| `HERMES_STREAM_STALE_GIVEUP` | 跨轮次熔断器：在连续这么多次过期终止（流式或非流式）且没有完成任何响应之后，立即以可操作的错误中止每次调用，而不是再次等待过期超时（默认：`5`，`0` 表示禁用）。任何完成的响应、`/model` 切换、回退激活或轮次开始时恢复主 provider 都会重置计数。 |
| `HERMES_AGENT_TIMEOUT` | gateway 中运行 agent 的不活动超时（秒，默认：`1800`，即 30 分钟）。每次工具调用和流 token 时重置。设为 `0` 可禁用。 |
| `HERMES_GATEWAY_MAX_STARTS` | 重生风暴熔断器：窗口内允许的 gateway（重）启动次数上限，超过后会休眠一段指数退避时间以打破风暴（默认：`5`，`0` 表示禁用）。也可通过 `config.yaml` 中的 `gateway.respawn_storm.max_starts` 配置。 |
| `HERMES_GATEWAY_START_WINDOW_S` | 重生风暴熔断器的窗口长度（秒，默认：`120`）。也可通过 `config.yaml` 中的 `gateway.respawn_storm.window_seconds` 配置。 |
| `HERMES_AGENT_TIMEOUT_WARNING` | Gateway：不活动超过此秒数后发送警告消息（默认：`HERMES_AGENT_TIMEOUT` 的 75%）。 |
| `HERMES_AGENT_NOTIFY_INTERVAL` | Gateway：长时间运行的 agent 轮次中进度通知的间隔（秒）。 |
| `HERMES_CHECKPOINT_TIMEOUT` | 文件系统检查点创建超时（秒，默认：`30`）。 |
| `HERMES_EXEC_ASK` | 在 gateway 模式下启用执行审批提示（`true`/`false`） |
| `HERMES_ENABLE_PROJECT_PLUGINS` | 为 agent 加载器和仪表板 Web 服务器启用从 `./.hermes/plugins/` 自动发现仓库本地插件。接受标准真值集：`1`/`true`/`yes`/`on`（不区分大小写）。其他所有值——包括 `0`、`false`、`no`、`off` 和空字符串——均视为**禁用**（默认）。注意：自 GHSA-5qr3-c538-wm9j（#29156）起，即使启用此变量，仪表板 Web 服务器也拒绝自动导入项目插件的 Python `api` 文件——项目插件可通过静态 JS/CSS 扩展 UI，但其后端路由仅在移至 `~/.hermes/plugins/` 后才会加载。 |
| `HERMES_PLUGINS_DEBUG` | `1`/`true` 可在 stderr 上输出详细的插件发现日志——扫描的目录、解析的 manifest、跳过原因以及解析或 `register()` 失败时的完整回溯。面向插件作者。 |
| `HERMES_BACKGROUND_NOTIFICATIONS` | gateway 中后台进程通知模式：`all`（默认）、`result`、`error`、`off` |
| `HERMES_EPHEMERAL_SYSTEM_PROMPT` | 在 API 调用时注入的临时系统 prompt（永不持久化到会话） |
| `HERMES_PREFILL_MESSAGES_FILE` | 包含在 API 调用时注入的临时预填消息的 JSON 文件路径。 |
| `HERMES_ALLOW_PRIVATE_URLS` | `true`/`false`——允许工具获取 localhost/私有网络 URL。gateway 模式下默认关闭。 |
| `HERMES_REDACT_SECRETS` | `true`/`false`——控制工具输出、日志和聊天响应中的密钥脱敏（默认：`true`）。 |
| `HERMES_WRITE_SAFE_ROOT` | 可选目录前缀，**硬阻止** `write_file`/`patch` 写入列出的根目录之外的路径（无审批提示）。支持多个目录，使用 `os.pathsep` 分隔（Unix 为 `:`，Windows 为 `;`）。详见下方 [HERMES_WRITE_SAFE_ROOT](#hermes_write_safe_root)。 |
| `HERMES_DISABLE_LAZY_INSTALLS` | 官方 Docker 镜像中自动设置的内部桥接变量，用于阻止运行时将依赖安装到不可变的 `/opt/hermes` 树。面向用户的等价配置是 `config.yaml` 中的 `security.allow_lazy_installs: false`；不要在 `.env` 中手动设置此变量。 |
| `HERMES_DISABLE_FILE_STATE_GUARD` | 设为 `1` 可关闭 `patch`/`write_file` 上的"文件自上次读取后已更改"保护。 |
| `HERMES_BUNDLED_SKILLS` | 启动时加载的内置技能列表的逗号分隔覆盖。 |
| `HERMES_OPTIONAL_SKILLS` | 首次运行时自动安装的可选技能名称逗号分隔列表。 |
| `HERMES_DEBUG_INTERRUPT` | 设为 `1` 可将详细的中断/取消追踪记录到 `agent.log`。 |
| `HERMES_DUMP_REQUESTS` | 将 API 请求载荷转储到日志文件（`true`/`false`） |
| `HERMES_DUMP_REQUEST_STDOUT` | 将 API 请求载荷转储到 stdout 而非日志文件。 |
| `HERMES_OAUTH_TRACE` | 设为 `1` 可记录 OAuth token 交换和刷新尝试。包含脱敏的时序信息。 |
| `HERMES_OAUTH_FILE` | 覆盖 OAuth 凭证存储路径（默认：`~/.hermes/auth.json`）。 |
| `HERMES_AGENT_HELP_GUIDANCE` | 为自定义部署在系统 prompt 中追加额外指导文本。 |
| `HERMES_AGENT_LOGO` | 覆盖 CLI 启动时的 ASCII 横幅 logo。 |
| `DELEGATION_MAX_CONCURRENT_CHILDREN` | 每个 `delegate_task` 批次的最大并行子 agent 数（默认：`3`，下限为 1，无上限）。也可通过 `config.yaml` 中的 `delegation.max_concurrent_children` 配置——config 值优先。 |

### HERMES_WRITE_SAFE_ROOT {#hermes_write_safe_root}

设置此变量后，`write_file` 和 `patch` 只能写入列出的目录前缀内的路径。超出这些根目录的路径会被**立即拒绝**——不会进入危险命令审批流程，也没有聊天界面可以覆盖。

官方 Docker 镜像会设置 `HERMES_WRITE_SAFE_ROOT=/opt/data` 与 `HERMES_HOME=/opt/data`，防止 agent 逃出挂载的数据卷。

**除非有意沙箱化写入，否则不要将此变量加入 `~/.hermes/.env`。** 常见错误是将其指向项目目录，却期望 agent 编辑 `~/.hermes/cron/jobs.json`、`~/.hermes/skills/` 或 profile 下的脚本——这些路径在沙箱外，每次 `write_file`/`patch` 都会失败并返回 `outside HERMES_WRITE_SAFE_ROOT` 错误。

若需同时允许工作区和 Hermes 状态目录，列出两个前缀（顺序无关）：

```bash
export HERMES_WRITE_SAFE_ROOT=/path/to/project:/home/you/.hermes
```

取消设置或从 `.env` 中移除此变量可恢复常规写入（仍受凭证路径拒绝列表约束——见[文件写入安全](../user-guide/security.md#file-write-safety)）。

## 界面

| 变量 | 描述 |
|----------|-------------|
| `HERMES_TUI` | 设为 `1` 时启动 [TUI](../user-guide/tui.md) 而非经典 CLI。等同于传入 `--tui`。 |
| `HERMES_TUI_DIR` | 预构建 `ui-tui/` 目录的路径（必须包含 `dist/entry.js` 和已填充的 `node_modules`）。供发行版和 Nix 使用以跳过首次启动时的 `npm install`。 |
| `HERMES_TUI_RESUME` | 启动时按 ID 恢复特定 TUI 会话。设置后，`hermes --tui` 跳过创建新会话并接续指定会话——适用于断开连接或终端崩溃后重新连接。 |
| `HERMES_TUI_THEME` | 强制 TUI 颜色主题：`light`、`dark` 或原始 6 字符背景十六进制（例如 `ffffff` 或 `1a1a2e`）。未设置时，Hermes 使用 `COLORFGBG` 和终端背景查询自动检测；此变量覆盖不设置 `COLORFGBG` 的终端（Ghostty、Warp、iTerm2 等）上的检测。 |
| `HERMES_INFERENCE_MODEL` | 为 `hermes -z`/`hermes chat` 强制指定模型而不修改 `config.yaml`。与 `--provider` 标志配合使用。适用于需要每次运行覆盖默认模型的脚本调用者（sweeper、CI、批量运行器）。 |

## 会话设置

| 变量 | 描述 |
|----------|-------------|
| `SESSION_IDLE_MINUTES` | 不活动 N 分钟后重置会话（默认：1440） |
| `SESSION_RESET_HOUR` | 24 小时制每日重置时间（默认：4 = 凌晨 4 点） |
| `HERMES_SESSION_ID` | **自动导出到 Hermes 生成的每个工具子进程**（`terminal`、`execute_code`、持久 shell、Docker/Singularity 后端、委托子 agent 运行）。由 agent 设置为当前会话 ID；从工具调用的用户脚本可读取它，以将其输出、遥测或副作用与原始 Hermes 会话关联。**不应手动设置**——从父 shell 覆盖仅在 agent 运行外生效，且 agent 启动会话时会被覆盖。 |

## 上下文压缩（仅 config.yaml）

上下文压缩完全通过 `config.yaml` 配置——没有对应的环境变量。阈值设置位于 `compression:` 块，摘要模型/提供商位于 `auxiliary.compression:` 下。

```yaml
compression:
  enabled: true
  threshold: 0.50
  target_ratio: 0.20         # fraction of threshold to preserve as recent tail
  protect_last_n: 20         # minimum recent messages to keep uncompressed
```

:::info 旧版迁移
包含 `compression.summary_model`、`compression.summary_provider` 和 `compression.summary_base_url` 的旧版配置在首次加载时自动迁移到 `auxiliary.compression.*`。
:::

## 辅助任务覆盖

| 变量 | 描述 |
|----------|-------------|
| `AUXILIARY_VISION_PROVIDER` | 覆盖视觉任务的提供商 |
| `AUXILIARY_VISION_MODEL` | 覆盖视觉任务的模型 |
| `AUXILIARY_VISION_BASE_URL` | 视觉任务的直接 OpenAI 兼容端点 |
| `AUXILIARY_VISION_API_KEY` | 与 `AUXILIARY_VISION_BASE_URL` 配对的 API 密钥 |
| `AUXILIARY_WEB_EXTRACT_PROVIDER` | 覆盖网页提取/摘要的提供商 |
| `AUXILIARY_WEB_EXTRACT_MODEL` | 覆盖网页提取/摘要的模型 |
| `AUXILIARY_WEB_EXTRACT_BASE_URL` | 网页提取/摘要的直接 OpenAI 兼容端点 |
| `AUXILIARY_WEB_EXTRACT_API_KEY` | 与 `AUXILIARY_WEB_EXTRACT_BASE_URL` 配对的 API 密钥 |

对于特定任务的直接端点，Hermes 使用该任务配置的 API 密钥或 `OPENAI_API_KEY`。不会为这些自定义端点复用 `OPENROUTER_API_KEY`。

## 回退提供商（仅 config.yaml）

主模型回退链完全通过 `config.yaml` 配置——没有对应的环境变量。在顶层添加包含 `provider` 和 `model` 键的 `fallback_providers` 列表，以在主模型遇到错误时启用自动故障转移。provider 为 `auto` 的辅助任务在使用 Hermes 内置的辅助发现链之前也会先查询该回退链。

```yaml
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-sonnet-4
```

旧版顶层 `fallback_model` 单提供商格式仍可向后兼容读取，但新配置应使用 `fallback_providers`。针对特定任务的辅助策略，请使用 `config.yaml` 中的 `auxiliary.<task>.fallback_chain`；没有对应的环境变量。

详见 [回退提供商](/user-guide/features/fallback-providers)。

## 提供商路由（仅 config.yaml）

这些配置写入 `~/.hermes/config.yaml` 的 `provider_routing` 部分：

| 键 | 描述 |
|-----|-------------|
| `sort` | 排序提供商：`"price"`（默认）、`"throughput"` 或 `"latency"` |
| `only` | 允许的提供商 slug 列表（例如 `["anthropic", "google"]`） |
| `ignore` | 跳过的提供商 slug 列表 |
| `order` | 按顺序尝试的提供商 slug 列表 |
| `require_parameters` | 仅使用支持所有请求参数的提供商（`true`/`false`） |
| `data_collection` | `"allow"`（默认）或 `"deny"` 以排除存储数据的提供商 |

:::tip
使用 `hermes config set` 设置环境变量——它会自动将其保存到正确的文件（密钥保存到 `.env`，其他所有内容保存到 `config.yaml`）。
:::