---
title: "Hermes Desktop Plugins — Write desktop app plugins that add UI panes and commands"
sidebar_label: "Hermes Desktop Plugins"
description: "编写桌面应用插件，添加 UI 面板与命令"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Hermes Desktop Plugins

编写桌面应用插件，添加 UI 面板与命令。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认已安装） |
| 路径 | `skills/hermes-desktop-plugins` |
| 版本 | `1.0.0` |
| 平台 | linux, macos, windows |
| 标签 | `desktop`, `plugins`, `ui`, `extension` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Hermes Desktop Plugins Skill

为 Hermes 桌面应用编写插件：状态栏项、布局面板、命令面板命令、快捷键、路由和主题。
一个插件就是一个纯 JavaScript 的 ESM 文件，由应用在运行时加载——无需构建步骤，
也不必改动仓库。插件还可以与自己的 Python 后端命名空间通信
（`ctx.rest`/`ctx.socket` → `/api/plugins/<id>`）；通用的 Python 插件体系
（`~/.hermes/plugins/`）另有独立文档。

面向人的完整参考（每个导出、各区域的载荷、后端、安全）：
`website/docs/developer-guide/desktop-plugin-sdk.md`。

## 使用时机

- 用户希望在不修改应用本身的前提下，新增一个桌面 UI 元素（面板、状态栏小组件、
  仪表盘、命令）。
- 你想把自己计算出的数据（通过 gateway RPC）呈现在应用内。

## 前置条件

- Hermes 桌面应用（由它加载插件；仅有 CLI/gateway 是不行的）。
- 对 `$HERMES_HOME/desktop-plugins/`（通常是 `~/.hermes/desktop-plugins/`）
  的写入权限。

## 如何运行

1. 依照 `templates/plugin.js`（相对于此 skill 目录）创建
   `$HERMES_HOME/desktop-plugins/<name>/plugin.js`——默认即 `~/.hermes/...`，
   在具名 profile 下则是 `~/.hermes/profiles/<profile>/...`。保持 `<name>` 与插件
   `id` 一致。
2. 桌面应用会监视该目录：文件落盘后几秒内插件就会加载，之后每次保存都会就地热重载，
   无需重新加载步骤。（若没有出现，兜底做法：⌘K →
   **Reload desktop plugins**。）
3. 如果加载失败，应用会弹出一条注明错误的提示——修好文件再保存即可。

## 快速参考

唯一的导入面是 `@hermes/plugin-sdk`（外加 `react` /
`react/jsx-runtime`，它们会解析到应用自带的 React——请用 `jsx()` 调用来编写 UI，
不要用 JSX 语法；该文件不会被编译）。

- `host.state.*` — 只读的响应式 atom：`activeSessionId`、`cwd`、
  `gateway`、`model`、`profile`、`viewport`。在处理函数中用 `.get()` 读取，
  在组件中用 `useValue(atom)`。
- `host.request(method, params)` — gateway JSON-RPC（会话、配置、
  skill、cron——应用用到的一切）。
- `host.onEvent(type, fn)` — 实时 gateway 事件（`'*'` 表示全部）。返回一个
  取消订阅函数。
- `host.notify({ kind, message })`、`host.navigate(path)`、`host.logs(...)`、
  `host.status()`、`haptic('tap')`。
- `ctx.register({ id, area, order?, render?, data? })` — 贡献 UI。
  主要区域：`'statusBar.right'`/`'statusBar.left'`（chip），
  `'panes'`（布局区域——设置 `title` 和
  `data: { placement, dock?, width?, height? }`；面板会自动加入匹配的
  区域），`PALETTE_AREA`（⌘K 命令），`KEYBINDS_AREA`（可重新绑定的
  操作）。
- 面板放置：`placement: 'left'|'right'|'bottom'|'main'` 表示语义角色——
  面板会与该角色下已有的面板堆叠（形成标签页）。
  若想落到某个具体的**边缘**，请加上 `dock: { pane, pos }`——这与把面板拖到
  某个面板的投放 chip 上是同一个动作。`pane` 可以是任意面板 id
  （`workspace` 是主对话线程面板；还有 `sessions`、`terminal`、`files`、
  `review`、`logs`），`pos` 取 `'top'|'bottom'|'left'|'right'|'center'`。
  例如"在对话下方"就是 `dock: { pane: 'workspace', pos: 'bottom' }`
  ——记得声明 `height`（如 `'200px'`），以免它占掉半个区域。
- 完整**页面**：注册 `area: ROUTES_AREA`，配合 `data: { path: '/my-page' }`
  和一个 `render`——该页面会像任何内置视图一样挂载到 workspace（主）面板。
  再加一行侧边栏导航让它可达：
  `ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/my-page', label: 'My Page', codicon: 'project' } })`
  （渲染在 Artifacts 下方，进入该路由时会高亮）——以及/或者一个调用
  `host.navigate('/my-page')` 的 `PALETTE_AREA` 命令。
- `ctx.storage.get/set/remove` — 以你的插件为命名空间的持久化存储。
- `ctx.i18n.register({ en, ja, ... })` — 发布**你自己的**语言包，作用域限定在
  你的插件内（绝不要修改核心的 `en.ts`）。值可以是字面字符串或插值函数；
  嵌套结构通过点号路径寻址。在组件中用 `usePluginI18n(id)` 响应式读取，
  它返回 `t('key', ...args)`（切换语言时会重新渲染）；在处理函数/store 中
  则使用 `ctx.i18n.t`。解析顺序为应用当前语言、你的 `en`，最后是原始 key。
