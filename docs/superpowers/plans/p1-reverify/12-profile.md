# G12-profile 盲审报告

审计范围：TS 权威源 = `reference/packages/boot/app-boot/src/profile.ts`、`reference/packages/util/home-paths/src/index.ts`、`reference/packages/util/launch-environment/src/index.ts`、`reference/packages/bundle/base/cordis.patch.yml`、`reference/packages/bundle/web-app/cordis.patch.yml`（均逐行通读）；Python 被审移植 = `dsh/cordis/profile.py`（415 行，任务书写 364 行，实读 415 行）、`dsh/cordis/environment.py`（291 行）。为裁决委托与组装管线，另通读了 `dsh/boot/profile.py`、`dsh/boot/app_boot.py`、`dsh/cordis/loader.py`、`reference/apps/cli/src/profile-boot.ts`、`reference/apps/cli/src/dump-config.ts`、`reference/packages/boot/app-boot/src/index.ts`、`reference/vendor/include/src/index.ts`、`reference/vendor/loader/src/config/{entry,utils}.ts`、`reference/packages/bundle/web-app/src/index.ts` 的相关段落作为引文证据。

**数据层基线事实**（后续差异判定依赖）：`packages/bundle/{base,web-app,headless,sdk-app,acp-app,sdk-minimal}/cordis.patch.yml` 与 `reference/packages/bundle/` 同名文件经 SHA-256 比对**全部逐字节相同**；base 手工清点为 **86 条 insert 行**（base yml:15 单一 `insert:` 块），web-app 手工清点为 **24 条 `disabled: true` 行**（web-app yml:313–425）外加 2 个 insert 块与 3 条 config 覆盖。Python 运行时数据由 `_load_builtin_bundles` 从这些文件读入（dsh/cordis/profile.py:89–111），故**文件在位时数据忠实**；偏差集中在文件缺失/损坏时的兜底与解析路径（D3）。

## 映射表

| TS 符号 (file:line) | Python 符号 (file:line) | 状态（1:1 / ADAPT / D#） |
|---|---|---|
| profile.ts:41 `PROFILES_DIR` | cordis/profile.py:247（内联 `"profiles"`；正典孪生 dsh/boot/profile.py:22 有常量） | D1 |
| profile.ts:44 `PROFILE_PATCH_FILENAME` | cordis/profile.py:19 | 1:1 |
| profile-boot.ts:87 `PROFILE_ROOT_FILENAME` | cordis/profile.py:18（**声明后从未使用**） | D8 |
| profile-boot.ts:77 `TELEMETRY_ROW_ID` | cordis/profile.py:20 | 1:1 |
| profile-boot.ts:69-71 `homePatchPath()` | cordis/profile.py:23-26 `home_patch_path` | 1:1（+ADAPT：多出可选 `dsh_home` 参数） |
| app-boot/index.ts:280 `loadOptionalPatches` | cordis/profile.py:30-51 `load_optional_patches`（委托 dsh/boot/app_boot.py:279） | D14 |
| app-boot/index.ts:300 `loadOverlayPatches` | cordis/profile.py:54-66 `load_overlay_patches`（委托 app_boot.py:293） | 1:1 |
| profile.ts:106 `Profile` | cordis/profile.py:69-86 `Profile` | D4（缺 `layers`/`patchReload`；正典孪生 boot/profile.py:95 完整） |
| —（无 TS 对应） | cordis/profile.py:89-193 `_load_builtin_bundles` / :197 `BUILTIN_BUNDLES` | D2, D3 |
| profile.ts:137-158 `PROFILE_TEMPLATES` | cordis/profile.py:200-236 `BUILTIN_PROFILES` | D4, D5 |
| profile.ts:161-163 `INSTALLATION_OWNED_PROFILE_TUPLES` | cordis/profile.py 无（正典孪生 boot/profile.py:65-67 有，未接cordis管线） | D4 |
| profile.ts:166/169 `DEFAULT_PROFILE_BUNDLES`/`DEFAULT_PROFILE_PATCH_RELOAD` | cordis/profile.py:274（硬编码）、无 patchReload 默认常量（boot/profile.py:26-27 有） | D4, D6 |
| profile.ts:197-217 `initProfile` | cordis/profile.py 无（boot/profile.py:635-662 有，未被cordis管线调用） | D6, D8 |
| profile.ts:127-134 `resolveProfileDir` | cordis/profile.py:243-247（内联等价校验）；boot/profile.py:620-632 为 1:1 | 1:1（内联） |
| profile.ts:805-844 `loadProfile` + profile-boot.ts:118-122 `prepareProfile` | cordis/profile.py:239-277 `prepare_profile` | D4, D5, D6, D7, D8 |
| profile.ts:685-699/706-708 `readProfileManifest`/`writeProfileManifest` | cordis/profile.py 无（boot/profile.py:665-689 有） | D6 |
| profile.ts:721-743 `normalizeShippedProfile`（+:711-713 `sameBundles`） | cordis/profile.py 无（boot/profile.py:692-717 有） | D4 |
| profile.ts:778-789 `resolveBundleDir`（+:753-764 `packageDirFromAnchor`） | cordis/profile.py 无（boot/profile.py:720-736/428-444 有） | D2 |
| profile.ts:497-532/579-592/608-677 模块 fallback 全族 | cordis/profile.py 无（boot/profile.py:447-617 有） | D9 |
| profile-boot.ts:124-143 `ComposedProfile`/`allPatches` | cordis/profile.py:280-301 `ComposedProfile`/`all_patches` | 1:1（四层顺序一致） |
| profile-boot.ts:100-103 `resolveTelemetryPatch` | cordis/profile.py:304-308 `resolve_telemetry_patch` | 1:1 |
| profile-boot.ts:156-173 `composeProfile` | cordis/profile.py:311-356 `compose_profile` | D2, D7, D9 |
| dump-config.ts:30-52 `runDumpConfig` + app-boot/index.ts:394-457 `renderConfigDump` | cordis/profile.py:359-373 `dump_config` | D7 |
| app-boot/index.ts:394-457 `renderConfigDump` | cordis/profile.py:376-389 `render_config_dump`（委托 app_boot.py:305-401，后者逐段对齐 TS） | D15 |
| web-app/src/index.ts:135-142 `resolveLanTrust` | cordis/profile.py:392-413 `resolve_lan_trust` | D19 |
| home-paths:70-74 `expandHomePath` | environment.py:13-19 `expand_home_path` | ADAPT（`os.path.expanduser("~")`≈`homedir()`；Py3.8 起 expanduser 优先 USERPROFILE，与 Node 一致） |
| home-paths:61-63 `defaultDshHome` | environment.py:34（内联） | 1:1（内联，ADAPT） |
| home-paths:87-91 `resolveDshHome` | environment.py:22-35 `resolve_dsh_home` | D11 |
| home-paths:33-55 `canonicalizeWatchPath` | **全仓缺失**（grep 无命中） | D20 |
| home-paths:98-100 `dshHomePath` | 无顶层函数；harness.py:82-88 以 `ctx.dshHomePath` 提供（对应 app-boot/index.ts:18+26） | ADAPT |
| home-paths:110-112 `dshHomeDisplay` | cordis/environment.py 无；dsh/context/agent_instructions/files.py:66 另有实现 | D20 |
| home-paths:12/15/18 `DSH_HOME_DIR_NAME`/`DEFAULT_DSH_HOME_DISPLAY`/`DSH_HOME_ENV` | environment.py 无常量（内联 `.dsh`/`"DSH_HOME"`） | D20 |
| launch-env:16/19 `LaunchEnvironmentSource`/`SOURCE_ORDER` | environment.py:165 `SOURCE_ORDER` | 1:1 |
| launch-env:22-29 `LaunchEnvironmentEntry` | environment.py:150-162 | 1:1 |
| launch-env:60-63 `lookupKey`（win32 折叠大写） | environment.py:183/194（`sys.platform == "win32"` 折叠） | 1:1（ADAPT 判据 `process.platform`→`sys.platform`） |
| launch-env:78-103 `createLaunchEnvironmentSnapshot` | environment.py:168-210 `LaunchEnvironmentSnapshot.__init__`/`get_from` | D13（其余 1:1） |
| launch-env:106 `DSH_LAUNCH_ENVIRONMENT_KEY='launchEnvironment'` | environment.py:213 `LAUNCH_ENVIRONMENT_KEY="launch_environment"` | D12 |
| launch-env:114-117 `launchEnvironmentOf` | environment.py:216-224 | D12 |
| app-boot/index.ts:96-131 `BOOTSTRAP_NAMES`/`PREFIXES`/`isBootstrapOnly` | environment.py:39-75（同名集合逐项比对：TS:96-117 与 PY:41-58 集合成员一致） | 1:1 |
| app-boot/index.ts:142-167 `readEnvLayer` | environment.py:227-233 `read_env_layer`（委托 app_boot.py:176-210） | 1:1 |
| app-boot/index.ts:11+157 `parseEnv`（node:util） | environment.py:78-147 `parse_dotenv` | D17（PROBE） |
| app-boot/index.ts:180-201 `loadLayeredEnv` | environment.py:236-248 `load_layered_env`（委托 app_boot.py:213-239） | D16, D18 |
| —（无 TS 对应） | environment.py:251-290 `resolve_layered_config` | D21 |

