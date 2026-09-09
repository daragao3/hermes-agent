# 1Password

在进程启动时从 [1Password](https://1password.com/) 解析提供商 API 密钥，而不是以明文形式存储在 `~/.hermes/.env` 中。你将密钥保存为 1Password 条目，并通过 `op://vault/item/field` 引用它们；轮换凭据只需在 1Password 中修改一处即可。

## 工作原理

1. 安装官方 [1Password CLI](https://developer.1password.com/docs/cli/get-started/)（`op`）并完成认证——可以使用**服务账户令牌**（无头服务器），也可以使用**交互式/桌面会话**（你的笔记本电脑）。
2. 在 `~/.hermes/config.yaml` 中把环境变量名映射到 `op://` 引用。
3. 每次 `hermes`（或 gateway，或 cron 任务）启动时，在 `~/.hermes/.env` 加载完成之后，Hermes 会为每个引用执行 `op read`，并将解析出的值写入 `os.environ`。
4. 默认情况下，Hermes 会**覆盖**环境中已有的值，因此 1Password 是唯一可信来源——轮换一次凭据，每个 Hermes 进程在下次启动时即可获取最新值。如果希望 `.env` 优先，可将 `override_existing: false`。

Hermes 从不代表你进行认证，也从不下载 `op`：它只是调用你已安装、已信任的 CLI。如果 `op` 缺失、会话被锁定，或某个引用有误，Hermes 会打印一行警告并继续使用 `.env` 中已有的凭据——它绝不会阻塞启动。

## 认证

`op` 支持两种适合非交互式场景的模式；Hermes 两者都支持：

- **服务账户**（推荐用于服务器/CI）：在 1Password 中创建一个服务账户，授予其对相关保险库的读取权限，并将其令牌以 `OP_SERVICE_ACCOUNT_TOKEN` 的形式导出到 `~/.hermes/.env` 中。该令牌本身就是凭据——请像对待其他 bearer token（持有者令牌）一样对待它。
- **桌面/交互式会话**（笔记本电脑）：运行 `op signin`（或在 1Password 应用中启用 CLI 集成）。Hermes 会将你的 `OP_SESSION_*` 变量传递给 `op` 子进程。1Password 缓存键包含这些会话变量，因此登录到另一个账户时绝不会返回以前身份缓存下来的值。

## 引导令牌

当你使用**服务账户令牌**进行认证时，该令牌本身就是 Hermes 在解析任何 `op://` 引用*之前*所需的引导凭据。它必须存在于每一个解析密钥的进程的 `os.environ` 中——包括 cron 任务（`kanban.dispatch_in_gateway: false`）、子进程调用、CLI 运行、macOS launchd agent 以及 Docker 容器——而不仅仅是交互式 gateway。有三种方式可以让它可用，按优先级排列如下：

1. **放入 `~/.hermes/.env`（推荐）。** `hermes secrets onepassword setup --token <token>` 会将令牌写入 `~/.hermes/.env`，与 Bitwarden 的 `BWS_ACCESS_TOKEN` 完全一致。由于 `load_hermes_dotenv()` 总是会加载 `.env`，该令牌无需任何额外设置即可在各处使用。这是最简单可靠的选项。

2. **放入 `~/.hermes/.op.env`（已被 gitignore）。** 如果你更希望把服务账户令牌排除在 `.env` 之外——例如让 `.env` 可以提交到私有 dotfiles 仓库，而令牌不进入版本控制——可以把它放在 `~/.hermes/.op.env` 中：

   ```bash
   echo 'OP_SERVICE_ACCOUNT_TOKEN=ops_...' > ~/.hermes/.op.env
   chmod 600 ~/.hermes/.op.env
   ```

   Hermes 会在启动时、**在** `.env` 之后自动加载 `.op.env`，并且**绝不**覆盖环境中已有的令牌。`.op.env` 已被 gitignore，因此令牌绝不会进入被提交的文件。

3. **通过 systemd `EnvironmentFile`（Linux gateway）。** 如果你在 systemd 下运行 gateway，可以直接把令牌注入服务环境：

   ```ini
   [Service]
   EnvironmentFile=-/home/youruser/.hermes/.op.env
   ```

   以这种方式注入的令牌具有更高优先级——Hermes 检测到 `OP_SERVICE_ACCOUNT_TOKEN` 已被设置后，会完全跳过加载 `.op.env`。

如果令牌只能通过交互式 shell 获得（`op signin`、在 `.bashrc` 中导出 `OP_SESSION_*` 等），那么 cron 任务或新派生的子进程**不会**继承它，这些环境会记录一条警告并回退到 `.env` 中已有的凭据。对任何非交互式工作负载，请使用上述三种方式之一。

## 设置

### 1. 安装并登录 `op`

参照 [1Password CLI 快速上手指南](https://developer.1password.com/docs/cli/get-started/)。验证其可用：

```bash
op whoami
```

### 2. 启用集成

```bash
hermes secrets onepassword setup
```

该命令会验证 `op` 是否在 `PATH` 上（或使用 `--binary-path`）、记录你的账户/令牌设置、检查是否存在活跃会话，并将 `secrets.onepassword.enabled: true` 打开。非交互式参数：

```bash
hermes secrets onepassword setup \
  --account my.1password.com \
  --token-env OP_SERVICE_ACCOUNT_TOKEN \
  --token "$OP_SERVICE_ACCOUNT_TOKEN"
```

### 3. 映射你的凭据

引用格式为 `op://<vault>/<item>/<field>`：

```bash
hermes secrets onepassword set OPENAI_API_KEY    "op://Private/OpenAI/api key"
hermes secrets onepassword set ANTHROPIC_API_KEY "op://Private/Anthropic/credential"
```

### 4. 预览并确认

```bash
hermes secrets onepassword sync     # dry-run：立即解析，展示将会应用的内容
hermes secrets onepassword status   # 配置 + 二进制文件 + 引用 + 认证
```

此后，每次调用 `hermes` 都会在启动时解析这些引用。进程中首次应用密钥时，你会在 stderr 中看到一行摘要。

## CLI

| 命令 | 作用 |
|---|---|
| `hermes secrets onepassword setup` | 验证 `op`，设置账户/令牌环境变量，启用集成 |
| `hermes secrets onepassword status` | 展示配置、二进制文件、认证以及已配置的引用 |
| `hermes secrets onepassword set ENV_VAR "op://…"` | 将环境变量映射到某个引用（存储时会去除空白并校验） |
| `hermes secrets onepassword remove ENV_VAR` | 删除一条映射 |
| `hermes secrets onepassword sync` | dry-run：立即解析引用并展示将会应用的内容 |
| `hermes secrets onepassword sync --apply` | 解析并导出到当前 shell 的环境中 |
| `hermes secrets onepassword disable` | 置为 `enabled: false`；保留已有映射 |

`op` 和 `1password` 都可以作为 `onepassword` 的别名使用。

## 配置

`~/.hermes/config.yaml` 中的默认值：

```yaml
secrets:
  onepassword:
    enabled: false
    env:
      OPENAI_API_KEY: "op://Private/OpenAI/api key"
      ANTHROPIC_API_KEY: "op://Private/Anthropic/credential"
    account: ""
    service_account_token_env: OP_SERVICE_ACCOUNT_TOKEN
    binary_path: ""
    cache_ttl_seconds: 300
    override_existing: true
```

| 键 | 默认值 | 作用 |
|---|---|---|
| `enabled` | `false` | 总开关。为 false 时绝不会调用 `op`。 |
| `env` | `{}` | 环境变量名 → `op://vault/item/field` 引用的映射。名称不是合法环境变量名、或值不是 `op://` 引用的条目会被跳过并给出警告。 |
| `account` | `""` | 作为 `op read --account` 传入的账户简称/登录地址。留空则使用 `op` 的默认账户。 |
| `service_account_token_env` | `OP_SERVICE_ACCOUNT_TOKEN` | Hermes 从中读取服务账户令牌的环境变量。其值会以 `OP_SERVICE_ACCOUNT_TOKEN`（`op` 期望的名称）导出给 `op` 子进程。不设置该变量则使用桌面/交互式会话。 |
| `binary_path` | `""` | `op` 的绝对路径。设置后会被原样使用，**不会**查询 `PATH`——固定此项可避免信任 `PATH` 上最先出现的任意 `op`。 |
| `cache_ttl_seconds` | `300` | 已解析的值可复用多久（进程内与磁盘上）。设为 `0` 可**同时**禁用两层缓存——不会向磁盘写入任何值。 |
| `override_existing` | `true` | 为 true 时，解析出的值会覆盖环境中已有的内容（因此轮换会生效）。改为 `false` 可让 `.env` / shell 导出优先；这些引用会在调用 `op` *之前*被跳过。 |

## 故障模式

1Password 绝不会阻塞 Hermes 启动。如果出现任何问题，你会在 stderr 中看到一行警告，Hermes 继续运行：

| 现象 | 原因 | 解决方法 |
|---|---|---|
| `the op CLI was not found on PATH` | `op` 未安装／不在 PATH 上 | 安装 CLI，或设置 `secrets.onepassword.binary_path` |
| `op read failed for 'op://…': …` | 会话被锁定、令牌过期，或没有保险库访问权限 | 执行 `op signin`、刷新令牌，或为服务账户授予访问权限 |
| `op read returned an empty value for 'op://…'` | 被引用的字段存在但为空 | 在 1Password 中修正该条目/字段（空值绝不会被应用——你已有的环境变量保持不变） |
| `… is not an op:// secret reference` | 某个映射的值不是 `op://` 引用 | 用正确的 `op://vault/item/field` 形式重新设置 |
| `op read timed out` | 网络被阻断或 1Password 响应缓慢 | 检查网络连通性／桌面应用集成 |

## 缓存

成功且完整的拉取会缓存在进程内以及磁盘上的 `<hermes_home>/cache/op_cache.json`（原子写入，权限 `0600`），因此接连运行的短生命周期 `hermes` 调用不必为每个引用重新调用 `op`。该缓存：

- 只存储已解析的密钥**值**——绝不存储服务账户令牌或任何原始认证材料（认证信息以指纹形式写入缓存键）；
- 在令牌、账户、`OP_SESSION_*` 变量或引用集合发生变化时失效；
- 当某次拉取出现任何单个引用的错误时**不会**被写入，因此瞬时的认证失败不会在整个 TTL 期间被固化下来；
- 在 `cache_ttl_seconds: 0` 时完全禁用——读*和*写都禁用。

## 安全说明

- 1Password 服务账户令牌可以读取该账户有权访问的所有密钥。请将其存储在 `~/.hermes/.env` 中（而非 `config.yaml`），一旦泄露请在 1Password 中吊销并重新生成。
- 即使 `override_existing: true`，Hermes 也会拒绝让解析出的值覆盖令牌环境变量本身。
- `op` 子进程只获得一个最小化的白名单环境（认证/会话变量加上 `PATH`/`HOME`），而不是完整 `os.environ` 的副本，因此加载 dotenv 之后的提供商凭据不会被子进程全部继承。
- 引用会被校验必须以 `op://` 开头，并且引用会在 `--` 选项终止符之后传入，因此精心构造的值无法被解析为 `op` 的参数。

## 不适用场景

- **单机个人配置**，此时 `~/.hermes/.env` 已经足够。
- **物理隔离环境**，无法访问 1Password。
- **CI/CD**，其中已经接入了现成的密钥注入机制——选择一条路径，而不是两条。

真正适合使用它的场景是多机器集群、共享开发机、gateway VPS，或任何你希望在多个 Hermes 安装之间集中轮换和吊销凭据的地方。
