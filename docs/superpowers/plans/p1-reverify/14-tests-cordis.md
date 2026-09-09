# T1-tests-cordis 盲审报告

前置说明：`tests/1to1/cordis/` 下实际存在 **17 个** `test_*.py`（任务描述写 18 个，经 glob 核实为 17 个，无遗漏）。另注：`test_environment_parity.py` 声称对齐的 `launch-environment`/`home-paths` 权威源在仓库 `reference/packages/util/{launch-environment,home-paths}/src/index.ts` 中存在，本审计顺带以其核对了该文件。

## 覆盖矩阵

| 测试文件 | 钉住的 TS 行为（file:line） | 判定 |
|---|---|---|
| test_context_parity.py | isolate 同 label 合入同域 context.ts:121-125；has() 对已声明 None 服务为真 reflect.ts:199-205；internal/get 拦截 reflect.ts:152-167；ctx.effect 委托 fiber.effect fiber.ts:415-418；strict 下根 store 可被子 fiber 解析 reflect.ts:153-166 | 等价为主；T4 触发路径钉错（F2）；T2 docstring 虚报（F10） |
| test_environment_parity.py | resolve_dsh_home 优先级 home-paths index.ts:87-90（configured > $DSH_HOME > ~/.dsh，空白视为未设）；dotenv 行内注释/多行/转义；launchEnvironmentOf 进程回退 launch-environment index.ts:115-116；快照不可变 index.ts:78-95 | 等价（断言精确，无发现） |
| test_events_parity.py | waterfall 洋葱/否决 events.ts:234-243；parallel 派发 mode='emit' events.ts:184；internal/update prepend events.ts:140-146；bail 异常透传 events.ts:217-222；filter 异常透传 events.ts:171-174 | 多数等价；**F1 WRONG-PIN**（None-return 续传钉成 TS 语义）；F14 弱（internal/dispatch 形参） |
| test_fiber_parity.py | 父 unload 级联子 fiber fiber.ts:265-297；dispose 注销 registry fiber.ts:270-274；internal/plugin 先于 unload + 监听器错误隔离 fiber.ts:120-137,268；inject 拦截写 ctx fiber.ts:238-245；FAILED fiber 可注册 effect fiber.ts:415-421；DISPOSED 优先 fiber.ts:574-579；CordisError 文案 fiber.ts:171-174；根 fiber dispose 即重启 fiber.ts:331 | 多数等价；**F3 WRONG-PIN**（匿名命名启发式）；T19 等价 |
| test_harness_parity.py | preset/overlay fail-loud（app-boot index.ts:286,413）；dshHomePath（home-paths index.ts:98-100）；session-query 休眠；插件激活失败 fail-loud | 等价为主；T3 弱断言（F9）、T6 弱（F16） |
| test_hmr_parity.py | registerConfig 存在文件立即 refresh 一次 hmr index.ts:134-187（ignoreInitial:false 注释 232-239）；add/unlink 触发；重复注册/未激活报错 index.ts:135,139；config 刷新不发 hmr/change index.ts:249-256 | 等价；add/unlink 用 `>=1` 弱断言（F13） |
| test_include_parity.py | init 缺文件+initial 写入/否则 raise include index.ts:273-289；internal/update 命中短路 index.ts:206-214；写入保序/readonly PermissionError index.ts:323-342；read 分级 read/parse/validate index.ts:240-265 | 等价（错误类型 PermissionError 为合法 Python 适配） |
| test_loader_parity.py | disabled: 字符串真值/空串/!!js entry.ts:104-112；group 永不禁用 entry.ts:88-91；partial-dispose 事件 group.ts:48-57；interpolate 字面量/`__jsExpr` 求值 utils.ts:12-27；show_log 门控 loader index.ts:172-175 | 多数等价；T2/T15 **OVERCLAIM**（F6、F7）；T16 为 PyYAML 适配（合理） |
| test_logger_parity.py | code 32 位有符号哈希常量 logger.ts:89-97,165-173；color decoration colors>=2 logger.ts:84-87；cause 先打 + aggregate 只打子项 logger.ts:141-150；format 占位符边界 logger.ts:99-131；exporter disposer 删最新 _snExporter quirk logger.ts:232-237；exporter 异常透传 logger.ts:154-159；hyphenate+intercept logger.ts:239-261 | 等价；**F4 WRONG-PIN**（level=0 返回 0 vs TS undefined） |
| test_plugin_parity.py | inject 回调 (ctx,config) registry.ts:300-302；对象/dict 插件 apply 收 config registry.ts:131-133；invalid plugin 报错 registry.ts:319,222-228；构造器 TypeError 入 _error fiber.ts:646-673；apply 返回 disposer/generator 收集 fiber.ts:356-400；Service.provide + Config 校验 registry.ts:326 + fiber.ts:50-62 | 等价（T3 弱，见 F11） |
| test_profile_parity.py | 非法 profile 名 profile.ts:127-134；未知名 fail-loud profile.ts:810-817；patch 列表 fail-loud（app-boot index.ts:270-345）；telemetry 补丁 apps/cli profile-boot.ts:100-110 | 等价；**F8 OVERCLAIM**（权威误标为 profile.ts） |
| test_reflect_parity.py | 跨 fiber set 报错 reflect.ts:260-262；重复 provide 报错 reflect.ts:289-291；internal/service 隔离域过滤 reflect.ts:314-336；数字串特殊属性 reflect.ts:86-91 | 等价 |
| test_registry_parity.py | Service 随 fiber 卸载注销 service.ts:42-58 + reflect.ts:297-303；@inject 不改基类 registry.ts:37-44；拦截配置入 intercept（无 required 污染）fiber.ts:238-245；name==='apply' 匿名 registry.ts:324-326；FAILED fiber 可挂载 registry.ts:320 + fiber.ts:351-354；internal/plugin 时 fiber 已入 registry fiber.ts:265-267,302 | 等价；T3 弱（F11） |
| test_schema_parity.py | 工厂默认 meta schemastery index.ts:852-858；intersect 首员默认/首胜/全 nullable index.ts:474-484,777-795；autofix/sKey 改写 index.ts:698-735；bitset 抑制 adapted index.ts:654-674；array skip_min index.ts:713-717；transform 双调 index.ts:797-813；pattern flags/const 严格/deep_equal/simplify/lazy/`~standard`/date/is-MRO/set-push TypeError index.ts 各处 | 大面积等价；T26 弱（F15）；bitset 直构 default 偏差未钉（附注） |
| test_service_parity.py | 重复注册报错 service.ts:57 + reflect.ts:289-291；可调用服务走 invoke service.ts:50-52 + utils.ts:226-233；resolveConfig base/head 原样传 service.ts:86-102；check 门控依赖 fiber.ts:597-609 | 等价 |
| test_timer_parity.py | interval dispose 后持续 reject / aclose 干净停 / 慢消费丢 tick timer index.ts:70-102；callback 协程不阻塞 index.ts:62-66；throttle dispose 后立即路径仍触发、trailing 抑制、no_trailing index.ts:106-136；timeout future dispose reject index.ts:44-53 | 等价；**F5 OVERCLAIM**（no-loop 分支零覆盖） |
| test_utils_cosmokit_parity.py | camelCase/tokenize string.ts:12-64；parseTime/format/template time.ts:41-91；valueMap/filterKeys/pick/omit misc.ts:39-69；deepEqual types.ts:118-142；DisposableList utils.ts:5-40；getTraceable/withProps/composeError/buildOuterStack utils.ts:117-147,268-287；数组/杂项 helpers array.ts:4-42 + string.ts:99-113 | 等价为主；d10 弱（F12）、parse_date 弱（附注） |

