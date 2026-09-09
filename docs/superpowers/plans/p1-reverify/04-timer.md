# G4-timer 盲审报告

审计范围：`reference/vendor/timer/src/index.ts`（147 行，逐行通读）↔ `dsh/cordis/timer.py`（442 行，逐行通读）。框架对接点（`dsh/cordis/fiber.py:213` `effect(setup, label)`、`dsh/cordis/service.py:45` `Service.__init__(ctx, name, allow_replace)`、`dsh/cordis/reflect.py:322` `mixin`）已核实，仅用于判定语义，不作为差异依据。以下所有行为核对均基于源码本身。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态（1:1 / ADAPT / D#） |
|---|---|---|
| module augmentation `Context extends Pick<...>` (index.ts:3-7) | 无对应（PY 以运行时 `ctx.mixin` + 动态查找实现，timer.py:118） | ADAPT（TS 类型层声明合并无法移植，运行时行为经 mixin 等价达成） |
| `type WithDispose<T>` (index.ts:9) | 无类型对应；以函数属性 `.dispose` 达成（timer.py:376, 438） | ADAPT（py3.8 类型系统无交叉类型） |
| `class TimerService extends Service` (index.ts:12) | `class TimerService(Service)` (timer.py:107) | 1:1 |
| `constructor` + `ctx.mixin(...)` (index.ts:13-16) | `__init__` + `allow_replace=True` + `has hasattr` 守卫 (timer.py:115-118) | D7 |
| `setTimeout` deprecated 别名 (index.ts:19-21) | `setTimeout` (timer.py:120-122) | 1:1（多出 `ctx` 参数，归 D4） |
| `setInterval` deprecated 别名 (index.ts:24-26) | `setInterval` (timer.py:124-126) | 1:1（同上） |
| `timeout(callback, delay)` 回调分支 (index.ts:29-42) | `timeout` callable 分支 (timer.py:140-190) | D2 / D5 / D6（ms→s 换算为 ADAPT：asyncio 计时 API 以秒为单位，偏离清单第 1 条强制；`Error`→`RuntimeError` 同为 ADAPT） |
| `timeout(delay): Promise<void>` 分支 (index.ts:43-53) | `timeout` 非 callable 分支 → Future/协程 (timer.py:191-250) | D1 / D5 / D6（Promise→Future/协程为 ADAPT：py3.8 无 Promise） |
| `interval(callback, delay)` 回调分支 (index.ts:57-66) | `interval` callable 分支 (timer.py:264-315) | D2 / D5 |
| `interval(delay): AsyncIterableIterator` 迭代器分支 (index.ts:58, 67-103) | `_AsyncIntervalIterator` (timer.py:16-104)，由 `interval` timer.py:316-318 构造 | D3 / D5 / D9 |
| `_schedule` 私有助手 (index.ts:106-118) | 无独立对应（逻辑内联进 throttle/debounce，timer.py:334-343, 392-404） | D8 |
| `throttle(callback, delay, noTrailing?)` (index.ts:121-136) | `throttle` (timer.py:320-377) | D2 / D4 / D5 / D6（核心语义核对一致：leading 边缘 `remaining<=0` 不检查 disposed，两侧一致） |
| `debounce(callback, delay)` (index.ts:139-144) | `debounce` (timer.py:379-439) | D2 / D4 / D5 / D6（dispose 后调用 no-op 两侧一致） |
| `export default TimerService` (index.ts:147) | `Timer = TimerService` (timer.py:442) | 1:1 |

 dispose 后回调吞没核对结论：timeout 单次（TS index.ts:36-40 `clearTimeout`；PY timer.py:179-187 cancel + `disposed` 旗标）与 interval（TS index.ts:74-76；PY timer.py:307-313）两侧均吞；throttle 的 leading 边缘在 dispose 后**仍执行**（TS index.ts:130-131 不检查 `isDisposed`；PY timer.py:362-366 同样无条件 `_execute`）——一致；debounce dispose 后调用 no-op（TS index.ts:141；PY timer.py:408-409）——一致。

## 差异

