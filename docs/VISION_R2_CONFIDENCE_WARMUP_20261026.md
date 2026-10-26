# Vision R2 后续：置信度诊断与单变量 warmup 实验

**结论：旧模型零候选的直接原因是分数低于 0.25，但这不是单纯调整阈值即可解决的校准问题。关闭 warmup 后，分数显著上升，同时出现大量错误位置和背景框，训练集与开发验证集都未达到可靠识别。本轮仍为 NO_GO，生产识别 BLOCKED。**

本任务依据负责人在 PR #20 后追加的合同，关联 Issue #19，不关闭 Issue。基于 PR #20 `bbe8d4a` 创建 `feature/19-vision-r2-confidence-warmup`，作为依赖 PR #20 的 stacked PR 提交，base 为 `feature/19-vision-r2-yolo`。不修改生产 ImageMatcher、SearchCore、Agent、SQLite，不更新旧 R0/R1/R2 报告或历史实拍实验文件。

## 输入、实验顺序和口径

仍为原来18张人工审核实拍：训练11张（8正3负），开发验证7张（4正3负），原图、标注、分组不变。所有照片已经参与探索，**独立测试为0张**。没有用低阈值结果重新选参考、改标签、改分组或调整业务门槛。

先对官方预训练、冻结主干 best.pt、低学习率 best.pt 运行 **3×18×2尺寸×5阈值=540次**真实全图预测；完成后另进程读取人工GT评分并生成绑定门槛。只有该门槛完整、hash一致、额度未占用时，才执行一次新训练。之后对新 best.pt 另跑180次预测与评分。总计720次调用，物理样本仍为18张。

固定诊断阈值为 `0.001 / 0.01 / 0.05 / 0.10 / 0.25`，全图尺寸640/960，NMS IoU=0.7、max_det=100、batch=1、half=False、augment=False，全部类别参与。**业务阈值始终0.25。** 推理入口没有标签参数，不读取GT、不按答案裁图。

每次推理保存全部 NMS 后输出，同时在不改写网络返回值的观察器中复制 NMS 前张量：全部类别的 decoded sigmoid 分数、网络输入坐标与换算回原图的框。原始张量、原图hash、每张图的框/分数/耗时/实际执行状态及评分全部在 ignored 目录。该分数不等于经校准的物理身份概率。

**max_det=100 是旧实验固定上限，未为本轮更改。** 低阈值经常触顶，故NMS后FP是该固定输出策略的实际计数，不是未截断网络候选总数。完整 raw 张量单独保存，不能把触顶后的100框说成所有网络框。正确 raw 框也不是已接受预测；它可能被阈值、类别竞争、NMS或排序上限排除。

## A. 三个旧模型的诊断

640下的 NMS 后结果如下；TP/FP/FN按IoU≥0.5、一对一匹配计算。一个目标附近多出的框仍计FP。所有尺寸、分组和阈值详见 [完整对照CSV](evidence/issue-19-followup/threshold-comparison.csv)。

| 模型 | conf | train TP/FP/FN | dev val TP/FP/FN | 负例有候选 / 6 |
|---|---|---|---|---|
| 官方COCO | .001 | 8/13/0 | 4/22/0 | 5 |
| 官方COCO | .01 | 8/4/0 | 4/9/0 | 4 |
| 官方COCO | .05 | 8/2/0 | 3/7/1 | 3 |
| 官方COCO | .10 | 7/2/1 | 3/7/1 | 3 |
| 官方COCO | .25 | 7/2/1 | 3/3/1 | 2 |
| 冻结主干 | .001 | 8/1092/0 | 4/696/0 | 6 |
| 冻结主干 | .01 | 7/1/1 | 1/3/3 | 3 |
| 冻结主干 | .05 | 0/0/8 | 0/0/4 | 0 |
| 冻结主干 | .10 | 0/0/8 | 0/0/4 | 0 |
| 冻结主干 | .25 | 0/0/8 | 0/0/4 | 0 |
| 低学习率 | .001 | 8/1092/0 | 3/697/1 | 6 |
| 低学习率 | .01 | 8/1080/0 | 1/687/3 | 6 |
| 低学习率 | .05 | 3/0/5 | 0/1/4 | 1 |
| 低学习率 | .10 | 0/0/8 | 0/0/4 | 0 |
| 低学习率 | .25 | 0/0/8 | 0/0/4 | 0 |

