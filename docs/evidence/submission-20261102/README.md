# 最终材料工作包验收

11月2日启动、11月3日完成。对应 Issue #4 / #12，基线 PR #47；本次源码包提交为 `e1d1d9147bbc07f2eb57546c26e45e3f2e261c4d`。本目录是打包完成后的证据提交，不在已生成 ZIP 内；产品代码和源快照未因此改变。

## 实际结果

- 新建 Windows venv，从导出源码构建/安装 wheel，pip check 通过，全量1161 passed（191.98秒），28项前端通过（260.1336ms），空工作区HTTP/wheel9项检查通过。
- 最终 ZIP 实际解压后再次全量 **1161 passed（179.77秒）**，一个既有LangChain弃用提示；前端 **28 passed（246.1649ms）**。不是把不同分支数字相加。
- 官方草稿3页、技术书6页逐页检查；PPT12页回读渲染逐页检查；视频161.92秒全片解码及13张抽帧检查。只读Word导出作为缺LibreOffice的明确fallback，无原生PowerPoint操作声明。
- ZIP 6,611,867 bytes、226项；SHA256 `1e222868d77c549c8afeb075cb06e51c5961cb87488fc8cbced4f8a864498e16`。全部CRC/SHA256通过，216份源码文件，旧ZIP哈希不变。
- 正式主表校验因team_name等身份未填写保持BLOCKED；审阅包 `ready_to_submit=false`、`uploaded=false`。平台检查均PENDING，不能上传此工作包。

`pytest.txt` / `frontend.txt`：最终 ZIP 的全量原始输出，仅把本地工作区路径替换为占位符。`clean-venv-*`：先前新环境运行的独立日志。`tests.json`：实际进程退出与测试统计。`clean-install.json`：安装和HTTP检查。`material-qa.json`：文件哈希及逐页检查记录。`privacy-audit.json`：提交前扫描。`archive.json`：ZIP和源码快照。`formal-preflight.json`：身份与平台待办状态。

新环境导出与最终ZIP只差交付报告补充实际测试结果、视频时间轴表述澄清；最终ZIP仍重新完整测试。软件测试不证明识别精度。实拍结果继续引用 PR #47 原脱敏记录，不重新调用模型、不重发图片；本轮无自动FOUND、无私图、无Key或数据库公开上传。

媒体原件、DOCX、PPTX和ZIP只留本机Git ignored目录。官方原始空模板、规则PDF、私人配置不在包内。团队身份由负责人填写，PM审查依赖链后再核对平台和生成正式候选；本轮没有合并或提交比赛。
