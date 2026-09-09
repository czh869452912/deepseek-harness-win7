# G8-logger 盲审报告

## 审计范围澄清（影响全文判定）

指定 TS 权威源为 logger-console（Node/浏览器控制台导出器包），而 `dsh/cordis/logger.py:1-4` 自述移植的是 **cordis 核心日志服务**：

```python
"""
Cordis Logger Service matching reference/vendor/cordis/src/logger.ts
Implements Logger, LoggerService, Exporters, ANSI color hashing, and formatting.
"""
```

- dsh/cordis/logger.py:1-3

即：**被审 Python 文件与指定权威源不在同一层**。logger-console 的全部符号（`ConsoleExporter`/`render`/`showTime`/`showDiff`/`label`/`export()` 落盘/ANSI 探测）在 Python 侧**完全不存在**（全 `dsh/` 树 grep `ConsoleExporter|showTime|showDiff|supports_color|isatty` 均无命中）。因此本报告以 logger-console 为权威源报告缺失项（D1），另以 `reference/vendor/cordis/src/logger.ts`（shared.ts:1 `import { ... Logger, Message } from '@deepseek-ai/cordis'` 的依赖权威源，也是 Python 文件自述的基准）作为核心行为比对依据逐条列差异。

## 映射表

### A. 指定权威源（logger-console）→ Python

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| shared.ts:28 `class ConsoleExporter` | 无 | 缺失（D1） |
| shared.ts:29 `static name = 'logger-console'` | 无 | 缺失（D1） |
| shared.ts:31-42 `static Config`（colors/maxLength/levels/showDiff/showTime/label schema） | 无 | 缺失（D1） |
| shared.ts:44-52 实例字段（colors/maxLength/levels/showDiff/showTime/label/timestamp/formatters） | 无 | 缺失（D1） |
| shared.ts:54-58 `constructor`（`Object.assign(this, this.getDefaults(), config)`；`ctx.logger.exporter(this)`） | 无 | 缺失（D1） |
| shared.ts:60-66 `getDefaults()`（`colors: false`、`showTime: 'yyyy-MM-dd hh:mm:ss '`） | 无 | 缺失（D1） |
| shared.ts:68-71 `export()` → `console.log(this.render(message))` | 无（Python `Exporter.export` 仅回调 `_export_fn`，默认写内存环） | 缺失（D1） |
| shared.ts:73-97 `render()`（`[X]` 前缀、margin、showTime 着色 code 8、name 着色、padStart/padEnd、align、indent 换行缩进、showDiff `+Xs`、timestamp 更新） | 无 | 缺失（D1） |
| shared.ts:6 `ColorSupportLevel`、shared.ts:9-13 `LabelStyle` | 无 | 缺失（D1） |
| index.ts:9-11 `inspectFormatter`（`util.inspect`，注册为 `o`/`O`） | 无 | 缺失（D1） |
| index.ts:14-26 Node `ConsoleExporter`（`formatters = { o, O }`；getDefaults `colors: supportsColor.stdout?.level ?? 0`） | 无（全仓无 supports-color/isatty 等价物） | 缺失（D1） |
| index.ts:28 / shared.ts:100 / browser.ts:17 default export | 无 | 缺失（D1） |
| browser.ts:8-15 browser `ConsoleExporter`（`console.error/warn/log` 分发，原始 args 透传） | 无 | 缺失（D1） |

### B. Python 顶层符号 → cordis 核心权威源（reference/vendor/cordis/src/logger.ts，补充依据）

