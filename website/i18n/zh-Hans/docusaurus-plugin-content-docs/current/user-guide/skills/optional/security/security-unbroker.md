---
title: "Unbroker — Autonomously remove your info from data-broker sites"
sidebar_label: "Unbroker"
description: "自主地从数据经纪商网站上移除你的个人信息"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Unbroker

自主地从数据经纪商网站上移除你的个人信息。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/security/unbroker` 安装 |
| 路径 | `optional-skills/security/unbroker` |
| 版本 | `1.0.0` |
| 作者 | SHL0MS (github.com/SHL0MS) |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `privacy`, `data-broker`, `opt-out`, `ccpa`, `gdpr`, `security`, `doxxing` |
| 相关 skill | [`google-workspace`](/user-guide/skills/bundled/productivity/productivity-google-workspace), [`agentmail`](/user-guide/skills/optional/email/email-agentmail), [`himalaya`](/user-guide/skills/bundled/email/email-himalaya), [`scrapling`](/user-guide/skills/optional/research/research-scrapling), [`osint-investigation`](/user-guide/skills/optional/research/research-osint-investigation) |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# unbroker

找出某个人的个人信息（姓名、地址、电话、邮箱、亲属）在数据经纪商和
人肉搜索站点上的暴露位置，然后把它们移除——尽可能自动完成，只有当站点要求
CAPTCHA、政府证件、电话或传真时，才引导人工介入。可独立管理多个
对象。它**不会**破解反机器人系统，**不会**在没有记录同意的情况下对任何人采取行动，
也**不会**移除公共记录（选民/房产/法院）或本人可控的账号。

Python CLI（`scripts/pdd.py`）掌管确定性状态——配置、档案 + 同意记录、
经纪商数据库、分级规划、账本、草稿、报告，**以及邮件发送（SMTP）、验证链接
轮询（IMAP）和自主动作队列（`next`）**。你（agent）负责用原生工具做扫描
和填表：用 `web_extract` 和 `browser_navigate` 做搜索与网页表单，用
`cronjob` 做周期性重扫。

## 自主性约定

此 skill 的设计目标是**免人工照看**地运行。在接案（+ 记录同意）之后，只存在两个
合理的人工接触点：(1) 接案对话本身，(2) 运行结束时的**一次**汇总人工任务
摘要（`$PDD tasks`）。在这两者之间：

- **绝不要让操作者去选择配置。** `$PDD setup --auto` 会检测能力，
  自行挑选最自主的有效配置。
- 当 `autonomy=full`（默认）时，**绝不要在每次提交前暂停**：接案时
  记录的同意就是 T0-T2 退出请求的长期授权。（`autonomy=assisted` 会恢复
  逐次提交确认，供谨慎的操作者使用——请遵守 `next` 输出中的 `confirm_first` 标记。）
- **绝不要为纯人工的工作中断整个运行。** 记录下来（`record ... human_task_queued
  --reason "..."`）并继续；这些会在最终摘要中一次性呈现。
- **整个运行以 `$PDD next <subject>` 的循环来驱动**——它会返回此刻应当执行的
  确切有序动作（扫描、轮询验证、复查、父站优先退出、把被阻断的重新入队），
  外加人工摘要。执行每一个动作，记录结果，再次运行 `next`，如此往复直到
  `done_for_now`。然后呈现摘要、报告，并安排 cron。

自主性永远无法凌驾的硬性界限：没有记录同意就不行动；不披露
超出 `disclosure_fields` 的内容；不绕过 CAPTCHA/反机器人；并且只有在
复查确认之后才能标记 `confirmed_removed`。

## 使用时机

- "把我（或我家人）的数据从数据经纪商 / 人肉搜索站点上移除。"
- "帮我退出"、"从 Spokeo/Whitepages 等站点删除我"、"人肉之后做清理"。
- "设置周期性隐私监控"（经纪商会重新收录人员信息）。
- 检查还有哪些经纪商仍在暴露某人，以及原因是什么。

## 前置条件

- `python3`（仅需标准库；核心引擎不需要额外依赖包）。
- **可选增强项**（没有它们此 skill 也能零配置工作；`setup --auto` 会启用它检测到的
  每一项，并从 shell 环境**以及 `$HERMES_HOME/.env`** 读取凭据，这样 Hermes
  已经为自身工具加载的密钥无需重新导出即可被使用——每一项都能把一类人工任务
  转化为 agent 动作）：
  - **云浏览器（推荐的默认项）：`BROWSERBASE_API_KEY`。** 只要该密钥存在，
    `setup --auto` 就会选用它，而且它本就是预期的基线：一个具备真实住宅 IP 的云
    浏览器**能把软性/托管型 CAPTCHA（Cloudflare Turnstile、hCaptcha/reCAPTCHA
    复选框）当作常规操作直接通过**，因此这些经纪商仍可保持自动化（T1），而不会
    变成人工任务。这**不是** CAPTCHA"破解"——没有打码服务，也没有指纹伪造；
    只有浏览器确实无法通过的交互式/行为型（"硬"）挑战才会退回为人工任务。没有该密钥时，
    会使用普通的 agent 浏览器，软性 CAPTCHA 的经纪商会降级为 T2（人工）。
  - 邮件自动化，有两种是否需要凭据的选项：
    - **浏览器模式（无需密码）：`setup --email-mode browser`。** agent 通过操作者
      **已登录的网页邮箱**、使用 `browser_*` 工具发送退出/CCPA
      邮件并打开验证链接。不存储任何内容。这要求把 Hermes 指向操作者自己
      已登录的浏览器，**而不是**云浏览器：无头云浏览器（Browserbase）既没有
      网页邮箱会话，其本身在网页邮箱以及与会话绑定的经纪商关卡上（例如
      PeopleConnect 的引导模式）也会被 Cloudflare/DataDome 拦截。请通过 CDP 驱动
      操作者真实的 Chrome——启动
      `chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.hermes/chrome-debug"`
      （使用一个专用的调试 profile，并在其中登录一次网页邮箱，不要用 Default profile），
      然后把浏览器工具连接到 `127.0.0.1:9222`。**`$PDD cdp` 会替你完成启动**
      （它会找到 Chrome/Chromium/Brave/Edge，以专用 profile 分离启动，并打印 CDP 端点；
      `--check` 用于测试，`--print` 打印命令）。参见 `references/methods.md` ->
      "Browser backends: scan vs execute"。
      如果收件箱不可达，会退回为生成邮件草稿。
    - **SMTP/IMAP（存储凭据）：`EMAIL_ADDRESS` + `EMAIL_PASSWORD`**（非主流服务商还需
      `EMAIL_SMTP_HOST` / `EMAIL_IMAP_HOST`；gmail/outlook/yahoo/icloud/fastmail 可自动推断）。
      CLI 通过 `send-email` 发送，并通过 `poll-verification` 读取验证链接。`agentmail`
      skill（按经纪商分配别名）同样可用。
  - Google Sheets 跟踪表：`google-workspace` skill。
  - 用于隐身/受 Cloudflare 保护页面的 `scrapling` skill。

