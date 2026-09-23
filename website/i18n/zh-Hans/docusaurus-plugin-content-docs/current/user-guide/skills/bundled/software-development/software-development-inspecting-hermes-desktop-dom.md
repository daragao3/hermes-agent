---
title: "Inspecting Hermes Desktop Dom — 通过 CDP 读取运行中的 Hermes 桌面端 DOM/CSS"
sidebar_label: "Inspecting Hermes Desktop Dom"
description: "通过 CDP 读取运行中的 Hermes 桌面端 DOM/CSS"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Inspecting Hermes Desktop Dom

通过 CDP 读取运行中的 Hermes 桌面端 DOM/CSS。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/software-development/inspecting-hermes-desktop-dom` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `desktop`, `electron`, `cdp`, `dom`, `ui-verification`, `self-inspection` |
| 相关 skill | [`node-inspect-debugger`](/user-guide/skills/bundled/software-development/software-development-node-inspect-debugger), [`systematic-debugging`](/user-guide/skills/bundled/software-development/software-development-systematic-debugging), [`dogfood`](/user-guide/skills/bundled/software-development/software-development-dogfood) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# 检查运行中的 Hermes 桌面端 DOM {#inspecting-the-live-hermes-desktop-dom}

## 概述 {#overview}

当你在开发 `apps/desktop`，而用户正在运行同一个应用
（`hgui` / `npm run dev`）时，你可以读取他们正在看的窗口的**实时渲染 DOM**
——计算样式、几何尺寸、究竟是哪条 CSS 规则胜出、控制台输出——而不是从 `.tsx` 去推断然后推断错。

dev-server 运行时会自动在 `127.0.0.1:9222` 上打开一个 Chrome DevTools Protocol 端口。
渲染器是一个 Chromium 页面，因此 DevTools 能读到的一切，
脚本都能读到。

**这并不能替代亲眼查看。** CDP 回答的是*事实性*问题（"计算后的 padding
是多少"、"这个元素渲染了吗"、"哪个选择器匹配了"）。
它无法告诉你结果是否好看。色彩平衡、间距观感，
以及"这丑不丑"，仍然需要用户的眼睛或一张截图。用 CDP 回答事实；
把审美交给用户。

## 使用场景 {#when-to-use}

- 验证某个 UI 改动是否真的在运行中的应用里生效
- "为什么这个元素还是 X？"——在编辑任何东西之前先找出胜出的规则
- 为你即将修改的组件找到一个稳定的选择器
- 在真实节点上检查某个设计 token 的计算值
- 读取用户提到但无法复制出来的渲染器控制台错误

**不适用于：** 性能分析或堆相关工作（`node-inspect-debugger`、
`debugging-hermes-desktop`），或任何真正的问题是"这看起来对不对"的场景。

## 端口 {#the-port}

任何 dev-server 运行都会在 `127.0.0.1:9222` 上打开端口。只有两种情况下它是关闭的
（`apps/desktop/electron/dev-cdp.ts`）：

- **打包构建**——始终关闭，且任何环境变量值都无法覆盖；
- **没有 `HERMES_DESKTOP_DEV_SERVER`**——针对 `dist/` 运行未打包的 `electron .`
  是对打包应用进行冒烟测试的方式，因此它的行为与打包应用一致。

`HERMES_DESKTOP_CDP_PORT` 可以移动端口（`=9333`）或禁用它（`=off`）。

在做任何其他事情之前先检查：

```bash
curl -s --max-time 3 http://127.0.0.1:${HERMES_DESKTOP_CDP_PORT:-9222}/json/version
```

输出为空 → 没有端口。不要悄悄地去猜另一个端口。

**绝不要为了拿到端口而重新启动用户的应用。** 那会毁掉他们的会话和
状态。改为启动你自己的隔离实例（见下文）。

## 读取 DOM {#reading-the-dom}

`apps/desktop/scripts/eval.mjs` 是一行命令版本：

```bash
cd apps/desktop
node scripts/eval.mjs "document.querySelectorAll('[data-slot]').length"
```

多步骤的工作请使用共享客户端——它具备目标发现和
支持 promise 的 eval：

```js
import { CDP, SELECTORS } from './scripts/perf/lib/cdp.mjs'

