# R1 登记参考 ROI 的正式实拍评估

2026-10-23 在 Windows、Python 3.11.4、OpenCV 4.14.0、NumPy 2.4.6 上执行，固定 seed=0、threads=1。本轮复现了耳机壳全图参考中的木纹背景假阳性。使用团队预先提供的登记 ROI 后，该负例变为 UNKNOWN；**所有明确正例仍未确认，不能宣称家庭物品已稳定识别。**

## 方法与数据边界

- 四组物品各六张，共 24 张团队私有原图。核对每张的解码尺寸、字节数、清单 SHA256 与独立 SHA256SUMS，运行前后原图校验值一致。
- 每组固定一张参考图，其余五张全部评估；全图与登记 ROI 两种模式共 40 个计划评价项。ROI 使用输入建议的一次固定坐标，没有按场景结果调整。
- 全图基线通过 `git show e3adca7:src/hometrace/image_matcher.py` 保存并动态加载已合并版本的正式 `ImageMatcher`，实际解析的代码提交号记录在公开摘要。ROI 使用当前正式 `ImageMatcher(reference_roi=...)`，工具比对实际导入文件与仓库源码字节哈希，防止运行旧安装包；两者质量及几何阈值完全一致，搜索图始终完整读取。
- 预检 JSON 只作为任务风险说明，程序没有将其输出读作检测结果。本文所有数字来自本次生产代码实际运行。部分几何统计与外部预检不同，以正式执行记录为准。
- 人工标注仅在 detector 返回后用于离线分类。每种模式含明确正例 6、明确负例 8、uncertain 5、辅助旧参考 1。`uncertain_or_negative` 归入 uncertain；辅助旧参考不计正负例。小熊猫与大熊猫不是同一目标实例。
- 实际拍摄时间未知；图片名中的 history 不被采纳为已确认历史。照片不证明物品移动过程或机器人运动，CLI 仅使用空历史与明确标为 `demo_sequence` 的实验顺序。

公开逐项数字见 [experiment-summary.json](evidence/issue-4-r1/experiment-summary.json)。其中使用匿名场景编号，不包含私图路径、图像 SHA256、检测框、ROI 坐标或原图。完整路径/原图哈希/bbox、固定 ROI、环境和基线/当前源码 SHA256 保留在 Git 忽略的本地实验目录。

## 实际结果

| 方法 | 计划评价项 | 实际 detect 调用 | 登记拒绝影响项 | FOUND | SUSPECTED | UNKNOWN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 已合并基线，全图参考 | 20 | 15 | 5 | 1 | 13 | 1 |
| 正式 API，登记 ROI | 20 | 20 | 0 | 0 | 16 | 4 |

全图小熊猫参考触发登记清晰度/纹理质量门槛，一次构造器拒绝使该组五项都无法执行检测。这五项记录为 `enrollment_rejected`、`detect_called=false`、`status=null`，不伪装为五次 UNKNOWN 检测。裁剪后的登记通过，但独立小熊猫正例仍只到 SUSPECTED。

| 物品 | 全图参考结果 | 登记 ROI 结果 |
| --- | --- | --- |
| 耳机壳 | 1 FOUND（明确空背景误报）、4 SUSPECTED | 3 SUSPECTED、2 UNKNOWN |
| 小熊猫 | 5 项登记拒绝 | 4 SUSPECTED、1 UNKNOWN |
| 钥匙 | 5 SUSPECTED | 5 SUSPECTED |
| 纸巾 | 4 SUSPECTED、1 UNKNOWN | 4 SUSPECTED、1 UNKNOWN |

同背景空木纹复现：

| 指标 | 全图基线 | 登记 ROI |
| --- | ---: | ---: |
| 参考关键点 | 1404 | 552 |
| 当前图关键点 | 775 | 775 |
| good matches | 55 | 2 |
| 几何内点 | 44 | 0 |
| 内点比例 | 0.8 | 0 |
| 参考几何覆盖 | 0.4012 | 0 |
| 本次 detect 耗时（ms） | 55.972 | 52.128 |
| 状态 | FOUND | UNKNOWN |
| 原因 | verified_planar_reference_match | no_verified_match |

这些耗时仅为本机此次运行，不是性能提升结论。视觉检查可见原参考包含大量木纹，而目标只占部分画面；空图有同一木纹，因此平面几何验证可以成功支持背景。ROI 限制登记特征来源，解决了本轮这个已知误报；它没有语义分割能力，也不证明其他背景假阳性已经消失。

ROI 模式明确负例 **0/8 FOUND**，明确正例 **0/6 FOUND**。基线明确负例有 1 个 FOUND，但只执行了 6 个负例检测，另外 2 个因参考登记拒绝未执行；不能将它们写成负例识别成功。未确认仍只代表证据不足，不能推断物品不存在。未提供任何准确率泛化、搜索效率或真机表现声明。

## SQLite / CLI 的独立实际验证

工具额外为耳机壳创建两个独立 SQLite 数据库，分别执行 `register` 与后续独立进程 `search`，两者共四次命令均退出 0。登记 manifest 的 observations 为空；登记返回 UNKNOWN，没有虚构历史位置。只向搜索提供一个实验视点的完整空背景照片：

- 当前 API 全图登记：search 返回 FOUND，再次暴露背景误报。
- 当前 API ROI 登记：search 返回 UNKNOWN。

两个进程之间读取 SQLite 的登记信息。全部导航为 `simulated_navigation`。私有命令、stdout、stderr、report、events 与数据库保留本地，不把含图片路径/hash/bbox 的 CLI 报告发布到 GitHub。

## 复现与自动化验证

登记 CLI 的新增参数为 `register --reference-roi X1 Y1 X2 Y2`：使用原始参考图像素坐标，右边界和下边界不包含，宽高至少 32 像素且不得越界。省略参数保留原全图行为。坐标与原参考图 SHA256 一同存入 SQLite；改变 ROI 需另建 object_id。后续 `search` 自动加载，不能传入当次场景 ROI 或覆盖登记范围。诊断记录原参考尺寸、ROI、裁剪后尺寸及完整场景尺寸；输出框始终位于完整场景坐标系。应在本地确认登记范围主要覆盖物体本身，仍含大量背景的 ROI 不提供可靠保证。

```powershell
.venv/Scripts/python.exe tools/evaluate_registration_roi.py --data-root local_data/team_new_20261023 --output-dir artifacts/issue-4-r1/experiment-verified
.venv/Scripts/python.exe -m pytest tests/test_roi_experiment.py -q
```

单元测试覆盖输入完整性、分类、统计、实际导入源码核验和基线归属，不算真实照片识别成功；完整回归输出见 [R1 验证](evidence/issue-4-r1/README.md)。40 项实拍计划评价单独记录。已有输出目录会拒绝覆盖，复现时选择新的 Git 忽略目录。缺失私有数据会非零退出，不生成虚构结果。

核心边界：登记 ROI 是减少背景特征污染的最小防护；ORB 与单应性仍适合有充分纹理、近似平面的外观。耳机曲面与遮挡、小熊猫非刚性姿态、钥匙细小反光、纸巾尺度/方向/遮挡仍会限制确认。当前比赛稳定正例继续采用公开 OpenCV 回归路径，家庭样本作为真实失败及防误报分析，不包装成成功寻物演示。
