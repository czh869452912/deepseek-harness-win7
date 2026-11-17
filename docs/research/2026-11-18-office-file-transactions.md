# Office 文件事务提供层（C9-BP）

固定 Source：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`，SDK `@deepseek-ai/libreoffice-kit@0.2.3`。

新增 `dsh/office/file_transaction.py`，供下一段默认转换器编排使用。输出文件先以 wx/0600 创建，再读取输入；既有输出或目录失败时不会被清理。失败转换只删除本次成功打开的输出；成功输出完成写入后关闭句柄。图片批次只拥有新建的目录，失败时清理本次部分产物。

输入采用限额完整读取，检查普通文件、非空输入、大小以及读前/读后 size、mtime、ctime。Windows 使用既有 Win7 兼容句柄 API 获取真实 ChangeTime。磁盘线程在调用者取消后排空，防止工作区删除与后台写入竞争；重复取消也不能中断排空。

定向范围覆盖文件事务提供方，以及直接使用的实体字体身份与浏览器载体回归。最终 42 项检查通过（pytest 7.38 秒）。12 组原版对照使用固定 Source 的实际公开 createConverter/convert，并直接执行原版 readBounded 函数体：空输入、限额、缺失输入、既有输出、输出目录、缺失父目录、失败优先级、原始取消原因和精确边界结果一致。x86 Python 3.8.10 实际完成限额读、独占导出和失败图片目录清理。

两个已消费的测试工作区、tmp 和 home 已删除，共计 3,668 字节；保留命令、日志、XML 和实际 Source JSON。x86 临时目录在 finally 清理。默认引擎接入、真实格式矩阵、打包和 Win7 VM 资格仍在后续范围，本段不提升生产 pin 或 accepted_upstream。

回执：[office-file-transaction-checks.json](../../migration/candidates/rc022/office-file-transaction-checks.json)。
