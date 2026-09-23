---
title: "Ast Grep —— 通过 ast-grep 进行感知 AST 的结构化代码搜索与重写"
sidebar_label: "Ast Grep"
description: "通过 ast-grep 进行感知 AST 的结构化代码搜索与重写"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ast Grep

通过 ast-grep 进行感知 AST 的结构化代码搜索与重写。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/software-development/ast-grep` 安装 |
| 路径 | `optional-skills/software-development/ast-grep` |
| 版本 | `1.0.0` |
| 作者 | Yeongyu Kim (code-yeongyu)，由 Hermes Agent 改编 |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `ast`, `codemod`, `refactoring`, `structural-search`, `code-search`, `rewrite`, `tree-sitter` |
| 相关 skill | [`simplify-code`](/user-guide/skills/bundled/software-development/software-development-simplify-code)、[`systematic-debugging`](/user-guide/skills/bundled/software-development/software-development-systematic-debugging) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# ast-grep

`ast-grep`（二进制文件也叫 `sg`）是一个支持 25 种语言的**感知 AST 的搜索与重写工具**。它把你的模式当作代码，以解析项目的同样方式解析它，并进行结构化匹配。只要你的问题取决于**代码的形状**而不是文本字节，它就是合适的工具。

本 skill 附带一个位于 `scripts/ast_grep_helper.py` 的 Python 封装，以及平台安装脚本 `install.sh`（POSIX）和 `install.ps1`（Windows）。该辅助脚本增加了离线模式校验、两遍写入技巧以及二进制文件自动解析。请将它作为默认入口。

上游来源：vendored 自 [code-yeongyu/ast-grep-skill](https://github.com/code-yeongyu/ast-grep-skill)（MIT），即 oh-my-openagent 共享 skill 包中所附带的版本。

---

## 何时使用本 skill {#when-to-use-this-skill}

只要问题关乎**代码结构**而非字节，就使用它：

- "找出所有接受 `Request` 参数的函数。"
- "把所有 `console.log(x)` 重写为 `logger.info(x)`。"
- "去掉所有 `as any` 类型转换。"
- "在整个仓库中把 `require(...)` 替换为 `import`。"
- "找出空的 catch 块。"
- "把 `Optional[X]` 迁移为 `X | None`。"
- "在这 200 个文件上应用这个 codemod。"
- "运行我们的 YAML lint 规则并列出违规项。"

当问题是文本形态时（字符串字面量内容、注释、许可证头、文件名、跨语言正则），改用 `search_files`（或直接用 `rg`）。拿不准时就问自己："答案取决于语言的语法树，还是只取决于文件的字节？"如果是前者，用 ast-grep；如果是后者，用 search_files。

Hermes 集成说明：
- 通过 `terminal` 工具运行辅助脚本和 `sg`。每个模式都用单引号括起来，这样 shell 永远不会展开 `$VAR`。
- 对于围绕匹配结果的"查找→读取"链，使用 `--json-out` 并用 `execute_code` 处理，而不是通过解释器管道传递。
- 它是对 Hermes `patch` 工具的补充（而非替代）：`patch` 用于你亲自编写的定点编辑；ast-grep 用于跨多处位置、由模式驱动的批量重写。

---

## agent 必须牢记的三件事 {#three-things-the-agent-must-internalize}

### 1. ast-grep 不是正则 {#1-ast-grep-is-not-regex}

通配符是 `$VAR`（一个 AST 节点）和 `$$$`（零个或多个节点）。正则语法会静默失败：

| 你写的 | ast-grep 看到的 | 你真正想要的 |
|---|---|---|
| `foo\|bar` | `foo` 与 `bar` 的按位或 | 分别执行两次搜索 |
| `.*foo` | 无法解析 | `$$$ foo`（如果 `$$$` 是一组节点）或改用 rg |
| `\w+` | 无法解析 | 用 `$VAR` 捕获任意标识符 |
| `[a-z]` | 字符类，无法解析 | 改用 rg |

完整的反模式表见 `references/pitfalls.md` §1。辅助脚本的 `validate` 子命令能机械地捕获这些错误——在手工排查"没有匹配"之前先调用它。

### 2. 模式必须是合法代码 {#2-patterns-must-be-valid-code}

模式本身必须能被解析。`def $FN($$$):` 会失败，因为结尾的 `:` 让它不完整；请使用 `def $FN($$$)`。没有参数/函数体的 `function $NAME` 会失败；请使用 `function $NAME($$$) { $$$ }`。各语言的完整表格见 `references/pitfalls.md` §2。

### 3. `--update-all` 与 `--json` 互斥（且静默） {#3---update-all-and---json-are-mutually-exclusive-silently}

这是编写脚本时最大的一个坑。`sg run -p P -r R --json --update-all` 会返回 JSON，但**不会修改文件**。要同时预览并应用，请运行**两遍**：

```bash
sg run -p P -r R --json=compact .   # 第 1 遍：查看将要改动的内容
sg run -p P -r R --update-all .     # 第 2 遍：真正应用
```

当你调用 `replace --apply` 时，辅助脚本会自动这样做。参阅 `references/pitfalls.md` §9。

---

## 辅助脚本——`scripts/ast_grep_helper.py` {#the-helper-script--scriptsast_grep_helperpy}

一个单文件、仅依赖 Python 3 标准库的封装。在所有操作系统上表现一致。它是 agent 的默认入口。

### `search`——查找某个模式的所有匹配 {#search--find-all-matches-of-a-pattern}

```bash
python scripts/ast_grep_helper.py search 'console.log($MSG)' --lang ts src/
```

它会先离线校验模式。如果模式看起来像正则（`\w`、`.*`、`|` 等），辅助脚本会给出提示并退出，绝不调用 `sg`——省去一次往返。传入 `--force` 可跳过校验。

标志：
- `--lang ts`（或 25 种语言中的任意一种；接受 `js`、`py`、`rs`、`kt` 等别名）
- `--globs '!**/*.test.ts'`（可重复；加 `!` 前缀表示排除）
- `-C 3`（上下文行数）
- `--json-out`（输出原始 JSON 而非人类可读格式）

### `replace`——按模式重写，默认 dry-run {#replace--rewrite-by-pattern-dry-run-by-default}

```bash
# Dry-run 预览（默认——不修改任何文件）
python scripts/ast_grep_helper.py replace 'console.log($MSG)' 'logger.info($MSG)' --lang ts src/

