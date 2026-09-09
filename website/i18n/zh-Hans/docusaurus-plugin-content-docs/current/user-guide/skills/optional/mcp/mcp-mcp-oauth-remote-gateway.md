---
title: "Mcp Oauth Remote Gateway —— 在无头网关上为远程 MCP 服务器手动完成 OAuth"
sidebar_label: "Mcp Oauth Remote Gateway"
description: "在无头网关上为远程 MCP 服务器手动完成 OAuth"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Mcp Oauth Remote Gateway

在无头网关上为远程 MCP 服务器手动完成 OAuth。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/mcp/mcp-oauth-remote-gateway` 安装 |
| 路径 | `optional-skills/mcp/mcp-oauth-remote-gateway` |
| 版本 | `1.0.0` |
| 作者 | Ben Barclay (benbarclay), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos |
| 标签 | `MCP`, `OAuth`, `PKCE`, `Remote-Deployment` |
| 相关 skill | `native-mcp`, [`mcporter`](/user-guide/skills/optional/mcp/mcp-mcporter), [`fastmcp`](/user-guide/skills/optional/mcp/mcp-fastmcp) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# 在远程 Hermes 网关上完成 MCP OAuth

## 概述

Hermes 内置的 MCP OAuth 客户端会在 Hermes 进程内于 `127.0.0.1:<port>` 上启动一个一次性 HTTP 监听器，并把该回环地址注册为 OAuth 的 `redirect_uri`。这在用户自己机器上的本地 CLI 场景中完全没问题。但当 Hermes 作为远程网关运行时（容器、VPS、消息机器人），它就彻底失效了，因为用户浏览器会把 `127.0.0.1` 解析到用户自己的笔记本，而不是远程容器 —— 于是授权码永远送不到 Hermes。

本 skill 手动完成 OAuth 流程，并把得到的令牌写入 Hermes 令牌存储所期望的确切文件中，这样随后的 `/reload-mcp` 就能找到缓存令牌，完全跳过浏览器流程。

## 何时使用

当**以下全部**条件成立时使用本 skill：

1. 用户想要添加一个需要 OAuth（而非静态 Bearer 令牌）的远程 HTTP MCP 服务器。
2. Hermes 以**远程网关**方式运行（容器、VPS、Docker、托管服务）—— 而不是用户笔记本上的本地 CLI。
3. 该服务器支持带 PKCE 的 OAuth 2.1 以及 RFC 7591 动态客户端注册（多数现代 MCP 服务器都支持 —— Better Stack、Linear、Cloudflare、Datadog 等）。如果它不支持 DCR（GitHub 是著名的例外），本 skill 不适用 —— 请改用预先注册的 OAuth App 或个人访问令牌。

以下情况**不要**使用：
- **本地 CLI 版 Hermes** —— 直接在 `mcp_servers.<name>` 中设置 `auth: oauth` 并 `/reload-mcp` 即可。内置流程会打开浏览器并在 localhost 上捕获回调，工作得很好。
- **接受静态 Bearer 令牌（API key）的服务器** —— 只要用户愿意，就优先使用 `headers.Authorization: "Bearer <token>"`。更简单，也不用折腾刷新。
- **GitHub Copilot MCP**（`api.githubcopilot.com/mcp/`）—— GitHub 不提供 DCR。请使用 PAT 或预先注册的 OAuth App（见陷阱 12）。

## 为什么内置 OAuth 流程在远程网关上会失败

Hermes 原生的 MCP OAuth 客户端（`tools/mcp_oauth.py`）：

1. 挑选一个空闲的本地端口 `P`。
2. 向授权服务器（AS）动态注册一个 OAuth 客户端，发送 `redirect_uri = http://127.0.0.1:P/callback`。
3. **在 Hermes 进程内**于 `127.0.0.1:P` 启动一个 HTTP 服务器。
4. 打印授权 URL，并在其本地端点上等待授权码。

