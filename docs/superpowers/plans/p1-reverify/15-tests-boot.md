# T2-tests-boot 盲审报告

## it() → test_ 映射矩阵

| TS spec | it() 总数 | 已映射 | 弱化 | 缺失 | 多余 |
|---|---|---|---|---|---|
| reference/packages/boot/app-boot/tests/app-boot.spec.ts | 47 | 47 | 13 | 0 | 0 |
| reference/packages/boot/app-boot/tests/config-dump.spec.ts | 6 | 6 | 0 | 0 | 0 |
| reference/packages/boot/app-boot/tests/config-reload.spec.ts | 12 | 12 | 3 | 0 | 0 |
| reference/packages/boot/app-boot/tests/hmr-config.spec.ts | 6 | 6 | 1 | 0 | 0 |
| reference/packages/boot/app-boot/tests/profile.spec.ts | 39 | 39 | 3 | 0 | 0 |
| reference/packages/boot/app-boot/tests/user-patches.spec.ts | 16 | 16 | 2 | 0 | 0 |
| reference/packages/boot/cmdline/tests/cmdline.spec.ts | 20 | 20 | 9 | 0 | 0 |
| reference/apps/cli/tests/args.spec.ts | 6 | 6 | 0 | 0 | 0 |
| **合计** | **152** | **152** | **31** | **0** | **0** |

说明：
- `it.each`（app-boot.spec.ts:129，7 个安全案例）与 PY `@pytest.mark.parametrize`（test_app_boot.py:189，7 案例）按 1 个用例计，案例清单逐条一致。
- 无任何 TS 用例缺失，也无 PY 多余用例。所有"弱化"均存在于映射成立的用例内部（断言降级/fixture 钉错）。
- 8 个测试文件的 docstring 均声称 "1:1 Parity"，但其中 31 个用例存在不同程度的断言降级，属轻度虚报覆盖（详见各条发现）。

## 发现

### F1: boot 最深 cause 的"原始栈拼接"格式未被钉住
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:746-761` — fixture 将 `failure.stack` 钉为 `'Error: pinned activation failure\n    at failing-fixture'`，并用正则断言完整格式：`failed to apply loader entry failing \(\./failing\.mjs\): pinned activation failure\nError: pinned activation failure\n {4}at failing-fixture$`
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:899-912` — fixture 仅 `raise failure`（未设 `.stack`），断言降级为 `match="pinned activation failure"`
- 类型: WEAK
- 建议修法: 实现侧（`dsh/boot/app_boot.py:732-733`）明确支持 `getattr(deepest, "stack", None) or str(deepest)` 的拼接分支。在 PY fixture 中给抛出的错误设置 `err.stack = "Error: pinned activation failure\n    at failing-fixture"`（JS 桥接层可传递该属性），然后断言完整两段格式（头部行 + 换行 + 固定栈文本结尾），钉住"原始栈逐字追加且以栈结尾"的语义。

### F2: "labels non-Error preparation failures" 用例传入的是 Error，非 Error 路径完全未测
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:646-660` — `const failure = 42`，prepare 直接 `throw failure`（非 Error），断言 `message: "...host preparation failed: 42"` 且 `cause: failure`（原始 42 被保留为 cause）
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:815-832` — PY 写成 `raise RuntimeError(str(failure))`，把 42 预先包装成了 Error；也未断言 `__cause__` 保留
- 类型: OVERCLAIM（测试名与 docstring 声称覆盖非 Error 失败，实际未覆盖）
- 建议修法: Python 虽不能 `raise 42`，但允许 `wrapper = RuntimeError("wrapped setup failure"); wrapper.__cause__ = 42; raise wrapper`（`__cause__` 可赋任意对象）。`boot()` 的最深 cause 遍历（app_boot.py:725）用 `getattr(deepest, "__cause__")`，可直接命中。建议改为经 `__cause__=42` 驱动，并断言消息含 "host preparation failed" 与 "42"、`exc_info.value.__cause__` 被保留；若实现承诺对非 Exception 准备失败也包一层 RuntimeError，应显式测该包装。

### F3: "disposed mid-startup" 的确定性时序未被复刻，竞态不受控
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:690-717`（关键 703-707）— `delayed.mjs` 顶部 `await new Promise(resolve => setTimeout(resolve, 10))`，确保 exiting 行的 dispose 发生在最后一个 entry settle 之前（确定性 staging）
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:855-865` — `delayed.mjs` 写成 `export function apply() {}`，无任何延迟
- 类型: WRONG-PIN
- 建议修法: 在 PY fixture 的 delayed 插件内引入确定性延迟（例如 Python 桥接模块顶层 `time.sleep(0.01)` 或等效的 async 睡眠），复刻"dispose 先于最后一个 entry settle"的前提；否则 `ctx.get("loader") is None` 断言依赖未受控的执行顺序，可能在实现正确时偶发失败（或实现错误时偶发通过）。

