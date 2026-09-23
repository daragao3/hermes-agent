---
title: "Ascii Art — ASCII 艺术：pyfiglet、cowsay、boxes、图片转 ASCII"
sidebar_label: "Ascii Art"
description: "ASCII 艺术：pyfiglet、cowsay、boxes、图片转 ASCII"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ascii Art

ASCII 艺术：pyfiglet、cowsay、boxes、图片转 ASCII。

## Skill 元数据 {#skill-metadata}

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/creative/ascii-art` 安装 |
| 路径 | `optional-skills/creative/ascii-art` |
| 版本 | `4.0.0` |
| 作者 | 0xbyt4, Hermes Agent |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `ASCII`, `Art`, `Banners`, `Creative`, `Unicode`, `Text-Art`, `pyfiglet`, `figlet`, `cowsay`, `boxes` |
| 相关 skill | [`excalidraw`](/user-guide/skills/optional/creative/creative-excalidraw) |

## 参考：完整 SKILL.md {#reference-full-skillmd}

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# ASCII Art Skill

针对不同 ASCII 艺术需求的多种工具。所有工具都是本地 CLI 程序或免费的 REST API——无需 API 密钥。

## 工具 1：文字横幅（pyfiglet —— 本地） {#tool-1-text-banners-pyfiglet--local}

将文字渲染为大号 ASCII 艺术横幅。内置 571 种字体。

### 安装 {#setup}

```bash
pip install pyfiglet --break-system-packages -q
```

### 用法 {#usage}

```bash
python -m pyfiglet "YOUR TEXT" -f slant
python -m pyfiglet "TEXT" -f doom -w 80    # 设置宽度
python -m pyfiglet --list_fonts             # 列出全部 571 种字体
```

### 推荐字体 {#recommended-fonts}

| 风格 | 字体 | 最适合 |
|-------|------|----------|
| 简洁现代 | `slant` | 项目名、标题 |
| 粗犷方块 | `doom` | 标题、logo |
| 大而易读 | `big` | 横幅 |
| 经典横幅 | `banner3` | 宽屏显示 |
| 紧凑 | `small` | 副标题 |
| 赛博朋克 | `cyberlarge` | 科技主题 |
| 3D 效果 | `3-d` | 启动画面 |
| 哥特 | `gothic` | 戏剧性文字 |

### 提示 {#tips}

- 预览 2-3 种字体，让用户挑选最喜欢的
- 短文本（1-8 个字符）配合 `doom` 或 `block` 这类细节丰富的字体效果最好
- 长文本更适合 `small` 或 `mini` 这类紧凑字体

## 工具 2：文字横幅（asciified API —— 远程，无需安装） {#tool-2-text-banners-asciified-api--remote-no-install}

将文字转换为 ASCII 艺术的免费 REST API。250+ 种 FIGlet 字体。直接返回纯文本——无需解析。在未安装 pyfiglet 时使用，或作为快速替代方案。

### 用法（通过终端 curl） {#usage-via-terminal-curl}

```bash
# 基本文字横幅（默认字体）
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello+World"

# 指定字体
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Slant"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Doom"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Star+Wars"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=3-D"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Banner3"

