---
title: "Llama Cpp — llama.cpp 本地 GGUF 推理 + HF Hub 模型发现"
sidebar_label: "Llama Cpp"
description: "llama.cpp 本地 GGUF 推理 + HF Hub 模型发现"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Llama Cpp

llama.cpp 本地 GGUF 推理 + HF Hub 模型发现。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/mlops/llama-cpp` 安装 |
| 路径 | `optional-skills/mlops/inference/llama-cpp` |
| 版本 | `2.1.2` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖 | `llama-cpp-python>=0.2.0` |
| 平台 | linux, macos, windows |
| 标签 | `llama.cpp`, `GGUF`, `Quantization`, `Hugging Face Hub`, `CPU Inference`, `Apple Silicon`, `Edge Deployment`, `AMD GPUs`, `Intel GPUs`, `NVIDIA`, `URL-first` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# llama.cpp + GGUF {#llamacpp--gguf}

将此 skill 用于本地 GGUF 推理、量化版本选择，或为 llama.cpp 发现 Hugging Face 仓库。

## 使用时机 {#when-to-use}

- 在 CPU、Apple Silicon、CUDA、ROCm 或 Intel GPU 上运行本地模型
- 为特定的 Hugging Face 仓库找到合适的 GGUF
- 从 Hub 构建 `llama-server` 或 `llama-cli` 命令
- 在 Hub 上搜索已经支持 llama.cpp 的模型
- 列举某个仓库中可用的 `.gguf` 文件及其大小
- 根据用户的 RAM 或 VRAM 在 Q4/Q5/Q6/IQ 变体之间做出选择

## 模型发现工作流 {#model-discovery-workflow}

在要求使用 `hf`、Python 或自定义脚本之前，优先使用 URL 工作流。

1. 在 Hub 上搜索候选仓库：
   - 基础 URL：`https://huggingface.co/models?apps=llama.cpp&sort=trending`
   - 针对某个模型家族，添加 `search=<term>`
   - 当用户有大小限制时，添加 `num_parameters=min:0,max:24B` 或类似参数
2. 使用 llama.cpp 本地应用视图打开仓库：
   - `https://huggingface.co/<repo>?local-app=llama.cpp`
3. 当本地应用代码片段可见时，将其视为事实来源：
   - 复制确切的 `llama-server` 或 `llama-cli` 命令
   - 完全按照 HF 显示的内容报告推荐的量化版本
4. 以页面文本或 HTML 形式读取同一个 `?local-app=llama.cpp` URL，并提取 `Hardware compatibility` 下的部分：
   - 优先使用其中确切的量化标签和大小，而不是通用表格
   - 保留仓库特有的标签，例如 `UD-Q4_K_M` 或 `IQ4_NL_XL`
   - 如果在获取的页面源码中看不到该部分，请如实说明，并退回到 tree API 加上通用的量化指导
5. 查询 tree API 以确认实际存在哪些文件：
   - `https://huggingface.co/api/models/<repo>/tree/main?recursive=true`
   - 保留 `type` 为 `file` 且 `path` 以 `.gguf` 结尾的条目
   - 将 `path` 和 `size` 作为文件名和字节大小的事实来源
   - 将量化检查点与 `mmproj-*.gguf` 投影器文件和 `BF16/` 分片文件区分开
   - 仅将 `https://huggingface.co/<repo>/tree/main` 作为供人查看的备选方案
6. 如果本地应用代码片段无法以文本形式看到，就根据仓库加上所选的量化版本重建命令：
   - 简写形式的量化选择：`llama-server -hf <repo>:<QUANT>`
   - 精确文件的备选方案：`llama-server --hf-repo <repo> --hf-file <filename.gguf>`
7. 只有当仓库尚未提供 GGUF 文件时，才建议从 Transformers 权重进行转换。

## 快速开始 {#quick-start}

### 安装 llama.cpp {#install-llamacpp}

```bash
# macOS / Linux (simplest)
brew install llama.cpp
```

```bash
winget install llama.cpp
```

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build
cmake --build build --config Release
```

### 直接从 Hugging Face Hub 运行 {#run-directly-from-the-hugging-face-hub}

```bash
llama-cli -hf bartowski/Llama-3.2-3B-Instruct-GGUF:Q8_0
```

```bash
llama-server -hf bartowski/Llama-3.2-3B-Instruct-GGUF:Q8_0
```

### 从 Hub 运行一个确切的 GGUF 文件 {#run-an-exact-gguf-file-from-the-hub}

当 tree API 显示自定义的文件命名，或缺少确切的 HF 代码片段时，使用此方法。

```bash
llama-server \
    --hf-repo microsoft/Phi-3-mini-4k-instruct-gguf \
    --hf-file Phi-3-mini-4k-instruct-q4.gguf \
    -c 4096
```

### OpenAI 兼容服务器检查 {#openai-compatible-server-check}

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Write a limerick about Python exceptions"}
    ]
  }'
```

## Python 绑定（llama-cpp-python） {#python-bindings-llama-cpp-python}

`pip install llama-cpp-python`（CUDA：`CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --force-reinstall --no-cache-dir`；Metal：`CMAKE_ARGS="-DGGML_METAL=on" ...`）。

### 基础生成 {#basic-generation}

```python
from llama_cpp import Llama

llm = Llama(
    model_path="./model-q4_k_m.gguf",
    n_ctx=4096,
    n_gpu_layers=35,     # 0 for CPU, 99 to offload everything
    n_threads=8,
)

out = llm("What is machine learning?", max_tokens=256, temperature=0.7)
print(out["choices"][0]["text"])
```

