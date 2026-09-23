---
sidebar_position: 11
title: "唤醒词"
description: "免手动的 'Hey Hermes' 唤醒词——像 'Hey Siri' 一样，开口说话即可开启语音会话"
---

# 唤醒词（"Hey Hermes"）

唤醒词让 Hermes 在 CLI、TUI 和桌面应用中成为一个免手动的助手：只需打开一项设置，
Hermes 就会在后台监听一个口述的触发短语。说出它，Hermes 就会开启一个新会话、打开麦克风、
通过常规的[语音管线](/user-guide/features/voice-mode)捕获你的命令，并作出回答——
就像 "Hey Siri" 或 "Alexa" 一样。用 `surface` 选择由哪一个界面来监听。

检测**完全在设备本地**运行。常驻的监听器只关注唤醒短语；在你真正对 agent
说出命令之前，没有任何音频会离开你的机器。

## 工作原理 {#how-it-works}

1. 当 `wake_word.enabled: true`（或执行 `/wake on` 之后）时，一个轻量级的热词
   检测器会在你配置的输入设备上监听；若未设置 `wake_word.input_device`，则使用进程的默认
   麦克风。
2. 当它听到唤醒短语时，会暂停自身（释放麦克风）、开启一个新会话，并借助语音模式的
   静音检测录制一段话语。
3. 你的语音会被转写并发送给 agent。它回复之后，监听器会自动恢复，
   等待下一次唤醒词。

它**默认关闭**——在你开启之前，什么都不会监听。

在桌面应用中，只需**说 "stop"**（或 "never mind"、"goodbye"、"cancel"、"that's all"）
即可结束一次免手动的语音对话——这条口述命令会结束对话，而不会被发送给 agent。只有
整句都是停止命令时才会匹配，因此像 "stop the docker container" 这样的真实请求仍会
正常送达。



## 远程桌面（客户端采集） {#remote-desktop-client-capture}

当桌面应用连接到一个**远程** Hermes 后端时（例如一台无头 Docker 主机或另一个房间里的
机器），后端往往**没有麦克风**。这时服务端的 PortAudio 会失败，报错 “Failed to open the
wake-word microphone.”

针对这种情况，Hermes 支持**客户端采集**：

1. 桌面端以 `capture: client` 启用唤醒（当后端没有本地输入设备时，GUI 会自动如此；
   也可以按下文显式设置）。
2. openWakeWord 仍然**在后端**运行（相同的引擎、相同的模型）。
3. 桌面端打开**本地 Mac/PC 麦克风**，重采样为 16 kHz 单声道
   int16，并通过 `wake.feed` RPC 以短帧形式流式发送。
4. 检测到唤醒时，后端照常发出 `wake.detected`；桌面端在客户端麦克风上启动
   常规的语音管线。

```yaml
wake_word:
  enabled: true
  capture: auto    # auto | local | client
  # auto   —— 使用本地 PortAudio，除非桌面端以 client_capture 启用
  # local  —— 始终打开后端麦克风（CLI/TUI 默认）
  # client —— 始终等待来自桌面端的 wake.feed PCM（适合远程）
```

桌面 GUI 在 `wake.start` 时总会传入 `client_capture: true`，因此没有麦克风的远程
后端会自动以客户端模式启用。CLI 和 TUI 保持本地采集，除非你显式设置 `capture: client`。

隐私说明：使用客户端采集时，唤醒 PCM 会通过经过认证的
桌面↔后端 WebSocket 传输（与会话其余部分使用同一通道）。检测仍然不会把音频发送给
第三方唤醒 API；引擎在后端进程本地运行。

## 引擎 {#engines}

| 引擎 | 费用 | API 密钥 | 说明 |
|--------|------|---------|-------|
| **openWakeWord**（默认） | 免费 | 无 | 本地 ONNX 模型。自带一个 **"hey hermes"** 模型（默认）；也支持 `hey_jarvis`、`alexa`、`hey_mycroft`……以及自定义模型 |
| **sherpa** | 免费 | 无 | **开放词表**——无需任何训练即可检测任意输入的短语。小型英文模型会在首次使用时自动下载（约 13 MB） |
| **Porcupine** | 免费套餐 / 付费 | `PORCUPINE_ACCESS_KEY` | Picovoice 引擎；内置关键词 + 自定义 `.ppn` 文件 |

