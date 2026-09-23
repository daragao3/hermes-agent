---
sidebar_position: 8
title: "程序化集成"
description: "从外部程序驱动 hermes-agent 的三种协议：ACP、TUI gateway JSON-RPC 以及兼容 OpenAI 的 HTTP API"
---

# 程序化集成 {#programmatic-integration}

Hermes 提供三种协议，供外部程序驱动 agent——IDE 插件、自定义 UI、CI 流水线、嵌入式子 agent。根据你的传输方式和消费端选择合适的协议。

| 协议 | 传输方式 | 适用场景 | 定义位置 |
|----------|-----------|----------|------------|
| **ACP** | JSON-RPC over stdio | 已支持 [Agent Client Protocol](https://github.com/zed-industries/agent-client-protocol) 的 IDE 客户端（VS Code、Zed、JetBrains） | `acp_adapter/` |
| **TUI gateway** | JSON-RPC over stdio（或 WebSocket） | 需要精细控制会话、slash 命令、审批及流式事件的自定义宿主 | `tui_gateway/server.py` |
| **API server** | HTTP + Server-Sent Events | 兼容 OpenAI 的前端（Open WebUI、LobeChat、LibreChat……）及语言无关的 Web 客户端 | `gateway/platforms/api_server.py` |

三种协议均驱动同一个 `AIAgent` 核心，区别仅在于线路格式和所暴露的功能集。

---

## ACP（Agent Client Protocol） {#acp-agent-client-protocol}

`hermes acp` 启动一个基于 stdio 的 JSON-RPC 服务器，使用 ACP 协议。已在 VS Code（Zed Industries 的 ACP 扩展）、Zed 以及所有安装了 ACP 插件的 JetBrains IDE 中投入生产使用。

暴露的能力：会话创建、prompt（提示词）提交、流式 agent 消息块、工具调用事件、权限请求、会话 fork、取消及身份验证。工具输出会被渲染为 IDE 可理解的 ACP `Diff`/`ToolCall` 内容块。

完整生命周期、事件桥接及审批流程：[ACP 内部机制](./acp-internals)。

```bash
hermes acp                  # 在 stdio 上提供 ACP 服务
hermes acp --check          # 检查 ACP 依赖项及适配器导入
hermes acp --setup          # 为 ACP 终端认证交互式配置 provider/模型
```

---

## TUI Gateway JSON-RPC {#tui-gateway-json-rpc}

`tui_gateway/server.py` 是 Ink TUI（`hermes --tui`）和嵌入式仪表板 PTY 桥接所使用的协议。任何外部宿主均可通过 stdio（或经由 `tui_gateway/ws.py` 的 WebSocket）使用相同协议。

### 方法目录（精选） {#method-catalog-selected}

```
prompt.submit           prompt.background       session.steer
session.create          session.list            session.active_list
session.activate        session.close           session.interrupt
session.history         session.compress        session.branch
session.title           session.usage           session.status
clarify.respond         sudo.respond            secret.respond
approval.respond        config.set / config.get commands.catalog
command.resolve         command.dispatch        cli.exec
reload.mcp              reload.env              process.stop
delegation.status       subagent.interrupt      subagent.steer
spawn_tree.save / list / load
terminal.resize         clipboard.paste         image.attach
```

`session.active_list`、`session.activate` 和 `session.close` 是 TUI 会话切换器所使用的进程内实时会话控制方法。查找已保存的会话记录请使用 `session.list` / `/resume`；活跃会话相关方法仅适用于当前在 TUI gateway 进程中打开的会话。

在同一个已认证的 gateway 内，恢复或激活一个实时会话会附加一个新的事件订阅者，而不是替换之前的连接。流式事件和终端事件会发送给所有已附加的客户端；断开其中一个客户端不会结束另一个客户端正在查看的会话。现有的提交互斥规则和已配置的忙碌输入策略依然有效。已附加的客户端可以引导（steer）该会话的子 agent；但浏览器控制器的结果仍然要求由注册该控制器的那个连接接收。这并不允许相互独立的 gateway 进程写入同一个会话，也不意味着在所有者重启后仍能持久地接纳 prompt。

### 在 `prompt.submit` 上回退历史 {#rewinding-history-on-promptsubmit}

回退 / 编辑 / 重新生成，本质上是一次在运行新轮次之前丢弃部分已存储会话记录的 `prompt.submit`。由于该写入会破坏性地重写会话的持久化行，gateway 只有在客户端明确声明意图时才会执行：

| 参数 | 含义 |
|-----------|---------|
| `truncate_before_user_ordinal` | 要截断处的用户轮次的零基索引。从该轮次起的所有内容都会被丢弃。仅用于显示的时间线行（`display_kind`）不计入。必须是真正的整数——JSON 布尔值会被拒绝，返回代码 `4004`。 |
| `truncate_before_row_id` | 目标用户轮次的整数 SQLite 行 ID（`messages.id` / `row_id`），在此处截断。首选的持久化寻址方式。同时提供序号和行 ID 时，gateway 会校验二者是否一致（不一致时返回 `4030`）。未知或过期的行 ID 会被拒绝并返回 `4018`——它**不会**回退到使用序号。 |
| `confirm_truncate` | 只要发送了序号、消息 ID 或行 ID 就必须提供。声明此次提交确实是一次回退，而不是恰好携带了残留参数的普通发送。没有目标却发送该参数会被拒绝，返回代码 `4004`。 |
| `confirm_empty_truncate` | 当截断会使会话记录变为空（序号 `0`）时额外需要。 |

携带截断参数但没有 `confirm_truncate` 的请求会被拒绝，返回代码 `4004` 或 `4029`，且不会写入任何内容。实现回退功能的宿主必须在用户发起回退的那一刻设置该标志，并且绝不能在普通提交之间将截断参数保留在状态中。优先使用 `truncate_before_row_id`（来自恢复时的 `row_id` / `_row_id`）而不是序号；仅在尚无可用持久化 ID 时，才将序号作为向后兼容 / 乐观行路径保留。

对持久化会话成功执行截断提交后，`prompt.submit` 的结果还会额外携带 `survivor_user_row_ids`——保留下来的用户轮次在重写后的新行 ID，按可见用户序号排列。重写会把保留的前缀作为新行重新插入，因此宿主在回退之前缓存的每个行 ID 之后都会失效；请根据此列表重新绑定缓存的 ID（`null` 条目表示该轮次没有持久化 ID——丢弃缓存的那个），否则下一次针对更早的保留轮次的回退会被拒绝并返回 `4018`。

### 流式返回的事件 {#events-streamed-back}

`message.delta`、`message.complete`、`tool.start`、`tool.progress`、`tool.complete`、`approval.request`、`clarify.request`、`sudo.request`、`sudo.expire`、`secret.request`、`secret.expire`、`gateway.ready`，以及会话生命周期和错误事件。过期（expire）事件会携带原始的 `{ request_id }`；外部宿主应仅清除与之匹配的待处理提示。

### Pi 风格 RPC 映射 {#pi-style-rpc-mapping}

Pi-mono RPC 规范（[issue #360](https://github.com/NousResearch/hermes-agent/issues/360)）中的每条命令均有对应的 TUI gateway 等价项：

| Pi 命令 | Hermes 等价项 |
|------------|-------------------|
| `prompt` | `prompt.submit`（或 ACP `session/prompt`） |
| `steer` | `session.steer` |
| `follow_up` | 在当前轮次结束后排队的 `prompt.submit` |
| `abort` | `session.interrupt` |
| `set_model` | 通过 `command.dispatch` 执行 `/model <provider:model>`（会话中途生效，持久化） |
| `compact` | `session.compress` |
| `get_state` | `session.status` |
| `get_messages` | `session.history` |
| `switch_session` | `session.resume` |
| `fork` | `session.branch` |
| `ui_request` / `ui_response` | `clarify.respond` / `sudo.respond` / `secret.respond` / `approval.respond` |

---

## 兼容 OpenAI 的 API Server {#openai-compatible-api-server}

`gateway/platforms/api_server.py` 通过 HTTP 暴露 Hermes，供任何已支持 OpenAI 格式的客户端使用。适用于需要 Web 前端、curl 驱动的 CI 运行器或非 Python 消费端的场景。

端点：

```
POST /v1/chat/completions        OpenAI Chat Completions（通过 SSE 流式传输）
POST /v1/responses               OpenAI Responses API（有状态）
POST /v1/runs                    启动一次运行，返回 run_id（202）
GET  /v1/runs/{id}               运行状态
GET  /v1/runs/{id}/events        生命周期事件的 SSE 流
POST /v1/runs/{id}/approval      解决待处理的审批
POST /v1/runs/{id}/steer         在下一个工具边界注入运行中途的引导
POST /v1/runs/{id}/stop          中断运行
GET  /v1/capabilities            机器可读的功能标志
POST /v1/browser-control/register 注册浏览器控制器
GET  /v1/browser-control/ws       浏览器控制器 WebSocket
GET  /v1/models                  列出 hermes-agent
GET  /api/model/options          感知 provider 的选择器清单
GET  /health, /health/detailed
```

配置、请求头（`X-Hermes-Session-Id`、`X-Hermes-Session-Key`）及前端接入：[API Server](../user-guide/features/api-server)。

浏览器扩展可以选择启用默认关闭的控制器协议，以驱动发起该 Hermes 对话的那个确切浏览器会话。API 与仪表板两种传输方式共享同一个绑定到主体（principal）的代理（broker），以及同一份显式的能力白名单；参见[浏览器扩展控制](../user-guide/features/api-server#browser-extension-control)。

### 模型目录接口 {#model-catalog-surfaces}

兼容 OpenAI 的 API 有意让 `GET /v1/models` 保持精简：它是前端所期望的兼容性端点，而不是完整的 Hermes provider/模型选择器目录。

如果外部控制平面需要 Hermes 精选的 provider 行、每个模型的定价或能力提示，请使用以下任一需要认证的选择器接口：

- API server REST：`GET /api/model/options`，使用 API server 的 bearer 密钥
- 仪表板后端 REST：`GET /api/model/options`，使用 `X-Hermes-Session-Token`
- TUI gateway RPC：`model.options`

这些接口共享同一个负载构建器和同一套自定义 provider 探测策略：

- 正常打开：只探测当前的自定义 provider，避免离线的已保存端点拖慢选择器。
- 显式刷新（`refresh=1` 或 `refresh: true`）：清除 provider-模型缓存并探测所有已保存的自定义 provider，使实时目录完整地重新填充。

需要兼容 OpenAI 客户端时使用 `/v1/models`。构建感知 Hermes 的模型选择器时使用 `/api/model/options` 或 `model.options`。

`POST /v1/runs/{id}/steer` 是 Hermes `/steer` 的 HTTP 等价物：它不会创建新的用户轮次，也不会立即重写正在生成中的助手输出。相反，这段文本会被追加到正在进行的运行中，并在下一个工具边界之后对 agent 可见，从而让 agent 在不丢弃当前工具调用循环的情况下修正方向。

`/v1/runs/{id}/steer` 仅在运行状态为 `running` 时被接受。排队中、因审批暂停、正在停止、已取消、已失败和已完成的运行都会返回 `409 run_not_accepting_steer`，即使服务器在协作式关闭期间仍保留着内部 agent 引用。

`200`（以及 `run.steered` 事件）表示文本已被**排队**，而不是 agent 已经消费了它。如果一条 steer 在 agent 给出最终回复之后才到达——此后再没有可以投递它的工具边界——未投递的文本会作为 `pending_steer` 出现在终止的 `run.completed` 事件和运行状态中，以便客户端将其作为下一个用户轮次重放，而不会丢失。

---

## 该选哪个？ {#which-one-should-i-use}

- **正在编写 IDE 插件，且 IDE 已支持 ACP** → 选 ACP。IDE 侧无需任何协议工作。
- **正在编写自定义桌面 / Web / TUI 宿主，且需要 Hermes 的全部功能**（slash 命令、审批、clarify、多 agent、会话分支）→ 选 TUI gateway JSON-RPC。
- **需要任意兼容 OpenAI 的前端、语言无关的 HTTP 客户端或 curl 驱动的自动化** → 选 API server。
- **需要在 Python 进程内嵌入，不想启动子进程** → 直接导入 `run_agent.AIAgent`。参见 [Agent Loop](./agent-loop)。

---

## 模型热切换 {#model-hot-swapping}

会话中途切换模型在所有接入方式上均可用——底层均为 `/model` slash 命令。

- **CLI / TUI：** `/model claude-sonnet-4` 或 `/model openrouter:anthropic/claude-sonnet-4.6`
- **TUI gateway RPC：** 使用 `{"command": "/model claude-sonnet-4"}` 调用 `command.dispatch`
- **ACP：** IDE 将 slash 命令作为 prompt 发送，agent 负责分发
- **API server：** 在请求体中包含 `model` 字段

内置 provider 感知解析（相同的模型名称会根据当前 provider 自动选择正确格式）。参见 `hermes_cli/model_switch.py`。

---

## 关于 `--mode rpc` 的说明 {#a-note-on---mode-rpc}

Hermes 没有 `--mode rpc` 标志。上述三种协议已覆盖所有使用场景——ACP 用于 IDE 协议客户端，TUI gateway 用于 stdio JSON-RPC 宿主，API server 用于 HTTP。如果你发现上述协议均无法满足的真实需求，请提交 issue 并说明你正在构建的具体消费端。