当 Hermes 在远程运行时，`redirect_uri` 中的 `127.0.0.1` 指的是远程容器的回环地址，而不是用户的。授权之后，用户浏览器会 302 跳转到 `http://127.0.0.1:P/callback?code=...`，它解析到用户自己的笔记本并连接失败。回调永远到不了 Hermes 进程，流程超时，而 `/reload-mcp` 只会返回一句没有细节的 "No MCP tools available"。

需要识别的症状：hermes 用户下出现 `[xdg-open] <defunct>` 进程、令牌目录（`$HERMES_HOME/mcp-tokens/`）为空或不存在，以及一次 reload 的 `change_detail` 中没有任何 "Added/Reconnected: X" 行。

## 廉价的首选退路：内置流程自带的逃生舱

在做任何手动令牌手术之前，先看看内置流程的退路是否已经覆盖了你的部署形态。当 Hermes 检测到是远程会话时，它会在授权 URL 旁边打印两个选项（`tools/mcp_oauth.py`）：

1. **粘贴回填** —— 在交互式 TTY 上，会有一个 stdin 读取器与 HTTP 监听器竞争。用户完成授权后，浏览器连接 `127.0.0.1:<port>` 失败，用户把地址栏中的完整 URL（`?code=...&state=...`）粘贴回提示符。适用于 SSH 登录的 CLI 会话。
2. **SSH 端口转发** —— `ssh -N -L <port>:127.0.0.1:<port> <user>@<host>` 可以让重定向正常抵达远端监听器。

两者都需要一个连到 Hermes 主机的交互式终端。本 skill 的其余部分针对的是**没有**交互式 TTY 的情况 —— Hermes 纯粹作为消息网关/机器人运行，`/reload-mcp` 触发了流程却没人在提示符前。

## 首选正门：Hermes 仪表盘（在手动令牌手术之前先试它）

远程 Hermes 网关通常还会以**独立进程**运行**仪表盘** Web UI（例如 `hermes dashboard --host 0.0.0.0 --port <port>`；用 `ps aux | grep 'hermes dashboard'` 检查）。它提供一个连接器/MCP 控制台 —— 有 `/api/mcp/servers`、`/api/mcp/status` 和 `/connectors` 之类的端点（都需要登录；不带 cookie 的 curl 返回 401/302 即可确认它们存在）。

**为什么仪表盘能解决核心问题：** 当用户*在自己的浏览器里*从仪表盘驱动 OAuth 时，重定向会落在仪表盘能够捕获的上下文中 —— 从而绕开了让 CLI/手动流程失败的 `127.0.0.1` 回调问题。因此，"在远程网关上添加或重新授权一个 OAuth MCP 服务器"的正确升级顺序是：

1. **仪表盘，在用户自己的浏览器中** —— 这是设计上的正门。添加服务器、执行 OAuth、重载，全部以用户身份完成认证。不需要复制粘贴回调的折腾，也不需要手写令牌文件。
2. **手动令牌手术（本 skill 的其余部分）** —— 当没有通往仪表盘的浏览器会话时（纯聊天/无头环境）的**退路**。

**找到仪表盘的公网 URL。** 仪表盘在内部绑定 `0.0.0.0:<port>`，但用户需要的是外部可达的 URL。大多数部署平台会把它注入环境变量 —— 与其让用户去翻，不如直接 grep：

```bash
env | grep -iE "HERMES_DASHBOARD_PUBLIC_URL|RAILWAY_PUBLIC_DOMAIN|RAILWAY_STATIC_URL|RAILWAY_SERVICE_.*_URL|PUBLIC_URL|BASE_URL|DOMAIN" \
  | sed -E 's/(TOKEN|SECRET|KEY|PASSWORD)=.*/\1=***REDACTED***/I'
```

