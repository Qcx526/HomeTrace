# 主人位置记忆与进程重启验收：Issue #40

2026-10-31，在 `feature/40-owner-memory-restart` 上执行。[Issue #40](https://github.com/Qcx526/HomeTrace/issues/40) 为本轮合同；基线为未合并 [PR #39](https://github.com/Qcx526/HomeTrace/pull/39) 的 `9f8bcd3ea1e370600c2df1c7201b7befac5a762d`，PR 目标分支是 `feature/38-feedback-decisions`，继续依赖上游 PR #37。本轮不合并任何 PR。

## 结论与输入

已实际完成主人陈述的持久化和重启后历史查询。软件样例在真实 HTTP、SQLite 和三个服务进程阶段中验证了确认前不写、恢复待确认、拒绝过期重复确认、重启后读取同一事件。随后将负责人明确提供的自定义地点写入新的本地私有工作区，并通过重启后的真实文本 LLM 查询读回；没有重复写入。

这些结果只支持“主人说过物品在某地”的历史记忆，不证明物品当前仍在那里。真实名称与地点绑定、照片、数据库和原始响应仅留本机。本轮没有新的图片外发或视觉识别实验。

当前网页照片搜索只配置三个固定地点。自定义地点虽然可以通过既有记忆接口保存、查询，但没有对应的导航及场景配置，**不能宣称真实物品寻物全闭环通过**。没有把该地点映射成另一个固定地点，也没有自动 FOUND；独立实拍识别验收继续 BLOCKED。

## 最小实现

- `src/hometrace/household_memory.py`：只对四种格式严格匹配的本地确认来源补充 `reported_at_basis=local_system_clock`。程序确认时间不是照片拍摄时间，也不是物品实际放置时间；未知或格式错误来源保留旧 CLI 语义。数据库 schema、原始 `source`、时间戳和排序规则不变。
- `tools/accept_memory_restart.py`：在全新、Git ignored 输出目录中运行软件样例验收。真实模型选择记忆或查询工具，程序通过 HTTP 执行；子进程重启后用只读 SQLite 快照核对。工具不覆盖旧目录，失败保存摘要并停止，没有自动重试或用假模型替代真实响应。
- `tests/test_household_memory.py`：新增 19 项来源语义、重开数据库与文件字节不变测试。
- `tests/test_accept_memory_restart.py`：12 项离线工具约束、失败保留和实际本地 HTTP/SQLite 回归。该离线测试中的模型是明确的测试替身，重建服务对象不被说成真实子进程验收。

既有 Agent、ImageMatcher、SearchCore、视觉阈值、场景配置、SQLite schema 与历史冻结报告没有修改。

## 软件样例实际执行

输入是程序绘制的确定性几何图案，明确登记为 `synthetic`；没有使用真实家庭照片或视觉评分。登记 ROI 和点击确认由脚本模拟，不能冒充负责人对实物的身份审核。

| 阶段 | 实际返回 | 主人事件数 | 视觉证据数 |
|---|---|---:|---:|
| 空工作区，未提供地点的记住请求 | `ERROR`，意图为 remember | 0 | 0 |
| 明确提供软件样例地点 | `CONFIRM_MEMORY` | 0 | 0 |
| 第二个服务进程恢复原会话 | 待确认状态完全一致 | 0 | 0 |
| 脚本明确确认 | `COMPLETED`，owner_reported | 1 | 0 |
| 重发旧版本确认 | HTTP 409，无新增事件 | 1 | 0 |
| 第三个服务进程，查询历史 | `COMPLETED`，原事件与时间一致 | 1 | 0 |

共 3 个不同 PID、8 次只读数据库快照，72 次运行断言全部通过。这些含重复 HTTP 状态检查，不是 72 项独立 pytest 测试。子进程由工具主动终止以测试重启，Windows 退出码为 1；没有将它们写作正常退出码 0。

三个文本阶段分别实际调用 1 次模型，Token 为 1746、1719、1731，共 **3 次 / 5196 Token**。确认后的状态快照仍含之前的调用计数，统计时没有重复累加。模型经当前已配置的第三方兼容接口调用，请求标识为 `deepseek-v4.1-flash-1017`；不据此保证底层模型身份。

限制为每阶段最多 2 次调用、最多 3 阶段、每次超时 45 秒、重试 0、每个运行 24000 Token 预算、验收总期限 360 秒。没有场景注册、图片授权或寻物请求。结果见 [软件样例脱敏记录](evidence/issue-40/memory-restart.json)。

## 真实主人陈述与失败保留

负责人明确给出地点后，复用原物品登记身份与已批准参考，在新本地工作区通过既有 `HouseholdMemory` CLI 追加 **1 条** owner_reported 事件；这是编码工程师执行已有明确陈述，不是 LLM 推断位置，也不是在浏览器上代点已冻结的搜索候选。实际放置时间未知，事件使用本地确认时间并标明来源。

首次重启后查询将总预算人为压到 6000 Token，触发调用前 `TOKEN_INPUT_BOUND`，模型调用为 **0**，验收失败。该失败目录和日志原样保留。随后恢复原有 24000 Token 预算，保留每运行最多 2 次调用、45 秒超时、0 重试，在新的结果目录显式进行一次查询；这不是底层自动重试，没有再次写入记忆。

第二次查询真实执行 **1 次文本模型调用 / 1738 Token**。两个新服务进程之间事件一致，查询结果中的事件 ID、地点及时间与已保存值相同，查询前后的 owner-memory 数据库字节哈希不变。无观察、无导航、无图像调用、无视觉确认。脱敏结果见 [主人历史查询记录](evidence/issue-40/owner-recall-redacted.json)。

本轮合计 4 次实际文本模型调用、6934 Token。首次预算拦截不计作模型调用。原照片可在本地工作区被加载，但没有获得外发授权，也没有图片请求。已有冻结照片结果哈希核对未变化。

## 运行命令与回归

实际使用既有可选 Agent 环境：Windows / Python 3.11.4、HomeTrace 0.4.1、Pillow 12.0.0、LangGraph 1.0.2、langchain-openai 1.0.1；前端 Node v24.18.0。源码运行时哈希和实际限制见 [execution.json](evidence/issue-40/execution.json)。真实运行发生于提交前，记录基线 HEAD 与当时工作树源码哈希；提交前逐文件核对一致。

```powershell
# 离线回归，使用已有可选 Agent 环境
.\artifacts\issue-11\agent-env\Scripts\python.exe -X utf8 -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs

# 明确联网的文本记忆验收；需要配置的真实 API；每次用新的 ignored 输出目录
.\artifacts\issue-11\agent-env\Scripts\python.exe -X utf8 tools/accept_memory_restart.py --output-dir artifacts/issue-40/memory-restart-NEW
```

也可按 README 安装 `.[dev,vision,agent,vision-advisor]` 后用相应虚拟环境运行；本轮没有重做 Windows 全新安装验收。

本分支完整回归实际结果为 **1034 passed、1 warning / 157.63 秒**，进程退出码 0；警告为原有 LangChain `allowed_objects` 默认值弃用提示。这里使用一次联合全量结果，没有累加分支测试数量。此前两次执行仅留下部分进度，没有完成摘要，不计通过；另一次误用系统 Python，报 `No module named pytest`，没有执行测试。所有原始记录留存。前端实际结果为 **21 passed**；网页文件没有改动，本轮未重新运行完整浏览器交互，HTTP 验收不冒充浏览器操作。

公开的 [pytest 完整日志](evidence/issue-40/pytest-full-04.txt)、[前端日志](evidence/issue-40/node-tests-01.txt)、[验证汇总](evidence/issue-40/validation.json) 与 [源码/隐私审计](evidence/issue-40/audit.json) 均保留实际结果。日志只将仓库绝对路径替换为 `<repo>`；源码、实际 Key、私有身份/地点和原图哈希扫描通过，`git diff --check` 通过。

## 审查与后续

公开交付只包含代码、软件测试和脱敏汇总；不包含原图、私人地点或身份绑定、原始模型响应、数据库、权重、Key 或本机私有路径。脱敏材料按字段白名单生成，私有原始证据留在 Git ignored 目录；时间来源新增值只解释来源，不授予位置或身份权威性。

本增量可提交 PM 审查。下一步若要在真实自定义地点完成寻找，需要先增量支持地点和场景配置，再获得该场景的当前照片与必要审核；历史记忆不能代替当前观察。需要外发新照片时仍须有对应授权。本轮不制作参赛包、不关闭视觉识别阻塞、不自行合并上游或本 PR。
