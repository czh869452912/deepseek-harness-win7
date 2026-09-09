# G13-boot 盲审报告

审计范围：TS 权威源 7 个文件逐行通读完毕（app-boot/index.ts 实际 846 行、cmdline/index.ts 239 行、apps/cli 5 个文件）；Python 被审 5 个文件逐行通读完毕。为核对运行时语义另通读了被审文件直接依赖的运行时（dsh/cordis/{context,fiber,loader,include,environment,file_lock,hmr,reflect}.py、dsh/cordis/profile.py、apps/cli/main.py、apps/cli/args.py、dsh.py）。未运行任何命令、未写任何文件。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态 |
|---|---|---|
| app-boot index.ts `resolveConfigPath` (64) | dsh/boot/app_boot.py `resolve_config_path` (76) | 1:1 |
| index.ts `loadEnv` (81) | app_boot.py `load_env` (92) | 1:1 |
| index.ts `BOOTSTRAP_NAMES` (96) | dsh/cordis/environment.py `BOOTSTRAP_NAMES` (39) | 1:1（集合逐项一致） |
| index.ts `BOOTSTRAP_PREFIXES` (120) | environment.py `BOOTSTRAP_PREFIXES` (62) | 1:1 |
| index.ts `isBootstrapOnly` (128) | environment.py `is_bootstrap_only` (65) | 1:1 |
| index.ts `readEnvLayer` (142) | app_boot.py `_read_env_layer` (176) | 1:1 |
| index.ts `loadLayeredEnv` (180) | app_boot.py `load_layered_env` (213) | 1:1（home==cwd 用 normcase 比较，属 Win7 ADAPT） |
| @deepseek-ai/dsh-launch-environment `LaunchEnvironmentSnapshot`（index.ts:19 导入） | app_boot.py `LaunchEnvironmentSnapshot` (124) **与** environment.py `LaunchEnvironmentSnapshot` (168) 两份实现 | **D27** |
| index.ts `UserPatchWatchOptions` (213) | app_boot.py `watch_user_patches` 的无类型 dict 入参 (739) | ADAPT |
| index.ts `watchUserPatches` (235) | app_boot.py `watch_user_patches` (739) | D10 |
| index.ts `loadOptionalPatches` (280) | app_boot.py `load_optional_patches` (279) | 1:1 |
| index.ts `loadOverlayPatches` (300) | app_boot.py `load_overlay_patches` (293) | 1:1（异常类自定，ADAPT） |
| index.ts `anchorInsertedPluginNames` (311) | app_boot.py `_anchor_inserted_plugin_names` (242) | 1:1 |
| index.ts `parsePatchList` (335) | app_boot.py `_parse_patch_list` (264) | **D5** |
| index.ts `ConfigDumpLayer` (356) | app_boot.py `render_config_dump` 的 dict 层 (305) | ADAPT |
| index.ts `renderConfigDump` (394) | app_boot.py `render_config_dump` (305) | D12, D13 |
| index.ts `groupedDump` (460) | app_boot.py `render_config_dump` 内联 flush (376-401) | 1:1 |
| index.ts `mountRootInclude` (501) | app_boot.py `mount_root_include` (407) | D6, D7 |
| index.ts `FailLoudProcess` (550) | app_boot.py `DefaultProc` (552) | ADAPT |
| index.ts `retainAssembledRejection`/`releaseAssembledRejection`/`observeLoaderRejectionCheckpoint` (567/571/580) | app_boot.py `AssembledRejectionTracker` (462) + `retain/release_assembled_rejection` (536/540) + assert_entries_activated 内联 checkpoint (679-686) | 1:1（weakref 化属 ADAPT；setImmediate→sleep(0) 属 ADAPT） |
| index.ts `FAIL_LOUD_RELEASE_TIMEOUT_MS` (593) | app_boot.py 常量 (62) | 1:1 |
| index.ts `installFailLoud` (624) | app_boot.py `install_fail_loud` (544) | **D8** |
| index.ts `assertEntriesLoaded` (673) | app_boot.py `assert_entries_loaded` (626) | **D6** |
| index.ts `FIBER_PENDING/ACTIVE/FAILED` (686-688) | dsh/cordis/fiber.py `FiberState` (15) | 1:1（0/2/3 一致） |
| index.ts `formatActivationError` (691) | app_boot.py `_format_activation_error` (639) | ADAPT（Python 无 Error.stack） |
| index.ts `assertEntriesActivated` (707) | app_boot.py `assert_entries_activated` (645) | 1:1（审计语义逐条核对：拒绝 FAILED/PENDING、逐条归因、checkpoint 均等价） |
| index.ts `boot` (772) | app_boot.py `boot` (691) | 1:1（另见 D32 例外路径差异） |
| index.ts `HARNESS_SOURCE_SECTION` (822) | app_boot.py 常量 (61) | 1:1 |
| index.ts `addHarnessSourceSection` (838) | app_boot.py `add_harness_source_section` (769) | **D11** |
| profile.ts `PROFILES_DIR`/`PROFILE_PATCH_FILENAME` (41/44) | dsh/boot/profile.py (22/23) | 1:1 |
| profile.ts `PROFILE_MODULE_FALLBACK_DIR`（私有, 47） | profile.py (24, 公开导出) | ADAPT（可见性放宽） |
| profile.ts `PROFILE_TEMPLATES` (137) | profile.py (42) | 1:1（五个模板逐项一致） |
| profile.ts `INSTALLATION_OWNED_PROFILE_TUPLES`（私有, 161） | profile.py (65, 导出) | 1:1 |
| profile.ts `DEFAULT_PROFILE_BUNDLES`/`DEFAULT_PROFILE_PATCH_RELOAD` (166/169) | profile.py (26/27) | 1:1 |
| profile.ts `resolveProfileDir` (127) | profile.py `resolve_profile_dir` (620) | 1:1 |
| profile.ts `initProfile` (197) | profile.py `init_profile` (635) | 1:1 |
| profile.ts `readModuleProxyRecord` (219) | profile.py `read_module_proxy_record` (197) | 1:1 |
| profile.ts `ensureSymlink` (229) | profile.py `ensure_symlink` (206) | ADAPT（junction：is_symlink_or_junction/create_symlink, 131/152） |
| profile.ts `canonicalLinkPath` (270) | profile.py `canonical_link_path` (167) | ADAPT（normcase） |
| profile.ts `symlinkPointsTo` (283) | profile.py `symlink_points_to` (179) | ADAPT |
| profile.ts `ensureProfileSymlink` (291) | profile.py `ensure_profile_symlink` (228) | 1:1 |
| profile.ts `ownedPackageNames` (303) | profile.py `owned_package_names` (235) | 1:1 |
| profile.ts `removeProfileSymlink` (315) | profile.py `remove_profile_symlink` (252) | **D23** |
| profile.ts `isPackagedExecutable` (347) | profile.py `is_packaged_executable` (192) | **D25** |
| profile.ts `packageEntryFromPackage` (352) | profile.py `package_entry_from_package` (268) | ADAPT（resolve.exports 库 → 手写 export-map 走查） |
| profile.ts `packageProxySource` (379) | profile.py `package_proxy_source` (324) | ADAPT（createRequire.resolve → 候选枚举） |
| profile.ts `ensureModuleProxy` (434) | profile.py `ensure_module_proxy` (371) | 1:1 |
| profile.ts `readModuleFallbackManifest` (487) | profile.py `read_module_fallback_manifest` (415) | 1:1 |
| profile.ts `profileDependencyNames` (492) | profile.py `profile_dependency_names` (421) | ADAPT（peer 与 dep 重名去重；下游 visited 集合使行为等价） |
| profile.ts `resolveModuleFallbackEntries` (497) | profile.py `resolve_module_fallback_entries` (447) | 1:1 |
| profile.ts `moduleFallbackEntryCurrent` (535) | profile.py `module_fallback_entry_current` (481) | **D24**（symlink 分支） |
| profile.ts `moduleFallbackCurrent` (553) | profile.py `module_fallback_current` (502) | 1:1 |
| profile.ts `healProfilesModuleFallback` (579) | profile.py `heal_profiles_module_fallback` (599, async + with_file_lock) | 1:1 |
| profile.ts `healProfilesModuleFallbackLocked` (595) | profile.py `heal_profiles_module_fallback_locked` (585) | 1:1 |
| profile.ts `dependencyClosure` (608) | profile.py `dependency_closure` (507) | **D21** |
| profile.ts `healProfileModuleFallback` (643) | profile.py `heal_profile_module_fallback` (542) | **D22** |
| profile.ts `readProfileManifest` (685) | profile.py `read_profile_manifest` (665) | 1:1 |
| profile.ts `writeProfileManifest` (706) | profile.py `write_profile_manifest` (684) | 1:1 |
| profile.ts `sameBundles` (711) | profile.py 列表 `==` 内联 (704-705) | 1:1 |
| profile.ts `normalizeShippedProfile` (721) | profile.py `normalize_shipped_profile` (692) | **D30** |
| profile.ts `packageDirFromAnchor` (753) | profile.py `package_dir_from_anchor` (428) | ADAPT（createRequire.resolve.paths → 父目录 node_modules 走查，顺序等价） |
| profile.ts `resolveBundleDir` (778) | profile.py `resolve_bundle_dir` (720) | 1:1 |
| profile.ts `loadProfile` (805) | profile.py `load_profile` (739) | 1:1 |
| profile.ts `composeEntries` (854) | profile.py `compose_entries` (797) | D29 |
| cmdline index.ts `CmdlineArgs` (27) | dsh/boot/cmdline.py `CmdlineArgs` (13) | 1:1 |
| cmdline index.ts `AppExit`/`AppReady` (36/45) | cmdline.py 可调用约定 + `AppReady` 基类 (24) | ADAPT |
| cmdline index.ts `provideCmdline` (84) | cmdline.py `provide_cmdline` (60) | 1:1 |
| cmdline index.ts `AppStdin` (92) | 无类型约束 | ADAPT |
| cmdline index.ts `internals` (102) | cmdline.py `_Internals`/`internals` (34/57) | ADAPT（附加自发明 `queue_microtask`） |
| cmdline index.ts `exitOnStdinEnd` (123) | cmdline.py `exit_on_stdin_end` (85) | D19 |
| commander `Command`（cmdline index.ts:19 导入, 类型由宿主提供） | cmdline.py 自制 `Command` (144) + `CommanderError` (132) | **D31** |
| cmdline index.ts `parseCmdline` (165) | cmdline.py `parse_cmdline` (370) | 1:1 壳，语义受 D31 制约 |
| cmdline index.ts `hasAction` (199) | cmdline.py `has_action` (349) | 1:1 |
| cmdline index.ts `configureExitAndOutput` (213) | cmdline.py `configure_exit_and_output` (359) | 1:1 |
| cmdline index.ts `isCommanderError` (234) | cmdline.py `is_commander_error` (340) | 1:1 |
| bin.ts `readVersion` (17) | 无对应（apps/cli/args.py:51 硬编码 "1.2.3"） | **D3** |
| bin.ts 模式分发 (26-50) | apps/cli/main.py `main_async` (86, argparse 直连 build_harness) | **D1** |
| args.ts `parseDshArgs`/`resolveBoot`/`collect`/`rejectParentOptions` (112/83/61/148) | apps/cli/args.py `parse_dsh_args` 等 (51/171/235)（**生产路径未接线**） | **D2** |
| dump-config.ts `runDumpConfig` (30) | dsh/cordis/profile.py `dump_config` (359)（无溯源注释渲染） | **D4** |
| profile-boot.ts `createAppReady`/`provideCmdline` 接线 (40/258) | 无对应（harness.py 不提供 cmdlineArgs/appExit/appReady） | **D16** |
| profile-boot.ts `homePatchPath`/`INSTALL_ANCHOR` (69/74) | dsh/cordis/profile.py `home_patch_path` (23) / 无 INSTALL_ANCHOR | ADAPT/D1 |
| profile-boot.ts `resolveTelemetryPatch` (100) | dsh/cordis/profile.py `resolve_telemetry_patch` (304)（存在但 build_harness 未用） | **D17** |
| profile-boot.ts `prepareProfile` (118, 重写根 cordis.yml) | dsh/cordis/profile.py `prepare_profile` (239, 不写根文件) | D4 |
| profile-boot.ts `allPatches`/`composeProfile` (136/156) | dsh/cordis/profile.py `ComposedProfile`/`compose_profile` (280/311) | D4, D17 |
| profile-boot.ts `suppressShutdownError`/`runProfile` (197/209) | 无对应（harness.py `build_harness` (64) 自行装配） | D1 |
| plugin.ts `runPlugin`/`exportsPatch`/`reconcilePlugins`/`anchorPathSpec` (120/36/59/104) | **无任何 Python 对应** | **D18** |
| dsh/boot/__init__.py | TS 侧无单一对应（cmdline 是独立包 @deepseek-ai/dsh-cmdline） | ADAPT（打包合并） |
| harness.py `build_harness` (64) | TS 端无同名物；对照 runProfile+boot 端到端 | D1, D15, D16, D17 |
| （PY 独有）app_boot.py `file_url_to_path` (69)、四个异常类 (156-173)、`AssembledRejectionTracker` (462) | TS 侧内联/无 | ADAPT |
| （PY 独有）dsh/cordis/profile.py `BUILTIN_BUNDLES`/`BUILTIN_PROFILES`/`_load_builtin_bundles` (89-236)、`resolve_lan_trust` (392) | TS 侧无（TS 从 dsh.bundle manifest 动态解析） | D4 关联 |

