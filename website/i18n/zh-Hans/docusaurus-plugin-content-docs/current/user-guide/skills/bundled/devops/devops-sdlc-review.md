---
title: "Sdlc Review — 审查 Kanban 交接并路由已验证的结果"
sidebar_label: "Sdlc Review"
description: "审查 Kanban 交接并路由已验证的结果"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Sdlc Review

审查 Kanban 交接并路由已验证的结果。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/devops/sdlc-review` |
| 版本 | `1.1.0` |
| 作者 | Jakub Wolniewicz (@frizikk) + Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `kanban`, `review`, `quality`, `verification` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# SDLC Review Skill

独立验证从 Kanban 实现运行交接到审查通道（review lane）的工作，然后批准、要求修改或上报。本 skill 审查交付物及其证据；它不会接管实现者的工作。

## 何时使用 {#when-to-use}

当以下条件全部满足时使用本 skill：

- dispatcher 为从 `review` 通道认领的任务派生了你；
- 实现者提交了一个 `review_requested` 交接；
- 该任务在完成之前需要一个独立的裁决。

不要将其用于单独的下游审查卡片。下游卡片是带有面向审查规格说明的普通实现工作，会通过其自身的生命周期完成。

## 前置条件 {#prerequisites}

- 一个带有当前任务和运行标识符的 Kanban worker 上下文。
- 原生 Kanban 工具：`kanban_show`、`kanban_comment`、`kanban_complete`、`kanban_request_changes` 和 `kanban_block`。
- 当交付物是代码时，通过 `read_file`、`search_files` 和 `terminal` 访问工作区。
- 任务的原始规格说明、验收标准、交接摘要以及先前的运行历史必须能通过 `kanban_show` 获取。

## 如何运行 {#how-to-run}

本 skill 由审查 dispatcher 自动加载。在检查文件或选择裁决之前，先从 `kanban_show` 开始。

1. 阅读任务规格说明和最新的 `review_requested` 交接。
2. 检查实际交付物并运行相关验证。
3. 选择且仅选择一个裁决：批准、要求修改或上报。
4. 在终结性的 Kanban 状态转换中记录具体证据。

## 快速参考 {#quick-reference}

| 裁决 | 何时 | 最终动作 |
|---|---|---|
| 批准 | 验收标准和验证均通过 | `kanban_complete` |
| 要求修改 | 仍存在可纠正的实现缺陷 | `kanban_comment`，然后 `kanban_request_changes` |
| 上报 | 需要人类决策或外部前置条件 | `kanban_block` |

要求修改的状态转换会将任务退回给其原始实现者。当该实现者在未指定审查者的情况下再次请求审查时，持久化的审查者来源信息会把复审路由回同一个审查者 profile。

## 审查视角 {#review-lenses}

每一轮都变换审视工作的方式，而不是重复同样的检查。去相关的视角能捕捉不同类别的缺陷：冷读工件能暴露被实现者叙述掩盖掉的设计与正确性问题，实际执行能暴露无法复现的声明，严格的契约审计能暴露悄然发生的范围漂移。在第 3 轮重复第 1 轮的视角，大多只会重新发现第 1 轮已经发现的问题。

根据任务记录已提供的历史确定当前轮次：统计 worker 上下文中 "Prior attempts on this task" 部分里 `changes_requested` 条目的数量（在 `kanban_show` 中也可作为先前运行看到）。当前审查轮次就是该数量加一。因此第 1 轮显示零次 `changes_requested` 尝试；第 2 轮显示一次；依此类推。

| 轮次 | 视角 | 如何应用 |
|---|---|---|
| 1 | 工件 | 在阅读实现者摘要之前，先冷读 diff 或交付物。形成独立判断，然后将其与交接叙述对比，并调查每一处不一致。 |
| 2 | 执行 | 检出工作并通过 `terminal` 实际运行它：构建、测试，并亲自验证所报告的行为。以实证方式核实每一条交接声明，而不是重读工件。 |
| 3+ | 契约 | 重读原始任务正文和验收标准，然后严格对照它们审计交付物。同时核实每一轮先前 `kanban_request_changes` 中的每一项是否确实已落实。 |

“流程”一节中的基线职责在每一轮仍然适用；视角决定你以哪种检查为先、为重。

### 临时审查扇出的视角变化 {#lens-variation-for-ad-hoc-review-fan-outs}

同样的原则也适用于 Kanban 审查通道之外。通过 `delegate_task` 派生多个并行审查者时，给每个审查者不同的视角——一个仅看 diff 的简报、一个完整上下文的简报、一个检出并运行的简报——而不是相同的简报。相同的简报会产出相关联的裁决和重复的发现；变化的简报能以相同的审查成本覆盖更多缺陷类别。

## 流程 {#procedure}

### 1. 从持久的任务记录中定位 {#1-orient-from-the-durable-task-record}

调用 `kanban_show` 并识别：

- 原始任务正文和验收标准；
- 最新的实现摘要和结构化元数据；
- 变更的文件、提交标识符和测试证据；
- 早先运行中的评论和决策；
- 先前审查轮次的发现。

将交接视为一个有待验证的声明，而不是工作正确的证明。

### 2. 对比要求的行为与交付的行为 {#2-compare-requested-behavior-with-delivered-behavior}

将每一条验收标准映射到具体的实现或输出证据。在决定是否进行更深入的检查之前，记下遗漏、语义变更以及无关的范围。

对于代码工作：

1. 使用 `read_file` 和 `search_files` 检查变更的路径及其调用方。
2. 使用 `terminal` 检查 diff，并运行项目现有的针对性测试、lint、类型检查或构建命令。
3. 在可行时，演练所报告的失败路径以及至少一条普通的对照路径。
4. 检查与该变更相关的错误处理、边界情况、并发边界、数据保全、安全边界以及跨平台行为。
5. 确认测试断言的是行为，而不仅仅是对源码文本或常量做快照。

对于非代码工作：

1. 检查完整的交付物，而不只是其摘要。
2. 检查正确性、完整性、格式和出处。
3. 当引用的 URL 或外部事实会影响裁决时，使用合适的原生工具进行验证。

### 3. 选择一个裁决 {#3-choose-one-verdict}

#### 批准 {#approve}

仅当验收标准得到满足且证据充分时才批准。调用：

```text
kanban_complete(
    summary="Reviewed and approved. <what was verified>",
    metadata={"review_outcome": "approved", "reviewer_checks": [...]}
)
```

写明通过的确切检查，以及任何不阻碍验收的有限保留意见。

#### 要求修改 {#request-changes}

用于具体、可纠正的缺陷。先记录可操作的发现：

```text
kanban_comment(
    task_id="<current-task-id>",
    body="Changes requested:\n1. <file or artifact + defect>\n2. <required correction>",
)
```

然后将同一任务退回给其实现者：

```text
kanban_request_changes(
    reason="<concise summary of the required corrections>"
)
```

说明缺陷在哪里、如何复现、为何违反了任务要求，以及解决它所需的最低结果。该状态转换不使用阻塞项复发计数。

#### 上报 {#escalate}

仅当审查者和实现者在没有人类决策或外部前置条件的情况下无法解决问题时才上报：

```text
kanban_block(
    reason="escalation: <decision or prerequisite required>"
)
```

解释被阻塞的决策，以及继续推进所需的最少信息。

### 4. 保持角色分离 {#4-preserve-role-separation}

作为审查者时不要编辑实现。要求修改，让实现者产出下一个候选版本；然后在下一次审查运行中独立验证该候选版本。

## 常见陷阱 {#pitfalls}

- **橡皮图章：** 一份看似通过的交接摘要并不是独立证据。
- **审查者亲自实现：** 编辑交付物会模糊归属，并削弱复审边界。
- **模糊的发现：** “需要改进”无法给实现者一个可复现的修正目标。
- **仅因风格而阻塞：** 当行为和仓库标准均已满足时，不要为偏好层面的细枝末节要求修改。
- **跳过先前轮次：** 复审必须同时确认所要求的修正已完成，以及先前通过的行为得以保留。
- **把阻塞用于普通返工：** 可纠正的缺陷应走 `kanban_request_changes`；`kanban_block` 留给真正的外部阻塞或人类决策。
- **没有证据就完成：** 每一份批准摘要都必须点名实际检查过的检查项或工件。

## 验证 {#verification}

提交裁决之前，确认：

- [ ] 已针对当前任务和运行阅读 `kanban_show`。
- [ ] 每一条验收标准都已映射到证据。
- [ ] 已检查实际交付物。
- [ ] 已运行相关的针对性检查，或在无法执行时记录了明确理由。
- [ ] 复审时已重新测试先前要求的修改。
- [ ] 已考虑无关的回归和范围变更。
- [ ] 裁决恰好使用了一个终结性动作。
- [ ] 摘要包含具体且不含机密的证据。
- [ ] 审查者没有编辑任何实现文件。
