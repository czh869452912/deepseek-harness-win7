# Office 默认 Cordis 提供方（C9-BT）

固定目标 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。当前基线的 office-kit 绑定改为组合插件，在没有注入 officeKitEngine 时挂载默认引擎服务，再挂载应用 Office 服务；已有注入提供方保留其所有权。运行时懒加载、失败可重试、日志去重，卸载等待加载和浏览器任务排空。

生产发现只接受安装目录下批准的实体运行时清单，逐文件检查大小和 SHA，拒绝目录链接及路径逃逸，不搜索开发观察器、用户浏览器、Node 或下载替代。批准表暂为空，等待下一段独立输入与许可证封存后填写；本段不声称已交付可用 Portable。

79 项定向检查通过，覆盖默认提供方、应用消费者及所有直接引擎提供层。实际原版 DOCX 经默认服务、应用队列和真实浏览器转换为输出存储的 TXT，字节与已记录的原版公开 SDK 观察一致。测试中的显式运行时定位替换只用于选定独立测试输入；生产定位不启用该替换。首轮夹具漏传输出归属、混用了 Worker/公开 SDK 的 TXT 观察，并发现 Windows 根路径需显式拒绝，均已修正，保留原失败日志。

已清理本段三个 pytest 工作区、tmp/home，命令、XML 和实际 Source 结果保留，空间统计见回执。另一运行时采集任务仍由 C9 拥有并供正在进行的打包工作消费。生产 pin、accepted_upstream、实际 Win7 资格及完整发行门禁不变。

回执：[office-default-provider-checks.json](../../migration/candidates/rc022/office-default-provider-checks.json)。
