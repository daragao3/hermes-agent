---
title: 上下文压缩与缓存
description: Hermes Agent 如何通过双重压缩系统和 Anthropic prompt 缓存高效管理上下文窗口。
---

# 上下文压缩与缓存

Hermes Agent 使用双重压缩系统和 Anthropic prompt（提示词）缓存，在长对话中高效管理上下文窗口用量。

源文件：`agent/context_engine.py`（ABC）、`agent/context_compressor.py`（默认引擎）、
`agent/prompt_caching.py`、`gateway/run_turn.py`（会话清理）、`agent/compression_facade.py`（搜索 `_compress_context`）


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

位于 `gateway/run_turn.py`（搜索 `Session hygiene`）。这是一个**安全网**，在 agent 处理消息之前运行。它防止会话在两次交互之间增长过大时（例如 Telegram/Discord 中的隔夜积累）导致 API 失败。

- **阈值**：固定为模型上下文长度的 85%
- **Token 来源**：优先使用上一轮 API 实际报告的 token 数；其次使用持久化在会话行上的用量锚点（真实计数 + 此后追加内容的增量；可在 gateway 重启后保留）；最后才使用基于字符的粗略估算（`estimate_messages_tokens_rough`）
- **触发条件**：仅当 `len(history) >= 4` 且压缩已启用时
- **目的**：捕获逃过 agent 自身压缩器的会话

Gateway 清理阈值有意高于 agent 压缩器的阈值。将其设置为 50%（与 agent 相同）会导致长 gateway 会话在每一轮都过早触发压缩。

### 2. Agent ContextCompressor（50% 阈值，可配置）

位于 `agent/context_compressor.py`。这是**主要压缩系统**，在 agent 的工具循环内运行，可访问准确的 API 报告 token 数。

#### Token 计数：提供商锚点与显式启发式回退

每个压缩闸门（轮次开始预检、空闲、API 调用前压力、工具调用后）都会先询问**用量锚点**（`agent/usage_anchor.py`）：提供商上一次返回的 prompt 与 completion token 数，加上仅对该响应之后追加的消息所做的粗略估算。锚点通过内容指纹识别已计价的转录，因此即使 gateway 每轮都从数据库重新读取历史也能保留；它还被持久化在会话行上，使新进程（`--resume`、桌面端按轮次启动的 `serve`）在持久转录仍然匹配时能够恢复它。压缩、会话重置以及 codex 原生压缩都会清除锚点。

对于内置引擎的**轮次开始与 API 调用前阈值闸门**，在没有锚点时（首次请求、回退/编辑重发），整段上下文的粗略估算即使超过阈值，也会**等待一次请求**以获取提供商证据（`should_defer_preflight_to_real_usage`）。这也包括估算值达到或超过整个上下文窗口的情况：估算的大小并不能证明请求一定会失败。切换模型后，旧用量会被清除，首次请求同样由新提供商裁定；真正超大的请求可能会先被拒绝一次，然后才进入被动恢复。

这种等待并不等于禁用。一旦某个响应缺少用量信息，现有的启发式回退仍然可用；真实用量已超过阈值以及提供商证实的溢出仍然允许压缩。压缩后闩锁会等待一个响应，即使该响应缺少用量信息也会被消耗。恢复过程仍受压缩尝试预算和无进展保护的约束，而不是无限重发循环。

这**不是仅依赖精确计数的策略**，也不意味着 #104462 字面意义上“绝不估算”的验收已关闭。以下策略保持不变：

- 锚点包含提供商的 prompt 与 completion token 数，外加**粗略的追加消息增量**（第一条追加的 assistant 消息已被 completion 用量覆盖）。因此，一个大型的新工具结果仍可能凭借估算增量越过阈值。边界指纹匹配不会对整个前缀、模型、工具或系统提示词做指纹。
- 可选的空闲压缩使用自己的下限/冷却时间，并可能针对无锚点的压力采取行动；它不共享阈值闸门的“等待一次请求”机制。
- Agent 之前的 gateway 清理保留其粗略历史回退和硬性消息安全阀。回放测试框架的 `gateway` 形态会重新加载转录字典；它**不会**覆盖那套独立的清理策略。
- 工具调用后缺少用量时的回退、微压缩、摘要/尾部大小计算、裁剪以及溢出进度检查仍使用本地估算。原生压缩保留其提供商特定的归属与检查点闩锁。

