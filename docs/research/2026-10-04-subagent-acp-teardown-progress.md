# subprocess ACP 关闭失败第六部分

本部分先在隔离树推进，现移入主树独立实施；第五部分产品 defabc05 已提交，但完整预览和 clean gate 均在原版浏览器启动时取消而失败。两个任务仍未验收，不将隔离证明或定向通过写成 integrated。原版固定 cd5ef8148158c3a752a658978873241fdf8e2bbc，前端与九类原版 bug 例外未变。

## 独立复现与根因

使用实际原版 startAcpRun 和 spawnSubprocess 启动独立 Python ACP peer，在共享 SubprocessHandle 边界注入已声明的“实际子进程退出后 waitForExit 拒绝”。原版四组观察为 published-post-exit、startup-post-exit、cancelled-startup-post-exit、throwing-error-sink；原始 wire、实际 pid/cwd、Host cause 字符串及退出码完整保留。

首轮 Native 三组不匹配：发布后的重复 dispose 每次重新包装异常并重复报告 Host 错误（三次而非原版一次），虽然底层 process teardown 已缓存；未发布普通/取消回滚在实际子进程已退出后仍使用清理之前的 outcome，错误报告 unknown，丢失原版 process-exit/exit code 1。第四组 throwing-error-sink 已匹配，不能宣称全都缺失。

修复把发布后的完整 dispose 事务缓存为单一 owned Task，等待方使用 shield，重复等待返回同一失败实例且只报告一次；普通和取消 startup rollback 的 cleanup failure 从当前已经完成的 child.done 获取实际结构化事实。原始 Host cause 保留，模型可见诊断仍仅安全 provider/stage/category/exit 信息，没有复制 private path/SECRET_TOKEN。startup 两个 AggregateError member 或取消的单 member 与原版严格匹配。

## 当前证明

修复后四组新鲜原版/Native 完整观察匹配，实际子进程已退出，两个 wait seam 调用和一次 terminate，以及真实 AbortSignal listener 清理均检查；raw cause 字符串不做模糊映射或丢弃。正式 subagent_acp_teardown_oracle 驱动通过，有界 literal specification 和 27 项反例证明拒绝丢失 member/cause/退出码、重复日志/终止、不同错误实例、弱类型、遗漏 wire/物理 spawn 或外国模块来源。只抽象 RPC id/pid 命名空间，原始记录保留。

另两项 Python cancellation 实际进程测试通过：取消 dispose 等待方不能取消 owned EOF flush/退出/RPC 排空；取消 startup 等待方仍回收尚未发布且阻塞 new-session 的真实进程。它们证明 Python Task 取消适配，不假称 JS Promise 有原生 cancel API。提供端与源观察 14 项、关闭/反例 30 项、未来 release/关闭门禁 201 项通过。

未来门禁已在隔离树接入 84 必需 lane、33 个 paired driver，八组 788 项原版断言保持。实际解压 Portable 将使用其自身 Python -I 运行四组 teardown peer，检查模块/root/3.8.10 及原始 cause/wire/退出事实；目前尚未实测该包，不能 integrated。本部分没有认证即时无限无响应/异常 stream、完整嵌套进程树、所有 SDK、background Jobs、整体迁移或用户延期的 Win7。

首轮 teardown-source-v1/native-v1 原始差分及后续 paired/regression/formal 日志保留于协调树 .goose/out/acp-a4-work。根据两次全量浏览器失败，调整执行顺序：已提交的第五提供端继续追踪网络根因，先独立提交已证实的关闭修复，再由共同干净候选全套门禁及实际解压同时签收第五和第六有界合同；未通过则都保持开放。隔离树第七、八部分 MCP/subprocess 改动没有混入本部分。

主树新鲜提供端/取消/观察器/门禁及第五消费者回归 220 passed、31.93 秒；正式主树 driver 四项通过，migration check 和 diff check 通过。任务 MIG-SUBAGENT-ACP-TEARDOWN-011 running、CON-SUBAGENT-ACP-TEARDOWN@1 specified。下一步独立产品提交，继续其他已验证的关闭修复，并由最终共同冻结候选执行全套和实际解压；本记录不签发 acceptance。
# 实际解压编码失败与修复

干净共同产品 34c581a5 的 Python 全量 5722 passed、6 skipped、1 warning，八组 788 项原版断言、35 配对及 Cordis 判据通过；最终实际解压 ACP teardown 因中文 cwd wire 失真拒绝发布，publishable=false，四个 running 任务均未签收。

严格解压环境不继承 PYTHONIOENCODING。观察peer原先按系统 cp936 读取生产 UTF-8 JSON，中文 cwd 被误解码；未改生产代码、原版前端或放宽任何判据。peer显式设置 stdin/stdout UTF-8，新测试用 -I、无 PYTHON 环境、中文 cwd 验证。隔离修复后，同一实际解压旧产品的四组 ACP teardown、七组 MCP disposal、四组 subprocess ownership 原判据通过，诊断保留于 `.goose/out/acp-a4-work`，不代替新产品干净验收。

失败完整共同回执在 `.goose/out/owned-teardown-clean-34c581a5`，与先前两次浏览器失败共同保留。当前通过的浏览器旅程不证明此前启动取消根因已修复；既有 Proactor warning 和 HTTP 10054 仍未归因。
