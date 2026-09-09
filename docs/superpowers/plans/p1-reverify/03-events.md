# G3-events 盲审报告

审计对象：`reference/vendor/cordis/src/events.ts`（352 行，设计基准）↔ `dsh/cordis/events.py`（506 行，被审移植）。
辅助证据（仅源码，未读 docs/）：`reference/vendor/cordis/src/utils.ts`、`src/context.ts`（grep 定位）、`src/reflect.ts`（grep 定位）；`dsh/cordis/fiber.py`、`dsh/cordis/utils.py`（grep 定位）。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态（1:1 / ADAPT / D#） |
|---|---|---|
| `isBailed` events.ts:13-15 | `is_bailed` events.py:12-17 | ADAPT（TS 三值 null/false/undefined → Python None/False 两值；`undefined` 在 Python 无对应，并入 None） |
| `Parameters`/`ReturnType`/`ThisType` 类型 events.ts:18-22 | — | ADAPT（纯类型层，运行时无对应物） |
| `DispatchMode` events.ts:32 | —（mode 以 str 字面量传入 `_dispatch_hooks`） | ADAPT（类型层；运行时 mode 字符串逐点核对见差异节） |
| `EventOptions` 接口 events.ts:112-117 | `on`/`once` 的 `prepend`/`global_listener`/`ctx` 关键字参数 events.py:120-127 | ADAPT（options 对象 → kwargs 惯用法；但引发 D7 payload 变形） |
| `Hook` 接口 events.ts:120-123 | `Hook` 类 events.py:28-34 | 1:1（字段 ctx/callback/global/prepend 等价） |
| `EventsService` 类 events.ts:131 | `EventBus` 类 events.py:57 | D19（类名不同） |
| `_hooks: Record<keyof any, Hook[]>` events.ts:132 | `_hooks: Dict[str, List[Hook]]` events.py:65 | D15（Python 仅 str 键） |
| 构造器 `defineProperty(this, symbols.tracker, …)` events.ts:135-138 | — | D14 |
| 构造器 `internal/listener` 内建 handler events.ts:140-146 | `_on_internal_listener` events.py:68-83 | D7、D13(a) |
| 构造器 `internal/update` 内建 handler events.ts:148-155 | `_on_internal_update` events.py:85-118 | D13(b)(c)(d) |
| `dispatch(type, args)` events.ts:165-175 | `_dispatch_hooks` events.py:183-233 | D8 |
| `parallel` events.ts:183-187 | `parallel` events.py:276-296 | 1:1（mode 怪癖 'emit' 已复刻 ✔；返回值差异 D9） |
| `emit` events.ts:194-196 | `emit` events.py:235-263 | D6、D10 |
| `serial` events.ts:204-209 | `serial` events.py:298-310 | 1:1 |
| `bail` events.ts:217-222 | `bail_sync` events.py:312-334 | D12（裁参） |
| `waterfall` events.ts:234-243 | `waterfall_sync` events.py:362-428 | D3、D4、D5 |
| `register(label, hooks, callback, options)` events.ts:254-260 | —（内联于 `on` events.py:145-152） | D1 |
| `unregister(hooks, callback)` events.ts:269-275 | 闭包 `disposer` events.py:154-158 | D16 |
| `on` events.ts:288-302 | `on` events.py:120-160 | D1、D2、D7 |
| `once` events.ts:312-318 | `once` events.py:162-181 | 1:1（先注销后调用 ✔；caller_ctx 剥离属 D8 配套） |
| `Events` 事件表接口 events.ts:329-352 | — | ADAPT（类型层；Python 无声明合并事件表） |
| — | `AggregateError` events.py:20-25 | ADAPT（Python 3.8 无内建 AggregateError，偏离清单第 1 条强制） |
| — | `_bind_caller_ctx` events.py:37-54 | D8（自发明） |
| — | `emit_async` events.py:265-274 | D11（自发明附加 API） |
| — | `bail`（async） events.py:336-360 | D11（自发明附加 API；TS bail 仅同步） |
| — | `waterfall`（async） events.py:430-506 | D11（自发明附加 API；TS waterfall 仅同步） |

