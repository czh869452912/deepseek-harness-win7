# dsh/harness.py ↔ reference/packages/boot/app-boot/src/index.ts (+ bundle/base)

Comparison snapshot: TS `dsh-v0.1.2-alpha.1` (git submodule `reference/`). Authority: TS sources.
Scope: assembly contract of `boot()`/`loadLayeredEnv()`/dump glue vs `build_harness()`, plus what
`bundle/base/cordis.patch.yml` mounts unconditionally and what `bundle/web-app` / `bundle/headless`
layer on top. CLI arg parsing parity and Web GUI endpoints (P4) are out of scope per task rules.

Notes on the TS side used below:
- `bundle/base/src/index.ts` carries no runtime API (`export {}`); the package's substance is its
  `cordis.patch.yml`, applied as ONE insert over the profile root. Row order carries no load
  semantics ("activation is service-availability driven").
- `bundle/headless` layers a one-shot driver (reasoning→stderr, result→stdout) and no Host/HTTP rows.
- `bundle/web-app` layers host rows (webserver, modules, connection, controllers, pickers, inventory),
  a `web-runtime` glue plugin (frontend-static, URL line, browser handoff, LAN trust), and disables
  the base agent-plane rows (tools/skills/delegation/compaction) behind per-session agent presets.

## 差异清单

