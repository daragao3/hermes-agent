---
title: "Bot 模式"
description: "把你的 Hermes profile 变成一份具名 Bot 名单——每个 Bot 都有自己的聊天、角色、模型、记忆、skill 和头像。Bot 可以运行例行任务、共享群聊，并互相发送消息。"
---

# Bot 模式 {#bot-mode}

**Bot Mode** 会把你的 [Hermes profile](./profiles.md) 变成一份具名 **Bot** 名单。每个 Bot 都有自己的角色、模型、记忆、skill 和头像；Bot 可以运行周期性的例行任务、在群聊中共同商议，并直接互相发送消息。一个专精 Bot 只需构建一次，它就会永远在那里，一键可达。

Bot Mode **内置于[桌面应用](./desktop.md)**中，并且**默认开启**——无需安装。它在左侧边栏中以 Sessions 旁边的 **Bots** 标签页出现，当 Bots 标签页处于活跃状态时，会有一个 **Routines** 面板停靠在对话旁边。

:::tip Bot 就是一个 profile
不需要学习任何新概念：Bot **就是**一个 Hermes profile——位于 `~/.hermes/profiles/<name>/` 下的相互隔离的配置、记忆、skill、凭据和聊天历史。Bot Mode 是这一基础概念之上的 UI，因此你在其中做的一切在 CLI 中也都可见：`hermes -p <bot> chat` 会打开同一个 agent，Bot 的例行任务会出现在 `hermes cron list` 中。没有核心补丁，没有后台守护进程，也没有额外的存储。
:::

## Bots 面板 {#the-bots-pane}

名单为每个 agent profile 显示一行：头像、最新消息预览和时间戳。

- **点击一个 Bot** 即可进入它的聊天——每个 Bot 都有一个规范的、持久的 **Bot Chat** 对话，在 Bot 诞生的那一刻就会被创建（并置顶）。点击一行总是会打开那个 Bot Chat（即该行所预览的对话），即使你为该 Bot 打开了其他标签页；那些标签页会保留在它旁边。在标签栏中，Bot Chat 以 Bot 的名称作为标题，因此两个打开的 Bot 一眼就能区分。
- **Active now** —— 名单的活动筛选包括当前聚焦的实时轮次的所属者、在过去 90 秒内写过消息的 Bot，以及最近有 worker 心跳的 Bot。仅仅是 gateway 已连接并不意味着某个 Bot 正在工作。
- **搜索**会在你输入时筛选名单。
- **隐藏 Bot** —— 右键点击一行 → **Hide Bot**，即可把你不用的 Bot 从名单和 Active-now 条中移除。隐藏只影响显示：@mention 仍然能解析，群聊成员关系不受影响，例行任务也继续运行。一旦至少隐藏了一个 Bot，面板标题中就会出现一个**眼睛开关**——点击它可以让隐藏的 Bot 以变暗的形式原地显示，然后右键 → **Unhide Bot** 把它恢复。隐藏的 Bot 永远不会弹出提示，但它们会静默累积未读活动，眼睛图标上会显示一个圆点，让你知道发生了什么。隐藏状态保存在 Bot 的 profile 元数据中，因此它会跟随该 Bot 出现在连接到该后端的每一台桌面上。

:::note 规范的 Bot Chat 是一个永久聊天
在 Bot 的规范聊天中输入 `/new`（或 `/reset`）会把这段关系分叉成一个临时会话——而这正是 Bot Mode 承诺永远不会发生的事。输入框会把它改为 `/compact`：全新的工作上下文，同一个对话。同一 profile 上的普通会话仍然可以完全自由地使用 `/new`。
:::

### 将 Bot 组织到分区中 {#organize-bots-into-sections}

分区是你自己创建的文件夹——**Clients**、**Team**，任何合适的名称——作为自动按 gateway 分组之外的第二个维度。没有创建任何分区时，名单就是一如既往的普通列表。

