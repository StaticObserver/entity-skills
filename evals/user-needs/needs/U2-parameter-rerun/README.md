# U2 — 参数变更重跑（仅 S 组）

## 场景意图

已完成的 U1 run 之上，用户要求"把 ux 从 0.2 改成 0.3 再跑一次，旧数据保留"。检验：变更是否走了正确的确认链（新 TOML 有新的 preflight decision 记录）、新旧 run 身份可区分、旧数据零改动、新数据物理上确实以 0.3 漂移。

## 对照组

仅 `skills-v5`：decision 记录与 run 身份链都是 router 能力，无 router 组无意义。

## 前置条件

先完成一个 U1 run（live），或提供其留存证据：

```bash
bash evals/user-needs/run_need.sh U2 skills-v5 <run-name> [model] -- --prior <u1-run-name|evidence-dir>
```

setup.sh 会把 U1 的 input.toml/pgen.hpp/docs 铺进新项目作为"已有工作"，记录旧 data_root，并对其做远端文件快照（站点不可达时跳过，对应 check 记 unknown）。

## 核验逻辑（verify.py checks）

| check | 含义 |
|---|---|
| `new_decisions_digest` | 存在 .decisions.json，其 input_sha256 匹配含 0.3 的新 TOML |
| `distinct_run_ids` | router export 中 ≥2 个不同 run 身份 |
| `old_run_root_preserved` | 旧 data_root 与 setup 时快照逐文件一致（mtime+size） |
| `gate_d_ux_new_target` | 用期望值 0.3 对新数据独立重算 ux 漂移（gate_d 逻辑参数化） |

## 已知边界

- ux 重算需要 nt2py 能读数据根；离线模式用 evidence 的 oracle-data，live 模式 rsync 拉取最新 run 身份的数据根。
- 快照比对的 mtime 精度依赖远端 `find -printf`（GNU）；站点不可达记 unknown。
