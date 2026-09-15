---
title: "Mpp Agent — 通过机器支付协议（MPP）为 HTTP 402 API 付费"
sidebar_label: "Mpp Agent"
description: "通过机器支付协议（MPP）为 HTTP 402 API 付费"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Mpp Agent

通过机器支付协议（MPP）为 HTTP 402 API 付费。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/payments/mpp-agent` 安装 |
| 路径 | `optional-skills/payments/mpp-agent` |
| 版本 | `0.1.0` |
| 作者 | Teknium (teknium1), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos |
| 标签 | `Payments`, `MPP`, `HTTP-402`, `Tempo`, `Stripe` |
| 相关 skills | [`stripe-link-cli`](/user-guide/skills/optional/payments/payments-stripe-link-cli), [`stripe-projects`](/user-guide/skills/optional/payments/payments-stripe-projects) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# MPP Agent Skill

封装机器支付协议（MPP，https://mpp.dev）客户端，使 Hermes 能够针对返回 `HTTP 402 Payment Required` 的服务器按请求付费访问 API。

共有三种客户端可选，均通过 npm 分发。请挑选能满足用户需求的最轻量的一个。由于更广泛的支付工具链在 Windows 上仍在完善中，此 skill 被限定为 `[linux, macos]`。

## 使用场景

- 商户 API 返回带 `www-authenticate` 头的 `HTTP 402` —— 而用户希望真正支付它，而不只是记录响应。
- 用户要求"按请求付费"、"设置一个 agent 钱包"、"使用 Tempo / Privy / AgentCash"，或者想要发现按 MPP 定价的服务。
- 一笔 Stripe Link 支出已产生共享支付令牌（SPT），agent 需要将其附加到 402 挑战上 —— 在该流程中，请优先使用 `link-cli mpp pay`（参见 `stripe-link-cli` skill）。

## 选择客户端

| 工具 | 适用场景 | 设置方式 |
|---|---|---|
| `link-cli` | 用户已配置好 Stripe Link，或 402 挑战声明了 `method="stripe"` | 参见 `stripe-link-cli` skill |
| Tempo Wallet | 需要支出控制、服务发现的 MPP 服务 | `tempo wallet login` |
| Privy Agent CLI | 多链钱包、基于浏览器的充值 | `privy-agent-wallets login` |
| AgentCash | 通过单一 USDC.e 余额访问 300+ 已定价 API | `npx agentcash onboard` |
| `mppx` | 开发与调试，依赖面最小 | `npm install -g mppx`，然后 `mppx account create` |

默认策略：如果用户已配置 Stripe Link，或 402 挑战指定了 `method="stripe"`，使用 `link-cli mpp pay`（即 `stripe-link-cli` skill）。否则，一次性付费调用与调试用 `mppx`，当用户需要持久的支出控制时用 Tempo Wallet。

## 前置条件

- `PATH` 上有 Node.js 20+
- 一个已充值的钱包（Tempo / Privy / AgentCash）或一个 `mppx` 账户
- 对于 Tempo / Privy / AgentCash：遵循它们各自的上手 skill：
  - `https://tempo.xyz/SKILL.md`
  - `https://agents.privy.io/skill.md`
  - `https://agentcash.dev/skill.md`

如果用户选择了其中之一，使用 `web_extract` 获取对应的 SKILL.md 文件。

## 操作步骤（mppx，最快路径）

所有命令都通过 `terminal` 工具运行。

### 1. 安装并创建账户

```
npm install -g mppx
mppx account create
```

按照 CLI 的提示保存生成的账户凭证（CLI 会将其写入自己的配置目录 —— 不要把它们粘贴到 agent 对话记录中）。

### 2. 检查商户的 402 挑战

如果用户给出了一个 URL，先探测它，确认它确实支持 MPP：

```
curl -i <url>
```

一个真正的 MPP 402 响应形如：

```
HTTP/1.1 402 Payment Required
www-authenticate: tempo amount=0.1 currency=...
```

### 3. 为请求付费

```
mppx <url>
```

对于非 GET 方法或带请求体的请求：

```
mppx <url> --method POST --data '<json>'
```

`mppx` 会自动处理 402 挑战/凭证交互流程，并在成功时打印商户的实际响应。

### 4. 验证收据

`mppx` 会自动附加收据头。检查方式：

```
mppx <url> -v
```

## 操作步骤（Tempo Wallet）

https://tempo.xyz/SKILL.md 上的 Tempo Wallet skill 是权威参考；用 `web_extract` 获取并遵循它。要点：

```
tempo wallet login
tempo wallet pay <url>
```

支出控制与服务发现位于 https://wallet.tempo.xyz 的钱包 UI 中。

## 常见陷阱

- **没有 `method="stripe"` 的 `HTTP 402` 无法用 Stripe Link 支付。** 如果挑战只声明了 Tempo 或其他方法，请使用 `mppx`（或与之匹配的钱包）—— Link 会拒绝它。反之，如果它声明了 `method="stripe"`，请优先通过 `stripe-link-cli` skill 使用 Link，这样支出会走用户已批准的卡片。
- **一个头里包含多个挑战。** `www-authenticate` 可能列出多种方法（例如 `tempo, stripe`）。Link CLI 的 `mpp decode` 会选择 Stripe 的那个；`mppx` 会选择 Tempo。没有唯一"正确"的客户端 —— 按用户已充值的钱包来选。
- **零金额挑战。** 有些 MPP 端点收费 `$0.00`，只是想要一份证明凭证。这类请求无需已充值的钱包即可完成。不要把它们当作"坏掉的"而拒绝。
- **钱包密钥绝不进入 agent 上下文。** 这四个客户端都把密钥存放在各自的配置目录下（在 Privy 的情况下，是生成每次会话的临时密钥对）。不要对它们执行 `cat`/`read_file`。
- **服务端 MPP 是另一个 skill。** 如果用户想给自己的 API 添加 402，此 skill 就用错了 —— 请把他们指向 https://mpp.dev/quickstart/server 以及 `mppx/nextjs` / `mppx/hono` / `mppx/express` / `mppx/elysia` 中间件。未来可能会有专门的 `mpp-server` skill。

## 验证

```
mppx --version && mppx account list
```

退出码为 0 表示已安装且账户存在。