- **创建分区**：通过面板的 **+** 菜单 → **New section**，或右键点击一个 Bot → **Move to section** → **New section…**（这会在创建分区的同时把该 Bot 归入其中）。
- **归档 Bot**：把它的行拖到某个分区上——悬停时目标会高亮，按 **Esc** 取消拖动——或右键 → **Move to section** 并选择一个分区。**Remove from section** 会把它放回 **Unassigned**。
- **重命名、重新排序或删除**分区：通过其标题的右键菜单（或悬停时出现的 **⋯**）；双击标题即可重命名。标题可以像 gateway 标题一样折叠。
- **删除分区永远不会删除 Bot** —— 它们会回到 **Unassigned**，提示中会提供 **Undo**。不会要求确认。

成员关系存储在每个 Bot 的 profile 元数据（`ui_meta`）中，因此 Bot 的分区会跟随它出现在连接到该后端的每一台桌面上。当名单显示多个 gateway 时，分区会嵌套在每个 gateway 的分组内。

## 创建 Bot {#creating-a-bot}

在名单中点击 **New Agent**。快捷路径只有三个字段——**Name**、**Title**、**Description**——几秒钟内 Bot 就会创建完成，并在其新 Bot Chat 的第一条消息中进行自我介绍。

**Advanced** 展开项会打开完整的能力配置界面：

- **从现有 profile 克隆** —— 以另一个 Bot 的配置、skill、SOUL 和记忆为起点，或选择 **Fresh profile** 从零开始。
- **Create empty** —— 完全跳过内置 skill，得到一个最小化的 profile。
- **固定模型与 provider** —— 给 Bot 指定它自己的模型。Hermes 所知的任何 provider/model 组合都可以使用，不同的 Bot 可以并排运行在不同的模型上。不设置则继承启动 profile 的设置。
- **自定义 SOUL.md** —— Bot 的人设和常驻指令。
- **按 skill、按工具集、按 MCP 服务器启用** —— 精确勾选这个专精 Bot 需要的能力。
- **共享密钥** —— 默认情况下，新 Bot 与主 profile 共享同一个 OAuth/token 池，因此凭据刷新不会相互失效。（较旧的 gateway 则会复制凭据——仍然可用，只是分叉了。）

### 选择它所在的机器（"Create on"） {#choosing-which-machine-it-lives-on-create-on}

当 [Settings → Connections](./multi-connection-desktop.md) 中注册了多个连接时，New Agent 对话框会多出一个 **Create on** 选择器。选择一台设备，profile 就会在**那台**机器的后端上创建——你的窗口永远不会切换 gateway。新 Bot 随后会作为 Connections Bot 出现在名单中（当该名称存在于多台机器上时，带有 `@name-device` 句柄），与它聊天会路由到它自己的机器。

只有一个连接时（常见情况），选择器会被隐藏，Bot 会创建在你当前连接的机器上——与以前的行为完全一致。

远程创建说明：

- **克隆来源**是*目标*机器上的 profile（其 `default`）——远程机器上并没有你的本地 profile 可供克隆。
- 实时的 Capabilities 标签页会固定到目标机器的后端，因此你在创建期间配置的 skill、工具和 MCP 服务器会落到 Bot 将要驻留的机器上。（较旧的桌面版本对远程目标会回退到分阶段的 Skills/Tools/MCP 清单；两者读取的都是目标机器的目录。）
- 取消对话框会丢弃在相应机器上创建的草稿 profile。

**Edit Profile**（右键点击 Bot）随时都会在该实时 profile 上重新打开同一界面：头像、标题、描述、固定模型、skill、工具集、MCP 服务器以及完整的 SOUL.md。

**Duplicate**（右键）会完整克隆一个 Bot——配置、skill、SOUL.md、记忆以及外观。**Delete Profile** 会永久删除一个 Bot，需经过与桌面 profile 菜单相同的破坏性操作确认；默认 profile 不能被删除。

## 头像 {#avatars}

每个 Bot 都有一张脸：

