---
title: 上下文压缩与缓存
description: Hermes Agent 如何通过双重压缩系统和 Anthropic prompt 缓存高效管理上下文窗口。
---

# 上下文压缩与缓存

Hermes Agent 使用双重压缩系统和 Anthropic prompt（提示词）缓存，在长对话中高效管理上下文窗口用量。

源文件：`agent/context_engine.py`（ABC）、`agent/context_compressor.py`（默认引擎）、
`agent/prompt_caching.py`、`gateway/run.py`（会话清理）、`run_agent.py`（搜索 `_compress_context`）


## 可插拔上下文引擎

上下文管理基于 `ContextEngine` ABC（`agent/context_engine.py`）构建。内置的 `ContextCompressor` 是默认实现，但插件可以用其他引擎替换它（例如无损上下文管理）。

```yaml
context:
  engine: "compressor"    # default — built-in lossy summarization
  engine: "lcm"           # example — plugin providing lossless context
```

引擎负责：
- 决定何时触发压缩（`should_compress()`）
- 执行压缩（`compress()`）
- 可选地暴露 agent 可调用的工具（例如 `lcm_grep`）
- 追踪 API 响应中的 token 用量

通过 `config.yaml` 中的 `context.engine` 进行配置驱动选择。解析顺序：
1. 检查 `plugins/context_engine/<name>/` 目录
2. 检查通用插件系统（`register_context_engine()`）
3. 回退到内置 `ContextCompressor`

插件引擎**永远不会自动激活**——用户必须在 `context.engine` 中显式设置插件名称。默认的 `"compressor"` 始终使用内置实现。

通过 `hermes plugins` → Provider Plugins → Context Engine 进行配置，或直接编辑 `config.yaml`。

关于构建上下文引擎插件，请参阅 [Context Engine 插件](/developer-guide/context-engine-plugin)。

## 双重压缩系统

Hermes 有两个独立运行的压缩层：

```
                     ┌──────────────────────────┐
  Incoming message   │   Gateway Session Hygiene │  Fires at 85% of context
  ─────────────────► │   (pre-agent, rough est.) │  Safety net for large sessions
                     └─────────────┬────────────┘
                                   │
                                   ▼
                     ┌──────────────────────────┐
                     │   Agent ContextCompressor │  Fires at 50% of context (default)
                     │   (in-loop, real tokens)  │  Normal context management
                     └──────────────────────────┘
```

### 1. Gateway 会话清理（85% 阈值）

位于 `gateway/run.py`（搜索 `Session hygiene: auto-compress`）。这是一个**安全网**，在 agent 处理消息之前运行。它防止会话在两次交互之间增长过大时（例如 Telegram/Discord 中的隔夜积累）导致 API 失败。

- **阈值**：固定为模型上下文长度的 85%
- **Token 来源**：优先使用上一轮 API 实际报告的 token 数；回退到基于字符的粗略估算（`estimate_messages_tokens_rough`）
- **触发条件**：仅当 `len(history) >= 4` 且压缩已启用时
- **目的**：捕获逃过 agent 自身压缩器的会话

Gateway 清理阈值有意高于 agent 压缩器的阈值。将其设置为 50%（与 agent 相同）会导致长 gateway 会话在每一轮都过早触发压缩。

### 2. Agent ContextCompressor（50% 阈值，可配置）

位于 `agent/context_compressor.py`。这是**主要压缩系统**，在 agent 的工具循环内运行，可访问准确的 API 报告 token 数。


## 配置

所有压缩设置从 `config.yaml` 的 `compression` 键读取：

```yaml
compression:
  enabled: true              # Enable/disable compression (default: true)
  threshold: 0.50            # Fraction of context window (default: 0.50 = 50%)
  target_ratio: 0.20         # How much of threshold to keep as tail (default: 0.20)
  protect_last_n: 20         # Minimum protected tail messages (default: 20)
  codex_gpt55_autoraise: true  # gpt-5.5 on Codex OAuth: raise trigger to 85% (default: true)
  codex_gpt55_autoraise_notice: true  # Show the one-time autoraise notice (default: true)
  codex_app_server_auto: native  # native|hermes|off for Codex app-server thread compaction

# Summarization model/provider configured under auxiliary:
auxiliary:
  compression:
    model: null              # Override model for summaries (default: auto-detect)
    provider: auto           # Provider: "auto", "openrouter", "nous", "main", etc.
    base_url: null           # Custom OpenAI-compatible endpoint
```

### 参数详情

