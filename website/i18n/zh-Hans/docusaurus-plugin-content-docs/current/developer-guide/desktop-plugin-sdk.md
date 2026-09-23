---
title: "桌面端插件 SDK（@hermes/plugin-sdk）"
sidebar_label: "Desktop Plugin SDK"
description: "扩展原生 Hermes 桌面端应用——面板、页面、侧边栏导航、状态栏、命令面板、快捷键、主题，以及一个作用域受限的后端命名空间，只需一次 import，无需构建步骤。"
---

# 桌面端插件 SDK

原生 [Hermes 桌面端](/user-guide/desktop)应用是由贡献（contribution）驱动的：
窗口中的每一个界面——面板、路由、侧边栏导航、状态栏条目、命令面板条目、
快捷键、主题——都注册到同一个中心注册表中。核心代码注册自身界面的方式
与插件完全相同，因此插件方案是真正的一等公民，而不是事后附加的补丁。

一个**桌面端插件**就是一个默认导出 `HermesPlugin` 的单个 ESM 文件。
它只 import 一个模块——`@hermes/plugin-sdk`——便可获得一切：应用的
实时状态、网关 JSON-RPC 通道、作用域受限的 REST/socket 后端命名空间、
React Query，以及应用自身的 UI 套件，从而让插件 UI 默认就是原生观感。无需
克隆仓库、无需 `npm run build`、无需修补应用源码。把文件放进
`$HERMES_HOME/desktop-plugins/<id>/plugin.js`，应用会在数秒内加载它，
并在你每次保存时热重载。

:::warning 这不是 web dashboard 的插件 SDK
“插件”在 Hermes 中指代好几种互不相干的东西。本页讲的是**原生桌面端应用**
（`hermes desktop`）的 SDK——即 `@hermes/plugin-sdk` 模块与
`$HERMES_HOME/desktop-plugins/`。**web dashboard**（`hermes dashboard`）有它
自己的、毫不相干的插件系统，基于 `window.__HERMES_PLUGIN_SDK__` 与
`manifest.json`——文档见
[扩展 Dashboard](/user-guide/features/extending-the-dashboard)。Python
CLI/网关插件的文档见[构建 Hermes 插件](/developer-guide/plugins)。
这三者不共享代码、API 或分发方式。只有后端的 `plugin_api.py`
命名空间（`/api/plugins/<id>`）在桌面端与 dashboard 两个 SDK 之间是共享的。
:::

## 心智模型

本 SDK 沿用 VS Code 的模块模型。插件作者只 import 一个模块，永远不碰应用
内部（在打包插件中它们会被 lint 围栏挡住，在磁盘插件中则无法解析）。能力
分为若干层级：

- **`host.state.*`** —— 对应用实时状态的只读视图（nanostore
  atom）：当前会话、按会话的轮次忙碌状态、cwd、网关 socket 状态、
  模型、配置档、视口。`gateway` 指的是 WebSocket，而不是轮次忙碌状态。
- **`host.*` 动作** —— 经过筛选的安全动词：toast、导航、跟踪日志、
  重启网关、订阅网关事件流。
- **`host.request`** —— 网关 JSON-RPC 通道：会话、配置、skills、
  cron——应用自己调用的一切。
- **`ctx.rest` / `ctx.socket`** —— 如果你随插件提供了 `plugin_api.py`，
  这就是你插件自己的后端命名空间（`/api/plugins/<id>`）。
- **UI 套件导出** —— 设计语言：应用真实的组件（`Button`、`Dialog*`、
  `EmptyState` 等）、`icons` 以及格式化函数（`relativeTime`、`fmtDateTime`
  等），都从同一个模块按名导入，让你的 UI 与应用像素级一致。

## 两种分发模式

| 模式 | 位置 | 面向谁 | 构建步骤 |
|------|-------|-----|------------|
| **磁盘**（推荐） | `$HERMES_HOME/desktop-plugins/<id>/plugin.js` | 用户、智能体 | 无——纯 ESM，未经编译即加载 |
| **统一包** | `$HERMES_HOME/plugins/<id>/desktop/plugin.js` | 同时附带智能体侧代码的插件 | 无——同一条磁盘流水线 |
| **打包内置** | `apps/desktop/src/plugins/<id>/plugin.tsx` | 仓库内，随应用一同发布 | 应用自身的 Vite 构建 |