存在 `HERMES_DASHBOARD_PUBLIC_URL` 时它是权威的。在 Railway 上还要检查 `RAILWAY_PUBLIC_DOMAIN` / `RAILWAY_STATIC_URL`（那个 `*.up.railway.app` 主机名）以及 `RAILWAY_SERVICE_*_URL` 变量，后者有时带有更友好的自定义域名。把完整的 `https://` URL 交给用户，并指引他们到 Connectors/MCP 区域。**务必**通过上面的 `sed` 做脱敏 —— 这类环境变量 grep 就挨着 `*_TOKEN`/`*_SECRET` 变量。

**仪表盘解决不了什么（仍属主机侧 / shell 范畴）：** 需要 shell 认证状态的 stdio 服务器（某个 CLI 的 `login` 命令，其凭据未必能在重启后保留），以及任何从 `$HERMES_HOME/.env` 读取凭据的东西。无论如何，这些都不在仪表盘的职责范围内。

## 变通方案

手动完成 OAuth 流程，然后把得到的令牌写入 Hermes 的 `HermesTokenStorage` 本会写入的确切文件中，这样在 `/reload-mcp` 时 Hermes 就能找到缓存令牌，完全跳过浏览器流程。

在网关主机上通过 `terminal` 工具运行下面的 shell 命令，并通过 `execute_code` 或 `terminal` 中的 python3 调用来执行 Python 步骤（PKCE 生成、令牌交换、文件写入）—— 文件写入必须与令牌交换处在**同一个**代码块中（见陷阱 16）。

### 1. 确认这确实是远程网关

```bash
env | grep -iE "HERMES|RAILWAY|CONTAINER"
echo "$DISPLAY $WAYLAND_DISPLAY $SSH_CLIENT"
```

没有显示环境 + 有远程标志 = 远程网关。`tools/mcp_oauth.py::_can_open_browser()` 用的正是这些环境变量，所以如果 Hermes 自己的自动检测说是"无头"，内置流程就跑不通。

### 2. 找到 HERMES_HOME 与配置文件路径

```bash
HERMES_HOME=$(python3 -c 'from hermes_constants import get_hermes_home; print(get_hermes_home())')
echo "config: $HERMES_HOME/config.yaml"
echo "tokens: $HERMES_HOME/mcp-tokens/"
```

### 3. 从 MCP 服务器发现 OAuth 元数据

MCP 服务器通过 RFC 9728（OAuth 2.0 受保护资源元数据）公布其 OAuth 配置。401 响应上的 `WWW-Authenticate` 头会告诉你去哪里找：

```bash
curl -sI https://mcp.example.com | grep -i www-authenticate
# → Bearer realm="mcp", resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"
```

**并非每个服务器都会返回 `WWW-Authenticate`。** 有些只返回一个裸的 `{"errors":["Unauthorized"]}` 401，没有任何认证发现提示。遇到这种情况，直接探测常见的 well-known 路径：

```bash
for p in \
  /.well-known/oauth-protected-resource \
  /.well-known/oauth-authorization-server \
  /.well-known/openid-configuration ; do
  echo "=== $p ==="
  curl -s -A "python-httpx/0.27" "https://mcp.example.com$p" | head -c 400; echo
done
```

抓取资源元数据以获得 `authorization_servers`，然后抓取该 AS 的 `/.well-known/oauth-authorization-server` 以获得 `authorization_endpoint`、`token_endpoint` 和 `registration_endpoint`。

陷阱：很多服务器位于 Cloudflare 之后，会对裸 `urllib` 的 User-Agent 返回 403。本流程中的请求请始终设置 `User-Agent: python-httpx/0.27`（或类似值）。

### 4. 动态客户端注册（RFC 7591）

向 `registration_endpoint` POST：

```json
{
  "client_name": "Hermes Agent (manual OAuth)",
  "redirect_uris": ["http://127.0.0.1:8765/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none",
  "scope": "<scopes_from_resource_metadata>"
}
```

