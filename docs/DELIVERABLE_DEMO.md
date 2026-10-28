# 当前交付 Demo 与空工作区验收

Issue #30，2026-10-28。分支 `feature/30-deliverable-acceptance`，依赖 PR #29 的 `dc2c4f81bee31e8e3fbd5c52991d73ee2550c31f`；PR 目标为 `feature/28-photo-llm-agent`，属于 stacked PR，未合并 main。

本轮验收的软件流程已跑通：登记名称与外观、保存主人陈述的位置、真实 LLM 查询历史并选择地点、本地匹配提出候选、主人确认或拒绝、跨进程保留历史。**真实家庭实例识别仍为 BLOCKED，正式参赛材料和上传未完成。** 合成图上的闭环不替代实拍验收。

## 从空目录开始

在仓库根目录按 README 建立 `.venv` 并安装 `.[dev,vision,agent]`。真实模型配置使用本地 `config.yaml` 与 `.env`，不要覆盖已有密钥。选择一个从未使用的工作区路径：

```powershell
.\.venv\Scripts\python.exe -m hometrace demo --photo-agent --port 8770 --household-dir artifacts/my-new-home
```

打开 `http://127.0.0.1:8770/`，应显示零件物品和三个未配置地点。再次指定同一工作区会恢复原数据；要从零体验，换一个新目录，不必删除已有记忆。浏览器刷新会恢复本次执行编号，进程重启后可继续核对候选。

1. 展开“登记新的物品名称”，填写编号、名称与别名。
2. 选中物品、选择正确图片来源、上传参考图。调整框使其覆盖目标并核对；确认后本轮参考固定，不训练新网络。
3. 在“你现在所在的位置”选择地点，发送“请记住，蓝色钥匙我放在这里了”，查看模型解析后点击确认。这里只保存主人陈述，不声称已经视觉识别。
4. 为各地点配置当前场景照片。可以替换原位置的图片，模拟物品已经离开；新搜索读取新配置，进行中的任务保持原输入。
5. 发送“蓝色钥匙找不到了，请先检查最近记录的位置，没找到再继续寻找”。查看真实模型调用数、已执行地点、工具返回与观察图片。
6. 若出现候选，比较参考与实际框，选择接受或拒绝。接受写入 `USER_CONFIRMED / owner_reported`；拒绝会把反馈交回 LLM，继续选择未访问地点或结束为 UNKNOWN。
7. 停止服务并使用同一命令重启，再问“蓝色钥匙最近一次记在哪里”。系统应读取保存的历史。重复使用旧图片不会重新贡献有效搜索证据。

地点目前固定为玄关托盘、书房桌面、客厅茶几；由用户提供位置和图片，没有实时摄像、自动定位或真机导航。模型可以建议搜索顺序，但模型声称“常见位置”不是经过验证的家庭习惯记忆。

本机已有的 `local_data/ai_html_test_20261027/` 是明确标记的 AI 合成素材。参考为 `01_reference_keys.png`，本轮人工核对 ROI `[110,120,1390,950]`；空场景为 `05_empty_entry_tray.png`，候选场景为 `03_keys_study_desk.png`，相似干扰为 `04_rival_red_keys.png`。文件名不证明现实地点，本轮摆放顺序是虚构的流程演示。该本地素材未随公共 PR 发布，克隆者需自行提供图片；不得把缺少素材记为验收成功。

## 实际执行与证据

全量命令与输出保存在 `docs/evidence/issue-30/`，私人完整 HTTP 记录、数据库和截图保存在被忽略的 `artifacts/issue-30/`。基于当前工作区直接运行，未把独立分支的历史测试数量相加。

| 检查 | 本轮实际结果 | 证明范围 |
| --- | --- | --- |
| Python 全量 | 781 passed，128.10 秒，1 项 LangChain 待废弃警告 | 既有 773 项及新增 8 项全部通过 |
| Node 前端 | 8 passed，0 failed | 恢复、轮询竞态、失败上传等回归 |
| 整理后真实 API HTTP 验收 | `http-04`：32 项检查通过，6 个独立请求，16 次模型调用 | 两个新建空工作区，确认与拒绝分支、进程重启、旧图重放 |
| 真实浏览器 | 两个空工作区通过表单登记、上传、保存位置、搜索、确认与拒绝、重启查询 | 真实页面操作，独立于 HTTP 脚本；5 个请求共 12 次模型调用 |
| 干净 Windows 安装 | 新源码快照构建 wheel，全新 venv 安装 `[vision,agent]`，`pip check` 通过，10 项 HTTP 检查通过 | 从仓库外启动规则模式；不是第二次 LLM/视觉精度验证 |

