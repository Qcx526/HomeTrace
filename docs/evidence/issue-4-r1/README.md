# Issue #4 R1 验证记录

2026-10-23，基线 `e3adca7ebde7317546a70506514d65c39fe1a62f`（已合并 PR #8）。本轮为登记 ROI 与背景误报复核，未重写 SearchCore/UI，未更改 ORB、匹配距离、RANSAC、内点及几何验证阈值。代码版本 0.4.1。

| 验证 | 本次真实结果 | 证据 |
| --- | --- | --- |
| 开发环境全量回归 | 289 passed in 54.40s，0 skipped | [pytest.txt](pytest.txt) |
| Windows 新虚拟环境，非 editable wheel | 289 passed in 55.21s，0 skipped；pip check 通过；仓库外 fixture CLI FOUND | [测试](clean-environment/pytest.txt)、[安装归属](clean-environment/installation.json)、[依赖](clean-environment/dependencies.txt) |
| 旧测试保留 | 原有 226 项、原文件与 main 相同；新增 63 项 | [源码与 wheel 摘要](validation.json) |
| 家庭图片完整性 | 四组 24 张，前后 SHA256、字节数、尺寸一致；原图与 ROI 未按结果调整 | [公开数值](experiment-summary.json)、[完整分析](../../REGISTRATION_ROI_EVALUATION.md) |
| 正式检测对照 | 40 个计划项，35 次实际 detect，5 项参考图质量拒绝；整图空木纹误报 FOUND，ROI 后 UNKNOWN | [逐项指标及 CLI 汇总](experiment-summary.json) |
| ROI 家庭正负例 | 明确负例 0/8 FOUND；明确正例 0/6 FOUND；5 不确定、1 辅助参考单列 | [实验报告](../../REGISTRATION_ROI_EVALUATION.md) |
| 公开浏览器，实际新 wheel | moved FOUND/B，missing SUSPECTED/null，replay UNKNOWN/null；检测框、逐步计数、下载、手机宽度通过，无页面错误 | [浏览器逐步检查](browser/browser-checks.json)、[正例框](browser/moved-matched.png)、[未确认](browser/missing-final.png)、[重放](browser/replay-final.png) |

新增测试：登记 ROI 23 项；固定种子合成背景对抗 10 项；实验输入及归属 18 项；提交材料中文占位符 12 项。合成对抗中两次完整参考图背景误确认是明确反例；ROI 后六个负例未确认，两个不同背景的合成正例 FOUND 且框/四角误差在 5 像素内。它们是自动化软件回归，不是家庭照片识别成绩。原有 226 项包括最初 P0/P1/P2 的 148 项。

## 实际运行命令

以下命令在仓库根目录执行，已有输出不可覆盖；复跑应换新目录。

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/evaluate_registration_roi.py --data-root local_data/team_new_20261023 --output-dir artifacts/issue-4-r1/experiment-verified
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml artifacts/issue-4-r1/pytest.xml
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir artifacts/issue-4-r1/wheel .
.\.venv\Scripts\python.exe -m venv artifacts/issue-4-r1/clean-env
.\artifacts\issue-4-r1\clean-env\Scripts\python.exe -m pip install "artifacts/issue-4-r1/wheel/hometrace-0.4.1-py3-none-any.whl[dev,vision]"
.\artifacts\issue-4-r1\clean-env\Scripts\python.exe -X utf8 -m pytest -q --junitxml artifacts/issue-4-r1/clean-pytest.xml
.\artifacts\issue-4-r1\clean-env\Scripts\python.exe -m pip check
.\artifacts\issue-4-r1\clean-env\Scripts\python.exe -X utf8 -m hometrace demo --port 8768 --output-dir artifacts/issue-4-r1/public-demo
node tools/validate_p2_browser.cjs http://127.0.0.1:8768 artifacts/issue-4-r1/browser
```

最后一条开发验证工具使用 bundled Node/Playwright 与本机 Edge 155.0.4283.62；它不是运行 Demo 的依赖。正式实验额外执行四个独立 register/search CLI，原始命令、报告及 SQLite 均保存在 `artifacts/issue-4-r1/experiment-verified/cli/`。登记历史为空，所有时间标记为实验 `demo_sequence`，不虚构真实拍摄或搬移顺序。公共三场景两种策略的访问步数仍然打平（2/3/3），没有效率提升结论。

Windows 10 / Python 3.11.4 / OpenCV 4.14.0 / NumPy 2.4.6。新建的是虚拟环境，不是重装 Windows。非隔离 wheel 构建最初因开发环境缺少 `bdist_wheel` 失败；改用上述标准隔离构建后成功，无需增加产品依赖。最终 wheel 与源码包内 21 个文件逐字节核对一致；安装位置为新环境 site-packages。本轮没有其他操作系统或真实机器人运行。

## 隐私、材料与交付状态

公开实拍统计只含匿名场景编号、人工评估类别、真实检测状态、数字指标和原因；图像哈希、路径映射、ROI/bbox、私图及 EXIF 仅留在 Git 忽略目录。公开截图全部来自 OpenCV 许可样例，导航始终为模拟。预筛选 JSON 未作为正式检测结果导入。旧 75 项家庭评价与本轮 40 项不相加为独立样本或成功率。

ROI 缓解了本轮已知误报，不能保证任意 ROI 或未知家庭场景可靠；完整参考图模式仍可能匹配背景。没有家庭成功演示入口。Word/PPT/MP4 为 PR #8 历史材料，新增书面风险与实验结论已同步到材料说明和运行报告。旧 `candidate-HomeTrace.zip` 保留原摘要，不能代表 R1。PM 审查后仍需同步最终材料、补齐本地团队身份、核验本届平台要求、重新打包并实际上传。Issue #4 保持 OPEN，本 PR 不自行合并。
