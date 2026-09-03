# dsh/cordis/utils.py ↔ reference/vendor/cordis/src/utils.ts + reference/vendor/cosmokit/src/{array,misc,string,time,types}.ts

对比快照: dsh-v0.1.2-alpha.1。移植版共 565 行；TS 侧 utils.ts 287 行 + cosmokit 四文件 ~427 行。
注意：utils.py 中 `capitalize`/`uncapitalize`/`camel_case`/`param_case`/`snake_case` 存在**两处重复定义**（L71-113 与 L255-306），Python 模块级后定义覆盖前定义——**生效的是第二处**，第一处为死代码。下述 D1/D2 的偏差均由"生效版本"产生。

## 差异清单

### D1 [MUST-FIX] camelCase 生效实现把分隔符后的数字/大写也吞并，与 TS 正则不一致
- 位置: py:dsh/cordis/utils.py:269-274 vs ts:reference/vendor/cosmokit/src/string.ts:12-14
- 原版行为:
```ts
export function camelCase(source: string) {
  return source.replace(/[_-][a-z]/g, str => str.slice(1).toUpperCase())
}
```
- 移植版现状:
```python
def camel_case(source: str) -> str:   # 生效的第二处定义（L85-88 的第一处被本处覆盖）
    return re.sub(r"[_-]([a-zA-Z0-9])", lambda m: m.group(1).upper(), source)
```
- 修复方案: 改为严格等价 `/[_-][a-z]/g`：`re.sub(r"[_-]([a-z])", lambda m: m.group(1).upper(), source)`。差异实例：`camelCase("foo-1bar")` TS→`"foo-1bar"`、移植版→`"foo1Bar"`；`camelCase("foo-Foo")` TS→`"foo-Foo"`、移植版→`"fooFoo"`。同时删除 L85-88/L91 的死代码定义，保留单一实现。

### D2 [MUST-FIX] paramCase/snakeCase 生效实现（hyphenate/snake_case 第二处）缺少缩写词边界规则，且把空格当分隔符
- 位置: py:dsh/cordis/utils.py:281-303 vs ts:reference/vendor/cosmokit/src/string.ts:22-64
- 原版行为:
```ts
function tokenize(source: string, delimiters: number[], delimiter: number) {
  // 状态机：UPPER/LOWER/DELIM；大写后接小写才插分隔符（缩写词边界）；
  // 仅 '-'(45)/'_'(95) 是分隔符；其余字符（含空格、数字）原样输出
}
export function paramCase(source: string) { return tokenize(source, [45, 95], 45) }
export function snakeCase(source: string) { return tokenize(source, [45, 95], 95) }
```
- 移植版现状:
```python
def hyphenate(source: str) -> str:   # L292-293 把 paramCase/param_case 重绑定到本函数
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", source)
    s2 = re.sub(r"[_\s]+", "-", s1)
    return s2.lower().strip("-")
def snake_case(source: str) -> str:  # 生效的第二处定义，同样只有 ([a-z0-9])([A-Z]) 一条规则
    ...
```
- 修复方案: 按字符状态机 1:1 移植 `tokenize`（大写序列仅在后随小写时插入分隔符；`-`/`_` 作分隔符去重；空格等其余字符原样保留）。差异实例：`paramCase("HTTPServer")` TS→`"http-server"`、移植版→`"httpserver"`；`paramCase("fooBar baz")` TS→`"foo-bar baz"`、移植版→`"foo-bar-baz"`。注意第一处 `param_case`（L94-99）有 `([A-Z]+)([A-Z][a-z])` 规则但已被覆盖——删除重复定义后按 tokenize 重写，勿沿用两条正则近似。

