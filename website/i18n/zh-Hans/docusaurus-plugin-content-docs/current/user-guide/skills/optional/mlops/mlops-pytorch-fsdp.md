---
title: "Pytorch Fsdp"
sidebar_label: "Pytorch Fsdp"
description: "PyTorch FSDP 全分片数据并行训练专家指导 - 参数分片、混合精度、CPU 卸载、FSDP2"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Pytorch Fsdp

PyTorch FSDP 全分片数据并行训练专家指导 - 参数分片、混合精度、CPU 卸载、FSDP2

## Skill 元数据

| | |
|---|---|
| 来源 | 可选 — 通过 `hermes skills install official/mlops/pytorch-fsdp` 安装 |
| 路径 | `optional-skills/mlops/pytorch-fsdp` |
| 版本 | `1.0.0` |
| 作者 | Orchestra Research |
| 许可证 | MIT |
| 依赖 | `torch>=2.0`, `transformers` |
| 平台 | linux, macos |
| 标签 | `Distributed Training`, `PyTorch`, `FSDP`, `Data Parallel`, `Sharding`, `Mixed Precision`, `CPU Offloading`, `FSDP2`, `Large-Scale Training` |

## 参考：完整 SKILL.md

:::info
以下是 Hermes 在触发此 skill 时加载的完整 skill 定义。这是 skill 激活时 agent 看到的指令内容。
:::

# Pytorch-Fsdp Skill

基于官方文档生成的 pytorch-fsdp 开发综合辅助。

## 何时使用此 Skill

以下情况应触发此 skill：
- 使用 pytorch-fsdp
- 询问 pytorch-fsdp 功能或 API
- 实现 pytorch-fsdp 解决方案
- 调试 pytorch-fsdp 代码
- 学习 pytorch-fsdp 最佳实践

## 快速参考

### 常用模式

**模式 1：** 通用 join 上下文管理器用于在输入不均匀时进行分布式训练。相关的类是 `Join`、`Joinable` 和 `JoinHook`。

```
Join
```

**模式 2：** `torch.distributed` 支持四种内置后端（gloo、mpi、nccl、xccl），各具不同能力。经验法则：CUDA GPU 的分布式训练用 NCCL，XPU GPU 用 XCCL，CPU 用 Gloo。

```
torch.distributed
```

**模式 3：** 在调用任何其他方法之前，必须先用 `torch.distributed.init_process_group()` 或 `torch.distributed.device_mesh.init_device_mesh()` 函数初始化该包。两者都会阻塞，直到所有进程都加入。

```
torch.distributed.init_process_group()
```

**模式 4：** `init_device_mesh()` 会构建一个描述设备拓扑的 `DeviceMesh`，可用于一维或 N 维并行。

```
>>> from torch.distributed.device_mesh import init_device_mesh
>>>
>>> mesh_1d = init_device_mesh("cuda", mesh_shape=(8,))
>>> mesh_2d = init_device_mesh("cuda", mesh_shape=(2, 8), mesh_dim_names=("dp", "tp"))
```

**模式 5：** 默认情况下，集合通信在默认组（也称为 world）上进行，并要求所有进程都进入该分布式函数调用。`new_group()` 可在所有进程的任意子集上创建一个组。

```
new_group()
```

**模式 6：** 并发使用安全性：当在 NCCL 后端下使用多个进程组时，用户必须确保各 rank 之间集合通信的执行顺序全局一致。

```
NCCL
```

**模式 7：** 如果你把 `DistributedDataParallel` 与分布式 RPC 框架一起使用，应始终用 `torch.distributed.autograd.backward()` 计算梯度，并用 `torch.distributed.optim.DistributedOptimizer` 优化参数。

```
torch.distributed.autograd.backward()
```

**模式 8：** `static_graph (bool)` —— 设为 `True` 时，DDP 知道所训练的图是静态的：在整个训练循环中，已使用和未使用参数的集合不会改变，图的训练方式也不会改变。

```
True
```

上面每个模式都是精简过的。scraper 原先内联在此处的完整文档页面已逐字保留在
`references/quick-reference-pages.md` 中。

## 参考文件

此 skill 在 `references/` 中包含完整文档：

- **other.md** - 其他文档
- **quick-reference-pages.md** - 上面快速参考中所概括页面的完整文本

需要详细信息时，使用 `view` 读取特定参考文件。

## 使用此 Skill

### 初学者
从 getting_started 或 tutorials 参考文件开始，了解基础概念。

### 特定功能
使用相应类别的参考文件（api、guides 等）获取详细信息。

### 代码示例
上方快速参考部分包含从官方文档中提取的常用模式。

## 资源

### references/
从官方来源提取的有组织文档，包含：
- 详细说明
- 带语言注释的代码示例
- 原始文档链接
- 快速导航目录

### scripts/
在此添加常见自动化任务的辅助脚本。

### assets/
在此添加模板、样板代码或示例项目。

## 说明

- 此 skill 由官方文档自动生成
- 参考文件保留了源文档的结构和示例
- 代码示例包含语言检测以提供更好的语法高亮
- 快速参考模式从文档中的常见用法示例中提取

## 更新

要使用最新文档刷新此 skill：
1. 使用相同配置重新运行爬虫
2. skill 将使用最新信息重新构建