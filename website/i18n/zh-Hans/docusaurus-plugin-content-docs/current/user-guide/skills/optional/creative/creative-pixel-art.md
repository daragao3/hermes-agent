---
title: "Pixel Art — 带时代调色板的像素艺术（NES、Game Boy、PICO-8）"
sidebar_label: "Pixel Art"
description: "带时代调色板的像素艺术（NES、Game Boy、PICO-8）"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Pixel Art

带时代调色板的像素艺术（NES、Game Boy、PICO-8）。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 使用 `hermes skills install official/creative/pixel-art` 安装 |
| 路径 | `optional-skills/creative/pixel-art` |
| 版本 | `2.0.0` |
| 作者 | dodo-reach |
| 许可证 | MIT |
| 平台 | linux, macos, windows |
| 标签 | `creative`, `pixel-art`, `arcade`, `snes`, `nes`, `gameboy`, `retro`, `image`, `video` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 所看到的指令内容。
:::

# Pixel Art

将任意图片转换为复古像素艺术，然后可选地把它做成一段带时代感特效（雨、萤火虫、雪、余烬）的
短 MP4 或 GIF 动画。

本 skill 附带两个脚本：

- `scripts/pixel_art.py` —— 照片 → 像素艺术 PNG（Floyd-Steinberg 抖动）
- `scripts/pixel_art_video.py` —— 像素艺术 PNG → 动画 MP4（+ 可选 GIF）

两者都可被导入，也可直接运行。当你需要还原时代色彩时，预设会对齐硬件调色板
（NES、Game Boy、PICO-8 等）；也可以使用自适应 N 色量化，得到街机/SNES 风格的效果。

## 使用时机

- 用户想把某张源图做成复古像素艺术
- 用户要求 NES / Game Boy / PICO-8 / C64 / 街机 / SNES 风格
- 用户想要一段短循环动画（雨景、夜空、下雪等）
- 海报、专辑封面、社交贴文、精灵图、角色、头像

## 操作流程

生成之前，先与用户确认风格。不同预设产出的效果差异极大，重新生成的成本很高。

### 第 1 步 —— 提供风格选项

用 4 个有代表性的预设调用 `clarify`。根据用户的诉求挑选这组选项 ——
不要一股脑把全部 14 个都列出来。

当用户意图不明确时的默认菜单：

```python
clarify(
    question="Which pixel-art style do you want?",
    choices=[
        "arcade — bold, chunky 80s cabinet feel (16 colors, 8px)",
        "nes — Nintendo 8-bit hardware palette (54 colors, 8px)",
        "gameboy — 4-shade green Game Boy DMG",
        "snes — cleaner 16-bit look (32 colors, 4px)",
    ],
)
```

当用户已经点名了某个时代（例如"80 年代街机""Gameboy"），就跳过
`clarify`，直接使用对应的预设。

### 第 2 步 —— 提供动画选项（可选）

如果用户要的是视频/GIF，或者输出加上动效会更好，就询问用哪个场景：

```python
clarify(
    question="Want to animate it? Pick a scene or skip.",
    choices=[
        "night — stars + fireflies + leaves",
        "urban — rain + neon pulse",
        "snow — falling snowflakes",
        "skip — just the image",
    ],
)
```

**不要**连续调用 `clarify` 超过两次。一次问风格，若涉及动画再问一次场景。
如果用户已在消息中明确指定了具体风格和场景，就完全跳过 `clarify`。

### 第 3 步 —— 生成

先运行 `pixel_art()`；若需要动画，再把结果接入
`pixel_art_video()`。

## 预设目录

| 预设 | 时代 | 调色板 | 色块 | 适用场景 |
|--------|-----|---------|-------|----------|
| `arcade` | 80 年代街机 | 自适应 16 色 | 8px | 醒目海报、主视觉 |
| `snes` | 16 位 | 自适应 32 色 | 4px | 角色、细节丰富的场景 |
| `nes` | 8 位 | NES（54 色） | 8px | 纯正 NES 观感 |
| `gameboy` | DMG 掌机 | 4 级绿色 | 8px | 单色 Game Boy |
| `gameboy_pocket` | Pocket 掌机 | 4 级灰色 | 8px | 单色 GB Pocket |
| `pico8` | PICO-8 | 固定 16 色 | 6px | 幻想主机观感 |
| `c64` | Commodore 64 | 固定 16 色 | 8px | 8 位家用电脑 |
| `apple2` | Apple II 高分辨率 | 固定 6 色 | 10px | 极致复古，仅 6 色 |
| `teletext` | BBC 图文电视 | 8 种纯色 | 10px | 厚重的原色 |
| `mspaint` | Windows 画图 | 固定 24 色 | 8px | 怀旧桌面风 |
| `mono_green` | CRT 荧光屏 | 2 级绿色 | 6px | 终端/CRT 美学 |
| `mono_amber` | CRT 琥珀色 | 2 级琥珀 | 6px | 琥珀色显示器观感 |
| `neon` | 赛博朋克 | 10 种霓虹色 | 6px | 蒸汽波/赛博 |
| `pastel` | 柔和马卡龙 | 10 种柔和色 | 6px | 可爱 / 温柔 |

