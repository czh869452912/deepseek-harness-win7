# G7b-schema 校验与序列化盲审报告

> 注：G7（schema 全量盲审）智能体两次返回为空，按计划 §6 规模对策拆分为 G7a（构造面，`07-schema-a.md`）/ G7b（本报告）两个子报告，合并构成 G7 全量结论。

审计范围：TS `reference/vendor/schemastery/src/index.ts`（resolve/resolvers/merge/serialize/deserialize 面，460-817 行为主，含 210-307 的 ValidationError/refs 支撑面）↔ PY `dsh/cordis/schema.py`（783-1107 resolver 面、425-492 序列化面）。已核对 cosmokit `clone`(types.ts:89)/`isNullable`(misc.ts:20)/`isPlainObject`(misc.ts:30) 的被引用语义。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| `ValidationError` (index.ts:210-235) | `ValidationError` (schema.py:17-64) | ✓ + PY 超集(issues 聚合模式) |
| `~standard` validate getter (index.ts:275-292) | `Schema.validate` (schema.py:154-167) | ✓ + PY 超集(raw_message) |
| **refs 反序列化分支 `options.refs` (index.ts:244-255)** | **无对应实现**（全仓 grep 无 fromJSON/deserialize） | **PY 缺失** |
| `Schema.resolve` (index.ts:470-495) | `Schema.resolve` (schema.py:783-813) | ✓ |
| `resolvers` 表 (index.ts:464) | `Schema.resolvers` (schema.py:111) | ✓ |
| `Schema.extend` (index.ts:466-468) | `Schema.extend` (schema.py:576-577) | ✓ |
| resolver `lazy` (index.ts:581-587) | `_resolve_lazy` (schema.py:827-837) | ✓ + PY `_dynamic` 重建分支(828-831) |
| resolver `any` (index.ts:589-591) | `_resolve_any` (schema.py:841-842) | ✓ |
| resolver `never` (index.ts:593-595) | `_resolve_never` (schema.py:845-846) | ✓ |
| resolver `const` (index.ts:597-600) | `_resolve_const` (schema.py:849-852) | ✓ |
| `checkWithinRange` (index.ts:602-606) | `_check_range` (schema.py:818-824) | ✓ |
| resolver `string` (index.ts:608-616) | `_resolve_string` (schema.py:855-872) | ✓（regex 引擎 ADAPT） |
| `decimalShift` (index.ts:618-627) | 无 | **PY 缺失** |
| `isMultipleOf` (index.ts:629-637) | 内联 epsilon 取模 (schema.py:879-884) | 算法替换 |
| resolver `number` (index.ts:639-647) | `_resolve_number` (schema.py:875-885) | ✓（bool 排除 ADAPT） |
| resolver `boolean` (index.ts:649-652) | `_resolve_boolean` (schema.py:888-891) | ✓ |
| resolver `bitset` (index.ts:654-674) | `_resolve_bitset` (schema.py:894-915) | ✓（default 缺省差异 D8） |
| resolver `function` (index.ts:676-679) | `_resolve_function` (schema.py:918-921) | ✓（callable ADAPT） |
| resolver `is` (index.ts:681-696) | `_resolve_is` (schema.py:924-937) | ✓（`__mro__` ADAPT；兜底分支差异 D10） |
| `property` (index.ts:698-711) | `_property` (schema.py:940-954) | ✓（autofix 数组差异 D9） |
| resolver `array` (index.ts:713-717) | `_resolve_array` (schema.py:957-964) | ✓ |
| resolver `dict` (index.ts:719-735) | `_resolve_dict` (schema.py:967-992) | ✓（改名时机 D13） |
| resolver `tuple` (index.ts:737-743) | `_resolve_tuple` (schema.py:995-1002) | ✓ |
| `merge` (index.ts:745-750) | 内联于 `_resolve_object` (schema.py:1014-1017) | ✓ skip 语义一致 |
| resolver `object` (index.ts:752-763) | `_resolve_object` (schema.py:1005-1018) | ✓ |
| resolver `union` (index.ts:765-775) | `_resolve_union` (schema.py:1021-1029) | ✗ 错误文案 |
| resolver `intersect` (index.ts:777-795) | `_resolve_intersect` (schema.py:1032-1065) | ✗ 同键深合并 |
| resolver `transform` (index.ts:797-813) | `_resolve_transform` (schema.py:1068-1078) | ✓（callback 参数 ADAPT） |
| `Schema.prototype.toJSON` (index.ts:296-307) | `toJSON` (schema.py:425-466) | 部分（缺 callback/constructor/preserve 字段） |
| —（TS 无） | `to_json` (schema.py:468-492) | PY-only |
| —（TS 无） | `to_json_schema` (schema.py:494-569) | PY-only |
| `clone` (cosmokit types.ts:89-115，深拷+环保护) | `copy.deepcopy` (schema.py:802) | ✓ ADAPT |
| `isNullable` (cosmokit misc.ts:20-22) | `is_nullable` (schema.py:101-102) | ✓ ADAPT |
| `isPlainObject` (cosmokit misc.ts:30-32) | `isinstance(data, dict)` (schema.py:968/1006) | ✓ ADAPT |

