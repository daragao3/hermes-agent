---
title: "Stripe Projects — 通过 Stripe Projects 开通 SaaS 服务并同步凭据"
sidebar_label: "Stripe Projects"
description: "通过 Stripe Projects 开通 SaaS 服务并同步凭据"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Stripe Projects

通过 Stripe Projects 开通 SaaS 服务并同步凭据。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/payments/stripe-projects` 安装 |
| 路径 | `optional-skills/payments/stripe-projects` |
| 版本 | `0.1.0` |
| 作者 | Teknium (teknium1), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos |
| 标签 | `Payments`, `Stripe`, `Projects`, `Provisioning`, `Infrastructure` |
| 相关 skills | [`stripe-link-cli`](/user-guide/skills/optional/payments/payments-stripe-link-cli), [`mpp-agent`](/user-guide/skills/optional/payments/payments-mpp-agent) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Stripe Projects Skill

封装 [Stripe Projects](https://projects.dev) CLI 插件，使 Hermes 能够开通 SaaS 服务（Neon、Twilio、Vercel 等）、生成凭据并同步到用户的 `.env` 中，并在一个地方管理跨服务商的计费。

在更广泛的支付类 skill 集群于 Windows 上成熟之前，本 skill 被限定为 `[linux, macos]`。Stripe CLI 本身是跨平台的；这一限制是该集群的整体策略，而非硬性限制。

## 使用时机

触发短语：

- "set up &lt;provider>"、"provision &lt;Neon|Twilio|Vercel|...>"、"create a database"
- "give me a &lt;Postgres|Redis|Twilio number|...> for this project"
- "manage my stack credentials"、"rotate this key"、"upgrade my plan"
- "what providers can I add?"

如果用户已经拥有某个服务商的账户，本 skill 仍可用 `stripe projects link <provider>` 将其连接进来。如果用户想使用已有的服务商资源，例如已有的数据库或 Vercel 项目，请先确认服务商是否支持；目前许多服务商支持开通新资源，但不支持导入已有资源。

## 前置要求

- 已安装 Stripe CLI（macOS 上用 Homebrew，Linux 上用包管理器，或从 https://docs.stripe.com/stripe-cli/install 下载）
- 已安装 Stripe Projects 插件
- 一个 Stripe 账户。如果用户还没有，CLI 可以在设置过程中引导他们在浏览器中登录或创建账户。

## 安装

macOS：

```
brew install stripe/stripe-cli/stripe
stripe plugin install projects
```

Linux：按照 https://docs.stripe.com/stripe-cli/install 上针对具体平台的安装说明操作，然后执行：

```
stripe plugin install projects
```

## 如何运行

所有命令都通过 `terminal` 工具在用户的项目目录中执行（CLI 会把 `.env` 和 `.projects/vault/vault.json` 写入当前工作目录）。

## 操作步骤

### 1. 初始化项目

```
cd <project-root>
stripe projects init
```

这会创建 `.projects/vault/vault.json`（加密的凭据存储），并让项目做好接入服务商的准备。

### 2. 查看可用的服务商

```
stripe projects catalog
```

列出 Stripe Projects 支持的每一个服务商 —— 数据库、托管、认证、AI、分析、消息等等。

### 3. 添加服务

```
stripe projects add <provider>/<service>
```

示例：

- `stripe projects add neon/postgres`
- `stripe projects add twilio/sms`
- `stripe projects add runloop/sandbox`

CLI 会在用户自己的服务商账户中开通该服务、生成凭据、把凭据同步进 `.env`，并把资源记录到 vault 中。用户可能需要确认套餐选择或价格提示。

### 4. 验证

```
stripe projects list
```

应当能看到新添加的服务商及其 `.env` 键。

### 5. 管理 / 升级 / 移除

```
stripe projects upgrade <provider>     # tier change
stripe projects remove <provider>      # deprovision
stripe projects rotate <provider>      # rotate credentials
```

## 陷阱

- **对 `.env` 的写入是真实写入。** CLI 会追加到项目根目录下的任何 `.env` 文件。如果用户的 `.env` 已被 gitignore（通常如此），密钥会安全落地；否则本 skill 可能成为凭据泄露的途径。请务必先检查 `.gitignore`。
- **状态是按项目隔离的。** `.projects/vault/vault.json` 是按项目存放的。在两个不同项目中开通同一个服务会创建两份独立资源 —— 也就是两份账单。
- **计费发生在 Stripe 一侧。** `add`/`upgrade` 过程中的套餐提示对应真实扣费；在确认之前请向用户明确说明。
- **服务商可用性会变化。** 目录会不断扩充；如果用户提到的服务商不在列表里，请先执行 `stripe projects catalog | grep <name>`，而不是让 `add` 调用直接失败。
- **vault 中的凭据是加密的，但 `.env` 是明文。** 适用标准的 `.env` 卫生规范 —— 绝不要提交它。
- **移除服务并不总是会销毁底层资源。** 某些服务商会留下暂停/休眠状态的资源。对高成本服务（尤其是托管数据库），请在 `remove` 之后到服务商自己的控制台确认。

## 验证

```
stripe projects --version && stripe projects list
```

在已初始化的项目中退出码为 0，说明插件运行正常。
