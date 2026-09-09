# G9-hmr 盲审报告

审计对象：`reference/vendor/hmr/src/index.ts`（576 行）+ `error.ts`（36 行）↔ `dsh/cordis/hmr.py`（642 行）。全部行号引文来自本次通读；未使用 docs/ 任何文件。补充核验了 `dsh/cordis/loader.py`、`context.py`、`service.py`、`logger.py`、`fiber.py`、`registry.py` 的 API 事实（仅用于判定调用点活性与签名，不作为设计基准）。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态（1:1 / ADAPT / D#） |
|---|---|---|
| `loadDependencies` (index.ts:37) | `ModuleDependencyGraph.scan_file` / `get_transitive_dependents` (hmr.py:36, hmr.py:109) | ADAPT（语义缺口见 D20） |
| `interface Reload` (index.ts:50) | `reloads[old_key] = {"filename", "runtime"}` (hmr.py:445) | 1:1（形状） |
| `interface ConfigRefresh` (index.ts:55) | `class ConfigRefreshState` (hmr.py:128) | 1:1 |
| `interface ConfigRegistration` (index.ts:60) | 无（`_configs: Dict[str, Callable]`，hmr.py:170） | D16 |
| `findWatchRoot` (index.ts:64) | `find_watch_root` (hmr.py:134) | 1:1（errno 口径差异 D14） |
| `class Hmr extends Service` (index.ts:86) | `class ConfigWatcherService(Service)` (hmr.py:156) | 见各 D# |
| `static inject = ['loader','timer']` (index.ts:87) | `inject = ["loader", "timer"]` (hmr.py:164) | 1:1 |
| `baseDir` + 构造器解析 (index.ts:89, index.ts:124) | `base_dir` 解析 (hmr.py:180-199) | ADAPT |
| `internal`/`watcher`/`configs`/`configRefreshes`/`refreshTasks` (index.ts:91-95) | `_configs`/`_mtimes`/`_config_contents`/`_refreshes`/`_refresh_tasks`/`_poll_task` (hmr.py:170-177) | ADAPT（chokidar→轮询） |
| `externals` (index.ts:101) | 无 | D1 |
| `accepted` (index.ts:107) | 无 | D4 |
| `declined` (index.ts:113) | 无 | D4 |
| `stashed` (index.ts:116) | 无 | D2/D19 |
| 构造器守卫 `--expose-internals` (index.ts:120-122) | 无对应检查 (hmr.py:166-210) | D8 |
| `registerConfig` (index.ts:134) | `register_config` (hmr.py:468)（别名 `registerConfig` hmr.py:557） | D16 |
| `_resolve` (index.ts:192) | 无（`LoaderInternal.resolve/resolveSync` 为 `pass` 桩，loader.py:1820-1824） | D5 |
| `[Service.init]`（启动 + teardown yield）(index.ts:199-295) | 无 init 挂接；构造器自启轮询 (hmr.py:206-210) + `teardown`/`_async_teardown` (hmr.py:623, hmr.py:605) | ADAPT（取消语义差异 D9） |
| `refreshConfig` (index.ts:297) | `_trigger_config_refresh` (hmr.py:324) | D10/D11 |
| `getOuterStack` (index.ts:327) | 无 | D15 |
| `getLinked` (index.ts:331) | `ModuleDependencyGraph`（经 hmr.py:389 消费） | ADAPT |
| `analyzeChanges` (index.ts:345) | 无 | D4 |
| `partialReload` (index.ts:400) | `_trigger_module_reload` (hmr.py:370) | D2/D3/D5/D12/D19 |
| `namespace Hmr.Config` schema (index.ts:552-574) | 裸 dict `config.get(...)` (hmr.py:168-201) | D7 |
| error.ts `isBuildFailure` (error.ts:6) | 无 | D13 |
| error.ts `handleError` (error.ts:11) | 无 | D13 |
| —（TS 无） | `_poll_loop` 根扫描 (hmr.py:212) | ADAPT（语义差异 D2/D6/D7/D17/D19） |
| —（TS 无） | `register_module`/`registerModule` (hmr.py:559, hmr.py:603) | D18（自发明） |
| —（TS 无） | `ConfigDisposer` (hmr.py:497) / `RegistrationPromise` (hmr.py:539) | ADAPT（对应 TS async disposer，D16） |
| —（TS 无） | `_config_contents` 字节级内容比对 (hmr.py:234-248) | D15（自发明增强） |
| —（TS 无） | 别名 `Hmr`/`HmrService` (hmr.py:641-642) | D15（无害） |

