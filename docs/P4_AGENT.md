# P4 Agent：真实 API、共享可信工具与反馈搜索

Issue #11，基线 `e5732b4024d90cc190aedb77f98f626b11e982cd`。本阶段实现真实 LangGraph Agent；未经 PM 审查不合并。YOLOE 的独立 PR #13 为 NO_GO，本分支不依赖该 PR，不接入神经候选。现有公开照片仍用 ORB 原阈值。

## 已执行的闭环

真实自然语言请求 → 千问AI平台托管的 `deepseek-v4.1-flash-1017` → LangChain 原生 Tool Calling → SQLite 记忆 → 模型选择合法视点 → 模拟导航与读取照片 → ORB/原 SearchCore 证据验证 → ToolMessage → 模型再次选择或生成中文说明。模型文字始终单独显示为非事实来源。

Gate 0 已真实执行 4 次模型请求：普通文本、`list_registered_objects`、读取反馈后 `query_memory`、读取记忆反馈后再次回应。两个工具真正读取本地 SQLite；协议目录是专门登记的无图测试条目，不是家庭图像识别成绩。模型不是 DeepSeek 官方直连；Chat Completions 强制 `use_responses_api=False`，没有 Responses API、假模型或无 Key 降级。

正式演示使用公开 OpenCV 盒子；“找耳机壳”返回未登记，不用盒子冒充耳机壳。两个同名杯子是用于澄清路径的**辅助目录条目**，没有照片/历史/识别成果，不允许作为可用图像目标执行。家庭神经识别没有升级成功。

## 最小结构与可信边界

- `agent_config.py / agent_model.py`：根 `.env` 仅 Key，`config.yaml` 是模型、HTTPS接口、超时、预算唯一配置来源。PyYAML safe_load、严格键/类型/范围、重复键/循环别名拒绝；python-dotenv override=False，允许 CI 预置 Key 优先。错误不输出请求正文、响应体、Key 或路径。
- `agent.py`：LangGraph `StateGraph` 的 model→tools→model 条件循环；显式预算、真实消息与 ToolMessage、目录绑定、未知/歧义、错误与停止状态。没有独立第二套 FOUND 规则。`AgentState` 区分用户目标、解析目标、合法视点、访问、历史、消息、工具返回、预算、轨迹和可信结果。
- `SearchCore` 增量抽取 `start_search / navigate_viewpoint / observe_current / verify_current / finish_search`。原 `run` 调用同一组原语；保留来源、时间水位、旧图重放、检测合法性、SQLite 写入及唯一 FOUND 路径。状态快照不可回写。乱序操作、重复访问和确认后继续执行被拒绝。
- 六个 LangChain 工具是 `list_registered_objects / query_memory / navigate_and_observe / verify_visual / render_report / unresolved_target`。为减少调用与费用，导航+观察合为一工具，视觉验证+可信写库合为一工具；底层各自独立事件真实记录。LLM 选择下一地点，不是预跑 SearchCore 后只写总结。工具参数没有 status/bbox/location 或任意执行命令。
- `agent_service.py`：后台线程拥有本轮 SQLite；沿用公开图片快照、独立登记进程、哈希核验和本地 HTTP 边界。只有已观察图像进入访问白名单，变更图片以新 URL 更新。`web/agent.*` 每秒读取实际运行状态，按原图坐标绘框；原经典三场景保留。
- `submission.py`：源码允许 `config.yaml` 和**空** `.env.example`，排除 `.env`、私照、模型和数据库；阻止误填示例/秘密字段和本机 Key 混入普通源码。不能识别一切任意新秘密，提交前仍须人工隐私核验。

LLM 只收到登记别名、O/V/H/E 匿名标识和已取得的结构化事实；不传原图、路径、图像 SHA、身份信息、未来图片或场景答案。LangSmith/tracing 显式关闭。网页和完整 trace 保留本地，用户私有请求不得直接公开。公开验收只选本次固定的非敏感测试请求。

## 实际结果

V1/V2/V3 分别映射当前演示 A/B/C。自动化通过数不是识别率；以下均为**真实 API + 本地实际程序**运行：

