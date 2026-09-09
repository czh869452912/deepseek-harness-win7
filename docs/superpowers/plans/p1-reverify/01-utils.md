# G1-utils 盲审报告

审计范围说明：基准为 cosmokit 六个 TS 文件（逐行通读）。被审 `dsh/cordis/utils.py` 自称同时移植 `reference/vendor/cordis/src/utils.ts`（已通读该文件仅用于归属判定，不作为 cosmokit 基线的豁免依据）。cosmokit 中仅类型层面（无运行时行为）的导出不计入运行时差异，单列说明。

## 映射表

### A. cosmokit 基线 ↔ Python

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| contain (array.ts:4) | contain (utils.py:395) | D7 |
| intersection (array.ts:9) | intersection (utils.py:400) | D7 |
| difference (array.ts:14) | difference (utils.py:405) | D7 |
| union (array.ts:19) | union (utils.py:410) | D7 |
| deduplicate (array.ts:24) | deduplicate (utils.py:425) | D7 |
| remove (array.ts:29) | remove (utils.py:440) | D7 |
| makeArray (array.ts:40) | make_array / makeArray (utils.py:449 / 460) | D8 |
| noop (misc.ts:17) | noop (utils.py:350) | 1:1（ADAPT：undefined→None） |
| isNullable (misc.ts:20) | is_nullable / isNullable (utils.py:342 / 347) | 1:1（ADAPT：null+undefined→None） |
| isNonNullable (misc.ts:25) | is_non_nullable (utils.py:355) | 1:1 |
| isPlainObject (misc.ts:30) | is_plain_object (utils.py:360) | D9 |
| filterKeys (misc.ts:39) | filter_keys (utils.py:116) | ADAPT（D12） |
| mapValues (misc.ts:44) | value_map (utils.py:92)；**无 mapValues 别名** | ADAPT（D12）+ D14 |
| valueMap (misc.ts:49) | value_map (utils.py:92) | ADAPT |
| pick (misc.ts:52) | pick (utils.py:71) | D2 |
| omit (misc.ts:62) | omit (utils.py:84) | 1:1 |
| defineProperty (misc.ts:76) | 无 | D14 |
| capitalize (string.ts:2) | capitalize (utils.py:136) | 1:1 |
| uncapitalize (string.ts:7) | uncapitalize (utils.py:143) | 1:1 |
| camelCase (string.ts:12) | camel_case / camelCase / camelize (utils.py:150 / 157 / 158) | 1:1 |
| tokenize 私有 (string.ts:22) | _tokenize + _TokenizeState (utils.py:167 / 161) | 1:1 |
| paramCase (string.ts:57) | param_case / paramCase / hyphenate (utils.py:195 / 200 / 201) | 1:1 |
| snakeCase (string.ts:62) | snake_case / snakeCase (utils.py:204 / 209) | 1:1 |
| formatProperty (string.ts:99) | format_property / formatProperty (utils.py:365 / 375) | D10 |
| trimSlash (string.ts:105) | trim_slash / trimSlash (utils.py:378 / 385) | 1:1 |
| sanitize (string.ts:110) | sanitize (utils.py:388) | 1:1 |
| Time 常量 millisecond..week (time.ts:3-8) | Time 常量 (utils.py:465-470) | 1:1 |
| Time 模块级 timezoneOffset 初值 (time.ts:10) | Time._timezone_offset (utils.py:472) | D4 |
| Time.setTimezoneOffset / getTimezoneOffset (time.ts:12-18) | Time.set_timezone_offset / get_timezone_offset (utils.py:474-484) | 1:1 |
| Time.getDateNumber (time.ts:20) | Time.get_date_number (utils.py:487-495) | ADAPT（受 D4 影响） |
| Time.fromDateNumber (time.ts:26) | Time.from_date_number (utils.py:500-504) | ADAPT（Date→datetime） |
| Time.parseTime (time.ts:41，regex 32-39) | Time.parse_time (utils.py:517-530，regex 508-514) | 1:1 |
| Time.parseDate (time.ts:51) | Time.parse_date (utils.py:535-547) | D5 |
| Time.format (time.ts:63) | Time.format (utils.py:552-569) | 1:1（Math.round=floor(x+0.5) 已正确复刻） |
| Time.toDigits (time.ts:77) | Time.to_digits (utils.py:572-574) | D11 |
| Time.template (time.ts:81) | Time.template (utils.py:579-591) | D6 |
| is (types.ts:8-16) | 无 | D14 |
| Binary 命名空间 (types.ts:27-75) | 无 | D14 |
| base64ToArrayBuffer / arrayBufferToBase64 / hexToArrayBuffer / arrayBufferToHex (types.ts:78-84) | 无 | D14 |
| clone (types.ts:87-115) | clone (utils.py:16-18 **及重复定义** 27-29) | D1 + D13 |
| deepEqual (types.ts:118-142) | deep_equal (utils.py:32-68) | D3 |
| 仅类型导出：Dict/Get/Extract/MaybeArray/Promisify/Awaitable/Intersect (misc.ts:2-14)、Letter、类型级 camelize/hyphenate (string.ts:71-96) | 无 | N/A（无运行时行为，类型层面不可移植） |

