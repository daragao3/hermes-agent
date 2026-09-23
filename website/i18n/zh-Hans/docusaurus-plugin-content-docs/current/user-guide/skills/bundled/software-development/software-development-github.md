---
title: "Github — 通过 gh CLI 使用 GitHub：PR、issue、评审、仓库、认证"
sidebar_label: "Github"
description: "通过 gh CLI 使用 GitHub：PR、issue、评审、仓库、认证"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Github

通过 gh CLI 使用 GitHub：PR、issue、评审、仓库、认证。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/software-development/github` |
| 版本 | `2.0.0` |
| 作者 | Ben Barclay (benbarclay), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `github`, `gh`, `git`, `pull-requests`, `issues`, `code-review`, `repos`, `auth`, `ci` |
| 相关 skill | [`codebase-inspection`](/user-guide/skills/bundled/software-development/software-development-codebase-inspection), [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# GitHub

使用 `gh` CLI 端到端地处理 GitHub 工作（个别地方注明以 REST 作为后备）：认证、
issue、PR 生命周期、从 issue 到 PR 的交付、代码评审以及仓库管理。本 skill 合并了
六个原有 skill；每个工作流都完整地写在各自的参考文件中 —— 开始某个工作流之前，
务必先阅读对应的参考文件，下面的正文只负责路由。

## 路由 {#routing}

| 任务 | 先读 |
|---|---|
| 认证失效 / 新机器 / token 或 SSH 配置 / gh 登录 | `references/auth.md` |
| 创建、分诊、打标签、指派、关闭 issue | `references/issues.md` |
| 建分支、提交、开 PR、盯 CI、合并 | `references/pr-workflow.md` |
| 把一个 ISSUE 推进到经过验证的 PR（完整交付闭环） | `references/issue-to-pr.md` |
| 评审他人的 PR：diff、行内评论、结论 | `references/code-review.md` |
| 克隆/创建/fork 仓库、remote、release | `references/repo-management.md` |

辅助资源：`scripts/gh-env.sh` + `scripts/git-credential-token.py`
（认证辅助脚本）、`templates/`（PR 正文、bug 报告、功能请求）、
`references/ci-troubleshooting.md`、`references/conventional-commits.md`、
`references/github-api-cheatsheet.md`、`references/review-output-template.md`。

## 核心纪律（适用于所有工作流） {#core-discipline-applies-to-every-workflow}

- 每个会话预检一次：`gh auth status` —— 如果失败，先去看
  `references/auth.md`，再做其他任何事。
- 优先使用 `gh` 而不是原始 REST；只有在 porcelain 命令缺少某个端点时
  才降级到 `gh api`（cheatsheet 列出了这些端点）。
- 没有亲自检查 `gh pr checks` 之前，绝不报告 CI 通过；没有验证
  `state,mergedAt` 之前，绝不声称已合并。
- 动笔之前先读完整上下文：`gh issue view --comments` /
  `gh pr view --comments` —— 决策藏在讨论串里，而不是标题里。
- 创建任何东西之前先排查重复：
  `gh pr list --search` / `gh issue list --search`。

## 验证 {#verification}

- 每个工作流自己的参考文件定义了该任务的完成标准。
- 通用要求：关于远程状态（CI、合并、release、issue 状态）的每一项断言，
  都必须有一次新鲜的 `gh` 读取作为依据，绝不能凭记忆。
