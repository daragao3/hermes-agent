---
sidebar_position: 0
title: "在 Hermes Agent 中免费运行 Nemotron 3 Ultra"
description: "在 Nous Portal 上试用 NVIDIA Nemotron 3 Ultra——6 月 4 日至 18 日免费——Hermes Agent 提供 day 0 支持"
---

# 在 Hermes Agent 中免费运行 Nemotron 3 Ultra

Nous Research 已加入 **Nemotron 联盟（Nemotron Coalition）**，与 **NVIDIA** 及多家领先 AI 实验室共同推进开放的前沿基础模型。为此，我们与 **Nebius** 合作，在 [Nous Portal](https://portal.nousresearch.com) 上免费提供 **Nemotron 3 Ultra**，为期两周（**6 月 4 日 – 6 月 18 日**）。按照下面的说明，今天就能在你的 Hermes Agent 中试用该模型。

:::info 限时优惠
`nvidia/nemotron-3-ultra:free` 档位的可用时间为 **6 月 4 日至 6 月 18 日**。`:free` 标签正是让它保持免费方案的关键——请务必选择这个确切的变体。
:::

选择适合你的安装方式。**桌面应用**最简单——无需终端。如果你更习惯终端，**命令行**安装方式紧随其后。

## 方式 A —— 桌面应用（推荐）

最简单的路径：一键安装程序，配合引导式的点选配置。无需终端。

### 1. 下载并安装

[下载 Hermes Desktop 安装程序](https://hermes-agent.nousresearch.com/)（macOS 或 Windows），然后打开它。首次启动时它会完成自身的安装配置（通常不到一分钟）。

### 2. 连接 Nous Portal

应用打开后，你会看到一个 "Let's get you set up" 界面。点击 **Nous Portal**（标记为 **Recommended**）。浏览器会打开——创建一个 [Nous Portal](https://portal.nousresearch.com) 账号（或登录），选择 **Free** 方案，并授权 Hermes。应用会自动完成连接。

### 3. 选择免费的 Nemotron 3 Ultra 模型

连接完成后，应用会显示一张 **Default model** 卡片。点击 **Change**，搜索 **nemotron 3 ultra**，并选择标记为 **Free tier** 的变体：

```
nvidia/nemotron-3-ultra:free
```

`:free` 标签正是让它保持免费档位的关键——请选择该变体。

### 4. 开始对话

点击 **Start chatting**。就这样——你已经在免费使用 Nemotron 3 Ultra 了。

## 方式 B —— 命令行

更喜欢终端？

### 1. 安装 Hermes Agent

在 macOS/Linux/WSL2/Android 上运行

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

在 Windows 上运行

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

想先审查脚本？下载 [`install.sh`](https://hermes-agent.nousresearch.com/install.sh)，检查后再运行。

安装完成后，重新加载你的 shell：

```bash
source ~/.bashrc   # or source ~/.zshrc
```

### 2. 运行 Quick Setup

```bash
hermes setup
```

选择 **Quick Setup**。Hermes 会打开一个浏览器标签页，等待你完成后续步骤。

### 3. 创建 Nous Portal 账号

在浏览器中创建一个 [Nous Portal](https://portal.nousresearch.com) 账号（或登录），并选择 **Free** 方案。

### 4. 连接你的账号

当提示将账号连接到 Hermes Agent 时，点击 **Connect**。连接成功后你会看到确认信息。

### 5. 选择免费的 Nemotron 3 Ultra 模型

返回终端。从模型列表中选择：

```
nvidia/nemotron-3-ultra:free
```

`:free` 标签正是让它保持免费档位的关键，所以务必选中该变体。

### 6. 开始对话

完成 Quick Setup 剩余的提示，然后运行：

```bash
hermes
```

就这样——你已经在免费使用 Nemotron 3 Ultra 了。

## 之后再切换到它

已经用其他模型完成配置了？

- **桌面应用：** 打开模型选择器，搜索 **nemotron 3 ultra**，选择 **Free tier** 变体。
- **CLI / TUI：** 在会话中随时用 `/model nvidia/nemotron-3-ultra:free` 切换，或运行 `/model` 打开选择器并从列表中选择。

## 故障排查

- **在列表里看不到这个模型？** 确认你已完成 Nous Portal 连接，并且使用的是 **Free** 方案。在 CLI 中，`hermes portal info` 可确认你已登录并通过 Nous 路由。
- **选错了变体？** 重新选择 `nvidia/nemotron-3-ultra:free`——必须带 `:free` 后缀才能保持在免费档位。
- **浏览器没有打开／你在远程主机上（CLI）？** 参见 [OAuth over SSH / 远程主机](/guides/oauth-over-ssh) 中的端口转发变通方案。

## 另请参阅

- **[桌面应用](/user-guide/desktop)** —— 原生一键应用（macOS、Windows、Linux）
- **[通过 Nous Portal 运行 Hermes Agent](/guides/run-hermes-with-nous-portal)** —— 完整的 Portal 操作指南：模型、Tool Gateway 与验证
- **[Nous Portal 集成](/integrations/nous-portal)** —— 订阅包含哪些内容
- **[快速入门](/getting-started/quickstart)** —— 5 分钟内从安装到对话
