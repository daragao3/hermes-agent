---
title: "Blender Mcp — 通过目录中的 blender MCP 驱动 Blender，并附 bpy 用法示例"
sidebar_label: "Blender Mcp"
description: "通过目录中的 blender MCP 驱动 Blender，并附 bpy 用法示例"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Blender Mcp

通过目录中的 blender MCP 驱动 Blender，并附 bpy 用法示例。

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/creative/blender-mcp` 安装 |
| 路径 | `optional-skills/creative/blender-mcp` |
| 版本 | `2.1.0` |
| 作者 | alireza78a + kshitijk4poor + Hermes Agent |
| 平台 | linux, macos, windows |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 agent 在 skill 激活时所看到的指令内容。
:::

# Blender MCP Skill

Hermes MCP 目录中 `blender` 条目的配套 skill。MCP 服务器负责与 Blender 建立
连接；本 skill 教你驱动它所需的 bpy 惯用法与陷阱。它不涵盖 Blender 的界面
操作流程——这里的一切都通过 MCP 工具作用于一个正在运行的 Blender 会话。

## 何时使用

当用户想在正在运行的 Blender 实例中创建或修改任何内容时使用：网格、材质、
动画、灯光、渲染。需要已安装 blender MCP 服务器，并且有一个已连接插件的
Blender 桌面会话。

## 前置条件

1. 从 Nous 目录安装 MCP 服务器（一次性）：

       hermes mcp install blender

   这会配置固定版本的 `blender-mcp` stdio 服务器，并启用精选的工具集：
   `get_scene_info`、`get_object_info`、`get_viewport_screenshot`、
   `execute_blender_code`。

2. 在 Blender 内安装插件（一次性——目录条目的安装后说明中也有介绍）：
   - 下载 https://raw.githubusercontent.com/ahujasid/blender-mcp/main/addon.py
   - Blender > Edit > Preferences > Add-ons > Install... > 选择 addon.py，
     启用 "Interface: Blender MCP"。

3. 每次会话：先启动 Blender，在视口中按 N 键，打开 "BlenderMCP" 标签页，
   点击 "Connect to Claude"（启动本地桥接 socket）。然后再启动你的 Hermes
   会话，这样 MCP 工具才会被加载。

   该插件拒绝在 `blender -b`（后台模式）下启动。在没有显示器的机器上，请在
   虚拟显示下运行 Blender：`xvfb-run blender`。GPU 渲染在 Xvfb 下正常工作。

## 快速参考

| MCP 工具                  | 用途                                       |
|---------------------------|--------------------------------------------|
| `get_scene_info`          | 动手改场景之前先列出对象                   |
| `get_object_info`         | 检查单个对象（变换、材质）                 |
| `get_viewport_screenshot` | 目视检查你构建出的结果                     |
| `execute_blender_code`    | 其余一切——任意 bpy Python 代码             |

更深入的资料放在参考文件中（按需加载）：

| 参考文件 | 内容 |
|-----------|------|
| `references/bpy-api.md` | 核心 bpy 操作：建模、材质、修改器、渲染 |
| `references/recipes.md` | 完整可用的场景：低多边形地形、玻璃球体、HDRI 灯光、转盘动画 |
| `references/pitfalls.md` | 来之不易的经验：5.x 中代码返回空结果、ops 与 data API 之别、各版本的引擎名称 |

可选的素材服务工具（PolyHaven、Sketchfab、Hyper3D、Hunyuan3D）默认处于禁用
状态。如果用户已在插件面板中启用了某项服务，可通过 `hermes mcp configure
blender` 选择启用其工具。

## 操作步骤

1. 先调用 `get_scene_info`——永远不要假定场景是空的。
2. 用 `execute_blender_code` 构建，采用小而聚焦的多次调用（每次调用完成一个
   逻辑步骤：先加对象，再加材质，然后动画）。庞大的单体脚本会触发桥接超时。
3. 在各主要步骤之间用 `get_viewport_screenshot` 做目视验证。
4. 渲染到绝对路径，并告诉用户文件在哪里。

### 常用 bpy 模式

清空场景：

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

添加网格对象：

    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0))
    bpy.ops.mesh.primitive_cube_add(size=2, location=(3, 0, 0))
    bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=2, location=(-3, 0, 0))

创建并指定材质：

    mat = bpy.data.materials.new(name="MyMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (R, G, B, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Metallic"].default_value = 0.0
    obj.data.materials.append(mat)

关键帧动画：

    obj.location = (0, 0, 0)
    obj.keyframe_insert(data_path="location", frame=1)
    obj.location = (0, 0, 3)
    obj.keyframe_insert(data_path="location", frame=60)

渲染到文件：

    bpy.context.scene.render.filepath = "/tmp/render.png"
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.ops.render.render(write_still=True)

## 注意事项

- 只有在服务器已安装、且会话是在安装之后启动的情况下，blender MCP 工具才会
  存在。如果找不到这些工具，请运行 `hermes mcp install blender` 并开启一个新
  会话。
- 每个 Blender 会话都必须在 Blender 内部（重新）连接插件桥接
  （N 面板 > BlenderMCP > Connect）。工具报 "Connection refused" 意味着
  Blender 没有运行或插件未连接——去解决它，不要重试。
- 把复杂场景拆分为多次较小的 `execute_blender_code` 调用，以避免桥接超时。
- 渲染输出路径必须是绝对路径（`/tmp/render.png`），不能用相对路径——它们是
  在 Blender 所在主机的文件系统上解析的，当 Hermes 和 Blender 运行在不同机器
  上时这一点很重要。
- `shade_smooth()` 要求对象已被选中且处于对象模式。
- `execute_blender_code` 会在 Blender 内部运行任意 Python，且没有沙箱——信任
  级别与 `terminal` 工具相同。不要把不受信任的代码粘贴进去。
- 不要再从 `execute_code` 手工拼装发往 9876 端口的原始 TCP JSON——那是本
  skill 在 MCP 之前的临时方案。它绕过了目录的版本固定与工具精选。MCP 工具才
  是受支持的路径。

## 验证

- 每个构建步骤之后，`get_scene_info` 返回预期的对象列表。
- `get_viewport_screenshot` 显示的是你想要的场景。
- 渲染之后，确认输出文件存在，并把它的绝对路径报告给用户。
