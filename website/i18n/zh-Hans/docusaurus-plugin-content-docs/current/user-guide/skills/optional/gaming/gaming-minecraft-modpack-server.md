---
title: "Minecraft Modpack Server —— 托管模组版 Minecraft 服务器（CurseForge、Modrinth）"
sidebar_label: "Minecraft Modpack Server"
description: "托管模组版 Minecraft 服务器（CurseForge、Modrinth）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Minecraft Modpack Server

托管模组版 Minecraft 服务器（CurseForge、Modrinth）。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 —— 通过 `hermes skills install official/gaming/minecraft-modpack-server` 安装 |
| 路径 | `optional-skills/gaming/minecraft-modpack-server` |
| 平台 | linux, macos |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Minecraft 模组整合包服务器搭建

## 何时使用
- 用户想用一个服务端整合包 zip 搭建模组版 Minecraft 服务器
- 用户需要 NeoForge/Forge 服务器配置方面的帮助
- 用户询问 Minecraft 服务器性能调优或备份相关问题

## 先收集用户偏好
开始搭建之前，先向用户询问：
- **服务器名称 / MOTD** —— 在服务器列表中应该显示什么？
- **种子** —— 指定种子还是随机？
- **难度** —— 和平 / 简单 / 普通 / 困难？
- **游戏模式** —— 生存 / 创造 / 冒险？
- **正版验证（online mode）** —— true（Mojang 验证、正版账号）还是 false（适合局域网/离线）？
- **玩家人数** —— 预计多少玩家？（影响内存与视距调优）
- **内存分配** —— 或者让 agent 根据模组数量与可用内存决定？
- **视距 / 模拟距离** —— 或者让 agent 根据玩家人数与硬件决定？
- **PvP** —— 开还是关？
- **白名单** —— 开放服务器还是仅白名单？
- **备份** —— 需要自动备份吗？多久一次？

如果用户无所谓，就使用合理的默认值，但在生成配置前一定要先问。

## 步骤

### 1. 下载并检查整合包
```bash
mkdir -p ~/minecraft-server
cd ~/minecraft-server
wget -O serverpack.zip "<URL>"
unzip -o serverpack.zip -d server
ls server/
```
查找：`startserver.sh`、安装器 jar（neoforge/forge）、`user_jvm_args.txt`、`mods/` 文件夹。
检查脚本以确定：模组加载器类型、版本以及所需的 Java 版本。

### 2. 安装 Java
- Minecraft 1.21+ → Java 21：`sudo apt install openjdk-21-jre-headless`
- Minecraft 1.18-1.20 → Java 17：`sudo apt install openjdk-17-jre-headless`
- Minecraft 1.16 及以下 → Java 8：`sudo apt install openjdk-8-jre-headless`
- 验证：`java -version`

### 3. 安装模组加载器
大多数服务端整合包都自带安装脚本。使用 INSTALL_ONLY 环境变量来只安装、不启动：
```bash
cd ~/minecraft-server/server
ATM10_INSTALL_ONLY=true bash startserver.sh
# 通用 Forge 整合包则用：
# java -jar forge-*-installer.jar --installServer
```
这会下载依赖库、给服务端 jar 打补丁等。

### 4. 接受 EULA
```bash
echo "eula=true" > ~/minecraft-server/server/eula.txt
```

### 5. 配置 server.properties
面向模组/局域网的关键设置：
```properties
motd=\u00a7b\u00a7lServer Name \u00a7r\u00a78| \u00a7aModpack Name
server-port=25565
online-mode=true          # 局域网且不做 Mojang 验证时设为 false
enforce-secure-profile=true  # 与 online-mode 保持一致
difficulty=hard            # 多数整合包按困难难度做平衡
allow-flight=true          # 模组版必需（飞行坐骑/物品）
spawn-protection=0         # 让所有人都能在出生点建造
max-tick-time=180000       # 模组版需要更长的 tick 超时
enable-command-block=true
```

性能设置（按硬件调整）：
```properties
# 2 名玩家、性能强劲的机器：
view-distance=16
simulation-distance=10

# 4-6 名玩家、中等配置机器：
view-distance=10
simulation-distance=6

# 8 名以上玩家或较弱硬件：
view-distance=8
simulation-distance=4
```

### 6. 调整 JVM 参数（user_jvm_args.txt）
按玩家数量与模组数量调整内存。模组版的经验法则：
- 100-200 个模组：6-12GB
- 200-350+ 个模组：12-24GB
- 至少给操作系统/其他任务留出 8GB

