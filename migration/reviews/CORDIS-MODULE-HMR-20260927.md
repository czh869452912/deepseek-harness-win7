# 模块 HMR：替换、依赖与错误边界

固定上游 cd5ef8148158c3a752a658978873241fdf8e2bbc，真实临时模块文件，运行上游 Hmr.partialReload 与 Python 模块刷新入口。

C52–C57 全部匹配：入口替换、导入语法失败保留旧插件、apply 失败保留 FAILED 新 fiber、连续两次替换、依赖更新、依赖导入失败保留旧插件。

修复三项：apply 失败不再触发额外回滚；watch 注册更新为新类；依赖按导入顺序重新编译，更新 sys.modules 与 Loader loadCache，导入失败恢复缓存。全部模块先导入再卸载，避免部分导入失败破坏旧插件。旧 fiber 保持原身份，不被修改为新插件实例。

首个差异报告 CORDIS-HMR-BEFORE-20260927.json 保留。最终报告 CORDIS-HMR-20260927.json；全量日志 CORDIS-HMR-FULL-20260927.txt：2977 passed、3 skipped、2 warnings，exit 0。

这些场景不是完整 HMR 状态空间证明；循环依赖、复杂包内相对导入、并发多文件变化仍须覆盖，不能将有限探针宣称为全部验收。
