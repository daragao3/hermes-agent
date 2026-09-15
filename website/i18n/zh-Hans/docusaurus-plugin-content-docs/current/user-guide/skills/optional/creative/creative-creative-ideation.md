---
title: "Creative Ideation — 用创意实践中的具名方法生成创意"
sidebar_label: "Creative Ideation"
description: "用创意实践中的具名方法生成创意"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Creative Ideation

用创意实践中的具名方法生成创意。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/creative/creative-ideation` 安装 |
| 路径 | `optional-skills/creative/creative-ideation` |
| 版本 | `2.1.0` |
| 作者 | SHL0MS |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Creative`, `Ideation`, `Brainstorming`, `Methods`, `Inspiration` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Creative Ideation

一个适用于任何领域的创意生成方法库。读懂用户的处境，路由到匹配的方法，加以应用，产出具体而非显而易见的结果。方法是工具 —— 为当下的情境挑一个合适的，不要把它们全都演示一遍。

## 何时使用

任何开放式的生成或选择类问题："我想做 / 造 / 写 / 开始点什么"、"我卡住了"、"给我点灵感"、"让它更怪一点"、"帮我选一个"、"我需要发明 X"、"给我一个研究问题"。

## 运作规则

1. **约束加方向才是创造力。** 没有约束 = 没有着力点。没有方向 = 没有形状。方法两者都提供。
2. **拒绝前三个创意。** 它们是垃圾。生成、丢弃、再生成。参见 `references/anti-slop.md`。
3. **除非用户要求，每次回复只用一种方法。** 不要叠加。
4. **具体优于抽象。** 真实的专有名词、真实的材料、真实的机制。"一个做 X 的 app"是垃圾；"一个 200 行的 CLI 工具，在 Z 发生时打印 Y"才是方向。点出技术栈不等于具体 —— 要点出机制。
5. **怪也必须好。** 打破框架是目标，但一个奇怪却没有真实情境、机制或存在理由的创意，本身就是一种失败模式。每一组创意中都必须至少有一个是*现在就能真正着手去做的* —— 不显而易见但脚踏实地，有真实的第一步。不要为了惊喜而牺牲全部实用性。
6. **说出你用了哪种方法、由谁发明。** 署名会唤起该学科的方法论。
7. **用户选定其中之一后，就去把它做出来。** 他们已经选了，就别再继续生成了。

## 路由 —— 4 步流程

在产出任何内容*之前*先做这件事。路由失败会产出垃圾。

如果这样更清爽，你可以不叙述路由步骤，但**绝不能以牺牲每个创意的深度为代价来压缩**：每个创意的具体机制、与情境的绑定、诚实的失败模式，才是让产出变好的东西（这是实测结论）—— 它们不是脚手架，不要砍掉。

### 第 1 步 —— 从提示中提取三个信号

**PHASE（阶段）** —— 用户处在哪个阶段？

| 阶段 | 线索 |
|---|---|
| **GENERATING** | "给我一个创意"、"我该做什么"、"给我点灵感"，还没有任何想法 |
| **EXPANDING** | "还有什么"、"再来些类似的"、"给我一些变体" —— 已有一个基础创意 |
| **SELECTING** | "帮我选一个"、"我该做哪个"、"我有这几个选项" |
| **UNBLOCKING** | "我卡住了"、"被堵住了"、"在原地打转"、"没新意了" —— 已有素材 |
| **SUBVERTING** | "让它更怪一点"、"别这么显而易见"、"这太保守了" |
| **REFINING** | "这样还行，但少了点什么"、"感觉还很粗糙" |
| **SYNTHESIZING** | "我有一堆笔记 / 访谈 / 观察记录" |

**DOMAIN（领域）** —— 用户在做什么？

