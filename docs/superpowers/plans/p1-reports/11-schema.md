# dsh/cordis/schema.py ↔ reference/vendor/schemastery/src/index.ts

对比基准：`reference/vendor/schemastery/src/index.ts`（快照 dsh-v0.1.2-alpha.1，实际 902 行）为权威实现；
`dsh/cordis/schema.py`（实际 1027 行）为移植版。cosmokit 辅助函数（`deepEqual`/`clone`/`isNullable`/`isPlainObject`/`pick`/`filterKeys`/`valueMap`）语义以 `reference/vendor/cosmokit/src/{misc,types}.ts` 为准。

## 差异清单

### D1 [MUST-FIX] 工厂构造器缺失 meta.default（object/dict→{}、array/tuple→[]、bitset→0）
- 位置: py:dsh/cordis/schema.py:658-684 vs ts:reference/vendor/schemastery/src/index.ts:852-858
- 原版行为: `defineMethod` 末尾统一赋默认值：
  ```ts
  if (name === 'object' || name === 'dict') { schema.meta.default = {} }
  else if (name === 'array' || name === 'tuple') { schema.meta.default = [] }
  else if (name === 'bitset') { schema.meta.default = 0 }
  ```
- 移植版现状: 工厂仅传 type/inner/list/dict/bits，meta 保持 `{}`，如
  ```py
  @classmethod
  def array(cls, inner: Any) -> "Schema":
      return cls({"type": "array", "inner": cls.from_(inner)})
  ```
- 修复方案: 在 `Schema.array/dict/tuple/object/bitset` 五个工厂里创建后设置 `meta["default"]`（dict/object→`{}`、array/tuple→`[]`、bitset→`0`）；注意直接 `Schema({...})` 构造不应获得该默认值（与 TS 一致）。影响面极大：`Schema.object({...})(None)` 在 TS 返回 `{}` 并继续解析成员默认值，Python 返回 `None`；`simplify()` 顶层默认比较同样受影响。

### D2 [MUST-FIX] resolve() 缺失 intersect 默认值回退链
- 位置: py:dsh/cordis/schema.py:755-761 vs ts:reference/vendor/schemastery/src/index.ts:476-483
- 原版行为:
  ```ts
  let current = schema
  let fallback = schema.meta.default
  while (current?.type === 'intersect' && isNullable(fallback)) {
    current = current.list![0]
    fallback = current?.meta.default
  }
  if (isNullable(fallback)) return [data]
  data = clone(fallback)
  ```
- 移植版现状:
  ```py
  fallback = schema.meta.get("default")
  if is_nullable(fallback):
      return data, None
  data = copy.deepcopy(fallback)
  ```
- 修复方案: 在 `_nullable` 分支加入 while 下探：type 为 intersect 且 fallback 为空时取 `list[0].meta.default`（可递归多层 intersect），非空后 deepcopy 作为 data。例：`Schema.intersect([Schema.object({...})])(None)` TS 返回成员默认值填充的对象，Python 返回 None。

### D3 [MUST-FIX] resolve() 未实现 Options.ignore
- 位置: py:dsh/cordis/schema.py:750-772 vs ts:reference/vendor/schemastery/src/index.ts:470-472
- 原版行为:
  ```ts
  Schema.resolve = function resolve(data, schema, options = {}, strict = false) {
    if (!schema) return [data]
    if (options.ignore?.(data, schema)) return [data]
  ```
- 移植版现状: `Schema.resolve(cls, data, schema, options=None, strict=False)` 中无任何 `ignore` 钩子调用，options 直接透传给 resolver。
- 修复方案: 在 `if not schema` 之后、nullable 分支之前加入 `ignore = opt.get("ignore"); if callable(ignore) and ignore(data, schema): return data, None`（注意 TS 中 ignore 优先于 required 检查）。

### D4 [MUST-FIX] property() 缺失 adapted 回写与 autofix；dict 键重命名不回写输入；bitset adapted 未按 default 抑制
- 位置: py:dsh/cordis/schema.py:881-887(另见 899-915、839-857) vs ts:reference/vendor/schemastery/src/index.ts:698-711、731-732、672-673
- 原版行为:
  ```ts
  const [value, adapted] = Schema.resolve(data[key], schema, {...options, path: [...]})
  if (adapted !== undefined) data[key] = adapted
  return value
  // catch: if (!options?.autofix) throw e; delete data[key]; return schema.meta.default
  ```
  dict resolver 还会 `data[rKey] = data[key]; if (key !== rKey) delete data[key]`；
  bitset 在 `value === meta.default` 时返回 `[value]`（不带 keys）。
