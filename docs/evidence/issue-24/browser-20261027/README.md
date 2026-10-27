# Issue #24 浏览器补验收（2026-10-27）

在源码提交 `f99ebefbdf74f85ddcfb08d1ae5d0972935168e0` 上实际操作内置浏览器，补齐初次因工具禁用而缺失的页面验收。所有名字、地点和陈述都是本次软件测试输入；没有使用私人照片、真实家庭位置、语言模型或机器人。此目录是追加证据，原 pytest、HTTP、wheel 和浏览器阻塞记录未覆盖。

## 实际执行与结果

服务使用已有 Agent 测试环境启动，本页不用模型：

```powershell
& artifacts/issue-11/agent-env/Scripts/python.exe -u -m hometrace demo --port 8784 --output-dir artifacts/issue-24/browser-20261027-01/photo-runs --household-dir artifacts/issue-24/browser-20261027-01/home
# 打开 http://127.0.0.1:8784/household.html
# 复现时请换新的工作区目录；测试重启时复用该目录。
```

通过真实页面控件完成登记、选择、确认、取消和查询；截图不是构想图。共保存 14 份原始 DOM 快照，公开其中 5 张原始截图，其余图片保存在 ignored 实验目录。逐项结果与最终数据库只读摘要见 [browser-checks.json](browser-checks.json)，文件完整性见 [artifact-hashes.json](artifact-hashes.json)。页面检查不计入 pytest 测试数量。

| 检查 | 实际结果 | 直接证据 |
| --- | --- | --- |
| 名称与同名选择 | 两件钥匙共用“我的钥匙”，先澄清，再显式选择蓝色钥匙 | [01](01-clarify.txt) |
| 刷新恢复 | `cd377659`、版本 2、待确认目标及玄关位置保留 | [02 快照](02-reload-pending.txt)、[截图](02-reload-pending.jpg) |
| 服务重启恢复 | 停止服务 1、服务 2 使用同目录；恢复同一待确认会话 | [03](03-server-restart-pending.txt)、[服务 1 请求](server-1.err)、[服务 2 请求](server-2.err) |
| 确认写入 | 版本 3 完成，玄关位置历史一条 | [04](04-confirmed.txt) |
| 多页面旧版本冲突 | 第二页面取消旧版本收到实际 HTTP 409，提示已更新，恢复已完成状态 | [05 截图](05-conflict.jpg)、[快照](05-conflict.txt)、[请求日志](server-2.err) |
| 取消无新增 | 取消蓝色钥匙的新位置后，历史仍为一条 | [06](06-cancelled.txt)、[07](07-cancel-history.txt) |
| 未知物品登记后续接 | 未知水杯 → 登记 `demo-cup` → 重试原 `412bc391` 会话，保留客厅位置 | [08](08-unknown.txt)、[09 截图](09-unknown-resumed.jpg) |
| 取消水杯 | 后续查询水杯历史为零 | [10](10-cup-empty.txt) |
| 历史排序 | 蓝色钥匙确认第二条后，书房桌面 → 玄关托盘 | [11](11-latest-history.txt) |
| 实例隔离 | 红色钥匙历史为零，不串入蓝色钥匙陈述 | [12](12-other-instance-empty.txt) |
| 完成态刷新 | 重新查询并刷新，仍显示同一已完成查询和两条历史 | [13 截图](13-final-history.jpg)、[快照](13-final-history.txt) |
| 窄屏布局 | 实际截图宽 375 px，卡片和控件未见重叠，页面未见横向溢出；没有手机实机测试 | [14 截图](14-mobile-layout.jpg)、[快照](14-mobile-layout.txt) |

最后用 SQLite `mode=ro` 读取本次演示库：3 件登记物品、8 个持久交互会话；蓝色钥匙 2 条位置陈述，红色钥匙和水杯各 0 条。两条事件均为 `owner_reported`，`visual_confirmed=0`，没有 FOUND。数据库文件不提交。

## 过程问题、验证边界和当前结论

- 首次访问 `/favicon.ico` 为 404；页面资源加载和主流程正常。本轮没有改源码处理这一非阻塞问题。
- 续接工作期间服务曾不可用，使用第三个服务进程及同一目录恢复后继续测试，数据未丢失。服务 3 的重定向日志为空，未把它作为逐请求证据；其结果由快照、截图与最终数据库摘要支持。保留前两个进程的原始请求日志，只替换本机工作区路径前缀。
- 刷新后上方“新请求”表单恢复默认值，下方已保存会话正确恢复。未声称保存未提交的表单草稿。
- 窄屏检查请求 viewport 为 390×844，DOM 读数 clientWidth/scrollWidth 均为 390；工具保存的全页 JPEG 为 375×3261。两者尺寸不一致，分别记录，不将截图像素宽度称为设备分辨率。
- [控制台记录](console-handoff.json) 是最后重新打开页面时的 warn/error 查询结果 `[]`，不代表所有历史标签页均无控制台消息。
- 没有执行禁用 localStorage、跨浏览器、手机实机和浏览器自填时间分支。这些未执行项不记为通过。
- 原一次完整回归为 **630 passed、0 failed、0 skipped、1 warning，97.32s**。本次只修订说明并追加证据，源码与测试未变，没有重新跑 pytest，也没有把 13 项浏览器检查加成 643 项自动化测试。

Issue #24 的本地记忆交互主流程已具备审查证据，PR #25 仍待负责人审查，依赖分支仍未合并。**家庭实例识别仍 BLOCKED**：名称登记不是照片登记，历史查询不是主动扫描，本工作区与现有照片 Agent 尚未贯通。下一步是私有参考照片登记及人工确认，再展示共享模型候选与 UNKNOWN；不能用主人陈述或相似度代替可信实例确认。本次未更新正式参赛材料。
