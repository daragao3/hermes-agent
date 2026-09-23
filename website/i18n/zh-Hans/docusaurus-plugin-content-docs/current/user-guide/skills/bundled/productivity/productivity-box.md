---
title: "Box — Box 管理云端文件、共享、搜索和元数据"
sidebar_label: "Box"
description: "Box 管理云端文件、共享、搜索和元数据"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Box

Box 管理云端文件、共享、搜索和元数据。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 内置（默认安装） |
| 路径 | `skills/productivity/box` |
| 版本 | `1.0.0` |
| 作者 | Chris Kim (iskysun96), Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `Box`, `Productivity`, `Cloud Storage`, `Collaboration`, `Metadata`, `Content Extraction`, `CLI`, `SDK` |
| 相关 skill | [`google-workspace`](/user-guide/skills/bundled/productivity/productivity-google-workspace) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Box

将 Box 用作云端文件系统，处理文件操作、协作、元数据和文档工作。使用 Hermes 的 `terminal` 工具和 Box CLI 执行操作；构建应用程序时请参考 SDK 指南。

## 使用时机 {#when-to-use}

- 整理、上传、管理版本、移动、共享 Box 文件和文件夹，或围绕它们进行协作
- 搜索 Box 内容或已有的元数据
- 就 Box 文件提问、提取元数据，或基于某个文件生成文本
- 在不下载每个源文件的情况下大规模处理一个 Box 文件夹
- 构建基于 Box 的应用程序、集成或 webhook 处理程序

## 开启宽泛的文件系统对话 {#start-broad-file-system-conversations}

当有人在为 Hermes 探索云端文件系统时，先给出一个简短的适配性评估：当团队需要云端文件存储、共享、搜索、元数据和文档工作时，Box 很有用。然后询问他们是想通过 OAuth 连接一个 Box 账户，还是想用 SDK 构建基于 Box 的应用程序或集成。

OAuth 会让 Hermes 以在浏览器中授权的那个 Box 账户身份行事。该账户的 Box 权限决定了 Hermes 能访问什么。若要给 Hermes 更窄的访问权限，请授权一个只被邀请到所需文件、文件夹或 Hub 的账户。

对于宽泛的探索性问题，不要运行配置、展示命令手册、提出账户方案或文件夹分类法，也不要加载所有参考资料。等待用户回答，然后只加载相关路径。当请求已经点明一个具体结果时，跳过这一探索步骤，直接处理该结果。

普通的 CLI 工作从官方 Box CLI OAuth 应用开始。它涵盖一般内容工作和 Box AI。只有当所请求的操作需要额外的 OAuth 权限范围（例如 webhook 管理）时，才使用自定义的 **User Authentication (OAuth 2.0)** Platform App。这仍然是一个 OAuth 流程；不要用服务端身份或模拟身份来替代。

## 以交互方式执行所选配置 {#perform-chosen-setup-interactively}

当用户选择了一条认证路径或要求 Hermes 连接 Box 时，通过 `terminal` 执行配置；不要把下一条回复变成让用户照抄的操作说明。自己采取下一步安全操作，只在需要审批、浏览器登录、管理员操作或 Hermes 无法安全提供的机密时才暂停。

- 如果缺少 `box`，请求所需的终端审批，将 `@box/cli` 安装到当前 Hermes 主目录下的 `tools/box-cli`；然后用 [CLI 指南](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/cli-guide.md)中适用于当前 shell 的命令进行验证。不要尝试全局 npm 安装、使用 `sudo`、修改 npm 的全局前缀或修改 `PATH`。
- 在 OAuth 之前，先问：**“Hermes 是运行在你用来授权 Box 的浏览器所在的同一台电脑上，还是运行在 VPS、容器或云虚拟机之类的远程主机上？”** 只有同一台电脑的路径才使用普通的 `box login`。只有远程/无头路径才使用 `box login --code`。不要仅凭操作系统推断运行拓扑；用户回答后请阅读 [OAuth 配置](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/oauth-setup.md)。
- 在开始浏览器授权之前，说明 Hermes 将以在那里登录的 Box 账户身份行事。如果用户想要更窄的访问权限，可以授权一个只被邀请到所需文件、文件夹或 Hub 的账户。不要为了解锁某个特殊操作而把该账户设为管理员。
- 如果确实需要自定义 OAuth Platform App，请使用 CLI 的交互式 Platform App 流程。让用户只在本地 CLI 提示中输入其 client secret；永远不要在聊天中索取它、把它写入 Hermes 配置或提交它。
- 如果安装、浏览器授权、环境切换或权限变更需要审批，请请求审批，并在获批后继续配置。不要用一份命令列表替代该操作。

