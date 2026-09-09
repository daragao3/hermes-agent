---
sidebar_position: 13
title: "浏览器提供商插件"
description: "如何为 Hermes Agent 构建云端浏览器后端插件"
---

# 构建浏览器提供商插件

浏览器提供商插件注册一个**云端浏览器后端**，用于服务云模式下的 `browser_*` 工具调用（导航、点击、截图……）。内置提供商——Browserbase、Browser Use 和 Firecrawl——均以插件形式存放于 `plugins/browser/<name>/` 目录下。你可以在它们旁边新建一个目录来添加新提供商，或覆盖已有的内置提供商。

:::tip
浏览器后端是 Hermes 支持的多种**后端插件**之一。其他插件（各有其 ABC）包括：[网页搜索提供商插件](/developer-guide/web-search-provider-plugin)（本 ABC 有意与之保持一致）、[图像生成](/developer-guide/image-gen-provider-plugin)、[视频生成](/developer-guide/video-gen-provider-plugin)、[记忆提供商](/developer-guide/memory-provider-plugin)、[上下文引擎](/developer-guide/context-engine-plugin)、[密钥来源](/developer-guide/secret-source-plugin)和[模型提供商](/developer-guide/model-provider-plugin)。通用工具/hook/CLI 插件请参阅[构建 Hermes 插件](/developer-guide/plugins)。
:::

## 各部分如何协作

浏览器提供商**不**实现浏览行为。它实现的是**会话生命周期**：创建一个远程浏览器会话、返回一个 CDP websocket URL，并在结束时销毁该会话。Hermes 自身的浏览器栈（`agent-browser` + `tools/browser_tool.py`）会连接到你返回的任意 CDP URL，并从那里驱动页面——每个提供商都能免费获得完整的 `browser_*` 工具集。

活跃的提供商由 `config.yaml` 中的 `browser.cloud_provider` 选定；`tools/browser_tool.py` 中的分发器是纯粹的注册表查找，不含任何针对具体提供商的条件分支。

## 发现机制

Hermes 在三个位置扫描浏览器后端：

1. **内置** — `<repo>/plugins/browser/<name>/`（以 `kind: backend` 自动加载）
2. **用户** — `~/.hermes/plugins/browser/<name>/`（通过 `plugins.enabled` 或 `hermes plugins enable <name>` 按需启用）
3. **Pip** — 声明了 `hermes_agent.plugins` 入口点的包

每个插件的 `register(ctx)` 会调用 `ctx.register_browser_provider(...)`，将实例放入 `agent/browser_registry.py` 中的注册表。

## 目录结构

```
plugins/browser/my-backend/
├── __init__.py     # register() entry point
├── provider.py     # BrowserProvider subclass
└── plugin.yaml     # Manifest with kind: backend and provides_browser_providers
```

`plugin.yaml`：

```yaml
name: browser-my-backend
version: 1.0.0
description: "My cloud browser backend. Requires MY_BACKEND_API_KEY."
author: you
kind: backend
provides_browser_providers:
  - my-backend
```

`__init__.py`：

```python
from plugins.browser.my_backend.provider import MyBackendProvider


def register(ctx) -> None:
    ctx.register_browser_provider(MyBackendProvider())
```

## BrowserProvider ABC

实现 `agent.browser_provider.BrowserProvider`。包含三个生命周期方法，外加标识信息：

```python
from agent.browser_provider import BrowserProvider


class MyBackendProvider(BrowserProvider):
    @property
    def name(self) -> str:
        return "my-backend"          # the browser.cloud_provider config value

    @property
    def display_name(self) -> str:
        return "My Backend"          # shown in `hermes tools`

    def is_available(self) -> bool:
        """Cheap check only — env var present, dep importable.
        NO network calls: runs at tool-registration time and on every
        `hermes tools` paint."""
        return bool(os.environ.get("MY_BACKEND_API_KEY"))

    def create_session(self, task_id: str) -> dict:
        """Create a remote browser session; return the session-metadata contract."""
        session = my_api.create_browser(...)
        return {
            "session_name": f"my-backend-{task_id}",  # unique agent-browser session name
            "bb_session_id": session.id,              # provider session ID (for cleanup)
            "cdp_url": session.cdp_ws_url,            # CDP websocket URL
            "features": {"stealth": True},            # feature flags you enabled
        }

    def close_session(self, session_id: str) -> bool:
        """Terminate by provider session ID. Log-and-return-False on error —
        never raise, so the dispatcher's cleanup loop keeps moving."""
        ...

    def emergency_cleanup(self, session_id: str) -> None:
        """Best-effort teardown from atexit/signal handlers. Must not raise."""
        ...
```

### 会话元数据契约

`create_session()` 必须至少返回 `session_name`、`bb_session_id`、`cdp_url` 和 `features`。有两点值得注意：

- **`bb_session_id` 是一个遗留键名**，为与 `tools/browser_tool.py` 保持向后兼容而原样保留——无论供应商是谁，它保存的都是*你自己*提供商的会话 ID。不要重命名它。
- `create_session()` **可以抛异常**——凭据缺失抛 `ValueError`，网络/API 故障抛 `RuntimeError`。分发器会把这些呈现给用户。这与 `close_session`/`emergency_cleanup` 不同，后两者绝不能抛异常。

可选的 `external_call_id` 键用于支持托管网关的计费。

### `get_setup_schema()` —— `hermes tools` 选择器中的一行

覆写此方法，即可作为一等选项出现在 Browser Automation 选择器中，并带上 API key 提示与安装钩子：

```python
def get_setup_schema(self) -> dict:
    return {
        "name": "My Backend",
        "badge": "paid",
        "tag": "Cloud browser with stealth and proxies",
        "env_vars": [
            {"key": "MY_BACKEND_API_KEY",
             "prompt": "My Backend API key",
             "url": "https://mybackend.example"},
        ],
        "post_setup": "agent_browser",   # auto-installs the agent-browser npm dep
    }
```

按照本项目对工具后端的标准：如果一个后端不能通过 `hermes tools` 选中并配置，那它就没做完——"请手动设置这个环境变量"不算集成。

## 用户如何配置

```yaml
browser:
  cloud_provider: my-backend
```

## 参考实现

`plugins/browser/` 下的三个内置提供商是权威示例，按复杂度递增：`firecrawl`（最简单）、`browser_use`，以及 `browserbase`（带 stealth/代理/keep-alive 功能开关，并在付费功能不可用时优雅降级）。挑最接近的那个来复制。

## 检查清单

- [ ] `name` 为小写且保持稳定（这是用户会写进配置的值）
- [ ] `is_available()` 不做任何网络调用
- [ ] `create_session()` 返回完整的元数据契约（`bb_session_id` 键名保持不变）
- [ ] `close_session()` / `emergency_cleanup()` 绝不抛异常
- [ ] `get_setup_schema()` 暴露你的环境变量，以便 `hermes tools` 能配置该后端
- [ ] `plugin.yaml` 声明了 `kind: backend` + `provides_browser_providers`