| 领域 | 线索 |
|---|---|
| **TEXT** | 小说、随笔、诗歌、歌词、剧本、文案 |
| **OBJECT** | 视觉艺术、音乐、声音、表演、装置、雕塑 |
| **ARTIFACT** | 软件、硬件、机构装置、设备 |
| **SYSTEM** | 组织、公共事务、制度、生态、社区 |
| **SELF** | 人生决策、职业、个人实践 |
| **RESEARCH** | 论文、学位论文、学术问题 |
| **PRODUCT** | 商业、市场、服务 |

**SPECIFICITY（具体度）** —— 提示中包含多少约束？

| 级别 | 线索 |
|---|---|
| **NONE** | "我好无聊"、"给我点灵感" —— 没有领域，没有项目 |
| **DOMAIN** | "我想写点东西" —— 知道领域，没有项目 |
| **PROJECT** | "我正在做这个具体的 X" |
| **PROBLEM** | "我在 X 里遇到了这个具体的摩擦点" |

### 第 2 步 —— 应用覆盖规则（最高优先级，先触发）

覆盖规则优先于路由表：

- **情绪信号** —— 用户说"怪"、"奇特"、"出人意料"、"别那么显而易见"、"更有意思一点" → 无论领域为何，都走 `references/methods/lateral-provocations.md` 或 `references/methods/pataphysics.md`。
- **用户点名了某个方法** —— 就用它。
- **用户询问方法推荐**（"该用哪种方法"）→ 给出 2–3 个候选，每个一句话说明，再问用哪个。不要默默地取默认值。
- **高垃圾密度地带** —— "AI 创意"、"创业点子"、"习惯追踪器"、"生产力 / 健康 / 健身 / 美食 / 旅行 app" → 强制使用 `references/methods/lateral-provocations.md` 或 `references/methods/pataphysics.md`，而不是那个显而易见的方法。要拒绝前 **5** 个创意，而不是 3 个。

### 第 3 步 —— 先按阶段路由，再按领域路由

**按阶段（与领域无关）：**

| 阶段 | 默认路由 |
|---|---|
| GENERATING + SPECIFICITY=NONE | `references/full-prompt-library.md` 的 **General** 一节（约束派发） |
| GENERATING + 领域已知 | 按领域路由（见下表） |
| EXPANDING | `references/methods/scamper.md` |
| SELECTING | `references/methods/premortem-and-inversion.md`（或用 `references/methods/compression-progress.md` 看上行空间） |
| UNBLOCKING | `references/methods/oblique-strategies.md` |
| SUBVERTING | `references/methods/lateral-provocations.md`（备选 `references/methods/pataphysics.md`） |
| REFINING（文本） | `references/methods/defamiliarization.md` |
| REFINING（其他） | `references/methods/creative-discipline.md`（Tharp 的"脊柱"法） |
| SYNTHESIZING | `references/methods/affinity-diagrams.md` |
| 需要快速上量 | `references/methods/volume-generation.md` |

**按领域（GENERATING 且领域已知时）：**

| 领域 | 默认路由 |
|---|---|
| TEXT —— 形式 / 诗歌 | `references/methods/oulipo.md` |
| TEXT —— 叙事 | `references/methods/story-skeletons.md` |
| TEXT —— 有可再创作的素材 | `references/methods/chance-and-remix.md` |
| OBJECT（音乐、视觉、表演） | `references/methods/oblique-strategies.md` |
| OBJECT —— 实体创作者 / 需要一个起始约束 | `references/full-prompt-library.md` 的 **Physical / object** 一节 |
| ARTIFACT —— 需要一个起始约束 | `references/full-prompt-library.md` 的 **Software / artifact** 一节 |
| ARTIFACT —— 存在参数冲突的工程发明 | `references/methods/triz-principles.md` |
| ARTIFACT —— 软件架构 | `references/methods/pattern-languages.md` |
| ARTIFACT —— 有自然界的对应类比 | `references/methods/biomimicry.md` |
| ARTIFACT —— 有一堆待质疑的既有假设 | `references/methods/first-principles.md` |
| SYSTEM（公共事务、组织、制度） | `references/methods/leverage-points.md` |
| SYSTEM —— 集体 / 参与式 | `references/full-prompt-library.md` 的 **Social / collective** 一节 |
| SELF（人生、职业、学什么） | `references/methods/derive-and-mapping.md` |
| RESEARCH —— 挑选问题 | `references/methods/compression-progress.md` |
| RESEARCH —— 攻克已知问题 | `references/methods/polya.md` |
| PRODUCT（商业、服务） | `references/methods/jobs-to-be-done.md` |
| 需要打破框架 / 寻找类比 | `references/methods/analogy-and-blending.md` |

