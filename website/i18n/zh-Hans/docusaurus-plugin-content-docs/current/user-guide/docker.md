---
sidebar_position: 7
title: "Docker"
description: "在 Docker 中运行 Hermes Agent 以及将 Docker 用作终端后端"
---

# Hermes Agent — Docker

Docker 与 Hermes Agent 的交集有两种截然不同的方式：

1. **在 Docker 中运行 Hermes** — agent 本身在容器内运行（本页的主要内容）
2. **Docker 作为终端后端** — agent 在宿主机上运行，但将每条命令在单个持久化 Docker 沙箱容器中执行，该容器在工具调用、`/new` 和子 agent 之间保持存活，直至 Hermes 进程结束（参见 [配置 → Docker 后端](./configuration.md#docker-backend)）

本页介绍选项 1。容器将所有用户数据（配置、API 密钥、会话、技能、记忆）存储在从宿主机挂载于 `/opt/data` 的单个目录中。镜像本身是无状态的，可通过拉取新版本进行升级而不会丢失任何配置。

## 快速开始 {#quick-start}

如果这是你第一次运行 Hermes Agent，请在宿主机上创建一个数据目录，并以交互方式启动容器以运行设置向导：

:::caution 执行安装命令时避免使用浏览器版 VPS 控制台
某些 VPS 提供商（Hetzner Cloud 以及其他若干家）提供基于浏览器的
控制台来管理主机。这些控制台会错误地传输特殊字符——`:` 可能变成
`;`、`@` 可能被错误渲染，非英语键盘布局的情况更糟——这会悄无声息地
破坏 `docker run` 参数，例如 `-v ~/.hermes:/opt/data`、`-e KEY=value`
以及粘贴进去的 API key / token。

**请改用 SSH 连接**（`ssh root@<host>`），以便安全地复制粘贴命令。
如果你必须使用浏览器控制台，请手动键入命令而不要粘贴，并在按下
回车前逐一核对结果中的每个 `:`、`@`、`=` 和 `/`。
:::

```sh
mkdir -p ~/.hermes
docker run -it --rm \
  -v ~/.hermes:/opt/data \
  nousresearch/hermes-agent setup
```

这将进入设置向导，向导会提示你输入 API 密钥并将其写入 `~/.hermes/.env`。你只需执行一次。强烈建议此时为 gateway 配置一个聊天系统。

:::tip
在容器内执行一次 `hermes setup --portal` —— 刷新令牌会持久化在挂载的 `~/.hermes` 卷中。参见 [Nous Portal](/integrations/nous-portal)。
:::

## 以 gateway 模式运行

配置完成后，将容器作为持久化 gateway（Telegram、Discord、Slack、WhatsApp 等）在后台运行：

```sh
docker run -d \
  --name hermes \
  --restart unless-stopped \
  -v ~/.hermes:/opt/data \
  -p 8642:8642 \
  nousresearch/hermes-agent gateway run
```

端口 8642 暴露 gateway 的 [OpenAI 兼容 API 服务器](./features/api-server.md)和健康检查端点。如果你只使用聊天平台（Telegram、Discord 等），该端口是可选的；但如果你希望 dashboard 或外部工具访问 gateway，则必须开放。

:::tip Gateway 以受监管方式运行
在官方 Docker 镜像中，`gateway run` 会**由 s6-overlay 自动监管**：如果 gateway 进程崩溃，它会在几秒内重启而不会丢掉容器；当设置了 `HERMES_DASHBOARD=1` 时，dashboard 也会一并被监管。`gateway run` 这个 CMD 进程本身只是一个 `sleep infinity` 心跳，用来保持容器存活，而由 s6 管理真正的 gateway 进程 —— 因此 `docker stop` 仍会干净地关停一切，而 `docker logs` 显示的是受监管 gateway 的输出。

你会在 `docker logs` 中看到一行面包屑，确认该升级已生效。若要退出这一行为 —— 恢复历史上"gateway 就是容器的主进程，容器退出 = gateway 退出"的语义 —— 可传入 `--no-supervise` 或设置 `HERMES_GATEWAY_NO_SUPERVISE=1`。这个退出选项适用于希望容器以 gateway 的状态码退出的 CI 冒烟测试；对于生产部署，受监管的默认行为严格更优。

该行为仅适用于基于 s6 的镜像。更早的（基于 tini 的）镜像仍将 `gateway run` 作为前台主进程运行。
:::

:::note gateway 日志去了哪里
完整的路由映射（各 profile 的 gateway、dashboard、启动协调器、容器级 `docker logs`）见下方的[日志去了哪里](#where-the-logs-go)一节。
:::

:::note 无人值守 gateway 的工具循环硬停止
`tool_loop_guardrails.hard_stop_enabled` 默认为 `false`，这对交互式 CLI 和 TUI 会话是合理的 —— 那里有人能看到重复的工具调用警告。在无人值守的 gateway 或服务器部署中，仅有警告可能无法阻止陷入重复工具调用循环的 agent。希望获得熔断行为的运维人员应在该 profile 的 `config.yaml` 中显式启用硬停止：

```yaml
tool_loop_guardrails:
  hard_stop_enabled: true
  hard_stop_after:
    exact_failure: 5
    idempotent_no_progress: 5
```
:::

注意：API 服务器需设置 `API_SERVER_ENABLED=true` 才会启用。若要在容器内将其暴露至 `127.0.0.1` 以外，还需设置 `API_SERVER_HOST=0.0.0.0` 和 `API_SERVER_KEY`（最少 8 个字符——可用 `openssl rand -hex 32` 生成）。示例：

```sh
docker run -d \
  --name hermes \
  --restart unless-stopped \
  -v ~/.hermes:/opt/data \
  -p 8642:8642 \
  -e API_SERVER_ENABLED=true \
  -e API_SERVER_HOST=0.0.0.0 \
  -e API_SERVER_KEY="$(openssl rand -hex 32)" \
  -e API_SERVER_CORS_ORIGINS='*' \
  nousresearch/hermes-agent gateway run
```

在面向互联网的机器上开放任何端口都存在安全风险。除非你了解相关风险，否则不应这样做。

## 运行 dashboard

内置 Web dashboard 在同一容器内作为受 s6-rc 监管的服务与 gateway 并行运行。设置 `HERMES_DASHBOARD=1` 即可拉起它：

```sh
docker run -d \
  --name hermes \
  --restart unless-stopped \
  -v ~/.hermes:/opt/data \
  -p 8642:8642 \
  -p 9119:9119 \
  -e HERMES_DASHBOARD=1 \
  nousresearch/hermes-agent gateway run
```

Dashboard 由 s6 监管：若进程崩溃，`s6-supervise` 会在短暂退避后自动重启。Dashboard 的 stdout/stderr 会直接转发到 `docker logs <container>`；gateway 的主输出现在写入每个 profile 的 s6 日志文件，见下方的 per-profile 日志说明。

| 环境变量 | 描述 | 默认值 |
|---------------------|-------------|---------|
| `HERMES_DASHBOARD` | 设为 `1`（或 `true` / `yes`）以启用受监管的 dashboard 服务 | *（未设置——服务已注册但保持关闭）* |
| `HERMES_DASHBOARD_HOST` | dashboard HTTP 服务器的绑定地址 | `0.0.0.0` |
| `HERMES_DASHBOARD_PORT` | dashboard HTTP 服务器的端口 | `9119` |
| `HERMES_DASHBOARD_INSECURE` | **已弃用 / 空操作。** 以前用于绕过鉴权门控；自 2026 年 6 月的安全加固起，它不再禁用鉴权。任何非回环绑定都必须配置鉴权提供方 | *（被忽略——请改为配置提供方）* |

容器内的 dashboard 默认绑定 `0.0.0.0`，否则发布的 `-p 9119:9119` 端口将无法从宿主机访问。若你要把它限制在容器回环地址（例如 sidecar / 反向代理拓扑），请显式设置 `HERMES_DASHBOARD_HOST=127.0.0.1`。

当以下两项同时满足时，dashboard 的鉴权门控会自动启用：

1. 绑定地址为非回环地址，**且**
2. 注册了一个 `DashboardAuthProvider` 插件。

有三种内置方式可满足第二个条件：

- **用户名/密码** —— 最简单的自托管 / 局域网 / VPN 内部署方式：设置 `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` + `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`（以及用于跨重启稳定 session 的 `HERMES_DASHBOARD_BASIC_AUTH_SECRET`）。不适合直接暴露到公网上。
- **OAuth（Nous Portal）** —— 适合托管/公网部署：设置 `HERMES_DASHBOARD_OAUTH_CLIENT_ID` 后，`dashboard_auth/nous` 提供者会自动激活。
- **自托管 OIDC** —— 通过标准 OpenID Connect 接入你自己的身份提供商：设置 `HERMES_DASHBOARD_OIDC_ISSUER` + `HERMES_DASHBOARD_OIDC_CLIENT_ID` 后，`dashboard_auth/self_hosted` 提供者会激活。

无论选择哪种，调用方在访问受保护路由前都会先被重定向到登录页。三种提供方的完整说明见 [Web Dashboard → 鉴权](features/web-dashboard.md#authentication-gated-mode)。

如果未注册提供者且绑定为非回环地址，dashboard **会在启动时
失败关闭**，并给出指向缺失环境变量的具体错误信息。现在已不再
存在以无鉴权方式在公网绑定上提供 dashboard 的“逃生通道”：
`HERMES_DASHBOARD_INSECURE=1` 现在是一个已弃用的空操作（它会
打印告警并被忽略）。请改为配置鉴权提供方，或设置
`HERMES_DASHBOARD_HOST=127.0.0.1` 并通过 SSH 隧道 / Tailscale 访问。

:::warning 为什么移除了 `--insecure`
无鉴权的公网 dashboard 是 2026 年 6 月 MCP 配置持久化攻击活动的入口：互联网扫描器访问到暴露的 dashboard（以及 OpenAI API 服务器），诱导 agent 植入 SSH 密钥后门。现在每个非回环绑定都强制启用鉴权门控。对于可信局域网 / homelab 主机，内置的用户名/密码提供方（`HERMES_DASHBOARD_BASIC_AUTH_USERNAME` + `_PASSWORD`）是满足该要求的零基础设施方式。
:::

当独立的 dashboard 容器与宿主机共享 PID 与网络命名空间时（例如 `network_mode: host`，正如仓库自带的 `docker-compose.yml` 中的 `dashboard` 服务那样），**是**支持将 dashboard 作为独立容器运行的。其 gateway 存活检测需要与 gateway 进程共享 PID 命名空间，因此该限制仅适用于在隔离的 bridge 网络容器中、且未共享 PID 命名空间的 dashboard。

## 交互式运行（CLI 聊天）

对已有数据目录打开交互式聊天会话：

```sh
docker run -it --rm \
  -v ~/.hermes:/opt/data \
  nousresearch/hermes-agent
```

或者，如果你已通过 Docker Desktop 等方式在运行中的容器内打开了终端，直接运行：

```sh
/opt/hermes/.venv/bin/hermes
```

## 持久化卷 {#persistent-volumes}

`/opt/data` 卷是所有 Hermes 状态的唯一数据来源。它映射到宿主机的 `~/.hermes/` 目录，包含：

| 路径 | 内容 |
|------|----------|
| `.env` | API 密钥和机密 |
| `config.yaml` | 所有 Hermes 配置 |
| `SOUL.md` | Agent 个性/身份 |
| `sessions/` | 对话历史 |
| `memories/` | 持久化记忆存储 |
| `skills/` | 已安装的技能 |
| `home/` | Hermes 工具子进程（`git`、`ssh`、`gh`、`npm` 及 skill CLI）的 per-profile HOME |
| `cron/` | 定时任务定义 |
| `hooks/` | 事件 hook |
| `logs/` | 运行时日志 |
| `skins/` | 自定义 CLI 皮肤 |

### 不可变安装树

在托管/发布的 Docker 镜像中，`/opt/hermes` 是安装好的应用树。它由 root 拥有，并且对运行时的 `hermes` 用户只读，因此 agent 回合、gateway 会话、dashboard 操作以及普通的 `docker exec hermes hermes ...` 命令都不能原地修改核心源码、打包的 `.venv`、`node_modules` 或 TUI bundle。

所有可变的 Hermes 状态都应位于 `/opt/data` 下：配置、`.env`、profiles、skills、memories、sessions、logs、dashboard 上传、plugins 以及其他用户管理的文件。官方镜像还会阻止在运行时向不可变的 `/opt/hermes` 树写入 `.pyc` 或执行 Hermes 的懒安装依赖流程。

如果运维人员确实需要修复或检查 `/opt/data` 之外的文件，请有意识地使用 root shell。`hermes` shim 默认会把 `docker exec hermes hermes ...` 降回运行时用户；只有在你明确需要 root 语义时，才临时设置 `HERMES_DOCKER_EXEC_AS_ROOT=1`。

某些 skill CLI 会把凭据写到 `~` 下，因此在官方 Docker 布局里要针对子进程 HOME 初始化，而不是只针对数据卷根目录。例如 [xurl skill](./skills/bundled/social-media/social-media-xurl.md) 会把 OAuth 状态存到 `~/.xurl`；在容器里这对应 `/opt/data/home/.xurl`，因此手动认证时应使用 `HOME=/opt/data/home xurl auth status` 之类的调用。

:::warning
切勿同时对同一数据目录运行两个 Hermes **gateway** 容器——会话文件和记忆存储不支持并发写入。
:::

## 多 profile 支持 {#multi-profile-support}

Hermes 支持[多个 profile](../reference/profile-commands.md)——独立的 `~/.hermes/` 子目录，让你可以从单个安装运行独立的 agent（不同的 SOUL、skills、memory、sessions、credentials）。**在官方 Docker 镜像内，s6 监管树把每个 profile 当作一等受监管服务**，因此推荐部署方式是：**一个容器承载多个 profile**。

每个通过 `hermes profile create <name>` 创建的 profile 都会获得：

- 一个专用的 s6 服务槽位 `/run/service/gateway-<name>/`，运行时动态注册，无需重建镜像。
- 崩溃后的自动重启，由 `s6-supervise` 管理退避。
- 每个 profile 独立的轮转日志：`${HERMES_HOME}/logs/gateways/<name>/current`（10 份归档 × 每份 1 MB）。
- 跨容器重启的状态持久化：启动协调器会从每个 profile 目录读取 `gateway_state.json`，仅为上次记录状态是 `running` 的 profile 重新拉起槽位。只有你显式停止过的 gateway（`hermes gateway stop`）才会在重启后保持停止 —— 容器重启、镜像升级或意外退出都会把记录状态留在 `running`，因此 gateway 会在下次启动时自动拉起。

容器内生命周期命令与宿主机上一致：

```sh
# 创建 profile —— 同时注册 gateway-<name> s6 槽位
docker exec hermes hermes profile create coder

# 启停/重启 —— 底层分发给 s6-svc；gateway 生命周期在 docker restart 后依然保持
docker exec hermes hermes -p coder gateway start
docker exec hermes hermes -p coder gateway stop
docker exec hermes hermes -p coder gateway restart

# 状态 —— 容器内会显示 `Manager: s6 (container supervisor)`
docker exec hermes hermes -p coder gateway status

# 删除 profile —— 同时拆除 s6 槽位
docker exec hermes hermes profile delete coder
```

在底层，容器内的 `hermes gateway start/stop/restart` 会被拦截并路由到针对正确服务目录的 `s6-svc`；你不需要直接学习 s6 命令。若要查看原始的 supervisor 状态，使用 `/command/s6-svstat /run/service/gateway-<name>`（注意 `/command/` 只对监管树启动的进程在 PATH 上 —— 从 `docker exec` 调用时请传入绝对路径）。

### 从容器外访问多个 profile

有两个不同的接口可以从容器外访问某个 profile 的 gateway，它们的行为并不相同 —— 不要混为一谈：

**Hermes Desktop（以及 web dashboard）。** Desktop 应用的 **Remote Gateway** 连接的是 `hermes dashboard` 后端（默认**端口 9119**，由 `HERMES_DASHBOARD=1` 启用）—— *不是* OpenAI API 服务器。一个 dashboard 后端服务**所有**同处一地的 profile：应用的 profile 切换器会在每个请求中携带目标 profile，后端则在磁盘上打开该 profile 的 `HERMES_HOME`。所以对 Desktop 来说，你**不需要**为每个 profile 准备第二个端口或第二条连接；一条 `:9119` 连接通过切换器就能覆盖全部。

**OpenAI 兼容 API 客户端（Open WebUI、LobeChat、`/v1/...`）。** 这些客户端连接的是每个 profile 的 **API 服务器**，而它对**每个 profile 都绑定 8642 端口**（取自 `API_SERVER_PORT` / `platforms.api_server.extra.port` —— 没有自动分配，也没有 `config.yaml`/`gateway.port` 这样的键）。如果你想让客户端访问*某个特定的*第二个 profile，请在**该 profile 自己的** `.env` 中给它一个不同的 `API_SERVER_PORT`，否则它的 gateway 也会尝试绑定 8642，从而与默认 profile 冲突：

```sh
# 创建 profile（同时注册它的 gateway-<name> s6 槽位）
docker exec hermes hermes profile create work

# 把它的 API 服务器指向一个空闲端口（写入该 profile 自己的 .env）
cat >> /opt/data/profiles/work/.env <<'EOF'
API_SERVER_ENABLED=true
API_SERVER_PORT=8643
EOF

docker exec hermes hermes -p work gateway restart
```

请把 `API_SERVER_PORT` 放在每个 profile **自己的** `.env` 中，绝不要放进容器级的 `environment:` 块 —— 全局值会把所有 profile 逼到同一个端口上并互相冲突。使用桥接网络时，在 `docker-compose.yml` 中发布额外端口（`- "8643:8643"`）；使用 `network_mode: host` 时它在宿主机上已经可达。默认 profile 的 8642 连接不受影响。

### 为什么是一个容器承载多个 profile，而不是多个容器

在迁移到 s6 之前，"每个 profile 一个容器"是推荐做法，因为容器内没有可以管理多个 gateway 的 supervisor。有了 s6 作为 PID 1，这就不再必要了，而单容器布局几乎在每个维度上都更简单：

| | 一个容器，多个 profile | 每个 profile 一个容器 |
|---|---|---|
| 磁盘开销 | 一个镜像、一个内置 venv、一份 Playwright 缓存 | N 个镜像 / N 份缓存 |
| 内存开销 | 共享 Python 解释器缓存、共享 node_modules | 每个容器重复一份 |
| 创建 profile | `docker exec ... hermes profile create <name>`（几秒） | 新的 `docker run` 调用 + 端口分配 + 绑定挂载配置 |
| 每个 profile 的崩溃恢复 | `s6-supervise` 自动重启 | Docker 的 `--restart unless-stopped`（更慢，会打断同容器内的其他工作） |
| 日志 | 通过 `s6-log` 得到每个 profile 独立的轮转文件，外加容器启动审计日志 | 每个容器一份 `docker logs <name>` —— 没有内置轮转 |
| 备份 | 一个 `~/.hermes` 目录 | N 个目录需要协调 |

默认 profile（`default`）总是在首次启动时注册，因此全新容器开箱即带一个受监管的 gateway。额外的 profile 纯粹是运行时新增。

### 什么时候你确实需要单独的容器

profile-in-container 是默认方案。只有在你有具体理由时，才为每个 profile 运行单独的容器：

- **按工作负载做资源隔离** —— 例如 profile A 中失控的浏览器工具会话不应该能把 profile B 撑到 OOM。容器可以为每个 profile 提供 `--memory` / `--cpus`。
- **独立的镜像版本固定** —— 不同工作负载使用不同的上游镜像 tag。
- **网络分段** —— 每个 profile 使用不同的 Docker 网络（例如一个面向客户、一个面向内部）。
- **合规 / 爆炸半径** —— 不同的凭据从不共享同一个操作系统级进程树。

在这些情况下，为每个 profile 声明一个服务，并使用不同的 `container_name`、`volumes` 和 `ports`：

```yaml
services:
  hermes-work:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-work
    restart: unless-stopped
    command: gateway run
    ports:
      - "8642:8642"
    volumes:
      - ~/.hermes-work:/opt/data

  hermes-personal:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-personal
    restart: unless-stopped
    command: gateway run
    ports:
      - "8643:8642"
    volumes:
      - ~/.hermes-personal:/opt/data
```

[持久化卷](#persistent-volumes)一节中的警告依然适用：切勿让两个容器同时指向同一个 `~/.hermes` 目录。每个容器内的 s6 supervisor 管理自己的 profile 集合；跨容器共享数据卷会损坏会话文件和记忆存储。

## 日志去了哪里 {#where-the-logs-go}

s6 容器有四个不同的日志面，而"为什么我的 gateway 在 `docker logs` 里什么都不显示"是常见的意外。速查表：

| 来源 | 落在哪里 | 如何查看 |
|---|---|---|
| **各 profile 的 gateway**（`hermes gateway run` 以及 s6 下的各 profile gateway） | 同时输出到两处：`docker logs <container>`（实时，无额外前缀）**以及** `${HERMES_HOME}/logs/gateways/<profile>/current`（轮转、带 ISO-8601 时间戳，10 份归档 × 每份 1 MB） | 在宿主机上执行 `docker logs -f hermes` 或 `tail -F ~/.hermes/logs/gateways/default/current` |
| **Dashboard**（当 `HERMES_DASHBOARD=1` 时） | `docker logs <container>`（无前缀） | `docker logs -f hermes` —— 与 gateway 的输出交织在一起 |
| **启动协调器**（记录每次容器启动时恢复了哪些 profile gateway） | `${HERMES_HOME}/logs/container-boot.log`（仅追加的审计日志） | `tail -F ~/.hermes/logs/container-boot.log` |
| **通用 Hermes 日志**（`agent.log`、`errors.log`） | `${HERMES_HOME}/logs/`（区分 profile） | `docker exec hermes hermes logs --follow [--level WARNING] [--session <id>]` |

有两个值得知道的实际后果：

- 能在容器重启后留存下来的是 `logs/gateways/<profile>/current` 这份文件副本。`docker logs` 只保留当前容器生命周期内的输出（并在 `docker rm` 时被清除）；轮转文件则持久保存在绑定挂载的卷上。
- 启动协调器的审计行格式是 `<iso-timestamp> profile=<name> prior_state=<state> action=<registered|started>`，因此快速执行 `grep profile=coder ~/.hermes/logs/container-boot.log` 就能看出某个 profile 上次是何时恢复的，以及 s6 是否自动启动了它。

## 环境变量转发

API 密钥从容器内的 `/opt/data/.env` 读取。你也可以直接传递环境变量：

```sh
docker run -it --rm \
  -v ~/.hermes:/opt/data \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e OPENAI_API_KEY="sk-..." \
  nousresearch/hermes-agent
```

直接传入的 `-e` 标志会覆盖 `.env` 中的值。这对于不希望将密钥写入磁盘的 CI/CD 或密钥管理器集成非常有用。

:::note 寻找 Docker 作为**终端后端**的说明？
本页介绍在 Docker 内运行 Hermes 本身。如果你希望 Hermes 在 Docker 沙箱容器内执行 agent 的 `terminal` / `execute_code` 调用（一个长期存活、在多个 Hermes 进程间共享的容器——参见 issue #20561），那是另一个配置块——`terminal.backend: docker` 加上 `terminal.docker_image`、`terminal.docker_volumes`、`terminal.docker_forward_env`、`terminal.docker_env`、`terminal.docker_run_as_host_user`、`terminal.docker_extra_args`、`terminal.docker_persist_across_processes` 和 `terminal.docker_orphan_reaper`。包含容器生命周期规则在内的完整配置请参见 [配置 → Docker 后端](configuration.md#docker-backend)。
:::

## Docker Compose 示例

对于同时运行 gateway 和 dashboard 的持久化部署，使用 `docker-compose.yaml` 更为方便：

```yaml
services:
  hermes:
    image: nousresearch/hermes-agent:latest
    container_name: hermes
    restart: unless-stopped
    command: gateway run
    ports:
      - "8642:8642"   # gateway API
      - "9119:9119"   # dashboard（仅在 HERMES_DASHBOARD=1 时生效）
    volumes:
      - ~/.hermes:/opt/data
    environment:
      - HERMES_DASHBOARD=1
      # 取消注释以直接转发特定环境变量而非使用 .env 文件：
      # - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      # - OPENAI_API_KEY=${OPENAI_API_KEY}
      # - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2.0"
```

使用 `docker compose up -d` 启动，使用 `docker compose logs -f` 查看日志。受监管 gateway 的 stdout 同时也会输出到卷上的 `${HERMES_HOME}/logs/gateways/<profile>/current` —— 完整的路由映射见[日志去了哪里](#where-the-logs-go)。

## 可选：Linux 桌面音频桥接 {#optional-linux-desktop-audio-bridge}

在 Docker 中使用语音模式需要两件事同时成立：必须允许 Hermes 在容器内探测音频设备，并且容器必须能访问宿主机的音频服务器。下面的配置覆盖了宿主机侧的音频管道，适用于暴露 PulseAudio 兼容套接字的 Linux 桌面，包括许多 PipeWire 配置。

:::caution
这是一个 Linux 桌面的变通方案，不是通用的 Docker Desktop 功能。当你的宿主机音频已经可用、并希望在 Hermes 容器内使用 CLI 语音模式时，它才有用。如果 Hermes 仍然报告 `Running inside Docker container -- no audio devices`，请使用包含对 `PULSE_SERVER` / `PIPEWIRE_REMOTE` 的 Docker 音频探测支持的构建版本。
:::

首先，在 Compose 文件旁边创建一个 ALSA 配置：

```conf title="asound.conf"
pcm.!default {
    type pulse
    hint {
        show on
        description "Default ALSA Output (PulseAudio)"
    }
}

pcm.pulse {
    type pulse
}

ctl.!default {
    type pulse
}
```

然后构建一个安装了 ALSA PulseAudio 插件的小型派生镜像：

```dockerfile title="Dockerfile.audio"
FROM nousresearch/hermes-agent:latest

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libasound2-plugins \
    && rm -rf /var/lib/apt/lists/*
```

在 Compose 中使用该镜像，并把宿主机用户的 PulseAudio 套接字和 cookie 透传进去：

```yaml
services:
  hermes:
    build:
      context: .
      dockerfile: Dockerfile.audio
    image: hermes-agent-audio
    container_name: hermes
    restart: unless-stopped
    command: gateway run
    volumes:
      - ~/.hermes:/opt/data
      - /run/user/${HERMES_UID}/pulse:/run/user/${HERMES_UID}/pulse
      - ~/.config/pulse/cookie:/tmp/pulse-cookie:ro
      - ./asound.conf:/etc/asound.conf:ro
    environment:
      - HERMES_UID=${HERMES_UID}
      - HERMES_GID=${HERMES_GID}
      - XDG_RUNTIME_DIR=/run/user/${HERMES_UID}
      - PULSE_SERVER=unix:/run/user/${HERMES_UID}/pulse/native
      - PULSE_COOKIE=/tmp/pulse-cookie
```

用你宿主机的 UID/GID 启动它，这样容器进程才能访问按用户划分的音频套接字：

```sh
export HERMES_UID="$(id -u)"
export HERMES_GID="$(id -g)"
docker compose up -d --build
```

要验证 PortAudio 在容器内看到了什么：

```sh
docker exec hermes /opt/hermes/.venv/bin/python -c "import sounddevice as sd; print(sd.query_devices())"
```

## 资源限制

Hermes 容器需要适量资源。推荐最低配置：

| 资源 | 最低 | 推荐 |
|----------|---------|-------------|
| 内存 | 1 GB | 2–4 GB |
| CPU | 1 核 | 2 核 |
| 磁盘（数据卷） | 500 MB | 2+ GB（随会话/技能增长） |

浏览器自动化（Playwright/Chromium）是最耗内存的功能。如果不需要浏览器工具，1 GB 即可。启用浏览器工具时，请至少分配 2 GB。

在 Docker 中设置限制：

```sh
docker run -d \
  --name hermes \
  --restart unless-stopped \
  --memory=4g --cpus=2 \
  -v ~/.hermes:/opt/data \
  nousresearch/hermes-agent gateway run
```

## Dockerfile 说明 {#what-the-dockerfile-does}

官方镜像基于 `debian:13.4`，包含：

- Python 3.13，依赖通过 `uv sync --frozen --no-install-project` 从 lockfile 同步，涵盖预置的 extras（`all`、`messaging`、Anthropic/Bedrock/Azure identity、Hindsight、Matrix），随后再对 Hermes 本身执行不带依赖的可编辑安装。
- Node.js 22 + npm（用于浏览器自动化、WhatsApp 桥接、TUI/桌面 bundle 以及工作区构建工具）
- Playwright 与 Chromium（`npx playwright install --with-deps chromium --only-shell`）
- ripgrep、ffmpeg、git 和 `xz-utils` 作为系统工具
- **`docker-cli`** — 使容器内运行的 agent 可以驱动宿主机的 Docker 守护进程（绑定挂载 `/var/run/docker.sock` 以启用），用于 `docker build`、`docker run`、容器检查等操作
- **`openssh-client`** — 从容器内启用 [SSH 终端后端](/user-guide/configuration#ssh-backend)。SSH 后端调用系统 `ssh` 二进制文件；若缺少此组件，在容器化安装中会静默失败
- WhatsApp 桥接（`scripts/whatsapp-bridge/`）
- **[`s6-overlay`](https://github.com/just-containers/s6-overlay) v3** 作为 PID 1（替代旧版 `tini`）——监管 dashboard 和各 profile gateway，崩溃后自动重启，回收僵尸子进程，并转发信号

镜像在运行时把 `/opt/hermes` 视为不可变的安装树。必须在 Docker 内可用的可选 Python extras、Node 工作区和 TUI 资源都需要在镜像构建时预置；运行时的懒安装被禁用，以免受监管的 gateway 和 `docker exec hermes …` 命令尝试把依赖产物写回只读的源码树。

容器的 `ENTRYPOINT` 是 s6-overlay 的 `/init`。启动时：
1. 以 root 身份运行 `/etc/cont-init.d/01-hermes-setup`（即 `docker/stage2-hook.sh`）：可选的 UID/GID 重映射、修复卷所有权、首次启动时初始化 `.env` / `config.yaml` / `SOUL.md`、除非设置了 `HERMES_SKIP_CONFIG_MIGRATION=1` 否则执行非交互式的配置 schema 迁移、同步内置技能。
2. 运行 `/etc/cont-init.d/02-reconcile-profiles`（即 `hermes_cli.container_boot`）：遍历 `$HERMES_HOME/profiles/<name>/`，在 `/run/service/gateway-<profile>/` 下重建各 profile 的 gateway s6 服务槽，并仅自动启动上次记录状态为 `running` 的 profile（参见 [Per-profile gateway 监管](#per-profile-gateway-supervision)）。
3. 启动静态的 `main-hermes` 和 `dashboard` s6-rc 服务。
4. 将容器的 CMD 作为主程序 exec（`/opt/hermes/docker/main-wrapper.sh`），根据用户传给 `docker run` 的参数进行路由：
   - 无参数 → `hermes`（默认）
   - 第一个参数是 PATH 上的可执行文件（如 `sleep`、`bash`）→ 直接 exec
   - 其他情况 → `hermes <args>`（子命令透传）
   主程序退出时容器退出，并使用其退出码。

:::warning 与 pre-s6 镜像的破坏性变更
容器 ENTRYPOINT 现在是 `/init`（s6-overlay），而非 `/usr/bin/tini`。所有五种已记录的 `docker run` 调用模式（无参数、`chat -q "…"`、`sleep infinity`、`bash`、`--tui`）的行为与基于 tini 的镜像完全相同。如果你有依赖 tini 特定信号行为或硬编码 `/usr/bin/tini --` 调用的下游封装，请固定到之前的镜像标签。
:::

:::warning 权限模型
除非你在命令链中保留 `/init`（或等效的旧版 `docker/entrypoint.sh` shim，它会转发到 stage2 hook），否则不要覆盖镜像入口点。s6-overlay 的 `/init` 以 root 运行，以便在首次启动时对卷执行 chown，然后通过 `s6-setuidgid` 为每个受监管的服务**以及**主程序降权至 `hermes` 用户。在官方镜像内以 root 启动 `hermes gateway run` 默认会被拒绝，因为这可能在 `/opt/data` 中留下 root 所有的文件，导致后续 dashboard 或 gateway 启动失败。仅在你有意接受该风险时才设置 `HERMES_ALLOW_ROOT_GATEWAY=1`。
:::

### `docker exec` 会自动降权到 `hermes` 用户 {#docker-exec-automatically-drops-to-the-hermes-user}

`docker exec hermes <cmd>` 在容器内默认以 root 运行，但镜像在 `/opt/hermes/bin/hermes`（位于 PATH 最前）提供了一个薄 shim，它会检测 root 调用者并透明地通过 `s6-setuidgid hermes` 重新 exec。因此 `docker exec hermes login`、`docker exec hermes profile create …`、`docker exec hermes setup` 等等写出的文件都归 UID 10000 所有 —— 也就是受监管 gateway 可读 —— 无需额外的 `--user` 标志。非 root 调用者（受监管进程本身、`docker exec --user hermes`、容器内的 kanban 子 agent）会命中一个短路分支，直接 exec venv 二进制文件，因此热路径上没有额外开销。

如果你确实需要一个保留 root 语义的 `docker exec`（诊断会话、检查仅 root 可见的状态、`/opt/data` 之外恰好归 root 所有的文件），可以按调用逐次退出该行为：

```sh
docker exec -e HERMES_DOCKER_EXEC_AS_ROOT=1 hermes <cmd>
```

该 shim 接受 `1` / `true` / `yes`（不区分大小写）。其他任何值 —— 包括 `=0` 这类笔误 —— 都会落到降权分支，因此不可能出现静默的退出。如果 `s6-setuidgid` 不可用（自定义构建剥离了 s6-overlay），shim 会拒绝以 root 运行并以 126 退出，从而把损坏的权限模型大声暴露出来，而不是退回到历史上的陷阱：`docker exec hermes login` 会以 `root:root` 写出 `auth.json`，并在每条聊天平台消息上破坏受监管 gateway 的认证。

### Per-profile gateway 监管 {#per-profile-gateway-supervision}

每个通过 `hermes profile create <name>` 创建的 profile 都会自动在 `/run/service/gateway-<name>/` 注册一个受 s6 监管的 gateway 服务，并具备跨容器重启的状态持久化自动重启能力。面向用户的工作流和生命周期命令见上面的[多 profile 支持](#multi-profile-support)。

**相比 pre-s6 镜像的监管优势：**

- Gateway 崩溃后由 `s6-supervise` 在约 1 秒退避后自动重启。
- Dashboard 在通过 `HERMES_DASHBOARD=1` 启用后，位于同一棵监管树上，享有相同的自动重启待遇。
- `docker restart`、镜像升级（`docker compose up -d --force-recreate`）以及意外退出都会保留运行中的 gateway：cont-init 协调器读取 `$HERMES_HOME/profiles/<name>/gateway_state.json`，若上次记录状态为 `running` 则恢复该槽位。只有显式的 `hermes gateway stop` 才会记录 `stopped` 并让 gateway 在重启后保持停止；重启或升级时容器/s6 发出的 SIGTERM 被视为"仍在运行"，因而会自动启动。
- 各 profile 的 gateway 日志持久化于 `$HERMES_HOME/logs/gateways/<profile>/current`（由 `s6-log` 轮转），协调器的操作在每次启动时追加到 `$HERMES_HOME/logs/container-boot.log`。完整的路由映射见[日志去了哪里](#where-the-logs-go)。

在容器内执行 `hermes status` 会显示 `Manager: s6 (container supervisor)`。使用 `/command/s6-svstat /run/service/gateway-<name>` 查看原始 supervisor 状态（注意 `/command/` 仅在监管树进程的 PATH 中；从 `docker exec` 调用时请传入绝对路径）。

## 升级

拉取最新镜像并重建容器。你的数据目录得以保留，容器会在启动 gateway 之前，针对挂载的 `$HERMES_HOME/config.yaml` 执行非交互式的配置 schema 迁移。需要迁移时，Hermes 会先在 `config.yaml` 和 `.env` 旁边写入带时间戳的备份。

```sh
docker pull nousresearch/hermes-agent:latest
docker rm -f hermes
docker run -d \
  --name hermes \
  --restart unless-stopped \
  -v ~/.hermes:/opt/data \
  nousresearch/hermes-agent gateway run
```

或使用 Docker Compose：

```sh
docker compose pull
docker compose up -d
```

仅当你需要在新镜像重写持久化配置之前手动检查或迁移它时，才设置 `HERMES_SKIP_CONFIG_MIGRATION=1`。

## 技能与凭据文件

当使用 Docker 作为执行环境时（不是上述方法，而是 agent 在 Docker 沙箱内运行命令——参见 [配置 → Docker 后端](./configuration.md#docker-backend)），Hermes 为所有工具调用复用单个长期运行的容器，并自动将技能目录（`~/.hermes/skills/`）和技能声明的所有凭据文件以只读卷的形式绑定挂载到该容器中。技能脚本、模板和引用在沙箱内无需手动配置即可使用，由于容器在 Hermes 进程的整个生命周期内持续存在，你安装的任何依赖或写入的文件都会在下次工具调用时保留。

SSH 和 Modal 后端也会进行相同的同步——技能和凭据文件在每次命令执行前通过 rsync 或 Modal mount API 上传。

## 在容器中安装更多工具

官方镜像预装了一套精选工具（参见 [Dockerfile 说明](#what-the-dockerfile-does)），但并非 agent 可能需要的每个工具都已预装。以下是五种推荐方式，按工作量和持久性递增排列。

### npm 或 Python 工具——使用 `npx` 或 `uvx`

对于发布到 npm 或 PyPI 的任何工具，指示 Hermes 通过 `npx`（npm）或 `uvx`（Python）运行，并将该命令记入其持久记忆。如果工具需要配置文件或凭据，指示其将这些文件放在 `/opt/data` 下（如 `/opt/data/<tool>/config.yaml`）。

依赖按需获取并在容器生命周期内缓存。写入 `/opt/data` 的配置在容器重启后仍然存在，因为它位于绑定挂载的宿主机目录上。包缓存本身在 `docker rm` 后会重建，但 `npx` 和 `uvx` 会在下次运行工具时透明地重新获取。

### 其他工具（apt 包、二进制文件）——安装并记住

对于 npm 或 PyPI 之外的工具——`apt` 包、预构建二进制文件、镜像中未包含的语言运行时——指示 Hermes 如何安装（如 `apt-get update && apt-get install -y <package>`），并告知它记住该安装命令。工具在容器剩余生命周期内持续可用，Hermes 在容器重启后下次需要该工具时会重新运行安装命令。

这种方式适合安装快速且偶尔使用的工具。对于频繁使用的工具，建议采用下一种方式。

### 持久安装——构建派生镜像

当工具必须在每次容器启动时立即可用且无需重新安装延迟时，构建一个继承自 `nousresearch/hermes-agent` 并在层中安装该工具的新镜像：

```dockerfile
FROM nousresearch/hermes-agent:latest

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends <your-package> \
    && rm -rf /var/lib/apt/lists/*
USER hermes
```

构建并替换官方镜像使用：

```sh
docker build -t my-hermes:latest .
docker run -d \
  --name hermes \
  --restart unless-stopped \
  -v ~/.hermes:/opt/data \
  -p 8642:8642 \
  my-hermes:latest gateway run
```

入口点脚本和 `/opt/data` 语义原样继承，本页其余内容仍然适用。拉取更新的上游 `nousresearch/hermes-agent` 时记得重新构建镜像。

### 复杂工具或多服务栈——运行 sidecar 容器

对于自带服务（数据库、Web 服务器、队列、无头浏览器集群）或过于庞大而不适合放在 Hermes 容器内的工具，将其作为独立容器运行在共享 Docker 网络上。Hermes 通过容器名称访问 sidecar，与访问本地推理服务器的方式相同（参见 [连接本地推理服务器](#connecting-to-local-inference-servers-vllm-ollama-etc)）。

```yaml
services:
  hermes:
    image: nousresearch/hermes-agent:latest
    container_name: hermes
    restart: unless-stopped
    command: gateway run
    ports:
      - "8642:8642"
    volumes:
      - ~/.hermes:/opt/data
    networks:
      - hermes-net

  my-tool:
    image: example/my-tool:latest
    container_name: my-tool
    restart: unless-stopped
    networks:
      - hermes-net

networks:
  hermes-net:
    driver: bridge
```

在 Hermes 容器内，sidecar 可通过 `http://my-tool:<port>` 访问（或其提供的任何协议）。这种模式使每个服务的生命周期、资源限制和升级节奏保持独立，避免因单个工具的依赖而使 Hermes 镜像臃肿。

### 广泛有用的工具——提交 issue 或 pull request

如果某个工具可能对大多数 Hermes Agent 用户有用，考虑将其贡献到上游，而不是在私有派生镜像中维护。在 [hermes-agent 仓库](https://github.com/NousResearch/hermes-agent)提交 issue 或 pull request，描述该工具及其使用场景。被纳入官方镜像的工具惠及所有用户，并避免了维护下游 fork 的开销。

## 连接本地推理服务器（vLLM、Ollama 等） {#connecting-to-local-inference-servers-vllm-ollama-etc}

在 Docker 中运行 Hermes 且推理服务器（vLLM、Ollama、text-generation-inference 等）也在宿主机或另一个容器中运行时，网络配置需要额外注意。

### Docker Compose（推荐）

将两个服务放在同一 Docker 网络上。这是最可靠的方式：

```yaml
services:
  vllm:
    image: vllm/vllm-openai:latest
    container_name: vllm
    command: >
      --model Qwen/Qwen2.5-7B-Instruct
      --served-model-name my-model
      --host 0.0.0.0
      --port 8000
    ports:
      - "8000:8000"
    networks:
      - hermes-net
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

  hermes:
    image: nousresearch/hermes-agent:latest
    container_name: hermes
    restart: unless-stopped
    command: gateway run
    ports:
      - "8642:8642"
    volumes:
      - ~/.hermes:/opt/data
    networks:
      - hermes-net

networks:
  hermes-net:
    driver: bridge
```

然后在 `~/.hermes/config.yaml` 中，使用**容器名称**作为主机名：

```yaml
model:
  provider: custom
  model: my-model
  base_url: http://vllm:8000/v1
  api_key: "none"
```

:::tip 关键点
- 使用**容器名称**（`vllm`）作为主机名——而非 `localhost` 或 `127.0.0.1`，它们指向 Hermes 容器本身。
- `model` 值必须与传给 vLLM 的 `--served-model-name` 一致。
- 将 `api_key` 设为任意非空字符串（vLLM 要求该请求头，但默认不验证其值）。
- `base_url` 末尾**不要**加斜杠。
:::

### 独立 Docker run（无 Compose）

如果推理服务器直接在宿主机上运行（不在 Docker 中），在 macOS/Windows 上使用 `host.docker.internal`，在 Linux 上使用 `--network host`：

**macOS / Windows：**

```sh
docker run -d \
  --name hermes \
  -v ~/.hermes:/opt/data \
  -p 8642:8642 \
  nousresearch/hermes-agent gateway run
```

```yaml
# config.yaml
model:
  provider: custom
  model: my-model
  base_url: http://host.docker.internal:8000/v1
  api_key: "none"
```

**Linux（host 网络）：**

```sh
docker run -d \
  --name hermes \
  --network host \
  -v ~/.hermes:/opt/data \
  nousresearch/hermes-agent gateway run
```

```yaml
# config.yaml
model:
  provider: custom
  model: my-model
  base_url: http://127.0.0.1:8000/v1
  api_key: "none"
```

:::warning 使用 `--network host` 时，`-p` 标志会被忽略——所有容器端口直接暴露在宿主机上。
:::

### 验证连通性

从 Hermes 容器内部确认推理服务器可达：

```sh
docker exec hermes curl -s http://vllm:8000/v1/models
```

你应该看到列出已服务模型的 JSON 响应。如果失败，请检查：

1. 两个容器是否在同一 Docker 网络上（`docker network inspect hermes-net`）
2. 推理服务器是否监听 `0.0.0.0` 而非 `127.0.0.1`
3. 端口号是否匹配

### Ollama

Ollama 的配置方式相同。如果 Ollama 在宿主机上运行，使用 `host.docker.internal:11434`（macOS/Windows）或 `127.0.0.1:11434`（Linux 使用 `--network host`）。如果 Ollama 在同一 Docker 网络的独立容器中运行：

```yaml
model:
  provider: custom
  model: llama3
  base_url: http://ollama:11434/v1
  api_key: "none"
```

## 故障排查

### 容器立即退出

检查日志：`docker logs hermes`。常见原因：
- `.env` 文件缺失或无效——先以交互方式运行以完成设置
- 开放端口时存在端口冲突

### "Permission denied" 错误

容器的 stage2 hook 通过 `s6-setuidgid` 在每个受监管的服务内将权限降至非 root 用户 `hermes`（UID 10000）。如果宿主机的 `~/.hermes/` 由不同 UID 拥有，请设置 `HERMES_UID`/`HERMES_GID`——或它们的别名 `PUID`/`PGID`，以便与 LinuxServer.io 和 NAS 镜像保持一致——以匹配宿主机用户，或确保数据目录可写：

```sh
chmod -R 755 ~/.hermes
```

在 NAS（UGOS、Synology、unRAID）上，数据目录通常是一个由容器无法 `chown` 的宿主机 UID 所拥有的**绑定挂载**。请把 `PUID`/`PGID`（或 `HERMES_UID`/`HERMES_GID`）设置为该宿主机用户，让运行时以该挂载的所有者身份运行，而不是 UID 10000：

```sh
docker run -d \
  --name hermes \
  -e PUID=1000 -e PGID=10 \
  -v /volume1/docker/hermes:/opt/data \
  nousresearch/hermes-agent gateway run
```

`docker exec hermes <cmd>` 同样会自动降权到 UID 10000 —— 详情以及按调用退出的方式见[`docker exec` 会自动降权到 `hermes` 用户](#docker-exec-automatically-drops-to-the-hermes-user)。

### 浏览器工具无法使用

Playwright 需要共享内存。在 Docker run 命令中添加 `--shm-size=1g`：

```sh
docker run -d \
  --name hermes \
  --shm-size=1g \
  -v ~/.hermes:/opt/data \
  nousresearch/hermes-agent gateway run
```

### 网络问题后 gateway 无法重连

`--restart unless-stopped` 标志可处理大多数瞬时故障。如果 gateway 卡住，重启容器：

```sh
docker restart hermes
```

### 检查容器健康状态

```sh
docker logs --tail 50 hermes          # 最近日志
docker run -it --rm nousresearch/hermes-agent:latest version     # 验证版本
docker stats hermes                    # 资源使用情况
```