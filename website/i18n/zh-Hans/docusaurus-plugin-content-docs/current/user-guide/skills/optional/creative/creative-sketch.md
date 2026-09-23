---
title: "Sketch — 一次性 HTML 原型：2-3 个设计变体用于比较"
sidebar_label: "Sketch"
description: "一次性 HTML 原型：2-3 个设计变体用于比较"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Sketch

一次性 HTML 原型：2-3 个设计变体用于比较。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/creative/sketch` 安装 |
| 路径 | `optional-skills/creative/sketch` |
| 版本 | `1.0.1` |
| 作者 | Hermes Agent（改编自 gsd-build/get-shit-done） |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `sketch`, `mockup`, `design`, `ui`, `prototype`, `html`, `variants`, `exploration`, `wireframe`, `comparison` |
| 相关 skill | [`spike`](/user-guide/skills/bundled/software-development/software-development-spike), [`claude-design`](/user-guide/skills/bundled/creative/creative-claude-design), [`popular-web-designs`](/user-guide/skills/bundled/creative/creative-popular-web-designs), [`excalidraw`](/user-guide/skills/optional/creative/creative-excalidraw) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Sketch

当用户想在**确定方向之前先看看设计方向**时使用此 skill——以可丢弃的 HTML 原型来探索一个 UI/UX 想法。重点是生成 2-3 个可交互的变体，让用户能并排比较不同的视觉方向，而不是产出可交付的代码。

当用户说出诸如“把这个界面画个草图”“给我看看 X 可能长什么样”“比较布局 A 和 B”“给我 2-3 种这个 UI 的方案”“让我看几个变体”“在我动手之前先做个原型”之类的话时，加载此 skill。

## 何时不应使用 {#when-not-to-use-this}

- 用户想要一个生产级组件——使用 `claude-design` 或正式地构建它
- 用户想要一个精致的一次性 HTML 作品（落地页、演示文稿）——`claude-design`
- 用户想要一张图表——`excalidraw`、`architecture-diagram`
- 设计已经敲定——直接构建即可

## 如果用户安装了完整的 GSD 系统 {#if-the-user-has-the-full-gsd-system-installed}

如果 `gsd-sketch` 作为同级 skill 出现（通过 `npx get-shit-done-cc --hermes` 安装），你可以使用 **`gsd-sketch`** 来获得更完整的工作流：带 MANIFEST 的持久化 `.planning/sketches/`、前沿模式分析、跨历史草图的一致性审计，以及与 GSD 其余部分的集成。本 skill 是轻量的独立版本——不带状态机制的一次性草图。

> **注意：** 上游 GSD 项目（[gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done)）在 GitHub 上已**归档 / 不再维护**。npm 包（`get-shit-done-cc`）仍然可以安装，但应将其视为一个已归档的社区项目——这个独立的 `sketch` skill 才是持续维护的路径，且无需任何额外依赖。

## 核心方法 {#core-method}

```
intake  →  variants  →  head-to-head  →  pick winner (or iterate)
```

### 1. 需求收集（如果用户已经给了足够信息就跳过） {#1-intake-skip-if-the-user-already-gave-you-enough}

在生成变体之前，先弄清三件事——一次问一个问题，而不是一股脑全问：

1. **感觉。** “它应该给人什么感觉？形容词、情绪、氛围。”——*“沉静、编辑风、像 Linear 那样”*比*“极简”*能告诉你更多。
2. **参考。** “有哪些应用、网站或产品体现了你想象中的感觉？”——真实的参考胜过抽象的描述。
3. **核心操作。** “用户在这个界面上做的最重要的一件事是什么？”——所有变体都应很好地服务于这件事；如果没有，那它们就只是装饰。

在问下一个问题之前，简短地复述每个回答。如果用户一开始就给出了全部三项，直接进入变体阶段。

### 2. 变体（2-3 个，绝不只有 1 个，很少 4 个以上） {#2-variants-2-3-never-1-rarely-4}

一次性产出 **2-3 个变体**。每个变体都是一个完整、独立的 HTML 文件。不要描述变体——把它们做出来。重点在于比较。

每个变体应采取**不同的设计立场**，而不是不同的像素数值。好的变体维度包括：

- **密度：** 紧凑 / 通透 / 超高密度（选两个对立的极端）
- **侧重：** 内容优先 / 操作优先 / 工具优先
- **美学：** 编辑风 / 实用风 / 活泼风
- **布局：** 单栏 / 侧边栏 / 分栏
- **承载方式：** 卡片式 / 纯内容 / 文档式

选定一个维度，并沿它拉开差距。两个只在强调色上不同的变体是白费功夫——用户根本分辨不出来。

**变体命名：** 描述立场，而不是编号。

<!-- ascii-guard-ignore -->
```
sketches/
├── 001-calm-editorial/
│   ├── index.html
│   └── README.md
├── 001-utilitarian-dense/
│   ├── index.html
│   └── README.md
└── 001-playful-split/
    ├── index.html
    └── README.md
