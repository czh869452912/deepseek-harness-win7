# Office 双架构离线运行时（C9-BU）

固定目标 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。安装目录中的默认 Office 服务现在接受已封存的 x64/x86 运行时清单：原版 WASM 0.2.3、对应 Chromium 108 快照、引擎许可证、Chromium LICENSE 和浏览器完整第三方许可证。清单逐文件记录大小和 SHA-256；不包含交互测试程序或生成的 debug.log。开发观察器的历史记录保持独立。

构建前显式采集两种架构，输出目录必须尚不存在：

```powershell
python scripts/acquire_office_runtime.py --source <固定原版源码和依赖> --node <构建用Node> --architecture x64 --output <新目录64>
python scripts/acquire_office_runtime.py --source <固定原版源码和依赖> --node <构建用Node> --architecture x86 --output <新目录32>
```

将两份已核验的架构目录放在同一个输入根下，使用 `scripts/build_portable.py --office-runtime <输入根> --architecture x64` 或 x86。构建环境也可设置 `DSH_OFFICE_RUNTIME_INPUT_ROOT`；产品启动不读取该环境变量，不下载运行时，不依赖预装 Node、Playwright 或用户浏览器。采集器验证官方原始 ZIP 和所有选定成员，实际打开对应浏览器的 chrome://credits 保存完整许可证，再删除下载 ZIP。构建只复制批准成员和 runtime.json；缺少输入时保留旧分发目录和 ZIP。

98 项定向测试覆盖输入封存、构建失败保全、默认服务及直接引擎消费者。独立目录分别通过 Python 3.8.10 x64/x86 及同架构 Chromium 的默认应用服务转换，原版 DOCX 的 TXT 输出 SHA-256 均为 `529cde620df98cd964bbdd3ef16c40e4858c0147287b700be7777768aab00e8d`，卸载后任务、转换器和状态为空。该目录仅包含本轮所需框架、bundle 配置和 Office 输入，解释器是外部固定输入；不等于完整 Portable 验收。

首轮修复了清单误收录生成日志、隔离夹具遗漏 bundle 配置两处问题。之后宿主整体卡顿造成两次启动超时，独立 Python/PowerShell 启动诊断及用户确认均保留；结束自有进程后，新鲜串行运行通过。没有把超时日志改为成功，也没有修改产品期限来掩盖宿主问题。

已按逐文件校验清理重复采集副本、失效隔离候选和自有工作区，保留命令、XML、原版观察、失败日志及清理回执。双架构主输入由 C9 持有，继续供格式矩阵及 Portable 资格消费，验收后只保留正式共享输入及必要记录。实际 Win7 客体、完整 Portable/发行门禁、生产 pin 与 accepted_upstream 晋升均尚未完成。

回执：[office-runtime-packaging-checks.json](../../migration/candidates/rc022/office-runtime-packaging-checks.json)。
