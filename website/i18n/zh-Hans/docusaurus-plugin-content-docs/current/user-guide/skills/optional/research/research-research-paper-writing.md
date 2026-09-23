---
title: "Research Paper Writing —— 为 NeurIPS/ICML/ICLR 撰写 ML 论文：从设计到投稿"
sidebar_label: "Research Paper Writing"
description: "为 NeurIPS/ICML/ICLR 撰写 ML 论文：从设计到投稿"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Research Paper Writing {#research-paper-writing}

为 NeurIPS/ICML/ICLR 撰写 ML 论文：从设计到投稿。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/research/research-paper-writing` 安装 |
| 路径 | `optional-skills/research/research-paper-writing` |
| 版本 | `1.1.0` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖 | `semanticscholar`, `arxiv`, `habanero`, `requests`, `scipy`, `numpy`, `matplotlib`, `SciencePlots` |
| 平台 | linux, macos |
| 标签 | `Research`, `Paper Writing`, `Experiments`, `ML`, `AI`, `NeurIPS`, `ICML`, `ICLR`, `ACL`, `AAAI`, `COLM`, `LaTeX`, `Citations`, `Statistical Analysis` |
| 相关 skill | [`arxiv`](/user-guide/skills/bundled/research/research-arxiv), [`subagent-driven-development`](/user-guide/skills/optional/software-development/software-development-subagent-driven-development) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Research Paper Writing Pipeline {#research-paper-writing-pipeline}

用于产出可发表的 ML/AI 研究论文的端到端流水线，目标会议为 **NeurIPS、ICML、ICLR、ACL、AAAI 和 COLM**。该 skill 覆盖完整的研究生命周期：实验设计、执行、监控、分析、论文撰写、评审、修改和投稿。

这**不是一条线性流水线** —— 它是一个迭代循环。结果会触发新的实验，评审会触发新的分析。agent 必须处理好这些反馈循环。

<!-- ascii-guard-ignore -->
<!-- ascii-guard-ignore -->
```
┌─────────────────────────────────────────────────────────────┐
│                    RESEARCH PAPER PIPELINE                  │
│                                                             │
│  Phase 0: Project Setup ──► Phase 1: Literature Review      │
│       │                          │                          │
│       ▼                          ▼                          │
│  Phase 2: Experiment     Phase 5: Paper Drafting ◄──┐      │
│       Design                     │                   │      │
│       │                          ▼                   │      │
│       ▼                    Phase 6: Self-Review      │      │
│  Phase 3: Execution &           & Revision ──────────┘      │
│       Monitoring                 │                          │
│       │                          ▼                          │
│       ▼                    Phase 7: Submission               │
│  Phase 4: Analysis ─────► (feeds back to Phase 2 or 5)     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
<!-- ascii-guard-ignore-end -->
<!-- ascii-guard-ignore-end -->

---

## 何时使用此 Skill {#when-to-use-this-skill}

在以下情况使用此 skill：
- **开始一篇新的研究论文**，基于现有代码库或想法
- **设计并运行实验**，以支撑论文中的论点
- **撰写或修改**研究论文的任何章节
- **准备投稿**到特定会议或 workshop
- **回应评审意见**，补充实验或进行修改
- **转换**论文的会议格式
- **撰写非实证类论文** —— 理论、综述、基准或立场论文（参见 [Paper Types Beyond Empirical ML](#paper-types-beyond-empirical-ml)）
- **设计人工评估**，用于 NLP、HCI 或对齐研究
- **准备录用后的交付物** —— 海报、报告、代码发布

## 核心理念 {#core-philosophy}

1. **主动出击。** 交付完整的草稿，而不是问题。科学家们很忙 —— 产出他们可以直接回应的具体内容，然后迭代。
2. **绝不捏造引用。** AI 生成的引用约有 40% 的错误率。始终以编程方式获取。将无法验证的引用标记为 `[CITATION NEEDED]`。
3. **论文是一个故事，而不是实验的堆砌。** 每篇论文都需要一个能用一句话陈述的清晰贡献。如果做不到，说明论文还没准备好。
4. **实验服务于论点。** 每个实验都必须明确说明它支撑哪个论点。绝不运行与论文叙事无关的实验。
5. **尽早提交，频繁提交。** 每完成一批实验、每次更新论文草稿 —— 都用描述性信息提交。Git 日志就是实验历史。

### 主动性与协作 {#proactivity-and-collaboration}

**默认：主动出击。先写草稿，再带着草稿提问。**

| 置信度 | 行动 |
|-----------------|--------|
| **高**（仓库清晰，贡献明显） | 撰写完整草稿，交付，根据反馈迭代 |
| **中**（存在一些歧义） | 撰写草稿并标注不确定之处，继续推进 |
| **低**（存在重大未知） | 通过 `clarify` 提出 1-2 个针对性问题，然后撰写草稿 |

| 章节 | 自主撰写？ | 随草稿标注 |
|---------|-------------------|-----------------|
| 摘要 | 是 | "将贡献表述为 X —— 如有需要请调整" |
| 引言 | 是 | "强调了问题 Y —— 如有错误请纠正" |
| 方法 | 是 | "包含了细节 A、B、C —— 请补充缺失部分" |
| 实验 | 是 | "突出了结果 1、2、3 —— 如有需要请调整顺序" |
| 相关工作 | 是 | "引用了论文 X、Y、Z —— 请补充我遗漏的" |

**仅在以下情况下暂停等待输入**：目标会议不明确、存在多种相互矛盾的表述框架、结果似乎不完整、明确要求先评审。

---

## 阶段 0：项目设置 {#phase-0-project-setup}

**目标**：建立工作区，理解已有工作，确定贡献。

### 步骤 0.1：探索仓库 {#step-01-explore-the-repository}

```bash
# Understand project structure
ls -la
find . -name "*.py" | head -30
find . -name "*.md" -o -name "*.txt" | xargs grep -l -i "result\|conclusion\|finding"
```

需要查找：
- `README.md` —— 项目概述和论点
- `results/`、`outputs/`、`experiments/` —— 已有发现
- `configs/` —— 实验设置
- `.bib` 文件 —— 已有引用
- 草稿文档或笔记

### 步骤 0.2：组织工作区 {#step-02-organize-the-workspace}

建立一致的工作区结构：

```
workspace/
  paper/               # LaTeX source, figures, compiled PDFs
  experiments/         # Experiment runner scripts
  code/                # Core method implementation
  results/             # Raw experiment results (auto-generated)
  tasks/               # Task/benchmark definitions
  human_eval/          # Human evaluation materials (if needed)
```

### 步骤 0.3：设置版本控制 {#step-03-set-up-version-control}

```bash
git init  # if not already
git remote add origin <repo-url>
git checkout -b paper-draft  # or main
```

**Git 纪律**：每完成一批实验，都要用描述性信息提交。示例：
```
Add Monte Carlo constrained results (5 runs, Sonnet 4.6, policy memo task)
Add Haiku baseline comparison: autoreason vs refinement baselines at cheap model tier
```

### 步骤 0.4：确定贡献 {#step-04-identify-the-contribution}

在动笔之前，先阐明：
- **是什么（The What）**：这篇论文贡献的唯一一件事是什么？
- **为什么（The Why）**：有什么证据支持它？
- **那又怎样（The So What）**：读者为什么应该关心？

> 向科学家提议："根据我的理解，主要贡献是：[一句话]。关键结果表明 [Y]。这是你想要的表述框架吗？"

### 步骤 0.5：创建 TODO 列表 {#step-05-create-a-todo-list}

使用 `todo` 工具创建结构化的项目计划：

```
Research Paper TODO:
- [ ] Define one-sentence contribution
- [ ] Literature review (related work + baselines)
- [ ] Design core experiments
- [ ] Run experiments
- [ ] Analyze results
- [ ] Write first draft
- [ ] Self-review (simulate reviewers)
- [ ] Revise based on review
- [ ] Submission prep
```

在整个项目过程中持续更新它。它充当跨会话的持久状态。

### 步骤 0.6：估算计算预算 {#step-06-estimate-compute-budget}

在运行实验之前，估算总成本和时间：

```
Compute Budget Checklist:
- [ ] API costs: (model price per token) × (estimated tokens per run) × (number of runs)
- [ ] GPU hours: (time per experiment) × (number of experiments) × (number of seeds)
- [ ] Human evaluation costs: (annotators) × (hours) × (hourly rate)
- [ ] Total budget ceiling and contingency (add 30-50% for reruns)
```

在实验运行时跟踪实际花费：
```python
# Simple cost tracker pattern
import json, os
from datetime import datetime

COST_LOG = "results/cost_log.jsonl"

def log_cost(experiment: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "experiment": experiment,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }
    with open(COST_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
```

**预算紧张时**：在投入完整扫描之前，先运行试点实验（1-2 个随机种子、任务子集）。用更便宜的模型调试流水线，然后在最终运行时切换到目标模型。

### 步骤 0.7：多作者协调 {#step-07-multi-author-coordination}

大多数论文有 3-10 位作者。尽早建立工作流程：

| 工作流程 | 工具 | 适用场景 |
|----------|------|-------------|
| **Overleaf** | 基于浏览器 | 多位作者同时编辑，没有 git 经验 |
| **Git + LaTeX** | `git` 搭配忽略辅助文件的 `.gitignore` | 技术团队，需要基于分支的评审 |
| **Overleaf + Git 同步** | Overleaf 高级版 | 两者兼得 —— 实时协作并保留版本历史 |

**章节归属**：将每个章节分配给一位主要作者。其他人可以评论，但不直接编辑。这可以避免合并冲突和风格不一致。

```
Author Coordination Checklist:
- [ ] Agree on section ownership (who writes what)
- [ ] Set up shared workspace (Overleaf or git repo)
- [ ] Establish notation conventions (before anyone writes)
- [ ] Schedule internal review rounds (not just at the end)
- [ ] Designate one person for final formatting pass
- [ ] Agree on figure style (colors, fonts, sizes) before creating figures
```

**需要尽早约定的 LaTeX 规范**：
- 用 `\method{}` 宏统一方法命名
- 引用风格：`\citet{}` 与 `\citep{}` 的用法
- 数学记号：向量用小写粗体，矩阵用大写粗体，等等
- 英式与美式拼写

---

## 阶段 1：文献综述 {#phase-1-literature-review}

**目标**：找到相关工作，确定基线，收集引用。

### 步骤 1.1：确定种子论文 {#step-11-identify-seed-papers}

从代码库中已引用的论文开始：

```bash
# Via terminal:
grep -r "arxiv\|doi\|cite" --include="*.md" --include="*.bib" --include="*.py"
find . -name "*.bib"
```

### 步骤 1.2：搜索相关工作 {#step-12-search-for-related-work}

**加载 `arxiv` skill** 以进行结构化的论文发现：`skill_view("arxiv")`。它提供 arXiv REST API 搜索、Semantic Scholar 引用图谱、作者档案以及 BibTeX 生成。

使用 `web_search` 进行广泛发现，使用 `web_extract` 获取特定论文：

```
# Via web_search:
web_search("[main technique] + [application domain] site:arxiv.org")
web_search("[baseline method] comparison ICML NeurIPS 2024")

# Via web_extract (for specific papers):
web_extract("https://arxiv.org/abs/2303.17651")
```

可以尝试的其他搜索查询：

```
Search queries:
- "[main technique] + [application domain]"
- "[baseline method] comparison"
- "[problem name] state-of-the-art"
- Author names from existing citations
```

**推荐**：安装 **Exa MCP** 以进行实时学术搜索：
```bash
claude mcp add exa -- npx -y mcp-remote "https://mcp.exa.ai/mcp"
```

### 步骤 1.2b：深化搜索（先广度，后深度） {#step-12b-deepen-the-search-breadth-first-then-depth}

扁平搜索（只进行一轮查询）通常会遗漏重要的相关工作。采用受深度研究流水线启发的迭代式**先广度后深度**模式：

```
Iterative Literature Search:

Round 1 (Breadth): 4-6 parallel queries covering different angles
  - "[method] + [domain]"
  - "[problem name] state-of-the-art 2024 2025"
  - "[baseline method] comparison"
  - "[alternative approach] vs [your approach]"
  → Collect papers, extract key concepts and terminology

Round 2 (Depth): Generate follow-up queries from Round 1 learnings
  - New terminology discovered in Round 1 papers
  - Papers cited by the most relevant Round 1 results
  - Contradictory findings that need investigation
  → Collect papers, identify remaining gaps

Round 3 (Targeted): Fill specific gaps
  - Missing baselines identified in Rounds 1-2
  - Concurrent work (last 6 months, same problem)
  - Key negative results or failed approaches
  → Stop when new queries return mostly papers you've already seen
```

**何时停止**：如果某一轮返回的论文中有 >80% 已在你的收集中，说明搜索已饱和。通常 2-3 轮就足够了。对于综述论文，预计需要 4-5 轮。

**对于基于 agent 的工作流程**：通过 `delegate_task` 并行委派每一轮的查询。收集结果、去重，然后根据汇总的收获生成下一轮的查询。

### 步骤 1.3：验证每一条引用 {#step-13-verify-every-citation}

**绝不凭记忆生成 BibTeX。始终以编程方式获取。**

对于每条引用，遵循强制性的 5 步流程：

```
Citation Verification (MANDATORY per citation):
1. SEARCH → Query Semantic Scholar or Exa MCP with specific keywords
2. VERIFY → Confirm paper exists in 2+ sources (Semantic Scholar + arXiv/CrossRef)
3. RETRIEVE → Get BibTeX via DOI content negotiation (programmatically, not from memory)
4. VALIDATE → Confirm the claim you're citing actually appears in the paper
5. ADD → Add verified BibTeX to bibliography
If ANY step fails → mark as [CITATION NEEDED], inform scientist
```

```python
# Fetch BibTeX via DOI
import requests

def doi_to_bibtex(doi: str) -> str:
    response = requests.get(
        f"https://doi.org/{doi}",
        headers={"Accept": "application/x-bibtex"}
    )
    response.raise_for_status()
    return response.text
```

如果无法验证某条引用：

```latex
\cite{PLACEHOLDER_author2024_verify_this}  % TODO: Verify this citation exists
```

**始终告知科学家**："我已将 [X] 条引用标记为需要验证的占位符。"

完整的 API 文档以及完整的 `CitationManager` 类请参见 [references/citation-workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/citation-workflow.md)。

### 步骤 1.4：组织相关工作 {#step-14-organize-related-work}

按方法论对论文分组，而不是逐篇罗列：

**好**："一类工作采用 X 的假设 [refs]，而我们采用 Y 的假设，因为……"
**差**："Smith 等人提出了 X。Jones 等人提出了 Y。我们将两者结合。"

---

## 阶段 2：实验设计 {#phase-2-experiment-design}

**目标**：设计能直接支撑论文论点的实验。每个实验都必须回答一个具体问题。

### 步骤 2.1：将论点映射到实验 {#step-21-map-claims-to-experiments}

建立明确的映射：

| 论点 | 实验 | 预期证据 |
|-------|-----------|-------------------|
| "我们的方法优于基线" | 主要对比（表 1） | 胜率、统计显著性 |
| "对较弱模型的效果更大" | 模型规模研究 | 单调提升曲线 |
| "收敛需要范围约束" | 有约束 vs 无约束 | 收敛速度对比 |

**规则**：如果某个实验无法映射到某个论点，就不要运行它。

### 步骤 2.2：设计基线 {#step-22-design-baselines}

强基线是区分被录用论文与被拒论文的关键。评审会问："他们和 X 比较过吗？"

标准基线类别：
- **朴素基线**：最简单的可行方法
- **强基线**：已知最好的现有方法
- **消融基线**：你的方法去掉某一个组件
- **计算量匹配基线**：相同计算预算，不同分配方式

### 步骤 2.3：定义评估协议 {#step-23-define-evaluation-protocol}

在运行任何东西之前，明确说明：
- **指标**：你在衡量什么，方向符号（越高/越低越好）
- **聚合**：结果如何在多次运行/任务之间合并
- **统计检验**：用哪些检验来确立显著性
- **样本量**：多少次运行/多少个问题/多少个任务

### 步骤 2.4：编写实验脚本 {#step-24-write-experiment-scripts}

遵循以下来自成功研究流水线的模式：

**增量保存** —— 每一步之后保存结果，以便从崩溃中恢复：
```python
# Save after each problem/task
result_path = f"results/{task}/{strategy}/result.json"
if os.path.exists(result_path):
    continue  # Skip already-completed work
# ... run experiment ...
with open(result_path, 'w') as f:
    json.dump(result, f, indent=2)
```

**产物保留** —— 保存所有中间输出：
```
results/<experiment>/
  <task>/
    <strategy>/
      final_output.md          # Final result
      history.json             # Full trajectory
      pass_01/                 # Per-iteration artifacts
        version_a.md
        version_b.md
        critic.md
```

**关注点分离** —— 将生成、评估和可视化分开：
```
run_experiment.py              # Core experiment runner
run_baselines.py               # Baseline comparison
run_comparison_judge.py        # Blind evaluation
analyze_results.py             # Statistical analysis
make_charts.py                 # Visualization
```

完整的设计模式、cron 监控和错误恢复请参见 [references/experiment-patterns.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/experiment-patterns.md)。

### 步骤 2.5：设计人工评估（如适用） {#step-25-design-human-evaluation-if-applicable}

许多 NLP、HCI 和对齐论文需要将人工评估作为主要或补充证据。请在运行自动化实验之前设计好它 —— 人工评估的准备周期通常更长（IRB 审批、标注员招募）。

**何时需要人工评估：**
- 自动化指标无法捕捉你所关心的内容（流畅度、有用性、安全性）
- 你的贡献涉及面向人的特性（可读性、偏好、信任）
- NLP 会议（ACL、EMNLP）的评审对生成任务有此期望

**关键设计决策：**

| 决策 | 选项 | 指导 |
|----------|---------|----------|
| **标注员类型** | 专家、众包工作者、终端用户 | 与你的论点所需相匹配 |
| **量表** | Likert（1-5）、成对比较、排序 | 对于 LLM 输出，成对比较比 Likert 更可靠 |
| **样本量** | 每位标注员的条目数及总条目数 | 功效分析，或至少 100 个条目、3 位以上标注员 |
| **一致性指标** | Cohen's kappa、Krippendorff's alpha、ICC | 超过 2 位标注员时用 Krippendorff's alpha；同时报告原始一致率 |
| **平台** | Prolific、MTurk、内部团队 | 追求质量用 Prolific；追求规模用 MTurk；需要领域专长用内部团队 |

**标注指南检查清单：**
```
- [ ] Clear task description with examples (good AND bad)
- [ ] Decision criteria for ambiguous cases
- [ ] At least 2 worked examples per category
- [ ] Attention checks / gold standard items (10-15% of total)
- [ ] Qualification task or screening round
- [ ] Estimated time per item and fair compensation (>= local minimum wage)
- [ ] IRB/ethics review if required by your institution
```

**报告要求**（评审会逐项检查）：
- 标注员人数及其资质
- 标注员间一致性，给出具体指标和数值
- 报酬细节（金额、估算时薪）
- 标注界面描述或截图（附录）
- 总标注时间

完整指南（包括针对人工评估数据的统计检验、众包质量控制模式和 IRB 指导）请参见 [references/human-evaluation.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/human-evaluation.md)。

---

## 阶段 3：实验执行与监控 {#phase-3-experiment-execution--monitoring}

**目标**：可靠地运行实验，监控进度，从故障中恢复。

### 步骤 3.1：启动实验 {#step-31-launch-experiments}

对长时间运行的实验使用 `nohup`：

```bash
nohup python run_experiment.py --config config.yaml > logs/experiment_01.log 2>&1 &
echo $!  # Record the PID
```

**并行执行**：同时运行相互独立的实验，但要注意 API 速率限制。在同一个 API 上并发运行 4 个以上实验会拖慢每一个实验。

### 步骤 3.2：设置监控（Cron 模式） {#step-32-set-up-monitoring-cron-pattern}

对于长时间运行的实验，设置周期性的状态检查。cron prompt 应遵循以下模板：

```
Monitor Prompt Template:
1. Check if process is still running: ps aux | grep <pattern>
2. Read last 30 lines of log: tail -30 <logfile>
3. Check for completed results: ls <result_dir>
4. If results exist, read and report: cat <result_file>
5. If all done, commit: git add -A && git commit -m "<descriptive message>" && git push
6. Report in structured format (tables with key metrics)
7. Answer the key analytical question for this experiment
```

**静默模式**：如果自上次检查以来没有任何变化，回复 `[SILENT]` 以抑制对用户的通知。只在有新消息时才报告。

### 步骤 3.3：处理故障 {#step-33-handle-failures}

常见故障模式及恢复方法：

| 故障 | 检测 | 恢复 |
|---------|-----------|----------|
| API 速率限制 / 额度耗尽 | 日志中出现 402/429 错误 | 等待，然后重新运行（脚本会跳过已完成的工作） |
| 进程崩溃 | PID 消失，结果不完整 | 从最后一个检查点重新运行 |
| 难题超时 | 进程卡住，日志无进展 | 终止并跳过，在结果中注明 |
| 模型 ID 错误 | 错误信息引用了模型名称 | 修正 ID 并重新运行 |

**关键**：脚本应始终检查已有结果并跳过已完成的工作。这使得重新运行既安全又高效。

### 步骤 3.4：提交已完成的结果 {#step-34-commit-completed-results}

每批实验完成后：

```bash
git add -A
git commit -m "Add <experiment name>: <key finding in 1 line>"
git push
```

### 步骤 3.5：维护实验日志 {#step-35-maintain-an-experiment-journal}

Git 提交记录了发生了什么，但没有记录**探索树** —— 即根据所学决定下一步尝试什么的那些决策。维护一份结构化的实验日志来捕捉这棵树：

```json
// experiment_journal.jsonl — append one entry per experiment attempt
{
  "id": "exp_003",
  "parent": "exp_001",
  "timestamp": "2025-05-10T14:30:00Z",
  "hypothesis": "Adding scope constraints will fix convergence failure from exp_001",
  "plan": "Re-run autoreason with max_tokens=2000 and fixed structure template",
  "config": {"model": "haiku", "strategy": "autoreason", "max_tokens": 2000},
  "status": "completed",
  "result_path": "results/exp_003/",
  "key_metrics": {"win_rate": 0.85, "convergence_rounds": 3},
  "analysis": "Scope constraints fixed convergence. Win rate jumped from 0.42 to 0.85.",
  "next_steps": ["Try same constraints on Sonnet", "Test without structure template"],
  "figures": ["figures/exp003_convergence.pdf"]
}
```

**为什么要用日志，而不只是 git？** Git 跟踪文件变更，而日志跟踪推理过程：你为什么尝试 X、学到了什么、这对下一个实验意味着什么。撰写论文时，这棵树对方法章节（"我们观察到 X，这促使我们采用 Y"）以及如实报告失败都极为宝贵。

**选择最佳路径**：当日志呈现出分支树（exp_001 → exp_002a、exp_002b、exp_003）时，找出最能支撑论文论点的那条路径。将走不通的分支作为消融实验或负面结果记录在附录中。

**为每个实验快照代码**：每次运行后复制实验脚本：
```bash
cp experiment.py results/exp_003/experiment_snapshot.py
```
这样即使后续代码发生变更，也能精确复现。

---

## 阶段 4：结果分析 {#phase-4-result-analysis}

**目标**：提取发现、计算统计量、确定论文的叙事主线。

### 步骤 4.1：汇总结果 {#step-41-aggregate-results}

编写分析脚本，完成以下工作：
1. 加载一个批次中的所有结果文件
2. 计算每个任务的指标及汇总指标
3. 生成汇总表格

```python
# Standard analysis pattern
import json, os
from pathlib import Path

results = {}
for result_file in Path("results/").rglob("result.json"):
    data = json.loads(result_file.read_text())
    strategy = result_file.parent.name
    task = result_file.parent.parent.name
    results.setdefault(strategy, {})[task] = data

# Compute aggregate metrics
for strategy, tasks in results.items():
    scores = [t["score"] for t in tasks.values()]
    print(f"{strategy}: mean={np.mean(scores):.1f}, std={np.std(scores):.1f}")
```

### 步骤 4.2：统计显著性 {#step-42-statistical-significance}

务必计算：
- **误差棒**：标准差或标准误，并注明使用的是哪一种
- **置信区间**：关键结果给出 95% CI
- **成对检验**：比较两种方法时使用 McNemar 检验
- **效应量**：用 Cohen's d 或 h 衡量实际显著性

McNemar 检验、bootstrap 置信区间和 Cohen's h 的完整实现见 [references/experiment-patterns.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/experiment-patterns.md)。

### 步骤 4.3：确定叙事主线 {#step-43-identify-the-story}

分析完成后，明确回答以下问题：
1. **主要发现是什么？** 用一句话表述。
2. **什么让你感到意外？** 出乎意料的结果往往能成就最好的论文。
3. **什么失败了？** 失败的实验可能最有信息量。如实报告失败会让论文更有说服力。
4. **还需要哪些后续实验？** 结果常常会引出新的问题。

#### 处理负面结果或零结果 {#handling-negative-or-null-results}

当你的假设是错的或结果不确定时，你有三种选择：

| 情况 | 行动 | 适合的会议/期刊 |
|-----------|--------|-----------|
| 假设错误，但**原因**很有启发性 | 围绕"为什么"的分析来组织论文 | NeurIPS、ICML（如果分析足够严谨） |
| 方法未能超越基线，但**揭示了新东西** | 将贡献重新定位为理解/分析 | ICLR（重视理解类工作）、workshop 论文 |
| 针对流行观点的干净负面结果 | 写成论文——领域需要知道这一点 | NeurIPS Datasets & Benchmarks、TMLR、workshop |
| 结果不确定，没有清晰的叙事 | 转向——做不同的实验或重新定位 | 不要硬凑一篇并不存在的论文 |

**如何撰写负面结果论文：**
- 开篇说明社区普遍相信什么，以及为什么值得检验它
- 描述你严谨的方法论（必须无懈可击——审稿人会更严格地审视）
- 用统计证据清晰呈现零结果
- 分析预期结果**为什么**没有出现
- 讨论对该领域的启示

**明确欢迎负面结果的会议/期刊**：NeurIPS（Datasets & Benchmarks track）、TMLR、ML Reproducibility Challenge、各大会议的 workshop。有些 workshop 专门征集负面结果。

### 步骤 4.4：制作图表 {#step-44-create-figures-and-tables}

**图**：
- 所有图均使用矢量格式（PDF）：`plt.savefig('fig.pdf')`
- 使用色盲友好的配色（Okabe-Ito 或 Paul Tol）
- 图注自成一体——读者无需正文即可理解
- 图内不加标题——图注承担这一功能

**表**：
- 使用 `booktabs` LaTeX 宏包
- 每个指标的最佳值加粗
- 标注方向符号（越高/越低越好）
- 小数精度保持一致

```latex
\usepackage{booktabs}
\begin{tabular}{lcc}
\toprule
Method & Accuracy $\uparrow$ & Latency $\downarrow$ \\
\midrule
Baseline & 85.2 & 45ms \\
\textbf{Ours} & \textbf{92.1} & 38ms \\
\bottomrule
\end{tabular}
```

### 步骤 4.5：决策：继续实验还是开始写作？ {#step-45-decide-more-experiments-or-write}

| 情况 | 行动 |
|-----------|--------|
| 核心论点得到支持，结果显著 | 进入阶段 5（写作） |
| 结果不确定，需要更多数据 | 回到阶段 2（设计） |
| 意外发现指向新方向 | 回到阶段 2（设计） |
| 缺少一个审稿人必然会要求的消融实验 | 先跑完它，再进入阶段 5 |
| 所有实验已完成但部分失败 | 记录失败，进入阶段 5 |

### 步骤 4.6：撰写实验日志（通往写作的桥梁） {#step-46-write-the-experiment-log-bridge-to-writeup}

在转入论文写作之前，创建一份结构化的实验日志，把结果与正文连接起来。这是实验与写作之间最重要的衔接环节——没有它，负责写作的 agent 只能从原始结果文件中重新推导叙事主线。

**创建 `experiment_log.md`**，结构如下：

```markdown
# Experiment Log

## Contribution (one sentence)
[The paper's main claim]

## Experiments Run

### Experiment 1: [Name]
- **Claim tested**: [Which paper claim this supports]
- **Setup**: [Model, dataset, config, number of runs]
- **Key result**: [One sentence with the number]
- **Result files**: results/exp1/final_info.json
- **Figures generated**: figures/exp1_comparison.pdf
- **Surprising findings**: [Anything unexpected]

### Experiment 2: [Name]
...

## Figures
| Filename | Description | Which section it belongs in |
|----------|-------------|---------------------------|
| figures/main_comparison.pdf | Bar chart comparing all methods on benchmark X | Results, Figure 2 |
| figures/ablation.pdf | Ablation removing components A, B, C | Results, Figure 3 |
...

## Failed Experiments (document for honesty)
- [What was tried, why it failed, what it tells us]

## Open Questions
- [Anything the results raised that the paper should address]
```

**为什么这很重要**：起草时，agent（或被委派的子 agent）可以将 `experiment_log.md` 与 LaTeX 模板一起加载，产出基于真实结果的初稿。没有这座桥梁，负责写作的 agent 就必须解析原始 JSON/CSV 文件并自行推断叙事——这正是数字被幻觉编造或误报的常见根源。

**Git 规范**：将此日志与其描述的结果一起提交。

---

## 迭代改进：策略选择 {#iterative-refinement-strategy-selection}

此流水线中的任何产出——论文草稿、实验脚本、分析——都可以迭代改进。autoreason 研究为每种改进策略何时有效、何时失效提供了实证依据。请用本节来选择合适的方法。

### 快速决策表 {#quick-decision-table}

| 你的情况 | 策略 | 原因 |
|---------------|----------|-----|
| 中等水平模型 + 受约束任务 | **Autoreason** | 最佳适用区。生成-评估差距最大。基线方法会主动破坏弱模型的输出。 |
| 中等水平模型 + 开放任务 | **Autoreason**，并加上范围约束 | 加入固定事实、结构或交付物来限定改进空间。 |
| 前沿模型 + 受约束任务 | **Autoreason** | 即使在前沿模型上，也在 2/3 的受约束任务中胜出。 |
| 前沿模型 + 无约束任务 | **Critique-and-revise** 或 **single pass** | Autoreason 排名垫底。模型的自我评估已经足够好。 |
| 具体技术任务（系统设计） | **Critique-and-revise** | 直接的发现-修复循环更高效。 |
| 模板填充任务（只有一种正确结构） | **Single pass** 或 **conservative** | 决策空间极小。迭代没有增益。 |
| 带测试用例的代码 | **Autoreason（代码变体）** | 修复前先结构化分析*为什么*失败。恢复率 62% 对比 43%。 |
| 非常弱的模型（Llama 8B 级别） | **Single pass** | 模型太弱，无法生成多样化的候选。应投入于生成质量。 |

### 生成-评估差距 {#the-generation-evaluation-gap}

**核心洞见**：Autoreason 的价值取决于模型生成能力与自我评估能力之间的差距。

<!-- ascii-guard-ignore -->
```
Model Tier        │ Generation │ Self-Eval │ Gap    │ Autoreason Value
──────────────────┼────────────┼───────────┼────────┼─────────────────
Weak (Llama 8B)   │ Poor       │ Poor      │ Small  │ None — can't generate diverse candidates
Mid (Haiku 3.5)   │ Decent     │ Poor      │ LARGE  │ MAXIMUM — 42/42 perfect Borda
Mid (Gemini Flash)│ Decent     │ Moderate  │ Large  │ High — wins 2/3
Strong (Sonnet 4) │ Good       │ Decent    │ Medium │ Moderate — wins 3/5
Frontier (S4.6)   │ Excellent  │ Good      │ Small  │ Only with constraints
```
<!-- ascii-guard-ignore-end -->

这一差距是结构性的，而非暂时的。随着成本下降，今天的前沿模型会成为明天的中等水平模型。最佳适用区会移动，但永远不会消失。

### Autoreason 循环（摘要） {#autoreason-loop-summary}

每一轮由全新的、相互隔离的 agent 产出三个候选：

1. **Critic** → 找出现任版本 A 的问题（不做修复）
2. **Author B** → 根据批评修订 A
3. **Synthesizer** → 合并 A 和 B（标签随机化）
4. **Judge Panel** → 3 个盲评的 CoT 评审通过 Borda 计数对 A、B、AB 排序
5. **Convergence** → A 连续赢得 k=2 轮 → 结束

**关键参数：**
- k=2 收敛（k=1 过早，k=3 成本太高且无质量提升）
- 始终使用 CoT 评审（收敛速度快 3 倍）
- 作者温度 0.8，评审温度 0.3
- 保守的平局处理：平局时现任版本胜出
- 每个角色都是全新的 agent，不共享上下文

### 应用于论文草稿 {#applying-to-paper-drafts}

通过 autoreason 改进论文本身时：
- **向 critic 提供真实依据**：实际实验数据、结果 JSON、统计输出。否则模型会幻觉编造出虚假的消融研究和伪造的置信区间。
- **至少使用 3 个正常工作的评审**：一个坏掉的评审解析器不只是增加噪声——它会彻底阻止达到均衡。
- **限定修订范围**：要说"解决这些具体弱点"，而不是"改进这篇论文"。

### 失败模式 {#failure-modes}

| 失败 | 检测 | 修复 |
|---------|-----------|-----|
| 不收敛（A 从未胜出） | 20+ 轮中 A 胜率 &lt;15% | 为任务添加范围约束 |
| 合成漂移 | 字数无限增长 | 约束结构和交付物 |
| 退化到低于 single pass | 基线得分高于迭代后的输出 | 切换为 single pass；模型可能太弱 |
| 过拟合（代码） | 公开测试通过率高，私有测试通过率低 | 使用结构化分析，而不仅仅依赖测试反馈 |
| 评审失效 | 解析失败使评审小组不足 3 人 | 继续之前先修复解析器 |

完整的 prompt、Borda 计分细节、模型选择指南、范围约束设计模式以及计算预算参考，见 [references/autoreason-methodology.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/autoreason-methodology.md)。

---

## 阶段 5：论文起草 {#phase-5-paper-drafting}

完整的起草流程（逐节顺序、LaTeX 脚手架、图/表
约定、摘要与引言的写作公式、相关工作的定位）位于
`references/phase5-paper-drafting.md`——到达此阶段时用 `read_file` 加载它。
并搭配 `references/writing-guide.md` 获取行文层面的风格规则。

## 阶段 6：自我审阅与修订 {#phase-6-self-review--revision}

**目标**：在投稿前模拟审稿过程。尽早发现弱点。

### 步骤 6.1：模拟审稿（集成模式） {#step-61-simulate-reviews-ensemble-pattern}

从多个视角生成审稿意见。自动化研究流水线（尤其是 SakanaAI 的 AI-Scientist）的关键洞见是：**由 meta-reviewer 汇总的集成审稿，比单次审稿产出的反馈校准得多。**

**第 1 步：生成 N 份独立的审稿意见**（N=3-5）

使用不同的模型或温度设置。每位审稿人只看到论文，看不到其他审稿意见。**默认采用负面偏向**——LLM 在评估中存在有据可查的正面偏向。

```
You are an expert reviewer for [VENUE]. You are critical and thorough.
If a paper has weaknesses or you are unsure about a claim, flag it clearly
and reflect that in your scores. Do not give the benefit of the doubt.

Review this paper according to the official reviewer guidelines. Evaluate:

1. Soundness (are claims well-supported? are baselines fair and strong?)
2. Clarity (is the paper well-written? could an expert reproduce it?)
3. Significance (does this matter to the community?)
4. Originality (new insights, not just incremental combination?)

Provide your review as structured JSON:
{
  "summary": "2-3 sentence summary",
  "strengths": ["strength 1", "strength 2", ...],
  "weaknesses": ["weakness 1 (most critical)", "weakness 2", ...],
  "questions": ["question for authors 1", ...],
  "missing_references": ["paper that should be cited", ...],
  "soundness": 1-4,
  "presentation": 1-4,
  "contribution": 1-4,
  "overall": 1-10,
  "confidence": 1-5
}
```

**第 2 步：元审稿（Area Chair 汇总）**

将全部 N 份审稿意见交给一个 meta-reviewer：

```
You are an Area Chair at [VENUE]. You have received [N] independent reviews
of a paper. Your job is to:

1. Identify consensus strengths and weaknesses across reviewers
2. Resolve disagreements by examining the paper directly
3. Produce a meta-review that represents the aggregate judgment
4. Use AVERAGED numerical scores across all reviews

Be conservative: if reviewers disagree on whether a weakness is serious,
treat it as serious until the authors address it.

Reviews:
[review_1]
[review_2]
...
```

**第 3 步：反思循环**（可选，2-3 轮）

每位审稿人在看到元审稿意见后可以修订自己的审稿意见。使用提前终止标记：如果审稿人回复"I am done"（没有改动），就停止迭代。

**审稿所用模型的选择**：审稿最好使用可用的最强模型，即使你用更便宜的模型写了论文。审稿模型应独立于写作模型来选择。

**Few-shot 校准**：如果可以获取，加入 1-2 份目标会议真实发表的审稿意见作为示例。这能显著改善评分校准。审稿示例见 [references/reviewer-guidelines.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/reviewer-guidelines.md)。

### 步骤 6.1b：视觉审阅（VLM） {#step-61b-visual-review-pass-vlm}

纯文本审阅会漏掉一整类问题：图的质量、排版问题、视觉一致性。如果你能使用具备视觉能力的模型，请对编译后的 PDF 单独进行一次**视觉审阅**：

```
You are reviewing the visual presentation of this research paper PDF.
Check for:
1. Figure quality: Are plots readable? Labels legible? Colors distinguishable?
2. Figure-caption alignment: Does each caption accurately describe its figure?
3. Layout issues: Orphaned section headers, awkward page breaks, figures far from their references
4. Table formatting: Aligned columns, consistent decimal precision, bold for best results
5. Visual consistency: Same color scheme across all figures, consistent font sizes
6. Grayscale readability: Would the figures be understandable if printed in B&W?

For each issue, specify the page number and exact location.
```

这能发现基于文本的审阅无法发现的问题：坐标轴标签难以辨认的图、放在距首次引用 3 页之外的图、Figure 2 与 Figure 5 之间不一致的配色，或明显超出栏宽的表格。

### 步骤 6.1c：论点核查 {#step-61c-claim-verification-pass}

模拟审稿之后，单独进行一次核查。这能发现审稿人可能漏掉的事实性错误：

```
Claim Verification Protocol:
1. Extract every factual claim from the paper (numbers, comparisons, trends)
2. For each claim, trace it to the specific experiment/result that supports it
3. Verify the number in the paper matches the actual result file
4. Flag any claim without a traceable source as [VERIFY]
```

对于基于 agent 的工作流：将核查委派给一个**全新的子 agent**，它只接收论文文本和原始结果文件。全新的上下文可以防止确认偏差——核查者不会"记得"结果本应是什么。

### 步骤 6.2：为反馈排定优先级 {#step-62-prioritize-feedback}

收集审稿意见后，进行分类：

| 优先级 | 行动 |
|----------|--------|
| **Critical**（技术缺陷、缺少基线） | 必须修复。可能需要新实验 → 回到阶段 2 |
| **High**（表述不清、缺少消融实验） | 应在本次修订中修复 |
| **Medium**（小的写作问题、额外实验） | 时间允许时修复 |
| **Low**（风格偏好、旁枝建议） | 记录下来留作未来工作 |

### 步骤 6.3：修订循环 {#step-63-revision-cycle}

对每个 critical/high 问题：
1. 确定受影响的具体章节
2. 起草修复
3. 核实修复不会破坏其他论点
4. 更新论文
5. 对照审稿人的关切重新检查

### 步骤 6.4：撰写 Rebuttal {#step-64-rebuttal-writing}

回应真实审稿意见时（投稿之后），撰写 rebuttal 是一项有别于修订的独立技能：

**格式**：逐条回应。针对每位审稿人的每条关切：
```
> R1-W1: "The paper lacks comparison with Method X."

We thank the reviewer for this suggestion. We have added a comparison with 
Method X in Table 3 (revised). Our method outperforms X by 3.2pp on [metric] 
(p<0.05). We note that X requires 2x our compute budget.
```

**规则**：
- 回应每一条关切——审稿人会注意到你跳过了哪一条
- 以最有力的回应开头
- 简洁直接——审稿人要读几十份 rebuttal
- 如果在 rebuttal 期间做了实验，附上新结果
- 永远不要防御或轻视，即使面对薄弱的批评
- 使用 `latexdiff` 生成标注改动的 PDF（见 Professional LaTeX Tooling 一节）
- 感谢审稿人具体、可操作的反馈（而非泛泛的赞美）

**不要做的事**：没有证据就说"We respectfully disagree"。不加解释就说"This is out of scope"。只回应优点而无视弱点。

### 步骤 6.5：论文演进追踪 {#step-65-paper-evolution-tracking}

在关键里程碑保存快照：
```
paper/
  paper.tex                    # Current working version
  paper_v1_first_draft.tex     # First complete draft
  paper_v2_post_review.tex     # After simulated review
  paper_v3_pre_submission.tex  # Final before submission
  paper_v4_camera_ready.tex    # Post-acceptance final
```

---

## 阶段 7：投稿准备 {#phase-7-submission-preparation}

**目标**：最终检查、排版与投稿。

### 步骤 7.1：会议检查清单 {#step-71-conference-checklist}

每个会议都有强制性的检查清单。请认真完成——清单不完整可能导致直接拒稿（desk rejection）。

以下内容见 [references/checklists.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/checklists.md)：
- NeurIPS 16 项论文检查清单
- ICML 更广泛影响 + 可复现性
- ICLR LLM 使用披露政策
- ACL 强制性局限性章节
- 通用投稿前检查清单

### 步骤 7.2：匿名化检查清单 {#step-72-anonymization-checklist}

双盲审稿意味着审稿人无法知道论文作者是谁。请检查以下**全部**事项：

```
Anonymization Checklist:
- [ ] No author names or affiliations anywhere in the PDF
- [ ] No acknowledgments section (add after acceptance)
- [ ] Self-citations written in third person: "Smith et al. [1] showed..." not "We previously showed [1]..."
- [ ] No GitHub/GitLab URLs pointing to your personal repos
- [ ] Use Anonymous GitHub (https://anonymous.4open.science/) for code links
- [ ] No institutional logos or identifiers in figures
- [ ] No file metadata containing author names (check PDF properties)
- [ ] No "our previous work" or "in our earlier paper" phrasing
- [ ] Dataset names don't reveal institution (rename if needed)
- [ ] Supplementary materials don't contain identifying information
```

**常见错误**：补充材料代码中可见的 Git 提交信息、机构工具生成的带水印图片、从旧稿中遗留下来的致谢、在匿名期之前发布了 arXiv 预印本。

### 步骤 7.3：格式核查 {#step-73-formatting-verification}

```
Pre-Submission Format Check:
- [ ] Page limit respected (excluding references and appendix)
- [ ] All figures are vector (PDF) or high-res raster (600 DPI PNG)
- [ ] All figures readable in grayscale
- [ ] All tables use booktabs
- [ ] References compile correctly (no "?" in citations)
- [ ] No overfull hboxes in critical areas
- [ ] Appendix clearly labeled and separated
- [ ] Required sections present (limitations, broader impact, etc.)
```

### 步骤 7.4：编译前验证 {#step-74-pre-compilation-validation}

在尝试 `pdflatex` **之前**运行这些自动检查。在这里捕获错误比调试编译器输出更快。

```bash
# 1. Lint with chktex (catches common LaTeX mistakes)
# Suppress noisy warnings: -n2 (sentence end), -n24 (parens), -n13 (intersentence), -n1 (command terminated)
chktex main.tex -q -n2 -n24 -n13 -n1

# 2. Verify all citations exist in .bib
# Extract \cite{...} from .tex, check each against .bib
python3 -c "
import re
tex = open('main.tex').read()
bib = open('references.bib').read()
cites = set(re.findall(r'\\\\cite[tp]?{([^}]+)}', tex))
for cite_group in cites:
    for cite in cite_group.split(','):
        cite = cite.strip()
        if cite and cite not in bib:
            print(f'WARNING: \\\\cite{{{cite}}} not found in references.bib')
"

# 3. Verify all referenced figures exist on disk
python3 -c "
import re, os
tex = open('main.tex').read()
figs = re.findall(r'\\\\includegraphics(?:\[.*?\])?{([^}]+)}', tex)
for fig in figs:
    if not os.path.exists(fig):
        print(f'WARNING: Figure file not found: {fig}')
"

# 4. Check for duplicate \label definitions
python3 -c "
import re
from collections import Counter
tex = open('main.tex').read()
labels = re.findall(r'\\\\label{([^}]+)}', tex)
dupes = {k: v for k, v in Counter(labels).items() if v > 1}
for label, count in dupes.items():
    print(f'WARNING: Duplicate label: {label} (appears {count} times)')
"
```

继续之前修复所有警告。对于基于 agent 的工作流：将 chktex 输出反馈给 agent，并指示其做最小化修复。

### 步骤 7.5：最终编译 {#step-75-final-compilation}

```bash
# Clean build
rm -f *.aux *.bbl *.blg *.log *.out *.pdf
latexmk -pdf main.tex

# Or manual (triple pdflatex + bibtex for cross-references)
pdflatex -interaction=nonstopmode main.tex
bibtex main
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex

# Verify output exists and has content
ls -la main.pdf
```

**如果编译失败**：解析 `.log` 文件，找到第一个错误。常见修复：
- "Undefined control sequence" → 缺少宏包或命令名拼写错误
- "Missing $ inserted" → 数学符号出现在数学模式之外
- "File not found" → 图片路径错误或缺少 .sty 文件
- "Citation undefined" → .bib 条目缺失或未运行 bibtex

### 步骤 7.6：各会议的特定要求 {#step-76-conference-specific-requirements}

| 会议 | 特殊要求 |
|-------|---------------------|
| **NeurIPS** | 附录中的论文检查清单；若被接收需提供通俗摘要 |
| **ICML** | Broader Impact Statement（置于结论之后，不计入页数限制） |
| **ICLR** | 必须披露 LLM 使用情况；互惠审稿协议 |
| **ACL** | 强制性 Limitations 章节；Responsible NLP 检查清单 |
| **AAAI** | 严格的样式文件——不允许任何修改 |
| **COLM** | 面向语言模型社区来阐述贡献 |

### 步骤 7.7：会议重投与格式转换 {#step-77-conference-resubmission--format-conversion}

在不同会议之间转换时，**切勿在模板之间复制 LaTeX 导言区（preamble）**：

```bash
# 1. Start fresh with target template
cp -r templates/icml2026/ new_submission/

# 2. Copy ONLY content sections (not preamble)
#    - Abstract text, section content, figures, tables, bib entries

# 3. Adjust for page limits
# 4. Add venue-specific required sections
# 5. Update references
```

| 从 → 到 | 页数变化 | 关键调整 |
|-----------|-------------|-----------------|
| NeurIPS → ICML | 9 → 8 | 删减 1 页，添加 Broader Impact |
| ICML → ICLR | 8 → 9 | 扩充实验，添加 LLM 使用声明 |
| NeurIPS → ACL | 9 → 8 | 按 NLP 惯例重组结构，添加 Limitations |
| ICLR → AAAI | 9 → 7 | 大幅删减，严格遵守格式要求 |
| Any → COLM | 不定 → 9 | 围绕语言模型重新组织叙述重点 |

删减页数时：将证明移至附录，精简相关工作，合并表格，使用子图。
扩充页数时：添加消融实验，扩展局限性讨论，加入更多基线，添加定性示例。

**被拒之后**：在新版本中回应审稿人的关切，但不要包含"修改说明"部分，也不要提及之前的投稿（盲审）。

### 步骤 7.8：Camera-Ready 版本准备（录用后） {#step-78-camera-ready-preparation-post-acceptance}

论文被录用后，准备 camera-ready 版本：

```
Camera-Ready Checklist:
- [ ] De-anonymize: add author names, affiliations, email addresses
- [ ] Add Acknowledgments section (funding, compute grants, helpful reviewers)
- [ ] Add public code/data URL (real GitHub, not anonymous)
- [ ] Address any mandatory revisions from meta-reviewer
- [ ] Switch template to camera-ready mode (if applicable — e.g., AAAI \anon → \camera)
- [ ] Add copyright notice if required by venue
- [ ] Update any "anonymous" placeholders in text
- [ ] Verify final PDF compiles cleanly
- [ ] Check page limit for camera-ready (sometimes differs from submission)
- [ ] Upload supplementary materials (code, data, appendix) to venue portal
```

### 步骤 7.9：arXiv 与预印本策略 {#step-79-arxiv--preprint-strategy}

在 ML 领域，将论文发布到 arXiv 是标准做法，但在时机和匿名性方面有重要的注意事项。

**时机决策树：**

| 情况 | 建议 |
|-----------|---------------|
| 投稿至双盲会议（NeurIPS、ICML、ACL） | 在投稿截止**之后**再发布到 arXiv，不要提前。提前发布在技术上可能违反匿名政策，尽管执行力度因会议而异。 |
| 投稿至 ICLR | ICLR 明确允许在投稿前发布到 arXiv。但不要在投稿稿件本身中写入作者姓名。 |
| 论文已在 arXiv 上，投稿至新会议 | 大多数会议都可接受。审稿期间**不要**用引用审稿意见的修改来更新 arXiv 版本。 |
| Workshop 论文 | 任何时候发布到 arXiv 都可以——workshop 通常不是双盲的。 |
| 希望确立优先权 | 如果担心被抢发，请立即发布——但要接受匿名性上的取舍。 |

**arXiv 分类选择**（ML/AI 论文）：

| 分类 | 代码 | 最适合 |
|----------|------|----------|
| Machine Learning | `cs.LG` | 通用 ML 方法 |
| Computation and Language | `cs.CL` | NLP、语言模型 |
| Artificial Intelligence | `cs.AI` | 推理、规划、agent |
| Computer Vision | `cs.CV` | 视觉模型 |
| Information Retrieval | `cs.IR` | 搜索、推荐 |

**列出主分类 + 1-2 个交叉分类。** 分类越多 = 曝光度越高，但只在确实相关时才交叉列出。

**版本策略：**
- **v1**：初始提交（与会议投稿版本一致）
- **v2**：录用后包含 camera-ready 修正的版本（在摘要中添加"accepted at [Venue]"）
- 审稿期间不要发布明显回应审稿人反馈的 v2 版本

```bash
# Check if your paper's title is already taken on arXiv
# (before choosing a title)
pip install arxiv
python -c "
import arxiv
results = list(arxiv.Search(query='ti:\"Your Exact Title\"', max_results=5).results())
print(f'Found {len(results)} matches')
for r in results: print(f'  {r.title} ({r.published.year})')
"
```

### 步骤 7.10：研究代码打包 {#step-710-research-code-packaging}

发布干净、可运行的代码能显著提高引用量和审稿人的信任。请将代码与 camera-ready 版本一同打包发布。

**仓库结构：**

```
your-method/
  README.md              # Setup, usage, reproduction instructions
  requirements.txt       # Or environment.yml for conda
  setup.py               # For pip-installable packages
  LICENSE                # MIT or Apache 2.0 recommended for research
  configs/               # Experiment configurations
  src/                   # Core method implementation
  scripts/               # Training, evaluation, analysis scripts
    train.py
    evaluate.py
    reproduce_table1.sh  # One script per main result
  data/                  # Small data or download scripts
    download_data.sh
  results/               # Expected outputs for verification
```

**研究代码的 README 模板：**

```markdown
# [Paper Title]

Official implementation of "[Paper Title]" (Venue Year).

## Setup
[Exact commands to set up environment]

## Reproduction
To reproduce Table 1: `bash scripts/reproduce_table1.sh`
To reproduce Figure 2: `python scripts/make_figure2.py`

## Citation
[BibTeX entry]
```

**发布前检查清单：**
```
- [ ] Code runs from a clean clone (test on fresh machine or Docker)
- [ ] All dependencies pinned to specific versions
- [ ] No hardcoded absolute paths
- [ ] No API keys, credentials, or personal data in repo
- [ ] README covers setup, reproduction, and citation
- [ ] LICENSE file present (MIT or Apache 2.0 for max reuse)
- [ ] Results are reproducible within expected variance
- [ ] .gitignore excludes data files, checkpoints, logs
```

**投稿用的匿名代码**（录用前）：
```bash
# Use Anonymous GitHub for double-blind review
# https://anonymous.4open.science/
# Upload your repo → get an anonymous URL → put in paper
```

---

## 阶段 8：录用后的交付物 {#phase-8-post-acceptance-deliverables}

**目标**：通过展示材料和社区互动，最大化已录用论文的影响力。

### 步骤 8.1：会议海报 {#step-81-conference-poster}

大多数会议都要求参加海报环节。海报设计原则：

| 要素 | 指南 |
|---------|-----------|
| **尺寸** | 查看会议要求（通常为 24"x36" 或 A0 竖版/横版） |
| **内容** | 标题、作者、一句话贡献、方法示意图、2-3 个关键结果、结论 |
| **阅读流** | 从左上到右下（Z 字形）或分栏布局 |
| **文字** | 标题在 3 米外可读，正文在 1 米外可读。不要整段文字——只用要点。 |
| **图表** | 以更高分辨率复用论文中的图。放大关键结果。 |

**工具**：LaTeX（`beamerposter` 宏包）、PowerPoint/Keynote、Figma、Canva。

**制作**：在会议前 2 周以上下单。布质海报更便于携带出行。如今许多会议也支持虚拟/数字海报。

### 步骤 8.2：会议报告 / Spotlight {#step-82-conference-talk--spotlight}

如果获得口头报告（oral）或 spotlight 展示机会：

| 报告类型 | 时长 | 内容 |
|-----------|----------|---------|
| **Spotlight** | 5 分钟 | 问题、方法、一个关键结果。排练到恰好 5 分钟。 |
| **Oral** | 15-20 分钟 | 完整叙事：问题、方法、关键结果、消融实验、局限性。 |
| **Workshop 报告** | 10-15 分钟 | 根据 workshop 听众调整——可能需要更多背景介绍。 |

**幻灯片设计规则：**
- 每张幻灯片一个观点
- 尽量减少文字——细节用嘴讲，不要投在屏幕上
- 为关键图表添加动画，逐步建立理解
- 在结尾加入一张"要点"幻灯片（一句话概括贡献）
- 为预期的提问准备备用幻灯片

### 步骤 8.3：博客文章 / 社交媒体 {#step-83-blog-post--social-media}

通俗易懂的总结能显著提升影响力：

- **Twitter/X 推文串**：5-8 条推文。以结果开篇，而非方法。附上图 1 和关键结果图。
- **博客文章**：800-1500 字。面向 ML 从业者而非审稿人撰写。略过形式化推导，强调直觉和实际意义。
- **项目主页**：包含摘要、图表、演示、代码链接、BibTeX 的 HTML 页面。使用 GitHub Pages。

**时机**：在论文出现在会议论文集或 arXiv camera-ready 版本发布后 1-2 天内发布。

---

## Workshop 与短论文 {#workshop--short-papers}

Workshop 论文和短论文（例如 ACL 短论文、Findings 论文）遵循相同的流程，但约束和期望有所不同。

### Workshop 论文 {#workshop-papers}

| 属性 | Workshop | 主会 |
|----------|----------|-----------------|
| **页数限制** | 4-6 页（通常） | 7-9 页 |
| **审稿标准** | 对完整性要求较低 | 必须完整、详尽 |
| **审稿流程** | 通常为单盲或轻量审稿 | 双盲、严格 |
| **看重什么** | 有趣的想法、初步结果、立场观点 | 具有强基线的完整实证叙事 |
| **arXiv** | 随时发布 | 时机很重要（见 arXiv 策略） |
| **贡献门槛** | 新颖方向、有趣的负面结果、进行中的工作 | 有强有力证据支撑的重大进展 |

**何时以 workshop 为目标：**
- 希望在写完整论文之前获得反馈的早期想法
- 不足以支撑 8 页以上篇幅的负面结果
- 针对热点话题的立场或观点文章
- 复现研究或可复现性报告

### ACL 短论文与 Findings {#acl-short-papers--findings}

ACL 系列会议有不同的投稿类型：

| 类型 | 页数 | 期望内容 |
|------|-------|-----------------|
| **长论文** | 8 | 完整研究、强基线、消融实验 |
| **短论文** | 4 | 聚焦的贡献：一个有证据支撑的清晰论点 |
| **Findings** | 8 | 与主会失之交臂的扎实工作 |

**短论文策略**：选择**一个**论点并充分论证。不要试图把长论文压缩到 4 页——而是写一篇不同的、更聚焦的论文。

---

## 实证 ML 之外的论文类型 {#paper-types-beyond-empirical-ml}

上述主流程针对的是实证 ML 论文。其他类型的论文需要不同的结构和证据标准。各类型的详细指导见 [references/paper-types.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/paper-types.md)。

### 理论论文 {#theory-papers}

**结构**：引言 → 预备知识（定义、记号）→ 主要结果（定理）→ 证明概要 → 讨论 → 完整证明（附录）

**与实证论文的主要区别：**
- 贡献是定理、界或不可能性结果——而非实验数字
- 方法部分由"预备知识"和"主要结果"取代
- 证据是证明而非实验（尽管欢迎对理论进行实证验证）
- 正文给出证明概要、附录给出完整证明是标准做法
- 实验部分是可选的，但如果能验证理论预测，会增强论文说服力

**证明写作原则：**
- 正式陈述定理，并明确列出所有假设
- 在正式证明之前提供直觉（"关键洞见在于……"）
- 证明概要应在 0.5-1 页内传达主要思路
- 使用 `\begin{proof}...\end{proof}` 环境
- 为假设编号并在定理中引用："在假设 1-3 下，……"

### 综述 / 教程论文 {#survey--tutorial-papers}

**结构**：引言 → 分类体系 / 组织框架 → 详细论述 → 开放问题 → 结论

**主要区别：**
- 贡献在于组织、综合以及识别开放问题——而非新方法
- 在其范围内必须全面（审稿人会检查是否遗漏参考文献）
- 需要清晰的分类体系或组织框架
- 价值来自于单篇论文未能建立的工作之间的联系
- 最佳去处：TMLR（综述 track）、JMLR、Foundations and Trends in ML、ACM Computing Surveys

### 基准论文 {#benchmark-papers}

**结构**：引言 → 任务定义 → 数据集构建 → 基线评估 → 分析 → 预期用途与局限性

**主要区别：**
- 贡献是基准本身——它必须填补真实的评估空白
- 数据集文档是必需的，而非可选（见 Datasheets，步骤 5.11）
- 必须证明该基准具有挑战性（基线无法使其饱和）
- 必须证明该基准衡量的正是你所声称的内容（构念效度）
- 最佳去处：NeurIPS Datasets & Benchmarks track、ACL（资源论文）、LREC-COLING

### 立场论文 {#position-papers}

**结构**：引言 → 背景 → 论点 / 主张 → 支持证据 → 反驳观点 → 启示

**主要区别：**
- 贡献是一个论点，而非一个结果
- 必须认真回应反驳观点
- 证据可以是实证的、理论的或逻辑分析
- 最佳去处：ICML（立场 track）、workshop、TMLR

---

## Hermes Agent 集成 {#hermes-agent-integration}

此 skill 专为 Hermes agent 设计。它使用 Hermes 的工具、委派、调度和记忆功能来支持完整的研究生命周期。

### 相关 Skill {#related-skills}

在特定阶段将此 skill 与其他 Hermes skill 组合使用：

| Skill | 何时使用 | 如何加载 |
|-------|-------------|-------------|
| **arxiv** | 阶段 1（文献综述）：搜索 arXiv、生成 BibTeX、通过 Semantic Scholar 查找相关论文 | `skill_view("arxiv")` |
| **subagent-driven-development** | 阶段 5（起草）：并行撰写各章节，采用两阶段审阅（先规范符合性，后质量） | `skill_view("subagent-driven-development")` |
| **plan** | 阶段 0（准备）：在执行前创建结构化计划。写入 `.hermes/plans/` | `skill_view("plan")` |
| **qmd** | 阶段 1（文献）：通过 BM25+向量混合搜索检索本地知识库（笔记、转录、文档） | 安装：`skill_manage("install", "qmd")` |
| **diagramming** | 阶段 4-5：创建基于 Excalidraw 的图表和架构图 | `skill_view("diagramming")` |
| **data-science** | 阶段 4（分析）：使用 Jupyter 实时内核进行交互式分析和可视化 | `skill_view("data-science")` |

**此 skill 取代了 `ml-paper-writing`**——它包含 ml-paper-writing 的全部内容，外加完整的实验/分析流程和 autoreason 方法论。

### Hermes 工具参考 {#hermes-tools-reference}

| 工具 | 在此流程中的用途 |
|------|----------------------|
| **`terminal`** | LaTeX 编译（`latexmk -pdf`）、git 操作、启动实验（`nohup python run.py &`）、进程检查 |
| **`process`** | 后台实验管理：`process("start", ...)`、`process("poll", pid)`、`process("log", pid)`、`process("kill", pid)` |
| **`execute_code`** | 运行 Python 进行引用验证、统计分析、数据汇总。可通过 RPC 访问工具。 |
| **`read_file`** / **`write_file`** / **`patch`** | 论文编辑、实验脚本、结果文件。对大型 .tex 文件的定点编辑请使用 `patch`。 |
| **`web_search`** | 文献发现：`web_search("transformer attention mechanism 2024")` |
| **`web_extract`** | 获取论文内容、验证引用：`web_extract("https://arxiv.org/abs/2303.17651")` |
| **`delegate_task`** | **并行起草章节**——为每个章节启动独立的 subagent。也可用于并发验证引用。 |
| **`todo`** | 跨会话的主要状态跟踪器。每次阶段切换后都要更新。 |
| **`memory`** | 跨会话持久化关键决策：贡献定位、会议选择、审稿人反馈。 |
| **`cronjob`** | 调度实验监控、截止日期倒计时、自动 arXiv 检查。 |
| **`clarify`** | 受阻时向用户提出有针对性的问题（会议选择、贡献定位）。 |
| **cron `deliver:`** | 在实验完成或草稿就绪时通知用户，即使用户不在聊天中——将检查调度为带有消息 `deliver:` 目标的 cron 任务（agent 已不再拥有 `send_message` 工具；外发投递由 cron/`hermes send` 处理）。 |

### 工具使用模式 {#tool-usage-patterns}

**实验监控**（最常见）：
```
terminal("ps aux | grep <pattern>")
→ terminal("tail -30 <logfile>")
→ terminal("ls results/")
→ execute_code("analyze results JSON, compute metrics")
→ terminal("git add -A && git commit -m '<descriptive message>' && git push")
→ (final response auto-delivers "Experiment complete: <summary>"; for unattended runs, schedule via cron with a deliver: target)
```

**并行起草章节**（使用委派）：
```
delegate_task("Draft the Methods section based on these experiment scripts and configs. 
  Include: pseudocode, all hyperparameters, architectural details sufficient for 
  reproduction. Write in LaTeX using the neurips2025 template conventions.")

delegate_task("Draft the Related Work section. Use web_search and web_extract to 
  find papers. Verify every citation via Semantic Scholar. Group by methodology.")

delegate_task("Draft the Experiments section. Read all result files in results/. 
  State which claim each experiment supports. Include error bars and significance.")
```

每个委派任务都作为一个**全新的 subagent** 运行，不共享上下文——请在 prompt 中提供所有必要信息。收集各输出并整合。

**引用验证**（使用 execute_code）：
```python
# In execute_code:
from semanticscholar import SemanticScholar
import requests

sch = SemanticScholar()
results = sch.search_paper("attention mechanism transformers", limit=5)
for paper in results:
    doi = paper.externalIds.get('DOI', 'N/A')
    if doi != 'N/A':
        bibtex = requests.get(f"https://doi.org/{doi}", 
                              headers={"Accept": "application/x-bibtex"}).text
        print(bibtex)
```

### 使用 `memory` 和 `todo` 进行状态管理 {#state-management-with-memory-and-todo}

**`memory` 工具**——持久化关键决策（有上限：MEMORY.md 约 2200 字符）：

```
memory("add", "Paper: autoreason. Venue: NeurIPS 2025 (9 pages). 
  Contribution: structured refinement works when generation-evaluation gap is wide.
  Key results: Haiku 42/42, Sonnet 3/5, S4.6 constrained 2/3.
  Status: Phase 5 — drafting Methods section.")
```

在重大决策或阶段切换后更新 memory。它会跨会话持久保存。

**`todo` 工具**——跟踪细粒度进度：

```
todo("add", "Design constrained task experiments for Sonnet 4.6")
todo("add", "Run Haiku baseline comparison")
todo("add", "Draft Methods section")
todo("update", id=3, status="in_progress")
todo("update", id=1, status="completed")
```

**会话启动流程：**
```
1. todo("list")                           # Check current task list
2. memory("read")                         # Recall key decisions
3. terminal("git log --oneline -10")      # Check recent commits
4. terminal("ps aux | grep python")       # Check running experiments
5. terminal("ls results/ | tail -20")     # Check for new results
6. Report status to user, ask for direction
```

### 使用 `cronjob` 进行定时监控 {#cron-monitoring-with-cronjob}

使用 `cronjob` 工具调度周期性的实验检查：

```
cronjob("create", {
  "schedule": "*/30 * * * *",  # Every 30 minutes
  "prompt": "Check experiment status:
    1. ps aux | grep run_experiment
    2. tail -30 logs/experiment_haiku.log
    3. ls results/haiku_baselines/
    4. If complete: read results, compute Borda scores, 
       git add -A && git commit -m 'Add Haiku results' && git push
    5. Report: table of results, key finding, next step
    6. If nothing changed: respond with [SILENT]"
})
```

**[SILENT] 协议**：如果自上次检查以来没有任何变化，请严格回复 `[SILENT]`。这会抑制向用户投递通知。只有在出现真正值得了解的变化时才报告。

**截止日期跟踪**：
```
cronjob("create", {
  "schedule": "0 9 * * *",  # Daily at 9am
  "prompt": "NeurIPS 2025 deadline: May 22. Today is {date}. 
    Days remaining: {compute}. 
    Check todo list — are we on track? 
    If <7 days: warn user about remaining tasks."
})
```

### 沟通模式 {#communication-patterns}

**何时通知用户**（通过你的直接/最终回复，或对无人值守的运行使用 cron `deliver:` 目标）：
- 一批实验完成（附结果表）
- 出现需要决策的意外发现或失败
- 某章节草稿已准备好供审阅
- 截止日期临近且仍有未完成任务

**何时不要通知：**
- 实验仍在运行，没有新结果 → `[SILENT]`
- 例行监控且无变化 → `[SILENT]`
- 无需关注的中间步骤

**报告格式**——始终包含结构化数据：
```
## Experiment: <name>
Status: Complete / Running / Failed

| Task | Method A | Method B | Method C |
|------|---------|---------|---------|
| Task 1 | 85.2 | 82.1 | **89.4** |

Key finding: <one sentence>
Next step: <what happens next>
```

### 需要人工输入的决策点 {#decision-points-requiring-human-input}

在真正受阻时，使用 `clarify` 提出有针对性的问题：

| 决策 | 何时询问 |
|----------|-------------|
| 目标会议 | 开始写论文之前（影响页数限制、叙述定位） |
| 贡献定位 | 存在多种合理定位时 |
| 实验优先级 | TODO 列表中的实验多于时间允许的数量时 |
| 投稿就绪度 | 最终投稿之前 |

**不要询问**（主动行事，做出选择，并标注出来）：
- 措辞选择、章节顺序
- 具体突出哪些结果
- 引用完整性（先用找到的内容起草，标注缺口）

---

## 审稿人评估标准 {#reviewer-evaluation-criteria}

了解审稿人关注什么有助于集中精力：

| 标准 | 他们检查什么 |
|-----------|----------------|
| **质量** | 技术可靠性、有充分支撑的论断、公平的基线 |
| **清晰度** | 行文清晰、专家可复现、记号一致 |
| **重要性** | 对社区的影响、推进认识 |
| **原创性** | 新的洞见（不要求新方法） |

**评分（NeurIPS 6 分制）：**
- 6：Strong Accept——开创性、无瑕疵
- 5：Accept——技术扎实、影响力高
- 4：Borderline Accept——扎实，但评估有限
- 3：Borderline Reject——缺点多于优点
- 2：Reject——存在技术缺陷
- 1：Strong Reject——已知结果或存在伦理问题

详细指南、常见关切和 rebuttal 策略见 [references/reviewer-guidelines.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/reviewer-guidelines.md)。

---

## 常见问题与解决方案 {#common-issues-and-solutions}

| 问题 | 解决方案 |
|-------|----------|
| 摘要过于泛泛 | 如果第一句可以放在任何 ML 论文开头，就删掉它。从你的具体贡献开始。 |
| 引言超过 1.5 页 | 将背景拆分到相关工作中。把贡献要点前置。 |
| 实验缺乏明确的论断 | 在每个实验之前添加："此实验检验 [具体论断] 是否……" |
| 审稿人觉得论文难以理解 | 添加路标式引导，使用一致的术语，让图注自成一体。 |
| 缺少统计显著性 | 添加误差线、运行次数、统计检验、置信区间。 |
| 实验范围蔓延 | 每个实验都必须对应一个具体论断。删掉不对应的实验。 |
| 论文被拒，需要重投 | 见阶段 7 中的会议重投。回应审稿人关切，但不要提及审稿意见。 |
| 缺少 broader impact 声明 | 见步骤 5.10。大多数会议都要求提供。"没有负面影响"几乎从不可信。 |
| 人工评估被批评为薄弱 | 见步骤 2.5 和 [references/human-evaluation.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/human-evaluation.md)。报告一致性指标、标注者详情、报酬。 |
| 审稿人质疑可复现性 | 发布代码（步骤 7.9），记录所有超参数，包含随机种子和算力细节。 |
| 理论论文缺乏直觉 | 在正式证明之前添加带有通俗解释的证明概要。见 [references/paper-types.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/paper-types.md)。 |
| 结果为负面/无效 | 见阶段 4.3 关于处理负面结果的内容。考虑 workshop、TMLR，或重新定位为分析型论文。 |

---

## 参考文档 {#reference-documents}

| 文档 | 内容 |
|----------|----------|
| [references/writing-guide.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/writing-guide.md) | Gopen & Swan 7 条原则、Perez 微技巧、Lipton 措辞建议、Steinhardt 精确性、图表设计 |
| [references/citation-workflow.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/citation-workflow.md) | 引用 API、Python 代码、CitationManager 类、BibTeX 管理 |
| [references/checklists.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/checklists.md) | NeurIPS 16 项清单、ICML、ICLR、ACL 要求、通用投稿前检查清单 |
| [references/reviewer-guidelines.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/reviewer-guidelines.md) | 评估标准、评分、常见关切、rebuttal 模板 |
| [references/sources.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/sources.md) | 所有写作指南、会议指南、API 的完整参考文献 |
| [references/experiment-patterns.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/experiment-patterns.md) | 实验设计模式、评估协议、监控、错误恢复 |
| [references/autoreason-methodology.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/autoreason-methodology.md) | Autoreason 循环、策略选择、模型指南、prompt、范围约束、Borda 评分 |
| [references/human-evaluation.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/human-evaluation.md) | 人工评估设计、标注指南、一致性指标、众包质控、IRB 指导 |
| [references/paper-types.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/references/paper-types.md) | 理论论文（证明写作、定理结构）、综述论文、基准论文、立场论文 |

### LaTeX 模板 {#latex-templates}

`templates/` 中提供以下模板：**NeurIPS 2025**、**ICML 2026**、**ICLR 2026**、**ACL**、**AAAI 2026**、**COLM 2025**。

编译说明见 [templates/README.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/research/research-paper-writing/templates/README.md)。

### 关键外部资源 {#key-external-sources}

**写作理念：**
- [Neel Nanda: How to Write ML Papers](https://www.alignmentforum.org/posts/eJGptPbbFPZGLpjsp/highly-opinionated-advice-on-how-to-write-ml-papers)
- [Sebastian Farquhar: How to Write ML Papers](https://sebastianfarquhar.com/on-research/2024/11/04/how_to_write_ml_papers/)
- [Gopen & Swan: Science of Scientific Writing](https://cseweb.ucsd.edu/~swanson/papers/science-of-writing.pdf)
- [Lipton: Heuristics for Scientific Writing](https://www.approximatelycorrect.com/2018/01/29/heuristics-technical-scientific-writing-machine-learning-perspective/)
- [Perez: Easy Paper Writing Tips](https://ethanperez.net/easy-paper-writing-tips/)

**API：** [Semantic Scholar](https://api.semanticscholar.org/api-docs/) | [CrossRef](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | [arXiv](https://info.arxiv.org/help/api/basics.html)

**会议：** [NeurIPS](https://neurips.cc/Conferences/2025/PaperInformation/StyleFiles) | [ICML](https://icml.cc/Conferences/2025/AuthorInstructions) | [ICLR](https://iclr.cc/Conferences/2026/AuthorGuide) | [ACL](https://github.com/acl-org/acl-style-files)
