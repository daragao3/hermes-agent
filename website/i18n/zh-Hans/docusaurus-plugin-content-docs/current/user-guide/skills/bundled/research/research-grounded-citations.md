---
title: "Grounded Citations —— 让回答和文档建立在有引用、可核验的来源之上"
sidebar_label: "Grounded Citations"
description: "让回答和文档建立在有引用、可核验的来源之上"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Grounded Citations

让回答和文档建立在有引用、可核验的来源之上。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/research/grounded-citations` |
| 版本 | `1.2.0` |
| 作者 | Hermes Agent + Teknium |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Research`, `Citations`, `Grounding`, `Sources`, `Web`, `Reports` |
| 相关 skill | [`arxiv`](/user-guide/skills/bundled/research/research-arxiv), [`pdf`](/user-guide/skills/bundled/productivity/productivity-pdf), [`reddit-reading`](/user-guide/skills/optional/social-media/social-media-reddit-reading), [`rss-feeds`](/user-guide/skills/optional/research/research-rss-feeds), [`youtube-content`](/user-guide/skills/bundled/media/media-youtube-content) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Grounded Citations

每一条取自外部来源的论断，都会获得一个行内编号引用和一份
`Sources:` 列表，风格类似 Perplexity。一个台账脚本负责维护 `url → [n]` 映射，
因此编号和 URL 都来自检索，而不是来自记忆——模型只会
输出别人交给它的小整数。

对于高风险的工作，同一个台账还兼作事实核查链：逐字
引文会附加到每个来源上（除非它确实出现在抓取到的页面文本中，否则会被拒绝），
来自模型知识的论断会被标记为 `[unverified]`，而
`verify --evidence` 会让任何所引来源没有证据的草稿检查失败。

此 skill 涵盖聊天中的回答、书面文档（markdown、PDF、docx、
幻灯片）以及研究报告。它不涵盖学术 BibTeX 流程——
会议论文请使用 `arxiv` skill，本 skill 可以为它
提供输入（参见 `references/citation-formats.md`）。

## 何时使用 {#when-to-use}

只要回答或产出物依赖于你抓取到的信息（而不是你本来就知道的），
就应当使用：

- 研究、对比、新闻摘要、"X 目前的状况如何"
- 你写入磁盘的任何交付物，只要它引用、转述或报告了
  外部事实——报告、简报、文档、演示文稿、wiki 页面
- 用户会想要核对你工作的事实调查
- 需要为相互矛盾的来源分别标注出处的多来源综合

当检索只是另一项任务的附带环节时，可以省略行内引用——例如编码过程中
快速查一下语法/版本、闲聊、创意写作。
只有在用户很可能想要该链接时才提及 URL。

## 前置条件 {#prerequisites}

除标准工具集外无其他要求。`scripts/sources.py` 是仅依赖标准库的 Python 3 脚本。
检索来自已配置的任何工具：`web_search`、`web_extract`、
`browser_navigate` 或 `terminal`（curl、各类 CLI）。

台账位置：`$HERMES_HOME/cache/citations/ledger.json`（感知 profile）。
可按任务用 `--ledger <path>` 或 `HERMES_CITATION_LEDGER` 覆盖。

## 运行方式 {#how-to-run}

```bash
S=~/.hermes/skills/research/grounded-citations/scripts/sources.py

python "$S" reset                                  # 开始一个干净的台账
python "$S" add https://example.com/a --title "A"  # 输出：[1]
python "$S" add https://example.com/b --title "B"  # 输出：[2]
python "$S" list                                   # 台账表格
python "$S" render                                 # Sources: 区块
python "$S" verify draft.md                        # 捕获错误的引用
```

`add` 是幂等的，并且会对 URL 做规范化：在同一个台账中，同一页面总是返回相同的
id，因此在多轮搜索/提取之间 id 保持稳定。

## 快速参考 {#quick-reference}

| 操作 | 命令 |
|---|---|
| 为新任务创建全新台账 | `sources.py reset` |
| 登记一个来源并获取其 id | `sources.py add <url> [--title T]` |
| 一次登记多个来源 | `sources.py add <url1> <url2> ...` |
| 从 JSON 工具输出中登记 | `sources.py ingest results.json` |
| 为来源附加逐字证据 | `sources.py quote <id> --text "exact wording" --from page.txt` |
| 显示台账 | `sources.py list [--json]` |
| 渲染 Sources 区块 | `sources.py render [--style markdown\|plain\|footnotes\|bibtex\|evidence] [--only 1,3]` |
| 只渲染草稿中引用到的来源 | `sources.py render --cited-in draft.md` |
| 就地重写草稿中的 Sources 区块 | `sources.py render --replace-in draft.md` |
| 检查草稿的引用 | `sources.py verify draft.md [--strict] [--min-coverage 0.6] [--evidence]` |

