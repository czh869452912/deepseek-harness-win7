# 创造模式：同步超时修复与一比一闭环复核

后续能力边界、Client 诊断、服务桥及导出宿主收尾见[后续记录](2026-11-07-creative-closeout.md)。本文保留前次候选与回执的历史身份。

日期：2026-11-07。比较基线为固定原版 `a4c74a91e06b00fe0b0937bde982170c526cc842`，reference 保持干净；迁移目标为 Python 3.8.10、Win7。本文检查本轮工作区源码，不认证先前发布的安装器或 Portable。

**结论：临时 Host 的同步原生阻塞超时已实现修复；本轮主要创造工作流有实际运行证据，但全部设计调整尚未闭环，不能声明创造模式整体一比一等价。** 主要未闭环项是默认 Host 的协作式能力边界、Client 完整编译/诊断等价、进程代理的完整服务 ABI，以及新候选的 Win7/发行资格。

## 超时修复的范围

旧实现在主事件循环中 `exec`，通过 `sys.settrace` 检查期限。原生休眠或计算没有跟踪事件，期限到达后仍继续运行，且阻塞父进程；线程加 `wait_for` 也不能取消底层调用。新实现由每个临时 Run 独立拥有的 Python 进程承载源码、函数闭包及后续任务，真实 Cordis Fiber、工具及服务注册保留在主进程。子进程初始求值超时后关闭 Win7 Job/终止进程，不能继续执行晚到副作用。

相关实现：[进程所有权](../../dsh/extensions/cordis_host_process.py)、[worker](../../dsh/extensions/cordis_host_worker.py)、[对象与回调桥](../../dsh/extensions/cordis_host_bridge.py)、[Runner](../../dsh/extensions/host_runner.py)、[卸载](../../dsh/extensions/cordis_runner_state.py)。产品不增加 Node/TS、cloudpickle 或现代 Python 依赖；Windows 进程无可见窗口，Job 使用 Win7 已有 API。保留一个已就绪的备用 worker；创建备用进程放到后台，初始化及 IPC 等待不混入模型同步执行计时。

初始 `harness.handle/defineTool` 在 worker 本地处理，避免在同步期限内把模型的大型 DSL 校验搬回主事件循环；成功求值后才绑定父进程 harness。工具跨边界时在真实父上下文重建受标记的 Tool，普通未标记对象仍被 Guard 拒绝。函数、异步结果、生成器 effect、共享 dict/list、RPC 和 disposer 在 Run 完整寿命内继续有效；停止和更新先执行真实 Fiber 清理，再关闭进程。进程意外退出会撤销服务与工具并向所属模型报告。

`vmTimeoutMs` 仅约束初始源码同步求值，不新增 async apply 或后续 RPC 的运行期限。固定原版的实际 `createSandbox/evaluateHostCode` 另有新鲜探针：30ms 配置中断 600ms 原生阻塞，晚到调用没有发生，80ms 异步续体仍成功。新实现也检查原生休眠、原生计算、Python 死循环、初始大型 DSL、无晚到文件副作用、父循环继续运行、其他活跃插件不受影响、备用进程启动失败及恢复重试。

这关闭 `CORDIS-SYNC-TIMEOUT-001` 的临时 Host 实现缺口。系统调度、启动及通信有开销，不承诺 run 调用总耗时精确等于配置毫秒数；完整 Win7/Job 嵌套环境仍需实际资格验证。原来的 strict xfail 已移除，相关用例现在必须实际通过。

## 按原版能力复核

| 原版能完成的事／本轮调整 | 当前迁移实现及证据 | 闭环判断 |
| --- | --- | --- |
| 创造模式加载开发技能、按需 Inspect、编写 Host/Client | 默认同名技能、七工具；Host 改为 Python，Client 保留 plain JS 与原样前端；实际 CLI/Web 模型请求、skill 加载及示例回归 | 主工作流已覆盖；开发指引不再要求 TS 工具链。AGENTS 中残留四个旧工具名已纠正。 |
| 定义临时 Plugin、追加精确 Package，读取基版本 | 实际工具及 Runner 旅程；两半语法预检在 mint/登记前完成，失败不消耗 ID、不改旧 Package | 已覆盖正常与拒绝主路径。 |
| 审批、授权未来版本、同一请求多页面附着 | 原版布尔条件修复；完整共享审批旅程、原样前端重复附着 | 已覆盖本轮已知分支。 |
| 运行、更新、停止、撤销旧 RPC、移除 | 子进程保留闭包；真实父 Fiber 拥有注册，依赖等待/重新激活及取消仍沿用原状态机 | 定向与原版配对通过；不能推广为任意 Python 对象的透明 ABI。 |
| 注册工具、JSON RPC、事件、服务、timer、async cleanup | 实际示例和 canonical Web composition；生成器/异步生成器、双向共享状态、异步 apply/RPC、意外进程退出额外回归 | 已覆盖列出的行为；通用服务返回值与复杂对象仍需完整资格。 |
| Client 插槽、主题、页面重载、多页面 Inspect、取消 | 前端源码未改；现代 Edge、固定 Chromium 108 的 33 步真实旅程，各有 35/35 Inspect 结算 | 本机浏览器范围通过；不是 Win7 真机或全部浏览器差异认证。 |
| 源码错误定位并引导自主修复 | Python 普通异常保留真实 traceback 与业务异常链，参数适配不再污染上下文；Client 有 body 行/列及 caret | Python 已知回归通过；Client 教学提示尚未逐项对应原版。 |
| 初始同步求值期限 | 独立进程强制终止，后续 async apply/RPC 保留原范围 | 实现缺口修复，发行与真机验收待完成。 |
| 能力通过 Context、依赖和 effect 取得并清理 | Context Guard 与注册仍受控，但 Python 仍开放完整 builtins/imports | **未闭环：CORDIS-HOST-CAPABILITY-001。** 独立进程不等于能力边界已收窄，任意 open/import/线程仍可绕过 Context。 |
| Client 定义阶段的精确语法接受集合 | 已修复 new.target、using、正则修饰符与重复组名；46 种 paired gate 回归 | **部分闭环。** 未证明全部 Acorn/QuickJS/V8 语法、Unicode/正则版本与错误提示等价。 |
| 保持原版默认功能边界 | 默认七工具不含 export；可选源码发行分开 | 共享 Inspect 租约是本机附加修复；导出/打包是额外能力，不能写成原版的一一对应。 |
| 用户自定义技能路径 | 通用 provider 按 cwd 解析相对路径；Creative 默认资源单独锚定安装位置 | 功能回归已修复；启动层了解插件资源路径仍是设计债。 |

