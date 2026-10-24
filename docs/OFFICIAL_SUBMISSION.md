# 官方初赛表与本地候选包

更新：2026-10-24，以 [Issue #12](https://github.com/Qcx526/HomeTrace/issues/12) 为准。主办方 DOCX 已在本地提供；此前“自编技术说明书替代官方主表”的约定已失效。七页说明书、PPT 和演示视频是补充材料。原实验报告和历史媒体保持不变，P4 内容只在对应 PR 经 PM 审核合并后同步更新。

## 本地输入

复制 `examples/submission_config.example.json` 到 Git ignored `local_data/submission/config-issue12.json`。不要覆盖旧配置和旧候选 ZIP。填写以下接口：

- `document_source=official_template`；`materials.official_template` 指向主办方原 DOCX，`official_template_sha256` 为本地校验值，`official_source` 留存来源说明。
- `materials.application` 为不同路径的新填写稿，不能指向原件。`official_fields` 包含与平台一致的队伍名称、课题名称、不超过 300 字的描述、一位队长及最多两位队员。成员顺序的第一位为队长，八项字段都需真实填写。
- `identity_confirmed` 和 `official_fields.identity_confirmed` 在实际核对平台后设为 `true`；`team` 中的姓名、队名和电话须与主表字段一致。工具只校验一致性，不认证身份真伪。
- `materials.technical_supplement` 可选，指向团队自编说明书。原始官方模板与比赛规则说明 PDF 均不进入 ZIP。

所有相对路径以配置文件目录为根。配置、原件和输出必须被 Git 忽略；不得公开实名 DOCX、家庭照片、身份配置、API Key 或候选 ZIP。

## 填写及核验

```powershell
.venv/Scripts/python.exe tools/fill_official_submission.py --config local_data/submission/config-issue12.json
.venv/Scripts/python.exe tools/fill_official_submission.py --config local_data/submission/config-issue12.json --check
.venv/Scripts/python.exe tools/build_submission.py --config local_data/submission/config-issue12.json --check
.venv/Scripts/python.exe tools/build_submission.py --config local_data/submission/config-issue12.json
```

工具验证官方模板的单表八行结构、固定标签和原件 SHA256，仅填写既有单元格。不存在的队员行遵照原表“若无则删除此行”说明移除；其余表格网格、段落布局、固定说明和非正文 OOXML 部件必须保持一致。原件和已有输出均不覆盖。填写稿字段要与本地确认输入逐项一致，占位符、错误电话、错误邮箱、超过 300 字和身份未确认都会拒绝正式填表或打包。

身份尚未提供时，可将输出文件名改为包含 `DRAFT` 的独立路径，运行 `--draft`。该模式只填写课题名称和描述，队名与成员栏明确保留待填写，状态为 `DRAFT_IDENTITY_MISSING`。该文件不能通过正式填表检查，也不能进入有效官方候选包。它用于本地讨论版式与叙述，不作为提交成果。

自动检查通过仍保留 `visual_review=PENDING`、`ready_to_submit=false`、`officially_verified=false`、`uploaded=false`。必须在 Word 中实际查看全部页面，并在最新审核版本构建后解压打开 DOCX/PPTX/MP4。

## 当前交付边界

本轮仅完成材料输入、填表与候选包保护，不把进行中的 Agent 或 YOLOE 实验写成已合并成果。稳定软件基线为 `e5732b4024d90cc190aedb77f98f626b11e982cd`（0.4.1，原有 289 项回归）；公开 OpenCV 三场景支持 FOUND、未确认和重放保护，家庭实拍在该基线尚未可靠确认。导航始终 simulated，无真机运行。

真实队伍资料仍未填写，正式主表及新实名 ZIP 为 **BLOCKED**。旧 `candidate-HomeTrace.zip` 是历史快照，不能作为最新提交。真实身份齐备后继续使用同一工具，无需重新设计架构。

官方初赛最多提交五次，按最后一次评分。团队当前计划截止为 2026-11-04，具体小时、时区、附件、命名和大小仍由负责人在本届提交页面核验。规则说明 PDF 仅供参赛阅读，不压入作品包。上传由队长完成，真实回执才证明提交成功。

本轮实际运行和回归见 [证据索引](evidence/issue-12/README.md)。

## 与 Agent 分支的合并依赖

Issue #12 最新 PM 评论要求源码包含 `config.yaml` 与空 `.env.example`，排除 `.env`。这项白名单、配置秘密字段与本机 Key 泄漏检查已在独立 [PR #14](https://github.com/Qcx526/HomeTrace/pull/14) 实现并测试；本分支不重复复制 Agent 配置。两项 PR 经 PM 审查合并后，必须再做联合回归及实际源码包检查，确认配置与当时 Demo 一致。当前 318 项与 PR #14 的 401 项是各自分支成绩，不是合并版本成绩；未生成声称包含 P4 最终能力的参赛包。
