---
sidebar_position: 7
title: "Mixture of Agents"
description: "创建具名的 MoA 预设，它们会作为可选模型出现在 Mixture of Agents provider 之下"
---

# Mixture of Agents

Mixture of Agents 是一个虚拟模型 provider。每个具名的 MoA 预设都会作为一个可选模型出现在 `moa` provider 之下。

当你选择某个 MoA 预设时，该预设的聚合器（aggregator）就是实际执行的模型。它负责撰写助手回复并发出工具调用。参考模型先行运行，为聚合器提供分析结果。

当一项困难任务需要多种模型视角、但仍需要 Hermes 正常的 Agent 循环——工具调用、后续迭代、中断、对话记录持久化以及与其他消息相同的会话上下文——时，就该使用 MoA。

## 选择 MoA 预设作为你的模型

你可以通过常规的模型选择界面来选择预设：

```bash
/model default --provider moa
/model review --provider moa
```

MoA 预设在 **Hermes 的所有界面**中都可选，因为在模型系统中 MoA 就是一个普通的 provider：

- **CLI / 网关 / TUI 的 `/model`** — `/model <preset> --provider moa`，或用 `/model --provider moa` 选择默认预设。当名称与已配置的预设完全一致时，直接使用 `/model <preset>` 也可以。
- **`hermes model`** 以及**仪表板模型选择器** — 会出现一行 `Mixture of Agents` provider，其模型即你的预设名称。
- **桌面 GUI 应用** — 模型下拉列表中会显示一个 `MoA presets` 分区；选择其中一项（`MoA: <preset>`）会将当前模型切换为该预设。桌面应用的设置面板同样可以创建和编辑预设。

因此，已配置的预设会出现在你挑选任何其他模型的所有位置。

## 斜杠命令快捷方式

`/moa` 是一次性的便捷语法糖。它用**默认** MoA 预设运行单条提示，随后恢复你原先所用的模型：

```bash
/moa design and implement a migration plan for this flaky test cluster
```

Hermes 会为这一轮临时切换到默认 MoA 预设，发送提示，之后再恢复你之前的模型。整个参数都是提示内容——`/moa` 不再将其解释为预设名称。

```bash
/moa
```

不带提示的裸 `/moa` 只会打印用法说明。

如果要在会话余下时间里**切换**到某个 MoA 预设，请从模型选择器中选择它——MoA 预设会在每个模型选择界面中以 `Mixture of Agents` provider 的形式出现（见上文）。`/moa` 有意不做模型切换，这样普通提示就绝不会意外改变你的模型。

## 它在 Agent 循环中如何工作

当选中 `moa` provider 后，对于每次主模型调用，Hermes 会：

1. 按名称解析所选预设；
2. 在不带工具 schema 的情况下运行已配置的参考模型（它们只接收对话中的用户/助手文本——不包含 Hermes 系统提示或工具调用记录——因此参考调用成本低廉，并可避免严格 provider 的拒绝）；
3. 将参考模型的输出作为私有上下文追加给聚合器；
4. 使用正常的 Hermes 工具 schema 调用已配置的聚合器；
5. 将聚合器的响应视为真正的模型响应；
6. 如果聚合器调用了工具，Hermes 会照常执行这些工具；
7. 在下一次模型迭代中，同样的 MoA 流程会基于更新后的对话（包括工具结果）再次运行。

由于 MoA 是通过常规模型系统选择的，它可以自动与 `/goal`、网关会话、TUI 会话以及桌面应用聊天组合使用。

## 配置预设

你可以从以下位置配置具名的 MoA 预设：

- 仪表板 → Models → Model Settings → Mixture of Agents
- 桌面应用 → Settings → Model → Mixture of Agents
- `hermes moa configure [name]`
- `config.yaml`

配置中存储的是显式的 provider/模型对，因此你可以混用多个 provider，也可以使用同一 provider 的多个模型：

```yaml
moa:
  default_preset: default
  presets:
    default:
      reference_models:
        - provider: openai-codex
          model: gpt-5.5
        - provider: openrouter
          model: deepseek/deepseek-v4-pro
      aggregator:
        provider: openrouter
        model: anthropic/claude-opus-4.8
      # 可选：固定采样温度。省略时（默认行为），
      # 不会发送 temperature，各模型使用其 provider 的默认值——
      # 与单模型的 Hermes Agent 行为一致。
      # reference_temperature: 0.6
      # aggregator_temperature: 0.4
      max_tokens: 4096
      enabled: true
```

默认预设：

- 参考模型：`openai-codex:gpt-5.5`
- 参考模型：`openrouter:deepseek/deepseek-v4-pro`
- 聚合器 / 执行模型：`openrouter:anthropic/claude-opus-4.8`

### 用 `reference_max_tokens` 调优顾问速度

