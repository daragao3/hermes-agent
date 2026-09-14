---
title: "Baoyu Comic —— 知识漫画：科普、传记、教程"
sidebar_label: "Baoyu Comic"
description: "知识漫画：科普、传记、教程"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Baoyu Comic

知识漫画：科普、传记、教程。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/creative/baoyu-comic` 安装 |
| 路径 | `optional-skills/creative/baoyu-comic` |
| 版本 | `1.56.1` |
| 作者 | 宝玉 (JimLiu) |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `comic`, `knowledge-comic`, `creative`, `image-generation` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# 知识漫画创作器

改编自 [baoyu-comic](https://github.com/JimLiu/baoyu-skills)，适配 Hermes Agent 的工具生态。

以灵活的画风 × 基调组合创作原创知识漫画。

## 何时使用

当用户要求创作知识/科普漫画、传记漫画、教程漫画，或使用诸如"知识漫画""教育漫画""Logicomix-style"之类的表述时，触发此 skill。用户会提供内容（文本、文件路径、URL 或主题），并可选地指定画风、基调、版式、宽高比或语言。

## 参考图 {#reference-images}

Hermes 的 `image_generate` 工具是**纯提示词**的 —— 它接受一段文字提示与一个宽高比，返回一个图片 URL。它**不**接受参考图。当用户提供参考图时，请用它来**以文字形式提取特征**，再把这些特征嵌入每一页的提示词中：

**接收**：当用户提供文件路径时接受（或用户在对话中粘贴图片）。
- 文件路径 → 复制到漫画输出目录旁的 `refs/NN-ref-{slug}.{ext}`，以保留出处
- 粘贴了图片但没有路径 → 通过 `clarify` 向用户索要路径，或退而求其次用文字描述风格特征
- 没有参考图 → 跳过本节

**用法模式**（针对每张参考图）：

| 用法 | 效果 |
|-------|--------|
| `style` | 提取风格特征（线条处理、质感、氛围）并追加到每页提示词正文 |
| `palette` | 提取十六进制颜色并追加到每页提示词正文 |
| `scene` | 提取场景构图或主体说明并追加到相关页面 |

存在参考图时，**记录在每页提示词的 frontmatter 中**：

```yaml
references:
  - ref_id: 01
    filename: 01-ref-scene.png
    usage: style
    traits: "muted earth tones, soft-edged ink wash, low-contrast backgrounds"
