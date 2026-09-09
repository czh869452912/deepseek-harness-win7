# G5-fiber 盲审报告

> 审计说明：任务描述给出 `dsh/cordis/fiber.py` 为 937 行，实际逐行读取为 **1033 行**，本报告以实读内容为准。证据仅来自源码本身（未使用 docs/、未运行任何命令修改系统）。TS 侧引用均为 `reference/vendor/cordis/src/fiber.ts`（简写 TS），Python 侧为 `dsh/cordis/fiber.py`（简写 PY）；个别跨文件证据来自 `dsh/cordis/registry.py`、`dsh/cordis/schema.py`、`dsh/cordis/utils.py`、`dsh/cordis/events.py`，均标注完整路径。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| `ValidationError` fiber.ts:19-40 | `dsh/cordis/schema.py:17-43`（fiber.py:11 导入） | ADAPT（见 D32） |
| `kValidationError` brand fiber.ts:16,38-40 | 无（schema.py 无等价 brand） | ADAPT（D32） |
| `resolveConfig` fiber.ts:50-62 | `resolve_config` fiber.py:36-62 | D1 |
| `Disposable/Effect/SyncEffect/AsyncEffect` 类型别名 fiber.ts:74-93 | 无类型别名（鸭子类型，effect() 内联判定） | n/a（动态语言） |
| `AsyncDisposable`（thenable 契约）fiber.ts:64-66,555-559 | `cancel_effect`（普通函数，无 `__await__`）fiber.py:264-468 | D10 |
| `EffectMeta` fiber.ts:96-101 | `EffectMeta` fiber.py:65-75 | 1:1（children 未填充 → D30） |
| `EffectRunner` fiber.ts:103-108 | `effect()` 闭包状态（disposables/executing/disposed 等）fiber.py:223-231 | ADAPT（结构内联，行为差异见 D9/D11/D18） |
| `effectInertia` + `runDisposable` fiber.ts:110-117 | 无直接等价（由 `cancel_effect` 的 `disposed` 守卫部分覆盖）fiber.py:265-267 | D24 |
| `emitPluginDisposed` fiber.ts:119-137 | `_emit_plugin_disposed` fiber.py:874-909 | D22 |
| `FiberState` fiber.ts:147-154 | `FiberState` fiber.py:15-21 | 1:1（值序一致 0-5） |
| `CordisError` + `Code` fiber.ts:156-174 | `CordisError` + `CODE_MESSAGES` fiber.py:24-33 | 1:1 |
| `INACTIVE = '__INACTIVE__'` fiber.ts:176 | `INACTIVE_EPOCH` fiber.py:78 | 1:1 |
| `Fiber` 构造器（插件分支）fiber.ts:222-319 | `Fiber.__init__` 插件分支 fiber.py:89-161（注册/发布/checkImpl/refresh 移至 registry.py:344-362） | D2 |
| `Fiber` 构造器（root 分支）fiber.ts:320-332 | fiber.py:162-167 | 1:1（root dispose 见 D28） |
| `get name()` fiber.ts:336-343 | `name` property fiber.py:169-188 | D20 |
| `assertActive()` fiber.ts:351-354 | `assert_active(check_error=True)` fiber.py:200-204 | D12 |
| `_execute(runner)` fiber.ts:356-400 | 内联进 `effect()` 各分支 fiber.py:369-465 | D9/D11/D18 |
| `effect(execute, label)` fiber.ts:415-561 | `effect(execute_or_disposer, label, is_disposer)` fiber.py:213-468 | D9/D10/D11/D18/D19 |
| `getEffects()` fiber.ts:568-572 | `get_effects()` fiber.py:474-476 | D30 |
| `_getState()` fiber.ts:574-579 | `_get_state()` fiber.py:816-823 | 1:1 |
| `_updateState(callback)` fiber.ts:581-595 | `set_state(new_state)` fiber.py:482-498 | D31 |
| `_checkImpl(name)` fiber.ts:597-609 | `_checkImpl(name)` fiber.py:500-522 | D16 |
| `_refresh()` fiber.ts:611-623 | `_refresh()` fiber.py:524-554 | D5 |
| `_setEpoch(epoch)` fiber.ts:625-639 | `set_epoch(epoch)` fiber.py:556-574 | 1:1（三分支与 TS else 合并等价；inertia 守卫见 D25） |
| `_resolveConfig(config)` fiber.ts:641-644 | `_resolve_config(config)` fiber.py:206-211 | D1 |
| `_reload()` fiber.ts:646-673 | `_reload()` fiber.py:633-814 | D6/D7/D8/D14/D15 |
| `_unload()` fiber.ts:675-696 | `_unload()` fiber.py:825-872 | D17 |
| `await()` fiber.ts:704-710 | `await_settled()`/`__await__`/`await_` fiber.py:197-198,1012-1030 | D13 |
| `restart()` fiber.ts:718-723 | `restart(new_config=None)` fiber.py:982-1010 | D21 |
| `update(config, noSave)` fiber.ts:736-753 | `update(config, no_save)` fiber.py:954-980 | D23 |
| `dispose`（构造器内创建的效果包装器）fiber.ts:265-297 | `dispose()` 方法 fiber.py:911-952 + parent effect 挂接 fiber.py:159-161 | D2/D3 |
| `_hooks` fiber.ts:202 | `_hooks` fiber.py:131 | 1:1（两侧均未使用） |
| `store: Dict | undefined` fiber.ts:198,324,647,687 | `store` fiber.py:108,637,848,867 | D27 |
| `DisposableList`（utils.ts:5-40） | `DisposableList`（utils.py:220-299，id()+绑定方法回退代替 WeakKey） | ADAPT |
| `composeError`（utils.ts:268-281，用于 _execute/_unload） | `compose_error` 仅导入未使用（fiber.py:12；全文件零调用） | D29 |
| 无 | `resolve_config` 的 `None→{}` 默认化 fiber.py:40-43 | D1 |
| 无 | `disposable()` fiber.py:470-472 | D29 |
| 无 | `error` property fiber.py:478-480 | D29 |
| 无 | `_instantiate_plugin` fiber.py:576-631 | D6 |
| 无 | `_in_flight_effects` fiber.py:132 | D29 |
| 无 | `entry` 管线 fiber.py:103-107,142-144 | D29 |
| 无 | `Fiber._uid_counter` 回退 fiber.py:87,139-141 | D29 |
| 无 | `__getattr__` 委托 plugin fiber.py:190-195 | D29 |
| 无 | `__repr__` fiber.py:1032-1033 | D29 |

