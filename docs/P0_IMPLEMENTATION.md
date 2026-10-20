# Issue #1：P0 离线 fixture 寻物闭环

本阶段以 [GitHub Issue #1](https://github.com/Qcx526/HomeTrace/issues/1) 为任务合同。它建立可安装的 Python 项目、可运行的 CLI 和自动化测试，用于检验寻物决策与记录链路。产品仍以真实图片和最终真机验证为后续目标；Issue #1 明确不要求真实模型或真机集成。

## 当前闭环

用户指定一个已注册目标，系统读取历史记忆，选择候选观察点，通过 `MockAdapter` 模拟导航，取得准备好的 fixture 观察记录，读取该记录的人工测试标注，更新记忆和任务状态，最终输出结构化报告。

内置测试数据使用一个遥控器目标与三个观察点 A、B、C：

1. `moved`：历史记录显示目标曾在 A。本次任务先检查 A，当前未找到后重新规划到 B，在 B 的当前 fixture 标注中确认目标。
2. `missing`：历史记录同样指向 A。本次可用记录无法确认目标，包含未见目标和遮挡情形，最终输出 `UNKNOWN`。

历史 `FOUND` 不直接成为本次 `FOUND`。规划器通过历史记忆与候选点选择下一步，不直接读取未来观察点的目标标注。已访问点不会在同一任务中无限重复搜索。

## 证据与能力边界

| 数据或操作 | 本阶段含义 | 不能据此声称 |
| --- | --- | --- |
| `MockAdapter` / `navigation_mode = mock` | 返回模拟导航结果；没有底盘运动 | 真实机器人已经到达观察点 |
| `data_source = fixture` | 仓库内人工编写的合成测试记录 | 相机真实采集、真实图片检测或真机观测 |
| `image_path = null`、`image_hash = null` | 本阶段没有图像文件作为证据 | 已有可人工核验的现场图像 |
| `matcher = fixture_annotation` | 读取预先准备的测试标注 | 视觉模型已经识别目标 |
| 当前记录的 `FOUND` | 本次 fixture 规则确认目标 | 现实物品存在或识别准确率达到某数值 |
| `NOT_FOUND_IN_VIEW` | 当前可见记录中未发现目标 | 物品不存在于整个房间 |
| `UNKNOWN` | 未得到足够证据确认位置，包括遮挡或候选点耗尽 | 已证实物品不在任何地方 |
| fixture 中的历史时间 | 用于表达测试中的先后关系 | 真实采集时间、真实机器人运行时间或性能数据 |

数据模型保留 `FOUND`、`SUSPECTED`、`NOT_FOUND_IN_VIEW`、`UNKNOWN`、`UNREACHABLE` 等状态。默认的两个 CLI 场景关注历史位置失效后的重新规划与找不到时的诚实结果，不代表所有产品场景已完成。

本阶段没有真实图片、生成图片、模型权重、云 API、ROS、机器人 SDK、SLAM 或三维重建。fixture 中的目标、地点与标注来自项目测试数据的人工编写；它们不是从相机或机器人导出的观察。

## 核心代码结构

| 位置 | 职责 |
| --- | --- |
| `src/hometrace/models.py` | 注册目标、观察点、观测、检测结果、任务事件、状态和报告的数据合同 |
| `src/hometrace/memory.py` | SQLite 记忆存储、查询与本次运行快照 |
| `src/hometrace/search_core.py` | 历史查询、候选点选择、状态推进、记忆更新与报告构建 |
| `src/hometrace/environment.py` | 环境接口与明确标记模拟导航的 `MockAdapter` |
| `src/hometrace/perception.py` | 读取当前 fixture 观测的测试标注 |
| `src/hometrace/fixtures.py` | 加载并校验离线测试 fixture |
| `src/hometrace/fixture_data/` | 随包分发的 `moved.json` 与 `missing.json` 测试记录 |
| `fixtures/README.md` | fixture 格式、测试来源与使用约束 |
| `src/hometrace/cli.py`、`src/hometrace/__main__.py` | CLI 参数、输出文件和 `python -m hometrace` 入口 |
| `tests/` | 状态、规划、记忆与负向路径的自动化测试 |
| `pyproject.toml` | Python 包与开发测试依赖 |

Search Core 通过环境、观察与记忆接口运行，不依赖特定视觉模型、UI 或机器人 SDK。运行时使用 Python 标准库，SQLite 由标准库提供；pytest 用于开发测试。

## 安装与运行

需要 Python 3.11 或更高版本。在仓库根目录按 [README](../README.md#运行本阶段-demo) 创建虚拟环境并安装：

```text
python -m venv .venv
```

Windows PowerShell 中：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m hometrace --scenario moved --output-dir artifacts/moved
.\.venv\Scripts\python.exe -m hometrace --scenario missing --output-dir artifacts/missing
.\.venv\Scripts\python.exe -m pytest -q
```

在 macOS / Linux 中将上述解释器路径替换为 `.venv/bin/python`。在已激活的虚拟环境中，单条 Demo 命令为：

```text
python -m hometrace --scenario moved --output-dir artifacts/moved
```

CLI 参数：

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `--scenario` | `moved` | 选择 `moved` 或 `missing` 内置 fixture |
| `--object-id` | `remote-control` | 查找 fixture 中已注册的目标 |
| `--fixture` | 未指定 | 指定自定义 JSON 测试 fixture |
| `--output-dir` | `artifacts/demo` | 保存本次运行产物的目录 |

`--fixture` 与 `--scenario` 不能同时指定。自定义 fixture 应遵循仓库内置 JSON 的格式与校验约束。`--fixture` 只用于测试输入，不会把输入提升为真实图片或真机数据。请先查看 `python -m hometrace --help`、[fixture 格式与来源说明](../fixtures/README.md) 和 [moved fixture](../src/hometrace/fixture_data/moved.json)，再构造自己的记录。

成功完成搜索任务时退出码为 `0`，包括诚实返回 `UNKNOWN` 的任务；输入或文件错误返回 `2`。脚本应读取报告中的 `result_status` 判断是否找到目标，不能把进程成功退出理解为 `FOUND`。

## 运行产物

每次运行从所选 fixture 建立独立的内存 SQLite 数据库，结束后导出以下文件：

| 文件 | 内容 |
| --- | --- |
| `report.json` | 目标、最终状态、位置、已访问点、观测证据、事件、来源和限制 |
| `events.jsonl` | 每行一个结构化事件，用于核验查询、规划、模拟导航、观测和状态变化 |
| `memory.sqlite3` | 初始历史记忆与本次新增记忆的 SQLite 快照 |

CLI 同时向终端展示执行结果。同一路径再次运行会覆盖这三个同名产物；它不会把上次的 SQLite 快照读回作为下一次的历史。需要保存多次结果时应使用不同的 `--output-dir`。

核验 `moved` 时，应检查当前访问顺序先 A 后 B、A 的当前结果未找到、最终 `location` 为 B，并确认支撑 `FOUND` 的证据来自本次 B 观测。核验 `missing` 时，应检查最终 `result_status` 为 `UNKNOWN`、`location` 为 `null`，并查看逐点负例与遮挡记录。两份报告均应明确写出 fixture 来源及模拟导航。

## 实际验证结果

2026-10-20 在 Windows / Python 3.11.4 环境中构建 wheel，创建全新的虚拟环境，以非 editable 方式安装 wheel 和 pytest 后执行测试及两个 CLI 场景。`pip check` 通过，pytest **54 项通过**。本次没有在 macOS / Linux 上执行验证，也没有采集模型性能或机器人运动数据。

| 实际执行项 | 结果 | 可核验产物 |
| --- | --- | --- |
| `python -m pytest -q` | 54 passed | [pytest 原始输出](evidence/issue-1/pytest.txt) |
| `python -m hometrace --scenario moved --output-dir artifacts/moved` | A → B；`FOUND`；位置 B | [终端输出](evidence/issue-1/moved/stdout.txt)、[sample report JSON](evidence/issue-1/moved/report.json)、[事件日志](evidence/issue-1/moved/events.jsonl) |
| `python -m hometrace --scenario missing --output-dir artifacts/missing` | A → B → C；`UNKNOWN`；位置 `null` | [终端输出](evidence/issue-1/missing/stdout.txt)、[最终报告](evidence/issue-1/missing/report.json)、[事件日志](evidence/issue-1/missing/events.jsonl) |
| wheel 构建与全新环境安装 | 均成功退出 | [构建输出](evidence/issue-1/wheel-build.txt)、[安装输出](evidence/issue-1/clean-install.txt) |
| 安装来源与依赖检查 | 从新环境的 `site-packages` 导入；依赖无冲突 | [解释器与模块位置](evidence/issue-1/installed-package.txt)、[pip check](evidence/issue-1/pip-check.txt)、[依赖版本](evidence/issue-1/dependencies.txt) |

[验证清单](evidence/issue-1/validation.json) 记录实际解释器、逐条命令、退出码、环境与源码 SHA-256。命令中的 `<REPO>` 代表仓库绝对路径；上表为便于阅读而省略了虚拟环境解释器路径。SQLite 快照由 CLI 生成，未将数据库二进制文件提交到仓库。

两次真实执行的软件 Demo 输出分别包含以下结果行；这里的“真实执行”指运行程序，不指真实图片或真实机器人：

```text
HomeTrace P0 | Mock navigation | data_source=fixture
RESULT FOUND location=B
VISITED A,B
```

```text
HomeTrace P0 | Mock navigation | data_source=fixture
RESULT UNKNOWN location=null
VISITED A,B,C
```

## 验收范围

Issue #1 的验收项与本阶段交付对应如下；实际执行命令与原始输出以 PR 中保存的运行证据为准，不用这里的预期行为代替测试结果。

| Issue #1 要求 | 本阶段对应 |
| --- | --- |
| 清晰的 Search Core、environment mock、data models、CLI 与 pytest | 独立的 Python 模块、`python -m hometrace` 入口和 `tests/` |
| 三个观察点与单目标示例数据 | A、B、C 与 `remote-control` 的两个内置 fixture |
| 查询记忆 → 选择地点 → 模拟导航 → 读取测试观察记录 → 判断 → 更新 → 日志和报告 | 两个 CLI 场景及 JSON / JSONL / SQLite 运行产物 |
| 目标从 A 移至 B 后能够重新规划 | `moved` fixture、对应自动化测试与实际 Demo 日志 |
| 找不到时不能假报 `FOUND` | `missing` fixture、负向测试与最终 `UNKNOWN` 报告 |
| 明示 `MockAdapter` 与 fixture 来源 | 终端提示、观测来源、导航来源和报告限制 |
| requirements / pyproject、README 命令与 sample report JSON | `pyproject.toml`、README 快速运行步骤、[实际样例报告](evidence/issue-1/moved/report.json) |
| 干净环境安装运行、pytest 通过，PR 列出命令和输出 | 全新虚拟环境安装 wheel，54 项测试通过；命令、退出码及两个 Demo 的实际输出见上方证据索引 |

`PRODUCT_BRIEF.md` 与 `DEMO_ACCEPTANCE.md` 描述了更广的产品及参赛验收，以下事项尚未在本阶段完成，不能由 Issue #1 的 fixture 成功运行替代：

- 真实拍摄图片与物品、地点、历史时间的关联。
- 真实图片识别、人工核验图像与附图结果。
- 固定顺序与记忆优先搜索的同场景基准比较。
- 界面、演示录屏、赛事 Word / PPT 等材料。
- 官方底盘、RobotClaw API 核实及真实机器人验证。

本阶段完成后只提交 feature 分支与指向 `main` 的 PR，由 PM 审查并决定后续工作；不自动合并，也不提前实施 Issue #2。
