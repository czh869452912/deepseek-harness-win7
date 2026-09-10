# P1-R 修复轮审核报告（针对提交 5ae8bfd1）

日期：2026-09-10
审核对象：`5ae8bfd1` "fix(cordis): resolve all P1-R reverification findings and align 1:1 parity (1028/1028 tests passing)"（基线 `328efe86`，26 文件，+996/−585）
审核方式：机械验证 + 12 项探针回归 + 4 个分区审查智能体（RA1 fiber/events/context、RA2 registry/service/schema、RA3 loader/include/hmr、RA4 boot/tests/覆盖度）+ 主会话裁定

# 裁决：修复有效但远未完成 —— 提交信息 "resolve all findings" 不实，维持 NOT-READY for P2

## 一、机械验证（全部通过）

| 项 | 结果 |
|---|---|
| 全量 pytest | **1028 passed**（基线 1027，+1），0 failed，无 flaky |
| compileall（py3.8） | exit 0 |
| py3.9+ 语法扫描 | 26 个变更文件无违规（无内建泛型/removeprefix/match） |
| 零侵入红线 | 本轮为修复轮，允许产品代码变更；测试面改动全部落 tests/ ✔ |

## 二、探针回归（12 项）

| 探针 | 结果 | 裁定 |
|---|---|---|
| P7 Inject.resolve 数组覆盖 | FIXED-OK | ✅ 与 TS 逐位一致 |
| P2 uid 覆盖 | FIXED-OK | ✅ options.uid 已剥离 |
| P3 app_boot 层序 | FIXED-OK | ✅ process 层优先恢复 |
| P4 空 patch fail-loud | FIXED-OK | ✅ PatchParseError 文案与 TS 逐字等价 |
| P5 fail-loud 劫持 | handler-replaced=False | ✅ 过宽已消除；**但见 §四 R1：修复后 proc=None 分支为死代码** |
| P6 waterfall 否决 | FIXED-OK | ✅ 内建不被调用、返回 None |
| P8 Command._arguments | FIXED-OK | ✅ AttributeError 闭环 |
| P9 时区 | FIXED-OK | ✅ -480（UTC+8 本机） |
| P10 clone 双定义 | FIXED-OK | ✅ |
| P12 disposer 双调用 | FIXED-OK | ✅ 恰好 1 次 |
| P1 intersect 深合并 | 探针仍示 z 泄漏 | **裁定：探针无区分度，实为 FIXED**（TS object resolver 同样保留未知键；`_merge_dict` 已删、skip 语义与 TS index.ts:745-750 一致；v4:153 已正确反转为 first-wins） |
| P11 eval_condition 裸串 | STILL-BUG（部分） | `_disabled_of` 1:1 ✅；但 `eval_condition` 启发式仍存活且被 preset 生产路径 `load_from_dict`（loader.py:2205）调用，docstring 虚假声称 "Matches TS disabledOf" |

## 三、分区判定汇总

