# G7a-schema 构造面盲审报告

> 注：G7（schema 全量盲审）智能体两次返回为空，按计划 §6 规模对策拆分为 G7a（构造面）/ G7b（校验与序列化面）两个子报告。本报告与 `07-schema-b.md` 合并构成 G7 全量结论。

审计范围：TS 构造面（`reference/vendor/schemastery/src/index.ts`，含 1–460 行原型/描述符与 529–579、818–900 行类型构造器符号，以实际符号为准）↔ PY `dsh/cordis/schema.py`（1–500 行类主体 + 574–780 行工厂类方法）。只读审计，未写文件、未运行 pytest、未执行 git 命令。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| `ValidationError` 类 + `ValidationError.is` (index.ts:210-235) | `ValidationError` (schema.py:17-64) | 部分：PY 无 `.is()`/kValidationError 标记（用 isinstance 替代）；PY 增加 issues-list 重载（PY-only） |
| symbol path 分支 `[Symbol(...)]` (index.ts:220-222) | 通用 `[{segment}]` (schema.py:54-55) | ADAPT（Python 无 Symbol） |
| `Schema` 构造器 (index.ts:239-269) | `Schema.__init__` + `__call__` (schema.py:113-138) | 部分（见 D1/D2/D3/D17） |
| 构造器 refs 重建分支 (index.ts:244-255) | 无 | 缺失（D2） |
| callback 字符串反序列化 (index.ts:258-263) | 无 | 缺失（D3） |
| `Object.defineProperty(schema,'uid',...)` 后置不可写 (index.ts:264) | uid 先置、options 可覆盖 (schema.py:114-116, 131-133) | 差异（D1） |
| `schema.meta \|\|= {}` (index.ts:266) | `if not isinstance(self.meta, dict)` (schema.py:134-135) | 近似等价 |
| `schema.toString.bind` (index.ts:267) | N/A（方法天然绑定） | ADAPT |
| `Schema.prototype[kSchema]=true` (index.ts:273) | `isinstance(source, Schema)` (schema.py:759) | ADAPT（等价） |
| `~standard` getter (index.ts:275-292) | `standard` property + `__getitem__` + `validate` (schema.py:141-167) | 部分（D15） |
| `Schema.ValidationError = ValidationError` (index.ts:294) | 无 | 缺失（D16） |
| `toJSON` 全局 refs 机制 (index.ts:296-307) | `toJSON(refs_collector)` (schema.py:425-466) + `to_json` (schema.py:468-492, PY-only) | 部分（D3） |
| `set`/`push` (index.ts:309-317) | `set`/`push` (schema.py:302-312) | 匹配（PY 增加容器守护，DEVIATION-PERMITTED） |
| `mergeDesc`/`getInner`/`extractKeys` (index.ts:319-338) | 内联于 `i18n` (schema.py:317-327, 335, 349, 353, 363) | 部分（D13） |
| `i18n` (index.ts:340-368) | `i18n` (schema.py:314-376) | 部分（D13） |
| `extra` (index.ts:370-374) | `extra` (schema.py:297-300) | 匹配 |
| boolean 组循环 required/hidden/loose/disabled/collapse (index.ts:376-384) | required(186)/hidden(201)/loose(206)/disabled(211)/collapse(216) | 匹配（默认值均 True） |
| `deprecated`/`experimental` (index.ts:386-398) | 同名 (schema.py:248-260) | 匹配（badges 容器复制差异归入 D4） |
| `pattern` (index.ts:400-405) | `pattern` (schema.py:267-280) | ADAPT（str/re.Pattern，flags 仅 i/m/s）（D20） |
| `simplify` (index.ts:407-442) | `simplify` (schema.py:378-423) | 部分（D14） |
| `toString` + formatters 注册 (index.ts:444-446, 818-900) | 仅 `__repr__` (schema.py:571-572) | 缺失（D6） |
| `role` (index.ts:448-452) | `role` (schema.py:221-226) | 部分（D7） |
| default/link/comment/description/max/min/step 循环 (index.ts:454-462) | 同名单方法 (schema.py:228-296) | 匹配 |
| `Schema.extend` (index.ts:466-468) | `extend` classmethod (schema.py:575-577) | 匹配 |
| `Schema.resolve` (index.ts:470-495) | `resolve` (schema.py:782-813) | 匹配（intersect 回退链/loose 均一致） |
| `Schema.from` (index.ts:497-515) | `from_` (schema.py:755-773) | 匹配 |
| `Schema.lazy` (index.ts:517-527) | `lazy` (schema.py:737-739) + `_resolve_lazy` (schema.py:827-837) | 匹配（meta 合并顺序 {**outer, **inner} 一致） |
| `Schema.natural` (index.ts:529-531) | `natural` (schema.py:599-601) | 匹配（`.step(1).min(0)` 顺序一致） |
| `Schema.percent` (index.ts:533-535) | `percent` (schema.py:603-605) | 匹配 |
| `Schema.date` (index.ts:537-546) | `date` (schema.py:611-630) | ADAPT（D8） |
| `Schema.regExp` (index.ts:548-559) | `reg_exp` (schema.py:632-651) | ADAPT（等价结构） |
| `Schema.arrayBuffer` (index.ts:561-579) | `array_buffer` (schema.py:653-677) | ADAPT（D9） |
| `defineMethod('is',['constructor'])` (index.ts:864-870, 842-848) | `is_` (schema.py:690-692) | 匹配（缺 constructor 序列化，见 D3） |
| `any`/`never`/`const`/`string`/`number`/`boolean`/`function` (index.ts:872-879) | 同名 (schema.py:579-597, 607-609, 686-688) | 匹配 |
| `bitset` (index.ts:878, 829-835, 856-857) | `bitset` (schema.py:679-684) | 匹配（bits 过滤排除 bool = ADAPT，因 Python bool 是 int） |
| `array` (index.ts:880) | `array` (schema.py:694-698) | 匹配（inner 归一化 via from，default=[] 一致） |
| `dict` (index.ts:881, 825, 852-853) | `dict` (schema.py:700-708) | 部分（D5；default={} 一致） |
| `tuple` (index.ts:882) | `tuple` (schema.py:710-715) | 匹配（PY 额外支持 varargs） |
| `object` (index.ts:884-889, 852-853) | `object` (schema.py:717-721) | 匹配（dict 值逐个 from 归一化顺序一致） |
| `union`/`intersect` (index.ts:891-898) | 同名 (schema.py:723-731) | 匹配（list 逐项 from；PY 额外 varargs） |
| `transform` (index.ts:900, 837-841) | `transform` (schema.py:733-735) | 匹配（缺 callback.toJSON 注入，见 D3） |
| — | `optional`(191)/`nullable`(196)/`badges`(262)/`dynamic`(741)/`computed`(746)/`to_json_schema`(494)/`z` 别名(1110)/`const`等别名(775-780) | PY-only（D18） |