### 第 4 步 —— 处理歧义与矛盾

- **多条路径都说得通** → 选最贴近用户实际措辞的那条。不要为了显得高明而挑最有意思的方法。
- **确实有歧义** → 问一个澄清问题，不要默默猜测。例如：*"你是在生成创意，还是在已有的几个里做选择？"* / *"这是给小说、随笔，还是别的什么？"*
- **信号相互矛盾**（例如"怪一点的创业点子" → 产品领域 + 求怪的情绪）→ **明确地叠加两种方法**。说明你在做什么：*"用 `jobs-to-be-done` 搭产品框架 + 用 `lateral-provocations` 打破显而易见的形状。"*
- **没有匹配项** → 约束派发（`references/full-prompt-library.md`）是安全的兜底。
- **同一个问题再次被问到** → 换方法。方法有变化 = 创意分布有变化。

### 反默认检查（生成前执行）

- 正准备写"这里有 5 个创意："或一个光秃秃的编号列表？→ 停。先挑一个方法。
- 正准备退回到通用的 LLM 式头脑风暴？→ 停。从上面选一条路径。
- 产出看起来像一个没做路由的 LLM 会写的东西？→ 路由失败，重来。

默认的 LLM 模式正是这个 skill 要取代的东西。如果你不做路由就开始生成，就等于废掉了这个 skill。

更细的边界情况（情绪信号、方法叠加、反模式）见 `references/heuristics.md`。

## 输出格式

约束派发这条默认路径：

```
## Constraint: [Name] — from [Source]
> [The constraint, one sentence]

### Ideas

1. **[One-line pitch]**
   [2-3 sentences — what specifically is made, why it's interesting]
   ⏱ [weekend/week/month]  •  🔧 [stack/medium/materials]

2. ...
3. ...
```

其他方法请使用该方法自身规定的格式（TRIZ 产出的是矛盾分析；OuLiPo 产出的是受约束的文本；Oblique Strategies 产出的是一张被应用的卡片 → 下一步动作）。不要把每种方法都硬塞进约束模板。

**无论用哪种方法，每一组创意都必须：**
- 说出所用的方法。在垃圾密度高的地带，还要说出你拒绝了哪些显而易见的创意。
- 为每个创意给出具体机制，以及诚实的失败模式 / 取舍 / 适合谁。这种深度才是让创意落地的东西 —— 这是实测结论，不是装饰。
- 至少把一个创意标记为 **grounded（脚踏实地）** 的那一个 —— 现在就能着手去做，不显而易见但有真实的第一步。其余的可以走得更远、更怪；这一个必须真正可行。别让整组创意都是怪而不切实际的。

## 文件地图

- `references/full-prompt-library.md` —— 约束库，按领域分节（General、Software、Physical、Social、Lists）。SPECIFICITY=NONE 时的默认路径。
- `references/method-catalog.md` —— 每种方法的一句话摘要 + 适用时机
- `references/heuristics.md` —— 针对边界情况的扩展决策树
- `references/anti-slop.md` —— 反垃圾规则；适用于每一次产出
- `references/exercises.md` —— 限时练习（5 分钟 / 30 分钟 / 1 小时 / 一天 / 一周）
- `references/methods/` —— 22 种具名方法，每种一个文件，只加载你正在用的那一个

## 署名

约束派发的核心改编自 [wttdotm.com/prompts.html](https://wttdotm.com/prompts.html)。各方法取自每个方法文件中所引用的原始出处。
