# subprocess 服务关闭所有权第八部分

固定原版 cd5ef8148158c3a752a658978873241fdf8e2bbc。本部分先在第五 clean gate 期间隔离推进，现移入主树，在第六 3ba3f93d 和第七 fda99add 产品检查点之后独立实施。前面任务和本部分均等待共同完整验收，不宣称 integrated。

## 原始反例

四组实际原版 LocalSubprocessRuntime 配对 Native 同一受控 handle seam：host-exit-contained、pending-host-exit、mixed-failure、single-failure。提供端、Context/plugin 和关闭函数是真实代码；seam 的 wait/terminal failure 是显式 observer 输入，没有捏造实际 pid/子进程/系统退出事实。

首轮有效 Native v3 对三组不匹配。同步 Host-exit helper 在尚未完成正常关闭时提前清空 live/terminals，使 pending 所有权无法继续作为最终退出 fallback 权威；普通 wait 和 terminal terminate 同时拒绝时，Native 绕过 terminal 自身 Host-exit 接口直接信号 pid，丢失该接口；多错误输出普通 RuntimeError 和改写消息，源端为真实 AggregateError，member 身份和顺序应保留。single-failure 已严格匹配，不重写其错误。

另有 mixed-failure 的 admission 顺序差异：JS 调用 terminal.terminate 的同步前段发生在 resolved done 的 then(wait) 之前；Python 把两个 coroutine 直接加入 gather 时 ordinary wait 先进入。修复先接纳 terminal owned Task，再由已有 gather 等待全部关闭，保持实际 source trace 的顺序，不使用固定睡眠或删除 trace 来放宽比较。

## 修复与范围

同步 finalizer 保留权威集合，正常关闭事务结束才清空；失败 fallback 统一调用同一个 finalizer，使普通和 terminal 接口都执行，并逐项包含失败继续其他目标。多错误使用已有 dsh.cordis.errors.AggregateError，原始错误实例和顺序保留；单错误仍直接抛原实例。修复后的 Native v4 四组完整 trace、retained/after registry、error name/message/members/identity 与有效 source v2 相同。

观察器 v1 的 Source 根 Context.dispose 调用错误和 Native class-local 名字解析错误、v2 的 Native 根关闭 API 误用及其 coroutine warnings 完整保留。这些是观察器错误，不登记为原版或产品缺陷；修正为实际 plugin fiber 的 awaited scope disposal。source v2/native v3/v4 原始 JSON、日志和新鲜 source regression 保存在协调树 acp-a4-work。

定向服务/subagent teardown 回归 21 passed，新鲜原版配对和十九项观察器反例 20 passed，正式冻结 `subprocess_ownership_oracle.py` 四项通过，隔离树 subprocess 相关完整回归 89 passed、5619 deselected。模块/root/Python 3.8.10 来源和完整 raw ownership/error fields 都属于严格判据，不允许根目录或弱类型替代。

主树门禁接入 86 必需 lane、35 paired driver 及实际解压四场景服务消费者，要求 pending ownership、fallback、aggregate 和实际来源完整保留。本部分不认证实际 root/descendant 的全树退出、Host 强制崩溃、终端 backend/WinPTY 或延期 Win7。原版完整 spawn spec 的两项 Windows fixture 转换失败仍另见 subprocess-source-discovery，不改写或隐藏失败。实际解压和主树 clean acceptance 尚未执行；有界 seam 不能代替完整进程树消费者。

主树提供端/反例/现有 subprocess/subagent teardown/门禁 231 passed、15.77 秒，调整测试布局后独立门禁复验 191 passed；正式主树 driver 四项通过，migration check 与 diff check 通过。产品独立提交后冻结共同候选，执行全量回归、八组原版断言、35 配对和实际解压；四个新任务仍 running，不用本段定向数字签发全量验收。