## 发现

### F1: 瀑布监听器"返回 None 即续传"被钉成 TS 语义（WRONG-PIN）
- TS: `reference/vendor/cordis/src/events.ts:227-229`（JSDoc："a listener that does not call `next()` vetoes the rest of the chain"）与 `events.ts:237-239`（`const next = () => { const cb = cbs.shift() ?? inner; return cb(...args) }`——每个监听器都收到 `next`，不调即否决，返回 undefined 亦然）。
- TEST: `tests/1to1/cordis/test_events_parity.py:63-79`：`mw_observer(data)` 单参返回 None，断言 `res == "HELLO!"`（链继续到 mw_modify）。docstring 引 `ts:cordis/events.ts:225-243` 作为 parity 依据，未标 permitted deviation。
- 类型: WRONG-PIN（同文件 `test_d2_permitted_deviation_reducer` 正确地用 "Permitted Deviation" 标注了同类偏离，此例漏标）。
- 建议修法：要么把该测试改名为 permitted deviation 并在 docstring 标注（TS 下该场景结果是 undefined/否决），要么新增一个对照测试钉住 TS 语义的 Python 适配边界（带 `next` 形参的监听器不调 next 必须否决——该语义目前无测试）。

### F2: internal/get 用 `ctx.get()` 触发，而 TS 中 `ctx.get()` 不经过 internal/get（WRONG-PIN，局部）
- TS: `reference/vendor/cordis/src/reflect.ts:152-167`（internal/get 仅在 **proxy 属性读取** trap 中派发；`reflect.ts:233-235` `get(name, strict)` 直读 `_getImpl`，不经 internal/get；`reflect.ts:345` 事件文档亦写明 "read through the context proxy"）。
- TEST: `tests/1to1/cordis/test_context_parity.py:59-72`：以 `ctx.get("virtual_prop")` 触发并断言拦截生效。Python `dsh/cordis/reflect.py:124-127` 对所有 get（含 `ctx.get`）都走 internal/get 瀑布——测试把这一 Python 路由偏差钉成了 parity。附带：`test_context_parity.py:136` 断言的消息用单引号 `'nonexistent_service'`，TS 原文是双引号（reflect.ts:144）。
- 类型: WRONG-PIN（拦截语义本身是 TS 真行为，但触发通道与消息引号是非 TS 的）。
- 建议修法：改用属性访问 `getattr(ctx, "virtual_prop")`（Python 中对应 TS proxy get 的通道）作触发，并为 `ctx.get()` 不派发 internal/get 与否补一条偏差标注或对齐测试。

