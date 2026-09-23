---
sidebar_position: 8
title: "MCP 配置参考"
description: "Hermes Agent MCP 配置键、过滤语义及工具策略参考"
---

# MCP 配置参考

本页是主 MCP 文档的简明参考手册。

概念说明请参阅：
- [MCP（Model Context Protocol）](/user-guide/features/mcp)
- [在 Hermes 中使用 MCP](/guides/use-mcp-with-hermes)

## 根配置结构 {#root-config-shape}

```yaml
mcp_servers:
  <server_name>:
    command: "..."      # stdio servers
    args: []
    env: {}

    # OR
    url: "..."          # HTTP servers
    headers: {}

    # Optional HTTP/SSE TLS settings:
    ssl_verify: true                # bool or path to a CA bundle (PEM)
    client_cert: "/path/to/cert.pem"  # mTLS client certificate (see below)
    # client_key: "/path/to/key.pem"  # optional, when key lives in a separate file

    enabled: true
    timeout: 120
    connect_timeout: 60
    supports_parallel_tool_calls: false
    tools:
      include: []
      exclude: []
      resources: true
      prompts: true
```

## 服务器键 {#server-keys}

| 键 | 类型 | 适用范围 | 含义 |
|---|---|---|---|
| `command` | string | stdio | 要启动的可执行文件 |
| `args` | list | stdio | 子进程的参数 |
| `env` | mapping | stdio | 传递给子进程的环境变量 |
| `url` | string | HTTP | 远程 MCP 端点 |
| `headers` | mapping | HTTP | 远程服务器请求的请求头 |
| `ssl_verify` | bool 或 string | HTTP | TLS 校验。`true`（默认）使用系统 CA，`false` 关闭校验（不安全），也可填自定义 CA 证书包（PEM）的路径字符串 |
| `client_cert` | string 或 list | HTTP | mTLS 客户端证书。字符串 = 同时包含证书与私钥的 PEM 文件路径。列表 `[cert, key]` = 证书与私钥分文件。列表 `[cert, key, password]` = 加密私钥 |
| `client_key` | string | HTTP | 客户端私钥路径，适用于 `client_cert` 为字符串且私钥位于单独文件的情况 |
| `enabled` | bool | 两者 | 为 false 时完全跳过该服务器 |
| `timeout` | number | 两者 | 工具调用超时时间（秒，默认：`300`） |
| `connect_timeout` | number | 两者 | 初始连接超时时间（秒，默认：`60`） |
| `protocol` | string | 两者 | 协议时代协商：`auto`（默认——先进行传统的 `initialize` 握手，当服务器以"仅支持新协议"为由拒绝握手时，回退到 2026-07-28 的 `server/discover` 无状态探测）、`stateless`（先探测 `server/discover`；再用传统方式重试一次）或 `legacy`（仅握手，不回退） |
| `supports_parallel_tool_calls` | bool | 两者 | 允许该服务器的工具并发执行 |
| `skip_preflight` | bool | HTTP | 对于 HEAD/GET 返回非 MCP content type 的合法 Streamable HTTP 端点，跳过快速失败的 content-type 预检（默认：`false`） |
| `transport` | string | HTTP | 设为 `sse` 可使用 SSE 传输而非 Streamable HTTP |
| `keepalive_interval` | number | 两者 | 存活探测（ping）的间隔秒数（默认：`180`，最低 5 秒）。对于会很快回收空闲会话的服务器，请将其设为低于服务器会话 TTL 的值 |
| `idle_timeout_seconds` | number | stdio | 可选：stdio 服务器空闲多久后回收（`0` 表示禁用）。也可以放在 `lifecycle:` 映射下 |
| `max_lifetime_seconds` | number | stdio | 可选：stdio 服务器存活多久后回收（`0` 表示禁用）。也可以放在 `lifecycle:` 映射下 |
| `tools` | mapping | 两者 | 过滤及工具策略 |
| `auth` | string | HTTP | 认证方式。设为 `oauth` 可启用带 PKCE 的 OAuth 2.1 |
| `sampling` | mapping | 两者 | 服务器发起的 LLM 请求策略（参见 MCP 指南） |
| `elicitation` | mapping | 两者 | 服务器发起的用户输入请求。`enabled`（默认 `true`）与 `timeout`（秒，默认 `300`）。表单模式的请求会经由审批界面处理；URL 模式会被拒绝（参见 MCP 指南） |
| `trust` | string | 两者 | 信任层级：`full`（默认）或 `untrusted`。在 `untrusted` 服务器上，所有具备写能力的工具调用（即没有 `readOnlyHint: true` 注解的工具）在执行前都需要通过标准审批界面获得用户批准。`readOnlyHint` 是服务器自报的*提示* —— 恶意服务器最多只能让自称只读的工具跳过审批，绝不会因此获得额外权限，因此对不完全受控的服务器请标记为 `untrusted`。无法识别的值按 `untrusted` 处理（失败即关闭） |

