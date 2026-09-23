---
title: "Outlines — Outlines：结构化 JSON/regex/Pydantic LLM 生成"
sidebar_label: "Outlines"
description: "Outlines：结构化 JSON/regex/Pydantic LLM 生成"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Outlines

Outlines：结构化 JSON/regex/Pydantic LLM 生成。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 使用 `hermes skills install official/mlops/outlines` 安装 |
| 路径 | `optional-skills/mlops/inference/outlines` |
| 版本 | `1.0.1` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖项 | `outlines`, `transformers`, `vllm`, `pydantic` |
| 平台 | linux, macos, windows |
| 标签 | `Prompt Engineering`, `Outlines`, `Structured Generation`, `JSON Schema`, `Pydantic`, `Local Models`, `Grammar-Based Generation`, `vLLM`, `Transformers`, `Type Safety` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时看到的指令内容。
:::

# Outlines：结构化文本生成

## 何时使用此 Skill

在以下情况下使用 Outlines：
- **保证有效的 JSON/XML/代码**结构化生成
- **使用 Pydantic 模型**获得类型安全的输出
- **支持本地模型**（Transformers、llama.cpp、vLLM）
- **通过零开销结构化生成最大化推理速度**
- **自动根据 JSON schema 生成**
- **在 grammar（语法）层面控制 token 采样**

**GitHub Stars**：12,000+ | **来自**：dottxt.ai（前身为 .txt）

> **API 说明（Outlines 1.x）：** 本 skill 面向当前的 v1 API。
> 1.0 之前的辅助函数（`outlines.models.transformers(...)`、
> `outlines.generate.json/choice/regex/...`）已被**移除**。在 v1 中，
> 你使用 `outlines.from_transformers(...)`（或 `from_vllm`、
> `from_llamacpp`、`from_openai`）创建模型，然后带上输出类型**直接调用模型**：
> `model(prompt, output_type)`。JSON/Pydantic 输出以 **JSON 字符串**形式返回
> ——请用 `YourModel.model_validate_json(result)` 进行校验。

## 安装

```bash
# 基础安装
pip install outlines

# 安装特定后端
pip install outlines transformers  # Hugging Face 模型
pip install outlines llama-cpp-python  # llama.cpp
pip install outlines vllm  # vLLM 用于高吞吐量
```

## 快速开始

### 基础示例：分类

```python
import outlines
from typing import Literal
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = "microsoft/Phi-3-mini-4k-instruct"

# v1：包装一个 Transformers 模型 + tokenizer
model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained(MODEL_NAME, device_map="auto"),
    AutoTokenizer.from_pretrained(MODEL_NAME),
)

# 带输出类型直接调用模型
prompt = "Sentiment of 'This product is amazing!': "
sentiment = model(prompt, Literal["positive", "negative", "neutral"])

print(sentiment)  # "positive"（保证为其中之一）
```

### 使用 Pydantic 模型

```python
from pydantic import BaseModel
import outlines
from transformers import AutoModelForCausalLM, AutoTokenizer

class User(BaseModel):
    name: str
    age: int
    email: str

MODEL_NAME = "microsoft/Phi-3-mini-4k-instruct"
model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained(MODEL_NAME, device_map="auto"),
    AutoTokenizer.from_pretrained(MODEL_NAME),
)

# 生成结构化输出（返回 JSON 字符串）
prompt = "Extract user: John Doe, 30 years old, john@example.com"
result = model(prompt, User, max_new_tokens=200)

user = User.model_validate_json(result)  # 解析为 Pydantic 模型
print(user.name)   # "John Doe"
print(user.age)    # 30
print(user.email)  # "john@example.com"
```

## 核心概念

### 1. 受约束的 Token 采样

Outlines 使用由输出类型派生出的已编译自动机，在 logit 层面约束 token 生成。

**工作原理：**
1. 将输出类型（JSON/Pydantic/regex/`Literal`）转换为 schema/grammar
2. 将 grammar 编译为 token 级自动机
3. 在生成的每一步过滤无效 token
4. 当只有一个有效 token 时快速前进

**优势：**
- **零开销**：过滤在 token 层面进行
- **速度提升**：通过确定性路径快速前进
- **保证有效性**：无效输出不可能产生

```python
import outlines
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

class Person(BaseModel):
    name: str
    age: int

model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained("microsoft/Phi-3-mini-4k-instruct", device_map="auto"),
    AutoTokenizer.from_pretrained("microsoft/Phi-3-mini-4k-instruct"),
)

result = model("Generate person: Alice, 25", Person)
person = Person.model_validate_json(result)
```

