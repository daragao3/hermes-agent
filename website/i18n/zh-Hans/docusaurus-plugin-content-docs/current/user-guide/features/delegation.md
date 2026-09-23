---
sidebar_position: 7
title: "子智能体委派"
description: "使用 delegate_task 为并行工作流生成隔离的子智能体"
---

# 子智能体委派 {#subagent-delegation}

`delegate_task` 工具会生成具有隔离上下文、继承工具访问权限和独立终端会话的子 AIAgent 实例。每个子智能体获得全新的对话并独立运行——只有其最终摘要会进入父智能体的上下文。

顶层模型调用会自动在后台运行。Hermes 会立即返回句柄，使对话可以继续，并在任务完成后将结果作为新消息发送回来。编排者子智能体会等待自己的工作线程完成，以便在返回前综合结果。

## 完成结果的交付 {#completion-delivery}

消息网关只有在其适配器真正调度了该事件、或将其插入会话队列之后，才会确认后台完成事件。缺少处理器、会话路由不匹配以及队列已满，都会使完成事件保持待处理状态以便重试；这些准入拒绝不会消耗持久化的交付尝试预算。一次成功的准入会在运行中的网关内抑制重复交付，但并不能证明模型轮次或出站回复已经完成。崩溃/重启后的交付仍是"至少一次"，并受现有重放时限约束；真正的传输失败则保留其有界重试策略。

不可用的 API 服务器路由会保持待处理状态，且不会反复发出缺失路由警告。格式错误的消息路由仍会产生诊断信息。在 API 服务器上，异步委派完成只会添加一条持久化的时间线交付行：下一次模型轮次由客户端负责。将后台进程通知设为 `off` 时，仍会静默消化模式监视（pattern-watch）事件。

## 后台进程的生命周期 {#background-process-lifetime}

后台终端进程属于启动它的智能体。委派结束并关闭子智能体时，系统会终止它仍在运行的进程，包括先前轮次启动的任务，但不会停止父智能体或其他子智能体拥有的进程。共享终端环境并不意味着转移进程所有权。

子智能体应等待构建、测试等有明确结束条件的后台命令完成，再返回最终摘要。如果 CI 监视器或服务器需要在子智能体结束后继续运行，应由父会话启动；返回进程 ID 不会将所有权转移给父智能体。

## 单任务 {#single-task}

```python
delegate_task(
    goal="Debug why tests fail",
    context="Error: assertion in test_foo.py line 42"
)
```

## 并行批处理 {#parallel-batch}

默认最多 10 个并发子智能体（可配置，无硬性上限）：

```python
delegate_task(tasks=[
    {"goal": "Research topic A", "context": "Focus on recent primary sources"},
    {"goal": "Research topic B", "context": "Compare the leading explanations"},
    {"goal": "Fix the build", "context": "Project root: /home/user/project"}
])
```

## 结构化输出（`output_schema`） {#structured-output-output_schema}

每个任务都可以携带一个可选的 `output_schema`，即子智能体最终答案必须通过校验的 JSON Schema 对象。子智能体会预先看到该 schema，作为输出约定；答案返回时由父智能体进行校验，校验失败时会向子智能体发送恰好一次有界的纠正轮次，其中逐字附上校验错误（不会重新粘贴 schema）。随后该任务的结果会增加 `schema_valid`（true/false）字段，失败时还会增加 `schema_errors`。

```python
delegate_task(
    tasks=[{
        "goal": "Check which of these three endpoints return 200",
        "context": "https://a.example, https://b.example, https://c.example",
        "output_schema": {
            "type": "object",
            "properties": {
                "healthy": {"type": "array", "items": {"type": "string"}},
                "failing": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["healthy", "failing"]
        }
    }]
)
```

schema 应保持宽松：只把你真正会读取的字段设为必填。没有 `output_schema` 的任务不受影响。

## 子智能体上下文的工作方式 {#how-subagent-context-works}

:::warning 关键：子智能体一无所知
子智能体以**全新对话**启动。它们对父智能体的对话历史、之前的工具调用或委派前讨论的任何内容一无所知。子智能体的唯一上下文来自父智能体调用 `delegate_task` 时填写的 `goal` 和 `context` 字段。
:::

唯一例外：当父智能体有已解析的工作区目录时，每个子智能体的系统提示都会嵌入该工作区的**项目上下文文件**（`.hermes.md` > AGENTS.md 链 > CLAUDE.md > `.cursorrules`——与主智能体系统提示相同的发现逻辑、优先级和大小上限；SOUL.md 除外）。在仓库中工作的子智能体无需重新发现即可遵循仓库自身的约定。

这意味着父智能体必须在调用中传递子智能体所需的**一切**信息：

```python
# BAD - subagent has no idea what "the error" is
delegate_task(goal="Fix the error")

# GOOD - subagent has all context it needs
delegate_task(
    goal="Fix the TypeError in api/handlers.py",
    context="""The file api/handlers.py has a TypeError on line 47:
    'NoneType' object has no attribute 'get'.
    The function process_request() receives a dict from parse_body(),
    but parse_body() returns None when Content-Type is missing.
    The project is at /home/user/myproject and uses Python 3.11."""
)
```

子智能体会收到一个基于你的 goal 和 context 构建的专注系统 prompt（提示词），指示其完成任务并提供结构化摘要，包括所做的事情、发现的内容、修改的文件以及遇到的问题。

## 实际示例 {#practical-examples}

### 并行研究 {#parallel-research}

同时研究多个主题并收集摘要：