## 差异

### D1: 生产启动管线不走 TS boot 管线（bin→runProfile→boot）
- TS: `apps/cli/src/bin.ts:26-34`
```ts
switch (invocation.mode) {
  case 'profile': {
    const { runProfile } = await import('./profile-boot.ts')
    await runProfile({
      environment: loadLayeredEnv('dsh'),
      profile: invocation.profile,
      patchFiles: invocation.patches,
      args: invocation.args,
    })
```
  以及 `profile-boot.ts:251` `const ctx = await boot(NAME, rootConfig, structuredClone(allPatches(composed)), (hostCtx) => {...})`。
- PY: `apps/cli/main.py:105-114` 直接 `build_harness(mode=..., patch_file=args.patch, enable_web=...)`；`dsh/harness.py:64-244` 用 `ctx.plugin(...)` 逐个注册约 40 个插件类 + `PresetLoader.load_preset_file(presets/<mode>.yaml, patches=combined_patches)`。TS 管线的全部阶段——`loadLayeredEnv` 先于 boot、profile 目录合成（bundle 层→profile 层→home 层→--patch→telemetry）、`prepareProfile` 重写空根 cordis.yml、`healProfilesModuleFallback`、`mountRootInclude`（create 后 loader 存活复查）、`watchUserPatches`（live 档）、`appReady.commit`——在生产路径均不执行（`dsh.boot.app_boot.boot`/`mount_root_include`/`watch_user_patches` 仅被 tests 引用）。
- 判定: MUST-FIX
- 影响: 预设/补丁/环境三层语义与 TS 快照溯源、热重载契约在产品入口整体缺位；boot 期审计（D15/D16/D17）被 harness 内联替代。
- 建议修法: `apps/cli/main.py` 改为 `parse_dsh_args` 分发 + `run_profile`（新增 Python 版 profile-boot）调用 `dsh.boot.app_boot.boot`，harness.build_harness 降级为 prepare 回调内的插件注册宿主。

