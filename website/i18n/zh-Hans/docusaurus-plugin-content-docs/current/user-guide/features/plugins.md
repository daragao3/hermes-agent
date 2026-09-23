---
sidebar_position: 11
title: "插件"
sidebar_label: "插件"
description: "通过插件系统为 Hermes 扩展自定义工具、hook 和集成"
---

# 插件 {#plugins}

Hermes 提供了一套插件系统，可在不修改核心代码的情况下添加自定义工具、hook（钩子）和集成。

如果你想为自己、团队或某个项目创建自定义工具，这通常是正确的路径。开发者指南中的
[Adding Tools](/developer-guide/adding-tools) 页面针对的是存放在 `tools/` 和 `toolsets.py` 中的 Hermes 内置核心工具。

**→ [构建 Hermes Plugin](/developer-guide/plugins)** —— 包含完整可运行示例的分步指南。

## 快速概览 {#quick-overview}

在 `~/.hermes/plugins/` 下放入一个目录，包含 `plugin.yaml` 和 Python 代码：

```
~/.hermes/plugins/my-plugin/
├── plugin.yaml      # manifest（清单）
├── __init__.py      # register() — 将 schema 与处理器绑定
├── schemas.py       # tool schema（LLM 所见的内容）
└── tools.py         # tool 处理器（调用时实际执行的代码）
```

启动 Hermes —— 你的工具会与内置工具一同出现，模型可立即调用它们。

### 最小可运行示例 {#minimal-working-example}

以下是一个完整插件，添加了一个 `hello_world` 工具，并通过 hook 记录每次工具调用。

**`~/.hermes/plugins/hello-world/plugin.yaml`**

```yaml
name: hello-world
version: "1.0"
description: A minimal example plugin
```

**`~/.hermes/plugins/hello-world/__init__.py`**

```python
"""Minimal Hermes plugin — registers a tool and a hook."""

import json


def register(ctx):
    # --- Tool: hello_world ---
    schema = {
        "name": "hello_world",
        "description": "Returns a friendly greeting for the given name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to greet",
                }
            },
            "required": ["name"],
        },
    }

    def handle_hello(params, **kwargs):
        del kwargs
        name = params.get("name", "World")
        return json.dumps({"success": True, "greeting": f"Hello, {name}!"})

    ctx.register_tool(
        name="hello_world",
        toolset="hello_world",
        schema=schema,
        handler=handle_hello,
    )

    # --- Hook: log every tool call ---
    def on_tool_call(tool_name, params, result):
        print(f"[hello-world] tool called: {tool_name}")

    ctx.register_hook("post_tool_call", on_tool_call)
```

将两个文件放入 `~/.hermes/plugins/hello-world/`，重启 Hermes，模型即可立即调用 `hello_world`。每次工具调用后，hook 会打印一行日志。

面向模型的工具描述应写在 `schema["description"]` 中。可选的 `ctx.register_tool(description=...)` 值是独立的 `ToolEntry` 注册表元数据：省略时，它会默认使用 schema 中的描述；但如果 schema 缺少 `description`，Hermes 不会把该元数据反向复制到 schema。建议只在 schema 中定义一次描述。如果同时提供两个值，请保持同步；模型看到的是 schema 中的值。

`./.hermes/plugins/` 下的项目本地插件默认禁用。仅对可信仓库启用，方法是在启动 Hermes 前设置 `HERMES_ENABLE_PROJECT_PLUGINS=true`。

## 插件能做什么 {#what-plugins-can-do}

以下所有 `ctx.*` API 均可在插件的 `register(ctx)` 函数中使用。