```
<!-- ascii-guard-ignore-end -->

### 3. 做成真正的 HTML {#3-make-them-real-html}

每个变体都是一个**单一的自包含 HTML 文件**：

- 内联 `<style>`——没有构建步骤，没有外部 CSS
- 系统字体，或通过 `<link>` 引入一个 Google Font
- 通过 CDN 使用 Tailwind（`<script src="https://cdn.tailwindcss.com"></script>`）也可以
- 逼真的假内容——真实的句子、真实的名字，而不是“Lorem ipsum”
- **可交互**：链接可点击、悬停效果真实、至少有一个状态切换（打开/关闭、筛选、开关）。一张冻结的静态图片，比一个粗糙但会动的原型更糟糕。

在浏览器中打开它。如果看起来有问题，先修好再给用户看。

**用 Hermes 的浏览器工具在视觉上验证变体。** 不要只写完 HTML 就指望它能正常渲染；加载每个变体并亲眼看一看：

```
browser_navigate(url="file:///absolute/path/to/sketches/001-calm-editorial/index.html")
browser_vision(question="Does this layout look clean and readable? Any visible bugs (overlapping text, unstyled elements, broken images)?")
```

`browser_vision` 会返回页面上实际内容的 AI 描述以及一个截图路径——能发现纯源码检查遗漏的布局问题（例如悄无声息失败的字体导入、塌陷的 flex 容器）。修复后重新导航，直到每个变体都显示正确。

用于快速起步的**默认 CSS 重置 + 系统字体栈**：

```html
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    color: #1a1a1a;
    background: #fafafa;
    line-height: 1.5;
  }
</style>
```

### 4. 变体 README {#4-variant-readme}

每个变体的 `README.md` 需回答：

```markdown
## Variant: {stance name}

### Design stance
One sentence on the principle driving this variant.

### Key choices
- Layout: ...
- Typography: ...
- Color: ...
- Interaction: ...

### Trade-offs
- Strong at: ...
- Weak at: ...

### Best for
- The kind of user or use case this variant actually serves
```

### 5. 正面对比 {#5-head-to-head}

所有变体都构建完成后，以比较的形式呈现。不要只是罗列——要**给出观点**：

```markdown
## Three takes on the home screen

| Dimension | Calm editorial | Utilitarian dense | Playful split |
|-----------|----------------|-------------------|---------------|
| Density   | Low            | High              | Medium        |
| Primary action visibility | Low | High | Medium |
| Scan-ability | High | Medium | Low |
| Feel | Calm, trusted | Sharp, tool-like | Inviting, energetic |

**My take:** Utilitarian dense for power users, calm editorial for content-forward audiences. Playful split is weakest — tries to do both and commits to neither.
```

让用户选出一个胜出者，或将两个合并为混合方案，或要求再来一轮。

## 主题化（当项目有视觉识别体系时） {#theming-when-the-project-has-a-visual-identity}

如果用户已有主题（颜色、字体、token），把共享 token 放进 `sketches/themes/tokens.css`，并在每个变体中 `@import` 它们。保持 token 精简：

```css
/* sketches/themes/tokens.css */
:root {
  --color-bg: #fafafa;
  --color-fg: #1a1a1a;
  --color-accent: #0066ff;
  --color-muted: #666;
  --radius: 8px;
  --font-display: "Inter", sans-serif;
  --font-body: -apple-system, BlinkMacSystemFont, sans-serif;
}
```

不要给一次性草图做过度的 token 化——通常三种颜色加一种字体就够了。

## 交互标准 {#interactivity-bar}

当用户能做到以下几点时，草图的交互性就足够了：

1. **点击主操作**后会发生可见的变化（状态变化、弹窗、toast、模拟跳转）
2. **看到一个有意义的状态切换**（筛选列表、切换模式、打开/关闭面板）
3. **悬停在可识别的可操作元素上**（按钮、行、标签页）

超出这些就是在为一次性作品过度设计。达不到这些就只是一张截图。

## 前沿模式（挑选下一个要画的草图） {#frontier-mode-picking-what-to-sketch-next}

如果已经有草图，而用户问“接下来我该画什么？”：

- **一致性缺口**——来自不同草图的两个胜出变体各自做了独立的选择，还没有被组合到一起
- **未画过的界面**——被引用过，但从未探索
- **状态覆盖**——画了理想路径，但没画空状态 / 加载中 / 错误 / 1000 条数据
- **响应式缺口**——只在一种视口下验证过；在移动端 / 超宽屏上还成立吗？
- **交互模式**——已有静态布局；过渡、拖拽、滚动行为还没有

提出 2-4 个具名候选项，让用户挑选。

## 输出 {#output}

- 在仓库根目录创建 `sketches/`（如果用户使用 GSD 约定，则为 `.planning/sketches/`）
- 每个变体一个子目录：`NNN-stance-name/index.html` + `README.md`
- 告诉用户如何打开它们：macOS 上用 `open sketches/001-calm-editorial/index.html`，Linux 上用 `xdg-open`，Windows 上用 `start`
- 保持变体可丢弃——如果你觉得某个草图有必要保留，就应该把它提升为真正的项目代码，而不是作为资产来维护

**单个变体的典型工具调用序列：**

```
terminal("mkdir -p sketches/001-calm-editorial")
write_file("sketches/001-calm-editorial/index.html", "<!doctype html>...")
write_file("sketches/001-calm-editorial/README.md", "## Variant: Calm editorial\n...")
browser_navigate(url="file://$(pwd)/sketches/001-calm-editorial/index.html")
browser_vision(question="How does this look? Any obvious layout issues?")
```

对每个变体重复上述步骤，然后呈现比较表格。

## 致谢 {#attribution}

改编自 GSD（Get Shit Done）项目的 `/gsd-sketch` 工作流——MIT © 2025 Lex Christopherson（[gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done)）。上游 GSD 仓库目前在 GitHub 上已**归档/不再维护**；`get-shit-done-cc` npm 包仍然可以安装（`npx get-shit-done-cc --hermes --global`），并提供持久化的草图状态、主题/变体模式参考以及一致性审计工作流，但应将其视为一个已归档的社区项目。