- 移植版现状: `_property` 仅 `res, adapted = Schema.resolve(val, schema, sub_opt); return res`，adapted 被丢弃；无 autofix 分支；`_resolve_dict` 不回写重命名后的键；`_resolve_bitset` 恒 `return val, keys`。
- 修复方案: ①`_property` 内 resolver 成功且 `adapted is not None` 时回写 `data[key] = adapted`（dict/list 均适用）；②增加 `opt.get("autofix")` 异常分支：`del data[key]; return schema.meta.get("default")`；③`_resolve_dict` 解析后执行 `data[rk] = data[k]`，键名变化时 `del data[k]`；④`_resolve_bitset` 当 `val == schema.meta.get("default")`（工厂默认 0）时返回 `(val, None)`。

### D5 [MUST-FIX] array 长度校验缺失 skipMin（inner 有 default 时跳过 min 检查）
- 位置: py:dsh/cordis/schema.py:777-783、890-893 vs ts:reference/vendor/schemastery/src/index.ts:602-606、715
- 原版行为:
  ```ts
  function checkWithinRange(data, meta, description, options, skipMin = false) {
    ...
    if (data < min && !skipMin) throw ...
  }
  // array resolver:
  checkWithinRange(data.length, meta, 'array length', options, !isNullable(inner!.meta.default))
  ```
- 移植版现状: `_check_range(data, meta, description, opt)` 无 skipMin 参数；`_resolve_array` 恒 `self._check_range(len(data), schema.meta, "array length", opt)`。
- 修复方案: `_check_range` 增加 `skip_min=False` 参数；`_resolve_array` 传 `skip_min=schema.inner is not None and schema.inner.meta.get("default") is not None`。string/number 调用点保持 skipMin=False。

### D6 [MUST-FIX] tuple 短输入：TS 逐成员解析（required 报错/optional 取默认），Python 直接整体验错
- 位置: py:dsh/cordis/schema.py:918-924 vs ts:reference/vendor/schemastery/src/index.ts:737-743
- 原版行为:
  ```ts
  const result = list!.map((inner, index) => property(data, index, inner, options))
  if (strict) return [result]
  result.push(...data.slice(list!.length))
  ```
  无长度前置校验；缺位时 `data[index]` 为 undefined，走 required/default 逻辑。
- 移植版现状:
  ```py
  if len(data) < len(items):
      raise ValidationError(f"expected tuple of length {len(items)} but got {len(data)}", opt)
  ```
- 修复方案: 删除长度前置校验，改为对 `range(len(items))` 逐索引 `_property`（缺位即 None → required 报 "missing required value"、optional 取默认）；保留非 strict 时 `res.extend(data[len(items):])`。

### D7 [MUST-FIX] intersect 合并语义：TS 为浅层 first-wins，Python 为深层 last-wins；类型相等判定与全空结果不同
- 位置: py:dsh/cordis/schema.py:957-986 vs ts:reference/vendor/schemastery/src/index.ts:745-750、777-795
- 原版行为:
  ```ts
  function merge(result, data) { for (const key in data) { if (key in result) continue; result[key] = data[key] } }
  // typeof result !== typeof value → error; typeof value === 'object' → merge(result ??= {}, value)
  // 结束后 return [result]（全成员为 nullable 时 result === undefined）
  ```
- 移植版现状:
  ```py
  elif type(res) != type(val): raise ...
  elif isinstance(val, dict):
      for k, v in val.items():
          if k in res and isinstance(res[k], dict) and isinstance(v, dict): res[k].update(v)
          else: res[k] = v
  ...
  return (res if res is not None else data), None
  ```
- 修复方案: ① 对齐 TS `merge` 合并语义：同级字段遵循先到先得（`for k, v in val.items(): if k not in res: res[k] = v`，第一子项值覆盖后续子项）；② 类型相容性判定对齐 JS `typeof` 宽松类型桶（如 `(int, float)` 归入数值桶、`dict` 与普通对象归入 object 桶），禁止使用过于严苛的 `type(a) != type(b)`；③ 全员 nullable 场景返回 `(None, None)`；④ 严格遵循 Python 3.8.10 语法（类型注解使用 `typing.Dict`, `typing.Union`，严禁 `type[X]` 或 `dict | list` 联合语法）。

### D8 [MUST-FIX] transform：TS 对 result 与 adapted 各调用一次 callback（副作用×2、adapted 被转换），Python 只调用一次且 adapted 原样返回
- 位置: py:dsh/cordis/schema.py:989-995 vs ts:reference/vendor/schemastery/src/index.ts:797-813
- 原版行为:
  ```ts
  const [result, adapted = data] = Schema.resolve(data, inner!, options, true)
  if (preserve) return [callback!(result)]
  else return [callback!(result), callback!(adapted)]
  ```
- 移植版现状:
  ```py
  transformed = schema.callback(res, opt) if len(inspect_params(schema.callback)) >= 2 else schema.callback(res)
  return transformed, (data if schema.preserve else adapted)
  ```
