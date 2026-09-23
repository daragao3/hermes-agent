---
sidebar_position: 3
title: "内置工具参考"
description: "Hermes 内置工具权威参考，按工具集分组"
---

# 内置工具参考

本页记录 Hermes 的内置工具，按工具集分组。可用性因平台、凭据和已启用的工具集而异。

**当前注册表快速统计：** 约 86 个工具 —— 10 个浏览器工具（核心）+ 2 个 CDP 门控浏览器工具、4 个文件工具、4 个 Home Assistant 工具、2 个终端工具（`terminal`、`process`）、12 个桌面 GUI 工具（`read_terminal`、`close_terminal`、`open_preview`、`close_preview`、`read_preview`、`drive_preview`、`annotate_preview`、`read_window_below`、`focus_pane`、`react_to_message`、`tour`、`tip` —— 仅限桌面应用会话）、2 个 Web 工具、5 个 Feishu 工具、7 个 Spotify 工具（由内置 `spotify` 插件注册）、5 个 Yuanbao 工具、12 个 kanban 工具（在 kanban 调度器生成 agent 时注册）、3 个 project 工具（桌面/GUI 会话）、2 个 Discord 工具、3 个视频工具（`video_generate`、`xai_video_edit`、`xai_video_extend`），以及若干独立工具（`memory`、`clarify`、`delegate_task`、`execute_code`、`cronjob`、`session_search`、`skill_view`/`skill_manage`/`skills_list`、`text_to_speech`、`image_generate`、`vision_analyze`、`video_analyze`、`todo`、`computer_use`、`x_search`）。

:::tip MCP 工具
除内置工具外，Hermes 还可从 MCP 服务器动态加载工具。MCP 工具以 `mcp__<server>__` 为前缀（例如，`github` MCP 服务器的 `mcp__github__create_issue`）。配置方法见 [MCP 集成](/user-guide/features/mcp)。
:::

## `browser` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `browser_back` | 在浏览器历史记录中导航回上一页。需先调用 `browser_navigate`。 | — |
| `browser_click` | 点击快照中由 ref ID 标识的元素（如 `@e5`）。ref ID 显示在快照输出的方括号中。需先调用 `browser_navigate` 和 `browser_snapshot`。 | — |
| `browser_console` | 获取当前页面的浏览器控制台输出和 JavaScript 错误。返回 `console.log`/`warn`/`error`/`info` 消息及未捕获的 JS 异常。用于检测静默 JavaScript 错误、失败的 API 调用和应用警告。需先调用… | — |
| `browser_get_images` | 获取当前页面所有图片的列表，包含 URL 和 alt 文本。可用于查找供 vision 工具分析的图片。需先调用 `browser_navigate`。 | — |
| `browser_navigate` | 在浏览器中导航到某个 URL，初始化会话并加载页面。必须在其他浏览器工具之前调用。对于简单信息检索，优先使用 `web_search` 或 `web_extract`（更快、更省）。当需要… 时使用浏览器工具。 | — |
| `browser_press` | 按下键盘按键。适用于提交表单（Enter）、导航（Tab）或键盘快捷键。需先调用 `browser_navigate`。 | — |
| `browser_scroll` | 向某个方向滚动页面。用于显示当前视口上方或下方的更多内容。需先调用 `browser_navigate`。 | — |
| `browser_snapshot` | 获取当前页面无障碍树的文本快照。返回带 ref ID（如 `@e1`、`@e2`）的交互元素，供 `browser_click` 和 `browser_type` 使用。`full=false`（默认）：仅含交互元素的紧凑视图。`full=true`：完整… | — |
| `browser_type` | 向由 ref ID 标识的输入框中输入文本。先清空字段，再输入新文本。需先调用 `browser_navigate` 和 `browser_snapshot`。 | — |
| `browser_vision` | 对当前页面截图，以便你直观地检查它。当需要了解页面的外观时使用——尤其适用于 CAPTCHA、视觉验证挑战、复杂布局，或文本快照遗漏重要视觉信息的情况。在原生支持视觉的模型上，截图会直接附带；否则回退到辅助视觉模… | — |

## `browser` 工具集（CDP 门控工具）

