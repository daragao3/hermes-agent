---
sidebar_position: 4
---

# 同时运行多个 Gateway

在同一台机器上以受管服务的形式运行多个 [profile](./profiles.md) —— 每个 profile
拥有自己的 bot token、session 和记忆。本页介绍相关的运维事项：一次性启动
全部实例、跨 profile 查看日志、防止主机休眠，以及从常见的
launchd/systemd 怪异行为中恢复。

如果你只运行一个 Hermes agent，则不需要本页 —— 基础内容参见
[Profiles](./profiles.md)。

## 何时需要这套方案

当你有两个或更多 Hermes agent 需要同时在线时，就需要这套配置。
常见原因：

- 一个 Telegram bot 上跑私人助理，另一个上跑编码 agent
- 每位家庭成员一个 agent，或每个 Slack 工作区一个 agent
- 同一份配置的沙箱实例 + 生产实例
- 一个研究 agent + 一个写作 agent + 一个由 cron 驱动的 bot —— 各自拥有隔离的
  记忆和技能

每个 profile 本来就会获得自己的按平台划分的 LaunchAgent
（`ai.hermes.gateway-<name>.plist`）或 systemd 用户服务
（`hermes-gateway-<name>.service`）。本指南补充的是集中管理它们的模式。

## 快速上手

```bash
# 创建 profile（只需一次）
hermes profile create coder
hermes profile create personal-bot
hermes profile create research

# 分别配置
coder setup
personal-bot setup
research setup

# 将每个 gateway 安装为受管服务
coder gateway install
personal-bot gateway install
research gateway install

# 全部启动
coder gateway start
personal-bot gateway start
research gateway start
```

就这样 —— 三个独立的 agent，各自运行在自己的进程中，崩溃时和用户登录时
都会自动重启。

## 备选方案：所有 profile 共用一个 gateway（多路复用）

上面的模型是**每个 profile 一个进程**。这是默认方式，对大多数配置来说
也是正确的选择。但在拥有大量 profile 的主机上 —— 或者在每个 profile 一个进程
显得运维负担过重的容器部署中 —— 你也可以改为运行**单个多路复用 gateway**：
默认 profile 的 gateway 成为唯一的入站进程，为这台机器上的*每一个* profile
提供消息服务。

该功能**需要显式开启**，且**默认关闭**。关闭时，本页的其他内容
不受任何影响 —— 下文的所有行为都处于失效状态。

### 何时更适合使用多路复用

- 在容器/VPS 部署中，N 个 supervisor 单元、N 个端口和 N 个 PID 文件
  是一种负担。
- 有很多低流量 profile，不值得各自占用一个完整进程。
- 你希望只有一个东西需要启动、监控和重启。

如果你需要 profile 之间硬性的进程级隔离（独立的内存占用、互不影响的崩溃域、
能够重启某一个 profile 而不影响其他 profile），请继续使用每个 profile
一个进程的方式。

### 如何开启

在**默认 profile** 上设置该开关（多路复用器归它所有），然后重启
它的 gateway：

```bash
hermes config set gateway.multiplex_profiles true
hermes gateway restart
```

等价地，在默认 profile 的 `~/.hermes/config.yaml` 中：

```yaml
gateway:
  multiplex_profiles: true
```

（为方便起见，该开关也接受顶层的 `multiplex_profiles: true` 写法。）下次启动时，
默认 gateway 会枚举每一个 profile，使用各 profile 自己的凭据启动其已启用的
平台，并把每条入站消息路由到它所属的 profile。每一轮对话都会解析所路由 profile
的配置、技能、记忆、SOUL **以及 provider 密钥** —— 凭据绝不会跨 profile 共享。

对于次级 profile，你**不需要**运行 `hermes gateway start` —— 默认 gateway
会为它们提供服务。相关契约变化见下文。

### 开启多路复用后会发生什么变化

启用该开关会改变少数几项行为。关闭开关后，这些变化会立即全部回退。

#### 1. 次级 profile 不得启动自己的 gateway

在多路复用器运行时，对具名 profile 执行 `hermes gateway start` / `run` 会是
一个**硬性错误**，并把你指回多路复用器：

```
The default gateway is running as a profile multiplexer and already serves
profile 'coder'. ...
```

多路复用器是唯一的入站进程；第二个 profile gateway 会对该 profile 的平台
造成重复绑定。只有当你确实想为该 profile 单独开一个进程时才传 `--force`
（不建议在多路复用器运行期间这么做）。因此本页前面提到的跨 profile 生命周期
封装脚本在多路复用模式下**不**适用 —— 你只需管理默认 gateway。

#### 2. HTTP 入站平台通过 `/p/<profile>/` URL 前缀访问

