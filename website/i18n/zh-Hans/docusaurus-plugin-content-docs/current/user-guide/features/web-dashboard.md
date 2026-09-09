---
sidebar_position: 15
title: "Web Dashboard"
description: "基于浏览器的管理面板，用于管理配置、API 密钥、MCP 服务器、消息配对、webhook、gateway、记忆、凭据、会话、日志、分析、定时任务和技能"
---

# Web Dashboard

Web Dashboard 是一个基于浏览器的 UI，用于管理你的 Hermes Agent 安装。无需编辑 YAML 文件或运行 CLI 命令，即可通过简洁的 Web 界面配置设置、管理 API 密钥并监控会话。

:::tip
托管模式（hosted-mode）的认证使用 Nous Portal OAuth；如果你还希望 Dashboard 连接到真实的后端，`hermes setup --portal` 会一并配置好模型与工具 gateway。参见 [Nous Portal](/integrations/nous-portal)。
:::

## 快速开始

```bash
hermes dashboard
```

这将启动一个本地 Web 服务器，并在浏览器中打开 `http://127.0.0.1:9119`。Dashboard 完全在你的机器上运行——数据不会离开 localhost。

### 选项

| 标志 | 默认值 | 描述 |
|------|---------|-------------|
| `--port` | `9119` | Web 服务器运行端口 |
| `--host` | `127.0.0.1` | 绑定地址 |
| `--no-open` | — | 不自动打开浏览器 |
| `--insecure` | 关闭 | 允许绑定到非 localhost 主机（**危险**——会在网络上暴露 API 密钥；请配合防火墙和强认证使用） |
| `--isolated` | 关闭 | 从命名 profile 启动时（`worker dashboard`），运行一个专属于该 profile 的服务器，而不是路由到机器级 Dashboard |

```bash
# 自定义端口
hermes dashboard --port 8080

# 绑定到所有接口（在共享网络上请谨慎使用）
hermes dashboard --host 0.0.0.0

# 启动时不打开浏览器
hermes dashboard --no-open
```

## 管理多个 profile {#managing-multiple-profiles}

Dashboard 是一个**机器级**管理界面：一个服务器管理机器上的每一个
[profile](../profiles.md)。侧边栏中的 profile 切换器（只要存在多个 profile
就会显示）决定管理页面读写哪个 profile——Config、API Keys、Skills、
MCP、Models 和 Chat 标签页都会跟随它。当选中的不是 Dashboard 自身的
profile 时，一条琥珀色横幅会标明当前被管理的 profile，因此写入目标永远
不会含糊不清。

该选择保存在 URL 中（`?profile=<name>`），因此像
`http://127.0.0.1:9119/skills?profile=worker` 这样的深链接打开时切换器已
预先选中，并且刷新后依然保持。

从 profile 别名启动 Dashboard 会路由到机器级 Dashboard，而不是启动第二个
服务器：

```bash
worker dashboard
# → 已在运行：在浏览器中打开 ?profile=worker
# → 未在运行：启动机器级 Dashboard 并预选 "worker"
```

传入 `--isolated` 可以选择退出这一行为，运行一个仅限该 profile 的专属服务器
（即统一之前的行为——如果你有意让不同 profile 的 Dashboard 使用不同认证暴露
出去，这会很有用）。

**Chat** 标签页同样跟随切换器：受限于某个 profile 的聊天会以该 profile 的
`HERMES_HOME` 启动其 PTY 子进程，因此对话运行在该 profile 的模型、技能、
记忆和会话历史之下。切换 profile 会开启一个全新的终端会话。

哪些内容仍然是按 profile 独立、*不会*被切换器接管的：gateway 进程
（通过 `hermes -p <name> gateway …` 管理）、每个 profile 各自的会话数据库，
以及 cron 调度器（Cron 页面本身已经跨 profile 聚合，并带有自己的过滤器）。

## 前置条件

默认的 `hermes-agent` 安装不包含 HTTP 栈或 PTY 辅助工具——这些是可选扩展。**Web Dashboard** 需要 FastAPI 和 Uvicorn（`web` 扩展）。**Chat** 标签页还需要 `ptyprocess` 来在伪终端（pseudo-terminal）后面启动嵌入式 TUI（POSIX 上的 `pty` 扩展）。使用以下命令同时安装：

```bash
cd ~/.hermes/hermes-agent && uv pip install -e ".[web,pty]"
```

`web` 扩展会引入 FastAPI/Uvicorn；`pty` 扩展会引入 `ptyprocess`（POSIX）或 `pywinpty`（原生 Windows——注意嵌入式 TUI 本身仍需要 WSL）。`cd ~/.hermes/hermes-agent && uv pip install -e ".[all]"` 包含两个扩展，如果你还需要消息/语音等功能，这是最简便的方式。

在没有依赖项的情况下运行 `hermes dashboard` 时，它会告诉你需要安装什么。如果前端尚未构建且 `npm` 可用，则会在首次启动时自动构建。

Chat 标签页是每次 `hermes dashboard` 启动的一部分——内嵌的浏览器聊天面板（通过 PTY/WebSocket 运行 TUI）始终可用，无需任何额外参数。

## 页面

### Status（状态）

首页显示你的安装的实时概览：

- **Agent 版本**和发布日期
- **Gateway 状态**——运行中/已停止、PID、已连接平台及其状态
- **活跃会话**——过去 5 分钟内活跃的会话数量
- **最近会话**——最近 20 个会话的列表，包含模型、消息数、token 用量和对话预览

状态页每 5 秒自动刷新一次。

### Chat（聊天） {#chat}