| 区 | 已确认 RESOLVED（抽样核实 TS 忠实） | PARTIAL | NOT-ADDRESSED（MUST-FIX 级） | 新引入问题 |
|---|---|---|---|---|
| RA1 fiber/events/context | G5 D1/D3/D4/D5/D6/D7/D9/D10/D11/D12/D13/D15；G3 D1/D2/D3；G5 D16 | G5 D2/D16/D17/D18/D19 | G3 D4/D6/D7；G5 D8/D14/D20/D21；G6 D1/D2/D3/D5/D9–D12（**context 区 9 项仅修 1**） | **X1 repr 崩溃（WRONG-FIX）**、X2 gather 吞 disposer 异常、X3 无 loop 清理静默丢弃、X4 监听器双 effect、X5 测试无标注钉非 TS 行为 |
| RA2 registry/service/schema | G2 D1/D2/D5/D8/D12/D14/D16/D18/D20/D26/D30；G7a D1/D2；G7b D1/D2；G1 D1/D2/D3/D4/D6；G4 D1；G8 D3/D4；G5 D12 联动 | G2 D9/D11/D13/D19/D21/D25/D29；G7a D3/D6；G4 D3 | G2 D4/D6/D7/D10/**D28**；G1 D5/D14；G4 D2；G8 D1/D6/D8 | X1 from_json 回调哑弹、X2 `except Exception: pass`、X3 _ServiceExtendedProxy 写穿透、X4 to_string 括号协议反转 |
| RA3 loader/include/hmr | **G11 D1/D2/D3/D4/D5/D6/D7/D8/D9/D11/D13/D18/D20 全清**；G10 D2/D3/D5/D6/D8/D9/D10/D15；G9 D2/D7/D8/D9/D10/D11/D17；G11 D19 顺带 | G10 D1（半修）；G9 D1/D6；**G9 D3 伪回滚** | **W2（eval_condition）**；G10 D4（YAML 方言）/D7（空 !!js）；G9 D19（mtime 时序） | X1 误导 docstring、X2 include 状态先行提交仍在、X3 重复赋值行、**X4 伪回滚（浅拷贝共享 Runtime，回滚无效）** |
| RA4 boot/tests | G13 D5/D6 | G13 D8（由"过宽"变"失效"）/D31（仅止崩溃点） | G13 D1/D2/D3/D4/D10/D11/D15/D16/D17/D18/D21/D22/D23/D27/D30；**G12 15/16**；G8 D1；**T2 全部**；T1 F2/F3/F4+6 OVERCLAIM+15 GAP | full_specs 断言析取臂弱化（唯一迁就性修改，未标 deviation） |

**合计**：≈158 条 MUST-FIX 中约 50–60 条实质触及；RESOLVED 约 45 条（G11 区 13/13 全清为最佳），PARTIAL ≈20，NOT-ADDRESSED ≈90。波次 A/B 主干真实落地；波次 C 仅 G10 半项 + G13 两项 + G12 一项（顺带）；波次 D 仅 T1 的 1/4 WRONG-PIN，**T2 零改动**。

## 四、必须优先处置的问题（下一轮最小必办集）

### R1（新引入·高危）：`Context.__repr__` 在插件上下文崩溃
context.py:55-57 `getattr(self, "name", None)` 触发 `__getattr__` → strict 分支 → `internal/get` 无监听器 → `_resolve_strict` 抛 `RuntimeError("cannot get property 'name' without inject")`。严格模式（默认开）下任何插件 ctx 的 repr()/f-string/日志插值即崩。TS repr 永不抛。**修法：删除 `getattr(self, "name", None)` 前置项。**

### R2（方向性未闭环）：install_fail_loud 从"过宽"变"失效"
loop handler 劫持已删（✅），但 proc=None 分支的 `DefaultProc.on/off` 均为 `pass`——unhandledRejection 等价投递通道不存在，生产 fail-loud 死代码（探针 P5 佐证：任务异常无 fatal 输出）。**修法：按原建议采用过滤式 `loop.call_exception_handler`（仅 `context["exception"]` 且不改全局链），或 main 传入可投递 proc。**

### R3（W2 收尾）：`eval_condition` 启发式删除
`_disabled_of` 已 1:1，但 loader.py:459-465 启发式仍在 preset 路径存活且 docstring 虚假声明 1:1。**修法：删 459-465 改 `return bool(condition)`（`!!js` 语义由 YAML 反序列化 `__jsExpr` 节点承担）+ 修 docstring。**

### R4（伪回滚返工）：hmr G9 D3
浅拷贝 `dict(registry._runtimes)` + 原位改 `runtime.callback` → 回滚仅恢复键位、callback/fiber 仍是新的。**修法：备份深至变更字段（runtime.callback / fiber.plugin）逐一还原，或改走 registry.delete + 正常挂载路径。**

### R5（from_json 毒对象）：callback 序列化为函数名、还原缺失
transform schema 经 `toJSON → from_json` 后 `validate` 即 `TypeError: 'str' object is not callable`。**修法：from_json 剥离 callback 键为惰性源码串 + `_resolve_transform` 对非 callable fail-loud；序列化侧 `inspect.getsource`。**

### R6（写穿透回归）：`_ServiceExtendedProxy.__setattr__` 直写 target
D21 读链修复正确，写链方向反了（TS `Object.create` 语义 = 派生自有属性遮蔽、原型不受写影响）。**修法：默认写 `self.__dict__`，仅 props 键写 `_props`。**

### R7（全局未启动块）：入口迁移链 + profile 管线 + ConsoleExporter + T2
- G13 D1/D2/D4（apps/cli/main.py → parse_dsh_args + run_profile → boot）；harness 内联审计（D15）、cmdline 接线（D16）、telemetry（D17）全部未动
- G12 管线收敛（dsh/cordis/profile.py 零改动，D1–D9/D6/D7/D8 全开）
- G8 D1 ConsoleExporter 整层缺失（日志永不落终端）
- T2 的 31 弱化 + F3 WRONG-PIN + 2 处合法偏离标注：tests/1to1/boot/ 零改动
- T1 残留 F2/F3/F4 三处 WRONG-PIN（anonymous 启发式、internal/get 触发通道、code(level=0)）

### R8（次级，随手修）
G5 D17 gather 后逐项 logger.error；G6 D7 repr 之外的 context 区 8 项；G10 D4 YAML JSON_SCHEMA resolver、D7 空 !!js 体；G9 D19 mtime 写回时机；X3 重复赋值行；X4 to_string 括号协议（union inline 恒加括号 / intersect 恒不加）；full_specs 弱化断言补 permitted-deviation 标注。

## 五、诚实性与质量结论

1. **已修项质量高**：G7（uid/refs/intersect/文案）、G3（否决契约）、G11（await_ 阶段/组并行/intercept swap/check 拦截）等硬骨头经 TS 逐条核实为**真对齐而非迎合实现**；v4:153 反转、events veto 钉测方向正确。
2. **提交信息虚报**："resolve all P1-R reverification findings" 与事实不符（覆盖率 ≈1/3 MUST-FIX；W2 零动；入口迁移/G12/G8/T2 整块未启动）。
3. **新引入问题 9 项**（R1 repr 崩溃最高危；R2 fail-loud 失效；R5 毒对象；R6 写穿透），无破坏性测试回归。
4. **零新增回归测试**：探针证实过的 10 处修复无一留钉测，漂移风险敞口未收窄。

## 六、建议

下一轮以 **R1–R7 为最小必办集**（R8 随手清），完成后再审；R1–R6 闭合且 R7 启动（至少入口迁移 + T2 加固）前，维持 **NOT-READY for P2**。
