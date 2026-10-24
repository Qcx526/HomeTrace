# P4-Vision：YOLOE Visual Prompt 可行性结论

**Gate 0 实际 GPU 推理通过；Gate 1 对生产接入为 NO_GO。** 2026-10-24 在固定参数下完成全部 20 个场景。模型在一张正例中框出小熊猫挂件，但也把大熊猫误作为登记目标候选。未接入生产 Detector、SearchCore、SQLite 或网页，不继续调阈值、换模型或重训练。下一阶段转向 Issue #11 的真实 LLM 工具调用。

## 输入与实验方法

基线 main `e5732b4024d90cc190aedb77f98f626b11e982cd` / v0.4.1。团队新包四组各六张，24 张原图的 SHA256、字节数和尺寸在前后均通过核对。每组一张完整登记参考，使用 PR #9 已固定的原参考 ROI；其余五张完整场景参与推理。人工类别仅在模型进程返回后用于评价：6 明确正例、8 明确负例、5 不确定、1 辅助参考。真实拍摄时间未知，本实验没有导航或历史搬移声明。

使用官方 `YOLOE.predict(source=完整场景, refer_image=完整参考, visual_prompts={bboxes: 原坐标ROI, cls: [0]}, predictor=YOLOEVPSegPredictor)`。模型内部 letterbox 保留完整场景，没有按答案裁场景。输出 `object0` 绑定登记提示，不是神经网络辨认出的物品名字，更不证明是登记的特定实例。每张图启动新进程并重新加载相同权重，避免提示状态跨物品或场景污染。候选最多只标 `SUSPECTED`，没有候选标 `UNKNOWN`；绝不由模型分数产生 FOUND。

参数在运行前写入并冻结：[protocol.json](evidence/issue-10/protocol.json)：confidence=0.25、IoU=0.7、imgsz=640、max_det=100、half=false、seed=0、cuda:0、每图180秒超时。没有根据结果修改参数、ROI、标签或挑掉不利场景。该数据曾被人工及 ORB 检查，属于探索性实验，没有独立保留集，不能报告泛化精度。

## 真实结果

| 类别 | 场景数 | 有候选框的场景 | 无候选 | 执行失败 |
| --- | ---: | ---: | ---: | ---: |
| 明确正例 | 6 | 2 | 4 | 0 |
| 明确负例 | 8 | 1 | 7 | 0 |
| 不确定 | 5 | 0 | 5 | 0 |
| 辅助参考 | 1 | 0 | 1 | 0 |

**正例图有框不等于定位正确。** 实际查看全部三个候选覆盖图后：

- `panda/scene_02`：正例，分数 0.498809，框主要落在大熊猫；登记小挂件未获得正确的独立候选。属于相似实例混淆，不能算正例识别成功。
- `panda/scene_03`：只有大熊猫的明确负例，分数 0.796382，产生候选误报。
- `panda/scene_05`：正例，分数 0.550312，框覆盖登记小熊猫挂件，视觉复核支持目标候选；仍没有独立身份验证，不得晋升 FOUND。
- 耳机壳正例、钥匙正例、两个纸巾正例均无候选。小目标、遮挡、非平面形变与登记外观变化仍是当前限制；本实验未做消融，不能把失败唯一归因于其中某项。
- 耳机壳空木纹挑战及其余明确负例除大熊猫外均无候选。无候选不证明物品不存在。

所以 6 个正例仅 1 个有视觉复核支持的目标候选，5 个没有正确目标候选；8 个负例出现 1 个候选误报。没有人工真值框或 IoU 定量标注，不把这份复核说成正式定位基准。逐样本类别、分数、耗时、设备、候选数和失败/未确认原因见 [summary.json](evidence/issue-10/summary.json)，复核记录见 [localization-review.json](evidence/issue-10/localization-review.json)。原始 bbox、坐标图、路径、图像 SHA、请求和完整输出在本地 `artifacts/issue-10/evaluation-01/`，不提交公共仓库。

## 与 ORB + ROI 比较

PR #9 同一固定数据的 ORB + ROI：6 明确正例均未确认，8 明确负例均未 FOUND；完整参考曾对空木纹误报 FOUND。YOLOE 获得 1 个视觉支持候选，但引入相似熊猫负例候选，未解决实例身份。两者语义不同，不能直接把 YOLOE 的有框率与 ORB 的 FOUND 比作准确率。旧 P3 的75项、R1的40项、本次20场景分别记录；Gate 0 重复空桌面仅是 API smoke，不增加独立样本数。旧报告不改。

预先门槛要求真实正例候选有用且明确负例无候选误报。大熊猫负例已使本轮不能通过，因此不实现可选 NeuralDetectorAdapter，不在初赛 Demo 加入“家庭已找到”。保留可复现实验工具，后续如研究实例核验须另立合同和新数据，不在本阶段无限调参。

## 环境、性能和许可

