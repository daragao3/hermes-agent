---
title: "Pretext — 用无需 DOM 的文本布局构建创意浏览器演示"
sidebar_label: "Pretext"
description: "用无需 DOM 的文本布局构建创意浏览器演示"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Pretext

用无需 DOM 的文本布局构建创意浏览器演示。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选——使用 `hermes skills install official/creative/pretext` 安装 |
| 路径 | `optional-skills/creative/pretext` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `creative-coding`, `typography`, `pretext`, `ascii-art`, `canvas`, `generative`, `text-layout`, `kinetic-typography` |
| 相关 skill | [`p5js`](/user-guide/skills/bundled/creative/creative-p5js), [`claude-design`](/user-guide/skills/bundled/creative/creative-claude-design), [`excalidraw`](/user-guide/skills/optional/creative/creative-excalidraw), [`architecture-diagram`](/user-guide/skills/bundled/creative/creative-architecture-diagram) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Pretext Creative Demos

## 概述 {#overview}

[`@chenglou/pretext`](https://github.com/chenglou/pretext) 是 Cheng Lou（React 核心、ReasonML、Midjourney）开发的一个 15KB、零依赖的 TypeScript 库，用于**无需 DOM 的多行文本测量与布局**。它只做一件事：给定 `(text, font, width)`，返回换行位置、每行宽度、每个字素的位置以及总高度——全部通过 canvas 测量完成，不触发重排。

这听起来像是底层管道。其实不然。正因为它快速且基于几何，它是一种**创意原语**：你可以让段落以 60fps 围绕一个移动的精灵重新排版，构建关卡几何由真实单词组成的游戏，让 ASCII 标志穿行于散文之中，用精确的逐字素起始位置把文本打碎成粒子，或者在没有任何 `getBoundingClientRect` 抖动的情况下打包紧凑贴合的多行 UI。

这个 skill 的存在，是为了让 Hermes 能用它做出**很酷的演示**——就是人们会发到 X 上的那种。社区演示合集见 `pretext.cool` 和 `chenglou.me/pretext`。

## 使用场景 {#when-to-use}

当用户要求以下内容时使用：
- 一个"pretext 演示" / "很酷的 pretext 作品" / "把文本变成 X"
- 围绕移动形状流动的文本（首屏区块、编辑排版、动态长页面）
- 使用**真实单词或散文**而非等宽栅格的 ASCII 艺术效果
- 游戏场地 / 障碍物 / 砖块由文本构成的游戏（字母俄罗斯方块、散文打砖块）
- 带有逐字形物理效果的动态排版（碎裂、散射、群聚、流动）
- 排版生成艺术，尤其是涉及非拉丁文字或混合文字的场景
- 多行"紧凑贴合"UI（仍能容纳文本的最小容器宽度）
- 任何需要在*渲染之前*就知道换行位置的场景

不适用于：
- CSS 已经能解决布局的静态 SVG/HTML 页面——直接用 CSS
- 富文本编辑器、通用的内联格式化引擎（pretext 刻意保持专注）
- 图像 → 文本（使用 `ascii-art` / `ascii-video` skill）
- 不涉及文本的纯 canvas 生成艺术——使用 `p5js`

## 创意标准 {#creative-standard}

这是在浏览器中渲染的视觉艺术。Pretext 返回的是数字；**你**来负责画出作品。

- **不要交付一个"hello world"演示。** `hello-orb-flow.html` 模板只是*起点*。每个交付的演示都必须加入有意为之的色彩、动态、构图，以及一个用户没有要求但会欣赏的视觉细节。
- **深色背景、暖色核心、经过斟酌的调色板。** 经典的黑底琥珀色（CRT / 终端）可行，冷白配炭灰（编辑风）和低饱和粉彩（孔版印刷风）也同样可行。选定一种并坚持到底。
- **比例字体才是重点。** Pretext 的整体气质就是"非等宽"——要充分利用这一点。使用 Iowan Old Style、Inter、JetBrains Mono、Helvetica Neue 或可变字体。绝不用默认的无衬线字体。
- **真实的源文本，而不是 lorem ipsum。** 语料应当有意义。简短的宣言、诗歌、真实的源代码、一段拾得的文本、该库自己的 README——绝不用 `lorem ipsum`。
- **首帧即出色。** 没有加载状态，没有空白帧。演示在打开的那一刻就必须看起来可以直接发布。

## 技术栈 {#stack}

每个演示是一个独立完整的 HTML 文件。没有构建步骤。

| 层 | 工具 | 用途 |
|-------|------|---------|
| 核心 | 通过 `esm.sh` CDN 引入的 `@chenglou/pretext` | 文本测量 + 行布局 |
| 渲染 | HTML5 Canvas 2D | 字形渲染、逐帧合成 |
| 分段 | `Intl.Segmenter`（内置） | 针对 emoji / CJK / 组合标记的字素拆分 |
| 交互 | 原生 DOM 事件 | 鼠标 / 触摸 / 滚轮——不用框架 |

```html
<script type="module">
import {
  prepare, layout,                   // use-case 1: simple height
  prepareWithSegments, layoutWithLines,  // use-case 2a: fixed-width lines
  layoutNextLineRange, materializeLineRange, // use-case 2b: streaming / variable width
  measureLineStats, walkLineRanges,  // stats without string allocation
} from "https://esm.sh/@chenglou/pretext@0.0.6";
</script>
```

固定版本号。撰写本文时为 `@0.0.6`——如果演示行为异常，请到 [npm](https://www.npmjs.com/package/@chenglou/pretext) 查看最新版本。

## 两种用法 {#the-two-use-cases}

几乎所有场景都可以归结为以下两种形态之一。两种都要掌握。

### 用法 1——测量，然后用 CSS/DOM 渲染 {#use-case-1--measure-then-render-with-cssdom}

```js
const prepared = prepare(text, "16px Inter");
const { height, lineCount } = layout(prepared, 320, 20);
```

文本仍然由浏览器来绘制。Pretext 只告诉你在给定宽度下盒子会有多高，**无需**读取 DOM。适用于：
- 行内包含换行文本的虚拟化列表
- 卡片高度精确的瀑布流布局
- 开发阶段的"这个标签放得下吗？"检查
- 在远程文本加载时防止布局偏移

**让 `font` 和 `letterSpacing` 与你的 CSS 保持完全同步。** canvas 的 `ctx.font` 格式（例如 `"16px Inter"`、`"500 17px 'JetBrains Mono'"`）必须与渲染的 CSS 一致，否则测量结果会漂移。

### 用法 2——测量*并*自己渲染 {#use-case-2--measure-and-render-yourself}

```js
const prepared = prepareWithSegments(text, FONT);
const { lines } = layoutWithLines(prepared, 320, 26);
for (let i = 0; i < lines.length; i++) {
  ctx.fillText(lines[i].text, 0, i * 26);
}
```

这才是创意工作的所在。绘制由你掌控，因此你可以：
- 渲染到 canvas、SVG、WebGL 或任何坐标系统
- 替换逐字形变换（旋转、抖动、缩放、透明度）
- 将行元数据（宽度、字素位置）用作几何数据

对于**每行宽度可变**的流式排版（围绕形状的文本、环形带中的文本、非矩形栏中的文本）：

```js
let cursor = { segmentIndex: 0, graphemeIndex: 0 };
let y = 0;
while (true) {
  const lineWidth = widthAtY(y);  // your function: how wide is the corridor at this y?
  const range = layoutNextLineRange(prepared, cursor, lineWidth);
  if (!range) break;
  const line = materializeLineRange(prepared, range);
  ctx.fillText(line.text, leftEdgeAtY(y), y);
  cursor = range.end;
  y += lineHeight;
}
```

这是整个库中最重要的模式。正是它解锁了"文本围绕被拖动的精灵流动"——那个在 X 上走红的演示。

### 值得了解的辅助函数 {#helpers-worth-knowing}

- `measureLineStats(prepared, maxWidth)` → `{ lineCount, maxLineWidth }`——最宽的一行，即多行紧凑贴合宽度。
- `walkLineRanges(prepared, maxWidth, callback)`——遍历各行而不分配字符串。在不需要字符本身、只需对字素做统计/物理计算时使用。
- `@chenglou/pretext/rich-inline`——同一套系统，但用于混排字体 / 标签 / 提及的段落。从子路径导入。

## 演示配方模式 {#demo-recipe-patterns}

社区合集（见 `references/patterns.md`）可以归纳为少数几种强有力的模式。选一种并在其上发挥——除非用户要求，否则不要发明新类别。

| 模式 | 关键 API | 示例创意 |
|---|---|---|
| **围绕障碍物重排** | `layoutNextLineRange` + 逐行宽度函数 | 编辑风段落，在被拖动的光标精灵周围分开 |
| **文本即几何的游戏** | `layoutWithLines` + 逐行碰撞矩形 | 打砖块，每块砖都是一个测量过的单词 |
| **碎裂 / 粒子** | `walkLineRanges` → 逐字素 (x,y) → 物理 | 点击后炸裂成字母的句子 |
| **ASCII 障碍排版** | `layoutNextLineRange` + 测量得到的逐行障碍区间 | 位图 ASCII 标志、形状变形，以及可拖动的线框物体，让文本围绕它们的实际几何形状让开 |
| **编辑风多栏** | 每栏使用 `layoutNextLineRange` + 共享游标 | 带引文的动态杂志跨页 |
| **动态文字** | `layoutWithLines` + 随时间变化的逐行变换 | 星球大战片头滚动、波浪、弹跳、故障效果 |
| **多行紧凑贴合** | `measureLineStats` | 自动缩放到最紧凑容器的引言卡片 |

可用的单文件起步模板见 `templates/donut-orbit.html` 和 `templates/hello-orb-flow.html`。

## 工作流程 {#workflow}

1. 根据用户的需求，从上表中**选择一种模式**。
2. **从模板开始**：
   - `templates/hello-orb-flow.html`——围绕移动的球体重新排版的文本（围绕障碍物重排模式）
   - `templates/donut-orbit.html`——进阶示例：测量得到的 ASCII 标志障碍物、可拖动的线框球体/立方体、变形的形状场、可选中的 DOM 文本，以及仅限开发时使用的控件
   - 用 `write_file` 在 `/tmp/` 或用户的工作区中新建一个 `.html`。
3. **替换语料**，换成与需求契合的内容。真实的散文，10-100 句，不用 lorem。
4. **调整美感**——字体、调色板、构图、交互。这才是真正的工作；不要跳过。
5. **本地验证**：
   ```sh
   cd <dir-with-html> && python -m http.server 8765
   # then open http://localhost:8765/<file>.html
   ```
6. **检查控制台**——如果 `prepareWithSegments` 收到错误的字体字符串，pretext 会抛出异常；`Intl.Segmenter` 在所有现代浏览器中都可用。
7. **把文件路径告诉用户**，而不只是代码——他们想要打开它。

## 性能说明 {#performance-notes}

- `prepare()` / `prepareWithSegments()` 是开销大的调用。每个文本+字体组合只调用**一次**。缓存返回的句柄。
- 窗口尺寸变化时，只重新运行 `layout()` / `layoutWithLines()`——绝不重新 prepare。
- 对于文本不变但几何形状变化的逐帧动画，在紧凑循环中调用 `layoutNextLineRange` 的开销足够低，对于正常长度的段落可以以 60fps 每帧执行。
- 逐帧渲染 ASCII 遮罩时，保留一个单元格缓冲区（`Uint8Array`/类型化数组），从单元格或投影几何中推导出测量得到的逐行障碍区间，合并这些区间，然后在绘制文本之前将它们传给 `layoutNextLineRange`。
- 让视觉动画与布局动画保持耦合。如果一个球体变形为立方体，要用同一个值同时补间渲染的单元格缓冲区和障碍区间；否则演示看起来像是画上去的，而不是真正在物理上重排。
- 对于淡入淡出，优先使用图层透明度，而不是改变字形强度或障碍物缩放。把临时的 ASCII 精灵放在单独的 canvas 上，用 CSS/GSAP 的 opacity 淡化整个 canvas，这样几何形状就不会显得在缩小。
- 设置 canvas 的 `ctx.font` 出乎意料地慢；如果字体不变，每帧只设置**一次**，而不是每次 `fillText` 调用都设置。

## 常见陷阱 {#common-pitfalls}

1. **CSS/canvas 字体字符串不一致。** 用 `ctx.font = "16px Inter"` 测量，但 CSS 写的是 `font-family: Inter, sans-serif; font-size: 16px`。*如果* Inter 加载成功就没问题。如果 Inter 返回 404，CSS 会回退到 sans-serif，测量结果会偏差 5-20%。务必 `preload` 字体，或使用网页安全字体族。

2. **在动画循环内重新 prepare。** 只有 `layout*` 是廉价的。每帧重新调用 `prepare` 会让性能一落千丈。把 prepare 得到的句柄放在模块作用域中。

3. **拆分字素时忘记使用 `Intl.Segmenter`。** Emoji、组合标记、CJK——`"é".split("")` 会得到两个字符。采样单个可见字形时，使用 `new Intl.Segmenter(undefined, { granularity: "grapheme" })`。

4. **使用 `break: 'never'` 的标签却没有 `extraWidth`。** 在 `rich-inline` 中，如果你对原子化的标签/提及使用 `break: 'never'`，还必须为药丸形内边距提供 `extraWidth`——否则标签的外框会溢出容器。

5. **从 `unpkg` 使用只有 TypeScript 入口的 `@chenglou/pretext`。** 使用 `esm.sh`——它会自动把 TS 导出编译为浏览器可用的 ESM。`unpkg` 会返回 404 或提供原始 TS。

6. **等宽字体回退悄无声息地让一切失去意义。** 看到输出像等宽字体的用户，往往是 CSS 的 `font-family` 一路回退到了 `monospace`。通过 DevTools 验证实际渲染的字体。

7. **围绕形状排版时是跳过行还是调整宽度。** 如果这一行的通道太窄放不下一行文本，就*跳过这一行*（`y += lineHeight; continue;`），而不是给 `layoutNextLineRange` 传一个极小的 maxWidth——pretext 会返回只有一个字素的行，看起来像是坏掉了。

8. **交付一个冷冰冰的演示。** 默认的首帧看起来只是教程水准。加上：暗角、细微的扫描线、空闲时的自动运动、一个精心挑选的交互响应（拖动、悬停、滚动、点击）。没有这些，"很酷的 pretext 演示"就会沦为"实习生照着 README 复现的东西"。

## 验证清单 {#verification-checklist}

- [ ] 演示是一个独立完整的 `.html` 文件——双击或通过 `python -m http.server` 即可打开
- [ ] 通过 `esm.sh` 以固定版本导入 `@chenglou/pretext`
- [ ] 语料是真实的散文，而不是 lorem ipsum，并且与演示的概念相符
- [ ] 传给 `prepare` 的字体字符串与 CSS 字体完全一致
- [ ] `prepare()` / `prepareWithSegments()` 只调用一次，而不是每帧调用
- [ ] 深色背景 + 经过斟酌的调色板——而不是默认的白色 canvas
- [ ] 至少一个交互响应（拖动 / 悬停 / 滚动 / 点击）或空闲时的自动运动
- [ ] 已用 `python -m http.server` 在本地测试，并确认没有控制台错误
- [ ] 在中端笔记本上达到 60fps（或已记录优雅降级方案）
- [ ] 一个用户没有要求的"额外用心"细节

## 参考：社区演示 {#reference-community-demos}

克隆这些项目以获取灵感 / 模式（基本都是类 MIT 许可，链接自 [pretext.cool](https://www.pretext.cool/)）：

- **Pretext Breaker**——用单词砖块做的打砖块——`github.com/rinesh/pretext-breaker`
- **Tetris × Pretext**——`github.com/shinichimochizuki/tetris-pretext`
- **Dragon animation**——`github.com/qtakmalay/PreTextExperiments`
- **Somnai editorial engine**——`github.com/somnai-dreams/pretext-demos`
- **Bad Apple!! ASCII**——`github.com/frmlinn/bad-apple-pretext`
- **Drag-sprite reflow**——`github.com/dokobot/pretext-demo`
- **Alarmy editorial clock**——`github.com/SmisLee/alarmy-pretext-demo`

官方演练场：[chenglou.me/pretext](https://chenglou.me/pretext/)——accordion、bubbles、dynamic-layout、editorial-engine、justification-comparison、masonry、markdown-chat、rich-note。