## 差异

### D1: externals 全量重载路径（`loader.exit()`）整体缺失
- TS: `index.ts:260` 摘录
  ```ts
  // Full reload: the changed file is part of the framework
  if (this.externals.has(url)) return loader.exit()
  ```
  externals 在 init 时采集：`index.ts:220-226`
  ```ts
  const mainUrl = pathToFileURL(resolve(process.argv[1])).href
  const mainJob = this.internal.loadCache.get(mainUrl)
  if (mainJob) {
    this.externals = await loadDependencies(mainJob)
  } else {
    this.externals = new Set()
  }
  ```
- PY: 无任何 externals 概念。root 扫描只有"缓存外→emit / 缓存内→无动作"两分支 (hmr.py:304-313)。Python `Loader.exit` 存在（loader.py:2087）但 hmr.py 全文不调用。
- 判定： MUST-FIX
- 影响: 框架自身文件（CLI 入口依赖树）变更永远不做全量重载，行为静默丢失。
- 建议修法: 在 `ConfigWatcherService` 初始化时以入口模块依赖图（`sys.modules` + `ModuleDependencyGraph`）构建 `self.externals`，在 `_poll_loop` 根扫描变更分支中优先匹配 externals 并调用 `self.ctx.loader.exit()`。

### D2: loadCache 命中分支缺失——root 监视下部分重载入口不可达
- TS: `index.ts:265-268` 摘录
  ```ts
  if (loader.internal!.loadCache.has(url)) {
    this.stashed.add(url)
    return partialReload()
  }
  ```
- PY: `hmr.py:304-313`
  ```python
  if load_cache is not None and hasattr(load_cache, "has"):
      in_cache = load_cache.has(url)
  else:
      in_cache = False
  if not in_cache and hasattr(self.ctx, "emit"):
      self.ctx.emit("hmr/change", url)
  ```
  命中缓存时无动作。且经 grep 证实：`dsh/` 全仓库无任何代码向 `internal.loadCache` 写入（`LoadCache` 定义于 loader.py:1809-1818，仅此一处），`in_cache` 恒为 False——TS 的 stash+partialReload 分支在 Python 中不可达，`_trigger_module_reload` 仅能由自发明的 `register_module`（D18）触发。emit 分支本身与 TS else 分支（index.ts:270）一致。
- 判定： MUST-FIX
- 影响: root 监视到的模块变更永远不会触发热重载；hmr/change 语义虽对齐但热重载主链路断裂。
- 建议修法: 让 Python loader 在导入插件时写入 `internal.loadCache[url]`，并在 `_poll_loop` 中对 `in_cache` 文件进入与 TS 对应的 stash + 防抖 partialReload 路径。

### D3: 部分重载无事务性——无缓存备份、无 rollback、无失败重挂
- TS: `index.ts:461-489` 备份与回滚
  ```ts
  for (const filename of this.accepted) {
    const job = Map.prototype.get.call(this.internal.loadCache, filename)
    esmBackup[filename] = job
    Map.prototype.delete.call(this.internal.loadCache, filename)
    ...
  }
  const rollback = () => { ... }
  ```
  导入失败：`index.ts:497-500` `handleError(this.ctx, e); return rollback()`；重载/卸载失败：`index.ts:532-545` `rollback()` 后对每个 reloads 项 `registry.delete(attempts[filename]); reload(plugin, runtime)` 重挂旧插件。
- PY: `hmr.py:376-460` 直接 `exec` 新合成模块（hmr.py:399-407）、直接手术 `registry._runtimes`（hmr.py:431-432）、`await fiber.restart()`（hmr.py:443）；任一步失败（hmr.py:453）无任何恢复——已重载文件、已换键的 runtime、已 restart 的 fiber 全部留在半途状态。
- 判定： MUST-FIX
- 影响: 重载中途失败导致插件处于新旧混合的不可逆状态，违背 TS 的原子重载设计。
- 建议修法: 在 `_trigger_module_reload` 中先备份 `sys.modules` 中受影响原模块与 `registry._runtimes` 键值及 fiber 状态，exec/restart 失败时恢复备份并重挂旧类（对齐 TS rollback 两段式）。