Windows 10 build 19045，Python 3.11.4，GTX 1660 6 GB（sm75），驱动551.61；实际 torch 2.6.0+cu124、torchvision 0.21.0+cu124、CUDA runtime12.4、Ultralytics8.3.221、NumPy2.4.6、OpenCV4.14.0。独立环境位于 `artifacts/issue-10/neural-env/`，原 HomeTrace 开发环境不含 torch；默认安装依赖不变。详见 [环境](evidence/issue-10/environment.json)、[完整依赖冻结](evidence/issue-10/neural-freeze.txt)。

权重为官方 `yoloe-11s-seg.pt`，27,803,986字节，SHA256 `8e439445c87338b79d9ce21dec109f4621e26df67e94d26ea1a98c1e64dce3e3`；[固定发布源](https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11s-seg.pt)。所有权重留本地且Git忽略。依照[官方 VP API](https://docs.ultralytics.com/models/yoloe/)并检查固定8.3.221源码执行，未套用最新版改变的默认模型。

20次实际 predict（包括参考提示编码、模型预热和设备同步）为850.776–1172.626ms，中位885.641ms；最大 PyTorch allocated显存192,036,352字节。它不含所有驱动/桌面显存，不等于整机显存占用；进程启动与模型载入另列，不宣称机器人端侧速度或与 ORB 的加速比。全部20次成功执行，0超时/运行失败。

Ultralytics 包是 [AGPL-3.0](https://raw.githubusercontent.com/ultralytics/ultralytics/v8.3.221/LICENSE)，另有[官方许可说明](https://www.ultralytics.com/license)。仓库目前没有根 LICENSE，公开 GitHub 本身不等于已满足 AGPL 的后续集成/分发要求。此 PR 仅交付独立实验工具与报告，不分发权重或运行时、不擅自更改全库许可证；如果以后集成或分发，应由 PM 明确许可方案，不能默认可嵌入商业 SDK。

## 复现

从仓库根目录，先按 [PyTorch 官方旧版安装说明](https://pytorch.org/get-started/previous-versions/)安装匹配CUDA的版本。本轮命令如下；新输出路径必须不存在：

```powershell
.\.venv\Scripts\python.exe -m venv artifacts/issue-10/neural-env
.\artifacts\issue-10\neural-env\Scripts\python.exe -m pip install --upgrade pip==25.3
.\artifacts\issue-10\neural-env\Scripts\python.exe -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124 --extra-index-url https://pypi.org/simple
.\artifacts\issue-10\neural-env\Scripts\python.exe -m pip install -r tools/requirements-neural.txt
.\artifacts\issue-10\neural-env\Scripts\python.exe -m pip check
Copy-Item docs/evidence/issue-10/protocol.json artifacts/issue-10/protocol.json
New-Item -ItemType Directory -Force artifacts/issue-10/weights
curl.exe -L --fail --output artifacts/issue-10/weights/yoloe-11s-seg.pt https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11s-seg.pt
.\.venv\Scripts\python.exe -X utf8 tools/evaluate_yoloe.py --data-root local_data/team_new_20261023 --output-dir artifacts/issue-10/new-smoke --python artifacts/issue-10/neural-env/Scripts/python.exe --weights artifacts/issue-10/weights/yoloe-11s-seg.pt --protocol artifacts/issue-10/protocol.json --smoke
.\.venv\Scripts\python.exe -X utf8 tools/evaluate_yoloe.py --data-root local_data/team_new_20261023 --output-dir artifacts/issue-10/new-evaluation --python artifacts/issue-10/neural-env/Scripts/python.exe --weights artifacts/issue-10/weights/yoloe-11s-seg.pt --protocol artifacts/issue-10/protocol.json
.\.venv\Scripts\python.exe -m pytest -q
```

初次旧pip解析typing-extensions依赖失败；升级独立环境pip并补PyPI索引后安装成功。另一次未固定torch的解析在安装前停止，最终全部按上述版本固定，`pip check`通过。未改GPU驱动、系统Python或原环境。模型推理前后核验图像与权重SHA；关闭usage/HUB/外部集成，并在worker禁止socket网络访问。私人照片从不发送给LLM或云视觉接口。

## 交付范围与下一阶段

新增工具 `evaluate_yoloe.py`（输入/超时/记录）、`yoloe_worker.py`（官方真实推理）、`neural_contract.py`（候选边界/脱敏）。只创建独立实验产物，不生成假的工具导航或神经框；单元测试的stub明确仅测试软件边界，真实模型证据来自上述GPU运行。测试日志与原289回归保留见 [验收索引](evidence/issue-10/README.md)。

本阶段没有LLM调用，也不声称Agent已经实现。Issue #11将使用指定网关的真实模型API、LangGraph/LangChain和共享可信工具；不采用正式离线Agent。官方DOCX主表及团队身份由Issue #12独立处理。研究结论NO_GO不阻止稳定公开Demo和正式材料准备。PR由PM审查，未经审查不合并。
