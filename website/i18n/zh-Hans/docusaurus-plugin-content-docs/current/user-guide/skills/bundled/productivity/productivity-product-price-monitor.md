---
title: "Product Price Monitor — 监控商品、航班或房源价格；达到目标时发出提醒"
sidebar_label: "Product Price Monitor"
description: "监控商品、航班或房源价格；达到目标时发出提醒"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Product Price Monitor

监控商品、航班或房源价格；达到目标时发出提醒。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/product-price-monitor` |
| 版本 | `0.1.0` |
| 作者 | Ben Barclay (benbarclay), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Prices`, `Availability`, `Shopping`, `Travel`, `Alerts` |
| 相关 skill | [`maps`](/user-guide/skills/bundled/productivity/productivity-maps) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Product Price Monitor

监控一个具体的可购买物品，并在标准化的全包价格或可用性条件满足时发出提醒。明确处理规格变体、税费、附加费用、币种、库存、取消条款以及重复提醒。设置在前台执行一次；周期性检查以 `cronjob` tick 的形式运行（`price-watch` 自动化蓝图会为此搭好框架）。

## 使用时机 {#when-to-use}

- “这台笔记本降到 1,000 美元以下时提醒我。”
- “盯着这些航班，票价低于 500 美元时告诉我。”
- “这家酒店有可退款的房间时告诉我。”
- “追踪门票/房源的可用情况。”
- 某个已有价格监控的 cron tick 触发时（第 4-6 步）。

不适用于：一次性的“这东西现在多少钱”查询（直接使用 `web_search`/`web_extract`）。

## 流程——设置（前台，一次） {#procedure--setup-foreground-once}

### 1. 定义确切的物品 {#1-define-the-exact-item}

记录来源 URL/提供方、可用时的商品/房源 ID、规格变体、数量、地点、日期、旅客/住客、会员/登录假设、成色、卖家以及可接受的替代品。当两个规格变体不可能被混淆时，即告完成。

### 2. 定义提醒条件 {#2-define-the-alert-condition}

指定币种、全包价还是税前价、最高价格、可用性/库存规则、运费、可退款性、舱位/房型/票种、冷却时间以及通知目的地。当合成示例都能得到确定性的提醒决策时，即告完成。

### 3. 建立实时基线，然后再调度 {#3-establish-a-live-baseline-then-schedule}

使用 `web_extract` 或 `browser_navigate` 获取一个有边界的实时结果，并记录获取时间、来源价格、费用/税费、可用性和条款。在一次前台获取成功之前不要调度。将监控约定（物品、条件、基线观测）写入 `~/.hermes/price-watches/<watch-slug>.json` 下的状态文件，然后创建任务：

```
cronjob(action="create",
        schedule="every 6h",
        prompt="Load the product-price-monitor skill and run the tick for the watch contract at ~/.hermes/price-watches/<watch-slug>.json.",
        deliver=<user's destination>)
```

选择一个遵守速率限制和网站条款的频率。当基线与确切的物品约定相符且任务已存在时，即告完成。

## 流程——Tick（每次调度运行） {#procedure--tick-each-scheduled-run}

### 4. 获取并标准化 {#4-fetch-and-normalize}

重新获取来源。只使用带时间戳的汇率进行币种换算，并保留来源币种。分别列出基础价格、强制费用、运费/税费、总价以及可用性。排除易变的页面元数据。获取失败意味着状态未知：报告或跳过，但永远不要用错误页面覆盖上一次的有效观测。当观测结果可与基线比较，或被明确标记为失败时，即告完成。

### 5. 比较并抑制重复 {#5-compare-and-suppress-duplicates}

按要求在进入阈值、出现符合条件的可用性、价格显著下降或恢复时发出提醒。将上一次有效观测和上一次提醒的指纹存储在状态文件中。重放同一报价时不得发送第二次提醒；遵守冷却时间。当提醒决策相对于已存储的状态是确定性的时，即告完成。

### 6. 发送提醒或保持沉默 {#6-deliver-or-stay-silent}

当条件满足时，提醒应包括：确切的物品/规格变体、观测到的全包价格和来源币种、可用性/条款、阈值、获取时间戳、来源链接以及重要的不确定因素。永远不要声称库存已被预留。当没有任何条件满足时，保持沉默——除非用户要求定期发送“一切正常”，否则不要发出“仍在监控”之类的噪音。当状态文件反映了本次运行时，即告完成。

## 常见陷阱 {#pitfalls}

- 拿基础票价与全包价阈值做比较。
- 针对错误的尺码、卖家、舱位、日期或房间条款发出提醒。
- 用错误页面覆盖上一次已知的有效值。
- 轮询过于激进，以致触发封锁或违反网站条款。
- 在一次前台获取成功之前就进行调度。

## 验证 {#verification}

- [ ] 监控约定将物品固定下来，使两个规格变体不可能被混淆。
- [ ] 在创建任何任务之前，有一次前台获取已成功。
- [ ] 提醒决策可以从状态文件确定性地重放；重复提醒被抑制。
- [ ] 失败的获取从未替换上一次已知的有效状态。
- [ ] 提醒包含全包价格、来源币种、时间戳和来源链接。
