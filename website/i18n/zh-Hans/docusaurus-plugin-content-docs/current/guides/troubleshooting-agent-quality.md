---
sidebar_position: 27
title: "故障排查：“我的 Agent 变笨了”"
description: "当 Hermes 看起来不如以前能干，或在会话中途忘事时的诊断清单——模型切换、上下文压力、上下文长度检测错误，以及冻结的记忆快照"
---

# 故障排查：“我的 Agent 变笨了” {#troubleshooting-my-agent-feels-dumber}

有时 Hermes 看起来没有昨天那么敏锐，或者忘了你二十分钟前告诉它的事情。这几乎从来都不神秘——通常存在一个具体、可检查的原因。请按顺序逐项排查这份清单：各步骤按照它们成为真正答案的频率排序。

## 1. 检查会话实际使用的是哪个模型 {#1-check-which-model-the-session-is-actually-using}

**症状：** 回答变浅了，代码质量下降，推理感觉不对——而且是全面性的。

**检查：** 不带参数运行 `/model` 以显示当前模型，或运行 `/status` 在一个视图中查看会话的模型、provider 和 profile。

**含义：** 切换模型就意味着能力变化，而且你很容易在不知不觉中用上了与预想不同的模型：

- 普通的 `/model <name>` 切换默认**仅作用于当前会话**（除非设置了 `model.persist_switch_by_default: true`），因此你当前使用的模型可能与 `config.yaml` 中的不一致。
- 在仪表板的 Models 页面更改主模型只对**新会话**生效——已经打开的聊天会继续使用它启动时的模型。
- 如果你为简单任务切换到了更快的模型（[技巧与最佳实践](/guides/tips#choose-the-right-model) 推荐的做法），记得在进行复杂推理工作时切换回来。

如果模型不对，`/model <name>` 可以为当前会话修正它；加上 `--global` 可将更改持久化到 `config.yaml`。注意，会话中途切换会重置 prompt 缓存，因此下一轮会以完整输入价格重新读取整个对话——在长会话中，直接用正确的模型开启新会话可能更便宜。

## 2. 检查上下文使用情况 {#2-check-context-usage}

**症状：** 会话开始时表现很好，但响应越来越慢、被截断，或者丢失了前面的细节。

**检查：** 运行 `/usage` 查看 token 使用量和上下文窗口状态，或运行 `/context` 以可视化方式查看窗口被哪些内容占用（系统 prompt、工具定义、skill、记忆、对话）以及剩余空间。

**含义：** 长时间的对话会不断累积消息和工具输出，逐渐逼近上下文上限。当你在长会话中注意到表现下降时：

```bash
# Compress the conversation (summarizes history, preserves key context)
/compress

# Or start a fresh session
/new
```

`/compress` 会对对话历史进行摘要，在保留关键上下文的同时大幅减少 token 数量。`/compress here [N]` 会原样保留最近的 N 轮交流并对其余部分进行摘要，而聚焦主题（`/compress focus <topic>`）可以收窄完整摘要所保留的内容。

:::tip
在长会话中定期使用 `/compress`，而不是等到出问题再用；并定期使用 `/usage` 了解当前状况。
:::

## 3. 核实检测到的上下文长度 {#3-verify-the-detected-context-length}

**症状：** 上下文问题出现得出奇地早——第一次长对话就已触及上限，或者压缩触发的时间远早于模型宣称的窗口大小所应允许的时间。

**检查：** 查看 CLI 启动行——它会显示检测到的上下文长度（例如 `📊 Context limit: 128000 tokens`）。你也可以在会话中通过 `/usage` 查看。

**含义：** Hermes 可能为你的模型自动检测到了错误的上下文长度。请显式设置它：

```yaml
# In ~/.hermes/config.yaml
model:
  default: your-model-name
  context_length: 131072  # your model's actual context window
```

或者对于自定义端点，在 provider 条目上按模型设置：

```yaml
providers:
  my-server:
    api: "http://localhost:11434/v1"
    models:
      qwen3.5:27b:
        context_length: 64000
```

Ollama 用户：如果你设置了自定义的 `num_ctx`，请在 Hermes 中设置相匹配的上下文长度——Ollama 的 `/api/show` 报告的是模型的*最大*上下文，而不是你配置的实际生效的 `num_ctx`。在运行中的 gateway 上，对 `model.context_length` 或任何 `compression.*` 键的修改会在下一条消息时生效——无需重启。

自动检测的工作原理以及所有覆盖选项，请参阅[上下文长度检测](/integrations/providers#context-length-detection)。

## 4. “我告诉过它，它却忘了”——冻结的记忆快照 {#4-i-told-it-something-and-it-forgot--the-frozen-memory-snapshot}

**症状：** 你在本次会话中让 Hermes 记住某件事，它确认已保存，但在*同一*会话的稍后阶段，它似乎并不知道这件事。

**检查：** 没有任何东西坏掉——检查一下时间点。会话中途保存的记忆会立即写入磁盘，但系统 prompt 要到下一次会话才会反映出来。

**含义：** 这是有文档记载的、有意为之的行为。记忆以**会话开始时的冻结快照**形式注入系统 prompt，并且这一注入在会话中途永远不会改变——这是为了保留 LLM 的前缀缓存以提升性能。当 agent 在会话中添加或删除记忆条目时，更改会立即持久化到磁盘，但只有在下一次会话开始时才会出现在系统 prompt 中。工具响应始终显示实时状态，因此保存本身是经过确认且真实有效的。

:::info
冻结快照的实际含义：在会话中说“记住 X”，意味着 X 保证在**下一次**会话中可用。在当前会话中，这一事实仍存在于对话历史本身之中——只有当那部分对话随后被压缩掉时，agent 才会忘记它（见第 7 步）。
:::

完整机制请参阅[持久记忆](/user-guide/features/memory#how-memory-appears-in-the-system-prompt)。

## 5. 记忆是有上限且经过整理的——不是对话记录 {#5-memory-is-bounded-and-curated--not-a-transcript}

**症状：** Hermes 记不起上周某次会话中的一个细节，尽管你们当时详细讨论过。

**检查：** 记忆容量和内容。系统 prompt 中的记忆标题会显示使用量（例如 `[67% — 1,474/2,200 chars]`），而 `hermes journey list` 会列出每一条已保存的记忆条目和 skill。

**含义：** 持久记忆被有意设置了上限——MEMORY.md 为 2,200 个字符（约 800 个 token），USER.md 为 1,375 个字符（约 500 个 token）。它保存的是经过整理的关键事实，而不是对话记录。值得保存的是偏好、环境事实、约定和纠正；原始的讨论细节按设计不会存放在那里。

对于“我们上周讨论过 X 吗？”这类回忆，agent 有一个独立的机制：`session_search` 会查询所有过去的会话（存储在带全文搜索的 SQLite 中），即使内容不在活动记忆中，也能找到几周前讨论过的事情。直接问就行——“在我们过去的会话里搜索关于部署的讨论。”

你也可以直接提供帮助：在一次高效的会话之后说“下次记住这个”，或者在记忆接近容量上限时说“清理一下你的记忆”，让 agent 合并条目。请参阅[记忆与 Skill 技巧](/guides/tips#memory--skills)和[容量管理](/user-guide/features/memory#capacity-management)。

## 6. 检查 skill 和工具是否已加载 {#6-check-that-skills-and-tools-are-loaded}

**症状：** Hermes 以前能熟练地处理某个特定工作流，现在却处理得很生疏，或者说它做不了以前做过的事。

**检查：**

- `/skills` —— 浏览已安装的 skill（agent 依赖的某个 skill 可能已被移除）。
- `/reload-skills` —— 重新扫描 `~/.hermes/skills/`，查找新安装或已移除的 skill。
- `/tools list` —— 查看可用工具；之前用 `/tools disable` 禁用的工具在本次会话中会一直不在 agent 的工具集中。
- `/context all` —— 按 skill 和按工具集列出开销，同时也可作为实际已加载内容的清单。

**含义：** Skill 是 agent 的程序性知识——多步骤工作流和特定工具的使用说明。如果某个 skill 缺失，或者工具集被裁剪了（例如，为了减轻 prompt 负担而用 `hermes chat -t "terminal"` 启动的会话），agent 在该会话中能用的东西确实更少。用 `/tools enable` 重新启用工具，或者按名称显式调用该 skill（`/github-pr-workflow`）以确认它能被加载。

## 7. 压缩的副作用 {#7-compression-side-effects}

**症状：** 在一次长会话之后（或者刚运行完 `/compress`），Hermes 记得大致内容，但丢失了对话早期的细节。

**检查：** 压缩是否已触发——在消息平台上，`/usage` 和 `/context` 会显示压缩统计和上下文状态，而手动运行的 `/compress` 总会报告其结果。

**含义：** 压缩会用摘要替换较早的对话历史——这正是它的目的，而且它必然以细节换取空间。了解它的形态：

- 最近的消息受到保护：默认情况下，最后 20 条消息保持不压缩（`protect_last_n`），开头的交流会被固定（`protect_first_n: 3`），从而让最初的目标始终可见。
- 压缩是非破坏性的：在默认的 `compression.in_place: true` 下，会话保持同一个持久 id，压缩前的轮次会被软归档——仍然可以通过 `session_search` 搜索并恢复，而不是被删除。
- 当 `in_place: false`（旧版行为）时，每次压缩都会轮换到一个**链接到旧会话的新会话**——带标题的会话会变成 `"my project" → "my project #2" → "my project #3"`。如果你按标题恢复，`hermes -c "my project"` 会自动选择最新的变体。
- 聚焦主题可以收窄完整摘要所保留的内容：`/compress focus auth-refactor` 会保留该主线的细节，代价是牺牲其余部分。

如果某个被压缩掉的细节很重要，请让 agent 去搜索它（`session_search` 能访问已归档的轮次），或者把关键事实重新粘贴到对话中。

完整的设置参考请参阅[上下文压缩](/user-guide/configuration#context-compression)，带标题的会话如何串联请参阅[压缩时的自动沿袭](/user-guide/sessions#auto-lineage-on-compression)。

---

## 速查表 {#quick-reference}

| 症状 | 首个命令 | 可能原因 |
|---------|--------------|--------------|
| 一切都感觉不如以前能干 | `/model` | 会话使用的模型与你以为的不同 |
| 长会话表现下降 | `/usage` | 上下文压力——压缩或开启新会话 |
| 出奇地早就触及上限 | CLI 启动行 / `/usage` | 自动检测到的上下文长度错误 |
| 忘了我在本次会话中说过的话 | ——（按设计如此） | 冻结的记忆快照——下次会话才会出现 |
| 忘了上周的讨论 | 让它使用 `session_search` | 记忆有上限，只保存整理过的事实 |
| 失去了某项特定能力 | `/skills`、`/tools list` | 本次会话未加载相应 skill 或工具集 |
| 长会话后丢失了早期细节 | `/usage`、`/context` | 压缩对较早的历史进行了摘要 |
