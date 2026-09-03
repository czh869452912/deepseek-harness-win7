# dsh/cordis/include.py ↔ reference/vendor/include/src/index.ts (336)

## 差异清单

### D1 [MUST-FIX] internal/update 处理器：异步后台应用 + 继续传递 next()，而 TS 在瀑布内同步 await 且短路
- 位置: py:dsh/cordis/include.py:83-102 (`_on_update`) vs ts:vendor/include/src/index.ts:206-213
- 原版行为:
  ```ts
  ctx.on('internal/update', async (config, _, next) => {
    if (config.path !== this.config.path) return next()
    await this.enqueue(async () => {
      const data = this.applyPatches(this.data!, config.patches)
      await this.root.update(data)
      this.config = config
    })
  })
  ```
  匹配分支内 **不调用 `next()`**：应用完成后短路瀑布（后面还有 loader 的 'reload' 日志监听器等）。
- 移植版现状:
  ```python
  loop.create_task(_do_update())
  ...
  return next_fn() if next_fn and callable(next_fn) else None
  ```
  应用被丢进后台任务（不等待、不参与瀑布顺序），并且**继续调用 `next_fn()`** 把更新传给后续监听器——后者会看到尚未提交的树，且双写风险（两条路径都在推进同一 config）。
- 修复方案: `_on_update` 改为 async；`_do_update` 的 `root.update` 在返回前 `await` 完成；匹配分支返回时不调用 `next_fn()`（短路），与 TS 一致。

### D2 [MUST-FIX] readonly 检测与写保护完全缺失
- 位置: py:dsh/cordis/include.py:72-73, 199-261 vs ts:vendor/include/src/index.ts:203, 231-238, 323-326
- 原版行为:
  ```ts
  private async checkAccess() {
    if (!this.type) return
    try { await access(this.filename, constants.W_OK) } catch { this.readonly = true }
  }
  ...
  private async _writeFile(config: EntryOptions[]) {
    if (this.readonly) { throw new Error(`cannot overwrite readonly config`) }
  ```
  `_apply` 每次应用后调用 `checkAccess()`；`initial` 写入路径同样经 `_writeFile` 受 readonly 保护。
- 移植版现状: `self.readonly = False` 后从未更新；`_write_file_sync/_write_file_async` 不检查 readonly，对只读文件直接失败（Win7 上是 PermissionError 重试 10 次后才抛）。
- 修复方案: 应用后（`refresh`/`init`）调用 `checkAccess()`（`os.access(self.filename, os.W_OK)` 失败则 `readonly=True`）；两个写函数开头 `if self.readonly: raise PermissionError("cannot overwrite readonly config")`。

### D3 [MUST-FIX] 写回丢失 `!!js` 方言（__jsExpr 字典被写成映射而非 `!!js` 标量）
- 位置: py:dsh/cordis/include.py:199-245 (`_write_file_*` 用 `yaml.safe_dump`) vs ts:vendor/include/src/index.ts:9-23, 327-328
- 原版行为:
  ```ts
  const JsExpr = new yaml.Type('tag:yaml.org,2002:js', { ... represent: (data) => data['__jsExpr'] })
  export const entryListSchema = yaml.JSON_SCHEMA.extend(JsExpr)
  ...
  this.content = yaml.dump(config, { schema })
  ```
  `!!js expr` 写回时保持 `!!js expr` 标量形式，可被重新加载并再次求值。
- 移植版现状: `yaml.safe_dump(sorted_data, sort_keys=False, allow_unicode=True)` 把 `{"__jsExpr": "expr"}` 写成普通映射，重载后 `is_js_expr` 虽仍能识别，但文件方言偏离（人写 `!!js` 的文件一次写回后变成 `__jsExpr:` 映射，且 safe_dump 对未标注 tag 的数据走默认样式，`dsh --dump-config` 与 include 写出的形态不一致）。
- 修复方案: 注册 PyYAML 专属 Dumper representer：为形如 `{'__jsExpr': str}` 的字典或专用包装类注册 representer（`yaml.Dumper.add_representer` 或 `yaml.SafeDumper.add_representer`），将其序列化为带有 `tag:yaml.org,2002:js` 标签（或标准 `!js` 标量）的 YAML 节点，确保写回文件时维持 `!!js <expr>` 语法规范，支持无损循环重载。

### D4 [MUST-FIX] 写回排序：include 写路径做了 sort_keys，TS 不排序
- 位置: py:dsh/cordis/include.py:201, 225 (`[sort_keys(dict(opt)) for opt in config_data]`) vs ts:vendor/include/src/index.ts:323-331
- 原版行为:
  ```ts
  private async _writeFile(config: EntryOptions[]) {
    if (this.readonly) { throw ... }
    if (this.type === 'application/yaml') { this.content = yaml.dump(config, { schema }) }
    else if (this.type === 'application/json') { this.content = JSON.stringify(config, null, 2) }
  ```
  原样写回（键序保持树内现状），sortKeys 只在 Entry.update 提交 candidate 时发生。
