---
sidebar_position: 9
title: "Matrix"
description: "将 Hermes Agent 设置为 Matrix 机器人"
---

# Matrix 设置

Hermes Agent 与 Matrix 集成，Matrix 是一种开放的联邦消息协议。Matrix 允许你运行自己的 homeserver，也可以使用 matrix.org 等公共 homeserver——无论哪种方式，你都保持对通信的控制权。机器人通过 `mautrix` Python SDK 连接，通过 Hermes Agent 管道（包括工具调用、记忆和推理）处理消息，并实时响应。它支持文本、文件附件、图片、音频、视频，以及可选的端对端加密（E2EE）。

Hermes 兼容任何 Matrix homeserver——Synapse、Conduit、Dendrite 或 matrix.org。

在开始设置之前，先了解大多数人最想知道的：Hermes 连接后的行为方式。

## Hermes 的行为方式

| 场景 | 行为 |
|---------|----------|
| **私聊（DM）** | Hermes 响应每条消息，无需 `@mention`（@ 提及）。每个 DM 有独立的会话。设置 `MATRIX_DM_MENTION_THREADS=true` 可在 DM 中被 `@mentioned` 时创建线程。 |
| **房间** | 默认情况下，Hermes 需要 `@mention`（@ 提及）才会响应。设置 `MATRIX_REQUIRE_MENTION=false` 或将房间 ID 添加到 `MATRIX_FREE_RESPONSE_ROOMS` 可开启自由响应模式。房间邀请会被自动接受。 |
| **线程** | Hermes 支持 Matrix 线程（MSC3440）。在线程中回复时，Hermes 会将线程上下文与主房间时间线隔离。机器人已参与的线程无需提及即可响应。 |
| **自动线程** | 默认情况下，Hermes 会为其在房间中响应的每条消息自动创建线程，以保持对话隔离。设置 `MATRIX_AUTO_THREAD=false` 可禁用此功能。设置 `MATRIX_DM_AUTO_THREAD=true`（默认 false）可同时为私聊消息自动创建线程——这与 `MATRIX_DM_MENTION_THREADS` 不同，后者仅在私聊中机器人被 `@mentioned` 时才创建线程。 |
| **命令** | 当你的 Matrix 客户端会发送 `/命令` 时，Hermes 可以正常接收。如果你的客户端把 `/` 保留给本地命令，请改用 `!命令`；Hermes 会把已知的 `!command` 别名规范化为 `/command`。 |
| **交互式控件** | 危险命令审批和 `/model` 选择可以使用 Matrix 反应。审批反应可以限制为仅由发起该操作的用户操作。 |
| **思考与工具活动** | 启用 gateway 进度显示时，Matrix 使用可编辑的线程化思考/工具活动面板，因此更新不会淹没主房间时间线。 |
| **多用户共享房间** | 默认情况下，Hermes 在房间内按用户隔离会话历史。同一房间中的两个人不会共享同一对话记录，除非你明确禁用该功能。 |

:::tip
机器人在被邀请时会自动加入房间。只需将机器人的 Matrix 用户邀请到任意房间，它就会加入并开始响应。
:::

## 能力矩阵

此表以 Matrix 适配器的能力声明和 Matrix 测试覆盖为依据。E2EE 是按模式区分的，
因为各部署可以自行选择加密房间是禁用、机会性启用还是强制要求。

| 能力 | Matrix |
|------------|--------|
| 文本 | 是 |
| 线程 | 是 |
| 反应 | 是 |
| 审批 | 是 |
| 模型选择器 | 是 |
| 思考面板 | 是 |
| 图片 | 是 |
| 多张图片 | 是 |
| 文件 | 是 |
| 语音/音频 | 是 |
| 视频 | 是 |
| E2EE | 关闭 / 可选 / 必需 |
| 诊断 | 是 |

### Matrix 中的会话模型

默认情况下：

- 每个 DM 有独立的会话
- 每个线程有独立的会话命名空间
- 共享房间中的每个用户在该房间内有独立的会话

这由 `config.yaml` 控制：

```yaml
group_sessions_per_user: true
```

仅当你明确希望整个房间共享一个对话时，才将其设置为 `false`：

```yaml
group_sessions_per_user: false
```

共享会话在协作房间中可能有用，但也意味着：

- 用户共享上下文增长和 token 消耗
- 某人的长时间工具密集型任务会膨胀所有人的上下文
- 某人正在进行的任务可能会打断同一房间中另一人的后续操作

### 提及与线程配置

你可以通过环境变量或 `config.yaml` 配置提及和自动线程行为：

```yaml
matrix:
  require_mention: true           # 在房间中要求 @提及（默认：true）
  allowed_users:                  # 允许触发 agent 回合的 Matrix 用户
    - "@alice:matrix.org"
  allowed_rooms:                  # 允许触发 agent 回合的 Matrix 房间
    - "!abc123:matrix.org"
  free_response_rooms:            # 免除提及要求的房间
    - "!abc123:matrix.org"
  ignore_user_patterns:           # 需要忽略的桥接/appservice 幽灵用户
    - "^@telegram_"
    - "^@whatsapp_"
  process_notices: false          # 默认忽略 m.notice
  session_scope: room             # auto|room|thread；项目房间推荐使用 room
  auto_thread: true               # 自动为响应创建线程（默认：true）
  dm_mention_threads: false       # 在 DM 中被 @提及时创建线程（默认：false）
  max_message_length: 16000       # 出站分块大小，单位为字符（默认：16000，最大：65535）
```

