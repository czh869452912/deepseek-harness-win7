# dsh/cordis/environment.py ↔ reference/packages/util/launch-environment/src/index.ts (61/124) + reference/packages/util/home-paths/src/index.ts (67/112)

核对说明：BOOTSTRAP_NAMES 与 BOOTSTRAP_PREFIXES 两个集合与 ts:app-boot/src/index.ts:96-120（环境层的 tripwire 真源）逐项一致（含 `PYTHONHOME`、`PERL5LIB`、`NODE_TLS_REJECT_UNAUTHORIZED` 等），不构成差异。快照的层序（process → project-env → user-env）、materialize 时"两文件先解析后应用、不覆盖已有值"的顺序（py:200-211 vs ts:186-195）一致。

## 差异清单

### D1 [MUST-FIX] DSH_HOME / 显式配置路径不做 `~` 展开
- 位置: py:dsh/cordis/environment.py:12-22 (`resolve_dsh_home`) vs ts:reference/packages/util/home-paths/src/index.ts:70-91 (`expandHomePath` + `resolveDshHome`)
- 原版行为:
  ```ts
  export function expandHomePath(path: string): string {
    if (path === '~') return homedir()
    if (path.startsWith('~/') || path.startsWith('~\\')) return join(homedir(), path.slice(2))
    return path
  }
  export function resolveDshHome(configured?: string, env = process.env): string {
    const fromEnv = env[DSH_HOME_ENV]
    const selected = configured ?? (fromEnv !== undefined && fromEnv.trim().length > 0 ? fromEnv : defaultDshHome())
    return resolve(expandHomePath(selected))
  }
  ```
- 移植版现状:
  ```python
  env_home = env_dict.get("DSH_HOME")
  if env_home and isinstance(env_home, str) and env_home.strip():
      return os.path.abspath(env_home)
  return os.path.abspath(os.path.join(os.path.expanduser("~"), ".dsh"))
  ```
  默认 home 走 `expanduser`，但 `DSH_HOME=~/dsh-alt` 或 `configured="~/dsh-alt"` 在 py 得到 `<cwd>\~\dsh-alt`（字面 `~` 目录），TS 得到 `<home>\dsh-alt`。profile.py:22-31 的同名函数同样受影响（15-profile 报告 D11）。
- 修复方案: `resolve_dsh_home` 对 selected 值先做等价 `expandHomePath`：`~` → `os.path.expanduser("~")`；`~/`、`~\` 前缀 → `os.path.join(homedir(), path[2:])`；再 `os.path.abspath`。

### D2 [MUST-FIX] .env 语法是 node:util parseEnv 的子集：行内注释与多行值处理缺失
- 位置: py:dsh/cordis/environment.py:65-95 (`parse_dotenv`) vs ts:reference/packages/boot/app-boot/src/index.ts:157 (`parseEnv(content)`)
- 原版行为:
  ```ts
  const values = parseEnv(content) as Record<string, string>
  ```
  Node `parseEnv` 支持：双引号值内的转义（`\n` `\r` `\t` 等）、**跨行多行值**（引号未闭合时继续读取后续行）、单引号字面量、`export ` 前缀、`#` 整行注释。
- 移植版现状:
  ```python
  key, val = line.split("=", 1)
  ...
  if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
  ```
  (a) 无行内注释剥离：`DEEPSEEK_API_KEY=sk-xxx # rotated` 在 TS 值为 `sk-xxx`，py 值含 ` # rotated`——这是安全 tripwire 文件里最常见的写法；(b) 多行引号值在第 1 行截断，静默产出错误值；(c) 双引号转义替换顺序（`\\n` 在 `\\` 之前处理链中无保护，`\\n`（字面反斜杠+n）会被错误展开）。
- 修复方案: `parse_dotenv` 增加非引号值的行内 ` #` 注释剥离；实现多行值聚合（遇未闭合引号继续吞行直到闭引号）；用单遍扫描处理双引号转义（避免顺序敏感的多重 replace）；单引号保持纯字面量（当前正确）。

