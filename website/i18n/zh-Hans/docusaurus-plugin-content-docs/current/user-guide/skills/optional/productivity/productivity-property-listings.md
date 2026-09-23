---
title: "Property Listings — 以桌面卡片形式展示房产和租赁房源"
sidebar_label: "Property Listings"
description: "以桌面卡片形式展示房产和租赁房源"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Property Listings

以桌面卡片形式展示房产和租赁房源。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/productivity/property-listings` 安装 |
| 路径 | `optional-skills/productivity/property-listings` |
| 版本 | `0.1.0` |
| 作者 | Teknium (teknium1), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `property`, `rental`, `real-estate`, `listings`, `desktop`, `cards` |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Property Listings Skill {#property-listings-skill}

在 Hermes 桌面端的对话记录中，将调研过的房产以可浏览的卡片形式展示出来。
这是一个展示配方，而不是房源搜索服务或投资估值工具。

## 使用时机 {#when-to-use}

- 展示房产或租赁搜索结果、比较候选清单，或对房产重新排序。
- 跟进一个已经展示过的房产时：继续使用卡片，使候选清单保持可比性。
- 在桌面应用之外，改用带来源链接的普通 Markdown；其他客户端不一定能渲染 listing 代码块。

## 前提条件 {#prerequisites}

- 一个 Hermes 桌面端对话，用于显示原生卡片；后端可以是本地的，也可以是远程的。
- 由用户提供，或通过本会话中可用的 `web_search`、`web_extract` 或浏览器工具核实过的房产详情。
- 卡片格式化不需要任何额外的 API 密钥或依赖。

## 如何运行 {#how-to-run}

通过 Skills 目录安装这个可选 skill，或者使用 `terminal`：

```text
hermes skills install official/productivity/property-listings
```

展示房源时，用 `skill_view(name="property-listings")` 加载它。
安装不会追溯更新正在进行的对话的 skill 索引；请开启一个新对话以进行自动发现，或者现在就显式加载已安装的 skill。

## 速查 {#quick-reference}

输出一个语言为 `listing`、内容为合法 JSON 的围栏代码块。
使用单个对象、对象数组，或者用 `{ "listings": [...] }` 进行比较。

| 字段 | 形式与含义 |
|---|---|
| `address` | 必填、非空的街道地址或房产标题。 |
| `price` | 格式化的字符串，包含币种以及（如适用）租期。 |
| `beds`, `baths` | 正数计数；未知的值省略。 |
| `size` | 格式化的面积，包含单位。 |
| `note` | 这处房产为什么值得一看。 |
| `facts` | 由简短的、已核实的规格或配套设施组成的数组。 |
| `catches` | 由看房前需要核实的风险或问题组成的数组。 |
| `images` | 按房源顺序排列的直接 HTTPS 照片 URL；第一张作为主图。 |
| `links` | 由 `{ "label": "Source", "url": "https://..." }` 详情页链接组成的数组，而不是搜索结果 URL。 |

## 流程 {#procedure}

1. 收集地址、价格、规格、照片和规范的详情页 URL。区分已核实的事实和未知信息；不要编造价格、配套设施或照片 URL。
2. 将各门户网站上同一房产的镜像去重，合并为一张卡片，同时保留有用的来源链接。把来源日期和可用性方面的注意事项放在周围的正文中。
3. 为展示的每一处房产输出 `listing` 代码块，包括后续跟进和重新排序。保持事实简短，并把尚未解决的顾虑放进 `catches`。
4. 发送之前检查 JSON。下面这个虚构的格式示例展示了所有字段；请用已核实的房源数据替换其中的值和示例 URL：

```listing
{
  "address": "12 Example Lane",
  "price": "$2,400/mo",
  "beds": 3,
  "baths": 2.5,
  "size": "1,600 sqft",
  "note": "Fits the requested space and budget.",
  "facts": ["12-month lease", "Covered parking"],
  "catches": ["Verify pet policy and total move-in fees"],
  "images": ["https://example.com/property/front.jpg", "https://example.com/property/kitchen.jpg"],
  "links": [{"label": "Listing details", "url": "https://example.com/property/12"}]
}
```

## 常见陷阱 {#pitfalls}

- 卡片是根据收集到的数据编写的，而不是从房源 URL 或嵌入的门户页面抓取的。
- 一张信息稀疏的卡片只需要地址。省略未知的字段，而不是用猜测去填充。
- 使用直接的远程图片 URL，而不是本地路径、data URL 或搜索结果页面。
  过期或被屏蔽的图片会从图库中消失；文本和链接仍然有用。
- 每个代码块最多包含 24 处房产，每处房产最多 40 张图片，facts、catches 和 links 最多各 12 项。文本字段会被渲染器截断为 400 个字符。
- 格式错误的 JSON 或缺少身份信息的卡片会退回为普通代码块。
  一张有效的卡片并不能证明其背后的房源是最新的或准确的。

## 验证 {#verification}

- 每一处展示的房产都有地址和一个已核实的来源链接；未知信息都明确标出。
- 桌面端将地址、价格、规格、facts、catches 和 links 显示为原生卡片。
- 照片构成一个图库；选择某张照片会打开灯箱。三张或更多照片会使用“主图 + 辅助图”的拼贴布局；更多的照片仍可在其中浏览。
- 如果卡片无法渲染，请检查代码块的语言和 JSON，然后保留一个包含相同事实和链接的、可读的 Markdown 备选版本。
