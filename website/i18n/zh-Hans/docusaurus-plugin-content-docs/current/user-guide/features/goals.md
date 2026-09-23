---
sidebar_position: 16
title: "持久目标"
description: "设置一个持续目标，让 Hermes 跨轮次持续工作直到完成。我们对 Ralph loop 的实现。"
---

# 持久目标（`/goal`）

`/goal` 为 Hermes 设置一个跨轮次持续存在的目标。每轮结束后，一个轻量级裁判模型会检查目标是否已被助手的最新回复满足。若未满足，Hermes 会自动将一条续行 prompt（提示词）注入同一会话并继续工作——直到目标达成、你暂停或清除目标，或者轮次预算耗尽为止。

这是我们对 **Ralph loop** 的实现，直接受 Eric Traut（OpenAI）在 [Codex CLI 0.128.0 的 `/goal`](https://github.com/openai/codex) 中的启发。核心思路——跨轮次保持目标存活、不达成不停止——源自他们。此处的实现是独立的，并已适配 Hermes 的架构。

## 适用场景

当你希望 Hermes 自主迭代、无需每轮重新提示时，使用 `/goal`：

- "修复 `src/` 中的所有 lint 错误，并验证 `ruff check` 通过"
- "从仓库 Y 移植功能 X，包含测试，并让 CI 变绿"
- "调查为何会话 ID 有时在中途压缩时发生漂移，并撰写报告"
- "构建一个小型 CLI，按 EXIF 日期重命名文件，然后对 photos/ 文件夹进行测试"

只需一轮即可完成的任务不需要 `/goal`。*否则你需要说三次"继续"* 的任务，才是它的用武之地。

## Goals 与 Kanban：我该用哪一个？ {#goals-vs-kanban-which-one-do-i-want}

`/goal` 和 [Kanban](./kanban) 都能让 Hermes 在你不重新提示的情况下持续工作，因此很容易以为二者会相互衔接。事实并非如此——两者的边界非常清晰：

- **`/goal` 是单会话的。** 循环会把续行 prompt 送回*当前*对话，直到裁判判定完成。设置目标永远不会创建 kanban 卡片、不会把工作分配给其他 profile，也不会扇出。不存在任何交接到看板的行为，无论显式还是隐式。
- **Kanban 是由许多任务组成的看板。** 每张卡片都会被分派给拥有独立会话的独立 worker 进程。卡片、依赖、负责人和交接都位于看板上——而不在 `/goal` 中。
- **两者的重叠是刻意的，而且很小。** 用 `--goal` 创建的 kanban 卡片会运行与 `/goal` 相同的 Ralph 式续行引擎——但只在*该卡片自己的 worker 会话内部*。它借用的是引擎，而不是看板。参见[目标模式卡片](./kanban#goal-mode-cards---goal)。

| 你想要 | 应当使用 |
|---|---|
| 在当前聊天中持续迭代一个任务直到完成 | `/goal <text>` |
| 多个相互独立的任务，带有依赖、交接或多个 profile | [Kanban](./kanban) —— `hermes kanban create …` |
| 看板上的某一张卡片需要持续迭代，直到满足其验收标准 | 带 `--goal` 的 kanban 卡片 |

:::note
如果你希望工作出现在看板上，请自己把它放上去（`hermes kanban create …`）——`/goal` 不会替你这么做。反过来也一样：在当前聊天中暂停、恢复或清除目标，永远不会创建、认领或移动任何 kanban 卡片。
:::

## 快速开始

```
/goal Fix every failing test in tests/hermes_cli/ and make sure scripts/run_tests.sh passes for that directory
```

你将看到：

1. **目标已接受** — `⊙ Goal set (20-turn budget): <your goal>`
2. **第 1 轮运行** — Hermes 开始工作，就像你发送了一条普通消息一样。
3. **裁判运行** — 轮次结束后，裁判模型判定 `done`、`continue` 或 `blocked`。
4. **若需要则触发循环** — 若为 `continue`，你将看到 `↻ Continuing toward goal (1/20): <judge's reason>`，Hermes 自动执行下一步。
5. **终止** — 最终你会看到 `✓ Goal achieved: <reason>` 或 `⏸ Goal paused — N/20 turns used`。

## 命令

| 命令 | 功能 |
|---|---|
| `/goal <text>` | 设置（或替换）持续目标。立即启动第一轮，无需再发送单独消息。 |
| `/goal draft <text>` | 从一句自然语言目标起草一份结构化的完成契约，然后设置它。参见[完成契约](#completion-contracts)。 |
| `/goal show` | 打印当前活跃目标的完成契约。 |
| `/goal` 或 `/goal status` | 显示当前目标、状态及已用轮次。 |
| `/goal pause` | 停止自动续行循环，但不清除目标。 |
| `/goal resume` | 恢复循环（将轮次计数器重置为零）。 |
| `/goal clear` | 完全删除目标。 |
| `/goal wait <pid> [reason]` | 将循环停靠在某个后台进程上——进程运行期间不再每轮催促 agent，进程退出后自动恢复。 |
| `/goal unwait` | 撤销等待屏障并立即恢复循环。 |
| `/goal gate add <command>` | 添加一个**质量关卡**：一条必须通过的 shell 命令，目标才能被判定为完成。参见[质量关卡](#quality-gates)。 |
| `/goal gate` 或 `/goal gate list` | 列出目标的关卡及其通过/失败状态。 |
| `/goal gate remove <N>` | 删除第 N 个关卡（从 1 开始计数）。 |
| `/goal gate clear` | 删除所有关卡。 |

经典 CLI、TUI、Desktop、dashboard 聊天和消息网关共用同一个 `/goal` 命令处理器。这包括 draft/show、内联契约、wait/unwait、质量关卡以及 clear/stop/done 别名。Desktop 的目标控件同样使用该处理器。ACP 目前既不公布也不实现 `/goal`。

`/goal draft <text>` 既会创建目标，也会启动其第一轮——即使起草功能不可用、Hermes 回退为自由格式目标时也是如此。`draft` 是一个整词子命令：`/goal drafting docs` 会把 `drafting docs` 当作字面目标，而不会调用起草模型。

消息平台保留各自的访问规则：`/goal gate add` 需要显式配置的网关管理员；列出、删除和清空关卡仍然可用，以便恢复。渲染和轮次调度因界面而异，但命令解析和持久化的目标变更是共享的。

## 完成契约 {#completion-contracts}

裸的 `/goal <text>` 也能正常工作，但*含糊*的目标只能带来含糊的判定——裁判只能检查你告诉它想要的东西。Codex 的 `/goal` 指南也提出了同样的观点：一个持久的目标最好明确说明**「完成」意味着什么、如何证明、什么不能被破坏、范围有哪些、以及何时停止**。Hermes 将其改造为叠加在既有目标循环之上的可选**完成契约**。

一份契约有五个字段，全部可选：

| 字段 | 含义 |
|---|---|
| `outcome` | 完成时必须为真的那个唯一终态。 |
| `verification` | *证明*该终态的具体测试 / 命令 / 产物。 |
| `constraints` | 不得改变或退化的内容。 |
| `boundaries` | 哪些文件、目录、工具或系统在范围内。 |
| `stop_when` | Hermes 应当停下来征求输入的条件。 |

设置契约后，两个 prompt 都会改变：**续行 prompt** 会要求 agent 瞄准验证面并遵守约束，**裁判 prompt** 则*只在验证条件被具体证据满足时*（命令结果、文件摘录、测试输出）才判定 `done`——而不是含糊的「看起来完成了」。这直接收紧了 `/goal` 最常见的失败模式（在目标欠定义时过早完成或无休止地过度续行）。

### 设置契约的两种方式

**1. 让 Hermes 起草**（推荐——改编自 Codex 的「让 agent 起草目标」技巧）：

```
/goal draft Migrate the auth service from session cookies to JWT
```

Hermes 会通过 `goal_judge` 辅助模型把你的一句话展开成完整契约、设置它，并把结果展示给你，方便你审阅或收紧任一字段。如果辅助模型不可用，它会回退为普通的自由格式目标——起草永远不会阻塞目标的设置。

**2. 用 `field: value` 行内联书写**：

```
/goal Migrate auth to JWT
verify: pytest tests/auth passes
constraints: keep the /login response shape unchanged
boundaries: only touch services/auth and its tests
stop when: a DB schema migration is required
```

开头的非字段行是目标标题；被识别的字段前缀（`verify:`、`verified by:`、`constraints:`、`preserve:`、`boundaries:`、`scope:`、`stop when:`、`blocked:` 等）会填充契约。一个偶然含有冒号的普通目标（`Fix bug: the parser drops commas`）**不会**被拆坏——只有已知的字段前缀才会被提取出来。

使用 `/goal show` 审阅当前活跃契约。契约与目标一起持久化在 `SessionDB.state_meta` 中，因此在 `/resume` 后依然有效。此功能之前设置的旧目标会原样加载（无契约）。契约与 `/subgoal` 条件可以组合：子目标会作为裁判同样必须满足的额外条件折入契约。

## 目标进行中追加条件：`/subgoal`

目标激活期间，你可以使用 `/subgoal <text>` 追加额外的验收条件，而不会重置循环。每次调用会向目标的子目标列表添加一个编号条目；下一轮 agent 看到的**续行 prompt** 包含原始目标以及一个"用户在循环中途追加的额外条件"块，**裁判 prompt** 也会被重写，使裁判在判定时必须考虑所有子目标——只有原始目标**和**所有子目标均满足时，目标才会被标记为完成。

| 命令 | 功能 |
|---|---|
| `/subgoal <text>` | 向活跃目标追加一个新条件。需要有活跃的 `/goal`。 |
| `/subgoal`（无参数） | 显示当前编号子目标列表。 |
| `/subgoal remove <N>` | 删除第 N 个子目标（从 1 开始计数）。 |
| `/subgoal clear` | 删除所有子目标，但保留原始目标。 |

子目标与目标一起持久化存储在 `SessionDB.state_meta` 中，因此在 `/resume` 后依然有效。设置新的 `/goal <text>` 会替换目标并清空子目标列表；`/goal clear` 同样如此。

当你启动一个循环（"修复失败的测试"）后，中途发现还需要"为刚修复的 bug 添加回归测试"时，使用此功能——`/subgoal add a regression test` 可在不中断运行循环的情况下收紧成功条件。

## 质量关卡 {#quality-gates}

完成契约能让裁判更严格，但裁判仍然是一个阅读文字的 LLM。**质量关卡**更强：它是一条确定性的 shell 命令，必须以 0 退出，目标才可能完成。灵感来自 Prime-Agent 的有界自主模式（`--autonomous-gate`）。

```
/goal Fix the flaky session tests
/goal gate add scripts/run_tests.sh tests/hermes_cli/test_goals.py
```

每一轮的工作方式：

1. **关卡先于裁判运行。** 只要有任何关卡失败，就*不会调用*裁判——红色关卡是目标尚未完成的确定性证据。关卡的退出码和输出末尾（最后约 3 KB）会成为续行 prompt，让 agent 针对真实的失败迭代，而不是凭感觉。
2. **所有关卡通过 → 正常裁判。** 随后 LLM 裁判照常判定 done/blocked/continue/wait。
3. **工作区未变化 → 不重新运行。** 如果某个关卡失败后工作区没有任何变化（通过 HEAD + 工作树状态的 git 指纹追踪），该关卡不会重新运行——而是重放已记录的失败并递增尝试次数。卡住的 agent 无法在反复运行同一套红色测试上浪费时间。在 git 仓库之外，关卡总是会重新运行。
4. **重试次数有上限。** 每个关卡默认重试 3 次、超时 5 分钟。当某个关卡耗尽重试次数时，目标会自动暂停（与轮次预算类似），并提示你手动修复、删除该关卡，或执行 `/goal resume`。

关卡与目标一起持久化在 `SessionDB.state_meta` 中（在 `/resume` 和上下文压缩后依然有效），并且在网关上运行中途管理关卡（`/goal gate …`）是安全的——关卡只在轮次边界运行。

关卡与契约可以组合使用：用契约塑造 *agent 的目标方向*，用关卡让*「完成」可被机械地检验*。两者同时设置时，关卡先运行。

## 停靠在后台进程上：自动执行，并提供手动覆盖

有些目标被某个需要数分钟、且自行运行的东西所阻塞——已推送 PR 的 CI、一次长时间构建、一个测试矩阵、一次部署，或一段限流冷却期。若无特殊处理，目标循环会在等待期间每轮都催促 agent 做「好了吗？」这类无用功。

**这一点是自动处理的。** 每一轮中，裁判都会看到 agent 自己的实时后台进程（本会话启动的 `terminal(background=true)` 注册表条目——pid、会话 id、命令、运行时长、近期输出，以及任何 `watch_patterns` / `notify_on_complete` 触发器；由委派子代理启动的进程不会显示，因此扇出的父代理永远不会停靠在某个 worker 的轮询器上），与目标和 agent 的回复一并呈现。当 agent 的进展确实被其中某个进程阻塞时，裁判会返回 **`wait`** 判定而非 `continue`，循环随即**停靠**：接下来的轮次被跳过（不调用裁判、不续行、不消耗轮次），直到等待条件被满足——然后带着结果正常恢复。基于 pid/会话的等待上限为 30 分钟；永不退出的进程（监视器、被遗忘的轮询器）无法让目标无限期停靠。裁判也可以基于**时间**停靠（`wait_for_seconds`），用于退避/冷却等待。停靠期间 `/goal status` 会显示 `⏳ Goal (parked …)`。

裁判会根据进程自身的信号选择合适的等待类型：

- **`wait_on_session <id>`** —— 在进程*自身的触发器*触发时释放：进程退出，**或**（若它是带 `watch_patterns` 启动的）其模式匹配成功。这适用于会在**运行中途**发出信号、且可能永远不会自行退出的长驻监视器 / 服务器 / 轮询器（例如打印 `BUILD SUCCESSFUL` 后继续运行的构建进程，或 `notify_on_complete` 监视器）。
- **`wait_on_pid <pid>`** —— 仅在进程退出时释放。
- **`wait_for_seconds <n>`** —— 在固定延迟后释放。

你无需为此输入任何内容——这是裁判根据循环交给它的进程上下文做出的决定。手动命令仅作为覆盖手段存在：

| 命令 | 功能 |
|---|---|
| `/goal wait <pid> [reason]` | 手动将循环停靠，直到该 PID 对应的进程退出。 |
| `/goal unwait` | 清除任何等待屏障（由裁判或手动设置）并立即恢复。 |

该屏障（基于 pid 或时间）与目标一起持久化在 `SessionDB.state_meta` 中，因此在 `/resume` 后依然有效。`/goal pause`、`/goal resume` 和 `/goal clear` 都会将其撤销。如果设置屏障时该 PID 已经死亡（或在停靠期间死亡），或时间期限已过，屏障会在下一次检查时清除——过期屏障永远不会卡住循环。

典型流程：agent 推送一个 PR，用 `terminal(background=true, notify_on_complete=true)` 启动一个 CI 监视器，并报告「正在监视 CI」。裁判看到监视器进程仍在运行，于是对其 pid 返回 `wait`，循环随即安静下来——待 CI 一结束便立刻恢复，并针对实际结果判定目标。

## 行为细节

### 裁判

每轮结束后，Hermes 会调用一个辅助模型，传入：

- 持续目标文本
- agent 最新的最终回复（最后约 4 KB 文本）
- 一个系统 prompt，要求裁判以严格的单行 JSON 格式回复：`{"verdict": "done" | "blocked" | "continue" | "wait", "reason": "<one-sentence rationale>"}`（wait 判定会附加 `wait_on_session` / `wait_on_pid` / `wait_for_seconds`；旧版的 `{"done": <bool>, "reason": "..."}` 形状仍被接受）

裁判刻意保守：只有当回复**明确**确认目标已完成、最终交付物已清晰产出时，才会将目标标记为 `done`。如果 agent 说明目标**不可达**（不可能、超出范围、需要用户输入），则会得到 `blocked` 判定——而绝不是 `done`：目标会附带裁判给出的原因**暂停**（`🚫 Goal judged unachievable — paused`），这样你可以用 `/goal <text>` 重新界定范围，或用 `/goal resume` 强制继续，而不是白白消耗预算，或让一个不可能的任务被当作完成放行。

### 失败开放语义

若裁判出错（网络抖动、响应格式错误、辅助客户端不可用），Hermes 将判定视为 `continue`——损坏的裁判不会阻塞进度。**轮次预算**才是真正的兜底机制。

### 轮次预算

默认为 20 个续行轮次（`config.yaml` 中的 `goals.max_turns`）。预算耗尽时，Hermes 自动暂停并告知你如何继续：

```
⏸ Goal paused — 20/20 turns used. Use /goal resume to keep going, or /goal clear to stop.
```

`/goal resume` 将计数器重置为零，你可以按可控的块继续推进。

### 用户消息始终优先

目标激活期间，你发送的任何真实消息都优先于续行循环。在 CLI 上，你的消息会在队列中的续行消息之前进入 `_pending_input`；在 gateway 上，它以同样的方式通过适配器 FIFO 传递。你的轮次结束后裁判会再次运行——因此如果你的消息恰好完成了目标，裁判会捕获到并停止循环。

### 运行中安全性（gateway）

agent 正在运行时，`/goal status`、`/goal pause`、`/goal clear`、`/goal wait` 和 `/goal unwait` 可以安全执行——它们只操作控制面状态，不会中断当前轮次。在运行中设置**新**目标（`/goal <new text>`）会被拒绝，并提示你先执行 `/stop`，以防旧续行与新目标产生竞争。

### 持久化

目标状态存储在 `SessionDB.state_meta` 中，以 `goal:<session_id>` 为键。这意味着 `/resume` 可以从你离开的地方继续——设置目标、合上笔记本、明天回来、执行 `/resume`，目标依然完好如初（活跃、暂停或已完成）。

### Prompt 缓存

续行 prompt 是一条以用户角色追加到历史记录中的普通消息。它**不会**修改系统 prompt、切换工具集，也不会以任何使 Hermes prompt 缓存失效的方式改动对话。运行一个 20 轮目标，在缓存层面与 20 轮普通对话的开销相同。

## 配置

在 `~/.hermes/config.yaml` 中添加：

```yaml
goals:
  # Hermes 自动暂停并要求你执行 /goal resume 之前的最大续行轮次。
  # 默认 20。若想要更紧凑的循环可降低此值；
  # 长时间重构可适当提高。
  max_turns: 20
```

### 选择裁判模型

裁判使用 `goal_judge` 辅助任务。默认情况下，它解析为你的主模型（参见[辅助模型](/user-guide/configuration#auxiliary-models)）。若想将裁判路由到廉价快速的模型以降低成本，可添加覆盖配置：

```yaml
auxiliary:
  goal_judge:
    provider: openrouter
    model: google/gemini-3-flash-preview
```

裁判调用量小（约 200 个输出 token），每轮运行一次，因此廉价快速的模型通常是正确选择。

## 示例演练

```
You: /goal Create four files /tmp/note_{1..4}.txt, one per turn, each containing its number as text

  ⊙ Goal set (20-turn budget): Create four files /tmp/note_{1..4}.txt, one per turn, each containing its number as text

Hermes: Creating /tmp/note_1.txt now.
  💻 echo "1" > /tmp/note_1.txt   (0.1s)
  I've created /tmp/note_1.txt with the content "1". I'll continue with the remaining files on the next turn as you specified.

  ↻ Continuing toward goal (1/20): Only 1 of 4 files has been created; 3 files remain.

Hermes: [Continuing toward your standing goal]
  💻 echo "2" > /tmp/note_2.txt   (0.1s)
  Created /tmp/note_2.txt. Two more to go.

  ↻ Continuing toward goal (2/20): 2 of 4 files created; 2 remain.

Hermes: [Continuing toward your standing goal]
  💻 echo "3" > /tmp/note_3.txt   (0.1s)
  Created /tmp/note_3.txt.

  ↻ Continuing toward goal (3/20): 3 of 4 files created; 1 remains.

Hermes: [Continuing toward your standing goal]
  💻 echo "4" > /tmp/note_4.txt   (0.1s)
  All four files have been created: /tmp/note_1.txt through /tmp/note_4.txt, each containing its number.

  ✓ Goal achieved: All four files were created with the specified content, completing the goal.

You: _
```

四轮，一次 `/goal` 调用，你零次"继续"提示。

## 裁判判断有误时

没有裁判是完美的。需注意两种失败模式：

**假阴性——目标实际已完成，裁判却说继续。** 轮次预算会兜底。你会看到 `⏸ Goal paused`，可以执行 `/goal clear` 或直接发送新消息。

**假阳性——工作尚未完成，裁判却说已完成。** 你会看到 `✓ Goal achieved`，但你知道实际情况并非如此。发送后续消息继续，或更精确地重新设置目标：`/goal <更具体的文本>`。裁判的系统 prompt 刻意保守，以使假阳性比假阴性更少出现。

如果你觉得某次裁判判定不可信，`↻ Continuing toward goal` 或 `✓ Goal achieved` 行中的原因文本会告诉你裁判看到了什么。这通常足以诊断出是目标文本存在歧义，还是模型的回复有问题。

## 致谢

`/goal` 是 Hermes 对 **Ralph loop** 模式的实现。面向用户的设计——跨轮次保持目标存活、不达成不停止，以及创建/暂停/恢复/清除控制——由 OpenAI Codex 团队的 Eric Traut 在 [Codex CLI 0.128.0](https://github.com/openai/codex) 中推广并落地。我们的实现是独立的（中央 `CommandDef` 注册表、`SessionDB.state_meta` 持久化、辅助客户端裁判、gateway 侧的适配器 FIFO 续行），但这个想法源自他们。功劳归于应得之人。