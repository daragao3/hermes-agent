---
sidebar_position: 6
title: 网页搜索与提取
sidebar_label: 网页搜索
description: 通过多个后端提供商搜索网页并提取页面内容——包括免费的自托管 SearXNG。
---

# 网页搜索与提取

Hermes Agent 内置两个可供模型调用的网页工具，由多个提供商支持：

- **`web_search`** —— 搜索网页并返回排序结果
- **`web_extract`** —— 从一个或多个 URL 获取并提取可读内容

两者均通过单一后端选择进行配置。提供商可通过 `hermes tools` 选择，或直接在 `config.yaml` 中设置。

## 后端

| 提供商 | 环境变量 | 搜索 | 提取 | 免费层级 |
|----------|---------|--------|---------|-----------|
| **Firecrawl**（默认） | `FIRECRAWL_API_KEY`（可选——选中后可免密钥使用） | ✔ | ✔ | 500 积分/月 · 选中后可免密钥使用云服务 |
| **SearXNG** | `SEARXNG_URL` | ✔ | — | ✔ 免费（自托管） |
| **Brave Search（免费层级）** | `BRAVE_SEARCH_API_KEY` | ✔ | — | 2 000 次查询/月 |
| **DDGS (DuckDuckGo)** | —（无需密钥） | ✔ | — | ✔ 免费 |
| **Exa** | `EXA_API_KEY`（可选） | ✔ | ✔ | ✔ 免密钥轮换成员 · 有密钥时 1 000 次搜索/月 |
| **Parallel** | `PARALLEL_API_KEY`（可选） | ✔ | ✔ | ✔ 免密钥轮换成员 · 有密钥时付费 |
| **Tavily** | `TAVILY_API_KEY`（可选） | ✔ | ✔ | ✔ 选中后可选择免密钥使用 |
| **Perplexity** | `PERPLEXITY_API_KEY` | ✔ | ✔（与查询相关的片段） | 付费（Search API 按请求计费） |
| **Keenable** | `KEENABLE_API_KEY`（可选） | ✔ | ✔ | ✔ 免密钥轮换成员 · 有密钥时付费 |
| **xAI (Grok)** | `XAI_API_KEY` 或 `hermes auth add xai-oauth` | ✔ | — | 付费（SuperGrok 或按 token 计费） |

