# dsh/cordis/loader.py ↔ reference/vendor/loader/src/index.ts (166) + internal.ts (115) + config/entry.ts (270) + config/group.ts (116) + config/isolate.ts (149) + config/tree.ts (151) + config/utils.ts (28) + reference/vendor/group/src/index.ts (2)

## 差异清单

### D1 [MUST-FIX] Entry.disabled 语义三重偏离：无 group 豁免、无祖先链传播、纯字符串被当表达式求值
- 位置: py:dsh/cordis/loader.py:826-829 (`Entry.disabled`)、362-379 (`eval_condition`) vs ts:vendor/loader/src/config/entry.ts:83-108
- 原版行为:
  ```ts
  get disabled() { return this._disabled(this.options) }
  private _disabled(options: EntryOptions) {
    if (options.group) return false            // group 永远启用
    if (this.disabledOf(options)) return true
    let entry = this.parent.ctx.fiber.entry    // 沿父 entry 链检查
    while (entry) { if (this.disabledOf(entry.options)) return true; entry = entry.parent.ctx.fiber.entry }
    return false
  }
  private disabledOf(options: EntryOptions): boolean {
    return isJsExpr(options.disabled)
      ? Boolean(this.evaluate(options.disabled.__jsExpr))   // 只有 !!js 节点才求值
      : Boolean(options.disabled)                            // 其余为布尔强转
  }
  ```
- 移植版现状:
  ```python
  @property
  def disabled(self) -> bool:
      dis = self.options.get("disabled", False)
      return eval_condition(dis, self.ctx)
  ```
  `eval_condition` 对**任何**非空值调用 `evaluate_expr`（py:362-379）：`disabled: "false"`（字符串）在 TS 是 `Boolean("false") === true`（禁用），在 py 求值为 `False`（启用）；`disabled: "0"`、`disabled: "off"` 等同理反转。group 豁免与祖先链缺失——`EntryGroup.update`/`load_from_dict` 以外没有任何层实现级联（tests/test_cordis_config_reload_1to1.py:43 的祖先级联是在组插件层实现的，Entry 层仍不满足 TS 语义）。
- 修复方案: `Entry.disabled` 改为：`options["group"]` 为真 → False；`is_js_expr(dis)` → `bool(evaluate_expr(self.ctx, dis["__jsExpr"]))`；否则 `bool(dis)`（不做字符串求值）；再沿 `entry.parent.ctx.fiber.entry` 链向上逐层检查。`eval_condition` 仅保留给 `load_from_dict` 的兼容入口或同步收紧。

### D2 [MUST-FIX] 嵌套 entry id 缺少父前缀（`parentEntryId:childId`）
- 位置: py:dsh/cordis/loader.py:787-813 (`Entry.__init__` 静态 id) vs ts:vendor/loader/src/config/entry.ts:75-81
- 原版行为:
  ```ts
  get id() {
    let id = this.options.id
    if (this.parent.tree.ctx.fiber.entry) {
      id = this.parent.tree.ctx.fiber.entry.id + EntryTree.sep + id
    }
    return id
  }
  ```
  子树内条目的对外 id 是 `父entryid:自身id`，`EntryTree.resolve` 据此逐段解析。
- 移植版现状:
  ```python
  self.id = entry_id or name or hex(random.randint(0x10000000, 0xFFFFFFFF))[2:]
  ```
  id 恒等于 options.id，嵌套前缀从不生成；`EntryTree.resolve`（py:571-585）虽按 `:` 分段，但 `self.store` 中嵌套子树条目以裸 id 存储，跨树前缀解析永远走不通，错误信息与 `get_outer_stack`（py:835-844 用 `entry.id`）也输出非 TS 形态。
- 修复方案: `Entry.id` 改为 property：`parent.tree.ctx.fiber.entry` 存在时返回 `父.id + ":" + options.id`；所有 `entry.id` 消费点（`get_outer_stack`、`_on_patch_context` 的 `f"{name}#{entry.id}"`、日志）随之对齐。

