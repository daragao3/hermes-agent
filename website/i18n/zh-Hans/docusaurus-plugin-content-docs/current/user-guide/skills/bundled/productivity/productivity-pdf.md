---
title: "Pdf — PDF 文件：创建、读取、合并、填写、OCR、编辑文本"
sidebar_label: "Pdf"
description: "PDF 文件：创建、读取、合并、填写、OCR、编辑文本"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Pdf

PDF 文件：创建、读取、合并、填写、OCR、编辑文本。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/pdf` |
| 版本 | `1.1.0` |
| 作者 | Nous Research |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `pdf`, `documents`, `forms`, `ocr`, `text-extraction`, `reportlab`, `pypdf`, `pdfplumber`, `pymupdf`, `marker` |
| 相关 skill | [`docx`](/user-guide/skills/bundled/productivity/productivity-docx), [`xlsx`](/user-guide/skills/bundled/productivity/productivity-xlsx), [`powerpoint`](/user-guide/skills/bundled/productivity/productivity-powerpoint) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# PDF Skill

根据结构化规格创建 PDF，构建并填写 AcroForm 表单（带布局检查和可视化叠加图），提取文本/表格/元数据，合并/拆分/旋转/加水印/加盖页面，导出页面图像，管理元数据和附件，以及加密/解密——使用 pypdf、reportlab 和 pdfplumber。另有两项并入的能力放在 references/ 中（执行相应任务前请先阅读对应文件）：

- **扫描件/纯图像 PDF 与 OCR**（pymupdf 快速路径、marker-pdf 高质量路径，scripts/extract_pymupdf.py + scripts/extract_marker.py）：`references/ocr-extraction.md`
- **通过自然语言提示编辑现有 PDF 中的文本**（nano-pdf CLI）：`references/nano-pdf-editing.md`

## 使用场景 {#when-to-use}

- 以 PDF 形式生成报告、发票或多页文档。
- 根据 JSON 规格构建可填写的 AcroForm（文本/复选框/单选/下拉），并先检查布局。
- 从 PDF 中提取文本、表格（JSON/CSV）、元数据或表单字段值。
- 合并、拆分、旋转、提取页面子集、加水印、在指定坐标加盖文本/图像、添加书签或压缩 PDF。
- 将页面导出为 PNG，用于可视化审阅或交给 OCR 处理；设置/清除文档元数据；添加/提取文件附件。
- 填写或扁平化 AcroForm 表单；使用密码加密或解密。
- **不**适用于扫描件/纯图像 PDF（请使用 `references/ocr-extraction.md`），也**不**适用于像素级精确的 HTML 转 PDF 渲染（请使用无头浏览器）。

## 前置条件 {#prerequisites}

- Python 3.10+，并安装 `pypdf`、`reportlab`、`pdfplumber`：
  `python -m pip install pypdf reportlab pdfplumber`
- 可选，用于页面栅格化（`pdf_page_image.py`、叠加图渲染）：`python -m pip install pypdfium2`，或 PATH 中有 poppler 的 `pdftoppm`。脚本按 pypdfium2 → pdftoppm 的顺序回退，两者都不存在时报告 `{"rendered": false, "missing": [...]}`（退出码 0）。
- 每个辅助脚本都会延迟检查导入，缺少依赖时会打印安装提示。

## 如何运行 {#how-to-run}

所有辅助脚本都位于 `scripts/` 中，且都是 argparse CLI——使用 `terminal` 工具运行它们；每个脚本都支持 `--help`。它们严格以 UTF-8 读写 JSON，将 JSON 结果打印到 stdout，失败时以非零退出码退出。

```bash
python scripts/pdf_create.py spec.json -o out.pdf         # build PDF from JSON spec
python scripts/pdf_make_form.py formspec.json -o form.pdf # build fillable AcroForm from JSON spec
python scripts/pdf_form_layout.py formspec.json           # lint form layout BEFORE building
python scripts/pdf_form_layout.py formspec.json --render-overlay boxes.png [--pdf form.pdf]
python scripts/pdf_read.py doc.pdf --text                 # per-page text (JSON)
python scripts/pdf_read.py doc.pdf --tables --csv-dir t/  # tables to JSON + CSV files
python scripts/pdf_read.py doc.pdf --meta                 # metadata, page sizes, encrypted/scanned flags
python scripts/pdf_read.py form.pdf --fields              # form fields: name, type, value
python scripts/pdf_merge.py a.pdf b.pdf -o merged.pdf [--bookmarks]
python scripts/pdf_split.py doc.pdf --pages 1-3,7 -o part.pdf [--rotate 90]
python scripts/pdf_fill_form.py form.pdf --fields-json values.json -o filled.pdf [--flatten]
python scripts/pdf_secure.py doc.pdf --encrypt -o enc.pdf --user-password your-password
python scripts/pdf_secure.py enc.pdf --decrypt -o dec.pdf --password your-password
python scripts/pdf_watermark.py doc.pdf --stamp mark.pdf -o stamped.pdf [--under]
python scripts/pdf_stamp.py doc.pdf -o out.pdf --text "DRAFT" --x 150 --y 400 \
    --font-size 60 --rotation 45 --opacity 0.3 --color "#cc0000" [--pages 1-3]
