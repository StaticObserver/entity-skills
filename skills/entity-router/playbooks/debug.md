# Playbook：Debug

## 收益

record 原语失败时零写入，没有半拉子状态要收拾——修好原因重跑同一条
命令即可。就绪板和台账告诉你失败发生在哪个环节，而不是让你猜。

## 没有"debug 状态"

Debug 不是项目的一个阶段，而是某个环节上附着了失败证据。流程永远是：
**定位到拥有修复的那个环节 → 回到对应 playbook**。

## 按证据定位

| 证据 | 环节 | 回到 |
|---|---|---|
| `record build` 门禁失败（checkpoint 不过） | 环境/构建配置 | setup-env / build |
| 编译脚本执行失败 | 编译 | build（看日志，改配置重跑） |
| `record run-prepare` 报参数未确认 | PGen/参数 | develop-pgen |
| `record run-launch` preflight 拒绝（QoS/partition） | Site 策略 | `entityctl site discover <site>` 后修正 |
| run 格 `failed` + exit_code | 模拟运行 | 看 run_root 日志；物理/数值问题归科学判断 |
| run 格 `gone` / live `job_gone` | 带外变更 | 检查谁动了作业；必要时重新 prepare+launch |
| live `untracked_job` | 带外提交 | 用 `record run-launch --adopt-*` 认领，或清退 |
| 结果物理上不合理 | PGen/参数设计 | develop-pgen（这是科学问题，不是工程问题） |

## 工具

- `status` / `status --live`：就绪板、台账、带外变更（divergences）；
- `show --project-root <project>`：Case 事实明细（identity payload、
  证据引用）；
- run_root 下的 `run.log` / 提交脚本 / `.entity-exit-code`；
- `doctor`：安装与存储健康检查（崩溃后、换机器后先跑）。

## 原则

只处理已归属的问题：属于哪个环节就回哪个 playbook；归属不清时先
收集证据（日志、退出码、live 探测），不要扩大修改范围。