（"正典孪生" = `dsh/boot/profile.py`，其对 profile.ts 的函数级移植经逐段比对为忠实 1:1，但被审管线 `dsh/cordis/profile.py` 除 `compose_entries` 外不经过它，见 D1。）

## 差异

### D1: `dsh/cordis/profile.py` 组装管线为平行第二实现，不走正典 `dsh/boot/profile.py`
- TS: `reference/packages/boot/app-boot/src/profile.ts:805-844`
```ts
export function loadProfile(
  binName: string, name: string, installAnchor: string, home: string = resolveDshHome(),
  options: { userLayer?: boolean } = {},
): Profile {
  const dir = resolveProfileDir(name, home)
  if (!existsSync(join(dir, 'package.json'))) { ... initProfile(...) }
  const manifest = normalizeShippedProfile(name, dir, readProfileManifest(binName, dir))
```
- PY: `dsh/cordis/profile.py:239-277` 自建 `prepare_profile`（builtin 表 + 目录探测），仅 :344/:370 两处 `from dsh.boot.profile import compose_entries` 复用正典组装；`dsh/boot/profile.py` 头注自称 "Matching reference/packages/boot/app-boot/src/profile.ts 1:1"（boot/profile.py:3）但 `prepare_profile`/`compose_profile`/`dump_config` 的生产调用链（apps/cli/main.py:15,98-100）全部走本文件。正典侧 `load_profile`/`resolve_bundle_dir`/`normalize_shipped_profile`/`heal_*` 生产调用方为 0。
- 判定: MUST-FIX
- 影响: 下述 D2/D4/D6/D8/D9 全部根因于此；同一仓库内两条 profile 管线行为不一致。
- 建议修法: `prepare_profile`/`compose_profile`/`dump_config` 改为对 `dsh.boot.profile.load_profile`（传 `INSTALL_ANCHOR`）与 `heal_profiles_module_fallback` 的薄封装，`BUILTIN_PROFILES` 仅作为缺失 profile 目录时的模板名映射。

### D2: bundle 层解析静默跳过未知 bundle，且不读 `dsh.bundle` manifest 契约
- TS: `reference/packages/boot/app-boot/src/profile.ts:829-838`
```ts
const layers = bundles.map((packageName): ProfileLayer => {
  const packageDir = resolveBundleDir(binName, packageName, installAnchor, dir)
  const bundleManifest = JSON.parse(readFileSync(join(packageDir, 'package.json'), 'utf8')) as ProfileManifest
  const declared = bundleManifest.dsh?.bundle?.patch
  if (declared === undefined) {
    throw new Error(`${binName}: profile bundle ${JSON.stringify(packageName)} declares no dsh.bundle in its package.json`)
```
（`resolveBundleDir` profile.ts:785-788 对解析不到的 bundle 抛错，含 `run 'dsh plugin --profile ... install'` 提示。）
- PY: `dsh/cordis/profile.py:328-331`
```python
bundle_patches: List[Dict[str, Any]] = []
for bname in profile.bundles:
    if bname in BUILTIN_BUNDLES:
        bundle_patches.extend(copy.deepcopy(BUILTIN_BUNDLES[bname]))
```
未知 bundle 名既不报错也不产生任何层；也无"bundle 必须声明 patch 文件"的 fail-loud 契约。
- 判定: MUST-FIX
- 影响: 拼错的 bundle 名（如 `dsh-webap`）被静默丢弃，挂载树缺少整层，违反 TS "Misconfiguration fails loud"。
- 建议修法: `compose_profile` 循环内对 `bname not in BUILTIN_BUNDLES` 抛 `RuntimeError`，文案对齐 profile.ts:785-788。