- **Blob 脸**（默认）—— 根据 Bot 名称确定性生成的软体脸：同一名字，永远是同一张脸。在 New Agent 中输入名字时，脸会实时跟随变化；点击 **Randomize** 重新随机，点击 **Lock face** 保留你喜欢的那张脸（即使名字改变），或者固定六种轮廓之一（round、organic、boxy、nub、cloud、sun），其余一切仍由名字决定。
- **几何脸** —— 经典的 7 种形状 × 10 种颜色。在聚焦的实时轮次中，所属的 Bot 会前倾并向上看，伴随三个动画圆点，轮次结束后再缓缓回到空闲状态。所属关系包含连接信息，因此不同 gateway 上的同名 Bot 不会借用这个姿态。后台 worker 保留其原有的工作动画；照片、blob 脸和徽记保持各自的渲染方式。
- **上传的图片** —— 任何你喜欢的图片。
- **AI 生成的肖像** —— 配置了图像后端时就地生成（这使用标准的 `image.generate` RPC，在本地和远程 gateway 上都可用）。
- **像素宠物** —— 来自 [petdex 图鉴](./features/pets.md)的伙伴，在 Bot 忙碌时会在头像旁边蹦跳。在终端中运行 `hermes pets` 即可浏览图鉴。

Bot 的外观、标题和描述存储在后端的 profile 元数据中，因此同一个 Bot 在连接到该后端的每一台桌面上都以相同的样子出现。

## 例行任务 {#routines}

**Routines** 面板把周期性任务附加到执行它们的 Bot 上——“每天早上汇总我的收件箱”就放在负责它的 Bot 旁边。该面板只在 Bots 标签页活跃时停靠在聊天旁边，切回 Sessions 时会让开（较旧的桌面版本则始终显示它）。一个结构化的日程选择器用于构建日程（先选频率，然后只填写真正相关的细节），另有一个 Advanced 字段暴露原始的 Hermes 日程字符串。

例行任务就是普通的 [Hermes cron 任务](./features/cron.md)，其命名空间为 `[bot:<name>] <routine>`——它们也会出现在 `hermes cron list` 和核心 Cron 页面中。运行结果会写入 Bot 自己的聊天历史，因此结果正好出现在你本来就会与该 Bot 交谈的地方。

## 分组与群聊 {#groups-and-group-chats}

右键点击一个本地 Bot → **Manage groups**，即可把它加入或移出任意数量的群聊。可以单独挑选现有的群组，或就地新建一个。本地成员关系存储在 Bot 的与后端同步的 profile 元数据中，因此它会跨桌面跟随该 profile；带有一个旧版群组的旧 profile 仍可继续工作。Connections Bot 通过 New Group Chat 选择器加入，并在房间的共享状态中保持来源限定。

**房间跟随你的 gateway，而不是某一个 Desktop。** 每个房间最近的聊天记录、成员、图片和名称都会被镜像到你的 Desktop 所连接的**每一个** gateway 的共享 profile 元数据中，并带有按 gateway 区分的版本控制，因此两个 Desktop 同时写入时会合并而不是互相覆盖。在另一台机器上针对同一个 gateway 打开 Hermes Desktop（局域网、Tailscale、任何地方），房间就会连同其历史一起出现；仅连接 gateway 的客户端也能看到。房间带有一个持久的内部身份，因此重命名只会在所有地方改变其显示名称，解散一个房间会在每个客户端上永久移除它——即使是当时处于离线状态的客户端——而重新创建一个同名群组会开启一个真正全新的房间。如果某个 gateway 宕机或被移除，也不会丢失任何东西：每个已连接的 Desktop 都在本地保留完整的房间，并会把它重新播种到重新连接的任何 gateway 上。（完整的编排日志保存在每个 Desktop 的本地存储中；共享镜像只是一个有上限的近期历史投影。）

群组是与 Bot 私聊处于同一个按活动排序名单中的独立行。即使一个 Bot 属于多个群组，它也只保留一个私聊行，而每个群组都有自己的房间行，显示成员数、最新消息预览、时间戳以及需要你处理的状态。

