# dsh/cordis/reflect.py ↔ reference/vendor/cordis/src/reflect.ts

对比基线：TS 为实现权威。注意 TS 的属性解析主体是 `ReflectService.handler`（Proxy traps，ts:reflect.ts:135-206），Python 拆分为 `reflect.get/set`（宽松解析）+ `Context.__getattr__` 的 strict 链游走（context.py:399-425）——这一拆分本身属预期 ADAPT。TS 里 `ctx.reflect` 经 traceable 代理访问，方法内的 `this.ctx` 解析为调用方 ctx（ts:utils.ts:165-176）；Python 用显式 `ctx` 参数等价实现。

## 差异清单

### D1 [MUST-FIX] `set()`：root ctx（uid 0/None）可跨 fiber 改写他人服务；TS 一律拒绝
- 位置: py:reflect.py:150-152 vs ts:reflect.ts:260-262
- 原版行为:
  ```ts
  if (impl.fiber !== this.ctx.fiber) {
    throw new Error(`cannot set property "${name}" in multiple fibers`)
  }
  ```
- 移植版现状:
  ```python
  fiber = getattr(ctx, "fiber", None)
  if fiber is not None and impl.fiber is not None and impl.fiber is not fiber and getattr(fiber, "uid", None) not in (0, None):
      raise RuntimeError(f"cannot set property '{name}' in multiple fibers")
  ```
- 修复方案: 去掉 `uid not in (0, None)` 豁免——root fiber 上对插件 fiber 提供的服务执行 `ctx.set(...)` 也必须抛错。现有测试 tests/test_cordis_1to1_final_completeness.py:227 只覆盖“插件 fiber 之间”的跨 fiber 拒绝，root 豁免路径无测试。

### D2 [MUST-FIX] `provide()` 冲突检测弱于 TS：对 root fiber 提供的服务静默替换，且 `allow_replace` 完全绕过
- 位置: py:reflect.py:200-209 vs ts:reflect.ts:289-291
- 原版行为:
  ```ts
  if (this.store[key]) {
    throw new Error(`service "${name}" has been registered at <${this.store[key].fiber.name}>`)
  }                                    // 无条件：只要同 key 已有实现就抛
  ```
- 移植版现状:
  ```python
  if not allow_replace and key in self.store and self.store[key].fiber is not None and self.store[key].fiber is not fiber:
      if (prev_fiber.state not in (DISPOSED, FAILED)
          and getattr(fiber, "runtime", None) is not None
          and getattr(prev_fiber, "runtime", None) is not None):   # root fiber runtime=None → 不抛
          raise RuntimeError(f"service '{name}' has been registered at <{prev_name}>")
  ```
- 修复方案: ① 去掉 `prev_fiber.runtime is not None` 条件——Context 构造时 events/logger/reflect/registry 等均由 root fiber 提供，插件 fiber 再提供同名服务时 TS 必抛，Python 当前静默替换 root 服务（连带 `set_service(allow_replace=True)` 的调用方一并收敛，见 8-service.md D1）；② DISPOSED/FAILED 前任放行是为规避异步 teardown 竞态的 Python 化处理，可保留但要求：替换时先同步移除旧 impl 再登记新 impl，并记录一条 warn 日志；③ `allow_replace` 仅保留给 `set_service` 这一 Python 扩展入口并默认 False。

### D3 [MUST-FIX] `provide()` 在 fiber LOADING 阶段即 notify；TS 仅 ACTIVE
- 位置: py:reflect.py:222-224 vs ts:reflect.ts:294-296
- 原版行为:
  ```ts
  if (this.ctx.fiber.state === FiberState.ACTIVE) {
    this.notify([name])
  }          // LOADING（apply 执行中）不通知；等 _updateState 进入 ACTIVE 时由状态迁移统一 notify（fiber.ts:588-594）
  ```
- 移植版现状:
  ```python
  if fiber is None or fiber.state in (FiberState.ACTIVE, FiberState.LOADING):
      self.notify([name])
  ```
- 修复方案: 收敛为 `state == ACTIVE`（或 fiber 为 root）。LOADING 期通知会让依赖方在提供方尚未 ACTIVE 时提前 `_refresh`（TS 依赖 `impl.fiber.state !== ACTIVE → _getImpl 返回 undefined` 挡住，Python `_get_impl` 对 plugin 为 None 的 fiber 有豁免，叠加后可能提前激活依赖方）。注意 `set_state` 里的迁移期 notify（py:fiber.py:443-450）已覆盖 ACTIVE 化时机，不会丢通知。

