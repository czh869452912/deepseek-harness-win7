# subprocess 实际进程树与 Python 退出钩子

固定原版 cd5ef8148158c3a752a658978873241fdf8e2bbc。前一部分的 controlled handle 关闭顺序不认证物理退出。本部分用同一个 Python root/descendant peer 驱动实际原版 LocalSubprocessRuntime 与 Native；原版代码通过固定 TypeScript transpiler/标准 decorator 和 manifest alias 开发加载器执行，没有替换 subprocess 或系统退出函数。

四个范围为显式 terminate、运行中 AbortSignal、Cordis fiber disposal、Host sys.exit/process.exit。先等待 peer 发布真实 root/descendant/cwd，再获取 Windows PROCESS_QUERY_LIMITED_INFORMATION/SYNCHRONIZE/TERMINATE handles；同一 handle 持续确认进程身份和退出，失败清理也只作用于这两个已打开的 handle。对照前两进程都活着、最后两进程都退出，Host exitCode 为 direct=23、其他=0，stdout/stderr 为空。物理 pid 和临时 cwd 原样存档，只在双侧比较时抽象命名空间；不得仅检查根进程或宽泛 taskkill 清理后再宣布观察通过。

发现并复现 Native Python 3.8.10 的真实退出死锁：LocalSubprocessRuntime 先登记 atexit，第一次 run_in_executor 后才延迟载入 concurrent.futures.thread，后注册的 thread._python_exit 先执行并 join 正在等待 child 的 worker。Runtime finalizer 未能运行，Host 和两层 child 在五秒观察边界内仍存活。观察器最终只关闭所持 handle 以避免残留，然后 Host 才退出。独立 direct 和顶层未捕获异常两次失败及原始结果保留，属于 Native 迁移问题，不是原版 bug 绕过。

修复在 local 模块显式载入 concurrent.futures.thread，使其 join hook 在 runtime hook 前注册，按 Python 3.8 atexit 逆序先关闭受管树再等待 worker。不修改 Python 标准库、不替换全局退出钩子、不引入新 OS API。定向 direct/uncaught 与后续四组真实 source/native 旅程通过。原版测试 process-exit.spec.ts 的直接运行另因开发 execa 未解析而未执行，不能引用成五项源断言通过。开发 source observer 的未捕获异常诊断在当前 Node/加载器下 tree 已退出但 Host 十五秒未结算，原因还需归因；该路径不在本四组合同，也不登记为上游产品缺陷。

初次 formal observer 出现过 maximum recursion depth 后一次完善诊断的完整运行通过；这保留为未归因观察失败，不能宣称所有诊断已修复。需全量回归及干净候选门禁、独立实际解压同四组后才有界签收。未知 orphan、root 已退出之后的未记录后代、终端 WinPTY、强制 os._exit/SIGKILL Host、POSIX group、Jobs 和用户延期的 Win7 都未认证。

同时实际解压前一产品 34c581a5 暴露 ACP teardown 观察peer的编码错误：严格环境不继承 PYTHONIOENCODING，peer sys.stdin 使用 cp936 读取 UTF-8 JSON，使中文 cwd 变成乱码。原始失败不可忽略。peer 显式设定 stdin/stdout UTF-8；新测试用 -I、无 PYTHON 环境、中文 cwd 验证。修正后的独立实际解压 ACP teardown 四组、MCP disposal 七组、subprocess controlled ownership 四组都通过。此修复是观察器协议边界，不是重写生产错误或放宽比较。主树仍需提交后重新完整干净门禁。
主树接入后定向 267 项通过，固定四组 physical driver 通过，当前 mandatory regression 扩为 92 lane、paired driver 扩为 36。产品保持逐部分提交；完整干净候选和新解压包尚未通过前，不 integrated 或填写 accepted_upstream。