### D3: bundle YAML 缺失/损坏时用硬编码有损兜底数据替代，解析宽松且不锚定相对插件名
- TS: `reference/packages/boot/app-boot/src/index.ts:300-307`
```ts
export function loadOverlayPatches(binName: string, file: string): PatchOptions[] {
  let content: string
  try {
    content = readFileSync(file, 'utf8')
  } catch (error) {
    throw new Error(`${binName}: failed to read overlay ${file}: ${String(error)}`)
  }
  return parsePatchList(binName, file, content, 'overlay')
```
TS 侧 bundle patch 文件缺失/不可解析一律 fail loud，且经 `parsePatchList`（index.ts:335-353）强校验"顶层 YAML 数组 + 每项为 mapping"并执行 `anchorInsertedPluginNames`（index.ts:311-321）。
- PY: `dsh/cordis/profile.py:102-111`
```python
try:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    parsed = yaml.safe_load(content)
    if isinstance(parsed, list):
        return parsed
except Exception as e:
    sys.stderr.write(f"warning: failed to read bundle patch {path}: {e}\n")
    return []
```
解析失败仅 stderr 警告并 `return []`（且不再尝试第二个候选目录，:99 的 `for b_dir in candidate_dirs` 被短路）；返回非 list 或文件缺失同样静默，随后 :120-177 启用**硬编码兜底**——base 兜底仅 18 条 insert（真实文件 86 条，缺 session-telemetry-otel、sandbox/permission、plan-mode、subagent 全族、web 全族、llm-deepseek 等），web-app 兜底仅 6 条 host 行（真实文件含 24 条 disabled + 浏览器 roster + webserver/web-runtime 配置全部缺失）；且 `_read_bundle_patch` 不做 `_parse_patch_list` 的形状校验、不执行 `_anchor_inserted_plugin_names`（当前六个 yml 无相对插件名，属潜伏缺陷）。
- 判定: MUST-FIX
- 影响: 损坏的 bundle 文件会静默产出与 TS 设计完全不同的挂载树（且 telemetry 行缺失使 `DSH_TELEMETRY_DISABLED` 开关失效）；TS 下同类故障直接拒绝启动。
- 建议修法: 删除 :120-177 兜底数据；`_read_bundle_patch` 改走 `dsh.boot.app_boot.load_overlay_patches(bin_name, path)`（其已含校验、fail-loud 与锚定），候选目录循环命中即抛。

### D4: `BUILTIN_PROFILES` 缺 `patchReload` 生命周期与 `normalizeShippedProfile` 归一化
- TS: `reference/packages/boot/app-boot/src/profile.ts:137-149`
```ts
export const PROFILE_TEMPLATES: Record<string, ProfileTemplate> = {
  acp: {
    bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-acp-app'],
    patchReload: 'startup',
  },
  web: {
    bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'],
    patchReload: 'live',
```
及 profile.ts:822-828（读取时校验 `patchReload ∈ {live,startup}`，缺省回落 `DEFAULT_PROFILE_PATCH_RELOAD`='live'）、profile.ts:721-743 `normalizeShippedProfile`（retired tuple `headless` 三元组归一 + 补写默认 patchReload 并回写 manifest）。
- PY: `dsh/cordis/profile.py:200-236` 每个 profile 只有 `bundles`/`patches` 两键，无 `patchReload`；:239-277 无任何 patchReload 校验或回落；无 retired-tuple（`INSTALLATION_OWNED_PROFILE_TUPLES`）归一化路径（该逻辑仅存在于未被调用的 boot/profile.py:65-67,692-717）。
- 判定: MUST-FIX
- 影响: web profile 的 live 热重载语义（profile-boot.ts:270-300 依赖 `patchReload === 'live'`）与 startup 档位在cordis管线中不可表达；用户手写 manifest 带非法 patchReload 不会被拒。
- 建议修法: `BUILTIN_PROFILES` 补 `"patchReload"` 键（web=live，其余=startup，与 TS 模板对齐）；`prepare_profile` 增加校验与 `'live'` 回落；接通 `normalize_shipped_profile`。

### D5: 自发明 `standard`/`minimal`/`creative` profile（TS 无此设计）
- TS: `reference/packages/boot/app-boot/src/profile.ts:137-158` — 模板仅 `acp/web/headless/sdk/sdk-minimal` 五个；`dump-config`/CLI 均无 "standard" 缺省 profile。
- PY: `dsh/cordis/profile.py:209-222`
```python
"standard": {
    "bundles": ["dsh-base", "dsh-headless"],
    "patches": [],
},
"minimal": {
    "bundles": ["dsh-sdk-minimal"],
    "patches": [],
},
"creative": {
    "bundles": ["dsh-base", "dsh-headless"],
    "patches": [
        {"insert": [{"id": "cordis-manager", "name": "@deepseek-ai/dsh-cordis-manager"}]}
    ],
},
```
且 `dump_config` 缺省 `profile_name="standard"`（:360），`BUILTIN_PROFILES` 的 `"patches"` 合成层（creative 的 cordis-manager insert，:256 深拷贝后并入 `profile.patches`）在 TS 的 Profile 模型中没有对应层——TS `profile.patches` 只装用户 `cordis.patch.yml`（profile.ts:839-842）。
- 判定: DEVIATION-PERMITTED（本仓 AGENTS.md 明确要求 Minimal/Standard/Creative 三预设与 creative 挂载 `@deepseek-ai/dsh-cordis-manager`；不在任务允许的两条偏离清单内，故记录在此）
- 影响: TS 侧以 preset 插件（`packages/preset/`）实现的能力在 Python 侧被折进 profile 名空间；creative 的合成 patch 层使 `Profile.patches` 语义与 TS 漂移（非纯用户层）。
- 建议修法: 保留三个名字但把它们实现为"模板→`init_profile` 写盘"而非内存合成层；cordis-manager insert 移入 `BUILTIN_BUNDLES` 注册的独立合成 bundle 键，使 `Profile.patches` 回归纯用户层。