使用房间旁边的 **Move up** 和 **Move down** 箭头来选择它在房间中的位置。在第一次移动之前，现有的“置顶优先、按最近活动排序”的顺序保持不变。移动之后，房间顺序会保存在这台 Desktop 上并在重新加载后保留；新房间会排在其所在置顶或非置顶区段中已显式排序的房间之后。移动不能跨越置顶边界，筛选也不会把隐藏的房间从已保存的顺序中丢弃。这些控件重新排序的是实际的 Group Chat 房间，而不是用户创建的 Bot 文件夹，也不会改变成员关系或 gateway 归属。

在任意群组行（2–6 个 Bot）上点击 **Open chat**，会打开一个共享房间，整个群组在其中协作：

- **一个可见的对话。** 公开消息和每个成员的回复都按到达顺序保持可读，并附有发言者的名称和时间戳。开启另一个话题不会折叠之前的回复。**Reply in thread** 会继续该话题而不重新排列房间；**Activity** 是一个辅助的状态视图，而不是消息的替代品。私人 Bot Chat 保持独立。
- 你的消息最多触发**三轮串行**的成员轮次。被 @ 提及的 Bot 会回应（没有人被提及时所有人都回应）；每个 Bot 简短回复或跳过，当一整轮都保持沉默时房间就会平息下来。
- Bot 用 `@name` 互相拉入对话，并用 `@user` 把真正需要判断的问题上报给你——发生这种情况时，群组行会显示一个 **needs you** 徽章。待处理的问题和命令审批也会点亮该徽章；解决最后一个提示只会清除提示类的关注，而不会清除独立的提及。提示会跟随重命名后的房间，而解散房间会使它们失效，即使某个成员正在进行的轮询稍后才到达。
- 硬性上限（每次发送 10 条消息、3 轮）可以防止房间无休止地空转。
- 每个成员都保有自己持久的 `Group: <name>` 会话，因此房间上下文会像其他任何对话一样保留下来。
- **并非每个 Bot 都会回复每条消息。** 发言是每个成员自己的选择——Bot 只在有新内容可补充时才回复，否则就跳过；@ 提及特定成员会把这一轮限定在他们身上。预期你点名的成员（或有话要说的成员）会发言，其余的保持安静。
- **关闭 Desktop 后房间仍会继续运行。** 当一个房间的所有成员都在同一个 gateway 上时，该 gateway 会通过一个持久的驱动器负责轮次调度：关闭 Hermes Desktop（或失去连接）不会让房间在讨论中途停下，Desktop 重新连接时只需从房间日志中追上进度即可。在这种情况下，gateway 上的 `groups.capabilities` 会报告 `driver: true`。成员分布在多台机器上的房间则不同：每个成员的轮次在它自己的 gateway 上运行，并且 *Bot 之间的消息* 中描述的跨连接信使机制仍然适用于它们。
- **房间可以跨越机器。** New Group Chat 选择器可以安排来自任何已注册连接的 Bot 入座；每个成员的轮次都在它自己的机器上、在那里它自己的 `Group: <name>` 会话中运行。跨机器的成员在房间中和其他成员的聊天记录中都带有设备徽章（`dixie · Mac Mini`），消歧后的 `@name-device` 句柄可以在房间提及中使用——因此两台机器上的同名 agent 永远不会混为一谈。

## Bot 之间的消息 {#bot-to-bot-messaging}

Bot 之间会带着署名互相发送消息，你也可以从任何聊天中移交工作：