## 差异

### D1: intersect 同键 dict — TS 跳过(first-wins)，PY 递归深合并
- TS: `index.ts:745-750` + `index.ts:787-788`
  ```ts
  function merge(result: any, data: any) {
    for (const key in data) {
      if (key in result) continue   // 已存在键整体跳过，无深合并
      result[key] = data[key]
    }
  }
  ...
  } else if (typeof value === 'object') {
    merge(result ??= {}, value)
  ```
- PY: `schema.py:1049-1055`
  ```py
  def _merge_dict(target, source):
      for k, v in source.items():
          if k not in target:
              target[k] = v
          elif isinstance(target[k], dict) and isinstance(v, dict):
              _merge_dict(target[k], v)   # 同键 dict 递归深合并
  ```
- 判定： **MUST-FIX**
- 影响： `Schema.intersect([object({a:{x:1,y:1}}), object({a:{x:2,z:2}})])` TS 得 `{a:{x:1,y:1}}`，PY 得 `{a:{x:1,y:1,z:2}}`；配置合并语义完全不同（后者会泄露第二成员的同名嵌套键）。这正是任务点名的「同键 dict 深合并还是跳过」分歧点。
- 建议修法： `_resolve_intersect` 中对象分支改为与 `_resolve_object`(1014-1017) 相同的 skip 循环：`for k, v in val.items(): if k not in res: res[k] = v`，删除 `_merge_dict`。

### D2: union/intersect 失败错误文案丢失类型串
- TS: `index.ts:774`
  ```ts
  throw new ValidationError(`expected ${toString()} but got ${JSON.stringify(data)}`, options)
  ```
  （intersect 同款见 index.ts:786/790；`toString()` 经 896-898 格式化为如 `A & B` 的类型串）
- PY: `schema.py:1029` / `schema.py:1044`
  ```py
  raise ValidationError(f"expected union but got {json.dumps(data, default=str)}", opt)
  raise ValidationError(f"expected {schema} but got {json.dumps(data, default=str)}", opt)  # __repr__ → "Schema<intersect>"
  ```
- 判定： **MUST-FIX**
- 影响： 错误文案 1:1 破坏：TS 输出 `expected string | number but got true`，PY 输出 `expected union but got true` / `expected Schema<intersect> but got ...`；下位客户端（web GUI 错误面板、i18n 匹配）拿到的是另一套字符串。
- 建议修法： 在 PY 增加 `__str__`/`describe()` 最小格式化器（union: ` | `.join 成员、intersect: ` & `.join，对齐 index.ts:891-898），union/intersect 抛错处改用它；data 侧已用 `json.dumps(..., default=str)` 近似 `JSON.stringify`，可保留。

