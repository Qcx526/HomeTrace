# Issue #1 测试素材

测试文件位于 `src/hometrace/fixture_data/`，随 Python 包安装，运行时不要求当前目录在仓库根目录。这两个 JSON 文件由项目开发者手工编写，来源为 **synthetic fixture（合成测试样例）**。物品、地点、历史记录、状态和时间戳都是固定的测试数据。它们不含真实图片、生成图片、相机观测、机器人实测或视觉算法输出。

- `moved.json`：历史记忆为 A；本轮 A 未找到，B 的测试标注为 FOUND，C 未找到。预期先检查 A，再检查 B。
- `missing.json`：历史记忆为 A；本轮 A、B 未找到，C 被遮挡且为 UNKNOWN。预期遍历后诚实返回 UNKNOWN。

导航由 `MockAdapter` 模拟；ARRIVED 只表示模拟到达，不代表实体机器人发生运动。`FixtureDetector` 读取测试标注，不识别图片。FOUND 在此仅表示测试状态机成功处理了明确的正例标注。

## JSON 格式 v1

根对象必须恰好包含：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 整数 `1` |
| `name` | 非空测试名称 |
| `data_source` | 固定为 `fixture` |
| `navigation` | `adapter_kind: "mock"`、`simulated: true`、`unreachable_viewpoints: []` |
| `object` | 非空 `object_id`、`description`；可选 `sample_image_path` 仅允许 `null` |
| `viewpoints` | 唯一的 `viewpoint_id` 与非空 `name` 列表 |
| `memory_records` | 历史 `{observation, detection}` 列表 |
| `observations` | 每个地点最多一条当前 observation |
| `detections` | 当前 observation 的检测标注列表；允许缺少标注，检测时返回 UNKNOWN |

Observation 字段为 `evidence_id`、`viewpoint_id`、`captured_at`、`data_source`、`visibility_status`。证据 ID 在历史与当前记录之间也必须唯一；地点必须已注册；时间为带时区的 ISO 格式。可见性为 `clear`、`occluded` 或 `unobservable`。`image_path` 和 `image_hash` 可省略或为 `null`，不允许宣称不存在的图像证据。

Detection 字段为 `target_id`、`evidence_id`、`status`、`matcher`；可选 `score` 仅允许 `null` 或 0–1 的有限数值（测试标注分数，不是模型精度）。目标必须等于注册物品，证据必须对应 observation，`matcher` 固定为 `fixture_annotation`。状态允许 FOUND、SUSPECTED、NOT_FOUND_IN_VIEW、UNKNOWN；被遮挡或不可观察时只能标注 UNKNOWN。UNREACHABLE 属于导航结果，不是检测结果。

所有层级拒绝未知字段，防止误把真实图像或真机字段混入此阶段的合成数据。无图像样本是 Issue #1 的能力边界；后续真实图片阶段需要独立的数据来源、输入适配与验收，不能把这些测试样例重新标记为真实采集。
