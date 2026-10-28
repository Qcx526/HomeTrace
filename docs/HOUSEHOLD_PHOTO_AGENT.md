# Issue #28：LLM 决策接入照片工作区

2026-10-28。依赖 PR #27 的 `5861967f8e78d9470fad19cc0ead595bca3f58d5`，独立分支 `feature/28-photo-llm-agent`，PR 指向 `feature/26-household-photo-flow`。不合并上游，不改写旧实验结论。

## 本轮行为

同一 `/home-flow.html` 可以通过 `--photo-agent` 启用真实模型。模型解析已登记物品及记忆/历史/寻找意图，工具读取真实 SQLite 历史；之后每一个检查地点和停止动作均由新的模型工具调用选择。观察反馈及主人拒绝会进入下一次模型上下文。父流程给出的历史排序仅是候选建议，不直接驱动下一步。

新增 `PhotoAgentService` 继承照片工作区，使用既有 LangChain 模型接口、工具接口和 LangGraph 条件循环。`resolve_request` 读取物品历史，`inspect_location` 执行模拟导航、读取本地图片并调用既有 SearchCore / ImageMatcher；`finish_search` 只能结束为 UNKNOWN。另外提供未知物品、否定请求和歧义澄清工具。工具集合按阶段限制，参数、状态、版本、地点与预算再次由程序校验。

工具没有提交 bbox、设定 FOUND、代替主人确认或任意写位置的接口。模型给出的简短理由单独标为非观察证据，原始模型正文不成为可信回复。主人确认仍通过原跨库事务保存 `owner_reported`，`visual_confirmed=false`。

## 运行

```powershell
python -m pip install -e ".[dev,vision,agent]"
# 本地 .env 设置 HOMETRACE_LLM_API_KEY；不要粘贴到聊天或提交到 Git。
python -m hometrace demo --photo-agent --port 8770 --household-dir artifacts/my-photo-agent
```

模型与预算沿用 `config.yaml`，可用 `--config` 指定本地配置。实际验证使用 `deepseek-v4.1-flash-1017`、LangGraph 1.0.2、langchain-openai 1.0.1。API 使用已有配置网关。图片、参考 ROI、原始 hash、私有路径不发送给模型；请求文本、登记名称/别名、地点、历史时间顺序及选取的结构化工具反馈会发出。外部 tracing 关闭。修改 Key 或模型配置后重启服务，不能假定已运行客户端自动重载。

不加 `--photo-agent` 时保留明确标识的规则模式；LLM 服务失败不会暗中回退。两种模式的已有任务不能交叉续跑。原 `/agent.html` 和经典三场景保持独立。

本机授权合成素材已存在时，可先创建新演示工作区：

```powershell
python tools/prepare_photo_flow_demo.py --workspace artifacts/my-new-llm-demo
python -m hometrace demo --photo-agent --port 8770 --household-dir artifacts/my-new-llm-demo
```

准备器建立蓝色钥匙、三张场景和两条明确虚构的主人位置陈述，不调用模型、不搜索。页面发送“出门要用的蓝色钥匙不见了，帮我看看哪里有。”后，才实际调用 LLM。也可选择当前位置，发送“请记一下，蓝色钥匙我就放在这儿了。”并人工确认。名称、参考图和场景仍用表单登记，当前尚不是语音或摄像头自动登记。

## 真实运行证据

命令（输出目录必须不存在）：

```powershell
python tools/validate_photo_agent.py --output-dir artifacts/issue-28/live-reproduce
python -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs
```

实际 `live-02` 创建 4 个 CLI 服务进程、3 个私有工作区，8 个不同 LLM 请求共 **22 次真实模型调用、28415 Token**（按 run_id 去重，不把确认/拒绝前后快照重复计数）。这是一次运行记录，不保证模型每次使用相同步数。

