---
sidebar_position: 3
title: "更新与卸载"
description: "如何将 Hermes Agent 更新至最新版本或将其卸载"
---

# 更新与卸载

## 更新

使用单条命令更新至最新版本：

```bash
hermes update
```

此命令会从 `main` 拉取最新代码、更新依赖项，并提示你配置自上次更新以来新增的选项。

:::tip
`hermes update` 会自动检测新的配置选项并提示你添加。如果跳过了该提示，可手动运行 `hermes config check` 查看缺失的选项，再运行 `hermes config migrate` 以交互方式添加。
:::

### 更新过程

运行 `hermes update` 时，将依次执行以下步骤：

1. **更新前快照** — 默认保存一份轻量级状态快照（涵盖配对数据、cron 任务、`config.yaml`、`.env`、`auth.json` 及其他运行时修改的状态文件；单个超过 1 GiB 的文件会被跳过，因此大型会话数据库不会拖慢更新）。由 `updates.pre_update_backup` 控制（默认 `quick`，`full` 为整个 `HERMES_HOME` 的 zip 备份，`off` 为禁用）。可通过 [快照与回滚](../user-guide/checkpoints-and-rollback.md) 中描述的快照恢复流程进行恢复。
2. **Git pull** — 从 `main` 分支拉取最新代码并更新子模块
3. **拉取后语法校验 + 自动回滚** — 拉取完成后，Hermes 会编译每次调用 `hermes` 时启动阶段都会导入的八个关键文件。若其中任何一个无法解析（例如残留的合并冲突标记、意外被截断的文件），Hermes 会运行 `git reset --hard <pre-pull-sha>` 将安装回滚，以保证你的 shell 仍可启动。等上游修复落地后再重新运行 `hermes update`。
4. **依赖安装** — 运行 `uv pip install -e ".[all]"` 以获取新增或变更的依赖项
5. **配置迁移** — 检测自当前版本以来新增的配置选项并提示设置
6. **Gateway 自动重启** — 更新完成后刷新正在运行的 gateway，使新代码立即生效。由服务管理的 gateway（Linux 上的 systemd、macOS 上的 launchd）通过服务管理器重启；手动启动的 gateway 在 Hermes 能将运行中的 PID 映射回某个 profile 时会自动重新启动。

### 针对非默认分支更新：`--branch`

默认情况下 `hermes update` 跟踪 `origin/main`。传入 `--branch <name>` 可针对其他分支更新——适用于 QA 通道、功能分支或候选发布版测试：

```bash
hermes update --branch release-candidate
hermes update --check --branch experimental   # 仅预览落后了多少
```

如果你的本地检出位于其他分支，Hermes 会自动 stash 未提交的工作，将 HEAD 切换到目标分支，然后再拉取。本地不存在的分支会自动从 `origin/<name>` 跟踪（`git checkout -B <name> origin/<name>`）。任何地方都不存在的分支会干净地失败——退出前会恢复你 stash 的改动，因此你绝不会被困在奇怪的状态里。仅适用于 `main` 的 fork 上游同步逻辑在非 `main` 分支上会自动跳过。

### 非交互式更新中的本地改动

当你在终端里运行 `hermes update` 时，Hermes 会 stash 源码树中所有未提交的改动，拉取，然后**询问**是否恢复它们——与一直以来的行为完全一致。交互式更新没有任何变化。

当更新在**没有终端**的情况下运行时——来自桌面/聊天应用的"更新"按钮，或由 gateway 触发的更新——没有提示可供回答。此时由 `updates.non_interactive_local_changes` 设置决定你 stash 的改动会怎样：

```yaml
# ~/.hermes/config.yaml
updates:
  non_interactive_local_changes: stash   # 默认：保留 + 自动恢复
  # non_interactive_local_changes: discard  # 丢弃本地源码改动
```

- `stash`（默认）— 自动 stash、拉取，然后把你的改动自动恢复到更新后的代码之上。不会丢失任何内容；若恢复时出现冲突，改动会保留在 git stash 中以便手动恢复。
- `discard` — 自动 stash 并在拉取后丢弃该 stash，使更新总是落在干净的工作树上。仅在你从不打算保留 Hermes 源码本地改动的机器上使用。它执行的是 stash drop（而非 `git reset --hard` + `git clean -fd`），因此 `node_modules`、`venv` 和构建产物等被忽略的路径绝不会被触碰。