核对通过项（无差异，正面确认）：
- **构造参数默认值**：所有布尔 meta 方法默认 `True`（TS 378 `value = true` ↔ PY 各 `value: bool = True`）；`regExp(flag='')` ↔ `reg_exp(flag='')`。
- **子 schema 归一化顺序**：array/dict/transform 为 inner→sKey/callback→preserve；object 为 dict 值逐个 from；union/intersect/tuple 为 list 逐项 from——两侧一致（dict 的 sKey 除外，见 D5）。
- **Meta 继承**：lazy 构建时 `{**outer.meta, **inner.meta}`（inner 胜出）两侧一致（TS 521/584 ↔ PY 830/835、433/472）。
- **natural/dict 键处理**：natural 构造一致；dict 构造 default={} 一致；dict 校验键重命名（TS 719-735 ↔ PY 967-992）语义等价（PY 延迟到循环后重命名 vs TS 循环内即时，仅病态键冲突下不同）。
- **typeof 对 True/1 的区分**：`_resolve_number` 拒绝 bool（schema.py:876）↔ JS `typeof data !== 'number'`；`_resolve_boolean` 仅接受 bool（schema.py:888-891）；`deep_equal` 显式区分 bool/int（schema.py:72-73）↔ JS 严格相等；`from_(True)` → const（schema.py:761）↔ TS `typeof true === 'boolean'` → const。全部一致。

