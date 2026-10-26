# Vision R2 后续真实证据

[中文报告及实际命令](../../VISION_R2_CONFIDENCE_WARMUP_20261026.md)。所有结果来自同一18张开发实拍，独立测试0张，业务confidence固定.25。只执行一次额外训练，无生产接入。

最终联合回归 **499 passed，0失败，0跳过，77.41秒**，保留PR #20的470项并新增29项；只有原有LangChain弃用警告。历史实验393个文件及18张原图hash不变，旧报告、生产代码和原两次训练保护不变。唯一修改的既有文件是测试导入方式。

- [四模型全部阈值与分组对照](threshold-comparison.csv)：含FP、FN、负例图数、100框上限触顶与raw正确框覆盖。
- 完整聚合与分数分布：[官方预训练](pretrained-metrics.json)、[旧冻结组](freeze-backbone-metrics.json)、[旧微调组](low-lr-finetune-metrics.json)、[新无warmup组](no-warmup-metrics.json)。
- [720次诊断执行、版本与模型hash](diagnostic-execution.json)、[旧0.25逐框精确重现](business-threshold-reproduction.json)。
- [单变量训练证据](controlled-training.json)、[66步实际学习率](optimizer-steps.csv)、[11轮记录](training-epochs.csv)、[实际曲线](training-loss.png)、[真实日志摘录](training-excerpt.txt)。
- [类别头形状与标签检查](head-and-label-audit.json)：不含原图或GT框坐标。
- [联合回归日志](pytest.txt)、[历史保护与隐私审计](audit.json)。

公开文件不含原图、原图SHA256、私有标注、预测框坐标、模型权重或API Key。唯一公开PNG为无照片的loss曲线。原始输入与完整逐图结果、每张正例最高分及IoU、低置信度正确框、负例分数和错误框均留在ignored目录。

本地目录 `artifacts/vision-r2-followup/`：三个旧模型各自的目录保存阶段A；`phase-a-scores`保存事后评分和训练前完成门槛；固定 `controlled-training-attempt.json`保留一次额度；`nowarmup`保存唯一训练；`no-warmup-inference`、`phase-c-scores`保存阶段C；`review-confidence.private.html`提供全部照片及阈值的私有审查页。

最初全量测试出现6项异常类型断言失败，原因是旧测试在收集时替换同名模块，导致两个Blocked类。修复测试导入后重跑完整套件；不修改拒绝逻辑，不删原断言，最初日志仍在私有目录。最终测试结果以本目录pytest.txt为准，不能用软件通过代替识别结果。
