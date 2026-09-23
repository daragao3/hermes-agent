---
sidebar_position: 9
title: "可选技能目录"
description: "hermes-agent 附带的官方可选技能 — 通过 hermes skills install official/<category>/<skill> 安装"
---

# 可选技能目录

可选技能随 hermes-agent 一起发布，位于 `optional-skills/` 目录下，但**默认未激活**。请显式安装：

```bash
hermes skills install official/<category>/<skill>
```

示例：

```bash
hermes skills install official/blockchain/solana
hermes skills install official/mlops/flash-attention
```

下方每个技能均链接至专属页面，包含完整定义、配置和使用说明。

卸载方式：

```bash
hermes skills uninstall <skill-name>
```

## autonomous-ai-agents

| 技能 | 描述 |
|-------|-------------|
| [**agent-merge-conflict-arbiter**](/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-agent-merge-conflict-arbiter) | 两个 agent 之间合并冲突的中立仲裁者。 |
| [**antigravity-cli**](/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-antigravity-cli) | 操作 Antigravity CLI（agy）：插件、鉴权、沙箱。 |
| [**blackbox**](/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-blackbox) | 将编码任务委托给 Blackbox AI 多模型 CLI。 |
| [**grok**](/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-grok) | 将编码任务委托给 xAI Grok Build CLI（功能开发、PR）。 |
| [**honcho**](/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-honcho) | 为 Hermes 配置 Honcho 记忆并排查问题。 |
| [**openhands**](/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-openhands) | 将编码任务委托给 OpenHands CLI（模型无关，基于 LiteLLM）。 |

## blockchain

| 技能 | 描述 |
|-------|-------------|
| [**evm**](/user-guide/skills/optional/blockchain/blockchain-evm) | 只读 EVM 客户端：覆盖 8 条链的钱包、代币、gas。 |
| [**hyperliquid**](/user-guide/skills/optional/blockchain/blockchain-hyperliquid) | Hyperliquid 市场数据、账户历史、交易复盘。 |
| [**solana**](/user-guide/skills/optional/blockchain/blockchain-solana) | 以美元计价查询 Solana 钱包、代币、交易和 NFT。 |

## communication

| 技能 | 描述 |
|-------|-------------|
| [**one-three-one-rule**](/user-guide/skills/optional/communication/communication-one-three-one-rule) | 1-3-1 决策简报：一个问题、三个选项、一个推荐。 |

## creative

| 技能 | 描述 |
|-------|-------------|
| [**ascii-art**](/user-guide/skills/optional/creative/creative-ascii-art) | ASCII 艺术：pyfiglet、cowsay、boxes、图片转 ASCII。 |
| [**audiocraft-audio-generation**](/user-guide/skills/optional/creative/creative-audiocraft-audio-generation) | AudioCraft：MusicGen 文本生成音乐，AudioGen 文本生成音效。 |
| [**baoyu-article-illustrator**](/user-guide/skills/optional/creative/creative-baoyu-article-illustrator) | 文章插图：类型 × 风格 × 配色保持一致。 |
| [**baoyu-comic**](/user-guide/skills/optional/creative/creative-baoyu-comic) | 知识漫画：教育、人物传记、教程。 |
| [**comfyui**](/user-guide/skills/optional/creative/creative-comfyui) | 通过扩散工作流生成图像、视频和音频。 |
| [**concept-diagrams**](/user-guide/skills/optional/creative/creative-concept-diagrams) | 以 HTML 形式生成扁平、极简的教学用 SVG 图示。 |
| [**creative-ideation**](/user-guide/skills/optional/creative/creative-creative-ideation) | 借助创意实践中的具名方法生成点子。 |
| [**draw-your-font**](/user-guide/skills/optional/creative/creative-draw-your-font) | 把手写照片变成可安装的 TTF 字体。 |
| [**excalidraw**](/user-guide/skills/optional/creative/creative-excalidraw) | 手绘风格的 Excalidraw JSON 图表（架构、流程、时序）。 |
| [**heartmula**](/user-guide/skills/optional/creative/creative-heartmula) | HeartMuLa：根据歌词 + 标签生成类似 Suno 的歌曲。 |
| [**hyperframes**](/user-guide/skills/optional/creative/creative-hyperframes) | 将 HTML 合成渲染为 MP4/WebM 视频。 |
| [**impeccable**](/user-guide/skills/optional/creative/creative-impeccable) | 前端设计指导，由上游维护（impeccable）。 |
| [**kanban-video-orchestrator**](/user-guide/skills/optional/creative/creative-kanban-video-orchestrator) | 规划并运行多 agent 视频制作流水线。 |
| [**meme-generation**](/user-guide/skills/optional/creative/creative-meme-generation) | 基于模板用 Pillow 叠加文字，生成表情包 PNG。 |
| [**pixel-art**](/user-guide/skills/optional/creative/creative-pixel-art) | 带时代调色板的像素画（NES、Game Boy、PICO-8）。 |
| [**pretext**](/user-guide/skills/optional/creative/creative-pretext) | 用无 DOM 的文本布局构建创意浏览器演示。 |
| [**simple-english**](/user-guide/skills/optional/creative/creative-simple-english) | 将文本改写为 ASD-STE100 简化技术英语。 |
| [**sketch**](/user-guide/skills/optional/creative/creative-sketch) | 一次性 HTML 原型：2-3 个设计变体供比较。 |
| [**social-media-content-calendar**](/user-guide/skills/optional/creative/creative-social-media-content-calendar) | 规划多平台社媒活动：从简报到发布。 |
| [**tldraw-offline**](/user-guide/skills/optional/creative/creative-tldraw-offline) | 用 agent 驱动并编写 tldraw 离线画布脚本。 |
| [**touchdesigner-mcp**](/user-guide/skills/optional/creative/creative-touchdesigner-mcp) | 通过 twozero MCP 控制 TouchDesigner。 |
| [**unreal-mcp**](/user-guide/skills/optional/creative/creative-unreal-mcp) | 自动化 Unreal Engine 编辑器中的场景、Actor 和渲染。 |