这两个工具属于 `browser` 工具集，但仅在会话启动时可访问 Chrome DevTools Protocol（CDP）端点时才注册——通过 `/browser connect`、`browser.cdp_url` 配置、Browserbase 会话或 Camofox。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `browser_cdp` | 发送原始 Chrome DevTools Protocol 命令。用于高层 `browser_*` 工具未覆盖的浏览器操作的逃生舱口。参见 https://chromedevtools.github.io/devtools-protocol/ | CDP 端点 |
| `browser_dialog` | 响应原生 JavaScript 对话框（alert / confirm / prompt / beforeunload）。先调用 `browser_snapshot`——待处理的对话框会出现在其 `pending_dialogs` 字段中。然后调用 `browser_dialog(action='accept'\|'dismiss')`。 | CDP 端点 |

## `clarify` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `clarify` | 在继续之前需要澄清、反馈或决策时向用户提问。支持三种模式：1. **单选** —— 最多 4 个选项；用户选择其一，或通过第 5 个"其他"选项自行输入答案。2. **多选** —— `multi_select=true` 渲染复选框，返回所选项的列表。3. **开放式** —— 不提供选项；用户输入自由格式的回答。选项按推荐程度从高到低排序，因此第一个选项在所有界面上都标注为 `(Recommended)` 并默认高亮；该标签仅用于展示，agent 读取的答案中会将其去除。在经典 CLI 中，多选使用空格键切换复选框；在没有原生复选框 UI 的消息平台上，用户以逗号/空格分隔的编号（例如 "1, 3"）或选项文本回复。 | — |

### 一次提出多个问题 {#asking-multiple-questions-at-once}

`clarify` 工具还接受一个 `questions` 数组（2–5 个相互独立的问题，每个都有自己的 `choices` 和 `multi_select`），这样 agent 就能把多个澄清需求合并到一个提示中，而不必依次提问。结果是一个顺序相同的 `responses` 数组，并回显每个问题的 `id`（如果提供了的话）。

各界面的行为：

- **桌面端**在一张卡片上显示所有问题。所选项和输入的答案会在本地暂存，一个 **Confirm and continue** 按钮（在每个问题都有答案后启用）会提交整批答案。在确认之前，暂存的答案都可以修改。Skip 会取消整批问题。
- **TUI 和 CLI** 显示一个紧凑的状态列表（`✓` 已回答 / `▸` 当前 / `·` 待回答），只展开当前问题的选项。Enter 锁定当前答案并跳到下一个未回答的问题；Tab 在问题之间切换，可按任意顺序作答；Esc 取消整批问题。
- **消息平台**（Telegram、Discord……）回退为通过现有的单问题提示逐个提问。如果用户停止回应，剩余的问题不会再发送。

如果提示在中途超时，用户已锁定的答案会被保留：工具结果会携带这些答案以及 `"timed_out": true`，未回答的条目留空，这样 agent 就能区分用户是有意跳过还是不在场。

## `code_execution` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `execute_code` | 运行可以编程方式调用 Hermes 工具的 Python 脚本。当需要 3 次以上工具调用且调用之间有处理逻辑、需要在大型工具输出进入上下文前过滤/压缩、需要条件分支（…）时使用。 | — |

## `cronjob` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `cronjob` | 统一的定时任务管理器。使用 `action="create"`、`"list"`、`"update"`、`"pause"`、`"resume"`、`"run"` 或 `"remove"` 管理任务。支持带一个或多个附加 skill 的 skill 驱动任务，`update` 时 `skills=[]` 可清除已附加的 skill。Cron 任务在无当前聊天上下文的全新会话中运行。 | — |

## `delegation` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `delegate_task` | 在隔离上下文中生成子 agent；每个子 agent 拥有独立的对话、终端会话和工具集，只有其最终摘要会返回给你。单个任务提供 'goal'，并行批量任务提供 'tasks'（数量限制和嵌套规则… | — |

## `feishu_doc` 工具集

仅限飞书文档评论智能回复处理器（`gateway/platforms/feishu_comment.py`）使用。不在 `hermes-cli` 或常规飞书聊天适配器中暴露。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `feishu_doc_read` | 根据 `file_type` 和 token 读取飞书/Lark 文档（Docx、Doc 或 Sheet）的完整文本内容。 | 飞书应用凭据 |

