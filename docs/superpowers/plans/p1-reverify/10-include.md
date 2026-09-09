# G10-include 盲审报告

审计对象：
- TS 权威源：`reference/vendor/include/src/index.ts`（377 行，逐行通读）
- Python 被审移植：`dsh/cordis/include.py`（310 行，逐行通读）
- 关联依赖（核对共享行为所必需，已通读）：`dsh/cordis/loader.py`（`apply_entry_patches`、`js_constructor`、emitter 补丁、`EntryTree`/`EntryGroup`）、`dsh/cordis/context.py`、`dsh/cordis/events.py`、`dsh/cordis/fiber.py`、`dsh/cordis/service.py`、`reference/vendor/loader/src/config/{tree,group,entry,utils}.ts`、`reference/vendor/cordis/src/fiber.ts`、`tests/1to1/cordis/test_include_parity.py`。未读 docs/，未写任何文件，未运行 pytest/git。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| `JsExpr` yaml.Type (index.ts:9-15) | `js_constructor` (loader.py:106) + `js_dict_representer` (loader.py:135) + `_dsh_choose_scalar_style` (loader.py:116) | ADAPT（PyYAML 无 `Type.extend`，以全局 loader/dumper 补丁等价实现） |
| `entryListSchema`/`schema` (index.ts:23,25) | SafeLoader/SafeDumper 全局补丁注册 (loader.py:131-142) | ADAPT（导出面不同：TS 具名导出 schema，Python 为全局副作用） |
| `writable` (index.ts:27-31) | `SUPPORTED_EXTENSIONS` (include.py:39) + type 映射 (include.py:85) | D6（大小写宽窄） |
| `supported` (index.ts:33) | `SUPPORTED_EXTENSIONS` (include.py:39) | 1:1 |
| `WRITE_RETRY_LIMIT`/`WRITE_RETRY_DELAY_MS` (index.ts:35-36) | `WRITE_RETRY_LIMIT`/`WRITE_RETRY_DELAY_SEC` (include.py:36-37) | 1:1 / ADAPT（ms→s，偏离 2 无关，属等价改写） |
| `retryableWriteError` (index.ts:38-41) | 内联 `except (OSError, PermissionError)` (include.py:248,274) | D5 |
| `applyEntryPatches` (index.ts:58-128) | `apply_entry_patches` (loader.py:468-555) | 1:1（例外：D9 insert 真值、D14 深拷贝） |
| `ConfigUpdateStage` (index.ts:130) | `stage: str` (include.py:25) | ADAPT |
| `ReadCandidate` (index.ts:132-135) | `{"content","data"}` dict (include.py:169) | ADAPT |
| `ConfigFileError` (index.ts:137-142) | `ConfigFileError` (include.py:22-33) | D16 |
| `PatchOptions` (index.ts:145-156) | 无类型 dict | ADAPT |
| `Include.Config` namespace (index.ts:159-171) | dict 键 `path/initial/patches/enableLogs` | ADAPT |
| `Include` 类 (index.ts:174-375) | `Include` (include.py:42-308) | 见 D1-D19 |
| `static inject=['loader']` (index.ts:175) | `inject=["loader"]` (include.py:48) | 1:1 |
| `static [EntryGroup.key]=true` (index.ts:182) | `is_tree_carrier`/`entry_group_key` (include.py:49-50) | 1:1（映射等价） |
| 私有字段/writeQueue/applyQueue (index.ts:184-192) | 字段 + `_apply_lock`/`_write_lock` (include.py:87-108) | ADAPT（Lock 代替 Promise 队列，偏离 1 允许的 3.8 写法；回退分支见 D19） |
| 构造器 (index.ts:194-214) | `__init__` (include.py:52-131) | D11、D15、D18、D19 |
| `enqueue` (index.ts:225-229) | `_apply_lock` 的 `async with` (include.py:120,215) | ADAPT |
| `checkAccess` (index.ts:231-238) | `check_access` (include.py:142-146) | D8 |
| `read` (index.ts:240-265) | `_read_file`/`read` (include.py:148-173) | D4、D12 |
| `applyPatches` 私有包装 (index.ts:267-271) | `apply_patches` (include.py:133-140) | D10 |
| `async* [Service.init]` (index.ts:273-289) | `init` 同步生成器 (include.py:175-206) | D1 |
| `stop` (index.ts:291-294) | `stop` (include.py:208-211) | D2 |
| `refresh` (index.ts:301-309) | `refresh` (include.py:213-225) | 1:1 / ADAPT（同步读，见 D12） |
| `_apply` (index.ts:311-321) | 内联进 refresh/_on_update/init (include.py:120-127,193-198,219-225) | D1（init 内联顺序不一致） |
| `_writeFile` (index.ts:323-342) | `_write_file_sync`/`_write_file_async` (include.py:227-277) | D5 |
| `writeFile` (index.ts:344-350) | `write_file` (include.py:285-293) | D13 |
| `flushWrite` (index.ts:352-368) | `flush_write` (include.py:295-307) | D3 |
| `write` (index.ts:371-374) | `write` (include.py:279-283) | 1:1 |
| default export (index.ts:377) | `IncludeService = Include` (include.py:310) | 1:1（别名，见 D19） |

