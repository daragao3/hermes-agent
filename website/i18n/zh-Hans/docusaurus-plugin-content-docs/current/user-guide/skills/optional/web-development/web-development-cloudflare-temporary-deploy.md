---
title: "Cloudflare Temporary Deploy — Deploy a Worker live, no account, via wrangler --temporary"
sidebar_label: "Cloudflare Temporary Deploy"
description: "无需账号，通过 wrangler --temporary 实时部署 Worker"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Cloudflare Temporary Deploy

无需账号，通过 wrangler --temporary 实时部署 Worker。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/web-development/cloudflare-temporary-deploy` 安装 |
| 路径 | `optional-skills/web-development/cloudflare-temporary-deploy` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `cloudflare`, `workers`, `wrangler`, `deploy`, `temporary`, `agent`, `serverless`, `web-development` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Cloudflare Temporary Deploy Skill

使用 `wrangler deploy --temporary`，无需任何账号配置即可把 Cloudflare Worker 部署到一个可访问的 `workers.dev` URL。Cloudflare 会创建一个临时账号、完成部署，并打印一个有效期 60 分钟的认领（claim）URL；未被认领的账号会自动删除。这让 agent 获得一个紧凑的 写 → 部署 → 验证 循环，全程无需 OAuth、注册或复制粘贴 token。

此 skill **不**涵盖生产环境部署（那种情况请使用 `wrangler login` + 永久账号），也不涵盖下文临时账号限制之外的其他非 Worker 类 Cloudflare 产品。

## 使用时机

当用户想要做以下事情时加载此 skill：

- **把 agent 写的代码发布到一个可访问的 URL**，且不必先创建 Cloudflare 账号——"部署一下，给我个链接"
- **在后台/自主会话中迭代**，此时浏览器 OAuth 步骤会成为硬性阻塞
- 用一个可认领的临时目标**快速原型验证或评估 Workers**
- **构建自我验证的部署循环**——部署、`curl` 线上 URL、确认输出与代码一致、再次部署

## 不适用场景

- **生产或 CI/CD** → 请使用永久账号（`wrangler login` 或 `CLOUDFLARE_API_TOKEN`）。只要存在任何凭据，`--temporary` 就会报错。
- **Wrangler 已完成认证** → `--temporary` 会按设计返回错误。只有当用户明确希望做一次性临时部署时，才先运行 `wrangler logout`。
- **长期托管** → 临时部署若未被认领，会在 60 分钟后删除。

## 前置条件

- **Wrangler 4.102.0 或更高版本。** 这是引入 `--temporary` 的版本，更早的版本没有该选项。用 `npx wrangler@latest --version` 确认。
- **Node 18+ / npm**（或 `npx`、`yarn`、`pnpm`）。无需全局安装——`npx wrangler@latest` 即可。
- **不能存在 Cloudflare 凭据。** `--temporary` 仅在 Wrangler 未认证时可用：没有 OAuth 登录，没有 `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_API_KEY` 环境变量，也没有 `~/.wrangler` / `~/.config/.wrangler` 中缓存的 OAuth。请直接使用 `terminal` 工具的现有环境；不要去设置这些变量。
- 能够访问 `cloudflare.com` 和 `workers.dev` 的网络出口。
- 使用 `--temporary` 即表示接受 Cloudflare 的服务条款与隐私政策。

## 如何运行

每一步都使用 `terminal` 工具。务必固定版本（`wrangler@latest` 或 `wrangler@4.102.0` 及更高），以免误用某个缺少该选项的旧版全局 wrangler。

1. **搭建一个最小 Worker**（如果项目已存在则跳过）。一个 Worker 需要 `wrangler.toml`（或 `wrangler.jsonc`）以及一个入口脚本。最小 TypeScript 示例——用 `write_file` 写入以下文件：

   `wrangler.jsonc`：
   ```jsonc
   {
     "name": "hello-agent",
     "main": "src/index.ts",
     "compatibility_date": "2025-01-01"
   }
   ```

   `src/index.ts`：
   ```typescript
   export default {
     async fetch(): Promise<Response> {
       return new Response("hello cloudflare");
     },
   };
   ```

2. 在项目目录中**使用 `--temporary` 部署**：
   ```
   npx wrangler@latest deploy --temporary
   ```
   工作量证明（proof-of-work）检查会带来一小段自动延迟。成功后 Wrangler 会打印一行 `Account: <name> (created)`（或 `(reused)`）、一个 `Claim URL`，以及可访问的 `https://<worker>.<account>.workers.dev` URL。

