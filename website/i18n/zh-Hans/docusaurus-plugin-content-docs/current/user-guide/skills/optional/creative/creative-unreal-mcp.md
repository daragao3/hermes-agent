---
title: "Unreal Mcp"
sidebar_label: "Unreal Mcp"
description: "当用户想通过 Epic 官方内嵌于编辑器的 MCP 服务器（目录条目：unreal-engine）在 Unreal Engine 中执行任何操作时使用——搭建/打光/填充场景、放置与变换 Actor、编写 Blueprint、用 Sequencer 制作动画、创建材质实例、构图相机、截图、渲染..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Unreal Mcp

当用户想通过 Epic 官方内嵌于编辑器的 MCP 服务器（目录条目：unreal-engine）在 Unreal Engine 中执行任何操作时使用——搭建/打光/填充场景、放置与变换 Actor、编写 Blueprint、用 Sequencer 制作动画、创建材质实例、构图相机、截图、渲染、导入资产、运行 PIE 测试会话与自动化测试，或者完全用自然语言提示端到端地自动化编辑器，无需任何 Unreal 知识。内容涵盖工具检索式的发现流程（list_toolsets/describe_toolset/call_tool）、串行游戏线程调用纪律、ProgrammaticToolset 批处理、Blueprint 图 DSL 循环、场景制作数值（物理光照单位、曝光、比例约定）、完整的搭建配方、保存/撤销的良好习惯，以及用自定义 Python toolset 扩展工具面。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/creative/unreal-mcp` 安装 |
| 路径 | `optional-skills/creative/unreal-mcp` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `unreal`, `unreal-engine`, `ue5`, `3d`, `mcp`, `scenes`, `cinematics`, `lighting`, `gamedev` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Unreal Engine MCP Skill

这是 Hermes MCP 目录中 `unreal-engine` 条目的配套 skill。该 MCP 服务器
（Epic 官方的实验性 "Unreal MCP" 插件，内部 id 为
`ModelContextProtocol`）运行在 Unreal 编辑器进程**内部**，把编辑器功能
以带类型的工具形式暴露出来。此 skill 教你如何用好它：
发现实时的工具面、安全地编排调用顺序、把自然语言的诉求翻译成真正好看的场景，
并在视觉上验证成果。除了启动编辑器之外，用户不应需要动手操作编辑器。

## 使用时机

当用户想在 Unreal Engine 中做任何事情时使用：搭建或布置关卡、
生成/移动/删除 Actor、设置光照与氛围、创建或调整材质实例、构图相机镜头、
截图或渲染、导入资产、检查场景或 UI、运行自动化测试，或者编写编辑器脚本。
既适用于单个动作（"把太阳调成黄金时刻"），也适用于
完整的多步骤项目（"给我搭一个阴郁的林间空地，中间有篝火，并渲染一张镜头"）。

不适用于：DCC 式的网格建模/雕刻（请用 `blender-mcp` 并把结果导入），
或编辑 Unreal C++ 项目源码（那是普通的写代码工作——用终端即可；
此 skill 面向的是运行中的编辑器）。

## 前置条件

分两部分，顺序如下：Hermes 连接之前，编辑器侧必须先就绪。

### 一次性设置：编辑器侧

1. Unreal 编辑器 **5.8+**，并已打开一个项目。（macOS：必须安装完整的 Xcode
   并接受其许可协议——否则编辑器首次启动就会退出；参见常见陷阱。）
2. **Edit > Plugins** — 启用 **Unreal MCP**（它依赖的 Toolset Registry
   会自动启用）。出现提示时重启编辑器。
3. 带类型的 toolset 与服务器是分开发布的：请在同一个 Plugins 浏览器中一并启用
   **AllToolsets** 插件。Unreal MCP 自身**不**附带任何
   工具——AllToolsets 才提供随附的 toolset（SceneTools、
   ActorTools、MaterialInstanceTools、ObjectTools 等）；跳过它的话，
   服务器虽能连上，但 agent 无工具可调。
4. **Edit > Editor Preferences > General > Model Context Protocol** — 启用
   **Auto Start Server**。默认绑定为 `http://127.0.0.1:8000/mcp`
   （端口/路径可在同一面板中配置；服务器名为 `unreal-mcp`）。
   若想改为手动启动，请在编辑器控制台（反引号键）中运行
   `ModelContextProtocol.StartServer`。