## 如何运行

一切都通过 `terminal` 工具运行。在此 skill 目录下：

```bash
PDD="python3 scripts/pdd.py"
```

引擎把数据存放在 `$PDD_DATA_DIR`（默认 `$HERMES_HOME/unbroker`），以
`0600` 写入。请用 `terminal` 运行，**不要**用 `execute_code`（那个沙箱会清理环境变量并
对输出做脱敏，会导致读取档案失败）。

## 快速参考

| 命令 | 用途 |
|---|---|
| `$PDD setup --auto` | **自主设置**：检测能力，挑选最自主的有效配置（不提问） |
| `$PDD doctor` | 就绪检查：配置、经纪商数量，以及哪些增强项已启用/可用 |
| `$PDD cdp [--check] [--print] [--port N]` | 通过 CDP 启动/检测操作者的 Chrome，用于第 2 阶段的浏览器 + 网页邮箱（专用调试 profile；这是发送网页邮件和通过会话绑定关卡的可靠方式） |
| `$PDD intake --full-name "..." [--alias ...] [--email ... --phone ...] [--city --state] [--prior-location "City,ST"] --consent` | 创建一个已同意的对象；采集别名 + 多个邮箱/电话 + 历史居住地；打印 `subject_id` |
| `$PDD next <subject>` | **自主循环的驱动器**：此刻的有序 agent 动作 + 人工摘要 + `next_wake_at` |
| `$PDD brokers [--priority crucial]` | 列出人肉搜索经纪商数据库（精选 + 实时） |
| `$PDD refresh-brokers` | 拉取最新的 BADBOOL 人肉搜索清单**以及加州数据经纪商登记册**（缓存过期时 `next` 会自动重新入队此动作） |
| `$PDD registry [--search NAME]` | 州登记册覆盖情况（CA 已导入约 545 家；VT/OR/TX 门户已列出）；属于 DROP/邮件通道，不做扫描 |
| `$PDD drop <subject> [--filed]` | **一击式法律杠杆**：一份 CA DROP 请求即可从**所有**已登记经纪商处删除；`--filed` 记录该操作 |
| `$PDD plan <subject> [--priority crucial]` | 每个经纪商的分级 + 方法 + `search_vectors` + 需披露的确切字段 |
| `$PDD plan <subject> --batch` | **归约视图**：叠加账本状态，按下一步动作对经纪商分组（unscanned/found/indirect/blocked/in_progress/done），折叠归属集群，**把 `found` 分组按集群父站优先排序并生成定制化的 `parent_playbook`**，打印 `next_actions` |
| `$PDD fanout <subject> [--priority crucial] [--size 5]` | 把经纪商分批交给并行的 `delegate_task` 子 agent（大规模运行时自动启用；每批 5 个——8 个以上会超时） |
| `$PDD record <subject> <broker> <state> [--found true] [--evidence JSON] [--disclosed F --channel C] [--reason "..."]` | 更新账本（带校验的状态机）；**自动打上 `next_recheck_at` 时间戳** |
| `$PDD show <subject> <broker>` | 读回某个案例已记录的状态 + 证据 + 披露日志（这样父 agent 无需重新推导列表 URL 即可复核子 agent 的 `found`） |
| `$PDD send-email <subject> <broker> --listing <url> [--kind ccpa_indirect ...]` | 渲染并记录该请求（收件人被锁定为该经纪商自己的地址）。**browser** 模式返回一个 `compose` 载荷，由网页邮箱发送（无需密码）；**programmatic** 模式则通过 SMTP 发送 |
| `$PDD verify-link <subject> <broker> --text '<body>'` | **浏览器模式**：从你读到的网页邮箱正文中提取经纪商的验证链接（带反钓鱼评分） |
| `$PDD poll-verification <subject> [--broker <id>]` | **programmatic 模式**：通过 IMAP 轮询验证链接（带反钓鱼评分）；自动推进 `submitted → verification_pending` |
| `$PDD render-email <subject> <broker> --listing <url>` | 仅生成草稿（未配置邮件模式时的兜底方案） |
| `$PDD due <subject>` | 已到复查窗口的案例（cron 重扫队列） |
| `$PDD tasks <subject>` | **一次性**汇总的人工任务摘要（在运行**结束**时呈现） |
| `$PDD status <subject>` | Markdown 状态报告 |
| `$PDD report <subject> --sheets` | 用于 Google Sheets 跟踪表的数据行 |

