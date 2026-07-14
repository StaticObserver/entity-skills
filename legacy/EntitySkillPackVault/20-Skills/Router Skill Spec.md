# Router Skill 规范

## 角色

判断用户请求类型，并加载最小必要的 Entity skill。

Router 应该很薄，不包含详细 Entity API。

## 路由表

| 用户意图 | Skill |
| --- | --- |
| 配置运行、写 TOML、选择 pgen、提交任务 | [[Simulation Skill Spec|Simulation Skill]] |
| 读取输出、作图、诊断物理行为 | [[Analysis Skill Spec|Analysis Skill]] |
| 修改 Entity 源码或增加核心功能 | [[Development Skill Spec|Development Skill]] |
| 诊断编译、运行、输出或性能失败 | [[Debug Skill Spec|Debug Skill]] |
| 写运行笔记、设计说明、PR 摘要或报告 | [[Docs Skill Spec|Docs Skill]] |

## 总是加载

任何任务 skill 之前，都先加载：

- [[10-Architecture/Knowledge Model and Version Strategy|知识模型与版本策略]]
- [[50-References/Entity Source of Truth|Entity 权威信息源]]

## 分类示例

“帮我在 A100 上跑 reconnection” -> simulation。

“画粒子谱并检查能量守恒” -> analysis。

“增加一个新的输出 quantity” -> development，然后可能需要 analysis 验证。

“ADIOS2 输出时崩溃” -> debug。

“把这次运行整理成可复现记录” -> docs 加 simulation。

## Router 输出

Router 应说明：

- 选择了哪个 skill；
- 为什么选择它；
- 后续是否可能需要另一个 skill。