### D4 [MUST-FIX] `notify()` 的 `internal/service` 派发缺失按作用域过滤的合成上下文
- 位置: py:reflect.py:275-280 vs ts:reflect.ts:330-334
- 原版行为:
  ```ts
  for (const name of names) {
    const self: Context = Object.create(this.ctx)
    self[symbols.filter] = (target: Context) => filter(target, name)   // 只有同 isolate 作用域的监听器收到
    this.ctx.events.emit(self, 'internal/service', name, this._getImpl(name, false)?.value)
  }
  ```
- 移植版现状:
  ```python
  for name in names:
      impl = self.store.get(name)                     # 不按 isolate key 查（隔离服务查不到，回落 getattr）
      val = impl.value if impl else getattr(self.ctx, name, None)
      self.ctx.emit("internal/service", self.ctx, name, val)   # caller_ctx 无 filter 属性 → 全量广播
  ```
- 修复方案: 构造合成子 ctx（`child = self.ctx.extend()`，并挂一个可被 `EventBus._dispatch_hooks` 消费的过滤属性，如 `child.filter = lambda hook_ctx: <isolate label 比较>`），用 `child.emit(...)` 派发；事件参数与 TS 对齐为 `(name, value)` 或明确固化 Python 的 `(ctx, name, value)` 三参约定并同步到文档。同时 value 的取值改为 `_get_impl(self.ctx, name, strict=False)` 口径。

### D5 [ADAPT] `provide()` 的 teardown 为同步：不等待依赖方 settle，也不清理提供方 fiber.store 快照
- 位置: py:reflect.py:226-238 vs ts:reflect.ts:297-303
- 原版行为:
  ```ts
  return async () => {
    delete this.store[key]
    const fibers = this.notify([name])
    await Promise.allSettled(fibers.map(fiber => fiber.await()))   // 依赖方卸载/重启完成才算 teardown 完成
    delete this.ctx.fiber.store![name]                             // 最后清自己 fiber 的快照
  }
  ```
- 移植版现状:
  ```python
  def teardown() -> None:
      if key in self.store and self.store[key] == impl: del self.store[key]
      if hasattr(target_store, "_services") and name in target_store._services:
          del target_store._services[name] ...
      self.notify([name])          # 同步触发；依赖方的异步 reload 不等待
  ```
- 修复方案: 让 teardown 返回协程（fiber.effect 已支持可等待 disposer，py:fiber.py:266-313）：删 store → notify 收集受影响 fibers → `await asyncio.gather(*(f.await_settled() for f in fibers), return_exceptions=True)` → 最后 `fiber.store.pop(name)`。Python 的 `_services`/`delattr` 镜像清理是 attr 直读路径所需，保留（ADAPT）。

### D6 [ADAPT] store 键策略：名字回落 vs root 自动 Symbol 标签
- 位置: py:reflect.py:196-197, 213 vs ts:reflect.ts:286-292
- 原版行为:
  ```ts
  this.ctx.root[symbols.isolate][name] ??= Symbol(name)   // 每个被提供的服务在 root isolate 表里都有标签
  const key = this.ctx[symbols.isolate][name]             // 隔离作用域用 shadow 标签
  this.store[key] = impl
  ```
- 移植版现状: `key = isolated_map.get(name, name)` —— 未隔离时直接用服务名作键，不回填 root 表。
- 修复方案: 键策略自洽（查找侧 `_get_impl`/`set` 用同一推导），行为等价，保留。副作用：Python `reflect.store` 的键是字符串名，`set_state` 遍历（py:fiber.py:445-449）与 TS 语义一致。

### D7 [ADAPT] `get()`：Python 是超集宽松解析器；严格解析在 `Context.__getattr__` 内实现
- 位置: py:reflect.py:70-115 vs ts:reflect.ts:233-243（store-only）与 ts:reflect.ts:136-171（proxy handler 严格路径）
- 原版行为: TS `reflect.get(name, strict)` 只查 store（`getTraceable(this.ctx, this._getImpl(name, strict)?.value)`）；proxy get 的完整顺序是 special → own props → accessor → runtime 为空时宽松 store → waterfall internal/get 走 fiber 链。
- 移植版现状: `reflect.get` 依次查 accessor → `_get_impl` → `ctx._services` → `get_service` 父链 → default，绝不抛错；`ctx.<attr>` 的严格抛错由 `__getattr__`（context.py:399-425）承担，错误文案与 TS 一致（"cannot get property ... without inject" / "cannot get required service ... in inactive context"）。
- 修复方案: 结构性 ADAPT，保留。注意 TS `ctx.get(name)`（strict=true）对“impl 存在但 fiber 非 ACTIVE”返回 undefined，Python `_get_impl(strict=True)` 同语义（对 plugin 为 None 的 fiber 豁免，等价 root fiber 恒 ACTIVE，见 D8）。

