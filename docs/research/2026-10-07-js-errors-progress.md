# JS 解析和业务错误边界

本部分将实际编译异常交给原版 Session 构造边界，使解析失败在 Ready 之前返回结果；原生继承 stack getter 补齐实际业务名称和消息，保留真实原生帧、原生构造函数及显式 own stack。普通 parse-only 和非工作流编译失败保持原有分类。

规范 C 构建和工作流构建已实际重新执行。worker SHA256 为 `032d3ad64ccdd38e0b7afb35153db156fe6469a385f707f31234dc9d2982b7e9`，workflow manifest 为 `c151658c0832e62dae18c804ef052ed022fb061303a918e900ff2facd244af14`。工作流 provenance 使用仓库内输入路径，不再依赖忽略目录中的候选源文件或构建后改写。

32 个实际原版 Session/realm/error 场景在 Root 与新构建解压包的自有 Python3.8.10 匹配。全部 22 个实际导入文件和 20 个私有资源核验 ZIP 字节；新包 SHA256 为 `1199df68e0cd8d77093b5323284e9154264b0a007bc6bf7f86cca3034fe8666e`。该包明确 dirty、非发布资格包，不能替代完整签收。

原生引擎帧格式、部分生成诊断和 stack descriptor 归属仍有平台差异。fixture 逐场景记录双方精确值，验证真实原生帧及原版业务首行后才赋比较标签；原始观察完整保留。不生成虚假 V8 帧，不声明完整 Node API 等价，也不新增既有九条 Source 缺陷豁免。

首轮接入为 69 passed / 28 failed：一项离线解释器控制误用了 Root venv 位置，二十七项门禁夹具被旧 Ready 验收的固定 19 资源检查提前拒绝。控制改用其明确的便携解释器模型；Ready/initial 验收改核对精确的 20 文件集合。初次 XML/日志保留，没有重试未改候选。修正后 191 项消费者、Ready/initial、解压拒绝与逐 lane 必需控制通过，385.34 秒；另 181 项既有实际 JS 会话/物理退出/子任务归属/工作流回归通过，22.81 秒。迁移只读 check 有效。

正式门禁已接入第 74 个实际配对、选定解压解释器观察、独立批准模块/资源、完整 Source 身份和错误观察。2522 必需 lane；全量收集 8981 项。109 文件独立资格归档为 `migration/evidence/artifacts/JS-ERRORS-ROOT-QUALIFICATION-20261007-49B118DF.zip`，SHA256 `b30b028ba2638b47d0f90bd07e1d61a6a1af7c066c91c488649c6c80d359f6bc`。

052 保持 running，须新的干净冻结完整回归、20 组 1911 原样 Source、全部配对、真实解压及原版浏览器通过后才能有界签收。最新完整签收仍 842d6373 / 62，054/055、036 更大 JS 范围与七父范围保持开放；实际 Windows7 验收仍按用户决定延期。
