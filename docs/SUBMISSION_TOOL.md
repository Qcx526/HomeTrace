# 本地候选提交包工具

以 [Issue #12](https://github.com/Qcx526/HomeTrace/issues/12) 为准：`document_source=official_template`，主办方原件与填写稿必须分离，七页自编说明书仅作补充。填表字段、DRAFT 模式、原件 SHA256 与版式验证见 [官方材料接口](OFFICIAL_SUBMISSION.md)。工具不上传，不自动认定官方格式、内容或参赛资格通过。

2026-10-25 集成状态：PR #15 在 main `4429fcf21797d6af05d189effdd510918315acc4` 的同一合并工作树实际运行 **463 passed，0 failed，0 skipped，82.32 秒**，含 5 项官方表与 Agent 配置/动态 Key 联合测试及 5 项真实模板缺陷回归，未修改旧断言。原独立分支报告保持不变，见 [本轮集成证据](evidence/pr-15-integration-20261025/README.md)。DRAFT 正式填表检查及包预检均为 exit 2 / BLOCKED。历史 DOCX 重叠本轮未复现，原件和非编辑部分未改，不宣称修复；正式实名版本仍需负责人 Word 全页复核。真实身份、最终 P4 媒体与 ZIP 尚未验收，正式参赛包仍 **BLOCKED**。

## 输入与运行

先按 README 安装项目。打包入口只有一个；实际 MP4 校验需要 PATH 中的 `ffprobe` 和 `ffmpeg`，PDF 报告需要可选 `pypdf`，使用 Markdown 报告则无需 PDF 依赖。

```powershell
New-Item -ItemType Directory -Force local_data/submission
Copy-Item examples/submission_config.example.json local_data/submission/config.json
.venv/Scripts/python.exe tools/build_submission.py --config local_data/submission/config.json --check
.venv/Scripts/python.exe tools/build_submission.py --config local_data/submission/config.json
```

配置内材料路径相对于配置文件所在目录，使用 `/`，禁止绝对路径、`..`、符号链接和 Windows reparse point。例如 `final/HomeTrace.mp4` 对应 `local_data/submission/final/HomeTrace.mp4`。以下材料必须存在、非空且通过结构检查：

| 配置字段 | 内容 |
| --- | --- |
| `materials.application` | 填写后的官方 DOCX，默认包内名 `01_HomeTrace官方初赛作品文档.docx` |
| `materials.presentation` | PPTX 技术展示 |
| `materials.video` | 实际运行录制的 MP4 |
| `materials.run_report` | UTF-8 Markdown 或 PDF 运行说明与测试报告 |
| `materials.originality` | UTF-8 Markdown 或 PDF 开源算法与原创性说明 |

官方表要求本地真实身份完整、确认且与 `team` 配置一致。缺失身份会 BLOCKED；可用 `fill_official_submission.py --draft` 准备讨论稿，但该稿不能进入正式候选包。旧 `team_authored` 接口仅保留历史技术候选兼容，报告明确 `official_application=BLOCKED`、包内名含“缺少官方主表”，不符合当前提交合同。配置和实名材料只留本地。

三个内容确认项 `privacy_reviewed`、`media_truthful`、`materials_consistent` 应在实际检查材料后设为 `true`；未确认时记录 `PENDING`，不阻断候选包，但最终上传前必须复核。这些是本地人工/团队确认记录，程序不会自动替人断言内容真实。图像证据与视频必须保持实际照片、公开样例、模拟导航和真机数据的区分。实际检测到的越界、链接、可识别密钥等仍会阻断生成。

`submission_page_checks` 记录格式、名称、大小、附件、截止时间、团队信息和解压打开情况。未确认项为 `PENDING`，**不会阻断完整候选包**。DOCX/PPTX/Markdown 中可检测到的 `TODO`、`待填写` 等占位内容产生待复核提醒；并不代表所有占位内容已被检测出来。最终上传前需逐项核验实际提交页面，不硬编码未知的官方大小限制。

必须提供 `materials.official_template`、`official_source`、`official_template_sha256` 和 `official_fields`；`materials.technical_supplement` 为可选补充。工具不会将原件或规则说明 PDF 压入包。自动检查无法判断来源陈述的真伪，负责人仍须核对官方来源及实际页面。

## 输出和校验

输出固定到 Git 忽略的 `dist_submission/`：

- `candidate-HomeTrace.zip`（或本地真实身份命名）：材料与核心源码。
- `submission-audit.json`：状态、缺失/损坏原因、待核验项、媒体校验方式、源码来源及 ZIP 大小、SHA256；失败也会生成报告。
- `archive.sha256`：整个成功归档的 SHA256。

ZIP 内包含材料清单、`SOURCE_INFO.json`、`PRE_UPLOAD_REVIEW.json` 和逐文件 `manifest.sha256`。每个输入在写入前再次比对哈希；写入后重新打开 ZIP，检查 CRC、精确条目集合及每个条目的 SHA256。清单不包含自身哈希（避免循环依赖）；程序仍验证清单本身的内存预期哈希，外部归档哈希覆盖整个 ZIP。

源码从 Git 的已跟踪及未忽略工作文件清单中筛选，使用限定的路径和扩展名 allowlist：核心 `src/`、测试、工具、README、构建配置、选定技术文档及 OpenCV 公开回归样例/许可。允许开发候选包包含尚未提交的合法源码，记录 HEAD、工作区脏状态、纳入的未跟踪文件数、实际源码快照 SHA256；不能将它描述为完全等同于 HEAD。`expected_source_commit` 可设置为当前完整提交号，设置后不一致会失败。交付最终版应优先从已提交的可追溯版本生成。

源码白名单保留 `config.yaml` 和空 `.env.example`，用于复现已合并 Agent；真正的 `.env` 绝不导出。`.env.example` 只有空 Key 示例才可进入包；配置中的秘密字段、可识别的私钥/部分 token，以及本机已配置 Key 混入普通源码时会阻断。实际源码包必须验证这两项配置存在且敏感文件缺席，不能只检查文件名。

排除 `.git`、`.venv`、除上述空示例外的隐藏文件、缓存、数据库、`local_data`、私密原图、模型权重、旧 ZIP、历史运行日志和非 allowlist 文件。公开的记录图像只允许列出的 OpenCV 稳定样例。这不是完备的密钥或隐私扫描，文档与视频中的个人信息、二维码、屏幕内容必须人工检查。为防止静默覆盖，已有同名 ZIP 时拒绝生成新包；先在本地归档旧包再重试。

Office 验证包括 ZIP CRC、必需 OOXML 部件、XML 可解析性、可读取文本、重复/越界条目、宏及嵌入对象检查；不保证排版或内容完整，须在 Word/PowerPoint 中打开。MP4 验证包括容器基本结构、`ffprobe` 视频流/时长、`ffmpeg` 全片解码；不证明视频中的内容是实拍或执行结果。PDF 通过 `pypdf` 读取页面；Markdown 检查 UTF-8 和非空内容。

退出码 `0` 表示本次预检/候选归档校验完成；`2` 为 `BLOCKED`。成功状态为 `CANDIDATE_PREFLIGHT_PASSED` 或 `VERIFIED_CANDIDATE_REQUIRES_OWNER_REVIEW`，始终 `ready_to_submit=false`、`officially_verified=false`、`uploaded=false`。必须人工解压打开、完成提交页核验后，才能由团队决定上传。

## 自动化测试边界

```powershell
.venv/Scripts/python.exe -m pytest tests/test_submission.py -q
.venv/Scripts/python.exe -m pytest tests/test_official_submission.py tests/test_agent_submission.py -q
# 集成验收先安装可选 Agent/视觉测试依赖，再在同一工作树运行完整测试
.venv/Scripts/python.exe -m pip install -e ".[dev,vision,agent]"
.venv/Scripts/python.exe -m pytest -q
```

合成资料仅用于 `test_only=true`，输出恒为 `TEST_ONLY-candidate-HomeTrace.zip`，清单和状态均明确非正式提交。测试 MP4 仅有伪造的结构盒，用于校验异常输入逻辑，不是可播放视频。真实候选视频不会使用该旁路，必须完成解码。测试覆盖材料缺失/为空、损坏 Office/MP4、路径越界/链接、工作区源码与隐私排除、密钥阻断、重复配置、打包期间文件改变、已有 ZIP、防止身份泄漏、完整性和清单复核。

正式集成还须用本地真实官方原件核对 SHA 与表结构，实际验证缺失身份的 DRAFT 被拒绝，并对源码 ZIP 重新打开核验 CRC、条目清单及 SHA256。源码 ZIP 或 TEST_ONLY 夹具通过不能表示官方参赛包通过；原件、规则说明 PDF、私人身份和含图结果仍只留在本地。全量测试和产物校验完成后提交 PR 供 PM 复核，不自行合并。
