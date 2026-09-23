---
sidebar_position: 3
title: "更新与卸载"
description: "如何将 Hermes Agent 更新至最新版本或将其卸载"
---

# 更新与卸载

## 更新 {#updating}

使用单条命令更新至最新版本：

```bash
hermes update
```

此命令会从 `main` 拉取最新代码、更新依赖项，并提示你配置自上次更新以来新增的选项。

:::tip
`hermes update` 会自动检测新的配置选项并提示你添加。如果跳过了该提示，可手动运行 `hermes config check` 查看缺失的选项，再运行 `hermes config migrate` 以交互方式添加。
:::

### 被动更新提示 {#passive-update-notices}

固定版本或非交互式的安装可以禁用 CLI 的被动版本检查和横幅更新检查：

```bash
hermes config set updates.check false
```

这会同时抑制缓存的更新提示和被动的更新检查网络请求。默认值为 `true`。显式运行的 `hermes update --check` 和 `hermes update` 仍然有效；此设置不控制桌面应用的更新程序。

### 更新过程 {#what-happens-during-an-update}

运行 `hermes update` 时，将依次执行以下步骤：

1. **更新前快照** — 默认保存一份轻量级状态快照（涵盖配对数据、cron 任务、`config.yaml`、`.env`、`auth.json` 及其他运行时修改的状态文件；单个超过 1 GiB 的文件会被跳过，因此大型会话数据库不会拖慢更新）。由于代码替换和 gateway 重启会波及每一个 profile，安装中的**每个 profile** 都会拍摄同样的快照——各自存入自己的 `state-snapshots/` 目录——并且更新后的 cron 任务安全网会用每个 profile 自己的快照来检查它。由 `updates.pre_update_backup` 控制（默认 `quick`，`full` 为整个 `HERMES_HOME` 的 zip 备份，`off` 为禁用）。可通过 [快照与回滚](../user-guide/checkpoints-and-rollback.md) 中描述的快照恢复流程进行恢复。快速快照用于恢复丢失的文件，而不是代码回滚的保险——如需一致的时间点回滚，请使用 `--backup`（full 模式）。
2. **Git pull** — 从 `main` 分支拉取最新代码并更新子模块
3. **拉取后语法校验 + 自动回滚** — 拉取完成后，Hermes 会编译每次调用 `hermes` 时启动阶段都会导入的九个关键文件。若其中任何一个无法解析（例如残留的合并冲突标记、意外被截断的文件），Hermes 会运行 `git reset --hard <pre-pull-sha>` 将安装回滚，以保证你的 shell 仍可启动。等上游修复落地后再重新运行 `hermes update`。
4. **依赖安装** — 运行 `uv pip install -e ".[all]"` 以获取新增或变更的依赖项
5. **配置迁移** — 检测自当前版本以来新增的配置选项并提示设置
6. **桌面应用重建（暂存后替换）** — 如果 Hermes Desktop 应用是从此检出构建的，它会被重新构建，使 GUI 与新代码保持一致。重建会打包到 `apps/desktop/release/` 旁边的一个临时暂存目录中，校验暂存的应用，然后才将其重命名覆盖之前的构建。无论在哪个环节失败——Electron 下载损坏、缺少依赖、磁盘已满——之前的应用都保持原样且可以启动；更新会报告 `⚠ Update partially complete`，而 `hermes desktop` 会重试重建。
7. **Gateway 自动重启** — 更新完成后刷新正在运行的 gateway，使新代码立即生效。由服务管理的 gateway（Linux 上的 systemd、macOS 上的 launchd）通过服务管理器重启；手动启动的 gateway 在 Hermes 能将运行中的 PID 映射回某个 profile 时会自动重新启动。手动启动的 `hermes serve` / `hermes dashboard` 后端（例如为远程桌面提供服务、绑定网络的 serve）也以同样方式处理：每个后端在启动时都会把自己的绑定地址记录到安装的派生台账中，因此更新会在代码替换前停止它，并在之后以**相同的主机和端口**重新启动——指向该端点的远程桌面会重新连接，而不会被晾在一边。由正在运行的桌面应用所拥有的后端，则交给应用自己重新派生。

