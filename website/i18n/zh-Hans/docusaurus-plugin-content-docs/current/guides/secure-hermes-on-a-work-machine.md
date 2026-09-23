---
sidebar_position: 26
title: "在个人或工作电脑上运行 Hermes"
description: "在你日常使用的电脑上运行 Hermes Agent 的安全态势指南——默认设置保护了什么、如何进一步收紧，以及如何撤销失误"
---

# 在个人或工作电脑上运行 Hermes {#running-hermes-on-a-personal-or-work-machine}

你即将在自己日常使用的电脑上运行一个 agent——可能是个人笔记本，也可能是雇主管理的工作站。什么才是安全的姿态？

简短回答：默认设置已经完成了大部分工作。Hermes 默认即安全，采用纵深防御模型，覆盖命令审批、文件写入安全和凭据处理。本页介绍开箱即启用的保护措施、在共享或工作电脑上应收紧哪些开关，以及出错时如何撤销。这里的每一项控制都在[安全](/user-guide/security)指南中有详细说明。

## 默认设置已经提供的保护 {#what-the-defaults-already-protect}

全新安装、未做任何配置时，以下保护即已生效：

**危险命令需要审批。** 在执行任何命令之前，Hermes 都会将其与一份精心维护的危险模式列表比对——递归删除、写入 `/etc/`、磁盘操作、管道传给 shell 等等。默认的 `approvals.mode: smart` 使用一个辅助 LLM 评估风险：低风险命令仅就该命令自动批准，真正危险的命令自动拒绝，不确定的情况升级为手动确认。

**审批提示失败即关闭。** 如果你在超时时间内（默认 300 秒）没有回应审批提示，该命令会被**拒绝**。离开座位永远不会悄悄批准任何东西。

**硬性黑名单是始终生效的底线。** 某些命令——`rm -rf /`、fork 炸弹、清零物理磁盘——**无论**审批模式、`--yolo` 还是明确的“始终允许”，都会被拒绝。黑名单在审批层看到命令之前就会触发，并且没有任何覆盖标志。

**写入敏感路径的操作会被阻止。** `write_file` 和 `patch` 工具无法触碰磁盘上任何位置的操作系统凭据存储（`~/.ssh/`、`~/.aws/`、`~/.kube/`、`/etc/sudoers`、`~/.netrc`）、Hermes 凭据存储（`auth.json`、`.env`、配对数据）或项目密钥文件（`.env`、`.env.local`、`.envrc`）。被阻止的写入会立即返回错误——没有审批提示，也无法从聊天界面覆盖。

**输出中的密钥会被脱敏。** `security.redact_secrets` 默认开启：工具输出中看起来像 API 密钥、令牌和密码的内容，在进入对话上下文和日志之前就会被脱敏。

