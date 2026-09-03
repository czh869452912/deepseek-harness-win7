# dsh/cordis/fiber.py ↔ vendor/cordis/src/fiber.ts

对照基准: `reference/vendor/cordis/src/fiber.ts` (dsh-v0.1.2-alpha.1 snapshot, 754 行) vs `dsh/cordis/fiber.py` (744 行)。
分类规则: MUST-FIX = 对调用方/其他框架代码可见的行为分歧; ADAPT = 等价 Python 实现; SKIP = 平台不可行。

## 差异清单

### D1 [MUST-FIX] 子 Fiber 的所有权未挂到父 Fiber effect 上 (父卸载不联动子卸载/registry 清理/发布失败回滚缺失)
- 位置: py:dsh/cordis/fiber.py:130-137 (构造器无任何父 effect 注册; registry.py:321-333 仅部分补偿) vs ts:reference/vendor/cordis/src/fiber.ts:265-319
- 原版行为:
  ```ts
  this.dispose = parent.fiber.effect(() => {
    const remove = runtime.fibers.push(this)
    return async () => {
      this.uid = null
      emitPluginDisposed(this.context, this)
      if (this.ctx.registry.has(runtime.callback)) {
        remove()
        if (!runtime.fibers.length) { this.ctx.registry.delete(runtime.callback) }
      }
      this._setEpoch(INACTIVE)
      if (!this.inertia) { this._updateState(() => { this.inertia = this._unload(); return FiberState.UNLOADING }) }
      while (this.inertia) { await this.inertia }
    }
  }, 'ctx.plugin()')
  ...
  } catch (error) { void Promise.resolve(this.dispose()).catch(reason => this.ctx.logger.error(reason)); throw error }
  if (this.uid !== null && parent.fiber.state !== FiberState.UNLOADING) {
    for (const name of Object.keys(this.inject)) { this._checkImpl(name) }
    this._refresh()
  }
  ```
- 移植版现状:
  ```python
  # fiber.py 构造器 (130-137) 只做 uid/ctx/state 赋值, 未注册任何 parent.fiber.effect
  self.ctx = parent_ctx.extend({"fiber": self}) if parent_ctx else None
  self.state = FiberState.PENDING
  # registry.py:321-333 补偿: runtime.add_fiber(fiber) + emit internal/plugin + _checkImpl/_refresh,
  # 但 1) 无父 Fiber effect → 父 unload 时子 fiber 不会被 dispose;
  # 2) internal/plugin 抛出时只 self._runtimes.pop(callback, None) 后 raise, 不调用 fiber.dispose() 回滚;
  # 3) 初始 _checkImpl/_refresh 不检查 `uid !== null && parent.fiber.state !== UNLOADING` 门控。
  ```
- 修复方案: 在 `Fiber.__init__` (runtime 非 None 分支) 中注册 `self.parent.fiber.effect(...)` 形式的所有权 effect: effect 体执行 `runtime.add_fiber(self)` (返回 async disposer), disposer 内依次 `uid=None` → 发 disposed 事件 (见 D3) → 从 `runtime.fibers` 移除且列表空时 `ctx.registry._runtimes.pop(callback)` → `set_epoch(INACTIVE_EPOCH)` → `inertia` 不存在时 `set_state(UNLOADING); self._unload()` → `while inertia: await`。同时把 registry.py 的 `add_fiber`/`emit`/`_checkImpl`/`_refresh` 收敛进该 effect 语义, 发布失败 (`internal/plugin` 抛出) 时 fire-and-forget 调 `fiber.dispose()` 再 re-raise, 并补上 `uid is not None and parent.fiber.state != UNLOADING` 门控。

### D2 [MUST-FIX] 直接调用 fiber.dispose() 不从 runtime.fibers / registry 注销
- 位置: py:dsh/cordis/fiber.py:651-672 vs ts:reference/vendor/cordis/src/fiber.ts:270-274
- 原版行为:
  ```ts
  if (this.ctx.registry.has(runtime.callback)) {
    remove()
    if (!runtime.fibers.length) { this.ctx.registry.delete(runtime.callback) }
  }
  ```
- 移植版现状:
  ```python
  async def dispose(self) -> None:
      if self.state in (FiberState.UNLOADING, FiberState.DISPOSED): return
      self.uid = None
      self.set_epoch(INACTIVE_EPOCH)
      ...  # 全程不触碰 self.runtime.fibers / ctx.registry
  ```
  仅 `registry.unload_plugin`/`registry.delete` 路径会移除记录; 直接 `await fiber.dispose()` 后 `registry.has(plugin)` 仍为 True, `registry.list_fibers()` 仍返回已释放 fiber。
- 修复方案: 在 `Fiber.dispose()` 中 (uid 置 None 之后) 加入与 TS 相同的注销: `if self.runtime is not None: self.runtime.remove_fiber(self); if not self.runtime.fibers and ctx.registry has runtime: 移除 runtime 记录` (或并入 D1 的 disposer)。

