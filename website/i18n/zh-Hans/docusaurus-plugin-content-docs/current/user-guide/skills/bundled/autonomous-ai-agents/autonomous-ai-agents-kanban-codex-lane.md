---
title: "Kanban Codex Lane"
sidebar_label: "Kanban Codex Lane"
description: "当 Hermes Kanban worker 想把 Codex CLI 作为一条隔离的实现通道来运行，而由 Hermes 保留对任务生命周期、对账、测..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Kanban Codex Lane

当 Hermes Kanban worker 想把 Codex CLI 作为一条隔离的实现通道来运行，而由 Hermes 保留对任务生命周期、对账、测试和交接的所有权时使用。

## Skill 元数据

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/autonomous-ai-agents/kanban-codex-lane` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 标签 | `kanban`, `codex`, `worktrees`, `autonomous-agents`, `prediction-market-bot` |
| 相关 skills | [`codex`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex), [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Kanban Codex Lane

## 概览

此 skill 为 Kanban worker 定义了轻量的 Hermes+Codex 双通道约定。Hermes 始终是任务所有者：它调用 `kanban_show`，判断是否适合使用 Codex，创建或选择一个隔离的工作区，启动并监控 Codex，对差异进行对账，运行验证，并写入最终的 `kanban_complete` 或 `kanban_block` 交接。Codex 只是一条输入通道。Codex 的输出不是任务完成信号，不是可信的评审者，也不允许直接写入持久化的 Kanban 状态。

这套约定的存在，是为了让 Hermes worker 能在不改动调度器的前提下，借助 Codex 获得有边界的实现帮助。调度器仍然必须派生 Hermes worker。worker 可以选择在自己的运行过程中派生 Codex，然后在独立评审和测试之后，决定接受、部分接受或拒绝该通道的产出。

## 使用场景

当以下条件全部成立时，使用 Codex 通道：

- 该 Kanban 任务是编码、重构、文档、测试或机械式迁移类任务，且有明确的验收标准。
- 一份有边界的 diff 可以由 Hermes 在一次运行中完成评估。
- 仓库可以被复制，或在隔离的 git worktree/分支中检出。
- Codex 退出后，Hermes 能自行运行相关测试。
- 提示词能够写清所有安全约束以及不得改动的文件。

当以下任一条件成立时，不要使用 Codex 通道：

- 任务需要 Kanban 正文中尚未记录的人类判断。
- worker 没有仓库访问权限、Codex 认证，或没有时间对结果做对账。
- 变更涉及密钥、凭证存储、用户隐私数据或生产下单系统。
- 一次小的直接编辑比再派生一个 agent 更快也更安全。
- 任务只是研究性质，应产出书面交接而非 diff。
- worker 会被诱导仅凭 Codex 的自我汇报就把任务标记为 Done。

## 所有权规则

1. Hermes 拥有 Kanban 生命周期。Codex 绝不能调用 `kanban_complete`、`kanban_block`、`kanban_create`、网关消息发送或任何 Hermes 看板 CLI 来替代 worker。
2. Hermes 拥有最终验收权。在评审和验证之前，把 Codex 的提交/diff 当作不可信补丁对待。
3. Hermes 拥有测试执行权。Codex 可以运行测试，但那些运行只是参考性的；必要的验证要由 Hermes 使用仓库的规范包装脚本重新执行一遍。
4. Hermes 拥有安全责任。如果 Codex 改动了安全边界、风险闸门、实盘交易行为或密钥处理方式，即使测试通过也要拒绝该通道。
5. Hermes 拥有清理责任。终止卡死的 Codex 进程，并在临时 worktree 不再需要时将其移除。

## 必需的 worktree 与分支模式

绝不要直接在共享的脏检出目录中运行 Codex。使用能把该通道与 Kanban 任务关联起来的分支/worktree 名称，并把不可信的编辑隔离开。

推荐的变量：

```bash
TASK_ID="${HERMES_KANBAN_TASK:-t_manual}"
REPO="/path/to/repo"
BASE="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
SAFE_TASK="$(printf '%s' "$TASK_ID" | tr -cd '[:alnum:]_-')"
BRANCH="codex/${SAFE_TASK}/$(date -u +%Y%m%d%H%M%S)"
WORKTREE="/tmp/${SAFE_TASK}-codex-lane"
```

创建隔离通道：

```bash
git -C "$REPO" fetch --all --prune
git -C "$REPO" worktree add -b "$BRANCH" "$WORKTREE" "$BASE"
git -C "$WORKTREE" status --short --branch
```

如果当前的 Kanban 工作区本身就是为该任务创建的隔离 git worktree，那么只有当 `git status --short` 除了有意为之的 Hermes 编辑之外是干净的，你才可以在其中创建一个同级的 Codex 分支。否则，创建一个独立的临时 worktree，并在对账之后把被接受的提交 cherry-pick 或复制回来。

对账之后的清理：

```bash
git -C "$REPO" worktree remove "$WORKTREE"
git -C "$REPO" branch -D "$BRANCH"  # 仅在被接受的提交已复制/cherry-pick，或已被有意拒绝之后执行
```

如果 worktree 需要作为评审用的产物保留，就保留它；把它记录在 `codex_lane.artifacts` 中，并在交接里提到它。

## Codex 能力检查

在派生 Codex 之前运行这些检查。缺少 Codex 是跳过该通道的正常理由；只要 Hermes 能直接完成任务，它就不构成任务阻塞。

```bash
command -v codex
codex --version
codex features list | grep -i goals || true
```

如果确实需要 `/goal` 支持，请先检查可用性，再启用或带着该特性开关启动：

```bash
codex features enable goals || true
codex --enable goals --version
```

认证可以通过 `OPENAI_API_KEY` 或 Codex CLI 的 OAuth 状态（通常在 `~/.codex/auth.json`）完成。不要打印令牌文件。缺少 `OPENAI_API_KEY` 并不能证明认证不可用。

## 模式选择

对于有边界、且希望 Codex 自行退出的一次性编辑，使用 `codex exec`：

```python
terminal(
    command="codex exec --full-auto '$(cat /tmp/codex_prompt.md)'",
    workdir=WORKTREE,
    background=True,
    pty=True,
    notify_on_complete=True,
)
```

只有在更宽泛、需要持久目标跟踪的多步工作中才使用 Codex 的 `/goal`。在 PTY/tmux 会话中交互式启动；如果该特性默认关闭，则使用 `codex --enable goals`。让目标描述自包含：仓库路径、任务 id、安全约束、允许的范围、验收标准、测试以及提交要求。

粘贴到 Codex 中的 `/goal` 目标文本示例：

```text
/goal Work in this repository only: <WORKTREE>. Task: <TASK_ID> <TITLE>.
Hermes owns the Kanban lifecycle; do not call Hermes kanban tools or messaging.
Create small commits on branch <BRANCH>. Follow the PMB safety constraints in the prompt.
Run the requested verification commands and report exact outputs. Stop after producing a diff and summary.
```

不要对 prediction-market-bot 或安全敏感的仓库使用 `--yolo`。优先在隔离的 worktree 中使用 `--full-auto`，然后依靠 Hermes 的对账。

## 提示词构建

对于 prediction-market-bot 的工作，使用 `templates/pmb-codex-lane-prompt.md` 中链接的模板。对于其他仓库，保持相同结构，并把 PMB 专属的安全段落替换为该仓库自己的不变量。

每一份 Codex 提示词都必须包含：

- `task_id`、标题，以及完整的 Kanban 验收标准。
- 仓库路径、worktree 路径、分支名，以及允许改动的文件范围。
- 明确声明：Hermes 拥有 Kanban 生命周期；Codex 只是一条输入通道。
- 要求的输出：简明摘要、改动的文件、提交、运行过的测试，以及已知风险。
- 禁止的行为：访问密钥、对外发送消息、改动看板、无关重构、非必要的依赖升级。
- Codex 可以运行的验证命令，以及 Hermes 事后将运行的命令。

对于 PMB，必须原样包含以下强制安全约束：

```text
PMB safety constraints:
- live-SIM is paper-only; do not add or enable live REST order entry.
- Never use market orders.
- Do not add execution crossing or bypass price/risk checks.
- Do not fake passive fills, fills, PnL, order states, or reconciliation evidence.
- Do not weaken risk gates, limits, kill switches, or fail-closed behavior.
- Keep research/selection outside the C++ hot path unless explicitly requested.
- Do not read, print, write, or require secrets/tokens/credentials.
```

## 监控、超时与终止行为

耗时较长的 Codex 通道应在后台启动，并开启 PTY 与完成通知：

```python
result = terminal(
    command="codex exec --full-auto '$(cat /tmp/codex_prompt.md)'",
    workdir=WORKTREE,
    background=True,
    pty=True,
    notify_on_complete=True,
)
session_id = result["session_id"]
```

在不干扰的前提下监控：

```python
process(action="poll", session_id=session_id)
process(action="log", session_id=session_id, limit=200)
process(action="wait", session_id=session_id, timeout=300)
```

对于超过两分钟的通道，每隔几分钟发送一次 Kanban 心跳，例如 `kanban_heartbeat(note="Codex lane running in <WORKTREE>; waiting for tests/diff")`。

终止条件：

- 在任务剩余的运行时预算内没有产出有用输出。
- Codex 请求密钥、生产凭证或外部权限。
- Codex 试图修改 worktree 之外的文件。
- Codex 开始进行无关的重写或依赖变动。
- 已接近 worker 超时时间 Codex 仍在运行，且不存在安全可用的部分产物。

终止命令：

```python
process(action="kill", session_id=session_id)
```

终止之后，检查 `git status --short`，仅在安全的前提下保留有用的补丁，并记录 `codex_lane.result: timed_out` 或 `rejected`，同时给出具体的 `rejected_reason`。

## 对账检查清单

在接受任何 Codex 通道结果之前，Hermes 必须完成这份清单：

- [ ] `git -C <WORKTREE> status --short --branch` 只显示预期内的文件。
- [ ] Hermes 已评审 `git -C <WORKTREE> diff --stat` 和 `git diff`。
- [ ] 其中不包含密钥、凭证、生成的缓存、无关数据或本地产物。
- [ ] PMB 安全约束得到保留：没有实盘 REST 下单、没有市价单、没有撮合穿越、没有伪造的被动成交/PnL、没有削弱风险闸门、没有涉及密钥。
- [ ] Codex 的提交足够小，可以干净地 cherry-pick 或压缩。
- [ ] Hermes 自行运行了规范测试：Hermes Agent 使用 `scripts/run_tests.sh`，其他仓库使用其文档中的包装脚本。
- [ ] 由 Codex 运行的测试与由 Hermes 运行的测试分别列出。
- [ ] 被接受的提交/diff 已应用到 Hermes 拥有的工作区/分支。
- [ ] 被拒绝或部分接受的工作有具体理由，必要时附上产物路径。

验收结果：

- `accepted`：Codex 的 diff/提交已评审、已应用并已验证。
- `partial`：部分 Codex 工作在编辑或 cherry-pick 之后被接受；被拒绝的部分已记录在案。
- `rejected`：没有接受任何 Codex 改动；理由已记录在案。
- `timed_out`：Codex 超出了该通道的预算；可能存在也可能不存在有用产物。

## kanban_complete 元数据 schema

对于每一个考虑过使用该通道的任务，都在 `metadata.codex_lane` 下包含这个对象。如果没有使用 Codex，则设置 `used: false`，并在 `rejected_reason` 或同级的 `notes` 字段中说明原因。

```json
{
  "codex_lane": {
    "used": true,
    "mode": "exec | goal | skipped",
    "worktree": "/absolute/path/to/codex/worktree",
    "branch": "codex/t_caa69668/20260508100000",
    "command": "codex exec --full-auto ...",
    "result": "accepted | rejected | partial | timed_out",
    "accepted_commits": ["<sha1>", "<sha2>"],
    "rejected_reason": "empty when fully accepted; otherwise concrete reason",
    "tests_run": [
      {"command": "scripts/run_tests.sh tests/tools/test_x.py", "exit_code": 0, "owner": "hermes"},
      {"command": "codex-reported: npm test", "exit_code": 0, "owner": "codex"}
    ],
    "artifacts": ["/absolute/path/to/log-or-patch"]
  }
}
```

对于有意跳过 Codex 的任务：

```json
{
  "codex_lane": {
    "used": false,
    "mode": "skipped",
    "worktree": null,
    "branch": null,
    "command": null,
    "result": "rejected",
    "accepted_commits": [],
    "rejected_reason": "Direct Hermes edit was smaller and safer than spawning Codex.",
    "tests_run": [],
    "artifacts": []
  }
}
```

## 常见陷阱

1. 把 Codex 的自我汇报当作验证。始终要检查 diff，并从 Hermes 重新运行测试。
2. 在用户的脏 main 检出目录中运行 Codex。始终在 worktree/分支中隔离。
3. 让 Codex 拥有 Kanban。Codex 可以总结进展，但看板状态由 Hermes 写入。
4. 在提示词中遗漏 PMB 安全不变量。缺少安全文本属于通道设置失败。
5. 用 `/goal` 做快速编辑。除非需要持久的多步续跑，否则优先使用 `codex exec`。
6. 终止卡死的通道却不记录原因。`rejected_reason` 必须解释该决定。
7. 因为测试通过就接受大范围的无关清理。要拒绝，或只 cherry-pick 范围内的改动。

## 验证检查清单

- [ ] Codex 要么被跳过，要么只在 `command -v codex`、`codex --version` 以及可选的 goals 特性检查之后才启动。
- [ ] Codex 只在隔离的 worktree/分支中运行。
- [ ] 提示词包含任务范围、所有权规则、适用时的 PMB 安全约束，以及验证命令。
- [ ] Hermes 评审了 `git diff` 与安全敏感文件。
- [ ] Hermes 独立运行了规范测试。
- [ ] `kanban_complete.metadata.codex_lane` 遵循上面的 schema。
- [ ] 临时进程与不再需要的 worktree 已被清理。
