---
sidebar_position: 5
title: "内置技能目录"
description: "随 Hermes Agent 附带的内置技能目录"
---

# 内置技能目录

Hermes 附带一个大型内置技能库，安装时会复制到 `~/.hermes/skills/`。下方每个技能均链接至专属页面，包含完整定义、配置和用法说明。

Hermes 在执行 `hermes update` 时也会同步内置技能，但同步清单会尊重本地删除和用户编辑。如果此处列出的某个技能在你的 profile 的 `~/.hermes/skills/` 目录树中缺失，它仍随 Hermes 一同发布；可通过 `hermes skills reset <name> --restore` 恢复。

如果某个技能未出现在此列表中但存在于仓库中，目录由 `website/scripts/generate-skill-docs.py` 重新生成。

## apple

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`apple-notes`](/user-guide/skills/bundled/apple/apple-apple-notes) | 通过 memo CLI 管理 Apple Notes：创建、搜索、编辑。 | `apple/apple-notes` |
| [`apple-reminders`](/user-guide/skills/bundled/apple/apple-apple-reminders) | 通过 remindctl 操作 Apple Reminders：添加、列出、完成。 | `apple/apple-reminders` |
| [`findmy`](/user-guide/skills/bundled/apple/apple-findmy) | 在 macOS 上通过 FindMy.app 追踪 Apple 设备/AirTag。 | `apple/findmy` |
| [`imessage`](/user-guide/skills/bundled/apple/apple-imessage) | 在 macOS 上通过 imsg CLI 发送和接收 iMessage/SMS。 | `apple/imessage` |

## autonomous-ai-agents

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`claude-code`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-claude-code) | 将编码任务委托给 Claude Code CLI（功能开发、PR）。 | `autonomous-ai-agents/claude-code` |
| [`codex`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex) | 将编码任务委托给 OpenAI Codex CLI（功能开发、PR）。 | `autonomous-ai-agents/codex` |
| [`computer-use`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-computer-use) | 以后台优先的方式驱动桌面；出现信号时再升级处理。 | `autonomous-ai-agents/computer-use` |
| [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) | 使用、配置、定制主题、扩展和编排 Hermes Agent。 | `autonomous-ai-agents/hermes-agent` |
| [`opencode`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-opencode) | 将编码任务委托给 OpenCode CLI（功能开发、PR 审查）。 | `autonomous-ai-agents/opencode` |

## creative

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`architecture-diagram`](/user-guide/skills/bundled/creative/creative-architecture-diagram) | 以 HTML 形式生成深色主题的 SVG 架构/云/基础设施图。 | `creative/architecture-diagram` |
| [`ascii-video`](/user-guide/skills/bundled/creative/creative-ascii-video) | ASCII 视频：将视频/音频转换为彩色 ASCII MP4/GIF。 | `creative/ascii-video` |
| [`baoyu-infographic`](/user-guide/skills/bundled/creative/creative-baoyu-infographic) | 信息图：21 种布局 × 21 种风格（信息图, 可视化）。 | `creative/baoyu-infographic` |
| [`claude-design`](/user-guide/skills/bundled/creative/creative-claude-design) | 设计一次性 HTML 制品（落地页、幻灯片、原型）。 | `creative/claude-design` |
| [`design-md`](/user-guide/skills/bundled/creative/creative-design-md) | 编写/验证/导出 Google 的 DESIGN.md token 规范文件。 | `creative/design-md` |
| [`humanizer`](/user-guide/skills/bundled/creative/creative-humanizer) | 人性化文本：去除 AI 腔，加入真实语气。 | `creative/humanizer` |
| [`manim-video`](/user-guide/skills/bundled/creative/creative-manim-video) | Manim CE 动画：3Blue1Brown 风格数学/算法视频。 | `creative/manim-video` |
| [`p5js`](/user-guide/skills/bundled/creative/creative-p5js) | p5.js 草图：生成艺术、着色器、交互、3D。 | `creative/p5js` |
| [`popular-web-designs`](/user-guide/skills/bundled/creative/creative-popular-web-designs) | 54 种真实设计系统（Stripe、Linear、Vercel）的 HTML/CSS 实现。 | `creative/popular-web-designs` |
| [`songwriting-and-ai-music`](/user-guide/skills/bundled/creative/creative-songwriting-and-ai-music) | 歌曲创作技巧与 Suno AI 音乐 prompt（提示词）。 | `creative/songwriting-and-ai-music` |

