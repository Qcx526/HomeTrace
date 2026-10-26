# Vision R1 脱敏证据

这是 2026-10-26 多参考原型实验，不覆盖早期 R1 ROI 阶段或 Vision R0 的任何报告。

- `comparison.public.json`：当前 `81b14bd` 代码的真实20场景、40方法行及4张登记质量，原图哈希/路径/框仅保存在 ignored 目录。
- `baseline-comparison.public.json`：与 R0 ORB_ROI 的20条非时间结果逐项核对。
- `run.log`：实际 runner 输出，包含所有多参考未执行原因。
- `regression.public.json`、`pytest.log`：同一代码的联合全量549测试；独立环境的76项运行另见 `pytest-cv414.log`，不额外相加。
- `source-audit.public.json`：324个基线文件保持及 PR #15 工作树 HEAD。
- `privacy-audit.public.json`：公开文件对已知私有图片哈希、原始命名和本地环境秘密值的扫描。

全部真实照片已经用于历史开发；独立测试为0。多参考20项未满足登记前提，不能把未执行负例当成通过。公开 accepted_geometry 只表示原 matcher 的几何信号，不能视为物理实例已确认。原始数值和失败均保留；公开 scene/object/reference ID 是匿名别名，本地映射在 `binding.private.json`。