### D1 [MUST-FIX] Missing preset file is silently skipped instead of failing loud
- 位置: py:dsh/harness.py:170-172 vs ts:packages/bundle/base/cordis.patch.yml:1-4 + ts:packages/boot/app-boot/src/index.ts:772-818
- 原版行为: The TS bin resolves the config path and boots the Include against it; an unreadable or
  missing config fails the boot. The repo rule is explicit ("Misconfiguration fails loud at load …
  never silently skip a missing referent"), and `loadOptionalPatches`' contract states the policy:
  ```ts
  // A missing file means "no layer"; an unreadable, unparsable, or non-array file throws —
  // a present patch file that cannot apply is a misconfiguration and must fail
  // loud at boot, never be silently skipped.
  ```
  For the base bundle every profile row is mounted unconditionally; nothing in the TS boot path
  tolerates a missing composition.
- 移植版现状:
  ```python
  preset_file = os.path.join("dsh", "presets", f"{mode}.yaml")
  if os.path.exists(preset_file):
      loader.load_preset_file(preset_file, ctx)
  ```
  A typo'd/missing mode (`build_harness(mode="standrad")`) silently returns a context with base infra
  plugins only — no persona, no fs, no tools — and the CLI REPL then crashes later on
  `ctx.get("agent_loop")` or runs a tool-less agent. `load_preset_file` itself already raises
  `FileNotFoundError` (dsh/cordis/loader.py:1289-1290); the `exists` guard discards that signal.
- 修复方案: Remove the `os.path.exists` guard (or raise a labelled error like
  `dsh: failed to read preset dsh/presets/<mode>.yaml`), letting `load_preset_file`'s
  `FileNotFoundError` propagate so a bad mode name fails at boot, matching TS fail-loud semantics.

### D2 [MUST-FIX] `patch_file` parameter is accepted but never applied (user patch layers dead in live boot)
- 位置: py:dsh/harness.py:69 (param), whole body has no reference; caller apps/cli/main.py:107 vs ts:packages/boot/app-boot/src/index.ts:501-544 (mountRootInclude applies `patches`), 300-308 (loadOverlayPatches throws when the named overlay is missing)
- 原版行为:
  ```ts
  export async function boot(
    binName: string,
    absoluteConfigPath: string,
    patches?: PatchOptions[],
    ...
  ```
  and the `--patch` overlay loader:
  ```ts
  export function loadOverlayPatches(binName: string, file: string): PatchOptions[] {
    let content: string
    try { content = readFileSync(file, 'utf8') } catch (error) {
      throw new Error(`${binName}: failed to read overlay ${file}: ${String(error)}`)
    }
  ```
  Patches compose as one flattened list applied over the included tree; a named-but-missing overlay
  is a hard boot failure.
- 移植版现状:
  ```python
  def build_harness(
      ...
      patch_file: Optional[str] = None,
  ```
  `patch_file` never appears again in harness.py. `apps/cli/main.py:107` passes
  `patch_file=args.patch`, so `dsh --patch overlay.yml` boots with the overlay silently ignored.
  The faithful loader `load_overlay_patches` (dsh/cordis/profile.py:65-70, raises
  `FileNotFoundError`) and `load_preset_file(..., patches=...)` (dsh/cordis/loader.py:1280-1296)
  both exist but are not wired into the live path; `$DSH_HOME/cordis.patch.yml` (the user layer) is
  likewise only consulted by `--dump-config`, never by boot.
- 修复方案: In `build_harness`, when `patch_file` is set, load it via
  `dsh.cordis.profile.load_overlay_patches(patch_file)` (fail loud on missing) and pass the list as
  `patches=` to `loader.load_preset_file(preset_file, ctx)`; optionally also apply the
  `$DSH_HOME/cordis.patch.yml` user layer via `load_optional_patches` before the overlay, mirroring
  the TS bundle→user→overlay composition order.

### D3 [MUST-FIX] No fail-loud boot audit: unresolved preset plugins only warn, partial context is not disposed, no stage labels
- 位置: py:dsh/harness.py:172 (returns ctx without audit) + dsh/cordis/loader.py:1273-1277 vs ts:packages/boot/app-boot/src/index.ts:673-679 (assertEntriesLoaded), 707-740 (assertEntriesActivated), 801-818 (dispose + labelled stage)
- 原版行为:
  ```ts
  const failed = [...ctx.loader.entries()].filter(entry => entry.fiber === undefined && !entry.disabled)
  if (failed.length > 0) {
    const names = failed.map(entry => entry.options.name).join(', ')
    throw new Error(`${binName}: plugin(s) failed to load: ${names}; Cordis startup failed ...`)
  }
  ```
  and on any boot failure the partial tree is torn down first:
  ```ts
  } catch (cause) {
    await ctx.fiber.dispose()
    ...
    throw new Error(`${binName}: ${stage}: ${detail}${stack}`, { cause })
  ```
  with `stage` = `'host preparation failed'` before any config-tree entry mounts, else
  `'plugin tree failed to load'`.
- 移植版现状: `build_harness` has no try/except and no post-load audit. A preset row whose `name`
  cannot be resolved only logs and continues:
  ```python
  else:
      if ctx and hasattr(ctx, "logger"):
          ctx.logger("loader").warn("Unknown plugin name/id: '%s'", plugin_name)
      else:
          sys.stderr.write(f"[Cordis Loader Warning] Unknown plugin name/id: '{plugin_name}'\n")
  ```
  A preset referencing an unregistered plugin name boots "successfully" with that plugin (and every
  tool/service it would provide) silently absent — exactly the failure class TS refuses to boot with.
- 修复方案: After `load_preset_file` returns, audit the loader store/entries: any entry whose plugin
  class failed to resolve or whose fiber ended failed/pending (not `disabled`) must raise a labelled
  error listing the entry names (`dsh: N entries did not activate: ...`). Wrap the assembly body in
  try/except that disposes the context (`ctx.teardown()` / fiber dispose) before re-raising
  `dsh: plugin tree failed to load: <detail>`.

### D4 [MUST-FIX] No `dshHomePath` provider for `!!js` config expressions; expression failures silently degrade to the raw string
- 位置: py:dsh/harness.py:78-80 vs ts:packages/boot/app-boot/src/index.ts:784-785; consumers ts:packages/bundle/base/cordis.patch.yml:110-113, 148-151 and ts:packages/bundle/sdk-minimal/cordis.patch.yml:114-117
- 原版行为:
  ```ts
  ctx.baseUrl = pathToFileURL(dirname(absoluteConfigPath)).href + '/'
  ctx.provide('dshHomePath', dshHomePath)
  ```
  Base rows rely on it at boot:
  ```yaml
  - id: session-persistence-jsonl
    name: '@deepseek-ai/dsh-session-persistence-jsonl'
    config:
      root: !!js dshHomePath('sessions')
  ```
  (`storage-json` root uses `dshHomePath('storages')`; even the standalone sdk-minimal tree uses
  `dshHomePath('sessions')`.)
- 移植版现状:
  ```python
  ctx = Context()
  launch_env = load_layered_env(cwd=os.getcwd())
  ctx.set_service("launch_environment", launch_env)
  ```
  No `dshHomePath` equivalent is provided, and the expression evaluator's scope
  (dsh/cordis/loader.py:299-314) has no such callable. `evaluate_expr` swallows the failure:
  ```python
  except Exception as e:
      ...
      return expr
  ```
  so any preset/config row using `dshHomePath(...)` receives the literal string
  `"dshHomePath('sessions')"` as its config value with no error — a silent misconfiguration.
- 修复方案: Register a `dsh_home_path` callable (delegating to
  `dsh.cordis.environment.resolve_dsh_home`) into the evaluator scope in `build_harness` (or provide
  it as a ctx service the evaluator reads), and make `evaluate_expr` fail loud (or at minimum log an
  error) instead of returning the raw expression string on evaluation failure.

### D5 [MUST-FIX] `--dump-config` composes a different tree than the live boot and omits provenance comments / skipped-patch warnings
- 位置: py:dsh/harness.py (boot composition) vs apps/cli/main.py:95-98 → dsh/cordis/profile.py:318-336 vs ts:packages/boot/app-boot/src/index.ts:394-457 (renderConfigDump)
- 原版行为:
  ```ts
  * Compose the effective entry list exactly as `boot()` would mount it: parse
  * the base config file with the include's entry-list dialect, apply every
  * layer's patches as ONE flattened list through the include's own patch
  * algorithm (`applyEntryPatches`) — the same single call `boot()` makes ...
  ```
  Output groups rows under `# == <file>[, patched by <layers>]` comments and warns per layer when a
  patch matches no row.
- 移植版现状: The CLI dump path is
  ```python
  final_entries = apply_entry_patches(initial_entries, [*composed.profile.patches, *composed.home_patches, *composed.overlays])
  sorted_entries = [sort_keys(dict(e)) for e in final_entries]
  return yaml.safe_dump(sorted_entries, sort_keys=False, allow_unicode=True)
  ```
  where `initial_entries` is the static `BUILTIN_BUNDLES["dsh-base"]` row list (profile.py:95-132) —
  a composition the live boot never mounts (boot mounts harness.py's `ctx.plugin(...)` set plus the
  `dsh/presets/<mode>.yaml` rows, which contain rows like `persona`, `fs-local`,
  `str-replace-editor` that the dump lists with different config, and rows the dump omits). The
  faithful `render_config_dump` (profile.py:339-414, with provenance comments) is dead code on the
  CLI path, and skipped-patch warnings are dropped (`apply_entry_patches` default warn goes to
  stderr only when `warn=None`, and dump passes none deliberately).
- 修复方案: Make `dump_config` derive its base rows from the same source boot uses (harness base
  mounts + `dsh/presets/<mode>.yaml`), apply the same flattened patch layers through one
  `apply_entry_patches` call, and render via `render_config_dump` so `# ==` provenance comments and
  per-layer skipped-patch warnings appear. Alternatively wire `--dump-config` to
  `render_config_dump` with a boot-equivalent base file.

### D6 [MUST-FIX] `SessionQueryPlugin` mounted without base's dormant `openAt: never` contract (eager SQLite + live search tools in every non-minimal mode)
- 位置: py:dsh/harness.py:93-94 vs ts:packages/bundle/base/cordis.patch.yml:121-134
- 原版行为:
  ```yaml
  # Full-text session search is opt-in. `openAt: never` keeps
  # ctx.sessionQuery mounted — exact reads, titles, and lineage traces
  # (session export, subagent-fork Workspace inheritance) stay available —
  # while search calls fail with SESSION_QUERY_SEARCH_DISABLED and SQLite is
  # never opened; ...
  - id: session-query-sqlite
    config:
      path: ':memory:'
      openAt: never
  ```
  Mounted dormant in every base-backed profile; deployments opt into search by overriding `openAt`
  in a later patch layer.
- 移植版现状:
  ```python
  if mode != "minimal":
      ctx.plugin(SessionQueryPlugin)
  ```
  Mounted with no config; the plugin opens SQLite at mount and registers `session_search` /
  `session_event_search` unconditionally (dsh/session/session_query.py:435-438, 646-653). The
  opt-in search contract (search disabled by default, SQLite never opened until enabled) does not
  exist at the assembly level — the harness would need to pass the dormant config for the default
  composition to match base.
- 修复方案: Mount with the base defaults, e.g.
  `ctx.plugin(SessionQueryPlugin, config={"path": ":memory:", "open_at": "never"})`, and have the
  plugin honor `open_at` (defer connect, fail search calls with a disabled error) — the plugin-side
  `open_at` support may already be tracked by the session-query report; the harness-side gap is the
  missing dormant config.

### D7 [ADAPT] CliVisualizerPlugin is a port-only surface with no TS counterpart
- 位置: py:dsh/harness.py:97-98 vs ts:packages/bundle/headless/cordis.patch.yml:17-30 (headless layers a runner, no visualizer)
- 原版行为: No TS base/profile bundle mounts a CLI visualizer; the headless bundle streams provider
  reasoning to stderr and the final text to stdout through `headless-runner` itself.
- 移植版现状:
  ```python
  if verbose:
      ctx.plugin(CliVisualizerPlugin, config={"verbose": True})
  ```
- 修复方案: Port-only surface — keep, but note two inconsistencies: (1) `verbose=True` is the
  default in `build_harness`, so the visualizer is on unless callers opt out, and (2)
  `BUILTIN_BUNDLES["dsh-headless"]` (dsh/cordis/profile.py:141-143) also lists `cli-visualizer`,
  diverging from the TS headless patch's row set (see D5 for the dump-side consequences).

### D8 [ADAPT] Web profile: host-row set matches; mount order non-semantic; agent-plane-behind-presets restructure deferred
- 位置: py:dsh/harness.py:162-168 vs ts:packages/bundle/web-app/cordis.patch.yml:43-165 (host insert), 296-438 (agent-plane disables + agent presets)
- 原版行为:
  ```yaml
  - id: webserver
    name: '@deepseek-ai/dsh-host-webserver'
    inject: [webStartup]
    config:
      host: !!js ctx.webStartup.host ?? '127.0.0.1'
      port: !!js ctx.webStartup.port ?? 3080
  ```
  The web bundle additionally disables every base agent-plane row (`tool-bash`, `tool-pwsh`,
  `tool-jobs`, `tool-fs`, `tool-fs-search`, `tool-str-replace-editor`, `skill-filesystem`,
  `tool-skill`, `command-goal`, `tool-goal`, `plan-mode`, `compaction-basic`, `command-compact`,
  `tool-result-pruner`, `tool-subagent*`, `workflow*`, `tool-ralph`, `agent-instructions`,
  `tool-todo`, `tool-web`) and mounts `agent-presets` (default `standard`) so each Web session
  mounts a preset; the `web-runtime` glue waits for Loader settlement before printing the
  authenticated URL and opening the browser.
- 移植版现状:
  ```python
  if enable_web:
      ctx.plugin(WebServerPlugin, config={"host": web_host, "port": web_port})
      ctx.plugin(ClientModulesPlugin)
      ctx.plugin(PluginInventoryPlugin)
      ctx.plugin(DirectoryPickerAutoPlugin)
      ctx.plugin(ApiProxyPlugin)
      ctx.plugin(FrontendStaticPlugin)
  ```
  The same six host-side capabilities are mounted (server, client modules, inventory, directory
  picker, api proxy, frontend static). Differences: (a) webserver config comes from CLI args at
  mount instead of a `webStartup` service — equivalent outcome, different mechanism; (b) the
  agent-plane disabling + per-session preset mounting is not implemented — the port keeps preset
  tools mounted process-wide (single-host design; per-session presets are the P4 Web session work);
  (c) URL announce/browser-open happen in apps/cli/main.py:127-139 immediately after
  `web_server.start()`, printing a plain `http://host:port` URL rather than awaiting full tree
  settlement and printing an authenticated, LAN-aware URL. Row-order differences are not behavioral
  (base: "Row order carries no load semantics").
- 修复方案: Keep as ADAPT for P1; when P4 lands, move URL announce/browser-open behind full
  settlement, add the trust fence (`resolve_lan_trust` already exists in profile.py but is not
  wired into the webserver mount), and gate the agent-plane rows per session.

### D9 [ADAPT] Layered env bootstrap is a faithful port (documented parity)
- 位置: py:dsh/harness.py:79-80 → dsh/cordis/environment.py:184-219 vs ts:packages/boot/app-boot/src/index.ts:180-201
- 原版行为:
  ```ts
  // Parse both layers first: a rejection must not leave one file applied.
  const project = readEnvLayer(binName, cwd, warn)
  const user = home === resolve(cwd) ? undefined : readEnvLayer(binName, home, warn)
  // Apply the checked values without replacing a higher-ranked name.
  if (process.env[name] === undefined) process.env[name] = value
  ```
- 移植版现状: `load_layered_env` matches contract: home resolved before either read (environment.py:195-196), both layers parsed before either applied (:201-204), bootstrap-only names raise before materialization (:173-179, same message text), values applied only when unset (:207-211), snapshot carries process/project-env/user-env layers (:213-217), non-ENOENT read failure warns and treats the file as absent (:168-170). `build_harness` calls it before any plugin mount, matching the TS ordering (env bootstrap precedes boot).
- 修复方案: None — equivalent. Note only: the snapshot is stored as service `"launch_environment"`; TS additionally provides `dshHomePath` on the ctx (covered by D4).

### D10 [ADAPT] LLM credentials/model are frozen into the plugin config at mount instead of resolving per request from settings/credential services
- 位置: py:dsh/harness.py:100-104 vs ts:packages/bundle/base/cordis.patch.yml:496-501
- 原版行为:
  ```yaml
  # The native DeepSeek adapter. No key or endpoint is inlined: both resolve per
  # request from the `llm-deepseek:` settings section over this entry, with the
  # key coming from the credential store below.
  - id: llm-deepseek
    name: '@deepseek-ai/dsh-llm-deepseek'
  ```
  Base's `settings` row documents that a `llm-deepseek:` settings section overrides adapter
  entries "without a restart" (cordis.patch.yml:87-89).
- 移植版现状:
  ```python
  ctx.plugin(LLMOpenAIPlugin, config={
      "api_key": api_key,
      "base_url": base_url,
      "model": model,
  })
  ```
  CLI values are materialized at mount; per-request settings/credential precedence is delegated to
  the plugin's internal resolution (env `DEEPSEEK_API_KEY`/`OPENAI_*` per AGENTS.md). Net behavior
  is equivalent for the default deployment; the hot-reload precedence difference is plugin-level,
  not assembly.
- 修复方案: None for P1 assembly; if settings hot-reload parity is required later, pass
  references (env names/settings keys) rather than resolved values at the mount site.

### D11 [SKIP] Snapshot-aware config path resolution (`DSH_SNAPSHOT=replay`)
- 位置: py:dsh/harness.py (absent) vs ts:packages/boot/app-boot/src/index.ts:64-72
- 原版行为:
  ```ts
  export function resolveConfigPath(
    configPath: string, snapshotMode: string | undefined, cwd: string = process.cwd(),
  ): string {
    const absolute = resolve(cwd, configPath)
    if (snapshotMode !== 'replay') return absolute
    const dir = dirname(absolute)
    const replayName = basename(absolute).replace(/cordis\.ya?ml$/, 'cordis.snapshot.yml')
    return resolve(dir, replayName)
  }
  ```
- 移植版现状: No counterpart anywhere in the port.
- 修复方案: SKIP — the recorded-session snapshot/replay pipeline (`test:snapshot`, keyless replay
  through shipped profiles) does not exist in the port; this is a bin/CLI-level feature of the
  deferred subset, not an assembly divergence within the implemented glue. Revisit if/when the
  snapshot harness is ported.

### D12 [SKIP] `installFailLoud` late-failure process guard and HMR user-patch watching
- 位置: py:dsh/harness.py (absent) vs ts:packages/boot/app-boot/src/index.ts:624-664 (installFailLoud), 235-267 (watchUserPatches)
- 原版行为:
  ```ts
  proc.stderr.write(`${binName}: fatal load failure: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`)
  ...
  proc.exit(1)
  ```
  One labelled diagnostic + `exit(1)` on late unhandled rejections, with a terminal-release hook
  bounded by `FAIL_LOUD_RELEASE_TIMEOUT_MS = 2_000`; `watchUserPatches` transactionally reapplies
  `$HOME`-layer patches through Cordis HMR.
- 移植版现状: No counterpart. Boot-window error handling is covered by D3; these two guards govern
  post-boot life.
- 修复方案: SKIP — (a) the Cordis HMR service does not exist in the port (the TS base row itself
  ships `disabled: true`; module reload is opt-in per profile), so user-patch watching has no
  substrate; (b) the late-failure process guard is a bin-layer concern (apps/cli) in a port whose
  asyncio runtime surfaces task exceptions differently, and Python has no `unhandledRejection`
  equivalent with the same terminal-ownership semantics (raw mode/bracketed paste are not used).
  Revisit the exit-code contract under CLI parity work.

## 测试缺口

Existing coverage: `tests/test_harness.py` (2 cases: minimal & creative happy paths — plugin ids +
tool names only), `tests/test_cli_args_and_shutdown_parity.py` + `tests/test_cli_args_full_specs.py`
(argparse only, no build_harness), `tests/test_profile_boot_and_bundles.py` +
`tests/test_profile_and_boot_specs.py` (profile/dump/patch composition offline only),
`tests/test_host_1to1_modules.py` (web-mode plugin inventory RPC), `tests/test_presets_alignment.py`
(tool surface per mode). No test exercises boot failure paths, patch application in the live boot,
expression scope, or dump↔boot equivalence.

### T1 Missing preset file must fail loud (D1)
`test_build_harness_missing_preset_fails_loud` — `build_harness(mode="nonexistent-mode")` raises
(FileNotFoundError or labelled boot error); assert no silently-reduced context is returned.

### T2 `--patch` overlay applies to the booted preset (D2)
`test_build_harness_applies_patch_overlay` — write a temp overlay
(`[{"id": "str-replace-editor", "config": {"maxOutputChars": 99}}]`), call
`build_harness(mode="minimal", patch_file=...)`, assert the mounted `str-replace-editor` plugin
config reflects the overlay; and `test_build_harness_missing_patch_file_fails_loud` — missing
overlay path raises instead of being ignored.

### T3 User home patch layer applies at boot (D2)
`test_build_harness_applies_user_home_patch_layer` — with `DSH_HOME` pointed at a temp dir
containing `cordis.patch.yml`, assert the boot honors the user row (e.g. disable a preset row) and
that overlay patches win over user rows.

### T4 Boot fails loud on unresolved preset plugin names (D3)
`test_build_harness_fails_loud_on_unresolved_preset_plugin` — temp preset yaml containing
`{"id": "x", "name": "@deepseek-ai/does-not-exist"}` loaded through `PresetLoader` /
`build_harness` path raises an error naming the entry instead of warn-and-continue.

### T5 Boot failure disposes the partial context with a stage label (D3)
`test_build_harness_boot_failure_labels_and_disposes` — make a late preset row fail (e.g. a plugin
whose `apply` raises or an unresolvable inject), assert the raised error message contains the
`plugin tree failed to load` stage label and that effects/child contexts registered before the
failure were torn down (no leaked services on the returned/raised context).

### T6 `dshHomePath` resolves in preset `!!js` expressions (D4)
`test_preset_dsh_home_path_expression_resolves` — with `DSH_HOME` set to a temp dir, load a preset
row with `config: {root: "!!js dshHomePath('sessions')"}` through the harness path and assert the
mounted config value equals `os.path.join(home, "sessions")` (not the literal expression string);
plus `test_expr_evaluation_failure_fails_loud` for the non-silent fallback.

### T7 `--dump-config` matches the booted composition (D5)
`test_dump_config_matches_booted_composition` — for each mode, boot `build_harness(mode=...)` and
`dump_config(mode)`; assert every mounted plugin id appears as a dump row and every dump row maps
to a mounted plugin (or is a registered-but-disabled row), so the dump is the tree boot would mount.

### T8 Dump renders provenance comments and skipped-patch warnings (D5)
`test_dump_config_renders_provenance_and_patch_warnings` — dump with a patch layer that overrides a
row and a patch that matches nothing; assert `# ==` group comments name the source and
`patched by` layers, and the unmatched patch produces a warning line naming its layer.

### T9 Session query mounts dormant in default compositions (D6)
`test_build_harness_session_query_mounted_dormant` — `build_harness(mode="standard")` mounts
session-query with the dormant defaults (`path=":memory:"`, open mode `never`); search calls fail
with a disabled error and no SQLite file/handle is opened until enabled, while exact reads/titles
stay available.