- 数据：`useQuery`/`useMutation`/`useQueryClient`/`queryClient`（应用**唯一**的
  React Query 客户端——缓存、去重、`refetchInterval`、失效机制都与核心一致；
  绝不要自己手写轮询循环），以及用于插件本地状态的 `atom`/`computed`。
- 后端：如果插件附带 Python 的 `plugin_api.py`（位于
  `~/.hermes/plugins/<id>/dashboard/`，manifest 中写 `"api": "plugin_api.py"`），
  可用 `ctx.rest('/path', { method?, body?, timeoutMs? })` 访问它，其实时孪生接口是
  `ctx.socket('/events', onMessage)`——两者在构造上都被限定在 `/api/plugins/<id>`
  之内（路径穿越会被拒绝）。`ctx.socket` 在 **OAuth 远端上是空操作**，
  因此务必保留一条轮询兜底路径。只有当插件出现在 `config.yaml` 的
  `plugins.enabled` 中时，Python 后端才会被导入（这与应用内的启用开关是两回事）。
  若要获取 gateway 全局数据，请改用 `host.request` / `host.onEvent`。
- `Contribute`（作用域绑定挂载）：在组件内渲染
  `jsx(Contribute, { area, id, children })`，这样页面自有的外壳元素
  （例如 `TITLEBAR_AREAS.center` 中的标题栏控件）会在页面卸载时一并消失——
  `ctx.register` 用于永久性的贡献。
- 在默认导出上设置 `defaultEnabled: false` 可发布一个需用户主动开启的插件：
  它会出现在 设置 → 插件 的清单中，在用户打开之前保持关闭。
- 用户在 设置 → 插件 中管理插件（实时启用/停用、打开所在文件夹）。被停用的插件
  在重启后仍保持停用——不要跟它较劲；是用户把你关掉的。
- UI：应用的设计语言，可直接导入——`Button`、`Input`、
  `Textarea`、`Select*`、`Switch`、`Checkbox`、`SegmentedControl`、`Tabs*`、
  `Dialog*`、`ConfirmDialog`、`DropdownMenu*`、`ContextMenu*`、`Popover*`、
  `Tip`/`Tooltip*`、`Badge`、`Kbd`/`KbdGroup`、`SearchField`、`ScrollArea`、
  `Separator`、`Skeleton`、`GlyphSpinner`、`EmptyState`、`ErrorState`、
  `CopyButton`、`StatusDot`、`LogView`、`Codicon`、`DecodeText`，以及 `cn`
  和 `icons.*`。优先使用它们而不是自己手写元素，这样插件看起来才原生；
  样式请使用主题变量，绝不要硬编码颜色。

## 步骤

1. 选一个简短的 kebab-case `id`；文件夹名必须与之一致。
2. 从 `templates/plugin.js` 开始；保持默认导出的形状
   （`{ id, name, register(ctx) }`）。
3. 若要做面板，注册 `area: 'panes'`，给出 `placement` 提示和一个返回你的组件的
   `render`——应用会自动把它放进合适的区域；之后用户可以随意拖动。
4. 用 `host.request` 获取数据，并/或用 `host.onEvent` 订阅；
   轮询频率绝不要快于几秒一次。
5. 用你的文件工具写入该文件，然后请用户从 ⌘K 运行
   **Reload desktop plugins**。

## 常见陷阱

- 绝不要硬编码颜色或背景（`#000`、`black`、`rgb(...)`）。面板本身就位于应用的
  编辑器背景之上——不要动背景，其他一切都使用主题变量：
  `var(--ui-text-secondary)`、`var(--ui-text-quaternary)`、
  `var(--ui-stroke-secondary)`、`var(--ui-accent)`。绘制 canvas 时，用
  `getComputedStyle(canvas).getPropertyValue('--ui-accent')` 一次性解析它们。
- 只引用你导入过的东西——忘记导入的组件
  （例如 `StatusDot`）会在渲染时抛出 ReferenceError。请逐一核对你 `jsx()`
  调用中的每个标识符都出现在 import 那一行里。
- Canvas 面板**必须**用 `ResizeObserver` 跟踪其容器并重新设置 canvas 尺寸
  （要设置 width/height 属性，而不只是 CSS）——面板会频繁改变大小
  （拖动分隔条、切换布局）；只在挂载时设一次尺寸会留下空白或产生模糊缩放。
- JSX 语法无法解析——该文件是未经编译加载的。请使用
  `react/jsx-runtime` 中的 `jsx('div', { children: ... })`。
- 除了 `@hermes/plugin-sdk`、`react` 和 `react/jsx-runtime`，不要导入任何
  其他东西；其他说明符无法解析。
- 处理函数必须以命令式方式读取状态（`$atom.get()`），绝不要从渲染闭包中读取——
  否则高频事件会读到陈旧的值。
- 保持组件小巧；只在真正渲染该值的叶子组件中订阅（`useValue`）。

## 验证

- 执行 **Reload desktop plugins** 后，插件的 UI 出现了。
- 没有出现错误提示（"Plugin &lt;name> failed to load"）；如果出现了，提示信息会指出
  失败原因——修好后重新加载。
- 对于面板：新的区域可见，并且能像任何核心面板一样拖动。
