# 开发计划

## 目标

把这个 vault 落地成可维护的 Entity skill pack，既支持单 agent 使用，也支持多个专门 agent 协作。

## Phase 0：Vault 基础

状态：进行中。

交付物：

- Obsidian vault 结构；
- 架构笔记；
- skill 规范；
- 开发计划；
- 初始模板。

验收：

- vault 可以作为连贯的 Obsidian 知识库打开；
- 每个主要设计笔记都能从 [[Home|首页]] 找到；
- simulation 和 development 的 skill 边界明确。

## Phase 1：最小 Skill Pack

交付物：

- `SKILL.md` router；
- `core/source-of-truth.md`；
- `core/code-map.md`；
- `skills/entity-sim.md`；
- `skills/entity-dev.md`；
- run manifest template；
- development design note template。

验收：

- 单个 agent 可以把 simulation request 路由到 `entity-sim`；
- 单个 agent 可以把 source-code request 路由到 `entity-dev`；
- 两个 skill 都要求 checkout/version probing；
- 两个 skill 都把版本敏感细节交给当前 checkout 文件确认。

## Phase 2：Analysis 和 Debug Skills

交付物：

- `skills/entity-analysis.md`；
- `skills/entity-debug.md`；
- analysis report template；
- debugging workflow；
- nt2py source-of-truth notes。

验收：

- analysis skill 区分 visual、numerical、regression 和 unresolved 证据；
- debug skill 覆盖 build/runtime/output/checkpoint/performance 类别；
- 常见 debug 结论包含 evidence 和 remaining uncertainty。

## Phase 3：Playbooks 和 Local Overlays

交付物：

- new simulation playbook；
- reproduce run playbook；
- add pgen playbook；
- add output quantity playbook；
- modify kernel playbook；
- checkpoint restart playbook；
- StaticObserver fork 和实验分支的 local overlays。

验收：

- local overlays 被标注为本地行为；
- 官方上游行为没有和 fork 行为混淆；
- 每个 playbook 都有 inputs、outputs 和 stop conditions。

## Phase 4：Packaging 和 Validation

交付物：

- 最终 skill-pack 目录；
- README install instructions；
- smoke examples；
- validation checklist；
- 可选 GitHub 发布计划。

验收：

- skill pack 可以复制进 agent skills directory；
- relative links 可用；
- agent 可以完成一次模拟路由测试且不缺文件；
- docs 标明当前支持的 Entity version buckets。