- 修复方案: 非 preserve 分支返回 `(cb(res), cb(adapted if adapted is not None else data))`（adapted 为 None 时按 TS 解构默认取原 data）；preserve 分支 adapted 返回 None。注意 TS 运行时 callback 只收 1 个位置参数（options 形参实为 undefined），Python 以 2 参传入 options 属既定 ADAPT 约定（见 D25），修复时保留 2 参调用但补齐 adapted 的二次调用。

### D9 [MUST-FIX] string pattern：校验时完全忽略 flags；pattern() 把 flags 编码成十进制整数字符串；错误信息缺 flags
- 位置: py:dsh/cordis/schema.py:263-269、808-817 vs ts:reference/vendor/schemastery/src/index.ts:400-405、608-616
- 原版行为:
  ```ts
  const pattern = pick(regexp, ['source', 'flags'])          // flags 为 'gi' 等字母串
  const regexp = new RegExp(meta.pattern.source, meta.pattern.flags)
  if (!regexp.test(data)) throw new ValidationError(`expect string to match regexp ${regexp}`, options)
  ```
- 移植版现状:
  ```py
  s.meta["pattern"] = {"source": regex.pattern, "flags": str(regex.flags)}   # "10" 这类整数串
  src = pat.get("source", "")
  if not re.search(src, data):   # flags 未参与
      raise ValidationError(f"expect string to match regexp {src}", opt)
  ```
- 修复方案: ①`pattern()` 将 `regex.flags` 位标志转换为 JS 风格字母串（i/m/s 映射；其余 Python 专属标志按 D22 约定丢弃或映射）；②`_resolve_string` 用 `re.compile(src, 解析出的flags)` 校验；③错误信息改为 `expect string to match regexp /{src}/{flags}`。

### D10 [MUST-FIX] is() 字符串构造器：TS 沿原型链匹配 constructor.name（子类通过），Python 仅比对精确 __name__
- 位置: py:dsh/cordis/schema.py:866-878 vs ts:reference/vendor/schemastery/src/index.ts:681-696
- 原版行为:
  ```ts
  let prototype = Object.getPrototypeOf(data)
  while (prototype) {
    if (prototype.constructor?.name === constructor) return [data]
    prototype = Object.getPrototypeOf(prototype)
  }
  ```
- 移植版现状:
  ```py
  if type(data).__name__ == ctor:
      return data, None
  raise ValidationError(f"expected {ctor} but got {data}", opt)
  ```
- 修复方案: 改为沿 `type(data).__mro__` 逐级匹配 `cls.__name__ == ctor`（含 object 之前的所有基类；TS 会一路走到 Object.prototype，对应 Python mro 含 object）。

### D11 [MUST-FIX] deep_equal 与 cosmokit deepEqual 语义偏差：bool/int 跨型相等、re.Pattern 按身份比较、strict(is_dict) 参数被忽略、tuple/list 不等价
- 位置: py:dsh/cordis/schema.py:67-86 vs ts:reference/vendor/cosmokit/src/types.ts:118-142（被 index.ts 407、597、672 等处使用）
- 原版行为:
  ```ts
  export function deepEqual(a, b, strict?) {
    if (a === b) return true
    if (!strict && isNullable(a) && isNullable(b)) return true
    if (typeof a !== typeof b) return false        // true 与 1 不同型
    ...
    ?? check(is('RegExp'), (a, b) => a.source === b.source && a.flags === b.flags)
  ```
- 移植版现状:
  ```py
  def deep_equal(a, b, is_dict=False):
      if a == b: return True          # True == 1、0 == False、{'a': True} == {'a': 1} 均为 True
      if type(a) != type(b): return False
      ...
  ```
  `is_dict`（对应 TS 的 strict）在函数体内从未使用；`re.compile('a') == re.compile('a')` 为 False（TS 按 source+flags 判等）；`(1,2)` 与 `[1,2]` 不等（TS 数组等价）。
- 修复方案: ①先做类型桶比较（bool 与 int/float 分离、数值同桶），禁用 `==` 短路导致的跨型相等；②对 `re.Pattern` 比较 `pattern` 与 `flags`；③实现 strict 语义：非 strict 时 None 与缺失键等价（`{...a, ...b}` 键并集 + 嵌套非严格比较），strict（dict simplify 路径）禁用该等价；④list/tuple 视为同构序列。

