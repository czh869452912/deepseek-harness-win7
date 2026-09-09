# P1-R 基线快照

- 日期：2026-09-09
- HEAD：`60ea814561800f04e54692e629b5cc4e093c8b96`
- 工作区：clean（git status 无输出）
- 全量测试：`1027 passed, 5 warnings`（`.venv\Scripts\python.exe -m pytest tests -q --tb=no`）
- 1:1 测试文件：`tests/1to1/cordis/` 18 个 + `tests/1to1/boot/` 8 个
- 产品代码零改动红线：本目录之外只允许 `%TEMP%\opencode\p1r-probes\` 临时探针
