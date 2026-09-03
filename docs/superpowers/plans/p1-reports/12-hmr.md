# dsh/cordis/hmr.py ↔ reference/vendor/hmr/src/index.ts (516) + reference/vendor/hmr/src/error.ts (33)

## 差异清单

### D1 [MUST-FIX] registerConfig 缺少注册时初始 'add' 触发（present file 必须立即 refresh 一次）
- 位置: py:dsh/cordis/hmr.py:163-178 (poll loop `if last_mtime > 0: skip initial`) vs ts:vendor/hmr/src/index.ts:147 (`ignoreInitial: false`) + ts:156-158 (`watcher.on('add', onChange)`)
- 原版行为:
  ```ts
  const watcher = watch(root, { ...this.config, cwd: undefined, depth, ignored: undefined, ignoreInitial: false })
  ...
  watcher.on('add', onChange)   // 注册时文件已存在 → chokidar 初始扫描立即 'add' → refreshConfig 一次
  ```
  ts:237-239 的注释明确指出："`registerConfig` keeps its own initial scan because a user patch layer present at registration must apply once."（注册时已存在的用户 patch 层必须立即应用一次）
- 移植版现状:
  ```python
  last_mtime = self._mtimes.get(filename, 0.0)
  if mtime > last_mtime:
      self._mtimes[filename] = mtime
      if last_mtime > 0:  # Skip initial check
          self._trigger_config_refresh(filename, refresh_fn)
  ```
  `register_config` 只记录 mtime（py:338-344），首个 poll 周期只建立基线（`last_mtime == 0`），已存在的文件在注册时永远不会触发 refresh。
- 修复方案: `register_config` 在注册时若 `os.path.exists(abs_path)` 则同步（或调度）调用一次 `_trigger_config_refresh`，与 TS `'add'` 初始触发等价；同时为"注册时不存在、之后创建"的文件保留 mtime 基线为 0（不要用 `time.time()` 预填，见 D2），使创建事件也能触发。

### D2 [MUST-FIX] 文件不存在时用 time.time() 预填 mtime，吞掉创建事件
- 位置: py:dsh/cordis/hmr.py:339-342 与 359-363 vs ts:vendor/hmr/src/index.ts:151-158 (`onChange` 覆盖 add/change/unlink 三事件)
- 原版行为:
  ```ts
  watcher.on('add', onChange)
  watcher.on('change', onChange)
  watcher.on('unlink', onChange)
  ```
  `add`/`unlink` 都触发 refresh。
- 移植版现状:
  ```python
  if os.path.exists(abs_path):
      self._mtimes[abs_path] = os.path.getmtime(abs_path)
  else:
      self._mtimes[abs_path] = time.time()
  ```
  之后 poll 只比较 `mtime > last_mtime`。注册后才创建、但 mtime ≤ 注册时刻 `time.time()` 的文件永远不会触发；unlink 事件完全没有建模（poll 对不存在的文件直接 `continue`）。
- 修复方案: 不存在时基线存 `0.0`；poll 中区分三种迁移：`不存在→存在`(add)、`mtime 变化`(change)、`存在→不存在`(unlink)，三者都触发 refresh（TS 三事件同路径）。

### D3 [MUST-FIX] full-vs-partial 语义：externals → 全量重载（loader.exit()）完全缺失
- 位置: py:dsh/cordis/hmr.py:239-332 (`_trigger_module_reload` 只有 per-module 路径) vs ts:vendor/hmr/src/index.ts:220-226 + 259-268
- 原版行为:
  ```ts
  const mainUrl = pathToFileURL(resolve(process.argv[1])).href
  const mainJob = this.internal.loadCache.get(mainUrl)
  if (mainJob) { this.externals = await loadDependencies(mainJob) } else { this.externals = new Set() }
  ...
  // Full reload: the changed file is part of the framework
  if (this.externals.has(url)) return loader.exit()
  ```