如果 AS 的 `scopes_supported` 为空，就完全省略 `scope` —— 见步骤 5 的陷阱。使用端口 `8765`（或任意端口 —— 反正不会有东西监听）。`token_endpoint_auth_method: none` 表明这是一个公共 PKCE 客户端。保存返回的 `client_id`。

### 5. 用 PKCE 构造授权 URL

生成：
- `code_verifier`：`secrets.token_urlsafe(64)[:128]`
- `code_challenge`：`base64url(sha256(code_verifier))`（不带填充）
- `state`：`secrets.token_urlsafe(24)`

查询参数：`response_type=code`、`client_id`、`redirect_uri`、`code_challenge`、`code_challenge_method=S256`、`state`，外加 `resource=<mcp_server_url>`（RFC 8707 —— 很多服务器要求用它把令牌绑定到具体的 MCP 资源）。**仅当** AS 元数据的 `scopes_supported` 是非空数组，和/或资源元数据声明了具体 scope 时，才包含 `scope=<空格分隔>`。如果 `scopes_supported: []`，请省略 `scope` 参数 —— 服务器会自行授予其完整的默认集合。在 `scopes_supported` 为空的情况下编造 scope 字符串，可能在某些 AS 上引发 `invalid_scope` 错误。

**把 `code_verifier` 和 `state` 暂存到磁盘**（例如 `/tmp/.mcp-oauth-work/<server>.json`，权限 0600）。步骤 7 需要它们，而且可能要跨多轮对话。

### 6. 把授权 URL 交给用户

```
Open this URL in your browser:
<authorize_url>

After approving, your browser will try to load http://127.0.0.1:8765/callback
and fail to connect — THAT'S EXPECTED. Just copy the entire URL from the
address bar (it will contain ?code=...&state=...) and paste it back here.
```

### 7. 用授权码换取令牌

当用户粘贴回调 URL 后：

1. 从查询串中解析 `code` 与 `state`。
2. **校验 `state` 与暂存值一致**（CSRF 检查 —— 不要跳过）。
3. 以 `application/x-www-form-urlencoded` 向 `token_endpoint` POST：
   - `grant_type=authorization_code`
   - `code=<from callback>`
   - `redirect_uri=<same as step 4>`
   - `client_id=<from step 4>`
   - `code_verifier=<stashed>`
   - `resource=<mcp_server_url>`（如果 AS 在步骤 5 中要求了它，这里也要带上）
4. 响应中包含 `access_token`、`refresh_token`、`token_type`、`expires_in`、`scope`。

### 8. 按 Hermes 的确切 schema 写入令牌

`tools/mcp_oauth.py::HermesTokenStorage` 期望在 `$HERMES_HOME/mcp-tokens/` 下有两个文件（目录用 `0o700` 创建，文件用 `0o600`）：

**`<server_name>.json`** —— `OAuthToken` pydantic 模型：
```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 7200,
  "refresh_token": "...",
  "scope": "read write"
}
```

**`<server_name>.client.json`** —— `OAuthClientInformationFull` 模型：
```json
{
  "client_id": "...",
  "redirect_uris": ["http://127.0.0.1:8765/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none",
  "scope": "read write",
  "client_name": "..."
}
```

每个文件都用 `json.dumps(..., indent=2)` 写出。用 `re.sub(r'[^\w\-]', '_', server_name)[:128]` 清洗文件名 —— 这与 Hermes 令牌存储中的 `_safe_filename()` 保持一致。

### 9. 把服务器添加到 config.yaml

```yaml
mcp_servers:
  <name>:
    url: "https://mcp.example.com"
    auth: oauth
    timeout: 180
    connect_timeout: 60
```

### 10. 在让用户重载之前先冒烟测试令牌

手动 POST 一个 MCP `initialize` 请求，端到端确认令牌可用 —— 这能在用户被又一次 "No MCP tools available" 搞糊涂之前，抓出 scope 配置错误、错误的 `resource` 值以及 CF 拦截：

