---
title: "Reddit Reading —— 读取 Reddit：子版块、搜索、帖子、用户"
sidebar_label: "Reddit Reading"
description: "读取 Reddit：子版块、搜索、帖子、用户"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Reddit Reading

读取 Reddit：子版块、搜索、帖子、用户。无需浏览器。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/social-media/reddit-reading` 安装 |
| 路径 | `optional-skills/social-media/reddit-reading` |
| 版本 | `1.0.0` |
| 作者 | Teknium (teknium1), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Reddit`, `Social Media`, `Research`, `Discussions`, `Community` |
| 相关 skill | [`rss-feeds`](/user-guide/skills/optional/research/research-rss-feeds), [`grounded-citations`](/user-guide/skills/bundled/research/research-grounded-citations), [`blocked-page-recovery`](/user-guide/skills/bundled/web/web-blocked-page-recovery), [`xurl`](/user-guide/skills/bundled/social-media/social-media-xurl) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Reddit Reading Skill

在常规途径都已失效的服务器或无头机器上读取 Reddit 内容——子版块列表、全站或子版块搜索、
带评论的完整帖子，以及用户动态。它不会发帖、投票，也不会以用户身份登录。创意来源：
[Agent Reach](https://github.com/Panniantong/Agent-Reach) 中按平台划分的后端路由。

## 何时使用 {#when-to-use}

- "What is r/LocalLLaMA saying about X"、"find Reddit threads on Y"、"summarise this
  Reddit thread"、"what has u/someone posted lately"。
- 用户分享的任何 `reddit.com` URL。`web_extract`、`browser_navigate` 以及
  `.json` 端点从服务器 IP 访问时全都会失败（403 或 "Prove your humanity" 拦截页）；
  这个 skill 才是可行的途径。
- 不适用于发帖、投票、私信，或任何需要用户登录的操作。

## 前置条件 {#prerequisites}

**无。** 不需要 Reddit 账号、登录、cookie 或 API 密钥。默认后端是
Reddit 公开的 Atom feed（`.rss` 端点），这是 Reddit 仍然向非住宅 IP 提供的
唯一一条免认证途径。它被限流为每个 IP 大约每分钟一次请求，
返回的数据也更少（没有分数，只有顶层评论），不过用于少量调用已经足够。

**可选升级（应用凭据，仍然不需要用户登录）：** 若需持续使用或获取完整
数据，可在 https://www.reddit.com/prefs/apps 注册一个免费的 "script" 类型应用，并把它的
两个值写入 `~/.hermes/.env`：

```
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

这是一次应用注册，而不是登录：脚本使用仅限应用的
`client_credentials` 授权，从不使用用户名、密码或浏览器 cookie，也从不
以用户身份行事。两个值都设置后，它会自动切换到 OAuth API
（约每分钟 100 次请求，带分数、嵌套评论、`num_comments`）；如果它们
缺失或被拒绝，就会回退到匿名 feed，并在 stderr 上说明这一点。

| | 匿名 feed（默认） | OAuth 应用凭据 |
|---|---|---|
| 设置 | 无需任何操作 | 1 分钟的应用注册，两个 `.env` 值 |
| 速率限制 | 约 1 次请求 / 分钟 / IP | 约 100 次请求 / 分钟 |
| 帖子数据 | 帖子 + 顶层评论，无分数 | 嵌套评论、分数、评论数 |
| 以用户身份行事 | 否 | 否 |

## 运行方式 {#how-to-run}

通过 `terminal` 运行每条命令，使用相对于 skill 的脚本路径：

```bash
python3 scripts/reddit.py doctor                                  # 当前使用哪个后端，当前速率限制窗口
python3 scripts/reddit.py sub LocalLLaMA --sort hot --limit 15
python3 scripts/reddit.py search "hermes agent" --sub LocalLLaMA --sort new
python3 scripts/reddit.py thread https://www.reddit.com/r/x/comments/abc123/slug/ --limit 40
python3 scripts/reddit.py user spez --limit 10
python3 scripts/reddit.py --json search "topic"                  # 机器可读输出
```

## 快速参考 {#quick-reference}

每条命令在两种后端上都能使用；后端由脚本选择，你无需传入任何参数。

| 需求 | 命令 | 匿名 | OAuth |
|---|---|---|---|
| 子版块首页 | `sub NAME --sort hot\|new\|top\|rising [--time week]` | ✔ | ✔ |
| 全站搜索 | `search "q" --sort relevance\|new\|top\|comments` | ✔ | ✔ |
| 搜索单个子版块 | `search "q" --sub NAME` | ✔ | ✔ |
| 帖子 + 评论 | `thread URL --limit N` | ✔ 仅顶层，无分数 | ✔ 嵌套，带分数 |
| 用户帖子/评论 | `user NAME` | ✔ | ✔ |
| 后端 + 速率限制 | `doctor` | ✔ | ✔ |

## 操作步骤 {#procedure}

① 如果本次会话中还没调用过 `doctor`，每个任务调用一次——它会告诉你哪个
后端可用，以及匿名窗口还剩多少秒。

② 先规划好调用再执行。匿名访问 Reddit 大约只允许**每个 IP 每分钟
一次请求**；遇到 429 时脚本会睡眠直到窗口重置，然后重试一次，因此
一个五次调用的计划大约要花五分钟。优先用一次 `search --sub`，而不是多次 `sub`
列表；只读一个帖子，而不是整个列表。

③ 对于"社区在说什么"之类的问题，要读取帖子正文（`thread`），而不是
只看标题；列表中每个帖子只包含前约 300 个字符。

④ 当结果要用于报告时，引用永久链接（`url` 字段），而不是列表页。
`grounded-citations` 会像登记其他来源一样登记这些 URL。

⑤ 如果用户需要持续访问 Reddit（监控，或超过约 10 次调用），请停下来，
请用户注册应用凭据（见前置条件），而不是硬扛着
限流继续。要明确告诉他们：这是一次免费的应用注册，并不是让 Hermes 登录他们的
账号。绝不要索要 Reddit 密码或浏览器 cookie。

## 常见陷阱 {#pitfalls}

- `www.reddit.com/…/.json`、`api.reddit.com` 和 `old.reddit.com` 对数据中心 IP
  会返回 403 或一个空的 "Welcome to Reddit" 外壳页。不要回退到它们；也不要
  伪造浏览器 User-Agent（同样是 403）。
- `r.jina.ai` 和 `browser_navigate` 工具会遇到同样的拦截（"blocked by network
  security" / 人机验证）。`blocked-page-recovery` 的 Wayback 途径仍然可以恢复
  已被存档的**旧**帖子；但无法获取新帖子。
- 匿名的帖子 feed 只包含帖子本身和顶层评论（Reddit 把
  feed 限制为少量条目）；分数和回复嵌套仅在 OAuth 下可用。
- Reddit feed 上的 `limit` 只是建议值——无论你请求多少，预计都只会返回 5–25 条。
- 绝不要把 `REDDIT_CLIENT_SECRET` 粘贴到聊天或日志中；脚本只从
  环境变量中读取它。
- 不要试图通过循环重试或添加代理来"修复" 429；限流是按 IP 计算的，
  而且脚本已经会等待窗口过去一次。连续出现不止一次 429 意味着
  该任务需要应用凭据。

## 验证 {#verification}

`python3 scripts/reddit.py doctor` 会打印 `anonymous_feed: ok` 和一个
`x-ratelimit-reset` 值；`sub announcements --limit 1` 会返回一条带有
`reddit.com/r/announcements/comments/` URL 的条目。设置凭据后，`doctor` 会打印
`active_backend: oauth`，并且 `thread …` 的输出会显示数字分数。
