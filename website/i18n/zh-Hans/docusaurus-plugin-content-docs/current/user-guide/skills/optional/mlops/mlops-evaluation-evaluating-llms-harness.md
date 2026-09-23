---
title: "Evaluating Llms Harness — lm-eval-harness：对 LLM 进行基准测试（MMLU、GSM8K 等）"
sidebar_label: "Evaluating Llms Harness"
description: "lm-eval-harness：对 LLM 进行基准测试（MMLU、GSM8K 等）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Evaluating Llms Harness

lm-eval-harness：对 LLM 进行基准测试（MMLU、GSM8K 等）。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/mlops/evaluating-llms-harness` 安装 |
| 路径 | `optional-skills/mlops/evaluation/evaluating-llms-harness` |
| 版本 | `1.0.1` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖 | `lm-eval`, `transformers`, `vllm` |
| 平台 | linux, macos |
| 标签 | `Evaluation`, `LM Evaluation Harness`, `Benchmarking`, `MMLU`, `HumanEval`, `GSM8K`, `EleutherAI`, `Model Quality`, `Academic Benchmarks`, `Industry Standard` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# lm-evaluation-harness - LLM 基准测试 {#lm-evaluation-harness---llm-benchmarking}

## 内容概览 {#whats-inside}

在 60+ 个学术基准（MMLU、HumanEval、GSM8K、TruthfulQA、HellaSwag）上评估 LLM。适用于对模型质量进行基准测试、比较模型、报告学术结果或跟踪训练进度。这是 EleutherAI、HuggingFace 及各大实验室使用的行业标准。支持 HuggingFace、vLLM 和 API。

## 快速开始 {#quick-start}

lm-evaluation-harness 使用标准化的提示词和指标，在 60+ 个学术基准上评估 LLM。

**安装**：
```bash
pip install lm-eval
```

**评估任意 HuggingFace 模型**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu,gsm8k,hellaswag \
  --device cuda:0 \
  --batch_size 8
```

**查看可用任务**：
```bash
lm-eval ls tasks
```

## 常见工作流 {#common-workflows}

### 工作流 1：标准基准评估 {#workflow-1-standard-benchmark-evaluation}

在核心基准（MMLU、GSM8K、HumanEval）上评估模型。

复制这份清单：

```
Benchmark Evaluation:
- [ ] Step 1: Choose benchmark suite
- [ ] Step 2: Configure model
- [ ] Step 3: Run evaluation
- [ ] Step 4: Analyze results
```

**第 1 步：选择基准套件**

**核心推理基准**：
- **MMLU**（Massive Multitask Language Understanding）——57 个学科，多项选择
- **GSM8K**——小学数学应用题
- **HellaSwag**——常识推理
- **TruthfulQA**——真实性与事实性
- **ARC**（AI2 Reasoning Challenge）——科学问题

**代码基准**：
- **HumanEval**——Python 代码生成（164 道题）
- **MBPP**（Mostly Basic Python Problems）——Python 编程

**标准套件**（推荐用于模型发布）：
```bash
--tasks mmlu,gsm8k,hellaswag,truthfulqa,arc_challenge
```

**第 2 步：配置模型**

**HuggingFace 模型**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,dtype=bfloat16 \
  --tasks mmlu \
  --device cuda:0 \
  --batch_size auto  # 自动检测最佳 batch size
```

**量化模型（4-bit/8-bit）**：
```bash
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,load_in_4bit=True \
  --tasks mmlu \
  --device cuda:0
```

**自定义检查点**：
```bash
lm_eval --model hf \
  --model_args pretrained=/path/to/my-model,tokenizer=/path/to/tokenizer \
  --tasks mmlu \
  --device cuda:0
```

**第 3 步：运行评估**

```bash
# 完整 MMLU 评估（57 个学科）
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu \
  --num_fewshot 5 \  # 5-shot 评估（标准）
  --batch_size 8 \
  --output_path results/ \
  --log_samples  # 保存每条预测

# 一次运行多个基准
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu,gsm8k,hellaswag,truthfulqa,arc_challenge \
  --num_fewshot 5 \
  --batch_size 8 \
  --output_path results/llama2-7b-eval.json
```

**第 4 步：分析结果**

结果保存在 `results/llama2-7b-eval.json`：

```json
{
  "results": {
    "mmlu": {
      "acc": 0.459,
      "acc_stderr": 0.004
    },
    "gsm8k": {
      "exact_match": 0.142,
      "exact_match_stderr": 0.006
    },
    "hellaswag": {
      "acc_norm": 0.765,
      "acc_norm_stderr": 0.004
    }
  },
  "config": {
    "model": "hf",
    "model_args": "pretrained=meta-llama/Llama-2-7b-hf",
    "num_fewshot": 5
  }
}
```

### 工作流 2：跟踪训练进度 {#workflow-2-track-training-progress}

在训练过程中评估检查点。

```
Training Progress Tracking:
- [ ] Step 1: Set up periodic evaluation
- [ ] Step 2: Choose quick benchmarks
- [ ] Step 3: Automate evaluation
- [ ] Step 4: Plot learning curves
```

**第 1 步：设置周期性评估**

每 N 个训练步评估一次：

```bash
#!/bin/bash
# eval_checkpoint.sh

