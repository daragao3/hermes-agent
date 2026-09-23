---
title: 出口凭据注入代理（iron-proxy）
description: "使用 iron-proxy 凭据注入代理，让真实 API 密钥远离 Docker 终端沙箱"
---

# 出口凭据注入代理（iron-proxy）

当 Hermes 在 Docker 终端沙箱中运行你的 agent 时，该沙箱通常持有你真实的上游 API 密钥（`OPENROUTER_API_KEY`、`OPENAI_API_KEY` 等）。沙箱中一个遭受提示注入的 agent 可以执行 `cat ~/.config/openrouter/auth.json` 或 `printenv | grep -i key` 并将它们外泄。

出口代理解决了这个问题：沙箱只持有不透明的**代理令牌**，绝不持有真实密钥。来自沙箱的所有出站流量都会经过宿主机上的本地 [iron-proxy](https://github.com/ironsh/iron-proxy) 守护进程（Apache-2.0，Go 编写），它终止 TLS，并在把请求转发到上游之前将代理令牌替换为真实凭据。即使沙箱被攻破，攻击者拿走的也只是在**已配置的受信任代理边界**之后才有效的令牌——CA 私钥和代理端点的完整性都是该边界的一部分。如果流量可以被重定向到攻击者控制的代理基础设施（例如 CA 私钥被盗或代理端点被劫持），令牌所提供的保证就不再成立。

本版本只将出口代理接入 Docker 后端。Modal、Daytona、SSH 和 Singularity 目前**不会**获得代理环境变量或 CA 挂载。

## 它是什么 {#what-it-is}

- 宿主机上一个受管理的 `iron-proxy` 子进程，按需安装到 `~/.hermes/bin/iron-proxy`
- 位于 `~/.hermes/proxy/ca.crt` 的本地 CA，沙箱信任它，从而让 iron-proxy 可以对 TLS 进行中间人处理并改写请求头
- 位于 `~/.hermes/proxy/proxy.yaml` 的 `proxy.yaml` 配置，列出你允许的上游主机以及密钥转换映射
- 一个 `mappings.json`，记录哪个代理令牌对应哪个真实环境变量

沙箱会获得 `HTTPS_PROXY=http://host.docker.internal:9090`、`HTTP_PROXY=http://host.docker.internal:9091`，以及被设为不透明代理令牌的标准提供商环境变量，例如 `OPENROUTER_API_KEY`。同时还会导出对应的 `HERMES_PROXY_TOKEN_<ENV_NAME>` 别名用于诊断。现有的提供商 SDK 读取常用的环境变量名，在 `Authorization` 中发送代理令牌，而 iron-proxy 的 `secrets` 转换会将其替换为取自宿主机侧守护进程环境的真实值。

## 它不是什么 {#what-it-is-not}

- 它**不是**入站方向的 `hermes proxy` 命令，后者是一个 OAuth 聚合反向代理。命令不同（`hermes egress`），方向也不同。
- 它**不会**位于你的本地终端与提供商之间——只位于沙箱与提供商之间。
- 它**不会**为宿主机进程在进程内发起的 LLM 调用改写凭据。这些调用继续直接使用你 `.env` 中的密钥。威胁模型针对的是*沙箱*，而不是宿主机。

## 快速开始 {#quick-start}

```bash
# 1. 安装 iron-proxy 二进制文件（固定版本，经过 SHA-256 校验）
hermes egress install

# 2. 运行向导：生成 CA，为环境中的每个提供商密钥生成代理令牌，
#    并写入 proxy.yaml。
hermes egress setup

# 3. 启动代理守护进程
hermes egress start

# 4. 检查状态
hermes egress status
```

`hermes egress setup` 会从你的环境中发现提供商密钥。如果你的密钥只存在于 `~/.hermes/.env` 中（没有导出到 shell），setup 会自动读取该文件——你不必先 `export` 它们。

以后当你重新运行 `setup` 时（新增允许列表主机、轮换令牌、切换凭据来源），它会停止正在运行的守护进程，因为守护进程的配置保存在内存中，然后**主动提出为你重启它**，让改动立即生效。在 tty 上它会询问；传入 `--restart` 始终重启，传入 `--no-restart` 则保持停止状态。在其他任何时候要应用改动，`hermes egress restart` 就是一条"先停止再启动"的命令。

运行之后，Docker 终端后端会自动：

- 将 `~/.hermes/proxy/ca.crt` 挂载到沙箱中的 `/etc/ssl/certs/hermes-egress-ca.crt`
- 设置 `HTTPS_PROXY`、`HTTP_PROXY`、`REQUESTS_CA_BUNDLE`、`SSL_CERT_FILE`、`CURL_CA_BUNDLE`、`NODE_EXTRA_CA_CERTS`，使所有常见的 HTTP 运行时都经过代理并信任该 CA
- 设置 `NODE_OPTIONS=--use-openssl-ca`（追加到你在 `docker_env.NODE_OPTIONS` 中已有的值之后），使 Node.js 走由其他 CA 证书包变量控制的 OpenSSL 证书存储——剩余的缺口见下文的 [Node.js 非对称 CA 注意事项](#nodejs-asymmetric-ca-caveat)
- 添加 `--add-host=host.docker.internal:host-gateway`，使沙箱在 Linux 上能访问宿主机侧的代理（在 macOS/Windows 上 Docker Desktop 会自动处理）
- 以标准提供商环境变量名（例如 `OPENROUTER_API_KEY`）导出代理令牌，并为每个生成的映射额外导出一个 `HERMES_PROXY_TOKEN_<ENV_NAME>` 诊断别名

## 配置 {#configuration}

完整配置位于 `~/.hermes/config.yaml` 的 `proxy:` 部分下。默认值以内联注释说明；所有项都是可选的。

```yaml
proxy:
  # 总开关。为 false 时该功能完全不起作用——不下载
  # 二进制文件，不添加 docker 挂载，不启动子进程。
  enabled: false

  # 隧道监听端口。沙箱访问 http://host.docker.internal:<port>。
  tunnel_port: 9090

  # 首次使用时自动下载固定版本的 iron-proxy 二进制文件。
  auto_install: true

  # iron-proxy 在出口时从哪里查找真实的上游密钥。
  #   env       — 进程环境（默认）。代理启动时你的 ~/.hermes/.env
  #               中的内容即为唯一可信来源。
  #   bitwarden — 每次代理重启时从 Bitwarden Secrets Manager 重新
  #               获取。在 BW Web 应用中轮换即可生效，无需
  #               改动 .env。需要 `secrets.bitwarden.enabled: true`。
  credential_source: env

  # 为 true（默认）时，如果代理已启用但未运行，Docker 后端
  # 会拒绝启动沙箱。设为 false 则在代理不可用时回退到
  # 旧的"沙箱内持有真实凭据"的模式。
  enforce_on_docker: true

  # 当 `credential_source: bitwarden` 但缺少 BWS 访问令牌 /
  # project_id，或者 bws 获取对已映射的提供商没有返回值时，
  # 守护进程默认会报错（符合"我要求了轮换——不要悄悄使用
  # 过期的环境变量值"的本意）。设为 true 可重新启用旧的
  # 宿主机环境变量回退——适用于迁移场景：你想开始切换到
  # BW 模式，但还没有接好所有密钥。
  allow_env_fallback: false

  # 应用于出站流量的 SSRF 拒绝列表。省略 / 保持 null 则
  # 使用安全的默认值：回环地址（v4 + v6）、链路本地地址（包括
  # 169.254.169.254 上的云元数据 IP）、RFC1918、IPv6 ULA、IPv4 映射的 v6、
  # CGNAT，以及 RFC2544 基准测试地址段。显式设为 `[]`
  # 则完全退出（仅在封闭测试中才合理）。
  upstream_deny_cidrs: null

  # 在内置默认值之外额外允许的上游主机。
  # 支持通配符（`*.foo.com`）。默认值涵盖 OpenRouter、
  # OpenAI、Anthropic、Google、xAI、Mistral、Groq、Together、DeepSeek
  # 以及 Nous Research。
  extra_allowed_hosts: []
```

### 默认允许的上游主机 {#default-allowed-upstream-hosts}

```
openrouter.ai           *.openrouter.ai
api.openai.com          api.anthropic.com
generativelanguage.googleapis.com
api.x.ai                api.mistral.ai
api.groq.com            api.together.xyz
api.deepseek.com        inference.nousresearch.com
```

如果你的 agent 需要访问不在列表中的上游——自托管的推理端点、额外的云端 LLM、某个 MCP 服务器——将其添加到 `proxy.extra_allowed_hosts`。通配符针对完整主机名进行匹配（`*.example.com` 匹配 `api.example.com` 和 `staging.example.com`，但不匹配 `example.com` 本身）。

### 默认的 SSRF 拒绝 CIDR {#default-ssrf-deny-cidrs}

无论允许列表如何都会生效。iron-proxy 在网络边界处拒绝这些地址段，因此通过允许列表中的主机名发起的 DNS 重绑定攻击无法触及 IMDS 或你的内部网络：

| CIDR | 用途 |
|---|---|
| `127.0.0.0/8`, `::1/128` | 回环地址（v4 + v6） |
| `169.254.0.0/16`, `fe80::/10` | 链路本地地址——**包括位于 `169.254.169.254` 的 AWS / GCP / Azure IMDS** |
| `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | RFC1918 |
| `fc00::/7` | IPv6 ULA |
| `::ffff:0:0/96` | IPv4 映射的 IPv6——堵住双栈 IMDS 绕过 |
| `100.64.0.0/10` | RFC6598 CGNAT（AWS VPC、K8s pod 网络会使用） |
| `198.18.0.0/15` | RFC2544 基准测试地址段 |

如需覆盖：将 `proxy.upstream_deny_cidrs` 设为你自己的列表。如需完全退出（例如封闭测试需要访问回环地址上的上游）：将其设为空列表 `[]`。

### 绑定策略 {#bind-policy}

代理绝不绑定 `0.0.0.0`。默认绑定地址因平台而异，因为 iron-proxy v0.39 只支持**每个守护进程一个绑定地址**：

- **Linux：** docker 网桥网关（默认为 `172.17.0.1:<tunnel_port>`）。容器通过 `host.docker.internal` 访问代理，而 `--add-host=host.docker.internal:host-gateway` 恰好将其解析为这个网桥网关 IP——仅绑定回环地址的话，沙箱内部将无法访问。网桥 IP 是宿主机 `docker0` 接口上的地址，因此不会暴露到局域网；默认网桥网络上的其他容器**可以**访问它，但请求仍需要一个已生成的代理令牌以及一个在允许列表中的上游。如果检测不到 docker 网桥（docker 未安装/未运行），绑定会回退到回环地址并给出警告。
- **macOS / Windows Docker Desktop：** 回环地址（`127.0.0.1:<tunnel_port>`）。Desktop 的 VPNkit 会把 `host.docker.internal` 路由到宿主机，因此容器可以访问回环地址，这也是暴露面最小的选择。

持有泄露代理令牌的局域网对端无法使用该代理——两种绑定地址都无法从外部网络访问。

我们还固定了 `metrics.listen: 127.0.0.1:0`，使守护进程内置的指标服务器获得一个临时的回环端口，而不是默认的 `:9090`——否则它会与 `tunnel_port: 9090` 争夺同一个套接字，守护进程将以 "address already in use" 拒绝启动。注意 `:0` 临时端口每次启动都是随机的，且不会在任何地方显示，因此在该固定配置下指标实际上处于禁用状态。

即使 PATH 中靠前位置的恶意 `ip` 垫片能够把一个非私有 IPv4 注入为网桥地址（`0.0.0.0`、公网地址、组播、链路本地地址等），回环回退依然适用——我们绝不绑定任何无法通过 `ipaddress.IPv4Address` + `is_*` 检查验证的地址。

## 已覆盖的认证方案 {#covered-auth-schemes}

`secrets` 转换会在匹配位置中出现代理令牌的任何地方进行替换——而且它匹配的不只是 `Authorization: Bearer`：

| 提供商 | 环境变量 | 替换位置 |
|---|---|---|
| OpenRouter、OpenAI、Groq、Together、DeepSeek、Mistral、xAI、Nous | `*_API_KEY` | `Authorization` 请求头 |
| Anthropic 原生 | `ANTHROPIC_API_KEY` | `x-api-key` + `Authorization` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | `api-key` + `Authorization`（`*.openai.azure.com`、`*.cognitiveservices.azure.com`、`*.services.ai.azure.com`） |
| Google AI Studio（Gemini） | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | `x-goog-api-key` 请求头或 `?key=` 查询参数 |

`GEMINI_API_KEY` 和 `GOOGLE_API_KEY` 被视为同一个凭据：只生成一个代理令牌，并以**两个**名称注入沙箱，宿主机环境中存在任意一个名称即可满足发现条件。

## 未覆盖的提供商 {#uncovered-providers}

涉及请求签名或 SDK 生成 OAuth 的认证方案无法通过静态的请求头替换来处理——如果存在它们的环境变量，沙箱就会持有这些提供商的**真实凭据**，出口隔离保证对它们而言是不完整的：

| 环境变量 | 提供商 | 原因 |
|---|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS Bedrock / SageMaker | SigV4 签名请求 |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCP Vertex AI | 从服务账号文件生成 OAuth |

大多数开发者笔记本上都会因为无关的工具（terraform、gcloud、aws CLI、ECR push）而存在这些环境变量。它们会在向导和 `hermes egress status` 中以警告形式显示，但绝不会阻止代理启动。如果你不在沙箱中使用这些提供商，`unset` 这些变量即可清除警告。

## Bitwarden 集成 {#bitwarden-integration}

如果你已经通过 [`hermes secrets bitwarden setup`](../secrets/bitwarden) 使用 Bitwarden Secrets Manager，出口代理可以从那里拉取真实凭据，而不是从 `os.environ`：

```bash
hermes egress setup --from-bitwarden
```

这会设置 `proxy.credential_source: bitwarden`，并从你的 BW 项目中发现提供商环境变量名。

### 轮换语义 {#rotation-semantics}

当 `credential_source: bitwarden` 时，iron-proxy 守护进程**每次启动时**都会通过 `bws secret list <project_id>` 从 BWS 重新获取密钥。因此轮换流程是：

1. 在 Bitwarden Web 应用中轮换一个密钥。
2. 在宿主机上执行 `hermes egress stop && hermes egress start`。
3. 此后启动的沙箱会把代理令牌替换为新值。

无需编辑 `.env`。无需在宿主机上重启 Hermes。代理守护进程是唯一接触新值的组件——你的宿主机进程和 `os.environ` 均不受影响。

### 启动时大声失败 {#fail-loud-at-start}

当 `credential_source: bitwarden` 时，`hermes egress start` 会在向导层进行预检查，**并且** `_build_proxy_subprocess_env` 会在守护进程层再次检查：

- BWS 访问令牌环境变量未设置 → 拒绝启动，并提示先 `unset` 再重新运行，或运行 `hermes egress setup --no-bitwarden` 切换回 env 模式
- `secrets.bitwarden.project_id` 为空 → 拒绝启动，并提示运行 `hermes secrets bitwarden setup`
- `bws secret list` 对一个或多个已映射的提供商没有返回值 → 拒绝启动，并列出缺失的名称

这是有意为之。在 BW 模式下回退到宿主机环境变量，恰恰会重新引入 BW 路径本来要消除的过期凭据问题（运维人员选择 BW 是为了获得轮换保证；悄无声息的回退会破坏这一保证）。

`proxy.allow_env_fallback: true` 配置标志可以在迁移场景中重新启用旧的"BWS 不可达时悄悄回退到宿主机环境变量"行为。当你正在把密钥逐个迁移到 BW、并希望守护进程使用当前可用的值启动时使用它。

### 切换凭据来源 {#switching-credential-source}

| 从 | 到 | 命令 |
|---|---|---|
| env | bitwarden | `hermes egress setup --from-bitwarden` |
| bitwarden | env | `hermes egress setup --no-bitwarden` |

**在不带任一标志的情况下重新运行 `hermes egress setup` 会保留现有的 `credential_source`**——向导拒绝悄悄地把你降级回 env。这一点很重要，因为一旦你配置了 bitwarden 模式，轮换保证就是你所选择的；你必须明确表示"我想要回到 env"才能更改它。

## 斜杠命令 {#slash-commands}

CLI 子命令树：

```
hermes egress install                  # download the pinned iron-proxy binary
hermes egress install --force          # re-download even if a managed copy exists

hermes egress setup                    # interactive wizard
hermes egress setup --tunnel-port N    # override the tunnel listener port
hermes egress setup --from-bitwarden   # use BWS as credential source (fail-loud)
hermes egress setup --no-bitwarden     # explicitly switch back to env mode
hermes egress setup --rotate-tokens    # mint fresh tokens for every provider
                                       #   (default preserves existing)

hermes egress start                    # spawn the managed proxy daemon
hermes egress stop                     # SIGTERM (then SIGKILL after 5s grace)
hermes egress restart                  # stop (if running) then start — needed when
                                       #   upstream SECRETS change (rotation, new provider)
hermes egress reload                   # hot-reload the ruleset from proxy.yaml via the
                                       #   management API — no restart, no dropped
                                       #   connections (allowlist / mapping edits)

hermes egress status                   # binary + config + pid + listening state + mappings
hermes egress status --show-tokens     # print proxy tokens in full
                                       #   (default: redacted prefix + suffix only)

hermes egress disable                  # flip proxy.enabled = false
                                       #   (does not stop a running proxy)

hermes egress config                   # print the path to proxy.yaml for debugging
```

### 令牌轮换 {#token-rotation}

默认情况下，`hermes egress setup` 会为已有令牌的提供商**保留**代理令牌。添加新的提供商只会为新提供商生成新令牌；现有令牌保持不变。这样可以避免你重新运行向导时让正在运行的沙箱遭遇 401。

`--rotate-tokens` 会轮换所有令牌：

```bash
hermes egress setup --rotate-tokens
```

当已存在令牌**且** stdin 是 tty 时，向导会提示确认：

```
⚠  --rotate-tokens will invalidate proxy tokens in every running
   Hermes sandbox.  They will start 401-ing against upstreams until restarted.
Type 'rotate' to confirm:
```

非 tty 调用（CI、脚本）会跳过提示——该标志被视为有意为之。在任何覆盖操作之前，当前的 `mappings.json` 会被复制为一个带时间戳的同级文件，以便手动恢复：

```
backup: ~/.hermes/proxy/mappings.json.rotated-20260524T143012
```

`hermes egress setup` 在重写配置或令牌映射时会停止正在运行的守护进程，因为守护进程会在内存中保留旧的 YAML。执行 `--rotate-tokens` 之后：

```bash
hermes egress start
```

已经在运行的容器持有旧令牌，需要重启才能获取新令牌。新的持久化 Docker 容器会带有一个出口状态标签，因此 Hermes 不会为新会话复用启用出口代理之前或令牌轮换之前的容器。

## 状态目录布局 {#state-directory-layout}

iron-proxy 维护的所有内容都位于 `~/.hermes/proxy/` 中：

| 路径 | 模式 | 用途 |
|---|---|---|
| `~/.hermes/proxy/`（目录） | `0o700` | 仅归你所有且仅你可遍历 |
| `ca.crt` | `0o644` | 分发到沙箱中的公开 CA 证书 |
| `ca.key` | `0o600` | CA 签名密钥——绝不离开宿主机 |
| `proxy.yaml` | `0o600` | iron-proxy 配置；每次 `setup` 都会重写 |
| `mappings.json` | `0o600` | 沙箱代理令牌 → 上游环境变量 |
| `mappings.json.rotated-*` | `0o600` | 由 `--rotate-tokens` 创建的备份 |
| `iron-proxy.pid` | `0o600` | 正在运行的守护进程的 PID |
| `iron-proxy.nonce` | `0o600` | 每次启动生成的 nonce，用于 PID 复用防御 |
| `iron-proxy.log` | `0o600` | 守护进程的 stdout/stderr——**在 v0.39 上包含逐请求记录** |
| `audit.log` | `0o600` | 为未来二进制版本中专用的逐请求审计流预留；预先创建，以便上游接入时隐私契约依然成立 |

CA 私钥是最敏感的文件。它从第一个字节起就以 `0o600` 创建（不存在 umask 时间窗口的 TOCTOU），并使用 `O_NOFOLLOW`，使同一 uid 的攻击者无法通过预先放置的符号链接重定向它。pidfile、nonce 文件、守护进程日志和审计日志也采用同样的处理。

### iron-proxy v0.39 上的日志 {#logging-on-iron-proxy-v039}

在当前固定的二进制版本（**v0.39.0**）上，iron-proxy 将**所有**输出——守护进程级诊断信息**以及**逐请求记录——写入 **`~/.hermes/proxy/iron-proxy.log`**。v0.39 的 `config.Log` 结构体没有单独的 `audit_path` 字段，因此我们无法在该版本上把逐请求记录路由到专用的日志流。

我们仍然以 `0o600` 和 `O_NOFOLLOW` 预先创建 `~/.hermes/proxy/audit.log`，原因是：

1. 它为未来的版本升级预留了路径：当固定版本升级到支持 `log.audit_path` 的版本时，逐请求记录将开始写入该文件，无需运维侧重新配置。**在那之前该文件始终为 0 字节——暂时不要把监控、告警或取证工具指向它。** 目前一切都请使用 `iron-proxy.log`。
2. "从第一个字节起即为 0o600"的保证可以防范上游修复落地的那一天：届时 v0.40+ 若发现该文件不存在，会以其默认 umask 创建它。

在该版本升级落地之前，请将 `iron-proxy.log` 视为以下两类受众的唯一可信来源：

- 守护进程级事件（启动横幅、绑定错误、关闭原因、转换错误）。面向运维 + 故障排查。
- 逐请求记录（到允许列表中上游的 CONNECT、触发的密钥替换、允许列表拒绝）。面向取证 + 合规。

两个文件在重启之间都是追加写入的。如果你关心长期运行宿主机上的磁盘占用，请用 logrotate 轮转它们。

## 工作原理 {#how-it-works}

```
┌──────────────┐                ┌──────────────┐                ┌─────────────┐
│ Docker       │ CONNECT /     │ iron-proxy    │ HTTPS w/       │ OpenRouter  │
│ sandbox      ├──────────────▶│ (host:9090)   ├───────────────▶│ / OpenAI /  │
│              │ HTTP forward  │               │ real API key   │ Anthropic …  │
│ has:         │ w/ proxy tok  │ mints leaf    │                │             │
│ - proxy tok  │ in Auth hdr   │ cert from CA  │                │             │
│ - CA cert    │               │ matches token │                │             │
│ - HTTPS_PROXY│               │ swaps secret  │                │             │
└──────────────┘               └──────────────┘                └─────────────┘
                                       │
                                       │ daemon + per-request log (combined on v0.39)
                                       ▼
                              ~/.hermes/proxy/iron-proxy.log
                              (~/.hermes/proxy/audit.log reserved for v0.40+ split stream)
```

1. 沙箱发起一个 HTTPS 请求，例如 `POST https://openrouter.ai/v1/chat/completions`，带有 `Authorization: Bearer hermes-proxy-openrouter-…`（代理令牌，而不是真实密钥）。
2. 由于设置了 `HTTPS_PROXY`，请求以 CONNECT 隧道的形式发往 iron-proxy。
3. iron-proxy 检查允许列表。`openrouter.ai` 在允许范围内。
4. iron-proxy 为 `openrouter.ai` 生成一张由我们的 CA 签名的叶证书，终止 TLS 连接，并检查请求。
5. `secrets` 转换匹配到 `Authorization` 请求头中的代理令牌字符串，并将其替换为取自 iron-proxy 自身环境的真实 `OPENROUTER_API_KEY` 值。
6. 请求被重新加密并转发到 OpenRouter。
7. 在 v0.39 上，请求会被记录到 `~/.hermes/proxy/iron-proxy.log`。当固定的二进制版本支持拆分日志流（v0.40+）时，逐请求记录将写入 `~/.hermes/proxy/audit.log`，而守护进程级诊断信息将保留在 `iron-proxy.log` 中。见 [iron-proxy v0.39 上的日志](#logging-on-iron-proxy-v039)。

发往不在允许列表中的主机的请求（例如 `https://attacker.example.com/leak?key=...`）会在任何字节离开宿主机之前被以 HTTP 403 拒绝。该拒绝会连同上游主机和来源沙箱一起记录在 `iron-proxy.log` 中。

### 将 CA 分发到沙箱 {#ca-distribution-into-the-sandbox}

当 Docker 后端在 `proxy.enabled: true` 且守护进程正在监听的情况下启动容器时，会向 `docker run` 添加以下参数：

| 参数 | 用途 |
|---|---|
| `-v ~/.hermes/proxy/ca.crt:/etc/ssl/certs/hermes-egress-ca.crt:ro` | 以只读方式挂载 CA |
| `-e HTTPS_PROXY=http://host.docker.internal:9090` | Python httpx / curl / go 默认传输层 / Node fetch |
| `-e HTTP_PROXY=http://host.docker.internal:9091` | curl + wget 的明文 HTTP——明文 HTTP 转发监听器位于 `tunnel_port + 1` |
| `-e NO_PROXY=127.0.0.1,localhost,::1` | 沙箱内的回环开发服务器绕过代理 |
| `-e REQUESTS_CA_BUNDLE=…ca.crt` | Python `requests` |
| `-e SSL_CERT_FILE=…ca.crt` | Python `ssl` 模块 / OpenSSL——**替换**系统证书存储 |
| `-e CURL_CA_BUNDLE=…ca.crt` | curl——**替换**系统证书存储 |
| `-e NODE_EXTRA_CA_CERTS=…ca.crt` | Node.js——**添加**到系统证书存储 |
| `-e NODE_OPTIONS="<your value> --use-openssl-ca"` | Node.js——走 OpenSSL 证书存储（追加方式；你的 `--max-old-space-size` 等设置会被保留） |
| `-e HERMES_EGRESS_PROXY=1` | agent 可读取的哨兵变量，用于得知自身处于代理感知状态 |
| `-e OPENROUTER_API_KEY=<proxy-token>` | 标准提供商环境变量名接收代理令牌，使现有 SDK 继续正常工作 |
| `-e HERMES_PROXY_TOKEN_<NAME>=…` | 每个映射的诊断别名；值与标准提供商环境变量相同 |
| `--add-host=host.docker.internal:host-gateway` | 仅限 Linux；Docker Desktop 会自动映射 |

#### Node.js 非对称 CA 注意事项 {#nodejs-asymmetric-ca-caveat}

`REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` / `CURL_CA_BUNDLE` 会**替换**沙箱内的系统 CA 存储。`NODE_EXTRA_CA_CERTS` 则是**添加**到其中。沙箱内的 Node.js 进程理论上可以通过打开一个原始 `net.Socket` 并自行发起 TLS 握手来绕过代理——系统 CA 存储仍然会信任真实的上游证书，因此在 Python / curl 会验证失败的情况下，该请求却能成功。

`NODE_OPTIONS=--use-openssl-ca` 会追加到你在 `docker_env.NODE_OPTIONS` 中已有的值之后。这会强制 Node 使用由 `SSL_CERT_FILE` 控制的 OpenSSL 证书存储，从而缩小这种不对称。它**不能**覆盖显式向 `tls.connect()` 或 `https.request()` 传入自己 `ca` 选项的代码，但堵住了容易利用的情况。

这是 v1 的已知限制。请关注 [github.com/ironsh/iron-proxy/issues](https://github.com/ironsh/iron-proxy/issues) 以获取上游的解决方案；在此期间，不要在你依赖出口隔离的沙箱中运行会打开原始套接字的不受信任 Node 代码。

### docker\_env 冲突 {#docker_env-collisions}

如果你在 `docker_env:` 配置块中设置了控制代理的环境变量（少见但可能），在设置了 `enforce_on_docker: true` 时，Hermes 会拒绝启动沙箱。这同时包括：

- 出口控制变量：`HTTPS_PROXY`、`HTTP_PROXY`、`NO_PROXY`、`REQUESTS_CA_BUNDLE`、`SSL_CERT_FILE`、`CURL_CA_BUNDLE`、`NODE_EXTRA_CA_CERTS`
- 真实提供商环境变量：`mappings.json` 中的每个名称（例如 `OPENROUTER_API_KEY`、`OPENAI_API_KEY`）

错误示例：

```
docker_env in config.yaml overrides egress-proxy variables
['HTTPS_PROXY', 'OPENROUTER_API_KEY']; enforce_on_docker is enabled.
Remove these keys from docker_env or disable enforce_on_docker to
opt out of egress isolation.
```

在 `enforce_on_docker: false` 时，同样的情况会以警告形式出现，并以你的 `docker_env` 值为准——适用于迁移或测试，但这意味着你明确**退出**了隔离保证。

## PID 与 nonce 防御 {#pid-and-nonce-defense}

守护进程的 pidfile 以 `O_EXCL` + `O_NOFOLLOW` + 所有权检查的方式写入。并发的 `hermes egress start` 调用会产生以下两种结果之一：

- 现有 pidfile 指向一个存活的 iron-proxy → 第二次启动会以 "another start in progress" 拒绝，并提示运行 `hermes egress stop`
- 现有 pidfile 已过期（守护进程崩溃）→ 第二次启动会删除它并重试一次

除此之外，每次 `start_proxy` 都会在两个地方植入一个新的随机 nonce：

- 守护进程环境中的 `HERMES_IRON_PROXY_NONCE=<nonce>`
- `~/.hermes/proxy/iron-proxy.nonce`（pidfile 的 0o600 同级文件）

当 `hermes egress stop`（或任何其他 `_pid_alive` 检查）想要确认某个 PID 仍然指向*我们的*守护进程——而不是在 iron-proxy 崩溃后被分配到同一 PID 的无关进程——时，它会读取 `/proc/<pid>/environ` 并查找该 nonce。磁盘上的副本使这一机制能够跨 CLI 调用工作（内存中的 `_proxy_nonce` 是进程级的，每次 `hermes` 调用都会重置）。

如果 nonce 检查失败，代码会回退为将 `argv[0]` 的基本名称与 `iron-proxy` 进行匹配。`stop_proxy` 还会在 SIGTERM 之前捕获 `/proc/<pid>/stat` 中的 starttime，并在 5 秒宽限期结束后重新验证——如果 starttime 发生漂移，说明该 PID 在等待期间被复用，SIGKILL 会被抑制并给出警告。

## 安全模型 {#security-model}

**它能防范：**

- Docker 沙箱中遭受提示注入的 agent 读取 `printenv` / 凭据文件并外泄真实密钥。
- 沙箱中被攻破的依赖向任意主机回传数据——默认拒绝的允许列表会阻止未知目的地。
- agent 访问云元数据端点（`169.254.169.254`）——iron-proxy 默认通过 `upstream_deny_cidrs` 拒绝这些地址，包括 IPv4 映射的 v6 形式 `::ffff:169.254.169.254`。
- 通过允许列表中的主机名进行 DNS 重绑定以指向私有 IP——拒绝 CIDR 在连接时检查，而不是在允许列表匹配时检查。
- 同一 uid 的本地进程读取 iron-proxy 守护进程的环境以窃取密钥——只有映射引用的环境变量名会被转发，而不是完整的宿主机环境。
- 持有泄露沙箱代理令牌的局域网对端消耗你的 API 配额——代理绑定在 docker 网桥网关（Linux）或回环地址（Docker Desktop）上，绝不绑定 `0.0.0.0`，因此无法从外部网络访问。

**它不能防范：**

- 被攻破的宿主机进程。如果 agent 进程本身被攻破，宿主机 `~/.hermes/.env` 中的真实密钥无论如何都会暴露。这是针对*沙箱*被攻破的纵深防御功能，而不是针对宿主机被攻破。
- **受信任代理边界本身的失守。** 令牌替换保证的前提是：沙箱信任挂载的 CA 证书（`/etc/ssl/certs/hermes-egress-ca.crt`），并且流量确实到达了*我们的* iron-proxy。如果 CA 私钥被盗，或沙箱出口流量被重定向到攻击者控制的代理基础设施，中间人攻击者就可以出示有效的叶证书，代理令牌也就不再构成有意义的边界（参见 [MITRE ATT&CK T1588.004](https://attack.mitre.org/techniques/T1588/004/)——获取 TLS 证书材料以实施 AiTM）。请相应地保护好 CA 密钥（它是 `0600`，仅存在于宿主机）和代理端点。
- 通过原始套接字绕过 `HTTPS_PROXY` 的沙箱进程。代理无法拦截不经过它的流量。Node.js 通过 `NODE_OPTIONS=--use-openssl-ca` 得到了部分缓解（见上文注意事项）。
- 显式挂载到 Docker 中的凭据文件（`terminal.credential_files` 或 skill 注册的挂载）。出口代理保护的是提供商环境变量；它不会检查任意挂载的文件。不要把真实的提供商凭据挂载到启用了强制出口的沙箱中。
- 通过允许列表中的主机外泄数据。如果允许 `api.openai.com`，agent 可以把外泄数据嵌入发往该主机的请求体中。守护进程日志会记录该请求的发生，但无法阻止它。
- 未覆盖的提供商（AWS Bedrock SigV4、GCP Vertex 服务账号 OAuth）。它们的环境变量保留在沙箱中；如果你启用它们，这些凭据会完全绕过代理。见 [未覆盖的提供商](#uncovered-providers)。
- iron-proxy 内存中密钥的清零。Go 二进制文件会在进程内存中保存替换进来的真实凭据；同一 uid 的攻击者通过 core dump 或读取 `/proc/<pid>/mem` 就能获取它们。这超出了本层的范围。

## 故障模式 {#failure-modes}

- **二进制文件未安装，`auto_install: true`**——首次运行 `hermes egress setup` 或 `hermes egress start` 时会下载它。会对照上游的 `checksums.txt` 进行 SHA-256 校验。
- **二进制文件未安装，`auto_install: false`**——`start` 会失败，并给出指向手动安装的清晰提示。
- **`enabled: true` 但代理未运行**——在 `enforce_on_docker: true`（默认）时，Docker 沙箱创建会拒绝启动并给出解释性错误。在 `enforce_on_docker: false` 时，会回退到使用真实凭据直接出站，并记录一条警告。
- **端口冲突**——iron-proxy 会立即退出；`hermes egress start` 会报告最后 20 行日志，并以非零退出码失败。
- **上游主机被拒绝**——沙箱从代理收到 HTTP 403，响应体会说明哪个主机未被允许。agent 会看到该错误并进行报告。
- **请求了云元数据 IP（169.254.169.254）**——无论允许列表如何，都会被 `upstream_deny_cidrs` 拒绝。
- **`docker_env` 与控制代理的变量冲突（强制模式开启）**——沙箱创建会拒绝，并列出冲突键的名称。
- **`docker_forward_env` 试图转发受保护的提供商密钥（强制模式开启）**——沙箱创建会拒绝；从 `docker_forward_env` 中移除该键，或通过 `proxy.enforce_on_docker: false` 退出。
- **`docker_extra_args` 覆盖了代理的环境变量/网络控制（强制模式开启）**——沙箱创建会拒绝；用户提供的 `-e HTTPS_PROXY=...`、`--env-file` 或 `--network` 参数在 Hermes 生成的参数之后运行，可能绕过出口控制。
- **在 `credential_source: bitwarden` 下缺少 BWS 访问令牌**——`hermes egress start` 会拒绝启动，并以 `--no-bitwarden` 作为恢复提示。
- **iron-proxy 在 5 秒内没有完成绑定**——进程被终止，pidfile 被删除，错误信息会指出端口以及 `iron-proxy.log` 的末尾内容。
- **并发的 `hermes egress start` 调用**——如果第一个调用的守护进程已启动，第二个调用会以 "another start in progress" 拒绝；否则第二个调用会删除过期的 pidfile 并继续。

## 故障排查 {#troubleshooting}

### "Refusing to start: BWS_ACCESS_TOKEN is not set" {#refusing-to-start-bws_access_token-is-not-set}

你启用了 `credential_source: bitwarden`，但你的 shell 中没有访问令牌环境变量。可以：

```bash
export BWS_ACCESS_TOKEN=…   # 一次性设置
hermes egress start
```

或者把它移到 `~/.hermes/.env` 中。或者切换回 env 模式：

```bash
hermes egress setup --no-bitwarden
```

### "iron-proxy exited immediately" {#iron-proxy-exited-immediately}

查看 `~/.hermes/proxy/iron-proxy.log` 的最后 20 行。常见原因：

- 端口已被占用 → 修改 `proxy.tunnel_port`，或终止占用 9090 的其他进程
- `proxy.yaml` 无效 → 运行 `hermes egress setup` 重新生成
- CA 证书 / 密钥权限错误 → `chmod 0o600 ~/.hermes/proxy/ca.key`

### "iron-proxy did not bind \<bind-host\>:9090 within 5s" {#iron-proxy-did-not-bind-bind-host9090-within-5s}

守护进程已启动，但始终没有绑定监听器。这通常意味着二进制文件卡住了，或者在启动时做了某些开销很大的事情。检查 `~/.hermes/proxy/iron-proxy.log`。孤儿进程会被自动终止，pidfile 也会被清理，因此你只需重试 `hermes egress start`。

### 沙箱连接代理超时（Linux） {#sandbox-times-out-connecting-to-the-proxy-linux}

容器将 `host.docker.internal` 解析为 docker 网桥网关，代理也绑定在那里，但宿主机防火墙（通常是 INPUT 默认拒绝的 `ufw`）丢弃了 `docker0` 上容器→宿主机的流量。从容器中验证：

```bash
docker run --rm --add-host host.docker.internal:host-gateway busybox \
  nc -zv -w 3 host.docker.internal 9090
```

如果在 `hermes egress status` 显示 `listening` 的情况下该命令超时，请在防火墙中放行网桥子网，例如对于 ufw：

```bash
sudo ufw allow in on docker0 to any port 9090 proto tcp
sudo ufw allow in on docker0 to any port 9091 proto tcp
```

（9091 = 位于 `tunnel_port + 1` 的明文 HTTP 转发监听器。）

### 沙箱从代理收到 `HTTP 403` {#sandbox-sees-http-403-from-the-proxy}

沙箱中的 agent 尝试访问一个不在 `proxy.extra_allowed_hosts` 中的主机。403 响应体会说明是哪个主机。如果你想允许它，将其添加到配置中：

```yaml
proxy:
  extra_allowed_hosts:
    - api.example.com
    - "*.staging.example.com"
```

然后运行 `hermes egress setup`（以重新生成 `proxy.yaml`）以及 `hermes egress stop && hermes egress start`。

### 沙箱出现 SSL 验证错误 {#sandbox-sees-ssl-verification-errors}

要么 CA 没有挂载到沙箱中（少见；当 `proxy.enabled: true` 时 docker 后端会自动挂载），要么你镜像中的 HTTP 客户端读取的是非标准的环境变量。

```bash
# 在沙箱内：
cat /etc/ssl/certs/hermes-egress-ca.crt | head -1
# 应输出：-----BEGIN CERTIFICATE-----
env | grep -E "^(REQUESTS|CURL|SSL|NODE).*CA"
# 应列出全部四个 CA 证书包环境变量，且都指向 /etc/ssl/certs/hermes-egress-ca.crt
```

如果证书不在那里，检查 `proxy.enabled: true` **且** `hermes egress status` 显示 `Listening yes`。如果缺少环境变量，沙箱镜像可能运行了一个会剥离它们的 entrypoint——检查你的 `docker_env` 配置。

### 沙箱从上游收到 `HTTP 401` {#sandbox-sees-http-401-from-upstreams}

两个常见原因：

1. **重新设置时令牌被覆盖。** 你运行了 `hermes egress setup --rotate-tokens`（或以其他方式轮换了令牌），而正在运行的沙箱仍持有旧令牌。重启这些沙箱。
2. **Bitwarden 刷新悄无声息地失败了。** 在新的大声失败行为下不应发生这种情况，但如果你设置了 `proxy.allow_env_fallback: true`，守护进程可能是以过期的环境变量值启动的。检查守护进程的环境（`/proc/<iron-proxy-pid>/environ`）中是否有预期的 `OPENROUTER_API_KEY` 等。

### 父进程退出后出现 "Address in use" {#address-in-use-after-the-parent-process-died}

父 Hermes 进程在 `hermes egress start` 期间退出了（在监听探测期间按下 Ctrl-C、OOM、panic）。新的修复逻辑会在 `Popen` 之后立即写入 pidfile，因此孤儿进程是可以恢复的：

```bash
hermes egress stop   # 通过 pidfile 找到孤儿进程并将其终止
hermes egress start
```

如果 `hermes egress stop` 提示 "iron-proxy was not running"，但你仍能在 `ps` 中看到该守护进程，说明 pidfile 已经不同步。手动恢复：

```bash
pkill -TERM iron-proxy
rm -f ~/.hermes/proxy/iron-proxy.pid ~/.hermes/proxy/iron-proxy.nonce
hermes egress start
```

### 检查逐请求行为 {#inspecting-per-request-behavior}

在固定的二进制版本（**v0.39**）上，守护进程级事件和逐请求记录都写入 `~/.hermes/proxy/iron-proxy.log`。格式为按行分隔的 JSON。用 grep 查找特定上游：

```bash
grep '"upstream":"openrouter.ai"' ~/.hermes/proxy/iron-proxy.log | tail -20
```

或者实时查看：

```bash
tail -f ~/.hermes/proxy/iron-proxy.log | jq
```

当固定版本升级到 v0.40+（新增 `log.audit_path`）时，逐请求记录将迁移到 `~/.hermes/proxy/audit.log`，而 `iron-proxy.log` 将只保存守护进程级事件。在该升级之前，`audit.log` 只是一个空的占位文件（以 `0o600` 预先创建，使未来的守护进程继承严格的权限）——现在请将你的 logrotate / 监控工具接到 `iron-proxy.log` 上，并计划在版本升级后再加入 `audit.log`。

## 限制（v1） {#limitations-v1}

- 仅支持 Docker 后端。Modal、Daytona 和 SSH 的接入将在单独的 PR 中跟进。
- 使用基于签名认证的提供商（AWS SigV4、GCP 服务账号 OAuth）会完全绕过代理——见 [未覆盖的提供商](#uncovered-providers)。请求头令牌类提供商（bearer、`x-api-key`、`api-key`、`x-goog-api-key`）均已覆盖。
- 上游没有原生 Windows 二进制文件。请在 Linux / macOS / WSL 上运行。
- CA 在首次生成时是一张有效期 10 年的自签名证书。轮换需要手动执行 `openssl genrsa ...`（或等待后续新增 `hermes egress rotate-ca` 的更新）。
- 重新运行 setup 会在重写配置或映射后停止正在运行的守护进程；需要重启（仅规则集变更时可用 `hermes egress reload`），并在令牌轮换后重启已经在运行的沙箱。
- iron-proxy 内存中密钥的清零由上游控制。拥有 `/proc/<pid>/mem` 读取权限的同一 uid 攻击者可以从守护进程内存中读取替换进来的密钥。
- iron-proxy v0.39 只支持**每个守护进程一个绑定地址**（我们在 Linux 上绑定 docker 网桥网关，在 Docker Desktop 上绑定回环地址），并将守护进程记录与逐请求记录合并为单一日志流。当上游新增 `proxy.http_listens`（复数）和 `log.audit_path` 后，一次版本升级即可接入多地址绑定和专用审计流。

## 另请参阅 {#see-also}

- 上游项目：[github.com/ironsh/iron-proxy](https://github.com/ironsh/iron-proxy)
- 上游文档：[docs.iron.sh](https://docs.iron.sh/)
- Bitwarden 集成：[`hermes secrets bitwarden`](../secrets/bitwarden)
- Hermes Docker 终端后端：[Docker](../docker)
- 开发者 / 贡献者参考：[出口代理内部机制](../../developer-guide/egress-internals)
