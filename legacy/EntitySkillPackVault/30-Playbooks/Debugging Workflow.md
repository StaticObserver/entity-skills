# 排错工作流

## 目标

用最小改动从 symptom 走到 verified cause。

## 步骤

1. 捕获 exact command 和 environment。
2. 分类 failure：build、runtime、output、checkpoint、performance、numerical。
3. 读取离错误最近的信息源。
4. 缩小 case。
5. 与已知可运行 example 比较。
6. 应用一个改动。
7. 重新运行最小检查。
8. 记录结果和 remaining risk。

## 优先检查的文件

- build：CMake configure output 和 compiler error；
- runtime：`<name>.err`、`<name>.log`、stdout；
- output：`.info`、output directory structure、ADIOS2/HDF5 files；
- analysis：stats CSV 和 nt2py loading error。

