# dsh/cordis/plugin.py ↔ reference/vendor/cordis/src/index.ts

对比快照: dsh-v0.1.2-alpha.1。TS 侧 `index.ts`（14 行）是**纯桶导出**（barrel）：runtime 契约实际定义在 `registry.ts`（Plugin 类型族、Inject、RegistryService）与 `fiber.ts`（插件执行、Config 校验、disposable 收集）。Python 侧同样分层：`plugin.py`（Plugin 基类，31 行）、`registry.py`（registry/Inject）、`fiber.py`（执行）。本报告在"插件入口契约"层面对比，涉及移植版行为的位置标注到实际承载文件。

## 差异清单

### D1 [MUST-FIX] Plugin.Base 元数据字段缺失：provide / intercept / Config（及 PluginRuntime.Config 字段）
- 位置: py:dsh/cordis/plugin.py:10-16 vs ts:reference/vendor/cordis/src/registry.ts:100-111（index.ts:10 转出）
- 原版行为:
```ts
export interface Base<T = any> {
  name?: string
  Config?: StandardSchemaV1<any, T>   // 配置校验器
  inject?: Inject
  provide?: string | string[]         // Service 与 loader 读取
  intercept?: Dict<boolean>           // 声明消费哪些服务的 intercept 配置
}
```
- 移植版现状:
```python
class Plugin:
    id: str = ""
    name: str = ""
    inject: List[str] = []      # 无 provide / intercept / Config 声明
```
- 修复方案: 基类补 `provide: Optional[Union[str, List[str]]] = None`、`intercept: Optional[Dict[str, bool]] = None`、`Config = None`；`PluginRuntime`（registry.py:120-139）补 `Config` 字段并在 registry.plugin() 创建 runtime 时写入（对齐 registry.ts:326 `runtime = {..., Config: plugin.Config}`）；fiber/reflect 在自动命名提供服务时读取 `plugin.provide`（对齐 service.ts:43 `name ??= this.constructor['provide']`）。现状：Config 校验在子类声明 `Config`/`schema` 时已生效（fiber.py:40 resolve_config 读取），但 `provide`/`intercept` 在 dsh/ 全仓无消费者。

### D2 [MUST-FIX] ctx.inject() 回调契约丢参：TS 调 callback(ctx, config)，移植版只传 ctx
- 位置: py:dsh/cordis/registry.py:346-353 vs ts:reference/vendor/cordis/src/registry.ts:300-302 + fiber.ts:259
- 原版行为:
```ts
inject(inject: Inject, callback: Plugin.Function<void>) {
  return this.plugin({ inject, apply: callback, name: callback.name })
}
// fiber 执行： return runtime.callback(this.ctx, this.config)   // fiber.ts:259
```
- 移植版现状:
```python
class InjectPlugin:
    def apply(self, c: Any) -> Any:
        return callback(c)        # config 从未传入
```
- 修复方案: `InjectPlugin.apply` 透传 fiber 配置——把 `config` 存到包装实例并在 apply 中 `return callback(c, self._config)`（或经 fiber 以 `(ctx, config)` 调用函数插件）。差异实例：按 TS 契约声明的 `def cb(ctx, config)` 在移植版 `ctx.inject(deps, cb)` 下必然 TypeError → fiber 置 FAILED。

### D3 [MUST-FIX] 对象/类插件的 apply 契约：TS 恒以 (ctx, config) 调用，移植版只传 ctx
- 位置: py:dsh/cordis/fiber.py:567-570 vs ts:reference/vendor/cordis/src/fiber.ts:251-260（Plugin.Object 契约 registry.ts:130-133）
- 原版行为:
```ts
if (isConstructor(runtime.callback)) {
  const instance = new runtime.callback(this.ctx, this.config)
  ...
} else {
  return runtime.callback(this.ctx, this.config)   // 对象插件解析出的 apply 也走这里
}
```
- 移植版现状:
```python
if hasattr(self.plugin, "apply") and callable(self.plugin.apply):
    res = self.plugin.apply(self.ctx)              # config 只经实例属性 self.config 可达
elif not isinstance(self.plugin, Service) and callable(self.plugin):
    res = self.plugin(self.ctx, self.config)       # 函数插件路径正确
```
- 修复方案: apply 路径按 `inspect.signature` 判定后传 `(self.ctx, self.config)`；基类 `Plugin.apply(self, ctx)` 签名更新为 `apply(self, ctx, config=None)` 保持向后兼容。差异实例：TS 形状的对象插件 `apply(ctx, config)` 在移植版下 TypeError → fiber FAILED。