提供商计数端点仍被推迟。要消除这些剩余的估算，需要一个明确的策略决策：接受已记录的活性回退，或用提供商证据替代它们，同时为从不返回用量的提供商定义行为。简单地禁用所有无锚点维护并不等价。

`evals/token_accounting/replay_gates.py` 覆盖窗口以下与超出窗口的膨胀、真实超阈值对照、重新加载/恢复锚点，以及本地 HTTP 溢出/缺少用量时的恢复（使用真实压缩但固定的本地摘要文本）。这些是脚本化的控制流检查，而不是厂商分词器或计费证据。

不透明的提供商数据块（Codex 推理 / 压缩条目上的 `encrypted_content`）在所有本地估算中计为 0；只有真实用量才会对其计价。

图片按**从提供商用量中学习到的**单张图片成本计价（`agent/image_token_cost.py`），而不是厂商公式：当某个响应相对上一个锚点的增量引入了 N 张图片时，真实 `prompt_tokens` 与纯文本预测之间的残差即为 N × 提供商的单价。该值按 `model@host` 保存在 `~/.hermes/cache/image_token_costs.json` 中，并按轮次绑定，使触发估算器、尾部预算遍历和 gateway 清理都使用同一个数值。在第一次视觉轮次之前，使用固定的 1,500 默认值。

#### 失败冷却与提供商证实的溢出

一次失败或停滞的摘要尝试会为该会话设置**失败冷却**（逐级递增 60s → 300s → 900s，持久化在 `state.db` 中）。冷却生效期间，普通的阈值触发压缩会被推迟，以免损坏的摘要后端每轮都重新触发。以下两种路径仍会执行真正的尝试：

- 手动 `/compress`（`force=True`）——清除冷却并重试。
- **提供商证实的溢出**——当提供商本身以上下文长度错误拒绝请求时，恢复流程会忽略冷却，执行一次有界尝试（`max_compression_attempts`），但不会清除冷却。在这里推迟会让会话卡死：每一轮都会被提供商退回，而下一次失败又会延长冷却阶梯（#100661）。如果这次尝试失败，冷却会照常记录。


## 配置

所有压缩设置从 `config.yaml` 的 `compression` 键读取：

