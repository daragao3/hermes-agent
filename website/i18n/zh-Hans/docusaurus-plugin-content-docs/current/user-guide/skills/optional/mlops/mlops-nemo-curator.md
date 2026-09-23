---
title: "Nemo Curator —— 整理 LLM 训练数据：去重、过滤、PII 脱敏"
sidebar_label: "Nemo Curator"
description: "整理 LLM 训练数据：去重、过滤、PII 脱敏"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Nemo Curator

整理 LLM 训练数据：去重、过滤、PII 脱敏。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/mlops/nemo-curator` 安装 |
| 路径 | `optional-skills/mlops/nemo-curator` |
| 版本 | `1.0.1` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖项 | `nemo-curator`, `cudf`, `dask`, `rapids` |
| 平台 | linux, macos |
| 标签 | `Data Processing`, `NeMo Curator`, `Data Curation`, `GPU Acceleration`, `Deduplication`, `Quality Filtering`, `NVIDIA`, `RAPIDS`, `PII Redaction`, `Multimodal`, `LLM Training Data` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# NeMo Curator - GPU 加速数据整理

NVIDIA 用于为 LLM 准备高质量训练数据的工具包。

## 何时使用 NeMo Curator

**在以下情况下使用 NeMo Curator：**
- 从网络抓取数据（Common Crawl）准备 LLM 训练数据
- 需要快速去重（比 CPU 快 16×）
- 整理多模态数据集（文本、图像、视频、音频）
- 过滤低质量或有害内容
- 跨 GPU 集群扩展数据处理

**性能**：
- **16× 更快**的模糊去重（8TB RedPajama v2）
- **降低 40% TCO**（总拥有成本），优于 CPU 方案
- **近线性扩展**，跨 GPU 节点

**以下情况请使用替代方案**：
- **datatrove**：基于 CPU 的开源数据处理
- **dolma**：Allen AI 的数据工具包
- **Ray Data**：通用 ML 数据处理（无数据整理专项功能）

## 快速开始

### 安装

```bash
# NeMo Curator 1.x 使用 uv 安装。extras 使用连字符（PyPI 规范化形式）：
#   text-cuda12 / text-cpu（以及 image/video/audio/math 变体），或 `all`。

# 文本整理（CUDA 12）
uv pip install "nemo-curator[text-cuda12]"

# 所有模态
uv pip install "nemo-curator[all]"

# 仅 CPU 文本整理（较慢）
uv pip install "nemo-curator[text-cpu]"
```

### 基础文本整理流水线

> **主版本重写（1.x）：** NeMo Curator 已围绕**基于 Ray 的流水线/阶段（pipeline/stage）架构**重写。0.x 中 `DocumentDataset` + `nemo_curator.modules.*` / `ScoreFilter` / `Modify` 这种"对数据集调用对象"的 API 已被移除。在 1.x 中，你需要将 `ProcessingStage` 组合成一个 `Pipeline`，再用执行器（executor）运行它。具体的阶段与导入接口因模态而异——请将本 skill 下文中的示例视为**概念性**的（0.x 风格），并参照当前的
> [quickstart](https://github.com/NVIDIA-NeMo/Curator/blob/main/tutorials/quickstart.py)
> 和[文本指南](https://docs.nvidia.com/nemo/curator/latest/get-started/text)获取准确的 1.x API，而不要逐字复制其中的导入语句。

1.x 流水线的大致形态（来自上游 quickstart）：

```python
from nemo_curator.pipeline import Pipeline
from nemo_curator.stages.base import ProcessingStage
from nemo_curator.stages.resources import Resources
from nemo_curator.backends.xenna import XennaExecutor
from nemo_curator.core.client import RayClient

# 1. 定义/组合各阶段（加载 -> 过滤 -> 去重 -> 分类 -> 写出）。
#    每个阶段声明自己的 Resources（CPU 核心数、GPU 显存、副本数）。
pipeline = Pipeline(name="curation", stages=[...])

# 2. 使用执行器运行（基于 Ray）。
client = RayClient()
client.start()
pipeline.run(XennaExecutor())
client.stop()
```

后续章节中的 0.x 风格代码片段用于说明各项*概念*（质量过滤、精确/模糊/语义去重、PII 脱敏、分类器过滤）。如需可运行的 1.x 代码，请将每个概念映射到对应模态指南中的相应阶段。

## 数据整理流水线

### 阶段 1：质量过滤

```python
from nemo_curator.filters import (
    WordCountFilter,
    RepeatedLinesFilter,
    UrlRatioFilter,
    NonAlphaNumericFilter
)