- 移植版现状: 无 externals 集合，无 `loader.exit()` 钩子（py Loader 类也没有 `exit()` 方法）；框架文件变更走与用户文件相同的局部重载路径。
- 修复方案: 在 py Loader 上加 `exit()` 空钩子（宿主可覆写为进程重启）；`_trigger_module_reload` 先判定变更文件是否属于宿主入口依赖闭包（如 `dsh/` 包内文件），是则调用 `ctx.get("loader").exit()` 并返回，否则进入局部重载。

### D4 [MUST-FIX] partialReload 事务语义：无 accepted/declined 分类、无旧插件卸载、无回滚、hmr/reload 载荷形状不同
- 位置: py:dsh/cordis/hmr.py:245-326 vs ts:vendor/hmr/src/index.ts:345-398 (analyzeChanges) + 400-549 (partialReload)
- 原版行为:
  ```ts
  this.ctx.registry.delete(plugin)          // 先卸载旧实例
  ...
  reload(attempts[filename], runtime)       // 用新 module 重新 registry.plugin，并回接 fiber.entry
  ...
  this.ctx.emit('hmr/reload', reloads)      // Map<Plugin, Reload{filename, runtime}>
  this.stashed = new Set()
  ```
  且导入失败时 `handleError(...); return rollback()`（恢复缓存），重挂失败时整体 rollback（恢复缓存 + 重新注册旧 plugin）。
- 移植版现状:
  ```python
  new_inst = new_cls(config=fiber.config)
  ...
  fiber.plugin = new_inst
  await fiber.restart()
  ...
  reloads[old_key] = {"filename": file_path, "runtime": runtime}
  if reloads and hasattr(self.ctx, "emit"):
      self.ctx.emit("hmr/reload", reloads)
  ```
  直接在运行中的 fiber 上换 plugin 类并 restart；异常只记 warn + `hmr/config-update-failed`，从不 `registry.delete` 旧实例、无缓存备份/回滚、stash 永不清理；`hmr/reload` 载荷是 `Dict[str, Dict]`（key 为 entry id）而非 TS 的 `Map<Plugin, Reload>`。
- 修复方案: 重载事务改为：对每个受影响 entry 先 `ctx.registry.delete(旧实例)` → 用重载后的类 `registry.plugin(新实例, config, get_outer_stack)` 回接 `fiber.entry`；失败路径恢复旧实例注册（rollback）；`hmr/reload` 载荷改为 `{旧插件实例: {"filename": ..., "runtime": ...}}` 映射；成功后清空 stash 集合。

### D5 [MUST-FIX] 观察范围：TS watch config.root（ignored 排除规则）覆盖整个树，py 只看显式注册文件
- 位置: py:dsh/cordis/hmr.py:142-159 (config 只读 debounce) vs ts:vendor/hmr/src/index.ts:552-574 (Config: `root: ['.']`, `ignored: ['**/node_modules','**/.*','cache','data']`, `base`) + ts:228-240 (主 watcher)
- 原版行为:
  ```ts
  export const Config: z<Config> = z.object({
    base: z.string(),
    root: z.array(String).role('table').default(['.']),
    ignored: z.array(String).role('table').default(['**/node_modules', '**/.*', 'cache', 'data']),
    debounce: z.natural().role('ms').default(100),
  })
  this.watcher = watch(root, { cwd: watchBaseDir, ignored: path => match(relative(watchBaseDir, path)), ignoreInitial: true })
  ```
- 移植版现状: `self.config.get("debounce", 100)` 是唯一被消费的配置；`root`/`ignored`/`base` 无对应实现，未注册的模块文件变更不可观察。
- 修复方案: 至少接受并记录 `root`/`ignored`/`base` 配置字段；轮询实现下可将 `root` 下未被 ignored 的 `.py` 文件纳入扫描（或显式说明 py 版只支持注册式监视并在文档标注），并让 `include.refresh()` 路由复用 TS 的 Include 匹配逻辑（`entry.subtree.filename == filename`）。