### D1: timeout 无回调分支的 dispose 挂点在"await 结束"而非"promise 结算"
- TS: `index.ts:44-52`
```ts
const { promise, resolve, reject } = Promise.withResolvers<void>()
const dispose = this.ctx.effect(() => {
  const timer = setTimeout(resolve, delay)
  return () => {
    clearTimeout(timer)
    reject(new Error('Context has been disposed'))
  }
}, 'ctx.timeout()')
return promise.finally(dispose)
```
- PY: `timer.py:244-250`
```py
async def _wait_future():
    try:
        return await future
    finally:
        dispose()
...
return _wait_future()
```
- 判定： MUST-FIX
- 影响： TS 的 `promise.finally(dispose)` 在 promise 结算时即触发 dispose（无论是否有人 await）；PY 的 dispose 只在调用方 await 该协程并退出时执行。若协程对象未被 await，timer 已由 effect 同步注册（timer.py:225-242）并照常触发、future 被 set_result，但 dispose 永不执行 → effect 残留至 context 卸载，TS 无此泄漏路径。
- 建议修法： 在 timer.py:242 之后给 `future.add_done_callback(lambda _f: dispose())`，使结算（set_result 或 set_exception）即触发 dispose，与 TS `promise.finally` 对齐；`_wait_future` 的 finally 可保留（disposer 需幂等）。

### D2: 回调异常被捕获吞掉（timeout/interval/throttle/debounce），TS 为未捕获异常直接上抛
- TS: `index.ts:36-39`（timeout；interval 的 index.ts:63-66、throttle 的 index.ts:123-126、debounce 的 index.ts:142 同样无任何 try/catch，Node 下回调抛错即 uncaughtException）
```ts
const timer = setTimeout(() => {
  dispose()
  callback()
}, delay)
return () => clearTimeout(timer)
```
- PY: `timer.py:157-169`（timeout 捕获后记日志）；`timer.py:287-289`（interval 捕获后记日志、循环继续）；`timer.py:355-360`、`timer.py:423-428`（throttle/debounce 捕获）；`timer.py:300-303`（interval 线程路径完全静默）
```py
try:
    callback()
except Exception:
    pass
```
- 判定： MUST-FIX（设计不一致，两条允许偏离均不强制此行为；且 timer.py:300-303 为未命名吞没的空 catch）
- 影响： TS 中回调抛错会使进程崩溃（故障显性），PY 中 timeout 静默继续、interval 循环永不中断、线程路径连日志都没有——故障可察觉性与 TS 相反。
- 建议修法： 对齐 TS 语义——timeout 回调异常应上抛（或至少进程级显性告警）；interval 若决定"异常不断循环"须作为文档化偏离并统一记日志；timer.py:300-303 空 catch 至少接入 `target_ctx.logger` 或按仓库规范命名吞没原因。

### D3: interval 异步迭代器缺 `throw(reason)`，且 `return(value)`/`done.value` 语义丢失
- TS: `index.ts:93-98`
```ts
throw: (reason) => {
  if (!done) done = { kind: 'throw', reason }
  nextTask?.reject(reason)
  dispose()
  return Promise.resolve({ done: true, value: undefined })
},
```
另 index.ts:84 `if (done.kind === 'return') return Promise.resolve({ done: true, value: done.value })` 与 index.ts:88 `if (!done) done = { kind: 'return', value }` 将 return 携带的 value 存入终态并回放。
- PY: `timer.py:83-90`（仅 `aclose()`，无 value 参数、value 固定 `None`，无 `athrow`）；`timer.py:69-72`（done 后 return 分支仅 `raise StopAsyncIteration`，丢弃存储的 value）
```py
async def aclose(self) -> None:
    if not self._done:
        self._done = {"kind": "return", "value": None}
```
- 判定： MUST-FIX（TS 有而 PY 无的成员/行为）
- 影响： 显式驱动迭代器协议（`ait.throw(reason)`）的调用方在 PY 无入口；return 携带值不可传递。常规 `async for` 场景无感知。
- 建议修法： `_AsyncIntervalIterator` 补 `async def athrow(self, reason)`：置 `self._done = {"kind": "throw", "reason": reason}`、向 pending future `set_exception(reason)`、调用 `self._dispose()`，与 TS index.ts:93-98 一致；`aclose` 增加可选 value，`__anext__` 的 return 分支改为 `raise StopAsyncIteration(done["value"])`。

