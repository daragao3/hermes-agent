---
title: 工具搜索
sidebar_position: 95
---

# 工具搜索

当一个会话挂载了大量 MCP 服务器或非核心插件工具时，它们的 JSON schema
会在每一轮对话中占用相当可观的一部分上下文窗口——即便其中只有少数几个
与用户实际的提问相关。

**工具搜索（Tool Search）** 就是 Hermes 针对这一问题提供的可选式渐进披露层。
一旦启用，模型可见的工具数组中的 MCP 工具与插件工具会被三个桥接工具替代，
模型再按需加载每个具体工具的 schema。

:::info Hermes 内置工具永不延迟加载
构成 Hermes 核心能力集的工具（`terminal`、
`read_file`、`write_file`、`patch`、`search_files`、`todo`、`memory`、
`browser_*`、`web_search`、`web_extract`、`clarify`、`execute_code`、
`delegate_task`、`session_search`，以及
`_HERMES_CORE_TOOLS` 中的其余工具）*始终*直接加载。只有 MCP 工具和
非核心插件工具才可能被延迟加载。
:::

## 工作原理

当某一轮启用工具搜索时，模型会在被延迟加载的工具位置上看到三个新工具：

```
tool_search(query, limit?)     — 搜索延迟加载工具目录
tool_describe(name)            — 加载某个工具的完整 schema
tool_call(name, arguments)     — 调用一个延迟加载的工具
```

一次典型的交互如下：

```
Model: tool_search("create a github issue")
  → { matches: [{ name: "mcp_github_create_issue", ... }, ...] }
Model: tool_describe("mcp_github_create_issue")
  → { parameters: { type: "object", properties: { ... } } }
Model: tool_call("mcp_github_create_issue", { title: "...", body: "..." })
  → { ok: true, issue_number: 42 }
```

当模型调用 `tool_call` 时，Hermes 会**拆开桥接层**，
完全按照模型直接调用该工具的方式来派发底层工具。工具调用前 hook、护栏、
审批提示以及工具调用后 hook，全部针对真实的工具名运行——而不是针对
`tool_call`。CLI 和网关中的活动流同样会拆开桥接层，因此你看到的是
底层工具，而不是桥接工具。

## 什么时候会启用？

默认情况下工具搜索运行在 `auto` 模式：只有当可延迟加载的工具 schema
将占用当前模型上下文窗口至少 10% 时才会启用。低于该比例时，工具数组的
组装是纯粹的直通，不产生任何开销。

这个判断在每次构建工具数组时都会重新评估，因此：

- 只挂载了少量 MCP 工具、且模型上下文很长的会话，永远不会启用
  工具搜索。
- 挂载了大量 MCP 服务器的会话（通常 15 个以上工具）会开始
  启用它。
- 会话中途移除 MCP 服务器后，下一次组装会正确地回到直接暴露的方式。

## 配置

```yaml
tools:
  tool_search:
    enabled: auto       # auto（默认）、on 或 off
    threshold_pct: 10   # 上下文占比——仅在 auto 模式下使用
    search_default_limit: 5
    max_search_limit: 20
```

| 键 | 默认值 | 含义 |
| --- | --- | --- |
| `enabled` | `auto` | `auto` 表示超过阈值时启用；`on` 表示只要存在至少一个可延迟加载的工具就始终启用；`off` 表示完全禁用。 |
| `threshold_pct` | `10` | `auto` 模式生效的上下文长度百分比。取值范围 0–100。 |
| `search_default_limit` | `5` | 模型调用 `tool_search` 且未指定 `limit` 时返回的命中数。 |
| `max_search_limit` | `20` | 模型可通过 `limit` 请求的硬性上限。取值范围 1–50。 |

你也可以改用旧版的布尔写法：

```yaml
tools:
  tool_search: true   # 等价于 {enabled: auto}
```

## 什么时候不该使用

工具搜索是用一份固定的每轮 token 开销（三个桥接工具的 schema，约 300 token）
和至少一次额外的往返（搜索 → 描述 → 调用），来换取延迟加载 schema 上的
节省。当你工具很多、而每轮只用到少数几个时，这是明显的净收益；当你的
工具总数本就很少时，它就只是开销。

`auto` 默认值已经替你处理了这一点。如果你无条件设置 `enabled: on`，
在小工具集上要预期会有轻微的每轮开销。

## 无法消除的权衡

以下几点源自提示词缓存完整性这一不变量——它们是任何渐进披露设计所固有的，
并非本实现特有：

- **冷工具会多一次往返。** 模型第一次需要某个延迟加载的工具时，
  会额外花费一到两次模型调用来查找并加载其 schema。静态部分节省的
  token 是真实的，但其中一部分会在运行时被偿还回去。
- **延迟加载的 schema 得不到缓存收益。** 已加载的 `tool_describe`
  结果会进入对话历史（因此在后续轮次中确实会被缓存），但它永远无法
  享受系统提示词的缓存前缀。
- **依赖模型质量。** 工具搜索假定模型能为它想要的工具写出一个
  合理的搜索查询。较小的模型在这方面表现更差；Anthropic 公布的数据
  （Opus 4 上使用与不使用工具搜索分别为 49% → 74%）显示了收益，
  但也说明仍有约 26 个百分点的准确率损失来自检索失败。
- **工具集变更会让缓存失效。** 会话中途新增或移除工具会改变桥接工具的
  描述（其中包含延迟加载工具的数量）以及目录，因此提示词缓存会
  失效。这与任何工具集变更面临的权衡完全相同。

## 实现细节

- **检索：** 对分词后的工具名 + 描述 + 参数名做 BM25。当 BM25 返回
  不到任何正分命中时，回退到对工具名的字面子串匹配，以此防范
  零 IDF 的退化情形（例如在一个所有工具名都包含 "github" 的目录中
  搜索 `"github"`）。
- **目录跨轮次无状态。** 它在每次组装时从当前的工具定义列表重建——
  没有以会话为键的 `Map`。这避免了那一类“存储的目录与实时工具注册表
  逐渐失同步”的 bug。
- **目录的作用域限定在会话自身的工具集内。** `tool_search`、
  `tool_describe` 和 `tool_call` 只能看到并调用该会话确实被授予的工具。
  被限制为工具集子集的子智能体、kanban worker 或网关会话，无法借助桥接
  去发现或调用该子集之外的工具——延迟加载目录是会话自身启用/禁用工具集
  中可延迟加载的那一部分，而不是整个进程注册表。
- **没有 JS 沙箱。** Hermes 采用更简单的“结构化工具”模式
  （search / describe / call 三个普通函数）。某些其他实现提供的
  JS 沙箱“代码模式”攻击面很大；我们不做这一层。

## 另请参阅

- `tools/tool_search.py` —— 实现代码
- `tests/tools/test_tool_search.py` —— 回归测试套件
- 最初实现 PR 中的 `openclaw-tool-search-report` PDF，其中包含塑造了
  本设计的研究材料