### F3: 用 "anonymous_child" 命名函数制造匿名插件，依赖 Python 独有启发式（WRONG-PIN）
- TS: `reference/vendor/cordis/src/registry.ts:324-326`：`let name = plugin.name; if (name === 'apply') name = undefined`——只把 `apply` 匿名化；名为 `anonymous_child` 的函数在 TS 是**具名**插件，fiber.name 应为 `"anonymous_child"`（fiber.ts:336-343）。
- TEST: `tests/1to1/cordis/test_fiber_parity.py:125-142`：`def anonymous_child(child_ctx)` 并断言 `child_fiber.name == "grand_parent_runtime"`。能通过全靠 Python `dsh/cordis/registry.py:128` 的 `cb_name.startswith("anonymous")` 启发式——该偏差未在任何 permitted-deviation 清单中标注。
- 类型: WRONG-PIN（测试以非 TS 构造钉住"匿名继承"这一 TS 真行为，通过理由错误）。
- 建议修法：改用真正的匿名可调用（`lambda child_ctx: None`，Python `__name__ == "<lambda>"` 已被过滤，registry.py:128），或在偏差清单中显式登记 "anonymous* 前缀视为匿名" 并在 docstring 标注。

### F4: `Logger.code(name, 0) == 0` 钉住 Python 偏差，TS 返回 undefined（WRONG-PIN，轻微）
- TS: `reference/vendor/cordis/src/logger.ts:95-96`：`const colors = !level ? [] : ...; return colors[Math.abs(hash) % colors.length]`——level 为 0/false 时对空数组取 `NaN` 索引，返回 `undefined`。
- TEST: `tests/1to1/cordis/test_logger_parity.py:26`：`assert Logger.code("test", 0) == 0`。Python `dsh/cordis/logger.py:103-110` 显式 `if not colors: return 0`。
- 类型: WRONG-PIN（常量部分 `"core"→166/4`、`"test_str_10"→80/1` 是高质量等价钉住，唯 level=0 分支偏离）。
- 建议修法：断言改为 `Logger.code("test", 0) in (None, 0)` 并注明 TS 为 undefined，或删除该行、保留有符号哈希常量断言。

