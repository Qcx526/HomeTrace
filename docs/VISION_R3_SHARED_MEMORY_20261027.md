# Vision R3：共享冻结视觉与持久记忆首轮结果

**结论：免训练参考登记已真实运行，并在复用的水杯开发照片中获得有限正确定位；还未达到完整识别验收。继续受控开发为 GO，接入生产 FOUND 为 NO_GO，独立家庭识别仍 BLOCKED。**

关联 Issue #22；基于 PR #21 的 `cf049774891b020a988ce14421bb73dc75790240`，目标分支 `feature/19-vision-r2-confidence-warmup`。PR #21 又依赖 PR #20。没有合并这些PR，没有修改原有生产代码或历史报告。

## A. 输入和固定方法

负责人希望登记新物品无需逐物品训练，并允许必要时使用AI图补充训练。此次先复用已有预训练能力，**训练步骤0、生成图0、增强图0**；没有必要先生成数千张钥匙、眼镜等图片。当前只验证水杯，不声称已覆盖这些类别。

输入为18张既有人工审核水杯照片。SONY杯的两张已审核参考和卡通杯的一张已审核参考，从搜索成绩中排除，剩余15张为10正5负。全部参与过开发探索，独立测试0张。卡通杯只作rival控制，并未借用其参考自匹配作为负例成绩。

固定协议见 [实验协议](VISION_R3_PROTOCOL.md)：官方YOLO11n全图候选，640/960两种分辨率、conf=.25；DINOv2 ViT-S/14共享冻结编码器；目标两参考相似度均≥.70、前两条平均分比最佳rival高≥.05才给出 `APPEARANCE_SUPPORTED`。**这些是预设、未经校准的实验门槛，不是生产确认规则。** 本轮未按结果降低或修改门槛。

三张登记ROI沿用负责人批准的物体区域；搜索时使用检测器自己产生的框，未按场景真值提前裁剪。推理入口拒绝场景label/GT等字段。全部推理完成后，另一进程才读取人工框做IoU≥.5一对一评分。参考图片hash触发重放保护。

模型来源、权重SHA256、源版本和许可见 [环境记录](evidence/issue-22/environment.public.json)。GTX1660、PyTorch2.6.0+cu124、Ultralytics8.3.221；编码器权重直接使用Meta官方预训练，未创建逐物品模型。DINOv2为Apache-2.0；Ultralytics许可义务仍需在分发前核对，此PR不分发模型或权重。

## B. 实际产物

- `tools/vision_gallery.py`：不依赖GPU的多参考相似度、rival比较与拒识函数；原图hash去重、重放保护、异常向量校验。
- `tools/vision_r3_retrieve.py`：使用可选神经网络环境的真实全图检测＋冻结编码；私有gallery、36条场景推理记录、候选框、特征和36张覆盖图。
- `tools/score_vision_r3.py`：独立事后评分，强制完整评价格网；全部样本的本地HTML审查页。
- `tools/household_memory.py`：独立SQLite主人陈述记忆原型；登记/目录/别名解析/记住/历史/地点候选六项CLI。
- 本轮确定性测试、实际GPU推理、跨进程记忆运行及隐私/历史保护审计见 [证据索引](evidence/issue-22/README.md)。

原图、标签、图像hash、向量、逐图坐标、覆盖图、数据库、权重仅在 ignored 的 `artifacts/vision-r3-shared/`。公开证据只有脱敏聚合指标、模型环境和测试日志。

## C. 真实结果与模拟边界

真实执行：原图解码、全图YOLO候选、DINOv2特征提取、参考比较、标签事后评分、SQLite跨进程持久化。**未执行**：机器人移动、实时摄像、真实LLM登记对话、生产FOUND、独立测试。记忆演示中的地点陈述是显式软件演示输入，不是负责人真的移动物品的事实。

## D/E. 正负例、失败与测试

同一批15张非参考场景的结果：

| 分辨率 | 方法 | TP / FP / FN | 定位召回 | 候选精确率 | 负例错误支持 |
|---|---|---|---|---|---|
| 640 | 仅通用cup候选 | 8 / 4 / 2 | 80% | 66.7% | 1/5 |
| 640 | 加共享特征检索 | **3 / 0 / 7** | **30%** | 100%（仅3次正确支持） | 0/5 |
| 960 | 仅通用cup候选 | 8 / 5 / 2 | 80% | 61.5% | 1/5 |
| 960 | 加共享特征检索 | **4 / 0 / 6** | **40%** | 100%（仅4次正确支持） | 0/5 |

此处FP按“是否是指定SONY目标的正确框”计算，卡通杯被通用cup检出不代表通用类别检测错误。**100%是复用开发集上3/4个支持框的描述，不能扩展成物理实例精度已达标。** 完整train/val/all分组见 [指标](evidence/issue-22/metrics.public.json)，val也不是独立测试。

失败分布：两分辨率都有候选定位漏检；大量已有正确候选因不足两条参考达到预设相似度而拒识，640下10张正例仅支持3张，960仅4张。更高分辨率并未稳定修复全部图像。部分错误框和卡通杯更像rival，成功被保留为UNKNOWN；另一些未支持候选仍更像目标，但达不到双参考要求。参考只有正面区域，不能据此证明其他可见表面已经被可靠登记。

典型开发样例：