### D3 [MUST-FIX] `internal/plugin` (释放通知) 时机与错误隔离不符
- 位置: py:dsh/cordis/fiber.py:671-672 vs ts:reference/vendor/cordis/src/fiber.ts:120-137, 268-269
- 原版行为:
  ```ts
  function emitPluginDisposed(context: Context, fiber: Fiber) {
    const args: any[] = ['internal/plugin', fiber]
    let callbacks: Function[]
    try { callbacks = context.events.dispatch('emit', args) } catch (error) { context.logger.error(error); return }
    for (const callback of callbacks) {
      try {
        const returned = callback(...args)
        void Promise.resolve(returned).catch(error => context.logger.error(error))
      } catch (error) { context.logger.error(error) }
    }
  }
  // 在 disposer 开头、uid=null 之后、unload 之前调用
  ```
- 移植版现状:
  ```python
  self.set_state(FiberState.DISPOSED)
  if self.ctx and hasattr(self.ctx, "emit"):
      self.ctx.emit("internal/plugin", self)   # 卸载完成之后才发; events.py emit 无逐监听器 try/except
  ```
  事件在卸载完成后才发出 (TS: 卸载前、uid 已置空); 且 `dsh/cordis/events.py:220-233` 的 `emit` 不隔离监听器异常, 单个观察者抛错会中断释放流程或外泄异常。
- 修复方案: 把 disposed 事件移到 `dispose()`/D1 disposer 中 `uid=None` 之后、`_unload` 之前; 新增专用 `_emit_plugin_disposed()`: 显式经 `events._dispatch_hooks("emit", ...)` 取回调并逐个 `try/except` + awaitable 兜底 catch, 失败记 `ctx.logger.error`。

### D4 [MUST-FIX] inject 值语义被改写 (required 标志) 且未写入 ctx 拦截表
- 位置: py:dsh/cordis/fiber.py:104-116 vs ts:reference/vendor/cordis/src/fiber.ts:238-245
- 原版行为:
  ```ts
  const injectEntries = Object.entries(this.inject)
  if (injectEntries.length) {
    this.ctx[Context.intercept] = Object.create(parent[Context.intercept])
    for (const [name, config] of injectEntries) {
      if (isNullable(config)) continue
      this.ctx[Context.intercept][name] = config   // inject 值 = 服务拦截配置
    }
  }
  ```
- 移植版现状:
  ```python
  if isinstance(raw_inject, (list, tuple)):
      self.inject = {k: None for k in raw_inject}
  elif isinstance(raw_inject, dict):
      self.inject = dict(raw_inject)   # 值被 _refresh 当作 {"required": bool}/bool 解释
  # 无任何 self.ctx._intercept_map 写入
  ```
  TS 中 inject 值是 intercept config (service.ts:87 经 `ctx[Context.intercept]` 原型链读取); Python 里 fiber 从不设置 `ctx._intercept_map` (context.py:319 的 `intercept()`/loader 是唯一入口), `@inject({"tools": {"intercept": True}})` 声明的拦截配置实际不生效。另外 `_refresh` 依赖 `required` 标志 (见 D15) 属同一语义改写。
- 修复方案: 在 `Fiber.__init__` (runtime 分支) 中, 对 `self.inject` 中非 None 值执行 `self.ctx._intercept_map = dict(parent._intercept_map)` 后逐项 `self.ctx._intercept_map[name] = config` (或经 `ctx.intercept()`), 使 `service.resolve_intercept_config` 能读到; `required` 解释若保留为移植扩展须与 D15 一并裁决。

### D5 [MUST-FIX] name 属性缺少祖先链回溯
- 位置: py:dsh/cordis/fiber.py:139-149 vs ts:reference/vendor/cordis/src/fiber.ts:336-343
- 原版行为:
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
- 移植版现状:
  ```python
  @property
  def name(self) -> str:
      if self.plugin:
          if hasattr(self.plugin, "name") and self.plugin.name: return self.plugin.name
          if hasattr(self.plugin, "id") and self.plugin.id: return self.plugin.id
          if isinstance(self.plugin, type): return self.plugin.__name__
          return self.plugin.__class__.__name__
      return "root"
  ```
  匿名插件在 TS 中继承最近命名祖先的 runtime 名; Python 返回自身类名或 "root", 影响日志、`teardown({name})` effect 标签、`registry.get_fiber(name)` 查找。
- 修复方案: 在 `name` getter 中沿 `self.parent.fiber` (经 `getattr(parent, "fiber", None)`) 向上回溯取第一个非空 `runtime.name`/插件名, 到底返回 "root"; 保留 `plugin.id` 兜底可置于回溯之后。

### D6 [MUST-FIX] assert_active 在 FAILED/UNLOADING 状态提前拒绝并转抛存储错误
- 位置: py:dsh/cordis/fiber.py:161-165 vs ts:reference/vendor/cordis/src/fiber.ts:351-354
- 原版行为:
  ```ts
  assertActive() {
    if (this.uid !== null) return
    throw new CordisError('INACTIVE_EFFECT')
  }
  ```
- 移植版现状:
  ```python
  def assert_active(self) -> None:
      if self.uid is None or self.state in (FiberState.DISPOSED, FiberState.UNLOADING, FiberState.FAILED):
          if self._error is not None: raise self._error
          raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")
  ```
  TS 中 FAILED fiber (uid 未清) 仍可注册 effect (effect() 只额外拦 UNLOADING), 首次启动失败的插件可在 catch 后注册兜底 effect; Python 一律拒绝且抛的是原始 `_error` 而非 CordisError, 调用方按 `CordisError.code == 'INACTIVE_EFFECT'` 判断会失效。
