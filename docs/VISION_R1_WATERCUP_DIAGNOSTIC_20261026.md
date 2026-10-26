# Vision R1-WaterCup：真实水杯照片开发诊断（2026-10-26）

本轮结论为 **BLOCKED**。18 张照片完成原始字节校验、解码和质量审计；负责人批准了三张固定登记 ROI 及两个实体的身份。三张参考都通过原图像质量门槛，但独立原始拍摄来源仍未确认，三者均存在 `capture_id_unknown`。因此没有合格的独立参考对，rival 也没有完整登记资格。**多参考共识未执行，不能认定其成功或失败率。**

原 `ImageMatcher` 的逐参考诊断确实运行：每轮 10 个场景、30 次去重检测调用，全部返回空框，没有几何接受。单参考方法执行 10 个场景、全部 UNKNOWN；多参考方法 10 个场景均 `executed=false`。场景真值仍未获确认，不计算正式 precision、recall、FPR 或 IoU。软件回归 **566 passed** 不等于真实识别通过。

## 1. 代码、依赖与不变边界

- 本分支：`feature/4-vision-r1-watercup`，从 PR #17 `16915c5f503e35076bdbbe612df465536c1d35f0` 建立。
- 新 PR 的 base 为 `feature/4-vision-r1-multireference`，stacked 依赖 #17，再依赖 #16；没有合并任何 PR。
- 实验代码提交：`c7b8ce34a01c86f68ba19284e52280ee10607573`。之后的报告提交只增加证据和文档。
- 原 `tools/vision_r1.py`、`tools/evaluate_vision_r1.py`、`tools/vision_r1_metrics.py`、生产 `ImageMatcher`、SearchCore、AgentService、SQLite schema、配置和旧报告均未改动。
- 新增 `tools/prepare_watercup_diagnostic.py`：验证 18 个固定输入、绑定哈希与人工审查文件、生成新私有快照，拒绝覆盖旧目录。候选场景 ROI 不进入检测 manifest，也不生成定位真值。新增 17 项准备合同测试。
- PR #15 仍 OPEN，head 为 `775d601f63c1201bf517b57287fe5589b8b1b1d9`；其工作区未改动。

本轮没有新增模型、神经网络依赖、导航或生产 FOUND 路径。全部观察来自离线真实照片，没有机器人运行，也没有模拟导航过程。测试生成纹理仅用于软件测试，不参与真实照片成绩。

## 2. 输入、原图审计与来源限制

输入仅使用负责人指定的本地水杯目录，没有回退旧数据。18/18 可解码；所有原图 SHA256 与首次审计、review-01、draft-01、draft-02 的绑定一致，无原始字节变化。没有完全相同的文件或解码彩色像素副本。逐张 SHA256、尺寸、清晰度、ORB 关键点、候选 ROI 和目视备注均保存在 ignored 私有文件中。

公开尺寸和质量表见 [inventory.public.json](evidence/vision-r1-watercup-20261026/inventory.public.json)，已删除输入哈希、原始路径、ROI 坐标、EXIF 设备信息及私人图像。18 张均为 `real / diagnostic_reused`，独立测试图片数为 0；没有合成或增强图片计入本轮实验。

没有读到 DateTime、DateTimeOriginal 或 DateTimeDigitized。部分文件有时区偏移，但它不能还原拍摄时间或证明独立拍摄。两个辅助视图分辨率较低，传输过程未知，不能推断其为独立拍摄或伪造图片。目录只有 18 张 JPG，没有额外 README、manifest 或原始来源凭据。缺失的 capture_id、时间和采集批次继续 unknown。

首次私有联系表审计使用彩色解码后转灰度；准备器与检测器使用 `IMREAD_GRAYSCALE` 原尺寸解码，少量清晰度数值存在差异。公开质量数据采用后者，匹配诊断直接取检测器输出。旧审计与记录保持原样，另存更正说明，不混用解码口径。

## 3. 负责人审核后参考资格

参考别名 `reference_01 / reference_02` 属于同一目标实例；`reference_03` 属于另一个 rival 实例。别名与原图映射仅在私有 manifest 中保留。

| 参考 | 原 ROI 清晰度 | ORB 关键点 | 图像质量 | 身份 / ROI 审查 | 当前资格缺项 |
|---|---:|---:|---|---|---|
| reference_01 | 30.682 | 768 | PASS | 负责人确认 | capture_id_unknown |
| reference_02 | 54.997 | 1067 | PASS | 负责人确认 | capture_id_unknown |
| reference_03（rival） | 70.803 | 1973 | PASS | 负责人确认其为不同实体 | capture_id_unknown |

