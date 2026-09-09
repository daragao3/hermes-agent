---
title: "Plan — Plan 模式：将可执行的 Markdown 计划写入"
sidebar_label: "Plan"
description: "Plan 模式：将可执行的 Markdown 计划写入"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Plan

Plan 模式：将可执行的 Markdown 计划写入 .hermes/plans/，不执行任何操作。任务粒度细小、路径精确、代码完整。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/software-development/plan` |
| 版本 | `2.0.0` |
| 作者 | Hermes Agent（写作技巧改编自 obra/superpowers） |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `planning`, `plan-mode`, `implementation`, `workflow`, `design`, `documentation` |
| 相关 skill | [`subagent-driven-development`](/docs/user-guide/skills/optional/software-development/software-development-subagent-driven-development), [`test-driven-development`](/docs/user-guide/skills/bundled/software-development/software-development-test-driven-development), [`requesting-code-review`](/docs/user-guide/skills/bundled/software-development/software-development-requesting-code-review) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Plan 模式

当用户需要计划而非执行时，使用此 skill。

## 核心行为

在本轮中，你仅进行规划。

- 不实现代码。
- 不编辑项目文件，计划 Markdown 文件除外。
- 不运行有副作用的终端命令，不提交、不推送，不执行外部操作。
- 必要时可使用只读命令/工具检查仓库或其他上下文。
- 你的交付物是保存在活跃工作区 `.hermes/plans/` 目录下的 Markdown 计划文件。

## 输出要求

编写一份具体且可操作的 Markdown 计划。

在相关时包含以下内容：
- 目标
- 当前上下文 / 假设
- 建议方案
- 分步计划
- 可能变更的文件
- 测试 / 验证
- 风险、权衡与待解问题

如果任务与代码相关，请包含精确的文件路径、可能的测试目标以及验证步骤。

## 保存位置

使用 `write_file` 将计划保存至：
- `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md`

将该路径视为相对于活跃工作目录 / 后端工作区的路径。Hermes 文件工具具备后端感知能力，使用此相对路径可确保计划文件在 local、docker、ssh、modal 和 daytona 后端上均与工作区保持一致。

如果运行时提供了具体的目标路径，则使用该精确路径。
如果没有，则自行在 `.hermes/plans/` 下创建一个合理的带时间戳的文件名。

## 交互风格

- 如果请求足够清晰，直接编写计划。
- 如果 `/plan` 没有附带明确指令，则从当前对话上下文中推断任务。
- 如果任务确实描述不足，提出简短的澄清问题，而非凭空猜测。
- 保存计划后，简要回复你所规划的内容及保存路径。
---

# 写好计划

本 skill 的其余部分讲述的是撰写一份*优秀*实现计划的技巧——也就是写入上述 Markdown 文件中的内容。

## 概述

编写全面的实现计划时，假设实现者对代码库毫无了解、品味也值得怀疑。把他们需要的一切都写清楚：要改哪些文件、完整的代码、测试命令、需要查阅的文档、如何验证。给他们粒度细小的任务。DRY、YAGNI、TDD、频繁提交。

假设实现者是一名熟练的开发者，但对工具链和问题领域几乎一无所知。假设他们并不太懂良好的测试设计。

**核心原则：** 一份好的计划会让实现变得显而易见。如果有人需要靠猜，说明计划不完整。

## 何时需要完整的实现计划

**在以下情况前务必使用：**
- 实现多步骤功能
- 拆解复杂需求
- 通过 subagent-driven-development 委派给 subagent

**在以下情况下也不要跳过：**
- 功能看起来很简单（假设会导致 bug）
- 你打算自己实现（未来的你也需要指引）
- 独自工作（文档同样重要）

## 细粒度任务

**每个任务 = 2-5 分钟的专注工作。**

每一步都是一个动作：
- “编写失败的测试”——一步
- “运行它以确认它确实失败”——一步
- “实现让测试通过的最小代码”——一步
- “运行测试并确认通过”——一步
- “提交”——一步

**过大：**
```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**大小合适：**
```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## 计划文档结构

### 文件头（必需）

每份计划都必须以以下内容开头：

```markdown
# [Feature Name] Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### 任务结构

