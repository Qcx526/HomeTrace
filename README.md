# HomeTrace — 家庭物品记忆与主动寻找

HomeTrace 把物品参考、位置历史和当前图片放入同一个持久工作区。真实 LLM 理解请求、调用记忆工具，并根据本轮观察或主人拒绝选择下一处地点；本地视觉提出候选，由主人核对。

**新增可选视觉 Agent 闭环（Issue #34）**：LLM 可请求看图、依据视觉建议决定补拍或继续搜索；每张场景单独批准外发，最后由主人核对并保存位置。启动与实际证据见 [视觉 Agent 说明](docs/VISUAL_AGENT_LOOP.md)。本增量叠加在未合并的 PR #33 上，未发布到 main。

**实拍杯子验收（Issue #36）**：已实际完成十次有界视觉比较和一条遮挡补图反馈链，未自动确认身份；本地检测框与独立实拍验收仍未通过。逐图结果、复现工具和限制见 [实拍 Agent 验收报告](docs/REAL_CUP_AGENT_ACCEPTANCE.md)。

**视觉反馈决策调整（Issue #38）**：减少未见目标和可由主人核对时的不必要补拍。十二次真实文本调用在六组软件场景中完成旧/新配置对照；不代表实拍识别提升，详情见 [决策调整与验证](docs/VISUAL_AGENT_DECISION_REFINEMENT.md)。

**位置记忆重启验收（Issue #40）**：已验证主人显式确认后保存位置，重启后由真实文本 LLM 查询同一历史事件；该阶段尚未支持自定义搜索地点，后续扩展见 Issue #42。实际运行、首次预算拦截和脱敏证据见 [记忆重启验收](docs/OWNER_MEMORY_RESTART_ACCEPTANCE.md)。

**自定义地点（Issue #42）**：工作区可用 `locations.json` 配置自己的地点，新运行冻结地点快照，旧运行不被新配置改名。新增 8 张实拍已完成本地与授权顾问诊断，仍没有有效本地框或自动身份确认；配置与结果见 [自定义地点和新增实拍](docs/WORKSPACE_LOCATIONS_AND_NEW_PHOTOS.md)。

**当前是受限软件 Demo，真实家庭实例识别仍未通过验收。** 图片由用户上传，当前位置由用户选择，导航模拟；LLM 不生成检测框或自动 FOUND。合成图片只能用于流程演示。当前开发分支依赖未合并的 PR #29，不能视作 main 已发布或比赛已提交。

## 启动当前 Demo

Windows、Python 3.11+。在仓库根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,vision,agent]"
# 首次配置：在本机 .env 中填写 HOMETRACE_LLM_API_KEY=，不要提交密钥。
# 模型和预算使用 config.yaml；已有 .env 不要覆盖。
.\.venv\Scripts\python.exe -m hometrace demo --photo-agent --port 8770 --household-dir artifacts/my-home
```

打开 [HomeTrace](http://127.0.0.1:8770/)。首次目录为空；再次使用同一 `--household-dir` 会保留登记、历史和证据。服务仅监听本机，停止按 `Ctrl+C`。模型不可用时明确报错，不静默切换为规则执行。不加 `--photo-agent` 是明确标识的规则模式。

1. 登记物品名称和别名，上传参考照片，框选并确认目标区域。
2. 选择“你现在所在的位置”，发送“请记住，蓝色钥匙我放在这里了”，核对后确认保存。
3. 给已配置地点上传场景照片，发送“蓝色钥匙找不到了，帮我寻找”。默认三个地点；自定义地点配置见上方说明。
4. 查看 LLM 实际调用、访问顺序、检测框和工具返回；核对候选，或拒绝后继续寻找。
5. 重启后查看历史。历史是主人陈述，不保证物品现在仍在那里；已使用的旧图片不能成为新的搜索证据。

详细步骤、验收结果和兼容说明见 [当前交付 Demo](docs/DELIVERABLE_DEMO.md)。真实照片请按 [拍摄指南](docs/REAL_PHOTO_CAPTURE_GUIDE.md)准备，先验证你登记的同一件实物，不要求为每件物品训练网络。

## 当前能力与边界

- 持久 SQLite 名称、别名、位置历史、照片参考与证据；支持刷新和服务重启后恢复。
- 真正的 LangGraph / LangChain 工具调用；LLM 选择目标、意图、下一地点与停止，程序负责执行和事实校验。
- 默认 `--photo-agent` 图像只在本地匹配；可选 `--photo-vision-agent` 在每次明确批准后，将参考 ROI 和完整场景的去元数据缩小副本发往页面显示的第三方网关。上传到本机不等于批准外发。
- 默认地点：玄关托盘、书房桌面、客厅茶几；工作区可用 `locations.json` 定义至多 10 个地点，单次搜索仍受原有预算限制。不是实时摄像或自动定位，也没有经过验证的习惯学习。
- 网页使用 ORB 外观匹配，候选为 `SUSPECTED`；主人接受为 `USER_CONFIRMED` / `owner_reported`，不变成自动视觉 `FOUND`。
- 共享神经网络视觉仍是隔离实验，不能将类别框、少量开发成功或合成图演示说成真实家庭通用识别。

LLM 版原验证为 773 项 Python、8 项前端回归，真实 API 22 次调用；本轮整理后的实际结果单独记录在 [验收报告](docs/DELIVERABLE_DEMO.md)，不把历史数量相加。[LLM 实现与历史证据](docs/HOUSEHOLD_PHOTO_AGENT.md)。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
# 可选：需要本机已授权的固定合成素材包和真实 API；输出目录必须不存在。
.\.venv\Scripts\python.exe tools/accept_photo_workflow.py --output-dir artifacts/acceptance-new
```

HTTP 脚本与真实浏览器操作分别记录；离线单元测试不证明识别精度。原图、截图、数据库、模型权重、Key 和私人团队信息均留本地忽略目录，不提交公共 GitHub。

## 目录与交付

- `src/hometrace/`：当前运行逻辑；`web/` 只保留当前页面三份资源。
- `tests/`：全部回归；`tests/fixtures/legacy_web/` 保存旧页面，供显式兼容回归使用，不进入安装 wheel。
- `tools/`：验收、隔离视觉实验和打包工具；实验结果不自动接入生产。
- `docs/`：当前说明与不可覆盖的历史证据，入口见 [历史索引](docs/HISTORY_INDEX.md)。

比赛材料内部目标为 **2026 年 11 月 2 日结束前**完成整理；官方主表、最新 PPT/视频、源码和最终 ZIP 须与审核版本一致。历史材料不是本轮成品，平台格式与实际上传仍需另行核验。本轮不生成或宣称正式参赛包完成。

开发从 Issue 出发，通过 feature 分支与 PR 审查，不直接推送 main，不自行合并。参阅 [AGENTS.md](AGENTS.md)。
