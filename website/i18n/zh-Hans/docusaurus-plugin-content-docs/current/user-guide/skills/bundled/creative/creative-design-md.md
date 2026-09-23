---
title: "Design Md — 编写/验证/导出 Google 的 DESIGN.md token 规范文件"
sidebar_label: "Design Md"
description: "编写/验证/导出 Google 的 DESIGN.md token 规范文件"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Design Md

编写/验证/导出 Google 的 DESIGN.md token（设计令牌）规范文件。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/creative/design-md` |
| 版本 | `1.1.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `design`, `design-system`, `tokens`, `ui`, `accessibility`, `wcag`, `tailwind`, `dtcg`, `google` |
| 相关 skill | [`popular-web-designs`](/user-guide/skills/bundled/creative/creative-popular-web-designs), [`claude-design`](/user-guide/skills/bundled/creative/creative-claude-design), [`excalidraw`](/user-guide/skills/optional/creative/creative-excalidraw), [`architecture-diagram`](/user-guide/skills/bundled/creative/creative-architecture-diagram) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# DESIGN.md Skill

DESIGN.md 是 Google 的开放规范（Apache-2.0，`google-labs-code/design.md`），用于向编码 agent 描述视觉标识。一个文件包含：

- **YAML 前置元数据** — 机器可读的设计 token（规范值）
- **Markdown 正文** — 人类可读的说明，按规范章节组织

Token 提供精确值。正文告诉 agent *为什么*这些值存在以及如何应用它们。CLI（`npx @google/design.md`）可对结构和 WCAG 对比度进行 lint 检查，对版本进行 diff 以检测回归，并导出为 Tailwind 或 W3C DTCG JSON。

## 何时使用此 skill

- 用户请求 DESIGN.md 文件、设计 token 或设计系统规范
- 用户希望在多个项目或工具中保持一致的 UI/品牌风格
- 用户粘贴了现有的 DESIGN.md，并要求进行 lint、diff、导出或扩展
- 用户希望将样式指南移植为 agent 可消费的格式
- 用户希望对其调色板进行对比度/WCAG 无障碍验证

若仅需视觉灵感或布局示例，请改用 `popular-web-designs`。若需要从零开始设计一次性 HTML 产物（原型、幻灯片、落地页、组件实验室）时的*流程与品味*，请使用 `claude-design`。本 skill 专用于*正式规范文件*本身。

## 文件结构

```md
---
version: alpha
name: Heritage
description: Architectural minimalism meets journalistic gravitas.
colors:
  primary: "#1A1C1E"
  secondary: "#6C7278"
  tertiary: "#B8422E"
  neutral: "#F7F5F2"
typography:
  h1:
    fontFamily: Public Sans
    fontSize: 3rem
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  body-md:
    fontFamily: Public Sans
    fontSize: 1rem
rounded:
  sm: 4px
  md: 8px
  lg: 16px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sm}"
    padding: 12px
  button-primary-hover:
    backgroundColor: "{colors.primary}"
---

## Overview

Architectural Minimalism meets Journalistic Gravitas...

## Colors

- **Primary (#1A1C1E):** Deep ink for headlines and core text.
- **Tertiary (#B8422E):** "Boston Clay" — the sole driver for interaction.

## Typography

Public Sans for everything except small all-caps labels...

## Components

`button-primary` is the only high-emphasis action on a page...
```

## Token 类型

| 类型 | 格式 | 示例 |
|------|--------|---------|
| 颜色 | 任意 CSS 颜色（十六进制、`rgb()`、`oklch()`、命名颜色） | `"#1A1C1E"`、`"oklch(62% 0.18 250)"` |
| 尺寸 | 数字 + 单位（`px`、`em`、`rem`） | `48px`、`-0.02em` |
| Token 引用 | `{path.to.token}` | `{colors.primary}` |
| 字体排版 | 包含 `fontFamily`、`fontSize`、`fontWeight`、`lineHeight`、`letterSpacing`、`fontFeature`、`fontVariation` 的对象 | 见上方 |

组件属性白名单：`backgroundColor`、`textColor`、`typography`、`rounded`、`padding`、`size`、`height`、`width`。变体（hover、active、pressed）是**独立的组件条目**，使用相关键名（`button-primary-hover`），而非嵌套结构。

## 规范章节顺序

章节均为可选，但已存在的章节应按以下顺序排列。linter 会标记顺序错误的章节（`section-order`，警告）以及重复的标题——按照规范，消费方会拒绝重复标题，因此在返回文件前请把这两类问题都修复。

1. Overview（别名：Brand & Style）
2. Colors
3. Typography
4. Layout（别名：Layout & Spacing）
5. Elevation & Depth（别名：Elevation）
6. Shapes
7. Components
8. Do's and Don'ts

未知章节会被保留，不会报错。未知 token 名称在值类型有效时可被接受。未知组件属性会产生警告。

## 工作流：编写新的 DESIGN.md

