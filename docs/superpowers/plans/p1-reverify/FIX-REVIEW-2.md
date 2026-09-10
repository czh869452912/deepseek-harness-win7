# P1-R 修复轮 2 审核报告（针对提交 228511d8）

日期：2026-09-10
审核对象：`228511d8` "fix(cordis): resolve FIX-REVIEW R1-R8 defects, CLI pipeline migration and test hardening (1032/1032 passed)"（基线 `78c95f07`，25 文件，+829/−82）
审核方式：机械验证 + 8 项探针（R1–R6 定向 + 2 项上轮回归）+ 2 个分区审查智能体（RB1 管线迁移、RB2 点修/logger/tests）+ 主会话读码裁定

# 裁决：R1–R6 点修全部属实（5 全修 + 1 半修）；管线迁移主体落地但端到端不可运行 —— 维持 NOT-READY for P2，最小必办集收窄

## 一、机械验证

| 项 | 结果 |
|---|---|
| 全量 pytest | **1032 passed**（上轮 1028，+4），0 failed |
| compileall（py3.8） | exit 0 |
| py3.8 语法 | 25 变更文件 ast 全过，无 3.9+ 语法 |

## 二、探针回归（8 项）

| 探针 | 结果 |
|---|---|
| R1 repr 插件 ctx | **FIXED-OK**（`Context <Plug>`，不再崩） |
| R2 fail-loud 投递 | **FIXED-OK**（首测假阴性系探针持有 task 引用；修正探针后 `dsh: fatal load failure` 正确投递，且过滤式 handler 仅针对未检索异常 = TS unhandledRejection 等价） |
| R3 eval_condition | **FIXED-OK**（首测 PARTIAL 系探针实参顺序错误；直读函数体确认启发式已删、与 entry.ts:104-108 同构、docstring 已诚实） |
| R4 hmr 深回滚 | 备份深度达标（runtime.callback/fiber.plugin）；回滚语义差距见 §四 |
| R5 from_json | **FIXED-OK**（fail-loud 替代毒对象；机制审查见 §三） |
| R6 代理写穿透 | **FIXED-OK**（ext 写不再泄漏到原实例） |
| G7b-D1 / G3-D3 回归 | 保持 OK，无回退 |

## 三、R1–R8 判定汇总（RB2 逐行 TS 比对）

| 项 | 判定 | 要点 |
|---|---|---|
| R1 repr | **FIXED** | `self.__dict__.get("fiber")` 直读，不经 `__getattr__`；与 TS context.ts:86-88 逐点一致。**无钉测** |
| R2 fail-loud | **FIXED** | DefaultProc 过滤式 loop handler + prev handler 还原 + exiting 闩 + release 2s wait_for；带还原钉测。残差：转发面含非 rejection 类循环异常（略宽）、handler 自身异常被未命名 except 吞 |
| R3 eval_condition | **FIXED** | 启发式整段删除，W2 尾巴闭合；测试按 TS 真值表重写 |
| R4 hmr 回滚 | **PARTIAL** | 备份面达标；但 TS 的 delete+重挂完整生命周期语义未闭合（仅还原引用 + `_refresh`），restart 已成功后出异常仍留状态不一致窗口；`f._refresh()` 包未命名空 except；回滚零测试 |
| R5 from_json | **FIXED**（机制） | callback 剥离为 `_callback_source` + getsource 序列化 + fail-loud 抛出稳定；**TS `new Function` 还原分支的缺失未登记为许可偏差** |
| R6 写穿透 | **FIXED** | props 写副本、其余写自有 dict，读链保持；**无钉测** |
| R7 | 部分启动 | ConsoleExporter 落地（G8 D1 ✅ 带偏差簇）；dump_config 接 canonical（G12 D7 主体 ✅）；入口迁移启动（见 §四） |
| R8 | 大部兑现 | gather 逐项 logger.error ✅、重复赋值行删 ✅、to_string 括号协议修复+钉测 ✅；G6 context 区 8 项、G10 D4/D7、G9 D19 未动 |

## 四、新发现（管线迁移区，RB1）

**评级 B（按"能否承载真实应用"口径接近 C）**：函数级映射约 90% 忠实，dump-config 分支可完整交付（G12 D7 全对齐），ProcessShutdown 控制器/compose 四层合成/telemetry 开关/fail-loud 本体均 1:1。**但运行时半边未接通，4 个阻断级缺口**：

