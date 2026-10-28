# Issue #26 前端复核补充

2026-10-28，补充于 `b7ccde2` 的完整软件闭环验证之后。原全量测试、HTTP、浏览器、图像实验和审计文件保持不变，本报告不改写其结论。

## 缺陷与修复

1. 旧任务 A 的轮询请求悬置，用户取消 A 并创建 B 后，迟到的 A 响应会覆盖页面和 localStorage 中的 B。现在每次用户操作递增操作代次，轮询只接收当前任务、当前代次且版本不倒退的响应；失效请求的错误也不会覆盖新任务提示。
2. 已上传参考图 A 并勾选 ROI 确认，随后替换图 B 上传失败时，旧引用和确认可能保留，允许误存 A。现在开始替换即清空旧引用和确认，上传失败显示明确提示，保存按钮保持禁用。

只调整页面的异步状态管理，不改变视觉算法、阈值、导航、服务端接口、记忆或 FOUND 规则。

## 验证方法

`tests/test_photo_flow_client.cjs` 执行完整生产 JavaScript，以 Node 内置测试器、DOM 和网络 double 控制请求完成顺序，验证用户提交/取消/上传的实际事件处理器。该软件测试不是浏览器操作、照片检测或机器人运行证据，不依赖 Git 历史和第三方前端测试包。

```powershell
node --test tests/test_photo_flow_client.cjs
node --check src/hometrace/web/home-flow.js
```

本地保留 `artifacts/issue-26/audit-followup/client-regression.cjs` 的修复前后对照：同一测试在 `b7ccde2` 复现两个缺陷，修复后均不再发生。新的公开运行结果见本目录 `ui-followup/`。Python 738 项全量结果仍对应原报告；新增 JavaScript 测试单列，不将不同测试套件数量相加。后端没有追加代码修改。

- [JavaScript 实跑日志](ui-followup/client-tests.txt)：4 passed，0 failed，0 skipped，105.8469 ms；语法检查退出码 0。
- [缺陷修复前后输出](ui-followup/before-after.json)：修复前两项 `correct=false`，修复后两项 `correct=true`。
- 额外后端复核：`.venv/Scripts/python.exe -m pytest tests/test_photo_flow_service.py tests/test_photo_engine.py tests/test_photo_flow_http.py tests/test_photo_core_contract.py -q` → 108 passed in 12.23s（工具运行记录，未另存原始日志；不是新的全量结果）。
- [源码、隐私和服务审计](ui-followup/audit.json)、[新 wheel 构建日志](ui-followup/wheel-build.txt)。

重新构建 wheel 并核对其中 JavaScript 字节与当前源码一致。旧 wheel 的哈希与构建日志保持为历史记录。没有声称进行了新的 Windows 全新环境安装。

本次追加复核期间浏览器工具再次返回 `Local browser use is disabled in Work settings`，因此没有把 Node 软件测试写成新增浏览器验收。此前实际浏览器操作及截图仍保留，适用范围见原证据。HTTP 静态资源检查确认演示服务提供修复后的脚本。

## 能力与审查边界

新工作区保留给用户首次搜索，检查过程不消耗其图像证据。AI 合成图、模拟导航、实际 ORB 候选与主人确认保持分别标识。真实家庭实例识别仍为 BLOCKED；本修复不提供新的照片识别能力证据。提交到同一 PR #27，继续等待审查，不合并。
