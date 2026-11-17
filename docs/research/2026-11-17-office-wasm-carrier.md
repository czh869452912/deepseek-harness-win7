# Office WASM 载体可行性

固定目标 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。C9-BL 的实际观察见[回执](../../migration/candidates/rc022/office-wasm-carrier-checks.json)。原 native EXE 的普通导入仍不兼容 Windows 7；本次没有修改 EXE、补系统 API 或调用系统 Office。

原版 `@deepseek-ai/libreoffice-kit-wasm@0.2.3` 的未修改 loader 可在浏览器 Worker 使用。在 Chromium 108.0.5359.0、同源 COOP/COEP 页面和共享内存环境中，127846009 字节原始 WASM 实际编译、初始化及 pthread 启动成功。原样 DOCX 夹具经过 LibreOffice 转成 PDF/TXT，PDF 再经过同一引擎内的 PDFium 输出 PNG。文字检查和图片目视检查通过。成功回执在文档销毁、Office 销毁、pthread 终止后发送，浏览器和自有 HTTP 服务随后关闭。

复现命令：

```powershell
<source-node> scripts/rc022_office_wasm_probe.mjs --source <clean-pinned-source> --browser <chromium-108.0.5359.0-exe> --output .goose/out/<fresh-owned-run>
```

探针使用本机 Arial 的原始文件，不复制字体进发布物；可用 `--font` 显式选择受控字体。当前所有字体请求均返回这一个字体，因此该结果只证明实际引擎路径可运行，不能用来认定字体匹配、中文回退或缺失字体报告已对齐。输入与四个引擎资产有大小/SHA-256；引擎资产按原包 prebuild manifest 校验。

生产路径还需完成：Python 3.8 的浏览器通信和拥有者生命周期；原版字体选择、格式及渲染逻辑；安全的有界输入/输出和取消；默认 `officeKitEngine` 服务；带许可证和固定哈希的 Portable 运行时。后续应直接复用已有大资产并保留本次实际 PDF/TXT/PNG，避免反复复制 150 MB 引擎。Node/Playwright 仅用于本次实验，尚不是零依赖发布实现。实际 Windows 7、完整 Office 和同包发行验收保持待完成。
