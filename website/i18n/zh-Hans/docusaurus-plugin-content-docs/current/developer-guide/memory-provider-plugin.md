---
sidebar_position: 8
title: "Memory Provider 插件"
description: "如何为 Hermes Agent 构建 memory provider 插件"
---

# 构建 Memory Provider 插件

Memory provider 插件为 Hermes Agent 提供跨会话的持久化知识，超越内置的 MEMORY.md 和 USER.md。本指南介绍如何构建一个 memory provider 插件。

:::tip
Memory provider 是两种 **provider 插件**类型之一。另一种是 [Context Engine 插件](/developer-guide/context-engine-plugin)，用于替换内置的上下文压缩器。两者遵循相同的模式：单选、配置驱动、通过 `hermes plugins` 管理。
:::

## 安装布局 {#installation-layouts}

Hermes 从四个来源发现 memory provider，优先级顺序如下：

| 来源 | 位置 | 说明 |
|---|---|---|
| 内置 | `plugins/memory/<name>/` | 随 Hermes 一同发布。不再接受新的 provider——参见 [CONTRIBUTING](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)。 |
| 用户 | `$HERMES_HOME/plugins/<name>/` | 由用户放入，按 profile 隔离。 |
| 项目 | `./.hermes/plugins/<name>/` | 通过 `HERMES_ENABLE_PROJECT_PLUGINS=1` 选择启用。 |
| 包 | `hermes_agent.memory_providers` 入口点 | `pip install` 即可，无需复制任何文件。 |

名称冲突时排在前面的来源胜出，因此放进工作树中的目录永远无法遮蔽随 Hermes 发布的 provider。

:::note
这与通用插件系统“后者胜出”的顺序相反。memory provider 是按*名称*（`memory.provider`）激活的，因此遮蔽会悄无声息地重定向 agent 的记忆，而不仅仅是覆盖某个工具。
:::

发现过程只做*枚举*——它从不导入任何 provider。在 `memory.provider` 指定它之前，什么都不会运行。

### 目录形式的 Provider {#directory-provider}

目录形式的 provider 随 Hermes 内置时位于 `plugins/memory/<name>/`，由用户安装时位于 `$HERMES_HOME/plugins/<name>/`，项目本地的则位于 `./.hermes/plugins/<name>/`：

```
plugins/memory/my-provider/
├── __init__.py      # MemoryProvider 实现 + register() 入口点
├── plugin.yaml      # 元数据（name、description、hooks）
└── README.md        # 配置说明、配置参考、工具
```

### 打包形式的 Provider {#packaged-provider}

通过 pip 安装的 provider 会在 `hermes_agent.memory_providers` 组中发布一个入口点。入口点的名称就是用户在 `memory.provider` 中选择的 provider 名称；其值指向 provider 的 `register(ctx)` 函数：

```toml title="pyproject.toml"
[project.entry-points."hermes_agent.memory_providers"]
my-provider = "my_provider:register"
```

让入口点指向**包**，或指向包内的 `register(ctx)`，并将你的实现、技能和其他资源按常规的 Python 包布局组织。无需在 `$HERMES_HOME/plugins/` 下放置任何副本。

包入口点能获得目录安装所能获得的一切，包括 Hermes 从磁盘读取而非导入的两个文件——`config_schema.py`（仪表盘配置面板）和 `cli.py`（你的 `hermes <provider>` 子命令）。两者都会在你的包的 `__init__.py` 旁边被找到，因此如果你提供了其中任何一个，请让入口点指向一个包，而不是单个模块。

## MemoryProvider 抽象基类 {#the-memoryprovider-abc}

你的插件需要实现 `agent/memory_provider.py` 中的 `MemoryProvider` 抽象基类（ABC）：

```python
from agent.memory_provider import MemoryProvider

class MyMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "my-provider"

    def is_available(self) -> bool:
        """检查此 provider 是否可以激活。禁止发起网络请求。"""
        return bool(os.environ.get("MY_API_KEY"))

    def initialize(self, session_id: str, **kwargs) -> None:
        """在 agent 启动时调用一次。

        kwargs 始终包含：
          hermes_home (str): 当前活跃的 HERMES_HOME 路径。用于存储数据。
        """
        self._api_key = os.environ.get("MY_API_KEY", "")
        self._session_id = session_id

    # ... 实现其余方法
```

## 必须实现的方法 {#required-methods}