### D3: toJSON 序列化丢失 callback/constructor/preserve 节点
- TS: `index.ts:296-303`（`{...this}` 展开全部自有可枚举属性，经 JSON round-trip 后：callback 经 839 的 `callback.toJSON` 序列化为源码字符串、constructor 函数经 845 序列化为 name、preserve 布尔保留）
  ```ts
  globalThis.__schemastery_refs__ = { [this.uid]: { ...this } as Schema }
  globalThis.__schemastery_refs__[this.uid] = JSON.parse(JSON.stringify({ ...this }))
  const result = { uid: this.uid, refs: globalThis.__schemastery_refs__ }
  ```
- PY: `schema.py:444-462` — node 手工构建，仅含 `uid/type/meta/value/inner/sKey/list/dict/bits`；`callback`（活函数对象）、`constructor`、`preserve` 一律不写入；无 JSON round-trip（refs 表内残留不可 JSON 化的 Python callable 时 `json.dumps` 直接失败）。
- 判定： **MUST-FIX**
- 影响： transform（preserve/callback）与 is（函数 constructor）类 schema 无法序列化落盘/过线，Web GUI 或配置导出拿到的是残缺节点；反序列化侧（D4）即便补齐也无源可恢复。
- 建议修法： node 中补 `"preserve": self.preserve`；`callback` 用 `inspect.getsource`/`__repr__` 产出可逆字符串（TS 语义 = `callback.toString()`）；`constructor` 为 type 时写 `ctor.__name__`、为 str 时原样。

### D4: refs 反序列化（uid→Schema 重接线）整体缺失
- TS: `index.ts:244-255`
  ```ts
  if (options.refs) {
    const refs = valueMap(options.refs, options => new Schema(options))
    const getRef = (uid: any) => refs[uid]!
    for (const key in refs) {
      const options = refs[key]!
      options.sKey = getRef(options.sKey); options.inner = getRef(options.inner)
      options.list = options.list && options.list.map(getRef)
      options.dict = options.dict && valueMap(options.dict, getRef)
    }
    return refs[options.uid!]
  }
  ```
  配套 `index.ts:258-263`：反序列化时 callback 字符串经 `new Function('return ' + s)()` 还原。
- PY: `schema.py:113-135`（`__init__` 仅 `setattr` 逐键赋值；无 refs 键处理、无 `sKey` 驼峰→`s_key` 蛇形映射、无 callback 字符串还原）。
- 判定： **MUST-FIX**（若 PY 侧确无任何序列化消费方，可降级为 ADAPT；但对照「Portable Release + Web GUI 配置往返」使命，至少需补 `Schema.fromJSON(data)` 一个入口）
- 影响： `toJSON` 产物是单向的：`{uid, refs}` 表无法还原为可用 Schema 树；含共享/递归引用（lazy、复用 inner）的 schema 无法跨进程重建。
- 建议修法： 新增 classmethod `Schema.fromJSON(payload)`：先按 refs 表逐项 `cls(node)` 实例化（注意 `sKey`→`s_key` 键名转换、uid 以节点值为准不要重新编号），第二轮遍历将 inner/s_key/list/dict 的 uid 替换为实例；callback 源码串按白名单 eval 或存为惰性字符串（PY 3.8 无 `Function`，需定义还原策略并在报告中记录）。

### D5: number step 校验算法 — 精确十进制移位 vs epsilon 取模
- TS: `index.ts:629-637`
  ```ts
  function isMultipleOf(data: number, min: number, step: number) {
    step = Math.abs(step)
    if (!/^\d+\.\d+$/.test(step.toString())) return (data - min) % step === 0
    const digits = step.toString().slice(index + 1).length
    return Math.abs(decimalShift(data, digits) - decimalShift(min, digits)) % decimalShift(step, digits) === 0
  }
  ```
- PY: `schema.py:879-884` — `diff = abs(data - min_v)`，`abs(diff % step) > 1e-9 and abs((diff % step) - step) > 1e-9` 判错；无 `decimalShift` 对应物。
- 判定： **DEVIATION-PERMITTED**（无偏离规则强制，但典型配置数值域内两者结果一致；差异仅在极大数值与 1e-9 邻近容差边界）
- 影响： step=0.01、data=1e15 量级时浮点误差可能超过 1e-9 产生假阳性/假阴性。
- 建议修法： 可选移植 decimalShift（纯 Python 可实现，无兼容障碍）；若保留 epsilon 方案，建议注释标注与 TS 的偏差。