### Windows 更新程序文件缺失 {#missing-windows-updater-files}

如果维护中的更新脚本缺失（例如被杀毒软件隔离之后），旧版的更新转发器会直接失败，而不是报告交接成功。请修复安装，并在重试前查看安全软件的隔离报告；不要禁用杀毒保护。在报告成功之前，维护中的更新程序会检查 CLI 导入、Windows 可执行文件头、ASAR 头和打包后的主入口、带有本地模块入口的可读渲染器 HTML、初始模块文件以及当前构建戳。这些只是最低限度的产物检查，而不是完整的依赖审计，也不是应用/后端的启动测试。缺少 Python 会在等待桌面应用关闭之前就被报告；依赖修复仍然可以作为更新的一部分运行。当存在相应布局时，Electron 会在停止后端之前检查维护中交接流程的前置条件；真正的旧式扁平更新程序布局仍受支持，因此并不是每一个缺失的更新程序文件都会在后端关闭之前被检测到。

在 Windows 上，如果在打包期间桌面应用被重新打开，它会在暂存构建被提升之前再次被立即停止。这项清理仅限于该检出的桌面发布目录树中的可执行文件；不相关的安装不会被停止。如果仍有残留的文件锁，暂存提升仍会失败，而不会绕过重命名错误。

### 针对非默认分支更新：`--branch` {#updating-against-a-non-default-branch---branch}

默认情况下 `hermes update` 跟踪 `origin/main`。传入 `--branch <name>` 可针对其他分支更新——适用于 QA 通道、功能分支或候选发布版测试：

```bash
hermes update --branch release-candidate
hermes update --check --branch experimental   # preview behindness only
```

如果你的本地检出位于其他分支，Hermes 会自动 stash 未提交的工作，将 HEAD 切换到目标分支，然后再拉取。本地不存在的分支会自动从 `origin/<name>` 跟踪（`git checkout -B <name> origin/<name>`）。任何地方都不存在的分支会干净地失败——退出前会恢复你 stash 的改动，因此你绝不会被困在奇怪的状态里。仅适用于 `main` 的 fork 上游同步逻辑在非 `main` 分支上会自动跳过。

### 停留在功能分支上的检出 {#checkout-parked-on-a-feature-branch}

如果源码检出停留在某个功能分支上（由工具、worktree 实验或手动检出造成），只要工作树是干净的，`hermes update` 就会自动将其切换回更新目标：

- **分支已完全合并**（每个提交都已包含在 `origin/main` 中——`git cherry` 报告没有未合并的内容）：更新会如实说明——`Checkout was parked on '<branch>' (fully merged) — switched back to main`——并在之后保持在 `main` 上。
- **分支有未合并的提交**，但工作树是干净的：更新仍会切换到 `main` 以便继续进行——非交互式调用方（桌面应用的更新按钮、gateway 的 `/update`、cron）依赖的正是这一点，因为它们无法处理"跳过"的情况。你的提交不会受到影响：`git checkout` 永远不会丢弃已提交的工作，而更新会打印一条醒目的提示，写明分支名和提交数量，以及之后用于找回这些工作的 `git checkout <branch>` 命令。

如果你是*有意*运行一个自定义分支（在 main 之上维护本地补丁），请在 `config.yaml` 中设置 `updates.parked_branch_strategy: update_in_place`。这样更新会把 `origin/main` 合并**进**你的分支，而不是切换离开它——检出位置永远不动，你的提交得以保留，运行中的代码也会前进。能快进时就快进；出现分叉时，会在一个 `pre-update-<stamp>` 安全标签之后执行真正的合并，遇到冲突则干净地停止（不做任何改动）。`hermes update --switch-branch` 可在单次运行中改回切换路径——对于不能积累由更新产生的合并提交的深层功能分支很有用。