| TS 符号 (logger.ts:line) | Python 符号 (logger.py:line) | 状态 |
|---|---|---|
| logger.ts:165 `c16` | logger.py:16 `c16` | 1:1 |
| logger.ts:167-173 `c256` | logger.py:17-23 `c256` | 1:1 |
| logger.ts:22-27 `LoggerLevel` | logger.py:26-30 `LoggerLevel` | 1:1 |
| logger.ts:30-38 `Message`（interface，含 `fiber?: WeakRef`） | logger.py:33-65 `Message`（+`meta`/`to_dict()`/`type` 默认 `"info"`） | D13 |
| logger.ts:41-47 `Exporter`（interface） | logger.py:68-86 `Exporter`（class + `_export_fn` + 默认参数） | D13 |
| logger.ts:84-87 `Logger.color` | logger.py:89-95 `default_color`（logger.py:119 挂为 `Logger.color`） | 1:1 |
| logger.ts:89-97 `Logger.code` | logger.py:98-111 `default_code`（logger.py:120 挂为 `Logger.code`） | D10 |
| logger.ts:99-131 `Logger.format` | logger.py:128-205 `Logger.format` | D2–D8 |
| logger.ts:141-161 `Logger._method` | logger.py:207-239 `Logger._method` | 1:1（D7 见 format 侧） |
| logger.ts:135-138 构造器绑定 error/info/warn/debug | logger.py:241-251 `error/info/warn/debug` | 1:1 |
| logger.ts:203-224 `LoggerService` 构造器（createCallable/tracker/shadow、默认 buffer exporter） | logger.py:262-276 `LoggerService.__init__` | ADAPT*（无 callable 包装/tracker/shadow；buffer 环 1000 与 colors=3 一致） |
| logger.ts:152/154（`++_snMessage`、遍历 exporters） | logger.py:278-280 `_next_message_sn`、logger.py:235-239 | 1:1 |
| logger.ts:232-237 `LoggerService.exporter()`（含 teardown 删当前 `_snExporter` 的上游 quirk） | logger.py:282-299 `exporter()`（logger.py:291-293 复刻同一 quirk） | 1:1 |
| 无（TS 无此符号） | logger.py:301-305 `_bind` | Python-only（D13） |
| logger.ts:239-249 `_resolveConfig()`（intercept 原型链） | logger.py:307-320 `resolve_intercept_config()`（ctx 父链 + `_intercept_map`） | D11 |
| logger.ts:251-261 `[symbols.invoke]()` | logger.py:322-332 `__call__` | D12 |
| logger.ts:263-269 静态 error/info/warn/debug 快捷方式 | logger.py:334-344 `error/info/warn/debug` | 1:1 |
| 无 | logger.py:260 `name = "logger"` | Python-only（D13） |

\* ADAPT 备注按规则口径：createCallable/tracker 属 JS 运行时元编程，Python 无对应语言设施，但不属于允许偏离清单两条，严格计为 D13 记录项。

## 差异

### D1: logger-console `ConsoleExporter` 整层未移植（渲染/落盘/ANSI 探测全缺）
- TS: reference/vendor/logger-console/src/shared.ts:73-90
  ```ts
  render(message: Message) {
    const prefix = `[${message.type[0].toUpperCase()}]`
    const space = ' '.repeat(this.label?.margin ?? 1)
    let indent = 3 + space.length, output = ''
    if (this.showTime) {
      indent += this.showTime.length
      output += Logger.color(this, 8, Time.template(this.showTime))
    }
    const code = Logger.code(message.name, this.colors)
  ```
  以及 shared.ts:68-71 `export()` 落 stdout、index.ts:20-25 `colors: (supportsColor.stdout ? supportsColor.stdout.level : 0)`、index.ts:15-18 `formatters = { o: inspectFormatter, O: inspectFormatter }`、browser.ts:9-14 `console[method](prefix, ...message.args)`。
- PY: dsh/cordis/logger.py:84-86 `export()` 仅转发 `_export_fn`；默认导出器写内存环（logger.py:271-276）。全 Python 树无 `render`/`showTime`/`showDiff`/`label`/`[X]` 前缀/padStart/padEnd/console 落盘/supports-color 探测（grep 证实）。
- 判定: MUST-FIX
- 影响: 指定权威源的三种构建（shared/index/browser）无任何 Python 对应物；日志只进内存，永不落终端；stdout/stderr 对应物与 ANSI 禁用判定（`colors=false|0..3` 的推导）均不存在。
- 建议修法: 新增 `dsh/cordis/console_exporter.py`（或等价文件）1:1 移植 shared.ts `ConsoleExporter`（render 的 prefix/space/indent/padLength/align/showDiff/timestamp 全字段）+ index.ts 的 `o/O=inspect`（Python 以 `repr`/`pprint.pformat` 等价物并标注 ADAPT）+ browser 版的 method 分发不需要（无浏览器运行时，记录为 N/A）；ANSI 探测用 `sys.stdout.isatty()` + `os.environ.get("TERM")`/Windows API 等价物替代 supports-color（偏离清单第 2 条允许的 ADAPT，需标注）。