| 参数 | 默认值 | 范围 | 描述 |
|-----------|---------|-------|-------------|
| `threshold` | `0.50` | 0.0-1.0 | 当 prompt token 数 ≥ `threshold × context_length` 时触发压缩 |
| `target_ratio` | `0.20` | 0.10-0.80 | 控制尾部保护 token 预算：`threshold_tokens × target_ratio` |
| `protect_last_n` | `20` | ≥1 | 始终保留的最近消息最小数量 |
| `protect_first_n` | `3` | （硬编码）| 系统提示词 + 首次交互始终保留 |
| `codex_gpt55_autoraise` | `true` | bool | 在 ChatGPT Codex OAuth 路由上为 gpt-5.5 将触发阈值提升到 85%（见下文）。设为 `false` 可保持全局 `threshold` |
| `codex_gpt55_autoraise_notice` | `true` | bool | 显示一次性的 Codex gpt-5.5 自动提升提示。设为 `false` 可保留 85% 自动提升但隐藏该横幅 |
| `codex_app_server_auto` | `native` | `native`、`hermes`、`off` | Codex app-server 会话的线程压缩模式（见下文） |

### Codex gpt-5.5 阈值自动提升

ChatGPT Codex OAuth 后端将 gpt-5.5 的上下文窗口硬性限制为 **272K**（同一 slug 在 OpenAI 直连 API 和 OpenRouter 上暴露为 1.05M，在 GitHub Copilot 上为 400K）。在默认的 50% 触发阈值下，压缩会在约 136K 时触发——只有模型实际可用窗口的一半。当活跃路由是 Codex OAuth（`provider: openai-codex`）且模型为 gpt-5.5 时，Hermes 会将触发阈值提升到 **85%**（约 231K），并显示一条带有退出命令的提示。该提示每个 profile 只显示一次——`$HERMES_HOME` 下的一个标记文件（`.codex_gpt55_autoraise_notice`）记录它已经运行过，因此重复的 agent/会话初始化（例如每条入站网关消息）不会重复发出；如果提升后的阈值之后发生变化，则会再次提示一次。只有这一条精确路由会受影响；在任何其他提供商上的 gpt-5.5 仍使用你的全局 `threshold`。若要退回到全局值：

```bash
hermes config set compression.codex_gpt55_autoraise false
```

若要保留 85% 自动提升但仅隐藏这条一次性提示：

```bash
hermes config set compression.codex_gpt55_autoraise_notice false
```

### Codex app-server 线程压缩

Codex app-server 会话（`api_mode: codex_app_server`——即 codex CLI/agent 运行时）与其他所有路由都不同：codex agent 拥有背后的线程上下文，因此 Hermes 的辅助摘要器无法压缩它——重写本地转录镜像只会让真实线程无限增长，直到发生一次硬性上下文重置。对于该运行时，压缩改为走 app-server 自身的机制：

- 手动压缩（`/compress`）会请求 app-server 压缩线程（`thread/compact/start`）并等待压缩轮次完成。
- 自动压缩由 `compression.codex_app_server_auto` 控制：默认值 `native` 让 app-server 自行决定何时压缩，Hermes 只记录由此产生的压缩事件（压缩计数器、会话事件）。设为 `hermes` 可让 Hermes 的压缩阈值发起 app-server 压缩，设为 `off` 则完全禁用由 Hermes 发起的自动压缩（codex 仍可能原生压缩）。

在该运行时上，Hermes 的本地转录永远不会被重写——state.db 记录压缩边界，而可见的转录保持完整。所有其他路由（包括 Codex OAuth 聊天会话）仍使用 Hermes 的摘要压缩器。

### 计算值（200K 上下文模型，默认参数）

```
context_length       = 200,000
threshold_tokens     = 200,000 × 0.50 = 100,000
tail_token_budget    = 100,000 × 0.20 = 20,000
max_summary_tokens   = min(200,000 × 0.05, 12,000) = 10,000
```

:::note 阈值由**主**模型的上下文窗口推导得出
`threshold_tokens` 始终等于 `threshold × context_length`，其中 `context_length` 是**主 agent 模型的**上下文窗口——绝不是辅助/摘要模型的。对于一个 262,144 token 的模型，在默认 `0.50` 下，阈值为 `262,144 × 0.50 = 131,072`。这个数字接近常见的「128K 上下文」只是百分比造成的巧合，并不意味着辅助模型的窗口是触发条件。辅助模型的上下文窗口是另一个独立问题——参见下文「摘要模型上下文长度」警告，它影响的是能否生成摘要，而不是压缩何时触发。
:::