Python 自发明且 TS 无对应：`os.getcwd()` 回退（include.py:72）、`os.path.splitext(...).lower()`（81）、锁创建失败的 `new_event_loop` 回退（95-106）、`Service.__init__(name="include", allow_replace=True)` 服务注册（55，service.py:66-68）、init 中 `inspect.iscoroutine` 守卫（199-204）、`check_access` 的 `os.path.exists` 前置门（145）、`flush_write` 吞错（303-307）——均已计入对应 D 条目。
TS 有而 Python 无：`read()` 的动态 import 分支（死代码，D12）；`applyEntryPatches` 中解构后 `if (key === 'id') continue`（index.ts:121-122，死代码，Python 语义一致）。

## 差异

### D1: `init` 生命周期——同步生成器 + fire-and-forget apply + 状态先行提交 + 未入 applyQueue
- TS: `index.ts:273-289`
```ts
async* [Service.init]() {
  let candidate: ReadCandidate
  try { candidate = (await this.read(true))! } catch (error) { ... }
  yield () => this.stop()
  await this.apply(candidate)
}
```
  配合 `index.ts:225-229`（enqueue）与 `index.ts:311-321`（`_apply`：`root.update → content/data → checkAccess` 顺序）。TS cordis fiber 把 `[symbols.init]()` 返回的异步生成器作为 runner 结果消费（cordis/src/fiber.ts:257），init 体 `await this.apply` 完成前 fiber 不算激活；disposer 先注册。
- PY: `include.py:175-206`
```py
candidate = self._read_file(forced=True)
...
self.content = candidate["content"]; self.data = candidate["data"]; self.check_access()
patched = self.apply_patches(...)
res = self.root.update(patched)
if inspect.iscoroutine(res):
    try: loop = asyncio.get_running_loop(); self._update_task = loop.create_task(res)
    except RuntimeError: pass
yield self.stop
```
  四重偏差：(1) 同步生成器被 fiber 同步消费到第一个 yield（fiber.py:691-694），无 await 点；(2) `EntryGroup.update` 在运行中的 loop 下返回的是 **Task**（loader.py:1312-1316），`inspect.iscoroutine(Task)` 为 False，守卫永不命中，apply 成为孤儿任务，异常无人观测；(3) `content/data` 在 update 之前提交——apply 失败后 `content` 已等于文件内容，后续 `refresh()` 因内容未变直接 return（include.py:155-156），树永远停在未应用状态；TS 则 update 成功后才提交；(4) init 的 apply 不经过 `_apply_lock`，而 TS 注释明言 "every apply path funnels through this queue"（index.ts:216-224，含 "the init apply"）。另外 disposer yield 在 apply 之后（TS 在之前）。
