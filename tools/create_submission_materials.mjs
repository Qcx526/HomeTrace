/** Offline PPTX authoring with @oai/artifact-tool. No HomeTrace runtime dependency.
 * Set HOMETRACE_ARTIFACT_MODULES to the bundled node_modules directory and
 * HOMETRACE_PRESENTATION_SKILL to the installed Presentations skill directory.
 * Optional HOMETRACE_TEST_COUNT/HOMETRACE_TEST_LOG require a real test log.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runtime = process.env.HOMETRACE_RUNTIME ?? path.join(process.env.USERPROFILE ?? '', '.cache/codex-runtimes/codex-primary-runtime/dependencies');
const modules = process.env.HOMETRACE_ARTIFACT_MODULES ?? path.join(runtime, 'node/node_modules');
process.env.RUNTIME_NODE_MODULES = modules;
const skill = process.env.HOMETRACE_PRESENTATION_SKILL ?? path.join(process.env.USERPROFILE ?? '', '.codex/plugins/cache/openai-primary-runtime/presentations/26.1020.11127/skills/presentations');
const { Presentation, PresentationFile } = await import(pathToFileURL(path.join(modules, '@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const { finalizePresentation } = await import(pathToFileURL(path.join(skill, 'container_tools/artifact_tool_utils.mjs')).href);
const revision = process.env.HOMETRACE_MATERIAL_REVISION ?? 'r1';
const build = path.join(root, 'artifacts/p3-materials', revision);
const outputDir = path.join(build, 'output');
await fs.mkdir(outputDir, {recursive:true});
const count = process.env.HOMETRACE_TEST_COUNT;
if (count) await fs.access(path.resolve(root, process.env.HOMETRACE_TEST_LOG ?? '__missing_test_log__'));

const font='Microsoft YaHei';
const colors={bg:'#F6F5F1',ink:'#142B3D',muted:'#51616C',teal:'#087F78',amber:'#A35F11',white:'#FFFFFF'};
const presentation=Presentation.create({slideSize:{width:1280,height:720}});
function tx(slide,text,x,y,w,h,size=28,color=colors.ink,bold=false){
  const shape=slide.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  shape.text=text;
  shape.text.style={typeface:font,fontSize:size,bold,color};
  return shape;
}
function base(number,title,summary){
  const slide=presentation.slides.add();slide.background.fill=colors.bg;
  tx(slide,title,64,46,1152,78,44,colors.ink,true);
  if(summary)tx(slide,summary,64,132,1152,58,25,colors.muted);
  tx(slide,'HomeTrace    实拍图像 · 模拟导航 · 无真实机器人运行',64,676,1040,25,16,colors.muted);
  tx(slide,`${String(number).padStart(2,'0')} / 10`,1120,676,100,25,16,colors.muted);
  return slide;
}
async function picture(slide,name,x,y,w,h){
 const bytes=await fs.readFile(path.join(root,'docs/evidence/issue-3/browser',name));
 slide.images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:'image/png',alt:`HomeTrace actual browser evidence ${name}`,fit:'contain',position:{left:x,top:y,width:w,height:h}});
}
function note(slide,value){slide.speakerNotes.text=value;}
function table(slide,values,y,widths){
  const t=slide.tables.add({rows:values.length,columns:values[0].length,left:64,top:y,width:1152,height:values.length*72,columnWidths:widths,values});
  t.borders.assign({style:'solid',fill:'#D8DEDF',width:1});
  for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){
    const cell=t.getCell(r,c);cell.fill=r===0?'#17324D':r%2?'#FFFFFF':'#EDF2F2';
    cell.text.style={typeface:font,fontSize:24,bold:r===0,color:r===0?'#FFFFFF':colors.ink};
  }
  return t;
}

let s=base(1,'HomeTrace','家庭物品的时空记忆与主动寻找');
tx(s,'记住历史位置\n用当前证据确认结果',64,250,1120,170,58,colors.ink,true);
tx(s,'2026 年华为嵌入式软件大赛初赛技术展示',64,468,1100,52,29,colors.teal);
tx(s,'可运行软件闭环与家庭照片适用性实测',64,536,1100,48,27,colors.muted);
note(s,'团队自编技术展示。证据来源：docs/evidence/issue-3/；docs/TEAM_PHOTO_EVALUATION.md。个人团队身份仅在本地填写。导航全部模拟，没有真实机器人运行数据。');

s=base(2,'从历史线索开始，逐步验证','产品创新集中在记忆、决策与证据的完整流程');
tx(s,'01  登记物品与历史位置',64,226,1120,56,34,colors.teal,true);
tx(s,'SQLite 跨运行保存参考外观、历史观测和来源。',124,286,1050,52,29);
tx(s,'02  读取当前观察并调整计划',64,374,1120,56,34,colors.teal,true);
tx(s,'先检查历史点，未确认时继续搜索候选地点。',124,434,1050,52,29);
tx(s,'03  结果附带可追溯证据',64,522,1120,56,34,colors.teal,true);
tx(s,'展示当前照片、几何支持、失败原因与结束状态。',124,582,1050,52,29);
note(s,'来源：docs/PRODUCT_BRIEF.md、docs/ARCHITECTURE.md、docs/P1_IMPLEMENTATION.md。历史位置是决策依据，不能作为本轮确认。');

s=base(3,'历史记录不能代替当前证据','图像来源、时间和 SHA256 共同约束证据链');
table(s,[['状态','含义','对用户的说明'],['FOUND','当前图像通过验证','确认外观与地点'],['SUSPECTED','存在候选但支持不足','尚未确认'],['UNKNOWN','没有足以确认的证据','尚未确认']],220,[260,430,462]);
tx(s,'旧图更名或改时间，仍不能产生新的确认。',64,570,1152,52,31,colors.teal,true);
note(s,'来源：docs/P1_IMPLEMENTATION.md 与 docs/evidence/issue-3/replay/。SUSPECTED 和 UNKNOWN 不证明物品不存在。FOUND 是已登记外观，不区分同款多个实体。');

s=base(4,'轻量本地实现，核心逻辑独立','Python + SQLite + OpenCV + 本地 HTML/JS');
table(s,[['模块','本阶段职责'],['Search Core','历史查询、候选排序、观察消费与重规划'],['视觉适配','ORB 特征、Hamming 匹配、RANSAC 验证'],['证据存储','参考图、当前图、摘要、时间与结构化事件'],['展示与导航','逐步页面与模拟到达事件']],216,[300,852]);
tx(s,'无需模型权重、ROS 或机器人 SDK。',64,606,1152,44,27,colors.muted);
note(s,'来源：pyproject.toml、src/hometrace/、docs/ARCHITECTURE.md。OpenCV 等成熟算法为开源复用，原创贡献为记忆、决策、验证和展示适配。');

s=base(5,'正例在 B 获得当前图像确认','公开实拍样例：检查 A 未确认，继续 B，最终 FOUND');
await picture(s,'moved-matched.png',64,210,790,420);
tx(s,'45',900,240,280,70,60,colors.teal,true);tx(s,'有效匹配',900,314,280,44,26);
tx(s,'41',900,392,280,70,60,colors.teal,true);tx(s,'几何内点',900,466,280,44,26);
tx(s,'框坐标与报告一致',876,568,340,44,26,colors.muted);
note(s,'实际截图：docs/evidence/issue-3/browser/moved-matched.png，配套 moved-report.json。45 matches/41 inliers。bbox [90.4,159.53,285.45,296.16]。OpenCV box_in_scene.png 为独立正例，box.png 登记自匹配不计独立正例。图片来源与许可：examples/recorded_images/sources.json。A/B/C 和时间为 Demo 编排。');

s=base(6,'负例保留未确认状态','SUSPECTED 的确认地点为空，不把候选匹配解释为成功');
await picture(s,'missing-final.png',64,204,790,432);
tx(s,'SUSPECTED',872,280,344,55,34,colors.amber,true);
tx(s,'检查全部候选点\n仍无可靠确认\n\n不证明物品不存在',872,370,344,222,27);
note(s,'来源：docs/evidence/issue-3/browser/missing-final.png，missing-report.json。公开负例为 OpenCV apple/orange/fruits 照片，原图未修改，不是机器人采集。');

s=base(7,'旧图重放不能刷新确认','已见图像拒绝成为本轮新证据，最终 UNKNOWN');
await picture(s,'replay-rejected-B.png',64,204,790,432);
tx(s,'UNKNOWN',872,280,344,55,36,colors.amber,true);
tx(s,'拒绝旧 B 与旧 A\n仅 C 新解码\n\n不出现当前确认框',872,370,344,222,27);
note(s,'来源：docs/evidence/issue-3/browser/replay-rejected-B.png、replay-report.json。三次模拟到达仅一次新的图像观察，重放拒绝不能包装为新的视觉匹配。');

s=base(8,'公平对照中，当前步数打平','同候选点、同输入图片，两种策略分别登记与运行');
table(s,[['场景','记忆优先','固定顺序','最终状态'],['正例 moved','2 步','2 步','FOUND / B'],['负例 missing','3 步','3 步','SUSPECTED'],['重放 replay','3 步','3 步','UNKNOWN']],218,[350,240,240,322]);
tx(s,'尚未证明搜索效率提高',64,552,1152,55,35,colors.teal,true);
tx(s,count?`P3 本轮 ${count} 项通过；P2 稳定基线 148 项保留。`:'P2 稳定基线 148 项通过；P3 本轮见最新测试日志。',64,614,1152,39,24,colors.muted);
note(s,`来源：docs/evidence/issue-3/comparison.json，pytest.txt。P2 基线 main efaaaffae47ddb577ec9472d03838b66321eb178。${count?`P3 ${count} passed，日志 ${process.env.HOMETRACE_TEST_LOG}`:'P3 总数未在本页预设。'}不能将小样本对照推广为效率或准确率优势。`);

s=base(9,'家庭照片如实呈现适用性限制','25 个图对，3 种成熟算法，共 75 次检测评估，0 FOUND');
table(s,[['目标与算法','匹配 / 内点','几何覆盖','结果'],['纸巾当前 B  ORB','15 / 3','0.0012','未确认'],['纸巾当前 B  SIFT','74 / 23','0.0391','未确认'],['保温杯  AKAZE','36 / 33','0.0342','未确认']],218,[420,250,240,242]);
tx(s,'匹配点多，也可能缺少足够的几何支持。',64,551,1152,55,32,colors.teal,true);
tx(s,'生产保留 ORB 和原阈值；家庭原图不进入公开材料。',64,612,1152,40,24,colors.muted);
note(s,'来源：docs/TEAM_PHOTO_EVALUATION.md、docs/evidence/p3-photos-summary.json。75 是同图片跨算法评估，其中24带目标评价和51无目标评价，不是75独立图片或泛化率。耳机壳参考图质量拒绝，钥匙/笔未确认，玻璃杯无正例。纸巾 SQLite moved/missing SUSPECTED/null，replay UNKNOWN。');

s=base(10,'可追溯的寻物软件闭环','材料与实际能力保持一致，下一步以补齐验证为优先');
tx(s,'已经实现',64,230,1120,55,35,colors.teal,true);
tx(s,'跨运行记忆、主动搜索、当前图像验证、重放保护\n逐步演示与证据报告、提交材料和打包校验',64,302,1152,115,30);
tx(s,'当前边界',64,464,1120,55,35,colors.amber,true);
tx(s,'家庭图片尚未确认，搜索效率尚未证明提升\n导航为模拟，真实机器人与端侧性能仍待验证',64,536,1152,100,29);
note(s,'来源：docs/submission/OPEN_SOURCE_AND_ORIGINALITY.md、MATERIALS_CHECKLIST.md、RUN_TEST_REPORT.md。技术说明书为 team_authored 自编材料，非官方模板。个人团队信息本地补充，最终ZIP需要材料完整、PM审核与解压核验，上传成功另需平台回执。');

const candidate=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(presentation)).save(candidate);
const final=path.join(outputDir,'HomeTrace_技术展示.pptx');
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,
  pythonExecutable:path.join(runtime,'python/python.exe'),
  integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[3,4,8,9].flatMap(n=>['--require-native-table-slide',String(n)])],
  requiredNativeTableOwnerSlides:[3,4,8,9],fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,
  receiptPath:path.join(build,'validation.json'),explicitTotalSlideCount:10});
for(let i=0;i<10;i++){
  const blob=await presentation.export({slide:presentation.slides.items[i],format:'png',scale:1});
  await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify({final,slides:10,previews:build}));