| 能力 | 方式 |
|-----------|-----|
| 添加工具 | `ctx.register_tool(name=..., toolset=..., schema=..., handler=...)` |
| 添加 hook | `ctx.register_hook("post_tool_call", callback)` |
| 添加斜杠命令 | `ctx.register_command(name, handler, description)` —— 在 CLI 和 gateway 会话中添加 `/name` |
| 从命令中调度工具 | `ctx.dispatch_tool(name, args)` —— 调用已注册的工具，自动注入父 agent 上下文 |
| 添加 CLI 命令 | `ctx.register_cli_command(name, help, setup_fn, handler_fn)` —— 添加 `hermes <plugin> <subcommand>` |
| 注入消息 | `ctx.inject_message(content, role="user", session_key=...)` —— 参见 [注入消息](#injecting-messages) |
| 附带数据文件 | `Path(__file__).parent / "data" / "file.yaml"` |
| 打包 skill | `ctx.register_skill(name, path)` —— 命名空间为 `plugin:skill`，通过 `skill_view("plugin:skill")` 加载 |
| 按环境变量控制 | 在 plugin.yaml 中设置 `requires_env: [API_KEY]` —— 在 `hermes plugins install` 时提示输入 |
| 通过 pip 分发 | `[project.entry-points."hermes_agent.plugins"]` |
| 注册 gateway 平台（Discord、Telegram、IRC 等） | `ctx.register_platform(name, label, adapter_factory, check_fn, ...)` —— 参见 [Adding Platform Adapters](/developer-guide/adding-platform-adapters) |
| 注册图像生成后端 | `ctx.register_image_gen_provider(provider)` —— 参见 [Image Generation Provider Plugins](/developer-guide/image-gen-provider-plugin) |
| 注册视频生成后端 | `ctx.register_video_gen_provider(provider)` —— 参见 [Video Generation Provider Plugins](/developer-guide/video-gen-provider-plugin) |
| 注册上下文压缩引擎 | `ctx.register_context_engine(engine)` —— 参见 [Context Engine Plugins](/developer-guide/context-engine-plugin) |
| 注册终端执行后端（云沙箱） | `ctx.register_terminal_environment_provider(provider)` —— 参见 [Terminal Environment Plugins](/developer-guide/terminal-environment-plugin) |
| 路由人工审批提示 | `ctx.register_approval_transport(name, present_fn)` —— 参见 [审批传输](#approval-transports) |
| 注册 memory 后端 | 在 `plugins/memory/<name>/__init__.py` 中继承 `MemoryProvider` —— 参见 [Memory Provider Plugins](/developer-guide/memory-provider-plugin)（使用独立发现系统） |
| 执行宿主托管的 LLM 调用 | `ctx.llm.complete(...)` / `ctx.llm.complete_structured(...)` —— 借用用户当前激活的模型和认证，进行一次性补全，支持可选 JSON schema 验证。参见 [Plugin LLM Access](/developer-guide/plugin-llm-access) |
| 调用 MCP 工具（受能力授权控制） | `ctx.call_mcp(server, tool, arguments, timeout=30)` —— 参见 [从插件调用 MCP 服务器](#calling-mcp-servers-from-plugins) |
| 注册推理后端（LLM provider） | 在 `plugins/model-providers/<name>/__init__.py` 中调用 `register_provider(ProviderProfile(...))` —— 参见 [Model Provider Plugins](/developer-guide/model-provider-plugin)（使用独立发现系统） |

## 插件发现 {#plugin-discovery}

| 来源 | 路径 | 使用场景 |
|--------|------|----------|
| 内置 | `<repo>/plugins/` | 随 Hermes 附带 —— 参见 [Built-in Plugins](/user-guide/features/built-in-plugins) |
| 用户 | `~/.hermes/plugins/` | 个人插件 |
| 项目 | `.hermes/plugins/` | 项目专属插件（需要 `HERMES_ENABLE_PROJECT_PLUGINS=true`） |
| pip | `hermes_agent.plugins` entry_points | 分发包 |
| Nix | `services.hermes-agent.extraPlugins` / `extraPythonPackages` | NixOS 声明式安装 —— 参见 [Nix Setup](/getting-started/nix-setup#plugins) |

名称冲突时，后面的来源会覆盖前面的，因此与内置插件同名的用户插件会替换它。

### 插件子分类 {#plugin-sub-categories}

在每个来源内，Hermes 还识别将插件路由到专用发现系统的子分类目录：

| 子目录 | 内容 | 发现系统 |
|---|---|---|
| `plugins/`（根目录） | 通用插件 —— 工具、hook、斜杠命令、CLI 命令、打包 skill | `PluginManager`（kind: `standalone` 或 `backend`） |
| `plugins/platforms/<name>/` | Gateway 频道适配器（`ctx.register_platform()`） | `PluginManager`（kind: `platform`，深一层） |
| `plugins/image_gen/<name>/` | 图像生成后端（`ctx.register_image_gen_provider()`） | `PluginManager`（kind: `backend`，深一层） |
| `plugins/memory/<name>/` | Memory provider（继承 `MemoryProvider`） | **独立加载器**，位于 `plugins/memory/__init__.py`（kind: `exclusive` —— 同时只有一个激活） |
| `plugins/context_engine/<name>/` | 上下文压缩引擎（`ctx.register_context_engine()`） | **独立加载器**，位于 `plugins/context_engine/__init__.py`（同时只有一个激活） |
| `plugins/model-providers/<name>/` | LLM provider profile（`register_provider(ProviderProfile(...))`） | **独立加载器**，位于 `providers/__init__.py`（首次调用 `get_provider_profile()` 时懒加载扫描） |

`~/.hermes/plugins/model-providers/<name>/` 下的用户插件会覆盖同名内置 model provider（`register_provider()` 中后写者胜出），因此无需修改仓库即可替换内置 provider profile。Memory provider 的解析方向正好相反：对于 `~/.hermes/plugins/memory/<name>/`，名称冲突时**内置** provider 胜出（依次为内置、用户、项目、entry points；先出现者胜出），因此用户 memory provider 需要使用独有的名称。

## 插件默认关闭（少数例外） {#plugins-are-opt-in-with-a-few-exceptions}

**通用插件和用户安装的后端默认禁用** —— 发现系统会找到它们（因此它们会出现在 `hermes plugins` 和 `/plugins` 中），但在你将插件名称添加到 `~/.hermes/config.yaml` 的 `plugins.enabled` 之前，任何带有 hook 或工具的内容都不会加载。这可防止第三方代码在未经明确同意的情况下运行。

```yaml
plugins:
  enabled:
    - my-tool-plugin
    - disk-cleanup
  disabled:       # 可选的拒绝列表 — 若名称同时出现在两个列表中，此列表始终优先
    - noisy-plugin
  # 可选：进程内 Python 插件 hook 回调（热路径观察者 + pre_tool_call）的
  # 墙钟时间上限（秒）。默认 30；设为 0 表示禁用；超过 600 的值会被截断。
  # 超时的 pre_tool_call 回调按失败关闭处理（阻止该工具）。subagent_stop 等
  # 在调用方线程运行的 hook 永远不会被移到超时工作线程上。
  # Shell hook 在顶层 hooks: 键下保留各自条目的超时设置。
  hook_callback_timeout: 30
```

切换状态的三种方式：

```bash
hermes plugins                    # 交互式切换（空格勾选/取消勾选）
hermes plugins enable <name>      # 添加到允许列表
hermes plugins disable <name>     # 从允许列表移除并添加到禁用列表
```

执行 `hermes plugins install owner/repo` 后，会询问 `Enable 'name' now? [y/N]` —— 默认为否。脚本化安装时可用 `--enable` 或 `--no-enable` 跳过提示。

如需可复现的安装，请固定到一个完整且不可变的 commit（不接受 tag、分支和缩写 SHA）：

```bash
hermes plugins install owner/repo --ref 0123456789abcdef0123456789abcdef01234567
```

Hermes 以 detached 方式检出该 commit，校验 `HEAD` 与所请求的 SHA 完全一致，并在当前 profile 中记录规范来源、已安装的修订版本和固定状态。`hermes plugins update` 拒绝移动已固定的插件；请用
`hermes plugins install <source> --force --ref <new-commit>` 显式选择新的确切 commit。profile 本地的安装元数据不包含任何配置值、环境变量值、密钥或能力授权。

### 允许列表不控制的内容 {#what-the-allow-list-does-not-gate}

某些类别的插件绕过 `plugins.enabled` —— 它们是 Hermes 内置功能的一部分，若默认关闭会破坏基本功能：

| 插件类型 | 激活方式 |
|---|---|
| **内置平台插件**（IRC、Teams 等，位于 `plugins/platforms/`） | 自动加载，使所有内置 gateway 频道可用。实际频道通过 `config.yaml` 中的 `gateway.platforms.<name>.enabled` 开启。 |
| **内置后端**（`plugins/image_gen/` 等下的图像生成 provider） | 自动加载，使默认后端"开箱即用"。通过 `config.yaml` 中的 `<category>.provider` 选择（例如 `image_gen.provider: openai`）。 |
| **Memory provider**（`plugins/memory/`） | 全部发现；同时只有一个激活，由 `config.yaml` 中的 `memory.provider` 选择。 |
| **Context engine**（`plugins/context_engine/`） | 全部发现；同时只有一个激活，由 `config.yaml` 中的 `context.engine` 选择。 |
| **Model provider**（`plugins/model-providers/`） | `plugins/model-providers/` 下的所有内置 provider 在首次调用 `get_provider_profile()` 时发现并注册。用户通过 `--provider` 或 `config.yaml` 一次选择一个。 |
| **pip 安装的 `backend` 插件** | 通过 `plugins.enabled` 选择加入（与通用插件相同）。 |
| **用户安装的平台**（位于 `~/.hermes/plugins/platforms/`） | 通过 `plugins.enabled` 选择加入 —— 第三方 gateway 适配器需要明确同意。 |

简而言之：**内置的"始终可用"基础设施自动加载；第三方通用插件需选择加入。** `plugins.enabled` 允许列表专门用于控制用户放入 `~/.hermes/plugins/` 的任意代码。

### 审批传输 {#approval-transports}

审批传输（approval transport）改变的是**人类在哪里看到并回应**一个既有的 Hermes 工具审批请求。它不决定某条命令是否需要审批，也不是授权策略 API。

```python
def present(request):
    # Deliver request.command and request.description to your UI, wait for
    # its authenticated human response, then return a request-bound decision.
    choice = send_to_my_ui_and_wait(request)  # once/session/always/deny
    return request.respond(choice)


def register(ctx):
    ctx.register_approval_transport("my-ui", present)
```

`present` 可以是同步或异步函数。Hermes 在一个有界工作线程上运行它，并且即使插件自身没有强制，也会执行规范的 `approvals.timeout`。请求对象不可变，包含已脱敏的显示文本、宿主呈现类别（`cli` 或 `gateway`）、宿主超时、允许的选项，以及一个不透明的请求 ID/摘要。
请返回
`request.respond(choice)` 的结果；未绑定的字典以及过期或被更改的请求 ID/摘要都会被拒绝。插件不能返回宿主未提供的作用域（例如对仅限一次的请求返回 `always`）。

仅注册不会产生任何效果。启用插件与显式选择其传输是两个独立的同意步骤：

```yaml
plugins:
  enabled: [my-approval-plugin]

security:
  approval:
    transport: my-ui
    transport_fallback: deny     # 默认值
```

传输异常、超时、注册不可用、无效选项和过期响应默认都会拒绝。若希望在所选传输失败时，有意在普通的 CLI/TUI/gateway/ACP 界面上显示提示，请设置
`transport_fallback: builtin`。没有这个确切的显式选择，Hermes 永远不会在其他界面上呈现该提示。

Hermes 仍然掌控硬性阻止规则、sudo-stdin 保护、用户拒绝规则、请求绑定、允许的作用域、持久化、hook 以及最终授权。硬性阻止的命令会在任何传输回调之前就被拦截。该接口有意**不提供插件审批策略、自动放行回调或必需的
`pre_tool_call` 策略**。未来的审批策略能力可能会采用插件能力同意模型，但选择传输并不授予该能力。

### 现有用户的迁移 {#migration-for-existing-users}

当你升级到支持选择加入插件的 Hermes 版本（config schema v21+）时，已安装在 `~/.hermes/plugins/` 下且不在 `plugins.disabled` 中的用户插件会**自动纳入** `plugins.enabled`。你的现有配置继续正常工作。内置独立插件**不会**自动纳入 —— 即使是现有用户也需要明确选择加入。（内置平台/后端插件从未需要纳入，因为它们从未被控制。）

## 可用 hook {#available-hooks}

插件可注册 `hermes_cli.plugins.VALID_HOOKS` 当前接受的 26 个生命周期事件。**[Event Hooks 目录](/user-guide/features/hooks#shipped-plugin-hook-catalog)**是精确触发时机、返回值处理、payload 字段和隐私说明的权威参考。

| 描述性类别 | 已发布 hook |
|---|---|
| **指令/控制** | `pre_tool_call`, `pre_llm_call`, `pre_verify`, `pre_gateway_dispatch` |
| **转换** | `transform_tool_result`, `transform_terminal_output`, `transform_llm_output`, `pre_transcription` |
| **观察者** | `post_tool_call`, `post_llm_call`, `pre_api_request`, `post_api_request`, `api_request_error`, `on_stream_start`, `on_stream_delta`, `on_stream_end`, `on_interim_message`, `on_session_start`, `on_session_end`, `on_session_finalize`, `on_session_reset`, `on_skill_lifecycle`, `subagent_start`, `subagent_stop`, `pre_approval_request`, `post_approval_response`, `pre_command`, `kanban_task_claimed`, `kanban_task_completed`, `kanban_task_blocked` |

这些类别只描述当前行为，不规定未来命名规则。Plugin middleware 仍是独立的注册表/接口。
## 插件类型 {#plugin-types}

Hermes 有四种插件：

| 类型 | 作用 | 选择方式 | 位置 |
|------|-------------|-----------|----------|
| **通用插件** | 添加工具、hook、斜杠命令、CLI 命令 | 多选（启用/禁用） | `~/.hermes/plugins/` |
| **Memory provider** | 替换或增强内置 memory | 单选（同时只有一个激活） | `plugins/memory/` |
| **Context engine** | 替换内置上下文压缩器 | 单选（同时只有一个激活） | `plugins/context_engine/` |
| **Model provider** | 声明推理后端（OpenRouter、Anthropic 等） | 多注册，通过 `--provider` / `config.yaml` 选择 | `plugins/model-providers/` |

Memory provider 和 context engine 是 **provider 插件** —— 每种类型同时只能有一个激活。Model provider 也是插件，但可以同时加载多个；用户通过 `--provider` 或 `config.yaml` 一次选择一个。通用插件可以任意组合启用。

## 可插拔接口 —— 各场景对应文档 {#pluggable-interfaces--where-to-go-for-each}

上表展示了四种插件类别，但在"通用插件"中，`PluginContext` 暴露了多个不同的扩展点 —— Hermes 还接受 Python 插件系统之外的扩展（配置驱动的后端、shell hook 命令、外部服务器等）。使用下表找到适合你需求的文档：

| 想要添加… | 方式 | 编写指南 |
|---|---|---|
| LLM 可调用的**工具** | Python 插件 —— `ctx.register_tool()` | [Build a Hermes Plugin](/developer-guide/plugins) · [Adding Tools](/developer-guide/adding-tools) |
| **生命周期 hook**（LLM 前后、会话开始/结束、工具过滤） | Python 插件 —— `ctx.register_hook()` | [Hooks reference](/user-guide/features/hooks) · [Build a Hermes Plugin](/developer-guide/plugins) |
| CLI / gateway 的**斜杠命令** | Python 插件 —— `ctx.register_command()` | [Build a Hermes Plugin](/developer-guide/plugins) · [Extending the CLI](/developer-guide/extending-the-cli) |
| `hermes <thing>` 的**子命令** | Python 插件 —— `ctx.register_cli_command()` | [Extending the CLI](/developer-guide/extending-the-cli) |
| 插件附带的 **skill** | Python 插件 —— `ctx.register_skill()` | [Creating Skills](/developer-guide/creating-skills) |
| **推理后端**（LLM provider：OpenAI 兼容、Codex、Anthropic-Messages、Bedrock） | Provider 插件 —— 在 `plugins/model-providers/<name>/` 中调用 `register_provider(ProviderProfile(...))` | **[Model Provider Plugins](/developer-guide/model-provider-plugin)** · [Adding Providers](/developer-guide/adding-providers) |
| **Gateway 频道**（Discord / Telegram / IRC / Teams 等） | 平台插件 —— 在 `plugins/platforms/<name>/` 中调用 `ctx.register_platform()` | [Adding Platform Adapters](/developer-guide/adding-platform-adapters) |
| **Memory 后端**（Honcho、Mem0、Supermemory 等） | Memory 插件 —— 在 `plugins/memory/<name>/` 中继承 `MemoryProvider` | [Memory Provider Plugins](/developer-guide/memory-provider-plugin) |
| **上下文压缩策略** | Context-engine 插件 —— `ctx.register_context_engine()` | [Context Engine Plugins](/developer-guide/context-engine-plugin) |
| **图像生成后端**（DALL·E、SDXL 等） | 后端插件 —— `ctx.register_image_gen_provider()` | [Image Generation Provider Plugins](/developer-guide/image-gen-provider-plugin) |
| **视频生成后端**（Veo、Kling、Pixverse、Grok-Imagine、Runway 等） | 后端插件 —— `ctx.register_video_gen_provider()` | [Video Generation Provider Plugins](/developer-guide/video-gen-provider-plugin) |
| **TTS 后端**（任意 CLI —— Piper、VoxCPM、Kokoro、xtts、语音克隆脚本等） | 配置驱动（推荐）—— 在 `config.yaml` 的 `tts.providers.<name>` 下以 `type: command` 声明。或 Python 后端插件 —— 对需要超出 shell 模板的 Python SDK / 流式引擎使用 `ctx.register_tts_provider()`。 | [TTS Setup](/user-guide/features/tts#custom-command-providers) · [Python plugin guide](/user-guide/features/tts#python-plugin-providers) |
| **STT 后端**（任意 CLI —— whisper.cpp、自定义 whisper 二进制、本地 ASR CLI） | 配置驱动（推荐）—— 在 `config.yaml` 的 `stt.providers.<name>` 下以 `type: command` 声明，或设置 `HERMES_LOCAL_STT_COMMAND` 使用旧版单命令逃生舱。或 Python 后端插件 —— 对 Python SDK 引擎（OpenRouter、SenseAudio、Gemini-STT 等）使用 `ctx.register_transcription_provider()`。 | [STT Setup](/user-guide/features/tts#stt-custom-command-providers) · [Python plugin guide](/user-guide/features/tts#python-plugin-providers-stt) |
| **通过 MCP 使用外部工具**（文件系统、GitHub、Linear、Notion、任意 MCP 服务器） | 配置驱动 —— 在 `config.yaml` 中以 `command:` / `url:` 声明 `mcp_servers.<name>`。Hermes 自动发现服务器的工具并与内置工具一同注册。 | [MCP](/user-guide/features/mcp) |
| **额外 skill 来源**（自定义 GitHub 仓库、私有 skill 索引） | CLI —— `hermes skills tap add <repo>` | [Skills Hub](/user-guide/features/skills#skills-hub) · [发布自定义 tap](/user-guide/features/skills#publishing-a-custom-skill-tap) |
| **Gateway 事件 hook**（在 `gateway:startup`、`session:start`、`agent:end`、`command:*` 时触发） | 将 `HOOK.yaml` + `handler.py` 放入 `~/.hermes/hooks/<name>/` | [Event Hooks](/user-guide/features/hooks#gateway-event-hooks) |
| **Shell hook**（在事件时运行 shell 命令 —— 通知、审计日志、桌面提醒） | 配置驱动 —— 在 `config.yaml` 的 `hooks:` 下声明 | [Shell Hooks](/user-guide/features/hooks#shell-hooks) |

:::note
并非所有扩展都是 Python 插件。某些扩展接口有意使用**配置驱动的 shell 命令**（TTS、STT、shell hook），这样你已有的任意 CLI 无需编写 Python 即可成为插件。其他的是 agent 连接并自动注册工具的**外部服务器**（MCP）。还有一些是拥有自己 manifest 格式的**即插即用目录**（gateway hook）。根据你的集成风格选择合适的接口；上表中的编写指南各自涵盖了占位符、发现机制和示例。
:::

## NixOS 声明式插件 {#nixos-declarative-plugins}

在 NixOS 上，插件可通过模块选项声明式安装 —— 无需 `hermes plugins install`。完整详情请参见 **[Nix Setup 指南](/getting-started/nix-setup#plugins)**。

```nix
services.hermes-agent = {
  # 目录插件（包含 plugin.yaml 的源码树）
  extraPlugins = [ (pkgs.fetchFromGitHub { ... }) ];
  # 入口点插件（pip 包）
  extraPythonPackages = [ (pkgs.python312Packages.buildPythonPackage { ... }) ];
  # 在 config 中启用
  settings.plugins.enabled = [ "my-plugin" ];
};
```

声明式插件以 `nix-managed-` 前缀符号链接 —— 与手动安装的插件共存，从 Nix 配置中移除后自动清理。

## 管理插件 {#managing-plugins}

```bash
hermes plugins                               # 统一交互式 UI
hermes plugins list                          # 表格：已启用 / 已禁用 / 未启用
hermes plugins search <term>                 # 搜索 Hermes 插件目录
hermes plugins install <name>                # 安装目录条目（仓库 @ 经审核的固定 SHA）
hermes plugins install user/repo             # 从 Git 安装，然后提示 Enable? [y/N]
hermes plugins install user/repo --enable    # 安装并启用（无提示）
hermes plugins install user/repo --no-enable # 安装但保持禁用（无提示）
hermes plugins update my-plugin              # 拉取最新版本（本地修改会自动 stash 并重新应用）
hermes plugins remove my-plugin              # 卸载
hermes plugins enable my-plugin              # 添加到允许列表
hermes plugins disable my-plugin             # 从允许列表移除并添加到禁用列表
hermes plugins capabilities [my-plugin]      # 已声明与已授予的能力对比
```

### 一键安装链接（桌面版） {#one-click-install-links-desktop}

Hermes Desktop 注册了 `hermes://` URL scheme，因此网站、README 或聊天消息可以直接链接到插件安装：

```
hermes://plugin/install?repo=owner/repo            # 主安装链接
hermes://plugin/install?repo=owner/repo&enable=1   # 安装后启用 agent 插件
hermes://plugin/install?repo=owner/repo&force=1    # 替换已有安装
```

点击这样的链接会打开 Hermes 并显示一个**确认对话框** —— 包含仓库 id、一段"安装前须知"说明，以及 GitHub 浏览和克隆链接 —— 随后浅克隆该仓库以检测它包含的内容（**agent 插件** —— 后端 Python；**桌面插件** —— 应用 UI；或两者兼有）。你通过复选框选择组件并确认。在你确认之前不会安装任何内容；深度链接永远不会自动安装，而且 agent 插件的安装会经过与
`hermes plugins install` 相同的[安装时安全扫描](#install-time-security-scanning)。

混合仓库（agent 与桌面两部分位于同一仓库）只使用一个链接和一个对话框。不通过链接也可以经由 **Settings → Plugins →
Install from Git** 打开同一个对话框。旧版 `hermes://plugin-agent/…` 和
`hermes://plugin-desktop/…` URL 会路由到同一个对话框。在开发构建中（`npm run dev`），scheme 为 `hermes-dev://`。

网站无需任何 SDK —— 普通的锚点链接即可：

```html
<a href="hermes://plugin/install?repo=owner/repo&enable=1">Install in Hermes</a>
```

MCP 服务器也有等价的链接形式 —— 参见
[Add to Hermes link](/reference/mcp-config-reference#add-to-hermes-link)。

### 插件能力与同意 {#plugin-capabilities-and-consent}

插件可以在其 `plugin.yaml` 中声明所需的特权宿主接口：

```yaml
name: my-plugin
capabilities:
  - tools.override        # 替换内置工具
  - llm.model_override    # 为宿主托管的 LLM 调用选择模型
```

当插件声明了能力时，`hermes plugins install`（以及
`hermes plugins enable`）会列出这些能力并附上一行风险说明，然后询问一次。同意后，授权会记录在
`plugins.entries.<id>.granted_capabilities` 下，并附带同意哈希和时间戳。拒绝则插件保持启用、但这些能力关闭 —— 行为良好的插件会用 `ctx.has_capability()` 探测并优雅降级。

**更新时重新同意：** 如果插件更新声明了你尚未授予的能力，`hermes plugins update` 会列出新增项并再次询问。新能力在你同意之前保持关闭 —— 插件更新永远不会悄悄扩大其访问权限。

**非交互式会话按失败关闭处理：** 在没有 TTY 的情况下安装或更新会完成安装，但声明的能力*不会*被授予。之后请以交互方式运行
`hermes plugins enable <id>` 来授予它们。

随时查看状态：

```bash
hermes plugins capabilities             # 所有插件的已声明/已授予能力
hermes plugins capabilities my-plugin   # 单个插件，已声明与已授予对比
```

能力 id 与旧的按功能配置开关一一对应，旧开关仍然有效，但已**弃用**，建议改用同意流程：

| 能力 | 旧版键（`plugins.entries.<id>.…`） |
|---|---|
| `tools.override` | `allow_tool_override` |
| `llm.provider_override` | `llm.allow_provider_override` |
| `llm.model_override` | `llm.allow_model_override` |
| `llm.agent_id_override` | `llm.allow_agent_id_override` |
| `llm.profile_override` | `llm.allow_profile_override` |
| `llm.task_override` | `llm.allow_task_override` |
| `gateway.platform_actions` | `allow_platform_actions` |

只要能力已授予*或*设置了旧版键，开关就会打开 —— 现有配置无需修改即可继续工作。

:::warning 不是沙箱
能力是一个**同意与审计层**，而不是隔离机制。插件作为普通的进程内 Python 运行：恶意插件可以无视这里的所有开关。授予能力代表你信任插件作者 —— 它不是代码审计，Hermes 也没有审查过插件的代码。请只安装来自可信来源的插件。
:::

### 平台操作 {#platform-actions}

`ctx.platform_actions` 为插件提供一组最小的、受能力控制的动作，通过实时的 gateway 适配器注册表在已连接的聊天平台上执行操作 —— 这是替代对适配器打猴子补丁的官方方式。**它默认关闭**：每次调用都会重新检查 `gateway.platform_actions` 能力（旧版键 `plugins.entries.<id>.allow_platform_actions`），未授权的调用会返回结构化错误而不是执行操作。

v1 动作（都是 `async`，都返回普通 dict，且都不会向 hook 调度抛出异常）：

```python
result = await ctx.platform_actions.add_reaction(
    platform="telegram", chat_id="-100123", message_id="456", emoji="👍",
)
result = await ctx.platform_actions.set_thread_title(
    platform="discord", chat_id="123", thread_id="456", title="New title",
)
if not result["ok"]:
    print(result["error"], result.get("detail"))
```

成功时返回 `{"ok": True, "action": <verb>}`。失败时返回
`{"ok": False, "error": <code>, "detail": <str>}`，错误码是稳定的：
`capability_not_granted`、`invalid_argument`、`gateway_unavailable`、
`unknown_platform`、`adapter_not_registered`、`adapter_disconnected`、
`unsupported_platform_action`、`action_failed`。操作执行前会校验目标适配器存在且已连接；适配器断开或缺失时会降级为结构化错误，绝不会抛出异常。

v1 支持的平台：Telegram 和 Discord。Telegram 的 `add_reaction`
是*设置*机器人的反应（Bot API 会替换机器人之前的反应，而不是叠加）。每个操作 —— 无论被允许还是被拒绝 —— 都会连同插件 id、动作、平台和结果写入日志。

:::warning 安全说明
平台操作是一种**以机器人身份发消息的权力**：获得授权的插件可以在 gateway 机器人能触达的任何聊天中添加反应和重命名话题，而不仅仅是触发 hook 的那个聊天。请只把 `gateway.platform_actions` 授予你信任的插件，并优先选择明确说明自己会执行哪些操作的插件。原始平台 SDK 的 payload/句柄访问有意**不**包含在此接口中 —— 根据 #64176 第二轮设计修正，它需要单独的能力（`gateway.raw_events`），带有"不保证稳定性"标签并需要单独设计，目前尚未发布。
:::

### 发现插件 —— Hermes 插件目录 {#discovering-plugins--the-hermes-plugin-catalog}

`hermes plugins search <term>` 搜索 **Hermes 插件目录** —— 这是在 hermes-agent 仓库中维护的、经过筛选且固定 SHA 的目录（`plugin-catalog/`）。匹配范围包括条目名称、描述和声明的工具：

```bash
hermes plugins search telegram    # 搜索目录
hermes plugins browse             # 浏览所有条目
hermes plugins info <name>        # 查看单个条目的完整详情
```

找到插件后，直接用名称安装 —— 该名称会解析到条目仓库的**固定 commit SHA**，并记录目录来源，以便 `hermes plugins update` 在目录变动时重新固定：

```bash
hermes plugins install <catalog-name>
```

显式的 `owner/repo` 或 Git URL 标识符永远不会经过目录，并被标记为自定义（未经审核）来源。显式的
`--ref <40-char commit SHA>` 可固定自定义安装。

完整的信任模型、准入 CI 和提交流程请参见 [Plugin Catalog](./plugin-catalog.md)。

:::warning 已收录 ≠ 已审计
目录条目意味着该条目的元数据和声明的能力在准入时经过了审核 —— **这不是代码审计**。安装仍会经过正常的同意流程（插件安装后默认禁用，启用是显式步骤，工具覆盖权限需要单独授予）。启用插件之前请先审查其源码。
:::

### 插件包 {#plugin-packs}

**插件包**（plugin pack）是一个声明式、可分享的 YAML 文件（`hermes-pack.yaml`），用于固定一组插件 —— 类似于分享一个模组包。安装插件包会展开为若干普通的固定版本安装；运行时不会引入任何新东西。

```yaml
name: voice-assistant-pack
description: STT + streaming TTS + approval relay
author: hyper
version: 1.0.0
plugins:
  - name: hermes-telegram-business       # 插件目录中的名称…
    ref: e905f3bc5eeaa5a9dab9bc5155601b3ebec75757
  - repo: owner/approval-relay           # …或显式的 owner/repo（或 git URL）
    ref: 8f3c2d1a9b4e5f6071829304a5b6c7d8e9f00112
    subdir: plugins/relay                # 可选的 monorepo 路径
config:                                  # 可选，仅限非密钥的初始值
  hermes-media-studio:
    default_model: flux-3
skills: []                               # 仅为声明列表（暂不自动安装）
```

```bash
hermes plugins pack show ./hermes-pack.yaml     # 预演审查
hermes plugins pack install ./hermes-pack.yaml  # 审查 → 确认 → 安装
hermes plugins pack export > hermes-pack.yaml   # 导出当前安装的快照
hermes plugins pack export --enabled-only       # 仅导出 plugins.enabled
```

**供应链安全立场。** 每个条目的 `ref` 必须是确切的 40 字符 commit SHA —— tag 和分支名会被拒绝，并在错误中指出对应条目，规则与插件目录相同。插件包安装走的是与
`hermes plugins install --ref <sha>` 完全相同的固定安装路径，并在 `plugins/.install-metadata.json` 中记录相同的来源信息，因此同一插件包的两次安装会得到完全一致的结果。插件包建立在
[manifest v2 字段](/developer-guide/plugins)（`manifest_version`、
`api_version`、`requires_plugins`）之上 —— 每个插件自己的 manifest 仍会通过正常安装路径进行校验。

**同意永远不会被批量授予。** `pack install` 会显示一个强制性的审查界面（每个插件、来源、固定 ref 以及它声明的能力），然后对插件包内容**只**询问一次确认。之后，每个插件声明的能力都会经过标准的逐插件能力同意提示 —— 与单独执行 `hermes plugins install` 完全相同。
没有 `--yes`，非交互式会话也无法安装插件包。

**密钥永远不会随插件包传递。** `config:` 初始值仅限于非密钥的 `plugins.entries.<id>` 键 —— 看起来像密钥的键名
（`*token*`、`*key*`、`*password*` 等）、能力授权以及已弃用的
`allow_*` 信任开关在安装时会被拒绝，在导出时会被剔除。需要密钥的插件应在自己的 `requires_env` 中声明，安装时会照常提示输入。`plugins.entries.<id>` 中已有的用户值始终优先于插件包的初始值。

**部分失败。** 每个插件独立安装；失败会按插件分别报告，其余插件继续安装，只要有任何插件失败，命令就会以非零状态退出。

**导出注意事项。** `pack export` 只包含具有已知 Git 来源（通过 `hermes plugins install` 安装）的插件。仅本地的插件会在生成的 YAML 中以警告注释的形式列出，而不是可安装的条目。

`skills:` 列表会在安装时被解析和显示，但暂不会自动安装 —— 目前请手动安装（`hermes skills`）。将 skill-hub id 接入插件包安装是一个已记录的后续衔接点。

### 安装时安全扫描 {#install-time-security-scanning}

每次 `hermes plugins install` 和 `hermes plugins update` 都会在插件激活前对插件目录树运行静态安全扫描（灵感来自 Claude Cowork 的 skill 与插件安全扫描）。该扫描器复用与 [Skills Hub guard](/user-guide/features/skills)
相同的威胁模式引擎 —— 凭据存储外泄、反弹 shell、破坏性命令、持久化机制、混淆执行以及文档文件中的提示注入 —— 并带有面向插件的豁免：provider 插件从环境中读取其**自己的** API key（即文档中的
`requires_env` 模式）不会被标记。

三种判定，对应 Cowork 的 pass/warn/fail：

| 判定 | 行为 |
|---|---|
| **safe** | 正常安装，无额外输出 |
| **caution** | 显示发现项；你需要确认 `Install anyway? [y/N]`（或传入 `--force`） |
| **dangerous** | 被阻止。`--force` **无法**覆盖 |

在 `hermes plugins update` 时，如果更新后的目录树被判定为 dangerous，插件会被禁用，直到你审查发现项并重新启用它。

扫描默认开启；可在 `config.yaml` 中禁用：

```yaml
plugins:
  scan_on_install: false
```

### 交互式 UI {#interactive-ui}

不带参数运行 `hermes plugins` 会打开一个复合交互界面：

```
Plugins
  ↑↓ navigate  SPACE toggle  ENTER configure/confirm  ESC done

  General Plugins
 → [✓] my-tool-plugin — Custom search tool
   [ ] webhook-notifier — Event hooks
   [ ] disk-cleanup — Auto-cleanup of ephemeral files [bundled]

  Provider Plugins
     Memory Provider          ▸ honcho
     Context Engine           ▸ compressor
```

- **General Plugins 区域** —— 复选框，用空格切换。勾选 = 在 `plugins.enabled` 中，未勾选 = 在 `plugins.disabled` 中（明确关闭）。
- **Provider Plugins 区域** —— 显示当前选择。按 ENTER 进入单选选择器，选择一个激活的 provider。
- 内置插件在同一列表中显示，带有 `[bundled]` 标签。

Provider 插件的选择保存到 `config.yaml`：

```yaml
memory:
  provider: "honcho"      # 空字符串 = 仅使用内置

context:
  engine: "compressor"    # 默认内置压缩器
```

### 已启用 vs. 已禁用 vs. 未设置 {#enabled-vs-disabled-vs-neither}

插件处于以下三种状态之一：

| 状态 | 含义 | 在 `plugins.enabled` 中？ | 在 `plugins.disabled` 中？ |
|---|---|---|---|
| `enabled` | 下次会话时加载 | 是 | 否 |
| `disabled` | 明确关闭 —— 即使同时在 `enabled` 中也不会加载 | （无关） | 是 |
| `not enabled` | 已发现但从未选择加入 | 否 | 否 |

新安装或内置插件的默认状态为 `not enabled`。`hermes plugins list` 显示全部三种状态，便于区分明确关闭的插件和等待启用的插件。

在运行中的会话里，`/plugins` 显示当前已加载的插件。

## 注入消息 {#injecting-messages}

插件可使用 `ctx.inject_message()` 向 CLI 对话或已知的 gateway 会话注入消息：

```python
# Active CLI conversation
ctx.inject_message("New data arrived from the webhook", role="user")

# Existing gateway conversation
ctx.inject_message(
    "New data arrived from the webhook",
    role="user",
    session_key="agent:main:telegram:dm:123456789",
)
```

**签名：** `ctx.inject_message(content: str, role: str = "user", *, session_key: str | None = None) -> bool`

在 CLI 模式下：

- 若 agent **空闲**（等待用户输入），消息会作为下一条输入排队并开始新一轮。
- 若 agent **处于轮次中**（正在运行），消息会中断当前操作 —— 与用户输入新消息并按下 Enter 效果相同。
- 对于非 `"user"` 角色，内容会以 `[role]` 为前缀（例如 `[system] ...`）。
- 若消息成功排队，返回 `True`。

在 gateway 模式下：

- `session_key` 为必填项，且必须标识一个已存在的 gateway 会话。它是稳定的路由键，而不是 CLI 会话 ID。
- Hermes 会复用该会话已存储的平台、聊天、话题、profile 和对话历史。插件无法通过此 API 提供新的聊天路由。
- Hermes 在调度前会按 gateway 当前的授权规则重新检查已存储的路由。
- 仅依赖适配器阶段或上游授权决定的路由会被拒绝，除非 Hermes 能根据当前的核心允许列表、配对或显式的全部放行配置重新验证它们。
- 注入的文本始终是对话输入。它不能调用斜杠命令、批准工具，也不能处理待确认或待澄清的提示。
- 在调度等待期间，路由和对话会被固定。如果话题恢复改变了路由，或会话在处理开始前发生轮换，Hermes 会丢弃该请求。
- 请求会进入平台适配器的正常消息路径。活跃会话会使用现有的忙碌会话队列，而不是启动一个相互竞争的轮次。
- 当实时 gateway 接受请求进行异步调度时返回 `True`。这并不代表 agent 轮次或平台投递已经完成。
- 当省略 `session_key`、权限未授予或没有实时 gateway 能接受该请求时返回 `False`。在异步接受之后才发现的未知或无法路由的会话键会写入 gateway 日志。

这使得远程控制查看器、消息桥接或 webhook 接收器等插件能够从外部来源向对话注入消息。

Gateway 注入可能会把 agent 的回复发送到外部消息平台。它对所有插件默认禁用。请在 `config.yaml` 中按插件授权：

```yaml
plugins:
  entries:
    my-plugin:
      allow_gateway_injection: true
```

:::warning
只把 gateway 注入权限授予你信任的插件。Hermes 会检查这一宿主 API 权限，并将其限制在已有的会话路由上，但 Python 插件在进程内运行，此设置并不是沙箱。
:::

:::note
此插件 API 不会为外部进程暴露公开的 HTTP 端点或 CLI 命令。插件必须事先知道目标 gateway 的 `session_key`，例如来自其自身的可信配置或之前保存的会话状态。
:::

## 从插件调用 MCP 服务器 {#calling-mcp-servers-from-plugins}

`ctx.call_mcp()` 让插件可以调用用户已配置的某个 MCP 服务器上的工具 —— 同步调用，可在任何 hook 或工具处理器中使用 —— 并通过 Hermes 现有的原生 MCP 客户端路由（与模型调用的 MCP 工具使用相同的连接、信任层级开关、熔断器和重连逻辑；绝不会另起一个并行客户端）。

```python
result = ctx.call_mcp(
    "knowledge_rag",            # server name from mcp.servers
    "query_knowledge",          # tool on that server
    {"query": "deploy runbook"},
    timeout=30,                 # seconds; clamped to 1–600
)
if result["ok"]:
    print(result["result"])
else:
    print("MCP error:", result["error"])
```

**签名：** `ctx.call_mcp(server: str, tool: str, arguments: dict | None = None, timeout: float = 30) -> dict`

返回一个稳定的封装结构：`{"ok": True, "result": ...}`（服务器提供时还会附带 `structuredContent`）或 `{"ok": False, "error": "..."}`。超过约 64 KB 的结果会被截断，并标记 `"truncated": True`。

### 安全：默认关闭，按服务器设置允许列表 {#security-default-off-per-server-allowlist}

插件**默认没有 MCP 访问权限**。运维者必须在 `config.yaml` 中显式授予每个服务器：

```yaml
plugins:
  entries:
    my-plugin:
      mcp_allowlist: ["knowledge_rag", "github"]
```

- 调用不在列表中的服务器会抛出 `PermissionError`，并指出需要设置的确切配置键。
- 授权按服务器、按插件进行 —— 绝不会获得对所有已配置服务器的全局权限，且不支持 `"*"` 通配符。
- 每次调用都有强制超时（默认 30 秒），因此挂起的 MCP 服务器不会拖住调用它的 hook 或工具流水线。
- MCP 服务器返回的是不可信内容。请把 `result` 当作数据而不是指令 —— 未经校验不要将其用于特权决策（审批、命令执行）。

:::warning
授予 `mcp_allowlist` 会让插件对该 MCP 服务器拥有与模型相同的访问权限 —— 包括服务器暴露的任何具有写入能力的工具（受服务器 `trust` 层级开关约束）。只授予插件确实需要的服务器。
:::

完整的处理器约定、schema 格式、hook 行为、错误处理和常见错误请参见 **[完整指南](/developer-guide/plugins)**。
