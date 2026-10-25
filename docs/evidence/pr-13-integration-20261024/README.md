# PR #13：合并 main 后的联合验收

2026-10-24，按 [Issue #4 最新 PM 集成顺序](https://github.com/Qcx526/HomeTrace/issues/4#issuecomment-6381943135) 与 [PR #13 复核要求](https://github.com/Qcx526/HomeTrace/pull/13#issuecomment-6381946127) 执行。本记录由开发者实际运行产生，不表示 PM 独立运行或复核通过。

## 输入与源码差异

- main / 已合并 PR #14：`708d8b2ae78bcc488d0e126f5a9fdd27eb303cc1`。
- PR #13 原提交：`e5b8aa74a6560fa5130ac07907f04bb6b32e9f2e`。
- 本次 merge commit：`3c49bec9ae78b136d2bfe191b09a97355fc6a5fb`，两父提交即上述分支与 main。
- 仅 README 发生冲突，已保留真实 Agent 说明、配置启动命令、YOLOE **NO_GO** 与官方 DOCX 边界，并修正 PR #14 已合并状态；`.gitignore` 自动合并且与 main 相同。
- main 的 `src/`、`tests/`、`config.yaml`、`.env.example`、`pyproject.toml`、`.gitignore` 共 **54 个 Git blob** 完全保留。PR #13 原变更中的 **17 个非 README 文件**完全保留，包含视觉工具、测试和冻结报告。没有新增 Agent 架构、视觉模型或检测阈值修改。
- 本目录是新集成证据；`docs/evidence/issue-10/`、`issue-11/` 及此前报告未改写。后续证据提交只新增本目录，不改变已测试的程序或配置。

核对命令（在仓库根目录执行）：

```powershell
git diff 708d8b2 -- src config.yaml .env.example pyproject.toml .gitignore
git diff e5b8aa7 -- tools/neural_contract.py tools/evaluate_yoloe.py tools/yoloe_worker.py tools/requirements-neural.txt tests/test_neural_contract.py tests/test_yoloe_runner.py docs/P4_VISION_EVALUATION.md docs/evidence/issue-10
git diff --check
```

前两条均无差异。[源码核验 JSON](source-validation.json) 记录逐文件比对和实际源码 ZIP 检查。

## 同一合并工作树的全量回归

```powershell
& artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 -m pytest -q --junitxml=artifacts/pr-13-integration-20261024/pytest.xml
```

**424 passed，0 failed，0 errors，0 skipped，77.58 秒。** 这是一次完整测试进程的实际结果，不是独立分支测试数相加。使用同时安装 Agent 与 OpenCV 依赖的环境；GPU 模型依赖仍在独立可选环境。详见 [终端输出（仅工作区路径脱敏）](pytest.txt)、[JUnit 汇总](regression.json)。一条 LangChain 序列化默认参数未来变更警告来自依赖，未出现测试失败；本轮没有为消除警告改动架构。

## 真实 GPU 全量复跑

```powershell
& artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 tools/evaluate_yoloe.py --data-root local_data/team_new_20261023 --output-dir artifacts/pr-13-integration-20261024/yoloe --python artifacts/issue-10/neural-env/Scripts/python.exe --weights artifacts/issue-10/weights/yoloe-11s-seg.pt --protocol artifacts/issue-10/protocol.json
```

24 张原图的 SHA256、尺寸和字节数在前后均验证通过；4 张参考、20 张完整场景，模型、ROI、权重 SHA 与固定参数均未改变。YOLOE-11s / Ultralytics 8.3.221 / PyTorch 2.6.0+cu124 / GTX 1660 上完成 20 次真实推理，全部正常返回。协议中的老基线字段保留，实际集成源码提交另行记录在新 JSON 的 `integration_run`。

| 样本组 | 场景数 | 有候选场景 | 无候选 | 推理失败 |
| --- | ---: | ---: | ---: | ---: |
| 明确正例 | 6 | 2 | 4 | 0 |
| 明确负例 | 8 | 1 | 7 | 0 |
| 不确定 | 5 | 0 | 5 | 0 |
| 辅助 | 1 | 0 | 1 | 0 |

新运行的每个状态、原因、候选框及分数均与冻结实验相同；运行时间重新测量。开发者重新查看三个候选叠加图：正例 `panda/scene_02` 框错大熊猫，负例 `panda/scene_03` 误框大熊猫，只有 `panda/scene_05` 支持小挂件定位。故仍是 **1/6 正例有视觉支持的候选、1/8 负例误候选、0 个实例确认，NO_GO**。这是同一数据的集成复跑，不能扩大样本量或声称泛化改善。

[逐样本脱敏指标、耗时、设备与复核](neural-rerun.json)。私人原图、原坐标框、含图叠加结果仅在 Git ignored 的本地 `artifacts/pr-13-integration-20261024/yoloe/`；未上传，未传给 LLM。生产视觉继续使用 ORB。

## 真实 Agent 与浏览器产物

同一份 main 配置、本地 Key、真实模型 API 与 LangGraph 工具循环；没有 Mock API 或预填工具返回。图像为已有 OpenCV 公共实拍，A/B/C 为演示编排，**导航全部模拟**。FOUND 仅由现有 SearchCore 对当前图片证据判定，不证明家庭物品或机器人运行。

| 实际场景 | 最终状态 / 位置 | 实际访问顺序 | 模型 / 工具调用 | API 报告 Token |
| --- | --- | --- | ---: | ---: |
| moved，浏览器实际点击 | FOUND / V2 | V1→V2 | 7 / 6 | 10190 |
| fair，历史位置 C | FOUND / V3 | V3 | 5 / 4 | 6112 |
| missing | SUSPECTED / null | V1→V2→V3 | 9 / 8 | 14691 |
| replay | UNKNOWN / null | V2→V1→V3 | 7 / 6 | 10236 |

V1/V2/V3 分别映射 A/B/C。公平对照使用相同冻结输入与独立 SQLite：固定顺序 A→B→C 三步、Agent 先读历史后访问 C 一步；这仅证明受控公开样例中历史能改变搜索顺序，不代表实物机器人耗时或家庭搜索效率。

[四次真实工具轨迹](agent-runs.json) · [公平对照](fair-comparison.json) · [浏览器核验](browser.json) · [实际 FOUND 页面截图](agent-found.png)

浏览器使用新启动的端口 8767，避免复用旧进程。实际轮询 21 次，其中 20 次看到运行中状态；页面无异常，实际当前图与画框画布均为 512×384，图片使用本轮 `current-2` URL，移动端横向布局检查通过。录屏和其余截图保留在本地 `artifacts/pr-13-integration-20261024/browser/`。

```powershell
& artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 tools/run_agent_demo.py --goal '请帮我找登记的样例盒子' --scenario fair --output-dir artifacts/pr-13-integration-20261024/agent-fair
& artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 tools/run_agent_demo.py --goal '请帮我找到已登记的公开样例盒子' --scenario missing --output-dir artifacts/pr-13-integration-20261024/agent-missing
& artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 tools/run_agent_demo.py --goal '请帮我找到已登记的公开样例盒子' --scenario replay --output-dir artifacts/pr-13-integration-20261024/agent-replay
& artifacts/issue-11/agent-env/Scripts/python.exe -X utf8 -m hometrace demo --agent --port 8767 --output-dir artifacts/pr-13-integration-20261024/server
# 另一个终端，使用已安装 Playwright 的 Node 环境：
node tools/validate_agent_browser.cjs http://127.0.0.1:8767 artifacts/pr-13-integration-20261024/browser
```

复跑应换新输出目录；无需或不应在命令中明文提供 Key。API 调用轨迹受模型响应影响，新的结果必须重新记录。

## 核心源码 ZIP 与隐私校验

在 merge commit 的干净工作树调用生产 `collect_source`，生成本地 `integration-test-core-source-verified.zip`，**仅供集成验证，不是正式比赛 ZIP**。实际 101 个文件、616998 字节；重开 ZIP 后 CRC、无重复路径、全部文件 SHA256 均通过。详细摘要与 SHA256 见 [source-validation.json](source-validation.json)。

- 保留 `config.yaml`、空值 `.env.example`、Agent 页面/代码、SearchCore、公开样例。
- 排除 `.env`、私人照片、数据库、权重、缓存及 Git 元数据。生产收集器使用本机已配置 Key 进行内容检查，日志不输出 Key；额外在临时 Git 仓库用合成环境变量 Key 验证复制进普通 README 会被拒绝。
- 此允许列表不含完整 YOLOE 实验依赖文本及冻结实验报告，因此只称核心 Demo 源码快照。YOLOE 复现材料仍由仓库提供；不声称该源码 ZIP 能独立复现 GPU 实验。
- 本地一次性审计脚本最初误用 `Entry.source` 字段而停止；改用真实字段 `Entry.path` 后在新文件重做并通过。未改动产品代码，也未把该中止尝试记为成功。

## 合并条件与后续门槛

本轮已完成 PR #13 与 main 的实际联合回归、原始源码保持检查和产物验证，可交 PM 复核；**未自行合并**。按 [PR #15 的最新 PM 要求](https://github.com/Qcx526/HomeTrace/pull/15#issuecomment-6381946398)，必须在 #13 复核并合并后才把 #15 更新到届时最新 main。因此本轮未动 #15 分支，也不宣称官方 DOCX 与 Agent 已完成联合验收。

正式参赛包仍 **BLOCKED**：官方主表本地身份字段、原表排版复核、P4 PPT/视频、最终一致性 ZIP、赛事页面核验与上传回执均未由本轮完成。旧候选包与冻结媒体保持原样，不能冒充 P4 正式提交。#15 后续必须验证官方 DOCX 保真、身份绑定、Agent 配置导出和动态 Key 泄露拒绝同时有效。