### D4 [MUST-FIX] 非法插件错误类型/文案不一致，且 resolve() 缺少 apply 访问的 try/catch、callable 判定顺序不同
- 位置: py:dsh/cordis/registry.py:165-175, 231-232 vs ts:reference/vendor/cordis/src/registry.ts:222-228, 319
- 原版行为:
```ts
resolve(plugin: Plugin): Function | undefined {
  try {                                   // "plugin.apply may throw"
    if (typeof plugin === 'function') return plugin
    if (isApplicable(plugin)) return plugin.apply
  } catch {}
}
...
if (!callback) throw new Error('invalid plugin, expect function or object with an "apply" method, received ' + typeof plugin)
```
- 移植版现状:
```python
if callable(plugin): return plugin            # 带 __call__ 的实例先于 apply 命中（TS 中对象走 apply 分支）
if hasattr(plugin, "apply") and callable(plugin.apply): return plugin.apply   # 无 try 保护
...
raise ValueError(f"Invalid plugin, expected function, class, or object with 'apply' method: {plugin_cls_or_instance}")
```
- 修复方案: ①apply 属性访问包 try/except → None；②错误改为 `Error`（或项目 CordisError）并复刻 TS 文案 `invalid plugin, expect function or object with an "apply" method, received <type>`；③判定顺序对齐：纯函数/类（`types.FunctionType`/`isclass`）→ apply → 其余 callable 兜底。

### D5 [MUST-FIX] 插件 apply/init 的返回值未按 Disposable 收集：TS 把返回的 disposer 注册为清理回调，移植版直接丢弃
- 位置: py:dsh/cordis/fiber.py:565-587 vs ts:reference/vendor/cordis/src/fiber.ts:79-80, 247-263
- 原版行为:
```ts
// fiber.ts:79-80 契约注释
// Either a single disposer, a promise of one, or a (possibly async) iterable
// yielding several — generator effects register each yielded disposer as it ...
const collect = (dispose: Disposable) => { this._disposables.push(dispose) }
this._runner = { ..., execute: function () { ... return runtime.callback(this.ctx, this.config) }, collect }
```
- 移植版现状:
```python
res = self.plugin.apply(self.ctx)
if inspect.isawaitable(res):      # 只处理协程；返回的可调用 disposer / 生成器被丢弃
    ...
self._error = None
self.set_state(FiberState.ACTIVE)
```
- 修复方案: `_reload` 中对非 awaitable 的返回值：callable → `self.effect(res, label=f"apply({self.name})")`；生成器/异步生成器 → 走 effect 的 yield-disposer 收集（fiber.effect 已支持），保证卸载时执行。差异实例：TS 插件 `apply(ctx){ ...; return () => cleanup() }` 的 cleanup 在移植版卸载时永不运行。

### D6 [MUST-FIX] 类插件构造调用用 TypeError 级联试探，会吞掉构造函数内部真实 TypeError
- 位置: py:dsh/cordis/registry.py:243-265 vs ts:reference/vendor/cordis/src/fiber.ts:251-257
- 原版行为:
```ts
if (isConstructor(runtime.callback)) {
  const instance = new runtime.callback(this.ctx, this.config)   // 单一调用形态；构造内 TypeError 照常抛出
```
- 移植版现状:
```python
try:    plugin_inst = plugin_cls_or_instance(self.ctx, config=config)
except TypeError:
    try: plugin_inst = plugin_cls_or_instance(self.ctx)
    except TypeError: plugin_inst = plugin_cls_or_instance()     # 内部 TypeError 也会触发降级重试
```
- 修复方案: 用 `inspect.signature` 一次性判定构造形态（接受 (ctx, config) / (ctx) / ()），按判定结果调用一次；真实 TypeError 直接传播给 fiber 失败处理（`self._error = e`）。现有级联可能让 `def __init__(self, ctx): self.x = None + 1` 之类错误被静默降级成无参构造"成功"。

### D7 [ADAPT] Plugin.id 与 teardown() 为移植版独有扩展
- 位置: py:dsh/cordis/plugin.py:10, 24-28 vs ts:registry.ts:100-111（Base 无此二字段）
- 原版行为: TS 无 `id`/`teardown`；清理统一走 effect/apply 返回的 disposable（fiber.ts:79-80）。
- 移植版现状: `id` 供 loader/registry 按 id 查找（registry.py:183, 379）；`teardown` 被 fiber 注册为 effect（fiber.py:562-563）。
- 结论: 无害扩展，保留并在 docstring 标注"移植版扩展，无 TS 对应物"。