### B. Python 侧超出 cosmokit 基线的符号（归属判定）

| Python 符号 (file:line) | 最近 TS 对应（非本次基线，已核对） | 状态 |
|---|---|---|
| template (utils.py:212) `{key}` 插值 | **两份 utils.ts 均无对应** | 自发明（D15） |
| DisposableList (utils.py:220) | cordis/src/utils.ts:5-40 | 越基线；unshift(246)/delete 绑定方法回退(278) 为 TS 无（D15） |
| Symbols / symbols (utils.py:302 / 330) | cordis/src/utils.ts:50-73（Symbol.for） | 越基线；字符串替代 Symbol（D15） |
| is_object (utils.py:333) | cordis/src/utils.ts:102-104 isObject | 越基线 ADAPT |
| TracedProxy / get_traceable (utils.py:594 / 725) | cordis/src/utils.ts:117-125 getTraceable、165-218 createTraceable | 越基线、设计分叉（D15） |
| _WithPropsProxy / with_props (utils.py:771 / 817) | cordis/src/utils.ts:128-140 withProps | 越基线（空 props 判定差异，D15） |
| build_outer_stack (utils.py:826) | cordis/src/utils.ts:284-287 | 越基线（切片算术不同，D15） |
| compose_error (utils.py:841) | cordis/src/utils.ts:268-281（含 240-265 handleError） | 越基线（info 可选、无 thenable 处理，D15） |
| get_isolate_symbol (utils.py:868) | 两份 utils.ts 均无对应 | 自发明（D15） |

## 差异

### D1: `clone` 在模块内定义两次，后者遮蔽前者
- TS: types.ts:87-89 ```ts /** Deep-clone common JavaScript values while preserving prototypes. */ export function clone<T>(source: T): T /** Deep-clone common JavaScript values while preserving prototypes and cycles. */ export function clone(source: any, refs = new Map<any, any>()) { ```
- PY: utils.py:16-18 与 utils.py:27-29，两段完全相同的 `def clone(value: Any) -> Any: return copy.deepcopy(value)`，中间夹着 utils.py:21-24 的中途 import。第二个定义覆盖第一个。
- 判定： MUST-FIX
- 影响： 死代码；一旦其中一处被单独修改将产生隐蔽的双实现漂移。
- 建议修法： 删除 utils.py:16-18 与 21-24（import 上移至文件头），仅保留一处 clone。

### D2: `pick` 对 None 值键的行为与 TS 不一致，且存在死逻辑
- TS: misc.ts:55-58 ```ts for (const key of keys) { if (forced || source[key] !== undefined) result[key] = source[key] } ```
- PY: utils.py:76-81 ```python for k in keys: if forced or (k in obj and obj[k] is not None): res[k] = obj.get(k) elif k in obj: res[k] = obj[k] ```
  `elif k in obj` 分支使 `obj[k] is not None` 检查完全失效：值为 None 的现存键**总是**被拾取；而 TS 会丢弃 undefined 值的键（除非 forced）。
