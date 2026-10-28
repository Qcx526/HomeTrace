# 历史实现与实验索引

当前运行入口、安装和能力边界以 [README](../README.md) 与 [交付 Demo](DELIVERABLE_DEMO.md) 为准。本页只组织已有记录，不覆盖旧结论；旧文档中的日期、入口、测试数量和材料状态均属于其记录阶段。

| 阶段 | 保留依据 |
| --- | --- |
| P0 固定数据闭环 | [实现](P0_IMPLEMENTATION.md)、`docs/evidence/issue-1/` |
| P1 图片与跨运行记忆 | [实现](P1_IMPLEMENTATION.md)、`docs/evidence/issue-2/` |
| P2 经典三场景网页 | [说明](P2_DEMO.md)、`docs/evidence/issue-3/` |
| P3 材料与打包 | [说明](P3_DELIVERY.md)、[打包工具](SUBMISSION_TOOL.md)；旧媒体不代表当前交付 |
| ROI 与传统视觉失败 | [实拍报告](TEAM_PHOTO_EVALUATION.md)、[ROI 对照](REGISTRATION_ROI_EVALUATION.md) |
| 神经网络与视觉探索 | [P4 视觉](P4_VISION_EVALUATION.md)、[共享模型 R3](VISION_R3_SHARED_MEMORY_20261027.md) |
| 原 Agent 与文字工作区 | [P4 Agent](P4_AGENT.md)、[文字工作区](HOUSEHOLD_WORKSPACE.md) |
| 当前照片工作区与 LLM | [照片流程](HOUSEHOLD_PHOTO_FLOW.md)、[LLM 接入](HOUSEHOLD_PHOTO_AGENT.md) |

旧静态页面原样移到 `tests/fixtures/legacy_web/`，Git blob 与基线一致（工作树行尾遵循 Git 配置）。需要复现历史页面时，从源码根目录显式运行：

```powershell
python -m hometrace demo --legacy-web-dir tests/fixtures/legacy_web --port 8765
# 原 /agent.html 需要再加 --agent 及本机配置。
```

默认启动不加载旧页面；源码包保留测试夹具以便回归，安装 wheel 仅携带当前 `home-flow` 资源。旧 CLI 和核心接口继续保留，避免为整理界面破坏历史可复现性。

官方 DOCX 已由负责人提供。旧 `SUBMISSION_PLAN.md`、`SUBMISSION_READINESS.md` 中“未知模板/自编替代”的口径不得作为当前提交要求；当前后续交付需沿用官方表格，技术说明书仅补充。正式材料更新属于后续任务，不因本页索引完成而视为已经完成。
