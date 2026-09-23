---
title: "Weekly Review Planning —— 每周重置：承诺事项、停滞工作、下周计划"
sidebar_label: "Weekly Review Planning"
description: "每周重置：承诺事项、停滞工作、下周计划"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Weekly Review Planning

每周重置：承诺事项、停滞工作、下周计划。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/weekly-review-planning` |
| 版本 | `0.1.0` |
| 作者 | Ben Barclay (benbarclay), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Weekly-Review`, `Planning`, `Tasks`, `Calendar`, `Productivity` |
| 相关 skill | [`obsidian`](/user-guide/skills/bundled/note-taking/note-taking-obsidian), [`notion`](/user-guide/skills/bundled/productivity/productivity-notion), [`airtable`](/user-guide/skills/bundled/productivity/productivity-airtable), [`google-workspace`](/user-guide/skills/bundled/productivity/productivity-google-workspace), [`email-inbox-triage`](/user-guide/skills/bundled/email/email-email-inbox-triage) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# 每周回顾与计划

在用户选定的各个系统上执行一次有边界的每周重置。这是一项具体的周期性任务，而不是一套通用的效率方法论——`weekly-review` Automation Blueprint 会把它作为 cron 任务进行调度。

## 何时使用 {#when-to-use}

- "Run my weekly review."
- "What did I commit to and what is slipping?"
- "Plan next week from my calendar, tasks, and notes."
- "Find stale projects and waiting items."
- 某个定时的每周回顾 cron 触发。

不适用于：每日简报（参见 `google-workspace` 的 daily-brief 参考）或单一收件箱分拣（`email-inbox-triage`）。

## 操作步骤 {#procedure}

### 1. 确定系统和时间窗口 {#1-set-systems-and-window}

确认时区、回顾周期、规划范围、权威的任务/项目存储、日历、收件箱以及允许的写入操作。默认只给出建议/草稿，而不做修改。当各信息源之间的冲突都已明确哪一方为准时，此步完成。

### 2. 回顾日历证据 {#2-review-calendar-evidence}

加载 `google-workspace` 或相关的日历连接器。检查已结束一周中的会议和承诺，然后检查接下来 1-2 周的截止日期、出行、准备工作和可用容量。记录过去事件所隐含的后续事项以及未来的冲突。当回顾部分和前瞻部分都已覆盖时，此步完成。

### 3. 清空收集箱 {#3-clear-capture-inboxes}

回顾任务收件箱、笔记（`obsidian`、`notion`）、已标记的邮件（线程级分拣由 `email-inbox-triage` 负责）以及其他已声明的收集点。把每一项转换为下一步行动、项目、等待中、已排期、将来某天、参考资料、归档或删除提议。在范围获批之前不要做修改。当剩余未处理的条目已被计数并说明时，此步完成。

### 4. 核对进行中的项目 {#4-reconcile-active-projects}

为每个项目确定期望结果、下一步行动、负责人、截止日期、阻碍因素、最后一次有意义的活动以及来源链接。标记出没有下一步行动、错过日期、记录重复或状态矛盾的项目。当每个进行中的项目都可执行或已明确暂停时，此步完成。

### 5. 回顾等待事项和承诺 {#5-review-waiting-and-commitments}

找出用户做出的承诺以及他人欠用户的事项。提出带有日期和渠道的跟进建议。不要把沉默推断为已完成。当每个等待事项都有负责人和下一次回顾/跟进日期时，此步完成。

### 6. 制定考虑容量的计划 {#6-build-a-capacity-aware-plan}

估算固定的日历负载，选出少量的每周目标以及近期的下一步行动。按后果、截止日期、依赖关系和工作量排序；不要把每个空闲小时都填满。当计划符合实际容量并列出了被推迟的工作时，此步完成。

### 7. 应用已批准的更新 {#7-apply-approved-updates}

仅在获得批准后，才更新任务/项目、创建日历占位、归档已处理条目以及起草跟进消息。从提供方读回每一条被修改的记录。当经过验证的写入与回顾摘要一致时，此步完成。

## 输出结构 {#output-shape}

1. 成果和已完成的承诺
2. 已逾期或有风险
3. 等待中/需跟进
4. 停滞或含糊的项目
5. 下周目标和日历约束
6. 待批准的更新提议
7. 覆盖缺口

## 常见陷阱 {#pitfalls}

- 只根据任务做计划，而不考虑日历容量。
- 把每个未完成的事项都作为高优先级顺延。
- 把没有下一步行动的项目标记为进行中。
- 悄悄删除或改期个人承诺。
- 把他人的沉默当作已完成。

## 验证 {#verification}

- [ ] 已结束的一周和规划范围都已覆盖，或已说明缺口。
- [ ] 每一个停滞/等待标记都能追溯到具体的记录、事件或线程。
- [ ] 没有任何任务、事件或笔记在未经批准的情况下被修改；已批准的写入都已读回确认。
- [ ] 计划列出了被推迟的内容，而不仅仅是被选中的内容。
