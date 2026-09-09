# G11-loader 盲审报告

**范围声明**：设计基准为 `reference/vendor/loader/src/index.ts` 与 `internal.ts`（题目钦定）。index.ts 通过 `export *`（index.ts:11-21）将 entry/group/isolate/tree/utils 的语义纳入 Loader 公共面，且题目重点核对项（await_ 阶段、生命周期时序、事务回滚、isolate/intercept）的实际定义位于 `config/*.ts`，故本报告对这些项引用 vendored 支撑源码作为证据（均为源码，非 docs/）。未读 docs/，未写入任何文件，未运行 pytest/git。

**行数说明**：Python 被审文件实际为 **2251 行**（任务书标注 1951 行），已按实际文件全文通读。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| `export * from entry/group/isolate/tree/utils/internal` (index.ts:11-21) | 单模块 dsh/cordis/loader.py 内联全部实现 | 1:1（re-export 合并为单文件） |
| Events `'exit'` (index.ts:25) | 无事件声明；`Loader.exit()` (loader.py:2087) | 1:1（钩子）/ 声明 N/A |
| Events `'loader/config-update'` (index.ts:26) | 无 loader.py 内发射；include.py:282 发射 | 1:1（发射点在 include，TS 亦不在 index.ts 发射） |
| Events `'loader/entry-init'` (index.ts:27) | emit loader.py:1475；监听 loader.py:1872 | 1:1 |
| Events `'loader/partial-dispose'` (index.ts:28) | emit loader.py:1276,1735,1754,1758,1797,1801；监听 loader.py:2000 | 1:1（payload 三参形状一致） |
| Events `'loader/patch-context'` (index.ts:29) | waterfall loader.py:1573-1576；监听 loader.py:1980 | 1:1 |
| `Context.loader` (index.ts:33) | Service name="loader" (loader.py:1833,1837) | 1:1 |
| `EnvData.startTime` (index.ts:37) | 无 | **D1（缺失）** |
| `Fiber.entry` (index.ts:41) | fiber.entry（loader.py:1593,2006 等） | 1:1 |
| `Loader.Config.baseUrl` (index.ts:50) | config 字典存在但从未消费 | **D2（缺失）** |
| `Loader.Intercept.await` (index.ts:56) | 无 | **D3（缺失）** |
| `Loader` 类 (index.ts:65) | `class Loader(EntryTree, Service)` (loader.py:1827) | 1:1 |
| `envData` (index.ts:68-70) | 无 | **D1** |
| `name='loader'` (index.ts:72) | loader.py:1833 | 1:1 |
| `internal = ModuleLoader.fromInternal()` (index.ts:73) | `self.internal = LoaderInternal()` (loader.py:1859) | D14（ADAPT/DEVIATION-PERMITTED） |
| `builtins` (index.ts:75) | loader.py:1847（另预填 include/group，见自发明 #8） | 1:1 + 等价展开 |
| constructor baseUrl 分支 (index.ts:79-81) | 无 | **D2** |
| `defineProperty(Service.tracker)` (index.ts:84-88) | 委托 `Service.__init__` (loader.py:1837)，tracker 语义不可见 | 范围外待证 |
| `reflect.provide('loader', this, check)` (index.ts:90) | 委托 Service（无 check 回调） | **D3** |
| `internal/config` 监听 (index.ts:92-101) | `_on_internal_config` (loader.py:2093-2112) | 1:1 + D20（tree-carrier 判定键） |
| `internal/update` 保存监听 (index.ts:103-109) | `_on_internal_update` (loader.py:2114-2143)，注册含 prepend ✓ (1863) | 1:1 |
| `internal/update` 'reload' 日志监听 (index.ts:111-115) | 无 | **D4（缺失）** |
| `internal/plugin` 七例监听 (index.ts:117-157) | `_on_internal_plugin` (loader.py:2002-2058) | 1:1（D15 两处防御性偏差） |
| `ctx.plugin(isolate)` (index.ts:159) | 内联为 3 个监听器 (loader.py:1865-2000) | 等价展开 + D9/D10/D12 |
| `write()` no-op (index.ts:162-164) | 继承 EntryTree.write，filepath=None → no-op (loader.py:1163-1166) | 1:1 |
| `[Service.check]` (index.ts:166-170) | 无 | **D3** |
| `showLog` (index.ts:172-175) | `show_log` (loader.py:2060-2072) | 1:1 + D16（%C→%s） |
| `locate` (index.ts:178-185) | loader.py:2074-2085 | 1:1 |
| `exit()` (index.ts:188-189) | loader.py:2087-2089 | 1:1 |
| `unwrapExports` (index.ts:192-199) | `unwrap_exports` (loader.py:1156-1161) | D17（ADAPT） |
| `default Loader` (index.ts:202) | 同类 | 1:1 |
| internal.ts 类型（ModuleFormat/ResolveResult/LoadResult/ModuleWrap/ModuleJob/V1/V2/ModulePhase 等，internal.ts:5-102） | 无（类型 N/A） | N/A（类型） |
| `ModuleLoader.requireInternal` (internal.ts:108-118) | 无 | N/A（Node 内部，Python 不可达） |
| `ModuleLoader.fromInternal` (internal.ts:120-131) | LoaderInternal 硬编码 version="v2" (loader.py:1814-1824) | D14 |
| `LoadCache` (internal.ts:24-28) | `LoadCache(dict)` (loader.py:1809-1811) | ADAPT |

