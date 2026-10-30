# 视觉 Agent 闭环：Issue #34

本增量在 `feature/34-visual-agent-loop`，以 PR #33 / `feature/32-visual-advisor` 的 `f0935341ec201c0ccd444d0229b1d000b25e1216` 为基线，属于 stacked PR。未合并 main。历史 R0/R1/R2、PR #33 实拍诊断报告不改写；本轮不训练模型、不制作比赛材料。

## 使用方式

```powershell
# 在已配置 .env 的仓库根目录；不要覆盖已有 Key
python -m pip install -e ".[dev,vision,agent,vision-advisor]"
python -m hometrace demo --photo-vision-agent --port 8784 --household-dir artifacts/my-visual-home
```

打开 `http://127.0.0.1:8784/`。新目录首次为空，重复使用相同目录恢复 SQLite 记录。默认 `--photo-agent` 继续只做本地匹配；只有显式 `--photo-vision-agent` 提供以下工具。

1. 登记名称、别名，上传参考照片，框选并确认 ROI。当前网页每个物品只有一张固定参考，不等同于 PR #33 的六参考实验。
2. 手动选择当前位置，发送“请记住，我的水杯放在这里”，核对后保存。位置来自主人陈述，尚不是视觉证明。
3. 配置各地点照片，发送“请找我的水杯，先查看历史位置；不清楚时请我补拍”。
4. LLM 调用 `inspect_location`，执行真实本地匹配；可以调用 `visual_advice` 请求看图。页面会显示本次参考 ROI、完整场景、接收网关及请求编号，复选框默认未勾选。
5. 批准仅发送本次去元数据、最长边 1280 像素的 JPEG 副本。拒绝则将拒绝结果交回 LLM。新照片需再次独立授权，上传到本机不代表允许外发。
6. LLM 读到真实顾问建议后，再选择 `request_new_photo`、下一地点、`request_owner_review` 或停止。补拍在同一 run 保留旧观察，并对新图重新执行 Core 校验。补拍由主人操作，导航始终模拟。
7. 无检测框时显示完整场景和文字建议，不制造方框。主人接受后保存 `owner_reported`，状态为 `USER_CONFIRMED`，自动视觉状态仍未升级为 `FOUND`。

照片中若含敏感桌面信息，批准前应检查页面预览；去 EXIF 不会去除画面中的文字、人物或屏幕。当前接收方为配置的第三方兼容网关，并非 DeepSeek 官方直连。页面显示请求模型，执行记录另存返回模型标识；这不能证明第三方底层模型身份。此前十次家庭照片诊断的授权已经用完，本轮只外发固定合成素材。

## 代码与可信边界

| 文件 | 作用 |
|---|---|
| `visual_photo_agent_service.py` | 新工具、等待授权/补拍状态、逐请求预算、取消与恢复、顾问结果交回 LLM |
| `visual_advisor.py` | 从 PR #33 抽出的纯合同；严格 JSON、图像载荷及只读建议验证 |
| `visual_advisor_client.py` | 固定 ROI/全景副本、元数据清理、一次真实 API 请求；无自动重试或重定向 |
| `photo_agent_service.py` | 小型扩展钩子、模式隔离和无敏感正文的协议拒绝诊断 |
| `photo_flow_service.py` | 补拍证据 ID、同地点重新观察及主人记忆来源钩子 |
| `demo_server.py`、`web/home-flow.*` | 可选启动开关、严格 HTTP 参数、授权预览、补拍上传和实际工具轨迹 |
| `tools/accept_visual_agent.py` | 固定哈希合成素材的真实接口验收；不依赖私人物品照片 |

`ImageMatcher`、`SearchCore`、SQLite schema 和生产阈值不变。模型没有直接写位置、注入检测框或确认 FOUND 的工具。参考/场景原图哈希、副本哈希、观察序号、端点、模型及请求版本全部绑定；换图或换目的地使旧批准失效。参考重放、已用场景和来源不一致仍被拒绝。

每 run 最多三次视觉请求、两次补拍；视觉预算 24000 Token，每次先预留 8192，响应后结算。失败保留预留，已知实际用量更高时按更高值保留，溢出后停止；这是应用层预算，不保证第三方账单绝不越界。45 秒为网络超时配置，不是整个工作流耗时上限。取消无法撤回已发送的图片，但迟到建议只结算用量并记录 discarded，不推进工具或记忆。中断的视觉请求不静默重发。

## 实际验收与失败记录

运行日志及脱敏摘要见 [evidence/issue-34](evidence/issue-34/)。原始 JSON、图片、SQLite、截图和完整日志位于本地 ignored 的 `artifacts/issue-34/`。测试发生于 2026-10-29 至 2026-10-30，本报告不把此前测试数量相加。

```powershell
python -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
# 显式联网，读取现有固定合成素材；每次输出目录必须不存在且被 Git 忽略
python tools/accept_visual_agent.py --output-dir artifacts/issue-34/acceptance-new
python tools/accept_visual_agent.py --case rival --output-dir artifacts/issue-34/rival-new
```