### D8 [ADAPT] 入口形状联合类型不完整：PluginType 漏掉"对象 with apply"形状
- 位置: py:dsh/cordis/plugin.py:31 vs ts:registry.ts:92-95
- 原版行为: `type Plugin<T> = Plugin.Function<T> | Plugin.Constructor<T> | Plugin.Object<T>`（三种形状）。
- 移植版现状: `PluginType = Union[Plugin, Callable[[Any], None]]`——运行时 registry.resolve 支持对象插件（registry.py:173-174），仅类型别名/文档缺第三形状。
- 结论: 更新别名与文档即可（如 `Union[Plugin, Callable, Any]` + 注释说明 apply 协议）。

### D9 [ADAPT] 构造/apply 签名形态与 @Inject 装饰器的平台化改写
- 位置: py:dsh/cordis/plugin.py:14-22 + registry.py:64-117 + fiber.py:536-543 vs ts:registry.ts:37-60, 126-127 + fiber.ts:253-257
- 原版行为: 类插件 `new (ctx, config)` 构造即得 ctx；`instance?.[symbols.initHooks]` 逐个执行 @Inject 方法钩子后调 `instance?.[symbols.init]?.()`。
- 移植版现状: `Plugin.__init__(config)` 拿 config，ctx 由 fiber 事后注入（fiber.py:536-537）；`@inject` 装饰器类级累积进 inject 字典、方法级生成 wrapper + `_init_hooks`（registry.py:278-319），fiber._reload 统一执行 init 钩子与 `init`（fiber.py:540-560）。
- 结论: 无 JS 装饰器/Symbol 元数据的等价实现，行为对齐（延迟到服务可用后执行），保留。

### D10 [ADAPT] Config 校验：StandardSchemaV1 → Schema（schemastery 移植）经 resolve_config
- 位置: py:dsh/cordis/fiber.py:31-55 vs ts:fiber.ts:50-56（`runtime.Config['~standard'].validate(config)`）+ registry.ts:143-145
- 原版行为: `resolveConfig(runtime, config)` 走 `~standard.validate`，issues 映射为异常。
- 移植版现状: `resolve_config` 读 `plugin.schema or plugin.Config`，`Schema.validate` 返回 `{value, issues}`，issues → ValidationError；loader 侧另读 runtime/plugin 的 Config（loader.py:1188）。
- 结论: 平台等价（issues→异常、value 回填语义一致），保留。

### S1 [SKIP] index.ts 转出的类型层构造无运行时行为
- 位置: ts:registry.ts:148-162（Spread/GetPluginParameters/GetPluginConfig 条件类型）、164-187（`declare module './context.ts'` 声明合并）、19-24（InjectKey 映射类型）；fiber.ts 类型注释
- 原版行为: 纯类型/模块扩充，编译期完成。
- 移植版现状: Python 3.8 typing 无法等价表达，也无运行时效果（运行时对应物即 ctx.plugin/ctx.inject 方法，已存在于 context.py:252-257）。
- 结论: 跳过。

## 测试缺口
现有覆盖：tests/test_cordis_inject_decorator_1to1.py（@inject 装饰器）、tests/test_cordis_strict_inject*.py（服务注入门禁）、tests/test_cordis_1to1_full.py 等（fiber 生命周期/组合纪元）。以下插件入口契约行为无用例：

### T1 ctx.inject 回调收到 (ctx, config)（D2）
- 建议: `test_inject_callback_receives_config` — `ctx.inject([], lambda ctx, config: captured.append(config))` 且 config 为 None（inject() 无配置）。
### T2 对象/类插件 apply 收到 config（D3）
- 建议: `test_object_plugin_apply_receives_config` — `ctx.plugin(obj_with_apply, {"a": 1})` 时 apply 第二参收到 `{"a": 1}`。
### T3 非法插件错误类型与文案（D4）
- 建议: `test_registry_invalid_plugin_error_message` — `ctx.plugin(123)` 抛 Error 且消息含 `invalid plugin, expect function or object with an "apply" method`；apply 属性访问抛异常的插件 resolve 返回 None 而非传播。
### T4 类插件构造 TypeError 不被级联吞掉（D6）
- 建议: `test_plugin_constructor_typeerror_propagates` — 构造函数内部 `raise TypeError("boom")` 时 fiber 置 FAILED 且 `_error` 原样为该异常（而非无参构造成功或次生错误）。
### T5 apply 返回的 disposer 在卸载时执行（D5）
- 建议: `test_plugin_apply_returned_disposer_disposed` — apply 返回闭包修改标志位，`fiber.dispose()` 后标志位被置位；生成器 yield 多个 disposer 逐一执行。
### T6 plugin.provide / PluginRuntime.Config 元数据被消费（D1）
- 建议: `test_plugin_provide_metadata_and_runtime_config` — 类插件声明 `provide = "svc"` 后加载即以该名提供服务；`runtime.Config` 在 registry.plugin() 后可读并驱动 resolve_config 校验。
