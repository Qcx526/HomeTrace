# 自定义地点与新增实拍诊断：Issue #42

2026-10-31，基于未合并 PR #41 的 `e14569f018188464e225296d705afe38c293bc7a`，在 `feature/42-workspace-locations` 增量实现，目标分支为 `feature/40-owner-memory-restart`。关联 [Issue #42](https://github.com/Qcx526/HomeTrace/issues/42)，不合并上游或本分支。

## 本轮结论

工作区可以使用自定义地点，不再只能选择原来的三个演示地点。新运行保存自己的地点快照，服务重启或配置修改不会把旧会话里的地点改成另一个名称。旧工作区缺少配置时仍使用原三地点，旧运行没有快照时也只回退原三地点。

新实拍包实际包含 8 张照片，主人文件名标注为 6 张目标出现、2 张目标缺席。固定已批准单参考 ORB 在 8 张全图中都没有给出合格框；授权的 8 次视觉比较得到 4 张外观相似、1 张不确定、1 次无效响应、2 张未见目标。**没有实例身份确认、没有新检测框、没有自动 FOUND；独立家庭识别仍未通过。**

本轮真实照片比较是独立顾问调用，不是一次完整的实际 Agent 搜索。自定义地点的工具执行与恢复通过离线脚本模型、实际 SQLite 回归验证；浏览器只验证配置与结果页面，不将这些证据合并说成完整实拍闭环。

## 最小实现和配置

在 Git ignored 的家庭工作区内创建 UTF-8 `locations.json`，再用该工作区启动现有 Demo。例如以下名称全部为软件样例：

```json
{
  "version": 1,
  "locations": [
    {"location_id": "alpha-table", "location_name": "样例桌"},
    {"location_id": "zeta-shelf", "location_name": "样例架"}
  ]
}
```

```powershell
python -m hometrace demo --photo-vision-agent --port 8770 --household-dir artifacts/my-home
```

- 配置只在服务启动时读取。最多 10 个地点、16 KiB，ID 与规范化名称唯一；非法 JSON、重复字段、未知字段、控制字符、非法 ID、符号链接等明确拒绝，不静默回退。
- 缺少文件兼容旧默认。地点 ID 与名称应保持稳定，不用同一个 ID 表示另一地点。已有记忆层仍拒绝同 ID 对应冲突名称；本轮不做自动重命名或地点合并。
- `household_locations.py` 集中加载和验证；`HouseholdService` 返回本工作区配置；`PhotoFlowService` 在新运行里保存 `location_snapshot`。
- 记忆确认、历史优先规划、模拟导航、Agent 上下文、合法工具地点与视觉反馈摘要都使用运行快照。旧运行缺快照回退旧默认，存在但损坏的快照明确报错。
- 退出当前配置的场景不进入新运行或当前配置列表，旧图片、历史与旧运行不删除。旧运行恢复仍使用原场景快照。
- 页面原有地点下拉框按配置动态显示，无需重写 UI。名称作为文本渲染，模型上下文仍使用原有文本脱敏约束；LLM 自主选择工具，服务校验实际地点。
- 最多地点数不等于搜索预算。原 `max_viewpoints`、工具/模型调用上限、逐次图像授权、重放保护及主人确认要求不变。配置超过预算时，单次运行未必能遍历所有地点。

未修改 ImageMatcher、SearchCore、视觉阈值、SQLite schema 或此前冻结实验。新增字段仅在既有运行 JSON 中保存。

## 私有数据审计与方法

压缩包有 8 张 3072×4096 JPEG，均正常解码；中文文件名按原 ZIP 字节的 GB18030 编码恢复。提取时校验文件类型、路径边界、体积与 CRC，提取后逐文件 SHA256 与包内字节一致。原图不裁剪、不重编码，没有与之前输入完全相同的文件；没有可核验的 EXIF 拍摄时间，采集时间、批次、移动顺序与当前实物地点继续 unknown。哈希不同不证明拍摄独立性，本批作为开发诊断使用。

地点和目标出现/缺席标签来自负责人文件名；数值真值框没有审核，不计算 IoU、正确定位率或实例 precision。主人另外确认新数据中的一处桌面与旧记忆地点不同，本地配置保留不同 ID，不将名称相近当作同一个地方。真实文件名、地点、图像哈希、标签、原始响应和参考身份仅存本机。

本地诊断调用现有 `ImageMatcher`：固定之前已批准的 ref1 ROI、默认 ORB 参数、seed=0、threads=1；搜索场景使用原始完整图片，未按真值裁剪，没有降低阈值或挑换参考。记录匹配点、内点、几何支持、坐标、实际耗时及拒识原因。

模型比较前准备固定参考 ROI 和 8 张完整场景的去 EXIF JPEG 副本，最长边 1280。负责人对这批数据及当前第三方网关明确授权最多 8 次，每张一次、零重试。复用 `tools/run_vision_advisor.py` 和原有授权账本。模型输入只有匿名编号与图片，没有文件名、地点、存在标签或真值框；标签在返回后单独比对。本批额度全部用完，没有将授权复制到交互 Demo。