## 差异

### D1: 监听器未挂接 fiber.effect —— 卸载时 hooks 泄漏
- TS: `reference/vendor/cordis/src/events.ts:254-260`
```ts
  register(label: string, hooks: Hook[], callback: any, options: EventOptions): () => void {
    const method = options.prepend ? 'unshift' : 'push'
    return this.ctx.fiber.effect(() => {
      hooks[method]({ ctx: this.ctx, callback, ...options })
      return () => this.unregister(hooks, callback)
    }, label)
```
  另 JSDoc events.ts:129："automatically disposes listeners with their owning fiber"。
- PY: `dsh/cordis/events.py:145-152` —— `on()` 直接创建 `Hook` 并 `insert/append` 到 `_hooks`，仅返回闭包 disposer，**未调用 `fiber.effect`**，fiber/context 卸载时监听器残留。
- 判定： MUST-FIX
- 影响: 任何按 fiber 生命周期注册的监听器在卸载后仍被分发（hooks 泄漏 + 幽灵回调），与 TS 契约直接冲突。
- 建议修法： 在 `on()` 注册段改走 `caller_ctx.fiber.effect(..., label)`（Python 侧 `dsh/cordis/fiber.py:213` 已有 `effect`），effect 清理函数内执行现有 disposer 逻辑；label 按 TS events.ts:300 格式 `ctx.on("…")` 生成。

### D2: `on()` 缺少 `fiber.assertActive()`（INACTIVE_EFFECT 守卫）
- TS: `reference/vendor/cordis/src/events.ts:293-295`
```ts
    // handle special events
    this.ctx.fiber.assertActive()
    listener = this.ctx.reflect.bind(listener)
```
  JSDoc events.ts:280-281："Throws `CordisError('INACTIVE_EFFECT')` if the fiber is already disposed."
- PY: `dsh/cordis/events.py:120-160` —— `on()` 全程无活性断言；对已卸载 fiber 的 ctx 注册会静默成功。
- 判定： MUST-FIX
- 影响: 已卸载 fiber 上注册的监听器既不报错也无人清理，故障延后且难排查。
- 建议修法： 在 `on()` 入口（reflect.bind 之前）调用 `caller_ctx.fiber.assert_active()`（`dsh/cordis/fiber.py:200` 已存在），失败抛等价 `CordisError('INACTIVE_EFFECT')`。

### D3: waterfall 被"签名嗅探 + 自动续链/自动回穿"重写，颠覆 next() 否决契约
- TS: `reference/vendor/cordis/src/events.ts:234-243`
```ts
  waterfall(...args: any[]) {
    const cbs = this.dispatch('waterfall', args)
    const inner = args.pop()
    const next = () => {
      const cb = cbs.shift() ?? inner
      return cb(...args)
    }
    args.push(next)
    return next()
```
  TS 语义：每个监听器（含 inner）都收到**相同**的 `(args…, next)`；链是否继续**只由运行时是否调用 `next()` 决定**；不调用 = 否决（内建也不执行）；监听器返回值即其子树结果，**无自动参数回穿**。
- PY: `dsh/cordis/events.py:384-407`（async 同构 452-482）
```python
                takes_next = "next" in param_names or "next_fn" in param_names or has_var or len(params) >= len(current_args) + 1
                ...
                elif pos_count == 0:
                    res = cb()
                    if res is not None:
                        return res
                    return next_fn(*current_args)
                else:
                    call_args = current_args[:pos_count] if pos_count < len(current_args) else current_args
                    res = cb(*call_args, **kwargs)
                    if res is not None:
                        new_args = [res] + list(current_args[1:])
                        return next_fn(*new_args)
                    return next_fn(*current_args)
```
  Python 语义：由**签名**决定是否传 `next`；未声明 next 形参的监听器**永远不否决**——返回 None 自动续链、返回非 None 自动以 `[res] + 其余参数` 回穿续链。TS 下 `def h(config): pass`（不调用 next）应终止整链，Python 下却继续执行到内建行为——关键路径语义相反。