```python
body = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "hermes-debug", "version": "1.0"},
    },
}).encode()
# 向 MCP URL POST，并带上：
#   Authorization: Bearer <access_token>
#   Accept: application/json, text/event-stream
#   Content-Type: application/json
#   MCP-Protocol-Version: 2025-06-18
#   User-Agent: python-httpx/0.27
```

预期得到 HTTP 200、`Content-Type: text/event-stream`，以及一个包含 `serverInfo` 与 `capabilities` 的 JSON-RPC 结果。**不要用带默认 UA 的 `urllib`** —— Cloudflare 会给你 403，尽管 Hermes（使用 httpx）能成功。`scripts/diagnose-oauth-mcp.py` 会自动执行这项冒烟测试。

### 11. 让用户运行 `/reload-mcp`

重载时，Hermes 看到 `auth: oauth`，调用 `HermesTokenStorage.get_tokens()`，找到你缓存的令牌，跳过浏览器流程，并注册 `mcp_<name>_*` 工具。刷新会在 `expires_in` 到期前自动进行。

## 陷阱与经验教训

1. **不要以为"无头"就等于"OAuth 不可能"。** 内置流程在本地 CLI 上工作良好；问题严格限于用户浏览器与 Hermes 进程分处不同机器的远程部署。在宣称 OAuth 不可行之前，先检查执行环境。

2. **读源码，别只读 skill 文档。** `tools/mcp_oauth.py` 以及 `website/docs/` 中的 MCP 配置参考才是权威依据。在告诉用户某个功能"不存在"之前，先 grep 一遍代码树。

3. **Cloudflare 的 UA 过滤。** 很多 MCP/OAuth 提供方把基础设施放在 Cloudflare 后面，即便元数据端点是公开的，它也会对 `python-urllib/*` 的 User-Agent 返回 403。请在本流程的每个请求上设置 `User-Agent: python-httpx/0.27`（或任何类浏览器字符串）。Hermes 自身使用 httpx，所以在真实连接路径上从不会遇到这个问题。

4. **在授权请求和令牌请求中都带上 `resource`。** 对多数现代 MCP 服务器而言，RFC 8707 的资源指示符不是可选项 —— 它把签发的令牌绑定到具体的 MCP 资源 URL。省略它有时仍然能用，但可能得到一个之后在 MCP 服务器上因 scope/audience 错误而失败的令牌。

5. **尾部斜杠很重要。** 有些服务器把资源公布为带尾斜杠的 `https://mcp.example.com/`，并拒绝针对无斜杠变体签发的令牌。请从 `.well-known/oauth-protected-resource` 响应中逐字复制 `resource` 值。

6. **`/reload-mcp` 失败时是静默的。** 如果重载显示 "No MCP tools available" 且没有 `change_detail` 行，说明配置里有某个服务器连接失败，却没有错误冒上来。去看错误日志尾部，用手动的 `initialize` POST 直接冒烟测试令牌，如果一切看起来都正常 —— 那就要求完整重启进程。

7. **熔断器可能在 `/reload-mcp` 后仍然存在。** `tools/mcp_tool.py` 维护着一个模块级的错误计数字典，阈值很小。一旦触发（例如令牌过期导致连续多次失败），工具处理器可能在调用服务器之前就短路，于是没有任何一次成功调用能重置计数器。症状：重载说 "Reconnected: X"，但同一轮对话中后续调用仍然报 "server unreachable"。恢复顺序：**先**试 `/reload-mcp`（成本低，不会中断聊天进程）—— 在当前版本上它可以清除计数器；只有当重载后真实调用**仍然**短路时，才升级到完整重启网关进程。不要一上来就说"你必须重启"。

8. **access_token 已过期 + 熔断器已触发 = 死锁。** 自动刷新逻辑跑在 MCP 调用路径里，而熔断器一旦触发就会把这条路径短路。仅仅手动刷新磁盘上的令牌无济于事 —— 手动刷新令牌要与完整重启配对，而不是与 `/reload-mcp` 配对。

