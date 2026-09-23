---
title: "Actual Setup — 在 Hermes 中配置 Actual Computer（actual.inc）推理"
sidebar_label: "Actual Setup"
description: "在 Hermes 中配置 Actual Computer（actual.inc）推理"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Actual Setup

在 Hermes 中配置 Actual Computer（actual.inc）推理。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/devops/actual-setup` 安装 |
| 路径 | `optional-skills/devops/actual-setup` |
| 版本 | `2.0.0` |
| 作者 | shl0ms + Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `actual`, `actual-inc`, `provider`, `local-inference`, `relay`, `gguf`, `setup` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Actual Computer 配置 Skill {#actual-computer-setup-skill}

将 [actual.inc](https://actual.inc)（Actual Computer）配置为 Hermes 的推理
提供方。Actual 把用户自己的硬件变成一个私有推理集群，并通过两种方式提供
兼容 OpenAI 的 API：一种是位于 `https://api.actual.inc` 的托管端到端加密
中继（使用 `ac_` 密钥认证），另一种是位于 `http://127.0.0.1:8080` 的本地
设备端守护进程（回环地址上无需认证）。本 skill 不会替用户安装 Actual
守护进程 —— 设备授权需要真人在浏览器中完成。

## 使用时机 {#when-to-use}

- 用户想把 actual.inc 添加为推理提供方（云端中继或本地）。
- 用户有一个 `ac_` 密钥，想让 Hermes 经由其 Actual 集群路由。
- 用户想通过 Actual 守护进程实现完全本地的设备端推理。
- 故障排查：Actual 请求因含义不明的 400 或空流而失败。

## 前置条件 {#prerequisites}

- Hermes 提供**一等公民级的 `actual` provider 支持**（provider id 为 `actual`，
  别名 `actual-computer`、`actualcomputer`、`aci`）。在当前版本的 Hermes 上，
  不要把 Actual 配置为 `custom_providers` / `providers.actual.*` 条目 —— 内置
  provider 占用了这个名称，并自动处理 base-url 规范化、Responses 传输以及
  本地免认证。
- 中继模式：一个 Actual 账号，以及从
  https://actual.inc/user/keys 获取的 `ac_` 推理密钥。
- 本地模式：用户已安装守护进程
  （`curl -fsSL "https://actual.inc/install" | bash`），并已完成设备授权——
  即运行一次 `actual`，然后在浏览器中打开其打印出的
  `https://actual.inc/device?code=...` URL。把该 URL 转告用户并等待 ——
  绝不要编造邮箱或代替用户授权。授权码 5 分钟后过期；重新运行 `actual`
  即可获得新的授权码。

## 运行方式 {#how-to-run}

### 中继 / API 模式 {#relay--api-mode}

1. 把密钥放进 `.env`（只放密钥 —— 绝不放进 config.yaml）：
   在 `~/.hermes/.env` 末尾追加 `ACTUAL_API_KEY=ac_...`。
2. 用 `terminal` 验证密钥并发现可用模型：
   ```bash
   curl -s https://api.actual.inc/v1/models -H "Authorization: Bearer $ACTUAL_API_KEY"
   ```
3. 选择 provider 和模型：
   ```bash
   hermes config set model.provider actual
   hermes config set model.default "MODEL_ID_FROM_DISCOVERY"
   ```
4. 端到端验证：
   ```bash
   hermes chat -Q -q "Reply with exactly: ACTUAL_OK" --provider actual -m MODEL_ID
   ```

### 本地模式 {#local-mode}

1. 真人已安装并授权守护进程（见前置条件）。
2. 下载并加载一个模型（授权完成后即可脚本化）：
   ```bash
   actual models search "qwen2.5 0.5b instruct gguf" --limit 8 --no-prompt
   # Downloads REQUIRE an explicit quantization (409 ambiguous_model_download otherwise):
   actual models download "Qwen/Qwen2.5-0.5B-Instruct-GGUF/Q4_K_M"
   actual models list        # note the INSTALLED name (differs from download id)
   actual models load "qwen2.5-0.5b-instruct-q4_k_m"   # load by installed name
   ```
