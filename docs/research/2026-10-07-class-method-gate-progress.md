# 完整门禁的 pytest 类方法身份

新必需消费者是设置测试的 TestRegistration 类方法，实际 XML 的 classname 为 `tests.1to1.settings.settings.test_settings.TestRegistration`（批量目录运行还可能省略前两个前缀）。旧门禁只取最后一段，因此无法满足按文件模块登记的必需项。使用已完成的 291 项真实 XML 独立复现确定性拒绝；合成 XML 的旧控制没有覆盖此载体格式。

公共门禁现在按已声明模块或模块/类后缀匹配完整测试名。该消费者显式登记为 `test_settings.TestRegistration`，不把所有同名类合并；零匹配、歧义、重复、跳过或失败继续拒绝。每个 XML case 只枚举其有限命名空间后缀并进行集合查找，不遍历全部必需项。真实子 pytest 生成类方法 XML，正例签收后分别变更省略、跳过、重复、失败、模块和类，六种情况均拒绝；另覆盖身份歧义。121 项相关门禁/Unicode/进程必需控制通过，291 项既有真实 XML 的四处目标消费者完整识别。

协调器在确认此确定性门禁拒绝后停止干净 2003821e 的专属进程树。该运行无完整 pytest XML 或正常门禁结果，不计作通过；冻结输入、原始日志、精确 ZIP、旧门禁提供端与真实 XML 保存在 `migration/evidence/artifacts/CLASS-METHOD-GATE-INTERRUPTED-20261007-2003821E.zip`，SHA256 `2481c6fed3c297afef00a2c59138f4666f0855bd295d8d7b115673ac6c168681`。候选 ZIP SHA256 `9ddb9a77a8157bf9043a768f1c6ae10a25557b8351d5f3c21e337956e4a52adb`。未结束工作区保留。

10 文件修复资格归档 `migration/evidence/artifacts/CLASS-METHOD-GATE-QUALIFICATION-20261007-2003821E.zip`，SHA256 `330a70a29b1abb7f014af5e5dc2d43f344785305525b50be9f2ef4354c5ad69f`，包括初次控制因错误命名空间预期产生的六失败原始结果。未修改业务提供端、原版前端、预算或既有 Source 缺陷接受谓词。继续新干净提交的完整门禁；最新完整签收仍为 83026446/65，父范围及延期认证不自动关闭。
