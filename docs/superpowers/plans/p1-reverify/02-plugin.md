# G2-plugin 盲审报告

审计范围：TS 权威源 `reference/vendor/cordis/src/{index,registry,service,reflect,utils}.ts` ↔ Python 移植 `dsh/cordis/{plugin,registry,service,reflect}.py`（另通读 `dsh/cordis/{utils,fiber}.py` 作为交叉参照，不作为受审差异的独立判据，仅用于确认被审文件所引用符号的实际行为）。逐函数/逐类建立映射如下；所有判定仅基于所读源码。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| index.ts:1-14（barrel 再导出，无运行时符号） | 无需对应 | 1:1（空） |
| registry.ts:8-10 `isApplicable` | registry.py:181-189（`resolve` 内联判定） | ADAPT |
| registry.ts:19 `Inject` 类型 | registry.py:14 `Inject` 类（仅命名空间） | ADAPT |
| registry.ts:37-60 `@Inject` 装饰器 | registry.py:64-117 `inject()` | D4, D5, D36 |
| registry.ts:63-89 `Inject.resolve` | registry.py:20-61 `Inject.resolve` | D1, D2, D3 |
| registry.ts:92-146 `Plugin` 类型联合/Base/Function/Constructor/Object | plugin.py:4-32 `Plugin` 基类 + plugin.py:35-39 `PluginType` | D6, D16, D17 |
| registry.ts:113-118 `Plugin.Transform` | 无对应 | D35 |
| registry.ts:136-145 `Plugin.Runtime` | registry.py:120-143 `PluginRuntime` | D7, D36 |
| registry.ts:148-162 `Spread`/`GetPluginParameters`/`GetPluginConfig` | 无（纯类型层） | 1:1（类型层不适用） |
| registry.ts:164-187 `ctx.inject`/`ctx.plugin` 声明合并 | RegistryService.inject/plugin（registry.py:369/234）+ Context 侧（越出受审集） | 部分 ADAPT |
| registry.ts:196-198 `_counter`/`_internal` | registry.py:155-156 `_counter`/`_runtimes` | 1:1 |
| registry.ts:199-204 构造器 `defineProperty(symbols.tracker)` | registry.py:153-158（无 tracker） | D34 |
| registry.ts:207-209 `counter` getter（++ 后返回） | registry.py:166-169 `counter` property | 1:1 |
| registry.ts:212-214 `size` | registry.py:171-173 `size` | 1:1 |
| registry.ts:222-228 `resolve` | registry.py:175-192 `resolve` | D15 |
| registry.ts:236-239 `get` | registry.py:194-196 `get` | 1:1 |
| registry.ts:247-250 `has` | registry.py:204-206 `has` | 1:1 |
| registry.ts:258-267 `delete` | registry.py:208-223 `delete` | D11 |
| registry.ts:270-291 `keys/values/entries/forEach` | 无对应 | D12 |
| registry.ts:300-302 `inject(deps, callback)` | registry.py:369-393 `inject`（签名嗅探为自发明） | ADAPT + D32 |
| registry.ts:316-336 `plugin()` | registry.py:234-367 `plugin()` | D7-D10, D14, D9 |
| service.ts:13-25 `Service` 静态符号 ×7 | service.py:32-40 + service.py:11-22 `ServiceSymbols` | D18 |
| service.ts:27 `[symbols.config]` 幻影类型 | service.py:34 `config`（字符串类属性，形态不同） | ADAPT |
| service.ts:42-59 构造器 | service.py:45-68 `__init__` | D19, D20, D23, D34 |
| service.ts:61-63 `[symbols.filter]` | service.py:105-111 `filter` | 1:1（经 get_isolate_symbol，ADAPT） |
| service.ts:65-73 `[symbols.extend]` | service.py:113-128 `_extend` | D21 |
| service.ts:86-102 `[symbols.resolveConfig]` | service.py:77-103 `resolve_intercept_config` | D22 |
| service.ts:104-114 `static [Symbol.hasInstance]` | 无对应 | D24 |
| reflect.ts:73-78 `enhanceError` | 无对应（utils.py:841-865 `compose_error` 以 `_outer_stack` 属性替代栈拼接） | ADAPT |
| reflect.ts:80-91 `RESERVED_WORDS`/`isSpecialProperty` | reflect.py:44-47 `RESERVED_PROPERTIES` + reflect.py:86 门控 | D25 |
| reflect.ts:97-113 `Property` 命名空间 | reflect.py:11-29 `PropertyType`/`PropertyAccessor`/`PropertyService` | 1:1（ADAPT，receiver 语义见 D32 注） |
| reflect.ts:116-125 `Impl` 接口 | reflect.py:32-41 `Impl` 类 | 1:1 |
| reflect.ts:135-171 `handler.get` 陷阱 | reflect.py:82-127 `get`（无 Proxy，逻辑并入） | D25, D32 |
| reflect.ts:173-197 `handler.set` 陷阱 | reflect.py:141-174 `set` | D27, D32 |
| reflect.ts:199-205 `handler.has` 陷阱 | 无对应（疑似在 context.py，越出受审集） | 记录缺口 |
| reflect.ts:209-211 `store`/`props` | reflect.py:64-65（`StoreDict` 替代 `Object.create(null)`） | ADAPT |
| reflect.ts:213-223 构造器 + 四组 mixin | reflect.py:62-65 `__init__` + reflect.py:73-80 `setup_mixins` | D31, D34 |
| reflect.ts:233-235 `get(name, strict)` | reflect.py:82-127 `get(ctx, name, default, strict)` | D25 |
| reflect.ts:237-243 `_getImpl` | reflect.py:129-139 `_get_impl` | D26 |
| reflect.ts:254-265 `set` | reflect.py:141-174 `set` | D27 |
| reflect.ts:277-305 `provide` | reflect.py:176-253 `provide`（双签名 + allow_replace 为自发明） | D19, D28, D29 |
| reflect.ts:314-336 `notify` | reflect.py:255-295 `notify` | D30 |
| reflect.ts:345-353 `accessor` | reflect.py:298-320 `accessor` | 1:1（D32 标签引号差异） |
| reflect.ts:364-390 `mixin` | reflect.py:322-363 `mixin` | D31 |
| reflect.ts:398-400 `trace` | reflect.py:365-370 `trace` | 1:1 |
| reflect.ts:408-417 `bind` | reflect.py:372-389 `bind` | DEVIATION-PERMITTED（receiver 不追踪、无 construct 形态） |
| utils.ts:5-40 `DisposableList` | utils.py:220-299 `DisposableList`（registry.py:132 用裸 list 存 fibers，未复用） | ADAPT + D36 |
| utils.ts:43-47 `Tracker` | dict 约定（无类型） | ADAPT |
| utils.ts:50-73 `symbols` | utils.py:302-330 `Symbols`（字符串常量）；service.py:11-22 重复定义且取值不同 | ADAPT + D18 |
| utils.ts:79-89 `isConstructor` | 无直接对应（fiber.py:576-631 签名嗅探替代） | ADAPT |
| utils.ts:92-99 `joinPrototype` | 无对应 | ADAPT（未被任何被审路径使用） |
| utils.ts:102-104 `isObject` | utils.py:333-339 `is_object` | 1:1 |
| utils.ts:107-114 `getPropertyDescriptor` | 无对应 | ADAPT |
| utils.ts:117-125 `getTraceable` | utils.py:725-768 `get_traceable`（重构为 `_extend`/`TracedProxy` 分支） | ADAPT |
| utils.ts:128-140 `withProps` | utils.py:771-823 `with_props`/`_WithPropsProxy` | ADAPT |
| utils.ts:226-233 `createCallable` | 无对应（service.py:130-141 `__call__` 运行时分发替代） | ADAPT |
| utils.ts:240-281 `handleError`/`composeError` | utils.py:841-865 `compose_error`（不拼接栈，仅附属性） | ADAPT |
| utils.ts:284-287 `buildOuterStack` | utils.py:826-838 `build_outer_stack`（帧偏移口径不同） | ADAPT（诊断文本差异，归入 D32） |