### D3 [MUST-FIX] Entry.update 缺失事务路径：可空键删除、diff 判定、name/inject/group 替换重导入、rollback 与 updateError 包装
- 位置: py:dsh/cordis/loader.py:865-885 (`Entry.update`) vs ts:vendor/loader/src/config/entry.ts:141-246
- 原版行为:
  ```ts
  const replace = diff.some(key => key === 'name' || key === 'inject' || key === 'group')
  ...
  plugin = diff.includes('name')
    ? this.loader.unwrapExports(await this.parent.tree.import(candidate.name, this.getOuterStack))
    : previous.runtime!.callback
  ...
  } catch (error) {                                  // start 失败
    this.options = previousOptions
    try { await this._start(previousPlugin) } catch (rollbackError) {
      throw updateError('rollback', legacy, new AggregateError([error, rollbackError]))
    }
    this.context.emit('loader/partial-dispose', this, candidate, true)
    throw updateError('apply', candidate, error)
  }
  ```
  还有：`isNullable(value)` 删除 candidate 键（ts:146-154）、`sortKeys(candidate)`、`deepEqual` diff、`if (!diff.length && !force) return`、disabled 提交路径 `_dispose` 失败 → `updateError('dispose', ...)`。
- 移植版现状:
  ```python
  prev = dict(self.options)
  self.options.update(options)
  ...
  else:
      if "config" in options and self.fiber:
          self.fiber.update(self.config, no_save=True)
          if self.fiber.error is not None:
              raise self.fiber.error
  ```
  仅三条路径（禁用→dispose；无 fiber→init；否则只在 config 变化时 fiber.update）；name/inject/group 变化不会重导入插件；无 updateError 包装（`failed to {stage} loader entry {id} ({name}): {detail}`）；无 `loader/partial-dispose` 发射；可空值不删除旧键（patch 层传 `null` 无法撤销字段）。
- 修复方案: `Entry.update` 移植 TS 四段结构：(1) candidate 构造（nullable 删除 + sortKeys）；(2) `diff`（deepEqual 语义）+ force 短路；(3) 分支：无 fiber→init、disabled→dispose、非 replace→fiber.update(config)；(4) replace→import 新插件→dispose 旧→start 新→失败回滚旧插件并 `updateError` 包装；每条成功路径 emit `loader/partial-dispose`（见 D6）。

### D4 [MUST-FIX] Entry._dispose 发射后不管：`_disposing` 窗口与 dispose 完成时序错位
- 位置: py:dsh/cordis/loader.py:846-863 vs ts:vendor/loader/src/config/entry.ts:130-139
- 原版行为:
  ```ts
  async _dispose(fiber = this.fiber) {
    if (!fiber) return
    if (this.fiber === fiber) this.fiber = undefined
    this._disposing += 1
    try { await fiber.dispose() } finally { this._disposing -= 1 }
  }
  ```
- 移植版现状:
  ```python
  self._disposing += 1
  try:
      try:
          loop = asyncio.get_running_loop()
          loop.create_task(fiber.dispose())
      except RuntimeError:
          asyncio.run(fiber.dispose())
  finally:
      self._disposing -= 1
  ```
  有事件循环时 `create_task` 后立即递减 `_disposing`——`internal/plugin` 的 case 6（`if getattr(entry, "_disposing", False): return`）在真正的 dispose 进行期间已失效；且 update 链不等 dispose 完成就继续（TS await 顺序保证旧 fiber 完全停止后才启动新的）。
- 修复方案: 把 `_dispose` 改为 async 并在所有调用点 await（`Entry.update`、`EntryGroup.remove`、`EntryGroup.stop`）；事件循环内 `await fiber.dispose()`，无循环时保留 `asyncio.run` 回退。

### D5 [MUST-FIX] EntryGroup.update：串行挂载 vs 并发 allSettled、失败聚合、teardown 竞态守卫、回滚错误聚合
- 位置: py:dsh/cordis/loader.py:719-753 vs ts:vendor/loader/src/config/group.ts:59-106
- 原版行为:
  ```ts
  const outcomes = await Promise.allSettled(config.map(options => this.create(options)))
  if (this.ctx.fiber.uid === null) return                 // 树已卸载：不再回滚
  const failures = outcomes.filter(o => o.status === 'rejected').map(o => o.reason)
  if (failures.length === 1) throw failures[0]
  if (failures.length > 1) throw new AggregateError(failures, 'loader entries failed to apply')
  ...
  if (rollbackErrors.length) throw new AggregateError([error, ...rollbackErrors], 'loader entry rollback failed')
  ```
