---
title: "Unsloth — Unsloth：2-5倍更快的 LoRA/QLoRA 微调，更少显存"
sidebar_label: "Unsloth"
description: "Unsloth：2-5倍更快的 LoRA/QLoRA 微调，更少显存"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Unsloth

Unsloth：2-5倍更快的 LoRA/QLoRA 微调，更少显存。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/mlops/unsloth` 安装 |
| 路径 | `optional-skills/mlops/training/unsloth` |
| 版本 | `1.0.0` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖项 | `unsloth`, `torch`, `transformers`, `trl`, `datasets`, `peft` |
| 平台 | linux, macos |
| 标签 | `Fine-Tuning`, `Unsloth`, `Fast Training`, `LoRA`, `QLoRA`, `Memory-Efficient`, `Optimization`, `Llama`, `Mistral`, `Gemma`, `Qwen` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Unsloth Skill

基于官方文档生成的 unsloth 开发综合辅助。

## 何时使用此 Skill

以下情况应触发此 skill：
- 使用 unsloth 进行开发
- 询问 unsloth 功能或 API
- 实现 unsloth 解决方案
- 调试 unsloth 代码
- 学习 unsloth 最佳实践

## 快速参考

### 常用模式

**模式 1：** 用 `FastModel.from_pretrained` 加载模型。`load_in_4bit = True` 为 4-bit 量化；`False` 表示 16-bit LoRA。要做全参数微调，请设置 `full_finetuning = True`。

```
model, tokenizer = FastModel.from_pretrained(
    model_name = "unsloth/gpt-oss-20b",
    max_seq_length = 2048, # Choose any for long context!
    load_in_4bit = True,  # 4-bit quantization. False = 16-bit LoRA.
    load_in_8bit = False, # 8-bit quantization
    load_in_16bit = False, # [NEW!] 16-bit LoRA
    full_finetuning = False, # Use for full fine-tuning.
    # token = "hf_...", # use one if using gated models
)
```

**模式 2：** 用 `get_peft_model` 添加 LoRA 适配器。`use_gradient_checkpointing = "unsloth"` 可少用 30% 显存，并支持 2 倍大的批次。

```
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj",],
    lora_alpha = 16,
    lora_dropout = 0, # Supports any, but = 0 is optimized
    bias = "none",    # Supports any, but = "none" is optimized
    # [NEW] "unsloth" uses 30% less VRAM, fits 2x larger batch sizes!
    use_gradient_checkpointing = "unsloth", # True or "unsloth" for very long context
    random_state = 3407,
    max_seq_length = max_seq_length,
    use_rslora = False,  # We support rank stabilized LoRA
    loftq_config = None, # And LoftQ
)
```

**模式 3：** 用 `get_chat_template` 为你的 tokenizer 应用正确的对话模板。

```
tokenizer = get_chat_template(
      tokenizer,
      chat_template = "gemma-3", # change this to the right chat_template name
  )
```

**模式 4：** 如果你的数据集使用 ShareGPT 的 `from`/`value` 键，而不是 ChatML 的 `role`/`content` 格式，请先用 `standardize_sharegpt` 转换。

```
from unsloth.chat_templates import standardize_sharegpt
dataset = standardize_sharegpt(dataset)
```

**模式 5：** 若只想在助手回合上训练，请用 `train_on_responses_only` 包装 trainer，并定义指令部分与助手部分。下面给出的是 Llama 3.x / 4 的形式。

```
from unsloth.chat_templates import train_on_responses_only
trainer = train_on_responses_only(
    trainer,
    instruction_part = "<|start_header_id|>user<|end_header_id|>\n\n",
    response_part = "<|start_header_id|>assistant<|end_header_id|>\n\n",
)
```

**模式 6：** Unsloth 本身就提供原生 2 倍速推理，因此请始终调用 `FastLanguageModel.for_inference(model)`。想要更长的回复就调高 `max_new_tokens`。

```
FastLanguageModel.for_inference(model)
```

**模式 7：** 若要使用 vLLM 后端生成，请在加载时设置 `fast_inference = True`，并调用 `model.fast_generate`。

```
from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Llama-3.2-3B-Instruct",
    fast_inference = True,
)
model.fast_generate(["Hello!"])
```

**模式 8：** 用 `save_pretrained_merged` 保存合并后的权重，或用 `save_pretrained_gguf` 配合某种量化方法导出 GGUF。

```
# Save to 16-bit precision
model.save_pretrained_merged("model", tokenizer, save_method="merged_16bit")
model.save_pretrained_gguf("directory", tokenizer, quantization_method = "q4_k_m")
```

以上模式为精简版；完整文档请阅读 `references/` 中的文件。

## 参考文件

此 skill 在 `references/` 中包含完整文档：

- **llms-txt.md** - Llms-Txt 文档
- **llms-full.md** - 上游 llms-full.txt 完整文档
- **llms.md** - 上游 llms.txt 链接索引

需要详细信息时，使用 `view` 读取特定参考文件。

## 使用此 Skill

### 面向初学者
从 getting_started 或 tutorials 参考文件入手，了解基础概念。

### 针对特定功能
使用相应分类的参考文件（api、guides 等）获取详细信息。

### 获取代码示例
上方快速参考部分包含从官方文档中提取的常用模式。

## 资源

### references/
从官方来源提取的有组织文档，包含：
- 详细说明
- 带语言标注的代码示例
- 原始文档链接
- 便于快速导航的目录

### scripts/
在此添加用于常见自动化任务的辅助脚本。

### assets/
在此添加模板、样板代码或示例项目。

## 说明

- 此 skill 由官方文档自动生成
- 参考文件保留了源文档的结构和示例
- 代码示例包含语言检测以提供更好的语法高亮
- 快速参考模式从文档中的常见用法示例中提取

## 更新

如需使用最新文档刷新此 skill：
1. 使用相同配置重新运行爬取程序
2. Skill 将以最新信息重新构建

<!-- Trigger re-upload 1763621536 -->