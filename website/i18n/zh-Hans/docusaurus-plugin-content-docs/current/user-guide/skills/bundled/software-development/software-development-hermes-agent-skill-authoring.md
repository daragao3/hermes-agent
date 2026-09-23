---
title: "Hermes Agent Skill 编写——编写仓库内 SKILL.md 文件：frontmatter 与结构"
sidebar_label: "Hermes Agent Skill 编写"
description: "编写仓库内 SKILL.md 文件：frontmatter 与结构"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Hermes Agent Skill 编写

编写仓库内 SKILL.md 文件：frontmatter（前置元数据）与结构。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/software-development/hermes-agent-skill-authoring` |
| 版本 | `2.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `skills`, `authoring`, `hermes-agent`, `conventions`, `skill-md` |
| 相关 skill | [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# 编写 Hermes-Agent Skills（仓库内）

## 概述

SKILL.md 可以存放在两个位置：

1. **用户本地：** `~/.hermes/skills/<maybe-category>/<name>/SKILL.md` —— 个人使用，不共享。通过 `skill_manage(action='create')` 创建。
2. **仓库内（本 skill 讨论此情况）：** hermes-agent 仓库中的 `skills/<category>/<name>/SKILL.md` 或 `optional-skills/<category>/<name>/SKILL.md` —— 已提交，随包一起发布。使用 `write_file` + `git add`。`skill_manage(action='create')` **不**针对此目录树。

仓库内 skill 必须满足仓库的**硬性编写标准**（参见 AGENTS.md 中的 "Skill authoring standards (HARDLINE)" 一节——该节是事实来源；本 skill 是其操作性演练）。评审者会拒绝违反这些标准的 PR，因此一开始就满足它们，比事后返工更省事。

## 使用时机

- 用户要求你"在此分支 / 仓库 / 提交中"添加一个 skill
- 你正在提交一个应随 hermes-agent 一起发布的可复用工作流
- 你正在编辑 `skills/` 或 `optional-skills/` 下的现有 skill（小改动用 `patch`，重写用 `write_file`；`skill_manage` 对仓库内 skill 的 patch 仍有效，但 `create` 无效）
- 不适用于：`~/.hermes/skills/` 中的个人 skill（直接用 `skill_manage` 即可）

## 先决定层级：内置还是可选

- **内置（`skills/<category>/`）** —— 日常使用的行为，对多种用户类型都广泛有用，占用小。硬性门槛：你能一本正经地说出"用户每月会在 5 个以上会话中加载它"。
- **可选（`optional-skills/<category>/`）** —— 小众、特定垂直领域（区块链、游戏、金融、某个单一应用）、周期性作业/任务类 skill，或任何重量级的内容。通过 `hermes skills install official/<category>/<skill>` 安装。

**拿不准时，选可选。** 以后提升很容易；降级则是折腾。"任何需要它的人都会觉得有用"是可选层级的论据，而不是内置层级的论据。

按工具**是什么**来选类别，而不是按它给人的感觉（一个 AI agent CLI 应放在 `autonomous-ai-agents/`，即使它"感觉像生产力工具"）。用 `search_files(pattern='*', target='files', path='skills')` 确认现有类别，不要随意新建顶层类别。

**不要写路由 / 索引 / 枢纽类 skill。** 一个核心内容是指向兄弟 skill 的路由表的 skill，会增加一次间接跳转，并重复兄弟 skill 自身的 `When to Use` 触发条件。如果去掉"改为加载 skill X"这类指针后该 skill 就空了，那就不要写它——目录和各兄弟 skill 的触发条件已经在做这件事。

## 必需的 Frontmatter

验证器的事实来源：`tools/skill_manager_tool.py::_validate_frontmatter`。验证器的硬性要求：

- 以 `---` 作为首字节开头（无前导空行）。
- 在正文前以 `\n---\n` 结束。
- 可解析为 YAML 映射。
- 存在 `name` 字段。
- 存在 `description` 字段（验证器上限为 1024 个字符——但请参见下面仓库的硬性规定，它严格得多）。
- 关闭 `---` 后有非空正文。

仓库标准格式（所有字段都应具备，即使验证器不强制要求）：

```yaml
---
name: my-skill-name               # 小写，连字符，≤64 个字符（MAX_NAME_LENGTH）
description: Concise capability statement, under sixty chars.
version: 0.1.0                    # semver；新 skill 从 0.1.0 开始
author: Real Name (github-handle), Hermes Agent
license: MIT
platforms: [linux, macos, windows]   # 审查而非猜测——参见平台限定
metadata:
  hermes:
    tags: [Short, Descriptive, Tags]
    related_skills: [other-in-repo-skill]
---
```

### `description` 规则（硬性规定——验证器的 1024 并**不是**标准）

- **≤ 60 个字符。** 一句话，以句号结尾。
- 陈述能力而非实现，且不要重复 skill 名称。
- 不要使用营销词汇（"powerful"、"comprehensive"、"seamless"、"advanced"）。
- 系统提示词中的 skill 索引会在 57 个字符处截断并加上 "..."——触发条件/能力描述必须在这个窗口内自成一体。
- 如果 description 中包含 `:`，请用双引号括起来，否则 YAML 会把它解析为映射，导致文档生成器崩溃。引号不计入 60 个字符。

好的示例：`Track named companies for material news with cited digests.`
坏的示例：`Use when a user asks to monitor named competitors or companies for product launches, pricing changes, funding, ...`（240 个字符——在评审中被拒绝）

### `author` 规则

- **先署人名**，再将 "Hermes Agent" 作为次要协作者：`Ben Barclay (benbarclay), Hermes Agent`。
- 贡献的 skill 绝不能只写 `author: Hermes Agent`——要署人而不是署工具，即使（尤其是）由 agent 起草文本时也是如此。
- 维护者编写的 skill：`Teknium (teknium1), Hermes Agent`。

### `related_skills` 规则

- 每个条目都必须能解析到与你的 PR 处于同一树状态的现有**仓库内** skill。不要引用仅在计划中、位于另一个 PR 中，或只存在于 `~/.hermes/skills/` 中的 skill。
- 逐条验证：`search_files(pattern='<name>', target='files', path='skills')`（以及 `optional-skills/`）。

## 平台限定：审查，而不是轻信

`platforms:` 按宿主操作系统限定加载。根据 skill 的正文和脚本实际调用的内容来设置它：

| Skill 仅使用…… | `platforms:` |
|---|---|
| Hermes 工具 + 标准库 Python + 跨平台 CLI | `[linux, macos, windows]` |
| bash 管道、`grep`/`awk`/`sed` 链、heredoc | `[linux, macos]` |
| `osascript`、`defaults`、`pmset` | `[macos]` |
| `apt`/`systemctl`/`/proc` | `[linux]` |

在 `scripts/` 中需要搜索的仅限 POSIX 的信号：`fcntl`、`termios`、`pty`、`os.fork`、`os.killpg`、`signal.SIGKILL`、`os.kill(pid, 0)` 存活检查、硬编码的 `/tmp` `/proc` `/etc`。默认立场：先修复为跨平台（`tempfile.gettempdir()`、`pathlib.Path`、`psutil.pid_exists`）；只有当依赖确实绑定平台时才收窄限定，并在 `## Pitfalls` 中说明原因。

## 大小限制

- 完整 SKILL.md：强制执行 ≤ 100,000 个字符（`MAX_SKILL_CONTENT_CHARS`），但目标是**简单 skill 约 100 行，复杂 skill 约 200 行**。同类 skill 在 8-14k 字符之间。
- 篇幅较大或分支专用的材料放进 `references/*.md`、`templates/` 或 `scripts/`——从 SKILL.md 指向它们，而不是内联。
- 不要指望模型每次调用都内联编写解析器或复杂逻辑——在 `scripts/` 中提供辅助脚本，并按路径引用它。

## 正文结构（现代章节顺序）

```
# <Skill> Skill
2-3 sentence intro: what it does, what it doesn't do, dependency stance.

## When to Use          — bulleted triggers (+ "Don't use for:" counter-triggers)
## Prerequisites        — exact env vars, installs, API key sourcing
## How to Run           — canonical invocation through the `terminal` tool
## Quick Reference      — flat command list, no narration
## Procedure            — numbered steps, each with a checkable completion criterion
## Pitfalls             — known limits, things that look broken but aren't
## Verification         — how to prove the skill worked
```

并非每个章节都适用于每个 skill（纯流程类任务 skill 可能没有 Quick Reference），但 When to Use + 可执行的正文 + Pitfalls + Verification 是最低要求。删掉营销式开场白、空转的 "Setup Check"，以及对 Prerequisites 中已说明的环境变量的重复解释。

### 引用 Hermes 工具，而不是原始 shell

当 skill 需要某种能力时，用反引号写出对应的 Hermes 工具：`terminal`、`read_file`、`write_file`、`patch`、`search_files`、`web_search`、`web_extract`、`browser_navigate`、`vision_analyze`、`delegate_task`、`cronjob`。**不要**写出 agent 已有封装的 shell 工具（`grep` → `search_files`，`cat` → `read_file`，`sed`/`awk` → `patch`，`find`/`ls` → `search_files target='files'`）。CLI 封装类 skill 应把调用写成 `terminal(command="<tool> ...", timeout=...)` 的形式——纯 shell 叙述（"运行 `foo --version`"）是会阻塞评审的不合规项。如果 skill 依赖某个 MCP 服务器，请写明其名称并在 Prerequisites 中记录配置方法。

### 绝不使用机器本地路径

写仓库相对路径（`skills/...`、`tools/skill_manager_tool.py`）。写进已提交 skill 的 `/home/<you>/...` 路径会对其他所有用户失效，并会立即在评审中被标记。

## 写作质量原则

Skill 的存在是为了让 agent 的处理过程更可预测——让 agent 可靠地遵循同一套有用的准则。

1. **面向过程可预测性优化。** 如果某一行不改变行为，就删掉它。
2. **选择合适的上下文负载。** description 每轮都要付出代价；细节放进正文或链接的参考文件。
3. **每个步骤都以完成标准收尾。** 可检查，必要时穷尽："每个被修改的文件都已交代清楚"胜过"总结改动"。
4. **让规则与其约束的概念放在一起。**
5. **使用有力的引导词**（"tight loop"、"root cause"、"regression test"），而不是反复的长篇解释。
6. **清除重复与空转内容。** "小心点"和"使用最佳实践"不会改变模型行为——用可检查的标准替换它们，或者删除。

## 测试与文档（仓库 skill 必需）

1. **测试**位于 `tests/skills/test_<skill>_skill.py`——只用标准库 + pytest + `unittest.mock`，不访问实时网络。通过 `scripts/run_tests.sh tests/skills/test_<skill>_skill.py -q` 运行。（通用的 `tests/tools/test_skill_manager_tool.py` 通过，并不能证明**你的** skill 的任何情况。）
2. **重新生成文档：** 运行 `python website/scripts/generate-skill-docs.py`，然后遵守范围纪律——生成器会重写**所有**自动生成的页面。对不属于你的所有内容执行 `git checkout --`；最终 diff 只能包含你的 SKILL.md、你的那一个 skill 文档页面、目录中的一行条目，以及 `website/sidebars.ts` 中插入的一行（用 `search_files(pattern='<your-slug>', path='website/sidebars.ts')` 验证——恰好一个匹配，否则该页面就是孤立页面）。
3. **`.env.example`**（仅当 skill 需要新的环境变量时）：一个界限清晰的注释块；不要改动该文件中的其他内容。

## 工作流程

1. 用 `search_files(target='files')` **调研目标类别中的同类 skill**，阅读 2-3 个同类 SKILL.md 文件以匹配语气和结构。优先扩展现有 skill，而不是新建一个狭窄的兄弟 skill。
2. **决定层级和类别**（见上文）。拿不准时选可选——并在推送前先询问，而不是默认处理。
3. 用 `write_file` **起草**到 `skills/<category>/<name>/SKILL.md`（或 `optional-skills/...`）。
4. **本地验证**：
   ```python
   import yaml, re, pathlib
   content = pathlib.Path("skills/<category>/<name>/SKILL.md").read_text()
   assert content.startswith("---")
   m = re.search(r'\n---\s*\n', content[3:])
   fm = yaml.safe_load(content[3:m.start()+3])
   assert "name" in fm and "description" in fm
   assert len(fm["description"]) <= 60, f"description {len(fm['description'])} chars — hardline is 60"
   assert fm["description"].endswith(".")
   assert "platforms" in fm
   assert len(content) <= 100_000
   ```
   同时验证每个 `related_skills` 条目都存在于仓库中。
5. **添加测试 + 重新生成文档**（见上一节）。
6. 在当前分支上 **Git add + commit**；发起 PR。
7. **注意：** 当前会话的 skill 加载器是缓存的——在新会话之前，`skill_view` / `skills_list` 看不到新 skill。这是预期行为，不是 bug。

## 编辑现有的仓库内 Skill

- **小修复：** `skill_manage(action='patch', ...)` 对仓库内 skill 有效，`patch` 也可以。
- **大规模重写：** 用 `write_file` 写入整个 SKILL.md。
- **支持文件：** 用 `write_file` 写入 skill 目录下的 `references/`、`templates/` 或 `scripts/`。
- **务必提交**——仓库内 skill 是源代码，而不是运行时状态。frontmatter 变更后要重新运行文档生成器。

## 常见陷阱

1. **对仓库内 skill 使用 `skill_manage(action='create')`。** 它写入的是 `~/.hermes/skills/`，而不是仓库目录树。请使用 `write_file`。
2. **把验证器的限制当作标准。** 验证器允许 1024 个字符的 description；评审会拒绝超过 60 个字符的内容。验证器不检查 `platforms:`、author 格式、测试或文档——评审会检查。
3. **在贡献的 skill 上写 `author: Hermes Agent`。** 先署人名。
4. **`---` 之前有前导空白。** 任何前导空行或 BOM 都会导致验证失败。
5. **description 过于笼统，或触发条件埋在第 57 个字符之后。**
6. **`related_skills` 指向仓库中不存在的 skill**（用户本地的、计划中的或位于兄弟 PR 中的）。
7. **与同类 skill 重复。** 先调研类别；扩展而不是另建兄弟 skill。
8. **跳过文档生成器，或把其无关的漂移一并推送。** 两个方向都是错的：不重新生成 = 没有文档页面的孤立 skill；盲目重新生成 = 充斥着其他 skill 漂移的膨胀 diff。
9. **期望当前会话能看到新 skill。** 加载器在会话启动时初始化。
10. **让 skill 堆积沉积物。** 添加一条规则时，删除它所取代的旧措辞。

## 验证清单

- [ ] 层级经过慎重决定（内置门槛：每月 5 个以上会话；否则放入 `optional-skills/`）
- [ ] 文件位于 `skills/<category>/<name>/SKILL.md` 或 `optional-skills/<category>/<name>/SKILL.md`
- [ ] Frontmatter 从第 0 字节以 `---` 开始，以 `\n---\n` 结束
- [ ] `name`、`description`、`version`、`author`、`license`、`platforms`、`metadata.hermes.{tags, related_skills}` 全部存在
- [ ] Description ≤ 60 个字符，一句话，以句号结尾，无营销词汇
- [ ] `author` 首先署名人类贡献者
- [ ] `platforms:` 已根据实际正文/脚本审查，而不是从兄弟 skill 复制
- [ ] 每个 `related_skills` 条目都能在仓库中解析
- [ ] 正文遵循现代章节顺序；命令通过 Hermes 工具表述
- [ ] 文件中任何地方都没有机器本地路径
- [ ] 每个有序步骤都有可检查的完成标准
- [ ] `tests/skills/test_<skill>_skill.py` 中的测试在 `scripts/run_tests.sh` 下通过
- [ ] 按范围纪律重新生成文档；侧边栏中该 slug 恰好有一个条目
- [ ] 在目标分支上 `git add` + commit；已发起 PR