### 支撑面（config/*.ts，服务于重点核对项）

| TS 符号 | Python 符号 | 状态 |
|---|---|---|
| `EntryTree`（tree.ts:7-166） | loader.py:868-1175 | 1:1 为主，D5/D13/D19 |
| `await()`（tree.ts:46-64） | `await_` (loader.py:912-956) | **D5** |
| `getTasks()`（tree.ts:36-40） | `get_tasks` (loader.py:887-902) | D19 |
| `ensureId`（tree.ts:66-73） | `ensure_id` (loader.py:958-965) | 1:1（ADAPT：hex 随机源） |
| `resolve/resolveGroup`（tree.ts:76-94） | loader.py:967-989 | 1:1 |
| `create/remove/update`（tree.ts:97-142） | loader.py:995-1072 | 1:1（回滚聚合文案一致 loader.py:1067） |
| `import`（tree.ts:145-162） | `import_plugin` (loader.py:1074-1152) | ADAPT + D13 |
| `Entry`（entry.ts:52-303） | loader.py:1424-1801 | 1:1 为主，D11/D18/D26 |
| `updateError`（entry.ts:24-27） | `LoaderUpdateError` (loader.py:563-573) | ADAPT（文案逐字一致） |
| `disabledOf`（entry.ts:104-108） | `_disabled_of` (loader.py:1516-1520) | 1:1；但 `eval_condition` (loader.py:447-465) 为 **D11** |
| `refresh`（entry.ts:124-128） | 无 | **D26（缺失）** |
| `_patchContext/_dispose/_start/_init/init/_await/update/getOuterStack`（entry.ts:114-302） | loader.py:1564-1657, 1671-1801 | 1:1（partial-dispose 发射顺序逐点一致）+ D18 |
| `EntryGroup`（group.ts:6-113） | loader.py:1178-1393 | 1:1 为主，**D7/D8** |
| `Group` 插件（group.ts:116-128） | loader.py:1396-1421 | 1:1（init 先 yield stop 再 update，顺序一致） |
| `isolate()`（isolate.ts:71-173） | loader.py:1865-2000 | 等价展开 + **D9/D10/D12** |
| `evaluate/interpolate/isJsExpr`（utils.ts:5-27） | `evaluate_expr/interpolate/is_js_expr` (loader.py:341-444,145-147) | ADAPT（AST 求值器）+ D11 |

## Python 侧自发明清单

