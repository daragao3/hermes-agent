---
title: "Stripe Link Cli — 通过 Stripe Link 实现 agent 支付 —— 卡片、SPT、审批"
sidebar_label: "Stripe Link Cli"
description: "通过 Stripe Link 实现 agent 支付 —— 卡片、SPT、审批"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Stripe Link Cli

通过 Stripe Link 实现 agent 支付 —— 卡片、SPT、审批。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/payments/stripe-link-cli` 安装 |
| 路径 | `optional-skills/payments/stripe-link-cli` |
| 版本 | `0.1.0` |
| 作者 | Teknium (teknium1), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos |
| 标签 | `Payments`, `Stripe`, `Link`, `Checkout`, `MPP` |
| 相关 skills | [`mpp-agent`](/user-guide/skills/optional/payments/payments-mpp-agent), [`stripe-projects`](/user-guide/skills/optional/payments/payments-stripe-projects) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Stripe Link CLI Skill

封装 [@stripe/link-cli](https://github.com/stripe/link-cli)，使 Hermes 能够使用一次性虚拟卡或共享支付令牌（Shared Payment Token，SPT）代表用户完成购买。每一笔支出都必须经过 Link 移动端/网页端应用中的应用内审批 —— Hermes 无法自行批准。

目前仅限美国（Link 账户的要求）。上游 CLI 不支持 Windows —— 本 skill 被限定为 `[linux, macos]`。

## 使用时机

触发短语：

- "buy X"、"pay for X"、"make a purchase"、"complete checkout"
- "get me a card"、"I need a payment method"
- "log in to Link"、"connect my Link wallet"
- 商户 API 返回带 `www-authenticate: ... method="stripe"` 的 HTTP 402 响应

如果用户需要的是付费 API 调用（HTTP 402，没有结账表单），那么 `card` 路径是错误的 —— 请通过同一个 skill 使用 SPT，或移交给 `mpp-agent` skill。

## 前置要求

- `PATH` 上可用的 Node.js 20+（`node --version`）
- 位于美国（Link 账户的要求）

Link 账户、支付方式和支出审批应用**不需要**在 Hermes 尝试付款之前就设置好 —— CLI 会在首次运行时引导用户完成：

- 一个 https://app.link.com 上的 Link 账户 —— 在首次 `link-cli` 认证时创建/关联
- 至少一种支付方式 —— 在首次运行时于 https://app.link.com/wallet 添加
- Link 移动端/网页端应用 —— 在首次发起支出请求时打开以批准

无需环境变量 —— 认证状态由 CLI 保存在其自身的配置目录下。

## 安装

全局安装一次：

```
npm install -g @stripe/link-cli
```

或通过 `npx @stripe/link-cli` 临时调用。下面的 skill 使用已安装的 `link-cli` 形式。

## 如何运行

所有命令都通过 `terminal` 工具运行。CLI 会自动检测非 TTY 调用方，并默认输出紧凑的 `toon` 格式 —— 这对模型来说没问题。若某一步需要结构化字段，请传 `--format json`。

发现命令：`link-cli --llms-full`。
在调用前获取某个命令的 schema：`link-cli <command> --schema`。

## 操作步骤

### 1. 检查 / 建立认证

```
link-cli auth status
```

若尚未认证，请用清晰的客户端名称登录（该标签会显示在用户的 Link 应用中）：

```
link-cli auth login --client-name "Hermes" --interval 5 --timeout 300
```

`--interval`/`--timeout` 这种形式会内联轮询，因此 agent 不需要自己管理 `_next` 步骤。把验证 URL 和验证短语打印给用户，然后等待 CLI 返回。

**在 `auth status` 确认已登录之前，不要越过这一步。**

### 2. 在创建支出请求前评估商户

确定凭据类型：

| 商户界面 | `--credential-type` |
|---|---|
| 标准网页结账表单 / Stripe Elements | `card`（默认） |
| 返回 HTTP 402 且 `www-authenticate` 中带 `method="stripe"` | `shared_payment_token` |
| 返回 HTTP 402 但不带 `method="stripe"` | 不支持 —— 停止 |

对于 402 响应，**不要**手动解码挑战串。直接传入原始请求头：

```
link-cli mpp decode --challenge '<full WWW-Authenticate header>'
```

该命令会校验挑战串，并提取网络 ID 与解码后的请求体。

### 3. 列出支付方式和收货地址

```
link-cli payment-methods list
link-cli shipping-address list
```

除非用户另有指定，否则使用第一条。`payment-methods list` 返回的 `id` 就是下一步中的 `--payment-method-id`。

### 4. 创建支出请求

发出此命令前，先与用户确认最终总额。金额以分为单位。

```
link-cli spend-request create \
  --payment-method-id <pm_id> \
  --merchant-name "<name>" \
  --merchant-url "<url>" \
  --context "<one sentence: what is being purchased and why>" \
  --amount <cents> \
  --line-item "name:<item>,unit_amount:<cents>,quantity:1" \
  --total "type:total,display_text:Total,amount:<cents>" \
  --request-approval
