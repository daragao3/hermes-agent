---
title: "Setup Wizard Generator —— 生成一个引导人工完成手动设置的 bash 向导"
sidebar_label: "Setup Wizard Generator"
description: "生成一个引导人工完成手动设置的 bash 向导"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Setup Wizard Generator

生成一个引导人工完成手动设置的 bash 向导。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/devops/setup-wizard-generator` 安装 |
| 路径 | `optional-skills/devops/setup-wizard-generator` |
| 版本 | `1.0.0` |
| 作者 | Matt Pocock (mattpocock/skills, wizard) + Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos |
| 标签 | `wizard`, `setup`, `onboarding`, `credentials`, `secrets`, `migration`, `bash`, `human-in-the-loop` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Setup Wizard Generator

生成一个交互式 bash **向导**：一个逐步引导人工完成某个手动流程的脚本——
这种流程手动操作很繁琐，每次重新解释一遍也很繁琐。它会打开每个 URL，
准确说明要点击和复制什么，捕获这些值，把它们写到该去的地方（`.env`、GitHub
secrets），在每个阶段进行确认，并显示还剩多少个阶段。

移植自 mattpocock/skills 中采用 MIT 许可证的 `wizard` skill。

## 何时使用 {#when-to-use}

- 开通基础设施或第三方服务（Stripe、Supabase、
  DNS、OAuth 应用），而控制台中的操作只能由人工点击完成
- 设置凭据、CI secrets 或仓库变量
- 带有不可逆、需人工把关步骤的一次性迁移或切换
- 任何用户会交给队友去执行的流程

不要用于 agent 自己就能完成的步骤——那些直接做就行。

## 前置条件 {#prerequisites}

- `bash`；仅当某些阶段需要写入 GitHub secrets/variables 时才需要 `gh` CLI
- 库模板：本 skill 目录下的 `templates/template.sh`

## 操作步骤 {#procedure}

### 1. 界定流程范围 {#1-scope-the-procedure}

梳理出人工必须执行的每一个手动步骤，以及沿途捕获的每一个值。
先读仓库，不要凭空提问：

- 设置类：`.env`、`.env.example`、`README`、`docker-compose*`、框架
  配置，以及 `.github/workflows/*`（每一处 `secrets.*` / `vars.*` 引用
  都是向导必须产出的一个值）。
- 迁移/切换类：当前状态、目标状态，以及二者之间的
  不可逆操作。

向用户展示有序的阶段列表以及每个阶段产出的值；用户可以
增加、删除或调整顺序。当每个阶段都已按顺序命名，并且对于每个
捕获的值，你都清楚 (a) 人工从哪里获取它，(b) 它被写到哪里
（`.env`、GitHub secret、两者都写，或都不写），以及 (c) 它是机密的
（隐藏输入）还是公开的，此步完成。

### 2. 描绘每个阶段的操作路径 {#2-map-each-stages-journey}

为每个阶段写出人工要遵循的精确路径：打开哪个 URL，
在那里做什么，值显示在哪里——例如 "Dashboard → Developers →
API keys → Reveal test key → copy"。如果你不了解当前的 UI 或
确切命令，就如实说明，并查阅文档或询问——绝不要编造
可能并不存在的步骤。

### 3. 编写向导 {#3-author-the-wizard}

将 `templates/template.sh`（来自本 skill 的目录）复制到目标
路径。把示例阶段替换为每个步骤一个 `stage`，按依赖
顺序排列。将 `TOTAL_STAGES` 设为你编写的阶段数量。

库辅助函数：`stage`、`say`/`step`/`note`/`warn`、`open_url`、
`ask`/`ask_secret`、`write_env`、`set_secret`/`set_var`、`pause`/`confirm`、
`banner`、`finish`。`STAGES` 标记之上的库部分在
每个向导中都完全相同——绝不要手动编辑它；保持这种一致性正是其意义所在。

遵守模板设定的标准：先打开 URL 再询问它对应的值，
任何机密内容都用 `ask_secret`，每个需要持久化的值都用 `write_env`，
只对 CI 真正需要的值使用 `set_secret`，并在任何不可逆操作之前先 `confirm`。
每个 `stage` 都会清屏——每个阶段只保留一个聚焦的任务，
这样人工需要的内容就不会被滚走。

向导默认是临时性的：把它保存到临时目录或 `scripts/` 路径下，
任务完成后删除。只有当用户希望在仓库中保留一个
可重复使用的设置路径时，才提交它。

### 4. 验证并交付 {#4-verify-and-hand-off}

- `bash -n <script>`；如有可用则运行 `shellcheck`；`chmod +x <script>`。
- 不要自己端到端运行它：它会打开浏览器并阻塞等待人工
  输入。改为静态追踪：第 1 步中的每个值都被捕获，并落到
  第 1 步所说的位置，且每个 `set_secret` 的名称都与 CI 中的某个
  `secrets.*` 引用完全一致。
- 告诉用户如何运行它。如果它可重复使用，就提交它并在
  README 中链接它。

## 常见陷阱 {#pitfalls}

1. **编辑库部分。** `STAGES` 标记之上的所有内容都是
   向导库；只在它下方编写。
2. **编造控制台路径。** 第三方 UI 会不断变化。如果不确定
   点击路径，请对照当前文档核实，或将其标注为近似路径。
3. **对 CI 用不到的值使用 `set_secret`。** 只把工作流实际引用的值
   推送到 GitHub secrets。
4. **自己运行向导。** 它会阻塞等待人工输入；静态追踪
   加上 `bash -n` 才是验证方式。
5. **一个巨型阶段。** 每个阶段都会清屏，这意味着一个很长的阶段会把
   关键说明滚走；请拆分它。

## 验证 {#verification}

- [ ] 编写前已与用户确认阶段列表
- [ ] `bash -n` 通过；脚本可执行
- [ ] 每个捕获的值都已追踪到其声明的目标位置
- [ ] 每个 `set_secret` 名称都与 CI 中的某个 `secrets.*` 引用匹配
- [ ] 库部分与模板保持一致，未被改动