- **@mention** —— 在任意聊天中输入 `@researcher have a look at this`，输入框的 `@` 自动补全会帮你挑选正确的 Bot；发送时，该提及会对照实时名单进行解析，活跃的 Bot 会被准确告知你指的是谁（profile、友好名称，以及跨连接 Bot 的设备）。随后 Bot 会自己撰写消息并用 `message_agent` 发送——你的文字永远不会被逐字转发，回复会以该 agent 的署名返回。电子邮件地址或未知的 `@` 会原样通过。其他已连接机器上的 Bot 也可以用同样的方式联系到：Desktop 会通过该连接自己的套接字中继消息（见下文 *跨机器的 Bot*）。
- **重命名的 Bot 会保持标签同步** —— 给 Bot 一个友好名称（其聊天标题中的铅笔图标，或 `hermes profile rename`），它就可以用该名称被标记：标题为 *Research Buddy* 的 Bot 会响应 `@research-buddy`（以及 `@researchbuddy`），在普通聊天和群聊房间中都一样。输入框的 `@` 自动补全会提供重命名后的标签，并且在你输入旧 profile 名称时也能匹配，旧名称同样可以继续解析。
- **私信** —— 每个 Bot Chat 都带有 `message_agent` 工具：Bot 通过调用 `message_agent(target="researcher", message="…")` 给队友发消息。该工具会对照实时名单校验目标，自动加上发送者的 `Message from 🤖 <sender> (@<sender>):` 署名前缀，并投递到队友的规范 Bot Chat 中。投递是**发出即不管**的：发送者会收到一个确认，完成它的轮次，回复稍后会以后台完成通知的形式到达。消息作为真正的参数传递（不经过任何 shell 解释——引号、`$(...)` 和反引号都会原样到达），并且 Bot 会自己撰写消息，而不是转发你的原话。队友名单——来自每个 profile 标题/描述的名称**和角色**——是每个 Bot Chat 系统 prompt 的一部分，因此 Bot 在选择收件人之前就知道谁负责什么。该工具**只**存在于 Bot-Mode 管理的安装中的规范 Bot Chat 会话里；普通聊天、群聊房间成员会话和 CLI 会话永远看不到它。

本地消息也能送达在 Desktop 或 TUI 中保持打开的 Bot Chat。接收方后端保持归属权：它通过现有的通知轮询器读取持久的入口消息，空闲时立即接纳，否则会等到正在运行的轮次以及已排队的人类 prompt 完成。`queued` 确认表示已被持久接纳，**而不是**已完成回复。目标 profile 会在 `runtime/bot_live_delivery/` 下保留投递 ID 和回执；`settled` 表示已完成。崩溃或被取消的导入轮次不会自动重放，而固定到已离开的所属者的待处理工作会保持可检查状态，而不是被静默地重新运行。不要重新发送结果未知的投递。不具备实时投递能力的旧后端会保留现有的归属拒绝行为；升级后请重启该后端。

后端会在构建 prompt 时自动向每个 Bot 的规范 Bot Chat 会话传授消息协议——包括队友从 CLI 以无界面方式打开它的情况。只有规范 Bot Chat 会获得协议部分；你的普通会话和 SOUL.md 保持不变。这由 `config.yaml` 中的 `agent.bot_mode_protocol` 控制（默认：开启）：

```yaml
agent:
  bot_mode_protocol: true   # 将 bot 之间的消息协议注入规范 Bot Chat
```

:::note
Bot 之间的投递是按调用进行的：接收方 Bot 会在下一次运行时获取消息。在对话进行中实时打断 Bot 是未来的工作。
:::

### 失败的轮次会安全重试 {#failed-turns-retry-safely}

本地一次性投递会把活跃会话的拒绝代码与其人类可读的消息分开保留。
`SESSION_NOT_OWNED` 会产生 `target_busy`；无法读取的协调注册表不会被误标为
另一个所属者。不带代码标记的旧版本地 CLI 仍然使用历史上的拒绝措辞。

失败的投递轮次最多重试一次，并且只在重试确实有帮助时才重试。暂时性故障（目标运行时离线、投递超时、provider 限流或服务器错误）会原封不动地重新运行同一个 Bot Chat 会话。上下文溢出故障也会重新运行同一个会话——重试的轮次会在调用模型之前，通过标准的上下文压缩流程压缩超出阈值的聊天记录，因此原本放不下的内容在重试时能够放下。认证、配额和配置故障永远不会自动重试：第二次尝试无法修复它们，只会白白消耗配额，因此故障会被立即呈现。重试的轮次永远不会开启新会话——你的 Bot Chat 历史和上下文保持完好。

### 投递失败时：类型化的原因 {#when-a-delivery-fails-typed-reasons}

