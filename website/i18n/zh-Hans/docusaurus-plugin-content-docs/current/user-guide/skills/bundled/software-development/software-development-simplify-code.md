---
title: "Simplify Code —— 用 3 个并行 agent 清理最近的代码改动"
sidebar_label: "Simplify Code"
description: "用 3 个并行 agent 清理最近的代码改动"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Simplify Code

用 3 个并行 agent 清理最近的代码改动。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/software-development/simplify-code` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent（灵感来自 Claude Code /simplify） |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `code-review`, `cleanup`, `refactor`, `delegation`, `subagent`, `parallel`, `simplify` |
| 相关 skill | [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review)、[`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development)、[`plan`](/user-guide/skills/bundled/software-development/software-development-plan) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Simplify Code —— 并行评审与清理

用三个各有专注方向的评审者并行评审你最近的代码改动，汇总它们的发现，并应用其中值得应用的修复。

**核心原则：** 三个窄口径评审者胜过一个宽口径评审者。每个评审者都针对单一类问题——复用、质量、效率——深入搜索代码库，而不会把注意力摊薄到三者之上。它们并发运行，所以你只需付出一次评审的延迟，而不是三次。

## 适用场景

当用户说出以下任意内容时触发此 skill：

- "simplify" / "simplify my changes" / "simplify these changes"
- "review my code" / "review my recent changes" / "clean up my changes"
- "/simplify"（如果他们把 Claude Code 的习惯带了过来）

用户可能附加的可选修饰语——请照做：

- **聚焦：** "simplify focus on efficiency" → 只运行效率评审者
  （或在汇总时向它倾斜）。可识别的聚焦方向：`reuse`、
  `quality`、`efficiency`。
- **空跑：** "simplify but don't change anything" / "just report" → 运行
  三个评审者，呈现发现，但不应用任何改动。应用前先询问。
- **范围：** "simplify the last commit" / "simplify staged" / "simplify
  src/foo.py" → 相应地收窄 diff 来源（见阶段 1）。

不要在每次编辑后自动运行它。它会消耗三个 subagent 份额的
token——只在用户明确要求时才调用。

## 流程

### 阶段 1 —— 确定要评审的改动

抓取要评审的 diff。按用户的要求选择来源，默认顺序如下：

```bash
# 1. Default: uncommitted working-tree changes (tracked files)
git diff

# 2. If that's empty, include staged changes
git diff HEAD

# 3. Scoped variants the user may request:
git diff --staged                 # "staged changes"
git diff HEAD~1                    # "the last commit"
git diff main...HEAD              # "this branch" / "my PR"
git diff -- src/foo.py            # specific file(s)
```

如果 `git diff` 和 `git diff HEAD` 都为空，且不存在 git 仓库或没有任何改动，就退回到用户明确点名的文件，或本次会话中最近创建/编辑过的文件。如果你确实找不到任何改动过的代码，就明说并停止——没有什么可以简化的。

抓取完整的 diff 文本。留意它的体量：如果非常大（比如超过 2000 行改动），提醒用户三个 subagent 各自携带完整 diff 会非常耗 token，并在继续之前提出把范围收窄（按目录、按提交）。

### 阶段 2 —— 并行启动三个评审者

使用 `delegate_task` 的**批处理模式**——把三个任务放在同一个 `tasks`
数组里传入，让它们并发运行。三是这个模式下合适的扇出数；
它在任何默认安装的 `delegation.max_concurrent_children` 预算之内。

给**每个**评审者**完整的 diff**（不是片段——跨文件的问题就藏在片段之间的缝隙里），外加仓库的绝对路径，好让它们能搜索更大范围的代码库。每个评审者都获得 `terminal`、`file` 和 `search`
工具集（这样它们可以用 `git`、`read_file` 和 `search_files`/grep）。

告诉每个评审者：
- 在现有代码库中搜索证据（不要仅凭 diff 推断）。
- **应用切斯特顿栅栏原则：** 在标记任何东西可删除之前，先对该行运行
  `git blame`，弄清它为什么存在。如果你无法确定它最初的用途，标记为
  `confidence: low`——不要猜。
- 以结构化输出报告发现，带上置信度和风险：
  ```
  file:line → problem → suggested fix | confidence: high/medium/low | risk: SAFE/CAREFUL/RISKY
  ```
  - **SAFE** = 已证明不影响行为（未使用的 import、被注释掉的
    代码、纯透传封装）。这些自动应用。
  - **CAREFUL** = 在不改变语义的前提下改进（重命名局部变量、
    展平嵌套三元表达式、抽取辅助函数）。应用时需配合测试验证。
  - **RISKY** = 可能改变行为或破坏公共契约（N+1
    重构、公共 API 重命名、内存生命周期变更）。标记出来交给
    人工评审——不要自动应用。
- 跳过吹毛求疵和纯风格的改动。只标记那些能实质改进代码的问题。

传入下面这三个目标（用户的聚焦方向排除掉哪个就删掉哪个）：

**评审者 1 —— 代码复用**
> 评审此 diff，找出重复实现了代码库中已有功能的代码。
> 搜索工具模块、共享辅助函数和相邻文件
> （使用 search_files / grep），寻找新代码本可以直接调用
> 而不必重新实现的现有函数、常量或模式。标记出：与现有函数
> 重复的新函数；已有工具函数已经能完成的手写逻辑
> （手动拼接字符串/路径、自定义环境检查、临时的
> 类型守卫、重新实现的解析）。对每一项，指出应该使用的现有
> 东西及其所在位置。

