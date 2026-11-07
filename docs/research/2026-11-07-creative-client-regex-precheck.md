# Client 正则语法门修复

日期：2026-11-07。比较基线保持固定原版 `a4c74a91e06b00fe0b0937bde982170c526cc842` 和 Node **22.20.0**；reference 未修改。承接[函数语境修复](2026-11-07-creative-client-function-precheck.md)，关闭复审提出的两类具体接受差异，不将完整语法等价标为已认证。

后续的同步超时修复和整体闭环复核见[进程边界修复记录](2026-11-07-creative-host-process-and-parity-audit.md)。下文 xfail 属于本轮历史输入，不能作为后续实现的通过或失败结果。

## 修复

原版 `new Function` 门拒绝正则局部修饰符 `/(?i:a)/` 和不同分支的重复捕获组名 `/(?<word>a)|(?<word>b)/`，此前 Acorn latest 与 QuickJS 均接受。新增回归在修复前通过真实 Runner 的 Client-only 和 Host/Client 联合定义路径复现了错误注册。

[Client driver](../../dsh/javascript/client-syntax/driver.js) 现在通过固定版本 Acorn 的两个解析钩子拒绝这两类产生式：修饰符由解析器识别，捕获组名使用解析器完成转义归一化后的名称及分支状态检查。没有扫描源码关键词，也没有降低整个 ECMAScript 语法年份。Acorn 原始资源与许可字节保持不变；更新 driver 资源摘要和加载器的 manifest 摘要。

定义阶段仍只编译、不执行 Client。字符串、模板、注释、转义括号、字符类和 `RegExp(...)` 的字符串参数不会被误当成正则字面量语法；后者的运行时错误仍由运行阶段处理。有效的 distinct named groups、反向引用、lookaround、`v`/`d` 标志、动态 import options、`new.target` 及普通 using 标识符保留。非法定义不消耗 ID，也不修改已有 Package。

## 本轮验证

输出目录：`.goose/out/creative-client-regex-20261107-014500/`。`verification-current.json` 保存命令、退出状态、XML/日志和当前输入摘要，`client-source-observations-current.json` 保存实际 Node 接受结果。测试记录实际 Node 版本并校验接受边界；本轮使用固定 Node 22.20.0，CI 的补丁版本差异不单独作为失败条件。

| 范围 | 新鲜结果 |
| --- | --- |
| 修复前缺陷回归 | Client-only、双半路径各失败 1 例；`before.log/xml` 保留原失败。 |
| 定向 pytest | **138 passed、1 xfailed**，26.49 秒；`verified.log/xml`。 |
| Client 差分 | **46 种函数体**，28 接受、18 拒绝；包含新增 24 项正则及防误拒对照。固定 Node 22.20.0 与实际 Runner 定义、新建/追加版本原子性比较；x64/x86 随包 worker 同时检查正则用例。 |
| Source/Python Runner | **16 旅程、162 步**；14 matched、1 项既有 NUL 碰撞例外、1 项 Python traceback 投影；`runner-verified.json`。 |
| Source/Python 工具 | **92 matched、0 different**；`tools-verified.json`。 |
| 静态检查 | Python 3.8、资源及回执摘要、reference pin/干净状态、文档链接和 diff 检查；`verified-checks.json`。 |

定向范围选择 Client 语法提供端、真实 Runner 定义及版本生命周期、直接工具消费路径；共享 workflow 编译器及浏览器源码未修改。没有重跑完整 Python 集合、浏览器验收、Portable 构建、发行门禁或 Win7 真机验证；上一轮回执保持原输入身份。

## 未关闭事项

本轮仅关闭已确认的两类正则接受差异，尚未认证 Acorn/QuickJS/V8 全部语法及诊断等价。同步原生阻塞超时 `CORDIS-SYNC-TIMEOUT-001` 仍未修复、未接受；strict xfail 不计为通过。完整 Python imports/builtins 仍是待决能力扩展，未转为必要移植差异。