- 判定： MUST-FIX
- 影响： `pick({'a': None}, ['a'])` TS→`{}`，PY→`{'a': None}`；依赖 pick 裁剪空字段的调用点行为不同。
- 建议修法： 删除 `elif` 分支（Python 无 undefined/null 之分，统一按 None↔undefined 处理），仅保留 `if forced or (k in obj and obj[k] is not None)`。

### D3: `deep_equal` 字典比较用长度检查替代 TS 的键并集语义
- TS: types.ts:141 ```ts ?? Object.keys({ ...a, ...b }).every(key => deepEqual(a[key], b[key], strict)) ```
  键并集比较：`deepEqual({a:1}, {a:1, b:undefined})` 非严格模式下为 **true**（缺失键≈undefined，两者 nullable）；严格模式下为 false。
- PY: utils.py:50-56 ```python if isinstance(a, dict): if len(a) != len(b): return False for k in a: if k not in b or not deep_equal(a[k], b[k], strict=strict): return False ```
  长度不等直接判假：`deep_equal({'a':1}, {'a':1,'b':None})` 非严格模式下为 **False**。
- 另一子差异：同对象 NaN——TS `NaN === NaN` 恒为 false（types.ts:119 `if (a === b) return true` 不命中，typeof number 非 object → false）；PY utils.py:34 `if a is b: return True` 对同一 NaN 对象返回 True。
- 判定： MUST-FIX（键并集语义）；NaN 子项 DEVIATION-PERMITTED
- 影响： 含 None 值字段的可选配置对象等价判断结果相反。
- 建议修法： 字典分支改为对 `set(a) | set(b)` 逐键 `deep_equal(a.get(k), b.get(k), strict)` 并显式定义"缺失键 ↔ None"的非严格配对规则。

### D4: `Time` 时区偏移默认值为 0，TS 默认取本机时区
- TS: time.ts:10 ```ts let timezoneOffset = new Date().getTimezoneOffset() ```
  初始化为本机时区偏移（JS 约定：UTC+8 → -480）。
- PY: utils.py:472 ```python _timezone_offset = 0 ```
  恒为 UTC，忽略本机时区。`get_date_number()` 不传 offset 时（utils.py:493 `offset = cls._timezone_offset`）与 TS 在非 UTC 机器上结果不同（可相差数小时，跨日翻转点不同）。
- 判定： MUST-FIX
- 影响： 默认"天数编号"在 UTC+8 等环境的日期归属可能错一天。
- 建议修法： 模块导入时初始化 `_timezone_offset = -int(time.localtime().tm_gmtoff / 60)`（Python 3.8 `tm_gmtoff` 可用，且与 JS getTimezoneOffset 符号约定一致）。

### D5: `Time.parse_date` 缺失 `M-D-(H:MM[:SS])` 分支；错误行为不同
- TS: time.ts:55-60 ```ts } else if (/^\d{1,2}(:\d{1,2}){1,2}$/.test(date)) { date = `${new Date().toLocaleDateString()}-${date}` } else if (/^\d{1,2}-\d{1,2}-\d{1,2}(:\d{1,2}){1,2}$/.test(date)) { date = `${new Date().getFullYear()}-${date}` } return date ? new Date(date) : new Date() ```
- PY: utils.py:541-547 仅有 `^\d{1,2}(:\d{1,2}){1,2}$` 分支（`now.replace(hour=..., minute=..., second=...)`），三段日期分支完全缺失，直接落入 `return now`。
- 差异点： (1) `parse_date('9-9-12:30')` TS 走年补全分支，PY 返回**当前时刻**；(2) 小时越界（如 `25:30`）TS 产出 Invalid Date 对象，PY `now.replace(hour=25)` 抛 `ValueError`；(3) TS 用 toLocaleDateString 字符串拼接再 `new Date()`（V8 下多为 Invalid Date），PY 用语义化 replace 实现——这是 ADAPT 方向的正确改写，但需在探针后定案（见 PROBE P1）。
- 判定： MUST-FIX（分支缺失）；错误通道差异 DEVIATION-PERMITTED
- 影响： "本月 9 号 12:30" 类相对日期输入被静默解析为 now。
- 建议修法： 在 `parse_date` 补第三分支：解析 `M-D` 与可选 `H:MM[:SS]`，以当前年构造 datetime；越界输入统一返回策略需先跑 P1 探针定案。

