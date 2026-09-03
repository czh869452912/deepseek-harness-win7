# dsh/cordis/timer.py ↔ reference/vendor/timer/src/index.ts

比对范围:`dsh/cordis/timer.py`(398 行)对照 `reference/vendor/timer/src/index.ts`(147 行,`TimerService`)。超出原版的 260 行主要为:无事件循环时的 `threading` 回退、logger 集成、`_AsyncIntervalIterator` 队列机制、disposed 防御——在下列条目中逐项归类。构造器 `super(ctx, 'timer')` + `ctx.mixin('timer', [6 个方法名])`、deprecated 别名已核对一致(别名多出的 `ctx` 形参为 Python 侧便利扩展)。

## 差异清单

### D1 [MUST-FIX] `interval(delay)` 迭代器 dispose 后的语义:TS 挂起与后续 `next()` 一律 reject `Error('Context has been disposed')`;Python 后续 `__anext__` 抛 StopAsyncIteration
- 位置: py:dsh/cordis/timer.py:49-56(effect cleanup)、65-71(`__anext__`) vs ts:reference/vendor/timer/src/index.ts:74-85
- 原版行为:
  ```ts
  return () => {
    clearInterval(timer)
    if (done) return
    done = { kind: 'throw', reason: new Error('Context has been disposed') }
    nextTask?.reject(done.reason)
  }
  ...
  next: () => {
    if (!done) return (nextTask = Promise.withResolvers()).promise
    if (done.kind === 'return') return Promise.resolve({ done: true, value: done.value })
    return Promise.reject(done.reason)     // dispose 后每次 next 都 reject
  }
  ```
  dispose 后:挂起的 `next()` reject,之后的每次 `next()` 也持续 reject 同一错误;`for await` 消费者收到的是异常而非正常结束。
- 移植版现状:
  ```python
  async def __anext__(self) -> None:
      if self._disposed:
          raise StopAsyncIteration        # dispose 后是"正常结束"
      item = await self._queue.get()       # 挂起者收到 RuntimeError
      if isinstance(item, Exception):
          raise item
  ```
  cleanup 向队列塞 `RuntimeError("Context has been disposed")` 只命中挂起者;后续 `__anext__` 变成 StopAsyncIteration,`async for` 静默退出,与 TS 的 reject 语义不同,吞掉了"上下文已销毁"的信号。
- 修复方案: 遵循 TS `done` 状态映射并严守 Python PEP 525 异步迭代器规范：引入 `_done: Optional[Dict[str, Any]] = None`：① 若由外部上下文释放（dispose）触发，置 `_done = {'kind': 'throw', 'reason': RuntimeError('Context has been disposed')}`，当前挂起等待者收到该异常，且后续所有 `__anext__` 调用均持续抛出该 RuntimeError；② 若由消费者主动退出或调用 `aclose()` 触发（对应 TS `return()`），置 `_done = {'kind': 'return'}`，挂起等待者与后续 `__anext__` 均抛出标准的 `StopAsyncIteration` 正常关闭。

### D2 [MUST-FIX] `interval(delay)` 慢消费者时 tick 处理:TS 丢弃无等待者的 tick(单槽 nextTask);Python 无界 Queue 缓存 tick 造成迟到爆发
- 位置: py:dsh/cordis/timer.py:23、30-34、65-71 vs ts:reference/vendor/timer/src/index.ts:69-83
- 原版行为:
  ```ts
  const timer = setInterval(() => {
    nextTask?.resolve({ done: false, value: undefined })   // 无挂起 nextTask 时 tick 直接丢弃
  }, delay)
  ...
  next: () => { if (!done) return (nextTask = Promise.withResolvers()).promise ... }
  ```
  任意时刻至多一个未交付 tick;消费慢时 tick 被合并/丢弃,恢复后不补发。
- 移植版现状:
  ```python
  self._queue: asyncio.Queue = asyncio.Queue()
  ...
  while not self._disposed:
      await asyncio.sleep(self.delay_sec)
      ...
      await self._queue.put(None)        # 无界累积
  ```
  消费暂停(如 awaited 回调耗时、event loop 阻塞)期间产生的每个 tick 都入队,恢复后被连发重放。
- 修复方案: 采用单槽通知模型替代无界 `asyncio.Queue`：使用 `asyncio.Event` 或持有单槽 pending Future。每次定时周期触发时，仅当存在正在挂起等待的 `__anext__` 消费者时才通知其放行；若当前无等待消费者，直接丢弃该 tick，杜绝在慢消费或阻塞恢复后的迟到连发爆发。

### D3 [MUST-FIX] `interval(callback)` 对异步回调 `await`,把固定速率变成"delay+回调时长"串行;TS setInterval 从不 await
- 位置: py:dsh/cordis/timer.py:243-251 vs ts:reference/vendor/timer/src/index.ts:63-66
- 原版行为:
  ```ts
  return this.ctx.effect(() => {
    const timer = setInterval(callback, delay)     // 返回的 promise 被忽略,不等待
    return () => clearInterval(timer)
  }, 'ctx.interval()')
  ```
  回调返回 promise 时 tick 周期仍是 `delay`,可重叠。