## data-science

| 技能 | 描述 |
|-------|-------------|
| [**jupyter-notebook**](/user-guide/skills/optional/data-science/data-science-jupyter-notebook) | 通过实时 Jupyter kernel 迭代运行 Python（hamelnb）。 |

## devops

| 技能 | 描述 |
|-------|-------------|
| [**actual-setup**](/user-guide/skills/optional/devops/devops-actual-setup) | 在 Hermes 中配置 Actual Computer（actual.inc）推理。 |
| [**docker-management**](/user-guide/skills/optional/devops/devops-docker-management) | 管理 Docker 容器、镜像、卷和 Compose。 |
| [**hermes-s6-container-supervision**](/user-guide/skills/optional/devops/devops-hermes-s6-container-supervision) | 修改或调试 Hermes Docker 镜像中的 s6 服务。 |
| [**inference-sh-cli**](/user-guide/skills/optional/devops/devops-inference-sh-cli) | 通过 inference.sh CLI 运行 150+ 个 AI 应用（图像、视频、LLM）。 |
| [**pinggy-tunnel**](/user-guide/skills/optional/devops/devops-pinggy-tunnel) | 通过 Pinggy 基于 SSH 建立免安装的 localhost 隧道。 |
| [**setup-wizard-generator**](/user-guide/skills/optional/devops/devops-setup-wizard-generator) | 生成一个 bash 向导，引导人工完成手动配置。 |
| [**watchers**](/user-guide/skills/optional/devops/devops-watchers) | 轮询 RSS、JSON API 和 GitHub，并用水位线去重。 |

## dogfood

| 技能 | 描述 |
|-------|-------------|
| [**adversarial-ux-test**](/user-guide/skills/optional/dogfood/dogfood-adversarial-ux-test) | 扮演挑剔的用户，发现并分类 UX 痛点。 |

## email

| 技能 | 描述 |
|-------|-------------|
| [**agentmail**](/user-guide/skills/optional/email/email-agentmail) | 当 agent 需要 AgentMail CLI 邮箱收件箱时使用。 |

## finance