### D2: launcher 参数方言与 args.ts 不符，且 parse_dsh_args 未接线
- TS: `apps/cli/src/args.ts:123-131`
```ts
    // The launcher's flags come first and end at the first token it does not
    // know; everything from there on belongs to the booted app, including
    // its -h. `dsh -h` with no profile still prints this help, below.
    .helpOption(false)
    .allowUnknownOption()
    .passThroughOptions()
    .enablePositionalOptions()
    .argument('[args...]', ...)
```
- PY: `apps/cli/main.py:19-30` 用 argparse（`--mode` 枚举、`--web`、`--prompt`、`--port` 等 TS 侧不存在的旗标），内层 args（"首个不识别 token 起全部交给 app"）概念消失；`apps/cli/args.py:51 parse_dsh_args` 是手工仿写且全仓库仅 `tests/1to1/boot/cmdline/test_args.py:10` 引用，生产入口不消费。
- 判定: MUST-FIX
- 影响: `dsh --profile tui --resume abc` 这类 TS 契约（args 透传给 cmdlineArgs）在 CLI 上不可表达。
- 建议修法: main.py 弃用 argparse 换 `parse_dsh_args`，并以 `provide_cmdline` 注入内层 args（见 D16）。

### D3: parse_dsh_args 与 parseDshArgs 的消息/版本差异（即便按 args.py 自身对照）
- TS: `apps/cli/src/bin.ts:17-22`
```ts
function readVersion(): string {
  const manifest = JSON.parse(
    readFileSync(fileURLToPath(new URL('../package.json', import.meta.url)), 'utf8'),
  ) as { version?: unknown }
  return typeof manifest.version === 'string' ? manifest.version : '0.0.0'
}
```
  另 `args.ts:96` `program.error(\`error: config dumps take no app arguments, got ${args.map(argument => JSON.stringify(argument)).join(' ')}\`)`；`args.ts:173` `.requiredOption('--profile <name>', ...)`（commander 专属缺失文案）。
- PY: `apps/cli/args.py:51` `def parse_dsh_args(argv, version: str = "1.2.3")`（硬编码版本）；`args.py:157` `_error(f"config dumps take no app arguments, got {' '.join(repr(a) for a in leftover)}")`（repr 单引号，非 JSON 双引号）；`args.py:260` `_error("--profile <name> is required")`。
- 判定: MUST-FIX（钉文本/钉行为漂移）
- 影响: `--dump-config` 带参错误输出与 `--version` 值与 TS 不一致。
- 建议修法: 读 package.json 版本；错误行改 JSON.stringify 等价（json.dumps）；补 required-option 文案。

### D4: dump-config 走另一套合成器，丢失 renderConfigDump 溯源与 defaultOnly 语义
- TS: `apps/cli/src/dump-config.ts:30-51`
```ts
export function runDumpConfig(profile: string, defaultOnly: boolean, patches: readonly string[]): void {
  const loaded = prepareProfile(profile, !defaultOnly)
  const layers: ConfigDumpLayer[] = loaded.layers.map(layer => ({ label: layer.packageName, patches: layer.patches }))
  if (!defaultOnly) {
    if (existsSync(loaded.patchPath)) layers.push({ label: loaded.patchPath, patches: loaded.patches })
    const homePatchFile = homePatchPath()
    ...
  process.stdout.write(renderConfigDump(NAME, join(loaded.dir, PROFILE_ROOT_FILENAME), layers))
```
- PY: `dsh/cordis/profile.py:359-373` `dump_config` 直接 `compose_entries` + `yaml.safe_dump`，无 `# ==` 溯源注释、无 defaultOnly、用户层来自硬编码 `BUILTIN_PROFILES`/`BUILTIN_BUNDLES`（`profile.py:200-236`）而非 `load_profile`/`resolve_bundle_dir` 对 profile 目录的解析；`dsh/cordis/profile.py:376-389` 虽有 `render_config_dump` 委托，但无调用方传入真实 layer 列表。
- 判定: MUST-FIX
- 影响: `--dump-config` 输出与 TS 的"可回载 YAML + 来源注释"契约不一致；损坏的 cordis.patch.yml 恢复诊断（defaultOnly）缺失。
- 建议修法: dump_config 改走 `dsh/boot/profile.py load_profile(userLayer=!defaultOnly)` + app_boot `render_config_dump`。