- 移植版现状:
  ```python
  for opt in config_list:
      self.create(opt)
  ...
  except Exception as e:
      for eid in reversed(list(new_map.keys())):
          ...
          try: self.remove(eid, is_dispose=True)
          except Exception: pass          # 回滚失败被静默吞掉
      self.data = old_config
      raise e
  ```
  差异：(a) 顺序 `create` 而非并发——服务可用性驱动的激活顺序不同（TS 注释明确挂载是并发的，inject-pending 才是顺序机制）；(b) 第一个异常立即中断剩余挂载并回滚，TS 允许全部尝试后聚合；(c) 无 `ctx.fiber.uid === null` 卸载竞态守卫（teardown 期间会误回滚）；(d) 回滚失败静默（TS 聚合为 `AggregateError`）。
- 修复方案: `update` 改为并发调度所有 `create`（asyncio.gather + return_exceptions，或逐个 await 保持顺序但聚合失败），按 TS 逻辑聚合/守卫/回滚；回滚错误收集后以 `RuntimeError("loader entry rollback failed: ...")` 附加原错误抛出。

### D6 [MUST-FIX] `loader/partial-dispose` 事件从未发射 → isolate 全局 realm GC 永不执行
- 位置: py:dsh/cordis/loader.py:710-717 (`EntryGroup.remove`)、1064-1082 (`_on_partial_dispose` 只注册不触发) vs ts:vendor/loader/src/config/group.ts:56 + ts:vendor/loader/src/config/isolate.ts:155-172
- 原版行为:
  ```ts
  async remove(id: string, isDispose = false) {
    ...
    delete this.tree.store[id]
    this.context.emit('loader/partial-dispose', entry, entry.options, false)
  }
  ```
  加上 entry.update 各成功路径的 `emit('loader/partial-dispose', this, legacy, true)`（ts:entry.ts:190, 210, 245）。
- 移植版现状: `EntryGroup.remove` 只做 `_dispose + unlink + store.pop`，从不 emit；`_on_partial_dispose` 处理器（GlobalRealm 垃圾回收）成为死代码。
- 修复方案: `EntryGroup.remove` 末尾 emit `('loader/partial-dispose', entry, entry.options, is_dispose)`（对齐 TS 的 active=false 语义：`remove(id, false)` 走 unlink 分支时 TS 仍 emit false——核对：TS 在 `if (!isDispose) unlink` 之后 emit，参数恒为 `false`？不——TS remove 恒 emit `false`；entry.update 内部 emit `true`。py 按此对齐即可）；`Entry.update` 的三条成功路径（D3）补 `emit(..., legacy, true)`。

### D7 [MUST-FIX] interpolate 对普通字符串做 `${...}` 模板展开——TS 中普通字符串保持字面量
- 位置: py:dsh/cordis/loader.py:327-359 (`interpolate`) vs ts:vendor/loader/src/config/utils.ts:12-22
- 原版行为:
  ```ts
  export function interpolate(ctx: object, value: any) {
    if (isJsExpr(value)) { return evaluate(ctx, value.__jsExpr) }
    else if (!value || typeof value !== 'object') { return value }   // 字符串原样返回
  ```
- 移植版现状:
  ```python
  elif isinstance(config, str):
      if config.startswith("!!js "):
          return evaluate_expr(ctx, config[5:])
      if "${" in config:
          ... # ${VAR}、${VAR:-default}、${process.env.X} 展开
      return config
  ```
  含 `${FOO}` 的配置值（如提示词模板、命令串 `run: "${HOME}/x"`）在 TS 挂载时保持字面量，在 py 被替换成环境变量值/空串——对模型可见的配置面产生可见差异；`!!js ` 前缀字符串求值同样是 TS 不存在的扩展（TS 只认 `__jsExpr` 节点）。
