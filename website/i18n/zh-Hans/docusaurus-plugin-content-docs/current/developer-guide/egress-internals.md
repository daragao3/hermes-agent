---
sidebar_position: 14
title: "出口代理内部机制"
description: "iron-proxy 出口防火墙如何与 Hermes 集成——模块布局、生命周期、安全不变量以及扩展点"
---

# 出口代理内部机制

本页从贡献者 / 插件作者的角度介绍出口凭据注入防火墙（`hermes egress` / iron-proxy）的架构。面向最终用户的设置与使用文档见 [出口代理](../user-guide/egress/iron-proxy.md)。

威胁模型和高层设计已在用户页面中概述；本页关注的是它*如何*连接起来、与安全相关的代码位于何处，以及如果你改动它，必须保持哪些不变量。

## 模块布局 {#module-layout}

```text
agent/proxy_sources/iron_proxy.py     Core: binary install, CA gen, config build,
                                       subprocess lifecycle, mappings I/O, PID/nonce
                                       defense.  Pure-function surface where possible.

hermes_cli/proxy_cli.py               Wizard + slash command handlers.
                                       `hermes egress {install,setup,start,stop,
                                       status,disable,config}`.  Wires the
                                       core module into argparse.

hermes_cli/subcommands/egress.py:_dispatch_egress
                                       Top-level subparser dispatcher.
                                       dest='egress_command' (intentionally
                                       disjoint from the inbound OAuth
                                       `hermes proxy` subparser, which uses
                                       dest='proxy_command').

hermes_cli/config.py: proxy schema    The `proxy:` block in DEFAULT_CONFIG.
                                       Adding a knob means: add it here, add a
                                       wizard prompt or `setdefault` in
                                       proxy_cli.cmd_setup, and document it
                                       in the user-guide page.

tools/environments/docker.py
  _egress_proxy_args_for_docker()     Builds the volume_args / env_overrides /
                                       host_args triple that the Docker backend
                                       injects when `proxy.enabled: true`.

  DockerEnvironment.__init__          Docker-side merge logic: collision
                                       detection against critical egress vars,
                                       NODE_OPTIONS append-merge via the
                                       _HERMES_EGRESS_NODE_OPTIONS_APPEND
                                       sentinel, enforce_on_docker precedence.

tests/test_iron_proxy.py              Hermetic tests (~70).  Binary install
                                       path, config build, mappings I/O,
                                       subprocess lifecycle, docker arg builder,
                                       deny CIDR defaults, bind policy, CA
                                       TOCTOU, ensure_audit_log behaviour, etc.

tests/test_iron_proxy_cli.py          CLI handler unit tests (~20).  Argparse
                                       wiring, fail-loud paths, BWS refresh
                                       wire-up, dest='egress_command'
                                       regression guard.

tests/test_iron_proxy_e2e.py          Live E2E (gated on HERMES_RUN_E2E=1).
                                       Real iron-proxy binary, real curl,
                                       end-to-end token swap verified.
```

## 生命周期 {#lifecycle}