当停留的分支存在**未提交的改动**（工作树是脏的）时，Hermes **不会**去动它。代码更新会被标记为 **SKIPPED**，并给出醒目的警告，写明分支名、它落后 `origin/main` 多少，以及用于解决问题的确切命令——而不是假装更新成功了。完成行总会显示实际的分支和 HEAD（`✓ Update complete! [main @ 30fcf9580]`），让偏离一目了然。在 `config.yaml` 中设置 `updates.auto_switch_parked_branch: false` 可完全禁用自动切换（跳过警告仍会触发）。

### 非交互式更新中的本地改动 {#local-changes-on-non-interactive-updates}

当你在终端里运行 `hermes update` 时，Hermes 会 stash 源码树中所有未提交的改动，拉取，然后**询问**是否恢复它们——与一直以来的行为完全一致。交互式更新没有任何变化。

当更新在**没有终端**的情况下运行时——来自桌面/聊天应用的"更新"按钮，或由 gateway 触发的更新——没有提示可供回答。此时由 `updates.non_interactive_local_changes` 设置决定你 stash 的改动会怎样：

```yaml
# ~/.hermes/config.yaml
updates:
  non_interactive_local_changes: stash   # default: keep + auto-restore
  # non_interactive_local_changes: discard  # throw local source edits away
```

- `stash`（默认）— 自动 stash、拉取，然后把你的改动自动恢复到更新后的代码之上。不会丢失任何内容；若恢复时出现冲突，改动会保留在 git stash 中以便手动恢复。
- `discard` — 自动 stash 并在拉取后丢弃该 stash，使更新总是落在干净的工作树上。仅在你从不打算保留 Hermes 源码本地改动的机器上使用。它执行的是 stash drop（而非 `git reset --hard` + `git clean -fd`），因此 `node_modules`、`venv` 和构建产物等被忽略的路径绝不会被触碰。

在桌面应用中，该项位于 **Settings → Advanced → In-App Update Local Changes**。

**桌面应用的更新永远不会自动恢复改动。** 桌面更新程序调用的是 `hermes update --keep-stash`：本地源码改动仍会被 stash，以便更新得以进行，但之后**不会**被重新应用——它们会留在 `git stash` 中，更新日志会打印用于找回它们的确切 `git stash apply <ref>` 命令。这能防止本地改动在桌面更新之间悄悄地跟着走，进而破坏刚刚更新好的安装。（如果你选择了丢弃，`non_interactive_local_changes: discard` 仍然优先。）手动恢复被搁置的改动：

```bash
cd ~/.hermes/hermes-agent   # or your install root
git stash list --format='%gd %H %s'   # find the hermes-update-autostash entry
git stash apply stash@{0}
```

如果你希望在交互式运行中也获得同样的"永不重新应用"行为，也可以给终端里的 `hermes update` 传入 `--keep-stash`。

### 仅预览：`hermes update --check` {#preview-only-hermes-update---check}

想在拉取前确认是否有更新？运行 `hermes update --check` — 它会获取并与 `origin/main` 比较提交。不修改任何文件，不重启 gateway。适合在以"是否有更新"为条件的脚本和 cron 任务中使用。

### 集群预览：`hermes update --plan` {#fleet-preview-hermes-update---plan}

在更新一台运行着多个 profile 或服务的机器之前，`hermes update --plan` 会打印完整的更新计划，而不改动任何东西：安装类型（git 检出、Docker 镜像、由 Nix/apt 管理）、所有 profile 中每一个正在运行的 Hermes 服务及其监管方式（systemd、launchd、手动）和它实际正在提供的代码版本，以及每个服务将采用的重启机制。手动启动的 `hermes serve` / `hermes dashboard` 后端也会出现在其中（来自派生台账），附带其记录的绑定端点，以及"代码替换前停止，按记录的启动参数重新启动"的重启机制。在由镜像或包管理的安装上，计划会报告该安装无法原地更新，并给出正确的更新命令。它是只读的，在运行中的集群上也可以安全使用。

同样的清单会嵌入到每一次真实更新的回执中（`~/.hermes/logs/update_receipts/`），因此更新之后，你可以把更新程序看到的情况与它实际执行的操作进行对照。

### 更新回执与集群版本检查 {#update-receipts-and-the-fleet-version-check}

