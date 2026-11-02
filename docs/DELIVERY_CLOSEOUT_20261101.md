# HomeTrace 当前交付与最后检查

收口启动于 2026-11-01，执行延续至 11-02。Issue #44，分支 `feature/44-delivery-closeout`，基于未合并 PR #43 的 `16445f7`，并纳入未合并 PR #15 的官方主表工具。原 PR、历史报告和原始照片不变；本分支不自动合并。

当前交付定位为 **LLM 主导工具决策、主人最终确认的家庭寻物软件 Demo**。用户手动选择地点并提供照片，导航模拟。家庭通用实例识别、自动可靠定位和真机运动没有通过验收。交付材料不得把主人确认写成自动 FOUND。

## 目前还缺什么

| 项目 | 当前事实 | 完成方式 |
| --- | --- | --- |
| 官方身份 | 负责人明确要求留空，之后自己填写 | 在本机填写官方主表与配置；未填时正式检查保持 BLOCKED |
| 最新软件流程 | 自定义地点空工作区 HTTP 验收已跑通，40项检查，16次真实文本调用 | 合成素材、脚本主人、模拟导航；不是家庭实拍验收 |
| 最新材料 | 新技术补充、PPT、实际浏览器视频分别生成，保留旧版 | 以本轮产物清单和实际验收日志为准 |
| 自动实例识别 | 新8图 ORB均无有效框；模型4相似、1不确定、1失败、2未见目标 | 保留受限人机协作展示，不临时训练或放宽阈值 |
| 代码审查 | 最新功能在 stacked PR，官方工具PR也未合并 | PM审查后统一集成；不能声称已发布 main |
| 平台提交 | 没有上传回执，大小/命名/剩余次数未登录核验 | 负责人实际检查报名系统并上传 |

公开[赛事页](https://developer.huaweicloud.com/contest/2026-huawei-embedded-ai-challenge.html)于本轮查询时列出实物组初赛截止 **2026-11-04 12:00**，初赛提交文档、PPT、视频、源码、Demo等材料，取最后一次提交评分。负责人提供的延期通知相符。最终仍需核对[本人报名页面](https://developer.huaweicloud.com/competition/information/1300000313/introduction)；未将公开时间查询等同于登录后的附件、容量或提交次数核验。内部目标是11月2日完成文件，11月3日留给填写和上传检查。

## 固定演示入口

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,vision,vision-advisor,agent]"
# 在本机 .env 填 HOMETRACE_LLM_API_KEY=；不要覆盖已有 Key。
.\.venv\Scripts\python.exe -m hometrace demo --photo-agent --port 8770 --household-dir artifacts/my-home
```

浏览器打开 `http://127.0.0.1:8770/`。先登记名称、别名、参考图和经用户确认的ROI；选择所在地点，发送“请记住这个物品放在这里了”，核对后保存。配置各地点当前场景，再发送寻找请求。查看真实LLM调用、工具反馈、候选和失败；主人接受才写入 `USER_CONFIRMED/owner_reported`。重启使用同一工作区可查询历史。

自定义地点是在该工作区创建 `locations.json`，配置见 [地点说明](WORKSPACE_LOCATIONS_AND_NEW_PHOTOS.md)。最多10地点，运行时冻结快照，不扩大原步骤预算。当前位置不会自动定位，未配置图像不算已观察。

可选 `--photo-vision-agent` 提供逐次授权看图；任何新私人图片必须在页面确认端点和图片范围。先前8次授权已消费，本轮没有借用它重新发图。离线/模型失败不得伪装为真实在线推理。

## 本轮空工作区验收

```powershell
python tools/accept_photo_workflow.py --custom-locations --output-dir artifacts/acceptance-NEW
python -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
```

真实验收工具要求本机固定哈希合成素材和有效API配置；输出目录必须不存在。克隆仓库并不自带私有或合成素材，缺输入就失败，不得报告成功。

2026-11-01实际HTTP运行：两个空工作区、4个服务进程、6个请求、16次文本LLM调用、20933 tokens、40项检查通过。历史地点位于字母序末位，模型仍首先检查历史点，然后到新地点产生实际ORB候选。候选重启恢复、脚本确认、再次重启查记忆、旧图重放UNKNOWN、拒绝后继续寻找均实际执行。图片外发0，重试0。素材是AI合成钥匙，不能据此证明水杯或家庭真实识别。

本轮浏览器、全量回归、干净安装和材料验证结果见 `docs/evidence/issue-44/` 以及本地 `materials/RUN_TEST_REPORT.md`。HTTP、浏览器、单元测试、实拍诊断分别统计，不把不同分支的测试数量相加。

## 交付文件与填写步骤

本机材料目录为 `local_data/submission/20261101/materials/`，配置为 `local_data/submission/20261101/config.json`。均被Git忽略，目录日期是本轮开始标识，实际制作可延续到11月2日。

- 官方主表 `DRAFT_HomeTrace官方初赛作品文档.docx`：来自原始官方DOCX，只填当前项目内容；团队字段保留待填，不认证为正式主表。
- `HomeTrace_作品设计与技术说明书.docx`：技术补充，不能代替官方主表。
- `HomeTrace_技术展示.pptx`：当前10页展示；实际测试数字带历史快照来源。
- `HomeTrace_演示视频.mp4`：真实程序页面的合成素材演示，字幕说明真实/模拟/人工环节。
- `RUN_TEST_REPORT.md`、`OPEN_SOURCE_AND_ORIGINALITY.md`：实际运行与能力边界。

填写前先复制配置，保留本轮草稿证据。设置 `official_fields.team_name`、课题名称和300字内描述；`members`填写1至3名成员的姓名、性别、学历、学校、专业、毕业时间、邮箱、电话，与平台一致。同步顶层 `team`，确认后设两处 `identity_confirmed=true`。修改 `materials.application` 为一个不存在的正式文件名，不覆盖DRAFT或官方原件。若直接在Word填写，也必须同步配置字段，严格验证才有可靠对照。

```powershell
python tools/fill_official_submission.py --config local_data/submission/20261101/config-final.json
python tools/fill_official_submission.py --config local_data/submission/20261101/config-final.json --check
python tools/build_submission.py --config local_data/submission/20261101/config-final.json --check
python tools/build_submission.py --config local_data/submission/20261101/config-final.json
```

在Word中逐页复核正式稿，核对姓名、团队名和描述没有溢出。配置中 `expected_source_commit` 指向最终审查提交。旧同名ZIP需由负责人保留在独立目录后再生成，工具不覆盖。完整性通过不等于官方审核或上传成功。

个人字段未填时可使用 `python tools/build_review_bundle.py --config local_data/submission/20261101/config.json` 生成 **REVIEW_ONLY_HomeTrace.zip**。它仅用于传递待填写的工作副本，包含醒目的不可上传说明；不改变正式检查结果。所有其他材料/源码/Key问题继续阻断。它不能改名冒充最终参赛包。

## 提交前最后六项

1. 官方身份、团队名与平台一致，删除不适用队员行，原表结构保留。
2. 主表、补充说明、PPT、视频、源码版本与事实一致，未经验证能力不宣传为完成。
3. 逐文件实际打开，视频完整播放，源码从解压目录安装运行；保留CRC与SHA256。
4. 原始家庭照片、API Key、数据库、训练权重、官方规则PDF和未填原件不进最终包。
5. PM审查剩余PR和本轮集成；不会自动合并或宣称main已更新。
6. 核验提交页大小、命名、附件和剩余次数，由负责人上传并保存真实回执。