Brave Search、DDGS 和 xAI 均为**仅搜索**——如果同时需要 `web_extract`，可将其中任意一个与 Firecrawl/Tavily/Perplexity/Keenable/Exa/Parallel 配合使用。DDGS 底层使用 [`ddgs` Python 包](https://pypi.org/project/ddgs/)；若尚未安装，请运行 `pip install ddgs`（或让 Hermes 在首次使用时懒加载安装）。xAI 通过 Responses API 运行 Grok 服务端的 `web_search` 工具——结果由 LLM 生成而非基于索引，因此标题、描述和 URL 选择均为模型输出（参见下方[信任模型说明](#xai-grok)）。

**按能力拆分：** 搜索和提取可分别使用不同的提供商——例如搜索使用 SearXNG（免费），提取使用 Firecrawl。详见下方[按能力配置](#per-capability-configuration)。

:::info 开箱即用——免密钥免费层级轮换
全新安装即使**完全没有任何网页凭证**，也能开箱即用 `web_search` 和 `web_extract`：请求会在轮换成员厂商的公共免费层级——**Exa、Parallel、Firecrawl 和 Keenable**——之间轮询，均匀分摊负载；被限速的请求会自动在轮换中的下一个厂商上重试（多跳，直到有一个成功响应或全部被限流）。无需注册，无需密钥。该层级严格作为最后手段——任何已配置的后端或已存在的 API 密钥始终优先——且请求不携带任何用户标识（仅有一个随机的每进程会话 id，重启时轮换）。如需有保障、不限流的服务，请配置一个带密钥的提供商。使用 `web.keyless_fallback: false` 可完全禁用免密钥层级。
:::

**显式选择免费或付费：** 在 `hermes tools` 中，Exa、Parallel 和 Keenable 各显示为两行——**Free (keyless)** 和 **Paid (API key)**。选择 Free 会固定使用该厂商的匿名端点（即使之后添加了密钥）；选择 Paid 会固定使用带密钥的路径（此时缺少密钥会直接报错，而不是悄悄降级到免费层级）。该选择存储为 `web.provider_tier.<name>: free|paid`；不设置则为自动（存在密钥 → 付费，否则使用免密钥轮换）。

:::tip Nous 订阅用户
如果您拥有付费 [Nous Portal](https://portal.nousresearch.com) 订阅，网页搜索和提取可通过 **[Tool Gateway](tool-gateway.md)** 使用托管的 Firecrawl——无需 API 密钥。新安装可运行 `hermes setup --portal` 登录并一次性开启所有 gateway 工具；现有安装可通过 `hermes tools` 单独开启网页功能。
:::

---

## `web_extract` 如何处理长页面 {#how-web_extract-handles-long-pages}

后端返回的原始页面 markdown 可能非常庞大（论坛帖子、文档站点、带嵌入评论的新闻文章）。为保持上下文窗口可用，`web_extract` 采用**确定性字符预算**——不涉及任何 LLM 摘要：

| 页面大小（字符数） | 处理方式 |
|------------------------|--------------|
| 预算以内（默认 15 000） | 原样返回——完整 markdown 直达 agent |
| 超出预算 | 头+尾窗口（约 75% 头部 / 25% 尾部，按 markdown 行边界切分），并附带明确的 `[TRUNCATED]` 尾注。完整的干净文本存储到磁盘，尾注告知 agent 文件路径以及分页读取被省略中间部分的确切 `read_file` 调用 |
| 超过 2 000 000 | 存储的文本上限为 2 MB |

每页预算可通过 `config.yaml` 中的 `web.extract_char_limit` 配置（默认 `15000`，范围限制在 2 000–500 000），agent 也可以通过工具的 `char_limit` 参数按调用提高。

### 当截断带来不便时

如果您明确需要实时 DOM 而非提取的 markdown——例如提取内容很少的 JS 密集页面——请改用 `browser_navigate` + `browser_snapshot`。浏览器工具返回实时无障碍树（超大页面受其自身快照上限约束）。

---

## 结果缓存

短时间窗口内重复的网页调用会从缓存提供，而不是再次请求付费后端——这在两种常出现重复的场景中节省积分和延迟：子 agent 扇出（多个被委派的 agent 研究同一主题），以及 agent 重新查看几分钟前读过的页面。

| 调用 | 缓存 | 范围 |
|------|-------|-------|
| `web_search`——相同查询（忽略大小写/空白），相同提供商 | 内存备忘 | 每进程 |
| `web_extract`——相同 URL、相同格式、相同提供商 | 完整文本存储在 `~/.hermes/cache/web/` 下 | 在 CLI、gateway、cron 和子 agent 进程间共享 |

并发的相同搜索（并行子 agent 扇出同时发出同一查询）会被**合并为单个后端请求**——第一个调用方付费，其余调用方共享响应。请求的搜索数量上限会向上归入 10/20/50/100 档，因此近乎相同的请求（`limit=5` 与 `limit=8`）共享同一条目，每个调用方仍收到各自请求的数量。

只有成功的响应才会被缓存。失败始终会重试后端；由一次性免密钥救援提供的响应从不缓存（下一次调用会再次尝试您选择的后端）；与您的 `security.website_blocklist` 匹配的 URL 从不从缓存提供。缓存的提取结果会重新走常规截断流程，因此第二次调用使用不同的 `char_limit` 时，会基于同一份已存储的抓取结果处理。

**本地开发 URL 从不缓存。** 任何位于 `localhost`、`127.0.0.1`、`*.local`、单标签局域网主机名或私有/链路本地 IP 范围（`192.168.*`、`10.*`、`172.16-31.*`）上的内容都会完全绕过提取缓存——开发服务器、热重载构建和聊天 GUI 的 artifact 预览每次保存都会变化，缓存副本只会给您展示过期的构建。每次获取本地页面都是实时的。（这些 URL 只有在启用 `security.allow_private_urls` 时才可访问。）

**通过公网进行测试？** 预发布部署和隧道 URL 属于公共 DNS，本地开发规则无法识别它们——将它们列入 `web.cache_exempt_hosts`，它们也会始终实时获取。条目可以精确匹配、作为 `*.` 通配符匹配，或作为域名后缀匹配（`mysite.dev` 同时覆盖 `preview.mysite.dev`）：

```yaml
# ~/.hermes/config.yaml
web:
  cache_exempt_hosts:
    - mysite.vercel.app
    - "*.ngrok-free.app"
```

```yaml
# ~/.hermes/config.yaml
web:
  cache_enabled: true      # 默认；设为 false 可同时禁用两种缓存
  cache_ttl_minutes: 20    # 新鲜度窗口，限制在 1–1440
```

如果您研究的是真正的实时数据（比分、价格、突发新闻），需要每次调用都获取最新内容，请调低 TTL 或设置 `web.cache_enabled: false`。

---

## 设置

### 通过 `hermes tools` 快速设置

运行 `hermes tools`，导航至 **Web Search & Extract**，选择一个提供商。向导会提示输入所需的 URL 或 API 密钥，并写入您的配置。

```bash
hermes tools
```

---

### Firecrawl（默认）

功能完整的搜索和提取。推荐大多数用户使用。

```bash
# ~/.hermes/.env
FIRECRAWL_API_KEY=fc-your-key-here
```

在 [firecrawl.dev](https://firecrawl.dev) 获取密钥。免费层级包含每月 500 积分。

**自托管 Firecrawl：** 指向您自己的实例而非云端 API：

```bash
# ~/.hermes/.env
FIRECRAWL_API_URL=http://localhost:3002
```

设置 `FIRECRAWL_API_URL` 后，API 密钥为可选项（使用 `USE_DB_AUTHENTICATION=false` 禁用服务器认证）。

---

### SearXNG（免费，自托管）

SearXNG 是一个注重隐私的开源元搜索引擎，聚合来自 70 多个搜索引擎的结果。**无需 API 密钥**——只需将 Hermes 指向一个运行中的 SearXNG 实例。

SearXNG 为**仅搜索**——`web_extract` 需要单独的提取提供商。

#### 方案 A——使用 Docker 自托管（推荐） {#option-a--self-host-with-docker-recommended}

这为您提供无速率限制的私有实例。

**1. 创建工作目录：**

```bash
mkdir -p ~/searxng/searxng
cd ~/searxng
```

**2. 编写 `docker-compose.yml`：**

```yaml
# ~/searxng/docker-compose.yml
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    ports:
      - "8888:8080"
    volumes:
      - ./searxng:/etc/searxng:rw
    environment:
      - SEARXNG_BASE_URL=http://localhost:8888/
    restart: unless-stopped
```

**3. 启动容器：**

```bash
docker compose up -d
```

**4. 启用 JSON API 格式：**

SearXNG 默认禁用 JSON 输出。复制生成的配置并启用它：

```bash
# 从容器中复制自动生成的配置
docker cp searxng:/etc/searxng/settings.yml ~/searxng/searxng/settings.yml
```

打开 `~/searxng/searxng/settings.yml`。
如果文件中存在 `use_default_settings: true`，则该文件只包含你的覆盖项，其余所有设置都继承自内置默认值。
要为 Hermes 启用 JSON 响应，请添加以下覆盖项：

```yaml
search:
  formats:
    - html
    - json
```

你的 `settings.yml` 应该类似于：

```yaml
# 在扩展默认设置之前请先阅读文档：
# https://docs.searxng.org/admin/settings/

use_default_settings: true

server:
  secret_key: "abcdef12345678"
  image_proxy: true

search:
  formats:
    - html
    - json
```

**5. 重启以应用更改：**

```bash
docker cp ~/searxng/searxng/settings.yml searxng:/etc/searxng/settings.yml
docker restart searxng
```

**6. 验证是否正常工作：**

```bash
curl -s "http://localhost:8888/search?q=test&format=json" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'{len(d[\"results\"])} results')"
```

您应该看到类似 `10 results` 的输出。如果收到 `403 Forbidden`，说明 JSON 格式仍未启用——请重新检查第 4 步。

**7. 配置 Hermes：**

```bash
# ~/.hermes/.env
SEARXNG_URL=http://localhost:8888
```

然后在 `~/.hermes/config.yaml` 中选择 SearXNG 作为搜索后端：

```yaml
web:
  search_backend: "searxng"
```

或通过 `hermes tools` → Web Search & Extract → SearXNG 设置。

---

#### 方案 B——使用公共实例

公共 SearXNG 实例列表见 [searx.space](https://searx.space/)。筛选**已启用 JSON 格式**的实例（表格中有显示）。

```bash
# ~/.hermes/.env
SEARXNG_URL=https://searx.example.com
```

:::caution 公共实例
公共实例有速率限制、可用性不稳定，且可能随时禁用 JSON 格式。生产环境强烈建议自托管。
:::

---

#### 将 SearXNG 与提取提供商配合使用

SearXNG 负责搜索；`web_extract` 需要单独的提供商。使用按能力配置的键：

```yaml
# ~/.hermes/config.yaml
web:
  search_backend: "searxng"
  extract_backend: "firecrawl"   # 或 tavily、perplexity、keenable、exa、parallel
```

使用此配置，Hermes 对所有搜索查询使用 SearXNG，对 URL 提取使用 Firecrawl——将免费搜索与高质量提取相结合。

---

### Tavily

针对 AI 优化的搜索和提取。在 `hermes tools` 中选择 Tavily（或设置 `web.backend: tavily`），即可在无账号的情况下**免密钥**使用（有速率限制）。需要更高额度时再设置 API 密钥。

```bash
# 可选——选择 Tavily 后若要免密钥使用，可跳过此步
# ~/.hermes/.env
TAVILY_API_KEY=tvly-your-key-here
```

在 [app.tavily.com](https://app.tavily.com/home) 获取密钥。参见 [Tavily 免密钥使用](https://docs.tavily.com/documentation/keyless)。

---

### Perplexity

[Perplexity 的 Search API](https://docs.perplexity.ai/docs/search/quickstart) 从 Perplexity 自有索引返回经过排序、带日期的结果（`web_search`）。对于 `web_extract`，它使用与官方 `pplx` CLI 相同的“与查询相关的*片段*”路径：您得到的是每个页面中相关的段落，省略处以 `…` 标记，而不是逐字的整页内容——需要完整页面时，请将 Firecrawl / Exa / Parallel 设为 `web.extract_backend`。仅支持带密钥使用；没有匿名层级。

```bash
# ~/.hermes/.env
PERPLEXITY_API_KEY=pplx-your-key-here
```

在 [perplexity.ai/account/api](https://www.perplexity.ai/account/api) 获取密钥。设置 `PERPLEXITY_BASE_URL` 可通过代理路由。

---

### Exa

具有语义理解的神经搜索。适合研究和查找概念相关内容。

```bash
# ~/.hermes/.env
EXA_API_KEY=your-exa-key-here
```

在 [exa.ai](https://exa.ai) 获取密钥。免费层级包含每月 1 000 次搜索。

---

### Parallel

具备深度研究能力的 AI 原生搜索和提取。

```bash
# ~/.hermes/.env
PARALLEL_API_KEY=your-parallel-key-here
```

在 [parallel.ai](https://parallel.ai) 申请访问权限。

---

### xAI (Grok) {#xai-grok}

通过 Responses API 将 `web_search` 路由至 Grok 服务端的 [web_search 工具](https://docs.x.ai/developers/tools/web-search)。Grok 执行实际搜索并以结构化 JSON 返回最佳结果。

支持两种凭证路径——无需新的环境变量，无需新的设置向导：

```bash
# ~/.hermes/.env（环境变量路径）
XAI_API_KEY=sk-xai-your-key-here
```

或对于 SuperGrok 订阅用户：

```bash
hermes auth add xai-oauth
```

然后选择 xAI 作为搜索后端：

```yaml
# ~/.hermes/config.yaml
web:
  backend: "xai"
```

**可选配置项：**

```yaml
web:
  backend: "xai"
  xai:
    model: grok-build-0.1        # web_search 所需的推理模型（默认）
    allowed_domains:             # 可选，最多 5 个——与 excluded_domains 互斥
      - arxiv.org
    excluded_domains:            # 可选，最多 5 个
      - example-spam.com
    timeout: 90                  # 秒（默认）
```

**仅搜索**——如果同时需要 `web_extract`，请与 Firecrawl / Tavily / Keenable / Exa / Parallel 配合使用。遇到 401 时，提供商会执行一次强制 OAuth token 刷新并重试（覆盖窗口中途吊销和主动过期检查无法解码的不透明 token）；环境变量凭证跳过重试。

:::caution 信任模型
与基于索引的提供商（Brave、Tavily、Exa）返回逐字搜索引擎结果不同，xAI 是由 LLM 选择要呈现的 URL 并自行撰写标题和描述。查询的*内容*会影响输出，因此恶意构造的查询（例如通过 agent 获取的不可信上游输入注入）原则上可以引导 Grok 输出攻击者指定的 URL。对返回的 URL 应与对待任何模型生成链接一样——在获取前进行验证，尤其是当查询来自不可信输入时。
:::

---

## 配置

### 单一后端

为所有网页功能设置一个提供商：

```yaml
# ~/.hermes/config.yaml
web:
  backend: "searxng"   # firecrawl | searxng | brave-free | ddgs | tavily | perplexity | keenable | exa | parallel | xai
```

### 按能力配置 {#per-capability-configuration}

搜索和提取使用不同的提供商。这允许您将免费搜索（SearXNG）与付费提取提供商组合使用，反之亦然：

```yaml
# ~/.hermes/config.yaml
web:
  search_backend: "searxng"     # 由 web_search 使用
  extract_backend: "firecrawl"  # 由 web_extract 使用
```

当按能力键为空时，两者均回退到 `web.backend`。只有在从未写入过任何网页选择时，才会根据存在的 API 密钥/URL 自动检测后端——一旦存在选择，运行时始终使用它，向 `.env` 添加密钥不会改变网页流量的路由。

**优先级顺序（按能力）：**
1. `web.search_backend` / `web.extract_backend`（显式按能力配置）
2. `web.backend`（共享回退；`nous` = 托管的 Tool Gateway）
3. 从环境变量自动检测（仅限从未配置过的环境）

### 自动检测

如果**从未**选择过后端（您或 `hermes tools` 都没有写入过 `web.backend` / 按能力键），Hermes 根据已设置的凭证选择第一个可用的后端：

| 存在的凭证 | 自动选择的后端 |
|--------------------|-----------------------|
| `TAVILY_API_KEY` | tavily |
| `PERPLEXITY_API_KEY` | perplexity |
| `EXA_API_KEY` | exa |
| `PARALLEL_API_KEY` | parallel |
| `FIRECRAWL_API_KEY` 或 `FIRECRAWL_API_URL`（或 Nous Tool Gateway 已就绪） | firecrawl |
| `SEARXNG_URL` | searxng |
| `BRAVE_SEARCH_API_KEY` | brave-free |
| 可导入 `ddgs` 包 | ddgs |
| *（完全未设置任何内容）* | 免密钥轮换：exa / parallel / firecrawl / keenable（轮询） |

**免密钥免费层级轮换：** 当上述凭证*均*不存在时，请求会在轮换成员厂商的公共免费层级（Exa、Parallel、Firecrawl、Keenable）之间轮换，使网页工具在全新安装、零配置的情况下即可工作——被限速的请求会自动故障转移到轮换中的下一个厂商。在 `hermes tools` 中固定某个厂商即可停止轮换（此时轮换仅在被限流时用作故障转移的后继顺序）。所有免费层级在突发负载下都会受到厂商限速；持续的正常使用可以顺利通过。设置 `web.keyless_fallback: false` 可关闭该层级——关闭后且没有凭证时，在配置提供商之前网页工具不可用。

**带密钥后端的一次性免密钥救援：** 当您选择的/带密钥的后端某次调用失败（密钥错误、服务中断、上游 5xx）时，该次调用会自动在免密钥免费层级轮换上重试，而不是报错——结果会注明由哪个厂商提供以及原因（`rescued_from` / `backend_error`）。这种故障转移从不粘滞：紧接着的下一次 `web_search`/`web_extract` 调用会再次尝试您选择的后端。使用 `web.keyless_rescue: false` 禁用（当 `keyless_fallback` 关闭时它也会关闭）。

xAI Web Search **不在**自动检测链中——设置了 `XAI_API_KEY`（或通过 xAI Grok OAuth 登录）不会自动将网页流量路由至 xAI，因为这些凭证同时用于推理/TTS/图像生成，用户可能希望为网页使用不同的后端。请通过 `web.backend: "xai"` 显式启用。

---

## 验证设置

运行 `hermes setup` 查看检测到的网页后端：

```
✅ Web Search & Extract (searxng)
```

或通过 CLI 检查：

```bash
# 激活 venv 并直接运行网页工具模块
source ~/.hermes/hermes-agent/.venv/bin/activate
python -m tools.web_tools
```

这将打印活动后端及其状态：

```
✅ Web backend: searxng
   Using SearXNG (search only): http://localhost:8888
```

---

## 故障排查

### `web_search` 返回 `{"success": false}`

- 检查 `SEARXNG_URL` 是否可达：`curl -s "http://localhost:8888/search?q=test&format=json"`
- 如果收到 HTTP 403，说明 JSON 格式已禁用——在 `settings.yml` 的 `formats` 列表中添加 `json` 并重启
- 如果收到连接错误，容器可能未运行：`docker ps | grep searxng`

### `web_extract` 提示"search-only backend"

SearXNG 无法提取 URL 内容。将 `web.extract_backend` 设置为支持提取的提供商：

```yaml
web:
  search_backend: "searxng"
  extract_backend: "firecrawl"  # 或 tavily / perplexity / keenable / exa / parallel
```

### SearXNG 返回 0 条结果

部分公共实例禁用了某些搜索引擎或分类。请尝试：
- 换一个查询词
- 从 [searx.space](https://searx.space/) 换一个公共实例
- 自托管实例以获得稳定结果

### 公共实例遭遇速率限制

切换到自托管实例（参见上方[方案 A](#option-a--self-host-with-docker-recommended)）。使用 Docker，您自己的实例没有速率限制。

### `web_extract` 返回截断内容并附有 `[TRUNCATED]` 尾注

对于超出字符预算的页面这是预期行为。尾注会给出保存完整干净文本的磁盘文件，以及分页读取被省略中间部分的确切 `read_file` 调用。若要内联查看更多内容，请在 `config.yaml` 中调大 `web.extract_char_limit`，或在调用时传入更大的 `char_limit`。

---

## 可选技能：`searxng-search`

对于需要直接通过 `curl` 使用 SearXNG 的 agent（例如作为网页工具集不可用时的回退），请安装 `searxng-search` 可选技能：

```bash
hermes skills install official/research/searxng-search
```

这将添加一个技能，教 agent 如何：
- 通过 `curl` 或 Python 调用 SearXNG JSON API
- 按分类筛选（`general`、`news`、`science` 等）
- 处理分页和错误情况
- 在 SearXNG 不可达时优雅降级