### F5: "no-loop timeout 回退"测试实际走的是有 loop 路径（OVERCLAIM，分支零覆盖）
- TS: `reference/vendor/timer/src/index.ts:44-53`（timeout(delay) promise 路径 dispose 即 reject）。
- TEST: `tests/1to1/cordis/test_timer_parity.py:139-152`：docstring 声称 "No-loop timeout fallback registers cancellable effect"，但 pytest-asyncio 下存在运行中事件循环，`dsh/cordis/timer.py:195-200` 的 `asyncio.get_running_loop()` 成功，走的是与 `test_d5_timeout_future_rejects_on_dispose`（126-136 行）完全相同的 future 路径；`_fallback_sleep` 分支（timer.py:202-223）零覆盖。
- 类型: OVERCLAIM（断言本身为真，但声称覆盖的行为未被测试）。
- 建议修法：直接单测 `_fallback_sleep` 分支（如在无 loop 线程里调用并断言 dispose 后 RuntimeError），或将 docstring 改为与 test_d5 同义并合并。

### F6: loader disabled 级联声称覆盖实则未测（OVERCLAIM）
- TS: `reference/vendor/loader/src/config/entry.ts:88-98`（`_disabled` 沿 parent entry 链逐级检查；`entry.ts:104-108` !!js 表达式求值）。
- TEST: `tests/1to1/cordis/test_loader_parity.py:54-62`：docstring "parent entry disabled propagates to children"，测试体只有一个 group entry 的豁免断言（`g_entry.disabled is False`），无任何父子级联构造。
- 类型: OVERCLAIM + GAP。
- 建议修法：补构造 parent entry（disabled=True）+ child entry，断言 child.disabled 为 True；并补 `{"disabled": {"__jsExpr": "false"}}` 求值用例。

### F7: Loader.locate 正向路径零断言（OVERCLAIM + 弱断言）
- TS: `reference/vendor/loader/src/index.ts:177-185`（沿 fiber→parent.fiber 找 `fiber.entry`，返回 `entry.id`）。
- TEST: `tests/1to1/cordis/test_loader_parity.py:148-158`：仅 `assert loader.locate() is None` 与 `loader.exit()` 可调用；docstring 声称 "returns owner entry id from child fiber" 无对应断言。
- 类型: OVERCLAIM。
- 建议修法：挂一个带 entry 的 fiber（`fiber.entry = entry; entry.id == "x"`）断言 locate 返回该 id，再保留否定路径。

### F8: resolve_telemetry_patch 权威误标为 app-boot/profile.ts（OVERCLAIM，行为本身正确）
- TS: 实际权威是 `reference/apps/cli/src/profile-boot.ts:100-110`（`resolveTelemetryPatch(disabledEnv, hasRow)`：空/未设→undefined；`hasRow` 为假→undefined；否则 `{id:'session-telemetry-otel', disabled:true}`，另有官方测试 `apps/cli/tests/telemetry-switch.spec.ts:4-20` 同口径）。`reference/packages/boot/app-boot/src/profile.ts` 中不存在该函数（grep 验证）。
- TEST: `tests/1to1/cordis/test_profile_parity.py:101-114`：三支路断言与 TS 完全一致。
- 类型: OVERCLAIM（docstring 权威指向错误；语义钉住正确）。
- 建议修法：docstring 改指 `apps/cli/src/profile-boot.ts:100`。

