---
sidebar_position: 9
title: "密钥源插件"
description: "如何为 Hermes Agent 构建一个 secret-manager 后端插件"
---

# 构建密钥源插件

密钥源（secret source）在进程启动时把供应商凭证从外部密钥管理器（vault、密码管理器、操作系统密钥库、自定义脚本）解析到环境变量中——在 `~/.hermes/.env` 加载之后、Hermes 读取凭证之前。Bitwarden 和 1Password 内置于代码树中；**其他所有后端都是插件**。本指南介绍如何构建一个。

:::tip
内置集合是刻意封闭的，与[记忆提供方](/developer-guide/memory-provider-plugin)的策略一致：在 `agent/secret_sources/` 下新增 vault 后端的 PR 会被关闭，并附上指向本指南的链接。请把你的后端作为独立插件仓库发布，并在 Nous Research Discord（`#plugins-skills-and-skins`）中分享。
:::

## 框架负责什么 vs. 你负责什么

编排器（`agent.secret_sources.registry.apply_all`）掌管所有与安全性和优先级相关的部分，因此后端不可能把它做错：

| 框架负责 | 你负责 |
|---|---|
| 源的排序、mapped 与 bulk 之间的优先级 | 从你的后端拉取值 |
| 先到先得的冲突处理 + 警告 | 校验你的引用格式 |
| `override_existing` 语义（永不跨源生效） | 与你的 CLI/SDK/API 通信 |
| 受保护的引导 token | 声明哪个环境变量是你的引导 token |
| 每个源的墙钟超时 | 保持 `fetch()` 足够快 |
| 每个变量的来源追踪 + `(from X)` 标签 | 一个人类可读的 `label` |
| `os.environ` 写入 | 无——你永远不碰环境变量 |

## 目录结构

```
~/.hermes/plugins/my-vault/
├── plugin.yaml      # name, description
└── __init__.py      # SecretSource subclass + register(ctx)
```

## SecretSource 抽象基类

实现 `agent.secret_sources.base.SecretSource`。只有一个方法是必需的：

```python
from pathlib import Path

from agent.secret_sources.base import (
    ErrorKind,
    FetchResult,
    SecretSource,
    run_secret_cli,
)


class MyVaultSource(SecretSource):
    name = "myvault"          # config section key: secrets.myvault
    label = "My Vault"        # used in startup lines + provenance labels
    shape = "mapped"          # "mapped" (explicit VAR→ref map) or "bulk" (project dump)
    scheme = "mv"             # optional: unique URI scheme you own (mv://...)

    def fetch(self, cfg: dict, home_path: Path) -> FetchResult:
        """Resolve secrets. MUST NOT raise. MUST NOT prompt."""
        result = FetchResult()
        token = os.environ.get("MYVAULT_TOKEN", "").strip()
        if not token:
            result.error = "secrets.myvault.enabled is true but MYVAULT_TOKEN is not set."
            result.error_kind = ErrorKind.NOT_CONFIGURED
            return result

        try:
            proc = run_secret_cli(
                ["myvault-cli", "export", "--json"],
                allow_env=["MYVAULT_TOKEN"],   # ONLY your auth vars — never full os.environ
                timeout=30,
            )
        except RuntimeError as exc:           # spawn failure / timeout
            result.error = str(exc)
            result.error_kind = ErrorKind.BINARY_MISSING
            return result

        if proc.returncode != 0:
            result.error = f"myvault-cli exited {proc.returncode}: {proc.stderr[:200]}"
            result.error_kind = ErrorKind.AUTH_FAILED
            return result

        result.secrets = parse_your_output(proc.stdout)  # {ENV_VAR: value}
        return result

    def protected_env_vars(self, cfg: dict):
        # Your bootstrap token — no source (including yours) may ever overwrite it.
        return frozenset({"MYVAULT_TOKEN"})
```

### 契约规则（强制执行，而非建议）

- **`fetch()` 绝不抛异常。** 错误写入 `result.error` + `result.error_kind`。抛异常的 fetch 会被编排器兜住并报告为 `INTERNAL`——这是违反契约，不是特性。
- **`fetch()` 绝不提示输入。** 启动过程运行在非 TTY 环境中（gateway、cron、Docker）。`run_secret_cli()` 会关闭 stdin，因此会提示输入的辅助程序会快速失败。交互式认证应放在你的 CLI 配置流程中，绝不能放在启动路径上。
- **同步执行，控制在预算内。** 编排器强制执行墙钟超时（默认 120 秒，用户可通过 `secrets.<name>.timeout_seconds` 调整）。超时会报告 `TIMEOUT`，并丢弃你的结果。
- **你负责获取；编排器负责应用。** 返回你*本应*贡献的映射。绝不要自己写 `os.environ`——那样会绕过优先级、冲突检测和来源追踪。
- **API 版本管理。** `SecretSource.api_version` 默认为当前的 `SECRET_SOURCE_API_VERSION`。对于针对不同版本构建的源，注册表会跳过（并给出警告），而不是让启动崩溃。