### D3 [MUST-FIX] Time.parse_time 不支持完整单词单位，且容忍空白（TS 一律拒绝）
- 位置: py:dsh/cordis/utils.py:318-335 vs ts:reference/vendor/cosmokit/src/time.ts:32-49
- 原版行为:
```ts
const timeRegExp = new RegExp(`^${['w(?:eek(?:s)?)?', 'd(?:ay(?:s)?)?', 'h(?:our(?:s)?)?',
  'm(?:in(?:ute)?(?:s)?)?', 's(?:ec(?:ond)?(?:s)?)?'].map(unit => `(${numeric}${unit})?`).join('')}$`)
export function parseTime(source: string) {
  const capture = timeRegExp.exec(source)
  if (!capture) return 0
  return (parseFloat(capture[1]) * week || 0) + ... 
}
```
- 移植版现状:
```python
pattern = r"^(?:(\d+(?:\.\d+)?)\s*w)?\s*(?:(\d+(?:\.\d+)?)\s*d)?\s*...$"
match = re.match(pattern, source.strip())
```
- 修复方案: 按原正则重建（无 `\s`、无 strip）：仅 `数字+单位` 紧邻；单位支持 `w(eek(s)?)/d(ay(s)?)/h(our(s)?)/m(in(ute)?(s)?)/s(ec(ond)?(s)?)`。差异实例：`"1week"` TS→604800000、移植版→0；`"10 s"`/`" 10s"`/`"1w 2d"` TS→0、移植版→非 0。`parseFloat(x)*mult || 0` 的 NaN→0 语义用 `float(x)*mult if x else 0` 保留。

### D4 [MUST-FIX] Time.format 用 Python round()（银行家舍入）且亚秒截断，TS 为 Math.round 半进一并保留小数
- 位置: py:dsh/cordis/utils.py:339-351 vs ts:reference/vendor/cosmokit/src/time.ts:63-75
- 原版行为:
```ts
if (abs >= day - hour / 2) { return Math.round(ms / day) + 'd' }
...
return ms + 'ms'
```
- 移植版现状:
```python
if abs_ms >= Time.day - Time.hour / 2:
    return f"{round(ms / Time.day)}d"
...
return f"{int(ms)}ms"
```
- 修复方案: 用 `math.floor(x + 0.5)` 复刻 Math.round（半进一、负数朝 +∞：`Math.round(-1.5)=-1` 而 Python `round(-1.5)=-2`）。差异实例：`format(30000)`（0.5m）TS→`"1m"`、移植版→`"0m"`；`format(-90000)` TS→`"-1m"`、移植版→`"-2m"`；亚秒 `format(500.5)` TS→`"500.5ms"`、移植版→`"500ms"`（末档需按 JS Number→string 规则去掉整数的 `.0`）。

### D5 [MUST-FIX] Time 缺少 7 个公开成员（时区偏移、日期序数、parseDate、toDigits、template）
- 位置: py:dsh/cordis/utils.py:309-351 vs ts:reference/vendor/cosmokit/src/time.ts:10-30,51-91
- 原版行为:
```ts
let timezoneOffset = new Date().getTimezoneOffset()
export function setTimezoneOffset(offset: number) ...
export function getDateNumber(date = new Date(), offset?) // Math.floor((valueOf/minute - offset) / 1440)
export function fromDateNumber(value: number, offset?) ...
export function parseDate(date: string) ...   // 时长/HH:MM(:SS)/YY-MM-DD 解析
export function toDigits(source: number, length = 2) ...
export function template(template: string, time = new Date()) ... // yyyy/yy/MM/dd/hh/mm/ss/SSS
```
- 移植版现状: `class Time` 仅有常量、`parse_time`、`format`；上述成员全部缺失（dsh/ 内 grep 无 `get_date_number|from_date_number|parse_date|to_digits|set_timezone` 实现）。
- 修复方案: 用 `datetime`/`time.localtime` 补齐七个成员（Python 无全局时区偏移状态，可用模块级变量 + `Time.set_timezone_offset/get_timezone_offset` 静态方法）；`template` 按固定顺序 `yyyy→yy→MM→dd→hh→mm→ss→SSS` 替换。