- 判定： MUST-FIX
- 影响： 所有"返回即否决"型 waterfall 插件（权限拦截、配置否决）在 Python 侧失去否决能力；回穿还悄悄改写了下游收到的首个参数。
- 建议修法： 对齐 TS：统一以 `(args…, next_fn)` 调用全部监听器（或仅对声明了 next 形参的监听器传 next 且**不**自动续链/回穿——未声明者视同收到 next 但不调用，按否决处理）；删除 396-407/467-482 的 None 续链与 res 回穿逻辑，返回值仅作为"本次 next() 调用的结果"透传。

### D4: Python `next_fn` 接受覆写参数（TS `next` 为无参闭包，传参被忽略）
- TS: `reference/vendor/cordis/src/events.ts:237-240`
```ts
    const next = () => {
      const cb = cbs.shift() ?? inner
      return cb(...args)
    }
```
- PY: `dsh/cordis/events.py:373-375`（async 同构 441-443）
```python
        def next_fn(*override_args: Any) -> Any:
            nonlocal idx
            current_args = list(override_args) + list(args_list[len(override_args):]) if override_args else list(args_list)
```
- 判定： MUST-FIX
- 影响： 监听器调用 `next(new_value)` 在 TS 中被忽略、在 Python 中生效，续链契约分叉，同类插件两侧行为不可移植。
- 建议修法： `next_fn` 去掉 `*override_args`（或收到非空 override 时显式抛错），恒用初始 `args_list` 续链，与 TS 237-240 一致。

### D5: inner 提取条件化 + 链尽静默兜底（TS 无条件 pop、异常路径显式抛错）
- TS: `reference/vendor/cordis/src/events.ts:236-238`
```ts
    const inner = args.pop()
    const next = () => {
      const cb = cbs.shift() ?? inner
```
  空参时 `pop()` 得 `undefined`，链尽时调用 `undefined(...)` 抛 TypeError；末参非 callable 同样在调用期抛错。
- PY: `dsh/cordis/events.py:370`（async 同构 438）与 `events.py:425-426`
```python
        inner = args_list.pop() if args_list and callable(args_list[-1]) else None
```
```python
            else:
                return current_args[0] if current_args else None
```
  仅当末参 callable 才弹出；无 inner 且监听器耗尽时静默返回首参或 None。
- 判定： DEVIATION-PERMITTED
- 影响： 仅误用路径（空参/末参非 callable）可察觉：TS 抛错、Python 静默吞并；正常用法不可察觉。
- 建议修法： 如需收紧，改为无条件 pop 且 inner 非 callable 时抛 `TypeError`，复刻 TS 失败模式；至少保留本条记录。

### D6: `internal/dispatch` 双调用约定（单参监听器改传 info dict）
- TS: `reference/vendor/cordis/src/events.ts:168-170`
```ts
    if (!name.startsWith('internal/')) {
      this.emit('internal/dispatch', type, name, args, thisArg)
    }
```
  恒 4 位置参 `(type, name, args, thisArg)`。
- PY: `dsh/cordis/events.py:248-255`
```python
            if sig is not None and len(sig.parameters) == 1 and not any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values()) and event_name == "internal/dispatch":
                info = {
                    "type": args[0] if len(args) > 0 else None,
                    "name": args[1] if len(args) > 1 else None,
                    "args": args[2] if len(args) > 2 else [],
                    "ctx": args[3] if len(args) > 3 else None,
                }
                res = listener(info)
```
- 判定： MUST-FIX
- 影响： 同一事件存在两种互斥的监听器调用约定（按签名分叉），TS 侧监听器直接移植会收到 dict 而非 4 实参；且该特判只在 `emit` 生效，`emit_async/parallel` 路径不一致。
- 建议修法： 删除 248-255 特判，统一 `listener(*args)`；若有存量单参监听器，改造监听器本身而非分发器。

