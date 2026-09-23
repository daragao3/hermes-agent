---
title: "Comfyui — 通过扩散工作流生成图像、视频和音频"
sidebar_label: "Comfyui"
description: "通过扩散工作流生成图像、视频和音频"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Comfyui

通过扩散工作流生成图像、视频和音频。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选——通过 `hermes skills install official/creative/comfyui` 安装 |
| 路径 | `optional-skills/creative/comfyui` |
| 版本 | `5.1.0` |
| 作者 | ['kshitijk4poor', 'alt-glitch', 'purzbeats'] |
| 许可证 | MIT |
| 平台 | macos, linux, windows |
| 标签 | `comfyui`, `image-generation`, `stable-diffusion`, `flux`, `sd3`, `wan-video`, `hunyuan-video`, `creative`, `generative-ai`, `video-generation` |
| 相关 skill | [`stable-diffusion`](/user-guide/skills/optional/mlops/mlops-stable-diffusion) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# ComfyUI

通过 ComfyUI 生成图像、视频、音频和 3D 内容：使用官方 `comfy-cli` 负责安装配置与生命周期管理，使用 REST/WebSocket API 直接执行工作流。

## 本 skill 包含的内容 {#whats-in-this-skill}

**参考文档（`references/`）：**

- `official-cli.md` —— 所有 `comfy ...` 命令及其参数
- `rest-api.md` —— REST + WebSocket 端点（本地 + 云端）、请求载荷 schema
- `workflow-format.md` —— API 格式 JSON、常见节点类型、参数映射
- `template-integrity.md` —— 将 `comfyui-workflow-templates` 从编辑器格式转换为 API 格式：绕过 Reroute 节点、带点号的动态输入键（`values.a`、`resize_type.width`）、Cloud 的特殊行为（302 重定向、免费版仅 1 个并发任务、1080p 显存上限）、兼容 Discord 的 ffmpeg 拼接。作者 [@purzbeats](https://github.com/purzbeats)。凡是从官方模板起步时都应加载此文档。

**脚本（`scripts/`）：**

| 脚本 | 用途 |
|--------|---------|
| `_common.py` | 共享的 HTTP、云端路由、节点目录（不要直接运行） |
| `hardware_check.py` | 探测 GPU/显存/磁盘 → 推荐本地或 Comfy Cloud |
| `comfyui_setup.sh` | 硬件检查 + comfy-cli + ComfyUI 安装 + 启动 + 验证 |
| `extract_schema.py` | 读取工作流 → 列出可控参数 + 模型依赖 |
| `check_deps.py` | 对照运行中的服务器检查工作流 → 列出缺失的节点/模型 |
| `auto_fix_deps.py` | 运行 check_deps，然后执行 `comfy node install` / `comfy model download` |
| `run_workflow.py` | 注入参数、提交、监控、下载输出（HTTP 或 WS） |
| `run_batch.py` | 以参数扫描方式提交工作流 N 次，并行数取决于你的套餐等级 |
| `ws_monitor.py` | 执行中任务的实时 WebSocket 查看器（实时进度） |
| `health_check.py` | 验证清单执行器 —— comfy-cli + 服务器 + 模型 + 冒烟测试 |
| `fetch_logs.py` | 拉取指定 prompt_id 的 traceback / 状态消息 |

**示例工作流（`workflows/`）：** SD 1.5、SDXL、Flux Dev、SDXL img2img、SDXL inpaint、ESRGAN 放大、AnimateDiff 视频、Wan T2V。参见 `workflows/README.md`。

## 使用场景 {#when-to-use}

- 用户要求使用 Stable Diffusion、SDXL、Flux、SD3 等生成图像
- 用户想运行某个特定的 ComfyUI 工作流文件
- 用户想串联多个生成步骤（txt2img → 放大 → 面部修复）
- 用户需要 ControlNet、inpainting、img2img 或其他高级管线
- 用户要求管理 ComfyUI 队列、检查模型或安装自定义节点
- 用户想通过 AnimateDiff、Hunyuan、Wan、AudioCraft 等生成视频/音频/3D 内容

## 架构：两层 {#architecture-two-layers}

<!-- ascii-guard-ignore -->
```
┌─────────────────────────────────────────────────────┐
│ Layer 1: comfy-cli (official lifecycle tool)        │
│   Setup, server lifecycle, custom nodes, models     │
│   → comfy install / launch / stop / node / model    │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│ Layer 2: REST/WebSocket API + skill scripts         │
│   Workflow execution, param injection, monitoring   │
│   POST /api/prompt, GET /api/view, WS /ws           │
│   → run_workflow.py, run_batch.py, ws_monitor.py    │
└─────────────────────────────────────────────────────┘
```
<!-- ascii-guard-ignore-end -->

**为什么分两层？** 官方 CLI 非常适合安装和服务器管理，但对工作流执行的支持很有限。REST/WS API 填补了这一空白 —— 脚本负责 CLI 不做的参数注入、执行监控和输出下载。

## 快速开始 {#quick-start}

### 检测环境 {#detect-environment}

```bash
# 有哪些可用？
command -v comfy >/dev/null 2>&1 && echo "comfy-cli: installed"
curl -s http://127.0.0.1:8188/system_stats 2>/dev/null && echo "server: running"

# 这台机器能在本地运行 ComfyUI 吗？（GPU/显存/磁盘检查）
python scripts/hardware_check.py
```

如果什么都没安装，请参阅下文的 **安装与上手** —— 但务必先运行硬件检查。

### 一行命令健康检查 {#one-line-health-check}

```bash
python scripts/health_check.py
# → JSON：comfy_cli 是否在 PATH 中？服务器是否可达？至少有一个 checkpoint？冒烟测试是否通过？
```

## 核心工作流 {#core-workflow}

### 第 1 步：获取 API 格式的工作流 JSON {#step-1-get-a-workflow-json-in-api-format}

工作流必须是 API 格式（每个节点都有 `class_type`）。来源包括：

- ComfyUI Web 界面 → **Workflow → Export (API)**（新版界面）或旧版的 "Save (API Format)" 按钮（旧版界面）
- 本 skill 的 `workflows/` 目录（可直接运行的示例）
- 社区下载（civitai、Reddit、Discord）—— 通常是编辑器格式，必须先加载到 ComfyUI 中再重新导出

编辑器格式（顶层为 `nodes` 和 `links` 数组）**无法直接执行**。脚本会检测到这种情况并提示你重新导出。

### 第 2 步：查看哪些参数可控 {#step-2-see-whats-controllable}

```bash
python scripts/extract_schema.py workflow_api.json --summary-only
# → {"parameter_count": 12, "has_negative_prompt": true, "has_seed": true, ...}

python scripts/extract_schema.py workflow_api.json
# → 包含参数、模型依赖、embedding 引用的完整 schema
```

### 第 3 步：带参数运行 {#step-3-run-with-parameters}

```bash
# 本地（默认 http://127.0.0.1:8188）
python scripts/run_workflow.py \
  --workflow workflow_api.json \
  --args '{"prompt": "a beautiful sunset over mountains", "seed": -1, "steps": 30}' \
  --output-dir ./outputs

# 云端（导出一次 API key；自动使用正确的 /api 路由）
export COMFY_CLOUD_API_KEY="comfyui-..."
python scripts/run_workflow.py \
  --workflow workflow_api.json \
  --args '{"prompt": "..."}' \
  --host https://cloud.comfy.org \
  --output-dir ./outputs

# 通过 WebSocket 获取实时进度（需要 `pip install websocket-client`）
python scripts/run_workflow.py \
  --workflow flux_dev.json \
  --args '{"prompt": "..."}' \
  --ws

# img2img / inpaint：传入 --input-image 即可自动上传并引用
python scripts/run_workflow.py \
  --workflow sdxl_img2img.json \
  --input-image image=./photo.png \
  --args '{"prompt": "make it watercolor", "denoise": 0.6}'

# 批量 / 参数扫描：8 个随机种子，并行数上限为云端套餐限制
python scripts/run_batch.py \
  --workflow sdxl.json \
  --args '{"prompt": "abstract"}' \
  --count 8 --randomize-seed --parallel 3 \
  --output-dir ./outputs/batch
```

`seed` 设为 `-1`（或省略它并使用 `--randomize-seed`）会在每次运行时生成新的随机种子。

### 第 4 步：展示结果 {#step-4-present-results}

脚本会向 stdout 输出描述每个输出文件的 JSON：

```json
{
  "status": "success",
  "prompt_id": "abc-123",
  "outputs": [
    {"file": "./outputs/sdxl_00001_.png", "node_id": "9",
     "type": "image", "filename": "sdxl_00001_.png"}
  ]
}
```

## 决策树 {#decision-tree}

| 用户说 | 工具 | 命令 |
|-----------|------|---------|
| **生命周期（使用 comfy-cli）** | | |
| "安装 ComfyUI" | comfy-cli | `bash scripts/comfyui_setup.sh` |
| "启动 ComfyUI" | comfy-cli | `comfy launch --background` |
| "停止 ComfyUI" | comfy-cli | `comfy stop` |
| "安装 X 节点" | comfy-cli | `comfy node install <name>` |
| "下载 X 模型" | comfy-cli | `comfy model download --url <url> --relative-path models/checkpoints` |
| "列出已安装的模型" | comfy-cli | `comfy model list` |
| "列出已安装的节点" | comfy-cli | `comfy node show installed` |
| **执行（使用脚本）** | | |
| "一切都准备好了吗？" | 脚本 | `health_check.py`（可选加上 `--workflow X --smoke-test`） |
| "这个工作流里我能改什么？" | 脚本 | `extract_schema.py W.json` |
| "检查 W 的依赖是否满足" | 脚本 | `check_deps.py W.json` |
| "修复缺失的依赖" | 脚本 | `auto_fix_deps.py W.json` |
| "生成一张图像" | 脚本 | `run_workflow.py --workflow W --args '{...}'` |
| "用这张图"（img2img） | 脚本 | `run_workflow.py --input-image image=./x.png ...` |
| "用随机种子生成 8 个变体" | 脚本 | `run_batch.py --count 8 --randomize-seed ...` |
| "给我看实时进度" | 脚本 | `ws_monitor.py --prompt-id <id>` |
| "获取任务 X 的错误信息" | 脚本 | `fetch_logs.py <prompt_id>` |
| **直接调用 REST** | | |
| "队列里有什么？" | REST | `curl http://HOST:8188/queue`（本地）或 `--host https://cloud.comfy.org` |
| "取消它" | REST | `curl -X POST http://HOST:8188/interrupt` |
| "释放 GPU 显存" | REST | `curl -X POST http://HOST:8188/free` |

## 安装与上手 {#setup--onboarding}

当用户要求安装配置 ComfyUI 时，**第一件事是询问他们想用 Comfy Cloud（托管、零安装、需 API key）还是本地（在自己的机器上安装 ComfyUI）**。在他们回答之前，不要开始运行安装命令或硬件检查。

**官方文档：** https://docs.comfy.org/installation
**CLI 文档：** https://docs.comfy.org/comfy-cli/getting-started
**Cloud 文档：** https://docs.comfy.org/get_started/cloud
**Cloud API：** https://docs.comfy.org/development/cloud/overview

### 第 0 步：询问本地还是云端（始终第一步） {#step-0-ask-local-vs-cloud-always-first}

建议话术：

> "你想在自己的机器上本地运行 ComfyUI，还是使用 Comfy Cloud？
>
> - **Comfy Cloud** —— 托管在 RTX 6000 Pro GPU 上，预装所有常用模型，
>   零配置。需要 API key（实际运行工作流需要付费订阅；
>   免费版为只读）。如果你没有性能足够的 GPU，这是最佳选择。
> - **本地** —— 免费，但你的机器必须满足硬件要求：
>   - NVIDIA GPU，**≥6 GB 显存**（SDXL 需 ≥8 GB，Flux/视频需 ≥12 GB），或
>   - 支持 ROCm 的 AMD GPU（Linux），或
>   - Apple Silicon Mac（M1+），**≥16 GB 统一内存**（推荐 ≥32 GB）。
>   - Intel Mac 和没有 GPU 的机器无法运行 —— 请改用 Cloud。
>
> 你想选哪个？"

分流：

- **Cloud** → 直接跳到 **路径 A**。
- **本地** → 先运行硬件检查，再根据结论从路径 B–E 中选择一条。
- **不确定** → 运行硬件检查，由结论决定。

### 第 1 步：验证硬件（仅当用户选择本地时） {#step-1-verify-hardware-only-if-user-chose-local}

```bash
python scripts/hardware_check.py --json
# 可选：同时探测 `torch` 以确认实际的 CUDA/MPS：
python scripts/hardware_check.py --json --check-pytorch
```

| 结论    | 含义                                                       | 操作 |
|------------|---------------------------------------------------------------|--------|
| `ok`       | ≥8 GB 显存（独立显卡）或 ≥32 GB 统一内存（Apple Silicon）       | 本地安装 —— 使用报告中的 `comfy_cli_flag` |
| `marginal` | SD1.5 可用；SDXL 吃紧；Flux/视频基本不行                  | 轻量工作流可本地运行，否则走 **路径 A（Cloud）** |
| `cloud`    | 无可用 GPU、显存 &lt;6 GB、Apple 统一内存 &lt;16 GB、Intel Mac、Rosetta 下的 Python | **改用 Cloud**，除非用户明确坚持本地 |

脚本还会报告 `wsl: true`（带 NVIDIA 直通的 WSL2）和 `rosetta: true`（Apple Silicon 上的 x86_64 Python —— 必须重新安装为 ARM64 版本）。

如果结论是 `cloud` 但用户想要本地，不要默默继续。原样展示 `notes` 数组，并询问他们是想 (a) 改用 Cloud，还是 (b) 强制本地安装（在现代模型上会 OOM 或慢到无法使用）。

### 选择安装路径 {#choosing-an-installation-path}

优先使用硬件检查。下表是在用户已经告诉你其硬件情况时的后备方案：

| 情况 | 推荐路径 |
|-----------|------------------|
| 硬件检查结论为 `verdict: cloud` | **路径 A：Comfy Cloud** |
| 没有 GPU / 想先试试不做投入 | **路径 A：Comfy Cloud** |
| Windows + NVIDIA + 非技术用户 | **路径 B：ComfyUI Desktop** |
| Windows + NVIDIA + 技术用户 | **路径 C：Portable** 或 **路径 D：comfy-cli** |
| Linux + 任意 GPU | **路径 D：comfy-cli**（最简单） |
| macOS + Apple Silicon | **路径 B：Desktop** 或 **路径 D：comfy-cli** |
| 无头 / 服务器 / CI / agent | **路径 D：comfy-cli** |

全自动路径（硬件检查 → 安装 → 启动 → 验证）：

```bash
bash scripts/comfyui_setup.sh
# 或带覆盖参数：
bash scripts/comfyui_setup.sh --m-series --port=8190 --workspace=/data/comfy
```

它会在内部运行 `hardware_check.py`，当结论为 `cloud` 时拒绝本地安装（除非使用 `--force-cloud-override`），选择正确的 `comfy-cli` 参数，并优先使用 `pipx`/`uvx` 而非全局 `pip`，以免污染系统 Python。

---

### 路径 A：Comfy Cloud（无需本地安装） {#path-a-comfy-cloud-no-local-install}

适合没有性能足够的 GPU 或希望零配置的用户。托管在 RTX 6000 Pro 上。

**文档：** https://docs.comfy.org/get_started/cloud

1. 在 https://comfy.org/cloud 注册
2. 在 https://platform.comfy.org/login 生成 API key
3. 设置 key：
   ```bash
   export COMFY_CLOUD_API_KEY="your-comfyui-key"
   ```
4. 运行工作流：
   ```bash
   python scripts/run_workflow.py \
     --workflow workflows/flux_dev_txt2img.json \
     --args '{"prompt": "..."}' \
     --host https://cloud.comfy.org \
     --output-dir ./outputs
   ```

**价格：** https://www.comfy.org/cloud/pricing
**并发任务数：** Free/Standard 1，Creator 3，Pro 5。免费版**无法通过 API 运行工作流** —— 只能浏览模型。`/api/prompt`、`/api/upload/*`、`/api/view` 等需要付费订阅。

---

### 路径 B：ComfyUI Desktop（Windows / macOS） {#path-b-comfyui-desktop-windows--macos}

面向非技术用户的一键安装程序。目前为 Beta 版。

**文档：** https://docs.comfy.org/installation/desktop
- **Windows（NVIDIA）：** https://download.comfy.org/windows/nsis/x64
- **macOS（Apple Silicon）：** https://comfy.org

Desktop **不支持** Linux —— 请使用路径 D。

---

### 路径 C：ComfyUI Portable（仅限 Windows） {#path-c-comfyui-portable-windows-only}

**文档：** https://docs.comfy.org/installation/comfyui_portable_windows

从 https://github.com/comfyanonymous/ComfyUI/releases 下载，解压后运行 `run_nvidia_gpu.bat`。通过 `update/update_comfyui_stable.bat` 更新。

---

### 路径 D：comfy-cli（全平台 —— 推荐 agent 使用） {#path-d-comfy-cli-all-platforms--recommended-for-agents}

官方 CLI 是无头/自动化安装的最佳路径。

**文档：** https://docs.comfy.org/comfy-cli/getting-started

#### 安装 comfy-cli {#install-comfy-cli}

```bash
# 推荐：
pipx install comfy-cli
# 或使用 uvx 免安装运行：
uvx --from comfy-cli comfy --help
# 或（如果 pipx/uvx 不可用）：
pip install --user comfy-cli
```

以非交互方式禁用统计分析：
```bash
comfy --skip-prompt tracking disable
```

#### 安装 ComfyUI {#install-comfyui}

```bash
comfy --skip-prompt install --nvidia              # NVIDIA (CUDA)
comfy --skip-prompt install --amd                 # AMD (ROCm, Linux)
comfy --skip-prompt install --m-series            # Apple Silicon (MPS)
comfy --skip-prompt install --cpu                 # CPU only (slow)
comfy --skip-prompt install --nvidia --fast-deps  # uv-based dep resolution
```

默认位置：`~/comfy/ComfyUI`（Linux）、`~/Documents/comfy/ComfyUI`（macOS/Win）。可用 `comfy --workspace /custom/path install` 覆盖。

#### 启动 / 验证 {#launch--verify}

```bash
comfy launch --background                       # background daemon on :8188
comfy launch -- --listen 0.0.0.0 --port 8190    # LAN-accessible custom port
curl -s http://127.0.0.1:8188/system_stats      # health check
```

---

### 路径 E：手动安装（高级 / 不受支持的硬件） {#path-e-manual-install-advanced--unsupported-hardware}

适用于 Ascend NPU、Cambricon MLU、Intel Arc 或其他不受支持的硬件。

**文档：** https://docs.comfy.org/installation/manual_install

```bash
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
python main.py
```

---

### 安装后：下载模型 {#post-install-download-models}

```bash
# SDXL（通用，约 6.5 GB）
comfy model download \
  --url "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" \
  --relative-path models/checkpoints

# SD 1.5（更轻量，约 4 GB，适合 6 GB 显卡）
comfy model download \
  --url "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors" \
  --relative-path models/checkpoints

# Flux Dev fp8（较小的变体，约 12 GB）
comfy model download \
  --url "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors" \
  --relative-path models/checkpoints

# CivitAI（先设置 token）：
comfy model download \
  --url "https://civitai.com/api/download/models/128713" \
  --relative-path models/checkpoints \
  --set-civitai-api-token "YOUR_TOKEN"
```

列出已安装的模型：`comfy model list`。

### 安装后：安装自定义节点 {#post-install-install-custom-nodes}

```bash
comfy node install comfyui-impact-pack             # popular utility pack
comfy node install comfyui-animatediff-evolved     # video generation
comfy node install comfyui-controlnet-aux          # ControlNet preprocessors
comfy node install comfyui-essentials              # common helpers
comfy node update all
comfy node install-deps --workflow=workflow.json   # install everything a workflow needs
```

### 安装后：验证 {#post-install-verify}

```bash
python scripts/health_check.py
# → comfy_cli 是否在 PATH 中？服务器是否可达？checkpoint？冒烟测试？

python scripts/check_deps.py my_workflow.json
# → 这个工作流的节点/模型/embedding 是否都已安装？

python scripts/run_workflow.py \
  --workflow workflows/sd15_txt2img.json \
  --args '{"prompt": "test", "steps": 4}' \
  --output-dir ./test-outputs
```

## 图像上传（img2img / Inpainting） {#image-upload-img2img--inpainting}

最简单的方式是在 `run_workflow.py` 中使用 `--input-image`：

```bash
python scripts/run_workflow.py \
  --workflow workflows/sdxl_img2img.json \
  --input-image image=./photo.png \
  --args '{"prompt": "make it cyberpunk", "denoise": 0.6}'
```

该参数会上传 `photo.png`，然后将其服务器端文件名注入到名为 `image` 的 schema 参数中。对于 inpainting，两者都要传：

```bash
python scripts/run_workflow.py \
  --workflow workflows/sdxl_inpaint.json \
  --input-image image=./photo.png \
  --input-image mask_image=./mask.png \
  --args '{"prompt": "fill with flowers"}'
```

通过 REST 手动上传：
```bash
curl -X POST "http://127.0.0.1:8188/upload/image" \
  -F "image=@photo.png" -F "type=input" -F "overwrite=true"
# 返回：{"name": "photo.png", "subfolder": "", "type": "input"}

# 云端等效命令：
curl -X POST "https://cloud.comfy.org/api/upload/image" \
  -H "X-API-Key: $COMFY_CLOUD_API_KEY" \
  -F "image=@photo.png" -F "type=input" -F "overwrite=true"
```

## Cloud 细节 {#cloud-specifics}

- **Base URL：** `https://cloud.comfy.org`
- **认证：** `X-API-Key` 请求头（WebSocket 使用 `?token=KEY`）
- **API key：** 设置一次 `$COMFY_CLOUD_API_KEY`，脚本会自动读取
- **输出下载：** `/api/view` 返回指向签名 URL 的 302；脚本会跟随重定向，并在从存储后端获取文件前剥离 `X-API-Key`（不要把 API key 泄露给 S3/CloudFront）。
- **与本地 ComfyUI 的端点差异：**
  - `/api/object_info`、`/api/queue`、`/api/userdata` —— **免费版返回 403**；仅限付费。
  - 云端上 `/history` 更名为 `/history_v2`（脚本会自动路由）。
  - 云端上 `/models/<folder>` 更名为 `/experiment/models/<folder>`（脚本会自动路由）。
  - WebSocket 中的 `clientId` 目前被忽略 —— 同一用户的所有连接接收相同的广播。请在客户端按 `prompt_id` 过滤。
  - 上传时接受 `subfolder` 但会被忽略 —— 云端使用扁平命名空间。
- **并发任务数：** Free/Standard：1，Creator：3，Pro：5。超出的任务会自动排队。使用 `run_batch.py --parallel N` 用满你的套餐额度。

## 队列与系统管理 {#queue--system-management}

```bash
# 本地
curl -s http://127.0.0.1:8188/queue | python -m json.tool
curl -X POST http://127.0.0.1:8188/queue -d '{"clear": true}'    # cancel pending
curl -X POST http://127.0.0.1:8188/interrupt                      # cancel running
curl -X POST http://127.0.0.1:8188/free \
  -H "Content-Type: application/json" \
  -d '{"unload_models": true, "free_memory": true}'

# 云端 —— 路径相同但位于 /api/ 下，另外还有：
python scripts/fetch_logs.py --tail-queue --host https://cloud.comfy.org
```

## 常见陷阱 {#pitfalls}

1. **必须使用 API 格式** —— 所有脚本以及 `/api/prompt` 端点都要求 API 格式的工作流 JSON。脚本会检测编辑器格式（顶层为 `nodes` 和 `links` 数组），并提示你通过 "Workflow → Export (API)"（新版界面）或 "Save (API Format)"（旧版界面）重新导出。

2. **服务器必须在运行** —— 所有执行都需要一个在线的服务器。`comfy launch --background` 可启动一个。用 `curl http://127.0.0.1:8188/system_stats` 验证。

3. **模型名称必须精确** —— 区分大小写，包含文件扩展名。`check_deps.py` 会做模糊匹配（带/不带扩展名和文件夹前缀），但工作流本身必须使用规范名称。用 `comfy model list` 查看已安装的内容。

4. **缺少自定义节点** —— "class_type not found" 表示某个必需的节点未安装。`check_deps.py` 会报告需要安装哪个包；`auto_fix_deps.py` 会替你执行安装。

5. **工作目录** —— `comfy-cli` 会自动检测 ComfyUI 工作区。如果命令因 "no workspace found" 失败，请使用 `comfy --workspace /path/to/ComfyUI <command>` 或 `comfy set-default /path/to/ComfyUI`。

6. **Cloud 免费版 API 限制** —— `/api/prompt`、`/api/view`、`/api/upload/*`、`/api/object_info` 在免费账户上都返回 403。`health_check.py` 和 `check_deps.py` 会妥善处理这种情况并给出清晰的提示。

7. **视频/音频工作流的超时** —— 当输出节点为 `VHS_VideoCombine`、`SaveVideo` 等时会自动识别；默认超时从 300 秒提高到 900 秒。可用 `--timeout 1800` 显式覆盖。

8. **输出文件名中的路径穿越** —— 服务器提供的文件名会经过 `safe_path_join`，拒绝任何逃出 `--output-dir` 的路径。请保持此保护开启 —— 带有自定义保存节点的工作流可能产生任意路径。

9. **工作流 JSON 等同于任意代码** —— 自定义节点会运行 Python，因此提交一个未知工作流与 `eval` 具有相同的信任风险。运行来自不可信来源的工作流之前请先检查。

10. **自动随机种子** —— 在 `--args` 中传入 `seed: -1`（或使用 `--randomize-seed` 并省略 seed），每次运行都会得到新的种子。实际使用的种子会记录到 stderr。

11. **`tracking` 提示** —— 首次运行 `comfy` 时可能会弹出统计分析提示。使用 `comfy --skip-prompt tracking disable` 以非交互方式跳过。`comfyui_setup.sh` 会替你完成这一步。

## 验证清单 {#verification-checklist}

使用 `python scripts/health_check.py` 一次性执行整个清单。手动检查：

- [ ] `hardware_check.py` 结论为 `ok`，或用户明确选择了 Comfy Cloud
- [ ] `comfy --version` 可用（或 `uvx --from comfy-cli comfy --help`）
- [ ] `curl http://HOST:PORT/system_stats` 返回 JSON
- [ ] `comfy model list` 至少显示一个 checkpoint（本地），或
      `/api/experiment/models/checkpoints` 返回模型（云端）
- [ ] 工作流 JSON 为 API 格式
- [ ] `check_deps.py` 报告 `is_ready: true`（或在云端免费版上仅有 `node_check_skipped`）
- [ ] 用一个小型工作流进行的测试运行成功完成；输出落在 `--output-dir` 中
