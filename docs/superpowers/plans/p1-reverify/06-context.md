# G6-context 盲审报告

**审计范围声明**：TS 基线实际为 146 行（任务书称 137 行，以实读为准）；引用行号均来自实读源码。依据仅来自 `reference/vendor/cordis/src/context.ts` 与 `dsh/cordis/context.py`（另以 `dsh/cordis/reflect.py`、`dsh/cordis/fiber.py`、`dsh/cordis/utils.py`、`tests/1to1/cordis/test_context_parity.py` 的只读检索作为 Python 侧内部一致性佐证，未读 docs/，未运行任何命令写入）。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态（1:1 / ADAPT / D#） |
|---|---|---|
| `interface Context` (context.ts:16-33) | 无类型层对应（docstring, context.py:20-24） | 类型层，N/A |
| `Context.effect` static symbol (44) | `effect_symbol` (context.py:27) | ADAPT（symbol→str） |
| `Context.filter` static symbol (46) | `filter_symbol` (context.py:28) | ADAPT |
| `Context.isolate` static symbol (48) | `isolate_symbol` (29) + `isolate` (31) 双份 | ADAPT（冗余重复） |
| `Context.intercept` static symbol (50) | `intercept_symbol` (30) + `intercept` (32) 双份 | ADAPT（冗余重复） |
| `Context.is` + static 品牌块 (61-68) | `is_` (34-48) | D1 |
| —（TS 无） | `is_context` 别名 (50-53) | 自发明别名，DEVIATION-PERMITTED |
| `constructor` (71-84) | `__init__` (55-95) | ADAPT + D2/D14/D15 |
| `[nodejs.util.inspect.custom]` (86-88) | **缺失**（无 `__repr__`） | D7 |
| `extend` (99-107) | `extend` (315-325) | D3/D4 |
| `isolate` (121-125) | `isolate` (327-344) | D4/D5/D6 |
| `intercept` (141-145) | `intercept` (346-352) | D4 |
| —（TS 由 `Proxy(ReflectService.handler)` 承担，74） | `__getattr__` (400-457) | ADAPT（机制）+ D9/D10/D11/D12 |
| —（TS 经 handler 的 symbol 键访问） | `__getitem__` (459-464) | ADAPT |
| —（TS 无） | `IsolatedKeysView` (467-470) | 自发明 shim，DEVIATION-PERMITTED |
| —（TS 无对应面，parent 归 fiber 管） | `parent` property + setter (97-103) | 自发明，DEVIATION-PERMITTED |
| `root` own property (75) | `root` property 走父链 (105-110) | ADAPT（结果等价） |
| `events` 服务 (26, 80) | `events` property (112-114) | ADAPT |
| —（TS: reflect.ts 的 provide 混入，基线外） | `set_service` (116-131) | D13 |
| `ctx.provide`（interface 30 文档，实现在基线外） | `provide` (133-137) | ADAPT |
| —（基线外） | `get_service` (139-149) | 自发明，DEVIATION-PERMITTED |
| `ctx.get`（interface 30 文档） | `get` (151-155) | ADAPT |
| `ctx[key] = val`（handler.set，基线外） | `set` (157-161) | ADAPT |
| `name in ctx`（handler.has，基线外） | `has` (163-179) | 基线外，DEVIATION-PERMITTED |
| `ctx.effect`（fiber 混入，基线外） | `effect` (181-188) | ADAPT + D16 死守卫 |
| —（基线外） | `disposable` (190-194) | 基线外，DEVIATION-PERMITTED |
| `ctx.on/emit/...`（events 混入，interface 26 文档，基线外） | `on` (196) / `once` (210) / `emit` (224) / `emit_async` (228) / `waterfall` (232) / `waterfall_sync` (236) / `parallel` (240) / `serial` (244) / `bail` (248) / `bail_sync` (252) | 基线外，D18（caller_ctx 注入） |
| `ctx.plugin`（interface 32 文档） | `plugin` (256-262) | ADAPT |
| `ctx.inject`（interface 32 文档） | `inject` (264-269) | ADAPT |
| —（TS 无） | `unload_plugin` (271-280) | D17 |
| —（TS 无） | `list_plugins` (282-298) | 自发明，DEVIATION-PERMITTED |
| `baseUrl` own property (24, 76) | `baseUrl` property (300-313) | D14 |
| —（TS 生命周期在 fiber，基线外） | `teardown`/`dispose` (354-368) | D16 |
| —（timer 混入，基线外） | `timeout`/`interval`/`throttle`/`debounce` (370-392)、`setTimeout`/`setInterval` (394-398) | 基线外，D18 |