### D7: `internal/listener` 触发条件收窄 + payload 变形
- TS: `reference/vendor/cordis/src/events.ts:296`（无条件分发）与 handler events.ts:140-146
```ts
    const result = this.bail(this.ctx, 'internal/listener', name, listener, options)
    if (result) return result
```
```ts
    this.on('internal/listener', function (this: Context, name, listener, options: EventOptions) {
      if (name === 'internal/update' && !options.global) {
```
  payload 为 `(name, listener, options对象)`（注意 events.ts:349 类型声明写的 `prepend: boolean` 与实现不一致，以实现为准）。
- PY: `dsh/cordis/events.py:138-143` 与 handler `events.py:68`
```python
        if caller_ctx is not None and not event_name.startswith("internal/listener"):
            intercepted = self.bail_sync("internal/listener", event_name, handler, prepend, global_listener, caller_ctx=caller_ctx)
```
```python
        def _on_internal_listener(name: str, listener: Any, prepend: bool = False, global_listener: bool = False, *args: Any, **kwargs: Any) -> Any:
```
  两处收窄/变形： ① `caller_ctx is None` 时完全不拦截；② 事件名以 `internal/listener` 开头时跳过拦截（TS 会照常分发）；③ payload 由 options 对象变为 `(prepend, global_listener)` 两个位置 bool + `caller_ctx` kwarg。
- 判定： MUST-FIX（①②为无理由的契约收窄；③的 options→双 bool 需与 TS 实现 payload 对齐或在 Hook 协议层统一）
- 影响： 外部拦截 `internal/listener` 的插件在无 caller_ctx、或拦截 `internal/listener` 自身注册时观察不到事件；payload 形状与 TS 不可移植。
- 建议修法： `on()` 中无条件 `self.bail_sync("internal/listener", event_name, handler, options)`（去掉 138 行两个守卫，经核对无递归风险：内建 handler 对非 internal/update 名返回 None）；payload 统一为单个 options 载体（dict 或 Hook 前体），内建 handler 与外部监听器共用。

### D8: this 绑定/过滤协议整体替换为 caller_ctx kwarg 注入 + 属性嗅探
- TS: `reference/vendor/cordis/src/events.ts:166-174`
```ts
    const thisArg = typeof args[0] === 'object' || typeof args[0] === 'function' ? args.shift() : null
    const name: string = args.shift()
    ...
    const filter = thisArg?.[Context.filter]
    return (this._hooks[name] || [])
      .filter(hook => hook.global || !filter || filter.call(thisArg, hook.ctx))
      .map(hook => hook.callback.bind(thisArg))
```
  thisArg 由调用方以首个位置参传入（调用约定见 `reference/vendor/cordis/src/reflect.ts:333`：`this.ctx.events.emit(self, 'internal/service', …)`）；过滤键为 `Context.filter` 符号（`src/context.ts:45-46`、`src/utils.ts:61`）。