- 修复方案: `interpolate` 移除字符串分支的全部处理（仅保留 `is_js_expr` → `evaluate_expr` 与递归）；`${}`/前缀字符串支持如确属 Win7 移植需要，必须收窄为仅在 `internal/config` 边界外的显式调用点（如 preset 加载）并记录于差异文档，不得影响 include/loader 挂载路径。

### D8 [MUST-FIX] is_js_expr 检查过严 + dict 键不参与插值的边界差异
- 位置: py:dsh/cordis/loader.py:98-100, 357-358 vs ts:vendor/loader/src/config/utils.ts:20, 25-27
- 原版行为:
  ```ts
  export function isJsExpr(value: any): value is JsExpr {
    return value instanceof Object && '__jsExpr' in value
  }
  ... return valueMap(value, item => interpolate(ctx, item))
  ```
- 移植版现状:
  ```python
  return isinstance(value, dict) and "__jsExpr" in value and isinstance(value["__jsExpr"], str)
  ...
  return {k: interpolate(ctx, v) for k, v in config.items()}
  ```
  两个偏差：(a) `__jsExpr` 值非字符串时 TS 仍走 `evaluate`（`with(ctx) eval(非字符串)` 会抛错暴露问题），py 静默按普通 dict 处理；(b) TS `valueMap` 同样只映射值（键不插值）——此处一致，但 py 对 dict 键为 `__jsExpr` 嵌套形状的误判（D7 的 `${}`/`!!js ` 字符串分支）叠加造成"什么保持字面量"的边界与 TS 不同。
- 修复方案: `is_js_expr` 去掉 `isinstance(value["__jsExpr"], str)` 限制（保持 in 检查）；`evaluate_expr` 对非字符串输入直接抛 ValueError。

### D9 [MUST-FIX] EntryTree.await 不抛 fiber 失败、不 notify loader
- 位置: py:dsh/cordis/loader.py:553-560 (`await_tasks`) vs ts:vendor/loader/src/config/tree.ts:46-64 (`await`)
- 原版行为:
  ```ts
  const outcomes = await Promise.allSettled([...this.entries()].map(entry => entry._await()))
  const failures = outcomes.filter(...).map(o => o.reason)
  if (failures.length === 1) throw failures[0]
  if (failures.length > 1) throw new AggregateError(failures, 'loader fibers failed')
  this.ctx.reflect.notify(['loader'])
  if (!this.getTasks().length) return
  ```
  entry._await 把 fiber 失败包装为 `updateError('apply', ...)`（ts:entry.ts:269-275）。
- 移植版现状:
  ```python
  async def await_tasks(self) -> None:
      while True:
          tasks = self.get_tasks()
          if tasks:
              await asyncio.gather(*tasks, return_exceptions=True)
              continue
          break
  ```
  只等任务清空，fiber 失败被 `return_exceptions=True` 吞掉，boot 永远观察不到启动失败（对应 harness 的 assertEntriesActivated 缺口，见 17-harness 报告）。
- 修复方案: `await_tasks` 增加第二阶段：对每个 entry `await entry.fiber.await()`（py Fiber 如有 await 语义），失败聚合后抛出（单失败原样、多失败聚合成一条含全部原因的错误），并触发 `ctx.reflect.notify(["loader"])`；保留外层 while 重试（TS 同样循环直到无任务）。

### D10 [MUST-FIX] Loader [Service.check] 的 `await` 拦截缺失（依赖 loader 的插件不会等待树就绪）
- 位置: py:dsh/cordis/loader.py:924-963 vs ts:vendor/loader/src/index.ts:166-170 + 53-58
- 原版行为:
  ```ts
  declare [Service.config]: Loader.Intercept      // { await?: boolean }
  [Service.check]() {
    const config: Loader.Intercept = Service.prototype[Service.resolveConfig].call(this)
    if (config.await && this.getTasks().length) return false
    return true
  }
  ```
  声明 `inject: [{ service: 'loader', config: { await: true } }]` 的插件在树未稳定前保持 pending。
