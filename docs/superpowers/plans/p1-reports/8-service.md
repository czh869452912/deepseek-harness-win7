# dsh/cordis/service.py ↔ reference/vendor/cordis/src/service.ts

对比基线：TS 为实现权威。Python 的 Service 是普通基类（非 abstract）；JS 的 symbol 键成员（`[Service.check]` 等）→ Python 约定方法/类属性，属预期 ADAPT。

## 差异清单

### D1 [MUST-FIX] 注册走 `ctx.set_service(allow_replace=True)` 而非 `ctx.reflect.provide`：绕过冲突检测且 impl 归属错误
- 位置: py:service.py:55-58 vs ts:service.ts:57
- 原版行为:
  ```ts
  self.ctx.reflect.provide(name, self, this[symbols.check])
  // reflect.provide 内：store[key] 已存在 → throw `service "${name}" has been registered at <...>`
  // disposer 挂在 this.ctx.fiber 上 → 服务随提供它的插件 fiber 卸载
  ```
- 移植版现状:
  ```python
  if hasattr(self.ctx, "set_service"):
      self.ctx.set_service(self.name, self, check=check_fn)      # allow_replace=True，冲突静默替换
  elif hasattr(self.ctx, "provide"):
      self.ctx.provide(self.name, self, check=check_fn)
  ```
- 修复方案: 统一改为 `self.ctx.provide(self.name, self, check=check_fn)`：① 对齐冲突检测：同名重复提供抛 `RuntimeError(f"service '{name}' has been registered at <{prev_fiber.name}>")`（与 TS `reflect.provide` 一致）；② 核心基础设施豁免：根上下文在启动引导期注册自身内置服务（events, timer, logger 等）时放行初始声明；③ 生命周期对齐：`impl.fiber` 正确指向当前插件的 fiber，当插件卸载时其提供的服务随之自动注销，杜绝常驻内存泄漏。

### D2 [MUST-FIX] `__call__` 的 invoke 查找永远失败（查字面量属性 "cordis.invoke"）
- 位置: py:service.py:117-124 vs ts:service.ts:50-52（构造时 `createCallable` 包装 `[symbols.invoke]`）与 ts:utils.ts:220-223
- 原版行为:
  ```ts
  if (self[symbols.invoke]) {
    self = createCallable(name, joinPrototype(Object.getPrototypeOf(this), Function.prototype), tracker)
  }
  // applyTraceable: value[symbols.invoke].apply(proxy, args)
  ```
- 移植版现状:
  ```python
  def __call__(self, *args, **kwargs):
      invoke_fn = getattr(self, self.invoke, None)   # self.invoke == "cordis.invoke"，实例上不存在该名字的属性
      if callable(invoke_fn):
          return invoke_fn(*args, **kwargs)
      raise TypeError(f"Service '{self.name}' is not callable")
  ```
- 修复方案: 将 `Service.__call__` 的派发逻辑映射为：优先获取 `getattr(self, "invoke", None) or getattr(self, "_invoke", None)`；若存在且可调用，直接将实参转发执行并返回结果；若未定义可调用的 invoke 方法，则抛出语义对齐的 `TypeError(f"Service '{self.name}' is not callable")`。

### D3 [ADAPT] 名称派生：provide_name/类名回退 + 去除 "service" 后缀；TS 仅 `constructor['provide']`
- 位置: py:service.py:44-49 vs ts:service.ts:42-43
- 原版行为:
  ```ts
  constructor(protected ctx: Context, name: string) {
    name ??= this.constructor['provide'] as string    // 只有一个回退，且不做后缀处理
  ```
- 移植版现状:
  ```python
  resolved_name = name or getattr(self, "provide_name", None) or getattr(self, "name", None) or self.__class__.__name__.lower()
  if resolved_name.endswith("service"):
      resolved_name = resolved_name[:-7]
  ```