```text
hermes egress install
  -> agent.proxy_sources.iron_proxy.install_iron_proxy(force=...)
       Downloads pinned tarball + checksums.txt from GitHub Releases.
       SHA-256 verification before extraction.
       tarfile.extract(..., filter="data") on Python 3.12+ (PEP 706);
         falls back to plain extract on older Python with member-name
         sanitisation via _pick_tar_member.
       Stage into ~/.hermes/bin/.iron-proxy_XXXX, chmod 755, os.replace
         to ~/.hermes/bin/iron-proxy (atomic).
       _VERSION_CACHE.pop(target) so a forced reinstall re-probes
         --version on next call.

hermes egress setup [--from-bitwarden | --no-bitwarden] [--rotate-tokens]
  -> proxy_cli.cmd_setup
       Step 1. find_iron_proxy(install_if_missing=False) -> install if absent.
       Step 2. ensure_ca_cert()
                 Run openssl genrsa + req via subprocess.
                 Write CA key via os.open(O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW, 0o600)
                   + os.replace.  Never exists on disk under default umask.
                 Write CA cert with 0o644 (public).
       Step 3. discover_provider_mappings() or pull names from BWS via
                 fetch_bitwarden_secrets() when --from-bitwarden.
                 merge_mappings(existing=load_mappings(), discovered,
                                rotate=args.rotate_tokens) preserves prior
                 tokens unless --rotate-tokens is passed.
                 discover_uncovered_providers() and surface warnings.
       Step 4. ensure_audit_log(audit_log_path)   # raises on OSError
               build_proxy_config(...) with defaults applied at the call site
                 (deny CIDRs default, bind policy from _default_http_listen).
               write_proxy_config(cfg)            # atomic via .tmp + os.replace, 0o600
               write_mappings(mappings)           # atomic, 0o600
       Step 5. proxy_cfg["enabled"] = True; credential_source preservation logic
               (do NOT silently downgrade bitwarden -> env on re-run);
               save_config(cfg).

hermes egress start
  -> proxy_cli.cmd_start
       Pre-checks (refuse-start path):
         - credential_source=bitwarden? -> pre-validate access_token_env + project_id
       -> iron_proxy.start_proxy(
            refresh_secrets_from_bitwarden=...,
            bitwarden_config=...,
          )
            existing=_read_pid(); if alive, idempotent return.
            _build_proxy_subprocess_env(...):  ALLOWLIST + mapped real_env_names,
              strip HTTPS_PROXY/etc. to avoid recursion, optional BWS refresh
              (raises on missing values unless allow_env_fallback=true).
            Plant nonce: _proxy_nonce = sha256(urandom(16)); env[NONCE_ENV] = ...
            Open log_path via O_NOFOLLOW + 0o600 + st_uid check.
            Popen with stdin=DEVNULL, stdout=log_fd, stderr=STDOUT,
              start_new_session=True (POSIX).
            Close parent's log_fd in finally.
            _write_pidfile_safely(pidfile, proc.pid)
              O_EXCL + O_NOFOLLOW + uid check + persisted nonce sidecar.
              FileExistsError -> discriminate live vs stale, retry once if stale.
            Install SIGINT/SIGTERM handlers (main-thread only).
            Poll loop (do-while shape):
              while True:
                if proc.poll() is not None: tail log + unlink pidfile + raise
                if _port_listening(probe_host, tunnel_port): break  # probe_host = configured bind host
                if time.time() >= deadline: break  (do-while: checked AFTER first probe)
                time.sleep(0.1)
            If not listening at exit: _kill_and_wait(proc) + unlink pidfile + raise.

hermes egress stop
  -> iron_proxy.stop_proxy
       _read_pid + _pid_alive guard.
       starttime_before = _pid_proc_starttime(pid)   # Linux only; None elsewhere
       os.kill(pid, SIGTERM)
       Wait up to 5s for graceful exit.
       After grace: re-check starttime + _pid_alive.
         If recycled (starttime drift OR _pid_alive False), DO NOT SIGKILL.
         Otherwise os.kill(pid, _KILL_SIGNAL).
       _cleanup_state_files: unlink pidfile + nonce sibling.
```

## 安全不变量 {#security-invariants}

以下是承重的关键属性。如果你改动该模块，必须保持它们。凡是有回归测试的地方，都已注明测试名称。

### 文件系统权限 {#filesystem-perms}

| 路径 | 模式 | 测试 |
|---|---|---|
| `~/.hermes/proxy/`（目录） | `0o700` | `test_proxy_state_dir_is_0o700` |
| `ca.key` | `0o600` | `test_ca_key_created_with_0o600` |
| `ca.crt` | `0o644` | （隐式；`ensure_ca_cert` 中的 chmod 调用） |
| `proxy.yaml` | `0o600` | （`write_proxy_config` 中原子重命名后执行 chmod） |
| `mappings.json` | `0o600` | （`write_mappings` 中原子重命名后执行 chmod） |
| `iron-proxy.pid` | `0o600` | （`_write_pidfile_safely` 中的 `os.open(..., 0o600)` 模式） |
| `iron-proxy.nonce` | `0o600` | （`_write_pidfile_safely` 中的 `os.open(..., 0o600)` 模式） |
| `audit.log` | `0o600` | `test_ensure_audit_log_creates_with_0o600` |
| `iron-proxy.log` | `0o600` | （`os.open(..., 0o600)` + `fchmod`） |

所有写入路径都使用 `os.open(O_WRONLY | O_CREAT | O_NOFOLLOW, 0o600)` + `os.fstat().st_uid` 检查。禁止使用 `shutil.copy2` + `os.chmod`，因为它会泄露一个默认 umask 下的时间窗口。

### 子进程环境最小化 {#subprocess-env-minimisation}

`_build_proxy_subprocess_env` **绝不能**使用 `os.environ.copy()`。允许列表是 `_PROXY_SUBPROCESS_ENV_ALLOWLIST`（PATH、HOME、locale 等）加上 `load_mappings()` 引用的环境变量名。其余一切都留在宿主机上。

回归测试：`test_subprocess_env_strips_unrelated_secrets`、`test_subprocess_env_strips_proxy_recursion_vars`、`test_subprocess_env_keeps_infrastructure_vars`。