## 批量操作（两阶段：先全量爬取，再删除）

只要涉及的经纪商超过两三个，就应当以 **map → reduce → act** 的方式运行，而不是逐个经纪商处理：

- **第 1 阶段 - 发现（只读、可并行、幂等）。** 先爬取*每一个*经纪商，并为每个记录一个
  结论（`found` / `not_found` / `indirect_exposure` / `blocked`）。扫描没有副作用，
  因此可以安全地并行与重试。在行动*之前*拿到完整的暴露地图，正是下文集群去重
  与优先级排序得以成立的前提。**默认做法：由父 agent 直接驱动 `web_extract`
  探测**——大多数人肉搜索站点会把姓名/电话/地址结果渲染为静态 HTML，`web_extract`
  几秒就能读到。只有少数纯 JS 站点才升级到 `browser_*`，而只有真正需要大量*推理*的工作
  （大规模同名者/亲属消歧）才升级到 `delegate_task` 子 agent。**不要把一大串经纪商
  交给带浏览器工具集的子 agent 去爬**——实际使用中这反复超时（600 秒，每个约 5-6 个
  经纪商，没有产出摘要），因为浏览器导航很重；侥幸留存下来的账本写入，其成本是父 agent
  用 `web_extract` 的 10 倍。被 `blocked` 的站点（DataDome/Cloudflare/`antibot`）同样
  *不是*子 agent 的活儿：记录为 `blocked`，重新入队等待隐身/云浏览器（Browserbase）那一轮。
  子 agent 的汇报属于自述——父 agent 要重新抓取关键 URL 来确认 `found` 之后才可采信
  （这把刀是双刃的：它也曾发现一条被父 agent 误判为误报的真实记录）。