### D6: intersect 全成员返回 null 时 — PY 修复了 TS 的崩溃
- TS: `index.ts:793`
  ```ts
  if (!strict && isPlainObject(data)) merge(result, data)  // result 可能为 undefined → `key in undefined` TypeError
  ```
- PY: `schema.py:1059-1061`
  ```py
  if not strict and isinstance(data, dict):
      if res is None:
          res = {}
  ```
- 判定： **DEVIATION-PERMITTED**（PY 侧防御性 bugfix；1:1 复刻 TS 崩溃无价值）
- 影响： `intersect` 成员全部对 null 数据放行时 PY 正常返回合并结果，TS 抛 TypeError。
- 建议修法： 保持 PY 现状，在移植日志登记该已知偏离。

### D7: transform callback 调用约定 — TS 恒单参，PY 按签名双参
- TS: `index.ts:798-811` — `callback!(result)` / `callback!(adapted)` 仅传 1 参（类型标注的 `options` 形参运行期恒为 undefined）。
- PY: `schema.py:1072-1077`
  ```py
  transformed = schema.callback(res, opt) if p_count >= 2 else schema.callback(res)
  ...
  t_adapted = schema.callback(adapted if adapted is not None else data, opt) if p_count >= 2 else ...
  ```
- 判定： **ADAPT**（Python 回调生态无单参强约定，按 `inspect` 探测签名是 3.8 兼容的合理选择）
- 影响： PY 回调可读取 `opt["path"]/["root"]` 等，TS 同名回调拿不到 —— 回调跨语言移植时行为面更宽。
- 建议修法： 在 `Schema.transform` docstring 标注「PY 回调可接收 (value, options)」，阻止误判为缺陷。

### D8: bitset — meta.default 缺失时的 adapted 返回
- TS: `index.ts:672-673`
  ```ts
  if (value === meta.default) return [value]   // default 为 undefined 时恒 false
  return [value, keys]
  ```
- PY: `schema.py:912-915`
  ```py
  default_val = schema.meta.get("default", 0)   # 缺省按 0
  if val == default_val:
      return val, None
  ```
- 判定： **DEVIATION-PERMITTED**（工厂路径 `Schema.bitset()` 两边都强制 `meta.default = 0`（index.ts:856-858 ↔ schema.py:683），仅手工 `Schema({"type":"bitset"})` 绕过工厂时可见差异）
- 影响： 绕过工厂构造时 TS 把 `keys` 作为 adapted 写回宿主 object，PY 不写回。
- 建议修法： 可忽略；若追求严格 1:1，改为 `default_val = schema.meta.get("default")` 并用 `default_val is not None and val == default_val` 判定。

### D9: property autofix — 数组元素失败时 PY 重新抛出
- TS: `index.ts:706-710`
  ```ts
  } catch (e) {
    if (!options?.autofix) throw e
    delete data[key]            // 数组上也执行（留下空洞）
    return schema.meta.default
  }
  ```
- PY: `schema.py:950-954` — `if opt.get("autofix") and isinstance(data, dict) and key in data:` 仅 dict 且键存在才修复，否则 `raise e`。
- 判定： **DEVIATION-PERMITTED**（JS `delete arr[i]` 留洞本身是宿主语言特有行为，PY 列表无对应物）
- 影响： `array` 元素校验失败 + autofix 开启时：TS 返回 default 并继续，PY 整体抛 ValidationError。
- 建议修法： 保持现状并登记；若需对齐，PY 可对 list 分支将 `data[key]` 置 None 后返回 default。