### D2: `%s` 对 `None` 打印 `"undefined"`（自发明分支）
- TS: reference/vendor/cordis/src/logger.ts:50-51
  ```ts
  export const defaultFormatters: Record<string, Formatter> = {
    s: (value) => String(value),
  ```
  （`String(null)` → `"null"`，无 `undefined` 特判；缺失实参时 `String(undefined)` → `"undefined"`）
- PY: dsh/cordis/logger.py:154-155
  ```python
  if ch == "s":
      return "undefined" if val is None else str(val)
  ```
- 判定: DEVIATION-PERMITTED
- 影响: 缺失实参（`args.pop(0)` 得 None，logger.py:151）时与 TS `"undefined"` 一致；但显式传 `None` 时 TS 语义（JS `null` → `"null"`）被替换为 `"undefined"`，输出可察觉。
- 建议修法: 保留现状可接受；若追求严格，需在文档记录"Python `None` 统一映射 JS `undefined`"的语义约定，不改代码。

### D3: `%d`/`%i` 遇 `±Infinity` 抛未捕获 `OverflowError`；`None`/`""` 语义偏移
- TS: reference/vendor/cordis/src/logger.ts:52-53
  ```ts
  d: (value) => Math.trunc(Number(value)),
  i: (value) => Math.trunc(Number(value)),
  ```
  （`Number(null)=0`、`Number("")=0`、`Math.trunc(Infinity)=Infinity` → `"Infinity"`，永不抛错）
- PY: dsh/cordis/logger.py:156-163
  ```python
  if ch in ("d", "i"):
      try:
          f_val = float(val)
          if math.isnan(f_val):
              return "NaN"
          return str(int(math.trunc(f_val)))
      except (ValueError, TypeError):
          return "NaN"
  ```
  `math.trunc(float("inf"))` 抛 `OverflowError`，不在捕获列表 → 异常穿出 `re.sub`，**日志调用整体崩溃**；且 `float(None)`/`float("")` → `"NaN"`（TS 为 `"0"`）、`float("0x10")` → `"NaN"`（JS `Number("0x10")=16`）。
- 判定: MUST-FIX
- 影响: `%d` 收到 `inf` 时从"打印 Infinity"变为抛异常中断日志（可能中断业务路径）；null/空串语义从 0 变 NaN。
- 建议修法: `replace_placeholder` 的 `d/i` 分支在 `math.isinf(f_val)` 时返回 `"Infinity"`/`"-Infinity"`（对齐 JS `String(Math.trunc(±Infinity))`），并把 `OverflowError` 加入 except；None/"" 是否对齐 TS 的 0 语义需产品裁决（建议按 D3 一并记录）。

### D4: `%f` 的 `None`/`""` → `"NaN"`（TS 为 `"0"`）；`inf` → `"inf"`（TS 为 `"Infinity"`）
- TS: reference/vendor/cordis/src/logger.ts:54
  ```ts
  f: (value) => Number(value),
  ```
- PY: dsh/cordis/logger.py:164-171
  ```python
  if ch == "f":
      try:
          f_val = float(val)
          if math.isnan(f_val):
              return "NaN"
          return str(f_val)
      except (ValueError, TypeError):
          return "NaN"
  ```
- 判定: DEVIATION-PERMITTED
- 影响: 边缘实参下的字符串表示差异（`0` vs `NaN`、`Infinity` vs `inf`），量级小但可察觉。
- 建议修法: 如需严格，`f` 分支对 `isinf` 返回 `"Infinity"`/`"-Infinity"`；None/"" 维持 NaN 并记录。