### D12 [MUST-FIX] simplify 多处偏差：object 未知键保留原值（TS 丢弃）；Python 额外“空结果→None”；Python 额外对数组做默认值比较；intersect 非 dict 成员处理不同
- 位置: py:dsh/cordis/schema.py:367-414 vs ts:reference/vendor/schemastery/src/index.ts:407-442
- 原版行为:
  ```ts
  const item = schema?.simplify(value[key])       // object 且 key 不在 dict → item=undefined → 键被丢弃
  if (this.type === 'dict' || !isNullable(item)) result[key] = item
  ...
  if (deepEqual(result, this.meta.default, this.type === 'dict')) return null
  return result                                    // 无“空对象→null”逻辑
  // array/tuple 分支：逐项 simplify 后直接 return result，无默认值比较
  ```
- 移植版现状:
  ```py
  item = schema.simplify(v) if schema else v      # 未知键保留原值
  ...
  if not res and not self.meta.get("default"): return None    # 多加：空 dict → None
  # array 分支多加：if default_val is not None and deep_equal(arr, default_val): return None
  ```
- 修复方案: ①object 分支未知键直接跳过（不写入结果）；②删除 `if not res ...: return None`；③删除 array 分支的默认值二次比较（顶层比较已存在）；④intersect 分支保持仅 dict 结果参与合并（与 TS `Object.assign` 对字符串成员会产生索引键的怪异行为相比，Python 行为更合理，建议保留并在 vendor README 记录为有意偏差）。

### D13 [MUST-FIX] toString()/formatters 整体缺失；union/intersect 校验失败信息不输出成员类型表达式
- 位置: py:dsh/cordis/schema.py:552-553、946-954、957-986 vs ts:reference/vendor/schemastery/src/index.ts:444-446、765-775、777-795、815-901
- 原版行为:
  ```ts
  Schema.prototype.toString = function toString(inline?) {
    return formatters[this.type]?.(this, inline) ?? `Schema<${this.type}>`
  }
  // union resolver: throw new ValidationError(`expected ${toString()} but got ${JSON.stringify(data)}`, options)
  // formatters: 'string'、'number'、'{ key?: type }'、'{ [key: K]: V }'、'T[]'、'[A, B]'、'A | B'、'A & B'、ctor.name、const 的 JSON.stringify 等
  ```
- 移植版现状: `__repr__` 恒返回 `Schema<{self.type}>`；`_resolve_union` 报 `expected union but got {json.dumps(...)}`；`_resolve_intersect` 报 `expected {schema}`（即 `Schema<intersect>`）。
- 修复方案: ①实现 `to_string(inline=False)` + 每类型 formatter 表（覆盖 is/any/never/const/string/number/boolean/bitset/function/array/dict/tuple/object/union/intersect/transform，注意 dict 的 sKey 缺省为 string、union inline 加括号、object 按 required 加 `?`）；②`_resolve_union`/`_resolve_intersect` 错误信息改用 `schema.to_string()`；③`JSON.stringify(data)` 对齐：None→"undefined" 语义差异可接受，但 datetime 等应转 ISO 字符串。

### D14 [MUST-FIX] toJSON/refs 往返：节点缺少 callback/constructor/preserve/builder 字段、无 JSON 安全化、缺少 refs 反序列化入口、lazy 的 inner 不序列化、uid 覆盖顺序相反
- 位置: py:dsh/cordis/schema.py:101-124、416-473、786-790 vs ts:reference/vendor/schemastery/src/index.ts:239-269、296-307、517-527
- 原版行为:
  ```ts
  // toJSON: globalThis.__schemastery_refs__[this.uid] = JSON.parse(JSON.stringify({ ...this }))
  //   spread 含 callback（经 toJSON 转 source 字符串）、constructor（函数→name 字符串）、preserve、value 等
  // new Schema(options): if (options.refs) { valueMap(options.refs, o => new Schema(o)); 重接线 sKey/inner/list/dict; return refs[options.uid] }
  // if (typeof schema.callback === 'string') schema.callback = new Function('return ' + schema.callback)()
  ```
- 移植版现状: `toJSON` 节点仅 `{uid, type, meta, value?, inner?, sKey?, list?, dict?, bits?}`（多出 uid、缺 callback/constructor/preserve/builder）；无 refs 反序列化分支；`Schema.lazy` 的 `inner` 为 None 导致 `toJSON` 不输出内容；`__init__` 中 `setattr(self, k, v)` 会用 options.uid 覆盖新分配的 uid（TS 的 defineProperty 反向覆盖）。
- 修复方案: ①节点补齐 `preserve`、`callback`（Python 端序列化为源码串不现实，至少保留可重建的标记或省略并记录偏差）、`constructor`（函数→`__name__`）；②`Schema.__init__`/新增 `Schema.parse(data)` 支持 `{"uid":..., "refs": {...}}` 图重建（uid→实例映射后重接 inner/s_key/list/dict）；③uid 分配放到最后一步且不可被 options 覆盖；④lazy 的 `toJSON` 触发 builder 构建后序列化 inner（与 D15 联动）。

