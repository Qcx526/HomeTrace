# Issue #3 实际验证证据

2026-10-22，Windows 10 / Python 3.11.4。此目录保存实际执行结果，不包含模拟成真机的记录。

- `setup/`：0.3.0 wheel 构建、新虚拟环境非 editable 安装、导入位置、wheel 哈希和验证命令。
- `pytest.txt` / `pytest.xml`：148 passed，0 skipped，包含原有 54 项 P0 与 68 项 P1。`validation.json` 保存源码 SHA256、环境和各场景实际 run_id。
- 验证后仅移除了 `demo_server.py` 文件末尾多余空行，Python AST 比对完全相同；验证时与提交时摘要均记录在 `post_validation_formatting`，不将格式变化冒充重新执行的测试。
- `moved/`、`missing/`、`replay/`：干净安装验证时，两种策略各自的搜索报告、JSONL、stdout、命令；登记历史和重放种子搜索保存一侧副本。实际运行两侧均独立登记，且在重放前均执行 memory_first 种子搜索。完整 SQLite 和输入副本留在本地忽略的 `artifacts/p2-validation/runs/<run_id>/`。
- `comparison.json`：同候选、同输入字节摘要、实际尝试/到达/解码次数与观察调用次数。没有模拟移动耗时。所有样例计数打平，不代表一般场景性能结论。
- `browser/`：另一次真实浏览器连续运行的截图、下载报告、逐步自动检查和录屏。与干净安装验证的 run_id 不同，各自报告匹配各自运行，不能将两次耗时混为同一数据。

浏览器实测 Edge 155.0.4283.45，1440×1080；另检查 390×844 窗口。`browser-checks.json` 保存每一核心事件的 DOM 计数和结果。B 的 SVG 框坐标与报告 bbox 比对；重放 B/A 不出现当前匹配框、不增加 observed；完整结果直到 complete 事件才显示，报告下载与 API 报告逐字段相同，无页面 JS 异常。

[连续 MP4](browser/demo-three-scenarios.mp4) 是自动操作实际浏览器的 50.24 秒录屏，无配音，不是效果动画；只从原始 WebM 转码，未修改事件顺序。录屏覆盖浏览器页面，未包含终端启动窗口，不等于最终比赛解说视频。原始 WebM 在本地 `artifacts/p2-browser-check-2/` 保留；[元数据](browser/video-metadata.json) 保存原始及 MP4 哈希、转码命令、完整解码通过结果。视频中的回放等待仅为可读性，不是计算或移动耗时。

素材来自 P1 已授权公开的 OpenCV 原图，[来源与许可](../../../examples/recorded_images/README.md) 不变。照片是真的，地点和时间为 Demo 编排，导航为模拟。家庭自产照片、端侧设备和真实机器人仍未测试。

复跑入口：`python tools/validate_p2.py --output-dir artifacts/new-p2-validation`；浏览器复跑见 [P2 说明](../../P2_DEMO.md)。所有输出目录应使用新路径，避免覆盖旧证据；正式提交 ZIP 及个人资料不属于本目录。
