# P1-R 探针裁决记录

日期：2026-09-09。探针脚本：`%TEMP%\opencode\p1r-probes\probe_p1r.py`（venv python 3.8.10 运行，运行后删除）。全部探针只读导入 `dsh.*`，未修改仓库文件。

| 探针 | 裁决对象 | 实际输出 | 裁决 |
|---|---|---|---|
| P1 | G7b D1 intersect 同键深合并 | `out={'a': {'x': 1, 'z': 2}}`（TS 预测 `{'a':{'x':1}}`，z 泄漏） | **CONFIRMED-BUG** |
| P2 | G7a D1 uid 可被 options 覆盖 | options uid=999 → 实例 uid=999（TS 强制全局递增） | **CONFIRMED-BUG** |
| P3 | G12 D18 app_boot 层序倒置 | `get('FOO').source='user-env'`（TS process 最优先） | **CONFIRMED-BUG** |
| P4 | G13 D5 空 patch 文档静默为空层 | 注释-only 文档 → `[]`（TS 抛 "must be a top-level YAML array"） | **CONFIRMED-BUG** |
| P5 | G13 D8 install_fail_loud 劫持 | `handler-replaced=True`；任务异常在探针窗口内未产出 "fatal" stderr（可能经 proc.stderr 通道未被 redirect 捕获） | **PARTIAL**：handler 劫持（替换 loop 默认异常处理器）已实证，与 TS 仅注册 unhandledRejection 的偏离成立；fatal 输出传播链未复现，留待修复轮验证 |
| P6 | G3 D3 / T1 F1 waterfall None 续传 | 无 next 形参监听器返回 None → `result='BUILTIN', builtin_called=True`（TS：否决、内建不执行） | **CONFIRMED-BUG**（且 T1 F1 的测试确实把该行为钉成了契约） |
| P7 | G2 D1 Inject.resolve 数组不覆盖 | 数组注入保留旧值 `{'x': 1}`（TS 无条件置 null） | **CONFIRMED-BUG** |
| P8 | G13 D31 Command._arguments 未初始化 | `AttributeError: 'Command' object has no attribute '_arguments'` | **CONFIRMED-BUG**（潜伏崩溃点实锤） |
| P9 | G1 D4 时区默认 0 | `Time._timezone_offset=0`（TS 本机时区） | **CONFIRMED-BUG** |
| P10 | G1 D1 clone 双定义 | `def clone count=2` | **CONFIRMED-BUG**（旧 Minor 确认） |

**汇总**：10 探针 = 9 CONFIRMED-BUG + 1 PARTIAL，0 反证。盲审报告的抽查通过率 100%（连同 Task 16 的 5 项静态抽查，共 15 项核实无一误报）。