### D5: 空文档 patch 文件被静默接受为空层，TS fail-loud
- TS: `reference/packages/boot/app-boot/src/index.ts:344-346`
```ts
  if (!Array.isArray(parsed)) {
    throw new Error(`${binName}: ${label} ${file} must be a top-level YAML array of loader patch entries`)
  }
```
- PY: `dsh/boot/app_boot.py:269-270`
```python
    if parsed is None:
        return []
```
- 判定: MUST-FIX（违反"present patch file that cannot apply is a misconfiguration and must fail loud"，index.ts:273-275 JSDoc 契约）
- 影响: 仅含注释/空白的 cordis.patch.yml 在 Python 侧静默为零层，TS 侧启动即报错。
- 建议修法: `_parse_patch_list` 删除 None 短路，让 None 落入 `not isinstance(parsed, list)` 分支抛 `PatchParseError`。

### D6: loader 缺失时审计与挂载静默放行，TS 直接读 ctx.loader（抛错）
- TS: `reference/packages/boot/app-boot/src/index.ts:673-676`
```ts
export function assertEntriesLoaded(ctx: Context, binName: string): void {
  const failed = [...ctx.loader.entries()].filter(entry => entry.fiber === undefined && !entry.disabled)
```
  以及 `index.ts:507` `ctx.loader.builtins.include = ...`（loader 缺失即 TypeError，符合"settled context"前置）。
- PY: `dsh/boot/app_boot.py:628-630` `loader = ctx.get("loader"); if not loader: return`；`app_boot.py:414-416` `mount_root_include` 开头 `if loader is None: return None`。
- 判定: MUST-FIX
- 影响: 树被释放后调用审计会得到"全部通过"的假阳性；TS 的"audit describes a live tree，读 ctx.loader 越界即抛"（index.ts:790-798 注释契约）被弱化。注意 `boot()` 内部在 assert 前已复查 loader（app_boot.py:716-717），故该放行只影响独立调用方。
- 建议修法: 去掉 `assert_entries_loaded` 与 `mount_root_include` 的 loader 空值短路（或改为显式抛 RuntimeError）。

### D7: HostResolvedRootInclude 裸名解析失败时的回退行为自发明
- TS: `reference/packages/boot/app-boot/src/index.ts:509-518`
```ts
    : class HostResolvedRootInclude extends Include {
      override import(name: string, getOuterStack?: () => string[]): unknown {
        const specifier = isAbsolute(name) ? pathToFileURL(name).href : name
        if (name.startsWith('.') || name.startsWith('cordis:')) return super.import(specifier, getOuterStack)
        const internal = this.ctx.loader.internal
        if (internal === undefined) return super.import(specifier, getOuterStack)
        return internal.import(specifier, bareModuleBaseUrl, {})
      }
```
- PY: `dsh/boot/app_boot.py:423-433` `HostBoundInclude.import_plugin`：先 `resolve_module_specifier(name, base_dir)` + `os.path.exists(resolved)` 命中则按相对路径导入，否则 `return super().import_plugin(specifier, get_outer_stack)`（按原名再试）。TS 用 Node internal loader 以 `bareModuleBaseUrl` 解析，失败即原样抛错；Python 的"存在性探测→回退原名"是自发明路径，且 `bare_module_base_url` 以 `.mjs/.js` 结尾的判断（app_boot.py:429）为 TS 侧不存在的分支。
- 判定: ADAPT（无 Node internal loader，属强制等价改写——偏离清单不直接覆盖，但属运行时宿主差异；回退语义差异本身记录在案）
- 影响: 打包运行时（pkg 等价物）下裸名失败模式不同：TS 报 internal loader 诊断，Python 可能以非预期 specifier 二次导入。
- 建议修法: 回退分支应直接抛"cannot resolve bare module ... from base"类错误而非再试原名；`.mjs/.js` 特判删除。

### D8: install_fail_loud 额外劫持 asyncio loop 异常处理器，失败面远大于 unhandledRejection
- TS: `reference/packages/boot/app-boot/src/index.ts:661-663`
```ts
  const uninstall = (): void => void proc.off('unhandledRejection', handler)
  proc.on('unhandledRejection', handler)
  return uninstall
```
  仅注册 unhandledRejection；`FailLoudProcess`（index.ts:550-560）只声明 on/off/stderr/exit。
- PY: `dsh/boot/app_boot.py:596-613`
```python
    if proc is None:
        try:
            loop = asyncio.get_event_loop()
            orig_loop_handler = loop.get_exception_handler()
            def _loop_exc_handler(l, context):
                exc = context.get("exception") or context.get("message")
                handler(exc)
                ...
            loop.set_exception_handler(_loop_exc_handler)
```
- 判定: MUST-FIX
- 影响: 任意任务内异常（不止插件初始化的 unhandled rejection）都会触发 `fatal load failure` + `exit(1)`；且 uninstall（app_boot.py:615-623）在 loop 未运行时可能还原错 handler。`apps/cli/main.py:88` 与 `main.py:181` 双重安装加剧。
- 建议修法: 仅保留显式 proc 注入路径；若需等价 unhandledRejection，用 `loop.call_exception_handler` 过滤 `context["exception"]` 且不改全局默认链，或在 main 只安装一次。

### D10: watch_user_patches 的 INACTIVE_EFFECT 判定附加消息嗅探
- TS: `reference/packages/boot/app-boot/src/index.ts:259-265`
```ts
  } catch (error) {
    // A surface can dispose the whole tree while the watcher is still opening;
    // ... the HMR effect registration then fails with INACTIVE_EFFECT.
    if ((error as { code?: string } | null)?.code === 'INACTIVE_EFFECT') return async () => {}
    throw error
  }
```
- PY: `dsh/boot/app_boot.py:762-766` `if getattr(error, "code", None) == "INACTIVE_EFFECT" or "inactive" in str(error).lower(): return noop_disposer`
- 判定: MUST-FIX（后半条件自发明）
- 影响: 任何 message 恰含 "inactive" 的无关错误被吞成 noop disposer，掩盖真实故障。
- 建议修法: 删除 `or "inactive" in ...` 子句，仅比对 `CordisError.code`（fiber.py:221 已产生该 code）。