- 修复方案: `assert_active` 仅保留 `uid is None → CordisError("INACTIVE_EFFECT")`; UNLOADING 拦截留在 `effect()` 内 (已存在); 删除 `raise self._error` 分支或将其限定到 `await_settled`。

### D7 [MUST-FIX] effect() 以函数名/标签启发式区分"效果体 vs 现成 disposer", 偏离 TS "总是执行" 语义; 缺少 TypeError('Invalid effect') 校验
- 位置: py:dsh/cordis/fiber.py:319-362 vs ts:reference/vendor/cordis/src/fiber.ts:356-399, 415-424
- 原版行为:
  ```ts
  const effect: Effect = runner.execute.call(this)   // 无条件执行
  if (typeof effect === 'function') return runner.collect(effect)
  else if (isNullable(effect)) { /* ok */ }
  else if (!isObject(effect)) throw new TypeError('Invalid effect')
  else if ('then' in effect) { ... } else if (Symbol.iterator in effect) { ... }
  else if (Symbol.asyncIterator in effect) { ... } else { throw new TypeError('Invalid effect') }
  ```
- 移植版现状:
  ```python
  fn_name = getattr(execute_or_disposer, "__name__", "")
  if (fn_name in ("disposer","_disposer","cancel_effect",...,"teardown","cleanup","remove","detach")
      or "disposer" in fn_name or "on(" in label or "once(" in label or "systemPrompt." in label):
      collect_disposer(execute_or_disposer)      # 不执行, 视为现成 disposer
  else:
      res = execute_or_disposer()
      ...
  elif res is None or isinstance(res, (bool, int, float, str)): ...  # 原始值静默接受
  # dict/其它对象返回值: 落空所有分支, 静默忽略
  ```
- 修复方案: 消除脆弱的字符串启发式并建立安全分流：① 为 `Fiber.effect` 引入 `is_disposer: bool = False` 形参，并在 `Context` 增加 `ctx.disposable(fn)` 语义入口。当 `is_disposer=True` 时，直接收集入 `_disposables`，绝不重复执行；② 默认（`is_disposer=False`）下严格对齐 TS：无条件调用 `execute()` 并按 TS 语义收集其返回值（可调用 disposer、awaitable、生成器等，非法类型抛 `TypeError("Invalid effect")`）；③ 对现有遗留的裸传 disposer 调用点，向后兼容允许识别标记为 `_is_disposer` 或已知由 `ctx.on` 返回的 Disposer 对象，杜绝直接移除启发式导致全仓监听器在注册时被误调销毁。

### D8 [MUST-FIX] effect 内部清理顺序: TS 严格串行 await 链 (含 async), Python 同步先清完 + 异步延后顺序 await
- 位置: py:dsh/cordis/fiber.py:196-213 (rollback_sync), 266-278, 296-301 (cancel_effect 非执行路径) vs ts:reference/vendor/cordis/src/fiber.ts:427-442
- 原版行为:
  ```ts
  const dispose = () => {
    if (disposing) return disposalTask
    disposing = true
    let task!: void | Promise<void>
    for (const disposable of disposables.splice(0).reverse()) {
      if (task) { task = task.then(() => runDisposable(disposable)) }
      else {
        const result = runDisposable(disposable)
        if (isObject(result) && 'then' in result) { task = result as any }
      }
    }
    return disposalTask = task
  }
  ```
- 移植版现状:
  ```python
  while disposables:
      disp = disposables.pop()          # 先同步弹完
      ...
      res = disp()
      if inspect.isawaitable(res): async_disposers.append(r)   # 异步先挂起
  ...
  for r in async_disposers: await r     # 之后按顺序 await
  ```
  TS 中前一个 disposer 的 Promise 未 settle 前不调用下一个 (后注册的 async disposer 会阻塞先注册的 sync disposer); Python 中后注册 async disposer 挂起后, 先注册的 sync disposer 仍立即执行, 交错时序可见 (如先注册的清理依赖后注册资源已释放)。
- 修复方案: `cancel_effect`、`rollback_sync`、`_dispose_after_barrier`、`_run_cleanup` 统一改为"逆序弹出 → await 上一个结果 (含同步返回值) → 再运行下一个"的链式模型 (可用 `async def` 循环内逐个 `await inspect.isawaitable(res) and res or None`), 保证与 TS 相同的严格 LIFO 串行语义。

### D9 [MUST-FIX] _unload: TS Promise.all 并发释放且逐个 logger.error + composeError 栈增强; Python 串行且降级为 warn/stderr
- 位置: py:dsh/cordis/fiber.py:600-649 vs ts:reference/vendor/cordis/src/fiber.ts:675-686
- 原版行为:
  ```ts
  await Promise.all(this._disposables.clear().map(async (dispose) => {
    try {
      await composeError(async (info) => { await Promise.resolve(); info.error = new Error(); await runDisposable(dispose) }, this._runner.getOuterStack)
    } catch (reason) { this.ctx.logger.error(reason) }
  }))
  ```
- 移植版现状:
  ```python
  for disposer in disposers:
      try:
          res = disposer()
          if inspect.isawaitable(res): async_disposers.append(res)
      except Exception as e:
          ... self.ctx.logger("fiber").warn("Exception during unload for '%s': %s", self.name, e)  # 或 stderr
  ...
  for r in async_disposers: await r   # 顺序 await, 且 warn 级别
  ```
  差异: (1) TS 各 effect 清理并发推进 (互不阻塞), Python 同步调用串行、异步顺序 await; (2) TS 错误级别 error, Python warn/stderr; (3) TS 每个清理经 `composeError(.., getOuterStack)` 附增外层栈, Python 导入了 `compose_error` 但 fiber.py 全程未用。