### D3 [MUST-FIX] 缺少 `launchEnvironmentOf` 等价读取入口，服务名约定未固定
- 位置: py:dsh/cordis/environment.py:113-154（仅快照类） vs ts:reference/packages/util/launch-environment/src/index.ts:105-117
- 原版行为:
  ```ts
  export const DSH_LAUNCH_ENVIRONMENT_KEY = 'launchEnvironment'
  export function launchEnvironmentOf(ctx: Context): LaunchEnvironmentSnapshot {
    return ctx.get(DSH_LAUNCH_ENVIRONMENT_KEY)
      ?? createLaunchEnvironmentSnapshot([{ source: 'process', values: process.env as Record<string, string> }])
  }
  ```
  消费方经统一入口读取，宿主未提供快照时回退到"仅 process 层"。
- 移植版现状: 只有 `dsh/harness.py:80` 的 `ctx.set_service("launch_environment", launch_env)`；environment.py 没有 `launch_environment_of(ctx)`，消费方各自 `ctx.get("launch_environment")` 且无回退。
- 修复方案: 增加 `LAUNCH_ENVIRONMENT_KEY = "launch_environment"` 与 `launch_environment_of(ctx)`（缺失时构造 `[{source:"process", values: dict(os.environ)}]` 快照），消费方一律走该入口。

### D4 [MUST-FIX] 快照未隔离后续 `os.environ` 突变（'process' 层值的可变性）
- 位置: py:dsh/cordis/environment.py:198, 213 vs ts:reference/packages/util/launch-environment/src/index.ts:78-87
- 原版行为:
  ```ts
  // Copy every layer so later mutations cannot change the snapshot.
  const bySource = new Map(... values: new Map(Object.entries(layer.values).map(...)) ...)
  ```
  ts:33-36 契约："nothing mutates it afterwards, so a later `chdir`, workspace switch, or resumed session observes the same values a consumer resolved at boot."
- 移植版现状:
  ```python
  inherited = dict(os.environ)      # 已拷贝 —— 此处正确
  ```
  `inherited` 拷贝本身正确；但 `parse_dotenv`/`read_env_layer` 返回的 `values` dict 未在快照构造时再拷贝（py:121-134 直接引用 layer["values"]），且 `LaunchEnvironmentSnapshot` 无任何防突变约束——当前 `load_layered_env` 调用链内无害，属契约缺口：任何消费方拿到 layer dict 引用即可改写"不可变"快照。
- 修复方案: `LaunchEnvironmentSnapshot.__init__` 对每层 `dict(vals)` 浅拷贝并私有化（不暴露 `_layers`）；文档注明只经 `get_from/get/get_value` 读取。

### D5 [MUST-FIX] user 层跳过条件：大小写折叠行为与 TS 不同
- 位置: py:dsh/cordis/environment.py:203-204 vs ts:reference/packages/boot/app-boot/src/index.ts:188
- 原版行为:
  ```ts
  const user = home === resolve(cwd) ? undefined : readEnvLayer(binName, home, warn)
  ```
  `resolve` 后按字符串全等比较（Windows 上大小写敏感比较）。
- 移植版现状:
  ```python
  if os.path.normcase(home_dir) != os.path.normcase(work_dir):
  ```
  `normcase` 在 Windows 折叠大小写与斜杠——`DSH_HOME=c:\Users\x\.dsh` 与 cwd=`C:\Users\x\.DSH` 之类输入下两边判定相反（py 跳过 user 层，TS 重复加载）。
- 修复方案: 保持 normcase（py 侧更安全，避免同一文件被当作两层重复加载），但在报告中记录为有意偏差；或对齐 TS 用 `os.path.abspath` 字符串比较。二选一后加测试固定行为。

### D6 [ADAPT] os.environ 的 Windows 大小写不敏感键 vs process.env
- 位置: py:dsh/cordis/environment.py:206-211 vs ts:reference/packages/boot/app-boot/src/index.ts:190-195
- 原版行为:
  ```ts
  if (process.env[name] === undefined) process.env[name] = value
  ```
  Node 在 Windows 上 process.env 键大小写不敏感。
