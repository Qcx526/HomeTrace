# 11月3日：实拍水杯演示视频修订

对应 Issue #4 / #12、PR #48。仍基于 PR #47 的未合并开发链；不改识别、Agent 或 SQLite，不覆盖11月2日的实验与材料，不自行合并。

## 本轮改了什么

此前视频主要播放合成钥匙的软件录屏，实拍水杯只出现在文字摘要中，无法直观看到真正的家庭寻物过程。本轮将整片替换为水杯任务回看：登记参考 → 历史地点 → 转查另一地点 → 请求近景 → 主人核对 → 保存 → 重启查询 → 旧图保护。

新片直接展示负责人提供的参考照片与三张实拍场景。口号和重复技术提示改为简短中文步骤；旧合成钥匙素材不再出现在新片中，因此无需在新片上标注该素材。软件测试和历史视频的原始来源记录保留，未将生成图片改称实拍。

**这是冻结真实任务的只读回看页面及浏览器截图剪辑，不是当天重新运行 Agent 的连续录像，也不是生产页面的新交互录像。** 右上持续标明执行日期与“真实任务回看”；保留“模拟导航、主人确认”。章节切换只切换已保存的快照，不执行工具或写数据库。解说是人工编辑摘要，不冒充模型原话。

## 证据与实现

- 真实执行依据：[五张新实拍验收](REAL_CUP_FRESH_WORKFLOW_20261102.md) 和其冻结脱敏 JSON。实际主流程、补拍、主人授权保存、新进程查询、旧图拒绝均来自此前运行；本轮没有新增模型调用或图片外发。
- `tools/create_task_review.py` 核对原图 SHA256、已审核参考、状态版本、已观察照片、保存事件与重启事件字段一致性。仅导出选定展示字段，默认要求输出被 Git 忽略，拒绝覆盖、路径逃逸和场景身份覆盖；页面禁止网络连接，无写入接口。
- `tools/encode_task_review.py` 将人工检查过的浏览器截图按明确时间线编码，记录逐帧哈希及媒体来源，拒绝覆盖旧视频。
- `tools/create_delivery_document.py` 同步视频来源描述；官方主表、12页PPT沿用已验收版本，技术补充仍为6页。团队身份按负责人要求留空。
- 私人原图、具体物品/位置绑定、回看 HTML、截图、视频和ZIP仅存本机忽略目录。屏幕、二维码、笔记在展示层遮挡，原始照片和模型输入记录字节不变。没有给无框结果人工添加检测框。

## 实际视频与检查

本机新目录：`local_data/submission/20261103-cup-video/`。新片80.00秒，1920×1080，H.264，中文字幕，无音轨；完整解码通过，8个章节的编码后抽帧均已逐张检查。视频 SHA256：`04b7b8c96a0c152997daba63fbcd62d645b36a36a27364061a8621b3d79a6e20`。

新技术书 SHA256：`f734b24a3484fa0762afca8f1c32b93711d07bcdf335ea2a321f4dcea443b8ef`。标准渲染器缺少LibreOffice，保留失败日志；使用本机Word16只读导出PDF和bundled Poppler，逐页检查6页，渲染未改写DOCX。

本轮同一次联合全量为 **1214 passed，193.92秒**，一个既有LangChain弃用提示；前端 **28 passed，318.9463ms**。新增53项导出/编码边界测试先单独运行通过，再包含于联合全量实际运行，不是把分支数量相加。日志见 `docs/evidence/cup-video-20261103/`。软件测试只证明导出与拒绝错误输入等行为，不证明视觉精度。旧报告/旧ZIP不变。

## 复现命令

输入文件含私人信息，不随公开仓库分发；以下路径为本地批次内的文件名约定。

```powershell
python tools/create_task_review.py --summary <私有运行摘要.json> --plan <私有图片计划.json> --story <本地章节说明.json> --output artifacts/cup-review-new
# 仅在127.0.0.1提供回看目录；浏览器逐章检查后保存01.png至08.png。
python tools/encode_task_review.py --frames <截图目录> --review artifacts/cup-review-new/review.private.json --output <新视频.mp4> --durations 8 10 10 12 12 10 10 8
python -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
python tools/build_review_bundle.py --config local_data/submission/20261103-cup-video/config.json --output-subdir 20261103-cup-video
git diff --check
```

## 保留的限制

本轮只修改展示与材料，未提高识别能力。旧记录中本地ORB仍无可靠框，外观意见不是实例身份确认；保存为`USER_CONFIRMED / owner_reported`。只有单水杯的受限主人协作流程完成，自动定位、独立真实测试、家庭通用识别、真机运动和普遍效率提升均未获验证。负例、预算失败和耗时保留在原实验报告，不因精简视频而抹去。

新版ZIP仍是 `REVIEW_ONLY_NOT_FOR_UPLOAD`。正式主表身份、PM审查及报名平台要求仍须负责人完成；尚未上传比赛，也没有提交回执。
