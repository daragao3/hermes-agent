---
sidebar_position: 1
title: "工具与工具集"
description: "Hermes Agent 工具概览——可用工具、工具集工作方式及终端后端"
---

# 工具与工具集

工具是扩展 Agent 能力的函数。它们被组织为逻辑上的**工具集**，可按平台启用或禁用。

## 可用工具 {#available-tools}

Hermes 内置了丰富的工具注册表，涵盖网页搜索、浏览器自动化、终端执行、文件编辑、记忆、委托、定时任务、Home Assistant 等功能。

:::note
**Honcho 跨会话记忆**作为记忆提供者插件（`plugins/memory/honcho/`）提供，而非内置工具集。安装方式请参阅 [Plugins](./plugins.md)。
:::

高层分类：

| 分类 | 示例 | 描述 |
|----------|----------|-------------|
| **Web** | `web_search`, `web_extract` | 搜索网页并提取页面内容。 |
| **X 搜索** | `x_search` | 通过 xAI 内置的 `x_search` Responses 工具搜索 X（Twitter）帖子和话题——需要 xAI 凭据（SuperGrok OAuth 或 `XAI_API_KEY`）；默认关闭，可通过 `hermes tools` → 🐦 X (Twitter) Search 启用。 |
| **终端与文件** | `terminal`, `process`, `read_file`, `patch` | 执行命令并操作文件。 |
| **浏览器** | `browser_navigate`, `browser_snapshot`, `browser_vision` | 支持文本和视觉的交互式浏览器自动化。 |
| **媒体** | `vision_analyze`, `image_generate`, `text_to_speech` | 多模态分析与生成。 |
| **Agent 编排** | `todo`, `clarify`, `execute_code`, `delegate_task` | 规划、澄清、代码执行及子 Agent 委托。 |
| **记忆与召回** | `memory`, `session_search` | 持久化记忆与会话搜索。 |
| **自动化** | `cronjob` | 支持创建/列出/更新/暂停/恢复/运行/删除操作的定时任务。出站投递由 cron 自身的投递机制、`hermes send` CLI 和 gateway 通知器负责——而不是由 Agent 可调用的工具负责。 |
| **集成** | `ha_*`、MCP server 工具 | Home Assistant、MCP 及其他集成。 |

如需查看由代码派生的权威注册表，请参阅 [内置工具参考](/reference/tools-reference) 和 [工具集参考](/reference/toolsets-reference)。