## `feishu_drive` 工具集

仅限飞书文档评论处理器使用。驱动云盘文件的评论读写操作。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `feishu_drive_add_comment` | 在飞书/Lark 文档或文件上添加顶级评论。 | 飞书应用凭据 |
| `feishu_drive_list_comments` | 列出飞书/Lark 文件的全文档评论，最新的排在最前。 | 飞书应用凭据 |
| `feishu_drive_list_comment_replies` | 列出特定飞书评论线程（全文档或局部选区）的回复。 | 飞书应用凭据 |
| `feishu_drive_reply_comment` | 在飞书评论线程上发布回复，支持可选的 `@` 提及。 | 飞书应用凭据 |

## `file` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `patch` | 对文件进行精准的查找替换编辑。用于替代终端中的 `sed`/`awk`。使用模糊匹配（9 种策略），轻微的空白/缩进差异不会导致失败。返回统一差异格式。编辑后自动运行语法检查… | — |
| `read_file` | 带行号和分页功能读取文本文件。用于替代终端中的 `cat`/`head`/`tail`。输出格式：`LINE_NUM\|CONTENT`。找不到文件时建议相似文件名。对大文件使用 `offset` 和 `limit`。超过约 100K 字符的读取会在行边界处截断，并返回 `next_offset`。Jupyter notebook（.ipynb）、Word 文档（.docx）和 Excel 工作簿（.xlsx）… | — |
| `search_files` | 搜索文件内容或按名称查找文件。用于替代终端中的 `grep`/`rg`/`find`/`ls`。基于 Ripgrep，比 shell 等效命令更快。内容搜索（`target='content'`）：在文件内进行正则搜索。输出模式：带行号的完整匹配… | — |
| `write_file` | 将内容写入文件，完全替换现有内容。用于替代终端中的 `echo`/`cat heredoc`。自动创建父目录。**覆盖整个文件** —— 精准编辑请使用 `patch`。对 .py/.json/.yaml/.toml 及其他有 lint 支持的语言自动运行语法检查；只会呈现本次写入新引入的错误。 | — |

## `homeassistant` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `ha_call_service` | 调用 Home Assistant 服务以控制设备。使用 `ha_list_services` 发现各域的可用服务及其参数。 | — |
| `ha_get_state` | 获取单个 Home Assistant 实体的详细状态，包括所有属性（亮度、颜色、温度设定值、传感器读数等）。 | — |
| `ha_list_entities` | 列出 Home Assistant 实体。可按域（light、switch、climate、sensor、binary_sensor、cover、fan 等）或区域名称（客厅、厨房、卧室等）过滤。 | — |
| `ha_list_services` | 列出用于设备控制的可用 Home Assistant 服务（动作）。显示每种设备类型可执行的操作及其接受的参数。用于发现如何控制通过 `ha_list_entities` 找到的设备。 | — |

## `computer_use` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `computer_use` | 通过 cua-driver 在后台控制桌面——截图（SOM / vision / AX）、点击 / 拖拽 / 滚动 / 输入 / 按键 / 等待、`list_apps`、`focus_app`。**不会**抢占用户的光标或键盘焦点。适用于任何支持工具的模型。支持 macOS、Windows 和 Linux。 | `cua-driver` 在 `$PATH` 中（通过 `hermes tools` 安装）。 |


:::note
**Honcho 工具**（`honcho_profile`、`honcho_search`、`honcho_context`、`honcho_reasoning`、`honcho_conclude`）不再是内置工具。它们通过 `plugins/memory/honcho/` 的 Honcho 记忆提供者插件提供。安装和使用方法见 [Memory Providers](../user-guide/features/memory-providers.md)。
:::

## `image_gen` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `image_generate` | 通过用户配置的后端（FAL.ai、OpenAI、OpenAI Codex 认证、xAI、Krea），从文本 prompt（提示词）生成图片（文本生成图片），或编辑/转换已有图片（图片生成图片）。传入 `image_url` 可编辑图片，传入 `reference_image_urls` 可提供风格参考；两者都省略则为文本生成图片。模型由用户配置，agent 不可选择。返回单个图片 URL 或本地路径。 | FAL_KEY / OPENAI_API_KEY / Codex OAuth / xAI OAuth / KREA_API_KEY |

