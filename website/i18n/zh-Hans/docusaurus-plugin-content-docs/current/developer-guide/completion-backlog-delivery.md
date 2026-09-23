---
title: 后台完成积压
sidebar_label: 完成积压
description: "交互式界面如何将已就绪的后台进程完成事件合并为单个通知轮次"
---

# 后台完成积压

对于同一个会话中已经就绪的连续后台进程完成事件，交互式界面会将它们合并为单个通知轮次。
这不会引入任何延迟，也不承诺合并在不同时间完成的任务。失败与成功的输出都保留在批次中；
只有一个完成事件时保持其原始文本。

进程标识在分派之前始终可用。因此，显式的 `process_manage`
wait/log/kill 消费即使在某个 CLI 完成事件已经离开进程注册表并进入输入队列之后，
仍然可以将其抑制。一个被完全消费的批次不会启动任何轮次。输出监视（watch）结果与异步委派结果
仍然是独立的通知，并保持原有顺序；它们不会被并入完成批次。

## 消费方与归属 {#consumers-and-ownership}

- **经典 CLI：** `hermes_cli/cli_process_notifications.py` 负责空闲/轮次后的排空、
  感知压缩的归属判定以及最终的输入解包。
- **TUI 与桌面端：** `tui_gateway/session_notifications.py` 在检查归属之后，对轮询器的
  就绪快照进行分组。每个进程仍会发出各自的 UI 状态。忙碌中的会话会将结构化事件重新入队，
  而不是已渲染的批次字符串。
- **TUI 轮次后安全网：** `tui_gateway/prompt_turn.py` 使用同一套路由与渲染路径。
  桌面端和仪表盘聊天客户端共享这一后端。
- **消息网关：** `gateway/run_notifications.py` 已经使用自己的按路由键划分的短窗口批处理。
  此次交互式积压改动不会替换该机制，也不会改变适配器的发送行为。
- **非交互/无头消费方：** 此改动不会为 API 请求、ACP 客户端或一次性 CLI
  创建新的自主通知循环。

共享渲染器为 `tools/process_registry_notifications.py::ProcessNotificationBatch`。
批次及其投递状态都不会被持久化到系统提示词中。
已指定地址的事件仍然需要一个可证明的归属方；其他活跃会话不能接管它们。
委派投递继续通过其现有的持久化 claim/complete 账本进行，
每个委派一次，而不是每个进程批次一次。

## 本地验证及其局限 {#local-validation-and-its-limits}

`evals/completion_backlog_probe.py REPO OUTPUT.json` 会在临时目录中启动真实的本地 shell 子进程，
读取它们真实的完成事件，并驱动生产环境的 CLI、TUI 轮询器以及轮次后通知路由。
一个回环 HTTP 轮次接收端替代了 `chat` / `_run_prompt_submit`；它会记录实际的分派，但**不会**
覆盖模型推理、原生渲染器交互或托管平台。
合成的 watch 与委派信封是带标签的测试夹具；委派 claim
使用真实的临时 SQLite 账本。积压用例包含一个非零退出码。

该探针检查以下场景：就绪积压、单个精确载荷、被显式消费的结果、
外部归属，以及与完成事件交错出现的 watch/委派。
它衡量的是通知边界处的轮次准入，而不是模型 token 的节省。
