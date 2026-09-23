---
title: "Publish Site —— 带版本管理地将站点部署到 GitHub/Cloudflare/Netlify Pages"
sidebar_label: "Publish Site"
description: "带版本管理地将站点部署到 GitHub/Cloudflare/Netlify Pages"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Publish Site

带版本管理地将站点部署到 GitHub/Cloudflare/Netlify Pages。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/web-development/publish-site` 安装 |
| 路径 | `optional-skills/web-development/publish-site` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent (Nous Research) |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `publish`, `deploy`, `hosting`, `github-pages`, `cloudflare-pages`, `netlify`, `static-site`, `versioning`, `rollback`, `web-development` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Publish Site

把用户构建的（或你为他们构建的）网站、仪表盘或 Web 应用发布到用户自己拥有的基础设施上——默认使用 GitHub Pages，需要更多功能时使用 Cloudflare Pages 或 Netlify。其纪律是：先在本地预览以获得确认，用 git tag 为每次部署打上版本，按提供商梯队部署，用真实的 HTTP 检查验证线上 URL，并让回滚始终只需一条命令。

此 skill 涵盖静态站点和 SPA 构建产物（纯 HTML/CSS/JS，或 Vite/Next-export/Astro 等生成的 `dist/`/`build/` 目录）。它不涵盖服务端运行时——若需要无需任何账号设置的一次性 serverless 部署，请改用可选的 `cloudflare-temporary-deploy` skill。

## 何时使用 {#when-to-use}

当用户提出以下请求时加载此 skill：

- **把站点放到网上**——"publish this"、"host this somewhere"、"give me a link I can share"
- **部署一个仪表盘、报告、作品集、文档站点或原型**（你刚刚生成的）
- **用新内容更新一个已发布的站点**（重新部署 = 新版本）
- 将一次有问题的部署**回滚**到上一个版本
- **选择一个托管平台**——他们不在乎放在哪里，只想要一个 URL

## 前置条件 {#prerequisites}

至少一个已认证的提供商 CLI（按以下顺序检查）：

- **GitHub Pages（默认）：** `gh auth status` 执行成功。还需要 `git`。
- **Cloudflare Pages：** `wrangler whoami` 执行成功（或已设置 `CLOUDFLARE_API_TOKEN`）。安装：`npm i -g wrangler`，或使用 `npx wrangler@latest`。
- **Netlify（后备）：** `netlify status` 执行成功。安装：`npm i -g netlify-cli`。

另外：

- 一个要发布的静态产物目录（站点根目录或 `dist/`/`build/` 目录）。如果项目需要构建步骤，先运行构建，然后发布输出目录，绝不要发布源码。
- 如需分享本地预览：`cloudflared`（可选——仅本地预览用 `python3 -m http.server` 就够了）。

## 运行方式 {#how-to-run}

以下所有命令都通过 `terminal` 工具在站点的项目目录中运行。整个流程始终是相同的五步：

1. 构建 → 2. 预览并获得确认 → 3. 提交 + 打 tag（先版本后部署）→ 4. 按提供商梯队部署 → 5. 用 `curl` 验证线上 URL 并报告。

## 快速参考 {#quick-reference}

| 步骤 | 命令 |
|---|---|
| 本地预览 | `python3 -m http.server 8080 --directory dist` |
| 可分享的预览 | `cloudflared tunnel --url http://localhost:8080` |
| 为部署打版本 | `git add -A && git commit -m "deploy: <what>" && git tag deploy-YYYYMMDD-HHMM` |
| GitHub Pages（分支模式） | `git subtree push --prefix dist origin gh-pages` |
| 在仓库上启用 Pages | `gh api repos/{owner}/{repo}/pages -X POST -f 'source[branch]=gh-pages' -f 'source[path]=/'` |
| Cloudflare Pages | `npx wrangler@latest pages deploy dist --project-name <name>` |
| Netlify | `netlify deploy --prod --dir dist` |
| 回滚 | `git checkout <previous-tag> -- . && redeploy`（或使用提供商控制台） |
| 验证线上站点 | `curl -sS -o /dev/null -w '%{http_code}' <url>` → 预期为 `200` |

## 操作步骤 {#procedure}

### 1. 构建并在本地预览 {#1-build-and-preview-locally}

如有需要先构建（`npm run build` 等），并确定输出目录。启动服务：

```bash
python3 -m http.server 8080 --directory dist
```

如需一个可分享的预览链接（用户在另一台机器上，或者你希望在上线前获得他们的确认），在后台 `terminal` 会话中打开一个快速隧道：

```bash
cloudflared tunnel --url http://localhost:8080
```

把 `https://*.trycloudflare.com` URL 交给用户，并在部署前获得确认。之后关闭隧道。

### 2. 先版本后部署——没有例外 {#2-version-before-deploy--no-exceptions}

每次部署都必须来自一个 git 提交，这样每次部署都可复现，回滚也轻而易举。

```bash
git init 2>/dev/null; git add -A
git commit -m "deploy: <short description>"
git tag "deploy-$(date +%Y%m%d-%H%M)"
```

如果项目已有仓库，只需提交 + 打 tag。绝不要部署未提交的文件。