## 环境变量引用 {#environment-variable-references}

服务器条目中任意位置的字符串值（`env`、`headers`、`args`、`url` 等）都可以用 `${VAR}` 或 Cursor 风格的 SecretRef 形式 `${env:VAR}` 引用环境变量——两者解析为同一个变量，因此从 Cursor / Claude 配置中复制来的 MCP 片段无需改动即可使用：

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${env:GITHUB_TOKEN}"   # same as "${GITHUB_TOKEN}"
```

这些值从当前 profile 的密钥作用域中解析（找不到时回退到进程环境），因此请把密钥放在 `~/.hermes/.env` 中。未设置的变量会保留其字面占位符。

### 上下文变量 {#context-variables}

除了环境变量之外，Cursor 风格的上下文变量也会被插值（名称区分大小写）：

| 变量 | 解析为 |
|---|---|
| `${userHome}` | 当前用户的主目录 |
| `${workspaceFolder}` | 会话工作区根目录（已知时为会话终端的 cwd，否则为进程的 cwd） |
| `${workspaceFolderBasename}` | `${workspaceFolder}` 的末级目录名 |
| `${pathSeparator}` / `${/}` | 操作系统的路径分隔符（`os.sep`） |

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "${workspaceFolder}"]
    env:
      CACHE_DIR: "${userHome}${/}.cache${/}mcp"
```

其他任何 `${...}` 引用都会落到上面的环境变量查找中。

## `tools` 策略键 {#tools-policy-keys}

| 键 | 类型 | 含义 |
|---|---|---|
| `include` | string 或 list | 白名单：指定允许注册的服务器原生 MCP 工具。条目可以是精确名称，也可以是 fnmatch 风格的通配模式（`*_radar_*`、`get_zones_*`） |
| `exclude` | string 或 list | 黑名单：指定禁止注册的服务器原生 MCP 工具。精确名称 / 通配模式的语义与 `include` 相同 |
| `resources` | bool-like | 启用/禁用 `list_resources` + `read_resource` |
| `prompts` | bool-like | 启用/禁用 `list_prompts` + `get_prompt` |

## 过滤语义 {#filtering-semantics}

### `include`

若设置了 `include`，则只注册其中列出的服务器原生 MCP 工具。

```yaml
tools:
  include: [create_issue, list_issues]
```

### `exclude`

若设置了 `exclude` 且未设置 `include`，则注册除列出名称之外的所有服务器原生 MCP 工具。

```yaml
tools:
  exclude: [delete_customer]
```

### 优先级 {#precedence}

若两者同时设置，`include` 优先。

```yaml
tools:
  include: [create_issue]
  exclude: [create_issue, delete_issue]
```

结果：
- `create_issue` 仍被允许
- `delete_issue` 被忽略，因为 `include` 优先级更高

## 工具策略 {#utility-tool-policy}

Hermes 可为每个 MCP 服务器注册以下工具包装器：

Resources（资源）：
- `list_resources`
- `read_resource`

Prompts（提示词）：
- `list_prompts`
- `get_prompt`

### 禁用 resources {#disable-resources}

```yaml
tools:
  resources: false
```

### 禁用 prompts {#disable-prompts}

```yaml
tools:
  prompts: false
```

### 能力感知注册 {#capability-aware-registration}

即使设置了 `resources: true` 或 `prompts: true`，Hermes 也只在 MCP 会话实际暴露对应能力时才注册相应工具。