```yaml
compression:
  enabled: true              # Enable/disable compression (default: true)
  threshold: 0.50            # Fraction of context window (default: 0.50 = 50%)
  # model_thresholds:        # Per-model threshold overrides (substring match,
  #   "glm-5.2": 0.40        # longest key wins). See "Per-model threshold
  #   "claude-sonnet": 0.35  # overrides" below.
  target_ratio: 0.20         # How much of threshold to keep as tail (default: 0.20)
  tail_mode: lean            # Tail retention policy: lean | legacy (default: lean)
  protect_last_n: 20         # Minimum protected tail messages (default: 20)
  min_tail_user_messages: 1  # Real user messages guaranteed in the tail (default: 1)
  codex_gpt55_autoraise: true  # gpt-5.5 on Codex OAuth: raise trigger to 85% (default: true)
  codex_gpt55_autoraise_notice: true  # Show the one-time autoraise notice (default: true)
  codex_app_server_auto: native  # native|hermes|off for Codex app-server thread compaction
  codex_responses_native: false  # gpt-5.6 on direct OpenAI/Codex: server-side compaction (opt-in)
  codex_responses_compact_threshold: null  # Automatic server compaction trigger
  in_place: true             # Compact on the same session id, no rotation (default: true)

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
| `model_thresholds` | `{}` | map | 按模型覆盖 `threshold`。键按子串与模型名称匹配（最长匹配者胜出）。小上下文下限仍会叠加生效（见下文） |
| `target_ratio` | `0.20` | 0.10-0.80 | 控制尾部保护 token 预算：`threshold_tokens × target_ratio`（仅 legacy 模式——`lean` 使用自己的截取规则） |
| `tail_mode` | `lean` | `lean`、`legacy` | 尾部保留策略。`legacy` 保留 `target_ratio` 大小的逐字尾部（大窗口模型约 100K+ token）。`lean` 保留截取后的尾部，大小为 `2.5% × context window`（上下文窗口的 2.5%，下限 10K、上限 25K），并改由摘要承载连续性：一份保留标识符的详细会话日志（由同一次摘要请求生成——lean 压缩每次尝试只进行恰好一次辅助 LLM 调用）、机械提取的锚点索引（PR 编号、SHA、路径、报错文本——正则提取，绝不改写）、逐字引用的每一条真实用户消息（按从新到旧分配预算），以及一个 `session_search` 恢复指引，使 agent 能重新访问任何被摘要掉的内容。过大的区域会被均匀采样后送入摘要器输入（带有显式省略标记），而不是触发额外调用。在 500K token 的真实会话上：保留约 49K（对比约 162K），且与恢复机制配合时召回率更高（参见 `evals/compaction/results/`）。lean 尾部中较旧的工具结果会降级为带恢复指引的单行占位 |
| `protect_last_n` | `20` | ≥1 | 始终保留的最近消息最小数量 |
| `min_tail_user_messages` | `1` | ≥1 | 保证在未压缩尾部中保留的真实（可执行）用户消息最小数量。`1` = 现有的单条最后用户消息锚点（保持原有行为的默认值）。可提高到例如 `3`，即使庞大的工具输出占满了尾部 token 预算，也能逐字保留最后 3 个真实用户轮次。空白的平台回显、压缩交接消息和合成的续接行永远不计入 N。该保证优先于尾部 token 预算——当锚点把切分点往回拉时，尾部可能超出预算 |
| `protect_first_n` | `3` | （硬编码）| 系统提示词 + 首次交互始终保留 |
| `idle_compact_after_seconds` | `0` | ≥0 秒 | 可选：当会话在空闲这么多秒后恢复时，预先进行压缩（0 = 禁用）。当上下文 ≤ threshold × target_ratio 时跳过；遵守冷却/防抖/锁保护 |
| `codex_gpt55_autoraise` | `true` | bool | 在 ChatGPT Codex OAuth 路由上为 gpt-5.4/5.5/5.6 以及 gpt-6 Astra 将触发阈值提升到 85%（见下文）。设为 `false` 可保持全局 `threshold` |
| `codex_gpt55_autoraise_notice` | `true` | bool | 显示一次性的 Codex gpt-5.5 自动提升提示。设为 `false` 可保留 85% 自动提升但隐藏该横幅 |
| `codex_app_server_auto` | `native` | `native`、`hermes`、`off` | Codex app-server 会话的线程压缩模式（见下文） |
| `codex_responses_native` | `false` | bool | 选择启用 OpenAI 在 Responses API 上的服务端压缩。仅对直连 OpenAI API 或 ChatGPT Codex 订阅上的 gpt-5.6 系列模型生效（见下文） |
| `codex_responses_compact_threshold` | `null` | `null` 或正整数 | `null` 跟随解析后的本地压缩触发点，并保留 8,192 token 的安全余量。正整数保持为绝对值，仅在必要时向下截取。无效值使用自动行为。当不存在可用的本地触发点时，自动模式回退到 `200000` |
| `in_place` | `true` | bool | 在同一会话 id 上压缩，而不是轮换到新的会话 id（见下文） |

### 原地压缩（单一稳定会话 id）

当 `compression.in_place: true`（默认）时，一次压缩会**在同一会话 id 上重写实时消息列表**：系统提示词被重建，摘要后的中间部分被换入，而压缩前的轮次以同一 id 软归档（会话存储中 `active=0, compacted=1`）——仍可通过 `session_search` 搜索并恢复，永不删除。不存在 `parent_session_id` 链，也没有 `name #N` 重新编号；一段对话在其整个生命周期内保持同一个持久 id。这消除了会话轮换相关的一系列 bug（丢失 `/goal` 状态、孤立会话、跨边界的搜索空白）。

消费方通过观察模式来判断，而不是比较会话 id 的差异：

- `session:compress` 事件携带 `in_place: true/false` 和 `old_session_id`（原地模式下为空字符串，因为不存在旧 id）。
- Gateway 根据 agent 与轮换无关的 `_last_compaction_in_place` 标志重新确定转录处理的基线，而不是依据 id 变化的差异。

设置 `in_place: false` 可恢复旧的轮换路径：每次压缩都会提交一个新的会话 id，并通过 `parent_session_id` 链接到上一个会话。

### 辅助模型可行性与尾部保留