每次运行 `hermes update` 都会向 `~/.hermes/logs/update_receipts/` 写入一份机器可读的回执（保留最近 20 份，`latest.json` 始终指向最新的一份）：更新前的集群计划、执行的每一步、跳过了什么以及原因、gateway 重启结果，以及最终的集群版本矩阵。在重启阶段之后，更新程序会把每个在线 gateway 正在运行的代码与刚刚更新的检出进行比较，并按 profile 打印一个矩阵——仍在提供更新前代码的 gateway 会被醒目地报告，并附上确切的重启命令，更新也会以非零状态退出，这样自动化流程永远不会把一个混合版本的集群当作健康的。`--plan` 和集群检查在可用时都会通过本地控制套接字直接询问每个正在运行的 gateway（profile 数据目录中的 `gateway.sock`，Windows 上则是命名管道），因此版本和监管信息来自 gateway 本身；旧版本的 gateway 仍会像以前一样通过其状态文件被发现。

### 被中断的 gateway 重启 {#interrupted-gateway-restarts}

如果之前的某次更新拉取了代码但没有完成集群的重启，那么即使检出已经是最新的，
下一次 `hermes update` 也会重试。进程扫描结果为空并不能证明已经恢复：失败的 systemd
单元和已安装的 launchd 任务可能没有存活的 PID。如果监管方发现失败、某次重启失败，
或者某个被请求的服务无法被确认处于活跃状态，待重启标记就会被保留。更新会以非零状态
退出并报告受影响的服务；用打印出来的命令恢复它们，然后重试 `hermes update`。

一份失败的历史回执本身并不能证明 gateway 仍然过时。启动和 gateway 状态警告，以及更新时的补做流程，都会在处理仅来自回执的重启义务之前先检查在线集群。每个被记录的 gateway profile 都必须在当前检出上有一个存活的继任者；一个不相关的当前 gateway 不能顶替一个缺失的、已停止的、版本未知的或非 gateway 的运行时。因此，一次手动的 gateway 重启可以消除警告，而不会把一次失败的更新改写为成功。单独的待重启标记仍然具有权威性，因为它可能属于一次更新的、被中断的更新，而那次更新的清单从未写入回执。

### 完整更新前备份：`--backup` {#full-pre-update-backup---backup}

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