### D15 [MUST-FIX] lazy 每次解析都重新调用 builder，未按 TS 语义记忆化（构建一次后替换 inner）
- 位置: py:dsh/cordis/schema.py:786-790 vs ts:reference/vendor/schemastery/src/index.ts:581-587（另见 517-527）
- 原版行为:
  ```ts
  Schema.extend('lazy', (data, schema, options, strict) => {
    if (!schema.inner![kSchema]) {
      schema.inner = schema.builder!()
      schema.inner!.meta = { ...schema.meta, ...schema.inner!.meta }
    }
    return Schema.resolve(data, schema.inner!, options, strict)
  })
  ```
- 移植版现状:
  ```py
  inner = schema.builder() if schema.builder else schema.inner
  if inner is not None:
      inner.meta = {**schema.meta, **inner.meta}
  return Schema.resolve(data, inner, opt, strict)
  ```
- 修复方案: 首次解析后将构建结果写回 `schema.inner` 并在后续调用复用（判断 `schema.inner is None` 或未构建标记）；meta 合并保持 `{**schema.meta, **inner.meta}`（子级优先）只执行一次。副作用：builder 内计数器/闭包状态在 TS 只触发一次。

### D16 [MUST-FIX] ~standard：vendor 应为 'schemastery'；非 ValidationError 异常应重新抛出而非吞成 issues；issue message 缺少路径前缀
- 位置: py:dsh/cordis/schema.py:129-163 vs ts:reference/vendor/schemastery/src/index.ts:275-292
- 原版行为:
  ```ts
  return { version: 1, vendor: 'schemastery', validate: (value) => {
    try { return { value: Schema.resolve(value, this, {})[0] } }
    catch (error) {
      if (ValidationError.is(error)) return { issues: [{ message: error.message, path: error.options.path }] }
      throw error
    }
  } }
  ```
- 移植版现状: `"vendor": "cordis"`；`except Exception as e: return {"issues": [...]}` 吞掉一切异常；message 用 `raw_message`（无 `$path ` 前缀），path 用 `err.path`。
- 修复方案: vendor 改为 `"schemastery"`；仅 `ValidationError` 转 issues（message 用 `str(err)` 带前缀、path 用 `err.options.path`），其余异常 `raise`。注意 `tests/test_cordis_schemastery_standard_schema_1to1.py:23` 现断言 `vendor == "cordis"`，修复时需同步更新。

### D17 [MUST-FIX] date()：Python 3.8 fromisoformat 不支持 'Z'/宽格式（TS new Date 均可解析），且报错引号风格不同
- 位置: py:dsh/cordis/schema.py:593-608 vs ts:reference/vendor/schemastery/src/index.ts:537-546
- 原版行为:
  ```ts
  Schema.transform(Schema.string().role('datetime'), (value, options) => {
    const date = new Date(value)
    if (isNaN(+date)) throw new ValidationError(`invalid date "${value}"`, options)
    return date
  }, true)
  ```
- 移植版现状:
  ```py
  return datetime.datetime.fromisoformat(val)   # 3.8 不接受 '2026-08-29T12:00:00Z' 等
  ...
  raise ValidationError(f"invalid date '{val}'", opt)   # 单引号 vs TS 双引号
  ```
- 修复方案: 解析层显式处理 `Z` 后缀（替换为 `+00:00`）并放宽为常用 ISO 8601 变体（空格分隔、缺秒等）；错误信息改双引号 `invalid date "{val}"`。union 分支结构（is(datetime)/is(date)/transform）属平台 ADAPT，可保留。

### D18 [MUST-FIX] 链式方法克隆别名语义：TS 的 `Schema(this)` 克隆与原对象共享 meta/list/dict 容器（deprecated/experimental/i18n 会改写原 schema 的 meta），Python 克隆全部浅拷贝容器、互不影响
- 位置: py:dsh/cordis/schema.py:166-180、244-256、303-316 vs ts:reference/vendor/schemastery/src/index.ts:239-269(Object.assign 引用拷贝)、386-398、340-343
- 原版行为:
  ```ts
  Schema.prototype.deprecated = function deprecated() {
    const schema = Schema(this)            // schema.meta === this.meta（共享引用）
    schema.meta.badges ||= []              // 原对象的 meta 被，连带修改
    schema.meta.badges.push({ text: 'deprecated', type: 'danger' })
    return schema
  }
  // i18n: schema.meta.description = desc 同样写穿到原对象
  ```
