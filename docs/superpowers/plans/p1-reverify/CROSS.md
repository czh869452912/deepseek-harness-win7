# P1-R 交叉比对矩阵（盲审 × 旧报告 × 修复记录）

日期：2026-09-09
方法：16 份盲审报告（01–15，G7 拆 a/b）全部 D/F 条目，对照旧 17 报告（`p1-reports/1..17`）与三轮复审结论（`2026-09-03-p1-review.md`，含 F7 收尾记录）逐条分类。主会话抽查 5 项高影响 MUST-FIX 的 TS 引文与 Python 现状，全部属实（tree.ts await_ 阶段1、registry.ts Inject.resolve 数组覆盖、app_boot.py 倒序层、_parse_patch_list None→[]、schema.py uid 覆盖）。

## 1. 分类汇总

| 组 | MUST-FIX | ADAPT | DEVIATION-PERMITTED | 与旧报告重叠判定 |
|---|---|---|---|---|
| G1-utils | 7 | 1+ | 7 | 3 项为旧 Minor 确认仍开放 |
| G2-plugin | 24 | 4 | 8 | **I1 整组未落地**（wave-2 承诺） |
| G3-events | 6 | 6 | 7 | I2 决策本体成立，测试标记缺失 |
| G4-timer | 3 | 2 | 4 | 全部 NEW |
| G5-fiber | 21 | 3 | 8 | C2/C3/C4 本体 CONFIRMED，伴生缺陷 NEW |
| G6-context | 9 | 4 | 6 | I3 本体 CONFIRMED，根上下文分支 NEW |
| G7-schema(a+b) | 10 | 6 | 12+ | D13/D14/D7 残留全部 CONFIRMED 仍开放 |
| G8-logger | 4 | 2 | 7 | ConsoleExporter 整层缺失 = NEW（旧轮从未发现） |
| G9-hmr | 15 | 4 | 3 | D3/D4/D5 残留 CONFIRMED 仍开放 |
| G10-include | 10 | 4 | 9 | 全部 NEW（YAML 方言、init 生命周期等） |
| G11-loader | 14 | 5 | 9 | D10/D12/D13 CONFIRMED；**I9 未落地** |
| G12-profile | 16 | 3 | 4 | 数据面 86/24 行 CONFIRMED 忠实；管线缺陷 NEW |
| G13-boot | 19 | 6 | 6 | 生产入口未迁移 CONFIRMED；**install_fail_loud 语义过宽 = WRONG-FIX** |
| T1-tests-cordis | — | — | — | 4 WRONG-PIN、6 OVERCLAIM、7 WEAK、15 GAP |
| T2-tests-boot | — | — | — | 152/152 映射完整；31 弱化、1 WRONG-PIN、1 OVERCLAIM |
| **合计** | **≈158** | **≈50** | **≈95** | |

## 2. 旧 9 项遗留逐条核对（P1 关闭时显式延后项）

| 旧编号 | 内容 | 新报告条目 | 判定 |
|---|---|---|---|
| loader D10 | [Service.check] await 拦截 | G11 D3 | ✅确认仍开放（MUST-FIX） |
| loader D12 | 'reload' 日志监听器 | G11 D4 | ✅确认仍开放（MUST-FIX） |
| loader D13 | isolate 告警 + intercept 整体替换 | G11 D8+D9 | ✅确认仍开放（MUST-FIX ×2） |
| hmr D3 | externals → exit() 全量重载 | G9 D1 | ✅确认仍开放（MUST-FIX） |
| hmr D4 | reload 事务/回滚 | G9 D3 | ✅确认仍开放（MUST-FIX） |
| hmr D5 | ignored 未消费 + root 默认 `['.']` | G9 D7 | ✅确认仍开放（MUST-FIX） |
| schema D13/D14 | preserve/constructor/callback 序列化 + refs 反序列化 | G7a D2+D3、G7b D3+D4 | ✅确认仍开放（MUST-FIX ×2） |
| schema D7 残留 | intersect 同键 dict 深合并 vs TS 跳过 | G7b D1 + T2 附注（v4 测试把偏差固化） | ✅确认仍开放，**且 v4 测试 WRONG-PIN 需一并修** |
| 入口 boot 管线 | main.py/build_harness 未切 dsh/boot | G13 D1 | ✅确认仍开放（MUST-FIX，G13 全链条展开） |

## 3. WRONG-FIX / 承诺未落地（旧轮声称处理但实测未达成或方向错误）

| # | 旧结论 | 盲审实证 | 分类 |
|---|---|---|---|
| W1 | I1（wave-2）：plugin 契约 D2–D6「按报告 2 逐项实现 + T1–T5」 | G2 D1（数组注入不覆盖）、D2（发明 required 键）、D4（@inject 缺服务抛错而非延迟）、D5（非法 target 静默）、D8（错误文案）、D16（构造契约 `__init__(config)` vs TS `new(ctx,config)`） | **PROMISED-NOT-LANDED** |
| W2 | I9（wave-2）：eval_condition 改为 `is_js_expr → evaluate else bool` | G11 D10 + G12 D10：裸串含 `process.platform/env` 子串仍被求值，`disabled: "!!js false"` 真值反转 | **PROMISED-NOT-LANDED** |
| W3 | wave-6：「install_fail_loud 接 loop.set_exception_handler 并在 CLI 装配」 | G13 D8：loop 异常处理器劫持过宽（任意任务异常→exit(1)），TS 仅 unhandledRejection；双重安装加剧 | **WRONG-FIX**（接线完成但语义偏离 TS） |
| W4 | I2 决策（Option B：reducer=许可偏差+钉测） | T1 F1：`test_events_parity` 的 None-return 续传用例**未标** permitted deviation（同文件 d2 用例已正确标注） | **PARTIAL**（决策成立，落地标记缺半） |
| W5 | C2 修复（类插件实例化移入 _reload） | G5 D6：实例化发生在 `_resolve_config` **之前**，构造器拿到未校验 config（TS 相反） | C2 本体 CONFIRMED + **伴生 NEW**（次序缺陷） |

