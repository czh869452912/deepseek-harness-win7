# Issue #6：r1 后实例检查访问拒绝

## 现场证据与判断

[2026-11-05 最新反馈](https://github.com/czh869452912/deepseek-harness-win7/issues/6#issuecomment-6655696787)：报告者卸载手动安装的 .NET Framework 及更新包后，再次运行 `v0.1.5-rc.3-r1 AIO`，安装目录为 `C:\Program Files\DeepSeek Harness`。截图的详情和日志均为 `Instance check exit=1`、中文“对路径的访问被拒绝”。

能确定失败发生在实例检查阶段，尚未执行前置组件安装或应用解包；不能据此认定有运行实例、空格路径不受支持，或某个 .NET 版本是唯一根因。报告者的卸载描述不等同于已确认的实际 PowerShell/CLR 版本。无需将获取第三方更多信息设为开发前提。

原脚本可能在目录/父目录读取或 WMI 查询时报错，但 catch 只输出异常消息，未保留阶段、路径和行号。r1 区分返回4和其他失败是有效改进，但没有闭合 AIO 在旧环境上的安装链路。

## 本次实现

- 环境诊断包含实际 PowerShell、CLR、进程位数、OS 版本、管理员状态和安装路径。失败包含阶段、当前路径或 PID、ErrorId/Category、脚本位置和异常链。
- 路径检查改用 `File.GetAttributes` 逐层读取，通过 `Path.GetDirectoryName` 计算父路径，避免依赖 PowerShell 文件系统 provider 和 `DirectoryInfo.Parent`。仍逐层拒绝 reparse point，不修改目录 ACL。
- 安装根目录不再通过 `Directory.Exists` 将访问错误隐藏成不存在；仅明确的 FileNotFound/DirectoryNotFound 作为不存在处理。真实拒绝访问返回1；文件冒充目录同样拒绝。
- 实例检查可接收 `-LogPath`，直接追加 UTF-8 日志。NSIS 传入原来的临时日志路径，另保留检查返回值，避免详细错误被 `ExecToStack` 字符串长度截断。日志写入失败仍在控制台报告。PowerShell 无法启动时，详情及返回结果仍是诊断入口。
- WMI 查询明确采用 Stop 错误策略；运行实例仍返回4，检查失败仍阻止应用文件变更，不终止进程。

这些改动减少兼容性依赖并提高可诊断性，不构成已复现或修复该报告者唯一根因的结论。AIO 仍先检查实例，再安装系统组件；没有绕过检查或改变系统补丁顺序。

## 定向验证

选择实例检查的直接消费者：安装清理/登记、运行进程保护、junction 拒绝、失败代回滚和用户文件保留；同时覆盖 Standard/AIO 前置组件策略、x86/x64 包选择、失败/重启边界。运行环境是 Windows 11、Windows PowerShell 5.1 / CLR4、Python 3.8.10。

命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_desktop_packaging.py tests/test_desktop_prerequisite_flow.py tests/test_windows_prerequisites.py -q --durations=10 --junitxml=.goose/out/issue6-diagnostics-20261105-final/targeted.xml
```

结果：46 passed，14.98秒，退出0；日志/XML位于上述自有输出目录。真实 NTFS 根目录和父目录拒绝访问、WMI 终止/非终止错误、缺目录、文件冒充目录、长中文错误日志和链接祖先均有控制。ACL 测试仅修改自有夹具对象，并恢复原始 ACL。随后将测试准备也纳入 finally 保护，相关8项复验通过，3.41秒，退出0，记录 `.goose/out/issue6-probe-cleanup-20261105/`；不将其与46项相加。

初始拒绝用例只拒绝 ReadAttributes，Windows 仍可通过父目录列举取得属性，因此两项未能触发预期拒绝。补充对另一个自有父目录的 ListDirectory 拒绝后，确认实际 UnauthorizedAccessException，原失败保留于 `issue6-diagnostics-20261105-a`。后续一个测试在移动夹具目录时发生 WinError5，发生于调用产品代码之前；取消不必要的移动后，链接祖先控制通过。该观察保留在 `issue6-diagnostics-20261105-c`，不归因为安装器现场根因。

固定清单校验 NSIS 3.13 ZIP 后，在新目录解压并执行 Standard/AIO × x64/x86 四种编译，全部退出0；命令、耗时和编译日志位于 `.goose/out/issue6-nsis-20261105/`。AIO 有原有的 PrereqLimited 未使用编译警告。使用占位 payload，仅为脚本编译验证，未运行安装器，不是可交付分发包。

## Docker 与后续验收

本机 Docker Desktop 4.48.0 / Engine 28.5.1，`desktop-linux` 后端正常运行；没有现存本地容器镜像。普通 Linux 容器不能验证 Windows NTFS/WMI、PS2/旧 CLR、UAC、系统组件和重启流程。[微软 Windows 容器支持范围](https://learn.microsoft.com/en-us/virtualization/windowscontainers/deploy-containers/system-requirements)也不包含 Win7。

可以用 Docker 管理完整 Windows 虚拟机，例如 [dockur/windows](https://github.com/dockur/windows)列有 Win7 选项；这是虚拟机测试，需要核验实际镜像的 SP1/补丁/PowerShell 状态，并保留干净快照，不能把默认自动安装结果直接当作 stock Win7。其 Windows 11 Docker Desktop 路线要求嵌套虚拟化。本次读取 Docker 的 WSL2 后端，`/dev/kvm` 不存在；尚未配置该路线，没有下载镜像、改变 Docker/WSL 设置或修改系统组件。

本轮为本机定向开发完成，未运行完整发布门禁、未打正式 Portable、未发布或修改 GitHub issue。仍需在 Win7 SP1 干净/已升级快照验证实际 AIO 入口、组件安装、重启及再次安装；在该阶段完成前保持 issue 打开。后续如调整 AIO 的引导顺序，须在应用文件变更之前重新完成实例检查，不能把检查失败直接转为成功。

### 后续环境检查：KVM 模块已加载

同日继续排查发现，本机 AMD CPU 的虚拟化已开启，WSL2 能看到 `svm`，6.6.87.2 内核的 KVM/AMD 驱动配置为模块；此前设备缺失不代表缺少内核支持。执行 `wsl -d docker-desktop --exec modprobe kvm_amd` 成功退出0，生成 `/dev/kvm`，`lsmod` 确认 `kvm_amd`、`kvm` 已加载；无需下载驱动、重启 Docker 或改写 WSL 配置。

随后通过临时容器 `docker run --rm --network none --device /dev/kvm alpine:3.22 sh -c 'test -c /dev/kvm && ls -l /dev/kvm'` 验证设备能传入 Docker 容器，退出0。本次新增本地 Alpine 镜像，拉取摘要为 `sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f`；临时容器已退出删除。设备可见尚不等于实际 Win7 虚拟机或安装器验收通过。模块加载属于当前 WSL 运行期状态，完整关闭 WSL 或电脑重启后应重新检查，必要时重跑上述 modprobe 命令。

### 提交后验证：ACL 测试恢复补强

产品改动及初始测试随 `54d00e6a` 推送。后续文件遍历发现，自有 ACL 测试夹具仍有本次添加的拒绝规则：原测试将未标记修改的 DirectorySecurity 对象交回 SetAccessControl，未保证 DACL 实际恢复；文件可读不能证明权限描述符已恢复。以上早期结果中“恢复原始 ACL”的说法应以本段修正为准。

测试现保存原始 Access SDDL，恢复时重新应用该描述符以标记待写入部分，并在 finally 中核对两个对象的实际 SDDL 与原值完全一致。仅对已确认的四个历史自有工作区中本测试创建的24个对象作检查，移除本测试添加的当前用户显式 ReadAttributes/ListDirectory Deny，保留其他规则；逐对象前后记录在 `.goose/out/issue6-fixture-acl-restoration.json`，没有更改真实工作区权限或删除夹具。补强后的三个直接消费者模块46项通过，16.97秒，退出0，记录 `.goose/out/issue6-postpush-54d00e6a/`；该记录使用修正后的测试，不标为原54d00e6a完整提交的验收。

### Docker Win7 客体：发现并修复 PS2 实际退出码丢失

`becea44f` 推送后，原定向46项再次通过（17.17秒），记录 `.goose/out/issue6-postpush-becea44f/`。随后使用固定 Docker 镜像 `dockurr/windows@sha256:16fd7c39a3e48bb946d29c59dc6015942e5b900a1fa5d7e5552053bfc48ee2ea` 建立独立客体。默认 Win7 镜像来自工具选择的 bobpony 镜像站，不宣称是已由微软来源校验的发行介质；来源、大小、SHA-256 记录于 `.goose/out/issue6-win7-54d00e6a/media.json`。客体实测 Windows 7 Ultimate SP1 / 6.1.7601、x64、PowerShell 2.0、CLR 2.0.50727.5420，前置组件检查显示 SSU/SHA2/D3D/.NET/PS 均缺。虚拟机仅绑定本机18006端口，无外网 RDP 暴露。

原始产品字节在客体中核对一致；正常目录检查的新旧版本都返回0，未复现第三方现场的唯一根因。但是原脚本在文件拒绝、链接拒绝、真实权限拒绝、Host 占用时，虽然日志正确，实际进程退出码却全为0，可能错误放行安装。进一步的最小探针确认：普通 `param` 脚本返回4，而加上 `[Parameter(Mandatory=$true)]` 的 advanced script 在 PS2 `-File` 下返回0；调整换行或把逻辑移入函数都无效，直接终止进程虽能设码但不采用该方式绕过正常清理。

本次将清理脚本改为基本参数入口，在脚本体内拒绝缺少必需参数；同样处理直接消费者 `publish-installation.ps1`，否则发布失败的1/5也可能丢失。未强制退出宿主或改变回滚逻辑。客体候选探针已证明基本入口下的0/1/4正常，真实 ACL 拒绝定位到具体路径和行号，恢复后的两个 SDDL 与原值一致。新增缺参/非法发布输入控制，本机三个模块51项通过（17.14秒），记录 `.goose/out/issue6-ps2-exitcode-fixed/`；最终提交后的客体验证另记。

初始客体探针自身有输出句柄冲突，第二轮还存在退出码收集歧义；保留全部原始日志。最终驱动改用独立 Process 标准输出/错误管道及真实 ExitCode，避免把这些驱动问题算作产品失败。各版探针、初始失败和最小复现位于 `.goose/out/issue6-win7-54d00e6a/`。该目录名来自初始提交，后续输入必须按单独哈希清单区分，不能把不同候选混为一次资格。

### 最终提交后的定向结果

产品提交 `912248536bd71a78a75c25c672e36a5486ead78b` 已推送至 `codex/win7-instance-check-diagnostics`。对该提交运行上述三个直接消费者模块：51 passed，17.34秒，退出0，记录 `.goose/out/issue6-postpush-91224853/`。同一产品输入的 Standard/AIO × x86/x64 四种 NSIS 占位 payload 编译全部退出0，记录 `.goose/out/issue6-nsis-91224853/`；仍只作为脚本编译证据。

Win7 SP1 / PS2 客体运行最终源脚本的 `probe-final.ps1`，`guest-final.log` 为 `RESULT=PASS`：存在/缺失目录返回0，文件冒充目录、junction、真实拒绝访问和缺少必需参数返回1，受控运行 Host 返回4；拒绝访问日志包含实际路径、行号和 UnauthorizedAccessException，测试 ACL 的两个 SDDL 均确认恢复。非法发布输入下，旧版脚本实际退出0，新版退出1，且没有生成发布目录；原有测试用户文件保持不变。该探针仅终止自己创建的模拟 Host，不是完整应用运行验收。

最终客体输入哈希、原始日志/探针哈希、产品提交和本机 XML/编译报告关联记录在 `.goose/out/issue6-postpush-91224853/receipt.json`。此次验证覆盖本轮改动和旧 PowerShell 的真实进程返回码，未执行完整 AIO 系统组件安装、重启链路、正式 Portable 或统一发布门禁；第三方现场的唯一根因仍未确认，issue 继续保持打开。

验证结束后已正常停止 Docker 虚拟机容器，保留其磁盘及全部本轮观察，不再占用客体运行内存。

### 后续完整 AIO 实测：NSIS / PS2 输入管道

继续实测前，在容器停止状态将40 GiB原始客体磁盘转换为独立压缩 qcow2 备份，结构检查无错误，逐逻辑内容比较为 `Images are identical`。备份及 SHA-256 记录于 `.goose/out/issue6-aio-110085ec/baseline.json`。此前 Docker 停止不等同于已证明 Windows 干净关机，备份按冷态原字节保留，不把镜像站介质称为微软原版认证介质。

使用当前安装器、已逐文件核对的真实应用载荷和固定哈希的五项 x64 微软输入构建349,945,529字节 AIO（SHA-256 `d2fc080800c717720987ce02ab1b8f90611bae20456571ad20b456b729ef30d1`），不是占位安装器。客体仍为 PS2/CLR2，SSU/SHA2/D3D/.NET/PS 全缺且无待重启。容器 FORWARD 链拒绝客体网桥向外转发，仅保留容器本地共享，防止联网更新混入安装结果。

首次测试驱动在 SMB 共享上创建输出目录时异常；目录已实际创建，但 .NET 报找不到文件。该轮未启动产品，失败原文单独保留；改为主机预建输出目录后继续。真实 AIO 随即在实例检查返回1，尚未开始补丁。GUI同样复现，截图和 round-2 日志保留；直接执行同一清理脚本成功不足以证明该 NSIS 载体通过。

最小 NSIS / PS2 探针分别采用 Write-Host、Console.WriteLine、Write-Output，未指定 InputFormat 均返回1及 `Access to the path is denied.`；加 `-InputFormat None` 后三行均输出且退出4。将所有六处安装/卸载 PowerShell 载体显式设为 None，避免 PS2 消费 nsExec 重定向的标准输入。同时按 [NSIS FileOpen 文档](https://nsis.sourceforge.io/Docs/Chapter4.html#fileopen)修复日志追加：`a` 保留内容但指针仍在开头，必须 FileSeek 到 END 后再写返回值，否则会覆盖脚本诊断。

新增实际 NSIS 集成回归，仅用可控策略返回3010，在应用解包和系统修改前停止；验证原始诊断保留、实际 PowerShell 参数及重启返回码。本机52项通过（19.14秒），四种 Standard/AIO × x86/x64 编译通过。Win7 客体中使用真实安装器入口加模拟策略，同样正确返回3010，日志完整，实例检查返回0。修复提交 `d828df425dba777e0df6b0e271f12b4ebb09046a` 已推送；包含真实补丁的重新编译及后续轮次另记。该结果解释了本机可复现的同文错误，仍不冒称已直接确认第三方机器的唯一根因。

### 实际补丁返回码采集补强

`d828df42` 的真实包经过 SSU/SHA-2 首次重启后，D3D/.NET/WMF 已执行，但日志把所有补丁退出码都写成0。受控 `cmd.exe /c exit` 实验证明原 `Start-Process -PassThru` 对象在 PS2 下丢失实际退出码：0、7、3010、1641、2359302、2149842967 均被采集为0。不能单靠 CBS/WindowsUpdate 两个待重启键代替真实返回码；旧轮次继续执行 WMF 时 .NET 的真实返回码不可确认，不将其当作返回码边界的通过证据。最终候选中实际观察到 .NET 返回0、WMF返回3010，继续安装 WMF 符合本次观测到的策略。

改为直接构造并启动 `Diagnostics.Process` 持有原生进程句柄，保留原30分钟超时、终止超时进程和无符号状态码规范化。新增实际子进程六种状态控制，本机三个直接消费者模块53项通过（19.65秒），记录 `.goose/out/issue6-native-servicing-exit/`。产品提交 `449380de0fa49461ed4cd68fbdfb046acfc49864` 已推送；全部四种 NSIS 配置编译通过，记录 `.goose/out/issue6-nsis-449380de/`。

在原冷态备份上创建独立 qcow2 写入层，旧候选正常关机，磁盘及其失败记录保留。新容器 `dsh-issue6-aio-final` 仅监听本机18007，基盘只读挂载，继续阻断客体外网转发。原始 PS2/CLR2 中对同一六类退出码作前后对照，旧实现全部0，新实现全部与预期一致。对照只运行自有目录中的 cmd 副本，不执行系统安装。

最终真实 AIO 复用并逐文件复核未变的4,244项真实载荷，冻结新的安装器输入后重新编译，产物349,950,705字节，SHA-256 `13bf82d0d134dadcbf9d5d3598a7cb628eabe1e0260b2dca9b2725da22234467`；完整输入和命令见 `.goose/out/issue6-aio-110085ec/repack-449380de/repack.json`。这是本轮 Win7 x64 实测包，未作为正式发行资格。最终客体原始轮次记录位于 `.goose/out/issue6-win7-54d00e6a/shared/aio-final/`；该目录与原始/中间失败候选分开。

### 最终候选：真实 AIO、两次重启与安装后运行

同一个上述 SHA-256 的真实 AIO 在阻断客体外网转发的 Win7 SP1 x64 中完成三轮安装：

| 轮次 | 实际组件退出码 | 安装器退出码 / 耗时 | 边界检查 |
| --- | --- | --- | --- |
| 1，PS2 / CLR2 | SSU=0，SHA-2=3010 | 3010 / 64.61秒 | 尚未解包应用，正常重启 |
| 2，PS2 / CLR2 | D3D=0，.NET 4.7.2=0，WMF=3010 | 3010 / 367.47秒 | 尚未解包应用，正常重启 |
| 3，PS5.1 / CLR4 | 前置组件已满足，无补丁执行 | 0 / 41.86秒 | 发布并登记真实应用代 |

每轮保留 before/after 快照、真实进程退出码和原始 NSIS 诊断；不同 Boot 标识证明两次客体重启。第三轮后实际 PowerShell 为 `5.1.14409.1005`，CLR 为 `4.0.30319.42000`，.NET Release 为 `461814`，五项前置组件检测均为真，无待重启标记。安装位置为 `C:\Program Files\DeepSeek Harness`，应用代为 `0.1.5-rc.3-r1-380707775648`；预先放入根目录的用户文件保持原文。客体时钟与主机 UTC 存在偏移，采用每轮顺序、耗时和 Boot 标识解释时序，不以跨机器 UTC 差计算安装耗时。

安装后的真实 Electron 22.3.27 / Node 16.17.1 调用同代 embedded Python，原有进程观察器9项检查通过：原始首页、12路交错 HEAD、实际 Typert RPC、2 MiB请求/64 KiB帧、流式与取消、来源拒绝、无待处理流、进程树异常退出释放 profile、EOF正常关闭。`pipe-report.json` 的 qualified 仅指该观察器范围，不等同于发布资格。

同代 Python / WinPTY / PowerShell 工具提供者5项通过：实际5.1版本、跨调用变量持久化、中文输出、原生失败退出码7、owner/context卸载后的终端清理。该探针装配实际提供者并调用真实工具；未请求 LLM，不冒称完整 CLI 对话验收。桌面应用用独立测试 DSH_HOME 启动，经原始内部测试提示和稍后配置密钥入口进入首页，再从 Application → Quit 正常退出。截图位于 `.goose/out/issue6-aio-110085ec/installed-win7.png`。

第四轮再次执行同一 AIO，实例检查为0，日志为 `Prerequisites already satisfied`，没有 Installing 行、没有重启，15.11秒退出1。这是当前产品对“完全相同的应用代已存在”的明确拒绝策略；不把退出1误写成安装成功，也不把它归为补丁失败。重复前后安装登记、前置状态及用户文件均保留。

最终检查逐项核对安装清单：原4,244项载荷清单保留，登记脚本按设计追加生成的卸载器一项；运行后78个 `__pycache__/*.pyc` 哈希变化，所有其他列出文件符合预期。缓存变化的路径和前后哈希保留在 `final-integrity.json`，不宣称运行后所有文件仍与压缩包字节相同。首次探针误将登记后的清单视为完全不变，随后严格探针观察到首个字节码缓存变化；修正为核对原清单行、唯一卸载器追加行及逐文件哈希并单列缓存，原始观察保留，不归为产品安装失败。

Application → Quit 后 WMI 未见安装代下的残留进程。通过客体 shutdown 正常关机，Docker最终 exited / 0，日志为 `Shutdown completed!`，保留原始磁盘、只读冷态备份和本轮写入层。最终外网阻断规则计数及容器状态一并保留。本轮候选、安装包、四轮日志、安装后探针、本机定向XML及四配置编译证据的哈希关联见 `.goose/out/issue6-aio-110085ec/final-receipt.json`。

以上完成真实 Win7 x64 AIO 补丁安装、重启、应用安装及安装后运行验证。x86只有四配置中的编译证据，尚未在x86客体实装；未跑统一发布门禁、未发布 release、未验证外部 API。第三方机器的唯一根因仍未直接确认，issue不自动关闭。
