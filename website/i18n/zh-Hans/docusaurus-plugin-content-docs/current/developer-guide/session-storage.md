---
title: "会话存储"
description: "Hermes 如何在 state.db SQLite 数据库中持久化会话元数据、消息历史和模型配置"
---

# 会话存储 {#session-storage}

Hermes Agent 使用 SQLite 数据库（`~/.hermes/state.db`）跨 CLI 和 gateway 会话持久化会话元数据、完整消息历史及模型配置。这替代了早期的逐会话 JSONL 文件方案。

源文件：`hermes_state.py`（门面）以及一组 `hermes_state_*.py` 兄弟模块（schema、fts、search、compression、portability、gateway 等）

### 桌面端 profile 隔离与压缩代次 {#desktop-profile-isolation-and-compaction-generations}

每个命名 profile 都把会话记录存放在各自的 `$HERMES_HOME/state.db` 中，即使由同一个 `hermes serve` 进程同时服务多个 profile 时也是如此。会话内的 agent 重建（Bot Chat 能力刷新和 `tools.configure`）必须保留该会话的数据库句柄，并在构建期间绑定其 profile 主目录。释放被替换的旧 agent 时，不得关闭其替代者所继承的句柄。即使客户端只提供了 `session_id`，`tools.configure` 也会根据实时会话的 `profile_home` 解析配置。重建会先准备好模型配置，再分配替代 agent，然后同时安装新 agent 并转移所有权；若准备阶段失败，则仍由现有 agent 负责清理。无法解析、或其目录已消失的显式 profile，会在访问启动配置或历史记录之前就失败。同样，过期的 `tools.configure` 会话 ID 会返回 `session not found`，且不会修改配置；省略会话 ID 时仍支持全局设置操作。

原地压缩会将旧行以 `active=0` 归档，并将保留下来的上下文作为 `active=1` 行插入。因此，受保护的消息可能合法地同时出现在两个代次中，且内容和时间戳完全相同。不要把这些归档行当作重复项删除。诊断重复的*实时*写入时请使用 `active=1`；排查看似回退的历史记录时，除了会话 ID，还要检查数据库所属的 profile。



## Codex app-server 输入所有权 {#codex-app-server-input-ownership}

agent 会在启动其 Codex 轮次之前，先持久化已接受的用户输入。随后 Codex 会把该输入投射为一条前导的 `userMessage` 通知。在运行时拼接边界处，只有当这条前导项与序列化进 `turn/start` 的文本（包括富输入强制转换后的结果）完全一致时，Hermes 才会将其排除。之后的或不匹配的用户事件保持不变，单独接受的内容相同的轮次也同样保留。这同样适用于合成的 / 无键输入；它不依赖平台消息 ID。已有的历史重复项不会被重写。当 agent 报告自己拥有持久化职责时，gateway 会跳过其会话记录写入。

## Gateway 异常路径的输入所有权 {#gateway-exception-path-input-ownership}

gateway 异常可能发生在 agent 构建之前，也可能发生在其输入已写入 SQLite 之后。gateway 会在现有的 `display_metadata` 附属字段中为已接受的输入添加一个所有者标记，并通过 agent 正常的持久化路径传递它。provider 消息中永远不会包含这些元数据。平台标记会按平台、profile、作用域、聊天和线程为入站消息 ID 加上命名空间；原始的 `platform_message_id` 保持不变，用于引用 / 回复解析。无键轮次会获得一个全新的标记，即使文本和时间戳完全相同。

异常写入器只探测该标记：先沿已发布的重路由和规范的实时压缩后继查找，再查找压缩祖先。活跃行和压缩归档都计入；已撤销的行、观察到的输入以及无关写入者都不计入。向同一会话写入的无关进程无法抑制此轮次。无需整段历史的基线，也无需分配已归档消息的正文。所有权读取失败不会授权任何推测性的追加；普通的历史读取失败仍返回现有的"历史不可用"响应。

由 agent 负责的正常持久化保持不变。这是失败写入者之间的仲裁，而不是通用的精确一次投递、内容去重或 schema 迁移。历史行不会被重写；未加标记的历史输入无法为重新投递的事件建立所有权。

