---
sidebar_position: 17
title: "SSH / 远程主机上的 OAuth"
description: "当 Hermes 运行在远程机器、容器或跳板机后面时，如何完成基于浏览器的 OAuth（Spotify、MCP 服务器）"
---

# SSH / 远程主机上的 OAuth

部分 Hermes 提供商——**Spotify** 和 **远程 MCP 服务器**（Linear、Sentry、Atlassian、Asana、Figma 等）——使用*回环重定向（loopback redirect）* OAuth 流程。认证服务器将浏览器重定向到 `http://127.0.0.1:<port>/callback`，由 Hermes 启动的小型 HTTP 监听器获取授权码。

当 Hermes 和浏览器在同一台机器上时，这一切运行正常。一旦两者不在同一台机器上就会出问题：你笔记本上的浏览器试图访问**你笔记本**上的 `127.0.0.1`，但监听器绑定的是**远程服务器**上的 `127.0.0.1`。

解决方法是一行 SSH 本地端口转发。对于交互式终端上的 MCP 服务器，通常也可以直接粘贴重定向 URL（无需隧道）。

**xAI Grok OAuth（`xai-oauth`）使用 OAuth 设备代码**，不是回环回调——在任意浏览器中打开打印的验证 URL，Hermes 轮询直到批准即可，无需 SSH 隧道。请参阅 [xAI Grok OAuth](./xai-grok-oauth.md)。

## 快速概览

```bash
# 在你的本地机器（笔记本）上，另开一个终端：
ssh -N -L 43827:127.0.0.1:43827 user@remote-host

# 在远程机器的现有 SSH 会话中：
hermes auth add spotify --no-browser
# → Hermes 打印授权 URL，在笔记本的浏览器中打开。
# → 浏览器重定向到 127.0.0.1:43827/callback，隧道将请求转发
#   到远程监听器，登录完成。
```

Hermes 会在 `Waiting for callback on ...` 一行打印实际绑定的端口——从那里复制。Spotify 默认端口为 `43827`。

## 哪些提供商需要此操作

| 提供商 | 回环端口 | 需要隧道？ |
|----------|---------------|----------------|
| Spotify | `43827`（默认） | 是，当 Hermes 在远程时 |
| MCP 服务器（`auth: oauth`） | 每台服务器自动选择 | 是，当 Hermes 在远程时（或粘贴重定向 URL） |
| `xai-oauth`（Grok SuperGrok） | 不适用 | 否——设备代码流程 |
| `anthropic`（Claude Pro/Max） | 不适用 | 否——粘贴代码流程 |
| `openai-codex`（ChatGPT Plus/Pro） | 不适用 | 否——设备码流程 |
| `minimax`、`nous-portal` | 不适用 | 否——设备码流程 |

如果你的提供商不在表中，则不需要隧道。

## MCP 服务器

远程 MCP 服务器（Linear、Sentry、Atlassian、Asana、Figma 等）使用同样的回环重定向流程。Hermes 会为每台服务器自动选择一个空闲端口，并在 OAuth 流程启动时打印授权 URL——可能是在启动时（当 `mcp_servers:` 中出现新服务器时），也可能是在你运行 `hermes mcp login <server>` 时。

从远程主机完成该流程有两种方式：

**方式 1 —— 粘贴回重定向 URL（无需配置，随处可用）。** 在交互式终端上，Hermes 会在运行本地监听器的同时提示你粘贴重定向 URL。在浏览器中批准后，跳转到 `http://127.0.0.1:<port>/callback` 会显示连接错误——这是预期行为。复制**浏览器地址栏中的完整 URL**，粘贴到 Hermes 的提示处：

```
  MCP OAuth: authorization required.
  Open this URL in your browser:

    https://mcp.linear.app/authorize?response_type=code&...

  Or paste the redirect URL here (or the ?code=...&state=... portion) and press Enter:
> https://mcp.linear.app/callback?code=abc123&state=xyz
  Got authorization code from paste — completing flow.
```

也可以只粘贴 `?code=...&state=...` 查询串。此方式适用于任何 `auth: oauth` 的 MCP 服务器，且无需修改 SSH 配置。

**方式 2 —— SSH 端口转发（与 Spotify 相同）。** Hermes 会在 SSH 会话提示中打印它实际绑定的端口。在笔记本上另开一个终端：

```bash
ssh -N -L <port>:127.0.0.1:<port> user@remote-host
```

然后照常在浏览器中打开授权 URL；重定向会经隧道转发，监听器即可接收。当你需要该流程无人值守地完成时（例如无法交互粘贴的脚本化重新认证），请使用此方式。

