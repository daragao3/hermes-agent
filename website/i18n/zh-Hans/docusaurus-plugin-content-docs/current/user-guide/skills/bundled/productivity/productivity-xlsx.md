---
title: "Xlsx —— 创建、读取、编辑 Excel .xlsx 工作簿和 CSV"
sidebar_label: "Xlsx"
description: "创建、读取、编辑 Excel .xlsx 工作簿和 CSV"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Xlsx

创建、读取、编辑 Excel .xlsx 工作簿和 CSV。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/xlsx` |
| 版本 | `1.1.0` |
| 作者 | Nous Research |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `excel`, `spreadsheet`, `xlsx`, `csv`, `openpyxl`, `productivity` |
| 相关 skill | [`docx`](/user-guide/skills/bundled/productivity/productivity-docx)、[`pdf`](/user-guide/skills/bundled/productivity/productivity-pdf)、[`powerpoint`](/user-guide/skills/bundled/productivity/productivity-powerpoint) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Xlsx Skill

使用 Python 和 openpyxl 处理 Excel .xlsx 工作簿：构建带公式和图表、样式丰富的多工作表工作簿，
检查或导出现有文件，编辑单元格和结构，以及与 CSV 互相转换。所有辅助脚本都是
argparse CLI，输出 JSON，并使用显式的 UTF-8 I/O。

## 使用时机 {#when-to-use}

- 创建 .xlsx 报表：多工作表、数字格式、样式、
  合并单元格、冻结窗格、自动筛选、条件格式、
  图表、数据验证下拉列表、原生 Excel 表格、定义
  名称、超链接、单元格批注、工作表保护。
- 读取工作簿：工作表清单，将数据导出为 JSON 或 CSV，
  列出公式与缓存值、批注、定义名称、表格。
- 编辑现有文件：设置单元格、追加行、插入/删除
  行/列（通过 `xlsx_restructure.py` 感知引用），
  复制/重命名工作表、表格、名称、批注、保护。
- 通过 LibreOffice 无头重新计算公式
  （`xlsx_recalc.py`）。
- 带类型推断和非 UTF-8 编码支持的 CSV 互操作。
- 不适用于旧版 .xls 二进制格式（先用 LibreOffice 转换：
  `soffice --headless --convert-to xlsx old.xls`）。

## 前置条件 {#prerequisites}

- Python 3.10+ 以及 `openpyxl`（`pip install openpyxl`）。不需要其他
  第三方包；其余全部来自标准库。
- 可选：LibreOffice（`soffice`），用于无头重新计算或
  格式转换。

## 运行方式 {#how-to-run}

用 `terminal` 工具从本 skill 的 `scripts/` 目录运行辅助脚本
（每个脚本都支持 `--help`）：

```bash
python scripts/xlsx_create.py spec.json report.xlsx   # 根据 JSON 规格构建
python scripts/xlsx_read.py report.xlsx --sheets      # 清单
python scripts/xlsx_read.py report.xlsx --json --sheet Data
python scripts/xlsx_read.py report.xlsx --formulas
python scripts/xlsx_edit.py report.xlsx --sheet Data --set B2=42 --recalc
python scripts/xlsx_restructure.py report.xlsx --sheet Data --insert-rows 3:2
python scripts/xlsx_recalc.py report.xlsx
python scripts/csv_to_xlsx.py data.csv out.xlsx --encoding utf-8
python scripts/xlsx_to_csv.py report.xlsx out.csv --sheet Data
```

用 `write_file` 编写 JSON 规格，用 `read_file` 或直接从 stdout
检查脚本的 JSON 输出。

## 快速参考 {#quick-reference}

| 任务 | 命令 |
|---|---|
| 根据规格创建工作簿 | `xlsx_create.py spec.json out.xlsx` |
| 工作表名称 + 尺寸 | `xlsx_read.py f.xlsx --sheets` |
| 将工作表导出为 JSON | `xlsx_read.py f.xlsx --json --sheet S` |
| 将工作表导出为 CSV | `xlsx_read.py f.xlsx --csv --out d.csv` |
| 列出公式 + 缓存值 | `xlsx_read.py f.xlsx --formulas` |
| 设置单元格 / 公式 | `xlsx_edit.py f.xlsx --set "A1==SUM(B:B)"` |
| 追加一行 | `xlsx_edit.py f.xlsx --append '[1,"x",true]'` |
| 插入 2 行，引用不平移 | `xlsx_edit.py f.xlsx --insert-rows 3:2` |
| 插入 2 行，引用平移 | `xlsx_restructure.py f.xlsx --insert-rows 3:2` |
| 删除一列，引用平移 | `xlsx_restructure.py f.xlsx --delete-cols B` |
| 创建原生表格 | `xlsx_edit.py f.xlsx --add-table Sales:A1:C9` |
| 在表格内追加 | `--table-append 'Sales=["West",5]'` |
| 列出表格 | `xlsx_edit.py f.xlsx --list-tables` |
| 定义名称 | `--define-name "Rates='Data'!$B$2:$B$9"` / `--delete-name Rates` / `xlsx_read.py f.xlsx --names` |
| 超链接 | `--hyperlink "A1=https://example.com|Docs"` |
| 单元格批注 | `--note "B2=Check this|Reviewer"`；通过 `xlsx_read.py f.xlsx --notes` 读取 |
| 保护工作表（参见常见陷阱） | `--protect your-password --unlock B2:B9` |
| 通过 LibreOffice 重新计算 | `xlsx_recalc.py f.xlsx` |
| 复制 / 重命名工作表 | `--copy-sheet Src:New --rename-sheet Old:New` |
| 打开时强制重新计算 | `xlsx_edit.py f.xlsx --recalc` |
| CSV -> 带样式的 xlsx | `csv_to_xlsx.py in.csv out.xlsx` |
| xlsx -> CSV | `xlsx_to_csv.py f.xlsx out.csv --encoding utf-8` |

## 操作步骤 {#procedure}

1. **创建**：编写 JSON 规格（schema 记录在
   `xlsx_create.py --help` 及其 docstring 中）。每个工作表支持
   `rows`（标量或带样式的单元格对象）、稀疏的 `cells` 覆盖、
   `column_widths`、`row_heights`、`merges`、`freeze_panes`、
   `autofilter`、`conditional_formats`（cell_is 规则和色阶）、
   `charts`（基于单元格区域的柱状图/折线图/饼图）、
   `validations`（列表下拉）、`tables`（带样式名称的原生 Excel 表格），
   以及 `protection`。工作簿级别的 `defined_names`
   将名称映射到引用。单元格对象还接受 `hyperlink` 和 `note`。
   类型化值：JSON 数字/布尔值
   原样传递；日期使用 `{"value": "2026-01-31", "type": "date"}`。
   数字格式为 Excel 格式字符串：货币 `"$#,##0.00"`、
   百分比 `"0.0%"`、日期 `"yyyy-mm-dd"`。
2. **公式**：在规格中用 `"formula": "SUM(B2:B9)"` 设置，或在编辑器中用
   `--set "C1==SUM(A:A)"` 设置。写入公式时，加上
   `"full_calc_on_load": true`（规格）或 `--recalc`（编辑器）；这会设置
   工作簿的 `fullCalcOnLoad` 标志，使 Excel/LibreOffice 在打开时重新计算
   所有内容。openpyxl 本身绝不会计算公式。
3. **读取**：`--sheets` 用于清单（名称、尺寸、合并
   区域、图表数量、表格、保护、定义名称），
   `--json`/`--csv` 用于数据，`--formulas` 将
   每个公式字符串与其缓存结果配对，`--notes` 用于
   单元格批注，`--names` 用于定义名称。只有当文件最后一次
   由真正的电子表格应用保存时才存在缓存结果；
   刚由 openpyxl 生成的文件在此处返回 `null`。要无头地得到结果，
   运行 `xlsx_recalc.py file.xlsx`（使用
   LibreOffice；当 `soffice` 不存在时输出 `{"recalculated": false, ...}`
   并以 0 退出），然后用 `--data-only` 重新加载。
4. **编辑**：`xlsx_edit.py` 先执行重命名/复制，然后执行
   行/列结构变更，最后执行 `--set`/`--append`。除非指定了
   `--out`，否则它会原地编辑——如果需要保留原文件，请先复制一份。
5. **重构**：对含有公式、
   合并单元格、表格或筛选的工作表进行插入/删除时，请使用 `xlsx_restructure.py` 而不是
   `xlsx_edit.py`。它会重写所有工作表上的公式引用
   （绝对 `$` 引用、区域、跨工作表引用），平移合并单元格、
   自动筛选、冻结窗格、数据验证和条件格式
   区域、表格引用、定义名称以及行/列尺寸，然后
   输出一份包含 `not_shifted` 列表的 JSON 报告。规则与
   限制：`references/restructuring.md`。
6. **CSV 互操作**：`csv_to_xlsx.py` 逐单元格推断 int/float/bool/ISO 日期
   并为表头行设置样式；`xlsx_to_csv.py` 写出 ISO
   日期，空单元格写为空字符串。两者默认使用 UTF-8，
   并接受 `--encoding`（例如 `utf-8-sig` 用于对 Excel 友好的 BOM，
   `cp1252` 用于旧版 Windows 导出）。

## 转换为 PDF {#converting-to-pdf}

LibreOffice 可以无头转换（也适用于导出单个工作表为 CSV）：

```bash
soffice --headless --convert-to pdf report.xlsx --outdir out/
soffice --headless --convert-to csv report.xlsx --outdir out/  # 仅第一个工作表
```

CSV 中只会包含第一个工作表；其他工作表请使用
`xlsx_to_csv.py --sheet NAME`。如果缺少 `soffice`，请安装
LibreOffice，或者直接把未转换的文件交给用户。

## 常见陷阱 {#pitfalls}

- **openpyxl 不做计算。** 公式结果只能
  通过 `load_workbook(path, data_only=True)` 获取，且仅当文件
  之前由 Excel/LibreOffice 保存过时才有。否则你会得到 `None`。
- **`xlsx_edit.py` 的插入/删除不会平移引用**（openpyxl
  原生行为）。请使用会平移引用的 `xlsx_restructure.py`——但即便是
  它也无法移动图表锚点、图片或条件格式的规则
  公式；请阅读其 JSON 报告中的 `not_shifted` 列表以及
  `references/restructuring.md`。
- **工作表保护不是安全措施。** `--protect` 设置的是标准的
  xlsx 工作表保护哈希：它只是向行为良好的应用表明"不要编辑这里"，
  仅此而已。任何人都可以通过编辑 zip 中的 XML 或在 LibreOffice 中取消勾选
  来去除它。绝不要依赖它来保证机密性或完整性；它不会加密任何东西。
- **以 `data_only=True` 加载后再保存**会悄无声息地丢弃所有公式
  （由缓存值替换）。除非这正是目的，否则绝不要保存以这种方式加载的工作簿。
- **加载会剥离图表/图片**：openpyxl 无法完整往返
  图表，因此编辑一个带图表的工作簿并保存会丢失图表。
  编辑后重新添加图表，或者避免重新保存带图表的文件。
- **CSV 区域设置陷阱**：始终传入显式编码（脚本
  已经这样做了），并记住欧洲的 CSV 常用 `;` 作为分隔符并使用
  小数逗号——使用 `--delimiter ';'`，并预期像
  `"12,5"` 这样的字符串会保持为字符串。
- **日期是 datetime**：Excel 将日期存储为序列号；
  openpyxl 返回 `datetime`/`date` 对象。这里的导出会输出 ISO
  字符串。
- 工作表名称最多 31 个字符，且不能包含 `[ ] : * ? / \`。

## 验证 {#verification}

- 创建后：运行 `xlsx_read.py out.xlsx --sheets`，确认工作表
  名称、尺寸、合并区域和图表数量符合预期。
- 用 `--json` 导出数据，并与源数据进行比较。
- 编辑后：重新导出受影响的区域；如果写入了公式，
  确认 `--formulas` 列出了它们，并且已应用 `--recalc`。
- 运行 `xlsx_restructure.py` 后：阅读其 JSON 报告，然后重新运行
  `--formulas` 和 `--sheets`，确认引用和区域落在预期位置。
- 如需完整的视觉检查，请在 LibreOffice 中打开：
  `soffice --headless --convert-to pdf out.xlsx` 并检查生成的 PDF。