或通过环境变量：

```bash
MATRIX_REQUIRE_MENTION=true
MATRIX_ALLOWED_USERS=@alice:matrix.org
MATRIX_ALLOWED_ROOMS=!abc123:matrix.org
MATRIX_FREE_RESPONSE_ROOMS=!abc123:matrix.org,!def456:matrix.org
MATRIX_IGNORE_USER_PATTERNS='^@telegram_,^@whatsapp_'
MATRIX_PROCESS_NOTICES=false
MATRIX_SESSION_SCOPE=room       # 推荐用于稳定的项目房间上下文
MATRIX_AUTO_THREAD=true
MATRIX_DM_MENTION_THREADS=false
MATRIX_REACTIONS=true          # 默认：true——处理过程中发送 emoji 反应
MATRIX_ALLOW_ROOM_MENTIONS=false
```

:::tip 禁用反应
`MATRIX_REACTIONS=false` 会关闭机器人在收到消息时发布的处理生命周期 emoji 反应（👀/✅/❌）。适用于反应事件较为嘈杂或部分参与客户端不支持的房间。
:::

:::tip 全房间提及
对于像 `@alice:example.org` 这样明确的 Matrix ID，Hermes 会发送结构化的 Matrix 用户提及。全房间的 `@room` 通知默认禁用；仅在允许机器人通知所有人的房间中才设置 `MATRIX_ALLOW_ROOM_MENTIONS=true`。
:::

:::note
如果你从没有 `MATRIX_REQUIRE_MENTION` 的版本升级，机器人之前会响应房间中的所有消息。要保留该行为，请设置 `MATRIX_REQUIRE_MENTION=false`。
:::

### 项目房间隔离

如果你在多个项目房间中使用同一个 Matrix 机器人，请配置稳定的按房间划分的会话：

```bash
MATRIX_SESSION_SCOPE=room
MATRIX_AUTO_THREAD=false
```

`MATRIX_SESSION_SCOPE` 接受以下取值：

| 作用域 | 行为 |
|-------|------|
| `auto` | 向后兼容的默认值。由现有的 `MATRIX_AUTO_THREAD` 行为控制合成线程。 |
| `room` | 未开线程的房间消息保持在同一个稳定的房间会话中。真正的 Matrix 线程仍然使用各自的线程根。 |
| `thread` | 未开线程的房间消息会根据触发事件 ID 合成一个线程/会话。 |

现在 Hermes 会把当前的 Matrix 房间名称、房间 ID、主题、消息 ID 以及一条 Matrix
房间边界说明加入 agent prompt（提示词）中。`/status` 也会显示当前的 Matrix
房间/会话作用域，并且 `/resume` 不会悄悄恢复来自另一个 Matrix 房间的同名会话，
除非你明确使用 `/resume --cross-room <session name>`。

`MATRIX_SESSION_SCOPE=room` 控制的是房间/线程这一条通道。现有的
`group_sessions_per_user` 设置仍然控制该房间内的用户是否共享这条通道。当
`group_sessions_per_user: true`（默认）时，Alice 和 Bob 各自拥有独立的
Project B 会话。当 `group_sessions_per_user: false` 时，该房间只有一份共享的
Project B 对话记录。

本指南将引导你完成完整的设置流程——从创建机器人账户到发送第一条消息。

## 第一步：创建机器人账户

你需要为机器人准备一个 Matrix 用户账户。有以下几种方式：

### 方式 A：在你的 Homeserver 上注册（推荐）

如果你运行自己的 homeserver（Synapse、Conduit、Dendrite）：

1. 使用管理员 API 或注册工具创建新用户：

```bash
# Synapse 示例
register_new_matrix_user -c /etc/synapse/homeserver.yaml http://localhost:8008
```

2. 选择一个用户名，例如 `hermes`——完整的用户 ID 将是 `@hermes:your-server.org`。

### 方式 B：使用 matrix.org 或其他公共 Homeserver