### D4: 自发明扩展面：`ctx` 可选参数、kwargs 转发、awaitable 结果调度
- TS: `index.ts:29-30`（代表性签名；index.ts:19-21, 24-26, 57, 121, 139 同——均无 ctx 参数；回调类型为 `() => void` / `F extends (...args: any[]) => void`，仅位置参数转发，见 index.ts:133 `setTimeout(execute, remaining, ...args)`）
```ts
timeout(callback: () => void, delay: number): () => void
timeout(delay: number): Promise<void>
```
- PY: `timer.py:128-133`（`ctx: Optional[Any] = None`；timer.py:120, 124, 252-257, 320-326, 379-384 同，`target_ctx = ctx or self.ctx` 见 timer.py:138, 262, 328, 386）；kwargs 转发见 timer.py:345, 406；awaitable 结果调度见 timer.py:159-164, 281-286, 355-360, 423-428
```py
def timeout(
    self,
    callback_or_delay: Union[Callable[[], Any], float, int],
    delay_ms: Optional[Union[float, int]] = None,
    ctx: Optional[Any] = None
) -> Any:
```
- 判定： DEVIATION-PERMITTED（默认值下与 TS 行为一致；均为 TS 不存在的附加能力，语义可察觉——显式传 `ctx` 时 effect 生命周期归属另一 fiber，awaitable 回调被 fire-and-forget 调度）
- 影响： 默认调用面无差异；扩展面使 PY 使用者可偏离 TS 设计的"timer 归属构造时 context"约定。
- 建议修法： 若追求严格 1:1，删除 `ctx` 参数与 awaitable 调度；若保留，须在 docstring 标注为 PY 侧扩展并写明生命周期归属规则。

### D5: 无事件循环时的 threading 回退分支（TS 全程假定事件循环，无对应物）
- TS: `index.ts:46`（代表性；index.ts:36, 64, 71, 133, 142 同——全部经由 JS 运行时定时器，语义上永远处于事件循环内）
```ts
const timer = setTimeout(resolve, delay)
```
- PY: `timer.py:171-177`（timeout 回调 `threading.Timer` 回退）、`timer.py:202-223`（timeout 无回调分支 `_fallback_sleep`：dispose 期间置位时仍睡满才抛）、`timer.py:294-305`（interval `threading.Thread` 回退，异常静默）、`timer.py:370-374`（throttle trailing 无 loop 时 `except RuntimeError: pass` 静默丢弃）、`timer.py:430-436`（debounce `threading.Timer` 回退）、`timer.py:40-44`（迭代器无 loop 时 `_task = None`，tick 永不发生，`__anext__` 于 timer.py:74 需 running loop）
```py
async def _fallback_sleep():
    try:
        if disposed:
            raise RuntimeError("Context has been disposed")
        await asyncio.sleep(delay_sec)
        if disposed:
            raise RuntimeError("Context has been disposed")
    finally:
        dispose()
```
- 判定： DEVIATION-PERMITTED（注意：不属于两条允许偏离强制，属自发明环境适配；TS 语义在"无事件循环"环境下未定义，故仅在 PY 裸脚本场景激活，有 loop 时零影响）
- 影响： `_fallback_sleep` 的 reject 即时性下降（dispose 后仍睡满 delay 才抛，TS 应立即 reject）；throttle trailing 在无 loop 时静默丢失；daemon 线程不阻止解释器退出（TS ref'd timer 阻止进程退出）。
- 建议修法： 至少为 `_fallback_sleep` 的"边界检查而非即时 reject"写明注释/文档；或无 loop 时直接抛 `RuntimeError("timer requires a running event loop")` 收敛偏差面。

