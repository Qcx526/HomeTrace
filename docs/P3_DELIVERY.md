# P3 初赛材料与候选交付

本阶段基于 PR #7 合并提交 `efaaaffae47ddb577ec9472d03838b66321eb178` 增量实现 Issue #4，不改变 Search Core、生产 ORB 或验证阈值。Word 合同按 [最新 PM 评论](https://github.com/Qcx526/HomeTrace/issues/4#issuecomment-6341286246) 修订：采用团队自编技术说明书，未知官方模板不阻断 candidate 打包。

## 已实现

- `demo_cases.py` 与 DemoService 支持本地物品身份、独立参考图及数据目录；公开 OpenCV 三场景保持稳定。
- 私有案例要求独立历史图片、明确来源与一致时间依据，当前观察晚于历史；每轮冻结后再次核验，历史不冒充当前发现。
- 私图运行输出在 Git 仓库内必须使用被忽略的目录；界面标明私有照片、模拟导航和未确认状态，切换数据集清除旧结果。
- `evaluate_team_photos.py` 对本地数据包检查路径/来源/时间/SHA，并执行生产 ORB 和有限 SIFT/AKAZE 对比；公开结果只保留数字白名单。
- 自编 Word、可编辑 PPT、实际软件录屏 MP4、运行测试报告、开源说明与材料清单已交付，见 [材料](submission/README.md)。
- `build_submission.py` 读取本地配置，检查材料与源码白名单，生成候选 ZIP 后复开检查 CRC/SHA256。团队与平台核验保留人工状态，工具不上传。

## 本地家庭案例

```powershell
# 照片包已经放在 local_data/team_tissue/；不要提交原图。
Copy-Item examples/demo_case.example.json local_data/team_tissue/demo_case.json
.\.venv\Scripts\python.exe -m hometrace demo --port 8765 --output-dir artifacts/team-demo --case-config local_data/team_tissue/demo_case.json
```

可重复 `--case-config` 添加数据集。配置所在目录须包含 `history.json`、`moved.json`、`missing.json` 和可读取图片。`image_root` 只允许配置目录内的子目录；参考图不能等于独立历史图字节。物品 ID 不能沿用 `sample-box`，本次纸巾使用 `tissue-pack`。来源说明和历史说明只作展示，不是检测答案。清单不接收真实标签或目标位置答案。

选择“团队纸巾实拍适配”，运行三个场景。当前实测 moved/missing 均为 SUSPECTED/null，replay 为 UNKNOWN/null；没有家庭 FOUND 或家庭检测框。这个入口展示真实失败边界，不宣称已完成家庭成功寻物。纸巾原图、钥匙、二维码、屏幕等数据和含图报告留在本地，不公开截图。

输入缺失或非法时该本地案例显示不可用，公开回归案例仍可运行。服务只监听 `127.0.0.1`；源码包不包含团队照片。完整照片结果见 [实拍适配记录](TEAM_PHOTO_EVALUATION.md)。

## 实际验证

开发环境完整回归：**226 passed，0 skipped**，包含保持原文件不变的 148 项 P0/P1/P2 回归、19 项 Demo 配置/隐私边界、18 项照片输入与几何测试、41 项打包测试。[证据目录](evidence/issue-4/README.md) 保存实际日志和浏览器结果；测试夹具与真实照片实验分别记录。

公开浏览器验证检查每一步计数、检测框与 bbox 一致、旧图不显示框、JSON 下载一致以及手机无横向溢出。家庭浏览器三场景检查自己的 `tissue-pack` 身份、未确认历史、无最终确认位置、隐藏检测框和切回公开数据集的状态清理；验证脚本不截图或录制私人图片。

Windows 全新虚拟环境使用非 editable wheel 安装；实际结果见同目录安装记录。没有在全新操作系统镜像、Linux、macOS 或嵌入式设备上宣称验证。

## 材料制作与包内边界

```powershell
# 以下是制作依赖；运行 Demo 不需要 Node、Office 或 ffmpeg。
node tools/validate_p2_browser.cjs http://127.0.0.1:8765 artifacts/new-public-recording
python tools/create_demo_video.py --recording-dir artifacts/new-public-recording --output artifacts/new-materials/HomeTrace.mp4
```

浏览器验证需 Playwright 与 Edge；视频制作需 ffmpeg/ffprobe，字幕采用微软雅黑。当前视频长 72.28 秒，包含 51.28 秒实际浏览器录像、中文说明、片头片尾，无音轨；播放节奏不是机器人耗时。录制仅使用公开图像，家庭结果以文字说明呈现。重新录制时应核对字幕分段时间与新视频一致。

DOCX/PPT 的生成脚本、内容来源和可选制作环境见 [材料说明](submission/README.md)。核心源码包用于运行 Demo；材料生成器引用的历史公开截图和制作依赖未全部纳入源码快照，不保证仅凭 ZIP 内源码重新制作全部媒体。

## 剩余人工事项

候选包与上传成功分开记录。负责人仍须本地填写团队身份，打开当届提交作品页面核验格式、命名、大小、必选附件/模板与截止时间，打开材料并解压复核，然后实际上传。PM 尚未审查本 PR，不合并。家庭照片未确认、真实机器人未运行、三个策略对照步数打平，这些边界在所有材料中保持一致。
