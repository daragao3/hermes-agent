---
title: "Hermes S6 Container Supervision"
sidebar_label: "Hermes S6 Container Supervision"
description: "修改、调试或扩展 Hermes Agent Docker 镜像内的 s6-overlay 监督树 —— 添加新服务、调试 profile gateway、理解……"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Hermes S6 Container Supervision

修改、调试或扩展 Hermes Agent Docker 镜像内的 s6-overlay 监督树 —— 添加新服务、调试
profile gateway、理解 Architecture B 主程序模式。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 使用 `hermes skills install official/devops/hermes-s6-container-supervision` 安装 |
| 路径 | `optional-skills/devops/hermes-s6-container-supervision` |
| 版本 | `1.0.0` |
| 作者 | Hermes Agent |
| 许可证 | MIT |
| 平台 | linux |
| 标签 | `docker`, `s6`, `supervision`, `gateway`, `profiles` |
| 相关 skills | [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent), `hermes-agent-dev` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Hermes s6-overlay 容器监督

## 何时使用此 skill

当你在处理以下工作时加载此 skill：
- 在 Hermes Docker 镜像中添加或移除一个静态服务（某个应在每次容器启动时都被监督的东西，
  比如 dashboard）
- 诊断为何某个按 profile 的 gateway 没有启动、重启，或没能在 `docker restart` 后存活
- 理解为何容器的 CMD 是 `/opt/hermes/docker/main-wrapper.sh`，以及以短横线开头的参数如何
  抵达用户的程序
- 修改 `cont-init.d` 启动脚本（UID 重映射、卷播种、profile 协调）
- 更改按 profile 的 gateway 的渲染后 run 脚本（阶段 4）

如果你只是运行 Hermes Agent 并想使用 Docker，请改看 `website/docs/user-guide/docker.md`。

## 架构一览

<!-- ascii-guard-ignore -->
```
/init                                  ← PID 1（s6-overlay v3.2.3.0）
├── cont-init.d                        ← 一次性设置，以 root 运行
│   ├── 01-hermes-setup                ← docker/stage2-hook.sh
│   │   ├── UID/GID 重映射
│   │   ├── chown /opt/data
│   │   ├── chown /opt/data/profiles（每次启动）
│   │   ├── 播种 .env / config.yaml / SOUL.md
│   │   └── skills_sync.py
│   └── 02-reconcile-profiles          ← hermes_cli.container_boot
│       ├── chown /run/service（hermes 可写，用于运行时注册）
│       └── 遍历 $HERMES_HOME/profiles/<name>/gateway_state.json
│           → 重建 /run/service/gateway-<name>/
│           → 仅自动启动 prior_state == "running" 的那些
│
├── s6-rc.d（静态服务，位于 /etc/s6-overlay/s6-rc.d/）
│   ├── main-hermes/run                ← exec sleep infinity（空操作槽）
│   └── dashboard/run                  ← 若 HERMES_DASHBOARD=1，运行 `hermes dashboard`
│
├── /run/service（s6-svscan 监视；tmpfs）
│   ├── gateway-coder/                 ← 运行时按 profile 注册
│   │   ├── type        （"longrun"）
│   │   ├── run         （"#!/command/with-contenv sh ... exec s6-setuidgid hermes hermes -p coder gateway run"）
│   │   ├── down        （标记 —— 存在即表示"已注册但不自动启动"）
│   │   └── log/run     （s6-log → $HERMES_HOME/logs/gateways/coder/current）
│   └── ...
│
└── CMD（"主程序"）               ← /opt/hermes/docker/main-wrapper.sh
    └── 路由用户参数：裸 exec | hermes 子命令 | hermes（无参数）
        —— 由 /init exec，继承 stdin/stdout/stderr（--tui 时为 TTY）
```
<!-- ascii-guard-ignore-end -->

## 关键文件

