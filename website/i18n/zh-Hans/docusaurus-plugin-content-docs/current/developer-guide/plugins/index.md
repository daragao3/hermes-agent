---
slug: /developer-guide/plugins
title: "构建 Hermes 插件"
sidebar_label: "Build a Plugin"
description: "逐步指南：构建包含工具、钩子、数据文件和技能的完整 Hermes 插件"
---

# 构建 Hermes 插件

本指南从零开始构建一个完整的 Hermes 插件。完成后，你将拥有一个包含多个工具、生命周期钩子（hook）、随附数据文件和捆绑技能的可用插件——涵盖插件系统支持的所有功能。

:::info 不确定需要哪份指南？
Hermes 有多种不同的可插拔接口——有些使用 Python `register_*` API，另一些是配置驱动或放入指定目录即可生效。请先查阅下表：

| 如果你想添加… | 请阅读 |
|---|---|
| 自定义工具、钩子、斜杠命令、技能或 CLI 子命令 | **本指南**（通用插件接口） |
| **原生桌面应用**扩展（面板、页面、状态栏、命令面板、主题） | [桌面插件 SDK](/developer-guide/desktop-plugin-sdk) |
| **Web 仪表盘**扩展（标签页、外壳插槽、主题） | [扩展仪表盘](/user-guide/features/extending-the-dashboard) |
| **LLM / 推理后端**（新提供商） | [模型提供商插件](/developer-guide/model-provider-plugin) |
| **网关频道**（Discord/Telegram/IRC/Teams 等） | [添加平台适配器](/developer-guide/adding-platform-adapters) |
| **记忆后端**（Honcho/Mem0/Supermemory 等） | [记忆提供商插件](/developer-guide/memory-provider-plugin) |
| **上下文压缩引擎** | [上下文引擎插件](/developer-guide/context-engine-plugin) |
| **图像生成后端** | [图像生成提供商插件](/developer-guide/image-gen-provider-plugin) |
| **视频生成后端** | [视频生成提供商插件](/developer-guide/video-gen-provider-plugin) |
| **网页搜索/提取后端** | [网页搜索提供商插件](/developer-guide/web-search-provider-plugin) |
| **云浏览器后端**（Browserbase 类 CDP 会话提供商） | [浏览器提供商插件](/developer-guide/browser-provider-plugin) |
| **密钥管理器后端**（保险库 / 密码管理器 / 系统钥匙串） | [密钥源插件](/developer-guide/secret-source-plugin) |
| **仪表盘 OIDC/认证提供商** | [Web 仪表盘 — 自定义提供商](/user-guide/features/web-dashboard#custom-providers) — `ctx.register_dashboard_auth_provider()` |
| **TTS 后端**（任意 CLI——Piper、VoxCPM、Kokoro、声音克隆等） | [TTS 自定义命令提供商](/user-guide/features/tts#custom-command-providers)——配置驱动，无需 Python |
| **STT 后端**（自定义 whisper / ASR CLI） | [语音消息转录](/user-guide/features/tts#voice-message-transcription-stt)——将 `HERMES_LOCAL_STT_COMMAND` 设置为按 argv 分词的模板 |
| **通过 MCP 接入外部工具**（文件系统、GitHub、Linear、任意 MCP 服务器） | [MCP](/user-guide/features/mcp)——在 `config.yaml` 中声明 `mcp_servers.<name>` |
| **网关事件钩子**（在启动、会话事件、命令时触发） | [事件钩子](/user-guide/features/hooks#gateway-event-hooks)——将 `HOOK.yaml` + `handler.py` 放入 `~/.hermes/hooks/<name>/` |
| **Shell 钩子**（在事件发生时运行 shell 命令） | [Shell 钩子](/user-guide/features/hooks#shell-hooks)——在 `config.yaml` 的 `hooks:` 下声明 |
| **额外技能来源**（自定义 GitHub 仓库、私有技能索引） | [技能](/user-guide/features/skills)——`hermes skills tap add <repo>` · [发布 tap](/user-guide/features/skills#publishing-a-custom-skill-tap) |
| 一流的**核心**推理提供商（非插件） | [添加提供商](/developer-guide/adding-providers) |

查看完整的[可插拔接口表](/user-guide/features/plugins#pluggable-interfaces--where-to-go-for-each)，获取每种扩展接口的汇总视图，包括配置驱动（TTS、STT、MCP、shell 钩子）和放入目录（网关钩子）两种方式。
:::

:::caution 第三方产品插件独立发布——不并入核心代码树
集成**他人产品或项目**的插件——可观测性/指标后端、厂商 SaaS 连接器、分析仪表盘、付费服务对接——应作为**独立的插件仓库**构建和分发，而不是合并进 `NousResearch/hermes-agent`。用户把它们安装到 `~/.hermes/plugins/`，或通过 pip entry point 安装；本指南中的一切在独立仓库里同样适用。这是一个耦合与维护上的决定（核心迭代很快，而我们并不拥有你的后端），不是质量门槛——一个插件可以很优秀，同时仍然应该待在自己的仓库里。欢迎在 Nous Research Discord 的 `#plugins-skills-and-skins` 频道推广它。政策详见 [CONTRIBUTING.md](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)。
:::

## 可移植 Agent Plugins v1 包 {#portable-agent-plugins-v1-packages}

Hermes 还可以安装并加载面向 Agent Plugins v1.0.0 格式的目录包。这是针对 Hermes 已拥有的
可移植组件的兼容适配层。它并不取代原生的 `plugin.yaml` 加 `register(ctx)` 插件。

```text
my-portable-plugin/
├── plugin.json
├── skills/
│   └── summarize/
│       ├── SKILL.md
│       └── references/
└── mcp.json
```

通过常规流程安装并激活可移植包：

```bash
hermes plugins install owner/repository --no-enable
hermes plugins list
hermes plugins enable <plugin-name>
```

可移植包在安装后处于禁用状态，除非你显式启用它们。已启用的包可以提供位于
`skills/*/SKILL.md` 的直接目录，以及来自根目录 `mcp.json` 的 stdio MCP 服务器。技能是只读的、
带命名空间的，并通过 `skills_list` 加 `skill_view` 加载。MCP 命令以单个可执行文件 token 加
独立参数列表的形式传递，绝不经过 shell。使用 `skills_list` 可以发现完整的限定技能名。可移植
技能的命名空间具有确定性的形式 `agent-plugin-<slug>-<hash>`，由发现的插件键派生而来，
因此经过清理的名称不会发生冲突。

Hermes 会在本地校验 `plugin.json`、Agent Skills frontmatter、固定的组件位置、`mcp.json`、
解析后的路径以及符号链接的包含关系。加载包时它不会去拉取 JSON schema。当有效的同级组件
仍能加载时，有问题的技能或 MCP 条目会在其自身边界处被跳过。`PLUGIN_ROOT` 指向解析后的包
根目录。`PLUGIN_DATA` 指向由 Hermes 管理的、按 profile 划分的可写目录。
在可移植 MCP 的 `env` 中声明的值是可见的包数据，而不是密钥存储机制。不要在 `mcp.json`
中放置凭证。

当前的可移植子集支持 stdio 和 Streamable HTTP 两种 MCP 条目。可移植的 `streamable-http`
条目会经由 Hermes 现有的原生远程 MCP 客户端路由（与支撑基于 URL 的 `mcp_servers` 配置的
是同一个运行时），并强制执行 v1 的边界规则：URL 必须是绝对的 http(s) 地址，且不含用户信息
或片段；明文 HTTP 仅对 `localhost`/回环主机开放；配置的请求头绝不会在跨源重定向时被转发。
旧式 `sse` 条目会被报告并跳过。Agent Plugins v1 没有定义信任、权限、来源证明或沙箱。启用
一个包，就意味着授予其指令和本地可执行文件与其他已安装 Hermes 插件相同的完全信任。

[渲染版规范](https://agent-plugins.org/specification)目前将 v1.0.0 标注为 Working Draft，而
[带版本的规范仓库](https://github.com/agentplugins/agent-plugins-spec/blob/main/spec/1.0.0.md)
将其记录为 Published。Hermes 的行为以规范的 v1.0.0 schema 标识符和规范性文本为准，而不依赖
任何一个可变的状态标签。这是一个明确支持的子集，并不声称完全符合 Agent Plugins 规范。

## 原生插件兼容性约定 {#native-plugin-compatibility-contract}

原生的 `plugin.yaml` 加 `register(ctx)` 插件受到的是行为层面的保护，而不是某个全局插件 API
版本号。Hermes 不公开 `PLUGIN_API_VERSION`，不要求清单级别的 `api:` 匹配，也不会给无关的
值附加 API 版本。使用了有文档记载行为的插件，在正常的 Hermes 升级之后应当继续可用。

兼容性规则如下：

- **以增量方式演进。** 有文档记载的 `PluginContext` 方法不会被移除或重命名。新参数是可选的、
  带有默认值，并且应当是仅限关键字参数。已有的返回字段不会被移除或悄悄改变类型。
- **钩子载荷是关键字载荷。** 新的钩子数据以关键字字段的形式添加，绝不会改变已有字段的含义
  或位置。Hermes 会检查回调签名：旧式回调接收它所声明的字段，而带有 `**kwargs` 的回调接收
  完整的当前载荷。新插件应当接受 `**kwargs`，这样无需再次修改签名即可获得新增数据。
- **清单对新增内容开放。** 未知的 `plugin.yaml` 字段会被忽略。因此，只要插件代码本身使用的是
  受支持的运行时行为，较旧的 Hermes 版本也能加载清单中包含较新版本引入的元数据的插件。
- **提供者接口通过默认值扩展。** 新的提供者方法带有默认实现。新的回调上下文是可选的，只有在
  签名检查表明提供者接受它时才会被转发。添加抽象方法或无条件转发的参数需要一个迁移窗口，
  而不是一刀切地更改签名。
- **为跨越边界的约定加版本号。** 当某项能力定义了线上载荷或持久化格式时（例如观察者载荷或
  secret-source 状态），它可以携带自己的 schema 版本。在该局部 schema 内保持字段的增量演进。
  持久化的插件状态和配置必须保持可读，否则就要提供明确的迁移；用旧格式写入的已恢复会话必须
  仍然可以重放。不要在无关的回调或上下文值中添加版本字面量。

### 弃用策略 {#deprecation-policy}

有文档记载的原生插件行为只有在同时满足以下所有条件时才可以被弃用：

1. 在插件指南和发布说明中提供替代方案和迁移说明；
2. 每个进程最多发出一次警告，指明替代方案以及最早的移除版本；
3. 旧行为在其后至少两个次要版本中继续受支持；并且
4. 在整个窗口期内，对旧路径和替代方案都提供基于行为的兼容性覆盖。

窗口期结束后的移除必须包含持久化数据或可恢复会话所需的任何迁移。实践中，相比移除，
更倾向于采用增量式的别名和适配器。

Hermes 通过从隔离的 `HERMES_HOME` 中发现的、冻结的外部插件夹具来强制执行这一约定。这些测试
通过 `PluginManager` 加载并调用插件；它们断言的是真实的注册和回调结果，而不是内部符号列表
或源代码形态。

### 2026 年 9 月模块拆分：旧导入路径于 2026-09-14 终止 {#sep-2026-module-decomposition-old-import-paths-end-2026-09-14}

Hermes 的内部实现于 2026 年 9 月被拆分为 `<stem>_<topic>` 同级模块（PR #102117）。**内部导入
路径从来都不属于**上述插件约定，但许多插件使用了它们。每个被移动的名称在 **2026-09-14** 之前
仍可从其旧模块解析，之后兼容层将被移除。

- **检查你的插件：** `hermes plugins compat /path/to/your/plugin` 会列出每一处使用旧路径的
  `file:line` 以及对应的新路径，只要仍有残留就以退出码 1 退出。仓库中的 `COMPAT_MANIFEST.md`
  是完整的映射表。
- **用户会看到什么：** CLI 横幅下方、`hermes doctor` 中以及 `hermes update` 之后会出现一条提示，
  Desktop 也会弹出一次性对话框并指明该插件。每次通过旧路径解析时，还会在每个进程中发出一次
  `HermesPluginCompatWarning`。
- **自 2026-09-14 起：** 仍在导入旧路径的插件将**不会被加载**（原因会显示在
  `hermes plugins list` 中）。在兼容层真正被移除之前，用户可以通过
  `plugins.allow_deprecated_imports: true` 强制加载，届时旧路径会抛出 `ImportError`。

## 你将构建什么

一个**计算器**插件，包含两个工具：
- `calculate`——计算数学表达式（`2**16`、`sqrt(144)`、`pi * 5**2`）
- `unit_convert`——在单位之间转换（`100 F → 37.78 C`、`5 km → 3.11 mi`）

另外还有一个记录每次工具调用的钩子，以及一个捆绑的技能文件。

## 第一步：创建插件目录

创建一个目录，然后继续第二步：

```bash
mkdir -p ~/.hermes/plugins/calculator
cd ~/.hermes/plugins/calculator
```

### 使用 Plugin Doctor 进行校验 {#validate-with-plugin-doctor}

`hermes plugins doctor [path-or-id]` 运行的目录发现、清单解析器、命名空间导入、`register(ctx)`、
钩子注册表和工具注册表，与 Hermes 自身使用的完全相同。它会报告无效的钩子名称、不接受
`**kwargs` 的回调、注册失败，以及声明的与实际注册的工具/钩子之间的偏差。传入 `--ci` 可在出错时
以非零状态退出：

```bash
hermes plugins doctor . --ci
```

Doctor 使用临时的 `HERMES_HOME`，在检查结束后恢复插件注册状态，并在注册运行期间阻止直接的
Python socket 连接，以捕获意外的网络访问。这不是沙箱：插件代码仍在进程内以当前用户的权限执行，
并且可以派生子进程，因此只应对你足够信任、愿意导入的代码运行 Doctor。

## 第二步：编写清单文件

创建 `plugin.yaml`：

```yaml
name: calculator
version: 1.0.0
description: Math calculator — evaluate expressions and convert units
provides_tools:
  - calculate
  - unit_convert
provides_hooks:
  - post_tool_call
```

这告诉 Hermes："我是一个名为 calculator 的插件，我提供工具和钩子。" `provides_tools` 和 `provides_hooks` 字段是插件注册内容的列表。

可选字段示例：
```yaml
author: Your Name
requires_env:          # 根据环境变量决定是否加载；安装时会提示用户
  - SOME_API_KEY       # 简单格式——缺失时插件禁用
  - name: OTHER_KEY    # 富格式——安装时显示描述/URL
    description: "Key for the Other service"
    url: "https://other.com/keys"
    secret: true
capabilities:          # 你申请的特权宿主接口（授权流程）
  - tools.override     # 替换内置工具（需要用户授权）
  - llm.model_override # 为宿主拥有的 LLM 调用选择模型
```

### 声明能力 {#declaring-capabilities}

如果你的插件需要特权宿主接口——覆盖内置工具、为 `ctx.llm` 调用挑选模型等——请在
`capabilities:` 中声明。在安装/启用时，用户会看到该列表并一次性授权；如果后续版本新增了某项能力，
更新流程只会就新增部分再次询问。未声明或未获授权的能力直接处于关闭状态（fail closed），因此
**使用前先探测，并优雅降级**：

```python
def register(ctx):
    if ctx.has_capability("tools.override"):
        ctx.register_tool(..., override=True)
    else:
        ctx.register_tool(...)   # 以不冲突的名称注册
```

已知的能力 id：`tools.override`、`llm.provider_override`、`llm.model_override`、
`llm.agent_id_override`、`llm.profile_override`、`llm.task_override`（规范注册表见
`hermes_cli/plugin_capabilities.py`）。未知的 id 会被忽略。较早的按能力划分的配置键
（`plugins.entries.<id>.allow_tool_override`，……）仍然有效但已弃用——请改为声明能力，这样用户
就能看到一个统一的、可审计的授权界面。能力是授权 + 审计，**而不是沙箱**：它们只负责门控宿主
API 接口，仅此而已。

**通过 pip 分发的插件**在安装后没有 `plugin.yaml` 目录，因此应改为在分发元数据中通过配套的
`hermes_agent.plugin_capabilities` entry-point 组声明能力。每条声明命名为
`<plugin-id>.<capability-id>`，并指向与你的 `hermes_agent.plugins` entry point 相同的对象：

```toml
[project.entry-points."hermes_agent.plugins"]
calculator = "my_pkg:register"

[project.entry-points."hermes_agent.plugin_capabilities"]
"calculator.tools.override" = "my_pkg:register"
```

Hermes 会从已安装的元数据中读取这些声明而无需导入你的代码，因此对于 pip 安装，
`hermes plugins capabilities` 和授权流程依然准确。

### 清单 v2 参考 {#manifest-v2-reference}

`plugin.yaml` 还支持增量式的 **v2 schema**（#64165）。每个字段都是可选的；没有
`manifest_version` 的清单就是 v1 清单，并将永远获得完整支持。未知字段绝不会导致加载失败——
它们会被忽略并给出警告（向前兼容），而比当前 Hermes 所能理解的更新的 `manifest_version`
也仍会加载并给出警告。

| 字段 | 类型 | 含义 |
|---|---|---|
| `manifest_version` | int | 清单**文件格式**版本。缺省 = `1`。当前最大值：`2`。与 `api_version` 相互独立。 |
| `api_version` | int | 插件所面向的运行时**插件 API 代际**（ctx 接口 / 钩子签名）。刻意与 `manifest_version` 分属不同维度——`api_version: 1` 的插件可以使用 v2 清单。 |
| `requires_plugins` | list | 插件间依赖：`- id: other-plugin`，可附带 `version_range: ">=1.0,<2"`。**仅供参考**：缺失的依赖会记录一条清晰的警告，但插件仍会加载——请在运行时用 `ctx.has_plugin("other-plugin")` 进行探测。加载**顺序**遵循这些依赖边：当 A 依赖 B 时，B 的 `register()` 先于 A 的运行（拓扑排序，按字母顺序打破平局；出现环时发出警告并回退为字母顺序）。 |
| `python_dependencies` | list of str | 声明的 pip 依赖（例如 `"requests>=2.0,<3"`）。**仅是声明接缝**——Hermes 会校验它们，`hermes plugins install` / `hermes plugins doctor` 会提示缺失项并给出 `pip install` 建议，但 Hermes **绝不会自动安装**它们。请固定上界。 |
| `config_schema` | mapping | 对 `plugins.entries.<id>.settings` 下各键的类 JSON-schema 描述：`api_url: {type: str, default: "", description: "...", required: false}`。在加载时校验；不匹配时记录可操作的警告，指明键名和期望类型——绝不会导致加载失败。类型：`str`、`int`、`float`、`bool`、`list`、`dict`（以及 JSON-schema 别名）。 |
| `license` | str | SPDX 风格的许可证 id（例如 `MIT`）。 |
| `homepage` | str | 项目 URL。 |
| `tags` | list of str | 自由格式的发现标签（例如 `[gateway, telegram]`）。 |

```yaml
# plugin.yaml — manifest v2 example
name: my-plugin
version: 1.2.0
manifest_version: 2
api_version: 1
license: MIT
homepage: https://github.com/owner/my-plugin
tags: [gateway, demo]
requires_plugins:
  - id: other-plugin
    version_range: ">=1.0,<2"
python_dependencies:
  - "somepkg>=1.0,<2"     # 仅提示，绝不自动安装
config_schema:
  api_url: {type: str, default: "", description: "Service endpoint"}
```

:::note pip 依赖隔离被推迟
`python_dependencies` 有意只做声明和提示。把任意包安装进 Hermes 共享的 venv 会带来冲突和
供应链风险，因此安装接缝的隔离设计（针对宿主锁文件的 constraints 安装、按插件的 vendored 目录，
或检测冲突并拒绝）是一项明确推迟的后续工作——参见
[#64165](https://github.com/NousResearch/hermes-agent/issues/64165) 上的第二轮评审以及
[#15220](https://github.com/NousResearch/hermes-agent/issues/15220)。插件包（#64166）构建在这些
v2 字段之上。
:::

## 第三步：编写工具 schema

创建 `schemas.py`——这是 LLM 读取以决定何时调用你的工具的内容：

```python
"""Tool schemas — what the LLM sees."""

CALCULATE = {
    "name": "calculate",
    "description": (
        "Evaluate a mathematical expression and return the result. "
        "Supports arithmetic (+, -, *, /, **), functions (sqrt, sin, cos, "
        "log, abs, round, floor, ceil), and constants (pi, e). "
        "Use this for any math the user asks about."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Math expression to evaluate (e.g., '2**10', 'sqrt(144)')",
            },
        },
        "required": ["expression"],
    },
}

UNIT_CONVERT = {
    "name": "unit_convert",
    "description": (
        "Convert a value between units. Supports length (m, km, mi, ft, in), "
        "weight (kg, lb, oz, g), temperature (C, F, K), data (B, KB, MB, GB, TB), "
        "and time (s, min, hr, day)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "description": "The numeric value to convert",
            },
            "from_unit": {
                "type": "string",
                "description": "Source unit (e.g., 'km', 'lb', 'F', 'GB')",
            },
            "to_unit": {
                "type": "string",
                "description": "Target unit (e.g., 'mi', 'kg', 'C', 'MB')",
            },
        },
        "required": ["value", "from_unit", "to_unit"],
    },
}
```

**schema 为何重要：** `description` 字段决定了 LLM 何时使用你的工具。请明确说明工具的功能和使用时机。`parameters` 定义了 LLM 传入的参数。

## 第四步：编写工具处理器

创建 `tools.py`——这是 LLM 调用工具时实际执行的代码：

```python
"""Tool handlers — the code that runs when the LLM calls each tool."""

import json
import math

# Safe globals for expression evaluation — no file/network access
_SAFE_MATH = {
    "abs": abs, "round": round, "min": min, "max": max,
    "pow": pow, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "log": math.log, "log2": math.log2, "log10": math.log10,
    "floor": math.floor, "ceil": math.ceil,
    "pi": math.pi, "e": math.e,
    "factorial": math.factorial,
}


def calculate(args: dict, **kwargs) -> str:
    """Evaluate a math expression safely.

    Rules for handlers:
    1. Receive args (dict) — the parameters the LLM passed
    2. Do the work
    3. Return a JSON string — ALWAYS, even on error
    4. Accept **kwargs for forward compatibility
    """
    expression = args.get("expression", "").strip()
    if not expression:
        return json.dumps({"error": "No expression provided"})

    try:
        result = eval(expression, {"__builtins__": {}}, _SAFE_MATH)
        return json.dumps({"expression": expression, "result": result})
    except ZeroDivisionError:
        return json.dumps({"expression": expression, "error": "Division by zero"})
    except Exception as e:
        return json.dumps({"expression": expression, "error": f"Invalid: {e}"})


# Conversion tables — values are in base units
_LENGTH = {"m": 1, "km": 1000, "mi": 1609.34, "ft": 0.3048, "in": 0.0254, "cm": 0.01}
_WEIGHT = {"kg": 1, "g": 0.001, "lb": 0.453592, "oz": 0.0283495}
_DATA = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_TIME = {"s": 1, "ms": 0.001, "min": 60, "hr": 3600, "day": 86400}


def _convert_temp(value, from_u, to_u):
    # Normalize to Celsius
    c = {"F": (value - 32) * 5/9, "K": value - 273.15}.get(from_u, value)
    # Convert to target
    return {"F": c * 9/5 + 32, "K": c + 273.15}.get(to_u, c)


def unit_convert(args: dict, **kwargs) -> str:
    """Convert between units."""
    value = args.get("value")
    from_unit = args.get("from_unit", "").strip()
    to_unit = args.get("to_unit", "").strip()

    if value is None or not from_unit or not to_unit:
        return json.dumps({"error": "Need value, from_unit, and to_unit"})

    try:
        # Temperature
        if from_unit.upper() in {"C","F","K"} and to_unit.upper() in {"C","F","K"}:
            result = _convert_temp(float(value), from_unit.upper(), to_unit.upper())
            return json.dumps({"input": f"{value} {from_unit}", "result": round(result, 4),
                             "output": f"{round(result, 4)} {to_unit}"})

        # Ratio-based conversions
        for table in (_LENGTH, _WEIGHT, _DATA, _TIME):
            lc = {k.lower(): v for k, v in table.items()}
            if from_unit.lower() in lc and to_unit.lower() in lc:
                result = float(value) * lc[from_unit.lower()] / lc[to_unit.lower()]
                return json.dumps({"input": f"{value} {from_unit}",
                                 "result": round(result, 6),
                                 "output": f"{round(result, 6)} {to_unit}"})

        return json.dumps({"error": f"Cannot convert {from_unit} → {to_unit}"})
    except Exception as e:
        return json.dumps({"error": f"Conversion failed: {e}"})
```

**处理器的关键规则：**
1. **签名：** `def my_handler(args: dict, **kwargs) -> str`
2. **返回值：** 始终返回 JSON 字符串。成功和错误均如此。
3. **不要抛出异常：** 捕获所有异常，改为返回错误 JSON。
4. **接受 `**kwargs`：** Hermes 未来可能传入额外上下文。

## 第五步：编写注册代码

创建 `__init__.py`——将 schema 与处理器连接起来：

```python
"""Calculator plugin — registration."""

import logging

from . import schemas, tools

logger = logging.getLogger(__name__)

# Track tool usage via hooks
_call_log = []

def _on_post_tool_call(tool_name, args, result, task_id, **kwargs):
    """Hook: runs after every tool call (not just ours)."""
    _call_log.append({"tool": tool_name, "session": task_id})
    if len(_call_log) > 100:
        _call_log.pop(0)
    logger.debug("Tool called: %s (session %s)", tool_name, task_id)


def register(ctx):
    """Wire schemas to handlers and register hooks."""
    ctx.register_tool(name="calculate",    toolset="calculator",
                      schema=schemas.CALCULATE,    handler=tools.calculate)
    ctx.register_tool(name="unit_convert", toolset="calculator",
                      schema=schemas.UNIT_CONVERT, handler=tools.unit_convert)

    # This hook fires for ALL tool calls, not just ours
    ctx.register_hook("post_tool_call", _on_post_tool_call)
```

**`register()` 的作用：**
- 在启动时恰好调用一次
- `ctx.register_tool()` 将你的工具放入注册表——模型立即可见
- `ctx.register_hook()` 订阅生命周期事件
- `ctx.register_cli_command()` 注册 CLI 子命令（例如 `hermes my-plugin <subcommand>`）
- `ctx.register_command()` 注册会话内斜杠命令（例如在 CLI / 网关聊天中输入 `/myplugin <args>`）——详见下方[注册斜杠命令](#register-slash-commands)
- `ctx.dispatch_tool(name, arguments)` ——以父代理的上下文（审批、凭证、task_id 自动连接）调用任意其他工具（内置或来自其他插件）。适用于需要直接调用 `terminal`、`read_file` 或其他工具的斜杠命令处理器，效果等同于模型直接调用。
- `ctx.get_config()` / `ctx.set_config()` 只能访问本插件自己的设置命名空间；`ctx.state` 在当前 profile 下存储插件拥有的运行时数据。
- 如果此函数崩溃，插件将被禁用，但 Hermes 继续正常运行

**`dispatch_tool` 示例——执行工具的斜杠命令：**

```python
def handle_scan(ctx, raw_args: str):
    """Implement /scan by invoking the terminal tool through the registry."""
    result = ctx.dispatch_tool("terminal", {"command": f"find . -name '{raw_args}'"})
    return result  # returned to the caller's chat UI

def register(ctx):
    # Handlers receive a single raw_args string; close over ctx via a lambda.
    ctx.register_command(
        "scan",
        lambda raw: handle_scan(ctx, raw),
        description="Find files matching a glob",
    )
```

被分发的工具会经过正常的审批、脱敏和预算流程——这是真实的工具调用，而非绕过这些流程的捷径。

### 存储设置和运行时状态 {#store-settings-and-runtime-state}

对用户可见的行为使用相对于插件的配置键。Hermes 会将它们解析到
`plugins.entries.<plugin-id>.settings` 之下，并拒绝全局路径、跨插件路径和路径穿越：

```python
def register(ctx):
    endpoint = ctx.get_config("endpoint", default="https://example.invalid")
    retries = ctx.get_config("retry.attempts", default=3)

    ctx.set_config("endpoint", endpoint)
    ctx.set_config("retry.attempts", retries)
```

对于插件拥有的游标、缓存和去重数据，请使用 `ctx.state`，而不是把运行时簿记数据放进
`config.yaml`：

```python
def register(ctx):
    cursor = ctx.state.get("cursor", default={"page": 0})
    ctx.state.set("cursor", {"page": cursor["page"] + 1})
```

状态按 profile 划分、以原子方式替换、对并发写入者安全，并且每个插件上限为 10 MiB。可移植包
与其 `PLUGIN_DATA` 共用同一个目录；原生插件会获得一个抗冲突、在 Windows 上安全的命名空间。
格式错误的已有状态会被报告并保留。

配置和状态有不同的所有者：设置是 `config.yaml` 中对用户可见的行为，而状态是位于
`<HERMES_HOME>/plugin-data/` 下、由插件拥有的运行时数据。两个 API 都不会暴露其他插件的命名空间。

## 第六步：测试

启动 Hermes：

```bash
hermes
```

你应该在启动横幅的工具列表中看到 `calculator: calculate, unit_convert`。

尝试以下提示词（prompt）：
```
What's 2 to the power of 16?
Convert 100 fahrenheit to celsius
What's the square root of 2 times pi?
How many gigabytes is 1.5 terabytes?
```

检查插件状态：
```
/plugins
```

输出：
```
Plugins (1):
  ✓ calculator v1.0.0 (2 tools, 1 hooks)
```

### 调试插件发现问题

如果你的插件没有出现，或出现了但未加载——设置 `HERMES_PLUGINS_DEBUG=1` 可在 stderr 获取详细的发现日志：

```bash
HERMES_PLUGINS_DEBUG=1 hermes plugins list
```

你将看到每个插件来源（内置、用户、项目、entry-points）的以下信息：

- 扫描了哪些目录，每个目录产出了多少个清单
- 每个清单：解析后的键、名称、类型、来源、磁盘路径
- 跳过原因：`disabled via config`、`not enabled in config`、`exclusive plugin`、`no plugin.yaml, depth cap reached`
- 加载时：正在导入的插件，以及 `register(ctx)` 注册内容的单行摘要（工具、钩子、斜杠命令、CLI 命令）
- 解析失败时：异常的完整堆栈跟踪（YAML 扫描器错误等）
- `register()` 失败时：指向 `__init__.py` 中抛出异常的行的完整堆栈跟踪

同样的日志始终写入 `~/.hermes/logs/agent.log`，失败时为 WARNING 级别，设置环境变量时为 DEBUG 级别（全部内容）。如果无法使用环境变量运行（例如从网关内部），可以改为追踪日志文件：

```bash
hermes logs --level WARNING | grep -i plugin
```

插件未出现的常见原因：

- **未在配置中启用**——插件需要手动启用。运行 `hermes plugins enable <name>`（名称来自 `plugins list` 输出，嵌套布局下可能是 `<category>/<plugin>`）。
- **目录结构错误：** 原生包使用 `~/.hermes/plugins/<plugin-name>/plugin.yaml`（扁平）或一级分类嵌套。可移植包在相同位置使用根目录的 `plugin.json`。更深层的目录会被忽略。
- **缺少 `__init__.py`：** 原生包需要同时包含 `plugin.yaml` 和带有 `register(ctx)` 函数的 `__init__.py`。可移植包不导入 Python，不需要 `__init__.py`。
- **`kind` 错误**——网关适配器需要在清单中设置 `kind: platform`。记忆提供商会被自动检测为 `kind: exclusive`，并通过 `memory.provider` 配置路由，而非 `plugins.enabled`。

## 插件的最终结构

```
~/.hermes/plugins/calculator/
├── plugin.yaml      # "我是 calculator，我提供工具和钩子"
├── __init__.py      # 连接：schema → 处理器，注册钩子
├── schemas.py       # LLM 读取的内容（描述 + 参数规格）
└── tools.py         # 实际运行的代码（calculate、unit_convert 函数）
```

四个文件，职责清晰：
- **清单**声明插件是什么
- **Schema** 向 LLM 描述工具
- **处理器**实现实际逻辑
- **注册**将一切连接起来

## 插件还能做什么？

### 随附数据文件

将任意文件放入插件目录，并在导入时读取：

```python
# In tools.py or __init__.py
from pathlib import Path

_PLUGIN_DIR = Path(__file__).parent
_DATA_FILE = _PLUGIN_DIR / "data" / "languages.yaml"

with open(_DATA_FILE) as f:
    _DATA = yaml.safe_load(f)
```

以上针对的是你*随附*的文件。你*写入*的状态则不同——参见下一节。

### 存储持久化状态 {#store-durable-state}

永远不要把运行时状态写进你的插件目录：那是安装树，`hermes plugins update` / `remove` 会对它
执行 git pull 或直接删除——你的用户数据会随之消失。官方认可的存放位置是按插件划分的数据根目录，
它在这两种操作后都能保留，并跟随当前 profile：

```python
from plugins.plugin_storage import plugin_data_dir, plugin_db

# <hermes home>/plugin-data/<name>/ — 首次使用时创建
state_file = plugin_data_dir("my-plugin") / "state.json"

# 或者位于 <data dir>/data.db 的 SQLite 数据库（WAL 模式，对线程友好）
conn = plugin_db("my-plugin")
conn.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY)")
```

每个插件一个目录，意味着每个插件的数据都可以在一个可预测的位置进行检查。密钥不属于这里——
凭证读取与其他地方一样，走标准的 `.env` / secret-scope 路径。

### 捆绑技能 {#bundle-skills}

插件可以随附技能文件，代理通过 `skill_view("plugin:skill")` 加载。在 `__init__.py` 中注册：

```
~/.hermes/plugins/my-plugin/
├── __init__.py
├── plugin.yaml
└── skills/
    ├── my-workflow/
    │   └── SKILL.md
    └── my-checklist/
        └── SKILL.md
```

```python
from pathlib import Path

def register(ctx):
    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)
```

代理现在可以通过命名空间名称加载你的技能：

```python
skill_view("my-plugin:my-workflow")   # → 插件版本
skill_view("my-workflow")              # → 内置版本（不受影响）
```

**关键特性：**
- 插件技能是**只读**的——它们不会进入 `~/.hermes/skills/`，也无法通过 `skill_manage` 编辑。
- 插件技能**不会**列在系统提示词的 `<available_skills>` 索引中——需要显式加载。
- 裸技能名称不受影响——命名空间防止与内置技能冲突。
- 代理加载插件技能时，会在前面添加一个捆绑上下文横幅，列出同一插件的兄弟技能。

:::tip 旧版模式
旧的 `shutil.copy2` 模式（将技能复制到 `~/.hermes/skills/`）仍然有效，但存在与内置技能名称冲突的风险。新插件请优先使用 `ctx.register_skill()`。
:::

### 根据环境变量决定是否启用 {#gate-on-environment-variables}

如果你的插件需要 API 密钥：

```yaml
# plugin.yaml — 简单格式（向后兼容）
requires_env:
  - WEATHER_API_KEY
```

如果 `WEATHER_API_KEY` 未设置，插件将被禁用并显示清晰的提示信息。不会崩溃，代理中也不会报错——只会显示"Plugin weather disabled (missing: WEATHER_API_KEY)"。

用户运行 `hermes plugins install` 时，会**交互式提示**输入任何缺失的 `requires_env` 变量。值会自动保存到 `.env`。

为了获得更好的安装体验，使用带有描述和注册 URL 的富格式：

```yaml
# plugin.yaml — 富格式
requires_env:
  - name: WEATHER_API_KEY
    description: "API key for OpenWeather"
    url: "https://openweathermap.org/api"
    secret: true
```

| 字段 | 必填 | 描述 |
|-------|----------|-------------|
| `name` | 是 | 环境变量名称 |
| `description` | 否 | 安装提示时显示给用户 |
| `url` | 否 | 获取凭证的地址 |
| `secret` | 否 | 若为 `true`，输入时隐藏（类似密码字段） |

两种格式可在同一列表中混用。已设置的变量会被静默跳过。

### 懒加载可选 Python 依赖 {#lazy-install-optional-python-dependencies}

如果你的插件封装了一个并非所有用户都会安装的 SDK（供应商 SDK、重型 ML 库、平台特定包），不要在模块顶部 `import` 它。在工具处理器内部使用 `tools.lazy_deps.ensure(...)` 辅助函数——Hermes 会在首次使用时安装该包，并受用户 `security.allow_lazy_installs` 配置的控制。

```python
# tools.py
from tools.lazy_deps import ensure, FeatureUnavailable

def my_tool_handler(args, **kwargs):
    try:
        ensure("my-plugin.my-backend")   # key must be in LAZY_DEPS
    except FeatureUnavailable as exc:
        return {"error": str(exc)}

    import my_backend_sdk   # safe now
    ...
```

来自 `tools/lazy_deps.py` 安全模型的两条规则：

| 规则 | 原因 |
|---|---|
| 你的功能键必须出现在内置的 `LAZY_DEPS` 允许列表中 | 防止恶意配置诱使 Hermes 安装任意包——只有 Hermes 自身随附的规格才符合条件 |
| 规格仅限 PyPI 包名 | 不允许 `--index-url`、`git+https://` 或 `file:` 路径。在允许列表条目中使用 PEP 440 固定版本（`"my-sdk>=1.2,<2"`） |

对于通过 pip 分发的第三方插件，在你自己的 `pyproject.toml` 中将可选依赖声明为 `[project.optional-dependencies]` extras，并告知用户执行 `pip install your-plugin[backend]`——该路径不经过 `lazy_deps`。懒加载安装最适合**内置**插件，因为对每次安装都强制依赖会增加 Hermes 基础安装的体积。

当全局设置 `security.allow_lazy_installs: false` 时，`ensure()` 会立即抛出 `FeatureUnavailable` 并附带修复提示——你的插件应捕获该异常并优雅降级（返回错误结果，而非让工具循环崩溃）。

### 线程安全的懒加载单例

插件常常把一个昂贵的对象——SDK 客户端、HTTP 会话、连接池——缓存在模块级变量中，首次使用时才构建：

```python
_client = None

def get_client():
    global _client
    if _client is not None:
        return _client
    _client = ExpensiveClient(...)   # ← TOCTOU race
    return _client
```

这是一个陷阱。Hermes 在同一个进程中运行多个线程（委派的工具调用、后台 worker、自我改进 fork），因此两个线程可能在 `_client` 被赋值之前同时进入 `get_client()`，**双双**通过 `is not None` 检查，**双双**执行昂贵的构建，第二次写入覆盖第一次——泄漏掉落败者打开的任何资源（连接、文件句柄、后台线程）。

不要自己手写锁。请使用 `plugins/plugin_utils.py` 中的辅助工具：

```python
from plugins.plugin_utils import lazy_singleton, SingletonSlot

# Zero-arg accessor → decorate it:
@lazy_singleton
def get_client():
    return ExpensiveClient(load_config())   # runs exactly once

client = get_client()    # safe across threads
get_client.reset()       # drop the instance (tests / teardown)


# Accessor that takes a build argument → use a slot:
_slot: SingletonSlot = SingletonSlot()

def get_client(config=None):
    return _slot.get(lambda: ExpensiveClient(resolve(config)))

def reset_client():
    _slot.reset()
```

两者都用双重检查锁定把并发的首次调用串行化，并保证工厂函数最多执行一次。如果工厂抛出异常，则什么都不会被缓存，下一次调用会重试。honcho 记忆插件（`plugins/memory/honcho/client.py`）是参考实现。

> 经验法则：只要你写下 `global _something`，紧接着是 `is None` 检查和一次构建，就应该改用其中之一。



### 条件工具可用性

对于依赖可选库的工具：

```python
ctx.register_tool(
    name="my_tool",
    schema={...},
    handler=my_handler,
    check_fn=lambda: _has_optional_lib(),  # False = 工具对模型隐藏
)
```

### 覆盖内置工具

要用你自己的实现替换内置工具（例如将默认浏览器工具替换为有头 Chrome CDP 后端，或将 `web_search` 替换为自定义企业索引），传入 `override=True`：

```python
def register(ctx):
    ctx.register_tool(
        name="browser_navigate",             # 与内置工具同名
        toolset="plugin_my_browser",         # 你自己的 toolset 命名空间
        schema={...},
        handler=my_custom_navigate,
        override=True,                       # 显式启用覆盖
    )
```

不加 `override=True` 时，注册表会拒绝任何会遮蔽来自不同 toolset 的已有工具的注册——这防止了意外覆盖。覆盖**内置**工具还需要运维者在 `config.yaml` 中通过 `plugins.entries.<plugin_id>.allow_tool_override: true` 选择启用；没有这道门控时，`register_tool(override=True)` 会抛出 `PluginToolOverrideError`。覆盖操作会被记录日志，可在 `~/.hermes/logs/agent.log` 中审计。插件在内置工具之后加载，因此注册顺序是正确的：你的处理器会替换内置处理器。

**非捆绑插件同样需要运维者授权。** 对于任何不随 Hermes 核心一起发布的插件（user、project 或 pip 来源），针对已有内置工具使用 `override=True` 还需要在 `config.yaml` 中按插件选择启用：

```yaml
plugins:
  entries:
    my-plugin:                    # 来自 `hermes plugins list` 的插件注册表键
      allow_tool_override: true
```

没有该授权时，`ctx.register_tool(..., override=True)` 会抛出 `PluginToolOverrideError`；由于 `register()` 的异常会被加载器捕获，该插件会被禁用而 Hermes 继续运行。设置这道门控的原因是：一个已启用的插件若悄悄替换了 `shell_exec` 或 `write_file` 这类特权内置工具，就可能拦截模型经由它路由的一切。捆绑插件不受此限：在那里进行覆盖是维护者的决定。如果无法加载配置，该门控会 fail closed。

你通常无需手动编辑这个键。启用非捆绑插件时，`hermes plugins enable <name>` 会询问是否授予该能力（默认为否），而 `--allow-tool-override` / `--no-allow-tool-override` 标志可在脚本化安装中跳过该提示。同一授权也门控 `deregister()`：没有它，插件无法移除不属于自己的工具（否则这就成了绕过覆盖检查的一种方式）。

### 注册多个钩子

```python
def register(ctx):
    ctx.register_hook("pre_tool_call", before_any_tool)
    ctx.register_hook("post_tool_call", after_any_tool)
    ctx.register_hook("pre_llm_call", inject_memory)
    ctx.register_hook("on_session_start", on_new_session)
    ctx.register_hook("on_session_end", on_session_end)
```

### 钩子参考

每个钩子的完整文档见**[事件钩子参考](/user-guide/features/hooks#plugin-hooks)**——回调签名、参数表、触发时机和示例。以下是摘要：

| 钩子 | 触发时机 | 回调签名 | 返回值 |
|------|-----------|-------------------|---------|
| [`pre_tool_call`](/user-guide/features/hooks#pre_tool_call) | 任意工具执行前 | `tool_name: str, args: dict, task_id: str` | 可选指令：`{"action": "block", "message": ...}` 否决该调用；`{"action": "approve", "message": ...}` 升级到人工审批闸门 |
| [`post_tool_call`](/user-guide/features/hooks#post_tool_call) | 任意工具返回后 | `tool_name: str, args: dict, result: str, task_id: str, duration_ms: int` | 忽略 |
| [`pre_llm_call`](/user-guide/features/hooks#pre_llm_call) | 每轮一次，工具调用循环前 | `session_id: str, user_message: str, conversation_history: list, is_first_turn: bool, model: str, platform: str` | [上下文注入](#pre_llm_call-context-injection) |
| [`post_llm_call`](/user-guide/features/hooks#post_llm_call) | 每轮一次，工具调用循环后（仅成功轮次） | `session_id: str, user_message: str, assistant_response: str, conversation_history: list, model: str, platform: str` | 忽略 |
| `pre_api_request` | 每次原始 provider API 请求之前（模型调用工具时每轮会有多次） | `session_id: str, model: str, provider: str, base_url: str, api_mode: str, api_call_count: int, message_count: int, tool_count: int, approx_input_tokens: int, max_tokens: int, request: dict` | 忽略 |
| `post_api_request` | 每次原始 provider API 请求返回之后 | `pre_api_request` 的字段，外加 `api_duration: float, finish_reason: str, response_model: str \| None, usage: dict, response: dict, assistant_content_chars: int, assistant_tool_call_count: int` | 忽略 |
| `api_request_error` | provider API 调用抛出异常 | 关联字段，外加 `status_code: int \| None, retry_count: int \| None, max_retries: int \| None, retryable: bool \| None, reason: str \| None, error: dict, request: dict` | 忽略 |
| [`on_session_start`](/user-guide/features/hooks#on_session_start) | 新会话创建（仅第一轮） | `session_id: str, model: str, platform: str` | 忽略 |
| [`on_session_end`](/user-guide/features/hooks#on_session_end) | 每次 `run_conversation` 调用结束 + CLI 退出 | `session_id: str, completed: bool, interrupted: bool, model: str, platform: str` | 忽略 |
| [`on_session_finalize`](/user-guide/features/hooks#on_session_finalize) | CLI/网关销毁活跃会话 | `session_id: str \| None, platform: str` | 忽略 |
| [`on_session_reset`](/user-guide/features/hooks#on_session_reset) | 网关切换新会话键（`/new`、`/reset`） | `session_id: str, platform: str` | 忽略 |
| [`gateway_platform_event`](/user-guide/features/hooks#gateway_platform_event) | 经过授权的平台原生事件在网关边界被归一化（目前为 Telegram 回应） | `platform: str, event_type: str, payload: dict` | 忽略 |
| `kanban_task_claimed` | kanban 任务被认领（dispatcher 进程中，worker 启动之前） | `task_id: str, board: str \| None, assignee: str \| None, run_id: int \| None, profile_name: str` | 忽略 |
| `kanban_task_completed` | kanban 任务完成（worker 进程） | `task_id, board, assignee, run_id, profile_name, summary: str \| None` | 忽略 |
| `kanban_task_blocked` | kanban 任务被阻塞（worker 进程） | `task_id, board, assignee, run_id, profile_name, reason: str \| None` | 忽略 |

大多数钩子是即发即忘的观察者——其返回值被忽略。例外是 `pre_llm_call`（可以向对话中注入上下文）和 `pre_tool_call`（可以返回 block/approve 指令）。

所有回调都应接受 `**kwargs` 以保持向前兼容性。如果钩子回调崩溃，会被记录日志并跳过。其他钩子和代理继续正常运行。

kanban 生命周期钩子在看板数据库变更提交**之后**触发，因此回调总是看到持久化后的状态，并且绝不会持有 SQLite 写锁。由于 kanban worker 以独立的 `hermes -p <profile> chat -q` 子进程运行，`kanban_task_claimed` 在 **dispatcher** 进程中触发，而 `kanban_task_completed` / `kanban_task_blocked` 在 **worker** 进程中触发——在 dispatcher 中挂钩可集中观察每一次状态转换，在 worker 中挂钩则可获得每个任务的会话内上下文。

**API 请求钩子**是针对原始 provider 请求的观察者，比每轮一次的 `pre_llm_call` / `post_llm_call` 低一个层级：一个调用了工具的轮次会发出多个 API 请求，这些钩子会在每个请求前后触发。它们为可观测性插件（追踪、成本核算、延迟仪表盘）而设。`request` 和 `response` 关键字参数是 provider 载荷经过清理、限制大小的 JSON 视图（敏感键已脱敏、长字符串已截断、SDK 对象已归一化），`usage` 是一个普通的 token 摘要字典。每个载荷都携带关联字段 `turn_id`、`api_request_id`、`task_id`、`session_id` 和 `api_call_count`，因此插件可以把请求、工具调用和轮次串联起来。`api_request_error` 在 provider 调用抛出异常时触发，并额外提供 `status_code`、`retry_count` / `max_retries`、`retryable`、`reason`，以及一个包含 `type` 和 `message` 的 `error` 字典。

### `pre_llm_call` 上下文注入 {#pre_llm_call-context-injection}

这是唯一一个返回值有意义的钩子。当 `pre_llm_call` 回调返回包含 `"context"` 键的字典（或纯字符串）时，Hermes 会将该文本注入**当前轮次的用户消息**中。这是记忆插件、RAG 集成、护栏以及任何需要向模型提供额外上下文的插件所使用的机制。

#### 返回格式

```python
# 包含 context 键的字典
return {"context": "Recalled memories:\n- User prefers dark mode\n- Last project: hermes-agent"}

# 纯字符串（等同于上面的字典形式）
return "Recalled memories:\n- User prefers dark mode"

# 返回 None 或不返回 → 不注入（仅观察）
return None
```

任何非 None、非空的返回值，只要包含 `"context"` 键（或为非空纯字符串），都会被收集并追加到当前轮次的用户消息中。

#### 超量上下文溢写 {#oversized-context-spill}

每个钩子的上下文默认上限为 `10,000` 个字符。超出上限的部分会被写入 `$HERMES_HOME/hook_outputs/<session_id>/<uuid>.txt`，并替换为首尾预览加上保存路径。如果模型确实需要，可以通过 `read_file` 或 `terminal` 读取完整内容。这可以防止某个失控插件撑大后续每一轮的 prompt，把 prompt 缓存前缀冲掉。可在 `config.yaml` 中调整：

```yaml
hooks:
  output_spill:
    enabled: true          # default: true
    max_chars: 10000       # default; set higher to opt out of spilling
    preview_head: 500      # chars shown at the top of the preview
    preview_tail: 500      # chars shown at the bottom of the preview
    # directory: null      # default: $HERMES_HOME/hook_outputs
```

#### 注入的工作原理

注入的上下文追加到**用户消息**，而非系统提示词（system prompt）。这是有意为之的设计：

- **保留提示词缓存**——系统提示词在各轮次之间保持不变。Anthropic 和 OpenRouter 会缓存系统提示词前缀，保持其稳定可在多轮对话中节省 75% 以上的输入 token。如果插件修改系统提示词，每轮都会缓存未命中。
- **临时性**——注入仅在 API 调用时发生。会话历史中的原始用户消息不会被修改，也不会持久化到会话数据库。
- **系统提示词是 Hermes 的领地**——它包含模型特定的指导、工具执行规则、个性指令和缓存的技能内容。插件在用户输入旁边贡献上下文，而非修改代理的核心指令。

#### 示例：记忆召回插件

```python
"""Memory plugin — recalls relevant context from a vector store."""

import httpx

MEMORY_API = "https://your-memory-api.example.com"

def recall_context(session_id, user_message, is_first_turn, **kwargs):
    """Called before each LLM turn. Returns recalled memories."""
    try:
        resp = httpx.post(f"{MEMORY_API}/recall", json={
            "session_id": session_id,
            "query": user_message,
        }, timeout=3)
        memories = resp.json().get("results", [])
        if not memories:
            return None  # nothing to inject

        text = "Recalled context from previous sessions:\n"
        text += "\n".join(f"- {m['text']}" for m in memories)
        return {"context": text}
    except Exception:
        return None  # fail silently, don't break the agent

def register(ctx):
    ctx.register_hook("pre_llm_call", recall_context)
```

#### 示例：护栏插件

```python
"""Guardrails plugin — enforces content policies."""

POLICY = """You MUST follow these content policies for this session:
- Never generate code that accesses the filesystem outside the working directory
- Always warn before executing destructive operations
- Refuse requests involving personal data extraction"""

def inject_guardrails(**kwargs):
    """Injects policy text into every turn."""
    return {"context": POLICY}

def register(ctx):
    ctx.register_hook("pre_llm_call", inject_guardrails)
```

#### 示例：仅观察钩子（不注入）

```python
"""Analytics plugin — tracks turn metadata without injecting context."""

import logging
logger = logging.getLogger(__name__)

def log_turn(session_id, user_message, model, is_first_turn, **kwargs):
    """Fires before each LLM call. Returns None — no context injected."""
    logger.info("Turn: session=%s model=%s first=%s msg_len=%d",
                session_id, model, is_first_turn, len(user_message or ""))
    # No return → no injection

def register(ctx):
    ctx.register_hook("pre_llm_call", log_turn)
```

#### 多个插件返回上下文

当多个插件从 `pre_llm_call` 返回上下文时，它们的输出以双换行符连接，一起追加到用户消息中。顺序遵循插件发现顺序（按插件目录名称字母排序）。

### 中间件：改变实际发生的事情 {#middleware-change-what-happens}

钩子观察代理循环（外加上文记载的少数几种引导形态）。**中间件则改变实际发生的事情**：请求中间件在任何下游组件看到之前重写实际生效的载荷，执行中间件则包裹实际的调用。在同一个 `register(ctx)` 入口点中注册它：

```python
def cap_find_output(tool_name, args, **kwargs):
    """Rewrite terminal find commands to cap their output."""
    command = args.get("command", "")
    if tool_name == "terminal" and command.startswith("find "):
        return {
            "args": {**args, "command": command + " | head -100"},
            "source": "my-plugin",
            "reason": "cap find output",
        }
    return None  # 保持调用不变

def register(ctx):
    ctx.register_middleware("tool_request", cap_find_output)
```

种类的规范列表是 `hermes_cli/middleware.py` 中的 `VALID_MIDDLEWARE`：

| 种类 | 接收 | 返回约定 |
|------|----------|-----------------|
| `tool_request` | `tool_name`、`args`、`original_args`、上下文关键字参数 | 返回 `{"args": {...}}`，在钩子、护栏、审批和执行看到之前替换实际生效的工具参数。返回 `None` 则保持调用不变。 |
| `llm_request` | `request`、`original_request`、上下文关键字参数 | 返回 `{"request": {...}}`，在 Hermes 发送之前替换实际生效的 provider 关键字参数。 |
| `tool_execution` | 载荷加上 `next_call` | 包裹工具执行。恰好调用一次 `next_call(payload)` 来运行下游链（或跳过它以短路），并返回结果。 |
| `llm_execution` | 载荷加上 `next_call` | 形态相同，包裹 provider 调用。 |

**实践中要紧的规则：**

- 请求中间件是链式的：每个回调看到的是被之前回调重写后的载荷，而 `original_args` / `original_request` 始终携带中间件处理之前的副本。载荷在回调之间会被复制，因此可以随意修改。
- 你可以在返回的字典中包含 `source`、`reason` 和 `name` 字符串。它们会进入中间件追踪记录，下游的观察者钩子会以 `middleware_trace` 关键字参数接收它。
- 执行中间件中的 `next_call` 是**一次性的**。调用两次会抛出异常，因为那会重新运行 provider 或工具。
- 抛出异常的中间件回调会被记录日志并跳过；链会继续。在你的 `next_call` 之后抛出的下游失败会原样传播。中间件永远不会破坏基础运行时路径。
- 中间件载荷会在观察者遥测字段之外携带 `middleware_schema_version`（`hermes.middleware.v1`）。
- 未知种类会在注册时给出警告而不是失败，因此针对较新 Hermes 编写的插件在较旧版本上仍能加载。

### 注册 CLI 命令

插件可以添加自己的 `hermes <plugin>` 子命令树：

```python
def _my_command(args):
    """Handler for hermes my-plugin <subcommand>."""
    sub = getattr(args, "my_command", None)
    if sub == "status":
        print("All good!")
    elif sub == "config":
        print("Current config: ...")
    else:
        print("Usage: hermes my-plugin <status|config>")

def _setup_argparse(subparser):
    """Build the argparse tree for hermes my-plugin."""
    subs = subparser.add_subparsers(dest="my_command")
    subs.add_parser("status", help="Show plugin status")
    subs.add_parser("config", help="Show plugin config")
    subparser.set_defaults(func=_my_command)

def register(ctx):
    ctx.register_tool(...)
    ctx.register_cli_command(
        name="my-plugin",
        help="Manage my plugin",
        setup_fn=_setup_argparse,
        handler_fn=_my_command,
    )
```

注册后，用户可以运行 `hermes my-plugin status`、`hermes my-plugin config` 等命令。

**记忆提供商插件**使用基于约定的方式：在插件的 `cli.py` 文件中添加 `register_cli(subparser)` 函数。记忆插件发现系统会自动找到它——无需调用 `ctx.register_cli_command()`。详见[记忆提供商插件指南](/developer-guide/memory-provider-plugin#adding-cli-commands)。

**活跃提供商限制：** 记忆插件 CLI 命令仅在其提供商是配置中活跃的 `memory.provider` 时才会出现。如果用户尚未设置你的提供商，你的 CLI 命令不会出现在帮助输出中。

### 注册斜杠命令 {#register-slash-commands}

插件可以注册会话内斜杠命令——用户在对话中输入的命令（如 `/lcm status` 或 `/ping`）。这些命令在 CLI 和网关（Telegram、Discord 等）中均可使用。

```python
def _handle_status(raw_args: str) -> str:
    """Handler for /mystatus — called with everything after the command name."""
    if raw_args.strip() == "help":
        return "Usage: /mystatus [help|check]"
    return "Plugin status: all systems nominal"

def register(ctx):
    ctx.register_command(
        "mystatus",
        handler=_handle_status,
        description="Show plugin status",
    )
```

注册后，用户可以在任意会话中输入 `/mystatus`。该命令会出现在自动补全、`/help` 输出和 Telegram 机器人菜单中。

**签名：** `ctx.register_command(name: str, handler: Callable, description: str = "")`

| 参数 | 类型 | 描述 |
|-----------|------|-------------|
| `name` | `str` | 不含前导斜杠的命令名称（例如 `"lcm"`、`"mystatus"`） |
| `handler` | `Callable[[str], str \| None]` | 以原始参数字符串调用。也可以是 `async`。 |
| `description` | `str` | 显示在 `/help`、自动补全和 Telegram 机器人菜单中 |

**与 `register_cli_command()` 的主要区别：**

| | `register_command()` | `register_cli_command()` |
|---|---|---|
| 调用方式 | 会话中的 `/name` | 终端中的 `hermes name` |
| 适用范围 | CLI 会话、Telegram、Discord 等 | 仅终端 |
| 处理器接收 | 原始参数字符串 | argparse `Namespace` |
| 使用场景 | 诊断、状态查询、快速操作 | 复杂子命令树、设置向导 |

**冲突保护：** 如果插件尝试注册与内置命令（`help`、`model`、`new` 等）冲突的名称，注册会被静默拒绝并记录警告日志。内置命令始终优先。

**异步处理器：** 网关分发会自动检测并 await 异步处理器，因此可以使用同步或异步函数：

```python
async def _handle_check(raw_args: str) -> str:
    result = await some_async_operation()
    return f"Check result: {result}"

def register(ctx):
    ctx.register_command("check", handler=_handle_check, description="Run async check")
```

### 从斜杠命令分发工具

需要编排工具的斜杠命令处理器（生成子代理 `delegate_task`、调用 `file_edit` 等）应使用 `ctx.dispatch_tool()`，而非深入框架内部。父代理上下文（工作区提示、spinner、模型继承）会自动连接。

```python
def register(ctx):
    def _handle_deliver(raw_args: str):
        result = ctx.dispatch_tool(
            "delegate_task",
            {
                "goal": raw_args,
                "toolsets": ["terminal", "file", "web"],
            },
        )
        return result

    ctx.register_command(
        "deliver",
        handler=_handle_deliver,
        description="Delegate a goal to a subagent",
    )
```

**签名：** `ctx.dispatch_tool(name: str, args: dict, *, parent_agent=None) -> str`

| 参数 | 类型 | 描述 |
|-----------|------|-------------|
| `name` | `str` | 工具注册表中的工具名称（例如 `"delegate_task"`、`"file_edit"`） |
| `args` | `dict` | 工具参数，与模型发送的格式相同 |
| `parent_agent` | `Agent \| None` | 可选覆盖。省略时从当前 CLI 代理解析（网关模式下优雅降级） |

**运行时行为：**

- **CLI 模式：** `parent_agent` 从活跃的 CLI 代理解析，工作区提示、spinner 和模型选择按预期继承。
- **网关模式：** 没有 CLI 代理，工具优雅降级——工作区从 `TERMINAL_CWD` 读取，不显示 spinner。
- **显式覆盖：** 如果调用者显式传入 `parent_agent=`，则尊重该值，不会被覆盖。

这是从插件命令分发工具的公开稳定接口。插件不应访问 `ctx._cli_ref.agent` 或类似的私有状态。

### 在钩子内部执行动作（profile + 工具）

`ctx._cli_ref` 只在**交互式 CLI** 会话中才有值。在网关中、在非交互式的 `hermes chat -q` 运行中，以及在 **kanban 派生的 worker 会话**中，它都是 `None`——因此任何通过 `_cli_ref` 取值的插件逻辑，恰恰会在这些场景下静默失效。有两个稳定且与会话无关的 API，覆盖了钩子真正需要的能力：

- **`ctx.profile_name`** — 当前活动的 profile 名称（例如 `"default"`，或 kanban worker 中被指派的 profile）。它由 `HERMES_HOME` 推导而来，因此在任何地方都有效，不依赖 `_cli_ref`。
- **`ctx.dispatch_tool(name, args)`** — 调用任何已注册的工具（内置或插件），包括 `kanban_*` 工具、`delegate_task`、`terminal`、`read_file` 等。无论钩子在哪个进程中触发，都可以从钩子回调中使用。

两者结合，就能让一个 kanban 生命周期钩子观察到状态转换并在看板上执行动作，而无需触碰框架内部实现：

```python
def register(ctx):
    def on_blocked(*, task_id, reason=None, **kw):
        # Runs in the worker process; ctx._cli_ref is None here.
        ctx.dispatch_tool("kanban_comment", {
            "task_id": task_id,
            "comment": f"[{ctx.profile_name}] auto-noted block: {reason}",
        })
    ctx.register_hook("kanban_task_blocked", on_blocked)
```

如果要运行完整的 `hermes <subcommand>`（例如 `hermes kanban show`），请通过 `terminal` 工具外壳调用：`ctx.dispatch_tool("terminal", {"command": "hermes kanban show ..."})`——无头 worker 会话没有进程内的斜杠命令桥接，工具才是从钩子驱动 Hermes 的受支持方式。

### 处理 Slack Block Kit 按钮点击

发布带交互元素（按钮、溢出菜单、日期选择器等）的 Block Kit 消息的插件，可以直接把点击处理器注册到 Slack 适配器上——无需对 `slack_bolt.AsyncApp` 打猴子补丁。

```python
def register(ctx):
    async def _on_approve(ack, body, action):
        # ack within 3 seconds — slack_bolt requirement.
        await ack()
        # body["channel"]["id"], body["user"]["id"], body["message"]["ts"]
        # action["action_id"], action["value"]
        sweep_id = (action.get("value") or "").split("|", 1)[-1]
        # ...do the deterministic work, then post a follow-up.

    ctx.register_slack_action_handler("inbox_sweep_approve", _on_approve)
```

**签名：** `ctx.register_slack_action_handler(action_id, callback) -> None`

| 参数 | 类型 | 说明 |
|-----------|------|-------------|
| `action_id` | `str \| re.Pattern \| dict` | `slack_bolt.App.action()` 接受的任何形式：字面量 `action_id`、匹配多个 id 的已编译正则，或形如 `{"action_id": "...", "block_id": "..."}` 的约束字典 |
| `callback` | async callable | 按 slack_bolt 约定接收 `(ack, body, action)` |

**运行时行为：**

- 处理器在插件加载时入队，并在 Slack 平台连接时接入适配器的 `slack_bolt.AsyncApp`。
- 每个回调都会被防御性地包装：如果你的处理器抛出异常，网关会记录错误并尽力 ack 该次点击，让 Slack 停止重试。
- slack_bolt 的常规规则依然适用——在 3 秒内 `await ack()`，然后再做耗时的工作。
- 对于多工作区部署，处理器会对任意已连接工作区的点击触发；如果需要按工作区区分行为，请使用 `body["team"]["id"]`。

这是插件参与 Slack 交互的公开方式。较老的插件可能会修补 `SlackAdapter.connect`；请优先使用本 API。如需完整的 slack_bolt 接口（事件、快捷方式、命令——而不仅仅是 Block Kit 动作），请使用下方通用的 `register_platform_handler("slack", ...)`。

### 注册原生平台处理器（任意平台） {#register-native-platform-handlers-any-platform}

需要接收核心适配器不会路由的平台事件的插件——额外的更新类型、原生按钮回调、回应/成员事件、webhook 路由——可以注册一个处理器工厂，由平台适配器在连接时调用。这适用于**所有**网关平台。

```python
def register(ctx):
    def _wire(native, adapter):
        # native: the platform's client/app object (see table below)
        # adapter: the platform adapter instance (treat as read-only)
        # Import platform SDKs HERE so register() works without them.
        ...

    ctx.register_platform_handler("discord", _wire)
```

**签名：** `ctx.register_platform_handler(platform, factory) -> None`

| 参数 | 类型 | 描述 |
|-----------|------|-------------|
| `platform` | `str` | 网关平台名称，小写（`"telegram"`、`"discord"`、`"slack"`、`"matrix"`，……） |
| `factory` | callable | 在连接时接收 `(native, adapter)` |

**各平台的 `native` 是什么：**

| 平台 | `native` 对象 | 常用挂钩方式 |
|----------|-----------------|---------------|
| `telegram` | PTB `Application` | `add_handler`——任意更新类型、按模式限定的回调 |
| `discord` | `discord.ext.commands.Bot` | `add_listener`——回应、成员事件、线程、语音 |
| `slack` | `slack_bolt.AsyncApp` | `app.event()` / `app.action()` / `app.command()` |
| `matrix` | Matrix 客户端 | 事件回调 |
| `teams` | Teams `App` | `on_message` / `on_card_action` 装饰器 |
| `dingtalk` | `DingTalkStreamClient` | 为其他 stream 主题使用 `register_callback_handler` |
| `feishu` | lark_oapi 客户端 | API 调用；事件路由 |
| `line`、`api_server`、`msgraph_webhook` | aiohttp `web.Application` | `router.add_get/post`——自定义路由（在路由器冻结之前接入） |
| 其他所有平台（whatsapp、signal、irc、email、sms、ntfy、wecom、weixin、bluebubbles、yuanbao，……） | `None` | 连接时钩子；通过 `adapter` 句柄进行操作 |

**运行时行为：**

- 工厂在插件加载时入队，并在平台连接时被调用——对于分发顺序很重要的平台（Telegram、Slack、Teams、aiohttp 路由器），它们会在核心处理器注册**之前**运行，因此限定了范围的插件处理器优先生效，其余一切则继续向下传递。
- **添加到首个匹配分发表中的处理器务必限定范围。** 在 Telegram 上，请使用 `CallbackQueryHandler(..., pattern=r"^myplugin:")`——未限定范围的处理器会吞掉核心的按钮流程（执行审批、模型选择器、澄清提示）。
- 每个工厂相互隔离：如果它抛出异常，错误会被记录，平台照常连接。
- 请在工厂函数体内导入平台 SDK，而不是在模块级别——`register()` 必须在 SDK 未安装时也能正常工作。
- 一个插件可以为多个平台注册工厂；每个工厂只在其对应平台连接时触发。

**Telegram 别名：** `ctx.register_telegram_handler(factory)` 是 `ctx.register_platform_handler("telegram", factory)` 的向后兼容别名。

示例——Telegram，按模式限定的内联按钮：

```python
def register(ctx):
    def _wire(application, adapter):
        from telegram.ext import CallbackQueryHandler

        async def _on_button(update, context):
            query = update.callback_query
            await query.answer()
            # ...handle "myplugin:*" callbacks

        application.add_handler(
            CallbackQueryHandler(_on_button, pattern=r"^myplugin:")
        )

    ctx.register_platform_handler("telegram", _wire)
```

示例——Discord，回应事件：

```python
def register(ctx):
    def _wire(bot, adapter):
        async def on_raw_reaction_add(payload):
            ...  # e.g. reaction-based voting / moderation

        bot.add_listener(on_raw_reaction_add, "on_raw_reaction_add")

    ctx.register_platform_handler("discord", _wire)
```

:::tip
本指南涵盖**通用插件**（工具、钩子、斜杠命令、CLI 命令）。以下各节简要介绍每种专用插件类型的编写模式；每节均链接到其完整指南以获取字段参考和示例。
:::

## 专用插件类型

Hermes 在通用接口之外还有五种专用插件类型。每种都以目录形式存放在 `plugins/<category>/<name>/`（内置）或 `~/.hermes/plugins/<category>/<name>/`（用户）下。各类别的约定不同——选择你需要的类型，然后阅读其完整指南。

### 模型提供商插件——添加 LLM 后端

在 `plugins/model-providers/<name>/` 下放置一个配置文件：

```python
# plugins/model-providers/acme/__init__.py
from providers import register_provider
from providers.base import ProviderProfile

register_provider(ProviderProfile(
    name="acme",
    aliases=("acme-inference",),
    display_name="Acme Inference",
    env_vars=("ACME_API_KEY", "ACME_BASE_URL"),
    base_url="https://api.acme.example.com/v1",
    auth_type="api_key",
    default_aux_model="acme-small-fast",
    fallback_models=("acme-large-v3", "acme-medium-v3"),
))
```

```yaml
# plugins/model-providers/acme/plugin.yaml
name: acme-provider
kind: model-provider
version: 1.0.0
description: Acme Inference — OpenAI-compatible direct API
```

在任何调用 `get_provider_profile()` 或 `list_providers()` 的地方首次使用时懒加载发现——`auth.py`、`config.py`、`doctor.py`、`models.py`、`runtime_provider.py` 和 chat_completions 传输层会自动连接。用户插件按名称覆盖内置插件。

**完整指南：** [模型提供商插件](/developer-guide/model-provider-plugin)——字段参考、可覆盖钩子（`prepare_messages`、`build_extra_body`、`build_api_kwargs_extras`、`fetch_models`）、api_mode 选择、认证类型、测试。

### 平台插件——添加网关频道

在 `plugins/platforms/<name>/` 下放置适配器：

```python
# plugins/platforms/myplatform/adapter.py
from gateway.platforms.base import BasePlatformAdapter

class MyPlatformAdapter(BasePlatformAdapter):
    async def connect(self): ...
    async def send(self, chat_id, text): ...
    async def disconnect(self): ...

def check_requirements():
    import os
    return bool(os.environ.get("MYPLATFORM_TOKEN"))

def _env_enablement():
    import os
    tok = os.getenv("MYPLATFORM_TOKEN", "").strip()
    if not tok:
        return None
    return {"token": tok}

def register(ctx):
    ctx.register_platform(
        name="myplatform",
        label="MyPlatform",
        adapter_factory=lambda cfg: MyPlatformAdapter(cfg),
        check_fn=check_requirements,
        required_env=["MYPLATFORM_TOKEN"],
        # 从环境变量自动填充 PlatformConfig.extra，使仅环境变量的设置
        # 在 `hermes gateway status` 中显示，无需 SDK 实例化。
        env_enablement_fn=_env_enablement,
        # 启用 cron 投递：`deliver=myplatform` 路由到此变量。
        cron_deliver_env_var="MYPLATFORM_HOME_CHANNEL",
        emoji="💬",
        platform_hint="You are chatting via MyPlatform. Keep responses concise.",
    )
```

```yaml
# plugins/platforms/myplatform/plugin.yaml
name: myplatform-platform
label: MyPlatform
kind: platform
version: 1.0.0
description: MyPlatform gateway adapter
requires_env:
  - name: MYPLATFORM_TOKEN
    description: "Bot token from the MyPlatform console"
    password: true
optional_env:
  - name: MYPLATFORM_HOME_CHANNEL
    description: "Default channel for cron delivery"
    password: false
```

**完整指南：** [添加平台适配器](/developer-guide/adding-platform-adapters)——完整的 `BasePlatformAdapter` 约定、消息路由、认证限制、设置向导集成。参考 `plugins/platforms/irc/` 获取仅使用标准库的可用示例。

### 记忆提供商插件——添加跨会话知识后端

在 `plugins/memory/<name>/` 下实现 `MemoryProvider`：

```python
# plugins/memory/my-memory/__init__.py
from agent.memory_provider import MemoryProvider

class MyMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "my-memory"

    def is_available(self) -> bool:
        import os
        return bool(os.environ.get("MY_MEMORY_API_KEY"))

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id

    def sync_turn(self, user_content, assistant_content, *,
                  session_id="", messages=None) -> None:
        ...

    def prefetch(self, query, *, session_id="") -> str:
        ...

    def get_tool_schemas(self) -> list[dict]:
        return []   # required @abstractmethod — see full guide

def register(ctx):
    ctx.register_memory_provider(MyMemoryProvider())
```

记忆提供商是单选的——同一时间只有一个处于活跃状态，通过 `config.yaml` 中的 `memory.provider` 选择。

如果某个提供商同时也作为通用插件加载，则由通用发现机制负责其生命周期钩子。在同一插件来源通过通用发现成功加载之前，记忆加载器只以回退方式提供钩子。重复加载提供商会替换这组回退钩子；组内不同的回调会被保留。这不会对来自不同插件来源的钩子进行去重，也不会改变提供商的激活方式。

**完整指南：** [记忆提供商插件](/developer-guide/memory-provider-plugin)——完整的 `MemoryProvider` ABC、线程约定、配置文件隔离、通过 `cli.py` 注册 CLI 命令。

### 上下文引擎插件——替换上下文压缩器

```python
# plugins/context_engine/my-engine/__init__.py
from agent.context_engine import ContextEngine

class MyContextEngine(ContextEngine):
    @property
    def name(self) -> str:
        return "my-engine"

    def update_from_response(self, usage) -> None: ...
    def should_compress(self, prompt_tokens: int = None) -> bool: ...
    def compress(self, messages, current_tokens=None, focus_topic=None,
                 force=False, memory_context="") -> list: ...

def register(ctx):
    ctx.register_context_engine(MyContextEngine())
```

上下文引擎是单选的——通过 `config.yaml` 中的 `context.engine` 选择。

**完整指南：** [上下文引擎插件](/developer-guide/context-engine-plugin)。

### 图像生成后端

在 `plugins/image_gen/<name>/` 下放置提供商：

```python
# plugins/image_gen/my-imggen/__init__.py
from agent.image_gen_provider import ImageGenProvider

class MyImageGenProvider(ImageGenProvider):
    @property
    def name(self) -> str:
        return "my-imggen"

    def is_available(self) -> bool: ...
    def generate(self, prompt: str, aspect_ratio="landscape", **kwargs) -> dict:
        # returns success_response(...) / error_response(...)
        ...

def register(ctx):
    ctx.register_image_gen_provider(MyImageGenProvider())
```

```yaml
# plugins/image_gen/my-imggen/plugin.yaml
name: my-imggen
kind: backend
version: 1.0.0
description: Custom image generation backend
```

**完整指南：** [图像生成提供商插件](/developer-guide/image-gen-provider-plugin)——完整的 `ImageGenProvider` ABC、`list_models()` / `get_setup_schema()` 元数据、`success_response()`/`error_response()` 辅助函数、base64 与 URL 输出、用户覆盖、pip 分发。

**参考示例：** `plugins/image_gen/openai/`（DALL-E / GPT-Image via OpenAI SDK）、`plugins/image_gen/openai-codex/`、`plugins/image_gen/xai/`（Grok 图像生成）。

## 非 Python 扩展接口

Hermes 也接受完全不是 Python 插件的扩展。这些在[可插拔接口表](/user-guide/features/plugins#pluggable-interfaces--where-to-go-for-each)中有所展示；以下各节简要介绍每种编写方式。

### MCP 服务器——注册外部工具

Model Context Protocol（MCP）服务器无需任何 Python 插件即可将自己的工具注册到 Hermes。在 `~/.hermes/config.yaml` 中声明：

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
    timeout: 120

  linear:
    url: "https://mcp.linear.app/sse"
    auth:
      type: "oauth"
```

Hermes 在启动时连接到每个服务器，列出其工具，并与内置工具一起注册。LLM 看到它们的方式与其他工具完全相同。**完整指南：** [MCP](/user-guide/features/mcp)。

### 网关事件钩子——在生命周期事件时触发

将清单和处理器放入 `~/.hermes/hooks/<name>/`：

```yaml
# ~/.hermes/hooks/long-task-alert/HOOK.yaml
name: long-task-alert
description: Send a push notification when a long task finishes
events:
  - agent:end
```

```python
# ~/.hermes/hooks/long-task-alert/handler.py
async def handle(event_type: str, context: dict) -> None:
    if context.get("duration_seconds", 0) > 120:
        # send notification …
        pass
```

事件包括 `gateway:startup`、`session:start`、`session:end`、`session:reset`、`agent:start`、`agent:step`、`agent:end` 以及通配符 `command:*`。钩子中的错误会被捕获并记录日志——它们不会阻塞主流程。

**完整指南：** [网关事件钩子](/user-guide/features/hooks#gateway-event-hooks)。

### Shell 钩子——在工具调用时运行 shell 命令

如果你只想在工具触发时运行脚本（通知、审计日志、桌面提醒、自动格式化），在 `config.yaml` 中使用 shell 钩子——无需 Python：

```yaml
hooks:
  - event: post_tool_call
    command: "notify-send 'Tool ran: {tool_name}'"
    when:
      tools: [terminal, patch, write_file]
```

支持与 Python 插件钩子相同的所有事件（`pre_tool_call`、`post_tool_call`、`pre_llm_call`、`post_llm_call`、`on_session_start`、`on_session_end`、`pre_gateway_dispatch`），以及用于 `pre_tool_call` 阻断决策的结构化 JSON 输出。

**完整指南：** [Shell 钩子](/user-guide/features/hooks#shell-hooks)。

### 技能来源——添加自定义技能注册表

如果你维护了一个技能 GitHub 仓库（或想从内置来源之外的社区索引拉取），将其添加为 **tap**：

```bash
hermes skills tap add myorg/skills-repo
hermes skills search my-workflow --source myorg/skills-repo
hermes skills install myorg/skills-repo/my-workflow
```

发布你自己的 tap 只需一个包含 `skills/<skill-name>/SKILL.md` 目录的 GitHub 仓库——无需服务器或注册表注册。

**完整指南：** [技能中心](/user-guide/features/skills#skills-hub) · [发布自定义 tap](/user-guide/features/skills#publishing-a-custom-skill-tap)（仓库结构、最小示例、非默认路径、信任级别）。

### 通过命令模板接入 TTS / STT

任何读写音频或文本的 CLI 都可以通过 `config.yaml` 接入——无需 Python 代码：

```yaml
tts:
  provider: voxcpm
  providers:
    voxcpm:
      type: command
      command: "voxcpm --ref ~/voice.wav --text-file {input_path} --out {output_path}"
      output_format: mp3
      voice_compatible: true
```

对于 STT，将 `HERMES_LOCAL_STT_COMMAND` 指向一个按 argv 分词的模板。它在运行时不会进行隐式的 shell 解释；如果可信的本地命令需要 shell 语法，请显式地用 `sh -c`、`cmd /c` 或 PowerShell 包裹它。支持的占位符：`{input_path}`、`{output_path}`、`{format}`、`{voice}`、`{model}`、`{speed}`（TTS）；`{input_path}`、`{output_dir}`、`{language}`、`{model}`（STT）。任何与路径交互的 CLI 都自动成为插件。

**完整指南：** [TTS 自定义命令提供商](/user-guide/features/tts#custom-command-providers) · [STT](/user-guide/features/tts#voice-message-transcription-stt)。

## 通过 pip 分发 {#distribute-via-pip}

如需公开分享插件，在你的 Python 包中添加 entry point：

```toml
# pyproject.toml
[project.entry-points."hermes_agent.plugins"]
my-plugin = "my_plugin_package"
```

```bash
pip install hermes-plugin-calculator
# 下次 hermes 启动时自动发现插件
```

## 为 NixOS 分发

:::warning Nix 已不再被明确支持
Nix/NixOS 已不再是明确支持的安装方式（仅按尽力而为维护）——参见 [Nix 安装配置](/getting-started/nix-setup)。保留本节是为了照顾已经在 NixOS 上部署的用户。
:::

如果你提供了带有 entry points 的 `pyproject.toml`，NixOS 用户可以声明式安装你的插件：

**Entry-point 插件**（推荐用于分发）：
```nix
# User's configuration.nix
services.hermes-agent.extraPythonPackages = [
  (pkgs.python312Packages.buildPythonPackage {
    pname = "my-plugin";
    version = "1.0.0";
    src = pkgs.fetchFromGitHub {
      owner = "you";
      repo = "hermes-my-plugin";
      rev = "v1.0.0";
      hash = "sha256-...";  # nix-prefetch-url --unpack
    };
    format = "pyproject";
    build-system = [ pkgs.python312Packages.setuptools ];
  })
];
```

**目录插件**（无需 `pyproject.toml`）：
```nix
services.hermes-agent.extraPlugins = [
  (pkgs.fetchFromGitHub {
    owner = "you";
    repo = "hermes-my-plugin";
    rev = "v1.0.0";
    hash = "sha256-...";
  })
];
```

完整文档（包括 overlay 用法和冲突检查）见 [Nix 设置指南](/getting-started/nix-setup#plugins)。

## 常见错误

**处理器未返回 JSON 字符串：**
```python
# 错误——返回了字典
def handler(args, **kwargs):
    return {"result": 42}

# 正确——返回 JSON 字符串
def handler(args, **kwargs):
    return json.dumps({"result": 42})
```

**处理器签名缺少 `**kwargs`：**
```python
# 错误——Hermes 传入额外上下文时会报错
def handler(args):
    ...

# 正确
def handler(args, **kwargs):
    ...
```

**处理器抛出异常：**
```python
# 错误——异常传播，工具调用失败
def handler(args, **kwargs):
    result = 1 / int(args["value"])  # ZeroDivisionError!
    return json.dumps({"result": result})

# 正确——捕获异常并返回错误 JSON
def handler(args, **kwargs):
    try:
        result = 1 / int(args.get("value", 0))
        return json.dumps({"result": result})
    except Exception as e:
        return json.dumps({"error": str(e)})
```

**Schema 描述过于模糊：**
```python
# 差——模型不知道何时使用
"description": "Does stuff"

# 好——模型清楚地知道何时以及如何使用
"description": "Evaluate a mathematical expression. Use for arithmetic, trig, logarithms. Supports: +, -, *, /, **, sqrt, sin, cos, log, pi, e."
```