- 修复方案: Python 扩展（类名回退 + 去后缀）方便移植，保留即可；但要在文档标注：`LoggerService` 在 Python 自动注册为 `logger`，TS 若不显式传名则注册名为 undefined（必然要求显式 provide 名或显式传参）。改名风险点：依赖“去后缀”派生名的服务与显式 `set_service` 名不一致时会双注册。

### D4 [ADAPT] check 谓词的解析顺序（`_check_availability` / 普通 `check` 靠 set_service 兜底）
- 位置: py:service.py:51-53 vs ts:service.ts:57（`this[symbols.check]`）
- 原版行为: `self.ctx.reflect.provide(name, self, this[symbols.check])` —— check 是 symbol 键方法，缺失即 undefined。
- 移植版现状: 先查字面量 `"cordis.check"`（永不命中）→ 再 `_check_availability`；而普通 `def check(self)` 只在走 `ctx.set_service` 分支时由 context.py:114-119 兜底识别，走 `ctx.provide` 分支（elif）时丢失。
- 修复方案: service.py 内直接补 `elif not callable(check_fn) and callable(getattr(self, "check", None)): check_fn = self.check`，消除两条注册路径的谓词差异。

### D5 [ADAPT] `_extend`：copy.copy 快照 vs `Object.create(this)` 活链；invoke 分支与 props 透传缺失
- 位置: py:service.py:104-116 vs ts:service.ts:65-73
- 原版行为:
  ```ts
  protected [symbols.extend](props?: any) {
    let self: any
    if (this[Service.invoke]) self = createCallable(this.name, this, this[symbols.tracker])
    else self = Object.create(this)          // 原型继承：之后对原实例的属性改动对扩展可见
    return Object.assign(self, props)        // props 任意键透传
  }
  ```
- 移植版现状: `copy.copy(self)` 浅拷贝 + 仅处理 `props["ctx"]` + 记 `_original`。
- 修复方案: Python 无原型链，可保留浅拷贝，但建议改为轻量代理（或 copy 后对可变属性做惰性转发）并支持任意 props 键透传，否则原实例在 extend 之后新增/修改的实例属性不会反映到扩展视图（get_traceable 每次读服务都会新建扩展视图，当前主要风险是 ctx 之外的属性陈旧）。`Symbols.tracker` 元数据（ts:service.ts:46-55 的 `{associate, property:'ctx'}`）Python 未设置，`associate.prop` 访问器（ts:utils.ts:180-181）因此不可用——现网未用，标注即可。

### D6 [ADAPT] `filter()` 隔离比较公式等价，但 Python 事件总线从不消费它
- 位置: py:service.py:95-102 vs ts:service.ts:61-63
- 原版行为:
  ```ts
  protected [symbols.filter](ctx: Context) {
    return ctx[symbols.isolate][this.name] === this.ctx[symbols.isolate][this.name]
  }
  ```
- 移植版现状: `_isolated_keys.get(self.name)` 的相等比较（双方缺省 None==None 亦真，语义等价）。
- 修复方案: 公式无需改；真正的问题是 Python `EventBus._dispatch_hooks`（events.py:200-217）只认 `actual_ctx.filter` 属性，TracedProxy/Service 作 thisArg 时不过滤——服务作用域过滤在 Python 为死代码。对齐方案见 9-reflect.md D4。

### D7 [ADAPT] `resolve_intercept_config`：非 dict 的 base/head 被包成 `{"base": ...}`；遍历方式等价
- 位置: py:service.py:67-93 vs ts:service.ts:86-102
- 原版行为:
  ```ts
  if (base) configs.unshift(base)
  if (head) configs.push(head)
  if (this['Config']?.merge) return this['Config'].merge(...configs)
  else return Object.assign({}, ...configs)
  ```
- 移植版现状:
  ```python
  if base: configs.insert(0, base if isinstance(base, dict) else {"base": base})
  if head: configs.append(head if isinstance(head, dict) else {"head": head})
  ```