### D6: 自定义 profile 分支忽略 `package.json` manifest，bundles 硬编码
- TS: `reference/packages/boot/app-boot/src/profile.ts:819-828`
```ts
const manifest = normalizeShippedProfile(name, dir, readProfileManifest(binName, dir))
// A hand-written profile manifest may omit the dsh section entirely.
const bundles = manifest.dsh?.profile?.bundles ?? []
const rawPatchReload: unknown = manifest.dsh?.profile?.patchReload
if (rawPatchReload !== undefined && rawPatchReload !== 'live' && rawPatchReload !== 'startup') {
  throw new Error(...)
```
缺失 manifest 时由 `PROFILE_TEMPLATES` 自动 `initProfile`（profile.ts:810-818）。
- PY: `dsh/cordis/profile.py:267-275`
```python
# Check for custom profile in $DSH_HOME/profiles/<name>
if os.path.isdir(profile_dir):
    return Profile(
        name=name,
        dir_path=profile_dir,
        patch_path=patch_file,
        patches=user_patches,
        bundles=["dsh-base"],
    )
```
从不读 `package.json`；`bundles` 恒为 `["dsh-base"]`；目录存在但无 manifest 不初始化；无 patchReload 校验。
- 判定: MUST-FIX
- 影响: 用户在自定义 profile 的 `dsh.profile.bundles` 中加的任何 bundle（如 sdk-minimal）永远不生效。
- 建议修法: `prepare_profile` 自定义分支改调 `dsh.boot.profile.load_profile(bin_name="dsh", name, install_anchor, home, {"userLayer": user_layer})`，缺失时按 `PROFILE_TEMPLATES`/`init_profile` 处理。

### D7: `dump_config` 与 TS `runDumpConfig`/`renderConfigDump` 行为与格式多重不一致
- TS: `reference/apps/cli/src/dump-config.ts:30-51`
```ts
export function runDumpConfig(profile: string, defaultOnly: boolean, patches: readonly string[]): void {
  const loaded = prepareProfile(profile, !defaultOnly)
  const layers: ConfigDumpLayer[] = loaded.layers.map(layer => ({
    label: layer.packageName,
    patches: layer.patches,
  }))
  if (!defaultOnly) {
    if (existsSync(loaded.patchPath)) {
      layers.push({ label: loaded.patchPath, patches: loaded.patches })
    }
    const homePatchFile = homePatchPath()
```
（渲染走 `renderConfigDump` → `# == 出处` 分组注释，app-boot/index.ts:459-488；`--dump-default-config` 跳过用户层，profile.ts:801-803 `userLayer: false`；dump 从不含 telemetry 开关 patch。）
- PY: `dsh/cordis/profile.py:359-373`
```python
composed = compose_profile(profile_name, patch_files=patch_files, dsh_home=dsh_home)
from dsh.boot.profile import compose_entries
final_entries = compose_entries([composed.bundle_patches, composed.profile.patches, composed.home_patches, composed.overlays])
return yaml.safe_dump(final_entries, sort_keys=False, allow_unicode=True)
```
差异逐条： (a) `compose_profile` 内部 :343-349 会在 `DSH_TELEMETRY_DISABLED` 非空时把 `{id: session-telemetry-otel, disabled: True}` 追加进 `overlays`，`dump_config` 复用该 `composed`，**dump 中混入了 TS dump 永不包含的 telemetry 开关 patch**（TS 只在 `runProfile` 的 `composedOverlays` 里加，dump-config.ts:32-48 的层列表无此物）； (b) 无 `defaultOnly`——`prepare_profile` 以 `user_layer=True`（:325 未传参）调用，用户层/home 层/overlay 全部进 dump，`--dump-default-config` 无法表达； (c) 无 `# ==` 来源/被改注释（TS groupedDump）； (d) 无逐 bundle 层 label（TS 以 `layer.packageName` 标层）； (e) 不锚定 profile 根 `cordis.yml`，也不初始化缺失的 profile 文件（TS `prepareProfile` 先 `loadProfile`（会 initProfile）再重写根文件，profile-boot.ts:118-122）。
- 判定: MUST-FIX（(a)(b)(e) 为行为不一致；(c)(d) 为输出格式不一致）
- 影响: dump ≠ TS 同名命令的产物；损坏用户层时 dump 不再是"恢复诊断"（TS 明确 default-only 是 broken cordis.patch.yml 的恢复路径，dump-config.ts:26-28）。
- 建议修法: `dump_config` 增加 `default_only` 参数并透传 `user_layer`；层结构改为 `[{label, patches}]` 复用 `dsh.boot.app_boot.render_config_dump`（其已 1:1 对齐 TS renderConfigDump）；把 telemetry 开关从 `compose_profile` 的共享 `overlays` 移到 boot 专用通道（或 dump 路径显式剔除）。

### D8: 不写 profile 根 `cordis.yml`（TS 每次启动/转储都强制重写空根）
- TS: `reference/apps/cli/src/profile-boot.ts:118-122`
```ts
export function prepareProfile(name: string, userLayer = true): Profile {
  const profile = loadProfile(NAME, name, INSTALL_ANCHOR, undefined, { userLayer })
  writeFileSync(join(profile.dir, PROFILE_ROOT_FILENAME), PROFILE_ROOT_CONFIG)
  return profile
```
（:107-113 注明：根文件必须每次重写，以防 Loader 写回把组合行固化、下次启动重复插入。）
- PY: `dsh/cordis/profile.py:18` 定义 `PROFILE_ROOT_FILENAME = "cordis.yml"` 后全文件无一处使用；`prepare_profile`/`compose_profile` 均不创建/重写根文件。
- 判定: MUST-FIX
- 影响: 若 Python 侧 include/Loader 具备配置写回（dsh/cordis/include.py:234/:260 有 `yaml.safe_dump(config_data, ...)` 写回路径），组合行可能被固化进根文件造成重复插入；且 dump/启动失去共同锚点文件。
- 建议修法: `prepare_profile` 末尾以 `PROFILE_ROOT_CONFIG`（profile-boot.ts:80-84 文本，`[]`）重写 `os.path.join(profile_dir, PROFILE_ROOT_FILENAME)`。

