# Issue #3：可视化寻物 Demo

本阶段以 [Issue #3](https://github.com/Qcx526/HomeTrace/issues/3) 和 [2026-10-22 PM 补充要求](https://github.com/Qcx526/HomeTrace/issues/3#issuecomment-6331797159) 为验收合同。界面展示现有 Search Core 的真实运行报告：公开实拍照片匹配、跨运行 SQLite 记忆、模拟导航，以及带来源的搜索结果。P1 已通过软件技术审查；团队家庭场景、实时摄像头和真实机器人仍未验证。

## 启动

在仓库根目录安装 Python 3.11+ 环境与可选视觉依赖，然后启动本地页面：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,vision]"
.\.venv\Scripts\python.exe -m hometrace demo --port 8765 --output-dir artifacts/p2-demo
```

浏览器访问 `http://127.0.0.1:8765`。服务默认仅监听本机。停止服务使用终端 `Ctrl+C`。安装完成后，样例演示不需要下载模型权重或访问云服务。macOS / Linux 的解释器路径为 `.venv/bin/python`；本阶段是否完成该平台实测以最后的验证记录为准。

入口不自动打开外部浏览器。默认从仓库的 `examples/recorded_images` 读取样例，`--samples-dir` 可指定同一格式的样例目录（需要 `history.json`、`moved.json`、`missing.json` 与 `box.png` 参考图）。界面的三段叙事围绕内置公开样例；团队照片使用 P1 输入指南另行采集和核验，替换清单必须如实填写来源及时间依据，不能直接沿用公开样例的采集说明。

每次运行建立唯一目录，输入快照、两种策略各自的数据库、登记/搜索报告和命令日志均保存在 `--output-dir/<run_id>/`。旧图重放场景两侧先执行同样的记忆优先搜索，再比较本轮两种策略，确保前置历史相同。服务不会删除已有运行目录，重复演示会增加本地文件。仅展示当前服务器启动期间生成的运行，重启后旧文件仍留在磁盘。报告下载和图片访问采用显式文件清单，图片展示前核对快照哈希。

页面从服务取得本次实际运行的报告，再按报告事件进行逐步回放。播放速度控制的是界面展示节奏，不是搜索性能，也不代表机器人移动时间。界面保留最终 JSON 状态，不能为了叙事把 `SUSPECTED` 改写成 `NOT_FOUND_IN_VIEW`。

## 连续演示三个场景

无需修改源码，在页面依次运行以下场景。可使用逐步查看、自动播放和最终结果视图；在每段结束时保存报告与事件。

| 场景 | 需要让观众看清的过程 | 结果的正确解释 |
| --- | --- | --- |
| `moved` 正例 | 历史 A → 模拟访问 A → A 照片匹配未确认 → 继续计划 B → B 照片上显示检测框和证据 | B 的参考外观匹配为 `FOUND`；A 的 `SUSPECTED` 只是当前图像不足以确认 |
| `missing` 未确认负例 | 查看 A/B/C 的逐点状态、照片和证据；检查已尝试、已到达、已解码观察三组记录 | 以实际报告为准；现有公开样例可能为 `SUSPECTED`，位置为空、确认列表为空，不能说物品不存在 |
| `replay` 旧图重放保护 | 先建立历史并执行一次搜索，再对同一记忆库重放旧照片；查看旧证据被拒绝的原因 | 历史 `FOUND` 不变成本轮确认；被拒绝的旧图不应再次产生本轮检测框或观察计数 |

`attempted` 表示尝试导航，`arrived` 表示模拟到达，`observed` 表示本轮照片成功解码。三者都不证明机器人发生了真实运动。旧图可能出现在观察事件中，但如果被来源、时间或重放检查拒绝，不能将它记为本轮成功解码匹配。

历史卡片与当前照片分别显示。登记历史 A 使用参考图本身，这是自参考登记，不算独立识别成绩；独立正例为 `box_in_scene.png`。照片原始文件和授权说明见 [公开样例说明](../examples/recorded_images/README.md)，SHA256 与固定上游来源见 [sources.json](../examples/recorded_images/sources.json)。