```python
delegate_task(tasks=[
    {
        "goal": "Research the current state of WebAssembly in 2025",
        "context": "Focus on: browser support, non-browser runtimes, language support"
    },
    {
        "goal": "Research the current state of RISC-V adoption in 2025",
        "context": "Focus on: server chips, embedded systems, software ecosystem"
    },
    {
        "goal": "Research quantum computing progress in 2025",
        "context": "Focus on: error correction breakthroughs, practical applications, key players"
    }
])
```

### 代码审查 + 修复 {#code-review--fix}

将审查并修复的工作流委派给全新上下文：

```python
delegate_task(
    goal="Review the authentication module for security issues and fix any found",
    context="""Project at /home/user/webapp.
    Auth module files: src/auth/login.py, src/auth/jwt.py, src/auth/middleware.py.
    The project uses Flask, PyJWT, and bcrypt.
    Focus on: SQL injection, JWT validation, password handling, session management.
    Fix any issues found and run the test suite (pytest tests/auth/)."""
)
```

### 多文件重构 {#multi-file-refactoring}

将会大量占用父智能体上下文的大型重构任务委派出去：

```python
delegate_task(
    goal="Refactor all Python files in src/ to replace print() with proper logging",
    context="""Project at /home/user/myproject.
    Use the 'logging' module with logger = logging.getLogger(__name__).
    Replace print() calls with appropriate log levels:
    - print(f"Error: ...") -> logger.error(...)
    - print(f"Warning: ...") -> logger.warning(...)
    - print(f"Debug: ...") -> logger.debug(...)
    - Other prints -> logger.info(...)
    Don't change print() in test files or CLI output.
    Run pytest after to verify nothing broke."""
)
```

## 批处理模式详情 {#batch-mode-details}

当顶层智能体提供 `tasks` 数组时，Hermes 会返回一个后台句柄，并行运行所有子智能体。默认情况下，该调用会在所有任务都完成后返回**一条**汇总消息。结果只会在父智能体的轮次之间交付：父智能体应先完成所有不依赖子智能体的工作，然后结束本轮，而不是在等待期间轮询转录、产物或 CI。

### 独立完成交付（需选择启用） {#independent-completions-opt-in}

设置 `delegation.independent_completions: true` 后，结果会改为按**完成单元**在各自完成时分别送达。面向模型的 `group` 字段及分组指引只会在启用此选项时才对模型公开。修改该设置后请开启新会话，这样工具 schema 能反映新设置，而不会改变现有对话已缓存的前缀。包含 `group` 的旧调用仍会被接受；此选项关闭时，整个调用仍会一起返回。

启用独立完成交付时：

- 当每个结果都值得单独处理时，省略 `group`。每个任务完成后立即报告。
- 当你希望一起审阅输出时——比较、综合或做出一个协调一致的决定——使用相同的 `group` 字符串。该组会在其所有任务完成后返回**一条**汇总消息。即使是可以独立执行的任务，只要它们的结果服务于同一个决定，也可以归入同一组。
- 不同的组各自独立报告；分组任务和未分组任务可以共存于同一个调用中。

此选项默认关闭，因为每个单元都会为编排者带来一个新轮次：一个 15 个任务的调用最多会产生 15 次唤醒，这会让长时间的任务序列变得支离破碎。分组控制的是**结果交付，而不是执行顺序**：所有任务仍会并行运行。如果任务 B 需要任务 A 的输出才能开展工作，请先派发 A，待 A 返回后再携带其输出派发 B。

```json
{"tasks": [
  {"goal": "Review PR #101 ..."},
  {"goal": "Review PR #102 ..."},
  {"goal": "Benchmark approach A ...", "group": "bench"},
  {"goal": "Benchmark approach B ...", "group": "bench"}
]}
```

派发句柄会列出每个单元（`units[].delegation_id`、`group`、`task_indexes`）；单元 id 是该调用的 id 加上后缀 `-1`、`-2`……，同一调用的所有单元共享 `delegation.max_concurrent_children` 中的一个槽位，因此分组永远不会改变容量计算（工作线程池会扩展到存活单元的数量，所以不会有单元因线程池已满而等待）。编排者子智能体会在当前轮次中等待整个批次完成，以便综合结果。

- **最大并发数：** 默认 10 个任务（可通过 `delegation.max_concurrent_children` 或环境变量 `DELEGATION_MAX_CONCURRENT_CHILDREN` 配置；最低为 1，无硬性上限）。超出限制的批次会返回工具错误，而不是被静默截断。
- **线程池：** 使用 `ThreadPoolExecutor`，以配置的并发限制作为最大工作线程数
- **进度显示：** 在 CLI 模式下，树形视图会实时显示每个子智能体的工具调用，并附带每个任务的完成行。在 gateway 模式下，进度会被批量汇总并转发给父智能体的进度回调。CLI 和 TUI 的完成通知使用以任务为先的标题，例如 `Subagent Task Completed: Review changes`；多任务组使用组名和任务数量。未成功或未完成的工作会获得相应的状态标签。这些简洁通知不会取代交付给父智能体的完整结果。
- **结果排序：** 在一个单元内，结果按任务索引排序，与输入顺序一致，不受完成顺序影响；`TASK i/N` 标签按整个调用编号
- **取消：** 后续消息不会取消顶层后台批处理。`/stop` 或关闭/重置所属会话会取消其活跃子智能体。同步编排者的子智能体仍会跟随其父智能体的中断状态

编排者发起的同步单任务委派会直接运行，不会产生线程池开销。

### 持久化后台完成事件 {#durable-background-completions}

