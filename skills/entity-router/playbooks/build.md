# Playbook：编译（build）

## 收益

登记过的 build identity 让 run 原语自动解析可执行文件（省略
`--executable`），也让"这个 run 是用哪个构建跑的"可追溯。重复登记同
一构建是幂等 no-op。

## 产物

- 可执行文件（如 `entity.xc`，在执行 Site 的 build root 下）；
- build identity（Router 台账，`status: verified`）。

## 步骤

1. 构建脚本和编译配置由 **entity-env-build** skill 生成
   （`entity-build.sh`，基于已验证的 env checkpoint）。
2. 执行编译。完整编译是长任务，可以拉起 sub-agent 跑脚本以隔离
   上下文——脚本由代码生成、结果由代码验证，sub-agent 不做任何记录。
3. 编译成功后登记：
   ```bash
   python3 scripts/entityctl.py --actor-run-id <id> --actor-provider <p> \
     record build --project-root <project> --site <site> \
     --checkpoint <entity-deps.local.json> --executable </abs/entity.xc>
   ```
   门禁：checkpoint 必须 `compatibility: pass` 且参数已确认；
   Router 会探测 executable 存在、可执行并计算哈希，然后才落账。

## 状态记在哪

就绪板的 build 格：`verified` + 可执行文件位置与站点。源码变化后
（就绪板 source 格提示 HEAD 漂移）应考虑重新编译并重新登记。

## 转引

`entity-env-build` SKILL：构建配置、entity-build.sh、编译错误修复。
