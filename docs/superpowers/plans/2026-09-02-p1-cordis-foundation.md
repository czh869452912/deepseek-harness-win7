# P1: Cordis 地基 1:1 对齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `dsh/cordis/*`（16 文件）+ `dsh/harness.py` 装配与 `reference/vendor/*` + `packages/boot/*` 对齐到 1:1，并 1:1 移植 app-boot/cmdline 全部 specs。

**Architecture:** 先由 6 个并行对照分析智能体产出逐文件差异报告（保存到 `docs/superpowers/plans/p1-reports/`），再按依赖序逐模块"先移植行为测试（红）→ 按报告对齐实现（绿）"。vendor 源码是唯一实现权威；差异仅允许来自 Python 3.8.10 / Win7 约束。

**Tech Stack:** Python 3.8.10（venv `.venv`），pytest + pytest-asyncio，无第三方运行时依赖。

**对照权威与验证命令（全计划通用）：**
- 实现权威：`reference/vendor/<pkg>/src/*.ts`、`reference/packages/boot/*/src/*.ts`、`reference/packages/util/{launch-environment,home-paths}/src/*.ts`
- 测试权威：`reference/packages/boot/app-boot/tests/*.spec.ts`、`reference/packages/boot/cmdline/tests/cmdline.spec.ts`
- 全量回归：`.venv\Scripts\python.exe -m pytest tests -q`（基线 728 全绿，结束时应 ≥ 基线 + 新增）
- 语法基线：`.venv\Scripts\python.exe -m compileall -q dsh tests`（无输出 = 通过）

---

## 对照对总表（Task 1 智能体分配）

| # | 移植版文件 | 原版权威文件 |
|---|---|---|
| A1 | `dsh/cordis/utils.py` (566) | `vendor/cordis/src/utils.ts` (255) + `vendor/cosmokit/src/{array,misc,string,time,types}.ts` (408) |
| A2 | `dsh/cordis/plugin.py` (23) | `vendor/cordis/src/index.ts` (14) |
| B1 | `dsh/cordis/events.py` (464) | `vendor/cordis/src/events.ts` (329) |
| B2 | `dsh/cordis/timer.py` (399) | `vendor/timer/src/index.ts` (136) |
| C1 | `dsh/cordis/fiber.py` (745) | `vendor/cordis/src/fiber.ts` (695) |
| D1 | `dsh/cordis/context.py` (438) | `vendor/cordis/src/context.ts` (137) |
| D2 | `dsh/cordis/registry.py` (388) | `vendor/cordis/src/registry.ts` (305) |
| D3 | `dsh/cordis/service.py` (128) | `vendor/cordis/src/service.ts` (105) |
| D4 | `dsh/cordis/reflect.py` (369) | `vendor/cordis/src/reflect.ts` (388) |
| E1 | `dsh/cordis/logger.py` (295) | `vendor/cordis/src/logger.ts` (238) + `vendor/logger-console/src/{shared,index,browser}.ts` (125) |
| E2 | `dsh/cordis/schema.py` (1028) | `vendor/schemastery/src/index.ts` (817) |
| F1 | `dsh/cordis/hmr.py` (389) | `vendor/hmr/src/{index,error}.ts` (549) |
| F2 | `dsh/cordis/include.py` (276) | `vendor/include/src/index.ts` (336) |
| F3 | `dsh/cordis/loader.py` (1305) | `vendor/loader/src/{index,internal}.ts` (281) + `vendor/loader/src/config/{entry,group,isolate,tree,utils}.ts` (714) + `vendor/group/src/index.ts` (2) |
| F4 | `dsh/cordis/profile.py` (441) | `packages/boot/app-boot/src/profile.ts` (808) |
| F5 | `dsh/cordis/environment.py` (263) | `packages/util/launch-environment/src/*.ts` (61) + `packages/util/home-paths/src/*.ts` (67) |
| F6 | `dsh/harness.py` (175) | `packages/boot/app-boot/src/index.ts` (811) + `packages/bundle/base/src/*.ts`（装配角色） |
| — | `dsh/cordis/file_lock.py` (91) | 无权威（port-only 工具，仅需确认无行为冲突） |

---

### Task 0: 基线与护栏

- [ ] **Step 0.1: 确认基线全绿**

Run: `.venv\Scripts\python.exe -m pytest tests -q 2>&1 | Select-Object -Last 3`
Expected: `728 passed`（如非 728，先停下排查，不得带病开工）

- [ ] **Step 0.2: 创建 1:1 测试目录骨架**