## 差异

### D1: uid 赋值顺序反转，options.uid 可覆盖全局 uid
- TS: `index.ts:257-264`
  ```ts
  Object.assign(schema, options)
  ...
  Object.defineProperty(schema, 'uid', { value: globalThis.__schemastery_index__++ })
  ```
  uid 恒由全局索引后置生成（不可写），options 中的 uid 被无条件丢弃。
- PY: `schema.py:114-116` 先 `self.uid = __schemastery_index__`，随后 `schema.py:131-133` `setattr(self, k, v)` 应用 options——若 options 含 `"uid"`（`toJSON` 输出即含 uid），PY 会采用传入 uid。
- 判定： **MUST-FIX**
- 影响： 反序列化/克隆路径可能产生重复 uid 或跳号，破坏 refs 去重（`toJSON` 以 uid 为键）。
- 建议修法： `__init__` 在应用 options 后重设 uid（或应用前 `options.pop("uid", None)`），保持 `__schemastery_index__` 递增。

### D2: 构造器缺少 refs 重建分支（JSON → Schema 反序列化整体缺失）
- TS: `index.ts:244-255`
  ```ts
  if (options.refs) {
    const refs = valueMap(options.refs, options => new Schema(options))
    const getRef = (uid: any) => refs[uid]!
    for (const key in refs) {
      options.sKey = getRef(options.sKey); options.inner = getRef(options.inner)
      options.list = options.list && options.list.map(getRef)
      options.dict = options.dict && valueMap(options.dict, getRef)
    }
    return refs[options.uid!]
  }
  ```
- PY: `schema.py:113-135` 无任何 refs 处理；`setattr` 会把 `refs` 挂成普通属性，连接器保持裸 uid/int，不可用。
- 判定： **MUST-FIX**（1:1 序列化往返缺失；当前 dsh/ 内无消费者——`dsh/settings/provider.py:337-340` 只用 PY-only 的 `to_json()`——但 Cordis 配置跨进程传输/恢复依赖此语义）
- 影响： `toJSON()` 输出无法还原为 Schema，端到端只有一半。
- 建议修法： `__init__` 开头加 refs 分支：先对每个 ref 构造 `Schema`，再对 sKey/inner/list/dict 按 uid 解引用，返回 `refs[options["uid"]]`（工厂形态可用 classmethod `Schema.from_json` 承载，ADAPT 于 Python 无 callable-instance 双重身份的构造分支）。

### D3: 序列化丢失 callback/constructor/builder/preserve，且无 callback 字符串反序列化
- TS: `index.ts:258-263`（构造端）
  ```ts
  if (typeof schema.callback === 'string') {
    try { schema.callback = new Function('return ' + schema.callback)() } catch {}
  }
  ```
  TS: `index.ts:837-841` `callback['toJSON'] ||= () => callback.toString()`；`index.ts:843-846` function constructor `toJSON = () => name`；`toJSON` 用 `{ ...this }` 全量展开（index.ts:298-303）。
- PY: `schema.py:444-462` node 仅含 uid/type/meta/value/inner/sKey/list/dict/bits——`transform` 的 callback、`is` 的 constructor、lazy 的 builder、preserve 全部不落盘；构造端也无字符串 callback 还原。
- 判定： **MUST-FIX**（与 D2 合起来才是完整往返；`constructor`→名称字符串无安全风险应立即补齐；callback 的 eval 还原在 Python 侧须 ADAPT，至少序列化为源码字符串并留显式还原钩子，绝不隐式 `eval`）
- 影响： transform/is/lazy schema 经序列化后类型信息不可恢复；`dsh/settings/provider.py:338` 的 `to_json()` 输出对 transform 注册项不完整。
- 建议修法： `toJSON`/`to_json` 节点补充 `"constructor"`（type 时取 `__name__`）、`"preserve"`、`"builder"`（标记不可序列化或序列化源码）；`__init__` 对字符串 callback 仅在显式开关下还原。

