---
sidebar_position: 5
title: "定时任务（Cron）"
description: "用自然语言调度自动化任务，通过单一 cron 工具管理，并附加一个或多个 skill"
---

# 定时任务（Cron）

使用自然语言或 cron 表达式调度自动运行的任务。Hermes 通过单一 `cronjob` 工具暴露 cron 管理能力，采用动作式操作，而非分散的 schedule/list/remove 工具。

## Cron 当前能做什么

Cron 任务可以：

- 调度一次性或周期性任务
- 暂停、恢复、编辑、触发和删除任务
- 为任务附加零个、一个或多个 skill
- 将结果回传到来源会话、本地文件或已配置的平台目标
- 在全新的 agent 会话中运行，使用正常的静态工具列表
- 以**无 agent 模式**运行——按计划执行脚本，其 stdout 原样投递，零 LLM 参与（参见下方[无 agent 模式](#no-agent-mode-script-only-jobs)章节）

所有这些功能均可通过 `cronjob` 工具由 Hermes 自身使用，因此你可以用自然语言创建、暂停、编辑和删除任务——无需 CLI。

:::tip
**cron 任务在哪个模型上运行？** 触发时的解析顺序为：单任务固定 → `config.yaml` 中的 `cron.model` → `hermes model` 设置的全局默认值。

- **单任务固定**——由*你*通过仪表盘、`hermes cron create/edit --model … --provider …` 或编辑 `~/.hermes/cron/jobs.json` 设置。一旦设置便保持不变，直到你修改它。agent 的 `cronjob` 工具无法设置或更改单任务模型——推理固定归用户所有。
- **`cron.model` / `cron.model_provider`**——cron 任务群的默认值：每个未固定的任务都在该模型上运行，与你的聊天模型无关。设置一次（`hermes config set cron.model <name>`）后，用 `hermes model` 或 `/model` 切换聊天模型永远不会影响你的 cron 任务群。
- **全局默认值**——只有上述两者都未设置时，任务才会跟随 `hermes model`。Hermes 会在创建时对提供商和模型做**快照**，该快照即为任务的实际固定：如果之后你切换了全局默认值（`hermes model`、`/model`、`hermes config set model.default …`），任务会**继续在创建时的模型和提供商上运行**，并在每次运行时记录一条 INFO 日志说明差异。全局模型的变更永远不会让定时任务停止，无人值守的任务也永远不会悄悄继承到付费提供商/模型的切换（#44585）。若要把任务迁移到新的默认值，请固定它（`hermes cron edit <job_id> --provider <provider> --model <model>`），或设置 `cron.model` 一次性迁移整个任务群。快照机制出现之前创建的任务仍会跟随实时的全局默认值。

无论任务解析到哪个提供商，其提供商特定的请求设置（例如自定义提供商的 `request_overrides`，如 `extra_body`/`extra_headers`）都会像交互式会话一样带入定时运行。

对于无人值守的运行，`hermes setup --portal` 是摩擦最小的选项，因为 OAuth 刷新是自动的。参见 [Nous Portal](/integrations/nous-portal)。
:::

:::tip
**单任务推理强度。** 任务可以固定自己的思考级别，与模型固定相互独立：取值为 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra` 之一。设置后，它会在该任务的运行中覆盖全局 `agent.reasoning_effort` 和按模型设置的 `agent.reasoning_overrides`（`none` 表示禁用思考）。通过 `hermes cron create/edit --reasoning-effort high` 设置；编辑时传入空字符串可清除固定，重新跟随配置。（它刻意没有暴露在 agent 的 `cronjob` 工具上——模型配置仍由用户决定。）模型不支持的级别会在请求时由提供商截断或省略——在上限为 `high` 的模型上固定 `xhigh`，实际会以 `high` 运行。该固定对 `no_agent` 任务无效（没有可调节的 LLM 调用）。可以用它让重量级的定时分析以 `high` 运行，而廉价的周期性任务以 `minimal` 运行，无需改动你的全局默认值。
:::

:::warning
Cron 运行的会话不能递归创建更多 cron 任务。Hermes 在 cron 执行内部禁用了 cron 管理工具，以防止失控的调度循环。
:::

## 创建定时任务

### 在聊天中使用 `/cron`

```bash
/cron add "in 30m" "Remind me to check the build"
/cron add "every 2h" "Check server status"
/cron add "every 1h" "Summarize new feed items" --skill blogwatcher
/cron add "every 1h" "Use both skills and combine the result" --skill blogwatcher --skill maps
```

### 从独立 CLI

```bash
hermes cron create "every 2h" "Check server status"
hermes cron create "every 1h" "Summarize new feed items" --skill blogwatcher
hermes cron create "every 1h" "Use both skills and combine the result" \
  --skill blogwatcher \
  --skill maps \
  --name "Skill combo"
```

### 通过自然对话

直接向 Hermes 描述：

```text
Every morning at 9am, check Hacker News for AI news and send me a summary on Telegram.
```

Hermes 会在内部使用统一的 `cronjob` 工具。

## 分派前的配置校验

在为定时运行构建任何 agent 机制之前，调度器会校验该任务的配置确实能够产生一次成功的运行：

- 提供商 API key 能够解析（如果配置了 `fallback_providers` 链则跳过，因为回退路径可能挽救缺失的主 key），
- 附加的 skill 已就绪（没有缺失的必需环境变量、命令或凭证文件），
- 投递平台目标是已知的，并已配置 gateway 凭证（`local`/`origin` 目标从不检查）。

校验失败时，任务的 `last_status` 变为 `blocked_config`，只投递**一条**告警（不会每个 tick 重复），并且**不会发起任何 LLM 调用**——配置错误的任务永远不会消耗 token。下一次健康的运行会清除阻塞状态，这样将来再出现配置问题时会再次告警。

若要禁用校验并恢复旧行为（运行照常进行，并在执行过程中失败）：

```yaml
cron:
  preflight: false
```

或者：`hermes config set cron.preflight false`

## 将未固定的任务迁移到新的全局默认值

未固定的任务会停留在创建时的提供商/模型上，因此更改聊天模型永远不会改变（或停止）你的 cron 任务群。当你*确实*希望定时任务迁移时：

```bash
hermes cron edit <job_id> --provider <provider> --model <model>   # 单个任务
hermes config set cron.model <model>                               # 所有未固定的任务
```

`hermes config set model.default …` 和桌面端模型选择器会列出将保留原模型的未固定任务，便于你慎重决定。每当你编辑任务的提供商、模型或 base URL 时，已存储的快照都会刷新。

## 附带 skill 的 cron 任务

Cron 任务可以在运行 prompt（提示词）之前加载一个或多个 skill。

### 单个 skill

```python
cronjob(
    action="create",
    skill="blogwatcher",
    prompt="Check the configured feeds and summarize anything new.",
    schedule="0 9 * * *",
    name="Morning feeds",
)
```

### 多个 skill

Skill 按顺序加载。Prompt 作为任务指令叠加在这些 skill 之上。

```python
cronjob(
    action="create",
    skills=["blogwatcher", "maps"],
    prompt="Look for new local events and interesting nearby places, then combine them into one short brief.",
    schedule="every 6h",
    name="Local brief",
)
```

当你希望定时 agent 继承可复用的工作流，而不必将完整的 skill 文本塞入 cron prompt 本身时，这非常有用。

## 在指定项目目录中运行任务

Cron 任务默认与任何代码仓库脱离运行——不加载 `AGENTS.md`、`CLAUDE.md` 或 `.cursorrules`，终端/文件/代码执行工具从 gateway 启动时的工作目录运行。传入 `--workdir`（CLI）或 `workdir=`（工具调用）可更改此行为：

```bash
# 独立 CLI（schedule 和 prompt 为位置参数）
hermes cron create "every 1d at 09:00" \
  "Audit open PRs, summarize CI health, and post to #eng" \
  --workdir /home/me/projects/acme
```

```python
# 在聊天中，通过 cronjob 工具
cronjob(
    action="create",
    schedule="every 1d at 09:00",
    workdir="/home/me/projects/acme",
    prompt="Audit open PRs, summarize CI health, and post to #eng",
)
```

设置 `workdir` 后：

- 该目录中的 `AGENTS.md`、`CLAUDE.md` 和 `.cursorrules` 会被注入系统 prompt（发现顺序与交互式 CLI 相同）
- `terminal`、`read_file`、`write_file`、`patch`、`search_files` 和 `execute_code` 均以该目录为工作目录
- 路径必须是已存在的绝对目录——相对路径和不存在的目录在创建/更新时会被拒绝
- 编辑时传入 `--workdir ""`（或工具中的 `workdir=""`）可清除该设置并恢复原有行为

:::note 隔离
每次 agent 运行都会将其 `workdir` 绑定到该次运行的唯一任务标识。设置了 workdir 的任务因此可使用正常的并行池，不会修改进程全局终端状态，也不会在并发运行之间泄漏路径。如需限制 cron 的总并发量，请设置 `cron.max_parallel_jobs`。
:::

## 编辑任务

无需删除并重建任务来修改它们。

:::tip 任务引用
下方（以及[生命周期操作](#lifecycle-actions)中）的 `<job_id>` 占位符也接受任务名称（不区分大小写）——当你记得 `morning-digest` 但不记得十六进制 ID 时很方便。精确的任务 ID 优先于名称匹配；如果引用不是 ID 且名称匹配到多个任务，命令会拒绝执行并打印候选 ID 供你消歧义。
:::

### 聊天

```bash
/cron edit <job_id> --schedule "every 4h"
/cron edit <job_id> --prompt "Use the revised task"
/cron edit <job_id> --skill blogwatcher --skill maps
/cron edit <job_id> --remove-skill blogwatcher
/cron edit <job_id> --clear-skills
```

### 独立 CLI

```bash
hermes cron edit <job_id> --schedule "every 4h"
hermes cron edit <job_id> --prompt "Use the revised task"
hermes cron edit <job_id> --skill blogwatcher --skill maps
hermes cron edit <job_id> --add-skill maps
hermes cron edit <job_id> --remove-skill blogwatcher
hermes cron edit <job_id> --clear-skills
```

注意：

- 重复使用 `--skill` 会替换任务已附加的 skill 列表
- `--add-skill` 追加到现有列表，不替换
- `--remove-skill` 删除指定的已附加 skill
- `--clear-skills` 删除所有已附加的 skill

## 生命周期操作 {#lifecycle-actions}

Cron 任务现在拥有比创建/删除更完整的生命周期。

### 聊天

```bash
/cron list
/cron pause <job_id>
/cron resume <job_id>
/cron run <job_id>
/cron remove <job_id>
```

### 独立 CLI

```bash
hermes cron list
hermes cron pause <job_id_or_name>
hermes cron resume <job_id_or_name>
hermes cron run <job_id_or_name>
hermes cron remove <job_id_or_name>
hermes cron edit <job_id_or_name> [...flags]
hermes cron status
hermes cron tick
```

各操作说明：

- `pause` — 保留任务但停止调度
- `resume` — 重新启用任务并计算下次运行时间
- `run` — 在下次调度器 tick 时触发任务
- `remove` — 彻底删除任务
- `edit` — 修改调度、prompt、投递方式等

**基于名称的查找。** 四个会产生变更的动词（`pause`、`resume`、`run`、`remove`、`edit`）以及 agent 的 `cronjob` 工具现在都接受用任务**名称**（不区分大小写）代替十六进制 ID。agent 和 CLI 都会优先匹配精确的 ID（如果存在）；名称匹配存在歧义时（多个任务同名），命令会拒绝执行并列出全部候选 ID，供你显式选择。名称并不唯一，因此这道防线很关键——它可以避免在两个任务同名时悄悄改错任务。

### 以暂停状态创建任务（安全的金丝雀）

创建金丝雀任务，而不会出现「先创建再暂停」的调度竞争：

```bash
hermes cron create "every 1h" "Post the digest" --paused --paused-reason "Awaiting review"
hermes cron resume <job_id>
```

`--paused` 会在第一次加锁写入时存储 `enabled: false`、`state: paused`、`next_run_at: null`、暂停时间戳以及可审计的原因，并且不注册触发器。省略原因时会存储 "Created paused; awaiting operator approval."。省略 `--paused` 则保持正常的启用状态创建。`--paused-reason` 需要配合 `--paused` 使用；无效值会在持久化之前被拒绝。

同样的 `paused` 布尔值和可选的 `paused_reason` 字符串也被 `cron.jobs.create_job`、cron 管理工具的 `create` 动作、gateway 的 `POST /api/jobs` 以及仪表盘的 `POST /api/cron/jobs` 接受。恢复会调度下一次未来的运行。暂停阻止的是自动触发，而不是操作员的覆盖：现有的显式 **Run now** / 强制运行行为仍然可用，并且可以恢复并运行该任务。它不是针对有权运行任务的操作员的安全边界。

## Agent 管理的调度（管理 cron 任务的 cron 任务）

默认情况下，*由*调度器启动的 agent 不能使用 `cronjob` 工具——定时任务不能创建、编辑或删除其他任务。可通过 `config.yaml` 选择启用：

```yaml
cron:
  allow_agent_scheduling: true   # 默认：false
```

启用后，定时 agent 可以像任何聊天会话一样管理 cron 表：在定时工作中安排后续的一次性任务、调整自身的频率，或运行一个协调整张表的「cron 管理员」任务（先 list，再按需 update/remove/create）。两个特性保证了这一切的合理性：

- **一张扁平、归用户所有的表。** 从 cron 运行中创建的任务与其他所有任务一样落在同一个 `jobs.json` 中，没有特殊的归属——你可以像自己创建的一样列出、编辑或删除它们。
- **不存在悬空的投递。** cron 运行是短暂的，因此在其中使用 `deliver: origin` 会在**创建时**解析为创建者任务自身的具体目标（`platform:chat_id[:thread_id]`，如果创建者任务不投递到任何地方则为 `local`）。由定时 agent 创建的任务永远不会把输出指向一个已不存在的会话。显式目标（`local`、`all`、`telegram:<chat_id>`）会被原样遵守。

优先使用更新现有任务的 prompt（先 list，再按 ID update），而不是每次运行都创建新任务的 prompt。

## 工作原理

**Cron 执行由 gateway 守护进程处理。** Gateway 每 60 秒 tick 一次调度器，在隔离的 agent 会话中运行到期的任务。

```bash
hermes gateway install     # 安装为用户服务
sudo hermes gateway install --system   # Linux：服务器开机启动的系统服务
hermes gateway             # 或在前台运行

hermes cron list
hermes cron status
```

### Gateway 调度器行为

每次 tick 时，Hermes：

1. 从 `~/.hermes/cron/jobs.json` 加载任务
2. 对照当前时间检查 `next_run_at`
3. 为每个到期任务启动全新的 `AIAgent` 会话
4. 可选地将一个或多个已附加的 skill 注入该新会话
5. 将 prompt 运行至完成
6. 投递最终响应
7. 更新运行元数据和下次调度时间

`~/.hermes/cron/.tick.lock` 文件锁可防止重叠的调度器 tick 重复运行同一批任务。

### 执行历史 {#execution-history}

Hermes 会在执行器或调度提供程序分派之前，将每次已领取的 cron 尝试记录到当前 profile 的 `~/.hermes/cron/executions.db`。尝试会依次进入 `claimed`、`running`，然后进入不可变的终态：`completed`、`failed` 或 `unknown`。重启后，只有原 PID 与进程启动时间指纹能够证明所有者已经消失时，Hermes 才会将遗留尝试标记为 `unknown`。未知尝试仅用于审计，绝不会自动重跑。

使用 `hermes cron runs [job-id] --limit 20`（别名：`history`）查看最近的尝试。终态历史有界，活动尝试不会被清理；快速备份也包含该账本。

定时尝试还会记录其确切的计划时刻，与领取时间分开存放。如果旧的 `jobs.json` 快照重新武装了一个在保留的账本中已记录为完成的时刻，Hermes 会跳过这次重放，并重新锚定周期性任务。即使快照早于分派标记，或原运行启动较晚，这一机制同样有效。显式的手动运行不会占用某个计划时刻的标识。

这并不是「恰好一次」的副作用保证：没有标识的旧行、已清理的历史、不可用的账本以及被中断的尝试都无法证明已完成。将账本本身恢复到较旧的备份也会移除这些证据。外部触发回调标识的是当前被接受的存储领取，而不是回调中缺失的上游计划时段。

### 重复失败审查提醒

每个任务都会跟踪一个 `failure_streak`——连续失败的运行次数（投递失败不计入）。在到达 agent 之前就失败的运行——更新只应用了一半后出现错误的导入、无法构建的提供商客户端——与 agent 自身失败的运行同样计数并告警。当*周期性*任务的连续失败次数达到阈值时，投递到聊天的失败消息会附带一条审查提醒，告诉你该任务已连续失败 N 次，并建议你修复、暂停（`hermes cron pause <job>`）或删除它。任何一次成功运行都会重置计数，`hermes cron list` 会在失败任务的上次运行旁显示该计数。一次性任务从不提醒。

```yaml
cron:
  failure_nudge_threshold: 3   # 默认值；0 表示禁用提醒
```

### 失败事件：确认已知失败

一个以*相同*错误反复失败的周期性任务会在每次运行时通知你。每次失败还会被记录为持久的**事件（incident）**，以任务加上错误文本的规范化签名为键，存储在与执行历史相同的按 profile 划分的账本数据库中。

```bash
hermes cron incidents                 # 列出事件（最新活动在前）
hermes cron incidents --state alerted # 过滤：detected | alerted | closed
hermes cron incidents ack <id>        # 确认——停止重复通知
```

确认一个事件只会静默该签名对应的每次运行失败通知。其他一切都不变：运行历史仍记录每次失败，连续失败计数继续累加，而一旦任务开始以*不同的*错误失败，就会生成新事件并再次触发告警。成功运行不会影响事件——事件按签名区分，而不是按任务区分。

事件生命周期：`detected`（已记录失败）→ `alerted`（至少有一次失败通知送达）→ `closed`（已确认；对该签名而言是终态）。存储的错误文本在写入前会进行密钥脱敏和截断。

记录始终开启，忽略它不会带来任何代价——在你显式 `ack` 之前，任何通知都不会被抑制。

### 任务群健康检查：`hermes cron doctor`

`hermes cron doctor` 是针对每个活动任务的只读健康检查。它按任务分组打印问题，发现任何需要处理的问题时以 `1` 退出（健康时为 `0`），因此可用于终端、看门狗脚本或 CI 风格的冒烟检查：

```bash
hermes cron doctor
```

每个活动任务的检查项：

- 上次运行失败（`last_status` 不是 ok，附带记录的错误），
- 上次投递失败（输出已产生但从未送达你），
- `next_run_at` 缺失，或停留在过去且超过 15 分钟的 ticker 宽限窗口——即「任务悄悄没有触发」的信号（调度器已停止、gateway 宕机，或触发领取卡住），
- 脚本缺失、不是文件，或解析到 `HERMES_HOME/scripts` 之外，
- `no_agent` 任务没有脚本，
- 配置的 `workdir` 已不存在。

Doctor 永远不会修改任务或状态——它只做报告。深入排查被标记的任务时，可配合 `hermes cron incidents`（持久的失败记录）和 `hermes cron runs`（尝试账本）使用。

## 投递选项 {#delivery-options}

调度任务时，你可以指定输出的去向：

| 选项 | 说明 | 示例 |
|--------|-------------|---------|
| `"origin"` | 回传到任务创建的来源 | 消息平台上的默认值 |
| `"local"` | 仅保存到本地文件（`~/.hermes/cron/output/`） | CLI 上的默认值 |
| `"telegram"` | Telegram 主频道 | 使用 `TELEGRAM_HOME_CHANNEL` |
| `"telegram:123456"` | 按 ID 指定的 Telegram 会话 | 直接投递 |
| `"telegram:-100123:17585"` | 指定 Telegram 话题 | `chat_id:thread_id` 格式 |
| `"discord"` | Discord 主频道 | 使用 `DISCORD_HOME_CHANNEL` |
| `"discord:#engineering"` | 按频道名指定的 Discord 频道 | 按频道名 |
| `"slack"` | Slack 主频道 | |
| `"whatsapp"` | WhatsApp 主账号 | |
| `"signal"` | Signal | |
| `"matrix"` | Matrix 主房间 | |
| `"mattermost"` | Mattermost 主频道 | |
| `"email"` | 邮件 | |
| `"sms"` | 通过 Twilio 发送 SMS | |
| `"homeassistant"` | Home Assistant | |
| `"dingtalk"` | 钉钉 | |
| `"feishu"` | 飞书/Lark | |
| `"wecom"` | 企业微信 | |
| `"weixin"` | 微信（WeChat） | |
| `"bluebubbles"` | BlueBubbles（iMessage） | |
| `"qqbot"` | QQ Bot（腾讯 QQ） | |
| `"bot-chat"` | 本 profile 的规范 Bot Chat——机器人读取输出并作出响应 | 仅限本机 |
| `"bot-chat:research"` | 另一个本地 profile 的 Bot Chat | 创建时校验 |
| `"all"` | 扇出到所有已连接的主频道 | 触发时解析 |
| `"telegram,discord"` | 扇出到指定的一组频道 | 逗号分隔列表 |
| `"origin,all"` | 投递到来源**加上**所有其他已连接频道 | 可组合任意 token |

Agent 的最终响应会自动投递到配置的 `deliver:` 目标——agent 自己不发送消息，因此 cron prompt 中无需调用任何东西。

### 投递失败是一种独立状态

执行与投递是分开跟踪的。当 agent 运行成功但输出从未到达目标时（平台 5xx、限速、会话过期、适配器没有返回发送成功的正面证据），任务会记录 `last_status: delivery_failed`——绝不会是普通的 `ok`——并在 `last_delivery_error` 中记录原因。`hermes cron list` 会以黄色显示为 `delivery_failed: <reason>`，`hermes cron doctor` 会将其报告为投递问题，手动的 `cronjob run` 会报告 `success: false` 并附带投递错误。投递失败不计入任务的 `failure_streak`（agent 已完成了它的工作）；下一次完全成功的运行会将状态恢复为 `ok`。

### Bot Chat 投递（`bot-chat`）

`bot-chat` 会把输出**作为一条真实消息投递到某个 profile 的规范「Bot Chat」会话中**。与其他所有目标不同——那些目标的接收方是阅读频道的人——这里的接收方是机器人自己：它把输出当作一条传入消息接收，处理其中需要处理的内容，并在其聊天中作出响应。当定时输出需要被*处理*而不仅仅是发布时，请使用它。

- `bot-chat`（裸写）指向任务自身所在的 profile。
- `bot-chat:<profile>` 指向**同一台机器上**的另一个 profile。创建任务时会用 `hermes profile list` 校验名称；其他 gateway 或机器上的 profile 永远无法被指定，因此不同机器上同名的 profile 不会产生歧义。
- 每次投递都会让目标机器人消耗一整轮 agent 轮次——请注意调度频率。
- 可与其他目标组合（`bot-chat,telegram`），但永远不会包含在 `all` 中。
- 如果规范聊天已在支持邮箱的桌面端/TUI 后端中打开，无论机器人空闲还是忙碌，投递都会**立即被持久排队**。只有该在线所有者会运行传入的轮次；cron 不会启动一个与之竞争的 CLI 写入者。没有在线邮箱所有者时，现有的 `hermes chat -c "Bot Chat" --create-if-missing` 通道仍然可用（正常的会话所有权检查依然适用）。
- **已排队不等于已完成。** Cron 会在 `last_delivery_queued` 中记录回执 ID 以及 `queued`/`claimed` 状态，投递结果为 `queued`（既非已投递也非失败）。成功的任务显示为 `delivery_queued`；其他目标上的真实错误仍优先作为投递失败处理。机器人可能稍后才完成。目标 profile 中 `runtime/bot_live_delivery/<receipt-id>.json` 里的持久回执才是权威的；cron 的历史状态不会自动刷新。
- 重新检查同一次执行会查看其已有的回执，即使所有者已经消失。接受之后它绝不会回退到另一个写入者。`failed`、`cancelled` 或 `ambiguous` 的回执不会被自动重放；在有意开始新工作之前，请先检查聊天和回执。每次新的 cron 执行都有不同的投递 ID。

### 路由意图（`all`）

`all` 让你将一个 cron 任务发送到所有已配置的消息频道，无需逐一列举名称。它在**触发时解析**，因此在你配置 `TELEGRAM_HOME_CHANNEL` 之前创建的任务，会在下次 tick 时自动纳入 Telegram。

语义：`all` 展开为所有已配置主频道的平台。零个也没问题；任务只是没有投递目标，并在上游记录为投递失败。

`all` 可与显式目标组合。`origin,all` 投递到来源会话**加上**所有其他已连接的主频道，按 `(platform, chat_id, thread_id)` 去重。

### Telegram cron 话题（`TELEGRAM_CRON_THREAD_ID`）

启用 Telegram 话题模式后，根 DM 被保留为系统大厅——发送到那里的回复会被拒绝并附带大厅提示，`reply_to_message_id` 会被丢弃，因此你无法回复落在主聊天中的 cron 消息。

将 cron 指向专用的论坛话题：

1. 在 Telegram 中打开机器人 DM，创建一个名为 `Cron` 的话题。长按话题标题 → **复制链接**；末尾的整数即为该话题的 `message_thread_id`。
2. 在 `.env` 中设置 `TELEGRAM_CRON_THREAD_ID=<该 id>`。

这仅适用于 cron 投递。`TELEGRAM_HOME_CHANNEL_THREAD_ID`（用于其他地方，如重启通知）不受影响。显式的 `deliver="telegram:chat_id:thread_id"` 目标仍优先于环境变量。对 cron 消息的回复现在会进入已有的话题会话，你可以直接在其中操作。

### 响应包装

默认情况下，投递的 cron 输出会带有页眉和页脚，以便接收方知道这来自定时任务：

```
Cronjob Response: Morning feeds
-------------

<agent output here>

Note: The agent cannot see this message, and therefore cannot respond to it.
```

若要投递不带包装的原始 agent 输出，将 `cron.wrap_response` 设为 `false`：

```yaml
# ~/.hermes/config.yaml
cron:
  wrap_response: false
```

### 推送通知（`cron.delivery.notify`）

Cron 输出是*最终*投递，而不是进度消息，因此默认会在发送时设置平台的通知标志——在 Telegram 上，这意味着即使适配器的通知模式为 `important`（否则会以 `disable_notification=true` 发送，而用户会把静默的简报报告为「从未送达」），简报也会触发推送。若要恢复静默投递：

```yaml
# ~/.hermes/config.yaml
cron:
  delivery:
    notify: false   # 默认：true
```

该标志同时作用于文本发送和所有媒体附件，因此一次运行绝不会出现一部分推送、另一部分静默的情况。

### 投递确认与 `UNVERIFIED` 状态

只有在适配器给出正面证据时，实时适配器投递才会被记录为已投递：一个明确的 `success`，且不是被过滤丢弃的结果（`delivered: false`），再加上 `message_id` 或 `raw_response`。带有 `success` 但两种证据都没有的结果——Slack、Matrix 和 Mattermost 适配器返回的就是这种形态——仍会被接受（它并不证明失败），但这次运行会在任务上记录为 `last_delivery_unverified`，并显示在 `hermes cron list` 中：

```
⚠ Delivery UNVERIFIED: adapter acked slack:C0123456 without message_id/raw_response
```

并在 `hermes cron doctor` 中显示为 `last delivery unverified (...)`。下一次带证据投递的运行会清除该标记。空载荷（没有文本也没有媒体）永远不会交给适配器；它会失败关闭，并在 `last_delivery_error` 中报告，而不是被记录为已投递。

### 可继续任务（回复 cron 投递）

默认情况下，cron 投递是「发完即忘」的：消息发送出去，但不会进入聊天的对话历史，
因此如果你回复它，agent 并不记得自己说过什么。将任务设为**可继续**后，投递的简报
就变成一段你可以回复进去的对话——agent 会把简报保留在上下文中，而不会反问
「Task #2 是什么？」。

选择性启用，**默认关闭**。可在配置中全局启用，或通过 `cronjob` 工具的
`attach_to_session` 按任务启用（会覆盖该任务的全局设置）：

```yaml
# ~/.hermes/config.yaml
cron:
  mirror_delivery: false   # 设为 true 使 cron 投递可继续
```

行为为**优先使用话题**，范围限定在任务自身的对话：

- **支持话题的平台**（Telegram 话题、Discord/Slack 话题）：每次投递都会新建
  专用话题，并将简报植入该话题的会话中，因此在话题内回复即可带完整上下文继续。
  周期性任务（例如每日简报）每次运行都会新建一个话题，使每次投递的后续讨论相互隔离。
- **仅 DM 的平台**（WhatsApp、Signal、SMS）：不存在话题，因此简报会被镜像进
  来源 DM 会话——DM 本身就是继续的载体。

只有任务**自身的对话**会被触及：

- 创建任务时所在的**来源聊天**；
- 当 `deliver: origin` 没有捕获到来源时（由脚本或 API 而非在线 gateway 聊天创建的任务）
  使用的**主频道回退**——用户的主要对话代替来源；
- 任务的**单个显式 `platform:chat` 目标**，但仅当任务本身通过 `attach_to_session: true`
  选择启用时——由任务作者声明该目标是一段对话。仅凭全局 `mirror_delivery` 标志，
  永远不会让一个显式指定的聊天变为可继续。

广播/扇出目标（`all`、裸平台主频道）永远不会被设为可继续。镜像以一条带标签的用户轮次
（`[Cron delivery: <task name>]`）写入，使对话历史在所有模型提供商之间都保持交替安全。

#### 平铺频道内继续（Slack） {#flat-in-channel-continuation-slack}

上面的优先话题行为每次投递都会新建专用话题。如果你希望可继续任务**平铺落在频道
时间线**中——不新建话题——将 Slack 的**继续投递方式**设为 `in_channel`：

```yaml
# ~/.hermes/config.yaml
slack:
  cron_continuable_surface: in_channel   # 默认：thread
  reply_in_thread: false                 # 必需搭配（见下）
  require_mention: false                 # 纯文本回复即可继续任务
```

在 `in_channel` 模式下，简报作为普通的顶层频道消息投递（不新建话题），你的回复通过
频道的共享会话继续任务。三项设置协同工作：

- **`cron_continuable_surface: in_channel`**——投递时跳过新建话题。
- **`reply_in_thread: false`**（必需）——让机器人在频道中*平铺*回复你，并将其
  归入简报所植入的同一个整频道会话。缺少它时继续功能仍可用，但回复会出现在话题里
  （安全回退为话题式继续，绝不会丢失回复——网关会在启动时记录一条警告便于发现不匹配）。
- **`require_mention: false`**（或将该频道加入 `free_response_channels`）——这样你
  可以用纯文本消息回复；否则机器人只在你每次 `@` 提及它时才被唤醒。

由于继续载体是**整频道**会话，它是共享的：频道里的其他闲聊——以及第二个可继续的
in_channel 任务——都会加入同一段滚动对话。这是「平铺在频道中」的固有取舍，与
`reply_in_thread: false` 用户已经接受的取舍相同；若希望每次投递的后续讨论相互隔离，
请使用默认的 `thread` 方式。

这目前是 Slack 的能力。其他平台接受该键，但会回退到 `thread` 方式（它们的继续原语
不同）；该选择按平台设置，位于各平台的配置下。这是网关侧的配置项——`/restart` 即可
生效；无需重新安装 Slack 应用。

:::note 1:1 私信（DM）
`cron_continuable_surface` 是**频道**设置——1:1 私信没有「话题 vs 时间线」的区分
（私信本身就是平铺的），因此该键在私信中无效。决定私信 cron 投递是否可继续的是另一个
已有的独立开关 **`slack.dm_top_level_threads_as_sessions`**：

- **`false`**——所有顶层私信共享同一个滚动私信会话，因此可继续的 cron 简报与你的回复
  落在**同一个**会话里，任务得以带上下文继续。这正是私信中可继续 cron 所需要的。
- **`true`**（默认）——每条顶层私信消息各自成为独立会话，因此对已投递简报的回复会开启
  一个**全新**、不含该简报记录的会话。此模式下继续功能不可用（对 cron 或任何平铺投递皆然）。

所以，若要让 cron 任务在 1:1 私信中可继续，请设置
`slack.dm_top_level_threads_as_sessions: false`。私信不需要（也会忽略）
`cron_continuable_surface`。
:::

### 静默抑制

如果 agent 的最终响应中包含 `[SILENT]`，投递将被完全抑制。输出仍会保存到本地以供审计（位于 `~/.hermes/cron/output/`），但不会向投递目标发送任何消息。

这对于只在出现问题时才需要上报的监控任务很有用：

```text
Check if nginx is running. If everything is healthy, respond with only [SILENT].
Otherwise, report the issue.
```

失败的任务无论 `[SILENT]` 标记如何都会投递——只有成功的运行才能被静默。对于安静的监控类任务，请在 prompt 中要求 agent 在没有任何情况需要报告时仅回复 `[SILENT]`。

## 脚本超时

预运行脚本（通过 `script` 参数附加）的默认超时为 3600 秒（1 小时）。它只约束**脚本本身**——基于 skill / 由 LLM 驱动的任务使用另一套空闲预算，不受此值限制。如果你的脚本需要不同的限制，可以修改它：

```yaml
# ~/.hermes/config.yaml
cron:
  script_timeout_seconds: 1800   # 30 分钟
```

或设置 `HERMES_CRON_SCRIPT_TIMEOUT` 环境变量。解析顺序为：环境变量 → config.yaml → 默认 3600 秒。

Cron 还会限制运行后会话与 agent 资源清理的时长。这发生在 LLM 轮次返回之后，因此与空闲超时相互独立。默认每项清理操作 10 秒。如果某个存储或客户端的终结器迟迟不返回，调度器会记录错误、释放该任务的运行中保护，并允许后续运行正常分派，而不是永远跳过该任务。

```yaml
# ~/.hermes/config.yaml
cron:
  cleanup_timeout_seconds: 10
```

只有在需要恢复旧版无上限清理行为时，才设置 `cleanup_timeout_seconds: 0`。

## 媒体发送超时

当 cron 投递包含通过实时 gateway 适配器发送的媒体附件（生成的 PDF、TTS 音频、导出的报告）时，每个附件的上传都受超时限制——默认 300 秒。在慢速上行链路上发送大文件可能需要更长时间：

```yaml
# ~/.hermes/config.yaml
cron:
  media_send_timeout_seconds: 600   # 每个附件 10 分钟
```

或设置 `HERMES_CRON_MEDIA_SEND_TIMEOUT` 环境变量。解析顺序为：环境变量 → config.yaml → 默认 300 秒。超时的附件会在任务的运行状态中记录为部分投递失败（文本仍会送达）。

## Bot Chat 投递超时

`bot-chat` 投递会在目标机器人的聊天中运行一整轮 agent 轮次，因此它的时限以分钟而非秒计——默认 600 秒：

```yaml
# ~/.hermes/config.yaml
cron:
  bot_chat_delivery_timeout_seconds: 900
```

超时的投递会记录在 `last_delivery_error` 中；机器人的轮次仍可能自行完成。

## 无 agent 模式（纯脚本任务） {#no-agent-mode-script-only-jobs}

对于不需要 LLM 推理的周期性任务——经典的看门狗、磁盘/内存告警、心跳、CI ping——在创建时传入 `no_agent=True`。调度器按计划运行你的脚本，并直接投递其 stdout，完全跳过 agent：

```bash
hermes cron create "every 5m" \
  --no-agent \
  --script memory-watchdog.sh \
  --deliver telegram \
  --name "memory-watchdog"
```

语义：

- 脚本 stdout（去除首尾空白）→ 原样作为消息投递。
- **stdout 为空 → 静默 tick**，不投递。这是看门狗模式："只在出现问题时才说话"。
- 非零退出或超时 → 投递错误告警，确保损坏的看门狗不会静默失败。
- 最后一行输出 `{"wakeAgent": false}` → 静默 tick（与 LLM 任务使用相同的门控）。
- 无 token、无模型、无 provider 回退——任务永远不会触及推理层。

`.sh` / `.bash` 文件在可用时使用 `PATH` 中的 `bash` 运行，否则使用 `/bin/bash`（这在 Windows Git Bash 上很重要）。其他文件在当前 Python 解释器（`sys.executable`）下运行。脚本必须解析到 `$HERMES_HOME/scripts/` 之内——只要解析后的目标仍在该目录中，相对名称、绝对路径和以 `~` 开头的路径都会被接受；逃逸出该目录的路径会被拒绝。子进程环境会被净化（`_sanitize_subprocess_env`）：提供商 API 凭证及其他由 Hermes 管理的密钥**不会**被 cron 脚本继承。

### Agent 为你设置这些

`cronjob` 工具的 schema 直接向 Hermes 暴露了 `no_agent`，因此你可以在聊天中描述一个看门狗，让 agent 来配置它：

```text
Ping me on Telegram if RAM is over 85%, every 5 minutes.
```

Hermes 会通过 `write_file` 将检查脚本写入 `~/.hermes/scripts/`，然后调用：

```python
cronjob(action="create", schedule="every 5m",
        script="memory-watchdog.sh", no_agent=True,
        deliver="telegram", name="memory-watchdog")
```

当消息内容完全由脚本决定时（看门狗、阈值告警、心跳），它会自动选择 `no_agent=True`。同一工具也让 agent 可以暂停、恢复、编辑和删除任务——整个生命周期都通过聊天驱动，无需任何人接触 CLI。

参见[纯脚本 Cron 任务指南](/guides/cron-script-only)获取实际示例。

## 通过 `context_from` 串联任务

Cron 任务在隔离的会话中运行，不保留之前运行的记忆。但有时一个任务的输出恰好是下一个任务所需的输入。`context_from` 参数自动建立这种连接——任务 B 的 prompt 在运行时会将任务 A 的最新输出作为上下文前置。

```python
# 任务 1：收集原始数据
cronjob(
    action="create",
    prompt="Fetch the top 10 AI/ML stories from Hacker News. Save them to ~/.hermes/data/briefs/raw.md in markdown format with title, URL, and score.",
    schedule="0 7 * * *",
    name="AI News Collector",
)

# 任务 2：分类——接收任务 1 的输出作为上下文
# 从 cronjob(action="list") 获取任务 1 的 ID
cronjob(
    action="create",
    prompt="Read ~/.hermes/data/briefs/raw.md. Score each story 1–10 for engagement potential and novelty. Output the top 5 to ~/.hermes/data/briefs/ranked.md.",
    schedule="30 7 * * *",
    context_from="<job1_id>",
    name="AI News Triage",
)

# 任务 3：发布——接收任务 2 的输出作为上下文
cronjob(
    action="create",
    prompt="Read ~/.hermes/data/briefs/ranked.md. Write 3 tweet drafts (hook + body + hashtags). Deliver to telegram:7976161601.",
    schedule="0 8 * * *",
    context_from="<job2_id>",
    name="AI News Brief",
)
```

**工作原理：**

- 任务 2 触发时，Hermes 从 `~/.hermes/cron/output/{job1_id}/*.md` 读取任务 1 的最新输出
- 该输出自动前置到任务 2 的 prompt
- 任务 2 无需硬编码"读取此文件"——它以上下文形式接收内容
- 链可以是任意长度：任务 1 → 任务 2 → 任务 3 → …

**`context_from` 接受的格式：**

| 格式 | 示例 |
|--------|---------|
| 单个任务 ID（字符串） | `context_from="a1b2c3d4"` |
| 多个任务 ID（列表） | `context_from=["job_a", "job_b"]` |

输出按列表顺序拼接。

**连续性：携带上一次运行的输出**

设置 `continuity=true` 后，任务会把它*自己*最近一次的输出注入到每次运行中。周期性任务通常每次运行都从「失忆」开始——新闻侦察任务会重复报告相同的新闻，监控任务会针对同一状况重复告警。开启连续性后，任务醒来时就能看到上次报告的内容，从而去重并从上次停下的地方继续：

```python
cronjob(
    action="create",
    prompt="Scan HN and arXiv for new agent-tooling papers. Report only items NOT already covered in your previous run's output.",
    schedule="every 6h",
    continuity=True,
    name="Agent Tooling Scout",
)
```

第一次运行没有上一次输出，因此 prompt 按原样运行。选择上下文时会跳过静默的监控 tick（`no_change`）、空输出以及 `wakeAgent=false` 的审计记录，因此一段安静期会保留最近一次有实质内容的输出。审计文件仍保留在磁盘上。错误文档仍有资格为下一次运行提供恢复上下文；这不是一个只保留成功记录的历史过滤器。在之后的运行中，上一次输出会带着连续性说明（"避免重复已经报告过的内容"）前置到 prompt。它可以与上游任务自由组合（`context_from=["<other_job_id>"]` 加上 `continuity=true`），在 update 时设置 `continuity=false` 可关闭它，同时保留其他 `context_from` 条目。在内部，该标志以保留的 `self` 条目形式存储在 `context_from` 中。

在 CLI 中：`hermes cron create "every 6h" "Scan for news" --continuity`，以及 `hermes cron edit <job_id> --continuity` / `--no-continuity` 可在现有任务上切换它。仪表盘的 cron 编辑器和桌面端 Bot Mode 例程对话框中也有同样的开关。

**适用场景：**

- 多阶段流水线（收集 → 过滤 → 格式化 → 投递）
- 步骤 N 依赖步骤 N−1 输出的依赖任务
- 一个任务聚合多个其他任务结果的扇出/扇入模式
- 需要针对自身上一次报告去重的周期性侦察/监控任务（`continuity=true`）

## Provider 恢复

Cron 任务继承你配置的回退 provider 和凭证池轮换。如果主 API key 被限速或 provider 返回错误，cron agent 可以：

- **回退到备用 provider**，前提是你在 `config.yaml` 中配置了 `fallback_providers`（或旧版 `fallback_model`）
- **轮换到下一个凭证**，即同一 provider 的[凭证池](/user-guide/configuration#credential-pool-strategies)中的下一个

这意味着高频运行或在高峰时段运行的 cron 任务更具弹性——单个被限速的 key 不会导致整次运行失败。

## 运行失败（`last_error`）

失败的 agent 运行会记录一条简洁的 `last_error`，可在任务列表和 `/cron list` 中看到，其中的凭证模式和 URL 凭证会被脱敏（包括之前已存储的错误）。它与 `last_fire_error`（调度器交接）和 `last_delivery_error`（投递）相互独立。当 agent 自身失败时，这两个字段为空是正确的。

对于连接失败，请在当前 Hermes home 的 `cron/output/<job_id>/` 下查看运行文档。其 `## Error` 部分包含链式回溯，凭证模式和 URL 凭证已被脱敏。该文件沿用现有的私有输出文件权限；回溯中的局部变量不会被捕获。投递通知和 `last_error` 保留的是简洁错误，而不是完整回溯。分享诊断信息前请先审阅：脱敏并不能保证任意应用数据都不敏感。

## 错过的计划触发（`last_fire_error`）

在托管（managed-cron）部署中，一次计划触发会从平台调度器经由仪表盘传到 gateway 的内部 API 服务器。如果最后这次交接失败——gateway 进程已停止，或其 API 服务器监听器从未启动——运行根本不会开始，因此没有执行记录，也没有可查看的 `last_status`。典型特征是：每次手动触发该任务都能正常工作，但它从不自动触发。

这些错过的触发会以 `last_fire_error`（时间戳 + 原因）的形式标记在任务记录上，并通过以下方式呈现：

- `cronjob` 工具 → `action: "list"`——`last_fire_error` 字段
- `hermes cron list`——任务下方一行红色的 `⚠ Missed scheduled fire:`
- 仪表盘的任务视图

该标记始终反映**当前**的自动触发健康状况：它会被更新的错过记录覆盖，并在下一次成功运行时自动清除。如果你看到它，说明任务及其调度都没问题——需要处理的是触发路径中 gateway 这一侧（最常见的做法是通过其监管程序重启 gateway，使其加载完整的 profile 环境：`hermes gateway restart`）。

### 错过触发的补跑

当外部调度提供程序处于活动状态时（托管部署上的 managed cron），gateway 还会运行一次补跑扫描：计划时间已过却没有触发送达、且宽限窗口已结束的任务，会被领取并在本地运行，因此触发交接中断只会损失几分钟，而不是一整天。该扫描通过与正常触发相同的存储领取机制，与调度器迟到的重试去重。

```yaml
cron:
  misfire_grace_minutes: 10   # 在本地补跑之前等待调度器自身重试的时长
                              # 0 表示禁用补跑
```

本地（内置 ticker）部署不需要这一机制——ticker 会在下一次 tick 时自动拾取已过期的任务。

## 调度格式

Agent 的最终响应会自动投递到任务的 `deliver:` 目标——agent 不再自行发送消息，因此面向用户的内容直接放在最终响应里即可。若要投递到**额外或不同的**目标，请在 cron 任务上列出多个 `deliver:` 目标（逗号分隔，例如 `deliver: "telegram,discord"`），而不是让 agent 去发送它们。

### 相对延迟（一次性）

```text
in 30m  → 30 分钟后运行一次
in 2h   → 2 小时后运行一次
in 1d   → 1 天后运行一次
```

### 间隔（周期性）

```text
30m          → 每 30 分钟（裸时长为周期性）
every 30m    → 每 30 分钟
every 2h     → 每 2 小时
every 1d     → 每天
every hour   → 每小时（裸单位 = 1）
```

### 自然语言的日期/时间调度（周期性）

```text
every monday 9am         → 每周一上午 9:00
every day at 9am         → 每天上午 9:00
weekdays at 9am          → 工作日上午 9:00
weekends at 10am         → 周六和周日上午 10:00
daily at 7am             → 每天上午 7:00
monday, wednesday at 9am → 每周一和周三上午 9:00
```

时间接受 `9am`、`9:30pm`、`14:00`、裸 24 小时制小时（`at 7`）、`noon` 和 `midnight`。这些形式在内部会被编译为 cron 表达式（需要 `croniter` 包，默认已安装）。

### Cron 表达式

```text
0 9 * * *       → 每天上午 9:00
0 9 * * 1-5     → 工作日上午 9:00
0 9 * * MON-FRI → 工作日上午 9:00（接受星期/月份名称）
0 */6 * * *     → 每 6 小时
30 8 1 * *      → 每月 1 日上午 8:30
0 0 * * 0       → 每周日午夜
```

### ISO 时间戳

```text
2026-03-15T09:00:00    → 2026 年 3 月 15 日上午 9:00 一次性运行
```

## 重复行为

| 调度类型 | 默认重复次数 | 行为 |
|--------------|----------------|----------|
| 一次性（`in 30m`、时间戳） | 1 | 运行一次 |
| 间隔（`every 2h`） | 永久 | 运行直到删除 |
| Cron 表达式 | 永久 | 运行直到删除 |

可以覆盖：

```python
cronjob(
    action="create",
    prompt="...",
    schedule="every 2h",
    repeat=5,
)
```

## 以编程方式管理任务

面向 agent 的 API 是单一工具：

```python
cronjob(action="create", ...)
cronjob(action="list")
cronjob(action="update", job_id="...")
cronjob(action="pause", job_id="...")
cronjob(action="resume", job_id="...")
cronjob(action="run", job_id="...")
cronjob(action="remove", job_id="...")
```

对于 `update`，传入 `skills=[]` 可删除所有已附加的 skill。

### 手动运行是异步的

`cronjob(action="run")` 会**在后台**立即触发任务（类似 `delegate_task`）：工具调用会立刻返回一个句柄，而任务的结果——成功/失败、投递目标、下次计划运行时间以及一段输出摘录——会在运行结束时作为一条新消息重新进入对话。在此期间 agent（以及你）可以继续工作；已经在运行中的任务会被以 "already running" 拒绝，而不会重复触发。

你也可以在 `action="run"` 时传入 `prompt`，注入仅针对本次运行的临时上下文：

```python
cronjob(action="run", job_id="...", prompt="CONTEXT: focus on the EU region today")
```

该上下文仅在这一次触发中追加到任务已存储的 prompt 的 `## Run Context` 标题下——它永远不会持久化到任务定义中，并且会经过与已存储 prompt 相同的 prompt 注入扫描。

无法接收分离结果的运行时（一次性的 `hermes -z`、CLI 中的 `hermes
cron run`、cron 子会话、Kanban worker）会自动回退为同步执行。

## Cron 任务可用的工具集

Cron 在全新的 agent 会话中运行每个任务，不附加任何聊天平台。默认情况下，cron agent 获得**你在 `hermes tools` 中为 `cron` 平台配置的工具集**——不是 CLI 默认值，也不是所有工具。

```bash
hermes tools
# → 在 curses UI 中选择 "cron" 平台
# → 像 Telegram/Discord 等平台一样切换工具集开关
```

通过 `cronjob.create`（或通过 `cronjob.update` 对现有任务）上的 `enabled_toolsets` 字段可进行更精细的单任务控制：

```text
cronjob(action="create", name="weekly-news-summary",
        schedule="every sunday 9am",
        enabled_toolsets=["web", "file"],      # 仅 web + file，无 terminal/browser 等
        prompt="Summarize this week's AI news: ...")
```

当任务上设置了 `enabled_toolsets` 时，它优先生效；否则 `hermes tools` 的 cron 平台配置生效；否则 Hermes 回退到内置默认值。这对成本控制很重要：在每个小型"获取新闻"任务中携带 `browser`、`delegation` 会在每次 LLM 调用时膨胀工具 schema prompt。

### 完全跳过 agent：`wakeAgent`

如果你的 cron 任务附加了预检脚本（通过 `script=`），脚本可以在运行时决定 Hermes 是否应该调用 agent。在 stdout 最后一行输出如下格式：

```text
{"wakeAgent": false}
```

……cron 将完全跳过本次 tick 的 agent 运行。适用于高频轮询（每 1–5 分钟），只在状态实际发生变化时才需要唤醒 LLM——否则你会为一遍遍的零内容 agent 轮次付费。

```python
# 预检脚本
import json, sys
latest = fetch_latest_issue_count()
prev = read_state("issue_count")
if latest == prev:
    print(json.dumps({"wakeAgent": False}))   # 跳过本次 tick
    sys.exit(0)
write_state("issue_count", latest)
print(json.dumps({"wakeAgent": True, "context": {"new_issues": latest - prev}}))
```

省略 `wakeAgent` 时，默认为 `true`（照常唤醒 agent）。

#### 实用方案：低成本预运行门控

`wakeAgent` 门控提供了一种零成本的方式，用于决定定时任务是否应该消耗任何 LLM token。三种模式覆盖了大多数使用场景。

**文件变更门控**——仅在被监视文件自上次成功 tick 以来有新内容时运行。调度器记录每个任务的 `last_run_at`；将其与文件的 mtime 比较。

```bash
#!/bin/bash
# ~/.hermes/scripts/feed-changed.sh
FEED="$HOME/data/feed.json"
STATE="$HOME/.hermes/scripts/.feed-changed.last"
test -f "$FEED" || { echo '{"wakeAgent": false}'; exit 0; }
mtime=$(stat -c %Y "$FEED")
last=$(cat "$STATE" 2>/dev/null || echo 0)
if [ "$mtime" -le "$last" ]; then
  echo '{"wakeAgent": false}'
else
  echo "$mtime" > "$STATE"
  echo '{"wakeAgent": true}'
fi
```

```text
cronjob(action="create", name="process-feed",
        schedule="every 30m",
        script="feed-changed.sh",
        prompt="A new ~/data/feed.json has landed. Summarize what changed.")
```

**外部标志门控**——仅在其他进程发出就绪信号时运行（例如，部署 hook 落下一个文件，CI 任务在状态存储中设置一个值）。

```bash
#!/bin/bash
# ~/.hermes/scripts/flag-ready.sh
if test -f /tmp/new-data-ready; then
  rm -f /tmp/new-data-ready
  echo '{"wakeAgent": true}'
else
  echo '{"wakeAgent": false}'
fi
```

```text
cronjob(action="create", name="nightly-analysis",
        schedule="0 9 * * *",
        script="flag-ready.sh",
        prompt="Run the nightly analysis over today's batch.")
```

**SQL 计数门控**——仅在你自己的数据库中有新行需要处理时运行。脚本还可以通过 `context` 将计数传递给 agent，让 agent 无需重新查询就知道数据量。

```python
#!/usr/bin/env python
# ~/.hermes/scripts/new-rows.py
import json, sqlite3
conn = sqlite3.connect("/home/me/data/app.db")
n = conn.execute(
    "SELECT COUNT(*) FROM messages WHERE ts > strftime('%s','now','-2 hours')"
).fetchone()[0]
if n < 1:
    print(json.dumps({"wakeAgent": False}))
else:
    print(json.dumps({"wakeAgent": True, "context": {"new_rows": n}}))
```

```text
cronjob(action="create", name="summarize-new-msgs",
        schedule="every 2h",
        script="new-rows.py",
        prompt="Summarize the new messages from the last 2 hours.")
```

同样的模式适用于任何可以从脚本查询的数据源——Postgres、HTTP API、你自己的状态存储——无需将 SQL 求值器内置到 cron 子系统中。

:::tip
Hermes 自身的 `~/.hermes/state.db` 是内部 schema，会在版本间变更。不要从预运行门控中查询它——指向你自己的数据库或 feed。
:::

致谢：此方案集由 @iankar8 在 [#2654](https://github.com/NousResearch/hermes-agent/pull/2654) 中的探索所启发，该 PR 提议将 sql/file/command 触发器作为并行机制添加。`script` + `wakeAgent` 门控已以零成本覆盖了所有三种情况，因此该工作以文档形式落地。

### 串联任务：`context_from`

Cron 任务可以通过在 `context_from` 中列出其他任务的名称（或 ID）来消费这些任务最近一次成功运行的输出：

```text
cronjob(action="create", name="daily-digest",
        schedule="every day 7am",
        context_from=["ai-news-fetch", "github-prs-fetch"],
        prompt="Write the daily digest using the outputs above.")
```

被引用任务最近一次完成的输出会作为上下文注入到本次运行的 prompt 之上。每个上游条目必须是有效的任务 ID 或名称（参见 `cronjob action="list"`）。注意：串联读取的是*最近一次完成*的输出——它不会等待同一 tick 中正在运行的上游任务。

## 任务存储

任务存储在 `~/.hermes/cron/jobs.json`。任务运行的输出保存到 `~/.hermes/cron/output/{job_id}/{timestamp}.md`。

任务定义是磁盘上的纯 JSON：它们在 `hermes update`、gateway 重启和机器重启后都会保留。重启时正在运行中的任务会在执行账本中被标记为 `unknown`——它不会被自动重试，但该任务的下一次计划 tick 会正常触发。详见[执行历史](#execution-history)。

:::tip
请让 agent 通过 `cronjob` 工具、`hermes cron edit` 或 `/cron` 来管理任务，而不要直接修补 `jobs.json`。当[文件写入安全](../security.md#file-write-safety)机制阻止该路径时（例如设置了 `HERMES_WRITE_SAFE_ROOT`），直接编辑可能会静默失败，而[文件变更校验器](../configuration.md#file-mutation-verifier)页脚才是"什么都没保存"的权威信号。
:::

任务可能将 `model` 和 `provider` 存储为 `null`。省略这些字段时，Hermes 在执行时从全局配置中解析它们。只有设置了单任务覆盖时，这些字段才会出现在任务记录中。

存储使用原子文件写入，因此中断的写入不会留下部分写入的任务文件。

## 自包含的 prompt 仍然重要

:::warning 重要
Cron 任务在完全全新的 agent 会话中运行。Prompt 必须包含 agent 所需的一切，除非已由附加的 skill 提供。
:::

**错误：** `"Check on that server issue"`

**正确：** `"SSH into server 192.168.1.100 as user 'deploy', check if nginx is running with 'systemctl status nginx', and verify https://example.com returns HTTP 200."`

## 安全性

定时任务的 prompt 在创建和更新时会扫描 prompt 注入和凭证外泄模式。包含不可见 Unicode 技巧、SSH 后门尝试或明显的密钥外泄载荷的 prompt 会被拦截。