- 修复方案: `_unload` 改为 `await asyncio.gather(*[async _dispose_one(d) ...], return_exceptions=False)` 形式: 每个 disposer 独立 `try/except` → `ctx.logger.error(reason)`; 每个清理用 `compose_error(..., self.get_outer_stack)` 包裹; 保留 LIFO 顺序启动。

### D10 [MUST-FIX] _reload 缺少微任务检查点与过期 epoch 复查
- 位置: py:dsh/cordis/fiber.py:528-534 vs ts:reference/vendor/cordis/src/fiber.ts:646-658
- 原版行为:
  ```ts
  private async _reload() {
    this.store = { ...this._store }
    const oldEpoch = this._runner.epoch
    try {
      await Promise.resolve()
      if (this._runner.epoch === oldEpoch) {   // 排队中的 disposer 已使加载失效时不执行插件代码
        this.config = this._resolveConfig(this._config)
        await this._execute(this._runner)
        this._error = undefined
      }
    } ...
  ```
- 移植版现状:
  ```python
  def _reload(self) -> None:
      epoch = self.epoch
      try:
          self.store = dict(self._store)
          self.config = self._resolve_config(self._config)   # 立即同步执行, 无检查点
  ```
  TS 在真正加载前让出一个微任务并复查 epoch: 检查点前入队的 disposer (如依赖刚被释放) 会阻止插件代码运行; Python 同步立刻加载, 竞态下会用过期依赖执行 apply。
- 修复方案: `_reload` 改为 async: 进入后先 `await asyncio.sleep(0)`, 再 `if self.epoch == epoch:` 才做 config 解析 + apply; `set_epoch`/`_unload` 完成回调中的惯序随之对齐 (inertia task 由 `_reload` 自身返回)。

### D11 [MUST-FIX] 插件回调 / init 返回值未按 Effect 解释 (disposer/Promise/迭代器全部丢弃)
- 位置: py:dsh/cordis/fiber.py:551-570 vs ts:reference/vendor/cordis/src/fiber.ts:250-261, 356-400
- 原版行为:
  ```ts
  execute: function () {
    if (isConstructor(runtime.callback)) {
      const instance = new runtime.callback(this.ctx, this.config)
      for (const hook of instance?.[symbols.initHooks] ?? []) hook()
      return instance?.[symbols.init]?.()          // 返回值进入 _execute
    } else { return runtime.callback(this.ctx, this.config) }
  }
  // _execute: 函数→collect 为 disposer; Promise→then 收集; (async) iterable→逐个收集; 非法→TypeError
  ```
- 移植版现状:
  ```python
  init_res = init_fn()
  if inspect.isgenerator(init_res) or inspect.isasyncgen(init_res):
      self.effect(lambda r=init_res: r, label=f"init({self.name})")
  elif inspect.isawaitable(init_res):
      loop.create_task(init_res)          # resolve 出的 disposer 被丢弃
  # init 返回普通函数 → 静默丢弃
  ...
  res = self.plugin.apply(self.ctx)        # apply 返回值: 函数/Promise/生成器一律丢弃
  ```
  TS 插件 (类 init 或函数回调) 可 `return () => cleanup` / `return Promise<disposer>` / `yield` 清理函数; Python 仅 init 生成器路径生效, 其余全丢, 卸载时资源泄漏。
- 修复方案: 把 `_reload` 中 `apply`/`init` 的返回值统一交过一个 `_execute_effect(value, label)` 帮助函数, 完整复刻 TS `_execute` 分支 (含 D7 的 TypeError 校验与 asyncgen 的 epoch 检查); 删除 `loop.create_task(init_res)` fire-and-forget。

### D12 [MUST-FIX] 重载不重建插件实例: TS 每次 _reload 重新 new runtime.callback, Python 复用同一实例
- 位置: py:dsh/cordis/fiber.py:565-570 (apply 复用) vs ts:reference/vendor/cordis/src/fiber.ts:250-257
- 原版行为:
  ```ts
  execute: function () {
    if (isConstructor(runtime.callback)) {
      const instance = new runtime.callback(this.ctx, this.config)   // 每次 reload 新实例
      for (const hook of instance?.[symbols.initHooks] ?? []) hook()
      return instance?.[symbols.init]?.()
    }
  ```
- 移植版现状:
  ```python
  if hasattr(self.plugin, "apply") and callable(self.plugin.apply):
      res = self.plugin.apply(self.ctx)      # 同一实例反复 apply
  ```
  TS restart/update 后插件 `__init__`/实例字段重置; Python 保留旧实例状态 (计数器、缓存、监听器残留), 重载行为可见偏离。
- 修复方案: 区分类插件与对象插件的生命周期：① 对于类插件（构造形态，`isclass(runtime.callback)`），`_reload` 每次重载时重新执行 `new_inst = plugin_cls(self.ctx, self.config)`，重新执行 initHooks 与 init，彻底清除上一轮生命周期的脏状态（与 TS 一致）；② 对于直接传入实例的对象插件（`Plugin.Object` 形态），保持复用该实例并调用其 `apply(self.ctx, self.config)`；③ 在 `runtime` 上明确区分类引用与用户预置实例，`self.plugin` 始终指向当前激活的实例。

