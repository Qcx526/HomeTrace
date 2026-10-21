# HomeTrace — 家庭时空记忆与主动寻物机器人

> Huawei Embedded AI Challenge 2026 / 开放创新赛道

**项目状态：** 本分支实现 [Issue #1](https://github.com/Qcx526/HomeTrace/issues/1) 的 P0 离线 fixture 寻物闭环，等待 PM 审查。本阶段使用人工编写的测试标注和模拟导航，尚无真实图片识别或机器人真机结果。

## 一句话产品定义

HomeTrace 让家庭机器人记住物品曾经在哪里，通过历史位置与实时观察，自主搜索被移动的物品，并给出附有观测证据的搜索结果。

## 初赛目标（2026-10-28 12:00 前）

在不依赖官方底盘的条件下完成可互动的小 Demo：用户指定已注册物品 → 查询历史记忆 → 选择搜索地点 → 在**真实采集**的场景图片中识别 → 找不到时更新判断并重规划 → 输出结果与证据。模拟导航和真实图像观察必须清晰区分。

比赛评分关注创新性、实现完整性与可实用性。优先使用成熟开源视觉方法，产品创新与执行闭环优先于从零发明算法。

## 运行本阶段 Demo

需要 Python 3.11 或更高版本。运行时仅使用 Python 标准库；测试使用 pytest。以下命令在仓库根目录执行。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m hometrace --scenario moved --output-dir artifacts/moved
.\.venv\Scripts\python.exe -m hometrace --scenario missing --output-dir artifacts/missing
.\.venv\Scripts\python.exe -m pytest -q
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m hometrace --scenario moved --output-dir artifacts/moved
.venv/bin/python -m hometrace --scenario missing --output-dir artifacts/missing
.venv/bin/python -m pytest -q
```

两个内置 fixture 都使用观察点 A、B、C 与注册目标 `remote-control`：

| 场景 | 测试输入 | 预期行为 |
| --- | --- | --- |
| `moved` | 历史标注在 A；当前 A 未见目标、B 标注目标存在 | 查询历史 → 检查 A → 根据当前未找到的结果重新规划 → 检查 B → 报告 `FOUND` |
| `missing` | 历史标注在 A；当前记录没有可确认的目标，包含遮挡记录 | 检查候选点并保留逐点观测结果 → 最终报告 `UNKNOWN`，不假报 `FOUND` |

**终端中的 Mock navigation 表示模拟运动。** `FOUND` 只表示 fixture 标注规则在本次测试中给出确认，不证明现实物品存在；本阶段没有加载真实图片，也没有连接摄像头或机器人。所有观测均标记 `data_source = fixture`，`image_path` 与 `image_hash` 为 `null`。

每次运行会在 `--output-dir` 下生成 `report.json`（最终报告与证据）、`events.jsonl`（逐步结构化事件）、`memory.sqlite3`（本次记忆快照）。每次任务从 fixture 初始化独立的内存数据库，不复用上次运行的知识；再次指定相同输出目录会覆盖这些同名产物。默认场景为 `moved`，默认输出目录为 `artifacts/demo`。

可用 `--object-id remote-control` 指定已注册目标，用 `--fixture <路径>` 加载符合内置格式的自定义测试 fixture；输入要求、代码结构及验收边界见 [P0 实现与验证说明](docs/P0_IMPLEMENTATION.md)。

已在 Windows / Python 3.11.4 的全新虚拟环境中安装 wheel 并运行验证：[54 项 pytest 通过](docs/evidence/issue-1/pytest.txt)，`moved` 访问 A → B 后返回 `FOUND`、位置 B，`missing` 访问 A → B → C 后返回 `UNKNOWN`。可查看 [sample report JSON](docs/evidence/issue-1/moved/report.json)、[负例报告](docs/evidence/issue-1/missing/report.json) 与 [完整命令和验证记录](docs/evidence/issue-1/validation.json)。macOS / Linux 命令未在本次环境执行。

## 工作方式

- 产品负责人：参赛团队；PM/技术审查：ChatGPT；开发执行：Codex。
- **GitHub 为协作与版本依据**：Issue 写明合同和验收标准；Codex 在任务分支实施，通过 Pull Request 提交；PM 检查源码、测试与证据，再决定是否合并。
- 禁止把模拟运动、离线图片、模型猜测写成真机观测；禁止用成功运行示例替代测试。
- 不在 Issue、提交记录或演示视频中写入私钥、云服务 Token、个人隐私图像或赛事敏感资料。

## 资料导航

- [产品需求](docs/PRODUCT_BRIEF.md)
- [系统架构与接口](docs/ARCHITECTURE.md)
- [初赛演示与验收](docs/DEMO_ACCEPTANCE.md)
- [Codex 协作规范](AGENTS.md)
- [P0 实现与验证说明](docs/P0_IMPLEMENTATION.md)

## 里程碑

1. P0 — 仓库/合同与可执行的假数据闭环
2. P1 — 基于真实采集图片的物品观察与记忆
3. P2 — 历史位置失效后的自主重新规划与演示界面
4. P3 — 测试/录屏/参赛材料（10 月 28 日前）
5. P4 — 如晋级，官方底盘适配与真机验证（11 月 21 日决赛前）

> 机器人型号、RobotClaw 官方 API、摄像头位置、算力、联网限制均待组委会文件核实。系统先定义中立接口，避免提前锁定不存在的能力。