## 压缩算法

`ContextCompressor.compress()` 方法遵循 4 阶段算法：

### 阶段 1：清除旧工具结果（廉价，无需 LLM 调用）

保护尾部之外的旧工具结果（>200 字符）将被替换为：
```
[Old tool output cleared to save context space]
```

这是一个廉价的预处理步骤，可从冗长的工具输出（文件内容、终端输出、搜索结果）中节省大量 token。

### 阶段 2：确定边界

```
┌─────────────────────────────────────────────────────────────┐
│  Message list                                               │
│                                                             │
│  [0..2]  ← protect_first_n (system + first exchange)        │
│  [3..N]  ← middle turns → SUMMARIZED                        │
│  [N..end] ← tail (by token budget OR protect_last_n)        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

尾部保护基于 **token 预算**：从末尾向前遍历，累积 token 直到预算耗尽。如果预算保护的消息数少于固定的 `protect_last_n`，则回退到该固定数量。

边界对齐以避免拆分 tool_call/tool_result 组。`_align_boundary_backward()` 方法会跳过连续的工具结果，找到父级 assistant 消息，保持组的完整性。

### 阶段 3：生成结构化摘要

:::warning 摘要模型上下文长度
摘要模型的上下文窗口必须**至少与主 agent 模型一样大**。整个中间部分通过单次 `call_llm(task="compression")` 调用发送给摘要模型。如果摘要模型的上下文更小，API 将返回上下文长度错误——`_generate_summary()` 会捕获该错误，记录警告并返回 `None`。压缩器随后会**在没有摘要的情况下丢弃中间轮次**，静默丢失对话上下文。这是压缩质量下降最常见的原因。
:::

中间轮次使用辅助 LLM 以结构化模板进行摘要：

```
## Goal
[What the user is trying to accomplish]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions]

## Progress
### Done
[Completed work — specific file paths, commands run, results]
### In Progress
[Work currently underway]
### Blocked
[Any blockers or issues encountered]

## Key Decisions
[Important technical decisions and why]

## Relevant Files
[Files read, modified, or created — with brief note on each]

## Next Steps
[What needs to happen next]

## Critical Context
[Specific values, error messages, configuration details]
```

摘要预算随被压缩内容的量动态调整：
- 公式：`content_tokens × 0.20`（`_SUMMARY_RATIO` 常量）
- 最小值：2,000 token
- 最大值：`min(context_length × 0.05, 12,000)` token

### 阶段 4：组装压缩后的消息

压缩后的消息列表为：
1. 头部消息（首次压缩时在系统提示词后追加一条说明）
2. 摘要消息（角色经过选择以避免连续相同角色违规）
3. 尾部消息（未修改）

`_sanitize_tool_pairs()` 清理孤立的 tool_call/tool_result 对：
- 引用已删除调用的工具结果 → 删除
- 结果已被删除的工具调用 → 注入存根结果

### 迭代重压缩

在后续压缩中，前一次摘要会连同指令一起传递给 LLM，要求其**更新**摘要而非从头摘要。这在多次压缩中保留了信息——条目从"进行中"移至"已完成"，新进展被添加，过时信息被删除。

压缩器实例上的 `_previous_summary` 字段存储最后一次摘要文本以供此用途。


## 压缩前后示例

### 压缩前（45 条消息，约 95K token）

```
[0] system:    "You are a helpful assistant..." (system prompt)
[1] user:      "Help me set up a FastAPI project"
[2] assistant: <tool_call> terminal: mkdir project </tool_call>
[3] tool:      "directory created"
[4] assistant: <tool_call> write_file: main.py </tool_call>
[5] tool:      "file written (2.3KB)"
    ... 30 more turns of file editing, testing, debugging ...
[38] assistant: <tool_call> terminal: pytest </tool_call>
[39] tool:      "8 passed, 2 failed\n..."  (5KB output)
[40] user:      "Fix the failing tests"
[41] assistant: <tool_call> read_file: tests/test_api.py </tool_call>
[42] tool:      "import pytest\n..."  (3KB)
[43] assistant: "I see the issue with the test fixtures..."
[44] user:      "Great, also add error handling"
```

### 压缩后（25 条消息，约 45K token）

```
[0] system:    "You are a helpful assistant...
               [Note: Some earlier conversation turns have been compacted...]"
