---
name: pytorch-fsdp
description: Expert guidance for Fully Sharded Data Parallel training with PyTorch FSDP - parameter sharding, mixed precision, CPU offloading, FSDP2
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [torch>=2.0, transformers]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Distributed Training, PyTorch, FSDP, Data Parallel, Sharding, Mixed Precision, CPU Offloading, FSDP2, Large-Scale Training]

---

# Pytorch-Fsdp Skill

Comprehensive assistance with pytorch-fsdp development, generated from official documentation.

## When to Use This Skill

This skill should be triggered when:
- Working with pytorch-fsdp
- Asking about pytorch-fsdp features or APIs
- Implementing pytorch-fsdp solutions
- Debugging pytorch-fsdp code
- Learning pytorch-fsdp best practices

## Quick Reference

### Common Patterns

**Pattern 1:** The generic join context manager facilitates distributed training on uneven inputs. The relevant classes are `Join`, `Joinable` and `JoinHook`.

```
Join
```

**Pattern 2:** `torch.distributed` supports four built-in backends (gloo, mpi, nccl, xccl), each with different capabilities. Rule of thumb: use NCCL for distributed training with CUDA GPUs, XCCL for XPU GPUs, and Gloo for CPU.

```
torch.distributed
```

**Pattern 3:** The package needs to be initialized using the `torch.distributed.init_process_group()` or `torch.distributed.device_mesh.init_device_mesh()` function before calling any other methods. Both block until all processes have joined.

```
torch.distributed.init_process_group()
```

**Pattern 4:** `init_device_mesh()` builds a `DeviceMesh` describing the device topology, for 1-D or N-D parallelism.

```
>>> from torch.distributed.device_mesh import init_device_mesh
>>>
>>> mesh_1d = init_device_mesh("cuda", mesh_shape=(8,))
>>> mesh_2d = init_device_mesh("cuda", mesh_shape=(2, 8), mesh_dim_names=("dp", "tp"))
```

**Pattern 5:** By default collectives operate on the default group (also called the world) and require all processes to enter the distributed function call. `new_group()` creates a group over an arbitrary subset of processes.

```
new_group()
```

**Pattern 6:** Safe concurrent usage: when using multiple process groups with the NCCL backend, the user must ensure a globally consistent execution order of collectives across ranks.

```
NCCL
```

**Pattern 7:** If you are using `DistributedDataParallel` in conjunction with the Distributed RPC Framework, you should always use `torch.distributed.autograd.backward()` to compute gradients and `torch.distributed.optim.DistributedOptimizer` for optimizing parameters.

```
torch.distributed.autograd.backward()
```

**Pattern 8:** `static_graph (bool)` – when set to `True`, DDP knows the trained graph is static: the set of used and unused parameters does not change across the training loop, and neither does the way the graph is trained.

```
True
```

Each pattern above is condensed. The full documentation pages the
scraper had inlined here are preserved verbatim in
`references/quick-reference-pages.md`.

## Reference Files

This skill includes comprehensive documentation in `references/`:

- **index.md** - Reference index and source-page map
- **common-patterns.md** - Reusable FSDP setup and training patterns
- **other.md** - Other documentation
- **quick-reference-pages.md** - Full text of the pages summarised in Quick Reference above

Use `view` to read specific reference files when detailed information is needed.

## Working with This Skill

### For Beginners
Start with the getting_started or tutorials reference files for foundational concepts.

### For Specific Features
Use the appropriate category reference file (api, guides, etc.) for detailed information.

### For Code Examples
The quick reference section above contains common patterns extracted from the official docs.

## Resources

### references/
Organized documentation extracted from official sources. These files contain:
- Detailed explanations
- Code examples with language annotations
- Links to original documentation
- Table of contents for quick navigation

### scripts/
Add helper scripts here for common automation tasks.

### assets/
Add templates, boilerplate, or example projects here.

## Notes

- This skill was automatically generated from official documentation
- Reference files preserve the structure and examples from source docs
- Code examples include language detection for better syntax highlighting
- Quick reference patterns are extracted from common usage examples in the docs

## Updating

To refresh this skill with updated documentation:
1. Re-run the scraper with the same configuration
2. The skill will be rebuilt with the latest information


