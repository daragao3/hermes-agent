---
title: "Draw Your Font — 将手写照片转换为可安装的 TTF 字体"
sidebar_label: "Draw Your Font"
description: "将手写照片转换为可安装的 TTF 字体"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Draw Your Font

将手写照片转换为可安装的 TTF 字体。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/creative/draw-your-font` 安装 |
| 路径 | `optional-skills/creative/draw-your-font` |
| 版本 | `0.1.0` |
| 作者 | Danilo Znamerovszkij (https://github.com/danilo-znamerovszkij/draw-your-font)，由 Hermes Agent 移植 |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `font`, `handwriting`, `typography`, `ttf`, `woff`, `vision`, `creative` |
| 相关 skill | [`pixel-art`](/user-guide/skills/optional/creative/creative-pixel-art) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# draw-your-font {#draw-your-font}

输入手写字母的照片 → 输出可安装的字体。由你负责“看”（找到并标注字母、判断质量）；所有几何工作（描摹、度量、字体组装）都由 CLI 完成。永远不要自己编辑 SVG 路径或坐标。

## 在 Hermes 中设置（每个会话一次） {#setup-in-hermes-once-per-session}

该 CLI 是固定版本的 npm 包 `draw-your-font@0.1.0`——通过 npx 运行（需要 Node ≥ 18，无需全局安装）：

```bash
npx -y draw-your-font@0.1.0 --help
```

下面的示例中凡是出现 `$DYF` 的地方，都使用 `npx -y draw-your-font@0.1.0`。Shell 变量不会在工具调用之间保留，所以每次都要粘贴完整命令。一切都在本地运行；用户的笔迹永远不会离开这台机器。

照片会以两种方式进入 Hermes：消息中的文件路径，或者通过 gateway 图片缓存——在 CLI 中使用实际的文件路径。如果照片出现在对话中却没有路径，请向用户索要文件（CLI 需要真实的文件，而不是你对图片的记忆）。

视觉相关步骤（缩略总览图、预览、字形表）通过 `vision_analyze` 加载 PNG 来完成。

## 确定流程 {#decide-the-flow}

- **用户还没有照片** → 提供模板：打印、书写、拍照。
- **用户分享了手写照片** → 按下面的主流程进行。
- **用户粘贴了图片但没有文件路径** → 你能看到图片，但 CLI 需要文件。请用户把图片文件拖进终端（这会插入其路径），或直接给出路径。不要凭记忆继续。
- **用户想修改本次会话中构建的字体** → 见“精修”一节。

## 模板流程（质量最佳） {#template-flow-best-quality}

```bash
$DYF template -o template.pdf --charset minimal   # or: spanish
```

告诉用户：把它打印出来，用深色笔（0.5 mm 以上）在每个格子里写一个字符，让字母落在实线上，然后在光线良好的环境下从正上方拍摄每一页，并分享文件路径。网格以浅灰色打印，在处理过程中会消失——只有他们的墨迹会被保留。

## 主流程：照片 → 字体 {#main-flow-photos--font}

**1. 分割。** 对模板页和自由书写的照片同样适用：

```bash
$DYF segment photo1.jpg photo2.jpg -d work
```

**2. 先看，再标注。** 用 `vision_analyze` 加载 `work/contact-1.png`（每张照片一张）：每个检测到的色块都有编号。这一步需要你用眼睛把关——检查：

- 每个书写的字符是否都恰好对应一个框？用分开的笔画写成的字母可能显示为两个框（重新标注即可处理：给主框标上该字符，把碎片标为 `""`），而两个相互接触的字母可能共用一个框（请用户只重拍这几个字母，或者接受这个缺口）。
- 垃圾框（阴影、横格线、污渍、页面边缘）→ 标为 `""`。

然后编写 `work/labels.json`，将色块 id 映射到字符，例如 `{"0": "A", "1": "B", "7": "", "8": "a"}`：

- 模板页：顺序是模板上印刷的字符集顺序——请对照表格核实，而不是盲目相信。minimal 的顺序：A–Z、a–z、0–9，然后是 `.,;:!?'"-()@#&+/$`；spanish 会追加 `ÑñÁÉÍÓÚáéíóúü¿¡`。
- 自由书写：从缩略总览图中识别每个字母。对于形状相同的大小写字母（S/s、O/o、C/c、X/x……），通过相对大小和位置判断大小写——与你有把握的相邻字母进行比较。
- 用户告诉了你他们写的是什么（例如 "ABC then abc"）？相信它，按阅读顺序映射（先第一行，从左到右），并进行视觉核实。
- 同一个字母出现两次 → 标注写得更好的那个，另一个标为 `""`。

