---
sidebar_position: 5
title: 将桌面应用连接到多个 Hermes 实例
description: "在一个桌面应用中注册本地、局域网、SSH 和 Hermes Cloud 后端，并同时使用它们"
---

# 将桌面应用连接到多个 Hermes 实例 {#connecting-desktop-to-many-hermes-instances}

把你拥有的每一个 Hermes 后端——本地运行时、位于局域网或 VPS 上的远程 gateway、
SSH 主机以及 Hermes Cloud 实例——注册到同一个桌面应用中，并同时使用它们上面的
agent。连接是持久的：每个已注册的 gateway 会按需连接自己的后端和 WebSocket，
当你查看另一个 gateway 时，后台 agent 仍会持续流式输出。

这是[同时运行多个 Gateway](./multi-profile-gateways.md) 在桌面端的补充：那一页讲的
是在一台机器上托管多个 gateway；本页讲的是一个桌面应用与多台机器通信。

## 在哪里找到它 {#where-to-find-it}

所有内容都位于统一的 **设置 → Gateways** 页面（较旧的版本有独立的
**Gateway** 和 **Connections** 页面；旧的 Connections 深层链接会重定向到这里）。
有三个入口可以到达：

- **设置 → Gateways** —— 页面本身（**Cmd/Ctrl+,**，然后在设置导航中选择
  **Gateways**）。连接注册表是该页面中的一个区域，位于机器级连接模式控件下方。
- **侧边栏 profile 导轨** —— 导轨右端的插头按钮
  （提示文字：**"Connect another Hermes gateway…"**）会直接深层链接到
  Gateways 页面。它始终可见，即便你还没有创建第二个 profile 或第二个连接。
- **命令面板** —— **Cmd/Ctrl+K**，然后输入 *Gateways*（也能匹配
  *connections*、*add gateway*、*remote*、*ssh*、*instances*）。

## Gateway 注册表 {#the-gateway-registry}

**设置 → Gateways** 中的 **Registered gateways** 区域管理着一份具名的 Hermes
gateway 列表。其简介说得很直白：*"Manage this device and every Hermes gateway
it can reach through remote, SSH, or Cloud connections."*
每个条目都是一个*连接*：

| 类型 | 它是什么 | 认证 |
|---|---|---|
| **Local** | "The Hermes runtime managed by this app."（由本应用管理的 Hermes 运行时） | 自动 |
| **Remote gateway** | "A Hermes gateway reachable over HTTP(S) — LAN, Tailscale, or the internet."（可通过 HTTP(S) 访问的 Hermes gateway——局域网、Tailscale 或互联网） | session token 或 OAuth |
| **SSH** | "A Hermes install reached over SSH."（通过 SSH 访问的 Hermes 安装）应用会为你打开隧道并启动仪表盘 | SSH 密钥 + 接管的 token |
| **Hermes Cloud** | "A hosted instance discovered through your Hermes Cloud account."（通过你的 Hermes Cloud 账户发现的托管实例） | 门户登录 |

值得了解的规则：

- **每个连接都需要一个唯一的设备名**（"Homelab"、"Work laptop"）。
  该名称会出现在实例出现的每一个地方——名单徽章、句柄、更新结果。
  唯一性不区分大小写，因此 `Homelab` 和 `homelab` 不能共存。
- **local** 条目由应用管理（它带有 **App-managed** 标签），不能被移除。
  移除任何其他连接会拆除其活跃的后端和隧道；实例本身不受影响。
- 始终有一个连接是 **Primary**（其所在行带有标签）：对于没有指定 gateway 的
  多 gateway 调用，它是注册表的回退目标。
  **Make primary** 不会切换当前的 Sessions 工作区；移除 primary 后会回退到
  local 条目。
- **At startup, return to Sessions on the last-used gateway** 控制应用完全重启后
  Sessions 打开哪个 gateway。它默认关闭，因此 Sessions 会在 **Primary** 上打开。
  开启后会恢复最近一次成功连接的 gateway。失败的切换永远不会被记住，
  已移除或不可用的已保存 gateway 会回退到 Primary。
- **Test** 会探测该连接自身的 HTTP *和* WebSocket 两条链路，因此通过
  （*"Reachable"* 提示）意味着聊天真的能用——而不仅仅是主机能 ping 通。