## `kanban` 工具集

在以下情况下注册：(a) agent 由 kanban 调度器生成（设置了 `HERMES_KANBAN_TASK` 环境变量），或 (b) 在显式启用 `kanban` 工具集的 profile 中运行。任务范围的 worker 使用生命周期工具处理其分配的任务；编排器 profile 还额外获得 `kanban_list` 和 `kanban_unblock` 等看板路由工具。完整工作流见 [Kanban 多 Agent](/user-guide/features/kanban)。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `kanban_show` | 显示分配给当前 worker 的活跃 kanban 任务（标题、描述、评论、依赖项）。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_list` | 带过滤器列出看板任务。仅限编排器；对调度器生成的任务 worker 隐藏。 | 含 `kanban` 工具集的 profile |
| `kanban_complete` | 用结构化交接载荷（结果、产物、后续事项）将当前任务标记为完成。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_block` | 因需向用户提问而阻塞当前任务——调度器暂停、呈现问题，并在人工回复后恢复。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_request_review` | 将实现交给审阅者，附带 `summary`、可选的结构化 `metadata` 以及可选的审阅者 profile。会把同一个任务移至 `review`；这不属于阻塞，也不影响阻塞循环的计数。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_request_changes` | 针对正在被认领的审阅运行给出的审阅者结论。关闭该审阅运行，重新应用父任务门控，并在不使用阻塞的情况下把任务路由回原来的实现者。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_heartbeat` | 在长时间运行的操作期间发送进度心跳，让调度器知道 worker 仍在运行。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_comment` | 在不改变任务状态的情况下向任务线程添加评论——适用于呈现中间发现。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_create` | 从当前任务派生子任务。由编排器和生成后续任务的 worker 使用。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_link` | 用父 → 子依赖边链接任务。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_unblock` | 当所有父任务均已完成时将被阻塞的任务移至 `ready`；只要仍有父任务未完成则移至 `todo`。仅限编排器；对调度器生成的任务 worker 隐藏。 | 含 `kanban` 工具集的 profile |
| `kanban_attach` | 以内联字节（base64）的方式向任务附加文件。作为真正的附件存储在任务的附件目录下，上限 25 MB。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_attach_url` | 通过 URL 向任务附加文件——Hermes 在服务端下载并将其存储为真正的附件（上限 25 MB）。仅支持 http/https URL。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |
| `kanban_attachments` | 列出附加到任务的文件：id、文件名、content_type、大小、上传者以及磁盘上的绝对路径。 | `HERMES_KANBAN_TASK` 或 `kanban` 工具集 |

## `project` 工具集

用于驱动桌面[项目（Projects）](../user-guide/cli.md)的工具——具名的多文件夹工作区。在启用 `project` 工具集时注册（主要用于桌面应用/仪表板界面）。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `project_create` | 创建一个桌面项目（具名工作区），并将当前聊天切换到该项目中。传入 `path` 可将其锚定到某个仓库/文件夹。 | — |
| `project_list` | 列出桌面项目以及当前处于活跃状态的项目。 | — |
| `project_switch` | 将当前聊天切换到已有项目（按名称、slug 或 id）；会把会话工作区移动到该项目的主文件夹。 | — |

## `memory` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `memory` | 将重要信息保存到跨会话持久化的记忆中。你的记忆会在会话启动时出现在系统 prompt 中——这是你在对话之间记住用户信息和环境信息的方式。何时保存… | — |

## `session_search` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `session_search` | 搜索存储在本地会话数据库中的历史会话，或在某个会话内滚动浏览。基于 FTS5 检索；返回数据库中的实际消息（无 LLM 调用）。四种形态：发现（传入 `query`）、滚动（传入 `session_id` + `around_message_id`）、读取（仅传入 `session_id`）、浏览（无参数）。 | — |

