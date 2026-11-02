# Issue 44 实际交付验收记录

执行日期：2026-11-01 至 11-02；分支 `feature/44-delivery-closeout`，基于 `16445f7`，集成 PR #15 `775d601` 官方主表工具。原 PR 不修改、不合并。私人原图/配置/数据库/原始模型回复和媒体仅在本机忽略目录，公开截图使用合成软件素材。

## 最终结果

| 实际执行 | 结果 |
| --- | --- |
| 联合工作树全量 | 1112 passed，182.04秒，1项既有弃用提示；见 `pytest-final.txt` |
| 前端回归 | 22 passed；见 `node-tests-01.txt` |
| 干净Windows虚拟环境 + 安装wheel 全量 | 1112 passed，173.88秒；见 `clean-install-pytest.txt` |
| 新安装依赖和运行 | pip check通过，9项HTTP/资源/空工作区/wheel内容检查通过 |
| 真实文本LLM HTTP完整验收 | 40项运行检查，6个请求，16次调用，20933tokens，零图片外发 |
| 真实浏览器 | 8项检查，3个请求，5次调用，6207tokens，零图片外发，无pageerror |
| 官方主表 | 3页真实官方原表派生草稿，描述238字；身份按负责人要求留空；正式检查BLOCKED |
| 技术DOCX/PPT/MP4 | 5页DOCX、10页PPT已逐页渲染检查，89.92秒MP4完整解码及关键帧检查 |

HTTP和浏览器均是真实LLM、本地ORB、SQLite/HTTP执行；照片是固定哈希AI合成软件样例，导航模拟，主人动作由脚本发出。实际历史优先顺序、拒绝后继续、重启记忆和重放UNKNOWN分别留档，不构成家庭实拍识别通过。详细核对点在 `workflow.json`。

新环境从限定的源码快照构建并安装wheel，导入路径为新venv的site-packages；不是复用开发editable路径。新环境依赖解析版本与旧环境不同，全量仍实际通过，环境版本见 `clean-install-freeze.txt`。未重装Windows、未宣称跨操作系统测试。

## 实际命令

```powershell
python -m pytest -q --junitxml=artifacts/issue-44/pytest-final.xml
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
python tools/accept_photo_workflow.py --custom-locations --output-dir artifacts/issue-44/custom-place-acceptance-01
# 隔离Playwright 1.56.1 + Edge；只有固定合成输入及真实文本模型
node tools/record_delivery_demo.cjs artifacts/issue-44/browser-01 <project-python>
python tools/create_delivery_video.py --recording-dir artifacts/issue-44/browser-01 --output <ignored-new-mp4>
python tools/fill_official_submission.py --config local_data/submission/20261101/config.json --draft
python tools/fill_official_submission.py --config local_data/submission/20261101/config.json --check
```

正式主表check的exit2是身份缺失的正确阻断，不计作已填报成功。审阅ZIP只用于负责人填写/审查，不将test_only或team_authored用于绕过官方主表规则；正式builder仍BLOCKED。

## 中间问题与处理

- 最初1109项全量通过后，独立review发现审阅ZIP可覆盖旧审计，已修复并补3项保护；最终1112项在工作树和新安装均重新全量执行，未叠加计数。
- 源码导出曾因测试夹具的完整私钥头字符串被保护拦截，首轮安装因此没有合法输入。保留 `clean-install-01` 失败；测试使用运行时组合后在 `clean-install-02` 重建成功，未降低Key保护。
- canonical DOCX渲染因缺soffice.exe失败，改用Word只读PDF导出与bundled Poppler。技术稿初版标题边线/状态单元格换行修正后重新检查全部5页。官方原件和草稿各3页，原件字节不变；字体提示如实记录在 `materials.json`。
- PPT三次中间构建的布局策略/回读参数问题保留，最终第四次构建完成结构/字体/回读和10页视觉检查；不宣称已操作原生PowerPoint。

## 代码及证据范围

`submission-integration-provenance.json` 记录PR15原样引入文件；原collect_source/Key检测等7个安全函数保持原语义。只扩充提交材料工具、验收runner和材料生产工具，不改ImageMatcher、SearchCore、Agent、SQLite schema或阈值。真实家庭照片旧结论不变。

图片、日志与Token来源清楚；所有测试用假身份均标为TEST_ONLY。本轮官方草稿包含待填写字段，不能上传。正式身份、PM审查、提交平台限制与上传回执仍未完成。
