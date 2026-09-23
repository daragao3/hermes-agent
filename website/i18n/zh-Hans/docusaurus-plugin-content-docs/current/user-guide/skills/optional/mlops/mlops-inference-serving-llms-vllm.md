---
title: "Serving Llms Vllm —— vLLM：高吞吐 LLM 服务、OpenAI API、量化"
sidebar_label: "Serving Llms Vllm"
description: "vLLM：高吞吐 LLM 服务、OpenAI API、量化"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Serving Llms Vllm

vLLM：高吞吐 LLM 服务、OpenAI API、量化。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/mlops/serving-llms-vllm` 安装 |
| 路径 | `optional-skills/mlops/inference/serving-llms-vllm` |
| 版本 | `1.0.1` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖项 | `vllm`, `torch`, `transformers` |
| 平台 | linux, macos |
| 标签 | `vLLM`, `Inference Serving`, `PagedAttention`, `Continuous Batching`, `High Throughput`, `Production`, `OpenAI API`, `Quantization`, `Tensor Parallelism` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# vLLM - 高性能 LLM 服务

## 何时使用 {#when-to-use}

在部署生产环境 LLM API、优化推理延迟/吞吐量，或在 GPU 显存有限的情况下提供模型服务时使用。支持 OpenAI 兼容端点、量化（GPTQ/AWQ/FP8）以及张量并行。

## 快速开始 {#quick-start}

vLLM 通过 PagedAttention（基于块的 KV 缓存）和连续批处理（混合 prefill/decode 请求），实现了比标准 transformers 高 24 倍的吞吐量。

**安装**：
```bash
pip install vllm
```

**基础离线推理**：
```python
from vllm import LLM, SamplingParams

llm = LLM(model="meta-llama/Meta-Llama-3-8B-Instruct")
sampling = SamplingParams(temperature=0.7, max_tokens=256)

outputs = llm.generate(["Explain quantum computing"], sampling)
print(outputs[0].outputs[0].text)
```

**OpenAI 兼容服务器**：
```bash
vllm serve meta-llama/Meta-Llama-3-8B-Instruct

# 使用 OpenAI SDK 查询
python -c "
from openai import OpenAI
client = OpenAI(base_url='http://localhost:8000/v1', api_key='EMPTY')
print(client.chat.completions.create(
    model='meta-llama/Meta-Llama-3-8B-Instruct',
    messages=[{'role': 'user', 'content': 'Hello!'}]
).choices[0].message.content)
"
```

## 常见工作流 {#common-workflows}

### 工作流 1：生产环境 API 部署 {#workflow-1-production-api-deployment}

复制此检查清单并跟踪进度：

```
Deployment Progress:
- [ ] Step 1: Configure server settings
- [ ] Step 2: Test with limited traffic
- [ ] Step 3: Enable monitoring
- [ ] Step 4: Deploy to production
- [ ] Step 5: Verify performance metrics
```

**步骤 1：配置服务器设置**

根据你的模型大小选择配置：

```bash
# 单 GPU 上的 7B-13B 模型
vllm serve meta-llama/Meta-Llama-3-8B-Instruct \
  --gpu-memory-utilization 0.9 \
  --max-model-len 8192 \
  --port 8000

# 使用张量并行的 30B-70B 模型
vllm serve meta-llama/Meta-Llama-3-70B-Instruct \
  --tensor-parallel-size 4 \
  --gpu-memory-utilization 0.9 \
  --quantization awq \
  --port 8000

# 启用缓存的生产环境（Prometheus 指标会自动
# 暴露在 API 端口的 /metrics 上）
vllm serve meta-llama/Meta-Llama-3-8B-Instruct \
  --gpu-memory-utilization 0.9 \
  --enable-prefix-caching \
  --port 8000 \
  --host 0.0.0.0
```

**步骤 2：用有限流量进行测试**

上线前先运行负载测试：

```bash
# 安装负载测试工具
pip install locust