### 绑定策略 {#bind-policy}

`_default_http_listen` 返回一个单元素列表：在 Linux 上是 docker 网桥网关 IP（容器通过 `host.docker.internal:host-gateway` 访问代理，它解析为网桥网关——在那里，绑定到回环地址的话容器内部无法访问）；在 macOS/Windows 的 Docker Desktop 上是回环地址（VPNkit 会把 `host.docker.internal` 路由到宿主机）。在 Linux 上若检测不到 docker0 网桥，则回退到回环地址并给出警告。绝不使用 `0.0.0.0`，绝不使用 `:PORT`（INADDR_ANY）。

`_detect_docker_bridge_ip` 通过 `ipaddress.IPv4Address` 进行校验，并拒绝 `is_unspecified` / `is_loopback` / `is_multicast` / `is_reserved` / `is_link_local` / `is_global`。PATH 上恶意的 `ip` 垫片无法注入 `0.0.0.0`。

**v0.39 的 schema 约束与监听器角色（已针对二进制文件实测验证）：** 二进制文件的 `config.Proxy` 结构体只有单数形式的监听器字段——不存在 `http_listens`（复数）列表。`tunnel_listen` 是 CONNECT + MITM 监听器（`HTTPS_PROXY` 流量到达的地方）；`http_listen` 只处理绝对形式的明文 HTTP 转发（发给它的 CONNECT 会被当作普通请求转发到上游并返回 400）。因此 `build_proxy_config` 将 `tunnel_listen` 绑定在 `tunnel_port` 上，将 `http_listen` 绑定在 `tunnel_port + 1` 上，两者都位于平台对应的绑定主机上。Docker 后端将 `HTTPS_PROXY` 设为 `tunnel_port`，将 `HTTP_PROXY` 设为 `tunnel_port + 1`。

存活探测（`start_proxy` 轮询循环、`get_status`）通过 `_read_http_listen_from_config()` 读取配置的绑定主机，并探测**该**主机——硬编码的回环探测会把一个绑定在网桥上、运行健康的守护进程报告为已停止。

回归测试：`test_default_bind_is_loopback_not_zero_zero`（断言没有 INADDR_ANY，**并且**渲染出的 yaml 中不含 `http_listens`）、`test_default_bind_uses_docker_bridge_on_linux`、`test_default_bind_falls_back_to_loopback_without_bridge`、`test_default_bind_is_loopback_on_macos`、`test_detect_docker_bridge_ip_rejects_dangerous`（参数化覆盖 8 种攻击输入）。

### 指标端口冲突 {#metrics-port-collision}

在 iron-proxy v0.39 中，`metrics.listen` 默认为 `:9090`——与 Hermes 默认的 `tunnel_port: 9090` **是同一个**端口。`build_proxy_config` **必须**显式固定 `metrics.listen: 127.0.0.1:0`，使指标绑定获得一个临时的回环端口，这样无论运维人员选择什么 `tunnel_port`，都不会与代理监听器冲突。

回归测试：`test_metrics_listener_pinned_to_loopback_ephemeral`。

### 默认拒绝的 CIDR {#default-deny-cidrs}

`_DEFAULT_UPSTREAM_DENY_CIDRS` 覆盖回环地址（v4 + v6）、链路本地地址（包括 169.254.169.254 上的 IMDS 及其 IPv4 映射的 v6 形式）、RFC1918、IPv6 ULA、CGNAT 以及 RFC2544 基准测试地址段。`build_proxy_config(..., upstream_deny_cidrs=None)` **必须**输出默认值；只有显式传入空列表才会退出该保护。

回归测试：`test_default_deny_cidrs_present_when_unspecified`、`test_default_deny_includes_ipv4_mapped_v6`。

### 审计日志大声失败 {#audit-log-fail-loud}

`ensure_audit_log` 在遇到任何 `OSError` 时都会抛出 `RuntimeError`。在固定的 v0.39 上，守护进程从不写入该文件（没有 `log.audit_path` 字段），因此 `cmd_setup` 将该失败视为**警告**（在版本升级之前该文件并不承重），并将成功提示行标注为 "reserved"。当固定版本升级到支持 `log.audit_path` 的版本时，需要重新审视：预先创建将成为"从第一个字节起即为 0o600"保证的承重环节，向导也应当重新改为大声失败。