## 差异

### D1: resolve_config 自发明配置默认化与 schema 来源扩展
- TS: `fiber.ts:50-62`
```ts
export function resolveConfig(runtime: Plugin.Runtime, config: any) {
  if (!runtime.Config) return config
  // TODO: async validation
  const result = runtime.Config['~standard'].validate(config)
  if ('then' in result) {
    throw new TypeError('Async config validation is not supported')
  }
```
- PY: `fiber.py:36-62`
```python
if config is None and isinstance(getattr(plugin, "config", None), dict):
    config = dict(getattr(plugin, "config", {}))
elif config is None:
    config = {}
schema = getattr(plugin, "schema", None) or getattr(plugin, "Config", None)
if not schema and runtime is not None:
    schema = getattr(runtime, "schema", None) or getattr(runtime, "Config", None)
```
- 判定： MUST-FIX
- 影响： TS 原样把 `null/undefined` config 交给 schema 校验；PY 把它替换为 `{}` 或 `plugin.config` 类属性缺省值，且 schema 来源从"仅 `runtime.Config`"扩成 plugin.schema/Config + runtime 回退。校验输入与"无 schema 直通"的边界都被改变。
- 建议修法： 在 `resolve_config` 删除 None→`{}`/`plugin.config` 默认化分支，schema 仅取 `runtime.Config`（保持 `_resolve_config` fiber.py:206-211 的调用面不变）；plugin 实例的 `.config` 缺省交给 schema 层处理。

### D2: 构造器生命周期职责迁移至 registry.py，且丢失 parent-UNLOADING 门控
- TS: `fiber.ts:265-297,310-319`
```ts
this.dispose = parent.fiber.effect(() => {
  const remove = runtime.fibers.push(this)
  return async () => { this.uid = null; emitPluginDisposed(this.context, this); ... }
}, 'ctx.plugin()')
...
if (this.uid !== null && parent.fiber.state !== FiberState.UNLOADING) {
  for (const name of Object.keys(this.inject)) { this._checkImpl(name) }
  this._refresh()
}
```
- PY: `fiber.py:159-161`（effect body 不注册 `runtime.fibers`，label 自定）；注册/发布/依赖评估被移至 `dsh/cordis/registry.py:344-362`：
```python
# fiber.py:159-161
parent_fiber.effect(lambda: (lambda: self.dispose()), label=f"child_fiber({self.uid})")
# registry.py:359-362 —— 无 `parent.fiber.state !== UNLOADING` 门控
for name in list(fiber.inject.keys()):
    fiber._checkImpl(name)
fiber._refresh()
```
- 判定： MUST-FIX（门控缺失）；职责迁移本身 DEVIATION-PERMITTED（顺序 add_fiber→emit→checkImpl→refresh 与 TS 一致，registry.py:346-357 的发布失败回滚也镜像 TS:299-308）。
- 影响： 父 fiber 正在 UNLOADING 时仍会对子 fiber 做 `_checkImpl/_refresh`，可能在注定被卸载的父级下触发子插件加载；效果标签 `child_fiber(uid)` vs `'ctx.plugin()'` 使 `get_effects` 诊断不可对照。
- 建议修法： 在 registry.py:359 前补 `parent_ctx.fiber` 的 UNLOADING/PENDING 检查；label 改为 `'ctx.plugin()'`。

### D3: dispose() 对 UNLOADING/DISPOSED 早退，不清 uid、不广播 internal/plugin
- TS: `fiber.ts:267-276`（disposer 无条件开头执行）
```ts
return async () => {
  this.uid = null
  emitPluginDisposed(this.context, this)
  if (this.ctx.registry.has(runtime.callback)) {
    remove()
    ...
  }
  this._setEpoch(INACTIVE)
```
- PY: `fiber.py:921-925`
```python
if self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
    return
self.uid = None
self._emit_plugin_disposed()
```
- 判定： MUST-FIX
- 影响： 依赖驱动的 UNLOADING 进行中（异步 disposer 未完成）调用 `dispose()` 会整体空转：uid 不清空、`internal/plugin` 不发布、`runtime.fibers` 不移除，与 TS 的"dispose 必达"语义相反。
- 建议修法： 删除 `fiber.py:921-922` 的状态早退，改为幂等守卫（如 `self._disposing` 标志），保留 `uid=None → 广播 → 注册表清理 → set_epoch → 等 inertia` 的无条件次序。