### D6: 0/负延迟边界：asyncio `call_later(0)` 立即触发 vs Node `setTimeout(0)` 钳 1ms
- TS: `index.ts:36`（代表性；index.ts:46, 64, 71, 133, 142 同——delay 原样透传，Node 运行时将 <1ms 钳到 1ms）
```ts
const timer = setTimeout(() => {
  dispose()
  callback()
}, delay)
```
- PY: `timer.py:143`（timeout 回调 `max(0.0, delay / 1000.0)`，`call_later(0)` 下一轮循环即触发）；`timer.py:267`、`timer.py:22`（interval 两分支 `max(0.001, ...)` 已与 Node 1ms 对齐）；`timer.py:329`、`timer.py:387`（throttle/debounce `max(0.0, ...)`）
```py
delay = float(delay_ms if delay_ms is not None else 0)
delay_sec = max(0.0, delay / 1000.0)
```
- 判定： DEVIATION-PERMITTED（负值两侧均归 0/1ms，语义一致；仅 timeout 单次 0 延迟比 Node 快约 1ms）
- 影响： 仅 0 延迟边界计时精度，无实质可观察差异（interval 已对齐）。
- 建议修法： 如需严格对齐，timeout 两分支（timer.py:143, 193）改为 `max(0.001, ...)`。

### D7: 构造函数：`allow_replace=True` 与 `hasattr(ctx, "mixin")` 守卫
- TS: `index.ts:13-16`
```ts
constructor(ctx: Context) {
  super(ctx, 'timer')
  ctx.mixin('timer', ['timeout', 'interval', 'throttle', 'debounce', 'setTimeout', 'setInterval'])
}
```
- PY: `timer.py:115-118`（`allow_replace=True` 落到 `service.py:45, 66-68` 的静默替换路径；mixin 守卫使不支持 mixin 的 ctx 静默跳过）
```py
def __init__(self, ctx: Any):
    super().__init__(ctx, "timer", allow_replace=True)
    if hasattr(ctx, "mixin"):
        ctx.mixin("timer", ["timeout", "interval", "throttle", "debounce", "setTimeout", "setInterval"])
```
- 判定： DEVIATION-PERMITTED（重复挂载时静默替换而非报错，违背"misconfiguration fails loud"精神，但影响限于同名服务重复注册场景；mixin 名单本身 1:1）
- 影响： 第二次实例化 TimerService 会无提示顶替首个实例。
- 建议修法： 去掉 `allow_replace=True`（或冲突时抛错）；mixin 守卫可保留但注明原因。

### D8: TS 私有助手 `_schedule` 在 PY 无对应符号（throttle/debounce 重复内联）
- TS: `index.ts:106-118`
```ts
private _schedule(label: string, trigger: (args: any[], isDisposed: boolean) => any, isDisposed = false) {
  let timer: number | NodeJS.Timeout | undefined
  const dispose = this.ctx.effect(() => () => {
    isDisposed = true
    clearTimeout(timer)
  }, label)
```
- PY: `timer.py:334-343`（throttle 内联）、`timer.py:392-404`（debounce 内联）——wrapper"先清旧定时器再触发"的语义两侧均成立，但结构不复用。
- 判定： DEVIATION-PERMITTED（私有实现结构差异，无独立可观察语义；属可维护性风险——两份内联实现已出现 D2/D5 的不一致漂移）
- 影响： 未来修改 throttle/debounce 语义时易单边漂移。
- 建议修法： 提取 `_schedule(label, trigger, is_disposed=False)` 私有方法，throttle/debounce 复用，对齐 index.ts:106-118。

### D9: `_AsyncIntervalIterator.__del__` GC 兜底（PY 自发明 finalizer）
- TS: `index.ts:81-102`（迭代器对象无任何 finalizer/自动 dispose；资源回收仅依赖显式 `return()/throw()`、context 卸载（index.ts:74-79）或 JS GC）
```ts
return: (value) => {
  if (!done) done = { kind: 'return', value }
  nextTask?.resolve({ done: true, value })
  dispose()
  return Promise.resolve({ done: true, value })
},
```
- PY: `timer.py:92-104`
```py
def __del__(self) -> None:
    if not self._done:
        self._done = {"kind": "return", "value": None}
        try:
            if self._task and not self._task.done():
                self._task.cancel()
        except Exception:
            pass
```
- 判定： DEVIATION-PERMITTED（资源安全网，仅用户漏 dispose 时触发；解释器关闭阶段 `__del__` 内调用 effect disposer 的异常已被吞，无崩溃风险）
- 影响： 使 PY 比 TS 多一层兜底，可能掩盖泄漏；语义可察觉（TS 中泄漏的迭代器 timer 持续 tick 至 ctx 卸载，PY 会在 GC 时静默收掉）。
- 建议修法： 保留但建议在 docstring 注明"GC 兜底非 TS 语义"；或删除以严格 1:1。