负责人通过本轮对话明确批准三个实际红框，认可两张目标参考覆盖可比较的正面杯身与主要标志；第二张底部少量背景残留获准保留，已记录风险。原坐标完全未改。三者 `roi_reviewed=true`、`identity_reviewed=true`，背景污染审查为 `object_dominant`；目标对使用相同的正面杯口至杯底范围标识。审核原文、来源和前次快照哈希保存在 `review-02`。

目标参考对：目视为近水平正面与稍俯视正面，场景分别为浅色背景与木纹背景，ROI dHash 距离 **30 ≥ 5**。这些是图像外观和审核事实，**不证明独立按快门来源或背景采集独立性**。用户明确没有批准这些采集事实。`background_id` 只描述可见背景，私有 `background_independence` 仍为 unknown。

按照原 `independent_pair` 规则，三张参考均因 capture_id 未知而不具完整资格；目标对不通过，rival 控制也不可用。程序先返回 `insufficient_independent_references`，该首个失败理由并不意味着 rival 已通过。详见 [qualification.public.json](evidence/vision-r1-watercup-20261026/qualification.public.json)。

这里冻结的是**诊断输入快照**及其哈希，不是“已完成独立参考登记”。未知批次本身不要求编造时间；需要的是可信的独立原始拍摄来源及可区分的拍摄记录，不能从不同视角反推补写 capture_id。

## 4. 实际执行及计数

| 项目 | 单参考 ORB | 多参考 ORB 共识 |
|---|---:|---:|
| 场景记录 | 10 | 10 |
| 方法 `executed=true` | 10 | 0 |
| UNKNOWN | 10 | 10（未执行） |
| 实验接受 | 0 | 0（不能当成功拒识） |
| 返回框 | 全 null | 全 null |
| 已确认正 / 负标签 | 0 / 0 | 0 / 0 |
| precision / recall / FPR / IoU | 均未定义 | 均未定义 / 未执行 |

原 runner 在资格门之前保留逐参考诊断，所以每场景仍实际调用两个目标参考及一个 rival matcher。两种方法行共享这些结果：**20 方法行不是 60 次独立推理**。每轮共 30 次调用，30 次解码成功，但只有 12 次进入几何计算；6 次在整图清晰度门早退，另外 12 次因匹配不足或无匹配停止。底层结果为 23 SUSPECTED、7 UNKNOWN、0 FOUND；多参考聚合从未越过资格门。

review-01 后的第一次诊断与 ROI 审核后的 `run-reviewed-02` 各执行一次。两次原图、ROI、阈值及标签均相同；审核元数据变化没有改变 20 行语义结果和 30 次诊断指标，耗时不要求相同。两轮不能当两批独立样本，也不累加为 20 个独立场景。[comparison.public.json](evidence/vision-r1-watercup-20261026/comparison.public.json) 保存复核结论。

计时为本机 CPU 实测。第二轮场景总耗时累计 8771.907 ms，包含三个参考调用及场景读取等开销；它由单参考和多参考方法行共享，不能据此比较两种方法的速度。逐参考耗时累计 8200.273 ms，登记耗时另列于原摘要。

## 5. 逐场景诊断

下表每个参考单元为“匹配数 / 几何内点数；拒识原因”。D=匹配不足，G=内点数或内点率不足，C=参考覆盖过于局部，Q=整图清晰度不足，N=无有效匹配。几何未执行时内点计数 0 是诊断初始化值，不代表完成了几何计算。

所有场景标签在评分文件中仍为 uncertain，所有实际检测框均为 null。负责人给出的 4 个出现候选、5 个缺席候选及 1 个困难样本只是私有标注草案，不是正式真值。尤其参考 rival 图没有再次充当搜索场景。

| 场景别名 | reference_01（单参考基线） | reference_02 | reference_03（rival） | 三参考共用场景耗时 ms |
|---|---|---|---|---:|
| scene_01 | 36 / 18；G | 62 / 36；C | 28 / 5；G | 963.210 |
| scene_02 | 5 / 0；D | 5 / 0；D | 11 / 0；D | 903.725 |
| scene_03 | 12 / 4；G | 13 / 5；G | 16 / 4；G | 933.062 |
| scene_04 | 0 / 0；Q | 0 / 0；Q | 0 / 0；Q | 550.557 |
| scene_05 | 0 / 0；Q | 0 / 0；Q | 0 / 0；Q | 474.791 |
| scene_06 | 9 / 0；D | 8 / 0；D | 12 / 2；G | 992.824 |
| scene_07 | 0 / 0；N | 4 / 0；D | 4 / 0；D | 958.651 |
| scene_08 | 6 / 0；D | 9 / 0；D | 104 / 35；G | 922.630 |
| scene_09 | 4 / 0；D | 22 / 5；G | 20 / 5；G | 957.814 |
| scene_10 | 6 / 0；D | 22 / 7；G | 30 / 5；G | 1114.643 |