640/.001 时两个微调模型在全部18图触及100框上限。960/.001 时，冻结组 NMS 后正确定位10/12、低学习率组12/12，但均伴随大量FP；不能据此换阈值宣称通过。COCO 的卡通杯/玻璃杯 cup 检测是正确类别候选，却是错误 SONY 目标候选；这里不是 COCO 类别精确率或物理实例验收。

| 旧模型 / 尺寸 | 正例上最高目标分数范围 | 负例上最高目标分数范围 | 具有 IoU≥.5 且分数>.001 的 raw 框的正例 |
|---|---|---|---|
| 冻结 / 640 | .00932–.01423 | .00863–.01218 | 12/12 |
| 冻结 / 960 | .00963–.01326 | .00882–.01255 | 12/12 |
| 微调 / 640 | .01337–.06476 | .01237–.06010 | 12/12 |
| 微调 / 960 | .01747–.04988 | .01246–.02448 | 12/12 |

这支持以下限定结论：旧微调模型保留了一些定位能力，0.25筛掉了全部分数；但正负例分数大量重叠，正确位置未总排在前列，降低阈值会放出大量错误框。因此“只是门槛太高”不足以解释可用性失败。每张正例的最高候选、其IoU、最高正确低分框与raw最佳IoU，以及负例候选分布，都保存于私有 `scores.private.json`。

本轮三个旧模型在0.25下共108次预测的目标框、类别与confidence，**逐项与PR #20历史输出完全相同**，不只是总指标相似；见 [重现核验](evidence/issue-19-followup/business-threshold-reproduction.json)。

## B. 一次受控训练