| Python 符号/分支 (file:line) | 判定 | 理由 |
|---|---|---|
| `AwaitableString` (loader.py:26-40) | 等价展开 | TS `group.create` 返回 id、`tree.create` 先 `await group.create`（tree.ts:99）；Python 以可 await 字符串+后台 task 复现"返回 id 且可等待" |
| `resolve_plugin_class` (loader.py:43-102) | 等价展开（ADAPT） | 替代 Node ESM `import()`（tree.ts:155-159）的 Python 模块/类解析 |
| yaml `!!js` constructor + `Emitter.choose_scalar_style` 全局 monkeypatch (loader.py:106-142) | 等价展开（ADAPT）+ 记录 | 对应 include YAML `!!js` 序列化；但 monkeypatch 是**进程级全局副作用**，插件不可逆（Cordis effect 原则），需记录 |
| `SafeASTEvaluator`/`evaluate_expr` (loader.py:150-428) | 等价展开（ADAPT） | 对应 utils.ts:5-9 `new Function('ctx','expr', 'with(ctx){return eval(expr)}')`；Python 侧必须换 AST 子集。scope 回退链 `ctx.get(name)`（loader.py:199-222）是超出 TS `with(ctx)` 语义的防御性扩展 |
| `eval_condition` 字符串启发式（`!!js` 前缀、`process.platform/env` 子串，loader.py:458-464） | **无理由发明** | 见 D11 |
| `apply_entry_patches` (loader.py:468-555) | 等价展开（跨包移植） | 自述移植 reference/vendor/include；仅被自发明 `load_from_dict` 使用，不在 loader 基准面 |
| `DuplicateEntryIdError` (loader.py:558-560) | 等价展开 | TS `new TypeError('duplicate loader entry id: ...')`（group.ts:64），Python 复合继承 TypeError ✓ |
| `AggregateError` (loader.py:576-582) | 等价展开（ADAPT） | JS 内建 AggregateError 的 Python 复刻；两条聚合文案 `'loader fibers failed'`/`'loader entry rollback failed'` 与 TS 逐字一致 |
| `sort_keys`/`replace_keys` (loader.py:585-606) | 1:1 | 对应 entry.ts:39-49；中间键排序 `sorted()` 为码点序，TS 为 `localeCompare`（entry.ts:42），非 ASCII 键序可能不同（微小） |
| `EntriesView`/`EntriesDescriptor` (loader.py:609-631) | 等价展开 | 复刻 tree.ts:27-33 生成器（只递归 subtree，不含 subgroup ✓）及 isolate.ts:163 `ctx.loader.entries()` 调用面 |
| `create_js_mock_plugin` (loader.py:634-733) | 无理由发明（测试垫片） | 用正则从 JS/TS 文件合成 Python mock 插件；TS 真实 import JS（tree.ts:155-159）。属测试兼容层，需许可 |
| `Realm`/`LocalRealm`/`GlobalRealm` (loader.py:736-779) | 等价展开（ADAPT） | Symbol→字符串（Python 无 Symbol）；LocalRealm.suffix 用 `entry.id` 偏差见 D12 |
| `_entry_from_package_json`/`resolve_module_specifier` (loader.py:782-865) | 等价展开（ADAPT） | 复刻 Node 模块解析（package.json exports/main、目录索引、bare 上溯 node_modules） |
| `get_tasks` 额外跟踪 root/subgroup `_update_task` + 子树重复收集 (loader.py:890, 897-901) | 等价展开（含缺陷） | TS getTasks 仅 `entry._initTask \|\| entry.fiber?.inertia`（tree.ts:38）；Python 额外纳入组更新任务（扩大 await 等待面），且 `entries()` 已递归子树、899-901 再 `sub.get_tasks()` 导致**同一任务重复入列** |
| `await_` 阶段1 抛错 + 两阶段按 `str(e)` 去重 (loader.py:917-929, 941-947) | **无理由发明** | 见 D5 |
| `EntryTree.__init__` 中 `setattr(self, "await", self.await_)` (loader.py:885) | 等价展开 | 复刻 TS `await()` 方法名（Python 关键字改名 await_） |
| `Entry.__init__` 接受 name/config/disabled/entry_id 直接构造 options (loader.py:1437-1464) | 等价展开 | TS Entry 构造器无参、options 由 `update(create=true)` 填充（entry.ts:66-69, group.ts:23）；Python 为 load_from_dict 路径的结构化变体 |
| `Entry.ctx` 额外注入 `"entry": self` 别名 (loader.py:1474) | 等价展开（防御） | TS 只注入 `[Entry.key]`（entry.ts:67）；别名支撑父链 disabled 走查 |
| `Entry._start` 中 subtree 再挂接 (loader.py:1594-1596) | 等价展开（冗余） | TS 子树挂接只在 EntryTree 构造器（tree.ts:18-19）；Python 两处，幂等无害 |
| `Entry.init()` 同步预创建 fiber (loader.py:1641-1651) | **无理由发明** | 见 D18 |
| `_dispose_async` 清理 `sys.modules` + `importlib.invalidate_caches()` (loader.py:1559-1562) | 等价展开（ADAPT） | Node ESM 缓存不可清除，Python 可；TS `_dispose`（entry.ts:130-139）无此步 |
| `_update_async` commit 时同步 `self.name/self.config` 镜像 (loader.py:1700-1701 等 5 处) | 等价展开（冗余） | TS Entry 无 name/config 属性，commit 仅 `this.options = replaceKeys(...)`（entry.ts:162-165） |
| `replace` 判定相同时 `previous.runtime.callback if previous.runtime else getattr(previous,'plugin',None)` 回退 (loader.py:1770,1774) | 等价展开（防御） | TS 非空断言 `previous.runtime!.callback`（entry.ts:218,223） |
| `EntryGroup.create` 直接 `data.append(options)` (loader.py:1207-1208) + `tree.create` 再补位 (loader.py:1000-1006) | 等价展开（偏离结构） | TS 组建 create 不动 data，仅 tree.create `splice(position,0,...)`（tree.ts:101）；Python 双写以值相等去重，净效果相同 |
| `Group.is_tree_carrier/entry_group_key/inject=["loader"]` (loader.py:1398-1400) | 等价展开（补偿） | 见 D20 |
| `LoaderInternal` 硬编码 v2 (loader.py:1814-1824) | DEVIATION-PERMITTED | 见 D14 |
| `Loader.__init__` 允许 ctx=None 的无头分支 (loader.py:1841-1845) | 无理由发明（防御） | TS 构造器必须 ctx（index.ts:77）；无偏离清单依据，但为无头测试提供便利 |
| `builtins`/`registry_map` 预填 include/group (loader.py:1849-1855) | 等价展开 | TS builtins 由宿主填充（index.ts:75 留空）；Python 同文件持有 Group/Include 故预注册以支撑 `cordis:group` 解析 |
| `load_from_dict`/`load_preset_file`/`register_plugin_class` (loader.py:2145-2247) | 无理由发明（DEVIATION-PERMITTED 候选） | TS 无对应面（TS 经 EntryTree 配置文件装载）；Python 预设系统需要，建议记录许可 |
| `_on_internal_plugin` Case 4 runtime 为 None 时继续而非返回 (loader.py:2028-2030) | 等价展开（防御） | TS `!ctx.registry.has(fiber.runtime!.callback)` 非空断言（index.ts:140） |

## 差异

### D1: `envData` 与 CORDIS_SHARED 完全缺失
- TS: `index.ts:68-70`
```ts
public envData = process.env.CORDIS_SHARED
  ? JSON.parse(process.env.CORDIS_SHARED)
  : { startTime: Date.now() }
```
- PY: 全文件无 `envData`/`CORDIS_SHARED`（grep 证实）；`Loader.__init__` (loader.py:1835-1859) 未定义任何等价物。
- 判定: MUST-FIX
- 影响: 依赖 `ctx.loader.envData.startTime` 的宿主语义（共享进程启动时间）在 Python 侧不存在。
- 建议修法: 在 `Loader.__init__` 中读取 `os.environ.get("CORDIS_SHARED")`，`json.loads` 失败或缺失时回退 `{"startTime": time.time()*1000}`，挂为 `self.envData`。

