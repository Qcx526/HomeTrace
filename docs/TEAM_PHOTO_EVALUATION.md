# 团队实拍照片适配记录（P3）

2026-10-22 在 Windows 本机实际运行。结论：**当前团队纸巾正例尚未达到 FOUND**。生产 ORB、有限 SIFT 和 AKAZE 对比均未可靠确认；不降低验证阈值，不以人工标签替代识别结果，不把参考图登记或历史图当作当前确认。

本记录仅公开数值与结论。原始照片、中文来源文件名、画面、完整 CLI 报告、SQLite 数据库和含图 Demo 截图保留在 Git 忽略目录。运行时读取的图片 SHA256 在实验前后均通过校验；未修改、裁剪或生成照片。

## 可复跑命令与本地证据

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/evaluate_team_photos.py --data-root local_data --output-dir artifacts/p3-photo-final-20261022
.\.venv\Scripts\python.exe -m pytest tests/test_team_photo_inputs.py -q
```

输出目录必须是新的 Git 忽略目录；再次运行时换一个目录名，避免旧数据库和旧证据污染实验。该工具不联网、不读取 `PRECHECK_RESULTS.json` 的检测结论，不修改生产 matcher。

本次保存：

- `artifacts/p3-photo-final-run.log`：实际运行 stdout/stderr。
- `artifacts/p3-photo-final-20261022/evaluation.private.json`：75 次匹配与 8 次独立 CLI 进程的完整结果。
- `artifacts/p3-photo-final-20261022/cli/{moved,missing}/{register,search,replay,hash_replay}/`：逐次 JSON、事件与 CLI 日志；两个场景使用各自 SQLite 文件。
- [公开数值汇总](evidence/p3-photos-summary.json)：从真实结果按字段白名单提取，不含照片、原文件名、私有路径或原始观察文本。

输入边界测试：**18 passed in 0.36s**（首次执行；后续测试时间可变）。测试使用明确标注的合成字节验证 SHA、路径、来源、时间序列、隐私汇总、缺输入、拒绝覆盖与几何门槛；不是实拍识别成绩。

## 数据与方法

两个本地数据包共 16 个图片清单条目（部分场景图片重复出现），路径、映射大小/SHA256、随包 SHA256SUMS 全部通过校验。纸巾的 history/moved/missing 通过现有严格 manifest 解析器，确认无检测答案字段、当前序列晚于历史序列。来源是团队提供的真实照片，**拍摄时刻未认证**；`2000-01-01` 等时间只表达 `demo_sequence`。A/B/C 是演示观察点标签，不是机器人行走记录。

纸巾使用自己的 `tissue-pack` 身份与团队参考图；其他物品按独立身份做 detector-only 图对评估，没有编造它们的历史 A→B 寻找过程。人工存在标签只用于检测完成后的评价列，不输入视觉算法或搜索决策。

环境：OpenCV 4.14.0，随机种子 0，OpenCV 线程 1。ORB 使用生产 `ImageMatcher`。SIFT/AKAZE 只位于评估工具中；SIFT 使用 L2 距离，AKAZE 使用 Hamming 距离，不能将不同描述子的绝对距离当作同一量纲比较。

三个方法固定使用 ratio 0.75、不同场景描述子的唯一匹配、至少 12 个匹配、10 个几何内点、内点比例 0.55、参考图支持覆盖 0.10；清晰度门槛 30。几何验证保留 RANSAC 3 像素、2000 次迭代、置信度 0.995，以及凸性、面积、边长与可见比例限制。ORB 与 AKAZE 另用 Hamming ≤64；SIFT 使用 L2 ratio，不套用没有意义的 Hamming 上限。所有阈值在对比前固定，未按单张图片调参。

采用成熟开源方法的依据：[OpenCV 特征匹配](https://docs.opencv.org/4.13.0/dc/dc3/tutorial_py_matcher.html)、[特征匹配与单应性](https://docs.opencv.org/4.13.0/d1/de0/tutorial_py_feature_homography.html)、[AKAZE 匹配](https://docs.opencv.org/4.13.0/db/d70/tutorial_akaze_matching.html)。这些基础算法不是 HomeTrace 原创；本项目贡献在记忆、搜索决策、证据边界及可追溯流程。

## 纸巾实际结果

最新参考图清晰度为 **102.530**，能够登记；不是外部旧参考图的约 27 数值。

下表使用最终实跑的实际数值。几何阶段尚未执行时 `inliers=0` 表示**未估计**，不能解释成已检验过全部匹配。耗时是一次本机运行，不是性能基准：ORB 列只计 scene detection；SIFT/AKAZE 列还包含参考图解码和特征提取，不能据此直接算加速比。完整 ORB 总耗时也保存在 JSON。

| 场景 | 方法 | 匹配 | 内点 | 内点比例 | 参考支持覆盖 | 耗时 ms | 状态/主要原因 |
|---|---|---:|---:|---:|---:|---:|---|
| 历史 A（人工可见目标） | ORB | 21 | 7 | 0.3333 | 0.0524 | 65.035 | SUSPECTED / 几何内点不足 |
| 历史 A | SIFT | 30 | 9 | 0.3000 | 0.0599 | 1013.662 | SUSPECTED / 几何内点不足 |
| 历史 A | AKAZE | 4 | 0 | 0 | 0 | 746.183 | SUSPECTED / 匹配数不足 |
| 当前 A（人工负例） | ORB | 18 | 6 | 0.3333 | 0.0778 | 60.513 | SUSPECTED / 几何内点不足 |
| 当前 A | SIFT | 29 | 8 | 0.2759 | 0.0364 | 908.567 | SUSPECTED / 几何内点不足 |
| 当前 A | AKAZE | 3 | 0 | 0 | 0 | 899.693 | UNKNOWN / 无已验证匹配 |
| 当前 B（人工可见目标） | ORB | 15 | 3 | 0.2000 | 0.0012 | 104.368 | SUSPECTED / 几何内点不足 |
| 当前 B | SIFT | 74 | 23 | 0.3108 | 0.0391 | 1266.930 | SUSPECTED / 几何内点比例不足 |
| 当前 B | AKAZE | 14 | 5 | 0.3571 | 0.0111 | 749.228 | SUSPECTED / 几何内点不足 |
| 无目标 B | ORB | 13 | 4 | 0.3077 | 0.0534 | 93.539 | SUSPECTED / 几何内点不足 |
| 无目标 B | SIFT | 22 | 6 | 0.2727 | 0.0100 | 1054.537 | SUSPECTED / 几何内点不足 |
| 无目标 B | AKAZE | 3 | 0 | 0 | 0 | 708.443 | UNKNOWN / 无已验证匹配 |
| 当前 C（人工负例） | ORB | 11 | 0 | 0 | 0 | 70.046 | SUSPECTED / 匹配数不足 |
| 当前 C | SIFT | 25 | 7 | 0.2800 | 0.0321 | 944.475 | SUSPECTED / 几何内点不足 |
| 当前 C | AKAZE | 4 | 0 | 0 | 0 | 723.250 | SUSPECTED / 匹配数不足 |

本地人工视检看到：参考图较近且包含背景；历史 A 的纸巾遮住包装正面大部分纹理；当前 B 目标较小、靠近左边缘，视角和可见平面变化较大。这些是对失败原因的观察解释，不是额外检测标签或算法确认。SIFT 虽增加匹配，但有效内点比例和空间覆盖仍不足，不能把 23 个内点直接宣传为 FOUND。

纸巾所有输出 `bbox=null`，因此“团队正例检测框与图像坐标一致”本次为 **NOT_APPLICABLE_NO_FOUND / 尚未通过家庭正例验收**。不得补画人工框冒充检测框。稳定 OpenCV 公开样例与已有检测框回归路径保留；家庭数据还需要清晰、主体占比合适、正面纹理未大幅遮挡且场景中主体完整的独立补拍，随后重做负例验证。

## SQLite 记忆与重放实跑

每种场景依次启动 4 个新的 Python CLI 进程，使用同一个该场景专用 SQLite 文件；moved 与 missing 两套文件互不混用。

| 操作（两个场景都执行） | 实际结果 | 历史记录数 | 确认位置 | 证据保护 |
|---|---|---:|---|---|
| register 独立登记并观察历史 A | SUSPECTED | 0（运行前） | null | 新参考已登记，历史 A 未确认 |
| search 当前三张场景图 | SUSPECTED | 1 | null | 历史只指导计划，不作为当前确认 |
| 同 manifest 重跑 | UNKNOWN | 4 | null | 3 次 `replayed_evidence` |
| 新 evidence ID、晚一天 demo 时间、相同图片字节 | UNKNOWN | 4 | null | 3 次 `replayed_image_content` |

8 次 CLI 进程返回码均为 0，`confirmed_evidence_ids` 均为空。运行完成不等于视觉成功；此处如实验证了未确认历史持久化、当前观察分离、重规划及证据重放拒绝，未验证家庭案例成功找到目标。

## 其他目标适用性

每个目标与 4 个独立场景进行 ORB/SIFT/AKAZE 对比，完整数值见公开 JSON；没有历史过程或真机运行记录。

| 目标 | 当前条件与结果 | 能力边界 |
|---|---|---|
| 恐龙耳机壳 | 参考清晰度 21.265，低于 30；三种方法 UNKNOWN | 当前参考图拒绝登记，需补拍清晰纹理；不是耳机主体类别识别 |
| 钥匙 | 人工正例 ORB 18 匹配/4 内点；SIFT 40/6；AKAZE 4 匹配，未进入几何估计；均 SUSPECTED | 细小、反光与姿态变化；私密齿形和标识不得公开 |
| 圆珠笔 | 两个人工正例 ORB 匹配 3/7，UNKNOWN/SUSPECTED；SIFT 4/6；AKAZE 0/2 | 狭长、纹理少、场景中主体小，未确认 |
| 保温杯 | ORB 正例 7 匹配；SIFT 68/37，但比例 0.5441、覆盖 0.0171；AKAZE 36/33、比例 0.9167，但覆盖 0.0342 | 局部图案支持不足以代表整个参考图；三种均 SUSPECTED，不降低覆盖门槛 |
| 绿色皮套玻璃杯 | 参考可读取；无明确远景正例，其他场景均未 FOUND | 正例适用性尚未测试，不能宣称已支持 |

总计 25 个图对、75 次方法评估；人工标注的存在图对有 8 个，其余 17 个为外部标注未见该目标的对照。**FOUND 0 次**，未出现把这些对照判为 FOUND 的情况，但正例也全部未确认；不能据此宣称准确率、泛化成功、可靠缺席判断或搜索效率提高。当前三个稳定演示中两种搜索策略的步数仍打平。

## 交付决策

保留生产 ORB 及原稳定样例，不把 SIFT/AKAZE实验接入生产。家庭实拍仅作受限本地适配与失败边界展示，界面必须保留 SUSPECTED/UNKNOWN、无已确认位置、模拟导航及未认证拍摄时间。当前瓶颈需要有限补拍和重新验证；不为本次图片放松门槛、不扩展大模型或复杂框架。