## 差异

### D1: `Context.is_` 增加鸭子类型兜底，破坏品牌判定唯一性
- TS: `reference/vendor/cordis/src/context.ts:61-67`
```ts
static is(value: any): value is Context {
    return !!value?.[Context.is as any]
}
static {
    Context.is[Symbol.toPrimitive] = () => Symbol.for('cordis.is')
    Context.prototype[Context.is as any] = true
}
```
- PY: `dsh/cordis/context.py:42-48`
```python
if getattr(value, "__cordis_context_brand__", None) == "cordis.v1.context":
    return True
return isinstance(value, Context) or (
    hasattr(value, "registry")
    and hasattr(value, "reflect")
    and hasattr(value, "extend")
)
```
- 判定： MUST-FIX
- 影响： TS 明确以全局 symbol 品牌为唯一判据（注释 54-57 行言明"rather than by `instanceof`"），Python 兜底使任意携带 registry/reflect/extend 三属性的普通对象被误判为 Context，`is_` 失去窄化可信度。
- 建议修法： 删除 `context.py:44-48` 的 `isinstance`+`hasattr` 兜底，仅保留品牌字符串判定（brand 机制本身可保留为 ADAPT）。

### D2: 根上下文构造额外清除 `_effect_metas`，TS 仅清 `_disposables`
- TS: `reference/vendor/cordis/src/context.ts:82`
```ts
this.fiber._disposables.clear()
return self
```
- PY: `dsh/cordis/context.py:94-95`
```python
self.fiber._disposables.clear()
self.fiber._effect_metas.clear()
```
- 判定： MUST-FIX
- 影响： TS 的 EffectMeta 诊断树（context.ts:43-44 `Context.effect` 符号注释）在构造后保留；Python 侧在根构造时即抹除，effect 诊断元数据（fiber.py:130/359/476 维护）提前丢失，行为可察觉（`list` 诊断输出为空）。
- 建议修法： 删除 `context.py:95` 的 `self.fiber._effect_metas.clear()`，与 TS 82 行保持只清 `_disposables`。

### D3: `extend` 丢失 `symbols.shadow` 传播与 `getTraceable` 原型溯源
- TS: `reference/vendor/cordis/src/context.ts:100-106`
```ts
const shadow = Reflect.getOwnPropertyDescriptor(this, symbols.shadow)?.value
const self = Object.create(getTraceable(this, this))
for (const prop of Reflect.ownKeys(meta)) {
  Object.defineProperty(self, prop, Reflect.getOwnPropertyDescriptor(meta, prop)!)
}
if (!shadow) return self
return Object.assign(Object.create(self), { [symbols.shadow]: shadow })
```
- PY: `dsh/cordis/context.py:315-325`（构造子 Context、复制两个 dict、`setattr` meta，无任何 shadow 读取/透传，无 getTraceable）
- 判定： MUST-FIX
- 影响： TS extend 必须沿子链保留 shadow 标记；Python 仅在 `RESERVED_ATTRS`（context.py:403）与 `utils.py:739-752`、`context.py:422` 中**读取** `_shadow/_shadow_fiber/is_shadow`，全库无写入方——机制休眠但缺失，一旦移植 shadow 生产方即出现行为缺口。
- 建议修法： 在 `extend` 中透传父的 shadow 标记（如 `child._shadow = getattr(self, "_shadow", None)` 语义），并对齐 `getTraceable`（经 `utils.get_traceable`）。

### D4: isolate/intercept 用 dict 快照替代 TS 的原型链 shadow map
- TS: `reference/vendor/cordis/src/context.ts:122-124`
```ts
isolate(name: string, label?: symbol) {
    const shadow = Object.create(this[symbols.isolate])
    shadow[name] = label ?? Symbol(name)
    return this.extend({ [symbols.isolate]: shadow })
}
```
（intercept 同构：context.ts:142-144 `Object.create(this[symbols.intercept])`）
- PY: `dsh/cordis/context.py:320-321, 331, 343`
```python
child._isolated_keys = dict(self._isolated_keys)
child._intercept_map = dict(self._intercept_map)
...
shadow = dict(self._isolated_keys)
...
child._isolated_keys = shadow
```
- 判定： DEVIATION-PERMITTED
- 影响： TS 子 map 经原型链继承父 map（父 map 后续变更对子可见）；Python 为创建时值拷贝。由于 TS 公共 API 从不原地改写父 map，经公共 API 不可区分；仅直接改写 map 时可见（见 PROBE）。
- 建议修法： 可保留，但建议注释声明"父 map 视为不可变"前提；或改为链式委托视图。