### F9: fail-loud 消息断言含恒真析取（WEAK）
- TS: `reference/packages/boot/app-boot/src/index.ts:286`（`${binName}: failed to read patches ${file}: ...`，overlay 同族 fail-loud）。
- TEST: `tests/1to1/cordis/test_harness_parity.py:50`：`assert "Overlay patch file not found" in str(exc.value) or "not found" in str(exc.value)`——第二个析取支吞掉第一个，具体文案从未被真正钉住（Python 实际消息是 `dsh/harness.py:201` "failed to read overlay ...: file not found"）。
- 类型: WEAK。
- 建议修法：改为单断言 `"failed to read overlay" in str(exc.value)`（与 harness.py:201 一致）。

### F10: test_context T2 docstring 虚报 RESERVED_ATTRS 前提（OVERCLAIM，轻微）
- TS: `reference/vendor/cordis/src/reflect.ts:80-91`（特殊属性仅 symbol/prototype/then/数字串/_前缀；`status`/`session`/`agent` 都不是特殊属性）；Python `dsh/cordis/context.py:401-404` 的 RESERVED_ATTRS 亦不含 `status`。
- TEST: `tests/1to1/cordis/test_context_parity.py:37-45`：docstring "even if name in RESERVED_ATTRS"，实际 `status` 不在任何保留名单中。
- 类型: OVERCLAIM（docstring 层面；行为断言 `child.status == dummy_status` 本身是正确的 TS parity）。
- 建议修法：docstring 改为"服务名与内置属性名冲突时的解析优先级"，或换用真实保留名做负例。

### F11: invalid plugin 断言用 `pytest.raises(Exception)`（WEAK）
- TS: `reference/vendor/cordis/src/registry.ts:319`（`throw new Error('invalid plugin, expect function or object with an "apply" method, received ' + typeof plugin)`）。
- TEST: `tests/1to1/cordis/test_registry_parity.py:62`（同型于 `test_plugin_parity.py:62`）：`pytest.raises(Exception)`——任何异常类型都能过；Python 实现抛 `ValueError`（dsh/cordis/registry.py:252）。另 TS `received object`（typeof），Python `received ExplodingApply`（类名），未被钉住。
- 类型: WEAK。
- 建议修法：钉 `ValueError`；并对 int 用例补 `received int` 精确断言（该半边已有 `"int" in msg`，可保留）。

### F12: DisposableList 身份删除断言因小元组驻留而恒真（WEAK）
- TS: `reference/vendor/cordis/src/utils.ts:21-25`（WeakMap 身份删除）。
- TEST: `tests/1to1/cordis/test_utils_cosmokit_parity.py:151-158`：`t1 = (1, 2); t2 = (1, 2)`——CPython 同一代码对象内常量元组去重，`t1 is t2` 成立：push 两次同一对象后 `delete(t1)` 删的是 sn=2 的条目，`list(lst) == [t2]` 因对象同一而恒真，身份语义完全未被检验。
- 类型: WEAK。
- 建议修法：改用 `object()` 两个实例（或 `t2 = (1, 2,)` 强制新建）做身份对照。

### F13: HMR add/unlink 断言用 `>= 1`，无法检出重复/合并回归（WEAK）
- TS: `reference/vendor/hmr/src/index.ts:151-158`（onChange → refreshConfig，dirty+running 单飞合并，index.ts:297-324）。
- TEST: `tests/1to1/cordis/test_hmr_parity.py:76,83`：`assert len(events) >= 1`——刷新被触发多次（去抖/合并回归）也不会失败。
- 类型: WEAK。
- 建议修法：在稳定窗口后断言精确次数（创建 1 次、删除 1 次），并把轮询间隔设置成远小于睡眠时间以降噪。