9. **手动刷新时的 `invalid_grant` 意味着 refresh token 已死 —— 唯一的修复是重新授权，不要循环重试。** 当 access_token 过期时间足够长后，refresh_token 也可能在服务端被吊销/过期。此时 `grant_type=refresh_token` 的 POST 会返回 HTTP 400 `{"error":"invalid_grant",...}`（措辞各异："Grant not found"、"Token expired"、"refresh token is invalid"）。从网关侧**没有**任何恢复手段。请把问题交回用户，并给出两个选项：(a) 重新走一遍完整的手动 OAuth 流程（步骤 3–10），或 (b) 如果提供方支持静态个人 API key，就改用它 —— 没有刷新/过期周期，对无人值守的远程网关更耐用。尽早检测：在对 OAuth MCP 执行任何创建/更新操作之前，用 `expires_at` 与 `time.time()` 比较；如果已经过期，先尝试刷新并立刻暴露 `invalid_grant`，而不是在任务中途失败。

10. **刷新成功但新令牌仍被拒绝 = 服务端会话被吊销；只有一次全新的 authorization_code 流程能修复。** 这与陷阱 9 不同。存储的令牌文件可能看上去很健康（`expires_at` 还很远，refresh_token 也在），但一次实时的 `initialize` POST 返回 `401 invalid_token`，JSON-RPC 主体形如 `{"error":{"code":-32002,"message":"Session expired. Please re-authenticate."}}`。`grant_type=refresh_token` 的 POST 甚至可能**成功**（HTTP 200，拿到新的 access_token）—— 但这个崭新的令牌照样得到同一个 `-32002`。提供方在服务端吊销了底层的 MCP *会话*；OAuth 刷新链能重新铸造凭据，却无法重建一个已被吊销的会话。当某个 OAuth MCP 报告"未连接"时的判定规则：(1) 用手动 `initialize` POST 冒烟测试已存储的 access_token；(2) 若得到 `401 invalid_token`，尝试刷新并冒烟测试**新**令牌；(3a) 新令牌可用 → 写入并重启以清除熔断器；(3b) 新令牌仍得到 `-32002`/"Session expired" → 到此为止，这是会话吊销，把授权 URL 交给用户做完整的重新授权。`scripts/diagnose-oauth-mcp.py` 会自动执行第 1–2 步，并打印出你处在哪个分支。对于会话不断被吊销的无人值守网关，优先使用静态的个人 API key。参见 `references/stripe-mcp-oauth-revocation.md`，其中有一个每周吊销会话的提供方的实例分析。

11. **客户端信息文件不是可选的。** Hermes 需要 `<server>.client.json` 才能知道刷新授权时用的 `client_id`。跳过它意味着第一次刷新就会失败，用户不得不重新授权 —— 同时写入两个文件正是本 skill 的全部意义。

12. **绝不要手工敲出重定向 URL 让用户去打开。** 用 `urllib.parse.urlencode()` 以程序方式生成授权 URL。scope 中的空格和 `state` 中的特殊字符会破坏字符串拼接出来的 URL。

13. **安全：暂存文件里含有 `code_verifier`。** 令牌交换成功后立即删除 `/tmp/.mcp-oauth-work/<server>.json`。身份证明类的秘密一旦被消费掉，就没有理由再留着。

14. **写入令牌端点实际返回的内容。** AS 授予的 scope 可能比你请求的更窄（或更宽）。请把令牌交换响应中的 `scope` 写入 `<server>.json`，而不是你在步骤 5 里请求的那个。当 `scopes_supported: []` 时，你发送的显式 scope 列表在两个方向上都是权威的：有些服务器恰好授予你列出的内容（想最小权限就传窄的 scope，用户需要全部功能就把完整集合列全），而有些服务器在注册阶段不会回显已授予的 scope —— 只有令牌交换响应才是权威的。