### D5: `isolate` 自发明多键/字典/`keys=` 扩展 API，list 分支发明"共享 label 组隔离"
- TS: `reference/vendor/cordis/src/context.ts:121`
```ts
isolate(name: string, label?: symbol) {
```
- PY: `dsh/cordis/context.py:327, 335-340`
```python
def isolate(self, name_or_keys: Union[str, List[str], Dict[str, Any]] = None, label: Any = None, keys: Optional[List[str]] = None) -> "Context":
    ...
    elif isinstance(target_keys, list):
        for k in target_keys:
            shadow[k] = label or object()
    elif isinstance(target_keys, dict):
        for k, v in target_keys.items():
            shadow[k] = v
```
- 判定： MUST-FIX
- 影响： TS 仅支持单 `(name, label?)`；Python 的 list 分支让多个服务共享同一 label（TS 无法表达的"组隔离"语义），dict 分支引入父 map 批量预填。两条许可偏离均不强制此扩展。
- 建议修法： 收敛签名为 `isolate(name: str, label=None)`；如 harness 其余调用点确需多键，拆分为多次 `isolate` 调用并逐点改造。

### D6: label 默认值用真值判断 `label or object()`，TS 为 `label ?? Symbol(name)`
- TS: `reference/vendor/cordis/src/context.ts:123`
```ts
shadow[name] = label ?? Symbol(name)
```
- PY: `dsh/cordis/context.py:334`
```python
shadow[target_keys] = label or object()
```
- 判定： DEVIATION-PERMITTED
- 影响： 传入 falsy label（`0`/`""`/`False`）时 Python 静默替换为新对象而非沿用调用者标签，极端调用下两个 isolate 意外不 join。
- 建议修法： 改为 `label if label is not None else object()`。

### D7: 缺失 `inspect.custom` 调试表示
- TS: `reference/vendor/cordis/src/context.ts:86-88`
```ts
[Symbol.for('nodejs.util.inspect.custom')]() {
    return `Context <${this.fiber.name}>`
}
```
- PY: 无对应（`context.py` 无 `__repr__`/`__str__`）。
- 判定： MUST-FIX（缺失行为；严重度低）
- 影响： 调试/日志中 Context 无法按 `Context <fiber 名>` 识别。
- 建议修法： 在 `Context` 添加 `__repr__` 返回 `f"Context <{self.fiber.name}>"`。

### D8: TS Proxy 由 `__getattr__` 模拟（机制层）
- TS: `reference/vendor/cordis/src/context.ts:74`
```ts
const self = new Proxy<this>(this, ReflectService.handler)
```
- PY: `dsh/cordis/context.py:400-457`（`__getattr__` 内联保留名单、accessor、strict 解析、兜底栈）
- 判定： ADAPT
- 说明： Python 无 Proxy，`__getattr__` 是语言必需的等价改写（超出两条许可清单字面，但属同类必要性，予以记录许可）。其内部分支的正确性见 D9-D12。

### D9: strict 门控要求 `fiber.runtime is not None`，根上下文绕过 strict 注入，错误面分裂
- TS: `reference/vendor/cordis/src/context.ts:74`（handler 对所有上下文统一生效；具体 strict 文本在基线外 reflect.ts）
- PY: `dsh/cordis/context.py:418`
```python
if getattr(self, "strict_inject", True) and getattr(self, "fiber", None) and getattr(self.fiber, "runtime", None) is not None:
```
而根 fiber 构造为 `context.py:89` `Fiber(self, None, config={}, runtime=None)` → 根上 strict 分支永不进入，未声明属性最终走 `context.py:457` `raise AttributeError(f"Context object has no attribute or service '{name}'")`；插件子上下文则走 `context.py:419` `RuntimeError(f"cannot get property '{name}' without inject")`（tests/1to1/cordis/test_context_parity.py:136 钉测了后者）。
- 判定： MUST-FIX
- 影响： 同一"未注入访问"在根与插件上下文抛不同异常类型/文本，严格模式在根上下文事实失效。
- 建议修法： 去除 `runtime is not None` 前置条件（或让根 fiber 具备等价 active 态），统一错误为 `cannot get property '{name}' without inject`。

