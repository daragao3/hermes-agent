---
sidebar_position: 95
title: 工具搜索
description: "当挂载了大量 MCP 与插件工具时，只检索本轮真正需要的工具，避免 schema 占满上下文窗口"
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
tool_search(queries, limit?)   — search the deferred-tool catalog (one or more queries)
tool_describe(names)           — load the full schemas for one or more tools
tool_call(name, arguments)     — invoke a deferred tool
```

一次典型的交互如下：

```
Model: tool_search(["create a github issue", "send a slack message"])
  → { results: [ { query: "create a github issue",
                   matches: ["mcp_github_create_issue", ...] },
                 { query: "send a slack message",
                   matches: ["mcp_slack_post_message", ...] } ],
      tools: { mcp_github_create_issue: { description: "...",
                                          required: ["title"], ... },
               mcp_slack_post_message: { ... } } }
Model: tool_describe(["mcp_github_create_issue", "mcp_slack_post_message"])
  → { tools: { mcp_github_create_issue: { parameters: { ... } },
               mcp_slack_post_message: { parameters: { ... } } } }
Model: tool_call("mcp_github_create_issue", { title: "...", body: "..." })
  → { ok: true, issue_number: 42 }
```

一次 `tool_search` 调用中的每个查询都会针对同一个目录独立检索
（`limit` 按每个查询分别生效）；各查询分组只携带工具名，而共享的
`tools` 映射则为每个命中的工具只存放一次其描述和必填参数名。查询会做
词干化处理，因此 "issues" 也能找到 `create_issue`。任何没有命中的查询
分组都会附带一份已连接服务器的 `available_sources` 摘要，以免把一次
词法上的未命中误当成能力缺失。
`tool_describe` 在一次调用中解析所有请求的名称；未知名称会在
`not_found` 中报告，而不会让整批请求失败。

当模型调用 `tool_call` 时，Hermes 会**拆开桥接层**，
完全按照模型直接调用该工具的方式来派发底层工具。工具调用前 hook、护栏、
审批提示以及工具调用后 hook，全部针对真实的工具名运行——而不是针对
`tool_call`。CLI 和网关中的活动流同样会拆开桥接层，因此你看到的是
底层工具，而不是桥接工具。

## 什么时候会启用？

工具搜索采用**分层披露**：只要存在*任何*可延迟加载的（MCP/插件）工具，
就会启用桥接层；随目录规模变化的是目录中有多少内容保持可见，而不是
schema 是否被延迟加载。

| 层级 | 条件 | 模型看到的内容 |
| --- | --- | --- |
| **0** | 没有 MCP/插件工具 | 所有工具都直接加载，没有桥接层。纯直通。 |
| **1** | 延迟加载目录的清单在预算之内 | 桥接层 + 一份技能风格的清单，列出每个延迟加载的工具（名称 + 简短描述，超出预算时降级为仅名称）。降级是**按服务器**进行的：当一个超大的服务器（Cloudflare）与若干小服务器（Linear）同时挂载时，小服务器保留逐工具的清单，只有超大的服务器被压缩为一行摘要。 |
| **2** | 即使每个服务器都只列名称，逐工具清单仍超出预算（例如仅 Cloudflare 的扁平 API 面：约 3,300 个工具，光名称就约 32K token） | 仅有桥接层 + 每个服务器一行的摘要（服务器名 + 工具数量），让模型知道哪些领域可以访问；具体工具只能通过 `tool_search` 发现。 |

清单预算为 `min(threshold_pct% of context, listing_max_tokens)`。
这个判断在每次构建工具数组时都会重新评估，因此会话中途新增或移除
MCP 服务器，会在下一次组装时让会话在不同层级之间切换。

## 配置

```yaml
tools:
  tool_search:
    enabled: auto       # auto (default), on, or off
    threshold_pct: 5    # listing budget as a percentage of context
    search_default_limit: 5
    max_search_limit: 25
    listing: auto       # embed a grouped name+description catalog manifest
    listing_max_tokens: 4000
