# P0：固定输入与发行门禁

目标上游保持 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。开发验证需要当前 Windows、Python 3.8.10 x64、Node 22.22.2 和 Git；Node 不进入便携发行物。

在没有 `.venv`、`node_modules` 的干净检出中运行：

```powershell
git submodule update --init --recursive
python scripts/verify_release.py --prepare
```

脚本建立 `.venv`，安装两个 Python 锁文件及两个 npm lockfile 指定的依赖，验证 reference SHA；随后构建 portable、运行完整 pytest、80 项上游消费者测试、67 个 Cordis 原始配对场景及精确 C58 差异验收，最后用包内 Python 隔离启动。报告写入 `.goose/out/release-gate`。只有全部通过才生成 `summary.json`；重新运行先移除旧成功标记。

打包只复制锁定的运行依赖，不复制整个开发环境。前端以 `scripts/frontend-inputs.json` 中的已入库产物及字节摘要为输入，不再覆盖混入 reference 的本机构建。输入缺失或摘要不符时，在替换旧发行目录之前失败。

`verify.yml` 提供 PR、手动和 reusable 验证入口。tag 发布调用相同门禁，下载并发布已验证的压缩包，不重新打包。这里的“可复现”指固定输入可重新安装、构建、验证，不声称 ZIP 时间戳或机器路径实现位级一致。

边界：当前前端仍是版本化预编译输入，不是当前上游源码重建或浏览器语义对齐证明；Web Connection 批次继续承担这部分工作。两个既有 pytest skip 是 Windows 不适用的 POSIX 行为；Proactor 清理警告保留在原始日志。Win7 真机验证继续暂缓。远程 Actions 是否运行以实际工作流结果为准，本地门禁成功不能代替它。