### D10: `internal/get` 自发明内部事件且存在双派发点；accessor 默认错误类型/文本互相矛盾
- TS: `reference/vendor/cordis/src/context.ts` 全文无该扩展点（TS 对应逻辑在基线外 reflect.ts）。
- PY: `dsh/cordis/context.py:443-444`
```python
if hasattr(self, "waterfall_sync"):
    return self.waterfall_sync("internal/get", self, name, err, _resolve_strict)
```
与 `dsh/cordis/reflect.py:125-126` 重复派发；且 accessor 错误：`context.py:414` `RuntimeError(f"cannot get property '{name}' without inject")` vs `reflect.py:92` `KeyError(f"cannot get property '{name}'")`。
- 判定： MUST-FIX（一致性）
- 影响： 同一属性访问可能经两条不同派发路径（`ctx.get` 走 reflect.get，属性访问走 `__getattr__`），监听者行为依路径而异；accessor 失败异常类型分裂。
- 建议修法： 收敛为单一派发点（建议只留 reflect.py 一处），统一 accessor 错误类型与文本后再与 TS 基线外 reflect.ts 对表。

### D11: `__getattr__` 尾部多级兜底栈削弱 strict 与隔离语义
- TS: `reference/vendor/cordis/src/context.ts:74`（handler 单一解析路径，无多级回退；回退细节在基线外）
- PY: `dsh/cordis/context.py:447-456`
```python
if name in self._services:
    ...return get_traceable(self, self._services[name])
if hasattr(self, "reflect"):
    val = self.reflect.get(self, name, default=None, strict=False)
    ...
if self._parent and name not in self._isolated_keys and hasattr(self._parent, name):
    return getattr(self._parent, name)
```
- 判定： MUST-FIX
- 影响： strict 分支未命中时（见 D9 场景）逐级绕过 fiber 链解析协议；父链 `getattr` 回溯仅检查子级 isolate 键，不校验父侧隔离一致性，可跨越隔离边界读到服务。
- 建议修法： 非 strict 路径统一收口到 reflect 层的单一解析函数，删除 `context.py:447-456` 的散装兜底。

### D12: strict 解析中 store 查找使用裸 `name`，忽略 isolate key；与 reflect 层查找协议不一致
- TS: `reference/vendor/cordis/src/context.ts`（store 协议在基线外 reflect.ts，无法直接对表）
- PY: `dsh/cordis/context.py:423-425`
```python
key = getattr(self, "_isolated_keys", {}).get(name, name)
while curr_fiber is not None:
    impl = getattr(curr_fiber, "store", {}).get(name) if getattr(curr_fiber, "store", None) else None
```
`key` 仅用于 437-439 行父边界比较，从不参与 store 查找；而 `dsh/cordis/reflect.py:130-132` 用 `get_isolate_symbol(ctx, name) or name` 查 store。两协议并存。
- 判定： MUST-FIX（库内不一致；对 TS 的最终对表需 reflect.ts，见 PROBE）
- 影响： isolate 子上下文中属性访问与 `ctx.get` 可能命中不同 store 条目，隔离语义依访问路径而异。
- 建议修法： `context.py:425` 改为按 `key` 查找（与 reflect.py `_get_impl` 同协议），或直接复用 reflect 层解析。

### D13: `set_service` 为自发明写入口：root 定向写、check 自动发现、`allow_replace=True`
- TS: `reference/vendor/cordis/src/context.ts` 无该方法（TS 对应 `ctx.provide` 在基线外 reflect.ts）。
- PY: `dsh/cordis/context.py:120-131`
```python
target = self if name in self._isolated_keys else self.root
target._services[name] = service_instance
setattr(target, name, service_instance)
...
chk = service_instance._check_availability  # 自动发现（126-129）
self.reflect.provide(self, name, service_instance, check=chk, allow_replace=True)
```
- 判定： DEVIATION-PERMITTED（harness 约定使用 `ctx.set_service`，但写目标为 root、且绕过 isolate 的 reflect 键协议，需与 reflect.ts 对表后复核；当前影响限于库内）
- 影响： 隔离子上下文调用 `set_service` 时实例写入 root store 而隔离声明在子级，读写路径可能不对称。
- 建议修法： 写目标与 isolate key 协议对齐（同 D12），`allow_replace=True` 的静默替换改为显式参数。