默认短语是 **"hey hermes"**——Hermes 自带对应的模型，因此无需训练即可
开箱即用。（首次使用时，openWakeWord 会下载其共享的特征提取模型——一次性的少量下载。）

两者都会在你第一次启用唤醒词时延迟安装（使用 `--include-desktop` 进行的桌面
安装会预先装好它们，因此"耳朵"可以立即工作）。如需提前安装：

```bash
cd ~/.hermes/hermes-agent && uv pip install -e ".[wake]"
```

## 快速开始 {#quick-start}

```bash
# 在交互式 `hermes` 会话中：
/wake on        # 开始监听（首次使用时会安装引擎）
/wake status    # 显示短语、提供商和状态
/wake off       # 停止监听
```

在桌面应用中，点击输入框中的耳朵图标。

开关本身就是设置：打开或关闭唤醒词——无论通过 `/wake` 还是桌面端的耳朵按钮——
都会把 `wake_word.enabled` 写入 `~/.hermes/config.yaml`，因此你的选择会跨会话保留。
你也可以手动切换：

```yaml
wake_word:
  enabled: true
```

## 配置 {#configuration}

```yaml
wake_word:
  enabled: false
  surface: auto               # 可用界面："auto" | "cli" | "tui" | "gui"
  input_device: null           # PortAudio 输入索引或设备名子串；null = 进程默认
  capture: auto               # auto | local | client —— PCM 在哪里采集（见远程桌面）
  provider: openwakeword      # "openwakeword"（免费、本地）| "sherpa"（免费、任意短语）| "porcupine"
  phrase: "hey hermes"        # 仅为显示用标签 —— 检测由下方的模型/关键词决定
  sensitivity: 0.6            # 0.0-1.0 —— 越高越严格（误触发越少），所有引擎一致
  confirmation_frames: 3      # 仅 openWakeWord —— 触发所需的连续超阈值帧数
  start_new_session: true     # 唤醒时开启新会话，还是继续当前会话
  openwakeword:
    model: hey_hermes         # 自带默认模型；或内置名称；或自定义 .onnx/.tflite 的路径
    inference_framework: ""   # ""（自动）| "onnx" | "tflite"
  porcupine:
    keyword: jarvis           # 内置关键词，或自定义 .ppn 的路径
```

`sensitivity`、`phrase` 和 `start_new_session` 适用于两种引擎。
`openwakeword` 和 `porcupine` 配置块用于选择实际的检测模型。

`input_device` 会直接传给唤醒监听器的 PortAudio
（`sounddevice`）流。可以使用数字设备索引，也可以使用不产生歧义的
设备名子串。此设置只影响唤醒词采集；桌面端的按住说话仍然使用桌面应用自己的麦克风路径。

### 减少环境语音造成的误触发 {#reducing-false-triggers-on-ambient-speech}

openWakeWord 每次只对一小段（约 80ms）音频帧打分，因此背景对话中偶然出现的某个音素
有时会让单独一帧的分数冲过阈值，从而意外触发唤醒词。有两个参数可以控制这一点：

- **`confirmation_frames`**（默认 `3`，仅 openWakeWord）——唤醒触发前需要多少个
  *连续*的超阈值帧。真正的 "hey hermes" 会在若干帧内保持高分；环境中的偶发杂音
  只会让一帧冲高。如果在嘈杂的房间里仍有误触发，可以调高它（例如 `4`–`5`）；代价是
  多出几十毫秒的延迟。设为 `1` 可恢复旧的"首帧即触发"行为。
- **`sensitivity`**（默认 `0.6`）——检测阈值，范围 `0.0`–`1.0`。
  越高越严格（误触发越少）。这一方向在**所有**引擎中保持一致——对 openWakeWord
  而言它就是原始的逐帧分数阈值，对 sherpa 它映射到关键词阈值，对 Porcupine 则在
  内部取反，使"越高 = 越严格"同样成立。默认值 `0.6` 高于 openWakeWord 宽松的 `0.5`
  基线（后者会放过像 "hey hor" 这样的近似音）；如果仍有误触发，可向 `0.8` 调高；
  如果真正的 "hey hermes" 被漏掉，则调低它。