较小的辅助压缩模型可能会降低实际生效的压缩触发点，但不会改变所选的尾部策略。在 `lean` 模式下，选择预算仍基于**主模型的上下文窗口**：2.5%，截取到 10K–25K token。例如，一个 1M 主模型搭配 512K 辅助模型时，即使可行性检查将触发点从 850K 降到 512K，仍保留 25K 的选择预算。显式的 `legacy` 模式则会重新计算 `threshold_tokens × target_ratio`（512K × 0.20 时为 102,400 token）。这些是尾部选择预算，而不是对整个压缩后上下文的严格限制：受保护的消息、边界对齐、摘要和锚点都可能增加 token。

### 按模型覆盖阈值

`compression.model_thresholds` 允许你根据当前活跃模型在不同的位置触发压缩——当你在上下文窗口差异很大的模型之间切换时很有用（例如 1M 上下文的模型可以更晚压缩，而 128K 的模型应更早压缩）：

```yaml
compression:
  threshold: 0.50
  model_thresholds:
    "glm-5.2": 0.40
    "glm-5.2-1M": 0.25
    "claude-sonnet": 0.35
```

解析规则：

- 键按**子串**与模型名称匹配；**最长的匹配键胜出**（对于模型 `glm-5.2-1M`，`glm-5.2-1M` 优先于 `glm-5.2`）。
- 当没有键匹配（或映射为空）时，使用全局 `threshold`。
- 每次 `/model` 切换时都会重新解析覆盖值；切换到没有匹配键的模型时回退到全局 `threshold`。
- **小上下文下限仍会叠加在覆盖值之上**（只升不降）：上下文窗口低于 512K 的模型下限为 `0.75`，因此低于该下限的覆盖值会被提升到 `0.75`，而高于它的覆盖值（例如 `0.80`）胜出。

插件上下文引擎可以通过 `from agent.context_compressor import resolve_model_threshold` 复用同一套解析逻辑；覆写 `update_model()` 的引擎拥有自己的压缩策略，可以忽略该映射。

### Codex gpt-5.x / Astra 阈值自动提升

ChatGPT Codex OAuth 后端将 gpt-5.4/5.5/5.6 以及 gpt-6 Astra 的上下文窗口硬性限制为 **272K**（同一 slug 在 OpenAI 直连 API 和 OpenRouter 上暴露为 1.05M，在 GitHub Copilot 上为 400K）。在默认的 50% 触发阈值下，压缩会在约 136K 时触发——只有模型实际可用窗口的一半。当活跃路由是 Codex OAuth（`provider: openai-codex`）且模型属于上述系列之一时（Astra 匹配任何包含 `astra` 的 slug；可选的 `-900k` 选择器变体被排除，因为它们已经解锁了更大的窗口），Hermes 会将触发阈值提升到 **85%**（约 231K），并显示一条带有退出命令的提示。该提示每个 profile 只显示一次——`$HERMES_HOME` 下的一个标记文件（`.codex_gpt55_autoraise_notice`）记录它已经运行过，因此重复的 agent/会话初始化（例如每条入站网关消息）不会重复发出；如果提升后的阈值之后发生变化，则会再次提示一次。只有这一条精确路由会受影响；同样的模型在任何其他提供商上仍使用你的全局 `threshold`。若要退回到全局值：

```bash
hermes config set compression.codex_gpt55_autoraise false
```

若要保留 85% 自动提升但仅隐藏这条一次性提示：

```bash
hermes config set compression.codex_gpt55_autoraise_notice false
```

### Codex 大上下文 `-900k` 选择器变体（可选启用）

ChatGPT Codex 后端为 gpt-5.4 和 gpt-5.6（Sol/Terra/Luna）系列*宣称*的窗口是 272K，但对 ChatGPT 订阅账号实际接受约 911K 输入 token（2026 年 8 月实测验证）。Hermes 对基础 slug 保持**宣称的 272K 作为默认值**——更大的窗口意味着每次请求消耗更多 token，订阅用量的消耗也会快得多，因此大窗口严格为可选启用。

要使用大窗口，请在 `/model` 中选择显式的 `-900k` 变体（例如 `gpt-5.6-sol-900k`、`gpt-5.6-terra-900k`、`gpt-5.6-luna-900k`、`gpt-5.4-900k`）。这些是 Hermes 侧的别名：在模型 id 发送到后端之前会去掉该后缀，定价/用量统计也将其视为基础模型。真正强制执行 272K 的 slug（gpt-5.5、gpt-5.4-mini）没有 `-900k` 变体。