### D6 [MUST-FIX] value_map 用 try/except TypeError 兜底单参调用，会吞掉 transform 内部真实 TypeError
- 位置: py:dsh/cordis/utils.py:55-63 vs ts:reference/vendor/cosmokit/src/misc.ts:44-46
- 原版行为:
```ts
export function mapValues<U, T, K extends string>(object: Dict<T, K>, transform: (value: T, key: K) => U) {
  return Object.fromEntries(Object.entries(object).map(([key, value]) => [key, (transform as any)(value, key)]))
}
```
- 移植版现状:
```python
try:
    res[k] = transform(v, k)
except TypeError:
    res[k] = transform(v)
```
- 修复方案: 无条件 `transform(v, k)`（TS 恒传两参）。现兜底会在 transform 内部抛 TypeError（如 `value + 1` 遇 None）时以单参重跑，掩盖原始出错位置、可能触发次生错误。

### D7 [MUST-FIX] filter_keys 谓词只传 key，缺 TS 的 (key, value) 双参契约
- 位置: py:dsh/cordis/utils.py:66-68 vs ts:reference/vendor/cosmokit/src/misc.ts:39-41
- 原版行为:
```ts
export function filterKeys(object: {}, filter: (key: string, value: any) => boolean) {
  return Object.fromEntries(Object.entries(object).filter(([key, value]) => filter(key, value)))
}
```
- 移植版现状:
```python
def filter_keys(obj, predicate: Callable[[str], bool]) -> Dict[str, Any]:
    return {k: v for k, v in obj.items() if predicate(k)}
```
- 修复方案: 谓词支持 `(key, value)` 双参契约：使用 `inspect.signature` 探测谓词形参；若仅接受 1 个位置参数，调用 `predicate(k)`（保持向后兼容）；若接受 ≥2 个参数或 `*args`，调用 `predicate(k, v)`（满足 TS 规范）。tests/test_cordis_full_specs_parity.py:201 可继续兼容，并新增双参谓词测试锁定 TS 契约。

### D8 [MUST-FIX] pick/omit 缺少无 keys 时整体浅拷贝默认行为与 forced 参数
- 位置: py:dsh/cordis/utils.py:44-52 vs ts:reference/vendor/cosmokit/src/misc.ts:52-69
- 原版行为:
```ts
export function pick<T, K extends keyof T>(source: T, keys?: Iterable<K>, forced?: boolean) {
  if (!keys) return { ...source }
  for (const key of keys) { if (forced || source[key] !== undefined) result[key] = source[key] }
}
export function omit<T, K extends keyof T>(source: T, keys?: Iterable<K>) {
  if (!keys) return { ...source } ...
}
```
- 移植版现状:
```python
def pick(obj, keys): return {k: obj[k] for k in keys if k in obj}   # keys 必填；无 forced
def omit(obj, keys): ...                                            # keys 必填
```
- 修复方案: `keys=None` 时返回 `dict(obj)`；pick 增加 `forced: bool = False`（Python 无 undefined，"跳过 undefined" 对应"跳过缺失键"，None 值视为存在并保留，需在 docstring 注明该映射）。

### D9 [MUST-FIX] deep_equal 丢弃 strict 参数；`type()` 严格判等阻断跨类型/子类比较；首步 `==` 引入 bool/int 等价
- 位置: py:dsh/cordis/utils.py:21-41 vs ts:reference/vendor/cosmokit/src/types.ts:118-142
- 原版行为:
```ts
export function deepEqual(a: any, b: any, strict?: boolean): boolean {
  if (a === b) return true
  if (!strict && isNullable(a) && isNullable(b)) return true
  if (typeof a !== typeof b) return false
  ...
  ?? check(is('RegExp'), (a, b) => a.source === b.source && a.flags === b.flags)
  ?? Object.keys({ ...a, ...b }).every(key => deepEqual(a[key], b[key], strict))
}
```
- 移植版现状:
```python
def deep_equal(a: Any, b: Any, is_dict: bool = False) -> bool:   # 第三参 is_dict 从未使用
    if a == b: return True          # 1 == True → True（TS === 为假）
    if type(a) != type(b): return False   # OrderedDict vs dict、实例 vs dict 直接判 False
```
- 修复方案: ①首步改 `a is b`；②类型闸放宽为"同为 dict/list（含子类）或同类型"后再走结构比较，复刻 TS 的 union-keys 比较；③恢复 `strict: bool = False` 形参并透传递归（None/None 恒真即 Python 对 undefined 缺失的最近映射，docstring 注明）；④补 `datetime.datetime`（valueOf→timestamp）与 `re.Pattern`（pattern/flags）分支（现状 `deep_equal(re.compile("a"), re.compile("a"))` → False，TS → True）。

