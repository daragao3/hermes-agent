---
title: "Har Derived Api Client — 将网站的 XHR 录制为 HAR，并推导出 HTTP 客户端"
sidebar_label: "Har Derived Api Client"
description: "将网站的 XHR 录制为 HAR，并推导出 HTTP 客户端"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Har Derived Api Client

将网站的 XHR 录制为 HAR，并推导出 HTTP 客户端。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选——通过 `hermes skills install official/web-development/har-derived-api-client` 安装 |
| 路径 | `optional-skills/web-development/har-derived-api-client` |
| 版本 | `0.1.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Browser`, `HAR`, `API`, `Reverse-Engineering`, `Playwright` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# HAR-Derived API Client

用真实浏览器驱动网站一次，同时把它的网络流量录制成 HAR 文件，然后把这个 HAR 提炼成该网站的私有 JSON API，这样你就可以直接用普通 HTTP 调用它——比每次请求都操控浏览器页面便宜得多、也快得多。致谢：该技巧由 Jared Longster 提出，由 Dax（thdxr）推广。本 skill 只做捕获和重放；它**不会**绕过认证、破解 CAPTCHA 或规避机器人检测——如果网站需要登录会话，你是把它的 headers/cookies 沿用下去，而不是伪造它们。

脚本依赖为标准库加 Playwright：捕获需要 Playwright，推导是纯标准库，重放只需要 `requests`/`httpx`（或 `curl`）。

覆盖 **Hermes 的每一种浏览器路径**：默认的本地 `browser_navigate` 后端，加上云端/远程后端（Browserbase、Browser-Use、Firecrawl），以及任何 `/browser connect` CDP 端点。共有两个捕获脚本——一个用于你自行启动的浏览器，一个用于通过 CDP 附加的浏览器——因为两种情况下 HAR 录制的工作方式不同（参见“运行方式”）。

## 使用时机 {#when-to-use}

- “为 &lt;website> 构建一个 CLI/客户端”——推导它的 API，而不是编写点击脚本。
- “这个网站没有公开 API，但页面显然在获取 JSON。”
- 你正准备为同一个查询反复循环调用 `browser_navigate`——停下来，一次性推导出端点。
- 逆向分析自动补全、搜索、信息流或结账 XHR。
- 你在云端后端（Browserbase / Browser-Use / Firecrawl）上或通过 `/browser connect` 捕获了一个会话，想获得 API 而不必再次租用浏览器。

## 前置条件 {#prerequisites}

- Playwright + 一个浏览器二进制文件（仅捕获步骤需要）：
  - `pip install playwright`，然后 `playwright install chromium`
  - （如果系统中的 Playwright 已在 `~/.cache/ms-playwright` 下装有浏览器，直接复用即可。）
- 重放步骤需要 `requests` 或 `httpx`（标准库 `urllib` 也可以）。
- 不需要 API 密钥。客户端需要的任何密钥/token 都是 HAR 捕获到的那些。
- 对于 CDP 路径（`har_capture_cdp.py`）：需要一个可访问的 CDP 端点。在 Hermes 上，运行 `/browser connect` 打印当前活动端点，或读取配置中的 `BROWSER_CDP_URL` / `browser.cdp_url`。云端后端将其暴露为 `cdpUrl`/`connectUrl`。

## 运行方式 {#how-to-run}

脚本位于本 skill 的 `scripts/` 下，通过 `terminal` 工具调用。
**按路径选择捕获脚本**——这是最容易出错的部分：

| 浏览器路径 | Hermes 如何连接它 | 捕获脚本 |
|---|---|---|
| 本地 `browser_navigate`（默认，agent-browser/Playwright） | 本地启动 | `har_capture.py` |
| Camofox（设置了 `CAMOFOX_URL`） | 本地 REST/CDP | 若暴露 CDP 则用 `har_capture_cdp.py`，否则自行驱动 |
| Browserbase / Browser-Use / Firecrawl（云端） | **CDP**（`cdpUrl`） | `har_capture_cdp.py` |
| `/browser connect <url>` / `BROWSER_CDP_URL` | **CDP** | `har_capture_cdp.py` |