## 差异

### D1: Inject.resolve 数组注入不覆盖已有键
- TS: `registry.ts:73-76`
  ```ts
  if (Array.isArray(inject)) {
    for (const name of inject) {
      result[name] = null
    }
  }
  ```
- PY: registry.py:32-39
  ```python
  if isinstance(inject_meta, (list, tuple, set)):
      for name in inject_meta:
          ...
          else:
              if name_str not in result:
                  result[name_str] = None
  ```
- 判定： MUST-FIX
- 影响: TS 数组条目无条件覆盖先前（含父级）配置为 null；PY 保留旧值，子类无法用数组形式清空父级 inject 配置。
- 建议修法： registry.py `Inject.resolve` 数组分支去掉 `if name_str not in result` 守卫，改为无条件 `result[name_str] = None`。

### D2: Inject.resolve 对象值被改写（发明 required 键）
- TS: `registry.ts:83-85`
  ```ts
  } else {
    for (const name of Object.keys(inject)) {
      result[name] = inject[name] ?? null
    }
  }
  ```
- PY: registry.py:41-48
  ```python
  for k, v in inject_meta.items():
      ...
      if isinstance(v, bool):
          result[k_str] = {"required": v}
      elif isinstance(v, dict):
          cfg = dict(v)
          cfg.setdefault("required", True)
          result[k_str] = cfg
  ```
- 判定： MUST-FIX
- 影响: TS 中对象值是任意 intercept config，仅 `?? null` 兜底；PY 注入 `{"required": ...}` 键（并在 fiber.py:147-157 反向剥除），用户 config `{"a":1}` 会变成 `{"a":1,"required":True}`，可被 intercept 消费方察觉。
- 建议修法： 移除 `required` 键注入，可选依赖改由独立通道表达（如名称后缀在 resolve 出口转 None 并另存可选集合），保持 `result[name] = v or None`。

### D3: Inject.resolve 新增 str/tuple/set 输入形态
- TS: `registry.ts:19` `export type Inject<M = Dict> = (keyof M)[] | { [K in keyof M]?: M[K] }`（仅数组/对象）
- PY: registry.py:32（接受 `list, tuple, set`）、registry.py:56-60（接受单个字符串）
- 判定： DEVIATION-PERMITTED
- 影响: 接受超集输入；set 无序导致注入顺序不稳定（与 D1 叠加时结果可能不可复现）。
- 建议修法： 保留宽容但至少将 set 归一为有序 list，或在文档标注为扩展形态。