### D4: 克隆的连接器容器共享语义相反
- TS: `index.ts:376-384`（示例）+ `index.ts:257`
  ```ts
  [key](this: Schema, value = true) {
    const schema = Schema(this)          // Object.assign 浅拷贝
    schema.meta = { ...schema.meta, [key]: value }
  ```
  `Schema(this)` 经 `Object.assign` 使 clone.list/clone.dict/clone.badges 与原 schema 是**同一**容器；随后 `push`/`set`/`badges.push`（index.ts:309-317, 386-398）会写穿到原 schema。
- PY: `schema.py:170-184` `_clone` 重建 list/dict/bits 容器、复制 badges（schema.py:250, 258）——clone 修改不影响原 schema。
- 判定： **DEVIATION-PERMITTED**（PY 更安全；TS 的共享写属 JS 原型链惯用法副作用，dsh/ 无依赖此行为的代码）
- 影响： 链式 `.required().push(x)` 后原 schema 的 list 在 TS 中被改、PY 中不变；极端用例输出不同。
- 建议修法： 保持 PY 现状，并在移植差异记录中登记；不建议反向对齐。

### D5: dict 构造对显式 sKey 多包一层 `from_` 归一化
- TS: `index.ts:825`
  ```ts
  case 'sKey': schema.sKey = args[index] ?? Schema.string(); break
  ```
  显式 sKey **原样**赋值，不经过 `Schema.from`。
- PY: `schema.py:705` `"s_key": cls.from_(s_key) if s_key is not None else cls.string()`
- 判定： **DEVIATION-PERMITTED**（传 Schema 实例时二者等价；传原始值时 TS 会产生非法 sKey（resolve 时 `unsupported type undefined`），PY 归一化后反而可用；TS 对非 Schema sKey 本属未定义行为）
- 影响： 仅影响传入原始值的边缘调用。
- 建议修法： 保留 PY 归一化并登记差异；若追求严格 1:1 可改为原样赋值。

### D6: `toString(inline)` 与 formatters 注册机制整体缺失，union/intersect 错误文案退化
- TS: `index.ts:444-446`
  ```ts
  Schema.prototype.toString = function toString(inline?: boolean) {
    return formatters[this.type]?.(this, inline) ?? `Schema<${this.type}>`
  }
  ```
  且 union/intersect 抛错引用它：`index.ts:774` `` `expected ${toString()} but got ${JSON.stringify(data)}` ``（如 `expected string | number but got ...`）。
- PY: `schema.py:571-572` 仅 `__repr__` 返回 `Schema<union>`；`schema.py:1029` `_resolve_union` 消息为 `"expected union but got ..."`；`schema.py:1044/1047/1057` 用 `f"expected {schema}"`（repr 而非类型串）。
- 判定： **MUST-FIX**（错误消息是 cordis.yml 校验的用户可见面，属构造器注册面 `defineMethod` 的一部分）
- 影响： 配置报错丢失具体期望类型描述，与 TS 生态（及依赖该文案的客户端渲染）不一致。
- 建议修法： 为 union/intersect/object/array/dict/tuple/const/is 实现最小 `to_string(inline=False)` 注册表（照 TS 864-900 的 formatter 文案），并在 `_resolve_union`/`_resolve_intersect` 错误中使用。

### D7: `role()` 的 extra 键写入条件
- TS: `index.ts:448-452`
  ```ts
  const schema = Schema(this)
  schema.meta = { ...schema.meta, role, extra }
  ```
  `extra` 恒写入（可为 undefined，键存在）。
- PY: `schema.py:221-226` 仅 `if extra is not None` 才写 `meta["extra"]`。
- 判定： **DEVIATION-PERMITTED**（JSON 序列化后 undefined 与缺键等价；仅 `'extra' in meta` 反射检查可见差异）
- 影响： 极低。
- 建议修法： 保留。

### D8: `date()` 解析从 JS 宽格式收窄为 ISO 8601
- TS: `index.ts:540-544`
  ```ts
  Schema.transform(Schema.string().role('datetime'), (value, options) => {
    const date = new Date(value)
    if (isNaN(+date)) throw new ValidationError(`invalid date "${value}"`, options)
  ```
