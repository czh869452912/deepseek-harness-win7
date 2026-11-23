# Win7 运行性能与全套验证耗时分析

2026-11-23

优先检查 **Host HMR 的空闲文件读取**和 **JSONL 冷读的字节复制**。当前 Python 实现与固定上游有相同的行为目标，但在这两条路径上可以直接从源码确认额外工作。终端滚屏分页也会重复处理历史文本。全套验证与产品共享一部分文件和子进程开销，历史计时还显示发行回执夹具本身值得单独优化。

本报告对照产品提交 `a4214b06` 与仓库固定上游 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`，并复核 2026-10-08 两份完整 Python 回归 JUnit。运行部分是源码归因，当前 Win7 实机上的耗时、CPU 和内存占比仍待测量。历史回归对应当时的候选，能用于选择调查顺序。 [上游基线](../../migration/baseline.json) · [历史性能记录](2026-10-08-full-validation-performance-progress.md)

## 运行时实现

### Host HMR 在空闲时读取配置

固定上游使用 Chokidar 监听文件事件，等写入稳定后触发配置刷新。Python Host 的 HMR 每轮先休眠 20 ms，再同步检查注册文件。对仍存在的配置，即使时间戳和大小相同，它也会打开文件读全文以确认内容是否更改。这会增加空闲唤醒、文件打开和读取次数，实际物理磁盘开销取决于文件缓存及存储环境。Web 另有默认每 500 ms 检查客户端 bundle 的 HMR，Desktop 禁用了这一路客户端轮询。 [固定上游配置监听](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/boot/hmr/src/watch-config.ts#L47) · [Python Host HMR](../../dsh/cordis/hmr.py#L485) · [客户端 HMR](../../dsh/client/hmr.py#L20) · [Desktop 配置](../../dsh/host/desktop/runtime.py#L165)

优先考虑由 Win7 可用的目录变更通知触发检查，收到相关事件后再走现有稳定性判断。低频核对可覆盖通知溢出或监听重建。验证覆盖同大小同时间戳编辑、原子替换、文件暂时不存在及插件卸载时取消监听。

### JSONL 冷读产生额外的临时对象

两边都需要按文件身份读取稳定快照，当前后端也已有按修订命中的冷读缓存。缓存未命中时，上游扫描器用 `Buffer.subarray()` 在原始缓冲区上取视图。Python 的 `bytes` 切片会复制日志主体，扫描器还把行片段转入 `bytearray` 再生成 `bytes`。冻结事件时，上游在原对象图上冻结，Python 遇到普通 `dict`、`list` 会构造不可变容器。在长会话恢复时，原始字节、临时副本和解析对象可能同时存活。会话列表则有另一种成本，枚举会话目录并读取头部，随会话数增加。 [固定上游扫描器](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/session/session-persistence-jsonl/src/format.ts#L532) · [Python 扫描器](../../dsh/session/jsonl_current.py#L133) · [冻结实现](../../dsh/core/session/json.py#L98) · [会话冷读](../../dsh/session/jsonl_backend_current.py#L687) · [会话列表](../../dsh/session/jsonl_backend_current.py#L319)

先让扫描器使用同一个缓冲区及偏移量，完整行直接解码，只有跨块行才累计片段。随后测量事件转换是否仍有明显峰值，再判断能否在解析边界只构造一次不可变表示。若列表本身仍慢，可按已验证的文件身份和修订增量复用会话头。检查旧日志、zstd、损坏尾部恢复和并发追加，持久化刷盘继续服从现有耐久性合同。

### 终端分页重复整理滚屏，WinPTY 定时检查进程退出

当前持久 PowerShell 已和固定上游一样，每轮先检查最新一页，遇到结束标记或需要返回部分结果时再收集更多历史。Python 的底层分页仍先取得整个滚屏快照，将文本按换行拆成列表，再选出请求的页面。滚屏较长时，读一页和连续翻页都会重复分割。Win7 的 WinPTY 还会约每 10 ms 检查一次进程句柄，上游终端载体使用退出回调。首次工具调用的 PowerShell 与 WinPTY 启动成本，以及持久 Shell 的常驻资源，应分别测量。 [固定上游持久 PowerShell](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/shell/tool-pwsh-persistent/src/index.ts#L358) · [固定上游终端退出通知](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/subprocess/subprocess-local/src/terminal.ts#L107) · [当前 PowerShell](../../dsh/terminal/persistent_authorized.py#L175) · [分页读取](../../dsh/terminal/session.py#L150) · [WinPTY 等待](../../dsh/subprocess/winpty.py#L133)

先评估让分页按行直接读取所需范围，保持偏移、UTF-8 字节截断和已丢弃滚屏的语义。再评估通过进程句柄通知等待退出，核对取消、退出码及进程树回收。

### 冷启动和 Desktop 常驻需要按进程归因

Host 启动会预检配置、装配 Loader 并检查插件激活。Desktop 还要创建 Electron 窗口并启动独立 Python Host。现有材料缺少这些阶段的目标机计时和分进程内存数据。若首屏前主要时间落在 Host，先看同一次装配里的重复文件读取、路径解析和配置转换。若资源主要集中在 Electron 或渲染进程，继续按首屏和可选功能初始化归因。 [Host 装配](../../dsh/boot/app_boot.py#L456) · [Host 激活检查](../../dsh/boot/app_boot.py#L822) · [Desktop 窗口](../../apps/desktop/main.cjs#L46) · [Desktop Host 子进程](../../apps/desktop/host-process.cjs#L21)

## 全套验证耗时

2026-10-08 的两份 JUnit 各收集 10,094 项，均完成 Python 回归并记录了失败。按 `test_current_release_gate` 的 JUnit 用例时长求和，该模块约占当时整轮的三分之一。用例时长含准备和清理，最慢的首批用例包含多组实际 Source 与 Native 观察的冷构造。 [历史验证记录](2026-10-08-full-validation-performance-progress.md)

| 指标 | `13d0ae22` | `c53fff6d` |
| --- | ---: | ---: |
| JUnit 整轮用时 | 3,467.3 秒 | 3,414.5 秒 |
| `test_current_release_gate` 累计用时 | 1,178.7 秒 | 1,212.3 秒 |
| 冷夹具构造及其所在用例 | 286.5 秒 | 308.3 秒，含首次失败及后续构造 |

历史回执校验剖析提供了重复路径操作的实例。局部复用路径解析后，`Path.resolve` 从 5,279 次降至 1,186 次，`nt._getfinalpathname` 从 20,605 次降至 3,571 次。前后结果绑定当时的受控回执，这组数据适合定位重复文件操作。整轮加速仍需用具体候选和相同环境比较。 [历史路径解析剖析](2026-10-08-full-validation-performance-progress.md)

当前完整发行门禁还包含 x64 Portable 构建、全量 Python 回归、固定上游 Source、配对验证，以及 x64 和 x86 的实际解压与 Desktop 验收。历史两轮在 Python 回归之后停下。真实 PowerShell、浏览器和文件操作会复用产品路径。回执构造、重复校验、打包和解压另外增加了门禁墙钟时间。 [当前发行门禁](../../scripts/current_release_gate.py#L220)

测试端优先给夹具准备、用例执行、清理及各发行阶段分别计时。针对反复篡改同一类回执的拒绝用例，可以在同一轮内复用只读基线，只为当前用例隔离变更，仍保留真实文件边界、字节比对和独立真实旅程的验证入口。这样可以先判断重复路径解析、序列化和深复制各占多少。 [回执验证入口](../../tests/test_current_release_gate.py#L100) · [回执夹具](../../tests/test_current_release_gate.py#L1903) · [验证范围指引](../testing.md)

## 建议的最小测量

在同一台目标 Win7 上用同一包采样一轮启动、空闲一分钟、首条和第二条 Shell 命令、一个长会话的冷读和暖读。记录 Host 就绪和首屏可用时刻，分进程记录 CPU 时间、私有内存及工作集。空闲阶段额外记录配置打开次数，终端阶段记录 WinPTY 与 PowerShell 子进程，长会话阶段记录文件大小与峰值。先用这组数据区分持续轮询、子进程常驻和一次性分配，再对命中的实现与直接消费者做定向复验。