### F14: internal/dispatch 监听器形状钉的是 Python info-dict 适配（WEAK，未标偏差）
- TS: `reference/vendor/cordis/src/events.ts:169`（`this.emit('internal/dispatch', type, name, args, thisArg)`，4 个位置参数；事件签名 events.ts:351）。
- TEST: `tests/1to1/cordis/test_events_parity.py:162-171`：单参 lambda 收 `{type, name, args, ctx}` dict（Python `dsh/cordis/events.py:248-255` 特判），且仅 `assert "emit" in dispatch_modes`——无法区分不同派发模式的 mode 值。
- 类型: WEAK（核心事实 parallel→'emit' 正确，events.ts:184；但签名适配未标注、serial/bail/waterfall 的 mode 无任何用例）。
- 建议修法：补一条断言 serial/bail/waterfall 派发的 mode 值（'serial'/'bail'/'waterfall'，events.ts:205,218,235），并在 docstring 标注 info-dict 为 Python 适配。

### F15: lazy toJSON 钉住 Python 包装形状，TS 输出经 inner 委托（WEAK）
- TS: `reference/vendor/schemastery/src/index.ts:517-527`（`Schema.lazy` 的 toJSON 委托 `schema.inner!.toJSON()`，配合 index.ts:296-307 的 uid/refs 机制，实际输出 inner 的序列化/uid 引用而非 `{"type":"lazy","inner":{...}}` 包装）。
- TEST: `tests/1to1/cordis/test_schema_parity.py:222-227`：断言 `type == "lazy"` 且 `inner is not None`——宽松到与两种形状都兼容，未钉住 TS 的 refs/uid 输出形态。
- 类型: WEAK（倾向于把 Python 包装形状当成 parity）。
- 建议修法：明确登记 toJSON 结构为允许偏差，或补一条断言 inner 内容等于被建 inner 的 type（`json_rep["inner"]["type"] == "string"`）以收窄。

### F16: dshHomePath 只断言 endswith（WEAK）
- TS: `reference/packages/util/home-paths/src/index.ts:98-100`（`dshHomePath(...segments)` = join(resolveDshHome(), segments)）。
- TEST: `tests/1to1/cordis/test_harness_parity.py:53-60`：`p.endswith("sessions")`——实现若只返回子路径也能通过，未验证位于 DSH_HOME 之下。
- 类型: WEAK。
- 建议修法：断言 `os.path.dirname(p)` 等于 `resolve_dsh_home()`（可设 `DSH_HOME` 环境变量做隔离）。

### F17: prepend 顺序断言耦合 `__wrapped__` 实现细节（WEAK）
- TS: `reference/vendor/cordis/src/events.ts:140-146`（internal/listener 对 internal/update 用 unshift/push 入 fiber._hooks）。
- TEST: `tests/1to1/cordis/test_events_parity.py:139-141`：`getattr(items[0], "__wrapped__", items[0]) is prepended_listener`——依赖 Python bind 包装器的 `__wrapped__` 属性名（events.py:46 `functools.wraps`）；实现改名即碎。执行顺序断言（144-145 行）是真语义钉住。
- 类型: WEAK（半边等价）。
- 建议修法：删去列表身份断言，仅保留执行顺序断言（TS 可观察行为）。

## GAP（最重要前 15 条）