在桌面应用中，该项位于 **Settings → Advanced → In-App Update Local Changes**。

### 仅预览：`hermes update --check`

想在拉取前确认是否有更新？运行 `hermes update --check` — 它会获取并与 `origin/main` 比较提交。不修改任何文件，不重启 gateway。适合在以"是否有更新"为条件的脚本和 cron 任务中使用。

### 完整更新前备份：`--backup`

对于高价值 profile（生产环境 gateway、团队共享安装），可选择在拉取前对 `HERMES_HOME`（配置、认证、会话、技能、配对数据）进行完整备份：

```bash
hermes update --backup
```

或将其设为每次运行的默认行为：

```yaml
# ~/.hermes/config.yaml
updates:
  pre_update_backup: full
```

`updates.pre_update_backup` 是单一开关，有三种模式：`quick`（默认 — 上述轻量级状态快照）、`full`（快速快照加上完整的 `HERMES_HOME` zip 备份；在大型 home 目录上可能增加数分钟）、`off`（完全不做更新前备份 — `--no-backup` 对单次运行有相同效果）。旧版布尔值仍然有效：`true` 等同于 `full`，`false` 等同于 `off`。

### Windows：另一个 `hermes.exe` 正在运行

在 Windows 上，如果 `hermes update` 检测到另一个 `hermes.exe` 进程持有 venv 入口点可执行文件的句柄，它将拒绝运行 — 最常见的情况是 Hermes Desktop 应用启动的后端进程、另一个终端中打开的 `hermes` REPL，或正在运行的 gateway：

```
$ hermes update
✗ Another hermes.exe is running:
    PID 12345  hermes.exe

  Updating now would fail to overwrite ...\venv\Scripts\hermes.exe because
  Windows blocks REPLACE on a running executable.

  Close Hermes Desktop, exit any open `hermes` REPLs, and
  stop the gateway (`hermes gateway stop`) before retrying.
  Override with `hermes update --force` if you've already
  confirmed those processes will not write to the venv.
```

关闭列出的进程后重试。如果你确定并发进程不会造成干扰（极少见 — 通常仅在杀毒软件 shim 被误判时有用），可传入 `--force` 跳过检查。此时更新程序仍会以指数退避方式重试 `.exe` 重命名操作，对于顽固的文件锁，会通过 `MoveFileEx(MOVEFILE_DELAY_UNTIL_REBOOT)` 将替换操作安排在下次重启时执行，以确保更新能够完成。

另有一道独立的防护：只要还有进程在使用该 venv 的 Python 解释器运行（桌面应用的后端、gateway、Python REPL），它就会拒绝改动 venv。这些进程会锁住原生扩展文件（`.pyd`），而依赖同步若因权限拒绝错误在中途失败，会让安装卡在两个版本之间。这道防护**不会**被 `--force` 绕过；如果你确信检测到的占用者是误报，请使用显式的 `hermes update --force-venv`。

预期输出如下：

```
$ hermes update
Updating Hermes Agent...
📥 Pulling latest code...
Already up to date.  (or: Updating abc1234..def5678)
📦 Updating dependencies...
✅ Dependencies updated
🔍 Checking for new config options...
✅ Config is up to date  (or: Found 2 new options — running migration...)
🔄 Restarting gateways...
✅ Gateway restarted
✅ Hermes Agent updated successfully!
```

### 更新后建议的验证步骤

`hermes update` 处理主要的更新流程，但快速验证可确认一切正常落地：

1. `git status --short` — 若工作树出现意外的脏状态，请在继续前检查
2. `hermes doctor` — 检查配置、依赖项和服务健康状态
3. `hermes --version` — 确认版本已按预期更新
4. 如果使用 gateway：`hermes gateway status`
5. 检查 Node.js 依赖是否存在漏洞：`hermes doctor --audit`（默认关闭——每棵依赖树的审计需要一到两分钟）。若报告有问题，请在标记的目录中运行 `npm audit fix`