### D5: `%o`/`%O` 的 undefined/NaN/循环引用行为差异
- TS: reference/vendor/cordis/src/logger.ts:55-56
  ```ts
  o: (value) => JSON.stringify(value),
  O: (value) => JSON.stringify(value),
  ```
  （`JSON.stringify(undefined)` 返回 `undefined` 值 → 占位符渲染为 `"undefined"`；`JSON.stringify(NaN)` → `"null"`；循环引用抛 `TypeError` 冒泡）
- PY: dsh/cordis/logger.py:172-176
  ```python
  if ch in ("o", "O"):
      try:
          return json.dumps(val, default=str, ensure_ascii=False)
      except Exception:
          return str(val)
  ```
  （顶层 `None` → `"null"`；`float("nan")` → `"NaN"`；循环引用被 `except Exception` 吞为 `str(val)`）
- 判定: DEVIATION-PERMITTED
- 影响: 顶层 undefined/NaN 表示差异；Python 的循环引用兜底为自发明防御行为（TS 会抛错）。
- 建议修法: 记录许可；若严格对齐，顶层 `None` 返回 `"undefined"`、非有限浮点返回 `"null"`，并移除或收窄 `except Exception`（至少命名被吞对象）。

### D6: 剩余参数拼接：非 dict/list 对象、`None`、bool 不走 oFormatter/JSON
- TS: reference/vendor/cordis/src/logger.ts:119-125
  ```ts
  const oFormatter = exporter.formatters?.o ?? defaultFormatters.o
  for (let arg of args) {
    if (typeof arg === 'object' && arg) {
      arg = oFormatter(arg, exporter, message)
    }
    format += ' ' + arg
  }
  ```
  （任意非 null 对象 → `JSON.stringify`；`null` → `" null"`；`true` → `" true"`）
- PY: dsh/cordis/logger.py:186-196
  ```python
  o_formatter = exporter.formatters.get("o") if exporter.formatters else None
  for remaining in args:
      if o_formatter is not None and not isinstance(remaining, (str, int, float, bool)):
          res += " " + str(o_formatter(remaining, exporter, message))
      elif isinstance(remaining, (dict, list)):
          res += " " + json.dumps(remaining, default=str, ensure_ascii=False)
      else:
          res += f" {remaining}"
  ```
  tuple/set/datetime/自定义对象 → `str()`（如 `"(1, 2)"`/`"<Foo object>"`，TS 为 `"[1,2]"`/`{...}` JSON 文本）；`None` → `" None"`（TS `" null"`）；`True` → `" True"`（TS `" true"`）。
- 判定: MUST-FIX
- 影响: 结构化数据的终端呈现语义不同：TS 保证非空对象一律 JSON 化，Python 仅覆盖 dict/list，其余退化为 `repr/str`，属自发明行为。
- 建议修法: `Logger.format` 剩余参数循环改为：非 `None` 且非 (str/int/float/bool) 的对象一律走 oFormatter（无自定义时用 `defaultFormatters.o` 等价的 `json.dumps`）；同时统一 bool 渲染为 `true/false`（或在报告中记录全局 str 化约定）。

### D7: 无参调用 / `None` 首参 → 空串（TS 打印 `"undefined"`/`"null"`）
- TS: reference/vendor/cordis/src/logger.ts:104-106
  ```ts
  } else if (typeof args[0] !== 'string') {
    args.unshift('%o')
  }
  ```
  （`logger.info()` → `args[0]===undefined` → `'%o'` → 渲染 `"undefined"`；`logger.info(null)` → `"null"`）
- PY: dsh/cordis/logger.py:129-132 与 logger.py:217
  ```python
  args = list(message.args)
  if not args:
      return ""
  ```
  ```python
  all_args = [format_str] + list(args) if format_str is not None else list(args)
  ```
