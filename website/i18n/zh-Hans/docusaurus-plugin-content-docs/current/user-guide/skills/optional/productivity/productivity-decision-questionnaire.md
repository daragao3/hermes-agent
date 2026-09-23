---
title: "Decision Questionnaire — 将一个无法独自回答的决策转化为问卷文档"
sidebar_label: "Decision Questionnaire"
description: "将一个无法独自回答的决策转化为问卷文档"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Decision Questionnaire

将一个无法独自回答的决策转化为问卷文档。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/productivity/decision-questionnaire` 安装 |
| 路径 | `optional-skills/productivity/decision-questionnaire` |
| 版本 | `1.0.0` |
| 作者 | Matt Pocock (mattpocock/skills, to-questionnaire) + Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `questionnaire`, `decision`, `async`, `stakeholder`, `discovery`, `communication` |
| 相关 skill | [`meeting-action-items`](/user-guide/skills/bundled/productivity/productivity-meeting-action-items), [`document-to-action-items`](/user-guide/skills/bundled/productivity/productivity-document-to-action-items) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Decision Questionnaire

将用户无法独自回答的问题转化为一份**问卷**：一份 Markdown 文档，用户可以把它交给某个人异步填写，或者在会议中一起填写。接收者掌握着用户所缺乏的知识；问卷的作用就是把这些知识从他们那里提取出来。

移植自 mattpocock/skills 中采用 MIT 许可证的 `to-questionnaire` skill。

## 使用时机 {#when-to-use}

- 某个决策卡在他人掌握的事实或判断上（领域专家、利益相关方、供应商联系人、运维人员）
- 用户说“我需要就这件事问问 X”，或者因为等待他人的意见而一再推迟某个决策
- 为一场必须得到特定答案的会议做准备

当答案可以从环境中找到时（代码库、文档、网络），**不要**使用——先自己去找。

## 核心原则：访谈“发送”本身，而不是主题 {#core-principle-interview-the-send-not-the-subject}

用户无法回答主题层面的问题（这正是问题所在），但他们**总是**能回答关于“发送”本身的问题。只就这方面访谈他们，分两轮简短的交流：

1. **要发给谁？** 角色、专业领域、与用户的关系。这决定了问卷的语气以及它需要携带多少背景信息。当你知道接收者是谁、以及他们知道哪些用户不知道的东西时，即告完成。
2. **你需要得到什么回复？** 用户无法独自解决的具体决策或事实。当你有了一份具体的清单，列明用户最终必须能够做到或决定的事情时，即告完成。

然后**编写问卷**：按照下面的结构，起草针对“接收者所知”与“用户所需”之间差距的问题。将其写入当前目录下的 `decision-questionnaire-<slug>.md`（slug 取自主题），并报告绝对路径。当文件存在、且第 2 步中的每一项都被某个问题覆盖时，即告完成。

## 文档结构 {#document-structure}

将其定位为一份**探查型问卷**：用户缺乏背景信息，而接收者掌握着它。按照从最重要到次要的顺序排列问题（异步意味着你可能只有一次机会）。当问题超过寥寥几个时，按主题将它们分组到 `##` 标题下。

模板：

```markdown
# <Questionnaire title>

**Purpose:** why this questionnaire exists and the decision riding on it.

**From:** <the user> · **To:** <the recipient> ·
**How your answers will be used:** <where they go>

## Context

One paragraph orienting a recipient who wasn't in the user's head. Enough
to answer well, not a page.

## How to answer

Deadline and rough effort. Partial answers and "I don't know" are useful:
flag anything you're unsure of rather than skipping it.

## <Theme heading>

### <One question — a single idea, never compound>

_Why this matters: <one line, only where the question could be misread or
invite a throwaway answer>._

>

## Anything else?

A closing catch-all: anything we didn't ask that we should know?
```

每个问题的正下方都有一个答案占位（`>`）。

## 常见陷阱 {#pitfalls}

1. **就主题盘问用户。** 他们回答不了——这正是这份文档存在的原因。只访谈关于“发送”的问题。
2. **复合问题。** 每个问题只包含一个要点；拆分“和/或”类问题。
3. **把关键问题埋没在后面。** 最重要的放在最前面；异步接收者的注意力会逐渐消退。
4. **堆砌背景信息。** 一段用于引导的段落即可，而不是全部来龙去脉。
5. **在有歧义的问题上省略“为什么这很重要”这一行。** 正是这一行能把一个敷衍的回答变成有用的回答——但不要把它加到本身已经没有歧义的问题上。

## 验证 {#verification}

- [ ] 在起草之前，用两轮交流了解了接收者的角色/知识以及所需的结果
- [ ] 第 2 步中的每一项都至少被一个问题覆盖
- [ ] 问题都只包含单一要点、最重要的在前，且都有答案占位
- [ ] 文件已写入，并已向用户报告绝对路径
