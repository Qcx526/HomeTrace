# Vision R0 验收证据（2026-10-26）

结论 **BLOCKED：没有通过筛选的家庭实例识别方案，也没有独立真实测试集**。主报告见 [失败诊断与方案筛选](../../VISION_R0_DIAGNOSIS.md)，预先冻结口径见 [协议](../../VISION_R0_PROTOCOL.md)。当前任务优先于材料/DataForge。

## 版本与范围

- 基线 main `4429fcf21797d6af05d189effdd510918315acc4`；PR #15保持OPEN，未合并。
- 独立分支 `feature/4-vision-r0`。
- `49f4fd1`：新候选运行前记录协议；`59e1412`：首版诊断工具；`0dbb1c742d4ec6a4f020382471514948866598b9`：最终证据绑定修复与被测源码。
- 后续提交仅补报告和脱敏证据。原生产代码、配置、测试、冻结报告均未修改，核对见 [preservation.json](preservation.json)。不将PR #15独立分支测试数量计入本分支。

## 实际运行结果

| 检查 | 结果与证据 |
| --- | --- |
| 原图与数据复用审计 | [data-audit.json](data-audit.json)、[data-integrity.json](data-integrity.json)：新包24张，三包40条目/32唯一字节文件，全部已使用，无独立保留集 |
| 历史基线复跑 | [baseline-reproduction.json](baseline-reproduction.json)：75+40+20逐行非时间数据一致；[P3](p3-rerun.json)、[ROI](roi-rerun.json)、[YOLOE](yoloe-rerun.json) |
| 新候选对照 | [comparison.json](comparison.json)、[实际stdout](comparison-02.txt)：8配置×20场景=160记录；不等于160图片或160神经推理 |
| 背景支持诊断 | [background-support.json](background-support.json)：ORB木纹44/44内点在固定登记ROI外；SIFT/AKAZE亦主要为背景支持 |
| 候选实际覆盖图复核 | [qualitative-cases.json](qualitative-cases.json)：开发者查看本轮三候选，1个正确小挂件候选、2个大熊猫混淆；不是负责人真值框或独立定位指标 |
| 原始神经证据绑定 | [rerun-binding.json](rerun-binding.json)：请求/worker/汇总相互核对；修复后160项重跑语义不变，旧run保留 |
| 软件回归 | [pytest.txt](pytest.txt)、[regression.json](regression.json)：**473 passed，0 failed/errors/skipped，68.35秒**，1条LangChain未来默认值警告 |
| 隐私与差异 | [preservation.json](preservation.json)：旧文件不变，新增文件无原始图路径/哈希及真实Key；git diff --check通过 |

473为在同一视觉工作树真实执行的完整日志：主线424项与新增49项均执行，未改旧断言。新增测试覆盖指标分母、无独立集、错误实例、登记拒绝、候选坐标、原图坐标映射、原始worker/request矛盾及篡改拒绝。pytest使用Agent环境的OpenCV4.12.0；最终传统图片对照使用原环境4.14.0/NumPy2.4.6。软件通过不等于家庭识别通过。

## 命令与私有产物

在仓库根目录，显式 `PYTHONPATH=src`。本轮实际输出根为 `artifacts/vision-r0-20261026/`，均被Git忽略；复跑须换新的输出名。

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
.venv/Scripts/python.exe -X utf8 tools/evaluate_team_photos.py --data-root local_data --output-dir artifacts/vision-r0-20261026/p3-baseline-cv414
.venv/Scripts/python.exe -X utf8 tools/evaluate_registration_roi.py --data-root local_data/team_new_20261023 --output-dir artifacts/vision-r0-20261026/roi-baseline-cv414
artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 tools/evaluate_yoloe.py --data-root local_data/team_new_20261023 --output-dir artifacts/vision-r0-20261026/yoloe-baseline --python artifacts/issue-10/neural-env/Scripts/python.exe --weights artifacts/issue-10/weights/yoloe-11s-seg.pt --protocol artifacts/issue-10/protocol.json
.venv/Scripts/python.exe -X utf8 tools/evaluate_vision_r0.py --data-root local_data/team_new_20261023 --neural-dir artifacts/vision-r0-20261026/yoloe-baseline --output-dir artifacts/vision-r0-20261026/comparison-02
artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 -m pytest -q --junitxml=artifacts/vision-r0-20261026/pytest.xml
git diff --check
```

本地完整输入、哈希、框、质量/匹配信息：`comparison-02/results.private.json`、`registry.private.json`（24条）、`binding.private.json`。真实YOLOE逐图request/result/stdout/覆盖图在`yoloe-baseline/`。诊断联系图`contact.private.jpg`；背景内点图在`support-trace/`。历史基线CLI仅模拟导航，新的成对对照无导航。没有真实机器人或合成家庭样本。

背景追踪是对已接受的四项输出做事后诊断，不是额外筛选算法：重新使用同方法特征、ratio0.75、对应距离、唯一场景描述子和原RANSAC，核对匹配/内点数量与保存结果相同，再统计参考关键点是否在固定登记ROI内。该ROI不是分割掩码；不据此声称ROI内所有点都属物体。私有内点图用于核查，未公开。

## 验收结论及剩余问题

ROI ORB/SIFT/AKAZE和YOLOE→SIFT均 **0/6正例几何接受、0/8负例错误接受**，无接受时precision未定义。全图方法出现明确木纹误接受，详情见主报告。YOLOE候选的“有框率”与实例确认指标严格分开；无独立数据的precision/recall/FPR均null/BLOCKED。

本轮交付诊断与筛选报告，不接入生产方案。下一步最小方向是物体表面/多视角参考登记与质量诊断，仍须有实际对照；不是保证有效的解决方案。补拍应提供冻结方案后的独立批次、相似实例负例及人工确认框，具体6正8负受限Demo协议已写明。当前没有真实家庭识别改善证据，不将结果包装为可参赛的完整识别能力。由PM审查PR，不自行合并。