| 技能 | 描述 |
|-------|-------------|
| [**3-statement-model**](/user-guide/skills/optional/finance/finance-3-statement-model) | 在 Excel 中构建联动的 IS/BS/CF 三表财务模型。 |
| [**comps-analysis**](/user-guide/skills/optional/finance/finance-comps-analysis) | 在 Excel 中构建可比公司估值工作簿。 |
| [**dcf-model**](/user-guide/skills/optional/finance/finance-dcf-model) | 在 Excel 中构建现金流折现估值工作簿。 |
| [**excel-author**](/user-guide/skills/optional/finance/finance-excel-author) | 通过 openpyxl 无界面构建可审计的财务工作簿。 |
| [**lbo-model**](/user-guide/skills/optional/finance/finance-lbo-model) | 在 Excel 中构建含 IRR/MOIC 的杠杆收购工作簿。 |
| [**merger-model**](/user-guide/skills/optional/finance/finance-merger-model) | 在 Excel 中构建并购增厚/摊薄工作簿。 |
| [**polymarket**](/user-guide/skills/optional/finance/finance-polymarket) | 查询 Polymarket：市场、价格、订单簿、历史。 |
| [**pptx-author**](/user-guide/skills/optional/finance/finance-pptx-author) | 通过 python-pptx 无界面构建 PowerPoint 演示文稿。 |
| [**stocks**](/user-guide/skills/optional/finance/finance-stocks) | 通过 Yahoo 获取股票报价、历史、搜索、比较及加密货币数据。 |

## gaming

| 技能 | 描述 |
|-------|-------------|
| [**minecraft-modpack-server**](/user-guide/skills/optional/gaming/gaming-minecraft-modpack-server) | 托管模组版 Minecraft 服务器（CurseForge、Modrinth）。 |
| [**pokemon-player**](/user-guide/skills/optional/gaming/gaming-pokemon-player) | 通过无界面模拟器 + 读取 RAM 来玩宝可梦。 |

## health

| 技能 | 描述 |
|-------|-------------|
| [**fitness-nutrition**](/user-guide/skills/optional/health/health-fitness-nutrition) | 借助 wger/USDA 进行训练计划、宏量营养素和身体指标管理。 |
| [**neuroskill-bci**](/user-guide/skills/optional/health/health-neuroskill-bci) | 使用来自 NeuroSkill 的实时 BCI 认知与情绪状态。 |

## mcp

| 技能 | 描述 |
|-------|-------------|
| [**fastmcp**](/user-guide/skills/optional/mcp/mcp-fastmcp) | 构建、测试和部署 Python MCP 服务器。 |
| [**mcp-oauth-remote-gateway**](/user-guide/skills/optional/mcp/mcp-mcp-oauth-remote-gateway) | 在无界面 gateway 上为远程 MCP 服务器手动完成 OAuth。 |
| [**mcporter**](/user-guide/skills/optional/mcp/mcp-mcporter) | 在终端中列出、认证并调用 MCP 服务器/工具。 |

## migration

| 技能 | 描述 |
|-------|-------------|
| [**openclaw-migration**](/user-guide/skills/optional/migration/migration-openclaw-migration) | 将 OpenClaw 配置（记忆、技能）导入 Hermes。 |

## mlops

