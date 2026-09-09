---
sidebar_position: 2.5
title: "平台支持"
description: "Hermes Agent 支持哪些操作系统、分发方式与功能特性。"
---

# 平台支持

Hermes Agent 对众多平台和分发方式保持支持，但我们无法支持所有可能的安装方式。

---

## 第一梯队（Tier 1）

我们努力确保这些平台的安装与更新永不中断。第一梯队中的问题与回归是我们的首要任务，优先级高于其他平台。

| 操作系统 / 架构                                                                | 安装方式                                                                                                                        | 说明                                                                                                                                                       |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **macOS**（Apple Silicon）                                                    | [Hermes Desktop](https://hermes-agent.nousresearch.com/)、[`install.sh`](./installation.md#linux--macos--wsl2--android-termux) |
| [**Windows 10 / 11**](../user-guide/windows-native.md)（x86_64、aarch64）      | [Hermes Desktop](https://hermes-agent.nousresearch.com/)、[`install.ps1`](./installation.md#windows-native)                    | 少数功能[尚不可用](../user-guide/windows-native.md#feature-matrix)。                                                                                       |
| **Linux / [WSL2](../user-guide/windows-wsl-quickstart.md)**（x86_64、aarch64） | [`install.sh`](./installation.md#linux--macos--wsl2--android-termux)                                                           | 我们在最新版 Ubuntu 与 WSL2 上测试。如果你的发行版带有 glibc、systemd，并遵循文件系统层次标准（FHS），那么它大概率能良好运行。 |
| [**Docker 容器**](../user-guide/docker.md#quick-start)（x86_64、aarch64）      | [`docker pull`](../user-guide/docker.md#quick-start)                                                                           | Docker 安装不支持 `hermes update`。更新方式是运行新镜像。                                                                                                 |

---

## 第二梯队（Tier 2） {#tier-2}

这些平台仅以尽力而为的方式在代码库中维护。
发布可能破坏它们，我们也无法保证在它们出问题时能及时修复。

我们接受修复这些问题的 PR，但其优先级低于修复第一梯队平台的问题。

| 操作系统 / 架构                 | 安装方式                                                             | 说明                                                                         |
| ------------------------------ | -------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **Android（Termux）**（aarch64） | [`install.sh`](./installation.md#linux--macos--wsl2--android-termux) | 少数功能[尚不可用](./termux.md#known-limitations-on-phones)。 |
| **Nix**（MacOS、Linux、NixOS）  | [`install.sh`](./nix-setup.md)                                       | 由于 node.js 打包的种种麻烦，经常出问题。祝你好运～！&lt;3             |

## 不受支持

以下平台与分发方式**不**受支持。
我们建议你迁移到受支持的分发方式或平台。
它们现在可能就是坏的，将来也可能坏得更彻底。
修复它们的 PR _不会_ 被接受，任何为保持与它们兼容而存在的代码都可能随时被移除。

- 通过 AUR 安装（如果有帮助，我们也许会把补丁提交到上游 &lt;3）
- x86（Intel）处理器上的 macOS
- 通过 `pypi` 安装（例如 `uv tool install hermes-agent`、`pip install hermes-agent` 等）
- 通过 `brew` 安装（`brew install hermes-agent`）

如果你正在使用不受支持的分发方式，请阅读[安装指南](./installation.md)了解如何切换到受支持的方式。
