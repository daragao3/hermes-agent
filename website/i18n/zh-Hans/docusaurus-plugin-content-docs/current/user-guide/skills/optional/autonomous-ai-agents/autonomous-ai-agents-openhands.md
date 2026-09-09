---
title: "Openhands —— 将编码任务委托给 OpenHands CLI（模型无关，基于 LiteLLM）"
sidebar_label: "Openhands"
description: "将编码任务委托给 OpenHands CLI（模型无关，基于 LiteLLM）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Openhands

将编码任务委托给 OpenHands CLI（模型无关，基于 LiteLLM）。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/autonomous-ai-agents/openhands` 安装 |
| 路径 | `optional-skills/autonomous-ai-agents/openhands` |
| 版本 | `0.1.0` |
| 作者 | Tim Koepsel (xzessmedia), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos |
| 标签 | `Coding-Agent`, `OpenHands`, `Model-Agnostic`, `LiteLLM` |
| 相关 skills | [`claude-code`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code), [`codex`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex), [`opencode`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-opencode), [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# OpenHands CLI

通过 `terminal` 工具将编码任务委托给 [OpenHands CLI](https://github.com/All-Hands-AI/OpenHands)。OpenHands 与模型无关：支持任何 LiteLLM 支持的提供商（OpenAI、Anthropic、OpenRouter、DeepSeek、Ollama、vLLM 等）。

本 skill 是用于批量/单次委托的无头（headless）模式封装。Hermes 不使用其交互式文本界面。

## 使用场景

- 用户明确希望将编码任务委托给 OpenHands。
- 用户希望使用可运行在非 Anthropic / 非 OpenAI 提供商（DeepSeek、Qwen、Ollama、vLLM、Nous 等）上的编码代理 —— 同类 skill `claude-code` 与 `codex` 都绑定单一厂商。
- 在工作区内执行多步文件编辑 + shell 命令。

若需 Claude 原生支持，优先选择 `claude-code`。若需 OpenAI 原生支持，优先选择 `codex`。若需 Hermes 原生子代理，请使用 `delegate_task`。

## 前置条件

1. 安装上游工具（需要 Python 3.12+ 和 `uv`）：

   ```
   terminal(command="uv tool install openhands --python 3.12")
   ```

   验证：`openhands --version`（撰写本文时为 `OpenHands CLI 1.16.0` / `SDK v1.21.0`）。

2. 选择模型并为 `--override-with-envs` 设置环境变量：

   ```
   export LLM_MODEL=openrouter/openai/gpt-4o-mini       # or any LiteLLM slug
   export LLM_API_KEY=$OPENROUTER_API_KEY
   export LLM_BASE_URL=https://openrouter.ai/api/v1     # omit for native OpenAI
   ```

   `LLM_MODEL` 使用 LiteLLM 的完整 slug。当提供商是 OpenRouter 时，slug 带有双重前缀：`openrouter/<vendor>/<model>`（例如 `openrouter/anthropic/claude-sonnet-4.5`）。原生 Anthropic 为：`anthropic/claude-sonnet-4-5`。原生 OpenAI 为：`openai/gpt-4o-mini`。

3. 关闭启动横幅，避免 JSON 输出前混入 ASCII 图案：

   ```
   export OPENHANDS_SUPPRESS_BANNER=1
   ```

## 如何运行

始终通过 `terminal` 工具调用。自动化场景下始终传入 `--headless --json --override-with-envs --exit-without-confirmation`。

### 单次任务

```
terminal(
  command="OPENHANDS_SUPPRESS_BANNER=1 LLM_MODEL=openrouter/openai/gpt-4o-mini LLM_API_KEY=$OPENROUTER_API_KEY LLM_BASE_URL=https://openrouter.ai/api/v1 openhands --headless --json --override-with-envs --exit-without-confirmation -t 'Add error handling to all API calls in src/'",
  workdir="/path/to/project",
  timeout=600
)
```

### 长时任务的后台模式

```
terminal(command="<same as above>", workdir="/path/to/project", background=true, notify_on_complete=true)
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")
```

### 恢复此前的会话

OpenHands 会在每次运行结束时打印 `Conversation ID: <32-hex>` 以及一行 `Hint: openhands --resume <dashed-uuid>`。恢复会话时请使用带连字符的形式：

```
terminal(
  command="OPENHANDS_SUPPRESS_BANNER=1 LLM_MODEL=... openhands --headless --json --override-with-envs --exit-without-confirmation --resume <dashed-uuid> -t 'Now fix the bug you found'",
  workdir="/path/to/project"
)
```

## 真实参数列表

已对照 `openhands --help`（CLI 1.16.0）核实。表中没有的内容都不是命令行参数 —— 请通过环境变量或设置文件传入。

| 参数 | 作用 |
|------|--------|
| `--headless` | 无界面，需要 `-t` 或 `-f`。自动批准所有操作（此模式下没有 `--llm-approve`）。 |
| `--json` | JSONL 事件流（需要 `--headless`）。 |
| `-t TEXT` | 任务提示词。 |
| `-f PATH` | 从文件读取任务。 |
| `--resume [ID]` | 恢复会话。不带 ID 则列出最近的会话。 |
| `--last` | 恢复最近一次会话（与 `--resume` 一起使用）。 |
| `--override-with-envs` | 应用 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 环境变量。不加此参数时，OpenHands 会使用 `~/.openhands/settings.json` 并忽略环境变量。 |
| `--exit-without-confirmation` | 不显示“确定要退出吗”的对话框。 |
| `--always-approve` / `--yolo` | 自动批准每一个操作（`--headless` 下的默认行为）。 |
| `--llm-approve` | 基于 LLM 的安全门禁（仅交互模式可用 —— 在无头模式下无效）。 |
| `--version` / `-v` | 打印版本号并退出。 |

**不存在 `--model`、`--max-iterations`、`--workspace`、`--sandbox`、`--sandbox-type` 参数。** 模型由 `LLM_MODEL` 指定。工作区就是你传给 `terminal` 工具的 `workdir`。沙箱/运行时由 `RUNTIME` 和 `SANDBOX_VOLUMES` 环境变量指定。

## JSON 事件结构

使用 `--json --headless` 时，OpenHands 输出 JSONL —— 每行一个 JSON 对象，另外还有少量非 JSON 的状态行（`Initializing agent...`、`Agent is working`、`Agent finished`、最终的摘要框、`Goodbye!`、`Conversation ID:`、`Hint:`）。请只筛选以 `{` 开头的行。

顶层的 `kind` 字段用于区分事件类型：

- `MessageEvent` —— 用户/代理的文本回合。`source` 为 `user` 或 `agent`。
- `ActionEvent` —— 代理选择了某个工具。读取 `tool_name`（`file_editor`、`terminal`、`finish`）和 `action.kind`（`FileEditorAction`、`TerminalAction`、`FinishAction`）。
- `ObservationEvent` —— 工具执行结果。`observation.is_error` 是成功与否的标志。`source` 为 `environment`。
- `ActionEvent` 内的 `FinishAction` 在 `action.message` 中携带代理的最终消息。

该 CLI 会先打印来自 LiteLLM/Authlib 的所有 stderr 输出 —— 参见“注意事项”。请只逐行解析 stdout，并忽略不以 `{` 开头的行。

## 注意事项

- **每次调用都会出现 LiteLLM 警告。** 由于未安装 `botocore`，CLI 会向 stderr 打印 `bedrock-runtime` 和 `sagemaker-runtime` 警告，另外还有一条 Authlib 弃用警告。这些是噪声，不是失败。请将 stderr 重定向到 `/dev/null` 或在展示给用户前过滤掉。
- **横幅刷屏。** 若不设置 `OPENHANDS_SUPPRESS_BANNER=1`，每次运行都会先输出一个多行的 `+--+` ASCII 方框来宣传 SDK。请始终导出该变量。
- **自动化场景下 `--override-with-envs` 是必需的。** 不加它时，OpenHands 会忽略 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`，转而回退到 `~/.openhands/settings.json`。在全新安装中该文件并不存在，CLI 会挂起等待首次运行的设置流程。
- **模型 slug 用的是 LiteLLM 的写法，而不是提供商的写法。** `openrouter/openai/gpt-4o-mini` 可用；指向 OpenRouter 时使用 `openai/gpt-4o-mini` 则不可用。`anthropic/claude-sonnet-4-5`（连字符）是原生 Anthropic；`openrouter/anthropic/claude-sonnet-4.5`（点号）是通过 OpenRouter。写错就会得到一个含义晦涩的 LiteLLM 400 错误。
- **`pip install openhands-ai` 是错误的包。** 那是旧版 V0 SDK。新版 CLI 用 `uv tool install openhands --python 3.12` 安装。没有受维护的 conda 包。
- **恢复会话的 ID 格式很讲究。** CLI 结尾会输出 `Conversation ID: f46573d9cfdb45e492ca189bde40019b`（无连字符），随后是 `Hint: openhands --resume f46573d9-cfdb-45e4-92ca-189bde40019b`（带连字符）。请使用带连字符的形式。
- **无头模式忽略 `--llm-approve`。** 如果传入该参数会得到 argparse 报错。无头模式硬编码为始终批准。
- **上游不支持 Windows。** OpenHands 文档要求在 Windows 上使用 WSL。因此本 skill 被限定为 `[linux, macos]`。
- **`~/.openhands/conversations/<id>/` 会不断累积。** 每次运行都会持久化一条轨迹。批量运行时请注意清理。
- **安装体积很大（约 200 个包）。** 请使用 `uv tool install`（隔离的虚拟环境）以避免与当前项目产生依赖冲突。

## 验证

```
terminal(
  command="OPENHANDS_SUPPRESS_BANNER=1 LLM_MODEL=openrouter/openai/gpt-4o-mini LLM_API_KEY=$OPENROUTER_API_KEY LLM_BASE_URL=https://openrouter.ai/api/v1 openhands --headless --json --override-with-envs --exit-without-confirmation -t 'Print the string OPENHANDS_OK to stdout via the terminal tool.'",
  workdir="/tmp",
  timeout=120
)
```

如果 JSONL 事件流以一个 `action.message` 中提到 `OPENHANDS_OK` 的 `FinishAction` 结束，说明安装正常。

## 相关链接

- [OpenHands GitHub](https://github.com/All-Hands-AI/OpenHands)
- [OpenHands CLI 命令参考](https://docs.openhands.dev/openhands/usage/cli/command-reference)
- 同类 skill：`claude-code`（仅 Anthropic）、`codex`（仅 OpenAI）、`opencode`（通过 OpenCode 支持多提供商）、`hermes-agent`（通过 `delegate_task` 使用 Hermes 子代理）。
