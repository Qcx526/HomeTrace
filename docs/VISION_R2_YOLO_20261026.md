# Vision R2：YOLO11n 真实水杯候选与两组迁移训练（2026-10-26）

**结论：Gate A 的通用 cup 候选定位可继续研究；本轮两组专用模型均 NO_GO，家庭实例识别与生产接入仍 BLOCKED。** 官方预训练模型在两个固定分辨率下均定位了 12 张正例中的 10 张，但不能区分 SONY 杯与卡通杯。两组微调 best.pt 在固定 confidence=0.25 下，对全部 18 张原图均输出零目标框。没有降低阈值、追加第三组训练、生成 FOUND 或接入生产。

这是 [Issue #19](https://github.com/Qcx526/HomeTrace/issues/19) 的真实 GPU 实验，不是预测训练效果的方案文档。基线为 main `4429fcf21797d6af05d189effdd510918315acc4`，独立分支 `feature/19-vision-r2-yolo`，不依赖 PR #16/#17/#18，不改 PR #15，不覆盖历史报告。未合并任何 PR，未整理或提交比赛包。

## A. 输入与运行环境

输入为负责人本地水杯包的全部 18 张原始 JPEG。负责人审核了展示的检测标注，并补充确认原先不确定的多视图与饮水机上方目标为正例。最终 **12 正例、6 负例、0 uncertain**。原始逐图映射、审核原话、坐标和 SHA256 只在本地保留，模型推理不接收这些标签。

开发划分按可见场景分组：训练 11 张（8 正、3 负），开发验证 7 张（4 正、3 负）。参考背景/木桌/杂物桌用于训练，电脑桌/饮水机场景用于开发验证；分组不跨 split，未随机拆近重复图。**实际采集批次和时间未知，不能证明拍摄批次独立。** 本批照片全用于探索，验证组也用于 early stopping / best.pt 选择；独立测试样本数为 0。

| 环境 | 实测 |
|---|---|
| 系统 / Python | Windows 10 build 19045 / 3.11.4 |
| GPU / 显存 / 驱动 | GTX 1660 / 6144 MiB / 551.61 |
| PyTorch / torchvision | 2.6.0+cu124 / 0.21.0+cu124 |
| CUDA / cuDNN | CUDA 可用，runtime 12.4 / 90100，设备 sm75 在本 wheel 支持列表内 |
| Ultralytics | 8.3.221，独立可选环境 |
| OpenCV / NumPy / Pillow | 4.14.0.94 / 2.4.6 / 13.0.0 |
| 模型 | 官方 COCO YOLO11n，5,613,764 bytes |
| 预训练权重 SHA256 | `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1` |

按合同先审查 YOLO26n：已安装版本没有 YOLO26 配置/模块/资产名支持，故采用获授权的 YOLO11n 回退，没有升级 CUDA。权重来自 [Ultralytics 官方资产](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt)，模型/API 依据 [官方模型文档](https://docs.ultralytics.com/models/yolo26/) 和 [推理接口](https://docs.ultralytics.com/modes/predict/)。本地包声明 AGPL-3.0；分发集成或权重前须核对 [Ultralytics 许可证](https://www.ultralytics.com/license) 的适用义务，本 PR 不分发权重，也不作商业授权判断。

## B. 实际执行与产物

新增四个隔离工具：`vision_r2_data.py` 审核并导出 YOLO 数据集；`train_vision_r2.py` 执行两组 GPU 迁移训练；`vision_r2_infer.py` 对全部原图执行全图推理；`score_vision_r2.py` 事后对人工标签评分。[数据合同](VISION_R2_DATA_CONTRACT.md) 描述字段与拒绝规则。

实际产生两套 best/last/逐轮权重、args.yaml、训练日志、loss 曲线、32 轮 epoch 记录，以及 **3 个模型 × 18 原图 × 2 分辨率 = 108 条全图预测与 108 张可视化**。零候选图也保存，不挑选成功图。每条私有记录包含原始 hash、bbox、confidence、时间、显存及失败原因；同一照片重复推理不增加真实样本数。

Gate A 在工具首次提交前运行，元数据如实记录 `source_worktree_dirty=true`、当时 HEAD 与脚本 SHA256，不把它写成干净提交上的实验。两组训练分别记录表中源码 commit 和驱动 hash。最终校验修复后只重新评分已有预测、检查输入并运行软件回归，没有再训练模型，三组评分与原结果完全相同。

公共 [证据目录](evidence/issue-19/README.md) 仅保留脱敏聚合 JSON、纯数值 CSV、无照片 loss 图、真实训练日志摘录和测试日志。全部逐图照片、人工标签、详细证据、模型权重在 ignored `artifacts/vision-r2-issue19/`。本次没有导航、机器人动作或 Agent 调用；所有检测和训练由真实程序执行，软件测试生成图仅检验代码。

## C. Gate A：预训练全图候选

固定 `conf=0.25, iou=0.7, device=0, half=False`，比较 `imgsz=640/960`，未使用切片或已知框裁图。IoU≥0.5 才计正确定位；按置信度一对一匹配，多余框计 FP。

下表评估的是“将 cup 候选当作 SONY 目标候选”的定位结果。卡通杯被 COCO 检测成 cup 是正确类别检测，但属于错误的 SONY 目标候选；不能把本表称为 COCO 类别精确率，也不能称为物理实例精确率。

| 模型 / 分辨率 | 组别 | TP / FP / FN | 目标候选 precision | 定位 recall | 有错误候选的负例图 |
|---|---|---|---|---|---|
| COCO / 640 | train 8正3负 | 7 / 2 / 1 | 77.78% | 87.50% | 1/3 |
| COCO / 640 | dev val 4正3负 | 3 / 3 / 1 | 50.00% | 75.00% | 1/3 |
| COCO / 640 | 全部 12正6负 | 10 / 5 / 2 | 66.67% | 83.33% | 2/6 |
| COCO / 960 | train 8正3负 | 7 / 2 / 1 | 77.78% | 87.50% | 1/3 |
| COCO / 960 | dev val 4正3负 | 3 / 4 / 1 | 42.86% | 75.00% | 1/3 |
| COCO / 960 | 全部 12正6负 | 10 / 6 / 2 | 62.50% | 83.33% | 2/6 |

具体失败机制已对全部 Gate A 覆盖图逐张检查：

- 普通前视杯身能产生正确框；640 漏俯视杯，960 修复该例，却漏掉另一个把手朝前视角，净召回没有提高。
- 饮水机上远处 SONY 杯两种尺寸均漏检；同图的卡通杯仍产生候选，960 还出现卡通杯重叠候选。
- 单独卡通杯和桌面卡通杯均被当作 cup，不具备目标实例区分力。木桌上的玻璃杯也会增加错误 SONY 候选。
- 一张目标存在图中的纸巾包装被错误框成 cup。这是真实类别误候选，不能只把误差归因于“所有杯子都像”。
- 空木桌没有 cup 候选；6 张负例中另外 4 张没有目标类别候选。样本很少，不据此宣称背景问题普遍解决。

## D. Gate C / D：两组真实迁移训练结果

两组均从同一官方预训练权重开始，实际日志为 `Transferred 448/499 items from pretrained weights`。80 类变为单类导致部分检测头参数不匹配，不能说整个网络随机初始化，也不能说所有类别参数都被完整迁移。

共同配置：`imgsz=640, batch=2, epochs<=50, patience=10, seed=19, deterministic=True, workers=0, amp=False`。train 内有限 HSV/旋转/平移/尺度增强，mosaic/mixup/翻转等关闭；没有增强验证照片。

| 项目 | 冻结主干 | 小学习率全网微调 |
|---|---|---|
| 运行时源码 | `a613ff4` | `7bb0c52` |
| freeze / optimizer / lr0 | 10 / SGD / 0.01 | 0 / AdamW / 0.001 |
| nbs / warmup_epochs / warmup_bias_lr | 64 / 3 / 0.1 | 2 / 1 / 0.001 |
| 实际训练轮数 / best epoch | 17 / 7 | 15 / 5 |
| 训练驱动总耗时 | 68.111 s | 76.939 s |
| PyTorch 峰值 allocated | 467,044,864 bytes | 802,392,576 bytes |
| best epoch 框架 mAP50 / mAP50-95 | 0.12617 / 0.10133 | 0.24741 / 0.24655 |
| best.pt，640 和 960 原图推理 | 两者均零目标框 | 两者均零目标框 |
| 全部图片 TP / FP / FN | 0 / 0 / 12 | 0 / 0 / 12 |
| train / dev val 定位 recall | 0% / 0% | 0% / 0% |
| precision / 负例候选图 | 未定义 / 0/6 | 未定义 / 0/6 |
| 结论 | NO_GO | NO_GO |

两组是不同小数据训练方案，改变了多个因素，**不是单变量消融**。两次启动前失败分别为未初始化 CUDA 就重置显存统计、第一组框架修复 JPEG 副本导致数据 hash 校验失败，均 0 epoch，保留日志，不计为额外训练。修复后仅执行上述两组真实训练。

best.pt SHA256 分别为：

- 冻结：`300df186b6fab35d5dee40f8ad7c48b06614f110cf1a04071389611fa3bc3bce`
- 微调：`75b390f89068a9815c765fcf04566944c0ffb3cdcd53f48f77d2c52faa836591`

框架 val 使用本版本默认候选阈值 0.001 计算 PR/mAP，本轮业务推理固定 0.25。**框架 mAP 非零与业务零检测不矛盾**，不能拿低阈值评估数字代替可演示结果。没有为了让报告出现框而下调推理阈值。

## E. 失败诊断与数据完整性

已核实的问题：本版本 trainer 的有效 warmup 为 `max(round(warmup_epochs * batches_per_epoch), 100)`。每轮仅 6 batch，冻结组 102 batch 几乎全在 warmup，微调组 90 batch 全在 warmup。`warmup_epochs=1` 没有实现预期的一轮 warmup；实际每轮 lr 已保存。第一组 nbs=64 还带来梯度累积，第二组 nbs=2 已消除该因素，但仍全部拒检。

第二组训练/验证分类 loss 未形成稳定低值，验证分类 loss 从约 4.3 升至 13.0，best 很早出现。**小数据、单类头迁移、warmup/早停相互作用是有依据的待验证原因，尚不能把某一项认定为唯一因果。** 没有通过第三次训练确认修正调度能解决问题；也不能因 train 图全失败就断言已学会背景或已泛化。过拟合背景的风险仍需同背景有/无目标配对照片检验。

另发现全部 JPEG 的末尾两个字节不是 EOI，触发框架 `corrupt JPEG restored and saved` 逻辑。原图正常解码，该日志不能直接证明用户照片内容损坏。第一组改变了 dataset-01 的训练副本；第二组改为专门 working-dataset，保留审核导出不变。最终审计确认：

- 原始 18 张照片 hash 全部不变，原始标签全部保留。
- 两组框架重编码后的 18 张训练/验证图片逐张字节相同；不存在两组输入内容不一致。
- EXIF 方向正常，重编码前后尺寸不变，坐标未因旋转/缩放失效；重编码会改变像素，不声称无损。
- 三个数据目录均恰好 18 张图 + 18 个标签，标签 hash 一致，没有未审核额外图片。
- dataset-01 原始 hash 绑定已失效，作为历史现场保留，不改写旧记录；dataset-02 审核导出全部 hash 保持一致。

[数据审计 JSON](evidence/issue-19/data-integrity.json) 与 [训练曲线](evidence/issue-19/README.md) 可公开核对。训练调度推导依据安装版本 `engine/trainer.py`，验证阈值依据 `engine/validator.py`；实际源码 hash 和核验摘录在证据目录，推导不冒充新训练结果。

## F. 推理耗时与执行边界

| 模型 | 640 非冷启动中位数 | 960 非冷启动中位数 | 首次冷调用 |
|---|---|---|---|
| 预训练 | 14.769 ms | 25.0755 ms | 6308.628 ms |
| 冻结 best | 13.096 ms | 19.420 ms | 1278.387 ms |
| 微调 best | 13.164 ms | 22.5015 ms | 4936.601 ms |

640 统计 17 次非冷调用，960 统计 18 次；同一进程先跑 640 再跑 960，形状变化仍可能触发初始化。CUDA 同步计时含 predict 预处理/后处理，不含读图、画框和文件写出。不是端到端机器人延迟或公平硬件 benchmark。推理峰值为 PyTorch 分配计数，预训练640/960分别约69.60/91.55 MiB，训练模型约64.22/82.47 MiB；不等于整卡占用。没有显存不足或静默 CPU 降级。

## G. 运行命令与软件回归

以下 PowerShell 在仓库根目录执行。已有独立 CUDA 环境实际复用 `artifacts/issue-10/neural-env`；默认 Demo 环境不新增深度学习依赖。需要重建实验环境时先安装对应 CUDA wheel，再装 `tools/requirements-vision-r2.txt`；本轮是复用环境，未宣称完成另一次干净环境安装。

```powershell
$py = 'artifacts/issue-10/neural-env/Scripts/python.exe'
$data = 'local_data/vision_r1_watercup_20261026'
$run = 'artifacts/vision-r2-issue19'
$weights = "$run/weights/yolo11n.pt"
$digest = '0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1'

# 实际 Gate A 命令；已存在目录会拒绝覆盖。
& $py tools/vision_r2_infer.py --weights $weights --data-root $data --output-dir "$run/gate-a-01" --imgsz 640 960
& $py tools/vision_r2_data.py --manifest "$run/annotation-reviewed-02/annotations.private.json" --data-root $data --output-dir "$run/dataset-02"

# 仅说明如何复现，不授权绕过本轮两组上限。
# 第一组历史实际输入为 dataset-01；当前修复版在干净审核导出上另建 working-dataset。
& $py tools/train_vision_r2.py --dataset "$run/dataset-02" --weights $weights --weights-sha256 $digest --output-root "$run/trials-02" --trial freeze-backbone --epochs 50
& $py tools/train_vision_r2.py --dataset "$run/dataset-02" --weights $weights --weights-sha256 $digest --output-root "$run/trials-02" --trial low-lr-finetune --epochs 50

& $py tools/vision_r2_infer.py --weights "$run/trials-02/low-lr-finetune/training/weights/best.pt" --data-root $data --output-dir "$run/finetune-infer-01" --imgsz 640 960
& $py tools/score_vision_r2.py --predictions "$run/finetune-infer-01/predictions.private.json" --annotations "$run/annotation-reviewed-02/annotations.private.json" --data-root $data --output-dir "$run/finetune-score-01"

$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& artifacts/issue-11/agent-env/Scripts/python.exe -m pytest -q --junitxml=artifacts/vision-r2-issue19/pytest-final.xml
git diff --check
```

原图和人工标签不公开，公共 clone 只能运行确定性软件回归，不能伪装复现私人实拍。实际旧命令/源码版本以训练 evidence 为准；修复版禁止覆盖已有证据。

新增数据合同和评分测试包括额外文件混入、错误 hash、人工审核缺失、错框/标签重算 hash、跨组重复、标签越界、私有目录、覆盖保护、空预测与零候选区别、重复框和 IoU 边界。测试使用合成小图，不代表真实照片效果。最终联合测试结果和源码/隐私审计见 [验收记录](evidence/issue-19/README.md)。基线 main 有 424 项测试，未合并实验分支的测试数量不能相加。

## H. Gate 判断、下一步与补拍清单

| Gate | 结论 | 剩余问题 |
|---|---|---|
| A 环境与预训练候选 | 执行完成；候选定位 GO | 对相似杯无实例鉴别力，远处目标漏检 |
| B 标注/数据准备 | 开发数据就绪 | 分组仅按场景，未知真实批次，无独立测试 |
| C 两组迁移训练 | 真实训练完成 | 两组固定阈值均零框，训练方案 NO_GO |
| D 受限真实识别 | BLOCKED | 独立6正8负未采集；现有开发效果已不达标 |
| Agent adapter / 生产 | 不实施 | 没有达到可靠验证门槛 |

建议 PM 下一步只审查一个最小修正实验：显式取消小数据集的长 warmup（例如 `warmup_epochs=0`，不修改框架）并记录实际 optimizer steps/学习率/分类分数分布，仍保留 0.25、同一分组和全部负例。先检验模型能否在训练图产生合理框，再谈独立泛化。**该实验尚未执行、不承诺成功，本轮已用完两组训练额度。** 不新增模型或大规模 DataForge。

如负责人补拍，优先补足真实目标外观和背景对照，而非大量近重复图：

1. **开发补拍 24 张**：16 正例，4 个视角（标志正面、两侧斜面、把手/弱标志面）× 2 距离（约0.5–0.8m与1.5–2.5m）× 2 光照（自然光、室内较暗光）。分布于浅色、木纹和杂物背景；每张独立按快门并改变摆放，不从连拍抽近重复图冒充独立。
2. **其中配套 8 张负例**：4 张移走目标但保持同背景；4 张放卡通杯/相似白杯/玻璃杯/纸巾包装。成对记录开发 group_id，整组留同 split，不把场景答案输入模型。
3. 模型和阈值冻结后，负责人另采**两批至少14张独立测试**，每批3正4负；正例覆盖近/远、轻遮挡和不同可见面，负例覆盖空背景、卡通杯、相似白杯和其他干扰物。记录实际批次与遮挡；未定框/身份标 uncertain。测试标签仅评分时可见，不参与训练/参考选择。

验收仍是 6 正例至少 5 张正确定位且 IoU≥0.5、8 负例零错误接受、实例 precision≥0.95；零接受 precision 未定义，不能通过。该模型训练目标只近似指定外观，对另一只相同外观的实体不能保证区分。即使将来通过，也只说明该物品的受限场景，不宣称家庭通用识别完成。

本 PR 交付可复现的实验代码、真实失败结果与最小下一步依据，供 PM 审查工程和证据。**不能以本 PR 合并、测试通过或模型文件存在关闭识别能力阻塞。**
