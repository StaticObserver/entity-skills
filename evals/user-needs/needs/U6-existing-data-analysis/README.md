# U6 — 存量数据分析（A/B 对照）

## 场景意图

用户手上已有一个完成的 run 的数据根，只要分析、不要新模拟：ux 是否漂移、E² 噪声水平，交付报告 + 可重跑脚本，且数据根只读。检验"分析能力"与"数据保护"，与 router 无关（analysis 不是 Goal，属技能边界而非缺陷——见 SUITE.md）。

## 对照组

- `skills-v5` 与 `skills-no-router` 同一套 checks（本场景无 router 专属产物）。

## 前置条件

setup.sh 需要数据根来源，并把它渲染进 prompt（`@DATA_ROOT@` 占位符）：

```bash
bash evals/user-needs/run_need.sh U6 <variant> <run-name> [model] -- --data-root <remote-path>
# 或从留存证据取 submission.json 里的 run.data_root：
bash evals/user-needs/run_need.sh U6 <variant> <run-name> [model] -- --evidence <evidence-dir>
```

## 核验逻辑（verify.py checks）

| check | 含义 |
|---|---|
| `analysis_artifacts_exist` | analysis/report.md 与 analysis/*.py 存在（Gate E 式） |
| `ux_value_consistent` | 报告中的 ux 数值与 nt2py 独立重算的最后快照 mean ux 偏差 ≤ max(0.02, 10%) |
| `analyze_rerunnable` | analyze.py 能对数据根重跑成功（尝试位置参数与 --data-root 两种调用） |
| `data_root_readonly` | 数据根内无分析产物（report/script/图/notebook） |

## 已知边界

- 报告数值提取是启发式（ux/drift 行上的浮点数），不命中记 unknown 交人工复核。
- analyze.py 的调用约定未标准化；verify 尝试两种常见形式，都失败才记 fail。
- 离线模式用 evidence 的 oracle-data 实测重算与重跑。