| 路径 | 角色 |
|---|---|
| `Dockerfile` | s6-overlay 安装 + cont-init.d 接线 + `ENTRYPOINT ["/init", "/opt/hermes/docker/main-wrapper.sh"]` |
| `docker/stage2-hook.sh` | "旧入口点逻辑" —— UID 重映射、chown、播种、skills 同步。作为 cont-init.d/01-hermes-setup 运行。 |
| `docker/cont-init.d/02-reconcile-profiles` | 每次启动时调用 `hermes_cli.container_boot`，从持久卷恢复 profile gateway 槽。 |
| `docker/main-wrapper.sh` | 容器的 CMD。路由用户参数，通过 `s6-setuidgid` 降权到 hermes，exec 所选程序。 |
| `docker/s6-rc.d/main-hermes/run` | 空操作 `sleep infinity` —— 槽存在是为了让 s6-rc user bundle 有效；主 hermes 作为 CMD 运行，而非作为受监督的服务。 |
| `docker/s6-rc.d/dashboard/run` | 条件服务 —— 除非 `HERMES_DASHBOARD` 为真，否则 `exec sleep infinity`。 |
| `docker/entrypoint.sh` | 向后兼容垫片，`exec` stage2 hook。硬编码了旧入口点路径的外部脚本仍可用。 |
| `hermes_cli/service_manager.py` | `S6ServiceManager`：`register_profile_gateway`、`unregister_profile_gateway`、`start/stop/restart/is_running`、`list_profile_gateways`。 |
| `hermes_cli/container_boot.py` | `reconcile_profile_gateways()` —— 遍历持久 profile，重新生成 s6 槽，输出 `container-boot.log`。 |
| `hermes_cli/gateway.py::_dispatch_via_service_manager_if_s6` | 拦截 `hermes gateway start/stop/restart`，在容器中运行时路由到 s6。 |

## 为何采用 Architecture B（CMD 作为主程序，而非受 s6 监督）

最初的计划（v1–v3）要求主 hermes 作为受监督的 s6-rc 服务运行。两个真实的 s6-overlay v3
机制阻碍了这一点：

1. **cont-init.d 脚本收不到 CMD 参数** —— 因此 stage2 hook 无法解析
   `docker run <image> chat -q "hi"` 来为某个服务 `run` 脚本设置 `HERMES_ARGS` 以供消费。