### D10: is resolver — constructor 非法类型时 PY 直接放行
- TS: `index.ts:685-694` — else 分支将 constructor 一律按字符串走原型链比对，不匹配即抛 `expected ${constructor} but got ${data}`。
- PY: `schema.py:936-937` — `return data, None`（ctor 既非 type 也非 str 时无校验放行）。
- 判定： **DEVIATION-PERMITTED**（`Schema.is_()` 工厂只会产出 type/str 两种 ctor；该分支不可达）
- 影响： 仅手工构造非法 Schema 时 PY 静默放行、TS 报错。
- 建议修法： 可忽略；严格对齐则改为抛 `ValidationError(f"expected {ctor} but got {data}", opt)`。

### D11: PY-only — `_dynamic` 每次 resolve 重建 builder
- PY: `schema.py:828-831` — `if getattr(schema, "_dynamic", False): built = schema.builder()` 无缓存；TS `lazy`（index.ts:581-587）首次构建后 `schema.inner` 永久缓存。
- 判定： **DEVIATION-PERMITTED**（服务 `Schema.dynamic/computed` PY-only 工厂；标准 `Schema.lazy` 路径 832-837 仍缓存，与 TS 一致）
- 影响： dynamic schema 的 builder 副作用（如读取运行时 ctx）每次求值刷新，语义为「惰性重算」而非 TS 的「惰性单例」。
- 建议修法： 在 docstring 明确与 TS lazy 的缓存差异即可。

### D12: PY-only 扩展面
- PY: `schema.py:24-43`（ValidationError issues 聚合模式 + "invalid config:\n" 前缀）、`schema.py:191-199`（`optional`/`nullable`）、`schema.py:262-265`（`badges`）、`schema.py:468-492`（`to_json` 无 refs 嵌套序列化）、`schema.py:494-569`（`to_json_schema`）、`schema.py:747-752`（`computed`）。TS index.ts 均无对应符号。
- 判定： **DEVIATION-PERMITTED**（超集扩展，未见破坏既有语义；`to_json` 对共享引用不去重、理论上遇环会死循环，需注意勿用于递归 schema）
- 影响： 序列化出口存在两套（refs 版/嵌套版），消费方可能混淆。
- 建议修法： 在 `to_json` docstring 标注「仅适用于无共享/环引用的树」。

### D13: dict 键改名写回时机 — 循环内即时 vs 循环后统一
- TS: `index.ts:731-732`
  ```ts
  result[rKey] = property(data, key, inner!, options)
  data[rKey] = data[key]        // for-in 迭代中变更宿主对象
  if (key !== rKey) delete data[key]
  ```
- PY: `schema.py:983-990` — 先收集 `renamed`，循环结束后统一 `data[new_k] = data[old_k]; del data[old_k]`。
- 判定： **DEVIATION-PERMITTED**（TS 的 for-in 迭代中新增键是否被再次访问属实现定义行为；PY 方案规避之，终态一致）
- 影响： 极端场景（两个原键映射到同一 rKey 且其一尚未迭代）TS 可能对已改写值二次校验，PY 不会；终态数据一致。
- 建议修法： 保持现状。

### D14: 默认值时机核对（一致，记录确认结论）
- TS: `index.ts:474-484` — nullable 输入 → `required` 抛错 → intersect 链下钻取 fallback → `data = clone(fallback)`（cosmokit clone 深拷贝+环保护，types.ts:89-115）→ 才进类型 resolver；loose 兜底 `return [schema.meta.default]` 不 clone（index.ts:493）。
- PY: `schema.py:792-802` + `schema.py:810-813` — 同序；`copy.deepcopy(fallback)`；loose 兜底同样直接引用 `meta.get("default")` 不深拷。
- 判定： **等价**（`clone`↔`deepcopy` 为 ADAPT；loose 兜底共享 default 引用的隐患两边刻意保持一致）
- 影响： 无。
- 建议修法： 无。

## 测试缺口

### T1: intersect 同键冲突合并语义 — 「`if (key in result) continue` (index.ts:745-750)」
现有 `test_schema_union_and_intersect`(tests/test_cordis_schema_1to1.py:80-93) 与 `test_schema_intersect_varargs`(tests/test_schemastery_advanced.py:5-12) 全部使用不相交键。缺：两成员声明同名键（含嵌套 dict）断言 first-wins skip —— 该用例当前会**失败**（暴露 D1），是 D1 的回归锚点。