15. **OAuth 令牌往往同时可以当作提供方公开 REST API 的 Bearer 令牌。** `<server>.json` 中的 access_token 经常并非"仅限 MCP" —— 只要对应的资源 scope 被授予，用 `Authorization: Bearer <token>` 访问提供方文档化的 REST API 就能成功。这是 OAuth 2.0 规范本身，而非某家提供方的怪癖。当 MCP 服务器只读、而你需要一次写操作时，先看看这个 OAuth 令牌能否直接打到提供方的 REST API，再考虑建议另外申请 API key。

16. **机密脱敏可能在工具输出中把令牌遮蔽掉。** 如果启用了机密脱敏，令牌和长的不透明字符串在工具结果里会渲染成 `***`，因此你无法靠 `print(response)` 把 access_token 跨轮次保留下来。再叠加 authorization_code 授权中 `code` 的一次性特性：如果你打印了令牌交换响应，可能既丢了令牌又消耗了授权码，被迫用新的授权 URL 从头再来。**务必在执行令牌交换的同一个代码块中，把 access_token 直接写入其最终目标文件。** 如果确实需要打印调试，只打印 `len(access_token)`、`token_type`、`scope`、`expires_in` —— 绝不要打印秘密本身。

17. **GitHub MCP（`api.githubcopilot.com/mcp/`）使用的是预先注册的机密型 OAuth App，而不是 DCR + 公共 PKCE。** 它的客户端信息自带真实的 `client_secret`，且 `token_endpoint_auth_method: client_secret_post`。向 `https://github.com/login/oauth/access_token` 发起的令牌交换 POST 必须在 `client_id`、`code`、`code_verifier` 和 `redirect_uri` 之外，把 `client_secret` 也作为表单字段带上（在密钥之上仍然会校验 PKCE）。重定向 URI 在 OAuth App 配置里是**固定的** —— 你改不了，所以手动指定监听端口的技巧在这里不适用；用户只需让浏览器在那个端口上连接失败，然后把地址栏 URL 粘贴回来。

## 不要做的事

- **不要拿 `mcp-remote` 当退路。** 它会跑一个 npx 子进程，而该子进程的 OAuth 回调服务器**同样**位于远程容器的 localhost 上 —— 一模一样的问题。只有当 MCP 客户端根本不支持远程 HTTP 时，`mcp-remote` 才有用（而 Hermes 原生支持）。
- **如果用户明确要求 OAuth，就不要硬推"把 API 令牌粘给我，我帮你加 headers"。** 只有在解释清楚原生 OAuth 流程为何在远程部署中失败之后，才提供静态令牌的捷径。用户为了免轮换、限定 scope 的访问而愿意多花力气，请尊重这个选择。
- **不要在没读源码的情况下声称 Hermes 不支持某个功能。** 做能力判断之前，先 grep 源码树。

## 速查文件

- `scripts/diagnose-oauth-mcp.py` —— 可重复运行、默认只读的诊断脚本。给定一个服务器名，它会冒烟测试已存储的 access_token、尝试刷新、再冒烟测试新令牌，并准确打印出你处在哪个恢复分支（`TOKEN_OK` = 熔断器/重启，`REFRESH_FIXED` = 持久化+重启，`SESSION_REVOKED` = 完整重新授权，`REFRESH_DEAD` = 完整重新授权/API key）。传 `--write` 可原子地持久化一个可用的刷新后令牌。绝不会打印秘密值。**当某个 OAuth MCP 服务器报告"未连接"时，先跑这个** —— 它编码了陷阱 7/9/10 的判定树。
- `references/stripe-mcp-oauth-revocation.md` —— 一个实例分析（Stripe），讲一个会周期性吊销 OAuth 会话的提供方，以及耐用的修复方案：改用静态的受限 API key。

## 相关

- `native-mcp` —— 在 Hermes 中配置 MCP 的通用指南。权威的配置参考在那里。
- `mcporter` —— 外部 CLI 桥接工具，用于在 Hermes 配置之外做临时的 MCP 调用。
