# HMR 循环依赖和多文件事务

C60 真实模块验证循环依赖与 Python 包内相对导入；C61 同批两个独立插件变化，第二个导入失败时两者都保留旧运行时。

先前失败分别保存在 CORDIS-HMR-CYCLE-BEFORE-20260927.json、CORDIS-HMR-BATCH-BEFORE-20260927.json。修复后 C52–C57/C60/C61 全匹配，见 CORDIS-HMR-COMPLEX-20260927.json。

实现递归发现本地模块依赖；同批变更组成一个导入事务；全部相关 sys.modules 项先移除，通过临时源码加载器处理循环、相对导入及避免旧 pyc。失败恢复缓存和父包属性，成功才替换插件。旧 Runtime 不被当成新 Runtime 修改。

专项 tests/test_cordis_hmr_observations.py、test_cordis_core_exact_parity.py、1to1/boot/app_boot/test_hmr_config.py：20 passed。完整验证统一记录在后续固定候选报告中。
