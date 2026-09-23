---
sidebar_position: 3
title: "Android / Termux"
description: "通过 Termux 在 Android 手机上直接运行 Hermes Agent"
---

# 在 Android 上通过 Termux 运行 Hermes

:::warning Tier 2 平台
Termux（Android）属于 [Tier 2 平台](./platform-support.md#tier-2)。这里的安装脚本和文档仅按尽力而为的方式维护。提交到 `main` 的改动可能随时破坏这些软件包。
:::

Hermes Agent 可以通过 [Termux](https://termux.dev/) 在 Android 手机上直接运行。

它为你提供手机上可用的本地 CLI，以及目前已知可在 Android 上干净安装的核心扩展功能。

## 已验证路径支持哪些功能？

已验证的 Termux 安装包含：

- Hermes CLI
- cron 支持
- PTY（伪终端）/后台终端支持
- Telegram gateway 支持（手动 / 尽力而为的后台运行）
- MCP 支持
- Honcho 记忆支持
- ACP 支持

具体对应以下命令：

```bash
python -m pip install -e '.[termux]' -c constraints-termux.txt
```

## 哪些功能尚未纳入已验证路径？

部分功能仍依赖桌面/服务器风格的依赖项，这些依赖项尚未为 Android 发布，或尚未在手机上验证：

- `.[all]` 目前不支持 Android
- `voice` 扩展被 `faster-whisper -> ctranslate2` 阻塞，`ctranslate2` 未发布 Android wheel 包
- 自动浏览器 / Playwright 引导在 Termux 安装程序中被跳过
- 基于 Docker 的终端隔离在 Termux 内不可用
- Android 可能仍会挂起 Termux 后台任务，因此 gateway 持久化是尽力而为，而非正常的托管服务

这并不妨碍 Hermes 作为手机原生 CLI agent 正常工作——只是意味着推荐的移动端安装有意比桌面/服务器安装更精简。

---

## 社区维护的原生 `pkg` 安装方式

:::caution 贡献者运营的发行版
此 APT 仓库**由 `@adybag14-cyber` 社区维护，并非 NousResearch 官方发行版**。NousResearch 不构建、不签名、不托管，也不审计这些软件包。启用该仓库即意味着信任这个由贡献者运营的仓库及其签名密钥。Termux 本身仍是 Tier 2 / 尽力而为的平台。
:::

如果你更倾向于使用原生包管理器安装，而不是在手机上构建 Python/Rust 依赖，可以使用一个社区维护的 APT 仓库。仓库引导脚本和打包源码发布在 [`adybag14-cyber/termux-python`](https://github.com/adybag14-cyber/termux-python)，Hermes 软件包的构建位于 [`adybag14-cyber/termux-hermes`](https://github.com/adybag14-cyber/termux-hermes)。

使用以下命令安装仓库密钥/源以及 Hermes：

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/scripts/setup_apt_repo.sh | bash
pkg install hermes-agent
```

该社区发行版目前公布的仓库签名密钥指纹为：

```text
EAD24A2124EFA7393A78B7B14699F966313F7A6B
```

通过 APT 管理的 Hermes 安装会被标记为安装方式 `apt`。因此 Hermes 不会对软件包所拥有的文件运行其 Git 自更新程序；请改用包管理器更新：

```bash
pkg update
pkg upgrade hermes-agent
```

此安装方式的打包/仓库/签名问题应报告给上述社区打包仓库。Hermes 运行时 bug 仍可在此处报告，但请注意 Android/Termux 支持属于尽力而为。

---

## 方式一：一行安装命令

Hermes 现已内置 Termux 感知的安装路径：

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

在 Termux 上，安装程序会自动：

- 使用 `pkg` 安装系统包
- 使用 `python -m venv` 创建虚拟环境
- 优先尝试较大的 `.[termux-all]` 扩展，失败后回退到较小的 `.[termux]` 扩展（再次失败则进行基础安装）——curl 安装程序自动按此顺序执行
- 将 `hermes` 链接到 `$PREFIX/bin`，使其保留在 Termux PATH 中
- 跳过未经验证的浏览器 / WhatsApp 引导

如果你需要显式命令或需要调试失败的安装，请使用下方的手动安装路径。

---

## 方式二：手动安装（完全显式）

### 1. 更新 Termux 并安装系统包

```bash
pkg update
pkg install -y git python clang rust make pkg-config libffi openssl nodejs ripgrep ffmpeg
```

各包用途说明：

- `python` — 运行时 + 虚拟环境支持

:::warning 支持的 Python 版本范围
Hermes 需要 **Python >=3.11,&lt;3.14**。当前 Termux 提供的 `python`
为 3.14.x，超出该范围——安装程序会检测到这一点，并自动尝试从
[Termux User Repository (TUR)](https://github.com/termux-user-repository/tur)
获取受支持的解释器。手动安装时，请自行安装一个：

```bash
pkg install tur-repo
pkg install python3.13
```

然后在下面的命令中用 `python3.13` 代替 `python`
（例如 `python3.13 -m venv venv`）。
:::

- `git` — 克隆/更新仓库
- `clang`、`rust`、`make`、`pkg-config`、`libffi`、`openssl` — 在 Android 上构建部分 Python 依赖所需
- `nodejs` — 可选的 Node 运行时，用于已验证核心路径之外的实验
- `ripgrep` — 快速文件搜索
- `ffmpeg` — 媒体 / TTS 转换

### 2. 克隆 Hermes

```bash
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
```

### 3. 创建虚拟环境

```bash
python -m venv venv
source venv/bin/activate
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk)"
python -m pip install --upgrade pip setuptools wheel
```

`ANDROID_API_LEVEL` 对于基于 Rust / maturin 的包（如 `jiter`）非常重要。

### 4. 安装已验证的 Termux 包

```bash
python -m pip install -e '.[termux]' -c constraints-termux.txt
```

如果你只需要最小化的核心 agent，以下命令同样有效：

```bash
python -m pip install -e '.' -c constraints-termux.txt
```

### 5. 将 `hermes` 添加到 Termux PATH

```bash
ln -sf "$PWD/venv/bin/hermes" "$PREFIX/bin/hermes"
```

`$PREFIX/bin` 在 Termux 中已默认在 PATH 中，因此这样做可以让 `hermes` 命令在新 shell 中持续可用，无需每次重新激活虚拟环境。

### 6. 验证安装

```bash
hermes --version
hermes doctor
```

### 7. 启动 Hermes

```bash
hermes
```

---

## 推荐的后续配置

### 配置模型

```bash
hermes model
```

或直接在 `~/.hermes/.env` 中设置密钥。

### 稍后重新运行完整的交互式设置向导

```bash
hermes setup
```

### 手动安装可选的 Node 依赖

已验证的 Termux 路径有意跳过 Node/浏览器引导。如果你之后想尝试浏览器工具，所需内容取决于你使用哪种后端：

- **云浏览器提供商**（Browserbase、Browser Use、Firecrawl）自行托管 Chromium，因此仅需 Node.js 即可——`agent-browser` 会在首次使用时通过 `npx agent-browser` 延迟解析：

  ```bash
  pkg install nodejs-lts
  ```

- Termux 上的**本地浏览器自动化**需要真正安装 `agent-browser`——在本地模式下，裸 npx 回退会被有意拒绝，因为它过于脆弱，不宜标记为就绪：

  ```bash
  pkg install nodejs-lts
  npm install -g agent-browser && agent-browser install
  ```

浏览器工具会自动将 Termux 目录（`/data/data/com.termux/files/usr/bin`）纳入 PATH 搜索，因此无需额外配置 PATH 即可发现 `agent-browser` 和 `npx`。

在另有文档说明之前，请将 Android 上的浏览器 / WhatsApp 工具视为实验性功能。

---

## 故障排查

### 安装 `.[all]` 时出现 `No solution found`

改用已验证的 Termux 包：

```bash
python -m pip install -e '.[termux]' -c constraints-termux.txt
```

当前阻塞原因是 `voice` 扩展：

- `voice` 依赖 `faster-whisper`
- `faster-whisper` 依赖 `ctranslate2`
- `ctranslate2` 未发布 Android wheel 包

### `uv pip install` 在 Android 上失败

改用标准库 venv + `pip` 的 Termux 路径：

```bash
python -m venv venv
source venv/bin/activate
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk)"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[termux]' -c constraints-termux.txt
```

### `jiter` / `maturin` 报错提示缺少 `ANDROID_API_LEVEL`

在安装前显式设置 API 级别：

```bash
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk)"
python -m pip install -e '.[termux]' -c constraints-termux.txt
```

### `hermes doctor` 提示缺少 ripgrep 或 Node

使用 Termux 包安装：

```bash
pkg install ripgrep nodejs
```

### 安装 Python 包时构建失败

确保已安装构建工具链：

```bash
pkg install clang rust make pkg-config libffi openssl
```

然后重试：

```bash
python -m pip install -e '.[termux]' -c constraints-termux.txt
```

---

## 手机上的已知限制 {#known-limitations-on-phones}

- Docker 后端不可用
- 通过 `faster-whisper` 进行的本地语音转录在已验证路径中不可用
- 安装程序有意跳过浏览器自动化配置
- 部分可选扩展可能可用，但目前仅 `.[termux]` 和 `.[termux-all]` 被记录为已验证的 Android 安装包

如果你遇到新的 Android 特定问题，请在 GitHub 上提交 issue，并附上：

- 你的 Android 版本
- `termux-info`
- `python --version`
- `hermes doctor`
- 确切的安装命令及完整错误输出