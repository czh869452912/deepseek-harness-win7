# Office 原版请求准入（C9-BR）

固定 Source `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`、SDK 0.2.3。构建脚本逐字保留原版 resolveOptions、resolveConversion、resolveImageRender、A1 几何及默认值代码，在已分发的 Win7 QuickJS x64/x86 引擎执行。Python 只提供当前平台预解析的绝对路径、扩展名、相对关系、系统字体根和缓存目录；工作进程没有通用文件读取或动态代码接口。

758 组实际 Source 对照在 x64/x86 均一致，覆盖 Writer/Calc/Impress 格式组合、重算约束、路径、sheet、图片 pages/范围/DPI/限额、所有 SDK 数值选项、字体列表、回退组、未知选项和 JS undefined/NaN/Infinity。错误类别、消息与成功结构均比较。另将默认系统根规范化，并增加含点路径的 Source 观察，现为 9 组根目录对照。

50 项定向检查通过，范围包含准入层直接消费者及实体字体、文件事务、浏览器载体。5 个合同资源（含 manifest）重建后逐字节一致；许可证和 NOTICE 随资源保留。首轮未注册默认缓存目录的路径查询表导致部分原版对照失败，已修复并保留失败报告，最终结果单独记录。

本段只建立闭合的请求/选项载体；不会将任意 Python 回调伪装为 JS resolveEnginePackage。默认引擎生命周期、输出页树、缓存编排、二进制打包和实际 Win7 VM 资格继续实施。已清理两个构建目录及定向测试工作区，保留紧凑日志、XML 和真实对照结果，详细空间统计见回执。

回执：[office-contracts-checks.json](../../migration/candidates/rc022/office-contracts-checks.json)。