失败的 bot 轮次或中继投递会端到端地在人类可读的错误文本之外携带一个机器可读的 `reason` 代码：目标 gateway 对故障进行分类（`provider_auth_or_access`、`provider_quota_limit`、`provider_rate_limit`、`provider_server_error`、`context_overflow`、`missing_config`、`model_unavailable`、`runtime_offline`、`queued_expired`、`delivery_timeout`、`target_busy`、`unknown`），Desktop 转发它，发送方 agent 的完成通知会在错误文本前标注 `[reason: <code>]`。调用方 agent 可以根据该代码分支处理——“重新登录”还是“稍后重试”——而无需解析 provider 的文字描述。Desktop 的需要关注徽章使用相同的代码。

### 跨已连接机器的消息（Desktop 中继） {#messaging-across-connected-machines-the-desktop-relay}

你在 **Settings → Connections** 中注册的每一个 gateway——本地、远程 URL、SSH、Hermes Cloud、docker——都是 Desktop 保持打开的一条持久线路，Bot Mode 会自动利用这些线路收发消息。无需额外配置：

- **名单会自行传播。** Desktop 运行期间，会定期告诉每个已连接的 gateway 哪些 agent 位于*其他*连接上。每个 Bot Chat 的队友名单随后都会列出它们（"Teammates on OTHER connected machines"），附带名称、角色以及它们所在的机器——当 agent 出现、消失或被重命名时，名单会刷新（能力纪元）。
- **`message_agent` 可以直接联系到它们。** 你笔记本上的 Bot 用 `message_agent(target="moxie", …)` 给云端 agent 发消息，与给本地队友发消息完全一样。如果同一个句柄存在于多台机器上，用 `target="moxie@<connection>"` 消歧（工具的错误信息会告诉 Bot 确切的格式）。投递依托于 Desktop：发送方 gateway 把消息排队，Desktop 把它中继到目标连接自己的 gateway，目标 Bot 在其规范 Bot Chat 中运行一个轮次，回复则以与本地私信相同的后台完成通知形式返回给发送方。
- **Desktop 就是信使。** 跨连接投递只在一个同时知道两个连接的 Desktop 正在运行时才有效（它持有套接字和凭据——gateway 之间永远看不到彼此的认证信息）。如果 Desktop 在投递中途被关闭，发送方 Bot 会被告知回复未送达，而不是一直悬而未决。若要进行无需 Desktop 参与、始终在线的机器间消息传递，请注册一个 peer（`hermes peer`，见下文）——两条路径可以共存。

### Bot 发起的跨机器私信（`hermes peer`） {#bot-initiated-dms-across-machines-hermes-peer}

一台机器上的 Bot 可以在没有任何桌面参与的情况下，给**另一台机器的 gateway** 上的 Bot 发消息。将另一个 gateway 注册为 *peer*（其 API 服务器 URL + `API_SERVER_KEY`）：

```bash
hermes peer add spark --url http://spark.lan:8377 --key <API_SERVER_KEY>
hermes peer list
hermes peer dm spark < /tmp/dm.txt        # 消息正文来自文件（不经任何 shell 解释）
hermes peer dm spark/researcher < /tmp/dm.txt   # 多路复用 peer 上的具名 profile
hermes peer run spark --idempotency-key ticket-123 < /tmp/long-task.txt
hermes peer status spark run_abc123
hermes peer stop spark run_abc123
```

`hermes peer dm` 通过 peer 现有的 API 服务器投递到远程 agent 的规范 Bot Chat 中，在那里运行一个 agent 轮次，并把回复打印到 stdout——正是本地 `hermes -p <bot> chat` 命令的跨机器孪生版本。

`peer dm` 只用于简短的查询和回执，因为它会一直占用一个 HTTP
连接直到轮次结束。对于较长的轮次，`peer run` 会立即返回一个
`run_id`；用 `peer status` 轮询它。该运行会继承规范 Bot Chat 的聊天记录，
而稳定的 `--idempotency-key` 会让重试返回原先的运行，而不是开启重复的工作。
使用 `peer stop` 加上那个确切的运行 ID 即可中断它，而不会波及其他轮次。