### D2: `config.baseUrl` 未写入 ctx.baseUrl
- TS: `index.ts:79-81`
```ts
constructor(ctx: Context, public config: Loader.Config = {}) {
  super(ctx)
  if (config.baseUrl) {
    this.ctx.baseUrl = config.baseUrl
  }
```
- PY: loader.py:1835-1859 只做 `self.config = config or {}`，`baseUrl` 键从未被消费；import_plugin 的 base_dir 回退链 (loader.py:1105-1112) 读 `ctx.baseUrl` 但无人写入 config 值。
- 判定: MUST-FIX
- 影响: 相对插件说明符与 `get_outer_stack` 中的 `at {baseUrl}#id`（loader.py:1533）全部落在错误基址（cwd）。
- 建议修法: `Loader.__init__` 在 `EntryTree.__init__` 后加 `if config and config.get("baseUrl"): self.ctx.baseUrl = config["baseUrl"]`。

### D3: `[Service.check]` 的 await 拦截与 `Loader.Intercept` 缺失
- TS: `index.ts:90`、`index.ts:166-170`、`index.ts:54-57`
```ts
ctx.reflect.provide('loader', this, this[Service.check])
...
[Service.check]() {
  const config: Loader.Intercept = Service.prototype[Service.resolveConfig].call(this)
  if (config.await && this.getTasks().length) return false
  return true
}
```
```ts
export interface Intercept {
  /** Keep dependent plugins pending while loader entries are still loading. */
  await?: boolean
}
```
- PY: loader.py 中无 `check` 方法、无 Intercept 语义；`Service.__init__` (loader.py:1837) 提供 'loader' 时未传 check 回调（文件内不可见）。
- 判定: MUST-FIX
- 影响: 依赖 loader 的插件在条目仍在装载时不会被挂起（TS 设计核心：`await: true` 时 check 返回 false 使依赖方 pending）。
- 建议修法: 为 Python `Loader` 增加 `def service_check(self)`：解析自身 config，`config.get("await") and self.get_tasks()` 时返回 False；并确认 `dsh/cordis/service.py` 的 provide 支持 check 回调后接入。

### D4: 'reload' 日志监听器缺失
- TS: `index.ts:111-115`
```ts
ctx.on('internal/update', function (config, _, next) {
  if (!this.entry || this.parent.fiber?.entry === this.entry) return next()
  self.showLog(this.entry, 'reload')
  return next()
}, { global: true })
```
- PY: 仅注册一个 `internal/update` 监听（保存用，loader.py:1863），无第二个非 prepend 监听，`show_log(entry, "reload")` 全文件无调用点。
- 判定: MUST-FIX
- 影响: 配置热更新不再产生 "reload plugin X" 日志。
- 建议修法: `Loader.__init__` 追加 `self.ctx.on("internal/update", self._on_internal_update_log, global_listener=True)`，回调内按 TS 条件（fiber 有 entry 且父 fiber.entry 不同于本 entry）调用 `self.show_log(fiber.entry, "reload")` 并返回 next 结果。

### D5: `await_` 阶段1 行为相反：TS 吞错重试，Python 抛 AggregateError 并按消息去重
- TS: `tree.ts:46-64`（阶段1 allSettled 吞错后 `continue`，仅在阶段2 经 `entry._await()` 重新暴露失败；聚合文案唯一为 `'loader fibers failed'`）
```ts
const tasks = this.getTasks()
if (tasks.length) {
  await Promise.allSettled(tasks)
  continue
}
...
if (failures.length === 1) throw failures[0]
if (failures.length > 1) throw new AggregateError(failures, 'loader fibers failed')
```
- PY: loader.py:912-929
```python
results = await asyncio.gather(*tasks, return_exceptions=True)
failures = [r for r in results if isinstance(r, Exception)]
if failures:
    unique_failures = []          # 按 str(e) 去重 —— TS 无去重
    ...
    if len(unique_failures) == 1:
        raise unique_failures[0]
    raise AggregateError(unique_failures, "loader tasks failed")   # TS 无此阶段/文案
```
阶段2 (loader.py:931-950) 也额外做了 `str(o)` 去重。
- 判定: MUST-FIX
- 影响: 阶段1 任务失败（后续会被 `_await` 以 updateError('apply') 语义重新抛出的）被提前以不同包装/文案抛出；去重掩盖多入口同类错误的计数语义。
- 建议修法: `await_` 阶段1 改为 `await asyncio.gather(*tasks, return_exceptions=True)` 后丢弃结果直接 `continue`；阶段2 保留 `failures` 原样（不去重）以复刻 tree.ts:59-60。

### D6: `EntryGroup.update` 串行创建，丢失并行聚合语义
- TS: `group.ts:71-80`
```ts
const outcomes = await Promise.allSettled(config.map(options => this.create(options)))
if (this.ctx.fiber.uid === null) return
const failures = outcomes.filter(o => o.status === 'rejected').map(o => o.reason)
if (failures.length === 1) throw failures[0]
if (failures.length > 1) throw new AggregateError(failures, 'loader entries failed to apply')
```
- PY: loader.py:1333-1334 顺序执行，首个异常立即进入回滚，无 `'loader entries failed to apply'` 聚合；uid 检查改为 `fiber.uid is None or root_fiber.uid is None`（loader.py:1340-1343，额外加 root_fiber 分支）。
```python
for opt in config_list:
    await self._create_async(opt)
```
- 判定: MUST-FIX（无偏离清单理由；Python 3.8 `asyncio.gather` 可用）
- 影响: 多条目同时失败时只报第一个错误；创建顺序/并发语义与 TS 不一致。
- 建议修法: `_update_async` 中改为 `results = await asyncio.gather(*(self._create_async(o) for o in config_list), return_exceptions=True)`，按 group.ts:76-80 聚合后判定 uid 再决定回滚。