- 判定： MUST-FIX
- 影响: 运行 loop 时（dsh-web 等）插件在条目实际挂载前即标记 ACTIVE；apply 失败被吞且热重载永久失效；与 internal/update、refresh 并发时可交错。
- 建议修法: 将 `init` 改为 `async def init` 异步生成器（Python 3.8 支持，Group.init 即此写法 loader.py:1419-1421）：先 `yield self.stop`，再在 `async with self._apply_lock:` 内复用与 `_apply` 等价的"update → content/data → checkAccess"顺序，`await`（`inspect.isawaitable` 而非 `iscoroutine`）`self.root.update(patched)` 的结果。

### D2: `stop()` 未 await `root.stop()`
- TS: `index.ts:291-294`
```ts
async stop() {
  await this.root.stop()
  await this.flushWrite()
}
```
- PY: `include.py:208-211`
```py
async def stop(self) -> None:
    self.root.stop()
    await self.flush_write()
```
  `EntryGroup.stop` 返回 Task（loader.py:1371-1376 `return loop.create_task(self._stop_async())`），此处未 await 即继续 flush。
- 判定： MUST-FIX
- 影响: 子条目 teardown 与写盘并发；unload 时可能把尚未停止的条目状态写回文件。
- 建议修法： `res = self.root.stop()` 后 `if inspect.isawaitable(res): await res`。

### D3: `flush_write` 吞掉写失败且空队列时不等待在途写
- TS: `index.ts:352-368`
```ts
private flushWrite(): Promise<void> {
  ...
  if (config === undefined) return this.writeQueue
  const run = this.writeQueue.then(() => this._writeFile(config), () => this._writeFile(config))
  this.writeQueue = run
  void run.catch((error) => { ...warn... })
  return run
}
```
  后台链吞错仅用于 `void run.catch`，而 `flushWrite()` 本身 `return run`——`stop()` 中 `await this.flushWrite()`（index.ts:293）会把写失败抛给调用方；无 pending 时返回 `writeQueue` 等待在途写。
- PY: `include.py:295-307`
```py
config_data = self.pending_write
self.pending_write = None
if config_data is None:
    return
async with self._write_lock:
    try: await self._write_file_async(config_data)
    except Exception as e:
        ... sys.stderr.write(...)   # 吞掉，不 re-raise
```
- 判定： MUST-FIX
- 影响: `stop()`/`flush_write` 调用方永远看不到写盘失败（TS 契约为 throws/拒绝）；无 pending 时提前返回，可能早于在途写完成。
- 建议修法： 去掉 `except` 吞错改为记录后 `raise`（后台调度点 write_file/call_soon 再单独吞错，对应 TS `void run.catch`）；`if config_data is None` 分支改为等待 `_write_lock` 空闲或在途任务。

### D4: YAML 方言基底——SafeLoader(YAML 1.1) vs js-yaml `JSON_SCHEMA`
- TS: `index.ts:23` 与 `index.ts:250-253`
```ts
export const entryListSchema = yaml.JSON_SCHEMA.extend(JsExpr)
...
if (this.type === 'application/yaml') { data = yaml.load(content, { schema }) }
```
- PY: `include.py:159-160`
```py
if self.type == "application/yaml":
    data = yaml.safe_load(content)
```
  `yaml.safe_load` = YAML 1.1 SafeLoader。分歧实例：`disabled: no` → TS JSON_SCHEMA 解析为字符串 `"no"`，loader `disabledOf` 走 `Boolean("no")` 为 **true（禁用）**；Python 解析为 `False`（**启用**）。`option: 1:30`（PyYAML 六十进制 int 90 vs TS 字符串）、`id: 012`（PyYAML 八进制 10 vs TS 字符串）、`~`/空串的 null 规则亦有别。
- 判定： MUST-FIX（两条允许偏离均不强制此选择）
- 影响: TS 工具链产出的 cordis.yml 在 Python 侧类型/真值漂移，尤其 `disabled` 布尔语义反转。
- 建议修法： 基于 `yaml.SafeLoader` 派生自定义 Loader，用 JSON 风格 implicit resolver（bool 仅 `true/false`、int/float JSON 正则、null 仅 `null/~`）替换默认 resolver，并保留 `tag:yaml.org,2002:js` constructor；`_read_file` 改用 `yaml.load(content, Loader=...)`，dump 侧保持 SafeDumper（写 `true/false` 本就 JSON 兼容）。

