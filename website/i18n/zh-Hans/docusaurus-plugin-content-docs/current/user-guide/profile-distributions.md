---
sidebar_position: 3
title: "Profile 分发：共享完整 Agent"
description: "把一个完整的 Hermes agent 打包成 git 仓库，他人可一键安装并原地更新，同时保留自己的密钥"
---

# Profile 分发：共享完整 Agent

**Profile 分发**将一个完整的 Hermes agent——个性、技能、cron 任务、MCP 连接、配置——打包为一个 git 仓库。任何有权访问该仓库的人都可以用一条命令安装整个 agent，就地更新，并保持自己的记忆、会话和 API 密钥不受影响。

如果说 [profile](./profiles.md) 是本地 agent，那么分发就是让该 agent 可共享的形式。

## 共享 profile 的两种方式 {#two-ways-to-share-a-profile}

Hermes 有两条共享途径，它们回答的是不同的问题。分发是持久的那一种；导出文件是快捷的那一种。

| | **分发**（git 仓库） | **导出文件**（`.tar.gz`） |
|---|---|---|
| 交付方式 | `hermes profile install <repo>` | 发送一个文件——聊天、AirDrop、U 盘、电子邮件 |
| 接收方需要 | git，以及对仓库的访问权限 | 这个文件 |
| 更新 | `hermes profile update` 拉取新版本 | 重新发送文件 |
| 版本管理 | tag、分支、commit SHA | 无——只是某一时刻的快照 |
| 作者的准备成本 | `distribution.yaml` + `.gitignore` + 一个仓库 | 无——一条命令 |
| 包含内容 | SOUL、配置、技能、cron、MCP、插件 | 同样的内容，**外加**桌面主题和布局 |
| 使用的命令 | `hermes profile install` / `update` | `/export` 和 `/import`，或 `hermes profile export` / `import` |

当 agent 是一个你会持续改进、且其他人需要跟进的产品时，选择**分发**：团队经过审核的内部 agent、社区发布版、部署到五台机器上的同一个 agent。