### D4: @inject 方法装饰器：缺服务时抛错而非延迟执行
- TS: `registry.ts:48-55`
  ```ts
  decorator.addInitializer(function () {
    const property = this[symbols.tracker]?.property
    ;(this[symbols.initHooks] ??= []).push(() => {
      (this.ctx as Context).inject(inject, (ctx) => {
        return value.call(property ? withProps(this, { [property]: ctx }) : this)
      })
    })
  })
  ```
- PY: registry.py:98-105（包装器在调用时检查并抛错）；registry.py:325-341（另一套 `_init_hooks` 经 `ctx.inject` 延迟——两条路径并存）
  ```python
  if ctx and hasattr(ctx, "has"):
      for dep in target._cordis_inject.keys():
          if not ctx.has(dep):
              raise RuntimeError(f"Cannot call method ... without injected service ...")
      return target(self_or_ctx, *args, **kwargs)
  ```
- 判定： MUST-FIX
- 影响: TS 语义是"方法调用被推迟/重跑到服务可用"；PY 直接调用路径变为抛 `RuntimeError`，行为可察觉地不同，且与 registry.py:298-343 的延迟钩子机制互相冲突。
- 建议修法： 删除包装器的抛错门控，统一走 `_init_hooks` → `ctx.inject` 延迟路径；或包装器内部改为转发到 `ctx.inject`。

### D5: inject() 装饰器对非法 target 静默返回
- TS: `registry.ts:56-58`
  ```ts
  } else {
    throw new Error('@Inject() can only be used on class or class methods')
  }
  ```
- PY: registry.py:109 `return target`
- 判定： MUST-FIX
- 影响: 误用（如装饰普通函数/属性）在 TS 立即失败，PY 静默吞掉，配置错误不响（违反 "Misconfiguration fails loud"）。
- 建议修法： registry.py `inject.decorator` 末分支改为 `raise TypeError('@Inject() can only be used on class or class methods')`。

### D6: Plugin 基类自发明 id 字段并成为查找/卸载键
- TS: `registry.ts:100-111`
  ```ts
  export interface Base<T = any> {
    name?: string
    Config?: StandardSchemaV1<any, T>
    inject?: Inject
    provide?: string | string[]
    intercept?: Dict<boolean>
  }
  ```
- PY: plugin.py:10 `id: str = ""`；registry.py:200、registry.py:419 以 `plugin.id`/`fiber.plugin.id` 匹配查找与卸载
- 判定： MUST-FIX
- 影响: TS 无 `id` 概念；PY 使 `id` 成为运行时一等标识（get_fiber/unload_plugin 依赖它），与 TS 以 callback 为身份键（registry.ts:142 `callback: globalThis.Function` 注释 "registry identity key"）的设计相悖，出现第二身份体系。
- 建议修法： 卸载/查找统一走 `registry.delete(resolve(plugin))`；`id` 降级为纯展示元数据或移除。

### D7: runtime 名称/Config 采集的自发明回退
- TS: `registry.ts:324-328`
  ```ts
  let name = plugin.name
  if (name === 'apply') name = undefined
  runtime = { name, callback, fibers: new DisposableList(), Config: plugin.Config }
  ```
- PY: registry.py:261-268（`name or plugin.id`、dict 的 `name/id` 键、`Config or schema`、dict 的 `Config/schema` 键）+ registry.py:128-129（`PluginRuntime` 过滤 `<lambda>`/`anonymous*`）
- 判定： MUST-FIX（其中 `schema` 回退与 `id` 回退为无理由发明；lambda 过滤可记 DEVIATION-PERMITTED）
- 影响: TS 只认 `name` 与 `Config`；PY 引入 `schema` 作为 Config 别名、`id` 作为名称来源，fiber 侧（fiber.py:45）同样读 `schema`，形成 TS 不存在的配置键名。
- 建议修法： runtime 构造仅读 `plugin.name`（'apply' → None）与 `plugin.Config`；如需兼容 `schema`，集中在一处显式归一并记录。

### D8: 无效插件错误类型与消息文本不一致
- TS: `registry.ts:318-319`
  ```ts
  const callback = this.resolve(plugin)
  if (!callback) throw new Error('invalid plugin, expect function or object with an "apply" method, received ' + typeof plugin)
  ```
- PY: registry.py:250-252
  ```python
  if not callback:
      type_str = type(plugin_cls_or_instance).__name__
      raise ValueError(f'invalid plugin, expect function or object with an "apply" method, received {type_str}')
  ```
- 判定： MUST-FIX
- 影响: 错误类型 `Error`→`ValueError`（勉强可接受），但尾段文本 `typeof plugin`（`'number'`/`'undefined'`…）变成 Python 类型名（`'int'`/`'NoneType'`），消息文本不 1:1。
- 建议修法： 映射一张 JS typeof 对照（int/float→'number'，None→'undefined'，dict→'object'，str→'string'，bool→'boolean'）或在消息中并列两种描述，保持可定位性。

