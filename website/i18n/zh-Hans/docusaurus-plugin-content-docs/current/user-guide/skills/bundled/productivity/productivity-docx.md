---
title: "Docx — 创建、读取、编辑、模板化和审阅 Word .docx 文件"
sidebar_label: "Docx"
description: "创建、读取、编辑、模板化和审阅 Word .docx 文件"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Docx

创建、读取、编辑、模板化和审阅 Word .docx 文件。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/docx` |
| 版本 | `1.1.0` |
| 作者 | Nous Research |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `word`, `docx`, `documents`, `office`, `templates`, `revisions`, `comments` |
| 相关 skill | [`pdf`](/user-guide/skills/bundled/productivity/productivity-pdf), [`xlsx`](/user-guide/skills/bundled/productivity/productivity-xlsx), [`powerpoint`](/user-guide/skills/bundled/productivity/productivity-powerpoint) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Docx Skill

通过一组小型 CLI，借助 python-docx 创建、读取、编辑和模板化 Microsoft Word `.docx` 文件。它可以处理文本、样式、列表、表格、图片、页眉/页脚、`{{token}}` 模板替换、修订（列出/接受/拒绝）、批注（列出/添加/删除）、目录和页码域，以及文档包健康检查。它本身不渲染文档（生成 PDF 需要 LibreOffice——参见“转换为 PDF”），也不编辑旧版 `.doc` 文件。

## 使用时机 {#when-to-use}

- 用户要求生成 Word 文档（报告、信函、合同）。
- 你需要获取 `.docx` 的文本、大纲、样式或内嵌图片。
- 你必须修改现有 `.docx`：替换文本、编辑表格单元格、插入/删除段落、应用样式、合并碎片化的 run。
- 你有一个带 `{{placeholders}}` 的 `.docx` 模板，需要用数据填充。
- 文档中有需要审阅、接受或拒绝的修订。
- 你需要读取审阅者的批注，或添加/删除批注。
- 某个 `.docx` 打不开或表现异常，需要做损坏排查。
- 文档需要目录或“第 X 页，共 Y 页”页脚。
- 不适用于：`.doc`（旧版格式）、`.odt` 或所见即所得的排版工作。

## 前置条件 {#prerequisites}

- Python 3.10+，并安装 `python-docx`：
  `pip install python-docx`（导入名为 `docx`；lxml 会随之安装）。
- 批注 `add` 在 python-docx >= 1.2 上使用原生 API，在旧版本上使用 XML 回退方案——两者都是自动的。
- 对于图片块：图片文件必须存在于本地（PNG/JPEG）。

## 运行方式 {#how-to-run}

所有辅助脚本都位于本文件旁的 `scripts/` 目录中。通过 `terminal` 工具运行它们；每个脚本都支持 `--help`，并将 JSON 输出到 stdout。

```bash
python scripts/docx_create.py spec.json out.docx
python scripts/docx_read.py out.docx --text
python scripts/docx_edit.py replace out.docx --find old --replace new
python scripts/docx_template.py tpl.docx values.json filled.docx
python scripts/docx_revisions.py list out.docx
python scripts/docx_comments.py list out.docx
python scripts/docx_validate.py out.docx
```

## 速查表 {#quick-reference}

| 任务 | 命令 |
| --- | --- |
| 从 JSON 规格创建 | `docx_create.py spec.json out.docx` |
| 全文（正文+表格+页眉/页脚） | `docx_read.py f.docx --text` |
| 标题大纲 + 表格形状 | `docx_read.py f.docx --structure` |
| 实际使用的样式 | `docx_read.py f.docx --styles` |
| 提取内嵌图片 | `docx_read.py f.docx --images outdir/` |
| 检测修订/批注 | `docx_read.py f.docx --revisions` |
| 查找/替换（保留格式） | `docx_edit.py replace f.docx --find A --replace B -o out.docx` |
| 设置表格单元格 | `docx_edit.py set-cell f.docx --table 0 --row 1 --col 2 --text X` |
| 在索引 N 之前插入段落 | `docx_edit.py insert f.docx --index N --text X --style Normal` |
| 删除段落 N | `docx_edit.py delete f.docx --index N` |
| 对段落 N 应用样式 | `docx_edit.py style f.docx --index N --style "Heading 1"` |
| 合并格式相同的相邻 run | `docx_edit.py normalize f.docx -o out.docx` |
| 在段落 N 之前插入目录域 | `docx_edit.py toc f.docx --index N -o out.docx` |
| “第 X 页，共 Y 页”页脚域 | `docx_edit.py page-numbers f.docx` |
| 填充 `{{tokens}}` | `docx_template.py tpl.docx values.json out.docx --strict` |
| 列出修订（id/作者/日期/文本） | `docx_revisions.py list f.docx` |
| 接受 / 拒绝全部修订 | `docx_revisions.py accept-all f.docx -o out.docx`（或 `reject-all`） |
| 接受 / 拒绝单条修订 | `docx_revisions.py accept f.docx --id 3 -o out.docx` |
| 列出批注（+锚定文本） | `docx_comments.py list f.docx` |
| 添加锚定到文本的批注 | `docx_comments.py add f.docx --target "phrase" --text "note" --author You` |
| 按 id 删除批注 | `docx_comments.py delete f.docx --id 0` |
| 对文档包做健康检查 | `docx_validate.py f.docx`（有错误时退出码为 1） |

## 操作步骤 {#procedure}

1. **创建。** 用 `write_file` 编写一个 JSON 规格，然后运行 `scripts/docx_create.py`。规格支持：`page`（纸张尺寸 + 页边距，单位 mm）、`header`/`footer` 字符串、`footer_page_numbers`（添加一个“第 X 页，共 Y 页”域页脚）、`styles`（自定义段落样式，含字体、字号、粗体/斜体、十六进制 `color`），以及 `blocks`——`heading`（级别 1-9）、`paragraph`（使用 `text`，或使用 `runs` 列表，其中每个 run 可以设置 `bold`/`italic`/`underline`）、`bullet_list`、`numbered_list`、`table`（`header` 行渲染为粗体、`rows`、可选的内置表格 `style`，例如 `Table Grid`）、`image`（`path`，可选 `width_mm`）、`toc`（目录域）以及 `page_break`。完整的规格格式记录在 `scripts/docx_create.py` 文件顶部。
2. **读取。** 使用 `scripts/docx_read.py`，并且只带一个模式标志。`--text` 以 JSON 返回正文段落、所有表格单元格文本以及页眉/页脚文本。`--structure` 返回标题大纲以及段落/表格/节的数量。`--images DIR` 将 `word/media/` 下的每个文件从文档包中复制出来。
3. **编辑。** 使用 `scripts/docx_edit.py`。`replace` 会遍历正文、表格（包括嵌套表格）、页眉和页脚，并保留 run 的格式；加上 `--body-only` 可跳过页眉/页脚。传入 `-o out.docx` 以保留原文件；省略它则原地编辑。`insert`/`delete`/`style`/`toc` 使用的段落索引对应 `--structure`/`--text` 的正文顺序。对经过大量 Word 编辑的文档，先运行 `normalize`——它会合并格式完全相同的相邻 run，使后续的查找替换能够可靠匹配。
4. **审阅修订。** `docx_revisions.py list` 会报告正文、表格、页眉或页脚中任何位置的每一个 `w:ins` 和 `w:del`（id、作者、日期、受影响文本）。`accept-all` / `reject-all` 批量处理它们；`accept`/`reject --id N` 处理单条修订。接受会保留插入内容并丢弃被删除的文本；拒绝则相反。
5. **批注。** `docx_comments.py list` 返回每条批注的 id、作者、日期、正文文本以及它所锚定的文档文本。`add --target "some phrase"` 将新批注锚定到该短语的第一次出现处（必要时会拆分 run；格式会保留）。`delete --id N` 删除批注及其标记，不触碰文档文本。
6. **模板。** 在文档中放入 `{{name}}` 风格的 token。使用一个包含取值的 JSON 对象运行 `scripts/docx_template.py`。使用 `--strict` 可在仍有 token 未填充时报错；无论哪种情况，JSON 输出都会列出 `filled` 计数和 `unfilled_tokens`。
7. **验证**（始终执行）：用 `--text` 或 `--structure` 重新读取输出，并对通过修订/批注手术生成的任何文件运行 `docx_validate.py`。

## 转换为 PDF {#converting-to-pdf}

无需脚本。安装了 LibreOffice 时，以无头模式转换：

```bash
soffice --headless --convert-to pdf --outdir outdir/ file.docx
```

先检查是否可用（`command -v soffice || command -v
libreoffice`）。如果两者都不存在，告诉用户当前环境无法进行 PDF 转换，而不是临时拼凑方案——python-docx 无法渲染 PDF，而版式保真需要真正的渲染器。

## 常见陷阱 {#pitfalls}

- **token 被拆分到多个 run 中。** Word 经常把文本拆成多个 run。替换辅助脚本会合并匹配到的 run（替换内容继承第一个 run 的格式）；先运行 `docx_edit.py normalize` 可以减少碎片化，便于后续所有编辑。
- **修订覆盖范围。** `docx_revisions.py` 能处理 run 级别的插入和删除（占绝大多数）。段落标记和表格行修订、格式变更记录以及移动会被 `--revisions` 检测到，但不会自动处理——参见 `references/revisions-and-comments.md`，并将这些交给 Word 处理。
- **批注线程。** 回复和“已解决”状态存放在 `commentsExtended.xml` 中，本 skill 会忽略它；它添加的批注都是普通的顶层批注。
- **域结果由 Word 计算。** `toc`、`page-numbers` 以及 `toc`/`footer_page_numbers` 规格选项写入的是*域代码*。Word/LibreOffice 会在打开文件时填充实际的条目和页码（Word 可能会提示更新域）；python-docx 从不计算它们，因此在此之前显示的是占位文本。
- **校验是健康检查，不是 schema 校验。** `docx_validate.py` 会校验 zip、必需部件、关系目标、图片魔数字节以及被引用的样式。它不是 XSD 校验——文件可能通过校验却仍包含 Word 不认可的 XML。
- **样式名必须存在。** 应用文档中未定义的样式会引发 `KeyError`。`Heading 1`、`List Bullet`、`List Number`、`Table Grid` 等内置样式存在于默认模板中；自定义样式必须先在创建规格中声明。
- **编号列表会重新开始。** `List Number` 依赖 Word 的默认编号；同一文档中的多个独立列表可能会延续编号而不是重新开始。对需要精确多列表编号的用户要给出提醒。
- **写入单元格会替换格式。** `set-cell` 使用 `cell.text = ...`，这会把该单元格中的 run 重置为普通格式。
- **编码。** 所有 JSON 规格/取值文件都显式以 UTF-8 读取；编写你自己的胶水代码时，切勿依赖区域设置默认值。
- **不要解压后用 sed 改 XML。** 通过脚本（或 python-docx）进行编辑；在 `document.xml` 中做原始文本替换很容易损坏文件。`patch`/`write_file` 只用于 JSON 输入，绝不要用于 `.docx` 本身。

## 验证 {#verification}

- 创建/编辑/模板化之后，运行 `docx_read.py out.docx --text`，检查预期的字符串是否出现（以及旧字符串是否已消失）。
- 接受/拒绝之后，`docx_revisions.py list` 应返回 `[]`（或只剩你有意保留的 id）；批注手术之后，`docx_comments.py list` 应反映出变化，并且 `--text` 输出必须保持不变。
- 对健康的文档包，`docx_validate.py out.docx` 以 0 退出并输出 `"ok": true`——在任何修订/批注/域操作之后都要运行它。
- 对模板，使用 `--strict` 运行，或检查 `unfilled_tokens == []`。
- 结构检查：`--structure` 应显示预期的标题大纲和表格形状；`--styles` 用于确认自定义样式已应用。
