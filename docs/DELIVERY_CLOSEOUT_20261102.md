# HomeTrace 11月2日新版材料与交付验收

Issue #4 / #12。分支 `feature/4-final-materials-20261102` 基于 PR #47 的 `537aa9c`，属于未合并依赖链上的材料增量。本轮不改寻物核心、视觉阈值、Agent 或数据库，不重新发送照片，不覆盖前轮材料或历史报告，也不自行合并。

制作于11月2日启动，最终交付检查延续至11月3日；目录日期是批次标识，实拍结果仍引用11月2日的冻结记录。

## 交付定位

**LLM 根据记忆与照片反馈选择工具、主人核对身份后保存位置的受限家庭寻物 Demo。** 已有一件真实水杯完成原地点未见、换地点、请求近景、主人确认、跨进程查询与旧图拒绝。自动实例识别、可靠实拍检测框、独立 6 正/8 负基准、真机运动和家庭通用识别仍未通过。

本轮材料引用 [新增实拍报告](REAL_CUP_FRESH_WORKFLOW_20261102.md) 及其脱敏 JSON，不把素材演示、HTTP 实验、软件回归拼成同一项准确率。首次 24,000 Token 预算停止保留；32,000 预算复跑完成，没有放宽视觉门槛。H/B 和 S1–S5 仅为匿名场景代号。

## 新材料与旧材料

本机新版在 `local_data/submission/20261102-final/`，旧 `20261101/` 保留。个人信息遵照负责人要求留空，官方主表为 **DRAFT**。原官方模板 SHA256：`44da6ca1ab0f3ad62c2588431e3a3c705b96e6a2638666ae826a2e37d29d69ec`，保持原表格结构；技术说明书是补充材料。

| 文件 | 用途与来源 |
| --- | --- |
| DRAFT_HomeTrace官方初赛作品文档.docx | 原官方主表填入项目内容，身份待负责人填写 |
| HomeTrace_作品设计与技术说明书.docx | 场景、架构、真实结果、失败和限制 |
| HomeTrace_技术展示.pptx | 可编辑技术展示，真实与模拟环节分开 |
| HomeTrace_演示视频.mp4 | 161.92秒；保留89.92秒既有合成钥匙演示视频（含片头、原速实际录屏与片尾），追加72秒实拍执行记录摘要，后者不是实时录屏 |
| RUN_TEST_REPORT.md | 运行命令、实际验证、结果与来源 |
| OPEN_SOURCE_AND_ORIGINALITY.md | 成熟算法复用、原创流程和素材来源 |

视频为 H.264、1440×1080、中文字幕、无音轨。没有展示私人原图、屏幕、二维码或位置绑定。没有根据 JSON 伪造浏览器画面；摘要卡片始终标注“非实时录屏”。完整解码和逐章节抽帧检查分别记录。本轮媒体制作新增模型调用和图片外发均为 0。

## 可复现入口

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,vision,vision-advisor,agent]"
# 在本地 .env 填 HOMETRACE_LLM_API_KEY，不要覆盖已有密钥。
.\.venv\Scripts\python.exe -m hometrace demo --photo-vision-agent --port 8770 --config config.photo-demo.yaml --household-dir artifacts/my-home
```

上传到本机不代表批准外发。参考 ROI 和每张场景需按界面目的地、范围与次数授权，旧授权不能复用。先登记并确认参考区域，选择地点后让系统记住位置；配置地点照片，再请求寻找。模型请求近景时提供同地点新照片；只有主人核对后才保存 `USER_CONFIRMED / owner_reported`。重启使用同一工作区。照片拍摄时间未知时不得写成当前可靠位置。导航模拟，无机器人自动扫描。

不使用云端图片时可用 `--photo-agent`；本地 ORB 在本轮水杯上未形成可靠框，因此它不能替代已验证的主人参与流程。离线软件回归不需要模型 Key，不证明现实识别精度。

## 打包与填写

```powershell
python tools/build_review_bundle.py --config local_data/submission/20261102-final/config.json --output-subdir 20261102-final
```

输出 `dist_submission/20261102-final/REVIEW_ONLY_HomeTrace.zip`。它包含源码快照、草稿、补充材料、SHA256 和醒目的不可上传说明；不会包含官方未填原件、规则 PDF、本地配置身份、照片、Key、数据库或权重。正式构建仍因身份为空而 BLOCKED。不要改名冒充可上传包。

负责人在本机复制 `config.json` 为 `config-final.json`，保留草稿证据；按平台填写 `official_fields` 中团队、1–3名成员八项字段，核对300字内描述，并同步顶层 `team` 和两处 `identity_confirmed`。设置 `materials.application` 为新的正式 DOCX 文件名，`expected_source_commit` 指向最终审查版本。不要覆盖原模板或 DRAFT。

```powershell
python tools/fill_official_submission.py --config local_data/submission/20261102-final/config-final.json
python tools/fill_official_submission.py --config local_data/submission/20261102-final/config-final.json --check
python tools/build_submission.py --config local_data/submission/20261102-final/config-final.json --check
python tools/build_submission.py --config local_data/submission/20261102-final/config-final.json
```

新版文件制作、源码回归、解压安装和审计的实际结果见当前 PR 的 `docs/evidence/submission-20261102/` 及包内测试报告。最终 ZIP 审计作为打包后的后续证据提交，未包含在 ZIP 自身；源快照以包内 `SOURCE_INFO.json` 和逐文件哈希为准。

本轮导出的源码在新的 Windows venv 中构建 wheel 并安装，`pip check` 通过，实际全量 **1161 passed，191.98秒**，一个既有 LangChain 弃用提示；同一导出目录前端 **28 passed，260.1336ms**。空工作区 HTTP 与 wheel 内容 **9项检查通过**。没有真实模型调用或图片外发；这是同一台 Windows 的新环境，不是重装操作系统。此前工作树的1160项结果保留；最后增加的1项打包秘密保护测试已在上述1161项中实际执行，不是数学相加。

官方草稿3页、技术书6页均逐页检查，原模板结构与非填写部件保持不变。标准 DOCX 渲染器缺 LibreOffice，失败日志保留，改用 Word16只读PDF导出和 bundled Poppler渲染，未保存改写DOCX。PPT12页通过结构、布局、字体及原生表格检查，最终文件回读渲染逐页检查；未声称在原生 PowerPoint 中打开。视频完整解码通过，检查13张抽帧（覆盖6张新增说明卡）。

## 仍须负责人完成

1. 填写官方团队身份并与报名系统一致，实际打开主表检查排版。
2. 让 PM 审查本 PR 及前置 PR 链，统一最终代码和材料版本。
3. 登录本人报名页面核验格式、命名、容量、必选附件、剩余次数和截止。负责人提供的延期通知为11月4日中午12点；本轮未重新登录核验，以平台最新值为准。
4. 构建正式候选后解压打开、完整播放视频、核对清单，再由负责人上传并保存回执。本轮没有执行比赛上传。