当你只是想让某人立刻拿到你的配置，或者你要迁移到一台新笔记本时，选择**导出文件**。不需要仓库，不需要 manifest——在聊天中运行 `/export`，把文件交给对方，对方运行 `/import`。参见[导出和导入 profile 文件](#export-and-import-a-profile-file)。

两者并不互斥。很多作者先自己试用一个 profile，用 `/export` 发给同事听取意见，等它值得做版本管理时再将其发布为分发。

## 这意味着什么 {#what-this-means}

在分发功能出现之前，共享一个 Hermes agent 意味着要发送：

1. 你的 SOUL.md
2. 需要安装的技能列表
3. 去掉密钥的 config.yaml
4. 接入了哪些 MCP 服务器的说明
5. 你设置的所有 cron 任务
6. 需要设置哪些环境变量的说明

……然后祈祷对方能正确组装。每次版本升级或修复 bug 都意味着重复这一过程。

有了分发功能，这一切都存放在一个 git 仓库中：

```
my-research-agent/
├── distribution.yaml    # manifest: name, version, env-var requirements
├── SOUL.md              # the agent's personality / system prompt
├── config.yaml          # model, temperature, reasoning, tool defaults
├── skills/              # bundled skills that come with the agent
├── cron/                # scheduled tasks the agent runs
└── mcp.json             # MCP servers the agent connects to
```

接收方运行：

```bash
hermes profile install github.com/you/my-research-agent --alias
```

……他们就拥有了完整的 agent。填入自己的 API 密钥（`.env.EXAMPLE` → `.env`），即可运行 `my-research-agent chat`，或通过 Telegram / Discord / Slack / 任何 gateway 平台与其交互。当你推送新版本时，他们运行 `hermes profile update my-research-agent` 即可拉取你的更改——他们的记忆和会话保持不变。

## 为什么选择 git？ {#why-git}

我们考虑过 tarball、HTTP 归档、自定义格式，但都比不上 git：

- **作者无需构建步骤。** 推送到 GitHub，用户即可安装。没有"打包、上传、更新索引"的循环。
- **标签、分支和提交本身就是版本管理系统。** 推送一个 tag 就能完成其他工具需要"打包 + 上传发布"才能做到的事。
- **更新只需 fetch。** 不需要重新下载整个归档。
- **透明。** 用户可以浏览仓库、阅读版本间的 diff、提 issue、fork 后自定义。
- **私有仓库开箱即用。** SSH 密钥、`git credential` helper、GitHub CLI 存储的凭据——终端已配置好的任何认证方式都能透明生效。
- **可复现性即 commit SHA。** 与 pip 和 npm 的记录方式相同。

权衡之处：接收方需要安装 git。在 2026 年运行 Hermes 的任何机器上，这已是既成事实。

## 什么时候应该使用分发？ {#when-should-you-use-a-distribution}

适合的场景：

- **你要共享一个专用 agent**——合规监控器、代码审查员、研究助手、客服机器人——给团队或社区。
- **你要将同一个 agent 部署到多台机器**，不想每次手动复制文件。
- **你在迭代一个 agent**，希望接收方用一条命令就能获取新版本。
- **你在将 agent 作为产品构建**——有主见的默认配置、精选技能、调优的 prompt（提示词）——供他人作为起点使用。

不适合的场景：

- **你只想立刻把你的配置交给某人一次。** 分发需要一个仓库、一个 manifest 和一个 `.gitignore`。`/export` 这些都不需要——参见[导出和导入 profile 文件](#export-and-import-a-profile-file)。备份 profile 或把它迁移到新机器也是同理。
- **你想共享桌面主题和布局。** 分发携带的是 agent 本身——SOUL、配置、技能、cron、MCP、插件。从桌面应用生成的导出还会携带外观：皮肤、浅色/深色模式、自定义主题、侧栏颜色和窗口布局。
- **你想随 agent 一起共享 API 密钥。** `auth.json` 和 `.env` 被刻意排除在分发之外。每个安装者使用自己的凭据。（导出文件同样会剥离它们。）
- **你想共享记忆 / 会话 / 对话历史。** 这些是用户数据，不是分发内容，永远不会被发送。（导出文件在这一点上不同——发送之前请先阅读[导出文件包含什么](#what-an-export-file-contains)。）

:::caution
**Hermes 并不控制 git。** 本页描述的文件排除规则是由**安装器**在有人运行 `hermes profile install` 或 `hermes profile update` 时应用的。当你运行 `git add` 或 `git commit` 时，这些规则**不会**生效。
:::

## 生命周期：从作者到安装者再到更新 {#the-lifecycle-author-to-installer-to-update}

以下是完整的端到端流程，选择你关心的一侧阅读。

---

## 作者篇：发布分发 {#for-authors-publishing-a-distribution}

### 第一步——从一个可用的 profile 开始 {#step-1--start-from-a-working-profile}

像构建其他 profile 一样构建并打磨 agent：

```bash
hermes profile create research-bot
research-bot setup                    # configure model, API keys
# Edit ~/.hermes/profiles/research-bot/SOUL.md
# Install skills, wire up MCP servers, schedule cron jobs, etc.
research-bot chat                     # dogfood until it feels right
```

### 第二步——添加 `distribution.yaml` {#step-2--add-a-distributionyaml}

创建 `~/.hermes/profiles/research-bot/distribution.yaml`：

```yaml
name: research-bot
version: 1.0.0
description: "Autonomous research assistant with arXiv and web tools"
hermes_requires: ">=0.12.0"
author: "Your Name"
license: "MIT"

# Tell installers which env vars the agent needs. These are checked against
# the installer's shell and existing .env file so they don't get nagged
# about keys they already have configured.
env_requires:
  - name: OPENAI_API_KEY
    description: "OpenAI API key (for model access)"
    required: true
  - name: SERPAPI_KEY
    description: "SerpAPI key for web search"
    required: false
    default: ""
```

这就是完整的 manifest。除 `name` 外，每个字段都有合理的默认值。

### 第三步——在首次提交之前创建 `.gitignore` {#step-3--create-a-gitignore-before-the-first-commit}

:::warning
请在运行 `git init` 或 `git add` **之前**完成这一步。如果你已经和该 profile 聊过天、跑过 setup，或以其他方式使用过它，那么该目录里现在就有一些绝不能发布的文件：`.env`、`auth.json`、`memories/`、`sessions/`、`state.db*`、`logs/` 等等。
:::

创建 `~/.hermes/profiles/research-bot/.gitignore`，内容至少包含：

```gitignore
# Credentials & secrets — NEVER commit
auth.json
.env
.env.EXAMPLE    # generated by install, not authorship domain

# Runtime databases & state
state.db
state.db-shm
state.db-wal
hermes_state.db
response_store.db
response_store.db-shm
response_store.db-wal
gateway.pid
gateway_state.json
processes.json
auth.lock
active_profile
.update_check

# User data — NEVER commit
memories/
sessions/
logs/
plans/
workspace/
home/

# Caches & generated artifacts
image_cache/
audio_cache/
document_cache/
browser_screenshots/
cache/

# Infrastructure (should not be in profile dir, but safe to exclude)
hermes-agent/
.worktrees/
profiles/
bin/
node_modules/

# User customization namespace — your local overrides
local/

# Checkpoints & backups (can be huge)
checkpoints/
sandboxes/
backups/

# Logs
errors.log
.hermes_history
```

这份清单对应安装器在自己那一端剥离的[硬性排除路径](#whats-not-in-a-distribution-ever)。任何你不希望进入仓库的其他内容（临时文件、大型素材、仅本地使用的技能）也应写进这里。

### 第四步——推送到 git 仓库 {#step-4--push-to-a-git-repo}

```bash
cd ~/.hermes/profiles/research-bot
git init
git add .
git commit -m "v1.0.0"
git remote add origin git@github.com:you/research-bot.git
git tag v1.0.0
git push -u origin main --tags
```

该仓库现在就是一个分发。任何有访问权限的人都可以安装它。

:::note
即使作者不慎把[硬性排除路径](#whats-not-in-a-distribution-ever)发布出去，安装器仍会额外剥离它们——但这只保护安装者，保护不了作者。
:::

### 第五步——为版本发布打标签 {#step-5--tag-versioned-releases}

每当 agent 达到稳定状态时，升级版本号并打标签：

```bash
# Edit distribution.yaml: version: 1.1.0
git add distribution.yaml SOUL.md skills/
git commit -m "v1.1.0: tighter research SOUL, add arxiv skill"
git tag v1.1.0
git push --tags
```

运行 `hermes profile update research-bot` 的接收方将拉取最新版本。

### 仓库结构示例 {#what-the-repo-looks-like}

一个完整的分发仓库：

```
research-bot/
├── .gitignore                   # excludes secrets & user data (see Step 3)
├── distribution.yaml            # required
├── SOUL.md                      # strongly recommended
├── config.yaml                  # model, provider, tool defaults
├── mcp.json                     # MCP server connections
├── skills/
│   ├── arxiv-search/SKILL.md
│   ├── paper-summarization/SKILL.md
│   └── citation-lookup/SKILL.md
├── cron/
│   └── weekly-digest.json       # scheduled tasks
└── README.md                    # human-facing description (optional)
```

### 分发所有权 vs 用户所有权 {#distribution-owned-vs-user-owned}

当安装者更新到新版本时，某些内容会被替换（作者的领域），某些内容保持不变（安装者的领域）。默认规则：

| 类别 | 路径 | 更新时 |
|---|---|---|
| **分发所有** | `SOUL.md`、`config.yaml`、`mcp.json`、`skills/`、`cron/`、`distribution.yaml` | 从新克隆中替换 |
| **配置覆盖** | `config.yaml` | 默认实际保留——安装者可能已调整模型或 provider。更新时传入 `--force-config` 可重置。 |
| **用户所有** | `memories/`、`sessions/`、`state.db*`、`auth.json`、`.env`、`logs/`、`workspace/`、`plans/`、`home/`、`*_cache/`、`local/` | 永不触碰 |

你可以在 manifest 中覆盖分发所有列表：

```yaml
distribution_owned:
  - SOUL.md
  - skills/research/            # only my research skills; other installed skills stay
  - cron/digest.json
```

省略时，上述默认规则生效——大多数分发都适用。

---

## 安装者篇：使用分发 {#for-installers-using-a-distribution}

### 安装 {#install}

```bash
hermes profile install github.com/you/research-bot --alias
```

执行过程：

1. 将仓库克隆到临时目录。
2. 读取 `distribution.yaml`，显示 manifest（名称、版本、描述、作者、所需环境变量）。
3. 对照你的 shell 环境和目标 profile 现有的 `.env` 检查每个必需的环境变量，标记为 `✓ set` 或 `needs setting`，让你清楚需要配置哪些内容。
4. 请求确认。传入 `-y` / `--yes` 可跳过。
5. 将分发所有的文件复制到 `~/.hermes/profiles/research-bot/`（或 manifest 中 `name` 解析到的位置）。即使作者不小心把[硬性排除路径](#whats-not-in-a-distribution-ever)留在了仓库里，也会在这次复制过程中被剥离。
6. 写入 `.env.EXAMPLE`，其中所需密钥以注释形式列出——复制为 `.env` 并填入。
7. 使用 `--alias` 时，创建一个 wrapper，使你可以直接运行 `research-bot chat`。

### 来源类型 {#source-types}

任何 git URL 均可使用：

```bash
# GitHub shorthand
hermes profile install github.com/you/research-bot

# Full HTTPS
hermes profile install https://github.com/you/research-bot.git

# SSH
hermes profile install git@github.com:you/research-bot.git

# Self-hosted, GitLab, Gitea, Forgejo — any Git host
hermes profile install https://git.example.com/team/research-bot.git

# Private repo using your configured git auth
hermes profile install git@github.com:your-org/internal-bot.git

# Local directory during development (no git push needed)
hermes profile install ~/my-profile-in-progress/
```

### 覆盖 profile 名称 {#override-the-profile-name}

两个用户希望以不同的 profile 名称使用同一个分发：

```bash
# Alice
hermes profile install github.com/acme/support-bot --name support-us --alias
# Bob（同一分发，不同本地名称）
hermes profile install github.com/acme/support-bot --name support-eu --alias
```

### 填写环境变量 {#fill-in-env-vars}

安装后，agent 的 profile 中包含一个 `.env.EXAMPLE`：

```
# Environment variables required by this Hermes distribution.
# Copy to `.env` and fill in your own values before running.

# OpenAI API key (for model access)
# (required)
OPENAI_API_KEY=

# SerpAPI key for web search
# (optional)
# SERPAPI_KEY=
```

复制它：

```bash
cp ~/.hermes/profiles/research-bot/.env.EXAMPLE ~/.hermes/profiles/research-bot/.env
# Edit .env, paste your real keys
```

已在你的 shell 环境中存在的必需密钥（例如在 `~/.zshrc` 中 export 的 `OPENAI_API_KEY`）在安装时会被标记为 `✓ set`——无需在 `.env` 中重复填写。

### 查看已安装内容 {#check-what-you-installed}

```bash
hermes profile info research-bot
```

显示：

```
Distribution: research-bot
Version:      1.0.0
Description:  Autonomous research assistant with arXiv and web tools
Author:       Your Name
Requires:     Hermes >=0.12.0
Source:       https://github.com/you/research-bot
Installed:    2026-05-08T17:04:32+00:00

Environment variables:
  OPENAI_API_KEY (required) — OpenAI API key (for model access)
  SERPAPI_KEY (optional) — SerpAPI key for web search
```

`hermes profile list` 还会显示 `Distribution` 列，让你一眼看出哪些 profile 来自仓库，哪些是手动构建的：

```
 Profile          Model                        Gateway      Alias        Distribution
 ───────────────    ───────────────────────────    ───────────    ───────────    ────────────────────
 ◆default         claude-sonnet-4              stopped      —            —
  coder           gpt-5                        stopped      coder        —
  research-bot    claude-opus-4                stopped      research-bot research-bot@1.0.0
  telemetry       claude-sonnet-4              running      telemetry    telemetry@2.3.1
```

### 更新 {#update}

```bash
hermes profile update research-bot
```

执行过程：

1. 从记录的来源 URL 重新克隆仓库。
2. 替换分发所有的文件（SOUL、skills、cron、mcp.json）。
3. **保留**你的 `config.yaml`——你可能已调整了模型、temperature 或其他设置。传入 `--force-config` 可覆盖。
4. **永不触碰**用户数据：记忆、会话、auth、`.env`、日志、state。

不需要重新下载整个归档，不会覆盖你对配置的本地修改，不会删除你的对话历史。

### 删除 {#remove}

```bash
hermes profile delete research-bot
```

删除确认提示会在要求你确认之前显示分发信息：

```
Profile: research-bot
Path:    ~/.hermes/profiles/research-bot
Model:   claude-opus-4 (anthropic)
Skills:  12
Distribution: research-bot@1.0.0
Installed from: https://github.com/you/research-bot

This will permanently delete:
  • All config, API keys, memories, sessions, skills, cron jobs
  • Command alias (~/.local/bin/research-bot)

Type 'research-bot' to confirm:
```

这样你就不会在不知道 agent 来源或无法重新安装的情况下意外删除它。

---

## 使用场景与模式 {#use-cases-and-patterns}

### 个人：跨机器同步同一个 agent {#personal-sync-one-agent-across-machines}

你在笔记本上构建了一个研究助手，想在工作站上使用同一个 agent。

```bash
# 笔记本——先创建 .gitignore（见"作者篇"第三步），然后：
cd ~/.hermes/profiles/research-bot
git init && git add . && git status   # 确认没有暂存任何密钥
git commit -m "initial"
git remote add origin git@github.com:you/research-bot.git
git push -u origin main

# 工作站
hermes profile install github.com/you/research-bot --alias
# 填写 .env，完成。
```

在笔记本上的任何迭代（`git commit && push`）都可以通过 `hermes profile update research-bot` 同步到工作站。记忆按机器独立保存——笔记本记住自己的对话，工作站记住自己的，互不干扰。

### 团队：发布经过审核的内部 agent {#team-ship-a-reviewed-internal-agent}

你的工程团队需要一个共享的 PR 审查机器人，具有特定的 SOUL、特定的技能，以及一个对每个 PR 运行审查的 cron 任务。

```bash
# 工程负责人——先创建 .gitignore（见"作者篇"第三步），然后：
cd ~/.hermes/profiles/pr-reviewer
# ... build and tune ...
git init && git add . && git status   # 确认没有暂存任何密钥
git commit -m "v1.0 PR reviewer"
git tag v1.0.0
git push -u origin main --tags    # push to your company's internal Git host

# 每位工程师
hermes profile install git@github.com:your-org/pr-reviewer.git --alias
# 填写 .env，使用自己的 API 密钥（费用由自己承担），.env.EXAMPLE 指明了所需内容
pr-reviewer chat
```

当负责人发布 v1.1（更好的 SOUL、新技能）时，工程师运行 `hermes profile update pr-reviewer`，所有人在几分钟内就能用上新版本。

### 社区：发布公开 agent {#community-publish-a-public-agent}

你构建了一些新颖的东西——也许是"Polymarket 交易员"、"学术论文摘要器"或"Minecraft 服务器运维助手"。你想分享它。

```bash
# 你——先创建 .gitignore（见"作者篇"第三步），然后：
cd ~/.hermes/profiles/polymarket-trader
# 在仓库根目录写一个完整的 README.md——GitHub 会在仓库页面展示它
git init && git add . && git status   # 确认没有暂存任何密钥
git commit -m "v1.0"
git tag v1.0.0
# 发布到公开 GitHub 仓库
git remote add origin https://github.com/you/hermes-polymarket-trader.git
git push -u origin main --tags

# 任何人
hermes profile install github.com/you/hermes-polymarket-trader --alias
```

发推分享安装命令。尝试的人会给你提 issue 和 PR。想要自定义的人可以 fork——与大家已熟悉的 git 工作流完全相同。

### 产品：发布有主见的 agent {#product-ship-an-opinionated-agent}

你在 Hermes 之上构建了产品——也许是合规监控框架、客服技术栈、特定领域的研究平台。你想以产品形式分发它。

```yaml
# distribution.yaml
name: telemetry-harness
version: 2.3.1
description: "Compliance telemetry harness — monitors and reviews regulated workflows"
hermes_requires: ">=0.13.0"
author: "Acme Compliance Inc."
license: "Commercial"

env_requires:
  - name: ACME_API_KEY
    description: "Your Acme Compliance license key (email support@acme.com)"
    required: true
  - name: OPENAI_API_KEY
    description: "OpenAI API key for model access"
    required: true
  - name: GRAPHITI_MCP_URL
    description: "URL for your Graphiti knowledge graph instance"
    required: false
    default: "http://127.0.0.1:8000/sse"
```

你的客户通过一条命令完成安装；安装预览会告诉他们需要准备哪些密钥；你打上新 tag 的那一刻更新就能推出；他们的合规数据（`memories/`、`sessions/`）永远不会离开他们的机器。

### 临时：在共享基础设施上运行一次性脚本 {#ephemeral-one-off-scripts-on-shared-infra}

你是运维负责人，需要一个临时 agent 来诊断生产事故——一个预设好 SOUL、配备正确工具和 MCP 连接的 agent——在三位值班工程师的笔记本上运行一周。

```bash
# 你——先创建 .gitignore（见"作者篇"第三步），然后：
# 构建 profile，提交，推送到私有仓库
git push -u origin main

# 每位值班人员
hermes profile install git@github.com:your-org/incident-2026-q2.git --alias

# 事故解决——清理
hermes profile delete incident-2026-q2
```

安装-删除的成本足够低，可以当作一次性工具使用。

---

## 实用技巧 {#recipes}

### 固定到特定版本 {#pin-to-a-specific-version}

:::note
Git ref 固定（`#v1.2.0`）已在规划中，但不在初始版本中——目前安装时跟踪默认分支。通过 `hermes profile info <name>` 查看已安装版本，在准备好之前暂缓更新。
:::

### 查看当前版本与最新版本 {#check-what-version-youre-on-vs-latest}

```bash
# 你已安装的版本
hermes profile info research-bot | grep Version

# 上游最新版本（不安装）
git ls-remote --tags https://github.com/you/research-bot | tail -5
```

### 在更新时保留本地配置自定义 {#keep-local-config-customizations-through-updates}

默认的更新行为已经做到这一点：`config.yaml` 会被保留。为了安全起见，将本地调整写入分发不拥有的文件：

```yaml
# ~/.hermes/profiles/research-bot/local/my-overrides.yaml
# (distribution never touches local/)
```

……并在 `config.yaml` 或 SOUL 中按需引用。

### 强制全新重装 {#force-a-clean-re-install}

```bash
# 彻底删除并重新安装（记忆/会话也会丢失）
hermes profile delete research-bot --yes
hermes profile install github.com/you/research-bot --alias

# 更新到当前 main，但将 config.yaml 重置为分发默认值
hermes profile update research-bot --force-config --yes
```

### Fork 并自定义 {#fork-and-customize}

标准 git 工作流——分发就是仓库：

```bash
# 在 GitHub 上 fork 仓库，然后安装你的 fork
hermes profile install github.com/yourname/forked-research-bot --alias

# 在 ~/.hermes/profiles/forked-research-bot/ 中本地迭代
# 编辑 SOUL.md，提交，推送到你的 fork
# 上游变更：用常规方式合并到你的 fork
```

### 推送前测试分发 {#test-a-distribution-before-pushing}

在作者机器上：

```bash
# 从本地目录安装（无需 git push）
hermes profile install ~/.hermes/profiles/research-bot --name research-bot-test --alias

# 调整、删除、重新安装，直到满意
hermes profile delete research-bot-test --yes
hermes profile install ~/.hermes/profiles/research-bot --name research-bot-test
```

---

## 导出和导入 profile 文件 {#export-and-import-a-profile-file}

当你不需要版本管理时，可以跳过仓库。`/export` 把一个 profile 打包成单个 `.tar.gz`；`/import` 在另一端将其解包为一个新 profile。导出时会剥离凭据。

### 导出 {#export}

在 CLI、TUI 或桌面聊天中：

```
/export                          # the active profile → managed profile-exports/<name>-<timestamp>.tar.gz
/export research-bot             # a named profile
/export research-bot -o ~/Desktop/research-bot.tar.gz
```

不带 `-o` 时，CLI 和 TUI 会把归档放在默认 Hermes home 下由 Hermes 管理的
`profile-exports/` 目录中，而不是当前工作目录。这样日常导出不会混进源码 checkout，
也能避免生成的 profile 快照被误认为仓库里的源文件。如果 Hermes home 本身就位于某个
Git checkout 内（一些 Docker/自定义部署），归档会放到 `~/.hermes-profile-exports/`，
若不行则放到操作系统临时目录下的某个按用户划分的目录——绝不会放进 checkout。
如果根本不存在安全的自动位置（所有候选位置都在 Git checkout 内），导出会以
"No safe automatic export destination" 拒绝执行，你必须通过 `-o` 传入一个
checkout 之外的路径。当你有意选择归档保存位置时，显式的 `-o` 路径依然有效。

或者从 shell 运行，底层机制相同：

```bash
hermes profile export research-bot
hermes profile export research-bot -o ./research-bot.tar.gz
```

在**桌面应用**中有三个入口，最终都会打开系统原生的保存对话框：

- **⌘K → Export profile…**
- 右键点击侧栏中的 profile 方块 → **Export profile…**
- 侧栏 **+** 旁边的导入按钮负责反方向的操作

桌面导出会额外加入一个 CLI 不会生成的文件：`desktop.json`，其中包含你的皮肤、浅色/深色模式、该皮肤所需的任何自定义主题定义、该 profile 的侧栏颜色以及你的窗口布局。这就是为什么从桌面共享出来的 profile 到达对方那里时*看起来*也和你的一样，而不仅仅是行为一样。

### 导入 {#import}

```
/import ~/Downloads/research-bot.tar.gz
/import ~/Downloads/research-bot.tar.gz --name research-bot-2
```

```bash
hermes profile import ./research-bot.tar.gz
hermes profile import ./research-bot.tar.gz --name research-bot-2
```

除非传入 `--name`，否则 profile 名称会从归档中推断。覆盖导入到已存在的 profile 会被拒绝——请先重命名或删除旧的 profile。当名称与现有命令不冲突时，会创建一个 shell wrapper（`research-bot` → `hermes -p research-bot`）。

在桌面应用中导入还会应用 `desktop.json` 叠加配置，并在新 profile 中为你打开一个全新的聊天。从 CLI 导入桌面生成的归档也没有问题——叠加配置文件会随之保存在磁盘上，并在你下次于桌面应用中打开该 profile 时生效。

:::note
你不能以 `default` 为名导入——这个名称是内置的根 profile（`~/.hermes`）。请传入 `--name something-else`。
:::

### 导出文件包含什么 {#what-an-export-file-contains}

对两种 profile 类型都始终排除：`auth.json` 和 `.env`。你的 API 密钥永远不会离开本机。

**默认 profile**（`~/.hermes`）通过白名单导出——只包含已知的 Hermes 产物，因此碰巧放在你 home 目录里的无关文件不会被卷进去：

`config.yaml`、`SOUL.md`、`MEMORY.md`、`USER.md`、`todo.json`、`system_prompt.md`、`AGENTS.md`、`CLAUDE.md`、`.cursorrules`、`skills/`、`plugins/`、`cron/`、`scripts/`、`sessions/`、`memories/`、`knowledge/`、`preferences/`，以及桌面应用暂存了 `desktop.json` 时的该文件。

**命名 profile**（`~/.hermes/profiles/<name>`）会复制整个目录，仅去掉 `auth.json` / `.env`。这个范围更广——如果该 profile 中有 `state.db`、日志或缓存，它们也会进入归档，文件会变得很大。

:::caution 发送之前先检查你的归档
导出是你 profile 的快照，而不是经过精选的发布版。与分发不同，它**可能**包含 `memories/`、`sessions/` 和 `USER.md`——而且不会有任何东西扫描技能、记忆或人设中你写进去的个人信息。凭据按文件名过滤；内容则不会过滤。

在分享给他人之前，先列出其中的内容：

```bash
tar -tzf research-bot.tar.gz | less
```

如果其中带有你不想交出的对话历史，请改为发布一个[分发](#for-authors-publishing-a-distribution)——分发永远不会包含记忆或会话。
:::

## 分发中永远不包含的内容 {#whats-not-in-a-distribution-ever}

即使作者不小心将以下路径提交到仓库，安装器也会硬性排除它们。没有任何配置选项可以覆盖此行为——这是经过回归测试的不变量：

- `auth.json` — OAuth token、平台凭据
- `.env` — API 密钥、密钥信息
- `memories/` — 对话记忆
- `sessions/` — 对话历史
- `state.db`、`state.db-shm`、`state.db-wal` — 会话元数据
- `logs/` — agent 和错误日志
- `workspace/` — 生成的工作文件
- `plans/` — 草稿计划
- `home/` — Docker 后端中用户的 home 挂载
- `*_cache/` — 图片 / 音频 / 文档缓存
- `local/` — 用户保留的自定义命名空间

当你作为安装者克隆一个分发时，这些内容根本不会被复制到你的 profile 目录。更新时，你自己的副本保持原样。如果你在五台机器上安装了同一个分发，你就拥有五套独立的此类数据——每台机器各一份。

:::caution
这项排除是在**安装者机器上的安装 / 更新时刻**执行的。它**不能**阻止作者提交敏感或不必要的文件。作者必须使用 [`.gitignore`](#step-3--create-a-gitignore-before-the-first-commit) 把密钥挡在仓库之外。
:::

## 安全与信任 {#security-and-trust}

Profile 分发默认不带签名。你信任的是：

- **git 托管平台**（GitHub / GitLab / 其他平台）能够提供作者推送的原始内容。
- **作者**不会发布恶意的 SOUL、技能或 cron 任务。

来自分发的 cron 任务**不会自动调度**——安装器会打印 `hermes -p <name> cron list`，你需要显式启用它们。SOUL.md 和技能在你开始与 profile 对话后立即生效，因此如果你从不熟悉的来源安装，请在第一次运行前阅读它们。

粗略类比：安装分发就像安装浏览器扩展或 VS Code 扩展。低摩擦、高权限，信任来源。对于公司内部分发，使用私有仓库和你现有的 git 认证——无需额外配置。

未来版本可能会添加签名、带有已解析 commit SHA 的 lockfile（`.distribution-lock.yaml`），以及在应用更新前打印 diff 的 `--dry-run` 标志。这些功能目前尚未发布。

## 底层实现 {#under-the-hood}

有关实现细节、精确的 CLI 行为和所有标志，请参阅 [Profile 命令参考](../reference/profile-commands.md#distribution-commands)。

简要说明：

- `install`、`update`、`info` 位于 `hermes profile` 下——不是独立的命令树。
- manifest 格式为 YAML，schema 极简（仅 `name` 为必填）。
- 安装器使用你本地的 `git` 二进制文件进行克隆，因此 shell 已处理的任何认证（SSH 密钥、credential helper）都能透明生效。
- 克隆完成后，`.git/` 会被剥离——已安装的 profile 本身不是 git checkout，避免了"不小心将 `.env` 提交到分发 git 历史"的陷阱。
- 保留的 profile 名称（`hermes`、`test`、`tmp`、`root`、`sudo`）在安装时会被拒绝，以避免与常见二进制文件冲突。

## 另请参阅 {#see-also}

- [Profiles：运行多个 Agent](./profiles.md) — 基础概念
- [Profile 命令参考](../reference/profile-commands.md) — 每个标志、每个选项
- [`hermes profile export` / `import`](../reference/profile-commands.md#hermes-profile-export) — [导出文件](#export-and-import-a-profile-file)的 CLI 形式
- [斜杠命令参考](../reference/slash-commands.md) — `/export`、`/import` 以及所有其他聊天内命令
- [在 Hermes 中使用 SOUL](../guides/use-soul-with-hermes.md) — 编写个性
- [个性与 SOUL](./features/personality.md) — SOUL 在 agent 中的作用
- [技能目录](../reference/skills-catalog.md) — 可打包的技能