- **归约 - `$PDD plan <subject> --batch`。** 把爬取结果收敛成面向阶段的计划：按
  下一步动作分组，**折叠归属集群**（一次父站移除若能连带清除子站，就算作**一个**动作而不是 N 个——
  例如一次 Intelius/PeopleConnect 抑制即可覆盖 Truthfinder/Instant Checkmate/US Search 等），
  并打印 `next_actions`。只要还有未扫描项，`phase` 就是 `discover`，否则为 `delete`。
- **第 2 阶段 - 删除（串行、不可逆）。** 按归约后的分组**父站优先**推进：
  `plan --batch` 会把 `found` 分组按集群父站优先（子站最多者最先）排序，并生成
  `parent_playbook`，其中包含针对每个父站定制的有序步骤——请遵循那个顺序和那些步骤
  （完整配方见 `references/methods.md` → "Ownership clusters - DO PARENTS FIRST"）。先做
  集群父站（跳过已被覆盖的子站），**在每个父站确认之后重新扫描它的子站**
  （它们通常会随之消失），然后处理独立的条目；把 `indirect_exposure` 案例作为
  CCPA/GDPR 删除个人信息邮件发出（`send-email --kind ccpa_indirect`），并把 `blocked`
  推迟到隐身浏览器那一轮。退出请求会遇到 CAPTCHA、邮件验证循环和会话绑定——请
  **一次一个、仔细地**处理（这与并行扇出正好相反），但在 `autonomy=full` 下不要为每次
  提交停下来征求许可；在 `assisted` 模式下则逐个确认。当经纪商同时提供两种方式时，
  **通常优先选择删除而非抑制**（Spokeo/BeenVerified）——但要遵循记录中的
  `deletion.prefer`：**PeopleConnect 是例外**（`prefer: false`），在那里删除
  你的用户数据反而会清除你的抑制设置，也无法阻止公共记录重新收录，因此应当
  改为抑制并持续维护。
- **盲发退出请求是默认做法，而不是兜底手段。** 对**每一个具备可用移除通道的站点提交
  退出/删除请求，哪怕尚未先确认存在条目**——这只会向该经纪商自己的官方通道披露
  对象本人的标识信息，因此不违反最小披露原则。有两个推论：(1) 一个能匹配
  邮箱+出生日期+姓名却返回"无结果"的引导流程，是比任何抓取都**更强的 `not_found`
  证据**——退出流程本身就兼作搜索；(2) 当某个表单对自动化不友好时（硬 CAPTCHA、
  Cloudflare/DataDome、滑块验证），**优先改用该经纪商公示的权利请求邮箱**
  （只提供姓名+州+联系邮箱），而不是记录为 `blocked`。
  CAPTCHA 策略：绝不破解行为型/令牌型/滑块型挑战；在对象自己的退出流程中，读取静态的
  扭曲文字或简单算术 CAPTCHA 是可以的，但如果站点在答案正确后仍拒绝整个
  提交，就要停手（它是在给自动化打指纹）。第三方/间接记录属于例外——那些仍需
  先确认再行动。逐站作战计划以及元搜索空操作跳过清单见
  `references/site-playbooks.md`；完整策略见 `references/methods.md`。
