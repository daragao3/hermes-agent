---
sidebar_position: 3
title: "桌面应用"
description: "原生的 Hermes 桌面应用 —— 与 Hermes 对话的精致体验，支持流式工具输出、并排预览、文件浏览器、语音、cron、profile、skills 和设置。支持 macOS、Windows 和 Linux。"
---

# 桌面应用

Hermes 桌面应用是一个原生应用，围绕**同一个** agent 构建 —— 与你在 CLI 和 gateway 中用到的完全一致：同样的配置、同样的 API 密钥、同样的会话、同样的 skills、同样的记忆。它不是一个独立产品，也不是轻量克隆版；它使用同一套 Hermes Agent 内核和设置，并通过一个现代、经过精心设计的 UI 来驱动它。如果你在终端里用过 `hermes`，你在那里配置的一切在这里已经就绪，你在这里做的任何事也会体现在那边。

它可运行在 **macOS、Windows 和 Linux** 上。

:::tip 各个界面分别是什么？
Hermes 有若干个前端，它们都连接到同一个 agent：

- **桌面应用**（本页）—— 一个原生应用，拥有为聊天、配置和管理量身打造的 UI。
- **CLI**（`hermes`）和 **[TUI](./tui.md)**（`hermes --tui`）—— 终端界面。
- **[Web Dashboard](./features/web-dashboard.md)**（`hermes dashboard`）—— 浏览器管理面板；其可选的 **Chat** 标签页通过伪终端嵌入 TUI。

按当下的需要挑一个用即可。它们共享状态，所以你可以在一个里开始会话，再到另一个里继续。
:::

## 安装

请参照 [Hermes Desktop 的安装说明](../getting-started/installation.md)。

如果你已经安装了 Hermes，直接运行

```bash
hermes desktop
```

它会使用你当前的配置、密钥、会话和 skills。

## 应用里有什么

桌面应用以聊天为核心组织窗口，左侧有一条导航侧边栏。它的设计目标是同时管理多个 agent 对话、配置消息提供方、创建 artifact、浏览项目的目录结构，以及同时推进多个项目。

### 聊天

应用的核心。你会得到：

- **流式响应**，在 agent 工作时实时显示工具活动和结构化的工具调用摘要。
- **与其他所有 Hermes 界面相同的对话历史** —— 在这里开始的会话可以在 CLI/TUI 中继续，反之亦然。
- **拖放文件** 到聊天区域的任意位置，把它们附加到你的下一条消息。
- **右侧预览栏** —— 在继续聊天的同时并排渲染网页、文件和工具输出。
- **输入框历史与队列编辑** —— 在空的输入框中按上/下方向键可调出并复用之前的提示词，也可以在排队的消息发送前编辑它们。

#### 状态栏

聊天底部的状态栏显示实时的会话状态，并提供无需打开设置就能使用的快捷控件：

