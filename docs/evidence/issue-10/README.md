# Issue #10 验收证据

2026-10-24，基线 `e5732b4024d90cc190aedb77f98f626b11e982cd`。实际 GPU 实验通过执行检查，生产接入结论 **NO_GO**。本目录不含私人图片、图像路径、图像 SHA256、原始框或权重。

- [报告](../../P4_VISION_EVALUATION.md)：方法、逐类结果、失败解释、许可和复现命令。
- [protocol.json](protocol.json)：推理前冻结的模型、参数、权重来源和门槛。
- [environment.json](environment.json)、[neural-freeze.txt](neural-freeze.txt)：实际独立环境和设备。
- [smoke.json](smoke.json)：官方 Visual Prompt 实际调用；重复空木纹场景不计作新增样本。
- [summary.json](summary.json)：全部 20 个场景的脱敏模型输出，人工类别在推理后加入。
- [localization-review.json](localization-review.json)：候选图人工复核，非额外检测器或人工真值框。6 正例仅 1 个目标候选得到支持；8 负例出现 1 个相似实例误候选。
- [pytest.txt](pytest.txt)：`.venv/Scripts/python.exe -X utf8 -m pytest -q --junitxml artifacts/issue-10/pytest.xml` 实际输出，**312 passed in 71.04s**。包含原有 289 项与 23 项新增离线边界测试；自动化数量不是视觉准确率。
- [validation.json](validation.json)：基线文件未修改校验、证据一致性与源码 SHA256。

完整框、叠加图、模型请求与进程输出仅保留在 Git ignored 的 `artifacts/issue-10/evaluation-01/`。24 张输入均在实验前后通过 SHA256、字节数与尺寸校验。没有导航、真机或 LLM 运行声明，没有修改旧实验报告。单元测试 stub 仅验证输入、隔离、超时、候选边界及脱敏；模型结果来自真实 GTX 1660 推理。