# 真正应用
python scripts/ast_grep_helper.py replace 'console.log($MSG)' 'logger.info($MSG)' --lang ts src/ --apply
```

辅助脚本会：
1. 校验 `pattern` 和 `rewrite`，找出可通过提示检测的错误。
2. 以 `--json=compact` 运行第 1 遍，收集匹配并显示预览。
3. 如果设置了 `--apply`，以 `--update-all` 运行第 2 遍来修改文件。

### `scan`——运行 YAML 规则 {#scan--run-yaml-rules}

```bash
# 从 cwd 发现 sgconfig.yml 并运行所有规则
python scripts/ast_grep_helper.py scan src/

# 运行单个规则文件
python scripts/ast_grep_helper.py scan -r rules/no-console.yml src/

# 应用自动修复
python scripts/ast_grep_helper.py scan -U src/

# 适合 CI 的 GitHub 注解
python scripts/ast_grep_helper.py scan --report-style short src/
```

### `validate`——离线模式检查（不调用 `sg`） {#validate--offline-pattern-check-no-sg-call}

适用于 CI lint、pre-commit 钩子以及快速的合理性检查：

```bash
python scripts/ast_grep_helper.py validate '\w+' --lang ts
# → exit 2: regex \w not supported. Use $VAR for identifiers.

