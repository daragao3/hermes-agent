---
title: "Tldraw Offline — 用 agent 驱动并编写 tldraw offline 画布脚本"
sidebar_label: "Tldraw Offline"
description: "用 agent 驱动并编写 tldraw offline 画布脚本"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Tldraw Offline

用 agent 驱动并编写 tldraw offline 画布脚本。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选——通过 `hermes skills install official/creative/tldraw-offline` 安装 |
| 路径 | `optional-skills/creative/tldraw-offline` |
| 版本 | `1.0.0` |
| 作者 | Teknium + Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `tldraw`, `canvas`, `whiteboard`, `document-script`, `diagramming` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# tldraw offline Skill

使用 tldraw offline 桌面应用（offline.tldraw.com）：读取当前打开的画布、进行编辑，并编写**文档脚本（document script）**——嵌入在 `.tldraw` 文件中的 JavaScript，会在加载时运行，为文件赋予持久化的行为。该应用运行一个**本地 HTTP API**（默认 `localhost:7236`），编程 agent 在终端中用普通的 `curl` 即可驱动它——这正是该应用主页演示（Codex 实时编辑画布）的工作方式。agent **不**使用 computer-use / GUI 点击，也**不**直接手工编辑 `.tldraw` 文件。工作期间请保持 tldraw offline 处于打开状态。

## 使用场景 {#when-to-use}

- 用户已打开 tldraw offline，并要求你构建或修改画布（图表、线框图、布局）。
- 你想通过嵌入的文档脚本为绘图添加持久化行为（响应式形状、可交互按钮、动画、连接逻辑）。

**不要**手工摆放形状来模仿一幅绘图——而是编写生成这些形状的代码。agent 编写画布脚本的能力远胜于在画布上作画。

## 前置条件 {#prerequisites}

- **已安装并运行 tldraw offline**，且打开了一个文档。发行版：
  https://github.com/tldraw/tldraw-offline/releases/latest（macOS DMG、Windows
  x64/Arm64、Linux `x86_64`/`arm64` AppImage 或 amd64/arm64 `.deb`）。
- **在应用中安装 agent skill**：`Develop → Install Agent Skills`。应用会将自己的 tldraw skill 写入 `~/.codex/skills/`、`~/.claude/skills/`、`~/.cursor/skills/` 和 `~/.gemini/skills/`——教会相应 agent 使用下文的 `curl` 用法。（本 Hermes skill 为 Hermes 复刻了这份指引。）
- **本地控制 API。** 启动时，应用会将 `server.json` 写入其配置目录（Linux `~/.config/tldraw/`，macOS `~/Library/Application Support/tldraw/`，Windows `%APPDATA%\tldraw\`），其中包含 `port`（默认 `7236`）、一个 bearer `token`、`pid` 和 `startedAt`。除 `GET /` 外的每个请求都需要 `Authorization: Bearer <token>`。正常退出会删除 `server.json`；如果该文件存在但端口无响应，说明应用是非正常退出的——应视为未运行。
- **每次 shell 调用都要重新读取 port 和 token。** 每次终端调用都是一个全新的 shell，因此 `export` 出去的 token 不会保留——"export 一次反复使用"会发送空 token 并得到 401。请在每次调用的开头内联读取二者：
  `PORT=$(jq -r .port <server.json>); TOKEN=$(jq -r .token <server.json>)`。
- 本地编辑无需账号，也无需联网。

## 运行方式 {#how-to-run}

有两种不同的工作流。根据改动是否需要在重新加载后保留来选择。

**A. 一次性画布编辑（`/exec`）**——布局、生成形状、清理。这是实时编辑，不是保存下来的脚本：

```bash
BASE=http://localhost:7236
TOKEN=$(python -c "import json;print(json.load(open('$HOME/.config/tldraw/server.json'))['token'])")
# find the focused document id
DOC=$(curl -s "$BASE/api/search" -X POST -H 'content-type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"code":"return (await api.getFocusedDoc()).id"}' | python -c "import sys,json;print(json.load(sys.stdin)['result'])")
# run code with the live `editor` + `helpers` in scope
curl -s "$BASE/api/doc/$DOC/exec" -X POST -H 'content-type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"code":"const {createShapeId,toRichText}=await import(\"tldraw\"); editor.createShape({id:createShapeId(),type:\"geo\",x:0,y:0,props:{geo:\"rectangle\",w:200,h:100,color:\"blue\",fill:\"solid\",richText:toRichText(\"hello\")}}); return editor.getCurrentPageShapes().length"}'
```

**B. 持久化行为（`script/main.js`）**——必须在重新加载后保留的响应式/交互逻辑。编辑磁盘上的文件；应用的文件监视器会应用它：

```bash
# get the live script file path for the doc
curl -s "$BASE/api/doc/$DOC/script-workspace" -X POST \
  -H "Authorization: Bearer $TOKEN"          # -> result.mainJsPath, result.isDefaultScript