### D4: `analyzeChanges` accepted/declined 分类不动点缺失
- TS: `index.ts:348-351` 摘录
  ```ts
  this.accepted = new Set(this.stashed)
  this.declined = new Set(this.externals)
  const isExcluded = (url: string) => url.startsWith('node:') || url.includes('/node_modules/')
  ```
  `index.ts:361-397` 为 accepted/declined 传播的不动点循环，残余 pending 一律归入 declined。
- PY: 无 accepted/declined。`hmr.py:389-390`
  ```python
  dependents = self.graph.get_transitive_dependents(abs_changed)
  files_to_reload = [abs_changed] + [f for f in dependents if f != abs_changed]
  ```
  无条件重载全部传递依赖，无 externals 排除、无"依赖者全 declined 则 declined"传播。
- 判定： MUST-FIX
- 影响: 与 TS 重载范围判定设计不一致；externals 之外的"不应重载"文件也会被卷入。
- 建议修法: 以 `get_transitive_dependents` 结果为基础实现 accepted/declined 双集合分类（含 externals 种子与不动点传播），再决定 `files_to_reload`。

### D5: 插件入口原子单元缺失——改为按文件 exec + `registry._runtimes` 私有字段手术
- TS: `index.ts:408-411` 以 loader entries 构建入口名映射
  ```ts
  const nameMap: Dict<Set<string>> = Object.create(null)
  for (const entry of this.ctx.loader.entries()) {
    (nameMap[entry.parent.tree.ctx.baseUrl!] ??= new Set()).add(entry.options.name)
  }
  ```
  `index.ts:417` `const { url } = await this._resolve(name, baseUrl, {})`；`index.ts:495` 经 `loader.import` 重新导入入口文件；`index.ts:505` 经 `oldFiber.parent.registry.plugin(...)` 正常生命周期重挂载。
- PY: `hmr.py:394-407` 每个文件单独 `compile`+`exec` 进合成模块 `hmr_reloaded_<hash>_<ms>`；`hmr.py:423-432` 直接读写 `registry._runtimes`（registry.py:156 确为私有实现字段）；`hmr.py:434-442` 手工替换 `fiber.plugin`，不经 registry 正常 dispose/apply 路径。Python `LoaderInternal.resolve/resolveSync` 为 `pass` 桩（loader.py:1820-1824），`_resolve` 无功能等价物。
- 判定： MUST-FIX
- 影响: 绕过插件生命周期（资源未按 dispose 释放顺序清理）；入口文件原子性丢失，插件多文件重载可能不一致。
- 建议修法: 复用 Python loader 的 entries/registry 公共 API（`registry.delete` + 正常挂载路径）重写 `_trigger_module_reload` 的重挂载段，避免触碰 `_runtimes`。

### D6: debounce 合并语义缺失——`debounce` 配置仅作轮询间隔
- TS: `index.ts:242` 摘录
  ```ts
  const partialReload = this.ctx.debounce(() => this.partialReload(), this.config.debounce)
  ```
  窗口内多文件变更累积进 `stashed`（index.ts:266）合并为一次 partialReload。
- PY: `hmr.py:215`
  ```python
  await asyncio.sleep(max(0.02, self.debounce_ms / 1000.0))
  ```
  `debounce_ms` 只决定轮询周期；同文件由 `state.dirty` 合并（hmr.py:372-378），不同文件每个轮询 tick 各自立即触发独立重载任务，无窗口合并、无 stash 累积。
- 判定： MUST-FIX
- 影响: 连续多文件变更触发 N 次独立重载而非 1 次合并重载，与 TS 事务粒度不一致。
- 建议修法: 引入 `_stashed: Set[str]` 与防抖调度器，在 `_poll_loop` 检出变更后 stash 并按 `debounce_ms` 合并调度单次 partialReload。

