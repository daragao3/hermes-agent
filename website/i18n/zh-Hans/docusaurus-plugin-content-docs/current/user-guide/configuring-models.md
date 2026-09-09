---
sidebar_position: 3
---

# 配置模型

Hermes 使用两类模型槽位：

- **主模型** — agent 的思考核心。每条用户消息、每个工具调用循环、每次流式响应都经由该模型处理。
- **辅助模型** — agent 卸载给较小模型的边缘任务。包括上下文压缩、视觉（图像分析）、网页摘要、审批评分、MCP 工具路由、会话标题生成和技能搜索。每项任务有独立槽位，可单独覆盖。

本页介绍如何通过仪表板配置上述两类模型。如需使用配置文件或 CLI，请跳至底部的[其他方法](#alternative-methods)。

:::tip 最快路径：Nous Portal
[Nous Portal](/user-guide/features/tool-gateway) 在单一订阅下提供 300+ 个模型。全新安装后，运行 `hermes setup --portal` 即可登录并一键将 Nous 设为提供商。使用 `hermes portal info` 查看当前配置。

- Portal 订阅者还可享受**按 token 计费的提供商 9 折优惠**。
:::

:::note `model:` 的 schema——空字符串还是映射
全新安装时，随附的默认配置中 `model: ""`（一个空字符串哨兵值，表示"尚未配置"）。当你第一次运行 `hermes setup` 或 `hermes model` 时，该键会被就地升级为一个映射，包含 `provider`、`default`、`base_url` 和 `api_mode` 子键——也就是本页以及 [`profiles.md`](./profiles.md) / [`configuration.md`](./configuration.md) 中通篇展示的结构。如果你在 `config.yaml` 中看到空字符串，运行 `hermes model`（或在仪表板中点击 **Change**），Hermes 就会为你写入字典形式。
:::

## Models 页面

打开仪表板，点击侧边栏中的 **Models**。页面分为两个区域：

1. **Model Settings** — 顶部面板，用于为各槽位分配模型。
2. **使用分析** — 按排名显示所选时间段内运行过会话的所有模型，包含 token 数量、费用和能力标签。

![Models 页面概览](/img/docs/dashboard-models/overview.png)

顶部卡片为 **Model Settings** 面板。主行始终显示 agent 将为新会话启动的模型。点击 **Change** 打开选择器。

## 设置主模型

点击主模型行上的 **Change**：

![模型选择器对话框](/img/docs/dashboard-models/picker-dialog.png)

选择器分为两列：

- **左列** — 已认证的提供商。仅显示已配置的提供商（已设置 API key、完成 OAuth 或定义了自定义端点）。若某提供商未出现，请前往 **Keys** 添加凭据。
- **右列** — 所选提供商的精选模型列表。这些是 Hermes 针对该提供商推荐的 agentic 模型，而非原始的 `/models` 接口返回结果（OpenRouter 的原始列表包含 400+ 个模型，涵盖 TTS、图像生成器和重排序器）。

在过滤框中输入提供商名称、slug 或模型 ID 进行筛选。

选择模型后点击 **Switch**，Hermes 会将其写入 `~/.hermes/config.yaml` 的 `model` 部分。**此操作仅对新会话生效** — 已打开的聊天标签页将继续使用启动时的模型。如需在当前聊天中热切换，请在聊天内使用 `/model` 斜杠命令。

### 会话中途切换与上下文警告

当你在**活跃会话内部**切换模型（Herm TUI 模型选择器、`hermes` CLI，或 Telegram/Discord 上的 `/model`）时，Hermes 会估算你的**下一条消息**是否会针对新模型的上下文窗口触发**预检上下文压缩**。如果该会话已经接近或超过该模型的压缩阈值（参见[上下文压缩](./configuration.md#context-compression)），切换的回复中会包含一条警告——与昂贵模型提示使用的是同一条 `warning_message` 路径。切换仍会立即生效；压缩会在**切换之后的第一条用户消息**上运行，先于模型作答。

:::warning 会话中途切换会重置 prompt 缓存
prompt（提示词）缓存以处理该请求的模型为键，因此任何在对话中途更换模型的操作——显式的 `/model` 切换、[自动回退](./features/fallback-providers.md)，或是[凭证池](./features/credential-pools.md)轮换到另一个账号——都意味着下一条消息会以完整输入 token 价格重新读取整段对话，而不是享受缓存价（约 75–90% 折扣）。在长会话中，这一次性的重读开销可能远大于两个模型之间的单 token 价差。需要切换时就切换，但最好在对话早期或刚开始新会话时进行。
:::

## 设置辅助模型

点击 **Show auxiliary** 展开 11 个任务槽位：

![辅助面板展开状态](/img/docs/dashboard-models/auxiliary-expanded.png)

每个辅助任务默认为 `auto`，即 Hermes 对该任务也会先尝试你的主模型。如果该路由不可用或遇到容量类失败，`auto` 会依次尝试该任务专属的 `auxiliary.<task>.fallback_chain`，然后是主链 `fallback_providers` / `fallback_model`，最后才是 Hermes 内置的辅助任务发现链。当某个边缘任务需要更便宜或更快的模型时，可单独覆盖该槽位。

### 常见覆盖模式

| 任务 | 何时覆盖 |
|---|---|
| **Title Gen（标题生成）** | 几乎总是。$0.10/M 的 flash 模型生成会话标题的效果与 Opus 相当。默认配置在 OpenRouter 上将此项设为 `google/gemini-3-flash-preview`。 |
| **Vision（视觉）** | 当主模型不支持视觉时。将其指向 `google/gemini-2.5-flash` 或 `gpt-4o-mini`。 |
| **Compression（压缩）** | 当你在用 Opus/M2.7 的推理 token 来摘要上下文时。快速聊天模型以 1/50 的成本即可完成此工作。 |
| **Approval（审批）** | 用于 `approval_mode: smart` — 由快速/廉价模型（haiku、flash、gpt-5-mini）决定是否自动批准低风险命令。此处使用昂贵模型是浪费。 |
| **Web Extract（网页提取）** | 当你大量使用 `web_extract` 时。逻辑同压缩 — 摘要任务不需要推理能力。 |
| **Skills Hub（技能中心）** | `hermes skills search` 使用此槽位。通常保持 `auto` 即可。 |
| **MCP** | MCP 工具路由。通常保持 `auto` 即可。 |

### 单任务覆盖

点击任意辅助行上的 **Change**，打开相同的选择器，操作方式相同 — 选择提供商和模型，点击 Switch。该行将从 `auto (use main model)` 更新为 `provider · model`。

### 全部重置为 auto

如果调整过度想重新开始，点击辅助区域顶部的 **Reset all to auto**。所有槽位将恢复使用主模型。

## "Use as" 快捷方式

页面上每张模型卡片都有 **Use as** 下拉菜单。这是快捷路径 — 从分析数据中选择一个模型，点击 **Use as**，一键将其分配到主槽位或任意辅助任务：

![Use as 下拉菜单](/img/docs/dashboard-models/use-as-dropdown.png)

下拉菜单包含：

- **Main model** — 与点击主行上的 Change 效果相同。
- **All auxiliary tasks** — 将此模型分配给全部 11 个辅助槽位。适合将所有边缘任务统一切换到廉价 flash 模型的场景。
- **单项任务选项** — Vision、Web Extract、Compression 等。每项任务当前分配的模型标记为 `current`。

当模型卡片当前已分配到某个槽位时，会显示 `main` 或 `aux · <task>` 标签，方便一眼看出历史模型的使用情况。

## 写入 `config.yaml` 的内容

通过仪表板保存时，Hermes 写入 `~/.hermes/config.yaml`：

**主模型：**
```yaml
model:
  provider: openrouter
  default: anthropic/claude-opus-4.7
  base_url: ''        # cleared on provider switch
  api_mode: chat_completions
```

**辅助覆盖示例（视觉任务使用 gemini-flash）：**
```yaml
auxiliary:
  vision:
    provider: openrouter
    model: google/gemini-2.5-flash
    base_url: ''
    api_key: ''
    timeout: 120
    extra_body: {}
    download_timeout: 30
```

**辅助任务处于 auto（默认）：**
```yaml
auxiliary:
  compression:
    provider: auto
    model: ''
    base_url: ''
    # ... other fields unchanged
```

`provider: auto` 加 `model: ''` 表示 Hermes 对该任务使用主模型；同时，当主路由无法承接该辅助调用时，仍会遵循回退策略。

可选的按任务回退链位于同一个辅助任务之下：

```yaml
auxiliary:
  title_generation:
    provider: auto
    model: ''
    fallback_chain:
      - provider: openrouter
        model: inclusionai/ring-2.6-1t:free
```

当不存在 `fallback_chain` 时，`auto` 会先使用顶层的 `fallback_providers` 链，然后才使用内置的辅助任务发现链。

## 何时生效？

- **CLI**（`hermes chat`）：下次执行 `hermes chat` 时生效。
- **Gateway**（Telegram、Discord、Slack 等）：下一个*新*会话生效。现有会话保持原有模型。如需强制所有会话使用新配置，重启 gateway（`hermes gateway restart`）。
- **仪表板聊天标签页**（`/chat`）：下一个新 PTY 生效。当前打开的聊天保持原有模型 — 在聊天内使用 `/model` 进行热切换。

更改不会使运行中会话的 prompt 缓存失效。这是有意为之：在会话内切换主模型需要重置缓存（系统 prompt 包含模型特定内容），该操作保留给聊天内的显式 `/model` 斜杠命令。

## 故障排查

### 选择器中显示"No authenticated providers"

Hermes 仅列出具有有效凭据的提供商。检查侧边栏中的 **Keys** — 应存在以下之一：API key、成功的 OAuth 或自定义端点 URL。若所需提供商不在列表中，运行 `hermes setup` 进行配置，或前往 **Keys** 添加环境变量。

### 主模型在运行中的聊天里未发生变化

符合预期。仪表板写入 `config.yaml`，新会话读取该文件。当前打开的聊天是一个活跃的 agent 进程 — 它保持启动时的模型。在聊天内使用 `/model <name>` 对该会话进行热切换。

### 辅助覆盖"未生效"

检查以下三点：

1. **是否启动了新会话？** 现有聊天不会重新读取配置。
2. **`provider` 是否设置为非 `auto` 的值？** 若字段显示 `auto`，该任务仍在使用主模型。点击 **Change** 选择实际的提供商。
3. **提供商是否已认证？** 若将 `minimax` 分配给某任务但没有 MiniMax API key，该任务将回退到 openrouter 默认值，并在 `agent.log` 中记录警告。

### 我选择了模型，但 Hermes 切换了提供商

在 OpenRouter（或任何聚合器）上，裸模型名称会优先在聚合器内解析。因此 OpenRouter 上的 `claude-sonnet-4` 会解析为 `anthropic/claude-sonnet-4.6`，保持在你的 OpenRouter 认证下。但若在原生 Anthropic 认证下输入 `claude-sonnet-4`，则会保持为 `claude-sonnet-4-6`。若出现意外的提供商切换，请确认当前提供商是否符合预期 — 选择器始终在对话框顶部显示当前主模型。

## 其他方法 {#alternative-methods}

### CLI 斜杠命令

在任意 `hermes chat` 会话内：

```
/model gpt-5.4 --provider openrouter             # 仅当前会话
/model gpt-5.4 --provider openrouter --global    # 同时持久化到 config.yaml
/model claude-opus-4.6 --once                    # 仅下一轮次生效，之后自动恢复
```

`--global` 与仪表板 **Change** 按钮效果相同，并额外在当前会话内原地切换模型。

`--once` 只为一个轮次切换模型，之后恢复到先前的模型——无论该轮次成功、报错还是被中断。它不会持久化任何内容：如果 gateway 在轮次中途重启，恢复后仍使用原模型。适合把某个难题临时升级到昂贵模型（"就这一次问问 Opus"），或者为一次性查询降级到便宜模型。

:::note prompt 缓存成本
一次性切换会两次打断提供商的 prompt（提示词）缓存前缀（切出和切回各一次）。在使用缓存前缀的提供商（Anthropic、OpenAI）上进行长会话时，下一轮次要重新支付完整的输入成本——`--once` 适合短会话或从便宜模型升级到昂贵模型的场景，但在一个漫长而昂贵的会话中插入一个简短的旁支问题，可能得不偿失。
:::

### 自定义别名

为常用模型定义短名称，然后在 CLI 或任意消息平台中使用 `/model <alias>`。有两种等价的格式——选择适合你工作流的一种。

**标准形式（顶层 `model_aliases:`）**——可完整控制 provider 与 base_url：

```yaml
# ~/.hermes/config.yaml
model_aliases:
  fav:
    model: claude-sonnet-4.6
    provider: anthropic
  grok:
    model: grok-4
    provider: x-ai
```

**短字符串形式（`model.aliases.<name>: provider/model`）**——从 shell 使用很方便，因为 `hermes config set` 只写入标量值，但它无法携带自定义的 `base_url`：

```bash
hermes config set model.aliases.fav anthropic/claude-opus-4.6
hermes config set model.aliases.grok x-ai/grok-4
```

两种路径都进入同一个加载器（`hermes_cli/model_switch.py`）。在 `model_aliases:` 中声明的条目优先于同名的 `model.aliases:` 条目。

然后在聊天中使用 `/model fav` 或 `/model grok`。用户别名会覆盖内置短名称（`sonnet`、`kimi`、`opus` 等）。完整参考请见[自定义模型别名](/reference/slash-commands#custom-model-aliases)。

### `hermes model` 子命令

```bash
hermes model            # 交互式提供商 + 模型选择器（切换默认值的标准方式）
```

`hermes model` 引导你选择提供商、完成认证（OAuth 流程会打开浏览器；API key 提供商会提示输入密钥），然后从该提供商的精选目录中选择具体模型。选择结果写入 `~/.hermes/config.yaml` 的 `model.provider` 和 `model.default` 字段。

如需在不启动选择器的情况下列出提供商/模型，请使用仪表板或下方的 REST 端点。查看 CLI 当前实际使用的配置：`hermes config get model --json` 和 `hermes status`。

### 直接编辑配置文件

编辑 `~/.hermes/config.yaml` 后重启相关服务。完整 schema 请见[配置参考](./configuration.md)。

### REST API

仪表板使用以下三个端点，可用于脚本化操作：

```bash
# 列出已认证的提供商及精选模型列表
curl -H "X-Hermes-Session-Token: $TOKEN" http://localhost:PORT/api/model/options

# 读取当前主模型及辅助任务分配
curl -H "X-Hermes-Session-Token: $TOKEN" http://localhost:PORT/api/model/auxiliary

# 设置主模型
curl -X POST -H "Content-Type: application/json" -H "X-Hermes-Session-Token: $TOKEN" \
  -d '{"scope":"main","provider":"openrouter","model":"anthropic/claude-opus-4.7"}' \
  http://localhost:PORT/api/model/set

# 覆盖单个辅助任务
curl -X POST -H "Content-Type: application/json" -H "X-Hermes-Session-Token: $TOKEN" \
  -d '{"scope":"auxiliary","task":"vision","provider":"openrouter","model":"google/gemini-2.5-flash"}' \
  http://localhost:PORT/api/model/set

# 将一个模型分配给所有辅助任务
curl -X POST -H "Content-Type: application/json" -H "X-Hermes-Session-Token: $TOKEN" \
  -d '{"scope":"auxiliary","task":"","provider":"openrouter","model":"google/gemini-2.5-flash"}' \
  http://localhost:PORT/api/model/set

# 将所有辅助任务重置为 auto
curl -X POST -H "Content-Type: application/json" -H "X-Hermes-Session-Token: $TOKEN" \
  -d '{"scope":"auxiliary","task":"__reset__","provider":"","model":""}' \
  http://localhost:PORT/api/model/set
```

session token 在启动时注入仪表板 HTML，每次服务器重启后轮换。如需对运行中的仪表板编写脚本，可从浏览器开发者工具中获取（`window.__HERMES_SESSION_TOKEN__`）。