# 列出所有可用字体（返回 JSON 数组）
curl -s "https://asciified.thelicato.io/api/v2/fonts"
```

### 提示 {#tips-1}

- 在 text 参数中将空格 URL 编码为 `+`
- 响应是纯文本 ASCII 艺术——没有 JSON 包装，可直接显示
- 字体名称区分大小写；使用 fonts 端点获取确切名称
- 在任何带有 curl 的终端中都能使用——无需 Python 或 pip

## 工具 3：Cowsay（消息艺术） {#tool-3-cowsay-message-art}

经典工具，用一个 ASCII 角色加对话气泡包裹文字。

### 安装 {#setup-1}

```bash
sudo apt install cowsay -y    # Debian/Ubuntu
# brew install cowsay         # macOS
```

### 用法 {#usage-1}

```bash
cowsay "Hello World"
cowsay -f tux "Linux rules"       # 企鹅 Tux
cowsay -f dragon "Rawr!"          # 龙
cowsay -f stegosaurus "Roar!"     # 剑龙
cowthink "Hmm..."                  # 思考气泡
cowsay -l                          # 列出所有角色
```

### 可用角色（50+） {#available-characters-50}

`beavis.zen`, `bong`, `bunny`, `cheese`, `daemon`, `default`, `dragon`,
`dragon-and-cow`, `elephant`, `eyes`, `flaming-skull`, `ghostbusters`,
`hellokitty`, `kiss`, `kitty`, `koala`, `luke-koala`, `mech-and-cow`,
`meow`, `moofasa`, `moose`, `ren`, `sheep`, `skeleton`, `small`,
`stegosaurus`, `stimpy`, `supermilker`, `surgery`, `three-eyes`,
`turkey`, `turtle`, `tux`, `udder`, `vader`, `vader-koala`, `www`

### 眼睛/舌头修饰符 {#eyetongue-modifiers}

```bash
cowsay -b "Borg"       # =_= 眼睛
cowsay -d "Dead"       # x_x 眼睛
cowsay -g "Greedy"     # $_$ 眼睛
cowsay -p "Paranoid"   # @_@ 眼睛
cowsay -s "Stoned"     # *_* 眼睛
cowsay -w "Wired"      # O_O 眼睛
cowsay -e "OO" "Msg"   # 自定义眼睛
cowsay -T "U " "Msg"   # 自定义舌头
```

## 工具 4：Boxes（装饰边框） {#tool-4-boxes-decorative-borders}

在任意文字周围绘制装饰性的 ASCII 艺术边框/画框。内置 70+ 种设计。

### 安装 {#setup-2}

```bash
sudo apt install boxes -y    # Debian/Ubuntu
# brew install boxes         # macOS
```

### 用法 {#usage-2}

```bash
echo "Hello World" | boxes                    # 默认边框
echo "Hello World" | boxes -d stone           # 石头边框
echo "Hello World" | boxes -d parchment       # 羊皮纸卷轴
echo "Hello World" | boxes -d cat             # 猫边框
echo "Hello World" | boxes -d dog             # 狗边框
echo "Hello World" | boxes -d unicornsay      # 独角兽
echo "Hello World" | boxes -d diamonds        # 菱形图案
echo "Hello World" | boxes -d c-cmt           # C 风格注释
echo "Hello World" | boxes -d html-cmt        # HTML 注释
echo "Hello World" | boxes -a c               # 文字居中
boxes -l                                       # 列出全部 70+ 种设计
```

### 与 pyfiglet 或 asciified 组合使用 {#combine-with-pyfiglet-or-asciified}

```bash
python -m pyfiglet "HERMES" -f slant | boxes -d stone
# 或者在未安装 pyfiglet 时：
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=HERMES&font=Slant" | boxes -d stone
```

## 工具 5：TOIlet（彩色文字艺术） {#tool-5-toilet-colored-text-art}

类似 pyfiglet，但带有 ANSI 颜色效果和视觉滤镜。非常适合终端里的视觉点缀。

### 安装 {#setup-3}

```bash
sudo apt install toilet toilet-fonts -y    # Debian/Ubuntu
# brew install toilet                      # macOS
```

### 用法 {#usage-3}

```bash
toilet "Hello World"                    # 基本文字艺术
toilet -f bigmono12 "Hello"            # 指定字体
toilet --gay "Rainbow!"                 # 彩虹着色
toilet --metal "Metal!"                 # 金属效果
toilet -F border "Bordered"             # 添加边框
toilet -F border --gay "Fancy!"         # 组合效果
toilet -f pagga "Block"                 # 方块风格字体（toilet 独有）
toilet -F list                          # 列出可用滤镜
```

### 滤镜 {#filters}

`crop`, `gay`（彩虹）, `metal`, `flip`, `flop`, `180`, `left`, `right`, `border`

**注意**：toilet 使用 ANSI 转义码输出颜色——在终端中有效，但可能无法在所有场景中正确渲染（例如纯文本文件、部分聊天平台）。

## 工具 6：图片转 ASCII 艺术 {#tool-6-image-to-ascii-art}

将图片（PNG、JPEG、GIF、WEBP）转换为 ASCII 艺术。

### 方式 A：ascii-image-converter（推荐，现代） {#option-a-ascii-image-converter-recommended-modern}

```bash
# 安装
sudo snap install ascii-image-converter
# 或者：go install github.com/TheZoraiz/ascii-image-converter@latest
```

```bash
ascii-image-converter image.png                  # 基本用法
ascii-image-converter image.png -C               # 彩色输出
ascii-image-converter image.png -d 60,30         # 设置尺寸
ascii-image-converter image.png -b               # 盲文字符
ascii-image-converter image.png -n               # 负片/反色
ascii-image-converter https://url/image.jpg      # 直接使用 URL
ascii-image-converter image.png --save-txt out   # 保存为文本
```

### 方式 B：jp2a（轻量，仅支持 JPEG） {#option-b-jp2a-lightweight-jpeg-only}

```bash
sudo apt install jp2a -y
jp2a --width=80 image.jpg
jp2a --colors image.jpg              # 彩色化
```

## 工具 7：搜索现成的 ASCII 艺术 {#tool-7-search-pre-made-ascii-art}

从网上搜索精选的 ASCII 艺术。使用 `terminal` 配合 `curl`。

### 来源 A：ascii.co.uk（推荐用于现成作品） {#source-a-asciicouk-recommended-for-pre-made-art}

按主题整理的大量经典 ASCII 艺术。作品位于 HTML `<pre>` 标签内。用 curl 获取页面，再用一小段 Python 代码提取作品。

**URL 模式：** `https://ascii.co.uk/art/{subject}`