:::warning 更新后工作树出现脏状态
如果 `hermes update` 后 `git status --short` 显示意外变更，请在继续前停下来检查。这通常意味着本地修改被重新应用到了更新后的代码之上，或依赖步骤刷新了锁文件。
:::

### 终端在更新中途断开连接

`hermes update` 针对意外终端断开进行了保护：

- 更新会忽略 `SIGHUP`，因此关闭 SSH 会话或终端窗口不再会在安装中途终止它。`pip` 和 `git` 子进程继承此保护，因此 Python 环境不会因连接断开而处于半安装状态。
- 更新运行期间，所有输出会同步镜像到 `~/.hermes/logs/update.log`。如果终端消失，重新连接后检查日志，确认更新是否完成以及 gateway 重启是否成功：

```bash
tail -f ~/.hermes/logs/update.log
```

- `Ctrl-C`（SIGINT）和系统关机（SIGTERM）仍会被响应 — 这些是主动取消操作，而非意外中断。

你不再需要将 `hermes update` 包裹在 `screen` 或 `tmux` 中来应对终端断开。

### 查看当前版本

```bash
hermes version
```

与 [GitHub releases 页面](https://github.com/NousResearch/hermes-agent/releases) 上的最新版本进行比较。

### 从消息平台更新

你也可以直接从 Telegram、Discord、Slack、WhatsApp 或 Teams 发送以下命令进行更新：

```
/update
```

此命令会拉取最新代码、更新依赖项并重启正在运行的 gateway。Bot 在重启期间会短暂下线（通常为 5–15 秒），之后恢复服务。

### 手动更新

如果你是手动安装的（未使用快速安装脚本）：

```bash
cd /path/to/hermes-agent
# 激活安装时创建的 venv（位于源码树之外）
export VIRTUAL_ENV="$HOME/.hermes/venvs/hermes-dev"
export PATH="$VIRTUAL_ENV/bin:$PATH"

# Pull latest code
git pull origin main

# Reinstall (picks up new dependencies)
uv pip install -e ".[all]"

# Check for new config options
hermes config check
hermes config migrate   # Interactively add any missing options
```

### 回滚说明

如果更新引入了问题，可以回滚到之前的版本：

```bash
cd /path/to/hermes-agent

# List recent versions
git log --oneline -10

# Roll back to a specific commit
git checkout <commit-hash>
uv pip install -e ".[all]"

# Restart the gateway if running
hermes gateway restart
```

回滚到特定发布标签（替换为你之前使用的标签——例如某个较新的版本 `v2026.5.16`，或 `git tag --sort=-version:refname` 中的任意较早标签）：

```bash
git checkout vX.Y.Z
uv pip install -e ".[all]"
```

:::warning
如果新增了配置选项，回滚可能导致配置不兼容。回滚后运行 `hermes config check`，如果遇到错误，请从 `config.yaml` 中删除无法识别的选项。
:::

### Nix 用户注意事项

Nix 已不再是明确支持的安装路径（仅尽力而为）——参见 [Nix 安装](./nix-setup.md)。如果你通过 Nix flake 安装，更新由 Nix 包管理器负责：

```bash
# Update the flake input
nix flake update hermes-agent

# Or rebuild with the latest
nix profile upgrade hermes-agent
```

Nix 安装是不可变的 — 回滚由 Nix 的 generation 系统处理：

```bash
nix profile rollback
```

详情参见 [Nix 安装](./nix-setup.md)。

---

## 卸载

```bash
hermes uninstall
```

卸载程序会提供选项，让你保留配置文件（`~/.hermes/`）以便将来重新安装。

### 手动卸载

```bash
rm -f ~/.local/bin/hermes
rm -rf /path/to/hermes-agent
rm -rf ~/.hermes            # 可选 — 如计划重新安装则保留
```

:::info
如果你将 gateway 安装为系统服务，请先停止并禁用它：
```bash
hermes gateway stop
# Linux: systemctl --user disable hermes-gateway
# macOS: launchctl remove ai.hermes.gateway
```
:::