### D5: 写回重试谓词过宽 + 重试次数差一
- TS: `index.ts:38-41,333-341`
```ts
function retryableWriteError(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException | null)?.code
  return code === 'EACCES' || code === 'EBUSY' || code === 'EPERM'
}
...
} catch (error) { if (!retryableWriteError(error) || retry >= WRITE_RETRY_LIMIT) throw error
  await delay((retry + 1) * WRITE_RETRY_DELAY_MS) }
```
  （rename 共尝试 11 次、delay 10 次。）
- PY: `include.py:241-251`（`_write_file_async` 267-277 同）
```py
except (OSError, PermissionError):
    if retry >= WRITE_RETRY_LIMIT - 1: raise
    time.sleep(WRITE_RETRY_DELAY_SEC * (retry + 1))
```
  捕获任意 `OSError`（含 ENOENT/ENAMETOOLONG/EISDIR 等 TS 会立即抛出的错误）重试 10 次（9 次 delay），共 10 次尝试。
- 判定： 谓词 = MUST-FIX；次数差一 = DEVIATION-PERMITTED
- 影响: 非竞争性错误被无谓拖延 ~4.5s 后才抛；最终错误相同但延迟语义与 TS 不一致。
- 建议修法： 抽 `def _retryable_write_error(e)` 按errno/winerror ∈ {EACCES, EBUSY, EPERM}（Win7 共享冲突通常 winerror 32/33/5）判定；循环改 `range(WRITE_RETRY_LIMIT + 1)` 对齐 11 次尝试。

### D6: 扩展名大小写不敏感
- TS: `index.ts:198-201`
```ts
const ext = extname(this.filename)
if (!supported.has(ext)) { throw new Error(`extension "${ext}" not supported`) }
```
- PY: `include.py:81-83`
```py
ext = os.path.splitext(self.filename)[1].lower()
if ext not in SUPPORTED_EXTENSIONS:
    raise ValueError(...)
```
  `Config.YAML` 在 TS 被拒，Python 接受。
- 判定： MUST-FIX
- 影响: TS 拒绝的路径 Python 静默接受，方言门禁变宽。
- 建议修法： 去掉 `.lower()`。

### D7: 空 `!!js` 表达式体被拒，破坏自产文件循环重载
- TS: `index.ts:9-15`
```ts
const JsExpr = new yaml.Type('tag:yaml.org,2002:js', {
  kind: 'scalar',
  resolve: (data) => typeof data === 'string',
  construct: (data) => ({ __jsExpr: data }),
  ...
  represent: (data) => data['__jsExpr'],
})
```
  `!!js ''` → `{__jsExpr: ''}`（resolve 对 '' 通过）。
- PY: `loader.py:106-110`（由 include.py:160 经全局补丁生效）
```py
def js_constructor(loader, node):
    val = loader.construct_scalar(node)
    if val is None or not str(val).strip():
        raise ValueError("empty !!js expression body")
    return {"__jsExpr": val}
```
  Python 侧 represent `{__jsExpr: ''}` 会写回 `!!js ''`（represent_scalar），重载时命中该 ValueError → `ConfigFileError('parse')`：自产文件自身不可重载。
- 判定： MUST-FIX
- 影响: 空表达式场景下"写回后可循环重载"被打破（用户要求核对的 YAML 方言保真项）。
- 建议修法： 删除空体检查，接受 `''` 构造 `{__jsExpr: ''}`（求值语义由 loader 表达式求值层负责）。

### D8: `check_access` 在文件缺失时不置 readonly
- TS: `index.ts:231-238`
```ts
private async checkAccess() {
  if (!this.type) return
  try { await access(this.filename, constants.W_OK) } catch { this.readonly = true }
}
```
  access 对不存在文件抛 ENOENT → `readonly = true`。