后台委派完成后，Hermes 会先把完成事件写入当前 profile 的 `state.db`，再发布到正常的新轮次队列。如果 Hermes 在完成后、交付前重启，待处理事件会被恢复，并继续经过相同的所有权检查。多个消费者通过持久化 claim 竞争；只有成功接收合成轮次的消费者会确认交付，失败尝试会释放 claim 以便重试。

这不会在崩溃后恢复子智能体执行。如果委派仍在运行时其所有者进程消失，Hermes 会将其记录为 `unknown`，因为无法证明外部副作用是否已经发生。待处理和已交付记录都有界，并按 profile 隔离。

### 子智能体后台进程通知 {#child-background-process-notifications}

子智能体启动的后台进程（例如带 `notify_on_complete` 的 `npm ci`）在技术上会把完成通知和监视模式通知路由到**父**对话，因为任何比子智能体存活更久的东西都需要一个持久的消费者。默认情况下，这些通知在父聊天中会被**抑制**——子智能体的汇总委派结果才是交付物，而子智能体内部构建在对话中途刷出的"进程已结束"消息墙只是噪音。被抑制的事件会以 debug 级别记录日志，并附带进程会话 ID 和子智能体任务 ID，因此仍可诊断。

委派结果本身永远不会被抑制。要恢复子智能体进程通知的交付（每条通知都带有 "Started by subagent …" 归属行）：

```yaml
delegation:
  surface_child_process_notifications: true   # default: false
```

### 将进程移交给父智能体 {#handing-a-process-to-the-parent}

子智能体的后台进程在**子智能体结束时也会被终止**，因此子智能体以 `notify=true` 启动的 CI 监视器或构建永远不会向任何人报告。子智能体的 `terminal` 结果会说明这一点（`notify_on_complete: false` 加上 `subagent_note`），子智能体在结束前有三个如实的选项：

- **等待**——`process_manage(action="wait", session_id=...)`，并自行报告结果；
- **终止**——`process_manage(action="kill", ...)`；
- **移交**——`process_manage(action="handoff", session_id=..., data="<one sentence: what it is for>")`。运行时会在注册表锁下将所有权转移给父智能体（每个子智能体最多 3 个；只接受子智能体自己拥有且正在运行的进程，其他情况均为工具错误）。随后父智能体的完成通知会以 `Handed off to you by a subagent… Purpose: …` 的形式出现在父聊天中，父智能体可以像对待自己的进程一样对其进行 poll/log/kill。

在子智能体仍在运行时就已结束的进程不需要移交：子智能体读取它（`poll`/`wait`/`log`）并报告即可。如果子智能体始终没有读取，退出码和输出尾部会作为 `unread_completions` 附加到其结果中并展示给父智能体。任何仍在运行、既未被终止也未被移交的进程，都会在其结果中（`orphaned_processes`）以及父智能体的委派通知中被标注为已终止，因此父智能体是从运行时——而不是从子智能体的文字描述——得知"监视器正在运行"已不再成立。对于 CI 监视器，更好的模式仍然是：子智能体返回事实（PR 编号、SHA），由父智能体启动自己的监视器。

## 模型覆盖 {#model-override}

你可以通过 `config.yaml` 为子智能体配置不同的模型——适用于将简单任务委派给更便宜/更快的模型：

```yaml
# In ~/.hermes/config.yaml
delegation:
  model: "google/gemini-flash-2.0"    # Cheaper model for subagents
  provider: "openrouter"              # Optional: route subagents to a different provider
```

如果省略，子智能体将使用与父智能体相同的模型。

### 成本策略：前沿模型规划，低价模型执行 {#cost-strategy-frontier-planner-inexpensive-workers}

将问题分解为规格清晰的子任务需要前沿模型级别的判断力；而执行一个已经带有明确目标、完整上下文和输出约定的子任务通常不需要。与此同时，token 消耗主要发生在子智能体身上——并行批量子智能体通常消耗一次运行中绝大多数的 token，因此成本真正落在 worker 模型上。将 `delegation.model` 固定为低价模型、同时主会话保持前沿模型，可以把规划质量留在最需要的地方，并在消耗量最大的地方削减开支：

```yaml
# ~/.hermes/config.yaml
model:
  default: "your-frontier-model"     # 父智能体（规划者）保持前沿模型
delegation:
  model: "your-inexpensive-model"    # 所有 delegate_task 子智能体运行此模型
  provider: "openrouter"             # 可选：将子智能体路由到不同的提供商
```