- PY: `dsh/cordis/events.py:37-54`（`_bind_caller_ctx` kwarg 注入）、`events.py:190-205`（thisArg 由 `caller_ctx` kwarg 或 `registry`+`reflect` 属性嗅探提供，绝不 shift 位置参）、`events.py:220-223`（过滤键改为 `_filter_hook`/`__dict__["filter"]` 属性 + `__cordis_context_brand__` 品牌检查）
```python
                if actual_ctx is not None and getattr(actual_ctx, "__cordis_context_brand__", None) == "cordis.v1.context":
                    ctx_filter = getattr(actual_ctx, "_filter_hook", None) or getattr(actual_ctx, "__dict__", {}).get("filter")
                else:
                    ctx_filter = getattr(actual_ctx, "filter", None)
```
- 伴随子差异： ① 非 callable 的 filter 在 Python 被静默视为 None（hook 全过），TS `filter.call` 会 TypeError（events.ts:173）；② TS 风格直调 `bus.emit(ctx_obj, 'evt')` 时 Python 把 `ctx_obj` 当事件实参（不走过滤、不绑定）；③ 带 `**kwargs` 的监听器每次分发都被注入 `caller_ctx` 键（TS 的 `bind` 不改变实参集合）；④ `_dispatch_hooks` 接受 list/tuple/单对象/ctx 对象四种入参形态（TS 仅数组）；⑤ `once` 内剥离 `caller_ctx`（events.py:170-177）与 waterfall/emit 向监听器透传分发级 `**kwargs`（events.py:257、395 等）均为该协议配套。
- 判定： DEVIATION-PERMITTED（Python 无 `this`/Symbol 机制的全库统一替代约定；过滤三态 `global 绕过 / 无 filter 全过 / filter(hook.ctx)` 与 TS 逐条等价，且 TS events.ts:14 `isBailed` 之外未观察到行为级破坏）。子项①②建议后续收紧。
- 建议修法： 维持协议，但 ① 对非 callable filter 抛 TypeError；② 在 `_dispatch_hooks` 文档化"首位置参永不作 thisArg"约定，防止 TS 风格调用静默误判。

### D9: `parallel` 返回 results 列表（TS 返回 void）
- TS: `reference/vendor/cordis/src/events.ts:183-187`
```ts
  async parallel(...args: any[]) {
    const results = await Promise.allSettled(this.dispatch('emit', args).map(async cb => cb(...args)))
    const errors = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected')
    if (errors.length) throw new AggregateError(errors.map(error => error.reason))
```
- PY: `dsh/cordis/events.py:292-296`
```python
        results = await asyncio.gather(*[_run(cb) for cb in listeners], return_exceptions=True)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise AggregateError(errors)
        return list(results)
```
  （空监听器提前返回 `[]`，events.py:283-284，与 TS allSettled 空数组等价。）
- 判定： DEVIATION-PERMITTED
- 影响： 附加返回值，按 void 消费的调用方不受影响；allSettled→gather(return_exceptions=True) 为 3.8 兼容等价改写（ADAPT 内核，已含于偏离清单第 1 条）。
- 建议修法： 可保留；在 docstring 标注"超出 TS 契约的附加返回值"。

### D10: `emit` 对 awaitable 返回值的调度（TS 直接丢弃返回的 promise）
- TS: `reference/vendor/cordis/src/events.ts:194-196`
```ts
  emit(...args: any[]) {
    this.dispatch('emit', args).map(cb => cb(...args))
  }
```
- PY: `dsh/cordis/events.py:258-263`
```python
            if inspect.isawaitable(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    pass
```
- 判定： DEVIATION-PERMITTED（有事件循环时为 fire-and-forget 的 Python 化等价；**无事件循环时 RuntimeError 被静默吞掉，协程永不执行且无告警**——TS 中 promise 至少会运行至完成）。
- 建议修法： 无循环分支改为记日志或直接抛错，避免协程静默丢失。

### D11: Python 附加异步 API：`emit_async` / async `bail` / async `waterfall`
- TS: 无对应——`bail`（events.ts:217-222）与 `waterfall`（events.ts:234-243）均为同步；async 监听器返回的 promise 被丢弃。
- PY: `dsh/cordis/events.py:265-274`（emit_async，顺序 await）、`events.py:336-360`（async bail，await 各监听器，mode 仍报 'bail'）、`events.py:430-506`（async waterfall，await 各监听器）。
- 判定： DEVIATION-PERMITTED（附加 API，不改变同步路径；但 async waterfall 的"等待每个监听器"是 TS 不存在的时序语义，且 async bail 与 async `serial`（mode 'serial'）行为几乎重合、仅 mode 字符串不同）。
- 建议修法： 保留但在模块 docstring 标注为 Python 扩展；评估 async bail 是否应并入 serial 以减少 mode 语义分叉。

