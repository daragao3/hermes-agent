---
title: 终端环境提供商插件
description: "以插件形式为 Hermes 添加第三方终端后端"
---

# 终端环境提供商插件 {#terminal-environment-provider-plugins}

Hermes 通过一组可插拔的**终端后端**运行 shell 命令。
内置后端（local、Docker、Singularity、Modal、Daytona、Vercel
Sandbox、SSH）位于核心仓库的 `tools/environments/` 下。第三方沙箱厂商
则以**插件**形式集成——一个安装在 `~/.hermes/plugins/` 下的独立插件仓库，
注册一个后端，用户可以像选择内置后端一样，通过 `config.yaml` 中的
`terminal.backend` 选择它。

本页与[浏览器提供商插件](/developer-guide/browser-provider-plugin)指南相对应
——相同的注册流程，相同的作用域语义。

## 提供商控制哪些内容 {#what-a-provider-controls}

已注册的后端会自动参与每一个核心界面：

| 界面 | 驱动来源 |
|---|---|
| 命令分发（`terminal`、`execute_code`、文件工具） | `create_environment()` |
| `hermes setup` 后端选择器 | `display_name`、`description`、`setup_instructions()`、`post_setup()` |
| 仪表盘终端后端选择器（探测状态） | `probe()` |
| `hermes status` / `hermes doctor` | `doctor_checks()` |
| 系统 prompt 中的环境提示 | `is_remote`、`env_description` |
| 跳过危险命令审批 | `skip_container_guards` |
| 容器路径/cwd 处理 | `is_container` |
| 同步缓存文件的路径转换 | `cache_path_base` |
| 从派生子进程中剥离密钥 | `strip_env_keys` |
| 按会话隔离沙箱（`container_persistent: false`） | `session_isolated_when_nonpersistent` |

在提供商上声明这些标志，就终结了经典的“新后端漏掉了第 N 处分类位置”这一
类 bug——核心代码在每一处都查询注册表，而不是查一份硬编码的名称列表。

## 最小提供商 {#minimal-provider}

```python title="~/.hermes/plugins/acmebox/__init__.py"
from agent.terminal_env_provider import TerminalEnvironmentProvider


class AcmeBoxEnvironment:
    """Must satisfy the BaseEnvironment duck-typed contract."""

    def __init__(self, cwd, timeout, task_id):
        self.cwd, self.timeout, self.task_id = cwd, timeout, task_id

    def execute(self, command, timeout=None, **kwargs):
        ...  # run the command in the sandbox
        return {"output": "...", "exit_code": 0}

    def cleanup(self):
        ...  # tear down / detach


class AcmeBoxProvider(TerminalEnvironmentProvider):
    name = "acmebox"
    display_name = "AcmeBox"
    is_remote = True          # commands don't run on the host
    is_container = True       # container-style path/cwd semantics

    @property
    def description(self):
        return "Run commands in an AcmeBox cloud sandbox."

    @property
    def cache_path_base(self):
        return "~/.hermes"    # where synced cache files land, or None

    @property
    def strip_env_keys(self):
        return frozenset({"ACMEBOX_TOKEN"})

    def is_available(self):
        import importlib.util, os
        return (
            importlib.util.find_spec("acmebox") is not None
            and bool(os.getenv("ACMEBOX_TOKEN"))
        )

    def create_environment(self, *, cwd, timeout, task_id="default",
                           image=None, container_config=None, **kwargs):
        return AcmeBoxEnvironment(cwd, timeout, task_id)


def register(ctx):
    ctx.register_terminal_environment_provider(AcmeBoxProvider())
```

```yaml title="~/.hermes/plugins/acmebox/plugin.yaml"
name: acmebox
version: 0.1.0
description: AcmeBox cloud sandbox terminal backend
kind: backend
```

启用、选择、运行：

```bash
hermes plugins enable acmebox
hermes config set terminal.backend acmebox
```

## 规则 {#rules}

- **保留名称。** 与内置后端名称冲突的注册
  （`local`、`docker`、`singularity`、`modal`、`managed_modal`、`daytona`、
  `vercel_sandbox`、`ssh`）会被拒绝。插件扩展后端集合；它们
  绝不会遮蔽树内后端。
- **`create_environment` 必须接受 `**kwargs`** 并忽略未知键——
  这是向前兼容的约定，使工厂签名可以演进而不破坏旧插件。
- **`is_available()` / `probe()` 必须廉价。** 不得发起网络调用——它们会在
  需求检查和 UI 绘制期间运行。
- **处处软失败。** 抛出异常的提供商属性会被核心视为其默认值
  （例如，抛出异常的 `skip_container_guards` 会让审批层保持开启）。不要依赖
  异常来控制流程。
- **密钥应放进 `strip_env_keys`。** 你的厂商 token 绝不能被模型编写的 shell
  命令读取；将其列入后，它会被无条件地从每个派生的子进程中剥离，就像内置的
  `MODAL_*` / `DAYTONA_API_KEY` 处理那样。

## 环境对象约定 {#environment-object-contract}

`create_environment()` 返回一个满足与
`tools.environments.base.BaseEnvironment` 相同鸭子类型接口的对象：

- `execute(command, timeout=None, ...)` → `{"output": str, "exit_code": int}`
- `cleanup()` —— 释放资源；在会话销毁 / 空闲回收时调用
- 可选：与内置云后端相对应的持久化 hook

建议继承 `BaseEnvironment`（这样你可以继承共享的文件同步和后台进程管道），
但不是必需的。

## 会话隔离语义 {#session-isolation-semantics}

如果你的沙箱是**按名称恢复**的（后端会重新连接的持久 VM），请设置
`session_isolated_when_nonpersistent = True`。在
`terminal.container_persistent: false` 下，每个会话随后都会获得自己的
沙箱身份，而不是共享同一个——否则，两个独立的临时运行可能会连接到同一个
活跃 VM，并在对方毫不知情的情况下把它删除。