- 移植版现状: include 的每次写回都强制 `id,name` 前置、`config` 末尾、中间字典序排序，用户文件中的键序在每次热更新后被重排。
- 修复方案: `_write_file_sync` 与 `_write_file_async` 彻底移除 `sort_keys` 调用，直接按树内数据字典序序列化 `config_data`，严格保持与 TS 一致的"写回数据所见即树内数据"契约，避免每次写回无端重排用户文件中的原有键顺序。

### D5 [MUST-FIX] init 的错误阶段（stage）分类被压扁成 'read'
- 位置: py:dsh/cordis/include.py:137-165 (`init`) vs ts:vendor/include/src/index.ts:273-289
- 原版行为:
  ```ts
  candidate = (await this.read(true))!      // read 内部抛 ConfigFileError('read'|'parse'|'validate')
  } catch (error) {
    if (!(error instanceof ConfigFileError) || error.stage !== 'read' || (error.cause as ...)?.code !== 'ENOENT') throw error
  ```
  只有 stage==='read' 且 cause 是 ENOENT 才走 initial 写入；parse/validate 错误原样上抛。
- 移植版现状:
  ```python
  except Exception as e:
      if not isinstance(e, ConfigFileError):
          raise ConfigFileError("read", self.filename, e)
      raise e
  ```
  init 内联的读/解析把 parse、validate 错误都包成 `ConfigFileError('read', ...)`（ENOENT 之外的读取错误也被重包），阶段语义与 TS 的 'read'/'parse'/'validate' 三分类不符。
- 修复方案: `init` 改为直接调用 `self.read(forced=True)`（保持内部三段分类），捕获 `ConfigFileError` 且 `stage == 'read'` 且 cause 为 `FileNotFoundError` 时才走 initial 分支，其余原样上抛；删除内联读写代码。

### D6 [MUST-FIX] flushWrite 无 writeQueue 串行链：并发 flush 可重排/交错（Windows 原子替换前后的窗口）
- 位置: py:dsh/cordis/include.py:253-275 (`write_file`/`flush_write`) vs ts:vendor/include/src/index.ts:344-368
- 原版行为:
  ```ts
  const run = this.writeQueue.then(() => this._writeFile(config), () => this._writeFile(config))
  this.writeQueue = run
  void run.catch((error) => { this.ctx.root.logger?.('loader').warn('failed to write config file %C', this.filename) ... })
  ```
  所有 flush 串行排在 `writeQueue` 链上，且上一个失败不阻塞下一个（`.then(_, _)` 双臂）。
- 移植版现状: `loop.call_soon(lambda: asyncio.create_task(self.flush_write()))` 每个 write 各起一个任务，仅靠 `_write_lock` 互斥；`flush_write` 中 `self.pending_write = None` 在拿锁**之前**执行——若写失败，数据已丢（TS 失败只记日志但 `config` 是调用时刻的参数副本，pending 语义一致，但 py 在等待锁期间有第二个 write 进来时可能被第一个 flush 拿走旧值，顺序与 TS 的"每次 flush 绑定自己那份 config"不同）。
- 修复方案: `flush_write` 在进入 `_write_lock` 前先捕获 `config_data`（当前已如此），但要把"取走 pending"与"写入"的配对改为链式：`self._write_chain = self._write_chain.then(...)` 风格（asyncio 下可用一个串行 consumer task + 队列），并保证失败日志 message 为 `failed to write config file {filename}`（当前已近同）。

### D7 [ADAPT] 读写 I/O 同步/异步混合与 Win7 重试
- 位置: py:dsh/cordis/include.py:35-36, 211-221 vs ts:vendor/include/src/index.ts:35-41, 333-341
- 原版行为:
  ```ts
  function retryableWriteError(error: unknown): boolean {
    const code = (error as NodeJS.ErrnoException | null)?.code
    return code === 'EACCES' || code === 'EBUSY' || code === 'EPERM'
  }
  ...
  if (!retryableWriteError(error) || retry >= WRITE_RETRY_LIMIT) throw error
  await delay((retry + 1) * WRITE_RETRY_DELAY_MS)
  ```
- 移植版现状: `WRITE_RETRY_LIMIT = 10`、`WRITE_RETRY_DELAY_SEC = 0.05`、退避 `(retry + 1) * 0.05s` 与 TS 一致；但 py 对**所有** `OSError/PermissionError` 重试（含 ENOENT 等不可重试错误），且 `os.path.exists` 分支用 `os.replace`/`os.rename` 处理 Windows 目标已存在。
- 评估: `os.replace` 是合法 Win7 ADAPT；重试条件应改为按 `getattr(e, 'errno', None)` 判定 EACCES/EBUSY/EPERM（Windows 上对应 winerror 5/32 等），避免对不可恢复错误空转 0.5s+。归类 ADAPT，附上述收敛建议。