### D10 [MUST-FIX] DisposableList.delete 按相等/哈希查找，可删掉"相等但不同实例"甚至从未 push 的值（TS 为 WeakMap 恒等语义）
- 位置: py:dsh/cordis/utils.py:163-193 vs ts:reference/vendor/cordis/src/utils.ts:21-25
- 原版行为:
```ts
private weak = new WeakMap<T, number>()
delete(value: T) {
  const sn = this.weak.get(value)
  if (!sn) return false
  return this.map.delete(sn)
}
```
- 移植版现状:
```python
try:
    if value in self._val_to_sn:            # 相等/同哈希即命中（push (1,2) 两次会互相覆盖）
        sn = self._val_to_sn[value]; return self.delete_by_sn(sn)
except TypeError: pass
...
for sn, v in list(self._map.items()):        # 线性扫描 v == value 兜底
    if v == value or v is value: return self.delete_by_sn(sn)
```
- 修复方案: 摒弃不可靠的 `_val_to_sn` 全等散列与线性裸 `==` 扫描。采用以对象同一性优先、绑定方法相等性兜底的映射：① 优先通过 `id(value)` 查找 sn；② 针对 Python 中动态生成绑定方法（`inspect.ismethod`）导致 `id` 瞬态变化的情况，按 `(m.__self__ is value.__self__ and m.__func__ is value.__func__)` 兜底匹配；③ 杜绝纯值相等（如相等的两个不同 tuple）的误匹配；`delete_by_sn` 同步清理映射。差异实例：push 两个相等的 tuple 后 delete 第一个，TS 删 sn1、移植版删 sn2；delete 一个从未 push 但相等的值，TS 返回 False、移植版误删并返回 True。

### D11 [MUST-FIX] get_traceable 对无 tracker 的 callable/_extend 对象也包一层（TS 无 tracker 原样返回）
- 位置: py:dsh/cordis/utils.py:514-523 vs ts:reference/vendor/cordis/src/utils.ts:117-125
- 原版行为:
```ts
export function getTraceable<T>(ctx: Context, value: T): T {
  if (!isObject(value)) return value
  ...
  const tracker = value[symbols.tracker]
  if (!tracker) return value
  return createTraceable(ctx, value, tracker)
}
```
- 移植版现状:
```python
if isinstance(value, Service):
    return value._extend({"ctx": effective_ctx})            # Service 无 tracker 也处理
if hasattr(value, "_extend") and ...:
    return value._extend({"ctx": effective_ctx})            # 任意带 _extend 的用户对象
if callable(value) and not inspect.isclass(value) ...:
    return TracedProxy(effective_ctx, value)                # 无 tracker 的裸函数也包
```
- 修复方案: 在分支前加统一闸门 `tracker = getattr(value, Symbols.tracker, None) or getattr(value, "_cordis_tracker", None); if not tracker: return value`（保留原始值快速路径）；Service 分支也应先检查 tracker（TS Service 构造时恒写 tracker，见 service.ts:46-55）。

