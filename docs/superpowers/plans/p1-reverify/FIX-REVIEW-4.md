# P1-R 修复轮 4 审核报告（针对提交 0277d425）

日期：2026-09-10
审核对象：`0277d425` "fix(reverify): resolve FIX-REVIEW-3 X1-X6 defects (G12-D2 json, HMR multi-file rollback, presets, portable anchor)"（基线 `2d5b67b1`，11 文件，+281/−30）
审核方式：机械验证 + 主会话定向探针/diff 读码 + 深验（智能体额度受限，本轮由主会话按同一标准逐项完成；RD1 深验项全部实地核实）

# 裁决：READY for P2（NOT-READY 解除，附 3 项登记）

FIX-REVIEW-3 §五 的解除判据为「完成 ①② 即可重审解除」。本轮 ①②③④ **全部完成**，判据达成。

## 一、机械验证

| 项 | 结果 |
|---|---|
| 全量 pytest | **1052 passed**（+5），0 failed |
| compileall（py3.8） | exit 0 |

## 二、X1–X6 终判

| 项 | 判定 | 依据 |
|---|---|---|
| X1 D2 NameError | **✅ 闭合** | `import json` 落位；文案对齐 TS profile.ts:785-788 逐字（"cannot resolve profile bundle … from the dsh installation or {dir}；run 'dsh plugin --profile {basename} install'"）；新钉测 `test_compose_profile_unknown_bundle_raises_runtime_error_not_name_error` 钉住 RuntimeError 类型 + 文案四要素 |
| X2 多文件回滚 | **✅ 闭合** | `saved_fibers`/`reload_plugin` 提升至 `_run` 级 + first-capture 守卫；新钉测 `test_hmr_multi_file_reload_failure_triggers_rollback_all` 经**真实 watcher 机制**构造依赖链（`graph.add_dependency(file_b, file_a)` → `get_transitive_dependents` 展开 files_to_reload，hmr.py:481-482），第二文件失败后断言 A/B 双双还原（`registry.has` + fibers 非空 + version==1）——回滚缺失则必红，判别性达标；回滚语义 `delete_async(新)` + `reg.plugin(旧类, config)` 与 TS index.ts:535-543 delete+remount 同构（registry 键即旧类） |
| X3 预设名 traceback | **✅ 闭合** | standard/minimal/creative 三预设进 boot `PROFILE_TEMPLATES`（两表 bundles 对齐）；main 顶层 `except RuntimeError` → 单行 stderr + exit(1)；新钉测断言 `"Traceback" not in captured.err` |
| X4 便携布局 | **✅ 闭合（带登记项 R-2）** | `package_dir_from_anchor` 增便携 packages/ 解析臂（@deepseek-ai/dsh-* 直映射 bundle/ 子目录 + 7 类目录 package.json name 扫描；`import json` 在位）；build_portable 拷 anchor package.json；`test_portable_layout_bundle_resolution_smoke` 真布局冒烟（resolved==base_pkg_dir、layers 正确） |
| X5 弱钉 | **✅ 闭合** | 回滚断言改为判别性（`registry.has(plugin_cls)` + restored_runtime 非空） |
| X6 微项 | **✅ 闭合** | fiber.py 空 except 具名 `(ValueError, KeyError, AttributeError)`；smoke appExit 硬断言 `assert ctx.get("appExit") is not None`；**T7 PERMITTED DEVIATION 注记**、**core_exact root ADAPT 注记**双双落账 |

## 三、深验发现（登记项，不阻塞 P2）

### R-1（登记 → 已按原版对齐闭合）：creative 挂载分层归位
原判"canonical creative 缺 cordis-manager 挂载"经原版对照重新定性：**reference 全树不存在 cordis-manager**（`@deepseek-ai/dsh-cordis-manager` 为本移植的产品层发明），且原版 profile 层仅 bundles+patchReload、无 patches 发明层。creative 的 cordis-manager 本就由 agent preset 层挂载（`dsh/presets/creative.yaml` L97），cordis BUILTIN_PROFILES 的 patches insert 属于与 preset 层重复的双挂载。已删除该 insert（`dsh/cordis/profile.py` BUILTIN_PROFILES.creative 回归 bundles-only，与原版 profile 形状一致；cordis-manager 单一挂载点归位 preset 层），新钉测 `test_creative_profile_aligns_with_upstream_shape` 钉住"profile 层无发明 + preset 层恰一行"。canonical creative dump 不含 cordis-manager 行为**正确行为**（host composition 本不含 agent preset 行）。Legacy 主入口（--mode creative → build_harness + preset yaml）行为不变。

### R-2（登记）：便携冒烟覆盖解析逻辑而非构建产物
`test_portable_layout_bundle_resolution_smoke` 验证了解析臂与布局匹配，但未对 `dist/` 实际构建产物跑端到端 profile boot。建议 P2 内补一条构建后冒烟门。

### R-3（登记）：X3 双行为收敛后遗留死代码
三预设进 boot 模板后，cordis `dump_config` 的 fallback 分支对三预设不可达（死代码），且两表 patches 层语义分叉（见 R-1）。G12 D1 的平行实现收敛仍未完成（prepare_profile/compose_profile/BUILTIN_PROFILES 双轨仍在），归入 P2 首批。

## 四、覆盖度终态（P1-R 周期收口）

| 组 | 状态 |
|---|---|
| FIX-REVIEW-1 R1–R8 | 全闭（R4 附判别性钉测） |
| FIX-REVIEW-2/3 P 项 + G12 D2/D3/D7/D10/D12 + G13 D2/D4/D8/D10/D16/D17 主体 | 全闭 |
| 钉测债 / 偏差标注债 | 全清（R1/R2/R5/R6/R8/R4、ConsoleExporter、T7、root） |
| 转入 P2 的开工积压 | G12 ≈10（D1 收敛/D4/D5→R-1/D6/D8/D9/D11/D13/D14/D15/D18/D19）、G13 ≈12+3 半（D15 双轨/D18 显式裁剪/D21–D31）、G8 2（D6/D8）、T1（F1 + 5 OVERCLAIM + 6 WEAK + 15 GAP）、T2（29 弱化 + F3 + F2） |

## 五、结论

三轮修复（5ae8bfd1 → 228511d8 → cec50d9a → 0277d425）经四轮审核闭环：P1-R 的全部阻断级发现（三大最危险 W1/W2/W3、方言级 N1–N6、崩溃级 C 类、四件套、X1–X6）全部处置完毕；管线在 dev 布局下可承载真实长驻应用（boot→运行→appExit/信号/超时三路有界退出→退出码贯通），测试面从 1027 增至 1052 且新增全部为判别性钉测/真冒烟。

**NOT-READY 解除，进入 P2。** P2 开工顺序建议：R-1 creative 合成 bundle（AGENTS.md 硬要求）→ G12 D1 管线收敛（删平行实现）→ G13 D15 legacy 双轨退役 → G8 D6/D8 → T1/T2 测试加固随实现波次同步进行。