每次底层状态、清晰度、关键点、匹配、内点率、参考覆盖率、独立耗时和拒识原因见 [attempts.public.json](evidence/vision-r1-watercup-20261026/attempts.public.json)。每个场景的两方法执行状态、参数和源码 SHA256 见未经改写的 [summary.public.json](evidence/vision-r1-watercup-20261026/summary.public.json)；原命令输出见 [run.log](evidence/vision-r1-watercup-20261026/run.log)。

原评分器在没有确定正例的集合上可能写出 `localization_truth_complete=true`，单参考 `instance_localization.status=SCORED`；这是空集合上的程序字段，不代表标注齐全。有效已确认正负例分母均为 0，指标均 null，本报告不把这些字段解释为验收通过。

## 6. 失败机制与尚不能得出的结论

30 次去重调用的拒识分布：内点数/率不足 11 次，匹配不足 11 次，整图清晰度不足 6 次，参考覆盖过小 1 次，无有效匹配 1 次。

1. **局部支持不足。** scene_01 的第二目标参考获得 62 个匹配、36 个内点、0.5806 内点率，但参考内点凸包仅覆盖 0.0208，即 2.08%，低于原 10% 门槛。它实际被 `reference_support_too_local` 拒绝；不能把“有 36 内点”表述为完整杯身确认。第一参考内点率 0.5，先被原 0.55 门槛拒绝。
2. **清晰度门提前停止。** scene_04 / scene_05 原尺寸整图清晰度分别为 26.076 / 21.810，低于 30，三参考均未进入特征匹配。该数值同时受纹理和图像内容影响，不足以单独断言相机失焦；本轮没有以裁剪搜索图或降低门槛绕过检查。
3. **匹配数量不等于可靠几何。** scene_08 的 rival 有 104 匹配、35 内点，但内点率仅 0.3365，覆盖 0.086，仍被拒绝。目标参考只有 6 / 9 个匹配。目标和 rival 结果没有混合计分。
4. **遮挡和小目标候选仍不确定。** scene_10 第二参考为 22 匹配、7 内点、0.3182 内点率、0.0136 覆盖。场景身份、可见范围与真值框尚未确认，不能计算定位 IoU，也不能将未执行的多参考结果当漏报率。

开发者目视观察到杯身为曲面、可辨纹理主要集中在标志/图案，部分场景有缩小、斜视和遮挡；这些是解释局部支持和几何失败的待验证假设，不是已经完成的因果消融。没有给无框结果补画“预测框”，没有从场景答案生成检测结果。

本轮没有任何几何接受，因此没有可观察到的已返回错误实例框或背景误接受框；但标签未确认，不能声称“负例零误报率”或“rival 拒识验收通过”。更不能声称多参考已取得正确定位。

相对 R0，本轮有证据支持的是：新增真实杯身 ROI 经过人工审查，三个候选参考可通过原图像质量检查，原检测器在新场景的具体拒识机制可复现。**没有证据支持真实识别能力改善**：数据不同、标签缺失、多参考未执行，也没有独立测试；R0/R1 历史结论不变。

## 7. 复现命令与私有产物

Windows PowerShell，从仓库根目录执行。必须提供负责人本地审查文件；公开仓库不携带私人图片、坐标或标签。新输出目录必须不存在，脚本不会覆盖旧实验。

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
.venv/Scripts/python.exe tools/prepare_watercup_diagnostic.py `
  --data-root local_data/vision_r1_watercup_20261026 `
  --review artifacts/vision-r1-watercup-20261026/review-02/review.private.json `
  --output-dir artifacts/vision-r1-watercup-20261026/draft-02
.venv/Scripts/python.exe tools/evaluate_vision_r1.py `
  --data-root local_data/vision_r1_watercup_20261026 `
  --manifest artifacts/vision-r1-watercup-20261026/draft-02/manifest.draft.private.json `
  --labels artifacts/vision-r1-watercup-20261026/draft-02/labels.private.json `
  --output-dir artifacts/vision-r1-watercup-20261026/run-reviewed-02
```