### D12 [MUST-FIX] with_props 语义与 TS withProps 的"属性覆盖层"不一致（当前无调用方，属潜伏偏差）
- 位置: py:dsh/cordis/utils.py:526-532 vs ts:reference/vendor/cordis/src/utils.ts:128-140
- 原版行为:
```ts
export function withProps(target: any, props?: {}) {
  if (!props) return target
  return new Proxy(target, {
    get: (target, prop, receiver) => {
      if (prop in props && prop !== 'constructor') return Reflect.get(props, prop, receiver)
      return Reflect.get(target, prop, receiver) },   // props 覆盖优先，set 同理
  })
}
```
- 移植版现状:
```python
def with_props(receiver: Any, service: Any) -> Any:
    if receiver is None: return service
    return TracedProxy(receiver, service)   # 读取走 service（TracedProxy target），ctx 注入、callable 再包装
```
- 修复方案: 按覆盖层语义重写（props dict + target 委托，get/set 先查 props 再落 target；`constructor` 等价排除不适用 Python 可忽略），或显式文档化差异。现状 dsh/ 内无调用方（仅 __init__ 导出），修复前禁止接线使用。

### D13 [MUST-FIX] compose_error 默认不取 outer stack、不向回调传 info，与 TS 默认 buildOuterStack() + StackInfo 契约不符
- 位置: py:dsh/cordis/utils.py:552-565 vs ts:reference/vendor/cordis/src/utils.ts:268-281
- 原版行为:
```ts
export function composeError<T>(callback: (info: StackInfo) => T, getOuterStack = buildOuterStack()): T {
  const info: StackInfo = { offset: 1, error: new Error() }
  ...
}
```
- 移植版现状:
```python
def compose_error(action, get_outer_stack: Optional[...] = None) -> Any:
    ...
    stack_msg = "\n".join(outer)      # 死变量，从未使用
    if not hasattr(e, "_outer_stack"): e._outer_stack = outer
```
- 修复方案: ①默认参数改为 `get_outer_stack=None` 时惰性 `build_outer_stack()`；②向 action 传 info（`{"offset": 1, "error": <捕获的基准异常>}`）供调用方做栈拼接定位；③删除死变量 `stack_msg`。（fiber.py:102 调用侧已显式传入 supplier，故默认值偏差目前潜伏。）

### D14 [MUST-FIX] build_outer_stack 缺少 offset 参数
- 位置: py:dsh/cordis/utils.py:535-549 vs ts:reference/vendor/cordis/src/utils.ts:284-287
- 原版行为:
```ts
export function buildOuterStack(offset = 0) {
  const outerError = new Error()
  return () => outerError.stack!.split('\n').slice(3 + offset)
}
```
- 移植版现状: `def build_outer_stack() -> ...` 无参，捕获 `format_stack()[:-1]` 全量帧。
- 修复方案: 增加 `offset: int = 0` 并在返回的 getter 中对捕获帧做 `filtered[offset:]` 切片，保持与 TS slice(3+offset) 的可组合性。

### D15 [MUST-FIX] is_object 对 __slots__ 实例误判 False
- 位置: py:dsh/cordis/utils.py:242-244 vs ts:reference/vendor/cordis/src/utils.ts:102-104
- 原版行为:
```ts
export function isObject(value: any): value is {} {
  return value && (typeof value === 'object' || typeof value === 'function')
}
```
- 移植版现状:
```python
return value is not None and (hasattr(value, "__dict__") or isinstance(value, (dict, list, tuple, set)) or callable(value))
```
- 修复方案: `__slots__` 类实例无 `__dict__` 会被误判；改为标量排除法：`value is not None and not isinstance(value, (bool, int, float, complex, str, bytes, bytearray, type(None))) or callable(value)`（注意 TS 返回原值而非布尔，Python 布尔返回在真值语境等价，docstring 注明）。

### D16 [MUST-FIX] cosmokit array.ts 七个数组助手全部缺失
- 位置: py:dsh/cordis/utils.py:-(缺失) vs ts:reference/vendor/cosmokit/src/array.ts:4-41
- 原版行为:
```ts
export function contain(array1, array2) { return array2.every(item => array1.includes(item)) }
export function intersection / difference / union / deduplicate / remove / makeArray ...
```
- 移植版现状: dsh/ 全局 grep 无 `make_array|deduplicate|intersection|union|contain` 等实现（命中均为 list.remove 方法调用）。当前上层移植用内联推导式替代，未见直接破坏；但作为 utils 对外契约缺失。
- 修复方案: 在 utils.py 补齐七个函数，保持 JS 语义：`make_array(None)→[]`、标量→`[x]`；`remove` 返回是否删除；`union/deduplicate` 保持首次出现顺序。