| 请求 | 实际结果 | 模型调用 / Token | 实际检查顺序 |
| --- | --- | --- | --- |
| 记住书房、记住玄关 | 分别等待确认，点击后保存主人记忆 | 1 / 1211；1 / 1196 | 不执行视觉 |
| 查询历史 | COMPLETED，2 条真实存储记录 | 1 / 1180 | 不执行视觉 |
| 寻找蓝色钥匙 | AWAITING_REVIEW；重启后人工确认 USER_CONFIRMED | 3 / 3865 | 玄关 → 书房 |
| 重复搜索旧图 | UNKNOWN | 5 / 6902 | 书房 → 玄关 → 客厅 |
| 拒绝场景准备记忆 | 确认后保存主人记忆 | 1 / 1206 | 不执行视觉 |
| 书房候选被拒绝后继续 | UNKNOWN；不新增主人记忆 | 总计 5 / 6641 | 书房 → 玄关 → 客厅 |
| 无目标图片与缺图 | UNKNOWN | 5 / 6214 | 玄关 → 客厅 → 书房（未配置图片） |

首次搜索中的实际 ORB 结果：空托盘 10 匹配/0 内点、UNKNOWN，89.198 ms；书房 174 匹配/142 内点、SUSPECTED，95.203 ms，原图框 `[439.12,511.97,1194.69,1003.22]`。拒绝分支的红色钥匙为 2 匹配/0 内点、UNKNOWN，91.867 ms。重放图由既有证据校验拒绝，缺图为 `no_observation`，均不生成框。耗时仅单次 CPU 处理，不是性能指标。

全部图片来自明确标记的 AI 合成包，不是家庭实拍、独立测试或真实机器人。没有新增网络训练、降低视觉阈值或修改 ImageMatcher。

独立浏览器工作区另实际完成：自然语言提交 → 3 次模型调用/3820 Token → 玄关 UNKNOWN → 书房候选；刷新仍恢复同一任务；点击“不是它”后模型再次检查客厅并停止 UNKNOWN。浏览器与 HTTP 验证分别记录，不相加成照片样本数。新增模型统计、短理由和实际执行地点顺序已可见。截图含合成图，只留本地 `artifacts/issue-28/browser/`，公开提供 AX 文本及脱敏报告。本轮未重做 ROI 拖拽、其他浏览器或手机实机验收。

测试：**一次联合 pytest 773 passed、0 failed、0 skipped、1 条既有 LangGraph 警告，123.07 秒**，原 738 项均保留。新增 35 项 Python 是模型注入和软件契约测试，不是实拍识别证据。Node 独立执行 8 passed，包括原有 4 项；不把 Node 数加到 pytest 数。wheel 构建成功，非新的全新环境安装认证。

## 实际失败与修正

`live-01` 的早期未提交版本已成功完成记忆、历史、候选和重放，但拒绝分支准备阶段模型再次调用 `resolve_request` 解析已绑定目标，程序报 ERROR，未越权观察。该轮结果、日志保留，未改写为成功；早期工作文件没有独立 commit/hash 记录。修正为每阶段只向模型绑定合法工具，同时明确 phase 与上次观察，再在全新 `live-02` 目录执行完整验证。没有为成功调整图片或视觉阈值。

离线新增测试初跑有 2 个预期错误码不符：工具在新增阶段白名单处更早被拒绝，仍无观察或写入。更新新测试的错误码预期后执行上述完整回归；不是修改既有测试或放宽拦截。

## 边界与后续

1. 模型负责下一步选择，但可能误解语言、重复工具、过早停止或产生不准确理由。实测中有将缺图说成“已查看”、将较旧历史称作最近记录的文字问题，原输出保留；可信状态和观察记录始终分开显示。不能把这些解释作为定位事实或已学会家庭习惯的证明。
2. 同名候选选择和本次任务内的拒绝/继续可持久恢复；未实现跨任意对话的代词理解或无限多轮聊天。未知名称、缺少参考和缺少当前位置仍需补充。
3. 模型/工具/地点/Token 预算和调用时间预留在本地持久记录，取消后的迟到结果失效。重试不重置预算。中断的请求可能已被提供商计费，保留预留预算但实际 Token 未知。底层已发出的请求不能保证远端即时撤销。
4. 真正家庭物品识别仍为 **BLOCKED**。LLM 没有改善 ORB 的尺度、纹理、视角或实例区分能力；当前仅完成真实模型参与、可操作且可追溯的受限软件 Demo。

源码、脱敏逐次调用、首次失败、测试和隐私审计见 [证据目录](evidence/issue-28/README.md)。交负责人审查，不自行合并，不因本次集成声称正式参赛包完成。