以上是实际使用的命令；再次复现须改用新的 draft/run 目录。实验版本 `multireference-orb-consensus/1`，Python 3.11.4、OpenCV 4.14.0、NumPy 2.4.6，CPU、seed 0、threads 1。生产参数完整保留：MIN_GOOD_MATCHES=12、MIN_INLIERS=10、MIN_INLIER_RATIO=0.55、MIN_REFERENCE_COVERAGE=0.10、MIN_SHARPNESS=30；多参考 quorum=2、box_iou=0.5、min_dhash_distance=5。没有参数搜索。

本地 ignored 根目录 `artifacts/vision-r1-watercup-20261026/` 保存：

- `audit/`：18 张原图逐图审计、私有联系表、来源复核；
- `review-01/`：检测前固定候选 ROI 与可视化；该历史页保留原始“未批准”标注；
- `review-02/`：负责人后续批准记录及新的审查 JSON；
- `draft-01/`、`draft-02/`：manifest、私有 labels、完整输入哈希、登记资格；后者另有 `diagnostic-freeze.private.json`；
- `run-draft-01/`、`run-reviewed-02/`：原始逐样本预测、详细框字段（本轮均 null）、绑定与原摘要；
- `pytest-reviewed.log/xml`：联合全量回归原输出。

## 8. 测试、隐私和源码审计

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
artifacts/issue-11/agent-env/Scripts/python.exe -m pytest -q `
  --junitxml=artifacts/vision-r1-watercup-20261026/pytest-reviewed.xml
.venv/Scripts/python.exe -m pytest -q tests/test_watercup_preparation.py
git diff --check
git diff --name-status 16915c5
```

全量实际输出：`566 passed, 1 warning in 69.71s`，0 failures/errors/skips。完整 Agent 环境为 Python 3.11.4、OpenCV 4.12.0、NumPy 2.2.6；唯一 warning 为已有 LangChain 弃用提示。照片实验环境另实际运行新增准备器测试：`17 passed in 4.20s`。两环境不同，不把其通过数相加。见 [pytest.log](evidence/vision-r1-watercup-20261026/pytest.log) 和 [regression.public.json](evidence/vision-r1-watercup-20261026/regression.public.json)。

相对 #17 的 344 个原跟踪文件均保留，生产、配置和冻结报告没有修改；新增文件清单和检查结果见 [source-audit.public.json](evidence/vision-r1-watercup-20261026/source-audit.public.json)。公开文件仅含新工具、测试、中文报告及脱敏指标；对实际私人输入哈希、私有实例 ID、ROI 坐标和本地密钥值进行精确扫描，密钥只在内存匹配、不打印。ignored 目录与 PR #15 工作区检查见 [privacy-audit.public.json](evidence/vision-r1-watercup-20261026/privacy-audit.public.json)。

## 9. 验收与下一步

| 验收项 | 结果 |
|---|---|
| 18 张输入审计、原字节不变、真实来源与软件 fixture 分离 | 完成 |
| 三张固定 ROI、参考身份及可比较表面审查 | 负责人已批准；小量背景残留记录 |
| 参考图像质量与目标对 dHash | 通过原门槛 |
| 独立原始拍摄来源与有效 capture_id | BLOCKED；三张均未知 |
| 目标参考对及 rival 完整资格 | BLOCKED |
| 单参考真实运行和逐参考失败诊断 | 已执行；无接受框 |
| 合格多参考共识对照 | 未执行，不计为通过 |
| 场景标签、定位真值和正式误接受评分 | BLOCKED；全部 uncertain，无人工框 |
| 独立真实场景受限 Demo 验收 | 未执行；独立测试数 0 |
| 生产识别能力 | BLOCKED；未集成实验 |

下一步最小输入是可信的三张参考拍摄来源记录；同一批拍摄并非自动不合格，但不同原始快门事件不能靠文件名、角度或 dHash 推断。若来源始终无法确认，本组仍只能用于低层诊断，不能登记成合格独立参考对。

随后需要人工确认场景实例标签和可定位范围。任何补充都生成新的版本，不回填旧输出；通过资格后才报告实际多参考执行及其失败/接受情况。本轮零目标支持说明“补齐元数据”本身不会改变已经观察到的底层匹配，不能承诺多参考因此会成功。

算法和参数冻结之后，另采集两批独立场景：至少 6 正、8 负，每物理实例单独评价；要求至少 5/6 正例正确定位且 IoU≥0.5、8 负例零错误接受、实例 precision≥0.95，零接受时 precision 未定义而非通过。当前既未满足这些前提，也没有达到该验收标准。新 PR 交 PM 审查，不自行合并，不更新比赛提交包。
