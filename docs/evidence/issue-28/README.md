# Issue #28 实际验收证据

2026-10-28。参见 [实现、运行方法与能力边界](../../HOUSEHOLD_PHOTO_AGENT.md)。

- [联合 Python 回归](pytest-01.txt)：773 passed，0 failed/skipped，1 条既有警告，123.07 秒。
- [Node 回归](node-01.txt)：8 passed，包含原有 4 项；独立统计。
- [真实 API 完整验证](live-02.json)：4 个 CLI 进程、8 个不同请求、22 次真实模型调用、28415 Token，记忆/历史/候选/重启确认/旧图/拒绝重规划/负例与缺图。按 run_id 去重，确认前后的快照不重复计数。
- [首次失败记录](live-01.json)：早期模型重复解析已绑定目标，程序拒绝；保留原结果，不用后续成功覆盖。
- [浏览器实际执行](browser-run.json)、[候选 AX](browser/01-candidate-ax.txt)、[刷新恢复](browser/02-refresh-ax.txt)、[拒绝后 UNKNOWN](browser/03-rejected-ax.txt)：另一个独立工作区的真实 UI 与 API，不是 DOM 软件测试。
- [构建日志](wheel-build.txt)、[源码哈希及隐私审计](audit.json)。

原始 HTTP 请求/响应、数据库、照片和截图保存在本机 ignored 的 `artifacts/issue-28/`。公开结果不含照片字节、Key 或私有绝对路径。截图 `browser/01-llm-candidate.png` 显示真实模型、3 次调用、3820 Token 与书房候选；`browser/03-llm-rejected.png` 为拒绝后无匹配的红钥匙图。图片全部是授权 AI 合成素材，不能用作真实家庭识别指标。

本轮早期浏览器连接不可用，随后恢复并完成上述限定范围的 UI 验证。模型解释可能不准确；尤其缺图不等于成功看过场景，以 `no_observation` 等实际工具结果为准。导航模拟，人工确认只记录主人陈述；没有自动实例 FOUND。真实家庭识别与正式参赛包仍未验收完成。PR 等待负责人审查，不自行合并。