### D13 [MUST-FIX] 异步 _reload 完成后缺少 epoch 复查链 (同步路径有, 异步路径没有)
- 位置: py:dsh/cordis/fiber.py:572-587 vs ts:reference/vendor/cordis/src/fiber.ts:665-672
- 原版行为:
  ```ts
  this._updateState(() => {
    if (this._runner.epoch === oldEpoch) { this.inertia = undefined }
    else { this.inertia = this._unload(); return FiberState.UNLOADING }   // 加载期间 epoch 变化 → 链式卸载
  })
  ```
- 移植版现状:
  ```python
  async def _async_wait_res():
      try:
          await res
          self._error = None
          self.set_state(FiberState.ACTIVE)     # 不检查 self.epoch != epoch
      except Exception as e: ...
  ```
  同步路径在 `_reload` 尾部有 `if self.epoch != epoch: _unload()` (py:596-598), 但 awaitable apply 分支完成后直接置 ACTIVE: 期间若发生 dispose/restart (`set_epoch(INACTIVE_EPOCH)`), fiber 停留在 ACTIVE 携带过期 epoch, `dispose()` 的 `while inertia` 循环因无新 inertia 而跳过卸载 → effects 泄漏。
- 修复方案: `_async_wait_res` 成功分支改为: `self._error = None; self.set_state(ACTIVE)` 后追加 `if self.epoch != epoch: self.set_state(UNLOADING); self._unload()`; 失败分支同样在 `set_state(FAILED)` 后复查 (TS 的 `_updateState` 统一处理)。

### D14 [MUST-FIX] 启动失败未写日志: TS ctx.logger.error(reason), Python 仅存 _error
- 位置: py:dsh/cordis/fiber.py:591-594 vs ts:reference/vendor/cordis/src/fiber.ts:659-664
- 原版行为:
  ```ts
  } catch (reason) {
    // impl guarantees that the error is non-null (?)
    this.ctx.logger.error(reason)
    this._error = reason
    this._runner.epoch = INACTIVE
  }
  ```
- 移植版现状:
  ```python
  except Exception as e:
      self._error = e
      self.epoch = INACTIVE_EPOCH
      self.set_state(FiberState.FAILED)     # 无任何 logger 输出
  ```
  未 `await` fiber 的调用方 (registry 批量装载) 完全看不到启动失败。
- 修复方案: except 分支首行加 `if self.ctx and hasattr(self.ctx, "logger"): self.ctx.logger.error(e)` (无 logger 时保留 stderr 兜底, 与 `_unload` 风格一致)。

### D15 [MUST-FIX] _refresh 语义偏离: TS 全依赖必须且仅按 uid 串接; Python 增加 optional 注入与非 ACTIVE 状态检查
- 位置: py:dsh/cordis/fiber.py:476-506 vs ts:reference/vendor/cordis/src/fiber.ts:611-623
- 原版行为:
  ```ts
  _refresh() {
    let epoch: string | boolean = false
    epoch = ''
    for (const name of Object.keys(this.inject)) {
      const impl = this._store[name]
      if (!impl) { epoch = INACTIVE; break }        // 一切依赖都必须就位
      epoch += ':' + impl.fiber.uid                 // 仅 uid 变化驱动重载; 不看依赖 state
    }
    this._setEpoch(epoch)
  }
  ```
- 移植版现状:
  ```python
  is_required = True
  if isinstance(config, dict): is_required = config.get("required", True)
  elif isinstance(config, bool): is_required = config
  impl = self._store.get(name)
  if not impl:
      if is_required: epoch = INACTIVE_EPOCH; break
      continue                                       # optional 依赖缺失不失效
  fib = getattr(impl, "fiber", None)
  if fib is not None and fib.state != FiberState.ACTIVE and getattr(fib, "uid", None) not in (0, None):
      if is_required: epoch = INACTIVE_EPOCH; break   # 依赖 LOADING 也把依赖方打回 INACTIVE
      continue
  epoch += f":{getattr(fib, 'uid', 0)}"
  ```
  行为分歧: (1) `required: False`/`"dep?"` optional 注入是 Python 扩展, TS 不存在 → epoch 组成不同, 依赖缺失时 Python 可激活而 TS 恒 INACTIVE; (2) 依赖处于 LOADING (restart 中途) 时 Python 立即卸载依赖方再重载, TS 中依赖 restart 不改 uid、依赖方保持 ACTIVE 不动, 仅依赖被 dispose (uid→null) 或换新实现 (新 uid) 才重载。
- 修复方案: 以 TS 为准重写 `_refresh`: 去掉 dep-state 检查, epoch 严格 `":" + impl.fiber.uid` 串接; optional 注入若作为产品扩展保留, 须将 `required` 判定移入 `_checkImpl`(缺失即不入 store) 并在 AGENTS/文档标注为许可偏差, 同时补 TS 对照测试锁定两种行为。

### D16 [MUST-FIX] 卸载后终态判定优先级: TS 先 uid 后 _error, Python 先 _error
- 位置: py:dsh/cordis/fiber.py:624-626, 643-645 vs ts:reference/vendor/cordis/src/fiber.ts:574-579
- 原版行为:
  ```ts
  private _getState() {
    if (this.uid === null) return FiberState.DISPOSED   // 已 dispose 即使有 _error 也是 DISPOSED
    if (this._error) return FiberState.FAILED
    if (this._runner.epoch !== INACTIVE) return FiberState.ACTIVE
    return FiberState.PENDING
  }
  ```