每个任务遵循以下格式：

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Files:**
- Create: `exact/path/to/new_file.py`
- Modify: `exact/path/to/existing.py:45-67` (line numbers if known)
- Test: `tests/path/to/test_file.py`

**Step 1: Write failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify failure**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: FAIL — "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify pass**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## 编写流程

### 第 1 步：理解需求

阅读并理解：
- 功能需求
- 设计文档或用户描述
- 验收标准
- 约束条件

### 第 2 步：探索代码库

使用 Hermes 工具了解项目：

```python
# Understand project structure
search_files("*.py", target="files", path="src/")

# Look at similar features
search_files("similar_pattern", path="src/", file_glob="*.py")

# Check existing tests
search_files("*.py", target="files", path="tests/")

# Read key files
read_file("src/app.py")
```

### 第 3 步：设计方案

决定：
- 架构模式
- 文件组织方式
- 所需依赖
- 测试策略

### 第 4 步：编写任务

按顺序创建任务：
1. 搭建 / 基础设施
2. 核心功能（每项均采用 TDD）
3. 边界情况
4. 集成
5. 清理 / 文档

### 第 5 步：补全细节

每个任务都应包含：
- **精确的文件路径**（不要写“配置文件”，而要写 `src/config/settings.py`）
- **完整的代码示例**（不要写“添加校验”，而要给出实际代码）
- **精确的命令**及其预期输出
- **验证步骤**，用以证明该任务确实生效

### 第 6 步：复查计划

检查：
- [ ] 任务顺序合理且符合逻辑
- [ ] 每个任务粒度细小（2-5 分钟）
- [ ] 文件路径精确
- [ ] 代码示例完整（可直接复制粘贴）
- [ ] 命令精确并附预期输出
- [ ] 没有遗漏上下文
- [ ] 已应用 DRY、YAGNI、TDD 原则

## 原则

### DRY（不要重复自己）

**反例：** 在 3 个地方复制粘贴同样的校验逻辑
**正例：** 抽取出校验函数，各处复用

### YAGNI（你不会需要它）

**反例：** 为未来的需求预留“灵活性”
**正例：** 只实现当前真正需要的东西

```python
# Bad — YAGNI violation
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # Not needed yet!
        self.metadata = {}     # Not needed yet!

# Good — YAGNI
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
```

### TDD（测试驱动开发）

每个会产出代码的任务都应包含完整的 TDD 循环：
1. 编写失败的测试
2. 运行以确认失败
3. 编写最小实现代码
4. 运行以确认通过

详见 `test-driven-development` skill。

### 频繁提交

每完成一个任务就提交：
```bash
git add [files]
git commit -m "type: description"
```

## 常见错误

### 任务含糊

**反例：** “添加认证功能”
**正例：** “创建带有 email 和 password_hash 字段的 User 模型”

### 代码不完整

**反例：** “第 1 步：添加校验函数”
**正例：** “第 1 步：添加校验函数”，随后附上该函数的完整代码

### 缺少验证

**反例：** “第 3 步：测试它是否正常工作”
**正例：** “第 3 步：运行 `pytest tests/test_auth.py -v`，预期：3 passed”

### 缺少文件路径

**反例：** “创建模型文件”
**正例：** “创建：`src/models/user.py`”

## 移交执行

保存计划后，主动提出执行方案：

**“计划已完成并保存。可以使用 subagent-driven-development 来执行——我会为每个任务派发一个全新的 subagent，并进行两阶段审查（先审规范符合度，再审代码质量）。是否继续？”**

执行时，使用 `subagent-driven-development` skill：
- 为每个任务发起全新的 `delegate_task`，并附带完整上下文
- 每个任务完成后进行规范符合度审查
- 规范审查通过后再进行代码质量审查
- 两项审查都通过后才继续下一步

## 谨记

```
Bite-sized tasks (2-5 min each)
Exact file paths
Complete code (copy-pasteable)
Exact commands with expected output
Verification steps
DRY, YAGNI, TDD
Frequent commits
```

**一份好的计划会让实现变得显而易见。**