压缩阈值随窗口而定：基础 slug（272K）获得上文所述的 **85% 自动提升**，而 `-900k` 变体保持你的全局 `compression.threshold`（默认 50%，约 450K）——自动提升的存在是为了避免浪费较小的窗口，而 900K 的窗口并不需要它。

### Codex app-server 线程压缩

Codex app-server 会话（`api_mode: codex_app_server`——即 codex CLI/agent 运行时）与其他所有路由都不同：codex agent 拥有背后的线程上下文，因此 Hermes 的辅助摘要器无法压缩它——重写本地转录镜像只会让真实线程无限增长，直到发生一次硬性上下文重置。对于该运行时，压缩改为走 app-server 自身的机制：

- 手动压缩（`/compress`）会请求 app-server 压缩线程（`thread/compact/start`）并等待压缩轮次完成。
- 自动压缩由 `compression.codex_app_server_auto` 控制：默认值 `native` 让 app-server 自行决定何时压缩，Hermes 只记录由此产生的压缩事件（压缩计数器、会话事件）。设为 `hermes` 可让 Hermes 的压缩阈值发起 app-server 压缩，设为 `off` 则完全禁用由 Hermes 发起的自动压缩（codex 仍可能原生压缩）。

在该运行时上，Hermes 的本地转录永远不会被重写——state.db 记录压缩边界，而可见的转录保持完整。所有其他路由（包括 Codex OAuth 聊天会话）仍使用 Hermes 的摘要压缩器。

### 原生 Responses 压缩（直连 OpenAI / Codex 订阅上的 gpt-5.6）

OpenAI 的 Responses API 支持服务端压缩：当请求包含 `context_management: [{type: "compaction", compact_threshold: N}]` 且渲染后的输入超过 N 个 token 时，服务端会把较早的上下文裁剪为一个不透明的加密 `compaction` 输出条目。Hermes 将该条目捕获到 assistant 消息现有的回放附属数据中，并在后续轮次中回传，以替代被裁剪的历史——无需客户端摘要即可实现长时程回忆，并且对 ZDR 友好（`store: false`，不使用 `previous_response_id`）。

通过 `compression.codex_responses_native: true` 选择启用。该闸门刻意设计得很窄，并在每次请求时重新检查：

- **模型**：仅限 gpt-5.6 系列。其他模型在请求包含该字段时会在服务端失败（gpt-5.1/5.2 返回 HTTP 500 或使流停滞——没有可据以降级的结构化拒绝，2026 年 8 月实测验证）。
- **路由**：仅限 `api.openai.com`（OpenAI API key）或 ChatGPT Codex 后端（Codex 订阅 OAuth）。xAI、GitHub/Copilot、OpenRouter、中转服务和本地服务器永远不会收到该字段。

压缩的其他方面保持不变：本地压缩器仍作为兜底负责方保持就绪（原生阈值被截取到本地触发点以下约 8K token，以便服务端先压缩），而提供商对该字段的结构化拒绝会为该会话禁用原生压缩，并在不带该字段的情况下重试请求。将会话切换到不符合条件的模型或路由只会停止发送该字段——当端点变化时，已捕获的检查点会被现有的跨签发方保护从回放中剔除。

默认情况下，`compression.codex_responses_compact_threshold: null` 会根据解析后的本地触发点推导原生阈值。例如，本地触发点为 765,000 时选择 756,808。设置一个正整数可保留绝对阈值，例如 200,000。无效值会选择自动行为。如果不存在可用的本地触发点，自动模式使用 200,000。提供商的最小值为 1,024 token，因此处于或低于该下限的异常小的本地触发点无法保证严格的“原生优先”顺序。

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

中间上下文压力警告已被移除（参见 `agent/turn_iteration_prep.py` 中的迭代预算块，其中注明："No intermediate pressure warnings — they caused models to 'give up' prematurely on complex tasks"）。压缩在 prompt token 达到配置的 `compression.threshold`（默认 50%）时触发，无需事先警告步骤；gateway 会话清理作为二级安全网在模型上下文窗口的 85% 处触发。