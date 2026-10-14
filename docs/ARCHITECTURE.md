# HomeTrace 架构合同 v0.1

## 分层
1. UI/CLI 与 RobotClaw 抽象：用户任务、工具调用、状态显示。
2. Search Core：状态机、位置记忆、候选地点打分、结果确认。
3. Perception：输入有出处的真实图片，输出候选物品观测；初期可提供人工标注测试适配器。
4. EnvironmentAdapter：MockAdapter（初赛）与待开发 RealRobotAdapter（决赛），使用同一接口。

## 关键接口（设计合同，非官方 RobotClaw API）
- register_object(object_id, sample_image_path, description)
- query_memory(object_id) -> observations[]
- list_viewpoints() -> viewpoints[]
- navigate_to(viewpoint_id) -> NavigationResult
- observe(viewpoint_id) -> Observation{image_path, timestamp, viewpoint_id, adapter_kind}
- detect_target(observation, object_id) -> DetectionResult
- update_memory(observation, detection) -> MemoryUpdate
- plan_next(task_state) -> PlanDecision
- build_report(task_id) -> SearchReport

## 实证与模拟边界
MockAdapter 返回模拟导航状态；图像可来自真实拍摄的数据集，但必须保留 data_source = recorded_image。真机观察需独立标记 real_robot，且不能由上层手动伪造。
历史位置不是当前确认。未检测到不意味着物品不存在；未覆盖、低清晰度或遮挡时报告 UNKNOWN。不能把同一图像重复输入算作独立复核。

## 数据对象建议
Observation: id, object_id?, viewpoint_id, captured_at, image_path, image_hash, data_source, visibility_status。
DetectionResult: target_id, category, bbox?, score?, matcher, evidence_id, status。
TaskEvent: seq, action, input_ids, result, provenance。
SearchReport: task_id, result_status, location?, evidence_ids, visited_viewpoints, limitations。

## 质量要求
核心算法可以完全离线运行和测试；数据的真实来源不得由 LLM 改写；随机性显式设种子；日志与测试集包含负例；路径统一使用仓库相对路径或配置。