具名调色板位于 `scripts/palettes.py`（完整列表见 `references/palettes.md` ——
共 28 个具名调色板）。任何预设都可以被覆盖：

```python
pixel_art("in.png", "out.png", preset="snes", palette="PICO_8", block=6)
```

## 场景目录（用于视频）

| 场景 | 特效 |
|-------|---------|
| `night` | 闪烁的星星 + 萤火虫 + 飘落的树叶 |
| `dusk` | 萤火虫 + 闪光 |
| `tavern` | 尘埃微粒 + 暖色闪光 |
| `indoor` | 尘埃微粒 |
| `urban` | 雨 + 霓虹脉动 |
| `nature` | 树叶 + 萤火虫 |
| `magic` | 闪光 + 萤火虫 |
| `storm` | 雨 + 闪电 |
| `underwater` | 气泡 + 光斑闪烁 |
| `fire` | 余烬 + 闪光 |
| `snow` | 雪花 + 闪光 |
| `desert` | 热浪扭曲 + 沙尘 |

## 调用方式

### Python（导入）

```python
import sys
sys.path.insert(0, "/home/teknium/.hermes/skills/creative/pixel-art/scripts")
from pixel_art import pixel_art
from pixel_art_video import pixel_art_video

# 1. 转换为像素艺术
pixel_art("/path/to/photo.jpg", "/tmp/pixel.png", preset="nes")

# 2. 制作动画（可选）
pixel_art_video(
    "/tmp/pixel.png",
    "/tmp/pixel.mp4",
    scene="night",
    duration=6,
    fps=15,
    seed=42,
    export_gif=True,
)
```

### CLI

```bash
cd /home/teknium/.hermes/skills/creative/pixel-art/scripts

python pixel_art.py in.jpg out.png --preset gameboy
python pixel_art.py in.jpg out.png --preset snes --palette PICO_8 --block 6

python pixel_art_video.py out.png out.mp4 --scene night --duration 6 --gif
```

## 流水线设计原理

**像素化转换：**
1. 增强对比度/色彩/锐度（调色板越小，增强越强）
2. 先做色调分离，在量化前简化色调区域
3. 用 `Image.NEAREST` 按 `block` 缩小（硬边像素，无插值）
4. 用 Floyd-Steinberg 抖动量化 —— 对齐到自适应 N 色调色板
   或某个具名硬件调色板
5. 再用 `Image.NEAREST` 放大回去

在缩小**之后**再量化，可以让抖动与最终的像素网格对齐。若先量化，
误差扩散会浪费在随后消失的细节上。

**视频叠加：**
- 每一帧都复制基准帧（静态背景）
- 叠加逐帧无状态的粒子绘制（每种特效一个函数）
- 通过 ffmpeg `libx264 -pix_fmt yuv420p -crf 18` 编码
- 可选的 GIF 通过 `palettegen` + `paletteuse` 生成

## 依赖

- Python 3.9+
- Pillow（`pip install Pillow`）
- PATH 上的 ffmpeg（仅视频需要 —— Hermes 会安装此包）

## 陷阱

- 调色板键名区分大小写（`"NES"`、`"PICO_8"`、`"GAMEBOY_ORIGINAL"`）。
- 非常小的源图（宽度 &lt;100px）在 8-10px 色块下会糊成一团。若源图很小，先放大。
- `block` 或 `palette` 传小数会破坏量化 —— 请保持为正整数。
- 动画粒子数量是针对约 640x480 画布调校的。图片非常大时，
  你可能想用不同随机种子再跑一遍来提升密度。
- `mono_green` / `mono_amber` 会强制 `color=0.0`（去饱和）。如果你覆盖它
  并保留色度，2 色调色板可能在平滑区域产生条纹。
- `clarify` 循环：每轮最多调用两次（先风格，再场景）。不要
  反复轰炸用户做选择。

## 验证

- 输出路径下已生成 PNG
- 能看到与预设色块尺寸一致的清晰方形像素块
- 颜色数量与预设吻合（肉眼检查图片，或运行 `Image.open(p).getcolors()`）
- 视频是有效的 MP4（`ffprobe` 能打开）且大小非零

## 署名

具名硬件调色板以及 `pixel_art_video.py` 中的程序化动画循环移植自
[pixel-art-studio](https://github.com/Synero/pixel-art-studio)
（MIT）。详情见本 skill 目录中的 `ATTRIBUTION.md`。