3. 让 Hermes 指向守护进程。当 `ACTUAL_BASE_URL` 使用回环主机时，内置 provider
   会自动切换到本地免认证模式 —— 无需密钥：
   在 `~/.hermes/.env` 末尾追加 `ACTUAL_BASE_URL=http://127.0.0.1:8080`，然后：
   ```bash
   hermes config set model.provider actual
   hermes config set model.default "INSTALLED_MODEL_NAME"
   ```
4. 验证（精简工具集 —— 见下文关于上下文窗口的陷阱）：
   ```bash
   hermes chat -Q -q "Reply with exactly: LOCAL_OK" --provider actual -m INSTALLED_NAME -t file,web
   ```

## 快速参考 {#quick-reference}

| 项目 | 值 |
|---|---|
| 托管中继 | `https://api.actual.inc/v1`（裸主机名会被自动规范化为此地址） |
| 本地守护进程 | `http://127.0.0.1:8080/v1`（回环地址上无需认证） |
| 密钥环境变量 | `ACTUAL_API_KEY`（`ac_...`） |
| Base URL 环境变量 | `ACTUAL_BASE_URL`（回环主机 ⇒ 本地免认证模式） |
| Provider id / 别名 | `actual` / `actual-computer`、`actualcomputer`、`aci` |
| 传输方式 | Responses API（`codex_responses`）—— 内置，不要覆盖 |
| 集群固定 | 通过 config.yaml 中的 `providers.actual.extra_headers` 设置 `X-Cluster-ID` 请求头 |
| 模型大小参考 | 0.5B Q4_K_M 约 470MB（玩具级），7-8B Q4_K_M 约 4.5GB（日常主力），32B 约 20GB |

## 常见陷阱 {#pitfalls}

1. **reasoning_effort 陷阱（自一等公民 provider 起已由 Hermes 处理）。**
   Actual 的 SGLang/vLLM 后端只接受 `none/low/medium/high/max`；
   `xhigh`/`ultra` 过去会以含义不明的
   `Expecting value: line 1 column 1 (char 0)`（一个被包装的 HTTP 400）失败。
   内置 provider 在发送时会把 `xhigh→high`、`ultra→max` 进行钳制。如果在旧版
   Hermes 上请求仍以这种方式返回 400，请设置按模型的上限：
   在 config.yaml 中设置 `agent.reasoning_overrides.<model>: high`。
2. **小型本地模型的上下文窗口溢出。** Hermes 的默认工具集约有 26k token 的
   schema，外加约 9k token 的系统提示词。以 32k 上下文加载的模型在第一轮之前
   就会溢出，而 llama.cpp 系列服务器会发出一个孤零零的 `data: [DONE]` ——
   Hermes 报告为
   `Provider returned an empty stream with no finish_reason`。这不是
   SSE 的 bug。解决办法：限制工具（`-t file,web`），以更大的 `n_ctx` 加载模型，
   或者为完整工具集选用 >=64k 上下文的模型。
   上游跟踪：#51448（不要新开 issue；把证据补充到那里）。
   相关但不同的问题：#65631（HTTP-200 的 SSE 中携带 400），#56516
   （只有推理内容的流）。
3. **下载 id 与安装名称不同。** `actual models download` 接受
   `repo/QUANT`，没有明确的量化方式时会返回 409；
   `actual models load` 接受的是 `actual models list` 中的安装名称。
4. **推理模型返回空内容。** GLM/Qwen 的推理变体会把思考过程放在单独的
   `reasoning` 字段中，并可能把较小的 `max_tokens` 全部耗在推理上。
   在认定失败之前，先给足 max_tokens。
5. **不要创建名为 `actual` 的自定义 provider。** 较早的配置指南
   （一等公民支持之前）会写入 `providers.actual.*` 配置块。在当前版本的
   Hermes 上，内置 provider 优先占用该名称；过时的自定义配置块会被忽略
   或产生冲突。请删除它们，改用上文的环境变量 + model.provider 流程。

## 验证 {#verification}

```bash
# Relay:
hermes chat -Q -q "Reply with exactly: ACTUAL_OK" --provider actual -m MODEL
# Local (small model — reduced toolset):
hermes chat -Q -q "Reply with exactly: LOCAL_OK" --provider actual -m MODEL -t file,web
# Provider status (local no-auth shows key_source=local-offline):
hermes status
```

对于其他兼容 OpenAI 的客户端（例如 OpenCode），请参阅
`references/opencode.md`。