经验法则：**如果浏览器是 Hermes *启动*的，用 `har_capture.py`；如果是通过 CDP *连接到*的，用 `har_capture_cdp.py`。** `har_capture.py` 使用 Playwright 的 `record_har_path`，它只适用于本地拥有的 context。`har_capture_cdp.py` 通过 `connect_over_cdp()` 附加，并根据 `page.on("request"/"response")` 事件组装 HAR，因为在已连接的浏览器上无法使用 `record_har_path`。

然后，无论哪条路径：

- `har_to_client.py`——将 HAR 过滤为 XHR/fetch/JSON，按端点分组，并打印参数、headers、请求体以及重放提示（User-Agent / cookie / auth）。

路径相对于本 skill 的目录解析。标准流程：

```bash
# 1a. Capture, LOCAL browser (Hermes launched it)
python3 scripts/har_capture.py "https://SITE/" out.har \
  --action "fill:input[name=search]:my query" --action "sleep:3" --wait 2

# 1b. Capture, CDP browser (cloud backend or /browser connect)
#     get the endpoint from /browser connect or BROWSER_CDP_URL
python3 scripts/har_capture_cdp.py "ws://HOST/devtools/browser/..." out.har \
  --goto "https://SITE/" --action "fill:input[name=search]:my query" \
  --action "sleep:3" --wait 2

# 2. Derive — read the endpoints out of the HAR
python3 scripts/har_to_client.py out.har --host SITE --max-body 400

# 3. Replay — write a tiny client from the printed endpoint (see Procedure)
```

## 速查表 {#quick-reference}

```
har_capture.py <url> <out.har> [--wait S] [--headed] [--action SPEC ...]
  action SPEC:  fill:SELECTOR:TEXT | press:SELECTOR:KEY | click:SELECTOR
                goto:URL | sleep:SECONDS      (run in order after page load)
  use when Hermes LAUNCHED the browser (local browser_navigate default)

har_capture_cdp.py <cdp_url> <out.har> [--goto URL] [--wait S] [--action SPEC ...]
  same action SPEC; attaches to an existing CDP browser and does NOT close it
  use for cloud backends (Browserbase/Browser-Use/Firecrawl) & /browser connect

har_to_client.py <in.har> [--host SUBSTR] [--include-static] [--max-body N]
  default: keeps only XHR/fetch/JSON; --host narrows to one domain
  prints per endpoint: query params, non-boring req headers, req body sample,
                       response status/content-type + body sample
  prints "### Replay hints": the browser User-Agent, cookie/auth presence
```

## 操作步骤 {#procedure}

0. **按路径选择捕获脚本**（参见“运行方式”中的表格）。本地启动 → `har_capture.py`；通过 CDP 连接 → `har_capture_cdp.py`。在 Hermes 上，当云端/远程后端处于活动状态时，`/browser connect` 会告诉你 CDP 端点。
1. **找到交互。** 用 `browser_navigate`（或 `--headed` 捕获）打开网站，查看应该在哪个选择器中输入 / 点击，并在 devtools/network 中确认有 JSON XHR 发出。
2. **捕获 HAR**，通过 `terminal` 工具进行。安排 `--action` 的顺序以触发请求：先 `fill` 输入框，然后 `sleep` 足够长的时间让防抖的 XHR 发出，并且始终在最后保留 `--wait`，以便迟到的响应被写入。两个捕获脚本都会内嵌响应体，因此推导出的客户端能看到真实的负载结构。
3. **推导**，使用 `har_to_client.py --host <domain>`。读出：方法、URL/路径模板（数字/UUID 段会折叠为 `{id}`）、查询参数、请求体 JSON，以及 `### Replay hints` 区块。
4. **编写客户端。** 精确地重建请求——相同的方法、路径、查询参数、请求体。发送网站实际需要的 headers：至少要复制重放提示中的 **User-Agent**。如果提示报告了 cookies 或 auth/token header，也要一并重新发送。
5. **在无浏览器环境下测试。** 用 `terminal` 工具运行客户端，确认它返回的数据与浏览器看到的相同。这就是回报所在：循环中不再需要浏览器。
6. **（可选）封装为 CLI**——在推导出的调用之上写一个小型 `argparse` 脚本，例如 `search.py "frank herbert"`。

