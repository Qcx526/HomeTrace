/** Create the evidence-based November delivery deck with the bundled Artifact Tool.
 * Run with --artifact-module <.../artifact_tool.mjs> --skill-dir <presentation skill>
 * --python <bundled python> [--output-dir <new ignored directory>].
 * Reads public evidence only. Never loads local credentials, databases or photographs.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import crypto from 'node:crypto';

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, item, i, all) => {
  if (item.startsWith('--')) pairs.push([item.slice(2), all[i + 1]]);
  return pairs;
}, []));
for (const key of ['artifact-module', 'skill-dir', 'python']) {
  if (!args[key]) throw new Error(`Missing --${key}`);
}
const root = process.cwd();
const output = path.resolve(args['output-dir'] || 'artifacts/submission-closeout-20261102/pptx/build-01');
await fs.mkdir(output, { recursive: false });
const { Presentation, PresentationFile } = await import(pathToFileURL(path.resolve(args['artifact-module'])).href);
// The finalizer spawns a clean import probe using the same bundled packages.
process.env.RUNTIME_NODE_MODULES ||= path.resolve(path.dirname(args['artifact-module']), '../../..');
const { finalizePresentation } = await import(pathToFileURL(path.join(args['skill-dir'], 'container_tools/artifact_tool_utils.mjs')).href);
const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = { bg: '#F5F3EE', ink: '#183831', muted: '#526660', teal: '#167360', light: '#E2EBE6', white: '#FFFFFF', caution: '#9A592B' };
const font = 'Microsoft YaHei';
const cited = new Set();
function text(slide, value, x, y, w, h, size = 27, color = C.ink, bold = false) {
  const shape = slide.shapes.add({ geometry: 'textbox', position: { left: x, top: y, width: w, height: h }, fill: 'none', line: { fill: 'none', width: 0 } });
  shape.text = value;
  shape.text.style = { typeface: font, fontSize: size, color, bold, wrap: 'square', autoFit: 'none', insets: 0 };
  return shape;
}
function slide(title, sources, note = '') {
  const s = presentation.slides.add();
  s.background.fill = C.bg;
  if (title) text(s, title, 72, 58, 1136, 65, 43, C.ink, true);
  text(s, `HomeTrace  /  ${String(presentation.slides.items.length).padStart(2, '0')}`, 72, 671, 700, 25, 17, C.muted);
  sources.forEach(p => cited.add(p));
  s.speakerNotes.text = `${note}\n\n来源：\n${sources.map(p => `仓库公开文件 ${p}`).join('\n')}\n证据快照：537aa9cdb1f893f411e98ef9ff20a00250f607eb（PR #47，待合并）。真实执行源码：cd75a52d1710608f316df401ea07f2e8d2008d7a。材料更新：2026-11-02。软件回归、合成流程与实拍诊断分别统计。`;
  return s;
}
function para(s, y, head, body, x = 72, width = 1136) {
  text(s, head, x, y, width, 45, 30, C.teal, true);
  text(s, body, x, y + 52, width, 83, 27, C.ink);
}
function table(s, values, widths, y, rowHeight = 76) {
  const t = s.tables.add({ rows: values.length, columns: values[0].length, left: 72, top: y, width: 1136, height: values.length * rowHeight, columnWidths: widths, values });
  t.borders.assign({ fill: '#D0DAD4', width: 1, style: 'solid' });
  for (let r = 0; r < values.length; r++) for (let c = 0; c < values[0].length; c++) {
    const cell = t.getCell(r, c);
    cell.fill = r === 0 ? C.ink : r % 2 === 0 ? C.light : C.white;
    cell.text.style = { typeface: font, fontSize: r === 0 ? 25 : 24, color: r === 0 ? C.white : C.ink, bold: r === 0, insets: { top: 15, bottom: 10, left: 18, right: 15 }, verticalAlignment: 'middle', wrap: 'square' };
  }
  return t;
}
const demo = 'docs/DELIVERABLE_DEMO.md';
const memory = 'docs/OWNER_MEMORY_RESTART_ACCEPTANCE.md';
const latest = 'docs/REAL_CUP_FRESH_WORKFLOW_20261102.md';
const evidencePath = 'docs/evidence/issue-46-new-photos/workflow.json';
const evidence = JSON.parse(await fs.readFile(path.join(root, evidencePath), 'utf8'));
const main = evidence.second.runs.main;
const realChecks = evidence.second.checks.filter(check => check.passed).length;
if (main.state !== 'USER_CONFIRMED' || main.automatic_found !== false || evidence.second.new_owner_events !== 1) {
  throw new Error('Published evidence no longer matches the approved owner-assisted claim');
}

let s = slide('', [demo, latest], '本作品展示单水杯、主人参与确认的软件流程。导航模拟，真实照片由主人提供，语言和视觉调用经过第三方网关。团队名称和个人信息保留在官方主表，当前待负责人填写。');
s.background.fill = C.ink;
text(s, 'HomeTrace', 72, 166, 1100, 104, 84, C.white, true);
text(s, '智慧家庭寻物 Agent', 76, 288, 1080, 78, 49, '#DCEDE6', true);
text(s, '记住主人说过的位置，依据当前观察继续寻找', 78, 406, 1090, 60, 32, '#DCEDE6');
text(s, '作品技术展示    2026 年 11 月', 78, 593, 1040, 38, 24, '#B8D3C6');

s = slide('家庭寻物场景', [demo, latest], '本页对话是交互方案示例，不冒充真实模型逐字响应。主人选择地点并提供照片，软件没有自动定位主人或控制实体机器人。当前实拍证据仅支持单水杯受限流程。');
text(s, '“这个物品我放这里了，帮我记住。”', 72, 178, 1136, 70, 41, C.teal, true);
text(s, '主人登记参考外观，选择地点，确认保存位置历史。', 74, 270, 1120, 58, 30);
text(s, '“我找不到它了，帮我找一下。”', 72, 381, 1136, 70, 41, C.teal, true);
text(s, 'Agent 查询历史、检查照片，依据反馈换地点或请求近照。\n主人核对后，系统保存新的照片位置历史。', 74, 475, 1118, 102, 30);

s = slide('物品登记与位置记忆', [demo, memory, latest], '固定参考图及经主人审核的 ROI 形成物品档案，登记不触发每物品训练。主人提供地点并确认保存。拍摄时间未知时不推断时间。新进程恢复同一事件已经实际验证。');
para(s, 163, '01  登记外观', '名称、别名和参考图归入同一档案。主人核对物体区域，无需为每件新物品训练网络。');
para(s, 322, '02  保存有来源的位置', 'SQLite 记录地点、确认时间及信息来源。主人陈述与视觉证据分别保存。');
para(s, 481, '03  保留历史线索', '跨进程读取同一记录。历史地点只提供搜索线索，不保证物品现在仍在那里。');

s = slide('LLM 的实际决策职责', [demo, latest, evidencePath], 'LangGraph 管理状态，LangChain 提供模型和工具接口。真实 LLM 调用 resolve_request、inspect_location、visual_advice、request_new_photo 和 request_owner_review。模型只选择行动，程序执行并校验。');
text(s, '语言模型选择下一步', 72, 164, 550, 57, 33, C.teal, true);
text(s, '理解记住、寻找或查询请求\n读取历史后选择搜索地点\n依据反馈换地点、请求近照\n或邀请主人核对候选', 72, 243, 545, 260, 29);
text(s, '程序执行并记录证据', 700, 164, 508, 57, 33, C.teal, true);
text(s, '校验物品、地点与调用权限\n执行模拟导航和照片观察\n限制步骤、Token 与图片额度\n保存工具返回和失败原因', 700, 243, 508, 260, 29);
text(s, '模型文字不能生成权威位置事实、真实机器人动作或检测证据。', 72, 572, 1136, 62, 27, C.caution, true);

s = slide('真实水杯流程中的反馈决策', [latest, evidencePath], '第二轮实际 HTTP 流程。配置中 B 先于 H，LLM 仍依据 H 历史先检查 H。本页是脱敏执行记录，不是新录屏。S3 由操作员提交主人提供的近景。负责人预先明确批准身份与地点后，工程师按授权通过 HTTP 保存。导航模拟。');
table(s, [['步骤', '真实观察或工具返回', 'LLM 实际选择'], ['1  查询历史', '最近主人历史位于 H', '先检查 H，改变配置顺序'], ['2  检查 H', 'S1：未见目标', '继续检查地点 B'], ['3  检查 B', 'S2：全景不确定', 'request_new_photo 请求近照'], ['4  读取近照', 'S3：外观相似', 'request_owner_review 请求核对'], ['5  主人授权', '明确同一水杯及照片地点', '系统保存 USER_CONFIRMED']], [224, 432, 480], 158, 67);
text(s, '照片来自主人，导航模拟。最终身份与位置历史由主人确认。', 72, 593, 1136, 52, 25, C.caution, true);

s = slide('5 张新实拍的完整结果', [latest, evidencePath], 'S1/S2/S3 为搜索链。S4/S5 为独立负例会话，不伪称五张都在同一次搜索中。存在性来自主人说明，缺少数值真值框，不能计算 IoU。全部为流程诊断，不能当作独立识别基准。公开展示不包含私人原图。');
table(s, [['场景', '视觉顾问建议', '实际后续结果'], ['S1  原位置无目标', 'not_visible', '检查下一地点'], ['S2  新位置全景', 'uncertain', '请求同地点近照'], ['S3  同位置近景', 'similar', '请求主人核对'], ['S4  相似杯负例', 'not_visible', 'UNKNOWN，无候选/记忆写入'], ['S5  空场景', 'not_visible', 'UNKNOWN，无候选/记忆写入']], [345, 300, 491], 158, 64);
text(s, '固定 ORB 全部没有合格框。近景支持本轮人工核对，自动定位仍未通过。', 72, 572, 1136, 71, 27, C.caution, true);

s = slide('确认后的记忆与旧图保护', [latest, evidencePath], '第二轮恰好新增 1 条 owner_reported，visual_confirmed=false。实际不同 PID 重启恢复同一 run。真实文本 LLM 查询新历史。旧 S1/S2 均 replayed_image_content，UNKNOWN，无图片重发、无新主人事件。未声称复查全局 S3 或当轮浏览器点击验收。');
table(s, [['验证项', '真实结果'], ['主人确认保存', '1 条 owner_reported，未写入自动视觉确认'], ['服务进程重启', '新进程恢复同一事件，数据库没有重复写入'], ['LLM 查询历史', '返回照片地点，并保留“此刻位置未知”的边界'], ['旧照片再次搜索', 'UNKNOWN，拒绝重放，零图片外发、零新记忆']], [345, 791], 168, 78);
text(s, 'USER_CONFIRMED 记录主人确认。它不代表系统自动识别物理实例。', 72, 591, 1136, 53, 26, C.caution, true);

s = slide('预算失败与受控复跑', [latest, evidencePath], '首次24,000预算失败保留。14,011已使用 + 11,145下一请求输入保守上界 = 25,156，超过24,000。第二轮仅将文本总预算设置32,000，视觉门槛/模型/工具调用等保持不变。新图片授权单独获得，零自动重试。展示的调用数仅第二轮主流程，不包括历史查询与重放。');
text(s, '首次运行：明确停止', 72, 169, 540, 57, 33, C.caution, true);
text(s, '24,000 Token 文本预算\n近景后的决策输入超过余量\nBUDGET_EXCEEDED\n没有保存新位置', 72, 249, 535, 245, 29);
text(s, '复跑：完成主人参与流程', 686, 169, 522, 57, 33, C.teal, true);
text(s, `32,000 Token 文本预算\n${main.model_calls} 次文本调用，${main.decision_tokens.toLocaleString('en-US')} Token\n${main.vision_calls} 次视觉调用，${main.vision_tokens.toLocaleString('en-US')} Token\n仅按主人授权保存 1 条历史`, 686, 249, 522, 245, 29);
text(s, '只调整文本总预算。旧失败保留，图像授权按批次单独计算。', 72, 572, 1136, 62, 27, C.muted);

s = slide('分开记录软件回归与实拍检查', [latest, evidencePath, 'docs/evidence/issue-46-new-photos/pytest.txt', 'docs/evidence/issue-46-new-photos/frontend.txt'], '引用 PR47 证据快照 537aa9c 下的实际联合回归：1137 pytest passed,1现有LangChain弃用警告,189.78秒；Node28 passed,252.4792ms。不是新材料分支尚未执行的测试数。9项实拍执行检查全部通过只验证受限流程，不证明识别精度。未重新执行全新Windows安装。');
text(s, String(evidence.tests.pytest), 72, 159, 515, 113, 92, C.teal, true);
text(s, 'Python 全量测试通过', 76, 277, 520, 57, 28);
text(s, String(evidence.tests.frontend), 700, 159, 490, 113, 92, C.teal, true);
text(s, '前端测试通过', 704, 277, 480, 57, 28);
text(s, `另有 ${realChecks} 项真实执行检查通过`, 72, 382, 1136, 64, 35, C.teal, true);
text(s, '覆盖历史优先、反馈搜索、主人确认、重启恢复和旧图拒绝。', 72, 463, 1136, 65, 30);
text(s, 'PR #47 基线 537aa9c，待合并。软件测试数量不代表真实识别准确率。', 72, 579, 1136, 53, 24, C.muted);

s = slide('隐私与外部模型调用', [demo, latest, 'config.photo-demo.yaml'], '真实文本和视觉经过当前第三方兼容网关。供应方实际模型底座未独立验证，不宣传为模型官方直连。原图与私人地点、API Key、SQLite、完整授权和响应均留本地 ignored 目录。已用图片授权不能复用。');
para(s, 160, '敏感数据保留本地', '私人照片、地点绑定、API Key 与数据库不进入公共源码和演示材料。');
para(s, 320, '逐批授权图片外发', '明确网关、图片及次数。发送去 EXIF 的缩小副本，背景仍存在，零自动重试。');
para(s, 480, '调用失败明确表达', '当前方案依赖第三方网络模型。额度、超时或观察不足时停止或请求协助。');

s = slide('作品创新与技术选择', [demo, memory, latest], '原创性重点是产品流程与工程规则，不声称原创基础识别算法。成熟方法包括OpenCV ORB、LangGraph/LangChain、SQLite和外部模型服务。历史导致本轮改变搜索顺序，但没有对照证据证明普遍搜索效率提升。');
para(s, 158, '有来源的家庭位置记忆', '把主人陈述、历史地点与当前观察分开，避免把旧记忆当作当前事实。');
para(s, 318, '根据反馈改变下一步', 'LLM 在真实工具返回后选择换地点、请求近照或交给主人核对。');
para(s, 478, '可审计的人机协作', '拒识、预算停止和旧图重放都有明确记录。成熟算法与服务支撑轻量可运行 Demo。');

s = slide('交付范围与能力边界', [latest, evidencePath], '本轮可以交付受限单水杯、主人参与确认的软件Demo。自动实例识别、可靠bbox、独立6正8负、家庭通用识别、真机运行未通过。长期习惯学习及普遍搜索效率提升未验证。团队个人信息留空，正式主表及平台格式、容量、截止时刻由负责人核验，当前未正式上传。');
text(s, '可演示：受限单水杯的主人协作流程', 72, 161, 1136, 60, 35, C.teal, true);
text(s, '真实 LLM 调用工具、依据照片反馈寻找、请求主人核对，\n保存位置历史并在重启后查询。', 72, 243, 1136, 105, 30);
text(s, '尚未通过：自动实例识别与通用识别', 72, 391, 1136, 60, 35, C.caution, true);
text(s, '没有可靠检测框和独立识别基准。导航模拟，\n长期习惯学习、效率提升和真实机器人运行均未验证。', 72, 473, 1136, 105, 30);
text(s, '提交前仍需填写团队信息并核对赛事平台要求。当前为审查材料，尚未正式提交。', 72, 605, 1136, 43, 22, C.muted);

const draft = path.join(output, 'draft.pptx');
await (await PresentationFile.exportPptx(presentation)).save(draft);
const renders = path.join(output, 'renders');
await fs.mkdir(renders);
for (const [i, page] of presentation.slides.items.entries()) {
  const png = await presentation.export({ slide: page, format: 'png', scale: 1 });
  await fs.writeFile(path.join(renders, `slide-${String(i+1).padStart(2, '0')}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await page.export({ format: 'layout' });
  await fs.writeFile(path.join(renders, `slide-${String(i+1).padStart(2, '0')}.json`), await layout.text());
}
const finalDirectory = path.join(output, 'final');
await fs.mkdir(finalDirectory);
const finalPath = path.join(finalDirectory, 'HomeTrace_技术展示.pptx');
const result = await finalizePresentation({
  workspaceDir: root, candidatePath: draft, finalPath,
  pythonExecutable: args.python,
  integrityValidatorPath: path.join(args['skill-dir'], 'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(args['skill-dir'], 'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu', '12192000,6858000', '--validate-bullet-geometry', '--validate-heading-fit', '--require-native-table-slide', '5', '--require-native-table-slide', '6', '--require-native-table-slide', '7'],
  explicitTotalSlideCount: 12,
  requiredNativeTableOwnerSlides: [5, 6, 7],
  fontPolicy: { basis: 'design', families: [font] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(output, 'validation.json'),
});
await fs.writeFile(path.join(output, 'sources.json'), JSON.stringify({
  date: '2026-11-02', code_evidence_date: '2026-11-02', code_evidence_commit: evidence.source_commit, reviewed_snapshot: '537aa9cdb1f893f411e98ef9ff20a00250f607eb', snapshot_status: 'PR47 open, not merged',
  sources: await Promise.all([...cited].map(async p => ({ path: p, sha256: crypto.createHash('sha256').update(await fs.readFile(path.join(root,p))).digest('hex') }))),
  final_sha256: crypto.createHash('sha256').update(await fs.readFile(finalPath)).digest('hex'),
  slide_count: 12, render_review_required: true,
}, null, 2));
console.log(JSON.stringify({ finalPath, result }, null, 2));
