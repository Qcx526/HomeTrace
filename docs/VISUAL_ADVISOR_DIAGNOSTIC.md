# Issue #32：DeepSeek 视觉顾问与家庭照片诊断

2026-10-29。分支 `feature/32-visual-advisor`，基于 PR #31 的 `feature/30-deliverable-acceptance` / `1c87851aaa59b169b7b930f9ead0af3c13565217`，属于 stacked PR。未合并上游，不修改生产识别、Agent、SQLite、默认隐私配置或历史实验结论。

结论：**GO 继续开发受限视觉顾问；自动实例确认和完整识别验收仍 BLOCKED。** 当前网关确实接受图像，并在这批复用开发照片中给出了有价值的外观比较及补拍建议。此工具没有预测框，不输出 FOUND，也没有接入网页的实时 Agent。不能把场景级文字判断当成正确定位，或与 YOLO + DINO 的框级指标直接比较。

## 输入与实际执行

官方文档当前说明 `deepseek-flash` 支持图像输入，服务于 V4.1 Flash 系列；本项目没有切换到官方直连接口。实际调用沿用配置的第三方兼容网关和 `deepseek-v4.1-flash-1017`，返回模型名相同。能力分别核实：[官方 Vision 文档](https://api-docs.deepseek.com/guides/vision/)、[当前模型说明](https://api-docs.deepseek.com/)。

先用不含私人内容的软件绘制几何图探测。首次回答因 400 输出 Token 上限截断，保留为不完整记录；随后固定 2048，两个不同图案均完整正确回答形状、颜色和左右位置，分别耗时 3600.054 / 2410.033 ms。这是接口能力验证，不是家庭物品实验。

负责人随后明确授权：6 张已批准的杯子参考 ROI、10 张开发场景缩小副本，经当前网关最多比较 10 次。授权内容、端点、模型和输入清单哈希绑定于本地 consent。参考取已批准 ROI；场景保留整幅画面，最大边 1280、JPEG quality 90、去除 EXIF。未按已知目标位置裁剪场景，未向模型发送人工标签、已知框、文件名、物品实例 ID、历史位置或旧模型结论。每次均为相同 6 张参考 + 1 张场景，不做对话累积。

实际完成 10 次网络调用、10 个有效结构化响应；无重试、无训练、无机器人动作。总计 **48117 Token**，单次耗时 3867.352–16744.922 ms，中位数 10722.918 ms。这是一次真实运行的观测值，不保证重跑一致；网关实际后端权重与随机性无法由本地验证。3 次软件探针与 10 次家庭调用分开记录，不混成识别样本。本机使用 Python 3.11、openai 2.54.0、httpx 0.28.1、Pillow 12.0.0、langchain-openai 1.0.1；图像理解在远端执行，没有使用本地 GPU 训练。

## 逐场景结果

下表 D01–D08 对应此前负责人审核的 8 张开发场景；D09–D10 为后续近拍/侧拍。公开表使用匿名索引，含图结果及原始回答仅留本地。

| 场景 | 已有人工信息 | 模型外观判断 | 模型建议 | 耗时 ms |
| --- | --- | --- | --- | ---: |
| D01 | 目标出现 | similar | 请主人核查 | 13538.307 |
| D02 | 目标出现 | similar | 补拍近景 | 6936.895 |
| D03 | 目标出现 | similar | 请主人核查 | 11853.217 |
| D04 | 目标出现、遮挡 | uncertain | 补拍近景 | 14133.697 |
| D05 | 目标缺席 | not_visible | 继续搜索 | 16744.922 |
| D06 | 目标缺席 | not_visible | 继续搜索 | 4992.184 |
| D07 | 目标缺席、其他外观 | different | 继续搜索 | 3867.352 |
| D08 | 空目标场景 | not_visible | 继续搜索 | 4905.877 |
| D09 | 后续近拍，单列开发诊断 | similar | 请主人核查 | 12215.155 |
| D10 | 后续侧拍，单列开发诊断 | similar | 请主人核查 | 9592.619 |

先推理，再读取已有人工标签做离线统计：原 4 张正例中 3 张为 `similar`、1 张为 `uncertain`；仅 2 张直接建议主人核查，另一张相似但仍要求近拍。原 4 张负例中 **0 张为 similar，0 张建议主人接受或核查候选**。两张补拍均为 similar，但不能加入原数据后声称完成独立 6 正例验收。

这里的 3/4 是“外观相似建议比例”，不是正确定位召回率。没有模型框和审核数值真值，IoU、实例 precision 及自动 FOUND 的 TP/FP/FN **均不适用**。确认物理身份数量为 0。所有图片都已参与开发；独立测试数量为 0。

## 失败机制与方案选择

本地共享检测/特征实验曾在 D03 没有获得可接受类别候选，近拍 D09 获得框但全局特征拒识。本次视觉语言模型能够比较这两张场景的外观，说明值得将它用于解释和观察决策；不能据此宣称已经修复检测框或实例检索。

D04 遮挡场景仍为不确定，模型选择补拍。D10 侧拍得到相似建议，支持“获取更多有效观察”这一开发方向。但补拍在调用前已经由用户提供，本轮只是逐图独立请求，**没有执行自主请求补拍 → 获取新图 → 再决策的在线闭环**。不能把这两次回答包装成已完成的 Agent 自主行为。

当前方案利用已有共享视觉语言模型，无须为每个登记物品重新训练。它可以提出可见特征、遮挡和下一步建议，仍可能幻觉、混淆同款物品、错误声称没看到目标；未经过同款不同实体、独立拍摄批次或广泛日常物品验证。文字字段全部为模型意见，不能直接写入权威位置/身份/记忆。

下一步最小集成应保留显式照片授权，增加受限 `visual_advice` 工具、等待新图片状态和新 asset 绑定，再由 Agent 选择补拍、换地点或请求主人确认。原有重放保护、预算、取消与版本检查继续有效。实际 API 的图像权限不能因本轮一次性授权自动对所有照片开启。

## 代码与保护

- `tools/vision_advisor.py`：固定提示、图文 payload、严格 JSON schema，包装始终是 `ADVISORY_ONLY` / `identity_confirmed=false` / `production_status=UNKNOWN`。模型无提交框、写记忆或执行命令入口。
- `tools/run_vision_advisor.py`：严格无标签输入、文件哈希、仅 Git ignored 路径、授权端点/模型/清单绑定、整批原子额度预留、不重试、不跟随 HTTP 重定向。按参考/场景角色、实际图片哈希集合及提供商/模型锁定同包额度；失败与中断不退还，换输出目录、JSON 排版或图片 ID 不能重置。授权文件必须来自人工批准，不能把本地可编辑文件误称为权限隔离或认证系统。
- `tests/test_vision_advisor.py`：纯离线软件契约，包含篡改输入、重放、假 FOUND、额外框、恶意文字、无授权、重复预算、超时/截断、元数据与图片尺寸等；测试夹具不是真实识别证据。

完整模型回答只写本地私有 JSON。控制台只打印索引、枚举建议、耗时与安全错误。首次实际执行版曾在控制台打印模型解释，本地记录保留；提交版已收紧为枚举。后续还加强了 JPEG 解码、最大尺寸、元数据拒绝和旧额度账本迁移；没有改变提示、图像 payload、请求参数或输出判定。

实际执行源码已保存本地快照并在调用前记录 SHA256：runner `fc3a8c7ae9ea95b6a8926a2970b3e41b4835a5947416baca56c3fbd1181ed293`，advisor `9bb6e2e58f1c7e6f46095977b1303522ac092b12dd343fd4beb61129635ec945`。后续离线核对全部 10 次 payload、全部 10 个解析结果一致；原图、外部补拍原件与冻结历史输出哈希保持不变。共 73 个一致性检查，不计为识别测试。授权 10 次已经用完，未为验证加固版本重新发送照片。

## 运行与复核

实验需要已有 `[agent]` 环境及 Pillow；本机沿用原有环境，不新增生产依赖或大模型。输入与输出必须在本地 Git ignored 目录。清单是严格结构：

```json
{"schema_version":1,"source_type":"real","references":[{"id":"r1","path":"local_data/approved-reference.jpg","sha256":"<SHA256>"}],"scenes":[{"id":"s1","path":"local_data/full-scene.jpg","sha256":"<SHA256>"}]}
```

图像应为已审查的参考 ROI / 完整场景 JPEG 缩小副本，无 EXIF/XMP，最大边 1280；原图另外留存。consent 必须包含 `schema_version:1`、`approved:true`、准确 `endpoint`、`model`、清单原始字节的 `manifest_sha256`、`max_calls`（1–10）及真实 `approval_source`。只有负责人授权才能建立；不得复制示例当成新授权。

```powershell
# 本次实际命令；已用完授权，不可重跑来刷新额度。
artifacts/issue-11/agent-env/Scripts/python.exe tools/run_vision_advisor.py --manifest artifacts/deepseek-vision-20261029/input.private.json --consent artifacts/deepseek-vision-20261029/consent.private.json --output-dir artifacts/deepseek-vision-20261029/household-01

# 离线回归，不使用 API
artifacts/issue-11/agent-env/Scripts/python.exe -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs
git diff --check
```

本地原始结果：`artifacts/deepseek-vision-20261029/household-01/`；后验统计：`posthoc-02/`；只读含图审查页由本机已有静态服务提供 `/vision-advisor-01/index.html`，页面不执行 Agent、不发新请求。原始响应、图片、批准文件、原图哈希和路径都不进入公共 PR。公开脱敏指标见 [运行摘要](evidence/issue-32/diagnostic-summary.json)。

本地静态页与 10 张图的 HTTP 请求全部为 200；本轮未完成真实浏览器交互验收。

最终一次联合 Python 回归 **858 passed、0 failed、1 条既有 LangGraph 警告，119.03 秒**；其中原 781 项全部保留。新增 77 项均为离线软件契约，不是照片识别次数。Node **8 passed** 单独记录。

首次全量运行是 **854 passed、1 failed**：既有 `test_external_control_rejected[headers1]` 服务端已记录 403，但客户端读取发生 Windows `ConnectionAbortedError / WinError 10053`。保留失败日志；未修改该测试或服务端，独立复跑该 HTTP 文件 **11 passed**，再执行上述最终全量回归。属于本次未重现的连接失败，不能据此认定根因已消除。

测试日志、初次失败与最终源码审计见 `docs/evidence/issue-32/`，仅替换本机绝对路径前缀并去掉行尾空白，原始日志留本地。`git diff --check` 与隐私扫描通过；仅新增实验工具、测试和报告，生产代码、配置、数据库 schema、历史冻结报告均无变更。代码可提交隔离实验审查，是否合并由负责人决定。生产视觉验收、独立样本和网页视觉顾问集成都仍未完成。
