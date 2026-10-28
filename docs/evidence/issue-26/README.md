# Issue #26 实际验证证据

2026-10-28；本轮使用 AI 生成的虚构蓝色钥匙图片，不是团队家庭实拍或独立测试。没有训练网络或运行真实机器人。

- [一次全量回归](pytest.txt)：738 passed，0 failed，0 skipped，1 条既有 LangGraph 警告，111.47 秒。
- [实际 HTTP 结果](http-results.json)：3 个 CLI 进程、53 次请求；逐场景匹配与 core 报告、进程重启后的主人确认、历史重排序与重放、拒绝后继续。无图像字节、私人照片或个人信息。
- [审计与文件哈希](audit.json)：原 33 个测试文件、292 个 docs 文件未改写；新源码、wheel SHA256、隐私检查及浏览器验收范围。
- [wheel 构建](wheel-build.txt)：0.4.1 本分支 wheel 成功构建；不是新增版本发布，未声称另一次全新环境完整安装。
- [浏览器候选快照](browser/01-candidate-dom.txt)、[服务重启恢复](browser/03-process-restart-dom.txt)、[主人确认](browser/04-owner-confirmed-dom.txt)、[旧图保护](browser/05-replay-dom.txt)、[拒绝后继续](browser/07-reject-dom.txt)、[同名选择](browser/08-ambiguity-dom.txt)。均来自真实 UI，未改写页面或注入检测结果。

候选、主人确认、旧图和窄屏截图实际保存于本地 `artifacts/issue-26/browser/02-reloaded-desktop.jpg`、`04-owner-confirmed.jpg`、`05-replay.jpg`、`06-mobile.jpg`。按合同，含生成图的截图与原图均留在 Git ignored 目录，公开 PR 只提供 DOM 文本和 JSON。截图为浏览器 API 原样导出，部分文字较模糊；全页截图第一次导出失败，随后使用实际可见区域截图，没有生成假截图。

## 运行命令

```powershell
$testPy = 'artifacts/issue-11/agent-env/Scripts/python.exe'
& $testPy -X utf8 -m pytest -q --junitxml=artifacts/issue-26/pytest-reproduce.xml
& $testPy -X utf8 tools/validate_photo_flow.py --images local_data/ai_html_test_20261027 --output-dir artifacts/issue-26/http-reproduce
& $testPy -X utf8 tools/prepare_photo_flow_demo.py --workspace artifacts/issue-26/another-new-demo
& $testPy -m hometrace demo --port 8769 --household-dir artifacts/issue-26/another-new-demo
& 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' --check src/hometrace/web/home-flow.js
& $testPy -m pip wheel --no-deps . --wheel-dir artifacts/issue-26/wheel-reproduce
git diff --check
```

复现输出目录需不存在。原始 HTTP 为 `http-02/`；`http-01/` 因验证脚本错误假设无历史地点顺序而失败，完整记录保留在本地。改为明确创建“较早书房、最近玄关”两条虚构主人陈述后重新运行，未修改搜索排序和视觉参数。浏览器先因本地连接禁用而受阻，负责人启用连接后已完成补验收。

## 验收边界

软件闭环可交付审查。人工核对返回 `USER_CONFIRMED`，视觉证据保持 SUSPECTED/UNKNOWN，未宣称实例 FOUND。真实家庭识别、自由 LLM 多轮、自动相机扫描、真实机器人运行与正式提交包仍未完成。原照片/Agent Demo 保留。PR 依赖 #25，未自行合并。