- 移植版现状:
  ```python
  if k not in os.environ:
      os.environ[k] = v
  ```
  CPython 在 Windows 上 os.environ 键同样大小写不敏感（存取时折叠为大写）。
- 评估: 语义等价，ADAPT；POSIX 上两边都是大小写敏感精确匹配。无动作。

### D7 [ADAPT] read_env_layer 的读取错误分类
- 位置: py:dsh/cordis/environment.py:165-170 vs ts:reference/packages/boot/app-boot/src/index.ts:147-155
- 原版行为: ENOENT 静默（"no .env is fine"）；其他读取错误 `warn(...)` 后按缺层处理。
- 移植版现状: 先 `os.path.isfile` 预检，读取异常统一 warn + 返回 None。
- 评估: 表面行为等价（缺文件无告警、坏文件告警且降级），ADAPT；区别仅在没有区分"不可读"与"读取中消失"的边角。无动作。

### D8 [SKIP] canonicalizeWatchPath（watch 路径规范化）
- 位置: ts:reference/packages/util/home-paths/src/index.ts:33-55 vs py:（无对应）
- 原版行为: 为原生 filesystem watcher 解析最深存在祖先的 realpath，处理 Windows 文件占位父目录与 8.3 短名。
- 评估: 消费方是 chokidar/原生 watch（12-hmr 已定为轮询 ADAPT），轮询无需路径规范化。平台不适用，跳过。

### D9 [SKIP] 显示辅助：dshHomeDisplay / DEFAULT_DSH_HOME_DISPLAY / dshHomePath
- 位置: ts:reference/packages/util/home-paths/src/index.ts:12-15, 94-111 vs py:（无对应）
- 原版行为: 把已解析 home 显示为 `~/.dsh` 或 `$DSH_HOME`（绝不暴露机器绝对路径），以及 join 便捷函数。
- 评估: 纯展示/便利函数，当前 py 端没有用户可见消费面（CLI 文案尚未实现该行）；待 py CLI 需要"home 显示名"时一并实现。跳过（无行为差异点）。

### D10 [SKIP] resolve_layered_config（settings 链）
- 位置: py:dsh/cordis/environment.py:222-261 vs ts:（两文件中无对应物）
- 原版行为: —
- 评估: py 自有扩展（system default → home settings → workspace → preset → CLI/env），不在本次对照的 TS 权威面内；其语义由 dsh-settings 相关包承载。不计差异，仅登记为移植扩展。

## 测试缺口

### T1 test_resolve_dsh_home_expands_tilde（对应 D1）
`DSH_HOME="~/dsh-alt"` → 结果位于用户 home 下，而非 `<cwd>\~\dsh-alt`；`configured="~"` → home 本身。

### T2 test_parse_dotenv_inline_comment_and_multiline（对应 D2）
`K=v # comment` → `v`；跨行双引号值完整保留换行；单引号值内 `#` 与 `\n` 保持字面。

### T3 test_parse_dotenv_escape_order（对应 D2）
值 `a\\nb`（字面反斜杠 + n）不被展开为换行；`\n` 正确展开。

### T4 test_launch_environment_of_falls_back_to_process_layer（对应 D3）
未挂载服务时 `launch_environment_of(ctx)` 返回仅 process 层快照；挂载后返回同一实例。

### T5 test_snapshot_is_immutable_after_load（对应 D4）
`load_layered_env` 后修改 `os.environ` 与任何 layer dict 引用 → 快照 `get_value` 结果不变。

### T6 test_get_from_respects_source_filter_and_case_folding（对应 D6 + 快照接口）
`get_from(name, ["process"])` 在 project-env 层有值时不返回；Windows 上 `get("path")` 命中 `PATH` 层内大小写变体（PY2/win32 折叠臂）。

### T7 test_user_layer_skipped_when_home_equals_cwd（对应 D5）
cwd 与 DSH_HOME 指向同一目录（含大小写/斜杠变体）→ 不加载 user 层且同一文件不产生两层。

### T8 test_blank_dsh_home_treated_as_unset（既有缺口）
`DSH_HOME="  "` → 回落 `~/.dsh`（当前实现已如此，但无测试固定；TS 契约明确"blank override never resolves the home to cwd"）。