### D4: intercept 映射剥离 `required` 键（自发明注入配置改写）
- TS: `fiber.ts:238-245`
```ts
const injectEntries = Object.entries(this.inject)
if (injectEntries.length) {
  this.ctx[Context.intercept] = Object.create(parent[Context.intercept])
  for (const [name, config] of injectEntries) {
    if (isNullable(config)) continue
    this.ctx[Context.intercept][name] = config
  }
}
```
- PY: `fiber.py:150-157`
```python
for name, config in self.inject.items():
    if config is not None:
        if isinstance(config, dict):
            clean_cfg = {k: v for k, v in config.items() if k != "required"}
            if clean_cfg:
                self.ctx._intercept_map[name] = clean_cfg
```
- 判定： MUST-FIX
- 影响： TS 将注入配置原样下传服务（服务侧自行合并 intercept，见 vendor service.ts:87-93）；PY 静默删除 `required` 键、丢弃"剥空后的空 dict"，服务看到的 intercept 配置与 TS 不同。
- 建议修法： `fiber.py:152-157` 直接 `self.ctx._intercept_map[name] = config`，`required` 语义只在 `_refresh`（见 D5）读取，不改写 intercept 载荷。

### D5: _refresh 自发明 required/optional 注入语义 + 依赖 fiber 状态检查
- TS: `fiber.ts:611-623`
```ts
_refresh() {
  let epoch: string | boolean = false
  epoch = ''
  for (const name of Object.keys(this.inject)) {
    const impl = this._store[name]
    if (!impl) { epoch = INACTIVE; break }
    epoch += ':' + impl.fiber.uid
  }
  this._setEpoch(epoch)
}
```
- PY: `fiber.py:531-552`
```python
is_required = config.get("required", True) ...
impl = self._store.get(name)
if not impl:
    if is_required: epoch = INACTIVE_EPOCH; break
    continue
fib = getattr(impl, "fiber", None)
if fib is not None and fib.state != FiberState.ACTIVE and ...:
    if is_required: epoch = INACTIVE_EPOCH; break
```
- 判定： MUST-FIX
- 影响： (a) TS 中注入项缺失一律 INACTIVE，PY 允许"非必需"缺失继续激活——整套 optional 注入语义是自发明；(b) TS 依赖可用性完全由 reflect 通知驱动 `_checkImpl` 重算，PY 额外直查依赖 fiber 的 `state != ACTIVE`，激活/失活时机提前/错后于 TS。
- 建议修法： `_refresh` 删除 `is_required` 分支与 `fib.state` 检查，恢复"缺 impl 即 INACTIVE、否则累加 `:uid`"的纯复合 epoch；optional 语义如需保留，应在 registry 的注入解析层（对应 vendor registry.ts:16-34）实现并单独记录。

### D6: 插件实例化启发式 + 实例化先于 config 解析（构造器拿到未校验 config）
- TS: `fiber.ts:250-259,654-656`
```ts
execute: function () {
  if (isConstructor(runtime.callback)) {
    const instance = new runtime.callback(this.ctx, this.config)
    ...
// _reload 内：
if (this._runner.epoch === oldEpoch) {
  this.config = this._resolveConfig(this._config)
  await this._execute(this._runner)
```
- PY: `fiber.py:637-643`（`_instantiate_plugin` 于 fiber.py:576-631，签名嗅探 Service/Plugin/普通类三种约定，如 `cls(self.ctx, config=self.config)`）
```python
self.store = dict(self._store)
if getattr(self, "_plugin_cls", None) is not None:
    self.plugin = self._instantiate_plugin()      # 此刻 self.config 还是原始 config
self.config = self._resolve_config(self._config)
...
if hasattr(self.plugin, "config"):
    self.plugin.config = self.config              # 事后补丁
```
- 判定： MUST-FIX
- 影响： TS 每次重载以**已校验** config 构造新实例；PY 构造发生在 `_resolve_config` 之前，构造器收到的 `config=` 是原始/上一轮 config，仅靠事后 `plugin.config` 属性补丁，构造期读取 config 的插件拿到错值。
- 建议修法： `_reload` 调整次序为先 `self.config = self._resolve_config(self._config)` 再实例化；`_instantiate_plugin` 收敛为统一 `cls(self.ctx, config=self.config)` 约定（或把嗅探逻辑上移到 registry 的 runtime 包装层），删除三种分支猜测。

### D7: 自发明 teardown 自动注册
- TS: `fiber.ts` 全文无 `teardown` 概念（插件清理仅经 effect/`Service[symbols.init]` 返回的 disposer，见 fiber.ts:250-261）。
- PY: `fiber.py:724-725`
```python
if hasattr(self.plugin, "teardown") and callable(self.plugin.teardown):
    self.effect(self.plugin.teardown, label=f"teardown({self.name})", is_disposer=True)
```
- 判定： MUST-FIX
- 影响： 带 `teardown` 方法的插件在 TS 下不会注册任何清理，PY 会——同一插件在两侧的卸载行为不同（多出一次 teardown 调用）。
- 建议修法： 删除该分支；如 Python 生态确需 teardown 约定，应作为独立适配层记录为 DEVIATION-PERMITTED 并在文档声明，而不是藏在 `_reload`。

### D8: apply/init 调用约定签名嗅探 + 返回值宽松处理
- TS: `fiber.ts:258-259`（函数插件固定两参调用）
```ts
} else {
  return runtime.callback(this.ctx, this.config)
}
```
- PY: `fiber.py:729-759`（`apply(ctx, config)` vs `apply(ctx)` 按 `inspect.signature` 嗅探；dict 插件、可调用 plugin 分支；`_async_wait_res` fiber.py:761-769 还接受 promise 解析出 generator/asyncgen——TS `safeCollect` 只接受函数，非函数真值直接 `TypeError('Invalid effect')`，见 fiber.ts:359-364）
- 判定： MUST-FIX
- 影响： 同一插件在两侧被以不同实参调用；`apply` 返回 awaitable 且解析出非 callable 的场景，TS 抛 Invalid effect，PY 静默忽略（或注册 effect），错误被吞。
- 建议修法： 统一 Python 插件契约为 `apply(ctx, config)`（或函数 `(ctx, config)`），删除签名嗅探；`_async_wait_res` 对非 callable、非 None 的解析值按 TS 抛 `TypeError("Invalid effect")`。