### D9: `compose_profile` 不调用 `healProfilesModuleFallback`
- TS: `reference/apps/cli/src/profile-boot.ts:156-164`
```ts
async function composeProfile(
  name: string,
  patchFiles: readonly string[],
): Promise<ComposedProfile> {
  const profile = prepareProfile(name)
  await healProfilesModuleFallback({ installAnchor: INSTALL_ANCHOR, profile })
```
- PY: `dsh/cordis/profile.py:311-356` 全函数无对应调用（正典实现在 boot/profile.py:599-617，未被cordis管线触达）。
- 判定: MUST-FIX
- 影响: bundle 携带的 profile-local 插件与安装依赖闭包不被投影，若后续按 TS 语义启用 out-of-tree 插件将静默缺依赖。（对当前纯内置 bundle 组合暂时无症状。）
- 建议修法: `compose_profile` 在 `prepare_profile` 后调用 `dsh.boot.profile.heal_profiles_module_fallback({"installAnchor": ..., "profile": ...})`（需先为 Python 侧定义 INSTALL_ANCHOR 等价物）。

### D10: `eval_condition` 自创宽松分支：裸字符串 `"!!js ..."`/含 `process.platform|process.env` 的裸串被求值
- TS: `reference/vendor/loader/src/config/entry.ts:104-108`
```ts
private disabledOf(options: EntryOptions): boolean {
  return isJsExpr(options.disabled)
    ? Boolean(this.evaluate(options.disabled.__jsExpr))
    : Boolean(options.disabled)
}
```
（`isJsExpr` = `value instanceof Object && '__jsExpr' in value`，utils.ts:25-27——只有 YAML `!!js` tag 产生的节点才走求值，其余一律 `Boolean()`。）
- PY: `dsh/cordis/loader.py:456-464`（被 `dsh/cordis/profile.py` 组装的行在挂载期使用）
```python
if is_js_expr(condition):
    return bool(evaluate_expr(ctx, condition["__jsExpr"]))
if isinstance(condition, str):
    cond_str = condition.strip()
    if cond_str.startswith("!!js"):
        return bool(evaluate_expr(ctx, cond_str[4:].strip()))
    if "process.platform" in cond_str or "sys.platform" in cond_str or "process.env" in cond_str:
        return bool(evaluate_expr(ctx, cond_str))
    return bool(cond_str)
```
- 判定: MUST-FIX
- 影响: `disabled: "!!js false"` 在 TS 下为 `Boolean("!!js false")=true`（行被禁用），Python 下求值为 false（行被启用）；`disabled: "process.platform === 'win32'"`（无 tag）同理反转。真值表整体偏离。
- 建议修法: 删除 loader.py:458-463 两个启发式分支，保留 `is_js_expr → evaluate else bool(condition)` 与 TS 完全同构（`if not condition: return False` 与 `Boolean()` 对空串/0 已等价，可留）。

### D11: `resolve_dsh_home` 对 `custom_home`/`DSH_HOME` 做 strip，且空串 `custom_home` 回落 env——TS 均非如此
- TS: `reference/packages/util/home-paths/src/index.ts:87-91`
```ts
export function resolveDshHome(configured?: string, env: Record<string, string | undefined> = process.env): string {
  const fromEnv = env[DSH_HOME_ENV]
  const selected = configured ?? (fromEnv !== undefined && fromEnv.trim().length > 0 ? fromEnv : defaultDshHome())
  return resolve(expandHomePath(selected))
}
```
要点：`configured` 用 `??`——**空串也是有效配置**（`resolve("")` = cwd）；env 只用 `trim()` 判空，**取值不 strip**（`DSH_HOME=" C:\\x "` 原样参与路径解析）。
- PY: `dsh/cordis/environment.py:26-32`
```python
if custom_home and isinstance(custom_home, str) and custom_home.strip():
    selected = custom_home.strip()
else:
    env_dict = env if isinstance(env, dict) else os.environ
    env_home = env_dict.get("DSH_HOME")
    if env_home and isinstance(env_home, str) and env_home.strip():
        selected = env_home.strip()
```
`custom_home=""`/全空白 → 落到 env 分支；env 命中后 `selected = env_home.strip()`。
- 判定: MUST-FIX（`~` 展开本身 1:1，expand/abspath 属允许偏离#2）
- 影响: 含首尾空白的 `$DSH_HOME` 两侧行为分叉；显式传空串 home 的调用方（测试/嵌入式）得到不同 home。
- 建议修法: 对齐 TS——`selected = custom_home if custom_home is not None else (env_home if (env_home is not None and env_home.strip()) else os.path.join(home, ".dsh"))`，除 env 判空外不做 strip。

### D12: Context 槽名 `launch_environment` ≠ TS `launchEnvironment`，且 fallback 多 `isinstance` 门
- TS: `reference/packages/util/launch-environment/src/index.ts:106,114-117`
```ts
export const DSH_LAUNCH_ENVIRONMENT_KEY = 'launchEnvironment'
export function launchEnvironmentOf(ctx: Context): LaunchEnvironmentSnapshot {
  return ctx.get(DSH_LAUNCH_ENVIRONMENT_KEY)
    ?? createLaunchEnvironmentSnapshot([{ source: 'process', values: process.env as Record<string, string> }])
```
（launcher 在任何 entry 挂载前 `hostCtx.provide(DSH_LAUNCH_ENVIRONMENT_KEY, ...)`，profile-boot.ts:255。）
- PY: `dsh/cordis/environment.py:213-224`
```python
LAUNCH_ENVIRONMENT_KEY: str = "launch_environment"
...
if hasattr(ctx, "get"):
    res = ctx.get(LAUNCH_ENVIRONMENT_KEY)
    if isinstance(res, LaunchEnvironmentSnapshot):
        return res
return LaunchEnvironmentSnapshot([{"source": "process", "values": dict(os.environ)}])
```
- 判定: MUST-FIX
- 影响: 任何按 TS 槽名提供/读取快照的移植插件彼此失配，静默退化为 process-only 层；`isinstance` 门会把合法的外来快照实现也吞掉。
- 建议修法: 常量改为 `"launchEnvironment"`；`isinstance` 门删除（保留 `res is not None` 判断即可）。