- PY: `include.py:142-146`
```py
if os.path.exists(self.filename) and not os.access(self.filename, os.W_OK):
    self.readonly = True
```
  文件不存在 → 短路，`readonly` 保持 False，后续 `write()` 可重建文件。
- 判定： MUST-FIX
- 影响: 文件被外部删除后 TS 进入只读保护，Python 会静默重建，行为分叉。
- 建议修法： 去掉 `os.path.exists` 前置门，改为 `if not os.access(self.filename, os.W_OK): self.readonly = True`（os.access 对缺失文件返回 False，等价 TS）。

### D9: patch `insert` 真值语义——falsy 非 None 值在 Python 崩溃
- TS: `index.ts:80,93-95`
```ts
const { id, insert, name, ...overrides } = patch
if (insert) {
  ...
  } else { data.push(...insert) }
```
  `insert: 0/false/""` 为 falsy → 跳过 insert 分支，落入"非 insert patch"路径（要求 id）。
- PY: `loader.py:516-533`（被 include.py:140 调用）
```py
insert = patch_copy.pop("insert", None)
...
if insert is not None:
    cloned_insert = copy.deepcopy(insert)
    if pid: ... target["config"].extend(cloned_insert)
    else: result.extend(cloned_insert)
```
  `insert: False/0/""` 命中分支 → `extend(False)` → TypeError 崩溃（TS 是 warn/skip 或正常路径）。
- 判定： MUST-FIX
- 影响: 极端 patch 配置下 Python 抛未分类异常而非按 TS 语义处理。
- 建议修法： 分支条件改为对齐 JS 真值且保留空数组语义：`if insert is not None and (insert or isinstance(insert, list)):`（`[]` 在 JS 为 truthy，须照常进入分支 push/buildMap）。

### D10: warn 汇点——logger 命名与上下文层级不同
- TS: `index.ts:267-271`
```ts
private applyPatches(data: EntryOptions[], patches?: PatchOptions[]): EntryOptions[] {
  return applyEntryPatches(data, patches, (message, ...args) => {
    this.ctx.root.logger?.('loader').warn(message, ...args)
  })
}
```
- PY: `include.py:133-140`
```py
def _warn(msg: str, *args: Any):
    if hasattr(self.ctx, "logger"):
        self.ctx.logger("include").warn(msg, *args)
    else:
        sys.stderr.write(f"[Cordis Include Warning] {msg % args if args else msg}\n")
```
  三点不同：logger 标签 `'include'` vs `'loader'`；`self.ctx` vs `ctx.root`；无可选链时回退 stderr（且 `msg % args` 遇 `%C` 会抛 ValueError，依赖 loader.py:481-487 的兜底转 `%s` 才不炸）。
- 判定： MUST-FIX（低危）
- 影响: 跳过 patch 的诊断日志命名空间/过滤通道与 TS 不一致。
- 建议修法： `_warn` 改为 `self.ctx.root.logger("loader").warn(...)` 形式（保留 hasattr 守卫），移除 `%` 直排回退或复用 loader.py:486-487 的 `%C→'%s'` 转换。

### D11: 路径/baseUrl 表示与解析宽窄
- TS: `index.ts:197,204`
```ts
this.filename = fileURLToPath(new URL(this.config.path, this.ctx.baseUrl))
...
this.ctx.baseUrl = new URL('.', pathToFileURL(this.filename)).href
```
  URL 语义：baseUrl 缺失时 `new URL(path, undefined)` 抛错；绝对盘符路径作 `config.path` 会被当作 scheme 解析而失败；写回的是带尾斜杠的 `file:///…/dir/`。
- PY: `include.py:64-79,90-93`
```py
base_dir = self.ctx.base_url or getattr(self.ctx, "baseUrl", None) or os.getcwd()
...
self.filename = os.path.abspath(os.path.join(base_dir, raw_path))
...
self.ctx.base_url = self.base_url   # 纯文件系统路径，非 file:// URL
```
  自发明：cwd 回退；接受绝对路径 `config.path`；`ctx.baseUrl` 由 URL 变为裸目录路径（Python 生态 hmr.py:182-196 等已兼容两种形态，属吸收性偏离）。路径规范化部分（abspath/normpath）属允许偏离 2。
