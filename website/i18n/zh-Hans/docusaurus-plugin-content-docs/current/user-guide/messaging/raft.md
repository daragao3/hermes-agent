---
sidebar_position: 19
title: "Raft"
description: "通过 wake-channel 桥接将 Hermes Agent 作为外部 agent 接入 Raft"
---

# Raft 设置

Hermes 通过本地 wake-channel 桥接进程，以外部 agent 的身份接入 [Raft](https://raft.build)。适配器会启动一个 loopback HTTP 端点，接收桥接进程发来的无内容唤醒提示（wake hint），然后将其注入 Hermes gateway 的会话管道。agent 通过 Raft CLI 读取和发送消息——适配器从不接触消息正文或投递游标。

:::info 职责划分
- **桥接进程**负责：消费唤醒提示、去重、退避、重连、至少一次投递以及凭证日志记录。
- **Hermes 适配器**负责：提供一个 localhost 唤醒端点，并向 agent 的上下文中注入一条简短通知。
- **agent** 负责：拉取消息（`raft message check`）、回复（`raft message send`），以及通过 CLI 完成其他所有 Raft 交互。

适配器不持有任何 Raft 凭据——只有一个用于桥接进程与端点之间 localhost 鉴权的每会话共享令牌。
:::

---

## 前提条件

- 一个可以创建 External Agent 的 **Raft 工作区**
- 已安装并已登录该 External Agent 配置档的 **Raft CLI**
- **aiohttp** —— Python 包（包含在 Hermes `[all]` 扩展依赖中）

在 Raft 中打开 Agents 菜单，创建一个 External Agent，然后按照设置卡片的指引安装 Raft CLI 并登录该 agent 配置档。agent 创建完成后，Raft 会展示一份 Hermes 设置指南，其中包含启动 gateway 所需的环境变量和配置。

---

## 设置

添加到 `~/.hermes/.env`：

```bash
RAFT_PROFILE=your-agent-profile
```

这样就完成了——设置 `RAFT_PROFILE` 后适配器会自动启用。它会生成一个每会话的桥接令牌、选取一个临时端口，并在 gateway 启动时自动派生桥接子进程。

---

## 工作原理

```
Raft 服务器 → 桥接进程（wake-hints SSE） → POST /wake → Hermes 适配器 → agent 上下文
agent → raft message check → Raft 服务器（消息正文）
agent → raft message send → Raft 服务器（回复）
```

1. Raft 服务器通过 SSE 向桥接进程发送唤醒提示。
2. 桥接进程将每条提示以 `POST /wake` 的形式转发到适配器的 loopback 端点。
3. 适配器校验桥接令牌，确认负载不含内容，并向 Hermes 会话注入一条唤醒通知。
4. agent 看到唤醒通知后，使用 Raft CLI 读取消息并回复。

唤醒负载按约定**不含内容**——它们携带元数据（事件 ID、消息 ID、时间戳），但绝不包含消息正文、频道名称或发送者身份。适配器会拒绝任何包含内容型字段（`text`、`body`、`content`、`messages` 等）的负载。

---

## 桥接进程

适配器会自动将 `raft agent bridge` 作为子进程派生，并传入端点 URL 和令牌。桥接进程使用配置的配置档连接 Raft 服务器，并开始转发唤醒提示。gateway 关闭时该进程会被终止。

---

## 环境变量

| 变量 | 说明 | 默认值 |
|----------|-------------|---------|
| `RAFT_PROFILE` | Raft agent 配置档 slug —— 设置后自动启用适配器 | _(必填)_ |
