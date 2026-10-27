# Issue #22：真实实验与回归证据

本轮是共享冻结视觉模型与独立记忆原型，不是生产识别接入，也不是完整会话Demo。

- [完整中文实验报告](../../VISION_R3_SHARED_MEMORY_20261027.md)
- [预设实验协议](../../VISION_R3_PROTOCOL.md)
- [实际环境、模型版本与权重hash](environment.public.json)
- [36次最终全图推理完成记录](completion.public.json)
- [相同输入重现核对](reproduction.json)：设置路径修复前后36条预测、特征和检索结果完全一致，总72次调用，仍18张物理照片。
- [完整分组指标](metrics.public.json)：参考排除后15张开发图，10正5负；640检索TP/FP/FN=3/0/7，960=4/0/6。没有独立测试，有限正例的100% precision不能当成物理实例验收。
- [完整联合测试](pytest.txt)：576项通过，无失败或跳过；原499项保留。
- [源码、历史与隐私审计](audit.json)
- [跨进程主人陈述记忆演示](memory-demo.public.json)：5个独立进程。输入是软件演示陈述，不是团队物品的真实移动记录，不代表视觉识别。

正确的全量测试环境是既有 `artifacts/issue-11/agent-env/Scripts/python.exe`。首次误用精简`.venv`执行458项通过、7项跳过；随后神经网络推理环境未安装产品/Agent依赖，收集产生20个导入错误。这些日志分别保留私有`pytest-full-01.txt`与`pytest-full-02.txt`，不作为全量通过。切换既有完整环境后全量通过，设置路径修复后再次完整验证，最终以本目录日志为准。未为通过测试修改任何旧断言。

运行目录 `artifacts/vision-r3-shared/` 为Git ignored：原始预测/特征/逐图框与评分、全部含图页面、模型源码及权重、私有登记清单、独立SQLite与旧实验hash快照。公开证据不包含照片、GT框、图像hash、外观向量、私人身份字段或API Key。

没有修改生产ImageMatcher/SearchCore/Agent/SQLite schema，也没有把OWNER_REPORTED或APPEARANCE_SUPPORTED映射为FOUND。YOLOE与既有R2的NO_GO不变。真实导航、实时采图、在线LLM登记、多轮会话与新媒体均未在本PR执行。