环境与之前一致：Windows / Python3.11.4 / GTX1660 6GB，PyTorch2.6.0+cu124、torchvision0.21.0+cu124、Ultralytics8.3.221、CUDA12.4。官方 YOLO11n 权重 SHA256 仍为 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`，未随机初始化整网。

新工具不改旧 `TRIALS`，不更改或重跑旧两组实验。它读取冻结 low-lr 的全部 arguments，验证版本、预训练hash、审核数据绑定、完整540次诊断及评分，使用固定输出目录和固定的原子创建额度文件。没有输出目录、epoch或模型覆盖参数，换目录不能获得第二次额度。额度已经占用，本轮不能重跑训练。

安装源码实际逻辑为：`nw=max(round(warmup_epochs*nb),100)`，但仅在warmup_epochs>0时使用；设为0则nw=-1，`ni<=nw`不会进入warmup。源码hash被记录。训练启动时再次核对框架解析后的完整参数，除存储路径外，**唯一差异是 warmup_epochs:1.0→0.0**。

不变参数包括 batch2、AdamW、lr0=.001、freeze0、nbs2、warmup_bias_lr=.001、seed19、imgsz640、patience10、最多50轮；增强、训练/验证组、val默认阈值与NMS也不变。JPEG工作副本与旧low-lr训练实际使用的副本逐张字节一致，原图与审核导出不变。

| 项目 | 实际结果 |
|---|---|
| 训练时源码提交 | `1bcc2aa` |
| 完成轮数 / best epoch | 11 / 1，因后续10轮无提升早停 |
| 真实 optimizer.step | **66**，每轮6次，由PyTorch step post-hook记录 |
| 第1步三组lr | [.001, .001, .001] |
| 第66步三组lr | [.000802, .000802, .000802] |
| 驱动总耗时 | 53.002秒；不是与历史运行的严格性能对照 |
| GPU peak allocated / reserved | 738,849,280 / 851,443,712 bytes，PyTorch口径 |
| best.pt SHA256 | `1216bb5e89ce2a20f543a060696d7b1140916e10f848e2294ca5d134eda8d914` |
| last.pt SHA256 | `568a323c39b5cf04758fbc0a67b5357e32d4ae0073f2a343352c61aa2811cb40` |

[每步学习率](evidence/issue-19-followup/optimizer-steps.csv)、[逐轮loss](evidence/issue-19-followup/training-epochs.csv)、[实际曲线](evidence/issue-19-followup/training-loss.png) 和 [训练参数证据](evidence/issue-19-followup/controlled-training.json) 可核对。旧实验没有记录实际step hook，不把推导的历史batch数冒充历史实际optimizer步数。

## C. 新模型结果及因果边界

先看固定业务门槛0.25：

| 尺寸 / 分组 | TP / FP / FN | 定位recall | 候选precision | 负例有候选 |
|---|---|---|---|---|
| 640 train | 1 / 71 / 7 | 12.50% | 1.39% | 0/3 |
| 640 dev val | 0 / 100 / 4 | 0% | 0% | 1/3 |
| 640 all | 1 / 171 / 11 | 8.33% | 0.58% | 1/6 |
| 960 train | 3 / 262 / 5 | 37.50% | 1.13% | 1/3 |
| 960 dev val | 1 / 247 / 3 | 25.00% | 0.40% | 1/3 |
| 960 all | 4 / 509 / 8 | 33.33% | 0.78% | 2/6 |

960/.25有2张图触及100框上限，FP统计仅为实际输出框。检测分数明显变高，但正确定位没有相应稳定：640正例最高分可到.9403，负例可到.9202；960分别到.9267和.8733。高分不能代表正确位置或目标身份。

640下新模型的完整阈值对照：

| conf | train TP/FP/FN | dev val TP/FP/FN | 负例有候选 / 6 |
|---|---|---|---|
| .001 | 7/1093/1 | 1/699/3 | 6 |
| .01 | 7/1093/1 | 1/699/3 | 6 |
| .05 | 7/507/1 | 1/315/3 | 5 |
| .10 | 4/305/4 | 1/199/3 | 3 |
| .25 | 1/71/7 | 0/100/4 | 1 |

逐图覆盖图检查发现大量大框或网格状背景框，错框覆盖桌面、屏幕边缘、饮水机等；这不是仅在“相似杯区分”上的失败。在饮水机上远处目标，两尺寸的raw最佳IoU分别约.416/.463，连不经阈值筛选的raw定位也未达.5。多数其他正例raw中仍有较低分的合格框，但最高分框经常落在错误位置。私有审查页保留全部成功、漏检和误报，不挑选样例。

**本次单变量实验支持warmup对当前小数据训练过程有明显影响，但不支持“关闭warmup就能修好模型”。** 在固定seed和本数据上，它提高了输出分数，却伴随更差的定位稳定性和大量错误接受；没有重复seed或独立测试，不能扩展为所有warmup设置的普遍结论。实际训练长度和best epoch随早停发生变化，是本次配置的结果，不是另行调整参数。

## 训练集失败后的进一步核查

1. **标注/坐标**：审核图像与标签hash保持一致，全部类别ID为0。8个train正例和4个val正例各有一个审核框，归一化框面积分别为图像面积的4.73%–30.61%和1.65%–15.97%。复制/重编码后尺寸与方向不变，没有发现路径、split、类别ID或坐标单位错误。该核查不能替代对标注语义的独立复审。
2. **类别头迁移**：checkpoint shape审计与训练日志一致，499项中448项形状兼容，51项不兼容均位于 `model.23.cv3` 分类支路。80类改1类不仅改变最后输出维度，也使该支路部分中间宽度从80变64；例如末端卷积由 `[80,80,1,1]` 变为 `[1,64,1,1]`。因此不能假设原cup分类器完整保留。证据是结构与日志，不是已证明的唯一失败原因。
3. **优化轨迹**：实际执行了66次AdamW更新，没有漏跑优化器；关闭warmup后第一轮就出现高验证loss（box约3.60、cls约22.28、dfl约8.34），其后未稳定改善，最佳模型停留在第一轮。直接对全网用.001与小batch/小数据的组合仍可能过于激进，但本轮没有改学习率、冻结层、BN模式或再训练来验证该假设。

新模型训练集也未学稳，故当前主要问题不是已证明的“训练很好、只在新背景泛化失败”。定位本身和背景抑制仍不足，也尚未达到“定位好、仅相似杯误检”的条件。按合同停止本轮训练，不堆叠更多专用训练配置。下一步建议PM先审查分类支路迁移/初始化与优化稳定性；若采用通用cup定位+冻结实例特征检索，应作为新的独立验证，保留正确定位/错误实例/背景的分项验收，不能直接接生产。

## 工程、证据与运行方式

新增 `diagnose_vision_r2_confidence.py`、`score_vision_r2_confidence.py`、`train_vision_r2_nowarmup.py`，旧生产及旧实验runner不变。补充数据网格、分数分布、raw IoU、单变量约束和一次额度测试。修复一个既有测试导入问题：旧数据测试直接替换 `sys.modules` 导致两份不同的Blocked异常类；改为共享正常导入，不删除或放宽任何原有断言。这不影响已执行的独立CLI实验。

最终联合回归、隐私与历史文件校验见 [证据索引](evidence/issue-19-followup/README.md)。原图/标签、720份raw NPZ、全部预测JSON、逐图评分、288张低阈值/业务阈值覆盖图、训练权重、完整日志和含图页面均保留本地ignored目录；公共PR仅源码、聚合指标、数值曲线和脱敏日志。

```powershell
$py = 'artifacts/issue-10/neural-env/Scripts/python.exe'
$old = 'artifacts/vision-r2-issue19'
$r = 'artifacts/vision-r2-followup'
$data = 'local_data/vision_r1_watercup_20261026'