### D9: plugin() 自发明 parent_ctx 参数且 assertActive 弱化
- TS: `registry.ts:316-320`
  ```ts
  plugin(plugin: Plugin, config?: any, getOuterStack = buildOuterStack()) {
    const callback = this.resolve(plugin)
    ...
    this.ctx.fiber.assertActive()
  ```
- PY: registry.py:234（多出 `parent_ctx` 形参）、registry.py:241（`target_parent = parent_ctx or ...`）、registry.py:254-257（`assert_active(check_error=False)`）
- 判定： MUST-FIX
- 影响: TS 恒以当前上下文挂载且断言活动态（fiber 已处置即抛）；PY 允许调用方指定挂载父级，且 `check_error=False` 抑制错误态再抛（fiber.py:200-204 仅 uid 为 None 时抛）。
- 建议修法： 去掉 `parent_ctx` 形参（如需子上下文挂载应走 `ctx.extend().plugin(...)`）；`assert_active` 恢复默认严格口径。

### D10: registry.plugin 注册期自发明 'internal/plugin' 事件与失败回滚
- TS: `registry.ts:316-336`（整段无任何 emit）
- PY: registry.py:346-357
  ```python
  try:
      target_ctx.emit("internal/plugin", fiber)
  except Exception as e:
      runtime.remove_fiber(fiber)
      ...
      raise e
  ```
- 判定： MUST-FIX（无法在受审 TS 文件中找到对应发射点；fiber.ts 越出盲审范围，列入 PROBE）
- 影响: 每次注册插件多出一条 TS 基准中不存在的事件；监听方（如 Web GUI 事件流）会看到 TS 没有的信号。
- 建议修法： 对照 fiber.ts 确认归属；若无对应，删除该 emit 或改为 fiber 内部既有事件名。

### D11: delete() 异步 dispose 桥接（create_task 丢弃 + asyncio.run 换环）
- TS: `registry.ts:258-267`
  ```ts
  delete(plugin: Plugin) {
    ...
    this._internal.delete(key)
    for (const fiber of runtime.fibers) {
      fiber.dispose()
    }
    return runtime
  }
  ```
- PY: registry.py:216-222
  ```python
  try:
      loop = asyncio.get_running_loop()
      loop.create_task(fiber.dispose())
  except RuntimeError:
      asyncio.run(fiber.dispose())
  ```
- 判定： MUST-FIX
- 影响: TS 同步确定性处置全部 fiber；PY 变为 fire-and-forget（异常不可观测、顺序不保证），无 loop 时 `asyncio.run` 新建并关闭事件循环，fiber 内部已绑定其它 loop 的 future/task 会跨环崩溃。
- 建议修法： delete 保持在有 loop 时 `create_task` 但收集 task 供 await（或提供 `await delete_async`）；无 loop 场景禁止 `asyncio.run`，改为同步执行 disposer 链或将 API 标注为 async-only。

### D12: keys/values/entries/forEach 缺失
- TS: `registry.ts:269-291`
  ```ts
  keys() { return this._internal.keys() }
  values() { return this._internal.values() }
  entries() { return this._internal.entries() }
  forEach(callback) { return this._internal.forEach(callback) }
  ```
- PY: registry.py `RegistryService` 无对应成员（仅自发明 `list_fibers`，registry.py:225-232）
- 判定： MUST-FIX
- 影响: reflect.notify 的 TS 实现依赖 `registry.values()`（reflect.ts:316）；PY 侧 Map 式巡检 API 缺失，宿主插件（如 cordis-manager 的 `cordis_list_plugins`）无法按 TS 契约枚举运行时。
- 建议修法： 补 `keys()/values()/entries()/forEach()`，`notify` 改用 `values()` 而非 `list_fibers()`。

### D13: update_dependencies 自发明并行通知通道
- TS: `reflect.ts:314-336` `notify` 是唯一依赖重估通道（遍历 `registry.values()` → `_checkImpl` → `_refresh`）
- PY: registry.py:395-411 `update_dependencies`（再遍历 `_pending_fibers` 重复 `_checkImpl/_refresh`）
- 判定： MUST-FIX
- 影响: 与 reflect.notify 形成双通道，同一 fiber 可能被两处驱动，重入顺序与 `_updating` 重入守卫（registry.py:399-401）造成的静默跳过都是 TS 不存在的行为。
- 建议修法： 删除 `update_dependencies`，服务变更统一走 `reflect.notify`；`_pending_fibers` 若仅为内部记账应移入 Fiber 生命周期。

### D14: dict 插件的 inject 键被忽略
- TS: `registry.ts:330` `new Fiber(this.ctx, config, Inject.resolve(plugin.inject), ...)`（属性访问对普通对象同样生效）
- PY: registry.py:273 `raw_inject = getattr(plugin_cls_or_instance, "inject", None)`（dict 无属性；registry.py:186-187 已支持 dict 形态插件）
- 判定： MUST-FIX
- 影响: `{"inject": [...], "apply": fn}` 形态插件的依赖声明丢失，fiber 永不等待其依赖。
- 建议修法： registry.py 取 inject 时补 `isinstance(plugin, dict)` 分支读 `plugin.get("inject")`。

