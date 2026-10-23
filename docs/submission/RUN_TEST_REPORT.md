# HomeTrace 运行说明与测试报告

## 范围与事实来源

本报告区分稳定 P2 基线与 Issue #4 新增实验。当前公开演示采用 OpenCV 实拍图片和模拟导航，没有真实机器人数据。家庭照片保留在本地，不能把公开样例的结果推广为家庭识别准确率。

## Windows 运行

在 Python 3.11 或更高版本的 Windows 环境，从源码根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,vision]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m hometrace demo --port 8765 --output-dir artifacts/submission-demo
```

浏览器打开 `http://127.0.0.1:8765`，依次运行“寻找目标”“未确认负例”“旧图重放保护”。每次实际登记与搜索产生独立报告；页面回放真实事件。下载报告检查 `result_status`、`location`、图片摘要与事件顺序。新一次验证应使用新输出目录，保留已有证据。

## 已审核 P2 基线

来源：`docs/evidence/issue-3/pytest.txt`、`validation.json`、`comparison.json` 与 `browser/`。该记录属于 main `efaaaffae47ddb577ec9472d03838b66321eb178` 的稳定基线，不冒充 P3 最新运行。

| 项目 | 真实留存结果 |
| --- | --- |
| Windows 环境 | Windows 10，Python 3.11.4，全新虚拟环境 wheel 安装 |
| 回归 | 148 passed，0 skipped，包含 P0 54 和 P1 68 |
| 公开正例 | moved 为 FOUND，确认地点 B，两种策略均尝试 2 步 |
| 未确认负例 | missing 为 SUSPECTED，确认地点 null，两种策略均尝试 3 步 |
| 旧图重放 | replay 为 UNKNOWN，确认地点 null，两种策略均尝试 3 步，只有 C 新解码 |
| 检测框 | 浏览器 SVG 坐标与报告 bbox 一致；旧图不产生当前匹配框 |

上述三组策略对照步数打平。独立图像评估只有 1 张正例和 3 张负例，其中 2 张负例为 SUSPECTED，未误报 FOUND；登记自匹配不算独立正例。这是小样本可运行验证，不能声称一般准确率或性能优势。

## Issue 4 家庭照片实际结果

2026-10-22 在 Windows 本机实际运行，完整结果见 [家庭适配记录](../TEAM_PHOTO_EVALUATION.md) 与 [公开数值汇总](../evidence/p3-photos-summary.json)。本地 16 个图片清单条目通过相对路径、映射大小、SHA256、来源及序列检查。25 个图对分别执行 ORB、SIFT、AKAZE，得到 75 次方法评估，**0 FOUND**。存在目标的图对为 8 个，未见目标对照为 17 个；同一图对跨方法复测，不是 75 张独立照片，不能宣称泛化准确率。

| 纸巾场景 | ORB 匹配/内点 | 比例/覆盖 | 检测耗时 ms | 状态与原因 |
| --- | --- | --- | --- | --- |
| 历史 A | 21/7 | 0.3333/0.0524 | 65.035 | SUSPECTED，几何内点不足 |
| 当前 A | 18/6 | 0.3333/0.0778 | 60.513 | SUSPECTED，几何内点不足 |
| 当前 B | 15/3 | 0.2000/0.0012 | 104.368 | SUSPECTED，几何内点不足 |
| 无目标 B | 13/4 | 0.3077/0.0534 | 93.539 | SUSPECTED，几何内点不足 |
| 当前 C | 11/0 | 未估计 | 70.046 | SUSPECTED，匹配数不足 |

耗时为一次本机 scene detection，不代表端侧或机器人性能。SIFT/AKAZE 的计时包含参考图解码与特征提取，不能直接与此列求加速比。纸巾 SIFT 当前 B 虽有 74 匹配/23 内点，比例 0.3108、覆盖 0.0391 仍未通过。保温杯 AKAZE 36/33、比例 0.9167，但覆盖 0.0342 小于原门槛 0.10，同样未确认。生产 ORB 与原阈值均未改变。

纸巾 moved/missing 各用独立 SQLite，分别执行 register、search、同证据重放、新 ID/较晚 demo 时间但同图片重放。8 个独立 CLI 进程完成：两次 search 均 SUSPECTED/null，重复证据和重复内容均 UNKNOWN/null；确认列表为空。所有家庭 bbox 为 null，家庭正例框一致性为 **NOT_APPLICABLE_NO_FOUND**，不能补画人工框。公开样例检测框回归仍保留。

耳机壳参考图清晰度 21.265 被质量门槛拒绝；钥匙、笔、保温杯未确认；玻璃杯没有远景正例。备用物品只做 detector-only 评估，未虚构历史 A 到 B 过程。18 项输入边界测试使用合成数据，仅验证适配工具行为。

复跑使用新输出目录：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/evaluate_team_photos.py --data-root local_data --output-dir artifacts/new-team-evaluation
.\.venv\Scripts\python.exe -m pytest tests/test_team_photo_inputs.py -q
```

## Issue 4 回归和打包

本轮开发环境完整回归实际输出为 **226 passed in 57.59s，0 skipped**，日志见 `docs/evidence/issue-4/pytest.txt`（原始本地记录 `artifacts/p3-pytest.txt`）。与 main 比对，原有 148 项测试文件没有修改；新增 19 项 Demo 配置测试、18 项照片输入与汇总测试、41 项打包测试。测试通过验证软件行为，不代表家庭照片识别已 FOUND。

Windows 全新环境安装和实际材料打包结果以 PR 对应的最终日志为准，尚未写入本节的结果不代表已完成。打包工具拒绝缺失、空文件或格式不可读的必需材料。候选包允许人工审查尚未完成，必须明确标为 candidate；工具没有自动认可正式可提交的 ready 模式；始终 ready_to_submit=false，最终上传由团队人工决定。自动化正常路径使用明确标注的假团队配置，不构成正式比赛提交。正式 ZIP 生成与赛事上传属于不同步骤。

Windows 干净安装验证已完成：现有 Windows 10 build 19045 上创建全新虚拟环境，非 editable 安装 HomeTrace 0.4.0 wheel，`pip check` 通过，仓库外 CLI 与 HTTP 服务运行通过。环境为 Python 3.11.4、OpenCV 4.14.0、NumPy 2.4.6、pytest 9.1.1；该轮 **226 passed in 61.55s，0 skipped**。证据在 `docs/evidence/issue-4/clean-environment/`。这是新虚拟环境，不是重装 Windows，不据此宣称其他操作系统或设备通过。

## 实际演示视频

`docs/submission/HomeTrace_演示视频.mp4` 已生成：72.28 秒，H.264，1440×1080，3,058,082 字节，完整解码通过。视频为实际浏览器软件运行画面，覆盖公开正例、未确认负例与旧图重放保护，含中文讲解字幕，无音轨。六个关键帧已人工检查可读，公开版不含团队家庭原图。视频元数据保存在同目录。播放节奏用于讲解，不作为计算或移动耗时。
