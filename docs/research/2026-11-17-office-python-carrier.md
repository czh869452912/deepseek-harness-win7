# Office Python 载体

C9-BM 已把 C9-BL 的实际 WASM 转换迁至 Python 3.8 标准库载体。运行时只需要 Python、Chromium 和原始 WASM 资产；Node/Playwright 仍可用于独立参考实验，不参与本轮合格 Python 转换。见[精确检查](../../migration/candidates/rc022/office-python-carrier-checks.json)。

载体为每项操作建立随机私有路径、精确资产路由和一次性浏览器配置目录。结果在读取前检查长度，二进制通过 base64 保留原字节。顶层页面、worker 与 pthread 脚本均使用 COOP/COEP 隔离头。Chromium 108 的无头生命周期由自动分配的本机调试监听维持，载体不使用 CDP；监听随进程树一并结束。

Windows 浏览器在执行首条指令前加入 Job。成功、同步/异步异常、期限、原始 AbortSignal、重复 task cancel 和并发 close 都等待进程范围结束，然后关闭 HTTP 服务并删除配置目录。真实浏览器 17 项定向检查通过；x64 与 x86 Python 分别实际完成 DOCX→PDF/TXT 与 PDF→PNG。TXT 和 PNG 字节与独立参考相同，文档、Office 和线程池在回传前释放。x86 Python 驱动本机同一个浏览器，不代表 32 位 Windows 系统已验收。

诊断保留了最初无头浏览器提前退出、缺少 pthread 隔离头及实验 trace 数组无法克隆导致的超时。额外诊断时临时尝试的 no-sandbox 参数未解决后者，已移除。最终运行使用默认浏览器沙箱，所有已用临时配置目录、测试工作区均已清理，失败报告和真实转换观察保留供下一步对照。

此部分只完成载体。Arial 解析器仍是受控协作者；默认 Office 服务、原版字体规则、完整格式与图片操作、Portable 许可资产和 Win7 实际执行尚待后续部分完成。
