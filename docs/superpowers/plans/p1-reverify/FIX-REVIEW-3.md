# P1-R 修复轮 3 审核报告（针对提交 cec50d9a）

日期：2026-09-10
审核对象：`cec50d9a` "fix(pipeline): resolve FIX-REVIEW-2 runnable defects, fail-loud bundles, R4 HMR rollback and pin tests (1047/1047 passed)"（基线 `6fdcd33b`，16 文件，+652/−142）
审核方式：机械验证 + 定向探针/diff 读码 + 2 个分区终审智能体（RC1 管线可运行性、RC2 点修与覆盖度）

# 裁决：四件套全闭、管线达到可运行（B+）；R4/G12-D3/钉测债闭合，但 G12-D2 触发即 NameError、HMR 多文件回滚失效 —— NOT-READY 维持，距解除仅剩两处点修

## 一、机械验证

| 项 | 结果 |
|---|---|
| 全量 pytest | **1047 passed**（+15），0 failed |
| compileall（py3.8） | exit 0 |
| py3.8 语法 | 13 变更文件 ast 全过 |

## 二、FIX-REVIEW-2 最小必办集逐条核对

| §六 条目 | 判定 | 要点 |
|---|---|---|
| 1. 管线可运行四件套 | **✅ 全闭** | P-1 `shutdown()` 改返回已调度 Task（=TS `void shutdown.shutdown(code)`）；P-2 `signal.signal(SIGTERM→0/SIGINT→130)` + SignalShutdown.abort + watcher/appReady 补 aborted 臂 + suppress_shutdown_error 三条件同构（Windows 走 signal.signal 正确）；P-3 exit_code 追踪 + main `sys.exit(code)` 消费 + KI→130；P-4 `await shutdown.wait()` + wait_for_exit 旁路，挂死路径核查无遗漏（异常/超时/强退全置位） |
| 2. P-5/P-8/P-7 | **✅** | heal dict 形参 + 删吞异常；dump_config 兜底收窄（RuntimeError+does not exist+内建名判定）+ dsh_home 直传；plugin 模式 stderr+exit(1) 显式裁剪（G13 D18 转显式裁剪，应登记） |
| 3. R4 + R1/R6/R4 钉测 + P-10 冒烟 | **◐** | R4 机制闭合（delete_async→registry.plugin 重挂 + entry 迁移 + 回滚删新挂旧，对照 TS index.ts:400-548 骨架逐点成立；`_refresh` 空 except 消除；fiber.py has 守卫逐点同构）；R1/R6/R4 三笔钉测债**全闭**；P-10 三个新模块 322 行真冒烟/单元测试落地。**残缺见 §三 X2/X5** |
| 4. G12 D2/D3 | **D3 ✅ / D2 ✗** | D3：兜底数据 6 块整删、缺失/非 list/非 dict 三级 RuntimeError。D2：raise 已就位但 **`json` 未导入 → 触发即 NameError**（下 X1） |
| 5. 偏差标注清账 | **◐ 2/4** | R5 new-Function（schema.py docstring）✅、ConsoleExporter 偏差簇（logger.py docstring）✅；test_context T7 弱化、core_exact root 迁就未动 |

## 三、新发现（按严重度）

### X1（阻断）：G12 D2 的 fail-loud raise 自身崩溃
profile.py:282 使用 `{json.dumps(bname)}`，但全文件无 `import json` → 触发未知 bundle 时抛 **NameError** 而非目标 RuntimeError；dump_config 兜底只捕 RuntimeError，NameError 直穿 CLI 成裸栈。当前树内触发面窄（预设 bundles 全内建、自定义 profile 固定 `["dsh-base"]`），但该路径正是为"用户 manifest 携带未知 bundle"设防的，触发即坏；1047 全过恰说明零覆盖。**修法：补 `import json`；文案对齐权威实现 dsh/boot/profile.py:733-736；补触发钉测。**