### D11: add_harness_source_section 的 section order 为自发明常量 -900
- TS: `reference/packages/boot/app-boot/src/index.ts:841-844`
```ts
  return systemPrompt.section({
    name: HARNESS_SOURCE_SECTION,
    order: FIRST_PARTY_SECTION_ORDER.HARNESS_SOURCE,
    text: `The DeepSeek Harness implementation checkout is at ${sourceRoot}. ...`,
  })
```
- PY: `dsh/boot/app_boot.py:774-776` `"order": -900`（`FIRST_PARTY_SECTION_ORDER` 未移植，文本本身逐字一致）。
- 判定: MUST-FIX（无法从被审源证实 -900 与官方常量等值；属无依据取值）
- 影响: section 排序偏离第一方布局约定。
- 建议修法: 移植 `FIRST_PARTY_SECTION_ORDER.HARNESS_SOURCE` 常量并引用之；若无法取得官方值，至少集中为具名常量并标注来源待核。

### D12: render_config_dump 的变更比较与 patchedBy 归因微差
- TS: `reference/packages/boot/app-boot/src/index.ts:448-451`
```ts
    const before = previous.map(entry => JSON.stringify(entry))
    for (let index = 0; index < composed.length; index += 1) {
      if (index >= before.length) provenance.push({ origin: layer.label, patchedBy: [] })
      else if (JSON.stringify(composed[index]) !== before[index]) provenance[index]?.patchedBy.push(layer.label)
    }
```
- PY: `dsh/boot/app_boot.py:364-370` 用 `json.dumps(e, sort_keys=True)`（键序不敏感——TS 侧键序变化计入"被 patch"，Python 不计），并附加去重 `if layer["label"] not in provenance[index]["patchedBy"]`（TS 无去重）。
- 判定: DEVIATION-PERMITTED（仅影响 dump 注释归因，单层循环下去重实为无害；sort_keys 偏离记录在案）
- 影响: 极端键序变化时 `# ==` 标签可能少标一个 patch 层。
- 建议修法: 与 TS 对齐去掉 sort_keys 与去重，保持逐位快照语义。

### D13: render_config_dump 缺文件错误的类型/文案差异
- TS: `reference/packages/boot/app-boot/src/index.ts:400-405`
```ts
  let content: string
  try {
    content = readFileSync(absoluteConfigPath, 'utf8')
  } catch (error) {
    throw new Error(`${binName}: failed to read config ${absoluteConfigPath}: ${String(error)}`)
  }
```
- PY: `dsh/boot/app_boot.py:312-313` 预检 `os.path.exists` 抛 `ConfigFileNotFoundError("...: file not found")`（自定义双继承异常类，app_boot.py:161-163）。
- 判定: DEVIATION-PERMITTED（Python 无 ENOENT 文案；异常类型自定是语言映射）
- 影响: 错误文案与 TS 断言不同。
- 建议修法: 若需 1:1 文案，去掉 exists 预检、统一走 try/except 分支。

### D15: harness.py 内联第二套激活审计，替代 assertEntriesActivated
- TS: `reference/packages/boot/app-boot/src/index.ts:725-731`
```ts
    if (state === FIBER_PENDING) {
      const missing = Object.keys(fiber.inject).filter(service => fiber.ctx.get(service) === undefined)
      const subject = missing.length === 1 ? 'service' : 'services'
      failures.push(`${entry.options.name}: pending (waiting for ${subject}: ${missing.join(', ') || 'unknown'})`)
    } else {
      failures.push(`${entry.options.name}: fiber state ${String(state)}`)
    }
```
  汇总为 `${binName}: ${count} ${noun} did not activate\n...`（index.ts:737-738）；FAILED 先 `await fiber.await()` 收回原始栈（index.ts:716-723）。
- PY: `dsh/harness.py:209-229` 自行遍历：跳过 `options.get("group")`/名字 `("cordis:group","group")`/`EntryGroup` 类型（TS 侧无此豁免，组行无 fiber 即在 `assertEntriesLoaded` 被点名）；FAILED 用 `getattr(fiber, "error", None)` 不 await（丢失原始异常栈与 rejection checkpoint）；消息格式 `f"{name} (pending waiting for ...)"` 且汇总为单行 `f"plugin(s) failed to activate: {', '.join(failed)}"`。
- 判定: MUST-FIX
- 影响: 与 app_boot.assert_entries_activated 双轨并存且语义不同（归因格式、组行处理、栈恢复）。
- 建议修法: harness.py 删除内联循环，直接 `await assert_entries_activated(ctx, "dsh")`（或 assertEntriesLoaded+Activated 两段）。

### D16: 启动前置服务未按 TS provide：cmdlineArgs/appExit/appReady 缺失，env 快照用 set_service
- TS: `apps/cli/src/profile-boot.ts:254-262`
```ts
    // Before any config-tree entry mounts, so plugins resolve all launch-time
    // environment values from the same immutable provenance snapshot.
    hostCtx.provide(DSH_LAUNCH_ENVIRONMENT_KEY, options.environment)
    // The command line and bounded exit request are launcher facts available
    // to every app plugin that injects the argument snapshot.
    provideCmdline(hostCtx, {
      args: options.args,
      exit: code => void shutdown.shutdown(code),
      ready: appReady.service,
    })
```
- PY: `dsh/harness.py:79-88` 仅 `ctx.set_service("launch_environment", launch_env)`（allow_replace=True 的全局 set，非 fiber-owned provide）与手工属性 `ctx.dshHomePath`；全文件无 `provide_cmdline`/`appExit`/`appReady`/`exit_on_stdin_end` 接线（cmdline.py 的 `parse_cmdline`/`exit_on_stdin_end` 因此在产品内不可用——二者要求前置服务，cmdline.py:91-92、376-378）。
- 判定: MUST-FIX
- 影响: stdio 应用生命周期（stdin EOF→exit）与 app 自有旗标解析的 TS 扩展点整体悬空。
- 建议修法: build_harness 在挂树前 `provide_cmdline(ctx, {...})` 并以 `ctx.provide(LAUNCH_ENVIRONMENT_KEY, snapshot)`（provide 语义）替换 set_service。