python scripts/ast_grep_helper.py validate 'console.log($MSG)' --lang ts
# → exit 0: pattern looks plausible for ast-grep.
```

### `langs` / `doctor` / `install` {#langs--doctor--install}

```bash
python scripts/ast_grep_helper.py langs       # 列出 25 种受支持的语言及别名
python scripts/ast_grep_helper.py doctor      # 检查 ast-grep 二进制是否可用
python scripts/ast_grep_helper.py install     # 委托给 install.sh / install.ps1
```

`new` 和 `test` 子命令直接代理到 `sg new` 和 `sg test`。

---

## 直接使用 `sg`（当辅助脚本不够用时） {#direct-sg-use-when-the-helper-isnt-enough}

辅助脚本有自己的取舍。如需完全控制，请直接使用 `sg`。本 skill 在 `references/cli.md` 中附带了一份 CLI 速查表。最基本的用法：

```bash
# 搜索
sg run -p 'console.log($MSG)' --lang ts src/

# 以 JSON 输出搜索结果，便于脚本处理
sg run -p 'console.log($MSG)' --lang ts --json=compact src/

# 重写，dry-run
sg run -p 'console.log($MSG)' -r 'logger.info($MSG)' --lang ts --json=compact src/

# 重写，应用
sg run -p 'console.log($MSG)' -r 'logger.info($MSG)' --lang ts --update-all src/

# 从 stdin 读取模式（非常适合临时试验）
echo 'console.log("hi")' | sg run -p 'console.log($MSG)' --lang js --stdin

# 调试一个返回 0 个匹配的模式
sg run -p '<your pattern>' --lang <lang> --debug-query=ast --stdin <<< '<sample-code>'

# 运行 YAML 规则
sg scan src/

# 内联 YAML 规则（一次性）
sg scan --inline-rules '
id: no-todo
language: TypeScript
severity: warning
rule: { pattern: TODO }' src/
```

在 shell 中直接使用 `sg` 时，**始终用单引号括起模式**，这样 `$VAR` 就不会被 shell 展开。

---

## 决策树——什么时候用什么 {#decision-tree--what-to-use-when}

<!-- ascii-guard-ignore -->
```
USER asks for "find/rewrite/codemod"
│
├─ structural pattern (function shape, call, class, import, control flow)
│  └→ ast-grep (this skill)
│
├─ text pattern (regex, alternation, character classes, file names)
│  └→ search_files / rg
│
├─ semantic question (what variable does this refer to? does this throw?)
│  └→ LSP tools, TypeScript compiler, Pyright, Semgrep with type inference
│
└─ multiple repos / federated search
   └→ a search engine + then ast-grep / rg / LSP per-repo