**v0.39 的 schema 约束：** `log.audit_path` 不是 iron-proxy v0.39 `config.Log` 结构体中的字段，因此 `build_proxy_config` 接受 `audit_log` 关键字参数，但**不会**把它输出到渲染的 yaml 中。在 v0.39 上，逐请求记录会与守护进程级事件一起写入 `iron-proxy.log`。`audit.log` 文件仍会以 `0o600` 和 `O_NOFOLLOW` 预先创建，这样当固定版本升级到支持独立日志流的版本时，隐私契约依然成立。

回归测试：`test_ensure_audit_log_raises_on_immutable_parent`、`test_audit_log_kwarg_does_not_inject_audit_path_v039`。

### Bitwarden 模式大声失败 {#bitwarden-mode-fail-loud}

当 `credential_source: bitwarden` **且** `proxy.allow_env_fallback: false`（默认）时：
- 缺少访问令牌环境变量 -> `cmd_start` 拒绝启动。
- 缺少 `project_id` -> `cmd_start` 拒绝启动。
- `bws secret list` 对一个或多个已映射的提供商没有返回值 -> `_build_proxy_subprocess_env` 抛出异常。

在 BW 模式下回退到宿主机环境变量，恰恰会重新引入 BW 路径本来要消除的过期凭据问题。

回归测试：`test_cmd_start_refuses_when_bitwarden_token_missing`（CLI 层）；`_build_proxy_subprocess_env` 中的严格模式断言（守护进程层）。

### docker_env 冲突检测 {#docker_env-collision-detection}

当 `enforce_on_docker: true` 时，如果 `docker_env` 覆盖了任何一个控制出口的变量（HTTPS_PROXY、SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等），**或**任何已映射的 `real_env_name`（OPENROUTER_API_KEY 等），就会在容器启动**之前**抛出 `RuntimeError`。

回归测试：`test_docker_env_collision_with_proxy_raises_when_enforce`。

### PID 复用防御 {#pid-recycling-defense}

`_pid_alive` 在信任 `argv[0]` 基本名称匹配之前，**必须**查询进程内的 `_proxy_nonce`（同一进程的情况）**或**磁盘上的 `iron-proxy.nonce`（跨 CLI 的情况）。`stop_proxy` 在发送 SIGKILL 之前**必须**重新检查 `/proc/<pid>/stat` 中的 starttime，并在 starttime 漂移时抑制该信号。

回归测试：`test_stop_proxy_suppresses_sigkill_on_pid_recycle`、`test_pid_proc_starttime_parses_comm_with_parens`、`test_persisted_nonce_roundtrip`。

### 重新设置时保留令牌 {#token-preservation-on-re-setup}

`merge_mappings(existing, discovered, rotate=False)` **必须**为重叠的提供商返回之前的令牌。重新运行 `hermes egress setup` 不能悄无声息地让正在运行的沙箱遭遇 401。`--rotate-tokens` 是显式的选择加入开关。

回归测试：`test_merge_mappings_preserves_existing_tokens`、`test_merge_mappings_rotate_mints_fresh_tokens`。

### 保留 `credential_source` {#credential_source-preservation}

在没有显式 `--no-bitwarden` 标志的情况下，`cmd_setup` 重新运行时**绝不能**把 `credential_source: bitwarden` 降级为 `env`。运行 `hermes egress setup`（不带标志）会保留之前配置的任何值。

通过 CLI 测试中的 `cmd_setup` 流程进行测试（当 `--from-bitwarden` 之后紧跟一次普通的 `setup` 重新运行时，会执行 bitwarden 保留路径）。

## 扩展点 {#extension-points}

### 添加新的 bearer 令牌提供商 {#adding-a-new-bearer-token-provider}

`iron_proxy.py` 中的 `_BEARER_PROVIDERS` 将环境变量名映射到上游主机元组。添加一个条目后，`discover_provider_mappings()` 就能发现它；当该环境变量存在时，向导会自动为其生成令牌。

```python
_BEARER_PROVIDERS: Dict[str, Tuple[str, ...]] = {
    ...,
    "MY_PROVIDER_API_KEY": ("api.myprovider.com",),
}
```

同时更新 `_DEFAULT_ALLOWED_HOSTS`，使代理默认允许该上游。运行 `test_discover_provider_mappings_*` 进行确认。

### 添加新的请求头令牌提供商（x-api-key 家族） {#adding-a-new-header-token-provider-x-api-key-family}

如果提供商使用静态的**非** Authorization 请求头进行认证（例如 Anthropic 的 `x-api-key`、Azure 的 `api-key` 或 Gemini 的 `x-goog-api-key`），请将其添加到 `_HEADER_AUTH_PROVIDERS`——iron-proxy 的 `secrets.replace.match_headers` 可以针对任意请求头名称，因此这些都是一等的可替换提供商：