**你的数据只会发往你指定的地方。** API 调用**只会发往你配置的 LLM 提供商**。Hermes Agent 不收集遥测、使用数据或分析数据。你的对话、记忆和技能都存储在本地的 `~/.hermes/` 中。参见 [FAQ](/reference/faq#is-my-data-sent-anywhere)。

:::info
表面之下还有更多保护——所有可访问 URL 的工具都有 SSRF 防护，MCP 子进程使用经过过滤的环境变量，上下文文件会进行提示词注入扫描。[安全](/user-guide/security)页面记录了每一层防护。
:::

## 为共享或工作电脑加固 {#tightening-for-a-shared-or-work-machine}

在存有雇主数据、生产凭据或他人文件的电脑上，请在默认设置之上叠加以下措施。

### 将审批切换为手动 {#switch-approvals-to-manual}

`smart` 模式会自动批准低风险命令。如果你想亲自查看每一条被标记的命令：

```yaml
approvals:
  mode: manual
```

手动模式在执行被标记的命令之前总会先询问你。

### 添加你自己的拒绝规则 {#add-your-own-deny-rules}

`approvals.deny` 是一组 glob 模式，会无条件阻止匹配的终端命令——即使在 `--yolo`、`/yolo` 或 `mode: off` 下也是如此。它是内置硬性黑名单的用户可编辑版本。用它来声明在这台电脑上绝不能运行的操作：

```yaml
approvals:
  deny:
    - "git push --force*"
    - "*curl*|*sh*"
    - "dd if=* of=/dev/*"
```

这些模式是不区分大小写的 [fnmatch](https://docs.python.org/3/library/fnmatch.html) glob，与完整命令文本进行匹配；匹配过程会作用于危险模式检测器所使用的同一组规范化/去混淆变体，因此简单的引号技巧无法绕过规则。请始终给模式加引号——开头裸露的 `*` 会导致 YAML 解析错误。修改立即生效，无需重启。详情：[用户自定义拒绝规则](/user-guide/security#user-defined-deny-rules-approvalsdeny)。

### 沙箱化文件写入 {#sandbox-file-writes}

`HERMES_WRITE_SAFE_ROOT` 将 `write_file` 和 `patch` 限制在你列出的目录前缀之内——此范围之外的一切都会被硬性阻止。在 Unix 上，多个根目录用 `:` 分隔：

```bash
export HERMES_WRITE_SAFE_ROOT=/path/to/project:/home/you/.hermes
```

安全根目录内的敏感路径仍然会被阻止——把它指向 `$HOME` 并不会允许写入 `~/.ssh/id_rsa`。

:::caution
不要随手把它加到 `~/.hermes/.env` 中。如果你只把它设置为某个项目目录，agent 就无法写入 `~/.hermes/cron/jobs.json`、profile 技能或该前缀之外的其他 Hermes 状态。请像上面那样把你的 Hermes 主目录作为第二个根目录加入。
:::

### 将命令执行移出宿主机 {#move-command-execution-off-the-host}

最强的隔离是根本不在你的电脑上运行命令。终端工具支持多种[后端](/user-guide/features/tools#terminal-backends)：

| 后端 | 隔离程度 |
|---------|-----------|
| `local` | 无——在宿主机上运行（适用危险命令检查） |
| `docker` | 容器——容器本身就是安全边界 |
| `ssh` | 远程机器——让执行留在另一台服务器上 |

```yaml
terminal:
  backend: docker
  docker_image: "nikolaik/python-nodejs:python3.11-nodejs20"
  docker_forward_env: []  # 仅显式白名单；留空可让密钥不进入容器
```

每个 Docker 容器都以加固设置运行——移除所有 Linux capabilities（仅加回最小集合）、`no-new-privileges`、进程数限制，以及限制大小的 tmpfs 挂载。使用容器后端时，容器内的破坏性命令无法损害宿主机，这也是为什么在那里会跳过危险命令检查。

对于 `ssh`，在 `config.yaml` 中设置 `terminal.backend: ssh`，并在 `~/.hermes/.env` 中通过 `TERMINAL_SSH_HOST`、`TERMINAL_SSH_USER` 和 `TERMINAL_SSH_KEY` 提供主机信息。参见[网络隔离](/user-guide/security#network-isolation)。

### 如果启用了消息功能：白名单与配对 {#if-messaging-is-on-allowlists-and-pairing}

在这台电脑上运行 [gateway](/user-guide/security#user-authorization-gateway)？默认已经是拒绝：如果没有配置任何白名单，且未设置 `GATEWAY_ALLOW_ALL_USERS`，**所有用户都会被拒绝**。请保持显式配置：

```bash
# ~/.hermes/.env
TELEGRAM_ALLOWED_USERS=123456789
GATEWAY_ALLOWED_USERS=123456789
```

也可以使用私信配对来代替硬编码 ID：未知用户会收到一次性配对码，你在 CLI 中用 `hermes pairing approve <platform> <code>` 批准他们。在你在意的电脑上，永远不要设置 `GATEWAY_ALLOW_ALL_USERS=true`。

## 撤销层：检查点与 `/rollback` {#the-undo-layer-checkpoints-and-rollback}

审批关卡用于防止破坏；[检查点](/user-guide/checkpoints-and-rollback)用于逆转破坏。启用后，Hermes 会在破坏性操作之前自动为你的项目创建快照——`write_file`、`patch`，以及 `rm`、`mv`、`sed -i`、`git reset` 等破坏性终端命令——存入 `~/.hermes/checkpoints/store/` 下的影子 git 存储。你项目真正的 `.git` 永远不会被触碰。

检查点需要主动启用。按会话启用：

```bash
hermes chat --checkpoints
```

或全局启用：

```yaml
checkpoints:
  enabled: true
```

然后在会话中：

| 命令 | 说明 |
|---------|-------------|
| `/rollback` | 列出所有检查点及变更统计 |
| `/rollback diff <N>` | 预览自检查点 N 以来的变更 |
| `/rollback <N>` | 恢复到检查点 N（同时撤销上一轮对话） |
| `/rollback <N> <file>` | 从检查点 N 恢复单个文件 |

:::tip
恢复之前先用 `/rollback diff <N>` 预览；并将检查点与 git worktree 结合使用以获得最大安全性——每个 Hermes 会话使用各自的 worktree，检查点作为额外的一层保护。
:::

## 这个威胁模型是什么——以及不是什么 {#what-this-threat-model-is--and-isnt}

要清醒地认识这些控制措施防御的是什么。正如[安全](/user-guide/security#user-defined-deny-rules-approvalsdeny)指南所说：

> 拒绝规则是针对“诚实但犯错”的 agent 的护栏，与危险模式检测器的威胁模型相同。它们不是针对蓄意对抗进程的沙箱——那种情况请使用隔离后端（Docker、Modal）或限制出站流量的环境。

文件写入防护同样如此：它们只作用于 `write_file` 和 `patch`，而 `terminal` 工具以同一个操作系统用户身份运行。拒绝列表能减少意外破坏，并给模型一个明确的停止信号；它并不能把一个恶意或已被攻陷的 agent 关进沙箱。如果你的需求是隔离遏制而不是护栏，答案就是隔离的终端后端——那才是为此设计的边界。

## 一份谨慎的起步配置 {#a-cautious-starting-config}

把以上所有内容组合起来。在 `~/.hermes/config.yaml` 中按需调整：

```yaml
approvals:
  mode: manual                  # 亲自查看每一条被标记的命令
  timeout: 300                  # 未回应的提示会被拒绝（失败即关闭）
  deny:                         # 永不运行列表——即使 /yolo 也不例外
    - "git push --force*"
    - "*curl*|*sh*"
    - "dd if=* of=/dev/*"

security:
  redact_secrets: true          # 本就是默认值；此处写明以求清晰

checkpoints:
  enabled: true                 # 在破坏性操作之前创建快照

terminal:
  backend: docker               # 或 ssh——让执行远离宿主机
  docker_forward_env: []        # 容器内不带任何宿主机密钥
```

如果你想要写入沙箱，在 `~/.hermes/.env` 中添加：

```bash
HERMES_WRITE_SAFE_ROOT=/path/to/project:/home/you/.hermes
```

## 另请参阅 {#see-also}

- **[安全](/user-guide/security)**——完整的纵深防御参考：每一种审批模式、容器加固标志、gateway 授权、MCP 凭据过滤
- **[检查点与回滚](/user-guide/checkpoints-and-rollback)**——配置、存储维护和恢复流程
- **[工具与工具集](/user-guide/features/tools)**——所有终端后端及其配置
- **[配置](/user-guide/configuration)**——完整的 `config.yaml` 参考