### D12: `bail_sync`/`bail` 按签名裁参（TS 恒传全部实参）
- TS: `reference/vendor/cordis/src/events.ts:218-221`
```ts
  bail(...args: any[]) {
    for (const cb of this.dispatch('bail', args)) {
      const result = cb(...args)
      if (isBailed(result)) return result
```
- PY: `dsh/cordis/events.py:324-329`（async 同构 348-353）
```python
                pos_count = sum(1 for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
                call_args = args if (has_var or pos_count >= len(args)) else args[:pos_count]
                res = listener(*call_args, **kwargs)
```
- 判定： DEVIATION-PERMITTED（Python 可调用对象不接受多余位置实参，裁参是语言级必需的等价改写：监听器视角收到的参数集合与 TS"忽略多余实参"一致；非两条偏离清单所列，故记录许可）。注意 Python 库内不对称：`serial`（events.py:304-309）不裁参，需钉测防漂移。
- 建议修法： 无需改码；为 serial/bail 裁参行为补统一钉测（见 T 项）。

### D13: `internal/update` 内建 handler 的四处子差异
- TS: `reference/vendor/cordis/src/events.ts:148-155`
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
- PY: `dsh/cordis/events.py:85-118`，子差异：
  - (a) TS 的 `internal/listener` 内建 handler 注册为**非 global**（events.ts:140 无 options，受 filter 约束）；Python 注册为 `global_listener=True`（events.py:83）。root ctx 通常无 filter，实际等价。
  - (b) TS 直接读 `this._hooks`（this=fiber thisArg，events.ts:149）；Python 从 `caller_ctx`/`self.ctx` 推导 fiber（events.py:86-88）——属 D8 协议替代。
  - (c) TS 恒 3 参调 `cb.call(this, config, noSave, _next)`（events.ts:152）；Python 对 `next_callback` 做签名自适应（0/1/2/3+ 参，events.py:96-113）——Python 严格 arity 的语言级必需等价改写（非两条清单所列，记录许可）。
  - (d) cbs 耗尽且无 `next_callback` 时 Python 返回 `cfg` 兜底（events.py:114）；TS 此路径必调用框架传入的 `next`。
  另附观察： TS events.ts:143 在 `prepend` 时调用 `hooks.unshift`，而 `DisposableList`（`src/utils.ts:5-40`）只有 `push/delete/clear`，该路径为 TS 侧 latent TypeError；Python `DisposableList` 有 `unshift`（`dsh/cordis/utils.py:246`），events.py:78-80 与 TS 逐行对应反而可运行（Python 侧超出 TS 修复，不判差异）。
- 判定： (a)(b)(c) DEVIATION-PERMITTED； (d) DEVIATION-PERMITTED（防御分支静默化，正常框架调用恒有 next）。
- 建议修法： (d) 无 next 时改为显式抛错或记日志，避免静默吞掉更新链。

### D14: `defineProperty(this, symbols.tracker, …)` 缺失
- TS: `reference/vendor/cordis/src/events.ts:134-138`
```ts
  constructor(private ctx: Context) {
    defineProperty(this, symbols.tracker, {
      property: 'ctx',
      noShadow: true,
    })
```
- PY: `dsh/cordis/events.py:63-65` 无任何 tracker 元数据。
- 判定： DEVIATION-PERMITTED（tracker 供 traceable proxy 消费，`src/utils.ts:117-125`；Python 侧无该消费机制，缺失仅损诊断能力，不影响分发语义）。
- 建议修法： 若 Python 侧后续引入 traceable service，需补等价 tracker 标记（如 `_cordis_tracker = {"property": "ctx", "no_shadow": True}`）。