### D15: resolve() 接受任意 callable（宽于 TS）
- TS: `registry.ts:222-228`
  ```ts
  resolve(plugin: Plugin): Function | undefined {
    try {
      if (typeof plugin === 'function') return plugin
      if (isApplicable(plugin)) return plugin.apply
    } catch {}
  }
  ```
- PY: registry.py:188-189 `if callable(plugin): return plugin`（兜底分支，覆盖 functools.partial、可调用实例等）
- 判定： DEVIATION-PERMITTED
- 影响: 无 apply 的可调用对象在 TS 会被判无效插件并抛 D8 错误，PY 会接受；行为面更宽，错误变晚。
- 建议修法： 可保留，但建议收紧为"可调用且非类实例"或直接删除兜底，与 TS 对齐。

### D16: Plugin 构造契约：`__init__(config)` vs TS `new (ctx, config)`
- TS: `registry.ts:126-127`
  ```ts
  export interface Constructor<T = any> extends Base<T> {
    new (ctx: Context, config: T): any
  }
  ```
- PY: plugin.py:17-19
  ```python
  def __init__(self, config: Optional[Dict[str, Any]] = None):
      self.config: Dict[str, Any] = config or {}
      self.ctx: Optional[Any] = None
  ```
  另 registry.py:287-288 在挂载前 `plugin_inst.config.update(config)` 预合并原始 config；fiber.py:609-615 对 Plugin 子类以 `cls(config=...)` 构造后回填 `inst.ctx`。
- 判定： MUST-FIX
- 影响: TS 类插件构造即持 ctx（可在构造器内 `ctx.provide`）；PY 基类契约使构造期无 ctx，且原始 config 先于校验被合并进实例（fiber 随后又以校验后 config 覆写，fiber.py:642-643），双写路径语义混乱。
- 建议修法： `Plugin.__init__` 改为 `__init__(self, ctx=None, config=None)`；删除 registry.py:287-288 的预合并，让 fiber 统一走 `_resolve_config` 后注入。

### D17: Plugin.teardown 自发明生命周期钩子
- TS: `registry.ts:100-111` `Plugin.Base` 无 teardown；TS 卸载契约 = apply 返回 disposer / effect（registry.ts:131-133 `apply(ctx, config): any`）
- PY: plugin.py:28-32 `teardown()`；fiber.py:724-725 将其注册为 disposer
- 判定： DEVIATION-PERMITTED
- 影响: 纯附加钩子，不破坏 TS 语义（多一条可被调用的清理路径），但属自发明 API。
- 建议修法： 保留需在框架文档标注为 portable 扩展；避免在 1:1 兼容层文档中暴露。

### D18: 双符号词表（ServiceSymbols 与 utils.Symbols 取值不一致）
- TS: `service.ts:13-15`
  ```ts
  static readonly init: unique symbol = symbols.init
  static readonly check: unique symbol = symbols.check
  ```
  （均源于 utils.ts:66-68 的 `Symbol.for('cordis.*')`，全局唯一）
- PY: service.py:13-19 `ServiceSymbols.init = "symbols.init"` 等 vs utils.py:321-327 `Symbols.init = "cordis.init"` 等
- 判定： MUST-FIX
- 影响: 两套字符串常量不相等：fiber.py:655 以 `"cordis.init"` 查 init 钩子，而 Service 子类若按 service.py 侧常量定义符号方法（`hasattr(self, "symbols.check"`，service.py:58）永不命中——TS 的 `this[symbols.check]` 主路径在 PY 实际失效（见 D19）。
- 建议修法： 删除 `ServiceSymbols`，`Service` 直接引用 `dsh.cordis.utils.symbols`；Service 类属性名避免与成员名冲突（改用模块级常量或 `__slots__` 外挂）。

### D19: Service check 谓词解析路径失效 + allow_replace 自发明
- TS: `service.ts:57` `self.ctx.reflect.provide(name, self, this[symbols.check])`（构造时即以符号方法为可用性谓词传入 provide）
- PY: service.py:57-63
  ```python
  if hasattr(self, ServiceSymbols.check) and callable(getattr(self, ServiceSymbols.check)):
      check_fn = getattr(self, ServiceSymbols.check)
  elif hasattr(self, "_check_availability") and callable(...):
      check_fn = getattr(self, "_check_availability")
  elif hasattr(self, "check") and callable(getattr(self, "check")):
      check_fn = getattr(self, "check")
  ```
  以及 service.py:45 `allow_replace: bool = False` 形参（TS 无此概念）
- 判定： MUST-FIX
- 影响: `ServiceSymbols.check == "symbols.check"`，`hasattr(self, "symbols.check")` 几乎恒 False → TS 主路径死亡；发明 `_check_availability` 别名；`check` 分支因类属性 `Service.check = "symbols.check"`（非 callable）恒 False，仅当子类覆写 `check()` 时生效——子类覆写同时遮蔽常量，易踩坑。
- 建议修法： 统一符号常量（见 D18）后按 `getattr(self, symbols.check, None)` 解析；删除 `allow_replace`（TS 重复注册一律抛，见 D28）。

