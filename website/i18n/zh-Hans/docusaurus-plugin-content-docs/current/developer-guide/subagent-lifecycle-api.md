---
title: 公开子 agent 生命周期 API
sidebar_label: 子 agent 生命周期 API
description: "在插件中启动并监管全新的 Hermes 子会话，无需触碰 delegate、gateway 或 TUI 的内部实现"
---

# 公开子 agent 生命周期 API {#public-subagent-lifecycle-api}

插件可以启动并监管全新的 Hermes 子会话，而无需导入
`tools.delegate_tool`、gateway 内部实现、TUI 状态或 `AIAgent` 字段。
该服务会从当前 agent 轮次中解析其父会话，因此可在
CLI、gateway、非交互式以及 kanban-worker 会话中使用。在活跃的
agent 轮次之外启动会以失败关闭（fail closed）的方式报错 `No active Hermes parent session`。

```python
from agent.subagent_lifecycle import SubagentLaunchRequest

def launch_review(ctx):
    # Call from a plugin tool or hook while an agent turn is active.
    service = ctx.subagent_lifecycle
    handle = service.launch(SubagentLaunchRequest(
        goal="Review this change for regressions.",
        context="Only inspect the supplied repository.",
        role="leaf",
        correlation_id="review-42",
        allowed_toolsets=("file",),
    ))
    # Persist handle.to_dict() if desired.
    if service.wait(handle, timeout_seconds=2).timed_out:
        return handle.to_dict()
    return service.result(handle)
```

`SubagentHandle` 可序列化，并携带一个带版本号的不透明能力凭证（capability）。
将它传回 `status`、`wait`、`cancel`、`result` 或 `reconnect` 即可；格式错误
或伪造的 handle 会返回 `UNKNOWN`/`UNKNOWN_HANDLE`，且无法访问任何子会话。

稳定状态包括 `PENDING`、`STARTING`、`RUNNING`、`SUCCEEDED`、`FAILED`、
`INTERRUPTED`、`CANCEL_REQUESTED`、`CANCELLED` 和 `UNKNOWN`。

`cancel(handle, reason=...)` 是协作式的：它请求子 agent 在下一个安全边界处
中断，并返回 `CANCEL_REQUESTED`；在 `wait` 或 `result` 观察到终止状态之前，它绝不会
声称已完成。终止结果不可变、幂等、上限为 32k 字符，不包含对话记录
和隐藏推理，并附带一个稳定的结果哈希。

此 API 是受生命周期管理的异步执行。子会话的构建与
完成走的是与 `delegate_task` 相同的宿主自有路径，包括父会话
工具解析的恢复、记忆通知、串行化的 `subagent_stop`
hook、资源清理以及子会话成本汇总。它不会改变
同步的 `delegate_task` 工具、批量委派，也不会改变其 gateway/TUI 显示。
初始实现会在进程内保留元数据和终止结果
一小时。
进程重启后，`reconnect` 返回 `RECONNECT_UNAVAILABLE`，且绝不会
启动替代的子会话。正在运行的 Python 线程同样无法在进程
退出后存活；调用方必须将这些 handle 视为已因进程退出而中断。

请求采用失败关闭策略：goal/context/metadata 的大小有上限，未知的或
会扩大父会话权限的 toolset 会被拒绝，而按工具的屏蔽、工作目录
覆盖以及按次启动的超时设置在 Hermes 能够在不削弱隔离的前提下
支持它们之前，都会被明确拒绝。使用 `allowed_toolsets` 来收窄
子会话的范围；Hermes 现有的不安全工具屏蔽依然生效。