1. **询问用户**（或推断）品牌基调、强调色和字体方向。若用户提供了网站、图片或风格描述，将其转换为上述 token 结构。
2. **编写 `DESIGN.md`**，使用 `write_file` 写入项目根目录。始终包含 `name:` 和 `colors:`；其他章节可选但建议添加。
3. **使用 token 引用**（`{colors.primary}`）在 `components:` 章节中引用颜色，而非重复输入十六进制值。保持调色板单一来源。
4. **进行 lint 检查**（见下文）。在返回前修复所有断开的引用或 WCAG 失败项。
5. **若用户有现有项目**，同时将 Tailwind 或 DTCG 导出文件写入文件旁（`tailwind.theme.json`、`tokens.json`）。

## 工作流：lint / diff / 导出

CLI 为 `@google/design.md`（Node）。使用 `npx`，无需全局安装。

```bash
# 验证结构 + token 引用 + WCAG 对比度
npx -y @google/design.md lint DESIGN.md

# 比较两个版本，发现回归时失败（exit 1 = 存在回归）
npx -y @google/design.md diff DESIGN.md DESIGN-v2.md

# 导出为 Tailwind v3 主题 JSON（`tailwind` 是向后兼容的别名）
npx -y @google/design.md export --format json-tailwind DESIGN.md > tailwind.theme.json

# 导出为 Tailwind v4 CSS @theme 块（--color-*、--text-*、--radius-* 等）
npx -y @google/design.md export --format css-tailwind DESIGN.md > theme.css

# 导出为 W3C DTCG（Design Tokens Format Module）JSON
npx -y @google/design.md export --format dtcg DESIGN.md > tokens.json

# 打印规范本身 — 在注入 agent prompt 时很有用
npx -y @google/design.md spec --rules-only --format json
```

所有命令均接受 `-` 作为 stdin。`lint` 在出现错误时返回 exit 1（仅有警告时返回 exit 0）。`export` 只要导出成功就返回 exit 0，与源文件中的 lint 结果无关——如需据此设置关卡，请单独运行 `lint`。输出默认为 JSON；若需要以结构化方式报告结果，请解析输出。

在 Windows 上，`design.md` 这个 bin 名称可能与 `.md` 文件关联发生冲突（静默无操作，或文件在编辑器中被打开）。请使用不含点号的别名：`npx -y -p @google/design.md designmd lint DESIGN.md`。

### Lint 规则参考（9 条规则，截至 CLI 0.3.0）

- `broken-ref`（错误）— `{colors.missing}` 指向不存在的 token
- `contrast-ratio`（警告）— 组件 `textColor` 与 `backgroundColor` 的对比度低于 WCAG AA（4.5:1）
- `missing-primary`（警告）— 定义了颜色但没有 `primary` token
- `missing-typography`（警告）— 定义了颜色但没有字体排版 token
- `orphaned-tokens`（警告）— 从未被任何组件引用的颜色 token
- `section-order`（警告）— 章节未按规范顺序排列
- `unknown-key`（警告）— 看起来像是 schema 键拼写错误的顶层 YAML 键（`colours:` → `colors:`）；自定义扩展键不会报告
- `token-summary`、`missing-sections`（信息）— 计数以及缺失的可选章节

当用户关注无障碍性时，请在摘要中明确指出 — WCAG 检查结果是使用 CLI 最重要的理由。

## 常见陷阱

- **不要嵌套组件变体。** `button-primary.hover` 是错误的；应将 `button-primary-hover` 作为同级键。
- **十六进制颜色必须加引号。** 否则 YAML 会在 `#` 处出错，或将 `#1A1C1E` 等值截断。
- **负数尺寸也需要加引号。** `letterSpacing: -0.02em` 会被解析为 YAML flow — 应写为 `letterSpacing: "-0.02em"`。
- **即使 linter 只发出警告，章节顺序也很重要。** 若用户以随机顺序提供正文，在保存前须重新排列为规范列表顺序——符合规范的消费方会依赖这一顺序。
- **字体排版子属性的拼写错误会被静默丢弃。** 截至 CLI 0.3.0，像 `fontwight:` 这样的拼写错误不会产生任何检查结果，其值会从导出中消失——请对照 schema 仔细核对子属性名（`fontFamily`、`fontSize`、`fontWeight`、`lineHeight`、`letterSpacing`、`fontFeature`、`fontVariation`）。
- **`version: alpha` 是当前规范版本**（截至 2026 年 7 月，CLI 0.3.0）。该规范标记为 alpha — 请关注破坏性变更。
- **Token 引用通过点分路径解析。** `{colors.primary}` 有效；`{primary}` 无效。

## 规范来源

- 仓库：https://github.com/google-labs-code/design.md（Apache-2.0）
- CLI：npm 上的 `@google/design.md`
- 生成的 DESIGN.md 文件的许可证：取决于用户项目所使用的许可证；规范本身为 Apache-2.0。