### D7: `ignored` 配置接受但未消费；`root` 默认值 `['.']` vs `[]`
- TS: `index.ts:562-569` 摘录
  ```ts
  root: z.array(String).role('table').default(['.']),
  ignored: z.array(String).role('table').default([
    '**/node_modules',
    '**/.*',
    'cache',
    'data',
  ]),
  debounce: z.natural().role('ms').default(100),
  ```
  消费点：`index.ts:215` `const match = picomatch(ignored)`、`index.ts:231` `ignored: path => match(relative(watchBaseDir, path))`。
- PY: `hmr.py:201` `self.root = list(self.config.get("root", []))`——默认 `[]`（且为 `[]` 时根扫描整体跳过，hmr.py:280）；`ignored` 键全文无 `config.get("ignored")`，被完全忽略；替代物为硬编码目录名剪枝 `hmr.py:288`
  ```python
  dirs[:] = [d for d in dirs if d not in (".venv", "node_modules", ".git", "__pycache__", "dist", ".pytest_cache")]
  ```
  仅剪目录名：TS 默认会忽略的 `**/.*`（点文件）、名为 `cache`/`data` 的**文件**在 Python 中不被忽略；用户配置的 glob 模式一律失效。
- 判定： MUST-FIX
- 影响: 默认 watch 集为空（缺省行为改变）；`ignored` 属"接受但未消费"审计项，过滤语义不对齐。
- 建议修法: `root` 默认改为 `["."]`；实现 glob（`fnmatch`/picomatch 等价）对 `config["ignored"]` 的相对路径匹配并替换硬编码剪枝（保留硬编码项作为默认值来源，对齐 TS 四条默认模式）。

### D8: 构造器缺少 `loader.internal` 守卫
- TS: `index.ts:120-122` 摘录
  ```ts
  if (!this.ctx.loader.internal) {
    throw new Error('--expose-internals is required for HMR service')
  }
  ```
- PY: `hmr.py:166-210` 构造器无对应检查（`loader.internal` 经 `_poll_loop` 内 `getattr` 容错访问，hmr.py:305-307）。
- 判定： MUST-FIX
- 影响: 缺 loader 内部能力时服务静默降级而非显式失败（违反 misconfiguration fails loud）。
- 建议修法: 在 `__init__` 中检查 `ctx.get("loader")` 及其 `internal` 属性，缺失时 raise。

### D9: 在飞刷新取消语义相反——TS 永不取消，Python 2 秒后 cancel
- TS: `index.ts:177-181` disposer 摘录
  ```ts
  return this.ctx.effect(() => async () => {
    if (this.configs.get(watchFilename) === registration) this.configs.delete(watchFilename)
    await watcher.close()
    await this.configRefreshes.get(registration)?.running
  }, 'hmr.registerConfig()')
  ```
  无限等待；teardown `index.ts:200-205` `await Promise.allSettled([...this.refreshTasks])`——等待全部完成，从不取消。
- PY: 模块 unregister `hmr.py:584-589`
  ```python
  await asyncio.wait_for(asyncio.shield(state.running), timeout=2.0)
  ...
  state.running.cancel()
  ```
  `_async_teardown` `hmr.py:613-617` 同样 2 秒超时后对全部在飞任务 `t.cancel()`。另注：`_trigger_module_reload` 创建的任务未加入 `_refresh_tasks`（hmr.py:462-466 无 add/done_callback，与 hmr.py:355-356 不对称），仅靠 `_refreshes` 间接覆盖。
- 判定： MUST-FIX
- 影响: 长刷新（如慢 include.apply）在 teardown/反注册时被强杀，TS 语义是等待其自然完成。
- 建议修法: `_async_teardown` 改为无超时 `await asyncio.gather(*running_tasks, return_exceptions=True)`（等价 allSettled）；模块 unregister 同步去除 cancel 分支。

### D10: `_trigger_config_refresh` 捕获 `BaseException` 吞掉 `CancelledError`；非 Error 原因无 cause 链
- TS: `index.ts:307-308` 摘录
  ```ts
  } catch (reason) {
    const error = reason instanceof Error ? reason : new Error(String(reason), { cause: reason })
  ```
  仅捕获异常；非 Error 原因保留 `cause` 链。