### D6: `Time.template` 的 `str.replace` 替换全部出现，TS 仅替换首次
- TS: time.ts:82-90 ```ts return template .replace('yyyy', time.getFullYear().toString()) .replace('yy', time.getFullYear().toString().slice(2)) ```
  JS `String.replace(string, ...)` 只替换**第一个**匹配：`template('yyyy-MM-yyyy')` → `'2026-09-yyyy'`。
- PY: utils.py:583-590 ```python res = tmpl.replace("yyyy", str(time_val.year)) res = res.replace("yy", str(time_val.year)[2:]) ```
  Python `str.replace` 默认替换**全部**：`'2026-09-2026'`。
- 判定： MUST-FIX
- 影响： 模板中重复 token（如文件名含两段年份/时间）的输出不同。
- 建议修法： 每步改用 `tmpl.replace(old, new, 1)`（保持 TS 的 yyyy→yy→MM→dd→hh→mm→ss→SSS 链式顺序）。

### D7: 集合/查找族用 `==`/哈希语义，TS 为 SameValueZero/严格相等
- TS: array.ts:19-21 ```ts export function union<T>(array1: readonly T[], array2: readonly T[]) { return Array.from(new Set([...array1, ...array2])) } ```；array.ts:30-31 ```ts const index = list?.indexOf(item) if (index >= 0) { ```
  JS `Set` 与 `indexOf` 不做类型强转：`1` 与 `true` 是两个元素；`remove(null, x)` 经 `?.` 返回 false 而非抛错。
- PY: utils.py:410-422（union）、425-437（deduplicate）、440-446（remove）```python try: lst.remove(item) return True except ValueError: return False ```
  `list.remove`/`in`/`set` 走 `==`：`union([1],[True])`→`[1]`（塌缩）；`remove([1], True)` 会移除 `1`；`remove(None, x)` 抛 `AttributeError`（TS 返回 False）；不同 NaN 对象在 PY set 中不合并（JS Set 合并）。
- 判定： DEVIATION-PERMITTED（1/True 塌缩与 NaN 边界，语义可察觉但影响极小）；`remove(None)` 抛 AttributeError 一并记录
- 影响： 布尔与整数混用的列表去重/移除结果与 TS 不同。
- 建议修法： 如需严格对齐，抽出"先 `is` 后 `==`"的成员判定助手供 union/deduplicate/contain/intersection/difference/remove 共用，并在 remove 入口对非 list 抛 TypeError 前返回 False。

### D8: `make_array` 将 tuple/set 展开为列表
- TS: array.ts:40-42 ```ts export function makeArray<T>(source: null | undefined | T | T[]) { return Array.isArray(source) ? source : isNullable(source) ? [] : [source] } ```
  只有真数组被透传，其余一切（含 Set）包装为单元素。
- PY: utils.py:449-457 ```python if isinstance(source, list): return source if isinstance(source, (tuple, set)): return list(source) return [source] ```
  tuple→list 可视为 Python 序列类比（ADAPT）；但 set 被展开成多元素，TS 语义是 `[{1,2}]`。
- 判定： tuple 分支 ADAPT（Python 数组类比）；set 展开分支 DEVIATION-PERMITTED
- 影响： 传 set 输入时返回长度与元素层级不同。
- 建议修法： 将 set 移出展开分支（保留 `[source]` 包装），或注释记录该许可。

### D9: `is_plain_object` 收窄为 dict
- TS: misc.ts:30-32 ```ts export function isPlainObject(data: any) { return data && typeof data === 'object' && !Array.isArray(data) } ```
  对任意非数组对象（含 Date、Map、类实例）返回 true。