- **保存时会拒绝重复项**：**local** 条目永远只有一个；**remote** 和 **cloud**
  条目按规范化后的 URL 去重（去除首尾空白、去掉末尾斜杠、转为小写——并且跨这
  两种类型，因此 cloud 条目和 remote 条目不能指向同一个 URL）；
  **SSH** 条目按规范化后的 `user@host:port` 加远程 profile 去重。
- Cloud 条目通常来自 Gateways 页面顶部的 Hermes Cloud 登录/发现流程——
  添加连接编辑器中的 **Hermes Cloud** 类型会把你引导到那里。

在 **Sessions** 侧边栏中切换 gateway。Profile、聊天、消息和 cron 都限定在该
gateway 范围内；应用管理的窗口后端仍由上方的连接模式控件选择。**Primary** 是
注册表的回退目标，不会切换当前工作区。

## 组织会话分组 {#organizing-session-groups}

在查看所有 profile 时，在 Sessions 侧边栏的视图菜单中选择 **Gateway & profile**。
每个 gateway 都有自己的可折叠区域，其中的 profile 子区域包含各自的会话。两个都带
`default` profile 的 gateway 会保持分开。Gateway 标题以已保存的连接名开头；
profile 标题显示 profile 名称。

使用 gateway 或 profile 区域的菜单可以 **Rename group**、**Reset name**、**Move up** 或
**Move down**。重命名只改变侧边栏标签，不改变 gateway 或 profile。
Gateway 以完整区域为单位重新排序，profile 则在各自所属的 gateway 内重新排序。
拖动区域前端的图标即可重新排序，或者聚焦该把手，按 Space、方向键，再按 Space
放置。名称、顺序和已折叠的区域都会在这台桌面上被记住。折叠某个 gateway 会保留其
各 profile 各自的折叠状态。每个 profile 的新建会话操作都以其所属 gateway 上的
该 profile 为目标。

当门户发现处于未登录状态时，Hermes Cloud 面板还会列出 **Saved Cloud gateways**。
**Use gateway** 会选择一个现有的已保存连接，而不改变默认 gateway；**Active in this
window** 标识当前使用的那个。添加新实例时使用其友好的 Cloud 名称，而现有的自定义
连接名称会被保留。已保存的连接仍需要有效的 gateway 认证；请在已注册连接的控件中
管理登录。

## 逐步添加连接 {#adding-a-connection-step-by-step}

1. 打开 **设置 → Gateways** 并滚动到连接注册表（或点击 profile 导轨中的插头）。
2. 点击 **Add connection**。
3. 选择类型：**Local**、**Hermes Cloud**、**Remote gateway** 或 **SSH**。
   （当应用管理的 local 条目存在时——几乎总是如此——**Local** 处于禁用状态；
   **Hermes Cloud** 会把你引导到上方的云端登录/发现流程。）
4. 填写字段：
   - **Name** —— 必填且唯一；即此实例出现的每个地方所显示的“设备名”
     （占位符：`Homelab`）。最多 64 个字符。
   - *仅 Remote gateway：*
     - **Gateway URL** —— 正在运行的 `hermes serve` 后端的基础 URL，
       例如 `http://homelab.lan:9119`。反向代理的路径前缀可以正常使用。
     - **Authentication** —— 选择 **Session token** 或 **OAuth**：
       - **Session token** —— 粘贴远程 gateway 的仪表盘 session token。
         编辑时，*"Leave blank to keep the saved
         token."*（留空即保留已保存的 token。）
       - **OAuth** —— 通过 Nous Portal 浏览器流程登录；无需粘贴 token。
   - *仅 SSH：*
     - **SSH host** —— 一个 `user@host:22` 形式的组合字段（用户和端口可选）。
       会使用你的 SSH 密钥；应用会通过隧道接管一个仪表盘 token。
5. 点击 **Save connection**（或 **Cancel**）。
6. 在新行上点击 **Test**，等待出现 *"Reachable"*。

之后可以用铅笔按钮编辑任何非 local 条目，或用垃圾桶按钮移除它——移除时会要求
确认，并提醒你 *"The instance itself is not touched — you can add it again any
time."*（实例本身不受影响——你随时可以再次添加。）