- 判定: DEVIATION-PERMITTED
- 影响: 仅空调用边缘路径输出不同（TS 恒有串，Python 允许空串）。
- 建议修法: 可保留；若严格对齐，`args` 为空时按 `'%o'`+`undefined` 路径渲染。

### D8: 行切分用 `splitlines()`，多余 Unicode 分行点
- TS: reference/vendor/cordis/src/logger.ts:128-130
  ```ts
  return format.split(/\r?\n/g).map(line => {
    return line.slice(0, maxLength) + (line.length > maxLength ? '...' : '')
  }).join('\n')
  ```
- PY: dsh/cordis/logger.py:199-205
  ```python
  lines = []
  for line in res.splitlines():
      if len(line) > max_len:
          lines.append(line[:max_len] + "...")
      else:
          lines.append(line)
  return "\n".join(lines)
  ```
  `str.splitlines()` 还会在 `\v \f \x1c-\x1e \x85 \u2028 \u2029` 处分行（TS 仅 CRLF/LF），截断点与 join 结果随之偏移。
- 判定: MUST-FIX
- 影响: 含 `\u2028/\u2029`（JSON 常见转义来源）或 `\x85` 的行被错误切分并各自加 `...`。
- 建议修法: `Logger.format` 末段改用 `re.split(r"\r?\n", res)` 精确对齐 TS。

### D9: Exception 首参栈文本用 `traceback.format_exception`
- TS: reference/vendor/cordis/src/logger.ts:101-103
  ```ts
  if (args[0] instanceof Error) {
    args[0] = args[0].stack || args[0].message
    args.unshift('%s')
  }
  ```
- PY: dsh/cordis/logger.py:134-138
  ```python
  if isinstance(args[0], Exception):
      err = args[0]
      tb_str = "".join(traceback.format_exception(type(err), err, err.__traceback__)) if getattr(err, "__traceback__", None) else str(err)
      args[0] = tb_str
      args.insert(0, "%s")
  ```
- 判定: DEVIATION-PERMITTED
- 影响: 栈文本格式不同（Python Traceback vs JS stack），为运行时固有限制；`stack || message` 的回退语义由 `__traceback__` 有无近似。
- 建议修法: 无需改码；在移植说明中记录"Error.stack ↔ traceback.format_exception"等价映射。

### D10: `default_code` 自发明默认 `level=3` 与空调色板返回 0
- TS: reference/vendor/cordis/src/logger.ts:89-96
  ```ts
  static code(name: string, level?: false | number) {
    let hash = 0
    for (let i = 0; i < name.length; i++) {
      hash = ((hash << 3) - hash) + name.charCodeAt(i) + 13
      hash |= 0
    }
    const colors = !level ? [] : level >= 2 ? c256 : c16
    return colors[Math.abs(hash) % colors.length]
  }
  ```
  （无参调用 `level` 为 undefined → `colors=[]` → 返回 `undefined`）
- PY: dsh/cordis/logger.py:98, 103-111
  ```python
  def default_code(name: str, level: Optional[int] = 3) -> int:
  ...
      if not level:
          colors = []
      ...
      if not colors:
          return 0
      return colors[abs(signed_h) % len(colors)]
  ```
- 判定: DEVIATION-PERMITTED
- 影响: 所有现存调用点（logger.py:180、shared.ts 对应逻辑在 Python 侧不存在）均显式传 level，默认值与 0 回退不可达；仅 API 形状差异。
- 建议修法: 去掉默认值或记录；哈希算法本身（含 `|=0` 的 int32 环绕与 `Math.abs`）已逐位等价，tests/1to1/cordis/test_logger_parity.py T1 已钉测。

### D11: `resolve_intercept_config` 遍历机制不同且存在冗余重复合并
- TS: reference/vendor/cordis/src/logger.ts:239-249
  ```ts
  private _resolveConfig(): LoggerService.Intercept {
    let intercept = this.ctx[symbols.intercept]
    const configs: LoggerService.Intercept[] = []
    while ('logger' in intercept) {
      if (Object.hasOwn(intercept, 'logger')) {
        configs.unshift(intercept['logger'])
      }
      intercept = Object.getPrototypeOf(intercept)
    }
    return Object.assign({}, ...configs)
  }
  ```
