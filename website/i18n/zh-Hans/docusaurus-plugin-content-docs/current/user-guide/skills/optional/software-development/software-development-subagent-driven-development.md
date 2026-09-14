---
title: "Subagent Driven Development — 通过 delegate_task 子 agent 执行计划（两阶段评审）"
sidebar_label: "Subagent Driven Development"
description: "通过 delegate_task 子 agent 执行计划（两阶段评审）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Subagent Driven Development

通过 delegate_task 子 agent 执行计划（两阶段评审）。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/software-development/subagent-driven-development` 安装 |
| 路径 | `optional-skills/software-development/subagent-driven-development` |
| 版本 | `1.1.0` |
| 作者 | Hermes Agent（改编自 obra/superpowers） |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `delegation`, `subagent`, `implementation`, `workflow`, `parallel` |
| 相关 skills | [`plan`](/user-guide/skills/bundled/software-development/software-development-plan), [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review), [`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Subagent-Driven Development

## 概览

通过为每个任务派发全新的子 agent，并配合系统化的两阶段评审，来执行实现计划。

**核心原则：** 每个任务一个全新的子 agent + 两阶段评审（先规格、后质量）= 高质量、快迭代。

## 使用场景

在以下情况使用此 skill：
- 你已经有了一份实现计划（来自 `plan` skill 或用户需求）
- 各任务之间大体相互独立
- 质量与规格符合度很重要
- 你希望在任务之间自动进行评审

**与手工执行相比：**
- 每个任务都有全新的上下文（不会被累积状态搞混）
- 自动化的评审流程能尽早发现问题
- 所有任务都接受一致的质量检查
- 子 agent 可以在开工前提问

## 流程

### 1. 读取并解析计划

读取计划文件。一次性提取出所有任务的完整文本和上下文。创建一份待办列表：

```python
# 读取计划
read_file("docs/plans/feature-plan.md")

# 用所有任务创建待办列表
todo([
    {"id": "task-1", "content": "Create User model with email field", "status": "pending"},
    {"id": "task-2", "content": "Add password hashing utility", "status": "pending"},
    {"id": "task-3", "content": "Create login endpoint", "status": "pending"},
])
```

**要点：** 计划只读一次。把所有内容都提取出来。不要让子 agent 去读计划文件——直接在上下文中提供完整的任务文本。

### 2. 单任务工作流

对计划中的每一个任务：

#### 步骤 1：派发实现者子 agent

使用 `delegate_task` 并附上完整上下文：

```python
delegate_task(
    goal="Implement Task 1: Create User model with email and password_hash fields",
    context="""
    TASK FROM PLAN:
    - Create: src/models/user.py
    - Add User class with email (str) and password_hash (str) fields
    - Use bcrypt for password hashing
    - Include __repr__ for debugging

    FOLLOW TDD:
    1. Write failing test in tests/models/test_user.py
    2. Run: pytest tests/models/test_user.py -v (verify FAIL)
    3. Write minimal implementation
    4. Run: pytest tests/models/test_user.py -v (verify PASS)
    5. Run: pytest tests/ -q (verify no regressions)
    6. Commit: git add -A && git commit -m "feat: add User model with password hashing"

    PROJECT CONTEXT:
    - Python 3.11, Flask app in src/app.py
    - Existing models in src/models/
    - Tests use pytest, run from project root
    - bcrypt already in requirements.txt
    """,
    toolsets=['terminal', 'file']
)
```

#### 步骤 2：派发规格符合度评审者

在实现者完成之后，对照原始规格进行核验：

```python
delegate_task(
    goal="Review if implementation matches the spec from the plan",
    context="""
    ORIGINAL TASK SPEC:
    - Create src/models/user.py with User class
    - Fields: email (str), password_hash (str)
    - Use bcrypt for password hashing
    - Include __repr__

    CHECK:
    - [ ] All requirements from spec implemented?
    - [ ] File paths match spec?
    - [ ] Function signatures match spec?
    - [ ] Behavior matches expected?
    - [ ] Nothing extra added (no scope creep)?

    OUTPUT: PASS or list of specific spec gaps to fix.
    """,
    toolsets=['file']
)
```

**如果发现规格问题：** 补齐差距，然后重新运行规格评审。只有符合规格后才继续。

#### 步骤 3：派发代码质量评审者

在规格符合度通过之后：

```python
delegate_task(
    goal="Review code quality for Task 1 implementation",
    context="""
    FILES TO REVIEW:
    - src/models/user.py
    - tests/models/test_user.py

    CHECK:
    - [ ] Follows project conventions and style?
    - [ ] Proper error handling?
    - [ ] Clear variable/function names?
    - [ ] Adequate test coverage?
    - [ ] No obvious bugs or missed edge cases?
    - [ ] No security issues?

    OUTPUT FORMAT:
    - Critical Issues: [must fix before proceeding]
    - Important Issues: [should fix]
    - Minor Issues: [optional]
    - Verdict: APPROVED or REQUEST_CHANGES
    """,
    toolsets=['file']
)
```

**如果发现质量问题：** 修复问题，重新评审。只有通过后才继续。

#### 步骤 4：标记完成

```python
todo([{"id": "task-1", "content": "Create User model with email field", "status": "completed"}], merge=True)
```

### 3. 最终评审

在所有任务都完成之后，派发一名最终集成评审者：

```python
delegate_task(
    goal="Review the entire implementation for consistency and integration issues",
    context="""
    All tasks from the plan are complete. Review the full implementation:
    - Do all components work together?
    - Any inconsistencies between tasks?
    - All tests passing?
    - Ready for merge?
    """,
    toolsets=['terminal', 'file']
)
```

### 4. 验证并提交