1. **parallel 聚合错误**：TS 并发派发收集全部 rejected 并抛 AggregateError（events.ts:183-187）。Python events.py:292-295 已实现，但 `test_events_parity.py` 无任何 AggregateError 用例——监听器异常被静默吞掉这类回归检不出来。
2. **serial 派发模式**：顺序 await + 首个非 null/false 值 bail（events.ts:204-209）。整个套件对 `serial` 零测试（AGENTS.md 明列 serial 为四类派发模式之一）。
3. **isBailed 边界**：`0`/`""` 应视为 bail（events.ts:13-15）。无用例（`is_bailed(0) is True` 等）。
4. **once() 单发自毁**：注册即包一层、首次调用后自卸载（events.ts:312-318）。本套件无用例。
5. **internal 事件不触发 internal/dispatch**：`if (!name.startsWith('internal/'))`（events.ts:168）。无用例钉住"内事件静默"。
6. **INACTIVE_EFFECT 行为级抛出**：已 dispose（uid=null）或 UNLOADING fiber 上 effect 注册抛 CordisError（fiber.ts:415-421,351-354）。目前只有 T17 钉了消息文案，没有行为用例。
7. **fiber.await() 重抛启动错误**（fiber.ts:704-710；registry.ts:331-334 wrapped.then）。`test_plugin_parity.py` 从不 await 失败 fiber，启动错误经 awaitable 通道传播的契约未钉。
8. **resolveConfig 校验失败 → ValidationError 聚合消息**（fiber.ts:19-62,641-644）。`test_plugin_parity.py` T6 只测默认值成功路径；`invalid config:` 多行 issue 格式零覆盖。
9. **registry.plugin 对已 dispose ctx fail-loud**（registry.ts:320 assertActive）。无用例。
10. **reflect.set 对未 provide 名字 fail-loud**（reflect.ts:254-265 `cannot set property ... without provide`）与 accessor()/mixin()（reflect.ts:345-390，撑起 ctx.on/ctx.plugin 门面）。均无用例。
11. **debounce 的 dispose 语义**：dispose 后不再执行挂起回调（timer index.ts:139-144）。timer 套件只测 throttle/interval/timeout，debounce 零覆盖。
12. **Entry.disabled !!js 表达式求值**（entry.ts:100-112 `disabledOf`）。`test_loader_parity.py` T1 只测了 disabled 字面量与布尔；`{"__jsExpr": ...}` disabled 求值无断言。
13. **applyEntryPatches 完整 patch 语义**：insert（含后补 patch 可命中先前 insert 的行）、name 不匹配跳过、id 未命中 warn 跳过（include index.ts:58-128；Python dsh/cordis/loader.py:468-555）。本套件零覆盖。
14. **logger levels 门控与 maxLength 截断**（logger.ts:127-130,155-159）。exporter.levels 阈值过滤与 10240 截断均无用例。
15. **hmr 模块重载分类与 hmr/config-update-failed**：changed 文件 → accepted/declined 分类、失败并行事件（hmr index.ts:244-271,297-324；Python hmr.py:324-369 已实现事件）。配置监视有测试，模块重载与失败事件零覆盖。

附注（不计入前 15）：bitset 直构（`Schema({"type":"bitset",...})`）时 TS `meta.default` 为 undefined、adapted 不被抑制，Python `meta.get("default", 0)`（schema.py:912-914）恒以 0 抑制——工厂路径已被 T7 钉住，直构偏差无测试区分；`Time.parse_date("10:30")` 仅断言 isinstance（test_utils_cosmokit_parity.py:98-99），未钉住时刻值，属弱断言。

## 结论摘要

- 高质量等价钉住占多数：logger 常量/格式化、timer 全族、include 分级错误、service/reflect 的错误契约、schema 的 intersect/transform/autofix 语义、environment 快照，断言精确、引文基本可对上。
- 必须优先修复的是 4 处 WRONG-PIN（F1 瀑布 None 续传、F2 internal/get 触发通道、F3 anonymous 前缀启发式、F4 code(level=0)），它们把未登记的 Python 偏差钉成了 1:1 parity；其次是 6 处 OVERCLAIM（F5-F10），docstring 声称的覆盖与实际断言不符，其中 F6/F7 属"声称覆盖但零断言"。
- GAP 集中在错误聚合（parallel AggregateError）、serial 模式、INACTIVE_EFFECT 行为级、以及 loader patch/hmr 模块重载两块完全无测试的子系统。
