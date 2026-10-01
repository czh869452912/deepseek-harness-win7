# 已展开的纯 Python 依赖闭包与 profile 生命周期

日期：2026-10-01。产品起点 `dfc0393f`，固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。本批次推进作者预先展开、逐文件
锁定的纯 Python 库交付，保持原生 Python 3.8.10 和统一 profile/Loader。
没有新增生产依赖、pip/Node 调用或 JS 引擎；不认证完整依赖生态、全项目 parity 或 Win7。

## 发行合同

实验 API 1 的 `dsh.python.dependencies` 可以是精确 `name==version` 根依赖数组。
非空数组必须配套 `dsh.pythonDependencies`，例如：

```json
{
  "formatVersion": 1,
  "python": [3, 8, 10],
  "abi": "none",
  "platform": "any",
  "packages": [{
    "name": "example-library",
    "version": "1.0.0",
    "sourceRoot": "vendor/example-library",
    "imports": ["example_library"],
    "requires": [],
    "files": {"example_library/__init__.py": "<64位SHA-256>", "LICENSE": "<64位SHA-256>"},
    "origin": "<作者记录的构建来源>"
  }]
}
```

作者在现代构建机准备完整文件集合，记录全部直接和传递依赖的精确版本、导入根、
依赖边、文件哈希和构建来源。名称归一化；不在用户电脑解析版本范围、extras、
markers 或下载库。`origin` 是作者记录，不是来源认证；锁不推断隐藏的动态 import，
`any` 也不是 Win7 证据。作者仍须验证实际 Python/OS API 与授权。

安装和 pack 检查根依赖与全部传递边，不接受额外不可达库、漏项、版本不符或
重叠 sourceRoot。导入根须对应普通模块或含 `__init__.py` 的包。文件集合完全匹配
哈希，Python 源码检查语法；额外顶层 Python 代码、DLL/PYD/SO/EXE、wheel、裸字节码、
`.pth` hook 被拒绝。不执行安装脚本或导入库。库目录与插件 sourceRoot 分开。

pack 的显式发行集合必须包含锁定的全部库文件及资源。目录、ZIP、HTTPS ZIP 继续
进入同一 store；库文件纳入插件安装记录、代次、journal、升级和离线回退。

## 冲突与导入

安装、升级、回退合并目标 profile 的已管理 Python 包闭包。同名库的版本、导入根、
传递边或内容不同拒绝提交；不同分发不能占用同一导入根。宿主可解析的模块、标准库、
核心 `dsh`/应用身份和私有 namespace 不允许覆盖，即便声明相同版本也不复用宿主库。

正式 `run_profile` 在 Loader 导入前建立租约，使用 CPython 普通 import、相对导入
和子模块机制。绕过 canonical profile 的依赖包导入明确拒绝。无依赖包保持既有
私有命名空间路径。没有第二套插件激活入口。

同进程只共享完全一致的库锁，同版本不同内容也不兼容。不兼容的另一个 profile
拒绝启动，原 profile 保留；原持有者停止后可启动不同版本。兼容持有者共享模块
状态，这不是每插件任意版本隔离。

库先复制到逐文件重新校验的进程临时目录，再注册受租约管理的 `sys.path`。
因此一个 profile 停止或卸载其安装目录后，另一持有者仍能 lazy import 和读资源。
最后持有者关闭后撤销路径、模块、导入器缓存和临时目录；依赖包的私有插件 namespace
也按所有者退役。整个 root fiber 和异步 cleanup 结算后才释放租约。
启动失败、复制时源码改变会撤销已建立的状态。

变更依赖集合/版本须停止 profile。它不是恶意 Python 沙箱，也不将环境自动传给
终端或 Python 子进程。进程崩溃后临时目录可能留在系统 temp，需要常规系统清理；
不会作为下次启动的依赖来源。

## Windows 源码偏差修正

迁移版原来大小写敏感地筛选 `.py`，Windows 可以加载 `.PY`，会漏掉语法检查、
import identity 的内容摘要、必需发行文件和库导入根盘点。现按不区分后缀大小写
处理。实测 `.PY` 内容变化创建新 namespace，错误语法安装前拒绝。关闭时也撤销
Windows case-relaxed import 的模块别名。这是迁移版偏差，不登记为原版 bug；
原版不包含本次 Python 描述路径，固定前端和 reference 均未修改。

## 实际验证

最终新增 **30 项通过，10.80 秒，退出码 0**，原生 Python 3.8.10 / 当前 Windows。
实际目录和作者 pack ZIP、正式 Tools 调用、两层传递依赖、关树/重启/升级/回退、
模块状态和 LICENSE 资源均验证。两个 live profile 共享、原安装卸载后的 lazy import、
不兼容启动的恢复、三种事务冲突、候选拒绝、异步 cleanup、导入失败、复制中源码
变化也覆盖。Windows `PYTHONCASEOK` 在真正设置启动环境的 Python 3.8 子进程中运行。

日志/XML：`.goose/out/python-dependencies-native-final.log` / `python-dependencies-native.xml`。
较早组合回归 154 项通过（166.97 秒），之后补充别名、字节码和大写源码检查，由最终
专项与全量验证。最早 fixture 带入 `__pycache__` 导致发行集合拒绝，已修正 fixture，
未放宽发行规则。

最终全量 `.venv\Scripts\python.exe -m pytest tests`，启用 `DSH_TEST_CHROMIUM`：
**4698 passed、2 skipped、1 warning，655.58 秒，退出码 0**。JUnit 共 4700 项，
failure/error 均为 0；新增 30 项依赖用例和五个原版浏览器用例均实际执行。
两个 skip 为 Windows 不适用的 POSIX 路径/权限检查。

日志、XML 与 14 个实现/fixture/示例输入快照分别为
`.goose/out/python-dependencies-final.log`、`python-dependencies-final.xml` 和
`python-dependencies-final-inputs.json`，结束后核对 0 漂移。五个全量浏览器报告
复制到 `python-dependencies-test_original_browser_*.json`：三条插件旅程 17 / 23 / 12
步，Runtime/console/network 错误为空；native lifecycle/Inspect 分别 17 / 32 步，
只记录各自断言预期的唯一故意 Client activation failure。

五个报告均核验 119 个固定前端输入；三条插件旅程各 21 个、两条 native 旅程各
15 个实现输入哈希无漂移。Host stderr 为空、退出码 0。保留既有 Windows Proactor
transport 析构 warning、pytest-asyncio fixture loop scope 提示与测试 HTTP 连接中止
诊断。compileall、diff whitespace、migration check/ready 通过，固定 reference
tracked 文件未修改。这些本机辅助证据不替代全项目 registry 或发行验收。

## 剩余范围

wheel/PEP 427、原生依赖/Win7、PEP 440 求解、宿主兼容库复用、namespace package、
更多 registry 获取仍未完成。预展开锁不替代这些能力。用户 preset 引用清理、
完整动态治理、任意 JS Host/Workflow、Inspector/CDP 和最新 Portable 解压验收继续
迁移。Win7 真机及目标浏览器验收保留用户暂缓决定；没有发布、推送或重建 Portable。