三者遵循相同的 `HermesPlugin` 契约，都会出现在**设置 → 插件**中，
并可实时启用/禁用。统一包只不过是磁盘通道在你的智能体插件文件夹内部进行扫描——参见
[一个包，两套 SDK](#one-package-both-sdks)。本页所有内容都是针对磁盘通道来写的
（也就是你和智能体所写的那种）；[打包内置插件](#bundled-plugins)会说明这两处
差异。目前核心仓库中没有发布任何桌面端插件——参考示例位于配套仓库
[`hermes-example-plugins`](https://github.com/NousResearch/hermes-example-plugins)。

## 快速开始——你的第一个插件

创建 `$HERMES_HOME/desktop-plugins/hello/plugin.js`（默认即 `~/.hermes/...`，
在具名配置档下则是 `~/.hermes/profiles/<name>/...`）。文件夹
名必须与插件 `id` 一致。

```javascript
// ~/.hermes/desktop-plugins/hello/plugin.js
import { host, haptic, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

function HelloPane() {
  const gateway = useValue(host.state.gateway)

  return jsxs('div', {
    className: 'flex h-full flex-col gap-2 p-3 text-sm',
    children: [
      jsx('div', { className: 'font-medium', children: 'Hello, Hermes' }),
      jsx('div', {
        className: 'text-(--ui-text-tertiary)',
        children: `gateway: ${gateway}`
      })
    ]
  })
}

export default {
  id: 'hello', // 必须与文件夹名一致
  name: 'Hello',
  register(ctx) {
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'hello',
      data: { placement: 'right', width: '260px' },
      render: () => jsx(HelloPane, {})
    })
    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 130,
      render: () =>
        jsx('button', {
          type: 'button',
          className: 'px-1.5 text-[0.6875rem] text-(--ui-text-tertiary)',
          onClick: () => {
            haptic('tap')
            host.notify({ kind: 'info', message: 'Hello from my plugin!' })
          },
          children: 'hello'
        })
    })
  }
}
```

保存即可。应用会监听 `desktop-plugins/`，在几秒内加载该文件，
并在此后每次保存时就地热重载。如果它没有出现，运行 ⌘K →
**Reload desktop plugins**。如果加载失败，会有一条 toast 指出错误——修复后
再次保存即可。

:::note 没有 JSX，没有构建
磁盘文件是**未经编译**加载的，因此 JSX 语法无法解析。请用
`react/jsx-runtime` 中的 `jsx()` / `jsxs()` 调用来编写 UI（或用 `React.createElement`）。
可 import 的说明符只有 `@hermes/plugin-sdk`、`react` 和
`react/jsx-runtime`——其余一律无法解析，这是有意为之。
:::

## 插件契约

插件默认导出一个 `HermesPlugin`：

```ts
interface HermesPlugin {
  /** 稳定的 slug——会成为 `plugin:<id>` 来源标记以及 id 命名空间。 */
  id: string
  /** 用于设置/关于界面的可读名称。默认为 `id`。 */
  name?: string
  /** 用户尚未做出选择时是否在加载时注册（默认 true）。对需要用户主动
   *  开启的插件设为 false：它们会列在 设置 ▸ 插件 中，在用户拨动开关
   *  之前保持关闭。 */
  defaultEnabled?: boolean
  /** 加载时调用一次；通过 `ctx` 接入各项贡献。 */
  register: (ctx: PluginContext) => void
}
```

`register` 收到的是一个**作用域受限的** `PluginContext`。它永远不会直接触碰
注册表——该上下文会自动打上来源标记（`source: 'plugin:<id>'`），并为每一项
贡献的 id 加上命名空间（`<id>:<localId>`），因此两个插件永远不会冲突。

```ts
interface PluginContext {
  /** 解析出的来源标记，例如 `'plugin:hello'`。 */
  readonly source: string
  /** 注册一项贡献（id 带命名空间，来源已打标）。返回一个销毁函数。 */
  register: (c: PluginContribution) => () => void
  /** 一次注册多项；返回的销毁函数会移除所有这些贡献。 */
  registerMany: (cs: PluginContribution[]) => () => void
  /** 访问本插件自身后端命名空间（`/api/plugins/<id>`）的 REST。 */
  rest: <T>(path: string, opts?: PluginRestOptions) => Promise<T>
  /** 连接到本插件自身命名空间的实时 WebSocket。返回一个销毁函数。 */
  socket: (path: string, onMessage: (data: unknown) => void) => () => void
  /** 经过筛选的 OS 通道：原生通知、外部打开、在文件管理器中显示、剪贴板。 */
  os: PluginOs
  /** 插件作用域的 JSON 持久化（键位于 `hermes.plugin.<id>.` 之下）。 */
  storage: PluginStorage
}
```

**贡献（contribution）**是所有界面共享的那一个原语：

```ts
interface Contribution {
  id: string          // 你写本地 id；宿主负责加命名空间
  area: string        // 放在哪里（一个贡献区域常量）
  title?: string
  order?: number      // 区域内的排序（越小越靠前）
  when?: () => boolean // 动态可见性；由该区域重新求值
  enabled?: boolean
  render?: () => ReactNode  // 要挂载的组件
  data?: unknown      // 区域相关的载荷（见操作手册）
}
```

你需要提供 `render`、`data` 或两者，具体取决于所在区域。

## 贡献区域——操作手册

从 SDK 中 import 区域常量；每个区域都有自己的 `data` 载荷。

| 界面 | `area` | 你需要提供 |
|---------|--------|-------------|
| 布局面板 | `PANES_AREA`（`'panes'`） | `title` + `render` + `data: { placement, dock?, width?, height? }` |
| 整页 | `ROUTES_AREA` | `data: { path }` + `render` |
| 侧边栏导航 | `SIDEBAR_NAV_AREA` | `data: { path, label, codicon }` |
| 状态栏 | `STATUSBAR_AREAS.left` / `.right` | `render`（或作为 `StatusbarItem` 的 `data`） |
| 标题栏 | `TITLEBAR_AREAS.left` / `.center` / `.right` | 作为 `TitlebarTool` 的 `data`，或一个挂载作用域的 `<Contribute>` |
| ⌘K 命令面板 | `PALETTE_AREA` | `data: PaletteContribution` |
| 快捷键 | `KEYBINDS_AREA` | `data: KeybindContribution` |
| 主题 | `THEMES_AREA` | 作为 `DesktopTheme` 的 `data` |
| 输入框 | `COMPOSER_AREAS.*` | 渲染插槽，或中间件 / 附件提供者 |

### 面板

面板是布局树中的一块区域。`placement` 表示语义角色——该面板会与已有的
同角色面板堆叠（以标签页形式）；用户之后可以把它拖到任何地方。

```javascript
ctx.register({
  id: 'pane',
  area: 'panes',
  title: 'my pane',
  data: { placement: 'right', width: '260px' },
  render: () => jsx(MyPane, {})
})
```

`placement` 取值为 `'main' | 'left' | 'right' | 'top' | 'bottom'`。若想停靠到某个
特定**边缘**而不是堆叠，请加上 `dock` 手势——它与把面板拖到某个面板的
投放标记上是同一回事：

```javascript
// 位于对话下方，高 200px。
data: {
  placement: 'bottom',
  dock: { pane: 'workspace', pos: 'bottom' },
  height: '200px'
}
```

`dock.pane` 可以是任意面板 id（`workspace` 是主对话；还有 `sessions`、
`terminal`、`files`、`review`、`logs`）；`dock.pos` 取值为
`'top' | 'bottom' | 'left' | 'right' | 'center'`。请声明 `width`/`height`，
以免面板占掉整个区域的一半。

关闭某个插件贡献的唯一面板会禁用该插件，之后可在**设置 → 插件**中重新启用。
当一个插件贡献了多个面板时，关闭其中一个只会移除该面板，插件的其他面板、
命令与中间件仍保持激活。**Reset layout** 会恢复被移除的贡献面板。

### 页面与侧边栏导航

路由会在工作区面板中挂载一整个页面，就像任何内置视图一样。给它配上一行
侧边栏导航（和/或一条命令面板命令），才能让它可达。

```javascript
import { ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'

ctx.registerMany([
  {
    id: 'page',
    area: ROUTES_AREA,
    data: { path: '/my-page' },
    render: () => jsx(MyPage, {})
  },
  {
    id: 'nav',
    area: SIDEBAR_NAV_AREA,
    data: { path: '/my-page', label: 'My Page', codicon: 'project' }
  }
])
```

`codicon` 是一个 [VS Code codicon](https://microsoft.github.io/vscode-codicons/dist/codicon.html)
id。在任意位置都可以用 `host.navigate('/my-page')` 导航到某个路由。

### 状态栏与标题栏

状态栏条目会渲染到底栏的左侧或右侧簇中。
最简单的是用 `render` 函数；若只需要一个普通按钮，可用作为
`StatusbarItem` 的 `data`（`{ id, label?, icon?, detail?, variant?, menuItems?, … }`）。

```javascript
import { STATUSBAR_AREAS, TITLEBAR_AREAS } from '@hermes/plugin-sdk'

ctx.register({
  id: 'count',
  area: STATUSBAR_AREAS.right,
  order: 120,
  render: () => jsx(MyStatus, {})
})
```

标题栏工具位于 `TITLEBAR_AREAS.left | .center | .right`，以 `TitlebarTool`
数据形式提供（`{ id, label, icon, active?, onSelect? }`）。

### 命令面板命令与快捷键

```javascript
import { PALETTE_AREA, KEYBINDS_AREA } from '@hermes/plugin-sdk'

ctx.registerMany([
  {
    id: 'open',
    area: PALETTE_AREA,
    data: {
      id: 'my-page.open',
      label: 'Open My Page',
      keywords: ['my', 'page'],
      run: () => host.navigate('/my-page')
    }
  },
  {
    id: 'refresh',
    area: KEYBINDS_AREA,
    data: {
      id: 'my-page.refresh',
      label: 'Refresh My Page',
      category: 'My Plugin',
      defaults: ['mod+shift+r'],
      run: () => void doRefresh()
    }
  }
])
```

快捷键可由用户在设置中重新绑定；`defaults` 只是初始绑定。

### 主题

主题贡献以其 `data` 提供一个完整的 `DesktopTheme`（name、label、
colors 等）。它会像内置主题一样出现在主题选择器中。

```javascript
import { THEMES_AREA } from '@hermes/plugin-sdk'

ctx.register({ id: 'noir', area: THEMES_AREA, data: myDesktopTheme })
```

注册主题只是把它列出来，并不会选中它。`useTheme()` 可以在组件中读取当前
呈现的外观（`theme`、`themeName`、`availableThemes`、`resolvedMode`）并修改它
（`setTheme`、`setMode`、`previewTheme`）：

```javascript
import { Button, useTheme } from '@hermes/plugin-sdk'

function ThemePicker() {
  const { availableThemes, setTheme, themeName } = useTheme()

  return availableThemes.map(t => (
    <Button key={t.name} disabled={t.name === themeName} onClick={() => setTheme(t.name)}>
      {t.label}
    </Button>
  ))
}
```

由渲染之外的事情驱动的切换——网关建立连接、一个 socket 事件、任意
`host.onEvent` 回调——没有可以挂载该 hook 的组件。此时请使用 `requestTheme(name)`。
无法解析的名称会被拒绝，而不是被强制回退到默认皮肤，因此返回值同时充当
可用性检查，错误的名称永远不会悄无声息地重置某人的外观：

```javascript
import { host, requestTheme } from '@hermes/plugin-sdk'

host.onEvent('gateway.ready', () => {
  if (!requestTheme('noir')) {
    host.notifyError('Connected, but the noir theme is not installed.')
  }
})
```

两种方式都会按配置档持久化，因此由插件驱动的切换与手动选择一样会保留下来。
若想给*当前*主题着色而不是替换它，请使用 `setAccentOverride(hex)`，并在
`ctx.onDispose` 中清除它——捆绑的 `accent` 插件就是现成的示例。

### 输入框扩展

`COMPOSER_AREAS`（`top`、`bottom`、`leading`、`actions`、`attachments`、
`middleware`）允许插件在消息输入框周围添加控件、提供
附件来源，或在草稿被发送前对其进行变换（`ComposerMiddleware`，
带有 `handler(draft) => draft | null`）。

### 转录指令——由模型调用的内联组件 {#transcript-directives--inline-components-the-model-addresses}

`TRANSCRIPT_DIRECTIVE_AREA` 让转录本身也成为一个贡献区域。注册一个具名指令后，
智能体只要输出一个形如 `::name{key="value"}` 的段落，就能在助手消息中内联渲染你的组件：

```javascript
import { TRANSCRIPT_DIRECTIVE_AREA } from '@hermes/plugin-sdk'

ctx.register({
  id: 'task-card',
  area: TRANSCRIPT_DIRECTIVE_AREA,
  data: {
    name: 'task', // 模型会写出 ::task{id="BB-12"}
    render: ({ attrs, streaming }) => jsx(TaskCard, { taskId: attrs.id, streaming })
  }
})
```

宿主会强制执行以下规则，以保证这一界面的安全：

- 指令必须构成**整个段落**——出现在正文中间的 `::name` 仍然是正文，因此插件组件
  永远无法劫持连续的文本。
- 属性是**不可信的模型输出**（`key="value"` 键值对，只能是字符串）。
  请自行校验字段；遇到垃圾输入时什么都不渲染，而不是去猜。
- **无人认领**的指令（没有插件为该名称注册）会渲染为它原本的普通段落——
  插件关闭时不会有任何东西坏掉。
- 渲染被包裹在贡献错误边界中：抛出的异常会降级为一个内联错误标记，
  而不会让整条消息失效。
- 名称冲突时先注册者胜出；对容易撞名的名称请用你的 slug 加命名空间
  （`myplugin-board`，而不是 `board`）。

核心附带了一个指令作为参考消费方：`::preview{file="…"}` 会把工作区中的 HTML 文件
**在消息内实时渲染**——一个带不透明源（opaque origin）的沙箱化 `srcdoc` iframe
（脚本会运行，组件完全可交互；但无法触及应用、其存储或桥接层）。该框架会根据内容
调整自身尺寸（高度实时跟随，宽度采用内容的固有宽度，在消息流中左对齐），并由一段
主题前导代码把应用解析后的 token（`--foreground`、`--muted-foreground`、
`--accent`、`--border`、`--card`）、应用字体和透明背景交给文档——于是组件形态的
HTML 看起来就像原生界面，而完整页面则保留其自身设计。非 HTML 目标以及远端网关会
回退到经典的预览卡片。请在一个 skill 中把你的指令告诉智能体（它正是这样学会输出该指令的）。

被预览的组件还可以**回传消息**。在框架内部，
`window.hermes.send('get-price eth')`（或者声明式的
`<button data-hermes-send="get-price eth">`——无需脚本）会把该提示词作为一条
用户轮次交给智能体，且不显示在屏幕上：转录中不会出现气泡，组件的更新就是可见的
响应。这个轮次仍然是真实的——它会唤醒智能体、遵循输入框的 steer/queue 规则，
并被持久化（类型为 `hidden`），因此恢复会话与会话数据库都保有完整记录。
提示词会被裁剪、上限为 500 个字符，并按每个框架每秒一条进行节流。

### 挂载作用域的界面元素（`Contribute`）

`ctx.register` 用于**长期存在**的贡献。当某些界面元素应当随一个已经在屏幕上的
组件一起生死时（例如某个页面自己的标题栏控件应在页面卸载时消失），
请改为在该组件内部渲染 `<Contribute>`：

```javascript
import { Contribute, TITLEBAR_AREAS } from '@hermes/plugin-sdk'

jsx(Contribute, {
  area: TITLEBAR_AREAS.center,
  id: 'my-page:switcher', // 用你的 slug 作命名空间
  children: jsx(MySwitcher, {})
})
```

它会在挂载时注册，并在卸载时自动销毁。

## Host API

`host` 上的一切在插件的任何位置都可访问。状态 atom 是
只读的——在处理函数中用 `.get()` 读取，在组件中用 `useValue(atom)` 订阅。

```ts
host.state.activeSessionId  // ReadableAtom<string | null>
host.state.awaitingResponse // ReadableAtom<boolean>  在收到第一个助手载荷之前为 true
host.state.busy             // ReadableAtom<boolean>  聚焦的对话在发送后正在工作
host.state.busyBySession    // ReadableAtom<Record<string, boolean>>  运行时 id → 是否处于轮次中
host.state.focusedSessionId // ReadableAtom<string | null>  （聚焦会话的运行时 id——感知分块；session.* RPC 优先使用它）
host.state.focusedSessionProfile // ReadableAtom<string>  （聚焦对话的所属配置档——按 bot/配置档展示时优先于 `profile`）
host.state.focusedStoredSessionId // ReadableAtom<string | null>  （持久 id——用于导航 / 会话列表匹配）
host.state.focusedUsage     // ReadableAtom<UsageStats | null>  （聚焦会话实时流式的用量，无需 RPC）
host.state.cwd              // ReadableAtom<string>
host.state.gateway          // ReadableAtom<string>  socket 状态（'idle' | 'connecting' | 'open' | …）
host.state.model            // ReadableAtom<string>
host.state.profile          // ReadableAtom<string>
host.state.viewport         // ReadableAtom<{ width, height, narrow }>
```

`host.state.gateway` 表示的是 WebSocket 连接，而不是某个对话轮次是否正在运行。
一个会话可能在 socket 为 `open` 时处于轮次中；同时另一个会话可能是空闲的。
请根据**聚焦会话**的轮次忙碌状态（`host.state.busyBySession[sessionId]`，或该会话的
`view.$busy`）来禁用输入框或插件动作——绝不要依据 `gateway`，也绝不要依据
进程级的全局忙碌标志。

```ts
host.notify({ kind, message, title?, detail?, action? })  // toast；返回 id
host.notifyError(error, fallbackMessage)                   // 以 toast 形式提示错误
ctx.os.notify({ title, body?, silent?, icon?, activate?, onActivate?, actions? })
                                           // 原生 OS 通知（归属到你的插件）
ctx.os.openExternal(url)                   // OS 默认处理程序（浏览器、邮件、spotify:）→ Promise<boolean>
ctx.os.revealPath(path)                    // 在 Finder / 资源管理器中显示 → Promise<boolean>
ctx.os.writeClipboard(text)                // 系统剪贴板 → Promise<boolean>
host.navigate('/route')                    // hash 路由导航
host.openSession(id, { profile?, intent? }) // 以核心方式打开一个已存储的会话；
                                           //   profile：先软切换到该配置档的后端
                                           //   intent：'in-place'（默认）| 'stack' | 'tab' | 'window'
host.newChat(profile?)                     // 新的对话草稿，可选地位于另一个配置档
host.openWorkspace(id, { render, title?, minWidth?, onClose? })
                                           // 把插件渲染的标签页停靠到主
                                           //   工作区区域并显示它；返回一个销毁函数
host.paneVisibility(paneId)                // ReadableAtom<boolean>——某个贡献面板
                                           //   是否真的在屏幕上（是其区域的活动标签页）？
host.onEvent(type, fn)                     // 网关事件流（'*' = 全部）；返回销毁函数
host.logs(...)                             // 跟踪某个应用日志文件
host.status()                              // 一次性的系统状态快照
host.restartGateway()                      // 重启后端网关
host.profileRoutes()                       // [{ profile, targetProfile, connectionId, mode }]
host.requestProfile<T>(route, method, params?)   // 经注册表路由的 RPC；不切换前台
host.requestProfile<T>(profile, method, params?) // 旧版 v1/本地重载
host.request<T>(method, params?)           // 当前网关的 JSON-RPC —— 真正的威力所在
```

`host.request` 就是应用自己使用的那套 JSON-RPC（会话、配置、skills、
cron、kanban 等）。`host.requestProfile` 接受来自 `host.profileRoutes()` 的描述符，
并把该 RPC 经由其确切的注册表来源与配置档进行路由，而不改变当前对话或网关。
仅接受配置档的重载只为单一本地/旧版拓扑而保留；感知注册表的插件应当传入描述符，
这样暴露同名配置档的两个来源就不会发生冲突。

`host.openWorkspace(id, { render, title?, minWidth?, onClose? })` 会把插件渲染的视图
以标签页形式停靠到**主工作区区域**——也就是会话分块与预览所使用的同一中央区域——
并显示它。用相同的 `id` 再次调用会就地刷新内容并把该标签页重新置前，而不是打开一个
重复的标签页。关闭该标签页（标签页的关闭控件或 ⌘W）会拆除注册并触发你的 `onClose`；
返回的销毁函数可以以编程方式关闭它。请做特性检测（`typeof host.openWorkspace ===
'function'`），并在较旧的桌面端版本上回退到普通的贡献面板——Bot Mode 的群聊房间
就是参考消费方（可用时接管主窗口，否则使用面板内视图）。

`host.paneVisibility(paneId)` 返回一个只读的响应式 atom，当某个贡献面板真正显示在
屏幕上时为 `true`：存在于布局树中、未被移除或隐藏、其区域未被最小化，并且占据其
区域的活动标签页位置（独占一个区域的单个面板也算）。id 是贡献作用域的面板 id，
即 `<pluginId>:<paneId>`。atom 按 id 进行记忆化，因此在渲染中调用它是安全的。
用它来仅在你的面板可见时注册配套 UI——Bot Mode 的 Cronjobs 面板就是参考消费方：
它在 Bots 面板占据侧边栏标签页时注册，并在用户切回 Sessions 时取消注册。
在较旧的桌面端上请做特性检测（`typeof host.paneVisibility === 'function'`），
并回退到始终注册的行为。

`host.profileRoutes()` 会盘点当前连接注册表中每一个已注册的来源。按需连接的 SSH
来源会暴露一个不含凭据的 `default` 种子路由而不打开隧道，因此插件可以成为第一个
拨通它们的调用方；SSH 的 `remoteProfile` 仍然是该路由的后端 `targetProfile`。
`connectionId` 是注册表的路由标识；
把它与 `profile` 搭配用于键与持久化。端点、token、SSH 主机/密钥以及其他原始连接
字段永远不会跨越插件 IPC 边界。`profile` 是用于请求的来源本地路由；
`targetProfile` 是该路由所服务的后端 Hermes 配置档。
当某个路由显式映射到另一个后端配置档时（例如 SSH 的 `remoteProfile` 覆盖或旧版的
按配置档 URL 别名），两者会不同。这种区分在不暴露连接密钥的前提下保留了后端身份。

面向配置档的插件也有一等方法可用：
`profiles.list`（每个配置档及其最近一次对话，作为 `last_session`；传入
`include_sessions: false` 可跳过按配置档的数据库探测；传入
`preferred_session_ids: { profileName: sessionId }` 可对每个配置档的一个固定会话进行
精确且经存在性校验的查找——每个被点名的行会得到一个 `preferred_session` 摘要，
它会把隐藏行与压缩谱系解析到其当前的最新端点，若该 id 确定已不存在则为 `null`；
较旧的网关会忽略此参数并省略该字段）
以及 `profiles.create`（`name`、`description`、`clone_from`、
`clone_all`、`no_skills`、`soul`，可选的 `model` + `provider` 固定）——它们是
dashboard 的 `/api/profiles` REST 路由在 ws 上的孪生版本。
`host.state.busy` 是聚焦对话的实时轮次（思考与流式输出）。
`host.state.awaitingResponse` 从发送起一直为 true，直到收到第一个助手载荷。
两者都跟随用户实际正在查看的对话——有会话分块持有焦点时为该分块，否则为主工作区
对话（与状态栏忙碌脉冲读取的是同一信号）。在组件中订阅：

```javascript
const busy = useValue(host.state.busy)
```

若需要 token 级别的细节，请用 `host.onEvent` 监听（`message.start`、
`message.delta`、`message.complete`）。

`host.onEvent` 会流式推送实时网关事件（消息增量、
会话生命周期、工具活动）。监听器之间彼此隔离——你的监听器中抛出的异常
不会影响应用的事件派发。每一个 `host` 通道都是异步安全的：内部辅助函数
抛出的同步异常（例如在普通浏览器中没有桌面端桥接）会变成你的 `.catch()`
能捕获的 rejection，而绝不会是导致错误边界崩溃的异常。

`ctx.os` 是经过筛选的 OS 通道——插件触及应用窗口之外的所有方式，都集中在一个
归属到你插件的命名空间中。`ctx.os.notify` 会发出一条**原生 OS 通知**——与应用自身的
审批/轮次提醒所用的是同一条 Electron 流水线。它只在用户离开 Hermes 时触发
（处于后台 / 未聚焦）；当用户正在看着应用时，请用 `host.notify` 显示应用内 toast。
用户可以在 设置 ▸ 通知 ▸ “Plugin notifications” 中按设备将其静音，并且同一插件的
重复通知会被节流，所以请把它当作真正值得关注的事件的信号——而不是日志。

丰富的呈现与激活（扩展了最初的 `ctx.os` 通道）：

```ts
ctx.os.notify({
  title: 'New match found',
  body: 'Someone matched your signal',
  icon: '/abs/path/to/icon.png', // Electron Notification 图标
  // 点击正文 → 聚焦 Hermes 并导航。与 OS 深度链接使用相同的写法：
  activate: 'hermes://index-network/intent/1',
  // 或：activate: '/index-network/intent/1'
  // 或：activate: { path: '/index-network/intent/1' }
  onActivate: () => focusLocalState('1'), // 可选的渲染进程回调
  actions: [
    { id: 'open', label: 'Open', activate: 'hermes://index-network/intent/1' },
    { id: 'dismiss', label: 'Dismiss', onAction: () => dismiss('1') },
  ],
})
```

`activate` 与深度链接兼容：`hermes://index-network/intent/1` 与 hash 路径
`/index-network/intent/1` 会解析到同一个应用内路由（同样的 `hermes://…` URL 也可作为
OS 深度链接使用）。操作按钮只在已签名的 macOS 版本上渲染；在其他平台上点击正文
仍然会激活。导航只会在用户点击时发生——绝不会仅由后台事件触发。

其他通道（`openExternal`、`revealPath`、`writeClipboard`）在能力不可用时
（较旧的桌面端外壳、普通浏览器）会 resolve 为 `false` 而不是抛出异常——请根据
结果分支，而不是去嗅探桥接层。

## 数据层——React Query + nanostores

插件共享应用唯一的 `QueryClient`，因此插件的查询在缓存、去重、
轮询和失效方面与核心界面完全一致——切勿手写取数循环。

```javascript
import { useQuery, useMutation, useQueryClient, atom, computed, useValue } from '@hermes/plugin-sdk'

function MyPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['my-plugin', 'items'],
    queryFn: () => host.request('my.list', {})
  })
  // …
}
```

对于需要在触发器与其面板之间（或轮询循环中）共享的状态，请使用 `atom` /
`computed`——正是 `host.state` 所用的那个原语。在真正渲染该值的叶子节点上
用 `useValue` 订阅。若要从 React **之外**让某个查询失效
（例如收到一个 `ctx.socket` 帧时），请 import 共享的 `queryClient`：

```javascript
import { queryClient } from '@hermes/plugin-sdk'

ctx.socket('/events', () => {
  queryClient.invalidateQueries({ queryKey: ['my-plugin', 'items'] })
})
```

## UI 套件与主题

直接 import 应用真实的组件，你的 UI 便默认是原生观感：

> `Button`、`Input`、`Textarea`、`Select*`、`Switch`、`Checkbox`、
> `SegmentedControl`、`Tabs*`、`Dialog*`、`ConfirmDialog`、`DropdownMenu*`、
> `ContextMenu*`、`Popover*`、`Tip`/`Tooltip*`、`Badge`、`Kbd`/`KbdGroup`、
> `SearchField`、`ScrollArea`、`Separator`、`Skeleton`、`GlyphSpinner`、`Loader`、
> `EmptyState`、`ErrorState`、`CopyButton`、`StatusDot`、`LogView`、`Codicon`、
> `DecodeText`。

此外还有一些辅助工具：`cn`（类名合并）、`icons.*`（应用的 lucide 图标集）、`haptic`、
`profileColor` / `profileColorSoft`（确定性的身份配色）、时间
格式化函数 `relativeTime` / `fmtDateTime` / `fmtDayTime` / `coarseElapsed`、
`useI18n`（本地化文案——让你的插件保持可翻译），以及
`evaluateRuntimeReadiness`。

**用主题变量来设置样式，绝不要硬编码颜色。** 面板本就位于
应用的编辑器背景之上——不要动背景，其余一切都用变量：
`var(--ui-text-secondary)`、`var(--ui-text-tertiary)`、
`var(--ui-text-quaternary)`、`var(--ui-stroke-secondary)`、`var(--ui-accent)`。
若要在画布上绘制，请用
`getComputedStyle(canvas).getPropertyValue('--ui-accent')` 解析一次。正是这一点让
插件能随每一个主题自动换肤。

## 为你的插件配一个后端

如果你的插件需要服务端工作，请随插件提供一个 Python `plugin_api.py`，并通过
`ctx.rest` / `ctx.socket` 访问它——这个命名空间**在构造上**就限定在你的插件之内。

### 一个包，两套 SDK {#one-package-both-sdks}

一个既需要桌面端 UI **又**需要智能体侧代码（一个 Python 插件、它的后端路由、skills）
的功能，不必拆成两个相互依赖的安装包来发布。桌面端应用还会扫描
`$HERMES_HOME/plugins/<id>/`——也就是常规的智能体插件根目录——寻找
`desktop/plugin.js`，并通过与独立磁盘通道完全相同的流水线加载它（包括热重载）：

```
~/.hermes/plugins/<id>/           # 一个可安装的文件夹
├── plugin.yaml                   # 智能体一半：工具、钩子、命令
├── skills/…
├── dashboard/
│   ├── manifest.json             # { "name": "<id>", "api": "plugin_api.py" }
│   └── plugin_api.py             # 后端路由 → /api/plugins/<id>/
└── desktop/
    └── plugin.js                 # 桌面端一半：面板、命令、ctx.rest
```

`desktop/plugin.js` 这一半就是一个普通的磁盘插件——相同的契约、相同的 import，
同样用 `ctx.rest('/…')` 访问与它并列的 `plugin_api.py`。安装、分享或移除该功能
都只涉及一个文件夹。

两个启用开关仍然各自生效，这是有意为之，并且两者默认都是**关闭**的：桌面端这一半
以需要用户主动开启的方式发布——它会列在**设置 → 插件**中，但在用户拨动开关之前
保持禁用——这与 Python 一半在 `config.yaml` 中的 `plugins.enabled` 门控相对应
（即下文的安全边界）。把一个包放进 `~/.hermes/plugins`，在用户另行决定之前，
它在任何界面上都是惰性的。当后端一半关闭时，桌面端一半会优雅降级——
`ctx.rest` 返回错误，而不是崩溃。

:::note
该扫描只针对运行桌面端应用的那台机器本地。连接远端后端时，远端机器的
`~/.hermes/plugins` 无法作为文件系统访问——只有本地安装的包才会贡献桌面端一半
（与独立通道的规则相同）。
:::

### 通过安装链接分发 {#install-link}

发布你的插件仓库（智能体一半、桌面端一半或两者），并用 `hermes://` scheme
链接到它——在你的网站或 README 中放一个普通锚点即可：

```html
<a href="hermes://plugin/install?repo=owner/repo&enable=1">Install in Hermes</a>
```

用户会看到一个确认对话框（仓库 id、来源链接、对仓库所含内容的探测），并在安装
任何东西之前选择组件——深度链接永远不会自动安装。`force=1` 会替换已有的安装；
开发版本使用 `hermes-dev://`。完整的链接参考见：
[一键安装链接](/user-guide/features/plugins#one-click-install-links-desktop)。

### Python 一侧

桌面端插件复用 dashboard 插件的后端挂载方式。把后端放在一个普通 Hermes 插件的
`dashboard/` 子目录中，并在 `manifest.json` 中声明：

```
~/.hermes/plugins/<id>/
└── dashboard/
    ├── manifest.json      # { "name": "<id>", "api": "plugin_api.py" }
    └── plugin_api.py      # 导出 `router = APIRouter()`
```

```python
# plugin_api.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/board")
async def board():
    return {"items": ["one", "two", "three"]}

@router.post("/action")
async def action(body: dict):
    return {"ok": True, "received": body}
```

路由挂载在 `/api/plugins/<id>/` 之下（`GET /api/plugins/<id>/board` 等）。
后端代码运行在网关进程内，因此它可以直接从
hermes-agent 代码库 import（`hermes_state`、`hermes_cli.config` 等）。完整的后端参考见
[扩展 Dashboard → 后端 API 路由](/user-guide/features/extending-the-dashboard#backend-api-routes)
——挂载方式完全相同。

:::caution Python 后端是单独受控的
在桌面端**设置 → 插件**面板中启用一个插件，只是渲染进程一侧的
选择；它**不会** import Python。用户插件的 `plugin_api.py` 只有在该插件
位于 `config.yaml` 的 `plugins.enabled` 白名单中（且不在 `plugins.disabled` 中）
时才会被 import。项目级插件（`./.hermes/`）
永远不会自动 import Python。这是一条安全边界，不是疏漏
（GHSA-mcfc-hp25-cjv7）。
:::

### 从插件中调用它

```javascript
register(ctx) {
  // REST —— 相对于命名空间的路径。
  const load = () => ctx.rest('/board')                 // GET /api/plugins/<id>/board
  const act  = () => ctx.rest('/action', { method: 'POST', body: { go: true } })

  // 实时孪生 —— 连接到你自己命名空间的 WebSocket。
  const stop = ctx.socket('/events', frame => {
    queryClient.invalidateQueries({ queryKey: [ctx.source, 'board'] })
  })
}
```

`ctx.rest` 是感知配置档的，并会拒绝路径穿越（`..`），所以你绝不可能通过它
访问另一个插件的 API 或某条核心路由。`PluginRestOptions` 为
`{ method?, body?, upload?: { filename, contentType?, bytes }, timeoutMs? }`。

`ctx.socket` 会以退避策略自动重连，直到被销毁。**在 OAuth 远端上它会退化为
空操作**（一次性的 WS 票据由核心管理）——请把 socket 当作轮询之上的
加速手段，而绝非替代品。反正每个消费方都需要轮询回退，因为任何 socket 都可能断开。

对于网关级别的数据（而非你自己的命名空间），请改用 `host.request`（JSON-RPC）与
`host.onEvent`（网关事件流）。

## 设置、启用状态与存储

每个插件——无论是否启用——都会列在**设置 → 插件**中，用户可在那里
实时开关它（无需重启应用）、显示其文件夹或重新扫描。用户的
选择会被记住：

- 尚未做出选择 → 采用插件自身的 `defaultEnabled`（默认 `true`）。设置
  `defaultEnabled: false` 可发布一个需要用户主动开启的插件，在用户
  拨动开关之前保持沉默。
- 已明确选择 → 会被持久化并在重启后沿用。被禁用的插件
  保持禁用——不要跟它较劲；是用户把你关掉的。

用 `ctx.storage` 持久化你自己的状态，它按插件加了命名空间
（`hermes.plugin.<id>.*`），因此插件之间无法互相读取或覆盖：

```javascript
ctx.storage.set('lastTab', 'board')
const tab = ctx.storage.get('lastTab', 'summary')
ctx.storage.remove('lastTab')
```

## 打包内置插件 {#bundled-plugins}

插件也可以随仓库内置于 `apps/desktop/src/plugins/<id>/plugin.tsx`（默认
导出一个 `HermesPlugin`）。它会在启动时由 `discoverBundledPlugins()` 发现——
无需 import、无需改动注册表——并与磁盘插件共享完全相同的清单与实时
启用/禁用契约。两处差异是：

1. 它会经过应用的 Vite 构建，因此你可以写**真正的 JSX**，并通过
   `@hermes/plugin-sdk` 别名 import SDK。
2. 它仍然被 lint 围栏限制为只能用 `@hermes/plugin-sdk` + `react`——不能用 `@/…` 应用
   内部模块。

目前核心仓库中没有发布任何桌面端插件；发布的应用保持精简，
示例则位于配套仓库
[`hermes-example-plugins`](https://github.com/NousResearch/hermes-example-plugins)。

## 安全模型

被加载的插件会以 ESM 形式在渲染进程 realm 中求值，并拥有**完整的应用
权限**——React 单例、整个 SDK（`host.request` 网关 RPC、
`ctx.rest`、storage、`navigate`）。加载器提供的隔离**只是错误
隔离**：插件无法让应用崩溃（贡献有错误边界，监听器彼此隔离），但它可以
做应用能做的任何事。

对于**本地**来源这是可接受的——一个磁盘文件本来就能在你的机器上运行
代码——这也正是磁盘通道只加载你（或你的智能体）编写的本地文件的原因。
可选的 `integrity`（`sha256-…`）校验只能证明字节与某个哈希匹配；它**不会**
沙箱化。未来的远端来源通道在落地之前需要一条真正的边界
（iframe/worker + CSP + 能力门控）；不要把这条流水线当成信任边界。

## 常见陷阱

- **磁盘插件中的 JSX 无法解析。** 文件是未经编译加载的——请用 `jsx()` /
  `jsxs()`（或 `React.createElement`），而不是 JSX 语法。（打包内置插件是构建过的，
  在那里用 JSX 没问题。）
- **只有三个说明符可以解析：** `@hermes/plugin-sdk`、`react`、
  `react/jsx-runtime`。任何其他 import 都会在加载时直接报错。
- **绝不要硬编码颜色**（`#000`、`black`、`rgb(...)`）。不要动背景；
  其余一切都用主题变量（`var(--ui-*)`）。
- **只引用你 import 过的东西。** 忘记 import 的组件（例如
  `StatusDot`）会在渲染时抛出 `ReferenceError`——请逐一核对你
  `jsx()` 调用中出现的每个标识符都在 import 行里。
- **在处理函数中以命令式方式读取状态**（`$atom.get()`），绝不要从渲染
  闭包里读——否则快速事件会读到过期的值。只在真正渲染该值的
  叶子节点上订阅（`useValue`）。
- **画布面板必须用 `ResizeObserver` 跟踪其容器**并调整画布尺寸
  （width/height 属性，而不只是 CSS）——面板会不断改变大小。
- **不要用 `host.request` 以快于几秒的频率轮询**；优先使用
  `host.onEvent` / `ctx.socket`，并让 React Query 去做去重。
- **`ctx.socket` 在 OAuth 远端上是空操作。** 请始终准备轮询回退。

## 参考

### SDK 导出一览

| 类别 | 导出项 |
|----------|---------|
| Host | `host`（`.state.*`、`.notify`、`.notifyError`、`.navigate`、`.onEvent`、`.logs`、`.status`、`.restartGateway`、`.request`） |
| 插件契约 | `HermesPlugin`、`PluginContext`、`PluginContribution`、`PluginStorage`、`PluginOs`、`PluginRestOptions`、`PluginNativeNotificationInput`、`PluginNotificationAction`、`HermesOpenTarget`、`Contribution` |
| 区域常量 | `PANES_AREA`、`ROUTES_AREA`、`SIDEBAR_NAV_AREA`、`STATUSBAR_AREAS`、`TITLEBAR_AREAS`、`PALETTE_AREA`、`KEYBINDS_AREA`、`THEMES_AREA`、`COMPOSER_AREAS` |
| 区域载荷 | `RouteContribution`、`SidebarNavContribution`、`StatusbarItem`、`TitlebarTool`、`PaletteContribution`、`KeybindContribution`、`ComposerMiddleware`、`ComposerAttachmentProvider` |
| React / 状态 | `useValue`、`atom`、`computed`、`useQuery`、`useMutation`、`useQueryClient`、`queryClient`、`Contribute` |
| 主题 | `useTheme`、`requestTheme`、`setAccentOverride`、`$accentOverride`、`retintTheme`、`themeHue`、`DesktopTheme`、`DesktopThemeColors`，以及 OKLCH 数学函数（`hexToOklch`、`oklchToHex`、`oklchToSrgb255`、`mixOklab`、`maxChroma`、`hueDelta`、`contrastRatio`、`readableOn`、`normalizeHex`） |
| UI 套件 | `Button`、`Input`、`Textarea`、`Select*`、`Switch`、`Checkbox`、`SegmentedControl`、`Tabs*`、`Dialog*`、`ConfirmDialog`、`DropdownMenu*`、`ContextMenu*`、`Popover*`、`Tip`/`Tooltip*`、`Badge`、`Kbd`/`KbdGroup`、`SearchField`、`ScrollArea`、`Separator`、`Skeleton`、`GlyphSpinner`、`Loader`、`EmptyState`、`ErrorState`、`CopyButton`、`StatusDot`、`LogView`、`Codicon`、`DecodeText` |
| 辅助工具 | `cn`、`icons`、`haptic`、`useI18n`、`profileColor`、`profileColorSoft`、`relativeTime`、`fmtDateTime`、`fmtDayTime`、`coarseElapsed`、`evaluateRuntimeReadiness` |

始终最新的权威导出列表是 `apps/desktop/src/sdk/index.ts`。

### 智能体：`hermes-desktop-plugins` skill

当智能体要编写桌面端插件时，它应当加载捆绑的
**`hermes-desktop-plugins`** skill——它以面向智能体的形式承载了与本页相同的
契约，并附有可直接复制的 `templates/plugin.js`。本页是
面向人类/开发者的参考；那个 skill 则是可操作的检查清单。

## 故障排查

**我的插件没有出现。** 确认文件位于
`$HERMES_HOME/desktop-plugins/<id>/plugin.js`，且文件夹名与导出的
`id` 一致。运行 ⌘K → **Reload desktop plugins**。查看应用中是否有指出失败原因的错误
toast，并跟踪 `hermes logs gui -f`。

**加载时报 “unsupported import”。** 磁盘插件只能 import
`@hermes/plugin-sdk`、`react` 和 `react/jsx-runtime`。请移除任何其他 import。

**某个 `jsx` 元素什么都没渲染 / 抛出 `ReferenceError`。** 某个在
`jsx()` 调用中使用的标识符没有被 import。把它加到 import 行里。

**`ctx.rest` 返回 404。** 后端没有挂载：确认
`~/.hermes/plugins/<id>/dashboard/manifest.json` 中有 `"api": "plugin_api.py"`，
确认该插件位于 `config.yaml` 的 `plugins.enabled` 中，并重启网关
（后端路由在启动时挂载）。跟踪 `~/.hermes/logs/errors.log` 中的
`Failed to load plugin <id> API routes`。

**`ctx.socket` 从不触发。** 在 OAuth 远端上它按设计是空操作——请使用你的
轮询回退。否则请确认后端在其命名空间下暴露了对应的
`@router.websocket(...)` 路由。

**切换主题后颜色不对。** 你硬编码了颜色。请把它换成
`var(--ui-*)` 主题变量。