```

角色一致性由 `characters/characters.md` 中的**文字描述**驱动（在步骤 3 中撰写），这些描述会被内联嵌入到每一页的提示词中（步骤 5）。步骤 7.1 中生成的可选 PNG 角色设定图是给人看的审阅产物，并不是 `image_generate` 的输入。

## 选项

### 视觉维度

| 选项 | 取值 | 说明 |
|--------|--------|-------------|
| 画风 | ligne-claire（默认）、manga、realistic、ink-brush、chalk、minimalist | 画风 / 渲染技法 |
| 基调 | neutral（默认）、warm、dramatic、romantic、energetic、vintage、action | 情绪 / 氛围 |
| 版式 | standard（默认）、cinematic、dense、splash、mixed、webtoon、four-panel | 分格排布 |
| 宽高比 | 3:4（默认，竖版）、4:3（横版）、16:9（宽屏） | 页面宽高比 |
| 语言 | auto（默认）、zh、en、ja 等 | 输出语言 |
| 参考图 | 文件路径 | 用于提取风格 / 配色特征的参考图（不会传给图像模型）。参见上文[参考图](#reference-images)。 |

### 部分流程选项

| 选项 | 说明 |
|--------|-------------|
| 仅分镜 | 只生成分镜，跳过提示词与图片 |
| 仅提示词 | 生成分镜 + 提示词，跳过图片 |
| 仅图片 | 从已有的提示词目录生成图片 |
| 重新生成第 N 页 | 只重新生成指定页面（例如 `3` 或 `2,5,8`） |

详情：[references/partial-workflows.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/partial-workflows.md)

### 画风、基调与预设目录

- **画风**（6 种）：`ligne-claire`、`manga`、`realistic`、`ink-brush`、`chalk`、`minimalist`。完整定义见 `references/art-styles/<style>.md`。
- **基调**（7 种）：`neutral`、`warm`、`dramatic`、`romantic`、`energetic`、`vintage`、`action`。完整定义见 `references/tones/<tone>.md`。
- **预设**（5 种），在单纯的画风+基调之外还带有特殊规则：

  | 预设 | 等价组合 | 特色 |
  |--------|-----------|------|
  | `ohmsha` | manga + neutral | 视觉隐喻、不用大头说话、道具揭示 |
  | `wuxia` | ink-brush + action | 气劲效果、打斗视觉、氛围感 |
  | `shoujo` | manga + romantic | 装饰元素、眼部细节、恋爱节拍 |
  | `concept-story` | manga + warm | 视觉符号体系、成长弧线、对话+动作平衡 |
  | `four-panel` | minimalist + neutral + four-panel 版式 | 起承转合结构、黑白 + 局部彩色、火柴人角色 |

  完整规则见 `references/presets/<preset>.md` —— 选定预设后请加载对应文件。

- **兼容性矩阵**与**内容信号 → 预设**对照表位于 [references/auto-selection.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/auto-selection.md)。在步骤 2 中推荐组合前请先阅读。

## 文件结构

输出目录：`comic/{topic-slug}/`
- Slug：由主题得出的 2-4 个单词的 kebab-case（例如 `alan-turing-bio`）
- 冲突：追加时间戳（例如 `turing-story-20260118-143052`）

**内容**：
| 文件 | 说明 |
|------|-------------|
| `source-{slug}.md` | 保存的原始内容（kebab-case slug 与输出目录一致） |
| `analysis.md` | 内容分析 |
| `storyboard.md` | 含分格拆解的分镜 |
| `characters/characters.md` | 角色定义 |
| `characters/characters.png` | 角色参考设定图（从 `image_generate` 下载） |
| `prompts/NN-{cover\|page}-[slug].md` | 生成提示词 |
| `NN-{cover\|page}-[slug].png` | 生成的图片（从 `image_generate` 下载） |
| `refs/NN-ref-{slug}.{ext}` | 用户提供的参考图（可选，用于保留出处） |

## 语言处理

**判定优先级**：
1. 用户指定的语言（显式选项）
2. 用户的对话语言
3. 原始内容的语言

**规则**：所有交互都使用用户的输入语言：
- 分镜大纲与场景描述
- 图像生成提示词
- 用户选项与确认
- 进度更新、提问、错误、总结

技术术语保持英文。

## 工作流

### 进度清单

```
Comic Progress:
- [ ] Step 1: Setup & Analyze
  - [ ] 1.1 Analyze content
  - [ ] 1.2 Check existing directory
- [ ] Step 2: Confirmation - Style & options ⚠️ REQUIRED
- [ ] Step 3: Generate storyboard + characters
- [ ] Step 4: Review outline (conditional)
- [ ] Step 5: Generate prompts
- [ ] Step 6: Review prompts (conditional)
- [ ] Step 7: Generate images
  - [ ] 7.1 Generate character sheet (if needed) → characters/characters.png
  - [ ] 7.2 Generate pages (with character descriptions embedded in prompt)
