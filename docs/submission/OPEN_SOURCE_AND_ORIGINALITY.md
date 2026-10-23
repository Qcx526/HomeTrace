# HomeTrace 开源技术与原创性说明

本作品面向家庭物品寻回，原创工作集中在历史时空记忆、主动搜索编排、证据验证和可追溯呈现。视觉基础算法采用成熟开源实现。本文不主张 ORB、Hamming 距离、RANSAC 或 SQLite 为团队原创。

## 团队实现的工作

- 物品登记与跨进程 SQLite 记忆，保存目标标识、参考外观和历史观测。
- 根据历史位置与当前观察决定后续搜索点，保留模拟导航、观察、重规划和结束原因。
- 将历史记录与本轮证据分离，依据图像摘要、时间及已见证据拒绝旧图重放。
- 将视觉候选和几何验证结果转为 FOUND、SUSPECTED、UNKNOWN，并生成 JSON/JSONL 证据链。
- 使用轻量本地页面展示逐步决策、当前照片、检测框和两种策略的同输入对照。
- 提交材料校验、限定源码导出、SHA256 清单与归档完整性检查。

这些系统适配不构成对基础视觉算法的原创声明。当前三组公开场景中，记忆优先与固定顺序的尝试步数打平，尚未证明搜索效率提高。

## 复用组件与图片

| 组件或素材 | 用途 | 来源与许可依据 |
| --- | --- | --- |
| Python 标准库 | CLI、HTTP、SQLite、JSON、ZIP | Python Software Foundation License；依赖版本见实际环境报告 |
| SQLite | 持久化目标、历史和证据 | SQLite 公共领域；通过 Python sqlite3 使用 |
| OpenCV | ORB 特征、Hamming 匹配、RANSAC 单应性验证 | Apache-2.0；wheel 中保留上游第三方告知 |
| NumPy | OpenCV 输入数组与数值运算 | BSD-3-Clause；随实际安装环境保留许可 |
| pytest | 回归测试 | MIT；仅开发依赖 |
| OpenCV 五张公开照片 | 稳定公开演示及回归 | 上游 4.12.0，commit `49486f61fb25722cbcf586b7f4320921d46fb38e`，来源/哈希与许可见下方 |

公开照片来自 [OpenCV 原仓库](https://github.com/opencv/opencv/tree/49486f61fb25722cbcf586b7f4320921d46fb38e/samples/data)。完整出处为 [sources.json](../../examples/recorded_images/sources.json)，同时保留 `LICENSE.opencv.txt`、`COPYRIGHT.opencv.txt` 和 `LICENSE_CHANGE_NOTICE.opencv.txt`。照片未修改，原摄影者和拍摄日期未知；A/B/C 地点与清单时间由 Demo 编排，不能视为真实家庭搬移记录。`box.png` 自匹配只用于登记检查，跨图正例为 `box_in_scene.png`。

团队家庭照片仅在本地 `local_data/` 读取。默认不公开原图；公开结果只保留经隐私检查的数值、失败原因和摘要。钥匙、二维码、屏幕和其他个人信息均不随材料发布。其他物品没有独立历史 A/B 序列时，仅作视觉适用性测试。

## 明确边界

本作品没有 RobotClaw、ROS 或机器人 SDK 接入，没有真实机器人运动记录、端侧耗时或能耗结论。FOUND 表示当前图像中登记外观通过匹配与几何校验，不能区分同款包装的不同实体。SUSPECTED/UNKNOWN 表示未确认，不能推断物品不存在。家庭适用性和最终回归结论以 [运行测试报告](RUN_TEST_REPORT.md) 的实际证据为准。

制作 DOCX/PPTX 的工具属于离线材料生产工具，不属于 HomeTrace 搜索核心运行依赖。材料中采用实际截图与原始报告，未生成替代实验照片。
