---
sidebar_position: 1
title: 出站代理
description: "用于远程终端沙箱的可选出站凭据注入防火墙"
---

# 出站代理

用于远程终端沙箱的可选出站凭据注入防火墙。沙箱中只会持有不透明的代理 token；真实的 API 密钥永远不会离开主机。

- [iron-proxy](./iron-proxy) —— 来自 [ironsh/iron-proxy](https://github.com/ironsh/iron-proxy) 的单二进制 TLS 拦截代理，按需延迟安装，并由 `hermes egress` 管理。