## `skills` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `skill_manage` | 管理 skill（创建、更新、删除）。Skill 是你的程序性记忆——针对重复任务类型的可复用方法。新 skill 保存到 `~/.hermes/skills/`；现有 skill 可在其所在位置修改。操作：create（完整 SKILL.m…） | — |
| `skill_view` | Skill 允许加载特定任务和工作流的信息，以及脚本和模板。加载某个 skill 的完整内容或访问其链接文件（参考资料、模板、脚本）。首次调用返回 SKILL.md 内容及… | — |
| `skills_list` | 列出可用 skill（名称 + 描述）。使用 `skill_view(name)` 加载完整内容。 | — |

## `terminal` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `process` | 管理通过 `terminal(background=true)` 启动的后台进程。操作：`list`（显示所有）、`poll`（检查状态 + 新输出）、`log`（带分页的完整输出）、`wait`（阻塞直到完成或超时）、`kill`（终止）、`write`（发送…） | — |
| `terminal` | 在 Linux 环境中执行 shell 命令。文件系统在调用之间持久化。对长时间运行的服务器设置 `background=true`。设置 `notify_on_complete=true`（配合 `background=true`）可在进程完成时自动收到通知——无需轮询。**不要**使用 `cat`/`head`/`tail`——使用 `read_file`。**不要**使用 `grep`/`rg`/`find`——使用 `search_files`。 | — |

## `desktop_ui` 工具集

对来源为 Hermes 桌面应用的会话启用，无论其连接的是哪种后端（本地、SSH、URL 或 Hermes
Cloud）。在 CLI、TUI、消息平台和 cron 会话中不存在。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `read_terminal` | 读取 Hermes 桌面 GUI 应用内终端面板（本聊天旁边的嵌入式 shell）当前显示的内容。 | — |
| `close_terminal` | 关闭 Hermes 桌面 GUI 中某个后台进程的只读终端标签页。**不会**杀死该进程——只是移除标签页/视图；要停止它请使用 process(action='kill')。 | — |
| `open_preview` | 在 Hermes 桌面应用中聊天旁边的预览面板里打开一个网页 URL、localhost 开发服务器 URL 或文件路径。 | — |
| `close_preview` | 关闭聊天旁边的预览面板，或其中的一个标签页。省略 `url` 关闭整个面板；传入 URL 或文件路径则关闭对应的标签页。 | — |
| `read_preview` | 读取 Hermes 桌面 GUI 预览面板当前显示的内容——应用内浏览器的页面文本（URL + 标题 + 渲染后的文本，可用 `start`/`count` 分页），或文件/产物标签页的标识。 | — |
| `drive_preview` | 与应用内浏览器中打开的页面交互：`elements` 盘点可点击和可输入的元素（每个都有一个为其命名的 ref，如 `btn-sign-in` 或 `inp-email`，以及角色、标签和值），然后 `click`、`hover`、`type`、`scroll` 和 `press` 作用于某个 ref，`back`/`forward`/`reload` 则驱动面板的历史记录。指针和键盘是真实输入，因此悬停菜单会展开。ref 在页面导航之前一直有效，即便经历重建元素的重新渲染也不失效，因此在首次盘点之后，每个操作只返回一个增量——新增、移除、变化或重新绑定了什么——而不是再次返回整个页面。 | — |
| `annotate_preview` | 在应用内浏览器中为某个元素加上轮廓，并保留该标记直到被移除——与 `drive_preview` 工作时绘制的临时提示相对应的刻意标注。`add` 为某个 ref 添加标记（可附带简短标签），`remove` 移除一个，`clear` 全部清除。标记跟随其元素，并随元素一起消失，因此导航会清除它们。 | — |
| `read_window_below` | 识别紧挨在 Hermes 桌面窗口下方的操作系统窗口——应用名称、标题、边界（仅元数据，从不包含像素）。在 macOS 上，只有在已授予屏幕录制权限时才会显示其他应用的标题；该工具从不请求这项权限。 | — |
| `focus_pane` | 在 Hermes 桌面应用中显示并聚焦某个面板（chat、files、terminal、review、sessions）。 | — |
| `react_to_message` | 用单个 emoji 回应一条消息，类似 iMessage 的 tapback。需在 Settings → Appearance 中选择启用（`display.message_reactions`）。 | — |
| `tour` | 提供实时引导游览：调暗屏幕、高亮某个元素，并附上带解说的弹出框（driver.js）。适用于 Hermes 应用自身的 UI，以及预览面板中打开的任意页面；`targets` 发现屏幕上有什么，`show` 逐步解说，`start` 把上一步/下一步控件交给用户。 | — |
| `tip` | 用一个小的强调色气泡和箭头指向某个元素——`tour` 的低调版本，不调暗屏幕、没有聚光灯，也没有上一步/下一步。使用相同的 `data-tour` 标识和相同的 `tour(action='targets')` 发现调用。 | — |

