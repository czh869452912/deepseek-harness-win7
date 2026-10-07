# 默认 Cordis 工具与原生导出扩展

固定原版tool-cordis公开七个工具。此前Python manager隐式附加cordis_export，造成创造模式第一次模型请求的工具数量和完整顺序与原版不同。现在默认manager只注册原版完整定义；原生Python源码导出保留为独立、显式挂载的Cordis插件，具有实际tools/dynamicCordisRunner/fs依赖和可逆Agent所有权。

需要原生导出的用户预设可添加以下行，然后从该预设创建会话：

```yaml
- id: tool-python-export
  name: '@deepseek-ai/dsh-tool-python-export'
```

导出、构建、安装、升级、回退和既有授权/文件系统策略保持由原实现负责。153项真实合同/导出/安装消费者通过；新增实际两个创造会话验证默认均没有export，显式挂载只在拥有者可见，dispose后退役。导出测试通过实际插件挂载继续执行原来指定旧版本、Client项目、外部所有者拒绝和真实安装重启链。

既有Cordis双侧观察器原来把native_contracts目录当作实际定义输出，遗漏隐式工具；现从真实注册回调读取所有Tool定义，完整公开描述/参数/输出schema都会进入比较。原版13处既有精确Python语言提示转换仍保持，不借此忽略多余工具。新鲜Source/Root/自有Python3.8.10的92回调场景和实际七完整定义匹配，15505完整自有字节前后守卫通过；此旧回调观察器没有枚举完整实际导入闭包，不能替代完整profile观察。新鲜SDK三实际链30/14/18帧匹配，批准导入清单不变。77既有通用回归验证器测试通过，两项新的实际生命周期/roster成为必需lane。

41文件不可变归档migration/evidence/artifacts/CORDIS-EXPORT-QUALIFICATION-20261007-FAF716E8.zip，SHA256为5513866392078b262b9f2e6f0254d303f7b9e76e81cc322bb8de77b61315a866。完整profile父范围和新的干净完整冻结仍开放；下一步沿真实模型组装与原版浏览器补齐全部组合链。