因此以下情况属于正常现象：
- 你启用了 prompts
- 但没有出现任何 prompt 工具
- 原因是该服务器不支持 prompts

## `enabled: false`

```yaml
mcp_servers:
  legacy:
    url: "https://mcp.legacy.internal"
    enabled: false
```

行为：
- 不发起连接
- 不进行服务发现
- 不注册工具
- 配置保留，供后续复用

## 空结果行为 {#empty-result-behavior}

若过滤后服务器原生工具全部被移除，且没有工具被注册，Hermes 不会为该服务器创建空的 MCP 运行时工具集。

## 配置示例 {#example-configs}

### GitHub 安全白名单 {#safe-github-allowlist}

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, create_issue, update_issue, search_code]
      resources: false
      prompts: false
```

### Stripe 黑名单 {#stripe-blacklist}

```yaml
mcp_servers:
  stripe:
    url: "https://mcp.stripe.com"
    headers:
      Authorization: "Bearer ***"
    tools:
      exclude: [delete_customer, refund_payment]
```

### 仅资源的文档服务器 {#resource-only-docs-server}

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      include: []
      resources: true
      prompts: false
```

### TLS 客户端证书（mTLS） {#tls-client-certificate-mtls}

对于要求客户端证书的 HTTP/SSE 服务器，请设置 `client_cert`（并可选设置 `client_key`）：

```yaml
mcp_servers:
  # Combined cert + key in a single PEM file
  internal_api:
    url: "https://mcp.internal.example.com/mcp"
    client_cert: "~/secrets/mcp-client.pem"

  # Separate cert and key files
  partner_api:
    url: "https://mcp.partner.example.com/mcp"
    client_cert: "~/secrets/client.crt"
    client_key: "~/secrets/client.key"

  # Encrypted key with a passphrase (3-element list form)
  bank_api:
    url: "https://mcp.bank.example.com/mcp"
    client_cert: ["~/secrets/client.crt", "~/secrets/client.key", "my-passphrase"]

  # Custom CA bundle (private CA / self-signed server)
  lab_api:
    url: "https://mcp.lab.local/mcp"
    ssl_verify: "~/secrets/lab-ca.pem"
    client_cert: "~/secrets/lab-client.pem"
```

注意事项：
- 路径支持 `~` 展开。文件缺失会在连接时快速失败，并给出针对该服务器的错误信息。
- `ssl_verify: false` 会完全关闭服务器证书校验。请勿在真实服务上使用。
- 在 Streamable HTTP 与 SSE 两种传输方式上均可使用。

## 重新加载配置 {#reloading-config}

修改 MCP 配置后，使用以下命令重新加载服务器：

```text
/reload-mcp
```

## 工具命名 {#tool-naming}

服务器原生 MCP 工具的命名格式为：

```text
mcp__<server>__<tool>
```

示例：
- `mcp__github__create_issue`
- `mcp__filesystem__read_file`
- `mcp__my_api__query_data`

工具包装器遵循相同的前缀规则：
- `mcp__<server>__list_resources`
- `mcp__<server>__read_resource`
- `mcp__<server>__list_prompts`
- `mcp__<server>__get_prompt`

双下划线分隔符（`mcp__…__…`）与 Claude Code、Codex 和 OpenCode 使用的约定一致，即使服务器名或工具名本身包含下划线，也能明确区分两者的边界。

### 名称规范化 {#name-sanitization}

服务器名称和工具名称中任何非字母、数字或下划线的字符（连字符、点号、空格等）在注册前均会替换为下划线。这确保工具名称是 LLM function-calling API 的合法标识符。

例如，名为 `my-api` 的服务器暴露了名为 `list-items.v2` 的工具，注册后变为：

```text
mcp__my_api__list_items_v2
```

编写 `include` / `exclude` 过滤器时请注意——使用**原始** MCP 工具名称（含连字符/点号），而非规范化后的名称。

## OAuth 2.1 认证 {#oauth-21-authentication}

对于需要 OAuth 的 HTTP 服务器，在服务器条目中设置 `auth: oauth`：

```yaml
mcp_servers:
  protected_api:
    url: "https://mcp.example.com/mcp"
    auth: oauth
```