### 游览 {#tours}

`tour` 工具会自行发现目标——调用 `action='targets'`，它就会返回屏幕上每个可定位的元素，附带选择器、标签和一个 `stable` 标志。稳定选择器以身份为键（`data-tour`、`id`、`data-testid`、`aria-label`），能在重新渲染后保留；基于位置的 `nth-child` 路径则不能，因此稳定选择器排在前面，应优先使用。

要为某个元素赋予你自己的持久标识，请这样标记它：

```html
<div data-tour="composer">…</div>
```

标识应用在**基础组件**上，而不是调用处，因此一次编辑就能为所有实例命名。已有的标识如下：

| 标识 | 所命名的对象 |
|---|---|
| `overlay-nav` | 任意路由浮层（settings、cron、profiles、agents）的左侧导航 |
| `nav-<id>` | 该导航中的一行——`nav-models`、`nav-appearance`、… |
| `field-<schemaKey>` | 某一设置行，按其配置键命名——`field-model`、`field-provider`、… |
| `page-tabs` | 任意 `PageSearchShell` 页面（artifacts、skills、…）上的筛选标签页 |
| `artifact-card` | 网格中的一张产物卡片 |

添加新界面时，请以同样的方式标记其共享的基础组件，而不是逐个屏幕打标记——这样能让游览词汇保持精简，并防止选择器失效。

同一个引擎也为桌面应用中精心编排的（非 agent）游览提供支持，因此一项功能可以附带自己的演示流程：

```ts
import { startTour, showTourStep, stopTour } from '@/lib/tour'

startTour([
  { selector: '[data-tour="composer"]', title: 'Composer', text: 'Type here.' },
  { selector: '[data-tour="files"]', title: 'Files', text: 'Browse your project.' }
])
```

某一步还可以把应用切换到其目标所在的位置，游览结束时会将一切恢复原状：

```ts
startTour([
  { navigate: '/artifacts', selector: '[data-tour="page-tabs"]', title: 'Filters', text: '…' },
  { pane: 'sessions', selector: '[data-slot="sidebar"]', title: 'Sessions', text: '…' }
])
```

`navigate` 接受一个路由路径，`pane` 接受一个桌面面板名称。两者都会在进入该步骤时执行，延迟挂载的目标会被等待，而关闭游览——无论通过何种方式，包括 Esc——都会回到游览开始时的位置。

将 `'preview'` 作为第二个参数传入，即可针对预览面板中的页面而非应用本身运行。

### 提示 {#tips}

提示（tip）是去掉了排场的游览步骤：一个气泡、一个箭头，没有遮罩，也没有需要翻页的内容。
它适合这样一句话：如果用手指指着它所说的东西会更清楚——“模型名称是一个按钮”——
而调暗整个应用则显得小题大做。

`tip` 工具接受与 `tour(action='targets')` 报告的相同选择器，因此一次调用就能同时完成
两者的发现，上面那些持久的 `data-tour` 标识也可以为两者命名目标。屏幕上同一时间只有一个
提示；新的提示会替换上一个。

应用也可以显示自己的提示，按顺序遍历内置的应用功能目录，节奏类似游戏加载画面的小贴士，
而不是通知：最早在启动几分钟后出现，之后每六小时最多一次，并且只在真正空闲的时刻出现。
来自 Hermes 的提示与之共享这个冷却时间，因此它也会为用户换来六小时不受轮播打扰的清静。
用 ✕ 关闭某条轮播提示会永久撤下该提示，而对应的设置行可以把它们恢复。