### D8 [ADAPT] `_get_impl` 的 strict 检查带 plugin-None 豁免；isolate key 按传入 ctx 推导
- 位置: py:reflect.py:117-130 vs ts:reflect.ts:237-243
- 原版行为:
  ```ts
  _getImpl(name, strict = true) {
    const key = this.ctx[symbols.isolate][name]
    const impl = key && this.store[key]
    if (!impl) return
    if (strict && impl.fiber.state !== FiberState.ACTIVE) return   // root fiber 恒 ACTIVE，天然放行
  ```
- 移植版现状:
  ```python
  if strict and impl.fiber is not None and getattr(impl.fiber, "plugin", None) is not None:
      if impl.fiber.state != FiberState.ACTIVE: return None
  ```
- 修复方案: Python 用 `plugin is None` 近似“root fiber”（TS root fiber state=ACTIVE 故无条件检查也放行 root 服务）——结果等价，保留；若未来出现 runtime 非空但 plugin 为 None 的 fiber 会绕过 strict，建议改判 `impl.fiber.uid in (0, None)` 更贴近 TS。

### D9 [ADAPT] `set()` 的键推导与镜像写；runtime 为空 ctx 的 own-property 写入缺失
- 位置: py:reflect.py:143-160 vs ts:reflect.ts:173-197, 254-265
- 原版行为:
  ```ts
  const key = this.ctx[symbols.isolate][name]        // reflect.ctx 固定 root → 恒 root 作用域键（隔离子 ctx 也写外层键）
  ...
  impl.value = value; return true                    // 只改 impl.value，不写 own property
  // set trap：def 不存在且 !ctx.fiber.runtime → Reflect.set（root ctx 可写 own property）
  ```
- 移植版现状: `key = isolated_map.get(name, name)`（按传入 ctx，隔离子 ctx 写隔离键——与 TS 的 root 固定键不同，但更直观）；成功后镜像 `target._services[name] = value; setattr(target, name, value)`（attr 直读路径所需）；`ctx.set()` 对未提供名字一律抛错。
- 修复方案: 镜像写保留（ADAPT）；隔离键口径差异建议在文档标注（TS 行为疑为 quirk，Python 语义更合理，但两者不可同时成立——若追求 1:1 需改回 root 键）；未提供名字在 runtime 为空 ctx 上的 own-property 写入可补：`ctx.set` 捕获“无 impl 且 ctx.fiber.runtime 为空”时改为 setattr own property 返回 True。

### D10 [ADAPT] `mixin()`：N 个独立 accessor + 冗余 cleanup_all；方法绑定丢失 receiver 覆盖
- 位置: py:reflect.py:304-342 vs ts:reflect.ts:364-390
- 原版行为:
  ```ts
  return this.ctx.fiber.effect(function* () {
    for (const [key, value] of entries) {
      yield self.accessor(value, { get(receiver, error) { ... const mixin = receiver ? withProps(receiver, service) : service
        ... return value.bind(mixin ?? service) }, set(...) {...} })
    }
  }, `ctx.mixin(...)`)          // 单个 effect，子 accessor 进 children 元数据树；方法 this = receiver+service 覆盖层
  ```
- 移植版现状: 每个 mixin 项独立 `self.accessor(...)`（各自挂 fiber effect），另返回一个多余的 `cleanup_all`；`get_fn` 直接 `getattr(target_obj, s_key)`——方法绑定到服务自身，`receiver`（withProps 覆盖层）不参与绑定；`target_obj is None` 时返回 None（TS 经 proxy 取 `ctx[source]` 会抛错）。
- 修复方案: 功能等价，保留；建议 ① 删除未使用的 `cleanup_all` 返回值（或改为返回外层 effect disposer）；② get/set 回调内用 `with_props(receiver, service)` 合成绑定对象（utils.py:526 已有实现）对齐方法 `this` 语义；③ 目标服务缺失时与 TS 对齐抛错（至少 warn）。

### D11 [ADAPT] `bind()`：不 trace thisArg、无 construct 通道
- 位置: py:reflect.py:351-368 vs ts:reflect.ts:408-417
- 原版行为:
  ```ts
  apply: (target, thisArg, args) => Reflect.apply(target, this.trace(thisArg), args.map(arg => this.trace(arg)))
  construct: (target, args, newTarget) => Reflect.construct(target, args.map(...), newTarget)
  ```
- 移植版现状: `traced_wrapper` 仅 trace `*args/**kwargs`；`functools.wraps` 保留原函数绑定，`this`（self）不经 trace；类作 callback 时包装器调用不会走 `__call__` 以外的构造路径。
- 修复方案: wrapper 内若存在显式 self/receiver 参数（通过 descriptor 协议或首参为 ctx 样对象）先 `get_traceable(ctx, self_arg)`；补充对类的支持（返回一个 trace 构造参数的 `__call__` 触发 `cls(*traced)` 的包装）或明确文档化为仅函数。