- 修复方案: 合并顺序（root 先、base 最先、head 最后）与 TS 一致；但非 dict 值 TS 原样传入 merge/Object.assign，Python 包了一层键 `base`/`head`，会改变无 merge 时的浅合并结果形状。建议去掉包装，非 dict 直接入列（与 TS 一致），由调用方保证形状。
- 另：TS 沿 intercept map 原型链 `while (this.name in intercept)` 上溯，Python 沿 `_parent` 链收集 `_intercept_map`——等价 ADAPT。

### D8 [ADAPT] `__getattr__` 的 original/shadow 读取、无 tracker 元数据
- 位置: py:service.py:60-65 vs ts:（symbols.original/shadow 在 utils.ts 的 traceable 代理内处理）
- 原版行为: TS 的 original/shadow 由 `createTraceable` 的 get trap 返回（`if (prop === symbols.original) return target`），Service 自身无此逻辑。
- 移植版现状: Service 直接响应 `cordis.original`/`cordis.shadow`/`shadow` 等字符串键，shadow 回落到 `self.ctx._parent`。
- 修复方案: Python 无 Proxy，把读取收敛在 Service/TracedProxy 上属等价实现；保留。`_original` 仅在 `_extend` 里写入，未 extend 时返回 self，与 TS 语义一致。

### D9 [SKIP] `abstract class` 与 `static [Symbol.hasInstance]`
- 位置: py:（无） vs ts:service.ts:11, 104-114
- 原版行为: TS 用 hasInstance 跨代理/跨 realm 判定 Service 实例（沿 constructor 原型链上溯）。
- 移植版现状: Python `isinstance(value, Service)` 天然按 MRO 判定，无跨 realm 问题。
- 修复方案: 语言机制差异，跳过。

## 测试缺口

### T1 经 Service 基类注册的同名服务冲突应抛错（对齐 reflect.provide 冲突检测）
- 建议测试名: `test_service_duplicate_registration_raises`
- 要点: `ctx.plugin(ServiceA)`（注册 "svc"）后再 `ctx.plugin(ServiceB)`（也注册 "svc"），第二个应抛 `service 'svc' has been registered at <...>`；当前经 set_service 静默替换。修复 D1 后与 tests/test_cordis_1to1_final_completeness.py:263 的 ctx.provide 用例并列覆盖 Service 路径。

### T2 声明了 invoke 的服务可直接调用
- 建议测试名: `test_callable_service_invokes_invoke_method`
- 要点: `class Fn(Service): def invoke(self, x): return x * 2`；`ctx.get("fn")(3) == 6`（当前 TypeError）；未声明 invoke 的服务调用仍抛 TypeError。

### T3 `_extend` 视图能看到原实例此后的属性变更（活链语义）或明确快照契约
- 建议测试名: `test_service_extend_visibility_of_later_mutations`
- 要点: `ext = svc._extend({"ctx": child})`；修改 `svc.attr = 1` 后按选定的对齐目标断言 `ext.attr` 可见（TS Object.create 语义）或文档化为快照（现状）——需一条测试固化所选语义，防止两处实现漂移。

### T4 非 dict 的 base/head 原样进入 merge/浅合并
- 建议测试名: `test_resolve_config_passes_non_dict_base_raw`
- 要点: `resolve_intercept_config(base="raw", head={"a":1})`，无 `Config.merge` 时结果应含原始字符串输入的处理（TS Object.assign 行为）而非 `{"base": "raw"}` 包装；有 `Config.merge` 时 merge 收到的实参不含包装。

### T5 普通 `def check(self)` 在两条注册路径下都成为可用性谓词
- 建议测试名: `test_service_plain_check_method_used_by_provide_path`
- 要点: 定义 `def check(self): return False` 的 Service 通过 `ctx.provide` 注册后，依赖它的插件保持 PENDING（当前 ctx.provide 分支拿不到该谓词）。

### T6 服务作用域过滤（Service.filter）在事件派发中生效
- 建议测试名: `test_service_scoped_event_filtering`
- 要点: isolated 作用域内的监听器不接收其他作用域以服务为 thisArg 派发的事件（依赖 9-reflect.md D4 的过滤上下文改造；当前 Python 全量广播）。
