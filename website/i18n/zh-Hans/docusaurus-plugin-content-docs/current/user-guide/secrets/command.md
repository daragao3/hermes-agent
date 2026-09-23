---
title: 命令助手密钥源
description: "启动时运行你自己的助手命令，从任意提供 CLI 的密钥存储中解析凭据"
---

# 命令助手密钥源

在启动时运行你自己的助手命令来解析凭据——任何带有 CLI 的密钥存储都可以使用：`keepassxc-cli`、`secret-tool`（GNOME Keyring）、`pass`、`gpg`、Vaultwarden 的 CLI，或是一个 cat 某个 tmpfs env 文件的脚本。助手在 stdout 上打印 `KEY=VALUE` 行；Hermes 通过与 [Bitwarden](./bitwarden) 和 [1Password](./onepassword) 相同的编排器应用这些值，因此你可以同时启用任意组合的密钥源。

## 工作原理 {#how-it-works}

1. 你在 `config.yaml` 中配置一个助手命令（绝不要放在 `.env` 中——命令属于配置，`.env` 存放的是值）。
2. 启动时，在 `.env` 加载之后，Hermes 通过 `/bin/sh -c` 运行该助手**一次**，并将其 stdout 解析为 dotenv 内容。
3. 解析出的键遵循标准的优先级阶梯：除非设置 `override_existing: true`，否则 `.env`/shell 优先；在有争议的变量上，映射型密钥源优先于这种批量密钥源；先声明者胜出。

```yaml
secrets:
  command:
    enabled: true
    command: "cat /run/user/1000/hermes-secrets.env"
    # or any vault CLI that dumps KEY=VALUE lines:
    # command: "pass show hermes/env"
    # command: "secret-tool lookup service hermes-env"
```

## 配置 {#config}

| 键 | 默认值 | 作用 |
|---|---|---|
| `enabled` | `false` | 总开关。 |
| `command` | `""` | 通过 `/bin/sh -c` 运行的助手；必须在 stdout 上打印 `KEY=VALUE` 行。 |
| `helper_timeout_seconds` | `3` | 单次助手运行的硬超时。刻意设得很紧——助手必须快速且**非**交互（不能有解锁提示，不能要求触摸/PIN）。 |
| `override_existing` | `false` | 助手的值覆盖 `.env`/shell 中的值。默认关闭（与 Bitwarden/1Password 不同），因为本地助手并不是集中的轮换权威。 |

## 安全模型 {#security-model}

- 助手命令字符串是**你自己的**配置——与你所控制的 `.env` 文件处于相同的信任级别。
- 输出硬性上限为 1 MiB；失控的助手无法卡住启动过程（超时时会杀掉整个进程组）。
- 助手的 **stderr 会被丢弃**——密钥库 CLI 的诊断信息可能携带密钥内容，因此它们绝不会进入 Hermes 的输出。失败时只记录结构化字段（退出码 / 信号 / errno），绝不记录命令字符串。
- 仅含空白的值被视为"无值"——占位条目绝不会流入 Authorization 头。
- 仅限 POSIX（需要 `/bin/sh`）。在 Windows 上该密钥源会报告自身未配置，启动照常继续。

## 故障模式 {#failure-modes}

启动绝不会被阻塞。错误会打印一行信息外加一个 `→` 修复提示：

| 症状 | 原因 | 修复 |
|---|---|---|
| `secrets.command.command is empty` | 已启用但未设置命令 | 在 config.yaml 中设置 `secrets.command.command` |
| `helper command failed` | 非零退出、超时、启动失败 | 在 shell 中手动运行该助手以查看真实错误（Hermes 会刻意丢弃其 stderr） |
| `helper output was not a KEY=VALUE map` | 助手打印了裸值或无效内容 | 让助手输出 dotenv 格式的行 |

## 何时使用它，何时使用插件 {#when-to-use-this-vs-a-plugin}

命令密钥源是为没有内置集成的密钥库准备的逃生通道。如果你发现自己在一个长脚本里包装复杂的 CLI 操作流程，不妨改用正规的 [密钥源插件](/developer-guide/secret-source-plugin)——插件提供缓存、来源标签和类型化配置。