# edit result.mainJsPath with read_file / patch / write_file (see scripts/main.js)
# then confirm the watcher applied it:
curl -s "$BASE/api/doc/$DOC/script-status" -H "Authorization: Bearer $TOKEN"
```

可直接改编使用的文档脚本是 `scripts/main.js`。

## 快速参考 {#quick-reference}

文档脚本约定（已对照应用自带的 `script-context.d.ts` 验证）：

```js
import { createShapeId, toRichText } from 'tldraw'   // primitives: import, not globals

export default function ({ editor, helpers, signal }) {
  editor.run(() => {                                 // batch = one undo step
    helpers.createShapeIfMissing({                   // idempotent furniture
      id: createShapeId('node-1'), type: 'geo', x: 0, y: 0,
      props: { geo: 'rectangle', w: 200, h: 100, richText: toRichText('hi') },
    })
  })

  const stop = editor.store.listen(() => { /* react */ })  // fires the tick AFTER a commit
  signal.addEventListener('abort', () => stop())           // REQUIRED cleanup on rerun/close
}
```

- `ctx.editor`——实时的 `Editor`（`createShape`、`updateShape`、`deleteShapes`、
  `getCurrentPageShapes`、`getShape`、`getBindingsFromShape`、`zoomToFit`、
  `on('tick'|'event', fn)`、`run(fn, { history: 'ignore' })`）。
- `ctx.helpers`——`createShapeIfMissing`、`createShapesIfMissing`、
  `createArrowBetweenShapes(from, to, { arrowheadEnd })`、`translateShapes`、
  `onShapeTranslate(id, fn, { signal })`、`richTextToPlainText`、`boxShapes`、
  `getLints`。
- `ctx.signal`——`AbortSignal`；把每个监听器/定时器的清理都挂到它上面。
- `config.js`（单独的文件）注册自定义的 shape/tool/component util，并在挂载前运行；`main.js` 针对已挂载的编辑器运行，并在保存时重新运行。

## 交互式 UI（驱动状态的可点击按钮） {#interactive-ui-clickable-buttons-that-drive-state}

绘制出的形状可以表现得像真正的应用——这是静态白板做不到的。完整示例：`scripts/counter.js`（一个数字显示 + MINUS/RESET/PLUS 按钮）。

验证边界——在声称交互可用或不可用之前请先读这一段。应用**自己的** agent 操作手册要求通过 `/exec` 以"一次模拟点击加一次状态读取"来验证可点击 UI 脚本（`editor.dispatch` 一个指针事件，等待一个 tick，读取形状的状态）——**而不是**驱动真实鼠标。按这个标准，计数器已通过验证：派发的点击使其依次变为
`0 → 1 → 2 → 1 → 0`。有两点值得记录：
- **脚本只有在应用的文件监视器应用它之后才会运行。** 在 Linux 上该监视器使用 inotify；若主机的 `fs.inotify.max_user_instances` 已耗尽，会记录 `inotify_add_watch ... No space left on device`，`script-status` 显示 `state: "not-watching"` / `hasEntry: false`，脚本永远不会执行。这是主机限制，不是脚本 bug——正常桌面环境不受影响。
- **用 computer-use 驱动画布需要前台（FOREGROUND）投递，而不是后台。** cua-driver 默认的 `background` 投递面对 Electron 被遮挡的渲染器会返回 `background_unavailable`——但这只是第一级，并非死路。cua-driver 会返回一个 `escalation: "foreground"` 提示；设置 `delivery_mode: "foreground"`（配合 `bring_to_front`），其 X11 XTest 路径（`x11_xtest_fg`）的点击就能生效——可以关闭 "Run Script" 授权对话框并点击画布。已由 Cua 团队在这个 v1.11.0 AppImage（Linux/X11）上验证。**不要**在后台模式下得出"Electron 拒绝合成点击"的结论就放弃——升级到前台模式。（真正的产品路径仍然是 `/exec`，而不是点击；本说明仅针对由 computer-use 驱动的测试。）

模式如下：

```js
export default function ({ editor, helpers, signal }) {
  // 1. Build buttons idempotently; tag each with meta so the handler finds them.
  //    Give buttons a visible label AND a meta.action.
  // 2. Hit-test pointer_down in PAGE coordinates against the button bounds:
  const inside = (b, p) => p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h
  function onEvent(info) {
    if (!info || info.name !== 'pointer_down') return
    let p = null
    try { if (info.point && editor.screenToPage) p = editor.screenToPage(info.point) } catch {}
    p = p ?? editor.inputs?.currentPagePoint
    if (!p) return
    const hit = editor.getCurrentPageShapes().find(
      (s) => s.meta?.ui === 'button' &&
        inside({ x: s.x, y: s.y, w: s.props.w, h: s.props.h }, p)
    )
    if (hit) runAction(hit.meta.action)   // mutate state; store it in a shape's meta
  }
  editor.on('event', onEvent)
  signal.addEventListener('abort', () => editor.off('event', onEvent))  // REQUIRED
}
```

- 通过 `meta`（或通过 `helpers.richTextToPlainText` 读取的可见标签）查找按钮，而不是靠硬编码坐标。
- **构建和读取由同一个脚本负责。** 如果形状由一条代码路径创建（带 `meta.action: 'inc'`），而处理函数读取的是另一种约定（`meta.action === 'PLUS'`），点击就会静默无效。要么让处理按钮的同一个脚本来构建按钮，要么交付一个空画布让脚本重新构建它们——绝不要把约定不匹配的形状预先烘焙进文件的 db。
- 把应用状态保存在某个形状的 `meta` 中（例如 `meta.count`），并将其渲染为该形状的 `richText` 标签，这样它能在保存后保留，也便于验证时读取。
- **在 `signal` abort 时解除监听器。** 省略这一步不只是影响美观：下次保存时，旧的 `onEvent` 会与新的一起保持挂载，于是每次点击都会触发两次，计数器每次跳 2 而不是 1。
- 连续运动使用 `editor.on('tick', fn)`；对于带有附属部件的移动锚点，使用 `helpers.onShapeTranslate(id, fn, { signal })`。

### 交付可自动运行脚本的 `.tldraw` {#shipping-a-self-running-scripted-tldraw}

`.tldraw` 是一个包含 `metadata.json` + `session.json` + `db.sqlite` + `assets/`
+ `script/` 的 zip（只有这些条目可以打包）。要让脚本自动运行、而不弹出 "This document contains a script → Run Script" 授权对话框：

- `metadata.json` 必须带有一个 `script` 清单：`{ "sha256": "<digest>" }`，其中该摘要是对每个排序后的 `script/` 路径按 `` `${path}\0${sha256hex(bytes)}\n` `` 拼接后计算的 `sha256`。不匹配会被视为遭到篡改而被拒绝。
- 通过将该摘要加入 `~/.tldraw/script-trust.json`（`{ "trusted": ["<digest>"] }`，或 `$TLDRAW_SCRIPT_TRUST`）来预先信任它。当 `isScriptTrusted(digest)` 为 true 时，应用会跳过授权确认。

## 操作步骤 {#procedure}

1. 从 `server.json` 读取当前的 token/port。用 `api.getFocusedDoc()`（或 `api.getDocs()`）找到目标文档；如果打开了多个文档，请明确指定其名称。
2. 布局/生成使用 `/exec`。持久化行为则通过 `/script-workspace` 编辑
   `script/main.js`。
3. 让脚本保持幂等：用 `helpers.createShapeIfMissing` 和稳定的 `createShapeId('name')` id 创建持久形状。脚本在每次加载时都会重新运行。
4. 让脚本自身的写入不进入用户的撤销栈：
   `editor.run(fn, { history: 'ignore' })`（或使用 `helpers.translateShapes`，它已经这样做了）。
5. 响应式逻辑使用 `editor.store.listen(cb)`，并在 `signal` abort 时拆除。交互使用 `editor.on('event', h)`（在页面坐标中对 `pointer_down` 做命中测试）；动画使用 `editor.on('tick', h)`。
6. 对于单个移动锚点 + 附属内部部件，优先使用
   `helpers.onShapeTranslate(anchorId, fn, { signal })`，而不是宽泛的 store 监听器——宽泛的监听器可能把你自己的写入变成反馈循环。

## 形状 props（已对照 tldraw SDK v5 schema 验证） {#shape-props-validated-against-tldraw-sdk-v5-schema}

`editor.createShape` / `createShapeIfMissing` 接受部分 props（shape util 会填充默认值）。为文件快照构建**原始记录（raw record）**时，下列每个 prop 都是必需的（运行 `scripts/validate_shapes.mjs`）：

| 形状 | 必需 props |
|-------|----------------|
| `note`  | `richText`, `color`, `labelColor`, `size`, `font`, `align`, `verticalAlign`, `growY`, `fontSizeAdjustment`, `url`, `scale`, `textLastEditedBy` |
| `text`  | `richText`, `color`, `size`, `font`, `textAlign`, `w`, `scale`, `autoSize` |
| `frame` | `w`, `h`, `name`, `color` |
| `geo`   | `geo`, `w`, `h`, `color`, `fill`, `richText`（+ dash/size 等取默认值） |

`richText` 必须是 `toRichText('...')`——纯字符串会被拒绝。`color` 枚举：
`black grey light-violet violet blue light-blue yellow orange green light-green
light-red red white`。`font` 枚举：`draw sans serif mono`。

## 常见陷阱 {#pitfalls}

- **`store.listen` 在提交之后的下一个 tick 触发，而不是同步触发。** 如果你写入一个形状后立即读取状态、并期望监听器已经运行，它其实还没运行。实测验证：同一轮内读取显示触发 0 次；经过一个 `setTimeout` tick 后显示 1 次。这也是应用注明 `editor.dispatch` 为异步的原因——验证前先等待一个 tick。
- **用 `ctx`，而不是全局变量。** 入口是 `export default function ({ editor,
  helpers, signal })`。文档脚本中没有裸露的 `editor` 全局变量。
  `createShapeId` / `toRichText` / `Vec` 来自 `import ... from 'tldraw'`。
- **用 `richText`，而不是 `text`。** text/note/geo 的标签使用 `richText: toRichText(s)`。
- **原始记录需要全部 props；`createShape` 不需要。** 在应用内只传你关心的 props；手工构建的 `.tldraw` 快照则需要完整集合（见上表）。
- **脚本在每次加载时重新运行——要保持幂等。** 使用带稳定 id 的 `createShapeIfMissing`，否则会重复内容并覆盖用户的编辑。
- **在 `signal` 上清理。** 对每个 `store.listen` / `editor.on` / `setInterval` 都要 `signal.addEventListener('abort', () => stop())`；该 signal 会在重新运行前和关闭时触发。
- **让脚本写入不进入撤销栈：**`editor.run(fn, { history: 'ignore' })`。
- **窗口隐藏时 `editor.on('tick')` 会暂停**（它是一个 RAF 循环）；
  `setInterval` 会继续触发，但 Electron 在后台会将其节流到约每秒 1 次。
- **API 需要来自 `server.json` 的 bearer token**；端口可能不是默认值（`server.listen(0)` 会自选一个）——始终读取该文件，不要硬编码 `7236`。
- **只能 import `tldraw` / `react` / `react-dom`**——这不是一个 Node 项目。

## 验证 {#verification}

- **形状 schema（离线，无需应用）：**`node scripts/validate_shapes.mjs`——构建真实的 tldraw schema 并验证 note/text/frame。通过时输出 `3/3`。
- **实时画布编辑：**在 `/exec` 之后，用 `/api/search` →
  `api.getShapes(docId)`（返回 `{ page, viewport, shapes }`）和
  `api.getBindings(docId)`（数组）读回结果。确认预期的形状/绑定存在。获取
  `api.getScreenshot(docId)`（返回 `{ filePath, ... }`），并用 `vision_analyze` 检查该 PNG/JPEG。
- **持久化脚本已应用：**`GET /api/doc/:id/script-status`。成功即
  `state: "applied"`（`currentDiskDigest === lastAppliedDigest === manifestSha256`、
  `pendingApply === false`、`lastApplyError === null`）。如果短暂重试后仍停留在 `"pending"`，请如实报告，而不要声称成功；`"error"` 表示应用失败——请阅读 `errorLogPath`。