[1] user:      "Help me set up a FastAPI project"
[2] assistant: "[CONTEXT COMPACTION] Earlier turns were compacted...

               ## Goal
               Set up a FastAPI project with tests and error handling

               ## Progress
               ### Done
               - Created project structure: main.py, tests/, requirements.txt
               - Implemented 5 API endpoints in main.py
               - Wrote 10 test cases in tests/test_api.py
               - 8/10 tests passing

               ### In Progress
               - Fixing 2 failing tests (test_create_user, test_delete_user)

               ## Relevant Files
               - main.py — FastAPI app with 5 endpoints
               - tests/test_api.py — 10 test cases
               - requirements.txt — fastapi, pytest, httpx

               ## Next Steps
               - Fix failing test fixtures
               - Add error handling"
[3] user:      "Fix the failing tests"
[4] assistant: <tool_call> read_file: tests/test_api.py </tool_call>
[5] tool:      "import pytest\n..."
[6] assistant: "I see the issue with the test fixtures..."
[7] user:      "Great, also add error handling"
```


## Prompt 缓存（Anthropic）

来源：`agent/prompt_caching.py`

通过缓存对话前缀，在多轮对话中将输入 token 成本降低约 75%。使用 Anthropic 的 `cache_control` 断点。

### 策略：system_and_3

Anthropic 每次请求最多允许 4 个 `cache_control` 断点。Hermes 使用"system_and_3"策略：

```
Breakpoint 1: System prompt           (stable across all turns)
Breakpoint 2: 3rd-to-last non-system message  ─┐
Breakpoint 3: 2nd-to-last non-system message   ├─ Rolling window
Breakpoint 4: Last non-system message          ─┘
```

### 工作原理

`apply_anthropic_cache_control()` 深拷贝消息并注入 `cache_control` 标记：

```python
# Cache marker format
marker = {"type": "ephemeral"}
# Or for 1-hour TTL:
marker = {"type": "ephemeral", "ttl": "1h"}
```

标记根据内容类型以不同方式应用：

| 内容类型 | 标记位置 |
|-------------|-------------------|
| 字符串内容 | 转换为 `[{"type": "text", "text": ..., "cache_control": ...}]` |
| 列表内容 | 添加到最后一个元素的字典中 |
| None/空 | 作为 `msg["cache_control"]` 添加 |
| 工具消息 | 作为 `msg["cache_control"]` 添加（仅限原生 Anthropic） |

### 缓存感知设计模式

1. **稳定的系统提示词**：系统提示词是断点 1，在所有轮次中缓存。避免在对话中途修改它（压缩仅在首次压缩时追加一条说明）。

2. **消息顺序很重要**：缓存命中需要前缀匹配。在中间添加或删除消息会使其后所有内容的缓存失效。

3. **压缩与缓存的交互**：压缩后，被压缩区域的缓存失效，但系统提示词缓存保留。滚动 3 消息窗口在 1-2 轮内重新建立缓存。

4. **TTL 选择**：默认为 `5m`（5 分钟）。对于用户在轮次之间有较长间隔的长时间会话，使用 `1h`。

5. **模型身份是缓存键的一部分**：提供商侧的缓存作用域限定在服务该请求的模型（以及账号/API key）上。任何在对话中途更换模型的行为——显式的 `/model` 切换、主模型回退，或凭据池轮换到另一个账号——都意味着下一次请求的缓存命中率为零，并会以未打折的输入价格重新读取整段对话。这是提供商缓存的固有机制，不是 Hermes 能够规避的；正因如此，`/model`、回退提供商和凭据池的面向用户文档都带有成本警告。不要添加会在会话中途静默切换模型或凭据的功能。

### 启用 Prompt 缓存

满足以下条件时，prompt 缓存自动启用：
- 模型为 Anthropic Claude 模型（通过模型名称检测）
- 提供商支持 `cache_control`（原生 Anthropic API 或 OpenRouter）

```yaml
# config.yaml — TTL is configurable (must be "5m" or "1h")
prompt_caching:
  cache_ttl: "5m"
```

CLI 在启动时显示缓存状态：
```
💾 Prompt caching: ENABLED (Claude via OpenRouter, 5m TTL)
```


## 上下文压力警告

中间上下文压力警告已被移除（参见 `run_agent.py` 中的迭代预算块，其中注明："No intermediate pressure warnings — they caused models to 'give up' prematurely on complex tasks"）。压缩在 prompt token 达到配置的 `compression.threshold`（默认 50%）时触发，无需事先警告步骤；gateway 会话清理作为二级安全网在模型上下文窗口的 85% 处触发。