创建 `tests/1to1/__init__.py`、`tests/1to1/cordis/__init__.py`、`tests/1to1/boot/__init__.py`（空文件；`tests/1to1/_support/` 留待 Task 14）。同时创建报告目录 `docs/superpowers/plans/p1-reports/`（放 `.gitkeep`）。

- [ ] **Step 0.3: 记录 py38 语法护栏**

Run: `.venv\Scripts\python.exe -m compileall -q dsh tests`
Expected: 无输出（退出码 0）。此命令在本阶段每个实现 Task 结束后重复执行。

---

### Task 1: 并行对照分析（6 个智能体，只读研究）

- [ ] **Step 1.1: 派发 6 个 explore 智能体（单条消息并行调用）**

每个智能体的提示词统一模板（替换 `<分配对照对>` 为总表中该组的行）：

```
Research-only task. Working directory: D:\Project\deepseek-harness-win7
逐对比较下列移植版 Python 文件与原版 TypeScript 权威文件（1:1 移植对齐项目，Python 3.8.10/Win7 约束见 AGENTS.md）：
<分配对照对>
对每一对：
1. 通读两侧全文，逐个函数/类/常量对照：列出移植版缺失的行为、语义漂移（参数默认值、边界条件、错误类型、事件/回调触发顺序、状态机迁移）、多余的本地化逻辑。
2. 区分三类差异并标注：MUST-FIX（改变可见行为的偏差）、ADAPT（py3.8/win7 允许的等价实现，如 Proxy→显式方法、Map→dict）、SKIP（平台不可行，如 finalizationRegistry 依赖）。
3. 检查移植版测试覆盖缺口：tests/ 下哪些 MUST-FIX 行为当前无测试钉住。
将完整报告写入 docs/superpowers/plans/p1-reports/<组号>-<模块名>.md（如 1-utils-cosmokit.md），格式：
# <文件对>
## 差异清单
### D<n> [MUST-FIX|ADAPT|SKIP] <一句话标题>
- 位置：py:<file>:<行号> vs ts:<file>:<行号>
- 原版行为：<引用 ts 关键代码 1-5 行>
- 移植版现状：<引用 py 关键代码 1-5 行>
- 修复方案：<具体到函数/字段级>
## 测试缺口
### T<n> <需新增的测试行为描述 + 建议测试名>
最后返回：每组差异计数（MUST-FIX/ADAPT/SKIP）与报告文件路径列表。
```

分组：A=`A1,A2`（报告 `1-utils-cosmokit.md`、`2-plugin.md`）；B=`B1,B2`（`3-events.md`、`4-timer.md`）；C=`C1`（`5-fiber.md`）；D=`D1,D2,D3,D4`（`6-context.md`、`7-registry.md`、`8-service.md`、`9-reflect.md`）；E=`E1,E2`（`10-logger.md`、`11-schema.md`）；F=`F1..F6`（`12-hmr.md`、`13-include.md`、`14-loader.md`、`15-profile.md`、`16-environment.md`、`17-harness.md`）。

- [ ] **Step 1.2: 汇总核对**

确认 17 份报告全部存在且每组含差异计数；将 MUST-FIX 总数记入 P1 阶段日志（提交信息用）。

---

### Task 2: utils.py + cosmokit 对齐（A1/A2）

**Files:** Modify `dsh/cordis/utils.py`, `dsh/cordis/plugin.py`; Test: `tests/1to1/cordis/test_utils_cosmokit_parity.py`（新建）

- [ ] **Step 2.1: 依报告 `1-utils-cosmokit.md` 先写失败测试**

每个 MUST-FIX 项 `D<n>` 对应一个测试函数，命名 `test_d<n>_<slug>`，docstring 引用权威 ts 文件与行号。模板：

```python
import pytest
from dsh.cordis import utils

def test_d1_camelize_deep_objects():
    """vendor/cosmokit/src/misc.ts camelize(): 递归转换 dict 键为 camelCase（含嵌套 list/dict）。"""
    assert utils.camelize({"foo_bar": [{"baz_qux": 1}]}) == {"fooBar": [{"bazQux": 1}]}
```

（上例为格式示例；实际断言以报告引用的原版行为为准，逐项覆盖。ADAPT/SKIP 项不写测试，在文件头注释列出并注明理由。）

- [ ] **Step 2.2: 运行确认红**

Run: `.venv\Scripts\python.exe -m pytest tests/1to1/cordis/test_utils_cosmokit_parity.py -q`
Expected: 新增用例 FAIL（若全 PASS，说明测试没钉住差异，回到报告复核）

