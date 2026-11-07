# Client 函数语境与模型说明修复

日期：2026-11-07。固定原版 `a4c74a91e06b00fe0b0937bde982170c526cc842`；reference 未修改。修复本轮复审的 Client 编译语境和旧模型说明，承接[运行时边界记录](2026-11-07-creative-win7-runtime-boundaries.md)。

后续复审确认的两类正则接受差异及其修复见[Client 正则语法门修复](2026-11-07-creative-client-regex-precheck.md)。下文保留本轮实现与回执身份，不表示这些旧回执已覆盖后续变更。

## 当前行为

[Host define](../../dsh/extensions/host_runner.py) 改用专属 [Client 编译检查](../../dsh/javascript/client_syntax.py)，在普通函数体内解析原版的 async-arrow 包装，再构造相同的 `new Function(wrapped)`。`new.target` 因而在正确的词法语境中有效。两次检查均不调用 Client 函数；私有 worker 实际执行的模型 body 固定为 `return null`。已有 workflow 全局脚本编译路径保持原义。

QuickJS 比固定 Node 22.20 更早接受资源管理声明。随包加入该 Node 发行自带、未修改的 Acorn 8.15.0，仅关闭 using 和 await using 两个声明产生式，再由 QuickJS 检查函数构造。没有使用关键词正则，普通变量、属性、字符串、模板、注释、正则字面量中的 using，以及 `await using` 表达式均保留。解析器使用自身最新语法，避免按年份笼统限制而误拒原版接受的动态 import options。

Acorn 源码、Node 发行中的 MIT 许可与来源摘要均保留在 [client-syntax](../../dsh/javascript/client-syntax/README.md)；manifest 和资源字节在加载时核验，Git 属性避免 Windows 换行转换。沿用现有 x64/x86 Win7 worker，不修改其 C 代码或二进制，不增加产品的 Node/npm/TS 工具链。Portable 构建原有 dsh 目录复制规则包含这些资源，本轮未重建 Portable。

[工具说明](../../dsh/extensions/cordis_prompt.py)的 native_contracts 最终结果及[实际随包技能](../../packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/SKILL.md)统一说明：定义时检查 Host/Client 语法且不执行源码；运行时仍可能遇到执行错误、缺失依赖和浏览器引擎差异。实际 CLI/Web 首次序列化请求及随后 skill 工具加载均验证该文字，不只检查源文件。

## 验证范围

输出：`.goose/out/creative-client-function-20261107-010800/`，命令、退出状态、输入摘要、日志/XML、原版与 Python 观察见 `verification.json`。使用 Python 3.8.10；定向覆盖真实 Runner Client-only/双半定义、新建/追加版本的原子性、22 种语法控制、原版 new Function 预检和求值包装、x64/x86 worker、无 Node PATH、共享 workflow 消费者及实际模型请求。

`new.target` 在原版求值包装返回插件函数，在 Python Runner 定义成功；using/await using/for-using 声明两侧均拒绝。无限循环和 throw body 可定义，证明编译不执行模型代码。Native 异常栈夹具只因 Host import 行号变化从实际运行重新捕获；旧回执不重标为当前输入。

初次兼容检查采用 ES2024 语法，定向 168 passed、1 xfailed；随后补查发现该年份选项会误拒有效的 dynamic-import options，已收敛为仅关闭 ERM 声明产生式，并加入相应接受控制。旧输出保留原身份，最终结果单列在 `verification.json`，不拼成完整回归或发行资格。

| 最终检查 | 结果 |
| --- | --- |
| 定向 pytest：Client 差分、工具合同、Runner、共享 JS runtime、CLI/Web 实际请求与技能加载 | **169 passed、1 xfailed**，42.91 秒；`final.log/xml`。已知同步超时 xfail 不计为通过。 |
| 新鲜 Source/Python Runner | **16 旅程、162 步**；14 matched、1 项既有 NUL 碰撞例外、1 项 Python traceback 投影；`runner-final.json` 及双侧观察。 |
| 新鲜 Source/Python 七工具 | **92 matched、0 different**；`tools-final.json` 及双侧观察，绑定更新后的模型说明。 |
| 源码／资源／文档 | Python 3.8 语法、相对链接、资源与回执摘要、Git 字节属性、diff check；`final-checks.json`。 |

## 剩余限制

未认证全部 Acorn/QuickJS/V8 语法、正则或诊断等价。本轮新增 Acorn 错误的源码行/列及 caret 上下文，坐标映射到 Client body；仍不等于原版完整教学提示。浏览器激活、跨引擎差异和多页面行为未做新一轮验收。

CORDIS-SYNC-TIMEOUT-001 仍未修复、未接受，strict xfail 不计为通过。完整 Python imports/builtins 仍为待决扩展。本轮不执行完整发行门禁或 Win7 真机验证，也不将上述状态改成已接受。