- 移植版现状: `_clone()` 中 `s.meta = dict(self.meta)`、`s.list = list(self.list)`、`s.dict = dict(self.dict)`，`deprecated()` 生成新 badges 列表赋回克隆，原 schema 永不被修改。
- 修复方案: 若追求 1:1，需让克隆共享 meta/list/dict 容器（仅 rebind 时不影响原对象，mutate 时写穿）；实践中 TS 该行为更像缺陷（连续两次 `.deprecated()` 会在原 meta 上累积两个 badge），建议：保留 Python 现状、在此记录为有意偏差并注释说明；若上游行为被 Web GUI 依赖（badge 累积显示）则按 TS 修。

### D19 [MUST-FIX] 工厂细节：dict 无 sKey 时 TS 默认 Schema.string()；bitset 工厂 TS 过滤非 number 位值
- 位置: py:dsh/cordis/schema.py:674-679、658-659 vs ts:reference/vendor/schemastery/src/index.ts:825、829-836
- 原版行为:
  ```ts
  case 'sKey': schema.sKey = args[index] ?? Schema.string(); break
  case 'bits': { schema.bits = {}
    for (const key in args[index]) {
      if (typeof args[index][key] !== 'number') continue
      schema.bits[key] = args[index][key]
    } break }
  ```
- 移植版现状:
  ```py
  "s_key": cls.from_(s_key) if s_key else None
  return cls({"type": "bitset", "bits": bits})   # 非 int 位值原样保留
  ```
- 修复方案: ①`dict()` 未传 s_key 时默认 `cls.string()`（toJSON 形状随之对齐；运行期对字符串键无行为差异）；②`bitset()` 过滤 `not isinstance(v, int) or isinstance(v, bool)` 的项，避免 `_resolve_bitset` 里 `data & "x"` 型 TypeError。

### D20 [MUST-FIX] set/push：TS 在 dict/list 缺失时抛 TypeError，Python 惰性建容器静默成功
- 位置: py:dsh/cordis/schema.py:291-301 vs ts:reference/vendor/schemastery/src/index.ts:309-317
- 原版行为:
  ```ts
  Schema.prototype.set = function set(key, value) { this.dict![key] = value; return this }
  Schema.prototype.push = function push(value) { this.list!.push(value); return this }
  ```
  （dict/list 为 undefined 时抛 `TypeError: Cannot ... of undefined`）
- 移植版现状:
  ```py
  def set(self, key: str, value: "Schema") -> "Schema":
      if self.dict is None: self.dict = {}
      self.dict[key] = value
      return self
  ```
- 修复方案: 对齐 TS：`self.dict`/`self.list` 为 None 时抛 `TypeError`。影响仅限误用路径（对 string/number 等 schema 调 set/push），但属可见错误处理差异。

### D21 [ADAPT] arrayBuffer：以 bytes/bytearray/memoryview + stdlib base64/binascii 替代 ArrayBuffer/SharedArrayBuffer/TypedArray/Binary
- 位置: py:dsh/cordis/schema.py:632-655 vs ts:reference/vendor/schemastery/src/index.ts:561-579
- 原版行为: `Schema.union([Schema.is(ArrayBuffer), Schema.is(SharedArrayBuffer), Schema.transform(Schema.any(), v => Binary.isSource(v) ? Binary.fromSource(v) : throw, true), ...encoding ? [base64/hex transform] : []])`
- 移植版现状: union 为 `is_(bytes)/is_(bytearray)/is_(memoryview)` + encoding 时的 transform；无 encoding 时字符串报 union 错（TS 报 'expected ArrayBufferSource but got ...' 后并入 union 错），最终均失败。
- 修复方案: 平台等价实现，保留。可补：encoding 缺省时对 str 给出 `expected binary but got ...` 风格更贴近的报错文案（低优先）。

### D22 [ADAPT] reg_exp：JS RegExp 旗标 d/g/i/m/s/u/y → Python 仅映射 i/m/s；编译错误消息来自 re.error（文案与 V8 不同）
- 位置: py:dsh/cordis/schema.py:611-629 vs ts:reference/vendor/schemastery/src/index.ts:548-559
- 原版行为: `new RegExp(value, flag)`，失败 `throw new ValidationError(e.message, options)`。
- 移植版现状: 手工映射 `i/m/s` 三种旗标，其余忽略；`raise ValidationError(str(e), opt)`。
- 修复方案: 保留平台映射；g/y/d/u 等 JS 运行语义旗标在 Python 无对应，忽略合理；在 docstring 注明旗标子集约定。

### D23 [ADAPT] ValidationError 的 Python 化：issues 列表构造器扩展、无 kValidationError 品牌符号/静态 is()（用 isinstance 替代）、str(e) 不含 "ValidationError: " 名称前缀
- 位置: py:dsh/cordis/schema.py:17-64 vs ts:reference/vendor/schemastery/src/index.ts:210-235
- 原版行为: `class ValidationError extends TypeError { name = 'ValidationError'; static is(error) { return !!error?.[kValidationError] } }`，message 由构造器拼 `$path ` 前缀。
- 移植版现状: `ValidationError(TypeError)`；额外支持 issues 列表入参（TS 不存在该路径）；`validate()`/内部判断用 isinstance；`raw_message` 保存无前缀文本。
- 修复方案: 语言等价实现，保留；可补 `ValidationError.is = classmethod(err -> isinstance(err, ValidationError))` 以贴近调用点写法。

