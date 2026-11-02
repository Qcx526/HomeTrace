"""Author the current technical supplement, never an official application.

Run with the bundled document-authoring Python. Existing outputs are refused.
Facts are tied to the cited evidence, not inferred from test counts.
"""
import argparse
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


def build(output):
    if output.exists():
        raise ValueError('Existing material must not be overwritten')
    doc = Document()
    for style in doc.styles:
        for border in list(style.element.iter(qn('w:pBdr'))):
            border.getparent().remove(border)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2)
    sec.left_margin = sec.right_margin = Cm(2.2)
    for name in ('Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2', 'Caption'):
        st = doc.styles[name]
        st.font.name = 'Microsoft YaHei'
        st.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), 'Microsoft YaHei')
        st.font.color.rgb = RGBColor(0, 0, 0)
    normal = doc.styles['Normal']
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.2
    normal.paragraph_format.space_after = Pt(8)
    doc.styles['Title'].font.size = Pt(26)
    doc.styles['Heading 1'].font.size = Pt(17)
    doc.styles['Heading 2'].font.size = Pt(13)
    doc.core_properties.author = 'HomeTrace Team'
    doc.core_properties.title = 'HomeTrace 作品设计与技术说明书'
    doc.core_properties.subject = '2026 年 11 月 1 日开发版本技术补充'
    footer = sec.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run('HomeTrace  技术补充  ').font.size = Pt(8)
    f = OxmlElement('w:fldSimple'); f.set(qn('w:instr'), 'PAGE'); footer._p.append(f)

    def p(value): doc.add_paragraph(value)
    def h(value): doc.add_heading(value, 1)
    def sub(value): doc.add_heading(value, 2)
    def page(value): doc.add_page_break(); h(value)
    def table(headers, rows, widths):
        t = doc.add_table(rows=1, cols=len(headers)); t.autofit = False
        for c, width in zip(t.columns, widths): c.width = Cm(width)
        for c, value in zip(t.rows[0].cells, headers): c.text = value
        for row in rows:
            for c, value in zip(t.add_row().cells, row): c.text = value
        for r, row in enumerate(t.rows):
            for c, width in zip(row.cells, widths):
                c.width = Cm(width); c.vertical_alignment = 1
                props = c._tc.get_or_add_tcPr()
                shade = OxmlElement('w:shd'); shade.set(qn('w:fill'), '17324D' if r == 0 else ('F1F4F6' if r % 2 else 'FFFFFF')); props.append(shade)
                borders = OxmlElement('w:tcBorders')
                for side in ('top', 'left', 'bottom', 'right'):
                    e = OxmlElement('w:'+side)
                    for k,v in {'val':'single','sz':'4','color':'D9D9D9'}.items(): e.set(qn('w:'+k),v)
                    borders.append(e)
                props.append(borders)
                margins = OxmlElement('w:tcMar')
                for side in ('top','left','bottom','right'):
                    e=OxmlElement('w:'+side);e.set(qn('w:w'),'110');e.set(qn('w:type'),'dxa');margins.append(e)
                props.append(margins)
                for para in c.paragraphs:
                    para.paragraph_format.space_after=Pt(3)
                    for run in para.runs:
                        run.font.size=Pt(10);run.bold=r==0
                        run.font.color.rgb=RGBColor.from_string('FFFFFF' if r==0 else '000000')
        repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
        p('')

    doc.add_paragraph('HomeTrace', 'Title')
    doc.add_paragraph('作品设计与技术说明书', 'Subtitle')
    p('家庭物品记忆与主动寻找 Agent\n2026 年 11 月 1 日开发版本技术补充')
    h('作品概述')
    p('HomeTrace 面向家庭中“刚放下物品，过后找不到”的场景。主人登记物品外观并说明放置地点，系统保存带来源的位置记录；再次寻找时，LLM 查询历史、选择观察地点、读取实际工具反馈，并决定继续搜索、请求补图或请主人核对。最终结果连同照片来源和决策轨迹一起保留。')
    p('当前成果是可运行的软件 Demo：用户上传照片并选择地点，导航由程序模拟，候选由主人最终确认。持久记忆、真实模型工具调用和拒绝后继续寻找已分别验证；真实家庭照片的自动实例识别仍未通过独立验收。系统不会把模型意见或主人确认改写为自动视觉 FOUND。')
    h('作品贡献')
    p('我们的实现重点是让记忆、决策和证据形成可追溯流程。历史位置用于决定先找哪里，不能作为当前发现；当前照片必须独立处理。拒识、旧图重放和模型失败会进入状态与报告，而不是被隐藏为成功。')
    p('登记依赖已有视觉方法和参考外观，不要求主人为每件物品训练一个网络。LLM 负责目标与意图解析、工具选择和反馈决策，数据库、照片处理与确认写入由程序约束。')
    sub('成果范围')
    p('本说明书是技术补充，不能代替官方初赛主表。源码基于 PR #43 的 16445f7，交付集成在 Issue #44 独立分支完成；待审分支不能标为 main 已发布，候选材料不等于平台已提交。')

    page('应用场景与人机协作')
    sub('登记与记住')
    p('主人说“请记住，我的水杯放在这里了”。用户先登记名称、别名及参考图，框选目标区域；“这里”由页面所选地点解释。系统展示将保存的物品和地点，主人明确确认后才写入 SQLite。记录类型是主人陈述，而不是机器人自动观察。')
    sub('寻找与调整')
    p('主人说“水杯找不到了，帮我找一下”。Agent 查询最近位置，再调用模拟导航和当前照片观察。如果证据不足，会根据实际反馈选择其他已配置地点、请求补图或结束为 UNKNOWN。长期历史可作为线索，但当前没有经过验证的家庭习惯学习，也不声称会自动推断主人位置。')
    sub('核对与更新')
    p('本地外观候选或视觉顾问意见不能单独证明物理身份。主人查看参考与当前场景后，可确认或拒绝。确认保存为 USER_CONFIRMED／owner_reported；拒绝作为反馈交回 Agent。服务重启后仍能读取同一位置事件，重复确认不会重复写入。')
    table(['状态','含义','是否确认实例'],[
        ['UNKNOWN','没有足够证据，或观察不可用','否'],
        ['SUSPECTED','存在外观候选，等待核对','否'],
        ['USER_CONFIRMED','主人明确核对并保存位置','人工确认；非自动视觉确认'],
        ['模型 similar 意见','模型认为外观相似','否；不生成权威检测框'],
    ],[4.8,6.1,5.7])
    p('演示中的地点安排和物品搬移可以由软件素材编排，但必须标为软件场景；历史照片不能拼成现实中未发生的移动过程。')

    page('技术结构与可信执行')
    table(['组件','实际职责'],[
        ['本地页面与工作区','名称、参考 ROI、当前场景、地点配置与证据展示'],
        ['LangGraph 与 LangChain','运行状态、模型工具调用、条件分支与反馈循环'],
        ['LLM 决策层','理解请求、选择工具或地点、解释反馈，不创造权威事实'],
        ['SQLite 记忆层','保存物品与主人位置事件，跨进程读取、来源区分'],
        ['照片与视觉模块','本地 ORB 几何诊断；可选逐次授权的视觉顾问'],
        ['执行和验证层','校验工具参数、预算、地点、输入快照与确认权限'],
    ],[4.4,12.2])
    p('搜索核心与视觉、UI 和运动接口分离。本轮不重构 SearchCore，不引入 ROS 或真实机器人 SDK。自定义地点配置最多十处，每次运行冻结地点快照，后续配置变更不会重新解释旧会话；单次执行仍受原有工具与模型预算限制。')
    sub('图片与密钥保护')
    p('默认照片匹配在本地完成。可选视觉 Agent 必须在每次发送前列出接收端点与图片副本，取得明确批准后发送去元数据缩小图；完整场景背景仍可能包含隐私。上传本机不等于允许外发，已用授权不能重复消费。API Key 仅保存在本机，源码包排除私图、数据库、权重与真实密钥。')
    sub('失败处理')
    p('请求或模型输出失败会保留错误，不伪造工具调用；未配置照片的地点不能声称已经观察。参考/场景哈希与旧图保护避免重复证据被写成新发现。模型预算、超时和步骤上限限制执行，不依赖无限重试。')

    page('实际证据与未解决问题')
    p('下表引用已经保存的运行证据。不同阶段、分支和素材的结果分开报告，测试通过数不等于识别准确率。新的联合验证以随包运行报告为准。')
    table(['证据','实际结果','证明范围'],[
        ['PR #43 回归','1061 项 Python，22 项前端通过','该开发快照的软件回归'],
        ['空工作区流程','已有真实文本模型 HTTP 与浏览器操作证据','合成素材、模拟导航、脚本主人动作'],
        ['记忆重启','主人确认后保存，重启真实模型查询同一事件','持久记忆与来源语义'],
        ['新增八张实拍','6 正例中4相似意见、1不确定、1输出失败','开发诊断；不是实例召回'],
        ['同批两张负例','2 张均返回目标不可见','仅该样本结果'],
        ['同批本地 ORB','8 张均无有效定位框','真实定位能力仍未通过'],
    ],[3.8,6.2,6.6])
    p('同批视觉顾问实际执行八次调用，其中七次产生有效结构化意见，一次输出截断。没有重试补齐成功样本。图片没有人工审核的数值真值框，因此不能计算 IoU、正确定位率或实例 precision。全部是开发诊断数据。')
    p('历史 YOLOE 和专用模型训练属于隔离实验，未接入当前生产 FOUND。木纹背景误匹配、相似物、远距离小目标与遮挡仍是关键困难。类别检测或外观相似不能证明主人登记的同一实体。')
    p('当前没有证据证明家庭通用识别、真实机器人运动或普遍搜索效率提升。独立受限验收仍需冻结后另采两批至少6正8负：至少5/6正确定位且IoU≥0.5、8/8负例零误接受、实例precision≥0.95；零接受不能通过。')

    page('运行 复现与交付')
    sub('本地运行')
    p('Windows Python 3.11 及以上。建立新虚拟环境，安装项目的 dev、vision、vision-advisor、agent 可选依赖；在本机 .env 填写模型 Key，检查 config.yaml 的端点、模型和预算。不要把真实 .env 放入源码包。')
    p('启动：python -m hometrace demo --photo-agent --port 8770 --household-dir artifacts/my-home。打开 http://127.0.0.1:8770/。再次使用同一路径会恢复记忆；从零演示请选择新目录。逐次授权看图使用 --photo-vision-agent。')
    p('工作区 locations.json 可定义地点。登记名称、上传参考并审核 ROI 后，选择所在地点发送记住请求；配置当前场景再发起寻找。页面显示实际调用和工具反馈，确认按钮是必要的人工环节。')
    sub('软件验收')
    p('全量命令：python -m pytest -q。前端命令：node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs。真实 API 验收由 tools/accept_photo_workflow.py 显式启动，需要本地固定哈希合成素材；缺素材或 Key 不得记为成功。')
    sub('开源与原创性')
    p('复用 Python、SQLite、OpenCV ORB/Hamming/RANSAC、LangGraph、LangChain、Pillow 等成熟技术，许可证清单随源码提供。原创工作是家庭位置事件与当前观察分离、反馈驱动的工具流程、证据重放与确认保护，以及可追溯展示和工作区适配；不宣传为原创基础视觉算法。')
    sub('证据索引')
    p('源码中的 docs/DELIVERABLE_DEMO.md、REAL_CUP_AGENT_ACCEPTANCE.md、OWNER_MEMORY_RESTART_ACCEPTANCE.md、WORKSPACE_LOCATIONS_AND_NEW_PHOTOS.md 保存对应阶段事实。随包运行报告记录最新集成命令、结果与失败。官方主表、团队身份、媒体内容和赛事提交要求仍须最终人工核对。')
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