# 创建包含示例请求的 test_load.py
# 运行：locust -f test_load.py --host http://localhost:8000
```

验证 TTFT（首 token 时间）&lt; 500ms，且吞吐量 > 100 req/sec。

**步骤 3：启用监控**

vLLM 在 API 端口（默认 8000）的 `/metrics` 上暴露 Prometheus 指标：

```bash
curl http://localhost:8000/metrics | grep vllm
```

需要监控的关键指标：
- `vllm:time_to_first_token_seconds` - 延迟
- `vllm:num_requests_running` - 活跃请求数
- `vllm:gpu_cache_usage_perc` - KV 缓存利用率

**步骤 4：部署到生产环境**

使用 Docker 以保证部署一致性：

```bash
# 在 Docker 中运行 vLLM
docker run --gpus all -p 8000:8000 \
  vllm/vllm-openai:latest \
  --model meta-llama/Meta-Llama-3-8B-Instruct \
  --gpu-memory-utilization 0.9 \
  --enable-prefix-caching
```

**步骤 5：验证性能指标**

检查部署是否达到目标：
- TTFT &lt; 500ms（针对短提示词）
- 吞吐量 > 目标 req/sec
- GPU 利用率 > 80%
- 日志中没有 OOM 错误

### 工作流 2：离线批量推理 {#workflow-2-offline-batch-inference}

用于在没有服务器开销的情况下处理大型数据集。

复制此检查清单：

```
Batch Processing:
- [ ] Step 1: Prepare input data
- [ ] Step 2: Configure LLM engine
- [ ] Step 3: Run batch inference
- [ ] Step 4: Process results
```

**步骤 1：准备输入数据**

```python
# 从文件加载提示词
prompts = []
with open("prompts.txt") as f:
    prompts = [line.strip() for line in f]

print(f"Loaded {len(prompts)} prompts")
```

**步骤 2：配置 LLM 引擎**

```python
from vllm import LLM, SamplingParams

llm = LLM(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    tensor_parallel_size=2,  # 使用 2 块 GPU
    gpu_memory_utilization=0.9,
    max_model_len=4096
)

sampling = SamplingParams(
    temperature=0.7,
    top_p=0.95,
    max_tokens=512,
    stop=["</s>", "\n\n"]
)
```

**步骤 3：运行批量推理**

vLLM 会自动对请求进行批处理以提高效率：

```python
# 一次调用处理所有提示词
outputs = llm.generate(prompts, sampling)

# vLLM 在内部处理批处理
# 无需手动切分提示词
```

**步骤 4：处理结果**

```python
# 提取生成的文本
results = []
for output in outputs:
    prompt = output.prompt
    generated = output.outputs[0].text
    results.append({
        "prompt": prompt,
        "generated": generated,
        "tokens": len(output.outputs[0].token_ids)
    })

# 保存到文件
import json
with open("results.jsonl", "w") as f:
    for result in results:
        f.write(json.dumps(result) + "\n")

print(f"Processed {len(results)} prompts")
```

### 工作流 3：量化模型服务 {#workflow-3-quantized-model-serving}

在有限的 GPU 显存中装下大模型。

```
Quantization Setup:
- [ ] Step 1: Choose quantization method
- [ ] Step 2: Find or create quantized model
- [ ] Step 3: Launch with quantization flag
- [ ] Step 4: Verify accuracy
```

**步骤 1：选择量化方法**

- **AWQ**：最适合 70B 模型，精度损失极小
- **GPTQ**：模型支持广泛，压缩效果好
- **FP8**：在 H100 GPU 上最快

**步骤 2：查找或创建量化模型**

使用 HuggingFace 上预先量化好的模型：

```bash
# 搜索 AWQ 模型
# 示例：TheBloke/Llama-2-70B-AWQ
```

**步骤 3：带量化参数启动**

```bash
# 使用预量化模型
vllm serve TheBloke/Llama-2-70B-AWQ \
  --quantization awq \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.95