| 技能 | 描述 |
|-------|-------------|
| [**accelerate**](/user-guide/skills/optional/mlops/mlops-accelerate) | 以最少改动在多 GPU 上运行 PyTorch 训练。 |
| [**axolotl**](/user-guide/skills/optional/mlops/mlops-training-axolotl) | Axolotl：基于 YAML 的 LLM 微调（LoRA、DPO、GRPO）。 |
| [**chroma**](/user-guide/skills/optional/mlops/mlops-chroma) | 用于 RAG 和语义搜索的嵌入数据库。 |
| [**clip**](/user-guide/skills/optional/mlops/mlops-clip) | 零样本图像分类与图文检索。 |
| [**dspy**](/user-guide/skills/optional/mlops/mlops-research-dspy) | DSPy：声明式 LM 程序，自动优化提示词、RAG。 |
| [**evaluating-llms-harness**](/user-guide/skills/optional/mlops/mlops-evaluation-evaluating-llms-harness) | lm-eval-harness：LLM 基准测试（MMLU、GSM8K 等）。 |
| [**faiss**](/user-guide/skills/optional/mlops/mlops-faiss) | 十亿规模的快速向量相似度搜索。 |
| [**flash-attention**](/user-guide/skills/optional/mlops/mlops-flash-attention) | 加速长序列 Transformer 的训练与推理。 |
| [**guidance**](/user-guide/skills/optional/mlops/mlops-guidance) | 用语法约束 LLM 输出；保证生成有效 JSON。 |
| [**huggingface-hub**](/user-guide/skills/optional/mlops/mlops-models-huggingface-hub) | HuggingFace hf CLI：搜索/下载/上传模型、数据集。 |
| [**huggingface-tokenizers**](/user-guide/skills/optional/mlops/mlops-huggingface-tokenizers) | 快速 BPE/WordPiece 分词及自定义词表训练。 |
| [**instructor**](/user-guide/skills/optional/mlops/mlops-instructor) | 经 Pydantic 校验的结构化 LLM 输出。 |
| [**lambda-labs**](/user-guide/skills/optional/mlops/mlops-lambda-labs) | 用于 ML 训练的按需 GPU 云实例。 |
| [**llama-cpp**](/user-guide/skills/optional/mlops/mlops-inference-llama-cpp) | llama.cpp 本地 GGUF 推理 + HF Hub 模型发现。 |
| [**llava**](/user-guide/skills/optional/mlops/mlops-llava) | 视觉-语言对话：VQA、图像描述、图像对话。 |
| [**modal**](/user-guide/skills/optional/mlops/mlops-modal) | 面向 ML 任务和模型 API 的 Serverless GPU 云。 |
| [**nemo-curator**](/user-guide/skills/optional/mlops/mlops-nemo-curator) | 整理 LLM 训练数据：去重、过滤、PII 脱敏。 |
| [**obliteratus**](/user-guide/skills/optional/mlops/mlops-obliteratus) | OBLITERATUS：消除 LLM 的拒答行为（diff-in-means）。 |
| [**outlines**](/user-guide/skills/optional/mlops/mlops-inference-outlines) | Outlines：结构化 JSON/正则/Pydantic LLM 生成。 |
| [**peft**](/user-guide/skills/optional/mlops/mlops-peft) | 在有限 GPU 显存上用 LoRA 微调大型 LLM。 |
| [**pinecone**](/user-guide/skills/optional/mlops/mlops-pinecone) | 面向生产级 RAG 和搜索的托管向量数据库。 |
| [**pytorch-fsdp**](/user-guide/skills/optional/mlops/mlops-pytorch-fsdp) | 使用 PyTorch FSDP 进行完全分片数据并行训练的专家指导 - 参数分片、混合精度、CPU 卸载、FSDP2 |
| [**pytorch-lightning**](/user-guide/skills/optional/mlops/mlops-pytorch-lightning) | 内置分布式支持的简洁训练循环。 |
| [**qdrant**](/user-guide/skills/optional/mlops/mlops-qdrant) | 面向生产级 RAG 系统的向量搜索引擎。 |
| [**saelens**](/user-guide/skills/optional/mlops/mlops-saelens) | 训练稀疏自编码器以解释模型特征。 |
| [**segment-anything-model**](/user-guide/skills/optional/mlops/mlops-models-segment-anything-model) | SAM：通过点、框、掩码进行零样本图像分割。 |
| [**serving-llms-vllm**](/user-guide/skills/optional/mlops/mlops-inference-serving-llms-vllm) | vLLM：高吞吐 LLM 服务、OpenAI API、量化。 |
| [**simpo**](/user-guide/skills/optional/mlops/mlops-simpo) | 无需参考模型的偏好对齐，比 DPO 更简单。 |
| [**slime**](/user-guide/skills/optional/mlops/mlops-slime) | 基于 Megatron 和 SGLang 的 LLM 强化学习后训练。 |
| [**stable-diffusion**](/user-guide/skills/optional/mlops/mlops-stable-diffusion) | 文生图、局部重绘和图生图。 |
| [**tensorrt-llm**](/user-guide/skills/optional/mlops/mlops-tensorrt-llm) | 在 NVIDIA GPU 上进行高吞吐 LLM 推理。 |
| [**torchtitan**](/user-guide/skills/optional/mlops/mlops-torchtitan) | 借助 PyTorch 4D 并行大规模预训练 LLM。 |
| [**trl-fine-tuning**](/user-guide/skills/optional/mlops/mlops-training-trl-fine-tuning) | TRL：用于 LLM RLHF 的 SFT、DPO、GRPO、RLOO 奖励建模。 |
| [**unsloth**](/user-guide/skills/optional/mlops/mlops-training-unsloth) | Unsloth：LoRA/QLoRA 微调提速 2-5 倍，显存占用更低。 |
| [**weights-and-biases**](/user-guide/skills/optional/mlops/mlops-evaluation-weights-and-biases) | W&B：记录 ML 实验、超参扫描、模型注册表、仪表盘。 |
| [**whisper**](/user-guide/skills/optional/mlops/mlops-whisper) | 转写并翻译 99 种语言的语音。 |

