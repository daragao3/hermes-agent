---
sidebar_position: 14
title: "API 服务器"
description: "将 hermes-agent 作为 OpenAI 兼容的 API 暴露给任意前端"
---

# API 服务器

API 服务器将 hermes-agent 作为 OpenAI 兼容的 HTTP 端点暴露出来。任何支持 OpenAI 格式的前端——Open WebUI、LobeChat、LibreChat、NextChat、ChatBox 以及数百个其他工具——都可以连接到 hermes-agent 并将其用作后端。

你的 agent 使用完整工具集（终端、文件操作、网络搜索、记忆、技能）处理请求，并返回最终响应。在流式传输时，工具进度指示器会内联显示，让前端能够展示 agent 正在执行的操作。

:::tip 一个后端同时覆盖模型与工具
Hermes 本身需要配置好 provider（提供商）和工具后端，API 服务器才能发挥作用。[Nous Portal](/user-guide/features/tool-gateway) 订阅同时处理两者——300+ 个模型，以及通过 Tool Gateway 提供的网络/图像/TTS/浏览器功能。在启动 API 服务器之前运行一次 `hermes setup --portal`，Open WebUI 或 LobeChat 等前端即可获得一个完整配备工具的后端。
:::

## 快速开始

### 1. 启用 API 服务器

在 `~/.hermes/.env` 中添加：

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=change-me-local-dev
# 可选：仅当浏览器需要直接调用 Hermes 时
# API_SERVER_CORS_ORIGINS=http://localhost:3000
```

### 2. 启动 gateway

```bash
hermes gateway
```

你将看到：

```
[API Server] API server listening on http://127.0.0.1:8642
```

### 3. 连接前端

将任何 OpenAI 兼容客户端指向 `http://localhost:8642/v1`：

```bash
# 使用 curl 测试
curl http://localhost:8642/v1/chat/completions \
  -H "Authorization: Bearer change-me-local-dev" \
  -H "Content-Type: application/json" \
  -d '{"model": "hermes-agent", "messages": [{"role": "user", "content": "Hello!"}]}'
```

或连接 Open WebUI、LobeChat 或其他任意前端——参见 [Open WebUI 集成指南](/user-guide/messaging/open-webui)获取分步说明。

## 端点

### POST /v1/chat/completions

标准 OpenAI Chat Completions 格式。无状态——完整对话通过每次请求的 `messages` 数组传入。

**请求：**
```json
{
  "model": "hermes-agent",
  "messages": [
    {"role": "system", "content": "You are a Python expert."},
    {"role": "user", "content": "Write a fibonacci function"}
  ],
  "stream": false
}
```

