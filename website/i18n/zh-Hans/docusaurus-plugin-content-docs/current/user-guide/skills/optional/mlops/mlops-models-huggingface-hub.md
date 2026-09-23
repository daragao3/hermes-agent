---
title: "Huggingface Hub — HuggingFace hf CLI：搜索/下载/上传模型、数据集"
sidebar_label: "Huggingface Hub"
description: "HuggingFace hf CLI：搜索/下载/上传模型、数据集"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Huggingface Hub

HuggingFace hf CLI：搜索/下载/上传模型、数据集。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/mlops/huggingface-hub` 安装 |
| 路径 | `optional-skills/mlops/models/huggingface-hub` |
| 版本 | `1.0.1` |
| 作者 | Hugging Face |
| 许可证 | MIT |
| 平台 | linux, macos, windows |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Hugging Face CLI（`hf`）参考指南 {#hugging-face-cli-hf-reference-guide}

`hf` 命令是与 Hugging Face Hub 交互的现代命令行界面，提供管理仓库、模型、数据集和 Spaces 的工具。

> **重要：** `hf` 命令取代了现已弃用的 `huggingface-cli` 命令。

## 快速开始 {#quick-start}
*   **安装：** `curl -LsSf https://hf.co/cli/install.sh | bash -s`
*   **帮助：** 使用 `hf --help` 查看所有可用功能及真实示例。
*   **认证：** 推荐通过 `HF_TOKEN` 环境变量或 `--token` 标志进行。

---

## 核心命令 {#core-commands}

### 通用操作 {#general-operations}
*   `hf download REPO_ID`：从 Hub 下载文件。
*   `hf upload REPO_ID`：上传文件/文件夹（推荐用于单次提交；也支持大型目录的断点续传上传）。
*   `hf upload-large-folder REPO_ID LOCAL_PATH`：**[已弃用]** —— 请改用 `hf upload`。
*   `hf sync`：在本地目录与 bucket 之间同步文件。
*   `hf env` / `hf version`：查看环境与版本详情。

### 认证（`hf auth`） {#authentication-hf-auth}
*   `login` / `logout`：使用来自 [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) 的 token 管理会话。
*   `list` / `switch`：管理并在多个已存储的访问 token 之间切换。
*   `whoami`：识别当前登录的账户。

### 仓库管理（`hf repos`） {#repository-management-hf-repos}
*   `create` / `delete`：创建或永久删除仓库。
*   `duplicate`：将模型、数据集或 Space 克隆到新 ID。
*   `move`：在命名空间之间转移仓库。
*   `branch` / `tag`：管理类 Git 引用。
*   `delete-files`：使用模式删除特定文件。

---

## 专门的 Hub 交互 {#specialized-hub-interactions}

### 数据集与模型 {#datasets--models}
*   **数据集：** `hf datasets list`、`info` 和 `parquet`（列出 parquet URL）。
*   **SQL 查询：** `hf datasets sql SQL` —— 通过 DuckDB 针对数据集 parquet URL 执行原始 SQL。
*   **模型：** `hf models list` 和 `info`。
*   **论文：** `hf papers ls` —— 查看每日论文。

### 讨论与 Pull Request（`hf discussions`） {#discussions--pull-requests-hf-discussions}
*   管理 Hub 贡献的完整生命周期：`list`、`create`、`info`、`comment`、`close`、`reopen` 和 `rename`。
*   `diff`：查看 PR 中的变更。
*   `merge`：完成 pull request 合并。

### 基础设施与计算 {#infrastructure--compute}
*   **Endpoints：** 部署和管理 Inference Endpoints（`deploy`、`pause`、`resume`、`scale-to-zero`、`catalog`）。
*   **Jobs：** 在 HF 基础设施上运行计算任务。包括用于运行带内联依赖的 Python 脚本的 `hf jobs uv`，以及用于资源监控的 `stats`。
*   **Spaces：** 管理交互式应用。包括 `dev-mode` 和 `hot-reload`，无需完全重启即可重载 Python 文件。

### 存储与自动化 {#storage--automation}
*   **Buckets：** 完整的类 S3 bucket 管理（`create`、`cp`、`mv`、`rm`、`sync`）。
*   **缓存：** 使用 `list`、`prune`（移除分离的修订版本）和 `verify`（校验和检查）管理本地存储。
*   **Webhooks：** 通过管理 Hub webhook 实现工作流自动化（`create`、`watch`、`enable`/`disable`）。
*   **Collections：** 将 Hub 条目组织到 collection 中（`add-item`、`update`、`list`）。

---

## 高级用法与技巧 {#advanced-usage--tips}

### 全局标志 {#global-flags}
*   `--format json`：生成供自动化使用的机器可读输出。
*   `-q` / `--quiet`：仅输出 ID。

### 扩展与 Skills {#extensions--skills}
*   **扩展：** 使用 `hf extensions install REPO_ID`，通过 GitHub 仓库扩展 CLI 功能。
*   **Skills：** 使用 `hf skills add` 管理 AI 助手 skill。