## devops

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`sdlc-review`](/user-guide/skills/bundled/devops/devops-sdlc-review) | 审查 Kanban 交接并路由已验证的结果。 | `devops/sdlc-review` |

## email

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`email-inbox-triage`](/user-guide/skills/bundled/email/email-email-inbox-triage) | 分拣收件箱：为邮件线程排定优先级，安全地起草回复。 | `email/email-inbox-triage` |
| [`himalaya`](/user-guide/skills/bundled/email/email-himalaya) | Himalaya CLI：在终端中收发 IMAP/SMTP 邮件。 | `email/himalaya` |

## media

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`gif-search`](/user-guide/skills/bundled/media/media-gif-search) | 通过 curl + jq 从 Tenor 搜索/下载 GIF。 | `media/gif-search` |
| [`songsee`](/user-guide/skills/bundled/media/media-songsee) | 通过 CLI 生成音频频谱图/特征（mel、chroma、MFCC）。 | `media/songsee` |
| [`youtube-content`](/user-guide/skills/bundled/media/media-youtube-content) | 将 YouTube 字幕转换为摘要、推文串、博客文章。 | `media/youtube-content` |

## note-taking

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`obsidian`](/user-guide/skills/bundled/note-taking/note-taking-obsidian) | 在 Obsidian 知识库中读取、搜索、创建和编辑笔记。 | `note-taking/obsidian` |

## productivity

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`airtable`](/user-guide/skills/bundled/productivity/productivity-airtable) | 通过 curl 调用 Airtable REST API：记录增删改查、过滤、upsert。 | `productivity/airtable` |
| [`box`](/user-guide/skills/bundled/productivity/productivity-box) | Box 管理云端文件、共享、搜索和元数据。 | `productivity/box` |
| [`document-to-action-items`](/user-guide/skills/bundled/productivity/productivity-document-to-action-items) | 从文档中提取带引用的义务、截止日期和任务。 | `productivity/document-to-action-items` |
| [`docx`](/user-guide/skills/bundled/productivity/productivity-docx) | 创建、读取、编辑、套用模板和审阅 Word .docx 文件。 | `productivity/docx` |
| [`google-workspace`](/user-guide/skills/bundled/productivity/productivity-google-workspace) | 通过 gws CLI 或 Python 操作 Gmail、Calendar、Drive、Docs、Sheets。 | `productivity/google-workspace` |
| [`maps`](/user-guide/skills/bundled/productivity/productivity-maps) | 通过 OpenStreetMap/OSRM 进行地理编码、POI 查询、路线规划、时区查询。 | `productivity/maps` |
| [`meeting-action-items`](/user-guide/skills/bundled/productivity/productivity-meeting-action-items) | 将会议笔记转化为带引用的决策、负责人和工单。 | `productivity/meeting-action-items` |
| [`notion`](/user-guide/skills/bundled/productivity/productivity-notion) | Notion API + ntn CLI：页面、数据库、Markdown、Workers。 | `productivity/notion` |
| [`pdf`](/user-guide/skills/bundled/productivity/productivity-pdf) | PDF 文件：创建、读取、合并、填写、OCR、编辑文本。 | `productivity/pdf` |
| [`powerpoint`](/user-guide/skills/bundled/productivity/productivity-powerpoint) | 使用 python-pptx 创建、读取、编辑 .pptx 演示文稿。 | `productivity/powerpoint` |
| [`product-price-monitor`](/user-guide/skills/bundled/productivity/productivity-product-price-monitor) | 监控商品、航班或挂牌价格；达到目标价时发出提醒。 | `productivity/product-price-monitor` |
| [`teams-meeting-pipeline`](/user-guide/skills/bundled/productivity/productivity-teams-meeting-pipeline) | Teams 会议摘要、任务重放、Graph 订阅。 | `productivity/teams-meeting-pipeline` |
| [`weekly-review-planning`](/user-guide/skills/bundled/productivity/productivity-weekly-review-planning) | 每周重置：梳理承诺事项、停滞的工作和下周计划。 | `productivity/weekly-review-planning` |
| [`xlsx`](/user-guide/skills/bundled/productivity/productivity-xlsx) | 创建、读取、编辑 Excel .xlsx 工作簿和 CSV 文件。 | `productivity/xlsx` |

