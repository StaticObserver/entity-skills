# U4 — 中断恢复（仅 S 组）

## 场景意图

agent 在 `entityctl apply` 执行中途被杀（模拟终端崩溃/掉线），重启后用户只说"接着干"。检验：不产生重复 sbatch、router store 里没有悬而未决的 anomaly Operation、最终数据照常交付。

## 对照组

仅 `skills-v5`（场景前提就是 router 的 apply/恢复语义）。

## 操作步骤（两段式）

1. `bash run_need.sh U4 skills-v5 <run-name> [model]`
2. 盯 transcript（`tail -f ~/entity-eval-traces/<run-name>/transcript.jsonl`），出现 `entityctl ... apply` 调用后杀掉 agent 进程（Ctrl-C 或 `kill <pid>`）。
3. `bash run_need.sh --followup U4 skills-v5 <run-name> [model]`（"请继续"）。
4. `bash grade_need.sh U4 <run-name>`。

## 核验逻辑（verify.py checks）

| check | 含义 |
|---|---|
| `no_duplicate_sbatch` | activities job_lifecycle 中每个 job-name 恰好提交 1 次（>1 进 fail，detail 提示人工核对首次是否 FAILED） |
| `no_anomaly_operations` | router export 中无 anomaly Operation，或 anomaly 均被同 case 后续 completed Operation 取代 |
| `data_delivered` | oracle Gate D 通过 |

## 已知边界

- "首次 FAILED 后可重交"的豁免需要 sacct 人工确认，verify 只给提示（fail + detail），避免自动豁免掩盖真重复。