- [ ] **Step 2.3: 对齐实现**

按报告"修复方案"逐项修改 `dsh/cordis/utils.py`、`dsh/cordis/plugin.py`；保持既有公开符号不删（旧测试 728 依赖它们）。

- [ ] **Step 2.4: 全绿验证**

Run: `.venv\Scripts\python.exe -m pytest tests/1to1/cordis/test_utils_cosmokit_parity.py tests/test_cordis.py tests/test_cordis_utils.py -q`（若个别旧文件名不存在，以 `Get-ChildItem tests -Filter "*cordis*utils*"` 实际名为准）+ `.venv\Scripts\python.exe -m compileall -q dsh`
Expected: 全 PASS，compileall 无输出

---

### Task 3: events.py 对齐（B1）

**Files:** Modify `dsh/cordis/events.py`; Test: `tests/1to1/cordis/test_events_parity.py`（新建）

- [ ] **Step 3.1:** 依报告 `3-events.md` 写失败测试（步骤同 2.1，模板同上；重点钉住：waterfall 的 `next()` 短路语义、emit 的同步/异步分派顺序、事件 Map 合并扩展、dispose 后停止分派）
- [ ] **Step 3.2:** Run `.venv\Scripts\python.exe -m pytest tests/1to1/cordis/test_events_parity.py -q` → 新增 FAIL
- [ ] **Step 3.3:** 按报告对齐 `dsh/cordis/events.py`
- [ ] **Step 3.4:** Run `.venv\Scripts\python.exe -m pytest tests/1to1/cordis/test_events_parity.py tests/test_cordis_waterfall_and_events_advanced_1to1.py -q` + `compileall` → 全 PASS

---

### Task 4: fiber.py 对齐（C1）

**Files:** Modify `dsh/cordis/fiber.py`; Test: `tests/1to1/cordis/test_fiber_parity.py`（新建）

- [ ] **Step 4.1:** 依报告 `5-fiber.md` 写失败测试（重点钉住：effect 注册/销毁逆序、epoch 隔离、lifecycle 事件顺序、屏障/等待语义、异常传播路径）
- [ ] **Step 4.2:** Run 新测试 → FAIL
- [ ] **Step 4.3:** 对齐 `dsh/cordis/fiber.py`（JS finalizationRegistry/GC 钩子等 SKIP 项按报告标注保留 ADAPT 注释）
- [ ] **Step 4.4:** Run 新测试 + `tests/test_cordis_fiber_barrier_and_persistence_1to1.py tests/test_cordis_lifecycle_reference_1to1.py -q` + `compileall` → 全 PASS

---

### Task 5: context/registry/service/reflect/plugin 对齐（D 组）

**Files:** Modify `dsh/cordis/context.py`, `dsh/cordis/registry.py`, `dsh/cordis/service.py`, `dsh/cordis/reflect.py`; Test: `tests/1to1/cordis/test_context_registry_service_reflect_parity.py`（新建）

- [ ] **Step 5.1:** 依报告 `6-context.md`…`9-reflect.md` 写失败测试（重点钉住：`ctx.effect` 可逆性、`inject` 缺失时的 fail-loud 行为、waterfall/parallel/serial/bail 分派模式语义、service 定义/解析、reflect 的键插值与类型判断）
- [ ] **Step 5.2:** Run 新测试 → FAIL
- [ ] **Step 5.3:** 按报告逐文件对齐（注意 `registry.py` 的 DI 解析顺序与 `context.py` 的服务缓存语义是全插件地基，改动必须保守且逐项可溯）
- [ ] **Step 5.4:** Run 新测试 + `tests/test_cordis_strict_inject*.py tests/test_cordis_scheduling.py tests/test_cordis_traceable_and_stack_1to1.py -q` + `compileall` → 全 PASS

---

### Task 6: logger.py 对齐（E1）

**Files:** Modify `dsh/cordis/logger.py`; Test: `tests/1to1/cordis/test_logger_parity.py`（新建）

- [ ] **Step 6.1:** 依报告 `10-logger.md` 写失败测试（重点钉住：日志级别过滤、transport 分派、color/格式化输出契约、child logger 继承）
- [ ] **Step 6.2:** Run 新测试 → FAIL
- [ ] **Step 6.3:** 对齐 `dsh/cordis/logger.py`（Win7 终端编码按 AGENTS.md：`sys.stdout.reconfigure(encoding="utf-8")` 属允许 ADAPT）
- [ ] **Step 6.4:** Run 新测试 + 相关旧测试（`Get-ChildItem tests -Filter "*logger*"`）+ `compileall` → 全 PASS

