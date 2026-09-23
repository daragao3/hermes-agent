---
title: "Powerpoint —— 使用 python-pptx 创建、读取、编辑 .pptx 演示文稿"
sidebar_label: "Powerpoint"
description: "使用 python-pptx 创建、读取、编辑 .pptx 演示文稿"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Powerpoint

使用 python-pptx 创建、读取、编辑 .pptx 演示文稿。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/powerpoint` |
| 版本 | `1.1.0` |
| 作者 | Nous Research |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `pptx`, `powerpoint`, `presentations`, `slides`, `office`, `python-pptx` |
| 相关 skill | [`docx`](/user-guide/skills/bundled/productivity/productivity-docx), [`xlsx`](/user-guide/skills/bundled/productivity/productivity-xlsx), [`pdf`](/user-guide/skills/bundled/productivity/productivity-pdf) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Powerpoint Skill

使用 python-pptx 库创建、检查和编辑 PowerPoint（.pptx）演示文稿。五个辅助脚本分别覆盖：基于 JSON 规格创建演示文稿、结构化回读、原地编辑、基于模板生成符合品牌规范的演示文稿，以及幻灯片渲染——全部离线完成，无需安装 PowerPoint。

## 使用时机 {#when-to-use}

- 用户要求制作幻灯片、报告演示文稿或 pitch deck。
- 需要从别人分享的 .pptx 中提取文本、备注、表格、图表数据或图片。
- 需要更新现有演示文稿：替换文本、刷新或修补图表数据、更换 logo、复制/删除/重排幻灯片，设置背景、页脚、超链接或演讲者备注。
- 必须基于公司的 .pptx 模板生成符合品牌规范的演示文稿。
- 不要将其用于 .ppt（旧版二进制）文件——如果有 LibreOffice，先用 `soffice --convert-to pptx old.ppt` 转换。

## 前置条件 {#prerequisites}

- Python 3.10+，并已安装 `python-pptx`（`pip install python-pptx`）。
- 可选：LibreOffice（`soffice`）加 poppler（`pdftoppm` 或 `pdftocairo`），用于将幻灯片渲染为 PNG 以及导出 PDF。`pptx_render.py` 会用 `shutil.which` 检测两者，缺失时优雅降级（报告 `{"rendered": false, "missing": [...]}`，退出码 0）——所有创建/读取/编辑操作在没有它们的情况下都能正常工作。
- 通过 `terminal` 检查可用性：`python -c "import pptx; print(pptx.__version__)"` 和 `which soffice pdftoppm`。

## 运行方式 {#how-to-run}

所有脚本都位于 `scripts/`，支持 `--help`，将 JSON 输出到 stdout，失败时以非零退出码退出。用 `terminal` 运行它们：

```bash
python scripts/pptx_create.py deck.json out.pptx
python scripts/pptx_read.py deck.pptx --outline      # 完整的 JSON 大纲
python scripts/pptx_read.py deck.pptx --notes        # 演讲者备注
python scripts/pptx_read.py deck.pptx --images ./img # 导出图片
python scripts/pptx_edit.py deck.pptx --replace-text "Old Corp" "New Corp"
python scripts/pptx_edit.py deck.pptx --chart-data update.json
python scripts/pptx_edit.py deck.pptx --duplicate-slide 2
python scripts/pptx_edit.py deck.pptx --remove-slide 3 --move-slide 2 0
python scripts/pptx_from_template.py brand.pptx out.pptx --values vals.json
python scripts/pptx_render.py deck.pptx --outdir ./render  # 幻灯片 PNG
```

用 `write_file` 编写 JSON 规格；用 `read_file` 检查脚本输出和生成的 JSON。

## 快速参考 {#quick-reference}

| 任务 | 命令 |
|---|---|
| 基于规格新建演示文稿 | `pptx_create.py spec.json out.pptx` |
| 16:9 与 4:3 | 在规格中写 `"slide_size": "16:9"` 或 `"4:3"` |
| 以 JSON 输出大纲 | `pptx_read.py deck.pptx --outline` |
| 导出图片 | `pptx_read.py deck.pptx --images DIR` |
| 替换文本 | `pptx_edit.py deck.pptx --replace-text OLD NEW` |
| 替换图表数据 | `pptx_edit.py deck.pptx --chart-data spec.json` |
| 修补单个系列 | 同一标志，规格中使用 `"ops"`（见下文） |
| 更换图片 | `pptx_edit.py deck.pptx --swap-image N NAME new.png` |
| 复制幻灯片 | `pptx_edit.py deck.pptx --duplicate-slide N` |
| 删除幻灯片 | `pptx_edit.py deck.pptx --remove-slide N` |
| 重排幻灯片 | `pptx_edit.py deck.pptx --move-slide FROM TO` |
| 幻灯片背景 | `pptx_edit.py deck.pptx --set-background N RRGGBB` |
| 为文本段添加超链接 | `pptx_edit.py deck.pptx --hyperlink N TEXT URL` |
| 开启幻灯片编号 | `pptx_edit.py deck.pptx --enable-slide-number N` |
| 页脚文本 | `pptx_edit.py deck.pptx --set-footer N TEXT` |
| 设置备注 | `pptx_edit.py deck.pptx --set-notes N TEXT` |
| 追加备注 | `pptx_edit.py deck.pptx --append-notes N TEXT` |
| 填充模板 | `pptx_from_template.py tpl.pptx out.pptx --values v.json` |
| 渲染幻灯片 PNG | `pptx_render.py deck.pptx --outdir DIR` |

## 操作步骤 {#procedure}

### 1. 创建演示文稿 {#1-create-a-deck}

编写一个 JSON 规格（完整格式见 `pptx_create.py --help`），然后运行 `pptx_create.py`。每张幻灯片可以设置：`layout`（title、title_content、section、two_content、title_only、blank）、`title`、`subtitle`、`bullets`（字符串，或包含 `level` 0-4、`size` 磅值、`bold`、`italic`、`font`、`color` 十六进制色值、用于超链接的 `link` URL 的字典）、`background`（纯色十六进制）、`footer`（文本；启用版式的页脚占位符）、`slide_number`（true；启用版式的幻灯片编号占位符）、`images`（路径 + 以英寸为单位的 left/top/width/height）、`tables`（`rows` 为列表的列表）、`shapes`（rectangle、rounded_rectangle、oval、diamond、right_arrow、chevron，带 `fill` 十六进制色值 + 可选的 `text`）、`charts`（bar、bar_h、line、pie，带 `categories` + `series`），以及 `notes`（演讲者备注）。

### 2. 读取演示文稿 {#2-read-a-deck}

`pptx_read.py deck.pptx --outline` 返回幻灯片尺寸、版式清单，以及每张幻灯片的：版式名称、所有形状文本、表格单元格、图片清单（文件名/扩展名/字节数）、图表的类别/系列/数值，以及演讲者备注。使用 `--images DIR` 将嵌入的图片导出为文件，如果需要查看图片内容，再对任意导出的图片调用 `vision_analyze`。

### 3. 编辑演示文稿 {#3-edit-a-deck}

`pptx_edit.py` 可在一次处理中组合多个操作；使用 `--output` 保留原文件。文本替换会扫描幻灯片形状、表格单元格和备注。图片替换会重新指向图片的关系 id（relationship id），因此位置和大小保持不变。删除幻灯片会移除对应关系和 `<p:sldId>` 条目；重排则在 `<p:sldIdLst>` 中移动 `<p:sldId>` 元素（python-pptx 对这两者都没有公开 API——脚本在 XML 层面完成这些工作）。`--duplicate-slide N` 会追加幻灯片 N 的一个独立深拷贝：形状 XML 以及图片/媒体/超链接关系都会被克隆并重新映射 rId，因此编辑副本永远不会影响原幻灯片。含图表的幻灯片会被拒绝（见常见陷阱）。`--set-notes`/`--append-notes` 用于编辑演讲者备注；`--set-background`、`--hyperlink`、`--enable-slide-number` 和 `--set-footer` 负责演示文稿的润色。

图表更新通过 `--chart-data` 接收一个 JSON 规格。完整替换：`{"slide": 0, "chart": 0, "categories": [...], "series": {...}}`。如需精细修改，改为传入 `"ops"`——一个由 `{"op": "update_series", "name": ..., "values": [...]}`、`add_series`、`remove_series`、`rename_category`（`from`/`to` 或 `index`）和 `set_title` 组成的列表。python-pptx 只能替换图表的整个数据集（`replace_data`），因此这些操作的实现方式是读取现有数据 → 修改 → 替换；按部件操作的体验只是一层封装，任何无法表示为类别 + 数值系列的图表数据都会在这次往返中被规范化。

### 4. 基于模板构建 {#4-build-from-a-template}

`pptx_from_template.py` 会打开一个品牌 .pptx，用 values JSON 替换幻灯片/表格/备注中的每个 `{{token}}`，并且可以追加使用模板自身版式（按版式名称或索引）的新幻灯片，使其继承母版的字体和颜色。提示：如果想从一个没有幻灯片的模板开始，可以事后用 `pptx_edit.py --remove-slide` 删除已有的幻灯片。

### 5. 视觉验证 {#5-visual-verification}

`pptx_render.py deck.pptx --outdir ./render` 会用 `soffice --headless` 将演示文稿转换为 PDF，再用 `pdftoppm`（或 `pdftocairo`）将其拆分为每张幻灯片一个 PNG。输出的 JSON 会列出 PNG 路径——用 `vision_analyze` 逐一检查。当任一工具缺失时，脚本以退出码 0 退出，并给出 `{"rendered": false, "missing": [...]}` 及指导说明；此时退而使用 `pptx_read.py` 生成的 JSON 大纲，它能验证内容和结构，只是无法验证视觉效果。

## 转换为 PDF {#converting-to-pdf}

如果已安装 LibreOffice，可直接将完成的演示文稿导出为 PDF：

```bash
soffice --headless --convert-to pdf --outdir ./out deck.pptx
```

输出位于 `./out/deck.pdf`。主机上未安装的字体会被替换，因此在交付 PDF 之前先进行渲染验证（操作步骤第 5 步）。不存在离线的纯 Python .pptx→PDF 路径；如果没有 `soffice`，请如实说明，而不是给出近似结果。

## 常见陷阱 {#pitfalls}

- **文本段拆分**：PowerPoint 会在拼写检查和编辑边界处把段落文本拆分成多个 run（文本段）。`--replace-text` 会先合并格式完全相同的相邻 run，因此跨越这类 run 的匹配在替换时能完整保留格式。只有当匹配跨越*格式确实不同*的 run 时，才会用第一个 run 的格式重写整个段落——替换后请检查这些幻灯片。
- **含图表的幻灯片无法复制**：每个图表关系都嵌入了一个独立的 XLSX 工作簿部件；可靠地克隆这张关系图不受支持，因此 `--duplicate-slide` 会干净地拒绝含图表的幻灯片，而不是损坏演示文稿。请改为在新幻灯片上重建图表。外部超链接和图片/媒体关系会被带过去；版式和备注关系会重新创建。
- **图表 ops 只是一层封装**：python-pptx 替换的是整个数据集；`"ops"` 会让现有绘图数据经由 `replace_data` 往返一次，且无法更改图表*类型*。
- **重排在 XML 层面进行**：python-pptx 没有受支持的重排 API。`--move-slide` 直接操作 `<p:sldIdLst>`；对普通演示文稿是安全的，但事后请重新读取演示文稿确认。
- **不支持在不同演示文稿之间复制幻灯片**——复制只在同一个演示文稿内有效，因为那里的版式和母版是共享的。
- 启用页脚/幻灯片编号会从幻灯片的版式中复制占位符；在没有这些占位符的版式上，`--set-footer` 会失败并给出明确提示（请改为添加文本框）。
- 超链接作用于整个 run；`--hyperlink` 会为该幻灯片上包含给定文本的每个 run 添加链接。
- python-pptx 的默认模板是 4:3；除非规格另有指定，创建脚本会设置为 16:9。自定义模板保留其自身尺寸。
- 版式索引因模板而异。对于品牌模板，先列出版式名称：`pptx_read.py template.pptx --outline`（`layouts_available`）。
- 在空白版式上 `slide.shapes.title` 为 None——创建脚本已处理这一点，但编写临时的 python-pptx 代码时要记住。
- 写入规格文件时始终传入 `encoding="utf-8"`；像 `{{city}}` 这样的 token 可能会被填入非 ASCII 值。

## 验证 {#verification}

1. 每次创建/编辑之后，运行 `pptx_read.py OUT.pptx --outline`，检查幻灯片数量、文本、表格、备注和图表数值是否符合预期。
2. 先用 `--images DIR` 导出，再检查文件大小，以确认图片已嵌入。
3. 用 `pptx_render.py deck.pptx --outdir ./render` 渲染每张幻灯片，并用 `vision_analyze` 逐一检查每个 PNG——这能发现大纲无法发现的形状重叠、文本截断和颜色问题。如果缺少渲染工具，脚本会明确说明；此时依赖大纲即可。
4. 内置测试套件是完整的契约：`python -m pytest tests/ -q`（需要 python-pptx + pytest）。
