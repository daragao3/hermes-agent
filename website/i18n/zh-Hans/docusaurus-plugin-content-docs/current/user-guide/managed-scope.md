---
sidebar_position: 3
title: "托管作用域"
description: "通过系统级托管目录实现管理员固定、用户不可更改的配置与密钥"
---

# 托管作用域

**托管作用域（managed scope）** 让管理员能够推送一份标准（非 root）用户**无法覆盖**的
配置与密钥基线。它面向车队/组织部署场景，例如 IT 需要在一台机器上为每个用户统一固定
模型提供商、共享的 API base URL，或 `security.redact_secrets: true`。

当存在托管作用域时，对于它所固定的那些键，其取值会优先于用户的
`~/.hermes/config.yaml`、`~/.hermes/.env`，乃至 shell 环境。其余一切仍完全由用户控制。

:::note 与包管理器锁定的安装不同
包管理器托管的安装（declarative-distro / formula）会阻止*所有*配置更改，并告诉你改用
你的包管理器。托管作用域是一种独立机制：它以逐键为粒度注入*特定的不可变取值*，而不是
锁定整份配置。两者彼此独立，可以共存。
:::

## 它位于何处

托管作用域从一个系统级目录读取，默认为 `/etc/hermes`：

```text
/etc/hermes/
├── config.yaml     # 托管配置层（优先于 ~/.hermes/config.yaml）
└── .env            # 托管环境层（优先于 ~/.hermes/.env + shell）
```

该目录和文件归 `root` 所有（目录模式 `0755`，文件 `0644`）：所有人可读，仅管理员可写。
**该文件系统权限就是强制执行机制** —— 标准用户可以读取托管文件，但无法编辑它们。

任一文件都是可选的。缺失的托管目录或缺失的文件仅仅表示"无托管作用域"，此时配置的解析
方式与未启用该特性时完全一致。

### 重定位该目录

可以用环境变量 `HERMES_MANAGED_DIR` 重定位该位置（用于容器或非 `/etc` 部署）。这是一个
部署/引导路径旋钮 —— 与 `HERMES_HOME` 类似 —— 由拥有托管文件的同一位管理员设置。它
**永远不会**被 Hermes 持久化到任何 `.env`。

```bash
# 将托管作用域指向自定义目录（由 IT / 部署方设置，而非用户）
export HERMES_MANAGED_DIR=/opt/org/hermes-policy
```

:::warning
能够设置 `HERMES_MANAGED_DIR` 的用户可以把托管作用域重新指向他们自己控制的目录，从而
使其失效。在真实部署中，该变量应由管理员固定（例如烘焙进 service unit / 容器镜像），而
不是留给用户可设置。`hermes doctor` 会报告*解析后*的托管目录，因此任何重定向都可见。
:::

## 优先级

对于托管层所指定的那些键，顺序为（最高者胜出）：

| 层级 | config.yaml | .env |
|---|---|---|
| 1 | `/etc/hermes/config.yaml`（托管） | `/etc/hermes/.env`（托管） |
| 2 | `~/.hermes/config.yaml`（用户） | `~/.hermes/.env`（用户） |
| 3 | 内置默认值 | 既有的 shell 环境 |

合并是**叶子级**的：固定 `model.default` 并不会冻结 `model.*` 的其余部分。一份如下的
托管 `config.yaml`：

```yaml
model:
  default: org/standard-model
```

会为每个用户强制 `model.default`，同时把 `model.fallback`（以及其他每个键）留给用户控制。

:::note 优先级说明
对于它所固定的键，托管作用域刻意也优先于 shell 环境 —— 否则它就算不上"托管"了。这是
唯一一处反转了通常"环境变量覆盖 config.yaml"规则的地方，且仅适用于托管层所指定的那些
特定键。
:::

## 查看哪些内容被托管

```bash
hermes config        # 显示一个标注托管来源 + 已固定键的表头
hermes doctor        # 报告解析后的托管目录 + 已固定键的数量
```

如果你尝试更改某个托管值，Hermes 会拒绝并指出其来源：

```bash
$ hermes config set model.default my/model
Cannot set 'model.default': it is managed by your administrator
(/etc/hermes/config.yaml) and cannot be changed.
```

对托管密钥同样适用 —— 对于被托管 `.env` 固定的某个环境键，`hermes config set` / setup
不会写入用户值。

## 设置托管作用域（管理员）

```bash
sudo mkdir -p /etc/hermes

# 为这台机器上的每个用户固定一些配置值
sudo tee /etc/hermes/config.yaml >/dev/null <<'YAML'
model:
  provider: nous
security:
  redact_secrets: true
YAML

# 可选地固定一个共享的、非敏感的环境值
sudo tee /etc/hermes/.env >/dev/null <<'ENV'
OPENAI_API_BASE=https://inference.example.com/v1
ENV

sudo chmod 0755 /etc/hermes
sudo chmod 0644 /etc/hermes/config.yaml /etc/hermes/.env
```

更改会在下次 Hermes 启动时生效（格式错误的托管文件会被大声记录并忽略 —— 它绝不会阻止
启动，但管理员应检查 `hermes doctor` 以确认策略正在被应用）。

## 安全模型与限制（v1）

- **强制执行仅依赖文件系统权限。** 如果用户对托管目录有写入权限（或以 `root` 身份运行
  Hermes），托管作用域便只是建议性的。
- **托管的 `.env` 是全局可读的**（`0644`），因此任何本地用户都能读取通过它推送的密钥。
  应把它用于共享的、非敏感的值（组织 API base URL、功能默认值），而非高敏感度密钥。
- **agent 自身的工具并未被从某个托管*环境*值中硬阻断。** 托管环境变量在启动时被应用，但
  没有任何东西阻止 agent 在它自己的子进程 shell 内设置一个不同的值。v1 是针对普通用户的
  管理便利边界，而非一个不可逃逸的沙箱。

以下内容刻意**排除在 v1 之外**，可能会在以后加入：

- agent 自身也无法逃逸的硬边界。
- macOS 和 Windows 上的原生托管位置（v1 以 Linux/POSIX 为先）。
- 用于分层策略的插入式片段目录（`managed.d/`）。
- 签名 / 完整性校验的托管文件。
- 远程 / 设备管理（MDM）分发。
- 对托管密钥更严格（按组作用域）的权限。
