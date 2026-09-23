---
sidebar_position: 15
title: "CLI 内部机制"
description: "hermes_cli 的整体结构：斜杠命令分发、配置加载器、皮肤引擎、事务化更新流水线，以及进程身份识别规则"
---

# CLI 内部机制

本页是 `hermes_cli/AGENTS.md`（规则本身）的配套文档——这里存放较长的说明。

## 更新流水线 {#update-pipeline}

逐阶段的契约（`plan → snapshot → apply → restart-per-kind → verify → report`）以及每个阶段所防范的实际故障，均记录在 `hermes_cli/AGENTS.md` 中；面向用户的行为（回执、`--plan`、快照模式）见 [更新](../getting-started/updating.md)。

systemd 粗暴重启回退路径会等待该 unit 的 `TimeoutStopUSec` 加上
`TimeoutStartUSec`，外加 15 秒的客户端余量。它在与重启相同的管理器作用域中读取目标 unit；
首次尝试和重试都使用这一时间预算，包括更新中断后的补偿重启。
优雅排空之后的启动只使用启动预算加余量。
缺失、无法解析或为无限的阶段时限，对该阶段回退为 90 秒，
从而让无人值守的更新保持有界。`systemctl` 客户端超时**并不会**取消管理器的事务。
自定义的多命令停止链或 `EXTEND_TIMEOUT_USEC` 仍可能超出这一估算；真正的超时
仍视为未完成的重启，而成功的命令仍需通过现有的服务健康检查和整个实例群的版本校验。
原始数值形式的 `*USec` 值单位为微秒，而格式化后的值使用 systemd 的固定单位，包括天、
周、月和年。合并后的超时上限被限制在原生有符号 32 位毫秒轮询上限之下（并留有舍入余量），
因此超长的 unit 时限不会导致子进程轮询溢出。为零/未知/无限的阶段时限
使用有界回退值。这不会改变活动轮次的排空设置。

## 进程身份：绝不从 argv 子串推断 {#process-identity-never-infer-it-from-argv-substrings}

约 10 个实例群更新问题（#90778、#87594、#78089、#76129、#91964……）背后的 bug 类别：
通过 `"serve" in cmdline` 或类似方式对进程分类。`kanban --preserve-cache` 包含
"serve"；某个 flag 的值可能等于一个子命令（`-m dashboard serve`）；被截断的 cmdline 会隐藏真正的
子命令。规则如下：

- 使用规范的匹配器：`gateway.status.looks_like_gateway_command_line`（gateway run）、
  `hermes_cli.update_cmd._hermes_holder_subcommand`（任意 Hermes argv 的顶层子命令）。绝不
  手写 token 扫描。
- flag 集合必须从解析器**派生**（`_holder_value_flags()` 会内省
  `build_top_level_parser()`），绝不使用手写列表——它们会漂移。
- 绝不在进程扫描中一刀切地排除祖先进程：当 `/update` 作为 gateway 的子进程运行时，
  gateway 祖先必须对暂停机制保持可见（#87594）。应排除交互式祖先链，
  并为 gateway 形态的祖先开辟例外。
- 基于**完整** cmdline 匹配；仅在显示时截断（#78089）。
- 在添加任何新的扫描启发式之前，先阅读 #92091——gateway 控制套接字取代扫描成为
  主要的协调机制；扫描只是面向旧进程/崩溃进程的回退层。

## 皮肤引擎——皮肤可以自定义什么 {#skin-engine--what-skins-customize}

| 元素 | 皮肤键 | 使用方 |
|---|---|---|
| 横幅面板边框 / 标题 / 分区标题 / 暗色 / 正文 | `colors.banner_border`, `banner_title`, `banner_accent`, `banner_dim`, `banner_text` | `banner.py` |
| 响应框边框 | `colors.response_border` | `cli.py` |
| 加载动画表情（等待 / 思考） | `spinner.waiting_faces`, `spinner.thinking_faces` | `display.py` |
| 加载动画动词 / 翅膀（可选） | `spinner.thinking_verbs`, `spinner.wings` | `display.py` |
| 工具输出前缀 / 各工具 emoji | `tool_prefix`, `tool_emojis` | `display.py` → `get_tool_emoji()` |
| Agent 名称 / 欢迎语 / 响应标签 / 提示符 | `branding.agent_name`, `welcome`, `response_label`, `prompt_symbol` | `banner.py`, `cli.py` |

内置皮肤（`hermes_cli/skin_engine.py` 中的 `_BUILTIN_SKINS`）：`default`（经典金色/kawaii）、
`ares`（深红/青铜，带自定义加载动画翅膀）、`mono`（灰度）、`slate`（冷蓝）。新增内置皮肤只需添加一个
字典条目 `{"name", "description", "colors", "spinner", "branding", "tool_prefix"}`。
用户皮肤为 `~/.hermes/skins/<name>.yaml`，使用相同的键，通过 `/skin <name>` 或
`display.skin: <name>` 激活；完整的 YAML 模板见
[皮肤与主题](../user-guide/features/skins.md) 用户指南。

## Profile：多实例支持 {#profiles-multi-instance-support}

Hermes 支持 profile——完全隔离的实例，每个实例都有自己的 `HERMES_HOME`（配置、API
密钥、记忆、会话、skill、gateway）。`hermes_cli/main.py` 中的 `_apply_profile_override()` 会在
任何模块导入之前设置 `HERMES_HOME`，因此每一处 `get_hermes_home()` 引用都作用于当前激活的
profile。Profile 操作以 HOME 为锚点（`_get_profiles_root()` 返回
`Path.home() / ".hermes" / "profiles"`，而不是 `get_hermes_home() / "profiles"`），因此
`hermes -p coder profile list` 无论当前激活的是哪个 profile 都能看到所有 profile——这是有意为之。
Profile 安全的编码规则见根目录的 `AGENTS.md`；多路复用的密钥作用域规则见
`gateway/AGENTS.md`。
