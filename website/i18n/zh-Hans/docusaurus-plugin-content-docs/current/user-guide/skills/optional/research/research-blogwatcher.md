---
title: "Blogwatcher —— 通过 blogwatcher-cli 工具监控博客和 RSS/Atom 订阅源"
sidebar_label: "Blogwatcher"
description: "通过 blogwatcher-cli 工具监控博客和 RSS/Atom 订阅源"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Blogwatcher

通过 blogwatcher-cli 工具监控博客和 RSS/Atom 订阅源。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/research/blogwatcher` 安装 |
| 路径 | `optional-skills/research/blogwatcher` |
| 版本 | `2.0.0` |
| 作者 | JulienTant（Hyaxia/blogwatcher 的分叉） |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `RSS`, `Blogs`, `Feed-Reader`, `Monitoring` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Blogwatcher

使用 `blogwatcher-cli` 工具追踪博客和 RSS/Atom 订阅源的更新。支持自动发现订阅源、HTML 抓取兜底、OPML 导入以及已读/未读文章管理。

## 配合 Hermes 工具使用（请先阅读） {#working-with-hermes-tools-read-this-first}

`blogwatcher-cli` 是订阅源数据库；围绕它的自动化由 Hermes 工具完成：

- **周期性监控——使用 cronjob 工具的 `monitor` 字段，而不是单纯的定时计划。** `monitor` 在每次触发时运行一个脚本，只有当输出发生变化时才唤醒 agent：将其设为运行 `blogwatcher-cli scan >/dev/null 2>&1 && blogwatcher-cli articles` 的脚本（输出是确定性的；有新文章 = 输出变化 = agent 被唤醒并注入差异）。输出未变的触发不消耗任何 LLM 调用。设置 `deliver` 将摘要路由到某个聊天/频道；加上 `continuity: true`，让相邻的摘要可以去重。
- **阅读用户询问的某篇文章**：对 `blogwatcher-cli articles` 中的文章 URL 调用 `web_extract([url])`——不要手工重新抓取。
- **一次性"监控此页面变化"，且不需要订阅源语义**：跳过本 skill；cronjob 工具的 `monitor` 字段可以直接接受 http(s) URL。
- **一次性读取某个订阅源或网站的最新文章，无需安装任何东西**：使用内置的 `rss-feeds` skill（`scripts/feed.py read URL`）；当你需要带已读/未读状态追踪大量订阅源时，才值得安装 blogwatcher。
- **带分析和引用的公司/竞争对手追踪**：优先使用 `competitor-news-monitor` skill；blogwatcher 是它可以依托的更轻量的原始订阅源层。

## 安装 {#installation}

任选一种方式：

- **Go：** `go install github.com/JulienTant/blogwatcher-cli/cmd/blogwatcher-cli@latest`
- **Docker：** `docker run --rm -v blogwatcher-cli:/data ghcr.io/julientant/blogwatcher-cli`
- **二进制（Linux amd64）：** `curl -sL https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_linux_amd64.tar.gz | tar xz -C /usr/local/bin blogwatcher-cli`
- **二进制（Linux arm64）：** `curl -sL https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_linux_arm64.tar.gz | tar xz -C /usr/local/bin blogwatcher-cli`
- **二进制（macOS Apple Silicon）：** `curl -sL https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_darwin_arm64.tar.gz | tar xz -C /usr/local/bin blogwatcher-cli`
- **二进制（macOS Intel）：** `curl -sL https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_darwin_amd64.tar.gz | tar xz -C /usr/local/bin blogwatcher-cli`

所有发行版：https://github.com/JulienTant/blogwatcher-cli/releases

### 使用持久化存储的 Docker {#docker-with-persistent-storage}

默认情况下数据库位于 `~/.blogwatcher-cli/blogwatcher-cli.db`。在 Docker 中，容器重启后它会丢失。使用 `BLOGWATCHER_DB` 或挂载卷来持久化：

```bash
# 命名卷（最简单）
docker run --rm -v blogwatcher-cli:/data -e BLOGWATCHER_DB=/data/blogwatcher-cli.db ghcr.io/julientant/blogwatcher-cli scan

