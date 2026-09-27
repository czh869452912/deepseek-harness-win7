# Include 失败、卸载与 registry 返回对象身份

固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；工作树基于
`24691c8d3415c4579f203f79c78f94386107f0de`，包括上一轮未提交的 Include
串行化修复。本轮契约 `CON-CORDIS-CORE@6` 仍为 draft，未建立 acceptance。

## 新增观察

| 场景 | 当前结果 | 语义 |
|---|---|---|
| C40 | 匹配 | 单个 gated 子插件初始失败：错误保留、data/content 未提交，FAILED 后可卸载 |
| C41 | 匹配 | 初次加载时卸载：等待在途启动，清理一次，最终 DISPOSED |
| C42 | **不匹配** | 已激活 Include 刷新中卸载：上游在子插件 gate 释放前完成；Python 在子插件清理后完成 |
| C43 | 匹配 | 两个子项失败，捕获聚合错误并等待 tree 后：即时状态两侧均 LOADING，根卸载后 DISPOSED |
| C44 | 修复后匹配 | 重复公共 dispose 不等待；结构所有者仍能等待原清理 |
| C45 | **不匹配** | registry 返回包装对象，await 后得到原始 fiber；Python 返回同一个对象 |

C41 最后仍可在 Include.store 中观察到已处置行，两侧一致；本轮没有将其
自行“清空”来制造更整洁的结果。C43 也不能被误改成“捕获异常就必须 FAILED”。

## C44 的局部修复

上游 fiber.dispose 是 parent.effect 返回的单次调用包装函数。重复公共调用
返回 undefined；结构清理通过 runDisposable/effectInertia 等待已启动的清理。
Python 先前所有重复调用均返回共享等待对象，将两种接口混为一谈。

现在公开 dispose 对重复调用返回立即完成的 awaitable（Python 语法适配），
父级 effect 调用 `_dispose_owned()`，仍持有共享 Task，并通过 shield 保护
清理不被观察者取消。root 没有这一单次限制，保持 restartable。
C25/C27/C30 重复 effect、根所有权及观察者取消场景继续匹配。

全量初跑有一项旧取消测试用“再调用 dispose”等待清理，与新证据 C44 冲突。
它已改为先验证重复调用立即完成且仍在 UNLOADING，再由根所有者等待并验证
DISPOSED。保留取消不影响共享清理的断言，没有跳过测试。

## C42/C45：优先处理的架构缺口

`reference/vendor/cordis/src/registry.ts` 返回 `Object.create(fiber)`，其 then
闭包调用原始 fiber.await；这不是普通的“同一个 fiber 可 await”接口。
包装对象继承方法，在其上调用 update 会产生自己的状态字段；继承的 dispose
闭包仍作用于原始 fiber。C45 的直接观测为：

| 观测点 | 上游 | Python |
|---|---|---|
| 返回对象与 await 结果相同 | false | true |
| 更新等待期间 handle/raw 状态 | LOADING / ACTIVE | LOADING / LOADING |
| handle.dispose 后 handle/raw 状态 | ACTIVE / DISPOSED | DISPOSED / DISPOSED |

Loader Entry 保存 registry.plugin 的直接返回对象，再调用其 await/update；
这让包装对象语义进入实际 Include 刷新和卸载路径。C42 原始完整事件轨迹也
保留了差异：上游 `dispose-complete → ready:2 → stop:2`，Python 是
`ready:2 → stop:2 → dispose-complete`。50ms pending 观察窗口之外，最终
事件顺序同样不同；不能把差异归为计时抖动。

C44 修复并未消除 C42，不能通过提前取消 Python 清理或删除事件观测来掩盖。
本轮保留两项开放发现，默认 runner 执行全部 45 项并返回 1（43 匹配、2 不同）。
离线 pytest 中新增四项已匹配场景；C42/C45 的执行入口是双侧 runner，未标 xfail。

## 下一批实现顺序

1. 先定义 Python 对应的 registry 返回 handle：await 解析到原始 fiber；明确
   哪些字段读取继承、哪些方法写入 handle、dispose 闭包属于谁。
2. 核对 Registry、Context.plugin、Loader 两套 Entry 实现、Include、HMR 和
   boot 的实际调用入口。提供端与这些必要消费端共同修改，不能按文件权限拆开。
3. 覆盖 raw/handle 两条 update、restart、await、dispose 及父级清理路径；
   重跑 C42/C45，并保留已经匹配的 C25/C27/C30/C39–C44。
4. 再推进模块 HMR 的实际热替换、缓存失效和失败回滚；在本身份契约关闭前
   不迁移新的上层模块，也不放行 MIG-SPINE-001。

## 证据

修复前公共处置差异见 `CORDIS-LIFECYCLE-PUBLIC-BEFORE-20260927.json`；
身份最小探针见 `CORDIS-HANDLE-IDENTITY-20260927.json`；当前完整结果见
`CORDIS-C1-C45-20260927.json`。执行日志、输入和摘要登记在
`RUN-CORDIS-LIFECYCLE-20260927.json`。这些均是工作树历史观察，不是固定
候选验收，不包含 Win7、portable 重建或真实 provider 认证。
