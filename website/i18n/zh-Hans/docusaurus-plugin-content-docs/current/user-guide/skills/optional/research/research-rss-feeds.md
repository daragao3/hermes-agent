---
title: "Rss Feeds — 读取 RSS、Atom、JSON 订阅源；发现页面背后的订阅源"
sidebar_label: "Rss Feeds"
description: "读取 RSS、Atom、JSON 订阅源；发现页面背后的订阅源"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Rss Feeds

读取 RSS、Atom、JSON 订阅源；发现页面背后的订阅源。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/research/rss-feeds` 安装 |
| 路径 | `optional-skills/research/rss-feeds` |
| 版本 | `1.0.0` |
| 作者 | Teknium (teknium1), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `RSS`, `Atom`, `Feeds`, `Monitoring`, `Research`, `Blogs`, `Releases` |
| 相关 skill | [`reddit-reading`](/user-guide/skills/optional/social-media/social-media-reddit-reading), [`competitor-news-monitor`](/user-guide/skills/bundled/research/research-competitor-news-monitor), [`grounded-citations`](/user-guide/skills/bundled/research/research-grounded-citations), [`youtube-content`](/user-guide/skills/bundled/media/media-youtube-content), [`blogwatcher`](/user-guide/skills/optional/research/research-blogwatcher) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# RSS Feeds Skill

将任意 RSS 2.0、RSS 1.0/RDF、Atom 或 JSON Feed URL 读取为一份整洁、按日期排序的条目列表，
并能发现普通页面 URL 背后的订阅源（`<link rel="alternate">` 或常见的
`/feed`、`/rss.xml`、`/atom.xml` 路径）。仅使用标准库，无需安装任何东西。
它不会抓取文章全文——如需全文，请把条目链接交给 `web_extract`。

## 使用时机 {#when-to-use}

- “&lt;博客/网站> 有什么新内容”“&lt;GitHub 仓库> 的最新版本”“&lt;subreddit> 最近的帖子”
  “读一下这个订阅源”“这个网站有 RSS 订阅源吗”。
- 用 `cronjob_manage` 构建定期摘要（订阅源比每次运行都抓取 HTML 首页更便宜、更稳定）。
  如需跨多个订阅源的持久化已读/未读数据库，请安装可选的 `blogwatcher` skill；本 skill 是零安装的读取方案。
- 任何结构化的 `title / link / date / author / summary` 列表比渲染后的页面更好用的场景：
  播客、更新日志、YouTube 频道、新闻中心、论坛版块。

## 前置条件 {#prerequisites}

无。Python 3.10+，以及到订阅源主机的网络访问。

## 如何运行 {#how-to-run}

通过 `terminal` 使用相对于 skill 的脚本路径运行：

```bash
python3 scripts/feed.py read https://hnrss.org/frontpage --limit 10
python3 scripts/feed.py read https://simonwillison.net/            # 页面 URL → 自动发现订阅源
python3 scripts/feed.py read URL --since 2026-09-01 --json          # 仅较新的条目，机器可读格式
python3 scripts/feed.py discover https://example.com/               # 列出候选订阅源 URL
```

## 速查 {#quick-reference}

| 来源 | 订阅源 URL 模式 |
|---|---|
| GitHub releases / commits / tags | `https://github.com/OWNER/REPO/releases.atom`、`…/commits/BRANCH.atom`、`…/tags.atom` |
| Subreddit / Reddit 搜索 | `https://www.reddit.com/r/NAME/.rss`、`https://www.reddit.com/search.rss?q=…`（匿名每分钟 1 次请求；参见 `reddit-reading`） |
| YouTube 频道 | `https://www.youtube.com/feeds/videos.xml?channel_id=UC…` |
| Hacker News | `https://hnrss.org/frontpage`、`https://hnrss.org/newest?q=TERM` |
| arXiv 分类 | `https://rss.arxiv.org/rss/cs.CL` |
| Substack / Medium / WordPress / Ghost | `SITE/feed`、`medium.com/feed/@user`、`SITE/rss/` |
| 播客 | 节目托管页面上的 RSS URL（`discover` 能找到它） |

每个条目的输出字段：`title`、`link`、`published`（UTC ISO 8601）、`author`、`summary`
（去除 HTML，≤ 2000 字符）。条目按从新到旧排序。

## 操作流程 {#procedure}

① 如果你只有网站 URL，直接对它运行 `read`；脚本会发现订阅源，
并报告它使用了哪个 URL（`discovered_from`）。当你想在多个公布的订阅源之间做选择时
（评论订阅源与文章订阅源、按分类的订阅源），使用 `discover`。

② 限定请求范围：“最新 N 条”用 `--limit`，“自上次检查以来”用 `--since YYYY-MM-DD`。
对于 cron 摘要，持久化上次看到的 `published` 值，并在下次运行时作为
`--since` 传入。

③ 如需全文，把条目的 `link` 交给 `web_extract`；订阅源摘要常常被截断，或只有第一段。

④ 当结果用于报告时，引用条目的 `link`，而不是订阅源 URL
（`grounded-citations`）。

## 常见陷阱 {#pitfalls}

- 返回 200 却是 HTML，说明该 URL 是页面而不是订阅源；脚本会自动转入发现流程，
  但如果网站既没有 `<link rel="alternate">`，也没有任何常见路径，就会报告 `no feed found`——
  在断定没有订阅源之前，先检查网站页脚或 `/sitemap.xml`。
- Reddit 订阅源共享 Reddit 的匿名限流（每个 IP 大约每分钟一次请求）。
  当你需要多次调用 Reddit 时，通过会等待限流窗口的 `reddit-reading` 串联调用。
- 日期：RSS 的 `pubDate` 是 RFC 822，Atom 使用 ISO 8601；脚本会将两者都规范化为
  UTC。省略日期的订阅源条目会排在最后，并会被 `--since` 丢弃。
- 有些订阅源由 Cloudflare 前置，会对非浏览器客户端返回 403；`blocked-page-recovery`
  负责处理这类情况。

## 验证 {#verification}

`python3 scripts/feed.py read https://github.com/NousResearch/hermes-agent/releases.atom
--limit 1` 会打印一个条目，带有 `releases/tag/` 链接和 `[atom]` 格式标记；
`discover https://simonwillison.net/` 会打印一个 `/atom/` URL。
