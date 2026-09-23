---
sidebar_position: 13
title: "插件目录"
sidebar_label: "插件目录"
description: "从精选目录中浏览并安装经过审核、固定 SHA 的 Hermes 插件"
---

# 插件目录 {#plugin-catalog}

插件目录是一个经过人工审核的精选 Hermes 插件目录，你可以用一条命令按名称安装其中的插件：

```bash
hermes plugins install <name>
```

可以在 **[/docs/plugins](/plugins)** 以可视化方式浏览——支持搜索、层级筛选（官方 / 社区）、能力标签，并为每个条目提供可复制的安装命令。

插件目录是对现有[插件系统](plugins.md)的补充——而非替代。从目录中安装的任何东西在底层都是普通插件；目录只是在其上增加了发现能力和一层审核。

## 条目包含什么 {#whats-in-an-entry}

每个目录条目都是 hermes-agent 仓库
[`plugin-catalog/`](https://github.com/NousResearch/hermes-agent/tree/main/plugin-catalog)
目录下的一个小型 YAML 文件，声明以下内容：

| 字段 | 含义 |
|---|---|
| `name` | 传给 `hermes plugins install` 的目录键名 |
| `repo` | 插件的公开 git 仓库 |
| `sha` | 经过审核的**确切 40 位十六进制提交**——安装会检出这个固定版本，而不是某个分支的最新提交 |
| `tier` | `official`（由 NousResearch 维护）或 `community` |
| `maintainer` | 插件的所有者 |
| `capabilities` | 声明的工具、hook、中间件以及所需的环境变量 |
| `requires_hermes` | 最低 Hermes 版本，例如 `>=0.19`（可选） |
| `platforms` | 操作系统限制，留空 = 全部（可选） |
| `docs_url` | 外部文档链接（可选） |

## 信任模型 {#trust-model}

插件目录的设计目标是让你确切知道自己安装的是什么：

- **人工合并准入。** 每个条目（以及每次固定版本更新）都通过由维护者审核的 pull request 合入。没有任何内容会自动进入目录。
- **精确的 SHA 固定。** 条目固定的是某个具体提交，而不是分支。插件作者向自己的仓库推送新代码**不会**改变目录安装的内容——更新固定版本需要另一个经过审核的 PR。
- **能力声明。** 条目会预先声明插件提供了哪些工具、hook 和中间件，以及需要哪些环境变量（API 密钥等），让你在安装之前就能判断其影响范围。
- **移除列表。** 从目录中撤下的插件（例如发生安全事件后）会连同原因和日期一起列入 `plugin-catalog/removed.yaml`。安装程序拒绝安装移除列表中的任何内容。
- **已安装 ≠ 已启用。** 安装目录插件只是把它放到磁盘上；与任何插件一样，它必须先启用才会加载。参见[插件 → 启用与禁用](plugins.md)。

:::warning 目录审核是某一时间点的审核
一个目录条目意味着固定的那个提交经过了人工查看、能力声明经过了核对，并且仓库满足提交标准。它不是安全审计，也不对同一仓库中的其他提交做任何保证。凡是你要交付凭据的插件，请自行审查其代码。
:::

## 从目录安装 {#installing-from-the-catalog}

```bash
# 按名称安装一个经过审核的目录条目（检出固定的 SHA）
hermes plugins install <name>

# 然后像任何插件一样启用它
hermes plugins enable <name>
```

安装提示会在克隆任何内容之前显示该条目的能力摘要——声明的工具、hook 和所需的环境变量。

### 更新目录安装的插件 {#updating-a-catalog-install}

对于目录安装，`hermes plugins update <name>` 从不运行 `git pull`——它会将你已安装的固定版本与当前目录中的固定版本进行比较，当目录发生变动（通过经审核的 PR）时，强制在新 SHA 上重新安装。你的启用/禁用状态会被保留。`hermes plugins list` 会把目录安装显示为 `catalog:<tier>@<sha>`，让你一眼看出来源。

### 不在目录中的名称 {#names-not-in-the-catalog}

一个不属于目录条目的裸名称会报错：不存在第二个未经审核的名称索引。请改用 `owner/repo` 或 Git URL 安装此类插件（自定义来源，见下文），或将它们提交到目录。

### 实时刷新 {#live-refresh}

文档构建会把目录发布为一个 JSON 文档
（`https://hermes-agent.nousresearch.com/docs/api/plugin-catalog.json`）。
`search`/`install`/`update` 最多每六小时获取一次，并缓存在 `~/.hermes/cache/` 下，因此新条目和移除项无需更新 Hermes 即可到达已安装的客户端。离线时会使用随你的检出一起提供的副本。仓库内列表和实时列表中的移除项始终同时生效。

### 自定义 git URL 则不同 {#custom-git-urls-are-different}

`hermes plugins install <git-url>` 对任何仓库仍然有效，但它会完全绕过目录：

- **没有审核**——你得到的是分支最新提交上的任何内容，而不是经过审核的固定版本。
- 会显示**一个警告横幅**，明确表示代码未经审查。
- 仍会查询移除列表（已知有问题的仓库会按 URL 被拒绝）。

对你自己的插件和你已信任的仓库使用 git URL 路径；用目录来发现插件。

## 向目录提交插件 {#submitting-a-plugin-to-the-catalog}

提交方式是发起一个新增一个 `plugin-catalog/<name>.yaml` 文件的 pull request。完整清单见
[plugin-catalog README](https://github.com/NousResearch/hermes-agent/tree/main/plugin-catalog)；
简而言之，条目必须满足：

1. **由所有者提交**——PR 作者拥有或维护该插件仓库。
2. **公开仓库**——`repo` URL 可以公开克隆。
3. **已发布**——仓库有真正的 release/tag，而不仅仅是一个默认分支。
4. **通过校验**——目录校验 GitHub Action 在该 PR 上为绿色（schema、SHA 格式、可达性）。
5. **固定到已稳定的代码**——固定的 SHA 至少已有 **2 周**，这样目录永远不会指向在审核前片刻才推送的代码。

固定版本更新（把 `sha` 提升到更新的提交）遵循同样的 PR + 审核流程。

## 另请参阅 {#see-also}

- [插件](plugins.md)——插件系统本身：清单格式、启用、配置
- [内置插件](built-in-plugins.md)——随 Hermes 一起提供的插件
- [构建 Hermes 插件](/developer-guide/plugins)——编写你自己的插件
- [插件目录页面](/plugins)——可浏览的目录
