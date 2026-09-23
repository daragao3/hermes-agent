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

从 [Hermes Desktop 产品页面](https://hermes-agent.nousresearch.com/desktop)下载应用，或参照 [Hermes Desktop 的安装说明](../getting-started/installation.md)。

如果你已经安装了 Hermes，直接运行

```bash
hermes desktop
```

它会使用你当前的配置、密钥、会话和 skills。

## 应用里有什么

桌面应用以聊天为核心组织窗口，左侧有一条导航侧边栏。它的设计目标是同时管理多个 agent 对话、配置消息提供方、创建 artifact、浏览项目的目录结构，以及同时推进多个项目。

侧边栏的选中状态跟随获得焦点的聊天面板。打开或聚焦一个会话标签页会清除页面的高亮（包括 Kanban 这类由插件贡献的页面），即使工作区仍保留着该页面的路由。

### 聊天

应用的核心。你会得到：

- **流式响应**，在 agent 工作时实时显示工具活动和结构化的工具调用摘要。
- **Markdown 换行**遵循 Markdown 语义：行尾两个空格产生硬换行；普通换行仍是软换行。媒体和预览提取会保留被移除附件片段之外的文本，包括首行代码的缩进和未闭合围栏代码块中的空白。代码显示和“复制”会保留 Markdown 解析器给出的开头空行、行尾空格和末尾空行。
- **与其他所有 Hermes 界面相同的对话历史** —— 在这里开始的会话可以在 CLI/TUI 中继续，反之亦然。
- **拖放文件** 到聊天区域的任意位置，把它们附加到你的下一条消息。
- **相互独立的后台草稿** —— 隐藏的聊天标签页可以更新各自的草稿，而不会移动可见输入框中的光标或选区。
- **指令标签操作** —— 悬停在一个可操作的引用（例如 URL）上，会显示它的操作胶囊按钮。一小段宽限时间让你能从标签移到胶囊按钮上而不会让它消失。只要你在胶囊按钮内移动，它就一直可用；离开之后，无关的指针移动不会延迟它的消失。点击其中的操作会保留草稿中的选区。
- **右侧预览栏** —— 在继续聊天的同时并排渲染网页、文件和工具输出。
- **应用内浏览器的批注模式** —— 在预览浏览器栏中点击 **Annotate**，然后点击实时页面上的任意元素（或拖出一个框）并输入备注；每条保存的批注都会以带编号的图钉留在页面上。保存图钉永远不会发送一轮对话 —— 完成后，**Add N comments** 会把每个图钉对应的裁剪截图以及一段逐条点名各批注的简短提示词附加到输入框，发送仍然由你自己点击。每条元素批注都带有它的 CSS 选择器、它的标记，以及对布局有影响的计算样式，这样 agent 就能在你的源码中找到该元素，而不是凭截图猜测。密码和隐藏字段的值，以及任何看起来像密钥或令牌的属性，都会在标记离开页面之前于页面上被脱敏。较多的批注会按它们所在的页面区域分组送达，因此二十来条批注会变成少数几块工作，而不是每条一个任务 —— 而且由于各组是彼此独立的 DOM 子树，它们通常涉及不同的文件，这正是把它们交给并行 worker 处理之所以安全的原因。删除某个图钉时其余图钉的编号保持不变，切换聊天会清空整组批注。
- **输入框历史与队列编辑** —— 在空的输入框中按上/下方向键可调出并复用之前的提示词，也可以在排队的消息发送前编辑它们。在有排队轮次时按 Stop（或 Esc）会暂停队列并在输入框上方展开它；可以在那里恢复队列，或者逐条发送、编辑和删除。
- **输入框上方的任务进度** —— 展开 Tasks 标题即可查看每个阶段。长列表在输入框上方保持有限高度；在展开的列表内部滚动即可看到最后的任务，而不会移动对话。
- **对话时间线导轨** —— 长对话会在记录边缘出现一条细长的标记导轨，每个提示词一个标记。悬停即可弹出提示词列表，点击其中一个就能直接跳到对话中的那个位置。（聊天有了若干轮之后才会出现。）
- **阅读位置记忆** —— 回到某个会话时，会恢复它保存的距底部距离，而不是总跳到最新消息。停留在底部的会话会继续跟随新输出。用 **Scroll to bottom** 回到实时边缘。位置保存在本桌面安装的本地存储中，不会通过后端同步。
- **页内查找** —— 按 **Cmd/Ctrl+F** 打开查找栏，在渲染后的聊天记录中搜索。Enter / Shift+Enter（或在查找栏打开时按 Cmd/Ctrl+G / Cmd/Ctrl+Shift+G）逐个跳转匹配项；Esc 关闭它。

异步的 cron 和委派完成结果会以折叠的时间线展开项形式出现。打开完成标签即可以 Markdown 形式阅读结果正文（包括任务输出）；长报告在展开项内部滚动。任务指令和投递信封不会作为报告内容显示。

#### 状态栏

聊天底部的状态栏显示实时的会话状态，并提供无需打开设置就能使用的快捷控件：

- **按会话切换 YOLO** —— 只针对当前会话开启或关闭 YOLO（与 TUI 一致）。YOLO 会绕过危险命令的审批提示，所以要清楚你关掉的是什么 —— 参见 [安全 → YOLO 模式](./security.md#yolo-mode)。
- **上下文用量表** —— 实时显示会话上下文窗口“已用百分比”的仪表。点击它会打开 **Context Usage** 弹出框，按类别（系统提示词、工具定义、skills、记忆、规则、MCP、子 agent 定义以及对话本身）给出 token 细分，让你在压缩启动之前准确看到是什么在占用窗口。
- **缓存命中率与每秒 token 数** —— 默认关闭；可在右键菜单中打开。缓存命中率是本会话提示词 token 中由提供方提示词缓存提供的比例（缓存 token 更便宜，所以越高越省钱 —— 你可以看着一个会话随着预热变得越来越便宜）。每秒 token 数是最近 10 次模型调用的平均输出吞吐量。两者都会在一轮对话进行中实时更新。
- **可自定义的条目** —— 右键点击状态栏（**Show in status bar**）选择要显示的内容：上下文用量表、缓存命中率、每秒 token 数、工作区、模型、审批、轮次/会话计时器、终端、Command Center、后端版本等 —— 也可以整个隐藏状态栏（**Cmd/Ctrl+Shift+S** 切换）。

想连接到另一台机器上的 Hermes 实例，而不是内置的本地后端？请看下方的[连接到远程后端](#connecting-to-a-remote-backend) —— 若要完整了解远程托管的 dashboard 连接是如何工作的（认证关卡、`/api/ws` 聊天套接字，以及 WebSocket 关闭码的排查），参见 [Web Dashboard → 将 Hermes Desktop 连接到远程后端](./features/web-dashboard.md#connecting-hermes-desktop-to-a-remote-backend)。

#### 仓库发现

Hermes Desktop 会以有限深度扫描你的主目录，为 Projects 侧边栏发现本地 Git 仓库。你可以在 **设置 → Workspace** 中按 profile 修改这一行为，或者在 `config.yaml` 中设置：

```yaml
desktop:
  repo_scan_enabled: true
  repo_scan_roots: []
  repo_scan_exclude_paths: []
```

- 设置 `repo_scan_enabled: false` 可完全停止文件系统扫描。该 profile 已有的磁盘发现缓存条目会被清除；显式添加的项目以及从有意发起的 Hermes 会话推断出的仓库仍然可用。
- 把 `repo_scan_roots` 设为一个文件夹列表，可将扫描限制在其中。空列表保持默认的主目录扫描。
- 把 `repo_scan_exclude_paths` 设为需要整棵子树跳过的文件夹。

修改其中任一值只会使该 profile 的磁盘发现缓存失效，并启动一次符合新策略的刷新。**Hide from sidebar** 仍然是一个独立的逐项整理操作。

#### 选择模型

模型选择器位于**输入框**中，就在麦克风左侧。点击它即可在同一个下拉菜单里切换模型、推理强度和快速模式。

- **输入框里的选择器是黏性的 UI 状态，永远不会改动你的默认值。** 它保存在本地（按设备），并会**跟随**到新的聊天和重启之后，而不是回退到默认值 —— 选一次模型，下一次 `Cmd/Ctrl+N` 就以它开启。在有活跃聊天时切换模型，改动的范围仅限于**当前这个聊天**；无论哪种情况，选择都会在会话创建/切换时一并带上，并且**绝不会**写入 profile 的默认值 —— 只有一个例外：在一个尚未配置 `model.default`/`model.provider` 的全新 profile 上，第一次选择会被持久化，这样应用在重启时就有一个真正的默认值，而不会落到某个零散的 API 密钥环境变量上。持久化遵循与 `/model` 相同的规则（`model.persist_switch_by_default`）；若要有意修改默认值，请使用 **设置 → Model**。（切换 [profile](#sessions--profiles) 会重新以该 profile 自己的默认值为准。）
- **在 设置 → Model 中设置默认值。** 那个“主”模型是你的**按 profile 的全局默认值** —— 新的聊天、cron、子 agent 和辅助任务都以它为起点，而且只有这里会写入它。每个 [profile](#sessions--profiles) 都保有自己的默认值。
- **每个模型各自的推理强度 / 快速模式预设。** 在桌面应用中，每个模型都会记住自己的推理强度和快速模式选择，在你选中该模型时重新应用到会话上。这些预设只是桌面端的便利功能，不会影响 cron 或子 agent。
- **聊天中途切换模型会重置提示词缓存。** 在活跃聊天里切换模型意味着下一条消息会以完整输入价格重新读取整段对话（提供方的提示词缓存是按模型绑定的）。偶尔切换没问题；但在长对话里，用新模型开一个新聊天往往比来回切换更省钱。

### 文件浏览器

无需离开应用即可浏览和预览工作目录 —— 在 agent 读取、写入和编辑文件时跟进很有用。用 `hermes desktop --cwd <path>`（或环境变量 `HERMES_DESKTOP_CWD`）设置初始项目目录。

### Artifacts

连接到远程 gateway 时，打开一个文件 artifact 会通过该 gateway 下载它，并使用该 artifact 来源的 profile 和会话。相对路径以会话保存的工作目录为基准解析；相对于主目录的路径使用 gateway 的主目录，绝不会使用桌面这台机器的主目录。Windows 风格的相对路径与正斜杠路径一样能被识别，文件 URI 会保留驱动器和网络共享信息，交由 gateway 解释。会话或工作目录缺失时会报错，而不会改为选中另一个本地文件。

**Artifacts** 视图把你的会话生成的内容 —— **图片、文件和链接** —— 汇集到一个可搜索、可浏览的画廊中。可以从侧边栏、命令面板（**Artifacts — Browse generated outputs**）或你自己绑定的 `nav.artifacts` 快捷键打开它。它会自动为近期的会话输出建立索引；每个 artifact 都会显示是哪个会话生成的，并可一键跳回那个聊天，图片和文件会在预览中打开，并提供下载 / 在浏览器中打开 / 复制等操作。

### 窗口、标签页与面板

应用是为同时处理多件事而设计的：

- **标签页** —— **Cmd/Ctrl+T** 打开一个新的会话标签页；**Ctrl+Tab** / **Ctrl+Shift+Tab** 在会话间循环切换，**Ctrl+1…9** 按位置跳到某个最近的会话。**Cmd/Ctrl+W** 关闭获得焦点的标签页，**Cmd/Ctrl+Shift+T** 重新打开最近关闭的那个。
- **多窗口** —— **Cmd/Ctrl+Shift+N** 打开一个新窗口，任何会话都可以通过它的右键菜单（**New window**）或命令面板弹出为独立窗口。弹出的窗口只渲染那一个聊天，不带全局侧边栏 —— 便于把一个长时间运行的会话放到另一台显示器上。agent 的实时输出会流式传送到每一个显示该会话的窗口。
- **面板** —— **Cmd/Ctrl+B** 切换左侧边栏，**Cmd/Ctrl+J** 切换右侧边栏，**Cmd/Ctrl+\\** 交换两侧边栏所在的位置。

### 终端

右侧边栏里、文件浏览器旁边，有一个真正的终端：

- **Ctrl+`** 显示终端（如果还没有则新开一个）；**Ctrl+Shift+`** 再新开一个。多个终端堆叠在一条标签导轨中 —— **Ctrl+Shift+↓/↑** 在它们之间切换，**Ctrl+Shift+W** 关闭当前终端。
- **隐藏时 shell 依然保留。** 关闭或隐藏面板不会杀掉你的 shell —— 每个打开的终端都会保持挂载，回滚记录和正在运行的进程完好无损，直到你显式关闭它。
- **Add to chat** —— 选中终端输出，把它作为下一条消息的上下文发送到输入框。

### 实时子 agent

当委派的 worker 正在运行时，输入框上方会出现一个 **Subagents** 框，显示它们的数量、任务名称、已用时间和最新活动。它最多预览三个 worker；展开标题可查看完整名单，再选中某个 worker 查看详情以及 **Steer** / **Stop** 控件。每个框都属于它所在的聊天，分栏面板中也是如此。Steer 的确认表示指引已排队等待某个检查点，而不是子 agent 已经读到了它。参见[监控子 agent](/user-guide/features/delegation#monitoring-running-subagents-agents)。

### Git 审查与 worktree

对于在 Git 仓库中运行的会话，应用内置了一个源码管理界面：

- **审查面板** —— **Cmd/Ctrl+G** 切换工作树审查面板：分支及 ahead/behind 状态、已修改文件（列表或树形视图），以及限定在 **Uncommitted**、**Branch** 或 **Last turn**（只看 agent 在最近一轮中改了什么）范围内的 diff。可以暂存/取消暂存文件、还原改动、撰写提交信息（或 **Generate commit message**），然后 **Commit** 或 **Commit & Push** —— 并通过 GitHub CLI（`gh`）**Create PR**，或者用 **Ask Hermes to open PR** 把整件事交给 agent。你也可以在这里创建和切换分支。
- **Worktree** —— **Cmd/Ctrl+Shift+B**（或侧边栏中某个项目上的 **New worktree**）会在一个新分支上创建 Git worktree，让 agent 可以在仓库的并行副本上工作，而不触碰你的检出目录。worktree 会作为项目下各自独立的通道显示；移除时可以选择删除 worktree 目录（分支保留），或者只隐藏该通道、把它留在磁盘上，当它有未提交的改动时还提供强制选项。

### 记忆图谱

**Memory Graph**（命令面板 → *Memory Graph*，或状态栏条目）是一张交互式地图，展示 Hermes 为你学到了什么 —— skills 和记忆以可缩放的节点图形式排布，并带有时间线，可按 **All / Used / Learned** 过滤。一个分享控件可以把地图布局导出为一段紧凑的代码，粘贴给别人（只包含布局 —— 不含你的任何记忆或 skill 文本），也可以用同样的方式导入代码。

### 快速输入

Quick Entry 是一个小巧、随时可用的输入框，通过**在系统任意位置都能触发的全局热键**唤出 —— 无需切换到（甚至无需打开）主窗口就能发出提示词。在 **设置 → Advanced → Quick Entry** 中启用；默认快捷键是 **Ctrl/Cmd+Shift+Space**，你也可以自行设置（至少需要一个修饰键）。如果其他应用已占用该组合键，设置行会提示你，以便你另选一个。

### 语音

与 Hermes 对话并听它回答，与别处提供的[语音模式](./features/voice-mode.md)相同。在 macOS 上，系统会提示一次麦克风权限。

### HUD 模式

**⌘/Ctrl+Shift+H**（或标题栏按钮）会把聊天分离成一个无边框、始终置顶的浮动条，悬浮在你正在使用的任何东西之上。应用窗口会让到一旁；HUD 保留你的实时对话和一个输入框。你把它停放在哪里本身就是上下文 —— 浮动条的位置会告诉 Hermes 你问的是哪个应用、哪块屏幕，因此“这个”“这里”“那个页面”都会解析为它下方的内容。

- **移动浮动条** —— 在 macOS 和 Windows 上，在输入框任意位置**按住**片刻，然后拖动。在 Linux/X11 上，按住 **Ctrl** 并用鼠标主键拖动即可立即抓取（包括在选中文本上）；按住再拖的方式同样可用。在抓取状态下调用桌面切换快捷键，可以把 HUD 带到另一个虚拟桌面。在原生 Wayland 上，输入框栏是合成器的拖动手柄（这是移动它的唯一方式，因为应用无法自行放置自己的窗口）。
- **调整大小** —— 拖动浮动条的任意边或角；对侧的边保持固定。原生 Wayland 只暴露右边和下边，因为合成器不允许应用自行定位顶层窗口。
- **重置布局** —— 浮动条上的丢弃控件会恢复默认大小以及（在 X11 / macOS / Windows 上的）位置。如果某个持久化的尺寸让 HUD 无法使用，就用它。
- **吸附到指针** —— **⌘/Ctrl+Shift+G**（全局热键，在任何应用中都有效）会让 HUD 跳到你光标所在的位置。在原生 Wayland 上这是空操作 —— 窗口位置由合成器掌控。
- **退出** —— 点击浮动条上的退出按钮，或再按一次 **⌘/Ctrl+Shift+H**。应用窗口会回来，会话完好无损。

#### Linux / Wayland

在 Wayland 会话中，Electron 20+ 本来就作为原生 Wayland 客户端运行。拖动、点击穿透和调整大小在这条路径上都能正常工作。

在 **Hyprland**（包括 Omarchy）上，HUD 会在映射之后通过合成器的 IPC 被设为浮动并固定 —— 否则 Hyprland 会像对待其他窗口一样把它平铺，`always-on-top` 会被忽略，合成器拖动也不起作用。无需额外的窗口规则。

少数合成器（尤其是 COSMIC）会对原生 Wayland 窗口忽略 `always-on-top`。要在那里恢复置顶，请让应用运行在 XWayland 下：

```yaml
desktop:
  ozone_platform_hint: x11
```

它会在启动时桥接到 `ELECTRON_OZONE_PLATFORM_HINT`（显式设置的环境变量仍然优先）。代价是：X11 无法恢复一个曾忽略鼠标的窗口，因此 HUD 会保持为实体窗口，而不是点击穿透。一些 KDE 环境还报告过使用 X11 ozone 后端时键盘失灵 —— 除非你需要始终置顶，否则把该提示保持为 `auto`。

#### WSLg（在 WSL2 中使用 Windows GPU）

当 `hermes gui` 在 WSL2 中运行，且存在 `/dev/dxg`、安装了 Mesa 的 `d3d12_dri.so` 时，启动器会为 Electron 设置 `GALLIUM_DRIVER=d3d12`，让渲染使用 Windows GPU 而不是 llvmpipe 软件光栅化器；如果你的环境中显式设置了 `GALLIUM_DRIVER`、`MESA_LOADER_DRIVER_OVERRIDE`、`LIBGL_ALWAYS_SOFTWARE` 或 `LIBGL_DRIVERS_PATH`，则不会被改动（例如 `GALLIUM_DRIVER=llvmpipe hermes gui` 会保持软件渲染）。

### 设置与初次引导

在真正的图形界面里管理提供方、模型、工具和凭据，而不用编辑 YAML。首次运行的引导流程能让你在几秒内发出第一条消息。设置面板覆盖提供方/密钥、模型选择、工具集配置、MCP 服务器、gateway 和会话管理。

- **提供方设置面板** —— 一个专门管理推理提供方的位置，提供账户 / API 密钥的交互界面，用于登录并按提供方存储凭据。账户和 API 密钥共用设置中的 **Applies to** 选择：在这里发起的凭据读取与编辑、OAuth 账户移除以及登录，作用对象都是所选的 profile，而不是当前聊天所用的 profile。登录流程会在凭据保存和模型选择的整个过程中保持这个目标。更改 **Applies to** 会丢弃尚未保存的凭据草稿。关闭登录会取消轮询并忽略迟到的结果；已经发出的凭据写入仍可能在其原本的 profile 中完成。由外部管理的 CLI 凭据使用它们自己的 CLI，不受这个 profile 选择器影响。它的 **Local Models** 视图可以安装和管理设备端的 llama.cpp 运行时 —— 参见[本地模型](/user-guide/local-models)。
- **菜单里包含每一个提供方和模型** —— GUI 会展示完整的提供方列表以及 `hermes model` 知道的每一个模型，因此你选择的范围与 CLI 看到的目录一致，而不是一个精选子集。
- **xAI Grok OAuth** —— Grok 在启动器中是一等的 OAuth 提供方；像其他 OAuth 提供方一样通过浏览器流程登录。
- **在 GUI 中安装工具后端** —— 直接在应用里执行某个工具后端的安装后置步骤，无需切到终端。
- **终端字体选择器** —— 在 **设置 → Appearance** 中选择一种已安装的字体。像 `MesloLGS NF` 这样的 Nerd Font 能在交互式终端和 agent 终端中正确渲染 Powerlevel10k 的分隔符和图标；该设置按 profile 保存。
- **启动时重新打开上次的聊天** —— 默认情况下，应用冷启动时会从你上次离开的地方继续。在 **设置 → Appearance** 中关闭它（或在 `config.yaml` 中设置 `display.resume_last_session: false`），就会总是以一个新聊天开始。无论哪种设置，深层链接和显式指定的目标都不会被覆盖。
- **辅助模型警告** —— 如果你把主模型切换到新的提供方，而辅助任务（标题生成、摘要及类似的辅助工作）仍固定在另一个提供方上，应用会给出警告，避免你在不知情的情况下把工作分散到两个提供方。
- **VS Code Marketplace 主题** —— 除了内置的主题预设，外观设置中还包含一个实时的 VS Code Marketplace 搜索：选中任意配色主题，应用就会下载、转换并把它安装为桌面主题。同一个导入器也可以从命令面板（*Install theme*）使用，导入的主题也能在外观设置中再次移除。
- **保持电脑唤醒** —— **设置 → Advanced → Keep computer awake** 会阻止机器休眠，让长时间或通宵运行的 agent 任务持续进行（显示器仍然可以变暗）。这是一个按电脑的设置。

首次运行的引导流程已在统一的浮层设计体系上重新设计，你也可以选择**稍后选择提供方**，先跳过提供方设置进入应用。

#### 按 profile 的设置：“Applies to”作用范围

当你有两个或更多 [profile](./profiles.md) 时，由配置支撑的设置页面 —— **Model、Workspace、Safety、Memory & Context、Voice、Chat、Advanced 和 Tools & Keys** —— 以及 **Messaging** 浮层会在顶部显示一排共享的 **Applies to** 标签。它决定你的编辑作用于哪个 profile：

- 默认选择**跟随当前活跃的 profile**，行为与以前完全相同 —— 编辑你正在使用的 profile。
- 选择另一个 profile，即可在不切换整个应用的情况下查看和编辑*它的*设置；在不同设置页面之间切换时，这个选择会保持不变。
- 切换应用的活跃 profile 会重置选择器，这样编辑就不会悄悄地继续落在之前选中的 profile 上。
- profile 少于两个时，这排标签会完全隐藏。

（Gateways 页面处理 profile 的方式不同 —— 通过它的 **Per-profile overrides** 子部分 —— 而 Capabilities 和 Scheduled Jobs 视图有各自的作用范围选择器。）

### 管理面板

应用同样呈现了更广泛的 Hermes 管理能力，让你不必切到终端：

- **Skills** —— 浏览、安装和管理 [skills](./features/skills.md)。Skills 标签页列出你已安装的 skills 并附带启用/禁用开关，下方是随 Hermes 一同发布的完整内置可选 skills 目录 —— 每一项都有一个一键 **Install** 按钮，安装完成后该行会移入已安装列表。
- **记忆图谱（Star Map）** —— 在聊天中输入 `/journey`（别名 `/learning`、`/memory-graph`），即可打开一个交互式星图，展示随时间习得的 skills 和记忆，并带有回放拖动条。可以直接在面板中编辑或删除节点（skills 会被归档，记忆会被移除）。参见[学习历程](./features/memory.md#learning-journey-journey)。
- **Cron** —— 查看和管理[定时任务](../reference/cli-commands.md#hermes-cron)。
- **Profiles** —— 在 [Hermes profile](./profiles.md) 之间切换（隔离的配置/skills/会话）。
- **Messaging** —— 配置 gateway 频道。
- **Agents** 和 **Command Center** —— 面向多 agent 协作的编排界面。

### Bot 模式（内置）

**Bot Mode** 随应用一同发布，并且默认开启：这是一个“每个 agent 一个聊天”的名单，每个 [Hermes profile](./profiles.md) 都以一个 bot 的形式出现，拥有自己的头像（几何脸、上传的图片、AI 生成的肖像，或一只像素宠物）、自己专属的 **Bot Chat** 对话，以及自己的 **Routines**（由 Hermes cron 支撑的周期性任务）。名单位于左侧边栏，作为你的对话旁边的一个标签页 —— 一条 **Sessions | Bots** 标签栏 —— 而不是堆叠在会话列表下方的第二个面板。沿用旧版堆叠布局的安装会被自动迁移到标签栏中，仅迁移一次；如果你自己手动摆放过面板，你的布局不会被改动。**Cronjobs**（Routines）面板只在 Bots 标签页激活时停靠在聊天旁边，切回 Sessions 时就会消失（较旧的桌面版本会让它始终可见）。

从名单中创建新的 agent —— 名称 / 头衔 / 描述，外加一个 Advanced 展开项，其中包含完整的能力设置（模型、SOUL、skills、工具集、MCP 服务器）—— 把它们分组到不同区段，并开启由多个 bot 共同讨论的群聊。群聊在名单中显示为独立的 Discord 风格行 —— 叠放的成员头像、成员数量、房间最新一行的预览，以及“需要你处理”徽标 —— 并按与 bot 行相同的“置顶 + 最近活跃”顺序与之交错排列。点击一个群聊行，会以标签页的形式在**主聊天窗口**中打开该房间（较旧的桌面版本会退而在 bots 侧面板中打开它）。

bot 之间可以互发消息：在任意聊天中输入 `@researcher have a look at this`，当前活跃的 bot 就会把消息转交出去并汇报结果，bot 之间也可以直接访问彼此的 Bot Chat（`hermes -p <bot> chat`）。后端会自动把消息协议教给每个 bot 专属的 **Bot Chat** 会话（配置项 `agent.bot_mode_protocol`，默认开启）—— 包括当某个队友 bot 从 CLI 以无头方式打开它的时候 —— 因此 bot 之间的回复和转交无需改动你的 SOUL.md 就能工作，你的普通会话也不受影响。

Bot 模式的会话 —— 每个 bot 专属的 Bot Chat 以及每个群聊成员会话 —— 始终不会出现在全局 Sessions 侧边栏中。它们存在于 Bots 面板里（名单行、房间视图以及每个 bot 的会话浏览器），而不会与你自己的对话交错在一起。

不常用的 bot 可以收起来：右键点击 bot 行 → **Hide Bot**。隐藏的 bot 会离开名单，但仍然在工作 —— @mention 依然可以解析，群聊成员身份也不受影响。只要至少有一个 bot 被隐藏，Bots 标题栏就会出现一个眼睛开关；点击它可以让隐藏的 bot 以变暗的样式在原位显示（右键 → **Unhide Bot** 可以恢复某个 bot），当某个隐藏的 bot 有未读活动时，眼睛图标上会显示一个圆点。隐藏状态存储在 bot 的 profile 中，所以它会随 bot 跨机器同步。

不想要它？在 **设置 → Plugins → Bots** 中关闭即可 —— 名单、routines 面板和输入框中间件会实时注销，无需重启。

完整指南 —— 创建 agent（包括多机器的 **Create on** 选择器）、跨连接的名单、bot 之间的提及，以及群聊如何决定由谁回复：[Bot 模式：agent 名单](./bot-mode.md)。

### 键盘与导航

- **命令面板** —— 按 **Cmd+K** 或 **Cmd+P**（Windows/Linux 上为 Ctrl+K / Ctrl+P）跳转到各项操作，用键盘在应用中导航：打开任意页面或设置区段、按标题或 id 跳到某个会话、切换模型/主题/颜色模式、新开终端、重启 gateway、更新 Hermes，等等。
- **可重绑定的快捷键** —— **设置 → Keyboard Shortcuts**（或 **Cmd/Ctrl+/**）会打开快捷键面板，你可以在其中重新映射几乎所有绑定 —— profile 切换、会话导航、视图切换，以及桌面插件贡献的任何快捷键。重复的分配会被标记为冲突。几个值得了解的默认值：**Cmd/Ctrl+N** 新会话，**Cmd/Ctrl+.** Command Center，**Cmd/Ctrl+,** 设置，**Cmd/Ctrl+Shift+F** 搜索会话，**Cmd/Ctrl+1–9** 切换 profile，**Shift+X** 切换浅色/深色。
- **自定义缩放快捷键** —— 以半步为增量缩放界面，更精细地控制文字大小。
- **界面语言切换器** —— 在应用内更改界面语言：英语、简体中文（zh-Hans）、繁体中文（zh-Hant）、日语、阿拉伯语（RTL）和俄语。

### 会话与 profile {#sessions--profiles}

- **会话列表大改** —— 重做后的会话列表支持归档以及一般性的会话整理，让列表在增长时依然可控。
- **按 id 搜索会话** —— 直接通过 id 找到某个特定会话。
- **跨 profile 的并发会话** —— 同时在多个 [profile](./profiles.md) 下运行会话，并用跨 profile 的 `@session` 链接引用另一个 profile 中的会话。
- **导出 / 导入 profile** —— 把一整套配置作为单个文件分享。**⌘K → Export profile…**（或右键点击导轨中的 profile 方块）会写出一个 `.tar.gz`，其中包含 skills、记忆、人设、cron、插件和设置；API 密钥会被剥离。从桌面应用导出时还会打包你的外观和界面 —— 皮肤、浅色/深色模式、自定义主题、该 profile 的导轨颜色以及你的窗口布局 —— 因此导入的 profile 看起来会和发送者那边一模一样。通过 **⌘K → Import profile…** 或导轨 **+** 旁边的按钮导入；它会应用这层覆盖并把你带进新的 profile。同一个归档文件也可用于聊天中的 `/export` / `/import`，以及 shell 中的 `hermes profile export` / `import`。参见[导出和导入 profile 文件](./profile-distributions.md#export-and-import-a-profile-file)。

## 更新 {#updating}

应用会在后台检查更新，并在有可用更新时提供一键更新。

本地更新期间，详细的构建输出会流式写入当前活跃 profile 的 `logs/update.log`，包括分离执行的 `--gateway` 更新。这些输出不会出现在终端中，但在构建完成之前就可以用于排查问题。Windows 的交接流程会把该日志中的新输出视为进度；不产生任何输出的子进程仍然受空闲看门狗约束。仅凭进程存活并不会重置该看门狗，取消更新也不会等待其构建完成。

桌面应用和它所连接的 Hermes 后端各自按独立的节奏更新 —— 应用包在你的机器上，后端则在它运行的地方。当存在多个更新目标（一个远程 gateway，或若干已注册的 gateway）时，更新入口（About 面板上的 **Update now**、⌘K 中的 **Update Hermes** 行，以及“更新已就绪”提示）会更新**所有东西**：先更新已连接的后端，然后是其他每一个符合条件的已注册 gateway（Hermes Cloud 条目由平台管理，会被跳过），最后才是桌面应用本身，因为应用客户端更新会重新启动应用。单机安装保持一键更新的体验。

任何一次后端更新之后，应用还会重新检查自己的版本，如果 GUI 仍然落后，就会给出带一键 **Update desktop app** 操作的警告 —— 因此更新远程后端永远不会悄悄地让你停留在过时的桌面版本上。

[手动更新流程](https://hermes-agent.nousresearch.com/docs/getting-started/updating)同样适用于 GUI。

## 卸载

打开 **设置 → 关于 → 危险区域**，选择要移除的范围：

- **仅卸载 Chat GUI** —— 移除桌面应用及其数据；Hermes agent、你的配置和聊天记录都会保留。（等同于 `hermes uninstall --gui`。）
- **卸载 GUI + agent，保留我的数据** —— 移除应用和 agent，但保留配置、聊天记录和密钥，方便日后重装。（等同于 `hermes uninstall`。）
- **全部卸载** —— 移除应用、agent 以及所有用户数据。（等同于 `hermes uninstall --full`。）

应用会关闭以完成清理（清理在它退出之后执行，这样才能移除正在运行的应用包及其自己的 venv）。当本机没有安装 agent 时（例如一个连接远程后端的纯 GUI“精简”客户端），移除 agent 的选项会自动隐藏。

你也可以在终端里做同样的事 —— `hermes uninstall --gui` 只卸载 GUI，`hermes uninstall` / `hermes uninstall --full` 则连 agent 一起卸载。

:::note
在**源码检出目录**（一个 `hermes desktop` 开发构建）中运行 `hermes uninstall --gui` 时，还会移除工作区的 `node_modules` 和 `apps/desktop/{dist,release}` 构建产物，因为它们属于 GUI 构建产物。它们可以通过 `hermes desktop`（或 `npm install` + 重新构建）恢复 —— 但如果你正在积极开发桌面应用，那就要做好之后重新安装依赖的准备。
:::

## CLI 参考：`hermes desktop`

要通过 CLI 启动，直接运行 `hermes desktop` 即可。默认情况下它会安装工作区的 Node 依赖、为当前操作系统构建未打包的 Electron 应用，然后启动这个打包产物。

在 Linux 上，每次启动都会刷新 `$XDG_DATA_HOME/applications/hermes.desktop`（默认为 `~/.local/share/applications/hermes.desktop`），让 Hermes 出现在应用程序菜单中。要保留手工编辑过的条目，请禁用刷新：

```bash
hermes config set desktop.manage_launcher_entry false
```

缺失的条目仍然会被创建；这个标志只会阻止 `hermes desktop` 重写一个已经存在的条目。

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

所有与连接相关的内容都集中在一个设置页面上：**设置 → Gateways**。（较旧的版本把它拆分成独立的 **Gateway** 和 **Connections** 两个页面 —— 现在二者已合并，旧的 `?tab=connections` 深层链接会重定向到合并后的页面。）

**设置 → Gateways → Connection mode** 提供了本地 gateway 之外的几种选择：

- **Remote gateway** —— 填入你自己运行的 `hermes serve` 后端的 URL 并登录。本节其余部分讲解的就是这种模式。
- **Hermes Cloud** —— 登录一次 Hermes Cloud，然后从你账户下的 agent 中挑选；无需粘贴 URL。应用会发现你的 agent（如果你的账户跨越多个组织，还会提供组织选择器），连接到其中一个就会自动把会话切换过去。连接处于活跃状态时，状态栏会显示云端连接。

Gateway 连接是**机器级**的：Gateways 页面管理这台桌面可以连接哪些 gateway 后端，而 profile 则是*从*你连接的 gateway 上发现的。会话每次选择一个 gateway，相邻的 profile 导轨则选择在该 gateway 上发现的某个 profile。

### 多连接注册表

在同一个 **设置 → Gateways** 页面的更下方，**Registered gateways** 管理着一份具名列表，涵盖应用所知的每一个 Hermes gateway —— 本地运行时、任意数量的远程 gateway（局域网、Tailscale、互联网）、Hermes Cloud 实例以及 SSH 主机 —— 全部统一持久化在一处。你可以从侧边栏 profile 导轨右端的插头按钮（**Connect another Hermes gateway…**）或通过 **⌘K → Gateways** 跳到那里。完整指南（包括合并后的 agent 名单、`@name-device` 句柄、全体实例更新以及插件 SDK 接口）见[将桌面应用连接到多个 Hermes 实例](./multi-connection-desktop.md)。

- **每个连接都需要一个唯一名称**（设备名，例如 “Homelab” 或 “Work laptop”）。当同一个 profile 名称存在于多个已注册的 gateway 上时，各处界面会将其区分为 `@profile-device`（例如 `@research-homelab`）。
- **从 Sessions 侧边栏切换 gateway。** 当注册了不止一个 gateway 时，会出现一个具名的 gateway 选择器，它能应对任意规模的注册表，又不会让 gateway 看起来像 profile。相邻的 profile 导轨随后只显示该 gateway 的 agent，并记住在那里最后使用的 profile；profile 很多时会独立折叠显示。
- **选择重启后打开什么。** **Open on launch** 保持向后兼容的默认值 **Primary gateway**，也可以在 **Last used** gateway 成功连接后恢复到它。该偏好存储在应用程序包之外，桌面应用更新后依然保留。
- 在面板中**添加 / 编辑 / 删除 / 测试**连接。**Add** 流程提供全部四种类型 —— **Local**、**Hermes Cloud**、**Remote gateway** 和 **SSH**（当应用托管的本地条目存在时，Local 按钮会被禁用；添加云端条目时会有提示指向上面的登录/发现流程）。本地条目由应用管理，无法删除。**Test** 会直接探测该连接自身的 HTTP 和 WebSocket 两条通路。
- **重复项会在保存时被拒绝**：**本地**条目始终只有一个；远程和云端条目按规范化后的 URL 去重（去除首尾空白、剥掉末尾斜杠、转为小写 —— 跨这两种类型）；SSH 条目按规范化后的 `user@host:port` 加远程 profile 去重。
- 第一次运行带有注册表的版本时，已有的设置会被**自动导入**：你当前的全局连接以及任何旧版按 profile 的覆盖都会变成具名条目。旧版设置文件保持原样，所以旧版本依然可以正常工作。
- 云端条目来自上面的 Hermes Cloud 登录/发现流程，而不是手工输入的 URL。
- 令牌使用操作系统的密钥环加密存储（在没有密钥环的 Linux 上可显式选择以明文存储）。

并行路由已经上线：每个已注册的 gateway 都会按需连接自己的后端和套接字（按连接 + profile 区分），插件 SDK 暴露合并后的 agent 名单（`host.agents()` / `host.ensureAgent()`），Gateways 页面上的 **Update all instances** 会一次性向每个符合条件的 gateway 分发 `hermes update` —— Hermes Cloud 条目会被跳过（由平台负责更新），每个实例各自报告结果。


:::info 远程后端是一个正在运行的 `hermes serve` 进程
“远程后端”指的是运行在远程机器上的 **`hermes serve`** 服务 —— 那才是桌面应用要连接的进程。本节的一切都建立在该后端确实处于运行且可达的前提上。桌面应用不会替你启动它；需要由你（或一个 `systemd` 服务）让 `hermes serve` 在远程主机上持续运行，应用再连上去。如果你同时还使用消息频道（Telegram、Discord 等），**gateway** 是一个*独立*的长期运行进程，需要你单独启动 —— 参见设置步骤之后的说明。
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

**设置 → Gateways → Remote gateway：**

1. **远程 URL** —— `http://<backend-host>:9119`（如果你在前面加了反向代理，`/hermes` 之类的路径前缀也可以用）
2. **登录** —— 应用会检测后端宣告的是哪种提供方并相应调整按钮。对于用户名/密码的后端，它会显示一个 **Sign in** 按钮，打开一个凭据表单（填入第 1 步中的凭据）。对于 OAuth 后端，它会显示 **Sign in with `<provider>`**（例如 *Sign in with Nous Research*），点击后会走该提供方的浏览器登录流程。无论哪种方式，应用最终都会获得一个针对该后端的已认证会话。
3. **保存并重新连接** —— 把桌面外壳切换到远程后端。会话会自动刷新；只要设置了 `HERMES_DASHBOARD_BASIC_AUTH_SECRET`，你在重启之间都会保持登录状态。

你也可以不通过 UI，而是在启动应用前用环境变量 `HERMES_DESKTOP_REMOTE_URL` 设置后端 URL（它会覆盖应用内的设置）；登录仍然在 Gateways 设置面板中完成。

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
并在每次保存时热重载。已安装的插件可以在 **设置 → Plugins** 中实时管理。

完整参考见 [Desktop Plugin SDK](../developer-guide/desktop-plugin-sdk.md)。
（这与 [web dashboard 插件系统](./features/extending-the-dashboard.md)是两回事。）

同一个 设置 → Plugins 页面上的 **Agent plugins** 区段管理你安装的后端（agent 侧）[插件](./features/plugins.md) —— 用户、git、项目、pip 以及便携式安装。仓库自带的内置插件（平台适配器、提供方插件及类似插件）不会列在那里：它们默认启用，并在各自的界面中配置，因此该区段只专注于你自己添加的东西。当有两个或更多 profile 时，该区段也有自己的 **Applies to** 选择器，这样你无需切换整个应用就能列出并开关另一个 profile 的 agent 插件（后端的 `plugins.manage` RPC 为此接受一个可选的 `profile` 参数）。

## 故障排查

### 无需重启应用即可重新连接

如果某个桌面聊天或 bot 停止响应，而连接仍显示 **Connected**，请选中那个 bot/profile 或 gateway，打开状态栏的 gateway 菜单，点击 **Reconnect gateway**。对于处于打开、连接中和已断开状态的传输，Reconnect 都可用。它会重新拨号当前路由，而不会重启桌面应用，也不会主动关闭其他路由的套接字。所选套接字上正在进行的请求可能会被中断；这是一个显式的恢复操作，而不是重启后端或模型。

### 失败的轮次会指明出错的层

当一轮对话失败时，聊天会渲染一张错误卡片，指明**是哪一层失败了** —— 提供方/模型、自定义端点、流式连接、认证、计费、gateway、本地运行时或磁盘 —— 而不是一条笼统的错误提示。卡片会提供与该失败相匹配的恢复操作：

- **Retry** —— 原地重新运行失败的那一轮（当重试必然会再次复现同样的失败时隐藏，例如内容策略拒绝）。
- **Switch provider** —— 对于提供方、端点、认证和计费类失败，跳转到 设置 → Models。
- **Open logs** —— 在你的文件管理器中打开 `HERMES_HOME/logs`。在远程或 Cloud 连接上，按钮显示为 **Open Desktop logs**：它打开本地桌面端的日志（传输层证据），因为失败轮次的 gateway/agent 日志位于远程机器上。
- **Send diagnostics** —— 在明确的同意提示之后，把一个经过脱敏的调试包上传到 Nous 内部存储（与 `hermes debug share --nous` 使用同一条流水线；密钥总是会被脱敏，该调试包仅 Nous 员工可见，并在 14 天后自动删除）。成功后你会得到一个私密查看链接，可以粘贴到你的支持会话中，另外还有指向 GitHub Issues、Nous Portal Support 和 Discord 的快捷链接。在远程或 Cloud 连接上，后端会打包它自己的 agent/gateway 日志，并附上本地桌面端日志，这样支持人员能同时看到两半。
- **Copy error details** —— 复制一段紧凑的纯文本摘要（层、代码、提供方/模型、错误信息），你可以把它粘贴到 bug 报告或 Discord 中。

层的判断来自 agent 重试循环所使用的同一个错误分类器，因此它反映的是真实的失败语义，而不是根据消息文本做的猜测。早于该描述符的旧版后端仍然会渲染这张卡片，但使用通用标题，并只提供 Retry / Open logs / Copy error details 这几个操作。

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

### “The host key has CHANGED since you last connected”（SSH 远程）

如果你的 SSH 远程主机被重装，或者其主机密钥发生了轮换，SSH 会以失败关闭，桌面应用会锁定显示一个错误浮层而不是不断重试（在清除过期密钥之前，重试永远不可能成功）。确认这次变更是预期之内的，然后删除旧条目，再从浮层中重试：

```bash
ssh-keygen -R <host>
```

清除条目之后，点击 **Retry**（或在 设置 → Gateway 中重新应用该连接）—— 锁定会被重置，下一次启动会重新拨号。

### "Build desktop app" 卡在 Electron 下载

构建过程会从 `github.com/electron/electron/releases` 下载 Electron 运行时（约 114&nbsp;MB）。如果安装器卡在 **Build desktop app** 这一步，且实时输出反复出现 `retrying attempt=…`，说明你的网络（防火墙、代理或地区限制）正在屏蔽或限速 GitHub。

安装器会自动自愈：构建失败时，它会 (1) 清除损坏的 Electron 缓存 zip 并重试，然后 (2) 如果仍然失败且你没有设置 `ELECTRON_MIRROR`，就再通过事实上的 Electron 社区镜像 `npmmirror.com` 重试一次。`@electron/get` 会对下载做 SHASUM 校验，但校验和同样来自那个镜像 —— 这能发现损坏或不完整的下载，却发现不了被入侵的镜像。如果你不愿信任第三方主机，可以固定你自己的 `ELECTRON_MIRROR`（见下）；构建过程绝不会覆盖你已设置的值。

要**选择你自己的镜像**（例如企业内部的可信镜像），请在安装前设置 `ELECTRON_MIRROR` 或手动重新构建 —— 构建会遵循它，也不会覆盖它：

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
  bash -c 'cd "$HOME/.hermes/hermes-agent/apps/desktop" && CSC_IDENTITY_AUTO_DISCOVERY=false npm run pack'
```

**其他需要镜像的原生下载（例如 Windows 上的 `get-windows` 预编译包）：** 把 npm 键写入 `$HERMES_HOME/npmrc`（Windows 上为 `%LOCALAPPDATA%\hermes\npmrc`，其他系统为 `~/.hermes/npmrc`）—— 例如 `node_get_windows_binary_host_mirror=https://<mirror>/sindresorhus/get-windows/releases/download/`。只要该文件存在，更新器启动的每一次 `npm ci`/`npm run`（桌面、web 和 TUI 构建）都会把 `NPM_CONFIG_USERCONFIG` 指向它，因此这份配置能在 `hermes update` 之后保留；仓库根目录的 `.npmrc` 受 git 跟踪，每次更新都会被自动暂存（autostash），而 `~/.npmrc` 可能读不到，因为桌面端的交接流程继承的是 GUI 的环境。你自己设置的 `NPM_CONFIG_USERCONFIG` 永远不会被覆盖。

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

### macOS 权限与本地重新构建（TCC）

**用一个开关消除所有文件夹提示。** macOS 会随着 Hermes 访问各个文件夹而按类别逐一弹出提示（先是桌面，然后是下载，再是文稿，……）。一次**完全磁盘访问权限**授权就能永久覆盖所有这些类别 —— 而借助 Hermes 稳定的签名身份，它能在每次更新后依然有效：

1. 系统设置 → **隐私与安全性 → 完全磁盘访问权限**（或运行
   `open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`）
2. 启用你的终端应用 —— 如果你使用桌面应用，也启用 **Hermes.app**。
3. 完全退出并重新启动它们一次。

`hermes doctor` 会报告当前终端环境是否已经获得该授权，而 `hermes setup` 在 macOS 上若发现尚未授权，会显示这条提示。

macOS 是依据应用的*代码签名身份*而不是它的路径来记住权限授权的（完全磁盘访问权限、桌面/下载/文稿、辅助功能、自动化、麦克风）。本地构建的应用和自更新的应用都使用一个稳定的、固定标识符的 ad-hoc 签名，因此授权会在更新之间保留。

一次性说明：在*固定标识符签名*修复（PR #73681）之前授予给构建版本的授权，带有旧的按 cdhash 固定的要求。对于这些过期的授权，macOS 会继续把开关显示为开启，却仍会再次弹出提示，因为存储的授权已经和重新构建的二进制文件不匹配了 —— 而且新式提示没有“允许”按钮，所以看起来好像没什么可以重新勾选的。如果遇到这种情况，请把过期授权重置一次，再重新授予：

```bash
tccutil reset ScreenCapture com.nousresearch.hermes   # 每个服务重复一次
```

然后在系统设置中把新出现的条目打开，并完全退出、重新启动 Hermes。此后授权就会保持稳定。

若要获得最强的保证 —— 一个以证书为锚点的身份，也就是 yabai/skhd 用户所依赖的同一机制 —— 请一次性创建一个自签名代码签名证书，并告诉 Hermes 使用它。这条一步到位的命令会完成所有事情（在你的登录钥匙串中创建证书、授予 `codesign` 访问权限、写入配置，并重新签名打包好的应用）：

```bash
hermes desktop --setup-tcc-identity
```

或者手动操作：

1. 钥匙串访问 → 证书助理 → **创建证书…**
2. 名称：`Hermes Local Signing`，身份类型：*自签名根证书*，
   证书类型：**代码签名**。
3. 在钥匙串访问中，双击新证书 → **信任** → 把
   **代码签名** 设为*始终信任*（导入的自签名证书在被信任用于代码签名之前，
   并不是有效的签名身份 —— 之后
   `security find-identity -v -p codesigning` 应当会列出它）。
4. `hermes config set desktop.macos_signing_identity "Hermes Local Signing"`

给这条命令加上 `--identity <name>` 可以创建/使用另一个名称的证书（默认：`Hermes Local Signing`）。该命令是幂等的 —— 更新之后重新运行它，即可重新指向配置并重新签名重建后的应用。

下一次更新会用该证书重新签名重建后的应用；每一项 TCC 授权都会保留。不需要 Apple Developer 账户。经过公证的正式发布版本会被识别出来，并且永远不会被重新签名。

一次性说明：更改签名身份（包括此修复之后的第一次更新）会让应用的身份改变一次，因此 macOS 会最后再弹出一次提示。此后授权就会保持稳定。如果某项权限卡住了，用 `tccutil reset All com.nousresearch.hermes` 重置它，然后重新授予。

## 另请参阅

- [CLI 指南](./cli.md) —— 终端界面
- [TUI](./tui.md) —— `hermes --tui` 和 dashboard 聊天标签页所使用的现代终端 UI
- [Web Dashboard](./features/web-dashboard.md) —— 带内嵌聊天标签页的浏览器管理面板
- [配置](./configuration.md) —— 桌面应用读写的配置
- [Windows（原生）](./windows-native.md) —— 原生 Windows 安装路径
