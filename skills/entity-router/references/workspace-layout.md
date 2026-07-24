# 多站点工作区契约

一个资源的 identity 始终是 `(site_id, 绝对路径)` 这一对组合加上它的
fingerprint。一个 Site 可以是一台本地机器，也可以是一个 SSH 访问边界，
覆盖一台 HPC 登录节点、scheduler、计算节点和共享文件系统。

## 控制器布局

```text
~/.entity-router/
└── router.db                         # controller authority
```

`router.db` 只包含紧凑的事实和证据引用。它绝不放在
源代码检出目录内，也绝不复制到 `.codex`、`.claude` 或
`.kimi-code` 等 provider 私有根目录。从 v3 导入的控制器可能仍
带有迁移前保留的文件（`registry.json`、`sites/`、`cases/`）；
它们是只读的历史证据，当前运行时绝不读取或写入它们。

## Owner-site 布局

各根目录相互独立，不需要共享父目录：

```text
<build_root>/<case_uid>/<build_id>
<run_root>/<case_uid>/<run_id>
<staging_root>/<case_uid>/<operation_id>/
<analysis_root>/<case_uid>/<analysis_id>
```

构建和运行在其 identity 提交之后即不可变。原始数据
在执行/数据 Site 保持权威；只取回盘点清单、日志、
图件、报告或明确选定的子集。

## 源权威

每个 Case 只有一个可编辑的源权威。干净的 Git 工作树或
内容寻址 manifest 标识其确切内容。脏文件和未跟踪
文件也包含在 manifest 中；仅有 `dirty=true` 不构成一个 identity。
其他检出目录在证明完全相等之前都只是副本。PGen、TOML 和
design 的编辑只发生在源权威处。

## 执行边界

控制器推导允许的根目录和不可变的 Step 请求。Site
执行器只能在这些根目录之下写入，且绝不写 `router.db`。
receipt 保留在 Operation 的暂存根目录下，以便 Apply 在
控制器进程丢失后能够恢复。

Site 本地的 module 配置或策略应放在受信任的 Site 适配器中，
而不是 record 原语参数或通用 Router 核心中。密码、令牌、私钥、可变
会话记忆以及完整的 skill 副本都不应进入项目或控制器状态。