```bash
# 运行完整测试套件
pytest tests/ -q

# 审阅全部改动
git diff --stat

# 如有需要，做最终提交
git add -A && git commit -m "feat: complete [feature name] implementation"
```

## 任务粒度

**每个任务 = 2-5 分钟的专注工作。**

**太大了：**
- "实现用户认证系统"

**大小合适：**
- "创建带 email 和 password 字段的 User 模型"
- "添加密码哈希函数"
- "创建登录端点"
- "添加 JWT token 生成"
- "创建注册端点"

## 危险信号 —— 绝不要这么做

- 没有计划就开始实现
- 跳过评审（规格符合度或代码质量）
- 在关键/重要问题未修复的情况下继续推进
- 为会改动同一批文件的任务派发多个实现子 agent
- 让子 agent 去读计划文件（应改为在上下文中提供完整文本）
- 省略背景铺垫（子 agent 需要理解该任务处在什么位置）
- 忽略子 agent 的提问（先回答，再让它继续）
- 在规格符合度上接受"差不多就行"
- 跳过评审循环（评审者发现问题 → 实现者修复 → 再次评审）
- 让实现者自评取代真正的评审（两者都需要）
- **在规格符合度 PASS 之前就开始代码质量评审**（顺序错误）
- 在任一评审仍有未解决问题时就转入下一个任务

## 问题处理

### 如果子 agent 提问

- 清晰、完整地回答
- 必要时补充额外上下文
- 不要催促它们赶紧实现

### 如果评审者发现问题

- 由实现者子 agent（或一个新的）来修复
- 评审者再次评审
- 重复直到通过
- 不要跳过复审

### 如果子 agent 任务失败

- 派发一个新的修复子 agent，并具体说明哪里出了问题
- 不要在控制器会话中手工修复（会污染上下文）

## 效率说明

**为什么每个任务都用全新的子 agent：**
- 避免累积状态造成的上下文污染
- 每个子 agent 都拿到干净、聚焦的上下文
- 不会被此前任务的代码或推理搞混

**为什么用两阶段评审：**
- 规格评审能尽早发现做少了或做多了
- 质量评审确保实现本身做得扎实
- 在问题跨任务累积之前就抓住它们

**成本权衡：**
- 子 agent 调用次数更多（每个任务一个实现者 + 两个评审者）
- 但能尽早发现问题（比事后调试叠加起来的问题更便宜）

## 与其他 skill 的集成

### 与 plan 配合

此 skill 负责执行由 `plan` skill 创建的计划：
1. 用户需求 → plan → 实现计划
2. 实现计划 → subagent-driven-development → 可运行的代码

### 与 test-driven-development 配合

实现者子 agent 应遵循 TDD：
1. 先写会失败的测试
2. 实现最小化代码
3. 验证测试通过
4. 提交

在每一份实现者上下文中都加入 TDD 指令。

### 与 requesting-code-review 配合

这套两阶段评审流程本身就是代码评审。做最终集成评审时，使用 requesting-code-review skill 的评审维度。

### 与 systematic-debugging 配合

如果子 agent 在实现过程中遇到 bug：
1. 遵循 systematic-debugging 流程
2. 先找到根因再修复
3. 写一个回归测试
4. 继续实现

## 示例工作流

```
[读取计划：docs/plans/auth-feature.md]
[创建包含 5 个任务的待办列表]

--- 任务 1：创建 User 模型 ---
[派发实现者子 agent]
  实现者："email 需要唯一吗？"
  你："是的，email 必须唯一"
  实现者：已实现，3/3 测试通过，已提交。

[派发规格评审者]
  规格评审者：✅ PASS —— 所有需求均已满足

[派发质量评审者]
  质量评审者：✅ APPROVED —— 代码干净，测试良好

[标记任务 1 完成]

--- 任务 2：密码哈希 ---
[派发实现者子 agent]
  实现者：没有问题，已实现，5/5 测试通过。

[派发规格评审者]
  规格评审者：❌ 缺失：密码强度校验（规格中写明"至少 8 个字符"）

[实现者修复]
  实现者：已加入校验，7/7 测试通过。

[再次派发规格评审者]
  规格评审者：✅ PASS

[派发质量评审者]
  质量评审者：重要：魔法数字 8，应提取为常量
  实现者：已提取 MIN_PASSWORD_LENGTH 常量
  质量评审者：✅ APPROVED

[标记任务 2 完成]

...（对所有任务重复）

[所有任务完成后：派发最终集成评审者]
[运行完整测试套件：全部通过]
[完成！]
```

## 牢记

```
每个任务一个全新的子 agent
每一次都做两阶段评审
规格符合度在先
代码质量在后
绝不跳过评审
尽早发现问题
```

**质量不是偶然的产物，而是系统化流程的结果。**

## 延伸阅读（需要时再加载）

当编排过程涉及大量上下文占用、漫长的评审循环或复杂的校验检查点时，加载这些参考资料以获取对应的具体方法：

- **`references/context-budget-discipline.md`** —— 四级上下文退化模型（PEAK / GOOD / DEGRADING / POOR）、随上下文窗口大小伸缩的读取深度规则，以及静默退化的早期预警信号。当一次运行明显会消耗大量上下文时（多阶段计划、大量子 agent、大型产物）加载它。
- **`references/gates-taxonomy.md`** —— 四种标准闸门类型（预检、修订、升级、中止）及其行为、恢复方式和示例。在设计或评审任何带校验检查点的工作流时加载它——显式使用这套术语，让每道闸门都有明确的进入条件、失败行为和恢复规则。

两份参考资料均改编自 gsd-build/get-shit-done（MIT © 2025 Lex Christopherson）。