提示和游览默认都已开启，可在 Settings → Appearance 中关闭
（`display.in_app_tips`、`display.in_app_tours`）。关闭对 Hermes 和应用同样生效：
该开关会同步到所连接 gateway 的配置，工具也会从模型的 schema 中移除，因此 agent 永远不会
被告知一个它不允许使用的界面。与所有 schema 变更一样，这会在下一个会话生效——正在进行的
对话会保留其开始时的工具集，在此期间应用会拒绝该调用。

## `todo` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `todo` | 管理当前会话的任务列表。适用于包含 3 个以上步骤的复杂任务，或用户提供多个任务时。不带参数调用可读取当前列表。条目可以嵌套：条目的可选 `parent` 字段指向另一个条目的 id，使其成为子任务——各界面会以缩进的树形结构渲染。 | — |

## `vision` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `vision_analyze` | 使用 AI 视觉分析图片。在支持视觉的主模型上，将原始图片像素作为多模态工具结果返回，使模型在下一轮能原生看到图片。在纯文本主模型上，回退到辅助视觉模型描述图片并以文本形式返回描述。两种情况下工具签名完全相同。 | — |

## `video` 工具集

可选工具集（默认 `hermes-cli` 集中不加载）。通过 `--toolsets video` 添加，或在 `toolsets:` 配置中包含 `video`。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `video_analyze` | 分析来自 URL 或文件路径的视频内容——字幕、场景分解、关键时间戳和视觉描述。 | — |

## `video_gen` 工具集

可选工具集（默认 `hermes-cli` 集中不加载）。通过 `--toolsets video_gen` 添加，或在 `hermes tools` → Video Generation 中启用（同时引导你选择后端）。

后端以插件形式存放于 `plugins/video_gen/<name>/`：

- **xAI Grok-Imagine** —— 文本生成视频和图片生成视频（SuperGrok OAuth 或 `XAI_API_KEY`）。
- **FAL.ai** —— Veo 3.1、Pixverse v6、Kling O3（需要 `FAL_KEY`）。

单个 `video_generate` 工具涵盖两种模态——传入 `image_url` 可为静态图片制作动画，省略则从文本生成。活跃后端自动路由到正确的端点。工具描述在会话启动时重建，以反映活跃后端的实际能力（模态、宽高比、分辨率、时长范围、最大参考图片数、音频支持）。后端开发见 [视频生成提供者插件](/developer-guide/video-gen-provider-plugin)。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `video_generate` | 使用用户配置的视频生成后端，从文本 prompt 生成视频（文本生成视频）或为静态图片制作动画（图片生成视频）。传入 `image_url` 可为该图片制作动画；省略则从文本生成。后端自动路由到正确端点。在 `video` 字段中返回 HTTP URL 或绝对文件路径。 | 活跃的 `video_gen` 插件 + 其凭据（如 `XAI_API_KEY`、`FAL_KEY`） |
| `xai_video_edit` | 使用 xAI Imagine 编辑已有视频。特定于该提供方（独立于 `video_generate`）。`video_url` 必须是先前某次 Imagine 结果的公开 HTTPS MP4 URL。 | xAI Imagine 凭据（SuperGrok OAuth 或 `XAI_API_KEY`） |
| `xai_video_extend` | 使用 xAI Imagine 延长已有视频。特定于该提供方（独立于 `video_generate`）。`video_url` 必须是先前某次 Imagine 结果的公开 HTTPS MP4 URL。 | xAI Imagine 凭据（SuperGrok OAuth 或 `XAI_API_KEY`） |

## `web` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `web_search` | 在网络上搜索信息。默认返回最多 5 条结果，包含标题、URL 和描述。接受可选的 `limit`（1-100，默认 5）。查询直接传递给配置的后端，因此当后端支持时，`site:domain`、`filetype:pdf`、`intitle:word`、`-term`、`"exact phrase"` 等运算符可能有效。 | EXA_API_KEY 或 PARALLEL_API_KEY 或 FIRECRAWL_API_KEY 或 TAVILY_API_KEY 或 PERPLEXITY_API_KEY 或 KEENABLE_API_KEY |
| `web_extract` | 从网页 URL 提取内容。以 markdown/文本形式返回干净的页面内容（无 LLM 摘要——速度快）。也支持 PDF URL（arxiv 论文、文档）——直接传入 PDF 链接即可。字符预算内（默认 15000）的页面完整返回；更大的页面返回头+尾窗口，并附带页脚，指向保存在磁盘上的完整文本。每次调用最多 5 个 URL。 | EXA_API_KEY 或 PARALLEL_API_KEY 或 FIRECRAWL_API_KEY 或 TAVILY_API_KEY 或 PERPLEXITY_API_KEY 或 KEENABLE_API_KEY |

