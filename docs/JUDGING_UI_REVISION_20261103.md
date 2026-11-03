# 图文报告与实际网页演示修订

对应 Issue #4 / #12，继续提交到 PR #48，不合并。依赖 PR #47 的实拍工作流。此前实验、材料、录屏和候选包均保留。

## 本轮内容

负责人要求报告增加图片，视频展示实际 HTML 操作，并将语音输入与具身机器人全屋搜索列为后续方向。本轮没有修改生产识别器、搜索判断、Agent、数据库结构或生产网页。

- 报告保留官方首表，论文正文增加4幅图：钥匙实际候选核对页面、水杯完整远景、同地点近景、重启后的历史查询界面。共18页、7张正文表。图片有编号、标题、来源与结果说明；没有将相似建议画成检测框。
- PPT继续采用负责人提供的学校蓝色模板，共12页。更新后续方向：语音输入与歧义确认；接入建图、定位、避障导航、相机和真实到达回执后，再验证全屋搜索。
- 视频约175.6秒，1440×1200、H.264、中文字幕、无音轨。前75.92秒为既有钥匙完整浏览器操作录像，随后是在实际生产HTML中查看已完成水杯任务。全片使用浏览器画面，原速保留，不使用幻灯片替代操作。钥匙使用合成软件样例；水杯为实拍任务回看，不是本轮新推理。
- 按负责人最新要求，工位画面保留原貌，不打码。照片和正式媒体只保存在Git忽略目录，不公开推送。

语音识别、实时全屋建图与机器人运动均未在当前版本实现或验收。软件提供记忆和决策基础，机器人接入仍需硬件适配与家庭环境测试，不表述为接上设备即具备人类水平。

## 网页录屏与证据

`tools/serve_saved_demo.py` 通过 SQLite 只读连接，核对完成任务与冻结记录一致后，复用原有HTML、JS、CSS和GET路由。写请求返回405，未构造模型客户端。`tools/record_saved_cup_demo.cjs` 实际选择登记物品、滚动观察与工具轨迹、打开历史和旧图拒绝记录，并检查所有浏览器请求只访问本地GET、数据库哈希未改变。

水杯录屏15个章节、10项核验通过；无浏览器错误，无新增模型调用、图片外发或位置写入。确认来源仍是此前负责人的明确授权，本轮没有重演确认点击。最初一轮录制因比较JSON字段顺序而停止，改为对象深度比较后通过，未影响数据库；先完成的遮挡版按负责人后续指令另录原貌版，旧文件保留。

`tools/create_ui_demo_video.py` 拼接两段真实浏览器录屏并加字幕，保留输入哈希与章节时刻。完整解码通过，28个章节代表帧均检查。原貌视频的SHA256在本轮媒体证据中记录。

## 文档与打包保护

图文报告允许新增内部PNG/JPEG图片，但保留官方首表、原有关系及不透明部分。新增媒体必须采用内容哈希命名且被正文引用；拒绝外部图片关系、路径逃逸、任意额外文件、未引用图片、篡改字节及原关系变化。图片还需通过完整解码，损坏PNG/JPEG不能仅凭有效头部通过校验。原官方表填充器未放宽。

标准DOCX渲染器因缺少LibreOffice不能执行，保留错误日志；使用本机Word16只读导出PDF和bundled Poppler检查18页，导出前后DOCX哈希一致。新图页、修改页逐页检查，其余页面与此前已检查渲染逐像素一致。PPT12页回读渲染完成，11页与之前逐像素相同，修改的后续方向页单独检查。

## 实际测试

```powershell
python -m pytest -q
node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs
```

同一次全量结果为 **1286 passed，1项既有依赖弃用提示，205.96秒**。前端联合 **28 passed，306.7927ms**。新增24项测试验证只读HTTP/SQLite、冻结记录不一致拒绝及DOCX图片包边界。测试数不作为识别精度，也没有与其他分支相加。

最终仍只有四项：报告DOCX、展示PPTX、视频MP4、相关代码ZIP。运行与测试说明、开源说明放进代码ZIP。源码白名单只新增本轮文档和脱敏记录，排除照片、身份信息、密钥、数据库及权重。候选包仍需要负责人核对赛事平台要求并上传；本轮不自动上传、不合并PR，不宣称家庭通用自动识别通过。

## 可复现命令

所有私有输入按本机实际目录传入；不向公共仓库提供真实任务库或照片。

```powershell
python tools/serve_saved_demo.py --workspace <本机已完成任务工作区> --summary <冻结结果JSON> --port 8788
node tools/record_saved_cup_demo.cjs <私有plan> <私有summary> artifacts/new-recording <Python路径>
python tools/create_ui_demo_video.py --keys <钥匙录像目录> --cup <只读录屏目录> --output <新MP4路径> --work artifacts/new-edit
python tools/create_judging_report.py --config <私有团队JSON> --template <官方原表> --figures <私有图片目录> --output <新DOCX路径> --qa-dir artifacts/new-report
python tools/build_four_file_submission.py --config local_data/submission/20261103-ui-demo/four.private.json --output-subdir my-new-ui-candidate
```