## 逐样本实际结果

| 匿名样本 | 主人标签 | ORB 匹配/内点 | ORB 拒识原因 | 视觉建议 | 后续建议 |
|---|---|---:|---|---|---|
| scene-01 | 出现 | 44 / 30 | 参考支持范围太局部 | similar | 主人核对 |
| scene-02 | 缺席 | 7 / 0 | 有效匹配点不足 | not_visible | 继续寻找 |
| scene-03 | 出现 | 4 / 0 | 有效匹配点不足 | ERROR | 未执行有效判定 |
| scene-04 | 出现 | 11 / 0 | 有效匹配点不足 | uncertain | 补拍近景 |
| scene-05 | 缺席 | 9 / 0 | 有效匹配点不足 | not_visible | 继续寻找 |
| scene-06 | 出现 | 10 / 0 | 有效匹配点不足 | similar | 补拍近景 |
| scene-07 | 出现 | 8 / 0 | 有效匹配点不足 | similar | 补拍近景 |
| scene-08 | 出现 | 26 / 8 | 几何内点不足 | similar | 补拍近景 |

8 次本地原始匹配均为 SUSPECTED、bbox=null；网页照片执行层对没有框的匹配保持 UNKNOWN，不能借 SUSPECTED 名称开放一个不存在的本地候选框。局部纹理支持和几何不足是当前单参考方法的实际限制。

视觉接口实际调用 8 次、有效意见 7 次、共 21001 Token。scene-03 的 `finish_reason=length`，2048 个输出 Token 被接口记为 reasoning_tokens，text_tokens=0，没有有效 JSON。该条按失败计入，消耗的调用与 Token 均保留，不增加额度重试。模型请求标识由已配置兼容接口记录，不保证其底层模型身份。

4/6 正例得到相似外观意见不等于 4/6 实例确认；另外两张分别为不确定和失败。2/2 负例未见目标仅说明这两张图的意见正确，不证明一般误报率为零。小目标、角度变化和遮挡仍会让顾问要求近景。完整脱敏数值见 [逐图记录](evidence/issue-42/photo-results.json)。

## 本地 Demo 准备与浏览器验证

新建独立工作区，复用已批准参考，导入 8 张原图，并配置 7 个不同地点（旧历史地点和新图中的 6 处）。通过 SQLite backup 复制原主人记忆，源数据库哈希不变；新工作区没有新增主人事件、运行或视觉证据。只配置一个明确的开发场景组合：一处缺席、另一处出现；其余已导入图片不被假称为同时发生的当前观察。文件名不决定当前地点，不用离线顾问输出自动填写运行状态。

实际浏览器已显示全部自定义地点、旧/新桌面分别列出、两张配置图及尚未开始状态。另一个只读页面逐张显示原图预览、原始模型建议、失败和无本地框状态。没有点击发送、确认候选或新图片外发；页面加载不计模型调用。截图和原始界面内容因含私人照片/地点不进入公共 PR。

## 验证及可复现入口

实际环境为 Windows、Python 3.11.4 的既有可选 Agent 环境，Node v24.18.0。命令：

```powershell
.\artifacts\issue-11\agent-env\Scripts\python.exe -X utf8 -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
# 需要新批次的明确图像授权；已消耗授权不可重复执行
python tools/run_vision_advisor.py --manifest artifacts/PRIVATE-BUNDLE/manifest.private.json --consent artifacts/PRIVATE-BUNDLE/consent.private.json --output-dir artifacts/PRIVATE-NEW-RESULT
```

本地匹配复现使用 `ImageMatcher(reference_path, reference_hash, object_id, image_root, reference_roi=approved_roi)` 和 `detect_target(Observation(...), object_id)`，按输入 SHA256 验证完整原图。采集时间为 unknown；诊断时间字段不是实际拍摄声明，不写生产证据。具体原图映射、已用授权、模型响应、执行脚本和私有准备记录均保留在本机 ignored 目录供负责人核对；公共材料不包含这些隐私绑定。

新增工作区测试首次为 26 passed / 1 failed：当前配置还列出退出配置的旧场景。修复显示过滤后 **27 passed**，旧数据未删除。随后联合全量 **1061 passed、1 warning / 155.35 秒，退出码 0**；前端 **22 passed**。所有测试都是离线软件回归，不靠模型随机输出通过；未重做全新 Windows 安装。完整日志见 [evidence/issue-42](evidence/issue-42/)。

下一步需要围绕有效视觉建议完成一次明确标记的 Agent 场景重放与主人核对，并处理无效模型响应的可理解提示；如需新图片比较，须有对应的新授权。仍不能以本轮测试数或顾问外观意见宣称真实寻物已全部验收。等待代码与证据审查，不自行合并，不整理或宣称正式参赛包完成。
