# Issue #11 实际验收记录

2026-10-24，Windows / Python3.11.4。完整方法、命令、预算调整、功能边界见 [P4 Agent](../../P4_AGENT.md)。公开结果只来自固定的非敏感测试请求；私人原图、团队信息、Key、数据库和任意用户请求不在本目录。

- [gate0.json](gate0.json)：真实 API 的 4 请求 / 2 SQLite 工具往返，非模拟模型。
- [runs.json](runs.json)：8 个真实 CLI 尝试的索引；每轮 JSON 保留实际模型与工具轨迹、参数、反馈、tokens、耗时与最终解释。包括两轮预算失败，不删除不利结果。
- [fair-comparison.json](fair-comparison.json)：相同公开照片与独立登记数据库；历史 C，Agent 实际 C，固定顺序 A→B→C；只对该受控案例成立。
- [browser.json](browser.json)、[browser-trace.json](browser-trace.json)：Microsoft Edge155 实际点击触发真实 API，17 次轮询（16 次运行中），7模型/6工具/9743已报告tokens；512×384图像与canvas一致、实际框非空、无JS错误、手机无横向溢出。截图为 [运行中](live-tools.png)、[FOUND](found.png)、[手机](mobile.png)。完整连续webm留在本地 artifacts/issue-11/browser-01。
- [classic-browser.json](classic-browser.json)：原公开三场景实际浏览器执行与逐事件检查全部通过，结果仍 FOUND/B、SUSPECTED/null、UNKNOWN/null。
- [pytest.txt](pytest.txt)：**401 passed, 1 warning in 67.66s**，原289+新增112，0失败0跳过。唯一warning来自LangGraph导入的序列化器未来默认值通知；不使用 checkpoint/pickle 接口。测试使用stub只验证软件边界，不作为模型能力证据。
- [baseline-preservation.json](baseline-preservation.json)：原测试及冻结证据文件未改。
- [agent-freeze.txt](agent-freeze.txt)：实际可选环境完整版本，pip check无冲突。editable仓库路径行去除，以本PR源码为准。原基础环境不用安装Agent依赖。

实际测试命令：

```powershell
.\artifacts\issue-11\agent-env\Scripts\python.exe -X utf8 -m pytest -q --junitxml artifacts/issue-11/pytest-final.xml
node tools/validate_agent_browser.cjs http://127.0.0.1:8766 artifacts/issue-11/browser-01
node tools/validate_p2_browser.cjs http://127.0.0.1:8766 artifacts/issue-11/classic-browser-01
```

浏览器脚本需要开发工具 Playwright + 本机 Edge，只运行实际网页，不注入响应或修改检测结果。先按文档启动 `hometrace demo --agent`。截图只含 OpenCV 公共样例，来源与许可继承 examples/recorded_images。原图照片时间未知，A/B/C与时间是demo_sequence编排；所有导航为模拟。

供应商未提供 request_id 时为null，response_id是LangChain运行标识。tokens为供应商成功响应的usage，不含无法获取用量的失败请求或潜在SDK重试。完整输入快照、SQLite、原始session在本地ignored artifacts/issue-11；原有历史报告和候选ZIP未覆盖。