## research

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`arxiv`](/user-guide/skills/bundled/research/research-arxiv) | 按关键词、作者、分类或 ID 搜索 arXiv 论文。 | `research/arxiv` |
| [`competitor-news-monitor`](/user-guide/skills/bundled/research/research-competitor-news-monitor) | 关注指定公司的重大新闻；生成带引用的摘要。 | `research/competitor-news-monitor` |
| [`grounded-citations`](/user-guide/skills/bundled/research/research-grounded-citations) | 让回答和文档以带引用、可核实的来源为依据。 | `research/grounded-citations` |
| [`llm-wiki`](/user-guide/skills/bundled/research/research-llm-wiki) | Karpathy 的 LLM Wiki：构建/查询互联 Markdown 知识库。 | `research/llm-wiki` |

## social-media

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`xurl`](/user-guide/skills/bundled/social-media/social-media-xurl) | 通过 xurl CLI 操作 X/Twitter：原始帖子搜索、发帖、私信、媒体。 | `social-media/xurl` |

## software-development

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`codebase-inspection`](/user-guide/skills/bundled/software-development/software-development-codebase-inspection) | 使用 pygount 检查代码库：代码行数、语言、占比。 | `software-development/codebase-inspection` |
| [`dogfood`](/user-guide/skills/bundled/software-development/software-development-dogfood) | Web 应用探索性 QA：发现 bug、收集证据、生成报告。 | `software-development/dogfood` |
| [`github`](/user-guide/skills/bundled/software-development/software-development-github) | 通过 gh CLI 操作 GitHub：PR、issue、审查、仓库、认证。 | `software-development/github` |
| [`hermes-agent-skill-authoring`](/user-guide/skills/bundled/software-development/software-development-hermes-agent-skill-authoring) | 编写仓库内 SKILL.md 文件：frontmatter 与结构。 | `software-development/hermes-agent-skill-authoring` |
| [`inspecting-hermes-desktop-dom`](/user-guide/skills/bundled/software-development/software-development-inspecting-hermes-desktop-dom) | 通过 CDP 读取运行中 Hermes 桌面应用的 DOM/CSS。 | `software-development/inspecting-hermes-desktop-dom` |
| [`node-inspect-debugger`](/user-guide/skills/bundled/software-development/software-development-node-inspect-debugger) | 通过 --inspect + Chrome DevTools Protocol CLI 调试 Node.js。 | `software-development/node-inspect-debugger` |
| [`python-debugpy`](/user-guide/skills/bundled/software-development/software-development-python-debugpy) | 调试 Python：pdb REPL + debugpy 远程调试（DAP）。 | `software-development/python-debugpy` |
| [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review) | 提交前审查：安全扫描、质量门控、自动修复。 | `software-development/requesting-code-review` |
| [`simplify-code`](/user-guide/skills/bundled/software-development/software-development-simplify-code) | 由 4 个 agent 并行清理近期的代码改动。 | `software-development/simplify-code` |
| [`spike`](/user-guide/skills/bundled/software-development/software-development-spike) | 一次性实验，在正式构建前验证想法。 | `software-development/spike` |
| [`systematic-debugging`](/user-guide/skills/bundled/software-development/software-development-systematic-debugging) | 四阶段根因调试：先理解 bug，再修复。 | `software-development/systematic-debugging` |
| [`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development) | TDD：强制执行红-绿-重构流程，先写测试再写代码。 | `software-development/test-driven-development` |

## web

| 技能 | 描述 | 路径 |
|-------|-------------|------|
| [`blocked-page-recovery`](/user-guide/skills/bundled/web/web-blocked-page-recovery) | 在抓取失败时使用：403/429、付费墙、WAF、机器人拦截。 | `web/blocked-page-recovery` |