### D12 [ADAPT] 保留字/特殊属性集合不同；accessor 错误类型 KeyError
- 位置: py:reflect.py:44-47, 80-81 vs ts:reflect.ts:80-91
- 原版行为:
  ```ts
  const RESERVED_WORDS = ['prototype', 'then']
  function isSpecialProperty(prop) { return typeof prop === 'symbol' || RESERVED_WORDS.includes(prop) || parseInt(prop).toString() === prop || prop.startsWith('_') }
  const error = new Error(`cannot get property "${prop}" without inject`)
  ```
- 移植版现状: `RESERVED_PROPERTIES` 含大量内部名（`_services`、`registry`、`reflect`、`fiber`、`root`、`logger`、`timer`…）+ `_` 前缀，但不含纯数字串；accessor get 的 err 载体是 `KeyError`。
- 修复方案: 属 Proxy 语义映射（own-props 在 Python 由原生查找承担，故额外保留名合理），保留；补两条小对齐：① 纯数字串名视为特殊属性（`name.isdigit()` 直通 getattr）；② accessor/解析错误的异常类型统一为 RuntimeError（KeyError 语义误导，捕获方按 Exception 兼容即可）。

### D13 [SKIP] enhanceError 栈改写与 `dispose[symbols.effect]` 元数据树（children 嵌套）
- 位置: py:（无对应） vs ts:reflect.ts:73-78, fiber.ts:444-453
- 原版行为: TS 重写错误栈前两行；effect 收集时把嵌套 effect 的 meta 挂到父 meta.children。
- 移植版现状: Python EffectMeta 恒为 `children=[]`（fiber.py:58-68），无栈改写。
- 修复方案: 纯诊断信息，Python traceback 机制不同，跳过；如后续需要诊断树，可在 `Fiber.effect` 执行期把新注册的 `_effect_metas` 条目挂入当前 meta.children。

## 测试缺口

### T1 root ctx 上 set 插件提供的服务必须抛 "in multiple fibers"
- 建议测试名: `test_set_from_root_ctx_across_fibers_raises`
- 要点: 插件 A provide "svc" 后，`root_ctx.set("svc", x)`（或 `root_ctx.reflect.set(root_ctx, "svc", x)`）应抛错；当前因 uid==0 豁免静默成功（tests/test_cordis_1to1_final_completeness.py:227 只覆盖插件 fiber 之间）。

### T2 插件提供与 root 已提供同名服务必须抛 "has been registered"
- 建议测试名: `test_plugin_provide_conflicting_with_root_provided_service_raises`
- 要点: Context 自带服务（如 logger/events 经 root fiber 提供）之外，先 `root_ctx.provide("base", v)`，再在插件 apply 内 `ctx.provide("base", v2)` 应抛错；当前 prev_fiber.runtime=None 豁免导致静默替换。

### T3 internal/service 监听器按 isolate 作用域过滤
- 建议测试名: `test_internal_service_listener_scope_filtering`
- 要点: 在 `root.isolate("svc")` 子作用域内 `ctx.on("internal/service", ...)`，root 作用域 provide/卸载 "svc" 不应触发该监听器；同作用域内应触发且 value 正确（当前全量广播，见 D4）。

### T4 provide 的 disposer 完成时依赖方已 settle（卸载顺序保证）
- 建议测试名: `test_provide_teardown_waits_for_dependent_fibers`
- 要点: 依赖方插件在依赖消失后其 teardown 先于提供方 disposer 返回完成（TS: `await Promise.allSettled(fibers.map(fiber => fiber.await()))`）；用事件顺序列表断言 teardown 返回点晚于依赖方 teardown 完成点。

### T5 `reflect.bind` 包装的调用会 trace this/self 与参数
- 建议测试名: `test_bind_traces_receiver_and_arguments`
- 要点: `bound = ctx.reflect.bind(fn)`；以对象方法或显式 receiver 调用时，receiver 与各实参均经 `get_traceable(ctx, ...)` 包装（当前仅 args/kwargs），可结合 tests/test_cordis_traceable_and_stack_1to1.py 的 TracedProxy 断言方式。

### T6 mixin 出来的方法调用可见 receiver 覆盖属性（withProps 语义）
- 建议测试名: `test_mixin_method_binds_with_receiver_props`
- 要点: 经 `ctx.mixin("events", ["on"])` 得到的 `ctx.on` 调用时，方法内 `this` 应能读到 receiver 上的属性（TS `value.bind(mixin ?? service)`）；至少固化当前“绑定到服务本体”的行为并标注差异。

### T7 纯数字串属性名走特殊属性直通（不入服务解析）
- 建议测试名: `test_numeric_string_property_bypasses_resolution`
- 要点: `ctx.get("0")`/`ctx[...]` 对名为 "0" 的属性按 TS isSpecialProperty 直通 getattr，不抛 inject 错误也不误建服务（当前 Python 未做数字串判定）。