### D13: `get_from(name, [])` 返回全层搜索结果，TS 返回 undefined
- TS: `reference/packages/util/launch-environment/src/index.ts:88-97`
```ts
const getFrom = (name: string, sources: readonly LaunchEnvironmentSource[]): LaunchEnvironmentEntry | undefined => {
  const key = lookupKey(name)
  for (const source of SOURCE_ORDER) {
    if (!sources.includes(source)) continue
```
空 `sources` → 每层都 skip → `undefined`（"omitted layers are unreachable"，:51 契约）。
- PY: `dsh/cordis/environment.py:195`
```python
allowed = sources or SOURCE_ORDER
```
空列表经 `or` 落回全层，`get_from(name, [])` 等价 `get(name)`。
- 判定: MUST-FIX
- 影响: TS 消费方如 web-app 的 `launchedThroughSsh`（web-app/src/index.ts:89 `environment.getFrom(name, ['process'])`）所依赖的"屏蔽 .env 层"能力被破坏的边缘场景（显式传 `[]`）。
- 建议修法: `allowed = SOURCE_ORDER if sources is None else list(sources)`。

### D14: `load_optional_patches` 包装器改写错误文本，产生 TS 不存在的双重前缀
- TS: `reference/packages/boot/app-boot/src/index.ts:341-345`
```ts
} catch (error) {
  throw new Error(`${binName}: failed to parse ${label} ${file}: ${String(error)}`)
}
if (!Array.isArray(parsed)) {
  throw new Error(`${binName}: ${label} ${file} must be a top-level YAML array of loader patch entries`)
```
（label='patches' → `dsh: failed to parse patches <file>: ...`。）
- PY: `dsh/cordis/profile.py:44-51`
```python
except Exception as e:
    msg = str(e)
    if "failed to parse patches" in msg:
        from dsh.boot.app_boot import PatchParseError
        msg = msg.replace("failed to parse patches", "failed to read patches: failed to parse patches")
        raise PatchParseError(msg) from e
    raise
```
产出 `... failed to read patches: failed to parse patches ...` 双重前缀；TS 的 `failed to read patches` 只用于读取失败（index.ts:286）。
- 判定: MUST-FIX（诊断文本属可钉测面）
- 影响: 错误消息无法与 TS 对齐，依赖文案的测试/文档失配。
- 建议修法: 包装器直接 `return _boot_load_optional(bin_name, target_path) or []`，删除字符串改写（委托目标已抛 `PatchParseError`）。

### D15: `render_config_dump` 包装器预检的异常类型与文案均异于 TS
- TS: `reference/packages/boot/app-boot/src/index.ts:400-405`
```ts
let content: string
try {
  content = readFileSync(absoluteConfigPath, 'utf8')
} catch (error) {
  throw new Error(`${binName}: failed to read config ${absoluteConfigPath}: ${String(error)}`)
}
```
- PY: `dsh/cordis/profile.py:387-389`
```python
if not os.path.exists(base_config_path):
    raise FileNotFoundError(f"{bin_name}: failed to read config {base_config_path}: file not found")
return _boot_render(bin_name, base_config_path, layers, warn=warn_fn)
```
预检抛 `FileNotFoundError`（文案 "file not found"），而委托目标 app_boot.py:312-313 已抛 `ConfigFileNotFoundError`（文案对齐 TS）；包装器文案/类型双重漂移，且 TOCTOU（存在性检查 vs 打开失败）。
- 判定: MUST-FIX
- 影响: 调用方按 TS 文案/类型捕获会失败。
- 建议修法: 删除包装器预检，直接透传委托目标。

### D16: `load_layered_env` 的 home==cwd 去重用 `normcase`（TS 为精确字符串比较）
- TS: `reference/packages/boot/app-boot/src/index.ts:184-188`
```ts
const home = resolveDshHome()
const inherited = { ...process.env } as Record<string, string>
// Parse both layers first: a rejection must not leave one file applied.
const project = readEnvLayer(binName, cwd, warn)
const user = home === resolve(cwd) ? undefined : readEnvLayer(binName, home, warn)
```
- PY: `dsh/boot/app_boot.py:225`（`dsh/cordis/environment.py:236-248` 委托至此）
```python
user_layer = None if os.path.normcase(home_dir) == os.path.normcase(base_cwd) else _read_env_layer(bin_name, home_dir, warn)
```
- 判定: ADAPT（偏离清单第 2 条：Windows 路径大小写不敏感规范化；语义为去重同一 `.env` 被读两层，属等价改写）
- 影响: 仅在 home 与 cwd 仅大小写/分隔符不同时，Python 少读一次文件，行为更合理。
- 建议修法: 无需修改；在 `environment.py.load_layered_env` docstring 记录该 ADAPT。

### D17: `parse_dotenv` 为手写解析器，TS 用 `node:util.parseEnv`（引文以调用点为准）
- TS: `reference/packages/boot/app-boot/src/index.ts:11,156-157`
```ts
import { parseEnv } from 'node:util'
...
// Parse once so validation and materialization use exactly the same entries.
const values = parseEnv(content) as Record<string, string>
```
- PY: `dsh/cordis/environment.py:78-147`（多行双引号/单引号、`export ` 前缀 :94-95、`re.sub(r'\\([\\ntr"])', ...)` 转义 :123-124、未加引号行内注释 `re.split(r'\s+#', ...)` :144）——node:util.parseEnv 的确切边缘语义（行内注释是否剥离、`\` 转义集、export 前缀处理）无法仅凭本仓源码裁决。
- 判定: PROBE 候选（见下）；静态比对无法定案。
- 影响: `.env` 值逐字符差异可能只影响个别用户文件。
- 建议修法: 待探针结论后对齐；至少补齐行为差异清单。

### D18: 【相邻发现，越界记录】`dsh/boot/app_boot.py` 内部快照 `reversed(layers)` 使 user-env 优先于 process
- TS: `reference/packages/util/launch-environment/src/index.ts:19,88-97` `SOURCE_ORDER = ['process', 'project-env', 'user-env']`，`getFrom` 按 SOURCE_ORDER 迭代——**process 最可信**。
- PY: `dsh/boot/app_boot.py:130-137`
```python
def get(self, name: str) -> Optional[Dict[str, Any]]:
    for layer in reversed(self._layers):
        if name in layer["values"]:
```
层表构造顺序为 `[process, project-env, user-env]`（app_boot.py:233-237），`reversed` 后 user-env 最先命中——与 TS 及与 `dsh/cordis/environment.py:193-203`（正确按 SOURCE_ORDER）都相反。被审文件 `environment.py:247-248` 用 `LaunchEnvironmentSnapshot(boot_snapshot.layers)` 重包一层后优先级恢复正确，但任何直接消费 app_boot 快照的调用方拿到的是反优先级。
- 判定: MUST-FIX（超出本次被审两文件，故单列"相邻发现"）
- 影响: `get`/`getFrom` 对同名变量返回 user-env 值而非 process 值；且该内部类无 win32 键名折叠（environment.py:183 有）。
- 建议修法: app_boot.py:130-146 改为按 `SOURCE_ORDER = ["process", "project-env", "user-env"]` 迭代，或直接复用 `dsh.cordis.environment.LaunchEnvironmentSnapshot`。

### D19: `resolve_lan_trust` 触发集合、枚举方式、internal 过滤、去重均偏离 TS
- TS: `reference/packages/bundle/web-app/src/index.ts:83,135-142`
```ts
const ALL_INTERFACES_HOST = '0.0.0.0'
...
export function resolveLanTrust(bindHost: string, extra: readonly string[]): WebRuntimeValues {
  const lanAddresses = bindHost === ALL_INTERFACES_HOST
    ? Object.values(networkInterfaces()).flat()
      .filter((iface): iface is NonNullable<typeof iface> => iface !== undefined && iface.family === 'IPv4' && !iface.internal)
      .map(iface => iface.address)
    : []
  return { lanAddresses, trustedHosts: [...lanAddresses, ...extra] }
}
```
- PY: `dsh/cordis/profile.py:398-412`
```python
if bind_host in ("0.0.0.0", "::", ""):
    lan_addresses: List[str] = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and ip not in lan_addresses:
                lan_addresses.append(ip)
    except Exception:
        pass