## 操作步骤 {#procedure}

① 在一项将产出有据可依的回答或文档的任务开始时，**重置台账**。
如果是继续一项草稿中已有 id 的工作，则跳过重置——复用台账可以保持编号稳定。

② **在检索时登记每一个来源。** 每次 `web_search` /
`web_extract` / `browser_navigate` / 抓取之后，把 URL 传给 `sources.py add`
（或把原始 JSON 通过管道传给 `sources.py ingest`）。要在撰写正文*之前*这样做。
事后凭记忆登记，正是这个 skill 所要防止的失败模式。

③ **边写边引用。** 把方括号 id 紧跟在
该来源所支持的每个句子之后：

```
Ice floats because it is less dense than liquid water.[1][2]
```

- 方括号前不加空格；每个 id 使用各自的方括号。
- 每句最多 3 个 id。逐句引用，而不是在末尾一股脑堆上。
- 只使用台账返回的 id。绝不要编造 id 或 URL。
- 来自你自身知识的论断不加引用。
- 来源相互矛盾时：两种说法都要呈现，各自带上自己的 id。
- 按来源的原样引用确切的数字、日期和名称；明确标出缺口
  （"no source found for X"），而不是把它们粉饰过去。

④ 使用 `sources.py render --cited-in <draft>` **追加 Sources 区块**，这样
id → URL 映射就是从台账机械生成的，而不是重新手打。
对于非 markdown 目标，选择对应的 `--style`，并按照
`references/citation-formats.md` 放置（docx 中用脚注，
PDF/LaTeX 中用尾注，演示文稿中用一页 Sources 幻灯片，wiki 输出中按页列出来源）。

⑤ **交付前先验证**——当存在未知 id、Sources 区块与台账不一致，
或（使用 `--min-coverage` 时）正文引用过于稀疏时，`sources.py verify <draft>` 会以非零状态退出。
修正后重新运行。

⑥ **聊天回答**遵循相同的步骤，草稿就是你的回复：登记
来源、行内引用、以渲染好的 `Sources:` 列表结尾。对于简短的回答，
你可以用 `sources.py render --only <ids>` 渲染区块，而不必
写入文件。

## 多平台综合检索 {#multi-platform-sweeps}

"大家对 X 怎么看" / "在网上全面研究 X" 并不是一次
`web_search` 就能搞定的。要在多种来源类型之间展开、并行收集，然后进行综合，
并把每条论断都归属到它所来自的平台：

| 来源类型 | 途径 | 它补充了什么 |
|---|---|---|
| 开放网络 | `web_search` → `web_extract` | 官方文档、文章、公告 |
| 社区讨论 | `reddit-reading`（`search`、`thread`） | 真实的用户体验、抱怨、变通办法 |
| 博客 / 发布 / 更新日志 | `rss-feeds`（`read`、`discover`） | 带日期的一手帖子、版本历史 |
| 视频 | `youtube-content` | 演练、演示、演讲 |
| 代码 | `terminal` 配合 `gh search repos` / `gh search issues` | 实现、未解决的 bug |
| X/Twitter | `xurl`（需要 API 访问权限） | 公告、开发者讨论 |

`reddit-reading` 和 `rss-feeds` skill 是可选的。如果没有安装，请在使用前通过
`hermes skills install official/social-media/reddit-reading` 或
`hermes skills install official/research/rss-feeds` 安装。

每条途径得到的每个 URL，一到手就登记进台账（步骤 ②）。把
观点和测量区分开：一个 Reddit 帖子是用户*报告*了某件事的证据，
而不是那件事为真的证据；要么为它配上一手来源，要么把它标注为
舆情。报告各平台的覆盖缺口（"Reddit search returned nothing
newer than March"），而不是悄悄地只保留有结果的那部分。

## 事实核查模式 {#fact-checking-mode}

对于读者必须能够核查整个链条的工作——医疗、法律、
金融、安全、有争议的论断，或者用户要求做事实核查时——
要从引用升级为证据：

① **为每个来源附加一段逐字引文。** 提取页面后，把它的
文本保存到文件中，并附上承载每条论断的那一句（或几句）：

```bash
python "$S" quote 1 --text "Ice is about 9% less dense than liquid water." --from page1.txt
```

除非该引文逐字出现在证据文本中，否则会被拒绝
（对空白、大小写和 markdown 标记不敏感——提取文本中像
`_[ERAP1](https://…)_` 这样的行内链接可以匹配读者看到的纯文本），
因此转述或记错的数字无法冒充证据。
从抓取到的文本中复制粘贴；绝不要重新手打。按读者所见的样子引用句子——
匹配器会替你看穿提取器的标记，所以
你不必在引文中重现链接语法或转义的星号。

