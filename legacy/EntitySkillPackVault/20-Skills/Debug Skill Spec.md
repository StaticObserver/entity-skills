# Debug Skill 规范

## 使命

诊断 Entity 的 build、runtime、output、checkpoint、cluster environment 和 numerical behavior 问题。

这个 skill 是横切能力，可以被 simulation、analysis 或 development 工作流调用。

## 排错类别

### Build

- CMake options；
- Kokkos backend 和 architecture flags；
- compiler 与 CUDA/HIP compatibility；
- ADIOS2 与 HDF5 discovery；
- MPI 和 GPU-aware MPI。

### Runtime

- `.err` 和 `.log` 文件；
- stdout progress；
- 粒子数异常增长或损失；
- `maxnpart` exceeded；
- NaN 或 timestep 收缩；
- boundary-condition 问题。

### 输出

- fields 或 particle data 缺失；
- BP5/HDF5 format mismatch；
- stats CSV 缺失或格式异常；
- custom output hook 未被检测到；
- checkpoint write/read 失败。

### Performance

- communication bottleneck；
- current deposition；
- field solver；
- particle pusher；
- output throughput。

## 工作流

1. 保留 failing command 和 environment。
2. 判断 failure 类型：build、runtime、output、checkpoint、performance 或 numerical。
3. 先读离错误最近的 artifact。
4. 最小化问题 case。
5. 可行时与已知可运行 pgen 比较。
6. 一次只提出一个改动。
7. 重新运行最小有用检查。

## 输出

说明：

- suspected cause；
- evidence；
- 已尝试或建议的 fix；
- verification result；
- remaining uncertainty。
