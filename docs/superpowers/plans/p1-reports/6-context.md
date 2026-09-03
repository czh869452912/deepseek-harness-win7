# dsh/cordis/context.py ↔ reference/vendor/cordis/src/context.ts

对比基线：TS 为实现权威（snapshot dsh-v0.1.2-alpha.1）。JS Proxy 属性访问 → Python 显式 `get/set/__getattr__` 方法属于预期 ADAPT，仅在语义/顺序/错误处理不同时报 MUST-FIX。

## 差异清单

### D1 [MUST-FIX] ctx.effect() 无 fiber 回退分支把 setup 当 disposer（与 fiber 路径语义相反）
- 位置: py:context.py:159-194 vs ts:context.ts:71-84（ctx.effect 来自 reflect.mixin('fiber', ['runtime', 'effect'])，实际实现为 fiber.effect）
- 原版行为:
  ```ts
  // fiber.ts effect(execute, label)：execute 一律立即执行，返回值才是 disposer
  task = this._execute(runner)   // runner.execute.call(this) 必然被调用
  ```
- 移植版现状:
  ```python
  if self.fiber:
      return self.fiber.effect(setup_or_disposer, label=label)   # setup：立即执行
  if not callable(setup_or_disposer):
      return lambda: None
  self._effects.append(setup_or_disposer)   # 回退分支：登记为 teardown 时才调用
  ...
  res = setup_or_disposer()                  # cancel_effect 时才执行
  ```
- 修复方案: 无 fiber 的回退分支应与 `Fiber.effect` 语义一致——立即执行 callable 并把返回的可调用对象登记为 disposer（`Fiber.effect` 内部已有按函数名判断 disposer 的启发式，见 fiber.py:319-328，该启发式本身在 registry/reflect 报告中另列）。当前回退分支仅在 `self.fiber` 为假值时可达（Context 构造时必然创建 root fiber），属死代码，但一旦触达语义相反；建议直接删除回退分支或改为 `return self.fiber.effect(...)` 的同构实现。

### D2 [MUST-FIX] `__getattr__` 的 RESERVED_ATTRS 把同名的已提供服务挡在属性访问之外
- 位置: py:context.py:381-388 vs ts:reflect.ts:136-142（handler.get 无此类黑名单，只有 `isSpecialProperty`：symbol / 'prototype' / 'then' / 纯数字串 / `_` 前缀）
- 原版行为:
  ```ts
  get: (target, prop, ctx) => {
    if (isSpecialProperty(prop)) return Reflect.get(target, prop, ctx)
    if (Reflect.has(target, prop)) return getTraceable(ctx, Reflect.get(target, prop, ctx))
    // 之后才是 accessor / fiber 链解析，'session'/'agent'/'status' 等普通名字都能解析到已提供的服务
  ```
- 移植版现状:
  ```python
  RESERVED_ATTRS = ("registry", "reflect", "fiber", "root", "events", "props", "store", "logger", "timer",
      "filter", "validate", "status", "teardown", "symbols", "base_url", "baseUrl",
      "strict_inject", "session", "agent", "is_shadow", "_shadow", "_shadow_fiber")
  if ... or name in RESERVED_ATTRS:
      raise AttributeError(...)
  ```
- 修复方案: 重构 `__getattr__` 解析流水线并精简保留属性：① 从 `RESERVED_ATTRS` 中彻底剔除业务服务名（`session`, `agent`, `status`, `filter` 等），仅保留不可通过动态服务覆盖的真正内部核心基础设施字段（如 `registry`, `reflect`, `fiber`, `root`, `events`, `logger`, `timer`, `_services`, `_parent`）；② 查找顺序调整为：原生属性/类属性优先 -> accessor 属性（`reflect.props`）-> 动态服务解析（`_resolve_strict` / fiber store）-> 仅当上述全未命中时对保留内部字段抛 `AttributeError` 兜底；③ 针对 `filter` 钩子，统一使用内部私有属性 `_filter_hook` 或通过 `reflect` 隔离查找，避免服务同名属性冲突。

### D3 [MUST-FIX] `has()` 语义是“解析值非 None”，TS `in` 是“属性已声明”
- 位置: py:context.py:153-157 vs ts:reflect.ts:199-205（handler.has）
- 原版行为:
  ```ts
  has: (target, prop) => {
    if (isSpecialProperty(prop)) return Reflect.has(target, prop)
    if (Reflect.has(target, prop)) return true
    return !!target.reflect.props[prop]   // 只要声明过（service 或 accessor）即为 true，与值无关
  }
  ```
- 移植版现状:
  ```python
  def has(self, name: str) -> bool:
      return self.get(name, strict=False) is not None
  ```
- 修复方案: `has()` 改为“声明存在性”判断：`name in self._services or name in self.reflect.props or (parent 链上声明)`；至少要覆盖“提供值为 None 的服务”与“已声明 accessor 但 get 返回 None”两类场景为 True。注意 registry.py:104 的方法级 `@inject` 包装器用 `ctx.has(dep)` 做调用前检查，语义会随之变化，需一并回归。

