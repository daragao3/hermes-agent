---
title: "Baoyu Article Illustrator —— 文章配图：类型 × 风格 × 配色一致性"
sidebar_label: "Baoyu Article Illustrator"
description: "文章配图：类型 × 风格 × 配色一致性"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Baoyu Article Illustrator

文章配图：类型 × 风格 × 配色一致性。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/creative/baoyu-article-illustrator` 安装 |
| 路径 | `optional-skills/creative/baoyu-article-illustrator` |
| 版本 | `1.57.0` |
| 作者 | 宝玉 (JimLiu) |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `article-illustration`, `creative`, `image-generation` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Article Illustrator

改编自 [baoyu-article-illustrator](https://github.com/JimLiu/baoyu-skills)，适配 Hermes Agent 的工具生态。

分析文章、识别配图位置，并生成具备**类型 × 风格 × 配色**一致性的图像。

## 何时使用

当用户要求为文章配图、给文章添加图片、为内容生成插图，或使用诸如"为文章配图""illustrate article""add images"之类的表述时，触发此 skill。用户会提供文章（文件路径或粘贴的内容），并可选地指定类型、风格、配色或密度。

## 三个维度

| 维度 | 控制内容 | 示例 |
|-----------|----------|----------|
| **类型（Type）** | 信息结构 | infographic、scene、flowchart、comparison、framework、timeline |
| **风格（Style）** | 渲染方式 | notion、warm、minimal、blueprint、watercolor、elegant |
| **配色（Palette）** | 配色方案（可选） | macaron、warm、neon —— 覆盖风格的默认配色 |

可自由组合：`type=infographic, style=vector-illustration, palette=macaron`。

也可以使用预设：`edu-visual` → 一次性确定类型 + 风格 + 配色。参见 [style-presets.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/style-presets.md)。

## 类型

| 类型 | 最适合 |
|------|----------|
| `infographic` | 数据、指标、技术内容 |
| `scene` | 叙事、情感表达 |
| `flowchart` | 流程、工作流 |
| `comparison` | 并列对比、方案选择 |
| `framework` | 模型、架构 |
| `timeline` | 历史、演进 |

## 风格

核心风格、完整风格画廊以及类型 × 风格兼容性，参见 [references/styles.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/styles.md)。

## 输出结构

<!-- ascii-guard-ignore -->
```
{output-dir}/
├── source-{slug}.{ext}    # 仅用于粘贴的内容
├── outline.md
├── prompts/
│   └── NN-{type}-{slug}.md
└── NN-{type}-{slug}.png
```
<!-- ascii-guard-ignore-end -->

**默认输出目录**：

| 输入 | 输出目录 | Markdown 插入路径 |
|-------|------------------|----------------------|
| 文章文件路径 | `{article-dir}/imgs/` | `imgs/NN-{type}-{slug}.png` |
| 粘贴的内容 | `illustrations/{topic-slug}/`（当前工作目录） | `illustrations/{topic-slug}/NN-{type}-{slug}.png` |

如果用户要求不同的布局（例如图片与文章放在一起，或放在 `illustrations/` 子目录中），请遵从用户的要求。

**Slug**：2-4 个单词，kebab-case。**冲突时**：追加 `-YYYYMMDD-HHMMSS`。

## 核心原则

- **可视化概念，而非比喻** —— 如果文章使用了比喻（例如"电锯切西瓜"），请为其背后的概念配图，而不是字面意象。
- **标签使用文章数据** —— 使用文章中的真实数字、术语和引文，而不是通用占位符。
- **prompt 文件是可复现性记录** —— 在生成任何图像之前，每张插图都必须在 `prompts/` 下有一个已保存的 prompt 文件。
- **剔除密钥** —— 在向磁盘写入任何内容之前，扫描源内容中的 API 密钥、令牌或凭据。

## 工作流

```
- [ ] 步骤 1：检测参考图（如果提供）
- [ ] 步骤 2：分析内容
- [ ] 步骤 3：确认设置（使用 clarify 工具，一次一个问题）
- [ ] 步骤 4：生成大纲
- [ ] 步骤 5：生成 prompt
- [ ] 步骤 6：生成图像（image_generate）
- [ ] 步骤 7：收尾
```

### 步骤 1：检测参考图

如果用户提供了参考图（内联粘贴的路径、附件或 URL）：

1. 对每张参考图，调用 `vision_analyze`，传入路径/URL 以及询问风格、配色、构图和主体的问题。通过 `write_file` 将返回的描述记录到 `{output-dir}/references/NN-ref-{slug}.md`。
2. **不要**尝试通过 `write_file` / `read_file` 复制二进制文件——它们只处理文本。如果你想为记录保留一份本地副本，请使用 `terminal`（`cp "$src" "{output-dir}/references/NN-ref-{slug}.{ext}"`）。此 skill 本身从不需要读取二进制文件；它基于视觉描述工作。
3. 由于 `image_generate` 不接受图像输入，视觉描述就是在步骤 5 中被嵌入 prompt 的内容。

完整流程：[references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/workflow.md#step-1-detect-reference-images)。

### 步骤 2：分析

| 分析项 | 输出 |
|----------|--------|
| 内容类型 | 技术 / 教程 / 方法论 / 叙事 |
| 目的 | 信息传达 / 可视化 / 想象力 |
| 核心论点 | 2-5 个要点 |
| 位置 | 配图能带来价值的地方 |

读取源内容（文件路径 → `read_file`，或粘贴的文本），并使用 `write_file` 将分析写入 `{output-dir}/analysis.md`。

完整流程：[references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/workflow.md#step-2-analyze)。

### 步骤 3：确认设置

使用 `clarify` 工具。由于 `clarify` 一次只处理一个问题，请先问最重要的问题。答案已经出现在用户请求中的问题应直接跳过。

| 顺序 | 问题 | 选项 |
|-------|----------|---------|
| Q1 | **预设或类型** | [推荐预设]、[备选预设]，或手动指定：infographic、scene、flowchart、comparison、framework、timeline、mixed |
| Q2 | **密度** | minimal（1-2）、balanced（3-5）、per-section（推荐）、rich（6+） |
| Q3 | **风格** *（若 Q1 已选预设则跳过）* | [推荐]、minimal-flat、sci-fi、hand-drawn、editorial、scene、poster |
| Q4 | **配色** *（可选）* | 默认（风格配色）、macaron、warm、neon |
| Q5 | **语言** *（仅当文章语言不明确时）* | 文章语言 / 用户语言 |

不要连续问超过 2-3 个 `clarify` 问题。如果用户已在请求中指定了这些内容，则完全跳过。

完整流程：[references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/workflow.md#step-3-confirm-settings)。

### 步骤 4：生成大纲 → `outline.md`

使用 `write_file` 保存 `{output-dir}/outline.md`，包含 frontmatter（type、density、style、palette、image_count）以及每张插图一个条目：

```yaml
## 插图 1
**Position**: [章节/段落]
**Purpose**: [原因]
**Visual Content**: [要展示的内容]
**Filename**: 01-infographic-concept-name.png
```

完整模板：[references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/workflow.md#step-4-generate-outline)。

### 步骤 5：生成 prompt

**阻塞条件**：在生成任何图像之前，每张插图都必须有一个已保存的 prompt 文件——prompt 文件就是可复现性记录。

对每张插图：

1. 按照 [references/prompt-construction.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/prompt-construction.md) 创建一个 prompt 文件。
2. 使用 `write_file` 带 YAML frontmatter 保存到 `{output-dir}/prompts/NN-{type}-{slug}.md`。
3. prompt 必须使用带结构化区块（ZONES / LABELS / COLORS / STYLE / ASPECT）的类型专用模板。
4. LABELS 必须包含文章特有的数据：真实的数字、术语、指标、引文。
5. 按 prompt frontmatter 处理参考图（`direct`/`style`/`palette`）——对于 `direct` 用法，请在 prompt 中嵌入该参考图的文字描述（因为 `image_generate` 不接受参考图输入）。

### 步骤 6：生成图像

对每个 prompt 文件：

1. 调用 `image_generate(prompt=..., aspect_ratio=...)`。`image_generate` 返回一个包含图像 URL 的 JSON 结果；它不会写入磁盘，也不接受输出路径。
2. 将 prompt 的 `ASPECT` 映射到 `image_generate` 的枚举值：`16:9` → `landscape`，`9:16` → `portrait`，`1:1` → `square`。自定义比例 → 最接近的具名比例。
3. 通过 `terminal` 将返回的 URL 下载到 `{output-dir}/NN-{type}-{slug}.png`（例如 `curl -sSL -o "{output-dir}/NN-{type}-{slug}.png" "{url}"`）。
4. 生成失败时，自动重试一次。

注意：底层的图像生成后端由用户配置（默认：FAL FLUX 2 Klein 9B），agent 无法通过 `image_generate` 选择。不要把模型名称写进 prompt 并期望它据此路由。

### 步骤 7：收尾

在对应段落之后插入 `![description](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/{relative-path}/NN-{type}-{slug}.png)`。替代文本：用文章所用语言写的简洁描述。

汇报：

```
文章配图完成！
文章：[路径] | 类型：[type] | 密度：[level] | 风格：[style] | 配色：[palette 或默认]
图像：X/N 已生成
```

## 修改

| 操作 | 步骤 |
|--------|-------|
| 编辑 | 更新 prompt → 重新生成 → 更新引用 |
| 新增 | 确定位置 → 编写 prompt → 生成 → 更新大纲 → 插入 |
| 删除 | 删除文件 → 移除引用 → 更新大纲 |

## 参考资料

| 文件 | 内容 |
|------|---------|
| [references/workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/workflow.md) | 详细流程 |
| [references/usage.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/usage.md) | 调用示例 |
| [references/styles.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/styles.md) | 风格画廊 + 配色画廊 |
| [references/style-presets.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/style-presets.md) | 预设快捷方式（类型 + 风格 + 配色） |
| [references/prompt-construction.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/creative/baoyu-article-illustrator/references/prompt-construction.md) | prompt 模板 |

## 常见陷阱

1. **数据完整性至上** —— 绝不总结、转述或改动源数据。"73% increase"必须保持为"73% increase"。
2. **剔除密钥** —— 在写入任何输出文件之前，扫描源内容中的 API 密钥、令牌或凭据。
3. **不要按字面意思为比喻配图** —— 应可视化其背后的概念。
4. **prompt 文件是强制要求** —— 没有已保存的 prompt 文件就不得生成图像。有了该文件，你之后才能重新生成或切换后端。
5. **`image_generate` 的宽高比** —— 该工具支持 `landscape`、`portrait` 和 `square`。自定义比例会映射到最接近的选项。
6. **`image_generate` 返回的是 URL，而非本地文件** —— 在把本地图片路径插入文章之前，务必先通过 `terminal`（`curl`）下载。
7. **agent 无法选择后端** —— `image_generate` 使用用户配置的任意模型（默认：FAL FLUX 2 Klein 9B）。不要把 `"use <model> to generate this"` 写进 prompt 并期望它据此路由。
