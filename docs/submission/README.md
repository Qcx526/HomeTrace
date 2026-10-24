# HomeTrace 初赛材料

**2026-10-23 R1 版本说明：** 本目录 DOCX/PPTX/MP4 是 PR #8 已审查的历史材料，记录此前 75 项家庭评价，不代表新增数据已经成功。新增四组照片的正式背景误报、登记 ROI 对照与未确认结论见 [R1 实验报告](../REGISTRATION_ROI_EVALUATION.md) 和 [最新回归](../evidence/issue-4-r1/README.md)。旧 candidate 不包含 R1 源码。最终上传前需依据 PM 审查后的版本同步材料与测试报告，重新打包；不要把背景误报计为家庭成功例。

本目录保留团队自编的作品设计与技术说明书、10 页技术展示 PPT、运行测试报告、开源与原创性说明、中文视频解说稿及提交清单。按当前 Issue #12 合同，这份历史 DOCX 仅是补充材料；必须另在本地填写主办方官方主表，见 [官方材料接口](../OFFICIAL_SUBMISSION.md)。公开材料只包含 OpenCV 公开样例的软件截图与家庭实验数值，不包含团队家庭原图或个人身份资料。

DOCX 中“待团队填写”是正式上传前需要在本地补齐的团队身份字段。材料可以阅读和审查，但这些字段尚未完成时不能宣称最终 ZIP 已可提交。最终视频和团队配置由打包输入目录传入，材料完整性、人工审查和 ZIP 核验以打包报告为准。

## 内容与证据

- `HomeTrace_作品设计与技术说明书.docx`：7 页，摘要、架构与创新、公开正例、重放保护、家庭适用性、运行测试、开源与边界。
- `HomeTrace_技术展示.pptx`：10 页，可编辑正文和表格，截图保留来源，相关证据索引写入逐页备注。
- `RUN_TEST_REPORT.md`：公开基线与本轮家庭实测分开记录；最新全量回归结果与 PR 日志对应。
- `OPEN_SOURCE_AND_ORIGINALITY.md`：成熟算法复用与项目原创系统适配分开说明。
- `VIDEO_SCRIPT.md`：实际录屏的中文解说参考，不是已执行的测试日志。
- `HomeTrace_演示视频.mp4`：72.28 秒实际软件录屏，中文字幕，无音轨；编码与解码检查见同名 `.metadata.json`。
- `MATERIALS_CHECKLIST.md`：材料输入与最终人工核对门槛。

## 重建材料

DOCX 使用 Python 的离线材料依赖 `python-docx`，与 HomeTrace 运行依赖分离：

```powershell
python tools/create_submission_materials.py
```

可用 `--test-count <实际通过数> --test-log <仓库相对日志路径>` 在文档中记录本轮回归；必须先有真实日志。文档默认不会把 P2 的 148 项冒充为 P3 结果。

PPT 使用 Codex bundled `@oai/artifact-tool`。通过 `HOMETRACE_RUNTIME` 或 `HOMETRACE_ARTIFACT_MODULES` 指定已有 runtime，`HOMETRACE_PRESENTATION_SKILL` 指定 Presentations 技能目录，运行：

```powershell
node tools/create_submission_materials.mjs
```

输出位于 `artifacts/p3-materials/<revision>/output/`；`HOMETRACE_MATERIAL_REVISION` 指定新版本目录，工具拒绝覆盖已校验的 PPTX。可用 `HOMETRACE_TEST_COUNT` 与 `HOMETRACE_TEST_LOG` 写入真实本轮回归结果。文本和数据表可直接在 PowerPoint 编辑，不需要 authoring runtime 才能查看。

这些 authoring 依赖只用于复现材料，不是运行寻物 Demo 的要求。修改材料后应重新检查全页内容、布局与证据一致性。

## 本机版式验证方式

PPT 通过包结构、字体、页面几何、原生表格与 Artifact Tool 回导检查，全部 10 页渲染 PNG 并逐页检查。没有据此宣称已在 PowerPoint 原生执行。

DOCX 按 documents 技能先尝试 canonical `render_docx.py`，实际报错为 `LibreOffice soffice.exe was not found on PATH`。当前 Windows bundle 不含 LibreOffice，因此使用已安装的 Microsoft Word 后台 COM 打开 DOCX 并导出 PDF，再用 bundled Poppler 生成 PNG 检查全部 7 页。没有调用系统 LibreOffice。临时渲染图、PDF 和校验收据保留在忽略的 `artifacts/p3-materials/`，正式交付只取核验后的 DOCX/PPTX 与指定报告。
