# dsh/cordis/events.py ↔ reference/vendor/cordis/src/events.ts

比对范围:`dsh/cordis/events.py`(464 行,含 `dsh/cordis/context.py:196-210` 的 `ctx.on/once` 包装)对照 `reference/vendor/cordis/src/events.ts`(352 行,`EventsService`)。命名风格(camelCase→snake_case)与 `caller_ctx` kwarg 替代 JS `this` 绑定按 ADAPT 处理,不计入差异。

## 差异清单

### D1 [MUST-FIX] waterfall 的 `next()` 忽略入参并重放原始 args;Python 版 `next_fn(next_data)` 做值穿线
- 位置: py:dsh/cordis/events.py:367-369(同步)、429-431(异步) vs ts:reference/vendor/cordis/src/events.ts:237-241
- 原版行为:
  ```ts
  const next = () => {
    const cb = cbs.shift() ?? inner
    return cb(...args)
  }
  ```
  `next` 是无参闭包:监听器传给 `next(...)` 的任何实参被静默丢弃;后续监听器与内建续体收到的始终是同一份原始 args(cordis 契约是"就地修改共享对象"来传递数据,而非给 `next` 传新值)。
- 移植版现状:
  ```python
  async def next_fn(next_data: Any = None) -> Any:
      payload = current_data if next_data is None else next_data
      return await run_pipeline(index + 1, payload)
  ```
  Python 版把 `next_fn(x)` 的 `x` 作为下一级的 `current_data`,发明了"传值穿线"契约(测试 `test_waterfall_next_continuation_and_pipeline` 依赖 `next_fn(data + " -> mw1")`)。TS 中该写法等价于 `next()`,下一级仍收到原始数据。
- 修复方案:将 `next_fn` 改为接受并丢弃参数(`def next_fn(*_a)` → `run_pipeline(index + 1, original_args)`),与 TS 一致地以"首参共享对象原地修改"为数据通道;若保留穿线语义则必须作为显式记录的偏离,但按"TS 为实现权威"应改为丢弃参数。

### D2 [MUST-FIX] waterfall 中"非 next 形参"监听器被当 reducer 自动续链;TS 中所有监听器均可用"不调 next"否决
- 位置: py:dsh/cordis/events.py:377-389(同步)、439-461(异步) vs ts:reference/vendor/cordis/src/events.ts:227-230, 239-242
- 原版行为:
  ```ts
  // 每个监听器都收到 next 作为最后一个实参(JS 多余实参自动忽略)
  // "a listener that does not call `next()` vetoes the rest of the chain, including the built-in behavior"
  const cb = cbs.shift() ?? inner
  return cb(...args)
  ```
  返回而不调 `next()` = 否决,返回值即整个 waterfall 的结果。
- 移植版现状:
  ```python
  if "next" in params or "next_fn" in params or len(params) >= len(args_list) + 2 or has_var_pos:
      ...  # next 风格,可否决
  res = cb(current_data, *args_list, **kw)
  if res is not None:
      return next_fn(res)      # reducer 风格:无条件续链,返回值穿线
  return next_fn(current_data)
  ```
  单参/短参监听器(如 `def h(config): return new_config`)在 TS 中会收到 next 并因不调用而否决;Python 版将其判为 reducer,自动续链且返回值向下游传播——否决能力凭签名启发式丢失。
- 修复方案:按签名探测监听器是否能接受 next;不能接受的监听器返回时视为否决(返回值即 waterfall 结果,不再调用 `next_fn`)。至少要把 reducer 自动续链限制为显式 opt-in,而非签名启发式默认。

### D3 [MUST-FIX] 链末内建续体(inner)的调用 arity:TS 传全部剩余实参 + next,Python 只传 current_data
- 位置: py:dsh/cordis/events.py:345-357、360-363、422-425 vs ts:reference/vendor/cordis/src/events.ts:236-242
- 原版行为:
  ```ts
  const inner = args.pop()          // 无条件 pop(最后一个实参,无论是否 callable)
  ...
  return cb(...args)                // cbs 耗尽时 cb === inner,收到 (a1..aN-1, next)
  ```
  内建续体(如 fiber 的默认行为)收到 `(config, noSave, next)` 全量实参。
