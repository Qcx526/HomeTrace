# Issue #2：公开实拍图片匹配与持久记忆

本阶段在 P0 Search Core 上加入本地图片输入、OpenCV 参考外观匹配和跨进程 SQLite 记忆。以 [Issue #2](https://github.com/Qcx526/HomeTrace/issues/2) 为合同；原有 fixture CLI 和 54 项 P0 测试保留。本阶段不做 GUI、提交材料、云 API、ROS 或真实机器人集成。

## 安装与两个进程的 Demo

Python 3.11+；在仓库根目录创建虚拟环境并安装可选视觉依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,vision]"
```

P0 不需要 `vision`。P1 的 `opencv-python-headless` 提供 ORB、Hamming 匹配与 RANSAC 单应性估计，不下载模型权重，不训练视觉模型。选择依据见 [P1 视觉方案](P1_VISION_CHOICE.md)。

在第一个进程登记目标和历史，在第二个进程查库搜索：

```powershell
.\.venv\Scripts\python.exe -m hometrace register --db artifacts/p1-moved/memory.sqlite3 --object-id sample-box --reference box.png --scene examples/recorded_images/history.json --output-dir artifacts/p1-moved/register
.\.venv\Scripts\python.exe -m hometrace search --db artifacts/p1-moved/memory.sqlite3 --object-id sample-box --scene examples/recorded_images/moved.json --output-dir artifacts/p1-moved/search
```

负例另用一个数据库，避免负例照片因之前已读过而被当作重放拒绝：

```powershell
.\.venv\Scripts\python.exe -m hometrace register --db artifacts/p1-missing/memory.sqlite3 --object-id sample-box --reference box.png --scene examples/recorded_images/history.json --output-dir artifacts/p1-missing/register
.\.venv\Scripts\python.exe -m hometrace search --db artifacts/p1-missing/memory.sqlite3 --object-id sample-box --scene examples/recorded_images/missing.json --output-dir artifacts/p1-missing/search
.\.venv\Scripts\python.exe -m pytest -q
```

macOS / Linux 使用 `.venv/bin/python` 代替上述解释器路径。每次完整重演应选新的 `--db` 路径；`register` 不覆盖已有目标。已有目标只能通过 `search` 读取；同一照片换证据 ID、文件名或时间不能成为独立新观察。

| 参数 | 含义 |
| --- | --- |
| `--db` | 必填，持久 SQLite 文件；不能为 `:memory:`；搜索要求它已存在 |
| `--object-id` | 必填，注册目标 ID；搜索要求目标已登记且来源为 `recorded_image` |
| `--scene` | 必填，无检测答案的本地 JSON 场景清单 |
| `--image-root` | 可选，默认清单所在目录；参考图和当前图都必须位于该目录内 |
| `--reference` | 仅登记必填，图像根目录下的参考图相对路径 |
| `--description` | 仅登记可选，目标描述 |
| `--output-dir` | 必填，保存本次 `report.json` 与 `events.jsonl` |

P1 持续写入 `--db` 指定的数据库，不向输出目录另存数据库快照。输出文件同名时覆盖；输出失败会回滚本次数据库变更，但输出目录可能留下部分文件。应检查退出码：完成搜索包括 `UNKNOWN` / `SUSPECTED` 时为 `0`，不可用的参考图、非法清单、未注册目标、文件或数据库错误为 `2`。

## 输入格式与来源

可从 [history.json](../examples/recorded_images/history.json)、[moved.json](../examples/recorded_images/moved.json) 和 [missing.json](../examples/recorded_images/missing.json) 复制清单结构。根对象要求以下字段；仅 `unreachable_viewpoints` 可选：

| 字段 | 要求 |
| --- | --- |
| `schema_version` | 整数 `1` |
| `data_source` | 固定为 `recorded_image` |
| `navigation_mode` | 固定为 `simulated_navigation` |
| `timestamp_basis` | `demo_sequence` 或 `declared_capture` |
| `capture_source` | 非空来源说明；需如实说明原拍摄时间未知等限制 |
| `viewpoints` | 非空观察点数组，每项包含唯一 `viewpoint_id` 和 `name` |
| `observations` | 每点至多一帧，每帧包含 `evidence_id`、`viewpoint_id`、`captured_at`、`image_path`、`visibility_status` |
| `unreachable_viewpoints` | 可选，唯一且已登记的观察点 ID，用于模拟不可达 |

`captured_at` 要求带时区的 ISO 时间；它的实际含义由 `timestamp_basis` 说明。`demo_sequence` 只表达回放顺序；`declared_capture` 是操作者声明的拍摄时间，未经相机硬件或 EXIF 认证。新接纳观测必须晚于已存及本次已接纳观测，且时间依据一致；候选点的规划顺序也应与可用记录的时间顺序相容。

`visibility_status` 可为 `clear`、`occluded` 或 `unobservable`；可见性声明不是目标答案。所有层级拒绝未知字段与重复 JSON 字段，不接受人工 `FOUND`、检测标注或调用方指定的图像哈希。检测只能读取图像像素；SHA256 由实际文件字节计算。

路径使用根目录内的相对 POSIX 形式，如 `images/current.png`，不接受绝对路径、反斜杠、`..` 或解析后越出根目录的链接。支持 PNG、JPG/JPEG、BMP、WEBP、TIF/TIFF；单文件不超过 25 MiB，解码图像不超过 2400 万像素且边长至少 32 像素。缺失、损坏、不可读或过大场景图按不可确认观测处理；参考图不可用则无法启动有效匹配，返回输入错误。

## 五张公开照片的含义

用户授权使用五张 OpenCV 公开实拍照片，其原始字节未经修改。固定上游提交、逐图下载 URL、SHA256 和文件大小见 [sources.json](../examples/recorded_images/sources.json)；[来源说明](../examples/recorded_images/README.md) 保留 [上游 Apache-2.0 许可](../examples/recorded_images/LICENSE.opencv.txt)、[版权告知](../examples/recorded_images/COPYRIGHT.opencv.txt) 和 [历史许可告知](../examples/recorded_images/LICENSE_CHANGE_NOTICE.opencv.txt)。

| 图片 | 用途与证据边界 |
| --- | --- |
| `box.png` | 登记参考图，也被安排为历史 A；自参考登记不算一次独立正例 |
| `box_in_scene.png` | 不同场景与字节的真实照片，作为当前 B 的跨图正例 |
| `apple.jpg`、`orange.jpg`、`fruits.jpg` | 人工核验不含目标包装外观的负例；答案只用于评价，不放进搜索清单 |

照片不是团队在家庭现场拍摄，也不是机器人数据；原摄影者和原拍摄日期未知。A/B/C、照片与地点的对应以及清单时间均是 Demo 编排，不证明现实发生过 A→B 的搬移。替换为团队照片的步骤见 [样例说明](../examples/recorded_images/README.md#替换为团队自行拍摄的图片)。

## 记忆、决策与报告

登记目标的参考路径、SHA256 和来源固定，不能由后续观察改写；搜索重新加载参考图并验证字节与登记值一致。SQLite 保存原始观测和检测结果，已有证据不可重写。相同证据 ID、已见图像 SHA256、搜索时重用参考图字节，都会被拒绝为当前新证据。哈希只能阻止字节相同的重放，不能证明拍摄时间或识别所有重新编码、裁切后的旧照片。

规划器使用已取得的历史记忆和候选点，不读取未来图像的答案。它先检查历史位置；本轮未确认后继续访问未尝试点。历史 `FOUND` 不等于当前发现。图像匹配使用 ORB、Hamming 近邻筛选、互异匹配、RANSAC 内点及几何检查；`FOUND` 表示有足够几何支持的参考外观匹配，不能识别任意类别，也不能区分相同印刷包装的两个实体。

不可靠匹配返回 `UNKNOWN` 或 `SUSPECTED`；负例上也可能存在少量误匹配而得到 `SUSPECTED`，这不能写作“已找到”。P1 不由特征匹配失败产生可靠的 `NOT_FOUND_IN_VIEW` 负证据，更不能推断物品在房间中不存在。遮挡、低纹理、模糊、缺图等原因保留在事件和诊断字段中。

报告使用 `schema_version = 2`，主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `operation` | `register` 或 `search`，区分登记与当前寻找 |
| `historical_evidence` | 本次运行开始时从数据库读出的历史证据 |
| `evidence` / `evidence_ids` | 本轮接纳并处理的证据，可能包含未确认或读取失败记录 |
| `confirmed_evidence_ids` | 本轮检测为 `FOUND` 的证据；需结合 `operation` 判断是否仅为登记自参考 |
| `attempted_viewpoints` | 已尝试的导航点，包括导航失败 |
| `arrived_viewpoints` | 模拟导航成功到达的点，不是真实运动 |
| `observed_viewpoints` | 图像已成功解码的点；不代表已找到或可见性良好 |
| `visited_viewpoints` | 为旧接口保留的 `attempted_viewpoints` 别名，不是到达或观测证明 |
| `result_status` / `location` | 最终判断及确认位置；未确认时位置为 `null` |
| `data_source` / `navigation_mode` | `recorded_image` / `simulated_navigation`，不能冒充 `real_robot` |

观测记录保存文件哈希；检测诊断记录匹配数、内点数、几何覆盖度、原因、OpenCV 版本、随机种子、线程数与实际处理耗时。耗时只描述此次 PC 上的匹配执行，不包括机器人移动，也不是嵌入式设备性能。

## 代码结构

| 模块 | 本阶段职责 |
| --- | --- |
| `recorded_cli.py` | 独立 register/search 入口、持久库与输出事务 |
| `recorded.py` | 严格清单校验、受限路径、实际文件哈希、模拟导航与图片观察 |
| `image_matcher.py` | 可选 OpenCV 依赖、实际图片解码、参考实例外观匹配与诊断 |
| `memory.py` | 参考身份固定、持久证据、事务及原有 P0 数据库的增量兼容 |
| `search_core.py` | 按来源处理证据、拒绝重放/过期记录、继续搜索、分开历史与当前报告 |
| `models.py` | 来源、导航、时间依据与扩展报告的数据合同 |

Search Core 不直接依赖 OpenCV；P0 通过 fixture 检测器运行，P1 通过图像匹配器运行。未安装视觉 extra 时仍可运行 P0。

## 验收与证据

2026-10-21 在 Windows 10 / Python 3.11.4 的全新虚拟环境中安装非 editable wheel 并完成验证：**122 项测试通过，0 跳过**，其中原有 54 项 P0 测试全部通过；原有四个测试文件相对基线 `caf693f` 无改动。已从安装环境的 `site-packages` 导入 HomeTrace，`pip check` 通过。

| 实际验证项 | 结果与证据 |
| --- | --- |
| wheel 构建、全新环境安装 | [逐条安装命令](evidence/issue-2/setup/commands.json)、[构建日志](evidence/issue-2/setup/wheel-build.txt)、[安装日志](evidence/issue-2/setup/clean-install.txt)、[导入位置与版本](evidence/issue-2/setup/installed-package.txt) |
| 全量测试与依赖 | [pytest 输出](evidence/issue-2/pytest.txt)、[逐例 JUnit 结果](evidence/issue-2/pytest.xml)、[pip check](evidence/issue-2/pip-check.txt)、[依赖版本](evidence/issue-2/dependencies.txt) |
| 独立进程登记 | [moved 登记日志](evidence/issue-2/moved/register/stdout.txt) 与 [登记报告](evidence/issue-2/moved/register/report.json)；参考图自匹配仅用于建立历史 |
| moved 当前搜索 | A `SUSPECTED` → B `FOUND`；位置 B，确认 ID 为 `opencv-moved-B`；[日志](evidence/issue-2/moved/search/stdout.txt)、[报告](evidence/issue-2/moved/search/report.json)、[事件](evidence/issue-2/moved/search/events.jsonl) |
| 独立库 missing 搜索 | A `SUSPECTED` → B `UNKNOWN` → C `SUSPECTED`；最终 `SUSPECTED`，位置 `null`、确认 ID 为空；[登记报告](evidence/issue-2/missing/register/report.json)、[搜索日志](evidence/issue-2/missing/search/stdout.txt)、[搜索报告](evidence/issue-2/missing/search/report.json)、[事件](evidence/issue-2/missing/search/events.jsonl) |
| 同库重放 moved | B/A 旧证据拒绝，最终 `UNKNOWN`；尝试与模拟到达 B、A、C，只有 C 成功产生新的解码观察；[日志](evidence/issue-2/replay/stdout.txt)、[报告](evidence/issue-2/replay/report.json) |
| P0 CLI 回归 | moved 为 `FOUND` / B，missing 为 `UNKNOWN`；[moved 日志](evidence/issue-2/p0-moved/stdout.txt)、[missing 日志](evidence/issue-2/p0-missing/stdout.txt) |

[验证清单](evidence/issue-2/validation.json) 保存实际命令、退出码和源码 SHA256；日志中的 `<REPO>` 代替本机仓库绝对路径。当前搜索确实读取历史：两次首次搜索都记录 `HISTORY 1`。moved 的 A 有 9 个筛选后匹配点，未获几何确认；B 有 45 个匹配点、41 个 RANSAC 内点，才返回 `FOUND`。负例最终 `SUSPECTED` 表示尚不能确认，不可写成找到，也不可写成物品不存在。

已安装 `dev,vision` 的环境可用以下命令复跑测试、两种场景、重放检查和图片测时；输出目录必须是尚不存在的新目录：

```powershell
.\.venv\Scripts\python.exe tools/validate_p1.py --output-dir artifacts/new-validation
```

### 小样本图像结果与 PC 耗时

[原始图像结果](evidence/issue-2/vision-results.json) 评估 4 张不同的公开实拍照片：1 正例、3 负例，排除 `box.png` 登记自匹配。结果为误报 `FOUND` 0、正例未确认 0、负例 `SUSPECTED` 2。样本规模只支持这四张照片的流程核验，不构成准确率基准。

环境为 Windows 10、Python 3.11.4、OpenCV wheel 4.14.0.94（运行库 4.14.0）、NumPy 2.4.6；CPU 标识 `Intel64 Family 6 Model 151`，12 个逻辑核。OpenCV 固定 1 线程、种子 0。每张图重复调用 10 次，仅用于测时，不算新增独立观察。

| 图片 | 实际状态 | 匹配数 / 内点数 | 单次调用中位耗时（ms） |
| --- | --- | --- | --- |
| `box_in_scene.png` | `FOUND` | 45 / 41 | 32.60 |
| `apple.jpg` | `SUSPECTED` | 9 / 0 | 10.23 |
| `orange.jpg` | `UNKNOWN` | 3 / 0 | 11.73 |
| `fruits.jpg` | `SUSPECTED` | 4 / 0 | 30.56 |

耗时包括文件哈希、解码、特征与几何处理，不包括解释器启动和参考特征初始化，文件读取可能命中缓存；表中中位数四舍五入到 0.01 ms，原始最小值、中位数和最大值保存在 JSON。端侧延迟为未验证；团队家庭照片、实时摄像头、真实机器人和 macOS / Linux 均未在本轮验证。

| P1 合同项 | 实现与核验方式 |
| --- | --- |
| 保留 P0，扩展现有 Search Core | 原有 moved / missing fixture、CLI 与 54 项测试保留；新增来源分支、证据校验与报告字段 |
| 读取真实图片并复用现有视觉方法 | OpenCV 参考外观匹配；公开原图、哈希、许可与方法选择可追溯 |
| 注册实际物品外观与持久历史记忆 | `sample-box` 对应实拍包装盒外观；`register` 保存参考身份及历史，独立 `search` 进程读取同一 SQLite |
| 历史位置失效后继续搜索 | moved 编排先检查 A，再以 B 的不同照片寻求当前确认 |
| 负例和不可观察情形不假报找到 | 独立 missing 数据库；`UNKNOWN` / `SUSPECTED`、缺图与低质量诊断 |
| 来源、历史与当前观测分开 | `recorded_image`、时间依据、独立历史字段、当前确认 ID 与访问三种状态 |
| 不把同图重放当新证据 | ID、图像内容哈希、参考字节与时间依据校验 |
| 团队照片可替换、素材许可可追溯 | 本地路径与清单输入；公开原图与来源说明；团队拍摄步骤明确隐私和时间声明 |
| 测试与复现 | 原有 P0 测试保留；本轮 122 项通过，含图片、清单、持久化与证据完整性测试；实际正负例和 PC 耗时见上方证据 |

当前公开照片仅验证一个有纹理的近似平面外观，尚未验证团队家庭场景、低纹理遥控器、外观相同的多个实体或端侧设备。Issue #3 的界面、Issue #4 的提交材料以及真实机器人验证尚未完成。本次交付停在待 PM 审查；PM 通过后可按用户授权合并，Issue #3 / #4 另行实施。
