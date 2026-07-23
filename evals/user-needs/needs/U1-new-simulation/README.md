# U1 — 新模拟全链路（A/B 对照）

## 场景意图

用户给出物理规格，要求在 siyuan 集群上完成"建 PGen → 编译 → 提交作业 → 分析 → 交付"全链路。这是 e2e-neutral-streaming 任务的需求化归一版：prompt 只提用户需求，评分只看最终客观状态（oracle Gates A-E、scheduler 事实、router store），不看 agent 走的路径。

## 对照组

- `skills-v5`（S 组）：装 entity 技能全家桶。额外核验 data-inventory.json 与 router source/build/run 身份链。
- `skills-no-router`（N 组）：保留 env-build/pgen/nt2py，仅无 entity-router。data inventory 与 router 链属 router 能力，记 unknown 并写入 skill_boundary_notes，不算 fail。

## 核验逻辑（verify.py checks）

| check | 含义 |
|---|---|
| `oracle_gates` | e2e oracle Gates A-E overall |
| `submission_schema` | submission.json 过 submission.schema.json |
| `data_inventory` | S：data-inventory.json 存在；N：unknown + boundary note |
| `single_sim_job_success` | activities job_lifecycle 中 sim 类作业恰好 1 次提交；重复次数进 detail |
| `router_run_chain` | S：router export 中 source/build/run 身份链完整；N：unknown |

## 已知边界

- N 组（无 router）无 data Goal / router 链（技能边界，见 SUITE.md 清单）。
- 离线干跑时 sacct/router 不可达的项记 unknown 并注明原因。

## 运行

```bash
bash evals/user-needs/run_need.sh U1 skills-v5 <run-name> [model]
bash evals/user-needs/grade_need.sh U1 <run-name>
# 离线干跑：
bash evals/user-needs/grade_need.sh U1 <run-name> --offline <evidence-dir>
```