## 架构概览 {#architecture-overview}

```
~/.hermes/state.db (SQLite, WAL mode)
├── sessions              — 会话元数据、token 计数、计费信息
├── messages              — 每个会话的完整消息历史
├── session_model_usage   — 按模型/按任务的用量归属行
├── messages_fts          — FTS5 虚拟表（content + tool_name + tool_calls）
├── messages_fts_trigram  — 使用 trigram tokenizer 的 FTS5 虚拟表（CJK / 子串搜索）
├── messages_fts_cjk      — 使用 cjk_unicode61 tokenizer 的 FTS5 虚拟表
├── state_meta            — 键值元数据表
├── gateway_routing       — Gateway 路由元数据
├── compression_locks     — 跨进程压缩锁
├── async_delegations     — 异步委派记录
├── delivery_obligations  — Gateway 发件箱（待发送的回复）；由 gateway/delivery_ledger.py 惰性创建
└── schema_version        — 单行表，跟踪迁移状态
```

`hermes sessions recover` 会把上面这些承载数据行的表复制到恢复后的数据库中（FTS 索引和 `schema_version` 会重新生成），源数据库中若存在惰性创建的 `delivery_obligations` 账本也会一并复制——它的行数会像 `sessions`/`messages` 一样被校验。

关键设计决策：
- **WAL 模式**：支持并发读取 + 单写入（gateway 多平台）
- **FTS5 虚拟表**：跨所有会话消息的快速全文搜索
- **会话血缘**：通过 `parent_session_id` 链实现（压缩触发的会话分割）
- **来源标记**（`cli`、`telegram`、`discord` 等）：用于平台过滤
- 批量运行器和 RL 轨迹不存储于此（独立系统）


## SQLite Schema {#sqlite-schema}

### Sessions 表 {#sessions-table}

以下为节选——完整的当前列清单见 `hermes_state_common.py` 中的 `SCHEMA_SQL`（由 `hermes_state_schema.py` 应用）（其中还包括 gateway 路由元数据，如 `session_key`、`chat_id`、`chat_type`、`thread_id`、`display_name`、`origin_json`、`expiry_finalized`，工作区字段 `cwd` / `git_branch` / `git_repo_root`，交接和压缩失败相关字段，`profile_name`、`rewind_count`、`archived` 以及 `pinned`）：

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    api_call_count INTEGER DEFAULT 0,
    -- ... 其他 gateway/工作区/交接/压缩相关列 ...
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique
    ON sessions(title) WHERE title IS NOT NULL;
```

### Messages 表 {#messages-table}

以下为节选——完整 schema 还包括 `effect_disposition`、`platform_message_id`、`observed`、`active`、`compacted`、`api_content`、`display_kind` 和 `display_metadata`：

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_content TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT,
    codex_message_items TEXT
    -- ... 其他显示/压缩相关列 ...
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);
```

说明：
- `tool_calls` 以 JSON 字符串存储（序列化的 tool call 对象列表）
- `reasoning_details`、`codex_reasoning_items` 和 `codex_message_items` 以 JSON 字符串存储
- 桌面端历史加载在 REST 和 JSON-RPC（`session.resume`、`session.activate`、`session.history`）两种投影中都会保留助手的附属字段，包括带有推理和工具调用的行。REST 可能返回 SQLite 中的 JSON 字符串，而 RPC 返回解码后的条目；桌面端两者都接受。最终的 Responses 回复可能只存在于 `codex_message_items` 中，而 `content` 为空。规范内容仍然优先，分析/评论类条目不会被提升为回复文本。
- `reasoning` 存储提供商暴露的原始推理文本
- `api_content` 是一个字节级保真的附属字段：当本条消息实际发送给 API 的内容字符串与 `content` 不同时（临时的记忆/插件注入、持久化覆盖），存储该确切字符串。它保留了线路上的原始字节，以便进行对 prompt 缓存稳定的重放——按发送时的原样存储，唯一例外是孤立代理项（lone surrogate）：sqlite3 无法绑定它们，而对话循环本来就会从每个发出的负载中清除它们。`NULL` 表示 `content` 是原样发送的。
- 时间戳为 Unix epoch 浮点数（`time.time()`）