```
<!-- ascii-guard-ignore-end -->

如果用户说"找出全部"或"每一个"，当目标有结构形状时（函数、类、调用、import、语句），默认使用 ast-grep。当目标是文本时（字符串内容、注释、许可证头、文件名、标识符子串），默认使用 search_files。

---

## 重写时始终先运行 dry-run {#always-run-dry-run-first-when-rewriting}

一个错误的模式会悄无声息地重写错误的内容。正因如此，辅助脚本的 `replace` 默认是 dry-run。流程是：

1. 搜索以确认匹配：`helper search '<pattern>' --lang X .`
2. Dry-run 重写：`helper replace '<pattern>' '<rewrite>' --lang X .`（不带 `--apply`）
3. 检查 dry-run 摘要：匹配数量、受影响的文件、逐处的预览。
4. 如果不对：改进模式，回到第 1 步。
5. 如果正确：`helper replace '<pattern>' '<rewrite>' --lang X . --apply`。

绝不要应用一个没有先做过 dry-run 的重写。在 git 仓库中执行 `--apply` 之后，提交前先用 `git diff --stat` 审查。

---

## 当 `sg` 返回 0 个匹配、但你确定代码就在那里时 {#when-sg-returns-0-matches-but-you-know-the-code-is-there}

按优先级顺序：

1. **运行 `helper validate '<pattern>' --lang <lang>`**——捕获正则误用、缺少函数体、Python 结尾冒号等问题。
2. **检查 `--lang`**——`sg` 根据扩展名推断；如果你对 `.tsx` 文件传入 `--lang ts`（而不是 `tsx`），JSX 将无法解析。
3. **检查解析后的模式**：`sg run -p '<pattern>' --lang <lang> --debug-query=ast --stdin <<< '<sample>'`。如果出现 `ERROR` 节点，说明模式格式有误。
4. **检查目标文件的 AST**：`sg run -p '$_' --lang <lang> --debug-query=cst path/to/file | head -40`——找到你想匹配的 `kind`。
5. **试试 playground**：&lt;https://ast-grep.github.io/playground.html>——粘贴代码 + 模式，看看发生了什么。

不要盲目地换着花样重试。每次失败都有原因；把它找出来。

---

## 何时使用 YAML 规则、何时使用内联 `-p` 模式 {#when-to-use-yaml-rules-vs-inline--p-patterns}

**使用内联 `-p`** 的情况：
- 一次性的临时查询。
- 模式很简单（没有约束，没有修复模板）。
- 你在做探索。

**使用 YAML 规则**（文件放在 `rules/` 下，通过 `sg scan` 运行）的情况：
- 模式会被复用（lint 规则、在 CI 中运行的 codemod）。
- 你需要 `constraints`、`transform`、复杂的 `inside`/`has` 或组合逻辑。
- 你需要自动修复（`fix:` 字段）。
- 你想测试规则（通过 `sg test` 进行快照测试）。

完整的 YAML 规则 schema 见 `references/yaml-rules.md`。项目设置（`sgconfig.yml`、`ruleDirs`、`utilDirs`）见 `references/sgconfig.md`。

---

## 输出规范 {#output-discipline}

- `sg run --json=compact` 输出一个匹配对象数组：`{ file, range: {start, end}, text, replacement?, lines, language, ... }`。
- 不带 `--json` 时，`sg` 输出适合终端的人类可读彩色输出。
- 辅助脚本的默认输出是人类可读的（file:line:column + 匹配预览）。传入 `--json-out` 获取原始 JSON。
- 辅助脚本的 `replace` 总会给出摘要：匹配数量、文件数量、逐处预览。

为用户做总结时，**始终包含受影响的文件数量**，而不仅仅是匹配数量。用户关心的是影响范围。

---

## 必读材料（按优先级排序） {#required-reading-in-order-of-priority}

1. `references/patterns.md`——元变量、命名规则、严格程度级别。当你不确定某个模式为何不匹配时阅读。
2. `references/pitfalls.md`——失败模式实用指南。当 0 个匹配让你意外时阅读。
3. `references/recipes.md`——按语言分类、可直接复制粘贴的模式。开始新任务时首先阅读。
4. `references/cli.md`——`sg run`、`sg scan`、`sg test`、`sg new`、`sg lsp`。当辅助脚本不够用时阅读。
5. `references/yaml-rules.md`——YAML 规则 schema。当内联模式不再够用时阅读。
6. `references/sgconfig.md`——项目级配置。为真实项目设置 `sg scan` 时阅读。
7. `references/install.md`——各操作系统的安装方法。仅在 `install.sh` / `install.ps1` 失败时阅读。

---

## 不变式（不可违反） {#invariants-do-not-break}

- **先校验再搜索。** 以编程方式生成模式时，先调用 `helper validate`。它能捕获正则误用这一类错误，而这类错误约占"0 个匹配"调试会话的 70%。
- **先 dry-run 再应用。** 绝不要在未先检查匹配结果的情况下运行 `sg run -r ... --update-all`。辅助脚本的 `replace` 默认就强制执行这一点。
- **两遍写入。** 直接使用 `sg` 同时进行预览和应用时，要调用两次——`--json` 会忽略 `--update-all`。
- **在 shell 中用单引号括起模式。** 用 `'$VAR'` 而不是 `"$VAR"`。在双引号中 shell 会把 `$VAR` 展开为空字符串，从而破坏模式。
- **模式是代码，不是正则。** 当模式需要 `|`、`.*`、`\w` 或 `[a-z]` 时，改用 search_files。不要试图把 ast-grep 硬塞成正则的形状。
- **从 stdin 读取时必须指定 `--lang`。** 使用 `--stdin` 管道输入时，要显式设置 `--lang`；`sg` 无法根据扩展名推断。
- **Linux 上优先使用 `ast-grep` 而不是 `sg`**，因为 `sg` 与 `util-linux` 中的 `setgroups` 冲突。辅助脚本会处理这一点；如果你直接调用 `sg`，请设置别名：`alias sg=ast-grep`。
