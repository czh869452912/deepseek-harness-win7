# dsh/cordis/registry.py ↔ reference/vendor/cordis/src/registry.ts

对比基线：TS 为实现权威。注意 TS 的 registry 只负责“归一化插件形状 + runtime 记录 + 创建 Fiber”，插件实例化/启动全部在 `Fiber._reload → _runner.execute`（fiber.ts:250-263）；Python 把实例化提前到了 `registry.plugin()`，这是本文件最大的语义分歧来源。

## 差异清单

### D1 [MUST-FIX] 类插件在 registry.plugin() 内用“registry 的 ctx（root）”立即实例化；TS 在 fiber 激活时用“fiber 自己的 ctx”才实例化
- 位置: py:registry.py:242-271 vs ts:fiber.ts:250-263（`_runner.execute`）、registry.ts:330
- 原版行为:
  ```ts
  // fiber.ts _runner.execute —— reload（依赖就绪）时才构造，且传入 fiber.ctx（parent.extend({fiber})）
  if (isConstructor(runtime.callback)) {
    const instance = new runtime.callback(this.ctx, this.config)
    ...
  } else {
    return runtime.callback(this.ctx, this.config)
  }
  ```
- 移植版现状:
  ```python
  # registry.plugin() 内：用 self.ctx（RegistryService.ctx = root）立即构造
  if issubclass(plugin_cls_or_instance, Service):
      plugin_inst = plugin_cls_or_instance(self.ctx, config=config)
  ...
  fiber = Fiber(self.ctx, plugin_inst, config=config, runtime=runtime, inject=inject_deps, ...)
  ```
- 修复方案: 把类插件的实例化移入 `Fiber._reload`（构造参数为 `(self.ctx, self.config)`），但在 `registry.plugin()` 阶段必须支持先静态解析类元数据（从类对象及 `@inject` 提取 `inject`, `provide`, `Config`），在未实例化时即可建立依赖拓扑；依赖就绪触发 `_reload` 时再执行 `cls(self.ctx, self.config)`。连带影响见 D2/D3 与 8-service.md D1：`Service.__init__` 里 `ctx.provide(...)` 的 impl.fiber 将正确落在插件 fiber 上，随插件卸载而注销。

### D2 [MUST-FIX] reload 复用旧实例；TS 每次激活都 new 一个新实例
- 位置: py:fiber.py:528-570（`_reload` 直接用 `self.plugin`） vs ts:fiber.ts:250-257（每次 `_execute` 都 `new runtime.callback(...)`）
- 原版行为:
  ```ts
  execute: function () {
    if (isConstructor(runtime.callback)) {
      const instance = new runtime.callback(this.ctx, this.config)   // 每次 reload 新实例
  ```
- 移植版现状:
  ```python
  def _reload(self) -> None:
      ...
      self.config = self._resolve_config(self._config)
      if hasattr(self.plugin, "ctx"):
          self.plugin.ctx = self.ctx      # 复用同一实例，仅改 ctx/config
      ...
      res = self.plugin.apply(self.ctx)
  ```
- 修复方案: `_reload` 时按 `runtime.callback`（类/工厂）重新构造实例并存到 fiber 上（依赖 D1 的改造）；仅对象插件（用户自带实例）按 TS 语义原样复用。否则插件内部状态跨 reload 泄漏（TS 语义是重启即重置）。

### D3 [MUST-FIX] 子 fiber 的生命周期未通过“父 fiber 的 effect”与父绑定
- 位置: py:registry.py:321-338 vs ts:fiber.ts:265-297
- 原版行为:
  ```ts
  // Fiber 构造器内：把“加入 runtime.fibers + 卸载时完整 dispose 自己”注册为父 fiber 的 effect
  this.dispose = parent.fiber.effect(() => {
    const remove = runtime.fibers.push(this)
    return async () => { this.uid = null; emitPluginDisposed(...); remove(); ... }
  }, 'ctx.plugin()')
  ```
- 移植版现状:
  ```python
  fiber = Fiber(self.ctx, plugin_inst, ...)
  ...
  runtime.add_fiber(fiber)          # 直接加入 runtime，无父 fiber effect
  for name in list(fiber.inject.keys()):
      fiber._checkImpl(name)
  fiber._refresh()
  ```