## 4. CONFIRMED（旧修复经盲审证实正确）

| 旧项 | 盲审证据 |
|---|---|
| C1 emit 单次执行 | G3 无双重执行发现；internal/dispatch 特判为另一独立问题（G3 D6） |
| C3 effect 启发式删除 + is_disposer 契约 | G5 D29 将 is_disposer 记为 PY-only API（许可）；启发式未见复活 |
| C4 异步 apply dispose 泄漏（epoch 复查） | G5 无该泄漏发现；相邻缺陷 D9（取消屏障双调用）为 NEW |
| C5 !!js 写回回落链 | G10 仅报空体被拒（D7，NEW 边角）与多键 representer 不对称（D17，DEVIATION） |
| C6 激活审计本体 | G13 映射表判 assert_entries_activated 1:1；空值短路（D6）为 NEW 边角 |
| I3 严格解析顺序 | G6 无子代/孙代 store 回溯缺陷发现；根上下文 strict 旁路（D9）为 NEW 分支 |
| I8 副本清收 | G12 确认 environment 版本为准；strip 语义（D11）为 NEW |
| I12 trim_slash/sanitize | G1 映射表判 1:1；format_property Unicode（D10）为 NEW minor |

## 5. 旧 Minor 确认仍开放（从未修复）

| 旧 Minor | 新报告 |
|---|---|
| 重复 clone 定义 | G1 D1 |
| Time 时区默认 0 | G1 D4 |
| parse_date 年份分支缺失 | G1 D5 |
| assert_active check_error 默认 True | G5 D12 |
| reflect 同值豁免（旧 Minor 6） | 16 份盲审均未覆盖该点（G2 主审 reflect.py 未报）——标注「fresh 未覆盖，维持记录」 |

## 6. NEW 发现Severity 摘要（全部为旧 17 报告未覆盖的新漏项，共 ≈95 条 MUST-FIX）

最高影响 NEW（修复波次排序建议）：
1. **G10 D1**：include.init 同步生成器 + apply 孤儿任务 + 状态先行提交（Web 模式下插件假激活、热重载失效）
2. **G10 D4**：YAML 1.1 vs JSON_SCHEMA（`disabled: no` 布尔反转，方言级）
3. **G12 D18**：app_boot 内部快照层序倒置（user-env 覆盖 process，与 TS 及自有 environment.py 均相反）
4. **G13 D31**：自制 Command 未初始化 `self._arguments`（潜伏 AttributeError）
5. **G13 D5 + G12 D3**：空 patch 文件静默为空层 + bundle 兜底 18 行（fail-loud 缺失）
6. **G11 D5/D6/D7**：await_ 阶段语义相反 + 组更新串行 + 错误双包装
7. **G5 D9**：effect 取消屏障 disposer 双调用（非幂等 disposer 真实故障）
8. **G2 D11/D18/D19**：delete() asyncio.run 换环 + Service 符号双表（check 谓词主路径失效）
9. **G8 D1**：logger-console ConsoleExporter 整层缺失（日志永不落终端）
10. **G7a D1**：uid 可被 options 覆盖（refs 去重破坏）

## 7. 测试保真度终表

- **T1（cordis 17 文件）**：WRONG-PIN ×4（F1 waterfall None 续传、F2 internal/get 触发通道、F3 anonymous 启发式、F4 code(level=0)）；OVERCLAIM ×6；WEAK ×7；GAP ×15（top）。GAP 重灾区：parallel AggregateError、serial 模式、INACTIVE_EFFECT 行为级、loader patch、hmr 模块重载。
- **T2（boot 8 spec，152 it）**：映射完整 152/152、缺失 0、多余 0；弱化 31；WRONG-PIN ×1（F3 disposed-mid-startup 时序前提未复刻）；OVERCLAIM ×1（F2 non-Error 用例实为 Error）；合法语言偏离 2 处（F17 裸串 throw、F19 ESM import 降级）需 docstring 标注。
- **结论**：测试面「数量 1:1 成立，质量存在 62 处需加固」；4+1 处 WRONG-PIN 会把错误行为钉成契约，修复实现时必须同步改测试（特别是 G7b D1 × v4:153）。

## 8. 终审结论

**NOT-READY for P2。**
- 旧 9 项遗留全部确认仍开放（无一被顺手修掉，也无虚报闭合——诚实性成立）。
- 但盲审新发现 ≈95 条旧报告从未覆盖的 MUST-FIX，其中 W1/W2 两条为「承诺已落地」实未落地，W3 一条为方向性 WRONG-FIX。
- 修复波次建议（依依赖序）：
  1. **波次 A（地基）**：G5 effect 引擎（D9/D10/D11/D17）、G3 events（D1/D2/D3/D4 fiber.effect 挂接 + 否决契约）、G2 registry/service 契约（W1 整组）
  2. **波次 B（loader/schema）**：G11（D5/D6/D7/D8/D9/D10/W2/D13）、G7（D1/D2/D3/D4/D6 + v4 测试反转）、G9 hmr（D1/D2/D3/D6/D7/D9/D19）
  3. **波次 C（include/profile/boot）**：G10（D1/D4/D5/D7/D8）、G12（D1–D9 管线收敛到 boot/profile.py）、G13（D1–D8/D15/D16/D17/D27/D31）、G8（D1 ConsoleExporter）
  4. **波次 D（测试修复）**：T1 4 WRONG-PIN + 6 OVERCLAIM 标注、T2 31 弱化加固、GAP top15 补测