### D20: Service 注册回退 ctx.set_service 路径
- TS: `service.ts:57` `self.ctx.reflect.provide(name, self, this[symbols.check])`（唯一路径，经 `fiber.effect` 获得生命周期所有权）
- PY: service.py:65-68
  ```python
  if hasattr(self.ctx, "provide"):
      self.ctx.provide(self.name, self, check=check_fn, allow_replace=allow_replace)
  elif hasattr(self.ctx, "set_service"):
      self.ctx.set_service(self.name, self, check=check_fn, allow_replace=allow_replace)
  ```
- 判定： MUST-FIX
- 影响: `set_service` 路径绕过 `fiber.effect` 所有权（服务不随 fiber 卸载而注销），且 allow_replace 透传弱化重复检测（reflect.py:213）。
- 建议修法： 删除 set_service 回退；`ctx.provide` 缺失视为上下文实现错误直接抛。

### D21: Service._extend 用 copy.copy 快照替代原型活链 + 恒等捷径
- TS: `service.ts:65-73`
  ```ts
  protected [symbols.extend](props?: any) {
    let self: any
    if (this[Service.invoke]) {
      self = createCallable(this.name, this, this[symbols.tracker])
    } else {
      self = Object.create(this)
    }
    return Object.assign(self, props)
  }
  ```
- PY: service.py:117-128
  ```python
  if (target_ctx is self.ctx or target_ctx is None) and not props:
      return self
  ...
  extended = copy.copy(self)
  ```
- 判定： MUST-FIX
- 影响: TS 派生对象经原型链读原实例（原实例后续变更对派生可见）；PY `copy.copy` 是独立快照（后续变更不可见）；且"同 ctx 且无 props 返回 self"的捷径使 TS 每次派生都产生新对象的恒等语义消失（`get_traceable` 每次 wrap 的新视图 vs 复用同一实例）。
- 建议修法： 以轻量代理（`__getattr__` 回退到原实例）模拟 `Object.create(this)`；移除恒等捷径。

### D22: resolve_intercept_config 仅合并 dict
- TS: `service.ts:97-101`
  ```ts
  if (this['Config']?.merge) {
    return this['Config'].merge(...configs)
  } else {
    return Object.assign({}, ...configs)
  }
  ```
- PY: service.py:99-103
  ```python
  res: Dict[str, Any] = {}
  for cfg in configs:
      if isinstance(cfg, dict):
          res.update(cfg)
  return res
  ```
- 判定： DEVIATION-PERMITTED
- 影响: 标量/数组型 intercept config 在 TS 会整体覆盖合并结果，PY 被静默丢弃；常规 dict 配置下等价。
- 建议修法： 非 dict 项按 TS `Object.assign` 语义整体写入（如记录到 `_scalar` 或最后生效值），或明确断言 config 必须为 dict。

### D23: Service 默认名类名推导 + provide 列表形态
- TS: `service.ts:43`
  ```ts
  name ??= this.constructor['provide'] as string
  ```
  （再无兜底；`provide` 元数据为 `string | string[]`，Service 构造器只按字符串消费）
- PY: service.py:47-55
  ```python
  resolved_name = name or getattr(self, "provide", None) or getattr(self, "provide_name", None) or getattr(self, "name", None)
  if isinstance(resolved_name, (list, tuple)) and resolved_name:
      resolved_name = resolved_name[0]
  if not resolved_name:
      cls_name = self.__class__.__name__.lower()
      if cls_name.endswith("service"):
          cls_name = cls_name[:-7]
      resolved_name = cls_name
  ```
- 判定： DEVIATION-PERMITTED（`provide_name` 别名与类名推导为发明；list 取首元素为宽容扩展）
- 影响: TS 中无 provide 的服务名落到 `props["undefined"]` 一类异常键（快速暴露）；PY 自动推导出小写类名，错误被掩盖为"能用的默认名"。
- 建议修法： 保留推导可作为 DEVIATION-PERMITTED 记录；建议至少在推导命中时输出一次性告警。

### D24: Symbol.hasInstance 语义缺失
- TS: `service.ts:104-114`
  ```ts
  static [Symbol.hasInstance](instance: any) {
    if (!instance) return false
    let constructor = instance.constructor
    while (constructor) {
      constructor = constructor.prototype?.constructor
      if (constructor === this) return true
      ...
  ```
- PY: service.py 无对应（`isinstance` 走默认 MRO）
- 判定： DEVIATION-PERMITTED
- 影响: TS 用它穿透 createCallable 代理做 instanceof；PY 未采用构造期代理（`__call__` 方案），普通实例 isinstance 天然可用，语义近似等价；对 TracedProxy（utils.py:594）`isinstance(x, Service)` 会失败——get_traceable 已在 Service 分支前拦截（utils.py:754-756），实际影响小。
- 建议修法： 若未来引入代理化 Service，补 `__instancecheck__` 元类；当前可记录许可。

### D25: proxy get 契约缺失：不可解析返回 None 而非抛错；保留名门控与多级回退
- TS: `reflect.ts:144`、`reflect.ts:152-166`
  ```ts
  const error = new Error(`cannot get property "${prop}" without inject`)
  ...
  if (!ctx.fiber.runtime) return ctx.reflect.get(prop, false)
  return ctx.events.waterfall('internal/get', ctx, prop, error, () => {
    ...
    if (prop in fiber.inject) {
      error.message = `cannot get required service "${prop}" in inactive context`
      throw error
    }
    if (!fiber.runtime) throw error
    ...
  ```