一旦注册了 peer，传授给每个 Bot Chat 的消息协议（`agent.bot_mode_protocol`）就会自动包含 peer 名单，并且 `message_agent` 可以直接接受 peer 目标——`message_agent(target="spark/researcher", …)`，或用 `target="spark"` 指向该 peer 的主 agent——因此**你的 bot 会自己了解到**其他机器上也有队友，以及如何联系他们。注册或移除 peer 会在下一条消息时刷新每个 Bot Chat 的协议（能力纪元）。

要求：peer 机器运行 `api_server` gateway 平台，并配置强 `API_SERVER_KEY`；可达性由你的网络负责（局域网、Tailscale、VPN）。该密钥是凭据，以 `HERMES_PEER_<NAME>_KEY` 的形式存放在 `~/.hermes/.env` 中；peer 的名称/URL 存放在 `config.yaml` 的 `bot_peers` 下。

:::note 单向可达性（NAT）
跨 gateway 链接是 gateway 与 gateway 之间的直接连接——Desktop 只是
查看者，不是中继。位于家庭 NAT 之后的 gateway 可以主动连接公网上的 peer
（笔记本 → VPS 可行），但反方向没有入站路由
（VPS → 家中 失败），除非你的网络提供了这样的路由。如果你的 Group Chat 跨越了
NAT 边界，请把房间的主导权放在每个参与者都能访问的主机上
（通常是公网 VPS），或者用 Tailscale/VPN 打通网络。
:::

### 转移托管房间的主导权 {#transferring-hosted-room-authority}

主导权接管是一个**运维恢复流程**，而不是一次原子性的交接。
请在相应的 gateway 上使用现有的 JSON-RPC 方法 `groups.promote` 和 `groups.demote`。
不存在 `groups.peer.promote` 或 `groups.peer.demote`
方法；`groups.capabilities` 会列出你的 gateway 支持的方法。

:::warning 提升前先隔离旧的写入方
在发送 `confirm: true` 之前，先确认之前的主导方**无法提交**，
并在它被降级之前一直保持该隔离措施。停止其写入房间的进程并阻止自动重启，
或使用等效的基础设施隔离手段。网络超时、断开 Desktop 或 `groups.stop`
都不能作为证明：旧 gateway 可能仍在运行，而停止一个轮次并不会撤销房间主导权。
如果你无法建立隔离，就不要提升。
:::

1. **检查副本覆盖范围。** 在替代 gateway 上，用 `{"room_id":"ROOM_ID"}` 查看
   `groups.replica_state`，并比较 `last_seq`
   与 `latest_seq`。计划内接管之前要求副本完整；
   提升操作本身不会检查这一覆盖范围。`groups.replicate` 在摄取 `groups.log`
   返回的页面后会报告 `caught_up`；仅注册 peer 并不能证明替代方拥有房间历史。
   已追上的状态描述的是最后复制的页面，并不能证明旧写入方已经停止，也不能证明
   不存在更新的事件。对于计划内迁移，先让写入方静止，复制到最终游标，然后保持
   隔离。对于灾难恢复，要考虑到那些从未到达副本的历史。
2. **只在旧写入方被隔离时提升。** 在替代 gateway 上：

   ```json
   {"jsonrpc":"2.0","id":1,"method":"groups.promote","params":{"room_id":"ROOM_ID","confirm":true,"reason":"planned-handover"}}
   ```

   `room_id` 和 `confirm: true` 是必需的；`reason` 可选，默认为
   `authority-unreachable`。确认是你对“之前的主导方无法提交”的断言，
   **而不是**请求自动隔离它。没有确认时，调用会返回错误 `4118`。
   成功的结果会报告 `authority_gateway_id` 和 `authority_epoch`（复制的纪元加一）。