```python
_HEADER_AUTH_PROVIDERS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    ...,
    "MY_PROVIDER_API_KEY": {
        "hosts": ("api.myprovider.com",),
        "match_headers": ("x-my-auth-header", "Authorization"),
        "aliases": (),
    },
}
```

`aliases` **只**用于*同一*凭据的可互换环境变量名（例如用 `GOOGLE_API_KEY` 代替 `GEMINI_API_KEY`）——别名会合并为单个映射，因为同一主机上的两条 `require: true` 规则会互相拒绝对方的请求。同时更新 `_DEFAULT_ALLOWED_HOSTS`。

### 添加新的签名认证提供商（不覆盖） {#adding-a-new-signature-auth-provider-uncovered}

如果提供商使用 SigV4 / SDK 生成的 OAuth / 请求签名，静态的请求头替换就无法覆盖它。将该环境变量添加到 `_NON_BEARER_PROVIDERS`，以便向导和 `hermes egress status` 对其发出警告：

```python
_NON_BEARER_PROVIDERS: Tuple[str, ...] = (
    ...,
    "MY_SIGNED_PROVIDER_ACCESS_KEY",
)
```

### 将 iron-proxy 接入非 Docker 后端 {#wiring-iron-proxy-into-a-non-docker-backend}

`_egress_proxy_args_for_docker` 是 Docker 专用的。想要类似接线的后端需要自己实现一个对应物，它需要：

1. 读取 `load_config().get("proxy", {})`；若 `enabled` 为 false，返回空参数。
2. 调用 `iron_proxy.get_status()`；在 `configured` / `pid` / `listening` / `ca_cert_path` 的失败路径上体现 `enforce` 语义。
3. 调用 `iron_proxy.load_mappings()`；若为空**且** `enforce_on_docker: true`，则拒绝挂载。
4. 设置七个环境变量（HTTPS_PROXY、NO_PROXY、REQUESTS_CA_BUNDLE、SSL_CERT_FILE、CURL_CA_BUNDLE、NODE_EXTRA_CA_CERTS、HERMES_EGRESS_PROXY）以及每个映射对应的 `HERMES_PROXY_TOKEN_<NAME>` 变量。
5. 将 CA 证书分发到沙箱中运行时会信任的路径（通常是 `/etc/ssl/certs/hermes-egress-ca.crt`）。
6. 针对用户特定于该后端的环境变量配置实现冲突检测。

Docker 的实现约 150 行；Modal / Daytona / SSH 的实现预计体量相近。

### 订阅逐请求审计事件 {#subscribing-to-per-request-audit-events}

在当前固定的 v0.39 上，iron-proxy 将按行分隔的 JSON 写入 `~/.hermes/proxy/iron-proxy.log`（守护进程记录与逐请求记录合在一起；见用户指南中的"iron-proxy v0.39 上的日志"）。插件 / 外部监视器可以 tail 该文件，并对允许列表拒绝、密钥替换或上游错误作出响应。当固定版本升级到支持 `log.audit_path` 的版本时，逐请求日志流会迁移到 `audit.log`，接在该路径上的监视器无需运维操作即可生效。schema 文档见 [docs.iron.sh/audit](https://docs.iron.sh/audit)（链接）。

## 测试 {#testing}

```bash
# 封闭测试套件（无网络，无真实二进制文件）
scripts/run_tests.sh tests/test_iron_proxy.py tests/test_iron_proxy_cli.py

# 实时 E2E（真实二进制文件、真实 curl、真实 CONNECT 隧道）
HERMES_RUN_E2E=1 scripts/run_tests.sh tests/test_iron_proxy_e2e.py

# 针对 `hermes egress` 的实时 PTY 冒烟测试
HERMES_HOME=/tmp/hermes-egress-test python3 -m hermes_cli.main egress --help
HERMES_HOME=/tmp/hermes-egress-test python3 -m hermes_cli.main egress setup --help
```

CLI 使用 argparse，因此 `--help` 是检查"我的新 flag 是否正确注册"的良好初步探测手段。

## 另请参阅 {#see-also}

- 面向用户的设置与故障排查：[出口代理](https://hermes-agent.nousresearch.com/docs/user-guide/egress/iron-proxy)
- Docker 后端内部机制：[Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- Bitwarden Secrets Manager 集成：[`hermes secrets bitwarden`](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/bitwarden)
- CLI 命令参考：[`hermes egress`](https://hermes-agent.nousresearch.com/docs/reference/cli-commands#hermes-egress)
- 注入沙箱的环境变量：[出口代理（注入沙箱）](https://hermes-agent.nousresearch.com/docs/reference/environment-variables#egress-proxy-sandbox-injected)
