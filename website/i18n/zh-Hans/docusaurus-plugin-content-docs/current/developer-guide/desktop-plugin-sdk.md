---
sidebar_label: "Desktop Plugin SDK"
title: "桌面端插件 SDK（@hermes/plugin-sdk）"
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
  atom）：当前会话、cwd、网关状态、模型、配置档、视口。
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
| **打包内置** | `apps/desktop/src/plugins/<id>/plugin.tsx` | 仓库内，随应用一同发布 | 应用自身的 Vite 构建 |

两者遵循相同的 `HermesPlugin` 契约，都会出现在**设置 → 插件**中，
并可实时启用/禁用。本页所有内容都是针对磁盘通道来写的
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

### 输入框扩展

`COMPOSER_AREAS`（`top`、`bottom`、`leading`、`actions`、`attachments`、
`middleware`）允许插件在消息输入框周围添加控件、提供
附件来源，或在草稿被发送前对其进行变换（`ComposerMiddleware`，
带有 `handler(draft) => draft | null`）。

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
host.state.cwd              // ReadableAtom<string>
host.state.gateway          // ReadableAtom<string>  （'idle' | 'connecting' | 'open' | …）
host.state.model            // ReadableAtom<string>
host.state.profile          // ReadableAtom<string>
host.state.viewport         // ReadableAtom<{ width, height, narrow }>

host.notify({ kind, message, title?, detail?, action? })  // toast；返回 id
host.notifyError(error, fallbackMessage)                   // 以 toast 形式提示错误
host.navigate('/route')                    // hash 路由导航
host.onEvent(type, fn)                     // 网关事件流（'*' = 全部）；返回销毁函数
host.logs(...)                             // 跟踪某个应用日志文件
host.status()                              // 一次性的系统状态快照
host.restartGateway()                      // 重启后端网关
host.request<T>(method, params?)           // 网关 JSON-RPC —— 真正的威力所在
```

`host.request` 就是应用自己使用的那套 JSON-RPC（会话、配置、skills、
cron、kanban 等）。`host.onEvent` 会流式推送实时网关事件（消息增量、
会话生命周期、工具活动）。监听器之间彼此隔离——你的监听器中抛出的异常
不会影响应用的事件派发。每一个 `host` 通道都是异步安全的：内部辅助函数
抛出的同步异常（例如在普通浏览器中没有桌面端桥接）会变成你的 `.catch()`
能捕获的 rejection，而绝不会是导致错误边界崩溃的异常。

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
| 插件契约 | `HermesPlugin`、`PluginContext`、`PluginContribution`、`PluginStorage`、`PluginRestOptions`、`Contribution` |
| 区域常量 | `PANES_AREA`、`ROUTES_AREA`、`SIDEBAR_NAV_AREA`、`STATUSBAR_AREAS`、`TITLEBAR_AREAS`、`PALETTE_AREA`、`KEYBINDS_AREA`、`THEMES_AREA`、`COMPOSER_AREAS` |
| 区域载荷 | `RouteContribution`、`SidebarNavContribution`、`StatusbarItem`、`TitlebarTool`、`PaletteContribution`、`KeybindContribution`、`ComposerMiddleware`、`ComposerAttachmentProvider` |
| React / 状态 | `useValue`、`atom`、`computed`、`useQuery`、`useMutation`、`useQueryClient`、`queryClient`、`Contribute` |
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