### D17: DSH_TELEMETRY_DISABLED 开关在 build_harness 路径未生效
- TS: `apps/cli/src/profile-boot.ts:169-172`
```ts
  const composedOverlays = [...overlays]
  const telemetryPatch = resolveTelemetryPatch(process.env.DSH_TELEMETRY_DISABLED, rows.has(TELEMETRY_ROW_ID))
  if (telemetryPatch !== undefined) composedOverlays.push(telemetryPatch)
```
- PY: `dsh/cordis/profile.py:304-349` `resolve_telemetry_patch`/`compose_profile` 已实现（含 `resolve_telemetry_patch` 的 any-non-empty 语义——注意 PY `if not disabled_env` 与 TS `if ((disabledEnv ?? '') === '' ...)` 等价），但 `dsh/harness.py:189-202` 只拼 home 层与 --patch，从不调用 compose_profile/telemetry。
- 判定: MUST-FIX
- 影响: 隐私开关（任何非空值禁用 session-telemetry-otel 行）在产品启动路径失灵。
- 建议修法: build_harness 引入 compose_profile 的行检测或在装载后按 `DSH_TELEMETRY_DISABLED` 应用 `{id: TELEMETRY_ROW_ID, disabled: True}` patch。

### D18: `dsh plugin` 子命令（pnpm 转发 + bundles 对账）无 Python 对应
- TS: `apps/cli/src/plugin.ts:120-138`
```ts
export function runPlugin(profile: string, args: readonly string[]): number {
  const dir = resolveProfileDir(profile)
  if (!existsSync(join(dir, 'package.json'))) {
    const template = PROFILE_TEMPLATES[profile]
    initProfile(dir, template?.bundles ?? DEFAULT_PROFILE_BUNDLES, template?.patchReload)
    ...
  const result = spawnSync('pnpm', args.map(argument => anchorPathSpec(argument, process.cwd())), ...)
```
  含 `reconcilePlugins`（按安装态增删 `dsh.profile.bundles`，plugin.ts:59-91）与 `anchorPathSpec`（相对路径重锚，plugin.ts:104-112）。
- PY: 无任何文件实现（apps/cli/args.py 仅解析出 `mode: 'plugin'`，无执行体；args.py:266-270 返回后无消费者）。
- 判定: MUST-FIX（偏离清单不豁免功能缺失；可论证以 pip/静态目录替代 spawn pnpm，但对账与初始化契约须有等价物）
- 影响: `dsh plugin --profile <n> add <pkg>` 契约（初始化、转发、bundles 对账、git+prepare 提示 plugin.ts:155-160）缺失。
- 建议修法: 新增 Python `run_plugin`：init_profile（dsh/boot/profile.py:635 已备）+ 子进程转发（Win7 规则下走 shell/pip 等价）+ manifest 对账。

### D19: exit_on_stdin_end 对 ready 的可调用回退自发明
- TS: `reference/packages/boot/cmdline/src/index.ts:133-137`
```ts
  const onEnd = (): void => {
    if (!active || ended) return
    ended = true
    cancelReady = ready.onReady(() => { exit(0) })
  }
```
- PY: `dsh/boot/cmdline.py:103-107` `on_ready_fn = getattr(ready, "on_ready", getattr(ready, "onReady", None)); if callable(on_ready_fn): ... elif callable(ready): cancel_ready[0] = ready(lambda: exit_fn(0))`（把 ready 本身当 disposer 形状的钩子）。
- 判定: DEVIATION-PERMITTED（宽松鸭子类型回退；主路径 on_ready/onReady 已覆盖 TS 契约）
- 影响: 仅当宿主传裸函数时行为不同。
- 建议修法: 如需严格 1:1 删除 elif 分支。

### D21: dependencyClosure 对无名 manifest 的处理：TS 整棵跳过，Python 仍遍历依赖
- TS: `reference/packages/boot/app-boot/src/profile.ts:616-623`
```ts
    const canonicalAnchor = realpathSync.native(anchor)
    const manifest = readModuleFallbackManifest(canonicalAnchor)
    if (manifest.name === undefined) continue
    if (!visited.has(manifest.name)) {
      visited.add(manifest.name)
      links.set(manifest.name, dirname(canonicalAnchor))
    }
```
- PY: `dsh/boot/profile.py:515-525` `if "name" in manifest: ...links[...]` 之后无条件继续 BFS 遍历该锚点依赖；且新增 `if not os.path.exists(anchor): continue` 容忍（TS 会 ENOENT 抛错）。
- 判定: MUST-FIX（次要）
- 影响: 无 name 的包其依赖被并入 fallback，TS 不会。
- 建议修法: `if "name" not in manifest: continue` 放在 BFS 之前。

### D22: healProfileModuleFallback 的 exclude 回调丢失 ENOENT→true 并发容忍
- TS: `reference/packages/boot/app-boot/src/profile.ts:657-663`
```ts
    } catch (error) {
      // A concurrent cleanup may remove the projection after package discovery.
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return true
      throw error
    }
```
- PY: `dsh/boot/profile.py:562-565` `except Exception: return False`（全部异常按"不排除"处理且不再上抛）。
- 判定: MUST-FIX（次要并发语义）
- 影响: 并发清理窗口下 Python 会把正被清理的投影再次纳入闭包，可能重建刚删的链接。
- 建议修法: 捕获 FileNotFoundError 返回 True，其他异常上抛。

### D23: removeProfileSymlink 吞掉全部 OSError，TS 只容忍 ENOENT
- TS: `reference/packages/boot/app-boot/src/profile.ts:318-329`
```ts
  try {
    if (lstatSync(profileLink).isSymbolicLink() && symlinkPointsTo(profileLink, ownedLink)) unlinkSync(profileLink)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  try {
    unlinkSync(ownedLink)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
```
- PY: `dsh/boot/profile.py:256-265` 两段均 `except OSError: pass`；且用 `symlink_points_to` 替代 `lstat().isSymbolicLink()` 判定（后者由 junction ADAPT 覆盖）。
- 判定: MUST-FIX（次要）
- 影响: 权限/占用类错误被静默吞掉，清理失败不可见。
- 建议修法: 仅捕获 FileNotFoundError，其余 raise。

