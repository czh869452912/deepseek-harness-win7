# subprocess 后续原版基线发现

固定原版 cd5ef8148158c3a752a658978873241fdf8e2bbc。第五部分主树干净门禁期间，仅在隔离树直接运行五份未经改写的原版 subprocess-local/subprocess spec：spawn、local、process-inspector、windows-inspector、service。

结果 103 passed、2 failed、15 skipped（平台条件），120 个展开项。两个失败都是 spawn.spec.ts 的 injected Windows tree semantics：host-exit termination 和 terminate-by-root-pid。失败发生在其自身 shellArgv('exec sleep 60') 转换函数抛出 "no win32 node translation"，尚未调用生产 spawnSubprocess，不能说原版产品树关闭错误，也不能证明 Native 对应行为已经匹配。

未改写该原版测试、忽略失败或增加 bug 例外。原始日志在协调树 `.goose/out/acp-a4-work/subprocess-original-v1.log`；隔离树 `vitest.subprocess.config.mts` 只是开发发现入口，尚未纳入正式发布门禁或 source count。本组的 103 项通过不能作为整组通过认证。

后续需要实际原版/Native 同一受控 root/descendant peer，记录真实 pid、待定/已结束所有权、取消/terminate/Host scope shutdown 和清理。显式限定当前 Windows 的源边界：原版 Windows treeAlive 只观察 direct child，不能据此承诺已退出 root 的未知后代可被回收；POSIX group 与异常/强制 Host 退出另立证据。完整嵌套树、terminal/WinPTY 和用户延期的 Win7 仍未验收。
