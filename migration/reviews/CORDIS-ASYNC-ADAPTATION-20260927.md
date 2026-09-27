# 已完成 await 的语言适配

C58 是原生语言边界诊断：JS await Promise.resolve() 必须让出执行；Python 3.8 await 已完成 Future 不让出执行。即使手动驱动 coroutine，已完成 Future 也不会把控制权交还调用者。不能在框架外层捕获一个不存在的挂起点，除非改写用户回调字节码或替换 Python 运行时。

C59 验证迁移写法：当上游已完成 Promise 的让出行为参与可观察时序，Python 回调显式 await asyncio.sleep(0)。同步前缀与后续监听顺序匹配。

不修改日志排序或删除 C58。默认 runner 继续报告这个真实差异，返回 1；它是已说明的语言限制，不代表任何 Python 代码都已被自动转换成 JS microtask 语义。原生插件作者和后续迁移需要遵守此规则。

Loopless 同步入口是 Python 特有适配，由本地回归覆盖；不得将其称作上游 JS 的独立同步事件循环。无 Win7 真机验证按用户要求移出本轮。