| # | 问题 | 影响 |
|---|---|---|
| P-1 | **appExit 接线返回未调度协程**（profile_boot.py:229 `lambda code: shutdown.shutdown(code)`，async def 调用仅产出 coroutine，无 ensure_future） | 有界退出契约 no-op：调用 appExit(code) 得到永不运行的协程 |
| P-2 | **信号契约整体缺失**（SIGINT→130/SIGTERM→0/AbortController/signalShutdown.interrupt 零调用） | Ctrl+C 走 main 的 `except KeyboardInterrupt: pass`：不 dispose、退出码 0（TS 应 130）；suppressShutdownError 的 aborted 臂随之消失 |
| P-3 | **退出码丢失**（process_shutdown.py:26 `setattr(sys, "exitcode", code)`——全仓无读者） | appExit(3) 后进程仍以 0 退出；退出码契约全部塌缩 |
| P-4 | **asyncio.run 收束即拆树**（run_profile 在 appReady.commit 后 return，main 的 asyncio.run finally 取消全部任务并关 loop） | 长 profile（web/tui）在 boot+watcher 建立后立即被整体拆除；TS 契约"进程生命周期归挂载插件"不成立。**P-1~P-4 合并后果：新 profile 管线当前只能 boot，不能运行也不能退出** |
| P-5 | heal 调用签名错误（位置实参 vs dict 形参）→ TypeError 被 `except Exception: pass` 吞 | heal 死代码 + 真故障伪装；恰是"新三模块零测试"的直接后果 |
| P-6 | installFailLoud 仍双重装配（main.py:184 惰性 + profile_boot.py:212 真实；legacy 还有第三处） | 当前侥幸无害，双轨清理时须收敛为 run_profile 单点 |
| P-7 | plugin 模式未分发 → 静默落入 legacy REPL | `dsh.py plugin ...` 启动交互式 REPL 而非报"未支持" |
| P-8 | dump_config fail-open 兜底（profile.py:376-383 `except Exception: 回落旧发散合成器`；dsh_home 参数 canonical 路径被静默忽略） | canonical 失败静默切换到旧路径（混入 telemetry、default_only 失效、无溯源注释）——破坏 D7 修复的可预期性 |
| P-9 | G13 D15 未解：build_harness 内联激活审计仍在（harness.py:206-229），双管线并存 | legacy 空参路径仍走旧架构 |
| P-10 | 三个新模块（profile_boot/process_shutdown/dump_config）零测试 | P-5 类签名错误正是无冒烟测试的直接后果 |

RB2 新引入：未命名空 except ×2（ConsoleExporter.export、_loop_handler 内 handler_fn 循环）；ConsoleExporter 偏差簇未标注（showTime 用 message.ts、showDiff 恒 ms、无 truecolor 档、o/O=json.dumps vs util.inspect）。

## 五、覆盖度更新

| 组 | 上轮开放 | 本轮闭合 | 剩余开放 |
|---|---|---|---|
| R1–R8 | 8 | **R1/R2/R3/R5/R6 全修 + R8 大部** | R4 半修 |
| G8 | 3 | **D1**（ConsoleExporter，带标注债） | D6、D8 |
| G12 | ≈15 | **D10 全闭；D7/D12 主体闭** | ≈13（D2/D3/D4/D6/D8/D9/D11/D13/D14/D15/D18/D19 全开 + D1 半开） |
| G13 | ≈17 | **D2/D4/D8/D10 全闭；D1/D16/D17 经新链主体落地** | ≈12 全开 + 3 半开（D15/D18/D21–D31 等；legacy 双轨未清） |
| T1 | 4 WRONG-PIN+6 OVERCLAIM+7 WEAK+15 GAP | **WRONG-PIN 3 闭合**（F2/F3/F4）+ OVERCLAIM 1 + WEAK 1 | WRONG-PIN 1（F1）、OVERCLAIM 5、WEAK 6、GAP 15 |
| T2 | 31 弱化+1 WRONG-PIN+1 OVERCLAIM | 弱化 2（F4/F5） | 弱化 29、WRONG-PIN 1（F3）、OVERCLAIM 1 |

新增钉测 4 个（R2 还原、R5/R8 schema、ConsoleExporter render）；**R1/R6/R4 仍零钉测**。

## 六、下一轮最小必办集（NOT-READY 解除条件）

1. **管线可运行四件套**：P-1（appExit ensure_future）+ P-2（signal.signal + abort/interrupt 接线 + aborted 臂）+ P-3（退出码经 main 消费）+ P-4（run_profile 持有退出等待点，asyncio.run 不再即时拆树）——完成后新管线才算"能运行"
2. P-5 heal 签名修正（删吞异常）+ P-8 兜底收窄（仅未知 profile 名回落预设模板，删裸 except）+ P-7 plugin 模式显式报错
3. R4 改 registry.delete + 重挂语义；R1/R6 补钉测；P-10 三个新模块最小冒烟测试
4. G12 D2/D3（bundle fail-loud + 兜底数据删除）——NOT-READY 解除前的最后硬骨头
5. 偏差标注清账：R5 new-Function 还原缺失、ConsoleExporter 偏差簇、test_context T7 弱化、core_exact root 迁就

完成 1–3 后可评估 READY；4 完成后正式解除 NOT-READY 进入 P2。
