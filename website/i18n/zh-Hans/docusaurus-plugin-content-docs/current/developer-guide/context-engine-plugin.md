---
sidebar_position: 9
title: "Context Engine 插件"
description: "如何构建替换内置 ContextCompressor 的 context engine 插件"
---

# 构建 Context Engine 插件

Context engine 插件用于替换内置的 `ContextCompressor`，以实现管理对话上下文的替代策略。例如，无损上下文管理（LCM）引擎通过构建知识 DAG 来替代有损摘要。

## 工作原理

Agent 的上下文管理基于 `ContextEngine` ABC（`agent/context_engine.py`）构建。内置的 `ContextCompressor` 是默认实现。插件引擎必须实现相同的接口。

同一时间只能有**一个** context engine 处于激活状态。选择由配置驱动：

```yaml
# config.yaml
context:
  engine: "compressor"    # 默认内置
  engine: "lcm"           # 激活名为 "lcm" 的插件引擎
```

插件引擎**永远不会自动激活** — 用户必须显式将 `context.engine` 设置为插件名称。

## 目录结构

每个 context engine 位于 `plugins/context_engine/<name>/`：

```
plugins/context_engine/lcm/
├── __init__.py      # 导出 ContextEngine 子类
├── plugin.yaml      # 元数据（name、description、version）
└── ...              # 引擎所需的其他模块
```

## ContextEngine ABC

你的引擎必须实现以下**必需**方法：

```python
from agent.context_engine import ContextEngine

class LCMEngine(ContextEngine):

    @property
    def name(self) -> str:
        """短标识符，例如 'lcm'。必须与 config.yaml 中的值匹配。"""
        return "lcm"

    def update_from_response(self, usage: dict) -> None:
        """每次 LLM 调用后，以 usage dict 为参数调用。

        从响应中更新 self.last_prompt_tokens、self.last_completion_tokens、
        self.last_total_tokens。
        """

    def should_compress(self, prompt_tokens: int = None) -> bool:
        """若本轮应触发压缩则返回 True。"""

    def compress(self, messages: list, current_tokens: int = None,
                 focus_topic: str = None) -> list:
        """压缩消息列表并返回新的（可能更短的）列表。

        返回的列表必须是有效的 OpenAI 格式消息序列。

        ``focus_topic`` 是来自手动 ``/compress <focus>`` 的可选主题字符串；
        支持引导式压缩的引擎应优先保留与其相关的信息，其他引擎可忽略。
        """
```

### 引擎必须维护的类属性

Agent 直接读取这些属性用于显示和日志记录：

```python
last_prompt_tokens: int = 0
last_completion_tokens: int = 0
last_total_tokens: int = 0
threshold_tokens: int = 0        # 触发压缩的阈值
context_length: int = 0          # 模型的完整上下文窗口
compression_count: int = 0       # compress() 已运行的次数
```

### 可选方法

这些方法在 ABC 中有合理的默认实现，按需覆盖：

| 方法 | 默认行为 | 何时覆盖 |
|--------|---------|--------------|
| `on_session_start(session_id, **kwargs)` | 空操作 | 需要加载持久化状态（DAG、DB）时 |
| `on_session_end(session_id, messages)` | 空操作 | 需要刷新状态、关闭连接时 |
| `on_session_reset()` | 重置 token 计数器 | 有需要清除的会话级状态时 |
| `update_model(model, context_length, ...)` | 更新 context_length 和阈值 | 需要在切换模型时重新计算预算时 |
| `get_tool_schemas()` | 返回 `[]` | 引擎提供 agent 可调用的工具时（例如 `lcm_grep`） |
| `handle_tool_call(name, args, **kwargs)` | 返回错误 JSON | 实现工具处理器时 |
| `should_compress_preflight(messages)` | 返回 `False` | 可在 API 调用前进行低成本预估时 |
| `get_status()` | 标准 token/阈值字典 | 有自定义指标需要暴露时 |
| `select_context(request_messages, *, conversation_messages, incoming_message, budget_tokens)` | 返回 `None`（空操作） | 需要选择/路由哪些上下文进入**本次**请求时（检索、话题路由）——见下文 |
| `on_turn_complete(messages, usage=None, **kwargs)` | 空操作 | 需要摄取/索引/观察已完成的轮次时——见下文 |