# 应用 30+ 启发式过滤器
from nemo_curator import ScoreFilter

# 词数过滤
dataset = dataset.filter(WordCountFilter(min_words=50, max_words=100000))

# 去除重复内容
dataset = dataset.filter(RepeatedLinesFilter(max_repeated_line_fraction=0.3))

# URL 比例过滤
dataset = dataset.filter(UrlRatioFilter(max_url_ratio=0.2))
```

### 阶段 2：去重

**精确去重**：
```python
from nemo_curator.modules import ExactDuplicates

# 删除完全重复项
deduped = ExactDuplicates(id_field="id", text_field="text")(dataset)
```

**模糊去重**（GPU 上速度提升 16×）：
```python
from nemo_curator.modules import FuzzyDuplicates

# MinHash + LSH 去重
fuzzy_dedup = FuzzyDuplicates(
    id_field="id",
    text_field="text",
    num_hashes=260,      # MinHash parameters
    num_buckets=20,
    hash_method="md5"
)

deduped = fuzzy_dedup(dataset)
```

**语义去重**：
```python
from nemo_curator.modules import SemanticDuplicates

# 基于 embedding（向量嵌入）的去重
semantic_dedup = SemanticDuplicates(
    id_field="id",
    text_field="text",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    threshold=0.8  # Cosine similarity threshold
)

deduped = semantic_dedup(dataset)
```

### 阶段 3：PII 脱敏

```python
from nemo_curator.modules import Modify
from nemo_curator.modifiers import PIIRedactor

# 脱敏个人身份信息（PII）
pii_redactor = PIIRedactor(
    supported_entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "LOCATION"],
    anonymize_action="replace"  # or "redact"
)

redacted = Modify(pii_redactor)(dataset)
```

### 阶段 4：分类器过滤

```python
from nemo_curator.classifiers import QualityClassifier

# 质量分类
quality_clf = QualityClassifier(
    model_path="nvidia/quality-classifier-deberta",
    batch_size=256,
    device="cuda"
)

# 过滤低质量文档
high_quality = dataset.filter(lambda doc: quality_clf(doc["text"]) > 0.5)
```

## GPU 加速

### GPU 与 CPU 性能对比

| 操作 | CPU（16 核） | GPU（A100） | 加速比 |
|-----------|----------------|------------|---------|
| 模糊去重（8TB） | 120 小时 | 7.5 小时 | 16× |
| 精确去重（1TB） | 8 小时 | 0.5 小时 | 16× |
| 质量过滤 | 2 小时 | 0.2 小时 | 10× |

### 多 GPU 扩展

```python
from nemo_curator import get_client
import dask_cuda

# 初始化 GPU 集群
client = get_client(cluster_type="gpu", n_workers=8)

# 使用 8 块 GPU 处理
deduped = FuzzyDuplicates(...)(dataset)
```

## 多模态数据整理

### 图像整理

```python
from nemo_curator.image import (
    AestheticFilter,
    NSFWFilter,
    CLIPEmbedder
)

# 美学评分
aesthetic_filter = AestheticFilter(threshold=5.0)
filtered_images = aesthetic_filter(image_dataset)

# NSFW 检测
nsfw_filter = NSFWFilter(threshold=0.9)
safe_images = nsfw_filter(filtered_images)

# 生成 CLIP embedding
clip_embedder = CLIPEmbedder(model="openai/clip-vit-base-patch32")
image_embeddings = clip_embedder(safe_images)
```

### 视频整理

```python
from nemo_curator.video import (
    SceneDetector,
    ClipExtractor,
    InternVideo2Embedder
)

# 场景检测
scene_detector = SceneDetector(threshold=27.0)
scenes = scene_detector(video_dataset)

# 提取片段
clip_extractor = ClipExtractor(min_duration=2.0, max_duration=10.0)
clips = clip_extractor(scenes)

# 生成 embedding
video_embedder = InternVideo2Embedder()
video_embeddings = video_embedder(clips)
```

### 音频整理

```python
from nemo_curator.audio import (
    ASRInference,
    WERFilter,
    DurationFilter
)