- PY: reflect.py:86（保留名/下划线/纯数字直接 `return default`）、reflect.py:106-120（`ctx._services` 直查 + `ctx.get_service` 父链回退，均为发明）、reflect.py:122 `return default`（永不抛）；reflect.py:92/124 错误载体仅 `KeyError/RuntimeError(f"cannot get property '{name}'")`，无 `without inject` 后缀，且 `cannot get required service ... in inactive context` 消息整体缺失
- 判定： MUST-FIX
- 影响: TS 上未注入即读服务是硬错误（增强栈后抛出）；PY 反射层静默返回 None/default，缺依赖被推迟成下游 NoneType 崩溃；inactive 上下文的专用错误文本丢失。
- 建议修法： `ReflectService.get` 保持宽松（与 TS `get` 一致，返回 undefined），但将"不可解析即抛"的契约实装到 Context 属性访问入口（与 context.py 对齐），并恢复两条错误消息原文。

### D26: _get_impl 的 name 回退键与 strict 松弛
- TS: `reflect.ts:237-243`
  ```ts
  _getImpl(name: string, strict = true) {
    const key = this.ctx[symbols.isolate][name]
    const impl = key && this.store[key]
    if (!impl) return
    if (strict && impl.fiber.state !== FiberState.ACTIVE) return
    return impl
  }
  ```
- PY: reflect.py:131-138
  ```python
  key = get_isolate_symbol(ctx, name) or name
  impl = self.store.get(key) or self.store.get(name)
  ...
  if strict and impl.fiber is not None and getattr(impl.fiber, "plugin", None) is not None:
      if impl.fiber.state != FiberState.ACTIVE:
          return None
  ```
- 判定： MUST-FIX
- 影响: ① TS 严格按隔离符号取 store，无符号即无实现；PY 回退按裸名查 store，隔离错位时可能读到其他作用域实现。② TS strict 无条件要求提供方 fiber ACTIVE；PY 对 `fiber.plugin is None` 的实现（根 fiber、类插件实例化前的 fiber）跳过 ACTIVE 检查，PENDING 阶段的提供可能提前可见。
- 建议修法： 删除 `or name` 回退；strict 判定去掉 `plugin is not None` 条件，恢复 `state != ACTIVE → None`。

### D27: set 缺少 !def 且非 running 上下文的直写分支 + 镜像副作用
- TS: `reflect.ts:179-183`
  ```ts
  const def = target.reflect.props[prop]
  if (!def) {
    if (!ctx.fiber.runtime) return Reflect.set(target, prop, value, ctx)
    throw enhanceError(error)
  }
  ```
- PY: reflect.py:152-174（`_do_set` 无 props 判定，未提供即抛）；reflect.py:165-168 额外 `target._services[name] = value; setattr(target, name, value)` 双写
- 判定： MUST-FIX（缺分支）；镜像双写记 DEVIATION-PERMITTED（作为无 Proxy 环境的等价机制，但形成双份事实源）
- 影响: 根/非运行态上下文上 `ctx.someProp = x` 在 TS 直写成功，PY 抛 `cannot set property ... without provide`；运行态上下文上 PY 在 store 之外再写 `_services` 与实例属性，与 `impl.value` 可能失步。
- 建议修法： `_do_set` 前补 `def` 缺失 + `fiber.runtime` 为空的直写分支；镜像写收敛为单一出口（统一由 store 读取，取消 `_services` 双写）。

### D28: provide 重复注册宽容（allow_replace / 同值放行）
- TS: `reflect.ts:288-291`
  ```ts
  const impl: Impl = { name, value, fiber: this.ctx.fiber, check }
  if (this.store[key]) {
    throw new Error(`service "${name}" has been registered at <${this.store[key].fiber.name}>`)
  }
  ```
- PY: reflect.py:212-218
  ```python
  if not allow_replace and key in self.store
  ```
  （后续分支：同值放行、allow_replace=True 静默替换——TS 一律抛错）
- 判定： MUST-FIX
- 影响: 重复提供同一服务在 TS 立即失败并报出首次注册位置；PY 可静默替换/放行，掩盖宿主配置错误（与 G6 的 set_service allow_replace 相互放大）。
- 建议修法： 删除 allow_replace 与同值放行，重复注册抛 `service "name" has been registered at <fiber>`。

### D29: provide 双签名自发明 + isolate key 协议漂移
- TS: `reflect.ts:277-305` `provide(name, value, check?)`（固定三参，isolate key 由 `ctx[symbols.isolate][name]` 推导）
- PY: reflect.py:176-211（`(ctx, name, value, check=None, ...)` 四参起步 + `get_isolate_symbol(ctx, name) or name`；与 context.py 的 `_isolated_keys` dict 协议并存两套键规则）
- 判定： MUST-FIX（签名膨胀记录为 ADAPT 倾向；键协议与 G6 D12 同源）
- 影响: 同一隔离语义在 reflect/context 两处实现不一致（裸名 vs isolate key），跨路径读取可能命中不同 store 条目。
- 建议修法： 收敛单一 isolate key 协议函数（读 `_isolated_keys`），provide/get/set 全部经它取键。