### FTS5 全文搜索 {#fts5-full-text-search}

`messages_fts` 是一个**外部内容（external-content）**索引：它只存储搜索索引，不
保存被索引文本的副本，需要时再从 `messages` 中读回。被索引的字符串跨越三个列，
因此 `content=` 选项指向的是一个视图，而不是直接指向 `messages`：

```sql
CREATE VIEW IF NOT EXISTS messages_fts_source AS
SELECT
    id AS id,
    COALESCE(content, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(tool_calls, '') AS content
FROM messages;

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    tool_name,
    tool_calls,
    content='messages',
    content_rowid='id'
);
```

FTS5 表通过三个触发器保持同步，它们分别在 `messages` 表发生 INSERT、UPDATE 和 DELETE 时触发。当前的触发器受 `state_meta` 中 `fts_rebuild_high_water` / `fts_rebuild_progress` 标记的门控（这样后台 FTS 重建可以进行而不会重复索引），并覆盖全部三个被索引的列——确切的 SQL 见 `hermes_state_common.py` 中的 `SCHEMA_SQL`。

从损坏或不完整的索引中恢复的方式是
`INSERT INTO messages_fts(messages_fts) VALUES('rebuild')`，它以
`SessionDB.rebuild_fts()` 的形式对外暴露。由于它是从视图重新生成索引的，因此也会
补上任何从未被索引过的消息——而对内联索引执行 rebuild 做不到这一点，因为后者读取
的是索引自身存储的副本。

`messages_fts_trigram` 是一个独立的**内联**索引；它是惰性创建的，可以通过
`HERMES_DISABLE_MESSAGE_TRIGRAM` 禁用。


## Schema 版本与迁移 {#schema-version-and-migrations}

当前 schema 版本：**23**

`schema_version` 表存储单个整数。简单的列添加由 `_reconcile_columns()` 声明式处理（对比实时列与 `SCHEMA_SQL` 并 ADD 缺失列）。版本门控链保留用于无法声明式表达的数据迁移及索引/FTS 变更：

| 版本 | 变更 |
|------|------|
| 1 | 初始 schema（sessions、messages、FTS5） |
| 2 | 向 messages 添加 `finish_reason` 列 |
| 3 | 向 sessions 添加 `title` 列 |
| 4 | 在 `title` 上添加唯一索引（允许 NULL，非 NULL 必须唯一） |
| 5 | 添加计费列：`cache_read_tokens`、`cache_write_tokens`、`reasoning_tokens`、`billing_provider`、`billing_base_url`、`billing_mode`、`estimated_cost_usd`、`actual_cost_usd`、`cost_status`、`cost_source`、`pricing_version` |
| 6 | 向 messages 添加推理列：`reasoning`、`reasoning_details`、`codex_reasoning_items` |
| 7 | 向 messages 添加 `reasoning_content` 列 |
| 8 | 向 sessions 添加 `api_call_count` 列 |
| 9 | 向 messages 添加 `codex_message_items` 列，用于 Codex Responses 消息 id/phase 重放 |
| 10 | 添加 `messages_fts_trigram` 虚拟表（trigram tokenizer，用于 CJK / 子串搜索）并回填现有行 |
| 11 | 重新索引 `messages_fts` 和 `messages_fts_trigram` 以覆盖 `tool_name` + `tool_calls`，从外部内容模式切换为内联模式；删除旧触发器并回填所有消息行 |
| 16 | 在 `model_config` 中标记 delegate 子 agent 行（`$._delegate_from`），使父会话删除导致其成为孤立行后，会话选择器仍保持整洁 |
| 18 | Gateway 元数据整合——从 `sessions.json` 回填 `display_name` / `origin_json` / `expiry_finalized` |
| 20 | 按模型的用量归属——从历史上的逐会话聚合总量播种 `session_model_usage` 行 |
| 22 | 按任务维度的用量归属——重建 `session_model_usage`，使 `task` 列成为 PRIMARY KEY 的一部分 |
| 23 | FTS 存储重新设计——以外部内容 FTS 表取代 v11 的内联模式副本（对现有数据库为可选迁移） |
| 29 | Cron 会话退出 trigram（子串/CJK）索引；`messages_fts_trigram_src` 视图及触发器按 `sessions.source` 过滤，一次性重建会清除历史行 |
| 30 | Delegate 子（subagent）会话同样退出 trigram 索引——依据 `source='subagent'` 或 `$._delegate_from` 标记（`FTS_TRIGRAM_SESSION_SQL`）。这些行仍保留在 `messages` 和标准的 `messages_fts` 词索引中，因此 `session_search` 仍能找到它们；只有约 2.6 倍大小的 trigram 影子表会缩小。一次性重建与 v29 相同 |

