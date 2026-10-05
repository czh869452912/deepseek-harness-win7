# 观察器解释器身份

干净候选7060e67b的完整门禁在实际Ready回执的executable拒绝用例出现失败。独立把Ready和runtime-context的同一用例放到仓库内basetemp，得到明确2 failed：校验仅要求解释器路径位于root以内，仓库内其他路径也被错误准入。前次定向夹具在仓库外，因此只检验了跨root路径，未覆盖这个分支。确认后停止该门禁自有pytest及其子进程，保留候选与原始观察；没有最终完整XML或可靠全量通过计数，原版/配对/解压门禁阶段未被准入，不接受或重试不变候选。

精确拒绝包 `migration/evidence/artifacts/RUNTIME-READY-REJECTED-20261005-7060e67b.zip`，SHA256 `aed98aa86cf44a89b5f49d39d84a665f3d3e5f064be7c45a7f53ac06f74f4275`；Portable SHA256 `77c2e70bcf1f7e8b974b99518b12766cccbbf1b5d83929546241bcaaeb3b41f5`，输入SHA256 `6a3346b32459ce527314bf816f8e7a89f32ccd0019819b36970cacd6d24314bf`。独立诊断日志/XML及两组实际Source/native回执也在归档中。

现在主树观察只准入实际选择的sys.executable，解压只准入解压root自己的python.exe；同一root内其他位置，即使文件字节与所选解释器完全相同，也拒绝。共用校验覆盖runtime-context、Ready和既有workflow观察；各原始观察、模块/私有资源闭包和判据保持原样。新增六项必需lane，在仓库内basetemp执行全部三个观察器及身份拒绝测试，54 passed（17.89秒），日志/XML为 `.goose/out/acp-a4-work/runtime-interpreter-fixed-v1.*`。当前728必需lane、58配对；037、038、JS036均仍未新增签收，必须新不同干净候选完整通过。

按用户对新v4清单的授权，逐项重新验证路径、长度、SHA256和假ZIP标记后仅删除264个合成JSON，2806505956字节；清单SHA256 `144096a58f048c4921127dfe33a0e3d4ec2e3814f69e95110173d40859ef5b15`，结果 `unit-receipt-cleanup-v4-result.json` 的remaining=0。所有真实验收、两次精确拒绝ZIP、输入、Source/浏览器观察及日志保留，没有扩展先前两份清单授权。

复查3be2afde旧日志451行也有上下文消费者F进度标记。此前记录漏报这个标记，现更正：旧门禁同时出现运行中失败和1800秒超时，缺少最终失败详情不等于没有失败。旧ZIP原始字节保持不变，补充历史证据记录，不推定旧完整批次的失败计数或擅自把新两项诊断当作旧最终摘要。
