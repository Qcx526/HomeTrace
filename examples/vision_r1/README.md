# 多参考实验输入示例

这两份 JSON 仅是字段示例，不包含真实登记、可运行图片或测试结论。示例 SHA256 故意无效，review 默认为 false/pending，必须用真实文件哈希、负责人确认的固定 ROI 和元数据替换；不能直接改成 true 以越过审查。把填写后的文件放到 ignored 的 `local_data/`，不要提交照片、个人信息或原图哈希。规则见 `docs/VISION_R1_PROTOCOL.md`。

使用已安装 vision 可选依赖的环境，PowerShell 从仓库根目录运行：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python tools/evaluate_vision_r1.py --data-root local_data/your_registration --manifest local_data/your_registration/manifest.private.json --labels local_data/your_registration/labels.private.json --output-dir artifacts/vision-r1-your-run
```

每次使用新的输出目录；工具拒绝覆盖已有输出。退出码 0 仅表示实验完成，不表示识别成功。先检查 `summary.public.json` 中每个方法的数据来源、未执行数、定位审查缺失和 BLOCKED 状态。`predictions.private.json` 保存原图框及逐参考证据，`registration.private.json` 保存登记质量，`binding.private.json` 保存输入和输出哈希，均留本地。

多个 objects 会互为 rival controls；不要求它们共享参考数量，但每个配置的 rival 至少需一张合格且审查完整的参考。没有配置 rival 时，接受结果标记 `rival_coverage=not_configured`，不能声称已排除相似实例。所有接受框来自实际单参考几何核验，未合成、未注入人工场景框。多参考使用同一表面的交叉支持，是保守假设，不是任何场景都能工作的算法。

现有 24 张历史照片可以使用 `tools/prepare_vision_r1_diagnostic.py` 生成单参考输入。该适配器保持未知视角、背景及表面元数据，不把历史场景转换成新参考。真实多参考效果须等待负责人补充登记照片。
