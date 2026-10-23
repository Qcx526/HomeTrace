# Issue 4 实际验证证据

2026-10-22 至 2026-10-23 在 Windows 10 主机运行。照片评价、浏览器回放、测试夹具和模拟导航分别记录；没有真实机器人运行。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 开发虚拟环境完整回归 | 226 passed in 57.59s，0 skipped | [pytest.txt](pytest.txt) |
| Windows 新建虚拟环境非 editable 0.4.0 wheel | 226 passed in 61.55s；pip check 通过；仓库外 fixture CLI、公开照片 FOUND/B 与 HTTP 资源均通过 | [安装与逐文件摘要](clean-environment/environment-and-wheel-proof.json)、[测试](clean-environment/pytest.txt)、[依赖](clean-environment/dependencies.txt) |
| 打包正常与异常输入 | 41 passed in 19.20s，TEST_ONLY 夹具明确非提交材料 | [日志](submission-tests.txt) |
| 公开实际浏览器 | FOUND/B、SUSPECTED/null、UNKNOWN/null；逐步计数、bbox、报告下载、手机宽度通过 | [逐步检查](browser/browser-checks.json)、各场景 session/download JSON |
| 私有纸巾浏览器 | moved/missing SUSPECTED/null，replay UNKNOWN/null；无确认框，未确认历史，物品身份 tissue-pack；没有录屏或截图私人图像 | [白名单检查结果](private-ui-checks.json) |
| 家庭原始图实测 | 16 个清单条目校验；25 图对 × 3 方法 = 75 评价，无 FOUND；原图 SHA 未变 | [数值汇总](../p3-photos-summary.json)、[分析与命令](../../TEAM_PHOTO_EVALUATION.md) |
| Word 与 PPT | 7 页 DOCX、10 页 PPT 全页视觉检查 | [实际制作与渲染记录](../p3-materials-validation.json) |
| 视频 | 72.28 秒，H.264 1440×1080，中文说明，无音轨，全片解码通过；6 个关键帧人工视检 | [MP4](../../submission/HomeTrace_演示视频.mp4)、[元数据](../../submission/HomeTrace_演示视频.metadata.json) |

完整测试包含未改动的 148 项 P0/P1/P2 和新增 19 项本地案例、18 项照片工具、41 项提交打包测试。新建虚拟环境发生在现有 Windows 主机上，不代表重新安装操作系统。照片实验使用真实团队图像；输入校验单元测试使用合成字节，不计作视觉成功。

公开浏览器记录由 `tools/validate_p2_browser.cjs` 操作真实本地页面生成，服务运行实际 CLI/OpenCV。虽然验证脚本沿用 P2 名称，此目录记录 P3 的界面与数据集选择改动。P3 的后续私图安全边界修补不改变公开事件结果；相关新分支已通过测试和非 editable 安装验证。原始 WebM 留在本地 `artifacts/p3-browser-public/`，其摘要记录于 MP4 元数据。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m hometrace demo --port 8766 --output-dir artifacts/p3-demo-public
node tools/validate_p2_browser.cjs http://127.0.0.1:8766 artifacts/new-public-browser
.\.venv\Scripts\python.exe -m hometrace demo --port 8767 --output-dir artifacts/p3-demo-private --case-config local_data/team_tissue/demo_case.json
node tools/validate_private_demo.cjs http://127.0.0.1:8767 artifacts/new-private-ui-check.json
.\.venv\Scripts\python.exe tools/build_submission.py --config local_data/submission/config.json
```

家庭原图、含图 JSON、SQLite 与临时日志未公开。公开 summary 仅保留白名单数字和状态。材料中使用的截图来自已标明的 P2 公开样例，视频是本轮 P3 实际录制；历史日期和阶段不混用。

候选 ZIP 的实际构建与解压复核另见 [候选包记录](candidate-validation.md)。候选包始终等待身份补齐、PM 审查、平台要求核验和真实上传；没有官方模板不再作为候选包阻塞项。