`sherpa` 和 `porcupine` 引擎会在内部解码整个短语，因此不存在单帧冲高的问题，
会忽略 `confirmation_frames`（但仍然遵循 `sensitivity`）。

`inference_framework` 用于选择 openWakeWord 的后端。保持为空（默认）即可让 Hermes
按平台自动选择：**Apple Silicon 上用 tflite**，其他平台用 onnx。openWakeWord 的 onnx
后端在 macOS ARM64 上返回的分数接近零
（[openWakeWord#336](https://github.com/dscripka/openWakeWord/issues/336)），
因此在那里固定为 `onnx` 的监听器会启用、显示为正在监听，却永远不会触发。
tflite 后端在 macOS 上需要 `ai-edge-litert`，Hermes 会在需要时连同其他唤醒词依赖一起安装。

### 界面（CLI、TUI、GUI） {#surfaces-cli-tui-gui}

唤醒词在 Hermes 的全部三种界面中都能使用，`surface` 决定由哪一个界面持有监听器，
并在唤醒触发时打开新会话：

| `surface` | 行为 |
|-----------|----------|
| `auto`（默认） | 所有本地界面都有资格；最先启用的那个持有监听器。 |
| `cli` | 仅经典的 `hermes` CLI。 |
| `tui` | 仅 `hermes --tui`。 |
| `gui` | 仅桌面应用。 |

检测器在设备本地运行且只使用一个麦克风，因此同一时间只有一个界面在监听，
即使各个 Hermes 界面运行在不同的进程中也是如此。持有关系是粘性的：
第一个符合条件的申领者会一直持有监听器，直到它停止、断开连接或其进程退出。
Hermes 不会静默地切换到另一个已打开的界面。
如果你希望固定持有者，而不是"先申领者胜出"，请设置 `surface`。
TUI 和桌面 GUI 共用同一个 Python 后端（`tui_gateway`），它在服务端运行检测器，
并在录制命令期间把麦克风让给语音采集。

## 使用其他短语 {#using-a-different-phrase}

"Hey Hermes" 开箱即用——自带的 openWakeWord 模型
（`model: hey_hermes`）是默认值。若要用别的短语唤醒，最简单的
途径是开放词表引擎：

### 方案 A —— sherpa（任意短语，无需训练） {#option-a--sherpa-any-phrase-zero-training}

输入你想要的短语即可；它会在运行时被切分为词元——"hey coder"、
"computer"、"wake up neo"，什么都行：

```yaml
wake_word:
  enabled: true
  provider: sherpa
  phrase: "hey coder"        # 检测键 —— 直接输入你的短语
```

小型英文 KWS 模型（约 13 MB）会在首次使用时下载一次。每个
profile 都可以设置自己的短语——为你运行的每个 profile 设一个 "hey \<profile\>"。

### 唤醒指定的 profile（桌面端） {#waking-a-specific-profile-desktop}

使用 sherpa 引擎时，一个监听器就能唤醒任意 profile。配置中带有
`wake_word.enabled: true` 的每个 profile 都会被自动登记；未设置时，其
短语默认为 `hey <profile name>`。说出某个 profile 的短语，
桌面应用就会实时切换到该 profile、在那里开启一个新会话，
并开始免手动语音：

- "hey hermes" → 默认 profile
- "hey coder" → `coder` profile
- "hey trader" → `trader` profile

在监听器所在的 profile 上设置 `wake_word.profile_routing: false` 即可退出此功能，
只监听它自己的短语。CLI 和 TUI 是单 profile
进程：属于其他 profile 的唤醒短语会打印出切换命令
（`hermes -p <profile>`），而不是进行路由。

名称按其英文子词发音进行声学匹配：由区分度高、含 2 个以上音节的名称组成的
双词短语效果最好。非常短的名称、明显的非英语音系特征，或两个发音相近的
profile 名称，都会降低准确率——必要时可按 profile 调整 `sensitivity`。

### 方案 B —— openWakeWord（免费，训练好的模型） {#option-b--openwakeword-free-trained-model}

指定一个内置模型（`hey_jarvis`、`alexa`、`hey_mycroft`……），或者训练一个
自定义模型（在免费/Colab GPU 上约需 75–90 分钟）以获得最佳鲁棒性，把
`.onnx` 文件放到某处，然后引用它：

```yaml
wake_word:
  enabled: true
  provider: openwakeword
  phrase: "computer"
  openwakeword:
    model: ~/.hermes/wakewords/computer.onnx   # 或内置名称，如 hey_jarvis
```

训练参考：

- [openWakeWord](https://github.com/dscripka/openWakeWord)
- [2026 训练 Colab](https://github.com/alfiedennen/openwakeword-colab-2026)

:::tip 选择一个有辨识度的短语
不会与日常用语冲突的唤醒短语泛化效果最好。包含一个不常见词语的双音节短语
（"hermes" 就符合）要胜过 "hello" 或 "stop" 这类常用词。
:::

### 方案 C —— Porcupine（几秒钟生成自定义关键词） {#option-c--porcupine-custom-keyword-in-seconds}

在 [Picovoice Console](https://console.picovoice.ai/) 中创建一个 "Hey Hermes" 关键词，
下载 `.ppn` 文件，然后：

```yaml
wake_word:
  enabled: true
  provider: porcupine
  phrase: "hey hermes"
  porcupine:
    keyword: ~/.hermes/wakewords/hey_hermes.ppn
```

在 `~/.hermes/.env` 中设置你的访问密钥：

```bash
PORCUPINE_ACCESS_KEY=your-key-here
```

## 要求 {#requirements}

- 一个可用的麦克风，以及 `sounddevice` + `numpy` 音频栈（与
  语音模式共用）。
- 一个用于转写口述命令的 STT 提供商——本地的 `faster-whisper`
  开箱即用；完整的提供商列表见[语音模式](/user-guide/features/voice-mode)。
- 一个用于朗读回复的 TTS 提供商（默认的 `edge-tts` 无需密钥即可使用）。唤醒流程
  完全免手动，因此在 STT 和 TTS 都就绪之前，开关会拒绝启用——`hermes tools`
  （Voice 部分）可以完成它们的设置。
- 唤醒引擎依赖（自动安装，或 `hermes-agent[wake]`）。

如果监听器无法启动，`/wake status` 会准确报告缺少了什么。

### 显示"正在监听"却从不唤醒（macOS） {#listening-but-never-wakes-macos}

macOS 按**进程**授予麦克风权限。桌面应用中 STT 能用，只能证明
*渲染进程*拥有麦克风权限——而唤醒监听器运行在 Python *后端*中，
后端需要单独授权。没有授权时，CoreAudio 会给后端一个
"能用"的音频流，但它只会输出静音，于是耳朵图标显示正在监听，
短语却永远不会触发。Hermes 能检测到这种情况（`/wake status` 会显示
"mic delivers only silence"；桌面端耳朵图标的提示文字也带有同样的提示）。
解决方法：系统设置 → 隐私与安全性 → 麦克风 → 启用 Hermes
后端（它可能显示为你的终端、`python` 或 Hermes），然后把唤醒词关掉再打开。

### 显示"正在监听"却只收到静音（Windows） {#listening-but-receives-silence-windows}

桌面端的按住说话和唤醒词采集使用不同的麦克风路径。
按住说话使用桌面应用的浏览器采集，而唤醒词监听器在 Python 后端中打开一个
PortAudio 流。可能一个能用，而另一个选中了静音或不可用的 Windows 输入设备。

`/wake status` 会报告所选的输入设备和 Windows 音频主机 API。
当它报告静音时，把 `wake_word.input_device` 设为可用 PortAudio 输入的数字索引或
不产生歧义的名称，然后切换一下唤醒词：

```bash
hermes config set wake_word.input_device "Microphone Array"
```

使用 `null` 恢复为进程默认值：

```bash
hermes config set wake_word.input_device null
```

## 说明与限制 {#notes--limits}

- **仅限本地界面。** 唤醒词在 CLI、TUI 和桌面 GUI 中运行——
  即任何有本地麦克风的地方。它不在消息网关（Telegram、Discord……）中运行，
  因为那里没有麦克风。
- **同一时间只用一个麦克风。** 检测器会在录制命令期间释放麦克风，
  并在该轮结束后重新占用，因此不会与语音采集争抢。
- **隐私。** 热词检测在本地进行。如果出现误触发，就调高 `sensitivity`；
  如果它总是听不到你，就调低它。
