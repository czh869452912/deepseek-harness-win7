# SQLite schema-19 推进

五个可选会话工具在干净产品 `ae2c1abe` 完整签收，证据台账提交为 `849ed8b1`。随后对照固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc` 的 `session/session-persistence-sqlite` 发现，本地原有 `persistence_sqlite.py` 是不同的旧布局，尚未实现规范 STRICT schema-19。不会重贴版本号或静默迁移旧库来声称等价。

首个格式实现包含独立 chunk-row codec、tagged provenance varints、物理记录压缩/解码和损坏尾段分类。826 组实际原版/原生观察匹配，两套原样压缩套件 42 项断言通过；新增实际 SQLite 3.51.2 STRICT ANY 写入/关闭后 detached read、跨缓冲区压缩输出边界及资产拒绝测试。格式编码与 JSONL 独立，写入最少三条/最多 1024 条/最多 1048576 UTF-8 字节，短尾保留标量。

私有 Zstandard 1.5.7 由未修改源码 `f8745da6ff1ad1e7bab384bd1f9d742439278e99`、固定 LLVM-MinGW MSVCRT 工具链编译，DLL 808448 字节，SHA-256 `93d87fd026179637db29580e1db2d1188954241293f0e2279f93a01e007a45cc`；仅导入 msvcrt.dll/KERNEL32.dll，目标 Windows 6.1。DLL、原版字典、七份许可证和构建来源均校验并随 Portable 打包，Node/编译器只是开发输入。普通 Windows 载入和当前主机验证不替代延期的 Win7 实机认证。[原版 Zstandard 发布](https://github.com/facebook/zstd/releases/tag/v1.5.7) 与 [官方 C API](https://raw.githubusercontent.com/facebook/zstd/v1.5.7/lib/zstd.h) 是外部构建依据。

研究保留数值与帧行为：`(seq0 + count) - 1` 的中间 IEEE-754 舍入使一个人工溢出向量被原版 codec 接受；Node 原版解码对部分截断帧产出空值，消费首帧并忽略后续帧/尾字节。这些实际观察按格式保留，未增加例外或放宽原版判据；下游持久化对人工历史的拒绝仍须单独验证。原生写入使用 one-shot dictionary API，研究 streaming writer 在六条记录上字节不同，已明确排除；读端使用实际匹配的流式首帧语义并在解析前约束 packed 输出。

原版完整 SQLite 研究套件先有缺失开发别名，补齐固定 fast-check/TypeScript 后为 129 passed、1 符号链接 EPERM、3 原版已有 skips。当前 token 没有 SeCreateSymbolicLinkPrivilege；没有修改系统权限、增设跳过或将该套件称为通过。格式的 42 项原样套件是独立有界范围，不能替代物理提供端的完整验收。全部原始研究、初始不匹配和编译 PE 日志留存于 `.goose/out/acp-a4-work`。

本实现尚待 clean committed 完整验收，当前门禁要求 336 必需 lane、十五组 1124 原版断言、51 双侧驱动与实际解压/浏览器，新的格式回执必须绑定完整原版/压缩输入/生成输入摘要以及七个模块、十一项资产。随后继续 schema-19 数据库所有权、lazy opening、journal/busy reservation、revision/stale append/repair、协调器与模型/profile/冷恢复消费者。完整 malformed/plugin ABI、跨进程/长历史、B/C/D、既有启动取消与整体范围开放，accepted_upstream 保持为空。
