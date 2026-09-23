---
sidebar_position: 9
title: "从其他 Agent 导入"
description: "一条命令将 Claude Code（~/.claude）或 OpenAI Codex CLI（~/.codex）的配置导入 Hermes——指令、白名单、MCP 服务器、技能和记忆。"
---

# 从其他 Agent 导入 {#import-from-other-agents}

`hermes import-agent` 用一条命令将你现有的 **Claude Code** 或 **OpenAI Codex CLI** 配置导入 Hermes。它沿用与 [`hermes claw migrate`](../guides/migrate-from-openclaw.md) 相同的“先预览”模式：在写入任何内容之前，你总能看到逐项计划，而 `--dry-run` 永远不会触碰磁盘。

```bash
hermes import-agent                    # 自动检测 ~/.claude 或 ~/.codex
hermes import-agent claude-code        # 从 ~/.claude 导入
hermes import-agent codex              # 从 ~/.codex 导入
hermes import-agent claude-code --dry-run          # 仅预览
hermes import-agent codex --source /path/to/.codex # 自定义位置
hermes import-agent claude-code --overwrite --yes  # 替换冲突项，跳过提示
```

## 导入哪些内容 {#what-gets-imported}

### Claude Code（`~/.claude`） {#claude-code-claude}

| Claude Code | Hermes |
|---|---|
| `CLAUDE.md`（全局指令） | `~/.hermes/memories/MEMORY.md` 中的记忆条目 |
| `settings.json` → `permissions.allow`（`Bash(...)` 规则） | `config.yaml` 中的 `command_allowlist` |
| `settings.json` → `permissions.deny`（`Bash(...)` 规则） | `config.yaml` 中的 `approvals.deny` |
| `mcpServers`（来自 `~/.claude.json` 和 `settings.json`） | `config.yaml` 中的 `mcp_servers` |
| `skills/<name>/`（包含 `SKILL.md` 的目录） | `~/.hermes/skills/claude-code-imports/<name>/` |
| `commands/*.md`（斜杠命令） | 跳过并附注说明——请将它们转换为技能 |

Claude 的 `Bash(npm run test:*)` 前缀规则会变成 `npm run test*` glob。非 `Bash` 的权限规则（`Read(...)`、`WebFetch` 等）用于管控 Claude 特有的工具，会被报告为未映射，而不会被导入。

### Codex CLI（`~/.codex`） {#codex-cli-codex}

| Codex CLI | Hermes |
|---|---|
| `AGENTS.md`（全局指令） | `~/.hermes/memories/MEMORY.md` 中的记忆条目 |
| `config.toml` → `[mcp_servers.*]` | `config.yaml` 中的 `mcp_servers` |
| `memories/*.md` | `~/.hermes/memories/MEMORY.md` 中的记忆条目 |
| `skills/<name>/`（包含 `SKILL.md` 的目录） | `~/.hermes/skills/codex-imports/<name>/` |

## 永远不会导入的内容 {#what-is-never-imported}

**API 密钥和凭据。** 凭据文件（`~/.claude/.credentials.json`、`~/.codex/auth.json`）永远不会被读取；名称看起来像密钥的 MCP 服务器环境变量或请求头（`*_TOKEN`、`*_API_KEY`、`Authorization` 等）会被剥离并列在报告中，以便你有意识地重新添加。运行 `hermes setup` 配置提供商，或将密钥添加到 `~/.hermes/.env`。

## 行为说明 {#behavior-notes}

- **始终先预览。** 命令会在应用之前打印完整计划；在非交互式会话中，除非你传入 `--yes`，否则它会停在预览阶段。
- **合并，而非替换。** 记忆条目会与你现有的 `MEMORY.md` 去重；白名单/拒绝列表模式会与 `config.yaml` 中已有的内容合并。
- **冲突默认跳过。** Hermes 中已存在的 MCP 服务器或技能会被报告为冲突；传入 `--overwrite` 可替换它。
- **格式错误的文件不会中止运行。** 损坏的 `settings.json` 或 `config.toml` 会成为报告中的单项错误，其余内容仍会照常导入。
- 如果你是从 OpenClaw 迁移过来？请使用 [`hermes claw migrate`](../guides/migrate-from-openclaw.md)。
