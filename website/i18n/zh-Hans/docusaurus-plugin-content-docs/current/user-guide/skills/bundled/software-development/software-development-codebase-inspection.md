---
title: "Codebase Inspection — 用 pygount 检查代码库：LOC、语言、比例"
sidebar_label: "Codebase Inspection"
description: "用 pygount 检查代码库：LOC、语言、比例"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Codebase Inspection

用 pygount 检查代码库：LOC、语言、比例。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/software-development/codebase-inspection` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `LOC`, `Code Analysis`, `pygount`, `Codebase`, `Metrics`, `Repository` |
| 相关 skill | [`github`](/user-guide/skills/bundled/software-development/software-development-github) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# 使用 pygount 检查代码库 {#codebase-inspection-with-pygount}

使用 `pygount` 分析仓库的代码行数、语言分布、文件数量以及代码与注释的比例。

## 使用时机 {#when-to-use}

- 用户询问 LOC（代码行数）统计
- 用户想了解某个仓库的语言分布
- 用户询问代码库的规模或构成
- 用户想了解代码与注释的比例
- 一般性的"这个仓库有多大"之类的问题

## 前置条件 {#prerequisites}

```bash
pip install --break-system-packages pygount 2>/dev/null || pip install pygount
```

## 1. 基本汇总（最常用） {#1-basic-summary-most-common}

获取包含文件数、代码行数和注释行数的完整语言分布：

```bash
cd /path/to/repo
pygount --format=summary \
  --folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,.eggs,*.egg-info" \
  .
```

**重要：** 务必使用 `--folders-to-skip` 排除依赖/构建目录，否则 pygount 会遍历这些目录，耗时极长甚至挂起。

## 2. 常见的排除目录 {#2-common-folder-exclusions}

根据项目类型调整：

```bash
# Python 项目
--folders-to-skip=".git,venv,.venv,__pycache__,.cache,dist,build,.tox,.eggs,.mypy_cache"

# JavaScript/TypeScript 项目
--folders-to-skip=".git,node_modules,dist,build,.next,.cache,.turbo,coverage"

# 通用兜底
--folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,vendor,third_party"
```

## 3. 按特定语言过滤 {#3-filter-by-specific-language}

```bash
# 仅统计 Python 文件
pygount --suffix=py --format=summary .

# 仅统计 Python 和 YAML
pygount --suffix=py,yaml,yml --format=summary .
```

## 4. 逐文件的详细输出 {#4-detailed-file-by-file-output}

```bash
# 默认格式显示逐文件分布
pygount --folders-to-skip=".git,node_modules,venv" .

# 按代码行数排序（通过管道交给 sort）
pygount --folders-to-skip=".git,node_modules,venv" . | sort -t$'\t' -k1 -nr | head -20
```

## 5. 输出格式 {#5-output-formats}

```bash
# 汇总表（默认推荐）
pygount --format=summary .

# JSON 输出，供程序化使用
pygount --format=json .

# 便于管道处理：Language、file count、code、docs、empty、string
pygount --format=summary . 2>/dev/null
```

## 6. 解读结果 {#6-interpreting-results}

汇总表的各列：
- **Language** —— 检测到的编程语言
- **Files** —— 该语言的文件数量
- **Code** —— 实际代码行数（可执行/声明式）
- **Comment** —— 注释或文档行数
- **%** —— 占总量的百分比

特殊的伪语言：
- `__empty__` —— 空文件
- `__binary__` —— 二进制文件（图片、编译产物等）
- `__generated__` —— 自动生成的文件（启发式检测）
- `__duplicate__` —— 内容完全相同的文件
- `__unknown__` —— 无法识别的文件类型

## 常见陷阱 {#pitfalls}

1. **务必排除 .git、node_modules、venv** —— 不加 `--folders-to-skip` 时，pygount 会遍历所有内容，在大型依赖树上可能耗时数分钟甚至挂起。
2. **Markdown 显示 0 行代码** —— pygount 将所有 Markdown 内容归类为注释而非代码。这是预期行为。
3. **JSON 文件的代码行数偏低** —— pygount 统计 JSON 行数可能比较保守。如需准确的 JSON 行数，请直接使用 `wc -l`。
4. **大型 monorepo** —— 对于非常大的仓库，考虑使用 `--suffix` 指定特定语言，而不是扫描全部内容。