# ASR 转录
asr = ASRInference(model="nvidia/stt_en_fastconformer_hybrid_large_pc")
transcribed = asr(audio_dataset)

# 按 WER（词错误率）过滤
wer_filter = WERFilter(max_wer=0.3)
high_quality_audio = wer_filter(transcribed)

# 时长过滤
duration_filter = DurationFilter(min_duration=1.0, max_duration=30.0)
filtered_audio = duration_filter(high_quality_audio)
```

## 常见模式

### 网络抓取数据整理（Common Crawl）

```python
from nemo_curator import ScoreFilter, Modify
from nemo_curator.filters import *
from nemo_curator.modules import *
from nemo_curator.datasets import DocumentDataset

# 加载 Common Crawl 数据
dataset = DocumentDataset.read_parquet("common_crawl/*.parquet")

# 流水线
pipeline = [
    # 1. 质量过滤
    WordCountFilter(min_words=100, max_words=50000),
    RepeatedLinesFilter(max_repeated_line_fraction=0.2),
    SymbolToWordRatioFilter(max_symbol_to_word_ratio=0.3),
    UrlRatioFilter(max_url_ratio=0.3),

    # 2. 语言过滤
    LanguageIdentificationFilter(target_languages=["en"]),

    # 3. 去重
    ExactDuplicates(id_field="id", text_field="text"),
    FuzzyDuplicates(id_field="id", text_field="text", num_hashes=260),

    # 4. PII 脱敏
    PIIRedactor(),

    # 5. NSFW 过滤
    NSFWClassifier(threshold=0.8)
]

# 执行
for stage in pipeline:
    dataset = stage(dataset)

# 保存
dataset.to_parquet("curated_common_crawl/")
```

### 分布式处理

```python
from nemo_curator import get_client
from dask_cuda import LocalCUDACluster

# 多 GPU 集群
cluster = LocalCUDACluster(n_workers=8)
client = get_client(cluster=cluster)

# 处理大型数据集
dataset = DocumentDataset.read_parquet("s3://large_dataset/*.parquet")
deduped = FuzzyDuplicates(...)(dataset)

# 清理
client.close()
cluster.close()
```

## 性能基准

### 模糊去重（8TB RedPajama v2）

- **CPU（256 核）**：120 小时
- **GPU（8× A100）**：7.5 小时
- **加速比**：16×

### 精确去重（1TB）

- **CPU（64 核）**：8 小时
- **GPU（4× A100）**：0.5 小时
- **加速比**：16×

### 质量过滤（100GB）

- **CPU（32 核）**：2 小时
- **GPU（2× A100）**：0.2 小时
- **加速比**：10×

## 成本对比

**基于 CPU 的数据整理**（AWS c5.18xlarge × 10）：
- 费用：$3.60/小时 × 10 = $36/小时
- 处理 8TB 耗时：120 小时
- **合计**：$4,320

**基于 GPU 的数据整理**（AWS p4d.24xlarge × 2）：
- 费用：$32.77/小时 × 2 = $65.54/小时
- 处理 8TB 耗时：7.5 小时
- **合计**：$491.55

**节省**：降低 89%（节省 $3,828）

## 支持的数据格式

- **输入**：Parquet、JSONL、CSV
- **输出**：Parquet（推荐）、JSONL
- **WebDataset**：用于多模态的 TAR 归档

## 使用场景

**生产部署**：
- NVIDIA 使用 NeMo Curator 准备 Nemotron-4 训练数据
- 已整理的开源数据集：RedPajama v2、The Pile

## 参考资料

- **[过滤指南](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/nemo-curator/references/filtering.md)** - 30+ 质量过滤器与启发式规则
- **[去重指南](https://github.com/NousResearch/hermes-agent/blob/main/optional-skills/mlops/nemo-curator/references/deduplication.md)** - 精确、模糊、语义去重方法

## 资源

- **GitHub**：https://github.com/NVIDIA-NeMo/Curator
- **文档**：https://docs.nvidia.com/nemo/curator/latest/
- **版本**：1.2.0（1.x 是基于 Ray 的流水线重写——复制 0.x 代码片段前请先查看 quickstart）
- **许可证**：Apache 2.0