## 按轮次的上下文选择与观察 {#per-turn-context-selection-and-observation}

`compress()` 回答的是“上下文太长 → 把它变短”。另有两个可选、默认空操作的钩子覆盖与之正交的*选择 / 观察*维度，因此引擎不再需要强行让 `should_compress()` 返回 `True`，把 `compress()` 滥用为按轮次的回调：

```python
def select_context(self, request_messages, *, conversation_messages=None,
                   incoming_message=None, budget_tokens=0):
    """在分发前为本次请求选择/替换上下文。

    返回一个新的消息列表，仅用于这一次 provider 调用（检索、话题路由、
    角色/分支切换），或返回 None 保持不变。
    仅作用于请求：持久化的对话历史永远不会被修改。
    """

def on_turn_complete(self, messages, usage=None, **kwargs):
    """在 assistant/工具循环结束后观察已完成的轮次。

    接收最终转录的浅拷贝以及该轮次的规范 usage dict（若未收到任何
    provider 响应则为 None），以便引擎为下一次 select_context() 进行
    摄取/索引/摘要。返回值会被忽略。
    """
```

契约：

- **默认空操作，失败时放行（fail-open）。** 两者默认都是 `return None`。缺失钩子、抛出异常或返回无效值都会让请求保持原样——因此出错的引擎绝不会比不安装引擎更糟。宿主还会对继承自 ABC 的默认实现做身份检查并完全跳过它，所以未实现这些钩子的引擎（包括内置压缩器）不会有任何按请求的额外开销。
- **`select_context()` 仅作用于请求。** 返回的列表只替换单次 provider 调用的消息；持久化历史永远不会被写入。返回 `None`、`[]`、非列表，或包含非 dict 元素的列表，都会回退到未修改的请求。
- **顺序 / 缓存稳定性。** 该钩子在 prompt cache-control 和所有请求清洗器**之前**运行，因此 (a) 替换后的列表仍会经过与任何请求相同的校验，(b) 空操作默认实现让请求保持逐字节一致——对未实现该钩子的引擎，prompt 缓存行为不变。替换列表的引擎只会改变它自己的缓存前缀。每次 provider 请求都会求值（重试时会重新运行）。
- **`on_turn_complete()`** 仅用于轮次结束后的观察；请把 `messages` 视为只读。**覆盖是尽力而为的：** 它从标准的轮次收尾接缝处触发。循环中的某些异常提前返回路径（例如内容策略拦截或 provider 终止性失败）会直接持久化并返回，不经过收尾流程，因此目前不会触发此钩子——请把它当作对已完成轮次的尽力观察，而不是对每个提前退出都保证触发的回调。把所有终止路径统一到同一个收尾接缝是单独的后续工作。

### 何时使用这些钩子——以及何时不该用 {#when-to-use-these-hooks--and-when-not-to}

- **只有当你的引擎必须*替换*按请求的上下文时，才实现 `select_context()`**——检索增强选择、话题/分支路由、角色切换。它是唯一能调换哪些消息进入请求的动词：`pre_llm_call` 插件钩子按文档设计是只注入的（它追加到用户消息中，从不重写列表，以保留 prompt 缓存前缀）。如果你不需要替换，就不要实现它。
- **如果你的插件只需要轮次结束后的观察 / 摄取**（索引、记忆同步、分析），请实现一个 **memory provider**（`sync_turn()`——参见 [Memory Provider 插件](./memory-provider-plugin.md)），而不是 context engine。context engine 会接管会话的压缩策略；memory provider 只观察轮次，不拥有任何东西。`on_turn_complete()` 是为*已经*需要 `select_context()` 的引擎提供的观察镜像——让同一组件能从它刚刚路由过的轮次中学习——而不是通用的轮次回调。
- **真实 `select_context()` 对 prompt 缓存的影响。** 非空操作的选择在改变选择结果的轮次上自然会改变 prompt 缓存前缀——该请求的前缀不再与 provider 缓存的前缀匹配，因此这些轮次会重写缓存而不是读取缓存。引擎应在**没有变化时返回稳定的选择**（同一对象或相等的列表），只在路由决策确实不同时才重塑上下文；每轮都打乱的选择会在每一轮悄无声息地丧失缓存复用。

## 引擎工具

Context engine 可以暴露 agent 直接调用的工具。从 `get_tool_schemas()` 返回 schema，并在 `handle_tool_call()` 中处理调用：