### 选择你的 `shape`

- `mapped` —— 用户在配置中显式地把环境变量名绑定到引用（类似 1Password 的 `env:` 映射）。意图最强：在有争议的变量上，mapped 声明优先于 bulk 声明。
- `bulk` —— 你隐式地注入整个项目/文件夹的密钥（类似 Bitwarden BSM）。会让位于 mapped 源。

### 可选钩子

| 方法 | 默认值 | 何时覆盖 |
|---|---|---|
| `is_enabled(cfg)` | `cfg.get("enabled")` | 自定义激活逻辑 |
| `override_existing(cfg)` | `cfg.get("override_existing", False)` | 你想要不同的默认值（两个内置源为了轮换默认为 `True`） |
| `protected_env_vars(cfg)` | 空 | 你有一个引导 token（你几乎肯定有） |
| `fetch_timeout_seconds(cfg)` | 120 秒 | 你的后端需要不同的预算 |
| `config_schema()` | `{}` | 为配置界面声明配置键 |

## 子进程安全：使用 `run_secret_cli()`

如果你的后端要调用外部 CLI，请使用这个共享辅助函数，而不是直接用 `subprocess.run`。它免费提供了经过审计的安全姿态：仅使用 argv（不用 `shell=True`）、**最小化的白名单子进程环境**（源运行时，`os.environ` 中已经装着 Hermes 知道的每一个凭证——绝不能把它整个交给子进程）、`NO_COLOR` + 清除 ANSI 的 stderr、关闭 stdin、超时转为干净的 `RuntimeError`。请把用户提供的引用字符串放在 argv 中 `--` 终止符之后，这样它们永远不会被解析成 flag。

## 注册

```python
# __init__.py
def register(ctx):
    ctx.register_secret_source(MyVaultSource())
```

以下情况注册会被拒绝（记录一条警告日志，绝不崩溃）：非 `SecretSource` 实例、名称无效或重复、`scheme` 已被其他源占用、`api_version` 不正确，或 `shape` 不在 `mapped`/`bulk` 之内。

:::note 时机
插件发现发生在启动流程中比首次 `load_hermes_dotenv()` 调用更晚的位置，因此发现插件的那个进程在首次加载环境变量时不会咨询插件源。但之后派生的每个 Hermes 进程（gateway 子进程、cron 会话、subagent）都会咨询它。首个进程的引导由内置源覆盖。
:::

## 用户像配置其他源一样配置它

```yaml
secrets:
  sources: [myvault, bitwarden]   # optional ordering
  myvault:
    enabled: true
    # ... your config_schema keys
```

多源优先级、冲突警告以及 `(from My Vault)` 来源标签都会自动生效——优先级阶梯参见[面向用户的密钥文档](/user-guide/secrets/)。

## 用一致性测试套件验证

在你插件的测试中继承 Hermes 仓库里的测试套件（`tests/secret_sources/conformance.py`）：

```python
import pytest
from tests.secret_sources.conformance import SecretSourceConformance

class TestMyVaultConformance(SecretSourceConformance):
    @pytest.fixture
    def source(self):
        return MyVaultSource()
```

它检查那些一旦违反就会影响他人的规则：配置格式错误时绝不抛异常、机器可读的错误类型、默认禁用、正数超时、受保护变量名有效，以及一次完整的 `apply_all()` 往返。通过一致性测试是把一个后端称为「契约合规」的评审门槛。

## ErrorKind 参考

| 类型 | 含义 |
|---|---|
| `NOT_CONFIGURED` | 已启用但缺少 token / 项目 / 映射 |
| `BINARY_MISSING` | 未找到辅助 CLI，或它不可执行 |
| `AUTH_FAILED` / `AUTH_EXPIRED` | 凭证错误 / 已过期 |
| `REF_INVALID` | 某个密钥引用未通过校验 |
| `NETWORK` | 传输层失败 |
| `EMPTY_VALUE` | 后端对某个引用返回了空值——绝不要用 `""` 覆盖一个有效凭证 |
| `TIMEOUT` | 获取超出预算 |
| `INTERNAL` | 其他任何情况（bug、意外的数据形状） |