运行命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=artifacts/issue-30/pytest-01.xml
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs
# 需要固定哈希的本地合成素材、已配置且已授权的真实 API；输出目录必须不存在
.\.venv\Scripts\python.exe tools/accept_photo_workflow.py --output-dir artifacts/issue-30/http-new
```

HTTP 工具通过网页相同端点操作，不冒充浏览器自动化。它检查最近地点先被执行，并允许 LLM 在剩余地点间自主选择顺序，不要求每次返回固定脚本路线。单元回归离线确定性，真实 API 验收为显式手工启动，不纳入自动 CI。

实际 HTTP 输出包括：

```text
accept-remember-entry: CONFIRM_MEMORY
accept-memory-confirmed: COMPLETED
find: AWAITING_REVIEW; visited=[entry-tray, study-desk]
candidate-confirmed: USER_CONFIRMED; visual_confirmed=false; history=2
history-after-restart: COMPLETED; latest=study-desk
replay: UNKNOWN; no candidate
reject-find: AWAITING_REVIEW
reject-continue: UNKNOWN; no new owner memory
```

浏览器第一次寻找实际为 **玄关托盘 → 客厅茶几 → 书房桌面**，4 次模型调用；前两处 UNKNOWN，第三处 SUSPECTED。HTTP 该次先到书房，3 次调用。这是模型真实选择差异，未把浏览器轨迹改写成脚本结果。书房合成图的匹配结果为 174 个有效匹配、142 个内点，框 `[439.12,511.97,1194.69,1003.22]`（原图 1448×1086）；精确计时见逐次 JSON。这些是外观候选，不是实体识别精度。

浏览器另一个空工作区实际执行拒绝分支：先玄关、后书房，出现候选后点击“不是它，继续寻找”，模型接收拒绝反馈再检查客厅并结束 UNKNOWN；累计 5 次模型调用，主人位置历史仍为 1 条。拒绝操作是本轮合成流程测试中的脚本化主人判断，不作为视觉正负标签。

原始 ImageMatcher 的平面几何结果可能标为 `raw_match_status=FOUND`；现有照片适配层继续将其降为 SUSPECTED，`identity_confirmed=false`。主人确认也没有改写 `visual_confirmed`。本轮没有更改该可信边界、匹配阈值或模型。

先前 `http-01` 因桌面应用重启中断，保留部分记录，不记通过；`http-02`、`http-03` 为已完成的前序执行。`http-04` 是最终脚本执行证据。浏览器初期因服务进程退出或尚未监听出现连接失败，待服务就绪后恢复；不修改失败记录。早期 AX 文本部分是增量快照，不能单独充当完整页面证据；完整快照、实际 run JSON 与截图分别保留。

## 交付整理范围

- 默认 `/` 直接打开当前 `home-flow.html`，不再先进入旧回放页；默认启动不依赖 OpenCV 公共样例目录或历史 DemoService。
- 安装 wheel 的网页仅 `home-flow.html`、`home-flow.css`、`home-flow.js`。旧 `agent`、`household`、回放页共 9 个文件原样移到 `tests/fixtures/legacy_web/`，不进入 wheel。Git 暂存内容与基线 blob 一致；Windows 工作树行尾遵循原 `core.autocrlf`，不混用工作树字节哈希与仓库 blob 哈希。
- 源码交付允许携带这 9 个精确命名的夹具，以保留原回归；其他夹具图片、私密 JSON、数据库不因此进入白名单。
- 旧测试只显式传入兼容页面目录，原断言不变。核心 ImageMatcher、SearchCore、PhotoAgentService、SQLite schema、config.yaml、实验算法与冻结报告未修改。
- 历史实现和证据仍在源库，用 [历史索引](HISTORY_INDEX.md) 追溯。没有删除旧实验数据或重写其结论。

显式运行旧开发页面（仅完整源码 checkout）：

```powershell
.\.venv\Scripts\python.exe -m hometrace demo --legacy-web-dir tests/fixtures/legacy_web --port 8765
# 如需旧 Agent 页的服务，在上面命令追加 --agent
```

这只提供开发兼容，不是默认交付入口。wheel 不包含历史夹具或私有素材。新版本安装不要复用残留 `build/` 构建结果；本轮使用全新源码快照构建并检查 zip 内容，SHA256 和实际安装版本见证据。

源码白名单实际导出并逐文件核对了 153 个文件，包含当前入口与旧测试夹具，未包含私人照片、数据库、缓存或权重。9 个迁移文件的 Git blob 与基线一致，两份既有测试的断言 AST 不变。提交文件通过常见密钥格式和本机配置 Key 的精确匹配扫描，零命中；扫描不能保证识别所有隐私内容，因此也人工复核了本轮 diff。详见 [源码审计](evidence/issue-30/source-audit.json)、[HTTP 证据](evidence/issue-30/http-acceptance.json)、[浏览器证据](evidence/issue-30/browser-execution.json)、[干净安装](evidence/issue-30/clean-install.json)。

## 剩余工作

1. 按 [实拍拍摄指南](REAL_PHOTO_CAPTURE_GUIDE.md) 先提供同一只 SONY 杯的 6 张参考与 8 张开发场景。我会检查原图、提出 ROI/标注供负责人确认，并记录全部失败。
2. 通过开发诊断后冻结参考、方法与参数，再另外采集两批共 6 正 8 负独立照片；现有合成图、历史调参图都不能充当该证据。
3. 根据真实结果决定视觉改动，不保证补拍即成功，不让 LLM 或类别置信度决定实体 FOUND。
4. 当前 PR 审查后再按审核版本整理正式材料；此次没有更新 Word/PPT/视频或生成正式 ZIP。软件流程可运行不等于整件参赛作品可提交。
