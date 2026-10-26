# Issue #19 实际执行证据

本目录只含公开聚合指标与纯数值/软件证据。原始照片、人工标签、逐图坐标、来源映射、原始日志及权重只保存在 ignored 本地目录。没有模拟训练数据计入真实评价。

最终同一工作区联合回归：**470 passed，0失败，0跳过，82.62秒**；424项main原有测试保留，新增46项。仅有原有 LangChain PendingDeprecationWarning。不是把其他未合并分支的测试数相加。

- [实验报告与命令](../../VISION_R2_YOLO_20261026.md)
- [108 次原图推理聚合结果](inference-metrics.json)：3个模型、18张实拍、640/960；实际物理样本只有18张。
- [两组训练配置、版本、权重 hash、耗时与显存](training-summary.json)
- [原图与框架工作副本完整性审计](data-integrity.json)
- 冻结主干：[逐轮数值](freeze-backbone-epochs.csv)、[实际日志摘录](freeze-backbone-training-excerpt.txt)、[loss曲线](freeze-backbone-loss.png)。
- 全网微调：[逐轮数值](low-lr-finetune-epochs.csv)、[实际日志摘录](low-lr-finetune-training-excerpt.txt)、[loss曲线](low-lr-finetune-loss.png)。
- [框架调度与验证阈值核验](framework-diagnosis.json)：由安装源码推导，不是额外训练。
- [最终联合回归日志](pytest.txt)、[源码与隐私审计](audit.json)。

训练框架的低阈值 mAP 不代替固定 confidence=0.25 的推理结果；两组 best.pt 后者均零框，结论 NO_GO。旧 R0/R1/YOLOE 报告不变，未接入生产。

私有目录索引（均在 `artifacts/vision-r2-issue19/`）：

| 目录 | 内容 |
|---|---|
| `annotation-review-01` | 推理前人工框草稿、全部原图框审查页 |
| `annotation-reviewed-02` | 负责人回复与最终私有标注 |
| `dataset-01` | 第一组真实训练用导出；JPEG副本被框架重编码，保留现场 |
| `dataset-02` | 第二次准备的未改字节审核导出 |
| `gate-a-01` / `gate-a-score-01` | 预训练逐图真实框/分数/IoU/失败原因 |
| `trials-01` | 第一次CUDA初始化失败，0epoch |
| `trials-02` | 两组真实训练配置、日志记录、权重、私有batch图；第二组隔离工作副本 |
| `freeze-infer-01` / `freeze-score-01` | 第一组best的全部36次推理及评分 |
| `finetune-infer-01` / `finetune-score-01` | 第二组best的全部36次推理及评分 |

所有推理照片保存，不因零检测而省略。私有 `predictions.private.json` 的 `human_localization_review: pending` 是推理当时记录；后续人工GT评分单独写入 `scores.private.json`，不覆写冻结推理文件。

本地总览页为 `artifacts/vision-r2-issue19/review-results.private.html`，列出全部108次实际执行及人工GT评分，并展示包括零框在内的每张结果图。公开仓库没有这份含私人照片的页面。