### D9: effect 取消屏障路径双重调用 async setup 的 disposer
- TS: `fiber.ts:475-483,511`
```ts
const disposeAfter = (setup: PromiseLike<void>) => {
  return Promise.resolve(setup).then(() => dispose(), async (reason) => { await dispose(); throw reason })
}
...
if (executing) return disposeAfter(waitForSetup())
```
TS 中 async setup 的 disposer 仅经 `safeCollect` 进入 `disposables`，由 `dispose()` 统一执行一次。
- PY: `fiber.py:376-391` 先 `collect_disposer(cleanup)`（进 disposables）再 `set_result(cleanup)`；取消路径 `fiber.py:271-297` 又单取一次：
```python
cleanup_fn = await barrier
if callable(cleanup_fn):
    r = cleanup_fn()          # 第一次
...
while disposables:
    disp = disposables.pop()
    r = disp()                # cleanup_fn 仍在 disposables 中 → 第二次
```
- 判定： MUST-FIX
- 影响： "setup 进行中即取消"时，async setup 返回的清理函数被调用两次（对非幂等 disposer 如 `close()`/`unlink()` 是真实故障）。
- 建议修法： `_dispose_after_barrier` 删除 barrier 结果的单独调用（或 `collect_disposer(cleanup)` 改为 set_result 后不再入列），保证每个 disposer 恰好执行一次，与 TS `disposeAfter` 对齐。

### D10: effect 返回包装器缺 thenable 契约（await 不触发 dispose）
- TS: `fiber.ts:550-560`
```ts
const disposeAsync = () => { if (!runner.epoch) return; runner.epoch = false; return finalizeDisposal(dispose) }
wrapper.then = async (onFulfilled, onRejected) => {
  return Promise.resolve(task).then(() => disposeAsync).then(onFulfilled, onRejected)
}
```
- PY: `fiber.py:466-468`
```python
executing = False
return cancel_effect
```
- 判定： MUST-FIX
- 影响： TS 契约 `await ctx.effect(...)` 会等待 setup 完成并**触发清理**；PY 返回普通函数，await 它直接 `TypeError`，`dsh` 侧若有 `await` 用法即行为分叉。
- 建议修法： 为 `cancel_effect` 补 `__await__`（等价 `wrapper.then`：先等 setup_task，再执行取消并返回结果），或提供显式 `await_dispose()` 并审计调用点。

### D11: 同步生成器 effect 的 epoch 中断 + asyncgen 的 aclose（TS 均无）
- TS: `fiber.ts:375-382`（同步 iterator 无 epoch 检查，跑满为止）
```ts
} else if (Symbol.iterator in effect) {
  info.error = new Error()
  const iter = effect[Symbol.iterator]()
  while (true) {
    const result = iter.next()
    safeCollect(result.value)
    if (result.done) return
  }
}
```
- PY: `fiber.py:404-412`（sync gen 每项检查 `self.epoch != old_epoch` 并 `res.close()`）；`fiber.py:427-432`（asyncgen epoch 失效时 `await res.aclose()`，TS fiber.ts:389-394 仅停止消费、不关闭迭代器）
- 判定： MUST-FIX
- 影响： epoch 翻转时 PY 提前中断同步生成器（后续 disposer 不注册）并对异步生成器触发其 `finally` 清理——两侧注册的 disposer 集合与生成器侧效果生命周期都不一致。
- 建议修法： 删除 sync 分支的 epoch 检查（TS 语义：同步消费必然完成）；async 分支保留 epoch 检查但移除 `aclose()`（仅 `break` 停止消费），与 TS 一致。

### D12: assert_active 增加 check_error 分支（默认抛存储错误）
- TS: `fiber.ts:351-354`
```ts
assertActive() {
  if (this.uid !== null) return
  throw new CordisError('INACTIVE_EFFECT')
}
```
- PY: `fiber.py:200-204`
```python
def assert_active(self, check_error: bool = True) -> None:
    if self.uid is None:
        raise CordisError("INACTIVE_EFFECT")
    if check_error and self._error is not None:
        raise self._error
```
- 判定： MUST-FIX
- 影响： 外部默认调用 `assert_active()` 在 fiber FAILED 时抛上次启动错误，而 TS 只做 disposed 检查——对 `update`/`restart` 之外的调用者是新增失败模式（内部调用点均传 `check_error=False` 规避，恰说明默认值与设计相反）。
- 建议修法： 默认 `check_error=False`（或删掉该参数，`_error` 的重抛只保留在 `await_settled`/`restart` 的 settle 路径）。

### D13: await_settled 吞掉 inertia 异常
- TS: `fiber.ts:704-710`
```ts
async await() {
  while (this.inertia) { await this.inertia }
  if (this._error) throw this._error
  return this
}
```
- PY: `fiber.py:1014-1018`
```python
while self.inertia is not None and not self.inertia.done():
    try:
        await self.inertia
    except Exception:
        pass
```
- 判定： MUST-FIX
- 影响： TS 明确让 inertia 的拒绝向上传播（fiber.ts:287-292 注释：inertia 拒绝即不可恢复错误）；PY 静默吞掉后仅靠 `_error` 兜底，非 `_error` 路径的失败（如 unload 清理炸掉）对等待者不可见。
- 建议修法： 去掉 `except Exception: pass`，与 TS 一致直接传播。