- PY: utils.py:360-362 ```python return bool(data and isinstance(data, dict)) ```
  仅 dict 为真；`is_plain_object(datetime.now())` → False，TS `isPlainObject(new Date())` → true。
- 判定： DEVIATION-PERMITTED
- 影响： 非 dict 对象的判定结果不同；当前 harness 内部调用均针对配置/数据 dict，影响极小。
- 建议修法： 在 docstring 记录该收窄许可；若后续有按 isPlainObject 分派动态属性的调用点，需改为 `not isinstance(data, (list, tuple, str, bytes))` 式判定。

### D10: `format_property` 的 Unicode 行为与 JS 不同
- TS: string.ts:99-102 ```ts if (typeof key !== 'string') return `[${key.toString()}]` return /^[a-z_$][\w$]*$/i.test(key) ? `.${key}` : `[${JSON.stringify(key)}]` ```
  JS `\w` 仅 ASCII；`JSON.stringify('café')` 保留非 ASCII 字面量。
- PY: utils.py:370-372 ```python if re.match(r"^[a-zA-Z_$][\w$]*$", key): return f".{key}" return f"[{json.dumps(key)}]" ```
  Python `\w` 默认 Unicode（`'café'` 命中 → `.café`）；`json.dumps` 默认 `ensure_ascii=True`（非 ASCII 转义为 `\uXXXX`）。
- 判定： DEVIATION-PERMITTED
- 影响： 仅非 ASCII 属性键的格式化输出不同（错误消息/调试路径）。
- 建议修法： 正则改 `[\w$]*` 为 `[0-9A-Za-z_$]*`，`json.dumps(key, ensure_ascii=False)`；或记录许可。

### D11: `Time.to_digits` 负数补零位置不同
- TS: time.ts:77-79 ```ts export function toDigits(source: number, length = 2) { return source.toString().padStart(length, '0') } ```
  `toDigits(-5)` → `'0-5'`（padStart 不识别符号）。
- PY: utils.py:572-574 ```python return str(source).zfill(length) ```
  `(-5)` → `'-5'`（zfill 符号感知）。
- 判定： DEVIATION-PERMITTED
- 影响： 仅负数输入（template 的时间分量不产生负值），影响极小。
- 建议修法： 如需 1:1，改为 `s = str(source); return '0' * max(0, length - len(s)) + s`；否则记录许可。

### D12: `value_map` / `filter_keys` 通过签名检查适配参数个数
- TS: misc.ts:44-46 ```ts export function mapValues<U, T, K extends string>(object: Dict<T, K>, transform: (value: T, key: K) => U) { return Object.fromEntries(Object.entries(object).map(([key, value]) => [key, (transform as any)(value, key)])) as Dict<U, K> } ```
  JS 恒以 `(value, key)` 两参调用，1 参函数自动忽略多余实参。
- PY: utils.py:96-113（value_map）、119-132（filter_keys）经 `inspect.signature` 判定 1/2 参后分别调用；签名不可得时 `try: transform(v, k) except TypeError: transform(v)`。
- 判定： ADAPT（Python 形参个数严格，无法依赖"多余实参被忽略"的 JS 行为；由 Python 3.8 语言限制强制的等价改写）
- 遗留风险： 兜底 `except TypeError` 会把 transform **内部**的 TypeError 误判为参数不匹配并重试单参调用，掩盖真实异常。
- 建议修法： 兜底路径改为仅捕获"参数个数"类 TypeError（比对 `str(e)` 中形参名），或签名不可得时直接调用 `transform(v, k)` 不降级。

### D13: `clone` 用 `copy.deepcopy` 替代 TS 手写克隆
- TS: types.ts:89-115：按 Date/RegExp/ArrayBuffer/TypedArray 特化、`Object.create(Object.getPrototypeOf(source))` 保留原型、`Reflect.ownKeys` + 属性描述符逐键克隆、`refs` Map 处理环。
- PY: utils.py:27-29 ```python def clone(value: Any) -> Any: """Deep clone a value matching Cosmokit clone.""" return copy.deepcopy(value) ```
  deepcopy 天然处理环（memo），但无原型/描述符语义（Python 无对应物）。
