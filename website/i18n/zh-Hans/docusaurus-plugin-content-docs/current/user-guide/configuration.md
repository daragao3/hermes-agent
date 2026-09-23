---
sidebar_position: 2
title: "Hermes Agent 配置"
description: "配置 Hermes Agent——config.yaml、provider、模型、API 密钥等"
---

# Hermes Agent 配置

所有设置都存储在 `~/.hermes/` 目录中，便于访问。

:::tip 获得可用 `config.yaml` 的最简路径
运行 `hermes setup --portal`——一次 OAuth 即可获得一个模型 provider 以及全部四个 Tool Gateway 工具，无需手动编辑 YAML。Portal 订阅用户在按 token 计费的 provider 上还可享受 9 折优惠。参见 [Nous Portal](/integrations/nous-portal)。
:::

## 目录结构 {#directory-structure}

```text
~/.hermes/
├── config.yaml     # 设置（模型、终端、TTS、压缩等）
├── .env            # API 密钥和机密
├── auth.json       # OAuth provider 凭据（Nous Portal 等）
├── SOUL.md         # 主要 agent 身份（系统 prompt 中的第 1 个槽位）
├── memories/       # 持久记忆（MEMORY.md、USER.md）
├── skills/         # agent 创建的 skill（通过 skill_manage 工具管理）
├── cron/           # 计划任务
├── sessions/       # Gateway 会话
└── logs/           # 日志（errors.log、gateway.log——机密会自动脱敏）
```

## 管理配置 {#managing-configuration}

```bash
hermes config              # 查看当前配置
hermes config edit         # 在编辑器中打开 config.yaml
hermes config get KEY      # 打印解析后的值
hermes config set KEY VAL  # 设置特定值
hermes config unset KEY    # 删除用户设置的值
hermes config check        # 检查缺失的选项（更新后）
hermes config migrate      # 交互式添加缺失的选项

# 示例：
hermes config get model
hermes config set model anthropic/claude-opus-4
hermes config set terminal.backend docker
hermes config unset terminal.backend
hermes config set OPENROUTER_API_KEY sk-or-...  # 保存到 .env
```

:::tip
`hermes config set` 命令会自动把值写到正确的文件——API 密钥保存到 `.env`，其他所有内容保存到 `config.yaml`。
:::

## 配置优先级 {#configuration-precedence}

设置按以下顺序解析（优先级从高到低）：

1. **CLI 参数** —— 例如 `hermes chat --model anthropic/claude-sonnet-4`（单次调用覆盖）
2. **`~/.hermes/config.yaml`** —— 所有非机密设置的主配置文件
3. **`~/.hermes/.env`** —— 环境变量的回退来源；机密（API 密钥、token、密码）**必须**放在这里
4. **内置默认值** —— 未设置任何值时使用的硬编码安全默认值

:::info 经验法则
机密（API 密钥、bot token、密码）放在 `.env` 中。其他所有内容（模型、终端后端、压缩设置、记忆限制、toolset）放在 `config.yaml` 中。两者都设置时，对于非机密设置以 `config.yaml` 为准。
:::

:::tip 组织部署
管理员可以通过系统级的托管目录固定特定的配置和机密值，普通用户无法覆盖这些值。参见
[托管作用域](/user-guide/managed-scope)。
:::

## 运行时限制 {#runtime-limits}

长时间运行的 Hermes 服务端界面（包括 gateway 和
`hermes serve --isolated`）会在操作系统支持时，于启动阶段应用所配置的 `RLIMIT_NOFILE` 软限制：

```yaml
runtime:
  nofile_soft_limit: 4096
```

默认值为 `4096`。Hermes 会把目标值限制在操作系统的硬限制之内，并且永远不会降低已经拥有更高软限制的进程。将该值设为 `0`、`false` 或 `null` 可禁用此调整。在 Windows 上以及无法更改该限制的沙箱中，启动会照常进行而不更改该限制。

## 数据库设置 {#database-settings}

`database:` 部分控制 Hermes 如何打开其 SQLite 状态数据库
（`state.db`），该数据库存储会话、消息和 gateway 路由：

```yaml
database:
  # state.db 的日志模式：wal（默认）或 delete。
  # 在 WAL 不安全的文件系统上（网络挂载、某些 virtiofs 配置）使用 delete。
  # 注意：已存在的磁盘上 WAL 数据库永远不会被在线降级——Hermes 会保留
  # WAL，并记录一条错误，告诉你所配置的 delete 未生效。要转换已有数据库，
  # 请停止所有使用它的进程，然后对该文件离线执行一次
  # `PRAGMA journal_mode=DELETE`。
  journal_mode: wal

  # 每个 state.db 连接的持久性级别：OFF、NORMAL、FULL、
  # EXTRA（或 0-3）。不设置则保留 SQLite 的编译期默认值，而该值
  # 因解释器构建而异。在 macOS 上这是下限而不是固定值：低于 FULL 的值
  # 会被拒绝，以防范 Darwin 的 fsync 重排序；EXTRA 会被采用。
  # synchronous: FULL

  # 可选的 WAL 大小相关 pragma（整数）。不设置 = SQLite 默认值。
  # wal_autocheckpoint: 1000     # 自动检查点之间的页数
  # journal_size_limit: 67108864 # WAL/日志大小上限（字节）
```

当已有数据库的磁盘日志模式在打开时被静默切换为 WAL 时——例如运维人员曾手动转换为 `delete` 的数据库——Hermes 也会发出警告（每个进程每个数据库一次），并指出 `database.journal_mode` 是让该选择保持生效的设置项。

## 环境变量替换 {#environment-variable-substitution}

你可以在 `config.yaml` 中使用 `${VAR_NAME}` 语法引用环境变量：

```yaml
auxiliary:
  vision:
    api_key: ${GOOGLE_API_KEY}
    base_url: ${CUSTOM_VISION_URL}

delegation:
  api_key: ${DELEGATION_KEY}
```

单个值中可以包含多个引用：`url: "${HOST}:${PORT}"`。如果引用的变量未设置，占位符会被原样保留（`${UNDEFINED_VAR}` 保持不变），并记录一条警告。裸的 `$VAR` 不会被展开。

在[多路复用的多 profile gateway](/user-guide/multi-profile-gateways) 下，profile 的 `config.yaml` 中的引用会针对**该 profile 的** `.env`（其机密作用域）解析，而不是共享的进程环境——profile B 中的 `${MATRIX_ACCESS_TOKEN}` 除非 B 自己定义了该变量，否则会保持未解析。单 profile 运行不受影响。

同样接受 Cursor 风格的 SecretRef 语法：`${env:VAR_NAME}` 的解析方式与 `${VAR_NAME}` 完全相同（会去掉 `env:` 前缀），因此从 Cursor / Claude 配置复制来的 MCP 或 provider 片段在 `config.yaml` 和 `mcp_servers` 块中都可以原样使用。其他 SecretRef 来源（`${file:...}`、`${vault:...}`、`${bitwarden:...}`）**不会**被内联解析——外部机密后端会在启动时通过 `secrets:` 块把它们的值注入环境，因此请改用 `${env:NAME}` 引用它们；未知前缀只会警告一次并保持原样。

关于 AI provider 设置（OpenRouter、Anthropic、Copilot、自定义端点、自托管 LLM、fallback 模型等），请参阅 [AI Providers](/integrations/providers)。

### Provider 超时 {#provider-timeouts}

你可以设置 `providers.<id>.request_timeout_seconds` 作为 provider 范围的请求超时，并用 `providers.<id>.models.<model>.timeout_seconds` 进行特定模型的覆盖。它适用于每种传输方式（OpenAI 协议、原生 Anthropic、Anthropic 兼容）上的主轮次客户端、fallback 链、凭据轮换后的重建，以及（对 OpenAI 协议）每请求的 timeout 参数——因此配置值优先于旧版的 `HERMES_API_TIMEOUT` 环境变量。

你还可以设置 `providers.<id>.stale_timeout_seconds` 用于非流式的停滞调用检测器，并用 `providers.<id>.models.<model>.stale_timeout_seconds` 进行特定模型的覆盖。它优先于旧版的 `HERMES_API_CALL_STALE_TIMEOUT` 环境变量。