每一轮中，MoA 会并行运行参考模型（顾问），然后由聚合器执行。顾问生成是每轮延迟的主要来源——
每轮的实际耗时与顾问输出的 token 数量高度相关，因为该轮需要等待写得最慢的顾问完成。
默认情况下顾问是**不设上限**的（`reference_max_tokens` 未设置），因此它们可能写出长篇大论式的建议。

在预设上设置 `reference_max_tokens` 可以限制顾问输出，让建议更简洁。聚合器只需要每位顾问
判断的要点，因此设置一个上限（例如 `600`）能在几乎不影响质量的前提下明显缩短每轮耗时。
它**只限制顾问**——执行任务的聚合器的输出（即用户可见的答案）永远不会被截断。

```yaml
moa:
  presets:
    fast:
      reference_models:
        - provider: openrouter
          model: anthropic/claude-opus-4.8
        - provider: openrouter
          model: openai/gpt-5.5
      aggregator:
        provider: openrouter
        model: anthropic/claude-opus-4.8
      reference_max_tokens: 600   # 简洁建议 → 更快的轮次
```

保持其未设置（或设为 `0`/留空）即可维持先前的不限量行为。

### 按插槽设置推理强度

参考模型与聚合器插槽也可以设置 `reasoning_effort`。当你希望同一个模型以不同深度参与，或希望
聚合器比作为顾问的参考模型思考得更深入时，可使用此项。有效取值与 Hermes 常规推理控制一致：
`none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max` 和 `ultra`。

```yaml
moa:
  presets:
    deep_review:
      reference_models:
        - provider: openai-codex
          model: gpt-5.6-sol
          reasoning_effort: low
        - provider: openai-codex
          model: gpt-5.6-sol
          reasoning_effort: xhigh
        - provider: xai-oauth
          model: grok-4.5
      aggregator:
        provider: openai-codex
        model: gpt-5.6-sol
        reasoning_effort: high
```

省略 `reasoning_effort` 即对该插槽使用 provider/Hermes 的默认值。

## 终端中的预设管理

```bash
hermes moa list
hermes moa configure              # 更新默认预设
hermes moa configure review       # 创建或更新一个具名预设
hermes moa delete review
```

## 基准测试

在 HermesBench 上，一个双模型 MoA 预设——由 `claude-opus-4.8` 聚合一个 `gpt-5.5` 参考模型——得分高于任一模型单独运行：

| 模型 | HermesBench 得分 |
|---|---|
| **Opus 聚合器（opus-4.8 + gpt-5.5 参考模型）—— MoA** | **0.8202** |
| `anthropic/claude-opus-4.8` | 0.7607 |
| `openai/gpt-5.5` | 0.7412 |

该 MoA 配置比其最强的组成部分（opus-4.8）高出约 6 个百分点，这印证了聚合第二种视角能够在困难任务上提升质量，而不只是把两者取平均。

## 提示缓存

MoA 的设计确保**主对话的提示缓存永远不会被破坏**。选择一个 MoA 预设就是一次普通的模型选择：它不会修改历史上下文、替换工具集，也不会在对话中途重建系统提示。你的对话历史、系统提示和工具 schema 保持逐字节稳定，因此其他模型所依赖的缓存前缀被原样保留，与使用普通模型时完全一致。切换到或切换离开某个 MoA 预设所付出的缓存失效代价，与任何其他 `/model` 切换相同——不多不少。

两类内部调用都能正常缓存：

- **参考模型**收到的是经过裁剪的、确定性的对话视图（剥离了系统提示和工具记录——见上文循环）。由于该视图是稳定历史的稳定函数，参考模型的提示前缀会在各次迭代中重复，因而能正常缓存。参考调用是简短的顾问式调用，不带工具。
- **聚合器**是执行模型。参考模型的输出会作为私有指导追加到最新用户回合的*末尾*。由于这段文本位于尾部——处在整个稳定前缀（系统提示 + 先前历史）之下——它不会使任何缓存前缀失效：聚合器在注入点之上的所有内容都能命中缓存，只有新追加的尾部是新增内容。这与每一次正常轮次的行为完全一致，在正常轮次中每条新用户消息同样是未缓存的尾部 token。

因此，MoA 在这两类调用上都不会牺牲提示缓存。它唯一的实际成本是每次迭代额外的参考调用——你付费购买的是多种模型视角，而不是被破坏的缓存。与 Hermes 其余部分共享的长期对话前缀完好无损。

## 注意事项

- MoA 不再列在 `hermes tools` 之下；也不存在需要启用的 `moa` 工具集。
- 在某个预设上设置 `enabled: false` 会禁用该预设的参考模型扇出：聚合器将单独执行，效果完全等同于你把它选作普通模型。这就是仪表板和桌面设置中暴露的按预设开关。
- 某个预设的聚合器不能是另一个 MoA 预设。递归的 MoA 树被有意禁止。
- 某个参考模型的凭据失败不会中断该轮次。Hermes 会把失败信息纳入参考上下文，并使用已返回结果的模型继续执行。
- MoA 会增加模型调用次数。单次模型迭代可能包含多次参考调用外加一次聚合器调用。