**响应：**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "hermes-agent",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Here's a fibonacci function..."},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 50, "completion_tokens": 200, "total_tokens": 250}
}
```

**内联图像输入：** 用户消息可以将 `content` 作为 `text` 和 `image_url` 部分的数组发送。支持远程 `http(s)` URL 和 `data:image/...` URL：

```json
{
  "model": "hermes-agent",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": "https://example.com/cat.png", "detail": "high"}}
      ]
    }
  ]
}
```

上传的文件（`file` / `input_file` / `file_id`）和非图像 `data:` URL 将返回 `400 unsupported_content_type`。

**流式传输**（`"stream": true`）：返回逐 token 响应块的 Server-Sent Events（SSE）。对于 **Chat Completions**，流使用标准 `chat.completion.chunk` 事件，以及 Hermes 自定义的 `hermes.tool.progress` 事件用于工具启动的 UX 展示。对于 **Responses**，流使用 OpenAI Responses 事件类型，如 `response.created`、`response.output_text.delta`、`response.output_item.added`、`response.output_item.done` 和 `response.completed`。

**流中的工具进度：**
- **Chat Completions**：Hermes 发出 `event: hermes.tool.progress` 以提供工具启动可见性，同时不污染持久化的 assistant 文本。
- **Responses**：Hermes 在 SSE 流期间发出符合规范的 `function_call` 和 `function_call_output` 输出项，让客户端能够实时渲染结构化工具 UI。

### POST /v1/responses

OpenAI Responses API 格式。通过 `previous_response_id` 支持服务端对话状态——服务器存储完整的对话历史（包括工具调用和结果），因此多轮上下文无需客户端自行管理。

**请求：**
```json
{
  "model": "hermes-agent",
  "input": "What files are in my project?",
  "instructions": "You are a helpful coding assistant.",
  "store": true
}
```

**响应：**
```json
{
  "id": "resp_abc123",
  "object": "response",
  "status": "completed",
  "model": "hermes-agent",
  "output": [
    {"type": "function_call", "status": "completed", "name": "terminal", "arguments": "{\"command\": \"ls\"}", "call_id": "call_1"},
    {"type": "function_call_output", "status": "completed", "call_id": "call_1", "output": "README.md src/ tests/"},
    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Your project has..."}]}
  ],
  "usage": {"input_tokens": 50, "output_tokens": 200, "total_tokens": 250}
}
```

`output` 数组中的工具调用已由 Hermes agent 在服务端执行完毕——它们以 `"status": "completed"` 的形式回放，用于结构化工具 UI，绝不会作为待客户端执行的挂起调用出现。

**内联图像输入：** `input[].content` 可以包含 `input_text` 和 `input_image` 部分。支持远程 URL 和 `data:image/...` URL：

```json
{
  "model": "hermes-agent",
  "input": [
    {
      "role": "user",
      "content": [
        {"type": "input_text", "text": "Describe this screenshot."},
        {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0K..."}
      ]
    }
  ]
}
```

上传的文件（`input_file` / `file_id`）和非图像 `data:` URL 将返回 `400 unsupported_content_type`。

#### 使用 previous_response_id 进行多轮对话

链式响应以在多轮之间保持完整上下文（包括工具调用）：

```json
{
  "input": "Now show me the README",
  "previous_response_id": "resp_abc123"
}
```

服务器从存储的响应链重建完整对话——所有之前的工具调用和结果均被保留。链式请求还共享同一个 session，因此多轮对话在仪表板和 session 历史中显示为单个条目。

#### 命名对话

使用 `conversation` 参数代替追踪响应 ID：

```json
{"input": "Hello", "conversation": "my-project"}
{"input": "What's in src/?", "conversation": "my-project"}
{"input": "Run the tests", "conversation": "my-project"}
```

服务器自动链接到该对话中的最新响应。类似于 gateway session 的 `/title` 命令。

### GET /v1/responses/\{id\}

通过 ID 检索之前存储的响应。

### DELETE /v1/responses/\{id\}

删除存储的响应。

### GET /v1/models

将 agent 列为可用模型。广播的模型名称默认为 [profile](/user-guide/profiles) 名称（默认 profile 则为 `hermes-agent`）。大多数前端进行模型发现时需要此端点。

`/v1/models` 有意保持为低开销的 OpenAI 兼容接口。它**不会**枚举 Hermes 可路由到的每一个已认证 provider/模型组合，也不做定价或能力信息的补充。

### GET /api/model/options

了解 Hermes 的客户端可以请求与仪表板和 TUI 相同的、经过整理的 provider/模型清单。该路由使用 API 服务器常规的 bearer 认证，返回 provider 行、模型能力提示和定价元数据——这些内容不属于 OpenAI 兼容的 `/v1/models` 响应：

```bash
curl \
  -H "Authorization: Bearer $API_SERVER_KEY" \
  "http://127.0.0.1:8642/api/model/options"
```

该载荷与仪表板 Models 页面和 TUI `model.options` RPC 使用的底层数据相同。它返回已认证的 provider、整理后的模型列表、按模型的定价以及模型能力提示。

对于自定义 provider，常规打开有意保持保守：Hermes 只探测**当前选中的**自定义端点，以免某个过期或离线的已保存端点阻塞选择器。显式刷新会切换为完整探测，并清空 provider 模型缓存：

```bash
curl \
  -H "Authorization: Bearer $API_SERVER_KEY" \
  "http://127.0.0.1:8642/api/model/options?refresh=1"
```

当 OpenAI 兼容客户端只需要一个模型名称、以便在 chat/responses 请求中回传时，使用 `/v1/models`。当已认证的 UI 需要更丰富的 Hermes 专属选择器元数据时，使用 `/api/model/options`。

### GET /v1/capabilities

返回 API 服务器稳定接口的机器可读描述，供外部 UI、编排器和插件桥接使用。

```json
{
  "object": "hermes.api_server.capabilities",
  "platform": "hermes-agent",
  "model": "hermes-agent",
  "auth": {"type": "bearer", "required": true},
  "features": {
    "chat_completions": true,
    "responses_api": true,
    "run_submission": true,
    "run_status": true,
    "run_events_sse": true,
    "run_stop": true
  }
}
```

在集成仪表板、浏览器 UI 或控制平面时使用此端点，以便它们能够发现当前运行的 Hermes 版本是否支持 runs、流式传输、取消和 session 连续性，而无需依赖私有 Python 内部实现。

## 浏览器扩展控制 {#browser-extension-control}

Hermes 可以将浏览器工具路由到一个经过认证的扩展，由它控制与当前 Hermes session 关联的浏览器会话。该功能默认禁用；将 `browser.extension_control.enabled` 设为 `true` 即可启用：

```yaml
browser:
  extension_control:
    enabled: true
```

本地 API 路径同样需要 API 服务器的 bearer 密钥。控制器只能为已存在的服务端 session 注册。Hermes 从已认证的服务端状态派生控制器主体（principal）；客户端提供的 `principal_id` 会被忽略。

通过 `GET /v1/capabilities` 发现实时契约。`browser_extension_control` 对象会报告该功能是否启用、协议版本、传输名称以及精确的能力允许列表：

```text
controller.noop
browser_back
browser_click
browser_navigate
browser_press
browser_screenshot
browser_scroll
browser_snapshot
browser_tab_activate
browser_tabs
browser_type
```

请求的能力若不在该列表中会被过滤掉。原始 CDP、任意脚本执行、控制台访问、上传、图像提取和视觉能力都不属于控制器协议的一部分。

当请求没有绑定的控制器身份，或该功能被禁用时，Hermes 会保留现有的浏览器后端。一旦 gateway 为请求绑定了控制器主体和传输族，该扩展通道即具有权威性：缺失、有歧义、已断开或能力不足的控制器会以失败关闭（fail closed），而不会静默切换到另一个本地/云端浏览器。选中某个确切的控制器后，其结果或错误即为权威结果，Hermes 绝不会通过其他后端重试同一操作。

### 本地 API 注册 {#local-api-registration}

1. 发送一个已认证的 `POST /v1/browser-control/register`，携带 `protocol_version`、`session_id`、`controller_id`、`browser_profile_id` 以及请求的 `capabilities`。
2. Hermes 返回一个 TTL 为 30 秒的一次性票据，以及经过过滤、绑定到服务端的控制器作用域。
3. 使用以下两个 WebSocket 子协议打开 `GET /v1/browser-control/ws`：`hermes-browser-control-v1` 和 `hermes-browser-control-ticket.<ticket>`。

票据绝不会通过查询字符串接受。未知、过期、重复使用或格式错误的票据会在 WebSocket 升级之前失败。

### 控制器帧 {#controller-frames}

Hermes 发送 `browser.controller.command` 帧，其中包含 `command_id`、`action`、不可变的 `arguments`、浏览器/控制器 id，以及发起调用的 `tool_call_id`。控制器以 `browser.controller.result` 回复，携带相同的 `command_id`、一个精确的布尔值 `ok`，以及 `result` 或 `error` 之一。取消和超时会发出 `browser.controller.cancel`；迟到的结果会被忽略。

意外的 socket 断开会将控制器标记为离线，并保留已在执行中的工作，直到每条命令原定的截止时间。使用相同主体、profile、session、控制器 id、浏览器 profile 和传输身份重新连接，会刷新传输，且在任何延迟的取消被刷出之前不会接纳新工作。协商的能力可以在重连时变化；它们不属于身份字段。在同一已认证 session 通道中使用不同的控制器 id 或浏览器 profile 属于硬替换：旧的挂起工作会在后继者变为可路由之前被取消。如需有意的硬分离，请在已认证的控制器传输上发送 `browser.controller.detach`——这会立即取消挂起的工作。仅仅关闭 socket 会被视为可恢复的断开连接。

已认证的仪表板传输通过其 Gateway RPC/事件通道提供相同的注册、结果、心跳、能力和归属语义。在两种传输中，选择都要求在主体、profile、session、控制器、浏览器 profile、传输族和能力上存在唯一且无歧义的精确匹配。一旦选中，控制器的失败即为权威结果，绝不会通过其他浏览器后端重试。

## 按请求选择模型 {#per-request-model-selection}

已认证的客户端可以在每个请求中发送以下字段，覆盖 Hermes 的默认模型选择：

- `model` —— 本轮次的目标模型 id
- `provider` —— 本轮次用于解析凭据/运行时的 Hermes provider slug
- `model_options` —— 请求作用域的推理 / 服务层级控制

以下端点接受相同的请求字段：

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/runs`
- `POST /api/sessions/{session_id}/chat`
- `POST /api/sessions/{session_id}/chat/stream`

优先级是确定的：

1. session 的 `/model` 覆盖（如果该 session 已设置）
2. 当请求的 `model` 是已配置的路由别名时，所选中的静态 `gateway.platforms.api_server.model_routes` 映射
3. 没有匹配的路由别名时，直接使用请求中的 `model` / `provider`
4. 全局 gateway 配置 / 环境变量默认值

无论最终采用哪个模型/provider，`model_options` 都保持请求作用域。如果请求发送的 `provider` 与已配置的 `model_routes` 别名冲突，Hermes 会以 `400` 拒绝该请求，而不是静默地把路由凭据与另一个 provider 混用。

**OpenAI 兼容端点上的裸 `model` 值需要显式启用。** 通用 OpenAI 客户端经常硬编码模型名称（`gpt-4o` 等），而现有部署依赖这些名称回退到 gateway 默认值。因此在 `POST /v1/chat/completions` 和 `POST /v1/responses` 上，未附带 `provider` 的 `model` 值会被忽略，除非你启用：

```yaml
gateway:
  platforms:
    api_server:
      direct_model_requests: true
```

包含显式 `provider` 的请求——以及 Hermes 原生的 `/v1/runs` 和 session-chat 端点——无论该标志如何，始终遵循请求的模型。

示例：

```json
{
  "model": "MiniMax-M3",
  "provider": "minimax",
  "model_options": {
    "reasoning_effort": "high",
    "service_tier": "priority"
  },
  "messages": [
    {"role": "user", "content": "Summarize the repo status."}
  ]
}
```

### GET /health

健康检查。返回 `{"status": "ok"}`。也可通过 **GET /v1/health** 访问，供期望 `/v1/` 前缀的 OpenAI 兼容客户端使用。

### GET /health/detailed

面向监控和控制平面的已认证就绪检查。它会报告当前 profile 的配置、状态数据库、已配置模型、磁盘空间、gateway/platform 状态、活跃 API run、待处理进程完成通知和活跃 delegation 的有限状态。响应只暴露状态与计数，不包含配置值、凭据、路径、命令、队列载荷或原始错误。

公开的 `/health` 路由仍是低开销的存活探针，不运行就绪检查。就绪状态降级时仍返回 HTTP 200；请检查顶层 `status` 和 `readiness.checks` 字段。

## Runs API（流式友好的替代方案）

除 `/v1/chat/completions` 和 `/v1/responses` 外，服务器还暴露了一个 **runs** API，适用于客户端希望订阅进度事件而非自行管理流式传输的长时 session。

### POST /v1/runs

创建新的 agent run。返回可用于订阅进度事件的 `run_id`。

```json
{
  "run_id": "run_abc123",
  "status": "started"
}
```

Runs 接受简单的 `input` 字符串，以及可选的 `session_id`、`instructions`、`conversation_history` 或 `previous_response_id`。当提供 `session_id` 时，Hermes 会在 run 状态中暴露它，以便外部 UI 将 run 与自己的对话 ID 关联。

如需可安全重试的创建操作，请发送 `Idempotency-Key` 请求头（1–255 个可见 ASCII 字符）。Hermes 会在开始工作前持久地预留该键。完全相同的重试会以 HTTP 202 和 `Idempotency-Replayed: true` 返回原始 `run_id`，即使 gateway 已重启、或 run 已完成、失败或被取消也是如此。以不同的 JSON 载荷复用同一个键会返回 HTTP 409，错误码为 `idempotency_key_conflict`。键按已认证的 API profile/凭据隔离，并在最后一次状态更新后保留 24 小时；客户端应使用唯一且不可猜测的键，且不得将其复用于无关操作。不带该请求头的请求保留旧有行为，始终创建新的 run。

当 `session_id` 指向一个已存在的 Hermes session，且未提供显式的 `conversation_history` 或 `previous_response_id` 时，run 会加载该 session 当前的会话记录。session 轮次租约（lease）会串行化并发写入者，并在经历争用等待后刷新会话记录。

### GET /v1/runs/\{run_id\}

轮询当前 run 状态。适用于需要状态但不想保持 SSE 连接的仪表板，或在导航后重新连接的 UI。

```json
{
  "object": "hermes.run",
  "run_id": "run_abc123",
  "status": "completed",
  "session_id": "space-session",
  "model": "hermes-agent",
  "output": "Done.",
  "usage": {"input_tokens": 50, "output_tokens": 200, "total_tokens": 250}
}
```

状态在终态（`completed`、`failed` 或 `cancelled`）之后会短暂保留，以供轮询和 UI 对账使用。

### GET /v1/runs/\{run_id\}/events

run 的工具调用进度、token 增量和生命周期事件的 Server-Sent Events 流。专为需要附加/分离而不丢失状态的仪表板和厚客户端设计。

当 agent 将工作委派给后台子 agent 时，该流还会携带 `subagent.start` 和 `subagent.complete` 生命周期事件，让客户端能够观察委派结果——包括超时和失败——而不是在子 agent 工作期间 run 一片沉寂。`subagent.complete` 载荷包含子 agent 的状态、摘要、耗时、token/成本数据、用于关联的 `child_session_id`，以及其所属批次的 `delegation_id`（使并发或嵌套的扇出保持可区分）；自由文本字段在离开进程前会经过强制的密钥脱敏。按工具划分的子 agent 事件（`subagent.tool`、进度 tick）有意**不**转发——它们是高频的 UI 噪音；如需逐步细节，请使用每个子 agent 的实时会话记录文件。这些事件仅在父流保持打开时可用；迟到的分离式完成不会重新打开已结束 run 的 SSE 流，也不会改变其终态。

#### 分离式结果与 session 历史 {#detached-results-and-session-history}

后台委派需要一个读取服务端 session 历史的续接：Chat Completions 上显式的 `X-Hermes-Session-Id`、原生的 `/api/sessions/{id}/chat` 请求，或使用 session 历史的 Runs 请求。不带该请求头的 Chat Completions、Responses 链，以及带有 `previous_response_id` 或调用方提供历史的 Runs 请求，则会同步执行委派，在原始轮次中返回结果。仅仅从请求内容派生出 session ID 并不会启用分离式投递。

对于可续接的请求，完成结果按每个委派单元持久化一次。它可以通过 `GET /api/sessions/{id}/messages` 获取，也会出现在下一个真实客户端轮次的 session 历史中。重试不会再次插入相同的结果；中途的任务失败通知有各自独立的身份。当某个客户端轮次持有 session 租约时，投递会等待，并跟随压缩续接。Chat Completions 会在 JSON 和流式响应中回显你提供的显式 session ID；即使发生压缩后，也请继续发送该 ID。

完成结果**绝不会发起未经请求的模型轮次**，也不会绕过待处理的人工确认。下一个轮次由客户端掌控。继续使用自身历史快照的客户端应使用同步委派，而不是期望服务端的投递行被合并进这些快照。

未消费的事件缓冲区会在五分钟后过期，避免已断开的客户端导致内存无限增长。这里只会过期传输状态：仍在执行的 run 会继续保留在状态轮询、审批、停止控制和并发计数中，直到其 executor 工作真正退出。已连接的 SSE 订阅者会继续正常消费事件。

### POST /v1/runs/\{run_id\}/stop

中断正在运行的 agent 轮次。端点立即返回 `{"status": "stopping"}`，同时 Hermes 要求活跃 agent 在下一个安全中断点停止。
run 会保持 `stopping` 并继续被跟踪，直到 executor 支持的工作退出，然后进入 `cancelled`；停止请求不会隐藏仍在运行的 worker。

### POST /v1/runs/\{run_id\}/approval

解决某个正在等待人工决策的 run 的待处理审批（例如受审批策略限制的工具调用）。请求体携带审批决策；决策被记录后 run 即恢复执行。该端点在 `/v1/capabilities` 中以 `run_approval` 特性广播，便于外部 UI 在展示审批提示之前检测是否支持。

## Jobs API（后台计划任务）

服务器暴露了一个轻量级 jobs CRUD 接口，用于从远程客户端管理计划/后台 agent run。所有端点均受同一 bearer 认证保护。

### GET /api/jobs

列出所有计划任务。

### POST /api/jobs

创建新的计划任务。请求体接受与 `hermes cron` 相同的结构——prompt（提示词）、schedule（计划）、skills（技能）、provider 覆盖、投递目标。

### GET /api/jobs/\{job_id\}

获取单个任务的定义和最后一次运行状态。

### PATCH /api/jobs/\{job_id\}

更新现有任务的字段（prompt、schedule 等）。部分更新会被合并。

### DELETE /api/jobs/\{job_id\}

删除任务。同时取消任何正在进行的 run。

### POST /api/jobs/\{job_id\}/pause

暂停任务而不删除它。下次计划运行的时间戳将被挂起，直到恢复。

### POST /api/jobs/\{job_id\}/resume

恢复之前暂停的任务。

### POST /api/jobs/\{job_id\}/run

立即触发任务运行，不受计划限制。

## Sessions API（通过 REST 控制 session）

外部 UI 无需搭建仪表板即可通过 REST 管理 Hermes 的 session。所有端点均受 `API_SERVER_KEY` 保护，位于 `/api/sessions/*` 之下。

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/sessions` | 列出 session（分页——`limit`、`offset`、`source`、`include_children`） |
| `POST` | `/api/sessions` | 创建一个空 session |
| `GET` | `/api/sessions/{id}` | 读取 session 元数据 |
| `PATCH` | `/api/sessions/{id}` | 更新标题或 `end_reason` |
| `DELETE` | `/api/sessions/{id}` | 删除 session |
| `GET` | `/api/sessions/{id}/messages` | 某个 session 的消息历史 |
| `POST` | `/api/sessions/{id}/fork` | 通过 `SessionDB` 血缘关系分叉 session（与 CLI `/branch` 语义一致） |
| `POST` | `/api/sessions/{id}/chat` | 同步运行一个 agent 轮次 |
| `POST` | `/api/sessions/{id}/chat/stream` | 单轮次的 SSE 包装——发出 `assistant.delta`、`tool.started`、`tool.completed`、`run.completed` 事件 |

`/v1/capabilities` 通过 `session_*` 特性标志和 `endpoints.session_*` 条目广播完整接口，便于外部 UI 检测支持情况并安全回退。`chat` 和 `chat/stream` 的载荷支持内联图片（多模态感知路径）。

```bash
# 分叉一个 session 并运行一个轮次
curl -X POST http://localhost:8642/api/sessions/$ID/fork \
  -H "Authorization: Bearer $API_SERVER_KEY" \
  -d '{"title": "explore alt path"}'

# 通过 SSE 流式运行一个轮次
curl -N -X POST http://localhost:8642/api/sessions/$ID/chat/stream \
  -H "Authorization: Bearer $API_SERVER_KEY" \
  -d '{"input": "what files changed in the last hour?"}'
```

## 技能与工具集发现

`GET /v1/skills` 和 `GET /v1/toolsets` 让外部客户端可以通过 REST 确定性地枚举 agent 的能力，而不必去询问模型。两者均为只读，且受 `API_SERVER_KEY` 保护。

```bash
curl http://localhost:8642/v1/skills \
  -H "Authorization: Bearer $API_SERVER_KEY"
# → [{"name": "github-pr-workflow", "description": "...", "category": "..."}, ...]

curl http://localhost:8642/v1/toolsets \
  -H "Authorization: Bearer $API_SERVER_KEY"
# → [{"name": "core", "label": "...", "description": "...", "enabled": true,
#     "configured": true, "tools": ["read_file", "write_file", ...]}, ...]
```

`/v1/skills` 返回与技能中心内部使用的相同元数据。`/v1/toolsets` 返回为 `api_server` 平台解析出的工具集，以及每个工具集展开后的具体 `tools` 列表。两者都在 `/v1/capabilities` 的 `endpoints.*` 下广播。

## 长期记忆作用域（`X-Hermes-Session-Key`）

像 Open WebUI 这样的多用户前端需要一个稳定的、按频道划分的标识符用于长期记忆（Honcho 等），并且要**独立**于按会话记录划分的 `X-Hermes-Session-Id`（该值会在 `/new` 时轮换）。在 `/v1/chat/completions`、`/v1/responses` 或 `/v1/runs` 上传入 `X-Hermes-Session-Key`，Hermes 会将其透传至 `AIAgent(gateway_session_key=...)`，Honcho 记忆提供商据此派生出稳定的作用域。

```http
POST /v1/chat/completions HTTP/1.1
Authorization: Bearer ***
X-Hermes-Session-Id: transcript-alpha
X-Hermes-Session-Key: agent:main:webui:dm:user-42
```

规则：最长 256 个字符，控制字符（`\r`、`\n`、`\x00`）会被拒绝，该值会在响应中回显（JSON + SSE）。`/v1/capabilities` 通过 `"session_key_header": "X-Hermes-Session-Key"` 广播支持情况。若不传该键，Honcho 的 `per-session` 策略会为每个 `session_id` 产生不同的作用域——这正是 Hermes 此前的行为。

## 系统 Prompt 处理

当前端发送 `system` 消息（Chat Completions）或 `instructions` 字段（Responses API）时，hermes-agent 会将其**叠加在**核心系统 prompt 之上。你的 agent 保留所有工具、记忆和技能——前端的系统 prompt 只是添加额外指令。

这意味着你可以按前端自定义行为，而不会失去能力：
- Open WebUI 系统 prompt："You are a Python expert. Always include type hints."
- agent 仍然拥有终端、文件工具、网络搜索、记忆等。

## 认证

通过 `Authorization` 请求头进行 Bearer token 认证：

```
Authorization: Bearer ***
```

通过 `API_SERVER_KEY` 环境变量配置密钥。如果需要浏览器直接调用 Hermes，还需将 `API_SERVER_CORS_ORIGINS` 设置为明确的允许列表。

### 多 profile 路由（`/p/<profile>/…`） {#multi-profile-routing-pprofile}

当启用了[多 profile gateway 路由](/user-guide/multi-profile-gateways)（`gateway.multiplex_profiles`）时，共享监听器通过 `/p/<profile>/` URL 前缀为每个 profile 提供服务——并且**认证绑定到被路由的 profile**：

- 发往 `/p/<profile>/v1/...` 的请求必须出示该 profile 自己的 `API_SERVER_KEY`（来自 `~/.hermes/profiles/<profile>/.env`）。默认监听器的密钥在命名 profile 前缀上会被拒绝。
- 不带前缀的路由和 `/p/default/...` 继续使用默认 profile 的密钥。
- 没有自己 `API_SERVER_KEY` 的命名 profile 会以失败关闭——在你为其设置密钥之前，其前缀不可访问。
- run 按 profile 划分作用域：`/v1/runs/{run_id}` 及其 `events`、`stop`、`steer` 和 `approval` 路由只响应创建该 run 的 profile（包括通过 `/api/sessions/{id}/chat/stream` 启动的 run）；其他 profile 的 run id 会返回 `404`，绝不会返回 `403`。

:::warning 破坏性变更（2026 年 7 月）
在此修复之前，有效的默认 profile 密钥在任何 `/p/<profile>/` 前缀上都会被接受。如果你曾依赖一个在各 profile 前缀之间共享的密钥，请在每个 profile 的 `.env` 中设置不同的 `API_SERVER_KEY`——在命名前缀上复用默认密钥现在会返回 `401`。
:::

:::warning 安全
API 服务器提供对 hermes-agent 工具集的完整访问权限，**包括终端命令**。**每一个部署都必须**设置 `API_SERVER_KEY`，包括默认绑定在 `127.0.0.1` 上的回环部署。当你明确允许浏览器调用方时，请保持 `API_SERVER_CORS_ORIGINS` 范围尽量小，以控制浏览器访问。
:::

## 配置

### 环境变量

| 变量 | 默认值 | 描述 |
|----------|---------|-------------|
| `API_SERVER_ENABLED` | `false` | 启用 API 服务器 |
| `API_SERVER_PORT` | `8642` | HTTP 服务器端口 |
| `API_SERVER_HOST` | `127.0.0.1` | 绑定地址（默认仅限本地） |
| `API_SERVER_KEY` | _（必填）_ | 认证用 Bearer token |
| `API_SERVER_CORS_ORIGINS` | _（无）_ | 逗号分隔的允许浏览器来源 |
| `API_SERVER_MODEL_NAME` | _（profile 名称）_ | `/v1/models` 上的模型名称。默认为 profile 名称，默认 profile 则为 `hermes-agent`。 |

### config.yaml

相同的设置也可以写在 `~/.hermes/config.yaml` 中嵌套的 `gateway.api_server:` 小节下：

```yaml
gateway:
  api_server:
    enabled: true
    port: 8642
    host: 127.0.0.1
    key: your-secret-key
    cors_origins: http://localhost:3000
    model_name: my-hermes
    max_concurrent_runs: 10   # 并发 run 上限；0 表示禁用该限制
```

`port`、`key`、`host`、`cors_origins` 和 `model_name` 会自动桥接到该平台的 `extra` 设置中，行为与对应的 `API_SERVER_*` 环境变量完全一致。环境变量优先于 `config.yaml` 中的值。该配置块同样可以放在 `gateway.platforms.api_server:` 或顶层 `platforms.api_server:` 小节下。

### 并发 run 上限 {#concurrent-run-cap}

API 服务器会限制 OpenAI 兼容端点和 Runs 端点上可同时执行的 agent run 数量。该上限读取自 `gateway.api_server.max_concurrent_runs`（默认 **10**；`0` 表示禁用该限制，负值会被钳制为 0）。达到上限时，新的启动 run 请求会被拒绝，返回 **HTTP 429** `Too many concurrent runs (max N)`——客户端应退避后重试。

## 安全响应头

所有响应均包含安全响应头：
- `X-Content-Type-Options: nosniff` — 防止 MIME 类型嗅探
- `Referrer-Policy: no-referrer` — 防止 referrer 泄露

## CORS

API 服务器默认**不**启用浏览器 CORS。

如需直接浏览器访问，请设置明确的允许列表：

```bash
API_SERVER_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

启用 CORS 后：
- **预检响应**包含 `Access-Control-Max-Age: 600`（10 分钟缓存）
- **SSE 流式响应**包含 CORS 头，使浏览器 EventSource 客户端能够正常工作
- **`X-Hermes-Session-Id`** 是允许的请求头，因此处于允许列表来源上的浏览器可以请求 session 续接。
- **`Idempotency-Key`** 是允许的请求头——客户端可发送它用于去重（响应按 key 缓存 5 分钟）

大多数已记录的前端（如 Open WebUI）采用服务器到服务器连接，完全不需要 CORS。

## 兼容前端

任何支持 OpenAI API 格式的前端均可使用。已测试/记录的集成：

| 前端 | Stars | 连接方式 |
|----------|-------|------------|
| [Open WebUI](/user-guide/messaging/open-webui) | 126k | 提供完整指南 |
| LobeChat | 73k | 自定义 provider 端点 |
| LibreChat | 34k | librechat.yaml 中的自定义端点 |
| AnythingLLM | 56k | 通用 OpenAI provider |
| NextChat | 87k | BASE_URL 环境变量 |
| ChatBox | 39k | API Host 设置 |
| Jan | 26k | 远程模型配置 |
| HF Chat-UI | 8k | OPENAI_BASE_URL |
| big-AGI | 7k | 自定义端点 |
| OpenAI Python SDK | — | `OpenAI(base_url="http://localhost:8642/v1")` |
| curl | — | 直接 HTTP 请求 |

## 使用 Profiles 的多用户设置

要为多个用户提供各自隔离的 Hermes 实例（独立的配置、记忆、技能），请使用 [profiles](/user-guide/profiles)：

```bash
# 为每个用户创建 profile
hermes profile create alice
hermes profile create bob

# 在不同端口上配置每个 profile 的 API 服务器。API_SERVER_* 是环境变量
# （不是 config.yaml 键），因此将它们写入每个 profile 的 .env：
cat >> ~/.hermes/profiles/alice/.env <<EOF
API_SERVER_ENABLED=true
API_SERVER_PORT=8643
API_SERVER_KEY=alice-secret
EOF

cat >> ~/.hermes/profiles/bob/.env <<EOF
API_SERVER_ENABLED=true
API_SERVER_PORT=8644
API_SERVER_KEY=bob-secret
EOF

# 启动每个 profile 的 gateway
hermes -p alice gateway &
hermes -p bob gateway &
```

每个 profile 的 API 服务器自动将 profile 名称作为模型 ID 广播：

- `http://localhost:8643/v1/models` → 模型 `alice`
- `http://localhost:8644/v1/models` → 模型 `bob`

在 Open WebUI 中，将每个添加为单独的连接。模型下拉列表显示 `alice` 和 `bob` 作为不同模型，每个均由完全隔离的 Hermes 实例支持。详见 [Open WebUI 指南](/user-guide/messaging/open-webui#multi-user-setup-with-profiles)。

## 限制

- **响应存储** — 存储的响应（用于 `previous_response_id`）持久化在 SQLite 中，gateway 重启后仍然存在。最多存储 100 个响应（LRU 淘汰）。
- **不支持文件上传** — 两个端点（`/v1/chat/completions` 和 `/v1/responses`）均支持内联图像，但不支持通过 API 上传文件（`file`、`input_file`、`file_id`）和非图像文档输入。
- **简单的 OpenAI 客户端仍只看到别名** — `/v1/models` 广播的是稳定的 Hermes 别名（`hermes-agent` 或当前 profile 名称）。更丰富的客户端可以在请求中发送显式的 `provider` / `model_options` 覆盖。

## 代理模式

API 服务器还作为 **gateway 代理模式**的后端。当另一个 Hermes gateway 实例配置了指向此 API 服务器的 `GATEWAY_PROXY_URL` 时，它会将所有消息转发到这里，而不是运行自己的 agent。这支持分离部署——例如，一个处理 Matrix E2EE 的 Docker 容器将请求中继到宿主机侧的 agent。

完整设置指南参见 [Matrix 代理模式](/user-guide/messaging/matrix#proxy-mode-e2ee-on-macos)。