# Python 插件的 HTTPS ZIP 获取与来源记录

日期：2026-10-01。产品起点 `81035d1d`，固定参考版本
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。本批次落实插件发行评估中的
Release ZIP 获取渠道，继续使用原生 Python 3.8.10 和统一 profile/Loader。
这是 Python/Win7 发行适配，不认证全部上游迁移、完整插件生态或 Win7 真机。

## 作者与用户流程

作者完成 Client 构建和发行文件检查后，执行既有原生 `pack`。命令现在同时打印
实际 ZIP 的 SHA-256，可与版本化 ZIP、源码、LICENSE 和验证说明一起交付。
打包仍不运行 Node/pnpm/pip、包脚本或 Python 插件代码。没有自动发布至 GitHub。

用户停止目标 profile 后，可以执行：

```text
dsh plugin --profile web add <HTTPS-ZIP-URL> --sha256 <64位归档哈希>
dsh plugin --profile web upgrade <HTTPS-ZIP-URL> --sha256 <64位归档哈希>
dsh plugin --profile web versions <包名>
dsh plugin --profile web rollback <包名> [版本]
```

Portable 入口使用 `dsh.bat` 传入相同参数。URL 可指向公开 GitHub Release 的
直接 ZIP asset，也可指向其他 HTTPS 文件服务；本次未访问或发布真实 GitHub
Release，不提供 GitHub API 搜索、私有仓库认证或目录索引。

HTTPS 来源必须明确提供归档哈希，不能将缺失哈希、错误参数或下载失败转交
pnpm。所下载内容仍必须是符合既有 `dsh.python` / bundle / release 规则的
发行物，不将 npm 安装、JS/TS 模拟装配或单纯下载成功视为 Python Host 可用。
其他已有 npm 命令仍使用既有后端。

## 获取与安装边界

获取器在独立临时目录流式写入 ZIP，验证完整传输与指定 SHA-256，再交给既有
`install` / `upgrade`。包描述、Python 3.8 语法、发行集合、Web/Remote receipt、
保留代次、ProfileLease 和 journal 恢复继续由同一原生 store 负责。
没有第二套注册或激活入口，没有新的生产依赖。

初始 URL 与每次 redirect 都要求 HTTPS；保留系统 TLS 证书验证，拒绝 URL
userinfo 和 fragment，限制重定向次数。只接受完整 200 响应和 identity HTTP
content encoding；归档最大 64 MiB，解包仍受既有 64 MiB / 4096 entries 限制。
无 Content-Length 的响应也按实际流量计数。截断、错误长度、哈希不同、非 ZIP、
TLS 失败与读取超时均失败并清理临时下载。

socket 超时 15 秒，读取步骤前后检查累计 90 秒 deadline。它没有把操作系统
DNS 解析变成可取消任务，也不是整个 urllib 调用的硬实时上限。测试验证实际
TLS 读取 stall 的超时和 deadline 判定，不据此认证任意网络环境的终止时限。

下载失败发生在 profile 初始化前。下载成功后的包验证仍沿用本地安装语义：
新 profile 可以先被初始化，再拒绝无效包；现有已管理版本在候选或提交失败时
保持文件和引用。运行中的 profile 不允许提交安装或替换；取得 ZIP 不绕过锁。
新代码只在正常 Loader 激活时执行，安装不是功能验证或代码沙箱。

## 版本来源

HTTPS 安装记录附带 `acquisition`：

```json
{
  "kind": "https-zip",
  "url": "https://example.invalid/releases/plugin.zip",
  "sha256": "<实际归档的64位SHA-256>",
  "bytes": 1234
}
```

安装器重新核对记录与源 ZIP 的字节数和摘要。URL 仅保留 scheme/authority/path，
不持久化初始下载或 signed redirect 中的 query；不保存临时下载目录。来源 URL
用于诊断，完整字节身份由归档哈希给出，不宣称该记录可重新获得过期 signed URL。
哈希不替代作者身份认证；用户仍需从自己的可信发行渠道取得期望值。

来源随保留的源码代次进入历史、回退和 `versions` JSON。回退使用已验证的本地
快照，断网时无需再下载。代次仍由包版本和发行文件哈希决定，不因下载 URL 或
ZIP 压缩字节变化建立不同的同内容代次。本地版本替换不继承前一远程归档的
来源，回退到 HTTPS 代次则恢复该代次原来的来源记录。

## 实际验证

复用仓库的 localhost 测试证书运行真实 HTTPS server，测试上下文仅信任该
fixture CA，没有关闭验证。canonical CLI 子进程通过 `SSL_CERT_FILE` 信任同一
测试 CA，PATH 只包含测试 Python 目录，不要求系统 Node/pnpm。

新增 36 项测试在 Python 3.8.10 / 当前 Windows 下通过，118.70 秒，退出码 0。
覆盖作者 pack 输出到真实下载安装、HTTPS redirect、工具调用和正式 profile
重启、HTTPS/本地混合升级、往返回退及来源、全新 profile、运行中锁、下载和
候选拒绝、提交失败恢复、临时文件释放与参数不回退 pnpm。

专项日志与 XML 为 `.goose/out/python-plugin-acquisition-native.log` /
`python-plugin-acquisition-native.xml`。较早组合回归有 129 项通过、1 项作者打包
fixture 失败：遗漏了既有 release schema 的 `formatVersion`，补正 fixture 后
该用例在上述 36 项中通过。没有修改 descriptor 合同或登记原版 bug。

最终执行原生 `.venv\Scripts\python.exe -m pytest tests`，启用
`DSH_TEST_CHROMIUM`：**4668 passed、2 skipped、1 warning，655.49 秒，退出码 0**。
JUnit 共 4670 项，failure/error 均为 0；36 项获取测试和五个原版浏览器用例
均执行通过。两个 skip 为 Windows 不适用的 POSIX 路径/权限检查。

全量日志、XML 与 17 个实现/fixture/示例输入快照为
`.goose/out/python-plugin-acquisition-final.log`、`python-plugin-acquisition-final.xml`
和 `python-plugin-acquisition-final-inputs.json`，结束后核对 0 漂移。
实际全量浏览器报告复制到 `python-plugin-acquisition-test_original_browser_*.json`：
三条插件交付旅程分别 17 / 23 / 12 步，Runtime/console/network 错误为空；
两条 native lifecycle/Inspect 旅程分别 17 / 32 步，只记录各自断言要求的唯一
故意 Client activation failure，未将它当成未预期的成功或额外错误。

五个报告均核验 119 个固定前端输入。三条插件旅程的各 21 个实现输入、两条
native 旅程的各 15 个实现输入哈希无漂移；Host stderr 均为空、退出码 0。
这些是开发机辅助证据，未写作全项目 registry acceptance。保留既有 Windows
Proactor transport 析构 warning、pytest-asyncio fixture loop scope 提示和测试
HTTP 连接中止诊断。Python 3.8 compileall、migration check/ready 和 diff whitespace
检查通过，固定 reference 的 tracked 文件未修改。

## 剩余范围

插件仍要求空 Python/npm 依赖声明；依赖闭包、冲突诊断、原生 wheel 的 Win7
认证、多来源目录与 npm/PyPI 原生获取均未由 HTTPS ZIP 完成。用户 preset
引用的事务性清理、完整动态治理、任意 JS Host/Workflow、Inspector/CDP 和最终
Portable 解压验证继续迁移。固定前端没有修改，本次没有发布、推送、安装新的
JS 引擎或重建 Portable；Win7 真机与目标浏览器验证保留用户暂缓决定。
