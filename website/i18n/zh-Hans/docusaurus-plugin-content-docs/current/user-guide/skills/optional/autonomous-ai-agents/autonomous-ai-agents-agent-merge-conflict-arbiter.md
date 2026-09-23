---
title: "Agent Merge Conflict Arbiter — 两个 agent 之间合并冲突的中立仲裁者"
sidebar_label: "Agent Merge Conflict Arbiter"
description: "两个 agent 之间合并冲突的中立仲裁者"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Agent Merge Conflict Arbiter

两个 agent 之间合并冲突的中立仲裁者。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/autonomous-ai-agents/agent-merge-conflict-arbiter` 安装 |
| 路径 | `optional-skills/autonomous-ai-agents/agent-merge-conflict-arbiter` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Multi-Agent`, `Git`, `Merge-Conflict`, `Kanban`, `Arbitration` |
| 相关 skill | [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Agent 合并冲突仲裁者 {#agent-merge-conflict-arbiter-1}

作为公正的第三方，解决两个 AGENT 分支之间的 git 合并冲突。针对同伴工作解决冲突的
agent 几乎总会要么覆盖同伴的改动，要么放弃自己的改动——它们缺少同伴的上下文，
且偏向自己一方。本 skill 就是解决之道：一个中立的调和者，接收双方的 diff 以及
双方陈述的意图，产出合并结果，就像合并队列（merge-queue）仲裁者一样。

## 何时使用 {#when-to-use}

- 在并行任务中两个 agent 的分支/worktree 发生冲突（kanban 工程流水线、
  并行 PR 波次、多 worktree 重构）。
- `git merge` 或 `git rebase` 因两个 agent 工作之间的冲突而中止，且两个原始
  agent 都不应自行裁决。
- 不要用于单个 agent 自身工作内部的冲突，也不要用于琐碎的
  lockfile/生成文件冲突（应重新生成这些文件）。

## 前置条件 {#prerequisites}

- 包含已中止合并的仓库检出，或者两个分支名以及自行执行合并的权限。
- 双方的意图来源：kanban 完成摘要（通过 `terminal` 运行
  `hermes kanban show <task-id>`）、PR 正文，或至少每个分支的提交信息。
- 项目的构建/测试命令（如果存在）。

## 如何运行 {#how-to-run}

**独立运行** —— 人类（或 agent）在存在冲突的仓库内调用本 skill：加载 skill，
然后从头到尾按照“流程”执行。

**派生中立 agent** —— 多 agent 任务中的首选形态：

- `delegate_task`：派生一个 subagent，其任务消息逐字包含仓库路径、两个分支名
  以及双方的意图摘要，并附上遵循本 skill 的指令。
- Kanban 原生方式：创建一张分配给**第三个 profile**（不是任一 worker 的 profile）
  的调和卡片，并将两张冲突卡片都链接为父卡片——
  `kanban_create(title="reconcile branch-a x branch-b", assignee="reconciler",
  parents=["t_a", "t_b"])`。父链接会自动将双方的完成摘要带入调和者的上下文；
  卡片正文应注明仓库路径和两个分支。

## 快速参考 {#quick-reference}

| Hunk 类别 | 定义 | 解决方式 |
|---|---|---|
| disjoint-intent | 两处改动服务于不同目标，可以共存 | 合并两者 |
| same-question-different-answer | 双方对同一个设计问题给出了不同答案 | 依据陈述的意图只选其一；明确公示该决定 |
| superseded | 在另一方改动后，一方的前提已不再成立 | 保留存续的一方；注明原因 |

公正性约定：绝不偏袒派生你的那一方；只改动存在冲突的区域（不做顺手修改）；
每一个设计问题的选择都必须明确出现在交回摘要中。

## 流程 {#procedure}

### 1. 收集双方信息 {#1-gather-both-sides}

- 通过 `terminal` 运行：`git status`（确认冲突状态并列出冲突文件）、
  `git merge-base <A> <B>`，然后对每一方运行
  `git log --oneline <base>..<side>`，并对每个冲突文件运行
  `git diff <base>..<side> -- <file>`。在已中止的合并中，`HEAD` 是一方，
  `MERGE_HEAD` 是另一方。
- 收集每一方的意图：用 `hermes kanban show <task-id>` 获取完成摘要/元数据，
  或 PR 正文，或上面 log 中的提交信息。在改动任何文件之前，为每一方写下
  一句话的意图。
- 完成标准：你能用自己的话陈述双方意图，并拿到了每个冲突文件的双方 diff。

### 2. 对每个冲突 hunk 分类 {#2-classify-every-conflicted-hunk}

- 用 `read_file` 打开每个冲突文件，定位每个
  `<<<<<<<`/`=======`/`>>>>>>>` 块。
- 依据快速参考表为每个 hunk 分配且仅分配一个类别，判断依据是陈述的意图
  ——而不是哪个改动看起来更好。
- 如果单个 hunk 包含多个独立决策（例如，可干净合并的新逻辑，外加一个双方
  回答不同的样式/取整选择），将其拆分为子决策并分别分类。
- 单个文件常常混合多种类别：一个 hunk 可能是设计冲突，而相邻的 hunk 是
  互不相交的。按 hunk 分类，而不是按文件分类。
- 完成标准：每个 hunk 都有书面类别和一行理由。

### 3. 在公正性约定下解决 {#3-resolve-under-the-impartiality-contract}

- 用 `patch`（或整文件重写时用 `write_file`）编辑每个 hunk：
  - disjoint-intent → 合并两处改动，使每个意图都得到完整满足。
  - same-question-different-answer → 选择最能满足所陈述意图的答案
    （例如，如果任务要求正确性，“严格校验”的意图胜过“快速默认值”）。
    绝不折中成双方都没有要求的混合方案。
  - superseded → 保留存续的一方；删除失效的前提。
- 绝不偏袒派生你的那一方。如果双方意图确实旗鼓相当，就上报
  （阻塞 kanban 卡片 / 回报），而不是猜测。
- 不改动冲突标记之外的任何内容——不格式化、不重命名、不做顺手修复。
- 通过 `terminal` 对每个已解决文件执行 `git add`。
- 完成标准：`search_files` 在仓库中找不到 `<<<<<<<` 标记，且每个已解决文件
  都已暂存。

### 4. 验证 {#4-verify}

- 通过 `terminal` 运行项目的构建/测试；至少导入/执行被改动的模块。两个意图
  都必须能在合并后的行为中观察到（例如，A 方的新语义与 B 方互不相交的新增
  内容都存在）。
- 完成合并：`git commit`（使用默认合并信息，再加上列出各 hunk 决策的正文即可）。
- 完成标准：验证通过且合并提交已存在。

### 5. 交回 {#5-hand-back}

- 产出一份点名每个 hunk 决策的完成摘要：
  `file:lines — class — which side(s) kept — rationale`。对每个
  same-question-different-answer hunk，写明设计问题以及你选择的答案，以便人类
  可以否决——绝不埋没设计决策。
- Kanban：`kanban_complete(summary=...)`。独立运行：打印摘要。
- 完成标准：摘要已交付并列出了所有 hunk。

## 常见陷阱 {#pitfalls}

- **偏袒自己**：如果你是由冲突 agent 之一派生的，你在结构上就有偏向——
  明确说明这一点，并有意识地权衡另一方的意图。优先采用第三 profile 的形态，
  从根本上避免这种情况。
- **折中处理**设计冲突会产生一个没人设计过的混合方案；选定一个答案并公示它。
- **按文件分类**：文件通常混合多种 hunk 类别；把整个文件归为一个类别会悄无
  声息地丢掉互不相交的改动。
- **顺手修改**会让合并无法审查，并夺走原始 agent 的决策权。
- **缺失意图**：仅凭提交信息可能信息不足；优先使用 kanban 完成摘要或 PR 正文。
  如果双方意图都无法还原，就上报而不是猜测。
- **屡次冲突**：多轮中在同一文件上反复出现的冲突是热点信号，而不是例行的
  调和工作——标记出来（例如一条 `hotspot: <path> — <reason>` kanban 评论），
  让编排者拆分该文件，而不是对其上每一次新冲突逐个调和。

## 验证 {#verification}

- `git status` 显示目标分支上是干净的工作树，并有一个合并提交。
- 不残留任何冲突标记（`search_files` 模式 `<<<<<<<`）。
- 构建/测试通过；双方意图都能被证明存在，或被丢弃的那一方已在摘要中明确点名。
- 交回摘要列出了每个 hunk 及其类别和理由。