# 主机绑定挂载
docker run --rm -v /path/on/host:/data -e BLOGWATCHER_DB=/data/blogwatcher-cli.db ghcr.io/julientant/blogwatcher-cli scan
```

### 从原版 blogwatcher 迁移 {#migrating-from-the-original-blogwatcher}

如果是从 `Hyaxia/blogwatcher` 升级，请迁移你的数据库：

```bash
mv ~/.blogwatcher/blogwatcher.db ~/.blogwatcher-cli/blogwatcher-cli.db
```

二进制名称已从 `blogwatcher` 改为 `blogwatcher-cli`。

## 常用命令 {#common-commands}

### 管理博客 {#managing-blogs}

- 添加博客：`blogwatcher-cli add "My Blog" https://example.com`
- 指定订阅源添加：`blogwatcher-cli add "My Blog" https://example.com --feed-url https://example.com/feed.xml`
- 使用 HTML 抓取添加：`blogwatcher-cli add "My Blog" https://example.com --scrape-selector "article h2 a"`
- 列出已追踪的博客：`blogwatcher-cli blogs`
- 移除博客：`blogwatcher-cli remove "My Blog" --yes`
- 从 OPML 导入：`blogwatcher-cli import subscriptions.opml`

### 扫描与阅读 {#scanning-and-reading}

- 扫描所有博客：`blogwatcher-cli scan`
- 扫描单个博客：`blogwatcher-cli scan "My Blog"`
- 列出未读文章：`blogwatcher-cli articles`
- 列出所有文章：`blogwatcher-cli articles --all`
- 按博客筛选：`blogwatcher-cli articles --blog "My Blog"`
- 按分类筛选：`blogwatcher-cli articles --category "Engineering"`
- 将文章标为已读：`blogwatcher-cli read 1`
- 将文章标为未读：`blogwatcher-cli unread 1`
- 全部标为已读：`blogwatcher-cli read-all`
- 将某个博客的全部文章标为已读：`blogwatcher-cli read-all --blog "My Blog" --yes`

## 环境变量 {#environment-variables}

所有标志都可以通过带 `BLOGWATCHER_` 前缀的环境变量设置：

| 变量 | 说明 |
|---|---|
| `BLOGWATCHER_DB` | SQLite 数据库文件路径 |
| `BLOGWATCHER_WORKERS` | 并发扫描 worker 数量（默认：8） |
| `BLOGWATCHER_SILENT` | 扫描时只输出 "scan done" |
| `BLOGWATCHER_YES` | 跳过确认提示 |
| `BLOGWATCHER_CATEGORY` | 按分类筛选文章的默认过滤条件 |

## 示例输出 {#example-output}

```
$ blogwatcher-cli blogs
Tracked blogs (1):

  xkcd
    URL: https://xkcd.com
    Feed: https://xkcd.com/atom.xml
    Last scanned: 2026-04-03 10:30
```

```
$ blogwatcher-cli scan
Scanning 1 blog(s)...

  xkcd
    Source: RSS | Found: 4 | New: 4

Found 4 new article(s) total!
```

```
$ blogwatcher-cli articles
Unread articles (2):

  [1] [new] Barrel - Part 13
       Blog: xkcd
       URL: https://xkcd.com/3095/
       Published: 2026-04-02
       Categories: Comics, Science

  [2] [new] Volcano Fact
       Blog: xkcd
       URL: https://xkcd.com/3094/
       Published: 2026-04-01
       Categories: Comics
```

## 说明 {#notes}

- 未提供 `--feed-url` 时，会从博客首页自动发现 RSS/Atom 订阅源。
- 如果 RSS 失败且配置了 `--scrape-selector`，则回退到 HTML 抓取。
- RSS/Atom 订阅源中的分类会被存储，可用于筛选文章。
- 支持从 Feedly、Inoreader、NewsBlur 等导出的 OPML 文件批量导入博客。
- 数据库默认存储在 `~/.blogwatcher-cli/blogwatcher-cli.db`（可用 `--db` 或 `BLOGWATCHER_DB` 覆盖）。
- 使用 `blogwatcher-cli <command> --help` 查看所有标志和选项。