- 修复方案: 在 `registry.plugin()`（或 Fiber 构造）里调用 `self.ctx.fiber.effect(...)` 注册“父卸载 → 子 dispose() → 从 runtime.fibers 移除”的可逆 effect。否则父插件因依赖变化重启（`_unload`→`_reload`）时，TS 会先完整 dispose 旧子 fiber 再由新一次 apply 重建；Python 旧子 fiber 仍然 ACTIVE，造成重复挂载/僵尸插件。同时补齐 TS 的“emit 失败 → dispose 子 fiber 再抛出”（ts:fiber.ts:303-308；Python 仅 `_runtimes.pop`，见 D8）。

### D4 [MUST-FIX] `@inject` 类装饰器原地改写继承来的 inject dict，污染基类与兄弟子类
- 位置: py:registry.py:77-89 vs ts:registry.ts:40-44
- 原版行为:
  ```ts
  if (!Object.hasOwn(value, 'inject')) {          // 只看 own property
    defineProperty(value, 'inject', Object.create(Object.getPrototypeOf(value).inject ?? null))
    defineProperty(value.inject, symbols.checkProto, true)
  }
  value.inject[name] = config                     // 写在子类自己的 shadow 对象上
  ```
- 移植版现状:
  ```python
  if not hasattr(target, "inject") or not isinstance(getattr(target, "inject"), dict):
      ...
      target.inject = cur_inject
  Inject.resolve(name_or_deps, target.inject)     # 若 inject 继承自基类，target.inject 就是基类的同一个 dict
  ```
- 修复方案: 判定改为 own attribute 检查（`"inject" in target.__dict__`）；若非 own attribute，先执行 `target.inject = dict(getattr(target, "inject", {}))` 浅拷贝断开对基类引用的共享，再写入当前类的依赖项（等价 TS 的 prototype shadow 隔离）；同时支持 `List[str]`, `Tuple[str, ...]`, `Dict[str, Any]` 等多种输入形状的规范化解析。

### D5 [MUST-FIX] inject 声明携带的 intercept config 从未写入 fiber ctx 的 intercept 表
- 位置: py:fiber.py:130（仅 `parent_ctx.extend({"fiber": self})`） vs ts:fiber.ts:238-245
- 原版行为:
  ```ts
  const injectEntries = Object.entries(this.inject)
  if (injectEntries.length) {
    this.ctx[Context.intercept] = Object.create(parent[Context.intercept])
    for (const [name, config] of injectEntries) {
      if (isNullable(config)) continue
      this.ctx[Context.intercept][name] = config      // @Inject('llm', {...}) 的 config 进入 intercept 表
    }
  }
  ```
- 移植版现状: `Fiber.__init__` 只做 `self.ctx = parent_ctx.extend({"fiber": self})`；`inject` 字典里的非空 config 仅被 `registry.plugin` 当作依赖元数据，`Service.resolve_intercept_config` 读 `_intercept_map` 时永远拿不到它。
- 修复方案: `Fiber.__init__`（runtime 分支）在 extend 后，把 `self.inject` 中值非 None 的条目写入 `self.ctx._intercept_map = dict(parent._intercept_map)` 的副本；与 D6 的 required 语义协调。

### D6 [MUST-FIX] inject 对象值被强行附加 `required: True`，污染传给服务的 intercept config
- 位置: py:registry.py:44-55 vs ts:registry.ts:79-86
- 原版行为:
  ```ts
  for (const name of Object.keys(inject)) {
    result[name] = inject[name] ?? null        // 值就是 intercept config，原样透传（含 null 归一）
  }
  ```
- 移植版现状:
  ```python
  elif isinstance(v, dict):
      cfg = dict(v)
      cfg.setdefault("required", True)        # {'intercept': True} → {'intercept': True, 'required': True}
      result[k_str] = cfg
  ```
- 修复方案: Python 的可选依赖扩展（`?` → `{"required": False}`）保留，但不要把 `required` 注入用户 config：要么在 `Fiber._refresh` 之外单独存 required 集合，要么在把 config 交给 `Service.resolve_intercept_config`/`internal/config` 前剥离 `required` 键。否则服务读到的 intercept config 多出 `required: True` 键（与 TS 契约不符）。