:::info 远程后端是一个正在运行的 `hermes serve` 进程
除非后端确实已在另一台机器上运行且可访问，否则这里的一切都不起作用。桌面应用
只是连接到它；不会替你启动它（SSH 连接除外，应用会按需通过隧道启动仪表盘）。
后端侧的配置——认证提供商、绑定到非回环地址以及 Tailscale 指引——参见
[连接到远程后端](./desktop.md#connecting-to-a-remote-backend)。
:::

### 从单连接设置迁移 {#migrating-from-the-single-connection-settings}

支持注册表的版本首次启动时会自动导入你现有的设置：全局连接模式以及来自
设置 → Gateway 的任何旧版按 profile 覆盖项，都会变成具名的注册表条目（按
URL/主机去重）。（较新的版本不再在 Gateways 设置页中提供按 profile 覆盖——
gateway 连接是机器级的，而 profile 是从你连接的 gateway 上发现的。）
旧的设置文件保持不变，因此同一台机器上的旧版本仍可正常工作。如果迁移后的名称
发生冲突，会被加上后缀（`Homelab 2`）。

## 跨 gateway 的 agent {#agents-across-gateways}

每个已注册连接上的每个 [profile](./profiles.md) 都是一个 *agent*。
多 gateway 界面（以及内置的 [Bot Mode](./bot-mode.md) 名单）渲染的是合并后的名单：

- 当同一个 profile 名称存在于多个 gateway 上时，句柄会以
  **`@name-device`** 形式消歧——你 Homelab 上的 `research` 渲染为
  `@research-homelab`，而在所有 gateway 中唯一的 profile 保留其原名。
- 枚举是即时的，但套接字是惰性的：应用通过 REST 列出 agent，而不会连接每个
  gateway 的 WebSocket。无法访问的 gateway 会在对应行上报告，而不会破坏整个名单；
  SSH 连接在你首次打开其上的 agent 之前保持按需连接（不会出现意外的隧道）。
- 打开一个 agent 会连接**它自己的 gateway**——聊天、会话和记忆都存放在拥有该
  profile 的机器上，就像你直接使用那个实例一样。

每个 `(connection, profile)` 组合都有自己的后端和套接字，与本地按 profile 的后端
一样纳入池化并采用相同的空闲回收——当你查看另一个 gateway 时，后台 agent 仍会
持续流式输出。

审批按钮会路由回拥有该会话的后端，而不是当前选中的任意 profile。对于本地的
次要 profile，即使缓存的会话绑定缺失，Desktop 也可以使用投递该请求的套接字。
已保存的会话归属仍然优先；删除或重命名该本地 profile 会清除这条临时路由，
而不是重新连接一个过时的后端。

### 切换与作用域 {#switching-and-scoping}

侧边栏底部遵循一个层级：**gateway → profile → sessions**。
Gateway 是机器或托管后端；profile 是位于某个 gateway 上的相互隔离的 Hermes agent。

- 只有一个已注册 gateway 时，不会添加 gateway 控件。仅本地的 Desktop 保持与以前
  相同的 profile 导轨和键盘操作流程。
- 有多个 gateway 时，侧边栏会显示一个具名的 gateway 选择器。其设备、云、网络或
  终端图标标识连接类型；profile 头像仍是分隔线之后的独立控件。同一个选择器可以
  从两个 gateway 扩展到更大的集群，而不会把后端变成类似 profile 的图标，也不会把
  profile 操作挤出导轨。
- 选择一个 gateway 会恢复在那里最后使用的 profile。主页标签会返回其默认 profile，
  图层标签显示 **All profiles on
  this gateway**。**Cmd/Ctrl+1–9** 仍然在当前活跃的 gateway 内切换 profile。
- 有多个 gateway 时，profile 导轨是一条**集群导轨**：每个已注册 gateway 的 profile
  都排列在同一条带上，每组以该 gateway 的类型图标（设备、网络、终端、云）开头
  ——与 gateway 选择器使用的图标相同。活跃 gateway 的方块看起来与单 gateway 的
  Desktop 完全一样；其他 gateway 的方块则变暗（“静置”）。
  悬停在静置的方块上会显示其所在机器（`omer · This device`），因此不同机器上
  两个同名 profile 永远不会看起来一样。
- 点击静置的方块会执行与 gateway 选择器相同的切换，直接落到那个确切的
  `(gateway, profile)`：连接目标期间方块会旋转，在目标响应之前仍保持显示之前的
  gateway，而无法连接的目标会让这次点击失败并给出消息，而不是让窗口停留在切换
  到一半的状态。无论哪个 gateway 处于活跃状态，各组都保持注册表顺序，因此方块
  永远不会在点击它的指针下移动。在静置方块上右键会提供 **Switch to**、**Color**、
  **Rename**、**Edit SOUL.md** 和 **Delete**，全部在该方块所属的 gateway 上执行；
  删除确认会点名该机器。
- 上次枚举无法访问的 gateway 会保留其方块，并在其图标上标记一个琥珀色圆点——
  一台休眠的机器仍然是你的。同一后端的两次注册会合并为一个组。整个集群的方块
  超过十三个时，这条带会压缩成一个按 gateway 分节的菜单。
- 只有在 **设置 →
  Gateways → At startup, return to Sessions on the last-used gateway** 开启时，所选
  gateway 才会在退出并重新启动后保留。该偏好和 gateway id 存放在应用的用户数据
  注册表中，因此替换或更新应用包不会重置它们。
- 当活跃 gateway 上的 profile 超过十三个时，它们的头像条会压缩成一个具名的
  profile 选择器。因此大量的 gateway 和 profile 可以共存，而无需改变
  **gateway → profile → sessions** 模型。
- 即使某个远程连接是 Primary，**This device** 仍然是一等 gateway。它可以在远程
  故障期间保持本地会话可用，但应用不会把它称为“离线模式”：所选模型或工具可能
  仍需要互联网访问。
- 会话列表、消息频道、cron 任务、设置、文件和记忆都限定在活跃的
  `(gateway, profile)` 范围内。从 Telegram gateway 切换到 Signal gateway 时，
  侧边栏中不可能残留前一个 gateway 的频道分组或会话。
- 仅仅显示切换器只会读取 Electron 的本地连接注册表。
  远程 gateway 只有在被选中时才会打开；不存在周期性的集群轮询。
- 悬停在某个 agent 上会预热其后端，因此切换时无需承担冷启动开销。
- **Capabilities** 页面（Skills / Tools / MCP）有相应的作用域：其
  **Configuring** 选择器列出合并名单中的每个 `(profile, device)` agent，选中其中
  一个即可读写**那台机器的** skill、工具集和 MCP 服务器，而不切换 Sessions 工作区。
  Hub 安装、环境变量键和 MCP 配置都会落到所选 agent 的后端上。
  MCP 标签页的 *hot-reload into a live session* 按钮只对窗口所连接的 gateway 上的
  agent 显示；其他机器上的编辑会在它们的下一个会话中生效。

在 **设置 → Gateways** 中添加、测试、重命名或移除 gateway。profile 操作旁边的插头
按钮是通往这个唯一管理入口的快捷方式，而不是第二个添加流程。

### 会话与 Bot Mode {#sessions-and-bot-mode}

Sessions 有意每次只显示一个活跃 gateway：这样可以把文件、工具、频道、cron 和会话
历史保持在一个易于理解的执行上下文中。集群 profile 导轨扩大的只是*选择器*——
每次点击之后，工作区仍然只位于一个确切的 `(gateway, profile)` 上。Bot Mode 承担的
是不同的工作，可以展示按 gateway 分组的合并名单，这样用户就能在同一个界面上
打开 NAS 上的一个 agent 和 VPS 上的另一个 agent。打开一个 bot 仍然会激活其确切的
`(gateway, profile)` 路由。

直接的 bot 提及和委派默认仍在 gateway 本地进行。跨越后端边界会改变文件系统、凭据、
工具和信任上下文，因此跨 gateway 执行应当是一座显式的桥梁，而不是共享同一个
Desktop 窗口带来的意外副作用。

## 一次性更新所有实例 {#updating-every-instance-at-once}

**设置 → Gateways → Update all instances**（注册了多个连接后才会显示）会并行地向
每个符合条件的连接下发 `hermes update`：

- **Local** 通过应用自身的更新管道更新（与设置 → Updates 的流程相同）。
- **Remote 和 SSH** 连接会被告知通过它们自己的后端更新自身——更新在*那台*机器上
  运行。
- **Hermes Cloud** 实例会被跳过，并附上 *"Managed by Hermes Cloud"* 说明：
  平台负责管理它们的版本。

每个实例独立报告，因此一台无法访问的机器永远不会卡住整批更新。由外部管理更新的
后端（Docker、Nix）会在各自的行上礼貌地拒绝，并给出它们自己的消息。

不过你很少需要这个设置按钮：一旦存在多个更新目标，应用常规的更新入口（About
面板上的 **Update now**、⌘K 中的 **Update Hermes**、更新就绪提示）会自动执行
同样的扇出——先更新活跃后端，然后是其他每个符合条件的 gateway，最后才是桌面应用
本身。参见桌面指南中的[更新](./desktop.md#updating)。

## 安全说明 {#security-notes}

- **token 存放在哪里。** 远程 gateway 的 session token（以及按 gateway 基础 URL
  索引的原生登录 OAuth token）以仅所有者可读写（0600）的文件形式存放在应用的
  用户数据目录中，由 Electron 主进程处理；渲染进程和插件永远看不到 token 字节。
- **可选的钥匙串加密。** 默认情况下，token **不会**经过操作系统钥匙串——尤其是在
  macOS 上，Electron 的 `safeStorage` 会在登录钥匙串中放置一个按应用区分的密钥，
  而锁定或损坏的钥匙串会导致每次启动都弹出密码提示。如果你希望在文件权限之上再加
  一层静态加密，请开启 **设置 → Gateway →
  "Encrypt saved secrets with the OS keychain"**；已存储的现有机密会被就地重新加密
  （macOS 上为 Keychain，Windows 上为 DPAPI，Linux 上为会话 keyring 后端）。
  再次关闭会将它们解密。
- **注册表文件**（应用用户数据目录下的 `connections.json`）保存标签、URL 和主机
  ——机密只会出现在加密封装内部。
- 插件 SDK 的 `host.connections()` 有意只返回标签、类型和 primary id——永远不会
  返回 token 材料。

## 面向插件作者 {#for-plugin-authors}

Desktop [插件 SDK](../developer-guide/desktop-plugin-sdk.md) 直接暴露了多 gateway 接口：

- `host.connections()` —— 已注册的连接列表（标签、类型、primary；永远不含 token
  字节）。
- `host.agents()` —— 合并名单：每个 `(gateway, profile)` 一行，附带预先计算好的
  `@name-device` 句柄。
- `host.ensureAgent(connectionId, profile)` —— 激活某个 agent 的 gateway，使后续的
  `host.request` 调用命中其后端。
- `host.warmAgent(connectionId, profile)` —— 发出即不管的套接字预热（悬停意图）。

这四个接口都采用特性检测：在较旧的 Desktop 版本上它们不存在，插件应回退到单
gateway 的 `profiles.list` 流程。Bot Mode 的多 gateway 名单是参考使用方。

## 故障排查 {#troubleshooting}

- **"Connection test failed"** —— 从这台机器无法通过该 URL 访问后端。检查远程主机
  上 `hermes serve` 是否在运行、端口是否开放，以及（对于 token 认证）token 是否仍
  有效。修复后重新运行 **Test**。
- **agent 显示出来但打不开** —— 对其连接运行 **Test**。HTTP 通过而 WebSocket 链路
  失败，通常意味着代理、防火墙或 gateway 的认证/来源防护阻止了 `/api/ws`。
- **某个远程 gateway 未出现在名单中** —— 其后端已停止或无法访问；名单会把它列在
  gateway 下并附上错误。SSH 连接在首次使用前显示 *connect-on-demand*——这是设计
  如此，并非故障。
- **"Update Hermes Desktop to chat with agents on other connections"** —— 应用版本
  早于多连接架构；请更新桌面应用本身。
- **设备名重复** —— 不可能出现；保存时会强制名称唯一。如果迁移后的名称发生冲突，
  会被加上后缀（`Homelab 2`）。
- **"Could not save the connection"** —— 最常见的原因是缺少 **Name**、名称已被
  使用，或 **Gateway URL** / **SSH host** 格式错误；错误消息会点明具体的违规项。