- 移植版现状:
  ```python
  if index >= len(listeners):
      if inner is not None:
          return _call_inner(inner, current_data)   # 只传 1 个实参
      return current_data
  ```
  且 Python 只在 `callable(args_list[-1])` 时才 pop inner(TS 无条件 pop)。内建续体收到的实参被截断,依赖 `(config, noSave, next)` 形参的 1:1 移植监听器会拿错参数。
- 修复方案:链末调用 `inner(current_data, *args_list, next_fn)`;并保留"无条件 pop 尾参为 inner"的原版语义(或至少在派发 `internal/update` 等内建事件时保证全量实参)。

### D4 [MUST-FIX] `internal/update` 内建监听器:回退到派发者续体时 TS 传 `(config, noSave, next)`,Python 只传 `(cfg)`;且多了 `args[-2]` 启发式
- 位置: py:dsh/cordis/events.py:83-103 vs ts:reference/vendor/cordis/src/events.ts:148-155
- 原版行为:
  ```ts
  this.on('internal/update', function (config, noSave, next) {
    const cbs = [...this._hooks['internal/update'] || []]
    const _next = () => {
      const cb = cbs.shift() ?? next
      return cb.call(this, config, noSave, _next)
    }
    return _next()
  }, { global: true, prepend: true })
  ```
  `cbs` 耗尽时回退到派发者传入的 `next`,且同样以 `(config, noSave, _next)` 全量实参调用。
- 移植版现状:
  ```python
  next_callback = args[-1] if args and callable(args[-1]) else None
  user_next = args[-2] if len(args) >= 2 and callable(args[-2]) else (args[0] if args and callable(args[0]) else None)
  ...
  elif user_next and callable(user_next):
      return user_next(cfg)          # 只传 cfg
  ```
- 修复方案:回退续体以 `(cfg, no_save, _next)` 调用;删除 `user_next = args[-2] ...` 启发式(TS 只有单一 `?? next` 回退)。

### D5 [MUST-FIX] `internal/listener` 内建拦截忽略 `prepend`(fiber 级钩子总是 push);TS 按 options.prepend unshift/push
- 位置: py:dsh/cordis/events.py:68-81(dsh/cordis/utils.py 的 `DisposableList` 无 unshift) vs ts:reference/vendor/cordis/src/events.ts:140-146
- 原版行为:
  ```ts
  if (name === 'internal/update' && !options.global) {
    const hooks = this.fiber._hooks['internal/update'] ??= new DisposableList()
    const method = options.prepend ? 'unshift' : 'push'
    return hooks[method](listener)
  }
  ```
- 移植版现状:
  ```python
  if "internal/update" not in fiber._hooks:
      fiber._hooks["internal/update"] = DisposableList()
  hooks = fiber._hooks["internal/update"]
  return hooks.push(listener)        # prepend 被丢弃
  ```
  `internal/update` 上带 `prepend=True` 的监听器在 fiber 钩子表中的顺序与 TS 不一致(应插到最前),会改变更新链的执行顺序。
- 修复方案:给 `DisposableList` 增加 `unshift`(头部插入并返回 disposer),`_on_internal_listener` 按 `prepend` 分派。

### D6 [MUST-FIX] 失活 fiber 上注册监听器的顺序:TS 先 `assertActive()` 再拦截/注册;Python 先写总线并派发拦截,之后才在 effect 里 assert_active → 失败后钩子泄漏在 `_hooks`
- 位置: py:dsh/cordis/context.py:196-202 + dsh/cordis/events.py:123-137 + dsh/cordis/fiber.py:173-181 vs ts:reference/vendor/cordis/src/events.ts:293-297
- 原版行为:
  ```ts
  // handle special events
  this.ctx.fiber.assertActive()
  listener = this.ctx.reflect.bind(listener)
  const result = this.bail(this.ctx, 'internal/listener', name, listener, options)
  ```
  断言在一切副作用之前;失活时抛 `CordisError('INACTIVE_EFFECT')`,总线与拦截钩子均无副作用。
- 移植版现状:
  ```python
  disposer = self._event_bus.on(event_name, handler, ...)   # 先注册进 _hooks 并派发 internal/listener
  self.effect(disposer, label=f"ctx.on({event_name})")       # 后经 fiber.effect → assert_active 抛错
  ```
  `effect` 注册失败(抛 INACTIVE_EFFECT)时,`EventBus.on` 已产生的总线注册与拦截派发不会回滚——监听器残留且永不触发/永不清理。
