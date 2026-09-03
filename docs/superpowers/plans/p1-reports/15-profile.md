# dsh/cordis/profile.py ↔ reference/packages/boot/app-boot/src/profile.ts (808)

对照基线补充：profile.py 的遥测开关与 4 层级联同时对应 `reference/apps/cli/src/profile-boot.ts`（`resolveTelemetryPatch`/`composeProfile`，第 77-173 行）、dump 对应 `reference/apps/cli/src/dump-config.ts` 与 `reference/packages/boot/app-boot/src/index.ts` 的 `renderConfigDump`；bundle 的组装角色来自 `reference/packages/bundle/base/src/index.ts`（无运行时代码，实体是其 `cordis.patch.yml`）。

## 差异清单

### D1 [MUST-FIX] 未知 profile 名静默回退 standard；TS 对无模板的未知名 fail loud，且缺少名字合法性校验
- 位置: py:dsh/cordis/profile.py:201-237 (`prepare_profile` 尾部 `return prepare_profile("standard", ...)`) vs ts:reference/packages/boot/app-boot/src/profile.ts:127-134 (`resolveProfileDir`) + 805-818 (`loadProfile`)
- 原版行为:
  ```ts
  if (name === '' || name.includes('/') || name.includes('\\') || name === '.' || name === '..' || name === 'node_modules') {
    throw new Error(`dsh: invalid profile name ${JSON.stringify(name)}`)
  }
  ...
  if (!existsSync(join(dir, 'package.json'))) {
    const template = PROFILE_TEMPLATES[name]
    if (template === undefined) {
      throw new Error(`${binName}: profile ${JSON.stringify(name)} does not exist; create it with 'dsh plugin --profile ${name} add <package>'`)
    }
    initProfile(dir, template.bundles, template.patchReload)
  }
  ```
- 移植版现状:
  ```python
  # Fallback to standard
  return prepare_profile("standard", dsh_home=home, user_layer=user_layer)
  ```
  `dsh --profile typo-name` 在 TS 启动失败（明确指引），在 py 变成静默以 standard 配置运行——用户数据（会话、工作区）挂到意料之外的组合上。
