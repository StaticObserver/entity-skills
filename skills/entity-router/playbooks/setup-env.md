# Playbook：确立编译环境（setup-env）

## 收益

环境 checkpoint 让你（和后续任何一轮会话）不用重新摸依赖、编译选项
和兼容性问题——一次确立，反复使用；换机器时也知道每台站点用的是什么
环境。

## 产物

- env-build checkpoint 文件（`entity-deps.local.json`，含
  `compatibility` 结论和构建参数记录）；
- Site profile（`entityctl site add` 注册进 store）。

## 步骤

1. 注册/检查执行 Site：`entityctl site add --profile <site.json>`；
   不确定站点的 partition/QoS/GPU/可写 root 时先
   `entityctl site discover <site_id>`。
2. 依赖与编译环境工作全部交给 **entity-env-build** skill（requirements、
   兼容性检查、`entity-build.sh`）。Router 不做构建推理。
3. checkpoint 产生后不需要立即登记——它在 `record build` 时作为证据
   被探测和引用。

## 状态记在哪

checkpoint 文件本身是环境事实的权威（项目内，用户指定位置）；Router
在 `record build` 时把它登记进 build identity。就绪板的 build 格变
`verified` 之前，这一格一直是 `missing`。

## 转引

`entity-env-build` SKILL：requirements.json、entity-deps.local.json、
compatibility 检查、env.sh、entity-build.sh、依赖修复。