### D14: _reload 缺少微任务失效检查点
- TS: `fiber.ts:650-658`
```ts
await Promise.resolve()
// A disposer queued before this checkpoint may already have invalidated the load.
if (this._runner.epoch === oldEpoch) {
  this.config = this._resolveConfig(this._config)
  await this._execute(this._runner)
```
- PY: `fiber.py:633-640`：`epoch = self.epoch` 记录后**同步**执行实例化/解析/apply，无任何让出点复查；仅异步路径在任务内复查（fiber.py:669,701,770）。
- 判定： MUST-FIX
- 影响： 排队在 reload 之前、同轮事件循环内已使 epoch 失效的 disposer 无法阻止 PY 运行插件代码（TS 会跳过，由尾部状态机排空）。
- 建议修法： `_reload` 改为 coroutine：先 `await asyncio.sleep(0)` 再复查 `self.epoch != epoch` 则直接返回（尾部状态机照旧），或等价地在同步入口先排空一次 pending 取消。

### D15: 异步 init/apply 失败在处理完后又 re-raise，任务异常无人消费
- TS: `fiber.ts:659-664`
```ts
} catch (reason) {
  // impl guarantees that the error is non-null (?)
  this.ctx.logger.error(reason)
  this._error = reason
  this._runner.epoch = INACTIVE
}
```
（吞掉，尾部 `_updateState` 驱动 unload；无 rethrow）
- PY: `fiber.py:675-683`（`_run_async_init`）、`fiber.py:776-785`（`_async_wait_res`）——记录 `_error`、置 FAILED、触发 `_unload()` 后：
```python
self.set_state(FiberState.UNLOADING)
self._unload()
raise e          # 任务以异常收尾，且该任务不被 _in_flight_effects 追踪
```
- 判定： MUST-FIX
- 影响： 该 Task 的异常无人 await（`self.inertia` 随即被 `_unload` 的清理 Task 覆盖，fiber.py:858），产生 "Task exception was never retrieved" 噪声，且与 TS "inertia 永不拒绝"的注释契约相悖。
- 建议修法： 删除三处 `raise e`（fiber.py:683,715,785），失败后仅落 `_error`/状态机；同时把 reload 的 Task 也纳入 `_in_flight_effects` 追踪以便 dispose 排空。

### D16: _checkImpl 缺 getTraceable 绑定、日志降为 warn、防御性早退
- TS: `fiber.ts:597-609`
```ts
const impl = this.ctx.reflect._getImpl(name, true)
if (!impl) return delete this._store[name]
try {
  if (impl.check && !impl.check.call(getTraceable(this.ctx, impl.value))) {
    return delete this._store[name]
  }
} catch (error) {
  impl.fiber.ctx.logger.error(error)
  return delete this._store[name]
}
```
- PY: `fiber.py:505-517`
```python
if not self.ctx or not hasattr(self.ctx, "reflect"): return
impl = self.ctx.reflect._get_impl(self.ctx, name, strict=True)
...
if impl.check and callable(impl.check) and not impl.check():
except Exception as e:
    self.ctx.logger("fiber").warn("Exception checking impl availability ...")
```
- 判定： MUST-FIX
- 影响： check 丢失 traceable 上下文绑定（依赖服务实例身份/ctx 的 check 判定可能翻转）；check 抛错日志级别与 TS 不一致；无 reflect 时静默返回（TS 必然有 reflect）。
- 建议修法： `impl.check` 经 `dsh.cordis.utils.get_traceable(self.ctx, impl.value)` 调用（按 Python 反射 API 传参），日志改 `error`，删除 505-506 早退。

### D17: _unload 串行执行 disposer（TS 为 Promise.all 并行）+ 日志级别
- TS: `fiber.ts:676-686`
```ts
await Promise.all(this._disposables.clear().map(async (dispose) => {
  try {
    await composeError(async (info) => { await Promise.resolve(); info.error = new Error(); await runDisposable(dispose) }, ...)
  } catch (reason) { this.ctx.logger.error(reason) }
}))
```
- PY: `fiber.py:827-838`（同步 disposer 顺序 inline 执行，awaitable 收集后 `fiber.py:841-847` 逐个 await），日志用 `.warn`
- 判定： MUST-FIX
- 影响： 卸载耗时与失败顺序可观察地不同：某 disposer 挂起时 TS 其余 disposer 并发推进，PY 阻塞后续全部；日志级别使监控口径错位。
- 建议修法： `_unload` 改为 `await asyncio.gather(*(self._run_one(d) for d in self._disposables.clear()))`（每项独立 try/except + `logger.error`），保持 `store=None` 与尾部状态机在 gather 之后。

### D18: effect 同步失败路径摘除包装器 + rollback fire-and-forget
- TS: `fiber.ts:521-537`（失败时 wrapper 仍留在 `_disposables`，供已在途的 owner unload 经 `runDisposable` 加入；清理链的错误最终 `.catch(logger)`）
```ts
removeWrapper = this._disposables.push(wrapper)
try { task = this._execute(runner) } catch (reason) {
  ...
  cleanup = finalizeDisposal(dispose)
  ...
  if (isObject(cleanup) && 'then' in cleanup) { cleanup.catch(error => this.ctx.logger.error(error)) }
  throw reason
}
```
- PY: `fiber.py:453-463` 失败即 `self._disposables.delete(cancel_effect)`；`rollback_sync` fiber.py:236-252 对 awaitable disposer `loop.create_task(res)` fire-and-forget，既不追踪也不记录失败。
- 判定： MUST-FIX
- 影响： (a) 并发 owner unload 无法再引用该效果（join 语义丢失）；(b) 异步 disposer 的失败彻底丢失且可能产生未消费任务警告。
- 建议修法： 保留 wrapper 于 `_disposables`（依赖 `disposed` 守卫返回 `in_flight_cleanup` 实现 join）；rollback 中 awaitable 统一包成带 `logger.error` 回调的 Task 并入 `_in_flight_effects`。