## 固定顺序与记忆优先对照

两种策略复用同一 Search Core、检测器和输入照片；只改变下一观察点的选择：

- `fixed_order`：按观察点 ID 的固定顺序搜索。
- `memory_first`：优先已有记忆中的候选；无可靠优先信息时使用既有确定性回退规则。

公平比较使用相同候选点、相同照片字节、相同注册历史及相同检测配置。两侧使用独立数据库，避免前一策略新增的证据污染后一策略。旧图保护对照的两侧须拥有相同的重放前置历史。

记录实际尝试步数、模拟到达数、成功解码观察数、访问顺序、结果状态和位置。步骤少不自动代表现实移动耗时更短；不使用虚构导航时间。规划器不得读取尚未取得的图像或评测答案。

当前公开样例从历史 A 开始，而固定顺序也从 A 开始，实测打平。打平是有效结果，不能宣称记忆策略在这些输入上降低搜索步数，也不能从一组编排的照片推断家庭场景性能。重放时记忆优先 B→A→C、固定顺序 A→B→C，计数仍相同。若未来补充不同历史位置，应保留同图同候选的比较条件，并说明时间顺序如何满足证据合同。

## 录屏流程

以下是最终比赛视频可使用的操作清单。本 PR 已提供 [50.24 秒实际浏览器录屏](evidence/issue-3/browser/demo-three-scenarios.mp4)：自动操作 Edge 连续演示三场景，未配音，未录入终端启动画面；它是工程验证片段，尚不是最终比赛解说视频。原始 WebM 留在本地，提交的 MP4 仅转码、未改写事件，元数据与原始/转码哈希见 [video-metadata.json](evidence/issue-3/browser/video-metadata.json)。

1. 录到终端启动命令，再切换浏览器首页。让“公开实拍照片”“模拟导航”以及团队家庭场景未验证的说明可见。
2. 选择 `moved` 和记忆优先，运行后展示历史 A、登记自参考提示。推进到 A，停留展示实际照片、`SUSPECTED` 和决策原因；解说“当前图像不足以确认，继续检查下一点”。
3. 推进至 B，展示真实匹配框、`FOUND`、证据 ID、图片路径及哈希。查看最终位置和 attempted/arrived/observed；打开对应报告。
4. 连续切换 `missing`，展示三个点仍未确认，最终位置为空。不要使用“百分之百准确”“已证明房间内没有物品”等说法。
5. 连续切换 `replay`，展示相同照片被拒绝的原因、本轮确认列表及旧历史的区别。不要将旧历史框叠成当前检测结果。
6. 展示两种策略的同输入对照表；按实际数值解释搜索步数和观察次数，打平时明确说打平。
7. 结尾展示能力边界和源码/测试证据入口。说明项目创新在记忆、决策与证据闭环；视觉部分复用成熟 OpenCV 方法。

录屏时保留页面中的来源和模拟标识。裁掉浏览器账号、桌面通知和其他窗口中的个人信息；原始家庭照片与正式团队资料只有在授权后才能出现在公开视频。建议保留未经剪辑的运行记录及同次运行报告，剪辑版本不得改变事件先后或结果。

## 提交证据与验收

2026-10-22 在 Windows 10 / Python 3.11.4 的全新虚拟环境安装非 editable 的 0.3.0 wheel；导入来自 site-packages，UI 静态资源已打入 wheel。**148 项通过、0 跳过**，其中原有 P0 54 项、P1 68 项文件未修改。额外 26 项覆盖策略、真实进程/SQLite 比较、中文输出目录、HTTP 访问边界和打包后资源。视觉依赖仍可选，无 OpenCV 时相关视觉测试跳过，P0 可继续运行。

