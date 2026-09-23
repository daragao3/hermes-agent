---
title: "Simple English — 将文本改写为 ASD-STE100 简化技术英语"
sidebar_label: "Simple English"
description: "将文本改写为 ASD-STE100 简化技术英语"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Simple English

将文本改写为 ASD-STE100 简化技术英语（Simplified Technical English）。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/creative/simple-english` 安装 |
| 路径 | `optional-skills/creative/simple-english` |
| 版本 | `1.2.0` |
| 作者 | AminBlg (https://github.com/AminBlg/SimpleEnglish)，由 Hermes Agent 移植 |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `writing`, `documentation`, `ste`, `asd-ste100`, `technical-writing`, `editing`, `anti-ai-slop` |
| 相关 skill | [`humanizer`](/user-guide/skills/bundled/creative/creative-humanizer) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Simple English：像航空航天手册一样写作 {#simple-english-write-like-an-aerospace-manual}

按照 ASD-STE100 简化技术英语（STE）的规则撰写技术文本。STE 是航空航天和国防制造商用于维护文档的受控语言。这些规则的存在，是为了让一个疲惫的、母语不是英语的读者不会误读任何一条指令。作为副作用，它们还会去除 AI 生成文本的常见特征：长句、同义词轮换、含糊其辞、填充语和装饰性从句。

为那个疲惫的读者而写。每个句子都必须经得起只读一遍。

## 如何在 Hermes 中使用 {#how-to-use-it-in-hermes}

文本通常以以下三种方式之一到达：

1. **内联。** 用户把文本粘贴在消息中。就地改写，并回复改写结果。
2. **文件。** 用户指向一个文件（README、运行手册、文档页面）。用 `read_file` 加载它，然后用 `patch` 进行针对性的分节改写，或用 `write_file` 进行整体改写。绝不要改动代码块、标识符或引用的错误信息（参见“不可改动项”）。
3. **检查模式。** 用户要求你审计文本是否符合 STE，而不是改写它。使用 `references/checklist.md`，把每处违规报告为：规则编号 + 违规文本 + 合规的改写。

本 skill 与 `humanizer` 不同：humanizer 恢复自然的人类语气；simple-english 则为技术指令强制执行一种受控语言。文档、运行手册和错误信息使用本 skill。博客文章、随笔和个人写作使用 humanizer。不要对同一段文本同时应用两者。

## 你的任务 {#your-task}

当被要求撰写或改写技术文本时：

1. **选择模式**（务实或严格，见下文）。
2. **将每段文字分类**为程序性或描述性。其他每条规则都依赖于此。
3. **在起草之前先校正你的词汇。** 在严格模式下，check/verify/confirm/ensure 这一概念使用 `make sure that`——词典拒绝将这四个词用作动词。在务实模式下，挑选其中一个并坚持使用。为 config/settings 挑选**一个**名词（它们都是有效的技术名词——选一个并坚持使用）。在整篇文档中，这些概念不要使用其他任何词。
4. **应用**下方规则目录中的**规则**。
5. **在交付之前进行自检。** 这一步不是可选的。
6. **绝不改动代码**、标识符、命令或引用的错误信息（参见“不可改动项”）。

当被要求检查（CHECK）文本而不是撰写文本时，将每处违规报告为：规则编号、违规文本、合规的改写。只引用本文件中存在的规则编号。不要凭记忆引用规则编号：编号并不直观，模型会编造编号（经过测试——一个没有本文件的 agent 引用了 "Rule 3.1: short sentences"；而真正的 Rule 3.1 讲的是动词形式）。

## 两种模式 {#two-modes}

| 模式 | 何时 | 应用什么 |
|---|---|---|
| **务实**（默认） | 文档、README、错误信息——用户想要清晰的文本 | 所有结构性规则。领域词汇保留（"idempotent"、"webhook"）。 |
| **严格** | 用户点名要求 STE、ASD-STE100 或合规 | 结构性规则 + 完整的词汇纪律，并告诉用户完全合规需要官方词典（可在 asd-ste100.org 免费获取）。 |

## 第 1 步：对文本分类 {#step-1-classify-the-text}

| | 程序性（指令） | 描述性（解释） |
|---|---|---|
| 目的 | 告诉读者要做什么 | 解释某个事物是什么或做什么 |
| 动词形式 | 祈使句："Install the pump." | 一般现在时/过去时/将来时 |
| 句长上限 | **20 个词**（Rule 5.1） | **25 个词**（Rule 6.3） |
| 单元规则 | 每句一条指令（5.2） | 每段一个主题（6.5），每段最多六句（6.6） |

不要在同一段文字中混用两者。"Getting started" 小节是程序性的。"Architecture" 小节是描述性的。程序中的注释是描述性的（25 词上限，不用祈使句）。

## 规则目录 {#the-rule-catalog}

9 个部分共 53 条规则，转述自 ASD-STE100 第 9 版，并配以软件示例。官方措辞见 asd-ste100.org 上免费提供的标准。

### 第 1 部分 —— 词语（Rules 1.1-1.14） {#section-1--words-rules-11-114}

| 规则 | 说明 |
|---|---|
| 1.1 | 只使用批准词、技术名词或技术动词。 |
| 1.2 | 批准词只能按其列出的词性使用。 |
| 1.3 | 批准词只能以其批准的含义使用。 |
| 1.4 | 只使用动词和形容词的批准形式。 |
| 1.5 | 你可以把领域词汇用作技术名词（"webhook"、"commit"、"endpoint"）。 |
| 1.6 | 只有当未批准词是技术名词或其组成部分时才可使用。 |
| 1.7 | 不要把技术名词用作动词。 |
| 1.8 | 使用你所在项目或行业的技术名词。 |
| 1.9 | 选择技术名词时，选一个简短且清晰的。 |
| 1.10 | 不要把地区用语、俚语或行话用作技术名词。 |
| 1.11 | 一个事物，一个名称。不要在这里叫它 "config"，在那里又叫它 "settings"。 |
| 1.12 | 你可以把领域动词用作技术动词（"deploy"、"compile"、"merge"）。 |
| 1.13 | 不要把技术动词用作名词。 |
| 1.14 | 使用美式英语拼写。 |

在务实模式下，规则 1.5、1.8 和 1.12 承担了主要工作：你的领域词汇是合法的。agent 常违反的是 1.7、1.11 和 1.13。

**Before:** You can webhook the event, then do a deploy.
**After:** Send the event to the webhook. Then deploy the service.

### 第 2 部分 —— 多词名词（Rules 2.1-2.2） {#section-2--multi-word-nouns-rules-21-22}

| 规则 | 说明 |
|---|---|
| 2.1 | 多词名词不超过三个词。 |
| 2.2 | 当技术名词需要超过三个词时，先完整写一次，然后给出简称，或用连字符连接各单元。 |

用介词（of、on、in、for）拆开长名词链：

**Before:** the connection pool timeout configuration value
**After:** the timeout value for the connection pool

### 第 3 部分 —— 动词（Rules 3.1-3.7） {#section-3--verbs-rules-31-37}

| 规则 | 说明 |
|---|---|
| 3.1 | 只使用词典给出的动词形式。 |
| 3.2 | 只使用：不定式、祈使式、一般现在时、一般过去时、一般将来时、用作形容词的过去分词。 |
| 3.3 | 过去分词只能用作形容词（"the cached response"）。 |
| 3.4 | 不要用助动词构成复杂结构。不用现在完成时，不用 "is to be installed"。 |
| 3.5 | "-ing" 形式只能作为技术名词或其组成部分使用（"logging"、"the mounting bracket"）——绝不能用作动词。 |
| 3.6 | 使用主动语态。在描述性文本中，只有当动作执行者未知时才允许使用被动语态。 |
| 3.7 | 用动词而不是名词来描述动作（"compress the file"，而不是 "perform compression of the file"）。 |

**批准的情态动词：can、will、must。禁止：should、would、may、might、could（Rule 3.2）。**
标准甚至在表示可能性时也拒绝 "could"：写 "an explosion can occur"，绝不写 "could occur"。对于 "should"：要求变为 "must"；建议则陈述为事实或删除。这一点对 agent 指令加倍重要——模型会把 "should" 理解为可选。

**Before:** The migration has completed and the table is being rebuilt.
**After:** The migration is complete. The database rebuilds the table.

**Before:** The flag can be set in the config file, making restarts unnecessary.
**After:** You can set the flag in the config file. Then a restart is not necessary.

**Before:** The temperature must be adjusted.
**After:** Adjust the temperature.

### 第 4 部分 —— 句子（Rules 4.1-4.5） {#section-4--sentences-rules-41-45}

| 规则 | 说明 |
|---|---|
| 4.1 | 写简短且清晰的句子。 |
| 4.2 | 不要为了缩短句子而省略词语或使用缩写形式。保留冠词，保留 "that"。 |
| 4.3 | 复杂文本使用竖排列表。 |
| 4.4 | 在相关主题的句子之间使用连接词（"Then"、"As a result"）。 |
| 4.5 | 在适用的情况下，在名词前加冠词（the、a、an）或指示形容词（this、these）。 |

Rule 4.2 是反对过度简略的规则。STE 是语法完整的短句，而不是电报体：

**Wrong shortening:** Ensure file exists before running.
**STE:** Make sure that the file exists before you run the command.

### 第 5 部分 —— 程序性写作（Rules 5.1-5.5） {#section-5--procedural-writing-rules-51-55}

| 规则 | 说明 |
|---|---|
| 5.1 | 每句最多 20 个词。警告和注意事项也包括在内。 |
| 5.2 | 每句一条指令，除非两个动作同时发生。 |
| 5.3 | 用祈使句写指令："Run the migration." |
| 5.4 | 把必要条件放在命令之前，用逗号分隔："If the build fails, read the log." |
| 5.5 | 注释提供信息，绝不提供指令。注释适用 25 词上限。 |

**Before:** You'll want to grab the API key from the dashboard before configuring the client, which you can do under Settings.
**After:** Get the API key from the dashboard, under Settings. Then configure the client with this key.

### 第 6 部分 —— 描述性写作（Rules 6.1-6.6） {#section-6--descriptive-writing-rules-61-66}

| 规则 | 说明 |
|---|---|
| 6.1 | 循序渐进地提供信息：每句一个新事实。 |
| 6.2 | 使用关键词和短语赋予文本逻辑结构。 |
| 6.3 | 每句最多 25 个词。 |
| 6.4 | 将相关信息归入段落。 |
| 6.5 | 每段一个主题。 |
| 6.6 | 每段最多六句。 |

描述性文本中不使用祈使句。描述负责解释；程序负责指示。

### 第 7 部分 —— 安全说明（Rules 7.1-7.3） {#section-7--safety-instructions-rules-71-73}

| 规则 | 说明 |
|---|---|
| 7.1 | 使用表明风险等级的词（"WARNING" = 人身伤害，"CAUTION" = 设备损坏）。 |
| 7.2 | 以清晰的命令或条件开头。 |
| 7.3 | 然后给出风险或可能的后果。 |

绝不要把指令埋在解释之后。这一模式可以直接迁移到破坏性的 CLI 标志、不可逆的迁移和危险的 API 选项上。

**Before:** Note that data loss may occur in some circumstances if the destructive flag happens to be enabled when running against production.
**After:** CAUTION: Do not use the `--force` flag against production. The flag deletes rows that do not match the source.

### 第 8 部分 —— 标点与词数统计（Rules 8.1-8.7） {#section-8--punctuation-and-word-count-rules-81-87}

| 规则 | 说明 |
|---|---|
| 8.1 | 除分号外，所有标准标点都是合法的。改写成两个句子。 |
| 8.2 | 用连字符连接作为一个单元的词。 |
| 8.3 | 括号可用于引用、条目编号、缩写、复数形式、解释和替代项。 |
| 8.4 | 在竖排列表中，引导语的冒号在计算词数时视为句子结束。 |
| 8.5 | 括号内的文本算作一个词。 |
| 8.6 | 以下各算作一个词：数字、带单位的数字、缩写、字母数字标识符、引用文本、标题、标签、专有名词。 |
| 8.7 | 带连字符的词算作一个词。 |

Rule 8.6 对软件文本很重要：反引号中的 `sqlpipe run --config sqlpipe.yaml` 属于引用文本，算作一个词。长标识符不会撑爆你的句长预算。

### 第 9 部分 —— 写作实践（Rules 9.1-9.4、GR-1 至 GR-8） {#section-9--writing-practices-rules-91-94-gr-1-to-gr-8}

| 规则 | 说明 |
|---|---|
| 9.1 | 当逐词替换行不通时，重新组织句子结构。 |
| 9.2 | 正确使用每个批准词：批准的含义、批准的词性。 |
| 9.3 | 不要构造短语动词（"go down" → "decrease"，"set up" → "install" 或 "configure"）。 |
| 9.4 | 在整篇文档中保持一致的风格和术语。 |

一般建议 GR-1 至 GR-8：保留连词 "that"，谨慎使用 "with"，让代词有明确的指代对象，优先用 "this + 名词" 而不是单独的 "this"，避免假朋友词（形似义异的词），避免拉丁缩写，使用包容性语言，并且只有在确定正确时才使用所有格撇号形式（GR-8：不确定时就不要用——非母语读者会觉得难以理解）。

软件文档的 GR-6："e.g." → "for example"，"i.e." → "that is"，删除 "etc."——列出具体条目或写 "and more"。

## 词汇纪律 {#vocabulary-discipline}

官方词典（约 900 个批准词，约 1,200 个附带替代词的禁用词）的版权归 ASD 所有，此处不予转载。即使没有它，其机制也同样适用：**一个词，一个含义，一个词性。**

已知的词性裁定，可作为参考模式：

| 词 | 裁定 |
|---|---|
| test, check, work | 仅作名词。"Do a test"，而不是 "test the pump"。"Check that X" 改为 "make sure that X"。 |
| oil | 仅作技术名词（TN）。动词用法，词典给出 "lubricate"："Lubricate the linkage with oil." |
| help | 仅作动词。名词用法，词典给出 "aid"："with the aid of"。 |
| fall (noun) | 被拒绝。数值下降用 "decrease"。FALL（动词）只用于因重力向下的物理运动："Make sure that the tools do not fall into the engine." |
| follow | 只表示 "to come after"（在……之后），绝不表示 "obey"（服从）。写 "obey the instructions"。 |
| above, below | 只用于物理位置。表示限值时写 "more than"、"less than"。 |

### 情态动词阶梯 {#the-modal-ladder}

| 你写的 | STE 写法 |
|---|---|
| should（要求） | must |
| should（建议） | 删除它，或陈述为事实："X is better because Y." |
| may / might / could（可能性） | can |
| may（许可） | can |
| would（假设） | 重组句子："If X occurs, Y occurs." |

### 从“AI 腔”到简明的替换 {#slop-to-simple-substitutions}

这张表是我们自己的，不是 ASD 词典的。它把 AI 生成文档中被滥用的词映射到朴素的替换词。如果某个词不承载任何事实，就删除它而不是替换它。

| 滥用词 | 改为 |
|---|---|
| leverage, utilize | use |
| in order to | to |
| prior to | before |
| ensure | make sure that（严格模式；在务实模式下，如果 ensure 是你唯一选定的检查类动词，则允许使用） |
| it is worth noting that | （删除） |
| it's important to, crucially | （删除——直接陈述事实） |
| simply, just, easily, seamlessly, effortlessly | （删除） |
| robust, powerful, comprehensive, performant | （删除，或给出可度量的属性） |
| functionality | function, feature |
| enables you to, allows you to | you can |
| is designed to, aims to | （删除——说明它做什么） |
| facilitate | help, make possible |
| dive into, delve into | read, examine |
| when it comes to | for |
| in the event that | if |
| due to the fact that | because |
| as needed, as necessary | （陈述具体条件） |
| and/or | 选其一，或写 "X, or Y, or both" |
| e.g. / i.e. / etc. | for example / that is /（列出具体条目） |
| gracefully handles | （说明它做什么："retries three times, then stops"） |
| out of the box | by default |
| under the hood | internally |
| blazingly fast, state-of-the-art | fast（给出数字）/（删除） |
| streamline | make simpler, make faster |
| plethora, myriad | many |
| addresses the issue, tackles | corrects the fault, removes the error |

### 一致性检查 {#consistency-pass}

把同义词轮换收敛为每个概念一个术语（Rules 1.11、9.4）。下面两个列表的作用方式不同。

**技术名词——不在词典中。选一个并保持一致（两种模式均适用）：**

- config / configuration / settings / options → 选一个

**词典裁定——标准已经做出了选择。使用批准词（严格模式）；选一个并保持一致（务实模式）：**

| 你写的 | 词典状态 | 改用 |
|---|---|---|
| check (verb) / verify / confirm / ensure | 作为动词全部被拒绝 | `make sure that`（严格）；选一个（务实） |
| validate | 不在词典中 | 作为技术动词使用（Rule 1.12），或替换为 `make sure that` |
| delete / drop (verb) / destroy | 全部被拒绝 | `erase`（数据）、`remove`（物理）；避免 `drop` 和 `destroy` |
| remove | 批准的动词 | 保留 |
| run / execute | 两者都被拒绝 | run 用 `operate`，execute 用 `do`（严格）；选一个（务实） |
| invoke / launch | 不在词典中 | 作为技术动词使用（Rule 1.12） |
| display (verb) / render / present (verb) | 全部被拒绝 | `show`（批准的动词） |
| issue | 不在词典中 | 作为技术名词使用，或替换为 `problem`（批准词） |
| failure | 一般用法中被拒绝；作为表示性能丧失的 TN 时批准 | 只在表示性能故障时使用："a failure of the pump" |
| error | 批准的名词 | 保留 |
| problem | 批准的名词 | 保留 |

## 不可改动项 {#untouchables}

这些是技术名称（Rules 1.5、8.6）。即使它们违反词汇规则，也要原样保留：

- 代码块、内联代码、标识符、CLI 命令、标志、文件路径
- 引用的错误信息和日志行
- 产品名称、API 端点名称、配置键
- 带单位的数字——在句长上限中各算作一个词

## 文档之外 {#beyond-documentation}

同样的规则，不同的对象。完整的适配见 `references/use-cases.md`：

- **错误信息**：说明发生了什么（一般过去时）、已知的原因，然后用祈使句给出修复方法。不要 "Oops"，不要 "Please ensure"，不要道歉式的填充语。
- **运行手册**：STE 的主场。祈使式步骤，条件在前，警告在步骤之前。
- **事故报告**：只用一般过去时。"We have identified an issue that may have impacted" 改为 "Between 14:02 and 14:31 UTC, 12% of requests failed."
- **发布说明**：破坏性变更遵循警告模式——命令在前，风险在后。
- **Agent 指令（prompt、AGENTS.md）**：系统 prompt 是写给一个无法提问的读者的程序。每句一条指令，不用 "should"，条件在前。
- **翻译准备**：STE 的本职工作。一词一义加上完整的语法，可以消除大部分翻译歧义。

## 交付前自检 {#self-check-before-you-deliver}

这一步不是可选的。对你的草稿执行以下四项检查：

1. 统计你最长的三个句子的词数。超过 20/25 的上限 → 拆分它们。
2. 在草稿中搜索：`'ll`、`'re`、`'s`（缩写形式）、`has been`、`have been`、`should`、逗号后的 `-ing` 动词、分号。
3. 搜索每一个 `if` 和 `when`。每一个都应位于其句子的**开头**，在命令之前。"Increase the timeout if the network is slow" → "If the network is slow, increase the timeout."
4. 搜索你在“你的任务”第 3 步中**没有**选定的动词（check/verify/confirm 这一组）。把每一处命中替换为你选定的动词。