### D24: moduleFallbackEntryCurrent 的 symlink 判定由精确 readlink 比较放宽为规范化比较
- TS: `reference/packages/boot/app-boot/src/profile.ts:538-541`
```ts
    const stat = lstatSync(link)
    if (entry.kind === 'symlink') {
      return stat.isSymbolicLink() && readlinkSync(link) === entry.packageDir
    }
```
- PY: `dsh/boot/profile.py:485-486` `return is_symlink_or_junction(link) and symlink_points_to(link, entry["packageDir"])`（normcase+realpath 父目录比较，profile.py:179-189）。
- 判定: ADAPT（Win7 SP1 规则第 2 条：junction/大小写不敏感路径必须规范化比较；TS 的字面比较在 junction 下不可用）
- 影响: 语义等价性成立，仅在不同路径拼写场景下 Python 判定更宽容。
- 建议修法: 无（保留），测试需覆盖大小写/尾斜杠差异场景。

### D25: isPackagedExecutable 增加 DSH_TEST_PACKAGED 环境变量测试钩子
- TS: `reference/packages/boot/app-boot/src/profile.ts:346-349`
```ts
/** Return whether the process reads application modules from pkg's virtual filesystem. */
function isPackagedExecutable(): boolean {
  return (process as NodeJS.Process & { pkg?: unknown }).pkg !== undefined
}
```
- PY: `dsh/boot/profile.py:192-194` `getattr(sys, "pkg", None) is not None or os.environ.get("DSH_TEST_PACKAGED") == "1"`。
- 判定: DEVIATION-PERMITTED（测试注入点；无 pkg 等价物时的可测性改写）
- 影响: 环境变量可强制走 proxy 分支，产品无碍。
- 建议修法: 保留，但在 AGENTS 测试规范中登记该钩子。

### D27: LaunchEnvironmentSnapshot 存在两份语义不同的实现
- TS: `reference/packages/boot/app-boot/src/index.ts:19`（单一权威类型）`import { createLaunchEnvironmentSnapshot, type LaunchEnvironmentSnapshot } from '@deepseek-ai/dsh-launch-environment'`；`index.ts:196-200` 由 process/project-env/user-env 层构造。
- PY: `dsh/boot/app_boot.py:124-153`（`get` 倒序遍历 `_layers` 原始层）与 `dsh/cordis/environment.py:168-211`（`get_from` 固定 SOURCE_ORDER 且 Win32 下键大写折叠；`harness.py:79` 经 environment.py:246-248 再包一层）。
- 判定: MUST-FIX
- 影响: 同名类两套 get 语义（含 Windows 大小写折叠只在一侧存在），消费方拿到哪份取决于 import 路径。
- 建议修法: app_boot.py 仅返回 environment.py 的单一实现，删除本地类。

### D29: compose_entries 的 warn 尾参 % 格式化自发明
- TS: `reference/packages/boot/app-boot/src/profile.ts:856-860`
```ts
  return applyEntryPatches([], structuredClone(layers.flat()), (message: string, ...args: unknown[]) => {
    let index = 0
    warn(message.replace(/%C/g, () => JSON.stringify(args[index++])))
  })
```
- PY: `dsh/boot/profile.py:816-821` 在 `%C` 替换完后追加 `if idx < len(args): formatted = formatted % args[idx:]`（把剩余参数当 printf 尾参再格式化一次）。
- 判定: DEVIATION-PERMITTED（仅在 warn 消息含额外 `%` 时可能改变输出；默认 warn 为静默）
- 影响: 含 `%s` 的消息文案可能被二次格式化出意外文本。
- 建议修法: 删除尾参格式化分支，与 TS 对齐只做 %C 替换。

### D30: normalize_shipped_profile 的 patchReload 回填用 `or` 而非空值安全合并
- TS: `reference/packages/boot/app-boot/src/profile.ts:736-737`
```ts
        bundles: [...template.bundles],
        patchReload: manifest.dsh?.profile?.patchReload ?? template.patchReload,
```
- PY: `dsh/boot/profile.py:713-715` `normalized["dsh"]["profile"]["patchReload"] = manifest...get("patchReload") or template["patchReload"]`——空串等 falsy 值会被静默改写为模板值并写回磁盘；TS 保留原值（随后由 load_profile 校验报错）。
- 判定: MUST-FIX（轻）
- 影响: 非法 patchReload 在 Python 侧被静默"修复"，TS 侧 fail-loud。
- 建议修法: 改为 `patchReload if patchReload is not None else template["patchReload"]`。

### D31: 自制 Command 解释器与 commander 语义不一致（parseCmdline 的宿主契约）
- TS: `reference/packages/boot/cmdline/src/index.ts:19-20, 176-185`
```ts
import type { Command } from 'commander'
...
  configureExitAndOutput(program)
  try {
    program.parse(args.get(), { from: 'user' })
  } catch (error) {
    if (!isCommanderError(error)) throw error
    exit(error.exitCode)
  }
```
  commander 的 action 调用约定为 `(...operands, options, command)`，且宿主程序可声明 `allowUnknownOption/passThroughOptions/requiredOption/collect`。
- PY: `dsh/boot/cmdline.py:322-337`
```python
            if param_count == 0:
                self._action_handler()
            elif param_count == 1:
                if self._arguments and operands:
                    self._action_handler(operands[0])
                else:
                    self._action_handler(parsed)
            else:
                self._action_handler(*operands, parsed, self)
```
  按 inspect 签名数分派（单参时传 options 而非 operand）；`Command` 无 allowUnknownOption/passThroughOptions/version/requiredOption/argument 声明 API（option() 不支持 collect 回调，cmdline.py:188-210）；含子命令的根遇到未匹配 operand 直接 `error("unknown command")`（cmdline.py:310-315）；help 检测 `"-h" in argv` 会把等于 `-h` 的选项值误判（cmdline.py:264）；且 `parse` 引用了从未初始化的 `self._arguments`（cmdline.py:332）——单参 action 且有 operand 时将 AttributeError。
- 判定: MUST-FIX
- 影响: 任何从 TS 宿主程序移植的 app 命令语法在 Python 侧无法等价表达；`_arguments` 缺陷是潜伏崩溃点。
- 建议修法: `Command.__init__` 增加 `self._arguments = []`；action 一律按 `(*operands, parsed, self)` 调用；补齐透传/未知选项开关；help 检测只在 operand 位置扫描。