```
-Xms12G
-Xmx24G
-XX:+UseG1GC
-XX:+ParallelRefProcEnabled
-XX:MaxGCPauseMillis=200
-XX:+UnlockExperimentalVMOptions
-XX:+DisableExplicitGC
-XX:+AlwaysPreTouch
-XX:G1NewSizePercent=30
-XX:G1MaxNewSizePercent=40
-XX:G1HeapRegionSize=8M
-XX:G1ReservePercent=20
-XX:G1HeapWastePercent=5
-XX:G1MixedGCCountTarget=4
-XX:InitiatingHeapOccupancyPercent=15
-XX:G1MixedGCLiveThresholdPercent=90
-XX:G1RSetUpdatingPauseTimePercent=5
-XX:SurvivorRatio=32
-XX:+PerfDisableSharedMem
-XX:MaxTenuringThreshold=1
```

### 7. 开放防火墙
```bash
sudo ufw allow 25565/tcp comment "Minecraft Server"
```
用以下命令检查：`sudo ufw status | grep 25565`

### 8. 创建启动脚本
```bash
cat > ~/start-minecraft.sh << 'EOF'
#!/bin/bash
cd ~/minecraft-server/server
java @user_jvm_args.txt @libraries/net/neoforged/neoforge/<VERSION>/unix_args.txt nogui
EOF
chmod +x ~/start-minecraft.sh
```
注意：对于 Forge（而非 NeoForge），参数文件路径不同。请查看 `startserver.sh` 获取确切路径。

### 9. 设置自动备份
创建备份脚本：
```bash
cat > ~/minecraft-server/backup.sh << 'SCRIPT'
#!/bin/bash
SERVER_DIR="$HOME/minecraft-server/server"
BACKUP_DIR="$HOME/minecraft-server/backups"
WORLD_DIR="$SERVER_DIR/world"
MAX_BACKUPS=24
mkdir -p "$BACKUP_DIR"
[ ! -d "$WORLD_DIR" ] && echo "[BACKUP] No world folder" && exit 0
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_FILE="$BACKUP_DIR/world_${TIMESTAMP}.tar.gz"
echo "[BACKUP] Starting at $(date)"
tar -czf "$BACKUP_FILE" -C "$SERVER_DIR" world
SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[BACKUP] Saved: $BACKUP_FILE ($SIZE)"
BACKUP_COUNT=$(ls -1t "$BACKUP_DIR"/world_*.tar.gz 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    REMOVE=$((BACKUP_COUNT - MAX_BACKUPS))
    ls -1t "$BACKUP_DIR"/world_*.tar.gz | tail -n "$REMOVE" | xargs rm -f
    echo "[BACKUP] Pruned $REMOVE old backup(s)"
fi
echo "[BACKUP] Done at $(date)"
SCRIPT
chmod +x ~/minecraft-server/backup.sh
```

添加每小时执行的 cron：
```bash
(crontab -l 2>/dev/null | grep -v "minecraft/backup.sh"; echo "0 * * * * $HOME/minecraft-server/backup.sh >> $HOME/minecraft-server/backups/backup.log 2>&1") | crontab -
```

## 陷阱
- 模组版**务必**设置 `allow-flight=true` —— 否则带喷气背包/飞行的模组会把玩家踢出去
- `max-tick-time=180000` 或更高 —— 模组服务器在世界生成时经常出现长 tick
- 首次启动很慢（大整合包要好几分钟）—— 不要慌
- 首次启动时的 "Can't keep up!" 警告是正常的，初始区块生成完成后就会稳定
- 如果 online-mode=false，也要把 enforce-secure-profile 设为 false，否则客户端会被拒绝
- 整合包自带的 startserver.sh 通常带有自动重启循环 —— 请另写一个不含该循环的干净启动脚本
- 删除 world/ 文件夹即可用新种子重新生成世界
- 部分整合包提供环境变量来控制行为（例如 ATM10 使用 ATM10_JAVA、ATM10_RESTART、ATM10_INSTALL_ONLY）

## 验证
- 用 `pgrep -fa neoforge` 或 `pgrep -fa minecraft` 检查是否在运行
- 查看日志：`tail -f ~/minecraft-server/server/logs/latest.log`
- 日志中出现 "Done (Xs)!" 即表示服务器已就绪
- 测试连接：玩家在多人游戏中添加服务器 IP