- 移植版现状: Loader 无 `[Service.check]` 等价物；`inject` 解析只做名称匹配（py:1084-1092 `Inject.resolve(opt_inject, fiber.inject)`），`await` 配置无消费方。
- 修复方案: 在 py 的 inject/注册检查协议中为 loader 服务增加 check 钩子：`config.get("await")` 为真且 `loader.get_tasks()` 非空时返回"未就绪"；若 py registry 无 check 机制，则在 `Inject.resolve` 时为该 fiber 挂起直至 `await_tasks()` 完成（并在报告中标注采用的形式）。

### D11 [MUST-FIX] showLog 门控失效：group 判断读错属性、enableLogs 门控缺失、默认值反转
- 位置: py:dsh/cordis/loader.py:528, 1142-1148 vs ts:vendor/loader/src/index.ts:172-175 + ts:vendor/loader/src/config/tree.ts:11
- 原版行为:
  ```ts
  showLog(entry: Entry, type: string) {
    if (entry.options.group || !entry.parent.tree.enableLogs) return
    this.ctx.root.logger?.('loader').info('%s plugin %C', type, entry.options.name)
  }
  ```
  `EntryTree.enableLogs` 默认 undefined → 日志默认关，需 include/配置显式开启。
- 移植版现状:
  ```python
  self.enable_logs = True                       # EntryTree.__init__ 默认 True
  def show_log(self, entry: Any, action_type: str) -> None:
      if getattr(entry, "group", False):        # Entry 实例没有 group 属性 → 恒 False
          return
      entry_name = getattr(entry, "name", str(entry))
      if hasattr(self.ctx, "logger"):
          self.ctx.logger("loader").info("%s plugin %s", action_type, entry_name)
  ```
  group 行不过滤（组条目会打日志）、`enable_logs` 完全不参与门控且默认 True（日志默认开）。
- 修复方案: `EntryTree.enable_logs` 默认 `None`；`show_log` 改为 `if entry.options.get("group") or not getattr(entry.parent.tree, "enable_logs", False): return`，日志格式对齐 `"%s plugin %s"`（name 用 options["name"]）。

### D12 [MUST-FIX] internal/update 的 'reload' 日志监听器缺失
- 位置: py:dsh/cordis/loader.py:1177-1196 vs ts:vendor/loader/src/index.ts:111-115
- 原版行为:
  ```ts
  ctx.on('internal/update', function (config, _, next) {
    if (!this.entry || this.parent.fiber?.entry === this.entry) return next()
    self.showLog(this.entry, 'reload')
    return next()
  }, { global: true })
  ```
- 移植版现状: 仅实现 save 型监听器（`_on_internal_update`），config 热更新不产生 `reload plugin <name>` 日志。
- 修复方案: 增加第二个 `internal/update` 监听器，在 fiber.entry 归属检查通过后调用 `self.show_log(fiber.entry, "reload")` 并透传。

### D13 [MUST-FIX] isolate patch-context：step 2 缺"service 未实现"告警；intercept 语义为合并而非整体替换
- 位置: py:dsh/cordis/loader.py:1006-1026 vs ts:vendor/loader/src/config/isolate.ts:110-126
- 原版行为:
  ```ts
  if (!impl.fiber) {
    entry.ctx.logger.warn(new Error(`expected service ${name} to be implemented`))
    continue
  }
  ...
  swap(entry.ctx[Context.intercept], entry.options.intercept)   // 整体替换
  ```
- 移植版现状:
  ```python
  impl = entry.ctx.reflect.store.get(sym) if ... else None
  if not impl:
      continue                       # 无告警
  ...
  entry.ctx._intercept_map.update(intercept_opt)   # 合并：旧 intercept 键无法撤销
  ```
- 修复方案: `impl` 缺失或无 fiber 时 `entry.ctx.logger("loader").warn("expected service %s to be implemented", name)`；intercept 改为整体替换 `entry.ctx._intercept_map = dict(intercept_opt or {})`（与 swap 等价）。