### 3. 部署——提供商梯队 {#3-deploy--provider-ladder}

**第 1 级——GitHub Pages（默认：免费，如果 `gh` 已认证则无需额外账号）：**

```bash
gh repo create <name> --public --source . --push   # 如果仓库已存在则跳过
git subtree push --prefix dist origin gh-pages      # 发布构建产物
gh api "repos/{owner}/<name>/pages" -X POST \
  -f 'source[branch]=gh-pages' -f 'source[path]=/'  # 仅首次需要
```

站点会出现在 `https://<owner>.github.io/<name>/`。如果站点就是仓库根目录（没有构建目录），则推送 `main` 并把 Pages 来源设为 `main`，而不是使用 subtree。对于需要构建步骤且会频繁重新部署的项目，优先使用官方的 `actions/deploy-pages` 工作流，这样推送后会自动发布。

**第 2 级——Cloudflare Pages（当用户需要自定义域名、重定向/响应头或 Functions 时）：**

```bash
npx wrangler@latest pages deploy dist --project-name <name>
```

首次运行会创建项目并打印 `https://<name>.pages.dev` URL。自定义域名通过 Cloudflare 控制台绑定（Pages → 项目 → Custom domains）。

**第 3 级——Netlify（后备，或当用户本来就在使用它时）：**

```bash
netlify deploy --prod --dir dist
```

`netlify deploy --dir dist`（不带 `--prod`）会给出一个草稿 URL——可用作第二个预览阶段。

### 4. 回滚 {#4-rollback}

回滚 = 重新部署之前的某个 tag。绝不要手动编辑线上产物。

```bash
git checkout deploy-<previous> -- .   # 或：git checkout deploy-<previous>; 重新构建
# 然后重新运行第 3 步中相同的部署命令
```

Cloudflare Pages 和 Netlify 也会在其控制台中保留每次部署的历史（"Rollback to this deploy"），在手边没有 CLI 时这样更快。

### 5. 密钥与环境变量 {#5-secrets-and-environment-variables}

- **绝不要提交密钥、API key 或 `.env` 文件**——在 Pages 托管上它们会被公开。在第一次提交前用 `git status` 检查，并把 `.env*` 放进 `.gitignore`。
- 运行时环境变量应放在提供商的控制台中：Cloudflare Pages → Settings → Environment variables；Netlify → Site settings → Environment variables。GitHub Pages 只支持静态内容——没有服务端环境；任何嵌入到打包产物中的内容按定义都是公开的。如果用户的构建内联了某个密钥，要提醒他们。

## 常见陷阱 {#pitfalls}

- **SPA 路由在 GitHub Pages 上返回 404。** Pages 没有重写规则。把输出目录中的 `index.html` 复制为 `404.html`（`cp dist/index.html dist/404.html`），让客户端路由得以恢复。Cloudflare Pages 和 Netlify 通过 `_redirects`（`/* /index.html 200`）处理 SPA。
- **GitHub Pages 构建延迟。** 首次启用后，站点可能需要 1–10 分钟才会出现，之后每次推送约需 1 分钟。不要在第一次 404 时就宣告失败——先用 `curl` 轮询几次再着手排查。
- **路径区分大小写。** Pages 托管运行在区分大小写的 Linux 上；一个在 macOS/Windows 上正常的站点，如果资源被引用为 `Logo.PNG` 而提交的是 `logo.png`，就可能返回 404。当某个资源 404 时，在 HTML 中 grep 大小写不一致的地方。
- **项目页的基础路径。** `https://<owner>.github.io/<name>/` 在 `/<name>/` 下提供服务——像 `/app.js` 这样的绝对资源 URL 会失效。使用相对路径，或设置构建工具的 base（`vite build --base=/<name>/`）。
- **`wrangler` 认证流程需要浏览器。** `wrangler login` 会打开 OAuth；在无头会话中优先使用 `CLOUDFLARE_API_TOKEN`（由用户在 dash.cloudflare.com → API Tokens 创建），并且绝不要把 token 回显到日志中。
- **自定义域名的 DNS 传播。** 新的 CNAME 可能需要几分钟到几小时才能生效。先针对提供商的默认 URL（`*.pages.dev`、`*.netlify.app`、`*.github.io`）进行验证，再单独检查自定义域名——不要把这两类失败混为一谈。
- **部署了源码而不是构建产物。** 当真正的站点位于 `dist/` 中时却发布了仓库根目录，会得到一个目录列表或原始 JSX。始终确认输出目录中包含 `index.html`。

## 验证 {#verification}

不要仅凭部署日志就报告成功。在告诉用户任何事情之前：

1. `curl -sS -o /dev/null -w '%{http_code}' <live-url>` 返回 `200`（对于首次 GitHub Pages 部署，在约 2 分钟内重试）。
2. `curl -sS <live-url> | head -30` 显示预期的 `index.html` 内容——也可以选择对线上 URL 使用 `web_extract` 确认页面标记。
3. 对于 SPA，还要 curl 一个深层路由（例如 `/about`），确认它返回 `200` 而不是 `404`。
4. `git tag --list 'deploy-*'` 显示了此次部署的 tag。

然后向用户报告线上 URL，以及他们可以回滚到的部署 tag。
