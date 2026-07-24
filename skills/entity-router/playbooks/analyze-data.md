# Playbook：分析数据（analyze-data）

## 收益

数据盘点为每份输出生成带哈希的 manifest——"分析基于哪份数据"可核对；
输出变化后重新盘点即可刷新，同一 run 的 data identity 幂等。

## 产物

- `<run_root>/data-inventory.json`（每个文件的 sha256 与大小）；
- data identity（Router 台账，`status: inventoried`）；
- 分析产物（图表、报告，归 entity-nt2py 和用户的工作区）。

## 步骤

1. run 到终态后盘点：
   ```bash
   python3 scripts/entityctl.py --actor-run-id <id> --actor-provider <p> \
     record data --project-root <project> [--run-id <id>]
   ```
2. 分析工作全部交给 **entity-nt2py** skill：字段、粒子、谱、
   诊断、作图、导出。Router 不做科学判断。
3. 数据被改动（续跑、重写输出）后重跑 `record data` 刷新 manifest。

## 状态记在哪

就绪板的 data 格：`inventoried` + 文件数。analysis 格目前只反映
是否登记过分析事实——分析结论属于项目文档（design.md / 分析报告），
不进 Router 台账。

## 转引

`entity-nt2py` SKILL：nt2py API、BP5/HDF5 读取、诊断与可视化。