```python
def get_tool_schemas(self):
    return [{
        "name": "lcm_grep",
        "description": "Search the context knowledge graph",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        },
    }]

def handle_tool_call(self, name, args, **kwargs):
    if name == "lcm_grep":
        results = self._search_dag(args["query"])
        return json.dumps({"results": results})
    return json.dumps({"error": f"Unknown tool: {name}"})
```

引擎工具在启动时注入到 agent 的工具列表中并自动分发 — 无需注册到注册表。

## 注册

### 通过目录（推荐）

将引擎放置于 `plugins/context_engine/<name>/`。`__init__.py` 必须导出一个 `ContextEngine` 子类。发现系统会自动找到并实例化它。

### 通过通用插件系统

通用插件也可以注册 context engine：

```python
def register(ctx):
    engine = LCMEngine(context_length=200000)
    ctx.register_context_engine(engine)
```

只能注册一个引擎。第二个尝试注册的插件将被拒绝并发出警告。

## 生命周期

```
1. 引擎实例化（插件加载或目录发现）
2. on_session_start() — 对话开始
3. update_from_response() — 每次 API 调用后
4. should_compress() — 每轮检查
5. compress() — 当 should_compress() 返回 True 时调用
6. on_session_end() — 会话边界（CLI 退出、/reset、gateway 关闭）
```

`on_session_reset()` 在 `/new` 或 `/reset` 时调用，用于清除会话级状态而不完全关闭。

## 配置

用户通过 `hermes plugins` → Provider Plugins → Context Engine 选择引擎，或直接编辑 `config.yaml`：

```yaml
context:
  engine: "lcm"   # 必须与引擎的 name 属性匹配
```

`compression` 配置块（`compression.threshold`、`compression.protect_last_n` 等）专属于内置的 `ContextCompressor`，但有一个明确的例外：`compression.model_thresholds`（按模型的阈值覆盖）属于 context engine 契约的一部分。宿主会在首次调用 `update_model()` *之前*把解析后的映射赋给 `engine.model_thresholds`，基类的 `update_model()` 会应用它（最长子串匹配，未匹配时回退到引擎配置的阈值）。覆盖了 `update_model()` 的引擎自行负责压缩策略，可以遵循也可以忽略该映射——可通过 `from agent.context_compressor import resolve_model_threshold` 复用相同的解析逻辑。除此之外，如有需要，你的引擎应定义自己的配置格式，并在初始化期间从 `config.yaml` 读取。

## 测试

```python
from agent.context_engine import ContextEngine

def test_engine_satisfies_abc():
    engine = YourEngine(context_length=200000)
    assert isinstance(engine, ContextEngine)
    assert engine.name == "your-name"

def test_compress_returns_valid_messages():
    engine = YourEngine(context_length=200000)
    msgs = [{"role": "user", "content": "hello"}]
    result = engine.compress(msgs)
    assert isinstance(result, list)
    assert all("role" in m for m in result)
```

完整的 ABC 契约测试套件请参见 `tests/agent/test_context_engine.py`。

## 线程安全 {#thread-safety}

当 `compression.context_timeout_seconds > 0`（默认如此）时，Hermes 会在一个池化的守护线程上运行整个压缩过程——包括你的引擎的 `compress()` 与边界回调，以及任何 memory provider 的 `on_pre_compress` / `on_session_switch`——并由宿主侧施加超时。因此你的引擎必须假设：

- 调用可能到达任意一个池化线程。不要依赖线程亲和性，也不要依赖与对话线程共享的 `threading.local` 状态。
- 你收到的消息列表是私有的深拷贝快照；允许原地修改（遗留契约），但只有当该过程提交时修改才会生效。宿主超时后，你仍在运行的工作会被丢弃——绝不要在提交之外向外部/持久状态发布任何内容。
- *不同*会话的压缩过程可能在池中的兄弟线程上并发运行；跨会话共享的单个引擎/provider 实例必须是线程安全的。

## 另请参阅

- [上下文压缩与缓存](/developer-guide/context-compression-and-caching) — 内置压缩器的工作原理
- [Memory Provider 插件](/developer-guide/memory-provider-plugin) — 类似的单选插件系统（用于内存）
- [插件](/user-guide/features/plugins) — 通用插件系统概述