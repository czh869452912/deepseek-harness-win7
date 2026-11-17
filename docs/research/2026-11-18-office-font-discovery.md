# Office 默认字体发现（C9-BQ）

固定 Source `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`，SDK 0.2.3。

Python 提供系统/用户字体根目录、实体文件身份和 Office 补充目录的只读 Dirent 清单。浏览器平台适配器允许原版 `officeFontFiles`、`scanFontSnapshot` 函数体直接执行：Office 安装目录只读首个存在的候选；补充文件名和字体家族白名单、云字体英文数字倒序、basename 去重、PreviewFont 排除、剩余容量和主目录别名优先均留在原版代码中。显式 fontDirectories（包括空数组）关闭补充发现。目录清单不授予通用文件系统读取权限。

定向检查选取本提供方、实体字体、文件事务与浏览器载体，45 项通过。系统根目录 7 组与实际 Source 函数体一致；9 个实体字体副本组成的安装/云缓存夹具，5 组扫描的全部 records/faces（含 dev、ino、size、mtime、ctime）与原版 Node Worker 一致。x86 Python 对相同五组另行通过。重跑既有 16 组真实 SDK 转换/渲染契约均通过，句柄/读缓冲留存均为零。全体 27 个分发资源重建后逐字节一致。

清理已消费字体副本、pytest 工作区、请求/输入和两份构建目录，共 19,855,690 字节。保留紧凑日志、XML、原版 JSON 和比较结果；当前及此前实际导出观察由 C9 保留至默认引擎集成验收，未新增大二进制入库。默认转换器、缓存持有者、打包和实际 Win7 资格仍待后续，不提升生产 pin。

回执：[office-font-discovery-checks.json](../../migration/candidates/rc022/office-font-discovery-checks.json)。