### D17 [MUST-FIX] misc/string 零散助手缺失：noop、isNonNullable、isPlainObject（utils 内）、formatProperty、trimSlash、sanitize
- 位置: py:dsh/cordis/utils.py:-(缺失) vs ts:reference/vendor/cosmokit/src/misc.ts:17-32 + string.ts:99-113
- 原版行为:
```ts
export function noop(): any {}
export function isNonNullable<T>(value: T) { return !isNullable(value) }
export function isPlainObject(data: any) { return data && typeof data === 'object' && !Array.isArray(data) }
export function formatProperty(key) / trimSlash(source) / sanitize(source) ...
```
- 移植版现状: `is_plain_object` 仅存在于 dsh/settings/provider.py:90（非 utils 导出）；其余五个全仓缺失。
- 修复方案: 在 utils.py 补齐并导出（`is_plain_object` 可从 settings 收敛回 utils 再转发，避免双份定义）。

### A1 [ADAPT] clone 用 copy.deepcopy 替代 TS 手写描述符克隆
- 位置: py:dsh/cordis/utils.py:16-18 vs ts:reference/vendor/cosmokit/src/types.ts:87-115
- 原版行为: TS clone 按 `Reflect.ownKeys` + 描述符逐键克隆（保留原型、非枚举键；Map/Set/装箱对象会退化为空对象——已知怪癖）。
- 移植版现状: `copy.deepcopy(value)`——循环引用、dict/set/datetime 均正确深拷贝（优于 TS 对 Map/Set 的行为），类与 `__dict__` 保留。
- 结论: 平台等价实现，无需修复；文档标注 Map/Set 类似物（dict/set）行为差异即可。

### A2 [ADAPT] Symbol.for → 字符串常量 Symbols 类；但与 service.py 的 ServiceSymbols 字符串集不一致
- 位置: py:dsh/cordis/utils.py:211-239 vs ts:reference/vendor/cordis/src/utils.ts:50-73
- 原版行为: `shadow: Symbol.for('cordis.shadow')` 等全局注册符号。
- 移植版现状: 字符串 `"cordis.shadow"` 等；而 dsh/cordis/service.py:13-19 的 `ServiceSymbols` 用 `"symbols.init"`、`"cordis.original"` 等另一套字符串表达同一批概念符号。
- 结论: Proxy/Symbol 的 Python 等价映射（ADAPT），但两套常量集应收敛为单一来源（utils.Symbols），否则跨模块 `getattr(obj, symbols.x)` 查找会静默失配。

### A3 [ADAPT] DisposableList：WeakMap→id()/值字典双映射；活迭代→快照迭代；nodejs inspect→__repr__
- 位置: py:dsh/cordis/utils.py:125-208 vs ts:reference/vendor/cordis/src/utils.ts:5-40
- 原版行为: `[Symbol.iterator]() { return this.map.values() }`（活迭代，遍历中删除的项被跳过）。
- 移植版现状: `__iter__` 返回 `list(...)` 快照（遍历期间被删除的项仍会访问）；`clear()` 同为逆序返回 ✓；push 返回闭包 disposer ✓。
- 结论: 无 WeakMap 的等价实现；快照迭代在"dispose-all"场景与 TS 行为一致，保留。