### D7: 组级错误二次包装（错误包装层数）
- TS: `group.ts:103-104`
```ts
if (rollbackErrors.length) throw new AggregateError([error, ...rollbackErrors], 'loader entry rollback failed')
throw error
```
（Entry 层已是唯一 `updateError` 包装：entry.ts:24-27）
- PY: loader.py:1358-1361
```python
if rollback_errors:
    error = AggregateError([error] + rollback_errors, "loader entry rollback failed")
fiber_entry = getattr(getattr(self.tree.ctx, "fiber", None), "entry", None)
if fiber_entry and getattr(fiber_entry, "options", None):
    raise LoaderUpdateError("apply", fiber_entry.options, error)
raise error
```
- 判定: MUST-FIX
- 影响: Entry 已抛 `LoaderUpdateError`，Group 再包一层 → 消息嵌套两层 "failed to apply loader entry ..."，与 TS 单层包装不一致，破坏错误归因。
- 建议修法: `Group._update_async` 末尾直接 `raise error`，删除 1359-1361 的再包装。

### D8: intercept 整体替换被实现为合并
- TS: `isolate.ts:122-126`
```ts
Object.setPrototypeOf(entry.ctx[Context.isolate], entry.parent.ctx[Context.isolate])
Object.setPrototypeOf(entry.ctx[Context.intercept], entry.parent.ctx[Context.intercept])
swap(entry.ctx[Context.isolate], newMap)
swap(entry.ctx[Context.intercept], entry.options.intercept)
```
（`swap` 先清空全部键再拷贝 source，source 为 null 时即清空 → **整体替换**）
- PY: loader.py:1933-1935
```python
intercept_opt = entry.options.get("intercept", {})
if isinstance(intercept_opt, dict):
    entry.ctx._intercept_map.update(intercept_opt)
```
- 判定: MUST-FIX
- 影响: 旧的 intercept 键永不清理；TS 中把 `intercept` 置空即可整体清除，Python 侧残留。
- 建议修法: `_on_patch_context` Step 3 改为 `entry.ctx._intercept_map = dict(intercept_opt) if isinstance(intercept_opt, dict) else {}`（对齐 swap 语义，替换而非 update）。

### D9: isolate step-2 缺失 "expected service ... to be implemented" 告警
- TS: `isolate.ts:110-119`
```ts
const impl = symbol && entry.ctx.reflect.store[symbol]
if (!impl) continue
if (!impl.fiber) {
  entry.ctx.logger.warn(new Error(`expected service ${name} to be implemented`))
  continue
}
```
- PY: loader.py:1918-1923
```python
impl = entry.ctx.reflect.store.get(sym) if ... else None
if not impl:
    continue
impl_fiber = getattr(impl, "fiber", None)
if not impl_fiber:
    continue
```
- 判定: MUST-FIX
- 影响: 服务已注册但无实现 fiber 时静默跳过，丢失 TS 的显式告警诊断。
- 建议修法: `if not impl_fiber:` 分支内 `entry.ctx.logger("loader").warn("expected service %s to be implemented", name)` 后 continue。

### D10: `eval_condition` 对纯字符串禁用条件做表达式求值（TS 一律布尔化）
- TS: `entry.ts:104-108` + `utils.ts:25-27`
```ts
private disabledOf(options: EntryOptions): boolean {
  return isJsExpr(options.disabled)
    ? Boolean(this.evaluate(options.disabled.__jsExpr))
    : Boolean(options.disabled)
}
export function isJsExpr(value: any): value is JsExpr {
  return value instanceof Object && '__jsExpr' in value
}
```
（仅 `{__jsExpr}` 节点求值；裸字符串一律 `Boolean()`——非空字符串即 disabled）
- PY: loader.py:447-465
```python
if isinstance(condition, str):
    cond_str = condition.strip()
    if cond_str.startswith("!!js"):
        return bool(evaluate_expr(ctx, cond_str[4:].strip()))
    if "process.platform" in cond_str or "sys.platform" in cond_str or "process.env" in cond_str:
        return bool(evaluate_expr(ctx, cond_str))
    return bool(cond_str)
```
- 判定: MUST-FIX（`_disabled_of` (loader.py:1516-1520) 是 1:1 的；偏差只在 `eval_condition` 的字符串启发式）
- 影响: `disabled: "process.env.X"` 之类裸串在 TS 恒为 True（disabled），Python 会去求值可能得到 False（enabled）→ 行为相反；且子串命中即可触发求值，属误判面。
- 建议修法: `eval_condition` 删除 459-463 的字符串启发式，仅保留 `is_js_expr` 分支 + `bool(condition)`；裸 `!!js` 前缀串如需支持，应在 YAML 反序列化阶段产出 `{__jsExpr}` 节点而非在求值器内特判。

