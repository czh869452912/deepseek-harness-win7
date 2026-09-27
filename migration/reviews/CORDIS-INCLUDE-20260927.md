# Include 初次加载与刷新串行化

前三轮已提交于 `24691c8d3415c4579f203f79c78f94386107f0de`，本轮工作树
以此为基点；固定上游仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。
契约为 `CON-CORDIS-CORE@5`，未声明完整验收或解锁下游。

## 触发与差异

C39 用真实 JSON 文件启动 Include，初始插件配置为 1，插件启动由 gate 暂停。
此时把文件改为配置 2 并调用 refresh，然后释放初始启动。

- 上游：初次 apply 先完成，再处理 refresh，最终配置为 2；轨迹为
  `start:1 → ready:1 → stop:1 → start:2 → ready:2`。
- 修复前 Python：初次 apply 和 refresh 没有共用串行路径，最终旧加载覆盖
  新刷新，配置仍为 1，轨迹止于 `start:1 → ready:1`。

`_IncludeInitDual` 过去在构造时直接调用 root.update，并提前发布 content/data。
后续 refresh 和内部配置更新虽然使用 `_apply_lock`，但不能阻止这一初始调用
与它们重叠。上游的 init apply、refresh 和同路径更新统一经过 applyQueue。

## 修改及闭包

ambient-loop 初次 apply 现在通过同一个 `_apply_lock`，子树更新成功后才提交
content/data。新任务通过 EntryTree._track 持有，由 Service.init 等待；没有
把异步任务变成无人负责的后台操作。无 ambient loop 的同步入口保留。

本轮不更改 Loader/HMR 接口。验证覆盖 Include、实际 Loader 子树、Cordis
生命周期，以及既有事件/取消/HMR 消费者回归。仍须单独检查 initial failure
与 pending disposal 的交错，不能由串行成功案例推断它们已覆盖。

## 场景与证据

| 场景 | 修复前 | 修复后 |
|---|---|---|
| C37 一次 refresh 等待中再发起一次 | 匹配 | 匹配 |
| C38 前一次 refresh 失败，后一次继续 | 匹配 | 匹配 |
| C39 初次 apply 等待中发起 refresh | 最终配置错误 | 匹配 |

`CORDIS-INCLUDE-BEFORE-20260927.json` 保留原始差异；
`CORDIS-C1-C39-20260927.json` 重跑全部 39 项。新增离线回归直接使用 BEFORE
报告中的上游观测作为预期，未使用修复后的 Python 输出生成断言。
测试日志、环境和输入摘要见 `RUN-CORDIS-INCLUDE-20260927.json`。

两个适配器均通过真实文件和 builtin 插件调用 Include；观察子类只捕获实例，
不覆写算法。C39 的 50ms 窗口用于观察 pending 阶段，最终配置和完整轨迹才是
关键判据。没有验证磁盘 HMR 事件派发、YAML 方言或 Win7 实机环境。

完整回归初跑暴露两项旧测试在 sleep(0) 后读取未提交状态，提前失败又遗留任务，
引起另外两项清理警告断言失败。补丁功能测试已使用真实插件并等待 mount 结束；
另加失败用例验证导入异常传播、content/data 不发布、子树回滚、最终根卸载无残留。
没有通过增加 sleep 次数或跳过测试来恢复通过。初跑日志和最终重跑均归档。
初次导入失败后的即时 fiber 状态仍需与上游单独对照；新增失败测试仅断言
错误/数据边界及最终 DISPOSED，不宣称即时状态已完成双侧认证。

## 下一批

先补 Include 初次失败与在途卸载交错，再推进真实模块热替换、缓存失效及
失败回滚。模块替换需同时验证 Loader registry、fiber 和必要消费者，不按
文件边界分割接口修复。旧 portable 和跨盘搜索基线任务仍保留。