:::tip 其实是要迁移到新机器？
更新备份保护的是原地更新。如果你要把整套环境迁移到另一台硬件上，请改用 `hermes backup` + `hermes import`——参见[将 Hermes 导出到另一台机器](/reference/faq#exporting-hermes-to-another-machine)和 [`hermes backup` 与 `hermes profile export` 的区别](/reference/faq#hermes-backup-vs-hermes-profile-export)。
:::

### Windows：另一个 `hermes.exe` 正在运行 {#windows-another-hermesexe-is-running}

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

#### Windows 上的 venv 重建是事务性的 {#windows-venv-recreation-is-transactional}

当 Windows 安装程序必须重建现有的 `venv` 时，它会先把旧目录移动到一个唯一的 `venv.stale.*` 名称下，然后创建并校验替代品。只有在依赖安装完成、并且基线导入在新目录树中通过之后，旧目录树才会被删除——在此之前，它都是回滚的来源（记录在 `venv.pending-backup` 中）。

如果移动无法完成，安装程序会停止，并保持在用的 `venv` 不受影响。如果 `uv` 失败，或者报告成功却没有创建出解释器，任何部分完成的替代品都会被移动到 `venv.failed.*`，并恢复之前的 venv。这样可以让健康检查和阻断项检查在安装失败后依然可用。

当另一个进程仍持有文件句柄时，`venv.stale.*` 或 `venv.failed.*` 目录可能会残留下来。关闭正在使用该安装的 Hermes Desktop、gateway 和 Python 进程，然后重试安装/更新；在成功重建之后，这些被搁置的目录会被尽力清理。

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

### 更新后建议的验证步骤 {#recommended-post-update-validation}

`hermes update` 处理主要的更新流程，但快速验证可确认一切正常落地：

1. `git status --short` — 若工作树出现意外的脏状态，请在继续前检查
2. `hermes doctor` — 检查配置、依赖项和服务健康状态
3. `hermes --version` — 确认版本已按预期更新
4. 如果使用 gateway：`hermes gateway status`
5. 检查 Node.js 依赖是否存在漏洞：`hermes doctor --audit`（默认关闭——每棵依赖树的审计需要一到两分钟）。若报告有问题，请在标记的目录中运行 `npm audit fix`

:::warning 更新后工作树出现脏状态
如果 `hermes update` 后 `git status --short` 显示意外变更，请在继续前停下来检查。这通常意味着本地修改被重新应用到了更新后的代码之上，或依赖步骤刷新了锁文件。
:::

### 终端在更新中途断开连接 {#if-your-terminal-disconnects-mid-update}

`hermes update` 针对意外终端断开进行了保护：

- 更新会忽略 `SIGHUP`，因此关闭 SSH 会话或终端窗口不再会在安装中途终止它。`pip` 和 `git` 子进程继承此保护，因此 Python 环境不会因连接断开而处于半安装状态。
- 更新运行期间，所有输出会同步镜像到 `~/.hermes/logs/update.log`。如果终端消失，重新连接后检查日志，确认更新是否完成以及 gateway 重启是否成功：

```bash
tail -f ~/.hermes/logs/update.log
```

- `Ctrl-C`（SIGINT）和系统关机（SIGTERM）仍会被响应 — 这些是主动取消操作，而非意外中断。

你不再需要将 `hermes update` 包裹在 `screen` 或 `tmux` 中来应对终端断开。

### 查看当前版本 {#checking-your-current-version}

```bash
hermes --version
```

与 [GitHub releases 页面](https://github.com/NousResearch/hermes-agent/releases) 上的最新版本进行比较。

### 从消息平台更新 {#updating-from-messaging-platforms}

你也可以直接从 Telegram、Discord、Slack、WhatsApp 或 Teams 发送以下命令进行更新：

```
/update
```

此命令会拉取最新代码、更新依赖项并重启正在运行的 gateway。Bot 在重启期间会短暂下线（通常为 5–15 秒），之后恢复服务。

### 手动更新 {#manual-update}

如果你是手动安装的（未使用快速安装脚本）：

```bash
cd /path/to/hermes-agent
# Activate the venv you created during install (outside the source tree)
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

### 回滚说明 {#rollback-instructions}

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

### 由镜像管理的安装（Docker）：来源标记 {#image-managed-installs-docker-the-provenance-marker}

发布的 Docker 镜像中内置了一个小型只读标记（`/etc/hermes/image-provenance.json`），用于权威地标识该文件系统是由镜像管理的。`hermes update`、`hermes update --check` 以及仪表盘的"更新"按钮在改动任何东西之前都会先查阅它：在由镜像管理的安装上，它们会干净地拒绝执行（退出码 2），打印出真正的更新命令（`docker pull nousresearch/hermes-agent:latest`），并写入一份 `refused` 回执，让集群工具能看到曾有过这次尝试。即使源码检出被 bind-mount 进容器，这个标记也依然优先——拒绝的依据是运行中的文件系统*是*什么，而不是它看起来像什么。损坏的标记同样会拒绝（失败即关闭）。由 Nix 和 apt 管理的安装则通过同一道关卡、使用现有的检测机制来拒绝。

### Nix 用户注意事项 {#note-for-nix-users}

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

## 卸载 {#uninstalling}

```bash
hermes uninstall
```

卸载程序会提供选项，让你保留配置文件（`~/.hermes/`）以便将来重新安装。

:::tip 是要迁移到新机器，而不是离开？
在删除任何东西之前，先把你的环境带走：`hermes backup` 会捕获包括凭据在内的整个 `~/.hermes` 目录，而 `hermes profile export` 只打包单个 profile，并且在设计上排除了凭据（因此单靠一次导出并不是完整备份）。参见 [`hermes backup` 与 `hermes profile export` 的区别](/reference/faq#hermes-backup-vs-hermes-profile-export)。
:::

### 手动卸载 {#manual-uninstall}

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