### D11: LocalRealm.suffix 用 `entry.id`（嵌套全路径）而非 `options.id`
- TS: `isolate.ts:54-56`
```ts
get suffix() {
  return '#' + this.entry.options.id
}
```
- PY: loader.py:766-768
```python
@property
def suffix(self) -> str:
    return f"#{getattr(self.entry, 'id', 'local')}"
```
（`Entry.id` 属性 loader.py:1488-1494 会拼 `parent.id:options.id`）
- 判定: MUST-FIX（低风险）
- 影响: 隔离符号名与 TS 形状不同（功能上仍唯一，但属无理由形状偏离）。
- 建议修法: 改为 `f"#{self.entry.options.get('id', 'local')}"`。

### D12: 未知 `cordis:` 内建抛 KeyError，TS 返回 undefined
- TS: `tree.ts:146-148`
```ts
if (name.startsWith('cordis:')) {
  return this.ctx.loader.builtins[name.slice(7)]
}
```
- PY: loader.py:1079-1085
```python
if name.startswith("cordis:"):
    ...
    if builtin_name in builtins:
        return builtins[builtin_name]
    raise KeyError(f"Unknown cordis builtin: {builtin_name}")
```
- 判定: DEVIATION-PERMITTED（符合仓库 "Misconfiguration fails loud" 立场，但与 TS 静默 undefined 不同，需记录）
- 影响: 未知内建在 TS 下游才失败、Python 在 import 点即失败。
- 建议修法: 保留现状并记录许可即可。

### D13: `Entry.init()` 同步预创建 fiber，导致 `_start` 使用与 import 结果可能不符的插件
- TS: `entry.ts:291-302`
```ts
private async _start(plugin: any) {
  let fiber: Fiber | undefined
  try {
    await this._patchContext([])
    this.loader.showLog(this, 'apply')
    fiber = this.fiber = this.ctx.registry.plugin(plugin, this.options.config, this.getOuterStack)
    await fiber.await()
```
（fiber 一律在 `_patchContext` 之后由 `_start` 用 **import 得到的 plugin** 创建）
- PY: loader.py:1641-1651 先同步 `resolve_plugin_class` 并 `registry.plugin` 预建 fiber；`_start` (loader.py:1587-1590) 发现 `self.fiber` 已存在则**复用预建 fiber 并丢弃 `_init` 中 `import_plugin` 的结果**（loader.py:1611-1628 导入的 plugin 变量成为死值）。
- 判定: MUST-FIX
- 影响: 实际挂载的插件类可能来自 registry_map 快路径而非树解析结果；registry.plugin 调用时机（internal/plugin 事件时序）早于 TS 的 _patchContext 之后。
- 建议修法: 删除 `Entry.init()` 中 1641-1651 的预创建块，让 `_init→_start` 独占 fiber 创建（与 TS 对齐）。

### D14: `LoaderInternal` 硬编码 version="v2"，无 fromInternal 版本探测
- TS: `internal.ts:120-131`
```ts
export function fromInternal(): ModuleLoader | undefined {
  if (_cachedLoader) return _cachedLoader
  const [major] = process.versions.node.split('.').map(Number)
  if (major >= 24) { ... version: 'v2' }
  else if (major >= 22) { ... version: 'v1' }
}
```
（且失败时返回 `undefined`）
- PY: loader.py:1814-1824 恒 `version = "v2"`，resolve/resolveSync 为空 pass，无 fromInternal/缓存。
- 判定: DEVIATION-PERMITTED（Node 内部模块系统在 Python 不可达，接口仅存形状）
- 影响: 仅形状占位；`internal` 恒真值，与 TS 可能为 undefined 的分支不同（tree.ts:154 `if (this.ctx.loader.internal)` 分支在 Python 恒走 internal 路径，但该路径本就是 ADAPT）。
- 建议修法: 保留并记录；如需对齐可在 LoaderInternal 上补 `from_internal()` 类方法返回 stub 或 None。

### D15: `internal/plugin` 两处防御性偏差（uid 判定 / runtime 容忍）
- TS: `index.ts:129` `if (fiber.uid) return`（truthy，uid=0 不返回）；`index.ts:140` `if (!ctx.registry.has(fiber.runtime!.callback)) return`（非空断言）
- PY: loader.py:2014 `if getattr(fiber, "uid", None) is not None: return`（uid=0 会返回）；loader.py:2028-2030 runtime 为 None 时不返回而是继续后续 case。
- 判定: DEVIATION-PERMITTED
- 影响: 仅在 uid 可能取 0 / runtime 缺失的异常场景行为不同；Python 侧更防御。
- 建议修法: 可保持现状；如严格对齐，uid 改 truthy 判断、runtime 缺失时按 TS 抛 AttributeError 暴露问题。

### D16: showLog 细节（%C→%s、name 回退、logger 来源）
- TS: `index.ts:172-175`
```ts
showLog(entry: Entry, type: string) {
  if (entry.options.group || !entry.parent.tree.enableLogs) return
  this.ctx.root.logger?.('loader').info('%s plugin %C', type, entry.options.name)
}
```
- PY: loader.py:2060-2072 —— 门控条件 1:1（group 跳过、enable_logs 缺省 None → 不打日志，与 TS `enableLogs?` undefined 一致，tree.ts:11）；差异：`'%C'`→`'%s'`（Python logger 无 %C，ADAPT）、`entry.options.name` 外多一层 `getattr(entry,'name',str(entry))` 回退、`self.ctx.logger` 而非 `self.ctx.root.logger?.`。
- 判定: ADAPT（%C 为格式化能力差异，属允许的等价改写；name 回退与 ctx.root 差异建议顺手对齐）
- 影响: 日志输出形状略异；无行为破坏。
- 建议修法: `show_log` 内 name 直接取 `opts.get("name")`，logger 改走 `self.ctx.root.logger`（若存在）。