完整示例（Wikipedia search-title，已推导并实时重放）：

```python
import requests
r = requests.get(
    "https://en.wikipedia.org/w/rest.php/v1/search/title",
    params={"q": "frank herbert", "limit": 5},
    headers={"accept": "application/json",
             "User-Agent": "Mozilla/5.0 ... Chrome/131 Safari/537.36"},  # from HAR
    timeout=15,
)
for p in r.json()["pages"]:
    print(p["title"], "-", p.get("description"))
```

## 常见陷阱 {#pitfalls}

- **默认的库 User-Agent 会得到 403。** 许多网站（Wikipedia、Cloudflare 前置的 API）会拒绝 `python-requests/x.y`。始终发送重放提示中的浏览器 UA。这是浏览器成功而推导出的客户端失败的头号原因。
- **失败的 `--action` 会在 HAR 写出之前中止**——你得不到任何文件。如果捕获在某个选择器上出错，这次运行什么也没产生；修正选择器（用 `--headed` 观察）然后重新运行。不要去调试一个不存在的 HAR。
- **服务端渲染的页面没有 XHR** 可供推导——`har_to_client.py` 会打印 "No API-looking entries"。数据是随 HTML 一起来的；直接抓取 HTML，或者找到确实会获取 JSON 的那个交互。
- **防抖/输入联想类 XHR 需要真正的停顿。** 在 `fill` 之后加上 `--action "sleep:3"`；仅靠输入，在 HAR 关闭时请求还不会发出。
- **认证/会话端点** 需要捕获到的 `Cookie`/`Authorization` header，而这些会过期。推导出的客户端只和凭据一样持久；当它返回 401 时重新捕获。HAR 包含实时的机密信息——把 `out.har` 视为敏感文件，推导完成后将其删除。
- **`record_har_content="embed"` 会产生很大的 HAR。** 用 `--max-body` 限制打印的内容；对于媒体较多的页面，文件本身可能很大。
- **端点会变化。** 网站会在不通知的情况下更改私有 API。客户端失效时，重新运行一遍捕获→推导流程，而不是手动修补 URL。
- **用错捕获脚本 = 空的/没有 HAR。** 在云端/CDP 后端上使用 `har_capture.py` 什么也录不到（它会自己启动一个本地浏览器，而不是你想要的那个）。`har_capture_cdp.py` 需要端点；在 Hermes 上从 `/browser connect` 或 `BROWSER_CDP_URL` 获取。让捕获脚本与路径匹配（参见“运行方式”中的表格）。
- **无头 Chrome 的 UA 是个弱特征。** 本地/agent-browser 捕获会得到 `HeadlessChrome/...` User-Agent；有些网站会嗅探 "Headless" 标记。云端后端（Browserbase/Browser-Use）发送真实的桌面版 Chrome UA，因此从云端捕获推导出的客户端重放起来更可靠。如果从无头捕获推导出的客户端返回 403 而浏览器没有，在认定端点已变更之前，先把 "Headless" UA 换成普通的 Chrome UA 字符串。
- **CDP 捕获不会关闭浏览器。** `har_capture_cdp.py` 附加到一个它并不拥有的浏览器上，并让它继续运行——这对由 Hermes 管理的云端/远程会话来说是正确的。不要添加关闭操作；让拥有它的后端负责销毁。

## 验证 {#verification}

针对一个无需 API 密钥的真实网站进行端到端验证：

```bash
python3 scripts/har_capture.py "https://en.wikipedia.org/wiki/Main_Page" /tmp/wiki.har \
  --action "fill:input[name=search]:dune messiah" --action "sleep:3" --wait 2
python3 scripts/har_to_client.py /tmp/wiki.har --host wikipedia.org --max-body 200
```

预期推导会打印 `GET https://en.wikipedia.org/w/rest.php/v1/search/title`，带有 `q` 和 `limit` 参数以及一个 JSON `pages` 响应——然后用“操作步骤”中的代码片段重放它，并确认通过普通 HTTP 返回了匹配的标题。