## payments

| 技能 | 描述 |
|-------|-------------|
| [**mpp-agent**](/user-guide/skills/optional/payments/payments-mpp-agent) | 通过 Machine Payments Protocol（MPP）支付 HTTP 402 API。 |
| [**stripe-link-cli**](/user-guide/skills/optional/payments/payments-stripe-link-cli) | 通过 Stripe Link 进行 agent 支付——银行卡、SPT、审批。 |
| [**stripe-projects**](/user-guide/skills/optional/payments/payments-stripe-projects) | 通过 Stripe Projects 开通 SaaS 服务并同步凭据。 |

## productivity

| 技能 | 描述 |
|-------|-------------|
| [**canvas**](/user-guide/skills/optional/productivity/productivity-canvas) | 通过 API token 获取 Canvas LMS 课程和作业。 |
| [**decision-questionnaire**](/user-guide/skills/optional/productivity/productivity-decision-questionnaire) | 把一个难以直接回答的决策变成一份问卷文档。 |
| [**here-now**](/user-guide/skills/optional/productivity/productivity-here-now) | 将站点发布到 &#123;slug&#125;.here.now，并在 Drives 中存储文件。 |
| [**memento-flashcards**](/user-guide/skills/optional/productivity/productivity-memento-flashcards) | 间隔重复记忆卡片：创建、复习、测验、导出。 |
| [**property-listings**](/user-guide/skills/optional/productivity/productivity-property-listings) | 以桌面卡片形式展示房产和租赁房源。 |
| [**shop**](/user-guide/skills/optional/productivity/productivity-shop) | Shop 商品目录搜索、结账、订单跟踪、退货。 |
| [**shopify**](/user-guide/skills/optional/productivity/productivity-shopify) | 通过 curl 查询 Shopify Admin/Storefront GraphQL API。 |
| [**siyuan**](/user-guide/skills/optional/productivity/productivity-siyuan) | 通过 API 查询和编辑思源笔记知识库。 |
| [**telephony**](/user-guide/skills/optional/productivity/productivity-telephony) | 开通 Twilio 号码、SMS/MMS，以及 AI 外呼电话。 |

## research

| 技能 | 描述 |
|-------|-------------|
| [**bioinformatics**](/user-guide/skills/optional/research/research-bioinformatics) | 通往 400+ 个基因组学与计算生物学技能的入口。 |
| [**blogwatcher**](/user-guide/skills/optional/research/research-blogwatcher) | 通过 blogwatcher-cli 工具监控博客和 RSS/Atom 订阅源。 |
| [**darwinian-evolver**](/user-guide/skills/optional/research/research-darwinian-evolver) | 用 Imbue 的进化循环演化提示词/正则/SQL/代码。 |
| [**domain-intel**](/user-guide/skills/optional/research/research-domain-intel) | 被动侦察子域名、SSL 证书、WHOIS 和 DNS。 |
| [**drug-discovery**](/user-guide/skills/optional/research/research-drug-discovery) | 药物发现：ChEMBL 搜索、类药性、相互作用。 |
| [**duckduckgo-search**](/user-guide/skills/optional/research/research-duckduckgo-search) | 通过 ddgs 进行免费、无需密钥的网页、新闻和图片搜索。 |
| [**gitnexus-explorer**](/user-guide/skills/optional/research/research-gitnexus-explorer) | 提供交互式代码库知识图谱 Web UI。 |
| [**osint-investigation**](/user-guide/skills/optional/research/research-osint-investigation) | 通过公开记录和制裁数据追踪资金流向。 |
| [**parallel-cli**](/user-guide/skills/optional/research/research-parallel-cli) | 面向 agent 的网页搜索、深度研究与数据增强。 |
| [**pinecone-research**](/user-guide/skills/optional/research/research-pinecone-research) | 基于 Pinecone 的 agent RAG 与长期记忆。 |
| [**qmd**](/user-guide/skills/optional/research/research-qmd) | 对笔记、文档和转录稿进行本地混合搜索。 |
| [**research-paper-writing**](/user-guide/skills/optional/research/research-research-paper-writing) | 为 NeurIPS/ICML/ICLR 撰写 ML 论文：从设计到投稿。 |
| [**rss-feeds**](/user-guide/skills/optional/research/research-rss-feeds) | 读取 RSS、Atom、JSON 订阅源；发现页面背后的订阅源。 |
| [**scrapling**](/user-guide/skills/optional/research/research-scrapling) | 通过隐身浏览和 Cloudflare 绕过抓取网站。 |
| [**searxng-search**](/user-guide/skills/optional/research/research-searxng-search) | 免费、无需密钥的元搜索，聚合 70+ 搜索引擎。 |