### D19: effect 异步 setup 任务失败无 catch 消费者
- TS: `fiber.ts:545-548`
```ts
task?.catch(() => {
  if (!runner.epoch) return dispose()
  return finalizeDisposal(dispose)
}).catch((error) => this.ctx.logger.error(error))
```
- PY: `fiber.py:392-399`（`_await_async_setup` 内 `raise async_err` 后仅 `create_task` + 追踪，无 done 回调记录错误；同构问题见 `_consume_async_gen` fiber.py:443-450）
- 判定： MUST-FIX
- 影响： setup Promise 拒绝时 TS 会驱动回滚并落日志；PY 的 setup Task 拒绝无人消费（除非恰好被 dispose/await_settled 排空），错误静默。
- 建议修法： 为 `setup_task` 添加 done-callback：失败时执行一次取消（复用 `cancel_effect`）并 `logger.error`。

### D20: name 属性自发明 plugin.name/plugin.id 回退
- TS: `fiber.ts:336-343`
```ts
get name() {
  let fiber: Fiber = this
  do {
    if (fiber.runtime?.name) return fiber.runtime.name
    fiber = fiber.parent.fiber
  } while (fiber !== fiber.parent.fiber)
  return 'root'
}
```
- PY: `fiber.py:173-180`
```python
if getattr(fiber, "runtime", None) and getattr(fiber.runtime, "name", None):
    return fiber.runtime.name
plugin = getattr(fiber, "plugin", None)
if plugin:
    if hasattr(plugin, "name") and plugin.name: return plugin.name
    if hasattr(plugin, "id") and plugin.id: return plugin.id
```
- 判定： MUST-FIX
- 影响： PY 会在 runtime 未命名时直接取 plugin 实例属性，返回值可与 TS（沿祖先链找命名 runtime，否则 'root'）完全不同；`registry.unload_plugin`（registry.py:419）按 `fiber.name` 匹配，放大该分叉。
- 建议修法： 回退逻辑移到 runtime 装配处保证 `runtime.name` 总被填充；`name` property 严格复刻 TS 遍历。

### D21: restart 自发明 new_config 参数与 _checkImpl 循环；返回 Task/None
- TS: `fiber.ts:718-723`
```ts
async restart() {
  this.assertActive()
  this._setEpoch(INACTIVE)
  this._refresh()
  await this.await()
}
```
- PY: `fiber.py:982-990`
```python
def restart(self, new_config: Optional[Any] = None) -> Any:
    self.assert_active(check_error=False)
    if new_config is not None: self._config = new_config
    self.set_epoch(INACTIVE_EPOCH)
    for name in list(self.inject.keys()):
        self._checkImpl(name)          # TS restart 不重查依赖
    self._refresh()
```
- 判定： MUST-FIX（`new_config` 参数与 `_checkImpl` 循环为自发明）；ADAPT（有事件循环时返回 Task、无循环返回 None——受"asyncio 3.8 兼容写法"约束的等价改写，但建议在无循环时至少同步跑完 `_wait_settled` 逻辑或抛错而非静默 None）
- 影响： restart 会重查依赖使 epoch 可能与 TS 计算不同；`new_config` 使外部可以绕过 `update()` 的校验/waterfall 直接换配置重载。
- 建议修法： 删除 `new_config` 参数与 `_checkImpl` 循环；`update()` 若需换配置走自身路径。

### D22: _emit_plugin_disposed 回调参数元数不同
- TS: `fiber.ts:119-137`
```ts
const args: any[] = ['internal/plugin', fiber]
...
callbacks = context.events.dispatch('emit', args)
...
const returned = callback(...args)
```
- PY: `fiber.py:881,891`
```python
callbacks = bus._dispatch_hooks("emit", "internal/plugin", self, caller_ctx=self.ctx)
...
res = cb(self)
```
- 判定： ADAPT（Python 事件总线全库约定回调只收载荷、不收事件名，如 loader.py:2058 的 `ctx.on("internal/plugin", _on_internal_plugin)`；TS `dispatch('emit', args)` 后 `callback(...args)` 双参是 TS bus 形态的产物）
- 影响： 仅在跨实现移植监听器时需注意签名；PY 内部自洽。

### D23: update/restart 返回 awaitable（TS 同步 waterfall）
- TS: `fiber.ts:747-752`
```ts
config = this._resolveConfig(config)
return this.context.waterfall(this, 'internal/update', config, noSave, () => {
  this.config = config; this._error = undefined; return this.restart()
})
```
- PY: `fiber.py:974-980`（loop 在则 `await ctx.waterfall(...)`，否则 `waterfall_sync`；无 ctx 时直接 `_do_update()`）
- 判定： ADAPT（Python events.waterfall 为 async 实现，属"asyncio 3.8 兼容写法"下的等价改写；语义差异是 update() 的返回值需 await 才有结果）
- 影响： 同步调用者拿不到 restart 结果；文档需声明该面为 awaitable。

### D24: effectInertia/runDisposable 的跨调用者 join 机制缺失
- TS: `fiber.ts:110-117`
```ts
// Public effect disposers remain single-shot, but structural owners and outer
// effects must still be able to join a cleanup that another caller started.
const effectInertia = new WeakMap<Disposable, () => void | Promise<void>>()
function runDisposable(dispose: Disposable) {
  const result = dispose()
  return effectInertia.get(dispose)?.() ?? result
}
```
- PY: 无对应模块级机制；仅靠 `cancel_effect` 的 `if disposed: return in_flight_cleanup`（fiber.py:265-267）在"同一 wrapper 重复调用"场景提供 join；嵌套 disposer（外层 effect 收集的内层 wrapper）在 PY 清理路径中直接 `disp()`，靠 wrapper 幂等守卫兜底。
- 判定： DEVIATION-PERMITTED
- 影响： 守卫使重复执行被阻止、in-flight Task 被返回等待，主要可观察行为近似；差异只在"外层清理是否等待内层已在途清理的完成"的等待面完整性，建议以探针验证（见 PROBE P4）。