② **用 `[unverified]` 标记来自模型知识的论断。** 对于一条你无法找到来源、
但又至关重要的论断，给它一个明确的标记，而不是引用：

```
The refactor likely predates the 2.0 release.[unverified]
```

`verify --min-coverage` 会把带 `[unverified]` 的句子算作已覆盖——目标
是为每条论断声明出处，而不是在每个句子上都加引用。
如果某条关键论断可以核查，就去核查；`[unverified]` 只用于确实无法核查的内容，
而一份被 `[unverified]` 标记占据主导的事实核查交付物
应当在其摘要中说明这一点。

③ **用第二个独立来源交叉核对有争议的事实。** 当两个
来源不一致时，把两种说法连同各自的 id 和引文一起引用，并说明
你更看重哪一个以及原因。一个来源只是报道；两个独立来源才是
佐证。

④ **用证据关卡进行验证，并渲染证据区块：**

```bash
python "$S" verify report.md --evidence --min-coverage 0.5
python "$S" render --style evidence --replace-in report.md
```

如果任何被引用的来源没有附加引文，`--evidence` 会让草稿检查失败。
`evidence` 渲染样式会在每个来源的 URL 下方打印它的引文，因此
交付物会展示论断 → 来源 → 确切的支撑文本，没有任何内容需要凭
信任接受。使用 `--replace-in <draft>` 就地重写已有的 Sources 区块
（幂等——附加更多引文后可以安全地重新运行）；`--cited-in` 则改为输出
到 stdout。两者都会输出标题 `## Sources`（`--style plain` 输出
`Sources:`）。

**`--min-coverage` 统计的是什么。** 覆盖率为
`sentences with declared provenance / prose sentences`。在去掉 Sources 区块、标题（`#`）、
表格行（`|`）和围栏代码之后，一个正文句子是指一个包含 4 个或以上单词的
非空行片段；引用块标记会被去除。
出处可以通过 `[n]` 引用或 `[unverified]` 标记来声明，
因此同时带有两者的句子只计一次。先不带阈值运行 `verify`，
阅读 `info: stats:` 那一行查看计数，然后再选定一个数值。

## 常见陷阱 {#pitfalls}

- **写完之后才登记。** 台账必须根据工具输出来填充，
  而不是从草稿中重建——那样恰恰会重新引入编号机制所消除的
  幻觉 URL 风险。
- **任务中途重新编号。** 绝不要手动编辑草稿中的 id。id 是台账中的
  身份标识；如果草稿引用了 `[4]`，`[4]` 就必须始终是那个来源。只在
  任务之间运行 `reset`。
- **把 URL 重新手打进 Sources 区块。** 始终使用 `render`。手打的 URL
  就是一条未经验证的论断。
- **把搜索摘要当作你读过的页面来引用。** `web_search` 的
  描述只能支持它字面上所说的内容。当论断需要正文时，要引用提取后的页面
  ——先对它执行 `web_extract`。
- **过度引用。** 一个句子三个 id 是上限；每个分句都加引用
  会让文本难以阅读，也会掩盖到底是哪个来源在承担论证。
- **在代码/配置产出物中引用台账。** 来源注释属于
  正文交付物和文档头部，而不属于生成的代码内部。
- **并行子 agent。** 每个子 agent 都有自己的工作目录；如果它们的
  输出会被合并，就用 `--ledger`（或 `HERMES_CITATION_LEDGER`）让它们都指向同一个台账，
  否则它们的 id 会发生冲突。
- **从摘要而不是页面中摘取引文。** 证据引文必须来自
  提取出的页面文本，而不是搜索结果的描述——先 `web_extract`，
  保存文本，然后对该文件执行 `quote --from`。
- **在 `quote --text` 中转述。** 逐字检查会拒绝它；正确的
  做法是找到真实的句子，而不是不断改写直到能匹配上。
- **把 `[unverified]` 当作逃生口。** 它用于标记确实无法找到来源的
  少数论断；如果大多数句子都带着它，说明该任务需要的是更多
  检索，而不是更多标记。
- **手动编辑 Sources 区块。** 使用 `render --replace-in <draft>`；自己
  切分文件有可能留下过时或重复的区块，随后会被 `verify` 标记出来。

## 验证 {#verification}

```bash
python "$S" verify report.md --strict --min-coverage 0.5
```

绿色表示：草稿中的每个 `[n]` 都存在于台账中，Sources 区块
恰好列出了被引用的 id 及台账中的 URL，并且承载来源的句子中
被引用的比例达到了阈值。即使退出码为 0，也要阅读警告——
已登记却未被引用的来源通常意味着某条论断在编辑过程中丢失了出处。