- 移植版现状:
  ```python
  final_state = FiberState.FAILED if self._error is not None else (FiberState.PENDING if self.uid is not None else FiberState.DISPOSED)
  ```
  带 `_error` 的 fiber 被 dispose 后, TS 报 DISPOSED、Python 报 FAILED, `internal/status` 载荷与状态机断言可见分歧。
- 修复方案: `_unload` 两处终态改为与 `_getState` 相同的优先级: `if self.uid is None: DISPOSED elif self._error: FAILED else: PENDING` (建议直接抽 `_get_state()` 帮助函数统一)。

### D17 [MUST-FIX] CordisError 默认消息用错误码而非可读文案
- 位置: py:dsh/cordis/fiber.py:24-28 vs ts:reference/vendor/cordis/src/fiber.ts:157-174
- 原版行为:
  ```ts
  export const Code = { INACTIVE_EFFECT: 'cannot create effect on inactive context' } as const
  constructor(public code: CordisError.Code, message?: string) { super(message ?? CordisError.Code[code]) }
  ```
- 移植版现状:
  ```python
  class CordisError(Exception):
      def __init__(self, code: str, message: Optional[str] = None):
          self.code = code
          super().__init__(message or code)    # str(err) == "INACTIVE_EFFECT"
  ```
- 修复方案: 增加 `CODE_MESSAGES = {"INACTIVE_EFFECT": "cannot create effect on inactive context"}`, `super().__init__(message or CODE_MESSAGES.get(code, code))`。

### D18 [MUST-FIX] 根 Fiber dispose 语义: TS 根 dispose == restart, Python 根会真正销毁
- 位置: py:dsh/cordis/fiber.py:132-137 (无 dispose 覆盖) vs ts:reference/vendor/cordis/src/fiber.ts:320-332
- 原版行为:
  ```ts
  } else {
    this.uid = 0
    this.ctx = this.context = parent
    this.state = FiberState.ACTIVE
    this.store = Object.create(null)
    ...
    this.dispose = () => this.restart()
  }
  ```
- 移植版现状: Python 根 fiber 走通用 `dispose()`: `uid=None` → `set_epoch(INACTIVE_EPOCH)` (''→INACTIVE) → `_unload` → 终态 DISPOSED, 根上下文被销毁而非重启。
- 修复方案: 根分支 (`runtime is None`) 覆盖 `dispose` 为 `self.restart()` (或 `async def dispose(): return self.restart()`), 保持 uid=0 恒定。

### D19 [ADAPT] effect 返回值缺少 AsyncDisposable (PromiseLike) 语义与 effectInertia join
- 位置: py:dsh/cordis/fiber.py:173-424 vs ts:reference/vendor/cordis/src/fiber.ts:64-66, 112-117, 504-560
- 原版行为: TS wrapper 挂 `symbols.effect` 元数据并定义 `wrapper.then`, `await ctx.effect(...)` = 等待 setup 完成 → 触发 `disposeAsync` → 结果解析为 disposer; `effectInertia` WeakMap 让 `runDisposable` 可加入他方已开始的清理 (`effectInertia.get(dispose)?.() ?? result`); wrapper 在未 epoch 时返回 `setupFailed ? inFlight : undefined`。
- 移植版现状: Python 返回普通函数 `cancel_effect`; 重复调用返回 `in_flight_cleanup` task (近似 join), 但无 await 协议 (`await effect_disposer` 不可用), 无 `effectInertia` 等价物 (`runDisposable` 直调 `dispose()`), `_effect_metas` 以函数对象为键替代 symbol 属性。
- 修复方案: 为 `cancel_effect` 增加 `__await__`/`__call__` 后返回 task 的统一约定 (await = 等 setup 后触发清理), 或提供 `await_disposer()` 辅助; join 语义保持现有 "已 disposed 则返回 in_flight_cleanup" 并补测试。命名/符号差异本身可接受。

### D20 [ADAPT] getEffects 数据源与嵌套 children 缺失
- 位置: py:dsh/cordis/fiber.py:58-68, 184, 426-428 vs ts:reference/vendor/cordis/src/fiber.ts:96-101, 444-456, 568-572
- 原版行为:
  ```ts
  getEffects() { return [...this._disposables].map(dispose => dispose[symbols.effect]).filter(Boolean) }
  // runner.collect: if (dispose[symbols.effect]) meta.children.push(dispose[symbols.effect])  → 嵌套树
  ```
- 移植版现状: Python 用独立 `_effect_metas: Dict[cancel_effect, EffectMeta]`, `EffectMeta.children` 恒为空列表 (`collect_disposer` 不回填), 嵌套 effect 的归属关系丢失; 返回 `to_dict()` 纯 dict 而非带 children 的元数据节点。
- 修复方案: `collect_disposer` 中若收集到的 disposer 带 `symbols.effect` 元数据 (或来自子 `ctx.effect()`), 将其 meta append 到当前 `meta.children`; `get_effects()` 保留 dict 序列化但输出 children。