## `x_search` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `x_search` | 使用 xAI 内置的 `x_search` Responses 工具搜索 X（Twitter）帖子、主页和话题串。用于只读地发现公开 X 上的当前讨论、反应或观点（而非通用网页）。它不会发帖、回复、点赞、发私信、上传媒体、删除内容或查看已认证的 X 账户——这些需要单独的已认证 X API 接口（例如 `xurl` skill）。默认关闭——通过 `hermes tools` → 🐦 X (Twitter) Search 选择启用。仅在配置了 xAI 凭据时注册 schema（check_fn 门控）。 | XAI_API_KEY **或** xAI Grok OAuth（SuperGrok / Premium+）登录 |

## `tts` 工具集

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `text_to_speech` | 将文本转换为语音音频。返回平台以语音消息形式传递的 `MEDIA:` 路径。在 Telegram 上以语音气泡播放，在 Discord/WhatsApp 上作为音频附件。在 CLI 模式下保存到 `~/voice-memos/`。语音和提供者… | — |

## `discord` 工具集

在 `hermes-discord` 平台工具集（仅 gateway）上注册。使用与消息适配器相同的 bot token。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `discord` | 读取并参与 Discord 服务器。操作包括 `search_members`、`fetch_messages`、`send_message`、`react`、`fetch_channel`、`list_channels` 等。 | `DISCORD_BOT_TOKEN` |

## `discord_admin` 工具集

在 `hermes-discord` 平台工具集上注册。审核操作需要 bot 持有相应的 Discord 权限。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `discord_admin` | 通过 REST API 管理 Discord 服务器：列出 guild/频道/角色，创建/编辑/删除频道，管理角色授予、禁言、踢出和封禁。 | `DISCORD_BOT_TOKEN` + bot 权限 |

## `spotify` 工具集

由内置 `spotify` 插件注册。需要 OAuth token——运行一次 `hermes auth spotify` 进行授权。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `spotify_playback` | 控制 Spotify 播放、查看当前播放状态或获取最近播放的曲目。 | Spotify OAuth |
| `spotify_devices` | 列出 Spotify Connect 设备或将播放转移到其他设备。 | Spotify OAuth |
| `spotify_queue` | 查看用户的 Spotify 队列或向其添加项目。 | Spotify OAuth |
| `spotify_search` | 在 Spotify 目录中搜索曲目、专辑、艺术家、播放列表、节目或单集。 | Spotify OAuth |
| `spotify_playlists` | 列出、查看、创建、更新和修改 Spotify 播放列表。 | Spotify OAuth |
| `spotify_albums` | 获取 Spotify 专辑元数据或专辑曲目。 | Spotify OAuth |
| `spotify_library` | 列出、保存或移除用户已保存的 Spotify 曲目或专辑。 | Spotify OAuth |

## `hermes-yuanbao` 工具集

仅在 `hermes-yuanbao` 平台工具集上注册。元宝是腾讯的聊天应用；这些工具驱动其私信/群组/表情包 API。

| 工具 | 描述 | 所需环境 |
|------|------|----------|
| `yb_query_group_info` | 查询群组（应用内称为"派/Pai"）的基本信息：名称、群主、成员数。 | 元宝凭据 |
| `yb_query_group_members` | 查询群组成员（用于 `@` 提及、按名称查找用户、列出机器人）。 | 元宝凭据 |
| `yb_send_dm` | 向群组中的用户发送私信，支持可选的媒体文件。 | 元宝凭据 |
| `yb_search_sticker` | 按关键词搜索元宝内置表情（TIM 表情）目录。 | 元宝凭据 |
| `yb_send_sticker` | 向当前元宝聊天发送内置表情。 | 元宝凭据 |