上面未列出的版本属于由 `_reconcile_columns()` 处理的声明式列添加（仅提升版本号，无数据迁移）。

声明式列添加使用 `ALTER TABLE ADD COLUMN`，包裹在 try/except 中以处理列已存在的情况（幂等）。每个成功的迁移块完成后版本号递增。


## 写入竞争处理 {#write-contention-handling}

多个 hermes 进程（gateway + CLI 会话 + worktree agent）共享同一个 `state.db`。`SessionDB` 类通过以下方式处理写入竞争：

- **短 SQLite 超时**（1 秒），而非默认的 30 秒
- **应用层重试**，带随机抖动（20–150ms，最多 15 次重试）
- **BEGIN IMMEDIATE** 事务，在事务开始时暴露锁竞争
- **定期 WAL checkpoint**，每 50 次成功写入执行一次（PASSIVE 模式）

这避免了"护卫效应"——SQLite 确定性内部退避会导致所有竞争写入者在相同间隔重试。

```
_WRITE_MAX_RETRIES = 15
_WRITE_RETRY_MIN_S = 0.020   # 20ms
_WRITE_RETRY_MAX_S = 0.150   # 150ms
_CHECKPOINT_EVERY_N_WRITES = 50
```


## 常用操作 {#common-operations}

### 初始化 {#initialize}

```python
from hermes_state import SessionDB

db = SessionDB()                           # 默认：~/.hermes/state.db
db = SessionDB(db_path=Path("/tmp/test.db"))  # 自定义路径
```

### 创建和管理会话 {#create-and-manage-sessions}

```python
# 创建新会话
db.create_session(
    session_id="sess_abc123",
    source="cli",
    model="anthropic/claude-sonnet-4.6",
    user_id="user_1",
    parent_session_id=None,  # 或用于血缘追踪的上一个会话 ID
)

# 结束会话
db.end_session("sess_abc123", end_reason="user_exit")

# 重新打开会话（清除 ended_at/end_reason）
db.reopen_session("sess_abc123")
```

### 存储消息 {#store-messages}

```python
msg_id = db.append_message(
    session_id="sess_abc123",
    role="assistant",
    content="Here's the answer...",
    tool_calls=[{"id": "call_1", "function": {"name": "terminal", "arguments": "{}"}}],
    token_count=150,
    finish_reason="stop",
    reasoning="Let me think about this...",
)
```

### 检索消息 {#retrieve-messages}

```python
# 包含所有元数据的原始消息
messages = db.get_messages("sess_abc123")

# OpenAI 对话格式（用于 API 重放）
conversation = db.get_messages_as_conversation("sess_abc123")
# 返回：[{"role": "user", "content": "..."}, {"role": "assistant", ...}]
```

### 会话标题 {#session-titles}

```python
# 设置标题（非 NULL 标题中必须唯一）
db.set_session_title("sess_abc123", "Fix Docker Build")

# 按标题解析（返回血缘中最新的）
session_id = db.resolve_session_by_title("Fix Docker Build")

# 自动生成血缘中的下一个标题
next_title = db.get_next_title_in_lineage("Fix Docker Build")
# 返回："Fix Docker Build #2"
```


## 全文搜索 {#full-text-search}

`search_messages()` 方法支持 FTS5 查询语法，并自动对用户输入进行清理。

### 基本搜索 {#basic-search}

```python
results = db.search_messages("docker deployment")
```

### FTS5 查询语法 {#fts5-query-syntax}