### D25: 异步 reload 完成后 inertia 残留 done Task（TS 置 undefined）
- TS: `fiber.ts:665-672`
```ts
this._updateState(() => {
  if (this._runner.epoch === oldEpoch) { this.inertia = undefined }
  else { this.inertia = this._unload(); return FiberState.UNLOADING }
})
```
- PY: `fiber.py:687,719,788`（`self.inertia = loop.create_task(...)` 后任务完成时无人置 `None`；`set_epoch` 的守卫 fiber.py:562-563 用 `done()` 补偿）
- 判定： DEVIATION-PERMITTED
- 影响： 行为由 `done()` 检查补偿，观察等价；残留 Task 引用延迟回收。

### D26: 失败路径状态序列多出 FAILED→UNLOADING→FAILED 瞬态
- TS: `fiber.ts:663-672`（catch 置 INACTIVE 后由尾部 `_updateState` 一次性落到 `_getState()`=FAILED）
- PY: `fiber.py:803-814`（`set_state(FAILED)` → 尾部 `set_state(UNLOADING)` → `_unload` 尾 `set_state(_get_state())`=FAILED，`internal/status` 事件流多两次跃迁）
- 判定： DEVIATION-PERMITTED
- 影响： 订阅 `internal/status` 的事件流可见瞬态差异；最终状态一致。

### D27: store 初始值为 `{}` 而非 undefined
- TS: `fiber.ts:197-198,324,687`（`store: Dict<Impl> | undefined`，插件分支在 `_reload` 前为 `undefined`，`_unload` 后复位 `undefined`）
- PY: `fiber.py:108`（`self.store: Optional[Dict[str, Any]] = {}`，构造即空 dict）
- 判定： DEVIATION-PERMITTED
- 影响： "未加载"与"空依赖"在 PY 不可区分；TS 侧 `store===undefined` 的消费者语义丢失。

### D28: root fiber dispose 语义与 root _reload 的 internal/config 副作用
- TS: `fiber.ts:331`
```ts
this.dispose = () => this.restart()
```
（root 重启 = `_setEpoch(INACTIVE)` → unload → `_refresh` → reload 循环；execute 为 no-op）
- PY: `fiber.py:913-919` 直接 `set_state(UNLOADING); _unload(); await; set_state(ACTIVE)`，跳过 reload 循环；但 `_unload` 尾部对非 INACTIVE epoch 会调 `_reload()`（fiber.py:870-872），其中 `_resolve_config`（fiber.py:206-211）会在 root 上触发 `internal/config` waterfall——TS root `_reload` 不解析 config（execute no-op）。
- 判定： DEVIATION-PERMITTED
- 影响： root 无效果时不可察觉；root 挂有 effect 且有 `internal/config` 监听时多一轮 waterfall 副作用。

### D29: Python-only API 表面（自发明便利层）
- TS: `fiber.ts:184-333` 类体中不存在下列成员。
- PY: `disposable()` fiber.py:470-472、`is_disposer` 形参 fiber.py:213、`error` property fiber.py:478-480、`_in_flight_effects` fiber.py:132、`entry` 管线 fiber.py:103-107/142-144、`Fiber._uid_counter` 回退 fiber.py:87/139-141、`__getattr__` 委托 plugin fiber.py:190-195、`__repr__` fiber.py:1032-1033、`compose_error` 导入未用（fiber.py:12，TS `_execute`/`_unload` 的长栈拼接 fiber.ts:358,678 在 PY 完全缺席）。
- 判定： DEVIATION-PERMITTED（记录许可；`__getattr__` 委托与 compose_error 缺席是其中最值得复核的两项——前者可能掩盖插件属性拼写错误，后者使错误栈诊断弱化）
- 影响： 表面积扩大；诊断栈拼接能力缺失。

### D30: get_effects 平铺 dict、EffectMeta.children 恒空、collect 不建子树
- TS: `fiber.ts:448-454,568-572`
```ts
collect: (dispose) => {
  disposables.push(dispose)
  this._disposables.delete(dispose)
  if (dispose[symbols.effect]) { meta.children.push(dispose[symbols.effect]) }
},
...
return [...this._disposables].map<EffectMeta>(dispose => dispose[symbols.effect]).filter(Boolean)
```
- PY: `fiber.py:232-234`（`collect_disposer` 仅 append 本地列表，无 `_disposables.delete`、无 children）、`fiber.py:474-476`（返回 `meta.to_dict()` 平铺列表）
- 判定： DEVIATION-PERMITTED
- 影响： 效果诊断树退化为平铺；TS 中"子效果从 fiber 顶层列表摘除、由父效果负责"的归属关系在 PY 不存在（清理结果等价，诊断形态不同）。

### D31: set_state 无回调形式、notify 批量化
- TS: `fiber.ts:581-595`（`_updateState(callback)`：新状态由回调返回值或 `_getState()` 推导；逐 impl `notify([impl.name])`）
- PY: `fiber.py:482-498`（`set_state(new_state)` 由调用方决定状态；`fiber.py:493-498` 收集 provided_names 后一次 `notify(provided_names)`）
- 判定： DEVIATION-PERMITTED
- 影响： 事件时序等价（状态变化才 emit、ACTIVE 边界才 notify）；notify 由 N 次单名调用合并为一次批量调用，依赖 notify 内部逐名顺序的观察者可见差异。

