# 实际候选 ZIP 验证

2026-10-23 使用本阶段真实材料构建，本地配置 `local_data/submission/config.json`，`test_only=false`、`document_source=team_authored`。身份字段为空，内容与赛事平台人工核验保留 PENDING，没有虚构队员姓名/手机号或人工批准。

```powershell
.\.venv\Scripts\python.exe tools/build_submission.py --config local_data/submission/config.json --check
.\.venv\Scripts\python.exe tools/build_submission.py --config local_data/submission/config.json
```

实际结果：`CANDIDATE_PREFLIGHT_PASSED` → `VERIFIED_CANDIDATE_REQUIRES_OWNER_REVIEW`。见 [工具审计 JSON](candidate-audit.json)。

| 项目 | 实际值 |
| --- | --- |
| 本地归档 | `dist_submission/candidate-HomeTrace.zip`，不提交公共 GitHub |
| 大小 | 5,081,580 字节 |
| 条目 | 81 个，包括 72 个限定源码文件 |
| 源码提交 | `db5e44e2a3152ba6e47f160509249747279604a5` |
| 工作区状态 | 构建时 clean；无未提交源码混入 |
| 源码快照 SHA256 | `8deeab6f4f6f0b92965902bed8fdef63550f7824eef2a15555b3e973712705bb` |
| ZIP SHA256 | `081546dbde846c04078b416ec20c90a37c8fee0e64fcde61cc551dde962b0512` |
| 完整性 | 重开 ZIP、CRC、精确条目集合、逐文件 SHA256 通过 |
| 正式状态 | `ready_to_submit=false`、`officially_verified=false`、`uploaded=false` |

材料包含最终 7 页 Word、10 页 PPT、72.28 秒实际软件演示 MP4、运行测试报告与开源原创性说明。Word/PPT 实际包结构可读取，7 页/10 页已渲染全检；解压后文件与核验材料字节一致。MP4 经 ffprobe 和 ffmpeg 全片解码，字幕与六个关键帧已核对。

另外用独立 `zipfile` 读取 `manifest.sha256` 并重新逐项计算，检查路径不含绝对路径/上级目录，未含 `.git`、虚拟环境、数据库、私有照片、密钥或其他 ZIP，然后实际解压到新的 `artifacts/p3-candidate-extracted/`。[解压与来源结果](candidate-extraction.json)。解压源码的完整回归另存 [实际测试输出](candidate-extracted-pytest.txt)；运行时显式 `PYTHONPATH` 指向解压的 `04_核心源代码/src`，CLI 子进程继承该目录。

后续补充证据的提交不改动此包的核心实现或媒体。该包仍是供 PM 与团队核验的候选，不是官方认证包或上传回执。负责人需补齐真实身份，并打开本届提交页面核对格式、命名、大小、必选附件/模板和截止时间。当前 Word 为自编作品说明书；若平台明确要求其他格式，再调整。

测试中的 TEST_ONLY 伪造 Office/MP4 结构只用于异常输入检验，不在此包内。此处真实 candidate 走正常 MP4 解码路径，没有使用测试旁路。
