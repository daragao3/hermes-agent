---
title: "Excalidraw — 手绘风格的 Excalidraw JSON 图表（架构图、流程图、时序图）"
sidebar_label: "Excalidraw"
description: "手绘风格的 Excalidraw JSON 图表（架构图、流程图、时序图）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Excalidraw

手绘风格的 Excalidraw JSON 图表（架构图、流程图、时序图）。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/creative/excalidraw` 安装 |
| 路径 | `optional-skills/creative/excalidraw` |
| 版本 | `1.0.1` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Excalidraw`, `Diagrams`, `Flowcharts`, `Architecture`, `Visualization`, `JSON` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Excalidraw 图表 Skill {#excalidraw-diagram-skill}

通过编写标准的 Excalidraw 元素 JSON 并保存为 `.excalidraw` 文件来创建图表。这些文件可以直接拖放到 [excalidraw.com](https://excalidraw.com) 上查看和编辑。无需账号，无需 API 密钥，无需渲染库——只需 JSON。

## 使用时机 {#when-to-use}

为架构图、流程图、时序图、概念图等生成 `.excalidraw` 文件。文件可以在 excalidraw.com 上打开，也可以上传以获取可分享的链接。

## 工作流 {#workflow}

1. **加载此 skill**（你已经加载了）
2. **编写元素 JSON**——一个由 Excalidraw 元素对象组成的数组
3. **保存文件**，使用 `write_file` 创建一个 `.excalidraw` 文件
4. **可选上传**，通过 `terminal` 使用 `scripts/upload.py` 获取可分享的链接

### 保存图表 {#saving-a-diagram}

将你的元素数组包裹在标准的 `.excalidraw` 外层结构中，然后用 `write_file` 保存：

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "hermes-agent",
  "elements": [ ...your elements array here... ],
  "appState": {
    "viewBackgroundColor": "#ffffff"
  }
}
```

可保存到任意路径，例如 `~/diagrams/my_diagram.excalidraw`。

### 上传以获取可分享链接 {#uploading-for-a-shareable-link}

通过终端运行上传脚本（位于此 skill 的 `scripts/` 目录中）：

```bash
python skills/creative/excalidraw/scripts/upload.py ~/diagrams/my_diagram.excalidraw
```

这会上传到 excalidraw.com（无需账号）并打印一个可分享的 URL。需要 `cryptography` pip 包（`pip install cryptography`）。

---

## 元素格式参考 {#element-format-reference}

### 必填字段（所有元素） {#required-fields-all-elements}
`type`、`id`（唯一字符串）、`x`、`y`、`width`、`height`

### 默认值（可省略——会自动应用） {#defaults-skip-these----theyre-applied-automatically}
- `strokeColor`：`"#1e1e1e"`
- `backgroundColor`：`"transparent"`
- `fillStyle`：`"solid"`
- `strokeWidth`：`2`
- `roughness`：`1`（手绘外观）
- `opacity`：`100`

画布背景为白色。

### 元素类型 {#element-types}

**矩形**：
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 100 }
```
- `roundness: { "type": 3 }` 用于圆角
- `backgroundColor: "#a5d8ff"`、`fillStyle: "solid"` 用于填充

**椭圆**：
```json
{ "type": "ellipse", "id": "e1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**菱形**：
```json
{ "type": "diamond", "id": "d1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**带标签的形状（容器绑定）**——创建一个绑定到该形状的文本元素：

> **警告：** **不要**在形状上使用 `"label": { "text": "..." }`。这**不是**有效的
> Excalidraw 属性，会被悄无声息地忽略，从而产生空白的形状。你**必须**
> 使用下面的容器绑定方法。

形状需要 `boundElements` 列出该文本，而文本需要 `containerId` 反向指回形状：
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 80,
  "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid",
  "boundElements": [{ "id": "t_r1", "type": "text" }] },
{ "type": "text", "id": "t_r1", "x": 105, "y": 110, "width": 190, "height": 25,
  "text": "Hello", "fontSize": 20, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "r1", "originalText": "Hello", "autoResize": true }
```
- 适用于矩形、椭圆、菱形
- 设置了 `containerId` 时，Excalidraw 会自动将文本居中
- 文本的 `x`/`y`/`width`/`height` 只是近似值——Excalidraw 在加载时会重新计算
- `originalText` 应与 `text` 一致
- 始终包含 `fontFamily: 1`（Virgil/手绘字体）

**带标签的箭头**——同样使用容器绑定方法：
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow",
  "boundElements": [{ "id": "t_a1", "type": "text" }] },
{ "type": "text", "id": "t_a1", "x": 370, "y": 130, "width": 60, "height": 20,
  "text": "connects", "fontSize": 16, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "a1", "originalText": "connects", "autoResize": true }
```

**独立文本**（仅用于标题和注释——没有容器）：
```json
{ "type": "text", "id": "t1", "x": 150, "y": 138, "text": "Hello", "fontSize": 20,
  "fontFamily": 1, "strokeColor": "#1e1e1e", "originalText": "Hello", "autoResize": true }
```
- `x` 是**左**边缘。要以位置 `cx` 为中心：`x = cx - (text.length * fontSize * 0.5) / 2`
- **不要**依赖 `textAlign` 或 `width` 来定位

**箭头**：
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow" }
```
- `points`：相对于元素 `x`、`y` 的 `[dx, dy]` 偏移量
- `endArrowhead`：`null` | `"arrow"` | `"bar"` | `"dot"` | `"triangle"`
- `strokeStyle`：`"solid"`（默认）| `"dashed"` | `"dotted"`

### 箭头绑定（将箭头连接到形状） {#arrow-bindings-connect-arrows-to-shapes}

```json
{
  "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 150, "height": 0,
  "points": [[0,0],[150,0]], "endArrowhead": "arrow",
  "startBinding": { "elementId": "r1", "fixedPoint": [1, 0.5] },
  "endBinding": { "elementId": "r2", "fixedPoint": [0, 0.5] }
}
```

`fixedPoint` 坐标：`top=[0.5,0]`、`bottom=[0.5,1]`、`left=[0,0.5]`、`right=[1,0.5]`

### 绘制顺序（z 轴顺序） {#drawing-order-z-order}
- 数组顺序 = z 轴顺序（第一个 = 最底层，最后一个 = 最顶层）
- 逐步输出：背景区域 → 形状 → 其绑定的文本 → 其箭头 → 下一个形状
- 错误：先所有矩形，再所有文本，再所有箭头
- 正确：bg_zone → shape1 → text_for_shape1 → arrow1 → arrow_label_text → shape2 → text_for_shape2 → ...
- 始终将绑定的文本元素紧跟在其容器形状之后

### 尺寸指南 {#sizing-guidelines}

**字号：**
- 正文、标签、描述的最小 `fontSize`：**16**
- 标题和小标题的最小 `fontSize`：**20**
- 仅次要注释的最小 `fontSize`：**14**（慎用）
- **永远不要**使用小于 14 的 `fontSize`

**元素尺寸：**
- 带标签的矩形/椭圆的最小形状尺寸：120x60
- 元素之间至少留出 20-30px 的间距
- 宁可用更少、更大的元素，也不要用许多细小的元素

### 调色板 {#color-palette}

完整的颜色表请参阅 `references/colors.md`。速查：

| 用途 | 填充颜色 | 十六进制 |
|-----|-----------|-----|
| 主要 / 输入 | 浅蓝色 | `#a5d8ff` |
| 成功 / 输出 | 浅绿色 | `#b2f2bb` |
| 警告 / 外部 | 浅橙色 | `#ffd8a8` |
| 处理 / 特殊 | 浅紫色 | `#d0bfff` |
| 错误 / 关键 | 浅红色 | `#ffc9c9` |
| 备注 / 决策 | 浅黄色 | `#fff3bf` |
| 存储 / 数据 | 浅青色 | `#c3fae8` |

### 技巧 {#tips}
- 在整个图表中一致地使用调色板
- **文本对比度至关重要**——永远不要在白色背景上使用浅灰色。白色背景上的最浅文本颜色：`#757575`
- **不要**在文本中使用 emoji——它们在 Excalidraw 的字体中无法渲染
- 深色模式图表请参阅 `references/dark-mode.md`
- 更大的示例请参阅 `references/examples.md`