### D8 [ADAPT] applyQueue → asyncio.Lock 串行化
- 位置: py:dsh/cordis/include.py:78, 87-99, 188-197 vs ts:vendor/include/src/index.ts:225-229 (`enqueue`)
- 原版行为: `enqueue` 把每个树变更任务串到 `applyQueue` promise 链上，前驱失败不影响后续（`.then(task, task)`）。
- 移植版现状: `refresh` 与 `_on_update` 均经 `self._apply_lock`（asyncio.Lock）串行化。
- 评估: 互斥语义等价（ADAPT）。注意 D1 修复后 `_on_update` 也必须在锁内且等待完成。

### D9 [ADAPT] internal/update 的 no-op 检测：TS 匹配分支无条件应用（read 已在 refresh 做 changed-check），py 直接应用 patches
- 位置: py:dsh/cordis/include.py:84-93 vs ts:vendor/include/src/index.ts:206-213
- 原版行为: 匹配 `config.path === this.config.path` 后直接 `applyPatches(this.data!, config.patches)`（`this.data` 非空断言——TS 中 internal/update 只发生在 init 完成后）。
- 移植版现状: `if self.data is not None:` 守卫，None 时静默跳过（初始化前的 update 丢失）。
- 评估: 行为差异仅在"init 未完成前收到 update"的竞态窗口；py 的静默跳过会丢更新，建议改为暂存待 init 后应用，或至少 warn。归 ADAPT 附建议。

### D10 [ADAPT] path 解析与 baseUrl 设置
- 位置: py:dsh/cordis/include.py:63-76 vs ts:vendor/include/src/index.ts:197-204
- 原版行为:
  ```ts
  this.filename = fileURLToPath(new URL(this.config.path, this.ctx.baseUrl))
  ...
  this.ctx.baseUrl = new URL('.', pathToFileURL(this.filename)).href
  ```
- 移植版现状: `os.path.abspath(os.path.join(base_dir, raw_path))`，`self.ctx.base_url = os.path.dirname(self.filename)`。
- 评估: 语义等价（相对 `ctx.base_url` 解析、挂载后把 baseUrl 指向配置目录）；仅 file:// URL 与原生路径的形式差异，ADAPT。

### D11 [MUST-FIX] enableLogs 回退链使用属性名不一致导致父树回退失效
- 位置: py:dsh/cordis/include.py:62 vs ts:vendor/include/src/index.ts:196
- 原版行为:
  ```ts
  this.enableLogs = config.enableLogs ?? ctx.fiber.entry?.parent.tree.enableLogs ?? false
  ```
- 移植版现状:
  ```python
  self.enable_logs = self.config.get("enableLogs", getattr(parent_tree, "enable_logs", False))
  ```
  表面一致，但 py `EntryTree.__init__` 把 `self.enable_logs` 默认置 **True**（py:dsh/cordis/loader.py:528），TS `EntryTree.enableLogs` 默认 **undefined**（ts:vendor/loader/src/config/tree.ts:11），且 TS `showLog` 是 `!entry.parent.tree.enableLogs → return`（默认关日志）。叠加结果：py 的 include 日志默认开、父树回退取到的也是 True；TS 默认关。见 loader 报告 D-log 同源问题；include 侧修复 = EntryTree 默认 `enable_logs = None`，回退链保持 `?? false`。

## 测试缺口

### T1 test_include_init_missing_file_with_initial_writes_and_applies
无文件 + `initial` 列表 → 写文件、应用 patches、root 挂载（py init 已有实现但无测试）；无 initial → 抛 `config file not found: <path>`（ts:283 文案）。

### T2 test_include_internal_update_short_circuits_and_awaits_apply
`internal/update` 匹配 path → update 返回后 root 树已包含新 patches，且后续（如 loader 的 reload 日志监听）不被调用（对应 D1）。

### T3 test_include_write_back_preserves_js_tag
含 `!!js` 表达式的条目经 write/flush 后读回仍是 `!!js` 标量形式（对应 D3）。

### T4 test_include_write_back_does_not_reorder_keys
写回文件保持条目键序，无 id/name/config 重排（对应 D4）。

### T5 test_include_readonly_write_raises
对只读文件（chmod 或目录只读）应用后 `write()` 抛 `cannot overwrite readonly config`（对应 D2）。

### T6 test_include_refresh_stages_parse_and_validate_errors
坏 YAML → `ConfigFileError('parse')`；顶层非数组 → `ConfigFileError('validate')`；stage 字段可断言（对应 D5）。

### T7 test_include_concurrent_write_and_refresh_serialize
并发 `write()` + `refresh()` → 两次操作串行完成，最终文件内容与最后一次 write 一致（对应 D6/D8）。

### T8 test_include_initial_update_before_init_is_not_lost
init 完成前收到 `internal/update`（不同 path → next 透传；相同 path → 更新不丢）（对应 D9）。