## 剩余缺口与顺序

1. **收窄默认 Host 能力边界。** 保留 Python 语言计算能力及明确的纯计算模块，对文件、网络、进程和定时器等默认入口给出 Context 服务替代提示；检验 imports、open、线程和动态代码入口不能成为普通插件旁路。同步更新 Builtin 自省、技能、示例与拒绝旅程。此处目标是原版协作式能力边界，不是抵御恶意 Python 代码的安全承诺。当前完整 imports/builtins 没有被用户单独接受。
2. **完成 Client 编译/诊断合同。** 继续绑定固定比较环境，扩展功能特性和原版错误提示的差分集合；具体不等价必须修复或单列决策。有限样本通过不能证明所有 JavaScript 源码的接受集合完全相同。
3. **资格化进程服务桥。** 当前没有证明所有 Service/Event、可变与只读对象、复杂返回类型、迭代/异步迭代、重入与取消、长期资源增长都透明等价。需按实际 Python provider 和消费者建立覆盖清单，而非将通用代理的存在视为全部 ABI 已通过。
4. **冻结候选后统一验收。** 本次跨模块运行时变更尚未执行完整发行门禁、x86 Python Host/实际解压 Portable、Win7 SP1 真机和不同 Job/桌面启动环境的资格检查。当前两种浏览器运行在现代 Windows；不可重标旧发行包。已知修复与目标回归稳定、前述合同决策完成后，再安排 `verify_release.py` 完整门禁。

可选导出后的持久 Python 插件仍由 [packaged_host.py](../../dsh/extensions/packaged_host.py) 的独立宿主求值，那里仍使用同进程 trace 的 5 秒检查。本轮临时 Run 修复不覆盖该额外发行能力；默认创造工作流不要求导出。若继续交付此扩展，须单独迁移并验收其生命周期、冷启动及升级回滚，不能沿用本次超时结论。

## 本轮验证身份

输出目录：`.goose/out/creative-host-process-20261107-023000/`。当前命令、输入摘要、日志/XML、源码位置、双侧观察与限制见 `verification-current.json`。修复过程的失败输出保留，包含初次 worker 缺少 venv 模块路径、旧栈夹具、Windows 启动开销误入期限和新增测试的夹具/异步结算问题，不改写为通过。

最终定向集合、Source/Python 配对、两种浏览器和固定原版超时探针各自保留精确输入身份；收尾进程启动失败恢复修复后的检查单独记录，不能把旧输入结果拼成新发行资格。Python traceback 夹具从真实 worker 观察捕获，严格保留 `<cordis-host>` 行号及全部框架帧，不过滤未知栈。

| 当前候选检查 | 结果 |
| --- | --- |
| 定向 pytest：进程、Client 语法、Runner、Guard、真实 Python 诊断、工具及 authoring composition | **301 passed、1 skipped**，263.02 秒；`qualified-targeted.log/xml`。跳过项为可选发行浏览器示例，超时回归不是 xfail。 |
| 临时 Host 超时实测 | 5ms 配置、80ms 休眠，run 调用约 31ms 结束；30ms 配置的休眠/原生计算/循环/DSL 约 47–63ms 结束，子进程均已退出且无晚到标记文件。数值为本机观察，不是调度承诺。 |
| 固定原版实际 evaluator 探针 | **1 passed**；30ms 配置约 44ms 返回超时，无晚到调用，80ms 异步续体成功；`source-timeout.json/log`。 |
| Source/Python 配对 | Runner **16 旅程/162 步**，Guard **119**，工具 **92**；`runner-current`、`guard-current`、`tools-current`。原 Runner NUL 例外、Python 栈投影及两个 Guard 例外仍单列。 |
| 现代 Edge、固定 Chromium 108 | 各 **33 步通过**，Inspect 各 **35/35** 结算；`browser-current.json`、`browser108-current.json`。原样前端、真实审批/更新/RPC/重载/停止/Inspect，无产品浏览器源码修改。 |
| 输入与静态检查 | 资源哈希、Python 3.8 AST、配对及浏览器输入哈希、文档链接、reference pin/干净状态、diff check；`final-checks.json`。 |

未执行完整回归、Portable 重建、安装器或 Win7 真机验收。本文的结论是“已修复指定超时缺口，已列出对齐阻碍”，不是“原版能做的任意创造任务已经能在 Win7 版一比一完成”。