### D30: notify 事件名/payload 与过滤通道差异
- TS: `reflect.ts:314-336`（遍历 `registry.values()` → 每实现 `fiber._checkImpl(name)` + `fiber._refresh()`，并 emit `internal/update`）
- PY: reflect.py:255-295（经 `list_fibers()` + 批量 notify；事件 payload 与 TS 不同，且过滤/去重逻辑为发明）
- 判定： MUST-FIX（与 D12/D13 同源；notify 应回归 TS 单通道语义）
- 影响: 依赖重估的触发面与顺序不同，可能出现 TS 不会有的重复刷新或漏刷新。
- 建议修法： notify 按 TS 逐实现 `_checkImpl → _refresh`，删除批量与去重分支。

### D31: mixin/构造器 mixin 装配差异（setup_mixins 自发明集合）
- TS: `reflect.ts:213-223`（构造器按固定四组混入：events、timer、life、model）
- PY: reflect.py:73-80（`setup_mixins` 按 `hasattr` 逐个尝试，集合可扩展）
- 判定： DEVIATION-PERMITTED
- 影响: 混入名单可漂移；缺一混入时 TS 编译期可见（类型），PY 运行期静默。
- 建议修法： 固定名单常量化并在缺混入时告警。

### D32: receiver/withProps/caller_ctx 协议为全库自发明约定
- TS: reflect.ts:333（`this.ctx.events.emit(self, ...)` 首参 thisArg）与 handler 的 receiver 转发
- PY: reflect.py 与 events.py 的 `caller_ctx` kwarg + 属性嗅探（与 G3 D8、G6 D18 同源）
- 判定： DEVIATION-PERMITTED（协议级替代，需在跨文件审计中统一裁决）
- 影响: 跨实现移植监听器需注意签名差异；库内自洽。
- 建议修法： 维持约定，在 events/reflect/context 三处文档化同一协议。

### D33: trace/accessor 的标签文本差异（'ctx.trace' vs 引号风格）
- TS: `reflect.ts:398-400` label 常量 `ctx.trace`
- PY: reflect.py:365-370 同名 label，但 effect 标签拼接风格略异（引号/括号）
- 判定： DEVIATION-PERMITTED（诊断文本）
- 影响与建议： 仅诊断可读性；统一标签模板即可。

### D34: tracker 元数据缺失（registry/reflect/service 构造器）
- TS: registry.ts:199-204、reflect.ts:216-222、service.ts:46-49 均定义 `symbols.tracker` 属性元数据
- PY: 无对应（G3 D14 同源）
- 判定： DEVIATION-PERMITTED（tracker 消费机制未移植）
- 影响: 仅诊断与 withProps 绑定面。
- 建议修法： 与 G1 D15 的 _internals 迁移一并处理。

### D35: Plugin.Transform 缺失
- TS: registry.ts:113-118（`Plugin.Transform`：注册前变换插件形态的扩展点）
- PY: 无对应
- 判定： DEVIATION-PERMITTED（若宿主生态未用则影响小；cordis-manager 等宿主插件若依赖需补）
- 影响与建议： 检索 dsh/ 是否有 Transform 语义需求，无则记录裁剪决定。

### D36: DisposableList 未被 registry 复用 + @inject 的 property 绑定缺失
- TS: registry.ts:141（`runtime.fibers = new DisposableList()`）与 registry.ts:48-55（withProps property 绑定）
- PY: registry.py:132（裸 list）+ 装饰器无 property 概念
- 判定： DEVIATION-PERMITTED
- 影响: fiber 集合的清理语义弱化（见 G2 D11 的 dispose 桥接问题）；方法内 `this` 上下文注入缺失。
- 建议修法： registry 复用 DisposableList；property 绑定随 D4 修复一并设计。

## 测试缺口

### T1: Inject.resolve 数组覆盖语义（D1）——子类数组注入清空父级配置
### T2: @inject 缺服务延迟执行而非抛错（D4）——initHooks 重跑路径
### T3: 非法装饰目标抛错（D5）——`@inject()` 装饰普通函数
### T4: invalid plugin 错误消息文本（D8）——各 typeof 形态
### T5: delete() 同步确定性 dispose（D11）——fiber 清理在 delete 返回前的可观察效果
### T6: registry 遍历 API（D12）——keys/values/entries/forEach 契约
### T7: 重复 provide 抛错与注册位置消息（D28）——`has been registered at <fiber>`
### T8: set 直写分支（D27）——根上下文属性赋值成功
### T9: Service 符号 check 谓词主路径（D18/D19）——`symbols.check` 命中
### T10: _extend 原型链可见性（D21）——原实例后续变更对派生可见

## PROBE 候选

- D10: 注册插件时挂监听 `internal/plugin`，探测注册期 emit 的实际触发与 TS fiber.ts:284-287 的 emitPluginDisposed 是否同源（跨文件归属裁决）。
- D11: 无 loop 环境调用 `registry.delete`，观察 `asyncio.run` 新建 loop 的清理是否完成、fiber 内已绑定其他 loop 的对象是否报错。
- D28: 重复 provide 同名服务的现行行为（静默替换 or 抛错），钉死现版语义后定修复方案。