- PY: dsh/cordis/logger.py:307-320
  ```python
  curr = self.ctx
  while curr is not None:
      intercept_map = getattr(curr, "_intercept_map", {})
      if "logger" in intercept_map and isinstance(intercept_map["logger"], dict):
          configs.insert(0, intercept_map["logger"])
      curr = getattr(curr, "_parent", None) or getattr(curr, "parent", None)
      if curr is getattr(curr, "root", None) and curr is self.ctx:
          break
  ```
  Python 侧 `_intercept_map` 在建子 ctx 时已整份复制（dsh/cordis/context.py:321 `child._intercept_map = dict(self._intercept_map)`），父链逐级再收一遍同一 config dict，重复 `update` 对纯 dict 幂等，结果次序（根先叶后、叶覆盖）与 TS 一致；末行 break 条件（`curr is getattr(curr, "root", None) and curr is self.ctx`）仅在起点为根时触发，属怪异短路。
- 判定: DEVIATION-PERMITTED
- 影响: 对 dict 配置结果等价；若未来 config 为含副作用的非常量值，重复合并可产生可观察差异；遍历方向/终止条件与 TS 语义不同构。
- 建议修法: 收集时按 identity 去重（`id(cfg)` 已见即跳过），或直接用 `self.ctx._intercept_map`（复制语义已含祖先），并简化/删除末行短路。

### D12: `__call__` 的 `"root"` 名称回退与缺失 shadow-context
- TS: reference/vendor/cordis/src/logger.ts:251-256
  ```ts
  [symbols.invoke](name?: string): Logger {
    const config = this._resolveConfig()
    const fiber = ((this.ctx as any)[symbols.shadow] ?? this.ctx).fiber
    name ??= config.name
    name ??= hyphenate(fiber.name)
  ```
- PY: dsh/cordis/logger.py:326-330
  ```python
  fiber = getattr(self.ctx, "fiber", None)
  target_name = name or config.get("name")
  if not target_name:
      fname = getattr(fiber, "name", "root") if fiber else "root"
      target_name = hyphenate(fname) if fname else "root"
  ```
  TS 无 `"root"` 回退（fiber.name 视为恒存在），Python 自发明 `"root"`；TS 先取 shadow ctx 的 fiber，Python 直接 `self.ctx.fiber`。
- 判定: DEVIATION-PERMITTED
- 影响: 仅在 fiber 缺失/无名时名称不同（`"root"` vs 异常路径）；shadow 语义在 Python Context 模型中以 `_bind`/服务复制近似。
- 建议修法: 记录 `"root"` 回退为移植约定；如需严格，让缺失时抛错以暴露调用方误用。

### D13: Python 侧自发明附加物（无 TS 对应）
- TS: reference/vendor/cordis/src/logger.ts:30-38（`Message` 仅 sn/ts/name/type/level/args/fiber）与 logger.ts:141-161（`_method` 内 `{...this.meta}` 展开进消息顶层）
  ```ts
  const message: Message = { sn, ts, type, level, name: this.name, ...this.meta, args }
  ```
- PY: dsh/cordis/logger.py:54 `self.meta = meta or {}`（消息携带独立 `meta` 字段）、logger.py:56-65 `to_dict()`、logger.py:50 `type or msg_type or "info"` 默认、logger.py:70-77 `Exporter` 默认参数（`colors=3`/`max_length=10240`/`export_fn` 可调用结构）、logger.py:260 `name = "logger"`、logger.py:297-299 `exporter()` 无 `ctx.effect` 时直接 `setup()` 回退、logger.py:301-305 `_bind`。
- 判定: DEVIATION-PERMITTED
- 影响: 均为附加/防御性结构，不改变 TS 定义的可观察行为（fiber 经 logger.py:53/221-222 以 `weakref.ref` 等价落地）；`to_dict()` 的 `str(a) if isinstance(a, Exception)` 是自发明序列化。
- 建议修法: 保留并在移植说明中登记 Python-only 面；`exporter()` 无 effect 回退建议改为 fail-loud（对齐仓库"Misconfiguration fails loud"惯例）。

