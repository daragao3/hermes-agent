---
sidebar_position: 17
title: "周期循环"
description: "在会话内按周期间隔重复运行一个 prompt——Hermes 对 Claude Code 的 /loop 的实现。"
---

# 周期循环（`/loop`） {#recurring-loops-loop}

`/loop` 会**在你当前的会话内**按周期节奏重复运行一个 prompt（或一个斜杠命令）。每次唤醒都是一个真实的 agent 轮次：Hermes 会重新读取当前状态——最新的 CI 结果、最新的队列深度、文件此刻的内容——完成工作、汇报结果，然后安静下来，直到下一次触发。

这是 Hermes 对 **Claude Code 的 `/loop`**（及其别名 `/proactive`，在这里同样可用）的实现。[`/goal`](./goals.md) 由裁判驱动——“持续工作直到达成这个目标”——而 `/loop` 由计时器驱动：“每 N 分钟（或在合适的时候）再做一次，直到有某个条件叫停。”

## 适用场景 {#when-to-use-it}

- **轮询外部状态。** “盯着部署 / CI 运行 / 队列，有变化时告诉我。”这是最典型的用法。
- **迭代直到变绿。** “运行测试，修复失败项，重复直到全部通过。”
- **工作期间的监控。** 在同一个对话里做别的事情时，留意错误率或某个长任务的进度。
- **定期整理。** 在长会话中每 N 分钟重新运行一次 lint 或状态汇总。

当工作需要**无人值守**运行——整夜运行、按真正的日程运行、在终端重启后依然存续——请改用 [cron 任务](./cron.md)。`/loop` 存在于某个会话之内；cron 存在于所有会话之外。而当任务是一个有明确完成定义的单一目标时，[`/goal`](./goals.md) 通常更合适。

## 快速开始 {#quick-start}

```
/loop 5m check the deploy status and tell me if it's live yet
```

你会看到：

1. **循环已接受** —— `↻ Loop set (every 5m): check the deploy status…`
2. **首次唤醒立即触发** —— 在下一次空闲轮询时（gateway：下一次 15s 的监视扫描），Hermes 注入唤醒并针对当前状态运行一个普通轮次。
3. **重复** —— 此后每 5 分钟一次，直到某个停止条件触发或你将其停止。

循环一个斜杠命令同样简单：

```
/loop 10m /recap
```

## 两种节奏模式 {#the-two-cadence-modes}

**固定间隔——由你设定时钟。** 给出一个间隔（`30s`、`5m`、`2h`、`1h30m`），循环就按该日程触发。当你监视的对象按其自身的时间线变化时使用：

```
/loop 2m poll the build at ci.example.com/job/42 and ping me the moment it finishes
```

**自定节奏——由 Hermes 设定时钟。** 省略间隔，循环会自行调节节奏：它从下限开始（默认 1 分钟），当 agent 的回复不再变化时按指数退避——2m、4m、8m，直到上限（默认 15 分钟）。一旦某次回复与上一次不同，节奏立即回到下限。变化检测是一次本地摘要比较（忽略时间戳），因此空闲等待不会产生额外开销：

```
/loop keep an eye on the migration and summarize progress
```

经验法则：**当外部时钟驱动工作时用固定间隔；当工作本身驱动节奏时用自定节奏。**

## 停止条件 {#stop-conditions}

当以下任一条件触发时，循环结束：

| 条件 | 方式 |
|---|---|
| agent 判定已完成 | 唤醒 prompt 会教 agent 在任务完成或已无意义时，在回复末尾单独一行写上 `LOOP_COMPLETE`。 |
| 运行次数上限 | `--times N` —— 在 N 次唤醒后停止。 |
| 基于证据的条件 | `--until <condition>` —— 每次唤醒后，由驱动 `/goal` 的同一个辅助裁判对照你的条件检查回复。如果裁判判定该条件无法达成，循环会带着原因**暂停**，而不是一直重复触发直到耗尽触发预算（失败即放行：坏掉的裁判绝不会卡死循环）。 |
| 你 | `/loop stop`（或用 `/loop pause` 保留它）。 |
| 兜底预算 | `loops.max_ticks`（默认 100）会暂停循环，使无人值守的会话不会无休止地消耗 token。`0` = 不限。 |