- **PeopleConnect 的"删除会清除抑制"（永久规则）。** 一次 PeopleConnect *删除*会清除
  抑制设置，导致对象在整个关联集群中重新被收录。如果出现"Your deletion request
  for PeopleConnect.us is Complete"这封邮件，就说明抑制已经没了 → **重新执行抑制并
  重新验证** Control 步骤显示为"suppressed"。绝不要让这个集群停留在已完成的删除状态
  （见 `references/brokers/intelius.json`）。

子 agent 的汇报属于自述：父 agent 在记录 `found` 之前、以及在任何删除之前，都要复核关键
论断（列表 URL、匹配依据）。

## 步骤（自主循环）

1. **设置（一次，不提问）。** 运行 `$PDD setup --auto`——它会检测能力并自行配置
   最自主的有效组合（存在 `EMAIL_*` 凭据时用 programmatic 邮件，存在 Browserbase
   密钥时用它，存在 `age` 二进制时启用加密，`autonomy=full`）。然后运行
   `$PDD doctor`，把就绪情况**作为信息而非提问**展示给操作者——随即继续。
   可以提一句还有哪些东西能解锁更多自动化（例如邮箱凭据），但不要等待。
2. **接案 + 同意（唯一的一次人工对话）。** 带 `--consent`（以及
   `--consent-method`）运行 `$PDD intake ...`。没有同意，引擎会拒绝规划或行动。一次性
   收齐所有信息——姓名/别名、当前 + 历史城市、邮箱、电话——这样你就不必再回头
   追问。对于加州的对象，还要阅读 `references/legal/drop.md`：`next` 会给出一个
   `drop_submit` 一击式动作，可一次性从每一家已登记的经纪商（约 545 家）处删除，这是
   杠杆最高的单个动作。提交它，然后执行 `drop <subject> --filed`。对于非加州对象，
   登记册通过定向的 CCPA/GDPR 邮件覆盖（`registry --search`，然后 `send-email`）；
   无论哪种情况，人肉搜索站点都要直接处理。
3. **清空队列。** 循环：

   ```
   while true:
     q = $PDD next <subject>
     if q.actions is empty: break
     execute EVERY action in order; record each outcome via $PDD record
   ```

   `next` 按顺序产出：`refresh_brokers`（缓存过期）、`fanout_scan`/`scan_inline`（第 1 阶段
   爬取——见第 4 步）、`poll_verification`（进行中的邮件确认）、`verify_removal`（到期
   复查）、`optout_web_form`/`optout_email_send`（第 2 阶段，父站优先并附带 playbook 步骤）、
   `indirect_email_send`，以及 `stealth_rescan`。纯人工的工作绝不会作为动作出现——它会
   累积在 `q.human_digest` 中。在 `autonomy=full` 下，执行动作时不要暂停；在
   `assisted` 模式下则遵守 `confirm_first`。
4. **扫描（当 `next` 这么要求时）。** 对于 `fanout_scan`：运行 `$PDD fanout <subject>`，并
   **为每个 `batch` 并行启动一个 `delegate_task` 子 agent，把该批次现成的 `brief` 传进去**——
   不要自己串行地扫描所有经纪商。对于 `scan_inline`：那少数几个经纪商就自己扫。
   无论哪种方式，每个经纪商都要按 `references/methods.md` 的阶梯
   （`web_extract` → `site:` 探测 → `browser_navigate` → `scrapling`）走完**每一条**
   `search_vectors` 条目；404 属于**不确定**
   （不是 `not_found`）；当设置了 `antibot` 且没有隐身浏览器可用时记录 `blocked`；
   并且在记录之前先确认是对象本人而非同名者/亲属：
   `$PDD record <subject> <broker> <found|not_found|indirect_exposure|blocked> --found <bool> --evidence '{"listing_urls":[...]}'`。
   父 agent 在采信子 agent 的关键 `found` 论断之前会先复核。