- 一张桌面近景SONY杯：两尺寸均正确框出并获得外观支持；640目标平均相似度约.855，rival约.551。
- 一张非参考卡通杯场景：两尺寸拒识；640目标约.535，rival约.923。这里只验证了一张独立于参考文件的卡通杯场景，仍是复用开发数据。
- 另一个SONY视角：640目标平均约.737，但有一条参考未到.70而拒识；960达到本轮规则，仍不据此调整阈值。
- 一张SONY正例：640目标平均约.663、960约.682，均拒识。
- 远处饮水机场景和复杂桌面：没有获得目标外观支持；候选存在不等于正确定位，全部失败保留在审查页。
- 其余4张负例没有cup候选；这说明本次全流程未误接受，**不能说实例检索器实际判断了这些画面里的每个物体**。

GPU同步的候选检测＋编码/比较暖调用中位数在最终运行中为640下47.5ms、960下59.2ms；不包括模型加载、原图解码、页面、网络或机器人动作，不能称为完整产品响应时间。无任何新模型训练。

本轮完整回归 **576项通过、0失败、0跳过**，见 [最终测试日志](evidence/issue-22/pytest.txt)。包含原有499项及新增77项，是同一次全量执行结果，不是分支测试数量相加。

首次推理发现Ultralytics在私有设置目录不存在时回退到仓库根目录；已把首次设置原样移入ignored目录，并在runner中预先建立私有设置目录。修复后重新执行36次推理，框、特征、检索分数与状态逐项完全重现。总调用72次，物理照片仍为18张，不将复跑计作更多样本；两次输出均保留。

## F. 方案理由

用户日常登记应该增加参考档案，不是等待训练。共享模型先提供通用候选和可比较外观，物品库提供实例参考，SQLite保存时间与地点。新增物品的计算主要是一次特征提取；这与本轮实际的零梯度、零训练相符。

检索层减少本数据上的错误候选，但明显牺牲召回；不能只报道筛掉卡通杯的成功。下一步应先检查参考表面覆盖、候选与登记裁剪的差异以及局部特征，而不是继续降低阈值或堆叠训练。若改变参考或方法，另立实验版本。

## G/H. 可用边界、后续与合并条件

本PR可以审查合入隔离实验工具与主人陈述记忆原型；不能解除Issue #19，也不能启用生产视觉确认。

记忆原型实际通过5次独立进程运行：登记→保存演示位置→新进程查询→候选排序→别名解析。重复ID不可重绑，位置事件不可覆盖，旧生产数据库只读识别后拒绝打开。**当前仅有owner_reported，尚未连接图像参考库和现有网页Agent；不把它称为完整会话产品。** 同名返回CLARIFY但未实现可恢复会话，仍需后续增量。

本轮支持的结论是“共享冻结特征无需逐物品训练，能在部分真实开发照片上提供正确定位后的外观筛选”；不证明多物品、任意视角、同款实例或家庭泛化已经解决。原R0/R1/R2报告、阈值、模型和原图不变。没有与R0不同数据/规则直接合并指标。

正式材料内部截止安排为11月2日结束前，见 [交付冲刺合同](DELIVERY_SPRINT_20261102.md)。这份PR不代表官方DOCX、PPT、视频或最终ZIP已经更新完成。识别与独立验证仍BLOCKED，材料必须如实描述。

## 可复现命令

私有登记文件为 `artifacts/vision-r3-shared/enrollment.private.json`，只含负责人审核的三参考ROI和18条无标签原图身份；模型源码、权重已按协议校验。首次准备可从Meta官方仓库固定提交和模型卡的torch.hub入口取得，必须核对协议中的hash；不升级现有CUDA环境。

```powershell
$visionPy = 'artifacts/issue-10/neural-env/Scripts/python.exe'
& $visionPy -X utf8 tools/vision_r3_retrieve.py --enrollment artifacts/vision-r3-shared/enrollment.private.json --data-root local_data/vision_r1_watercup_20261026 --encoder-source artifacts/vision-r3-shared/dinov2-source --encoder-weights artifacts/vision-r3-shared/torch-cache/hub/checkpoints/dinov2_vits14_pretrain.pth --detector-weights artifacts/vision-r2-issue19/weights/yolo11n.pt --output-dir artifacts/vision-r3-shared/full-frame-new
& $visionPy -X utf8 tools/score_vision_r3.py --inference artifacts/vision-r3-shared/full-frame-new --annotations artifacts/vision-r2-issue19/annotation-reviewed-02/annotations.private.json --data-root local_data/vision_r1_watercup_20261026 --output-dir artifacts/vision-r3-shared/scores-new
& artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 -m pytest -q
```

输出目录必须不存在，拒绝覆盖。最终实际结果位于 `full-frame-02` / `scores-02`，私有审查页为 `artifacts/vision-r3-shared/scores-02/review.private.html`；首次 `01` 目录保留。

主人陈述记忆示例（以下是演示输入，不是真实观察）：

```powershell
.venv/Scripts/python.exe -X utf8 tools/household_memory.py --db artifacts/household-demo/home.sqlite3 enroll --object-id demo-cup --name 演示水杯 --alias 我的杯子
.venv/Scripts/python.exe -X utf8 tools/household_memory.py --db artifacts/household-demo/home.sqlite3 remember --event-id demo-event-1 --object-id demo-cup --location-id study --location-name 书房桌面 --reported-at 2026-10-27T10:00:00+08:00 --source software-demo-owner-statement
.venv/Scripts/python.exe -X utf8 tools/household_memory.py --db artifacts/household-demo/home.sqlite3 history --object-id demo-cup
.venv/Scripts/python.exe -X utf8 tools/household_memory.py --db artifacts/household-demo/home.sqlite3 candidates --object-id demo-cup
```

真实CLI回复：`好的，我已记录你说的位置；尚未通过当前图像确认`。这些操作不需要模型、不训练网络，也不调用生产SearchCore。