### D6 [MUST-FIX] 'hmr/change' 事件发射面不一致（config refresh 也发射；TS 只对非模块文件发射）
- 位置: py:dsh/cordis/hmr.py:210-211, 250-252 vs ts:vendor/hmr/src/index.ts:248-270
- 原版行为:
  ```ts
  // config reload 路径: this.refreshConfig(include, include.filename, () => include.refresh())  // 不 emit hmr/change
  ...
  if (loader.internal!.loadCache.has(url)) { this.stashed.add(url); return partialReload() }  // 不 emit
  this.ctx.emit('hmr/change', url)   // 仅未跟踪文件
  ```
- 移植版现状:
  ```python
  if hasattr(self.ctx, "emit"):
      self.ctx.emit("hmr/change", filename)   # 每次 config refresh 前都 emit
  res = refresh_fn()
  ```
  config refresh 与模块重载都会先 emit `hmr/change`，事件订阅方会观察到 TS 版不会产生的事件。
- 修复方案: `_trigger_config_refresh` 内移除 `emit("hmr/change")`；`hmr/change` 仅对"已观察但既非 include 配置、也非已加载模块"的文件发射（TS onChange 尾部分支）。

### D7 [MUST-FIX] registerConfig 错误面：重复注册与非活跃状态应 fail loud
- 位置: py:dsh/cordis/hmr.py:334-353 vs ts:vendor/hmr/src/index.ts:134-139
- 原版行为:
  ```ts
  if (!this.watcher) throw new Error('HMR is not active')
  ...
  if (this.configs.has(watchFilename)) throw new Error(`config path already registered: ${filename}`)
  ```
- 移植版现状: `self._configs[abs_path] = refresh_fn` 静默覆盖同路径注册，无重复检测，无 inactive 状态检查。
- 修复方案: `register_config` 开头加 `if abs_path in self._configs: raise ValueError(f"config path already registered: {filename}")`；`teardown()` 后置 `self._running = False` 并在注册入口检查抛错。

### D8 [ADAPT] chokidar 文件监视 → mtime 轮询
- 位置: py:dsh/cordis/hmr.py:161-198 (`_poll_loop`) vs ts:vendor/hmr/src/index.ts:142-148, 228-240
- 原版行为: chokidar `watch(root, {...})` 事件驱动，`this.ctx.debounce(() => this.partialReload(), this.config.debounce)` 合并变更爆发。
- 移植版现状: `await asyncio.sleep(max(0.1, self.debounce_ms / 1000.0))` 周期轮询；`_trigger_*` 用 `dirty` 标志串行化（与 TS refreshConfig 的 do/while dirty 循环语义一致）。
- 评估: 轮询是 Win7/零依赖下的合法 ADAPT；dirty-flag 串行化与 TS 一致。但 debounce 目前同时充当轮询周期——爆发合并窗口与 TS 的"变更后静默 debounce_ms 再执行一次"不同（D5/T3 关联）。修复方向：poll 固定短周期（如 100ms），检测到变更后按 `debounce_ms` 定时合并再执行。

### D9 [ADAPT] 依赖图：TS 用运行时 ModuleJob.linked，py 用 AST 静态导入扫描
- 位置: py:dsh/cordis/hmr.py:22-124 (`ModuleDependencyGraph`) vs ts:vendor/hmr/src/index.ts:37-48 (`loadDependencies`)
- 原版行为:
  ```ts
  async function loadDependencies(job: ModuleJob, ignored = new Set<string>()) {
    ... if (job.url.startsWith('node:') || job.url.includes('/node_modules/')) return ...
    const children = await job.linked
  ```
- 移植版现状: `ast.parse` 提取 `ast.Import`/`ast.ImportFrom` 并解析为文件路径集合，维护正向/反向图。
- 评估: 表面语义（"改动文件 → 受影响的本地文件闭包"）等价，动态 import 在两边都不在静态图内（TS 的 linked 是实际执行过的 import 边，py 缺失执行期边，属于 ADAPT 偏差，建议在报告中保留为已知限制）。`node:`/`node_modules` 排除对应 py 天然不存在。