- 修复方案:`ctx.on/once` 在调用 `EventBus.on` 前先 `fiber.assert_active()`;`EventBus.on` 内部 effect 注册失败时回滚刚插入的 `Hook`(try/except + disposer)。

### D7 [MUST-FIX] `bail/bail_sync` 的 TypeError 降级重试会吞掉监听器体内抛出的 TypeError(被降级解释为"未 bail")
- 位置: py:dsh/cordis/events.py:289-301(`bail_sync`)、313-325(`bail`) vs ts:reference/vendor/cordis/src/events.ts:217-222
- 原版行为:
  ```ts
  bail(...args: any[]) {
    for (const cb of this.dispatch('bail', args)) {
      const result = cb(...args)
      if (isBailed(result)) return result
    }
  }
  ```
  监听器抛出的任何异常(含 TypeError)原样向上传播,中断派发。
- 移植版现状:
  ```python
  try:
      res = listener(*args, **kwargs)
  except TypeError:
      try:
          res = listener(*args)          # 重试 → 监听器体被二次执行
      except TypeError:
          ...
          res = None                      # 最终静默吞掉
  ```
  为兼容 Python 严格 arity 而引入的降级会把监听器逻辑内的 TypeError(以及部分执行后的副作用)静默化为"返回 None、继续派发"。
- 修复方案:像 waterfall 一样先 `inspect.signature` 判定可接受的 arity,再一次性调用;除"实参过多"这一确定情形外不捕获 TypeError,让监听器异常透传。

### D8 [MUST-FIX] `parallel` 派发时 `internal/dispatch` 的 mode 串:TS 报 'emit',Python 报 'parallel'
- 位置: py:dsh/cordis/events.py:252 vs ts:reference/vendor/cordis/src/events.ts:184
- 原版行为:
  ```ts
  async parallel(...args: any[]) {
    const results = await Promise.allSettled(this.dispatch('emit', args).map(...))
  ```
  `parallel` 复用 `'emit'` 作为诊断 mode;监听 `internal/dispatch` 的插件看到的 mode 是 `'emit'`。
- 移植版现状:
  ```python
  listeners = self._dispatch_hooks("parallel", event_name, args, caller_ctx)
  ```
- 修复方案:`_dispatch_hooks("emit", ...)`(parallel 调用点),保持诊断流 1:1。

### D9 [MUST-FIX] `_dispatch_hooks` 吞掉 `ctx_filter` 抛出的异常;TS 中 filter 异常会中断整次派发
- 位置: py:dsh/cordis/events.py:210-217 vs ts:reference/vendor/cordis/src/events.ts:171-174
- 原版行为:
  ```ts
  return (this._hooks[name] || [])
    .filter(hook => hook.global || !filter || filter.call(thisArg, hook.ctx))
    .map(hook => hook.callback.bind(thisArg))
  ```
  无 try/except:`filter` 抛错直接沿 dispatch → 派发调用方传播。
- 移植版现状:
  ```python
  try:
      if ctx_filter(hook.ctx):
          ...
  except Exception:
      pass        # 静默跳过该钩子,派发继续
  ```
- 修复方案:移除 try/except 使异常透传(如需容错,至少按仓库规则命名所吞异常并记录后重抛)。

### D10 [MUST-FIX] waterfall 派发时 `internal/dispatch` 的 args 载荷不含尾随续体;TS 在 pop inner 之前派发全量 args
- 位置: py:dsh/cordis/events.py:339-343、400-404 vs ts:reference/vendor/cordis/src/events.ts:235-236、165-170
- 原版行为:
  ```ts
  waterfall(...args: any[]) {
    const cbs = this.dispatch('waterfall', args)   // 派发时 args 仍含 inner
    const inner = args.pop()
  ```
  诊断流收到 `(mode, name, [a1..aN], thisArg)`,含尾随的内建续体。
- 移植版现状:
  ```python
  inner = args_list.pop() if args_list and callable(args_list[-1]) else None
  data = args_list.pop(0) if args_list else None
  listeners = self._dispatch_hooks("waterfall", event_name, [data] + args_list, caller_ctx)
  ```
  诊断流收到 `[data, ...args_list]`(仅 `[config, noSave]`),且尾参是否 pop 还取决于其是否 callable。