### A4 [ADAPT] createTraceable/Proxy 陷阱 → TracedProxy 显式 dunder；tracker.property/associate/invoke 派发未建模
- 位置: py:dsh/cordis/utils.py:354-482 vs ts:reference/vendor/cordis/src/utils.ts:149-233
- 原版行为: get 陷阱处理 `symbols.original`/`tracker.property`/`tracker.associate`（`ctx.reflect.props['<associate>.<prop>']`）/getter 描述符 shadow 接收者/嵌套 tracker 递归；apply 陷阱经 `symbols.invoke` 派发（utils.ts:220-223）。
- 移植版现状: `__getattr__` 硬编码 `"ctx"` 对应 tracker.property（utils.py:377）；无 associate 查找；`__call__` 直接调用目标（invoke 派发由 Service.__call__ service.py:117-124 承担）；shadow 方法绑定以 `caller_ctx` 关键字注入近似。
- 结论: JS Proxy 在 Python 无原语，属必然改写。注意：dsh/ 内当前无任何代码给对象挂 `_cordis_tracker`（TS Service 构造时恒写 tracker，service.ts:46-55），property/associate 偏差为潜伏项——待 tracker 有真实调用方时按 D11 的闸门一并补齐。

### A5 [ADAPT] isConstructor/joinPrototype/getPropertyDescriptor/createCallable 未导出，由 registry.py/Service 承担
- 位置: py:dsh/cordis/registry.py:165-175,243-265 vs ts:reference/vendor/cordis/src/utils.ts:79-99,107-114,226-233
- 原版行为: `isConstructor` 决定 new vs call；`joinPrototype` 原型链合并（Service+函数原型）；`createCallable` 造可调用服务对象。
- 移植版现状: registry 用 `inspect.isclass` 分流；MRO 取代原型合并；Service.__call__ 取代 createCallable。
- 结论: 平台等价；构造调用形态的 TypeError 级联问题在 pair-2 报告（2-plugin.md D6）单列。

### A6 [ADAPT] template（{key} 插值）为移植版独有，快照 TS 文件中无对应物
- 位置: py:dsh/cordis/utils.py:116-122 vs ts:-(快照内缺失；仅有 time.ts:81 的 Time.template，语义完全不同)
- 原版行为:（无）
- 移植版现状: `re.sub(r"\{\{([^{}]+)\}\}|\{([^{}]+)\}", ...)` 占位符插值。
- 结论: 疑为对旧版 cosmokit `template` 的移植；建议核对上游历史确认契约后保留并注明出处，或移出 1:1 面。

### A7 [ADAPT] is() 构造器名判定与 Binary/base64/hex 命名空间缺失，应映射到 Python 标准库
- 位置: py:dsh/cordis/utils.py:-(缺失) vs ts:reference/vendor/cosmokit/src/types.ts:8-16,27-84
- 原版行为: `is('Date', v)`（instanceof + toStringTag 兜底）；`Binary.toBase64/fromBase64/toHex/fromHex`。
- 移植版现状: 全仓无对应实现（Python 侧应以 `isinstance` + `base64`/`binascii` 标准库等价实现——Win7/Py3.8 可用）。
- 结论: 按需补齐时走标准库（ADAPT），不移植 Buffer 分支。

### S1 [SKIP] 类型层导出无运行时行为
- 位置: ts:reference/vendor/cosmokit/src/misc.ts:2-14（Dict/Get/Extract/MaybeArray/Promisify/Awaitable/Intersect）、string.ts:71-96（Letter 与类型级 camelize/hyphenate）、types.ts:3-5（GlobalConstructorNames）、cordis utils.ts:43-47（Tracker 接口）、235-238（StackInfo）
- 原版行为: 纯 TS 类型/条件类型/接口声明。
- 移植版现状: Python 3.8 typing 无法等价表达且无运行时效果。
- 结论: 跳过（类型系统构造，无行为可移植）。

### S2 [SKIP] Symbol.for 跨 realm 全局注册表语义
- 位置: ts:reference/vendor/cordis/src/utils.ts:52-72
- 原版行为: `Symbol.for(key)` 提供 JS 全局符号注册表（跨 realm/iframe 共享键）。
- 移植版现状: Python 字符串常量本就进程全局唯一，单进程移植无 realm 概念。
- 结论: 跳过（V8 realm 机制在目标环境不存在）。