### 对话 + 流式输出 {#chat--streaming}

```python
llm = Llama(
    model_path="./model-q4_k_m.gguf",
    n_ctx=4096,
    n_gpu_layers=35,
    chat_format="llama-3",   # or "chatml", "mistral", etc.
)

resp = llm.create_chat_completion(
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is Python?"},
    ],
    max_tokens=256,
)
print(resp["choices"][0]["message"]["content"])

# Streaming
for chunk in llm("Explain quantum computing:", max_tokens=256, stream=True):
    print(chunk["choices"][0]["text"], end="", flush=True)
```

### 嵌入 {#embeddings}

```python
llm = Llama(model_path="./model-q4_k_m.gguf", embedding=True, n_gpu_layers=35)
vec = llm.embed("This is a test sentence.")
print(f"Embedding dimension: {len(vec)}")
```

你也可以直接从 Hub 加载 GGUF：

```python
llm = Llama.from_pretrained(
    repo_id="bartowski/Llama-3.2-3B-Instruct-GGUF",
    filename="*Q4_K_M.gguf",
    n_gpu_layers=35,
)
```

## 选择量化版本 {#choosing-a-quant}

首先参考 Hub 页面，其次才是通用的经验法则。

- 优先选择 HF 标记为与用户硬件配置兼容的确切量化版本。
- 对于一般对话，从 `Q4_K_M` 开始。
- 对于代码或技术性工作，如果内存允许，优先选择 `Q5_K_M` 或 `Q6_K`。
- 对于非常紧张的 RAM 预算，只有在用户明确将“能装下”置于质量之上时，才考虑 `Q3_K_M`、`IQ` 变体或 `Q2` 变体。
- 对于多模态仓库，单独提及 `mmproj-*.gguf`。投影器不是主模型文件。
- 不要规范化仓库原生的标签。如果页面上写的是 `UD-Q4_K_M`，就报告 `UD-Q4_K_M`。

## 从仓库中提取可用的 GGUF {#extracting-available-ggufs-from-a-repo}

当用户询问存在哪些 GGUF 时，返回：

- 文件名
- 文件大小
- 量化标签
- 它是主模型还是辅助投影器

除非被要求，否则忽略：

- README
- BF16 分片文件
- imatrix 数据块或校准产物

此步骤使用 tree API：

- `https://huggingface.co/api/models/<repo>/tree/main?recursive=true`

对于像 `unsloth/Qwen3.6-35B-A3B-GGUF` 这样的仓库，本地应用页面可以显示诸如 `UD-Q4_K_M`、`UD-Q5_K_M`、`UD-Q6_K` 和 `Q8_0` 之类的量化标签，而 tree API 则会给出确切的文件路径，例如 `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` 和 `Qwen3.6-35B-A3B-Q8_0.gguf`，并附带字节大小。使用 tree API 将量化标签转换为确切的文件名。

## 搜索模式 {#search-patterns}

直接使用以下 URL 形式：

```text
https://huggingface.co/models?apps=llama.cpp&sort=trending
https://huggingface.co/models?search=<term>&apps=llama.cpp&sort=trending
https://huggingface.co/models?search=<term>&apps=llama.cpp&num_parameters=min:0,max:24B&sort=trending
https://huggingface.co/<repo>?local-app=llama.cpp
https://huggingface.co/api/models/<repo>/tree/main?recursive=true
https://huggingface.co/<repo>/tree/main
```

## 输出格式 {#output-format}

回答发现类请求时，优先使用类似下面这样紧凑的结构化结果：

```text
Repo: <repo>
Recommended quant from HF: <label> (<size>)
llama-server: <command>
Other GGUFs:
- <filename> - <size>
- <filename> - <size>
Source URLs:
- <local-app URL>
- <tree API URL>
```

## 参考资料 {#references}

- **[hub-discovery.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/llama-cpp/references/hub-discovery.md)** - 仅基于 URL 的 Hugging Face 工作流、搜索模式、GGUF 提取以及命令重建
- **[advanced-usage.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/llama-cpp/references/advanced-usage.md)** —— 推测解码、批量推理、语法约束生成、LoRA、多 GPU、自定义构建、基准测试脚本
- **[quantization.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/llama-cpp/references/quantization.md)** —— 量化质量的权衡、何时使用 Q4/Q5/Q6/IQ、模型大小扩展、imatrix
- **[server.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/llama-cpp/references/server.md)** —— 直接从 Hub 启动服务器、OpenAI API 端点、Docker 部署、NGINX 负载均衡、监控
- **[optimization.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/llama-cpp/references/optimization.md)** —— CPU 线程、BLAS、GPU 卸载的经验法则、批处理调优、基准测试
- **[troubleshooting.md](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/inference/llama-cpp/references/troubleshooting.md)** —— 安装/转换/量化/推理/服务器问题、Apple Silicon、调试

## 资源 {#resources}

- **GitHub**：https://github.com/ggml-org/llama.cpp
- **Hugging Face GGUF + llama.cpp 文档**：https://huggingface.co/docs/hub/gguf-llamacpp
- **Hugging Face 本地应用文档**：https://huggingface.co/docs/hub/main/local-apps
- **Hugging Face 本地 Agent 文档**：https://huggingface.co/docs/hub/agents-local
- **本地应用页面示例**：https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF?local-app=llama.cpp
- **tree API 示例**：https://huggingface.co/api/models/unsloth/Qwen3.6-35B-A3B-GGUF/tree/main?recursive=true
- **llama.cpp 搜索示例**：https://huggingface.co/models?num_parameters=min:0,max:24B&apps=llama.cpp&sort=trending
- **许可证**：MIT