- 移植版现状:
  ```python
  res = callback()
  if inspect.isawaitable(res):
      await res            # 循环内等待 → 下一 tick 推迟到回调完成之后
  ```
- 修复方案:回调结果改为 `loop.create_task(res)` fire-and-forget(与 `timeout` 回调路径一致),循环体只负责固定速率 sleep+触发。

### D4 [MUST-FIX] `throttle` dispose 后行为:TS 只抑制 trailing 调度,immediate 路径(`remaining<=0`)在 dispose 后仍执行;Python 直接整体短路
- 位置: py:dsh/cordis/timer.py:310-313、330-334 vs ts:reference/vendor/timer/src/index.ts:106-118、127-135
- 原版行为:
  ```ts
  const wrapper: any = (...args: any[]) => {
    clearTimeout(timer)
    timer = trigger(args, isDisposed)      // isDisposed 只影响 trigger 内的分支
  }
  // throttle trigger:
  if (remaining <= 0) {
    execute(...args)                        // dispose 后仍执行
  } else if (!isDisposed) {
    return setTimeout(execute, remaining, ...args)   // 仅 trailing 被抑制
  }
  ```
  (TS 借 `noTrailing` 作为 `isDisposed` 初值实现抑制,dispose 效果仅令 trailing 分支失效。)
- 移植版现状:
  ```python
  def throttled(*args: Any, **kwargs: Any) -> Any:
      nonlocal last_call, timer_handle
      if disposed:
          return None                      # dispose 后一切调用被吞
  ```
- 修复方案:`disposed` 只用于 `elif not no_trailing and not disposed:` 的 trailing 调度;`remaining <= 0` 的 immediate 路径去掉 disposed 短路,保持与 TS 一致。

### D5 [MUST-FIX] 无事件循环回退路径未纳入 effect 取消:`timeout(delay)` 无 loop 时不注册 effect;`debounce` 的 threading.Timer 不被 cleanup 取消
- 位置: py:dsh/cordis/timer.py:182-192、194-211、389-395 vs ts:reference/vendor/timer/src/index.ts:44-53、139-144
- 原版行为:
  ```ts
  } else {
    const { promise, resolve, reject } = Promise.withResolvers<void>()
    const dispose = this.ctx.effect(() => {          // 两种形态都注册 effect
      const timer = setTimeout(resolve, delay)
      return () => { clearTimeout(timer); reject(new Error('Context has been disposed')) }
    }, 'ctx.timeout()')
  ```
  计时器与 fiber 生命周期无条件绑定。
- 移植版现状:
  ```python
  if future is None:
      async def _fallback_sleep(): ...
      return _fallback_sleep()        # 未注册任何 effect,无法取消
  ...
  except RuntimeError:
      t = threading.Timer(delay_sec, ...)
      t.start()                        # debounce:cleanup 只 cancel timer_handle,t 不被取消
  ```
  无 loop 环境(Win7 同步 CLI 路径)下:timeout future 形态完全不受 fiber 卸载约束;debounce 的 threading.Timer 依赖 `_execute` 内 `if not disposed` 静默,计时线程仍会存活到点。
- 修复方案:无 loop 的 `timeout(delay)` 同样走 `target_ctx.effect`(cleanup 中 `threading.Timer.cancel()` + 置异常);`debounce` 将 threading.Timer 句柄纳入 `_cleanup`。

### D6 [ADAPT] 回调异常处理:TS 未捕获(Node 进程级 uncaughtException,通常致命);Python 捕获后记日志并继续
- 位置: py:dsh/cordis/timer.py:152-156(timeout)、252-254(interval)、317-328/377-387(throttle/debounce `_execute`) vs ts:reference/vendor/timer/src/index.ts:36-39、64、123-126、142
- 原版行为:`setTimeout(() => { dispose(); callback() }, delay)` — callback 抛错即成为 uncaught exception(Node 默认崩溃进程)。
- 移植版现状:`except Exception as e: target_ctx.logger("timer").error("Exception in timeout callback: %s", e)` — 记录后定时器体系继续运转。
- 修复方案:平台等价实现。asyncio 中 `call_later` 回调异常本就由 loop 异常处理器记录而不中止 loop;显式日志与之对齐,复刻"进程崩溃"既不可行也不合期望。保留,但建议日志统一走 `logger("timer")` 并在无边注的情况下命名吞掉的范围(仅回调异常,非 cleanup 异常)。

### D7 [ADAPT] 平台/语言形态映射:Promise.withResolvers→asyncio.Future、Symbol.asyncIterator→`__aiter__/__anext__`、Date.now()→time.time()(同为墙钟,含系统回拨偏差)、Node setInterval 的 ~1ms 下限↔`max(0.001, ...)`(timeout 侧 Python 为 `max(0.0, ...)` 不钳制,差异可忽略)、reject `new Error('Context has been disposed')`→`RuntimeError`(文案一致)、`_schedule` 的 `isDisposed=noTrailing` 初值技巧→显式 `no_trailing` 形参(语义等价)、wrapper 返回 timer 句柄→Python 返回 None、TS 迭代器的显式 `throw(reason)` 方法→Python 迭代协议无对应(仅 `aclose`)
- 位置: py:dsh/cordis/timer.py:16-92、107-113、130-177、285-295 vs ts:reference/vendor/timer/src/index.ts:9、29-54、106-118、139-144
- 修复方案:无需修改;若追求 1:1 可给迭代器补 `athrow()` 等价方法,但 Python `async for` 不消费它,SKIP 级。