### D14: `baseUrl` 三重冗余存储 + 构造期父链复制 + property 再回退
- TS: `reference/vendor/cordis/src/context.ts:76`
```ts
this.baseUrl = undefined
```
（子上下文经 extend 原型链自然继承，无复制逻辑）
- PY: `dsh/cordis/context.py:67-68`
```python
self._baseUrl: Optional[str] = base_url or (getattr(parent, "baseUrl", None) if parent else None)
self.base_url: Optional[str] = self._baseUrl
```
及 property 回退 `context.py:300-308`（`_baseUrl` → `base_url` → `_parent.baseUrl` 三级）。
- 判定： DEVIATION-PERMITTED
- 影响： 冗余状态有两个可分别被 setter 之外的代码改写的一致性风险点；观测行为现等价。
- 建议修法： 删除 `base_url` 别名存储，property 仅保留 `_baseUrl` + 父链回退。

### D15: `strict_inject` 默认值来自环境变量 `DSH_STRICT_INJECT`
- TS: `reference/vendor/cordis/src/context.ts` 无此机制（TS 严格性来源在基线外 runtime 配置）。
- PY: `dsh/cordis/context.py:75-76`
```python
import os
self.strict_inject = os.environ.get("DSH_STRICT_INJECT", "1") not in ("0", "false", "False")
```
- 判定： DEVIATION-PERMITTED（默认开启，方向与"fail loud"一致；但默认值策略 TS 基线不可核）
- 影响： 环境变量可全局关闭严格注入，行为可被部署环境隐式改变。
- 建议修法： 在 preset/文档层显式声明该开关；长期应改为 runtime 配置注入而非 env 直读。

### D16: `teardown`/`dispose` 别名与永不填充的 `_effects` 死代码；`effect/disposable` 的 `if self.fiber` 恒真假守卫
- TS: `reference/vendor/cordis/src/context.ts` 无 teardown/dispone 面与 `_effects`（生命周期在基线外 fiber）。
- PY: `dsh/cordis/context.py:66`（`self._effects: List ... = []`）、`365-366`（仅 clear）、`186-188/192-194`（`if self.fiber: ... raise RuntimeError("cannot register effect on context without fiber")`，而 `fiber` 在 55-95 行恒被赋值）。
- 判定： DEVIATION-PERMITTED（影响极小，属死逻辑与不可达守卫）
- 影响： `_effects` 写后即清的假生命周期、恒不可达的 RuntimeError 分支，误导维护者。
- 建议修法： 删除 `_effects` 字段与 `if self.fiber` 守卫（保留 fiber 必存不变式）。

### D17: `unload_plugin` 自发明同步包装，含 `asyncio.run` 新建事件循环兜底
- TS: `reference/vendor/cordis/src/context.ts` 无此方法（TS 卸载经 `ctx.plugin()` 返回 fiber 的 dispose，基线外）。
- PY: `dsh/cordis/context.py:275-280`
```python
loop = asyncio.get_running_loop()
loop.create_task(self.registry.unload_plugin(plugin_id))
return True
except RuntimeError:
    return asyncio.run(self.registry.unload_plugin(plugin_id))
```
- 判定： DEVIATION-PERMITTED（但 `asyncio.run` 兜底在嵌套/无 loop 环境下处置语义未钉测，见 PROBE）
- 影响： 无 loop 时新建临时 loop 执行异步卸载，fiber 清理时序与返回值 `True` 不反映真实卸载结果（create_task 分支恒 True）。
- 建议修法： 移除同步包装，要求调用方持 loop；或返回 Task/Future 让结果可观测。

### D18: 事件派发与 timer 混入的 `caller_ctx` 注入、`setTimeout/setInterval` 别名为自发明 API 面
- TS: `reference/vendor/cordis/src/context.ts:26` 仅文档化"events 方法混入"，具体名单/签名在基线外 events.ts；timer 混入同样基线外。
- PY: `dsh/cordis/context.py:224-254`（每个派发方法 `kwargs.setdefault("caller_ctx", self)`）与 `394-398`（`setTimeout`/`setInterval` 别名）。
- 判定： DEVIATION-PERMITTED（`bail/bail_sync/emit_async/waterfall_sync` 等名单、`caller_ctx` kwarg 均无法在基线内核对，属记录在案的许可扩展）
- 影响： 额外 kwarg 进入监听者签名，跨实现事件负载不同。
- 建议修法： 待 reflect.ts/events.ts 对表审计时统一裁决；当前保持但列入跨文件审计清单。