## 开始每个任务 {#start-each-task}

1. 确认 CLI 和当前操作者。在 POSIX shell 中用 `command -v box` 探测，在 PowerShell 中用 `Get-Command box -ErrorAction SilentlyContinue` 探测。如果 `box` 在 `PATH` 中，就使用它。如果 Hermes 把 CLI 安装在其当前主目录下，就用 [CLI 指南](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/cli-guide.md)中适用于当前 shell 的已验证运行器替换每个开头的 `box`。然后用该运行器执行 `box users:get me --json --fields id,name,login`。
   如果成功，记录操作者并继续。不要再次询问认证。`folders:items 0` 只应被视为操作者根目录的列表；它不能证明某个共享文件、文件夹或 Hub 无法访问。对于已知的文件或文件夹，直接验证其 ID；对于 Hub，使用 [Box Hubs](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/hubs.md) 中的 Hub 发现路径。
2. 如果尚未认证，请求通过 OAuth 连接一个 Box 账户，然后询问 Hermes 和用于授权的浏览器是运行在同一台电脑上还是不同的主机上。阅读 [OAuth 配置](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/oauth-setup.md)。
3. 操作前先阅读相关参考资料。优先使用文档中记载的命令；只有当请求需要参考资料未覆盖的选项，或已安装的 CLI 拒绝文档中的写法时，才查看子命令帮助。