**3. 构建。**

```bash
$DYF build -d work --labels work/labels.json --name "Dan's Hand"
```

以用户的名字命名字体（如果不清楚就问——最多问一个简短的问题）。

**4. 交付前先评判。** 用 `vision_analyze` 加载 `work/preview.png` 和 `work/glyphs.png`，像艺术总监一样挑剔地审视：

- 字母断裂或有墨团（描摹不佳）→ 通常是笔画太淡；尝试 `--weight 1`，或请用户只重拍那个字母。
- 整体太细/太粗 → 用 `--weight 1` / `--weight -1` 重新构建。
- 边缘有锯齿 → 用 `--smooth 1.5`（最高 2）重新构建。
- 某个字母位置不对（例如 `g` 没有下伸）→ 通常是标注错误；修正 labels.json 后重新构建。
- 字腔被填实（b、o、g 看起来是实心的）：这本不应发生——如果发生了，说明裁剪区域有污渍；请用户重拍。

重新构建成本很低，可以放心反复迭代。能自己修的先自己修；只有当源墨迹本身有问题时，才去麻烦用户重拍。

**5. 交付。** 字体会生成在 `<workdir>/<NameWithoutSpaces>.ttf`（构建输出会打印确切路径）。给出该路径以及安装方法：macOS——双击 → "Install Font"；Windows——右键 → "Install"。说明缺少哪些字符（构建会打印未覆盖的字母），并在不强推的前提下提供：

- Web 格式 + CSS：用 `--formats ttf,woff,woff2,css` 重新构建。
- 一次易读性评估（见下文）。
- 用他们的下一张照片补齐缺失字符：把所有照片（新旧都包括）重新运行 segment 到一个新的工作目录——`$DYF segment p1.jpg p2.jpg -d
  work2`——然后根据新的缩略总览图重新标注（色块 id 会重新编号；旧的 labels.json 不会沿用），并从新的工作目录构建。

## 精修（对话式迭代） {#refine-conversational-iteration}

| 用户说 | 操作 |
|---|---|
| “更平滑 / 更圆润” | `build … --smooth 1.5`（最高 2） |
| “更粗 / 更醒目” | `build … --weight 1`（最高 2） |
| “更细 / 更轻” | `build … --weight=-1`（负值需要使用 `=` 形式） |
| “这个 g 看起来不好” | 给他们看该字母的 `work/crops/<id>.png`；提供重拍或平滑的选项 |
| “字母错了” / 交换 | 编辑 labels.json，重新构建 |
| “给我 woff2 / web 格式” | `build … --formats ttf,woff,woff2,css` |
| 自定义预览文本 | `$DYF preview -d work --text "…"`（构建之后） |

所有精修命令都基于已存储的裁剪图重新构建——除非墨迹本身有问题，否则无需重新拍照。

## 易读性报告（交付后提供） {#legibility-report-offer-after-delivering}

```bash
$DYF preview -d work --text "minimum mill rn m cl d I l 1 O 0 quick brown fox" -o work/legibility.png
```

阅读它并给出诚实而友善的评价：用于正文时的得分（满分 10 分）、最容易混淆的 2–3 组字母（rn→m、cl→d、I/l/1、O/0），以及一两个具体的改进方法（把这些字母写大一些、增加间距）。注意，用于展示用途（标题、便笺）比用于段落更宽容。永远不要把交付卡在这一步上——这是建议，不是阻碍。

## 故障排查 {#troubleshooting}

分割找到的色块远远过多 / 过少、灰色辅助线残留、阴影色块、圆珠笔笔画太淡 → 参阅 `references/troubleshooting.md`。