**Chat** 标签页将完整的 Hermes TUI（与 `hermes --tui` 相同的界面）直接嵌入浏览器。你在终端 TUI 中能做的一切——斜杠命令、模型选择器、工具调用卡片、Markdown 流式输出、clarify/sudo/approval 提示、皮肤主题——在这里都完全一致，因为 Dashboard 运行的是真实的 TUI 二进制文件，并通过 [xterm.js](https://xtermjs.org/) 的 WebGL 渲染器以像素级精度渲染其 ANSI 输出。

**工作原理：**

- `/api/pty` 打开一个经 Dashboard 会话 token 认证的 WebSocket
- 服务器在 POSIX 伪终端后面启动 `hermes --tui`
- 按键传输到 PTY；ANSI 输出流式返回浏览器
- xterm.js 的 WebGL 渲染器将每个单元格绘制到整数像素网格；鼠标追踪（SGR 1006）、宽字符（Unicode 11）和方框绘制字形均原生渲染
- 调整浏览器窗口大小会通过 `@xterm/addon-fit` 插件调整 TUI 大小

**恢复已有会话：** 在 **Sessions** 标签页中，点击任意会话旁的播放图标（▶）。这会跳转到 `/chat?resume=<id>` 并以 `--resume` 参数启动 TUI，加载完整历史记录。

**会话切换器（右侧栏）：** Chat 标签页在终端旁的细长右侧栏中自带一个 ChatGPT 风格的对话列表，让你无需离开页面即可切换对话。侧栏顶部是模型选择器，紧接其下是会话列表；终端占据屏幕的绝大部分。列表显示当前 profile 下最近的会话——标题（没有标题时回退为消息预览）、相对的最后活跃时间、消息数，以及非 CLI 会话的来源渠道。点击任意一行即可就地恢复该会话（终端会带着该对话的历史重新启动）；当前活跃的会话会被高亮。**New chat** 开启一个全新会话，刷新控件会重新拉取列表。该侧栏仅用于切换，是只读的——删除、重命名、导出和批量清理仍然位于 **Sessions** 标签页。在窄屏上它会折叠为一个滑出面板。

**前置条件：**

- Node.js（与 `hermes --tui` 相同的要求；TUI 包在首次启动时构建）
- `ptyprocess`——由 `pty` 扩展安装（`cd ~/.hermes/hermes-agent && uv pip install -e ".[web,pty]"`，或 `[all]` 同时包含两者）
- POSIX 内核（Linux、macOS 或 WSL2）。`/chat` 终端面板特别需要 POSIX PTY——原生 Windows Python 没有等效实现，因此在原生 Windows 安装上，Dashboard 的其余部分（sessions、jobs、metrics、config editor）可以正常工作，但 `/chat` 标签页会显示提示，告知你需要使用 WSL2 才能使用该功能。

关闭浏览器标签页后，PTY 会在服务器端被干净地回收。重新打开会启动一个新会话。

若要让 [Hermes Desktop](#connecting-hermes-desktop-to-a-remote-backend) 指向运行在另一台机器上的 Dashboard，而不是使用它自带的本地后端，请参阅下面的远程后端一节。

### 通过远程后端使用 Desktop 聊天 {#desktop-chat-over-a-remote-backend}

Hermes Desktop 通常会启动自己的本地后端，但它也可以通过 **Settings → Gateway → Remote gateway** 连接到运行在远程机器（虚拟机、家庭实验室主机等）上的 Dashboard。这是"Desktop 说后端已就绪但聊天始终不可用"这类报告最常见的来源，因为 Desktop 的就绪检查所验证的内容比实时聊天连接实际需要的要少。

:::info 前置条件：远程主机上必须有一个正在运行的 `hermes dashboard`
Desktop 所连接的"远程后端"**就是**运行在远程机器上的 `hermes dashboard` 进程——也就是本页所描述的同一个服务器。在下面任何步骤生效之前，它必须已经启动并可访问；Desktop 只是连接到它，并不会替你启动它。请用 `systemd`/`tmux` 等方式保持它运行，以便在登出和重启后依然存活。**gateway**（Telegram/Discord/Slack 等）是一个*独立的*长期运行进程——如果你依赖消息渠道，请单独启动它；它并不是桌面应用所连接的对象。
:::

Desktop 的"远程后端已就绪"探测只会请求 `GET /api/status`，而这是一个公开端点——只要主机上*任何*一个 Dashboard 在运行，它就会有响应。实时聊天连接是一个**独立的** WebSocket，指向 `/api/ws`（以及 `/api/pty`），而这个 socket 还受到状态探测从不触及的另外两项检查的约束：

1. **你必须已通过认证。** 当 Dashboard 绑定到非回环地址时，它会启用认证门。请用用户名和密码保护它（内置的[用户名/密码提供方](#usernamepassword-provider-no-oauth-idp)）；Desktop 登录一次，然后通过一次性票据（ticket）将所得会话复用于 WebSocket。如果没有配置任何提供方，非回环的 Dashboard 会在**启动时直接失败关闭**。
2. **绑定主机必须允许该客户端，并且与 Host 头匹配。** 回环绑定（`127.0.0.1`）只接受回环客户端，因此无论凭据是否正确，远程机器都会在 socket 层被拒绝。请绑定到非回环地址（`--host 0.0.0.0`），让对端 IP 校验放行远程客户端。你在 Desktop 中填写的远程 URL 必须以它所绑定的同一主机名访问到该 Dashboard——DNS 重绑定（rebinding）防护要求 Host 头匹配。

#### 远程 Dashboard 设置

设置用户名和密码，然后让 Dashboard 绑定到一个可访问的地址运行。对于 `systemd` 服务：

```ini
[Service]
EnvironmentFile=%h/.hermes/.env
ExecStart=/path/to/venv/bin/python -m hermes_cli.main dashboard \
    --host 0.0.0.0 --port 9119 --no-open
```

其中 `~/.hermes/.env` 包含：

```bash
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=choose-a-strong-password
HERMES_DASHBOARD_BASIC_AUTH_SECRET=<32+ random bytes; openssl rand -base64 32>
```

然后在 Desktop 中填入 **Remote URL**（例如 `http://VM_IP:9119`），并用该用户名和密码**登录**。完整的配置项参见[用户名/密码提供方](#usernamepassword-provider-no-oauth-idp)一节。

:::tip 重试 Desktop 之前先确认认证门已开启
在任意机器上检查 Dashboard 是否已公布用户名/密码提供方：

```bash
curl -s http://VM_IP:9119/api/status | jq '.auth_required, .auth_providers'
# true
# ["basic"]
```

- `auth_required: true` 且提供方列表中含 `"basic"` → Desktop 的**登录**流程可以工作。
- `auth_required: false` → 绑定的是回环地址，或者认证门没有启用。请绑定到非回环地址。
- `auth_required: true` 但没有 `"basic"` 提供方 → 用户名/密码环境变量没有被加载。请先修复它们。
:::

如果 `/api/status` 显示认证门已开启且带有 `"basic"` 提供方，而 Desktop 登录后*仍然*连不上，那么问题就超出了基础配置的范围——请取一份新的 `desktop.log`（Settings → Gateway → Open logs）以及同一次重试时间窗内的 Dashboard 日志，查找 `/api/ws` 的关闭码（4403 = 聊天 WS 被请求守卫拒绝，例如 Host/对端不匹配；4401 = WS 票据认证失败）。

### Config（配置）

`config.yaml` 的表单式编辑器。所有 150+ 个配置字段均从 `DEFAULT_CONFIG` 自动发现，并按标签页分类组织：

![Config 管理页面——左侧为分区筛选，右侧为自动发现的字段](/img/dashboard/admin-config.png)


- **model** — 默认模型、提供商、基础 URL、推理设置
- **terminal** — 后端（local/docker/ssh/modal）、超时、Shell 偏好
- **display** — 皮肤、工具进度、恢复显示、spinner 设置
- **agent** — 最大迭代次数、gateway 超时、服务层级
- **delegation** — 子 agent 限制、推理力度
- **memory** — 提供商选择、上下文注入设置
- **approvals** — 危险命令审批模式（smart/manual/off）
- 更多——config.yaml 的每个部分都有对应的表单字段

具有已知有效值的字段（terminal 后端、皮肤、审批模式等）渲染为下拉菜单。布尔值渲染为开关。其余均为文本输入框。

**操作：**

- **Save** — 立即将更改写入 `config.yaml`
- **Reset to defaults** — 将所有字段恢复为默认值（点击 Save 前不会保存）
- **Export** — 将当前配置下载为 JSON
- **Import** — 上传 JSON 配置文件以替换当前值

:::tip
配置更改在下一次 agent 会话或 gateway 重启时生效。Web Dashboard 编辑的是 `hermes config set` 和 gateway 读取的同一个 `config.yaml` 文件。
:::

### API Keys（API 密钥）

管理存储 API 密钥和凭据的 `.env` 文件。密钥按类别分组：

- **LLM Providers** — OpenRouter、Anthropic、OpenAI、DeepSeek 等
- **Tool API Keys** — Browserbase、Firecrawl、Tavily、ElevenLabs 等
- **Messaging Platforms** — Telegram、Discord、Slack bot token 等
- **Agent Settings** — 非敏感环境变量，如 `API_SERVER_ENABLED`

每个密钥显示：
- 是否已设置（带有值的脱敏预览）
- 用途说明
- 提供商注册/密钥页面的链接
- 用于设置或更新值的输入框
- 删除按钮

高级/不常用的密钥默认隐藏，可通过开关显示。

### Sessions（会话）

浏览和检查所有 agent 会话。每行显示会话标题、来源平台图标（CLI、Telegram、Discord、Slack、cron）、模型名称、消息数、工具调用数以及最后活跃时间。实时会话以脉冲徽章标记。

- **Search** — 使用 FTS5 对所有消息内容进行全文搜索。结果显示高亮片段，展开时自动滚动到第一条匹配消息。
- **Stats** — 汇总栏显示会话总数、存储中活跃会话数、已归档数量、消息总数，以及按来源的细分。
- **Expand** — 点击会话以加载完整消息历史。消息按角色（user、assistant、system、tool）用颜色区分，并以带语法高亮的 Markdown 渲染。
- **Tool calls** — 包含工具调用的 assistant 消息显示可折叠块，包含函数名和 JSON 参数。
- **Rename** — 就地设置或清除会话标题（铅笔图标）。
- **Export** — 将会话（元数据 + 完整消息历史）下载为 JSON（下载图标）。
- **Prune** — 页头的"Prune old sessions"按钮会删除结束时间超过 N 天的会话。
- **Delete** — 使用垃圾桶图标删除会话及其消息历史。

![Sessions 管理页面——统计栏、清理，以及每行的重命名 / 导出 / 删除](/img/dashboard/admin-sessions.png)

### Logs（日志）

查看 agent、gateway 和错误日志文件，支持过滤和实时追踪。

- **File** — 在 `agent`、`errors` 和 `gateway` 日志文件之间切换
- **Level** — 按日志级别过滤：ALL、DEBUG、INFO、WARNING 或 ERROR
- **Component** — 按来源组件过滤：all、gateway、agent、tools、cli 或 cron
- **Lines** — 选择显示行数（50、100、200 或 500）
- **Auto-refresh** — 切换实时追踪，每 5 秒轮询新日志行
- **Color-coded** — 日志行按严重程度着色（错误为红色，警告为黄色，debug 为暗色）

### Analytics（分析）

基于会话历史计算的用量和成本分析。选择时间段（7、30 或 90 天）查看：

- **Summary cards** — 总 token 数（输入/输出）、缓存命中率、总估算或实际成本，以及总会话数和日均值
- **Daily token chart** — 堆叠柱状图，显示每日输入和输出 token 用量，悬停提示显示明细和成本
- **Daily breakdown table** — 每日日期、会话数、输入 token、输出 token、缓存命中率和成本
- **Per-model breakdown** — 显示每个使用模型的会话数、token 用量和估算成本的表格

### Cron（定时任务）

创建和管理按定期计划运行 agent prompt 的定时任务。

- **Create** — 填写名称（可选）、prompt、cron 表达式（如 `0 9 * * *`）和投递目标（local、Telegram、Discord、Slack 或 email）
- **Job list** — 每个任务显示其名称、prompt 预览、计划表达式、状态徽章（enabled/paused/error）、投递目标、上次运行时间和下次运行时间
- **Pause / Resume** — 在活跃和暂停状态之间切换任务
- **Edit** — 打开一个预填的弹窗，修改任务的 prompt、计划、名称或投递目标
- **Trigger now** — 在正常计划之外立即执行任务
- **Delete** — 永久删除定时任务

### Profiles（配置档案）

创建和管理 [profile](../profiles.md)——拥有各自配置、技能和会话的隔离 Hermes 实例。

- **Profile 卡片** — 每张卡片显示其模型/提供商、技能数量、gateway 状态、描述和徽章（活跃、默认、别名）
- **Create** — 名称 + 可选的从默认克隆 / 全量克隆 / 不含内置技能、描述和模型；专门的 Profile Builder 页面（`/profiles/new`）提供完整流程（模型、MCP、技能）
- **Manage skills & tools** — 跳转到限定该 profile 的 Skills 页面（会设置侧边栏的 profile 切换器）
- **Set as active** — 切换**未来 CLI/gateway 运行**所采用的粘性默认值（等同于 `hermes profile use`）。这*不会*改变 Dashboard 所管理的对象——那是 profile 切换器的职责
- **Edit model / description / SOUL** — 就地编辑器，直接写入该 profile
- **Rename / Delete** — 仅限命名 profile

### Skills（技能）

浏览、搜索和切换已安装的技能与工具集，并可从 hub 安装新的。技能从 `~/.hermes/skills/` 加载，并按类别分组。

- **Search** — 按名称、描述或类别过滤已安装的技能和工具集
- **Category filter** — 点击类别标签缩小列表范围（如 MLOps、MCP、Red Teaming、AI）
- **Toggle** — 使用开关启用或禁用单个技能。更改在下一次会话时生效。
- **Toolsets** — 单独的视图显示内置工具集（文件操作、Web 浏览等），包含其活跃/非活跃状态、设置要求和包含的工具列表
- **Browse hub** — 第三个视图跨所有来源搜索技能 hub（与 `hermes skills search` 相同），可按标识符安装任意结果并显示实时安装日志，还提供"Update all"按钮来刷新已安装的技能。

![Skills 管理页面——Browse hub 视图：搜索、安装和更新](/img/dashboard/admin-skills-hub.png)

### MCP

无需 CLI 即可管理 [MCP](/user-guide/features/mcp) 服务器。操作的是 `config.yaml` 中
`hermes mcp` 所读取的同一个 `mcp_servers` 块。

**你的 MCP 服务器：**

- **Add** — 注册 HTTP/SSE 服务器（URL）或 stdio 服务器（命令 + 参数），stdio 服务器可选填 `KEY=VALUE` 环境变量
- **Enable / disable** — 启用或禁用某个服务器而不删除它。被禁用的服务器仍保留在配置中，方便日后重新启用。在下一次 gateway 重启时生效。
- **Test** — 连接服务器、列出其工具，然后断开——在 agent 依赖它之前先验证连接
- **Remove** — 从配置中删除服务器
- 形似机密的环境变量值在列表视图中会被脱敏

**Catalog：** 浏览 Nous 认可的 MCP 服务器（内置的 `optional-mcps/`
目录），一键安装其中任意一个。需要 API 密钥的条目会就地提示填写；这些值会写入
`.env`。这与 `hermes mcp catalog` / `hermes mcp install` 使用的是同一个目录。

![MCP 管理页面——你的服务器及启用/禁用开关，以及安装目录](/img/dashboard/admin-mcp.png)

### Webhooks

管理动态 [webhook 订阅](/user-guide/messaging/webhooks)。必须先在消息设置中
启用 webhook 平台；未启用时页面会给出提示。

- **Create** — 名称、描述、事件过滤器、投递目标、可选的直接投递模式，以及一个 agent prompt。创建后页面会显示路由 URL 和一次性的 HMAC 密钥供你复制。
- **Enable / disable** — 启用或禁用某个订阅。被禁用的路由仍保留在订阅文件中，但 gateway 会拒绝其收到的事件（403）。gateway 会热重载该文件，因此更改在下一个事件时生效——无需重启。
- **List** — 每个订阅显示其 URL、事件和投递目标
- **Delete** — 删除订阅

![Webhooks 管理页面——带启用/禁用开关的订阅列表](/img/dashboard/admin-webhooks.png)

### Pairing（配对）

无需 CLI 即可批准和撤销消息用户——这是远程管理员将 Telegram/Discord 等
用户接入已配对 gateway 的方式。与 `hermes pairing` 功能完全对等。

- **Pending requests** — 每条显示平台、配对码、用户和存在时长，并带有 Approve 按钮
- **Approved users** — 每条显示平台和用户，并带有 Revoke 按钮
- **Clear pending** — 清除所有未处理的配对码

![Pairing 管理页面](/img/dashboard/admin-pairing.png)

### Channels（渠道）

在浏览器中把 Hermes 连接到任意消息平台——与 `hermes setup gateway` 功能
完全对等。该页面列出每一个受支持的渠道（Telegram、Discord、Slack、Matrix、
Mattermost、WhatsApp、Signal、BlueBubbles/iMessage、Email、SMS/Twilio、
DingTalk、Feishu/Lark、WeCom、WeChat、QQ Bot、Yuanbao，以及 API 服务器和
webhook 端点）及其实时连接状态。

- **Configure** — 打开针对该平台的表单，其中恰好包含该渠道所需的字段（bot token、app token、服务器 URL、允许列表等）。机密以密码输入框呈现并以脱敏方式存储；字段留空表示保留现有值。必填字段会被标注并校验。"Setup guide"链接指向该平台的凭据文档。
- **Enable / disable** — 启用或禁用某个渠道。凭据仍保留在磁盘上；改变的只是启用状态。
- **Test** — 检查该渠道是否已配置、已启用，以及 gateway 是否报告了实时连接。
- **Restart gateway** — 凭据写入 `~/.hermes/.env`，启用标志写入 `config.yaml`；gateway 会在下一次重启时连接每个已启用的渠道，而你可以直接在该页面触发重启。

![Channels 管理页面——每个消息平台的状态、启用开关和各平台的设置表单](/img/dashboard/admin-channels.png)

### System（系统）

面向整个安装的统一管理面板：

- **Host** — 实时系统统计：操作系统 / 内核、架构、主机名、Python 和 Hermes 版本、CPU 核心数 + 利用率、内存、Hermes home 的磁盘占用、运行时长和平均负载。（CPU/内存/磁盘在安装了 `psutil` 时提供；身份类字段始终显示。）Hermes 版本旁会显示**更新状态徽章**（已是最新 / 落后 N 个提交）和一个 **Check for updates** 按钮。当 git 或 pip 安装存在可用更新时，**Update now** 按钮会打开确认对话框——显示你将拉取多少个提交——然后在后台运行 `hermes update`。在 Docker/Nix/Homebrew 安装上，Dashboard 无法就地应用更新，因此会显示正确的带外（out-of-band）命令。
- **Nous Portal** — 登录状态、当前推理提供方，以及 Tool Gateway 路由表（哪些工具经由 Portal 运行、哪些在本地运行），并带有管理订阅的链接。这是 `hermes portal` 的只读镜像。
- **Skill curator** — 后台技能维护状态（活跃 / 已暂停、间隔、上次运行），带有暂停/恢复和立即运行按钮。对应 `hermes curator`。
- **Gateway** — 启动、停止和重启消息 gateway，并显示实时状态（运行中/已停止、PID、状态）
- **Memory** — 选择外部记忆提供方（或仅使用内置），并重置内置的 `MEMORY.md` / `USER.md` 存储
- **Credential pool** — 添加和移除 agent 轮询使用的轮换 API 密钥（按提供商）。密钥在列表中脱敏；原始值只会到达 agent。
- **Operations** — 运行 `doctor`、安全审计、创建备份、从备份归档恢复、更新技能、显示系统提示词大小明细、生成支持转储，或为已废弃设置迁移配置。每一项都会启动一个后台动作，其实时日志会流式显示在页面中。
- **Checkpoints** — 查看 `/rollback` 影子存储的大小并进行清理
- **Shell hooks** — 列出已配置的 hook 及其授权 + 可执行状态，**创建** hook（事件、命令、匹配器、超时，并可选择性授予授权），以及删除 hook。Hook 会运行任意命令，因此创建表单带有安全警告，且只有在授予授权后 hook 才会触发。

![System 管理页面——主机统计和 Nous Portal 状态](/img/dashboard/admin-system-top.png)

![System 管理页面——技能 curator、gateway、记忆和凭据池](/img/dashboard/admin-system-curator.png)

![System 管理页面——运维操作、检查点和 shell hook](/img/dashboard/admin-system-ops.png)

创建 shell hook（注意授权复选框和"运行任意命令"的警告）：

![新建 shell hook 弹窗](/img/dashboard/admin-hook-create.png)

:::warning 安全提示
Web Dashboard 会读写包含 API 密钥和机密的 `.env` 文件。它默认绑定到 `127.0.0.1`——只能从本机访问。如果绑定到 `0.0.0.0`，网络上的任何人都可以查看和修改你的凭据。Dashboard 本身没有任何认证机制。
:::

## `/reload` 斜杠命令

Dashboard 还为交互式 CLI 添加了 `/reload` 斜杠命令。通过 Web Dashboard（或直接编辑 `.env`）更改 API 密钥后，在活跃的 CLI 会话中使用 `/reload` 即可获取更改，无需重启：

```
You → /reload
  Reloaded .env (3 var(s) updated)
```

这会将 `~/.hermes/.env` 重新读取到运行中进程的环境中。当你通过 Dashboard 添加了新的提供商密钥并希望立即使用时非常有用。

## REST API

Web Dashboard 暴露了一个供前端使用的 REST API。你也可以直接调用这些端点进行自动化操作：

:::tip profile 级端点
各类管理端点族——`/api/config`、`/api/env`、`/api/skills`、
`/api/tools/toolsets`、`/api/mcp` 以及 `/api/model/{info,options,auxiliary,set}`——
都接受一个可选的 `?profile=<name>` 查询参数（写操作时也可在 JSON 请求体中
使用 `"profile"`），把读写限定到该 profile 的 `HERMES_HOME`。省略即表示
Dashboard 自身的 profile。未知的 profile 名会返回 `404`。`/api/pty`
WebSocket 接受同样的参数，用于在所选 profile 下启动聊天。
:::

### GET /api/status

返回 agent 版本、gateway 状态、平台状态和活跃会话数。

### GET /api/sessions

返回最近 20 个会话的元数据（模型、token 数、时间戳、预览）。

### GET /api/config

以 JSON 格式返回当前 `config.yaml` 内容。

### GET /api/config/defaults

返回默认配置值。

### GET /api/config/schema

返回描述每个配置字段的 schema——类型、描述、类别，以及适用时的选项。前端使用此 schema 为每个字段渲染正确的输入控件。

### PUT /api/config

保存新配置。请求体：`{"config": {...}}`。

### GET /api/env

返回所有已知环境变量，包含其设置/未设置状态、脱敏值、描述和类别。

### PUT /api/env

设置环境变量。请求体：`{"key": "VAR_NAME", "value": "secret"}`。

### DELETE /api/env

删除环境变量。请求体：`{"key": "VAR_NAME"}`。

### GET /api/sessions/\{session_id\}

返回单个会话的元数据。

### GET /api/sessions/\{session_id\}/messages

返回会话的完整消息历史，包含工具调用和时间戳。

### GET /api/sessions/search

对消息内容进行全文搜索。查询参数：`q`。返回匹配的会话 ID 和高亮片段。

### DELETE /api/sessions/\{session_id\}

删除会话及其消息历史。

### GET /api/logs

返回日志行。查询参数：`file`（agent/errors/gateway）、`lines`（数量）、`level`、`component`。

### GET /api/analytics/usage

返回 token 用量、成本和会话分析。查询参数：`days`（默认 30）。响应包含每日明细和按模型聚合数据。

### GET /api/cron/jobs

返回所有已配置的定时任务，包含其状态、计划和运行历史。

### POST /api/cron/jobs

创建新定时任务。请求体：`{"prompt": "...", "schedule": "0 9 * * *", "name": "...", "deliver": "local"}`。

### POST /api/cron/jobs/\{job_id\}/pause

暂停定时任务。

### POST /api/cron/jobs/\{job_id\}/resume

恢复已暂停的定时任务。

### POST /api/cron/jobs/\{job_id\}/trigger

在计划之外立即触发定时任务。

### DELETE /api/cron/jobs/\{job_id\}

删除定时任务。

### GET /api/skills

返回所有技能，包含其名称、描述、类别和启用状态。

### PUT /api/skills/toggle

启用或禁用技能。请求体：`{"name": "skill-name", "enabled": true}`。

### GET /api/tools/toolsets

返回所有工具集，包含其标签、描述、工具列表以及活跃/已配置状态。

### 管理端点

这些端点支撑着 MCP、Channels、Webhooks、Pairing 和 System 页面。它们与 `/api/`
的其余部分位于同一道认证门之后。

| 方法与路径 | 用途 |
|---------------|---------|
| `GET /api/mcp/servers` | 列出已配置的 MCP 服务器（环境变量值脱敏） |
| `POST /api/mcp/servers` | 添加服务器。请求体：`{name, url?, command?, args?, env?, auth?}` |
| `POST /api/mcp/servers/{name}/test` | 连接、列出工具、断开 |
| `PUT /api/mcp/servers/{name}/enabled` | 启用 / 禁用服务器 |
| `DELETE /api/mcp/servers/{name}` | 删除服务器 |
| `GET /api/mcp/catalog` | 浏览 Nous 认可的 MCP 目录 |
| `POST /api/mcp/catalog/install` | 安装目录条目（附带所需环境变量） |
| `GET /api/messaging/platforms` | 列出每个消息渠道及其状态 + 各平台的设置字段 |
| `PUT /api/messaging/platforms/{id}` | 配置渠道。请求体：`{enabled?, env?, clear_env?}`（env 写入 `.env`，enabled 写入 `config.yaml`） |
| `POST /api/messaging/platforms/{id}/test` | 报告某渠道是否已配置、已启用并已连接 |
| `GET /api/pairing` | 列出待处理 + 已批准的消息用户 |
| `POST /api/pairing/approve` | 批准一个配对码。请求体：`{platform, code}` |
| `POST /api/pairing/revoke` | 撤销一个用户。请求体：`{platform, user_id}` |
| `POST /api/pairing/clear-pending` | 清除所有待处理的配对码 |
| `GET /api/webhooks` | 列出订阅 + 平台启用状态 |
| `POST /api/webhooks` | 创建订阅（返回一次性密钥） |
| `DELETE /api/webhooks/{name}` | 删除订阅 |
| `GET /api/credentials/pool` | 列出池中的轮换密钥（脱敏） |
| `POST /api/credentials/pool` | 添加密钥。请求体：`{provider, api_key, label?}` |
| `DELETE /api/credentials/pool/{provider}/{index}` | 删除密钥（索引从 1 开始） |
| `GET /api/memory` | 当前提供方 + 可用提供方 + 内置文件大小 |
| `PUT /api/memory/provider` | 选择提供方（留空 = 仅内置） |
| `POST /api/memory/reset` | 重置内置记忆。请求体：`{target: all\|memory\|user}` |
| `POST /api/gateway/start` · `/stop` · `/restart` | Gateway 生命周期（后台执行） |
| `POST /api/ops/doctor` · `/security-audit` · `/backup` · `/import` | 诊断与维护（后台执行；通过 `/api/actions/{name}/status` 查看输出） |
| `GET /api/ops/hooks` | 已配置的 shell hook + 允许列表状态 |
| `GET /api/ops/checkpoints` · `POST .../prune` | 查看 / 清理 `/rollback` 存储 |
| `POST /api/ops/hooks` · `DELETE /api/ops/hooks` | 创建 / 删除 shell hook（需授权） |
| `GET /api/system/stats` | 主机统计——操作系统、CPU、内存、磁盘、运行时长 |
| `GET /api/hermes/update/check` | 报告是否有可用更新（落后多少提交、安装方式）而不实际应用。对于落后的 git/pip 安装，还会返回一个 `commits` 列表（`sha`、`summary`、`author`、`at`）说明变更内容。`?force=1` 会绕过 6 小时缓存 |
| `GET /api/curator` · `PUT .../paused` · `POST .../run` | 技能 curator 状态 + 暂停/恢复 + 运行 |
| `GET /api/portal` | Nous Portal 认证 + Tool Gateway 路由（只读） |
| `POST /api/ops/prompt-size` · `/dump` · `/config-migrate` | 诊断（后台执行） |
| `PUT /api/webhooks/{name}/enabled` | 启用 / 禁用 webhook 路由 |
| `POST /api/skills/hub/install` · `/uninstall` · `/update` | 技能 hub 操作（后台执行） |
| `GET /api/skills/hub/search` | 跨所有来源搜索技能 hub |
| `GET /api/sessions/stats` | 会话存储统计 |
| `PATCH /api/sessions/{id}` | 重命名 / 归档会话 |
| `GET /api/sessions/{id}/export` | 将会话（元数据 + 消息）导出为 JSON |
| `POST /api/sessions/prune` | 删除结束时间超过 N 天的会话 |
| `PUT /api/cron/jobs/{id}` | 编辑定时任务的 prompt / 计划 / 名称 / 投递目标 |

## 认证（gated 模式） {#authentication-gated-mode}

当 Dashboard 绑定到公网或非回环地址时——也就是 `127.0.0.1` / `localhost` 之外的任何地址——Hermes Agent 会启用一道认证门。每个请求都必须携带经过验证的会话 cookie，否则会被弹回登录页。内置了三种提供方：

- **[用户名/密码](#usernamepassword-provider-no-oauth-idp)** — 为自托管 / 本地部署 / 家庭实验室的 Dashboard 加上认证的最简单方式。不需要外部身份提供方。**只应在可信网络上或 VPN 之后使用——不适合暴露到公网。**
- **[OAuth（Nous Portal）](#default-provider-nous-research)** — 适用于托管部署以及任何可从公网访问的 Dashboard，也是[远程 Hermes Desktop 连接](#connecting-hermes-desktop-to-a-remote-backend)的推荐方式。每次登录都会针对你的 Nous 账户进行验证，因此这是适合面向互联网使用的提供方。
- **[自托管 OIDC](#self-hosted-oidc-provider)** — 通过标准 OpenID Connect 接入你自己的身份提供方（Keycloak、Auth0、Okta、Google、通过 OIDC 桥接的 GitHub 等）。不涉及 Nous Portal；在由符合规范的 OIDC 服务器托底时，适合暴露到公网。

绑定到回环地址、由运维者自用的 Dashboard 不受影响——没有认证，也没有登录页。

### 认证门何时启用

| 标志 | 认证门 | 使用场景 |
|-------|-----------|----------|
| `hermes dashboard`（默认——绑定到 `127.0.0.1`） | 关闭 | 本地开发 |
| `hermes dashboard --host 0.0.0.0` | **开启** | 远程 / 生产环境——请用用户名/密码提供方或 OAuth 保护 |

当且仅当满足以下条件时认证门开启：

1. 绑定主机不是 `127.0.0.1`、`::1`、`localhost` 或 `0.0.0.0`，**并且**
2. **没有**设置 `--insecure` 标志。

:::danger `--insecure` 会完全关闭认证
`--insecure` 会跳过认证门，提供一个未认证的 Dashboard，它可以读写你的 `.env`（API 密钥、机密）并运行 agent 命令。**不要在远程连接中使用它。** 若要把 Dashboard 暴露给另一台机器，请配置[用户名/密码提供方](#usernamepassword-provider-no-oauth-idp)（或 OAuth）并保持 `--insecure` 关闭。该标志仅作为在完全可信、有防火墙的单主机网络中的最后手段而存在。
:::

### 失败即关闭（fail-closed）语义

如果认证门本应启用，但**没有**注册任何 `DashboardAuthProvider`（没有 Nous 插件，也没有自定义插件），`hermes dashboard` 会拒绝绑定并给出明确的错误信息。不存在"默认拒绝但实际全部放行"的兜底行为——配置错误的 gated Dashboard 永远不会启动。

当你**交互式地**（在真实终端中）运行 `hermes dashboard --host 0.0.0.0` 而尚未配置任何提供方时，Hermes 不会直接失败——它会当场提出帮你配置一个：选择**用户名与密码**（将 `dashboard.basic_auth` 写入 `config.yaml`，几秒钟即可跑起来）或 **OAuth**（引导你使用 `hermes dashboard register`）。非交互式调用方——Docker/s6、CI、管道运行——会跳过提示并触发上面的失败即关闭错误，因此无人值守的部署仍然绝不会在没有认证的情况下启动。

### 默认提供方：Nous Research {#default-provider-nous-research}

内置的 `plugins/dashboard_auth/nous` 插件**始终随包安装**并自动加载。当配置了 client ID 时，它会自动注册一个名为 `nous` 的 `DashboardAuthProvider`。

因为每次登录都会针对 Nous Portal 进行验证，并受你的 Nous 账户保护，**Nous 提供方是适合将 Dashboard 暴露到公网的那一个。**

#### 注册一个 Dashboard {#registering-a-dashboard}

要使用 Nous 提供方，你需要一个 OAuth client ID（形如 `agent:{id}`）。获取方式有两种：

- **CLI —— `hermes dashboard register`。** 在 Dashboard 所在的主机上运行。它会解析你现有的 Nous 登录（如果尚未登录，请先运行 `hermes setup`），向 Portal 注册一个自托管 OAuth 客户端，并替你把 `HERMES_DASHBOARD_OAUTH_CLIENT_ID` 写入 `~/.hermes/.env`。可选标志：`--name`（人类可读的标签，否则自动生成）和 `--redirect-uri`（面向互联网的主机所使用的公网 HTTPS 回调 URL）。

  ```bash
  hermes dashboard register
  # ✓ Registered dashboard "swift_falcon"
  # …writes HERMES_DASHBOARD_OAUTH_CLIENT_ID to ~/.hermes/.env
  ```

- **GUI —— Local Dashboards 页面。** 在 Nous Portal 中打开 [`/local-dashboards`](https://portal.nousresearch.com/local-dashboards)，即可在浏览器中注册、命名、管理和撤销自托管 Dashboard。把得到的 `agent:{id}` client ID 复制到 `HERMES_DASHBOARD_OAUTH_CLIENT_ID`（环境变量）或 `dashboard.oauth.client_id`（config.yaml）。通过 CLI 注册的 Dashboard 也在这里撤销。

#### 配置

该插件从两个来源读取配置，环境变量在非空设置时优先：

**`config.yaml`** —— 规范来源：

```yaml
dashboard:
  oauth:
    client_id: agent:01HXYZ…             # 启用认证门所必需
```

**环境变量** —— 运维者覆盖项：

| 环境变量 | 覆盖 | 格式 | 由谁提供 |
|---------|-----------|--------|----------------|
| `HERMES_DASHBOARD_OAUTH_CLIENT_ID` | `dashboard.oauth.client_id` | `agent:{instance_id}` | `hermes dashboard register` |

按照 Hermes Agent 的惯例（`~/.hermes/.env` 只用于 API 密钥 / 机密），**推荐把这些值设置在 `config.yaml` 中**，适用于本地开发、本地部署以及任何由你直接掌控的部署。环境变量这条路径的存在，是为了让托管平台的密钥注入机制能够按部署推送不同的 `client_id`，而无需任何人去修改镜像内的 `config.yaml`——这才是它的主要用途。

空的环境变量值会被视为未设置，因此一个"已配置但未填值"的平台密钥不会意外覆盖有效的 `config.yaml` 条目。

如果两个来源都没有提供 client_id，插件会报告具体原因，而 Dashboard 失败即关闭的绑定错误会准确告诉你需要修复什么：

```
Refusing to bind dashboard to 0.0.0.0 — the OAuth auth gate engages on
non-loopback binds, but no auth providers are registered.

Bundled providers reported these issues:
  • nous: HERMES_DASHBOARD_OAUTH_CLIENT_ID is not set (and
    dashboard.oauth.client_id in config.yaml is empty). The Nous Portal
    provisions this env var (shape 'agent:{instance_id}') when it
    deploys a Hermes Agent instance — set it to your provisioned
    client id (either as an env var or under dashboard.oauth.client_id
    in config.yaml), or pass --insecure to skip the OAuth gate entirely.

Or pass --insecure to skip the auth gate (NOT recommended on untrusted
networks).
```

#### 实例演练：Nous Research

从一个已登录的 Hermes 安装，三步得到一个由 Nous 保护的 Dashboard。

**1. 登录并注册 Dashboard。** `hermes dashboard register` 会使用你现有的 Nous 登录来配置一个 OAuth 客户端，并替你把 `HERMES_DASHBOARD_OAUTH_CLIENT_ID` 写入 `~/.hermes/.env`：

```bash
hermes setup            # 如果你还没有登录 Nous Portal
hermes dashboard register
# ✓ Registered dashboard "swift_falcon"
# …writes HERMES_DASHBOARD_OAUTH_CLIENT_ID to ~/.hermes/.env
```

**2. 在可访问的地址上运行 Dashboard。** 不带 `--insecure` 的非回环绑定会启用 OAuth 认证门，而刚刚写入的 `client_id` 会激活 `nous` 提供方：

```bash
hermes dashboard --host 0.0.0.0 --port 9119 --no-open
```

**3. 登录。** 打开 `http://<host>:9119/`，你会被弹到 `/login`。点击 **Sign in with Nous Research** → 在 Portal 完成认证 → 回到已认证的 Dashboard。可在任意机器上验证认证门：

```bash
curl -s http://<host>:9119/api/status | jq '.auth_required, .auth_providers'
# true
# ["nous"]
```

随后 `GET /api/auth/me` 会返回已验证的会话（`provider: nous`）。对于面向互联网的主机，请用 `--redirect-uri https://hermes.example.com/auth/callback` 注册，并设置 `HERMES_DASHBOARD_PUBLIC_URL`，让 OAuth 回调解析到你的公网 URL（参见[公网 URL 覆盖](#public-url-override)）。

### 用户名/密码提供方（无 OAuth IDP） {#usernamepassword-provider-no-oauth-idp}

如果你不想搭建 OAuth 身份提供方——也就是"只想给我的 Dashboard 加个密码"的自托管部署——内置的 `plugins/dashboard_auth/basic` 插件会注册一个名为 `basic` 的 `DashboardAuthProvider`，它使用**用户名和密码**认证，而不是 OAuth 重定向。

它接入的是与 OAuth 提供方相同的认证门：认证门在不带 `--insecure` 的非回环绑定上启用，登录页为该提供方渲染一个凭据表单（而不是"用 X 登录"按钮），而登录之后的一切——会话 cookie、透明刷新、WS 票据、登出、审计日志——都与 OAuth 路径完全一致。会话是提供方自行签发的无状态 HMAC 签名 token，因此**不需要数据库，也不需要外部 IDP**。密码哈希使用标准库的 `scrypt`（无第三方依赖）。

:::warning 仅在可信网络中使用——不要用于公网
用户名/密码提供方面向的是位于**可信网络**中、或仅能通过 **VPN** 访问的自托管 / 本地部署 / 家庭实验室 Dashboard。它只保护一份共享凭据，背后没有外部身份提供方、MFA 或按用户的账户，因此**不适合把 Dashboard 直接暴露到公网**。对于面向互联网的 Dashboard，请改用 [Nous Research 提供方](#default-provider-nous-research)（或你自己的[自托管 OIDC](#self-hosted-oidc-provider) / [自定义 OAuth](#custom-providers) 提供方）。
:::

#### 配置

与 Nous 提供方一样，它从 `config.yaml`（规范来源）读取，环境变量在非空设置时优先。只有当同时配置了 `username` 以及 `password_hash`（推荐）或 `password` 之一时它才会激活——否则它是空操作，因此 OAuth 用户和回环/`--insecure` 运维者不受影响。

**`config.yaml`：**

```yaml
dashboard:
  basic_auth:
    username: admin
    # 推荐——静态存储中不含明文。计算方式：
    #   python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('PW'))"
    password_hash: "scrypt$16384$8$1$…$…"
    # ……或者一个明文密码（加载时在内存中哈希；静态存储安全性较低）：
    # password: "s3cret"
    secret: "<32+ random bytes, base64 or hex>"  # token 签名密钥
    session_ttl_seconds: 43200                    # 可选；access token 生存期（默认 12 小时）
```

**环境变量覆盖：**

| 环境变量 | 覆盖 | 说明 |
|---------|-----------|-------|
| `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` | `dashboard.basic_auth.username` | 激活所必需 |
| `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` | `dashboard.basic_auth.password_hash` | 推荐（静态存储中不含明文） |
| `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` | `dashboard.basic_auth.password` | 明文；**优先于配置中的 `password_hash`**，因此可以通过环境变量轮换 |
| `HERMES_DASHBOARD_BASIC_AUTH_SECRET` | `dashboard.basic_auth.secret` | token 签名密钥 |
| `HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS` | `dashboard.basic_auth.session_ttl_seconds` | access token 生存期 |

:::caution 显式设置 `secret` 以获得稳定的会话
当 `secret` 为空时，会为每个进程生成一个随机签名密钥。对单进程来说这没问题，但这意味着**每次重启都会使所有会话失效**，且会话**无法跨多个 worker**。对于需要在重启后存活 / 多 worker 的部署，请显式设置 `secret`。
:::

`/auth/password-login` 端点按客户端 IP 限流（默认每分钟 10 次尝试 → HTTP 429），并且对未知用户和错误密码都返回同一个通用的 `401 Invalid credentials`，因此它无法被用作用户名枚举的探针。

#### 实例演练：用户名/密码

在可信网络上，从零开始三步得到一个带密码保护的 Dashboard。

**1. 在 `~/.hermes/.env` 中设置凭据。** 对密码做哈希，使静态存储中不留明文，并设置一个稳定的签名密钥，让会话在重启后依然有效：

```bash
# 计算你所选密码的 scrypt 哈希：
HASH=$(python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('choose-a-strong-password'))")

cat >> ~/.hermes/.env <<EOF
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH=$HASH
HERMES_DASHBOARD_BASIC_AUTH_SECRET=$(openssl rand -base64 32)
EOF
chmod 600 ~/.hermes/.env
```

**2. 在可访问的地址上运行 Dashboard。** 不带 `--insecure` 的非回环绑定会启用认证门，而用户名 + 哈希会激活 `basic` 提供方：

```bash
hermes dashboard --host 0.0.0.0 --port 9119 --no-open
```

**3. 登录。** 打开 `http://<host>:9119/`，你会被弹到 `/login`——那里是一个**凭据表单**（而不是"用 X 登录"按钮）。输入 `admin` / 你的密码 → 进入已认证的 Dashboard。可在任意机器上验证认证门：

```bash
curl -s http://<host>:9119/api/status | jq '.auth_required, .auth_providers'
# true
# ["basic"]
```

随后 `GET /api/auth/me` 会返回已验证的会话（`provider: basic`）。请把它放在 VPN 之后——参见上面的警告；面向公网的主机请改用 [Nous Research](#default-provider-nous-research) 或[自托管 OIDC](#self-hosted-oidc-provider) 提供方。

#### 编写你自己的密码提供方

`basic` 只是某个扩展点的一种实现。任何插件都可以注册一个密码提供方：在你的 `DashboardAuthProvider` 子类上设置 `supports_password = True`，并实现 `complete_password_login(*, username, password) -> Session`（拒绝时抛出 `InvalidCredentialsError`，后端存储不可用时抛出 `ProviderError`）。对于纯密码提供方，OAuth 的 `start_login` / `complete_login` 方法可以保留为 `NotImplementedError` 桩。这正是实现 LDAP bind、凭据数据库或任何其他非重定向认证方案的路径——表单、路由、cookie 和刷新都由框架替你处理。

### 自托管 OIDC 提供方 {#self-hosted-oidc-provider}

如果你运行着自己的身份提供方，内置的 `plugins/dashboard_auth/self_hosted` 插件会使用**标准 OpenID Connect** 对 Dashboard 进行认证——不需要针对每个 IDP 写代码，也不涉及 Nous Portal。它已针对任何符合规范的 OIDC 服务器验证并可正常工作：

> **Authentik · Keycloak · Zitadel · Authelia · Auth0 · Okta · Google · ……**

与 Nous 提供方一样，它会自动加载，并且只有在完成配置后才注册自己，因此对回环 / `--insecure` 的 Dashboard 而言它是空操作。

#### 配置

配置一个 **issuer** 和一个 **client_id**（一个公开的 PKCE 客户端——没有 client secret）。插件会从 `{issuer}/.well-known/openid-configuration` 获取 IDP 的 `authorization_endpoint`、`token_endpoint` 和 `jwks_uri`，因此你永远不需要硬编码端点 URL。

**`config.yaml`** —— 规范来源：

```yaml
dashboard:
  oauth:
    provider: self-hosted
    self_hosted:
      issuer: https://auth.example.com/application/o/hermes/   # 必需
      client_id: hermes-dashboard                              # 必需
      scopes: "openid profile email"                           # 可选（这是默认值）
```

**环境变量** —— 运维者覆盖项（非空设置时环境变量优先于 `config.yaml`；空值视为未设置）：

| 环境变量 | 覆盖 | 说明 |
|---------|-----------|-------|
| `HERMES_DASHBOARD_OIDC_ISSUER` | `dashboard.oauth.self_hosted.issuer` | OIDC issuer URL——必需 |
| `HERMES_DASHBOARD_OIDC_CLIENT_ID` | `dashboard.oauth.self_hosted.client_id` | 公开 client id——必需 |
| `HERMES_DASHBOARD_OIDC_SCOPES` | `dashboard.oauth.self_hosted.scopes` | 默认为 `openid profile email` |

在你的 IDP 中，注册一个使用授权码 + PKCE（S256）授权类型的**公开**应用/客户端，并把 Dashboard 的回调添加为允许的重定向 URI。回调地址是 `<Dashboard 公网 URL>/auth/callback`（Dashboard 在代理之后如何推导其公网 URL，参见[公网 URL 覆盖](#public-url-override)）。

#### 它验证了什么

该提供方会针对发现到的 `jwks_uri` 验证 OpenID Connect 的 **ID token**（RS256/ES256），并把 `iss` 和 `aud` 声明固定为你所配置的 `issuer` 和 `client_id`。标准 OIDC 声明按如下方式映射到 Dashboard 会话：

| 会话字段 | 声明 |
|---------------|----------|
| `user_id` | `sub`（必需） |
| `email` | `email` |
| `display_name` | `name` → `preferred_username` → `nickname` → `email` |
| `org_id` | `org_id` / `organization`，否则为拼接的 `groups` |

确立身份的是 ID token——access token 被当作不透明值处理（OIDC 规范并不要求它是 JWT）。端点 URL 必须是 HTTPS（本地开发 IDP 允许回环 `http://`），并且发现文档中公布的 `issuer` 必须与你配置的一致（末尾斜杠的差异可以容忍）。当 IDP 签发 refresh token 时，会通过标准的 `refresh_token` 授权用于静默重新认证；登出时，如果 IDP 公布了 RFC 7009 的 `revocation_endpoint`，则会调用它。

> **机密客户端**（带 `client_secret` 的那种）尚不支持——请配置一个公开 + PKCE 客户端，这也是面向浏览器的 Dashboard 的典型选择。

#### 实例演练：Keycloak

[Keycloak](https://www.keycloak.org/) 是最容易搭起来做本地测试的自托管 OIDC 服务器之一——它以 dev 模式作为单个容器运行（内存数据库），并提供教科书式的 OIDC 发现。本演练能让你在几分钟内从零得到一个可用的 Dashboard 登录。

**1. 用预置 realm 运行 Keycloak。** 把下面这份 realm 导出保存为 `realm-hermes.json`——它定义了一个 `hermes` realm、一个**公开 PKCE 客户端**（`hermes-dashboard`）和一个测试用户，全部在启动时导入，因此管理界面里无需点击任何东西：

```json
{
  "realm": "hermes",
  "enabled": true,
  "clients": [
    {
      "clientId": "hermes-dashboard",
      "name": "Hermes Agent Dashboard",
      "enabled": true,
      "publicClient": true,
      "standardFlowEnabled": true,
      "protocol": "openid-connect",
      "redirectUris": ["http://localhost:9119/auth/callback"],
      "webOrigins": ["http://localhost:9119"],
      "attributes": { "pkce.code.challenge.method": "S256" }
    }
  ],
  "users": [
    {
      "username": "testuser",
      "enabled": true,
      "emailVerified": true,
      "email": "testuser@example.com",
      "firstName": "Test",
      "lastName": "User",
      "credentials": [
        { "type": "password", "value": "testpassword", "temporary": false }
      ]
    }
  ]
}
```

启动它（Keycloak 26+），把该文件挂载到导入目录：

```bash
docker run --rm -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -v "$PWD/realm-hermes.json:/opt/keycloak/data/import/realm-hermes.json:ro" \
  quay.io/keycloak/keycloak:26.0 \
  start-dev --import-realm
```

启动完成后，该 realm 会在
`http://localhost:8080/realms/hermes/.well-known/openid-configuration` 提供标准
OIDC 发现（issuer 为 `http://localhost:8080/realms/hermes`）。管理控制台位于
`http://localhost:8080/`（`admin` / `admin`）。

**2. 让 Dashboard 指向它。** 自托管插件允许回环的 `http://` issuer（任何非回环 issuer 都必须是 HTTPS），因此本地 Keycloak 可以直接使用：

```bash
export HERMES_DASHBOARD_OIDC_ISSUER="http://localhost:8080/realms/hermes"
export HERMES_DASHBOARD_OIDC_CLIENT_ID="hermes-dashboard"
export HERMES_DASHBOARD_PUBLIC_URL="http://localhost:9119"
hermes dashboard --host 0.0.0.0 --port 9119 --no-open
```

`HERMES_DASHBOARD_PUBLIC_URL` 告诉 Dashboard 它的 OAuth 回调是
`http://localhost:9119/auth/callback`——也就是上面 realm 所注册的那个
重定向 URI。绑定到 `0.0.0.0`（非回环绑定）且不带 `--insecure`，正是启用
OAuth 认证门的原因。

**3. 登录。** 打开 `http://localhost:9119/`，你会被弹到 `/login`。点击 **Sign in with Self-Hosted OIDC** → 在 Keycloak 以 `testuser` / `testpassword` 完成认证 → 回到已认证的 Dashboard。侧边栏会显示 `Logged in as Test User via self-hosted`，并且 `GET /api/auth/me` 会返回已验证的会话（`provider: self-hosted`、`email: testuser@example.com`）。

> 如果你绑定或浏览的是不同的主机/端口，请在 Keycloak 管理控制台中把该来源的
> `…/auth/callback` 添加到该客户端的 **Valid redirect URIs**（Clients →
> hermes-dashboard → Settings）。同样的模式也适用于 Authentik、Zitadel、
> Authelia 和其他 OIDC 服务器——区别只在 issuer URL 和客户端注册界面。

### 公网 URL 覆盖 {#public-url-override}

默认情况下，Dashboard 会从请求中重建 OAuth 回调 URL——`X-Forwarded-Host` + `X-Forwarded-Proto` + `X-Forwarded-Prefix`（当 uvicorn 配置了 `proxy_headers=True` 时，而认证门下的 `start_server` 会启用它）。在能正确设置这三个头的反向代理之后，这可以开箱即用。

对于那些不能可靠转发这些头的反向代理部署（手工搭建的 nginx、本地部署的 ingress、代理链不完整的自定义域名部署），请把 `dashboard.public_url`（或 `HERMES_DASHBOARD_PUBLIC_URL`）设置为访问 Dashboard 所用的**完整公网 URL**：

```yaml
dashboard:
  public_url: "https://dashboard.example.com/hermes"
```

设置之后，OAuth 回调 URL 会原样变为 `<public_url>/auth/callback`——该代码路径会忽略 `X-Forwarded-Prefix`，因为运维者已经明确声明了公网 URL。这是有意为之：在前缀已经写进 `public_url` 的常见情形下，再叠加前缀会造成双重前缀。

优先级与其他 Dashboard 设置相同——环境变量优先于 `config.yaml`：

| 来源 | 覆盖路径 | 何时使用 |
|---------|---------------|-------------|
| `config.yaml` 中的 `dashboard.public_url` | `HERMES_DASHBOARD_PUBLIC_URL` | 本地开发 / 本地部署（规范来源） |
| `HERMES_DASHBOARD_PUBLIC_URL` 环境变量 | — | 托管平台密钥 / CI |
| （未设置） | — | 默认——从 `X-Forwarded-*` 头重建 |

校验会拒绝缺少 `http://` / `https://` 协议、缺少主机，或包含引号 / 尖括号 / 空白 / 控制字符的值。格式错误的值会静默回退到基于请求头的重建，从而让登录流程继续可用，而不是把用户送去一个恶意 URL。

> **注意：** `public_url` 只覆盖 OAuth 回调 URL。cookie 的 `Secure` 标志仍由 `request.url.scheme` 决定（在 proxy_headers 下即 X-Forwarded-Proto），因此在 TLS 终结的公网部署上使用 `http://` 的 `public_url` 会产生非 Secure 的 cookie。这是运维上的一个坑——请把 `public_url` 与上游正确的 TLS 终结搭配使用。

### OAuth 流程

该提供方实现了 [Nous Portal OAuth 契约 v1](https://github.com/NousResearch/nous-account-service/blob/main/docs/agent-dashboard-oauth-contract.md)——带 PKCE（S256）的授权码授权：

1. 用户在没有会话 cookie 的情况下访问 `/` → 认证门重定向到 `/login`。
2. 登录页显示一个 "Continue with Nous Research" 按钮 → `/auth/login?provider=nous`。
3. 服务器把 PKCE state 存入一个短生命周期 cookie，并将用户重定向到 `https://portal.nousresearch.com/oauth/authorize?…`。
4. 用户在 Portal 完成认证，落到 `/auth/callback?code=…&state=…`。
5. 服务器在 `POST /api/oauth/token` 用授权码换取 access token，针对 Portal 的 JWKS（`/.well-known/jwks.json`）验证 JWT 签名，并设置 `hermes_session_at` cookie。
6. 用户被重定向到 `/`（或通过 `next=` 查询参数回到原始的深链接路径）。

Access token 的 TTL 为 15 分钟。**契约 v1 中没有 refresh token**——token 过期时，SPA 的 fetch 包装器会检测到 401 信封，并整页跳转回 `/login` 重新走一遍流程。

### 设置的 Cookie

| 名称 | 生存期 | 说明 |
|------|----------|-------|
| `hermes_session_at` | Token TTL（15 分钟） | HttpOnly、SameSite=Lax、HTTPS 时 Secure |
| `hermes_session_pkce` | 10 分钟 | HttpOnly；在往返过程中保存 PKCE verifier + 提供方提示 |
| `hermes_session_rt` | v1 中未使用 | 为向前兼容预留；当 `refresh_token` 为空时不会写入 |

三者都是 `Path=/` 且 `SameSite=Lax`。当 Dashboard 通过 HTTPS 访问时会设置 `Secure` 标志（通过请求 URL 的协议检测——在 `proxy_headers=True` 下会遵循上游 TLS 终结器的 `X-Forwarded-Proto`）。

### 登出

侧边栏控件显示 `Logged in as <user_id…> via nous` 以及一个登出图标。点击它会向 `/auth/logout` 发送 POST 请求，清除所有 Dashboard 认证 cookie 并重定向回 `/login`。

### 审计日志

每一次登录开始、成功、失败以及会话校验失败，都会以 JSON 行的形式写入 `$HERMES_HOME/logs/dashboard-auth.log`。敏感字段（`access_token`、`refresh_token`、`code`、`code_verifier`、`state`、`Authorization` 头）在写日志前会被脱敏。

### 自定义提供方 {#custom-providers}

若要接入非 Nous 的 OAuth 提供方（例如 Google、GitHub、自定义 OIDC），请创建一个注册 `DashboardAuthProvider` 的插件：

```python
# ~/.hermes/plugins/dashboard-auth-myidp/__init__.py
from hermes_cli.dashboard_auth import DashboardAuthProvider, Session, LoginStart

class MyIdPProvider(DashboardAuthProvider):
    name = "myidp"
    display_name = "My Identity Provider"

    def start_login(self, *, redirect_uri): ...
    def complete_login(self, *, code, state, code_verifier, redirect_uri): ...
    def verify_session(self, *, access_token): ...
    def refresh_session(self, *, refresh_token): ...
    def revoke_session(self, *, refresh_token): ...

def register(ctx):
    ctx.register_dashboard_auth_provider(MyIdPProvider())
```

登录页会列出所有已注册的提供方；可以同时叠加多个提供方，由用户在 `/login` 处选择其一。

### 非交互式（bearer token）认证

除了交互式的人工登录（会话 cookie + 刷新）之外，`DashboardAuthProvider` ABC 还通过 `supports_token = True` + `verify_token(token=...)` 支持一种**非交互式的服务间**能力。当某个提供方选择支持它时，入站的 `Authorization: Bearer <token>` 会被验证，成功后会在请求上附加一个 `TokenPrincipal`（`request.state.token_principal`），供该提供方标记为可 token 认证的端点使用——没有 cookie，没有重定向，也没有刷新。

内置的第一个使用者是 **drain** 提供方（`plugins/dashboard_auth/drain`）：`nous-account-service` 通过 `HERMES_DASHBOARD_DRAIN_SECRET` 为每个 agent 下发一个密钥，提供方用常数时间比较来验证入站的 bearer token，并把 `/api/gateway/drain` 注册为可 token 认证的端点。它是**失败即关闭**的——弱/过短的密钥（< 256 位）在注册时会被拒绝，该端点保持禁用；当环境变量未设置时它是空操作。行为参数（`scope`、`min_secret_chars`）位于 `config.yaml` 的 `dashboard.drain_auth` 之下。

自定义提供方可以用同样的方式实现 `supports_token`/`verify_token`，以暴露它们自己的可机器认证端点。

### 验证认证门已开启

```bash
# 快速的环境变量方式。
HERMES_DASHBOARD_OAUTH_CLIENT_ID=agent:test \
  hermes dashboard --host 0.0.0.0

# 或者通过 config.yaml 的等价方式（推荐用于本地开发 / 本地部署）：
#
#   dashboard:
#     oauth:
#       client_id: agent:test
#
# 然后直接运行：
hermes dashboard --host 0.0.0.0

# 请求 /api/status 查看认证门状态：
curl -s http://127.0.0.1:9119/api/status | jq '.auth_required, .auth_providers'
# true
# ["nous"]
```

Dashboard 的 React StatusPage 在 "Web server" 下显示同样的字段。登录之后，侧边栏的 AuthWidget 会展示当前身份。

## 将 Hermes Desktop 连接到远程后端 {#connecting-hermes-desktop-to-a-remote-backend}

Hermes Desktop 可以驱动运行在另一台机器上的 Hermes 后端（一台 VPS、一台家庭服务器、一台在 Tailscale 之后的 Mini）。在应用中，这一功能位于 **Settings → Gateway → Remote gateway**，它会询问 **Remote URL** 以及**登录**方式。（关于桌面应用本身——安装、设置、聊天——请参阅 [Hermes Desktop](/user-guide/desktop) 页面。）

你用内置的某个认证提供方保护远程 Dashboard，桌面应用则针对后端所公布的那一个进行登录。对于超出你本机可访问范围的后端——VPS、公网主机、任何面向互联网的部署——推荐的提供方是 **OAuth（Nous Portal）**（用 [`hermes dashboard register`](#registering-a-dashboard) 注册，并用 *Sign in with Nous Research* 登录）。内置的[用户名/密码提供方](#usernamepassword-provider-no-oauth-idp)是后端位于可信局域网或仅能通过 VPN 访问时最快捷的选择，但**不适合直接暴露到公网**。把 Dashboard 绑定到非回环地址会启用它的认证门；登录之后，Desktop 会自动把该会话复用于聊天 WebSocket——没有任何 token 需要复制粘贴。

下面的配方使用用户名/密码路径，因为它在可信网络上搭建起来最快；OAuth 路径请参见[默认提供方：Nous Research](#default-provider-nous-research)。

### 在后端（远程机器）上

```bash
# 1. 在 ~/.hermes/.env（机密文件，0600）中设置 Dashboard 登录凭据。
cat >> ~/.hermes/.env <<'EOF'
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=choose-a-strong-password
# 推荐：设置一个稳定的签名密钥，让会话在重启后依然有效。
HERMES_DASHBOARD_BASIC_AUTH_SECRET=$(openssl rand -base64 32)
EOF
chmod 600 ~/.hermes/.env

# 2. 让 Dashboard 绑定到一个可访问的地址运行。非回环绑定会启用
#    认证门；用户名/密码提供方负责登录。
hermes dashboard --no-open --host 0.0.0.0 --port 9119
```

不想在静态存储中留下明文？请改用 `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` 配合 scrypt 哈希——完整配置项参见[用户名/密码提供方](#usernamepassword-provider-no-oauth-idp)。

如果你把 Dashboard 作为 systemd 服务运行，只要该 unit 带有 `EnvironmentFile=%h/.hermes/.env`，`~/.hermes/.env` 就会被自动读取，因此凭据在开机时便已存在于环境中。

:::warning
Dashboard 会读写你的 `.env`（API 密钥、机密）并且可以运行 agent 命令。这里演示的**用户名/密码**方案适用于可信网络——切勿把仅有密码保护的 Dashboard 直接暴露到开放互联网。请把它放到 VPN 之后。[Tailscale](https://tailscale.com/) 是干净利落的选择：绑定到机器的 tailscale IP（`--host <tailscale-ip>`），并用 `http://<tailscale-ip>:9119` 作为 Remote URL。只有你 tailnet 上的设备才能访问它。若要通过公网访问后端，请改用 **OAuth（Nous Portal）** 提供方。
:::

### 在 Hermes Desktop 中

**Settings → Gateway → Remote gateway：**

- **Remote URL** — `http://<backend-host>:9119`（如果你在前面加了反向代理，也支持 `/hermes` 这类路径前缀）
- **Sign in** — 应用检测到用户名/密码网关后会显示一个 **Sign in** 按钮；点击它并输入第 1 步中的凭据
- **Save and reconnect** — 把桌面外壳切换到远程后端

当后端设置了 `HERMES_DASHBOARD_BASIC_AUTH_SECRET` 时，会话会自动刷新并在重启后依然有效。

### 环境变量覆盖

除了应用内的设置之外，你也可以在启动桌面应用之前用环境变量指定后端。当设置了 `HERMES_DESKTOP_REMOTE_URL` 时，它会覆盖应用内保存的 URL（Gateway 设置面板会显示一个 "env override" 徽章并禁用编辑）；你仍然需要在面板中用用户名和密码**登录**。

| 环境变量 | 值 |
|---------|-------|
| `HERMES_DESKTOP_REMOTE_URL` | `http://<backend-host>:9119` |

### 故障排查

- **"Remote gateway incomplete"** —— 你还没有填写远程 URL。
- **登录失败并返回 401 / "Invalid credentials"** —— 用户名或密码与后端的 `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` 不匹配。后端对未知用户和错误密码返回同一个通用错误，因此请两者都检查。用 `curl -s http://<host>:9119/api/status | jq '.auth_required, .auth_providers'` 确认认证门——它应当报告 `true` 并包含 `"basic"`。
- **没有 "Sign in" 按钮——反而要求填写 session token** —— 用户名/密码提供方没有激活（`/api/status` 不会列出 `"basic"`）。请确认用户名和密码（或密码哈希）已设置，并且 Dashboard 进程确实加载了它们。
- **每次重启都被登出** —— 请把 `HERMES_DASHBOARD_BASIC_AUTH_SECRET` 设置为一个稳定值；否则签名密钥会在每次启动时重新生成。
- **连接被拒绝 / 超时** —— 后端绑定到了 `127.0.0.1`（默认值）而不是可访问的地址，或者防火墙/VPN 阻断了该端口。请绑定到 `0.0.0.0` 或 tailscale IP，并向你的可信网络开放该端口。

## CORS

Web 服务器将 CORS 限制为仅 localhost 来源：

- `http://localhost:9119` / `http://127.0.0.1:9119`（生产环境）
- `http://localhost:3000` / `http://127.0.0.1:3000`
- `http://localhost:5173` / `http://127.0.0.1:5173`（Vite 开发服务器）

如果你在自定义端口上运行服务器，该来源会自动添加。

## 开发

如果你要为 Web Dashboard 前端做贡献：

```bash
# 终端 1：启动后端 API
hermes dashboard --no-open

# 终端 2：启动带 HMR 的 Vite 开发服务器
cd web/
npm install
npm run dev
```

`http://localhost:5173` 上的 Vite 开发服务器会将 `/api` 请求代理到 `http://127.0.0.1:9119` 上的 FastAPI 后端。

前端使用 React 19、TypeScript、Tailwind CSS v4 和 shadcn/ui 风格组件构建。生产构建输出到 `hermes_cli/web_dist/`，由 FastAPI 服务器作为静态 SPA 提供服务。

## 更新时自动构建

运行 `hermes update` 时，如果 `npm` 可用，Web 前端会自动重新构建。这使 Dashboard 与代码更新保持同步。如果未安装 `npm`，更新会跳过前端构建，`hermes dashboard` 将在首次启动时构建。

## 主题与插件

Dashboard 内置八个主题，并可通过用户自定义主题、插件标签页和后端 API 路由进行扩展——全部即插即用，无需克隆仓库。

**实时切换主题**：点击顶部栏语言切换器旁的调色板图标。选择会持久化到 `config.yaml` 的 `dashboard.theme` 下，并在页面加载时恢复。

**独立更改字体**：在同一个选择器中——主题列表下方的 **Font** 区域会覆盖当前所用主题的 UI 字体。该选择在切换主题后依然保留（`config.yaml` → `dashboard.font`）；选择 **Theme default** 可清除它，回到当前主题自带的字体。

内置主题：

| 主题 | 特点 |
|-------|-----------|
| **Hermes Teal** (`default`) | 深青色 + 奶油色，系统字体，舒适间距 |
| **Hermes Teal (Large)** (`default-large`) | 与 default 相同，但使用 18px 文字和更宽松的间距 |
| **Nous Blue** (`nous-blue`) | Nous 品牌蓝色调，间距轻盈 |
| **Midnight** (`midnight`) | 深蓝紫色，Inter + JetBrains Mono |
| **Ember** (`ember`) | 暖深红 + 古铜色，Spectral 衬线体 + IBM Plex Mono |
| **Mono** (`mono`) | 灰度，IBM Plex，紧凑 |
| **Cyberpunk** (`cyberpunk`) | 黑底霓虹绿，Share Tech Mono |
| **Rosé** (`rose`) | 粉色 + 象牙色，Fraunces 衬线体，宽松 |

如需构建自定义主题、添加插件标签页、注入 shell 插槽或暴露插件专属 REST 端点，请参阅 **[扩展 Dashboard](./extending-the-dashboard)**——完整指南涵盖：

- 主题 YAML schema——调色板、排版、布局、资源、componentStyles、colorOverrides、customCSS
- 布局变体——`standard`、`cockpit`、`tiled`
- 插件 manifest、SDK、shell 插槽、页面级插槽（在不覆盖内置页面的情况下注入控件）、后端 FastAPI 路由
- 完整的主题加插件综合演示（Strike Freedom cockpit 示例）
- 发现、重载和故障排查