### F4: fail-loud 对"错误栈优先"语义的钉子丢失
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:289-297`（295 行）— `expect(proc.written[0]).toContain(error.stack)`（完整栈）
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:334-341` — 仅 `assert "boom" in proc.written[0]`
- 类型: WEAK
- 建议修法: 实现 `install_fail_loud`（app_boot.py:570）优先读取 `err.stack`。PY 测试应给 error 设置 `err.stack = "Error: boom\n    at spec-frame"` 并断言 written[0] 包含该固定栈文本，钉住 `.stack` 优先于 `str(err)` 的选择逻辑。

### F5: uninstaller 的"默认真实进程"臂未验证监听器计数
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:317-330`（325-329 行）— 在真实 process 上安装/卸载，断言 `unhandledRejection` 监听数 +1 再还原
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:358-367` — 仅 `install_fail_loud(NAME); uninstall_real()`，未验证任何状态变化
- 类型: WEAK
- 建议修法: 实现的默认 proc 臂在事件循环上 `set_exception_handler`（app_boot.py:598-611）。建议断言安装前后 `asyncio.get_event_loop().get_exception_handler()` 发生变化且 uninstall 后还原为原 handler，对应 TS 的 listenerCount +1/-1 语义。

### F6: "exit 未在 release 完成前提交"的即时断言缺失
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:362-375`（372 行）— handler 调用后立即 `expect(proc.exits).toEqual([])`（release 在途、exit 未落）
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:408-425` — handler 调用后直接进入轮询等待 exits，无即时空断言
- 类型: WEAK
- 建议修法: 在 `proc.handlers[0](...)` 之后、轮询之前加 `assert proc.exits == []`。这样"同步 exit + 事后补 release"的错误实现也会被抓到（当前 PY 只靠 `order == ["released"]` 间接约束）。

### F7: assertEntriesActivated 未用 await 计数钉住"不触碰 ACTIVE/PENDING fiber"
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:462-479`（478 行 `expect(awaitCalls).toBe(0)`）、`497-520`（519 行同）
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:566-583`、`631-659` — 两处均无 await 调用计数
- 类型: WEAK
- 建议修法: 在 MockFiber 上增加 `await_calls` 计数器（MockFiber 已有 `await_`），断言审计结束后 `sum(await_calls) == 0`，钉住实现（app_boot.py:660-675 只对 FAILED 调 await）不因重构回退为逐 fiber await。

### F8: "原始激活栈"半边断言缺失
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:481-486` — 断言消息包含 `broken-plugin: ${original.stack!}`（原始栈逐字出现，而非 "fiber state 3"）
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:587-601` — 仅 match 消息体 "actual plugin failure"，未设置/验证 `.stack`
- 类型: WEAK
- 建议修法: 实现 `_format_activation_error`（app_boot.py:639-642）的 `.stack` 分支当前无任何测试触达。在 fixture 中给原始错误设置固定 `err.stack` 并断言其出现在审计消息中。

### F9: loadEnv 默认 stderr 写入次数放宽为 >=1
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:61-87`（85 行）— `expect(written).toHaveLength(1)`
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:148-149` — `assert len(captured) >= 1` + `any(...)`
- 类型: WEAK
- 建议修法: 改为 `assert len(captured) == 1`（或拼接后恰一次匹配），钉住"单行、单次写入"的契约。

### F10: "栈被抹除"前提未模拟（轻）
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:763-772` — 显式 `delete deepest.stack` 强制走 fallback 分支
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:916-929` — 普通 RuntimeError，未做任何抹除
- 类型: WEAK（轻度：Python 异常天然无 `.stack` 属性，`or str(deepest)` fallback 路径实际被覆盖；但测试无法区分"被抹除后 fallback"与"本无栈"）
- 建议修法: 增加对比用例：一个 cause 设置了 `err.stack`（验证栈优先），一个不设置（验证 message fallback），两条路径同时钉住。