**评审者 2 —— 代码质量**
> 评审此 diff 中的质量问题。关注：冗余状态（与现有状态
> 重复、或本可从现有状态推导出来的值；没必要存在的缓存）；
> 参数膨胀（在本应重构函数的地方硬加新参数）；
> 复制粘贴加微调（本该共享一层抽象的近似重复代码块）；
> 抽象泄漏（暴露内部实现、打破已有的封装边界）；
> 字符串化编程（在已有常量/枚举/注册表的地方使用裸字符串——标记前
> 先检查规范的注册表）；AI 生成的糊弄式模式（在 `count++` 上方写
> `// increment counter` 这类复述显而易见代码的多余注释；对已校验输入
> 做不必要的防御性 null 检查；绕过类型系统的 `as any`
> 转换；与文件其余部分不一致的写法）。对每一项，给出具体的重构方案。

**评审者 3 —— 效率**
> 评审此 diff 中的效率问题。关注：不必要的工作
> （重复计算、重复读取文件、重复的 API 调用、N+1
> 访问模式）；错失的并发（互不依赖的操作被串行执行）；
> 热路径臃肿（启动或每请求路径上的重量级/阻塞工作）；
> TOCTOU 反模式（在操作前先做存在性预检查，而不是直接
> 执行并处理错误）；内存问题（无界增长、缺少
> 清理、监听器/句柄泄漏）；读取范围过大（本可只读一小段
> 却加载整个文件）；静默失败（空的 catch 块、被忽略的错误
> 返回值、`except: pass`、不做任何处理的 `.catch(() => {})`、错误
> 传播断层——这些会掩盖 bug，至少也应该在吞掉之前记录
> 日志）。对每一项，给出具体的修复方案，并说明为什么更快或更安全。

### 阶段 3 —— 汇总并应用

等待三个评审者全部返回（批处理模式会一起返回）。

1. **合并**这些发现为一个列表，对评审者之间重叠的部分去重。
2. **丢弃误报**——你掌握的上下文最多；你不必
   跟评审者争辩，直接静默丢掉薄弱或错误的建议即可。
3. **解决冲突。** 评审者之间可能意见相左（评审者 1："使用现有的
   工具函数 X"；评审者 3："X 很慢，把它内联"）。默认的解决顺序：
   **正确性 > 用户声明的聚焦方向 > 可读性/复用 > 微优化。**
   除非该路径确实是热点，否则不要应用一个损害清晰度的性能"修复"。
   当两个建议互斥且都站得住脚时，选改动更少的那个，并把另一个方案记下来。
4. **按风险等级顺序应用：**
   - **先 SAFE**（自动应用）：未使用的 import、被注释掉的代码、
     纯透传封装、多余的类型断言。之后运行测试。
   - **再 CAREFUL**（带验证应用，一次一个文件）：重命名
     局部变量、展平三元表达式、抽取辅助函数、合并重复代码。每个文件之后都运行
     测试。任何导致失败的改动都回退。
   - **最后 RISKY**（标记待评审——不要自动应用）：N+1 重构、
     公共 API 变更、并发修复、错误处理变更。逐条呈现，
     附上风险描述和测试覆盖状况。
   如果用户选择了空跑，就呈现全部三个等级，不应用任何改动。
5. **验证**你没有弄坏任何东西：对被改动的文件运行项目的针对性测试
   （不是整个测试套件），并重新运行仓库使用的任何 linter/类型检查。如果某个修复弄坏了测试，就回退那一个修复并报告。
6. **总结**你改了什么：按评审者类别和风险等级分组的已应用修复简表，
   外加任何你有意跳过的发现及其原因。

## 陷阱

- **扇出不要超过 ~3 个。** 更多评审者意味着更高成本、更多需要调和的
  相互冲突的建议，而不是更好的覆盖率。三个类别
  已经覆盖了这个问题空间。
- **把完整的 diff 交给每个评审者。** 把 diff 拆开分给不同评审者
  会破坏这个设计——跨文件重复和 N+1 只有在完整视图下才会显现。
- **评审者要搜索，而不是猜测。** 一条没有指向现有工具函数的复用发现
  （"大概有个辅助函数干这个吧"）就是噪音。要求
  `file:line` 证据；丢弃缺少证据的发现。
- **应用 ≠ 重写。** 这是对用户最近改动的清理，不是
  重构整个模块的许可证。把编辑范围控制在 diff 触及的部分
  加上修复所需的最小周边改动。
- **尊重项目约定。** 如果仓库里有 AGENTS.md / CLAUDE.md /
  HERMES.md 或某个 linter 配置，把那些规则揉进评审者的提示词里，
  好让建议符合本项目的风格而不是与之对抗。
- **大 diff 会撑爆上下文。** 如果 diff 特别大，先收窄范围再
  委派——三个 subagent 各自携带 5000 行 diff 既昂贵，
  又可能被截断。
- **过度信任死代码工具。** `knip`、`ts-prune` 和 `depcheck` 会把
  确实被动态使用的导出（基于字符串的 import、反射）标记出来。删除前务必
  grep 该符号名——工具报告干净并不是证据。
- **不检查公共契约就重命名。** 导出名、API 路由
  路径、数据库列名和配置键都是契约——即使名字很糟，
  重命名也会破坏调用方。把公共契约的变更标为 RISKY；绝不
  自动重命名。
- **删除"不必要的"错误处理。** 一个空的 catch 块或被忽略的
  错误可能是有意为之——在那个上下文里错误是预期且无害的。
  标记它，不要删除它；让人来决定。

## 相关

如果你的安装带有 `subagent-driven-development` skill（可选），它
覆盖的是互补的场景：在实现*过程中*按任务进行并行评审。
本 skill 则是独立的*事后*清理环节。提交前的安全/质量把关请使用
`requesting-code-review`。
