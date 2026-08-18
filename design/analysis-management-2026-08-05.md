# Analysis 管理设计:代码、执行与环境

日期:2026-08-05。状态:已实现(57e55c1、695a69c)。配套:workspace-and-computation-site-2026-08-03.md。

## 1. 问题

分析脚本经常找不到、被误用(脚本与数据不对应)。现状(三个生产项目的调查
结论):脚本均为 CLI 参数化 Python(无 notebook),产物按 run 分目录、绝不
写原始 run root;但硬编码路径与 CLI 参数并存、手工 `-vN` 版本后缀代替
identity、脚本↔数据绑定只在人脑和散文里、同一脚本多处手动同步。

历史已定型未实现的部分直接继承:analysis 是 identity 链第六维,
`analysis_id = f(data_id, spec_hash, code_hash)`,parent 是 exact data ID;
data 变则 analysis stale,历史产物不删。0.4.0 的决定不变:科学方法留在
entity-nt2py,Ledger 只做登记/溯源。

## 2. 模型:代码与执行分开管

**分析代码**(源码性质,workspace 权威):

- 只有**通用脚本库**入台账,放 project 级:`projects/<p>/analysis/scripts/`。
  跨 case/run 复用的方法层(可以是包,如 bh-reconnection 的 aphi_topology)。
- 入库约定:数据路径必须 CLI 参数化。硬编码存量收编进 `scripts/legacy/`,
  **不拒绝登记**,manifest 标 `hardcoded_paths: true`,dashboard 显示提醒。
- case 级的一次性脚本由 agent 自己管理,**不计入台账**。

**分析执行**(事实,identity 链第六维):

- 执行是 agent 的自由探索(在哪跑、怎么跑,Ledger 不管);`record analysis`
  做事后登记 + 证据探测,失败零写入。
- 证据 = 产物目录里的 `analysis-manifest.json`:输入 data_id、脚本相对路径、
  参数、解释器/环境、生成时间。record 时重新探测:manifest 存在且 data_id
  与声称一致(强制);manifest 携带 script/script_sha256/params 时与登记
  交叉校验(可选字段,携带才校验)。
- `analysis_id = hash(data_id, script_hash, params)`;parent 挂 exact data ID;
  data current 变 → 旧 analysis stale。"误用"由此可查询:这份数据登记过哪
  些分析、什么脚本什么参数、是否还有效。

## 3. 分析环境:记录进 deps 注册表

Python 分析环境(conda/venv)**需要记录**,挂在 site 的 deps 注册表,与构建
栈同级,让 agent 一次查询即可找到(`site deps <site>`)。

- 注册表条目加 `kind` 字段:`build`(默认,构建工具链栈)| `analysis`
  (Python 环境)。analysis 条的 packages 记录解释器路径与关键包版本
  (python/numpy/nt2py 等),recipe 记录创建方式(conda env export 摘要或
  venv 路径)。
- `record analysis` 的 manifest 记录所用环境的 stack_id(可空——临时环境
  不强制登记);登记过栈的分析环境在 dashboard/查询中可溯源。
- `entityctl site deps-add` 扩展支持 `--kind analysis`(门禁放宽:不要求
  env.sh 与 compatibility pass,改要求解释器路径在 site 上真实存在)。

## 4. 物理布局(启用 0.7.0 预留槽位)

```text
# workspace 侧:
projects/<p>/analysis/scripts/                 # 通用脚本库(权威)
projects/<p>/cases/<c>/analysis/<analysis_id>/ # 取回的报告/图/manifest 副本(轻量)

# site 侧(靠近数据执行,大产物留这):
<site_root>/projects/<p>/analysis/<case>/<analysis_id>/   # 产物 + analysis-manifest.json
```

产物绝不写原始 run root(既有契约不变)。

## 5. 原语与呈现

```bash
entityctl record analysis --project-root <p> [--case <c>] \
  --script <scripts/ 相对路径> --data <run_id|data_id> \
  --params '<json>' --output-root <site 产物目录> [--env-stack <stack_id>]
```

- dashboard analysis 格升级:`none / established / stale`(父 data_id 是否
  current)+ manifest 证据 + hardcoded_paths 提醒标记;六格契约不变。
- `show` 输出 case 的 analysis 列表(脚本、参数、父 data、状态)。

## 6. 边界

- nt2py 边界不变:数据访问与绘图方法;不管登记,不判断物理对错。
- Ledger 不做:诊断方法、产物格式规定、分析流程编排。
- case 级一次性脚本:不入库、不登记,agent 自管。

## 7. 迁移

既有脚本收编随 0.7.0 生产迁移一起由 agent 执行:通用脚本进
`projects/<p>/analysis/scripts/`(硬编码的进 legacy/),各处手动同步的副本以
workspace 为权威去重;历史分析产物不追溯登记,新分析从 record analysis
开始。存量分析环境(如 bh-reconnection 的 venv)由 agent 用
`site deps-add --kind analysis` 登记。

## 8. 开发计划(单一阶段,已全部完成)

1. ✅ store:`analysis` 维度的写入路径打通(白名单已有),current 投影
   analysis_id 维护,stale 传播(data 变 → analysis stale,读时推导)。
2. ✅ `record analysis` 原语:manifest 证据探测(local + ssh 通道)、
   analysis_id 推导、零写入门禁、审计事件。
3. ✅ site 树:`projects/<p>/analysis/<case>/<analysis_id>/` 路径推导
   (execution_roots 扩展)。
4. ✅ deps 注册表:`kind` 字段 + `site deps-add --kind analysis`(解释器存在
   性门禁)。
5. ✅ dashboard:analysis 格 readiness + 证据 + hardcoded 提醒;show 的
   analysis 列表。
6. ✅ 文档:ledger SKILL.md(原语 + 语义)、workspace-layout.md(启用
   analysis 槽位)、nt2py SKILL.md(一句:登记找 ledger)、migration-guide.md
   (脚本收编段)、CHANGELOG。
7. ✅ 测试:record analysis 全门禁、stale 传播、kind=analysis 注册、dashboard
   呈现;全量 pytest 绿。
