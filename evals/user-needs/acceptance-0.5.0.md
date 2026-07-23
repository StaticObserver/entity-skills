# 0.5.0 生产验收报告（user-needs 套件）

被测对象：entity skills bundle 0.5.0（bundle_hash 见各轮 bundle.json）。
评测框架：evals/user-needs/（场景定义见 SUITE.md，流程见 LIVE-RUN.md）。
变体：S = skills-v5（完整 bundle）；N = skills-no-router（仅无 entity-router）。
基线对照：S1（2026-07-21）/ Snr1（2026-07-22）留存证据。

> 状态：5/9 轮完成（U1-S、U1-Nr、U6-Nr、U4-S、U6-S）。U2-S/U3-S/U3-Nr/U5-S
> 被环境阻塞：siyuan 账户级 GPU GRES 自 2026-07-22 ~22:00 起不可用
> （AssocGrpGRES，GrpTRES 空；两个 agent 独立诊断一致；gold run 前一天可跑），
> 由 gpu_probe.sh 每 20 分钟探测（cron 4441807b），恢复后按 LIVE-RUN.md 补跑；
> 因 U2-S 依赖一个 S 组完成的 run，恢复顺序为：重跑 U1-S → U2-S → U3-S/Nr → U5-S。

## 结果总表

| 轮次 | 场景 | 组 | overall | 关键事实 | 报告 |
|---|---|---|---|---|---|
| 2026-07-22-U1-S | U1 新模拟全链路 | S | **fail**（操作者按 §5 中止） | GPU 账户级 AssocGrpGRES 阻塞全程（~2h）；agent 试探 router 7 次（doctor/site list）但止步于 onboarding，未 site add 未 plan（share=0.081、手术=0）；67 次提交（26 build/41 sim 含 21 次 wrap 探测）；gcc 11.2 ICE 阻碍构建；agent 改 Entity 源码（get_gpu 补丁）并尝试 CPU 分区跑 sim（违 spec）；未交付 submission.json | need-report.json |
| 2026-07-22-U1-Nr | U1 | N | **fail**（agent 自行完成交付） | **Gate D 物理全过**（CPU 跑 sim，ux 漂移 2.35%、E² 4.7e-05）；schema ✓；失败项：未交付 input.toml/pgen/analysis 到 project（B/E）、4 次登录节点分析（A）、28 次 sim 提交；sim 作业在 64c512g（违 task.md 的 debuga100 要求，oracle 按 submission 自报值比对未抓——已记为 gate 缺口）；skill 调用仅 env-build | need-report.json |
| U2-S | U2 参数变更重跑 | S | 阻塞（GPU） | 依赖 U1-S 完成的 GPU run；待 GPU 恢复后补跑 | |
| U3-S | U3 作业带外被杀 | S | 阻塞（GPU） | 需要 RUNNING 中的 sim 作业才能 scancel | |
| U3-Nr | U3 | N | 阻塞（GPU） | 同上 | |
| 2026-07-23-U4-S | U4 中断恢复 | S | **fail**（环境阻塞下的部分结论） | 崩溃恢复：agent 采用 cancel+resubmit（run_a100.sbatch ×4，无并行重复，但每次损失队列位置——router 的 apply/adopt 正是为此设计，agent 却未用）；router 调用 9 次且完成 site add 注册，但始终未执行 plan/apply（onboarding 后回退裸 sbatch）；agent 两次精确诊断 GPU 根因（GrpTRES 空=0 需管理员）并按 task.md 停手；数据未交付（GPU 墙） | need-report.json |
| U5-S | U5 可核验交付 | S | 阻塞（GPU） | 依赖一次完成交付；待 GPU 恢复 | |
| U6-S | U6 存量数据分析 | S | _待跑_ | | |
| 2026-07-23-U6-Nr | U6 | N | **pass**（套件首个 pass） | 报告 ux=0.1985 与独立重算 0.2021 一致；analyze.py 重跑 exit 0；数据根只读；~8 min 完成（对照 U1 轮次数小时） | need-report.json |

## 1.0.0 候选标准对照

| 标准 | 证据 | 结果 |
|---|---|---|
| 真实 SSH 站点端到端 build→run→data 跑通 | U1-S need-report + router export | **未达成**（GPU 墙 + router 未采用） |
| 技能脚本命中率 >0 | U1-S activities.json skill_call_share | 0.081（router=7 次但无 plan/apply；指标 bug 修复后口径） |
| 无 sqlite 控制面手术 | 全部 S 轮 control_plane_surgery_calls | **达成**（U1-S=0、U4-S=0；S1 基线=1） |
| S1/Snr1 失败点被 gate 拦截 | U1-S oracle Gates B/C/D | 部分（U1-Nr 的 Snr1 式布局已被 Gate B 正确解析；物理 Gate D 在 U1-Nr 全过） |

## 与 S1/Snr1 基线对比（U1 场景）

| 指标 | S1 | Snr1 | U1-S | U1-Nr |
|---|---|---|---|---|
| sim 提交次数 | 4 | 8（7 成功） | | |
| 构建类提交 | 8 | 12 | | |
| 轮询次数（squeue/sacct/scontrol） | 26 | 42 | | |
| skill_call_share | 0.328 | 0.057 | | |
| sqlite 手术 | 1 | 0 | | |
| oracle overall | fail | fail | | |

## 头条发现：router 的 onboarding 摩擦

初报"router 采用率为零"是**测量 bug**（skill_adoption 把 `python3 ~/.claude/skills/.../entityctl.py` 的路径执行误判为"读技能文档"而跳过，已修并回归测试）。修正后的事实更有意思：

- U1-S：7 次 entityctl 试探（doctor 带错参数 → usage 错误 → help → doctor → site list），随后**放弃**，全程未 site add、未 plan；
- U4-S：9 次调用且**成功完成 site add**，但从未执行 `plan --goal` / `apply`——恢复阶段明文说"试试 router 的 plan"，下一秒却回退裸 sbatch；
- 结论：问题不在"agent 不知道 router"，而在**从 CLI 试探到第一个成功 plan 之间的摩擦**——手写 site profile、手写 GoalSpec JSON、decisions 确认链，每一步都可能报错，而裸 sbatch 一行即可提交。router 的价值（幂等/恢复/归因）要在 apply 之后才显现，onboarding 成本却前置。**0.6.0 的头号需求：降低首个 plan 的启动成本**（如 `entityctl init` 一键生成 site profile + goal 模板、或 agent-facing quickstart playbook）。

## 技能边界与缺陷记录（跑批中累积）

- （已知边界）0.5.0 无 run 完成收口 / 无 resubmit Goal / purge 未接线 / 跨站点 source 必然 needs_decision / analysis 非 Goal。
- （环境）siyuan 上存在一个 2026-07-20 遗留作业 59839672（dgx2, PENDING/AssocGrpGRES），非本评测产物，不干预。
