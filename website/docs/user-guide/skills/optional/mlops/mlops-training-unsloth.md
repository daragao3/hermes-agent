---
title: "Unsloth — Unsloth: 2-5x faster LoRA/QLoRA fine-tuning, less VRAM"
sidebar_label: "Unsloth"
description: "Unsloth: 2-5x faster LoRA/QLoRA fine-tuning, less VRAM"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Unsloth

Unsloth: 2-5x faster LoRA/QLoRA fine-tuning, less VRAM.

## Skill metadata

| | |
|---|---|
| Source | Optional — install with `hermes skills install official/mlops/unsloth` |
| Path | `optional-skills/mlops/training/unsloth` |
| Version | `1.0.0` |
| Author | Orchestra Research |
| License | MIT |
| Dependencies | `unsloth`, `torch`, `transformers`, `trl`, `datasets`, `peft` |
| Platforms | linux, macos |
| Tags | `Fine-Tuning`, `Unsloth`, `Fast Training`, `LoRA`, `QLoRA`, `Memory-Efficient`, `Optimization`, `Llama`, `Mistral`, `Gemma`, `Qwen` |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Unsloth Skill

Assistance with unsloth development, generated from official documentation.

## When to Use This Skill

This skill should be triggered when:
- Working with unsloth
- Asking about unsloth features or APIs
- Implementing unsloth solutions
- Debugging unsloth code
- Learning unsloth best practices

## Quick Reference

### Common Patterns

**Pattern 1:** Load a model with `FastModel.from_pretrained`. `load_in_4bit = True` gives 4-bit quantization; `False` means 16-bit LoRA. Set `full_finetuning = True` for full fine-tuning.

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

**Pattern 2:** Add LoRA adapters with `get_peft_model`. `use_gradient_checkpointing = "unsloth"` uses 30% less VRAM and fits 2x larger batch sizes.

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

**Pattern 3:** Use `get_chat_template` to apply the right chat template to your tokenizer.

```
tokenizer = get_chat_template(
      tokenizer,
      chat_template = "gemma-3", # change this to the right chat_template name
  )
```

**Pattern 4:** If your dataset uses the ShareGPT `from`/`value` keys instead of the ChatML `role`/`content` format, convert it first with `standardize_sharegpt`.

```
from unsloth.chat_templates import standardize_sharegpt
dataset = standardize_sharegpt(dataset)
```

**Pattern 5:** To train on the assistant turns only, wrap the trainer with `train_on_responses_only` and define the instruction and assistant parts. The parts below are the Llama 3.x / 4 form.

```
from unsloth.chat_templates import train_on_responses_only
trainer = train_on_responses_only(
    trainer,
    instruction_part = "<|start_header_id|>user<|end_header_id|>\n\n",
    response_part = "<|start_header_id|>assistant<|end_header_id|>\n\n",
)
```

**Pattern 6:** Unsloth provides 2x faster inference natively, so always call `FastLanguageModel.for_inference(model)`. Raise `max_new_tokens` for longer responses.

```
FastLanguageModel.for_inference(model)
```

**Pattern 7:** For vLLM-backed generation, load with `fast_inference = True` and call `model.fast_generate`.

```
from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Llama-3.2-3B-Instruct",
    fast_inference = True,
)
model.fast_generate(["Hello!"])
```

**Pattern 8:** Save merged weights with `save_pretrained_merged`, or export GGUF with `save_pretrained_gguf` and a quantization method.

```
# Save to 16-bit precision
model.save_pretrained_merged("model", tokenizer, save_method="merged_16bit")
model.save_pretrained_gguf("directory", tokenizer, quantization_method = "q4_k_m")
```

Patterns are condensed from `references/`; read those files for the full
documentation.

## Reference Files

This skill includes full documentation in `references/`:

- **llms-txt.md** - Llms-Txt documentation
- **llms-full.md** - Full upstream llms-full.txt documentation
- **llms.md** - Upstream llms.txt link index

Use `view` to read specific reference files when detailed information is needed.

## Working with This Skill

### For Beginners
Start with the getting_started or tutorials reference files for foundational concepts.

### For Specific Features
Use the appropriate category reference file (api, guides, etc.) for detailed information.

### For Code Examples
The quick reference section above contains common patterns extracted from the official docs.

## Resources

### references/
Organized documentation extracted from official sources. These files contain:
- Detailed explanations
- Code examples with language annotations
- Links to original documentation
- Table of contents for quick navigation

### scripts/
Add helper scripts here for common automation tasks.

### assets/
Add templates, boilerplate, or example projects here.

## Notes

- This skill was automatically generated from official documentation
- Reference files preserve the structure and examples from source docs
- Code examples include language detection for better syntax highlighting
- Quick reference patterns are extracted from common usage examples in the docs

## Updating

To refresh this skill with updated documentation:
1. Re-run the scraper with the same configuration
2. The skill will be rebuilt with the latest information

<!-- Trigger re-upload 1763621536 -->