```
四处偏离： 触发集合多了 `"::"` 与 `""`（TS 仅 `'0.0.0.0'`）； 枚举用 `gethostbyname_ex(hostname)` 而非网卡枚举（多宿主/多网卡 Win7 机器上结果集不同，且 IPv6 不入 TS 集、Python 端 `gethostbyname_ex` 只回 IPv4）； internal 过滤退化为 `startswith("127.")`（TS 的 `iface.internal` 覆盖更多内部接口）； Python 去重、TS 不去重。
- 判定: MUST-FIX（ TS 权威源中存在且可逐条对齐）
- 影响: LAN 信任围栏的地址集合在常见多网卡 Windows 主机上与 TS 不同——过宽（`::`/`""` 触发）或过窄（缺非主网卡地址）。
- 建议修法: 触发条件收敛为 `bind_host == "0.0.0.0"`；枚举改用能给出每接口 IPv4+internal 标志的 API（`socket.getaddrinfo(socket.gethostname(), None, AF_INET)` 无法给 internal，需 psutil 等价零依赖实现，Win7 可用 `GetAdaptersAddresses` via ctypes）；保留去重与否与 TS 对齐（TS 不去重）。

### D20: home-paths 侧符号缺失/移位
- TS: `reference/packages/util/home-paths/src/index.ts:33-55`
```ts
export async function canonicalizeWatchPath(path: string): Promise<string> {
  let current = resolve(path)
  const missing: string[] = []
  while (true) {
    try {
      const canonical = await realpath(current)
```
及 :12/15/18 常量 `DSH_HOME_DIR_NAME='.dsh'`、`DEFAULT_DSH_HOME_DISPLAY='~/.dsh'`、`DSH_HOME_ENV='DSH_HOME'`，:98-100 `dshHomePath`，:110-112 `dshHomeDisplay`（`resolvedHome === resolve(defaultDshHome()) ? '~/.dsh' : '$DSH_HOME'`）。
- PY: `dsh/cordis/environment.py` 无 `canonicalizeWatchPath`（全仓 grep 无命中）；常量未导出（`.dsh`/`"DSH_HOME"` 内联于 :34/:30）；`dshHomePath` 以 `ctx.dshHomePath` 形态存在于 dsh/harness.py:84-88 与 app_boot.py:703（等价 ADAPT）；`dsh_home_display` 在 dsh/context/agent_instructions/files.py:66（被审文件之外，未见逐行核对）。
- 判定: DEVIATION-PERMITTED（记录）：`dshHomePath`/`dshHomeDisplay` 已在别处以等价形态存在；`canonicalizeWatchPath` 为纯缺失——若 HMR/watch 插件启用将缺该规范化。
- 影响: watch 路径短名别名/不存在祖先的规范化缺失；用户可见展示串可能不走 `~/.dsh`。
- 建议修法: 在 `environment.py` 补 `dsh_home_display` 与同步 `canonicalize_watch_path`（用 `os.path.realpath` 逐级回退实现），并导出三个常量。

### D21: `resolve_layered_config` 无 TS 权威源对应（自发明五级配置链）
- TS: 给定五个权威文件中无任何对应实现（grep `resolve_layered|system_default` 于 reference 权威面无命中）。
- PY: `dsh/cordis/environment.py:251-290`
```python
val = system_default
# 2. Home Settings (~/.dsh/settings.yaml)
if ctx and hasattr(ctx, "has") and ctx.has("settings"):
    ...
# 5. CLI / Env (Highest precedence)
if cli_env_value is not None:
    val = cli_env_value
```
- 判定: DEVIATION-PERMITTED（记录）：无法与 TS 逐行核对，属自发明行为；命名参数 `preset_override`/`workspace_value` 优先级顺序无权威可依。
- 影响: 若 TS 侧存在同形能力，优先级顺序可能不同；当前仅能确认"无基准"。
- 建议修法: 在报告之外的正式审计中指认其 TS 对应物（疑在 settings/preset 域），或标注为 Python 特有 API 并在 docstring 去除 "matching" 措辞。

## 测试缺口

### T1: 未知/无 `dsh.bundle` 的 bundle 名必须 fail loud — profile.ts:833-835（引用见 D2）
缺失钉测：向 `BUILTIN_BUNDLES` 之外的名字（如 `"dsh-nope"`）组成 profile，断言抛错而非静默零层。

### T2: `patchReload` 校验与 `'live'` 回落 — profile.ts:823-828
```ts
if (rawPatchReload !== undefined && rawPatchReload !== 'live' && rawPatchReload !== 'startup') {
  throw new Error(... must be "live" or "startup" ...)
}
const patchReload = rawPatchReload ?? DEFAULT_PROFILE_PATCH_RELOAD
```
缺失钉测：manifest 写 `patchReload: "bogus"` 抛错；`dsh.profile.bundles` 为模板当前值但缺 `patchReload` 时归一化为模板值并回写（normalizeShippedProfile，profile.ts:721-743 + `INSTALLATION_OWNED_PROFILE_TUPLES` retired headless 三元组改写 profile.ts:161-163）。

### T3: `--dump-default-config` 只含 bundle 层、`--dump-config` 加用户/home/overlay 层、两者都不含 telemetry 开关 — dump-config.ts:30-52 + profile.ts:801-803
缺失钉测：设 `DSH_TELEMETRY_DISABLED=1` 后 dump，断言输出中不存在 `session-telemetry-otel` 的 disable-only 行；defaultOnly 时不解析损坏的 `cordis.patch.yml`（dump-config.ts:26-28 恢复诊断契约）。

### T4: dump 输出格式（`# == label[, patched by ...]` 分组注释与 `!!js` 原样）— app-boot/index.ts:459-488 + README 契约（以 renderConfigDump 源码为准）
缺失钉测：base+web+用户层覆盖同一 id（如 `tools`、`session-query-sqlite`）时，`# ==` 行应同时列 origin 与 patchedBy；`!!js` 表达式逐字保留不求值。

### T5: `resolveDshHome` 的空白与空串语义 — home-paths/index.ts:87-91（引用见 D11）
缺失钉测：`DSH_HOME="  "` → 默认 `~/.dsh`；`DSH_HOME=" C:\\x "` → 选中值**含空白**（Python 现状 strip 后通过，见 PROBE）；`configured=""` → `resolve("")`=cwd（TS 侧），Python 侧当前回落 env。

### T6: `getFrom` 省略层不可达 + win32 键名折叠 — launch-env/index.ts:51,60-63,88-97
缺失钉测：`getFrom("X", ["project-env"])` 在同名值存在于 process 与 project-env 时返回 project-env 值；`getFrom("X", [])` 返回 None（Python 现状返回全层最优，D13）；win32 下 `Process`/`PROCESS` 键折叠等价。

### T7: disabled 真值表 — vendor/loader/src/config/entry.ts:104-108（引用见 D10）
缺失钉测：`disabled: "false"`（裸串）→ 禁用；`disabled: "!!js false"`（若允许裸 tag 串）→ TS 禁用；`disabled: !!js process.platform === 'win32'` → 平台判定；空串/0 → 不禁用。

### T8: telemetry 开关任意非空值（含 `'0'`/`'false'`）禁用、无该行时不产生 patch — profile-boot.ts:100-103 + base yml:190
```ts
if ((disabledEnv ?? '') === '' || !hasRow) return undefined
return { id: TELEMETRY_ROW_ID, disabled: true }
```
缺失钉测：`DSH_TELEMETRY_DISABLED='0'` → 有行时插入 disable patch；组合不含 telemetry 行（如兜底数据场景）→ 不插入。

### T9: BUILTIN_BUNDLES 与 `packages/bundle/*.yml` 逐条一致（86 insert + 24 disabled）
缺失钉测：解析 `packages/bundle/base/cordis.patch.yml`（86 条）与 `web-app`（24 条 disabled + 2 个 insert 块），断言 `BUILTIN_BUNDLES["@deepseek-ai/dsh-base"]/["dsh-web-app"]` 与 `compose_entries` 组合产物逐一含相同 id 集与 `!!js`/disabled 值；并断言不存在硬编码兜底路径（D3）。

### T10: `.env` 分层物化去重与顺序 — app-boot/index.ts:184-195
```ts
const user = home === resolve(cwd) ? undefined : readEnvLayer(binName, home, warn)
for (const layer of [project, user]) { ... if (process.env[name] === undefined) process.env[name] = value }
```
缺失钉测：project 与 user 同名变量 → 物化取 project 值；process 已有该名 → 不覆盖；bootstrap-only 名（`DSH_*`、`PATH`）在两个文件中都抛 `BootstrapEnvError`（先解析后物化，两文件"要么都生效要么都不生效"）。

## PROBE 候选

- **D17（parse_dotenv ↔ node:util.parseEnv）**：构造 `.env` 用例集逐行对比：(1) `KEY=value # comment`（行内注释是否剥离——Python 剥离 `\s+#`，node 实现待证）；(2) 双引号跨行值含 `\"` 与 `\n` 转义；(3) 单引号跨行；(4) `export KEY=v` 前缀；(5) `KEY=`（空值）；(6) 值内 `#` 无前导空格（`v#x`）；(7) CRLF 行尾。在 Node 22 与 Python 3.8.10 各跑一遍 diff 全部解析结果。理由：node:util 源码不在仓内，静态裁决不可行。
- **D11（含空白/空白的 DSH_HOME）**：`DSH_HOME=" D:\\tmp "` 与 `DSH_HOME=""` 两种环境分别在 TS（Node，`resolveDshHome()`）与 Python（`resolve_dsh_home()`）下打印最终 home。理由：裁决 TS `resolve(" D:\\x ")` 对空白路径的实际行为（是否抛错/如何解析）与 Python `os.path.abspath` 的差异，决定 strip 是"修复"还是"偏离"。
- **D19（多宿主主机 LAN 地址集）**：在 ≥2 块网卡（含一块仅内部/未联网）的 Windows 主机上，分别运行 TS `resolveLanTrust('0.0.0.0', [])` 与 Python `resolve_lan_trust("0.0.0.0", [])`，对比地址集。理由：`gethostbyname_ex` 与 `networkInterfaces()` 的结果差异是环境依赖的，静态不可判定；同时裁决 `"::"`/`""` 触发扩展是否被现网依赖。
- **D3（损坏 bundle yml 的端到端行为）**：临时目录内破坏 `packages/bundle/base/cordis.patch.yml` 语法后分别执行 TS `dsh --profile headless --dump-default-config` 与 Python `dump_config("headless")`。理由：用运行结果钉死"TS fail-loud vs Python 兜底 18 行"的差异输出，供修复后回归对照。（可选：静态分析已能定案，此探针用于量化影响面。）
