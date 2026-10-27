# Issue #24 实际验证记录

对应 `feature/24-household-workspace`，基线 PR #23 / `1aa8526ab354113db0a67d9c74088a666dcfdef0`。本轮数据只有虚构的物品名称、地点和用户陈述；不是机器人观察或真实照片识别结果。

## 实际输出

- [最终全量 pytest](pytest.txt)：**630 passed, 1 warning in 97.32s**，0 失败、0 跳过。此前完整运行同为 630 passed / 101.56s，未合并计数。警告为已有 LangGraph 后续默认值弃用预告。
- [源码环境 HTTP 摘要](http-summary.json) / [20 次逐请求响应](http-requests.json)：两个真实 CLI 服务进程，跨进程恢复待确认、确认/取消/重试/历史排序。
- [全新 wheel 环境 HTTP 摘要](wheel-http-summary.json) / [逐请求响应](wheel-http-requests.json)：无运行时第三方依赖安装，两个真实进程再次通过同一验收。
- [wheel 构建](wheel-build.txt)、[安装日志](wheel-install.txt)、[环境与源码哈希](validation.json)。版本仍为 `0.4.1`，这是本分支构建产物，不是新增发布版本。wheel SHA256：`779e5027d634c44f646f13e673534f8443bd0bb5725d9950aa8c422b7334d126`。
- JavaScript `node --check` 退出码 0。HTTP 读取三个资源均 200；**未执行浏览器 UI**，原因是工具返回 `Local browser use is disabled in Work settings`。没有截图，也没有将 HTTP 验证写成页面操作成功。
- 基线已有 284 个 docs/tests 文件的 Git blob（按 checkout 换行过滤）一致；冻结报告及原回归测试未改写。生产 SearchCore、视觉和 Agent 逻辑未改动。

## 复现命令

以下命令在仓库根目录执行。示例复现输出目录必须不存在，避免覆盖本轮证据。

```powershell
$testPy = 'artifacts/issue-11/agent-env/Scripts/python.exe'
& $testPy -X utf8 -m pytest -q --junitxml=artifacts/issue-24/pytest-reproduce.xml
& $testPy -X utf8 tools/validate_household_workspace.py --output-dir artifacts/issue-24/http-reproduce
& 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' --check src/hometrace/web/household.js
& $testPy -m pip wheel --no-deps . --wheel-dir artifacts/issue-24/wheel-reproduce
& $testPy -m venv artifacts/issue-24/clean-reproduce
& artifacts/issue-24/clean-reproduce/Scripts/python.exe -m pip install --no-deps artifacts/issue-24/wheel-reproduce/hometrace-0.4.1-py3-none-any.whl
& artifacts/issue-24/clean-reproduce/Scripts/python.exe -X utf8 tools/validate_household_workspace.py --output-dir artifacts/issue-24/clean-http-reproduce
git diff --check
```

原实际目录为 `http-lifecycle-01`、`wheel-final`、`wheel-env`、`wheel-http-final`；日志、原始 JUnit、进程日志、SQLite 均保存在 ignored 的 `artifacts/issue-24/`。公开日志仅替换工作区和用户目录前缀，结果和耗时保持原输出。

全量测试环境安装了原 Agent/vision/test 依赖；全新 wheel 环境仅安装 hometrace（pip、setuptools 为 venv 引导工具）。后者验证本次标准库记忆工作区及资源打包，不声称全新环境运行所有 Agent 或照片推理依赖。

首次 `pip wheel --no-build-isolation` 因旧测试环境缺少 `bdist_wheel` 失败；保留本地失败日志。改用项目标准隔离构建后成功，没有升级现有模型/CUDA/Agent 环境。

## 验收结论

记忆接口与原子确认可供审查；浏览器交互/布局验收仍 **BLOCKED**，Issue #24 尚不关闭。家庭照片实例识别仍 **BLOCKED**。这些软件验证不证明钥匙/水杯外观已登记，不证明实时定位、LLM 操作或机器人找到了物品。完整范围及人工页面核验步骤见 [工作区说明](../../HOUSEHOLD_WORKSPACE.md)。