- PY: `schema.py:616-623` 仅 `datetime.fromisoformat`（手动补 `Z`→`+00:00`，因 3.8 不支持 Z）。
- 判定： **ADAPT**（Python 3.8.10 标准库无等价宽松解析器，由偏离强制；错误文案 `invalid date "..."` 已保持一致）
- 影响： `"2024/01/02"` 等非 ISO 串 TS 可解析、PY 抛 ValidationError。
- 建议修法： 保留；在文档登记接受的格式子集。

### D9: `arrayBuffer` 缺少常驻的 buffer-like 归一化分支
- TS: `index.ts:561-568`
  ```ts
  return Schema.union([
    Schema.is(ArrayBuffer), Schema.is(SharedArrayBuffer),
    Schema.transform(Schema.any<ArrayBufferView>(), (value, options) => {
      if (Binary.isSource(value)) return Binary.fromSource(value)
      throw new ValidationError(`expected ArrayBufferSource but got ${value}`, options)
    }, true),
    ...encoding ? [...] : [],
  ])
  ```
- PY: `schema.py:670-677` 仅 `is_(bytes/bytearray/memoryview)` + 可选 encoding transform；无"任意 buffer-like"常驻分支。
- 判定： **ADAPT**（Python 二进制生态不同；bytes/bytearray/memoryview 已覆盖主要源）
- 影响： array.array 等冷门 buffer 源不被接受。
- 建议修法： 保留并登记。

### D10: number step 倍数判定算法不同
- TS: `index.ts:618-637` `decimalShift`/`isMultipleOf` 十进制移位精确判定；`index.ts:643` `isMultipleOf(data, meta.min ?? 0, step)`。
- PY: `schema.py:879-884` 浮点取模 + `1e-9` 容差。
- 判定： **ADAPT**（常见值一致；大数值/极端小数边缘可能分叉；`min ?? 0` 缺省一致）
- 影响： 低。
- 建议修法： 可选移植 decimalShift 实现；至少保留容差并登记。

### D11: intersect 合并语义：TS 只补缺失键，PY 嵌套 dict 深合并；数组分支完全不同
- TS: `index.ts:745-750` + `index.ts:787-788`
  ```ts
  function merge(result: any, data: any) {
    for (const key in data) { if (key in result) continue; result[key] = data[key] }
  }
  ...
  } else if (typeof value === 'object') { merge(result ??= {}, value) }
  ```
  同键首值胜出、不递归；数组（typeof 'object'）按索引补缺。
- PY: `schema.py:1048-1056`
  ```python
  elif isinstance(res, dict) and isinstance(val, dict):
      def _merge_dict(target, source):
          for k, v in source.items():
              if k not in target: target[k] = v
              elif isinstance(target[k], dict) and isinstance(v, dict):
                  _merge_dict(target[k], v)
  ```
  嵌套 dict 递归合并（TS 会保留 target 整个子树）；数组落入 `type(res) != type(val) or res != val` 直接不等即抛。
- 判定： **MUST-FIX**（属 list connector 语义分叉；且 `tests/test_cordis_1to1_advanced_parity_v4.py:153` 的测试以 "deep merges dictionaries" 把 PY 偏差固化成了契约，需一并改测试）
- 影响： intersect 两侧声明同名嵌套对象时输出不同（TS 首值整树胜出，PY 深合并）；数组相交 TS 补缺、PY 抛错。
- 建议修法： `_merge_dict` 去掉递归分支改为仅补缺失键；数组改为逐索引补缺（模拟 TS merge 的 for..in 语义）；更新 v4 测试。

### D12: `_resolve_is` 对非法 constructor 静默放行
- TS: `index.ts:681-696` constructor 非 function 时按 name 原型链走查，**任何不匹配都抛** `expected ${constructor} but got ${data}`。
- PY: `schema.py:936-937`
  ```python
      raise ValidationError(f"expected {ctor} but got {data}", opt)
  return data, None   # ctor 既非 type 也非 str 时静默通过
  ```