## 测试缺口
现有覆盖：tests/test_reference_cosmokit_utils_1to1.py（字符串/Time 基础路径）、test_cordis_full_specs_parity.py:178-207（deep_equal/clone/pick/omit/value_map/filter_keys/camelCase 基础）、test_cordis_1to1_full.py（DisposableList 基础）、test_cordis_traceable_and_stack_1to1.py（get_traceable/with_props/compose_error 基础）。以下行为均无用例：

### T1 camelCase 分隔符后数字/大写的 TS 边界（D1）
- 建议: `test_camel_case_digit_and_upper_after_delimiter` — `camelCase("foo-1bar")=="foo-1bar"`、`camelCase("foo-Foo")=="foo-Foo"`。
### T2 paramCase/snakeCase 缩写词与空格边界（D2）
- 建议: `test_param_snake_case_acronym_and_space` — `paramCase("HTTPServer")=="http-server"`、`snakeCase("HTTPServer")=="http_server"`、`paramCase("fooBar baz")=="foo-bar baz"`。
### T3 parse_time 完整单词单位与空白拒绝（D3）
- 建议: `test_time_parse_time_unit_names_and_whitespace` — `"1week"/"1min"/"1sec"` 正确；`"10 s"/" 10s"/"1w 2d"` 返回 0。
### T4 format 半进一舍入与亚秒保留（D4）
- 建议: `test_time_format_math_round_and_subsecond` — `format(30000)=="1m"`、`format(-90000)=="-1m"`、`format(500.5)=="500.5ms"`。
### T5 Time 缺失成员的行为（D5）
- 建议: `test_time_date_number_and_template_helpers` — `getDateNumber/fromDateNumber` 往返、`parseDate("10:30")`、`toDigits(5)=="05"`、`Time.template("yyyy-MM-dd hh:mm:ss")`。
### T6 value_map 透传 transform 的 TypeError（D6）
- 建议: `test_value_map_propagates_transform_typeerror` — transform 内部 `value + 1`（value=None）应以原错误冒泡且只调用一次。
### T7 filter_keys 双参谓词（D7）
- 建议: `test_filter_keys_predicate_receives_value` — `filter_keys({"a":1,"b":2}, lambda k, v: v > 1) == {"b": 2}`。
### T8 pick/omit 无 keys 默认与 forced（D8）
- 建议: `test_pick_omit_defaults_and_forced` — `pick(obj)`/`omit(obj)` 返回浅拷贝；`pick(obj, keys, forced=True)` 包含缺失键语义。
### T9 deep_equal strict 参数与跨类型/子类/正则边界（D9）
- 建议: `test_deep_equal_strict_and_cross_type_edges` — `deep_equal(1, True) is False`、`deep_equal(OrderedDict(a=1), {"a": 1}) is True`、`deep_equal(re.compile("a"), re.compile("a")) is True`。
### T10 DisposableList 恒等删除语义（D10）
- 建议: `test_disposable_list_identity_delete` — 两个相等 tuple 分别 push/delete 互不影响；delete 未 push 的相等值返回 False。
### T11 get_traceable 无 tracker 原样返回（D11）
- 建议: `test_get_traceable_requires_tracker` — 无 tracker 的普通函数/带 `_extend` 的对象按原对象返回（`is` 断言）。
### T12 compose_error 默认栈供应商与 info 契约、build_outer_stack offset（D13/D14）
- 建议: `test_compose_error_default_outer_stack_and_info` — 不传 get_outer_stack 时异常被附加 outer 栈；action 收到 `info["offset"]==1`；`build_outer_stack(offset=2)` 帧数相应减少。
### T13 with_props 覆盖层语义（D12）
- 建议: `test_with_props_overlay_precedence` — props 键优先于 target、其余键落到 target、set 写入 props（对齐 TS withProps 后再固化）。
### T14 is_object 对 __slots__ 实例（D15）
- 建议: `test_is_object_slots_instance` — `class S: __slots__ = ()` 的实例 `is_object` 为 True。