### D15: `_hooks` 仅 str 键（TS 支持 symbol 事件名）
- TS: `reference/vendor/cordis/src/events.ts:132` `Record<keyof any, Hook[]>`；`on(name: string | symbol, …)` events.ts:288；label 的 symbol 分支 events.ts:300。
- PY: `dsh/cordis/events.py:65` `Dict[str, List[Hook]]`；`on(event_name: str, …)` events.py:120。
- 判定： ADAPT（Python 无 `Symbol.for` 机制，事件名域收敛为 str 为语言级等价改写；偏离清单第 1 条覆盖范围内）。备注：若需对象键，`Dict` 天然支持 hashable 键，属可选扩展。
- 建议修法： 无需改码；如后续需要内部符号事件，用模块级哨兵对象作键即可。

### D16: `unregister` 公有方法缺失；按 Hook 实例 vs 按回调身份移除
- TS: `reference/vendor/cordis/src/events.ts:269-275`
```ts
  unregister(hooks: Hook[], callback: any) {
    const index = hooks.findIndex(hook => hook.callback === callback)
    if (index >= 0) {
      hooks.splice(index, 1)
      return true
```
- PY: `dsh/cordis/events.py:154-158`
```python
        def disposer() -> bool:
            if event_name in self._hooks and hook in self._hooks[event_name]:
                self._hooks[event_name].remove(hook)
                return True
```
  Python 每次注册生成独立 `Hook` 实例，disposer 移除自身实例；TS 按 callback 身份移除首个匹配。最终一致（两次同 callback 注册各自注销各移除一条），仅外部直调 `unregister` 的入口缺失。
- 判定： DEVIATION-PERMITTED
- 建议修法： 如需 1:1 表面，补 `unregister(hooks, callback)` 方法供外部/调试使用。

### D17: `AggregateError` 自定义类
- TS: `reference/vendor/cordis/src/events.ts:186` 使用 JS 内建 `AggregateError`。
- PY: `dsh/cordis/events.py:20-25` 自定义异常，持 `.errors` 列表，消息含逐条摘要。
- 判定： ADAPT（Python 3.8 无内建 AggregateError、无 ExceptionGroup（3.11+），偏离清单第 1 条强制；`.errors` 属性与 TS 对齐）。
- 建议修法： 无。