### D10 [ADAPT] 服务初始化与签名差异
- 位置: py:dsh/cordis/hmr.py:133-159 vs ts:vendor/hmr/src/index.ts:118-125, 199-295
- 原版行为: `constructor` 断言 `this.ctx.loader.internal` 存在，否则 `throw new Error('--expose-internals is required for HMR service')`；`[Service.init]` 异步生成器 yield teardown（关闭 watcher、等待 refreshTasks）。
- 移植版现状: `__init__` 直接在构造时启动 poll task；`teardown()` 取消任务、清空注册表；无 loader.internal 等价物。
- 评估: Node 内部 ESM loader 无 Python 对应物，属平台差异 ADAPT；但 teardown 未等待在途 refresh task 完成（TS `await Promise.allSettled([...this.refreshTasks])`）——见 D11。

### D11 [MUST-FIX] disposer/teardown 不等待在途 refresh
- 位置: py:dsh/cordis/hmr.py:346-353, 368-375, 377-383 vs ts:vendor/hmr/src/index.ts:177-181, 199-205
- 原版行为:
  ```ts
  return this.ctx.effect(() => async () => {
    if (this.configs.get(watchFilename) === registration) this.configs.delete(watchFilename)
    await watcher.close()
    await this.configRefreshes.get(registration)?.running
  }, 'hmr.registerConfig()')
  ```
- 移植版现状:
  ```python
  def unregister() -> None:
      self._configs.pop(abs_path, None)
      self._mtimes.pop(abs_path, None)
      self._refreshes.pop(abs_path, None)
  ```
  同步丢弃状态，在途 `_run` 任务继续跑；`teardown()` 只 cancel poll task。
- 修复方案: `unregister`/`teardown` 记录并 `await`（或至少保留引用待结束）`state.running` 任务后再清理，保证与 TS 相同的"卸载后不再有 refresh 完成"语义。

### D12 [SKIP] error.ts handleError（esbuild BuildFailure + code frame）
- 位置: ts:vendor/hmr/src/error.ts:11-35
- 原版行为: 识别 esbuild `BuildFailure`（`errors[].location`）并用 `@babel/code-frame` 打印带位置的错误帧。
- 评估: Python 端没有 esbuild 转译管线，构建失败形态不存在；异常直接经 logger 输出已覆盖同等诊断面。平台不适用，跳过。

## 测试缺口

### T1 test_hmr_register_config_applies_present_file_once
注册时文件已存在 → refresh 恰好执行一次（对应 D1）；再修改一次 → 恰好再执行一次（无重复基线触发）。

### T2 test_hmr_config_file_creation_and_unlink_trigger
注册时文件不存在 → 创建文件触发 refresh；删除文件触发 refresh（对应 D2 的 add/unlink）。

### T3 test_hmr_module_reload_unmounts_old_and_emits_reload_map
`register_module` + 修改模块文件 → 旧实例先被 dispose（`hmr/reload` 之前）、fiber 挂新实例、`hmr/reload` 载荷可按 `filename`+`runtime` 检查（对应 D4）。

### T4 test_hmr_module_reload_failure_rolls_back_to_previous_plugin
新模块文件语法错误 → 旧 fiber 仍在运行、收到 `hmr/config-update-failed`、无半挂载状态（对应 D4 rollback）。

### T5 test_hmr_register_config_duplicate_raises
同一文件注册两次 → 第二次抛错（对应 D7）。

### T6 test_hmr_unregister_waits_for_inflight_refresh
refresh 执行中注销 → disposer 返回后不再观察到该文件的新 refresh 完成回调（对应 D11）。

### T7 test_hmr_debounce_coalesces_burst_into_single_reload
debounce 窗口内连续多次写文件 → 恰好一次 refresh（对应 D8 的爆发合并语义）。

### T8 test_hmr_change_event_not_emitted_for_config_refresh
config 文件变更路径不产生 `hmr/change` 事件；未跟踪模块文件变更才产生（对应 D6）。

### T9 test_hmr_exit_hook_called_for_externals
宿主注册 `exit()` 钩子后，框架（externals）文件变更触发 `exit()` 而非局部重载（对应 D3）。
