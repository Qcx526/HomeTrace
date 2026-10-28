# 照片登记、记忆与寻找：Issue #26

日期：2026-10-28。合同：[Issue #26](https://github.com/Qcx526/HomeTrace/issues/26)。本分支 `feature/26-household-photo-flow` 基于 PR #25 的 `b6f8d02`，PR 目标为 `feature/24-household-workspace`；这是 stacked PR，不代表 main 已合并。

## 本轮完成的闭环

页面 `/home-flow.html` 支持名称及别名登记、上传参考图、人工固定 ROI、三处地点的图片配置、中文规则请求、历史优先搜索、实际 ORB 匹配、候选核对、拒绝后继续搜索和跨进程恢复。照片与状态保存在 `--household-dir` 指定的私有目录。登记只是保存参考和提取已有 ORB 特征，**训练次数为 0**，没有每个物品训练一个网络。

“这里”由用户明确选择，尚无主人定位或摄像头自动扫描。语言解析支持“记住蓝色钥匙放在这里”“帮我找蓝色钥匙”“查看蓝色钥匙历史”等已登记名称/别名的单意图请求；同名或不同物品同时出现会要求选择。它不是任意自然语言 LLM。安装已有 `agent` 可选依赖时，实际使用确定性 LangGraph 条件循环；否则明确显示 `deterministic_rules`。本页面不调用云 API，原 `/agent.html` 的真实 LLM Agent 保持独立、不冒充已接到任意上传图流程。

每次搜索最多访问三个地点。先查主人陈述的最近地点，再查其他历史地点，最后按地点 ID 排序检查剩余地点。历史顺序不读取未来场景答案。每一步实际调用模拟导航、观察元数据和原 ImageMatcher；旧图在进入检测器之前被 SearchCore 拒绝。没有增加另一套 FOUND 判据，也没有修改 ORB 几何阈值。

## 亲自运行

首次安装可使用 `python -m pip install -e ".[vision]"`，需要展示 LangGraph 时安装已有 `.[agent,vision]`。不需要设置 API Key。

```powershell
python -m hometrace demo --port 8769 --household-dir artifacts/my-photo-home --output-dir artifacts/my-classic-demo
```

打开 `http://127.0.0.1:8769/home-flow.html`，按页面左侧依次登记名称、上传参考和三处场景，再发送请求。图片限制为 JPEG/PNG、8 MB、2400 万像素；带 EXIF 旋转的图片需先按显示方向另存。用户必须声明合成/实拍来源，两种来源不能混在同一目标的匹配证据中。ROI 是登记参考区域，场景始终整图推理。

本机已有生成素材 `local_data/ai_html_test_20261027/`。原图、prompt、SHA256 manifest 均被 Git 忽略，没有随 PR 提交。以下准备器仅接受已审查哈希的合成包和一个**不存在的新目录**，不会清空旧库或绕过旧图保护：

```powershell
python tools/prepare_photo_flow_demo.py --workspace artifacts/my-new-synthetic-demo
python -m hometrace demo --port 8769 --household-dir artifacts/my-new-synthetic-demo --output-dir artifacts/my-classic-demo
```

准备器保存蓝色钥匙参考及固定 ROI `[110,120,1390,950]`、空托盘/书房/红色钥匙三个场景，并创建两条明确虚构的演示陈述：较早在书房、最近在玄关。尚不运行搜索。直接输入“帮我找蓝色钥匙”即可看到玄关未确认→书房候选；可接受或拒绝。再次使用相同图片会被标为旧图，不能当新观察。需要再次体验完整的首次搜索时，用准备器创建另一个新目录，保留旧证据。公共仓库没有这个合成包时，应自行上传图片，不能把缺失素材记成运行成功。

## 状态与来源

| 状态/来源 | 含义 |
| --- | --- |
| `synthetic_image` | AI 合成图，非真实家庭、非独立验证 |
| `user_image` | 用户上传并声明实拍，来源及拍摄时刻未认证 |
| `UNKNOWN` | 无可审阅框、旧图、来源不符或观察不可用；不证明物体缺席 |
| `SUSPECTED` / `AWAITING_REVIEW` | 原几何检查接受的外观候选，等待主人核对 |
| `USER_CONFIRMED` | 用户点击确认后写入 `owner_reported` 位置，`visual_confirmed=false` |

新的两个来源在 SearchCore 中永不进入自动 FOUND。旧 fixture/recorded-image 回归合同保留。原匹配器内部使用 recorded-image 类型仅为接口兼容，外部证据、SQLite 和报告保留真实声明来源。时间用于处理顺序（demo_sequence），不冒充拍摄时间。byte-identical SHA256 重放保护不能发现所有编辑后的近重复图，也不能证明照片新鲜。

## 实际结果

本轮是合成图的软件演示，**不是家庭实拍能力通过**。所有场景使用同一个固定参考 ROI，未逐图换参考或阈值。没有 Ground Truth IoU 标注，因此不报告精确率或独立测试通过率。

| 输入 | 实际输出 | 匹配点 / 内点 | 检测框（原图 xyxy） | 单次匹配耗时 |
| --- | --- | --- | --- | --- |
| `05_empty_entry_tray.png` | UNKNOWN，匹配不足 | 10 / 0 | 无 | 98.068 ms |
| `03_keys_study_desk.png` | SUSPECTED，待人工核对 | 174 / 142 | `[439.12,511.97,1194.69,1003.22]` | 90.890 ms |
| `04_rival_red_keys.png` | UNKNOWN | 2 / 0 | 无 | 99.020 ms |
| 已用的书房/空托盘图再次输入 | UNKNOWN / replayed_image_content | 未再次运行匹配 | 无 | 不计检测耗时 |

耗时为真实单次 CPU 匹配，不含服务/上传/登记开销，不是性能基准。`02_keys_entry_tray.png` 的先前探针在固定 ROI 下因局部支持被拒绝，未作为本轮成功场景：合成图也不是所有构图都能通过。原始探针保留在 ignored 的 `artifacts/issue-next-visual-probe/`，没有通过换 ROI 隐藏失败。

全量测试实际一次执行：**738 passed, 0 failed, 0 skipped, 1 warning in 111.47s**，保留 630 项原回归，新增 108 项。警告是既有 LangGraph 弃用预告。测试 double 只验证软件状态，不计为照片识别证据；另有公开 OpenCV 照片的真实服务/匹配回归。

三次独立 CLI 服务进程、53 次 HTTP 请求实际验证：保存两条历史→首次搜索候选→停止重启→恢复同一候选→人工确认追加一条历史→再次搜索按新历史排序并拒绝旧图；另一个新测试库验证拒绝后继续到红钥匙图，最终 UNKNOWN 且不追加记忆。完整输入、实际框、诊断、core 报告和日志保存在 `artifacts/issue-26/http-02/`，公开脱敏摘要见 [证据](evidence/issue-26/README.md)。

2026-10-28 已使用内置浏览器实际操作上传、ROI 数值确认、场景配置、两条记忆、搜索、刷新、重启后确认、旧图保护、拒绝后继续、同名选择与缺少参考时取消。检查 1280px 桌面与 390px 窄屏，未见横向溢出，浏览器错误/警告日志为空。ROI 拖拽手势、禁用 localStorage、其他浏览器和手机实机未验收。最初浏览器权限连接失败的记录保留，随后连接恢复，不将最初失败改写为成功。

## 结构与审计

- `photo_flow_service.py`：私有照片库、冻结参考、场景快照、SQLite 会话/证据、真实工具执行及可选 LangGraph 循环。
- `photo_engine.py`：调用未改动的 ImageMatcher，保留匹配诊断，只提供外观候选。
- `models.py` / `search_core.py`：新增两个图像来源的独立安全分支；沿用重放检查，阻断自动 FOUND。
- `demo_server.py` / `web/home-flow.*`：同源本地 HTTP、上传限制、ROI/照片/决策/证据页面，兼容旧入口。
- `tests/test_photo_*.py`：来源、重放、几何、事务、并发、异常与 HTTP 契约。

`photo-flow.sqlite3` 不修改生产 SQLite schema；主人记忆仍使用原 owner-memory 库。确认动作要求两库 DELETE journal，并在同一附库事务写入事件与会话；WAL 情况明确拒绝。证据、完成地点与 trace 在一个事务提交，进程中断可从未完成地点继续。确认与取消使用版本号防止旧页面覆盖。输入图像以随机 ID 保存原始字节，不接受任意服务端路径，重新绑定场景不改变已开始任务的快照。

## 仍未解决

没有主人定位、实时相机、实体机器人、通用物品神经识别、自由多轮 LLM 对话或自主物理实例确认。原共享模型/真实家庭照片实验结论仍为 **BLOCKED**，本次未训练、未接入失败模型、未覆盖冻结报告。历史频次可以查看，但未训练长期习惯模型，也没有证明搜索效率提高。当前产品完成的是可操作、可审计的人在环软件 Demo；原始参赛包及家庭通用识别不能因此宣称完成。
