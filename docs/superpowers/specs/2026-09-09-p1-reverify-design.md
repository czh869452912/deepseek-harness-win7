# P1-R 独立重审设计（cordis 地基盲审）

日期：2026-09-09
状态：已获用户批准的设计
前置：P1（cordis 地基 1:1 对齐）已于 2026-09-07 关闭（1027 测试全绿，见 `docs/superpowers/plans/2026-09-03-p1-review.md` F7）。用户对前轮修复准确性存疑，要求在进入 P2 前做一轮**不预设旧结论正确**的独立重审。

## 1. 目标与判定基准

- 范围：
  - 实现层：`dsh/cordis/` 全部 16 包 + `dsh/boot/` + `dsh/harness.py` 装配
  - 测试层：`tests/1to1/cordis/` 与 `tests/1to1/boot/` 的保真度
  - 遗留层：9 项显式延后项复核（loader D10/D12/D13、hmr D3/D4/D5、schema D13/D14、schema D7 残留）
- 唯一权威：`reference/vendor/*`、`reference/packages/{boot,util}/*` 的 TS 源码
- 允许偏离仅两条：Python 3.8.10 语法/标准库限制；Windows 7 SP1 运行环境限制（同总设计 §1）
- 产出：全新差异报告集 + 终审裁决（Ready for P2 / Not Ready + 修复波次建议）
- **本阶段不改产品代码**：报告交用户过目后，修复波次另行决策与执行

## 2. 盲审智能体分组（13 实现 + 2 测试，并行派发）

| 组 | Python 侧 | TS 权威侧 |
|---|---|---|
| G1 | dsh/cordis/utils.py | vendor/cosmokit/src |
| G2 | cordis/registry.py + service.py + reflect.py | vendor/cordis/src/{plugin,registry,service,reflect}.ts |
| G3 | cordis/events.py | vendor/cordis/src/events.ts |
| G4 | cordis/timer.py | vendor/cordis timer 插件 |
| G5 | cordis/fiber.py | vendor/cordis/src/fiber.ts |
| G6 | cordis/context.py | vendor/cordis/src/context.ts |
| G7 | cordis/schema.py（含 D13/D14/D7 遗留复核） | vendor/schemastery/src |
| G8 | cordis/logger.py | vendor/logger-console/src |
| G9 | cordis/hmr.py（含 D3/D4/D5 复核） | vendor/hmr/src |
| G10 | cordis/include.py | vendor/include/src |
| G11 | cordis/loader.py（含 D10/D12/D13 复核） | vendor/loader/src |
| G12 | cordis/profile.py + environment.py | packages/boot/{profile,environment} |
| G13 | dsh/boot/* + harness.py + cmdline.py | packages/boot/{app-boot,cmdline} |
| T1 | tests/1to1/cordis/ 全部 | vendor/cordis 各包 test/ |
| T2 | tests/1to1/boot/ 全部 | packages/boot/{app-boot,cmdline} tests |

## 3. 盲审任务规格

- 智能体输入（仅限）：TS 权威文件路径 + 对应 Python 文件路径 + 允许偏离清单（AGENTS.md §3 摘要）
- 禁止读取：`docs/superpowers/plans/p1-reports/`、`docs/superpowers/plans/2026-09-03-p1-review.md`、git log/diff 结论——防止锚定偏差
- 差异报告格式（逐条）：
  - 编号 D<n>（差异）/ T<n>（测试缺口）
  - TS 引文：file:line + 关键代码摘录
  - Python 现状：file:line + 行为描述
  - 判定：MUST-FIX（设计不一致）/ ADAPT（py3.8/win7 合法偏离）/ DEVIATION-PERMITTED（需记录的许可偏差）
  - 建议修法 + 不确定项标注 PROBE 候选
- T 组额外核对：原版 it() → test_ 函数映射完整性、断言语义等价性、是否钉错语义、弱断言、虚报覆盖

## 4. 交叉比对与探针裁决

- 主会话将新报告对照旧 17 报告 + 修复记录，逐条分类：**NEW**（新漏项）/ **WRONG-FIX**（修错）/ **REGRESSED**（修对但回归）/ **CONFIRMED**（确认已修）
- 纸面争议项写可执行行为探针（`%TEMP%\opencode` 下运行后清理）实证裁决，探针结果记入报告
- 终审报告：verdict + 分类汇总表 + 修复波次建议

## 5. 验收标准

- 15 份盲审报告 + 交叉比对表 + 终审报告落盘 `docs/superpowers/plans/p1-reverify/`
- 机械验证：全量 pytest 全绿、`compileall` 通过（审查过程不得破坏现状）
- 报告与裁决交用户过目，修复波次由用户另行拍板

## 6. 风险与对策

- 锚定偏差：盲审输入白名单 + 禁读清单，违例即重派
- 智能体误报：所有 MUST-FIX 须经主会话抽样复核（TS 引文核实）后才入终审表；争议走探针
- 规模：单包报告过大时按子模块拆分为多报告（如 loader 拆 config/patch/plugin 三份）
