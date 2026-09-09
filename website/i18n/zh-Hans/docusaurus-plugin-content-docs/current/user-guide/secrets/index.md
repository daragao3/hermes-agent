# Secrets

Hermes 可以在进程启动时从外部密钥管理器拉取 API 密钥，而不是将其存储在 `~/.hermes/.env` 中。密钥管理器的引导令牌存放在 `.env` 中；其他所有提供商密钥（OpenAI、Anthropic、OpenRouter 等）可以保留在管理器中并集中轮换。

支持的后端：

- [Bitwarden Secrets Manager](./bitwarden) — 使用 `bws` CLI，懒加载安装，免费套餐可用。
- [1Password](./onepassword) — 通过官方 `op` CLI 使用 `op://` 引用；支持服务账号或桌面端 session 认证。

## 同时使用多个来源

你可以同时启用多个密钥来源——例如在团队 Bitwarden 项目之外再加一个个人保险库插件。各来源会按环境变量逐项组合，并遵循确定性的优先级阶梯：

1. **默认情况下你的 `.env` / shell 优先。** 只有当某个来源自身设置了 `override_existing: true` 时，它才会替换已存在的值（Bitwarden 默认为 true，以便集中轮换生效）。
2. **映射式来源优先于批量式来源。** 显式将环境变量绑定到引用（`env:` 映射）的来源，其优先级高于隐式注入整个项目密钥的来源，与顺序无关。
3. **先到先得。** 在形态相同的情况下，由可选的 `secrets.sources` 列表顺序（或注册顺序）决定。对已被占用的变量的后续声明会被跳过——并伴随一条启动警告，绝不会静默发生。

`override_existing` 绝不会允许一个来源覆盖另一个来源已经占用的变量，任何来源也永远无法覆盖其他来源的引导令牌（例如 `BWS_ACCESS_TOKEN`）。

```yaml
secrets:
  sources: [bitwarden]     # optional explicit ordering
  bitwarden:
    enabled: true
    project_id: "..."
```

由某个来源注入的每一份凭据都会标注其出处——setup 流程和 `hermes model` 会在检测到的密钥旁显示 `(from Bitwarden)`，让你始终清楚某个值来自哪里。

## 接入你自己的后端

第三方密钥管理器以独立插件形式发布，而不是核心 PR。后端需继承 `agent.secret_sources.base.SecretSource`（仅有一个必需方法：`fetch(cfg, home_path) -> FetchResult`），并在插件的 `register(ctx)` 中通过 `ctx.register_secret_source(MySource())` 注册。优先级、冲突处理、超时和出处追踪均由编排器负责——你的来源只负责拉取。包含契约规则、子进程安全辅助工具和一致性测试套件的完整指南：[构建 Secret Source 插件](/developer-guide/secret-source-plugin)。

内置集合是刻意封闭的（与记忆提供商采用相同策略）：Bitwarden 和 1Password 随代码树发布。其他一切——Infisical、Proton Pass、HashiCorp Vault、AWS Secrets Manager、操作系统密钥库——都应放在插件仓库中；欢迎在 Nous Research Discord（`#plugins-skills-and-skins`）中分享。