---

### Task 7: schema.py 对齐（E2）

**Files:** Modify `dsh/cordis/schema.py`; Test: `tests/1to1/cordis/test_schema_parity.py`（新建）

- [ ] **Step 7.1:** 依报告 `11-schema.md` 写失败测试（重点钉住：Schemastery 全类型构造/校验/序列化、链式 API、`i`/`extra`/回调语义、错误消息文本）
- [ ] **Step 7.2:** Run 新测试 → FAIL
- [ ] **Step 7.3:** 对齐 `dsh/cordis/schema.py`
- [ ] **Step 7.4:** Run 新测试 + `tests/test_cordis_schema_1to1.py tests/test_schemastery_advanced.py tests/test_cordis_schemastery_standard_schema_1to1.py tests/test_cordis_schemastery_advanced_1to1.py -q` + `compileall` → 全 PASS

---

### Task 8: timer.py 对齐（B2）

**Files:** Modify `dsh/cordis/timer.py`; Test: `tests/1to1/cordis/test_timer_parity.py`（新建）

- [ ] **Step 8.1:** 依报告 `4-timer.md` 写失败测试（重点钉住：interval/timeout/rollback 语义、sleep 取消、与 fiber 生命周期的联动）
- [ ] **Step 8.2:** Run 新测试 → FAIL
- [ ] **Step 8.3:** 对齐 `dsh/cordis/timer.py`
- [ ] **Step 8.4:** Run 新测试 + `tests/test_cordis_timer_1to1.py tests/test_timer_advanced_specs_1to1.py -q` + `compileall` → 全 PASS

---

### Task 9: hmr.py 对齐（F1）

**Files:** Modify `dsh/cordis/hmr.py`; Test: `tests/1to1/cordis/test_hmr_parity.py`（新建）

- [ ] **Step 9.1:** 依报告 `12-hmr.md` 写失败测试（重点钉住：配置文件 watcher 触发、防抖、重载错误上抛路径、error.ts 的 ConfigError 语义）
- [ ] **Step 9.2:** Run 新测试 → FAIL
- [ ] **Step 9.3:** 对齐 `dsh/cordis/hmr.py`（文件监听用轮询/win32 可行方式属允许 ADAPT，但对外回调时序必须与原版一致）
- [ ] **Step 9.4:** Run 新测试 + `tests/test_cordis_config_watcher_1to1.py tests/test_cordis_config_reload_1to1.py -q` + `compileall` → 全 PASS

---

### Task 10: include.py 对齐（F2）

**Files:** Modify `dsh/cordis/include.py`; Test: `tests/1to1/cordis/test_include_parity.py`（新建）

- [ ] **Step 10.1:** 依报告 `13-include.md` 写失败测试（重点钉住：`!!include`/`!include` 指令解析、相对路径解析、循环引用检测）
- [ ] **Step 10.2:** Run 新测试 → FAIL
- [ ] **Step 10.3:** 对齐 `dsh/cordis/include.py`
- [ ] **Step 10.4:** Run 新测试 + 相关旧测试（`Get-ChildItem tests -Filter "*include*"`）+ `compileall` → 全 PASS

---

### Task 11: loader.py 对齐（F3）

**Files:** Modify `dsh/cordis/loader.py`; Test: `tests/1to1/cordis/test_loader_parity.py`（新建）

- [ ] **Step 11.1:** 依报告 `14-loader.md` 写失败测试（重点钉住：entry/group/isolate/tree 四种 config 形态、`!!js` 条目求值边界（py3.8 下等价安全求值）、overlay 合并顺序、entry `disabled` 语义、事务式注册回滚）
- [ ] **Step 11.2:** Run 新测试 → FAIL
- [ ] **Step 11.3:** 对齐 `dsh/cordis/loader.py`
- [ ] **Step 11.4:** Run 新测试 + `tests/test_cordis_loader_safe_eval_1to1.py tests/test_cordis_patches_and_loader_specs.py tests/test_loader_entry_transactions_1to1.py tests/test_cordis_interpolate_1to1.py -q` + `compileall` → 全 PASS

---

### Task 12: profile.py + environment.py 对齐（F4/F5）

**Files:** Modify `dsh/cordis/profile.py`, `dsh/cordis/environment.py`; Test: `tests/1to1/cordis/test_profile_environment_parity.py`（新建）

