---
sidebar_position: 16
title: "通过 MCP 管理 Hermes Cloud"
description: "将 Hermes Agent 连接到 Nous Portal MCP 服务器，让本地 agent 以对话方式列出、启动、停止和管理你的 Hermes Cloud 实例"
---

# 通过 MCP 管理 Hermes Cloud

[Hermes Cloud](https://portal.nousresearch.com/cloud) 为你运行托管的 Hermes Agent 实例。通常你会在 [Nous Portal](/integrations/nous-portal) 的 `/agents` 页面管理它们。本指南将你的**本地** Hermes Agent 连接到 Portal 的 MCP 服务器，这样你只需开口提问——"列出我的云端 agent"、"重启那个已停止的"、"它花了我多少钱"——就能管理这些云端实例，无需离开终端。

它是由 Nous Research 托管的标准 [MCP](/user-guide/features/mcp) 服务器，使用与你登录 Portal 相同的 OAuth 登录进行鉴权。连接后，Hermes 会获得两个可代表你调用的工具。

## 你可以用它做什么 {#what-you-can-do-with-it}

连接后，模型可以针对你的 Hermes Cloud 组织调用以下操作：

| 你可以这样问…… | 底层调用 |
|----------|----------------|
| "列出我的云端 agent" | `agents`（list） |
| "`<name>` 的状态如何？" | `agents`（get / status） |
| "这个实例大概花费多少？" | `agents`（cost_estimate） |
| "启动 / 停止 / 重启 `<name>`" | `agent`（start / stop / restart） |
| "新建一个名为 `<name>` 的实例" | `agent`（create） |
| "销毁 `<name>`" | `agent`（destroy） |
| "更新 `<name>` 的环境变量 / 镜像" | `agent`（update_env / update_image） |

每次调用都以你的 Portal 身份作用于**你的**组织，并且每次调用都会重新检查成员资格——该连接只能操作你本来就能在 Web 界面中控制的实例。

## 前置条件 {#prerequisites}

- 一个拥有 [Hermes Cloud](https://portal.nousresearch.com/cloud) 访问权限的 [Nous Portal](/integrations/nous-portal) 账号（至少有一个实例，或者有权创建实例）。
- 已安装 MCP 支持。如果你使用的是标准安装脚本，它已经装好了；否则：

  ```bash
  cd ~/.hermes/hermes-agent
  uv pip install -e ".[mcp]"
  ```

你**不需要**单独的 API key 或客户端密钥——服务器使用带 PKCE 的 OAuth，登录只需在浏览器中往返一次。

## 第一步：添加服务器 {#step-1-add-the-server}

```bash
hermes mcp add --url https://portal.nousresearch.com/mcp --auth oauth hermes-cloud
```

`--auth oauth` 告诉 Hermes 这是一个受 OAuth 保护的 HTTP 服务器。首次连接时，Hermes 会：

1. 自动发现服务器的 OAuth 端点（RFC 9728 / 8414 元数据）。
2. 将自身注册为客户端（RFC 7591 动态客户端注册）——无需复制任何密钥。
3. 打开浏览器进入 Portal 进行登录和授权。
4. 将得到的 token 存储在 `~/.hermes/mcp-tokens/` 下并重复使用（刷新是自动的）。

### 选择组织 {#choosing-an-organization}

如果你的 Portal 账号属于**多个组织**，浏览器会在授权过程中显示一个**组织选择器**——选择此连接要管理的组织。这一选择只在浏览器中做一次；命令行上无需传递任何参数。只属于单个组织的账号会跳过此步骤并自动绑定。

如果以后需要让连接指向另一个组织，请移除并重新添加服务器（先 `hermes mcp remove hermes-cloud`，再次运行 `add` 命令），然后在浏览器中选择另一个组织。

## 第二步：验证连接成功 {#step-2-verify-it-connected}

```bash
hermes mcp test hermes-cloud
```

然后启动（或重新加载）一个会话：

```bash
hermes chat
```

```text
/reload-mcp
```

问一个只读问题，确认工具已生效：

```text
List my Hermes Cloud agents and their current status.
```

你应该会得到与 Portal `/agents` 页面上相同的实例。

## 第三步：开始使用 {#step-3-use-it}

只读问题总是安全的：

```text
Which of my cloud agents is currently running, and roughly what is each one costing?
```

生命周期操作对应普通的请求：

```text
Restart the instance called research-bot.
```

```text
Create a new Hermes Cloud instance named scratch, then tell me when it's ready.
```

Hermes 会报告每个工具返回的内容——实例列表、新状态、新建实例的详细信息——方便你确认操作已生效。

## 配置 {#configuration}

执行 `hermes mcp add` 之后，该服务器会保存在 `~/.hermes/config.yaml` 中：

```yaml
mcp_servers:
  hermes-cloud:
    url: "https://portal.nousresearch.com/mcp"
    auth: oauth
```

`config.yaml` 中不存放任何凭据——OAuth token 单独保存在 `~/.hermes/mcp-tokens/` 下，就像 Portal 的刷新 token 也不会出现在你的配置中一样。

### 限制工具暴露面 {#limiting-the-tool-surface}

该服务器同时暴露只读工具（`agents`）和变更类工具（`agent`）。如果你希望该连接是**只读**的——可以列出和查看，但永远不能启动/停止/创建/销毁——请将其限制为 `agents` 工具：

```yaml
mcp_servers:
  hermes-cloud:
    url: "https://portal.nousresearch.com/mcp"
    auth: oauth
    tools:
      include: [agents]
```

修改配置后运行 `/reload-mcp`。完整的过滤模型（`include`/`exclude`、`prompts`、`resources`）请参阅[在 Hermes 中使用 MCP](/guides/use-mcp-with-hermes)。

## 故障排查 {#troubleshooting}

### 浏览器显示了组织选择器，我不确定该选哪个 {#the-browser-shows-an-org-picker-and-im-not-sure-which-to-choose}

你属于多个 Portal 组织。请选择你希望通过此连接管理其 Hermes Cloud 实例的那个组织。如果不确定，就选拥有你在 Portal `/agents` 页面上看到的那些实例的组织。之后你可以通过移除并重新添加服务器来重新选择。

### 连接时出现 "invalid_client" 或 "unknown client" {#invalid_client-or-unknown-client-on-connect}

已存储的客户端注册信息与服务器不再匹配（例如你之前连接过另一个环境）。清除该服务器缓存的 OAuth 状态并重新添加：

```bash
hermes mcp remove hermes-cloud
rm -f ~/.hermes/mcp-tokens/hermes-cloud.*
hermes mcp add --url https://portal.nousresearch.com/mcp --auth oauth hermes-cloud
```

### 添加服务器后工具没有出现 {#the-tools-arent-showing-up-after-adding-the-server}

在会话内重新加载 MCP 并再次检查：

```text
/reload-mcp
```

```text
Tell me which MCP-backed tools are available right now.
```

如果仍然缺失，运行 `hermes mcp test hermes-cloud` 直接查看连接错误。

### 它要求我重新登录 {#it-asks-me-to-log-in-again}

OAuth token 会自动刷新，但如果 Portal 使你的会话失效（修改密码、撤销、过期），下一次调用会要求你重新授权。重新运行 `hermes mcp add` 命令即可——浏览器流程会重新签发 token。

### 无头 / SSH / 远程主机 {#headless--ssh--remote-host}

OAuth 浏览器回调运行在 Hermes 所在的机器上。在远程主机上，请通过 SSH 转发回环端口——与其他任何 OAuth 登录的方式相同。参见 [通过 SSH / 远程主机进行 OAuth](/guides/oauth-over-ssh)。

## 另请参阅 {#see-also}

- **[Nous Portal](/integrations/nous-portal)** —— 同一登录背后的订阅、模型和 Tool Gateway
- **[在 Hermes 中使用 MCP](/guides/use-mcp-with-hermes)** —— 连接和过滤 MCP 服务器的通用方法
- **[MCP 功能概览](/user-guide/features/mcp)** —— MCP 是什么以及 Hermes 如何使用它
- **[MCP 配置参考](/reference/mcp-config-reference)** —— 所有 `mcp_servers` 字段，包括 `auth: oauth`
- **[通过 SSH 进行 OAuth](/guides/oauth-over-ssh)** —— 在远程或仅有浏览器的环境中登录