- PY: `hmr.py:339-340`
  ```python
  except BaseException as reason:
      error = reason if isinstance(reason, Exception) else Exception(str(reason))
  ```
  Python 3.8 中 `asyncio.CancelledError` 继承 `BaseException`（非 `Exception`），被捕获后转为普通 `Exception` 并触发 `hmr/config-update-failed` 并行事件（hmr.py:344-346）——任务取消被误报为配置刷新失败；且 `Exception(str(reason))` 丢失 `__cause__`。
- 判定： MUST-FIX
- 影响: 取消传播被吞并产生虚假失败事件；错误因果链丢失。
- 建议修法: 改为 `except Exception as reason:`，取消（`CancelledError`）直接 `raise`；非 Exception 原因构造错误时设置 `error.__cause__ = reason`。

### D11: 无事件循环时的同步回退路径——refresh_fn 同步异常逃逸 + 重复 `asyncio.run` 块
- TS: 无此路径（refreshConfig 恒为异步任务，index.ts:302-323；registerConfig 有 ready await，index.ts:175-186）。
- PY: `hmr.py:357-368`
  ```python
  except RuntimeError:
      res = refresh_fn()
      if inspect.isawaitable(res):
          try:
              asyncio.run(res)
          except Exception:
              pass
      if inspect.isawaitable(res):
          try:
              asyncio.run(res)
          except Exception:
              pass
  ```
  两处缺陷：(a) `refresh_fn()` 同步抛错（hmr.py:358）不被捕获，向上逃逸到 `_poll_loop` 泛化 `except Exception`（hmr.py:320-322），绕过 `hmr/config-update-failed` 事件；(b) 第二个 `asyncio.run(res)` 对同一 coroutine 二次运行必然 RuntimeError 被吞，为笔误级重复块。TS 中刷新失败一律走 normalize→warn→parallel 事件。
- 判定： MUST-FIX
- 影响: 同步上下文中刷新失败既不告警到 logger 也不发事件，错误静默。
- 建议修法: 删除重复块；将 `refresh_fn()` 调用纳入 try 并复用与异步分支相同的 normalize/parallel 错误路径。

### D12: `hmr/config-update-failed` 被自发明用于模块重载失败
- TS: `index.ts:27-29` 事件契约摘录
  ```ts
  /**
   * A watched config-file refresh failed.
   * @param filename - Absolute path observed by HMR.
   * @param error - Normalized refresh failure.
   * @mode parallel
   */
  'hmr/config-update-failed'(filename: string, error: Error): Promise<void> | void
  ```
  唯一发射点在 `refreshConfig`（index.ts:312）；模块重载失败走 `handleError`+rollback（index.ts:497-500）或 warn+rollback（index.ts:511-545），不发此事件。
- PY: `hmr.py:456-458`
  ```python
  if hasattr(self.ctx, "parallel"):
      try:
          await self.ctx.parallel("hmr/config-update-failed", filename, reason)
  ```
  模块重载失败也发该事件。
- 判定： MUST-FIX
- 影响: 事件语义外溢，监听方无法区分"配置刷新失败"与"模块重载失败"。
- 建议修法: `_trigger_module_reload` 失败分支改走 warn + rollback（D3 修复后），移除该 parallel 调用（或引入独立事件名并记录为扩展点）。

### D13: error.ts `handleError`（BuildFailure 分类 + code frame）无 Python 对应
- TS: `error.ts:11-15` 摘录
  ```ts
  export function handleError(ctx: Context, e: any) {
    if (!isBuildFailure(e)) {
      ctx.logger.warn(e)
      return
    }
  ```
  及 `error.ts:22-31` 逐错误 `codeFrameColumns` 渲染源码帧。
- PY: 无对应函数；模块重载失败仅 `warn("Module reload at %s failed: %s", ...)` (hmr.py:455)。
- 判定： DEVIATION-PERMITTED
- 影响: 仅日志诊断呈现差异（无 esbuild/`@babel/code-frame` 等价物，非两条允许偏离强制项，故记录许可而非 ADAPT）。
- 建议修法: 如需对齐，可用 `linecache` + traceback 实现轻量 code-frame 的 `handle_error(ctx, e)`，挂在 D3 修复后的导入失败点。

