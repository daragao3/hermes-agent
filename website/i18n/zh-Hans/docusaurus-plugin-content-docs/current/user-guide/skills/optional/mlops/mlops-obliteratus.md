---
title: "Obliteratus — OBLITERATUS：消除 LLM 的拒答行为（diff-in-means）"
sidebar_label: "Obliteratus"
description: "OBLITERATUS：消除 LLM 的拒答行为（diff-in-means）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Obliteratus

OBLITERATUS：消除 LLM 的拒答行为（diff-in-means）。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/mlops/obliteratus` 安装 |
| 路径 | `optional-skills/mlops/obliteratus` |
| 版本 | `2.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 依赖项 | `obliteratus`, `torch`, `transformers`, `bitsandbytes`, `accelerate`, `safetensors` |
| 平台 | linux, macos |
| 标签 | `Abliteration`, `Uncensoring`, `Refusal-Removal`, `LLM`, `Weight-Projection`, `SVD`, `Mechanistic-Interpretability`, `HuggingFace`, `Model-Surgery` |
| 相关 skills | `vllm`, `gguf`, [`huggingface-tokenizers`](/user-guide/skills/optional/mlops/mlops-huggingface-tokenizers) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# OBLITERATUS Skill

## 内容概览

9 种 CLI 方法、28 个分析模块、覆盖 5 个算力档位的 116 个模型预设、锦标赛式评测，以及基于遥测数据的推荐。

在不重新训练或微调的前提下，移除开放权重 LLM 的拒答行为（护栏）。它使用机制可解释性技术 —— 包括 diff-in-means、SVD、白化 SVD、LEACE 概念擦除、SAE 分解、贝叶斯核投影等 —— 识别拒答方向并从模型权重中精准切除，同时保留推理能力。

**许可证警告：** OBLITERATUS 采用 AGPL-3.0 许可。绝不要把它作为 Python 库导入。始终通过 CLI（`obliteratus` 命令）或子进程调用。这样才能保持 Hermes Agent 的 MIT 许可证不受污染。

## 视频指南

一段 Hermes agent 使用 OBLITERATUS 对 Gemma 进行 abliteration 的完整演示：
https://www.youtube.com/watch?v=8fG9BrNTeHs（"OBLITERATUS: An AI Agent Removed Gemma 4's Safety Guardrails"）

当用户想在自己动手之前先直观了解端到端流程时很有用。

## 何时使用本 Skill

在用户出现以下情况时触发：
- 想要"解除审查"或"abliterate"某个 LLM
- 询问如何移除模型的拒答行为 / 护栏
- 想制作一个无审查版本的 Llama、Qwen、Mistral 等
- 提到 "refusal removal"、"abliteration"、"weight projection"
- 想分析某个模型的拒答机制是如何工作的
- 提及 OBLITERATUS、abliterator 或拒答方向

## 第 1 步：安装

检查是否已安装：
```bash
obliteratus --version 2>/dev/null && echo "INSTALLED" || echo "NOT INSTALLED"
```

如果尚未安装，从 GitHub 克隆并安装：
```bash
git clone https://github.com/elder-plinius/OBLITERATUS.git
cd OBLITERATUS
pip install -e .
# For Gradio web UI support:
# pip install -e ".[spaces]"
```

**重要：** 安装前请与用户确认。这会拉取约 5-10GB 的依赖（PyTorch、Transformers、bitsandbytes 等）。

## 第 2 步：检查硬件

开始之前，先确认可用的 GPU：
```bash
python3 -c "
import torch
if torch.cuda.is_available():
    gpu = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f'GPU: {gpu}')
    print(f'VRAM: {vram:.1f} GB')
    if vram < 4: print('TIER: tiny (models under 1B)')
    elif vram < 8: print('TIER: small (models 1-4B)')
    elif vram < 16: print('TIER: medium (models 4-9B with 4bit quant)')
    elif vram < 32: print('TIER: large (models 8-32B with 4bit quant)')
    else: print('TIER: frontier (models 32B+)')
else:
    print('NO GPU - only tiny models (under 1B) on CPU')
"
```

### 显存需求（采用 4-bit 量化时）

