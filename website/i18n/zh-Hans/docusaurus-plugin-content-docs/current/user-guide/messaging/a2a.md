---
title: A2A（Agent 间通信）
description: "借助 Hermes A2A 插件，把其他 A2A agent 当作工具调用，并通过 HTTP 接收 A2A 任务"
---

# A2A（Agent 间通信） {#a2a-agent-to-agent}

[A2A](https://a2a-protocol.org) 是开放的 Agent2Agent 协议（v1.0，由 Linux 基金会管理），用于独立 AI agent 之间的通信。Hermes A2A 插件支持**双向**工作：你的 agent 可以把其他 A2A agent 当作工具调用，其他 agent 也可以通过 HTTP 向你的 Hermes 发送任务。

它可以与任何符合 A2A 规范的对端互通 —— 另一个 Hermes、LangChain、CrewAI、Google ADK agent，或任何基于官方 `a2a-sdk` 构建的程序。

## 何时使用 A2A {#when-to-use-a2a}

- **跨机器的 Hermes ↔ Hermes** —— 让桌面上的 agent 把任务交给服务器上的 Hermes，反之亦然，双方各自拥有自己的记忆、工具和凭据。
- **委派给专长 agent** —— 在其 Agent Card 上声明了 `web_search`/`research`/`coding` 技能的对端，可以在对话过程中被发现并调用。
- **作为可调用的服务** —— 把你的 Hermes 暴露出去，让其他框架的 agent 可以向它发送任务。

如果你想在**同一台机器**上运行多个 agent，请优先使用 [委派](../features/delegation.md)（进程内子 agent）或 [看板](../features/kanban.md)（持久化的多 profile 工作队列）—— A2A 用于跨越进程/机器/框架的边界。

## 启用 {#enable}

```bash
hermes gateway setup      # pick A2A
```

或者在 `~/.hermes/config.yaml` 中：

```yaml
gateway:
  platforms:
    a2a:
      enabled: true
      extra:
        port: 9900
```

出站客户端工具以 `a2a` 工具集的形式提供，**默认关闭** —— 需要按平台启用：

```bash
hermes tools enable a2a --platform cli        # CLI/TUI sessions
hermes tools enable a2a --platform telegram   # or any messaging platform
hermes tools enable a2a --platform a2a        # let inbound A2A tasks call peers (agent chaining)
```

这些工具在所有进程类型中都可用 —— CLI、TUI、gateway 和 cron —— 无需启用入站平台。

## 出站：调用其他 agent {#outbound-calling-other-agents}

启用 `a2a` 工具集后，agent 会获得：

| 工具 | 作用 |
|---|---|
| `a2a_discover(url)` | 获取并概述对端的 Agent Card |
| `a2a_call(agent, message, context_id?)` | 发送任务并获取回复；通过 `context_id` 进行多轮对话 |
| `a2a_list()` | 已配置的对端、已保存的对话、指标 |
| `a2a_history(context_id)` | 调出一段已持久化的 A2A 对话 |
| `a2a_orchestrate(capability, message, mode?)` | 把任务分发给所有声明了某项能力的对端（`all` / `first` / `best`） |

在 `config.yaml` 中配置已知对端：

```yaml
a2a_agents:
  researcher:
    url: "http://research-box.local:9900"
    auth: { type: bearer, token: "..." }
    timeout: 120
    capabilities: [web_search, research]
```

然后直接提问即可：*"让 researcher agent 总结一下今天的 arXiv 投稿。"* 直接使用 URL 也可以 —— `a2a_call` 接受任何 A2A 端点。

## 入站：成为可调用的服务 {#inbound-being-callable}

启用该平台后，Hermes 会提供：

- **Agent Card**，位于 `GET /.well-known/agent-card.json`（v1.0 规范路径；旧的 `agent.json` 也会响应）—— 声明你的 agent 的名称、技能（由已启用的工具集推导）以及认证要求。
- **JSON-RPC 2.0**，位于 `POST /` —— v1.0 规范方法（`SendMessage`、`SendStreamingMessage`、`GetTask`、`ListTasks`、`CancelTask`、`SubscribeToTask`、推送通知配置的 CRUD），以及 1.0 之前的路径风格别名（`message/send`、……）。
- **SSE 流式传输**，用于 `SendStreamingMessage`，帧采用符合规范的 JSON-RPC 信封格式。
- **推送通知**（webhook），用于长时间运行的任务，使用 HMAC-SHA256 签名。

入站任务会被注入到一个**实时的 gateway 会话**中 —— 与服务你其他渠道的是同一个 agent、同一套记忆和工具 —— 最终回复会作为任务结果返回给调用方。对话以 A2A 的 `contextId` 为键，因此对端可以进行多轮交流。

互操作性已针对官方 Python `a2a-sdk` 验证过（card 解析、`SendMessage`、流式传输）。

## 安全模型 {#security-model}

默认安全；每一步放宽都需要显式操作：

- **没有 token ⇒ 仅限 localhost。** 服务器绑定 `127.0.0.1`。要对远程暴露，需要 bearer token **并且**显式设置 `A2A_HOST`。
- **按对端分配 token** —— `A2A_PEER_TOKENS="alice:tok1,bob:tok2"` 为每个对端分配各自的凭据；认证后的名称用于限流、信任判断和审计。
- **提示词注入过滤** —— 入站文本会经过过滤，并被标记为不可信的对端输入。远程对端无法调用运维者的斜杠命令。
- **出站脱敏** —— 形似凭据的字符串（API 密钥、JWT、token）会从回复中清除。
- **审计日志** —— 每次交互都会追加到 `~/.hermes/a2a_audit.jsonl`。
- **防循环** —— 按上下文设置的轮次上限，防止两个 agent 无休止地来回对话。

## 配置参考 {#configuration-reference}

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `A2A_PEER_TOKENS` | _（未设置）_ | 按对端的凭据 `name:token,…`（推荐） |
| `A2A_BEARER_TOKEN` | _（未设置）_ | 共享 token；身份退化为调用方 IP |
| `A2A_HOST` | `127.0.0.1` | 绑定主机 —— 只有在设置了 token 时才会放宽 |
| `A2A_PORT` | `9900` | 入站端口 |
| `A2A_AGENT_NAME` | 由主机名派生 | Agent Card 上的名称 |
| `A2A_PUBLIC_URL` | _（未设置）_ | 在 card 上声明的可路由 URL（反向代理 / k8s） |
| `A2A_TRUSTED_PEERS` | _（未设置）_ | 已认证身份的允许列表 |
| `A2A_ALLOW_ALL_USERS` | `false` | 允许任何已认证的对端（仅限开发环境） |
| `A2A_RATE_LIMIT` | `60` | 每个身份每分钟的请求数 |
| `A2A_MAX_PINGPONG_TURNS` | `5` | 每个上下文的防循环轮次上限（最大 20） |
| `A2A_REPLY_TIMEOUT` | `300` | 等待 agent 回复的秒数 |
| `A2A_PUSH_SECRET` | bearer token | 推送通知签名所用的 HMAC 密钥 |
| `A2A_ADVERTISED_TOOLSETS` | 所有已注册的 | 限制哪些技能出现在 Agent Card 上 |

在反向代理或 Kubernetes Service 之后，请设置 `A2A_PUBLIC_URL`（或依赖 `X-Forwarded-Host`/`X-Forwarded-Proto`），使 Agent Card 声明一个对端真正能够回调的 URL。

## 快速测试 {#quick-test}

```bash
# From another machine / agent:
curl http://your-host:9900/.well-known/agent-card.json

curl -X POST http://your-host:9900/ \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage",
       "params":{"message":{"messageId":"m1","role":"ROLE_USER",
                 "parts":[{"text":"What tools do you have?"}]}}}'
```

## 故障排查 {#troubleshooting}

- **对端无法访问 card URL** —— card 声明的是你的绑定地址；请把 `A2A_PUBLIC_URL` 设置为外部可路由的 URL。
- **`401 Unauthorized`** —— token 不匹配；检查服务器上的 `A2A_PEER_TOKENS`/`A2A_BEARER_TOKEN` 以及对端的 `auth:` 配置块。
- **服务器无法绑定非 localhost 地址** —— 这是设计使然：先设置 bearer token，再设置 `A2A_HOST=0.0.0.0`。
- **长任务的回复超时** —— 调大 `A2A_REPLY_TIMEOUT`，或者让调用方注册推送通知配置并轮询 `GetTask`。
