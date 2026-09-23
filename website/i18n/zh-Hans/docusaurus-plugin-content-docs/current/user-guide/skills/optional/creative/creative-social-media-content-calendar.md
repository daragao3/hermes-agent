---
title: "Social Media Content Calendar —— 规划多平台社交媒体活动：从简报到发布"
sidebar_label: "Social Media Content Calendar"
description: "规划多平台社交媒体活动：从简报到发布"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Social Media Content Calendar

规划多平台社交媒体活动：从简报到发布。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/creative/social-media-content-calendar` 安装 |
| 路径 | `optional-skills/creative/social-media-content-calendar` |
| 版本 | `0.1.0` |
| 作者 | Ben Barclay (benbarclay)、Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Social-Media`, `Content-Calendar`, `Campaigns`, `Publishing` |
| 相关 skill | [`xurl`](/user-guide/skills/bundled/social-media/social-media-xurl)、[`humanizer`](/user-guide/skills/bundled/creative/creative-humanizer) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发该 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Social Media Content Calendar

在选定的社交平台上规划一份具体的内容日历。本 skill 负责活动结构、帖子简报、渠道适配、审批以及发布验证；`xurl` 等平台 skill 负责 API 命令。对于没有连接器的平台，经验证的交接止步于交给用户排期工具的已批准草稿——要如实说明，而不是声称已经发布。

## 使用时机 {#when-to-use}

- "制定下个月的社交媒体日历。"
- "把这次发布活动改写成适用于 X、LinkedIn、Instagram 和 TikTok 的帖子。"
- "起草并排期一场营销活动。"
- "把这些文章/视频改编成社交媒体内容。"

以下情况不要使用：单条一次性帖子（直接使用平台 skill）。

## 操作步骤 {#procedure}

### 1. 明确活动约束 {#1-define-campaign-constraints}

记录目标、受众、优惠/信息、平台、日期范围、发布节奏、语气、必须/禁止的表述、链接、追踪约定、本地化，以及审批/发布权限。当每条拟议帖子都有明确的业务目的时，此步完成。

### 2. 盘点素材 {#2-inventory-source-material}

使用 `read_file` 和 `web_extract` 收集经过核实的产品事实、发布信息、文章、媒体、已获授权的用户评价、品牌资产和关键日期。标注每项表述的负责人和有效期。当缺乏依据的表述和缺失的素材都一目了然时，此步完成。

### 3. 构建主题与日历档期 {#3-build-themes-and-calendar-slots}

创建均衡的内容组合，例如教育、证明、产品、社区、活动、幕后花絮和互动话题。兼顾各平台的发布节奏和活动里程碑。当日期、平台、主题和目标构成一份连贯的日历、而不是重复的跨平台转发时，此步完成。

### 4. 编写针对各平台的简报 {#4-write-platform-specific-briefs}

为每条帖子指定开头钩子、核心信息、格式、文案长度、CTA、链接、素材尺寸/内容、无障碍文本、标签/提及以及成功指标。在不同平台之间做适配，而不是复制粘贴。当创作者无需隐含上下文即可产出素材时，此步完成。

### 5. 起草文案与素材 {#5-draft-copy-and-assets}

加载 `humanizer` 以把握语气；需要素材时用 `image_generate` 工具生成视觉内容。在遵循各平台惯例的同时，保持事实表述和统一的活动识别。当每个日历档期都有草稿文案和素材状态时，此步完成。

### 6. 进行编辑与风险审查 {#6-run-editorial-and-risk-review}

检查事实准确性、语气、重复、版权/授权、无障碍、披露声明、链接目标、日期相关性以及危机敏感性。标记为 `draft`、`needs review` 或 `approved`；不要直接从草稿发布。当每条帖子都有处置状态和负责人时，此步完成。

### 7. 排期或交接 {#7-schedule-or-hand-off}

呈现待批准批次。只使用可用的平台 skill（X 用 `xurl`）发布/排期已批准的帖子；对于没有连接器的平台，将已批准的内容包（文案、素材、时间）交付给用户的排期工具，并将这些档期标记为已交接，而不是已发布。对于实际发布的内容，回读排期时间、账号、内容预览以及服务商返回的帖子/任务 ID。当日历按档期反映出经过验证的发布或交接状态时，此步完成。

## 常见陷阱 {#pitfalls}

- 每个平台都用完全相同的文案。
- 用低价值的重复帖子填充发布节奏。
- 发布未经核实的数据、用户评价或关于未来的承诺。
- 把素材生成完成与已排期发布混为一谈。
- 对交接止步于草稿的平台声称"已排期"。

## 验证 {#verification}

- [ ] 每条帖子都可追溯到一个活动目标和经过核实的表述清单。
- [ ] 没有任何帖子是从 `draft` 或 `needs review` 状态发布的。
- [ ] 已发布的档期都有服务商确认的 ID；已交接的档期都已如实标记。
- [ ] 在任何发布之前都已检查版权、授权和披露声明。