### 一次性设置：Hermes 侧

    hermes mcp install unreal-engine

这会写入指向 `http://127.0.0.1:8000/mcp` 的 `mcp_servers.unreal-engine`
HTTP 条目，并探测运行中的服务器以获取其工具。请在编辑器 + 服务器
均已启动时运行它，这样探测到的才是真实的工具面。如果用户在 Editor Preferences
中改过端口/路径，请相应修改 `~/.hermes/config.yaml` 中
`mcp_servers.unreal-engine` 下的 `url`。

**不要**为 Hermes 使用 `ModelContextProtocol.GenerateClientConfig`——它写出的是
供 Claude Code/Cursor 等使用的 `.mcp.json` 风格文件。Hermes 是通过目录条目
从 `config.yaml` 连接的。

### 每次会话

1. 启动 Unreal 编辑器，等待项目加载完成；确认服务器已启动
   （Output Log 中会显示绑定地址，或手动运行
   `ModelContextProtocol.StartServer`）。
2. 启动 Hermes 会话。工具会注册为 `mcp_unreal_engine_*`。如果
   看不到它们：说明编辑器没有先启动——先启动编辑器，再新开一个
   Hermes 会话。
3. 健全性检查：调用 `mcp_unreal_engine_list_toolsets`，确认能返回 toolset。

## 工具面：靠发现，而非固定清单

插件默认运行在**工具检索模式**：`tools/list` 只返回
三个元工具，所有真正的工具都通过它们触达。在 Hermes 中
它们呈现为：

| Hermes 工具 | 用途 |
|---|---|
| `mcp_unreal_engine_list_toolsets` | 列出每个已注册 toolset 的名称与描述 |
| `mcp_unreal_engine_describe_toolset` | 获取某个具名 toolset 下各工具的完整 JSON schema |
| `mcp_unreal_engine_call_tool` | 以参数调用某个具名工具并取得结果 |

发现流程，始终按此顺序：

1. `list_toolsets` → 查看当前项目实际拥有哪些能力分组
   （工具面取决于项目：已启用的插件、Game Feature Plugin，
   以及任何自定义 toolset 都会贡献工具）。返回的名称是**完全限定**的
   （`editor_toolset.toolsets.scene.SceneTools`、
   `EditorToolset.EditorAppToolset`）——请原样用作 `toolset_name`。
2. 对你需要的分组调用 `describe_toolset` → 读取真实的参数
   schema。绝不要猜参数名——schema 才是契约。
3. 调用 `call_tool`，传入限定的 toolset 名称、**短**工具名
   （`find_actors`，不是带点的形式），以及符合 schema 的参数。

把学到的信息在本次会话内缓存起来；只有当编辑器侧发生变化
（启用了新插件、编写了新 toolset、运行了 `RefreshTools`）时才重新列举。

另一种预加载模式（在 Editor Preferences 中关闭 `Enable Tool Search`）
会把每个工具都作为独立的 `mcp_unreal_engine_<tool>` 条目公布。此时发现
发生在 `hermes mcp install`/`configure` 阶段。工具检索
模式是默认值，也是此 skill 的假设前提；它还能让 schema 的 token 不必
出现在每次 API 调用中，因此更推荐它。

随附 toolset 的目录、编写自定义 toolset，以及完整的插件配置/控制台命令参考，
请见 `references/tool-surface.md`。

## 操作循环

每个 Unreal 任务都遵循同一个循环：

1. **先检查。** 先列出 toolset，然后在动手之前查询场景/关卡状态。
   绝不要假定关卡是空的或处于默认状态。在不熟悉的项目中，还应检查
   项目注册的 Agent Skill
   （`call_tool` → `AgentSkillToolset.ListSkills`）：如果存在匹配的项目 skill，
   其指令优先于此 skill 的通用默认做法。
