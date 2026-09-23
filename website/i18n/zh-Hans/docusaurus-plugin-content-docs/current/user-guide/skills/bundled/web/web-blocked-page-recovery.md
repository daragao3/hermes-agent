---
title: "Blocked Page Recovery — 抓取失败时使用：403/429、付费墙、WAF、机器人拦截"
sidebar_label: "Blocked Page Recovery"
description: "抓取失败时使用：403/429、付费墙、WAF、机器人拦截"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Blocked Page Recovery

抓取失败时使用：403/429、付费墙、WAF、机器人拦截。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/web/blocked-page-recovery` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Research`, `Archives`, `Wayback`, `Paywall`, `WAF`, `Fallback` |
| 相关 skill | [`grounded-citations`](/user-guide/skills/bundled/research/research-grounded-citations) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Blocked-Page Recovery

当页面无法抓取时——403/429、Cloudflare 的 "Just a moment..."、付费墙，
或机器人检测插页——不要放弃，也不要对同一个 URL 反复循环。第三方服务常常保存着该页面的**副本**。
沿着下面这条阶梯逐级尝试，从成本最低的开始。

## 阶梯 {#the-ladder}

```
1. Wayback Machine  — archive.org "available" API  (snapshot + timestamp)
2. archive.today    — domain rotation: archive.ph → .md → .li → .is
3. Jina Reader      — only if JINA_API_KEY is set  (live server-side render)
4. API-first pivot  — look for /api/, /graphql, .json, or RSS on the same host
5. Real browser     — browser tool as the last, most expensive resort
```

使用内置脚本一次性运行：

```bash
python3 scripts/recover_page.py "https://example.com/blocked-article" --json
```

该脚本按顺序尝试每条路线，校验每个响应体（见下文"虚假成功"），
并打印第一个真正命中的结果及其来源类型。

## 来源纪律（不容商量） {#provenance-discipline-non-negotiable}

每份恢复出来的副本都带有一个来源类型，引用时你**必须**保留：

| 路线 | 来源类型 | 如何引用 |
|-------|-----------|-------------|
| Wayback / archive.today | `snapshot` | 引用时**附上**快照日期："as archived 2026-08-06"。绝不要把快照当作实时页面呈现——它可能已过时。 |
| Jina Reader | `live` | 在服务端重新渲染的实时页面；正常引用。 |
| 实时抓取 / 浏览器 | `live` | 正常引用。 |

如果用户需要*当前*数据（价格、库存、突发新闻），快照只是背景信息而不是答案——
要明确说明这一点，并注明其时效。

## 手动路线 {#manual-routes}

### 1. Wayback Machine（来源最可靠，优先尝试） {#1-wayback-machine-best-provenance-try-first}

```bash
# Discovery: returns closest snapshot URL + timestamp as JSON
curl -sL "https://archive.org/wayback/available?url={URL}"
# Then fetch archived_snapshots.closest.url
```

如需枚举多个快照（或恢复已删除的页面），使用 CDX 索引：

```bash
curl -sL "https://web.archive.org/cdx/search/cdx?url={URL}&output=json&limit=10"
```

CDX 在负载高时会间歇性返回 503——如果出现这种情况，回退到
`available` API；不要反复重试猛打它。

适用于：任何被公开抓取过的 URL。不适用于：被 robots 屏蔽的站点、
从未被抓取的 URL、纯 JS 的 SPA（快照无法渲染）。

### 2. archive.today（付费墙、已删除内容） {#2-archivetoday-paywalls-deleted-content}

由用户提交的存档——常常包含 Wayback 缺失的付费新闻文章。
它的限流非常激进（429）且会轮换域名，因此要逐个尝试：

```bash
for d in archive.ph archive.md archive.li archive.is; do
  curl -sL --max-time 20 "https://$d/newest/{URL}" -o /tmp/page.html \
    -w "%{http_code}" && break
done
```

**校验响应体，而不是状态码**——429 仍会返回好几 KB 的
限流 HTML，仅靠大小检查会误以为成功。

### 3. Jina Reader（需要 JINA_API_KEY） {#3-jina-reader-requires-jina_api_key}

`r.jina.ai` 在服务端用真实浏览器重新渲染实时页面，并
返回 markdown。匿名访问已失效（401 → Turnstile）；必须
提供密钥：

```bash
curl -s -H "Authorization: Bearer $JINA_API_KEY" "https://r.jina.ai/{URL}"
```

它能处理存档无法处理的 JS SPA。未设置该环境变量时，完全跳过
这条路线。

### 4. 转向 API 优先 {#4-api-first-pivot}

WAF 对 HTML 界面的保护远比对其背后的数据端点激进。
在某个站点上被拦截 2-3 次之后，停止与 HTML 较劲，
转而寻找：

- 页面 URL 的 `/api/...`、`/graphql` 或 `.json` 变体
- RSS/Atom 订阅源（`/feed`、`/rss`，或你已恢复出的任何副本中的
  `<link rel="alternate">`）
- 站点地图（`/sitemap.xml`），它可能揭示未被拦截的规范 URL

## 虚假成功——会"说谎"的路线 {#fake-successes--routes-that-lie}

这些路线会返回 HTTP 200 以及一个看似合理、但**并非**目标页面的响应体。脚本
会自动拒绝它们；手动操作时也要拒绝：

- **Google Cache 已失效**（自 2024 年年中起）。`webcache.googleusercontent.com`
  返回 200 + 数十 KB 内容，但那是一个带 JS 重定向的 Google 搜索插页，
  而不是缓存。绝不要使用它。
- **AMP 缓存**（`*.cdn.ampproject.org`）大多返回一个约 300 字节的
  `<title>Redirecting</title>` meta-refresh 存根，指回原始的（被拦截的）URL。
  把它当作成功会造成抓取死循环。
- **限流响应体**：archive.today 的 429 页面是好几 KB 的 HTML。要检查
  目标页面的实际内容（标题词、预期字符串），而不只是大小。

脚本采用的检测启发式：响应体低于每条路线的字节下限；
目标为原始主机的 meta-refresh/JS 重定向存根；插页
标题（"Just a moment"、"Redirecting"、"Google Search"、"Attention Required"）。

## 代理中继：不要用 {#proxy-relays-dont}

通用的"网页代理"中继从构造上就是中间人。绝不要通过它发送
cookie 或 Authorization 头，也不要把它们用于用户将要依赖的任何内容
——其来源无法验证。优先使用存档，它们至少会为副本
打上时间戳。