- [ ] **Step 12.1:** 依报告 `15-profile.md`、`16-environment.md` 写失败测试（重点钉住：profile/bundle 级联合并顺序、patch 层语义、.env 分层加载与 home 路径解析、优先级）
- [ ] **Step 12.2:** Run 新测试 → FAIL
- [ ] **Step 12.3:** 对齐 `dsh/cordis/profile.py`、`dsh/cordis/environment.py`
- [ ] **Step 12.4:** Run 新测试 + `tests/test_profile_and_boot_specs.py tests/test_profile_boot_and_bundles.py tests/test_environment_layers.py -q` + `compileall` → 全 PASS

---

### Task 13: harness.py 装配对齐（F6）

**Files:** Modify `dsh/harness.py`; Test: `tests/1to1/cordis/test_harness_assembly_parity.py`（新建）

- [ ] **Step 13.1:** 依报告 `17-harness.md` 写失败测试（重点钉住：装配顺序、服务注册时机、verbose/web 分支挂载差异、关停顺序）
- [ ] **Step 13.2:** Run 新测试 → FAIL
- [ ] **Step 13.3:** 对齐 `dsh/harness.py`（仅对齐装配语义，不引入 P4 的 API 层改动）
- [ ] **Step 13.4:** Run 新测试 + `tests/test_harness.py tests/test_cli_args_and_shutdown_parity.py -q` + `compileall` → 全 PASS

---

### Task 14: app-boot + cmdline specs 1:1 移植

**Files:** Test: `tests/1to1/boot/app_boot/test_<spec>.py` ×6、`tests/1to1/boot/cmdline/test_cmdline.py`；Create `tests/1to1/_support/`（所需 testkit 等价物）

spec → pytest 对照表（1 文件 1 测试模块，describe→class，it→test_ 函数保名 snake_case）：

| 原版 spec | 移植目标 |
|---|---|
| `boot/app-boot/tests/app-boot.spec.ts` (798) | `tests/1to1/boot/app_boot/test_app_boot.py` |
| `boot/app-boot/tests/config-dump.spec.ts` (181) | `tests/1to1/boot/app_boot/test_config_dump.py` |
| `boot/app-boot/tests/config-reload.spec.ts` (397) | `tests/1to1/boot/app_boot/test_config_reload.py` |
| `boot/app-boot/tests/hmr-config.spec.ts` (190) | `tests/1to1/boot/app_boot/test_hmr_config.py` |
| `boot/app-boot/tests/profile.spec.ts` (895) | `tests/1to1/boot/app_boot/test_profile.py` |
| `boot/app-boot/tests/user-patches.spec.ts` (419) | `tests/1to1/boot/app_boot/test_user_patches.py` |
| `boot/cmdline/tests/cmdline.spec.ts` (329) | `tests/1to1/boot/cmdline/test_cmdline.py` |

- [ ] **Step 14.1: 逐 spec 移植（每个 spec 一个子步骤，TDD）**

顺序：cmdline → config-dump → hmr-config → config-reload → user-patches → profile → app-boot（由简到繁）。每个 spec：翻译全部断言（含 fixture 布置与临时文件布局）→ Run `.venv\Scripts\python.exe -m pytest tests/1to1/boot -q` → 新增用例若 FAIL，回到对应实现文件修正（允许触碰 `dsh/cordis/{profile,hmr,loader,environment}.py`、`dsh/harness.py`）→ 至全 PASS。跳过项（Node/TS 特有）在文件头注释引用原 spec 行号并说明。

- [ ] **Step 14.2: Win7 不可行用例排除清单核对**

对照原版 `vitest.config.ts` 的 windowsUnsupportedTests 逻辑，确认移植集与之语义一致（本仓库目标就是 Windows，bash 系类排除项不适用）。

---

### Task 15: 阶段收尾

- [ ] **Step 15.1: 全量回归**

Run: `.venv\Scripts\python.exe -m pytest tests -q 2>&1 | Select-Object -Last 3`
Expected: 全 PASS（≥ 728 + P1 新增，0 failed）

- [ ] **Step 15.2: 语法与约束抽查**

Run: `.venv\Scripts\python.exe -m compileall -q dsh tests`；抽查改动文件无 3.9+ 语法（`rg` 不可用则用 `Select-String -Pattern ":\s*(list|dict|tuple|set)\[" -Path (改动文件)`）

- [ ] **Step 15.3: 阶段提交（唯一一次 commit）**

```bash
git add -A
git commit -m "P1: cordis foundation 1:1 alignment (17 file-pairs, <MUST-FIX> fixes, app-boot/cmdline specs ported)"
```

提交信息中 `<MUST-FIX>` 替换为 Task 1.2 记录的实际数量。