- 判定： DEVIATION-PERMITTED（其中"规范化"部分为偏离 2 强制的 ADAPT）
- 影响: 跨插件消费 `ctx.baseUrl` 时形态不同；TS 会失败的输入 Python 接受（门禁变宽）。
- 建议修法： 如需更严对齐，可去掉 cwd 回退、拒绝绝对路径入参；现状在 Python 生态内自洽，可保留并记录。

### D12: `read` 同步阻塞 I/O + TS 动态 import 死分支缺失
- TS: `index.ts:240-265`（`readFile` 异步；第三分支 `await import(this.filename)` + `module.default || module`）
- PY: `include.py:148-173`（`_read_file` 全同步，`read` 仅是 async 包装；无 import 分支）
- 判定： DEVIATION-PERMITTED（阻塞 I/O 在 3.8 下无 `asyncio.to_thread`，可用 `run_in_executor` 但影响极小；import 分支在 TS 中不可达——`supported` 恒等 `writable` 键集）
- 影响: 大配置文件读取时会阻塞事件循环。
- 建议修法： 可选：`_read_file` 经 `loop.run_in_executor` 执行；至少为 import 分支缺失留档。

### D13: `write_file` 无事件循环时同步落盘
- TS: `index.ts:344-350`（恒为 `setTimeout(0)` → `flushWrite` 延迟写）
- PY: `include.py:285-293`
```py
except RuntimeError:
    self._write_file_sync(config_data)
```
- 判定： DEVIATION-PERMITTED
- 影响: 无 loop 环境（纯 CLI 校验）下写时序由异步变同步，结果等价、时机不同。
- 建议修法： 保留，但应在 docstring 注明与 TS 的时序差。

### D14: insert 列表深拷贝（TS 共享 patch 对象引用）
- TS: `index.ts:91-94,101`（`target.config.push(...insert)` 直接推入 patch 内对象；`buildMap(insert)` 索引同批对象）
- PY: `loader.py:520` `cloned_insert = copy.deepcopy(insert)`
- 判定： DEVIATION-PERMITTED
- 影响: 结果与 patches 输入的别名关系不同（Python 更"干净"），单次 apply 语义一致。
- 建议修法： 保留；在 `apply_entry_patches` docstring 注明该处有意强于 TS。

### D15: `enableLogs` 的 null 处理
- TS: `index.ts:196`
```ts
this.enableLogs = config.enableLogs ?? ctx.fiber.entry?.parent.tree.enableLogs ?? false
```
- PY: `include.py:58-63`
```py
self.enable_logs = self.config.get("enableLogs", getattr(parent_tree, "enable_logs", False))
```
  `enableLogs: null` 时 TS 回落到父树值，Python 得到 None（键存在即取）。
- 判定： DEVIATION-PERMITTED
- 影响: 显式 null 配置下日志开关继承链断裂，场景罕见。
- 建议修法： `v = self.config.get("enableLogs"); self.enable_logs = v if v is not None else getattr(parent_tree, "enable_logs", False)`。

### D16: `ConfigFileError` 消息含 cause 文本；not-found 抛 `ConfigFileError` 而非普通 Error
- TS: `index.ts:137-142`（`super(\`failed to ${stage} config file ${path}\`, { cause })`，cause 不进 message）；`index.ts:283` `throw new Error(\`config file not found: ${this.filename}\`)`（plain Error）
- PY: `include.py:29-32`（`msg += f": {cause}"`）；`include.py:189` `raise ConfigFileError("read", self.filename, FileNotFoundError(...))`（已被 test_t1 钉死，test_include_parity.py:42-46）
- 判定： DEVIATION-PERMITTED（错误类型/文案可观察但无行为分支依赖；测试已固定 Python 侧选择）
- 影响: `str(err)` 文案不同；下游不能按 TS 的 Error/ConfigFileError 类型区分 not-found。
- 建议修法： 如需 1:1，可去掉 `": {cause}"` 拼接并将 not-found 改抛普通异常；或保留现状并在此记录许可。