### D21 [ADAPT] resolve_config 与 TS resolveConfig 的 schema 管道差异
- 位置: py:dsh/cordis/fiber.py:31-55 vs ts:reference/vendor/cordis/src/fiber.ts:50-62
- 原版行为:
  ```ts
  export function resolveConfig(runtime: Plugin.Runtime, config: any) {
    if (!runtime.Config) return config
    const result = runtime.Config['~standard'].validate(config)
    if ('then' in result) throw new TypeError('Async config validation is not supported')
    if (result.issues) throw new ValidationError(result.issues)
    else return result.value
  }
  ```
- 移植版现状: Python 额外做 `config is None → {}` 与 `plugin.config` 默认值拷贝, schema 来源为 `plugin.schema or plugin.Config` (Schema 实例或鸭子类型 validate), 无 async 校验拒绝; `_resolve_config` 中 `waterfall_sync("internal/config", ...)` 未传 TS 的 `() => config` 兜底回调、`update()` 未传 caller_ctx (TS 两处均以 `this` 为 caller)。
- 修复方案: 保留 Schema 适配, 但补: (1) validate 结果为 awaitable 时 `raise TypeError("Async config validation is not supported")`; (2) `update()` 的 `waterfall_sync(..., caller_ctx=self.ctx)` 与 `_resolve_config` 一致; (3) None→{} 默认值化属附加行为, 若 schema 依赖 undefined 触发 default 需验证 schema.validate(None) 兼容, 否则删除预置。

### D22 [ADAPT] _checkImpl: check 调用无 getTraceable this 绑定; 异常日志目标与级别不同
- 位置: py:dsh/cordis/fiber.py:452-474 vs ts:reference/vendor/cordis/src/fiber.ts:597-609
- 原版行为:
  ```ts
  if (impl.check && !impl.check.call(getTraceable(this.ctx, impl.value))) { return delete this._store[name] }
  } catch (error) { impl.fiber.ctx.logger.error(error); return delete this._store[name] }
  ```
- 移植版现状: `impl.check()` 无绑定调用 (JS `this` 语义在 Python 无对应, Service.check 通常已绑实例, 属可接受适配); check 抛错时记到**自身** fiber 的 logger 且级别为 `warn` (无 logger 时写 stderr), TS 记到 **impl 所属 fiber** 的 ctx.logger 且级别 `error`。
- 修复方案: 异常路径改为 `impl.fiber.ctx.logger.error(e)` (fallback 自身 logger.error), 对齐级别与归属; check 绑定可维持现状但补注释说明。

### D23 [ADAPT] restart(new_config) 为 Python 扩展且重启前重查全部依赖; settle 等待范围更宽
- 位置: py:dsh/cordis/fiber.py:698-726, 728-741 vs ts:reference/vendor/cordis/src/fiber.ts:704-723
- 原版行为:
  ```ts
  async restart() { this.assertActive(); this._setEpoch(INACTIVE); this._refresh(); await this.await() }
  async await() { while (this.inertia) { await this.inertia } if (this._error) throw this._error; return this }
  ```
- 移植版现状: Python `restart(new_config=None)` 接受新 config (TS 只能经 update), 且 restart 中先 `for name: self._checkImpl(name)` 再 `_refresh()` (TS restart 不重查 impl, 仅 reflect.notify 驱动); `_wait_settled`/`await_settled` 额外等待 `_in_flight_effects` (effect setup 任务), TS `await()` 只等 inertia。
- 修复方案: 保留扩展则文档化; 行为对齐项: `await` 语义如需严格一致应移除 `_in_flight_effects` 等待或注明差异; `_checkImpl` 重查会导致 Python 在 TS 保持惰性的场景下重启, 建议移除以贴合 TS。

### D24 [ADAPT] __getattr__ 将未知属性透传给 plugin 实例 (TS 无此机制)
- 位置: py:dsh/cordis/fiber.py:151-156 vs ts:reference/vendor/cordis/src/fiber.ts (无对应)
- 原版行为: TS Fiber 属性面固定, 服务/插件属性经 Context 代理暴露; Fiber 本身不代理插件成员。
- 移植版现状: `fiber.xxx` 落到 `getattr(self.plugin, name)`, 可能意外暴露插件内部成员并掩盖 AttributeError。
- 修复方案: 保留为移植便利但把 `__getattr__` 白名单化 (仅公开 `config`/`ctx` 等明确成员), 或至少在 `name.startswith("_")` 之外增加显式允许列表, 防止与未来 Fiber 字段冲突。

## 测试缺口

### T1 父插件 unload 级联 dispose 子插件 (D1) — `test_fiber_parent_unload_disposes_child_fibers`
父插件 apply 中 `ctx.plugin(ChildPlugin)`; await 父 `fiber.dispose()` 后断言子 fiber `state == DISPOSED`、子 effect 清理已执行、`registry.has(ChildPlugin) is False`。

### T2 直接 fiber.dispose() 后 registry/runtime 记录注销 (D2) — `test_fiber_direct_dispose_deregisters_from_registry`
`fiber = ctx.plugin(P)`; `await fiber.dispose()`; 断言 `ctx.registry.has(P) is False` 且 `list_fibers()` 不含该 fiber (现状: 仍为 True, 暴露分歧)。

### T3 internal/plugin 释放通知的时机与观察者异常隔离 (D3) — `test_plugin_disposed_event_before_unload_and_error_isolated`
观察者 1 记录 `fiber.uid is None` 与当前 effect 清理是否已跑; 观察者 2 抛错; 断言事件在清理前发出 (uid 已置空、disposers 未执行)、观察者 2 异常被记 logger.error 且 dispose 正常完成。

