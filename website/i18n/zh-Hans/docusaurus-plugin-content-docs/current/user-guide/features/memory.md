---
sidebar_position: 3
title: "持久化记忆"
description: "Hermes Agent 如何跨会话记忆——MEMORY.md、USER.md 与会话搜索"
---

# 持久化记忆

Hermes Agent 拥有有界、经过整理的记忆，可跨会话持久保存。这使它能够记住你的偏好、项目、环境以及已学到的内容。

## 工作原理

两个文件构成 Agent 的记忆：

| 文件 | 用途 | 字符上限 |
|------|------|----------|
| **MEMORY.md** | Agent 的个人笔记——环境事实、约定、已学内容 | 2,200 字符（约 800 tokens） |
| **USER.md** | 用户档案——你的偏好、沟通风格、期望 | 1,375 字符（约 500 tokens） |

两个文件均存储于 `~/.hermes/memories/`，在会话开始时以冻结快照的形式注入系统 prompt（提示词）。Agent 通过 `memory` 工具管理自身记忆——可添加、替换或删除条目。

:::info
字符上限使记忆保持聚焦。记忆**不会**自动压缩：当一次写入将超出上限时，
`memory` 工具会返回错误，而不是悄悄丢弃条目。随后 Agent 会自行腾出空间——
在同一轮中整合或删除条目，然后再重试（参见[记忆已满时会发生什么](#what-happens-when-memory-is-full)）。
注意 `replace` 同样受上限约束：把一个条目换成更长的内容仍可能溢出，
因此新内容必须缩短（或删除另一个条目）才能放得下。
:::

## 记忆在系统 Prompt 中的呈现方式

每次会话开始时，记忆条目从磁盘加载并以冻结块的形式渲染到系统 prompt 中：

```
══════════════════════════════════════════════
MEMORY (your personal notes) [67% — 1,474/2,200 chars]
══════════════════════════════════════════════
User's project is a Rust web service at ~/code/myapi using Axum + SQLx
§
This machine runs Ubuntu 22.04, has Docker and Podman installed
§
User prefers concise responses, dislikes verbose explanations
```

格式包含：
- 标头，显示存储类型（MEMORY 或 USER PROFILE）
- 使用百分比和字符计数，让 Agent 了解容量
- 以 `§`（节符）分隔的各条目
- 条目可以是多行

**冻结快照模式：** 系统 prompt 注入在会话开始时捕获一次，会话中途不会改变。这是有意为之——目的是保留 LLM 的前缀缓存以提升性能。当 Agent 在会话期间添加或删除记忆条目时，更改会立即持久化到磁盘，但要到下一次会话开始时才会出现在系统 prompt 中。工具响应始终显示实时状态。

## Memory 工具操作

Agent 使用 `memory` 工具执行以下操作：

- **add** — 添加新的记忆条目
- **replace** — 用更新内容替换现有条目（通过 `old_text` 进行子字符串匹配）
- **remove** — 删除不再相关的条目（通过 `old_text` 进行子字符串匹配）

没有 `read` 操作——记忆内容在会话开始时自动注入系统 prompt。Agent 将其记忆作为对话上下文的一部分来查看。

### 子字符串匹配

`replace` 和 `remove` 操作使用简短的唯一子字符串匹配——不需要完整的条目文本。`old_text` 参数只需是能唯一标识某一条目的子字符串即可：

```python
# If memory contains "User prefers dark mode in all editors"
memory(action="replace", target="memory",
       old_text="dark mode",
       content="User prefers light mode in VS Code, dark mode in terminal")
```

如果子字符串匹配到多个条目，则返回错误，要求提供更具体的匹配内容。

## 两个目标说明

### `memory` — Agent 的个人笔记

用于 Agent 需要记住的环境、工作流及经验教训相关信息：

- 环境事实（操作系统、工具、项目结构）
- 项目约定和配置
- 发现的工具怪癖与变通方法
- 已完成任务的日记条目
- 有效的技能和技术

### `user` — 用户档案

用于记录用户的身份、偏好和沟通风格：

- 姓名、角色、时区
- 沟通偏好（简洁 vs 详细、格式偏好）
- 反感的事项和需要避免的内容
- 工作流习惯
- 技术水平

## 什么该保存，什么该跳过

### 主动保存这些内容

Agent 会自动保存——无需你主动要求。当它学到以下内容时会保存：

- **用户偏好：** "我更喜欢 TypeScript 而非 JavaScript" → 保存到 `user`
- **环境事实：** "此服务器运行 Debian 12，安装了 PostgreSQL 16" → 保存到 `memory`
- **纠正信息：** "Docker 命令不要用 `sudo`，用户已在 docker 组中" → 保存到 `memory`
- **约定：** "项目使用 tab 缩进、120 字符行宽、Google 风格 docstring" → 保存到 `memory`
- **已完成的工作：** "2026-01-15 将数据库从 MySQL 迁移到 PostgreSQL" → 保存到 `memory`
- **明确请求：** "记住我的 API 密钥每月轮换一次" → 保存到 `memory`

### 跳过这些内容

- **琐碎/显而易见的信息：** "用户询问了 Python"——太模糊，没有实用价值
- **容易重新发现的事实：** "Python 3.12 支持 f-string 嵌套"——可以网络搜索
- **原始数据转储：** 大型代码块、日志文件、数据表——对记忆来说太大
- **会话特定的临时内容：** 临时文件路径、一次性调试上下文
- **已在上下文文件中的信息：** SOUL.md 和 AGENTS.md 的内容

## 容量管理

记忆有严格的字符上限，以保持系统 prompt 的有界性：

| 存储 | 上限 | 典型条目数 |
|------|------|-----------|
| memory | 2,200 字符 | 8-15 条 |
| user | 1,375 字符 | 5-10 条 |

### 记忆已满时的处理

当你尝试添加会超出上限的条目时，工具返回错误：

```json
{
  "success": false,
  "error": "Memory at 2,100/2,200 chars. Adding this entry (250 chars) would exceed the limit. Consolidate now: use 'replace' to merge overlapping entries into shorter ones or 'remove' stale or less important entries (see current_entries below), then retry this add — all in this turn.",
  "current_entries": ["..."],
  "usage": "2,100/2,200"
}
```

Agent 应当：
1. 读取当前条目（显示在错误响应中）
2. 识别可以删除或整合的条目
3. 使用 `replace` 将相关条目合并为更简短的版本
4. 然后 `add` 新条目

**最佳实践：** 当记忆使用率超过 80%（在系统 prompt 标头中可见）时，在添加新条目之前先整合现有条目。例如，将三个独立的"项目使用 X"条目合并为一个综合性的项目描述条目。

### 优质记忆条目的实际示例

**紧凑、信息密度高的条目效果最佳：**

```
# Good: Packs multiple related facts
User runs macOS 14 Sonoma, uses Homebrew, has Docker Desktop and Podman. Shell: zsh with oh-my-zsh. Editor: VS Code with Vim keybindings.

# Good: Specific, actionable convention
Project ~/code/api uses Go 1.22, sqlc for DB queries, chi router. Run tests with 'make test'. CI via GitHub Actions.

# Good: Lesson learned with context
The staging server (10.0.1.50) needs SSH port 2222, not 22. Key is at ~/.ssh/staging_ed25519.

# Bad: Too vague
User has a project.

# Bad: Too verbose
On January 5th, 2026, the user asked me to look at their project which is
located at ~/code/api. I discovered it uses Go version 1.22 and...
```

## 重复防护

记忆系统会自动拒绝完全重复的条目。如果你尝试添加已存在的内容，系统返回成功并附带"未添加重复项"的消息。

## 安全扫描

记忆条目在被接受之前会扫描注入和数据外泄模式，因为它们会被注入系统 prompt。匹配威胁模式（prompt 注入、凭据外泄、SSH 后门）或包含不可见 Unicode 字符的内容将被拦截。

## 会话搜索

除 MEMORY.md 和 USER.md 之外，Agent 还可以使用 `session_search` 工具搜索过去的对话：

- 所有 CLI 和消息会话均存储在 SQLite（`~/.hermes/state.db`）中，支持 FTS5 全文搜索
- 搜索查询返回数据库中的实际消息——无 LLM 摘要，无截断
- Agent 可以找到数周前讨论过的内容，即使它们不在活跃记忆中
- Agent 还可以在找到的任意会话中向前或向后滚动

```bash
hermes sessions list    # 浏览过去的会话
```

有关三种调用形式（发现 / 滚动 / 浏览）和响应格式，请参阅[会话搜索工具](/user-guide/sessions#session-search-tool)。

### session_search 与 memory 的对比

| 特性 | 持久化记忆 | 会话搜索 |
|------|-----------|---------|
| **容量** | 约 1,300 tokens 总计 | 无限制（所有会话） |
| **速度** | 即时（在系统 prompt 中） | 约 20ms FTS5 查询，约 1ms 滚动 |
| **成本** | 每次 prompt 均有 token 开销 | 免费——无 LLM 调用 |
| **使用场景** | 始终可用的关键事实 | 查找特定的过去对话 |
| **管理方式** | 由 Agent 手动整理 | 自动——所有会话均存储 |
| **Token 开销** | 每次会话固定（约 1,300 tokens） | 按需（仅在搜索时产生） |

**记忆**用于应始终在上下文中的关键事实。**会话搜索**用于"我们上周讨论过 X 吗？"这类需要 Agent 从过去对话中回忆具体内容的查询。

## 配置

```yaml
# In ~/.hermes/config.yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200   # ~800 tokens
  user_char_limit: 1375     # ~500 tokens
  write_approval: false     # false = 自由写入（默认） | true = 需要审批
```

## 控制记忆写入（`write_approval`）

默认情况下，Agent 会自由保存记忆——包括在一轮对话之后运行的后台自我改进
复盘所产生的保存。如果你更希望先审批这些保存，请设置
`memory.write_approval: true`。这是一个简单的开关式门控，同时作用于
**前台**对话轮和后台复盘：

| `write_approval` | 行为 |
|------------------|------|
| `false`（默认） | 自由写入——门控关闭（引入门控之前的行为）。 |
| `true` | 保存任何内容前都需要审批。在交互式 CLI 中，前台写入会内联提示你（条目足够短，可以完整阅读）。其他所有场景——消息平台、脚本以及后台自我改进复盘——写入都会被**暂存**，通过 `/memory pending` 审阅。 |

> 若要完全关闭记忆（而不只是加门控），请设置 `memory_enabled: false`。

在 CLI 或任意消息平台上审阅暂存的写入：

```
/memory pending             # 列出暂存的记忆写入（自动产生的会标记 [auto]）
/memory approve <id>        # 应用其中一条（或 'all'）
/memory reject <id>         # 丢弃其中一条（或 'all'）
/memory approval on         # 打开门控（或 'off'）并持久化该设置
```

这正是"Agent 保存了一个关于我的错误假设"的解法：设置
`write_approval: true`，此后每一次保存——尤其是那些未经请求的后台保存——
都要等你点头或否决之后才会进入你的档案。

## 后台复盘通知（`display.memory_notifications`）

在一轮对话之后，后台自我改进复盘可能会悄悄保存一条记忆或更新某个技能。
这是 Hermes 具备同意意识的学习闭环：反复出现的纠正和持久的工作流经验会
变成紧凑的记忆条目或流程化技能，而 `write_approval` 可以把这些写入暂存
起来供你审阅，再决定是否影响后续会话。默认情况下它会在聊天中显示一行简短的
`💾 Memory updated`，让你知道发生了什么。你可以控制它的啰嗦程度：

```yaml
display:
  memory_notifications: on    # off | on（默认） | verbose
```

| 取值 | 行为 |
|------|------|
| `off` | 不发聊天通知。复盘照常运行、照常写入——只是你看不到提示行。 |
| `on`（默认） | 通用提示行，例如 `💾 Memory updated`、`💾 Skill 'foo' patched`。 |
| `verbose` | 附带变更内容的紧凑预览，例如 `💾 Memory ➕ User prefers terse replies`，或一段 `"old" → "new"` 的技能 diff 片段。 |

> 这只控制**网关**的聊天通知。复盘本身以及对记忆/技能存储的写入不受此设置
> 影响。可通过 `display.platforms.<platform>.memory_notifications` 按平台设置。

## 在更便宜的模型上运行复盘（`auxiliary.background_review`）

复盘默认运行在你的**主聊天模型**上，重放整段对话——这些内容已经在 prompt
缓存中预热，因此只是廉价的缓存读取。如果主模型很贵，你可以改用更便宜的模型
来跑复盘：

```yaml
auxiliary:
  background_review:
    provider: openrouter
    model: google/gemini-3-flash-preview   # auto（默认）= 主聊天模型
```

当你把它指向与主模型**不同**的模型时，复盘会在那里以显著更低的成本运行
（基准测试中约为 3–5 倍差距）。由于不同的模型本来也无法复用主模型的 prompt
缓存，这个分支会自动重放一份紧凑的对话**摘要**（近期轮次逐字保留 + 较早内容
的总结），而不是完整记录——从而尽量减少写入新缓存的内容。捕获质量依然成立：
在测试中，记忆捕获与主模型复盘完全一致，技能捕获也几乎一致。

保持 `auto`（或将其设为你的主模型），一切照旧——复盘仍在主模型上运行，
并使用完整的热缓存重放。

## 控制技能写入（`skills.write_approval`）

技能使用同样的开关式门控，但审阅体验有所不同，因为 `SKILL.md` 远大于一个
聊天气泡所能容纳的篇幅：

```yaml
skills:
  write_approval: false     # false = 自由写入（默认） | true = 需要审批
```

当 `write_approval: true` 时，技能写入（create / edit / patch / write_file /
delete）无论来源如何都会**暂存**。你在内联界面审阅一行摘要，完整 diff 则保留
在带外查看：

```
/skills pending             # 列出暂存的技能写入，每条附一行摘要
/skills diff <id>           # 完整 unified diff（建议在 CLI 或仪表盘中查看）
/skills approve <id>        # 应用（或 'all'）
/skills reject <id>         # 丢弃（或 'all'）
/skills approval on         # 打开门控（或 'off'）并持久化该设置
```

在消息平台上，你可以根据摘要与元数据批准某个技能；想读完整改动时，可在
CLI / 仪表盘上执行 `/skills diff`，或直接查看 `~/.hermes/pending/skills/<id>.json`
下的暂存文件。完整细节参见 [为 Agent 技能写入加门控](/user-guide/features/skills#gating-agent-skill-writes-skillswrite_approval)。


## 外部记忆提供商

对于超出 MEMORY.md 和 USER.md 范围的更深层持久化记忆，Hermes 内置了 8 个外部记忆提供商插件——包括 Honcho、OpenViking、Mem0、Hindsight、Holographic、RetainDB、ByteRover 和 Supermemory。

外部提供商与内置记忆**并行**运行（而非替代），并增加了知识图谱、语义搜索、自动事实提取和跨会话用户建模等能力。

```bash
hermes memory setup      # 选择并配置提供商
hermes memory status     # 查看当前激活状态
```

有关每个提供商的完整详情、设置说明和对比，请参阅[记忆提供商](./memory-providers.md)指南。