3. 从该输出中**解析这些 URL**。不要靠肉眼辨认，运行辅助脚本可靠地提取：
   ```
   npx wrangler@latest deploy --temporary 2>&1 | python3 scripts/parse_deploy_output.py
   ```
   （请把 `scripts/parse_deploy_output.py` 解析为此 skill 的绝对路径。）它会打印 JSON：`{"live_url", "claim_url", "account", "account_state", "expires_minutes", "deployed"}`。

4. **验证部署确实已经生效**——不要只相信部署日志。`curl` 线上 URL，确认响应体与代码返回的内容一致：
   ```
   curl -sS <live_url>
   ```

5. **迭代。** 修改代码，用同样的 `npx wrangler@latest deploy --temporary` 重新部署。在 60 分钟窗口内，Wrangler 会复用缓存的临时账号（`Account: <name> (reused)`），因此 URL 保持不变。再次 `curl` 确认改动已生效。

6. **把认领 URL 交给用户。** 告诉他们：在 60 分钟内打开它才能保住该部署及其资源；如果不认领，一切都会自动删除。请把认领 URL 当作机密对待——它等同于该账号的所有权。

## 快速参考

| 步骤 | 命令 |
|---|---|
| 检查版本（需 4.102.0+） | `npx wrangler@latest --version` |
| 部署（无需账号） | `npx wrangler@latest deploy --temporary` |
| 部署并解析 URL | `npx wrangler@latest deploy --temporary 2>&1 \| python3 scripts/parse_deploy_output.py` |
| 验证线上可访问 | `curl -sS <live_url>` |
| 清除缓存的临时账号 | `npx wrangler@latest logout` |

### 临时账号的产品限制

| 产品 | 临时账号上的限制 |
|---|---|
| Workers | 部署到 `workers.dev` |
| Static Assets | 最多 1,000 个文件，每个 5 MiB |
| KV | 允许 |
| D1 | 1 个数据库，每库 100 MB / 总计 100 MB |
| Durable Objects | 允许 |
| Hyperdrive | 2 个配置，10 个连接 |
| Queues | 最多 10 个 |
| SSL/TLS 证书 | 允许 |

## 常见陷阱

- **`--temporary` 不在 `wrangler deploy --help` 中，也不是全局选项。** 它被有意隐藏，并且是动态浮现的：当未认证的 `wrangler deploy` 失败时，Wrangler 会提示"rerun with `--temporary`"。不要因为 `--help` 里没有它就断定该选项不存在——去检查版本。
- **陈旧的全局 wrangler。** 全局安装的旧版 `wrangler`（`< 4.102.0`）会悄无声息地缺少该选项。请始终使用 `npx wrangler@latest`（或固定到 `>=4.102.0`），以便你掌控版本。
- **存在凭据 → 直接报错。** 如果曾经运行过 `wrangler login`，或设置了 `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_API_KEY`，`--temporary` 就会报错。要么在当前 shell 中取消该变量，要么执行 `wrangler logout`。绝不要在未告知用户的情况下清除他们真实的凭据。
- **速率限制。** 过快地创建临时账号会失败。请在 60 分钟窗口内复用缓存的账号（直接重新部署），而不是强行创建新的；若已被限流，请等待或改用永久账号。
- **60 分钟硬性过期，不可延长。** 如果部署需要存活超过一小时，用户必须认领它。请把这一点讲清楚。
- **重新部署后 `curl` 可能短暂返回旧响应体。** `workers.dev` 存在短暂的边缘缓存；即使 `curl` 在几秒内显示的是旧内容，`(reused)` 这一行加上新的 `Current Version ID` 也足以确认部署已成功。在断定重新部署失败之前，请再 curl 一次，或加上用于绕过缓存的查询字符串。
- **不要把认领 URL 当作"只是一个链接"记录到共享的对话记录里。** 它等同于凭据。

## 验证

- `npx wrangler@latest --version` 返回 `>= 4.102.0`。
- `npx wrangler@latest deploy --temporary` 打印出一个 `workers.dev` 线上 URL 和一个含 `claim-preview?claimToken=` 的认领 URL。
- `curl -sS <live_url>` 返回的正是 Worker 代码产生的响应体。
- 第二次部署报告 `Account: <name> (reused)`，且线上 URL 保持不变。
- 解析脚本的自检通过：`python3 scripts/parse_deploy_output.py --selftest`。