### T4 inject 拦截配置写入 ctx._intercept_map (D4) — `test_inject_intercept_config_reaches_service`
插件声明 `inject = {"db": {"url": "x"}}`, db Service 在 `resolve_intercept_config`/init 中读取拦截值; 断言 apply 期间能读到注入的拦截配置 (现状: 读不到)。

### T5 name 祖先回溯 (D5) — `test_fiber_name_inherits_nearest_named_ancestor`
匿名函数插件被命名父插件加载; 断言 `child_fiber.name == 父插件名` 而非 `"root"`/匿名类名。

### T6 FAILED fiber 仍可注册 effect (D6) — `test_effect_registration_allowed_on_failed_fiber`
插件 apply 抛错使 fiber FAILED; 在 except 分支 `fiber.ctx.effect(...)`; 断言不抛 CordisError 且 dispose 时清理执行 (现状: 抛存储的原错误)。

### T7 效果体函数名启发式不吞掉应执行的 body (D7) — `test_effect_executes_body_named_cleanup_or_teardown`
`ctx.effect(function_named_cleanup)` (该函数执行后返回真 disposer); 断言函数体被执行、返回的 disposer 在卸载时调用 (现状: 函数体被当作现成 disposer 从不执行)。另加 `test_effect_rejects_invalid_return_shape`: apply/effect 返回数字/dict → `TypeError("Invalid effect")`。

### T8 混合同步/异步 disposer 严格串行 LIFO (D8) — `test_effect_mixed_sync_async_disposer_strict_lifo_chaining`
后注册的 async disposer 挂起 (event gate) 时, 先注册的 sync disposer 不得先执行; 释放 gate 后顺序应为 `[async, sync]` (TS 链式语义)。

### T9 _unload 并发释放与逐个 error 级日志 (D9) — `test_unload_disposers_run_concurrently_and_log_error_level`
两个 effect 的清理互相等待对方 gate (TS Promise.all 下可同时推进); 断言都能完成; 且某个清理抛错时 `ctx.logger` 收到 `error` 级记录、其余清理不受影响 (现状: warn/串行)。

### T10 _reload 微任务检查点拦截过期加载 (D10) — `test_reload_skips_plugin_execution_on_stale_epoch`
依赖可用瞬间 (notify 触发 `_refresh`) 立即注入并 dispose 该依赖; 断言 apply 未执行或加载后立即按新 epoch 链式卸载, 而非以过期依赖完成 ACTIVE。

### T11 插件回调/init 返回 disposer 的收集 (D11) — `test_plugin_callback_returned_disposer_collected`
类插件 `init` 返回 `() => cleanup()`、函数插件 `apply` 返回 disposer、返回 `Promise/async` 解析出 disposer、生成器 yield 多个 disposer; 各自断言 dispose 时清理被调用 (现状: 仅 init 生成器路径生效)。

### T12 重载重建插件实例 (D12) — `test_plugin_instance_recreated_on_restart`
插件构造器递增类级计数; `await fiber.restart()`; 断言构造器再次执行、实例字段重置 (现状: 仅 apply 重跑, 构造器只跑一次)。

### T13 异步 apply 期间 epoch 变化触发链式卸载 (D13) — `test_async_apply_epoch_change_chains_unload`
apply 为挂起协程; 挂起期间 `fiber.dispose()`/依赖移除; 断言最终不落入 ACTIVE、effects 全部清理、dispose 正常返回 (现状: 停留 ACTIVE, dispose 提前返回造成泄漏)。

### T14 启动失败写入 logger.error (D14) — `test_reload_failure_logged_via_error`
apply 抛错; 断言 `ctx.logger` 记录了该异常 (级别 error) 且 `fiber.error` 为原异常、状态 FAILED。

### T15 复合 epoch: optional 注入与依赖 LOADING 语义 (D15) — `test_optional_inject_and_dependency_reload_epoch_semantics`
(a) `inject = {"ghost": {"required": False}}` 服务永不可用 → 按 TS 应 PENDING/INACTIVE (Python 现激活), 用测试锁定裁决后的行为; (b) 依赖 restart (uid 不变) 期间断言依赖方 fiber 保持 ACTIVE 不卸载 (Python 现会 unload+reload)。

### T16 dispose 后终态优先级 (D16) — `test_disposed_fiber_with_error_reports_disposed`
apply 抛错 (fiber FAILED) 后 `await fiber.dispose()`; 断言 `state == DISPOSED` 且 `internal/status` 最后一次转换 old→DISPOSED (现状: FAILED)。

### T17 CordisError 消息文案 (D17) — `test_cordis_error_default_message_text`
`str(CordisError("INACTIVE_EFFECT")) == "cannot create effect on inactive context"` (现状: `"INACTIVE_EFFECT"`)。

### T18 根 fiber dispose == restart (D18) — `test_root_fiber_dispose_restarts_instead_of_disposing`
`ctx.fiber.dispose()` (或等价调用) 后断言根 fiber `uid == 0`、state 回到 ACTIVE/LOADING 而非 DISPOSED。

---
统计: MUST-FIX 18 (D1–D18) / ADAPT 6 (D19–D24) / SKIP 0 / 测试缺口 18 (T1–T18)。