- 修复方案:在 pop 之前以原始全量 args 派发 `internal/dispatch`。

### D11 [ADAPT] `parallel` 返回 results 列表(TS 返回 void);`AggregateError` 为自定义类(Python 3.8 无内置)
- 位置: py:dsh/cordis/events.py:246-266 vs ts:reference/vendor/cordis/src/events.ts:183-187
- 原版行为:`async parallel(...)` 仅以 `Promise<void>` 收尾,错误时 `throw new AggregateError(errors.map(e => e.reason))`。
- 移植版现状:`return list(results)` 额外返回各监听器结果;`AggregateError(errors)` 自定义类携带 `.errors`。
- 修复方案:可接受的多余返回值(对按 void 使用的调用方无破坏);自定义类字段 `errors` 与标准 `AggregateError.errors` 对齐,保留。

### D12 [ADAPT] Promise→asyncio 适配:emit 对 awaitable 调度为 task、emit_async/async bail/async waterfall/waterfall_sync 为 Python 侧 API 形态
- 位置: py:dsh/cordis/events.py:226-233、235-244、306-330、332-391、393-463 vs ts:reference/vendor/cordis/src/events.ts:194-196、204-222、234-243
- 原版行为:`emit` 同步 `.map(cb => cb(...args))`,返回的 promise 被忽略(floating);`waterfall`/`bail` 仅同步版;`serial` 为 async。
- 移植版现状:`emit` 中 `loop.create_task(res)` 保证协程不被 GC( rejection 之后成为 "never retrieved" 警告,与 TS unhandled rejection 观感相当);`emit_async`/`bail`(async)/`waterfall`(async)为等价的 asyncio 形态。
- 修复方案:保留;`emit` 的 fire-and-forget 语义已对齐(TS 同样不 await)。

### D13 [ADAPT] `internal/listener` 拦截的参数形状与非 callable 拦截结果;内建拦截器注册为 global
- 位置: py:dsh/cordis/events.py:68-81、123-128 vs ts:reference/vendor/cordis/src/events.ts:140-146、288-297
- 原版行为:拦截钩子收到 `(name, listener, options: EventOptions)`;`on()` 返回任何 truthy 拦截结果;内建拦截器经 `this.on('internal/listener', ...)` 注册(非 global,受 `Context.filter` 约束)。
- 移植版现状:拦截钩子收到位置布尔 `(name, listener, prepend, global_listener)`(见测试 `test_internal_listener_interception` 已按此约定);非 callable truthy 结果被规范化为 `lambda: True`;内建拦截器 `global_listener=True` 恒被调用。
- 修复方案:参数形状属 ADAPT(需在移植 `internal/listener` 上游插件时统一);global 化保证框架拦截在过滤场景下不丢,可接受但应记录——TS 中带 filter 的 thisArg 可能过滤掉内建拦截器,Python 永不。

### D14 [ADAPT] 监听器的 fiber 归属:TS `register()` 把 Hook 直接存为 `ctx.fiber.effect`;Python 由 EventBus 直写 `_hooks`,`ctx.on` 再以 effect 追踪 disposer(靠函数名/label 嗅探识别 bare disposer)
- 位置: py:dsh/cordis/events.py:130-145、dsh/cordis/context.py:196-202、dsh/cordis/fiber.py:319-328 vs ts:reference/vendor/cordis/src/events.ts:254-260、299-301
- 原版行为:
  ```ts
  register(label, hooks, callback, options) {
    return this.ctx.fiber.effect(() => {
      hooks[method]({ ctx: this.ctx, callback, ...options })
      return () => this.unregister(hooks, callback)
    }, label)
  }
  ```
  hook 的创建与 fiber 生命周期原子绑定;`unregister` 按 callback 同一性移除。
- 移植版现状:`EventBus.on` 直接 append `Hook` 并返回闭包 disposer(移除语义等价);`ctx.on` 把 disposer 交给 `fiber.effect`,依赖 `fn_name == "disposer"` / `"on(" in label` 的嗅探避免 disposer 被当作 setup 立即调用。
- 修复方案:功能等价可保留,但嗅探耦合脆弱——建议给 `fiber.effect` 增加显式 `is_disposer=True` 参数,`ctx.on/once` 传入。