1. 前往 [Element Web](https://app.element.io) 创建新账户。
2. 为机器人选择一个用户名（例如 `hermes-bot`）。

### 方式 C：使用你自己的账户

你也可以以自己的用户身份运行 Hermes。这意味着机器人以你的名义发帖——适合个人助手场景。

## 第二步：获取访问令牌

Hermes 需要访问令牌（access token）来向 homeserver 进行身份验证。有两种方式：

### 方式 A：访问令牌（推荐）

获取令牌最可靠的方式：

**通过 Element：**
1. 使用机器人账户登录 [Element](https://app.element.io)。
2. 前往 **设置** → **帮助与关于**。
3. 向下滚动并展开 **高级**——访问令牌显示在那里。
4. **立即复制。**

**通过 API：**

```bash
curl -X POST https://your-server/_matrix/client/v3/login \
  -H "Content-Type: application/json" \
  -d '{
    "type": "m.login.password",
    "user": "@hermes:your-server.org",
    "password": "your-password"
  }'
```

响应中包含 `access_token` 字段——复制它。

:::warning[保管好你的访问令牌]
访问令牌可完全访问机器人的 Matrix 账户。切勿公开分享或提交到 Git。如果泄露，请通过注销该用户的所有会话来撤销它。
:::

### 方式 B：密码登录

你可以不提供访问令牌，而是提供机器人的用户 ID 和密码。Hermes 会在启动时自动登录。这种方式更简单，但密码会存储在你的 `.env` 文件中。

```bash
MATRIX_USER_ID=@hermes:your-server.org
MATRIX_PASSWORD=your-password
```

## 第三步：找到你的 Matrix 用户 ID

Hermes Agent 使用你的 Matrix 用户 ID 来控制谁可以与机器人交互。Matrix 用户 ID 的格式为 `@username:server`。

查找方式：

1. 打开 [Element](https://app.element.io)（或你偏好的 Matrix 客户端）。
2. 点击你的头像 → **设置**。
3. 你的用户 ID 显示在个人资料顶部（例如 `@alice:matrix.org`）。

:::tip
Matrix 用户 ID 始终以 `@` 开头，并包含 `:` 后跟服务器名称。例如：`@alice:matrix.org`、`@bob:your-server.com`。
:::

## 第四步：配置 Hermes Agent

### 方式 A：交互式设置（推荐）

运行引导式设置命令：

```bash
hermes gateway setup
```

在提示时选择 **Matrix**，然后按提示提供你的 homeserver URL、访问令牌（或用户 ID + 密码）以及允许的用户 ID。

### 方式 B：手动配置

将以下内容添加到你的 `~/.hermes/.env` 文件：

**使用访问令牌：**

```bash
# 必填
MATRIX_HOMESERVER=https://matrix.example.org
MATRIX_ACCESS_TOKEN=***

# 可选：用户 ID（如省略则从令牌自动检测）
# MATRIX_USER_ID=@hermes:matrix.example.org

# 安全：限制可与机器人交互的用户
MATRIX_ALLOWED_USERS=@alice:matrix.example.org

# 可选：限制哪些房间可以触发机器人
MATRIX_ALLOWED_ROOMS=!abc123:matrix.example.org

# 多个允许用户（逗号分隔）
# MATRIX_ALLOWED_USERS=@alice:matrix.example.org,@bob:matrix.example.org
```

**使用密码登录：**

```bash
# 必填
MATRIX_HOMESERVER=https://matrix.example.org
MATRIX_USER_ID=@hermes:matrix.example.org
MATRIX_PASSWORD=***

# 安全
MATRIX_ALLOWED_USERS=@alice:matrix.example.org
```

## 私有部署加固

对于私有 Matrix 部署，请同时设置用户和房间白名单。如果未设置
`MATRIX_ALLOWED_USERS`，任何能在机器人已加入的房间中触达它的发送者都可以触发
agent 回合。如果未设置 `MATRIX_ALLOWED_ROOMS`，机器人加入的任何房间都可以触发
agent 回合。加固后的部署应当同时设置两者：

```bash
MATRIX_ALLOWED_USERS=@alice:matrix.example.org,@bob:matrix.example.org
MATRIX_ALLOWED_ROOMS=!ops:matrix.example.org,!dmroom:matrix.example.org
```

桥接和 appservice 部署需要额外的回环保护。Hermes 默认始终忽略自身事件、
localpart 以 `_` 开头的 Matrix appservice 风格用户、重复的事件 ID、启动前的旧事件、
编辑替换事件以及 `m.notice` 事件。当你的桥接使用不同的命名约定时，请补充与该部署
对应的桥接幽灵用户模式：

```bash
MATRIX_IGNORE_USER_PATTERNS='^@telegram_,^@slack_,^@whatsapp_'
```

只有当某个可信的人工工作流确实会发送 `m.notice` 时，才启用 notice：

```bash
MATRIX_PROCESS_NOTICES=true
```

出站的全房间通知默认禁用。除非明确允许机器人用 `@room` 唤醒整个房间，
否则请保持 `MATRIX_ALLOW_ROOM_MENTIONS=false`。

诊断信息和调试载荷会对 Matrix 访问令牌、恢复密钥、设备标识符和消息正文做脱敏处理。
媒体下载被限制为 Matrix `mxc://` 内容 URI，超过 `MATRIX_MAX_MEDIA_BYTES` 时会被拒绝。
请把联邦房间和不受信任的 homeserver 视为不可信输入：保持房间白名单收紧，
对工具密集型工作优先使用私聊或私有房间，并避免把桥接幽灵用户或 appservice
傀儡账号授权为允许用户。

`~/.hermes/config.yaml` 中的可选行为设置：

```yaml
group_sessions_per_user: true
```

- `group_sessions_per_user: true` 在共享房间内保持每个参与者的上下文隔离

### 启动 Gateway

配置完成后，启动 Matrix gateway：

```bash
hermes gateway
```

机器人应在几秒内连接到你的 homeserver 并开始同步。发送一条消息——DM 或机器人已加入的房间——进行测试。

:::tip
你可以在后台运行 `hermes gateway`，或将其作为 systemd 服务以持续运行。详情请参阅部署文档。
:::

## 端对端加密（E2EE）

Hermes 支持 Matrix 端对端加密，你可以在加密房间中与机器人聊天。

### 前提条件

E2EE 需要带有加密扩展的 `mautrix` 库以及 `libolm` C 库：

```bash
# 安装带 E2EE 支持的 mautrix
pip install 'mautrix[encryption]'

# 或通过 hermes extras 安装
cd ~/.hermes/hermes-agent && uv pip install -e ".[matrix]"
```

你还需要在系统上安装 `libolm`：

```bash
# Debian/Ubuntu
sudo apt install libolm-dev

# macOS
brew install libolm

# Fedora
sudo dnf install libolm-devel
```

### 启用 E2EE

在 `~/.hermes/.env` 中添加：

```bash
MATRIX_E2EE_MODE=required
```

`MATRIX_E2EE_MODE` 接受以下取值：

| 模式 | 行为 |
|------|------|
| `off` | 不初始化 Matrix E2EE。 |
| `optional` | 依赖可用时尝试启用 E2EE，但在加密模块无法初始化时仍保持未加密房间正常工作。 |
| `required` | 若 E2EE 依赖或加密设置不可用，则失败关闭（fail closed）。 |

在加密设置不可用时，optional 模式可能回退到非 E2EE 运行。required 模式则会失败关闭，而不是悄悄降级。

为向后兼容，`MATRIX_ENCRYPTION=true` 仍然启用 required 级别的 E2EE 行为。

启用 E2EE 后，Hermes 会：

- 将加密密钥存储在 `~/.hermes/platforms/matrix/store/`（旧版安装：`~/.hermes/matrix/store/`）
- 在首次连接时上传设备密钥
- 自动解密传入消息并加密传出消息
- 被邀请时自动加入加密房间

### Matrix 工具与控件

在 Matrix 对话中，Hermes 会向 agent 暴露 Matrix 专用工具：

- `matrix_send_reaction`
- `matrix_redact_message`
- `matrix_create_room`
- `matrix_invite_user`
- `matrix_fetch_history`
- `matrix_set_presence`

这些工具的作用范围仅限 Matrix 上下文，在非 Matrix 工具集中不可用。管理类工具默认禁用：撤回需要 `MATRIX_TOOLS_ALLOW_REDACTION=true`，邀请需要 `MATRIX_TOOLS_ALLOW_INVITES=true`，创建房间需要 `MATRIX_TOOLS_ALLOW_ROOM_CREATE=true`。创建公开房间还需要 `MATRIX_ALLOW_PUBLIC_ROOMS=true`。
Matrix 工具默认仅限于当前 Matrix 房间。明确的跨房间目标需要
`MATRIX_TOOLS_ALLOW_CROSS_ROOM=true`；撤回及类似邀请的跨房间操作还额外需要
`MATRIX_TOOLS_ALLOW_CROSS_ROOM_DESTRUCTIVE=true`。如果设置了 `MATRIX_ALLOWED_ROOMS`，
Matrix 工具只能以这些房间为目标。

反应控件使用：

- ✅ 批准一次
- ♾️ 始终批准
- ❌ 拒绝
- 数字反应用于 `/model` 选项

如果你有意让房间中任何已授权的 Matrix 用户都能操作审批/模型选择器提示，请设置 `MATRIX_APPROVAL_REQUIRE_SENDER=false`。在 Hermes 知道谁发起了该操作时，默认是绑定到发起者的。

### 媒体限制

Hermes 通过 Matrix 媒体 API 上传和下载 Matrix 图片、文件、音频和视频。多张生成的图片会作为一个有序的逻辑批次发送，在整个批次中保留标题和线程上下文。

默认情况下，超过 100 MB 的 Matrix 媒体会在上传/下载前被拒绝。可通过以下方式覆盖：

```bash
MATRIX_MAX_MEDIA_BYTES=104857600
```

入站媒体必须使用 Matrix `mxc://` 内容 URI。Hermes 会拒绝 Matrix 事件中任意的
HTTP(S) 媒体 URL，以免把联邦房间变成不受限的下载器。

## Synapse 集成测试

Hermes 附带了一个可选启用的 Synapse 测试环境，用于本地验证：

```bash
docker compose -f tests/e2e/matrix_synapse_gateway/docker-compose.yml up -d
HERMES_MATRIX_SYNAPSE_INTEGRATION=1 \
  scripts/run_tests.sh -m "integration and matrix_synapse" \
  tests/e2e/matrix_synapse_gateway/test_gateway.py
docker compose -f tests/e2e/matrix_synapse_gateway/docker-compose.yml down -v
```

该环境通过 Synapse 的共享密钥注册创建临时用户，覆盖私有房间的收发、具名房间的
邀请/加入、媒体上传/下载、机器人响应投递以及启动时的旧事件过滤。E2EE 冒烟测试
另以 `matrix_e2ee` 标记，因此在开发机器上可以保持为可选启用。

### 交叉签名验证（推荐）

如果你的 Matrix 账户启用了交叉签名（Element 中的默认设置），请设置恢复密钥，以便机器人在启动时自签其设备。若不设置，其他 Matrix 客户端在设备密钥轮换后可能拒绝与机器人共享加密会话。

```bash
MATRIX_RECOVERY_KEY=EsT... 你的恢复密钥
```

**查找位置：** 在 Element 中，前往 **设置** → **安全与隐私** → **加密** → 你的恢复密钥（也称为"安全密钥"）。这是你首次设置交叉签名时被要求保存的密钥。

每次启动时，如果设置了 `MATRIX_RECOVERY_KEY`，Hermes 会从 homeserver 的安全密钥存储中导入交叉签名密钥并对当前设备进行签名。此操作是幂等的，可以永久启用。

如果 Hermes 引导生成了新的 Matrix 恢复密钥，它绝不会把原始密钥写入日志。可在启动前设置
`MATRIX_RECOVERY_KEY_OUTPUT_FILE=/secure/path/matrix-recovery-key.txt`，将生成的密钥以
文件权限 `0600` 写出一次；若该文件已存在，则不会被覆盖。

:::warning[删除加密存储]
如果你删除了 `~/.hermes/platforms/matrix/store/crypto.db`，机器人将失去其加密身份。仅使用相同的设备 ID 重启**不能**完全恢复——homeserver 仍持有使用旧身份密钥签名的一次性密钥，对等方无法建立新的 Olm 会话。

Hermes 在启动时会检测到此情况并拒绝启用 E2EE，日志显示：`device XXXX has stale one-time keys on the server signed with a previous identity key`。

**最简恢复方式：生成新的访问令牌**（获得一个没有过期密钥历史的全新设备 ID）。请参阅下方"从带有 E2EE 的旧版本升级"章节。这是最可靠的路径，无需操作 homeserver 数据库。

**手动恢复**（高级——保留相同设备 ID）：

1. 停止 Synapse 并从其数据库中删除旧设备：
   ```bash
   sudo systemctl stop matrix-synapse
   sudo sqlite3 /var/lib/matrix-synapse/homeserver.db "
     DELETE FROM e2e_device_keys_json WHERE device_id = 'DEVICE_ID' AND user_id = '@hermes:your-server';
     DELETE FROM e2e_one_time_keys_json WHERE device_id = 'DEVICE_ID' AND user_id = '@hermes:your-server';
     DELETE FROM e2e_fallback_keys_json WHERE device_id = 'DEVICE_ID' AND user_id = '@hermes:your-server';
     DELETE FROM devices WHERE device_id = 'DEVICE_ID' AND user_id = '@hermes:your-server';
   "
   sudo systemctl start matrix-synapse
   ```
   或通过 Synapse 管理员 API（注意 URL 编码的用户 ID）：
   ```bash
   curl -X DELETE -H "Authorization: Bearer ADMIN_TOKEN" \
     'https://your-server/_synapse/admin/v2/users/%40hermes%3Ayour-server/devices/DEVICE_ID'
   ```
   注意：通过管理员 API 删除设备也可能使关联的访问令牌失效。之后你可能需要生成新令牌。

2. 删除本地加密存储并重启 Hermes：
   ```bash
   rm -f ~/.hermes/platforms/matrix/store/crypto.db*
   # 重启 hermes
   ```

其他 Matrix 客户端（Element、matrix-commander）可能缓存了旧的设备密钥。恢复后，在 Element 中输入 `/discardsession` 以强制与机器人建立新的加密会话。
:::

:::info
如果未安装 `mautrix[encryption]` 或缺少 `libolm`，机器人会自动回退到普通（未加密）客户端。你会在日志中看到警告。
:::

## 主房间

你可以指定一个"主房间"，机器人在此发送主动消息（例如 cron 任务输出、提醒和通知）。有两种设置方式：

### 使用斜杠命令

在机器人所在的任意 Matrix 房间中输入 `/sethome`。该房间即成为主房间。
如果你的 Matrix 客户端会拦截斜杠命令，请改为输入 `!sethome`。

### 手动配置

在 `~/.hermes/.env` 中添加：

```bash
MATRIX_HOME_ROOM=!abc123def456:matrix.example.org
```

## 房间白名单（`allowed_rooms`）

将机器人限制在固定的 Matrix 房间集合中。设置后，机器人**仅**在 ID 出现在列表中的房间响应——来自其他房间的消息会被静默忽略，即使提及了机器人。

**私聊（DM 房间）不受此过滤器限制**，因此授权用户始终可以一对一联系机器人。

```yaml
matrix:
  allowed_rooms:
    - "!abc123def456:matrix.example.org"
    - "!opsroom789:matrix.example.org"
```

或通过环境变量（逗号分隔）：

```bash
MATRIX_ALLOWED_ROOMS="!abc123def456:matrix.example.org,!opsroom789:matrix.example.org"
```

行为说明：

- 空值/未设置 → 无限制（默认）。
- 非空 → 房间 ID 必须在列表中。该检查在所有其他门控（提及要求、发送者白名单等）**之前**运行。
- 使用房间的**内部 ID**（`!abc...:server`），而非别名（`#room:server`）。你可以在 Element 中通过 房间 → 设置 → 高级 找到房间的内部 ID。

另请参阅：[管理员/用户斜杠命令分离](../../reference/slash-commands.md#permissions-and-adminuser-split)。

:::tip
查找房间 ID：在 Element 中，进入房间 → **设置** → **高级** → **内部房间 ID**（以 `!` 开头）。
:::

## Matrix 中的命令

Hermes 在 Matrix 中支持与其他消息平台相同的 gateway 命令，包括
`/commands`、`/model`、`/stop`、`/queue`、`/steer`、`/goal`、`/subgoal`、
`/background`、`/bg`、`/btw`、`/tasks` 和 `/yolo`。

有些 Matrix 客户端把开头的 `/` 保留给本地客户端命令，可能不会把未知的斜杠命令
发送到房间。这种情况下，请使用 `!` 作为 Matrix 下安全的别名：

```text
!commands
!model
!model gpt-5.5 --provider openrouter
!queue continue with the next task
!stop
```

只有当命令是 gateway 已知的命令、已注册的插件命令或已安装的 skill 命令时，
Hermes 才会规范化 `!command`。像 `!important` 这样普通的感叹表达仍然是普通聊天消息。

## 故障排查

### 机器人不响应消息

**原因**：机器人未加入房间、`MATRIX_ALLOWED_USERS` 中不包含你的用户 ID、`MATRIX_ALLOWED_ROOMS` 中不包含该房间，或者房间消息没有提及机器人。

**解决方法**：邀请机器人进入房间——它会在收到邀请时自动加入。确认你的用户 ID 在 `MATRIX_ALLOWED_USERS` 中（使用完整的 `@user:server` 格式）；若配置了 `MATRIX_ALLOWED_ROOMS` 白名单，还需确认房间 ID 在其中。在房间中请提及机器人，或把该房间加入 `MATRIX_FREE_RESPONSE_ROOMS`。重启 gateway。

### 机器人加入房间但静默丢弃所有消息（时钟偏差）

**原因**：主机系统时钟超前于实际时间。Matrix 适配器应用了 5 秒启动宽限过滤器（`event_ts < startup_ts - 5`）以忽略初始同步中重放的事件。当系统时钟超前时，每个传入事件看起来都"早于启动时间"，在到达消息处理器之前就被丢弃——机器人看起来已连接但从不回复。参见 [#12614](https://github.com/NousResearch/hermes-agent/issues/12614)。

**症状**：Gateway 日志显示 `Matrix: dropped N live events as 'too old' more than 30s after startup`。

**解决方法**：使用 NTP 同步主机时钟并重启机器人：

```bash
# Debian/Ubuntu
sudo timedatectl set-ntp true
timedatectl status   # 确认 "System clock synchronized: yes"

# macOS
sudo sntp -sS time.apple.com
```

### 启动时出现"身份验证失败"/"whoami 失败"

**原因**：访问令牌或 homeserver URL 不正确。

**解决方法**：确认 `MATRIX_HOMESERVER` 指向你的 homeserver（包含 `https://`，无尾部斜杠）。检查 `MATRIX_ACCESS_TOKEN` 是否有效——用 curl 测试：

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-server/_matrix/client/v3/account/whoami
```

如果返回你的用户信息，令牌有效。如果返回错误，请生成新令牌。

### "mautrix 未安装"错误

**原因**：未安装 `mautrix` Python 包。

**解决方法**：安装它：

```bash
pip install 'mautrix[encryption]'
```

或通过 Hermes extras：

```bash
cd ~/.hermes/hermes-agent && uv pip install -e ".[matrix]"
```

### 加密错误/"无法解密事件"

**原因**：缺少加密密钥、未安装 `libolm`，或机器人设备未被信任。

**解决方法**：
1. 确认系统上已安装 `libolm`（参见上方 E2EE 章节）。
2. 确保 `.env` 中设置了 `MATRIX_ENCRYPTION=true`。
3. 在你的 Matrix 客户端（Element）中，进入机器人的个人资料 → 会话 → 验证/信任机器人的设备。
4. 如果机器人刚加入加密房间，它只能解密*加入后*发送的消息。更早的消息无法访问。

### 从带有 E2EE 的旧版本升级

:::tip
如果你同时手动删除了 `crypto.db`，请参阅 E2EE 章节中的"删除加密存储"警告——还需要额外步骤来清除 homeserver 上的过期一次性密钥。
:::

如果你之前使用 `MATRIX_ENCRYPTION=true` 运行 Hermes，并正在升级到使用新的基于 SQLite 的加密存储的版本，机器人的加密身份已发生变化。你的 Matrix 客户端（Element）可能缓存了旧的设备密钥，并拒绝与机器人共享加密会话。

**症状**：机器人连接并在日志中显示"E2EE 已启用"，但所有消息显示"无法解密事件"，机器人从不响应。

**发生了什么**：旧的加密状态（来自之前的 `matrix-nio` 或基于序列化的 `mautrix` 后端）与新的 SQLite 加密存储不兼容。机器人创建了全新的加密身份，但你的 Matrix 客户端仍缓存了旧密钥，不会与密钥已更改的设备共享房间的加密会话。这是 Matrix 的安全特性——客户端将同一设备的身份密钥变更视为可疑行为。

**解决方法**（一次性迁移）：

1. **生成新的访问令牌**以获得全新的设备 ID。最简单的方式：

   ```bash
   curl -X POST https://your-server/_matrix/client/v3/login \
     -H "Content-Type: application/json" \
     -d '{
       "type": "m.login.password",
       "identifier": {"type": "m.id.user", "user": "@hermes:your-server.org"},
       "password": "***",
       "initial_device_display_name": "Hermes Agent"
     }'
   ```

   复制新的 `access_token` 并更新 `~/.hermes/.env` 中的 `MATRIX_ACCESS_TOKEN`。

2. **删除旧的加密状态**：

   ```bash
   rm -f ~/.hermes/platforms/matrix/store/crypto.db
   rm -f ~/.hermes/platforms/matrix/store/crypto_store.*
   ```

3. **设置恢复密钥**（如果你使用交叉签名——大多数 Element 用户都使用）。在 `~/.hermes/.env` 中添加：

   ```bash
   MATRIX_RECOVERY_KEY=EsT... 你的恢复密钥
   ```

   这让机器人在启动时使用交叉签名密钥自签，使 Element 立即信任新设备。若不设置，Element 可能将新设备视为未验证并拒绝共享加密会话。在 Element 的 **设置** → **安全与隐私** → **加密** 中找到你的恢复密钥。

4. **强制你的 Matrix 客户端轮换加密会话**。在 Element 中，打开与机器人的 DM 房间并输入 `/discardsession`。这会强制 Element 创建新的加密会话并与机器人的新设备共享。

5. **重启 gateway**：

   ```bash
   hermes gateway run
   ```

   如果设置了 `MATRIX_RECOVERY_KEY`，你应在日志中看到 `Matrix: cross-signing verified via recovery key`。

6. **发送新消息**。机器人应能正常解密并响应。

:::note
迁移后，升级*之前*发送的消息无法解密——旧的加密密钥已丢失。这只影响过渡期；新消息可正常工作。
:::

:::tip
**新安装不受影响。** 此迁移仅在你之前使用旧版 Hermes 配置了可用的 E2EE 并正在升级时才需要。

**为什么需要新的访问令牌？** 每个 Matrix 访问令牌绑定到特定的设备 ID。使用相同设备 ID 但新的加密密钥会导致其他 Matrix 客户端不信任该设备（它们将身份密钥的变更视为潜在的安全漏洞）。新的访问令牌获得一个没有过期密钥历史的新设备 ID，其他客户端会立即信任它。
:::

## 代理模式（macOS 上的 E2EE）

Matrix E2EE 需要 `libolm`，而该库无法在 macOS ARM64（Apple Silicon）上编译。`hermes-agent[matrix]` extra 仅限 Linux。如果你在 macOS 上，代理模式允许你在 Linux 虚拟机的 Docker 容器中运行 E2EE，而实际的 agent 在 macOS 上原生运行，可完整访问你的本地文件、记忆和技能。

### 工作原理

```
macOS（主机）：
  └─ hermes gateway
       ├─ api_server 适配器 ← 监听 0.0.0.0:8642
       ├─ AIAgent ← 单一数据源
       ├─ 会话、记忆、技能
       └─ 本地文件访问（Obsidian、项目等）

Linux 虚拟机（Docker）：
  └─ hermes gateway（代理模式）
       ├─ Matrix 适配器 ← E2EE 解密/加密
       └─ HTTP 转发 → macOS:8642/v1/chat/completions
           （无 LLM API 密钥，无 agent，无推理）
```

Docker 容器仅处理 Matrix 协议和 E2EE。消息到达时，容器解密消息并通过标准 HTTP 请求将文本转发给主机。主机运行 agent、调用工具、生成响应并流式返回。容器加密响应并发送到 Matrix。所有会话统一——CLI、Matrix、Telegram 及其他平台共享相同的记忆和对话历史。

### 第一步：配置主机（macOS）

启用 API 服务器，使主机接受来自 Docker 容器的请求。

在 `~/.hermes/.env` 中添加：

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=your-secret-key-here
API_SERVER_HOST=0.0.0.0
```

- `API_SERVER_HOST=0.0.0.0` 绑定到所有接口，使 Docker 容器可以访问。
- `API_SERVER_KEY` 是非回环绑定的必填项。请选择一个强随机字符串。
- API 服务器默认运行在端口 8642（如需更改，使用 `API_SERVER_PORT`）。

启动 gateway：

```bash
hermes gateway
```

你应该看到 API 服务器与其他已配置的平台一起启动。从虚拟机验证其可达性：

```bash
# 从 Linux 虚拟机
curl http://<mac-ip>:8642/health
```

### 第二步：配置 Docker 容器（Linux 虚拟机）

容器需要 Matrix 凭据和代理 URL。它**不需要** LLM API 密钥。

**`docker-compose.yml`：**

```yaml
services:
  hermes-matrix:
    build: .
    environment:
      # Matrix 凭据
      MATRIX_HOMESERVER: "https://matrix.example.org"
      MATRIX_ACCESS_TOKEN: "syt_..."
      MATRIX_ALLOWED_USERS: "@you:matrix.example.org"
      MATRIX_ENCRYPTION: "true"
      MATRIX_DEVICE_ID: "HERMES_BOT"

      # 代理模式——转发到主机 agent
      GATEWAY_PROXY_URL: "http://192.168.1.100:8642"
      GATEWAY_PROXY_KEY: "your-secret-key-here"
    volumes:
      - ./matrix-store:/root/.hermes/platforms/matrix/store
```

**`Dockerfile`：**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y libolm-dev && rm -rf /var/lib/apt/lists/*
RUN cd ~/.hermes/hermes-agent && uv pip install -e ".[matrix]"

CMD ["hermes", "gateway"]
```

这就是整个容器。无需 OpenRouter、Anthropic 或任何推理提供商的 API 密钥。

### 第三步：同时启动

1. 先启动主机 gateway：
   ```bash
   hermes gateway
   ```

2. 启动 Docker 容器：
   ```bash
   docker compose up -d
   ```

3. 在加密的 Matrix 房间中发送消息。容器解密消息，转发给主机，并将响应流式返回。

### 配置参考

代理模式在**容器侧**（精简 gateway）配置：

| 设置 | 说明 |
|---------|-------------|
| `GATEWAY_PROXY_URL` | 远程 Hermes API 服务器的 URL（例如 `http://192.168.1.100:8642`） |
| `GATEWAY_PROXY_KEY` | 用于身份验证的 Bearer token（必须与主机上的 `API_SERVER_KEY` 匹配） |
| `gateway.proxy_url` | 与 `GATEWAY_PROXY_URL` 相同，但在 `config.yaml` 中配置 |

主机侧需要：

| 设置 | 说明 |
|---------|-------------|
| `API_SERVER_ENABLED` | 设置为 `true` |
| `API_SERVER_KEY` | Bearer token（与容器共享） |
| `API_SERVER_HOST` | 设置为 `0.0.0.0` 以允许网络访问 |
| `API_SERVER_PORT` | 端口号（默认：`8642`） |

### 适用于任何平台

代理模式不限于 Matrix。任何平台适配器都可以使用它——在任意 gateway 实例上设置 `GATEWAY_PROXY_URL`，它将转发到远程 agent 而不是在本地运行。这适用于平台适配器需要在与 agent 不同的环境中运行的任何部署场景（网络隔离、E2EE 要求、资源限制）。

:::tip
会话连续性通过 `X-Hermes-Session-Id` 请求头维护。主机的 API 服务器按此 ID 跟踪会话，因此对话在消息之间持续存在，就像使用本地 agent 一样。
:::

:::note
**限制（v1）：** 来自远程 agent 的工具进度消息不会被中继回来——用户只能看到流式传输的最终响应，而非单个工具调用。危险命令审批提示在主机侧处理，不会中继给 Matrix 用户。这些问题可在未来版本中解决。
:::

### 机器人可以连接和发送，但忽略入站消息

**原因**：只有当同步载荷经由 mautrix 的 `handle_sync()` 机制分发时，Matrix 事件
处理器才会触发。若使用从不调用 `handle_sync()` 的原始 `client.sync()` 轮询，
适配器可能表现为已连接（发送正常），而入站消息永远到不了 `_on_room_message`。

**解决方法**：Hermes 使用一个显式的同步循环，在首次同步和每一次增量同步响应上都
调用 `client.handle_sync()`。这与上游 issue #7914 和已关闭的 PR #37807 中的诊断
一致，但保留了 Hermes 自己的后台维护任务（已加入房间的跟踪、邀请处理、E2EE 密钥
共享），而不是把完整生命周期委托给 `client.start()`。如果重启 gateway 后入站消息
仍然失败，请确认处理器是在首次同步之前注册的，并检查日志中是否有
`sync event dispatch error`。

### 同步问题/机器人落后

**原因**：长时间运行的工具执行可能延迟同步循环，或 homeserver 响应较慢。

**解决方法**：同步循环在出错时每 5 秒自动重试。检查 Hermes 日志中与同步相关的警告。如果机器人持续落后，请确保你的 homeserver 有足够的资源。

### 机器人离线

**原因**：Hermes gateway 未运行，或连接失败。

**解决方法**：检查 `hermes gateway` 是否正在运行。查看终端输出中的错误消息。常见问题：homeserver URL 错误、访问令牌过期、homeserver 不可达。

### "用户不被允许"/机器人忽略你

**原因**：你的用户 ID 不在 `MATRIX_ALLOWED_USERS` 中。

**解决方法**：将你的用户 ID 添加到 `~/.hermes/.env` 中的 `MATRIX_ALLOWED_USERS` 并重启 gateway。使用完整的 `@user:server` 格式。

### 机器人忽略整个房间

**原因**：设置了 `MATRIX_ALLOWED_ROOMS`，但当前房间 ID 不在列表中；或该房间要求提及，而消息没有提及机器人。

**解决方法**：把房间 ID 加入 `MATRIX_ALLOWED_ROOMS`；如果这是个人部署，也可以移除房间白名单。要查找房间 ID，请在 Element 中打开房间设置并查看**高级**。

### 桥接消息回环或回声

**原因**：某个桥接/appservice 傀儡账号把机器人的输出当作新的用户消息中继回来，或某个桥接使用了非标准的幽灵用户 ID。

**解决方法**：不要把桥接幽灵用户放进 `MATRIX_ALLOWED_USERS`，添加一条匹配的 `MATRIX_IGNORE_USER_PATTERNS` 条目，并保持 `MATRIX_PROCESS_NOTICES=false`，除非 notice 属于某个可信工作流的一部分。

## 安全

:::warning
始终设置 `MATRIX_ALLOWED_USERS`；对于共享/私有部署，还应设置 `MATRIX_ALLOWED_ROOMS`。若不设置，任何能在机器人已加入的房间中给它发消息的人都可能触发 agent。只授权你信任的人和房间——授权用户可完整访问 agent 的所有功能，包括工具调用和系统访问。
:::

有关保护 Hermes Agent 部署的更多信息，请参阅[安全指南](../security.md)。

## 注意事项

- **任何 homeserver**：兼容 Synapse、Conduit、Dendrite、matrix.org 或任何符合规范的 Matrix homeserver。无需特定的 homeserver 软件。
- **联邦**：如果你在联邦 homeserver 上，机器人可以与其他服务器的用户通信——只需将他们的完整 `@user:server` ID 添加到 `MATRIX_ALLOWED_USERS`。
- **自动加入**：机器人自动接受房间邀请并加入，加入后立即开始响应。
- **媒体支持**：Hermes 可以发送和接收图片、音频、视频和文件附件。媒体通过 Matrix 内容仓库 API 上传到你的 homeserver。
- **原生语音消息（MSC3245）**：Matrix 适配器自动为传出的语音消息添加 `org.matrix.msc3245.voice` 标志。这意味着 TTS 响应和语音音频在支持 MSC3245 的 Element 及其他客户端中以**原生语音气泡**形式呈现，而非普通音频文件附件。带有 MSC3245 标志的传入语音消息也会被正确识别并路由到语音转文字转录。无需任何配置——自动生效。