# 公开实拍图片 Demo 输入

这些文件用于 Issue #2 的离线图像匹配验证。图片来自 OpenCV 官方仓库公开的实拍样例，原始字节未经 HomeTrace 裁剪、合成或生成。它们不是团队在家庭现场拍摄的图片，也不是机器人运行数据。

## 来源与许可

- 固定上游：[OpenCV 4.12.0，commit `49486f61fb25722cbcf586b7f4320921d46fb38e`](https://github.com/opencv/opencv/tree/49486f61fb25722cbcf586b7f4320921d46fb38e/samples/data)。
- 每个文件的原始 URL、SHA256、字节数和角色均记录在 [sources.json](sources.json)，五张图片合计 357,388 字节。
- 上游以 [Apache-2.0 LICENSE](https://github.com/opencv/opencv/blob/49486f61fb25722cbcf586b7f4320921d46fb38e/LICENSE) 分发；当前样例目录没有另设图片许可证。随文件保留原始 [LICENSE](LICENSE.opencv.txt)、[COPYRIGHT](COPYRIGHT.opencv.txt) 和 [历史 BSD 许可告知](LICENSE_CHANGE_NOTICE.opencv.txt)。图中的包装商标仅作为视觉匹配对象，不表示其品牌为本项目背书。
- 原摄影者和拍摄日期在该上游元数据中未给出，因此均记录为未知。不要把 Demo 顺序时间当作真实拍摄时间。

| 文件 | 可人工核对的内容 | Demo 角色 |
| --- | --- | --- |
| [box.png](box.png) | 带纹理与文字的饼干包装盒正面 | 注册参考图；也作为人为安排在 A 的历史图 |
| [box_in_scene.png](box_in_scene.png) | 杂物场景中同一包装外观 | 新场景正例，安排在 B |
| [apple.jpg](apple.jpg) | 苹果静物 | 不含目标包装盒的负例 |
| [orange.jpg](orange.jpg) | 橙子静物 | 不含目标包装盒的负例 |
| [fruits.jpg](fruits.jpg) | 水果静物 | 不含目标包装盒的负例 |

这些人工核对结论用于评价测试结果；搜索输入 JSON 不含答案或检测标注，检测器必须读取图像像素并执行特征匹配。图片均已检查，没有家庭隐私原图、个人身份证件或可识别的人像。

## 场景的真实与模拟部分

[history.json](history.json) 把参考照片安排为历史 A 证据；这与参考图是同一张图，不算独立视角的成功识别。真正的跨图正例为 [moved.json](moved.json) 中的 B：它使用不同字节、不同视角和场景的 `box_in_scene.png`。

[moved.json](moved.json) 应先依据历史访问 A，未获得确认后访问 B；[missing.json](missing.json) 则用三张不含目标的实拍图片检验不误报。匹配失败只能说明未取得可靠实例匹配，因此通常输出 UNKNOWN，不能推出目标在整个房间不存在。

地点 A/B/C、图像编排和时间戳是 **Demo 场景编排**，不代表上游拍摄了一个真实的 A→B 搬移实验。清单统一使用 `timestamp_basis = demo_sequence`、`data_source = recorded_image`、`navigation_mode = simulated_navigation`，并在 `capture_source` 写明来源与未知真实日期。此证据能验证公开图片上的像素匹配与软件流程；团队家庭场景、低纹理物品和真机仍待实测。

分别验证 moved 与 missing 时，应为每个场景创建独立数据库并登记历史，再在第二个进程搜索。这样负例会实际进行匹配，不会仅被上一场景已读取图片的防重放检查拦截。若故意用同一数据库重放，则应把重复图片拒绝结果作为防重放测试，不能当作一次新拍摄。

完整运行命令及保存的实际结果见 [项目 README](../../README.md)。

## 替换为团队自行拍摄的图片

1. 先选有稳定纹理、文字或图案的平面物体正面，例如包装盒或书封；纯色、反光、明显形变或外观完全相同的多个物品不适合此方案。
2. 拍参考图，尽量让目标清晰、完整并占据主要画面；另外拍一张目标在 A 的历史照片。历史图与参考图可不同，更能反映实际用途。
3. 移动物品后，重新拍 A、B、C 的当前场景。另拍不含目标、遮挡、模糊的负例，记录实际发生的时间。不要把同一张照片换名后当作新观察。
4. 把照片和 JSON 清单放在本地独立目录，使用相对路径。为每帧填写唯一证据 ID、观察点、带时区的 ISO 时间、可见性。使用 `timestamp_basis = declared_capture`；`capture_source` 说明团队自主拍摄。这里是操作者声明，系统不会声称其已被硬件或 EXIF 认证。
5. `clear` 表示操作者声明图像可用，不是目标存在标签；遮挡或无法观察应分别标记 `occluded` / `unobservable`。清单不能出现 detections、FOUND 或答案字段。
6. 涉及家庭隐私的照片和数据库只放本地，不加入 Git。公开 PR 仅提交经授权可公开的原始图片、来源与结果；必要时在拍摄前重新布景，避免把遮挡隐私后的合成图冒充原始实拍。

当前例子使用原始文件的 SHA256；系统防重放可识别相同字节，无法证明用户重新编码、裁切后的图像是新拍摄。报告必须保留这一边界。