## security

| 技能 | 描述 |
|-------|-------------|
| [**1password**](/user-guide/skills/optional/security/security-1password) | 配置 op CLI、登录，并读取或注入密钥。 |
| [**godmode**](/user-guide/skills/optional/security/security-godmode) | LLM 越狱：Parseltongue、GODMODE、ULTRAPLINIAN。 |
| [**oss-forensics**](/user-guide/skills/optional/security/security-oss-forensics) | GitHub 供应链取证：恢复、IOC、报告。 |
| [**sherlock**](/user-guide/skills/optional/security/security-sherlock) | 在 400+ 个平台上查找某个用户名对应的账号。 |
| [**unbroker**](/user-guide/skills/optional/security/security-unbroker) | 自动从数据经纪商网站上删除你的个人信息。 |
| [**web-pentest**](/user-guide/skills/optional/security/security-web-pentest) | 经授权的 Web 渗透测试：侦察、基于证据的漏洞利用、报告。 |

## smart-home

| 技能 | 描述 |
|-------|-------------|
| [**openhue**](/user-guide/skills/optional/smart-home/smart-home-openhue) | 通过 OpenHue CLI 控制飞利浦 Hue 灯光、场景、房间。 |

## social-media

| 技能 | 描述 |
|-------|-------------|
| [**reddit-reading**](/user-guide/skills/optional/social-media/social-media-reddit-reading) | 阅读 Reddit：子版块、搜索、帖子、用户。无需浏览器。 |

## software-development

| 技能 | 描述 |
|-------|-------------|
| [**ast-grep**](/user-guide/skills/optional/software-development/software-development-ast-grep) | 通过 ast-grep 进行感知 AST 的结构化代码搜索与改写。 |
| [**code-wiki**](/user-guide/skills/optional/software-development/software-development-code-wiki) | 为任意代码库生成 wiki 文档 + Mermaid 图表。 |
| [**grill-me**](/user-guide/skills/optional/software-development/software-development-grill-me) | 实施前的对抗式方案质询。 |
| [**rest-graphql-debug**](/user-guide/skills/optional/software-development/software-development-rest-graphql-debug) | 调试 REST/GraphQL API：状态码、鉴权、schema、复现。 |
| [**subagent-driven-development**](/user-guide/skills/optional/software-development/software-development-subagent-driven-development) | 通过 delegate_task 子 agent 执行计划（两阶段评审）。 |

## web-development

| 技能 | 描述 |
|-------|-------------|
| [**cloudflare-temporary-deploy**](/user-guide/skills/optional/web-development/web-development-cloudflare-temporary-deploy) | 通过 wrangler --temporary 无需账号即可上线一个 Worker。 |
| [**har-derived-api-client**](/user-guide/skills/optional/web-development/web-development-har-derived-api-client) | 把网站的 XHR 录制为 HAR，并据此生成 HTTP 客户端。 |
| [**page-agent**](/user-guide/skills/optional/web-development/web-development-page-agent) | 在 Web 应用中嵌入页面内的自然语言 GUI 副驾驶。 |
| [**publish-site**](/user-guide/skills/optional/web-development/web-development-publish-site) | 将站点按版本部署到 GitHub/Cloudflare/Netlify Pages。 |

## yuanbao

| 技能 | 描述 |
|-------|-------------|
| [**yuanbao**](/user-guide/skills/optional/yuanbao/yuanbao-yuanbao) | 元宝（Yuanbao）群组：@mention 用户，查询信息/成员。 |

---

## 贡献可选技能

向仓库添加新的可选技能：

1. 在 `optional-skills/<category>/<skill-name>/` 下创建目录
2. 添加包含标准 frontmatter 的 `SKILL.md`（name、description、version、author）
3. 在 `references/`、`templates/` 或 `scripts/` 子目录中包含所有支撑文件
4. 提交 pull request — 合并后该技能将出现在本目录并获得专属文档页面