| 显存     | 最大模型规模    | 示例模型                                    |
|:---------|:----------------|:--------------------------------------------|
| 仅 CPU   | 约 1B 参数      | GPT-2, TinyLlama, SmolLM                    |
| 4-8 GB   | 约 4B 参数      | Qwen2.5-1.5B, Phi-3.5 mini, Llama 3.2 3B   |
| 8-16 GB  | 约 9B 参数      | Llama 3.1 8B, Mistral 7B, Gemma 2 9B       |
| 24 GB    | 约 32B 参数     | Qwen3-32B, Llama 3.1 70B（勉强）, Command-R |
| 48 GB+   | 约 72B+ 参数    | Qwen2.5-72B, DeepSeek-R1                    |
| 多 GPU   | 200B+ 参数      | Llama 3.1 405B, DeepSeek-V3 (685B MoE)      |

## 第 3 步：浏览可用模型并获取推荐

```bash
# Browse models by compute tier
obliteratus models --tier medium

# Get architecture info for a specific model
obliteratus info <model_name>

# Get telemetry-driven recommendation for best method & params
obliteratus recommend <model_name>
obliteratus recommend <model_name> --insights  # global cross-architecture rankings
```

## 第 4 步：选择方法

### 方法选择指南
**默认 / 大多数情况下推荐：`advanced`。** 它使用带保范投影的多方向 SVD，经过充分测试。

| 情境                              | 推荐方法           | 原因                                     |
|:----------------------------------|:-------------------|:-----------------------------------------|
| 默认 / 大多数模型                 | `advanced`         | 多方向 SVD、保范、可靠 |
| 快速试验 / 原型验证               | `basic`            | 快速、简单，足以做评估    |
| 稠密模型（Llama、Mistral）        | `advanced`         | 多方向、保范         |
| MoE 模型（DeepSeek、Mixtral）     | `nuclear`          | 专家粒度，能应对 MoE 的复杂性  |
| 推理模型（R1 蒸馏版）             | `surgical`         | 感知 CoT，保留思维链    |
| 顽固的拒答依然存在                | `aggressive`       | 白化 SVD + 注意力头手术 + 越狱   |
| 想要可逆的改动                    | 使用引导向量（见"分析"一节） |
| 追求极致质量，不在乎时间          | `optimized`        | 用贝叶斯搜索寻找最佳参数      |
| 实验性的自动检测                  | `informed`         | 自动检测对齐类型 —— 实验性质，未必总能胜过 advanced |

### 9 种 CLI 方法
- **basic** —— 通过 diff-in-means 提取单个拒答方向。快速（8B 模型约 5-10 分钟）。
- **advanced**（默认、推荐）—— 多个 SVD 方向、保范投影、2 轮精修。速度中等（约 10-20 分钟）。
- **aggressive** —— 白化 SVD + 越狱对比 + 注意力头手术。损伤连贯性的风险更高。
- **spectral_cascade** —— DCT 频域分解。研究性 / 新颖方法。
- **informed** —— 在 abliteration 过程中运行分析以自动配置。实验性质 —— 比 advanced 更慢、更难预测。
- **surgical** —— SAE 特征 + 神经元掩码 + 注意力头手术 + 逐专家处理。非常慢（约 1-2 小时）。最适合推理模型。
- **optimized** —— 贝叶斯超参数搜索（Optuna TPE）。耗时最长，但能找到最优参数。
- **inverted** —— 翻转拒答方向。模型会变得主动配合。
- **nuclear** —— 针对顽固 MoE 模型的最大火力组合。专家粒度。

### 方向提取方法（--direction-method 参数）
- **diff_means**（默认）—— 在拒答 / 配合两组激活之间做简单的均值差。稳健。
- **svd** —— 多方向 SVD 提取。更适合复杂的对齐。
- **leace** —— LEACE（Linear Erasure via Closed-form Estimation）。最优线性擦除。

### 4 种仅限 Python API 的方法
（不通过 CLI 提供 —— 需要 Python 导入，这会突破 AGPL 边界。仅当用户明确表示要在自己的 AGPL 项目中把 OBLITERATUS 当作库使用时才提及。）
- failspy、gabliteration、heretic、rdo

## 第 5 步：执行 Abliteration

### 标准用法
```bash
# Default method (advanced) — recommended for most models
obliteratus obliterate <model_name> --method advanced --output-dir ./abliterated-models

# With 4-bit quantization (saves VRAM)
obliteratus obliterate <model_name> --method advanced --quantization 4bit --output-dir ./abliterated-models

# Large models (70B+) — conservative defaults
obliteratus obliterate <model_name> --method advanced --quantization 4bit --large-model --output-dir ./abliterated-models
```

