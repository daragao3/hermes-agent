---
sidebar_position: 4
title: 本地模型
description: 完全在你自己的机器上运行模型——无需账户、无需 API 密钥，任何数据都不会离开你的电脑。
---

# 本地模型 {#local-models}

Hermes 可以完全在你自己的机器上运行开放模型。它会下载并管理推理引擎
（llama.cpp），为你的硬件挑选每个模型合适的构建版本，并负责内存管理，
因此你无需配置上下文大小、GPU 层数或量化。你只需挑选模型，其余交给 Hermes。

任何数据都不会离开你的电脑：无需账户、无需 API 密钥，模型下载完成后
也无需网络访问。

## 快速上手 {#getting-started}

1. 打开 **Settings → Providers → Local Models**（或在引导流程中选择
   **Run models locally**）。
2. 点击 **Install runtime**。Hermes 会为你的硬件下载官方 llama.cpp
   构建（几百 MB），对其进行校验，并保持更新。
3. 从目录中挑选一个模型并点击 **Download**。
4. 点击 **Use**。新的聊天现在会运行在本地模型上。

这就是完整流程。服务器随 Hermes 启动和停止，应用重启后依然保持，
切换回云端 provider 只需在模型选择器里点一下。

## Hermes 如何决定下载什么 {#how-hermes-picks-what-to-download}

在你下载任何东西之前，目录中的每个模型都会针对**你的机器**进行评估。
每一行显示：

- **内存适配** —— 绿色（*Fits your GPU*：完全在 GPU 显存中运行）、
  琥珀色（*Uses system RAM*：可以运行，但较慢）或红色（*Too big for this
  machine*）。
- **上下文** —— 模型起始的上下文窗口，以及它可以增长到的最大值。
- 为你的硬件所选构建版本的下载大小。

模型以多个质量等级（量化）发布。Hermes 会挑选能完全在你的 GPU 上运行的
最高质量构建；内存较少的机器会获得同一模型更紧凑的构建，并享有相同的
保证。低于 4-bit 时质量损失过于严重，因此 Hermes 从不提供比这更小的构建
——一台即便把 4-bit 构建溢出到系统内存也无法运行的机器，就是无法运行该模型。

放不下的模型仍然可见，并附有原因，因此你始终知道升级硬件能解锁什么。

## 内存管理如何工作 {#how-memory-management-works}

本地模型的成败取决于内存放置，因此 Hermes 端到端地管理它，且不暴露任何
调节项：

- **模型以一个完全适配你 GPU 的上下文窗口启动**，并随着对话需要更多空间
  而向其原生最大值增长。在长会话中你可能会在状态信息流里看到
  "Context window grown"——那是窗口在扩展，不是错误。
- **每个推荐模型都至少拥有 64K 的上下文窗口。** 当模型大于你的 GPU 显存时，
  Hermes 会有意按照影响最小的顺序把溢出部分放到系统内存中（先放专家权重，
  绝不放注意力缓存），以牺牲部分速度来保障上下文承诺。
- **对话压缩只会在达到模型最大窗口时才启动**——总是先增长窗口。
- 空闲模型会在 15 分钟后卸载以释放 GPU 显存；在下一条消息到来时会自动重新加载。

## 状态栏 {#the-status-bar}

右键点击状态栏并启用 **System resources**，即可在本地模型运行时查看实时的
GPU 利用率、GPU 显存和 RAM。上下文指示器始终反映模型实际运行时使用的窗口。

## 查找更多模型 {#finding-more-models}

目录是一个精选的起点，而不是边界。同一页面上的 **Find more
models** 区域可以搜索整个 Hugging Face：

- 结果会显示下载次数，以及按你的机器计算的逐文件适配检查，因此在下载之前
  你就知道某个构建能否完全在你的 GPU 上运行。
- 你下载的任何模型都与目录模型的行为完全一致——Hermes 会读取模型文件本身
  来决定其上下文窗口和内存放置。唯一的区别是：社区模型不带我们的
  “validated”测试徽章。
- 磁盘上已经有 `.gguf` 文件？**Add model file** 会把它链接进你的模型库而不复制
  （原文件保留在原处），并且可以立即使用。

## 使用你自己的 llama-server {#using-your-own-llama-server}

如果你的机器上已经在运行一个 llama-server，Hermes 会检测到它并使用它，
而不是启动自己的服务器。将一个自定义端点指向任意 OpenAI 兼容服务器即可
获得完全的手动控制——托管运行时只是默认选项，而非必需。对于手动配置
（Ollama、MLX、自定义构建、无界面的 CLI 机器），参见
[Run Hermes Locally with Ollama](/guides/local-ollama-setup) 和
[Run Local LLMs on Mac](/guides/local-llm-on-mac)。

## 配置 {#configuration}

托管运行时由 `config.yaml` 的 `local_runtime` 部分控制。桌面 UI 会替你
写入这些值；此处记录它们是为了 CLI 和无界面场景使用：

```yaml
local_runtime:
  enabled: false     # true = 随 Hermes 启动托管服务器。
                     # 桌面端的 "Use" 按钮会自动设置此项。
  backend: auto      # auto | cuda | metal | vulkan | hip | cpu
  tag: b10362        # 固定的 llama.cpp 发布版本；Hermes 会在每次
                     # 发布并重新验证后更新它
```

模型和运行时构建存放在 Hermes 主目录下（`models/` 和 `runtimes/llamacpp/`）。
将本地模型选为你的主模型时，使用标准的 `model.provider: llamacpp` +
`model.default` 设置——与其他所有 provider 的形式相同。

## 要求与限制 {#requirements-and-limits}

- **Windows 和 Linux：** NVIDIA GPU（CUDA）或 CPU。**macOS：** Apple
  Silicon（Metal）。Vulkan 构建用于 AMD GPU。
- 拥有 8 GB 以上显存的 GPU 可以流畅运行目录中的小模型；16 GB 以上可以以高质量
  运行 27–35B 的模型。
- 模型下载在传输过程中会对照目录校验字节大小；不完整的下载会被删除并报告，
  绝不会被半途使用。（只有运行时引擎的 zip 包会进行 SHA-256 校验。）
- 删除一个模型会移除它暂存的所有文件，包括视觉适配器和推测解码的配套模型。