| 语法 | 示例 | 含义 |
|------|------|------|
| 关键词 | `docker deployment` | 两个词均包含（隐式 AND） |
| 引号短语 | `"exact phrase"` | 精确短语匹配 |
| 布尔 OR | `docker OR kubernetes` | 任一词 |
| 布尔 NOT | `python NOT java` | 排除词 |
| 前缀 | `deploy*` | 前缀匹配 |

### 过滤搜索 {#filtered-search}

```python
# 仅搜索 CLI 会话
results = db.search_messages("error", source_filter=["cli"])

# 排除 gateway 会话
results = db.search_messages("bug", exclude_sources=["telegram", "discord"])

# 仅搜索用户消息
results = db.search_messages("help", role_filter=["user"])
```

### 搜索结果格式 {#search-results-format}

每条结果包含：
- `id`、`session_id`、`role`、`timestamp`
- `snippet` — FTS5 生成的片段，带 `>>>match<<<` 标记
- `context` — 匹配前后各 1 条消息（内容截断至 200 字符）
- `source`、`model`、`session_started` — 来自父会话

`_sanitize_fts5_query()` 方法处理边缘情况：
- 去除不匹配的引号和特殊字符
- 将含连字符的词包裹在引号中（`chat-send` → `"chat-send"`）
- 移除悬空的布尔运算符（`hello AND` → `hello`）


## 会话血缘 {#session-lineage}

会话可通过 `parent_session_id` 形成链。这发生在 gateway 中上下文压缩触发会话分割时。

### 查询：查找会话血缘 {#query-find-session-lineage}

```sql
-- 查找会话的所有祖先
WITH RECURSIVE lineage AS (
    SELECT * FROM sessions WHERE id = ?
    UNION ALL
    SELECT s.* FROM sessions s
    JOIN lineage l ON s.id = l.parent_session_id
)
SELECT id, title, started_at, parent_session_id FROM lineage;

-- 查找会话的所有后代
WITH RECURSIVE descendants AS (
    SELECT * FROM sessions WHERE id = ?
    UNION ALL
    SELECT s.* FROM sessions s
    JOIN descendants d ON s.parent_session_id = d.id
)
SELECT id, title, started_at FROM descendants;
```

### 查询：带预览的最近会话 {#query-recent-sessions-with-preview}

```sql
SELECT s.*,
    COALESCE(
        (SELECT SUBSTR(m.content, 1, 63)
         FROM messages m
         WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
         ORDER BY m.timestamp, m.id LIMIT 1),
        ''
    ) AS preview,
    COALESCE(
        (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
        s.started_at
    ) AS last_active
FROM sessions s
ORDER BY s.started_at DESC
LIMIT 20;
```

### 查询：Token 使用统计 {#query-token-usage-statistics}

```sql
-- 按模型统计总 token 数
SELECT model,
       COUNT(*) as session_count,
       SUM(input_tokens) as total_input,
       SUM(output_tokens) as total_output,
       SUM(estimated_cost_usd) as total_cost
FROM sessions
WHERE model IS NOT NULL
GROUP BY model
ORDER BY total_cost DESC;

-- token 使用量最高的会话
SELECT id, title, model, input_tokens + output_tokens AS total_tokens,
       estimated_cost_usd
FROM sessions
ORDER BY total_tokens DESC
LIMIT 10;
```


## 导出与清理 {#export-and-cleanup}

```python
# 导出单个会话及其消息
data = db.export_session("sess_abc123")

# 导出所有会话（含消息）为字典列表
all_data = db.export_all(source="cli")

# 删除旧会话（仅删除已结束的会话）
deleted_count = db.prune_sessions(older_than_days=90)
deleted_count = db.prune_sessions(older_than_days=30, source="telegram")

# 清除消息但保留会话记录
db.clear_messages("sess_abc123")

# 删除会话及所有消息
db.delete_session("sess_abc123")
```


## 数据库位置 {#database-location}

默认路径：`~/.hermes/state.db`

该路径由 `hermes_constants.get_hermes_home()` 推导，默认解析为 `~/.hermes/`，或 `HERMES_HOME` 环境变量的值。

数据库文件、WAL 文件（`state.db-wal`）和共享内存文件（`state.db-shm`）均创建于同一目录。