---
sidebar_position: 2
title: "Skills 系统"
description: "按需加载的知识文档——渐进式披露、agent 管理的 skills 以及 Skills Hub"
---

# Skills 系统

Skills 是 agent 在需要时可以加载的按需知识文档。它们遵循**渐进式披露**（progressive disclosure）模式以最小化 token 用量，并兼容 [agentskills.io](https://agentskills.io/specification) 开放标准。

所有 skills 存放在 **`~/.hermes/skills/`** 中——这是主目录和唯一可信来源。全新安装时，捆绑的 skills 会从仓库复制过来。通过 Hub 安装和 agent 创建的 skills 也存放在此处。agent 可以修改或删除任何 skill。

你也可以让 Hermes 指向**外部 skill 目录**——与本地目录一起扫描的额外文件夹。参见下方的[外部 Skill 目录](#external-skill-directories)。

另请参阅：

- [捆绑 Skills 目录](/reference/skills-catalog)
- [官方可选 Skills 目录](/reference/optional-skills-catalog)

## 从空白状态开始

默认情况下，每个 profile 都会预置捆绑的 skill 目录，并且每次 `hermes update` 都会加入新捆绑的 skills。如果你想要一个**不含任何捆绑 skills** 的 profile——并且在更新后仍保持为空——有两条路径：

**在安装时**（适用于默认的 `~/.hermes` profile）：

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --no-skills
```

**在创建 profile 时**（具名 profile）：

```bash
hermes profile create research --no-skills
```

**在已安装的 profile 上**（默认或具名），可在运行时切换：

```bash
hermes skills opt-out            # 停止未来的预置——不会改动磁盘上的任何内容
hermes skills opt-out --remove   # 同时删除未被修改的捆绑 skills（会先确认）
hermes skills opt-in --sync      # 撤销：删除标记并立即重新预置
```

这三条路径都会在 profile 目录中写入一个 `.no-bundled-skills` 标记文件。只要该标记存在，安装器、`hermes update` 以及任何 skill 同步都会跳过该 profile 的捆绑 skill 预置。删除该标记（或运行 `hermes skills opt-in`）即可重新启用。

:::note 默认即安全
`hermes skills opt-out` 只会停止*未来*的预置——它绝不会删除磁盘上已有的任何内容。可选的 `--remove` 标志**仅**在捆绑 skills 未被修改（与 Hermes 安装的版本逐字节相同）时才会删除它们。你编辑过的 skills、从 hub 安装的 skills，以及你自己编写的 skills 始终会被保留。
:::

## 使用 Skills

每个已安装的 skill 都会自动作为斜杠命令可用：

```bash
# 在 CLI 或任何消息平台中：
/gif-search funny cats
/axolotl help me fine-tune Llama 3 on my dataset
/github-pr-workflow create a PR for the auth refactor
/songsee analyze the frequency spread of this mix

# 只输入 skill 名称即可加载它，并让 agent 询问你的需求：
/excalidraw
```

### 在一条命令中叠加多个 skills

你可以在一条消息中调用多个 skill：只需在开头连续串接斜杠命令——开头的每个 `/skill` token（最多 5 个）都会被加载，其余部分作为你的指令：

```bash
/github-pr-workflow /test-driven-development fix issue #123 and open a PR
```

解析会在第一个非已安装 skill 的 token 处停止，因此恰好以 `/` 开头的参数（例如文件路径）绝不会被吞掉：

```bash
/ocr-and-documents /tmp/scan.pdf extract the tables   # 加载一个 skill；/tmp/scan.pdf 是参数
```

对于你反复使用的组合，更推荐使用 [skill 捆绑包](#skill-bundles)——一条短命令即可达到同样的效果。

（计划模式的工作方式相同，但现在是内置命令：`/plan [request]` 告知 Hermes 在需要时检查上下文、编写 markdown 实现计划而非直接执行任务，并将结果保存在相对于当前工作区/后端工作目录的 `.hermes/plans/` 下。）

你也可以通过自然对话与 skills 交互：

```bash
hermes chat --toolsets skills -q "What skills do you have?"
hermes chat --toolsets skills -q "Show me the axolotl skill"
```

## 从资料中学习一个 skill（`/learn`）

`/learn` 是把你已经掌握的知识——或一堆参考资料——快速变成可复用 skill 的方式，而无需手写 `SKILL.md`。它是开放式的：把它指向*任何你能描述的东西*，agent 会用它已有的工具收集材料，然后按照[本项目的编写规范](#skillmd-format)撰写一个 skill（描述不超过 60 字符、标准的章节顺序、以 Hermes 工具为框架、不臆造命令）。

```bash
# 本地 SDK 或文档目录——用 read_file / search_files 读取
/learn the REST client in ~/projects/acme-sdk, focus on auth + pagination

# 在线文档页面——用 web_extract 抓取
/learn https://docs.example.com/api/quickstart

# 你刚刚在本次对话中带着 agent 走过的工作流
/learn how I just deployed the staging server

# 粘贴的笔记 / 口述的操作步骤
/learn filing an expense: open the portal, New > Expense, attach the receipt, submit

# 整本书、一叠论文或大型文档语料——会变成一个知识库 skill
/learn ~/books/designing-data-intensive-applications.pdf
```

### 大型资料会变成知识库 skill {#large-sources-become-knowledge-base-skills}

当资料是一本书、一叠论文、一份规范或一个大型文档文件夹时，agent 不会把它塞进单个文件，
也不会把它压缩成有损的摘要。相反，它会编写一个**扩展型知识库 skill**：一个精简的 `SKILL.md`，
承载资料的核心心智模型以及一份索引，并在 `references/` 下为每一章或每个主题提供一个提炼后的
文件（在资料值得时还会附上术语表或速查表）。参考文件在有问题需要它之前不产生任何开销——agent
会按需通过 `skill_view` 加载它们，因此查询成本与答案成正比，而不是与资料规模成正比。针对同一
主题用新材料再次运行 `/learn`，会把新内容并入已有的 skill，而不是创建一个重复的 skill。

提炼过程综合的是结构——框架、定义、决策规则、反模式——绝不会复现资料原文的段落。

由于是实时的 agent 完成资料收集，`/learn` 在 CLI、消息 gateway、TUI 和仪表板中的表现完全一致——在任何终端后端（本地、Docker、远程）上也是如此，因为它没有独立的摄取引擎。在**仪表板**中，Skills 页面有一个 **Learn a skill** 按钮，会打开一个包含目录字段、URL 字段和开放式文本框的面板；它会组装出一条 `/learn` 请求并在聊天中运行。

它没有模型工具层面的开销：`/learn` 会构建一条遵循规范的提示词，并作为普通轮次交给 agent。agent 使用 `skill_manage` 工具保存结果，因此如果你启用了[写入审批门禁](#gating-agent-skill-writes-skillswrite_approval)，它同样适用。

## 渐进式披露

Skills 使用一种节省 token 的加载模式：

```
Level 0: skills_list()           → [{name, description, category}, ...]   (~3k tokens)
Level 1: skill_view(name)        → Full content + metadata       (varies)
Level 2: skill_view(name, path)  → Specific reference file       (varies)
```

agent 只在真正需要时才加载完整的 skill 内容。

## SKILL.md 格式 {#skillmd-format}

```markdown
---
name: my-skill
description: Brief description of what this skill does
version: 1.0.0
platforms: [macos, linux]     # Optional — restrict to specific OS platforms
metadata:
  hermes:
    tags: [python, automation]
    category: devops
    fallback_for_toolsets: [web]    # Optional — conditional activation (see below)
    requires_toolsets: [terminal]   # Optional — conditional activation (see below)
    config:                          # Optional — config.yaml settings
      - key: my.setting
        description: "What this controls"
        default: "value"
        prompt: "Prompt for setup"
---

# Skill Title

## When to Use
Trigger conditions for this skill.

## Procedure
1. Step one
2. Step two

## Pitfalls
- Known failure modes and fixes

## Verification
How to confirm it worked.
```

### 平台特定 Skills

Skills 可以使用 `platforms` 字段将自身限制在特定操作系统上：

| 值 | 匹配 |
|-------|---------|
| `macos` | macOS（Darwin） |
| `linux` | Linux |
| `windows` | Windows |

```yaml
platforms: [macos]            # macOS only (e.g., iMessage, Apple Reminders, FindMy)
platforms: [macos, linux]     # macOS and Linux
```

设置后，该 skill 会在不兼容的平台上自动从系统提示词、`skills_list()` 和斜杠命令中隐藏。若省略，则在所有平台上加载。

## Skill 输出与媒体传递 {#skill-output-and-media-delivery}

当 skill 响应（或任何 agent 响应）包含指向媒体文件的裸绝对路径时——例如 `/home/user/screenshots/diagram.png`——gateway 会自动检测到它，将其从可见文本中剥离，并以原生方式将文件传递给用户的聊天界面（Telegram 图片、Discord 附件等），而不是在消息中留下原始路径。

对于音频，`[[audio_as_voice]]` 指令会将音频文件提升为在支持该功能的平台（Telegram、WhatsApp）上的原生语音消息气泡。

### 强制文档式传递：`[[as_document]]`

有时你需要与内联预览**相反**的效果：你希望文件作为可下载附件传递，而不是经过重新压缩的图片气泡。典型示例是高分辨率截图或图表——Telegram 的 `sendPhoto` 会将其重新压缩至约 200 KB、1280 px，严重影响可读性。通过 `sendDocument` 发送的 1-2 MB PNG 则保留原始字节完整无损。

如果响应（或其中任何文本——通常是最后一行）包含字面指令 `[[as_document]]`，则从该响应中提取的每个媒体路径都会作为文档/文件附件传递，而不是图片气泡：

```
Here is your rendered chart:

/home/user/.hermes/cache/chart-q4-2025.png

[[as_document]]
```

该指令在传递前会被剥离，用户不会看到它。粒度有意设计为每个响应全有或全无：发出一次 `[[as_document]]`，同一响应中的每个图片路径都会作为文档传递。这与 `[[audio_as_voice]]` 的作用范围一致。

在以下情况下从 skill 中使用它：

- 你生成了用户需要作为文件的截图或图表（用于在其他工具中编辑、存档、完整分享）。
- 默认的有损预览会遮蔽细节（小字体、像素精确的图表、对颜色敏感的渲染）。

没有单独文档路径的平台（如 SMS）会回退到其支持的任何附件机制。

### 条件激活（Fallback Skills）

Skills 可以根据当前会话中可用的工具自动显示或隐藏自身。这对于**fallback skills**（回退 skills）最为有用——仅在高级工具不可用时才应出现的免费或本地替代方案。

```yaml
metadata:
  hermes:
    fallback_for_toolsets: [web]      # Show ONLY when these toolsets are unavailable
    requires_toolsets: [terminal]     # Show ONLY when these toolsets are available
    fallback_for_tools: [web_search]  # Show ONLY when these specific tools are unavailable
    requires_tools: [terminal]        # Show ONLY when these specific tools are available
```

| 字段 | 行为 |
|-------|----------|
| `fallback_for_toolsets` | 当列出的 toolsets 可用时，skill **隐藏**。不可用时显示。 |
| `fallback_for_tools` | 同上，但检查单个工具而非 toolsets。 |
| `requires_toolsets` | 当列出的 toolsets 不可用时，skill **隐藏**。可用时显示。 |
| `requires_tools` | 同上，但检查单个工具。 |

**示例：** 内置的 `duckduckgo-search` skill 使用 `fallback_for_toolsets: [web]`。当你设置了 `FIRECRAWL_API_KEY` 时，web toolset 可用，agent 使用 `web_search`——DuckDuckGo skill 保持隐藏。如果 API key 缺失，web toolset 不可用，DuckDuckGo skill 会自动作为 fallback 出现。

没有任何条件字段的 skills 行为与之前完全相同——始终显示。

## 加载时的安全设置

Skills 可以声明所需的环境变量，而不会从发现列表中消失：

```yaml
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: Tenor API key
    help: Get a key from https://developers.google.com/tenor
    required_for: full functionality
```

当遇到缺失的值时，Hermes 仅在本地 CLI 中实际加载 skill 时才会安全地请求输入。你可以跳过设置并继续使用该 skill。消息平台不会在聊天中请求密钥——它们会告诉你改用本地的 `hermes setup` 或 `~/.hermes/.env`。

一旦设置，声明的环境变量会**自动传递**到 `execute_code` 和 `terminal` 沙箱——skill 的脚本可以直接使用 `$TENOR_API_KEY`。对于非 skill 的环境变量，使用 `terminal.env_passthrough` 配置选项。详情参见[环境变量传递](/user-guide/security#environment-variable-passthrough)。

### Skill 配置设置

Skills 还可以声明存储在 `config.yaml` 中的非密钥配置设置（路径、偏好项）：

```yaml
metadata:
  hermes:
    config:
      - key: myplugin.path
        description: Path to the plugin data directory
        default: "~/myplugin-data"
        prompt: Plugin data directory path
```

设置存储在 config.yaml 的 `skills.config` 下。`hermes config migrate` 会提示配置未设置的项，`hermes config show` 会显示它们。当 skill 加载时，其解析后的配置值会注入到上下文中，agent 会自动知晓已配置的值。

详情参见 [Skill 设置](/user-guide/configuration#skill-settings) 和[创建 Skills——配置设置](/developer-guide/creating-skills#config-settings-configyaml)。

## Skill 目录结构

```text
~/.hermes/skills/                  # Single source of truth
├── mlops/                         # Category directory
│   ├── axolotl/
│   │   ├── SKILL.md               # Main instructions (required)
│   │   ├── references/            # Additional docs
│   │   ├── templates/             # Output formats
│   │   ├── scripts/               # Helper scripts callable from the skill
│   │   ├── examples/              # Referenced example outputs
│   │   └── assets/                # Supplementary files
│   └── vllm/
│       └── SKILL.md
├── devops/
│   └── deploy-k8s/                # Agent-created skill
│       ├── SKILL.md
│       └── references/
├── .hub/                          # Skills Hub state
│   ├── lock.json
│   ├── quarantine/
│   └── audit.log
└── .bundled_manifest              # Tracks seeded bundled skills
```

通过第三方 URL 或 GitHub 安装时，Hermes 会安装 `SKILL.md`，以及其中明确引用且位于 `references/`、`templates/`、`scripts/`、`assets/` 和 `examples/` 下的文件。未引用的仓库文件不会被复制。Hermes 会扫描完整的隔离捆绑包，并在 `skills/.hub/lock.json` 中记录来源 URL、精确内容哈希、扫描器版本、发现项、时间戳，以及本次结果是新扫描还是缓存复用。

### 建议性的 SkillEvaluator 扫描 {#advisory-skillevaluator-scan}

除了内置的安全扫描器（它负责执行上述安装策略）之外，Hermes 还可以在每次 hub 安装时运行
[NVIDIA SkillEvaluator](https://github.com/NVIDIA/SkillEvaluator) 的 Tier 1 检查作为第二意见。
Tier 1 是确定性的、无需密钥——包括 PII 检测（泄露的邮箱、个人路径、连接字符串）、Unicode
走私检测、脚本 lint、许可证合规，以及通过
[NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector) 进行的静态安全扫描。

该扫描**仅供参考**：发现项会在安装确认之前连同文件和行号一起打印出来，安装会继续进行。
看起来像真实凭据的发现项（私钥、云访问密钥、token、带凭据的连接字符串）会以红色高亮，
方便你在做决定之前审阅被标记的行。PII 类发现项仅作提示——上游扫描器有已知的误报类别
（例如 `git@github.com` SSH 语法、文档中的示例邮箱），因此它们永远不会阻止任何操作。

要启用它，请安装可选的扫描器二进制文件（第二个用于支撑 `security` 检查；没有它时该检查
只会报告“未运行”）：

```bash
uv tool install --python 3.13 \
  "skillevaluator @ git+https://github.com/NVIDIA/SkillEvaluator.git@v0.1.0"
uv tool install "git+https://github.com/NVIDIA/SkillSpector.git@v2.9.5"
```

如果 PATH 上没有该二进制文件，扫描会被静默跳过。要彻底关闭它：

```yaml
skills:
  tier1_advisory: false
```

仪表板 Browse-hub 的扫描按钮会在其响应中（`tier1` 字段）返回同样的建议性数据，并附带内置
扫描器的结论。

## 外部 Skill 目录 {#external-skill-directories}

如果你在 Hermes 之外维护 skills——例如，供多个 AI 工具使用的共享 `~/.agents/skills/` 目录——你可以告诉 Hermes 也扫描这些目录。

在 `~/.hermes/config.yaml` 的 `skills` 部分下添加 `external_dirs`：

```yaml
skills:
  external_dirs:
    - ~/.agents/skills
    - /home/shared/team-skills
    - ${SKILLS_REPO}/skills
```

路径支持 `~` 展开和 `${VAR}` 环境变量替换。

### 工作原理

- **本地创建，就地更新**：新的 agent 创建的 skills 写入 `~/.hermes/skills/`（配置了 `skills.create_dir` 时则写入该目录——见下文）。现有 skills 在找到的位置被修改，包括 `external_dirs` 下的 skills，当 agent 使用 `skill_manage` 操作（如 `patch`、`edit`、`write_file`、`remove_file` 或 `delete`）时。
- **外部目录不是写保护边界**：如果外部 skill 目录对 Hermes 进程可写，agent 管理的 skill 更新可以修改该目录中的文件。如果共享的外部 skills 必须保持只读，请使用文件系统权限或单独的 profile/toolset 设置。
- **本地优先**：如果同一 skill 名称同时存在于本地目录和外部目录中，本地版本优先。
- **完整集成**：外部 skills 出现在系统提示词索引、`skills_list`、`skill_view` 以及 `/skill-name` 斜杠命令中——与本地 skills 无异。
- **不存在的路径会被静默跳过**：如果配置的目录不存在，Hermes 会忽略它而不报错。适用于可能不在每台机器上都存在的可选共享目录。

### 示例

```text
~/.hermes/skills/               # Local (primary, read-write)
├── devops/deploy-k8s/
│   └── SKILL.md
└── mlops/axolotl/
    └── SKILL.md

~/.agents/skills/               # External (shared, mutable if writable)
├── my-custom-workflow/
│   └── SKILL.md
└── team-conventions/
    └── SKILL.md
```

所有四个 skills 都出现在你的 skill 索引中。如果你在本地创建一个名为 `my-custom-workflow` 的新 skill，它会遮蔽外部版本。

## 重定向 Skill 创建位置（`skills.create_dir`） {#redirecting-skill-creation-skillscreate_dir}

默认情况下，agent 会把新 skill 写入 profile 本地的 `~/.hermes/skills/`。如果你希望 agent 创建的 skill 落在别处——一个共享的“大脑”目录、一个受 git 跟踪的仓库，或一个全机队共用的 skills 卷——请在 `skills` 部分下设置 `create_dir`：

```yaml
skills:
  create_dir: /opt/brain/skills
```

这会改变：

- **`skill_manage` 的 create 会写入该目录。** 新 skill（包括分类子目录）会在 `create_dir` 下创建，而不是在本地 skills 目录中。该目录若不存在，会在首次写入时创建。
- **agent 的指令会跟随配置。** 所有提及 skill 创建路径的面向 agent 的指令——`skill_manage` 工具描述以及相关的提示文本——都会动态渲染所配置的目录，因此 agent 会被告知在那里创建 skill。无需覆盖系统 prompt，也无需任何文件系统技巧。
- **该目录完全集成。** `create_dir` 下的 skill 会与本地目录一同扫描：它们会出现在 skill 索引、`skills_list`、`skill_view` 和斜杠命令中，并且可以像任何本地 skill 一样被 patch 或删除。
- **其他一切保持本地。** 已有的 skill 仍在其所在位置被原地修改；捆绑 skill 同步、hub 和 curator 继续作用于 profile 本地目录。

路径支持 `~` 展开和 `${VAR}` 替换；相对路径相对于你的 Hermes 主目录解析。把 `create_dir` 设为本地 skills 目录等同于不设置。


## 项目本地 Skill {#project-local-skills}

仓库可以携带自己的 skill，这些 skill 只在该项目内启动的会话中生效——这与其他 agent 工具用于仓库本地配置的模式相同。当你在 git 检出目录中启动 Hermes 时，它会在以下位置查找 skill：

```text
<project-root>/.hermes/skills/    # Hermes 原生位置
<project-root>/.agents/skills/    # 跨工具约定（与其他 agent CLI 共享）
```

项目根目录是包含 `.git` 的最近的祖先目录（worktree 和 submodule 同样算数）。

### 信任一个项目 {#trusting-a-project}

Skill 是 agent 会遵循的流程文档，因此 Hermes **不会**从任意克隆的仓库中自动加载它们。当你第一次在带有项目 skill 的仓库中运行 Hermes 时，横幅会显示一条提示：

```text
◆ 3 project skill(s) found in /home/you/myproject but not loaded — run `hermes skills trust` to enable them.
```

信任该仓库一次即可（在仓库内部运行，或传入路径）：

```bash
hermes skills trust             # 信任当前仓库
hermes skills trust ~/myproject # 或显式指定
hermes skills untrust           # 撤销
```

受信任的根目录保存在 `~/.hermes/config.yaml` 的 `skills.trusted_project_dirs` 中。设置 `skills.project_discovery: false` 可彻底关闭该功能（不扫描，也不提示）。

### 优先级 {#precedence}

项目 skill 属于**最高优先级层**：`project → local (~/.hermes/skills/) → external_dirs`。一个名为 `deploy` 的项目 skill 会在该仓库内的会话中覆盖同名的 profile skill 或捆绑 skill——这正是其用意：随仓库提供的 skill 在自己的主场胜出，而不会触及你的全局 profile。项目 skill 在 agent 的 skill 索引中带有 `[project]` 标签，以便来源始终可见。

与外部目录一样，项目 skill 目录被视为归仓库所有：自主的 skill 维护（curator）从不修改它们，而 agent 新创建的 skill 总是写入 `~/.hermes/skills/`。

### 扫描时隔离 {#scan-time-quarantine}

信任是仓库级别的决定，但仓库中的 skill 内容会随着每次 `git pull` 而变化。为了弥补这一缺口，每个项目 skill 在进入索引之前，都会用与 Skills Hub 安装相同的安全扫描器进行扫描。扫描结论为**危险**的 skill（提示注入指令、凭据外泄命令、隐藏文本伎俩）会被隔离：它不会出现在 skill 索引、`skills_list` 和斜杠命令中，并且按名称加载时会以一条解释性错误拒绝加载。扫描结果按内容哈希缓存在 `~/.hermes/cache/project_skill_scans/` 下（绝不会放在你的仓库内），并在 skill 内容变化时自动重新运行。

### 非交互式界面（cron、API、ACP） {#non-interactive-surfaces-cron-api-acp}

Cron 任务和其他非交互式界面沿用你在交互中做出的信任决定——它们从不提示，也从不自动信任。项目根目录根据该界面的工作目录解析（cron 任务的 `workdir`，与 terminal 工具使用的机制相同）。`workdir` 位于你先前已信任的仓库内的 cron 任务会加载该仓库的项目 skill；位于未信任或尚未决定的仓库中的任务则不会加载任何项目 skill。

## Skill 捆绑包 {#skill-bundles}

Skill 捆绑包是将多个 skills 归组在单个斜杠命令下的小型 YAML 文件。当你运行 `/<bundle-name>` 时，捆绑包中列出的每个 skill 都会同时加载——当某个特定任务总是受益于同一组 skills 时非常有用。

### 快速示例

```bash
# 为后端功能开发创建一个捆绑包
hermes bundles create backend-dev \
  --skill github-code-review \
  --skill test-driven-development \
  --skill github-pr-workflow \
  -d "Backend feature work — review, test, PR workflow"
```

然后在 CLI 或任何 gateway 平台中：

```
/backend-dev refactor the auth middleware
```

agent 接收到所有三个 skills 加载到一条用户消息中，斜杠命令后的任何文本都作为用户指令附加。

### YAML 模式

捆绑包存放在 **`~/.hermes/skill-bundles/<slug>.yaml`** 中，格式如下：

```yaml
name: backend-dev
description: Backend feature work — review, test, PR workflow.
skills:
  - github-code-review
  - test-driven-development
  - github-pr-workflow
instruction: |
  Always start by writing failing tests, then implement.
  Open the PR through the standard workflow with co-author tags.
```

字段说明：
- `name`（可选——默认为文件名主干）——捆绑包的显示名称。规范化为连字符 slug 用于斜杠命令（`Backend Dev` → `/backend-dev`）。
- `description`（可选）——在 `/bundles` 和 `hermes bundles list` 中显示的简短文本。
- `skills`（必填，非空列表）——skill 名称或相对于你的 skills 目录的路径。使用与 `/<skill-name>` 相同的标识符。
- `instruction`（可选）——附加在加载的 skill 内容前的额外指导。适用于固化"我们总是这样一起使用这些 skills"的方式。

### 管理捆绑包

```bash
# 列出所有已安装的捆绑包
hermes bundles list

# 查看某个捆绑包
hermes bundles show backend-dev

# 交互式创建捆绑包（省略 --skill 标志以逐行输入）
hermes bundles create research

# 覆盖现有捆绑包
hermes bundles create backend-dev --skill ... --force

# 删除捆绑包
hermes bundles delete backend-dev

# 重新扫描 ~/.hermes/skill-bundles/ 并报告变更
hermes bundles reload
```

在聊天会话中，`/bundles` 会列出每个已安装的捆绑包及其 skills。

### 行为

- **当 slug 冲突时，捆绑包优先于单个 skills。** 如果你将捆绑包命名为 `research`，同时也有一个名为 `research` 的 skill，`/research` 会调用捆绑包。这是有意为之——你通过命名选择了捆绑包。
- **缺失的 skills 会被跳过，而不是致命错误。** 如果捆绑包列出了 `skill-foo` 但你未安装它，捆绑包仍会加载能解析的 skills，agent 会收到一条列出跳过内容的说明。
- **捆绑包在每个界面都有效**——交互式 CLI、TUI、仪表板聊天以及每个 gateway 平台（Telegram、Discord、Slack……）——因为调度与单个 skill 命令集中在同一位置。
- **捆绑包不会使 prompt 缓存失效。** 它们在调用时生成一条新的用户消息，与 `/<skill-name>` 的方式相同——不修改系统提示词。

### 捆绑包优于逐个手动安装 skill 的场景

在以下情况下使用捆绑包：
- 你总是为某个重复任务配对相同的 skills（`/backend-dev`、`/release-prep`、`/incident-response`）。
- 你想要比依次输入多个 `/skill` 调用更简洁的心智模型。
- 你想通过将捆绑包 YAML 提交到共享 dotfiles 仓库并符号链接到 `~/.hermes/skill-bundles/` 来发布团队范围的"任务配置文件"。

捆绑包只是一个 YAML 别名——它不会为你安装 skills。Skills 本身必须已经存在（在 `~/.hermes/skills/` 或外部 skill 目录中）。否则捆绑包调用只会跳过缺失的 skills。

## Agent 管理的 Skills（skill_manage 工具） {#agent-managed-skills-skill_manage-tool}

agent 可以通过 `skill_manage` 工具创建、更新和删除自己的 skills。这是 agent 的**程序性记忆**——当它找到一个非平凡的工作流时，它会将该方法保存为 skill 以供将来复用。

skills 与记忆在自我改进循环中协同工作：记忆存放应始终位于上下文中的、简短而持久的事实，而 skills 存放只在相关时才加载的较长流程。后台审查可以在一次会话之后建议或暂存 skill 变更，而下文的写入审批门禁则让你可以要求这些变更先经过人工审阅再落地。

### Agent 创建 Skills 的时机

系统 prompt 会要求 agent 用 `skill_manage` 记录非平凡的工作流，以便将来复用。实际上这涵盖：

- 当它摸索出一个值得重复使用的多步骤工作流时
- 遇到错误或死路并找到可行路径时
- 用户纠正了其方法时

### Skill 条目的样子 {#what-a-skill-entry-looks-like}

Skill 是按照你的要求、以最高效且正确的方式完成某一类任务的指令：按顺序排列的流程、行之有效的命令和工具调用、你希望结果呈现的样子，以及会浪费时间的陷阱。无论是在前台轮次中编写、由后台审查编写，还是由 curator 的整合流程编写，它记录的都是**经验，而不是日志**：一个陷阱就是一条可推广的规则，加上一句说明*原因*（其机制）的从句，附在它所影响的步骤上，只陈述一次。事件经过、PR 或 issue 编号、日期以及引用的聊天内容都不属于 skill 内容；规则必须脱离其背后的故事也能成立。始终生效的规则写在 `SKILL.md` 本身中；`references/` 存放少量按主题命名的文件（决策表、配方、提供方的怪癖），并在原文件上扩充，而不是每个会话累积一个文件。Skill 也不会重复每轮都已加载的内容（仓库的 `AGENTS.md`、工具 schema）。

`skill_manage` 会在 `create` 以及写入 `references/` 时运行一个建议性的 linter，并在工具结果中返回其发现项。有两条规则专门针对这种形态：`incident-log-shape`（正文中密集出现 PR/issue 编号）和 `references-sprawl`（参考文件超过 60 个）。它们只会警告，绝不会阻止写入。

### 操作

| 操作 | 用途 | 关键参数 |
|--------|---------|------------|
| `create` | 从头创建新 skill | `name`、`content`（完整 SKILL.md）、可选 `category` |
| `patch` | 针对性修复（首选） | `name`、`old_string`、`new_string` |
| `edit` | 重大结构性重写 | `name`、`content`（完整 SKILL.md 替换） |
| `delete` | 完全删除一个 skill | `name` |
| `write_file` | 添加/更新支持文件 | `name`、`file_path`、`file_content` |
| `remove_file` | 删除支持文件 | `name`、`file_path` |

:::tip
`patch` 操作是更新的首选方式——它比 `edit` 更节省 token，因为工具调用中只出现变更的文本。
:::

### 对 agent 的 skill 写入设置门禁（`skills.write_approval`） {#gating-agent-skill-writes-skillswrite_approval}

默认情况下 agent 可以自由写入 skills——包括来自轮次结束后运行的[后台自我改进审查](/user-guide/features/memory#controlling-memory-writes-write_approval)的写入。如果你更希望先审批每一次 skill 写入（例如小模型会误判自己学到了什么、处于安全敏感环境，或只是想盯着自我改进循环），可以打开写入审批门禁：

```yaml
skills:
  write_approval: false     # false = write freely (default) | true = require approval
```

当 `write_approval: true` 时，每一次 `skill_manage` 写入（create / edit / patch / delete / write_file / remove_file）都会被**暂存**而非直接提交——SKILL.md 体量太大，无法内联审阅，因此无论写入来自前台轮次还是后台审查，都一律暂存。暂存的写入保存在 `~/.hermes/pending/skills/` 下，可跨重启保留，并使用与危险命令相同、你已熟悉的批准/拒绝流程进行审阅：

```
/skills pending             # list staged skill writes + a one-line gist each
/skills diff <id>           # full unified diff (best viewed in CLI or dashboard)
/skills approve <id>        # apply it (or 'all')
/skills reject <id>         # drop it (or 'all')
/skills approval on         # turn the gate on (or 'off') and persist it
```

该审阅界面在交互式 CLI 和消息平台上均可使用（聊天气泡中的 diff 输出会被截断——请在 CLI 或 pending JSON 文件中查看完整 diff）。记忆写入在 `memory.write_approval` 下有同样的门禁——参见[控制记忆写入](/user-guide/features/memory#controlling-memory-writes-write_approval)。

> 另有一个独立的 `skills.guard_agent_created` 设置，它是内容扫描器（基于危险模式的启发式判断），而不是审批门禁——两者互相独立。参见 [对 agent 创建的 skill 写入设置防护](/user-guide/configuration#guard-on-agent-created-skill-writes)。

## Skills Hub

从在线注册表、`skills.sh`、直接的知名 skill 端点以及官方可选 skills 中浏览、搜索、安装和管理 skills。

### 常用命令

```bash
hermes skills browse                              # Browse all hub skills (official first)
hermes skills browse --source official            # Browse only official optional skills
hermes skills search kubernetes                   # Search all sources
hermes skills search react --source skills-sh     # Search the skills.sh directory
hermes skills search https://mintlify.com/docs --source well-known
hermes skills inspect openai/skills/k8s           # Preview before installing
hermes skills install openai/skills/k8s           # Install with security scan
hermes skills install official/security/1password
hermes skills install skills-sh/vercel-labs/json-render/json-render-react --force
hermes skills install well-known:https://mintlify.com/docs/.well-known/skills/mintlify
hermes skills install https://sharethis.chat/SKILL.md              # 直接 URL（含引用的支持文件）
hermes skills install https://example.com/SKILL.md --name my-skill # Override name when frontmatter has none
hermes skills list --source hub                   # List hub-installed skills
hermes skills check                               # Check installed hub skills for upstream updates
hermes skills update                              # Reinstall hub skills with upstream changes when needed
hermes skills audit                               # Re-scan all hub skills for security
hermes skills uninstall k8s                       # Remove a hub skill
hermes skills reset google-workspace              # Un-stick a bundled skill from "user-modified" (see below)
hermes skills reset google-workspace --restore    # Also restore the bundled version, deleting your local edits
hermes skills publish skills/my-skill --to github --repo owner/repo
hermes skills snapshot export setup.json          # Export skill config
hermes skills tap add myorg/skills-repo           # Add a custom GitHub source
```

### 支持的 hub 来源

| 来源 | 示例 | 说明 |
|--------|---------|-------|
| `official` | `official/security/1password` | Hermes 随附的可选 skills。 |
| `skills-sh` | `skills-sh/vercel-labs/agent-skills/vercel-react-best-practices` | 可通过 `hermes skills search <query> --source skills-sh` 搜索。当 skills.sh slug 与仓库文件夹不同时，Hermes 会解析别名式 skills。 |
| `well-known` | `well-known:https://mintlify.com/docs/.well-known/skills/mintlify` | 直接从网站的 `/.well-known/skills/index.json` 提供的 skills。使用站点或文档 URL 搜索。 |
| `url` | `https://sharethis.chat/SKILL.md` | 指向 `SKILL.md` 及其明确引用的支持文件的直接 HTTP(S) URL。名称解析顺序：frontmatter → URL slug → 交互式提示 → `--name` 标志。 |
| `github` | `openai/skills/k8s` | 直接从 GitHub 仓库/路径安装以及基于 GitHub 的自定义 tap。 |
| `clawhub`、`lobehub`、`browse-sh` | 来源特定标识符 | 社区或市场集成。 |

### 集成的 hub 和注册表

Hermes 目前与以下 skills 生态系统和发现来源集成：

#### 1. 官方可选 skills（`official`）

这些 skills 在 Hermes 仓库中维护，以内置信任级别安装。

- 目录：[官方可选 Skills 目录](../../reference/optional-skills-catalog)
- 仓库中的来源：`optional-skills/`
- 示例：

```bash
hermes skills browse --source official
hermes skills install official/security/1password
```

#### 2. skills.sh（`skills-sh`）

这是 Vercel 的公共 skills 目录。Hermes 可以直接搜索它、查看 skill 详情页、解析别名式 slug，并从底层源仓库安装。

- 目录：[skills.sh](https://skills.sh/)
- CLI/工具仓库：[vercel-labs/skills](https://github.com/vercel-labs/skills)
- Vercel 官方 skills 仓库：[vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)
- 示例：

```bash
hermes skills search react --source skills-sh
hermes skills inspect skills-sh/vercel-labs/json-render/json-render-react
hermes skills install skills-sh/vercel-labs/json-render/json-render-react --force
```

#### 3. Well-known skill 端点（`well-known`）

这是基于 URL 的发现机制，来自发布 `/.well-known/skills/index.json` 的站点。它不是单一的集中式 hub——它是一种 Web 发现约定。

- 示例实时端点：[Mintlify docs skills index](https://mintlify.com/docs/.well-known/skills/index.json)
- 参考服务器实现：[vercel-labs/skills-handler](https://github.com/vercel-labs/skills-handler)
- 示例：

```bash
hermes skills search https://mintlify.com/docs --source well-known
hermes skills inspect well-known:https://mintlify.com/docs/.well-known/skills/mintlify
hermes skills install well-known:https://mintlify.com/docs/.well-known/skills/mintlify
```

#### 4. 直接 GitHub skills（`github`）

Hermes 可以直接从 GitHub 仓库和基于 GitHub 的 tap 安装。当你已知仓库/路径或想添加自己的自定义源仓库时非常有用。

默认 tap（无需任何设置即可浏览）：
- [openai/skills](https://github.com/openai/skills)
- [anthropics/skills](https://github.com/anthropics/skills)
- [huggingface/skills](https://github.com/huggingface/skills)
- [NVIDIA/skills](https://github.com/NVIDIA/skills) — NVIDIA 官方验证的技能（带签名 `skill.oms.sig` 与治理用 `skill-card.md`）
- [garrytan/gstack](https://github.com/garrytan/gstack)

- 示例：

```bash
hermes skills install openai/skills/k8s
hermes skills tap add myorg/skills-repo
```

**分类分组（`skills.sh.json`）。** 一个 GitHub tap 可以在其仓库根目录提供一个遵循 [skills.sh schema](https://skills.sh/schemas/skills.sh.schema.json) 的 `skills.sh.json` 文件。其中的 `groupings`（每项含一个 `title` 和一组 skill 名称）会在建立索引时被读取，并成为 [Skills Hub](https://hermes-agent.nousresearch.com/docs) 页面上显示的分类标签——取代基于标签的推测。这是通用机制：任何提供该文件的 tap 都能获得真实的分类，无需改动 Hermes 侧的代码。

```json
{
  "$schema": "https://skills.sh/schemas/skills.sh.schema.json",
  "groupings": [
    { "title": "Inference AI", "skills": ["dynamo-recipe-runner", "dynamo-router-sla"] },
    { "title": "Decision Optimization", "skills": ["cuopt-developer", "cuopt-install"] }
  ]
}
```

#### 5. ClawHub（`clawhub`）

作为社区来源集成的第三方 skills 市场。

- 站点：[clawhub.ai](https://clawhub.ai/)
- Hermes 来源 id：`clawhub`

#### 6. LobeHub（`lobehub`）

Hermes 可以从 LobeHub 的公共目录中搜索并将 agent 条目转换为可安装的 Hermes skills。

- 站点：[LobeHub](https://lobehub.com/)
- 公共 agents 索引：[chat-agents.lobehub.com](https://chat-agents.lobehub.com/)
- 后端仓库：[lobehub/lobe-chat-agents](https://github.com/lobehub/lobe-chat-agents)
- Hermes 来源 id：`lobehub`

#### 7. browse.sh（`browse-sh`）

Hermes 与 [browse.sh](https://browse.sh) 集成，这是 Browserbase 的目录，包含 200+ 个针对特定站点的浏览器自动化 SKILL.md 文件（Airbnb、Amazon、arXiv、12306.cn、Etsy、Xero 等）。每个 skill 描述如何端到端驱动一个网站，适合与 Hermes 的浏览器工具以及你已安装的任何浏览器自动化 skills 配合使用。

- 站点：[browse.sh](https://browse.sh/)
- 目录 API：`https://browse.sh/api/skills`
- Hermes 来源 id：`browse-sh`
- 信任级别：`community`

```bash
hermes skills search airbnb --source browse-sh
hermes skills inspect browse-sh/airbnb.com/search-listings-ddgioa
hermes skills install browse-sh/airbnb.com/search-listings-ddgioa
```

标识符使用 `browse-sh/<hostname>/<task-id>` 的形式，与 browse.sh 目录公开的 slug 匹配。内容通过每个 skill 的详情端点（`/api/skills/<slug>` → `skillMdUrl`）解析，而不是通过目录的 GitHub `sourceUrl`。

#### 8. 直接 URL（`url`）

直接从任何 HTTP(S) URL 安装 `SKILL.md`——当作者在自己的站点上托管 skill 时非常有用（无 hub 列表，无需输入 GitHub 路径）。Hermes 还会获取其中明确引用且位于 `references/`、`templates/`、`scripts/`、`assets/` 和 `examples/` 下的文件，然后扫描并安装完整捆绑包。

- Hermes 来源 id：`url`
- 标识符：URL 本身（无需前缀）
- 范围：`SKILL.md` 加上允许目录中明确引用的支持文件。Hermes 不会枚举或复制托管站点上的其他文件。

```bash
hermes skills install https://sharethis.chat/SKILL.md
hermes skills install https://example.com/my-skill/SKILL.md --category productivity
```

名称解析顺序：
1. SKILL.md YAML frontmatter 中的 `name:` 字段（推荐——每个格式良好的 skill 都有）。
2. URL 路径中的父目录名称（例如 `.../my-skill/SKILL.md` → `my-skill`，或 `.../my-skill.md` → `my-skill`），当它是有效标识符（`^[a-z][a-z0-9_-]*$`）时。
3. 在有 TTY 的终端上的交互式提示。
4. 在非交互式界面（TUI 内的 `/skills install` 斜杠命令、gateway 平台、脚本）上，给出指向 `--name` 覆盖的清晰错误。

```bash
# Frontmatter 没有名称且 URL slug 无意义——手动提供：
hermes skills install https://example.com/SKILL.md --name sharethis-chat

# 或在聊天会话中：
/skills install https://example.com/SKILL.md --name sharethis-chat
```

信任级别始终为 `community`——与所有其他来源一样运行相同的安全扫描。URL 作为安装标识符存储，因此当你想刷新时，`hermes skills update` 会自动从同一 URL 重新获取。

### 安全扫描与 `--force`

所有通过 hub 安装的 skills 都经过**安全扫描器**检查，检测数据泄露、prompt 注入、破坏性命令、供应链信号及其他威胁。

`hermes skills inspect ...` 现在还会在可用时显示上游元数据：
- 仓库 URL
- skills.sh 详情页 URL
- 安装命令
- 每周安装量
- 上游安全审计状态
- well-known 索引/端点 URL

当你已审查第三方 skill 并希望覆盖非危险性策略阻止时，使用 `--force`：

```bash
hermes skills install skills-sh/anthropics/skills/pdf --force
```

重要行为：
- `--force` 可以覆盖谨慎/警告类发现的策略阻止。
- `--force` **不能**覆盖 `dangerous` 扫描结论。
- 官方可选 skills（`official/...`）被视为内置信任，不显示第三方警告面板。

### 信任级别

| 级别 | 来源 | 策略 |
|-------|--------|--------|
| `builtin` | 随 Hermes 附带 | 始终受信任 |
| `official` | 仓库中的 `optional-skills/` | 内置信任，无第三方警告 |
| `trusted` | 受信任的注册表/仓库，如 `openai/skills`、`anthropics/skills`、`huggingface/skills`、`NVIDIA/skills` | 比社区来源更宽松的策略 |
| `community` | 其他所有来源（`skills.sh`、well-known 端点、自定义 GitHub 仓库、大多数市场） | 非危险性发现可用 `--force` 覆盖；`dangerous` 结论保持阻止 |

### 更新生命周期

hub 现在跟踪足够的来源信息以重新检查已安装 skills 的上游副本：

```bash
hermes skills check          # Report which installed hub skills changed upstream
hermes skills update         # Reinstall only the skills with updates available
hermes skills update react   # Update one specific installed hub skill
hermes skills update react --force   # Overwrite a skill you've edited locally
```

这使用存储的来源标识符加上当前上游捆绑包内容哈希来检测漂移。

对于缺失或并非目录的安装（`orphaned`），以及不安全或无法解析的记录路径（`invalid_install`），检查会跳过网络请求。目录缺失的条目可以用 `hermes skills uninstall <name>` 移除；无效路径则需要先检查并修复当前 profile 的 `skills/.hub/lock.json`，然后再重试。不会自动移除任何条目。

有效的安装继续使用其来源适配器现有的同步获取和传输超时。更新检查没有严格的总截止时间：某个已有安装的来源若无法访问或速度缓慢，仍可能拖慢后续条目。

你在本地编辑过的 skill（磁盘上的内容与安装时记录的哈希不再匹配）会被 `hermes skills update` **跳过**，因此你的修改永远不会被静默覆盖。传入 `--force` 可无论如何用上游版本替换它们。

:::tip GitHub 速率限制
Skills hub 操作使用 GitHub API，未认证用户的速率限制为每小时 60 次请求。如果在安装或搜索时看到速率限制错误，请在 `.env` 文件中设置 `GITHUB_TOKEN` 以将限制提高到每小时 5,000 次请求。发生此情况时，错误消息会包含可操作的提示。
:::

### 发布自定义 skill tap {#publishing-a-custom-skill-tap}

如果你想分享一组精选的 skills——为你的团队、组织或公开分享——你可以将它们发布为 **tap**：其他 Hermes 用户通过 `hermes skills tap add <owner/repo>` 添加的 GitHub 仓库。无需服务器，无需注册表注册，无需发布流水线。只需一个包含 `SKILL.md` 文件的目录。

#### 仓库布局

tap 是任何 GitHub 仓库（公开或私有——私有仓库需要 `GITHUB_TOKEN`），布局如下：

```
owner/repo
├── skills/                       # default path; configurable per-tap
│   ├── my-workflow/
│   │   ├── SKILL.md              # required
│   │   ├── references/           # optional supporting files
│   │   ├── templates/
│   │   └── scripts/
│   ├── another-skill/
│   │   └── SKILL.md
│   └── third-skill/
│       └── SKILL.md
└── README.md                     # optional but helpful
```

规则：
- 每个 skill 存放在 tap 根路径（默认 `skills/`）下的独立目录中。
- 目录名成为 skill 的安装 slug。
- 每个 skill 目录必须包含一个带有标准 [SKILL.md frontmatter](#skillmd-format) 的 `SKILL.md`（`name`、`description`，以及可选的 `metadata.hermes.tags`、`version`、`author`、`platforms`、`metadata.hermes.config`）。
- `references/`、`templates/`、`scripts/`、`assets/` 等子目录在安装时与 `SKILL.md` 一起下载。
- 目录名以 `.` 或 `_` 开头的 skills 会被忽略。

Hermes 通过列出 tap 路径的每个子目录并探测每个目录中的 `SKILL.md` 来发现 skills。

#### 最小 tap 示例

```
my-org/hermes-skills
└── skills/
    └── deploy-runbook/
        └── SKILL.md
```

`skills/deploy-runbook/SKILL.md`：

```markdown
---
name: deploy-runbook
description: Our deployment runbook — services, rollback, Slack channels
version: 1.0.0
author: My Org Platform Team
metadata:
  hermes:
    tags: [deployment, runbook, internal]
---

# Deploy Runbook

Step 1: ...
```

将其推送到 GitHub 后，任何 Hermes 用户都可以订阅并安装：

```bash
hermes skills tap add my-org/hermes-skills
hermes skills search deploy
hermes skills install my-org/hermes-skills/deploy-runbook
```

#### 非默认路径

如果你的 skills 不在 `skills/` 下（当你向现有项目添加 `skills/` 子树时很常见），请编辑 `~/.hermes/skills/.hub/taps.json` 中的 tap 条目：

```json
{
  "taps": [
    {"repo": "my-org/platform-docs", "path": "internal/skills/"}
  ]
}
```

`hermes skills tap add` CLI 默认将新 tap 的 `path` 设为 `"skills/"`；如果需要不同路径，请直接编辑该文件。`hermes skills tap list` 显示每个 tap 的有效路径。

#### 直接安装单个 skills（无需添加 tap）

用户也可以从任何公开 GitHub 仓库安装单个 skill，而无需将整个仓库添加为 tap：

```bash
hermes skills install owner/repo/skills/my-workflow
```

当你想分享一个 skill 而不要求用户订阅你的整个注册表时非常有用。

#### tap 的信任级别

新 tap 默认分配 `community` 信任级别。从中安装的 skills 经过标准安全扫描，首次安装时显示第三方警告面板。如果你的组织或广泛受信任的来源应获得更高信任，请将其仓库添加到 `tools/skills_guard.py` 中的 `TRUSTED_REPOS`（需要 Hermes 核心 PR）。

#### Tap 管理

```bash
hermes skills tap list                                # show all configured taps
hermes skills tap add myorg/skills-repo               # add (default path: skills/)
hermes skills tap remove myorg/skills-repo            # remove
```

在运行中的会话内：

```
/skills tap list
/skills tap add myorg/skills-repo
/skills tap remove myorg/skills-repo
```

Tap 存储在 `~/.hermes/skills/.hub/taps.json` 中（按需创建）。

## 捆绑 skill 更新（`hermes skills reset`）

Hermes 在仓库的 `skills/` 中附带一组捆绑 skills。在安装时以及每次 `hermes update` 时，同步过程会将这些 skills 复制到 `~/.hermes/skills/` 中，并在 `~/.hermes/skills/.bundled_manifest` 记录一个清单，将每个 skill 名称映射到同步时的内容哈希（**origin hash**）。

每次同步时，Hermes 重新计算本地副本的哈希并与 origin hash 比较：

- **未更改** → 可以安全拉取上游变更，复制新的捆绑版本，记录新的 origin hash。
- **已更改** → 视为**用户修改**并永久跳过，因此你的编辑不会被覆盖。

skill 内部生成的运行时缓存（`__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`，以及紧挨着其 `.py` 的 `.pyc`）不计入哈希，因此运行某个 skill 的辅助脚本永远不会把它标记为用户修改，也不会让它从 `hermes skills list-modified` / `diff` 中消失。

这种保护机制很好，但有一个棘手的边缘情况。如果你编辑了一个捆绑 skill，后来想通过从 `~/.hermes/hermes-agent/skills/` 复制粘贴来放弃更改并回到捆绑版本，清单仍然保存着上次成功同步时的*旧* origin hash。你新复制粘贴的内容（当前捆绑哈希）与那个过时的 origin hash 不匹配，因此同步继续将其标记为用户修改。

`hermes skills reset` 是解决此问题的方法：

```bash
# 安全：清除此 skill 的清单条目。你当前的副本被保留，
# 但下次同步会重新以其为基准，使未来的更新正常工作。
hermes skills reset google-workspace

# 完全恢复：同时删除你的本地副本并重新复制当前捆绑版本。
# 当你想要恢复原始上游 skill 时使用此选项。
hermes skills reset google-workspace --restore

# 非交互式（例如在脚本或 TUI 模式中）——跳过 --restore 确认。
hermes skills reset google-workspace --restore --yes
```

同样的命令也可以作为斜杠命令在聊天中使用：

```text
/skills reset google-workspace
/skills reset google-workspace --restore
```

:::note Profiles
每个 profile 在其自己的 `HERMES_HOME` 下有自己的 `.bundled_manifest`，因此 `hermes -p coder skills reset <name>` 只影响该 profile。
:::

### 斜杠命令（在聊天中）

所有相同的命令都可以使用 `/skills` 执行：

```text
/skills browse
/skills search react --source skills-sh
/skills search https://mintlify.com/docs --source well-known
/skills inspect skills-sh/vercel-labs/json-render/json-render-react
/skills install openai/skills/skill-creator --force
/skills check
/skills update
/skills reset google-workspace
/skills list
```

官方可选 skills 仍使用 `official/security/1password` 和 `official/migration/openclaw-migration` 等标识符。