### D14 [MUST-FIX] 未知/导入失败插件只 warn 不抛错，无 'import' 失败传播
- 位置: py:dsh/cordis/loader.py:1256-1277 (`load_from_dict`)、887-916 (`Entry.init`) vs ts:vendor/loader/src/config/entry.ts:277-289
- 原版行为:
  ```ts
  try {
    plugin = this.loader.unwrapExports(await this.parent.tree.import(this.options.name, this.getOuterStack))
  } catch (error) {
    throw updateError('import', this.options, error)    // fail loud，冒泡到 group.update → boot 审计
  }
  ```
- 移植版现状:
  ```python
  else:
      if ctx and hasattr(ctx, "logger"):
          ctx.logger("loader").warn("Unknown plugin name/id: '%s'", plugin_name)
  ```
  `resolve_plugin_class` 内部 `except Exception: return (None, None)` 吞掉一切导入错误；entry 留下 `fiber=None` 继续运行，没有树级失败聚合。
- 修复方案: `Entry.init`/`load_from_dict` 在无法解析插件名时抛 `RuntimeError(f"failed to import loader entry {entry.id} ({name}): ...")`（message 对齐 updateError('import') 形态），由 D5/D9 的聚合与 await 链路传到 boot 层；`resolve_plugin_class` 只对"名称不是任何已知形式"返回 None，模块存在但导入失败必须上抛。

### D15 [MUST-FIX] EntryTree.update 移动回滚失败不聚合、成功后不写盘
- 位置: py:dsh/cordis/loader.py:633-650 vs ts:vendor/loader/src/config/tree.ts:125-142
- 原版行为:
  ```ts
  try { await entry.update({}, false, true) } catch (rollbackError) {
    throw new AggregateError([error, rollbackError], `failed to roll back loader entry move ${id}`)
  }
  ...
  source.tree.write()
  if (target !== source) target.tree.write()
  ```
- 移植版现状: 回滚失败仅 `logger.error`（py:645-649）后 `raise e`（原始错误）；成功路径无 `tree.write()`。
- 修复方案: 回滚失败抛 `RuntimeError(f"failed to roll back loader entry move {entry_id}: {error}; rollback: {rollback_err}")`；`update` 末尾对 `source.tree`（与跨组时的 `target.tree`）调用 `write()`。

### D16 [ADAPT] 模块导入管线：Node ESM internal loader → importlib/registry_map
- 位置: py:dsh/cordis/loader.py:24-83 (`resolve_plugin_class`)、924-963 vs ts:vendor/loader/src/index.ts:73, 191-199 + ts:vendor/loader/src/config/tree.ts:144-162
- 原版行为: `EntryTree.import` 走 `cordis:` builtins 表或 Node internal loader `internal.import(name, baseUrl)`；`unwrapExports` 归一 ESM/CJS 导出。
- 移植版现状: `registry_map` 名字表 + 点分模块路径 + `module:Class` + `文件.py:Class` 四段解析；无 unwrapExports。
- 评估: Python 无 ESM 导出形状问题，unwrapExports 不需要（合法省略）；四段解析是合法 ADAPT。但 `cordis:` builtin 表：TS `builtins[name.slice(7)]` 在 include/group 未注册时返回 undefined → `_start(undefined)` 抛错（fail loud）；py 的 registry_map 已含 `cordis:include`/`cordis:group`（py:943-947），等价。注意 py 额外把未知名回退成 Group（py:899-900），TS 无此回退——收窄为仅在 `options.group` 为真时回退。

### D17 [ADAPT] isolate Realm：Symbol → 字符串后缀
- 位置: py:dsh/cordis/loader.py:473-516 vs ts:vendor/loader/src/config/isolate.ts:26-68
- 原版行为: `this.store[key] ??= Symbol(\`${key}${this.suffix}\`)`；delim 为 Symbol，`entry.ctx[delim] = Symbol(\`${name}#${entry.id}\`)`。
- 移植版现状: store 值与 delim 均为字符串 `f"{key}{suffix}"`、`f"{name}#{entry.id}"`。
- 评估: 作为映射键/比较值的表面语义等价（Symbol 唯一性在 py 字符串方案下由后缀保证）；ADAPT。step 1 原型链继承（TS `Object.create(entry.parent.ctx[Context.isolate])`）在 py 为 dict 拷贝（py:971）——父后变更不再传播，属可接受 ADAPT，建议注释说明。