# 结果：70B 模型只需约 40GB 显存
```

**步骤 4：验证精度**

测试输出是否符合预期质量：

```python
# 比较量化与未量化模型的响应
# 验证特定任务上的性能没有变化
```

## 何时使用 vs 替代方案 {#when-to-use-vs-alternatives}

**以下情况使用 vLLM：**
- 部署生产环境 LLM API（100+ req/sec）
- 提供 OpenAI 兼容端点
- GPU 显存有限但需要使用大模型
- 多用户应用（聊天机器人、助手）
- 需要在高吞吐的同时保持低延迟

**以下情况改用替代方案：**
- **llama.cpp**：CPU/边缘推理，单用户
- **HuggingFace transformers**：研究、原型开发、一次性生成
- **TensorRT-LLM**：仅限 NVIDIA，需要绝对的极致性能
- **Text-Generation-Inference**：已身处 HuggingFace 生态

## 常见问题 {#common-issues}

**问题：加载模型时显存不足**

降低显存占用：
```bash
vllm serve MODEL \
  --gpu-memory-utilization 0.7 \
  --max-model-len 4096
```

或者使用量化：
```bash
vllm serve MODEL --quantization awq
```

**问题：首 token 很慢（TTFT > 1 秒）**

为重复的提示词启用前缀缓存：
```bash
vllm serve MODEL --enable-prefix-caching
```

对于长提示词，启用分块 prefill：
```bash
vllm serve MODEL --enable-chunked-prefill
```

**问题：找不到模型错误**

对自定义模型使用 `--trust-remote-code`：
```bash
vllm serve MODEL --trust-remote-code
```

**问题：吞吐量低（&lt;50 req/sec）**

增加并发序列数：
```bash
vllm serve MODEL --max-num-seqs 512
```

用 `nvidia-smi` 检查 GPU 利用率——应当 >80%。

**问题：推理比预期慢**

确认张量并行使用的 GPU 数量是 2 的幂：
```bash
vllm serve MODEL --tensor-parallel-size 4  # 不要用 3
```

启用推测解码以加快生成速度（以 JSON 形式传入配置；
`--speculative-model` 已被移除，改用 `--speculative-config`）：
```bash
vllm serve MODEL \
  --speculative-config '{"model": "DRAFT_MODEL", "num_speculative_tokens": 5, "method": "draft_model"}'
```

## 进阶主题 {#advanced-topics}

**服务器部署模式**：Docker、Kubernetes 和负载均衡配置请参阅 [references/server-deployment.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/serving-llms-vllm/references/server-deployment.md)。

**性能优化**：PagedAttention 调优、连续批处理细节和基准测试结果请参阅 [references/optimization.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/serving-llms-vllm/references/optimization.md)。

**量化指南**：AWQ/GPTQ/FP8 设置、模型准备和精度对比请参阅 [references/quantization.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/serving-llms-vllm/references/quantization.md)。

**故障排查**：详细的错误信息、调试步骤和性能诊断请参阅 [references/troubleshooting.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/serving-llms-vllm/references/troubleshooting.md)。

## 硬件要求 {#hardware-requirements}

- **小模型（7B-13B）**：1x A10（24GB）或 A100（40GB）
- **中等模型（30B-40B）**：2x A100（40GB），使用张量并行
- **大模型（70B+）**：4x A100（40GB）或 2x A100（80GB），使用 AWQ/GPTQ

支持的平台：NVIDIA（主要）、AMD ROCm、Intel GPU、TPU

## 资源 {#resources}

- 官方文档：https://docs.vllm.ai
- GitHub：https://github.com/vllm-project/vllm
- 论文："Efficient Memory Management for Large Language Model Serving with PagedAttention"（SOSP 2023）
- 社区：https://discuss.vllm.ai