### D4 [ADAPT] Proxy handler → 显式 get/set/`__getattr__` 三层解析
- 位置: py:context.py:141-157, 381-437 vs ts:reflect.ts:135-206
- 原版行为: proxy `get` 顺序：special → own props → accessor → (runtime 为空时 `reflect.get(prop,false)`) → waterfall internal/get 走 fiber 链；proxy `set` 顺序：special → accessor → waterfall internal/set → reflect.set，未声明且 runtime 为空时允许写 own property。
- 移植版现状: own-props 由 Python 原生属性查找承担（先于 `__getattr__`）；accessor 检查在 `__getattr__`/`reflect.get` 中先行；strict fiber 链游走实现在 `__getattr__` 的 `_resolve_strict`（py:399-425），与 ts:reflect.ts:153-167 的 while 循环逐分支对应（store 命中→返回；`name in fiber.inject`→"cannot get required service ... in inactive context"；父级 isolate key 不一致→原错误；runtime 空→退出抛原错误），错误文案一致（引号风格差异忽略）。
- 修复方案: 无需修复；保持 `ctx.get()`（宽松、返回 default）与 `ctx.<attr>`（严格、抛错）双通道与 TS 对应关系即可。差异点：TS 的 set trap 允许 runtime 为空的 ctx 写 own property（reflect.ts:181），Python `ctx.set()` 一律抛 "cannot set property ... without provide"（Python 直接 `ctx.attr = v` 原生 setattr 等价于 TS 行为）。

### D5 [ADAPT] isolate/intercept 表用“拷贝”而非“原型链”，isolate 支持超集入参
- 位置: py:context.py:288-325 vs ts:context.ts:99-145
- 原版行为:
  ```ts
  isolate(name, label?) {
    const shadow = Object.create(this[symbols.isolate])
    shadow[name] = label ?? Symbol(name)
    return this.extend({ [symbols.isolate]: shadow })
  }
  ```
- 移植版现状: `extend()` 中 `child._isolated_keys = dict(self._isolated_keys)`、`child._intercept_map = dict(self._intercept_map)`；`isolate()` 支持 `str | list | dict` 且 `label or object()`。
- 修复方案: 等价实现。TS 中 isolate 表从不被原地修改（每次 isolate 生成新 shadow），拷贝与原型链在查找结果上等价；同 label 合并作用域的语义两侧一致（Python 传同一 label 对象即合并）。superset 入参（list/dict）是 Python 扩展，不算发散。唯一理论差异：TS 里 `provide` 会向 root isolate 表回填 `Symbol(name)`（reflect.ts:286），Python 用“缺省回落到名字本身”替代——键策略自洽，ADAPT。

### D6 [ADAPT] `Context.is` 品牌判定：全局 symbol 品牌 → 类属性品牌 + 鸭子类型
- 位置: py:context.py:32-51 vs ts:context.ts:61-68
- 原版行为:
  ```ts
  static is(value: any): value is Context { return !!value?.[Context.is as any] }
  static { Context.prototype[Context.is as any] = true }
  ```
- 移植版现状: `__cordis_context_brand__ == "cordis.v1.context"` 命中即真；否则 `isinstance(value, Context)` 或鸭子类型（同时具备 `registry`/`reflect`/`extend`）。
- 修复方案: 跨模块重载场景 Python 用类属性品牌等价实现；鸭子类型分支比 TS 宽（拥有三个属性的非 Context 对象会误判为 True），可收紧为仅品牌 + isinstance，但现网无可见影响，保持现状可接受。

### D7 [ADAPT] strict_inject 可配置开关（Python 扩展，TS 恒严格）
- 位置: py:context.py:68-74 vs ts:（无对应物）
- 原版行为: TS 无 strict 开关；proxy get 在 `ctx.fiber.runtime` 非空时对未解析属性无条件抛错（reflect.ts:152-167）。
- 移植版现状: `DSH_STRICT_INJECT` 环境变量，默认开启（"1"），子 ctx 继承父值。
- 修复方案: 属移植期增能（Win7/harness 渐进迁移用），默认值与 TS 行为一致（严格）。保留，但在文档中标注为非 1:1 扩展。

