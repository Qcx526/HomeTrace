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
const output = path.resolve(args['output-dir'] || 'artifacts/issue-44/deck/build-01');
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
  s.speakerNotes.text = `${note}\n\n来源：\n${sources.map(p => `仓库公开文件 ${p}`).join('\n')}\n证据基线：16445f79491617b899c3c7bafca7c1241719e0c4（2026-10-31）。材料更新：2026-11-02。不同阶段验收不合并为同一次完整实拍验收。`;
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
const real = 'docs/REAL_CUP_AGENT_ACCEPTANCE.md';
const memory = 'docs/OWNER_MEMORY_RESTART_ACCEPTANCE.md';
const latest = 'docs/WORKSPACE_LOCATIONS_AND_NEW_PHOTOS.md';

let s = slide('', [demo, latest], '开场说明：本作品展示软件 Agent 的家庭物品记忆与寻找过程。页面中的导航属于模拟。真实家庭实例自动识别仍有明确能力边界。');
s.background.fill = C.ink;
text(s, 'HomeTrace', 72, 166, 1100, 104, 84, C.white, true);
text(s, '智慧家庭寻物 Agent', 76, 288, 1080, 78, 49, '#DCEDE6', true);
text(s, '记住主人说过的位置，依据当前观察继续寻找', 78, 406, 1090, 60, 32, '#DCEDE6');
text(s, '作品技术展示  ·  2026 年 11 月', 78, 593, 1040, 38, 24, '#B8D3C6');

s = slide('家庭寻物场景', [demo], '本页是交互方案示例，所列话语不冒充特定真实模型响应。主人需要选择当前地点，软件没有自动获取主人位置。');
text(s, '“这个物品我放这里了，帮我记住。”', 72, 178, 1136, 70, 41, C.teal, true);
text(s, '主人登记物品外观，选择地点，确认位置记录。', 74, 270, 1120, 58, 30);
text(s, '“我找不到它了，帮我找一下。”', 72, 381, 1136, 70, 41, C.teal, true);
text(s, 'Agent 先查询历史，再检查场景。主人核对候选，或让它继续找。', 74, 475, 1118, 94, 30);

s = slide('物品登记与位置记忆', [demo, memory, latest], '同一物品使用固定参考图和经过主人审核的 ROI。登记不触发每物品训练。当前视觉比较不能单凭名称证明特定实体身份。');
para(s, 163, '01  名称与外观', '物品编号、名称和别名归入同一档案。上传参考图，人工核对目标区域。');
para(s, 322, '02  主人陈述', '主人提供地点，确认后写入 SQLite。记录来源和确认时间，不推断拍摄时间。');
para(s, 481, '03  跨运行保留', '重启后读取同一条历史。自定义地点保持独立，新任务冻结本次地点与场景配置。');

s = slide('LLM 的实际决策职责', [demo, real, latest], '运行采用 LangGraph 状态与 LangChain 模型/工具接口。页面展示实际执行的工具与反馈。LLM 只提出计划和调用，程序执行并校验。视觉外发另有明确授权。');
text(s, '语言模型选择下一步', 72, 164, 550, 57, 33, C.teal, true);
text(s, '理解记住、寻找或查询请求\n读取历史后选择搜索地点\n根据观察决定换地点、补图或请主人核对', 72, 243, 545, 224, 29);
text(s, '程序执行并留下证据', 700, 164, 508, 57, 33, C.teal, true);
text(s, '校验已登记物品和合法地点\n执行模拟导航与照片观察\n限制步骤、Token 和调用额度\n保存工具返回、失败与确认来源', 700, 243, 508, 260, 29);
text(s, '模型的文字推断不能生成位置事实、机器人动作或视觉证据。', 72, 572, 1136, 62, 27, C.caution, true);

s = slide('可追溯的位置历史', [memory, latest, 'docs/evidence/issue-34/browser-history.png'], '图为仓库已公开的软件样例截图，照片素材标记为 AI 合成。它说明页面如何展示历史与来源，不是本批私人水杯的识别结果。Issue40 另外验证了真实主人陈述的跨进程读取。');
const screenshot = await fs.readFile(path.join(root, 'docs/evidence/issue-34/browser-history.png'));
s.images.add({ blob: screenshot.buffer.slice(screenshot.byteOffset, screenshot.byteOffset + screenshot.byteLength), contentType: 'image/png', alt: '公开软件样例的历史查询页面，素材为 AI 合成图', fit: 'contain', position: { left: 70, top: 155, width: 505, height: 475 } });
text(s, '历史只提供寻找线索', 632, 175, 576, 60, 35, C.teal, true);
text(s, '保存物品、地点、时间和来源。\n\n刷新与进程重启保留记录。\n\n历史地点与当前照片分开，旧图片不能重复贡献新证据。', 632, 263, 576, 280, 29);
text(s, '左侧为公开软件样例截图，包含 AI 合成素材。', 632, 585, 570, 47, 21, C.muted);