- **按会话切换 YOLO** —— 只针对当前会话开启或关闭 YOLO（与 TUI 一致）。YOLO 会绕过危险命令的审批提示，所以要清楚你关掉的是什么 —— 参见 [安全 → YOLO 模式](./security.md#yolo-mode)。

想连接到另一台机器上的 Hermes 实例，而不是内置的本地后端？请看下方的[连接到远程后端](#connecting-to-a-remote-backend) —— 若要完整了解远程托管的 dashboard 连接是如何工作的（认证关卡、`/api/ws` 聊天套接字，以及 WebSocket 关闭码的排查），参见 [Web Dashboard → 将 Hermes Desktop 连接到远程后端](./features/web-dashboard.md#connecting-hermes-desktop-to-a-remote-backend)。

#### 选择模型

模型选择器位于**输入框**中，就在麦克风左侧。点击它即可在同一个下拉菜单里切换模型、推理强度和快速模式。

- **输入框里的选择器是黏性的 UI 状态，永远不会改动你的默认值。** 它保存在本地（按设备），并会**跟随**到新的聊天和重启之后，而不是回退到默认值 —— 选一次模型，下一次 `Cmd/Ctrl+N` 就以它开启。在有活跃聊天时切换模型，改动的范围仅限于**当前这个聊天**；无论哪种情况，选择都会在会话创建/切换时一并带上，并且**绝不会**写入 profile 的默认值。（切换 [profile](#sessions--profiles) 会重新以该 profile 自己的默认值为准。）
- **在 设置 → 模型 中设置默认值。** 那个"主"模型是你的**按 profile 的全局默认值** —— 新的聊天、cron、子 agent 和辅助任务都以它为起点，而且只有这里会写入它。每个 [profile](#sessions--profiles) 都保有自己的默认值。
- **每个模型各自的推理强度 / 快速模式预设。** 在桌面应用中，每个模型都会记住自己的推理强度和快速模式选择，在你选中该模型时重新应用到会话上。这些预设只是桌面端的便利功能，不会影响 cron 或子 agent。
- **聊天中途切换模型会重置提示词缓存。** 在活跃聊天里切换模型意味着下一条消息会以完整输入价格重新读取整段对话（提供方的提示词缓存是按模型绑定的）。偶尔切换没问题；但在长对话里，用新模型开一个新聊天往往比来回切换更省钱。

### 文件浏览器

无需离开应用即可浏览和预览工作目录 —— 在 agent 读取、写入和编辑文件时跟进很有用。用 `hermes desktop --cwd <path>`（或环境变量 `HERMES_DESKTOP_CWD`）设置初始项目目录。

### 语音

与 Hermes 对话并听它回答，与别处提供的[语音模式](./features/voice-mode.md)相同。在 macOS 上，系统会提示一次麦克风权限。

### 设置与初次引导

在真正的图形界面里管理提供方、模型、工具和凭据，而不用编辑 YAML。首次运行的引导流程能让你在几秒内发出第一条消息。设置面板覆盖提供方/密钥、模型选择、工具集配置、MCP 服务器、gateway 和会话管理。

- **提供方设置面板** —— 一个专门管理推理提供方的位置，提供账户 / API 密钥的交互界面，用于登录并按提供方存储凭据。
- **菜单里包含每一个提供方和模型** —— GUI 会展示完整的提供方列表以及 `hermes model` 知道的每一个模型，因此你选择的范围与 CLI 看到的目录一致，而不是一个精选子集。
- **xAI Grok OAuth** —— Grok 在启动器中是一等的 OAuth 提供方；像其他 OAuth 提供方一样通过浏览器流程登录。
- **在 GUI 中安装工具后端** —— 直接在应用里执行某个工具后端的安装后置步骤，无需切到终端。
- **辅助模型警告** —— 如果你把主模型切换到新的提供方，而辅助任务（标题生成、摘要及类似的辅助工作）仍固定在另一个提供方上，应用会给出警告，避免你在不知情的情况下把工作分散到两个提供方。

首次运行的引导流程已在统一的浮层设计体系上重新设计，你也可以选择**稍后选择提供方**，先跳过提供方设置进入应用。

### 管理面板

应用同样呈现了更广泛的 Hermes 管理能力，让你不必切到终端：

- **Skills** —— 浏览、安装和管理 [skills](./features/skills.md)。
- **Cron** —— 查看和管理[定时任务](../reference/cli-commands.md#hermes-cron)。
- **Profiles** —— 在 [Hermes profile](./profiles.md) 之间切换（隔离的配置/skills/会话）。
- **Messaging** —— 配置 gateway 频道。
- **Agents** 和 **Command Center** —— 面向多 agent 协作的编排界面。

### 键盘与导航

- **命令面板** —— 按 **Cmd+K**（Windows/Linux 上为 Ctrl+K）跳转到各项操作，用键盘在应用中导航。
- **可重绑定的快捷键** —— 设置中的快捷键面板允许你把应用的键盘快捷键改成自己习惯的按键。
- **自定义缩放快捷键** —— 以半步为增量缩放界面，更精细地控制文字大小。
- **界面语言切换器** —— 在应用内更改界面语言，包括简体中文（zh-Hans）。

### 会话与 profile {#sessions--profiles}

- **会话列表大改** —— 重做后的会话列表支持归档以及一般性的会话整理，让列表在增长时依然可控。
- **按 id 搜索会话** —— 直接通过 id 找到某个特定会话。
- **跨 profile 的并发会话** —— 同时在多个 [profile](./profiles.md) 下运行会话，并用跨 profile 的 `@session` 链接引用另一个 profile 中的会话。

## 更新

应用会在后台检查更新，并在有可用更新时提供一键更新。

[手动更新流程](https://hermes-agent.nousresearch.com/docs/getting-started/updating)同样适用于 GUI。

## 卸载

打开 **设置 → 关于 → 危险区域**，选择要移除的范围：

- **仅卸载 Chat GUI** —— 移除桌面应用及其数据；Hermes agent、你的配置和聊天记录都会保留。（等同于 `hermes uninstall --gui`。）
- **卸载 GUI + agent，保留我的数据** —— 移除应用和 agent，但保留配置、聊天记录和密钥，方便日后重装。（等同于 `hermes uninstall`。）
- **全部卸载** —— 移除应用、agent 以及所有用户数据。（等同于 `hermes uninstall --full`。）

应用会关闭以完成清理（清理在它退出之后执行，这样才能移除正在运行的应用包及其自己的 venv）。当本机没有安装 agent 时（例如一个连接远程后端的纯 GUI"精简"客户端），移除 agent 的选项会自动隐藏。

你也可以在终端里做同样的事 —— `hermes uninstall --gui` 只卸载 GUI，`hermes uninstall` / `hermes uninstall --full` 则连 agent 一起卸载。

:::note
在**源码检出目录**（一个 `hermes desktop` 开发构建）中运行 `hermes uninstall --gui` 时，还会移除工作区的 `node_modules` 和 `apps/desktop/{dist,release}` 构建产物，因为它们属于 GUI 构建产物。它们可以通过 `hermes desktop`（或 `npm install` + 重新构建）恢复 —— 但如果你正在积极开发桌面应用，那就要做好之后重新安装依赖的准备。
:::

## CLI 参考：`hermes desktop`

要通过 CLI 启动，直接运行 `hermes desktop` 即可。默认情况下它会安装工作区的 Node 依赖、为当前操作系统构建未打包的 Electron 应用，然后启动这个打包产物。

| 参数                 | 说明                                                                                      |
| -------------------- | ----------------------------------------------------------------------------------------- |
| `--skip-build`       | 跳过 npm 安装/打包，直接从 `apps/desktop/release` 启动已有的未打包应用 |
| `--force-build`      | 即使内容戳匹配也强制完整重新构建                                    |
| `--build-only`       | 构建桌面应用但不启动它（供 `hermes update` 使用）                      |
| `--source`           | 通过 `electron .` 针对 `apps/desktop/dist` 启动，而不是启动打包后的应用           |
| `--cwd PATH`         | 桌面聊天会话的初始项目目录（设置 `HERMES_DESKTOP_CWD`）           |
| `--hermes-root PATH` | 覆盖应用所使用的 Hermes 源码根目录（设置 `HERMES_DESKTOP_HERMES_ROOT`）          |
| `--ignore-existing`  | 在后端解析过程中强制应用忽略 `PATH` 上已有的任何 `hermes` CLI      |
| `--fake-boot`        | 启用确定性的启动延迟，用于验证启动界面                            |

## 工作原理

打包后的应用附带 Electron 外壳和一个原生 React 聊天界面。首次启动时，它可以把 Hermes Agent 运行时安装到 `HERMES_HOME`（`~/.hermes`，Windows 上为 `%LOCALAPPDATA%\hermes`）—— **与 CLI 安装使用完全相同的目录布局**，这正是二者可以互换的原因。后端解析首先遵循 `HERMES_DESKTOP_HERMES_ROOT`，其次是已完成的托管安装，然后是在 `PATH` 上探测到的 `hermes`（除非设置了 `--ignore-existing` / `HERMES_DESKTOP_IGNORE_EXISTING=1`），最后是面向 Nix 之类打包方的显式 `HERMES_DESKTOP_HERMES` 命令覆盖。React 渲染进程与应用为你启动的无头后端通信 —— 一个提供 `tui_gateway` JSON-RPC/WebSocket API 的 `hermes serve` 进程 —— 并复用 agent 运行时，而不是内嵌 `hermes --tui`。桌面应用是**自包含**的：它运行自己的 `hermes serve` 后端，从不打开也不依赖 [web dashboard](./features/web-dashboard.md)。（比 `serve` 命令更旧的运行时会自动回退到无头的 `dashboard --no-open`，因此应用更新永远不会跑到后端前面。）安装、后端解析和自更新逻辑都位于 Electron 主进程中。

## 连接到远程后端 {#connecting-to-a-remote-backend}

默认情况下，应用会启动并管理自己的**本地**后端。你也可以让它指向运行在另一台机器上的 Hermes 后端 —— 一台 VPS、一台家用服务器，或是一台藏在 Tailscale 后面的 Mini。

:::info 远程后端是一个正在运行的 `hermes serve` 进程
"远程后端"指的是运行在远程机器上的 **`hermes serve`** 服务 —— 那才是桌面应用要连接的进程。本节的一切都建立在该后端确实处于运行且可达的前提上。桌面应用不会替你启动它；需要由你（或一个 `systemd` 服务）让 `hermes serve` 在远程主机上持续运行，应用再连上去。如果你同时还使用消息频道（Telegram、Discord 等），**gateway** 是一个*独立*的长期运行进程，需要你单独启动 —— 参见设置步骤之后的说明。
:::

这个连接由两部分组成：在后端一侧用**认证提供方**保护它，在应用一侧填入后端的 URL 并登录。把后端绑定到非环回地址会自动启用它的认证关卡，而你配置的提供方正是让桌面应用通过关卡的凭据来源。

**根据后端所在位置选择提供方：**

- **OAuth（Nous Portal）—— 只要超出你自己这台机器可达范围，都优先选它。** 登录会针对你的 Nous 账户进行校验，因此这是适用于 VPS、公网主机或任何远程后端的选项。用 `hermes dashboard register`（或 Portal 的 [`/local-dashboards`](https://portal.nousresearch.com/local-dashboards) 页面）注册 dashboard 以创建它的 OAuth 客户端，然后在应用中用 **Sign in with Nous Research** 登录。如果你自建身份提供方，自托管的 OIDC 提供方的工作方式完全相同。
- **用户名/密码 —— 仅限本地 / 受信任网络使用。** 当后端位于同一个受信任的局域网内，或只能通过 VPN（例如 Tailscale）访问时，这是最简单的选项。它只用一份共享凭据做保护，没有外部身份提供方，因此**不要把它用在暴露到公共互联网的 dashboard 上** —— 那种场景请改用 OAuth。

本节接下来演示用户名/密码这条路径，因为它在受信任网络中最快搭好；OAuth 路径参见 [Web Dashboard → 默认提供方：Nous Research](./features/web-dashboard.md#default-provider-nous-research)。

### 在后端（远程机器上）

设置用户名和密码，然后把后端绑定到一个可达地址上启动。凭据存放在 `~/.hermes/.env`（密钥文件，权限 0600）：

```bash
# 1. 设置 dashboard 的登录凭据。
cat >> ~/.hermes/.env <<'EOF'
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=choose-a-strong-password
# 建议：设置一个稳定的签名密钥，让会话在重启后依然有效。
# 不设置的话，每次启动都会生成一个随机密钥，你会在
# 每次重启后被登出。
HERMES_DASHBOARD_BASIC_AUTH_SECRET=$(openssl rand -base64 32)
EOF
chmod 600 ~/.hermes/.env

# 2. 把后端绑定到一个可达地址上运行。非环回绑定会
#    启用认证关卡；用户名/密码提供方负责登录。
hermes serve --host 0.0.0.0 --port 9119
```

只要你希望桌面应用能够连接，就必须让那个 `hermes serve` 进程一直运行 —— 一旦它停止，应用就再也连不上后端了。把它跑在 `systemd`、`tmux` 或你惯用的进程管理器下，让它在登出和重启后依然存活。

另外，如果你依赖消息频道，请确认远程主机上的 **gateway 正在运行** —— 桌面应用连接的是 `hermes serve` 后端，但你的 Telegram/Discord/Slack gateway 会话是另一个进程，需要你自行启动并保持运行。gateway 的设置参见 [Messaging](./messaging/index.md)。

不想在磁盘上留下明文密码？可以改为把 `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` 设为一个 scrypt 哈希 —— 用 `python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('PW'))"` 计算它。完整的配置面（config.yaml 中的键、所有环境变量、限流器）：[Web Dashboard → 用户名/密码提供方](./features/web-dashboard.md#usernamepassword-provider-no-oauth-idp)。

以 systemd 服务方式运行后端？请为该 unit 加上 `EnvironmentFile=%h/.hermes/.env`，这样开机时凭据就在环境变量中。

:::warning
后端会读写你的 `.env`（API 密钥、密钥），并且能够执行 agent 命令。上面演示的**用户名/密码**配置是给受信任网络用的 —— 绝不要把仅有密码保护的后端直接暴露到公网；请把它放在 VPN 之后。[Tailscale](https://tailscale.com/) 是干净的选择：把服务绑定到机器的 tailscale IP（`--host <tailscale-ip>`），并用 `http://<tailscale-ip>:9119` 作为远程 URL，这样只有你的 tailnet 能访问它。若要通过公共互联网访问后端，请改用 **OAuth（Nous Portal）** 提供方。
:::

### 在应用中

**设置 → Gateway → 远程 gateway：**

1. **远程 URL** —— `http://<backend-host>:9119`（如果你在前面加了反向代理，`/hermes` 之类的路径前缀也可以用）
2. **登录** —— 应用会检测后端宣告的是哪种提供方并相应调整按钮。对于用户名/密码的后端，它会显示一个 **Sign in** 按钮，打开一个凭据表单（填入第 1 步中的凭据）。对于 OAuth 后端，它会显示 **Sign in with `<provider>`**（例如 *Sign in with Nous Research*），点击后会走该提供方的浏览器登录流程。无论哪种方式，应用最终都会获得一个针对该后端的已认证会话。
3. **保存并重新连接** —— 把桌面外壳切换到远程后端。会话会自动刷新；只要设置了 `HERMES_DASHBOARD_BASIC_AUTH_SECRET`，你在重启之间都会保持登录状态。

你也可以不通过 UI，而是在启动应用前用环境变量 `HERMES_DESKTOP_REMOTE_URL` 设置后端 URL（它会覆盖应用内的设置）；登录仍然在 Gateway 设置面板中完成。

:::note 按 profile 的远程主机
远程 gateway 主机是按 [profile](./profiles.md) 配置的，因此每个 profile 都可以指向自己的远程后端（或继续使用本地后端）。切换 profile 就会切换应用连接的远程主机。
:::

### 故障排查

- **登录失败，返回 401 / "Invalid credentials"** —— 用户名或密码与后端的 `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` 不匹配。对于未知用户和错误密码，后端返回的是同一个通用错误（不提供枚举线索），所以两者都要仔细核对。用 `curl -s http://<host>:9119/api/status | jq '.auth_required, .auth_providers'` 确认关卡已开启 —— 它应当报告 `true` 并包含 `"basic"`。
- **没有 "Sign in" 按钮 —— 它反而要求填会话令牌** —— 后端的用户名/密码提供方没有启用。`/api/status` 的 `auth_providers` 中不会列出 `"basic"`。请确认 `~/.hermes/.env` 中同时设置了用户名和密码（或密码哈希），并且 dashboard 进程确实加载了它们。
- **每次重启都被登出** —— 把 `HERMES_DASHBOARD_BASIC_AUTH_SECRET` 设为一个固定值。不设置的话，令牌签名密钥每次启动都会重新生成，导致所有会话失效。
- **连接被拒绝 / 超时** —— 后端绑定到了 `127.0.0.1`（默认值），或者防火墙/VPN 挡住了端口。请绑定到 `0.0.0.0` 或 tailscale IP，并向你的受信任网络开放该端口。

同样的配置从 web dashboard 的角度看，参见 [Web Dashboard → 将 Hermes Desktop 连接到远程后端](./features/web-dashboard.md#connecting-hermes-desktop-to-a-remote-backend)；相关环境变量收录在[环境变量 → Web Dashboard 与 Hermes Desktop](../reference/environment-variables.md#web-dashboard--hermes-desktop)。

## 扩展桌面应用

桌面应用是由贡献驱动的 —— 面板、页面、侧边栏导航、状态栏
条目、命令面板命令、快捷键和主题全都通过同一套 SDK 注册，
你也可以添加自己的。一个插件就是放在
`$HERMES_HOME/desktop-plugins/<id>/plugin.js` 的单个 ESM 文件；应用会在几秒内加载它，
并在每次保存时热重载。已安装的插件可以在 **设置 → 插件** 中实时管理。

完整参考见 [Desktop Plugin SDK](../developer-guide/desktop-plugin-sdk.md)。
（这与 [web dashboard 插件系统](./features/extending-the-dashboard.md)是两回事。）

## 故障排查

启动日志位于 `HERMES_HOME/logs/desktop.log`（其中包含后端输出和最近的 Python traceback）—— 如果应用报告启动失败，先查看它。你也可以从 CLI 追踪它：

```bash
hermes logs gui -f
```

常见的重置操作：

```bash
# 强制进行一次干净的首次启动设置（macOS/Linux）
rm "$HOME/.hermes/hermes-agent/.hermes-bootstrap-complete"

# 重建损坏的 Python venv（macOS/Linux）
rm -rf "$HOME/.hermes/hermes-agent/venv"

# 重置卡住的 macOS 麦克风授权提示
tccutil reset Microphone com.nousresearch.hermes
```

### "Build desktop app" 卡在 Electron 下载

构建过程会从 `github.com/electron/electron/releases` 下载 Electron 运行时（约 114&nbsp;MB）。如果安装器卡在 **Build desktop app** 这一步，且实时输出反复出现 `retrying attempt=…`，说明你的网络（防火墙、代理或地区限制）正在屏蔽或限速 GitHub。

安装器会自动自愈：构建失败时，它会 (1) 清除损坏的 Electron 缓存 zip 并重试，然后 (2) 如果仍然失败且你没有设置 `ELECTRON_MIRROR`，就再通过事实上的 Electron 社区镜像 `npmmirror.com` 重试一次。`@electron/get` 会对下载做 SHASUM 校验，但校验和同样来自那个镜像 —— 这能发现损坏或不完整的下载，却发现不了被入侵的镜像。如果你不愿信任第三方主机，可以固定你自己的 `ELECTRON_MIRROR`（见下）；构建过程绝不会覆盖你已设置的值。

要**选择你自己的镜像**（例如企业内部的可信镜像），请在安装前设置 `ELECTRON_MIRROR` 或手动重新构建 —— 构建会遵循它，也不会覆盖它：

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
  bash -c 'cd "$HOME/.hermes/hermes-agent/apps/desktop" && CSC_IDENTITY_AUTO_DISCOVERY=false npm run pack'
```

要手动清除损坏的缓存 zip：

```bash
rm -f "$HOME/Library/Caches/electron"/electron-*.zip   # macOS
rm -f "$HOME/.cache/electron"/electron-*.zip            # Linux
```

## 从源码构建

如果你想开发应用本身，先在仓库根目录安装一次工作区依赖，然后从 `apps/desktop` 运行开发服务器：

```bash
npm install          # 在仓库根目录 —— 链接 apps/desktop、web、apps/shared
cd apps/desktop
npm run dev          # Vite 渲染进程 + Electron，由它启动 Python 后端
```

让应用指向某个特定的检出目录，或把它与你真实的配置隔离开：

```bash
HERMES_DESKTOP_HERMES_ROOT=/path/to/clone npm run dev
HERMES_HOME=/tmp/throwaway npm run dev
npm run dev:fake-boot   # 用确定性延迟来演练启动浮层
```

构建安装包：

```bash
npm run dist:mac     # DMG + zip
npm run dist:win     # NSIS + MSI
npm run dist:linux   # AppImage + deb + rpm
npm run pack         # release/ 下的未打包应用（无安装器）
```

当环境中存在相应凭据时（macOS 用 `CSC_LINK` / `CSC_KEY_PASSWORD` / `APPLE_*`，Windows 用 `WIN_CSC_*`），macOS/Windows 的签名与公证会自动执行。

## 另请参阅

- [CLI 指南](./cli.md) —— 终端界面
- [TUI](./tui.md) —— `hermes --tui` 和 dashboard 聊天标签页所使用的现代终端 UI
- [Web Dashboard](./features/web-dashboard.md) —— 带内嵌聊天标签页的浏览器管理面板
- [配置](./configuration.md) —— 桌面应用读写的配置
- [Windows（原生）](./windows-native.md) —— 原生 Windows 安装路径
