---
title: "代码库归属图"
description: "各目录分别属于哪个子系统，以及每个子系统对应的正确文档入口在哪里"
---

# 代码库归属图

Hermes 是一个大型仓库，而大多数贡献只涉及其中恰好一个子系统。本页将每个子系统映射到它的源码目录，以及你在修改它之前应当阅读的文档入口。用它来找到正确的起始文档、改动的正确位置，以及正确的测试目录（测试与源码镜像对应：`tools/` 中的代码在 `tests/tools/` 中测试，插件在 `tests/plugins/<type>/` 中测试，依此类推）。

| 子系统 | 源码目录 | 文档入口 |
|-----------|-------------------|------------------|
| Agent 核心（循环、传输、压缩） | `agent/`, `run_agent.py` | [Agent 循环](agent-loop.md)、[上下文压缩与缓存](context-compression-and-caching.md) |
| Prompt 组装 | `agent/prompt_builder.py`, `agent/system_prompt.py` | [Prompt 组装](prompt-assembly.md) |
| 模型提供商与传输 | `agent/transports/`, `plugins/model-providers/`, `hermes_cli/models.py` | [添加提供商](adding-providers.md)、[模型提供商插件](model-provider-plugin.md)、[提供商运行时](provider-runtime.md) |
| 内置工具 | `tools/` | [添加工具](adding-tools.md)、[工具运行时](tools-runtime.md) |
| 消息网关 | `gateway/`, `plugins/platforms/` | [网关内部机制](gateway-internals.md)、[添加平台适配器](adding-platform-adapters.md) |
| CLI | `hermes_cli/` | [扩展 CLI](extending-the-cli.md) |
| 插件系统 | `plugins/` | [构建 Hermes 插件](plugins/index.md) |
| Skills（内置与可选） | `skills/`, `optional-skills/` | [创建 Skills](creating-skills.md) |
| Cron / 定时任务 | `cron/` | [Cron 内部机制](cron-internals.md) |
| 会话存储 | `hermes_state.py`, `hermes_state_*.py` | [会话存储](session-storage.md) |
| 浏览器栈 | `tools/browser_tool.py`, `tools/browser_supervisor.py`, `tools/browser_cdp_tool.py` | [浏览器监管器](browser-supervisor.md) |
| 出口防火墙 | `agent/proxy_sources/iron_proxy.py` | [出口内部机制](egress-internals.md) |
| ACP（IDE 集成） | `acp_adapter/` | [ACP 内部机制](acp-internals.md) |
| 桌面应用 | `apps/desktop/` | [桌面插件 SDK](desktop-plugin-sdk.md)、[Worktree UI 开发](worktree-ui-dev.md) |
| TUI | `ui-tui/`, `tui_gateway/` | [Worktree UI 开发](worktree-ui-dev.md) |
| 文档站点 | `website/` | [贡献指南](contributing.md) |
| 测试 | `tests/`, `tests-js/` | [贡献指南 → 提交之前](contributing.md#before-submitting) |

从这张图中可以得出几条约定：

- **改动应当留在其所属的子系统内。** 一个需要编辑核心文件的插件是一种设计异味——应当转而拓宽通用的插件接口（参见仓库 `AGENTS.md` 中的贡献评审准则）。
- **你触及的每个源码目录，都要运行其镜像测试目录。** 对 `plugins/platforms/telegram/` 的改动需要 `tests/plugins/platforms/` 全部通过，而不仅仅是你碰巧想到的那个测试文件。
- **当涉及两个子系统时，由范围更窄的那个负责这次改动。** 优先在适配器或插件中修复，而不是在 agent 核心里加分支；核心是一个窄腰，在那里的每一处新增都要在每次 API 调用时付出代价。