| 请求/场景 | Agent 状态 | 可信视觉结果 | 实际路径 | 模型/工具调用 | 已报告 tokens |
| --- | --- | --- | --- | --- | ---: |
| 公开盒子 moved | COMPLETED | FOUND/V2 | V1→V2 | 7/6 | 10533 |
| 公开盒子 missing（最终预算） | COMPLETED | SUSPECTED/null | V1→V2→V3 | 9/8 | 14037 |
| 公开盒子 replay | COMPLETED | UNKNOWN/null | V2→V1→V3 | 7/6 | 10074 |
| 历史 C 公平案例 | COMPLETED | FOUND/V3 | V3 | 5/4 | 6145 |
| 找耳机壳 | UNKNOWN_OBJECT | UNKNOWN/null | 无导航 | 2/1 | 2043 |
| 找杯子 | CLARIFY | UNKNOWN/null | 无导航 | 2/1 | 2210 |
| 浏览器实际正例 | COMPLETED | FOUND/V2 | V1→V2 | 7/6 | 9743 |

初始预算并未全部成功：12000-token 保守预估使首轮正例在工具 FOUND 后、最终说明前停止（5模型/5工具，6026已报告 tokens）；8模型调用限制使首轮负例在写完报告后、最终解释前停止（8/8，11797 tokens）。两轮均完整保留为 `BUDGET_EXCEEDED`。据实调整配置为 **10模型调用、12工具、5视点、24000 tokens**；超时60秒、最多1次SDK重试不变。没有改视觉阈值或测试答案。输入预算估计保守，以 provider 实际 usage 累计校验；1024 单次输出上限，缺 usage 明确失败。失败请求/SDK重试可能没有 usage，不能把本地累计声称为供应商最终账单或硬性费用上限。

公平场景只调整公开演示编排：历史由 A 改为 C，当前 C 使用已有正例图片，A/B 使用已有负例；照片完整且时间仍 A<B<C，两策略同一快照、独立同样登记的数据库。固定顺序实际 A→B→C，Agent 读取历史后实际 C，两者 FOUND。这里只证明该受控输入下历史改变了选择顺序及访问步数；不推断普遍效率、机器人移动时间或真实家庭搬移。原三个场景仍打平。历史自匹配不算独立识别成绩。

公开逐轮指标、真实参数与反馈、失败轮、图像框坐标来自 [验收证据](evidence/issue-11/README.md)。供应商没有返回 request_id 时保留 null；LangChain 的 lc_run 标识不是伪造的供应商请求号。

## 运行

Windows 本次使用 Python3.11.4，独立可选环境；真实验证版本为 langchain-openai1.0.1、langchain-core1.7.0、langgraph1.0.2、python-dotenv1.2.1、PyYAML6.0.3，`pip check` 无冲突。直接依赖固定在 pyproject.toml，完整实际依赖在证据目录，版本说明以当次运行记录为准。

```powershell
python -m venv artifacts/issue-11/agent-env
.\artifacts\issue-11\agent-env\Scripts\python.exe -m pip install -e ".[agent,dev,vision]"
# 仅在还没有 .env 时复制；已有文件不可覆盖
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 在本机编辑 .env 填 Key；修改 config.yaml 选择模型/接口/预算
.\artifacts\issue-11\agent-env\Scripts\python.exe -X utf8 tools/check_agent_api.py --output-dir artifacts/issue-11/new-gate0
.\artifacts\issue-11\agent-env\Scripts\python.exe -X utf8 tools/run_agent_demo.py --goal "请帮我找公开样例盒子" --scenario moved --output-dir artifacts/issue-11/new-runs
.\artifacts\issue-11\agent-env\Scripts\python.exe -m hometrace demo --agent --port 8765 --output-dir artifacts/p4-demo
.\artifacts\issue-11\agent-env\Scripts\python.exe -m pytest -q
```

打开 `http://127.0.0.1:8765/agent.html`；`--config` 可指定 YAML，默认按源码仓库根定位而非调用时工作目录。源码推荐 editable 安装。不要在网页或聊天粘贴 Key。CLI `--scenario` 可用 moved/missing/replay/fair。真实 API 会使用账号额度；界面一次只运行一项。普通单元测试无网络；stub 只在 tests，用于协议/预算/异常边界，不作为真实 Agent 能力证据。

## 尚未完成与 PM 门槛

本阶段为公开照片的小型软件演示：没有现场拍摄、真机运动、RobotClaw SDK、ROS、神经实例确认或普适家庭识别。Agent 页面暂只开放公开样例，私人目录不自动发往云端。API 的目标绑定和中文解释有模型误解风险；输出文本不改变可信结果。时间水位仍可能拒绝乱序的旧观测；不为模型调整顺序放宽证据规则。代理停止时可能仍有未查地点，UNKNOWN/SUSPECTED 绝不代表物品不存在。

Issue #12 官方主表、私人身份和最终媒体独立准备；Agent 经 PM 审查合并后才更新正式 Word/PPT/MP4/ZIP。规则 PDF 不入提交包。计划截止2026-11-04的具体时刻和最终附件要求仍需本届平台核验。