### 核心生命周期 {#core-lifecycle}

| 方法 | 调用时机 | 是否必须实现？ |
|--------|-----------|-----------------|
| `name`（property） | 始终 | **是** |
| `is_available()` | agent 初始化，激活前 | **是** — 禁止网络请求 |
| `initialize(session_id, **kwargs)` | agent 启动 | **是** |
| `get_tool_schemas()` | 初始化后，用于注入工具 | **是** |
| `handle_tool_call(tool_name, args, **kwargs)` | agent 调用你的工具时 | **是**（如果有工具） |

### 配置 {#config}

| 方法 | 用途 | 是否必须实现？ |
|--------|---------|-----------------|
| `get_config_schema()` | 为 `hermes memory setup` 声明配置字段 | **是** |
| `save_config(values, hermes_home)` | 将非敏感配置写入原生位置 | **是**（除非仅使用环境变量） |

### 可选 Hook {#optional-hooks}

| 方法 | 调用时机 | 使用场景 |
|--------|-----------|----------|
| `system_prompt_block()` | 系统 prompt 组装时 | 静态 provider 信息 |
| `prefetch(query, *, session_id="")` | 每次 API 调用前 | 返回召回的上下文 |
| `queue_prefetch(query, *, session_id="")` | 每轮对话结束后 | 为下一轮预热 |
| `sync_turn(user, assistant, *, session_id="", messages=None)` | 每轮对话完成后 | 持久化对话内容 |
| `on_session_end(messages)` | 对话结束时 | 最终提取/刷新 |
| `on_pre_compress(messages)` | 上下文压缩前 | 在丢弃前保存关键信息 |
| `on_memory_write(action, target, content)` | 内置 memory 写入时 | 同步到你的后端 |
| `shutdown()` | 进程退出时 | 清理连接 |

### 超大的预取结果 {#oversized-prefetch-results}

外部 `prefetch()` 返回的结果若超过配置的溢出阈值，会被写入一个私有的溢出文件，并替换为按配置生成的首尾预览。预览中包含该文件路径，以便 agent 在真正需要时读取完整结果。等于或低于阈值的结果会原样返回。