- 判定： DEVIATION-PERMITTED（JS 特化分支在 Python 无对应类型，语义对 Python 数据等价）
- 影响： 含 getter/特殊原型语义不可比较；普通 dict/list/自定义对象行为一致。
- 建议修法： 记录许可即可；勿尝试复刻描述符克隆。

### D14: cosmokit 运行时 API 缺失（TS 有而 Python 无）
- TS: types.ts:12-16 ```ts export function is<K extends GlobalConstructorNames>(type: K, value?: any): any { if (arguments.length === 1) return (value: any) => is(type, value) return type in globalThis && value instanceof (globalThis[type] as any) || Object.prototype.toString.call(value).slice(8, -1) === type } ```；types.ts:27-75（`Binary.is/isSource/fromSource/toBase64/fromBase64/toHex/fromHex`）；types.ts:78-84（4 个别名）；misc.ts:76-78 ```ts export function defineProperty<T, K extends keyof any>(object: T, key: K, value: any) { return Object.defineProperty(object, key, { writable: true, value, enumerable: false }) } ```；misc.ts:44 `mapValues`（Python 仅有 `value_map`，无 `mapValues`/`map_values` 别名）。
- PY: 全部缺失（utils.py 全文无对应符号）。
- 判定： MUST-FIX（无偏离清单理由的缺漏）
- 影响： 依赖这些助手的后续移植（如事件负载判定、二进制编解码）无处复用。
- 建议修法： 补 `is`（基于 `isinstance`/类型名映射的谓词工厂）、`binary` 模块级函数组（`base64.b64encode/b64decode/hexlify/unhexlify` 映射 bytes）、`define_property`（`setattr` 等价记录）、`value_map` 增加 `mapValues = map_values` 别名；若确认 dsh 无使用点，至少在文件头注释记录裁剪决定。

### D15: Python 侧自发明/越基线增量（cosmokit 无对应）
- TS: 本节按"Python 有而 TS(cosmokit) 无"报告；归属对照见映射表 B 块。代表性引文——cordis/src/utils.ts:117-124 ```ts export function getTraceable<T>(ctx: Context, value: T): T { if (!isObject(value)) return value if (Object.hasOwn(value, symbols.shadow)) { return Object.getPrototypeOf(value) } const tracker = value[symbols.tracker] if (!tracker) return value return createTraceable(ctx, value, tracker) } ```
- PY: 逐项：
  - `template` (utils.py:212-217)：`{key}`/`{{key}}` 插值，两份 utils.ts 均无此函数，属自发明；且与 `Time.template` 同名异义。
  - `get_isolate_symbol` (utils.py:868-880)：无 TS 对应，自发明。
  - `DisposableList.unshift` (utils.py:246-254) 与 `delete` 的绑定方法回退 (utils.py:278-285)：cordis TS 版仅有 push/WeakMap delete (cordis/src/utils.ts:14-25)。
  - `Symbols` 用普通字符串 (utils.py:307-327) 替代 `Symbol.for('cordis.*')` (cordis/src/utils.ts:52-72)。
  - `get_traceable` (utils.py:725-768)：鸭子类型探测 Context/Fiber (733-737)、`_shadow` 属性解包 (739-741)、对**无 tracker** 的 `caller_ctx` 可调用对象也包代理 (761-767)——TS 版无 tracker 即原样返回。
  - `compose_error` (utils.py:841-865)：info 参数可选（TS 恒传 StackInfo，cordis/src/utils.ts:268-272）、不支持 thenable 长栈（TS 273-274）、以 `e._outer_stack` 附加替代栈帧拼接（TS 240-265 handleError）。
  - `build_outer_stack` (utils.py:826-838)：截尾算术（去尾 1 帧再按 offset 去尾）与 TS `slice(3 + offset)`（cordis/src/utils.ts:284-287）不同。
  - `with_props(target, {})` 空字典走 falsy 返回原对象 (utils.py:821-823)；TS `{}` 为 truthy 会返回代理 (cordis/src/utils.ts:128-130)——透传效果等价。