5. **退出请求（当 `next` 这么要求时）。** 动作已按父站优先预先排序，并附带来自各经纪商
   记录自身 `optout.playbook` 的 `steps`（均经实地验证；PeopleConnect、
   Whitepages、BeenVerified、Spokeo 等集群父站有确切的、实地核对过的配方）。**删除通常
   优于抑制**：当某个动作带有 `prefer_deletion` 时，请走该记录的删除通道，而不是
   仅仅走隐藏我的条目的流程。当它带的是 `prefer_suppression` 时（**PeopleConnect**——
   删除会清除你的抑制设置且无法阻止重新收录），就执行抑制流程并持续
   维护；只有在你有意做数据清除时才使用他们的 Delete 按钮。按方法区分：
   - **web_form** → 用 `browser_navigate`/`browser_type`/`browser_click` 驱动 `optout_url`，
     只提交 `disclosure_fields`，对确认页截图，然后执行该动作的 `after` 记录命令。
     playbook 可能以一封主张删除权的 `send-email` 收尾——请照做（那是彻底删除，而不只是
     隐藏条目）。
    - **email** → `$PDD send-email <subject> <broker> --kind <ccpa|gdpr|generic> --to <addr>
      --listing <url>` 一步完成记录与披露（收件人被锁定为经纪商记录中声明的地址；
      `next` 会依据居住地选择 kind——绝不要为不符合条件的人主张 CCPA/GDPR）。在 **browser**
      模式下它返回一个收件人锁定的 `compose` 载荷：在操作者的网页邮箱中通过 `browser_*`
      新建一封邮件，收件人为 `compose.to`，主题/正文严格使用 `compose.subject`/`compose.body`
      并发送（无需密码）；在 **programmatic** 模式下则通过 SMTP 发送。当某个经纪商存在删除邮箱时，
      `next` 还会把需人工介入的表单（电话回拨/政府证件）改走该邮箱——即**救援通道**
      （已在 Whitepages 上验证的模式）。若只能生成草稿，则退回到
      `render-email` 加一条摘要条目。
   - **captcha** → 软性/托管型挑战在默认的云浏览器上会自动通过（照常推进）；
     只有它确实无法通过的硬性交互/行为型挑战才记录为 `blocked`
     （重新入队等待隐身/操作者浏览器那一轮）。绝不使用打码服务。
   - **phone_callback / account / gov_id / fax / mail / voice（T3）**且*没有*删除邮箱时 →
     绝不作为 agent 动作；`next` 已经把它们路由到摘要中。请记录：
     `$PDD record <subject> <broker> human_task_queued --reason "..."`。
 6. **验证（当 `next` 这么要求时）。** 在 **programmatic** 模式下，`$PDD poll-verification <subject>`
    会通过 IMAP 找到已到达的确认链接（带反钓鱼评分，自动推进状态）。在
    **browser** 模式下，在操作者的网页邮箱中打开该经纪商的确认邮件，并运行
    `$PDD verify-link <subject> <broker> --text '<body>'` 为链接评分。无论哪种方式，都要
    **在同一个浏览器中打开该链接**（有几家经纪商会把验证会话绑定到打开它的那个浏览器），
    走完流程，然后记录 `awaiting_processing`。只有当复查扫描显示条目确实消失后，才可标记
    `confirmed_removed`——绝不能凭提交流程自己的确认页面就下结论。
7. **收尾（每次运行一次）。** 当 `next` 不再返回动作时：如果 `$PDD tasks <subject>`
   （汇总的人工摘要）非空就先呈现它，然后是 `$PDD status <subject>`；如果启用了 Sheets
   跟踪表，就通过 `google-workspace` skill 追加 `$PDD report <subject> --sheets` 的数据行。
8. **安排下一次唤醒。** `next` 会返回 `next_wake_at`（最早到期的复查时间）。创建**一个**
   `cronjob`，用于为该对象重新运行此 skill 的循环（提示词形如：*"run the
   unbroker loop for &lt;subject_id>: `$PDD next` and execute all actions"*）。处理
   窗口、验证轮询和重新出现的排查全都流经同一个队列，因此这个案子
   无需任何人工关注也能持续推进。

## 常见陷阱