### D24 [ADAPT] number step 校验：TS 用 decimalShift 精确十进制算法，Python 用 1e-9 容差浮点取模
- 位置: py:dsh/cordis/schema.py:820-830 vs ts:reference/vendor/schemastery/src/index.ts:618-647、639-647
- 原版行为:
  ```ts
  function isMultipleOf(data, min, step) {
    step = Math.abs(step)
    if (!/^\d+\.\d+$/.test(step.toString())) return (data - min) % step === 0
    // 小数步长：按小数位数 decimalShift 后整数取模
  }
  ```
- 移植版现状: `diff = abs(data - min_v); if abs(diff % step) > 1e-9 and abs((diff % step) - step) > 1e-9: raise`
- 修复方案: 常规输入下结果一致；极端大数/高精度小数可能 diverge。如需严格 1:1，移植 decimalShift（按字符串小数位做 10^n 移位）算法；否则保留并记录容差策略。另注意 `meta.get("min", 0)` 在 min 键存在但为 None 时会 TypeError，TS `meta.min ?? 0` 则回退 0，可一并处理。

### D25 [ADAPT] 链式 API 机制与扩展面：JS 函数对象 + `Schema(this)` 克隆 → 显式 `_clone()`；kSchema 符号 → isinstance；`Schema.ValidationError` 属性 → 模块级类；扩展方法 optional()/nullable()/to_json()/to_json_schema()/computed/dynamic/z 与 2 参 callback 约定
- 位置: py:dsh/cordis/schema.py:166-180、125-140、743-747、709-719、998-1004、1027 vs ts:reference/vendor/schemastery/src/index.ts:239-273、294、902
- 原版行为: `Object.setPrototypeOf(schema, Schema.prototype)`；`Schema.prototype[kSchema] = true`；`Schema.ValidationError = ValidationError`；transform callback 运行时只收 1 参。
- 移植版现状: Python class + `__call__`；`isinstance(source, Schema)` 判别；模块级 `ValidationError`；扩展方法为新增面（TS 无对应，不影响 TS 行为复现）；transform callback 以 `(value, options)` 2 参调用（options 真实可用，优于 TS 的 undefined）。
- 修复方案: 均为合理 ADAPT，保留；建议在模块 docstring 记录 callback 2 参约定，避免移植上游回调时误判。

### D26 [SKIP] ValidationError 路径前缀的 symbol 段格式 `[Symbol(...)]`
- 位置: py:dsh/cordis/schema.py:49-55 vs ts:reference/vendor/schemastery/src/index.ts:220-222
- 原版行为: `else if (typeof segment === 'symbol') prefix += `[Symbol(${segment.toString()})]``
- 移植版现状: 非 str/int 段统一 `prefix += f"[{segment}]"`。
- 修复方案: 平台不可行（配置路径中不存在 JS symbol 语义），保留现状。

## 测试缺口

现有覆盖：`tests/test_cordis_schema_1to1.py`（基础类型/object 默认/dict sKey/union/intersect 不相交键/date 本地 ISO/lazy/simplify/standard validate）、`tests/test_cordis_schemastery_advanced_1to1.py`（i18n $description/role/badges/bitset/regexp/arrayBuffer/loose）、`tests/test_schemastery_advanced.py`（varargs/dynamic/transform）、`tests/test_cordis_schemastery_standard_schema_1to1.py`（~standard/natural/percent/computed/hex/transform 1 参）。以下行为均无测试：