### T2: union/intersect 失败错误文案 — 「`expected ${toString()} but got ${JSON.stringify(data)}` (index.ts:774)」
无任何测试断言 union/intersect 的 ValidationError message 文本。缺：`pytest.raises(ValidationError, match=...)` 锁定类型串格式（同时锁定 D2 修复目标）。

### T3: 序列化往返与 refs 恢复 — 「`return refs[options.uid!]` (index.ts:254)」
全部 4 个 schema 测试文件无一条 toJSON/反序列化用例。缺：含 transform(callback)/is(ctor)/preserve 的 schema → `toJSON` → 断言 refs 表含 callback 源串与 constructor name（D3）；含共享 inner 的 schema 往返后 uid 引用完整（D4）。

### T4: number step 十进制步长边界 — 「`decimalShift` (index.ts:618-637)」
无 step 相关测试（natural/percent 测试仅走 happy path）。缺：step=0.01 + 非倍数（如 0.015）报错、step=0.01 + 大数值倍数通过。

### T5: 默认值深拷贝隔离 — 「`data = clone(fallback)` (index.ts:483)」
无测试证明校验产物的 object 默认值突变不污染 `meta.default`（连续两次校验第二条不被第一条污染）。缺：`Schema.object({...})` 校验两次、第一次产物内嵌 dict 突变后第二次仍得初始值。

### T6: dict sKey 改名写回 — 「`data[rKey] = data[key]; if (key !== rKey) delete data[key]` (index.ts:731-732)」
`test_schema_object_and_dict`(test_cordis_schema_1to1.py:47) 未覆盖 sKey 非恒等映射。缺：sKey=number() 时输入 `{"1": v}` → 输出键与宿主 data 的改名终态断言。

### T7: autofix 行为 — 「`delete data[key]; return schema.meta.default` (index.ts:706-710)」
无 autofix 用例。缺：object 属性失败 + autofix → 键被删除且返回 default；array 元素失败 + autofix → 记录 D9 的 PY 现状行为。

### T8: required + intersect fallback 下钻 — 「`while (current?.type === 'intersect' && isNullable(fallback))` (index.ts:478-481)」
无 nullable 输入命中 required / intersect 链下钻取默认值的用例。缺：`intersect([...])` 传 None → 得第一成员 default；`Schema.string().required()` 传 None → 抛 "missing required value"。

## PROBE 候选

- D1: `Schema.intersect([Schema.object({"a": Schema.object({"x":…, "y":…})}), Schema.object({"a": Schema.object({"x":…, "z":…})})])({"a": {...}})` — 验证同键嵌套 dict 是 first-wins skip（TS 语义）还是深合并（PY 现状）。
- D3/D4: `Schema.transform(Schema.string(), lambda v: v.upper(), preserve=True)` 与 `Schema.is_(datetime.datetime)` 各自 `toJSON()` → 检查 refs 表节点是否含 callback 串/constructor name/preserve；随后尝试从 refs 表重建并校验一个值（预期当前失败）。
- D5: `Schema.number().step(0.01).min(0)` 校验 `1e15 + 0.005` 与 `1e15`，对比 TS 判定。
- D6: `Schema.intersect([Schema.any(), Schema.any()])( {"k": 1} )`（两成员对 dict 数据均返回非 dict 值的变体：`Schema.union` 成员返回 null）→ 验证 TS 崩溃路径 vs PY 补 `{}`。
- D8: `Schema({"type": "bitset", "bits": {"a": 1}})`（绕过工厂，无 default）校验 `0` → 检查返回元组第二元素（TS=`keys`，PY=`None`）。
- D9: `Schema({"type":"array","inner":Schema.number()})` 以 `options={"autofix": True}` 校验 `[1, "x"]` → TS 得 `[1, default]`，PY 抛错。