const cdp = await CDP.connect({ port: 9222, match: '5174' })
const out = await cdp.eval(`JSON.stringify({
  radius: getComputedStyle(document.documentElement).getPropertyValue('--radius-scalar').trim(),
  composer: !!document.querySelector('[data-slot="composer-rich-input"]')
})`)
cdp.close()
```

`scripts/perf/lib/cdp.mjs` 中的 `SELECTORS` 保存着稳定的 `data-slot` 钩子
（输入框、线程视口、助手消息、轮次对、profile 侧栏）。优先使用
它们，而不是自己编一个 `querySelector`——组件移动时它们会作为一个整体
同步更新。

## 它最擅长回答的问题：哪条规则胜出了？ {#the-question-this-is-best-at-which-rule-won}

因为某个样式"没有生效"就去修改每个调用点，是典型的无用功。
先读取真实节点：

```js
const el = document.querySelector('[data-slot="aui_assistant-message-root"] a')
JSON.stringify({
  ownClasses: el.className,
  weight: getComputedStyle(el).fontWeight,
  parents: (() => {
    const out = []
    let n = el
    while ((n = n.parentElement) && out.length < 6) out.push(n.className)
    return out
  })()
})
```

如果该节点自身没有任何 class，那么这个值是**继承**来的——逐个修改
调用点解决不了问题，你需要找到祖先上的规则。插件样式表
（例如 `@tailwindcss/typography` 的 `prose a { font-weight: 500 }`）经常会压过
工具类；在共享的 class 上覆盖，而不是在每个使用处覆盖。

## 你自己的隔离实例 {#your-own-isolated-instance}

当没有端口，或者你绝不能打扰用户的窗口时：

```bash
cd apps/desktop
HERMES_HOME=/tmp/cdp-probe-home \
HERMES_DESKTOP_DEV_SERVER=http://127.0.0.1:5174 \
HERMES_DESKTOP_CDP_PORT=9333 \
  npx electron . --user-data-dir=/tmp/cdp-probe-userdata
```

单独的 `--user-data-dir` 可以避开 Electron 的单实例锁，因此它
不会与正在运行的 `hgui` 冲突；单独的 `HERMES_HOME` 则让它远离
真实会话。出于同样的原因，请选择 9222 以外的端口。在
后台运行它，用完后将其终止。

如果你还需要性能测试工具，`npm run perf:serve` 做的是同样的事，并内置了一个临时 `HERMES_HOME`。

## 常见陷阱 {#pitfalls}

- **绝不要为了"释放"什么而杀掉用户的 dev server 或应用。** 在服务过程中
  杀掉进程会摧毁 Chromium 的套接字池，随之出现的 `ERR_NETWORK_CHANGED`
  会被归咎于你刚刚改动的任何东西。
- **临时的 `HERMES_HOME` 没有后端。** 应用会为 `hermes:api` 记录 `ECONNREFUSED`，
  并可能自行退出。渲染器仍会挂载，DOM 也可读——要及时读取，
  不要把自行退出的探测实例误认为端口坏了。Chromium 在绑定端口时会记录
  `DevTools listening on ws://127.0.0.1:<port>/…`；这一行就是端口已打开的证据。
- **轮询，而不是只探测一次。** 刚启动的应用需要一两秒钟
  端口才会响应。
- **绝不要转储整个 DOM。** 桌面端会渲染数百个节点，
  `outerHTML` 会淹没你的上下文。在被求值的表达式内部
  将结果投影为一个小的 JSON 对象。
- **向 `CDP.connect` 传入 `match`。** 否则你可能会附加到宠物
  浮层、快速输入窗口或某个 devtools 目标上，而不是主窗口。
- **`cdp.eval` 直接返回值；原始的 `Runtime.evaluate` 会把它嵌套两层**
  （`.result.result.value`）。请使用封装。
- **在本仓库中，`import.meta.env.DEV` 在 `vite dev` 下为 `true`。**
  `apps/desktop/scripts/profile-typing-lag.md` 中声称相反的说明已经过时。