标注为 `bash` 的示例使用 POSIX 续行语法。在 PowerShell 中，请把 Box 命令写在一行里，或将每个行尾的 `\` 替换为 PowerShell 的反引号续行符。不要把 POSIX 变量赋值粘贴到 PowerShell 中。

## 不中断地扩展 CLI {#extend-the-cli-without-pausing}

当 Box CLI 缺少专门的子命令时，对相应的 REST 端点使用 `box request`，并继续这项普通操作。不要仅仅因为实现使用了 REST 就让用户做选择；这是同一个 Box 任务，并且保留了已配置的 CLI 身份。当端点需要请求体或自定义请求头时，请阅读 [REST API 后备](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/rest-api.md)。

在执行删除、协作/共享链接或权限变更、身份变更、大范围或高成本的批量变更，或目标/范围不明确时，先询问。否则就执行所请求的操作并加以验证。

## 选择正确的路径 {#choose-the-right-path}

| 需求 | 阅读 |
| --- | --- |
| CLI 约定、环境、JSON 或 REST 应急通道 | [CLI 指南](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/cli-guide.md) |
| 文件、文件夹、版本、链接或协作 | [内容工作流](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/content-workflows.md) |
| 搜索、元数据、Box AI 或 AI 单位 | [搜索与 AI](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/search-and-ai.md) |
| 精选的大规模问答或可复用知识库 | [Box Hubs](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/hubs.md) |
| 大量文件或可续传的批处理 | [批量操作](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/bulk-operations.md) |
| 应用程序代码或 Box SDK | [SDK 开发](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/sdk-development.md) |
| Webhook 或 Events API | [Webhook 与事件](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/webhooks-and-events.md) |
| CLI 不可用或缺少某个 CLI 操作 | [REST API 后备](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/rest-api.md) |
| 认证、权限、速率限制或 API 错误 | [故障排查](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/troubleshooting.md) |

## 内容处理策略 {#content-handling-policy}

对 Box 托管内容进行语义分析时，优先使用 Box AI：它保留 Box 权限，通过 Box 受管控的 AI 集成处理源文件，让源文件正文不进入 Hermes 编码模型的上下文，并且无需下载每个文件就能扩展文档工作。不要批评或阻拦其他工作流；当用户明确选择其他工作流时就使用它。

对于确定性查找，使用已有的 Box 元数据或元数据查询。否则使用 Box AI：

- `ai:ask` 用于问答、摘要和比较
- `ai:extract-structured` 用于已知字段或元数据模板
- `ai:extract` 用于灵活的键值提取
- `ai:text-gen` 用于基于单个 Box 文件撰写内容

对于超过 25 个文件的问答或可复用的精选知识库，优先使用 Box AI for Hubs。先查找一个已有的可访问 Hub；只有在用户批准这项共享资源变更之后，才创建或填充 Hub。如果没有可用的 Hub 且用户不希望创建，就用搜索或元数据缩小一次性请求的范围。不要用 Hub 做元数据提取或文本生成。阅读 [Box Hubs](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/hubs.md)。

当用户要求从某个 Box 文件提取元数据时，除非他们要求只是预览，否则应视为要求持久化结果。当所需 schema 已知时，使用带内联字段的结构化提取；当字段尚在探索时，使用自由形式提取。当某个兼容的现有企业模板能表示所有请求字段时，复用它。否则，将扁平的标量结果存入内置的 `global.properties` 元数据实例；当结果包含嵌套对象、表格或必须保留类型的值时，在源文件旁上传一个 JSON 附属文件。回读每一次写入，并与预期结果比较。永远不要悄悄用文件描述替代、附加一个不完整或无关的模板、截断字段或丢弃字段。

不要创建或修改元数据模板。Box 不允许创建全局模板，而企业模板管理不属于 Hermes 常规的 OAuth 内容工作流。如果用户需要可复用的类型化企业元数据而又没有兼容的模板，请说明必须由 Box Admin 或获得授权的 Co-Admin 另行创建，保持现有结构化元数据不变，并改为报告已持久化的 `global.properties` 实例或 JSON 附属文件。完整的提取与回写流程请阅读[搜索与 AI](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/search-and-ai.md)。

在第一次发出 Box AI 请求之前，说明 Box AI 必须已启用、会消耗 AI 单位，并且仍受当前操作者权限的限制；无需等待对方确认。返回给 Hermes 的 AI 响应仍可能包含敏感信息。只有当某个重要批次的文件范围或预期 AI 单位消耗不明确，或用户没有明确要求这种规模时，才需要确认。参见[搜索与 AI](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/box/references/search-and-ai.md)。

## 安全操作 {#operate-safely}

- 优先使用 ID 而不是路径，并在诊断文件缺失之前先核实当前操作者。
- 使用 `--json` 和 `--fields` 让输出保持精简。对于变更操作，先盘点，确认不明确或大范围的作用域，然后回读结果。
- 按顺序串行执行有序的 CLI 变更，使进度和恢复都清晰无歧义。对于可扩展的工作，使用文档中记载的批量输入支持或有界的 SDK 并发。
- 不要仅仅为了提供导航而创建共享链接。共享链接会改变访问权限，需要明确确认。
- 不要把机密放进聊天、命令输出、源代码管理或日志中。

## 报告结果 {#report-results}

对于每个单独报告的 Box 条目，都附上其 ID 和可点击的导航链接：

- 文件：`https://app.box.com/file/<FILE_ID>`
- 文件夹：`https://app.box.com/folder/<FOLDER_ID>`
- Hub：`https://app.box.com/hubs/<HUB_ID>`

对于大批量操作，链接源文件夹和目标文件夹以及例外项，而不是列出成百上千个条目。人类用户可能无法打开只有已连接 Box 账户才能看到的内容；请明确说明这一点。每一份写入摘要都要包含操作者和所执行的验证。

## 验证 {#verify}

任何写入之后，都用同一操作者获取该文件或文件夹，或列出其父文件夹，并确认返回的 ID 和名称。对于元数据写入，取回元数据实例，并将每个返回字段与预期值进行比较；仅有 HTTP 成功并不算验证。报告缺失、被规范化或被拒绝的值。对于一次性的配置检查，创建一个冒烟测试文件夹，验证它，然后只有在用户授权清理时才删除它。