### D14: `find_watch_root` 对一切 `OSError` 向上冒泡（TS 仅 ENOENT）
- TS: `index.ts:76-79` 摘录
  ```ts
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
    const parent = dirname(root)
    if (parent === root) throw error
  ```
- PY: `hmr.py:148-151`
  ```python
  except (FileNotFoundError, OSError):
      parent = os.path.dirname(root)
      if parent == root:
          raise
  ```
  EACCES 等非 ENOENT 错误也继续上溯直至文件系统根。非目录错误消息语义已保留（RuntimeError，hmr.py:143）。
- 判定： DEVIATION-PERMITTED
- 影响: 仅在路径中段出现权限/其他 I/O 错误时行为不同（TS 快速失败，Python 上溯后报根目录错误）。
- 建议修法: 收窄为 `except FileNotFoundError`（Windows 7 下保留 OSError 中 ENOENT 判定可用 `e.errno == errno.ENOENT`）。

### D15: 日志与杂项表面差异（自发明成功日志、缺启动/检测日志、`getOuterStack` 缺失、内容比对兜底、类别名）
- TS: `index.ts:209-213` 启动日志摘录
  ```ts
  if (!this.config.base) {
    this.ctx.logger.info('watching %o', root)
  } else {
    this.ctx.logger.info('watching %o in %s', root, this.baseDir)
  }
  ```
  `index.ts:244-245` 变更 debug 日志；`refreshConfig` 无成功 info（index.ts:297-324）。`getOuterStack`（index.ts:327-329）为 loader.import 提供空栈帧。TS 无内容字节比对（chokidar 事件语义）。
- PY: 无启动 `watching` 日志、无变更 debug 日志；新增成功日志 `hmr.py:338` `info("Reloaded config file %s", filename)` 与 `hmr.py:450-451`；logger 经 `self.ctx.logger("hmr")` 命名子 logger（`LoggerService.__call__`，logger.py:322，调用合法）而 TS 直接用 `ctx.logger`；自发明 `_config_contents` 字节比对（hmr.py:234-248，mtime 未变但内容变时比 TS 更灵敏）；自发明别名 `Hmr`/`HmrService`（hmr.py:641-642）；`getOuterStack` 无对应（Python 无 loader 栈帧隐藏需求）。
- 判定： DEVIATION-PERMITTED
- 影响: 观测面细节差异，无行为分支影响（内容比对仅提高灵敏度）。
- 建议修法: 如需逐项对齐可补充 watching info/debug 日志、移除成功 info；内容比对与别名可保留并记录。

### D16: `registerConfig` 生命周期弱化——无 ready/error 阶段、启动失败不抛、disposer 无恒等检查
- TS: `index.ts:175-186` 摘录
  ```ts
  try {
    await ready.promise
    return this.ctx.effect(() => async () => {
      if (this.configs.get(watchFilename) === registration) this.configs.delete(watchFilename)
      ...
    }, 'hmr.registerConfig()')
  } catch (error) {
    this.configs.delete(watchFilename)
    await watcher.close()
    throw error
  }
  ```
  watcher 启动失败 → 清理 + rethrow；disposer 带注册对象恒等检查（index.ts:178）。
- PY: `hmr.py:478-495` 注册即生效；`find_watch_root` 失败仍抛（覆盖 TS"路径不可用即抛"的一部分），但无 ready 等待与启动失败清理路径；`RegistrationPromise`（hmr.py:539-555）立即 resolve 返回 disposer；disposer 无恒等检查 `hmr.py:505` `self.hmr._configs.pop(self.canonical_filename, None)`。`ctx.effect(lambda: disposer, label=...)` (hmr.py:536-537) 与 TS effect 形态对应（context.py:181 签名兼容）。config disposer 等待在飞刷新语义与 TS 一致（hmr.py:510-513 shield await，无 cancel）。
- 判定： ADAPT（轮询实现无启动阶段，属文件监听等价实现差异，按偏离清单第 2 条处理）+ disposer 恒等检查缺失为 DEVIATION-PERMITTED（重复注册已被 hmr.py:479-480 阻止，单文件单注册下不可察觉）
- 影响: 启动失败反馈时机后移；恒等检查差异在当前用法下不可达。
- 建议修法: disposer 中改为 `if self.hmr._configs.get(...) is refresh_fn: pop(...)`；如需对齐启动失败语义，可在注册时对根目录做一次预检并抛错。