这使用共享的 `hooks.output_spill` 设置（默认 `10,000` 个字符）；参见[插件——超大上下文溢出](/developer-guide/plugins/#oversized-context-spill)。

## 压缩前检查点（失败即关闭） {#pre-compress-checkpoints-fail-closed}

`on_pre_compress()` 默认是尽力而为的：如果你的 provider 抛出异常，宿主会记录失败并继续压缩。对于提取关键信息而言，这是正确的默认行为——但对于一个职责是在有损重写*之前*把对话记录证据归档到持久存储的 provider 来说，这就是错误的默认行为。针对这种情况，宿主提供了一个需要选择加入的检查点契约（API v2）：

```python
from agent.memory_provider import MemoryProvider

class MyArchivingProvider(MemoryProvider):
    # 选择加入：每一次 on_pre_compress() 成功返回，都意味着持久化检查点
    # 已经提交。出现任何失败都要抛出异常——不要返回部分成功。版本 1
    # （继承的默认值）是隐式的历史契约：尽力而为的语义，原始消息列表。
    pre_compress_checkpoint_api_version = 2

    def on_pre_compress(self, messages, *, require_checkpoint=False):
        # require_checkpoint 对应运维人员的 checkpoint_required 设置：
        # 为 True 时，在这里抛出异常会阻止有损重写。
        ids = self._archive(messages)   # 返回前必须已持久化
        return f"checkpoint: {ids}"     # 会被转发进摘要 prompt
```

运维人员按部署启用强制检查：

```yaml
compression:
  checkpoint_required: true   # 默认：false
```

开启该关卡后，除非某个声明了此 API 的活跃 provider 完成了检查点，否则压缩会在任何有损重写之前**失败即关闭**：未压缩的对话记录会被保留，压缩尝试会以 `BLOCKED_MISSING_PREREQUISITE` 报错，并且可以在你的存储恢复后重试。关闭该关卡时（默认），现有 provider 不受任何影响。

该关卡约束的是每一个压缩主体，而不只是 Hermes 的摘要器：关卡启用期间，服务端原生压缩（`compression.codex_responses_native`）会被抑制；轮次结束后的微压缩（`compression.micro_compact`）会在 agent 初始化时被强制关闭（它会把旧的交互并入滚动摘要，而其路径上没有检查点 hook）；`codex_app_server` API 模式会在 agent 初始化时被拒绝——codex agent 会自行压缩它的线程，没有真实可信的压缩前边界，因此在那里无法保证必需的检查点。具备检查点意识的 Hermes 压缩器仍是唯一的有损主体。

你的 provider 收到什么，取决于它声明的 API 版本。版本 1 的 provider（隐式默认值——所有既有的 provider）保留历史契约：原始消息列表，与以前完全相同。版本 2 的检查点 provider 则会收到规范化的直接证据：只有 user/assistant 的文本行——工具结果、系统消息、assistant 消息中的 `tool_calls` 负载（其文字内容会保留）以及之前的压缩摘要，都会在宿主侧被过滤掉。之前的摘要通过一个持久的 `_compressed_summary` 消息标记来识别，该标记在进程重启后依然有效，因此恢复的会话永远不会把衍生摘要回灌进你的归档。

**检查点必须是幂等的。** 在一次失败即关闭的阻断之后，下一次压缩尝试会用同样的对话记录再次调用 `on_pre_compress()`——而一段只增长了一点点的对话记录会产生大量重叠的证据。请按内容（例如对话记录摘要值）为归档写入设定键并执行 upsert，让重试和重叠内容去重，而不是累积出重复的归档。

契约测试：`tests/agent/test_pre_compress_checkpoint_contract.py`。

## 配置 Schema {#config-schema}

`get_config_schema()` 返回一个字段描述符列表，供 `hermes memory setup` 使用：

```python
def get_config_schema(self):
    return [
        {
            "key": "api_key",
            "description": "My Provider API key",
            "secret": True,           # → 写入 .env
            "required": True,
            "env_var": "MY_API_KEY",   # 显式指定环境变量名
            "url": "https://my-provider.com/keys",  # 获取密钥的地址
        },
        {
            "key": "region",
            "description": "Server region",
            "default": "us-east",
            "choices": ["us-east", "eu-west", "ap-south"],
        },
        {
            "key": "project",
            "description": "Project identifier",
            "default": "hermes",
        },
    ]
```

`secret: True` 且带有 `env_var` 的字段写入 `.env`。非敏感字段传递给 `save_config()`。

:::tip 最简 Schema 与完整 Schema
`get_config_schema()` 中的每个字段都会在 `hermes memory setup` 期间提示用户输入。选项较多的 provider 应保持 schema 精简——只包含用户**必须**配置的字段（API key、必要凭证）。可选配置请在配置文件参考文档中说明（例如 `$HERMES_HOME/myprovider.json`），而不是在 setup 向导中逐一提示。这样既能保持 setup 流程简洁，又支持高级配置。可参考 Supermemory provider 的实现——它只提示输入 API key，其余选项均位于 `supermemory.json` 中。
:::

## 保存配置 {#save-config}

```python
def save_config(self, values: dict, hermes_home: str) -> None:
    """将非敏感配置写入原生位置。"""
    import json
    from pathlib import Path
    config_path = Path(hermes_home) / "my-provider.json"
    config_path.write_text(json.dumps(values, indent=2))
```

对于仅使用环境变量的 provider，保留默认的空实现即可。

## 插件入口点 {#plugin-entry-point}

```python
def register(ctx) -> None:
    """由 memory 插件发现系统调用。"""
    ctx.register_memory_provider(MyMemoryProvider())
```

provider 还可以在同一个回调中暴露只读技能。技能以入口点名称作为限定前缀，并且只有在该 memory provider 处于活跃状态时才会加载：

```python
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"

def register(ctx) -> None:
    ctx.register_memory_provider(MyMemoryProvider())
    ctx.register_skill(
        "maintenance",
        SKILLS_DIR / "maintenance" / "SKILL.md",
        "Maintain the provider's memory store",
    )
```

当 `my-provider` 入口点处于活跃状态时，该技能可通过 `skill_view()` 以 `my-provider:maintenance` 的形式使用。

## plugin.yaml

```yaml
name: my-provider
version: 1.0.0
description: "此 provider 功能的简短描述。"
hooks:
  - on_session_end    # 列出你实现的 hook
```

## 线程约定 {#threading-contract}

**`sync_turn()` 必须是非阻塞的。** 如果你的后端存在延迟（API 调用、LLM 处理），请在守护线程中执行：

```python
def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None):
    def _sync():
        try:
            self._api.ingest(user_content, assistant_content, session_id=session_id, messages=messages)
        except Exception as e:
            logger.warning("Sync failed: %s", e)

    if self._sync_thread and self._sync_thread.is_alive():
        self._sync_thread.join(timeout=5.0)
    self._sync_thread = threading.Thread(target=_sync, daemon=True)
    self._sync_thread.start()
```

`messages` 是可选参数，为截至本轮完成时的 OpenAI 风格对话上下文。存在时，它包含 user/assistant 消息、assistant 的工具调用以及工具结果消息。不需要原始轮次上下文的 provider 可以省略 `messages` 参数；Hermes 会继续以旧签名调用它们。

云端 provider 应说明 `messages` 中的哪些部分会被发送到设备之外。工具调用和工具结果可能包含文件路径、命令输出或其他工作区数据。

## Profile 隔离 {#profile-isolation}

所有存储路径**必须**使用 `initialize()` 中的 `hermes_home` kwarg，而不是硬编码的 `~/.hermes`：

```python
# 正确 — 按 profile 隔离
from hermes_constants import get_hermes_home
data_dir = get_hermes_home() / "my-provider"

# 错误 — 所有 profile 共享
data_dir = Path("~/.hermes/my-provider").expanduser()
```

## 测试 {#testing}

端到端测试模式请参见 `tests/agent/test_memory_provider.py` 及相邻的记忆相关测试（`tests/agent/test_memory_session_switch.py`、`tests/agent/test_memory_user_id.py`、`tests/run_agent/test_memory_provider_init.py`）。

```python
from agent.memory_manager import MemoryManager

mgr = MemoryManager()
mgr.add_provider(my_provider)
mgr.initialize_all(session_id="test-1", platform="cli")

# 测试工具路由
result = mgr.handle_tool_call("my_tool", {"action": "add", "content": "test"})

# 测试生命周期
mgr.sync_all("user msg", "assistant msg")
mgr.on_session_end([])
mgr.shutdown_all()
```

## 添加 CLI 命令 {#adding-cli-commands}

Memory provider 插件可以注册自己的 CLI 子命令树（例如 `hermes my-provider status`、`hermes my-provider config`）。这套系统基于约定发现，无需修改核心文件。

### 工作原理 {#how-it-works}

1. 在插件目录中添加 `cli.py` 文件
2. 定义 `register_cli(subparser)` 函数来构建 argparse 树
3. memory 插件系统在启动时通过 `discover_plugin_cli_commands()` 自动发现
4. 你的命令以 `hermes <provider-name> <subcommand>` 的形式出现

**仅对活跃 provider 开放：** 你的 CLI 命令只在你的 provider 是配置中活跃的 `memory.provider` 时才会出现。如果用户尚未配置你的 provider，你的命令不会显示在 `hermes --help` 中。

### 示例 {#example}

```python
# plugins/memory/my-provider/cli.py

def my_command(args):
    """由 argparse 分发的处理函数。"""
    sub = getattr(args, "my_command", None)
    if sub == "status":
        print("Provider is active and connected.")
    elif sub == "config":
        print("Showing config...")
    else:
        print("Usage: hermes my-provider <status|config>")

def register_cli(subparser) -> None:
    """构建 hermes my-provider 的 argparse 树。

    在 argparse 初始化时由 discover_plugin_cli_commands() 调用。
    """
    subs = subparser.add_subparsers(dest="my_command")
    subs.add_parser("status", help="Show provider status")
    subs.add_parser("config", help="Show provider config")
    subparser.set_defaults(func=my_command)
```

### 参考实现 {#reference-implementation}

完整示例请参见 `plugins/memory/honcho/cli.py`，包含 13 个子命令、跨 profile 管理（`--target-profile`）以及配置读写。

### 含 CLI 的目录结构 {#directory-structure-with-cli}

```
plugins/memory/my-provider/
├── __init__.py      # MemoryProvider 实现 + register()
├── plugin.yaml      # 元数据
├── cli.py           # register_cli(subparser) — CLI 命令
└── README.md        # 配置说明
```

## 单 Provider 规则 {#single-provider-rule}

同一时间只能有**一个**外部 memory provider 处于活跃状态。如果用户尝试注册第二个，MemoryManager 会拒绝并发出警告。这可以防止工具 schema 膨胀和后端冲突。