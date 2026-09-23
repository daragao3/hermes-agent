---
title: "Pinecone Research —— 基于 Pinecone 的 Agent RAG 与长期记忆"
sidebar_label: "Pinecone Research"
description: "基于 Pinecone 的 Agent RAG 与长期记忆"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Pinecone Research

基于 Pinecone 的 Agent RAG 与长期记忆。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/research/pinecone-research` 安装 |
| 路径 | `optional-skills/research/pinecone-research` |
| 版本 | `1.0.0` |
| 作者 | immuhammadfurqan |
| 许可证 | MIT |
| 依赖项 | `pinecone-client`, `langchain-pinecone` |
| 平台 | linux, macos, windows |
| 标签 | `RAG`, `Pinecone`, `Memory`, `Research`, `Vector Database`, `Agent`, `Retrieval` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Pinecone Research —— Agent RAG 与长期记忆

将 Pinecone 用作 agent 对话的检索增强生成（RAG）后端：
持久化 embedding、从过去的会话中检索相关上下文，
并构建长期记忆。

## 何时使用此 skill {#when-to-use-this-skill}

**适用于：**
- 以 Pinecone 作为向量存储构建 agent RAG 管线
- 需要跨 agent 会话的持久化长期记忆
- 将检索与 agent 工具调用相结合
- 研究或原型验证语义搜索工作流

**以下情况请改用 mlops/pinecone skill：**
- 需要通用的 Pinecone 参考（索引管理、CRUD、混合搜索）
- 在不涉及 agent 集成的生产基础设施上工作

## 快速开始 {#quick-start}

### 设置 {#setup}

```bash
pip install pinecone-client langchain-pinecone langchain-openai
```

设置你的 API 密钥：
```bash
export PINECONE_API_KEY="your-api-key"
```

### 基础 RAG 管线 {#basic-rag-pipeline}

```python
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings

# 初始化 Pinecone
pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])

# 创建或连接索引
index_name = "agent-memory"
if index_name not in [i.name for i in pc.list_indexes()]:
    pc.create_index(
        name=index_name,
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )

# 构建向量存储
vectorstore = PineconeVectorStore.from_documents(
    documents=docs,
    embedding=OpenAIEmbeddings(),
    index_name=index_name,
)

# 检索相关上下文
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
results = retriever.invoke("What did the agent discuss yesterday?")
```

### 基于命名空间的会话记忆 {#namespace-based-session-memory}

```python
# 按会话存储记忆
vectorstore = PineconeVectorStore(
    index=pc.Index(index_name),
    embedding=OpenAIEmbeddings(),
    namespace=f"session-{session_id}",
)

# 跨所有会话查询（不使用命名空间过滤）
all_memory = PineconeVectorStore(
    index=pc.Index(index_name),
    embedding=OpenAIEmbeddings(),
)
results = all_memory.similarity_search("relevant query", k=10)
```

## 最佳实践 {#best-practices}

1. **按会话或用户划分命名空间**——为多租户 agent 隔离数据
2. **批量 upsert**——每批 100–200 个向量以提高效率
3. **元数据过滤**——为向量标注会话 ID、时间戳、主题
4. **清理旧记忆**——删除过时的命名空间以控制成本
5. **使用 serverless**——自动扩缩容，按用量计费

## 资源 {#resources}

- **Pinecone 文档**：https://docs.pinecone.io
- **LangChain 集成**：https://python.langchain.com/docs/integrations/vectorstores/pinecone
- **免费套餐**：1 个索引，10 万个向量（1536 维）
