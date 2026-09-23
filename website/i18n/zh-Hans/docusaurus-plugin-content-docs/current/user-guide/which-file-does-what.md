---
sidebar_position: 4
title: "哪个文件负责什么？"
description: "SOUL.md、USER.md、MEMORY.md 与 AGENTS.md 对比——一页看懂 agent 的各个文件、分别由谁编写，以及 agent 实际何时能看到它们"
---

# 哪个文件负责什么？ {#which-file-does-what}

“我告诉过我的 agent 一件事，它却忘了。”“哪个文件是我的 agent 的大脑？”“我编辑了 SOUL.md——为什么它还是不知道我的名字？”这些问题归根结底都是同一回事：Hermes Agent 由多个 markdown 文件共同塑造，而每个文件的职责各不相同。本页将它们汇总在一处。如需深入了解其中任何一个，请查看[持久记忆](/user-guide/features/memory)、[个性与 SOUL.md](/user-guide/features/personality) 以及[上下文文件](/user-guide/features/context-files)。

## 总表 {#the-master-table}

| 文件 | 内容 | 编写者 | Agent 何时看到它 | 存放位置 |
|------|---------------|---------------|------------------------|----------------|
| **SOUL.md** | Agent 的主要身份——个性、语气、沟通风格、在风格上应避免的事项 | 你。如果文件不存在，Hermes 会自动生成一个初始文件；已存在的文件永远不会被覆盖 | 系统 prompt 的第 1 个槽位，在会话开始时 | `~/.hermes/SOUL.md`（使用自定义 home 时为 `$HERMES_HOME/SOUL.md`）——永远不在工作目录中 |
| **USER.md** | 用户档案——你的名字、角色、偏好、沟通风格、期望 | Agent，通过 `memory` 工具（你可以用 `write_approval` 对保存进行把关，或通过 `hermes journey edit` 编辑条目） | 在会话开始时以冻结快照的形式注入系统 prompt | `~/.hermes/memories/` |
| **MEMORY.md** | Agent 的个人笔记——环境事实、项目约定、工具的怪癖、学到的东西 | Agent，通过 `memory` 工具（把关和编辑方式与 USER.md 相同） | 在会话开始时以冻结快照的形式注入系统 prompt | `~/.hermes/memories/` |
| **AGENTS.md** | 项目说明、约定、架构——命令、端口、路径、仓库特定的工作流 | 你（或项目的编写者） | 启动时从你的工作目录加载到系统 prompt 中；当 agent 进入子目录时，会逐步发现嵌套的副本 | 项目工作目录 + 子目录 |
| **.hermes.md** / **HERMES.md** | 项目说明，类似 AGENTS.md，但专属于 Hermes 且优先级最高 | 你 | 启动时加载到系统 prompt 中（先匹配到者优先于 AGENTS.md） | 你的项目——查找会一直向上走到 git 根目录 |

:::info 每个会话只有一个项目上下文文件
每个会话只加载**一种**项目上下文类型，先匹配到者生效：`.hermes.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`。`SOUL.md` 始终作为 agent 身份独立加载——它不属于该优先级链。完整列表（包括 `CLAUDE.md` 和 `.cursorrules` 兼容性）请参阅[上下文文件](/user-guide/features/context-files)。
:::

一个实用的简记法：

- **SOUL.md** 是 agent *是谁*——如果它应该在任何地方都跟随你，就放在这里。
- **USER.md** 是*你*是谁——由 agent 替你维护。
- **MEMORY.md** 是 agent *学到了*什么——同样由它自己维护。
- **AGENTS.md**（或 `.hermes.md`）是*项目*需要什么——如果它属于某个项目，就放在这里。

## “为什么它忘了我刚说的话？” {#why-did-it-forget-what-i-just-said}

记忆（MEMORY.md 和 USER.md）以**冻结快照**的形式注入系统 prompt，该快照只在会话开始时捕获一次——当 agent 在会话中途保存某些内容时，更改会立即持久化到磁盘，但要到下一次会话开始才会出现在系统 prompt 中。这是有意为之：它保留了 LLM 的前缀缓存以提升性能，而且工具响应始终显示实时状态，因此不会丢失任何东西——开启一个新会话，更新后的记忆就在那里。完整细节请参阅[记忆如何出现在系统 prompt 中](/user-guide/features/memory#how-memory-appears-in-the-system-prompt)。

## 常见混淆 {#common-mix-ups}

### “我把关于自己的事实写进了 SOUL.md，但 USER.md 仍然是空的” {#i-put-facts-about-myself-in-soulmd-but-usermd-stayed-empty}

`SOUL.md` 和 `USER.md` 是两个相互独立的系统，彼此从不互相填充。`SOUL.md` 是一个由**你**直接编辑的个性文件——它塑造语气和身份，其内容会作为 prompt 的第 1 个槽位原样注入。`USER.md` 是持久记忆的一部分，由 **agent** 通过 `memory` 工具写入。如果你希望关于自己的事实出现在 USER.md 中，就告诉 agent（“记住我喜欢简洁的回答”），它会自己保存——编辑 SOUL.md 不会填充记忆，记忆条目也不会改变人设。用 SOUL.md 来提供持久的语气和个性指引；把偏好和个人档案事实交给记忆。请参阅[SOUL.md 里应该放什么？](/user-guide/features/personality#what-should-go-in-soulmd)以及[两个目标详解](/user-guide/features/memory#two-targets-explained)。

### “我在会话中途告诉了它我的名字，它却表现得像从没听过一样” {#i-told-it-my-name-mid-session-and-it-acted-like-it-never-heard-it}

如果 agent 把你的名字保存到了记忆中，那么保存是成功的——可以通过 `memory` 工具的响应或 `hermes journey list` 进行确认。你看到的现象正是上文的冻结快照规则：系统 prompt 不会在会话中途刷新，因此*注入的*记忆块仍然显示会话开始时的状态。Agent 仍然可以在当前对话中使用你告诉它的内容（它就在上下文中），而保存的条目会从下一次会话起出现在系统 prompt 中。这同样适用于你在会话运行期间对 `SOUL.md` 或 `AGENTS.md` 所做的编辑：上下文是在会话开始时组装的，所以请重启会话以应用更改。

:::tip 快速决策指南
- 想改变 agent **说话**的方式？编辑 `~/.hermes/SOUL.md`——[个性与 SOUL.md](/user-guide/features/personality)。
- 想让 agent **记住某个事实**？直接告诉它——它会自己保存到记忆中。[持久记忆](/user-guide/features/memory)。
- 想设置**项目规则**？在项目中放一个 `AGENTS.md`（或 `.hermes.md`）——[上下文文件](/user-guide/features/context-files)。
- 需要**临时**改变个性？使用 `/personality`——它是会话级的叠加层，无需编辑任何文件。
:::

## 相关文档 {#related-docs}

- [持久记忆](/user-guide/features/memory) —— MEMORY.md、USER.md、`memory` 工具、容量上限、`write_approval`
- [个性与 SOUL.md](/user-guide/features/personality) —— SOUL.md 内容指引、`/personality` 预设、prompt 栈
- [上下文文件](/user-guide/features/context-files) —— AGENTS.md、`.hermes.md`、渐进式发现、安全扫描