### D18 [ADAPT] applyEntryPatches 的 insert 行引用语义
- 位置: py:dsh/cordis/loader.py:382-455 (`apply_entry_patches`) vs ts:vendor/include/src/index.ts:58-128
- 原版行为: `structuredClone(data)` 后，insert 行以**引用**推入 `target.config`/`data`（patch 列表对象与结果共享）。
- 移植版现状: `cloned_insert = copy.deepcopy(insert)`（py:420）。
- 评估: 单次应用的结果值等价；py 的隔离消除了 TS 自认的跨快照泄漏隐患（ts:app-boot/src/index.ts:422-425 注释），合法 ADAPT。其余语义（buildMap 索引新增行、name 校验、warnings 文案）与 TS 一致。

### D19 [ADAPT] sortKeys 的 rest 排序与 ensureId 随机形状
- 位置: py:dsh/cordis/loader.py:458-470, 562-569 vs ts:vendor/loader/src/config/entry.ts:39-44 + ts:vendor/loader/src/config/tree.ts:66-73
- 原版行为: rest 键按 `a.localeCompare(b)`；id 为 `Math.random().toString(16).slice(2, 10)`（可为 0 开头）。
- 移植版现状: `sorted()`（ASCII 比较等价）；`hex(random.randint(0x10000000, 0xFFFFFFFF))[2:]`（恒 8 位、首位 1-f）。
- 评估: 排序对 ASCII 配置键等价；id 空间略窄但仍是 8 hex 不冲突即用，ADAPT。

### D20 [SKIP] internal.ts（Node 内部 ESM loader v1/v2 兼容层）
- 位置: ts:vendor/loader/src/internal.ts:1-132
- 原版行为: `ModuleLoader.fromInternal()` 经 `--expose-internals` / `node-addon-require-builtin` 抓取 Node 内部 ESM loader，兼容 Node 22/23(v1)/24(v2) 的 resolve/import/loadCache。
- 评估: 纯 Node 运行时管道；Python 侧由 importlib 与 registry_map 承担同等职责（见 D16），无移植对象。平台不适用，跳过。

### D21 [SKIP] Loader.envData / CORDIS_SHARED 共享环境
- 位置: ts:vendor/loader/src/index.ts:68-70 vs py:（无对应）
- 原版行为: `public envData = process.env.CORDIS_SHARED ? JSON.parse(...) : { startTime: Date.now() }`（多进程共享启动信息）。
- 评估: 依赖 Node 多进程共享协议，py 单进程运行时无消费方；跳过（如未来需要，等价物是磁盘共享文件）。

### D22 [MUST-FIX] Loader 公共面缺失：locate() 与 exit() 钩子
- 位置: py:dsh/cordis/loader.py:924-1304 vs ts:vendor/loader/src/index.ts:177-189
- 原版行为:
  ```ts
  locate(fiber = this.ctx.fiber) {          // 返回拥有该 fiber 的 loader entry id
    while (1) { if (fiber.entry) return fiber.entry.id; const next = fiber.parent.fiber; if (fiber === next) return; fiber = next }
  }
  exit() { }                                 // 宿主可覆写的全量重载钩子（HMR 调用）
  ```
- 移植版现状: 两者均缺失（`exit` 已在 12-hmr 报告 D3 记为 MUST-FIX 的依赖）。
- 修复方案: Loader 增加 `locate(fiber)`（沿 `fiber.parent` 上溯找 `entry`）与空 `exit()` 方法。