### D19: `on/once` 的 `assert_active` 前置与失败回滚为自发明组合
- TS: `reference/vendor/cordis/src/context.ts` 无 `on/once` 定义（基线外 events.ts/fiber.ts）。
- PY: `dsh/cordis/context.py:200-208`
```python
if self.fiber:
    self.fiber.assert_active()
disposer = self._event_bus.on(event_name, handler, ...)
try:
    self.disposable(disposer, label=f"ctx.on({event_name})")
except Exception:
    disposer()
    raise
```
- 判定： DEVIATION-PERMITTED（合理防御，但 TS 基线外无对表依据；`except Exception` 吞啸范围未按仓库"空 catch 必须命名"惯例注释）
- 影响： 活跃性断言时序与回滚语义无法与 TS 对证。
- 建议修法： 待 events.ts 审计轮次钉测；为该 `except` 补充"为何此处是唯一可达点"的命名注释。

## 测试缺口

### T1: `Context.is` 品牌判据 — TS context.ts:61-68 的跨副本/仅品牌判定无钉测
现有 parity 测试（tests/1to1/cordis/test_context_parity.py）未覆盖：伪造携带 `registry/reflect/extend` 的对象必须**不**被判为 Context（当前 PY 会误判，见 D1）；TS 引文：`static is(value: any): value is Context { return !!value?.[Context.is as any] }`（61-63）。

### T2: `extend` 元属性覆盖与父不可变性 — TS context.ts:99-107
"child prototypally inherits every property of this context; own properties of `meta` shadow the inherited ones. The parent is not mutated."（94-96 行 JSDoc + 102-104 defineProperty）无钉测：meta 覆盖继承属性、extend 后父的 isolate/intercept/map 不变。

### T3: `isolate` 同名默认 label 唯一性 — TS context.ts:123
`shadow[name] = label ?? Symbol(name)`：两次不传 label 的 `isolate('x')` 必须互不 join（现测 T1 只测显式同 label join 与显式不同），falsy label 行为（D6）亦无钉测。

### T4: `intercept` 子上下文配置可见性 — TS context.ts:141-145
"Plugins loaded under the returned context see `config` merged into the service's resolved config"（131-133 行 JSDoc）无 Python 侧钉测（intercept_map 写入后子/孙可见、父不可见）。

### T5: 根共享与调试表示 — TS context.ts:75, 86-88
`this.root = self`（子上下文 `ctx.root === 根代理`）与 `` `Context <${this.fiber.name}>` `` repr 均无钉测。

### T6: strict 解析错误面一致性 — PY D9/D10 衍生
tests/1to1/cordis/test_context_parity.py:92-136 仅钉测插件子上下文的 `RuntimeError`；根上下文未声明访问的异常类型（现 AttributeError）与 TS 统一 handler 行为无对照钉测。

## PROBE 候选

- D1： 构造 `class Fake: registry=1; reflect=1; extend=...` 实例，断言 `Context.is_(Fake())` 期望值；用于裁决鸭子兜底是否被现有调用方依赖。
- D4： `root = Context(); child = root.extend()` 后直接 `root._isolated_keys['x'] = object()`（模拟 TS 原型链可见性），比较 TS 语义（子可见）与 PY 快照（子不可见）是否被任何调用路径依赖。
- D9： 在根上下文直接访问未声明属性 vs 在插件 apply 内访问未声明属性，比较异常类型/文本（AttributeError vs RuntimeError）与 TS handler 单一行为对表。
- D12： `child = root.isolate('svc')` 后，在插件内分别用 `child.svc`（strict `__getattr__` 路径）与 `child.get('svc')`（reflect `_get_impl` 路径）访问，探测两路径是否命中同一 store 条目（裸 name vs isolate key）。
- D17： 在无运行 loop 的同步环境调用 `unload_plugin`，探测 `asyncio.run` 临时 loop 内 fiber dispose 的副作用顺序与后续根 loop 上的 fiber 状态一致性。