### 2. 输出类型

在 v1 中，你将期望的**输出类型**直接作为第二个参数传入。

#### 多项选择（`Literal`）

```python
from typing import Literal

sentiment = model("Review: This is great!", Literal["positive", "negative", "neutral"])
# 结果：三个选项之一
```

#### 通过 Pydantic 生成 JSON

```python
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float
    in_stock: bool

result = model("Extract: iPhone 15, $999, available", Product)
product = Product.model_validate_json(result)  # 有效的 Product 实例
```

#### Regex（传入 regex 字符串）

```python
# 生成匹配 regex 模式的文本
phone = model("Generate phone number:", r"[0-9]{3}-[0-9]{3}-[0-9]{4}")
# 结果："555-123-4567"（保证匹配模式）
```

#### 数值类型

```python
# 直接传入 Python 类型
age = model("Person's age:", int)      # 保证为整数
price = model("Product price:", float)  # 保证为浮点数
```

### 3. 模型后端

Outlines 通过 `from_*` 工厂函数支持多种本地及基于 API 的后端。

#### Transformers（Hugging Face）

```python
import outlines
from transformers import AutoModelForCausalLM, AutoTokenizer

model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained("microsoft/Phi-3-mini-4k-instruct", device_map="auto"),
    AutoTokenizer.from_pretrained("microsoft/Phi-3-mini-4k-instruct"),
)

result = model(prompt, YourModel)
```

#### llama.cpp

```python
import outlines
from llama_cpp import Llama

llm = Llama("./models/llama-3.1-8b-instruct.Q4_K_M.gguf", n_gpu_layers=35, n_ctx=4096)
model = outlines.from_llamacpp(llm)

result = model(prompt, YourModel)
```

#### vLLM（高吞吐量）

```python
import outlines
from vllm import LLM

llm = LLM("meta-llama/Llama-3.1-8B-Instruct", tensor_parallel_size=2)
model = outlines.from_vllm(llm)

result = model(prompt, YourModel)
```

#### OpenAI（服务端约束 JSON）

```python
import outlines
from openai import OpenAI

client = OpenAI()
model = outlines.from_openai(client, "gpt-4o-mini")

# API 后端支持 JSON-schema 风格的结构化输出
result = model(prompt, YourModel)
```

### 4. Pydantic 集成

Outlines 对 Pydantic 提供一流支持，可自动进行 schema 转换。
生成结果为 JSON 字符串；调用 `model_validate_json` 获取实例。

#### 基础模型

```python
from pydantic import BaseModel, Field

class Article(BaseModel):
    title: str = Field(description="Article title")
    author: str = Field(description="Author name")
    word_count: int = Field(description="Number of words", gt=0)
    tags: list[str] = Field(description="List of tags")

result = model("Generate article about AI", Article, max_new_tokens=300)
article = Article.model_validate_json(result)
print(article.title)
print(article.word_count)  # 保证 > 0
```

#### 嵌套模型

```python
class Address(BaseModel):
    street: str
    city: str
    country: str

class Person(BaseModel):
    name: str
    age: int
    address: Address  # 嵌套模型

result = model("Generate person in New York", Person)
person = Person.model_validate_json(result)
print(person.address.city)  # "New York"
```

#### Enum 与 Literal

```python
from enum import Enum
from typing import Literal

class Status(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class Application(BaseModel):
    applicant: str
    status: Status  # 必须为枚举值之一
    priority: Literal["low", "medium", "high"]  # 必须为 literal 之一

result = model("Generate application", Application)
app = Application.model_validate_json(result)
print(app.status)  # Status.PENDING（或 APPROVED/REJECTED）
```

## 常见模式

### 模式 1：数据提取

```python
from pydantic import BaseModel
import outlines
from transformers import AutoModelForCausalLM, AutoTokenizer

class CompanyInfo(BaseModel):
    name: str
    founded_year: int
    industry: str
    employees: int

model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained("microsoft/Phi-3-mini-4k-instruct", device_map="auto"),
    AutoTokenizer.from_pretrained("microsoft/Phi-3-mini-4k-instruct"),
)

text = """
Apple Inc. was founded in 1976 in the technology industry.
The company employs approximately 164,000 people worldwide.
"""

prompt = f"Extract company information:\n{text}\n\nCompany:"
company = CompanyInfo.model_validate_json(model(prompt, CompanyInfo, max_new_tokens=200))

print(f"Name: {company.name}")
print(f"Founded: {company.founded_year}")
print(f"Industry: {company.industry}")
print(f"Employees: {company.employees}")
```

