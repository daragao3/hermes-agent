---
title: 电脑操控
sidebar_position: 16
---

# 电脑操控

Hermes Agent 可以在 **macOS、Windows 和 Linux** 上以**后台**方式驱动你的桌面——点击、输入、滚动、拖拽。你的光标不会移动，键盘焦点不会改变，虚拟桌面 / Spaces 也不会被切换。你和 Agent 可以在同一台机器上协同工作。

与大多数电脑操控集成不同，这适用于**任何支持工具调用的模型**——Claude、GPT、Gemini，或本地 OpenAI 兼容端点上的开源模型。无需关心 Anthropic 原生 schema。

## 工作原理

`computer_use` 工具集通过 stdio 以 MCP 协议与 [`cua-driver`](https://github.com/trycua/cua) 通信，后者是一个开源的后台电脑操控驱动。每个平台在底层使用相应的无障碍 + 输入栈：

| 平台 | 无障碍树 | 输入投递 |
|---|---|---|
| macOS | AX（私有 SkyLight SPI） | `SLPSPostEventRecordTo` —— 按 pid 定向，不会造成光标跳转 |
| Windows | UIAutomation | `SendInput` + `PostMessage` —— 不抢占焦点 |
| Linux | AT-SPI（X11 + Wayland） | XTest（X11）/ virtual-keyboard（Wayland） |

在每个平台上的结果都是一样的：Agent 可以读取任何可见窗口的无障碍树，并投递合成事件，而无需将其提升到前台、切换虚拟桌面或移动真实的操作系统光标。

关于底层契约——*为什么*后台模式很重要、无前台不变式、点击投递的内部机制——请参阅
**[cua.ai/docs/explanation/the-no-foreground-contract](https://cua.ai/docs/explanation/the-no-foreground-contract)**。

## 启用

选择最方便的方式——两种方式运行的是同一个上游安装程序：

**方式一：使用专用 CLI 命令（最直接）。**

```
hermes computer-use install
```

此命令会获取并运行上游 cua-driver 安装程序——在 macOS/Linux 上是 `install.sh`，在 Windows 上是 `install.ps1`。使用 `hermes computer-use status` 验证安装结果。

**方式二：通过交互式界面启用工具集。**

1. 运行 `hermes tools`，选择 `🖱️  Computer Use (macOS/Windows/Linux)`。
2. 安装流程将运行上游安装程序（与方式一相同）。

安装完成后，无论采用哪种方式，都需要授予平台对应的前置条件：

| 平台 | 前置条件 |
|---|---|
| **macOS** | 系统设置 → 隐私与安全性 → **辅助功能** + **屏幕录制** → 允许你的终端（或 Hermes 应用）。`hermes computer-use doctor` 会告诉你缺少哪项权限。 |
| **Windows** | 安装时无需任何前置条件。如果你通过 SSH（而非 RDP / 控制台）驱动，则需要 autostart 模式——Session 0 ↔ Session 1+ 代理方案参见 [cua.ai/docs/how-to-guides/driver/windows-ssh](https://cua.ai/docs/how-to-guides/driver/windows-ssh)。 |
| **Linux** | 一个可达的显示服务器：X11 需设置 `DISPLAY`，或设置 `XDG_SESSION_TYPE=wayland`。Wayland 会话需要 XWayland 桥接才能截图。AT-SPI 必须开启（GNOME/KDE/Xfce 默认开启）。 |

然后启动启用了该工具集的会话：

```
hermes -t computer_use chat
```

或在 `~/.hermes/config.yaml` 中将 `computer_use` 添加到已启用的工具集列表。

## `hermes computer-use doctor` —— 排查的第一站

`hermes computer-use doctor` 会运行 cua-driver 的结构化 `health_report` MCP 工具，并打印逐项检查矩阵。这是查明某个操作*为什么*不生效的最快途径。

```
$ hermes computer-use doctor
⚠️  cua-driver 0.5.8 on darwin — degraded
  ✅ binary_version: cua-driver 0.5.8
  ✅ platform_supported: macOS 26.4.1 (arm64)
  ✅ session_active: MCP session is active.
  ❌ bundle_identity: Process has no CFBundleIdentifier.
      → Run the binary inside CuaDriver.app so TCC grants attribute correctly.
  ✅ tcc_accessibility: Accessibility is granted.
  ✅ tcc_screen_recording: Screen Recording is granted.
  ✅ ax_capability: AX is trusted and reachable.
  ✅ screen_capture_capability: ScreenCaptureKit reachable; 1 display(s) shareable.
```

- 整体状态为 `ok` 时**退出码为 0**——一切就绪。
- 状态为 `degraded` 或 `failed` 时**退出码为 1**——至少有一项检查失败；每条失败信息中的提示会告诉你需要修复什么。
- cua-driver 二进制文件本身不可达时**退出码为 2**。

常用参数：

- `--include CHECK` —— 仅运行列出的检查项（可重复指定多个）
- `--skip CHECK` —— 跳过某项检查（优先级高于 `--include`）
- `--json` —— 输出原始结构化 payload，格式与 `tools/call health_report` 的 MCP 响应一致

检查矩阵是平台感知的：`bundle_identity` / `tcc_*` 在 Windows 和 Linux 上为 `skip`，因为这些概念不适用。`ax_capability` 在 macOS 上检查 AX，在 Windows 上检查 UIA，在 Linux 上检查 AT-SPI —— 各自在不可达时给出对应的诊断提示。

## Agent 光标与会话

当 Agent 执行操作时，你会看到一个**带色调的浮层光标**滑过屏幕，停在每次点击 / 输入 / 滚动落点上。真实的操作系统光标从不移动——该浮层只是一个视觉提示，表示「Agent 正在这里操作」。每次 Hermes 运行都会声明自己的 cua-driver **会话 id**（形如 `hermes-3a7b9c14d2e8`）；光标的身份与该会话绑定，因此并发运行 / 子 Agent 各自拥有独立光标，互不干扰。

可以通过 `cua-driver` 的 CLI 参数或运行时 `set_agent_cursor_style` MCP 工具来调整光标——完整选项参见 [cua.ai/docs/how-to-guides/driver/personalize-cursor](https://cua.ai/docs/how-to-guides/driver/personalize-cursor)（内置 `arrow` 与 `teardrop` 轮廓、通过 `--cursor-icon` 使用自定义 SVG / PNG / ICO、运行时渐变颜色、光晕效果）。

## 深入了解 —— cua-driver 技能包

Hermes 有意让自己的技能（`skills/computer-use/SKILL.md`）专注于 Hermes 侧的 `computer_use` 动作词汇表——这是 Agent 加载的唯一真实来源。若需要更深入的材料——平台专属深度解析、录制语义、浏览器页面交互——请将你的 Agent 框架指向 cua-driver 团队直接发布并维护的 cua-driver 技能包：

```
cua-driver skills install
```

该命令会将技能包软链接到你的 Agent 框架的技能目录。运行后，Agent 即可访问：

| 文件 | 主题 |
|---|---|
| `SKILL.md` | 跨平台核心（快照不变式、无前台契约、点击投递、AX 树机制） |
| `MACOS.md` | macOS 专属内容：无前台契约、AXMenuBar 导航、SkyLight 点击投递、Apple Events JS 桥接 |
| `WINDOWS.md` | Windows 专属内容：UIA 树、UWP / `ApplicationFrameHost` 宿主机制、Session 0 隔离、autostart 模式 |
| `LINUX.md` | Linux 专属内容：AT-SPI 树、X11 / Wayland、终端模拟器检测 |
| `RECORDING.md` | 轨迹 + 视频录制语义 |
| `WEB_APPS.md` | 浏览器页面交互技巧 |
| `TESTS.md` | 按轨迹回放的工作流 |

这些是**平台深度解析，而非 Hermes 技能的副本**——当 Agent 报告「在 Windows 上，我的点击落到了错误的元素上」时，它会读取 `WINDOWS.md` 来获取解释原因以及应如何调整的 UIA / UWP 背景知识。

`cua-driver skills status` 会显示已安装内容以及它被链接到了哪些 Agent 框架。目前自动检测列表涵盖 Claude Code、Codex、OpenCode、OpenClaw 和 Antigravity；**对 Hermes 的自动检测计划在 `trycua/cua` 中作为后续工作实现**——在此之前，请先运行一次 `cua-driver skills install`，然后将你的框架指向生成的 `~/.cua-driver/skills/cua-driver` 目录（或将其软链接到你常用的技能目录）。

## 快速示例

用户 prompt（提示词）：*「找到我最近一封来自 Stripe 的邮件，总结他们希望我做什么。」*

Agent 的执行计划（在 macOS / Windows / Linux 上形状相同——模型会替换为该平台惯用的快捷键和应用名）：

1. `computer_use(action="capture", mode="som", app="Mail")` —— 获取邮件应用的截图，其中每个侧边栏项目、工具栏按钮和邮件行均已编号。
2. `computer_use(action="click", element=14)` —— 点击搜索框。
3. `computer_use(action="type", text="from:stripe")`
4. `computer_use(action="key", keys="return", capture_after=True)` —— 提交并获取新截图。
5. 点击最顶部的结果，读取正文，进行总结。

整个过程中，你的光标保持原位，邮件应用始终不会切换到前台。

## 提供商兼容性

| 提供商 | 支持视觉？ | 可用？ | 备注 |
|---|---|---|---|
| Anthropic（Claude Sonnet/Opus 3+） | ✅ | ✅ | 综合表现最佳；支持 SOM 与原始坐标。 |
| OpenRouter（任意视觉模型） | ✅ | ✅ | 支持多部分工具消息。 |
| OpenAI（GPT-4+、GPT-5） | ✅ | ✅ | 同上。 |
| Google（Gemini 2+） | ✅ | ✅ | 同时支持工具调用与视觉。 |
| 本地 vLLM / LM Studio / Ollama（视觉模型） | ✅ | ✅ | 需模型支持多部分工具内容。 |
| 纯文本模型 | ❌ | ✅（降级） | 使用 `mode="ax"` 仅通过无障碍树操作。 |

截图以 OpenAI 风格的 `image_url` 部分内联在工具结果中发送。对于 Anthropic，适配器会将其转换为原生 `tool_result` 图像块。图像 MIME 类型来自 cua-driver 显式提供的 `mimeType` 字段（`image/png` 或 `image/jpeg`）——不做客户端魔数嗅探。

## 安全性

Hermes 应用多层防护机制：

- 破坏性操作（click、type、drag、scroll、key、focus_app）需要审批——通过 CLI 对话框交互确认，或通过消息平台审批按钮确认。
- 工具层面硬性屏蔽的按键组合：清空废纸篓、强制删除、锁定屏幕、注销、强制注销。
- 硬性屏蔽的输入模式：`curl | bash`、`sudo rm -rf /`、fork bomb 等。
- Agent 的系统 prompt 明确规定：不得点击权限对话框，不得输入密码，不得执行截图中嵌入的指令。

如需对每个操作进行确认，可在 `~/.hermes/config.yaml` 中配置 `approvals.mode: manual`。

## Token 效率

截图开销较大。Hermes 应用四层优化措施：

- **截图淘汰** —— Anthropic 适配器在上下文中仅保留最近 3 张截图；较旧的截图替换为 `[screenshot removed to save context]` 占位符。
- **客户端压缩裁剪** —— 上下文压缩器检测多模态工具结果，并从旧结果中剥离图像部分。
- **图像感知 token 估算** —— 每张图像计为约 1500 个 token（Anthropic 的固定费率），而非其 base64 字符长度。
- **服务端上下文编辑（仅限 Anthropic）** —— 激活后，适配器通过 `context_management` 启用 `clear_tool_uses_20250919`，由 Anthropic API 在服务端清除旧工具结果。

在 1568×900 分辨率下执行 20 个操作的会话，截图上下文通常消耗约 3 万个 token，而非约 60 万个。

## 限制

- **性能。** 后台模式比前台模式慢——经无障碍层路由的事件在 macOS 上约 5–20 毫秒，在 Windows UIA 上约 3–10 毫秒，在 Linux AT-SPI 上约 5–15 毫秒，而直接 HID 投递更快。对于 Agent 速度的点击操作无明显影响；若尝试录制速通视频则会有感知。
- **不支持键盘输入密码。** `type` 对命令行 payload 有硬性屏蔽模式；密码请使用系统的自动填充功能（macOS 钥匙串 / Windows 凭据管理器 / GNOME Keyring / KWallet）。
- **部分应用不暴露无障碍树。** Windows 上的现代 UWP 应用、Linux 上低于 28 版本的 Electron，以及少数使用自定义绘制的 macOS 应用（Logic、Final Cut、部分游戏）的 AX 树稀疏或为空。如果树为空，请回退到像素坐标——或干脆跳过该任务。
- **Windows：无法从普通 Agent 驱动提升权限（管理员）的窗口。** Windows UIPI（用户界面特权隔离）强制执行完整性级别边界：中完整性级别的进程（默认的 Hermes Agent）无法枚举高完整性级别（管理员）进程所拥有窗口的 UIA 树，也无法向其注入鼠标输入。症状：`capture(mode='som')` 返回 0 个元素，`click(...)` 报告成功但实际什么都没做，而截图却能正常渲染（GDI 截图位于完整性检查之下）。键盘事件可部分绕过 UIPI，因此 Tab / Enter 仍能在提升权限的对话框中导航。这是操作系统的限制，而非 cua-driver 的缺陷——它影响每一个 Windows 自动化方案。若要驱动提升权限的窗口，请以高完整性级别运行 Hermes Agent 本身（从提升权限的终端启动）；否则请只针对未提升权限的窗口。
- **平台专属部署注意事项：**
  - **macOS** 使用私有 SkyLight SPI。Apple 可能在任何 OS 更新中更改它们。当已安装的 cua-driver 低于其测试基线版本时，Hermes 会发出警告。
  - **Windows** SSH 会话运行在 **Session 0** 中，该会话没有交互式桌面。请在 RDP / 控制台会话内部驱动 Hermes，或配置 cua-driver 的 autostart 计划任务——具体做法参见 [windows-ssh](https://cua.ai/docs/how-to-guides/driver/windows-ssh)。
  - **Linux** 需要一个可达的显示服务器。无头服务器需要先启动 Xvfb（`Xvfb :99 -screen 0 1920x1080x24`），`computer_use` 才能截图或注入事件。纯 Wayland 会话需要 XWayland 桥接才能进行屏幕捕获（cua-driver 的 Wayland 注入路径独立处理输入）。

如果需要跨平台 GUI 自动化但不想承担桌面开销（也不想配置 TCC / Session 0 / X11），`browser` 工具集使用真实的无头 Chromium，是纯 Web 任务的正确选择。

## 配置

覆盖驱动二进制路径（测试 / CI / 本地构建）：

```
HERMES_CUA_DRIVER_CMD=/path/to/your/cua-driver
```

完全替换后端（用于测试）：

```
HERMES_COMPUTER_USE_BACKEND=noop   # records calls, no side effects
```

### 遥测

cua-driver 上游默认启用匿名使用遥测（PostHog）。**Hermes 会替你关闭它**——在每次调用 cua-driver 时（MCP 后端、`status`、`doctor` 以及安装过程），Hermes 都会在驱动的环境中设置 `CUA_DRIVER_RS_TELEMETRY_ENABLED=0`。

若要重新开启（让 cua-driver 使用其自身默认值并发送遥测），请在 `config.yaml` 中设置：

```yaml
computer_use:
  cua_telemetry: true   # default: false (telemetry off)
```

开启时，`hermes computer-use doctor` 会报告 `telemetry: enabled`；关闭时（默认），它会报告 `telemetry: disabled via CUA_DRIVER_RS_TELEMETRY_ENABLED`。

## 针对本地 cua-driver 构建进行测试

当你正在开发 cua-driver 本身——或想测试一个尚未发布的修复——可以让 Hermes 指向你从源码构建的二进制文件，而不是已发布的版本。Hermes 通过 `shutil.which("cua-driver")` 解析驱动，并且**不强制校验 `HERMES_CUA_DRIVER_VERSION`**，因此本地构建（版本报告为 `0.0.0-local-*`）会被原样接受。有两种做法：

### 方式 A —— `install-local`（构建并放入 PATH）

在你的 `trycua/cua` 检出目录中运行上游的本地安装脚本。它会以 release 模式构建 Rust 后端，并将 `cua-driver` 放入与生产安装程序相同的安装布局中，同时把其 bin 目录加入 PATH：

```powershell
# Windows (PowerShell), from the cua repo root
./libs/cua-driver/scripts/install-local.ps1 -NoAutoStart
```

```bash
# macOS / Linux, from the cua repo root  (defaults to a debug build without --release)
./libs/cua-driver/scripts/install-local.sh --release
```

- Windows 会将构建产物暂存到 `%USERPROFILE%\.cua-driver\packages\…`，并将 `%LOCALAPPDATA%\Programs\Cua\cua-driver\bin`（已加入你的用户 PATH）以目录联接指向它。macOS/Linux 则将 `cua-driver` 软链接到 `~/.local/bin`（可用 `--bin-dir <path>` 覆盖）。
- `-NoAutoStart` 会跳过注册 `cua-driver-serve` 登录守护进程——Hermes 测试并不需要它（参见「注意事项与坑」）。

然后打开一个新的 shell（以便 PATH 变更生效）并确认：

```
cua-driver --version                 # local builds report 0.0.0-local-release
# Windows:      (Get-Command cua-driver).Source
# macOS/Linux:  which cua-driver
```

### 方式 B —— 让 Hermes 直接指向构建出的二进制文件（最快的循环）

完全跳过安装仪式：执行 `cargo build` 并把 `HERMES_CUA_DRIVER_CMD` 设置为生成的二进制文件。最适合快速的编辑/构建/测试循环。

```bash
cargo build -p cua-driver            # add --release for a release build; run from libs/cua-driver/rust
```

```
# Windows (.env)
HERMES_CUA_DRIVER_CMD=C:\path\to\cua\libs\cua-driver\rust\target\debug\cua-driver.exe
# macOS / Linux (.env)
HERMES_CUA_DRIVER_CMD=/path/to/cua/libs/cua-driver/rust/target/debug/cua-driver
```

### 确认 Hermes 正在使用你的构建

- `hermes computer-use status` 会打印解析到的二进制路径和版本。
- `hermes computer-use doctor` 会确认二进制文件可达，并端到端地跑通完整的 MCP 路径。
- 在会话中，`computer_use(action="capture")` 会实际驱动派生出的 `cua-driver mcp` 子进程。

### 注意事项与坑

- **Hermes 会通过 stdio 派生自己的 `cua-driver mcp` 子进程**——它*不会*连接到长期运行的 `cua-driver serve` autostart 守护进程或其命名管道。因此计划任务 / LaunchAgent 对测试来说不是必需的（使用 `-NoAutoStart` 即可）。autostart 守护进程和 Windows UIAccess 工作进程（`cua-driver-uia.exe`）只在某些应用（例如 WPF）需要前台安全输入时才有意义；标准工具面通过 stdio 子进程即可工作。在 Windows SSH 会话中，autostart 模式**是**必需的——参见「限制」一节。
- **Windows 上的二进制文件被占用。** 正在运行的 `cua-driver-serve` 守护进程可能占用 `cua-driver.exe`，导致重新构建时无法覆盖。`install-local.ps1` 会自动把被占用的二进制文件改名挪开；如果你手动执行 `cargo build`（方式 B），请先用 `cua-driver autostart disable`（或 `schtasks /End /TN cua-driver-serve`）停止它。
- **重新构建循环。** 修改 cua-driver 源码后，方式 A 重新运行 `install-local`（重新构建、重新暂存、切换 `current` 联接），方式 B 只需重新执行 `cargo build`——两种方式都不需要改动 Hermes。
- **本地构建跳过版本检查。** 当已安装的 cua-driver 低于其按操作系统设定的测试基线时 Hermes 会发出警告，但会豁免 `0.0.0-local-*` 开发构建——因此你的本地构建永远不会触发该警告。

## 故障排查

**出现任何异常时的第一个动作：运行 `hermes computer-use doctor`。** 结构化的逐项检查矩阵会准确告诉你（以及任何帮你调试的 Agent）问题出在哪里。

doctor 无法捕获的特定故障模式：

**`computer_use backend unavailable: cua-driver is not installed`** —— 运行 `hermes computer-use install` 获取 cua-driver 二进制文件，或运行 `hermes tools` 并启用 Computer Use 工具集。

**点击似乎没有效果** —— 截图并验证。可能有一个你未注意到的模态框正在阻止输入。使用 `escape` 或关闭按钮将其关闭。

**元素索引已过期** —— SOM 索引仅在下次 `capture` 之前有效。任何改变状态的操作后请重新截图。封装层会携带不透明的 `element_token` 用于过期检测——你会看到一个明确的错误，而不是一次错误的点击。

**「blocked pattern in type text」** —— 你尝试 `type` 的文本匹配了危险 shell 模式列表。请拆分命令或重新考虑操作方式。

**Linux 上截图为空** —— 未设置 `DISPLAY`，或你处在没有 XWayland 桥接的纯 Wayland 环境中。`hermes computer-use doctor` 会将其标记为 `ax_capability: fail`，并给出 `Set DISPLAY (X11)…` 提示。

**Windows 上通过 SSH 截图为空** —— 你处在 Session 0（服务会话）中。请直接从 RDP / 控制台驱动，或配置 autostart 模式——参见 [cua.ai/docs/how-to-guides/driver/windows-ssh](https://cua.ai/docs/how-to-guides/driver/windows-ssh)。

## 另请参阅

- **Hermes 侧技能** —— `skills/computer-use/SKILL.md` —— 讲解 Hermes 的 `computer_use` 动作词汇表；这是 Agent 实际加载的内容。
- **cua-driver 技能包** —— 若需平台专属深度解析（macOS 无前台契约、Windows UIA + Session 0、Linux AT-SPI + X11/Wayland、录制、浏览器页面），请运行 `cua-driver skills install` 并阅读 `MACOS.md` / `WINDOWS.md` / `LINUX.md` / `RECORDING.md` / `WEB_APPS.md`。一旦 `cua-driver skills install` 支持自动检测 Hermes（计划中的后续工作），这一步将在安装时自动完成。
- **cua.ai/docs** —— cua-driver 项目的文档：
  - [什么是电脑操控？](https://cua.ai/docs/explanation/what-is-computer-use) —— 概念介绍
  - [无前台契约](https://cua.ai/docs/explanation/the-no-foreground-contract) —— 后台模式*为何*重要
  - [安装参考](https://cua.ai/docs/how-to-guides/driver/install) —— 跨平台安装细节
  - [个性化 Agent 光标](https://cua.ai/docs/how-to-guides/driver/personalize-cursor) —— 内置形状、自定义素材、运行时覆盖
  - [通过 SSH 驱动 Windows](https://cua.ai/docs/how-to-guides/driver/windows-ssh) —— Session 0 → Session 1+ 的 autostart 模式
  - [保持 cua-driver 运行](https://cua.ai/docs/how-to-guides/driver/keep-running) —— autostart / 守护进程生命周期
  - [接入你的 Agent](https://cua.ai/docs/how-to-guides/driver/connect-your-agent) —— 将 cua-driver 注册到各类框架（Hermes 也在其中）
- [cua-driver 源码（trycua/cua）](https://github.com/trycua/cua)
- 若无需驱动原生应用的跨平台 Web 任务，请参阅[浏览器自动化](./browser.md)。