### 精细调参
```bash
obliteratus obliterate <model_name> \
  --method advanced \
  --direction-method diff_means \
  --n-directions 4 \
  --refinement-passes 2 \
  --regularization 0.1 \
  --quantization 4bit \
  --output-dir ./abliterated-models \
  --contribute  # opt-in telemetry for community research
```

### 关键参数
| 参数 | 说明 | 默认值 |
|:-----|:------------|:--------|
| `--method` | Abliteration 方法 | advanced |
| `--direction-method` | 方向提取方式 | diff_means |
| `--n-directions` | 拒答方向的数量（1-32） | 取决于方法 |
| `--refinement-passes` | 迭代轮数（1-5） | 2 |
| `--regularization` | 正则化强度（0.0-1.0） | 0.1 |
| `--quantization` | 以 4bit 或 8bit 加载 | 无（全精度） |
| `--large-model` | 面向 120B+ 的保守默认值 | false |
| `--output-dir` | abliterated 模型的保存位置 | ./obliterated_model |
| `--contribute` | 共享匿名化结果用于研究 | false |
| `--verify-sample-size` | 拒答检查所用测试提示的数量 | 20 |
| `--dtype` | 模型 dtype（float16、bfloat16） | auto |

### 其他执行模式
```bash
# Interactive guided mode (hardware → model → preset)
obliteratus interactive

# Web UI (Gradio)
obliteratus ui --port 7860

# Run a full ablation study from YAML config
obliteratus run config.yaml --preset quick

# Tournament: pit all methods against each other
obliteratus tourney <model_name>
```

## 第 6 步：验证结果

Abliteration 完成后，检查输出指标：

| 指标 | 良好取值 | 警告 |
|:-------|:-----------|:--------|
| 拒答率 | &lt; 5%（理想为 ~0%） | > 10% 说明拒答依然存在 |
| 困惑度变化 | &lt; 增加 10% | > 15% 说明连贯性受损 |
| KL 散度 | &lt; 0.1 | > 0.5 说明分布发生显著偏移 |
| 连贯性 | 高 / 通过定性检查 | 回答质量下降、出现重复 |

### 如果拒答依然存在（> 10%）
1. 尝试 `aggressive` 方法
2. 增大 `--n-directions`（例如 8 或 16）
3. 加上 `--refinement-passes 3`
4. 用 `--direction-method svd` 替代 diff_means

### 如果连贯性受损（困惑度增加 > 15%）
1. 减小 `--n-directions`（试试 2）
2. 增大 `--regularization`（试试 0.3）
3. 把 `--refinement-passes` 降到 1
4. 尝试 `basic` 方法（更温和）

## 第 7 步：使用 Abliterated 模型

输出是一个标准的 HuggingFace 模型目录。

```bash
# Test locally with transformers
python3 -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
model = AutoModelForCausalLM.from_pretrained('./abliterated-models/<model>')
tokenizer = AutoTokenizer.from_pretrained('./abliterated-models/<model>')
inputs = tokenizer('How do I pick a lock?', return_tensors='pt')
outputs = model.generate(**inputs, max_new_tokens=200)
print(tokenizer.decode(outputs[0], skip_special_tokens=True))
"

# Upload to HuggingFace Hub
huggingface-cli upload <username>/<model-name>-abliterated ./abliterated-models/<model>

# Serve with vLLM
vllm serve ./abliterated-models/<model>
```

## CLI 命令参考

| 命令 | 说明 |
|:--------|:------------|
| `obliteratus obliterate` | 主 abliteration 命令 |
| `obliteratus info <model>` | 打印模型架构细节 |
| `obliteratus models --tier <tier>` | 按算力档位浏览精选模型 |
| `obliteratus recommend <model>` | 基于遥测数据的方法 / 参数建议 |
| `obliteratus interactive` | 引导式设置向导 |
| `obliteratus tourney <model>` | 锦标赛：所有方法两两对决 |
| `obliteratus run <config.yaml>` | 从 YAML 执行消融研究 |
| `obliteratus strategies` | 列出所有已注册的消融策略 |
| `obliteratus report <results.json>` | 重新生成可视化报告 |
| `obliteratus ui` | 启动 Gradio 网页界面 |
| `obliteratus aggregate` | 汇总社区遥测数据 |