### D32: boot() 异常路径不捕获 CancelledError，部分树不 dispose
- TS: `reference/packages/boot/app-boot/src/index.ts:801-805`
```ts
  } catch (cause) {
    // ... a repeated call returns the settled single-shot result, so this await cannot reject and replace `cause`.
    await ctx.fiber.dispose()
```
- PY: `dsh/boot/app_boot.py:720-722` `except Exception as cause:` ——Python 3.8 中 `asyncio.CancelledError` 继承 BaseException，取消时跳过 dispose 与包装直接穿透。
- 判定: DEVIATION-PERMITTED（asyncio 取消语义下放行取消通常更正确；与 TS catch-all 行为不同的事实记录在案）
- 影响: 启动中被取消的 boot 留下未清理的部分 ctx。
- 建议修法: 如需严格对齐，加 `except asyncio.CancelledError: await ctx.fiber.dispose(); raise`。

## 测试缺口

### T1: 空/仅注释 patch 文档必须 fail-loud — TS index.ts:344-346（"must be a top-level YAML array"）；Python `_parse_patch_list` 现 return []（D5），缺反向钉测。
### T2: bootstrap-only 变量在 project 层与 user 层各自抛错且两文件都不被应用（先解析后应用）— TS index.ts:186-195；PY 侧无"一个文件被拒后另一个不落地"的钉测。
### T3: loadLayeredEnv 不覆盖已存在的环境变量、home==cwd 跳过 user 层 — TS index.ts:188, 190-195；PY normcase 路径（app_boot.py:225）缺 Win7 大小写/短路径差异钉测。
### T4: assertEntriesActivated 的 PENDING 归因文案（单/复数 service/services、unknown 兜底）与 FAILED 逐条原始栈 — TS index.ts:716-731, 737-738；tests/test_app_boot.py:587-663 已有部分，缺多失败聚合顺序与 rejection checkpoint 合并（retain→sleep→release，index.ts:580-587）钉测。
### T5: mountRootInclude 在 create 后 loader 被释放 → 返回 undefined、entry 缺失不写 bootstrapIncludes — TS index.ts:538-543；PY 无对应测试（且 PY 多了 `if entry is not None` 才写 weakmap 的分支，app_boot.py:457-458）。
### T6: installFailLoud 三件套：assembled rejection 合并（index.ts:630-631）、exiting latch 吞后续（632-636）、release 超 2s 仍 exit(1)（645-659, 593）；PY 侧全缺，且 D8 的 loop-handler 行为需要反向钉测（任务异常不得触发 exit）。
### T7: renderConfigDump 的 `# ==` 分组注释、`patched by` 标签与 skipped-patch warn 前缀 `[label]` — TS index.ts:444-451, 460-488；tests/test_reference_app_boot_config_dump_1to1.py 仅覆盖表层。
### T8: watchUserPatches：HMR/根 include 缺失抛错文案（index.ts:240-243）、INACTIVE_EFFECT→noop（264）、刷新保留 include 其他 config 字段（247-255）。
### T9: exitOnStdinEnd：EOF 先于 ready 提交 → onReady 挂钩后 exit(0)；可读已结束→queueMicrotask 立即触发；disposal 移除监听并取消 ready — TS cmdline index.ts:129-145。
### T10: parseCmdline：缺 cmdlineArgs/appExit 抛错、无 action 抛错、CommanderError→exit(exitCode) 而非崩溃、非 commander 错误 rethrow — cmdline index.ts:170-185；PY 需连同 `_arguments` 缺陷（D31）一并钉测。
### T11: runProfile 信号契约：SIGTERM→exit 0、SIGINT→exit 130，fail-loud release 先于 exit — profile-boot.ts:219-228。
### T12: resolveTelemetryPatch：任意非空值（含 '0'/'false'）禁用；无 telemetry 行时不生成 patch — profile-boot.ts:100-103；PY cordis/profile.py 有实现但 build_harness 未用（D17），缺端到端钉测。
### T13: dsh plugin 全链（初始化、pnpm 转发、ENOENT→127、reconcile 增删 bundles、相对路径重锚）— plugin.ts:120-163；PY 完全缺失（D18）。
### T14: prepareProfile 每次启动重写空根 cordis.yml（防 Loader 回写固化组合层）— profile-boot.ts:106-122；PY 无对应行为与测试。
### T15: args.ts 语法矩阵：`dsh web -h`、`dsh --profile web --help` 透传、`dsh plugin` 缺参、parent 选项在子命令前被拒、`--patch ""` 拒绝、双 dump 互斥 — args.ts:83-103, 135-181；PY args.py 未接线（D2）且无这些钉测。

## PROBE 候选

- D8: 在运行中的 loop 里 `install_fail_loud("dsh")`（proc=None）后 `asyncio.create_task` 一个抛 RuntimeError 的后台任务——预期 TS 语义进程不退出；若 PY 版本 exit(1) 即证实 loop-handler 劫持过宽。另验证 uninstall 后 handler 是否还原（嵌套安装场景）。
- D10: 构造 `hmr.register_config` 刷新回调抛 message 含 "inactive" 的普通 ValueError，观察 `watch_user_patches` 是否返回 noop disposer（应 rethrow）。
- D7: `boot(..., bare_module_base_url=file://<dir>)` 加载一个不存在的裸包名——TS 应抛 internal loader 解析错误；PY 预期走"回退原名导入"分支，确认最终诊断与 TS 的差异面。
- D31/D5/D30: (a) `cordis.patch.yml` 只含注释行时 `load_profile` 是否 fail-loud；(b) manifest `patchReload: ""` 是否被 normalize 静默改写并写回磁盘；(c) 自制 `Command` 单参 action + operand 触发 `self._arguments` AttributeError。三者均为可直接运行裁决的探针。
- D12: 构造 config 替换 patch 重排某行键序（如插入后再覆盖使 id/name 位置变化），比较 PY 与 TS 的 `# ==` 标签是否少标 patch 层。
- T3: 在 Windows 上设 `DSH_HOME` 为含不同大小写/尾分隔符的 cwd 等价路径，验证 user 层跳过判定（normcase）与 TS `resolve(cwd)` 精确相等的行为边界。

（无遗漏：映射表已覆盖 TS 侧 app-boot/index.ts、cmdline/index.ts、profile.ts（经 index.ts:30-53 再导出）、apps/cli 四文件的全部顶层符号，以及 Python 侧 app_boot.py、cmdline.py、boot/profile.py、boot/__init__.py、harness.py 的全部顶层函数/类。）