### D17: `__jsExpr` 多键字典的 representer/is_js_expr 不对称
- TS: `loader/src/config/utils.ts:25-26` 与 `index.ts:13-14`
```ts
export function isJsExpr(value: any): value is JsExpr {
  return value instanceof Object && '__jsExpr' in value
}
...
represent: (data) => data['__jsExpr'],
```
  TS：任意含 `__jsExpr` 的对象按 `!!js` 标量写回（多余键被丢弃）。
- PY: `loader.py:135-138,145-147`
```py
def js_dict_representer(dumper, data):
    if len(data) == 1 and "__jsExpr" in data:
        return dumper.represent_scalar('tag:yaml.org,2002:js', str(data["__jsExpr"]))
    return dumper.represent_dict(data.items())
...
def is_js_expr(value): return isinstance(value, dict) and "__jsExpr" in value
```
  读侧接受多键（与 TS 一致），写侧仅单键才打 tag → 多键 js 节点写回后不再是 `!!js`，循环重载后求值语义改变（TS 则丢弃多余键）。
- 判定： DEVIATION-PERMITTED
- 影响: 仅当 js 表达式求值结果或 patch 注入多键 `{__jsExpr,…}` 字典时触发，罕见。
- 建议修法： representer 条件去掉 `len(data) == 1`（改为 `"__jsExpr" in data`），与 `is_js_expr` 及 TS 对齐。

### D18: `internal/update` 中 `self.data` 为 None 时静默跳过并短路
- TS: `index.ts:206-213`
```ts
ctx.on('internal/update', async (config, _, next) => {
  if (config.path !== this.config.path) return next()
  await this.enqueue(async () => {
    const data = this.applyPatches(this.data!, config.patches)
    await this.root.update(data); this.config = config
  })
})
```
- PY: `include.py:120-129`
```py
async with self._apply_lock:
    if self.data is not None:
        ...
        self.config = dict(new_config)
# Short-circuit waterfall matching TS behavior
return None
```
  init 未完成时 TS 会带着 `undefined` 进入 apply（loudly 失败），Python 静默跳过且仍短路（不调 next）。
- 判定： DEVIATION-PERMITTED
- 影响: 仅在 init 未完成时收到热更新这一竞态下有差异；D1 修复（init 入队）后此分支基本不可达。
- 建议修法： 随 D1 一并收敛（init 在锁内完成后该守卫可移除或改为报错）。

### D19: 锁的构造回退、服务名注册与别名导出（Python 自发明）
- TS: 无对应（Include 不自注册命名服务；Promise 队列无需预建）。
- PY: `include.py:95-106`
```py
try: self._apply_lock = asyncio.Lock(); self._write_lock = asyncio.Lock()
except RuntimeError:
    try:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        self._apply_lock = asyncio.Lock(); self._write_lock = asyncio.Lock()
    except Exception:
        self._apply_lock = None; self._write_lock = None
```
  另 `include.py:55` `Service.__init__(self, ctx, name="include", allow_replace=True)`（service.py:66-68 → ctx.provide）与 `include.py:310` `IncludeService = Include`。
- 判定： 锁回退 = ADAPT（偏离 1：3.8 的 `asyncio.Lock` 构造期绑定 `get_event_loop`，跨 loop 使用需此防御；但 `_apply_lock is None` 时 `async with None` 会 TypeError，建议失败时改为延迟创建）；服务注册与别名 = DEVIATION-PERMITTED（Python 服务模型需要，`allow_replace` 已避碰撞）。
- 影响: 锁为 None 的极端环境下 refresh/_on_update 崩溃；其余仅命名面差异。
- 建议修法： None 兜底改为惰性 `asyncio.Lock()`（首次使用时创建）；注册与别名保留留档。

## 测试缺口