### X2（R4 残缺）：HMR 多文件回滚只覆盖最后一个文件
`saved_fibers` 快照与闭包 `reload_plugin` 定义在 `for file_path in files_to_reload:` **循环体内**，每轮重绑；回滚循环在循环外调用时 `saved_fibers` 只是最后一个文件的快照——前序文件的 runtime 已被 delete_async 清空 fibers → `reg.plugin` 不被调用 → **旧类既不重挂也不回注册表，插件整体丢失**。多文件重载+后续文件失败（最需要回滚的场景）契约失效。**修法：saved_fibers 提升为 `_run` 级一次性快照；reload_plugin 函数级定义一次；补"依赖链两插件、第二个文件 apply 抛错"回滚钉测。**

### X3（中）：主入口对任务三大预设名未捕获 traceback
main.py 新 argv 路径 `run_dump_config/run_profile` → boot `load_profile` 对 standard/minimal/creative 抛 RuntimeError 无捕获 → 全栈回溯；而 legacy 同请求走 cordis 兜底成功——同请求双行为，且兜底 dump 产物缺溯源注释/telemetry 层。**修法：把"BUILTIN_PROFILES 名回落"收敛进 boot.prepare_profile（或对齐两张 profile 表）；main 顶层把 RuntimeError 呈现为一行 `dsh: …`。**

### X4（中高·使命级）：便携布局下新管线 bundle 解析全灭
INSTALL_ANCHOR 三候选在 dist 内全部不存在（build_portable 不拷 package.json/reference/）；`package_dir_from_anchor` 找 node_modules 布局也必失败 → 便携包内 profile boot/dump-config 正典路径无法启动任何 profile（dev 布局正常）。**修法：build_portable 落地 anchor + bundle 解析臂（或 resolve 增加便携 packages/ 布局分支）+ 便携包内加 profile-boot 冒烟门。**

### X5（测试强度）：回滚钉测无法区分"回滚开启 vs 缺失"
`fiber.plugin.version == 1` 断言在回滚整体失效时同样通过（旧 fiber 的 plugin 本就是旧实例）。建议补判别性断言：回滚后 `registry.has(old_cls)`、entry.fiber 指回、apply 计数递增。

### X6（微·登记即可）
D2 文案为意译（权威逐字文案已在 boot/profile.py:733-736）；`_read_bundle_patch` 缺 TS "failed to parse overlay" 包装/完整路径/entry 后缀/anchorInsertedPluginNames（实害零）；fiber.py:983 空 except 未命名；smoke 测试 appExit 软分支应改 `assert ctx.get("appExit") is not None`；shutdown 无 loop 分支 sys.exit 非主线程仅终结该线程；dispose 期二次 SIGTERM 退出码不保证 0。

## 四、覆盖度更新（对比 FIX-REVIEW-2 §五）

| 组 | 上轮剩余 | 本轮变化 | 当前剩余 |
|---|---|---|---|
| R1–R8 | R4 半修 | **R4 全闭**（附 X2/X5 记录） | 0 |
| 钉测债 R1/R6/R4 | 3 | **3 全闭** | 0 |
| 偏差标注债 | 4 | 2 闭（R5、ConsoleExporter） | 2（T7、root 迁就） |
| G12 | ≈13+半 | D3 闭、D1 兜底收窄 | ≈10 全开 + D1 半开 + **D2 带 X1** |
| G8 | D6、D8 | 未动 | 2 |
| G13 | ≈12+3 半 | 未动（D15 双轨仍在；D18 转显式裁剪） | ≈12+3 半 |
| T1/T2 | 原值 | 未动；**新增 X5 弱钉 1** | 原值 |

## 五、结论与下一步

**本轮质量评级 B**：四件套工艺忠实（信号/退出码/等待点/Task 调度全部 TS 同构，322 行新测试真异步冒烟），R4/G12-D3/钉测债/标注债 2/4 全部落地。NOT-READY 解除被 X1 一个单行缺陷阻断。

**下一轮点修清单（完成 ①② 即可重审解除 NOT-READY）**：
1. ① profile.py 补 `import json` + D2 文案对齐 boot/profile.py:733-736 + 触发钉测（半小时级）
2. ② hmr.py saved_fibers/reload_plugin 提升作用域 + 多文件回滚钉测 + X5 判别性断言
3. ③ X3 预设名回落收敛进 boot 层 + main 顶层错误呈现；X4 便携布局 bundle 解析臂（需 build_portable 协同）
4. ④ T7/root 迁就两笔标注 + X6 微项登记
