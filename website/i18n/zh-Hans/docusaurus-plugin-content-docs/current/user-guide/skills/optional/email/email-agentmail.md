---
title: "Agentmail — 当 Agent 需要 AgentMail CLI 电子邮件收件箱时使用"
sidebar_label: "Agentmail"
description: "当 Agent 需要 AgentMail CLI 电子邮件收件箱时使用"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Agentmail

当 Agent 需要 AgentMail CLI 电子邮件收件箱时使用。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/email/agentmail` 安装 |
| 路径 | `optional-skills/email/agentmail` |
| 版本 | `1.0.0` |
| 作者 | Haakam Aujla (Haakam21), AgentMail |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Email`, `CLI`, `AgentMail`, `Communication` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 Agent 所看到的指令内容。
:::

# AgentMail Skill

AgentMail 为 Agent 提供专属的电子邮件收件箱，用于发送邮件、接收回复、完成电子邮件 OTP 流程以及运行入站邮件循环。请将其用于 Agent 自有的收件箱，而不是用户现有的 IMAP/SMTP 邮箱。

优先使用 `agentmail` CLI。仅当运行环境（harness）需要 MCP 工具时才使用 MCP；仅当 CLI 缺少所需操作时才使用 REST。

## 使用场景

- Agent 需要一个它自己拥有的电子邮件地址。
- 任务涉及电子邮件 OTP 流程、回复、线程、标签或附件。
- Agent 需要通过 webhook 或 WebSocket 接收入站邮件。

## 前置要求

- 通过 `terminal` 工具运行命令。
- 安装 CLI：

```bash
npm install -g agentmail-cli@latest
```

- 导出 API 密钥：

```bash
export AGENTMAIL_API_KEY="am_..."
```

还没有 API 密钥？请使用 [signup.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/signup.md)。

## 运行方式

当其他命令或脚本需要 ID 时，请始终使用 `--format json`。

```bash
agentmail inboxes list --format json
```

## 快速参考

- [AgentMail agent reference](https://agentmail.md)：托管副本。
- [AgentMail](https://agentmail.to)：产品首页。
- [Console](https://console.agentmail.to)：API 密钥与账户管理。
- [Docs](https://docs.agentmail.to)：完整产品文档。
- [signup.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/signup.md)：自助注册与 OTP 验证。
- [core.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/core.md)：收件箱、消息、线程、标签、附件。
- [webhooks.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/webhooks.md)：将事件推送到公网 HTTPS 服务器。
- [websockets.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/websockets.md)：将事件推送到本地 Agent 进程。
- [mcp.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/mcp.md)：MCP 集成。

## 操作流程

1. 安装 `agentmail-cli@latest` 并验证 `agentmail inboxes list --format json`。
2. 如果没有可用的 API 密钥，请完成 [signup.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/signup.md)。
3. 收件箱、发送、读取、回复、转发、标签、线程和附件相关流程请使用 [core.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/core.md)。
4. 仅当轮询不够用时，才添加 [webhooks.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/webhooks.md) 或
   [websockets.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/email/agentmail/references/websockets.md)。

## 注意事项

- 优先使用 `AGENTMAIL_API_KEY`，而不是 `--api-key`。
- 切勿在提示词、日志、URL 或已提交的文件中暴露 `AGENTMAIL_API_KEY`。
- 对于会重试的创建操作，使用稳定的 `client_id` 值。
- 如果存在 `extracted_text` 或 `extracted_html`，优先将其作为 LLM 输入。
- 对 `message.received` 做出响应，而不是对 Agent 自己发送的消息做出响应。

## 验证

```bash
agentmail inboxes list --format json
```
