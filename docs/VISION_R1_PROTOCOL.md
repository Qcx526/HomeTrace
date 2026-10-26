# Vision R1：多视角参考登记实验合同 v1

本轮依据负责人 Vision R1 指令，关联 Issue #4。分支 `feature/4-vision-r1-multireference` 从 PR #16 的 `37114b64c6f85c295ab7f69885dc9e8ee09fdee6` 创建，PR 目标为 `feature/4-vision-r0`，属于 stacked PR。不合并 #16，不改 #15，不修改生产代码、数据库或配置，不制作比赛材料。与早期同名 ROI 阶段报告区分，本文件是 **2026-10-26 Vision R1 多参考实验**。

## 预先固定的方法

所有参考使用登记时固定的物体 ROI，搜索始终输入完整图像。单参考基线使用 manifest 预先指定的 baseline_reference_id；多参考逐张调用未修改的生产 ImageMatcher，ORB、特征质量、匹配、RANSAC 和几何阈值全部保持。没有新模型、训练或 YOLOE 接入。

实验聚合额外限制（v1，先于真实实验固定）：

- 每实例最多 6 张参考；哈希校验，记录清晰度、关键点数及每张登记结果。原图哈希重复、参考与场景相同字节、未确认身份、未审查 ROI 均不能成为多参考接受证据。
- 至少两张质量合格的参考来自不同 capture_id、不同 view_id，且 visible_surface 相同。两张 ROI 的 64 位 dHash 距离必须大于 4。unknown 视角/表面/采集信息不能投票。dHash 仅过滤明显重复，不证明独立采集，也不能可靠识别所有近重复。
- ROI 的人工 background_review 必须为 object_dominant；pending/background_risk 禁止投票。此字段是参考图审查，不是搜索图标签；矩形裁剪仍可能残留背景，绝不保证身份。
- 至少两张上述参考各自通过原几何规则，且所有有效参考产生的接受框两两 IoU≥0.5；不同表面的投影不可当成同一个完整物体框。冲突框一律拒绝，不挑选有利子集。返回实际某张支持参考的框（固定 reference_id 字典序），不合成新框。
- 可登记其他实例作为 rival controls；任何 rival 在目标位置通过几何验证则拒绝 ambiguous_instance。若 rival 参考全部不可用，拒绝未完成的对照，不能借助无效控制宣称无干扰。没有 rival 时明确标记未覆盖；相同外观复制品仍可能误接受。

以上是保守工程假设，可能显著降低召回。新视角只在具有重叠可见表面、两个独立参考均能支持同一场景位置时有机会通过；不适用于单张可见参考或互不重叠的表面。重复拍摄同一背景也可能通过一致性验证。不能将规则本身当成背景误报已经解决的证据。

实验输出只有 EXPERIMENTAL_ACCEPTED / UNKNOWN。单参考原始 FOUND 仅保存在私有诊断中并映射为实验几何接受；不写入生产 FOUND、SearchCore、AgentService 或 SQLite。多参考输入不足时 executed=false，单张几何尝试仍记录，不能将未运行计为成功负例。

## 数据合同

机器可读取示例见 `examples/vision_r1/manifest.example.json`；精确字段由 `tools/vision_r1.py` 校验，拒绝额外字段，尤其搜索标签/真值框。所有路径为 data-root 内相对路径，输入哈希必须匹配；真实输入/输出仅允许 Git ignored 目录。输出目录已存在时拒绝覆盖。

顶层 schema_version=1、objects、scenes。objects 中每项含 object_instance_id、baseline_reference_id、references。实例 ID 是稳定、不含个人信息的物理物品登记编号，不能用类别名代替身份核查；baseline_reference_id 在实验前选定。每个参考必须包含：

|字段|定义|
|---|---|
|reference_id / object_instance_id|唯一参考 ID / 所属登记实例|
|path / sha256 / roi|原始文件、原始字节 SHA256、原图坐标整数 xyxy 半开矩形|
|view_id|预先登记的视角名称，如 front_left；不得用检测结果补填|
|visible_surface|投影可比较的同一表面，如 front_panel；unknown 不投票|
|capture_id|真实独立拍摄编号；unknown 不投票，不能用裁剪/增强冒充独立拍摄|
|source_type|real / synthetic / augmented，来源分开统计|
|identity_reviewed / roi_reviewed|人工确认登记身份和固定 ROI；不是模型推断|
|background_review|pending / object_dominant / background_risk；不能由搜索标签生成|

scenes 每项只含 sample_id、object_instance_id、path、sha256、source_type。质量字段是程序输出：sharpness、keypoints、quality_pass、eligibility_reasons、elapsed_ms；不能由 manifest 伪造。输出原图坐标框，原图尺寸、哈希、方法版本、参数、源码 SHA256、commit、环境和耗时均存档。

独立 labels 文件只在全部推理完成、私有预测写盘后读取。每项含 sample_id、label(positive/negative/uncertain/auxiliary)、source_type、split(diagnostic_reused/independent_test/software_fixture)、capture_batch、人工 target_box 或 null、box_source(human/none)、instance_reviews（按 method 的 correct/wrong/null）。同一场景不同方法的实例审查不能混用。禁止把预测框写成真值。

## 本轮可运行范围

现有 24 张图片仅有 4 张已指定参考、20 场景：6 正、8 负、5 不确定、1 辅助，全部历史复用。不重新切分，不把场景提升为参考，不编造视角或身份。可复现单参考 ORB ROI 和逐参考诊断；多参考正式试验待负责人提供新登记照片，当前应报告不足而非得分。合成 fixture 仅验证软件分支，绝不作为真实识别证据。

## 后续冻结与验收

每件优先目标建议补 2–3 个不同视角，每个需要至少 2 张不同背景的独立登记照，覆盖可重叠的物体表面，最多 6 张；不要只追加无纹理背面。负责人标明真实实例身份、视角、表面、capture_id 并审查 ROI。先在开发集评估，不承诺多参考必然有效；若只有一张匹配，保持 UNKNOWN 并记录原因。

开发算法/参数/参考集冻结并记录哈希后，再另采至少两个独立批次，总计至少 6 正、8 负，排除与登记/开发近重复；包含木纹空背景、相似错误实例、小目标、遮挡。测试标签与框只用于事后评估。6 正至少 5 个正确实例定位 IoU≥0.5，8 负零错误接受，实例 precision≥0.95；零接受 precision 未定义。超过 6 正时正确定位召回须≥5/6。未执行/未审查项全部列出且不能通过验收。软件检查不代替人工核查“独立采集”和冻结历史。

即使达标也仅限该物品和受限场景。当前生产识别能力 BLOCKED，YOLOE NO_GO。本轮不会宣称已改善真实家庭识别。