### D8 [ADAPT] Python 侧新增能力(非 TS 行为偏离):threading 回退(无 loop 的 Win7 同步场景)、logger 集成、`_AsyncIntervalIterator` 的队列/task 机制本体、`setTimeout/setInterval` 别名与各 API 的 `ctx=` 重定向形参、`timeout(callback)` 的 delay 缺省 0(TS 必填)
- 位置: py:dsh/cordis/timer.py:6-11、16-92、107-113、125-129 vs ts:reference/vendor/timer/src/index.ts:全文件
- 修复方案:保留;注意 D5 指出的"回退路径须同样纳入 effect 取消"是其中唯一的行为性缺口。

## 已核对一致项
`timeout(callback)`:到点先 `dispose()` 再回调、手动 disposer 取消未到点计时器(effect label `ctx.timeout()` 一致);`interval(callback)`:effect label `ctx.interval()`、dispose 停止后续 tick;`timeout(delay)` 正常路径 `finally(dispose)`↔`_wait_future` 的 finally dispose、dispose 后 future 置异常;throttle 首调立即执行、`last_call=-inf` 起算、trailing 以最后一次触发实参执行、`fn.dispose` 附加;debounce 重复调用重置计时;两实例互不干扰;`Service` 基类与 mixin 表。

## 测试缺口

### T1 dispose 后迭代器异常语义(修复 D1) — `test_timer_interval_iterator_dispose_rejects_pending_and_subsequent`
`ctx.interval(15)` 挂起一个 `__anext__` 后调用 `ctx.dispose()`(或 effect 清理),断言挂起者收到 `RuntimeError("Context has been disposed")`,且后续 `__anext__` 也抛同一错误而非 StopAsyncIteration。现有 `test_timer_interval_immediate_aclose` 只断言 `_disposed` 标志。

### T2 aclose 对挂起等待者的结束语义(修复 D1 return 路径) — `test_timer_interval_iterator_aclose_resolves_pending`
挂起等待期间 `await it.aclose()`,挂起的 `__anext__` 应以 StopAsyncIteration 结束(对应 TS `return(value)` 的 `{done:true}` resolve)。

### T3 慢消费者 tick 丢弃/合并(修复 D2) — `test_timer_interval_iterator_drops_unconsumed_ticks`
delay=10ms,消费侧每次 `__anext__` 前 `await asyncio.sleep(0.05)`,断言累计收到 tick 数按"至多 1 个待交付"计(≈每 50ms 一个),而非队列重放积压数量。

### T4 异步回调固定速率(修复 D3) — `test_timer_interval_async_callback_fixed_rate_overlaps`
异步回调内 `await asyncio.sleep(0.03)`、delay=10ms,持续 100ms 后 tick 数应接近 10(TS 语义)而非 ≈2-3(当前串行语义)。

### T5 dispose 后 throttle immediate 仍执行(修复 D4) — `test_timer_throttle_immediate_fires_after_dispose`
`fn = ctx.throttle(cb, 20)`;`await asyncio.sleep(0.05)` 后 `fn.dispose()`;再调 `fn(1)` 应执行回调(TS 语义),现有测试均未覆盖 dispose 后调用。

### T6 `timeout(delay)` future 形态被 dispose reject(修复 D5/对齐 TS reject 文案) — `test_timer_timeout_future_rejects_on_dispose`
`fut = ctx.timeout(200)`;`fut` 的 effect disposer 调用后 `await fut` 应抛 `RuntimeError("Context has been disposed")`。现有 `test_timer_timeout_cancel` 只覆盖 callback 形态的取消。

### T7 无 loop 回退路径的 effect 约束(修复 D5) — `test_timer_no_loop_timeout_registers_cancellable_effect`
在无运行 loop 的同步上下文直接调用 `TimerService.timeout(50)`(threading 回退),断言返回的 disposer 可取消计时且 fiber dispose 时被联动清理。

### T8 throttle `no_trailing=True` — `test_timer_throttle_no_trailing_skips_trailing_call`
`ctx.throttle(cb, 40, no_trailing=True)` 连续调用后等待超时,断言只有首调执行、无 trailing 补发(TS 契约的一部分,现有两个 timer 测试文件均未覆盖)。

### T9 回调异常被记录且不影响后续 tick(验证 D6 的容错面) — `test_timer_timeout_callback_exception_is_logged`
`ctx.interval` 回调抛 ValueError,后续 tick 仍触发且错误经 logger(而非 capsys 之外的异常冒泡);同时断言 cleanup 阶段的异常不受该容错影响。