2. **以小而单一目的的调用来行动。** 每次 `call_tool` 只做一个逻辑步骤。
   服务器在**游戏线程上串行**执行工具——一个庞大的
   单体操作会冻结编辑器 UI 直到结束，还有客户端超时的风险。
   例外：当需要对 5 个以上同类操作做循环时，
   一次 `ProgrammaticToolset.execute_tool_script` 调用可以在服务端批量完成，
   同时不违反串行规则
   （`references/advanced-workflows.md`）。
3. **绝不要发出重叠的调用。** 不要在同一轮中批量发起多个
   `mcp_unreal_engine_*` 调用——Hermes 会并发执行批量调用，
   而针对游戏线程的并行调用会死锁或
   失败。严格做到：一次一个调用，等待结果，再下一个。此规则
   **优先于**通用的并行工具调用指导。
4. **读取每一个结果。** 许多工具（Blueprint 编译、材质编辑、
   控件创建）会在响应体中报告成功/失败，而**不会**抛出协议级异常。
   凡不是明确成功的结果，都要停下来诊断，而不是耸耸肩略过。写入属性后，
   把值读回来——有几条写入路径会静默地什么都不做（参见常见陷阱）。
5. **在视觉与结构两方面验证。** 每完成一个里程碑，就通过查询
   你改动过的 Actor/属性来确认状态；当构图重要时，抓取一张视口
   截图（抓取选项见 `references/tool-surface.md`；
   用 `vision_analyze` 分析该图片——你就是艺术总监，请自行评判）。
6. **勤保存。** 编辑器的改动在保存 package/关卡之前只存在于内存中；
   编辑器崩溃会丢失上次保存之后的一切，而且 MCP
   的改动无法可靠撤销。任何批量改动**之前和之后**都要保存，
   每个里程碑之后也要保存。
7. **具体地汇报。** Actor 标签、资产路径（`/Game/...`）、截图/渲染产物的
   文件位置。

工作期间需牢记的世界规则：

- 单位是**厘米**；坐标轴为 **Z 轴向上**、X 轴向前；旋转以
  度为单位（Rotator：绕 X 为 Roll，绕 Y 为 Pitch，绕 Z 为 Yaw）。人眼
  高度约 165 cm；一扇门约 210×90 cm。完整表格见
  `references/scene-craft.md`。
- 内容路径使用长包名：项目内容用 `/Game/Folder/Asset.Asset`，
  引擎图元用 `/Engine/BasicShapes/Cube.Cube`。
- Actor 的**标签**（你在 Outliner 中看到的，可设置、不唯一）不同于 Actor
  的**名称**（内部使用，唯一）。优先通过标签/类查询来定位 Actor，
  然后保留工具返回的句柄。
- 优先使用物理上合理的光照数值（lux/candela/开尔文），而不是任意的
  亮度数字——但**首先**要读取现有太阳光的
  强度，以了解该场景的校准约定；模板世界
  常常是围绕 `intensity: 10` 校准的，直接套用物理数值会把画面
  曝爆（数值见 `references/scene-craft.md`，
  校准规则见 `references/pitfalls.md` 第 12b 条）。

## 从自然语言到场景

用户给出的是意图，而非规格。先翻译，再动手：

1. **提取需求要点。** 主体、氛围、时间、室内/室外、
   风格、交付物（截图？渲染？可玩关卡？）。最多问
   一轮澄清问题，然后就定下来——你是技术
   总监，别把 Unreal 术语丢回给用户。
2. **规划搭建顺序。** 行之有效的顺序：关卡/环境外壳 →
   体块搭建（把主要几何体/网格摆到位）→ 光照 + 氛围 → 材质
   → 场景装饰/细节 → 相机 → 抓图/渲染。多步骤搭建请把计划
   写成待办列表发出来。
3. **按上面的循环搭建**，一次一个里程碑，每个里程碑都截图。
4. **自己做艺术指导。** 把每张截图与需求要点比对：剪影是否
   清晰可读？光的方向/强度是否可信？地平线是否不在正中？相对于
   人体高度参照物，比例是否正确？先改好再往下走。
5. **交付。** 以文件形式给出截图/渲染（`MEDIA:` 路径），并附上
   关卡中现有内容及其保存位置的简短说明。

