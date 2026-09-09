---
sidebar_position: 11
title: "宠物（Petdex 吉祥物）"
description: "领养一只会随智能体活动而做出反应的动画吉祥物，横跨 CLI、TUI 与桌面端应用"
---

# 宠物

Hermes 可以显示一只动画**宠物**——一个小小的吉祥物精灵，它会随着智能体
正在做的事情（空闲、执行工具、思考、完成、失败）在 **CLI**、**TUI** 和
**桌面端应用**中做出反应。宠物来自公开的
[petdex](https://github.com/crafter-station/petdex) 图鉴。

宠物纯属装饰。它们对**提示词缓存、token 或智能体行为没有任何影响**——
精灵只是一个显示层的事情。该功能**默认关闭**，在你安装并选中一只宠物
之前一直处于休眠状态。

## 工作原理

- 宠物会被安装到你所在配置档的 `pets/` 目录
  （`<HERMES_HOME>/pets/<slug>/`），因此每个[配置档](../profiles.md)都保有
  自己的一套。
- 选中一只宠物会把 `display.pet.slug` 和 `display.pet.enabled` 写入
  `config.yaml`——不会有任何内容被当作密钥或环境变量存储。
- 每个界面都会观察它本就在跟踪的活动，并将其映射为六种动画状态之一。
  该映射只存在于一处，因此所有界面的行为完全一致：

  | 智能体活动 | 宠物状态 |
  | --- | --- |
  | 某次工具调用/轮次刚刚失败 | `failed` |
  | 一个计划已完成（所有待办事项都已完成） | `jump`（庆祝） |
  | 一轮干净地结束 | `wave` |
  | 某个工具正在执行 | `run` |
  | 模型正在思考/阅读 | `review` |
  | 轮次进行中（未细分） | `run` |
  | 正等待你（有澄清/审批提示处于打开状态） | `waiting`（在旧版 8 行精灵表上回退为 `idle`） |
  | 什么都没发生 | `idle` |

## 渲染

在终端中（CLI/TUI），当你的终端支持某种图形协议（**kitty**、**Ghostty**、
**WezTerm**、**iTerm2** 或 **sixel**）时，Hermes 会以完整保真度渲染精灵。
否则它会自动回退到真彩色 Unicode **半块字符**渲染。在管道或重定向中
（没有 TTY）时，终端渲染按设计被禁用。

桌面端应用会把宠物绘制成画布上的一个浮动精灵，并可在
**设置 → 外观**中开关。

## 快速开始（CLI）

```bash
# 浏览图鉴（按子串过滤）
hermes pets list
hermes pets list cat

# 安装一只宠物并一步将其设为当前生效
hermes pets install boba --select

# 在终端中预览/播放动画（Ctrl+C 停止）
hermes pets show

# 检查你的配置
hermes pets doctor
```

## `hermes pets` 命令

| 目标 | 命令 |
| --- | --- |
| 浏览图鉴 | `hermes pets list [query] [--limit N]` |
| 列出已安装的宠物 | `hermes pets list --installed` |
| 安装一只宠物 | `hermes pets install <slug> [--select] [--force]` |
| 设置当前生效的宠物 | `hermes pets select [slug]`（省略 slug 会打开选择器） |
| 在所有界面调整宠物大小 | `hermes pets scale <factor>`（例如 `0.5`，限制在 0.1–3.0） |
| 预览/播放动画 | `hermes pets show [slug] [--state <s>] [--cycle] [--once] [--mode <m>] [--scale <f>]` |
| 禁用宠物 | `hermes pets off` |
| 移除已安装的宠物 | `hermes pets remove <slug>` |
| 诊断配置 | `hermes pets doctor` |

`hermes pets show` 的参数：

- `--state` —— 播放单个状态（`idle`、`wave`、`run`、`failed`、`review`、
  `jump`）。
- `--cycle` —— 依次循环播放每个状态。
- `--once` —— 只播放一次而不循环。
- `--mode` —— 覆盖渲染协议（`kitty`、`iterm`、`sixel`、
  `unicode`、`auto`）。
- `--scale` —— 覆盖屏幕上的缩放比例（`0` = 使用配置值）。

## `/pet` 斜杠命令

在 CLI 和 TUI 中，你无需离开会话即可管理宠物：

- `/pet` —— 开关宠物（若当前没有生效的宠物，则领养第一只已安装的
  宠物）。
- `/pet list` —— 浏览图鉴。
- `/pet scale <factor>` —— 在所有界面调整宠物大小（例如 `/pet scale 0.5`）。
- `/pet <slug>` —— 领养指定的宠物。
- `/pet off` —— 禁用宠物。

在 TUI 中，`/pet list` 会打开一个交互式选择器浮层；在桌面端应用中
它会打开 Cmd+K 宠物面板。

## 生成一只宠物（`/hatch`）

除了从图鉴安装现成的宠物之外，Hermes 还能根据一段文字描述
**生成一只全新的宠物**——这是它自己的 AI 精灵生成流水线。

- CLI/TUI：`/hatch <description>`（别名 `/generate-pet`），或 `hermes pets` → 生成流程。
- 桌面端应用：宝可梦图鉴风格的**生成**界面——包含动画蛋、孵化特效和草稿选择器。

生成是如何工作的（一个分两步、成本可控的流程）：

1. **基础草稿** —— 先生成少量廉价的、纯提示词驱动的“这只宠物应该长什么样”的变体。你可以挑一个，也可以重混/重试换一批。
2. **孵化** —— 选中的基础图会被用作参考图像，为每个 Hermes 状态（空闲、思考、使用工具等）生成一行有依据的动画，随后被确定性地切分为帧，并打包成标准的 petdex/Codex 图集（8×9 网格，每格 192×208）。结果是一张你可以保留的合法精灵表——并且可以 `petdex submit`。

### 图像后端

生成会使用当前生效的[文生图提供商](/user-guide/features/image-generation)，但它需要**参考图像作为依据**，以保证每一行动画都还是与基础图相同的角色。支持参考图的后端有：**Nous Portal**、**OpenRouter**、**OpenAI**（`gpt-image-2`）和 **Krea**。OpenRouter/Nous 默认会走一条质量优先的模型链。

- 解析顺序优先 Nous Portal → OpenAI → OpenRouter。
- 如果没有配置任何支持参考图的后端，生成会抛出一个可操作的错误，指引你前往 `hermes tools` → Image Generation。（安装/领养图鉴中已有的宠物不需要任何图像后端。）
- 可用环境变量 `HERMES_PET_IMAGE_PROVIDER` 覆盖后端（例如 `HERMES_PET_IMAGE_PROVIDER=openrouter`）。

## 桌面端应用

在桌面端应用中你可以通过两种方式管理宠物：

- **Cmd+K → “Pets…”** —— 无需离开键盘即可浏览、搜索、领养和开关宠物
  （与主题选择器一致）。
- **设置 → 外观** —— 同样的图鉴，外加一个**大小滑块**，
  拖动时会实时调整浮动吉祥物的尺寸。

两者都会就地领养/开关/调整浮动吉祥物——尺寸变更立即生效；
领养一只新宠物会在片刻之内让它亮相。

### 弹出浮层

**Shift + 点击**浮动宠物，可把它弹出为一个独立的、透明的、
始终置顶的桌面窗口。在外面时，即使 Hermes 已最小化它也保持可见
（Codex 风格），一眼就能看出智能体在做什么。

弹出之后可用的手势：

| 手势 | 动作 |
| --- | --- |
| **拖动** | 把宠物移到屏幕上任意位置，甚至可以移出应用之外。它的位置和内/外状态会在重启后保留。 |
| **单击** | 打开一个迷你输入框，向最近的会话发送提示词——无需唤起应用。 |
| **双击** | 切换应用窗口：如果它在前台就最小化，如果它被隐藏就恢复。 |
| **Shift + 点击** | 把宠物收回窗口内。 |
| **邮件图标** | 只有当你离开期间某一轮结束时才会出现；点击可在最近的对话上唤起应用（并将其标为已读）。 |

只有弹出后的宠物才会显示**对话气泡**（`working…`、`thinking…`、
`your turn`……）——在窗口内时应用本身就是那个界面，所以宠物在那里
保持安静。

该浮层完全是应用内宠物的傀儡——它不携带独立的网关连接，
也永远不会出现在 dock 或应用切换器中。

## 配置

所有设置都位于 `config.yaml` 的 `display.pet` 之下：

```yaml
display:
  pet:
    enabled: false        # 总开关（选中一只宠物后为 true）
    slug: ""              # 当前生效的宠物；留空 = 第一只已安装的
    render_mode: auto      # auto | kitty | iterm | sixel | unicode | off
    scale: 0.33           # 总体尺寸旋钮（相对于 192x208 的原生帧）
    unicode_cols: 0       # 硬性覆盖终端宽度（0 = 由 scale 推导）
```

- **`scale`** 是唯一的总体尺寸旋钮。一个数字就能缩小所有界面：
  桌面画布按它缩放像素，CLI/TUI 则据此推导终端列宽。半块字符回退
  会被限制在一个可读性下限——它无法像真像素的 kitty/GUI 渲染那样
  缩得很小而不糊成一团，所以同一个 `scale` 在 kitty 下清晰锐利，
  在半块字符下则会被下限截住。
- **`render_mode: auto`** 会检测 kitty/iTerm2/sixel，并回退到 unicode
  半块字符。显式设置它可强制某个协议，或设为 `off` 以禁用终端渲染
  但仍在桌面端保留宠物。
- **`unicode_cols`** 可独立于 `scale` 固定终端列宽；
  保持为 `0` 则由 `scale` 推导宽度。

## 故障排查

运行 `hermes pets doctor` —— 它会报告：

- 宠物目录以及已安装了哪些宠物，
- `display.pet.enabled`、`display.pet.slug` 以及解析出的当前生效宠物，
- 配置的 `render_mode`、检测到的终端图形协议，以及
  TTY 下的实际生效模式，
- Pillow（用于精灵解码）是否可导入。

当宠物已安装、已选中、已启用且 Pillow 可用时，它会打印 `✓ ready`。

常见坑：

- 只有当一只宠物**已安装且已选中**（`enabled: true`）时才会显示。
- 在管道/重定向中（没有 TTY）时，终端渲染按设计被禁用。
- petdex 的 npm CLI 会安装到 `~/.codex/pets`；Hermes 使用的是它自己的
  按配置档隔离的 `<HERMES_HOME>/pets/`——请通过 `hermes pets` 安装。

## 另请参阅

- [`petdex` skill](../skills/bundled/productivity/productivity-petdex.md)
  可让智能体按你的要求替你安装和切换宠物。