### D23 [ADAPT] Group 插件挂载细节
- 位置: py:dsh/cordis/loader.py:762-780 (`Group`) vs ts:vendor/loader/src/config/group.ts:116-129 + ts:vendor/group/src/index.ts:1-2
- 原版行为: `super(ctx, ctx.fiber.entry!.parent.tree)`（父树为挂载目标）；`ctx.on('internal/update', config => this.update(config))`（async，经瀑布被 include 短路或不短路地接力）；`[Service.init]` yield stop 后 `await this.update(this.config)`。
- 移植版现状: `target_tree = parent_group.tree or ctx.loader`；`ctx.on("internal/update", lambda cfg, *args: self.update(cfg))`（同步、不参与瀑布 next 链）；`init` 生成器 yield stop 后同步 update。
- 评估: 挂载目标与 init 顺序等价（ADAPT）；但 `internal/update` 监听器不经 next_fn 且同步执行，与瀑布语义的交互（include 短路后 Group 是否还能收到更新）与 TS 不同——依赖 include D1 的修复联动，收窄为：监听器改为签名 `(cfg, no_save=None, next_fn=None)` 并在处理后调用 `next_fn()`（若语义为透传）。

## 测试缺口

### T1 test_entry_disabled_plain_string_is_truthy（对应 D1）
`disabled: "false"` 字符串 → entry.disabled 为 True；`disabled: ""` → False；`!!js` 节点仍求值。

### T2 test_entry_disabled_group_exempt_and_ancestor_cascade（对应 D1）
`group: true` 的行即使 `disabled: true` 也启用；父 entry disabled → 子 entry disabled 为 True（Entry 层属性断言）。

### T3 test_entry_update_replace_name_reimports_plugin（对应 D3）
已有 fiber 的 entry update `name` → 旧插件 dispose、新插件按新名挂载；新插件 start 失败 → 旧插件回滚且抛 `failed to apply loader entry ...`。

### T4 test_entry_update_nullable_value_deletes_key（对应 D3）
update 传入 `{"config": None}` → options 中 config 键被删除（写入树亦无该键）。

### T5 test_entry_update_wraps_error_with_stage_and_id（对应 D3/D14）
import/dispose/apply/rollback 各阶段失败 message 形如 `failed to {stage} loader entry {id} ({name}): {detail}`。

### T6 test_entry_group_update_concurrent_mount_and_failure_aggregation（对应 D5）
多行 update 中一行失败 → 其余行仍完成挂载尝试，抛出的错误聚合全部失败原因；teardown 后的 update 直接返回不回滚（uid 为空守卫）。

### T7 test_entry_group_remove_emits_partial_dispose_and_gc_realm（对应 D6）
remove(entry) → 观察到 `loader/partial-dispose(entry, options, false)`；最后一个使用某 GlobalRealm label 的 entry 移除后 `loader._realms` 不再包含该 label。

### T8 test_interpolate_keeps_plain_strings_literal（对应 D7/D8）
`{"cmd": "${HOME}/run.sh"}` 经 `interpolate(ctx, ...)` 后 cmd 值原样；仅 `{"__jsExpr": ...}` 被求值。

### T9 test_tree_await_raises_fiber_failure_aggregate（对应 D9）
挂载一个 init 抛错的插件 → `await_tasks()` 抛出含该错误；两个失败 → 错误信息含两条。

### T10 test_loader_await_intercept_holds_dependent_pending（对应 D10）
注入 `{service: "loader", config: {await: true}}` 的插件在有在途 entry 任务时不激活，任务清空后激活。

### T11 test_show_log_gating（对应 D11/D12）
组条目不打 apply/unload 日志；`enable_logs=False` 的树静默；config 热更新产生 `reload plugin <name>` 日志。

### T12 test_isolate_patch_context_warns_when_service_unimplemented（对应 D13）
isolate 指向无实现的服务名 → logger.warn 含 `expected service <name> to be implemented`；intercept 键在新 options 中移除后不再生效。

### T13 test_unknown_plugin_name_raises_at_mount（对应 D14）
preset/patch 引用未注册插件名 → 挂载抛 `failed to import loader entry ...`（或经聚合到达 boot），而非仅 stderr warn。

### T14 test_tree_update_move_rollback_error_aggregated_and_written（对应 D15）
跨组移动后 update 失败 → 回滚错误并入异常；成功移动后 source/target 树各 write 一次。

### T15 test_loader_locate_returns_owner_entry_id（对应 D22）
子 fiber 经 `locate()` 返回挂载 entry 的 id。
