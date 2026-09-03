# dsh/cordis/logger.py ↔ reference/vendor/cordis/src/logger.ts + reference/vendor/logger-console/src/{shared,index,browser}.ts

比对范围:`dsh/cordis/logger.py`(295 行)对照 `reference/vendor/cordis/src/logger.ts`(270 行)与 `reference/vendor/logger-console/src/shared.ts`(100 行)、`index.ts`(28 行)、`browser.ts`(17 行)。`Message`/`Exporter`/`LoggerLevel` 的结构映射、`bufferSize=1000` 环形缓冲、默认内存 exporter(colors=3)、`error/info/warn/debug` 委托 `self()` 的写法、targetLevel 三级回退(`levels[name] → levels.default → this.level`)均已核对一致。Python 侧差异集中在:哈希符号位、ANSI decoration 门控、printf 占位符边界语义、Error 参数展开、exporter 注册/注销时序,以及 `ctx.logger()` 的名字解析。

## 差异清单

### D1 [MUST-FIX] `Logger.code()` 哈希未按 32 位有符号解释,约一半名字取色错误
- 位置: py:dsh/cordis/logger.py:96-108 vs ts:reference/vendor/cordis/src/logger.ts:89-97
- 原版行为:
  ```ts
  hash = ((hash << 3) - hash) + name.charCodeAt(i) + 13
  hash |= 0                       // 每轮截断为 32 位有符号整数
  const colors = !level ? [] : level >= 2 ? c256 : c16
  return colors[Math.abs(hash) % colors.length]
  ```
  `| 0` 使 hash 为有符号数;当最终值 ≥ 2^31 时为负,`Math.abs` 取 `2^32 - h`。
- 移植版现状:
  ```python
  h = (((h << 3) - h) + ord(ch) + 13) & 0xFFFFFFFF
  ...
  return colors[abs(h) % len(colors)]
  ```
  Python 侧始终按无符号解释。每轮中间运算 mod 2^32 同余,但最终值高位置 1 时 TS 得 `-(2^32 - h)`、Python 得 `h`,`abs` 后取模结果不同(例:h=0xFFFFFFFF → TS 1,Python 3),导致 logger 名字颜色与 TS 不一致。
- 修复方案:循环内保持 `& 0xFFFFFFFF` 掩码;循环结束后补一步有符号重解释:`if h >= 2**31: h -= 2**32`,再 `colors[abs(h) % len(colors)]`。

