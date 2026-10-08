# 完整验证的重复路径解析优化

本轮按“先解决完整验证”推进。基础 HEAD 为 `4e6a1e85`，固定 Source 仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。先准备 Node 22.22.2 和两组锁定观察器依赖，再使用真实 `tests/test_current_release_gate.py::extracted_receipt` 返回的完整 archive/candidate/report tuple 测量；不从 provenance 猜测 candidate。

## 修改与拒绝边界

23 个已声明输入守卫的校验器复用既有 `scripts/import_paths.py::resolve_import_path`。只在一次 `check_files=False` 的导入清单校验内记录物理上不存在、没有重解析的首级目录。现存目录、普通/悬空链接、不规范路径，以及所有 `check_files=True` 仍沿用逐文件真实解析；没有文件散列、实际观察或跨次校验缓存。

LLM 汇总/子组、Session、DeepSeek、Agent、问答、工具、Message、FS、Unicode 和 Win32 元数据均保留原拒绝条件。23 文件 AST 对照还原允许的 helper 导入、输入声明、局部缺失目录记录和解析调用后，与基础 Git 的完整原始 AST 一致。helper 加入各 Source/observer 输入声明；四个 Node 回执提供端同步记录该字节。独立 CLI 和包内导入分别选择明确的 helper 模块位置。

新增 45 项路径/字节回归全部加入强制 lane，覆盖五个分组校验器的存在/缺失目录、真实正常/悬空 Windows junction 和两种校验模式，以及跨次文件内容变更拒绝。与既有 helper 和便携预检合计 90 passed / 116.57 秒；不与此前 55 或 28 项重复累加。

## 完整正例测量

| 项目 | 原始基线 | 优化后 |
|---|---:|---:|
| 完整正例回执字节 | 17339427 | 17341210 |
| 三次完整校验 / 秒 | 1.6294 / 1.5951 / 1.5483 | 0.6176 / 0.6033 / 0.5309 |
| 冷构造 / 秒 | 380.58 | 303.53 |
| cProfile 总时间 / 秒 | 2.186 | 0.904 |
| `Path.resolve` 次数 | 5279 | 1186 |
| `nt._getfinalpathname` 次数 | 20605 | 3571 |

两次为独立新鲜完整正例，新增 helper 身份字段使字节数不同。完整校验中位数减少约 62%，只代表该合成控制；冷构造涉及真实多组 Source/Root 观察和 I/O，不据此归因或推算整套加速比例。23 字节假 ZIP 是测试控制，不是可发行候选。

保留三类初始拒绝：测试把悬空 junction 的 Python 3.8 原有行为错误预期为统一 ValueError，改为直接对照原始物理解析；新增 helper guard 未同步 Node 提供端而被完整正例拒绝；独立 Runtime Context CLI 缺少包搜索路径而退出，已明确区分脚本/包导入，并由独立四组真实配对匹配复验。原日志/XML/完整观察和改正后的材料分开保存，没有放宽产品判据。

有限测量归档 `migration/evidence/artifacts/VALIDATION-PERFORMANCE-20261008-4E6A1E85.zip`，106 成员 / 2357893 字节，SHA-256 `58b04f4ef50d49786bc99c154d3349bc2eeaf6013b0ff425f974bb9b671f2e31`。逐成员完整字节与 CRC 已核验；保存实际 tuple、profile、拒绝/通过日志/XML、producer、AST 审计、修改后被测字节和基础 Git 逻辑 blob。基础 blob 不冒充原工作区物理换行；归档也不冒充完整发行资格。

## 完整发行验收

本轮尚待提交后冻结的干净完整门禁：全套 `pytest tests` 保持正常 3600 秒预算，新增强制 lane，83 配对、20 组 Source、同一精确便携包的实际解压和原版浏览器全部执行。不得用本页有限测量或 90 项预检替代通过。

最新完整产品签收暂仍为原始 `83026446` 的 65 个有界合同。056–064、六个父范围和 JS036 不因性能修改自动转状态；九项原版例外、Python 调度适配以及用户延期的 Win7/目标浏览器认证均保持。