### T1: patch insert 编入索引、后续 patch 可命中先前插入行 — index.ts:96-102
```ts
// Index what this patch added so a LATER patch in the same list can
// target it. ...
buildMap(insert)
```
现测试（test_include_parity.py T1/T2/T4/T5/T6）无 insert 用例：组内 insert（index.ts:87-92）、顶层 insert（93-95）、`patches=[{insert…},{id:<inserted>,disabled:true}]` 组合均未钉测。

### T2: patch 跳过路径的 warn+continue 语义 — index.ts:82-90,105-119
`patch insert: entry %C not found`、`is not a group`、`id is required`、`entry %C not found`、name mismatch skip（116-119）均无测试。

### T3: `refresh()` 未变短路 / 已变事务重应用 / 失败抛出 — index.ts:240-247,296-309
`if (!forced && this.content === content) return` 与 refresh 的 JSDoc "throws when reading… rollback fails" 均未钉测。

### T4: include 级 `!!js` 写回→重载闭环 — index.ts:9-23,327-331
`yaml.dump(config, { schema })` 后 `yaml.load(…, { schema })` 的往返（含 `": "` 表达式的单引号回落——loader 侧 T16 只测了 style，未测 include 的 write+read 闭环）。

### T5: applyQueue 串行化（init apply × internal/update × refresh 并发）— index.ts:216-229
注释所述"两并发 apply 在同批条目上交错 create/rollback"场景无测试；当前 Python 恰好在此分叉（D1）。

### T6: 不支持扩展名报错 — index.ts:198-201
`extension "${ext}" not supported` 未钉测（含大写扩展名在 TS 被拒的差异，D6）。

### T7: 写回重试与最终抛出 — index.ts:333-341
EBUSY/EACCES 竞争下 delay 后成功、超限后原样抛出，无测试。

### T8: `stop()` 顺序 `root.stop → flushWrite` 及写失败传播 — index.ts:291-294,352-368
stop 的先后顺序与 flushWrite 拒绝传导均未测（Python 当前 D2/D3 双双违反）。

### T9: internal/update path 不匹配时委托 next — index.ts:207
T2 只测了匹配路径的短路；`return next()` 委托分支未测。

### T10: checkAccess 对缺失文件置 readonly — index.ts:231-238
（对应 D8；Python 现行为反向。）

## PROBE 候选

- D4: 构造含 `disabled: no`、`val: 1:30`、`id: 012`、`k: on` 的 cordis.yml，分别在 node(js-yaml JSON_SCHEMA) 与 `yaml.safe_load` 下解析并打印类型/值——裁决 `disabled` 布尔反转与数值/字符串分叉是否实际可达（尤其经 loader `disabledOf` 的最终真值）。
- D7: 节点含 `{"__jsExpr": ""}` 调 `_write_file_sync` 后立刻 `_read_file(forced=True)`——确认 Python 侧抛 `ConfigFileError('parse')`；同文件在 TS 侧用 js-yaml dump/load 验证 `!!js ''` 可往返，从而钉死"自产不可重载"结论。
- D1: 运行 loop 中挂载 Include，init 尚未完成时立即发 `internal/update`（path 匹配），并用 `loop.set_exception_handler` 捕获孤儿 update task 的异常——验证"apply 异常无人观测 + 与 init apply 交错"的真实竞态。
- D3: 将目标目录置为只读（或以 Win7 共享锁打开目标文件）触发 `_write_file_async` 失败，`await inc.stop()`——断言 TS 语义应为 reject、Python 现为 resolve。
- D9: `patches=[{"id":"x","insert":False}]` 与 `{"id":"x","insert":0}` 调 `apply_entry_patches`——确认 Python TypeError、TS warn/skip 行为。
- D10/格式化: `ctx.logger("include").warn("patch: entry %C not found", "a")`——验证 Python logger 是否实现 TS 的 `%C`（JSON 引号包裹）占位符；若否，则 loader.py:481-487 的 ValueError 兜底成为唯一路径，需钉测其输出文案。
- D8: apply 后删除目标文件再触发 `check_access`——断言 TS `readonly=true` vs Python `readonly=False` 的最终写回行为分叉。
