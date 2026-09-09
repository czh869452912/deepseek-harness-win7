# P1-R 独立重审终审裁决（cordis 地基盲审）

日期：2026-09-09
审查方式：15 组盲审智能体（13 实现 + 2 测试保真度；G7 拆 a/b 共 14 份实现报告）+ 交叉比对 + 15 项核实（5 静态引文抽查 + 10 运行探针）
基线：HEAD `60ea8145`，1027 passed，全程零产品代码改动（机械验证通过）

# 裁决：NOT-READY for P2

## 一、总体判定

1. **诚实性成立**：旧 9 项显式延后项（loader D10/D12/D13、hmr D3/D4/D5、schema D13/D14、schema D7 残留、入口 boot 管线）经盲审逐条核实**全部仍开放**，无一被顺手修掉、无一虚报闭合（CROSS.md §2）。
2. **旧修复本体可信**：C1/C3/C4/C5/C6、I3、I8、I12 的核心修复经盲审与探针证实正确（CROSS.md §4）；仅发现伴生缺陷（C2 的实例化次序、W3 的 fail-loud 语义）。
3. **但存在重大新漏项**：盲审新发现 **≈95 条旧 17 报告从未覆盖的 MUST-FIX**（合计 ≈158 条 MUST-FIX / ≈50 ADAPT / ≈95 DEVIATION-PERMITTED），其中 3 条为「承诺已落地」实未落地或方向错误。
4. **测试面**：数量 1:1 成立（T2 152/152 映射、缺失 0），但存在 **62 处质量缺陷**（T1 5 错钉/虚报 + T2 31 弱化等），其中 5 处 WRONG-PIN 会把错误行为钉成契约。

## 二、三类最危险发现（必须优先修复）

### A. 承诺未落地 / 方向错误（WRONG-FIX）
| # | 项 | 证据 |
|---|---|---|
| W1 | 旧 I1（plugin 契约 D2–D6 整组）宣称 wave-2 落地，实测 6+ 项缺失 | G2 D1/D2/D4/D5/D8/D16；探针 P7 实证数组注入不覆盖 |
| W2 | 旧 I9（eval_condition 布尔化）宣称 wave-2 落地，实测裸串仍被求值 | G11 D10 + G12 D10（`disabled: "!!js false"` 真值反转） |
| W3 | install_fail_loud 接 loop 异常处理器语义过宽（TS 仅 unhandledRejection） | G13 D8；探针 P5 实证 handler 被替换 |

### B. 方言级/生命周期级错误（影响 Web GUI 与配置正确性）
| # | 项 | 探针 |
|---|---|---|
| N1 | intersect 同键 dict 深合并（TS 首值胜出），v4 测试把偏差固化 | P1 ✅ 实证泄漏 |
| N2 | waterfall 签名嗅探自动续链/回穿（TS next 否决契约反转） | P6 ✅ 实证 |
| N3 | include.init 同步生成器 + 孤儿 apply 任务 + 状态先行提交 | G10 D1（静态+源码核实） |
| N4 | YAML 1.1 vs JSON_SCHEMA（`disabled: no` 布尔反转） | G10 D4 |
| N5 | app_boot 层序倒置（user-env 覆盖 process） | P3 ✅ 实证 |
| N6 | 空 patch 文档静默为空层（TS fail-loud） | P4 ✅ 实证 |

### C. 潜伏崩溃 / 资源缺陷
| # | 项 | 探针 |
|---|---|---|
| C-1 | Command._arguments 未初始化（AttributeError） | P8 ✅ 实证 |
| C-2 | effect 取消屏障 disposer 双调用 | G5 D9 |
| C-3 | registry.delete() asyncio.run 换环 | G2 D11 |
| C-4 | uid 可被 options 覆盖（refs 去重破坏） | P2 ✅ 实证 |
| C-5 | logger-console ConsoleExporter 整层缺失（日志永不落终端） | G8 D1 |
| C-6 | Service 符号双表（check 谓词主路径失效） | G2 D18/D19 |

## 三、修复波次建议（依赖序）

1. **波次 A（地基）**：G5 effect 引擎（D9/D10/D11/D17）→ G3 events（fiber.effect 挂接 D1/D2 + 否决契约 D3/D4）→ G2 registry/service 契约（W1 整组 + D11/D18/D19/D20/D21/D28）
2. **波次 B（loader/schema/hmr）**：G11（D5/D6/D7/D8/D9/D10/W2/D13/D18/D20）→ G7（uid/refs/callback 往返 + intersect skip + 错误文案，同步反转 v4:153 测试）→ G9（externals/事务/ignored/debounce/D10/D18/D19）
3. **波次 C（include/profile/boot/日志）**：G10（init 生命周期 D1、YAML 方言 D4、fail-loud D5/D7/D8）→ G12（管线收敛到 dsh/boot/profile.py 正典 + D2/D3/D6/D7/D8/D11/D12/D13/D18/D19）→ G13（入口迁移 D1/D2/D4 + D5/D6/D8/D15/D16/D17/D27/D31）→ G8（ConsoleExporter D1 + D3/D6/D8）
4. **波次 D（测试修复）**：T1 4 WRONG-PIN + 6 OVERCLAIM + 15 GAP（top）；T2 31 弱化加固 + 2 处合法偏离 docstring 标注

完成波次 A–C 后建议再做一轮小范围复审（针对修复 diff），随后方可进入 P2。

## 四、许可偏差清单更新建议（记录在案即可）

DEVIATION-PERMITTED ≈95 条已按组记录在 01–15 报告；其中需要集中文档化的横向约定：
1. caller_ctx kwarg / 属性嗅探协议（G3 D8 / G6 D18 / G2 D32）——Python 无 this/Proxy 的全库统一替代，需在三处文档化同一契约；
2. Python-only 便利层（Fiber.disposable/error、Schema.dynamic/computed/to_json_schema、loader load_from_dict 族）——需在移植说明中登记超集边界；
3. threading/无 loop 回退分支（G4 D5、G2 D11、G10 D13、G6 D17）——建议统一收敛为显式报错或单一回退策略，避免四处各自发明；
4. yaml Emitter 全局 monkeypatch（G11 D22）——违反可逆 effect 原则，长期应改为 dump 局部 Dumper。

## 五、审查产物索引

| 文件 | 内容 |
|---|---|
| 00-baseline.md | 基线快照（HEAD/pytest/零侵入红线） |
| 01–13*.md | 14 份实现盲审报告（G1–G13，G7 拆 a/b） |
| 14/15*.md | 2 份测试保真度盲审报告 |
| CROSS.md | 交叉比对矩阵（分类汇总 + 9 遗留核对 + W/N/C 三表） |
| PROBES.md | 10 项运行探针裁决记录（9 CONFIRMED + 1 PARTIAL） |
| VERDICT.md | 本终审报告 |

## 六、给下轮工作的三条硬约束

1. 修复必须与测试同步改（尤其 v4:153 深合并断言、T1 F1/F2/F3/F4 四处错钉）——否则旧错钉会把修复判为回归。
2. 管线收敛优先于逐点打补丁：profile/include/boot 的修复应先删平行实现（G12 D1/G10 管线/G13 D1 双轨审计），再对齐逐项语义，避免三轨并存。
3. 每波次结束跑全量 pytest + compileall + 探针回归（PROBES.md 的 10 项可作为波次验收清单）。