- 修复方案: `prepare_profile` 中非内置名且 `profile_dir` 不存在时抛 `ValueError(f"profile {name!r} does not exist")`（保留 `standard` 作为显式内置名）；入口处拒绝空名、`.`、`..`、含 `/` `\`、`node_modules` 的名字。

### D2 [MUST-FIX] patch 层解析宽松且失败静默：非顶层数组被接受、解析错误吞成 []；TS 全部 fail loud
- 位置: py:dsh/cordis/profile.py:41-62 (`load_optional_patches`) vs ts:reference/packages/boot/app-boot/src/index.ts:280-353 (`loadOptionalPatches`/`loadOverlayPatches`/`parsePatchList`)
- 原版行为:
  ```ts
  if (!Array.isArray(parsed)) {
    throw new Error(`${binName}: ${label} ${file} must be a top-level YAML array of loader patch entries`)
  }
  parsed.forEach((entry, index) => {
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
      throw new Error(`${binName}: ${label} entry ${index + 1} in ${file} must be a mapping (a loader patch entry)`)
    }
  })
  ```
  且 `loadOptionalPatches` 对非 ENOENT 读取错误抛 `failed to read patches ${file}`；"A missing file means 'no layer'; an unreadable, unparsable, or non-array file throws"（ts:271-275）。
- 移植版现状:
  ```python
  except Exception as e:
      sys.stderr.write(f"[Cordis Profile Warning] Failed to parse patch file {filepath}: {e}\n")
      return []
  ...
  elif isinstance(data, dict):
      if "patches" in data and isinstance(data["patches"], list): return data["patches"]
      elif "plugins" in data and isinstance(data["plugins"], list): return data["plugins"]
      return [data]
  ```
  坏掉的 `cordis.patch.yml` 被静默当作"无层"继续启动；裸 mapping / `plugins:` 键形态是 TS 不存在的方言。
- 修复方案: `load_optional_patches` 改为：文件存在但读取失败 → 抛错（`failed to read patches <file>`）；解析失败或顶层非 list → 抛错（`must be a top-level YAML array of loader patch entries`）；逐项校验为 mapping；删除 dict/`plugins` 分支。（如需保留对旧配置的宽容，仅可对"缺少文件"返回 []。）

### D3 [MUST-FIX] web 组合缺少 dsh-web-app 的"禁用 agent 平面"层；bundle 层间 last-write-wins 关系被削弱
- 位置: py:dsh/cordis/profile.py:133-140 (`BUILTIN_BUNDLES["dsh-web-app"]`) vs ts:reference/packages/bundle/web-app/cordis.patch.yml:313-433
- 原版行为（web-app patch 尾段）:
  ```yaml
  - id: tool-pwsh
    disabled: true
  - id: tool-fs
    disabled: true
  ...
  - id: plan-mode
    disabled: true
  - id: tool-web
    disabled: true
  ```
  web 模式把 agent 平面行（tool-pwsh/tool-bash/tool-fs/tool-fs-search/tool-str-replace-editor/skill-filesystem/tool-skill/command-goal/tool-goal/plan-mode/compaction-basic/tool-todo/tool-web/tool-subagent*/tool-workflow/agent-instructions 等）整段 disabled，由 per-session preset 接管；并 restatement `system-prompt`/`session-query-sqlite`/`tools` 的 config。
- 移植版现状: `BUILTIN_BUNDLES["dsh-web-app"]` 只有 6 条 host 行（webserver/frontend-static/client-modules/directory-picker/plugin-inventory/apiproxy），无任何 disable patch —— web profile 下 base 的 agent 工具全部保持启用。
- 修复方案: 在 `BUILTIN_BUNDLES["dsh-web-app"]` 之后追加一层"patch 行"（py 中表现为对 `dsh-base` 行按 id 的 disable 覆盖，经 `compose_profile` 的 profile.patches 通道或新增 bundle_patches 分层），覆盖面以 ts web-app patch 的 disabled 段为准；`compose_profile`/`dump_config` 的应用顺序保持 base → web 覆盖 → profile → home → overlays。

### D4 [MUST-FIX] base 层构成：py 内置行既不是 dsh-base patch 的行集，也未按"行序无加载语义、内容按模式覆盖"的原文组织
- 位置: py:dsh/cordis/profile.py:94-159 (`BUILTIN_BUNDLES["dsh-base"]`) vs ts:reference/packages/bundle/base/cordis.patch.yml:15-501
- 原版行为（摘）:
  ```yaml
  - insert:
      - id: timer
        name: '@deepseek-ai/cordis-plugin-timer'
      - id: hmr
        name: '@deepseek-ai/cordis-plugin-hmr'
        disabled: true
        config: { root: ['.'] }
      ...
      - id: system-prompt
        name: '@deepseek-ai/dsh-system-prompt'
        config: { persona: '' }
      - id: agent-loop
        name: '@deepseek-ai/dsh-agent-loop'
        config: { agents: [] }
      - id: fs-sandbox
        name: '@deepseek-ai/dsh-fs-sandbox'
      - id: llm-deepseek
        name: '@deepseek-ai/dsh-llm-deepseek'
  ```
  dsh-base 含 ~70 行（timer、hmr(disabled)、session/session-log/typert、session-title、user-questions、agent-default-model、llm-pi-ai、attachment-local、session-query-sqlite(openAt: never)、session-projection(+cache)、storage-json/domain、session-telemetry-otel、subprocess、sandbox(+policy)、bash/pwsh-sandbox、shell-env、tool-bash/pwsh、fs-observation-policy、skill(+badge)/tool-skill、command-feedback、goal(+driver)/command-goal、command-compact、subagent 4 行、workflow-worker-thread、timeout-policy、spill-policy、session-checkpoint-policy、system-prompt、agent-loop、fs-sandbox、llm-deepseek 等）。
- 移植版现状: py `dsh-base` 为 37 条直排 entry（tools/credentials-local/settings-file/storage/workspace/... 无 timer、hmr、system-prompt、agent-loop、llm-deepseek、sandbox 家族、session 家族、subagent 注册行、goal/command 行等），且若干行（agent-loop、SessionQuery、LLMOpenAI）改由 `dsh/harness.py` 直接 `ctx.plugin` 挂载。
- 修复方案: 以"py 已有插件 ↔ TS 行"对照补齐 BUILTIN_BUNDLES（含 `disabled: true` 的休眠行如 hmr、llm-pi-ai），把 harness.py 中与行集重复的直接挂载收敛进 bundle 层（见 17-harness 报告）；无法对应的 TS 包（如 typert、sandbox）在报告中显式标注 SKIP 理由，而不是静默缺席。

### D5 [MUST-FIX] render_config_dump：逐层增量应用 + 警告无层级归属，偏离 TS 的"每次从 base 重放 1..k 层单次扁平应用"
- 位置: py:dsh/cordis/profile.py:362-382 vs ts:reference/packages/boot/app-boot/src/index.ts:394-457 (`renderConfigDump`)
- 原版行为:
  ```ts
  const snapshot = (count: number, warnings: string[]) => {
    const flattened = structuredClone(layers.slice(0, count).flatMap(layer => layer.patches))
    return applyEntryPatches(base, flattened, (message, ...args) => { ... })
  }
  ...
  for (const line of warnings.slice(previousWarnings.length)) {
    warn(`${binName}: [${layer.label}] ${line}`)      // 新增警告归属到当前层
  }
  ```
  ts:367-371 明言："apply every layer's patches as ONE flattened list ... the same single call `boot()` makes, so even patch-visibility corner cases (a later layer targeting a group child a plain config replacement introduced, which the single-pass id index never sees) compose identically"。
- 移植版现状:
  ```python
  composed = apply_entry_patches(composed, patches)     # 逐层增量：上一层结果作为下一层输入
  ...
  elif idx < len(provenance) and entry != previous[idx]:
  ```
  (a) 增量应用下，第 2 层 patch 可以命中第 1 层"整包替换 config 引入"的组子行（每次调用重建 id 索引）——TS 的单次扁平应用命中不了，两边 dump 与 boot 挂载结果不一致；(b) `apply_entry_patches(composed, patches)` 未传 warn 回调 → 警告走默认 stderr 前缀 `[Cordis Loader Patch Warning]`，没有 TS 的 `[layer.label]` 归属与 `binName:` 前缀；(c) TS 警告按快照差集（新尾部）输出，py 无对应。
- 修复方案: 循环改为对每个前缀 k 重放：`composed_k = apply_entry_patches(base, flatten(layers[:k]), warn=collector)`；warn 收集后按差集以 `f"{bin_name}: [{label}] {line}"` 输出；provenance 用 JSON 序列化逐位对比快照（与 TS `JSON.stringify` 对齐，py `!=` 比较对类型差异更宽松，宜统一为规范化序列化）。

### D6 [MUST-FIX] dump_config 把 bundle 行当 base、方言丢失 `!!js`；TS 是"全部层扁平 patches 作用于空表 + entryListSchema 打印"
- 位置: py:dsh/cordis/profile.py:318-336 (`dump_config`) vs ts:reference/apps/cli/src/profile-boot.ts:136-143 (`allPatches`) + ts:reference/packages/boot/app-boot/src/profile.ts:854-861 (`composeEntries`)
- 原版行为:
  ```ts
  export function composeEntries(layers, warn = () => {}): EntryOptions[] {
    return applyEntryPatches([], structuredClone(layers.flat()), ...)
  }
  ```
  bundle patch 列表也是 patch 层；dump 打印经 `yaml.dump(group, { schema: entryListSchema, noRefs: true })` 保持 `!!js` 标量。
- 移植版现状:
  ```python
  initial_entries = copy.deepcopy(composed.bundle_patches)          # bundle 行是 entries 不是 patches
  final_entries = apply_entry_patches(initial_entries, [...])
  sorted_entries = [sort_keys(dict(e)) for e in final_entries]
  return yaml.safe_dump(sorted_entries, sort_keys=False, allow_unicode=True)
  ```
  差异：(a) 组合起点不同——TS 中 bundle 层之间、bundle 与用户层之间是同一 id 索引下的单次组合，py 中 bundle 行直接构成 base（若未来 bundle 层间有 id 覆盖/insert 引用，语义分叉）；(b) `__jsExpr` 值被 dump 成普通映射（同 13-include 报告 D3）；(c) py 额外做 `sort_keys`（TS dump 不重排列，见 13-include 报告 D4）。
- 修复方案: `dump_config` 复用 13-include D3 的 `!!js` represent；`sort_keys` 移除；bundle 层保留为行的形态可接受（ADAPT），但须保证 `dump_config` 输出与 `compose_profile` 启动挂载经同一 patch 管线（profile/home/overlay 单次扁平应用——现状已满足）。

### D7 [MUST-FIX] 遥测开关的 has_row 判定基于原始层列表而非组合后的行集
- 位置: py:dsh/cordis/profile.py:303-308 vs ts:reference/apps/cli/src/profile-boot.ts:165-171
- 原版行为:
  ```ts
  const rows = new Map<string, EntryOptions>()
  for (const row of composeEntries([bundlePatches, profile.patches, homePatches, overlays])) {
    if (typeof row.id === 'string') rows.set(row.id, row)
  }
  const telemetryPatch = resolveTelemetryPatch(process.env.DSH_TELEMETRY_DISABLED, rows.has(TELEMETRY_ROW_ID))
  ```
  判定依据是**组合后**（insert 已展开、行按 id 收敛）的行集中是否存在该行。
- 移植版现状:
  ```python
  all_raw = [*bundle_patches, *profile.patches, *home_patches, *overlays]
  has_telemetry = any(entry.get("id") == TELEMETRY_ROW_ID for entry in all_raw if isinstance(entry, dict))
  ```
  原始列表里 id 命中即算——包括"patch 该行但组合后行被后续层行为改变"或"id 出现在 patch（非 insert 行）"等形态；与 TS 判定可产生真值差（例如某层 insert 的行随后被删/改的边角，或仅 patch 引用该 id 而组合后行存在性不同）。
- 修复方案: `compose_profile` 内先跑一次完整组合（bundle 行 + 各 patch 层经 `apply_entry_patches` 单次应用），对组合结果按 id 建 map 判定 `has_telemetry`；`resolve_telemetry_patch` 本身语义与 TS 一致（空串/未设置 → None），保留。

### D8 [MUST-FIX] 自定义 profile 的 bundles 列表硬编码 ["dsh-base"]，忽略 profile 目录的 manifest
- 位置: py:dsh/cordis/profile.py:227-234 vs ts:reference/packages/boot/app-boot/src/profile.ts:819-843
- 原版行为:
  ```ts
  const bundles = manifest.dsh?.profile?.bundles ?? []
  const layers = bundles.map((packageName) => { ... resolveBundleDir ... })
  ```
  自定义 profile 由其 `package.json` 的 `dsh.profile.bundles` 决定层列表（可为空表 = 无 bundle 层）；`patchReload` 非 live/startup 抛错（ts:822-827）。
- 移植版现状:
  ```python
  if os.path.isdir(profile_dir):
      return Profile(name=name, dir_path=profile_dir, patch_path=patch_file, patches=user_patches, bundles=["dsh-base"])
  ```
- 修复方案: py 无 npm 依赖解析（合法 ADAPT），但层列表应来自 profile 目录内一个可读的清单（复用现有 `package.json` 或新增 `profile.yaml` 的 `bundles:` 键；缺省 ["dsh-base"]），并校验清单内 bundle 名存在于 `BUILTIN_BUNDLES`（否则 fail loud）；`patchReload` 字段如保留须校验 `live|startup`。

### D9 [ADAPT] bundle 基础设施：npm 包/两锚解析/模块回退治愈 → 内置字典
- 位置: py:dsh/cordis/profile.py:94-159 vs ts:reference/packages/boot/app-boot/src/profile.ts:41-47, 778-789, 579-605, 642-677
- 原版行为: `resolveBundleDir`（installation anchor → profile dir 两锚）、`healProfilesModuleFallback`（symlink/ESM proxy + 跨进程锁）、`resolveModuleFallbackEntries`（依赖闭包 BFS）。
- 移植版现状: `BUILTIN_BUNDLES` 常量表。
- 评估: Windows 7 + 零依赖 portable 下 npm/pnpm 依赖图治愈不适用；插件已内嵌于 py 包。SKIP 级（`healProfilesModuleFallback`/`resolveBundleDir`/proxy 机制），但 D4 的行集补齐仍需人工对照完成。`INSTALLATION_OWNED_PROFILE_TUPLES` 归一化（ts:161-163, 721-743）与 `initProfile` 模板初始化同理 SKIP（无 profile 目录生成面）。

### D10 [ADAPT] Profile.patchReload（'live' | 'startup'）与用户 patch 层 HMR
- 位置: py:dsh/cordis/profile.py:73-90（无 patchReload 字段） vs ts:reference/packages/boot/app-boot/src/profile.ts:56-72, 822-828 + ts:reference/apps/cli/src/profile-boot.ts:278-294（watchUserPatches 消费）
- 原版行为: 模板声明 patch 文件生命周期（web=live、其余 startup、自定义默认 live）；`watchUserPatches` 经 `hmr.registerConfig` 监听 `cordis.patch.yml` 并经 `entry.update({config: {...includeConfig, patches: compose(userPatches)}})` 事务性重放。
- 移植版现状: Profile 无 patchReload；py 无 watchUserPatches 等价物（hmr 的 register_config 存在但无人为 patch 层注册）。
- 评估: ADAPT 目标态：Profile 增加 `patch_reload` 字段（默认 startup）；harness/CLI 在 `patch_reload == 'live'` 且 hmr 服务可用时调用 `hmr.register_config(patch_file, refresh=重放组合)`。行为面（live 重载用户层）当前完全缺失，依赖 12-hmr D1 的初始触发修复才可用。

### D11 [ADAPT] home 层路径解析重复实现
- 位置: py:dsh/cordis/profile.py:22-37 (`resolve_dsh_home`/`home_patch_path`) vs ts:reference/packages/boot/app-boot/src/profile.ts:69-71 (`homePatchPath`) + ts:reference/packages/util/home-paths/src/index.ts:87-91
- 原版行为: `homePatchPath() = join(resolveDshHome(), PROFILE_PATCH_FILENAME)`，单一实现在 home-paths。
- 移植版现状: profile.py 与 environment.py 各有一份 `resolve_dsh_home`（environment 版支持 custom_home/env 注入，profile 版只读 `DSH_HOME`）。
- 评估: 行为等价但双实现易漂移（`~` 展开缺失见 16-environment 报告 D1）；建议 profile.py 复用 environment.resolve_dsh_home。归类 ADAPT。

## 测试缺口

### T1 test_prepare_profile_unknown_name_fails_loud（对应 D1）
`prepare_profile("no-such-profile")` 抛错；非法名（`../x`、空串、`node_modules`）被拒。

### T2 test_load_optional_patches_fail_loud（对应 D2）
存在但内容非法（顶层 dict、语法错误、含非 mapping 元素的数组）→ 抛错而非返回 []；文件缺失 → []。

### T3 test_web_profile_disables_agent_plane_rows（对应 D3）
`compose_profile("web")` 组合后 `tool-pwsh`/`tool-fs`/`tool-skill`/`plan-mode`/`tool-web`/`tool-subagent` 等行的 `disabled` 为 True；host 行（webserver/client-modules）保持启用。

### T4 test_base_bundle_rows_mirror_reference_inventory（对应 D4）
BUILTIN_BUNDLES["dsh-base"] 覆盖 ts dsh-base patch 全部行的 py 对应物（含 `disabled: true` 休眠行 hmr），对照表可参数化断言。

### T5 test_render_config_dump_single_flat_snapshot_semantics（对应 D5）
构造"layer1 整包替换某组 config、layer2 patch 该组新子行"的场景：dump 结果与 `apply_entry_patches(base, flatten(all))`（单次调用）一致（即 layer2 patch 不命中）；警告输出带 `[layer-label]`。

### T6 test_dump_config_preserves_js_tag_and_order（对应 D6）
含 `!!js` 与非字母序键的条目 dump 后仍为 `!!js` 标量、键序不重排。

### T7 test_telemetry_switch_uses_composed_rows（对应 D7）
仅当组合后行集含 `session-telemetry-otel` 且 env 非空时生成 disable patch；原始层里出现该 id 但组合后无行时不生成。

### T8 test_custom_profile_bundles_from_manifest（对应 D8）
profile 目录清单声明 `bundles: [dsh-base, dsh-web-app]` → prepare_profile 读取该列表；未知 bundle 名 fail loud。

### T9 test_live_patch_reload_registered_when_hmr_available（对应 D10）
`patch_reload == 'live'` 且 ctx 挂有 hmr 服务 → patch 文件被注册监视；修改后 patches 事务性重放（配合 12-hmr T1 的初始触发）。