### D7 [MUST-FIX] `assert_active` 比 TS 严格：FAILED/UNLOADING fiber 上禁止再 plugin()
- 位置: py:fiber.py:161-165（被 registry.py:234 调用） vs ts:fiber.ts:351-354
- 原版行为:
  ```ts
  assertActive() {
    if (this.uid !== null) return           // 只要未 dispose（uid 未清）就放行，FAILED 也能继续挂插件
    throw new CordisError('INACTIVE_EFFECT')
  }
  ```
- 移植版现状:
  ```python
  if self.uid is None or self.state in (FiberState.DISPOSED, FiberState.UNLOADING, FiberState.FAILED):
      ...raise CordisError("INACTIVE_EFFECT", ...)
  ```
- 修复方案: 收敛为 TS 语义：仅 `uid is None` 抛错；如需保留 Python 侧严格性，应作为可配置项并默认关闭，否则“启动失败的插件 fiber 上再挂插件”会从 TS 的“允许”变成 Python 的抛错。

### D8 [ADAPT] resolve/实例化的宽松回退与错误形态
- 位置: py:registry.py:165-175, 224-232, 246-271 vs ts:registry.ts:222-228, 319
- 原版行为:
  ```ts
  resolve(plugin) { try { if (typeof plugin === 'function') return plugin; if (isApplicable(plugin)) return plugin.apply } catch {} }
  if (!callback) throw new Error('invalid plugin, expect function or object with an "apply" method, received ' + typeof plugin)
  ```
- 移植版现状: resolve 额外接受 Plugin 实例/类；构造签名依次尝试 `(ctx, config) → (ctx) → (config) → ()`（Service/Plugin/普通类三条链），失败类型 ValueError、文案不同。
- 修复方案: 属兼容性放宽，保留；但 D1 落地后应保证首选签名 `(ctx, config)` 与 TS 一致，回退仅在 TypeError 时启用且不影响 config 传递（当前 `(ctx)`/`()` 回退会静默丢 config，需在文档标注或改为显式 capability 探测）。

### D9 [ADAPT] runtime 记录形状与命名派生差异
- 位置: py:registry.py:120-139, 236-240 vs ts:registry.ts:136-146, 322-328
- 原版行为:
  ```ts
  let name = plugin.name
  if (name === 'apply') name = undefined          // 对象插件 {apply} 的 name 视为匿名
  runtime = { name, callback, fibers: new DisposableList(), Config: plugin.Config }
  ```
- 移植版现状: `PluginRuntime`（callback/name/fibers）；`name = getattr(plugin,'name',None) or getattr(plugin,'id',None)`，无 `=== 'apply'` 跳过；`Config` 不存 runtime（`resolve_config` 直接读 `plugin.schema/Config`，行为等价）。
- 修复方案: 补 `name == "apply"` 的跳过；`Fiber.name`（py:fiber.py:139-149）与 TS 的“沿祖先 fiber 找最近的具名 runtime，否则 'root'”（ts:fiber.ts:336-343）不一致——匿名插件 fiber 在 TS 继承祖先名，Python 回落到类名/'root'，影响 logger 名与诊断，建议一并对齐。

### D10 [ADAPT] internal/plugin 派发时机与 caller ctx
- 位置: py:registry.py:322-328 vs ts:fiber.ts:299-319
- 原版行为:
  ```ts
  this.context.emit('internal/plugin', this)      // 用 fiber 自己的 ctx；此时 runtime.fibers 已含本 fiber（effect 已执行）
  ```
- 移植版现状: `self.ctx.emit("internal/plugin", fiber)`（root ctx，caller_ctx=root），且派发时 fiber 尚未 `runtime.add_fiber`，监听器内查 `registry.list_fibers()` 看不到它。
- 修复方案: 调整顺序为先 `runtime.add_fiber(fiber)` 再 emit，并尽量以 `fiber.ctx` 作为派发 ctx（caller_ctx 语义对齐）；emit 抛错时按 D3 补 dispose 再抛。