### T1 工厂默认 meta：`Schema.object({...})(None)`、`Schema.array(...)(None)`、`Schema.dict(...)(None)`、`Schema.bitset(...)(None)` 应分别得 `{}`（含成员默认值）/`[]`/`{}`/`0` — test_factory_default_meta_on_null_input
### T2 intersect 空输入回退首成员默认值：`Schema.intersect([Schema.object({...})])(None)` → 成员默认值对象 — test_resolve_intersect_falls_back_to_first_member_default
### T3 `Schema.resolve(data, schema, {"ignore": lambda d, s: True})` 跳过校验原样返回 — test_resolve_options_ignore_skips_validation
### T4 property adapted 回写：object 内嵌 bitset（value≠default）解析后原输入 dict 的该键变为 keys 列表 — test_property_adapted_writeback_mutates_input
### T5 autofix：`options={"autofix": True}` 时非法属性被删除并取 schema 默认值 — test_property_autofix_deletes_invalid_key
### T6 dict sKey 键重命名回写：解析后输入 dict 的旧键被删除、新键出现 — test_dict_skey_rename_writes_back_to_input
### T7 bitset 解析值等于 meta.default（0）时 adapted 为 None（不产出 keys） — test_bitset_adapted_suppressed_when_value_equals_default
### T8 inner 有 default 的 array 在 `min(n)` 下允许更短数组 — test_array_min_length_skipped_when_inner_has_default
### T9 tuple 短输入逐成员解析：required 成员报 "missing required value"、optional 成员取默认，而非 "expected tuple of length" — test_tuple_short_input_resolves_members_individually
### T10 intersect 键冲突时首成员胜出（`string().default('x')` vs `string().default('y')` → 'x'） — test_intersect_conflicting_keys_first_member_wins
### T11 intersect 数值类型宽等：成员分别产出 1.0 与 1 时应通过（JS `1.0 === 1`） — test_intersect_numeric_type_equality_1_vs_1_0
### T12 intersect 全成员产出 nullable 时结果为 None（而非原输入） — test_intersect_all_nullable_members_returns_none
### T13 非 preserve transform：callback 对 result 与 adapted 各调用一次（副作用计数 == 2），adapted 为转换后的值 — test_transform_callback_applied_to_adapted
### T14 string pattern flags 生效：`pattern({"source": "[a-z]+", "flags": "i"})` 接受大写（当前必失败） — test_string_pattern_flags_applied
### T15 `re.compile(r'x', re.IGNORECASE)` 经 `.pattern()` 后 meta.flags 为 "i" 而非 "2" — test_pattern_meta_flags_letter_encoding
### T16 `is('Exception')` 对 ValueError 实例通过（MRO 链匹配） — test_is_name_walks_mro_for_subclasses
### T17 `Schema.const(True)` 拒绝 1、`Schema.const(1)` 拒绝 True — test_const_bool_int_not_interchangeable
### T18 deepEqual 语义：两个同 source+flags 的编译 pattern 判等；dict simplify 的 strict 模式 None-vs-缺失键行为 — test_deep_equal_compiled_patterns_and_strict_dict
### T19 `Schema.object({a...}).simplify({"a": ..., "extra": 1})` 丢弃未知键 extra — test_simplify_object_drops_unknown_keys
### T20 object simplify 结果为空且无默认时返回 `{}` 而非 None — test_simplify_empty_object_returns_empty_dict
### T21 array simplify 即便处理结果等于默认值也保留数组（仅顶层比较生效） — test_simplify_array_keeps_default_equal_array
### T22 union 失败信息包含成员类型串（如 `expected string | number but got ...`） — test_union_error_message_lists_member_types
### T23 各类型 `to_string()` 快照：string/number/object(含 `?`)/dict/array/tuple/union(inline 括号)/intersect/transform/is/const — test_schema_tostring_formatters
### T24 `toJSON()` 节点含 preserve/constructor（函数→name），且 refs 为 JSON 安全结构 — test_tojson_refs_roundtrip_full_fidelity
### T25 由 `{"uid", "refs"}` 数据重建 schema 图（嵌套 inner/sKey/list/dict 重接线）并可用 — test_deserialize_refs_rebuilds_schema_graph
### T26 `Schema.lazy(...).toJSON()` 触发 builder 并序列化已构建 inner — test_lazy_tojson_serializes_built_inner
### T27 lazy builder 只被调用一次（计数器断言，两次 resolve） — test_lazy_builder_called_once
### T28 `~standard`：vendor=="schemastery"、非 ValidationError 异常向上抛、issue message 带 `$path ` 前缀（现有 test_cordis_schemastery_standard_schema_1to1.py:23 断言 "cordis" 需同步修改） — test_standard_schema_vendor_and_unknown_error_rethrow
### T29 `Schema.date()("2026-08-29T12:00:00Z")` 解析成功（UTC） — test_date_parses_utc_z_suffix
### T30 TS 语义下连续 `.deprecated()` 与原 schema 检视的 badge 累积行为（若按 D18 修复则需此测试固化） — test_deprecated_badges_accumulate_on_shared_meta
### T31 链式克隆后 `set/push` 是否写穿到原 schema 的容器（D18 别名语义） — test_chain_clone_shares_list_dict_containers
### T32 `Schema.dict(inner)` 的 sKey 默认为 string schema（toJSON 中出现 sKey 节点） — test_dict_factory_default_skey_is_string_schema
### T33 `Schema.bitset({"a": "x"})` 过滤非数值位 — test_bitset_factory_filters_non_number_bits
### T34 对无 dict/list 的 schema 调 `set/push` 抛 TypeError — test_set_push_without_container_raises_typeerror