CHECKPOINT_DIR=$1
STEP=$2

lm_eval --model hf \
  --model_args pretrained=$CHECKPOINT_DIR/checkpoint-$STEP \
  --tasks gsm8k,hellaswag \
  --num_fewshot 0 \  # 0-shot 以提高速度
  --batch_size 16 \
  --output_path results/step-$STEP.json
```

**第 2 步：选择快速基准**

适合频繁评估的快速基准：
- **HellaSwag**：单 GPU 约 10 分钟
- **GSM8K**：约 5 分钟
- **PIQA**：约 2 分钟

不适合频繁评估（太慢）：
- **MMLU**：约 2 小时（57 个学科）
- **HumanEval**：需要执行代码

**第 3 步：自动化评估**

与训练脚本集成：

```python
# 在训练循环中
if step % eval_interval == 0:
    model.save_pretrained(f"checkpoints/step-{step}")

    # 运行评估
    os.system(f"./eval_checkpoint.sh checkpoints step-{step}")
```

或使用 PyTorch Lightning 回调：

```python
from pytorch_lightning import Callback

class EvalHarnessCallback(Callback):
    def on_validation_epoch_end(self, trainer, pl_module):
        step = trainer.global_step
        checkpoint_path = f"checkpoints/step-{step}"

        # 保存检查点
        trainer.save_checkpoint(checkpoint_path)

        # 运行 lm-eval
        os.system(f"lm_eval --model hf --model_args pretrained={checkpoint_path} ...")
```

**第 4 步：绘制学习曲线**

```python
import json
import matplotlib.pyplot as plt

# 加载所有结果
steps = []
mmlu_scores = []

for file in sorted(glob.glob("results/step-*.json")):
    with open(file) as f:
        data = json.load(f)
        step = int(file.split("-")[1].split(".")[0])
        steps.append(step)
        mmlu_scores.append(data["results"]["mmlu"]["acc"])

# 绘图
plt.plot(steps, mmlu_scores)
plt.xlabel("Training Step")
plt.ylabel("MMLU Accuracy")
plt.title("Training Progress")
plt.savefig("training_curve.png")
```

### 工作流 3：比较多个模型 {#workflow-3-compare-multiple-models}

用于模型比较的基准套件。

```
Model Comparison:
- [ ] Step 1: Define model list
- [ ] Step 2: Run evaluations
- [ ] Step 3: Generate comparison table
```

**第 1 步：定义模型列表**

```bash
# models.txt
meta-llama/Llama-2-7b-hf
meta-llama/Llama-2-13b-hf
mistralai/Mistral-7B-v0.1
microsoft/phi-2
```

**第 2 步：运行评估**

```bash
#!/bin/bash
# eval_all_models.sh

TASKS="mmlu,gsm8k,hellaswag,truthfulqa"

while read model; do
    echo "Evaluating $model"

    # 提取模型名用作输出文件名
    model_name=$(echo $model | sed 's/\//-/g')

    lm_eval --model hf \
      --model_args pretrained=$model,dtype=bfloat16 \
      --tasks $TASKS \
      --num_fewshot 5 \
      --batch_size auto \
      --output_path results/$model_name.json

done < models.txt
```

**第 3 步：生成比较表格**

```python
import json
import pandas as pd

models = [
    "meta-llama-Llama-2-7b-hf",
    "meta-llama-Llama-2-13b-hf",
    "mistralai-Mistral-7B-v0.1",
    "microsoft-phi-2"
]

tasks = ["mmlu", "gsm8k", "hellaswag", "truthfulqa"]

results = []
for model in models:
    with open(f"results/{model}.json") as f:
        data = json.load(f)
        row = {"Model": model.replace("-", "/")}
        for task in tasks:
            # 获取每个任务的主要指标
            metrics = data["results"][task]
            if "acc" in metrics:
                row[task.upper()] = f"{metrics['acc']:.3f}"
            elif "exact_match" in metrics:
                row[task.upper()] = f"{metrics['exact_match']:.3f}"
        results.append(row)

df = pd.DataFrame(results)
print(df.to_markdown(index=False))
```

输出：
```
| Model                  | MMLU  | GSM8K | HELLASWAG | TRUTHFULQA |
|------------------------|-------|-------|-----------|------------|
| meta-llama/Llama-2-7b  | 0.459 | 0.142 | 0.765     | 0.391      |
| meta-llama/Llama-2-13b | 0.549 | 0.287 | 0.801     | 0.430      |
| mistralai/Mistral-7B   | 0.626 | 0.395 | 0.812     | 0.428      |
| microsoft/phi-2        | 0.560 | 0.613 | 0.682     | 0.447      |
```

### 工作流 4：使用 vLLM 评估（更快的推理） {#workflow-4-evaluate-with-vllm-faster-inference}

使用 vLLM 后端，评估速度提升 5-10 倍。

```
vLLM Evaluation:
- [ ] Step 1: Install vLLM
- [ ] Step 2: Configure vLLM backend
- [ ] Step 3: Run evaluation
```

**第 1 步：安装 vLLM**

```bash
pip install vllm
```

**第 2 步：配置 vLLM 后端**

```bash
lm_eval --model vllm \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,tensor_parallel_size=1,dtype=auto,gpu_memory_utilization=0.8 \
  --tasks mmlu \
  --batch_size auto