次级 profile 的 Webhook（以及其他 HTTP 入站）流量会带着 profile 前缀
抵达默认监听器，而**不是**第二个端口：

```
# default profile
POST http://host:8644/webhooks/<route>
# the "coder" profile, same listener
POST http://host:8644/p/coder/webhooks/<route>
```

前缀中出现未知或未配置的 profile 会返回 `404`。由于这一个共享监听器已经以
这种方式服务于所有 profile，**次级 profile 不得自行启用绑定端口的平台** ——
这么做属于配置错误，会导致整个次级 profile 被跳过，而默认 profile 和其他
健康的 profile 继续运行。警告信息会指出被跳过的 profile 及每一个冲突的
平台：

```
Skipping secondary profile 'coder' due to port-binding config error: Profile
'coder' enables port-binding platform(s) webhook, but gateway.multiplex_profiles
is on. ... Remove these platform entries from profile 'coder's config.yaml or
configure them only on the default profile.
```

受此规则约束的绑定端口平台有：`webhook`、`api_server`、
`msgraph_webhook`、`feishu`、`wecom_callback`、`bluebubbles`、`sms`、
`whatsapp_cloud`、`line`。请**只在默认 profile 上**配置这些平台；
每个 profile 都可以通过它的 `/p/<profile>/` 前缀访问。

只有这种共享监听器冲突才会降级为跳过某个 profile。安全相关的配置错误
仍然是致命的：例如，一个自有策略为 `open` 的平台若没有设置
`GATEWAY_ALLOW_ALL_USERS` 或其平台专属的 allow-all 开关，依然会中止 gateway
启动，而不是静默丢弃这个不安全的 profile。

#### 3. 按凭据划分的平台仍需为每个 profile 配置各自的 token

