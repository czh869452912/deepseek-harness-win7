# Registry handle 身份与 Include 卸载顺序

基于已提交的 `777a6693`，固定上游仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。
本轮是工作树观察，`CON-CORDIS-CORE@7` 保持 draft，MIG-CORDIS-001 保持 review。

## 实现与依据

上游 registry.ts 使用 `Object.create(fiber)` 返回 handle，then/dispose 闭包仍绑定原始
fiber。Python 新增 FiberHandle：未写入的字段从原始对象读取，方法写入保留在 handle，
共享 epoch 和资源集合；registry 清单与 Context.fiber 继续保留原始对象。

`await handle` 等待原始 fiber；`handle.await_settled()` 先等待 handle 自身，再等待原始
fiber，模拟 JS async return-this 的 thenable assimilation。后者通过失败恢复探针发现，
不能仅凭源码中的 `return this` 认定 Promise 返回 handle。

## 双端证据

- C42：Include 刷新中的卸载顺序恢复一致，未取消在途清理。
- C45：handle 与 raw 身份不同；更新 handle 后字段独立，dispose 仍作用于 raw。
- C46：失败后仅更新 handle，handle ACTIVE、raw FAILED；await 仍抛原始启动错误。
- C47：直接更新 raw 可恢复原始错误，未被遮蔽的 handle 字段随 raw 改变。

完整 C1–C47 双端运行全部匹配；报告为 `CORDIS-C1-C47-20260927.json`。
离线生命周期回归加入 C42/C45/C46/C47，期望来自同一固定上游的实际输出。
历史 C42/C45 失败报告保留，不覆盖、不标 xfail。

现有七项测试的身份假设同步修正：注册清单和插件发布事件断言原始 fiber；原始
fiber 的失败恢复与依赖重检测试显式使用 raw。没有引入相等运算来混淆两个对象。

全量首跑另发现四处消费端测试身份断言，以及一项真实的 Preset 挂载审计回归。
`mount_preset` 原先保存 registry 返回对象，导致祖先比较无法识别子树发布的全局
服务。现在保存 await 得到的原始 fiber，与上游 mount.ts 从子树上下文记录的 owner
一致；原有泄漏拒绝测试保留。修复同时覆盖 service_for_agent 的子树查找，未绕过审计。

## 后续门槛

先补齐 handle/raw restart、依赖重检双端探针，再推进模块 HMR 实际替换、缓存失效、
失败回滚。C1–C47 是本地场景编号，不能视作全部官方用例覆盖；上层迁移仍受核心
契约门槛约束。完整测试结果及输入摘要见 `RUN-CORDIS-HANDLE-20260927.json`。
本轮没有 Win7 真机、portable 重建或真实 provider 认证。