行为：
- Hermes 使用 MCP SDK 的 OAuth 2.1 PKCE 流程（元数据发现、客户端标识、token 交换及刷新）
- 首次连接时，浏览器窗口将打开以完成授权
- Token 持久化至 `~/.hermes/mcp-tokens/<server>.json`，跨会话复用
- Token 刷新自动进行；仅在刷新失败时才需重新授权
- 仅适用于 HTTP/StreamableHTTP 传输（基于 `url` 的服务器）

### 设备码登录（RFC 8628） {#device-code-login-rfc-8628}

对于公布了 `device_authorization_endpoint` 的授权服务器，可以在运行 Hermes 的机器上的终端中显式选择设备授权：

```bash
hermes mcp login protected_api --flow device
```

在任意设备上打开打印出来的验证 URL，并输入显示的用户码。Hermes 会轮询等待批准，遵循 `authorization_pending` 和 `slow_down`，并在被拒绝或过期时停止。不会启动浏览器，也不需要回调监听器。`oauth.timeout` 限定等待批准的时间（默认 300 秒），同时也受该用户码有效期的限制。

在服务器上设置 `oauth.flow: device`，可让 `hermes mcp login` 和 `hermes mcp reauth`（包括 `reauth --all`）使用设备授权。`login --flow browser` 可在单次登录中覆盖该设置；浏览器 PKCE 仍是默认方式。不受支持的元数据会产生一个可据以处理的错误，而不会悄无声息地回退到其他流程。

设备登录会在动态注册时请求设备授权和刷新授权，或者使用你配置的 `oauth.client_id`、`oauth.client_secret` 和 `oauth.token_endpoint_auth_method`。注册的客户端必须允许设备授权。浏览器使用的 CIMD 文档在此不会被使用。`oauth.scope` 会随设备授权请求发送；`oauth.user_agent` 同样适用于 token 轮询。Token、注册信息和签发方元数据保存在当前 profile 的 MCP token 存储中，现有的运行时刷新路径会在重启后复用它们。失败的设备授权不会替换之前已保存的凭据。

首次设备登录只能在终端中进行：仪表盘/浏览器回调和后台重连都不会发起设备授权。请针对与 gateway **相同的 profile 和主机**运行登录命令。已过期/被拒绝的设备授权如果没有可用的刷新 token，就需要再次显式登录。

### 客户端标识：CIMD 与 DCR {#client-identification-cimd-and-dcr}

Hermes 通过 **Client ID Metadata Document**（CIMD，客户端 ID 元数据文档）向授权服务器表明自己的身份，这是 MCP `2026-07-28` 规范为取代动态客户端注册（Dynamic Client Registration）而采用的机制。该文档发布在
`https://nousresearch.github.io/hermes-agent/docs/oauth/client-metadata.json`，而这个 URL 本身*就是* `client_id`——授权服务器会获取它，以了解 Hermes 的名称、徽标和允许的重定向 URI。不会为每个安装单独注册任何东西，也没有任何与用户相关的内容。

最终的选择权在授权服务器手中：只有当服务器在其元数据中公布 `client_id_metadata_document_supported: true` 时，SDK 才会把文档 URL 作为 `client_id` 发送；否则会像以前一样通过 DCR 注册。DCR 在 MCP 规范中已被弃用，但目前几乎所有已部署的服务器仍在使用它。

#### 回调端口 {#callback-ports}

该文档声明了一组固定的回环重定向 URI，而规范要求授权请求中的重定向 URI 必须与其中之一*精确字符串匹配*——因此 CIMD 流程无法使用 Hermes 通常选择的随机高位端口。于是 Hermes 会把回调固定在 `27890`–`27894` 中的某个端口上。

这个固定必须在得知服务器能力之前就做出选择，因为重定向 URI 在流程开始时就已确定，而服务器的元数据要到流程中途才会到达。所以 Hermes 会为任何*可能*最终使用 CIMD 的流程固定端口，其余的则回退到随机端口：

