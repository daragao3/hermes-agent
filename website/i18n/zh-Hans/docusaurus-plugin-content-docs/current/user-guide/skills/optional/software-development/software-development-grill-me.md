---
title: "Grill Me —— 在实现之前对计划进行对抗式访谈"
sidebar_label: "Grill Me"
description: "在实现之前对计划进行对抗式访谈"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Grill Me

在实现之前对计划进行对抗式访谈。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/software-development/grill-me` 安装 |
| 路径 | `optional-skills/software-development/grill-me` |
| 版本 | `2.0.0` |
| 作者 | Rafael Zendron (rafaumeu) + Matt Pocock (mattpocock/skills, grilling) + Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `planning`, `adversarial`, `interview`, `decision-tree`, `pre-implementation`, `review`, `alignment` |
| 相关 skill | [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review)、[`subagent-driven-development`](/user-guide/skills/optional/software-development/software-development-subagent-driven-development)、[`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Grill Me

在编写任何代码之前，通过结构化的对抗式提问对计划进行压力测试。
将计划建模为一棵**设计树**——每个决策都会分支出依附于它的
后续决策——并分轮次访谈用户，直到每个分支都得到解决、
没有任何东西被默默假定。

它结合了原版的分阶段纪律，以及 mattpocock/skills 中 `grilling`
的前沿轮次机制。

## 使用时机 {#when-to-use}

- 用户说"grill me"、"访谈一下我的计划"、"对这个想法做压力测试"
- 在复杂工作之前：认证流程、schema 变更、迁移、支付
- 计划中存在未解决的决策，或看起来含糊不清
- 在进行 `subagent-driven-development` 拆解之前

不要用于已有代码（使用 `requesting-code-review`）或简单的一次性
任务。

## 前置条件 {#prerequisites}

无。本 skill 适用于任何计划或初步想法。

## 核心机制：前沿轮次 {#core-mechanic-frontier-rounds}

将计划映射为一棵设计树。**前沿**是所有前提条件都已确定的
决策——也就是你现在就能提出、无需猜测尚未听到的答案的那些问题。

按**轮次**进行：在一条消息中提出当前前沿的全部问题，编号列出，
每个问题都附上你的推荐答案。然后等待。如果某个问题的答案
依赖于本轮中另一个仍未解决的问题，它就属于之后的轮次，而不是这一轮。

每一轮按如下格式：

```
❓ Q1 — <question title>: <question body, options if relevant>
➡️ Recommendation: <your recommended answer + one-line why>

❓ Q2 — <question title>: <question body>
➡️ Recommendation: <...>
```

每个答案都会重塑这棵树：已确定的决策会把前沿向外推进，
并解锁依赖它们的问题。重新计算前沿，然后提出下一
轮问题。

**事实由你负责；决策由用户负责。** 当某个前沿问题
需要来自环境的事实（代码库、文件系统、配置、文档）时，
自己用 `search_files` / `read_file` / `terminal` 去查找——或者对繁重的探索
通过 `delegate_task` 派发一个子 agent。凡是你能自己查到的，绝不要问用户。
不要因为一次探索而停滞：只有依赖它的下游问题需要等待；
前沿中的其余问题现在就提出。

## 问题覆盖范围（将这些分支纳入设计树） {#question-coverage-work-these-branches-into-the-tree}

**理解**——真正的目标和边界：
- 实际目标是什么？哪些内容明确在范围内、哪些明确在范围外？
- 有哪些约束（时间、技术、团队、预算）？用户是谁？

**技术决策**——针对每个架构选择：
- "为什么选这种方案而不是 X？" / "如果 Y 失败会怎样？"
- "最坏情况是什么？" / "你会如何回滚？"
- 与现有代码库交叉对照；如果项目中已有
  针对此问题的模式，要明确指出。

**边界情况：**
- "如果用户做了 Z 会怎样？" / "如果依赖 X 宕机了怎么办？"
- "如果流量是预期的 100 倍呢？" / "有哪些安全影响？"

## 综合总结（当前沿为空时） {#synthesis-when-the-frontier-is-empty}

1. 用要点总结所有决策
2. 列出所有仍未解决的事项，以及明确在范围之外的内容
3. 询问："我们达成一致了吗？我应该开始实现，还是需要调整什么？"

在用户确认达成共识之前，不要按计划采取行动。

## 常见陷阱 {#pitfalls}

1. **不按依赖顺序提问。** 依赖于一个尚未回答的问题的提问，
   只是戴着问号的猜测。把它留到之后的轮次。
2. **跳过代码库。** 用 Hermes 工具从代码中查找事实，而不是
   问用户。
3. **把"我不知道"当作最终答案。** 提出选项，解释
   权衡，给出推荐。
4. **在盘问过程中写代码。** 只做对齐——在得到明确许可之后
   再写代码。
5. **过于随和。** 你的工作是发现问题。如果一切看起来都
   没问题，那就更仔细地找。
6. **不适配用户的语言。** 用户说什么语言，
   就用什么语言进行访谈。

## 验证 {#verification}

- [ ] 每一轮中的每个问题，其前提条件都已全部确定
- [ ] 每个问题都附有推荐答案
- [ ] 通过探索代码库获取事实，而不是问用户
- [ ] 在综合总结之前前沿已为空（没有分支被默默假定）
- [ ] 产出了一份清晰的总结，涵盖所有决策和未决事项
- [ ] 在停止之前确认了与用户达成一致