### D18: 类型层缺失（Parameters/ReturnType/ThisType、DispatchMode、EventOptions、Events 事件表）
- TS: events.ts:18-22、32、112-117、329-352（含 9 个 internal/* 事件的 JSDoc 契约与 @mode 标注）。
- PY: 无对应（事件契约仅存在于 docstring/events.py:1-4）。
- 判定： ADAPT（类型层；Python 3.8 typing 无法复刻声明合并事件表，运行时行为差异已由各 D 条目独立核算）。
- 建议修法： 在模块 docstring 补一张 internal/* 事件 payload 速查表（以源码为据），弥补类型层缺失。

### D19: 类名 `EventsService` → `EventBus`
- TS: events.ts:131 `export class EventsService`。
- PY: events.py:57 `class EventBus`。
- 判定： DEVIATION-PERMITTED（纯命名；语义无差，但跨仓库检索/对照时需心智映射）。
- 建议修法： 如追求可对照性可加别名 `EventsService = EventBus`。

（补充核对结论，不单列：`emit` 同步异常中断后续监听器并向上传播、分发快照内已完成监听器列表、`parallel` mode 恒报 'emit'、`serial`/`bail`/`waterfall` 的 mode 字符串、`once` 先注销后调用、`prepend` 插队顺序、空监听器各模式行为、`isBailed` 对 `0`/`''` 的真值判定——两侧逐点一致 ✔。events.py:8 `import sys` 未使用，属清理项。）

## 测试缺口

### T1: `parallel` 的 `internal/dispatch` mode 恒为 `'emit'` — TS events.ts:184 `this.dispatch('emit', args)`（非 'parallel'）；PY events.py:282 已复刻，缺钉测防"顺手修正"回归。
### T2: `emit` 同步异常中断后续监听器并向调用方传播 — TS events.ts:195 `.map(cb => cb(...args))` 短路；PY events.py:241-257 循环无 try，行为一致但无钉测。
### T3: bail 真值语义边界 — TS events.ts:14 `value !== null && value !== false && value !== undefined`：`0`、`''`、`NaN` 均 bailed；PY events.py:17 需钉测 `0`/`''`/`0.0` bailed、`False`/`None` 不 bail。
### T4: `once` 先注销后调用、返回值透传、同事件二次分发不再触发 — TS events.ts:313-316；PY events.py:170-181。
### T5: options 布尔速记与 prepend 插队 — TS events.ts:289-291 + 255；PY events.py:149-152（kwargs 形态），需钉测注册顺序。
### T6: `internal/update` 监听器经 `internal/listener` 拦截存入 `fiber._hooks`（DisposableList）并返回可注销 disposer — TS events.ts:141-144 + 296-297；PY events.py:72-80 + 138-143（依赖 D7 修复后统一 payload）。
### T7: 已卸载 fiber 上 `on()` 应抛 `CordisError('INACTIVE_EFFECT')` — TS events.ts:294；PY 现缺失（D2），修复后补钉测。
### T8: waterfall 监听器不调用 `next()` 否决内建行为（含内建不被执行、返回值成为结果）— TS events.ts:237-242；PY 当前签名嗅探自动续链（D3），修复后钉测否决路径。
### T9: 空监听器矩阵 — waterfall 直落 inner（TS events.ts:238）；parallel 不抛（events.ts:184）；serial/bail 返回 None（events.ts:207-208、221）；PY 对应 events.py:283-284、308-310、334。
### T10: 分发快照保证 — 监听器在分发中自我注销（once），本次分发仍完成已登记回调，不影响其余监听器；TS events.ts:172-174（filter/map 物化）；PY events.py:211（`list(...)` 拷贝）。

## PROBE 候选

- D3: 构造监听器 `def h(config): return None`（无 next 形参）注册于 waterfall 事件并随内建 `next` 分发——TS 契约预测内建**不**被调用（否决），Python 预测自动续链到内建；再构造零参监听器返回非 None，验证 PY events.py:396-400 的提前返回分支。用于实证语义相反。
- D5: `waterfall('evt', 'x', 123)`（末参非 callable）与 `waterfall_sync('evt')`（空参）——TS 预测调用期 TypeError（events.ts:236-238），Python 预测将 123 当普通实参 / 返回 None（events.py:370、425-426）。
- D6: 分别注册 `def h(info)`（单参）与 `def h(t, n, a, c)` 于 `internal/dispatch`，探测 PY events.py:248-255 双约定并存；再经 `parallel` 分发公共事件验证特判未覆盖路径。
- D8: 以 TS 约定 `bus.emit(ctx_obj, 'evt')` 直调 Python EventBus，确认 `ctx_obj` 被当事件实参（无过滤、无绑定）；注册 `def h(**kw)` 后分发，确认 `kw` 中出现注入的 `caller_ctx` 键（TS `bind` 不加实参）。
- D10: 无事件循环环境下 `emit` 一个返回 coroutine 的监听器，验证 PY events.py:262-263 RuntimeError 分支静默、协程永不执行且无告警。
- D12: `bail_sync` 分发 3 参、监听器 `def h(a)`——确认裁参收到 1 参；同场景走 `serial` 确认收到 3 参（PY 库内不对称，钉测防漂移）。
- D13(d): 构造无 `caller_ctx` 且 `self.ctx` 无 fiber 的 EventBus 分发 `internal/update`——TS 契约此时必调用框架 `next`，Python 走 events.py:114 返回 `cfg` 兜底；验证兜底是否被下游依赖。