- Hermes 以前连接过、且其缓存元数据未公布 CIMD 的服务器，继续使用它一直以来的随机端口。
- Hermes 从未连接过的服务器，在首次登录时会使用固定端口，因为猜测是 CIMD 能够被使用的唯一途径。
- 任何会把回调挪到别处的情况也都会回退：预先注册的 `oauth.client_id`、`oauth.client_secret`、自定义的 `oauth.client_name` 或 `oauth.token_endpoint_auth_method`、`oauth.redirect_uri` 或 `oauth.redirect_port` 覆盖、由仪表盘或桌面应用发起的登录、磁盘上已有的客户端注册，或者五个端口全部被其他进程占用。

每个固定端口在被选中后会立即绑定，并一直保持到浏览器重定向到达为止，因此两次并发登录——第二个 profile，或同一进程中的另一个服务器——不会落到同一个监听器上。

#### 当服务器拒绝该文档时 {#when-a-server-rejects-the-document}

如果服务器获取了该文档，却在 *token* 端点拒绝了它（`invalid_client`），Hermes 会记录这次拒绝，将其记在 `~/.hermes/mcp-tokens/<server>.cimd-off` 下，并从此对该服务器使用 DCR。

而完全无法获取或校验该文档的服务器，则会在*授权*端点就中止，在任何重定向发生之前。Hermes 在那里观察不到任何信号，因此浏览器会显示 invalid-client 错误，登录会在五分钟后超时。超时消息会点名该文档，并提示使用 `cimd: false`。运行 `hermes mcp login <server>` 会清除已记录的拒绝，让修正后的文档获得再次尝试的机会。

#### 可选的逐服务器键 {#optional-per-server-keys}

```yaml
mcp_servers:
  protected_api:
    url: "https://mcp.example.com/mcp"
    auth: oauth
    oauth:
      client_metadata_url: "https://example.com/my-cimd.json"  # self-hosted document
      cimd: false                                              # force DCR
      user_agent: "My-MCP-Client/1.0"                          # token-request User-Agent
```

`client_metadata_url` 必须是带路径的 HTTPS URL（不能只有 origin，不能带 fragment、userinfo 或 `.`/`..` 路径段），并且返回 `200` 和 `Content-Type: application/json`，**不能重定向**——授权服务器在获取它时被禁止跟随重定向。Hermes 仍会把回调固定在同样的 `27890`–`27894` 范围内，因此自托管的文档必须声明全部十个回环 URI（每个端口各一个 `http://127.0.0.1:<port>/callback` 和 `http://localhost:<port>/callback`），并且其 `client_id` 必须是它自己的 URL。

`user_agent` **只在 token 端点请求**（授权码交换和刷新）中替换 HTTP 库默认的 `User-Agent`——有些授权服务器和 WAF 会在那里拒绝默认的 `python-httpx/...` 值。它从不作用于 MCP 流量或 OAuth 发现，其他 token 请求头也都不可配置。空值或 null 值会被忽略。

## “添加到 Hermes”链接 {#add-to-hermes-link}

MCP 厂商和文档可以提供一键式 **"Add to Hermes"** 按钮，用于打开 Hermes 桌面应用并预填服务器配置，与 Cursor 的 `cursor://anysphere.cursor-deeplink/mcp/install` 方案相对应：

```text
hermes://mcp/install?name=NAME&config=BASE64
```

- `name` —— 服务器名称。必须匹配 `^[A-Za-z0-9._-]{1,64}$`。
- `config` —— 以 **base64url 编码的 JSON** 表示的服务器配置对象（也接受标准 base64）。解码后的 JSON 必须是一个对象，要么带有字符串类型的 `url` 字段（仅限 `http://`/`https://`），要么带有字符串类型的 `command` 字段，并且可以包含上文记录的任何服务器键。超过 32KB 的负载会被拒绝。

示例（JavaScript）：

```js
const config = { url: 'https://mcp.example.com/mcp' }
const link = `hermes://mcp/install?name=example&config=${btoa(JSON.stringify(config))
  .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`
```

打开链接本身永远不会安装任何东西：桌面应用会显示一个确认对话框，列出服务器名称和完整的格式化配置（对基于 `command` 的服务器会额外提醒，因为它们会运行本地进程），用户必须明确确认。已存在的服务器名称永远不会被覆盖——系统会要求用户重命名或取消。