**陷阱 —— 30 秒配置重载竞态。** 如果你在运行中的 Hermes 会话内编辑 `~/.hermes/config.yaml` 添加一个 OAuth MCP 服务器，CLI 会以 30 秒超时自动重载 MCP 连接。这不足以完成交互式 OAuth 流程，重载会放弃。请改为在新终端中运行 `hermes mcp login <server>`——它没有这个上限，会等待完整的 5 分钟供你粘贴回来。

## 为什么监听器不能直接绑定 0.0.0.0

Spotify 和大多数 MCP OAuth 服务器会根据白名单验证 `redirect_uri` 参数，并要求回环形式（`http://127.0.0.1:<精确端口>/callback`）。将监听器绑定到 `0.0.0.0` 或使用不同端口会导致认证服务器以 redirect_uri 不匹配为由拒绝请求。SSH 隧道可以端到端保持回环 URI 不变。

## 分步操作：单次 SSH 跳转

### 1. 从本地机器启动隧道

```bash
# Spotify（端口 43827）
ssh -N -L 43827:127.0.0.1:43827 user@remote-host
```

`-N` 表示「不打开远程 shell，仅保持隧道」。登录期间保持此终端运行。

### 2. 在另一个 SSH 会话中运行认证命令

```bash
ssh user@remote-host
hermes auth add spotify --no-browser
```

Hermes 检测到 SSH 会话，跳过自动打开浏览器，并打印授权 URL 以及 `Waiting for callback on http://127.0.0.1:<port>/callback`。

### 3. 在本地浏览器中打开 URL

从远程终端复制授权 URL，粘贴到笔记本的浏览器中。批准同意后，认证服务器重定向到 `http://127.0.0.1:<port>/callback`。浏览器经隧道访问，请求转发到远程监听器，Hermes 打印 `Login successful!`。

看到成功提示后即可关闭隧道（在第一个终端按 Ctrl+C）。

## 通过跳板机

如果通过堡垒机 / 跳板机访问 Hermes，使用 SSH 内置的 `-J`（ProxyJump）：

```bash
ssh -N -L 43827:127.0.0.1:43827 -J jump-user@jump-host user@final-host
```

这样会通过跳板机串联一条 SSH 连接，而不会把回环端口暴露在跳板机本身上。笔记本上的本地 `127.0.0.1:43827` 会直接隧道贯通到最终远程主机上的 `127.0.0.1:43827`。

对于不支持 `-J` 的旧版 OpenSSH，长格式写法是：

```bash
ssh -N \
    -o "ProxyCommand=ssh -W %h:%p jump-user@jump-host" \
    -L 43827:127.0.0.1:43827 \
    user@final-host
```

## Mosh、tmux 与 ssh ControlMaster

隧道是底层 SSH 连接的属性。如果你在 mosh 会话中的 `tmux` 内运行 Hermes，mosh 的漫游不会携带 `-L` 转发。请*单独*开一条普通 SSH 会话**专门**用于 `-L` 隧道——认证流程期间必须保持存活的正是这条连接。你的交互式 mosh/tmux 会话可以照常运行 Hermes。

如果你使用 `ssh -o ControlMaster=auto`，复用连接上的端口转发与主连接共享生命周期。若隧道无法建立，请重启主连接：

```bash
ssh -O exit user@remote-host
ssh -N -L 43827:127.0.0.1:43827 user@remote-host
```

## 故障排除

### `bind [127.0.0.1]:43827: Address already in use`

笔记本上已有进程占用该端口。可能是上一次的隧道没有干净退出，也可能是本地的 Hermes 也在监听它。找到并结束占用进程：

```bash
# macOS / Linux
lsof -iTCP:43827 -sTCP:LISTEN
kill <PID>
```

然后重试 `ssh -L` 命令。

### 等待本地回调超时

重定向未到达远程监听器。确认隧道仍在运行（`ssh -N` 不输出任何内容，所以要查看你启动它的那个终端），确认使用的是最新一次 `Waiting for callback on ...` 中的端口（首选端口被占用时 Hermes 可能自动递增），必要时重启隧道并重新运行认证命令。

### token 落到了错误的 `~/.hermes`

token 会写入运行 `hermes auth add ...` 的那个 Linux 用户名下。如果你的网关 / systemd 服务以另一个用户运行（例如 `root` 或专用的 `hermes` 用户），请以**该**用户身份认证，token 才会落到它的 `~/.hermes/auth.json`。可用 `sudo -u hermes -i` 或等效方式。

## 另请参阅

- [xAI Grok OAuth](./xai-grok-oauth.md)——设备代码；无需 SSH 隧道
- [Spotify（SSH 上运行）](../user-guide/features/spotify.md#running-over-ssh--in-a-headless-environment)
- [原生 MCP 客户端（OAuth 部分）](../user-guide/features/mcp.md#oauth-authenticated-http-servers)
- [SSH `-J` / ProxyJump（man 手册）](https://man.openbsd.org/ssh#J)