| 验收项 | 实际证据 | 结果 |
| --- | --- | --- |
| P0/P1 回归与新增测试 | [pytest 输出](evidence/issue-3/pytest.txt)、[JUnit](evidence/issue-3/pytest.xml)、[验证与源码摘要](evidence/issue-3/validation.json) | 148 passed in 30.24s，0 skipped |
| 三场景连续运行 | [录屏](evidence/issue-3/browser/demo-three-scenarios.mp4)、[浏览器逐步检查](evidence/issue-3/browser/browser-checks.json) | FOUND/B、SUSPECTED/null、UNKNOWN/null |
| 检测框与报告一致 | [B 实际截图](evidence/issue-3/browser/moved-matched.png)、[同次报告](evidence/issue-3/browser/moved-report.json) | 框 `[90.4,159.53,285.45,296.16]` 与 SVG 原图坐标一致 |
| 逐步回放语义 | [A 未确认](evidence/issue-3/browser/moved-unconfirmed-A.png)、[旧 B 拒绝](evidence/issue-3/browser/replay-rejected-B.png)、[窄屏](evidence/issue-3/browser/mobile.png) | 仅显示事件前缀；旧图无当前框/不计 observed；无 JS 异常，390px 无页面横向溢出 |
| 公平策略对照 | [moved](evidence/issue-3/moved/comparison.json)、[missing](evidence/issue-3/missing/comparison.json)、[replay](evidence/issue-3/replay/comparison.json) | 两侧同输入快照、独立数据库；三个场景计数打平 |
| 本地安装与启动 | [安装命令](evidence/issue-3/setup/commands.json)、[导入位置](evidence/issue-3/setup/installed-package.txt)、[依赖检查](evidence/issue-3/pip-check.txt) | wheel 安装及 UI 资源验证通过；Edge 155.0.4283.45 |
| 团队自产家庭照片 | 独立历史图与移动后的当前图、成功/失败记录、授权 | 尚未提供 |

| 场景 | 记忆优先 / 固定顺序 | 尝试步数（两侧） | 模拟到达（两侧） | 有效解码（两侧） | 最终结果（两侧） |
| --- | --- | --- | --- | --- | --- |
| moved | A→B / A→B | 2 | 2 | 2 | FOUND，B |
| missing | A→B→C / A→B→C | 3 | 3 | 3 | SUSPECTED，null |
| replay | B→A→C / A→B→C | 3 | 3 | 1（仅 C） | UNKNOWN，null |

复测命令（输出目录必须尚不存在）：

```powershell
.\.venv\Scripts\python.exe tools/validate_p2.py --output-dir artifacts/new-p2-validation
```

浏览器检查是开发工具，不是 Demo 运行依赖。已有 Node.js 时可单独安装 Playwright，启动 Demo 后执行：

```powershell
npm install --no-save --package-lock=false playwright
npx playwright install msedge ffmpeg
node tools/validate_p2_browser.cjs http://127.0.0.1:8765 artifacts/new-browser-check
```

浏览器检查逐步核对计数、最终结果隐藏时机、检测框坐标、旧图无框、下载报告一致性，另输出截图和连续 WebM。默认 Edge；其他已安装 Playwright 浏览器可用 `HOMETRACE_BROWSER_CHANNEL` 配置，但本轮只验证 Windows Edge。自动检查用短暂停留呈现页面，不把等待时间记为搜索性能。证据目录 README 区分干净安装验证与浏览器录制的两次独立运行。

实现仅在 Search Core 增加策略选择；`demo_service.py` 负责同输入运行及文件证据，`demo_server.py` 提供本机 HTTP，`web/` 按原始事件渲染。浏览器不向核心传入检测答案，不更改 `result_status`。当前 UI 计算完成后播放事件，尚未提供边执行边流式更新或真实机器人运动。

实际来源边界沿用 [P1 实现说明](P1_IMPLEMENTATION.md)：`FOUND` 是有几何支持的参考外观匹配，不能区分相同包装实体；哈希能阻止字节相同的旧图，不能认证拍摄时间或检测所有编辑过的旧图。Issue #4 的材料与最终 ZIP 另按 [交付准备表](SUBMISSION_READINESS.md) 推进。