python scripts/pdf_stamp.py doc.pdf -o out.pdf --image sig.png --x 400 --y 60 --width 120
python scripts/pdf_page_image.py doc.pdf --pages 1-3 --dpi 150 --out-dir imgs/
python scripts/pdf_meta.py doc.pdf --set-meta --title "T" --author "A" -o out.pdf
python scripts/pdf_meta.py doc.pdf --attach data.csv -o out.pdf
python scripts/pdf_meta.py doc.pdf --list-attachments | --extract-attachments dir/
```

## 快速参考 {#quick-reference}

| 任务 | 工具 | 命令 / API |
|---|---|---|
| 创建文档（标题、表格、图像） | reportlab platypus | `pdf_create.py spec.json -o out.pdf` |
| 构建可填写表单 | reportlab acroForm | `pdf_make_form.py formspec.json -o form.pdf` |
| 检查表单布局 / 叠加图 | 纯 python + PIL | `pdf_form_layout.py formspec.json [--render-overlay o.png]` |
| 逐页文本 | pdfplumber | `pdf_read.py f.pdf --text` |
| 表格 → JSON/CSV | pdfplumber | `pdf_read.py f.pdf --tables` |
| 元数据 / 尺寸 / 加密 / 扫描件 | pypdf + pdfplumber | `pdf_read.py f.pdf --meta` |
| 合并（+ 大纲） | pypdf | `pdf_merge.py a.pdf b.pdf -o m.pdf` |
| 拆分 / 提取 / 旋转 | pypdf | `pdf_split.py f.pdf --pages 2-5 --rotate 90` |
| 列出 / 填写 / 扁平化表单 | pypdf | `pdf_read.py --fields`, `pdf_fill_form.py` |
| 加密 / 解密（AES-256） | pypdf | `pdf_secure.py --encrypt/--decrypt` |
| 为 PDF 页面加水印 / 加盖 | pypdf | `pdf_watermark.py f.pdf --stamp w.pdf` |
| 在指定坐标加盖文本/图像 | reportlab + pypdf | `pdf_stamp.py f.pdf --text "Sign here" --x 400 --y 60` |
| 页面 → PNG（审阅 / 交给 OCR） | pypdfium2 或 pdftoppm | `pdf_page_image.py f.pdf --pages 1-3 --out-dir imgs/` |
| 设置/清除元数据、附件 | pypdf | `pdf_meta.py --set-meta / --attach / --extract-attachments` |
| 压缩内容流 | pypdf | `pdf_split.py f.pdf --pages 1-N --compress` |

## 流程 {#procedure}

1. **先检查。** 运行 `pdf_read.py file.pdf --meta`。检查 `encrypted`（若为 true，先用 `pdf_secure.py --decrypt` 解密）以及 `likely_scanned_pages`。如果页面是纯图像，用 `pdf_page_image.py --pages <scanned> --dpi 300 --out-dir imgs/` 导出，并将 PNG 交给 `references/ocr-extraction.md` skill 处理——不要把空文本报告为"没有内容"。
2. **创建。** 用 `write_file` 编写 JSON 规格（元素：`heading`、`paragraph`、`table`、`image`、`pagebreak`；可选的 `title`/`author` 元数据；页码会自动添加），然后运行 `pdf_create.py`。如果布局很重要，对渲染出的页面图像使用 `vision_analyze` 进行可视化验证。
3. **提取。** `--text` 给出逐页字符串的 JSON 列表；`--tables` 给出每页的行数组，还可以输出 CSV 文件。用 `read_file` 读取结果；绝不要直接肉眼查看二进制 PDF。
4. **处理。** `pdf_merge.py` 负责拼接，并可为每个源文件添加一个书签；`pdf_split.py` 处理页面范围（从 1 开始，例如 `1-3,5,9-`）、以 90° 为步长的旋转以及 `--compress`。加水印的方法是准备一个单页的印章 PDF（例如通过 `pdf_create.py`），再用 `pdf_watermark.py` 叠加；对于一行式的印章（"sign here"、斜向 DRAFT、角标），使用 `pdf_stamp.py` 在明确的坐标处加盖文本或图像。
5. **构建表单。** 编写一个表单规格 JSON（字段带有以 PDF 点为单位的 `label_box`/`entry_box`——见 `references/forms.md`），用 `pdf_form_layout.py` 检查并修复每个报告的问题，可选地用 `vision_analyze` 审阅 `--render-overlay` 生成的 PNG，然后用 `pdf_make_form.py` 构建，并用 `pdf_read.py --fields` 确认。
6. **填写表单。** 列出字段（`--fields`）以了解确切的名称和类型，用 `write_file` 写一个 `{"FieldName": "value"}` 形式的 UTF-8 JSON（复选框接受 `true`/`false`；单选/选择值必须与字段的导出选项匹配），然后运行 `pdf_fill_form.py`。用 `--fields` 重新读取，确认值已写入。
7. **元数据与附件。** `pdf_meta.py --set-meta` 写入 Title/Author/Subject/Keywords（DocInfo）；`--clear-meta` 删除它们；`--attach`/`--list-attachments`/`--extract-attachments` 完成嵌入文件的往返。
8. **安全。** 使用不同的用户/所有者密码和 AES-256 加密。要移除一个你知道的密码，`--decrypt` 会写出一份未加密的副本。
9. 在报告成功之前先**验证**（见下文）。

## 常见陷阱 {#pitfalls}

- **扫描件 PDF**：`extract_text()` 为空且页面带有图像，意味着没有文本层。转交 `references/ocr-extraction.md` 处理；不要编造文本。
- **扁平化的局限**：`pdf_fill_form.py --flatten` 使用 pypdf 的扁平化支持，把控件外观转换为页面内容。它对普通文本字段和复选框很可靠，但可能丢弃或错误渲染特殊控件（富文本、自定义外观流、某些单选组）。用 `vision_analyze` 对扁平化后的输出进行可视化验证；如需万无一失的扁平化，可使用外部渲染器（例如 Ghostscript 或 `pdftoppm`+重新组装）作为回退。
- **NeedAppearances**：填写之后，只有存在外观流时查看器才会渲染值。填写脚本会设置 AcroForm 的 `NeedAppearances` 标志，让符合规范的查看器重新生成外观流；一些精简的查看器会忽略它——如果显示保真度很重要，就进行扁平化。
- **非拉丁字符的表单值**：值会被正确存储（UTF-16），但字段的默认字体可能缺少字形，因此即使数据能完整往返，查看器也可能显示为空白。用 `--fields` 验证，而不能只靠肉眼。
- **压缩的预期**：`--compress` 只对内容流进行 deflate 压缩。通常节省 0–20%；对以图像为主或流已压缩的 PDF 毫无作用。它不能替代图像降采样（那是 Ghostscript 的领域）。
- **权限标志并不具强制力**：所有者密码的权限位（禁止打印、禁止复制）只是查看器可能遵守的礼貌请求；任何库（包括 pypdf）都能读取并去除它们。只有用户密码会通过加密真正限制内容访问。绝不要把权限标志当作安全措施来介绍。
- **表格提取是启发式的**：pdfplumber 根据标线/单词对齐来检测表格；无边框或含合并单元格的表格可能需要调整 `table_settings` 或手动清理。
- **页码索引**：辅助 CLI 使用从 1 开始的页码；pypdf API 从 0 开始。脚本会进行转换——不要重复转换。
- **旋转印章的文本提取**：pdfplumber 的行分组会打乱旋转后的字形（45° 的 "DRAFT" 会被提取成零散字母）；请改用 `pypdf` 的 `extract_text()` 或渲染图像来验证旋转印章。
- **单选组**：reportlab 要求每组至少 2 个 `radio()` 控件，填写时需要带斜杠的导出值（`"/red"`），而单选控件的扁平化保真度最差——见 `references/forms.md`。
- **元数据范围**：`pdf_meta.py` 只写入经典的 DocInfo 字典；嵌入的 XMP 元数据（如果有）保持不变，在某些查看器中可能显示不同的值。
- **PDF/A 不在范围内**：pypdf/reportlab 无法生成或验证符合规范的 PDF/A。如果需要归档合规，通过 `terminal` 工具运行 Ghostscript（例如使用合适的 ICC 配置文件执行 `gs -dPDFA=2 -dPDFACompatibilityPolicy=1 -sColorConversionStrategy=UseDeviceIndependentColor -sDEVICE=pdfwrite -o out.pdf in.pdf`），并用 veraPDF 验证——两者都需要外部安装，且结果仍需验证，而不能想当然。
- 旋转角度必须是 90 的倍数；加密的输入在进行任何其他操作之前必须先解密。

## 验证 {#verification}

- 创建/合并/拆分之后：`pdf_read.py out.pdf --meta`——确认 `page_count`，旋转过的话还要确认逐页的 `rotation`。
- 提取之后：检查 JSON 非空，并抽查一个已知字符串或单元格。
- 表单设计循环：`pdf_form_layout.py spec.json` 必须以 0 退出；然后运行 `--render-overlay boxes.png --pdf form.pdf`，并用 `vision_analyze` 审阅 PNG（红色 = 带字段名的输入框，蓝色 = 标签框），询问是否存在重叠、错位以及与字段脱离的标签。按 规格 → 检查 → 叠加图 的顺序迭代，直到没有问题。
- 构建表单之后：`pdf_read.py form.pdf --fields` 会列出规格中的每个字段，且类型和选项正确。
- 填写表单之后：运行 `pdf_read.py filled.pdf --fields` 并比较值（精确匹配，包括非 ASCII 字符）。
- 加盖之后：重新提取文本（旋转印章用 pypdf），或用 `pdf_page_image.py` 渲染页面并用 `vision_analyze` 检查。
- 编辑元数据/附件之后：`pdf_read.py --meta` / `pdf_meta.py --list-attachments`，并重新提取一个附件进行逐字节比较。
- 加密之后：`--meta` 显示 `"encrypted": true`，且不带密码打开会失败；解密之后，文本提取结果与原文一致。
- 对于任何可视内容（水印、扁平化表单），渲染后用 `vision_analyze` 检查。