### D32: ValidationError 移至 schema.py，无 kValidationError brand
- TS: `fiber.ts:16-40`
```ts
const kValidationError = Symbol.for('ValidationError')
export class ValidationError extends TypeError { name = 'ValidationError'; constructor(issues) { super(`invalid config:\n` + ...) } }
Object.defineProperty(ValidationError.prototype, kValidationError, { value: true })
```
- PY: `dsh/cordis/schema.py:17-43`（`class ValidationError(TypeError)`，list 分支聚合消息 `invalid config:\n  - msg (at path)` 与 TS 逐行一致）；fiber.py:11 导入。
- 判定： ADAPT（Python 无跨实例 brand 需求，类身份即判据；消息格式已对齐）
- 影响： 无（isinstance 判定等价于 brand 检查）。

## 测试缺口

### T1: effect 返回包装器的 thenable 契约 — `await ctx.effect(fn)` 应等待 setup 并触发清理（TS fiber.ts:555-559）。PY 当前完全缺失（D10），无任何测试钉住 `await` 语义。
### T2: _unload 并行卸载语义 — 三个 disposer、第二个挂起时第三个仍应开始执行，且全部完成后才 `store=undefined`（TS fiber.ts:676-687）。PY 串行（D17），无测试暴露。
### T3: 同步 iterator effect 不受 epoch 影响 — effect body 返回同步生成器时必须跑满注册全部 disposer（TS fiber.ts:375-382）。PY 的 epoch 中断（D11）无反向钉测。
### T4: PENDING fiber 的 pre-activation effect 在 dispose 时被排空 — 构造期 `internal/plugin` 观察者注册的效果，在 fiber 被 dispose 时必须被卸载（TS fiber.ts:277-295 的显式 unload 分支）。PY 无对应测试。
### T5: parent UNLOADING 时跳过子 fiber 的依赖评估 — TS fiber.ts:310-319 门控（D2）。registry.py:359-362 无门控亦无测试。
### T6: 构造期 `internal/plugin` 发布同步失败的回滚 — 从 runtime.fibers 移除、registry 清理、fire-and-forget dispose、异常继续上抛（TS fiber.ts:299-308；PY 对应实现在 registry.py:346-357）。
### T7: update() 在非 ACTIVE 状态下 defer config 解析 — 不做 `_resolveConfig`、置 `_error=undefined`、`_setEpoch(INACTIVE)+_refresh` 后返回 undefined（TS fiber.ts:739-746）。PY fiber.py:961-965 形似但无测试覆盖"解析被延迟"这一点。
### T8: await() 重抛启动错误 — settle 后 `throw this._error`（TS fiber.ts:704-710；PY await_settled fiber.py:1026-1027 有，但 D13 的吞异常路径无测试）。
### T9: resolveConfig 聚合消息格式与同步拒绝 — 多 issue 时 `invalid config:\n  - msg (at path)` 逐行格式与 `Async config validation is not supported`（TS fiber.ts:27-35,53-56）。PY ValidationError 格式已对齐（schema.py:27-40）但无 fiber 级测试；async 校验拒绝在 PY 侧完全缺失。
### T10: 异步 iterable effect epoch 失效停止消费 — epoch 翻转后不再 `iter.next()`（TS fiber.ts:389-394；PY fiber.py:427-432 有实现但额外 aclose，D11）。
### T11: assertActive 仅在 uid=null 时抛 INACTIVE_EFFECT — FAILED fiber 上创建 effect 不应因 `_error` 被拒（TS fiber.ts:351-354,418-419；PY `effect` 用 `check_error=False` 规避但公共默认值 D12 未测）。
### T12: dispose 幂等与 join — 已在途 dispose 的二次调用应返回同一清理 Task 而非重复执行（TS fiber.ts:427-442,504-514；PY 的 state 早退 D3 使 UNLOADING 中的首调直接空转，无测试）。

## PROBE 候选

- D9: 构造一个 effect body 返回 `async def`（await 后返回 disposer，disposer 内计数），在 setup 未决时立即调用 `effect()` 返回的取消函数并 await；TS 计数应为 1，PY 预期计数 2（`_dispose_after_barrier` 先调 barrier 结果再从 disposables 弹出重调）。该场景决定 D9 判 MUST-FIX 是否需升级为高危。
- D14: effect body 为协程的 fiber 激活后，在同一事件循环步内先 `set_epoch(INACTIVE)`（或同步 dispose）再放行事件循环；TS 侧 `_reload` 的 `await Promise.resolve()` 检查点会跳过插件执行，PY 预测插件代码已经同步运行。用旗标变量判定。
- D17: 注册三个 disposer，第二个返回挂起 Future；观察第三个 disposer 的开始时间戳（TS 并行→第三者已启动；PY 串行→被阻塞）。同时验证 `_unload` 返回/`store=None` 的时机。
- D24: 外层 effect 内注册内层 effect，先手动调用内层 wrapper 启动异步清理，再触发 fiber `_unload`，比较两侧外层清理是否等待内层 in-flight 完成（TS `runDisposable` join vs PY 幂等守卫返回值是否被上层 await）。
- D5: 依赖服务 fiber 处于 LOADING（异步 apply 未决）时挂载消费者插件：TS `_refresh` 只看 `_store` 应允许激活（epoch 含 `:uid`），PY 依赖 `state != ACTIVE` 检查预期保持 PENDING。用两个插件 + 受控异步 apply 复现。
- D29（compose_error 缺席）: 触发 effect body 深层异常，比对两侧错误对象的栈是否包含注册点外层帧（TS `handleError` 拼接 vs PY 原生栈）。仅为诊断面，不影响判定。