```

| 键 | 默认值 | 含义 |
| --- | --- | --- |
| `enabled` | `auto` | `auto`/`on` 只要存在至少一个可延迟加载的工具就会启用；`off` 表示完全禁用（所有工具都直接加载）。`auto` 目前是 `on` 的别名——它被保留给未来的一种模式：schema 能放进上下文时就内联，放不下时才延迟加载。如果你希望在升级后仍保证今天的行为，请固定为 `on` 或 `off`。 |
| `threshold_pct` | `5` | 清单预算，以当前模型上下文长度的百分比表示。取值范围 0–100。 |
| `search_default_limit` | `5` | 模型调用 `tool_search` 且未指定 `limit` 时，每个查询返回的命中数。 |
| `max_search_limit` | `25` | 模型可通过 `limit` 请求的硬性上限（按每个查询计）。取值范围 1–50。 |
| `listing` | `auto` | 在 `tool_search` 桥接工具的描述中嵌入一份技能风格的清单，列出每个延迟加载的工具（名称 + 其描述的第一句，≤60 个字符，按 MCP 服务器分组）。`auto` 在预算允许时包含它（依次回退为仅名称，再到第 2 层的服务器摘要）；`on`/`off` 则强制开启或关闭。 |
| `listing_max_tokens` | `4000` | 嵌入清单的绝对上限，与上下文大小无关。取值范围 200–60000。大型目录会降级为仅名称或按服务器摘要，完整 schema 仍可通过搜索获得。 |

每次调用的数组上限是内部安全边界，而不是配置项。超出上限的调用会返回
错误，以便模型用更小的批次重试。

### 为什么要有清单

没有清单时，延迟加载的能力是*不可见的*——实时基准测试显示，模型会用可见的
核心工具来替代（在终端里运行 `gh`，而不是去搜索延迟加载的 GitHub 工具），
或者直接宣称某项能力不存在，而不去调用 `tool_search`。清单把技能模式
应用到了工具上：每项能力始终可以按名称被发现，而完整的参数 schema 依然
保持延迟加载。如果模型在清单中看到了确切的工具名，就可以跳过
`tool_search`，直接调用 `tool_describe`，省去一次往返。

你也可以改用旧版的布尔写法：

```yaml
tools:
  tool_search: true   # equivalent to {enabled: auto}
```

## 什么时候不该使用

工具搜索是用一份固定的每轮 token 开销（三个桥接工具的 schema 加上目录清单）
和冷工具上至少一次额外的往返（描述 → 调用），来换取延迟加载 schema 上的
节省。在第 1 层，清单让每项能力都保持可见，因此发现环节的那次往返通常
会消失——模型会直接调用 `tool_describe`。实时基准测试显示，清单模式的
任务成功率与直接加载持平，而开销却低于仅有桥接层的模式。

如果你希望小工具集保持旧的始终直接加载行为，请设置 `enabled: off`。

## 无法消除的权衡

以下几点源自提示词缓存完整性这一不变量——它们是任何渐进披露设计所固有的，
并非本实现特有：

- **冷工具会多一次往返。** 模型第一次需要某个延迟加载的工具时，
  会额外花费一到两次模型调用来查找并加载其 schema。静态部分节省的
  token 是真实的，但其中一部分会在运行时被偿还回去。
- **延迟加载的 schema 得不到缓存收益。** 已加载的 `tool_describe`
  结果会进入对话历史（因此在后续轮次中确实会被缓存），但它永远无法
  享受系统提示词的缓存前缀。
- **延迟加载的 schema 没有 provider 原生校验。** `tool_describe`
  让模型能读到延迟加载工具的 schema，但 provider 看到的仍然只是通用的
  `tool_call.arguments` 对象。因此 Hermes 会在派发前在本地对底层参数进行
  强制转换和校验；对于 Hermes 无法安全校验的 schema（例如格式错误的
  schema 或外部引用），仍由具体工具或 MCP 服务器负责。
- **依赖模型质量。** 工具搜索假定模型能为它想要的工具写出一个
  合理的搜索查询。较小的模型在这方面表现更差；Anthropic 公布的数据
  （Opus 4 上使用与不使用工具搜索分别为 49% → 74%）显示了收益，
  但也说明仍有约 26 个百分点的准确率损失来自检索失败。
- **工具集变更会让缓存失效。** 会话中途新增或移除工具会改变桥接工具的
  描述（其中包含延迟加载工具的数量）以及目录，因此提示词缓存会
  失效。这与任何工具集变更面临的权衡完全相同。

## 实现细节

- **检索：** 对分词后的工具名、来源名（该工具所属的 MCP 服务器或插件
  工具集，因此即使某个工具自身的名称不含服务名，搜索 `"linear"` 也能找到
  该服务器的工具）、描述以及参数名做 BM25，并对索引和查询同时应用
  Snowball 词干化（英语），使词形变体也能匹配（"issues" 能找到
  `create_issue`）。当没有任何查询词元匹配任何文档时，回退到对工具名的
  字面子串匹配（例如搜索 `"hub"`，而词元是 `github`）。
- **并行执行会拆开桥接层。** 批处理规划器根据 `tool_call` 的*底层*工具
  来决定并发，而不是根据字面上的桥接工具名——因此通过
  `supports_parallel_tool_calls: true` 选择加入并发的 MCP 服务器，在其工具
  经由桥接层调用时仍保持并发，而 `tool_search` / `tool_describe` 查找也会
  像任何只读工具一样并发批处理。
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