```

**第 3 步：运行评估**

vLLM 比标准 HuggingFace 快 5-10 倍：

```bash
# 标准 HF：7B 模型跑 MMLU 约需 2 小时
lm_eval --model hf \
  --model_args pretrained=meta-llama/Llama-2-7b-hf \
  --tasks mmlu \
  --batch_size 8

# vLLM：7B 模型跑 MMLU 约需 15-20 分钟
lm_eval --model vllm \
  --model_args pretrained=meta-llama/Llama-2-7b-hf,tensor_parallel_size=2 \
  --tasks mmlu \
  --batch_size auto
```

## 何时使用及替代方案 {#when-to-use-vs-alternatives}

**在以下情况使用 lm-evaluation-harness：**
- 为学术论文对模型进行基准测试
- 在标准任务上比较模型质量
- 跟踪训练进度
- 报告标准化指标（所有人都使用相同的提示词）
- 需要可复现的评估

**在以下情况改用替代方案：**
- **HELM**（Stanford）：更广泛的评估（公平性、效率、校准）
- **AlpacaEval**：使用 LLM 评审的指令遵循评估
- **MT-Bench**：多轮对话评估
- **自定义脚本**：特定领域的评估

## 常见问题 {#common-issues}

**问题：评估太慢**

使用 vLLM 后端：
```bash
lm_eval --model vllm \
  --model_args pretrained=model-name,tensor_parallel_size=2
```

或减少 few-shot 示例：
```bash
--num_fewshot 0  # 代替 5
```

或只评估 MMLU 的子集：
```bash
--tasks mmlu_stem  # 仅 STEM 学科
```

**问题：内存不足**

减小 batch size：
```bash
--batch_size 1  # 或 --batch_size auto
```

使用量化：
```bash
--model_args pretrained=model-name,load_in_8bit=True
```

启用 CPU 卸载：
```bash
--model_args pretrained=model-name,device_map=auto,offload_folder=offload
```

**问题：结果与报告的不一致**

检查 few-shot 数量：
```bash
--num_fewshot 5  # 大多数论文使用 5-shot
```

检查确切的任务名称：
```bash
--tasks mmlu  # 不是 mmlu_direct 或 mmlu_fewshot
```

确认模型与 tokenizer 匹配：
```bash
--model_args pretrained=model-name,tokenizer=same-model-name
```

**问题：HumanEval 没有执行代码**

会执行代码的任务（HumanEval、MBPP 等）受一个显式确认标志保护——你必须传入 `--confirm_run_unsafe_code` 才能运行它们：

```bash
lm_eval --model hf \
  --model_args pretrained=model-name \
  --tasks humaneval \
  --confirm_run_unsafe_code  # 运行会执行生成代码的任务时必需
```

如果没有这个标志，lm-eval 会拒绝运行该任务，而不是悄悄跳过代码执行。

## 进阶主题 {#advanced-topics}

**基准说明**：参见 [references/benchmark-guide.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/evaluation/evaluating-llms-harness/references/benchmark-guide.md)，其中详细介绍了全部 60+ 个任务、它们测量什么以及如何解读。

**自定义任务**：参见 [references/custom-tasks.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/evaluation/evaluating-llms-harness/references/custom-tasks.md)，了解如何创建特定领域的评估任务。

**API 评估**：参见 [references/api-evaluation.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/evaluation/evaluating-llms-harness/references/api-evaluation.md)，了解如何评估 OpenAI、Anthropic 及其他 API 模型。

**多 GPU 策略**：参见 [references/distributed-eval.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/evaluation/evaluating-llms-harness/references/distributed-eval.md)，了解数据并行和张量并行评估。

## 硬件要求 {#hardware-requirements}

- **GPU**：NVIDIA（CUDA 11.8+），也可在 CPU 上运行（非常慢）
- **显存**：
  - 7B 模型：16GB（bf16）或 8GB（8-bit）
  - 13B 模型：28GB（bf16）或 14GB（8-bit）
  - 70B 模型：需要多 GPU 或量化
- **耗时**（7B 模型，单张 A100）：
  - HellaSwag：10 分钟
  - GSM8K：5 分钟
  - MMLU（完整）：2 小时
  - HumanEval：20 分钟

## 资源 {#resources}

- GitHub：https://github.com/EleutherAI/lm-evaluation-harness
- 文档：https://github.com/EleutherAI/lm-evaluation-harness/tree/main/docs
- 任务库：60+ 个任务，包括 MMLU、GSM8K、HumanEval、TruthfulQA、HellaSwag、ARC、WinoGrande 等
- 排行榜：https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard（使用此 harness）