### D17: `unwrapExports` 无 `__esModule` 二次解包
- TS: `index.ts:192-199`
```ts
unwrapExports(exports: any) {
  if (isNullable(exports)) return exports
  exports = exports.default ?? exports
  if (!exports.__esModule) return exports
  return exports.default ?? exports
}
```
- PY: loader.py:1156-1161 —— 仅一层：`hasattr(module,'default')` 即返回 default（且 default 为 None 时 TS `??` 会回退、Python 不会）。
- 判定: ADAPT（Python 模块无 `__esModule` 互操作层；但 None-default 回退差异建议对齐）
- 影响: `default=None` 边缘行为不同；双层解包场景 Python 不存在。
- 建议修法: `d = getattr(module, "default", module); return d if d is not None else module`。

### D18: `EntryGroup.key` 值不一致（'cordis.group' vs 'cordis.entryGroup'）及 tree-carrier 判定补偿
- TS: `group.ts:7` `static readonly key = Symbol.for('cordis.group')`；`group.ts:118` `static readonly [EntryGroup.key] = true`；`index.ts:98-99`
```ts
const plugin = this.runtime?.callback as Record<PropertyKey, unknown> | undefined
if (plugin?.[EntryGroup.key]) return config
```
- PY: loader.py:1180 `key = "cordis.entryGroup"`；Group (loader.py:1396-1400) 未定义该属性，靠 `is_tree_carrier=True` 补偿；`_on_internal_config` (loader.py:2107-2109) 三重判定：
```python
if getattr(plugin, "is_tree_carrier", False) or getattr(plugin, EntryGroup.key, False) or getattr(plugin, "group", False):
```
- 判定: MUST-FIX（键名不一致为设计不一致；三重判定中 `getattr(plugin,"group",False)` 是无理由发明——任何恰好带 truthy `group` 属性的插件都会被跳过插值）
- 影响: 以 `EntryGroup.key` 精确匹配的语义被放宽为属性启发式。
- 建议修法: `EntryGroup.key = "cordis.group"` 并让 `Group` 声明该类属性；`_on_internal_config` 只保留 `getattr(plugin, EntryGroup.key, False)`。

### D19: `get_tasks` 子树任务重复收集 + 额外组任务跟踪
- TS: `tree.ts:36-40`
```ts
getTasks() {
  return [...this.entries()]
    .map(entry => entry._initTask || entry.fiber?.inertia)
    .filter(isNonNullable)
}
```
- PY: loader.py:887-902 —— `entries()` 已递归 subtree（loader.py:622-630），899-901 又 `tasks.extend(sub.get_tasks())` → 子树条目任务重复入列；另纳入 `root._update_task`/`subgroup._update_task`（TS 无）。
- 判定: 等价展开（额外跟踪）+ 缺陷（重复收集）
- 影响: `await_` 对同一任务 gather 两次（无害但浪费）；等待面大于 TS。
- 建议修法: 删除 899-901 的 `sub.get_tasks()` 扩展；组任务跟踪如保留请在报告中记录许可。

### D20: `refresh()` 缺失
- TS: `entry.ts:124-128`
```ts
async refresh() {
  if (this.fiber) return
  if (this.disabled) return
  await this.init()
}
```
- PY: loader.py 全文无 `refresh`。
- 判定: MUST-FIX（公共面缺员）
- 影响: 宿主无法按 TS 语义"惰性补启动"条目。
- 建议修法: `Entry` 增加 `async def refresh(self)`，按 TS 三行直译。

### D21: dispose 时清理 `sys.modules` 并 invalidate_caches
- TS: `entry.ts:130-139` `_dispose` 仅 dispose fiber，无模块缓存操作。
- PY: loader.py:1559-1562 删除 `sys.modules[self._loaded_module_name]` 并 `importlib.invalidate_caches()`。
- 判定: DEVIATION-PERMITTED（Node ESM 缓存不可清除，Python 为支持重载的等价能力）
- 影响: 行为超集，无 TS 对应场景破坏。
- 建议修法: 保留并记录。

### D22: yaml Emitter 全局 monkeypatch（进程级副作用）
- TS: 无对应（!!js 标签由 JS 侧 yaml 栈处理）。
- PY: loader.py:113-129 在 import 时全局替换 `yaml.emitter.Emitter.choose_scalar_style`。
- 判定: DEVIATION-PERMITTED（!!js 序列化所需；但违反 Cordis 可逆 effect 原则，必须记录）
- 影响: 进程内所有 PyYAML 发射行为被改写。
- 建议修法: 记录许可；如需收敛可改为仅在 dump 时使用自定义 Dumper 子类。

### D23: `create_js_mock_plugin` JS 文件合成插件
- TS: 无对应（tree.ts:155-159 真实 import JS）。
- PY: loader.py:634-733 以正则解析 JS/TS 源码合成 Python mock。
- 判定: DEVIATION-PERMITTED（测试兼容垫片，绝不应进入产品路径）
- 影响: `.js/.mjs/.ts` 说明符在 Python 下走 mock 而非真实模块。
- 建议修法: 记录许可并限定仅在测试 preset 中可见。