`references/recipes.md` 提供了完整的实战搭建案例（室外日光场景、
阴郁室内、黄金时刻电影感镜头 + 渲染、资产导入与摆放），
含确切的调用序列与数值。

## 参考文件

按需加载；同时始终牢记 SKILL.md 层面的规则。

| 参考文件 | 内容 |
|---|---|
| `references/tool-surface.md` | 随附 toolset 目录、发现协议细节、插件控制台命令/CVar/开关、截图与抓取路径、MCP Inspector 调试、用自定义 Python/C++ toolset 扩展 |
| `references/advanced-workflows.md` | 经实机验证的进阶工作流：ProgrammaticToolset 批处理、Blueprint DSL 编写循环（create→DSL→compile→spawn）、PIE 测试会话、Sequencer 概览（140 个工具）、LogsToolset 自我调试、自动化测试、语义资产检索、配置设置、分场景决策表 |
| `references/scene-craft.md` | 数值速查表：物理光强、色温、曝光/EV100、雾密度、氛围配方（正午/黄金时刻/阴天/夜晚/室内）、比例表、内容路径约定 |
| `references/recipes.md` | 端到端实战搭建，含确切调用序列 |
| `references/pitfalls.md` | 安装、运行与工作流上的陷阱及其修复方法——首次使用前请阅读，遇到异常时也请回看 |

## 常见陷阱（重点摘要——完整列表见 references/pitfalls.md）

- **启动顺序很重要。** 先起编辑器 + 服务器，再开 Hermes
  会话。缺少 `mcp_unreal_engine_*` 工具 = 顺序搞反了。
- **一次只调一个。** 游戏线程串行执行；不要批量，不要重叠。
- **每次调用期间编辑器 UI 会冻结。** 这是设计使然（在游戏线程上
  执行）。长时间操作时请提前告知用户；保持调用粒度小。
- **模态对话框会阻塞一切。** 一旦某次工具调用打开（或撞上）编辑器的
  模态对话框，就会一直卡住，直到有人手动关掉它。如果某次调用
  长时间无响应，请让用户去编辑器里看看是否有对话框。
- **长时间操作会超时。** Hermes 每次调用的默认上限是 120 秒；资产
  导入、大型关卡保存和渲染都可能超过它。渲染/导入密集的会话请调高
  `~/.hermes/config.yaml` 中的
  `mcp_servers.unreal-engine.timeout`。
- **陈旧的工具 schema。** 在编写/热重载 toolset 或启用
  插件之后，请在编辑器控制台运行 `ModelContextProtocol.RefreshTools`
  并重新 `list_toolsets`。新增的 C++ `UFUNCTION` 需要完整重启编辑器——
  Live Coding 无法让它们浮现。
- **这是实验性插件。** API 和工具形态可能随引擎版本变化；
  请相信 `describe_toolset` 而不是记忆，也包括本 skill 中的
  示例。当文档与实时 schema 冲突时，以实时 schema 为准。
- **不要把该服务器暴露到 localhost 之外。** 按设计它仅监听回环且无鉴权。
  绝不要建议把它绑定到更大范围。
- **许可提示。** 服务器启动时会记录：经由该插件传输给所连接 LLM 服务的
  数据属于 UE EULA（§6(e)）下的 Licensed Technology——用户有责任
  确保其 LLM 提供商不会用这些数据训练模型。若用户问及数据处理，请主动说明。

## 验证清单

- [ ] 会话开始时 `list_toolsets` 能返回 toolset（连接正常）
- [ ] 首次编辑之前已查询场景状态（没有假定场景为空）
- [ ] 每个里程碑之后：重新查询改动过的 Actor/属性，并对照需求要点
      检查截图
- [ ] 每个里程碑之后以及最终都保存了关卡/已修改的 package
- [ ] 交付物确实存在于磁盘上（已确认截图/渲染路径），并以绝对路径
      告知用户
- [ ] 编辑器处于干净状态：没有待处理的模态框，没有意外未保存的内容，
      已明确告知用户创建/改动了什么以及位置在哪
