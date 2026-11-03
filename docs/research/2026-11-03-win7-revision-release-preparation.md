# Windows 分发修订版发行准备

用户选择新增 `v0.1.5-rc.3-r1`，保留旧版标签与产物。PR #8 已合并为 `269adec4bf3e692044c7d45628fa8c30f3a561d7`。

`r1` 表示本项目第一次分发修订；`win7` 继续只用于 Windows 7 平台标识。版本调整后，更新器、安装器、目录选择器和冷启动准备的直接消费者联合验证为 124 passed / 26.55 秒，记录 `.goose/out/rc3r1-final-targeted.xml`。旧标号的构建及 gate 已中止，保留记录，不转用为新标号资格。

首次 CI [41644050498](https://github.com/czh869452912/deepseek-harness-win7/actions/runs/41644050498) 在前端源文件契约失败：干净环境缺少 `reference/packages/client/ui-dockkit/lib/index.js`。本地已有忽略的生成文件，原先定向验证未暴露缺项。准备脚本现将 ui-dockkit 纳入 client 库构建；新增检查直接从已封存 sourcemap 提取库依赖，防止相同遗漏。未修改上游源码或原始浏览器分发字节。

修复后使用固定 Node 22.22.2、CI 环境变量执行该库生成，再运行准备脚本及实际前端源文件契约：10 passed / 6.55 秒，记录 `.goose/out/win7r1-cold-prep-targeted.xml`。此前版本/更新器/安装器/选择器的直接消费者定向验证为 114 passed / 20.90 秒，记录 `.goose/out/distribution-revision-targeted.xml`。

发现 CI 失败后中止尚未进入完整 pytest 的本地 gate，保留 `.goose/out/win7r1-release-daea0cbe-a` 及中止记录。该次结果不作为完整验收。正式资格必须重新绑定稳定提交、输入和精确归档；定向结果及旧版资格均不替代。