### D8 [ADAPT] Python 侧新增 API（无 TS 对应物）：set_service/get_service/list_plugins/unload_plugin/teardown/timer 系列
- 位置: py:context.py:106-139, 259-286, 327-349, 351-379 vs ts:（无对应物）
- 原版行为: TS 只暴露 `ctx.provide`（reflect.ts:277）与 proxy 读写；子 ctx 生命周期由 fiber 驱动，无独立 `teardown()`。
- 移植版现状: `set_service`（写 root `_services` + setattr + `reflect.provide(allow_replace=True)`）、`get_service`（沿 `_parent` 走 `_services`，尊重 `_isolated_keys`）、`list_plugins`、`unload_plugin`、`teardown`（root fiber dispose + `_effects` 回退清理）、`timeout/interval/throttle/debounce/setTimeout/setInterval`（TimerService）。
- 修复方案: 属 harness 必需的 Python 化入口，保留。但两处内部语义需对齐（在 7-registry.md / 9-reflect.md 详述）：`set_service` 的 `allow_replace=True` 绕过 TS 的 provide 冲突检测；`teardown()` 对非 root ctx 只清 `_effects`（该列表仅 D1 回退分支会写入），与 fiber 驱动的卸载模型不一致，建议 `teardown()` 统一走 `self.fiber.dispose()`（root）或显式 no-op 说明。

### D9 [ADAPT] 事件派发的 thisArg → caller_ctx 关键字约定
- 位置: py:context.py:212-242 vs ts:events.ts:165-175（dispatch 的 `thisArg` 过滤与绑定）
- 原版行为: TS `ctx.emit(name, ...)` 经 mixin 绑定后 `args[0]` 为事件名 → `thisArg=null` 不过滤；`reflect.notify` 用合成 ctx（带 `symbols.filter`）作 thisArg 实现按作用域过滤。
- 移植版现状: `Context.emit` 等统一注入 `kwargs["caller_ctx"]=self`，events.py 据此绑定 `caller_ctx` 形参；过滤依赖 `getattr(actual_ctx, "filter", None)`（Python 从不设置该属性 → 实际不过滤，见 9-reflect.md D4）。
- 修复方案: 约定层面等价（Python 无 `this`），保留；`internal/service` 的作用域过滤缺失在 reflect 报告中必须修复。

### D10 [SKIP] 诊断性能力：enhanceError 栈改写、`Symbol.for('nodejs.util.inspect.custom')`、`Context.is[Symbol.toPrimitive]`
- 位置: py:（无） vs ts:reflect.ts:73-78, context.ts:66, 86-88
- 原版行为: TS 改写 error.stack 前两行、自定义 inspect 输出 `Context <fiber.name>`、把 `Context.is` 强制转成全局 symbol 键。
- 移植版现状: 无对应实现（Python traceback 机制不同）。
- 修复方案: 平台不可行/纯诊断装饰，跳过。

## 测试缺口

### T1 相同 label 的两次 isolate() 应合并作用域（TS `label ?? Symbol(name)` 的“join”语义）
- 建议测试名: `test_isolate_same_label_joins_scope`
- 要点: `a = root.isolate("svc", label=L)`、`b = root.isolate("svc", label=L)`，在 a 下 provide 后 b 可见；与 `root.isolate("svc")`（新随机 label）互不可见。

### T2 RESERVED_ATTRS 不应挡住已提供的同名服务（尤其 session/agent/status/filter）
- 建议测试名: `test_child_context_attribute_access_for_reserved_service_names`
- 要点: root `set_service("status", obj)` 后，子 ctx `child.status` 应解析到 obj（当前抛 AttributeError）；同时验证 `ctx.get("status")` 不受影响（现状可通过）。

### T3 `has()` 对“已声明但值为 None 的服务”应返回 True（对齐 TS `in`）
- 建议测试名: `test_has_true_for_declared_none_valued_service`
- 要点: `ctx.provide("maybe", None)` 后 `ctx.has("maybe")` 为 True（当前 False）；accessor 只有 get 且返回 None 时同理。

### T4 internal/get waterfall 监听器的参数形状与短路能力
- 建议测试名: `test_internal_get_waterfall_listener_shape_and_short_circuit`
- 要点: 注册 `ctx.on("internal/get", (ctx, name, error, next))` 能在 `ctx.<attr>` 严格解析时被调用并可用返回值替换解析结果（对齐 ts:reflect.ts:153 的 `ctx.events.waterfall('internal/get', ctx, prop, error, () => {...})`）；当前 `waterfall_sync` 走 reducer/Koa 双风格猜测，需固化“四参 + next”契约。

### T5 accessor get 的 receiver 传递
- 建议测试名: `test_accessor_get_receives_receiver`
- 要点: `__getattr__` 访问 accessor 时 `def_prop.get(receiver, err)` 的第一参应是 receiver（traceable 包装后的 ctx），`reflect.get` 路径传的是 ctx 本体——两路径应行为一致且可区分 receiver。

### T6 ctx.effect(setup) 对“名字像 disposer 的 setup 函数”的执行语义
- 建议测试名: `test_ctx_effect_executes_setup_even_if_name_looks_like_disposer`
- 要点: 传入 `__name__` 含 "cleanup"/"disposer" 的 setup 函数时，TS 语义是立即执行并收集其返回的 disposer；Python fiber.effect 会跳过执行（fiber.py:319-328 启发式）。该行为属 fiber.py，但暴露面是 `ctx.effect`，需在此固化预期（按 TS：一律执行）。