**第 1 步 —— 获取页面：**

```bash
curl -s 'https://ascii.co.uk/art/cat' -o /tmp/ascii_art.html
```

**第 2 步 —— 从 pre 标签中提取作品：**

```python
import re, html
with open('/tmp/ascii_art.html') as f:
    text = f.read()
arts = re.findall(r'<pre[^>]*>(.*?)</pre>', text, re.DOTALL)
for art in arts:
    clean = re.sub(r'<[^>]+>', '', art)
    clean = html.unescape(clean).strip()
    if len(clean) > 30:
        print(clean)
        print('\n---\n')
```

**可用主题**（用作 URL 路径）：
- 动物：`cat`, `dog`, `horse`, `bird`, `fish`, `dragon`, `snake`, `rabbit`, `elephant`, `dolphin`, `butterfly`, `owl`, `wolf`, `bear`, `penguin`, `turtle`
- 物品：`car`, `ship`, `airplane`, `rocket`, `guitar`, `computer`, `coffee`, `beer`, `cake`, `house`, `castle`, `sword`, `crown`, `key`
- 自然：`tree`, `flower`, `sun`, `moon`, `star`, `mountain`, `ocean`, `rainbow`
- 角色：`skull`, `robot`, `angel`, `wizard`, `pirate`, `ninja`, `alien`
- 节日：`christmas`, `halloween`, `valentine`

**提示：**
- 保留作者签名/缩写——这是重要的礼仪
- 每个页面有多幅作品——为用户挑选最好的一幅
- 通过 curl 可稳定使用，无需 JavaScript

### 来源 B：GitHub Octocat API（有趣的彩蛋） {#source-b-github-octocat-api-fun-easter-egg}

返回一只随机的 GitHub Octocat 和一句智慧语录。无需认证。

```bash
curl -s https://api.github.com/octocat
```

## 工具 8：有趣的 ASCII 小工具（通过 curl） {#tool-8-fun-ascii-utilities-via-curl}

这些免费服务直接返回 ASCII 艺术——很适合作为有趣的附加内容。

### 以 ASCII 艺术呈现的二维码 {#qr-codes-as-ascii-art}

```bash
curl -s "qrenco.de/Hello+World"
curl -s "qrenco.de/https://example.com"
```

### 以 ASCII 艺术呈现的天气 {#weather-as-ascii-art}

```bash
curl -s "wttr.in/London"          # 带 ASCII 图形的完整天气报告
curl -s "wttr.in/Moon"            # ASCII 艺术形式的月相
curl -s "v2.wttr.in/London"       # 详细版本
```

## 工具 9：LLM 生成的自定义艺术（后备） {#tool-9-llm-generated-custom-art-fallback}

当以上工具都无法满足需求时，使用下列 Unicode 字符直接生成 ASCII 艺术：

### 字符调色板 {#character-palette}

**制表符：** `╔ ╗ ╚ ╝ ║ ═ ╠ ╣ ╦ ╩ ╬ ┌ ┐ └ ┘ │ ─ ├ ┤ ┬ ┴ ┼ ╭ ╮ ╰ ╯`

**方块元素：** `░ ▒ ▓ █ ▄ ▀ ▌ ▐ ▖ ▗ ▘ ▝ ▚ ▞`

**几何图形与符号：** `◆ ◇ ◈ ● ○ ◉ ■ □ ▲ △ ▼ ▽ ★ ☆ ✦ ✧ ◀ ▶ ◁ ▷ ⬡ ⬢ ⌂`

### 规则 {#rules}

- 最大宽度：每行 60 个字符（终端安全）
- 最大高度：横幅 15 行，场景 25 行
- 仅限等宽：输出必须能在等宽字体中正确渲染

## 决策流程 {#decision-flow}

1. **把文字做成横幅** → 已安装则用 pyfiglet，否则通过 curl 使用 asciified API
2. **用有趣的角色艺术包裹一条消息** → cowsay
3. **添加装饰边框/画框** → boxes（可与 pyfiglet/asciified 组合）
4. **某个具体事物的作品**（猫、火箭、龙） → 通过 curl + 解析使用 ascii.co.uk
5. **将图片转换为 ASCII** → ascii-image-converter 或 jp2a
6. **二维码** → 通过 curl 使用 qrenco.de
7. **天气/月亮艺术** → 通过 curl 使用 wttr.in
8. **自定义/创意内容** → 使用 Unicode 调色板由 LLM 生成
9. **任何工具未安装** → 安装它，或回退到下一个选项