### D17: root 扫描缺少 loader include（cordis.yml 类）匹配
- TS: `index.ts:249-254` 摘录
  ```ts
  for (const entry of loader.entries()) {
    const include = entry.subtree as Include | undefined
    if (include?.filename !== filename && include?.filename !== configuredFilename) continue
    this.refreshConfig(include, include.filename, () => include.refresh())
    return
  }
  ```
- PY: `_poll_loop` 根扫描（hmr.py:280-316）无 include 匹配逻辑。Python loader 具备实现条件：`entries()`（loader.py:1384）与 `Include` 内建（loader.py:1849-1853），但未使用。config include 文件在 root 监视下不会触发 `refreshConfig`；只有显式 `register_config` 的路径被监视。
- 判定： MUST-FIX
- 影响: TS 主监视器最重要的配置热更新路径（cordis.yml 变更即刷新 include 子树）在 root 监视维度缺失。
- 建议修法: 在根扫描变更分支（`url` 计算处，hmr.py:304）之前插入 loader entries 的 include filename 匹配，命中即走 `_trigger_config_refresh`。

### D18: 自发明 `register_module`/`registerModule` 公共 API 及其 add/unlink 触发语义
- TS: 无此 API。模块热重载仅经 root 监视 + loadCache + partialReload；且对非 change 事件直接返回：`index.ts:256` 摘录
  ```ts
  if (kind !== 'change') return
  ```
- PY: `hmr.py:559-603` `register_module`（含 `_modules` 字典，hmr.py:171）；`_poll_loop` 对注册模块的 **add 事件也触发重载**（hmr.py:268-270）、**unlink 事件也触发重载**（hmr.py:275-277）——两者均为 TS 明确不做的行为。其 unregister 的 2s-cancel 语义见 D9。
- 判定： MUST-FIX（自发明公共行为；且因 D2，它成了 Python 中唯一能触发模块重载的入口，掩盖了主链路缺失）
- 影响: API 表面与重载触发时机均为 TS 不存在的设计。
- 建议修法: 若保留需作为明确的 Python 侧扩展点记录并与 D2 修复协调；unlink/add 触发应移除以对齐"仅 change"语义。

### D19: 变更消费/重试语义——TS 失败保留 stash 待重试，Python 预写 mtime 致变更被消费
- TS: `index.ts:548` 摘录
  ```ts
  this.ctx.emit('hmr/reload', reloads)
  this.stashed = new Set()
  ```
  仅成功路径清空 stash；失败（rollback/return）后 stash 保留，下次防抖触发自然重试。
- PY: `hmr.py:269-272`
  ```python
  if last_mtime == 0.0:  # add event
      self._mtimes[filename] = (mtime, size)
      self._trigger_module_reload(filename, target_plugin)
  elif mtime != last_mtime or size != last_size:  # change event
      self._mtimes[filename] = (mtime, size)
      self._trigger_module_reload(filename, target_plugin)
  ```
  在触发重载**之前**写回新 mtime/size（root 扫描同理，hmr.py:303；config 路径 hmr.py:249）；重载失败后该变更已被消费，不再重试。
- 判定： MUST-FIX
- 影响: 一次瞬时失败（如编译期语法错误刚被修复前的窗口）永久吞掉该次变更。
- 建议修法: 将 mtime 写回移至重载任务成功路径（配合 D3 的 stash 化改造）。

### D20: `ModuleDependencyGraph` 静态 AST 近似的语义缺口（ADAPT 的边界记录）
- TS: `index.ts:37-48` 基于运行时真实模块图摘录
  ```ts
  if (job.url.startsWith('node:') || job.url.includes('/node_modules/')) return
  dependencies.add(job.url)
  const children = await job.linked
  ```
  并支持 ignored 剪枝参数（index.ts:433 `loadDependencies(job, this.declined)`）。
- PY: `hmr.py:96-107` `_resolve_module`
  ```python
  for b in (cur_dir, base_dir, os.getcwd()):
      cand = os.path.join(b, *parts) + ".py"
  ```
  顶层导入按 cur_dir → base_dir → cwd 顺序解析为本地文件，可能把标准库/第三方导入误绑到同目录同名 shadow 文件；`importlib.import_module` 动态导入不可见；`get_transitive_dependents`（hmr.py:109-125）无 ignored 剪枝参数。
