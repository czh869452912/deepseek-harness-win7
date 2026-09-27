# Cordis 官方覆盖盘点

scripts/cordis_inventory.py 按固定 reference 的 Git tracked 清单建立来源及 SHA-256，不用 Python 测试数量充当上游覆盖率。

- 604 个来源文件（vendored foundations 与直接导入 Cordis 的官方测试）。
- 8405 个字面声明：核心生命周期 11、选定必要消费者 65、业务消费者 8329。
- it.each/动态参数化单列为待展开；间接依赖不能由直接 import 扫描替代。
- 11 个核心生命周期用例均能定位 Python 对应回归。

直接运行未修改的官方 cordis-lifecycle.spec.ts 与 app-boot/hmr-config.spec.ts：17/17 passed。
Python 生命周期、Boot HMR、profile HMR、Preset 回归闭包：45 passed。
命令、输出见 CORDIS-OFFICIAL-20260927.txt 与 CORDIS-CONSUMER-CLOSURE-20260927.txt。
开发专用 Vitest 4.1.8 与依赖锁位于 scripts/oracles/official，不属于产品依赖。

清单是可复查分母，不是8405项全部迁移完成声明。必要消费者仍需逐项语义审核，标题候选只用于导航。