### D24: `load_from_dict`/`load_preset_file`/`register_plugin_class`
- TS: 无对应公共面（TS 装载走 EntryTree + 配置文件 + `tree.update/create`）。
- PY: loader.py:2145-2247。
- 判定: DEVIATION-PERMITTED（harness 预设系统的 Python 侧入口，超出 loader 基准面但服务同等目标）
- 影响: 额外装载路径绕过 Entry/EntryGroup 事务（直接 registry.plugin，不走 update 回滚/事件），与 TS 装载语义并存。
- 建议修法: 记录许可；长期应让 preset 装载收敛到 `EntryTree.create/update` 事务路径。

### D25: `builtins` 之外的 `registry_map` 快查
- TS: `tree.ts:145-162` import 仅 builtins + 动态 import。
- PY: loader.py:1091-1093、1148-1150 在 builtins 之外查 `registry_map`。
- 判定: 等价展开（ADAPT：Python 类解析需注册表替代 Node 包名解析）
- 影响: 无破坏。
- 建议修法: 无需修改，记录即可。

## 测试缺口

### T1: — `[Service.check]` await 拦截（index.ts:166-170）
无测试钉住：loader 条目装载中（`getTasks()` 非空）且 config `await: true` 时，依赖 loader 的插件保持 pending。当前 Python 完全缺失该行为（D3），测试先行可锁修复。

### T2: — 'reload' 日志（index.ts:111-115）
无测试钉住：非树载体 entry 的 `internal/update` 触发 `showLog(entry,'reload')` 且父 fiber 同 entry 时不触发。D4 缺失的直接验证点。

### T3: — `await()` 阶段语义（tree.ts:46-64）
无测试钉住：阶段1 任务失败被吞掉（allSettled + continue），最终错误必须经阶段2 `entry._await()` 以 `updateError('apply')` 形状抛出，多条失败聚合文案恰为 `'loader fibers failed'`（无 'loader tasks failed'、无消息去重）。D5 的回归锁。

### T4: — 组更新并行聚合（group.ts:71-80）
无测试钉住：多条目并发创建时两条同时失败 → `AggregateError(failures, 'loader entries failed to apply')`；`ctx.fiber.uid === null` 时创建后直接 return 不回滚。D6/D7 的回归锁（含 group.ts:103-104 `throw error` 不再包装）。

### T5: — intercept 整体替换（isolate.ts:126）
无测试钉住：entry 更新把 `intercept` 从 `{a:1}` 改为 `null`/`{b:2}` 后，旧键 `a` 必须消失（swap 语义）。D8 的回归锁。

### T6: — isolate 缺实现告警（isolate.ts:113-115）
无测试钉住：`reflect.store` 存在服务符号但实现 fiber 缺失时产生 `expected service <name> to be implemented` 告警且跳过 diff 项。D9 的回归锁。

### T7: — envData（index.ts:68-70）
无测试钉住：设置 `CORDIS_SHARED` 环境变量后 `ctx.loader.envData` 为其 JSON 解析结果，未设置时含数值 `startTime`。D1 的回归锁。

### T8: — config.baseUrl 传导（index.ts:79-81）
无测试钉住：`Loader(ctx, {baseUrl})` 后 `ctx.baseUrl` 被设置，且 `get_outer_stack` 输出 `    at {baseUrl}#{id}`。D2 的回归锁。

### T9: — unwrapExports 互操作（index.ts:192-199）
无测试钉住：`{default: X, __esModule: True}` → X；`{default: None}` → 原对象（`??` 回退）。D17 的回归锁。

### T10: — disabledOf 裸串布尔化（entry.ts:104-108）
无测试钉住：`disabled: "process.platform == 'win32'"`（裸字符串，非 `__jsExpr` 节点）必须按 `Boolean(value)` = True 处理（disabled），而不是求值。D10 的回归锁。

### T11: — `_start` 使用 import 结果创建 fiber（entry.ts:291-296）
无测试钉住：`init()` 后实际挂载的插件必须来自 `tree.import` + `unwrap_exports` 的返回值，而非注册表预解析副本。D13 的回归锁。

## PROBE 候选

- D5: 场景——一个 entry 装载任务失败 + 另一 entry fiber settled 失败，调用 `await_`：探测 Python 是否在阶段1 就抛 `AggregateError("loader tasks failed")`（TS 应吞掉任务失败、在阶段2 抛 `updateError('apply')` 或 `'loader fibers failed'` 聚合）。理由：两阶段职责错位是最难靠肉眼确认的时序差异。
- D13/D18: 场景——同名插件同时存在于 `registry_map` 与可解析模块路径（返回类不同），创建 entry 后探测 `entry.fiber.plugin` 到底是哪个：验证 `_start` 复用预建 fiber 丢弃 import 结果的行为（D13）与 `is_tree_carrier` 启发式是否误伤带 `group` 属性的普通插件（D18 判定分支）。
- D7/D6: 场景——两条目同时 import 失败：探测最终异常的嵌套层数与文案（期望单层 updateError 或 `'loader entries failed to apply'` 聚合；现状疑似双层 LoaderUpdateError 嵌套）。
- D8: 场景——entry 先配 `intercept: {tools: {...}}` 再更新为 `intercept: null`，探测 `_intercept_map` 是否残留旧键（swap 语义下必须为空）。