修正你发现的问题，然后交付。若需完整审计，请运行 `references/checklist.md`。

## 完整示例 {#full-example}

**改写前（真实的未经编辑的 AI 输出）：**

> **Connection timeouts.** If sqlpipe hangs or fails with `dial tcp: i/o timeout`, check that the host running sqlpipe can reach the Postgres port (usually 5432) — this is often a security group or firewall rule blocking the connection. If you're connecting to a managed database (RDS, Cloud SQL, etc.), confirm the instance allows connections from sqlpipe's IP. You can also try increasing `source.connect_timeout_seconds` in your config, since a slow network path can trip the default timeout even when the connection eventually succeeds.

**改写后（分类为程序性，动词 = "make sure"，条件在前，每句一条指令）：**

> **Connection timeouts.** sqlpipe stops with `dial tcp: i/o timeout` when it cannot reach the Postgres port (5432 by default).
>
> 1. Make sure that the host that runs sqlpipe can reach the Postgres port. A firewall or security group usually blocks it.
> 2. If the database is managed (RDS, Cloud SQL), make sure that the instance accepts connections from the IP of sqlpipe.
> 3. If the network is slow, increase `source.connect_timeout_seconds` in the configuration.

改动之处：40 个词的句子被拆分到 20 词以内；"you're" 被展开；"check/confirm" 收敛为 "make sure that"；每个条件都移到其命令之前；删除了 "etc."；代码和错误字符串保持不变。

## 局限 {#limits}

STE 适用于技术事实和指令。不要将其应用于营销文案、博客语气或品牌写作——它在设计上就会删除说服力。当用户要求对营销文本使用 STE 时，请如实说明，并建议将其用于文档。

本 skill 是一个非官方辅助工具。它与 ASD 或 STEMG 没有隶属关系，也未获其认可，并且没有任何工具能够保证 STE 合规。ASD-STE100 是 ASD 的注册商标。官方标准可在 asd-ste100.org 免费下载。

## 参考资料 {#references}

- `references/checklist.md` —— 带有可搜索模式的完整验证流程，用于检查模式和最终审计
- `references/use-cases.md` —— 长篇适配：错误信息、运行手册、事故报告、提交信息、UI 文案、i18n