轮询/长连接类平台（Telegram、Discord、Slack、Matrix、Signal 等）在多路复用下
可以正常工作，但每个启用它们的 profile 都必须提供**自己的** bot
token —— 同一个 token 不能被两个 profile 同时轮询。如果两个 profile
配置了相同的 `(platform, token)`，启动会快速失败并指出这两个 profile
（参见 [Token 冲突防护](#token-conflict-safety) —— 规则未变，
只是现在改为在同一个进程内强制执行）。

#### 4. Session 键按 profile 命名空间隔离

每个 profile 的 session 都位于 `agent:<profile>:…` 命名空间下，因此同一
平台/聊天中的两个 profile 在共享 session 存储中绝不会冲突。
**默认** profile 逐字节保留历史上的 `agent:main:…` 命名空间，因此已有的
默认 profile session 不受影响 —— 无需迁移，也不会产生孤立历史。

#### 5. 只有一个 PID/锁和一个状态面

只存在一个进程级的 PID 和锁（即多路复用器，位于默认 home 之下）。
`hermes status` 会报告多路复用器及其服务的 profile；
`hermes status -p <name>` 则只查看某一个 profile。每个 profile 仍会在自己的
home 下写出各自的 `runtime_status.json`，因此现有的按 profile 读取的程序
仍可正常工作。

#### 有哪些**不会**改变

按 profile 的 `.env` 凭据隔离得以保留，甚至更为严格：一个 profile 的密钥
只从它自己的作用域解析，绝不会被合并进共享环境（这也意味着 MCP server、
Kanban worker 等子进程只能看到自己所属 profile 的密钥）。Kanban、
按 profile 划分的技能/记忆/SOUL 以及模型路由，其行为与使用独立 gateway 时
完全一致。

### 将共享 bot 的会话路由到 profile（`profile_routes`）

多路复用按**凭据**（每个 profile 自己的 bot token）或按 **URL 前缀**
（HTTP 平台的 `/p/<profile>/`）来选择 profile。当多个社区共用**同一个** bot
token 时 —— 例如一个 Discord bot 服务多个服务器 —— 你还可以用
`gateway.profile_routes` 把特定的服务器/频道/话题路由到不同的 profile：

```yaml
gateway:
  multiplex_profiles: true
  profile_routes:
    # 整个 Discord 服务器 → 一个 profile
    - name: acme-server
      platform: discord
      guild_id: "1234567890"
      profile: acme

    # 该服务器中的某一个频道 → 另一个 profile
    - name: acme-support
      platform: discord
      guild_id: "1234567890"
      chat_id: "9876543210"
      profile: acme-support

    # 一个 Telegram 群组（没有服务器概念 —— 只有 chat_id）
    - name: tg-group
      platform: telegram
      chat_id: "-1001234567890"
      profile: tg-profile
```

路由按最具体优先的顺序匹配（`thread_id` > `chat_id` > `guild_id`），
所有声明的字段都必须满足（AND 关系），并且以频道为键的路由也会匹配
父级为该频道的话题/论坛帖。未匹配到任何路由的消息仍留在默认/当前 profile。
被路由到的 profile 会获得上文描述的完整按 profile 隔离（配置、技能、记忆、
凭据、session 命名空间）。路由适用于所有平台适配器，不只是 Discord。

`profile_routes` 需要 `gateway.multiplex_profiles: true`；关闭多路复用时
这些路由会被忽略。如果某条路由指向磁盘上不存在的 profile，gateway 会记录
一条警告，指出该 profile 及其来源，并回退到默认 home。

## 一次性启动、停止或重启所有 gateway

CLI 自带的是单 profile 的生命周期命令。若要对每个 profile 都执行操作，
可以用 shell 循环把它们包起来。把下面的脚本放到
`~/.local/bin/hermes-gateways` 并对其执行 `chmod +x`：

```sh
#!/bin/sh
set -eu

# 随着你创建 / 删除 profile，在这里增删 profile 名称。
profiles="default coder personal-bot research"

usage() {
  echo "Usage: hermes-gateways {start|stop|restart|status|list}"
}

run_for_profile() {
  profile="$1"
  action="$2"
  if [ "$profile" = "default" ]; then
    hermes gateway "$action"
  else
    hermes -p "$profile" gateway "$action"
  fi
}

action="${1:-}"
case "$action" in
  start|stop|restart|status)
    for profile in $profiles; do
      echo "==> $action $profile"
      run_for_profile "$profile" "$action"
    done
    ;;
  list)
    hermes gateway list
    ;;
  *)
    usage
    exit 2
    ;;
esac
```

然后：

```bash
hermes-gateways start      # 启动每个已配置的 profile
hermes-gateways stop       # 停止每个已配置的 profile
hermes-gateways restart    # 全部重启
hermes-gateways status     # 查看全部状态
hermes-gateways list       # 委托给 `hermes gateway list`
```

:::tip
`default` profile 用 `hermes gateway <action>`（不带 `-p`）来操作，
而不是 `hermes -p default gateway <action>`。上面的封装脚本两种写法都能处理。
:::

## 管理单个 profile

每个 profile 都会安装以下快捷命令：

```bash
coder gateway run        # 前台运行（Ctrl-C 停止）
coder gateway start      # 启动受管服务
coder gateway stop       # 停止受管服务
coder gateway restart    # 重启
coder gateway status     # 查看状态
coder gateway install    # 创建 LaunchAgent / systemd 单元
coder gateway uninstall  # 删除服务文件
```

它们等价于 `hermes -p coder gateway <action>` —— 当 profile 别名不在 `PATH`
中，或者你要在脚本中动态指定 profile 时，这一点很有用。

## 服务文件

每个 profile 都会以唯一名称安装自己的服务，因此安装之间
永远不会冲突：

| 平台     | 路径                                                              |
| -------- | ----------------------------------------------------------------- |
| macOS    | `~/Library/LaunchAgents/ai.hermes.gateway-<profile>.plist`        |
| Linux    | `~/.config/systemd/user/hermes-gateway-<profile>.service`         |

默认 profile 沿用历史名称：`ai.hermes.gateway.plist` /
`hermes-gateway.service`。

## 查看日志

每个 profile 都写入自己的日志文件：

```bash
# 默认 profile
tail -f ~/.hermes/logs/gateway.log
tail -f ~/.hermes/logs/gateway.error.log

# 具名 profile
tail -f ~/.hermes/profiles/<name>/logs/gateway.log
tail -f ~/.hermes/profiles/<name>/logs/gateway.error.log
```

同时跟踪所有 profile 的日志：

```bash
tail -f ~/.hermes/logs/gateway.log ~/.hermes/profiles/*/logs/gateway.log
```

CLI 也提供了结构化日志查看器：

```bash
hermes logs -f                  # 跟踪默认 profile
hermes -p coder logs -f         # 跟踪某一个 profile
hermes logs --help              # 过滤器、级别、JSON 输出
```

## 确认实际在运行的内容

```bash
hermes profile list             # profile + 模型 + gateway 状态
hermes-gateways status          # 所有 profile 的完整状态
launchctl list | grep hermes    # macOS —— PID 和标签
systemctl --user list-units 'hermes-gateway-*'   # Linux —— 单元
```

## 编辑配置

每个 profile 都把配置保存在自己的目录中：

```
~/.hermes/profiles/<name>/
├── .env              # API 密钥、bot token（chmod 600）
├── config.yaml       # 模型、provider、工具集、gateway 设置
└── SOUL.md           # 人格 / 系统提示词
```

默认 profile 直接使用 `~/.hermes/`，包含同样这三个文件。

你可以用任意编辑器编辑它们，或通过 CLI：

```bash
hermes config set model.model anthropic/claude-sonnet-4    # 默认 profile
coder config set model.model openai/gpt-5                  # 具名 profile
```

编辑 `.env` 或 `config.yaml` 之后，请重启受影响的 gateway：

```bash
coder gateway restart
# 或者，重启全部：
hermes-gateways restart
```

## 让主机保持唤醒

gateway 进程可以整天运行，但操作系统在空闲时仍会尝试休眠。
有两种做法：

### macOS —— `caffeinate`

`caffeinate` 是 macOS 内置的工具，运行期间可阻止休眠。无需安装。

```bash
caffeinate -dis                    # 阻止显示器休眠、空闲休眠和系统休眠
caffeinate -dis -t 28800           # 同上，8 小时后自动退出
caffeinate -i -w $(cat ~/.hermes/gateway.pid) &   # 默认 gateway 运行期间保持唤醒

# 持久化：后台运行后即可不再理会
nohup caffeinate -dis >/dev/null 2>&1 &
disown

# 查看 / 停止
pmset -g assertions | grep -iE 'caffeinate|prevent|user is active'
pkill caffeinate
```

| 参数   | 作用                                              |
| ------ | ------------------------------------------------- |
| `-d`   | 阻止显示器休眠                                    |
| `-i`   | 阻止系统空闲休眠（默认）                          |
| `-m`   | 阻止磁盘休眠                                      |
| `-s`   | 阻止系统休眠（仅限接电源的 Mac）                  |
| `-u`   | 模拟用户活动（防止锁屏）                          |
| `-t N` | `N` 秒后自动退出                                  |
| `-w P` | 当 PID `P` 退出时退出                             |

:::warning 合盖仍会让 Mac 休眠
`caffeinate` 无法覆盖 MacBook 上由硬件驱动的合盖休眠。
若需合盖运行，请修改你的“节能”/“电池”偏好设置，或
使用第三方工具。
:::

### Linux —— `systemd-inhibit` 或 `loginctl`

```bash
# 在某个命令运行期间抑制挂起
systemd-inhibit --what=idle:sleep --who=hermes --why="gateways running" \
  sleep infinity &

# 允许用户服务在注销后继续运行（推荐）
sudo loginctl enable-linger "$USER"
```

启用 lingering 后，你的 systemd 用户单元（包括
`hermes-gateway-<profile>.service`）会在 SSH 断开和重启之后继续运行。

## Token 冲突防护 {#token-conflict-safety}

每个 profile 在每个平台上都必须使用唯一的 bot token。如果两个 profile
共用同一个 Telegram、Discord、Slack、WhatsApp 或 Signal token，第二个
gateway 会拒绝启动，并报出指明冲突 profile 的错误。

审计方法：

```bash
grep -H 'TELEGRAM_BOT_TOKEN\|DISCORD_BOT_TOKEN' \
     ~/.hermes/.env ~/.hermes/profiles/*/.env
```

## 更新代码

`hermes update` 会拉取一次最新代码，并把新的内置技能同步到
每一个 profile：

```bash
hermes update
hermes-gateways restart
```

用户修改过的技能绝不会被覆盖。

## 故障排查

### “Could not find service in domain for user gui: 501”

你在此前执行过 `hermes gateway stop` 之后又运行了 `hermes gateway start`。
CLI 的 `stop` 会执行完整的 `launchctl unload`，这会把服务从 launchd 的注册表
中移除。CLI 在 `start` 时会捕获这个特定错误并自动重新加载 plist
（`↻ launchd job was unloaded; reloading service definition`）。服务会正常启动。
无需修复。

### 崩溃后残留的 PID

如果某个 profile 的 gateway 显示 `not running`，但仍有进程存活：

```bash
ps -ef | grep "hermes_cli.*-p <profile>"
cat ~/.hermes/profiles/<profile>/gateway.pid
kill -TERM <pid>          # 优雅退出
kill -KILL <pid>          # 若数秒后仍未退出
<profile> gateway start
```

### 强制硬重置某个服务

```bash
# macOS
launchctl unload ~/Library/LaunchAgents/ai.hermes.gateway-<profile>.plist
launchctl load   ~/Library/LaunchAgents/ai.hermes.gateway-<profile>.plist

# Linux
systemctl --user restart hermes-gateway-<profile>.service
```

### 健康检查

```bash
hermes doctor                  # 默认 profile
hermes -p <profile> doctor     # 单个 profile
```