## 测试缺口

### T1: dispose-before-fire 吞回调 — timeout 单次与 interval 循环
TS index.ts:36-40（dispose → `clearTimeout`，回调永不执行）与 index.ts:63-66（`clearInterval`）。缺钉测：`timeout(cb, 100)` 后立即 dispose，断言 cb 在远超 delay 的时间内不被调用；interval 同理。

### T2: timeout 无回调分支的 dispose 拒绝与正常结算清理
TS index.ts:47-50（dispose → `reject(new Error('Context has been disposed'))`）与 index.ts:52（`promise.finally(dispose)` 结算即注销 effect）。缺钉测：dispose 后 await 抛 `RuntimeError("Context has been disposed")`；正常结算后 effect 已从 context 注销（对应 D1 修复后行为）。

### T3: interval 迭代器三条终态路径
TS index.ts:74-79（dispose 时 pending `next()` 以 'Context has been disposed' reject）、index.ts:84-85（done 后再次 `next()`：return→done:true、throw→持续 reject）、index.ts:87-92（`return()` 时 pending `next()` 收到 done）。缺钉测覆盖：pending 拒绝、终态后重复 `next()`、以及 `athrow` 路径（D3 修复后）。

### T4: throttle 的 noTrailing 与 dispose 后 leading 仍执行
TS index.ts:127-135（`noTrailing` 作为 `_schedule` 初始 `isDisposed` 传入，index.ts:135 `}, noTrailing)`）与 index.ts:130-131（`remaining <= 0` 分支不检查 `isDisposed`）。缺钉测：`no_trailing=True` 时无 trailing 触发、leading 正常；context dispose 后调用且 `remaining<=0` 时回调仍执行、`remaining>0` 时不排 trailing。

### T5: debounce 连续调用只保留末次参数、dispose 后调用 no-op
TS index.ts:112-115（wrapper 先 `clearTimeout` 再触发）与 index.ts:140-143（`if (isDisposed) return`）。缺钉测：快速连调多次，仅末次参数在 delay 后执行；dispose 后调用不执行任何回调。

### T6: 迭代器 tick 时刻无消费者则该 tick 丢弃（不排队不缓存）
TS index.ts:71-73（`nextTask?.resolve(...)` 空安全，无 nextTask 时 tick 静默消失）。缺钉测：创建迭代器后不调用 `next()` 等待多个 delay，再 `next()` 断言等待下一个 tick 而非立即返回。

### T7: 重复 dispose 幂等
两侧 label（TS index.ts:41/66/80；PY timer.py:189/315/59/343/404）注册的 effect disposer 均可能被双调（如 D1 修复后 finally 与 done-callback 各一次）。缺钉测：对 timeout/interval/throttle/debounce 返回的 disposer 连调两次，断言无异常且清理只生效一次。

## PROBE 候选

- D1: 场景——`timeout(100)`（无回调）不 await，等 timer 触发后检查 fiber disposables/effect 计数是否残留；再触发 ctx 卸载。理由：验证"未 await 协程导致 effect 泄漏"是否实际发生（取决于 fiber.effect 对 setup 的同步执行与 disposer 幂等实现，需运行裁决）。
- D5: 场景——无 asyncio loop 的裸脚本中 `timeout(500)`（无回调）立即 dispose，测量 `_fallback_sleep` 抛 `RuntimeError` 的时刻（预期 ~500ms 后而非立即）。理由：量化 reject 即时性差异，裁决 DEVIATION-PERMITTED 是否应升级。
- D5: 场景——timeout 回调线程回退路径（timer.py:171-177）：dispose 与 fire 并发，`_on_timeout` 的 disposed 检查（timer.py:150-156）与 cleanup 之间存在竞态窗口，回调可能在 dispose 后仍执行一次。理由：TS 单线程无此窗口，需压力探针确认窗口是否可复现。
- D6: 场景——`timeout(cb, 0)` 与 `loop.call_later(0, ...)` 的实际触发轮次对比（同轮/下轮），并与 Node `setTimeout(cb, 0)`（≥1ms）基准对照。理由：确认 0 延迟边界差异是否在任何实际调用模式下可观察。