```

对于 MPP 商户，请加上 `--credential-type shared_payment_token`。

`--request-approval` 会向用户的 Link 应用推送提醒，并轮询直到用户批准或拒绝。若被拒绝/超时，CLI 会以非零状态退出。

### 5. 取回凭据 —— 请安全操作

**不要把卡片明细打印到 stdout。** 使用 `--output-file`，让卡号永远不会进入 agent 的对话记录或日志：

```
link-cli spend-request retrieve <lsrq_id> \
  --include card \
  --output-file /tmp/link-card.json \
  --format json
```

该文件以 `0600` 权限写入；stdout 只显示脱敏字段（卡组织、后四位、有效期）以及一个 `card_output_file` 路径。

### 6. 使用凭据

- 对于网页结账：把文件路径交给用户，或者把它传给一个能直接从磁盘填写表单的浏览器驱动工具。绝不要把卡片文件 `read_file` 或 `cat` 进 agent 的推理上下文。
- 对于 MPP 商户：

  ```
  link-cli mpp pay <merchant-url> \
    --spend-request-id <lsrq_id> \
    --method POST \
    --data '<json body>'
  ```

### 7. 清理

购买一完成，立即删除卡片文件：

```
rm -f /tmp/link-card.json
```

## 可选：改为以 MCP 服务器方式运行

`@stripe/link-cli --mcp` 会通过 stdio 把相同的命令暴露为 MCP 工具。将其注册到 Hermes 原生 MCP：

```
hermes mcp add stripe-link --command "npx" --args "@stripe/link-cli --mcp"
```

随后 `hermes mcp list` 应能看到 `stripe-link`。同样的审批规则依然适用 —— MCP 不会绕过 Link 应用的审批环节。

## 陷阱

- **仅限美国。** 在美国境外，`auth login` 会失败。请告知用户，不要反复重试。
- **卡号绝不能进入 agent 上下文。** 每次都使用 `--output-file`。如果你已经在没有它的情况下取回过，仅仅执行 `link-cli auth logout` 是不够的 —— 卡片虽是一次性的，但轮换卫生仍然重要。
- **`--request-approval` 会阻塞直到用户操作。** 如果用户在睡觉，CLI 会一直等到超时。请提前告知预期。
- **多步的 `_next` 命令。** 有些命令会返回必须继续执行的 `_next.command`。拿不准时，优先使用内联轮询参数（`--interval`/`--timeout`）。
- **非 TTY 模式下输出格式默认为 `toon`。** 用于叙述没问题，但如果下游步骤需要解析某个特定字段，请传 `--format json`。
- **不要默认选 `card`。** 商户评估步骤（第 2 节）之所以存在，是因为选错凭据类型会让购买静默失败，或泄露超出必要范围的数据。

## 验证

```
link-cli --version && link-cli auth status
```

退出码为 0 表示已安装且已登录。