3. **在旧主导方恢复服务之前将其降级。** 在旧 gateway 上通过一个受控的恢复连接
   执行此 RPC 期间，保持其常规房间写入方处于隔离状态。将示例中的 gateway ID
   和纪元替换为成功提升时返回的确切值：

   ```json
   {"jsonrpc":"2.0","id":2,"method":"groups.demote","params":{"room_id":"ROOM_ID","observed_gateway_id":"NEW_GATEWAY_ID","observed_epoch":2}}
   ```

   三个参数都是必需的。不要猜测未来的纪元：降级需要存在更新主导方的证据，
   而不是一个编造的值。它会记录 `authority.lost` 并采用所观察到的谱系；重复同一
   谱系是幂等的。如果旧主机不可用，就保持它的隔离状态，并在恢复其常规写入方
   之前执行这一步。
4. **验证并重新连接。** 在两个 gateway 上读取 `groups.state`，并将
   `room.authority_gateway_id` 和 `room.authority_epoch` 与提升结果进行比较。
   旧主导方的发送必须被拒绝；把客户端引导到替代 gateway。
   降级会隔离写入；它不会合并历史，也不会自动把旧的权威存储变成一个同步的副本。

在旧 gateway 仍可写入时进行提升，会让两个独立的
`state.db` 存储都接受消息，并形成分叉的历史。替代方上更高的纪元并不会远程
禁用旧写入方；脑裂并不需要纪元相等。如果历史已经分叉，请隔离写入方并保留
两份历史以供恢复，而不要假设提升、降级或重放会把它们合并。

## 跨机器的 Bot {#bots-across-machines}

当你在 **Settings → Connections** 中注册了多个后端——本地运行时、远程 gateway、SSH 主机、Hermes Cloud 实例——名单会持久地显示来自**每一个**已连接来源的 Bot：SSH 来源的盘点不会在远程机器上派生任何东西，暂时无法访问的机器会保留其最后已知的行而不是消失。当同一个 profile 名称存在于多个来源上时，句柄会以 `@name-device` 形式消歧（例如 `@research-homelab`）。Bot 的聊天、会话、记忆和例行任务都存放在拥有该 profile 的机器上。

点击一个 Connections Bot **不会**让你的窗口跳到那台机器上——留在你的聊天中 `@mention` 它、把它安排进群聊，或者用 **Create on** 选择器直接在它上面创建新 agent。云端和本地 agent 以这种方式共享一份名单：注册你的 Hermes Cloud 实例和你的桌面（比如通过 Tailscale 或 SSH），它们的 Bot 就可以互相发消息并坐在同一个房间里，每个 agent 的工作都在它自己的机器上运行。这些机器之间的 Bot 私信会自动经由 Desktop 中继（见上文 *跨已连接机器的消息*）。

完整的多连接指南参见[将桌面应用连接到多个 Hermes 实例](./multi-connection-desktop.md)。

## 关闭它 {#turning-it-off}

Bot Mode 是一个内置的桌面插件。在 **Settings → Plugins → Bots** 中关闭它——名单、Routines 面板和输入框中间件会实时注销，无需重启。无论开关与否，你的 profile、会话和 cron 任务都不受影响；Bot Mode 从不拥有你的数据，它只负责渲染数据。

还有一个偏好设置，可以把规范 Bot Chat 从常规侧边栏的会话列表中隐藏，让它们只出现在 Bots 面板中。（这使用核心的隐藏会话标志；在较旧的 gateway 上这些聊天会保持可见。）

## CLI 对应关系 {#cli-parity}

因为 Bot 就是 profile，所以一切都有对应的终端操作：

| 在 Bot Mode 中 | 在 shell 中 |
| --- | --- |
| 与 Bot 聊天 | `hermes -p <bot> chat` |
| Bot 的文件、skill、记忆 | `~/.hermes/profiles/<bot>/` |
| 例行任务 | `hermes cron list`（名为 `[bot:<name>] …` 的任务） |
| 创建 / 查看 profile | `hermes profile create`、`hermes profile list` |

底层概念参见 [Profiles](./profiles.md)，完整的 CLI 参考参见 [Profile 命令](../reference/profile-commands.md)。