## 测试缺口

### T1: `%d`/`%i` 的 Infinity 路径 — TS `Math.trunc(Number(value))`（logger.ts:52-53）对 `Infinity` 恒产 `"Infinity"` 且不抛错；Python 现崩溃（D3），无测试钉住
### T2: `%o` 顶层特殊值 — `JSON.stringify(undefined)`→`"undefined"`、`JSON.stringify(NaN)`→`"null"`（logger.ts:55），无钉测（Python 行为相反，见 D5）
### T3: 剩余参数任意对象一律 oFormatter — `if (typeof arg === 'object' && arg) arg = oFormatter(...)`（logger.ts:120-123），含数组/类实例；现有 T5 仅测自定义 o formatter 的 dict 情形，未覆盖默认路径与非 dict/list 对象（D6）
### T4: `maxLength=10240` 截断与 `...` 后缀、仅按 `/\r?\n/` 分行（logger.ts:127-130）— 无任何截断/分行钉测（D8）
### T5: exporter 级别过滤 — `exporter.levels?.[this.name] ?? exporter.levels?.default ?? this.level ?? LoggerLevel.INFO`（logger.ts:155）按名/default/Logger 默认三级回退无钉测
### T6: `Logger.level` 为 undefined 时回退 INFO（logger.ts:155 末位 `?? LoggerLevel.INFO`；Python 在构造期默认，logger.py:125）无行为级钉测
### T7: `%c` 消耗实参返回空串与 `%C` 按 `message.name` 取色（logger.ts:57-60）无钉测
### T8: logger-console `render()` 布局（prefix `[X]`、margin、`padStart/padEnd`、`align: 'right'`、showTime 着色 code 8、showDiff ` +Xs`，shared.ts:73-97）— 因 D1 无实现而无测试
### T9: index.ts `getDefaults()` 的 `colors: supportsColor.stdout ? ... : 0`（index.ts:20-25）与 browser.ts `console.error/warn/log` 分发（browser.ts:9-14）— 无实现无测试
### T10: 环形缓冲上限 1000（logger.ts:195, 216-219）无裁剪行为钉测（现有测试只查 buffer 内容）

## PROBE 候选

- D3: 构造 `Exporter(export_fn=..., colors=3)` + `Message(args=["%d", float("inf")])` 跑 `Logger.format` —— 预期确认 `OverflowError` 穿出 `re.sub`（崩溃路径）；同场景在 Node 侧对 vendor TS 运行 `console.log(new ConsoleExporter(ctx, {colors: 0}).render(...))` 类探针确认 `"Infinity"` 基线。
- D8: `Message(args=["a\u2028b" + "x"*10240])` —— 对比 Python `splitlines()`（在 `\u2028` 处分行→两段各自截断）与 TS `split(/\r?\n/)`（单行整体截断），证明截断偏移可观察。
- D6: exporter 无自定义 `o` formatter 时剩余参数传 `tuple(1,2)`/`set()`/`datetime.now()` —— 证明 Python `str()` 输出与 TS `JSON.stringify` 文本的差异面（现报告按源码判定，运行探针可量化）。
- D5: `%o` 传 `None` 与 `float("nan")` —— Node 侧确认 `"undefined"`/`"null"` 基线后裁决 Python 侧是否需对齐。
- D2/D7: Node 探针运行 `logger.info(null)`/`logger.info()`，确认 `"null"`/`"undefined"` 输出，作为 DEVIATION-PERMITTED 记录的行为基线。
- D11: 子 ctx `intercept("logger", {...})` 后再在父 ctx 修改同一 config 对象（可变 dict），遍历收集是否因复制/共享产生与 TS 不同的合并快照 —— 验证 D11 的"幂等"前提仅在不可变值下成立。