- 判定： **MUST-FIX**（违背 fail-loud；经 `is_()` 正常构造不可达，风险低但属防御性放行）
- 影响： 手工构造的 `{"type": "is"}` 节点 constructor 缺失时校验形同虚设。
- 建议修法： 末尾 fallthrough 改为抛 `ValidationError(f"expected {ctor} but got {data}", opt)`。

### D13: i18n 三处边缘偏差
- TS: `index.ts:319-330`（mergeDesc 仅认 `$description`/`$desc`/字符串）；`index.ts:345-347` dict 分支 `getInner(data)?.[key] ?? data?.[key]`（$value 缺 key 时回退原始 data）；`index.ts:351-355` list 分支字符串消息 → `extractKeys(data)` → `{}`。
- PY: `schema.py:321` 多出 `or val.get("")` 回退；`schema.py:335-337` $value 存在但缺 key 时**不回退**；`schema.py:354-355` 字符串消息被当作该 locale 描述替换。
- 判定： **DEVIATION-PERMITTED**（仅边缘消息形态触发；dsh/ 当前无 `.i18n()` 调用方）
- 影响： 极低。
- 建议修法： dict 分支补 `if k not in inner_dict` 回退即可对齐；其余保留并登记。

### D14: simplify 对非容器 value 的防御分支
- TS: `index.ts:410-426` object/dict 直接 `for..in`（原始值得 `{}`）、array/tuple 直接 `forEach`（非数组抛 TypeError）。
- PY: `schema.py:387-388, 401-402` isinstance 不符时原样返回 value。
- 判定： **DEVIATION-PERMITTED**（PY 防御性更合理；`simplify` 被 `dsh/cordis/loader.py:2128` 使用，防御分支避免崩溃）
- 影响： 极低。
- 建议修法： 保留。

### D15: `~standard` issues 附带 raw_message、path 缺省 `[]`
- TS: `index.ts:284-286`
  ```ts
  if (ValidationError.is(error)) {
    return { issues: [{ message: error.message, path: error.options.path }] }
  }
  ```
- PY: `schema.py:159-167` issues 元素多带 `"raw_message"`，path 缺省 `[]`（TS 可为 undefined）。
- 判定： **DEVIATION-PERMITTED**（PY 侧 ValidationError issues-list 渲染需要 raw_message；额外字段对 Standard Schema 消费者无害）
- 影响： 极低。
- 建议修法： 保留。

### D16: `Schema.ValidationError` 静态属性与 `ValidationError.is` 缺失
- TS: `index.ts:294` `Schema.ValidationError = ValidationError`；`index.ts:228-231` `static is(error)`。
- PY: 无（调用方用 isinstance / 直接导入；grep 证实 dsh/ 无 `ValidationError.is`、`Schema.ValidationError` 用法）。
- 判定： **DEVIATION-PERMITTED**
- 影响： 仅 API 形态差异。
- 建议修法： 可补 `Schema.ValidationError = ValidationError` 与 `is` classmethod（注意与 `is_` 命名避让）便于 1:1；非必需。

### D17: `type` 缺省值 "any"
- TS: 构造器不设默认 type，缺 type 时 resolve 抛 `unsupported type "undefined"`（index.ts:486-487）。
- PY: `schema.py:118` `self.type = "any"`——裸 `Schema()` 成为合法 any schema。
- 判定： **DEVIATION-PERMITTED**（PY `_clone` 依赖无参构造；语义更宽松且不会误吞错误——resolvers 仍按 type 分派）
- 影响： 极低。
- 建议修法： 保留。

### D18: PY-only 构造器与方法（TS 无对应）
- PY: `optional`(191)、`nullable`(196)、`badges`(262)、`dynamic`(741-744)、`computed`(746-752)、`to_json`(468)、`to_json_schema`(494-569)、`z` 别名(1110)、`const`/`is_type`/`from_type`/`regExp`/`arrayBuffer` 别名(775-780)、tuple/union/intersect varargs 重载(711-712, 724-725, 729-730)。
- 判定： **DEVIATION-PERMITTED**（严格超集，用于兼容 harness 内部调用与 Python 惯用法；`to_json_schema` 为独立增强面）
- 影响： 无 TS 回归风险。
- 建议修法： 在移植差异清单登记超集边界，避免误当作 1:1 面使用。

