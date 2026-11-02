# 官方初赛表与本地候选包

更新：2026-10-25，以 [Issue #12](https://github.com/Qcx526/HomeTrace/issues/12) 及 PM 最终冲刺合同为准。主办方 DOCX 已在本地提供；此前“自编技术说明书替代官方主表”的约定已失效。七页说明书、PPT 和演示视频是补充材料。原实验报告和历史媒体保持不变；PR #14 Agent 与 PR #13 YOLOE 实验已合并，P4 媒体须依据已验收能力另建版本，不能直接把历史材料标成最新成果。

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

当前主线为 `4429fcf21797d6af05d189effdd510918315acc4`。真实 LangGraph/LangChain Agent 已合并，具备文字请求、真实模型工具调用、SQLite 历史查询、观察反馈和共享 SearchCore 证据判断；公开 OpenCV 三场景保留 FOUND、未确认和重放保护。YOLOE 固定参数家庭实拍实验已合并归档，结论为 **NO_GO**，没有接入生产 Detector，不能宣称家庭实例识别已升级成功。详见 [Agent 功能及证据](P4_AGENT.md)、[视觉实验结论](P4_VISION_EVALUATION.md) 和 [主线集成证据](evidence/pr-13-integration-20261024/README.md)。导航始终 simulated，无真机运行；当前没有麦克风语音输入。

PR #15 在上述主线的同一合并工作树完成全量回归：**463 passed，0 failed，0 skipped，82.32 秒**，仍待 PM 复核。真实队伍资料仍未填写，P4 PPT、视频及最终 ZIP 尚未完成验收，正式主表及新实名 ZIP 均为 **BLOCKED**。旧 `candidate-HomeTrace.zip` 是历史快照，不能作为最新提交。真实身份齐备后继续使用同一工具，无需重新设计架构。

真实原件运行暴露两处此前简化测试模板未覆盖的缺陷：填表误改段落默认字符样式，以及 XML 序列化丢失图形属性中的换行/制表/回车。现仅修改可编辑文本 run 的样式，并保留属性字符引用；`verify_filled` 严格校验函数未变。真实原件加明确标记 TEST_ONLY 的 1 人及 3 人假资料均通过结构与内容校验；这些文件不是团队正式主表。修复前失败记录及修复后结果见本轮证据。

本轮将真实官方原件与新生成的 230 字 P4 DRAFT 分别以 Word 只读方式导出 PDF，再用 Poppler 渲染；各 3 页，共 6 张均已逐页查看，未复现历史文字/项目符号重叠。原件和非编辑部分未修改，因此不能称作版式问题已修复。Poppler 仍报告 Symbol/ArialUnicode 字体警告；正式实名版本须由负责人在 Word 全页复核，保留 **OWNER_REVIEW**，本轮草稿检查不代表最终主表验收。

本轮优先完成 PR #15，不在材料分支新增 DataForge、语音、Agent 架构或视觉模型。DataForge 是后续独立阶段的待实现能力，不能写入当前成果或宣称已提高真实家庭识别率。

官方初赛最多提交五次，按最后一次评分。团队当前计划截止为 2026-11-04，具体小时、时区、附件、命名和大小仍由负责人在本届提交页面核验。规则说明 PDF 仅供参赛阅读，不压入作品包。上传由队长完成，真实回执才证明提交成功。

官方填表工具独立分支的历史运行和回归见 [Issue #12 证据索引](evidence/issue-12/README.md)。该索引保持冻结，本轮主线集成结果见 [PR #15 集成证据](evidence/pr-15-integration-20261025/README.md)，不覆盖旧报告。

## 主线集成验收

源码必须包含 `config.yaml` 与空 `.env.example`，排除 `.env`。这些白名单、配置秘密字段和本机 Key 泄漏检查随 [PR #14](https://github.com/Qcx526/HomeTrace/pull/14) 已进入主线；PR #15 集成必须与官方 DOCX 原件 SHA、表结构、身份一致性、DRAFT 拒绝及规则 PDF 排除同时有效。必须在同一合并工作树运行完整测试并实际打开验证源码 ZIP，不能仅分别验证两个分支。

318 项与 401 项分别是 Issue #12、Issue #11 独立分支的历史成绩；主线 424 项对应上方 PR #13 集成证据，均不代替本轮 PR #15 集成日志。本轮实际 463 项包含新增的 5 项官方表与 Agent 配置/动态 Key 联合测试、3 项段落样式保留测试和 2 项 XML 属性空白保留测试，未修改旧断言，不以理论合计 453 项代替执行。真实 DRAFT 的正式填表检查及包预检均实际返回 exit 2 / BLOCKED，身份保护未被绕过。仍须等待 PM 复核，不自行合并或宣称已提交比赛。