- [ ] Step 8: Completion report
```

### 流程

```
Input → Analyze → [Check Existing?] → [Confirm: Style + Reviews] → Storyboard → [Review?] → Prompts → [Review?] → Images → Complete
```

### 步骤概览

| 步骤 | 动作 | 关键产出 |
|------|--------|------------|
| 1.1 | 分析内容 | `analysis.md`、`source-{slug}.md` |
| 1.2 | 检查已有目录 | 处理冲突 |
| 2 | 确认画风、侧重点、受众、审阅 | 用户偏好 |
| 3 | 生成分镜 + 角色 | `storyboard.md`、`characters/` |
| 4 | 审阅大纲（如有要求） | 用户确认 |
| 5 | 生成提示词 | `prompts/*.md` |
| 6 | 审阅提示词（如有要求） | 用户确认 |
| 7.1 | 生成角色设定图（如需要） | `characters/characters.png` |
| 7.2 | 生成页面 | `*.png` 文件 |
| 8 | 完成报告 | 总结 |

### 向用户提问

使用 `clarify` 工具确认选项。由于 `clarify` 一次只处理一个问题，请先问最重要的问题，然后依次推进。完整的步骤 2 问题集见 [references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/workflow.md)。

**超时处理（关键）**：`clarify` 可能返回 `"The user did not provide a response within the time limit. Use your best judgement to make the choice and proceed."` —— 这**不是**用户同意把所有项都取默认值。

- 只把它当作**那一个问题**的默认值。继续依次询问步骤 2 中剩余的问题；每个问题都是独立的同意点。
- **在下一条消息中显式告知用户所用的默认值**，让他们有机会纠正：例如 `"Style: defaulted to ohmsha preset (clarify timed out). Say the word to switch."` —— 不加说明的默认值与从未询问过无异。
- 不要因为一次超时就把步骤 2 压缩成一次"全部使用默认值"。如果用户确实不在场，那么五个问题他都同样不在场 —— 但他回来后可以纠正看得见的默认值，却无法纠正看不见的。

### 步骤 7：图像生成

所有图像渲染都使用 Hermes 内置的 `image_generate` 工具。它的 schema 只接受 `prompt` 和 `aspect_ratio`（`landscape` | `portrait` | `square`）；它**返回一个 URL**，而不是本地文件。因此每张生成的页面或角色设定图都必须下载到输出目录。

**提示词文件要求（硬性）**：在调用 `image_generate` **之前**，把每张图完整、最终的提示词写入 `prompts/` 下的独立文件（命名：`NN-{type}-[slug].md`）。提示词文件就是可复现性记录。

**宽高比映射** —— 分镜中的 `aspect_ratio` 字段按如下方式映射到 `image_generate` 的格式：

| 分镜宽高比 | `image_generate` 格式 |
|------------------|-------------------------|
| `3:4`、`9:16`、`2:3` | `portrait` |
| `4:3`、`16:9`、`3:2` | `landscape` |
| `1:1` | `square` |

**下载步骤** —— 每次调用 `image_generate` 之后：
1. 从工具结果中读取 URL
2. 使用**绝对**输出路径抓取图片字节，例如
   `curl -fsSL "<url>" -o /abs/path/to/comic/<slug>/NN-page-<slug>.png`
3. 在进入下一页之前，确认文件在该确切路径上存在且非空

**绝不要依赖 shell 的 CWD 在批次间保持不变来写 `-o` 路径。** terminal 工具的持久 shell CWD 可能在批次之间发生变化（会话过期、`TERMINAL_LIFETIME_SECONDS`、一次失败的 `cd` 把你留在了错误的目录）。`curl -o relative/path.png` 是一个静默的坑：如果 CWD 已漂移，文件会落到别处而没有任何报错。**始终给 `-o` 传入完全限定的绝对路径**，或者给 terminal 工具传 `workdir=<abs path>`。2026 年 4 月的事故：一部 10 页漫画中的第 06-09 页落到了仓库根目录而不是 `comic/<slug>/`，因为第 3 批继承了第 2 批留下的陈旧 CWD，`curl -o 06-page-skills.png` 写进了错误的目录。随后 agent 又花了好几轮声称文件存在于它们其实不在的位置。

**7.1 角色设定图** —— 当漫画为多页且存在反复出现的角色时，生成它（输出到 `characters/characters.png`，宽高比 `landscape`）。简单预设（例如 four-panel minimalist）或单页漫画可跳过。调用 `image_generate` 之前，`characters/characters.md` 这份提示词文件必须已存在。渲染出的 PNG 是**给人看的审阅产物**（便于用户直观核对角色设计），也是后续重新生成或手工修改提示词时的参考 —— 它**不**驱动步骤 7.2。页面提示词已在步骤 5 中根据 `characters/characters.md` 里的**文字描述**写好；`image_generate` 无法接受图片作为视觉输入。

**7.2 页面** —— 调用 `image_generate` 之前，每一页的提示词必须已存在于 `prompts/NN-{cover|page}-[slug].md`。由于 `image_generate` 是纯提示词的，角色一致性通过**在步骤 5 中把（取自 `characters/characters.md` 的）角色描述内联嵌入每一页提示词**来保证。无论 7.1 是否产出 PNG 设定图，这一嵌入都同样进行；PNG 只是审阅/重生成的辅助。

**备份规则**：已有的 `prompts/…md` 与 `…png` 文件 → 在重新生成前重命名，加上 `-backup-YYYYMMDD-HHMMSS` 后缀。

完整的分步流程（分析、分镜、审阅关卡、重生成变体）：[references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/workflow.md)。

## 参考资料

**核心模板**：
- [analysis-framework.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/analysis-framework.md) - 深度内容分析
- [character-template.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/character-template.md) - 角色定义格式
- [storyboard-template.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/storyboard-template.md) - 分镜结构
- [ohmsha-guide.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/ohmsha-guide.md) - Ohmsha 漫画要点

**风格定义**：
- `references/art-styles/` - 画风（ligne-claire、manga、realistic、ink-brush、chalk、minimalist）
- `references/tones/` - 基调（neutral、warm、dramatic、romantic、energetic、vintage、action）
- `references/presets/` - 带特殊规则的预设（ohmsha、wuxia、shoujo、concept-story、four-panel）
- `references/layouts/` - 版式（standard、cinematic、dense、splash、mixed、webtoon、four-panel）

**工作流**：
- [workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/workflow.md) - 完整流程细节
- [auto-selection.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/auto-selection.md) - 内容信号分析
- [partial-workflows.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-comic/references/partial-workflows.md) - 部分流程选项

## 页面修改

| 动作 | 步骤 |
|--------|-------|
| **编辑** | **先更新提示词文件** → 重新生成图片 → 下载新的 PNG |
| **新增** | 在对应位置创建提示词 → 嵌入角色描述后生成 → 后续页面重新编号 → 更新分镜 |
| **删除** | 移除文件 → 后续页面重新编号 → 更新分镜 |

**重要**：更新页面时，务必**先**更新提示词文件（`prompts/NN-{cover|page}-[slug].md`），再重新生成。这样才能保证改动有据可查、可复现。

## 陷阱

- 图像生成：每页 10-30 秒；失败后自动重试一次
- **务必下载** `image_generate` 返回的 URL 为本地 PNG —— 下游工具（以及用户的审阅）期望的是输出目录中的文件，而不是临时 URL
- **`curl -o` 使用绝对路径** —— 绝不要依赖持久 shell 的 CWD 跨批次保持不变。静默的坑：文件落到错误目录，之后在预期路径上 `ls` 什么也看不到。参见步骤 7 的"下载步骤"。
- 对敏感公众人物使用风格化的替代形象
- **步骤 2 的确认是必需的** - 不要跳过
- **步骤 4/6 是条件性的** - 仅在用户于步骤 2 中要求时执行
- **步骤 7.1 角色设定图** - 多页漫画推荐，简单预设可选。该 PNG 是审阅/重生成的辅助；页面提示词（在步骤 5 中写好）使用的是 `characters/characters.md` 里的文字描述，而非 PNG。`image_generate` 不接受图片作为视觉输入
- **剔除机密信息** —— 在写出任何输出文件之前，扫描原始内容中是否含有 API key、token 或凭据
