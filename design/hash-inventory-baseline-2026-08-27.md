# Hash inventory 性能基线（WP0）

日期：2026-08-27
方案：`design/hash-verification-optimization-plan-2026-08-27.md`

## 方法

用 `.tmp/baseline_inventory.py` 生成合成 run root 并直接调用 executor 的
inventory step（in-process，envelope 与真实调用相同）：

- **大目录**：200 个稀疏文件 × 50 MiB = 10 GiB 逻辑大小（`truncate` 创建，
  几乎不占真实磁盘块）；metadata inventory 读取的内容字节数为 0。
- **小目录**：20 个真实文件 × 4 KiB。

对比三种模式：`data.inventory.v1`（当前默认，全量逐文件 sha256）、
`data.inventory.v2 --integrity metadata`（只读目录项）、
`data.inventory.v2 --integrity strong`（逐文件 sha256，显式 opt-in）。
机器：macOS 工作站，数字为单次运行的量级参考，不是基准统计。

## 结果

| 场景 | 模式 | 文件数 | 逻辑字节 | 内容读取 | 耗时 |
|---|---|---:|---:|---|---:|
| 小目录 (80 KiB) | v1（全量 hash） | 20 | 81,920 | 全部 | 0.003 s |
| 小目录 | v2 metadata | 20 | 81,920 | 0 | 0.003 s |
| 小目录 | v2 strong | 20 | 81,920 | 全部 | 0.003 s |
| 大目录 (10 GiB) | v1（全量 hash） | 200 | 10,485,760,000 | 10 GiB | 5.788 s |
| 大目录 | v2 metadata | 200 | 10,485,760,000 | **0** | **0.010 s** |
| 大目录 | v2 strong | 200 | 10,485,760,000 | 10 GiB | 5.699 s |

v2 strong 的 receipt effect 包含 `bytes_planned_read: 10485760000`，调用方
可以在执行前报告计划读取量。

## 结论

- 默认路径的成本从“与数据总字节数成正比”降为“与文件数成正比”：10 GiB
  稀疏数据下 metadata inventory 比全量 hash 快约 **580 倍**（5.8 s → 10 ms），
  且完全由文件数决定；换成真实磁盘上的 10 GiB，全量 hash 只会更慢，
  metadata 数字不变。
- 强校验没有消失，而是变成显式选择：`strong` 与 v1 耗时一致（都要读全部
  字节），并通过 `bytes_planned_read` 诚实报告成本。
- 满足验收标准 8.2：默认 `record data` 不再因 TB 级数据量隐式触发 TB 级读取。