### F11: HMR 刷新失败归一化——非 Error 抛出值未测，message 断言降级为子串
- TS: `reference/packages/boot/app-boot/tests/hmr-config.spec.ts:171-201`（185 行 `throw 42`；191 行 `expect(observed.error.message).toBe('42')` 精确相等）
- TEST: `tests/1to1/boot/app_boot/test_hmr_config.py:222-261`（243-244 行 `raise RuntimeError("42")`；253 行 `assert "42" in str(observed["error"])`）
- 类型: WEAK
- 建议修法: Python 无法抛非 Exception 值，非 Error 归一化分支属合法语言性省略，应在测试 docstring 注明；但 message 断言应升级为 `assert str(observed["error"]) == "42"`（或 message 恰为 "42"），恢复 TS 的精确钉子。

### F12: noop disposer 的返回值未断言
- TS: `reference/packages/boot/app-boot/tests/user-patches.spec.ts:420-436`（432 行 `await expect(dispose()).resolves.toBeUndefined()`）
- TEST: `tests/1to1/boot/app_boot/test_user_patches.py:495-511`（507-509 行）— 仅 await 结果，不断言其值
- 类型: WEAK
- 建议修法: `res = dispose(); if inspect.isawaitable(res): res = await res; assert res is None`。

### F13: watchUserPatches 第二次失败广播的 error 类型断言缺失
- TS: `reference/packages/boot/app-boot/tests/user-patches.spec.ts:376` — `expect(failures[1]?.error).toBeInstanceOf(Error)`
- TEST: `tests/1to1/boot/app_boot/test_user_patches.py:448` — 仅 `assert failures[1]["filename"] == filename`
- 类型: WEAK
- 建议修法: 补 `assert isinstance(failures[1]["error"], Exception)`。

### F14: parent.data 身份同一性降级为存在性
- TS: `reference/packages/boot/app-boot/tests/config-reload.spec.ts:97`、`167` — `expect(entry.parent.data.find(o => o.id === 'target')).toBe(entry.options)`（同一对象引用，文件回写一致性的关键）
- TEST: `tests/1to1/boot/app_boot/test_config_reload.py:137`、`232` — `assert any(opt.get("id") == "target" for opt in entry.parent.data)`（仅存在性）
- 类型: WEAK
- 建议修法: 找到匹配项后断言 `is entry.options`（身份同一），恢复 TS 的 toBe 语义。

### F15: programmatic entry move 的 ctx 原型链断言缺失
- TS: `reference/packages/boot/app-boot/tests/config-reload.spec.ts:272` — `expect(Object.getPrototypeOf(target.ctx)).toBe(source.ctx)`
- TEST: `tests/1to1/boot/app_boot/test_config_reload.py:347-350` — 断言了 parent/index/排除/config，唯独缺原型链
- 类型: WEAK
- 建议修法: 若 PY Entry 的 ctx 采用 `__self__.parent` 式作用域链，补等效断言（如 `type(target.ctx).__mro__` 中含 source.ctx 或等效的作用域父指针检查）；若 PY 作用域模型不同，在测试注释中说明该断言在 PY 架构下的对应物。

### F16: cmdline fixture 绕过 Include 挂载，"profile boot 同构挂载"前提未复刻
- TS: `reference/packages/boot/cmdline/tests/cmdline.spec.ts:1-5`（头注释强调 "over a REAL Loader tree, mounted the way a profile boot mounts it"）、`100-158` — 经 `cordis:include` + 文件型 `.mjs` 行 + `structuredClone(composition)` patches 挂载，行 config 携带 `!!js` 表达式
- TEST: `tests/1to1/boot/cmdline/test_cmdline_spec.py:145-194` — 用 `ctx.plugin(DemoStartupPlugin)` + `ctx.loader.register_plugin_class("reader", ...)` + 直接 `loader.create({...})`，完全绕过 Include
- 类型: WEAK（结构性；影响 parseCmdline describe 的全部 8 个用例的 fixture 路径）
- 建议修法: 行内 `__jsExpr`（含 `?? 3080` fallback）与注入等待语义仍被覆盖，核心结果等价；但建议至少增加 1 个经 `mount_root_include`/Include 路径挂载的代表性用例（如 "lets a row read the flag value the app resolved"），使该套件与 spec 头注释宣称的挂载方式一致。

### F17: "rethrow 非对象抛出值"用例在 Python 中不可表达（合法偏离，记录在案）
- TS: `reference/packages/boot/cmdline/tests/cmdline.spec.ts:197-204` — action `throw 'action threw a string'`（裸字符串）
- TEST: `tests/1to1/boot/cmdline/test_cmdline_spec.py:255-264` — `raise Exception("action threw a string")`（本就是异常对象）
- 类型: WEAK（语言限制型省略）
- 建议修法: Python 3.8 无法 raise 非 BaseException 值，属允许偏离范围；建议在 docstring 注明该分支由"语言不可表达"豁免，避免被误判为完整覆盖。