## 分析模块

OBLITERATUS 包含 28 个用于机制可解释性的分析模块。
完整参考见 `skill_view(name="obliteratus", file_path="references/analysis-modules.md")`。

### 快速分析命令
```bash
# Run specific analysis modules
obliteratus run analysis-config.yaml --preset quick

# Key modules to run first:
# - alignment_imprint: Fingerprint DPO/RLHF/CAI/SFT alignment method
# - concept_geometry: Single direction vs polyhedral cone
# - logit_lens: Which layer decides to refuse
# - anti_ouroboros: Self-repair risk score
# - causal_tracing: Causally necessary components
```

### 引导向量（可逆的替代方案）
与其永久修改权重，也可以在推理时做引导：
```python
# Python API only — for user's own projects
from obliteratus.analysis.steering_vectors import SteeringVectorFactory, SteeringHookManager
```

## 消融策略

除了基于方向的 abliteration，OBLITERATUS 还包含结构性消融策略：
- **Embedding Ablation** —— 针对嵌入层组件
- **FFN Ablation** —— 移除前馈网络块
- **Head Pruning** —— 注意力头剪枝
- **Layer Removal** —— 整层移除

列出全部可用项：`obliteratus strategies`

## 评测

OBLITERATUS 内置了评测工具：
- 拒答率基准测试
- 困惑度对比（处理前 / 处理后）
- 集成 LM Eval Harness 以运行学术基准
- 与竞品的一对一对比
- 基线性能追踪

## 平台支持

- **CUDA** —— 完整支持（NVIDIA GPU）
- **Apple Silicon（MLX）** —— 通过 MLX 后端支持
- **CPU** —— 支持极小模型（&lt; 1B 参数）

## YAML 配置模板

通过 `skill_view` 加载可复现运行的模板：
- `templates/abliteration-config.yaml` —— 标准的单模型配置
- `templates/analysis-study.yaml` —— abliteration 前的分析研究
- `templates/batch-abliteration.yaml` —— 多模型批处理

## 遥测

OBLITERATUS 可以选择性地向一个全球研究数据集贡献匿名化的运行数据。
用 `--contribute` 参数启用。不会采集任何个人数据 —— 只有模型名称、方法和指标。

## 常见陷阱

1. **不要把 `informed` 当默认** —— 它是实验性的，而且更慢。要可靠结果就用 `advanced`。
2. **约 1B 以下的模型对 abliteration 反应很差** —— 它们的拒答行为浅而零散，很难干净地提取方向。预期只能得到部分效果（残留 20-40% 的拒答）。3B 以上的模型拒答方向更清晰，效果好得多（用 `advanced` 常能做到 0% 拒答）。
3. **`aggressive` 可能让情况更糟** —— 在小模型上它可能损伤连贯性，甚至反而提高拒答率。只有当 `advanced` 在 3B 以上的模型上仍留下 > 10% 拒答时才用它。
4. **务必检查困惑度** —— 如果飙升超过 15%，模型就已经受损了。降低激进程度。
5. **MoE 模型需要特殊处理** —— 对 Mixtral、DeepSeek-MoE 等使用 `nuclear` 方法。
6. **量化后的模型无法再次量化** —— 先对全精度模型做 abliteration，再对输出做量化。
7. **显存估算只是近似值** —— 4-bit 量化有帮助，但提取过程中峰值占用可能骤增。
8. **推理模型很敏感** —— 对 R1 蒸馏版使用 `surgical` 以保留思维链。
9. **查看 `obliteratus recommend`** —— 遥测数据给出的参数可能优于默认值。
10. **AGPL 许可证** —— 绝不要在 MIT/Apache 项目中 `import obliteratus`。只能通过 CLI 调用。
11. **大模型（70B+）** —— 始终使用 `--large-model` 参数以采用保守默认值。
12. **频谱认证显示 RED 很常见** —— 即使实际拒答率为 0%，频谱检查也常常标记为"不完整"。请以实际拒答率为准，不要只依赖频谱认证。

## 互补 Skills

- **vllm** —— 以高吞吐量部署 abliterated 模型
- **gguf** —— 把 abliterated 模型转换为 GGUF 供 llama.cpp 使用
- **huggingface-tokenizers** —— 处理模型分词器