解析顺序：`delegation.base_url`（直连端点）优先，其次是 `delegation.provider`（通过运行时提供商系统解析完整凭证包）；两者都未设置时，子智能体继承父智能体的提供商和凭证。`delegation.model` 在所有情况下生效，为空时子智能体继承父智能体的模型。同时设置 `delegation.provider` 与 `delegation.base_url` 时，会保留显式端点，但会把该提供商的请求覆盖项和最大输出 token 数带入子智能体。显式的 `delegation.request_overrides` 字典在每个分支上都会生效，并合并覆盖在这些由运行时派生的值之上（参见下方[配置](#configuration)）。

注意此固定是全局的：`delegate_task` 没有按任务指定模型的参数，批处理中的每个子智能体都运行配置的委派模型。对于需要更强模型的质量敏感型子任务，可以在该会话中不设置 `delegation.model`，或者将任务交给[看板](kanban.md#per-task-model-override)——看板支持按任务覆盖模型。

## `/review` 命令 {#the-review-command}

`/review` 会派生一个独立的、拥有完整工具权限的后台评审子智能体，专门评审对话刚刚产出的工作——PR、diff、代码、文档、设计。它在所有界面均可用：CLI、TUI、桌面应用以及所有网关消息平台。

```
/review                       # 评审最近 10 条消息中呈现的工作
/review 重点关注安全性          # 为评审者附加额外指示
```

工作流程：

1. 最近 10 条用户/助手消息被快照为评审者的起始证据（工具输出和系统消息被排除）。
2. 评审子智能体在与 `delegate_task` 相同的后台委派通道上派发——它拥有完整的常规子智能体工具集（终端、网络、文件、浏览器等），因此会实际打开 PR、阅读 diff、运行代码，而不是仅凭摘录下判断。
3. 评审者继承主智能体的工作上下文：主智能体已加载的技能（启动预加载或会话中通过 `skill_view` 加载）会列在其简报中，并指示其加载这些技能、以其约定为标准评判工作。与所有子智能体一样，其系统提示也会嵌入工作区的项目上下文文件（AGENTS.md / CLAUDE.md / .cursorrules）作为具有约束力的约定。
4. 完成后，完整评审作为常规后台子智能体完成事件重新进入同一会话——你的主智能体可以看到并据此行动（修复问题、推送后续提交、回复你）。

典型流程：主智能体开了一个 PR，你输入 `/review`，第二双眼睛在你继续工作的同时对其进行调查；评审结果回到聊天中，交给创建该 PR 的智能体。

派发时只会打印"Review started. Results will return here."。实时子智能体查看器会将该工作者标识为 **Review: your focus**（裸 `/review` 则为 **Review recent work**），并显示缩短后的单行标签；评审者仍会收到你的完整指示。在经典 CLI 中，输入框上方的停靠栏会显示已运行时间和最近活动；**Ctrl+T**（或 **F6**）会打开列表，其中包含其模型、转录、引导和停止控制。相同的评审标签也会出现在 TUI 和 Desktop 的子智能体查看器中。

### 评审模型 {#review-model}

默认情况下评审者运行在你的主模型上。要固定专用评审模型，请在 `config.yaml` 中设置 `auxiliary.review`：

```yaml
auxiliary:
  review:
    provider: openrouter               # 或 nous、anthropic、直连 base_url 等
    model: anthropic/claude-opus-4.6   # 一个强力的评审模型
```

凭证解析方式与 `delegation.provider` 固定完全相同（完整运行时提供商凭证包：base_url、API 密钥、api_mode）。`provider: auto` 加空 `model` 表示"继承主智能体的模型"——这是默认值。

`/review` 与 `/refine` 刻意分开：`/refine` 评审对话本身以更新记忆和技能，`/review` 评审对话产出的*工作成果*。

## 继承的工具访问权限 {#inherited-tool-access}

`delegate_task` 不接受面向模型的 `toolsets` 参数。每个子智能体都会继承父智能体已启用的工具集，因此模型无法授予子智能体父智能体本身没有的能力。如果委派任务需要其他能力，请在开始对话前配置父智能体的工具。

即使父智能体拥有某些工具，以下工具仍会对子智能体屏蔽：
- `delegate_task` — 对叶子子智能体屏蔽（默认）。`role="orchestrator"` 的子智能体可保留，受 `max_spawn_depth` 约束——参见下方[深度限制与嵌套编排](#depth-limit-and-nested-orchestration)。
- `clarify` — 子智能体无法与用户交互
- `memory` — 不可写入共享持久内存
- `send_message` — 不产生跨平台副作用
- `cronjob` — 不可以父智能体的名义调度更多工作

两种角色都保留 `execute_code`（程序化工具调用），以便子智能体批量处理机械性工作。

## 最大迭代次数 {#max-iterations}

每个子智能体都有迭代次数限制（默认：250），控制其可进行的工具调用轮次。该限制在 `config.yaml` 中全局设置，适用于每个子智能体；它不是 `delegate_task` 的按调用参数：

```yaml
# In ~/.hermes/config.yaml
delegation:
  max_iterations: 60   # lower it for fleets of simple tasks, raise it for long investigations
```

耗尽预算的子智能体会返回 `exit_reason: max_iterations` 和 `truncated: true`，这样父智能体就能区分因预算停止与已完成的任务。

## 子智能体超时 {#child-timeout}

默认情况下，子智能体**没有挂钟超时限制**。子智能体只会因其实际执行的操作而失败——API 错误、工具错误或达到迭代预算上限——而不会被委派层面的计时器终止。早期版本曾设有硬性上限（300 秒，后为 600 秒），但这会在任务执行过程中误杀正常工作的子智能体：深度代码审查、大规模研究分发以及慢速推理模型经常需要超过 10 分钟，而它们全程都在稳定推进。

真正卡死的子智能体仍会被检测到：当子智能体没有任何进展（无 API 调用、无工具启动、活动时间戳也没有跳动）时，心跳陈旧度监控会停止刷新父智能体的活动状态，从而让网关的不活动超时机制对真正卡死的工作进程生效。正在进行中的模型等待仍算作进展——子智能体在等待提供商时会刷新活动时钟，因此缓慢的本地推理或长时间预填充的补全不会被视为停滞。

如果仍需要硬性上限（例如对无人值守的 cron 驱动委派进行成本控制），可按安装实例选择启用：

```yaml
delegation:
  child_timeout_seconds: 0     # 默认：0 = 无超时
  # child_timeout_seconds: 1800  # 选择启用的硬性上限（下限 30 秒）
```

正值会对每个子智能体强制执行挂钟时间硬限制；`0` 或负值表示禁用。

当配置的上限触发时，子智能体的结果会在错误消息之外附带结构化的超时元数据，使父智能体和钩子无需解析文本即可将计时器终止与其他失败区分开来：`timeout_seconds`（配置的上限）、`timed_out_after_seconds`（实际挂钟时间）以及 `timeout_phase`（子智能体从未发出第一个请求时为 `before_first_llm_call`，否则为 `after_llm_calls`）。在非超时错误中，这三个字段均为 `null`。

## 失败可见性 {#failure-visibility}

失败的子智能体——不可重试的提供商错误（404/400）、超时、崩溃或没有可用输出——永远不会悄无声息：

- **CLI**：委派树会打印一行原因：`⚠️ Subagent failed — "your goal": HTTP 404: model not found (after 12s)`。批处理运行会把原因追加到每个任务的 `✗` 完成行后。
- **网关平台**（Telegram、Discord、Slack 等）：同样简洁的一行会作为独立的聊天通知送达，**即使该平台的 `tool_progress` 已关闭**。
- **父智能体**：工具结果条目会带有 `status: "failed"` 以及完整的 `error` 文本，以便模型做出反应（重试、改道、报告）。

错误文本会被精简为信息量最大的一行（异常消息，而不是整面 traceback），并限制长度。

:::tip 零调用超时时的诊断转储
在配置了硬性上限的情况下，如果子智能体在**零次** API 调用的情况下超时（通常原因：provider 不可达、认证失败或工具 schema 被拒绝），`delegate_task` 会将结构化诊断信息写入 `~/.hermes/logs/subagent-timeout-<session>-<timestamp>.log`，其中包含子智能体的配置快照、凭据解析追踪、早期错误消息，以及**所有**存活线程（而不仅是子智能体自身线程）的堆栈跟踪——如果没有完整全貌，一个停在等待嵌套辅助线程上的子智能体与一个缓慢的 provider 无从区分。
:::

## 后台子智能体的停滞检测 {#stall-detection-for-background-subagents}

后台委派（`delegate_task(background=true)`）由一个**基于进展的停滞监控器**看护——默认开启，零配置。与挂钟超时不同，只要子智能体仍在推进，无论运行多久，它都不会干预。

该监控器会对每个分离子智能体的进展信号进行采样——API 调用次数、当前工具，以及最近活动时间戳（该时间戳会在**每个流式 token**、工具切换和 API 调用边界时跳动，因此正在流式输出长回复的子智能体始终被视为存活）：

1. **正在推进的子智能体永远不会被干预。** 任何推进中的信号都会重置计时。
2. 进展完全冻结并超过陈旧阈值的子智能体（空闲 450 秒，处于工具内时 1200 秒——本就较慢的终端命令和网页抓取会获得更高的上限）会被**中断**，并获得 120 秒的宽限窗口。在宽限期内完成收尾的子智能体会通过正常的完成路径交付其部分结果。
3. 始终没有返回的子智能体会被强制终结，并产生一个终态的 `stalled` 完成事件，使所属会话能听到一个结果而不是陷入沉默，同时释放异步槽位以承接新工作。

`stalled` 事件携带的结构化元数据与同步路径的超时字段相对应：`stalled_after_quiet_seconds`、`stall_threshold_seconds`、`stall_phase`（`idle` / `in_tool`）以及 `stall_grace_seconds`。

这解决了一个长期存在的故障模式：卡死的后台子智能体会让其会话看起来像是已经死掉，直到进程重启。其底层卡死问题（网关连续运行多日后，子智能体卡在第一次 API 调用上）也已从根源上修复：委派的子智能体现在在自己的对话线程上内联执行 OpenAI 协议的 API 请求，而不是在嵌套的工作线程中执行——卡死问题正出在那一层。停滞监控器则作为其他情况的安全网保留。


## 监控运行中的子智能体（`/agents`） {#monitoring-running-subagents-agents}

TUI 提供 `/agents` 浮层（别名 `/tasks`），将递归 `delegate_task` 扇出转化为一级审计界面：

- 运行中和最近完成的子智能体的实时树形视图，按父智能体分组
- 每个分支的费用、token 和已触及文件的汇总
- 终止和暂停控制——可在不中断其兄弟智能体的情况下取消特定子智能体
- 事后回顾：即使子智能体已返回父智能体，也可逐轮查看其历史记录

### 输入框上方的实时活动 {#live-activity-above-the-composer}

经典 CLI、TUI 和 Desktop 会在输入框上方自动显示正在运行的子智能体。你可以一边继续输入，一边查看实时数量、任务名称、已运行时间和最近活动。终端停靠栏根据屏幕高度限制可见行数，并显示还有多少工作者被隐藏；Desktop 最多预览三个工作者。

| 界面 | 展开与查看 | 控制选中的工作者 |
|---|---|---|
| 经典 CLI | **Ctrl+T**（或 **F6**）打开全屏实时列表；方向键选择，**Enter** 打开转录尾部，**PgUp/PgDn** 滚动 | **s** 打开独立的引导输入；按 **x** 后再按 **y** 请求停止 |
| TUI | **Ctrl+T** 或 `/agents` 打开完整高度的树状列表；**Enter/t** 打开实时转录尾部；**d** 打开详细信息（在归档/回放中 Enter 仍打开详情） | **e** 打开引导；**x** 停止选中的工作者；**X** 停止其子树 |
| Desktop | 展开输入框上方的 **Subagents**，然后选择一个工作者查看其活动和详情 | **Steer** 将指引加入队列；**Stop** 请求中断该工作者 |

关闭终端监视器后会回到你原有的输入草稿。引导使用独立的输入框，确认的是**已排队**而非已送达：子智能体会在检查点读取指引。停止操作不会中断无关的兄弟智能体。

在经典 CLI 或 TUI 输入框中按 **F7**，可在多行预览和单行阴影摘要之间切换停靠栏。摘要行保留实时数量和展开/恢复提示，空间允许时还会显示活动。输入和发送仍然可用；打开和关闭监视器会保留你的草稿和光标位置。这只是本地的显示选择，不会写入配置。

实时转录尾部是有限长度的近期摘录，而不是无限制的对话浏览器。子智能体离开实时注册表后即离开停靠栏；完成消息以及 TUI/Desktop 的历史视图仍是回顾已完成工作的地方。最近活动只是一种观察，而不是完成百分比的估计。

经典 CLI 的 `/agents` 和 `/tasks` 命令仍打印文本摘要；**Ctrl+T**（或 **F6**）是即时的交互式监视器，父智能体忙碌时同样可用。参见 [TUI — 斜杠命令](/user-guide/tui#slash-commands)。

在经典 CLI 和所有网关平台（Telegram、Discord、Slack 等）上，`/agents` 还会列出**后台委派及每个子智能体的实时活动**，这些数据直接从每个运行中的子智能体采样：

```
Background delegations: 1 running
- deleg_ab12cd34 · running · research the delegation stall monitor
  - child 1: 4 api calls · in web_search · active 12s ago
  - child 2: 7 api calls · between turns · active 3s ago
```

被停滞监控器标记的委派会显示为 `stalling · no progress 450s — interrupting`，而长时间安静但健康的子智能体会显示其安静时长，让你一眼分辨"慢"与"卡住"。

## 引导运行中的子智能体 {#steering-a-running-subagent}

中断子智能体会丢弃其进行中的工作；很多时候你只是想为它改变方向。

### 从父智能体（面向模型） {#from-the-parent-agent-model-facing}

父智能体使用生成子智能体时所用的同一个 `delegate_task` 工具来编排其运行中的子智能体——无需单独的控制工具：

```json
{"action": "list"}
{"action": "steer", "subagent_id": "sa-0-1a2b3c4d", "message": "focus on pricing instead"}
{"action": "stop",  "subagent_id": "sa-0-1a2b3c4d"}
```

- **`list`** 返回该对话的存活子智能体：`subagent_id`、目标、状态、`running_seconds`、`accepting_steer` 以及实时转录路径。id 也会在生成派发响应中以 `subagent_ids` 返回。
- **`steer`** 在不停止子智能体的情况下，将一次方向修正排入其队列（交付语义见下文）。
- **`stop`** 在子智能体的下一个迭代边界提前结束它；部分结果仍会作为正常的完成消息重新进入对话。

控制操作在本轮内同步执行（永不转入后台），作用范围仅限调用者自己的生成树——一个对话永远无法看到或控制其他会话的子智能体——并且永远不会消耗每轮的子智能体生成上限，因此即使达到上限，`stop` 仍然可用。

### 从 TUI / 网关（面向会话） {#from-the-tui--gateway-session-facing}

`tools/delegate_tool_registry.py` 中的 `steer_subagent(subagent_id, text)` 是 `interrupt_subagent()` 在改向方面的对应物：它通过与 [`/steer`](/reference/slash-commands) 相同的机制将文本排入存活子智能体的队列——文本会在子智能体的下一个迭代边界追加到其最后一个工具结果之后，进行中的工具调用永远不会被打断，子智能体会将其视为一条带外用户消息。程序化宿主可通过会话范围的 `subagent.steer` 网关 RPC 调用它，该 RPC 与 `subagent.interrupt` 并列：

```json
{"method": "subagent.steer", "params": {"session_id": "owning-ui-session", "subagent_id": "sa-0-1a2b3c4d", "text": "focus on pricing instead"}}
```

子智能体 id 来自 `delegation.status`（或 `list_active_subagents()`）——与 `subagent.interrupt` 获取 id 的位置相同。网关只接受来自生成该子智能体的那个确切存活 UI/网关会话的引导。缺失、外来、有歧义或陈旧/被复用的会话身份都会被拒绝；知道一个全局子智能体 id 并不构成授权。直接的进程内调用者刻意保留了不带范围限制的辅助函数约定。

**已排队不等于已送达，但它绝不是伪造的成功。** `"queued"` 响应表示文本在子智能体的完成边界之前被接受，并不一定表示子智能体已经看到它。接受与完成是同步的：要么子智能体仍能读取该文本，要么其原文会作为 `pending_steer` 被转入结果中。关闭之后的调用返回 `"rejected"`。如果子智能体接受了引导、但此前已经生成了最终答案，父智能体收到的完成条目会将其保留为 `missed_steer`，并在摘要后追加一条说明：

```
[steer did not land — the subagent finished before it could be delivered: focus on pricing instead]
```

这样父智能体（或驱动它的操作者）就能区分被引导过的子智能体与按旧指示完成的子智能体，并将指引作为后续任务重新下达，而不是想当然地认为它已送达。

## 实时转录 {#live-transcripts}

每次 `delegate_task` 派发还会**为每个任务创建一份仅追加、人类可读的日志**，这样你（或父智能体）就能实时观察子智能体的工作，而不必等待汇总摘要：

```
<hermes_home>/cache/delegation/live/<delegation_id>/task-<n>.log
```

派发响应中以 `live_transcripts` 字段返回这些路径，且文件在派发时即已预先创建，因此可以立即使用：

```bash
tail -f ~/.hermes/cache/delegation/live/deleg_ab12cd34/task-0.log
```

每一行都带时间戳，展示子智能体的助手文本、思考片段、工具调用（`-> tool_name({args})`）、工具结果，以及最终的状态标记。同一目录下的 `manifest.json` 描述该批次（目标、任务数量、各任务状态）。日志在任务完成后仍会保留——它们与摘要互补，是完整保真的运行记录——超过 7 天的目录会在新的派发时自动清理。由于它们位于 `cache/delegation` 下，也可从远程终端后端（Docker/Modal/SSH）读取。

## 深度限制与嵌套编排 {#depth-limit-and-nested-orchestration}

默认情况下，委派是**扁平的**：父智能体（深度 0）生成子智能体（深度 1），而这些子智能体无法进一步委派。这可防止失控的递归委派。

对于多阶段工作流（研究 → 综合，或对子问题进行并行编排），父智能体可以生成**编排者**子智能体，这些子智能体*可以*委派自己的工作线程：

```python
delegate_task(
    goal="Survey three code review approaches and recommend one",
    role="orchestrator",  # Allows this child to spawn its own workers
    context="...",
)
```

- `role="leaf"`（默认）：子智能体无法进一步委派——与扁平委派行为相同。
- `role="orchestrator"`：子智能体保留 `delegation` 工具集。受 `delegation.max_spawn_depth` 约束（默认 **1** = 扁平，因此在默认设置下 `role="orchestrator"` 无效）。将 `max_spawn_depth` 提高到 2 可允许编排者子智能体生成叶子孙智能体；设为 3 或更高可获得更深的树。没有上限——费用才是实际的限制因素。
- `delegation.orchestrator_enabled: false`：全局开关，无论 `role` 参数如何，强制所有子智能体为 `leaf`。

**费用警告：** 在 `max_spawn_depth: 3` 和 `max_concurrent_children: 3` 的情况下，树可达到 3×3×3 = 27 个并发叶子智能体。每增加一层都会成倍增加开销——请谨慎提高 `max_spawn_depth`。

## 生命周期与持久性 {#lifetime-and-durability}

:::warning 后台完成事件持久化并不等于执行持久化
在会话支持稍后交付结果时，顶层面向模型的 `delegate_task` 调用会自动在后台运行。Hermes 会立即返回句柄，并在子智能体或批处理完成后将结果重新发送到对话中。编排者子智能体会在当前轮次中等待自己的工作线程，因为它们必须在返回前综合这些结果。无法稍后交付分离结果的无状态请求/响应端点会回退到同步执行。

- 普通后续消息不会取消后台子智能体。`/stop` 会取消运行中的后台委派，关闭或重置所属会话会丢弃其活跃子智能体。
- 显式关闭或重置会话会中断该会话的后台子智能体。关闭由 TUI 查看、但由网关拥有的会话不会终止网关自己的后台工作。
- Hermes 进程重启后**不会**恢复仍在运行的子智能体；该尝试会变为 `unknown`，因为 Hermes 无法证明哪些副作用已经发生。
- 如果子智能体在重启前已经完成、但结果尚未交付，该完成事件会被恢复，并重新经过所属会话的正常检查。
- 被取消的子智能体会返回结构化结果（`status="interrupted"`，`exit_reason="interrupted"`），但由于父智能体也被中断，该结果通常不会出现在用户可见的回复中。

对于必须在会话关闭或进程重启后继续的**持久执行**，请使用：

- `cronjob`（action=`create`）——调度独立的智能体运行；不受父智能体轮次中断影响。
- `terminal(background=True, notify_on_complete=True)`——长时间运行的 shell 命令，在智能体执行其他操作时持续运行。
:::

## 关键特性 {#key-properties}

- 每个子智能体获得其**独立的终端会话**（与父智能体分离）
- 子智能体继承父智能体已启用的工具集；模型无法按调用选择或扩大这些工具集
- **嵌套委派为可选项**——只有 `role="orchestrator"` 的子智能体可以进一步委派，且仅在 `max_spawn_depth` 从默认值 1（扁平）提高后才生效。可通过 `orchestrator_enabled: false` 全局禁用。
- 叶子子智能体**不能**调用：`delegate_task`、`clarify`、`memory`、`send_message`、`cronjob`。编排者子智能体保留 `delegate_task`，但其他屏蔽仍然有效。两种角色都保留 `execute_code`（程序化工具调用），以便子智能体批量处理机械性工作，而不是消耗推理迭代。
- **取消遵循所有权**——`/stop` 或关闭/重置所属会话会取消其后台子智能体；编排者下的同步后代会跟随父智能体的中断状态
- 只有最终摘要进入父智能体的上下文，保持 token 使用高效
- 子智能体继承父智能体的 **API 密钥、provider 配置和凭据池**（支持在速率限制时轮换密钥）

## 工作树隔离 {#worktree-isolation}

默认情况下，子智能体共享父智能体的工作目录——这对研究和以读取为主的工作没有问题，但并行子智能体编辑同一个仓库时可能相互冲突。设置 `delegation.worktree_isolation: true` 可为每个子智能体分配独立的 git 工作树，从仓库当前的 `HEAD` 分出（灵感来自 Muse Code 的 `--subagent-worktree-isolation`）：

```yaml
delegation:
  worktree_isolation: true   # default: false
```

启用隔离后：

- 每个子智能体的终端在 `<repo>/.worktrees/subagent-<id>` 中启动，位于其自己的分支 `hermes-subagent/subagent-<id>` 上，其目标消息会告诉它在那里工作并提交。
- 父智能体的检出保持不变；子智能体之间无法覆盖彼此的编辑。
- 子智能体完成后，其结果条目会增加一个 `worktree` 字段，报告 `path`、`branch`、`commits`（领先于基准的提交数）和 `dirty`。父智能体审阅或合并每个分支（`git log <branch>`、`git merge <branch>`）。
- **没有提交且工作区干净的工作树会被自动清理**（`pruned: true`）；任何保存着工作的工作树都会被保留。
- 清理需要证据。如果某次 git 检查探测失败——或收尾过程本身出错——工作树和分支都会被保留，条目会带上 `inspection_failed: true` 以及一条 `note`——此时 `commits`/`dirty` 只是默认值而非实测值，因此请检查该工作树，而不要假定子智能体什么都没产出。

适用范围：需选择启用，仅限 git，且仅限本地终端后端。在非 git 目录中、在 docker/ssh/modal 后端上，或工作树创建失败时，该设置会静默降级为现有的共享工作区行为——绝不会报错。

## delegate_task 与 execute_code 对比 {#delegation-vs-execute_code}

| 因素 | delegate_task | execute_code |
|--------|--------------|-------------|
| **推理** | 完整 LLM 推理循环 | 仅 Python 代码执行 |
| **上下文** | 全新隔离对话 | 无对话，仅脚本 |
| **工具访问** | 所有非屏蔽工具，具备推理能力 | 通过 RPC 访问 7 个工具，无推理 |
| **并行性** | 默认 10 个并发子智能体（可配置） | 单脚本 |
| **最适合** | 需要判断力的复杂任务 | 机械式多步骤流水线 |
| **Token 费用** | 较高（完整 LLM 循环） | 较低（仅返回 stdout） |
| **用户交互** | 无（子智能体无法澄清） | 无 |

**经验法则：** 当子任务需要推理、判断或多步骤问题解决时，使用 `delegate_task`。当需要机械式数据处理或脚本化工作流时，使用 `execute_code`。

## 配置 {#configuration}

```yaml
# In ~/.hermes/config.yaml
delegation:
  max_iterations: 250                       # Max turns per child (default: 250)
  # max_concurrent_children: 10             # Parallel children per batch (default: 10)
  # independent_completions: false          # true = each task/group returns as it finishes (default: one message per call)
  # worktree_isolation: false               # Give each child its own git worktree (see Worktree Isolation above)
  # max_spawn_depth: 1                      # Tree depth (floor 1, no ceiling, default 1 = flat). Raise to 2 to allow orchestrator children to spawn leaves; 3+ for deeper trees.
  # orchestrator_enabled: true              # Disable to force all children to leaf role.
  model: "google/gemini-3-flash-preview"             # Optional provider/model override
  provider: "openrouter"                             # Optional built-in provider
  api_mode: anthropic_messages                       # optional; auto-detected from base_url for anthropic_messages endpoints

# Or use a direct custom endpoint instead of provider:
delegation:
  model: "qwen2.5-coder"
  base_url: "http://localhost:1234/v1"
  api_key: "local-key"
  # api_mode: "anthropic_messages"  # Optional. Wire protocol override for base_url ("chat_completions", "codex_responses", or "anthropic_messages"). Empty = auto-detect from URL (e.g. /anthropic suffix). Set explicitly for endpoints the heuristic can't classify (Azure AI Foundry, MiniMax, Zhipu GLM, LiteLLM proxies, …).

# Send per-child request settings on every subagent API call — e.g. OpenRouter
# routing hints when delegating straight to openrouter.ai via base_url:
delegation:
  model: "deepseek/deepseek-v4-flash-0731"
  base_url: "https://openrouter.ai/api/v1"
  api_key: "sk-or-..."
  request_overrides:
    extra_body:
      provider:
        sort: throughput   # children route to the fastest OpenRouter provider
```

当 `base_url` 指向 Anthropic 兼容端点时——例如路径以 `/anthropic` 结尾、Azure Foundry Claude 路由或 MiniMax `/anthropic` 代理——`api_mode` 会被自动检测为 `anthropic_messages`，子智能体无需任何配置即可使用正确的传输格式。当自动检测结果有误时（罕见），请显式设置 `api_mode`。

子智能体与父智能体使用相同的比例触发压缩（`compression.threshold`，默认 0.50 × 窗口）。`delegation.compression_threshold_tokens`（默认 `0`，关闭）为子智能体的压缩*触发点*增加一个可选的绝对上限，取它与比例阈值中较低者；它从不改动请求载荷或父智能体。至少 16000 的 token 数即可启用它；`true` 或 `"200k"` 属于配置错误，会被警告并忽略。它默认关闭，是因为对一次 1,393 个智能体的运行进行重放后发现，在缓存前缀保持完整的情况下，200K–400K 的上限在成本上彼此相差不到 5%，而每一次压缩都是一次丢失细节的机会。

`delegation.request_overrides` 在**全部三种**解析分支上都有效——直连 `base_url`、命名 `provider` 以及纯继承——因此它总会生效。顶层键是 API 关键字参数（例如 `service_tier`）；`extra_body` 子字典会合并到请求的 `extra_body` 中。显式值会**覆盖**运行时或父智能体派生的覆盖项：显式顶层键优先，`extra_body` 做一层深度合并，因此提供商自身的请求特性（例如 `thinking: {type: disabled}`）会被保留，除非你的键重新定义了它。详见[配置 → 委派](../configuration.md#delegation)。

:::tip
智能体会根据任务复杂度自动处理委派。你无需明确要求它进行委派——它会在合适时自行决定。
:::