## 已核对一致项
`is_bailed`(None↔null/undefined、False↔false、0/''/NaN 均视为 bail);`once` 先 disposer 再调原监听器;`serial` 逐个 await 至首个 bail;`emit`/`serial`/`bail` 的 `internal/dispatch` 载荷与同步监听器异常透传;`reflect.bind` 应用点;`internal/update` 内建监听器的 `global+prepend` 选项与 `cbs` 快照拷贝;disposer 按 callback 同一性移除。

## 测试缺口

### T1 waterfall `next()` 入参丢弃语义(修复 D1 后) — `test_waterfall_next_ignores_arguments`
监听器调用 `next_fn("新的数据")` 后,下一个监听器收到的首参必须仍是原始数据(穿线现被测试 `test_cordis_1to1_advanced_parity_v2.py::test_waterfall_next_continuation_and_pipeline` 固化为偏离契约)。

### T2 无 next 形参监听器的否决语义(修复 D2 后) — `test_waterfall_listener_without_next_param_vetoes_like_ts`
`def h(data): return "X"` 应否决后续监听器与内建续体,waterfall 返回 "X"。现有测试(`test_waterfall_sync_veto_without_calling_next` 等)只覆盖声明了 `next_fn` 的监听器。

### T3 链末内建续体全量实参(修复 D3) — `test_waterfall_builtin_next_receives_full_args`
`waterfall_sync("ev", cfg, no_save, builtin)` 中 `builtin` 应收到 `(cfg, no_save, next)` 三个实参。

### T4 `internal/update` 回退续体全量实参(修复 D4) — `test_internal_update_fallback_next_receives_full_args`
fiber 钩子耗尽后,派发者传入的内建 `next` 应以 `(config, no_save, next)` 被调用(stage1_parity:66 只验证了单参 lambda)。

### T5 `internal/listener` 拦截的 prepend → unshift(修复 D5) — `test_internal_update_prepend_unshifts_fiber_hook`
以 `prepend=True` 注册 `internal/update` 后,`fiber._hooks["internal/update"]` 中该钩子应位于既有钩子之前(stage1_parity:45 只覆盖 push 情形)。

### T6 失活 fiber 上 `ctx.on` 不产生总线副作用(修复 D6) — `test_on_disposed_fiber_raises_and_does_not_leak_hook`
dispose 后 `ctx.on(...)` 抛 `INACTIVE_EFFECT`,且 `bus._hooks[event]` 中不残留钩子、`internal/listener` 拦截未被派发(`test_cordis_lifecycle_reference_1to1.py:171` 只断言了异常码)。

### T7 bail 监听器 TypeError 透传(修复 D7) — `test_bail_listener_typeerror_propagates`
监听器体内 `raise TypeError("boom")` 时,`bail/bail_sync` 应向上抛出而非降级为 None 继续。

### T8 `parallel` 的 internal/dispatch mode 串(修复 D8) — `test_parallel_internal_dispatch_mode_is_emit`
监听 `internal/dispatch`,`await ctx.parallel("ev")` 观察到的 mode 应为 `'emit'`(stage1_parity:26 只覆盖 `ctx.emit`)。

### T9 waterfall 的 internal/dispatch 载荷含尾随续体(修复 D10) — `test_waterfall_internal_dispatch_args_include_inner`
`waterfall_sync("ev", cfg, no_save, builtin)` 的诊断 args 应为 `[cfg, no_save, builtin]`。

### T10 filter 异常透传(修复 D9) — `test_dispatch_filter_exception_propagates`
`caller_ctx.filter` 抛错时,`emit/bail/waterfall` 应向上传播异常,而非静默跳过钩子继续派发。

### T11 `ctx.on` 监听器随 fiber 卸载从总线移除(验证 D14 等价性) — `test_ctx_on_listener_removed_from_bus_after_fiber_dispose`
插件 `apply` 中 `ctx.on("ev", h)`,fiber dispose 后断言 `EventBus._hooks["ev"]` 不再含该钩子(现有 fiber 卸载测试只覆盖 timer 类资源,未覆盖事件监听器泄漏)。
