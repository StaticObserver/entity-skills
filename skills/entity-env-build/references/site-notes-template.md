# 机器：<hostname>
> last_updated: <YYYY-MM-DD>

<!--
  【deprecated】site-notes 已被 workspace 的 sites/<site>.yaml 档案取代:
  散文进档案的 notes 节,结构化信息(transport/scheduler/site_root/deps
  注册表)进对应节;`entityctl site import-notes` 可把旧 notes 一次性
  迁入。本模板仅为旧流程参考保留,新站点请直接维护 sites/<site>.yaml。

  ~/.entity-env-build/site-notes/<hostname>.md 的模板
  由 AI agent 在运行时生成——不随技能源码发布。

  AI agent 在第 2 阶段（环境探测）开始时读取本文件，并在
  发现新问题或完成构建后写入它。

  各小节：
  - 机器档案     → 静态信息：这台机器有什么硬件/软件？
  - 已知可用组合 → 哪些依赖组合已被证明可用？
  - 已知问题     → 什么会坏，怎么修？
  - 构建历史     → 这台机器上做过哪些构建？

  条目保持简洁。优先使用要点列表而非散文。
  每次编辑时更新顶部的 last_updated。
-->

## 机器档案
<!-- 每台机器填写一次；环境变化时更新 -->
- 登录节点：
- Scheduler：
- GPU 分区：
- CPU 分区：
- Module 初始化：
- 默认 Python：
- 显著约束：<!-- 例如 "绝不在登录节点编译"、"计算节点无外网"、"只有 Python 3.6" -->

## 已知可用组合
<!-- 每次成功构建后添加。格式：
### <pgen> | <backend> | <MPI on/off>
- DTK: <version> | Kokkos: <version> | ADIOS2: <version> | HDF5: <version>
- OpenMPI: <version> | Compiler: <name+version>
- Optimization: <-Ox>
- Precision: <single/double>
- Notes: <any non-obvious detail>
-->

## 已知问题
<!-- 每当发现不直观的问题时添加。格式：
### <描述性标题>
- 症状：<错误信息模式>
- 触发：<什么导致的>
- 修复：<具体步骤>
-->

## 构建历史
<!-- 每次构建后追加。格式：
| <date> | <site_id> | <entity ver> | <source rev> | <backend> | <result> | <build root> |
-->
| 日期 | Entity | PGen | 后端 | 精度 | 优化 | 结果 | Workdir |
|------|--------|------|---------|-----------|-----|--------|---------|