示例：

```
/loop 2m poll CI --times 30
/loop 5m watch the queue --until queue depth reaches zero
```

## 命令 {#commands}

| 命令 | 作用 |
|---|---|
| `/loop [interval] <prompt> [--times N] [--until <cond>]` | 为此会话启动（或替换）循环。首次唤醒立即触发；之后按节奏进行。 |
| `/loop` 或 `/loop status` | 显示节奏、已触发次数以及距下次唤醒的时间。 |
| `/loop pause` | 停止触发但不丢失循环。 |
| `/loop resume` | 重新继续。 |
| `/loop stop` | 结束循环。 |
| `/proactive …` | `/loop` 的别名（与 Claude Code 保持一致）。 |

适用于 CLI、TUI（`hermes --tui`）、Web 仪表盘聊天、桌面应用以及所有 gateway 平台（Telegram、Discord、Slack、WhatsApp……）。在消息平台上，gateway 甚至会在你的消息之间触发唤醒——循环属于该聊天的会话，其结果以普通回复的形式送达。

## 与 `/goal` 混用 {#mixing-with-goal}

两个功能都会在空闲边界注入合成轮次，因此它们遵循同一条规则：**活跃的目标拥有会话。** 当 `/goal` 正在主动驱动时（裁判判定“continue”），循环唤醒会延后。一旦目标完成、暂停或停驻在等待屏障上（`/goal wait`，或裁判自动给出的 WAIT 裁决），循环会立即重新利用空闲时间。停驻的目标加上 `/loop` 是一个自然的组合：目标等待那件大型异步事务，而循环对另一件事保持心跳。

真实的用户消息总是优先于两者——唤醒只在会话空闲且你没有排队消息时触发。

## 行为细节 {#behavior-details}

- **唤醒是一个普通的 user 角色轮次。** 不修改系统 prompt，不切换工具集——prompt 缓存保持完好。
- **在 `/resume` 和压缩后依然存续。** 循环状态按会话持久化，并跨越上下文压缩边界迁移，与 `/goal` 相同。
- **每个会话一个循环。** 设置新的 `/loop` 会替换旧的。要运行多个循环，就运行多个会话（或者用 cron 管理一组日程）。
- **中断唤醒轮次（Ctrl+C）会暂停循环** —— 可用 `/loop resume` 恢复，因此取消就真的意味着取消。
- **token 成本随节奏增长。** 每次触发都是一个完整的 agent 轮次。让间隔匹配状态实际变化的频率；空闲等待时优先使用自定节奏。

## 配置 {#configuration}

```yaml
# ~/.hermes/config.yaml
loops:
  min_interval_seconds: 30       # 固定间隔的下限
  max_ticks: 100                 # 兜底预算（0 = 不限）
  self_paced_floor_seconds: 60   # 自定节奏的起始节奏
  self_paced_ceiling_seconds: 900  # 自定节奏的最大退避
```

`--until` 裁判通过 `goal_judge` 辅助任务路由，因此 `auxiliary.goal_judge.*` 路由覆盖（provider、model）同样适用于循环条件。

## `/loop`、`/goal` 与 cron 对比 {#loop-vs-goal-vs-cron}

| | `/loop` | `/goal` | cron |
|---|---|---|---|
| **触发方式** | 计时器（或自定节奏） | 每轮结束后的裁判裁决 | 日程，位于任何会话之外 |
| **所在位置** | 你当前的会话 | 你当前的会话 | 每次运行一个独立会话 |
| **何时结束** | 停止条件 / 上限 / 你 | 目标达成 / 预算 / 你 | 你移除该任务 |
| **最适合** | 轮询、监控、定期重复运行 | 单一目标，迭代直到完成 | 无人值守、长周期的日程 |