### D2 [MUST-FIX] `Logger.color()` 在 code < 8 分支无条件拼接 decoration;TS 以 `colors >= 2` 门控
- 位置: py:dsh/cordis/logger.py:88-93 vs ts:reference/vendor/cordis/src/logger.ts:84-87
- 原版行为:
  ```ts
  return `\u001b[3${code < 8 ? code : '8;5;' + code}${exporter.colors >= 2 ? decoration : ''}m${value}\u001b[0m`
  ```
  decoration(`;1` 加粗等)在所有码位上都要求 `colors >= 2` 才输出。
- 移植版现状:
  ```python
  if code < 8:
      return f"\033[3{code}{decoration}m{value}\033[0m"
  return f"\033[38;5;{code}{exporter.colors >= 2 and decoration or ''}m{value}\033[0m"
  ```
  仅 256 色分支做了门控;`colors == 1`(16 色)时 `;1` 仍被输出,ANSI 流与 TS 不同。
- 修复方案:code < 8 分支改为 `f"\033[3{code}{decoration if exporter.colors >= 2 else ''}m{value}\033[0m"`。

### D3 [MUST-FIX] `Logger.format()` 占位符循环:TS 对未知字符不消费参数、对耗尽参数仍调用 formatter;Python 提前返回并吞参数
- 位置: py:dsh/cordis/logger.py:139-172 vs ts:reference/vendor/cordis/src/logger.ts:108-117
- 原版行为:
  ```ts
  format = format.replace(/%([a-zA-Z%])/g, (match, char) => {
    if (match === '%%') return '%'
    const formatter = exporter.formatters?.[char] ?? defaultFormatters[char]
    if (typeof formatter === 'function') {
      const value = args.shift()      // 参数耗尽时为 undefined,formatter 照常调用
      return formatter(value, exporter, message)
    }
    return match                      // 未知字符:保留原文,且不消费参数
  })
  ```
  `"a %s %x"`,值 `1`:TS 输出 `a 1 %x`(参数未多耗);`"%s"` 无参:TS 输出 `undefined`。
- 移植版现状:
  ```python
  if not args:
      return match.group(0)           # 参数耗尽:占位符原样保留
  val = args.pop(0)
  ...
  return str(val)                     # 未知字符:消费参数并输出 str(val)
  ```
  两个方向都偏离:耗尽时 TS 继续以 `undefined` 调 formatter(如 `%s` → `"undefined"`),Python 保留 `%s`;未知字符(如 `%x`)TS 不消费参数,Python 消费并输出多余文本,造成后续占位符错位。
- 修复方案:删除 `if not args: return match.group(0)` 提前返回——命中 formatter 时照常 `args.pop(0)`(可为 None,默认 formatter 输出与 TS `undefined` 对齐的文本);未命中任何 formatter(含自定义表)时 `return match.group(0)` 且不消费参数。

### D4 [MUST-FIX] `%d`/`%i`/`%f` 数值格式化:TS 用 `Math.trunc(Number(v))`/`Number(v)`(非法输入得 `NaN`);Python `int(v)` 失败得 `"0"`,且 `int("3.7")` 抛错
- 位置: py:dsh/cordis/logger.py:148-159 vs ts:reference/vendor/cordis/src/logger.ts:50-56
- 原版行为:
  ```ts
  s: (value) => String(value),
  d: (value) => Math.trunc(Number(value)),
  i: (value) => Math.trunc(Number(value)),
  f: (value) => Number(value),
  ```
  `"%d", "3.7"` → `3`;`"%d", "abc"` → `NaN`;`"%f", "abc"` → `NaN`。
- 移植版现状:
  ```python
  if ch in ("d", "i"):
      try: return str(int(val))
      except (ValueError, TypeError): return "0"
  ```
  `"%d", "3.7"` → `"0"`(int 解析失败);`"%d", "abc"` → `"0"` 而非 `NaN`。
- 修复方案:改为 `float(val)` 后 `math.trunc` 取整(`d`/`i`),`f` 直接 `float(val)`;转换失败输出 `"NaN"`(与 JS `NaN` 字面一致),替代 `"0"`/`"0.0"`。

### D5 [MUST-FIX] 尾随参数处理:TS 统一经 `exporter.formatters.o ?? defaultFormatters.o` 处理一切真值对象;Python 仅处理 dict/list 且写死 json.dumps
- 位置: py:dsh/cordis/logger.py:174-181 vs ts:reference/vendor/cordis/src/logger.ts:119-125
- 原版行为:
  ```ts
  const oFormatter = exporter.formatters?.o ?? defaultFormatters.o
  for (let arg of args) {
    if (typeof arg === 'object' && arg) arg = oFormatter(arg, exporter, message)
    format += ' ' + arg
  }
  ```
  任意非 null 对象(含自定义类实例)都走 `o` formatter;Node ConsoleExporter 借此替换为 `util.inspect`。
- 移植版现状:
  ```python
  for remaining in args:
      if isinstance(remaining, (dict, list)):
          res += " " + json.dumps(remaining, default=str, ensure_ascii=False)
      else:
          res += f" {remaining}"
  ```
  自定义对象落入 `str()` 分支;exporter 自定义的 `formatters["o"]` 对尾随参数完全无效。
- 修复方案:循环前取 `o_fmt = exporter.formatters.get("o")`,对 `isinstance(remaining, object) and remaining is not None`(即非 None 对象)调用 `o_fmt(remaining, exporter, message)`,无自定义时回退到现有 json.dumps 实现。

### D6 [MUST-FIX] 单 Error 参数的 cause / AggregateError 展开逻辑缺失
- 位置: py:dsh/cordis/logger.py:192-209 vs ts:reference/vendor/cordis/src/logger.ts:78-80、141-150
- 原版行为:
  ```ts
  if (args.length === 1 && args[0] instanceof Error) {
    if (args[0].cause) {
      this[type](args[0].cause)          // 先递归记录 cause(无 return,原错误仍会记录)
    } else if (isAggregateError(args[0])) {
      args[0].errors.forEach(error => this[type](error))
      return                             // 聚合错误:逐个记录后不再记录原错误
    }
  }
  ```
- 移植版现状:
  ```python
  all_args = [format_str] + list(args) if format_str is not None else list(args)
  ```
  无任何 Error 特判:带 cause 的异常只记录一条,聚合错误也只记录包装对象本身。
- 修复方案:`_method` 开头增加:恰一个 `Exception` 参数时,若 `__cause__` 非空 → 先 `self.<type>(cause)` 再继续(与 TS 一致地记录两条);elif 异常带非空 `errors` 列表(duck-typed AggregateError/ExceptionGroup)→ 逐个记录后 `return`。

### D7 [MUST-FIX] exporter 抛错被吞掉(print 到 stderr);TS 不捕获、直接向上传播
- 位置: py:dsh/cordis/logger.py:215-218 vs ts:reference/vendor/cordis/src/logger.ts:154-159
- 原版行为:
  ```ts
  for (const exporter of this.service.exporters.values()) {
    ...
    exporter.export(message)             // 无 try/catch
  }
  ```
- 移植版现状:
  ```python
  try:
      exporter.export(message)
  except Exception as e:
      print(f"[Cordis Logger Error] Exporter error: {e}", file=sys.stderr)
  ```
  坏 exporter 只在 stderr 留一行,调用方无感知;TS 中 export 失败会中断本次日志并抛给日志调用点。
- 修复方案:去掉 try/except(如需保留诊断,捕获后 `raise`),使 exporter 异常按 TS 语义传播。

### D8 [MUST-FIX] exporter 注销按"注册时快照 sn"删除;TS disposer 删除的是"当前 `_snExporter`"(上游怪癖,1:1 需复刻)
- 位置: py:dsh/cordis/logger.py:261-274 vs ts:reference/vendor/cordis/src/logger.ts:232-237
- 原版行为:
  ```ts
  exporter(exporter: Exporter) {
    return this.ctx.effect(() => {
      this.exporters.set(++this._snExporter, exporter)
      return () => this.exporters.delete(this._snExporter)   // 读取的是属性当前值
    }, 'ctx.logger.exporter()')
  }
  ```
  先注册 A(sn=1)再注册 B(sn=2)后调用 A 的 disposer,实际删除的是 B。
- 移植版现状:
  ```python
  self._sn_exporter += 1
  sn = self._sn_exporter
  self.exporters[sn] = exporter
  def teardown() -> None:
      self.exporters.pop(sn, None)
  ```
  Python 捕获局部 `sn`,总是删除正确的表项——与 TS 行为在多 exporter 场景可见地不同。
- 修复方案:按 TS 复刻:teardown 改为 `self.exporters.pop(self._sn_exporter, None)`(注销时读取字段当前值),并在代码处注释该上游怪癖。

### D9 [MUST-FIX] exporter 在 `ctx.effect` 之前就写入 map;TS 在 effect 回调内注册(fiber 失活时 TS 不产生残留)
- 位置: py:dsh/cordis/logger.py:265-274 vs ts:reference/vendor/cordis/src/logger.ts:232-237
- 原版行为:`this.exporters.set(...)` 位于传给 `ctx.effect` 的工厂回调内部;fiber 处于 inactive/unloading 时 `ctx.effect` 先抛 `INACTIVE_EFFECT`,map 中不留任何表项。
- 移植版现状:
  ```python
  self._sn_exporter += 1
  sn = self._sn_exporter
  self.exporters[sn] = exporter      # 先注册
  ...
  return self.ctx.effect(teardown, label="ctx.logger.exporter()")
  ```
  effect 注册失败(如 INACTIVE_EFFECT)时 map 中的 exporter 已泄漏,后续每次日志仍会调用死 exporter。
- 修复方案:把 map 写入挪进传给 `ctx.effect` 的 setup 回调并返回 disposer(注意 `fiber.effect` 会把名为 `teardown` 的可调用对象当纯 disposer,setup 函数须另取名或以返回值交付 disposer)。

### D10 [MUST-FIX] `ctx.logger()` 未解析 intercept 配置(name/level),且未对 fiber 名做 hyphenate
- 位置: py:dsh/cordis/logger.py:276-282 vs ts:reference/vendor/cordis/src/logger.ts:176-181、239-261
- 原版行为:
  ```ts
  const config = this._resolveConfig()
  const fiber = ((this.ctx as any)[symbols.shadow] ?? this.ctx).fiber
  name ??= config.name
  name ??= hyphenate(fiber.name)
  return new Logger({ name, level: config.level, meta: { fiber: new WeakRef(fiber) } }, this)
  ```
  名字与级别可被 `logger` intercept(`{ name?, level? }`,沿原型链合并)覆盖;fiber 名转 kebab-case(`myPlugin` → `my-plugin`)。
- 移植版现状:
  ```python
  target_name = name
  fiber = getattr(self.ctx, "fiber", None)
  if not target_name:
      target_name = getattr(fiber, "name", "root") if fiber else "root"
  return Logger(name=target_name, service=self, meta={"fiber": fiber})
  ```
  无 intercept 解析(level 恒为 INFO),名字不做 hyphenate,消息 `name` 字段与 TS 输出不同。
- 修复方案:复用 dsh 已有基础设施:`Service.resolve_intercept_config`(dsh/cordis/service.py:67)读取 `_intercept_map["logger"]`,取 `config["name"]`/`config.get("level")` 传入 Logger;名字回退时套 `dsh/cordis/utils.py:281` 的 `hyphenate(fiber.name)`;保留 `"root"` 兜底(Python 侧便利,无 fiber 时 TS 会崩)。

### D11 [ADAPT] Message 形状:TS 把 `...this.meta` 平铺进记录顶层;Python 存于 `message.meta` 子字典,另增 `to_dict()`
- 位置: py:dsh/cordis/logger.py:33-64、200-209 vs ts:reference/vendor/cordis/src/logger.ts:29-38、157
- 原版行为:`const message: Message = { sn, ts, type, level, name: this.name, ...this.meta, args }` —— 自定义 meta 键是 message 的顶层字段;`fiber` 为 `WeakRef<Fiber>`。
- 移植版现状:`Message(..., meta=self.meta)`;`message.fiber = weakref.ref(fiber)`(等价 WeakRef);`meta` 独立成字典;`to_dict()` 为 Python 侧序列化辅助(Exception → str)。
- 修复方案:结构等价,可保留;若 Web GUI 消费方依赖平铺形状,再在 Message 上把 meta 键同步提升为属性。

### D12 [ADAPT] 同一条日志在多个 exporter 间共享同一 Message 实例;TS 为每个 exporter 新建对象
- 位置: py:dsh/cordis/logger.py:200-216 vs ts:reference/vendor/cordis/src/logger.ts:152-159
- 原版行为:message 字面量在 exporter 循环体内构造,每个 exporter 拿到独立对象(可被各自安全改写)。
- 移植版现状:循环外构造一次,逐个 `exporter.export(message)`。
- 修复方案:框架约定 Message 只读,保留现状;若未来出现改写型 exporter,改为循环内逐个构造。

### D13 [ADAPT] format() 中 Error 首参渲染:TS `stack || message`;Python `traceback.format_exception(...) or str(err)`
- 位置: py:dsh/cordis/logger.py:129-133 vs ts:reference/vendor/cordis/src/logger.ts:101-103
- 原版行为:`args[0] = args[0].stack || args[0].message; args.unshift('%s')`。
- 移植版现状:有 `__traceback__` 时拼接 traceback 文本,否则 `str(err)`;同样 unshift `"%s"`。
- 修复方案:Python 无 `.stack`,traceback 文本是等价惯用实现,保留。

### D14 [ADAPT] `default_code()` 在 level 为假时返回 0;TS 返回 `undefined`(colors[NaN])
- 位置: py:dsh/cordis/logger.py:100-107 vs ts:reference/vendor/cordis/src/logger.ts:95-96
- 原版行为:`colors[NaN]` → `undefined`,随后 `Logger.color` 因 `!exporter.colors` 短路,不产生可见差异。
- 移植版现状:`if not colors: return 0`。
- 修复方案:两者都被 `color()` 的 `!colors` 短路兜住,保留。

### D15 [ADAPT] 可调用 service(createCallable/joinPrototype/tracker)以普通 `__call__` + 方法实现
- 位置: py:dsh/cordis/logger.py:233-294 vs ts:reference/vendor/cordis/src/logger.ts:194-269
- 原版行为:构造器经 `createCallable('logger', joinPrototype(...), tracker)` 生成可代理实例,`error/info/warn/debug` 由 static 块挂到原型并委托 `this()[type](...)`。
- 移植版现状:普通类 + `__call__` + 四个同级方法,委托语义一致;`name = "logger"` 命名一致。
- 修复方案:框架层代理适配,保留。

### D16 [SKIP] logger-console 全套(ConsoleExporter shared/index/browser)在 Python 侧无对应模块
- 位置: py:(无对应文件,`dsh/` 全库 grep `ConsoleExporter|showTime|showDiff|maxLength` 仅命中 logger.py 内存 exporter) vs ts:reference/vendor/logger-console/src/shared.ts:28-98、index.ts:9-26、browser.ts:8-15
- 原版行为:`render()` 的 `[E]` 前缀、label 宽度/边距/对齐 padding、`showTime` 模板渲染、`showDiff` 时间差、Node 侧 `supports-color` 探测与 `util.inspect` 的 `o/O` formatter、浏览器侧按 type 分派 `console.error/warn/log`。
- 移植版现状:完全未移植;`dsh/` 中唯一的 exporter 是 logger.py:250-255 的内存环形缓冲。
- 修复方案(SKIP 理由):这是"缺失模块"而非"已移植代码的语义偏差"——控制台渲染面不在本次移植范围内。若后续需要,新建 `dsh/cordis/logger_console.py` 对齐 shared.ts 的 `render()`(label pad、Time.template、showDiff),颜色探测用 Win7 可用的 ANSI 使能检测替代 `supports-color`,`util.inspect` 以 json/pprint 替代;browser.ts 无对应场景,直接跳过。

## 测试缺口

现有覆盖:仅 `tests/test_cordis_1to1_full.py::test_logger_service_and_color_formatting`(消息字段、格式化片段、环形缓冲、disposer 调用)。`grep "logger|Logger" tests` 无其他直接用例。

### T1 `Logger.code` 与 TS 有符号哈希逐点一致(覆盖高位置 1 的名字)—— `test_logger_code_signed_hash_parity`
构造若干 32 位哈希高位置 1 的名字(可用大 BMP 字符/长 ASCII 名穷举验证),断言 `Logger.code(name, 3)`/`(name, 1)` 等于按 TS 算法(`|0` 有符号截断 + `Math.abs`)手算的期望色号;并断言 `level=0` 返回 0。

### T2 code < 8 时 decoration 受 `colors >= 2` 门控 —— `test_logger_color_decoration_requires_colors_2`
`Logger.color(Exporter(colors=1), 1, "x", ";1")` 不含 `;1`;`colors=3` 时含;`colors=0` 返回裸字符串。

### T3 单 Error 参数的 cause / 聚合展开 —— `test_logger_error_cause_and_aggregate_fanout`
`logger.error(err)` 且 `err.__cause__` 非空 → 收到两条消息(cause 在前,原错误在后);带 `errors` 列表的聚合异常 → 每个子错误一条、原错误不记录。

### T4 format 占位符边界语义 —— `test_logger_format_placeholder_parity`
① `"%s"` 无参 → TS 对齐的缺失值文本(非保留 `%s`);② `"a %x %s", 1, 2` → `%x` 原样保留且 `%s` 消费到 2;③ `"%d", "3.7"` → `"3"`;④ `"%d", "abc"` → `"NaN"`;⑤ `"%%"` → `"%"`。

### T5 尾随对象参数经 exporter 的 `o` formatter —— `test_logger_format_leftover_objects_use_o_formatter`
注册自定义 `formatters={"o": fn}` 后 `format(exporter, msg)`,尾随 dict/自定义对象都经 `fn`;未注册时回退 JSON 序列化。

### T6 exporter disposer 目标 sn 与注册原子性 —— `test_logger_exporter_disposer_targets_latest_sn`
依次注册两个 exporter 后调用第一个的 disposer:按 TS 语义断言"当前 `_sn_exporter`"对应的表项被移除(D8 修复后行为);另加 fiber 失活时 `logger.exporter()` 抛 INACTIVE_EFFECT 且 map 无残留(D9)。

### T7 exporter 异常传播 —— `test_logger_exporter_exception_propagates`
注册一个 `export()` 抛错的 exporter,断言 `logger.info(...)` 将异常抛给调用方(D7 修复后),且其后注册的 exporter 不再收到该条消息。

### T8 `ctx.logger()` 名字/级别解析 —— `test_logger_name_hyphenate_and_intercept_config`
camelCase fiber 名 → hyphenate 后的消息 name;`ctx.intercept("logger", {"name": "x", "level": 0})` 之下 `ctx.logger()` 的消息 name 为 `"x"` 且 DEBUG 级消息被 level=0 的 exporter 过滤。
