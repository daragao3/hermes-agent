---
sidebar_position: 2
title: "安装"
description: "在 Linux、macOS、WSL2、原生 Windows 或通过 Termux 在 Android 上安装 Hermes Agent"
---

# 安装

使用 Hermes Agent，两分钟内即可启动并运行！

:::tip 平台支持
如需完整的平台支持矩阵（支持哪些操作系统、分发方式以及受平台限制的功能），
请参阅 **[平台支持](./platform-support.md)**。
:::

## 快速安装
### 在 macOS 或 Windows 上使用 Hermes Desktop 安装程序（推荐）
如需便捷地安装命令行应用和桌面应用，请从我们的网站[下载 Hermes Desktop 安装程序](https://hermes-agent.nousresearch.com/)并运行。

### 不使用 Hermes Desktop：
如需不含 Hermes Desktop 的纯命令行安装，请运行：

#### Linux / macOS / WSL2 / Android（Termux） {#linux--macos--wsl2--android-termux}
```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

#### Windows（原生） {#windows-native}

在 PowerShell 中运行：
```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1) 
```

如果你在完成纯命令行安装后想要安装并运行 Hermes Desktop，只需运行
```bash
hermes desktop
```

### 安装程序做了什么

安装程序自动处理一切——所有依赖（Python、Node.js、ripgrep、ffmpeg）、仓库克隆、虚拟环境、全局 `hermes` 命令配置以及 LLM 提供商配置。完成后即可开始聊天。

#### 安装目录结构

安装程序的存放位置取决于你是以普通用户还是 root 身份安装：

| 安装方式                                | 代码位置                       | `hermes` 二进制                          | 数据目录                              |
| --------------------------------------- | ------------------------------ | ---------------------------------------- | ------------------------------------- |
| 用户级（git 安装程序）                  | `~/.hermes/hermes-agent/`      | `~/.local/bin/hermes`（符号链接）        | `~/.hermes/`                          |
| Root 模式（`sudo curl … \| sudo bash`） | `/usr/local/lib/hermes-agent/` | `/usr/local/bin/hermes`                  | `/root/.hermes/`（或 `$HERMES_HOME`） |

Root 模式的 **FHS 布局**（`/usr/local/lib/…`、`/usr/local/bin/hermes`）与其他系统级开发工具在 Linux 上的安装位置一致。适用于共享机器部署场景，一次系统安装可服务所有用户。每个用户的个人配置（认证、技能、会话）仍位于各自的 `~/.hermes/` 或显式指定的 `HERMES_HOME` 下。

### 安装后

重新加载 shell 并开始聊天：

```bash
source ~/.bashrc   # 或：source ~/.zshrc
hermes             # 开始聊天！
```

如需稍后重新配置单项设置，使用以下专用命令：

```bash
hermes model          # 选择 LLM 提供商和模型
hermes tools          # 配置启用的工具
hermes gateway setup  # 配置消息平台
hermes config set     # 设置单个配置项
hermes config get     # 查看单个配置项
hermes setup          # 或运行完整的设置向导一次性配置所有内容
```

:::tip 最快路径：Nous Portal
一个订阅涵盖 300+ 个模型以及 [Tool Gateway](/user-guide/features/tool-gateway)（网络搜索、图像生成、TTS、云端浏览器）。无需逐一管理各工具的密钥：

```bash
hermes setup --portal
```

该命令一次性完成登录、设置 Nous 为提供商并开启 Tool Gateway。
:::

:::tip 已经在另一台机器上运行 Hermes？
你无需从头重建配置。可以用 `hermes import` 恢复完整备份（参见[将 Hermes 导出到另一台机器](/reference/faq#exporting-hermes-to-another-machine)），或用 `hermes profile import` 迁移单个 Agent（参见[将单个配置档案迁移到另一台机器](/reference/faq#moving-a-single-profile-to-another-machine)）。注意，配置档案导出在设计上不包含凭据，因此仅靠导出并不是完整备份——[`hermes backup` 与 `hermes profile export` 的区别](/reference/faq#hermes-backup-vs-hermes-profile-export)说明了该用哪一个。
:::

---

## 前置条件

**安装程序：** 在非 Windows 平台上，唯一的前置条件是 **Git**。在 Linux 上，还需确保 `curl` 和 `xz-utils` 可用（安装程序会以 `.tar.xz` 归档形式下载 Node.js）。桌面应用还额外需要 `g++`（在 Debian/Ubuntu 上为 `build-essential`）来编译原生模块。安装程序自动处理其余一切：

- **uv**（快速 Python 包管理器）
- **Python 3.11**（通过 uv，无需 sudo）
- **Node.js v26**（用于浏览器自动化和 WhatsApp 桥接；系统中已有的 Node 22.22+、24.11+ 或 26+ 会被直接使用）
- **ripgrep**（快速文件搜索）
- **ffmpeg**（TTS 的音频格式转换）

:::info
你**无需**手动安装 Python、Node.js、ripgrep 或 ffmpeg。安装程序会检测缺失的依赖并自动安装。只需确保 `git` 可用（`git --version`）。在 Linux 上，请确保已安装 `curl` 和 `xz-utils`（在 Debian/Ubuntu 上执行 `sudo apt install curl xz-utils`）。对于桌面应用，还需安装 `build-essential`（`sudo apt install build-essential`）。
:::

:::tip Nix 用户
Nix **不再是明确支持的安装路径**（仅尽力而为）。如果你已经在使用 Nix（在 NixOS、macOS 或 Linux 上），有专门的配置路径，包含 Nix flake、声明式 NixOS 模块和可选容器模式。请参阅 **[Nix & NixOS 配置](./nix-setup.md)** 指南。
:::

---

## 手动 / 开发者安装

如果你想克隆仓库并从源码安装——用于贡献代码、从特定分支运行或完全控制虚拟环境——请参阅贡献指南中的[开发环境配置](../developer-guide/contributing.md#development-setup)章节。

---

## 非 Sudo / 系统服务用户安装

支持以专用非特权用户身份运行 Hermes（例如 `hermes` systemd 服务账户，或任何没有 `sudo` 权限的用户）。安装路径中真正需要 root 权限的只有 Playwright 的 `--with-deps` 步骤，该步骤通过 `apt` 安装 Chromium 所需的共享库（`libnss3`、`libxkbcommon` 等）。安装程序会检测 sudo 是否可用，并在不可用时优雅降级——它会将 Chromium 二进制安装到服务用户自己的 Playwright 缓存中，并打印管理员需要单独运行的确切命令。

**推荐的分步方式（Debian/Ubuntu）：**

1. **一次性操作，以具有 sudo 权限的管理员用户身份**，安装 Chromium 所需的系统库：

   ```bash
   sudo npx playwright install-deps chromium
   ```

   （可在任意位置运行——`npx` 会自动获取 Playwright。）

2. **以非特权服务用户身份**，运行常规安装程序。它会检测到缺少 sudo，跳过 `--with-deps`，并将 Chromium 安装到用户本地的 Playwright 缓存中：

   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
   ```

   如果想完全跳过 Playwright 步骤——例如在无头环境中运行且不需要浏览器自动化——传入 `--skip-browser`：

   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-browser
   ```

   安装程序还会预装 [`cua-driver`](../user-guide/features/computer-use.md)，这样 Computer Use 工具集在你启用的那一刻即可工作；传入 `--skip-computer-use` 可选择不预装（届时会在你启用该工具时按需安装）。

3. **使 `hermes` 对服务用户的 shell 可用。** 安装程序将启动器写入 `~/.local/bin/hermes`。系统服务账户通常具有不包含 `~/.local/bin` 的最小 PATH。可以将其添加到用户环境，或将启动器符号链接到系统位置：

   ```bash
   # 方案 A — 添加到服务用户的 profile
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

   # 方案 B — 系统级符号链接（以管理员身份运行）
   sudo ln -s /home/hermes/.hermes/hermes-agent/venv/bin/hermes /usr/local/bin/hermes
   ```

4. **验证：** `hermes doctor` 现在应能正常运行。如果出现 `ModuleNotFoundError: No module named 'dotenv'`，说明你在用系统 Python 调用仓库源码中的 `hermes` 文件（`~/.hermes/hermes-agent/hermes`），而非 venv 启动器（`~/.hermes/hermes-agent/venv/bin/hermes`）——请修正步骤 3。

5. **要从这个账户运行消息 gateway？** 用户级服务会在注销时停止，并且在你为该服务用户启用 lingering 之前不会在开机时启动：

   ```bash
   sudo loginctl enable-linger <service-user>
   ```

   服务本身的配置请参阅[消息 Gateway](/user-guide/messaging/)。

同样的方式适用于 Arch（安装程序使用 pacman，具有相同的 sudo 检测逻辑）、Fedora/RHEL 和 openSUSE——这些发行版完全不支持 `--with-deps`，因此管理员始终需要单独安装系统库。安装程序会打印相应的 `dnf`/`zypper` 命令。

---

## 故障排查

| 问题                        | 解决方案                                                                           |
| --------------------------- | ---------------------------------------------------------------------------------- |
| `hermes: command not found` | 重新加载 shell（`source ~/.bashrc`）或检查 PATH                                    |
| `API key not set`           | 运行 `hermes model` 配置提供商，或 `hermes config set OPENROUTER_API_KEY your_key` |
| 更新后配置丢失              | 运行 `hermes config check`，然后运行 `hermes config migrate`                       |

如需更多诊断信息，运行 `hermes doctor`——它会告诉你确切缺少什么以及如何修复。

### 符号链接的主目录与外部存储 {#symlinked-home-directories-and-external-storage}

Hermes 支持符号链接的 `HERMES_HOME` 以及符号链接的主目录子目录，
包括 `hooks`、`skills`、`sessions` 和 `logs`。在主目录初始化期间，
已有的目录链接会被保留，链接目录（以及 `logs/curator` 等子孙目录）的权限
交由其所有者管理。

如果链接目标缺失、无法访问或不是目录，初始化会停止，并报告一个存储错误，
其中指明该路径和链接目标。Hermes **不会**替换该链接，也不会创建缺失的目标：
这样做可能会在外部卷或 NAS 卷未挂载时把数据写到本地磁盘上。请检查报告的
链接，恢复挂载或修正其目标，并在重试前确认访问权限。如果确实要使用一个新的
dotfiles 目标，请仅在确认目标存储可用后自行创建。

`hermes doctor` 会将这些失败报告为存储问题，而非无效的 YAML。
请保留现有的 `config.yaml`；对于不可用的目录，运行 `hermes setup` 并不能修复。
这是目录可用性检查，而不是挂载监控：一个已存在的目录并不能证明预期的卷已挂载。

## 安装方式自动检测

Hermes 会自动检测安装方式（git 安装程序、Docker 或 NixOS），`hermes update` 会打印对应路径的更新命令。无需设置任何环境变量——检测基于安装目录结构（`~/.hermes/hermes-agent/` 检出、Docker 镜像标记或 Nix store 路径）。`hermes doctor` 也会在其环境摘要中显示检测到的安装方式。
