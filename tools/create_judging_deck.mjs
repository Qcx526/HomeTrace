/** Build the judge-facing deck using a supplied PPTX template and local evidence.
 * All photographs, team inputs and generated materials stay in ignored directories.
 * Run with bundled Node, --artifact-module, --skill-dir, --python, --template,
 * --team, --output (new file), and --qa (new build directory).
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
const args={};for(let i=2;i<process.argv.length;i+=2)args[process.argv[i].replace(/^--/,'')]=process.argv[i+1];
for(const k of ['artifact-module','skill-dir','python','template','team','output','qa'])if(!args[k])throw Error(`Missing --${k}`);
const root=process.cwd(), qa=path.resolve(args.qa), output=path.resolve(args.output);
await fs.mkdir(qa,{recursive:false});await fs.mkdir(path.dirname(output),{recursive:true});
const {PresentationFile,FileBlob}=await import(pathToFileURL(path.resolve(args['artifact-module'])).href);
process.env.RUNTIME_NODE_MODULES ||= path.resolve(path.dirname(args['artifact-module']),'../../..');
const {finalizePresentation}=await import(pathToFileURL(path.join(args['skill-dir'],'container_tools/artifact_tool_utils.mjs')).href);
const team=JSON.parse(await fs.readFile(args.team,'utf8'));
const p=await PresentationFile.importPptx(await FileBlob.load(args.template));
if(p.slides.items.length!==4)throw Error('Expected reviewed four-slide school template');
const original=[...p.slides.items], body=original[1];
const slides=[original[0]];
for(let i=0;i<10;i++)slides.push(body.duplicate());
slides.push(original[3]);
const inspected=await p.inspect({kind:'slide',maxChars:100000});
const byRaw=new Map(inspected.records.map(r=>[p.resolve(r.id).id,r.id]));
p.slides.keep(slides.map(s=>byRaw.get(s.id)));p.slides.reorder(slides.map(s=>byRaw.get(s.id)));
const font='微软雅黑', blue='#194F96', ink='#25374B', muted='#586B7B';
function text(s,v,x,y,w,h,size=23,color=ink,bold=false,fill='none'){
 const sh=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill,line:{fill:'none',width:0}});
 sh.text=v;sh.text.style={typeface:font,fontSize:size,color,bold,wrap:'square',autoFit:'none',insets:0};return sh;
}
function title(s,v){text(s,v,70,23,590,58,32,blue,true,'#E8F3F5');}
function note(s,sources,scope=''){s.speakerNotes.text=`${scope}\n资料来源：\n${sources.join('\n')}\n照片和团队信息仅包含在本机提交材料，不进入公开代码仓库。`}
function paragraph(s,heading,body,x,y,w=810){text(s,heading,x,y,w,37,27,blue,true);text(s,body,x,y+48,w,75,22);}
async function picture(s,relative,x,y,w,h,crop){const b=await fs.readFile(path.join(root,relative));s.images.add({blob:b,contentType:'image/png',alt:'HomeTrace 实际执行记录画面',fit:'contain',position:{left:x,top:y,width:w,height:h},...(crop?{crop}:{} )});}
function cropRect(x,y,w,h,sw,sh){return {left:x/sw,top:y/sh,right:1-(x+w)/sw,bottom:1-(y+h)/sh};}
function table(s,values,widths,x,y,w,rowHeight=64){const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:values.length*rowHeight,columnWidths:widths,values});t.borders.assign({fill:'#CCD8E7',width:0.6,style:'solid'});for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){const ce=t.getCell(r,c);ce.fill=r===0?blue:r%2===0?'#EFF4FA':'#FFFFFF';ce.text.style={typeface:font,fontSize:r===0?21:20,color:r===0?'#FFFFFF':ink,bold:r===0,insets:{left:13,right:10,top:11,bottom:8},verticalAlignment:'middle',wrap:'square'};}return t;}
const latest='docs/REAL_CUP_FRESH_WORKFLOW_20261102.md', evidence='docs/evidence/issue-46-new-photos/workflow.json', demo='docs/DELIVERABLE_DEMO.md';
let s=slides[0];
text(s,'HomeTrace',80,178,800,78,54,blue,true);
text(s,'基于位置记忆与反馈决策的\n家庭寻物 Agent',83,267,790,94,33,blue,true);
text(s,`${team.team.name}    电子科技大学`,84,375,790,38,22,ink);
note(s,[demo,latest],'课题正式名称以官方主表为准。本展示为本地软件 Demo，移动过程模拟，真实照片由主人提供，物品身份由主人确认。');
s=slides[1];title(s,'家庭里的两句话');
text(s,'“钥匙我放这里了，帮我记住。”',76,152,810,57,33,blue,true);
text(s,'登记物品外观和放置地点，保留主人确认的记录。',78,224,806,51,23);
text(s,'“我找不到了，帮我找一下。”',76,324,810,57,33,blue,true);
text(s,'先查最近的位置，再根据眼前的情况继续寻找。',78,397,806,51,23);
note(s,[demo],'本页为用户交互示意，非模型原始逐字响应。地点由主人提供，系统没有自动定位主人。');
s=slides[2];title(s,'一次寻物怎样完成');
const steps=[['1  记住物品','主人提供参考照片，确认它的名称和放置地点。'],['2  先查记忆','助手读取最近记录，选择优先检查的位置。'],['3  看清再判断','根据当前照片换地点、请求近景，或请主人核对。'],['4  保存新线索','主人确认后保存位置历史，下次寻找可以继续使用。']];
steps.forEach((r,i)=>{text(s,r[0],76,132+i*82,205,38,25,blue,true);text(s,r[1],292,134+i*82,595,58,22)});
note(s,[demo,latest],'当前照片由主人上传。历史记录只用于优先寻找，不保证物品现在仍在那里。多物品可分别建档，本轮实拍完成单水杯流程。');
s=slides[3];title(s,'助手如何作出下一步决定');
table(s,[['组成','负责什么','实际执行方式'],['位置记忆','回答以前在哪里','保存地点、来源和确认记录'],['语言模型','选择下一步行动','读取反馈后调用查询、观察或求助'],['观察与核对','检查现在的线索','比较照片，必要时请求主人确认'],['执行记录','解释为什么这样找','保留每次操作和返回结果']],[180,280,348],76,132,808,59);
text(s,'演示中的移动由软件模拟，照片观察和工具调用由程序实际执行。',78,447,806,42,18,muted);
note(s,[demo,latest,evidence],'内部使用 LangGraph、LangChain、SQLite 与既有视觉模块。模型不能凭文字制造到达、位置或视觉确认事实。');
s=slides[4];title(s,'钥匙演示：记住后，再去寻找');
await picture(s,'artifacts/issue-44/browser-01/07-actual-candidate.png',74,149,582,250,cropRect(505,644,844,332,1440,1080));
text(s,'先检查历史位置',691,158,207,40,23,blue,true);text(s,'原处未见后，\n继续查看新地点。',691,210,207,73,21);
text(s,'出现候选后核对',691,309,207,40,23,blue,true);text(s,'画面对照参考，\n主人确认后保存。',691,360,207,73,21);
text(s,'钥匙软件示例（合成场景）    实际匹配结果与操作画面',77,426,798,37,18,muted);
note(s,['artifacts/issue-44/browser-01/07-actual-candidate.png','artifacts/issue-44/browser-01/browser-checks.json',demo],'截图来自实际本地浏览器运行。钥匙及场景为软件测试合成素材，不能当作家庭实拍识别结果。裁剪只突出已有参考图和实际匹配框，未绘制新检测框。');
s=slides[5];title(s,'水杯实拍：原处没有，换处找');
await picture(s,'artifacts/cup-video-20261103/frames-01/03.png',76,129,491,330,cropRect(444,198,647,485,1912,905));
text(s,'原位置未见后',608,145,289,40,26,blue,true);text(s,'助手根据观察结果，\n转到另一处桌面继续检查。',608,201,289,85,23);
text(s,'杂物多，目标较小',608,326,289,40,26,blue,true);text(s,'全景信息不足时，\n继续获取更清楚的观察。',608,382,289,78,23);
note(s,[latest,evidence,'artifacts/cup-video-20261103/frames-01/03.png'],'真实照片任务回看。配置顺序不是历史优先，模型实际依据主人历史选择原位置，再转查另一地点。导航模拟。截图来自已完成执行记录，没有重新发送图片。');
s=slides[6];title(s,'水杯实拍：补近景，请主人核对');
await picture(s,'artifacts/cup-video-20261103/frames-01/05.png',76,129,491,330,cropRect(444,198,647,485,1912,905));
text(s,'看清杯身细节',608,145,289,40,26,blue,true);text(s,'近景显示图案、杯盖\n与底圈等外观特征。',608,201,289,85,23);
text(s,'交给主人作最后核对',608,326,289,40,25,blue,true);text(s,'主人确认是同一只杯子，\n并同意保存照片位置历史。',608,382,289,78,22);
note(s,[latest,evidence,'artifacts/cup-video-20261103/frames-01/05.png'],'模型真实返回外观相似并请求主人核对。身份与地点历史来自负责人明确授权，工程师按授权通过 HTTP 保存，未声称主人当时点击此回看页面。没有可靠自动检测框，未展示虚构框。');
s=slides[7];title(s,'记忆保存之后');
paragraph(s,'重新打开，记录仍在','服务重启后，再次询问水杯位置，系统读回刚才保存的同一条历史。',76,144);
paragraph(s,'旧照片不会变成新发现','再次使用已经看过的照片时，系统拒绝重复记忆，也不会再次发送照片。',76,296);
text(s,'历史位置提供下一次搜索线索，当前是否还在那里仍需重新观察。',78,447,806,45,19,muted);
note(s,[latest,evidence],'新进程实际恢复同一 owner_reported 事件，恰好新增一条，visual_confirmed=false。旧图 S1/S2 拒绝重放，无外发和新写入。');
s=slides[8];title(s,'这次实拍验证了什么');
table(s,[['实际情况','系统的处理'],['原位置没有水杯','转查另一处桌面'],['远景细节不够','请求补充近景'],['近景外观相似','请主人核对，再保存记录'],['相似杯与空场景','保留未确认，不保存新位置'],['重启及旧图再次使用','读回历史，阻止重复写入']],[341,467],76,122,808,55);
text(s,'本轮为单水杯协作流程验证，结果不等同于家庭物品的通用识别准确率。',78,463,806,38,17,muted);
note(s,[latest,evidence],'前3项来自实际主搜索链，相似杯/空场景来自独立控制会话，重启和旧图来自各自执行记录。没有独立真值框/IoU或新的独立识别测试集。');
s=slides[9];title(s,'作品的设计重点');
paragraph(s,'让记忆成为可用的搜索线索','记录物品与地点之间的联系，并保留来源。历史信息参与下一步选择。',76,127);
paragraph(s,'观察不足时，主动补充信息','找不到就换地点，看不清就请求近景，无法确认就请主人参与。',76,248);
paragraph(s,'让每次寻找留下可以复用的记录','确认后的地点进入长期保存，下次查询能够追溯到当时的照片与说明。',76,369);
note(s,[demo,latest],'创新重点为产品流程、反馈决策和有来源记忆。使用成熟开源方法与外部模型服务，不宣称原创基础视觉算法，也没有证据宣称普遍搜索效率提升。');
s=slides[10];title(s,'当前交付与后续方向');
text(s,'当前没有机器人，以软件演示流程',76,133,810,42,27,blue,true);
text(s,'主人提供实拍照片，系统按记忆和反馈寻找。\n移动由软件模拟，核对后保存并支持重启查询。',78,191,806,86,23);
text(s,'后续加入语音与具身机器人',76,303,810,42,27,blue,true);
text(s,'语音：直接说出记住或寻找请求，保留歧义确认。\n机器人：全屋建图与定位后，按地点逐步搜索。',78,363,806,80,22);
text(s,'需接入相机、避障导航与真实到达回执，再验证全屋自主搜索。',78,456,806,36,18,muted);
note(s,[latest,demo],'语音识别、语音回复、全屋建图、真实定位与导航均为后续计划，当前未实现或验收。接入具身机器人并不自动等于具备人类水平，需要设备适配与真实环境测试。当前为主人提供照片、模拟移动、人机协作确认的本地软件 Demo。自动特定物理实例识别、可靠框及真机运行未通过独立验收。照片进入外部视觉服务需要明确授权，私人图、身份信息和密钥不进入公共GitHub。');
s=slides[11];
text(s,'HomeTrace',74,52,812,58,41,blue,true);
text(s,'基于位置记忆与反馈决策的家庭寻物 Agent',76,111,810,35,23,ink);
text(s,team.team.name+'    电子科技大学',76,438,810,38,22,ink);
note(s,[demo,latest],'采用用户提供的电子科技大学蓝色模板，保留校徽、背景和结尾页原图。');
const draft=path.join(qa,'draft.pptx');await(await PresentationFile.exportPptx(p)).save(draft);
await fs.mkdir(path.join(qa,'renders'));
for(const [i,slide] of p.slides.items.entries()){await fs.writeFile(path.join(qa,'renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await(await p.export({slide,format:'png',scale:1.5})).arrayBuffer()));await fs.writeFile(path.join(qa,'renders',`slide-${i+1}.json`),await(await slide.export({format:'layout'})).text());}
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const result=await finalizePresentation({workspaceDir:root,candidatePath:draft,finalPath:output,pythonExecutable:args.python,integrityValidatorPath:path.join(args['skill-dir'],'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(args['skill-dir'],'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','9144000,5140325','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','4','--require-native-table-slide','9'],explicitTotalSlideCount:12,requiredNativeTableOwnerSlides:[4,9],fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,receiptPath:path.join(qa,'validation.json')});
await fs.writeFile(path.join(qa,'provenance.json'),JSON.stringify({created:'2026-11-03',slide_count:12,source_template_sha256:sha(await fs.readFile(args.template)),final_sha256:sha(await fs.readFile(output)),template_slides_used:[1,2,4],private_submission_only:true,external_model_calls:0,key_source:'synthetic software fixture, actual execution screenshot',cup_source:'actual completed task review, owner confirmation',full_slide_render_count:12,finalizer:result},null,2));
console.log(JSON.stringify({output,slide_count:12,sha256:sha(await fs.readFile(output))}));