# 三个模型各执行一次；脚本内部逐次执行18×2×5组合。
& $py tools/diagnose_vision_r2_confidence.py --weights "$old/weights/yolo11n.pt" --model-id pretrained --data-root $data --output-dir "$r/pretrained"
& $py tools/diagnose_vision_r2_confidence.py --weights "$old/trials-02/freeze-backbone/training/weights/best.pt" --model-id freeze-backbone --data-root $data --output-dir "$r/freeze-backbone"
& $py tools/diagnose_vision_r2_confidence.py --weights "$old/trials-02/low-lr-finetune/training/weights/best.pt" --model-id low-lr-finetune --data-root $data --output-dir "$r/low-lr-finetune"
& $py tools/score_vision_r2_confidence.py --diagnostics "$r/pretrained" "$r/freeze-backbone" "$r/low-lr-finetune" --annotations "$old/annotation-reviewed-02/annotations.private.json" --data-root $data --output-dir "$r/phase-a-scores" --phase-a-gate

# 本轮实际已执行一次。重复运行会被固定额度/输出目录拒绝。
$gate = (Get-FileHash "$r/phase-a-scores/phase-a-gate.private.json" -Algorithm SHA256).Hash.ToLower()
& $py tools/train_vision_r2_nowarmup.py --diagnostic-gate "$r/phase-a-scores/phase-a-gate.private.json" --gate-sha256 $gate
& $py tools/diagnose_vision_r2_confidence.py --weights "$r/nowarmup/training/weights/best.pt" --model-id no-warmup --data-root $data --output-dir "$r/no-warmup-inference"
& $py tools/score_vision_r2_confidence.py --diagnostics "$r/no-warmup-inference" --annotations "$old/annotation-reviewed-02/annotations.private.json" --data-root $data --output-dir "$r/phase-c-scores"

$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& artifacts/issue-11/agent-env/Scripts/python.exe -m pytest -q --junitxml=artifacts/vision-r2-followup/pytest-final.xml
git diff --check
```

所有输出拒绝覆盖，历史记录保留；不通过删除额度文件或换目录绕过一次授权。公共clone没有私人数据，不能冒充复现实拍。需要核对原图时，负责人打开本地 `artifacts/vision-r2-followup/review-confidence.private.html`。

本PR可供PM审查实验工程和结论，但**不能作为识别验收通过、Issue #19关闭或生产FOUND接入依据**。受限的6正8负独立验证尚未执行，家庭实例识别仍BLOCKED。
