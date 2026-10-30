# 实拍水杯 Agent 验收：Issue #36

本阶段基于 PR #35 的 `ed2693bef36636f5a1b42a63ed9588522f6ff65f`，在 `feature/36-real-cup-agent` 开发，目标分支为 `feature/34-visual-agent-loop`。这是 stacked PR，未合并 main，也不改写此前视觉实验结论。

## 本轮输入与边界

使用负责人已批准的第一张参考图及其固定 ROI，另有八张已有开发场景和两张负责人提供的补充视角照片。所有输入均为真实照片，但已参与探索，属于 `diagnostic_reused`；独立测试样本数为零。固定参考在本轮推理前选定，没有根据本轮返回结果择优选图。当前页面每个物品只使用一张参考，不能套用此前六参考诊断的结果。

原图、原始路径、ROI、输入哈希、授权和完整输出只留在 ignored 目录。采集时间、采集批次和实际地理位置未核实时仍为 unknown。“书房桌面”是程序验收中的演示地点映射，不是从图片推断出的真实放置地点；本轮不生成历史放置记忆。

负责人在本轮明确允许：固定参考 ROI 与这十张场景，经现有第三方兼容网关最多比较十次，每张场景最多一次，不重试。传输的是去元数据、最长边 1280 像素的 JPEG 副本，场景不裁切。网关仍能看到桌面背景；去 EXIF 不等于移除画面内容。此授权独立于已经耗尽的旧十次授权。

## 执行合同

1. 本地准备器先核验清单、原始字节哈希、解码和参考质量，再从全新目录登记物品与固定参考。逐图真实运行现有 `PhotoSearchEngine`，不联网、不写位置记忆。
2. 联网验收器通过真实 `VisualPhotoAgentService` 执行决策和工具，按具体请求核对原图/副本哈希、网关、模型和持久授权账本。脚本发起的场景映射和授权动作单独记录；不能把这种服务接口验收称为全程浏览器操作。
3. 统一请求限定本次演示地点，要求先本地观察再请求全图比较；模型在真实反馈后决定补拍、请主人核对或停止。这个提示限制必须计入能力边界，不能声称完全无提示的自主策略发现。
4. 补充视角只有在 Agent 请求时才接入原 run；否则单独比较并标记为独立的开发场景。没有实际补图请求就不能宣称展示了反馈补拍闭环。
5. 实拍候选停在 `AWAITING_REVIEW`，交主人审核。脚本不点击 `accept_candidate`，不写 `owner_reported` 位置，不将顾问 `similar` 升级为物理实例确认或 `FOUND`。
6. 全部失败、未执行、等待补拍和未核对项均保留。原始模型输出不含可信定位框；只有既有本地匹配器实际产出的框可以作为待审核外观框。

本轮不训练网络，不改 `ImageMatcher`、`SearchCore`、Agent 生产决策模块、SQLite schema 或阈值。没有人工批准的数值 Ground Truth 框时，不计算或宣称 IoU 达标。

## 实际结果

2026-10-30 实际执行完成。十张场景各调用一次视觉顾问，**10/10 返回合法结果，无重试**；九个寻物会话共 **38 次决策调用、69596 决策 Token**，另有 **22323 视觉 Token**。视觉请求耗时 3.642–11.514 秒，中位数 6.401 秒。配置中的决策请求重试次数原为 1，本验收器仅对当前进程显式覆盖为 0；生产配置不变。第三方返回的模型标识与请求一致，仍不能证明底层模型身份。

单参考本地匹配在十张图上均无有效框，进入 Agent 的观察状态均为 UNKNOWN。弱匹配 SUSPECTED 但无框的原始诊断仍保留，未用于开启确认。以下匹配点/内点均来自实际匹配；0 内点可能表示在几何估计之前已拒绝，不等于运行了所有几何步骤。

| 场景 | 原有主人存在性标注 | 匹配点 / 内点 | 本次云端意见 | Agent 实际选择 |
|---|---|---:|---|---|
| dev1 | 目标出现 | 3 / 0 | similar | 要求补图；无本轮可用补图，保留等待 |
| dev2 | 目标出现 | 6 / 0 | similar、建议近景 | 要求补图；保留等待 |
| dev3 | 目标出现 | 11 / 0 | similar | 等待主人核对，无框 |
| dev4 | 目标出现、遮挡 | 12 / 4 | uncertain | 请求补图，实际接收 dev4_side 后再次比较 |
| dev5 | 目标缺席 | 7 / 0 | uncertain | 要求补图，未请求确认 |
| dev6 | 目标缺席 | 12 / 4 | not_visible | 仍要求补图，未请求确认 |
| dev7 | 目标缺席 | 6 / 0 | different | 结束为 UNKNOWN |
| dev8 | 空场景 | 9 / 0 | not_visible | 仍要求补图，未请求确认 |
| dev3_close | 补充照片，本轮单列不正式评分 | 20 / 5 | similar | 独立会话等待主人核对 |
| dev4_side | 补充照片，本轮单列不正式评分 | 0 / 0 | similar | 原 dev4 会话等待主人核对 |

