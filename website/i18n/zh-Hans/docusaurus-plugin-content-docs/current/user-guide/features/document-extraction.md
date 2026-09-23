---
sidebar_position: 3
title: "文档提取"
description: "read_file 如何将 PDF、Office 文档和 notebook 转换为文本——以及当 PDF 是扫描图像时该怎么办"
---

# 文档提取

`read_file` 工具会自动将常见文档格式转换为可读文本，因此 agent 可以像读取源代码一样查看 PDF 或电子表格。

## 支持的格式 {#supported-formats}

| 格式 | 扩展名 | 转换器 | 可用性 |
|--------|-----------|-----------|--------------|
| Jupyter notebook | `.ipynb` | 内置（stdlib） | 始终可用 |
| Word 文档 | `.docx` | 内置（stdlib） | 始终可用 |
| Excel 工作簿 | `.xlsx` | 内置（stdlib） | 始终可用 |
| PDF | `.pdf` | 可选的 `anydoc` 转换器 | 首次使用时自动安装* |
| 旧版 Office | `.doc`, `.ppt`, `.xls`, `.pptx` 及其变体 | 可选的 `anydoc` 转换器 | 首次使用时自动安装* |
| OpenDocument | `.odt`, `.ods`, `.odp` | 可选的 `anydoc` 转换器 | 首次使用时自动安装* |
| 富文本 / 电子书 | `.rtf`, `.epub` | 可选的 `anydoc` 转换器 | 首次使用时自动安装* |

\* 可选转换器是 `firecrawl-anydoc` 包，在允许安装的环境中按需延迟安装（`config.yaml` 中的 `security.allow_lazy_installs`）。没有它时，三种 stdlib 格式仍然可用；其他格式会回退到二进制文件防护。

转换输出为 Markdown，通过 `read_file` 常规的 `offset`/`limit` 窗口分页。超过 50 MB 的文档会被拒绝，以保证工具轮次有界。

提取可与远程终端后端（Docker、Modal、SSH）配合使用：文件字节会跨越后端边界传输并在宿主侧转换，因此沙箱内的文档读起来与本地文档完全一样。

## 扫描版 PDF：覆盖率警告 {#scanned-pdfs-the-coverage-warning}

PDF 转换**只读取文本层**。扫描图像构成的页面——常见于法律文件、转售资料包、已签署的合同、传真——没有文本层，会被静默地转换为空。典型特征是只有章节标题而正文为空。

当相当比例的页面没有产出文本时（超过文档的 20%，或绝对数量达到 10 页以上），`read_file` 会在提取结果前加上一条警告。每个无法读取的空缺都会用它之前最后提取到的文本来标注——通常是一个章节分隔符——这样 agent 就可以只针对真正需要的空缺进行处理，而不必对整个文档做 OCR：

```
[EXTRACTION COVERAGE WARNING: 198 of 311 pages in this PDF yielded no
text. ... Unreadable gaps, each labeled with the last text extracted
before it:
  pages 42-77 (36 pages) — after "Antigua Maintenance Corp Bylaws" (p41)
  pages 92-213 (122 pages) — after "... Covenants, Codes and Regulations" (p91)
  page 224 (1 page) — after "... Insurance Declaration Pages" (p223)
Decide which gaps you actually need — do NOT OCR or render everything. ...]
```

警告会列出确切的页码范围和恢复途径：

1. **少量页面——渲染 + 视觉。** 将页面转换为图像，并用视觉工具读取：
   ```bash
   pdftoppm -jpeg -r 150 -f 92 -l 94 document.pdf /tmp/page
   ```
   然后用 `vision_analyze` 检查每张图像。零额外依赖（检测本身就需要 poppler）。
2. **大量页面——OCR。** `ocr-and-documents` skill 涵盖使用 marker-pdf 进行批量 OCR（支持 90 多种语言，能处理公式和表格；安装约 3-5 GB）。

检测使用 poppler 的 `pdftotext` 统计每页文本量。如果未安装 poppler，提取仍然可以工作——覆盖率检查会被静默跳过。

:::tip
agent 会自行处理该警告——它会主动提出渲染缺失页面或对其做 OCR。如果你自己阅读提取结果，请把"有标题但正文为空"视为扫描章节，而不是缺失章节。
:::