2. **`/run/s6/basedir/bin/halt` 不会传播**写入 `/run/s6-linux-init-container-results/exitcode`
   的退出码。无论如何容器总是以 143（SIGTERM）退出。已由 skarnet（s6 作者）在
   [issue #477](https://github.com/just-containers/s6-overlay/issues/477) 中确认：
   _"if you want a container shutdown, you need to either have your CMD exit, or, if you
   have no CMD, write the container exit code you want then call halt"_。

因此我们采用 s6-overlay 原生的 CMD 模式：`ENTRYPOINT ["/init",
"/opt/hermes/docker/main-wrapper.sh"]`。/init 会自动把 wrapper 前置到用户参数之前 ——
所以 `docker run <image> --version` 变成 `/init main-wrapper.sh --version`，且 `--version`
不会被 /init 的 POSIX shell 拦截。wrapper 通过 `s6-setuidgid` 降权到 hermes，然后 exec 所选
程序。程序的退出码成为容器退出码，与 s6 之前的 tini 契约完全一致。

权衡：主 hermes 在 s6 下不受监督。这恰好与它在 tini 下（s6 之前的镜像）的行为一致。
Dashboard 监督是唯一的**新**保证 —— 而 `/run/service/` 下按 profile 的 gateway 获得完整
监督。

## 快速食谱

### 验证 s6 在运行中的容器里是 PID 1

```sh
docker exec <c> sh -c 'cat /proc/1/comm; readlink /proc/1/exe'
# 预期：s6-svscan 或 init / /package/admin/s6/.../s6-svscan
```

### 检查某个 profile gateway 服务

```sh
# /command/ 不在 docker-exec 的 PATH 上 —— 使用绝对路径
docker exec <c> /command/s6-svstat /run/service/gateway-<name>
# "up (pid …) … seconds"            → 运行中
# "down (exitcode N) … seconds, normally up, want up, …" → s6 想让它起来但进程不断退出（崩溃循环）
# "down … normally up, ready …"     → 用户已停止它
```

### 手动拉起/放下某个服务

```sh
docker exec <c> /command/s6-svc -u /run/service/gateway-<name>   # 起来
docker exec <c> /command/s6-svc -d /run/service/gateway-<name>   # 放下
docker exec <c> /command/s6-svc -t /run/service/gateway-<name>   # SIGTERM（重启）
```

### 查看 cont-init 协调器日志

```sh
docker exec <c> tail -n 50 /opt/data/logs/container-boot.log
# 2026-05-21T06:18:05+0000 profile=coder prior_state=running action=started
# 2026-05-21T06:18:05+0000 profile=writer prior_state=stopped action=registered
```

### 添加一个新的静态服务

1. 创建 `docker/s6-rc.d/<name>/type`，内容为 `longrun\n`，以及 `docker/s6-rc.d/<name>/run`
   （使用 `#!/command/with-contenv sh` + `# shellcheck shell=sh`）。
2. 在 run 顶部通过 `s6-setuidgid hermes` 降权到 hermes（除非你确实需要 root）。
3. 创建空的 `docker/s6-rc.d/<name>/dependencies.d/base`，使其等待 base bundle。
4. 创建空的 `docker/s6-rc.d/user/contents.d/<name>`，使其加入 user bundle。
5. Dockerfile 中的 `COPY docker/s6-rc.d/` 会自动拾取它 —— 无需其他更改。

### 更改按 profile 的 gateway run 命令

编辑 `hermes_cli/service_manager.py` 中的 `S6ServiceManager._render_run_script`。该函数在
启动协调期间也会被 `hermes_cli/container_boot.py::_register_service` 调用，因此它是唯一的
真相来源。更新 `tests/hermes_cli/test_service_manager.py::test_s6_register_creates_service_dir_and_triggers_scan`
中对应的断言。

### 运行 docker 测试工具集

```sh
docker build -t hermes-agent-harness:latest .
HERMES_TEST_IMAGE=hermes-agent-harness:latest scripts/run_tests.sh tests/docker/ -v
# 针对 s6 镜像预期 19 passed, 0 xfailed
```

该工具集位于 `tests/docker/`，在 Docker 不可用时跳过。每测试超时被提高到 180s
（见 `tests/docker/conftest.py`）。

## 常见陷阱

### 通过 `docker exec` 出现 "command not found"

`/command/`（s6-overlay 放置其二进制文件之处）仅对由监督树派生的进程 —— 服务、
cont-init.d、main-wrapper.sh —— 在 PATH 上。`docker exec <c> s6-svstat …` 会以
"command not found" 失败；始终使用绝对路径 `/command/s6-svstat`。`hermes` 二进制之所以可用，
是因为 Dockerfile 把 `/opt/hermes/.venv/bin` 加进了运行时 `ENV PATH`。

### profile 目录所有权

cont-init 协调器以 hermes 运行（`02-reconcile-profiles` 中的 `s6-setuidgid hermes`）。如果
某个 profile 目录最终归 root 所有（例如因为 `docker exec <c> hermes profile create …`
默认以 root 运行），协调器将无法读取 SOUL.md 并以 `PermissionError` 失败。缓解措施：
`stage2-hook.sh` 在**每次**启动时幂等地把 `$HERMES_HOME/profiles` chown 给 hermes。不要
移除那个代码块。

### 由 `docker exec` 写入的文件归 root 所有

`docker exec` 默认以 root 运行。要么传入 `--user hermes`，要么依赖下次重启时的 stage2
chown 扫描。不要手动以 root 在 `$HERMES_HOME/profiles/<name>/` 下写文件 —— 下一次协调
会清扫它们，但进行中的操作可能会遇到权限错误。

### 服务槽存在但 s6-svstat 说 "s6-supervise not running"

服务目录位于 tmpfs 上，在容器重启时被清除。要么 cont-init 协调器尚未运行
（`docker restart` 后给它一点时间），要么它失败了。检查
`docker logs <c> | grep '02-reconcile'`。

### Gateway 启动后立即退出（svstat 中的 `down (exitcode 1)`）

最可能是该 profile 未配置模型或认证。服务槽是正确的 —— 是 gateway 本身未配置。先运行
`hermes -p <profile> setup`。s6 监督者会不断重启它；这是期望的行为（当你修好配置后，下一次
尝试会成功并保持在线）。

### 协调器跳过了某个 profile

协调器以 **`SOUL.md` 的存在**作为"真实 profile"标记的键。`hermes profile create` 总会播种
它。如果某个 profile 目录缺少 SOUL.md（散落目录、部分恢复、备份进行中），协调器会有意跳过
它。添加一个 `SOUL.md`（哪怕是空的）以重新加入。

### "救命，容器退出 143！"

检查是否有东西在调用 `s6-svscanctl -t` 或 `/run/s6/basedir/bin/halt` —— 两者都会导致 /init
开始第 3 阶段关闭，但返回 143（SIGTERM）而非期望的退出码。这就是 Phase 2 从 A 到 B 的架构
转向。要以真实退出码关闭容器，你必须让 CMD（main-wrapper.sh）正常退出；**不要**试图从
finish 脚本控制退出。

## 相关 skills

- `hermes-agent-dev`：通用 hermes-agent 代码库导航
- `hermes-tool-quirks`：具体的 Hermes 工具变通方法（sed/grep/等）—— 在调试 s6 栈与 hermes
  内置工具的交互时加载。