s = slide('确认状态与证据边界', [demo, real, latest], '当前照片流程将本地外观匹配与物理实例确认分开。没有框的匹配不能伪造定位框。主人明确确认才形成 owner_reported 事件。');
table(s, [['结果', '来源', '系统含义'], ['UNKNOWN', '观察不足、拒识或调用失败', '继续寻找、补图或停止'], ['SUSPECTED / similar', '本地候选或视觉顾问意见', '等待核对，尚未确认实体'], ['USER_CONFIRMED', '主人明确接受', '保存主人确认的历史来源']], [310, 390, 436], 176, 89);
text(s, 'YOLO 类别分数、LLM 建议和几何匹配都不单独决定实体 FOUND。', 72, 581, 1136, 58, 27, C.caution, true);

s = slide('已验证的软件流程', [demo, memory, latest], '本页测试数字引用 Issue42 在提交16445f7前实际执行的联合全量回归，不累加独立分支。1061 Python 测试及22前端测试不证明真实照片定位精度。真实API流程分别来自Issue30与Issue40。');
text(s, '1061', 72, 167, 515, 113, 92, C.teal, true);
text(s, 'Python 全量测试通过', 76, 285, 520, 57, 28);
text(s, '22', 700, 167, 490, 113, 92, C.teal, true);
text(s, '前端测试通过', 704, 285, 480, 57, 28);
text(s, '登记、记忆确认、历史查询、反馈继续与旧图重放均有回归。', 72, 385, 1136, 67, 30);
text(s, '真实 LLM 已执行软件样例寻找流程，并完成跨进程记忆查询。', 72, 468, 1136, 67, 30);
text(s, '证据快照：16445f7。合成流程、实拍诊断与软件测试分别统计。', 72, 578, 1136, 52, 23, C.muted);

s = slide('最新 8 张家庭照片的实际结果', [latest, 'docs/evidence/issue-42/photo-results.json'], '全部为开发诊断照片，无独立测试集。6正2负来自主人文件名，未审核数值真值框。每图一次、零重试，8次真实视觉调用、7次有效返回。API失败为输出token耗尽且无有效JSON。');
table(s, [['主人存在性标签', '视觉顾问实际输出', '数量'], ['目标出现，共 6 张', '外观相似 similar', '4'], ['目标出现，共 6 张', '不确定 uncertain', '1'], ['目标出现，共 6 张', '无效响应 ERROR', '1'], ['目标缺席，共 2 张', '未见目标 not_visible', '2']], [355, 576, 205], 166, 68);
text(s, '固定 ORB 在全部 8 张图上没有有效框。未取得自动定位或独立实例识别通过证据。', 72, 546, 1136, 94, 28, C.caution, true);

s = slide('隐私与失败处理', [demo, real, memory, latest], '原图、私人身份、API Key、授权账本、原始响应与数据库均留本地ignored目录。图像外发按批次和图片哈希授权，已用额度不复用。公共证据使用脱敏汇总。');
para(s, 160, '本地保留敏感数据', '照片、私人地点和 SQLite 留在工作区。公共源码仅携带脱敏指标和测试。');
para(s, 320, '图片外发需明确授权', '固定网关、固定图片和调用额度。发送去 EXIF 副本，仍保留画面中的背景。');
para(s, 480, '失败保持可见', '额度耗尽、模型失败或观察不足时停止或请求协助。不给出虚假的成功结论。');

s = slide('当前交付范围与下一步', [demo, real, memory, latest], '作品贡献在记忆、工具决策、证据约束和人机协作流程。成熟视觉方法与模型采用既有开源/服务方案。当前还没有证明搜索效率提升，没有机器人真机运行，也未完成独立真实照片实例识别验收。');
text(s, '已形成可运行的软件 Demo', 72, 163, 1136, 58, 36, C.teal, true);
text(s, '物品登记、历史记忆、LLM 工具决策、自定义地点和主人确认形成可追溯流程。', 72, 245, 1136, 95, 30);
text(s, '真实家庭识别仍需验收', 72, 393, 1136, 58, 36, C.caution, true);
text(s, '当前重点是完成自定义地点的实拍 Agent 搜索与主人核对。自动定位、独立照片测试和真机运行尚未通过。', 72, 475, 1136, 104, 30);
text(s, '作品贡献：把记忆线索、当前观察和主人确认放入同一条可审计的寻找过程。', 72, 603, 1136, 42, 23, C.muted);

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
  layoutArgs: ['--expected-slide-size-emu', '12192000,6858000', '--validate-bullet-geometry', '--validate-heading-fit', '--require-native-table-slide', '6', '--require-native-table-slide', '8'],
  explicitTotalSlideCount: 10,
  requiredNativeTableOwnerSlides: [6, 8],
  fontPolicy: { basis: 'design', families: [font] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(output, 'validation.json'),
});
await fs.writeFile(path.join(output, 'sources.json'), JSON.stringify({
  date: '2026-11-02', code_evidence_date: '2026-10-31', code_evidence_commit: '16445f79491617b899c3c7bafca7c1241719e0c4',
  sources: await Promise.all([...cited].map(async p => ({ path: p, sha256: crypto.createHash('sha256').update(await fs.readFile(path.join(root,p))).digest('hex') }))),
  final_sha256: crypto.createHash('sha256').update(await fs.readFile(finalPath)).digest('hex'),
  slide_count: 10, render_review_required: true,
}, null, 2));
console.log(JSON.stringify({ finalPath, result }, null, 2));