- 最终联合 Python：**904 passed**，126.71 秒，1 项 LangGraph 依赖弃用警告。前端 **21 passed**。离线测试使用明确的脚本替身，不能证明真实识别效果。
- 首次真实接口 `live-01`：首图比较及补拍真实执行，补拍后工具协议失败，保留 ERROR，无伪造成功。
- `live-02`：实际捕获 `finish_reason=length`、512 输出 Token、1 个无效工具调用；一次显式重试后完成。未重新调用已获批的视觉请求。
- 仅视觉模式把单次决策输出上限增至 1024，保留总预算；普通模式仍为 512，未降低任何视觉阈值。
- `live-03`：无需重试，完成空工作区登记、位置记忆、首图比较、补拍、同地新证据、再次比较、主人确认、两次服务重启、重新读取两条历史。

`live-03` 的实际寻物轨迹为：解析物品 → 查询记忆 → 检查书房 → 请求看图 → 主人批准 → 顾问 `uncertain/request_closeup` → LLM 请求补拍 → 重新观察 → 第二次看图授权 → 顾问 `similar/ask_owner_review` → LLM 请求主人核对 → 脚本模拟主人确认。

| 输入/阶段 | 实际结果 | 视觉耗时 | 视觉 Token |
|---|---|---:|---:|
| 首图：完整合成桌面缩小再模糊的软件 fixture | 本地 UNKNOWN；顾问 uncertain；请求补拍 | 8631.593 ms | 2405 |
| 补图：原始清晰合成桌面 | 本地 SUSPECTED；顾问 similar；请求主人核对 | 6910.787 ms | 2250 |

完整 `live-03` 共 8 次真实决策调用（记忆 1、寻物 6、重启历史 1），15690 决策 Token；另 2 次看图、4655 Token。两次观察使用不同图片哈希和证据 ID；最终只有主人陈述记忆增加。该脚本的用户请求明确要求补拍，不能把它表述为无需提示的自主恢复能力；软件降质图和原图也不是两次真实相机拍摄。

浏览器首次 `browser-01` 从空页面实际完成名称登记、上传参考、确认 ROI、配置相似钥匙负例、发起寻找和逐次授权。顾问调用失败且用量未知，预算预留保留，后续 LLM 工具协议也失败，未写任何位置。这个旧运行未保存更细的 provider 错误类型，因此不能推断为超时或断网。现已增加安全错误类型、HTTP 状态和响应结束原因记录，不保存异常正文或密钥。

`rival-01` 的真实负例比较成功：顾问返回 `different / continue_search`，说明蓝色编织带与棕红色皮质挂件、钥匙数量/颜色不同；耗时 3981.852 ms，2016 视觉 Token。决策 LLM 按用户限定的单地点范围执行 `finish_search`，最终 UNKNOWN，无候选，历史仍为最初 1 条。该寻物 run 为 4 次决策、7398 Token（另有登记记忆决策 1 次）。验收脚本最初错误地在 `llm_tool` 事件中寻找 `inspect_location`，使脚本断言失败；实际观察记录为 `observe_uploaded_image`。已修正脚本，并对原输出及 SQLite 做只读事后复核，10 项检查通过、零新增 API 调用；原失败报告原样保留，不能把它写成原脚本全通过。

`browser-02` 在新的服务进程中，通过真实页面输入历史查询；真实 LLM 1 次调用、1427 Token，读取两条持久历史。截图仅含合成素材，见 [网页历史查询](evidence/issue-34/browser-history.png)。浏览器证据覆盖首次登记/上传/授权和重启历史查询；补拍正例完整链路由 HTTP 脚本执行，不能混称全流程均由浏览器验证。

运行版本与代码边界：上述调试是在基线 `f093534` 上的工作树中运行，旧运行没有预存完整源码快照，不能事后声称它们是最终提交版本的逐字执行。`rival-01/execution.json` 记录当时各源码文件 SHA256 和依赖版本；公开 `source-audit.json` 记录最终暂存源码。SDK/网关的非确定性返回不会作为离线回归的预期值。

## 能力边界与下一步

这是可审查的可选软件集成，尚不是家庭通用识别验收通过。真实家庭照片本轮零次外发，独立真实测试样本仍为零。正例成功指完整工具链和人工核对流程；类别相似和语言模型的 similar 都不能证明唯一物理身份。

当前仅三个固定地点、手动当前位置、上传图片、单参考网页登记。没有实时摄像、自动找主人、真机导航或通用实例检测框。第三方服务可能失败或输出无效 JSON；错误会显示并停止/交回决策，不静默伪造结果。稳定性需要持续记录失败，不能从一次成功推断生产可用性。

下一步应由负责人在新页面逐次批准实际杯子场景，验证漏识别、遮挡补拍、相似杯和空场景；需要新的图像授权，不沿用旧实验授权。通过代码审查和真实验收前不合并、不称比赛材料已可提交。
