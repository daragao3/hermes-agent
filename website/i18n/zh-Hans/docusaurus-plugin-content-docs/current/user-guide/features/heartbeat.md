---
sidebar_position: 17
title: "会话心跳"
description: "一个周期性 prompt，会在当前会话空闲时重新进入该会话——/heartbeat every 10m Check the deployment."
---

# 会话心跳（`/heartbeat`） {#session-heartbeats-heartbeat}

`/heartbeat` 为**当前会话**设置一条周期性指令。每当会话空闲且间隔时间已到，该 prompt（提示词）就会作为一个普通的用户轮次触发——同一个对话、同一份上下文、同一个 prompt 缓存。

```
/heartbeat every 10m Check the deployment and report meaningful changes
```

灵感来自 Prime-Agent 的 `/heartbeat`。Hermes 的适配版本保持了严格的消息流不变量：心跳只会在轮次之间注入（绝不在运行中途），并且是一条普通的 user 角色消息。

## 心跳与 cron：我该用哪一个？ {#heartbeat-vs-cron-which-one-do-i-want}

两者看起来相似，但用途不同：

| | `/heartbeat` | [`hermes cron`](./cron) |
|---|---|---|
| 运行位置 | **当前对话**——完整上下文，记得之前的讨论 | 每次触发都是一个全新的隔离会话 |
| 进程重启后是否保留 | 状态保留（SessionDB）；gateway 的监视会在重启后自动恢复 | 是——完全持久化的调度器 |
| 数量 | 每个会话一个 | 任务数量不限 |
| 最适合 | “我们工作时，*在这个对话里*帮我盯着 X” | 常驻任务、报告、看门狗、定时投递 |

经验法则：如果周期性 prompt 需要对话的上下文，就用 `/heartbeat`。如果它是一个自包含的任务，就用 cron。

## 命令 {#commands}

| 命令 | 作用 |
|---|---|
| `/heartbeat every <interval> <prompt>` | 设置（或替换）会话的心跳。间隔：`90s`、`10m`、`2h`、`1d`（最小 60s）。 |
| `/heartbeat` 或 `/heartbeat status` | 显示心跳、其间隔以及距下次触发的时间。 |
| `/heartbeat pause` | 停止触发但不清除。 |
| `/heartbeat resume` | 恢复（重新锚定计时器——不会立即补发一次过期的触发）。 |
| `/heartbeat clear` | 移除心跳。 |

`/hb` 是其别名。适用于 CLI、TUI / Desktop 应用以及 gateway 平台（在 Slack 上使用 `/hermes heartbeat …`）。

## 行为细节 {#behavior-details}

- **仅在空闲时。** 心跳绝不会打断正在运行的轮次。如果触发时间到时 agent 正忙，它会在下一次空闲轮询时触发。在 gateway 中，空闲的受监视会话会被主动唤醒；无需新的入站消息。
- **错过的触发会合并。** 如果会话在多个间隔内一直忙碌（或进程未运行），你只会得到**一次**心跳轮次，而不是一堆积压。计时器在每次触发时重新锚定。
- **用户消息优先。** 排队中的用户消息始终优先；心跳会等待输入队列清空。
- **缓存安全。** 注入的 prompt 是一条普通用户消息。不修改系统 prompt，也不更改工具集。
- **Gateway 恢复。** 启动时会在所属 profile 中，使用当前持久化的对话和线程路由恢复活跃的心跳。每次轮询都会在临时存储故障或适配器停机后重试恢复；已暂停和已清除的心跳以及已挂起的对话不会重新启动。无需新的聊天消息。
- **持久化与对话边界。** 状态存放在 `SessionDB.state_meta` 中，以 `heartbeat:<session_id>` 为键，并跟随上下文压缩引起的会话轮换。在消息 gateway 中，通过重置、切换或挂起离开一个对话会清除其心跳；恢复那个已归档的对话不会让心跳复活。触发要求所属进程（CLI 会话或 gateway）正在运行。一次已被接纳的 gateway 触发会在会话解析之后、agent 执行之前再次检查：它可以跟随一个压缩后的子会话，但不能把旧指令带进一个已重置或已切换的对话。
- **执行计数。** gateway 在适配器接纳时预留一次到期的触发。如果这次具体尝试在进入 agent runner 之前就结束了（包括取消，或路由、授权、紧急停止、准备阶段的拒绝），它会退还该次触发，除非此后日程已被更改。一旦进入 agent runner，即使执行失败或被中断，这次触发仍计入次数。该计数**并不能**证明模型成功响应或已成功对外投递；进程突然死亡可能会阻止退还回调。
- **不凭空找事的防护。** 注入的 prompt 会告诉 agent 在没有任何有意义的变化时简短回复并停止，因此空闲的心跳不会制造无意义的忙碌工作。

## 示例 {#example}

```
You: /heartbeat every 15m Check whether the CI run for PR #1234 finished; summarize the result when it does

  ♥ Heartbeat set (every 15m): Check whether the CI run for PR #1234 finished; ...

[15 minutes of you working on other things in the same session]

Hermes: [Heartbeat — recurring instruction, fires every 15m]
  💻 gh pr checks 1234   (1.2s)
  CI is still running (14/37 checks complete). Nothing to report yet.
```

当答案不再变化时，用 `/heartbeat clear` 清除它——或者让它继续值守。
