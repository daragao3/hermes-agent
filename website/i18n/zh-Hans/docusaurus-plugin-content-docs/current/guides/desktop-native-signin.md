---
sidebar_position: 18
title: "桌面端原生登录（RFC 8252）"
description: "Hermes Desktop 应用如何使用系统浏览器和 PKCE 登录受保护的 gateway——无内嵌 webview，无会话 cookie"
---

# 桌面端原生登录（RFC 8252） {#desktop-native-sign-in-rfc-8252}

当 Hermes Desktop 应用连接到**受保护的 gateway**（位于 OAuth 提供方之后的托管或
自托管 dashboard）时，它有两种
登录方式：

1. **原生登录（RFC 8252）**——应用会打开你的**真实系统浏览器**，
   你在自己已经信任的浏览器中完成授权，应用随后收到 token，并将其
   以仅所有者可访问的文件形式存储在用户数据目录中（可选择通过操作系统钥匙串加密
   ——设置 → Gateway）。**无内嵌 webview，无
   浏览器会话 cookie。** 只要 gateway
   支持，这就是默认方式。
2. **内嵌登录（旧版回退）**——应用会打开一个小型的应用内
   浏览器窗口，并捕获 gateway 的会话 cookie。当 gateway 是不公布原生登录能力的
   旧版本时，会自动使用此方式。

你无需在二者之间做选择——应用会检测 gateway 支持的方式并
选出最佳方案。本页解释其中发生了什么以及为什么这样做。

## 为什么使用原生登录 {#why-native-sign-in}

在原生应用中内嵌浏览器来完成 OAuth 有众所周知的缺点：
登录页面看不到你现有的浏览器会话（因此你要重新输入
凭据并重新进行 MFA），密码管理器和通行密钥（passkey）常常无法使用，
而且应用依赖于从私有 webview 中读取会话 cookie。RFC
8252（"OAuth 2.0 for Native Apps"）是避免上述所有问题的业界最佳实践：
**在系统浏览器中完成授权，并把应用自己的
token 交给它。**

具体到 Hermes，原生登录意味着：

- **无内嵌 webview。** 授权发生在 Safari / Chrome /
  Firefox / Edge——无论你使用哪一个——中，你的登录状态、扩展和
  通行密钥都完好无损。
- **无会话 cookie。** 应用持有一个 OAuth **access token**（短期有效）
  和 **refresh token**，以仅所有者可访问的文件形式存储——当设置 → Gateway 中
  可选启用的钥匙串开关打开时，会通过操作系统钥匙串（Electron `safeStorage`）进行静态加密。
  REST 调用和 WebSocket ticket 使用 `Authorization: Bearer` 请求头进行认证，
  而不是 cookie jar。

## 工作原理 {#how-it-works}

```
Desktop app                Gateway (/auth/native/*)          Nous Portal (IDP)
   │ 1. open loopback 127.0.0.1:<random port>
   │ 2. system browser ─►  /auth/native/authorize
   │    (PKCE challenge)    (starts the normal PKCE login) ─► /oauth/authorize
   │                        ◄──── code ──── /auth/callback ◄──┘
   │                        3. mint one-time gateway code
   │ ◄─ 302 127.0.0.1/cb?code=… ─┘
   │ 4. POST /auth/native/token (code + PKCE verifier)
   │ ◄─ 5. { access_token, refresh_token, expires_at } ───────┘
   │ 6. store in local token store; use Bearer for REST + WS tickets
```

gateway 充当该流程的**中介（broker）**：它*对桌面应用*而言是授权服务器，
*对上游身份提供方*（Nous
Portal）而言是 OAuth 客户端。之所以必须如此，是因为上游的 `client_id` 和允许的
重定向 URI 都绑定在 gateway 自己的源（origin）上——桌面应用无法成为
Portal 的直接客户端。桌面端仍然获得完整的 RFC 8252
体验：它自己的 PKCE 密钥对、它自己的 loopback 重定向，以及它自己持有的 token。

**PKCE（RFC 7636）** 保护 loopback 这一跳：一次性的 gateway code 若没有
code verifier 就毫无用处，而 code verifier 从不离开应用。该 code
只能使用一次且有效期很短。

## 能力检测与回退 {#capability-detection--fallback}

桌面端会读取 gateway 公开的 `/api/status` 端点，该端点会公布
一个 `auth_flows` 数组：

| `auth_flows` 值 | 含义 |
|--------------------|---------|
| `["cookie", "native_pkce"]` | gateway 支持原生登录 → 应用使用原生登录 |
| `["cookie"]` | gateway 仅支持旧版流程 → 应用使用内嵌 webview |
| *（字段缺失）* | 较旧的 gateway → 应用使用内嵌 webview |

如果 gateway 公布了原生登录但因本地原因失败——例如安全
工具阻止了 loopback 监听器，或者你关闭了浏览器标签页——应用会
**自动回退到内嵌流程**，因此你仍然可以登录。

## Token 生命周期 {#token-lifecycle}

- **Access token**：短期有效（数分钟）。在每次 REST 调用以及
  铸造 WebSocket ticket 时，以 `Authorization: Bearer` 形式发送。
- **Refresh token**：有效期更长，且会轮换。当 access token 即将
  过期时，应用会调用 `/auth/native/refresh` 轮换两个 token，然后
  更新其 token 存储。
- **最终过期**：如果 refresh token 已失效（过期 / 被吊销 /
  检测到重用），应用会清除已存储的 token，并提示重新
  登录。
- **退出登录**：同时清除已存储的原生 token 以及该 gateway 的
  任何旧版会话 cookie。

## 面向 gateway 运维者 {#for-gateway-operators}

在任何注册了交互式会话提供方的受保护 gateway 上，原生登录都会自动
可用。无需任何配置——
`/auth/native/*` 路由和 `auth_flows` 公布都是
dashboard-auth 子系统的一部分。OAuth 提供方（例如内置的 **Nous** 提供方）
负责中转上游 IDP 的重定向；密码提供方（例如内置的
**basic-auth** 插件）则会让系统浏览器落到 gateway 的 `/login`
凭据表单上——正是这一点让操作系统的密码管理器（macOS
Passwords 等）能够自动填充表单，这是任何内嵌的桌面 webview 都无法
提供的。纯 token 凭据（例如 drain）不属于交互式登录，也
不会公布 `native_pkce`。

相关端点（全部公开，属于认证前的引导阶段，与现有的
`/auth/*` OAuth 路由相同）：

- `GET /auth/native/authorize`——启动经中介的 PKCE 登录
- `POST /auth/native/token`——用 loopback code + verifier 换取 token
- `POST /auth/native/refresh`——使用应用的 refresh token 轮换 token

## 另请参阅 {#see-also}

- [通过 SSH / 远程主机进行 OAuth](./oauth-over-ssh.md)——在远程机器上为提供方/MCP OAuth
  使用的 loopback 回调模式。
- [使用 Nous Portal 运行 Hermes](./run-hermes-with-nous-portal.md)