### D11 [ADAPT] Python 侧新增 API：update_dependencies / unload_plugin / get_fiber / list_fibers
- 位置: py:registry.py:181-185, 208-215, 355-371, 373-387 vs ts:（无对应物；TS 依赖刷新内嵌于 reflect.notify，ts:reflect.ts:314-336）
- 原版行为: TS 无独立 pending 集合（pending fiber 就在 runtime.fibers 里），也没有按 id 卸载的 API。
- 移植版现状: `_pending_fibers` 集合 + `update_dependencies()`（与 `reflect.notify` 功能重叠）+ `unload_plugin(id)`（卸单个 fiber，空了才删 runtime）+ `list_fibers/get_fiber`。
- 修复方案: 保留（harness/cordis-manager 工具依赖）；建议 `update_dependencies` 与 `reflect.notify` 收敛为单一路径以防重复刷新语义漂移。`unload_plugin` 与 TS `delete`（卸全部 fiber）语义不同，属命名不同的新 API，不算对 delete 的发散。

### D12 [SKIP] delete() 的 dispose 触发方式差异（fire-and-forget task vs 未 await 的 promise）
- 位置: py:registry.py:191-206 vs ts:registry.ts:258-267
- 原版行为: `for (const fiber of runtime.fibers) { fiber.dispose() }` —— promise 不等待。
- 移植版现状: `loop.create_task(fiber.dispose())`（无 running loop 时 `asyncio.run`）。
- 修复方案: 两侧都是“触发不等待”，等价；TS 的 dispose promise 内部自 await，Python task 亦然。跳过。

## 测试缺口

### T1 构造期注册的 Service 应随插件 fiber 卸载而注销（TS: impl.fiber = 插件 fiber）
- 建议测试名: `test_service_provided_by_class_plugin_disposed_on_plugin_unload`
- 要点: `ctx.plugin(MyServiceClass)` 后 `ctx.get("svc")` 可用；`await fiber.dispose()`（或 unload_plugin）后 `ctx.get("svc")` 为 None、`reflect.store` 无残留。当前 impl.fiber=root fiber，服务在插件卸载后仍存活。

### T2 reload 后插件实例是全新对象（状态不跨重启保留）
- 建议测试名: `test_class_plugin_instance_recreated_on_dependency_restart`
- 要点: 依赖服务卸载再恢复触发父 fiber `_unload→_reload`，断言 `fiber.plugin is not old_instance` 且实例属性（如计数器）被重置；对象插件实例则保持同一引用。

### T3 父插件重启时子插件被完整 dispose 再重建
- 建议测试名: `test_child_plugin_disposed_when_parent_fiber_restarts`
- 要点: 父 apply 内 `ctx.plugin(Child)`；让父的依赖失效→恢复，断言 Child 的 teardown/dispose 跑过且 `registry.get(Child)` 的 fibers 数量回落再增长（当前旧子 fiber 永远 ACTIVE）。

### T4 子类 @inject 不改动基类 inject 表
- 建议测试名: `test_inject_decorator_does_not_mutate_base_class_inject`
- 要点: `class Base(Plugin): inject=["a"]`；`@inject("b") class Child(Base)` 后 `Base.inject` 仍为 `["a"]`（当前被就地加入 "b"），`Child.inject` 含 a+b。

### T5 inject 声明中的 intercept config 能被服务读到
- 建议测试名: `test_inject_intercept_config_reaches_service_resolve_config`
- 要点: `@inject("db", {"pool": 2})` 的插件里，db 服务的 `resolve_intercept_config()` 应包含 `{"pool": 2}`（当前丢失；修复 D5/D6 后同时验证不含多余 `required` 键）。

### T6 对象插件 name === 'apply' 时 runtime 匿名
- 建议测试名: `test_object_plugin_named_apply_is_anonymous`
- 要点: `{"apply": fn, "name": "apply"}` 的 runtime.name 为 None，fiber.name 沿祖先解析（配合 D9 的 Fiber.name 对齐）。

### T7 FAILED fiber 上仍可挂插件（TS assertActive 仅看 uid）
- 建议测试名: `test_plugin_can_load_on_failed_fiber_like_ts`
- 要点: 构造一个启动失败的 fiber（state=FAILED、uid 未清），其 apply/事件里再 `ctx.plugin(X)` 不抛 INACTIVE_EFFECT（当前抛）。

### T8 internal/plugin 派发时 registry 已能看到该 fiber
- 建议测试名: `test_internal_plugin_listener_sees_fiber_in_registry`
- 要点: `ctx.on("internal/plugin", ...)` 内 `ctx.registry.list_fibers()` 包含正在派发的 fiber（当前因 add_fiber 晚于 emit 而看不到）。