### D20: `pattern()` 输入类型与 flags 映射
- TS: `index.ts:400-405` `const pattern = pick(regexp, ['source', 'flags'])`——只接受 JS RegExp。
- PY: `schema.py:267-280` 接受 str（flags 补 `""`）或 `re.Pattern`（仅映射 i/m/s）。
- 判定： **ADAPT**（Python re 与 JS RegExp flags 集合不同；`_resolve_string` 侧按同子集还原，schema.py:858-869，闭合自洽）
- 影响： JS 专属 flags（g/y/u）不落盘——Python 语义下无意义。
- 建议修法： 保留。

### D23: ValidationError path 的 symbol 段格式
- TS: `index.ts:220-222` `` prefix += `[Symbol(${segment.toString()})]` ``。
- PY: `schema.py:54-55` 通用 `prefix += f"[{segment}]"`。
- 判定： **ADAPT**（Python 无 Symbol；dict/symbol 键路径极罕见）
- 影响： 仅错误文案格式。
- 建议修法： 保留。

## 测试缺口

### T1: options.uid 不得覆盖全局 uid — TS `index.ts:264`
现有测试未见构造 `Schema({"uid": <任意值>})` 后断言 uid 仍为全局新值、且两个实例 uid 互异（D1 对应）。

### T2: toJSON → 构造器 refs 往返 — TS `index.ts:244-255`、`index.ts:296-307`
现有 `test_cordis_schema_1to1.py` / `tests/1to1/cordis/test_schema_parity.py` 覆盖 validate/simplify，无"序列化后重建并再次 validate 得到相同结果"的往返用例；含 transform/is 嵌套的往返（D2/D3 对应）完全缺失。

### T3: union 失败错误文案含类型串 — TS `index.ts:774`
`Schema.union([Schema.string(), Schema.number()])(true)` 应抛含 `string | number` 的消息（D6 对应）；现测试只断言抛错不断言文案。

### T4: intersect 同键嵌套对象首值胜出（非深合并） — TS `index.ts:745-750`
`test_cordis_1to1_advanced_parity_v4.py:153` 现断言 "deep merges dictionaries"，与 TS 相反——需反转为"嵌套同键保留首个 schema 的整棵子树"用例（D11 对应），并补数组相交用例。

### T5: 克隆后 push/set 不写穿原 schema（PY 语义冻结） — TS `index.ts:257`+`index.ts:309-317`
TS 中 `Schema.array(Schema.string()).required().push(x)` 会修改原 schema 的 list；PY `_clone` 已隔离。缺少固化 PY 行为的回归用例，防止未来"对齐"时无声翻转（D4 对应）。

### T6: `is` 校验对非法 constructor fail-loud — TS `index.ts:681-696`
constructor 缺失/为 None 时必须抛 ValidationError 而非放行（D12 对应）。

## PROBE 候选

- D1: 构造 `Schema({"type": "any", "uid": 999})` 两次，断言两实例 uid 均来自全局索引且互异、`__schemastery_index__` 前进 2。
- D2+D3: 构造 `Schema.object({"n": Schema.number(), "f": Schema.transform(Schema.string(), fn), "c": Schema.is_("ValueError")})` → `toJSON()` → 用重建分支还原 → 对同一数据 validate 结果与原 schema 逐项一致（transform/is 子节点存在性检查）。
- D6: `Schema.union([Schema.string(), Schema.number()])(True)` 断言错误消息含 `string | number` 且含 JSON 化的输入值。
- D11: `Schema.intersect([Schema.object({"a": Schema.object({"x": Schema.number()})}), Schema.object({"a": Schema.object({"y": Schema.number()})})])({"a": {"x": 1, "y": 2}})`——TS 输出 `{"a": {"x": 1}}`（首树胜出），PY 现输出 `{"a": {"x": 1, "y": 2}}`（深合并）；修 D11 后同步改 `test_cordis_1to1_advanced_parity_v4.py:153`。
- D4: `arr = Schema.array(Schema.string()); cloned = arr.required(); cloned.push(Schema.number())`——断言 `arr.list` 长度不变（固化 PY 隔离语义）。
