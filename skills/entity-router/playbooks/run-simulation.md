# Playbook：执行模拟（run-simulation）

## 收益

每个 run 都有台账记录：参数、站点、资源、终态、退出码。会话崩溃后
下轮能认领原作业而不是重复提交；续跑引用 parent，历史永不覆盖。
**run 序列就是研究轨迹。**

## 产物

- run 目录（`<run_root>/<case>/<run_id>/`：input、manifest、提交脚本、
  日志、退出码文件）；
- run identity（Router 台账：prepared → submitted → completed/failed）。

## 步骤

1. **预览**（可选，零写入）：
   ```bash
   python3 scripts/entityctl.py render-run --project-root <project> \
     --toml <input.toml> --site <site> [--gpus N] [--walltime HH:MM:SS]
   ```
2. **准备**：确认参数已 confirm（见 develop-pgen playbook），然后
   `record run-prepare`。Case 不存在时会自动创建。
3. **提交**：`record run-launch`。receipt 保证 exactly-once——重复
   执行不会重复提交，进程中断后重跑会认领已提交的作业。Slurm 站点
   提交前自动做 `sbatch --test-only` 预检。
   如果作业是你自己提交的：`record run-launch --adopt-job <job-id>`
   或 `--adopt-pid <pid>` 认领进台账（Router 探测确认后才落账）。
4. **等待期间不占状态**：run 上了调度器就是在途事实，你可以去
   分析上一个 run 或开发下一个 PGen。`status --live` 随时探测进度。
5. **终态落账**：`record run-exit` 探测退出文件/sacct，把
   completed（exit 0）或 failed（非 0）+ exit_code 落账。仍在运行
   时不写任何状态。
6. 输出到手后进入 analyze-data playbook。

## 状态记在哪

就绪板的 run 格 + Run 台账。run 失败（failed + exit_code）时按
debug playbook 定位；修复后从对应步骤重跑（每步幂等）。

## 转引

模拟物理与数值问题（发散、异常结果）属于科学判断，Router 不做；
数据读取见 `entity-nt2py`。
