# PR #15 最新 main 集成与真实官方表验证

日期：2026-10-25。任务为 [Issue #12](https://github.com/Qcx526/HomeTrace/issues/12)、[Issue #4](https://github.com/Qcx526/HomeTrace/issues/4) 最新 PM 评论及最终冲刺合同 P0。仍使用 `feature/12-official-submission`，不另建材料分支、不合并 PR、不开始 DataForge。

- main 基线：`4429fcf21797d6af05d189effdd510918315acc4`。
- 原 PR #15：`d260b68c859d9f6b74be69db270094142ba6767b`。
- 集成提交：`ae028dfb7b880cc3921478c7dfb8317b95d0afbc`。
- 最终被测源码与实际 ZIP 源码：`0800afac09b0025c62dcc014feb3780444a9a345`。其后仅新增本证据目录，不改变该源码快照。

## A. 实际问题与改动

将既有 PR #15 合入最新 main，保留真实 Agent、YOLOE **NO_GO** 归档与全部已有测试。README 和源码文档白名单冲突同时保留两边功能。`config.yaml`、空 `.env.example` 导出与动态 Key 扫描不变；官方表原件 SHA、表结构、身份绑定、草稿拒绝、补充文档分离及规则 PDF 排除继续同时生效。

真实官方原件实际填表时发现此前简化 fixture 未覆盖的两个缺陷，先复现失败再修复：

1. `_fill_cell` 修改了 `pPr/rPr` 段落默认字符样式，导致严格保真比较拒绝。现在只修改可编辑文本 run 的占位样式，显式设置非斜体，保留段落默认值。
2. `minidom` 将图形属性中的字符引用写为字面换行，重新解析后变成空格。序列化时保留 CR/LF/TAB 字符引用。正式填写与草稿共用该处理。

`verify_filled` 本体未修改，没有忽略差异或放宽验证。该填表器针对已提供的官方模板，不宣称是通用任意 DOCX 编辑器。

## B. 具体产物

| 产物 | 实际内容及范围 |
| --- | --- |
| 代码 | `official_submission.py` 两处修复；既有填表与打包入口保留 |
| 新测试 | 官方表/Agent/Key 联合测试 5 项，段落样式 3 项，属性空白 2 项 |
| 文档 | 官方填报、交付计划、准备表、打包说明及历史媒体边界同步 |
| [回归日志](pytest.txt)、[统计](regression.json) | 同一集成工作树最终 463 项真实执行 |
| [源码保护检查](preservation.json) | main 的 241 个既有源文件、测试、配置及冻结证据逐文件 Git blob 相同；另 4 个原 PR #15 测试/证据文件相同；白名单和 Key 收集函数 AST 不变 |
| [真实原件失败](before-fix.json)、[修复后结果](after-fix-real-template.json) | 真实官方原件配 TEST_ONLY 假身份的 1 人、3 人校验；不是团队填写成果 |
| [真实草稿](official-draft.json)、[渲染检查](render-validation.json) | 230 字 P4 草稿，原件和草稿各 3 页；私人 DOCX/PDF/PNG 仅留本地 |
| [测试 ZIP](test-only-archive.json)、[完整条目清单](test-only-archive-manifest.json) | 实际集成源码加假材料，108 个源码文件、118 个条目、648078 字节；只存本地 |

本轮没有新增网页、家庭图片实验或媒体演示。旧报告及媒体未覆盖。

## C–D. 数据、标注及泄漏

本轮处理家庭原图 **0** 张、增强 **0** 张、合成场景 **0** 张；未改变已有家庭数据集、人工标签或划分。输入为一份真实官方 DOCX、缺身份的本地配置、合成自动化测试材料及最新源码。不存在将标签输入检测器或用合成样本计算家庭识别率的行为。

私有原件、实名信息、渲染图、ZIP、数据库、模型权重和真实 Key 均未提交。真实配置 Key 仅在内存中用于实际源码与 ZIP 逐文件精确扫描，不打印值。联合测试另以假 Key 验证 `.env`/进程环境两种泄漏源及配置秘密字段均导致 BLOCKED。公开证据仅为脱敏文本和摘要；[最终公开文件检查](public-safety.json)记录扫描范围。

## E. 实际测试与产物验证

最终 **463 passed，0 failed，0 errors，0 skipped，82.32 秒**。有一条 LangChain 未来默认值弃用警告。新增 10 项测试，原有断言和冻结报告保持不变；这是实际日志，不是独立分支数量相加。中间的 458 项和 461 项通过均发生在真实原件缺陷尚未全部解决时，不能代替最终结果。

真实原件 SHA256 为 `44da6ca1ab0f3ad62c2588431e3a3c705b96e6a2638666ae826a2e37d29d69ec`。原件保持不变，八行原表和非编辑内容/其他 OOXML 部件一致；实际 TEST_ONLY 的 1 人及 3 人填写通过严格结构与内容校验。真实缺身份草稿正式检查和包预检均实际返回 **exit 2 / BLOCKED**，见 [填表输出](form-check-fixed.txt)、[打包输出](package-check-fixed.txt)。未生成新的真实参赛 ZIP。

实际测试 ZIP 状态为 **TEST_ONLY_VERIFIED**：重新打开后 CRC、所有 `manifest.sha256` 条目及条目唯一性均通过。Agent 配置和空 `.env.example` 存在，真实 Key、私有路径、数据库、权重、规则 PDF 和官方原件不在包内。主表与技术补充分开。PPTX/MP4 是小型容器 fixture，**不代表可播放的正式视频、最终 PPT 或真实团队资料**。`ready_to_submit=false`、`uploaded=false`。

渲染先实际尝试标准文档脚本，但本机缺其所需 LibreOffice，随后用 Word 只读导出 PDF、Poppler 渲染。原件与新草稿共六页全部查看；本轮没有复现历史文本/项目符号重叠，不据此宣称已修复历史版式问题。保留 Symbol/ArialUnicode 字体警告；正式实名版仍需负责人 Word 全页复核。

实际命令（`$py` 指向已有 Agent 可选环境的 Python；在本 PR 工作树运行，避免 editable install 误用主仓库源码）：

```powershell
$py = 'F:/qcx/code/HomeTrace/artifacts/issue-11/agent-env/Scripts/python.exe'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& $py -X utf8 -m pytest -q --junitxml=artifacts/pr-15-integration-20261025/pytest-final-463.xml
& $py -X utf8 tools/fill_official_submission.py --config F:/qcx/code/HomeTrace/local_data/submission/config-pr15-integration-fixed-draft.json --check
& $py -X utf8 tools/build_submission.py --config F:/qcx/code/HomeTrace/local_data/submission/config-pr15-integration-fixed-draft.json --repo-root . --check
git diff --check
```

私有产物验证命令为 `python -X utf8 artifacts/pr-15-integration-20261025/verify_artifacts.py`，该本地验收脚本读取已忽略的真实输入，使用生产 `collect_source/build/verify_filled` 完成检查。公开可重复的安全测试入口为 `python -m pytest -q tests/test_official_submission.py tests/test_official_agent_integration.py tests/test_official_paragraph_style.py tests/test_official_attribute_whitespace.py tests/test_agent_submission.py`；这些测试自行创建假资料，不需要官方原件或私人身份。

## F–G. 真实性及识别能力

真实执行的是全量测试、真实 DOCX 填写/拒绝/渲染、生产打包与 SHA/CRC/Key 校验。假材料仅用于正常打包路径和异常输入验证。本轮无真实家庭识别实验、无新增 Agent API 推理或机器人动作；已有 Agent 实测与 YOLOE **NO_GO** 仍以冻结报告为准。导航继续为模拟。

是否改善真实识别能力：**尚未证明**。本轮未修改检测阈值、SearchCore 或视觉后端，未增加 FOUND。

## H–I. 提交包状态与下一步

PR #15 集成代码和工具验证已提交 PM 复核，**未合并**。正式作品仍 **BLOCKED**：真实团队身份与平台信息未确认，正式实名主表未全页验收，P4 PPT/视频/补充说明和最终 ZIP 尚未完成。现有历史 candidate 不能改名充当最新作品；本轮 TEST_ONLY 包不能上传。

下一步首先由 PM 复核本 PR，同时在本地补齐真实身份及已验收 P4 能力的材料。后续 DataForge 必须另开分支，优先数据可追溯、划分与受控增强；无可靠掩码不合成，不宣称识别率改善。当前计划截止 2026-11-04，具体时刻待平台核验，保留 11 月 3 日检查/上传缓冲。只有平台成功回执才能报告已提交。