- 判定： 自发明项（template、get_isolate_symbol）与越基线增量整体 DEVIATION-PERMITTED（予以记录许可）；但若该模块后续按 cordis/src/utils.ts 做 1:1 验收，则 `get_traceable` 设计分叉与 `DisposableList.unshift` 升级为 MUST-FIX。
- 影响： 功能增量不违反 cosmokit 基线，但混入同一模块造成 provenance 混淆；`template` 与 `Time.template` 易误用。
- 建议修法： 将 cordis 侧符号迁移至独立模块（如 `dsh/cordis/_internals.py`），`template` 改名（如 `interpolate`）或在 docstring 标注非 TS 来源。

## 测试缺口

### T1: pick 对 undefined/None 值键的丢弃语义 — misc.ts:55-58（`source[key] !== undefined` 门控）与 forced 路径（forced 时缺失键也要产出 undefined/None 键）
### T2: deepEqual 键并集 — types.ts:141，`{a:1}` vs `{a:1,b:undefined}` 非严格 true / 严格 false
### T3: Time.template 仅替换首个 token — time.ts:82-91，`'yyyy-MM-yyyy'` → `'2026-09-yyyy'`
### T4: parseDate 三段日期分支 — time.ts:57-58，`'9-9-12:30'` 需年补全而非返回 now
### T5: Time 时区默认取本机 — time.ts:10，非 UTC 机器 `getDateNumber()` 默认偏移
### T6: union/deduplicate 的 SameValueZero — array.ts:19-26，`[1]` 与 `[true]` 不合并
### T7: remove(null, x) 返回 false — array.ts:30 `list?.indexOf(item)`
### T8: toDigits(-5) → '0-5' — time.ts:78 padStart 符号不感知
### T9: formatProperty('café') → '["café"]' — string.ts:101（ASCII \w + JSON.stringify 字面量）
### T10: makeArray 对非数组可迭代对象包装单元素 — array.ts:40-42
### T11: clone 单一定义回归 — 防止 D1 的双定义复活（当前 utils.py:27 版本生效）

## PROBE 候选

- D5: 用 Node 跑 `Time.parseDate('12:30:45')` 与 `Time.parseDate('9-9-12:30')`，确认 V8 对 `toLocaleDateString()-time` 与 `getFullYear()-M-D-time` 拼串的实际解析结果（预期 Invalid Date）。据此决定 Python 补分支时是复刻"Invalid Date 语义"（返回哨兵/None）还是保留 PY 的语义化实现，避免把 TS 的 locale 解析缺陷当成正确行为移植。
- D6: Node 跑 `Time.template('yyyy-MM-yyyy')` 钉死"仅首替换"，作为 PY 修复（`replace(old, new, 1)` 链）的验收基准。
- D7: Python 探针 `union([1],[True])`、`remove([1], True)`、`contain([float('nan')], [float('nan')])`，量化 ==/哈希塌缩的实际影响面后再定 DEVIATION-PERMITTED 或升级修复。
- D3: Python 探针 `deep_equal({'a':1},{'a':1,'b':None})`（预期 False）与 `deep_equal(nan, nan)`（预期 True），作为修键并集逻辑的对照。
- D10: `format_property('café')` 与 `format_property('a b')`，确认 `\w` Unicode 命中与 json.dumps 转义输出。
- D13/平台： 在 Win7 环境探针 `Time.from_date_number` 对 1969 年（负 epoch）与极端值的 `fromtimestamp` 行为（Windows 可能抛 OSError），确认 ADAPT 返回类型的异常通道。
- D15: 探针 `get_traceable` 对"无 tracker 但带 caller_ctx 参数的可调用"的包裹行为（utils.py:761-767），确认是否有真实调用方依赖，以决定 cordis 对齐时的回退策略。