- 判定： ADAPT（Node ESM ModuleJob 图在 Python 无等价物，AST 静态分析是偏离清单第 1 条下合理的等价实现；本条仅记录语义边界）
- 影响: 依赖图可能过近似/误近似，进而放大 D4 无条件重载的错误范围。
- 建议修法: 优先用 `sys.modules` 中已加载模块的 `__file__` 关系构建真实图，AST 仅作补充；`get_transitive_dependents` 增加 ignored 集合参数对齐 index.ts:433。

## 测试缺口

### T1: externals → `loader.exit()` 全量重载 — 入口依赖树内文件变更必须触发全量重载（index.ts:220-226, index.ts:260）
### T2: 缓存命中分支 — loadCache 内文件变更 → stash + 防抖合并为一次 partialReload；缓存外文件仅发 `hmr/change`（index.ts:242, index.ts:265-270）
### T3: 重载事务回滚 — 导入失败恢复双缓存并中止（index.ts:497-500）；dispose 失败继续、reload 失败抛出后 rollback + 旧插件重挂（index.ts:516-531, index.ts:532-545）；成功才清 stash（index.ts:548）
### T4: `refreshConfig` 串行化 — 在飞期间多次触发仅记 dirty，循环末尾补跑一次；结束后 running 置空（index.ts:297-324）
### T5: `registerConfig` — 重复注册抛错（index.ts:139）；注册时文件已存在触发一次 refresh（ignoreInitial: false，index.ts:147）；启动失败清理并 rethrow（index.ts:182-186）
### T6: `analyzeChanges` 分类不动点 — accepted 自 stashed 传播、declined 自 externals 传播、全 declined 依赖者归 declined、残余 pending 归 declined（index.ts:345-398）
### T7: teardown 等待全部在飞刷新完成且**不取消**（index.ts:200-205）
### T8: Config 默认值 — `root=['.']`、`ignored` 四默认模式（含 `**/.*` 与文件名 `cache`/`data`）、`debounce=100` 的消费路径（index.ts:560-570, index.ts:215, index.ts:231）
### T9: `root` 为空数组时 ready 立即解决（index.ts:277-279）
### T10: 构造器守卫 — loader.internal 缺失抛 `--expose-internals` 错误（index.ts:120-122）
### T11: `findWatchRoot` — 仅 ENOENT 上溯、非目录显式报错、到达文件系统根抛原始错误（index.ts:69, index.ts:77-79）
### T12: Python 侧 shadow 误绑定 — `cur_dir` 下同名 shadow 文件（如 `json.py`）+ `import json` 的被监听模块，依赖图不得误绑（对应 index.ts:41 的 node:/node_modules 排除语义）

## PROBE 候选

- D9: 构造 `register_module` 的慢 refresh（内含 `await asyncio.sleep(5)`），调用 unregister，探测 2 秒后任务是否被 `cancel()`、fiber 是否半途终止——取消是运行时属性，需真实 asyncio 传播验证；TS 语义应等待完成。
- D10: 在 `_trigger_config_refresh` 任务运行中对其 `task.cancel()`，探测是否误发 `hmr/config-update-failed`（`except BaseException` 分支将 CancelledError 转为普通 Exception 后进入 parallel 事件）。
- D5: 构造带 disposables 的插件类重载，探测 `fiber.restart()`（fiber.py:982）是否完整重跑 dispose→apply 生命周期，以判定其与 TS `registry.plugin` 重挂载（含 `fiber.entry` 迁移，index.ts:505-507）的等价程度。
- D11: 在无事件循环的同步主线程中调用 `register_config` 后修改文件，探测 `refresh_fn` 同步抛错是否被 `_poll_loop` 泛化 except（hmr.py:320-322）吞掉且 `hmr/config-update-failed` 缺失。
- D20: 构造 `cur_dir/json.py` shadow 文件与含 `import json` 的被监听模块，运行 `scan_file` 后检查 `dependencies` 是否误绑 shadow 文件（静态可推断，探针用于固定证据）。