### 模式 2：分类

```python
from typing import Literal
from pydantic import BaseModel

# 二分类
result = model("Email: Buy now! 50% off!", Literal["spam", "not_spam"])

# 多分类
category = model(
    "Article: Apple announces new iPhone...",
    Literal["technology", "business", "sports", "entertainment"],
)

# 带置信度
class Classification(BaseModel):
    label: Literal["positive", "negative", "neutral"]
    confidence: float

out = model("Review: This product is okay, nothing special", Classification)
result = Classification.model_validate_json(out)
```

### 模式 3：结构化表单

```python
class UserProfile(BaseModel):
    full_name: str
    age: int
    email: str
    phone: str
    country: str
    interests: list[str]

prompt = """
Extract user profile from:
Name: Alice Johnson
Age: 28
Email: alice@example.com
Phone: 555-0123
Country: USA
Interests: hiking, photography, cooking
"""

profile = UserProfile.model_validate_json(model(prompt, UserProfile, max_new_tokens=250))
print(profile.full_name)
print(profile.interests)  # ["hiking", "photography", "cooking"]
```

### 模式 4：多实体提取

```python
from typing import Literal

class Entity(BaseModel):
    name: str
    type: Literal["PERSON", "ORGANIZATION", "LOCATION"]

class DocumentEntities(BaseModel):
    entities: list[Entity]

text = "Tim Cook met with Satya Nadella at Microsoft headquarters in Redmond."
prompt = f"Extract entities from: {text}"

result = DocumentEntities.model_validate_json(model(prompt, DocumentEntities, max_new_tokens=300))
for entity in result.entities:
    print(f"{entity.name} ({entity.type})")
```

### 模式 5：代码生成

```python
class PythonFunction(BaseModel):
    function_name: str
    parameters: list[str]
    docstring: str
    body: str

prompt = "Generate a Python function to calculate factorial"
func = PythonFunction.model_validate_json(model(prompt, PythonFunction, max_new_tokens=300))

print(f"def {func.function_name}({', '.join(func.parameters)}):")
print(f'    """{func.docstring}"""')
print(f"    {func.body}")
```

### 模式 6：批量处理

```python
import outlines
from transformers import AutoModelForCausalLM, AutoTokenizer
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int

model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained("microsoft/Phi-3-mini-4k-instruct", device_map="auto"),
    AutoTokenizer.from_pretrained("microsoft/Phi-3-mini-4k-instruct"),
)

texts = [
    "John is 30 years old",
    "Alice is 25 years old",
    "Bob is 40 years old",
]

# v1 接受 prompt 列表进行批量生成
prompts = [f"Extract from: {t}" for t in texts]
outputs = model(prompts, Person, max_new_tokens=100)
people = [Person.model_validate_json(o) for o in outputs]
for person in people:
    print(f"{person.name}: {person.age}")
```

## 后端配置

### Transformers

```python
import outlines
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = "microsoft/Phi-3-mini-4k-instruct"

# 基础用法
model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained(MODEL_NAME, device_map="auto"),
    AutoTokenizer.from_pretrained(MODEL_NAME),
)

# GPU + dtype 配置在 HF 模型本身上设置
import torch
model = outlines.from_transformers(
    AutoModelForCausalLM.from_pretrained(MODEL_NAME, device_map="cuda", torch_dtype=torch.float16),
    AutoTokenizer.from_pretrained(MODEL_NAME),
)

# 常用模型
for name in [
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "Qwen/Qwen2.5-7B-Instruct",
]:
    model = outlines.from_transformers(
        AutoModelForCausalLM.from_pretrained(name, device_map="auto"),
        AutoTokenizer.from_pretrained(name),
    )
```

### llama.cpp

```python
import outlines
from llama_cpp import Llama

# 加载 GGUF 模型
llm = Llama(
    "./models/llama-3.1-8b.Q4_K_M.gguf",
    n_ctx=4096,       # 上下文窗口
    n_gpu_layers=35,  # GPU 层数
    n_threads=8,      # CPU 线程数
)
model = outlines.from_llamacpp(llm)

# 完全 GPU 卸载：在 Llama 对象上设置 n_gpu_layers=-1
```

### vLLM（生产环境）

