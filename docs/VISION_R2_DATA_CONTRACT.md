# Vision R2 私有标注与运行合同

本文件对应 Issue #19 的隔离实验，生产视觉、SearchCore、Agent 和 SQLite 均不改变。当前真实实验结论见 [R2 报告](VISION_R2_YOLO_20261026.md)。本合同不是已通过独立识别验收的声明。

## 输入与人工审核

原图、标注、导出数据集、权重、推理图和运行目录必须位于仓库内的 Git ignored 目录。数据缺失直接失败，不回退其他图片。原图 SHA256 在准备前后及训练后核对。训练目录中多余图片、标签、改框后重算导出 hash、与原图不同的副本均拒绝。

私有 JSON 由 `tools/vision_r2_data.py::validate_manifest` 校验，字段如下：

| 字段 | 约定 |
|---|---|
| `schema_version` | 整数 `1` |
| `class_name` | 本轮唯一类别 `sony_mug`，表示目标外观，不保证物理实例唯一性 |
| `purpose` | `exploratory_fit`；不得填写为独立测试 |
| `source_type` | 实拍为 `real_team_photo`；测试 fixture 为 `synthetic_software_fixture`，后者禁止实际训练 |
| `split_review` | `confirmed: true`、审核者 `reviewer`、来源 `source`；记录负责人授权开发者按场景分组的原始回复 |
| `images[]` | 完整图片清单，包含排除项 |
| `sample_id` / `path` / `sha256` | 唯一脱敏 ID、相对原图根目录路径、完整原图 hash；不得公开真实标注记录 |
| `split` | `train` / `val` / `excluded`，不随机拆近邻图 |
| `group_id` | 已核对的可见场景/近重复分组，同组不能跨 split；不是伪造的 capture_id |
| `label` / `label_review` | `present` / `absent` / `uncertain`；纳入训练/验证的标签必须明确经人工确认 |
| `boxes[]` | 原图像素 `xyxy`、`bbox_scope: full_visible_object` 和独立 `review` 来源；覆盖可见杯身及把手 |
| 审核补充元数据 | 私有 manifest 可记录身份确认、拍摄批次等；未知保持 unknown，程序不补造 |

`review` 结构与 `split_review` 相同。参考图的旧 ROI 审核不替代检测框审核。候选框先由人工查看原图拟定，再展示给负责人审核；不得把预测框复制成 Ground Truth。`uncertain` 必须 `excluded`，缺席图的 boxes 必须为空。EXIF 非正常旋转的图片会被阻止，须另行审核坐标归一化，不能静默旋转后沿用原坐标。

输出标准 YOLO Detection 目录：`images/train`、`images/val`、`labels/train`、`labels/val` 与 `data.yaml`。标签每行 `0 center_x center_y width height`，按原图尺寸归一化；负例 `.txt` 为空。`annotation.private.json` 与 `prepared.private.json` 绑定人工审核、原始 hash、导出文件 hash 和分组。

## 训练与推理隔离

- 模型必须为已下载并核对 hash 的官方 COCO YOLO11n 检测权重；读取权重后再确认 80 类及 cup 类。实际训练严格使用真实照片，不接受软件 fixture 冒充实拍。
- 本轮只有 `freeze-backbone` 和 `low-lr-finetune` 两组命名配置，上限 50 epochs。已有输出目录拒绝覆盖；不得通过更换目录绕过两次实际训练上限。历史的零 epoch 启动失败单独记录。
- 固定增强只在框架 train loader 内执行。`val` 参与早停和 best.pt 选择，是开发数据。独立测试必须在参数冻结后另采，不能从这批数据重新拆分获得。
- 框架可能修复 JPEG：训练在隔离 `working-dataset` 副本进行，记录副本变化；审核导出与原图不可改写。发现标签变化直接失败。首次真实训练发生在该修复前，具体差异如实保留在报告中。
- 训练禁止联网，关闭外部实验追踪；不发送私有图片。模型和字体在本地准备。原始训练日志、batch 可视化和 labels 图均私有。
- `vision_r2_infer.py` 只接受本轮全部 18 张原图，固定全图 640/960、confidence 0.25、NMS IoU 0.7。它不读取标签，不按答案裁图，不输出生产 FOUND。
- `score_vision_r2.py` 在推理完成后读取人工标签，使用 IoU ≥ 0.5、按预测置信度一对一匹配。重复候选计 FP、漏检计 FN；实际执行但零框不是缺失输入，precision 为 null。空文件、漏图、重复图、未执行和 hash 不符拒绝评分。

## 公私证据边界

私有逐图 JSON 保存原图 hash、尺寸、所有 bbox、confidence、执行状态、耗时、显存、来源、拒绝原因和评分 IoU。公开部分只发布聚合指标、无照片的 loss 图/数值日志、源码版本、模型 hash 与软件测试结果，不发布原图、私有 GT、详细输入路径或数据库。

软件 fixture 仅检验数据/评分合同，不能用来证明真实图像识别。新模型只有完成独立真实验证并通过 PM 审核后才能考虑独立 adapter；LLM、类别候选或模型 confidence 均不直接决定 FOUND。
