# 新模拟工作流

## 目标

从一个物理目标出发，创建可复现的 Entity simulation run。

## 步骤

1. 定义物理目标，以及判断成功所需的最小诊断。
2. 探测 Entity checkout 和版本。
3. 选择 engine、metric、dimension 和 pgen。
4. 读取当前 `input.example.toml`。
5. 起草 TOML 和 pgen/setup 参数。
6. 决定输出 quantities 和 cadence。
7. 决定 checkpoint 策略。
8. 使用明确 backend 和 architecture flags 编译。
9. 运行 reduced smoke case。
10. 检查 metadata、errors、logs 和 stats。
11. 记录 run manifest。

## 停止条件

如果请求行为需要修改 `src/`，停止并路由到 development。

如果 build 或 runtime failure 不能由配置解释，停止并路由到 debug。

如果问题是解释输出而不是生成 run，停止并路由到 analysis。