:::tip Nous Tool Gateway
付费 [Nous Portal](https://portal.nousresearch.com) 订阅者可通过 **[Tool Gateway](tool-gateway.md)** 使用网页搜索、图像生成、TTS 和浏览器自动化——无需单独配置 API 密钥。运行 `hermes model` 启用，或通过 `hermes tools` 配置各工具。
:::

## 使用工具集 {#using-toolsets}

```bash
# 使用指定工具集
hermes chat --toolsets "web,terminal"

# 查看所有可用工具
hermes tools

# 按平台交互式配置工具
hermes tools
```

常用工具集包括 `web`、`search`、`terminal`、`file`、`browser`、`vision`、`image_gen`、`skills`、`tts`、`todo`、`memory`、`session_search`、`cronjob`、`code_execution`、`delegation`、`clarify`、`homeassistant`、`messaging`、`spotify`、`discord`、`discord_admin`、`debugging` 和 `safe`。

完整列表（包括 `hermes-cli`、`hermes-telegram` 等平台预设以及 `mcp-<server>` 等动态 MCP 工具集）请参阅 [工具集参考](/reference/toolsets-reference)。

## 工具结果注释 {#tool-result-annotations}

阅读 Agent 对话记录时，以下几种工具行为值得了解：

- **信号终止会附带说明。** 当终端命令被信号终止时，结果会带上一条人类可读的说明，而不是一个孤零零的数字代码——例如退出码 `-9`/`137` 会变成“terminated by signal 9: SIGKILL — often the kernel OOM killer on memory exhaustion, or an explicit kill -9”（被信号 9 终止：SIGKILL——通常是内存耗尽时内核 OOM killer 所为，或显式执行了 kill -9），段错误、abort、SIGTERM、管道破裂以及 CPU/文件大小限制也会以同样方式标注。负数代码（subprocess 语义）会被明确陈述；而 shell 的 `128+signum` 约定则以“usually”（通常）加以限定，因为应用程序也可能合法地以这些代码退出。
- **UTF-16 文本文件会被转码，而不是拒绝读取。** `read_file` 会检测 UTF-16（通过 BOM 或字节模式启发式判断，支持两种字节序——Windows 记事本文件和 PowerShell `>` 重定向中很常见），并将其转码为 UTF-8 进行显示，而不是将文件标记为二进制。结果中会包含一条提示，说明进行了转换；通过 `patch`/`write_file` 进行的编辑会以 UTF-8 重新编码。超过 10 MB 的文件以及真正的二进制文件仍会被按二进制文件拒绝。

## 终端后端 {#terminal-backends}

终端工具可在不同环境中执行命令：

| 后端 | 描述 | 适用场景 |
|---------|-------------|----------|
| `local` | 在本机运行（默认） | 开发、可信任务 |
| `docker` | 隔离容器 | 安全性、可复现性 |
| `ssh` | 远程服务器 | 沙箱隔离，防止 Agent 修改自身代码 |
| `singularity` | HPC 容器 | 集群计算、无 root 权限 |
| `modal` | 云端执行 | 无服务器、弹性扩展 |
| `daytona` | 云端沙箱工作区 | 持久化远程开发环境 |
| `vercel_sandbox` | Vercel Sandbox 云微虚拟机 | 带快照文件系统持久化的云端执行 |

### 配置 {#configuration}

```yaml
# 在 ~/.hermes/config.yaml 中
terminal:
  backend: local    # 或：docker, ssh, singularity, modal, daytona, vercel_sandbox
  cwd: "."          # 工作目录
  timeout: 180      # 命令超时时间（秒）
```

### Shell 启动文件与非交互式命令 {#shell-startup-files-and-non-interactive-commands}

Agent 的终端调用以**非交互方式**运行你的 shell——没有 TTY，提示符前也没有人。那些在普通终端中你从未察觉的繁重或交互式 shell 初始化，可能会破坏 Agent 执行的每一条命令，或使其严重变慢：

- **初始化缓慢（`nvm`、版本管理器、访问网络的提示符）：** 经典的 `nvm.sh` 加载方式会给*每一次* shell 启动增加明显延迟，而 Agent 会启动大量 shell。耗时数秒的 rc 文件会让一个简单的 `git status` 面临超时风险。
- **需要 TTY 的代码块：** `.bashrc`/`.zshrc` 中任何会提示输入、执行 `tmux`/`screen` attach、调用 `read` 或打印菜单的内容，都会让非交互式 shell 挂起——命令看起来一直在运行，最后超时。
- **无条件输出：** 会 `echo` 横幅的 rc 文件会污染 Agent 需要解析的每一条命令输出。

解决方法是大多数发行版已在 `.bashrc` 顶部附带的标准守卫——当 shell 为非交互式时提前返回，并将任何繁重或交互式的内容放在它下面：

```bash
# ~/.bashrc —— 将此守卫放在靠近顶部的位置
case $- in
  *i*) ;;      # 交互式：继续
  *) return;;  # 非交互式：到此为止
esac

# 繁重/交互式初始化放在守卫下方
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
```

Zsh 用户：将仅登录时需要的设置放在 `.zprofile` 中，将仅交互时需要的设置放在 `.zshrc` 中；保持 `.zshenv` 精简，因为它会在每个 shell（包括非交互式 shell）中运行。如果 Agent 确实需要某个只有你的 rc 文件才会加入 `PATH` 的工具，请将 `PATH` 修改导出到守卫*上方*（路径导出开销很小），或将该二进制文件符号链接到 `~/.local/bin`。

如果 Agent 的终端命令在你自己的终端中正常工作后立刻挂起或超时，首先应怀疑你的 shell 初始化。

### Docker 后端 {#docker-backend}

```yaml
terminal:
  backend: docker
  docker_image: python:3.11-slim
```

**单个持久容器，在整个进程生命周期内共享。** Hermes 在首次使用时启动一个长期运行的容器（`docker run -d ... sleep infinity`），并通过 `docker exec` 将所有终端、文件及 `execute_code` 调用路由到同一容器中。工作目录变更、已安装的包、环境调整以及写入 `/workspace` 的文件，在同一 Hermes 进程的整个生命周期内，跨 `/new`、`/reset` 和 `delegate_task` 子 Agent 均会保留。容器在关闭时停止并删除。

这意味着 Docker 后端的行为类似持久化沙箱虚拟机，而非每次命令都使用全新容器。如果你执行过一次 `pip install foo`，该包在本次会话的剩余时间内均可用。如果你执行了 `cd /workspace/project`，后续的 `ls` 调用将看到该目录。完整的生命周期详情及控制 `/workspace` 和 `/root` 是否跨 Hermes 重启保留的 `container_persistent` 标志，请参阅 [配置 → Docker 后端](../configuration.md#docker-backend)。

### SSH 后端 {#ssh-backend}

推荐用于安全场景——Agent 无法修改自身代码：

```yaml
terminal:
  backend: ssh
```
```bash
# 在 ~/.hermes/.env 中设置凭据
TERMINAL_SSH_HOST=my-server.example.com
TERMINAL_SSH_USER=myuser
TERMINAL_SSH_KEY=~/.ssh/id_rsa
```

### Singularity/Apptainer

```bash
# 为并行 worker 预构建 SIF
apptainer build ~/python.sif docker://python:3.11-slim

# 配置
hermes config set terminal.backend singularity
hermes config set terminal.singularity_image ~/python.sif
```

### Modal（无服务器云） {#modal-serverless-cloud}

```bash
uv pip install modal
modal setup
hermes config set terminal.backend modal
```

### Vercel Sandbox

```bash
pip install 'hermes-agent[vercel]'
hermes config set terminal.backend vercel_sandbox
hermes config set terminal.vercel_runtime node24
```

需同时配置 `VERCEL_TOKEN`、`VERCEL_PROJECT_ID` 和 `VERCEL_TEAM_ID` 三个凭据。此访问令牌配置方式是在 Render、Railway、Docker 及类似平台上进行部署和正常长期运行 Hermes 进程的推荐路径。支持的运行时为 `node24`、`node22` 和 `python3.13`；Hermes 默认使用 `/vercel/sandbox` 作为远程工作区根目录。

对于本地一次性开发，Hermes 也接受短期 Vercel OIDC token：

```bash
VERCEL_OIDC_TOKEN="$(vc project token <project-name>)" hermes chat
```

在已关联的 Vercel 项目目录中：

```bash
VERCEL_OIDC_TOKEN="$(vc project token)" hermes chat
```

启用 `container_persistent: true` 后，Hermes 使用 Vercel 快照在同一任务的沙箱重建时保留文件系统状态，其中可包含沙箱内 Hermes 同步的凭据、技能和缓存文件。快照不保留活跃进程、PID 空间或相同的活跃沙箱标识。

后台终端命令使用 Hermes 通用的非本地进程流程：在沙箱存活期间，spawn、poll、wait、log 和 kill 均通过标准 process 工具运行，但 Hermes 不提供清理或重启后的原生 Vercel 后台进程恢复能力。

`container_disk` 保持未设置或使用共享默认值 `51200`；Vercel Sandbox 不支持自定义磁盘大小，设置后将导致诊断/后端创建失败。

### 容器资源 {#container-resources}

为所有容器后端配置 CPU、内存、磁盘和持久化：

```yaml
terminal:
  backend: docker  # 或 singularity, modal, daytona, vercel_sandbox
  container_cpu: 1              # CPU 核心数（默认：1）
  container_memory: 5120        # 内存（MB，默认：5GB）
  container_disk: 51200         # 磁盘（MB，默认：50GB）
  container_persistent: true    # 跨会话持久化文件系统（默认：true）
```

启用 `container_persistent: true` 后，已安装的包、文件和配置将跨会话保留。

### 容器安全 {#container-security}

所有容器后端均启用安全加固：

- 只读根文件系统（Docker）
- 丢弃所有 Linux capabilities
- 禁止权限提升
- PID 限制（256 个进程）
- 完整命名空间隔离
- 通过卷挂载实现持久化工作区，而非可写根层

Docker 可通过 `terminal.docker_forward_env` 接受显式的环境变量白名单，但转发的变量对容器内的命令可见，应视为在该会话中已暴露。

## 后台进程管理 {#background-process-management}

启动后台进程并进行管理：

```python
terminal(command="pytest -v tests/", background=true)
# 返回：{"session_id": "proc_abc123", "pid": 12345}

# 然后使用 process 工具进行管理：
process(action="list")       # 显示所有运行中的进程
process(action="poll", session_id="proc_abc123")   # 检查状态
process(action="wait", session_id="proc_abc123")   # 阻塞直到完成
process(action="log", session_id="proc_abc123")    # 完整输出
process(action="kill", session_id="proc_abc123")   # 终止进程
process(action="write", session_id="proc_abc123", data="y")  # 发送输入
```

PTY 模式（`pty=true`）可启用 Codex 和 Claude Code 等交互式 CLI 工具。

已完成的后台命令会在当前配置档案中保留其退出状态和捕获的输出。
恢复启动该命令的会话（或其上下文压缩后的延续会话），再使用原始 `session_id`
调用 `process(action="log")` 读取输出、调用 `process(action="poll")` 查看退出状态。
即使知道完整的进程标识，无关的会话以及未绑定所属会话的请求也不能读取保留的结果。
`process(action="list")` 也会列出当前任务或会话的保留结果。

Hermes 在配置档案的 Hermes 主目录下的 `logs/process-results/` 中保留最近的
**64 个已完成结果**，自完成起最多保存 **7 天**。每份记录最多包含现有的滚动
**200,000 个字符输出末尾**，并始终应用终端的敏感信息脱敏规则，即使实时输出脱敏已关闭。
过期记录会在后续读取或写入结果时清理。恢复结果不会重新运行命令，也不会重放完成通知。
这仅保留父进程存活期间已经完成的工作，不会让未完成的子进程在超时或崩溃后继续运行。

## Sudo 支持 {#sudo-support}

在交互式父会话中，受支持的 sudo 命令会使用掩码密码提示（在本次会话内缓存）。这包括字面量绝对路径或带引号的可执行文件路径，以及带普通选项和赋值的 `env` 前缀，例如 `env -u UNUSED /usr/bin/sudo id`。无密码 sudo 不需要提示。你也可以在 Agent 所在机器上配置档案的 `.env` 文件中设置 `SUDO_PASSWORD`。

诸如 `bash -c 'sudo id'` 之类的 shell 载荷、`env -S` 拆分字符串、动态可执行文件路径以及无法识别的 `env` 选项，都不会被密码改写器解析。需要交互式提示时，请直接调用 sudo。此处理不会改变审批规则，也不会改变针对 Agent 自行提供 sudo 密码的防护。

委托的子 Agent 无法打开密码提示：它们的并发工作没有串行化的人工密码通道。请改在父会话中运行该命令，或在本地配置 `SUDO_PASSWORD`。消息平台/无头会话没有安全的密码回复通道；切勿在聊天中发送密码。

:::warning
在消息平台上，如果 sudo 失败，输出中会提示将 `SUDO_PASSWORD` 添加到 `~/.hermes/.env`。
:::