dev4 真实执行了：本地观察 → 批准首图比较 → uncertain → LLM `request_new_photo` → 上传负责人既有侧面补图 → 新证据、本地重新观察 → 第二次授权比较 → similar → LLM `request_owner_review`。两次观察的输入哈希和 Core evidence ID 均不同。补图是既有负责人实拍，不是本轮自动拍照；没有强制指定模型必须请求补图。dev3 则没有请求补图，其 close 图按合同单独运行，不能把它计为同一会话的补拍成功。

八张已有主人存在性标注在推理结束后才用于核对：四张正例中三张 similar、一张 uncertain；四张负例中两张 not_visible、一张 different、一张 uncertain，**零负例进入主人候选确认**。这只是外观建议与存在性标注的对照，不能换算为实例定位 precision/recall 或“识别率 100%”。补充照片未据模型输出新增 Ground Truth。最终九个会话为：3 个等待主人核对、5 个等待补图、1 个 UNKNOWN；**无人自动确认，零位置记忆写入，零 FOUND**。

失败与不足：本地 ORB 无框的问题仍在；侧面图清晰度诊断为 29.933，低于现有门槛，未调整门槛；dev5 的局部相似干扰导致顾问 uncertain。dev6/dev8 已获 not_visible 建议，决策模型仍请求补图，说明停止/换地点策略需要收敛。dev1 即使顾问建议核对，决策模型仍要求近景。这些选择保留原样，没有重试直到出现理想轨迹。

联合全量回归：**964 passed，143.83 秒，1 项 LangGraph 依赖弃用警告**；前端 **21 passed**。新增 60 项是明确的软件 fixture/协议测试，不是实拍识别证据。已实际检查本地浏览器审查页，补图、无框提示、云端建议及会话关系显示一致；真实 Agent 请求由服务接口脚本执行，浏览器仅用于查看，不称全程网页交互验收。

公开逐样本脱敏指标、源码哈希和日志见 [evidence/issue-36](evidence/issue-36/)。含图页面、输入清单、授权账本、原始运行 JSON、SQLite 和截图只在 `artifacts/issue-36/`。旧报告及生产模块均未改动。

## 可复现命令与数据合同

```powershell
python -m pip install -e ".[dev,vision,agent,vision-advisor]"
# 纯本地。output 必须是此前不存在的 Git ignored 目录。
python tools/prepare_photo_acceptance.py --manifest artifacts/issue-36/input.private.json --image-root artifacts/issue-36/inputs --output-dir artifacts/issue-36/prepared-NEW
# 明确联网；必须有新的有效授权。当前本轮 consent 已使用完，命令不可用于再次发送。
python tools/accept_private_photo_agent.py --prepared artifacts/issue-36/prepared-NEW/prepared.private.json --consent artifacts/issue-36/NEW-consent.private.json --output-dir artifacts/issue-36/live-NEW
# 仅生成离线审查页，不调用模型。
python tools/report_private_photo_agent.py --prepared artifacts/issue-36/prepared-01/prepared.private.json --summary artifacts/issue-36/live-01/summary.private.json --output-dir artifacts/issue-36/review-NEW
python -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
```

准备清单采用 `schema_version: 1`、`source_kind: real_upload`、`scope: diagnostic_reused`。`object` 包含 `object_id/name/aliases`；`reference` 包含相对 `path/sha256/roi/roi_reviewed/identity_reviewed/review_source`；`scenes` 是 `sample_id/path/sha256/location_id` 列表。未映射到三个固定演示地点的 `location_id` 为 null。场景清单不包含答案或目标框。所有路径限制在显式 image-root 内；尺寸、解码、审核、参考质量或哈希不符时在建立工作区前拒绝。

授权文件单独包含 `schema_version/approved/review_source/endpoint/model/max_calls`、`reference_sha256/reference_derivative_sha256`、`scenes[{sample_id,sha256,derivative_sha256}]`，以及可选 `followups` 映射。它必须来自本轮实际人工批准，不是生成配置就等于获准。验收器在批准请求前持久记录一次性额度，失败不退还；授权文件绑定一次运行，不能换输出目录或复制账本绕过已用额度。进程崩溃后的锁不会自动清除或重试。

三个工具只新增在 `tools/`，没有生产接口变更。准备器与报告器均不读 Key、不联网；联网验收器才读取本地配置。所有图片输出路径也必须被 Git 忽略。报告器只从已校验资产产生去 EXIF 的本地预览，对正文转义，没有上传/确认按钮。超时和异常执行有有限版本刷新取消，保留已发生调用，绝不代替主人确认物品。

## 验收结论与下一步

软件层面已取得一条真实实拍的“无法确定 → 补充视角 → 外观相似 → 等待核对”反馈证据，满足本阶段增量审查条件；没有证明自动定位或唯一物理实例识别已经可交付。独立实拍验收、自动定位及实例能力仍为 **BLOCKED**。

下一步优先把 Agent 的停止与补拍决策收敛成清晰的用户体验：明确区分目标细节不足和本图未见目标，减少对负例反复要图；保留模型抉择与人工核对。随后由负责人在待核对照片上确认/拒绝，再以真实主人陈述运行记忆闭环。新的图像外发需新的授权额度；不使用本轮已耗尽的授权。待方案冻结后再采集独立照片，不能把这些反复查看的开发图重新命名为测试集。