不设置这些值会保留旧版默认值（`HERMES_API_TIMEOUT=1800` 秒、`HERMES_API_CALL_STALE_TIMEOUT=90` 秒、原生 Anthropic 900 秒）。非流式停滞检测器在隐式设置时会对本地端点自动禁用，并且在上下文非常大时可以向上扩展。目前尚未接入 AWS Bedrock（`bedrock_converse` 和 AnthropicBedrock SDK 两条路径都使用 boto3 及其自身的超时配置）。参见 [`cli-config.yaml.example`](https://github.com/NousResearch/hermes-agent/blob/main/cli-config.yaml.example) 中带注释的示例。

## 更新行为 {#update-behavior}

### 后台检查与 SSH 认证 {#background-checks-and-ssh-authentication}

启动时的更新检查会使用与其网络调用相同的隔离 Git 配置读取 origin URL。因此全局的 `url.*.insteadOf` 重写无法对公共 HTTPS 检查隐藏官方的 SSH 远程地址。

Hermes 的隔离内部 Git 命令默认使用 `ssh -o BatchMode=yes`：
未知的主机密钥、密码以及需要口令的加密密钥都会直接失败，而不会打开终端提示。拥有可用密钥或 SSH agent 的受信任主机会继续正常认证。这不会更改你磁盘上的 Git 或 SSH 配置，也不会影响你在终端工具中运行的命令。

该内部默认值会覆盖仓库的 `core.sshCommand` 设置。显式的 `GIT_SSH_COMMAND` 环境变量仍然优先，因此可以在其中保留自定义的身份或传输命令。如果这样的覆盖必须保持非交互式，请在其中包含
`-o BatchMode=yes`；允许提示的覆盖仍可能打断后台检查。

`hermes update` 的设置位于 `config.yaml` 的 `updates` 下：

```yaml
updates:
  pre_update_backup: quick       # quick（状态快照，默认）| full（快照 + HERMES_HOME zip）| off
  backup_keep: 5                 # 保留多少个完整的更新前备份 zip
  non_interactive_local_changes: stash  # stash | discard
  auto_switch_parked_branch: true       # 自动把干净且已完全合并的停放分支切回 main
```

`pre_update_backup` 是唯一的更新前安全开关：`quick`（默认）会将关键状态文件（配对数据、cron 任务、配置、auth；超过 1 GiB 的文件会被跳过）快照到 `state-snapshots/`；`full` 还会把整个 `HERMES_HOME` 打包成 zip 放到 `backups/`，在较大的主目录上可能多花几分钟；`off` 则两者都禁用。旧版的布尔值仍会被遵循（`true` → `full`，`false` → `off`）。

`config.yaml` 本身的时间点副本（在 `hermes setup` 重写它之前、在 `hermes migrate` 编辑它之前，以及文件解析失败时生成）会存放到 `backups/config/config.yaml.<reason>.<timestamp>`。完全相同的重复副本会被跳过，每种原因只保留最新的五个，因此它们永远不会堆积在 `config.yaml` 旁边。

对于 git 安装，Hermes 会在检出更新分支或拉取之前自动 stash 脏的已跟踪文件和未跟踪文件。交互式终端更新会在恢复该 stash 之前询问。非交互式更新（桌面/聊天应用、gateway 或 `--yes`）使用 `updates.non_interactive_local_changes`：`stash` 会在成功拉取后恢复本地源码编辑，而 `discard` 会在成功拉取后丢弃更新所创建的 stash。只在本地源码编辑本就不应保留的受管安装上使用 `discard`。

在执行该 stash 步骤之前，Hermes 还会还原由 npm install/build 抖动留下的已跟踪 `package-lock.json` 差异。请在更新之前提交或手动 stash 有意为之的 lockfile 编辑。

## 终端后端配置 {#terminal-backend-configuration}

Hermes 支持七种终端后端。每种后端决定 agent 的 shell 命令实际在哪里执行——你的本地机器、Docker 容器、通过 SSH 连接的远程服务器、Modal 云沙箱（直连或通过 Nous 托管的 gateway）、Daytona 工作区、Vercel Sandbox，或 Singularity/Apptainer 容器。

```yaml
terminal:
  backend: local    # local | docker | ssh | modal | daytona | vercel_sandbox | singularity
  cwd: "."          # Gateway/cron 工作目录（CLI 始终使用启动目录）
  temp_dir: ""      # 会话临时根目录；为空 = TMPDIR，否则 ~/.hermes/cache/terminal
  font_family: ""   # 桌面终端字体；例如 "MesloLGS NF"
  timeout: 180      # 每条命令的超时（秒）
  home_mode: auto   # auto | real | profile —— 子进程 HOME 策略
  env_passthrough: []  # 转发到沙箱执行环境的环境变量名（terminal + execute_code）
  singularity_image: "docker://nikolaik/python-nodejs:python3.11-nodejs20"  # Singularity 后端的容器镜像
  modal_image: "nikolaik/python-nodejs:python3.11-nodejs20"                 # Modal 后端的容器镜像
  daytona_image: "nikolaik/python-nodejs:python3.11-nodejs20"               # Daytona 后端的容器镜像
```

`terminal.temp_dir` 控制 Hermes 在本地后端上存放会话临时产物的位置——后台进程的日志/pid/退出文件、代码执行沙箱以及溢出的工具结果。当它为空（默认）时，Hermes 会遵循环境中显式设置的 `TMPDIR`/`TMP`/`TEMP`，否则使用位于真实存储上的托管目录 `~/.hermes/cache/terminal`，而不是 `/tmp`——在很多发行版上（尤其是基于 Arch 的系统），`/tmp` 是一个较小的内存 tmpfs，Hermes 的会话产物在负载下可能把它填满。该托管目录会被自动清理：超过 72 小时的产物会由 gateway 的例行维护每小时清扫一次，在仅使用 CLI 的安装上则每个进程清扫一次。将 `temp_dir` 设为一个已存在的绝对路径即可把会话临时文件重定向到其他位置；用户设置的路径永远不会被自动清理。

`terminal.font_family` 控制 Hermes Desktop 中的内嵌终端。它接受一个本地已安装的字体族名称（例如 `MesloLGS NF`）或一个 CSS 字体栈。Hermes 会追加其自带的 JetBrains Mono 字体栈作为回退，空值则保持默认。你也可以在 **设置 → 外观 → 终端字体** 中编辑这一 profile 范围的设置；不需要下载 Google Fonts，也不需要系统字体权限。

对于 Modal、Daytona 和 Vercel Sandbox 等云沙箱，`container_persistent: true` 表示 Hermes 会尝试在沙箱重建之间保留文件系统状态。它并不保证之后仍会运行同一个活跃沙箱、PID 空间或后台进程。

### 后端概览 {#backend-overview}

| 后端 | 命令运行位置 | 隔离程度 | 最适合 |
|---------|-------------------|-----------|----------|
| **local** | 直接在你的机器上 | 无 | 开发、个人使用 |
| **docker** | 单个持久化 Docker 容器（在会话、`/new`、子代理之间共享） | 完整（命名空间、cap-drop） | 安全沙箱、CI/CD |
| **ssh** | 通过 SSH 连接的远程服务器 | 网络边界 | 远程开发、高性能硬件 |
| **modal** | Modal 云沙箱 | 完整（云虚拟机） | 临时云计算、评测 |
| **daytona** | Daytona 工作区 | 完整（云容器） | 托管的云开发环境 |
| **vercel_sandbox** | Vercel Sandbox | 完整（云 microVM） | 具备快照支持的文件系统持久化的云端执行 |
| **singularity** | Singularity/Apptainer 容器 | 命名空间（--containall） | HPC 集群、共享机器 |

### 本地后端 {#local-backend}

默认后端。命令直接在你的机器上运行，没有隔离。无需任何特殊设置。

```yaml
terminal:
  backend: local
```

默认情况下，本地工具子进程会保留你真实的操作系统用户 `HOME`。这让 `git`、`ssh`、`gh`、`az`、`npm`、Claude Code 和 Codex 等外部 CLI 能找到它们在你平常 shell 中已在使用的凭据和配置。Hermes 的状态仍然通过 `HERMES_HOME` 按 profile 隔离；profile 并不是通过 `HOME` 来选择配置、记忆、会话或 skill 的。

Hermes **不会**更改你系统范围的 `HOME`、shell 启动文件或操作系统账户的主目录。此设置只控制传递给 Hermes 通过 `terminal`、后台终端进程、`execute_code` 和 ACP 辅助进程等工具启动的子进程的环境。

#### `terminal.home_mode`

| 模式 | 主机安装 | 容器 | 取舍 |
|---|---|---|---|
| `auto` | 保留真实的操作系统用户 `HOME` | 使用 `{HERMES_HOME}/home` | 推荐的默认值。主机上的 CLI 可继续工作；容器状态得以持久化。 |
| `real` | 强制使用真实的操作系统用户 `HOME` | 如可见，强制使用真实的操作系统用户 `HOME` | 当父进程意外地以指向 profile 主目录的 `HOME` 启动时很有用。 |
| `profile` | `{HERMES_HOME}/home` 存在时使用它 | `{HERMES_HOME}/home` 存在时使用它 | 严格的按 profile 隔离 CLI 配置，但除非你在 profile 主目录中初始化或链接它们，否则常规的 `~/.ssh`、`~/.gitconfig`、`~/.azure`、`~/.config/gh`、Claude/Codex 认证、npm 状态等都将不可见。 |

默认设置的缺点是，主机上的各个 profile 共享 `~` 下同一套常规的用户级 CLI 凭据/配置。如果你需要一个拥有独立 git 身份、SSH 密钥、GitHub CLI 登录、npm 配置或云 CLI 登录的 profile，请使用 `home_mode: profile`，并有意识地在该 profile 主目录中初始化这些工具。

如果你确实需要严格的按 profile 工具配置隔离，请设置：

```yaml
terminal:
  home_mode: profile
```

在该模式下，工具子进程使用 `{HERMES_HOME}/home` 作为 `HOME`。Hermes 还会设置 `HERMES_REAL_HOME`，以便脚本在需要时仍能找到真实的用户主目录。容器后端在 `auto` 模式下继续使用 `{HERMES_HOME}/home`，因为该目录位于持久化的 Hermes 数据卷上。

需要区分 profile 状态与真实用户主目录的脚本，应当用 `HERMES_HOME` 获取 Hermes 数据，用 `HERMES_REAL_HOME` 获取账户主目录：

```python
from pathlib import Path
import os

hermes_home = Path(os.environ["HERMES_HOME"])
real_home = Path(os.environ.get("HERMES_REAL_HOME", os.environ["HOME"]))
```

:::warning
agent 拥有与你的用户账户相同的文件系统访问权限。使用 `hermes tools` 禁用你不想要的工具，或切换到 Docker 进行沙箱隔离。
:::

### Docker 后端 {#docker-backend}

在经过安全加固的 Docker 容器内运行命令（丢弃所有 capability、禁止提权、限制 PID 数量）。

**单个持久化容器，在 Hermes 进程之间共享。** Hermes 在首次使用时启动**一个**长期存在的容器，并通过 `docker exec` 把每一次终端、文件和 `execute_code` 调用都路由到这同一个容器中——跨越会话、`/new`、`/reset` 以及 `delegate_task` 子代理。工作目录的变化、已安装的软件包、`/workspace` 中的文件以及**后台进程**，都会从一次工具调用延续到下一次，也会从一个 Hermes 进程延续到下一个。当你关闭 TUI 会话、运行 `/quit` 或启动新的 `hermes` 调用时，容器会继续运行，下一个 Hermes 进程会通过带标签的查找复用它。确切的销毁规则见下文的**容器生命周期**。

**按会话隔离模式（`container_persistent: false`）。** 在 Docker 后端上设置 `container_persistent: false` 会切换为**每个会话**一个容器：每个聊天（桌面应用会话、gateway 对话、TUI 会话）都会获得自己全新的沙箱，在其第一次终端/文件调用时创建，并在会话关闭或空闲超过 `lifetime_seconds` 时移除。会话之间不会延续任何东西——没有文件系统状态、没有挂载、没有后台进程。配合 `docker_mount_cwd_to_workspace: true` 时，只有**附加到该会话**的工作区会被挂载到 `/workspace`；没有附加目录的新会话会得到一个空工作区，而不会继承上一个会话的挂载。`delegate_task` 子代理仍然共享其父会话的容器。当沙箱是不同对话之间的安全边界时使用此模式；如果你想要上面描述的长期共享容器，请保持默认的 `true`。

```yaml
terminal:
  backend: docker
  docker_image: "nikolaik/python-nodejs:python3.11-nodejs20"
  docker_mount_cwd_to_workspace: false  # 将启动目录挂载到 /workspace
  docker_run_as_host_user: false   # 参见下文"以主机用户身份运行容器"
  docker_snap_compat: false        # 参见下文"Snap 打包的 Docker（AppArmor）"
  docker_forward_env:              # 转发到容器中的主机环境变量
    - "GITHUB_TOKEN"
  docker_env:                      # 要注入的字面环境变量（KEY=value）
    DEBUG: "1"
    PYTHONUNBUFFERED: "1"
  docker_volumes:                  # 主机目录挂载
    - "/home/user/projects:/workspace/projects"
    - "/home/user/data:/data:ro"   # :ro 表示只读
  docker_extra_args:               # 原样追加到 `docker run` 的额外参数
    - "--gpus=all"
    - "--network=host"
  docker_network: true             # false = 隔离容器网络（--network=none）

  # 资源限制
  container_cpu: 1                 # CPU 核心数（0 = 不限制）
  container_memory: 5120           # MB（0 = 不限制）
  container_disk: 51200            # MB（需要 XFS+pquota 上的 overlay2）
  container_persistent: true       # true = 持久化 /workspace + /root，共享容器；false = 每个会话一个新容器（见下文）

  # 跨进程容器复用（默认值与"跨会话共享的单个长期容器"契约一致
  # —— 参见容器生命周期）。
  docker_persist_across_processes: true   # 在 Hermes 重启之间复用容器
  docker_shared_container_key: ""         # 让受信任的 profile 选择加入同一身份
  docker_orphan_reaper: true              # 启动时清扫被遗弃的已退出容器

  # 跨后端生命周期设置（同样适用于 docker）
  timeout: 180                     # 每条命令的超时（秒）
  lifetime_seconds: 300            # 空闲回收窗口；也用于计算 2× 孤儿回收阈值
```

**`docker_env`** 与 **`docker_forward_env`**：前者注入你在配置中指定的字面 `KEY=value` 对（这些值存放在你的 `config.yaml` 中，或通过 `TERMINAL_DOCKER_ENV='{"DEBUG":"1"}'` 以 JSON 字典传入）。后者从你的 shell 或 `~/.hermes/.env` 转发值，因此真正的机密永远不会出现在配置文件中。对 token 使用 `docker_forward_env`，对容器需要的静态开关使用 `docker_env`。

**`terminal.docker_extra_args`**（也可通过 `TERMINAL_DOCKER_EXTRA_ARGS='["--gpus=all"]'` 覆盖）让你传入 Hermes 没有作为一等配置项提供的任意 `docker run` 参数——`--gpus`、`--network`、`--add-host`、替代的 `--security-opt` 覆盖等。每个条目都必须是字符串；该列表会追加在组装好的 `docker run` 调用的最后，因此必要时可以覆盖 Hermes 的默认值。请谨慎使用——与沙箱加固相冲突的参数（capability 丢弃、`--user`、工作区绑定挂载）会悄无声息地削弱隔离。

**`terminal.docker_network`**（默认 `true`；环境变量：`TERMINAL_DOCKER_NETWORK`）——设为 `false` 可让沙箱容器以 `--network=none` 运行，切断 agent 命令的所有网络出口。这适用于 `terminal`、`execute_code` 和文件工具所使用的执行容器。由于容器会在 Hermes 进程之间持久存在，当一个较旧的联网容器仍然存在时把它切换为 `false`，会移除该容器并启动一个全新的隔离网络容器（并记录一条警告）；其中运行的后台进程会丢失。请优先使用此配置项，而不是通过 `docker_extra_args` 传入 `--network=none`。

**要求：** 已安装并运行 Docker Desktop 或 Docker Engine。Hermes 会探测 `$PATH` 以及常见的 macOS 安装位置（`/usr/local/bin/docker`、`/opt/homebrew/bin/docker`、Docker Desktop 应用包）。Podman 开箱即用：当两者都已安装时，设置 `HERMES_DOCKER_BINARY=podman`（或完整路径）即可强制使用它。

#### 容器生命周期 {#container-lifecycle}

每个由 Hermes 管理的容器都带有三个标签，以便后续进程（以及孤儿回收器）识别它：

- `hermes-agent=1` —— 标记为由 Hermes 管理
- `hermes-task-id=<sanitized task_id>` —— 作为按任务复用探测的键
- `hermes-profile=<sanitized profile name>` —— 默认将复用和回收限定在当前的 Hermes profile；设置了 `docker_shared_container_key` 时，改用其清理后的值

启动时，Hermes 会运行 `docker ps --filter label=hermes-task-id=<id> --filter label=hermes-profile=<identity>`，找到已有容器时就**附着到该容器**。除非 `docker_shared_container_key` 显式让受信任的 profile 选择使用一个共同值，否则该身份就是当前 profile。如果容器处于 `exited` 状态（例如 Docker 守护进程重启后），它会被 `docker start` 并复用——文件系统状态和已安装的软件包得以保留，但容器内的后台进程不会。

当 Hermes 进程退出时——`/quit`、关闭 TUI 会话、gateway 关闭，甚至 SIGKILL——在默认模式下，清理路径**对容器是空操作**。容器会继续运行。下一个 Hermes 进程会通过标签探测在几毫秒内附着到它。这正是"跨会话共享的单个长期容器"契约所要求的行为：这是后台进程（npm watcher、开发服务器、长时间运行的 pytest）能够跨会话存活的唯一方式。

**容器只会在以下情况下被销毁（停止并执行 `docker rm -f`）：**

| 触发条件 | 何时触发 |
|---|---|
| `docker_persist_across_processes: false` | 显式的按进程隔离。每次 `cleanup()` 都会执行 `stop` + `rm -f`。与 issue #20561 之前的行为一致。 |
| 空闲回收器（`lifetime_seconds`，默认 300 秒） | 仅当环境为 `persist_across_processes=false` 时。持久模式的环境会被视为空操作；容器会在空闲清扫中存活。 |
| 下次启动时的孤儿回收器 | 清扫早于 `2 × lifetime_seconds`（默认 600 秒 = 10 分钟）的、带 hermes 标签的**已退出**容器，范围限定为当前 profile。**正在运行的容器永远不会被触碰**——以保证同级进程的安全。设置 `docker_orphan_reaper: false` 可禁用。 |
| 用户直接操作 | `docker rm -f`、`docker system prune`、Docker Desktop 重启。我们不设置 `--restart=always`，因此主机重启后容器会处于 `Exited` 状态（其写时复制层会保留并在下次启动时被复用，但后台进程已不复存在）。 |

值得了解的边界情况：

- **容器内 PID 1 被 OOM 杀死** 会使容器转为 `Exited`。下次复用时会 `docker start` 它；文件系统状态得以保留，后台进程则不会。
- **切换 profile** 会使容器彼此隔离——标记为 `hermes-profile=work` 的容器对运行在 `hermes-profile=research` 下的 Hermes 进程不可见。孤儿回收器同样按 profile 限定范围，因此跨 profile 的容器不会被意外回收，但在你以其原始 profile 再次启动 Hermes 之前，它们也不会被自动清理。
- **显式的跨 profile 共享** —— 对于有意在同一个受信任工作区中协作的 profile，在 `terminal:` 下设置相同的非空 `docker_shared_container_key`。这只会替换它们的容器身份标签；任务、出口和网络兼容性检查仍然适用。未设置该键的 profile 保持隔离。身份标签由该键派生并带有一个简短的摘要后缀，因此外观相似的键（`team/workspace` 与 `team_workspace`）永远不会冲突到同一个容器中。**重要：共享容器只会被创建一次，由最先启动它的那个 profile 创建**——该 profile 的 `docker_image`、卷、shm 大小以及其他不可变的 Docker 设置会生效，之后的 profile 会原样附着到它上面；它们配置中不同的设置会被忽略，直到该容器被移除并重建。共享同一个键的 profile 应当在镜像和挂载上保持一致。

通过 `delegate_task(tasks=[...])` 派生的并行子代理共享这一个容器——并发的 `cd`、环境变量修改以及对同一路径的写入会相互冲突。如果某个子代理需要隔离的沙箱，它必须通过 `register_task_env_overrides()` 注册一个按任务的镜像覆盖，RL 和基准测试环境（TerminalBench2、HermesSweEnv 等）会为其按任务的 Docker 镜像自动这样做。

**安全加固：**
- `--cap-drop ALL`，仅加回 `DAC_OVERRIDE`、`CHOWN`、`FOWNER`
- `--security-opt no-new-privileges`
- `--pids-limit 256`
- 大小受限的 tmpfs：`/tmp`（512MB）、`/var/tmp`（256MB）、`/run`（64MB）

**凭据转发：** `docker_forward_env` 中列出的环境变量会先从你的 shell 环境解析，然后从 `~/.hermes/.env` 解析。skill 也可以声明 `required_environment_variables`，这些会被自动合并。

#### 环境变量覆盖 {#environment-variable-overrides}

`terminal:` 下的每个键都有一个形如 `TERMINAL_<KEY_UPPERCASE>` 的环境变量覆盖。对 Docker 后端最有用的几个：

| 环境变量 | 映射到 | 说明 |
|---|---|---|
| `TERMINAL_DOCKER_IMAGE` | `docker_image` | 基础镜像 |
| `TERMINAL_DOCKER_FORWARD_ENV` | `docker_forward_env` | JSON 数组：`'["GITHUB_TOKEN","OPENAI_API_KEY"]'` |
| `TERMINAL_DOCKER_ENV` | `docker_env` | JSON 字典：`'{"DEBUG":"1"}'` |
| `TERMINAL_DOCKER_VOLUMES` | `docker_volumes` | 由 `"host:container[:ro]"` 字符串组成的 JSON 数组 |
| `TERMINAL_DOCKER_EXTRA_ARGS` | `docker_extra_args` | JSON 数组 |
| `TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE` | `docker_mount_cwd_to_workspace` | `true` / `false` |
| `TERMINAL_DOCKER_RUN_AS_HOST_USER` | `docker_run_as_host_user` | `true` / `false` |
| `TERMINAL_DOCKER_SNAP_COMPAT` | `docker_snap_compat` | `true` / `false` —— 默认 `false` |
| `TERMINAL_DOCKER_NETWORK` | `docker_network` | `true` / `false` —— 默认 `true`；`false` = `--network=none` |
| `TERMINAL_DOCKER_PERSIST_ACROSS_PROCESSES` | `docker_persist_across_processes` | `true` / `false` —— 默认 `true` |
| `TERMINAL_DOCKER_SHARED_CONTAINER_KEY` | `docker_shared_container_key` | 供受信任 profile 使用的显式共享身份；默认为空 |
| `TERMINAL_DOCKER_ORPHAN_REAPER` | `docker_orphan_reaper` | `true` / `false` —— 默认 `true` |
| `TERMINAL_CONTAINER_CPU` | `container_cpu` | CPU 核心数 |
| `TERMINAL_CONTAINER_MEMORY` | `container_memory` | MB |
| `TERMINAL_CONTAINER_DISK` | `container_disk` | MB |
| `TERMINAL_CONTAINER_PERSISTENT` | `container_persistent` | `true` / `false` —— 控制绑定挂载的工作区目录，与 `docker_persist_across_processes` 不同 |
| `TERMINAL_LIFETIME_SECONDS` | `lifetime_seconds` | 空闲回收窗口 |
| `TERMINAL_TEMP_DIR` | `temp_dir` | 会话临时根目录（本地后端） |
| `TERMINAL_TIMEOUT` | `timeout` | 每条命令的超时 |
| `HERMES_DOCKER_BINARY` | _无_ | 强制使用特定的 docker/podman 二进制路径 |

### SSH 后端 {#ssh-backend}

通过 SSH 在远程服务器上运行命令。使用 ControlMaster 复用连接（5 分钟空闲保活）。默认启用持久 shell——状态（cwd、环境变量）在命令之间保留。

```yaml
terminal:
  backend: ssh
  persistent_shell: true           # 保持一个长期存在的 bash 会话（默认：true）
```

**必需的环境变量：**

```bash
TERMINAL_SSH_HOST=my-server.example.com
TERMINAL_SSH_USER=ubuntu
```

**可选：**

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `TERMINAL_SSH_PORT` | `22` | SSH 端口 |
| `TERMINAL_SSH_KEY` | （系统默认） | SSH 私钥路径 |
| `TERMINAL_SSH_PERSISTENT` | `true` | 启用持久 shell |

**工作原理：** 初始化时使用 `BatchMode=yes` 和 `StrictHostKeyChecking=accept-new` 建立连接。持久 shell 会在远程主机上保持单个 `bash -l` 进程存活，通过临时文件通信。需要 `stdin_data` 或 `sudo` 的命令会自动回退到单次模式。

**Skill / 配置的环境变量透传：** skill 在 `required_environment_variables` 中声明的变量，或你在 `terminal.env_passthrough` 下列出的变量，会通过 OpenSSH 的 `SendEnv` 转发——变量名出现在 `ssh` 命令行中，而变量值随客户端的环境传递，永远不会出现在远程命令文本中。远程 `sshd` 必须接受它们；请在服务器的 `/etc/ssh/sshd_config` 中添加以下内容并重新加载 sshd：

```
AcceptEnv NEXTCLOUD_URL NEXTCLOUD_*      # 或你的 skill 所需的变量名
```

如果没有匹配的 `AcceptEnv`，服务器会静默丢弃这些变量，远程 shell 看到的将是未设置状态。Hermes 的 provider 凭据（`OPENAI_API_KEY` 等）即使被列出也永远不会被转发。参见 [环境变量透传](security.md#environment-variable-passthrough)。

### Modal 后端 {#modal-backend}

在 [Modal](https://modal.com) 云沙箱中运行命令。每个任务都会获得一个隔离的虚拟机，CPU、内存和磁盘均可配置。文件系统可以在会话之间快照/恢复。

```yaml
terminal:
  backend: modal
  container_cpu: 1                 # CPU 核心数
  container_memory: 5120           # MB（5GB）
  container_disk: 51200            # MB（50GB）
  container_persistent: true       # 快照/恢复文件系统
```

**必需：** `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` 环境变量，或 `~/.modal.toml` 配置文件，二者之一。

**持久化：** 启用后，沙箱文件系统会在清理时被快照，并在下一个会话中恢复。快照记录在 `~/.hermes/modal_snapshots.json` 中。这会保留文件系统状态，而不是活跃进程、PID 空间或后台作业。

**凭据文件：** 自动从 `~/.hermes/` 挂载（OAuth token 等），并在每条命令之前同步。

### Daytona 后端 {#daytona-backend}

在 [Daytona](https://daytona.io) 托管工作区中运行命令。支持停止/恢复以实现持久化。

```yaml
terminal:
  backend: daytona
  container_cpu: 1                 # CPU 核心数
  container_memory: 5120           # MB → 转换为 GiB
  container_disk: 10240            # MB → 转换为 GiB（最大 10 GiB）
  container_persistent: true       # 停止/恢复而不是删除
```

**必需：** `DAYTONA_API_KEY` 环境变量。

**持久化：** 启用后，沙箱会在清理时被停止（而不是删除），并在下一个会话中恢复。沙箱名称遵循 `hermes-{task_id}` 模式。

**磁盘限制：** Daytona 强制执行 10 GiB 的上限。超过该值的请求会被截断到上限并给出警告。

### Vercel Sandbox 后端 {#vercel-sandbox-backend}

在 [Vercel Sandbox](https://vercel.com/docs/vercel-sandbox) 云 microVM 中运行命令。Hermes 使用常规的终端和文件工具界面；没有面向模型的 Vercel 专用工具。

```yaml
terminal:
  backend: vercel_sandbox
  vercel_runtime: node24          # node24 | node22 | python3.13
  cwd: /vercel/sandbox            # 默认工作区根目录
  container_persistent: true      # 快照/恢复文件系统
  container_disk: 51200           # 仅支持共享默认值；不支持自定义磁盘
```

**必需安装：** 安装可选的 SDK extra：

```bash
pip install 'hermes-agent[vercel]'
```

**必需认证：** 使用 `VERCEL_TOKEN`、`VERCEL_PROJECT_ID` 和 `VERCEL_TEAM_ID` 三者一起配置访问 token 认证。这是在 Render、Railway、Docker 及类似主机上进行部署和运行常规长期 Hermes 进程时受支持的设置方式。

对于一次性的本地开发，Hermes 也接受短期有效的 Vercel OIDC token：

```bash
VERCEL_OIDC_TOKEN="$(vc project token <project-name>)" hermes chat
```

在已链接的 Vercel 项目目录中，可以省略项目名称：

```bash
VERCEL_OIDC_TOKEN="$(vc project token)" hermes chat
```

OIDC token 有效期很短，不应作为文档所述的部署方式使用。

**运行时：** `terminal.vercel_runtime` 支持 `node24`、`node22` 和 `python3.13`。未设置时，Hermes 默认使用 `node24`。

**持久化：** 当 `container_persistent: true` 时，Hermes 会在清理期间对沙箱文件系统进行快照，并从该快照为同一任务恢复之后的沙箱。快照内容可能包括被复制到沙箱中的、由 Hermes 同步的凭据、skill 和缓存文件。这只保留文件系统状态；它不会保留活跃沙箱的身份、PID 空间、shell 状态或正在运行的后台进程。

**后台命令：** `terminal(background=true)` 使用 Hermes 通用的非本地后台进程流程。在沙箱存活期间，你可以通过常规的 process 工具启动、轮询、等待、查看日志和终止进程。Hermes 不提供在清理或重启之后恢复 Vercel 原生分离进程的功能。

**磁盘大小：** Vercel Sandbox 目前不支持 Hermes 的 `container_disk` 资源开关。请不要设置 `container_disk`，或保持共享默认值 `51200`；非默认值会使诊断和后端创建失败，而不是被静默忽略。

### Singularity/Apptainer 后端 {#singularityapptainer-backend}

在 [Singularity/Apptainer](https://apptainer.org) 容器中运行命令。专为无法使用 Docker 的 HPC 集群和共享机器设计。

```yaml
terminal:
  backend: singularity
  singularity_image: "docker://nikolaik/python-nodejs:python3.11-nodejs20"
  container_cpu: 1                 # CPU 核心数
  container_memory: 5120           # MB
  container_persistent: true       # 可写覆盖层在会话之间持久保留
```

**要求：** `$PATH` 中有 `apptainer` 或 `singularity` 二进制文件。

**镜像处理：** Docker URL（`docker://...`）会被自动转换为 SIF 文件并缓存。已有的 `.sif` 文件会被直接使用。

**Scratch 目录：** 按以下顺序解析：`TERMINAL_SCRATCH_DIR` → `TERMINAL_SANDBOX_DIR/singularity` → `/scratch/$USER/hermes-agent`（HPC 惯例）→ `~/.hermes/sandboxes/singularity`。

**隔离：** 使用 `--containall --no-home` 实现完整的命名空间隔离，且不挂载主机的主目录。

### 常见终端后端问题 {#common-terminal-backend-issues}

如果终端命令立即失败，或终端工具被报告为已禁用：

- **Local** —— 没有特殊要求。入门时最安全的默认选择。
- **Docker** —— 运行 `docker version` 验证 Docker 是否正常工作。如果失败，请修复 Docker，或执行 `hermes config set terminal.backend local`。
- **SSH** —— 必须同时设置 `TERMINAL_SSH_HOST` 和 `TERMINAL_SSH_USER`。缺少任一项时 Hermes 会记录清晰的错误。
- **Modal** —— 需要 `MODAL_TOKEN_ID` 环境变量或 `~/.modal.toml`。运行 `hermes doctor` 检查。
- **Daytona** —— 需要 `DAYTONA_API_KEY`。Daytona SDK 会处理服务器 URL 配置。
- **Singularity** —— 需要 `$PATH` 中有 `apptainer` 或 `singularity`。常见于 HPC 集群。

如有疑问，请把 `terminal.backend` 改回 `local`，先确认命令能在那里运行。

### 销毁时从远程到主机的状态同步 {#remote-to-host-state-sync-on-teardown}

对于 **SSH**、**Modal** 和 **Daytona** 后端，Hermes 会在会话期间把你的 `~/.hermes/` 状态（凭据文件、skill、缓存）推送到远程沙箱中，并在销毁时**把发生变化的状态文件同步回**它们在主机上的原始位置。与最初推送的内容不同的文件（按内容哈希比较）会被原地写回；同步目录下的新远程文件（例如 agent 在远程创建的 skill）会被映射回对应的主机路径。仅上传的凭据文件永远不会在主机上被覆盖。

- 回写同步最多重试 3 次并带退避，且拒绝解压大于 2 GiB 的远程归档。
- Docker 和 Singularity 使用绑定挂载（实时的主机文件系统视图），不需要此机制。
- 这涵盖的是 Hermes 状态（`~/.hermes/`），**而不是**沙箱内任意的工作树文件——在沙箱被销毁之前，请让 agent 显式地把重要产物复制出来（例如 `scp`、`modal volume put`）。

### Docker 卷挂载 {#docker-volume-mounts}

使用 Docker 后端时，`docker_volumes` 让你可以与容器共享主机目录。每个条目使用标准的 Docker `-v` 语法：`host_path:container_path[:options]`。

```yaml
terminal:
  backend: docker
  docker_volumes:
    - "/home/user/projects:/workspace/projects"   # 读写（默认）
    - "/home/user/datasets:/data:ro"              # 只读
    - "/home/user/.hermes/cache/documents:/output" # gateway 可见的导出目录
```

这适用于：
- 向 agent **提供文件**（数据集、配置、参考代码）
- 从 agent **接收文件**（生成的代码、报告、导出内容）
- 你和 agent 访问同一批文件的**共享工作区**

如果你使用消息 gateway，并希望 agent 通过
`MEDIA:/...` 发送生成的文件，请优先使用一个专用的、主机可见的导出挂载，例如
`/home/user/.hermes/cache/documents:/output`。

- 在 Docker 内把文件写入 `/output/...`
- 在 `MEDIA:` 中输出**主机路径**，例如：
  `MEDIA:/home/user/.hermes/cache/documents/report.txt`
- **不要**输出 `/workspace/...` 或 `/output/...`，除非该确切路径对主机上的 gateway 进程同样存在

:::warning
YAML 中重复的键会静默覆盖先前的键。如果你已经有一个
`docker_volumes:` 块，请把新的挂载合并到同一个列表中，而不是在文件后面再添加另一个 `docker_volumes:` 键。
:::

也可以通过环境变量设置：`TERMINAL_DOCKER_VOLUMES='["/host:/container"]'`（JSON 数组）。

### Docker 凭据转发 {#docker-credential-forwarding}

默认情况下，Docker 终端会话不会继承任意的主机凭据。如果你需要在容器内使用某个特定 token，请把它添加到 `terminal.docker_forward_env`。

```yaml
terminal:
  backend: docker
  docker_forward_env:
    - "GITHUB_TOKEN"
    - "NPM_TOKEN"
```

Hermes 会先从你当前的 shell 解析每个列出的变量；如果它是用 `hermes config set` 保存的，则回退到 `~/.hermes/.env`。

:::warning
`docker_forward_env` 中列出的任何内容都会对容器内运行的命令可见。只转发你愿意暴露给终端会话的凭据。
:::

### 以主机用户身份运行容器 {#running-the-container-as-your-host-user}

默认情况下 Docker 容器以 `root`（UID 0）运行。在 `/workspace` 或其他绑定挂载中创建的文件在主机上归 root 所有，因此会话结束后，你必须先 `sudo chown` 它们，才能在主机编辑器中编辑。`terminal.docker_run_as_host_user` 标志可以解决这个问题：

```yaml
terminal:
  backend: docker
  docker_run_as_host_user: true   # 默认：false
```

启用后，Hermes 会在 `docker run` 命令后追加 `--user $(id -u):$(id -g)`，这样写入绑定挂载目录（`/workspace`、`/root`、`docker_volumes` 中的任何目录）的文件都归你的主机用户所有，而不是 root。代价是：容器不再能 `apt install`，也无法写入 `/root/.npm` 等归 root 所有的路径——如果两者都需要，请使用 `HOME` 归非 root 用户所有的基础镜像（或在镜像构建时加入所需的工具）。

保持 `false`（默认值）可获得向后兼容的行为。当你的工作流主要是"编辑挂载的主机文件"并且你已经厌倦了 `sudo chown -R` 时，再开启它。

### Snap 打包的 Docker（AppArmor） {#snap-packaged-docker-apparmor}

在以 snap 方式安装 Docker 的主机上（常见于 Ubuntu 云镜像，例如 Azure 虚拟机），snap 的 AppArmor 限制会拒绝沙箱的两个加固参数，导致容器在启动时退出：

```
exec /sbin/docker-init: operation not permitted     # --init
exec /usr/bin/sleep: operation not permitted        # --security-opt no-new-privileges
```

这是 snapd 的限制（[LP#1908448](https://bugs.launchpad.net/snapd/+bug/1908448)），不是 Hermes 能够探测绕过的问题。要么从 Docker 的 apt 仓库安装 Docker 而不是使用 snap（推荐——所有加固都保持开启），要么选择启用：

```yaml
terminal:
  docker_snap_compat: true   # 去掉 --init 和 no-new-privileges；cap-drop、tmpfs、PID 限制保持不变
```

开启后，沙箱内的僵尸进程不会被 init 回收，容器内的 setuid 二进制文件可以重新获得权限；容器启动时会记录一条警告。

### 可选：将启动目录挂载到 `/workspace` {#optional-mount-the-launch-directory-into-workspace}

Docker 沙箱默认保持隔离。除非你显式选择启用，否则 Hermes **不会**把你当前的主机工作目录传入容器。

在 `config.yaml` 中启用：

```yaml
terminal:
  backend: docker
  docker_mount_cwd_to_workspace: true
```

启用后：
- 如果你从 `~/projects/my-app` 启动 Hermes，该主机目录会被绑定挂载到 `/workspace`
- Docker 后端从 `/workspace` 开始
- 文件工具和终端命令看到的是同一个挂载的项目

禁用时，`/workspace` 保持归沙箱所有，除非你通过 `docker_volumes` 显式挂载某些内容。

安全取舍：
- `false` 保留沙箱边界
- `true` 让沙箱可以直接访问你启动 Hermes 时所在的目录

只有在你有意让容器处理实时主机文件时才选择启用。

### 持久 Shell {#persistent-shell}

默认情况下，每条终端命令都在各自的子进程中运行——工作目录、环境变量和 shell 变量会在命令之间重置。启用**持久 shell** 后，会在多次 `execute()` 调用之间保持一个长期存在的 bash 进程，使状态在命令之间得以保留。

这对 **SSH 后端**最有用，它还能消除每条命令的连接开销。持久 shell **对 SSH 默认启用**，对本地后端默认禁用。

```yaml
terminal:
  persistent_shell: true   # 默认——为 SSH 启用持久 shell
```

禁用方法：

```bash
hermes config set terminal.persistent_shell false
```

**在命令之间保留的内容：**
- 工作目录（`cd /tmp` 对下一条命令仍然有效）
- 导出的环境变量（`export FOO=bar`）
- Shell 变量（`MY_VAR=hello`）

**优先级：**

| 层级 | 变量 | 默认值 |
|-------|----------|---------|
| 配置 | `terminal.persistent_shell` | `true` |
| SSH 覆盖 | `TERMINAL_SSH_PERSISTENT` | 跟随配置 |
| 本地覆盖 | `TERMINAL_LOCAL_PERSISTENT` | `false` |

按后端的环境变量优先级最高。如果你也想在本地后端上使用持久 shell：

```bash
export TERMINAL_LOCAL_PERSISTENT=true
```

:::note
需要 `stdin_data` 或 sudo 的命令会自动回退到单次模式，因为持久 shell 的 stdin 已被 IPC 协议占用。
:::

各后端的详细信息，请参阅 [代码执行](features/code-execution.md) 以及 [README 的终端部分](features/tools.md)。

## Skill 设置 {#skill-settings}

Skill 可以通过其 SKILL.md frontmatter 声明自己的配置设置。这些是非机密的值（路径、偏好、领域设置），存储在 `config.yaml` 的 `skills.config` 命名空间下。

```yaml
skills:
  config:
    myplugin:
      path: ~/myplugin-data   # 示例——每个 skill 定义自己的键
```

**Skill 设置的工作方式：**

- `hermes config migrate` 会扫描所有已启用的 skill，找出未配置的设置，并提供提示让你填写
- `hermes config show` 会在"Skill Settings"下显示所有 skill 设置及其所属的 skill
- skill 加载时，其解析后的配置值会被自动注入到 skill 上下文中

**手动设置值：**

```bash
hermes config set skills.config.myplugin.path ~/myplugin-data
```

关于在你自己的 skill 中声明配置设置的详细信息，请参阅 [创建 Skill —— 配置设置](/developer-guide/creating-skills#config-settings-configyaml)。

### 对 agent 创建的 skill 写入进行防护 {#guard-on-agent-created-skill-writes}

当 agent 使用 `skill_manage` 创建、编辑、修补或删除 skill 时，Hermes 可以选择扫描新增/更新的内容中是否存在危险的关键字模式（凭据窃取、明显的 prompt 注入、外泄指令）。该扫描器**默认关闭**——那些合法地接触 `~/.ssh/` 或提到 `$OPENAI_API_KEY` 的真实 agent 工作流太容易触发这一启发式规则。如果你希望扫描器在 agent 的 skill 写入生效之前提示你，可以重新开启它：

```yaml
skills:
  guard_agent_created: true   # 默认：false
```

开启后，任何被标记的 `skill_manage` 写入都会以审批提示的形式出现，并附带扫描器的理由。接受的写入会生效；拒绝的写入会向 agent 返回一条说明性错误。

### Skill 写入的审批 {#write-approval-for-skill-writes}

与上面的内容扫描器相互独立，`skills.write_approval` 会让**每一次** agent 的 skill 写入（创建 / 编辑 / 修补 / 删除 / 支持文件）都必须经过你的明确审批——与危险命令使用相同的批准/拒绝机制：

```yaml
skills:
  write_approval: false   # false = 自由写入（默认）| true = 将每次写入暂存以供审查
```

开启后，skill 写入会被暂存在 `~/.hermes/pending/skills/` 下，并通过 `/skills pending`、`/skills diff <id>`、`/skills approve <id>`、`/skills reject <id>` 进行审查——可以在 CLI 或任意消息平台中操作。运行时可用 `/skills approval on|off` 切换。记忆也有同样的关卡（见下文的 `memory.write_approval`）。完整演练：[对 agent 的 skill 写入设置关卡](/user-guide/features/skills#gating-agent-skill-writes-skillswrite_approval)。

## 记忆配置 {#memory-configuration}

```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200   # 约 800 个 token
  user_char_limit: 1375     # 约 500 个 token
  write_approval: false     # true = 任何记忆写入前都需要审批
```

设置 `memory.write_approval: true` 后，记忆写入需要你的审批才会生效：交互式 CLI 轮次会就地提示；消息会话和后台自我改进审查会把写入暂存起来，供 `/memory pending` → `/memory approve <id>` / `/memory reject <id>` 审查。运行时可用 `/memory approval on|off` 切换。参见 [控制记忆写入](/user-guide/features/memory#controlling-memory-writes-write_approval)。

## 上下文文件截断 {#context-file-truncation}

控制 Hermes 在应用首尾截断之前，从每个自动上下文文件中加载多少内容。这适用于被注入系统 prompt 的文件，例如 `SOUL.md`、`.hermes.md`、`AGENTS.md`、`CLAUDE.md` 和 `.cursorrules`。它**不会**影响 `read_file` 工具。

```yaml
context_file_max_chars: null  # 默认——按模型上下文窗口缩放的动态上限（下限 2 万、上限 50 万字符）
```

设置一个正整数即可固定上限，而不使用动态行为：

```yaml
context_file_max_chars: 25000
```

每次读取上下文文件还受 `context_file_read_timeout`（秒，默认 `5.0`）限制。读取耗时更长的文件——通常位于 iCloud Drive、OneDrive 或 NFS 等基于网络的文件系统上——会被跳过并给出警告，这样系统 prompt 的其余部分仍能加载：

```yaml
context_file_read_timeout: 5.0
```

## 文件读取安全 {#file-read-safety}

控制单次 `read_file` 调用可以返回多少内容。超过限制的读取会被拒绝，并返回一条错误，提示 agent 使用 `offset` 和 `limit` 读取较小的范围。这可以防止一次性读取压缩过的 JS 包或大型数据文件而淹没上下文窗口。

```yaml
file_read_max_chars: 100000  # 默认——约 2.5 万至 3.5 万个 token
```

如果你使用的是上下文窗口较大的模型并且经常读取大文件，可以调高它。对于小上下文模型，可以调低以保持读取高效：

```yaml
# 大上下文模型（200K+）
file_read_max_chars: 200000

# 小型本地模型（16K 上下文）
file_read_max_chars: 30000
```

agent 还会自动对文件读取去重——如果同一文件区域被读取两次且文件未发生变化，会返回一个轻量的占位内容，而不是重新发送内容。上下文压缩时这一状态会重置，因此在文件内容被摘要掉之后，agent 可以重新读取文件。

## 工具输出截断限制 {#tool-output-truncation-limits}

三个相关的上限控制工具在 Hermes 截断之前可以返回多少原始输出：

```yaml
tool_output:
  max_bytes: 50000        # 终端输出上限（字符）
  max_lines: 2000         # read_file 分页上限
  max_line_length: 2000   # read_file 带行号视图中的单行上限
```

- **`max_bytes`** —— 当一条 `terminal` 命令产生的 stdout/stderr 合计字符数超过该值时，Hermes 会保留前 40% 和后 60%，并在两者之间插入一条 `[OUTPUT TRUNCATED]` 提示。默认 `50000`（在常见分词器下约 1.2 万至 1.5 万个 token）。
- **`max_lines`** —— 单次 `read_file` 调用的 `limit` 参数上限。超过该值的请求会被截断到上限，以免一次读取淹没上下文窗口。默认 `2000`。
- **`max_line_length`** —— `read_file` 输出带行号视图时应用的单行上限。超过该长度的行会被截断为这么多字符，后跟 `... [truncated]`。默认 `2000`。

对于上下文窗口较大、每次调用能承受更多原始输出的模型，可以调高这些限制。对于小上下文模型，可以调低以保持工具结果紧凑：

```yaml
# 大上下文模型（200K+）
tool_output:
  max_bytes: 150000
  max_lines: 5000

# 小型本地模型（16K 上下文）
tool_output:
  max_bytes: 20000
  max_lines: 500
```

### 工具结果溢出预算 {#tool-result-spillover-budget}

与截断不同，过大的工具*结果*会被溢出到磁盘而不是被截掉：完整输出会保存在 `$HERMES_HOME/cache/spillover/` 下，上下文中的内容会被替换为一段预览加上已保存文件的路径（可用 `read_file` 配合 `offset`/`limit` 读取，或用 `execute_code` 处理）。通用的单结果溢出阈值为 100,000 字符，对小上下文模型会自动按比例调低。

MCP 工具结果（名为 `mcp_*` 的工具）使用更严格的默认值 **50,000 字符** 进行溢出：MCP 服务器经常返回大型的未分页负载（工具发现目录、批量执行结果），否则它们会落在通用阈值之下，并在之后的每一轮中撑大上下文。不会丢失任何内容——完整结果会保存在磁盘上。可通过以下配置覆盖阈值：

```yaml
tool_budget:
  mcp_result_size_chars: 50000   # mcp_* 工具的单结果溢出阈值
```

MCP 阈值始终不会超过（可能按上下文缩放后的）通用单结果阈值，因此调高它不会超出当前模型窗口所允许的范围。

Hermes 还会标记 **provider 端省略**：当 MCP 或 Web 工具结果中嵌入了自身的截断标记（`...N more items`、`"has_more": true`、"saved to sandbox" 说明）时，会在结果后追加一行提示，警告可见的数据并不完整，在把任何列举视为完整之前应先翻页/获取剩余内容。

## 全局禁用 Toolset {#global-toolset-disable}

要在一个地方于 CLI 和所有 gateway 平台上屏蔽特定的 toolset，请在 `agent.disabled_toolsets` 下列出它们的名称：

```yaml
agent:
  disabled_toolsets:
    - memory       # 隐藏记忆工具 + MEMORY_GUIDANCE 注入
    - web          # 任何地方都不提供 web_search / web_extract
```

这会在按平台的工具配置（由 `hermes tools` 写入的 `platform_toolsets`）**之后**应用，因此这里列出的 toolset 总会被移除——即使某个平台保存的配置中仍然列有它。当你想要一个"在所有地方关闭 X"的单一开关，而不是在 `hermes tools` 界面中编辑 15 行以上的平台配置时，请使用它。

列表为空或省略该键时不会产生任何效果。

## Git Worktree 隔离 {#git-worktree-isolation}

启用隔离的 git worktree，以便在同一个仓库上并行运行多个 agent：

```yaml
worktree: true    # 始终创建 worktree（等同于 hermes -w）
# worktree: false # 默认——仅在传入 -w 标志时
```

启用后，每个 CLI 会话都会在 `.worktrees/` 下创建一个带有独立分支的全新 worktree。各个 agent 可以编辑文件、提交、推送和创建 PR 而不会相互干扰。干净的 worktree 会在退出时被删除；有未提交改动的会被保留以便手动恢复。

默认情况下，新 worktree 会从**刚获取的远程分支顶端**（当前分支的上游，否则为远程的默认分支）创建分支，因此它会以项目的最新状态为起点，而不是本地克隆中可能已过时的 `HEAD`。这能让 PR 的 diff 只包含实际的改动，而不会继承本地克隆落后的那部分内容。设置 `worktree_sync: false` 则改为从本地 `HEAD` 创建分支——适用于离线情况，或你有意把克隆的当前确切状态作为基线时。如果无法访问远程，会自动回退到本地 `HEAD`。

```yaml
worktree_sync: true    # 默认——从获取到的远程分支顶端创建分支
# worktree_sync: false # 从本地 HEAD 创建分支（离线 / 固定基线）
```

你还可以在仓库根目录的 `.worktreeinclude` 中列出要复制到 worktree 中的 gitignore 文件：

```
# .worktreeinclude
.env
.venv/
node_modules/
```

## 上下文压缩 {#context-compression}

Hermes 会自动压缩较长的对话，使其保持在模型的上下文窗口之内。压缩摘要器是一次独立的 LLM 调用——你可以把它指向任意 provider 或端点。

所有压缩设置都位于 `config.yaml` 中（没有环境变量）。

### 完整参考 {#full-reference}

```yaml
compression:
  enabled: true                                     # 开启/关闭压缩
  progress_notices: false                           # 需手动启用：把常规压缩进度通知发送到聊天平台——见下文
  threshold: 0.50                                   # 达到上下文上限的该百分比时压缩
  threshold_tokens: null                            # 绝对 token 上限（可选）——取比例与绝对值中较低者
  target_ratio: 0.20                                # 作为近期尾部保留的阈值比例
  tail_mode: lean                                   # 尾部保留方式："lean"（默认——截断至 2.5% 的尾部，1 万至 2.5 万，摘要中附带详细的会话日志 + 锚点索引 + session_search 恢复指针，全部来自一次辅助摘要调用；压缩后保留的 token 约少 3 倍）或 "legacy"（0.20×阈值的原文尾部）
  protect_last_n: 20                                # 保持不压缩的最少近期消息数
  protect_first_n: 3                                # 在各次压缩中固定保留的非系统开头消息数（0 = 不固定任何消息）
  in_place: true                                    # 在同一个会话 id 上压缩（不轮换）——见下文
  idle_compact_after_seconds: 0                     # 需手动启用的空闲压缩（0 = 禁用）——见下文
  hygiene_hard_message_limit: 5000                  # Gateway 安全阀——见下文
  hygiene_timeout_seconds: 30                       # 摘要模型**无输出**的最长秒数，超过后 hygiene 压缩会被中止
  hygiene_total_ceiling_seconds: 600                # 即使 token 仍在流式输出，hygiene 等待的绝对上限
  hygiene_max_turn_hold_seconds: 10                 # 传入轮次等待 hygiene 压缩的最长时间，超过后以未压缩状态继续——见下文
  hygiene_failure_cooldown_seconds: 300             # 按会话的 hygiene 失败退避的第一档（x1/x3/x9，上限 1 小时）
  context_timeout_seconds: 120                      # agent 内 compress_context（循环 /compress / 预检）的无活动预算——见下文
  context_total_ceiling_seconds: 600                # 即使 token 仍在流式输出，agent 内 compress_context *提交前* 等待的绝对上限（已开始的 SessionDB 提交永远不会被放弃；超时会被记录并提示）
  proactive_prune_tokens: 0                         # 需手动启用的无 LLM 工具结果修剪的 token 触发值（0 = 关闭；见下文）
  proactive_prune_min_result_chars: 8000            # 修剪的摘要步骤只处理大于该值的工具结果（下限为 200）
  proactive_prune_min_reclaim_tokens: 4096          # 只有至少回收这么多 token 时修剪才会提交（0 = 任意回收量都提交）

# 摘要模型/provider 在 auxiliary: 下配置：
auxiliary:
  compression:
    model: ""                                       # 为空 = 使用主聊天模型。可覆盖为例如 "google/gemini-3-flash-preview" 以获得更便宜/更快的压缩。
    provider: "auto"                                # Provider："auto"、"openrouter"、"nous"、"codex"、"main" 等
    base_url: null                                  # 自定义 OpenAI 兼容端点（覆盖 provider）
```

:::info 旧版配置迁移
带有 `compression.summary_model`、`compression.summary_provider` 和 `compression.summary_base_url` 的旧配置会在首次加载时自动迁移到 `auxiliary.compression.*`（配置版本 17）。无需手动操作。
:::

`progress_notices`（默认 `false`）控制**常规**压缩进度状态是否会发送到聊天平台（Telegram、Discord、Slack 等）。按照设计，自动压缩在聊天界面上是静默的——它在后台运行，仅在服务端记录日志。设置 `progress_notices: true` 可选择在聊天平台上看到常规的生命周期：「Compacting context…」开始通知、预检/调用 API 前的压缩触发、空闲压缩、重试进度（「Compressed 30 → 12 messages, retrying…」）以及「Context compaction complete」通知。该开关只针对压缩状态——无关的运维噪音（辅助模型失败、provider 限流/重试的消息）无论如何都会被抑制。压缩**失败**通知和手动 `/compress` 的反馈始终可见，不受此设置影响。在运行中的 gateway 上编辑该值，会在下一条消息时生效。

`hygiene_hard_message_limit` 是仅限 gateway 的**压缩前安全阀**。它的存在是为了打破一种恶性循环：当 API 调用在一个过大的会话上不断断开时，gateway 永远收不到 token 用量数据，因此基于 token 的阈值无法触发，于是对话记录不断增长，断开也越来越严重。这个基于计数的下限只依据消息数量触发（无论 API 是否失败，消息数量总是已知的），以强制压缩并挽救会话。默认 `5000`——远高于任何正常会话，包括执行数千个短轮次的大上下文（1M+）模型，这些模型早在此之前就会在 token 阈值上压缩。对于特殊平台可以进一步调高，调低则会强制更激进的压缩。在运行中的 gateway 上编辑该值，会在下一条消息时生效（见下文）。

`hygiene_timeout_seconds` 是 gateway 针对这一 agent 之前的压缩步骤的**无活动预算**——而不是总的墙钟时间上限。压缩摘要调用会从模型流式返回，每个到达的 token 都算作向前推进：一个仍在生成的慢速推理模型会不断延长它自己的截止时间，因此缓慢但健康的摘要模型永远不会在生成中途被切断。只有当摘要模型在这么多秒内**没有任何输出**（后端宕机、连接挂起、provider 静默）时，gateway 才会警告用户、在不压缩的情况下继续处理传入消息，并记录一个临时的按会话失败冷却，而不是看起来卡住了。

`hygiene_total_ceiling_seconds`（默认 `600`）即使在 token 仍在流动时也会限制总等待时间，这样一个退化的涓流式流就无法无限期地挟持某个轮次。它的值至少会被提升到 `hygiene_timeout_seconds`。

`hygiene_max_turn_hold_seconds`（默认 `10`）是 gateway 的**轮次挂起预算**——传入消息在等待 hygiene 压缩时被挂起的最长墙钟时间，超过后 gateway 会停止等待并基于未压缩的对话记录继续。之所以需要它，是因为仅靠 `hygiene_total_ceiling_seconds` 可能让线路静默的时间远远超过聊天传输层的空闲超时：一个持续流式输出 token 的摘要模型会不断重置无活动时间片，因此如果没有轮次挂起预算，等待可能一直拉长到上限，而用户却收不到任何字节——Telegram（以及类似的传输层）随后会断开连接，轮次看起来就像冻结了。把轮次的等待限制在这一预算内（远低于典型的约 30 秒传输层空闲超时），可以保证消息得到及时回复。**预算到期时压缩并不会丢失**：工作线程会以分离状态继续运行，并且——当其提交受水位线保护时（有会话数据库时的常规情况）——它会保留其提交资格，因此完成的摘要会在下一个安全边界被采用，而在放弃等待之后追加的轮次会作为并发尾部原样保留。这对**思考/推理型摘要模型**（DeepSeek、QwQ 等）尤其重要，它们仅推理阶段就可能超过该预算：它们的摘要会晚一轮生效，而不是永远不生效。如果提交无法被安全地保护，迟到的结果会被丢弃（`CompressionCommitFence`），并且它不会覆盖较新的轮次。如果你更希望压缩在同一轮内生效且你的传输层能容忍这段等待，可以调高该预算；对于非常慢的后端，调低它可以更快地恢复。

`hygiene_failure_cooldown_seconds` 控制 hygiene 压缩超时或中止之后的按会话冷却。在冷却期间，gateway 会跳过对同一个过大会话的重复 hygiene 尝试，这样每条传入消息就不会都阻塞在同一个出故障的辅助后端上。`/compress`、`/reset` 或之后一个正常的轮次仍然可以恢复该会话。

该值是一个逐级升高的阶梯的**第一档**，而不是固定间隔：同一会话连续失败时，会依次等待该值的 `1x`、`3x`，然后 `9x`，上限为一小时。因此，一个摘要模型永久损坏的会话会逐步退避，而不是以固定间隔无休止地重试；而一次真正缩短了对话记录的运行会把它重置回第一档。升级是按会话、仅在进程内生效的——gateway 重启会把它重置回第一档，而冷却截止时间本身会保留。

`context_timeout_seconds`（默认 `120`）是 agent 内 `compress_context` 使用的同一种**无活动预算**——包括对话循环、预检压缩和手动 `/compress`——这样挂起的摘要模型就无法无限期地拖住会话。流式输出的摘要 token 会延长等待；只有静默的工作线程才会被切断。超时时，Hermes 会针对 `auxiliary.compression.fallback_chain` 的第一个条目重试一次摘要（如果该条目声明了自己的 `timeout`，则使用它）——停滞的路由永远不会抛出异常，因此辅助客户端自身的 fallback 处理无法察觉到它。只有当这次尝试也失败，或没有配置 fallback 链时，Hermes 才会跳过压缩、保留现有消息并警告用户。设为 `0` 可禁用。Gateway 的会话 hygiene 保持其自己的 `hygiene_timeout_seconds` 路径，不会被重复包装。

`context_total_ceiling_seconds`（默认 `600`）即使在 token 仍在流动时，也会限制 agent 内**提交前**的等待（摘要 / 流式阶段）。它的值至少会被提升到 `context_timeout_seconds`。确切的保证是：**摘要阶段受此上限约束；提交阶段超出上限时会被记录并提示。** 一旦工作线程进入压缩提交保护区并且 SessionDB 变更正在进行，提交就永远不会被中途放弃——那样可能导致对话记录出现分歧——但等待不再是静默的：如果提交超过上限，Hermes 会记录超时（WARNING，重复发生时升级为 ERROR），通过用户可见的警告通道发送一次性警告，并以有限的增量继续等待，直到提交完成。当上限在摘要阶段到期时，摘要模型的流会在同一时刻在每种辅助协议上（chat.completions、Codex Responses、Anthropic Messages）被关闭——被放弃的摘要不会在一个无人等待的连接上被计费直至完成，其会话租约也会被释放给下一次尝试。

`protect_first_n` 控制有多少条**非系统**开头消息在每次压缩中被固定保留。默认 `3`——开头的用户/助手交流会在每次摘要中保留下来，使原始目标始终可见。在长期运行、滚动压缩的会话中，如果开头的轮次已不再相关，请设置 `protect_first_n: 0`，只固定系统 prompt + 摘要 + 尾部。无论此设置如何，系统 prompt 本身始终会被保留。

`in_place`（默认 `true`）控制压缩触发时会话身份的变化方式。为 `true` 时，压缩会重写消息列表并重建系统 prompt，**而不轮换会话 id**——对话在整个生命周期中保持同一个持久 id（没有 `parent_session_id` 链，会话列表中也不会出现 `name #2` / `#3` 这样的重新编号）。压缩是非破坏性的：实时上下文会被压缩，但压缩前的轮次会以同一个 id 被软归档（标记为非活跃/已压缩）——仍可通过 `session_search` 搜索并恢复，不会被删除。Hook 可以通过 `session:compress` 事件上的 `in_place` 字段看到这一模式。设置 `in_place: false` 可恢复旧行为，即每次压缩都会轮换到一个与旧 id 相链接的新会话 id。

`threshold_tokens` 为压缩触发设置一个可选的**绝对 token 上限**。设置后，压缩会在基于比例的 `threshold` 与这一绝对数量中较低者处触发——因此无论当前使用哪个模型，压缩都不会晚于用户偏好的 token 数触发。这解决了在上下文窗口不同的模型之间切换（例如 1M → 400K）会改变绝对触发点的问题。该上限会被限制在模型的上下文长度以内，因此把它设得比模型支持的更高也是安全的——此时会改用基于比例的阈值。默认 `null`（禁用——仅使用基于比例的阈值）。该上限在模型切换和 fallback 激活后依然有效。

`idle_compact_after_seconds` 是一个**需手动启用、基于时间**的触发器，用于补充基于大小的 `threshold`。默认 `0`（禁用）。设置为大于 0 时，一个在至少这么多秒的不活跃之后恢复的会话，会在第一次回复之前预先压缩其累积的历史——这样一个长期存在的对话串（例如你几小时后才回来的 Telegram 对话）就不会在之后的每一轮中重新读取其全部陈旧上下文。当上下文已处于或低于压缩后的目标（`threshold × target_ratio`）时，它永远不会触发，并且它遵循与每次自动压缩相同的失败冷却、防抖动和按会话加锁保护。示例：`idle_compact_after_seconds: 1800` 会在空闲 30 分钟后压缩。

`proactive_prune_tokens` 启用一个确定性的、不使用 LLM 的旧工具结果负载修剪，它独立于 `threshold` 运行。在大窗口模型上，`threshold` 压缩（约为窗口的 50%）很少触发，因此庞大的工具输出（终端转储、文件读取、网页提取）会一直留在历史中，并在之后的每一轮中被重新发送。当重新发送的历史超过 `proactive_prune_tokens`（默认 `0` = 关闭；可尝试 `48000` 来启用）时，修剪会对相同的结果去重、对较旧的超大结果做摘要，并截断较大的工具调用参数——同时保护最近的 `protect_last_n` 条消息，并且从不调用模型。完整输出仍可从会话存储中恢复。`proactive_prune_min_result_chars`（默认 `8000`，下限为 ≥ 200）设置了一个大小，低于它的工具结果不会被触碰。`proactive_prune_min_reclaim_tokens`（默认 `4096`）会阻止修剪在回收少于这么多 token 时提交——一次已提交的修剪会重写已发送的历史并使 provider 的 prompt 缓存前缀失效，因此这一关卡让这类缓存中断保持偶发且可摊销（一次有意义的中断，就像一个压缩边界），而不是在每次工具迭代时都触发。它只在内置的 `compressor` 引擎下运行；其他上下文引擎继承的是空操作。

:::tip Gateway 对压缩和上下文长度的热重载
从近期版本开始，在运行中的 gateway 上编辑 `config.yaml` 中的 `model.context_length` 或任意 `compression.*` 键，会在下一条消息时生效——无需重启 gateway、无需 `/reset`、也无需轮换会话。缓存 agent 的签名包含这些键，因此 gateway 在检测到变化时会透明地重建 agent。API 密钥和工具/skill 配置仍需要常规的重载途径。
:::

### 常见配置 {#common-setups}

**默认（自动检测）——无需配置：**
```yaml
compression:
  enabled: true
  threshold: 0.50
```
使用你的主 provider 和主模型。如果你想在比主聊天模型更便宜的模型上进行压缩，可以按任务覆盖（例如 `auxiliary.compression.provider: openrouter` + `model: google/gemini-2.5-flash`）。

**强制使用特定 provider**（基于 OAuth 或 API 密钥）：
```yaml
auxiliary:
  compression:
    provider: nous
    model: gemini-3-flash
```
适用于任何 provider：`nous`、`openrouter`、`codex`、`anthropic`、`main` 等。

**自定义端点**（自托管、Ollama、zai、DeepSeek 等）：
```yaml
auxiliary:
  compression:
    model: glm-4.7
    base_url: https://api.z.ai/api/coding/paas/v4
```
指向一个自定义的 OpenAI 兼容端点。使用 `OPENAI_API_KEY` 进行认证。

### 三个开关如何相互作用 {#how-the-three-knobs-interact}

| `auxiliary.compression.provider` | `auxiliary.compression.base_url` | 结果 |
|---------------------|---------------------|--------|
| `auto`（默认） | 未设置 | 自动检测最佳可用 provider |
| `nous` / `openrouter` / 等 | 未设置 | 强制使用该 provider，使用其认证 |
| 任意 | 已设置 | 直接使用自定义端点（忽略 provider） |

:::warning 摘要模型的上下文长度要求
摘要模型的上下文窗口**必须**至少与你的主 agent 模型一样大。压缩器会把对话的整个中间部分发送给摘要模型——如果该模型的上下文窗口小于主模型，摘要调用就会因上下文长度错误而失败。发生这种情况时，中间的轮次会**在没有摘要的情况下被丢弃**，从而静默地丢失对话上下文。如果你覆盖了模型，请确认它的上下文长度达到或超过你的主模型。
:::

## Gateway 轮次租约超时 {#gateway-turn-lease-timeout}

gateway 按解析后的会话 ID 串行化各个轮次，因此两个路由键无法同时加载并写入同一份对话记录。你可以独立于普通的 agent 无活动超时来配置最长的租约等待时间：

```yaml
agent:
  gateway_turn_lease_timeout: 5
```

如果在该预算到期时另一个轮次仍持有会话租约，Hermes 会失败即关闭：它不会为等待中的消息加载对话记录或运行模型。用户会收到一条拒绝通知，必须重新发送。Hermes 不会自动将消息重新排队，因为在缺少持久化排序和幂等性的情况下这样做可能会把消息处理两次。非正值会使用 5 秒的默认值。

## 会话停滞看门狗 {#session-stall-watchdog}

gateway 运行一个仅通知的停滞看门狗（`agent.session_stall_timeout`，默认 `300` 秒，`0` = 禁用）。当一个忙碌的会话有**待处理的入站后续消息**，并且 agent 的共享活动时钟已至少空闲了这么长时间时，gateway 会记录一条 WARNING 并向用户发送一次性通知：

```
⚠️ Agent session appears stalled (last activity N min ago). Try /new to reset.
```

语义：

- **仅通知。** 看门狗永远不会终止该轮次——与之相对的是 `agent.gateway_timeout`，后者会在长时间无活动后取消运行。停滞通知只是告诉你 agent 看起来卡住了，让你自己决定（`/new`、`/stop` 或继续等待）。
- **每个停滞事件只通知一次。** 当待处理的入站消息被处理完或活动恢复时，这一锁存状态会被清除，因此一个恢复后又再次停滞的会话会再次通知。
- 进度只来自共享的活动快照（工具调用、API 流进度、压缩心跳）。待处理的入站消息是通知的关卡，而不是进度时钟。

```yaml
agent:
  session_stall_timeout: 300   # 秒；0 表示禁用看门狗
```

## 重连关注升级 {#reconnect-attention-escalation}

当某个平台适配器连接失败时（网络中断、bot token 被吊销、sidecar 损坏），gateway 会以带上限的指数退避无限期地重试——重试永不停止，因此暂时性的中断总能在无需运维介入的情况下自愈。缺点是*永久性*的失败（被吊销的 Telegram token、缺少 Discord 特权 intent）看起来与一次小故障完全相同：永远是"正在重试"。

有两种机制让永久性失败变得可见：

- **终态分类。** 异常*类型*证明永远无法自愈的失败——被拒绝/吊销的 token（`telegram_auth_error`、`discord_auth_error`、`email_auth_error`）、缺少特权 intent（`discord_intents_required`）、依赖无法安装的 Photon sidecar（`SIDECAR_DEPS_MISSING`）或缺少 node 二进制文件的 sidecar（`SIDECAR_NODE_MISSING`）——会被标记为致命，而不是进入重试队列。分类严格基于类型；含义不明确的错误总是会继续重试。
- **需要关注的升级。** 一个平台如果在重试队列中持续超过 `agent.reconnect_attention_after`（默认 `7200` 秒 = 2 小时，`0` 表示禁用），会在 gateway 运行时状态（`hermes status`）中获得 `needs_attention: true` 和一个 `retrying_since` 时间戳，并记录一条 WARNING 日志。重试照常继续——这只是一个信号，而不是熔断器。成功重连后该标记会被清除。

```yaml
agent:
  reconnect_attention_after: 7200   # 秒；0 表示禁用升级标记
```

## Gateway Agent 缓存 {#gateway-agent-cache}

gateway 为每个会话保留一个 agent，这样对话就能复用其缓存的 prompt 前缀，而不必在每一轮都重建系统 prompt。该缓存的 agent 还持有会话的完整对话记录——包括工具输出，在一个有上百次工具调用的会话上可达数十 MB。因此在繁忙的多平台 gateway 上，该缓存是进程中最大的单一内存消耗者。

```yaml
agent:
  agent_cache:
    max_size: 128            # LRU 条目上限
    idle_ttl_secs: 3600      # 淘汰空闲这么久的 agent
    memory_high_mb: auto     # 匿名 RSS 预算；数字、"auto" 或 0/off
    max_evictions_per_pass: 16
    protect_recent: 8
```

`max_size` 和 `idle_ttl_secs` 按数量和时间限制缓存。二者都不知道缓存占用了多少字节，因此 `memory_high_mb` 增加了第三个限制：一旦 gateway 自身的匿名常驻内存超过预算，它就会丢弃最近最少使用的对话记录，这些记录会在下一轮时从已存储的会话中重新加载。如果 gateway 正在与其他服务争夺内存，请调低它；如果你更希望保持每个前缀都是热的，请调高它（或设为 `0` 关闭这一步骤）。

`auto` 会根据 gateway 实际运行时受到的内存限制推导预算——容器或 systemd 单元的 cgroup 限制，否则为总内存——因此单元上的 `MemoryMax`/`MemoryHigh` 会被遵循，无需再维护第二个需要保持同步的数字。

正处于轮次中的会话、`protect_recent` 个最近使用的会话，以及对话记录尚未完成写入磁盘的会话，永远不会被丢弃。淘汰会以 WARNING 级别记录，附带测得的 RSS 和被丢弃的会话：

```
Agent cache pressure: anon RSS 6802MB over budget 6656MB — evicting 5 LRU session(s): ...
```

## 上下文引擎 {#context-engine}

上下文引擎控制在接近模型 token 上限时如何管理对话。内置的 `compressor` 引擎使用有损摘要（参见 [上下文压缩](/developer-guide/context-compression-and-caching)）。插件引擎可以用其他策略替代它。

```yaml
context:
  engine: "compressor"    # 默认——内置的有损摘要
```

使用插件引擎（例如用于无损上下文管理的 LCM）：

```yaml
context:
  engine: "lcm"          # 必须与插件名称一致
```

插件引擎**永远不会被自动激活**——你必须显式地把 `context.engine` 设为插件名称。可通过 `hermes plugins` → Provider Plugins → Context Engine 浏览和选择可用的引擎。

关于记忆插件的类似单选机制，请参阅 [Memory Providers](/user-guide/features/memory-providers)。

## 迭代预算 {#iteration-budget}

当 agent 在处理一个需要大量工具调用的复杂任务时，它可能会耗尽其迭代预算（默认：500 轮）。Hermes **不会**在任务中途注入压力警告——早期版本会在预算达到 70%/90% 时警告模型，这会导致模型过早放弃复杂任务，因此已于 2026 年 4 月移除。

取而代之的是，当预算真正耗尽（500/500）时，Hermes 会注入一条消息请模型收尾，并允许一次**宽限调用**，让它能够给出最终回复。如果这次宽限调用仍未产生文本，则会要求 agent 总结它已完成的工作。

```yaml
agent:
  max_turns: none              # 每个对话轮次的迭代次数（默认：none = 不限制）
                               # 设为正整数即可设置上限；"none"/"null"/
                               # "unlimited"/"inf"/"infinity"/"infinite"/0/-1 = 不限制
  budget_warning_ratio: null   # 可选的一次性检查点警告，例如 0.75
  api_max_retries: 3           # 在启用 fallback 之前每个 provider 的重试次数（默认：3）
```

`agent.max_turns` **默认不限制**——轮次上限带来的问题比它解决的更多（任务中途被静默截断），因此开箱即用时 Hermes 会把一个对话轮次运行到完成。要设置上限，请设为正整数。若要明确表示"不限制"，以下任意不区分大小写的写法都可以：`"none"`、`"null"`、`"unlimited"`、`"infinite"`、`"infinity"`、`"inf"`、`0`、`-1`（它们会被解析为一个 `sys.maxsize` 哨兵值，因此循环永远不会因为轮次计数而退出）。

`agent.budget_warning_ratio` 对普通对话和委托对话默认关闭。当它被设为严格介于 `0` 和 `1` 之间的值，并同时设置了有限的 `max_turns` 时，Hermes 会在达到阈值后，在最新的工具结果后追加一条模型可见的检查点通知。该通知在每个对话轮次重新生效，并使用每个 agent 自己的迭代预算。它只会追加到当前的工具结果尾部，而不会追加到更早的轮次，也不会添加合成的用户/系统消息或改变现有的耗尽宽限调用。由调度器管理的 Kanban worker 默认会在 90% 时收到一个完成检查点（显式的比例会改变这一阈值），此时它们的工具仍然可用。该检查点要求给出经过验证的完成结果或一条持久的进度评论，而不是过早地宣告成功。

`agent.api_max_retries` 控制 Hermes 在遇到暂时性错误（限流、连接中断、5xx）时，在切换到 fallback provider **之前**重试一次 provider API 调用的次数。默认值为 `3`——总共四次尝试。如果你配置了 [fallback providers](/user-guide/features/fallback-providers) 并希望更快地故障切换，请把它降为 `0`，这样主 provider 上的第一次暂时性错误就会立即交给 fallback，而不会在不稳定的端点上反复重试。

## 墙钟运行预算 {#wall-clock-run-budget}

与迭代预算分开，你可以为每次对话运行设置一个可选的**墙钟**预算。它专为在硬性外部上限下运行的单次调用和评测框架调用而设计（例如每个任务 900 秒的限制）：如果没有它，一次运行可能在工作几乎完成时超时——距离输出最终答案只差一次生成，或卡在一次挂起的 provider 调用中。

```yaml
agent:
  run_budget_seconds: null     # 可选；未设置/null = 功能完全关闭（默认）
```

或通过 CLI 按次调用设置：

```bash
hermes chat --run-budget 850 -q "..."
```

设置预算后，会发生两件事：

1. **在 80% 时发出收尾通知。** 当预算已过去 80% 时，Hermes 会注入一条**一次性**通知（以缓存安全的方式投递，像 `/steer` 消息一样追加到最新的工具结果后），告诉模型停止新的探索/验证工作，并基于已有状态产出最终交付物。它每次运行最多触发一次，与现有的迭代预算收尾机制相呼应——不会有重复的压力警告。
2. **按截止时间缩放的停滞超时。** 隐式的非流式停滞超时（90 秒的默认值以及推理模型的下限，例如 DeepSeek 推理模型的 600 秒）会被限制在 `max(60, remaining_budget × 0.5)`，这样一次静默挂起的 provider 调用就永远无法耗尽剩余的运行时间。该上限只会*收紧*超时——永远不会放宽——并且显式配置的 `stale_timeout_seconds`（provider/模型配置或 `HERMES_API_CALL_STALE_TIMEOUT`）始终不受影响、优先生效。

预算按每个 `run_conversation` 轮次计算（每条用户消息都会重置），并且在未设置时该功能完全处于休眠状态——不读取时钟、不注入内容、不更改超时。

## 停止前验证（编码验证） {#verify-on-stop-coding-verification}

启用后，如果某一轮中 agent 在工作区里编辑了代码，却没有产出新的验证证据（通过的测试运行、构建、lint 等），Hermes 会拒绝接受最终答案——它会注入一条合成的后续消息，要求 agent 进行验证或解释为什么无法验证。仅编辑文档/markdown/skill 永远不会触发它，并且该循环是有界的，因此永远不会困住 agent。

```yaml
agent:
  verify_on_stop: false        # true | false | "auto"（感知界面：CLI/TUI/桌面开启，消息平台关闭）
  verify_guidance: true        # 在缺少证据的提示中追加创意 UI / 干净 diff 的指导
  max_verify_nudges: 3         # 每轮连续继续提示的上限（内置 + pre_verify hook）
  coding_instructions: ""      # 追加到编码简报中的长期项目级编码规则
```

`verify_on_stop` 接受 `true`（在所有地方开启）、`false`（关闭——默认值）或 `"auto"`（旧版的感知界面行为：在交互式编码界面——CLI、TUI、桌面——以及程序化调用方中开启；在 Telegram/Discord 等消息界面中关闭，因为在那里验证的叙述读起来像聊天噪音）。所有地方默认都是关闭的：全新安装默认为 `false`，而配置迁移也在已有安装上将其关闭，因此启用它是一种显式的选择。设置了 `HERMES_VERIFY_ON_STOP` 环境变量时，它会覆盖配置值。

为这一防护提供依据的证据（运行了哪些测试/lint/构建命令、此后编辑了哪些文件）存放在 `~/.hermes/verification_evidence.db` 中。只有在防护启用时才会写入或创建该账本；当 `verify_on_stop: false` 时不会记录任何内容，已有的文件可以随意删除。

如果你想在同一位置设置用户/插件策略关卡——用你自己的检查让 agent 继续工作——请参阅 [`pre_verify` hook](/user-guide/features/hooks#pre_verify)。

## 持续目标（`/goal`） {#standing-goals-goal}

当持续目标处于激活状态时，Hermes 会判断每一条助手回复是否满足该目标。如果没有，它会把一条续行 prompt 送回同一个会话并继续工作，直到目标完成、轮次预算耗尽，或用户暂停/清除它。轮次预算才是真正的兜底——裁判失败时会**失败开放**（继续），因此一个不稳定的裁判永远不会卡住进度。

```yaml
goals:
  max_turns: 20   # Hermes 自动暂停目标之前的最大续行轮次（默认：20）
```

`max_turns` 限制一个目标在 Hermes 自动暂停它并请用户执行 `/goal resume` 之前可以驱动的续行轮次数。它可以防范裁判的误判（目标实际已完成但裁判说要继续），以及在模糊或无法达成的目标上无限制的模型花费。完整功能请参阅 [Goals](/user-guide/features/goals)。

### API 超时 {#api-timeouts}

Hermes 为流式调用设有多个独立的超时层，并为非流式调用设有停滞检测器。只有当你保留隐式默认值时，停滞检测器才会针对本地 provider 自动调整。

| 超时 | 默认值 | 本地 provider | 配置 / 环境变量 |
|---------|---------|----------------|--------------|
| Socket 读取超时 | 120 秒 | 自动提高到 1800 秒 | `HERMES_STREAM_READ_TIMEOUT` |
| 流停滞检测 | 180 秒 | 提高到 900 秒的上限（`agent.local_stream_stale_timeout`） | `HERMES_STREAM_STALE_TIMEOUT` |
| 非流式停滞检测 | 90 秒 | 隐式设置时自动禁用 | `providers.<id>.stale_timeout_seconds` 或 `HERMES_API_CALL_STALE_TIMEOUT` |
| API 调用（非流式） | 1800 秒 | 不变 | `providers.<id>.request_timeout_seconds` / `timeout_seconds` 或 `HERMES_API_TIMEOUT` |

**Socket 读取超时**控制 httpx 等待 provider 下一块数据的时长。本地 LLM 在处理大上下文时可能需要几分钟的预填充才会产出第一个 token，因此 Hermes 在检测到本地端点时会把它提高到 30 分钟。如果你显式设置了 `HERMES_STREAM_READ_TIMEOUT`，则无论端点检测结果如何，始终使用该值。

**流停滞检测**会终止那些收到 SSE keep-alive ping 但没有实际内容的连接。对于本地 provider（它们在预填充期间不发送 keep-alive ping），默认值会被提高到一个有限的 900 秒上限，而不是 180 秒的基准值——可通过 `agent.local_stream_stale_timeout` 或 `HERMES_LOCAL_STREAM_STALE_TIMEOUT` 环境变量配置。

**非流式停滞检测**会终止那些长时间没有响应的非流式调用。默认情况下，Hermes 在本地端点上禁用它，以避免在长时间预填充期间误判。如果你显式设置了 `providers.<id>.stale_timeout_seconds`、`providers.<id>.models.<model>.stale_timeout_seconds` 或 `HERMES_API_CALL_STALE_TIMEOUT`，即使在本地端点上也会遵循该显式值。

该预算约束每一次非流式调用。一个接受了请求然后就保持沉默的 provider——连接保持打开、没有字节、没有错误——会在停滞超时处被中止并重试，而不是一直挂到长得多的 socket 读取超时（或者，对于无人值守的 cron 运行，直到外部某个东西杀死进程）。

周期性的 provider 等待通知只会在至少 **60 秒的静默**之后出现。Codex Responses 的**等待状态**描述的是静默时间，而不是总的生成时间：活跃的流事件（包括推理）会让它保持安静。如果事件停止，它会报告没有流事件的时长，而不是声称尚未收到响应；事件恢复时该通知会被清除。当一次重连开始了新的首个事件看门狗阶段时，等待状态会跟随该阶段。这一显示行为不会延长独立的墙钟停滞调用预算，也不会改变看门狗超时。Chat-completion 流同样会在数据块恢复时立即清除其静默警告，而不会替换本地模型加载状态。

Cron 任务和委托的子代理同样使用流式调用。它们在自己的线程上内联运行请求（其他会话使用的中断工作线程会在 gateway 的嵌套线程池中卡死），但线路上的请求仍然是 `stream: true`，因此上面的**流停滞检测**预算约束着它们——每个 token 都算作存活信号，因此一个思考几分钟的推理模型不会被误认为是挂起的 provider，而那些会切断静默连接的边缘代理也会持续看到字节流动。

### 禁用 API 流式输出 {#disabling-api-streaming}

`model.streaming: false` 会强制整个会话使用非流式请求——父 agent 和子代理都一样。它是为*流式*工具调用路径有问题的自托管 OpenAI 兼容服务器准备的应急开关（例如带有 `--tool-call-parser qwen3_xml` 加推理解析器的 vLLM，可能会把工具调用标记泄漏到纯文本中并返回零个 `tool_calls`，导致委托任务静默地什么都不做）。默认值为 `true`；除非你遇到这类问题，否则请保持不变，因为非流式调用会失去上面描述的存活特性。这与 `display.streaming` 是分开的，后者只控制终端中的 token 渲染。

```yaml
model:
  streaming: false
```

## 上下文压力警告 {#context-pressure-warnings}

与迭代预算压力分开，上下文压力追踪对话距离**压缩阈值**——即上下文压缩触发、对较早消息进行摘要的那个点——还有多近。这帮助你和 agent 了解对话何时变得过长。

| 进度 | 级别 | 会发生什么 |
|----------|-------|-------------|
| 达到阈值的 **≥ 60%** | Info | CLI 显示青色进度条；gateway 发送一条提示性通知 |
| 达到阈值的 **≥ 85%** | Warning | CLI 显示粗体黄色进度条；gateway 警告即将进行压缩 |

在 CLI 中，上下文压力会以进度条的形式出现在工具输出流中：

```
  ◐ context ████████████░░░░░░░░ 62% to compaction  48k threshold (50%) · approaching compaction
```

在消息平台上，会发送一条纯文本通知：

```
◐ Context: ████████████░░░░░░░░ 62% to compaction (threshold: 50% of window).
```

如果自动压缩已禁用，警告会改为提示你上下文可能会被截断。

上下文压力是自动的——无需配置。它纯粹作为面向用户的通知触发，不会修改消息流，也不会向模型的上下文注入任何内容。

## 凭据池策略 {#credential-pool-strategies}

当你为同一个 provider 拥有多个 API 密钥或 OAuth token 时，可以配置轮换策略：

```yaml
credential_pool_strategies:
  openrouter: round_robin    # 均匀地轮流使用各个密钥
  anthropic: least_used      # 总是选择使用最少的密钥
```

可选值：`fill_first`（默认）、`round_robin`、`least_used`、`random`。完整文档请参阅 [凭据池](/user-guide/features/credential-pools)。

## Prompt 缓存 {#prompt-caching}

当前 provider 支持时，Hermes 会自动开启跨会话的 prompt 缓存——无需用户配置。

对于**原生 Anthropic**、**OpenRouter** 和 **Nous Portal** 上的 Claude，Hermes 会在系统 prompt 和 skill 块上附加 1 小时 TTL（`ttl: "1h"`）的 `cache_control` 断点。一个新的小时内第一次发送按完整的输入费率计费；同一小时内任何会话中的后续发送都会以折扣后的缓存读取费率从缓存中获取。这意味着系统 prompt、已加载的 skill 内容以及任何长上下文内容的前面部分，会在第一个小时内于各个 `hermes` 会话和派生的子代理之间被复用。

Qwen Cloud（阿里云 DashScope）上游把缓存 TTL 限制在 5 分钟，因此 Hermes 在那里改用 5 分钟的断点 TTL。其他通过第三方访问 Claude 的途径（AWS Bedrock、Azure Foundry）会回退到 provider 自己的缓存默认值。xAI Grok 使用另一种按会话固定的 conversation-id 机制——参见 [xAI prompt 缓存](/integrations/providers#xai-grok--responses-api--prompt-caching)。

没有用于禁用它的开关——缓存始终开启，即使在单轮对话中也能省钱，因为仅系统 prompt 就占输入 token 数的相当一部分。

唯一显式的开关是 Hermes 在 Anthropic 风格断点上请求的缓存 TTL 档位：

```yaml
prompt_caching:
  cache_ttl: "5m"   # "5m" 或 "1h"（Anthropic 支持的档位）；其他值会被忽略
```

`cache_ttl` 选择 Hermes 通过原生 Anthropic API、OpenRouter 和 Nous Portal 为 Claude 附加的断点 TTL。只有 Anthropic 支持的两个档位（`"5m"`、`"1h"`）会被遵循——其他任何值都会被忽略。具有自身上限的 provider（例如最长 5 分钟的 Qwen Cloud）仍会被限制在上游允许的范围内。

## 辅助模型 {#auxiliary-models}

Hermes 使用"辅助"模型处理图像分析、浏览器截图分析、会话标题生成和上下文压缩等附带任务。默认情况下（`auxiliary.*.provider: "auto"`），Hermes 会把每个辅助任务路由到你的**主聊天模型**——即你在 `hermes model` 中选择的同一个 provider/模型。入门时你无需配置任何内容，但要注意在昂贵的推理模型（Opus、MiniMax M2.7 等）上，辅助任务会带来可观的开销。如果你希望无论主模型是什么，附带任务都又便宜又快，请显式设置 `auxiliary.<task>.provider` 和 `auxiliary.<task>.model`（例如用 OpenRouter 上的 Gemini Flash 处理视觉任务）。（网页提取不是辅助任务：`web_extract` 和浏览器快照会以确定性的方式截断长内容，并保存完整文本以供 `read_file` 分页读取——不涉及 LLM。）

:::note 为什么 "auto" 使用你的主模型
早期版本会把聚合器用户（OpenRouter、Nous Portal）分配到 provider 端的一个便宜默认模型上。这令人意外——为聚合器订阅付费的用户会看到由另一个模型处理他们的辅助流量。现在 `auto` 对所有人都使用主模型，而 `config.yaml` 中的按任务覆盖仍然优先（参见下文的[完整辅助配置参考](#full-auxiliary-config-reference)）。
:::

### 交互式配置辅助模型 {#configuring-auxiliary-models-interactively}

无需手动编辑 YAML，运行 `hermes model` 并从菜单中选择 **"Configure auxiliary models"**。你会得到一个交互式的按任务选择器：

```
$ hermes model
→ Configure auxiliary models

[ ] vision               currently: auto / main model
[ ] title_generation     currently: openrouter / google/gemini-3-flash-preview
[ ] tts_audio_tags       currently: auto / main model
[ ] compression          currently: auto / main model
[ ] approval             currently: auto / main model
[ ] triage_specifier     currently: auto / main model
[ ] kanban_decomposer    currently: auto / main model
[ ] profile_describer    currently: auto / main model
[ ] delegation           currently: auto / inherit main agent
```

选择一个任务，选择一个 provider（OAuth 流程会打开浏览器；API 密钥类 provider 会提示输入），再选择一个模型。更改会持久化到 `config.yaml` 中的 `auxiliary.<task>.*`。与主模型选择器使用相同的机制——无需学习额外的语法。

**Delegation** 条目比较特殊：它路由 `delegate_task` 子代理所使用的模型，并持久化到顶层的 `delegation.*` 部分（`delegation.provider` / `delegation.model`），而不是 `auxiliary.*`，因为子代理是完整的子 agent，而不是附带的 LLM 调用。它的 `auto` 表示"继承父 agent 的 provider、模型和凭据"。

如果你不希望 Hermes 在第一次交流后自动生成标题，请设置
`auxiliary.title_generation.enabled: false`。手动标题仍可通过
`/title` 和 `hermes sessions rename` 设置。

### 仅支持流式的端点 {#stream-only-endpoints}

一些 OpenAI 兼容端点会直接拒绝非流式聊天请求（例如 Tencent Copilot 会返回 HTTP 400 `"Non-stream chat request is currently not supported"`）。交互式聊天本来就是流式的，但辅助任务（标题生成、压缩、视觉）使用非流式调用，因此每次尝试都会失败。Hermes 始终把 `copilot.tencent.com` 视为仅支持流式；对于其他任何此类端点，请在 `auxiliary.stream_only_base_urls` 下列出一个 URL 子串：

```yaml
auxiliary:
  stream_only_base_urls:
    - "my-stream-only-proxy.example.com"
```

匹配的辅助调用会以 `stream=True` 发送，数据块（包括工具调用的增量）会在客户端聚合——对其他任何端点都没有行为变化。

### 视频教程 {#video-tutorial}

<div style={{position: 'relative', width: '100%', aspectRatio: '16 / 9', marginBottom: '1.5rem'}}>
  <iframe
    src="https://www.youtube.com/embed/NoF-YajElIM"
    title="Hermes Agent — Auxiliary Models Tutorial"
    style={{position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', border: 0}}
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
    allowFullScreen
  />
</div>

### 通用配置模式 {#the-universal-config-pattern}

Hermes 中的每个模型槽位——辅助任务、压缩、fallback——都使用相同的三个开关：

| 键 | 作用 | 默认值 |
|-----|-------------|---------|
| `provider` | 用于认证和路由的 provider | `"auto"` |
| `model` | 要请求的模型 | provider 的默认模型 |
| `base_url` | 自定义 OpenAI 兼容端点（覆盖 provider） | 未设置 |

辅助任务块还额外接受一个 `reasoning_effort` 开关：

| 键 | 作用 | 默认值 |
|-----|-------------|---------|
| `reasoning_effort` | 该任务 LLM 调用的思考级别：`none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra` | 未设置（provider 默认值） |

它是全局 `agent.reasoning_effort` 的按任务对应项：当你的主模型是昂贵的推理模型时，可以把压缩设为 `low`、把视觉设为 `none`，以降低附带任务的延迟和开销，而不影响你的主聊天行为。它适用于 `vision`、`compression`、`title_generation` 和 `curator` 等辅助客户端任务，覆盖全部三种辅助协议格式（chat completions、Codex Responses、Anthropic Messages）。同一任务上显式的 `extra_body.reasoning` 优先于这一简写。

**后台审查有所不同：** 同模型的审查分支总是继承父 agent 的推理强度。在该路径上 `auxiliary.background_review.reasoning_effort` 会被忽略，包括父 provider/模型被显式选择的情况。这是为了保持推理设置、系统 prompt、完整对话快照和工具定义逐字节一致，以实现 prompt 缓存对齐；同模型审查没有独立的强度开关。参见 [后台审查的推理设置](/user-guide/features/memory#same-model-review-reasoning)。单独的路由分支强度问题在 [#94825](https://github.com/NousResearch/hermes-agent/issues/94825) 中跟踪。

**MoA 也使用不同的配置：** Mixture-of-Agents 的推理深度是在 MoA 预设中**按槽位**配置的（`moa.presets.<name>.reference_models[].reasoning_effort` / `aggregator.reasoning_effort`），而不是在 `moa_reference`/`moa_aggregator` 辅助块上——参见 [Mixture of Agents](/user-guide/features/mixture-of-agents)。

```yaml
auxiliary:
  compression:
    reasoning_effort: "low"    # 摘要不需要深度思考
  vision:
    reasoning_effort: "none"   # 为图像描述禁用思考
```

设置了 `base_url` 时，Hermes 会忽略 provider，直接调用该端点（使用 `api_key` 或 `OPENAI_API_KEY` 认证）。只设置了 `provider` 时，Hermes 使用该 provider 内置的认证和 base URL。

辅助任务可用的 provider：`auto`、`main`，以及 [provider 注册表](/reference/environment-variables)中的任何 provider——`openrouter`、`nous`、`openai-codex`、`copilot`、`copilot-acp`、`anthropic`、`gemini`、`qwen-oauth`、`zai`、`kimi-coding`、`kimi-coding-cn`、`minimax`、`minimax-cn`、`minimax-oauth`、`deepseek`、`nvidia`、`xai`、`xai-oauth`、`ollama-cloud`、`alibaba`、`bedrock`、`huggingface`、`arcee`、`xiaomi`、`kilocode`、`opencode-zen`、`opencode-go`、`opencode-free`、`commandcode`、`commandcode-anthropic`、`ai-gateway`、`azure-foundry`——或你 `providers:` 字典中的任何具名自定义 provider（例如 `provider: "beans"`）。

:::tip MiniMax OAuth
`minimax-oauth` 通过浏览器 OAuth 登录（无需 API 密钥）。运行 `hermes model` 并选择 **MiniMax (OAuth)** 进行认证。辅助任务会自动使用 `MiniMax-M2.7-highspeed`。参见 [MiniMax OAuth 指南](../guides/minimax-oauth.md)。
:::

:::tip xAI Grok OAuth
`xai-oauth` 为 SuperGrok 和 X Premium+ 订阅用户提供浏览器 OAuth 登录（无需 API 密钥）。运行 `hermes model` 并选择 **xAI Grok OAuth (SuperGrok / Premium+)** 进行认证。同一个 OAuth token 会被复用于每一个直连 xAI 的界面（聊天、辅助任务、TTS、图像生成、视频生成、转录）。参见 [xAI Grok OAuth 指南](../guides/xai-grok-oauth.md)；如果 Hermes 运行在远程主机上，请参阅 [通过 SSH / 远程主机进行 OAuth](../guides/oauth-over-ssh.md)。
:::

:::warning `"main"` 仅用于辅助任务
`"main"` provider 选项的意思是"使用我的主 agent 所用的 provider"——它只在 `auxiliary:`、`compression:` 以及主 fallback 条目（`fallback_providers:` 或旧版的 `fallback_model:`）中有效。它**不是**顶层 `model.provider` 设置的有效值。如果你使用自定义的 OpenAI 兼容端点，请在 `model:` 部分中设置 `provider: custom`。所有主模型 provider 选项请参阅 [AI Providers](/integrations/providers)。
:::

### 完整辅助配置参考 {#full-auxiliary-config-reference}

```yaml
auxiliary:
  # 图像分析（vision_analyze 工具 + 浏览器截图）
  vision:
    provider: "auto"           # "auto"、"openrouter"、"nous"、"codex"、"main" 等
    model: ""                  # 例如 "openai/gpt-4o"、"google/gemini-2.5-flash"
    base_url: ""               # 自定义 OpenAI 兼容端点（覆盖 provider）
    api_key: ""                # base_url 使用的 API 密钥（回退到 OPENAI_API_KEY）
    timeout: 120               # 秒——LLM API 调用超时；视觉负载需要较宽松的超时
    download_timeout: 30       # 秒——图像 HTTP 下载；连接较慢时请调高
    max_concurrency: 8         # 整个进程中并发的图像编码/缩放突发的上限
                               # （默认：宿主 CPU 核心数，无上限）—— 只约束
                               # CPU 密集的编码步骤，使视频帧的扇出无法占满
                               # 所有核心并饿死事件循环；LLM 调用仍完全并发。
                               # 最小值为 1；小于 1 的值会被忽略。

  # 危险命令审批分类器
  approval:
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
    timeout: 30                # 秒

  # Gemini 3.1 TTS 隐藏音频标签插入
  tts_audio_tags:
    provider: "auto"
    model: ""                  # 为空 = 主聊天模型
    base_url: ""
    api_key: ""
    timeout: 30

  # 上下文压缩超时（独立于 compression.* 配置）
  compression:
    timeout: 120               # 秒——压缩需要对长对话做摘要，需要更多时间
    # fallback_chain:           # 可选——在限流 / 连接失败时尝试的 provider
    #   - provider: nous
    #     model: deepseek/deepseek-chat
    #   - provider: openrouter
    #     model: google/gemini-2.5-flash
    #     base_url: ""
    #     api_key: ""
    # max_concurrency: 2       # 可选：限制同时进行的压缩 LLM 调用数，
                               # 避免多个会话在降级的 provider 上堆积重试

  # 自动生成的会话标题。language 为空时跟随对话语言；
  # 设为例如 "English" 或 "Japanese" 可把标题固定为某一种语言。
  title_generation:
    enabled: true              # 设为 false 可禁用自动标题生成
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
    timeout: 30
    language: ""

  # Skills hub——skill 匹配与搜索
  skills_hub:
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
    timeout: 30

  # MCP 工具分派
  mcp:
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
    timeout: 30

  # 第一次交流后自动生成的简短会话标题
  title_generation:
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
    timeout: 30
    # max_concurrency: 2       # 可选：限制同时进行的标题生成调用数

  # Kanban 分诊细化器——`hermes kanban specify <id>`（或 dashboard 中
  # Triage 列卡片上的 ✨ Specify 按钮）使用该槽位
  # 把一句话扩展成具体的规格，并把任务提升到 `todo`。
  # 便宜快速的模型在这里表现很好；规格扩展
  # 很短，不需要推理深度。
  triage_specifier:
    provider: "auto"
    model: ""
    base_url: ""
    api_key: ""
    timeout: 120
```

:::tip
每个辅助任务都有可配置的 `timeout`（单位：秒）。默认值：vision 120 秒、approval 30 秒、compression 120 秒。如果你为辅助任务使用较慢的本地模型，请调高这些值。Vision 还有一个单独的 `download_timeout`（默认 30 秒）用于 HTTP 图像下载——连接较慢或使用自托管图像服务器时请调高它。
:::

:::info
上下文压缩有自己的 `compression:` 块用于阈值，以及一个 `auxiliary.compression:` 块用于模型/provider 设置——参见上文的[上下文压缩](#context-compression)。主 fallback 链使用顶层的 `fallback_providers:` 列表——参见 [Fallback Providers](/integrations/providers#fallback-providers)。三者都遵循相同的 provider/model/base_url 模式。
:::

### 辅助任务的按任务 fallback 链 {#per-task-fallback-chain-for-auxiliary-tasks}

每个辅助任务都可以选择定义一个 `fallback_chain`——由 provider/模型条目组成的列表，当主辅助 provider 因限流、连接问题或付费限制而失败时，Hermes 会依次尝试这些条目：

```yaml
auxiliary:
  compression:
    provider: openrouter
    model: openai/gpt-4o-mini
    fallback_chain:
      - provider: nous
        model: deepseek/deepseek-chat
      - provider: openrouter
        model: google/gemini-2.5-flash
```

当主辅助 provider（`openrouter` / `openai/gpt-4o-mini`）返回限流、连接超时或需要付费的错误时，Hermes 会按顺序遍历 `fallback_chain`。它会跳过 provider 与已失败 provider 相同的条目，并依次尝试其余每个条目，直到某个成功或链条耗尽。如果所有 fallback 都失败，Hermes 会回退到主 agent 模型作为最后的保障。

每个条目支持与任意辅助任务配置相同的三个开关：

| 键 | 说明 |
|-----|-------------|
| `provider` | Provider 名称（`nous`、`openrouter`、`anthropic`、`gemini`、`main` 等） |
| `model` | 该 provider 的模型名称 |
| `base_url` | （可选）自定义 OpenAI 兼容端点 |

`fallback_chain` 可用于任何辅助任务——`compression`、`vision`、`approval`、`skills_hub`、`mcp` 等。

### 限制辅助任务并发 {#limiting-auxiliary-concurrency}

`max_concurrency` 在整个进程范围内限制 `compression` 和 `title_generation` 等辅助任务正在进行的 LLM 调用数。`auxiliary.vision.max_concurrency` 不在此列：它本来就只控制视觉任务中 CPU 密集的图像编码/缩放工作线程，而不是 LLM 请求。它在以下情况最有用：

- 许多会话可能同时启动后台工作（Discord/Telegram 频道、多个终端）
- 你的 provider 受到限流或正在发生故障，重试会放大突发流量

默认不限制。一个典型的安全上限是 `2`：

```yaml
auxiliary:
  title_generation:
    max_concurrency: 2
  compression:
    max_concurrency: 2
```

该信号量包裹整个调用，包括重试和 fallback，因此一次缓慢的调用只会被计入上限一次。

### 辅助任务的 OpenRouter 路由与 Pareto Code {#openrouter-routing--pareto-code-for-auxiliary-tasks}

当某个辅助任务解析到 OpenRouter 时（无论是显式指定，还是在主 agent 使用 OpenRouter 时通过 `provider: "main"`），主 agent 的 `provider_routing` 和 `openrouter.min_coding_score` 设置**不会传递**过去——按照设计，每个辅助任务都是独立的。要为特定辅助任务设置 OpenRouter 的 provider 偏好或使用 [Pareto Code 路由器](/integrations/providers#openrouter-pareto-code-router)，请通过 `extra_body` 按任务设置：

```yaml
auxiliary:
  compression:
    provider: openrouter
    model: openrouter/pareto-code         # 为该任务使用 Pareto Code 路由器
    extra_body:
      provider:                            # OpenRouter provider 路由偏好
        order: [anthropic, google]         # 按顺序尝试这些 provider
        sort: throughput                   # 或 "price" | "latency"
        # only: [anthropic]                # 限制为特定 provider
        # ignore: [deepinfra]              # 排除特定 provider
      plugins:                             # OpenRouter Pareto Code 路由器开关
        - id: pareto-router
          min_coding_score: 0.5            # 0.0–1.0；越高 = 编码能力越强
```

其结构与 OpenRouter 在 chat completions 请求体中接受的格式一致。Hermes 会原样转发整个 `extra_body`，因此 [openrouter.ai/docs](https://openrouter.ai/docs) 中记载的任何其他 OpenRouter 请求体字段也同样适用。

### 更换视觉模型 {#changing-the-vision-model}

要使用 GPT-4o 而不是 Gemini Flash 进行图像分析：

```yaml
auxiliary:
  vision:
    model: "openai/gpt-4o"
```

或通过环境变量（在 `~/.hermes/.env` 中）：

```bash
AUXILIARY_VISION_MODEL=openai/gpt-4o
```

### Provider 选项 {#provider-options}

这些选项适用于**辅助任务配置**（`auxiliary:`、`compression:`）以及主 fallback 条目（`fallback_providers:` 或旧版的 `fallback_model:`），而不适用于你的主 `model.provider` 设置。

| Provider | 说明 | 要求 |
|----------|-------------|-------------|
| `"auto"` | 最佳可用选项（默认）。视觉任务依次尝试 OpenRouter → Nous → Codex。 | — |
| `"openrouter"` | 强制使用 OpenRouter——可路由到任意模型（Gemini、GPT-4o、Claude 等） | `OPENROUTER_API_KEY` |
| `"nous"` | 强制使用 Nous Portal | `hermes auth` |
| `"codex"` | 强制使用 Codex OAuth（ChatGPT 账号）。支持视觉（gpt-5.3-codex）。 | `hermes model` → ChatGPT 或 Codex 订阅 |
| `"minimax-oauth"` | 强制使用 MiniMax OAuth（浏览器登录，无需 API 密钥）。辅助任务使用 MiniMax-M2.7-highspeed。 | `hermes model` → MiniMax (OAuth) |
| `"xai-oauth"` | 强制使用 xAI Grok OAuth（面向 SuperGrok 或 X Premium+ 订阅用户的浏览器登录，无需 API 密钥）。同一个 OAuth token 涵盖聊天、TTS、图像、视频和转录。 | `hermes model` → xAI Grok OAuth (SuperGrok / Premium+) |
| `"main"` | 使用你当前生效的自定义/主端点。它可以来自 `OPENAI_BASE_URL` + `OPENAI_API_KEY`，也可以来自通过 `hermes model` / `config.yaml` 保存的自定义端点。适用于 OpenAI、本地模型或任何 OpenAI 兼容 API。**仅用于辅助任务——对 `model.provider` 无效。** | 自定义端点凭据 + base URL |

当你希望附带任务绕过默认路由器时，主 provider 目录中的直连 API 密钥类 provider 在这里同样可用。例如，配置了 `GMI_API_KEY` 后 `gmi` 即有效，配置了 `FIREWORKS_API_KEY` 后 `fireworks` 即有效：

```yaml
auxiliary:
  compression:
    provider: "gmi"
    model: "anthropic/claude-opus-4.6"
```

对于 GMI 辅助路由，请使用 GMI 的 `/v1/models` 端点返回的确切模型 ID。Fireworks 的模型 ID 使用该 provider 原生的斜杠形式，例如 `accounts/fireworks/models/glm-5p2`。

### 常见配置 {#common-setups-1}

**使用直连的自定义端点**（对于本地/自托管 API，比 `provider: "main"` 更清晰）：
```yaml
auxiliary:
  vision:
    base_url: "http://localhost:1234/v1"
    api_key: "local-key"
    model: "qwen2.5-vl"
```

`base_url` 优先于 `provider`，因此这是将辅助任务路由到特定端点最明确的方式。对于直连端点覆盖，Hermes 使用配置的 `api_key`，或回退到 `OPENAI_API_KEY`；它不会为该自定义端点复用 `OPENROUTER_API_KEY`。

**使用 OpenAI API 密钥处理视觉任务：**
```yaml
# In ~/.hermes/.env:
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_API_KEY=sk-...

auxiliary:
  vision:
    provider: "main"
    model: "gpt-4o"       # 或用更便宜的 "gpt-4o-mini"
```

**使用 OpenRouter 处理视觉任务**（可路由到任意模型）：
```yaml
auxiliary:
  vision:
    provider: "openrouter"
    model: "openai/gpt-4o"      # 或 "google/gemini-2.5-flash" 等
```

**使用 Codex OAuth**（ChatGPT Pro/Plus 账号——无需 API 密钥）：
```yaml
auxiliary:
  vision:
    provider: "codex"     # 使用你的 ChatGPT OAuth token
    # model 默认为 gpt-5.3-codex（支持视觉）
```

**使用 MiniMax OAuth**（浏览器登录，无需 API 密钥）：
```yaml
model:
  default: MiniMax-M2.7
  provider: minimax-oauth
  base_url: https://api.minimax.io/anthropic
```
运行 `hermes model` 并选择 **MiniMax (OAuth)** 即可登录并自动完成这一设置。对于中国区，base URL 为 `https://api.minimaxi.com/anthropic`。完整演练请参阅 [MiniMax OAuth 指南](../guides/minimax-oauth.md)。

**使用本地/自托管模型：**
```yaml
auxiliary:
  vision:
    provider: "main"      # 使用你当前生效的自定义端点
    model: "my-local-model"
```

`provider: "main"` 使用 Hermes 在普通聊天中所用的任何 provider——无论是具名的自定义 provider（例如 `beans`）、像 `openrouter` 这样的内置 provider，还是旧版的 `OPENAI_BASE_URL` 端点。

:::tip
如果你使用 Codex OAuth 作为主模型 provider，视觉功能会自动可用——无需额外配置。Codex 已包含在视觉任务的自动检测链中。
:::

:::warning
**视觉任务需要多模态模型。** 如果你设置了 `provider: "main"`，请确保你的端点支持多模态/视觉——否则图像分析会失败。
:::

### 环境变量（旧版） {#environment-variables-legacy}

辅助模型也可以通过环境变量配置。不过，`config.yaml` 是首选方式——它更易于管理，并支持包括 `base_url` 和 `api_key` 在内的所有选项。

| 设置 | 环境变量 |
|---------|---------------------|
| 视觉 provider | `AUXILIARY_VISION_PROVIDER` |
| 视觉模型 | `AUXILIARY_VISION_MODEL` |
| 视觉端点 | `AUXILIARY_VISION_BASE_URL` |
| 视觉 API 密钥 | `AUXILIARY_VISION_API_KEY` |

压缩和 fallback 模型设置只能在 config.yaml 中配置。（`AUXILIARY_WEB_EXTRACT_*` 变量已过时——网页提取不再使用辅助 LLM。）

:::tip
运行 `hermes config` 查看你当前的辅助模型设置。只有与默认值不同的覆盖项才会显示。
:::

## 推理强度 {#reasoning-effort}

控制模型在回复之前进行多少"思考"：

```yaml
agent:
  reasoning_effort: ""   # 为空 = medium。可选：none、minimal、low、medium、high、xhigh、max、ultra
```

未设置时（默认），推理强度默认为 "medium"——一个适用于大多数任务的平衡级别。设置一个值会覆盖它——更高的推理强度能在复杂任务上获得更好的结果，代价是更多的 token 和延迟。

:::note 通过 OpenRouter 使用的自适应思考模型（Claude 4.6+、Fable/Mythos 级别）
这些模型使用*自适应*思考，不接受常规的 `reasoning.effort`
字段——OpenRouter 会对它们忽略该字段。Hermes 会透明地把你的
`reasoning_effort` 路由到 OpenRouter 的 `verbosity` 参数（它映射到
Anthropic 的 `output_config.effort`），因此同一个强度开关在所选模型支持的级别内依然有效。`none`（或未设置）会让模型保持其自身的自适应默认值。原生 Anthropic provider 本来就直接控制强度，不受影响。
:::

:::note OpenRouter 模型与支持的强度级别
对于通过 OpenRouter 路由的其他模型，Hermes 会读取实时模型目录中的推理元数据（`supported_parameters` + 按模型的
`reasoning.supported_efforts`），以决定是否发送推理控制，并把你请求的强度限制到该路由实际支持的最接近级别（总是向下——例如在最高只支持 `high` 的路由上，`ultra` 会变成 `high`，永远不会被静默升级）。新的支持推理的厂商无需等待 Hermes 更新即可自动工作；当目录无法访问或模型未被列出时，Hermes 会回退到其内置的模型系列列表，并原样传递你的强度设置。
:::

你也可以在运行时用 `/reasoning` 命令更改推理强度：

```
/reasoning                # 显示当前强度级别和显示状态
/reasoning high           # 将推理强度设为 high（仅当前会话）
/reasoning high --global  # 设置强度并持久化到 config.yaml
/reasoning none           # 禁用推理（仅当前会话）
/reasoning show           # 在每条回复上方显示模型的思考内容
/reasoning hide           # 隐藏模型的思考内容
```

强度更改默认只作用于当前会话；添加 `--global` 可将新级别保存为你的 `agent.reasoning_effort` 默认值。

#### 按模型的推理覆盖 {#per-model-reasoning-overrides}

你可以为不同的模型设置不同的推理强度级别。当你希望复杂模型使用高推理强度、而更快的模型使用中等强度时，这很有用：

```yaml
agent:
  reasoning_effort: "medium"       # 全局默认值
  reasoning_overrides:
    "openrouter/anthropic/claude-opus-4.5": "xhigh"
    "openai/gpt-5": "low"
    "claude-sonnet-4.6": "high"    # 裸模型名称同样有效
```

键的匹配**容忍拼写差异**——任何合理的拼写都能匹配：
- `claude-opus-4.5`、`claude-opus-4-5`、`claude-opus.4.5`（点号和连字符可以互换）
- `anthropic/claude-opus-4.5`、`openrouter/anthropic/claude-opus-4.5`（provider 前缀可选）
- 精确匹配优先于变体

:::note
`reasoning_overrides` 的键不支持 `hermes config set`——请直接编辑 YAML 文件。这是因为模型名称常常包含点号（例如 `claude-opus-4.5`），与 CLI 的点分键语法相冲突。
:::

**解析优先级：**

1. 会话范围的 `/reasoning --session` 覆盖（仅 gateway）
2. 来自 `agent.reasoning_overrides` 的按模型覆盖（容忍拼写差异）
3. 全局的 `agent.reasoning_effort`
4. Provider 默认值

该覆盖在所有地方自动生效：CLI 启动、消息 gateway、Desktop/TUI、cron 任务、会话中途的 `/model` 切换以及 fallback 模型激活。

## 快速模式 {#fast-mode}

快速模式会以溢价向 provider 请求更快的输出：OpenAI [Priority Processing](https://openai.com/api-priority-processing/)（`service_tier: priority`）、Grok 4.6 上的 xAI Priority Processing，以及 Anthropic [Fast Mode](https://platform.claude.com/docs/en/build-with-claude/fast-mode)（`speed: fast`，仅限 Opus 4.8 / Opus 5）。它**默认关闭**。

```yaml
agent:
  service_tier: ""          # "" / normal | fast | auto | cold
  fast_auto_seconds: 60     # auto / cold 的时间窗口
```

| 模式 | 何时发送快速参数 | 适用场景 |
|------|---------------------------|------------|
| `normal`（默认，`""`） | 从不 | 最便宜；标准延迟 |
| `fast` | 每个请求 | 你始终需要速度的长时间交互会话 |
| `auto` | **每个**轮次的前 `fast_auto_seconds` 内的请求 | 第一条回复更迅速；长时间的工具循环回退到标准定价 |
| `cold` | 同样的窗口，但只在会话的**第一个轮次**（没有先前历史） | 快速的首次回复，之后按标准定价 |

`/fast normal|fast|auto|cold` 为当前会话切换模式；添加 `--global` 可持久化到 `config.yaml`。单独的 `/fast` 显示当前模式。

**费用说明：** 两家 provider 都以标准费率的倍数对快速请求计费（Anthropic：Opus 4.8 和 Opus 5 上输入/输出为每百万 token $10 / $50），并与 prompt 缓存定价叠加。`auto`/`cold` 把这部分溢价限制在时间窗口内。快速参数只会发送给支持它们的第一方端点（`api.openai.com` / Codex 订阅、`api.anthropic.com`、`api.x.ai`）；OpenRouter、Nous Portal、Copilot、Azure、Bedrock 和自定义 `base_url` 路由在任何模式下都不会收到它们。请求之间只有按请求的参数会变化——系统 prompt、工具和消息保持逐字节一致，因此 prompt 缓存可以跨越时间窗口边界保留。

## 工具使用强制 {#tool-use-enforcement}

有些模型偶尔会用文字描述打算执行的操作，而不是发起工具调用（"我会运行测试……"，而不是真正调用终端）。工具使用强制会注入系统 prompt 指导，引导模型回到真正调用工具的方式上。

```yaml
agent:
  tool_use_enforcement: "auto"   # "auto" | true | false | ["model-substring", ...]
```

| 值 | 行为 |
|-------|----------|
| `"auto"`（默认） | 对匹配以下名称的模型启用：`gpt`、`codex`、`gemini`、`gemma`、`grok`、`glm`、`qwen`、`deepseek`、`muse`。对其他所有模型（例如 Claude）禁用。 |
| `true` | 始终启用，无论使用哪个模型。当你注意到当前模型在描述操作而不是执行操作时很有用。 |
| `false` | 始终禁用，无论使用哪个模型。 |
| `["gpt", "codex", "qwen", "llama"]` | 仅当模型名称包含所列子串之一（不区分大小写）时启用。 |

### 它注入的内容 {#what-it-injects}

启用后，系统 prompt 中可能会加入两层指导：

1. **通用的工具使用强制**（所有匹配的模型）——指示模型立即发起工具调用而不是描述意图，持续工作直到任务完成，并且永远不要以承诺未来行动的方式结束一个轮次。

2. **Google 操作指导**（仅限 Gemini 和 Gemma 模型）——简洁性、绝对路径、并行工具调用以及编辑前先验证等模式。

这些对用户是透明的，只影响系统 prompt。本来就能可靠使用工具的模型（例如 Claude）不需要这些指导，这就是 `"auto"` 排除它们的原因。

### 何时开启 {#when-to-turn-it-on}

如果你使用的模型不在默认的自动列表中，并且注意到它经常描述它*会*做什么而不是真正去做，请设置 `tool_use_enforcement: true`，或把该模型的子串加入列表：

```yaml
agent:
  tool_use_enforcement: ["gpt", "codex", "gemini", "grok", "my-custom-model"]
```

## 执行纪律指导 {#execution-discipline-guidance}

与工具使用强制分开，Hermes 会为一些模型系列注入一个**执行纪律**块，这些模型系列在评测轨迹中表现出一组共同的 agent 失败模式：用文字而不是代码做算术、在外部写入之后跳过回读验证、"修复"格式错误的标识符、在数量不匹配时仍声称已完整，以及在未验证每一条验收标准的情况下就宣布"完成"。

```yaml
agent:
  execution_guidance: "auto"   # "auto" | true | false | ["model-substring", ...]
```

| 值 | 行为 |
|-------|----------|
| `"auto"`（默认） | 对匹配以下名称的模型启用：`gpt`、`codex`、`grok`、`deepseek`、`kimi`、`qwen`、`glm`、`minimax`、`mimo`、`mistral`、`muse`。 |
| `true` | 始终启用，无论使用哪个模型。 |
| `false` | 始终禁用，无论使用哪个模型。 |
| `["deepseek", "my-custom-model"]` | 仅当模型名称包含所列子串之一（不区分大小写）时启用。 |

注入的块涵盖：

- **工具坚持** —— 持续调用工具，直到任务完成*并且*经过验证；在下结论之前，对空的、部分的或可疑地狭窄的查找结果，用更宽泛或不同的查询重试。
- **强制使用工具** —— 算术、哈希、日期、系统状态和文件事实总是来自工具，而绝不来自心算。
- **外部写入回读** —— 在对外部系统进行任何改变状态的写入之后，先回读确切的目标再声称成功（工具已经确认过的内部文件编辑不会被重复验证）。
- **数量核对** —— 声明的总数（`total`、`reply_count`、`has_more`）是硬性断言；出现不一致时，重新获取或以程序方式解析。
- **字面值保留** —— 永远不要规范化或"修复"不符合既定格式的标识符；一次成功的查找并不能证明格式错误的源 token 是有效的。
- **以验证为关卡的完成** —— "完成"意味着每一条列出的验收标准都已验证，而绝不是一个看似合理的子集。

该关卡独立于 `tool_use_enforcement`——二者可以各自单独开启。该指导会在会话开始时根据模型名称一次性选定，因此系统 prompt 在整个对话期间保持逐字节稳定（对 prompt 缓存友好）。Gemini/Gemma 被排除在自动列表之外，因为它们会收到更具体的 Google 操作指导；Claude 被排除是因为它不会表现出这些失败模式——可以用 `true` 或子串列表让任何模型选择加入。

## 工具循环护栏 {#tool-loop-guardrails}

Hermes 会检测 agent 何时陷入无效的工具调用循环——同一个工具调用反复失败、同一个工具一次又一次失败，或一个幂等调用在没有任何进展的情况下返回相同的结果。默认情况下，它会在工具结果中注入一条**警告**，让模型自我纠正。交互式的 CLI、TUI、Desktop 和 ACP 会话保持仅警告，因为有人可以介入；无人值守的 gateway 和 cron 会话默认启用硬性停止。

对于无人值守的部署，可以禁用这一感知平台的默认行为，也可以在所有平台上显式启用硬性停止：

```yaml
tool_loop_guardrails:
  warnings_enabled: true       # 在工具结果中注入警告（默认：true）
  hard_stop_enabled: false     # 超过硬性停止阈值时还会**阻止**调用（默认：false）
  non_interactive_hard_stop_enabled: true  # gateway/cron 的默认硬性停止
  warn_after:
    exact_failure: 2           # 完全相同的失败调用重复 N 次
    same_tool_failure: 3       # 同一个工具失败 N 次（参数不同）
    idempotent_no_progress: 2  # 相同结果、没有进展，N 次
  hard_stop_after:
    exact_failure: 5
    same_tool_failure: 8
    idempotent_no_progress: 5
  loop_caps:
    max_web_searches: 50       # 每轮最多 web_search 调用次数（0 = 不限制）
    max_subagents: 50          # 每轮最多派生的子代理数（0 = 不限制）
```

`hard_stop_enabled` 会在所有平台上显式启用硬性停止。当它保持 `false` 时，`non_interactive_hard_stop_enabled` 仍会为无人值守的 gateway/cron 类平台启用硬性停止，同时对 CLI、TUI、Desktop、ACP、子代理和 `api_server` 运行（有活跃父级或客户端的受监督任务循环）保留仅警告的行为。设置 `non_interactive_hard_stop_enabled: false` 可让无人值守的部署选择退出。另请参阅 [Docker / 无人值守部署](docker.md)。

硬性停止旨在捕获**重放**——同一个调用、毫无变化、中间什么也没发生——而不是合理的迭代：

- **编辑 → 重新运行永远不是循环。** 任何成功的变更类调用（`write_file`、`patch`、成功的 `terminal`/`execute_code`、浏览器操作、任务/消息/cron 变更）都会为所有仍在计数的失败调用标记进展。下一次完全相同的重试（修复后重新运行失败的测试、点击后重新快照）会开始一个新的计数，而不是继续累积直至被阻止。
- **不同的失败命令是诊断，而不是循环。** 对于非零退出本就是普通输出的工具（`terminal`、`execute_code`、进程轮询器、`browser_navigate`、`web_extract`），`same_tool_failure` 阈值只会警告，永远不会中止。只有中间没有任何变化的完全相同参数的重放，或结果完全相同的连续序列，才能让它们停止。
- **中止只结束当前轮次，而不是会话。** agent 会回复是哪条护栏触发了以及原因；回复"continue"即可在重置了每轮计数器的情况下继续。

### 每轮失控循环上限 {#per-turn-runaway-loop-caps}

与上面基于失败的阈值分开，`loop_caps` 为单个 agent 循环（轮次）可以发起的 `web_search` 调用次数和子代理派生数量设置了硬性上限。计数器在每轮开始时重置，因此合理的多轮会话永远不会被限制——但一个失控成无界搜索或委托循环的单轮会被停止。这些上限始终开启，并且无论 `hard_stop_enabled` 如何都会触发。单个轮次发起几十次网页搜索或派生几十个子代理本身就已经不正常，因此默认值较低。达到上限时，越界的工具调用会被阻止并附带说明信息，该轮会干净地停止，而不是耗尽剩余的预算。将任一值设为 `0` 可完全禁用对应的上限。

单次 `delegate_task` 批处理中的每个任务都会计入 `max_subagents`（3 个任务的批处理计 3 次），因此该上限追踪的是实际派生的子代理，而不是 `delegate_task` 的调用次数。

这与 Claude Code 的按会话 WebSearch 和子代理上限（v2.1.212）相对应，后者同样默认为 200，并在 `/clear` 时重置。

### 运行时防停滞防护 {#runtime-anti-stall-guards}

作为上面基于失败的护栏的补充，`agent.stall_guards`（默认 `true`）启用两个保守的运行时防护，以避免浪费轮次。第一个是**相同调用循环断路器**：当同一个工具以相同的参数被连续调用 3 次以上，*并且*返回相同的结果时，会在该工具结果后追加一行简短提示，告诉模型不要重复该调用——在仅警告的会话中它永远不会阻止调用，并且可以合理重复的轮询器（`process`、`*_get_result`、`*_poll`）会被豁免。当硬性停止生效时（显式的 `hard_stop_enabled`，或无人值守的 gateway/cron 平台），同样的连续序列在达到 `hard_stop_after.idempotent_no_progress` 次连续相同调用时也会变成硬性停止——适用于**任何**工具，而不仅是 `idempotent_no_progress` 护栏所追踪的只读工具——因此一个反复重放同一个成功的 `terminal` 或 `skill_view` 调用的模型会被中止，而不会耗尽迭代预算（`identical_call_streak_halt`）。第二个是**继续意图恢复**：当模型在没有任何工具调用的情况下结束一个轮次，但其简短回复的结尾是在宣布一个动作（"Let me now update the file…"）时，Hermes 会通过与意图确认恢复相同的有界续行机制重新提示它去执行（每轮最多 2 次重新提示）。两者都对缓存安全（提示是在构建结果时添加的，从不追溯修改），并且可以一起禁用：

```yaml
agent:
  stall_guards: false
```

同一个开关还会启用**结果引用占位**：当重新发出的相同工具调用返回逐字节相同的新结果时，重复的负载会以一个简短的引用占位进入上下文，指向先前的结果（工具名称、`tool_call_id`、参数摘要，以及——如果第一次结果被持久化到磁盘——其溢出路径），而不是重复完整输出。工具每次仍会执行，因此轮询语义得以保留：变化了的结果总是会被完整传递。小于 512 个字符的结果、错误结果和多模态结果永远不会被占位替换，而轮询器*会*被占位替换（一次没有变化的轮询恰恰是重复负载不携带任何信息的情况）。

### 轮次存活看门狗 {#turn-liveness-watchdog}

`agent.turn_liveness` 限制一个对话轮次在 Hermes 强制恢复它之前可以**没有任何可观察进展**的时长。看门狗依据活动时钟（与标记 API 等待、流式 token 和工具心跳的是同一个信号——租约续期从不计入），因此一个在中途静默卡住的轮次（即 issue #95548 中观察到的情况：没有工具执行、没有 API 调用、没有错误，但会话一直处于"忙碌"状态）会被高调地报告出来、被中断从而以可重试的中断轮次方式展开，并且——当中断无法解开卡住的状态时——其持久的轮次租约会停止续期，这样过期轮次清理就能回收该会话，而不是让它一直挂到进程被杀死。

```yaml
agent:
  turn_liveness:
    timeout_s: 600.0   # 空闲上限；<= 0 表示禁用看门狗
    poll_s: 15.0        # 采样间隔（秒）
```

合理的慢速工作不会受到惩罚：流式响应、工具心跳（工具运行期间每 30 秒一次）以及审批等待都会不断触碰时钟，因此只有在整个上限时间内*完全*没有进展的轮次才会触发看门狗。无效值（拼写错误、`NaN`、`Inf`、非正的 `poll_s`）会记录一条警告并回退到默认值——它们永远不会导致启动崩溃，也不会静默地禁用看门狗。一次触发的中止会在开始恢复时报告停滞，并且只有在中断真正提交之后才会发布最终的已中止/租约已停止结果。

## TTS 配置 {#tts-configuration}

```yaml
tts:
  provider: "edge"              # "edge" | "elevenlabs" | "openai" | "minimax" | "mistral" | "gemini" | "xai" | "neutts" | "kittentts" | "piper" | "deepinfra"
  speed: 1.0                    # 全局速度倍率（所有 provider 的回退值）
  edge:
    voice: "en-US-AriaNeural"   # 322 种声音，74 种语言
    speed: 1.0                  # 速度倍率（转换为速率百分比，例如 1.5 → +50%）
  elevenlabs:
    voice_id: "pNInz6obpgDQGcFmaJgB"
    model_id: "eleven_multilingual_v2"
  openai:
    model: "gpt-4o-mini-tts"
    voice: "alloy"              # alloy、echo、fable、onyx、nova、shimmer
    speed: 1.0                  # 速度倍率（API 会将其限制在 0.25–4.0）
    base_url: "https://api.openai.com/v1"  # 覆盖为 OpenAI 兼容的 TTS 端点
  minimax:
    speed: 1.0                  # 语速倍率
    # base_url: ""              # 可选：覆盖为 OpenAI 兼容的 TTS 端点
  mistral:
    model: "voxtral-mini-tts-2603"
    voice_id: "c69964a6-ab8b-4f8a-9465-ec0925096ec8"  # Paul - Neutral（默认）
  gemini:
    model: "gemini-2.5-flash-preview-tts"   # 或 gemini-3.1-flash-tts-preview
    voice: "Kore"               # 30 种预置声音：Zephyr、Puck、Kore、Enceladus 等
    audio_tags: false           # 隐藏的 Gemini 3.1 TTS 音频标签插入
    persona_prompt_file: ""      # 可选的 Markdown/文本文件，包含 Gemini 声音指导
  xai:
    voice_id: "eve"             # xAI TTS 声音
    language: "en"              # ISO 639-1
    sample_rate: 24000
    bit_rate: 128000            # MP3 比特率
    # base_url: "https://api.x.ai/v1"
  neutts:
    ref_audio: ''
    ref_text: ''
    model: neuphonic/neutts-air-q4-gguf
    device: cpu
```

这同时控制 `text_to_speech` 工具以及语音模式下的语音回复（CLI 或消息 gateway 中的 `/voice tts`）。

**速度回退层级：** provider 专属速度（例如 `tts.edge.speed`）→ 全局 `tts.speed` → 默认 `1.0`。设置全局 `tts.speed` 可在所有 provider 上应用统一速度，或按 provider 覆盖以进行更细粒度的控制。

## 显示设置 {#display-settings}

```yaml
display:
  tool_progress: all      # off | new | all | verbose
  tool_progress_command: false  # 在消息 gateway 中启用 /verbose 斜杠命令
  focus_view: false       # CLI 专注视图（/focus）——减少输出，仅影响显示
  platforms: {}           # 按平台的显示覆盖（见下文）
  interim_assistant_messages: true  # Gateway：把轮次中途自然的助手更新作为独立消息发送
  show_commentary: true   # Codex 模型：把 commentary 通道的进度叙述作为可见的中途更新投递
  skin: default           # 内置或自定义的 CLI 皮肤（参见 user-guide/features/skins）
  personality: ""         # 旧版装饰性字段，仍会出现在某些摘要中
  compact: false          # 紧凑输出模式（更少空白）
  cli_multiline_shortcuts: true  # CLI：Ctrl+J、\ + Enter 以及受支持的 Shift+Enter 插入换行（false = 旧版 c-j 提交回退）
  resume_display: full    # full（恢复时显示之前的消息）| minimal（仅一行）
  bell_on_complete: false # agent 完成时响铃（非常适合长任务）
  bell_on_prompt: false   # 阻塞式提示打开时响铃（clarify、审批、sudo 密码、机密采集）——通过 SSH 同样有效
  # 两个响铃标志还会发出 OSC 9 桌面通知（Ghostty、iTerm2、Kitty、WezTerm 会弹出系统
  # 通知；其他终端会忽略它），并且在 Warp 中（TERM_PROGRAM=WarpTerminal 且声明了 CLI-agent
  # 协议）发出 warp://cli-agent OSC 777 事件（完成时为 `stop`，阻塞式提示时为 `permission_request`），
  # 让 Warp 的标签页状态和通知信箱跟踪 Hermes。无需额外的键。
  show_reasoning: true    # 在每条回复上方显示模型的推理/思考（默认：true；用 /reasoning show|hide 切换）
  streaming: false        # 在 token 到达时流式输出到终端（实时输出）
  show_cost: false        # 在 CLI 状态栏中显示估算的 $ 费用
  timestamps: false       # 为 true 时，在 CLI / TUI 对话记录的用户和助手标签前加上时间戳
  timestamp_format: "%H:%M"  # 这些时间戳的 strftime 格式（例如用 "%b-%d %H:%M" 显示月-日）
  tool_preview_length: 0  # 工具调用预览的最大字符数（0 = 不限制，显示完整路径/命令）
  turn_summary: true      # 仅 CLI：在每个交互式轮次之后打印一行轮次后统计页脚
  spinner_token_flow: true # 仅 CLI：在 spinner 计时器后追加实时累计的轮次 token 数
  runtime_footer:         # Gateway：在最终回复后追加运行时上下文页脚
    enabled: false
    fields: ["model", "context_pct", "cwd"]
  status_bar:             # CLI/TUI：选择哪些状态栏字段可见
    fields: []            # 为空 = 显示默认集合；见下文
  file_mutation_verifier: true    # 当本轮 write_file/patch 调用失败时追加一条提示性页脚
  credits_notices: true   # Nous 额度状态栏通知（用量档位、赠额已用完、已耗尽）。false = 静音；/usage 仍可用
  cli_rebuild_scrollback_on_redraw: false  # 经典 CLI：在 /redraw / Ctrl+L / 宽度变化的重绘恢复时同时清除终端回滚缓冲区（CSI 3J）。当终端/tmux 组合在最大化/还原时把过期的提示界面写入回滚缓冲区时启用。
  language: en            # 静态消息的 UI 语言（审批提示、部分 gateway 回复）。en | zh | zh-hant | ja | de | es | fr | tr | uk | af | ko | it | ga | pt | ru | hu
```

### 每轮摘要与 spinner token 流 {#per-turn-summary-and-spinner-token-flow}

`display.turn_summary`（默认 `true`）会在每个**交互式 CLI** 轮次之后打印一行暗色的统计信息，总结该轮实际做了什么：

```
⋯ 12.4s · edited 2 files +18 -3 · read 4 files · ran 3 commands
```

统计来源于 CLI 本就会收到的工具进度流，因此不会带来额外开销。细节：

- 墙钟时间是该轮的真实持续时间（超过一分钟时显示为 `2m05s`）。
- 工具调用按动词分组（`edited`、`read`、`ran`、`searched`……）并使用正确的复数形式；没有专门动词的插件/MCP 工具会合并为 `called N tools`。
- 只有当工具结果本身已报告 diff 时（目前是 `patch`），才会显示 `+X -Y` 的行数变化。Hermes 从不调用 git 来计算它们，因此 `write_file` 的编辑会被计数但不显示增减量。
- **失败的工具调用不会被计入**——一次被拒绝的写入永远不会显示为成功的编辑（互补的警告请参阅 [文件变更验证器](#file-mutation-verifier)）。
- 较长的轮次最多显示四个动词段，再加一个 `+N more` 尾部，因此该行永远不会换行。
- 没有工具调用的快速轮次什么也不会打印。

`display.spinner_token_flow`（默认 `true`）会把正在运行的轮次的累计输出 token 数追加到 CLI spinner 的实时计时器后：

```
  ⚡ Reading cli.py  (  2.3s · ↓ 1.2k tok)
```

该计数是按轮次的（会话总数以轮次开始时为基准），并随该轮中每次 API 调用报告的用量而更新。在第一次用量报告到达之前不会渲染任何内容，因此你永远不会看到误导性的 `↓ 0 tok`。

这两个键都只影响显示且仅用于 CLI：在安静模式下、`display.tool_progress` 为 `off` 时、单次查询/`-Q` 批量运行中，以及 gateway/消息界面中（它们改用 `display.runtime_footer`）都会被抑制。将任一键设为 `false` 可将其关闭。

### 文件变更验证器 {#file-mutation-verifier}

当 `display.file_mutation_verifier` 为 `true`（默认）时，只要本轮中有 `write_file` 或 `patch` 调用失败，并且之后没有被对同一路径的成功写入所取代，Hermes 就会在助手的最终回复后追加一行提示。这能捕获"一批并行 patch、一半静默失败、模型却总结为成功"这类过度宣称，而无需你在每次编辑后手动运行 `git status`。

页脚示例：

```
⚠️ File-mutation verifier: 3 file(s) were NOT modified this turn despite any wording above that may suggest otherwise. Run `git status` or `read_file` to confirm.
  • concepts/automatic-organization.md — [patch] Could not find match for old_string
  • concepts/lora.md — [patch] Could not find match for old_string
  • concepts/rag-pipeline.md — [patch] Could not find match for old_string
```

设置 `file_mutation_verifier: false`（或 `HERMES_FILE_MUTATION_VERIFIER=0`）可屏蔽该页脚。只有当轮次结束时仍存在真实的未解决失败时，验证器才会触发——一个在同一轮内重试失败的 patch 并成功的模型，不会因该文件触发它。

**相信验证器，而不是模型的总结。** 页脚意味着列出的文件在磁盘上**没有**被修改，即使助手的结束语说任务已经完成。常见原因：

- **写入被拒绝** —— 路径位于凭据拒绝列表中，或位于 `HERMES_WRITE_SAFE_ROOT` 之外（参见 [文件写入安全](./security.md#file-write-safety)）
- **Patch 不匹配** —— `old_string` 与磁盘上的文件不匹配
- **语法关卡** —— 候选内容在写入前未通过 JSON/YAML/TOML 校验

写入被阻止时的页脚示例：

```
⚠️ File-mutation verifier: 2 file(s) were NOT modified this turn despite any wording above that may suggest otherwise. Run `git status` or `read_file` to confirm.
  • ~/.hermes/cron/jobs.json — [patch] Write denied: '…' is outside HERMES_WRITE_SAFE_ROOT (/path/to/project)
  • ~/.hermes/scripts/monitor.py — [write_file] Write denied: '…' is outside HERMES_WRITE_SAFE_ROOT (/path/to/project)
```

如果对 Hermes 状态（`~/.hermes/` 下的 cron 任务、skill、脚本）的写入失败，请检查你的环境中是否设置了 `HERMES_WRITE_SAFE_ROOT`。对于 cron 变更，请使用 `cronjob` 工具或 `hermes cron edit`，而不是直接修补 `jobs.json`。

### 静态消息的 UI 语言 {#ui-language-for-static-messages}

`display.language` 设置会翻译一小部分面向用户的静态消息——CLI 审批提示、少量 gateway 斜杠命令的回复（例如重启排空通知、"approval expired"、"goal cleared"）。它**不会**翻译 agent 的回复、日志行、工具输出、错误回溯或斜杠命令描述——这些保持英文。如果你希望 agent 本身用另一种语言回复，只需在你的 prompt 或系统消息中告诉它。

支持的值：`en`（默认）、`zh`（简体中文）、`zh-hant`（繁体中文）、`ja`（日语）、`de`（德语）、`es`（西班牙语）、`fr`（法语）、`tr`（土耳其语）、`uk`（乌克兰语）、`af`（南非荷兰语）、`ko`（韩语）、`it`（意大利语）、`ga`（爱尔兰语）、`pt`（葡萄牙语）、`ru`（俄语）、`hu`（匈牙利语）。未知的值会回退到英文。

你也可以用 `HERMES_LANGUAGE` 环境变量按会话设置它，该变量会覆盖配置值。

```yaml
display:
  language: zh   # CLI 审批提示以中文显示
```

| 模式 | 你看到的内容 |
|------|-------------|
| `off` | 静默——只显示最终回复 |
| `new` | 仅在工具变化时显示工具指示 |
| `all` | 每个工具调用都附带简短预览（默认） |
| `verbose` | 完整的参数、结果和调试日志 |

在 CLI 中，用 `/verbose` 在这些模式之间循环切换。要在消息平台（Telegram、Discord、Slack 等）中使用 `/verbose`，请在上面的 `display` 部分中设置 `tool_progress_command: true`。之后该命令会循环切换模式并保存到配置中。

工具进度需要一个能够安全显示进度更新的 gateway 适配器。不支持编辑消息的平台（包括 Signal）即使 `/verbose` 保存了非 `off` 的模式，也会屏蔽工具进度气泡。

`off` 只隐藏工具调用的*界面装饰*。在 Desktop 应用和 TUI 中拥有自己界面的应用状态——任务列表（`todo_list`）、子代理进度、clarify 问题以及 MCP 同意卡片——无论此设置如何都会继续显示。

### 专注视图（`/focus`，CLI + TUI） {#focus-view-focus-cli--tui}

`display.focus_view: true` 启用**专注视图**——一种减少输出的显示模式，适用于你只想要答案、而不想看逐步过程的情况。它是对同一套 `tool_progress` 机制的一层薄封装，而不是第二条抑制路径：

- 开启它会把 `tool_progress` 固定为 `off`，并把你之前的模式保存到 `display.focus_saved_tool_progress`；
- `/focus off` 会精确恢复该模式，因此 `/verbose verbose` 的设置在一次往返后依然保留；
- 每个完成的轮次都会以一行暗色的恢复提示结束——`⋯ 7 tool lines hidden · /focus off to show`——该数量是按你*进入专注之前*的模式统计的，因此它永远不会声称隐藏了你本来就已经关闭的行；
- 状态栏中会常驻一个 `◉ focus` 标记（在 prompt_toolkit CLI 和 Ink TUI 中都是如此），因此这种精简模式永远不会是不可见的；
- 在专注开启时循环切换 `/verbose`，会把模式交还给 `/verbose` 并清除该标记。

专注视图**仅影响显示**。它从不编辑对话历史、系统 prompt、工具 schema 或任何请求负载——被隐藏的细节只是在屏幕上被抑制，从未被丢弃，prompt 缓存完全不受影响。

### 状态栏字段选择（CLI/TUI） {#status-bar-field-selection-clitui}

CLI/TUI 底部的交互式状态栏会显示模型、上下文用量、压缩次数、后台活动计数器、计时器和模式标记。`display.status_bar.fields` 选择其中哪些可见——适用于极简的状态栏（仅模型 + 时长），或用于显示需手动启用的会话 token 总数：

```yaml
display:
  status_bar:
    fields: ["model", "duration", "total_tokens"]   # 只控制可见性；保留内置顺序
```

支持的字段：`model`、`context_detail`（已用/总 token）、`context_pct`（百分比 + 进度条）、`cache_hit`（prompt 缓存命中率——在切换模型和压缩时重置）、`latency`（滚动平均 API 延迟，最近 10 次调用）、`tps`（滚动输出 token/秒，最近 10 次调用）、`compressions`、`bg_tasks`、`bg_processes`、`bg_subagents`、`goal`、`duration`、`prompt_elapsed`、`idle_since`、`focus`、`yolo`、`stash`、`battery`、`title`（右对齐的会话标记）以及 `total_tokens`（会话 Σ——仅在手动启用时显示，默认从不显示）。

说明：

- 空列表（默认）保留标准集合——除 `total_tokens` 以外的所有字段。
- 该配置控制的是**可见性，而不是顺序**；字段在其内置位置渲染。
- 无论配置如何，窄终端仍会隐藏仅宽屏模式可用的字段（`context_detail`、`cache_hit`、`latency`、`tps`、`prompt_elapsed`、`idle_since`）（`cache_hit` 在 ≥52 列的中等档位中也会显示）。
- 在记录到 API 调用之前，`latency`/`tps` 会保持隐藏（例如 Codex app-server 后端不报告延迟）。
- 这里的 `battery` 和 `title` 可见性会与它们各自的开关（`/battery`、`/title`）叠加——两者都开启时该段才会显示。
- 同一个键也会过滤 **Ink TUI** 的状态行（`hermes tui`），其中 `cache_hit`、`latency` 和 `tps` 会分别在 ≥96/104/110 列的终端上渲染为按宽度预算分配的尾部段（◎ / ◷ / ↑）。
- 仅影响显示：对 prompt 缓存或请求负载没有影响。更改在下一次会话启动时生效。

### 运行时元数据页脚（仅 gateway） {#runtime-metadata-footer-gateway-only}

当 `display.runtime_footer.enabled: true` 时，Hermes 会在每个 gateway 轮次的**最终**消息后追加一个小型的运行时上下文页脚。当前页脚可以显示模型、上下文窗口百分比和当前工作目录。默认关闭；如果你的团队希望每条回复都包含这些来源信息，可按 gateway 选择启用。

```yaml
display:
  runtime_footer:
    enabled: true
    fields: ["model", "context_pct", "cwd"]   # 按显示顺序；删除任意字段即可隐藏
```

支持的字段：

| 字段 | 渲染内容 | 示例 |
| --- | --- | --- |
| `model` | 去掉厂商前缀的裸模型 id | `gpt-5.4` |
| `context_pct` | 最近一次调用的上下文占用百分比 | `5%` |
| `latency` | 该轮的墙钟时长 | `22s`、`1m05s` |
| `cwd` | 相对于主目录的工作目录 | `~` |

默认字段集为 `["model", "context_pct", "cwd"]`。`latency` 需手动启用——把它加到 `fields` 中即可使用。数据不可用的字段会被静默跳过，而不是渲染一个空位。

`/footer` 斜杠命令可在任意会话中于运行时切换此功能。

追加到 Telegram/Discord/Slack 回复后的页脚示例：

```
— claude-opus-4.7 · 12 tool calls · 2m 14s · $0.042
```

只有一轮的**最终**消息会带有页脚；中途的更新保持简洁。

### 按平台的进度覆盖 {#per-platform-progress-overrides}

不同平台对详细程度有不同的需求。使用 `display.platforms` 设置按平台的模式：

```yaml
display:
  tool_progress: all          # 全局默认值
  platforms:
    signal:
      tool_progress: 'off'    # Signal 目前无法显示工具进度气泡
    telegram:
      tool_progress: verbose  # 在 Telegram 上显示详细进度
    slack:
      tool_progress: 'off'    # 在共享的 Slack 工作区中保持安静
```

在 CLI 中，请使用规范路径——`hermes config set display.platforms.telegram.streaming false`。简写形式 `hermes config set platforms.telegram.streaming false` 也被接受：因为按平台的*显示*设置（`streaming`、`show_reasoning`、`tool_progress`……）只会从 `display.platforms` 读取，所以 `config set`/`get`/`unset` 会把该简写重定向到规范键并打印一条说明。顶层 `platforms.<name>` 块下的连接类键（`token`、`enabled`、`reply_to_mode`、`extra`）不会被重定向。

没有覆盖的平台会回退到全局的 `tool_progress` 值。有效的平台键：`telegram`、`discord`、`slack`、`signal`、`whatsapp`、`matrix`、`mattermost`、`email`、`sms`、`homeassistant`、`dingtalk`、`feishu`、`wecom`、`weixin`、`bluebubbles`、`qqbot`。旧版的 `display.tool_progress_overrides` 键为了向后兼容仍可加载，但已弃用，并会在首次加载时迁移到 `display.platforms`。

Signal 被列为有效的平台键，是因为该设置可以按平台保存，但当前的 Signal 适配器无法编辑已发送的消息，也不会渲染工具进度气泡。请把 Signal 的 `tool_progress` 保持为 `off`；如果你需要实时观察每个工具调用，请使用 CLI 或支持编辑消息的消息平台。

`interim_assistant_messages` 仅用于 gateway。启用后，Hermes 会把轮次中途已完成的助手更新作为独立的聊天消息发送。这与 `tool_progress` 相互独立，也不需要 gateway 流式输出。

`show_commentary`（默认 `true`）控制 Codex Responses 模型的 commentary 通道——这些模型在其私有推理之外产生的、经过润色的进度叙述。启用后，每条已完成的 commentary 消息都会作为可见的中途更新投递（在 gateway 上这还需要 `interim_assistant_messages`）。如果这些额外叙述让你厌烦，请把它设为 `false`：此时 commentary 会回退到推理通道，只有在启用 `show_reasoning` 时才会显示。

## 隐私 {#privacy}

```yaml
privacy:
  redact_pii: false  # 从 LLM 上下文中去除 PII（仅 gateway）
```

当 `redact_pii` 为 `true` 时，gateway 会在受支持的平台上，于把系统 prompt 发送给 LLM 之前对其中的个人身份信息进行脱敏：

| 字段 | 处理方式 |
|-------|-----------|
| 电话号码（WhatsApp/Signal 上的用户 ID） | 哈希为 `user_<12-char-sha256>` |
| 用户 ID | 哈希为 `user_<12-char-sha256>` |
| 聊天 ID | 数字部分被哈希，保留平台前缀（`telegram:<hash>`） |
| 主频道 ID | 数字部分被哈希 |
| 用户姓名 / 用户名 | **不受影响**（由用户自行选择，公开可见） |

**平台支持：** 脱敏适用于 WhatsApp、Signal 和 Telegram。Discord 和 Slack 被排除在外，因为它们的提及系统（`<@user_id>`）需要在 LLM 上下文中使用真实 ID。

哈希是确定性的——同一个用户总是映射到同一个哈希，因此模型在群聊中仍然可以区分不同的用户。路由和投递在内部使用原始值。

### OpenAI Codex 请求身份 {#openai-codex-request-identity}

OpenAI 要求第三方 Codex 框架表明自己的身份。
经过 ChatGPT 认证、发往官方 Codex 端点的请求会自动发送 `originator: hermes-agent` 和 `User-Agent: HermesAgent/<version>`。
现有的 ChatGPT 账号头会被保留。不会发送任何额外的 prompt 内容或遥测请求。
直连 OpenAI API 的请求和自定义代理端点保持不变。

## 语音转文字（STT） {#speech-to-text-stt}

```yaml
stt:
  enabled: true                # 自动转录入站语音消息（默认：true）
  echo_transcripts: true       # 把原始转录以 🎙️ "..." 的形式发回聊天（默认：true）
  provider: "local"            # "local" | "groq" | "openai" | "mistral" | "xai" | "elevenlabs" | "deepinfra" | ...
  language: "en"               # 适用于每个 provider 的全局语言提示（按 provider 的 language 优先）；设为 "" 表示自动检测
  cloud_trim_silence: true     # 上传到云端 provider 之前用 ffmpeg 裁掉长停顿（默认：true）
  cloud_trim_threshold_db: -40 # 比该值更安静的音频被视为静音
  cloud_trim_keep_ms: 300      # 每段停顿在裁剪后保留的长度（保持自然节奏）
  # prompt: "Hermes, Teknium, Nous Research, kanban"   # 静态词汇提示（见下文）
  local:
    model: "base"              # tiny、base、small、medium、large-v3
    language: ""               # 按 provider 覆盖 stt.language
    initial_prompt: ""         # 可选的 whisper prompt，用于引导词汇/书写系统（例如简体中文）
    vad: true                  # Silero VAD 过滤器（默认开启）——静音永远不会到达 whisper；false = 原始行为（音乐/环境音）
    vad_min_silence_ms: 500    # vad 开启时分割语音片段的最短静音（毫秒）
    no_speech_prob_threshold: 0.6  # 只有当 no_speech_prob > 该值……
    logprob_threshold: -1.0        # ……并且 avg_logprob < 该值时才丢弃片段（两者都满足——安静的真实语音得以保留）
    unload_after_idle_seconds: 0   # 0 = 从不卸载（默认）；例如 300 = 空闲 5 分钟后释放模型
  groq:
    language: ""               # 按 provider 覆盖 stt.language
  openai:
    model: "whisper-1"         # whisper-1 | gpt-4o-mini-transcribe | gpt-4o-transcribe | gpt-transcribe
    language: ""               # 按 provider 覆盖 stt.language
  # model: "whisper-1"         # 旧版回退键仍被遵循
```

语言解析对**每个** STT provider（local、groq、openai、mistral、xai、elevenlabs、deepinfra、命令类 provider 和插件）都相同：`stt.<provider>.language` → `stt.language` → `HERMES_LOCAL_STT_LANGUAGE` 环境变量 → provider 自动检测。**默认值是 `stt.language: "en"`**——Whisper 的自动检测经常误判较短或带口音的片段，表现为语音消息被转录成了错误的语言。非英语使用者应当把 `stt.language` 设置为自己的语言代码一次（例如 `"es"`、`"zh"`、`"uk"`）；设为 `""` 可为多语言场景恢复自动检测。

当 gateway 需要为 agent 转录语音消息、但不得把原始转录发回聊天时（例如面向客户的 WhatsApp 机器人），请设置 `stt.echo_transcripts: false`。

Provider 行为：

- `local` 使用在你本机上运行的 `faster-whisper`。请用 `pip install faster-whisper` 单独安装。默认开启对静音幻觉的加固：Silero VAD 过滤器会阻止静音/噪声到达 Whisper，跨窗口条件化被禁用，并且被模型自身标记为可能不是语音*并且*低置信度的片段会被丢弃。设置 `stt.local.vad: false` 可用原始行为转录非语音音频（音乐、环境音）。为了低延迟转录，模型会在多条语音消息之间一直保持加载在内存中；设置 `stt.local.unload_after_idle_seconds`（例如 `300` 表示 5 分钟）可在空闲时自动释放模型。这会在 CUDA 主机上释放 GPU 显存（当本地 LLM 共享 GPU 时这是主要收益）；在 CPU 上，内存会变为可被进程复用，但在进程需要把这部分空间用于其他用途之前，操作系统可见的占用可能不会缩小。下一条语音消息会透明地重新加载模型。
- `groq` 使用 Groq 的 Whisper 兼容端点，读取 `GROQ_API_KEY`。传入 `stt.groq.language`（或全局的 `HERMES_LOCAL_STT_LANGUAGE` 环境变量）可跳过自动检测并降低延迟。
- `openai` 使用 OpenAI 语音 API，读取 `VOICE_TOOLS_OPENAI_KEY`。

安装了 `ffmpeg` 时，云端 provider（groq、openai、mistral、xai、elevenlabs、deepinfra）默认会进行**上传前静音裁剪**：语音消息中的长停顿会在文件上传之前于客户端被压缩，每段停顿保留 `cloud_trim_keep_ms`，从而保持自然节奏。更短的音频意味着更快的上传、更低的按音频分钟计费，以及更少来自远程模型的静音幻觉。短于 12 秒的片段会完全跳过裁剪（在那里节省微不足道，而且好几家 provider 本来就按每次请求的最低时长计费）。裁剪是尽力而为的——如果缺少 ffmpeg、裁剪失败、片段大部分是静音，或裁剪节省不到约 10%，就会原样上传原始文件。设置 `stt.cloud_trim_silence: false` 可始终上传原始文件（例如通过云端 provider 转录音乐或环境音时）。命令类和插件 provider 永远不会收到裁剪过的音频。

显式选择的 `stt.provider` 会被严格遵守——如果它不可用，转录会报错并提示运行 `hermes tools`，而不会切换 provider。只有当从未选择过任何 provider 时，Hermes 才会按以下顺序自动检测：`local` → `groq` → `openai`。

Groq 和 OpenAI 的模型覆盖由环境变量驱动：

```bash
STT_GROQ_MODEL=whisper-large-v3-turbo
STT_OPENAI_MODEL=whisper-1
GROQ_BASE_URL=https://api.groq.com/openai/v1
STT_OPENAI_BASE_URL=https://api.openai.com/v1
```

### 转录 prompt（词汇提示） {#transcription-prompt-vocabulary-hints}

`stt.prompt` 是一个可选的静态提示，会传递给支持 prompt 的 STT 后端。可用它来提示专有名词、产品名称和 Whisper 系列模型容易听错的术语：

```yaml
stt:
  provider: "local"
  prompt: "Hermes, Teknium, Nous Research, kanban, Ollama"
```

**组合方式。** 配置值是基础。注册了 [`pre_transcription`](/user-guide/features/hooks#pre_transcription) hook 的插件会在其之上进行修改，按字段后写者胜出。多个插件的提示会以确定性的方式组合：插件发现会按插件 id 排序加载插件，每个插件的回调按其自身的注册顺序运行，因此同一组插件总是产生相同的最终 prompt。hook 为 `prompt` 返回空字符串会清除该请求的配置 prompt。hook 还可以覆盖 `language` 和 `model`；`file_path` 是只读的，任何修改它的尝试都会被记录并丢弃。在没有注册 hook 且未设置 `stt.prompt` 时，发出的请求与以往版本完全相同。

**Provider 支持。**

| Provider | Prompt 参数 | 行为 |
|----------|-----------------|----------|
| `local`（faster-whisper） | `initial_prompt` | 原样转发给本地模型 |
| `openai` | `prompt` | 原样包含在转录请求中 |
| `groq` | `prompt` | 原样包含在转录请求中 |
| `mistral` | `prompt` | 原样包含在转录请求中 |
| `deepinfra` | `prompt` | OpenAI 兼容路径，原样转发 |
| `xai` | 不支持 | 以 DEBUG 级别记录，请求在没有 prompt 的情况下继续 |
| `elevenlabs` | 不支持 | 以 DEBUG 级别记录，请求在没有 prompt 的情况下继续 |
| `local_command` | 不支持 | 以 DEBUG 级别记录，请求在没有 prompt 的情况下继续 |
| 带 `type: command` 的 `stt.providers.<name>` | 不支持 | 以 DEBUG 级别记录，请求在没有 prompt 的情况下继续 |
| 插件注册的 provider | `transcribe(**extra)` 关键字参数中的 `prompt` | 只有在设置了 prompt 时才会发送，因此早于该键的 provider 看到的调用不变 |

**长度。** Whisper 系列模型只会以最后约 224 个 prompt token 作为条件。对于 whisper 系列后端（`local`、`openai`、`groq`、`deepinfra`），Hermes 会在客户端强制执行这一上限：过长的最终 prompt 会被截断为其尾部并记录一条警告——请求永远不会因为 prompt 长度而报错。其他后端（`mistral`、插件 provider）会原样收到 prompt，并自行负责校验。无论哪种情况，都请让提示简短而具体。

:::warning Prompt 会与你的音频一起上传
最终的 prompt 会与音频文件一起发送给所配置的 STT provider。请不要在 `stt.prompt` 以及 `pre_transcription` hook 返回的任何内容中包含机密和源自会话的上下文，尤其是当 provider 是托管 API 而不是本地 `faster-whisper` 时。
:::

## 语音模式（CLI） {#voice-mode-cli}

```yaml
voice:
  record_key: "ctrl+b"         # CLI 中的按键说话键
  max_recording_seconds: 120    # 长录音的硬性停止
  auto_tts: false               # /voice on 时自动启用语音回复
  beep_enabled: true            # 在 CLI 语音模式中播放录音开始/停止提示音
  beep_volume: 0.3              # 提示音幅度（0.0-1.0）；在较安静的系统 / 耳机上调高
  silence_threshold: 200        # 语音检测的 RMS 阈值
  silence_duration: 3.0         # 自动停止前的静音秒数
```

在 CLI 中使用 `/voice on` 启用麦克风模式，用 `record_key` 开始/停止录音，用 `/voice tts` 切换语音回复。端到端设置和各平台的具体行为请参阅 [语音模式](/user-guide/features/voice-mode)。

## 流式输出 {#streaming}

在 token 到达时把它们流式输出到终端或消息平台，而不是等待完整的回复。

### CLI 流式输出 {#cli-streaming}

```yaml
display:
  streaming: true         # 实时把 token 流式输出到终端
  show_reasoning: true    # 同时流式输出推理/思考 token（可选）
```

启用后，回复会在一个流式输出框中逐 token 出现。工具调用仍然会被静默捕获。如果 provider 不支持流式输出，会自动回退到普通显示。

### Gateway 流式输出（Telegram、Discord、Slack） {#gateway-streaming-telegram-discord-slack}

```yaml
streaming:
  enabled: true           # 启用渐进式消息编辑（默认：false）
  transport: auto         # "auto"（默认）| "edit"（渐进式消息编辑）| "off"
  edit_interval: 0.8      # 两次消息编辑之间的秒数（默认：0.8）
  buffer_threshold: 24    # 强制刷新一次编辑前的字符数（默认：24）
  cursor: " ▉"            # 流式输出期间显示的光标
  fresh_final_after_seconds: 0    # 当预览已存在这么久时，选择启用全新的最终消息（Telegram）
```

启用后，机器人会在第一个 token 到达时发送一条消息，然后随着更多 token 到达逐步编辑它。不支持消息编辑的平台（Signal、Email、Home Assistant）会在第一次尝试时被自动检测出来——该会话的流式输出会被平稳地禁用，而不会造成消息刷屏。

如果想要独立的、自然的轮次中途助手更新而不进行渐进式 token 编辑，请设置 `display.interim_assistant_messages: true`。

**溢出处理：** 如果流式输出的文本超过平台的消息长度上限（约 4096 个字符），当前消息会被收尾，并自动开始一条新消息。

**全新的最终消息（Telegram）：** Telegram 的 `editMessageText` 会保留原始消息的时间戳，因此一条长时间流式输出的回复即使在完成后也会保留第一个 token 的时间戳。设置 `fresh_final_after_seconds > 0` 可选择把较旧的预览作为全新的最终消息投递，并尽力删除预览。默认值为 `0`，它总是原地收尾流式回复，避免在会同时显示两种操作的客户端上出现短暂的重复消息/删除过程。

:::note 按平台的流式输出默认值
总开关 `streaming.enabled` 默认为 `false`——在你打开它之前不会有任何流式输出。启用之后，流式输出**按平台**决定：Telegram 自带 `display.platforms.telegram.streaming: true`（流式输出），Discord 自带 `display.platforms.discord.streaming: false`（不流式输出）。因此启用流式输出后，Telegram 开箱即会流式输出，而 Discord 会保持整条消息回复，直到你更改其开关。你可以在 dashboard 的 **Channels** 开关中或直接在 `~/.hermes/config.yaml` 中调整这些按平台的开关。
:::

## 群聊会话隔离 {#group-chat-session-isolation}

限制在 CLI、TUI/dashboard 和消息 gateway 之间可以同时活跃打开的聊天会话数：

```yaml
max_concurrent_sessions: null  # null/0 = 不限制；正整数 = 活跃会话上限
```

占用名额的时刻是会话运行其**第一个轮次**时，而不是打开聊天窗口时。在你发送消息之前，打开、恢复或重新连接到一个聊天都不会占用名额，因此闲置的桌面标签页（以及不稳定的 websocket 触发的后台恢复）不会挤占共享此上限的消息 gateway。

达到上限时，Hermes 会返回一条直接的限制消息，指出哪些界面占用了名额。已有的活跃会话保持其正常行为。运行 `hermes status` 可查看当前的名额使用情况以及每个占用者。

规范的键是顶层的 `max_concurrent_sessions`。Hermes 也接受 `gateway.max_concurrent_sessions` 作为回退，但两者都设置时以顶层键为准。

该上限通过一个本地运行时租约文件来执行，并且是尽力而为的：如果注册表无法读取或加锁，Hermes 会失败开放，以免用户被困住。它面向单个主机/profile 运行时，而不是挂载在多台机器之间的共享 `$HERMES_HOME`。

控制共享聊天是每个房间保持一个对话，还是每个参与者保持一个对话：

```yaml
group_sessions_per_user: true  # true = 在群组/频道中按用户隔离，false = 每个聊天一个共享会话
```

- `true` 是默认且推荐的设置。在 Discord 频道、Telegram 群组、Slack 频道以及类似的共享场景中，当平台提供用户 ID 时，每个发送者都会有自己的会话。
- `false` 会恢复旧的共享房间行为。如果你明确希望 Hermes 把一个频道当作一场协作对话，这可能有用，但这也意味着用户共享上下文、token 开销和中断状态。
- 私信不受影响。Hermes 仍会像往常一样按聊天/私信 ID 为私信建立键。
- 无论哪种设置，话题都与其父频道保持隔离；使用 `true` 时，每个参与者在话题内也会拥有自己的会话。

行为细节和示例请参阅 [会话](/user-guide/sessions) 和 [Discord 指南](/user-guide/messaging/discord)。

## 未授权私信的处理行为 {#unauthorized-dm-behavior}

控制当未知用户发送私信时 Hermes 的处理方式：

```yaml
unauthorized_dm_behavior: pair

whatsapp:
  unauthorized_dm_behavior: ignore
```

- `pair` 是聊天类私信平台的默认值。Hermes 会拒绝访问，但会在私信中回复一个一次性配对码。
- `ignore` 会静默丢弃未授权的私信。
- Email 默认使用 `ignore`，除非设置了 `platforms.email.unauthorized_dm_behavior: pair`，因为收件箱中可能包含无关的未读邮件。
- 平台部分会覆盖全局默认值，因此你可以大范围保持配对功能开启，同时让某个平台更安静。

## 快捷命令 {#quick-commands}

定义自定义命令，这些命令要么在不调用 LLM 的情况下运行 shell 命令，要么把一个斜杠命令映射为另一个。exec 类快捷命令不消耗 token，适合在消息平台（Telegram、Discord 等）中进行快速的服务器检查或运行工具脚本。

```yaml
quick_commands:
  status:
    type: exec
    command: systemctl status hermes-agent
  disk:
    type: exec
    command: df -h /
  update:
    type: exec
    command: cd ~/.hermes/hermes-agent && git pull && uv pip install -e .
  gpu:
    type: exec
    command: nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader
  restart:
    type: alias
    target: /gateway restart
```

用法：在 CLI 或任意消息平台中输入 `/status`、`/disk`、`/update`、`/gpu` 或 `/restart`。`exec` 命令在主机本地运行并直接返回输出——不调用 LLM，不消耗 token。`alias` 命令会被重写为所配置的目标斜杠命令。

- **30 秒超时** —— 长时间运行的命令会被终止并返回错误信息
- **优先级** —— 快捷命令会在 skill 命令之前被检查，因此你可以覆盖 skill 名称
- **自动补全** —— 快捷命令在分派时解析，不会显示在内置的斜杠命令自动补全表中
- **类型** —— 支持的类型为 `exec` 和 `alias`；其他类型会显示错误
- **随处可用** —— CLI、Telegram、Discord、Slack、WhatsApp、Signal、Email、Home Assistant

仅包含字符串的 prompt 快捷方式不是有效的快捷命令。对于可复用的 prompt 工作流，请创建一个 skill，或映射到一个已有的斜杠命令。

## 人类延迟 {#human-delay}

在消息平台中模拟类似人类的回复节奏：

```yaml
human_delay:
  mode: "off"                  # off | natural | custom
  min_ms: 800                  # 最小延迟（custom 模式）
  max_ms: 2500                 # 最大延迟（custom 模式）
```

## 代码执行 {#code-execution}

配置 `execute_code` 工具：

```yaml
code_execution:
  mode: project                # project（默认）| strict
  timeout: 300                 # 最长执行时间（秒）
  max_tool_calls: 50           # 代码执行中的最大工具调用次数
```

**`mode`** 控制脚本的工作目录和 Python 解释器：

- **`project`**（默认）—— 脚本在会话的工作目录中运行，使用当前激活的 virtualenv/conda 环境的 python。项目依赖（`pandas`、`torch`、项目自身的包）和相对路径（`.env`、`./data.csv`）都能自然解析，与 `terminal()` 看到的一致。
- **`strict`** —— 脚本在一个临时暂存目录中运行，使用 `sys.executable`（Hermes 自己的 python）。可复现性最高，但项目依赖和相对路径无法解析。

环境变量清理（去除 `*_API_KEY`、`*_TOKEN`、`*_SECRET`、`*_PASSWORD`、`*_CREDENTIAL`、`*_PASSWD`、`*_AUTH`）和工具白名单在两种模式下完全相同——切换模式不会改变安全态势。

## Web 搜索后端 {#web-search-backends}

`web_search` 和 `web_extract` 工具支持五种后端 provider。在 `config.yaml` 中或通过 `hermes tools` 配置后端：

```yaml
web:
  backend: firecrawl    # firecrawl | searxng | parallel | tavily | perplexity | keenable | exa

  # 或者使用按能力区分的键来混用 provider（例如免费搜索 + 付费提取）：
  search_backend: "searxng"
  extract_backend: "firecrawl"

  # 无密钥免费档位回退（默认：true）。在没有配置后端
  # 且没有任何 API 密钥时，web 工具会在 Exa/Parallel/
  # Firecrawl/Keenable 的免费档位之间轮换。设为 false 可禁用。
  keyless_fallback: true

  # 一次性的无密钥救援（默认：true）。当所选/带密钥的后端
  # 某次调用失败时，仅这一次调用会在无密钥环上重试；下一次
  # 调用会再次尝试所选后端（永远不会固定下来）。
  keyless_rescue: true

  # 把 Exa/Parallel 固定到某个档位（由 hermes tools 的 Free/Paid 行设置）。
  # free = 始终使用匿名端点；paid = 始终使用带密钥的 SDK 路径；
  # 未设置 = auto（有密钥 -> paid，否则 free）。
  provider_tier:
    parallel: free
    exa: paid
```

| 后端 | 环境变量 | 搜索 | 提取 |
|---------|---------|--------|---------|
| **Firecrawl**（默认） | `FIRECRAWL_API_KEY` | ✔ | ✔ |
| **SearXNG** | `SEARXNG_URL` | ✔ | — |
| **Parallel** | `PARALLEL_API_KEY`（可选——无密钥免费档位） | ✔ | ✔ |
| **Tavily** | `TAVILY_API_KEY`（可选——选中时无需密钥） | ✔ | ✔ |
| **Perplexity** | `PERPLEXITY_API_KEY` | ✔ | ✔（与查询相关的片段） |
| **Exa** | `EXA_API_KEY`（可选——无密钥免费档位） | ✔ | ✔ |

**后端选择：** 运行时始终使用已保存的 `web.backend` 选择（通过 `hermes tools` 设置；`nous` 会经由托管的 Tool Gateway 路由）。只有在从未选择过任何 web 后端时，才会根据可用的 API 密钥自动检测：如果只设置了 `SEARXNG_URL`，则使用 SearXNG；如果只设置了 `EXA_API_KEY`，则使用 Exa；如果只设置了 `TAVILY_API_KEY`，则使用 Tavily；如果只设置了 `PERPLEXITY_API_KEY`，则使用 Perplexity；如果只设置了 `PARALLEL_API_KEY`，则使用 Parallel；如果只设置了 `KEENABLE_API_KEY`，则使用 Keenable。在**既没有选择也完全没有凭据**时，请求会在无密钥免费档位环（Exa / Parallel / Firecrawl / Keenable）之间轮询，并在限流时自动故障切换到下一个——详情请参阅 [Web 搜索指南](/user-guide/features/web-search)。一旦存在选择，向 `.env` 添加密钥不会改变路由。在 `hermes tools` 中选择 Tavily、Firecrawl 或 Keenable 同样无需密钥即可工作。

**SearXNG** 是一个免费、自托管、尊重隐私的元搜索引擎，可查询 70 多个搜索引擎。无需 API 密钥——只需把 `SEARXNG_URL` 设置为你的实例地址（例如 `http://localhost:8080`）。SearXNG 只支持搜索；`web_extract` 需要单独的提取 provider（设置 `web.extract_backend`）。Docker 部署说明请参阅 [Web 搜索设置指南](/user-guide/features/web-search)。

**自托管 Firecrawl：** 设置 `FIRECRAWL_API_URL` 指向你自己的实例。设置了自定义 URL 时，API 密钥变为可选（在服务器上设置 `USE_DB_AUTHENTICATION=*** 可禁用认证）。

**Parallel 搜索模式：** 设置 `PARALLEL_SEARCH_MODE` 控制搜索行为——`fast`、`one-shot` 或 `agentic`（默认：`agentic`）。

**Exa：** 在 `~/.hermes/.env` 中设置 `EXA_API_KEY`。支持 `category` 过滤（`company`、`research paper`、`news`、`people`、`personal site`、`pdf`）以及域名/日期过滤。

## 浏览器 {#browser}

配置浏览器自动化行为：

```yaml
browser:
  inactivity_timeout: 120        # 自动关闭空闲会话前的秒数
  command_timeout: 30             # 浏览器命令（截图、导航等）的超时秒数
  record_sessions: false         # 自动将浏览器会话录制为 WebM 视频，保存到 ~/.hermes/browser_recordings/
  # 可选的 CDP 覆盖——设置后，Hermes 会直接附着到你自己的
  # Chromium 系浏览器（通过 /browser connect），而不是启动一个无头浏览器。
  cdp_url: ""
  # 对话框监管器——控制在附着了 CDP 后端（Browserbase、通过 /browser connect
  # 连接的本地 Chromium 系浏览器）时如何处理原生 JS 对话框（alert / confirm / prompt）。
  # 在 Camofox 和默认的本地 agent-browser 模式下会被忽略。
  dialog_policy: must_respond    # must_respond | auto_dismiss | auto_accept
  dialog_timeout_s: 300          # must_respond 模式下的安全自动关闭时间（秒）
  camofox:
    managed_persistence: false   # 为 true 时，Camofox 会话会在重启之间保留 cookie/登录状态
    user_id: ""                  # 可选的外部管理的 Camofox userId
    session_key: ""              # Hermes 创建标签页时发送的可选会话键
    adopt_existing_tab: false    # 在创建新标签页之前，复用该身份已有的标签页
```

**对话框策略：**

- `must_respond`（默认）—— 捕获对话框，在 `browser_snapshot.pending_dialogs` 中呈现它，并等待 agent 调用 `browser_dialog(action=...)`。如果 `dialog_timeout_s` 秒后仍无响应，对话框会被自动关闭，以防页面的 JS 线程永远卡住。
- `auto_dismiss` —— 捕获并立即关闭。事后 agent 仍能在 `browser_snapshot.recent_dialogs` 中看到该对话框记录，其中 `closed_by="auto_policy"`。
- `auto_accept` —— 捕获并立即接受。适用于带有激进 `beforeunload` 提示的页面。

完整的对话框工作流请参阅 [浏览器功能页面](./features/browser.md#browser_dialog)。

浏览器 toolset 支持多种 provider。关于 Browserbase、Browser Use 以及本地 Chromium 系 CDP 设置的详细信息，请参阅 [浏览器功能页面](/user-guide/features/browser)。

## 时区 {#timezone}

用 IANA 时区字符串覆盖服务器本地时区。它会影响日志中的时间戳、cron 调度以及系统 prompt 中注入的时间。

```yaml
timezone: "America/New_York"   # IANA 时区（默认："" = 服务器本地时间）
```

支持的值：任意 IANA 时区标识符（例如 `America/New_York`、`Europe/London`、`Asia/Kolkata`、`UTC`）。留空或省略表示使用服务器本地时间。

## Discord {#discord}

为消息 gateway 配置 Discord 专属行为：

```yaml
discord:
  require_mention: true          # 在服务器频道中需要 @提及才会回复
  free_response_channels: ""     # 逗号分隔的频道 ID，机器人在这些频道中无需 @提及即可回复
  auto_thread: true              # 在频道中被 @提及时自动创建话题
```

- `require_mention` —— 为 `true`（默认）时，机器人只有在服务器频道中被 `@BotName` 提及时才会回复。私信始终无需提及。
- `free_response_channels` —— 逗号分隔的频道 ID 列表，机器人会在这些频道中回复每一条消息，无需提及。
- `auto_thread` —— 为 `true`（默认）时，频道中的提及会自动为对话创建一个话题，保持频道整洁（类似于 Slack 的话题）。

## 安全 {#security}

执行前的安全扫描与机密脱敏：

```yaml
security:
  redact_secrets: true           # 在工具输出和日志中对 API 密钥模式进行脱敏（默认开启）
  tirith_enabled: true           # 为终端命令启用 Tirith 安全扫描
  tirith_path: "tirith"          # tirith 二进制文件路径（默认：$PATH 中的 "tirith"）
  tirith_timeout: 5              # 等待 tirith 扫描的超时秒数
  tirith_fail_open: true         # tirith 不可用时允许执行命令
  website_blocklist:             # 参见下文的网站屏蔽列表部分
    enabled: false
    domains: []
    shared_files: []
```

- `redact_secrets` —— 为 `true` 时，会在工具输出进入对话上下文和日志之前，自动检测并脱敏看起来像 API 密钥、token 和密码的内容。**默认开启**。只有在调试或开发脱敏器时确实需要原始的类凭据字符串，才显式设为 `false`。
- `tirith_enabled` —— 为 `true` 时，终端命令会在执行前由 [Tirith](https://github.com/sheeki03/tirith) 扫描，以检测潜在的危险操作。
- `tirith_path` —— tirith 二进制文件的路径。如果 tirith 安装在非标准位置，请设置此项。
- `tirith_timeout` —— 等待 tirith 扫描的最长秒数。扫描超时时命令会继续执行。
- `tirith_fail_open` —— 为 `true`（默认）时，如果 tirith 不可用或失败，允许执行命令。设为 `false` 则在 tirith 无法验证命令时阻止它们。

## 网站屏蔽列表 {#website-blocklist}

阻止 agent 的 web 和浏览器工具访问特定域名：

```yaml
security:
  website_blocklist:
    enabled: false               # 启用 URL 屏蔽（默认：false）
    domains:                     # 被屏蔽的域名模式列表
      - "*.internal.company.com"
      - "admin.example.com"
      - "*.local"
    shared_files:                # 从外部文件加载额外规则
      - "/etc/hermes/blocked-sites.txt"
```

启用后，任何匹配被屏蔽域名模式的 URL 都会在 web 或浏览器工具执行之前被拒绝。这适用于 `web_search`、`web_extract`、`browser_navigate` 以及任何访问 URL 的工具。

域名规则支持：
- 精确域名：`admin.example.com`
- 通配子域名：`*.internal.company.com`（屏蔽所有子域名）
- 顶级域通配：`*.local`

共享文件中每行一条域名规则（空行和 `#` 注释会被忽略）。缺失或无法读取的文件会记录警告，但不会禁用其他 web 工具。

该策略会缓存 30 秒，因此配置更改无需重启即可很快生效。

## 智能审批 {#smart-approvals}

控制 Hermes 如何处理潜在的危险命令：

```yaml
approvals:
  mode: smart   # smart | manual | off
```

| 模式 | 行为 |
|------|----------|
| `smart`（默认） | 使用辅助 LLM 评估被标记的命令是否真的危险。低风险命令仅针对该命令自动批准。真正有风险的命令会被拒绝；不确定的判断会升级给用户。 |
| `manual` | 在执行任何被标记的命令之前提示用户。在 CLI 中显示交互式审批对话框。在消息平台中排队一个待处理的审批请求。 |
| `off` | 跳过所有审批检查。等同于 `HERMES_YOLO_MODE=true`。**请谨慎使用。** |

智能模式对减轻审批疲劳特别有用——它让 agent 能在安全操作上更自主地工作，同时仍能拦截真正具有破坏性的命令。

:::warning
设置 `approvals.mode: off` 会禁用终端命令的所有安全检查。只在受信任的、沙箱化的环境中使用。
:::

### 拒绝熔断器 {#denial-circuit-breaker}

`approvals.denial_breaker_threshold`（默认 `3`）防止 agent 不断重试智能审批审查者一直拒绝的命令变体——每次重试都会多消耗一次守护 LLM 调用。在一个会话中连续被拒绝这么多次之后，拒绝消息会升级为一条硬性停止指令，告诉 agent 停下来、报告被阻止的操作，并请你手动运行或 `/approve`。任何一次批准都会重置计数；设为 `0` 可禁用：

```yaml
approvals:
  denial_breaker_threshold: 3   # 0 表示禁用熔断器
```

### 拒绝规则 {#deny-rules}

`approvals.deny` 是一个 glob 模式列表，会无条件阻止匹配的终端命令——即使在 `--yolo`、`/yolo` 或 `mode: off` 下也是如此。它是内置硬性阻止列表的用户可编辑对应项：

```yaml
approvals:
  deny:
    - "git push --force*"
    - "*curl*|*sh*"
```

模式是不区分大小写的 fnmatch glob，并且在 YAML 中必须加引号（裸的前导 `*` 会导致解析错误）。详情请参阅 [安全 —— 用户自定义拒绝规则](/user-guide/security#user-defined-deny-rules-approvalsdeny)。

### 自定义智能审批策略 {#custom-smart-approval-policy}

`approvals.smart_policy` 让你可以把自己的规则追加到智能审批审查者的指令中。设置后，该文本会被添加到守护 LLM 的系统 prompt 中（受信任的通道——永远不会与不受信任的命令文本放在一起），因此你无需修改代码就能针对你的环境收紧或放宽它的判断：

```yaml
approvals:
  smart_policy: |
    Always ESCALATE commands that modify anything under /etc.
    APPROVE docker compose restarts in ~/deploys — they are routine here.
```


## Checkpoints {#checkpoints}

在破坏性文件操作之前自动创建文件系统快照。详情请参阅 [Checkpoints 与回滚](/user-guide/checkpoints-and-rollback)。

```yaml
checkpoints:
  enabled: false                 # 启用自动 checkpoint（也可用：hermes chat --checkpoints）。默认：false（需手动启用）。
  max_snapshots: 20              # 每个目录保留的最大 checkpoint 数（默认：20）
```


## 委托 {#delegation}

为 delegate 工具配置子代理行为：

```yaml
delegation:
  # model: "google/gemini-3-flash-preview"  # 覆盖模型（为空 = 继承父级）
  # provider: "openrouter"                  # 覆盖 provider（为空 = 继承父级）
  # base_url: "http://localhost:1234/v1"    # 直连的 OpenAI 兼容端点（优先于 provider）
  # api_key: "local-key"                    # base_url 使用的 API 密钥（回退到 OPENAI_API_KEY）
  # api_mode: ""                            # base_url 的协议："chat_completions"、"codex_responses" 或 "anthropic_messages"。为空 = 根据 URL 自动检测（例如 /anthropic 后缀 → anthropic_messages）。对启发式规则无法检测的非标准端点请显式设置。
  compression_threshold_tokens: 0          # 可选的子代理压缩触发绝对上限（>= 16000）；0 = 关闭，子代理使用比例阈值
  # request_overrides:                      # 在每次子代理 API 调用上发送的按子代理请求设置（所有解析分支）。
  #   extra_body:                           # 合并到请求的 extra_body 中——例如 OpenRouter 路由提示：
  #     provider:
  #       sort: throughput
  max_concurrent_children: 3                # 每批并行的子代理数（下限 1，无上限）。也可通过 DELEGATION_MAX_CONCURRENT_CHILDREN 环境变量设置。
  worktree_isolation: false                 # 为每个子代理提供从 HEAD 分出的独立 git worktree（仅限本地后端 + git 仓库；灵感来自 Muse Code）。参见子代理委托 → Worktree 隔离。
  max_spawn_depth: 1                        # 委托树深度（下限 1，无上限）。1 = 扁平（默认）：父级派生无法再委托的叶子。2 = 编排器子代理可以派生叶子孙代理；3+ 表示更深的树。
  orchestrator_enabled: true                # 全局总开关。为 false 时会忽略 role="orchestrator"，无论 max_spawn_depth 如何，每个子代理都被强制为叶子。
```

**子代理 provider:model 覆盖：** 默认情况下，子代理继承父 agent 的 provider 和模型。设置 `delegation.provider` 和 `delegation.model` 可将子代理路由到不同的 provider:model 组合——例如，在主 agent 运行昂贵推理模型的同时，为范围狭窄的子任务使用便宜/快速的模型。

**子代理 fallback 链：** 设置 `delegation.fallback_providers` 可为 worker 提供它们自己的链（条目格式与顶层列表相同）。一个被显式固定的子代理（按 provider、端点或模型）只有在声明了该链时才会使用它；否则它会明确报错失败，而不会借用父 agent 的路由。对于未固定的子代理，该设置缺失或为 `null` 时会保留对父链的继承。在 `delegation:` 下使用 `fallback_providers: []` 可完全禁用子代理的 fallback。

**直连端点覆盖：** 如果你想使用显而易见的自定义端点路径，请设置 `delegation.base_url`、`delegation.api_key` 和 `delegation.model`。这会把子代理直接发送到该 OpenAI 兼容端点，并优先于 `delegation.provider`。如果省略了 `delegation.api_key`，Hermes 只会回退到 `OPENAI_API_KEY`。当 `delegation.provider` 与 `delegation.base_url` 同时设置时，显式的端点和密钥仍然优先，但该 provider 的请求设置（来自你 `custom_providers` 条目中的 `extra_body` 覆盖和最大输出 token 数）会被带入子代理。

**按子代理的请求设置（`request_overrides`）：** `delegation.request_overrides` 是一个在每次子代理 API 调用上发送的请求设置字典。顶层键是 API 关键字参数（例如 `service_tier`）；`extra_body` 子字典会被合并到请求的 `extra_body` 中。它在**全部三种**解析分支上都会被遵循——直连 `base_url`、具名 `provider` 以及纯继承——因此该键总会生效。优先级：显式的 `request_overrides` 值会合并**覆盖**任何运行时或源自父级的覆盖——显式的顶层键优先，而 `extra_body` 会进行一层深度合并，因此运行时的 `extra_body` 键（例如某个 provider 的 `thinking: {type: disabled}` 个性设置）会保留，除非你的键重新定义了它们。典型用例是为委托子代理设置 OpenRouter 路由提示：

```yaml
delegation:
  model: "deepseek/deepseek-v4-flash-0731"
  base_url: "https://openrouter.ai/api/v1"
  api_key: "sk-or-..."
  request_overrides:
    extra_body:
      provider:
        sort: throughput   # 将子代理路由到最快的 OpenRouter provider
```
**协议（`api_mode`）：** Hermes 会根据 `delegation.base_url` 自动检测协议（例如以 `/anthropic` 结尾的路径 → `anthropic_messages`；Codex / 原生 Anthropic / Kimi-coding 的主机名保持其现有的检测方式）。对于启发式规则无法分类的端点——例如 Azure AI Foundry、MiniMax、智谱 GLM，或前置了 Anthropic 形态后端的 LiteLLM 代理——请把 `delegation.api_mode` 显式设为 `chat_completions`、`codex_responses` 或 `anthropic_messages` 之一。保持为空（默认）则继续使用自动检测。

委托 provider 使用与 CLI/gateway 启动相同的凭据解析方式。所有已配置的 provider 都受支持：`openrouter`、`nous`、`copilot`、`zai`、`kimi-coding`、`minimax`、`minimax-cn`。设置了 provider 时，系统会自动解析正确的 base URL、API 密钥和 API 模式——无需手动接线凭据。

**优先级：** 配置中的 `delegation.base_url` → 配置中的 `delegation.provider` → 父级 provider（继承）。配置中的 `delegation.model` → 父级模型（继承）。只设置 `model` 而不设置 `provider` 只会更改模型名称，同时保留父级的凭据（适用于在同一个 provider（如 OpenRouter）内切换模型）。

**宽度与深度：** `max_concurrent_children` 限制每批并行运行的子代理数量（默认 `3`，下限为 1，无上限）。也可通过 `DELEGATION_MAX_CONCURRENT_CHILDREN` 环境变量设置。当模型提交的 `tasks` 数组长度超过上限时，`delegate_task` 会返回一个说明该限制的工具错误，而不是静默截断。`max_spawn_depth` 控制委托树的深度（下限为 1，无上限）。在默认值 `1` 时，委托是扁平的：子代理不能派生孙代理，传入 `role="orchestrator"` 会被静默降级为 `leaf`。提高到 `2` 可让编排器子代理派生叶子孙代理；`3` 或更多用于更深的树。agent 通过 `role="orchestrator"` 按次调用选择编排；`orchestrator_enabled: false` 则无论如何都会把每个子代理强制回叶子。成本按乘法增长——在 `max_spawn_depth: 3` 且 `max_concurrent_children: 3` 时，这棵树最多可以达到 3×3×3 = 27 个并发的叶子 agent。使用模式请参阅 [子代理委托 → 深度限制与嵌套编排](features/delegation.md#depth-limit-and-nested-orchestration)。

**子进程通知：** 子代理启动的后台进程会把它们的完成/监视通知路由到父对话，但默认情况下这些通知在那里会被**抑制**——子代理整合后的结果才是交付物。设置 `delegation.surface_child_process_notifications: true` 可投递它们（并附带子代理归属信息）。委托结果本身永远不会被抑制。参见 [子代理委托 → 子代理后台进程通知](features/delegation.md#child-background-process-notifications)。

## Clarify {#clarify}

配置 gateway 等待澄清问题回复的时长。规范的键是 `agent.clarify_timeout`（默认 `3600` 秒）；如果显式设置了旧版的顶层 `clarify.timeout`，仍会被遵循：

```yaml
agent:
  clarify_timeout: 3600        # 等待用户澄清回复的秒数（0 或更小 = 不限制）
```

## 上下文文件（SOUL.md、AGENTS.md） {#context-files-soulmd-agentsmd}

Hermes 使用两种不同的上下文作用域：

| 文件 | 用途 | 作用域 |
|------|---------|-------|
| `SOUL.md` | **主要 agent 身份**——定义 agent 是谁（系统 prompt 中的第 1 个槽位） | `~/.hermes/SOUL.md` 或 `$HERMES_HOME/SOUL.md` |
| `.hermes.md` / `HERMES.md` | 项目专属指令（最高优先级） | 向上查找到 git 根目录 |
| `AGENTS.md` | 项目专属指令、编码约定 | 递归遍历目录 |
| `CLAUDE.md` | Claude Code 上下文文件（同样会被检测） | 仅工作目录 |
| `.cursorrules` | Cursor IDE 规则（同样会被检测） | 仅工作目录 |
| `.cursor/rules/*.mdc` | Cursor 规则文件（同样会被检测） | 仅工作目录 |

- **SOUL.md** 是 agent 的主要身份。它占据系统 prompt 中的第 1 个槽位，完全取代内置的默认身份。编辑它即可完全自定义 agent 的身份。
- 如果 SOUL.md 缺失、为空或无法加载，Hermes 会回退到内置的默认身份。
- **项目上下文文件使用优先级机制**——只会加载一种类型（第一个匹配者胜出）：`.hermes.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`。SOUL.md 总是独立加载。
- **AGENTS.md** 是分层的：如果子目录中也有 AGENTS.md，所有这些文件都会被合并。
- 如果尚不存在 `SOUL.md`，Hermes 会自动生成一个默认的。
- 所有已加载的上下文文件都会被限制在 `context_file_max_chars` 个字符以内（默认 20,000），并采用智能截断。

另请参阅：
- [个性与 SOUL.md](/user-guide/features/personality)
- [上下文文件](/user-guide/features/context-files)

## 工作目录 {#working-directory}

| 场景 | 默认值 |
|---------|---------|
| **CLI（`hermes`）** | 你运行命令时所在的当前目录 |
| **消息 gateway** | `~/.hermes/config.yaml` 中的 `terminal.cwd`；未设置时为主目录 `~` |
| **Docker / Singularity / Modal / SSH** | 容器或远程机器中的用户主目录 |

覆盖工作目录：
```yaml
# In ~/.hermes/config.yaml:
terminal:
  cwd: /home/myuser/projects
```

`~/.hermes/.env` 中的 `MESSAGING_CWD` 和直接设置的 `TERMINAL_CWD` 条目是为了兼容旧版的回退方式。新配置应使用 `terminal.cwd`。

## 网络 {#network}

针对出站 HTTP 的连接问题的变通设置：

```yaml
network:
  force_ipv4: false   # 强制出站连接使用 IPv4（默认：false）
```

`force_ipv4` —— 在 IPv6 损坏或不可达的服务器上，Python 会优先解析 AAAA 记录，可能会在回退到 IPv4 之前挂起整个 TCP 超时时长。将其设为 `true` 可完全跳过 IPv6，直接通过 IPv4 连接。

## 新手引导 {#onboarding}

首次接触时的引导提示以及结构化的 profile 构建提议：

```yaml
onboarding:
  profile_build: "ask"   # "ask"（默认）| "off"
  seen: {}               # 内部锁存状态——保持为空
```

- `profile_build` —— 控制在有史以来第一条 gateway 消息上提供的 profile 构建路径。`"ask"`（默认）会提议构建用户 profile；该提议**需要用户选择加入并经过同意**——agent 会在任何查询之前先询问，并且从不静默读取已连接的账户。`"off"` 只显示一段普通的介绍。该提议最多触发一次。
- `seen` —— 内部状态。Hermes 会在这里锁存每条已显示过的提示，使其永远不再触发；profile 构建提议显示过一次后也会被记录在这里。不要手动编辑它——如果你想重新看到所有提示，请清除整个 `onboarding` 部分。

## Dashboard {#dashboard}

[Web dashboard](/user-guide/features/web-dashboard) 的配置——视觉主题、公开 URL 和认证提供方。认证提供方（OAuth、基本密码、drain）在 web-dashboard 页面上有详细说明；这里是其 `config.yaml` 结构。

```yaml
dashboard:
  theme: "default"            # "default" | "midnight" | "ember" | "mono" | "cyberpunk" | "rose"
  show_token_analytics: false # 重新启用（仅本地估算的）token/费用分析界面
  public_url: ""              # OAuth redirect_uri 使用的完整公开地址（环境变量：HERMES_DASHBOARD_PUBLIC_URL）
  trusted_proxies: []         # 允许提供 X-Forwarded-* 头的代理 IP/CIDR
  oauth:                      # Portal OAuth 关卡（在使用 --host 且未使用 --insecure 时启用）
    client_id: ""             # agent:{instance_id} —— 由 Portal 分配
    portal_url: ""            # 为空 → 插件默认值（生产环境 Portal）
  basic_auth:                 # 自托管的用户名/密码关卡（dashboard_auth/basic 插件）
    username: ""              # 为空 → 插件不起作用
    password_hash: ""         # scrypt$...（首选——静态存储时没有明文）
    password: ""              # 明文回退（加载时在内存中哈希）
    secret: ""                # token 签名密钥；为空 → 每个进程随机生成
    session_ttl_seconds: 0    # 0 → 插件默认值（12 小时）
  drain_auth:                 # Drain 控制的服务凭据关卡（dashboard_auth/drain 插件）
    scope: "drain"            # 已验证主体上的能力标签
    min_secret_chars: 43      # 熵门槛（url-safe-b64 字符；43 ≈ 256 位）
  ws_ping_interval: 20.0      # 非回环 WebSocket 保活 ping 间隔（秒）
  ws_ping_timeout: 20.0       # 非回环 WebSocket 保活 pong 超时（秒）
  ws_orphan_reap_grace_s: 20.0 # WS 断开的会话被回收前的宽限时间（秒）
  ssh_isolated_idle_grace_s: 900.0 # Desktop-over-SSH 后端在没有客户端且没有运行中的轮次这么久之后退出
  ws_orphan_activity_stale_s: 600.0 # 断开连接的运行中轮次在被中断前的活动空闲上限（秒）
  startup_orphan_sweep: true  # 启动时关闭因 gateway 进程死亡而遗留的会话行
```

- `theme` —— dashboard 视觉主题。
- `show_token_analytics` —— 默认关闭。Analytics 页面以及 token/费用数字只是**本地的下限估算**（它们不包括辅助调用、重试、fallback 和缓存写入），因此可能远低于 provider 的账单。只有在你明白它们不是账单时才设为 `true`。
- `public_url` —— 设置后，它是构建 OAuth `redirect_uri` 所使用的完整地址（协议 + 主机 + 可选的路径前缀）。对于部署在无法可靠转发 `X-Forwarded-*` 头的反向代理之后的情况，请设置它。留空则使用代理头重建。
- `trusted_proxies` —— 允许提供 `X-Forwarded-Proto` 和 `X-Forwarded-For` 的 IP 地址或有界的 CIDR 网络。回环地址始终自动受信任。当 TLS 反向代理从另一个容器或主机连接时请配置此项。优先使用代理的确切 IP；只有在其地址是动态的情况下才使用一个小型的专用网络。通配符和 `/0` 网络会被拒绝。
- `oauth` / `basic_auth` / `drain_auth` —— 由内置的 dashboard-auth 插件读取的认证提供方配置。drain 机密本身**不**在这里设置；它通过 `HERMES_DASHBOARD_DRAIN_SECRET` 环境变量提供。完整的认证设置请参阅 [Web Dashboard](/user-guide/features/web-dashboard)。
- `ws_ping_interval` / `ws_ping_timeout` —— 非回环绑定的 WebSocket 保活调优（回环连接从不 ping）。在高延迟链路上（Tailscale、远距离 SSH 隧道），20 秒的默认值可能会制造出虚假的 1006 断开，请调高它们。
- `ssh_isolated_idle_grace_s`（默认 `900`）—— 通过 SSH 访问、由 Desktop 拥有的 `hermes serve --isolated` 后端是有意与 SSH 会话分离的，这样笔记本在连接中途休眠时也不会把它关掉；过去每次暗唤醒重连都会多留下一个持有 `state.db` 的后端。现在，当没有任何客户端 WebSocket 连接达到这么久并且没有 agent 轮次在运行时，后端会自行退出（运行中的轮次会让它保持存活；无法读取的轮次状态也会让它保持存活）。如果你依赖分离的后端在笔记本休眠后完成长时间的工作，请把它设高。此类后端还会发送慢速的 WebSocket ping（60 秒，10 分钟超时），以便发现半开的隧道。
- `ws_orphan_reap_grace_s` —— WS 断开的会话在被孤儿回收器收集之前等待的时长。如果客户端重连较慢，请与保活值一起调高。周期性的会话维护也会为已关闭的套接字完成清理，并重新设置缺失的孤儿计时器，因此一个断开的聊天不会仅仅因为其初始清理或计时器丢失就一直保留其所有权租约。重新连接会取消该计时器；活跃的委托工作和健康的运行中轮次仍受常规孤儿回收检查的保护。（`HERMES_TUI_WS_ORPHAN_REAP_GRACE_S` 仍作为内部覆盖保留。）
- `ws_orphan_activity_stale_s`（默认 `600`）—— 一个断开连接的**运行中**轮次的活动时钟（与 `agent.turn_liveness` 看门狗采样的是同一个时钟：API 等待、流式 token、工具心跳）必须空闲多久，孤儿回收器才会中断它。一个客户端不在但仍在积极产出的轮次会在分离状态下继续运行直至完成——合上笔记本、把移动应用切到后台或桌面更新都不再会取消健康的长轮次；只有真正卡住的轮次才会被中断。设为 `0` 则无论活动如何都在宽限窗口到期时中断（旧行为）。
- `startup_orphan_sweep`（默认 `true`）—— 上面的 WS 孤儿回收计时器是进程内的，因此如果 gateway 在它触发之前重启（更新、崩溃、systemd），会话行就会永远保持打开——在 `/resume` 和 dashboard 中表现为幽灵般的"活跃"工作。在每次 gateway 启动时——包括 stdio TUI（`entry.main`）和 desktop/dashboard WebSocket sidecar（`handle_ws`）——来源为 `tui` / `desktop` / `subagent`、并且其开始时间**和**最新消息都早于会话 TTL（`HERMES_TUI_SESSION_TTL_S`，默认 6 小时）的行，会以 `end_reason: startup_orphan_reap` 关闭。消息平台会话（Telegram、Discord……）永远不会被触碰，内存中的活跃会话（已经恢复的客户端）会被排除，被清扫的会话仍可恢复。