### F18: FAIL_LOUD_RELEASE_TIMEOUT_MS 默认值未被时序用例钉住
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:384-396` — fake timers 推进真实的 `FAIL_LOUD_RELEASE_TIMEOUT_MS`（2000）
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:444-459` — `monkeypatch.setattr(boot_mod, "FAIL_LOUD_RELEASE_TIMEOUT_MS", 50)` 后再测
- 类型: WEAK（轻度；实现按运行时读模块全局，patch 有效，超时机制本身被验证）
- 建议修法: 可接受的平台适配；如需完全对齐，可在不改常量的前提下以 `asyncio.wait_for` 边界断言（约 2s 后 exit）验证，或在测试中同时断言导出常量 == 2000。

### F19: 打包态 ESM proxy 三用例由"实际 import 验证导出值"降级为"文件存在 + 内容子串"
- TS: `reference/packages/boot/app-boot/tests/profile.spec.ts:659-694`、`696-723`、`725-749` — 通过 `import(proxy/entry-N.js)` 断言解析结果 `{ packageName: 'bundle-a' }`、`{ feature: 'proxied' }`、`{ mini: true }`、`{ web: true }`
- TEST: `tests/1to1/boot/app_boot/test_profile.py:807-845`、`849-878`、`882-911` — 仅断言 entry 文件存在及内容包含 "export * from"/"feature.js"/"mini/index.js"/"dist/web/index.mjs"
- 类型: WEAK（平台合理降级：Python 无法执行 JS ESM）
- 建议修法: 若 dsh 的 JS 桥接可加载这些 entry，改为经桥接断言导出值；否则在三个测试的 docstring 注明"TS 侧由动态 import 验证加载正确性，PY 侧降级为产物文本校验"，避免虚报。

### F20: 非 Error 格式化分支被 MockFiber 预包装吞掉
- TS: `reference/packages/boot/app-boot/tests/app-boot.spec.ts:488-495` — 第二个 fiber `await` 抛裸字符串 `'plain failure'`
- TEST: `tests/1to1/boot/app_boot/test_app_boot.py:542-562`（MockFiber.await_ 第 560-562 行将非 BaseException 包装为 `RuntimeError(str(self.error))`）、`605-627`
- 类型: WEAK
- 建议修法: 实现 `_format_activation_error`（app_boot.py:640-642）的 `str(error)` 非 Exception 分支无测试触达。让 MockFiber 支持记录原始抛出值并允许测试注入非异常 reason（例如 fiber 内部直接把非 Exception 交给审计的模拟路径），或在 docstring 注明 Python 侧 raise 通道只产生 Exception。

## 专项检查结论汇总

- **a) 断言钉错语义（WRONG-PIN）**: F3（时序前提未复刻）为唯一实质钉错；F2 接近（测试目标与实际构造不符，归为 OVERCLAIM）。
- **b) 弱断言**: F1/F4/F8（栈文本降级）、F9（次数 1→>=1）、F11（toBe→in）、F12/F13（断言缺失）、F14（身份→存在性）、F15（断言缺失）、F5/F6/F7（断言缺失）。
- **c) 虚报覆盖**: 所有文件 docstring 声称 "1:1 Parity"，实际 31/152 用例存在降级；F2 为最明显的目标性虚报（测试名宣称 non-Error，构造却是 Error）。用例计数与映射本身无造假。
- **d) 顺序/共享状态差异**: F3 直接命中。另记录两处无实质影响的模式差异：TS 用例后置清理 `DSH_HOME`（user-patches.spec.ts:39-41 afterEach），PY 改为每用例前置 `os.environ.pop("DSH_HOME", None)`（test_user_patches.py:72 等，语义等效）；cmdline 的 `restore_internals` autouse fixture 与 TS afterEach 对应（test_cmdline_spec.py:119-129），还原范围还额外包含 `queue_microtask`，无语义差异。
- **允许偏离口径**: bash 系 windowsUnsupported 排除在这 8 个 spec 中不存在；Python 3.8 语法限制均合规（未发现 3.9+ 泛型/`removeprefix`/`match case`）；`!!js` 经全局 `yaml.SafeLoader.add_constructor`（dsh/cordis/loader.py:132-140）使 config-dump 的 `safe_load` 往返成立，`FiberState.DISPOSED == 4`（fiber.py:20）、`ConfigDisposer.disposed`（hmr.py:497-520）、`sys.pkg`（profile.py:194）、`FAIL_LOUD_RELEASE_TIMEOUT_MS` 运行时读取（app_boot.py:580）等实现细节均与测试假设一致。