- **绝不要披露超出经纪商已展示范围的信息。** 只提交 `disclosure_fields`。引擎
  绝不会主动提供 SSN/证件号码，你也绝不可以。
- **没有同意就不行动。** 引擎会强制这一点；不要为了"研究"第三方而绕开它。
- **`send-email` 是幂等且带限流的。** 它会拒绝对已处于 `submitted` 或更后状态的案例
  重复发送（只有确有必要重发时才用 `--force`），并且 SMTP 发送会按
  `email_min_interval_seconds`（默认 20 秒）节流，并带重试/退避。不要为了"保险起见"
  循环发送——SMTP 成功交接并不等于送达；到期队列的复查扫描才是真正的确认。
- **账本写入带锁。** 并发运行（cron + 手动）会安全地串行化；如果你看到锁超时，说明
  另一次运行正在写入——让它完成，不要手动删除 `.lock`。
- **自主 ≠ 即兴发挥。** 完全自主意味着不在步骤之间*提问*，它并不放松任何
  关卡。如果某个经纪商在流程中途索要超出计划 `disclosure_fields` 的内容，请停止该案例
  并把它入队（`human_task_queued --reason`），而不是自行决定披露额外的个人信息。
- **不要用提问打断运行。** 配置选择是 `setup --auto` 的职责；纯人工的工作
  进摘要。运行途中唯一值得提问的，是某个阻碍扫描的身份信息缺失（例如完全没有城市）——
  而那本应在接案时就收集到。
- 对 `pdd.py` 请**使用 `terminal`，而不是 `execute_code`**（密钥清理 + 输出脱敏会破坏它）。
- **档案默认是明文的**（JSON，`HERMES_HOME` 下 `0600`）。要做静态加密，请运行
  `$PDD setup --encryption age`——它会生成一个本地 `age` 密钥并加密档案 + 账本
  （审计日志只保留字段名，保持明文）。它防的是随手查看/备份/误提交造成的泄露，
  而不是对整个 `HERMES_HOME` 的读取；若要真正做到密钥分离，请把 `PDD_AGE_IDENTITY`
  设到另一个卷上。`$PDD doctor` 会显示加密是否*确实*生效（而不只是是否安装了 `age`）。
- **"已从免费搜索中隐藏" ≠ 已删除。** 只有在核实记录确实消失之后才标记
  `confirmed_removed`；并在报告中注明付费层级的留存情况。
- **软 CAPTCHA 默认可通过；不要去硬碰硬的那些。** 默认云浏览器会把托管/软性挑战
  当作常规操作通过（那些经纪商仍属 T1）。对于它确实无法通过的硬性交互挑战，
  请记录 `blocked`，交给隐身/操作者浏览器那一轮——绝不使用第三方打码服务或指纹伪造。
- **经纪商页面会变。** 如果某个流程失效，请 `$PDD record ... blocked`，并把
  `references/brokers/` 中对应的经纪商文件标记为待重新核实，而不是靠猜。
- **提交前先核实未经实地验证的记录。** `confidence: auto` 的记录来自解析
  BADBOOL（请阅读 `optout.notes`/`optout.links`，确认真实的退出 URL）。`confidence:
  documented` 的记录（若干人肉搜索站点）带有正确的公示退出 URL，但**未**经
  实地验证（它们会对数据中心 IP 返回 403），因此首次使用时请通过操作者的
  住宅网络浏览器确认实际流程，然后设置 `last_verified`。经实地验证的精选记录
  （没有 `confidence` 字段，例如各集群父站）机制已核对过，优先级最高。

## 验证

- `scripts/run_tests.sh tests/skills/test_unbroker_skill.py`（封闭环境；无网络），或使用
  零依赖运行器 `python3 tests/skills/test_unbroker_skill.py`。
- 试运行：`$PDD setup --auto && $PDD doctor && SID=$($PDD intake --full-name "Test Person"
  --email t@example.com --consent | python3 -c 'import sys,json;print(json.load(sys.stdin)["subject_id"])')
  && $PDD next "$SID"`，确认能看到就绪情况摘要以及一个有序的动作队列。
