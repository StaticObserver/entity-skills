# vNext Kimi Code 黑盒验收

## 环境

- 开发分支：`codex/vnext-minimal-ledger`
- 第一轮提交：`aa647ce`
- 修复提交：`785cb24`
- Kimi Code：`0.38.0`
- 每轮使用新的 detached worktree、空 skills 目录和独立 `/tmp` Workspace/Site。
- Kimi 只读取架构、README、示例 JSON 和 CLI help；不读取测试或实现源码，不修改仓库。

## 第一轮

通过：

- Workspace、Project、local Site、deps；
- 两个 Source commit 与同一个 PGen 组合；
- direct Build、Run、Attempt、TOML、Data；
- fake Slurm 的 non-MPI/MPI 脚本与提交；
- 单 Run 和联合 Analysis；
- `entity check` 只读断链报告；
- legacy 只读迁移 smoke test。

发现：

- `check` 未报告 `build-result.json` 指向的可执行文件缺失；
- 非法 legacy JSON 泄露 traceback；
- 未注册 Site 的初始化提示不清；
- 残缺 Source 目录的人工修复提示不清；
- legacy export 格式缺少公开示例；
- Slurm accounting 复合行未归一化。

## 修复

- 增加 `build_executable_missing`；
- legacy JSON/SQLite 错误统一为结构化错误；
- 增加 `site_not_registered` 和 add→init 指引；
- 增加 `partial_record` 人工修复指引；
- 增加 `schemas/examples/legacy-export.json`；
- Slurm 状态从复合 `sacct` 行提取标准状态；
- 明确单 Run Analysis JSON 位于 Workspace，Site 保存大型产物。

## 第二轮

提交 `785cb24` 的独立复验结果：6/6 PASS。

1. 未注册 Site 明确提示先 `site add`；
2. 非法/缺失 migration 输入返回结构化错误，无 traceback；
3. legacy 示例只读导入 Source，Build/Run/Case 进入冲突报告；
4. 删除已记录 executable 后 `check` 报 `build_executable_missing`，且不写文件；
5. 残缺 Source 返回 `partial_record` 和人工修复路径；
6. `4242|COMPLETED|0:0` 归一为 `COMPLETED`。

阻断问题：无。

## 验证边界

- 使用 fake compiler、fake Entity、fake Slurm；未在真实 HPC 提交作业。
- SSH transport 已实现，但未连接真实远程站点。
- 旧版自动迁移只转换能满足新四对象合同的 Source；PGen、Build、Run、Data 和 Case 的不足信息进入 `migration-report.json`，由人映射。

## 技能层切换验收

- Kimi Code `0.39.0` 仅加载 `vnext/skills/`，正确发现
  `entity-workspace`、`entity-env-build`、`entity-pgen`、`entity-nt2py`，未发现
  `entity-ledger`。
- 第一轮把“同一 TOML 调整 Slurm 资源”误解为 TOML 改动；据此明确 Run 身份只由
  Build 与 TOML 决定，资源和环境由 Attempt 记录。
- 第二轮正确判断：修改 PGen 创建新 PGen、Build 和 Run；保持新 Run 的 Build/TOML
  不变而调整节点数，只创建新 Attempt。
- 技能测试只做只读判断，未连接站点、编译、提交或修改 Workspace。