```python
import outlines
from vllm import LLM

# 单 GPU
model = outlines.from_vllm(LLM("meta-llama/Llama-3.1-8B-Instruct"))

# 多 GPU
model = outlines.from_vllm(LLM("meta-llama/Llama-3.1-70B-Instruct", tensor_parallel_size=4))

# 带量化
model = outlines.from_vllm(LLM("meta-llama/Llama-3.1-8B-Instruct", quantization="awq"))
```

## 最佳实践

### 1. 使用具体类型

```python
# ✅ 好：具体类型
class Product(BaseModel):
    name: str
    price: float  # 非 str
    quantity: int  # 非 str
    in_stock: bool  # 非 str

# ❌ 差：全部用字符串
class Product(BaseModel):
    name: str
    price: str  # 应为 float
    quantity: str  # 应为 int
```

### 2. 添加约束

```python
from pydantic import Field

# ✅ 好：带约束
class User(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=0, le=120)
    email: str = Field(pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")

# ❌ 差：无约束
class User(BaseModel):
    name: str
    age: int
    email: str
```

### 3. 对分类使用 Enum

```python
# ✅ 好：固定集合使用 Enum
class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class Task(BaseModel):
    title: str
    priority: Priority

# ❌ 差：自由格式字符串
class Task(BaseModel):
    title: str
    priority: str  # 可以是任意值
```

### 4. 在 Prompt 中提供上下文

```python
# ✅ 好：清晰的上下文
prompt = """
Extract product information from the following text.
Text: iPhone 15 Pro costs $999 and is currently in stock.
Product:
"""

# ❌ 差：上下文不足
prompt = "iPhone 15 Pro costs $999 and is currently in stock."
```

### 5. 处理可选字段

```python
from typing import Optional

# ✅ 好：对不完整数据使用可选字段
class Article(BaseModel):
    title: str  # 必填
    author: Optional[str] = None  # 可选
    date: Optional[str] = None  # 可选
    tags: list[str] = []  # 默认空列表

# 即使 author/date 缺失也能成功
```

### 6. 始终校验 JSON 输出

```python
# 对于 Pydantic/JSON 输出类型，v1 返回 JSON 字符串。
result = model(prompt, Article)          # str
article = Article.model_validate_json(result)  # Article 实例
```

## 与替代方案的对比

| 特性 | Outlines | Instructor | Guidance | LMQL |
|---------|----------|------------|----------|------|
| Pydantic 支持 | ✅ 原生 | ✅ 原生 | ✅ 支持 | ❌ 无 |
| JSON Schema | ✅ 支持 | ✅ 支持 | ✅ 支持 | ✅ 支持 |
| Regex 约束 | ✅ 支持 | ❌ 无 | ✅ 支持 | ✅ 支持 |
| 本地模型 | ✅ 完整 | ⚠️ 有限 | ✅ 完整 | ✅ 完整 |
| API 模型 | ✅ 支持 | ✅ 完整 | ✅ 支持 | ✅ 完整 |
| 零开销 | ✅ 支持 | ❌ 无 | ⚠️ 部分 | ✅ 支持 |
| 自动重试 | ❌ 无 | ✅ 支持 | ❌ 无 | ❌ 无 |
| 学习曲线 | 低 | 低 | 低 | 高 |

**何时选择 Outlines：**
- 使用本地模型（Transformers、llama.cpp、vLLM）
- 需要最大推理速度
- 需要 Pydantic 模型支持
- 需要零开销结构化生成
- 需要控制 token 采样过程

**何时选择替代方案：**
- Instructor：需要 API 模型并支持自动重试
- Guidance：需要 token healing 和复杂工作流
- LMQL：偏好声明式查询语法

## 性能特性

**速度：**
- **零开销**：结构化生成与无约束生成同样快速
- **快速前进优化**：跳过确定性 token
- **比生成后验证方案快 1.2–2 倍**

**内存：**
- 自动机对每个输出类型只编译一次（已缓存）
- 极低的运行时开销
- 配合 vLLM 可实现高吞吐量

**准确性：**
- **100% 有效输出**（由受约束的自动机保证）
- 无需重试循环
- 确定性 token 过滤

## 资源

- **文档**：https://dottxt-ai.github.io/outlines/
- **GitHub**：https://github.com/dottxt-ai/outlines（12k+ stars）
- **Discord**：https://discord.gg/R9DSu34mGd
- **博客**：https://blog.dottxt.co

## 另请参阅

- `references/json_generation.md` —— 全面的 JSON 与 Pydantic 模式
- `references/backends.md` —— 后端专项配置
- `references/examples.md` —— 生产就绪示例
