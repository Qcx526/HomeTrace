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
    doc.core_properties.subject = '2026 年 11 月 2 日实拍流程开发版本技术补充'
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
    p('家庭物品记忆与主动寻找 Agent\n2026 年 11 月 2 日实拍流程开发版本技术补充')
    h('作品概述')
    p('HomeTrace 面向家庭中“刚放下物品，过后找不到”的场景。主人登记物品外观并说明放置地点，系统保存带来源的位置记录；再次寻找时，LLM 查询历史、选择观察地点、读取实际工具反馈，并决定继续搜索、请求补图或请主人核对。最终结果连同照片来源和决策轨迹一起保留。')
    p('当前已完成受限的单水杯软件 Demo：真实 LLM 先查历史地点，读取未见目标反馈后换地点，因远景不确定请求近景，再请求主人核对；主人授权保存后，重启仍能查到同一位置事件，旧图再次搜索被拒绝。导航由程序模拟，照片由主人提供；本轮未完成自动实例识别或可靠检测框验收。')
    h('作品贡献')
    p('我们的实现重点是让记忆、决策和证据形成可追溯流程。历史位置用于决定先找哪里，不能作为当前发现；当前照片必须独立处理。拒识、旧图重放和模型失败会进入状态与报告，而不是被隐藏为成功。')
    p('登记依赖已有视觉方法和参考外观，不要求主人为每件物品训练一个网络。LLM 负责目标与意图解析、工具选择和反馈决策，数据库、照片处理与确认写入由程序约束。')
    sub('成果范围')
    p('本说明书是技术补充，不能代替官方初赛主表。能力基线为 PR #47 的 537aa9c；实拍执行代码为 cd75a52，后续仅增加可复现配置与证据。当前材料分支依赖未合并 PR，具体源码快照以包内 SOURCE_INFO.json 为准。团队信息由负责人填写，材料审阅包不等于平台已提交。')

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
    p('实拍验收中的 H 是主人曾记录的地点，B 是本次照片地点，均以脱敏代号展示。拍摄时间未知；两个地点的照片不能拼成现实连续搬动或机器人自动巡航记录。既有合成钥匙录屏只验证软件交互，和本轮实拍证据分别说明。')

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
    p('默认照片匹配在本地完成。可选视觉 Agent 在发送前核验已批准的端点、图片哈希和次数，仅发送去元数据缩小副本；完整背景仍可能包含隐私。本轮使用已授权的第三方兼容网关，不能据模型名称确认底层服务商。上传本机不等于允许外发，额度不可重置。API Key 仅存本机，交付源码排除私图、数据库、权重与真实密钥。')
    sub('失败处理')
    p('请求或模型输出失败会保留错误，不伪造工具调用；未配置照片的地点不能声称已经观察。参考/场景哈希与旧图保护避免重复证据被写成新发现。模型预算、超时和步骤上限限制执行，不依赖无限重试。')

    page('五张实拍照片的实际结果')
    p('2026 年 11 月 2 日，负责人提供五张新实拍照片。下面列出全部样本；S4、S5 单独运行负例控制，没有将它们编入同一条搜索链。照片角色来自主人说明，没有人工数值真值框，不能计算 IoU、正确定位率或实例 precision。')
    table(['照片与角色','ORB 匹配／内点','视觉建议','实际处理'],[
        ['S1 原位置无目标','14／0','not_visible','先查 H，再转 B'],
        ['S2 新位置全景','15／4','uncertain','请求同地点近景'],
        ['S3 同位置近景','18／5','similar','请求主人核对'],
        ['S4 相似杯负例','13／4','not_visible','UNKNOWN，无写入'],
        ['S5 空场景','9／0','not_visible','UNKNOWN，无写入'],
    ],[4.0,3.5,3.2,5.9])
    p('本地 ORB 五张均无合格 bbox。S1 至 S4 因几何内点不足拒绝，S5 因有效匹配不足拒绝。视觉顾问没有生成权威检测框；近景的相似建议只支持请求人工核对，不证明自动识别了同一物理实例。')
    sub('一次失败和一次完整复跑')
    p('首轮文本预算 24,000 Token。Agent 已检查 H、B 并请求近景，下一次文本决策因输入上界超过剩余额度被拦截，返回 BUDGET_EXCEEDED，零新记忆。该失败及近景、负例控制均保留，没有用成功复跑覆盖。')
    p('获得新的图片授权后，仅将文本总预算改为 32,000，保持模型、视觉判据、超时、零重试和其他调用上限不变。第二轮主流程完成：8 次文本调用共 20,001 Token，3 次视觉调用共 10,068 Token。两批合计 8 次视觉调用，分别受 5 次和 3 次授权约束，授权均已用完。')
    p('第二轮视觉耗时分别约 10.7、33.6、11.2 秒，属于本次实际测量，不能作为稳定性能承诺。云端输出和耗时会波动；预算增加不是检测准确率提升。')

    page('流程验收与能力边界')
    p('第二轮保存、重启查询与旧图保护共 9 项实际执行检查通过。配置中 B 位于 H 前，LLM 仍按历史先查 H，证明本例搜索顺序确实受记忆影响；没有因此宣称普遍提高搜索效率。')
    table(['检查环节','本轮实际结果'],[
        ['反馈决策','原处未见后换地点，远景不确定后请求近景'],
        ['身份核对','相似建议后请求主人核对，不自动 FOUND'],
        ['记忆保存','按主人明确授权执行 HTTP 确认，恰好新增 1 条 owner_reported'],
        ['服务重启','新进程恢复同一事件，真实 LLM 查到新照片位置历史'],
        ['旧图重放','原 S1／S2 被拒绝，零视觉外发、零重复事件'],
        ['软件回归基线','PR #47：1137 项 Python 与 28 项前端通过'],
    ],[4.4,12.2])
    p('确认由工程师依据负责人明确授权通过 HTTP 执行；不是本轮主人亲自点击网页的新浏览器验收。前端回归通过不能替代实际点击录像，随包合成钥匙录屏标注其独立来源。最新材料集成测试及环境检查见随包运行报告。')
    p('限制仍包括：只有一件水杯的受限流程完成；远景需补近景；本地定位无合格框；没有独立实例测试、真实机器人运动或长期习惯学习证据。历史 YOLOE 与专用训练仍为隔离实验，未接入生产 FOUND。')
    p('若要验收自动实例定位，算法冻结后仍需另采至少两批共 6 正例、8 负例：至少 5/6 正确定位且 IoU≥0.5，8/8 负例零误接受，实例 precision≥0.95；零接受不能通过。本轮材料以真实完成的主人参与流程为边界，不等待更多照片才展示现有软件成果。')

    page('运行 复现与交付')
    sub('本地运行')
    p('Windows Python 3.11 及以上。建立新虚拟环境，安装项目的 dev、vision、vision-advisor、agent 可选依赖；在本机 .env 填写模型 Key。真实看图演示检查 config.photo-demo.yaml 的第三方端点、模型和预算；不要把真实 .env 放入源码包。')
    p('启动：python -m hometrace demo --photo-vision-agent --config config.photo-demo.yaml --port 8770 --household-dir artifacts/my-home。打开 http://127.0.0.1:8770/。再次使用同一路径会恢复记忆；从零演示请选择新目录。发送图片前仍需新的明确授权。')
    p('工作区 locations.json 可定义地点。登记名称、上传参考并审核 ROI 后，选择所在地点发送记住请求；配置当前场景再发起寻找。页面显示实际调用和工具反馈，确认按钮是必要的人工环节。')
    sub('软件验收')
    p('全量命令：python -m pytest -q。前端命令：node --test tests/test_photo_flow_client.cjs tests/test_photo_agent_client.cjs tests/test_visual_photo_agent_client.cjs。真实 API 验收由 tools/accept_photo_workflow.py 显式启动，需要本地固定哈希合成素材；缺素材或 Key 不得记为成功。')
    sub('开源与原创性')
    p('复用 Python、SQLite、OpenCV ORB/Hamming/RANSAC、LangGraph、LangChain、Pillow 等成熟技术，许可证清单随源码提供。原创工作是家庭位置事件与当前观察分离、反馈驱动的工具流程、证据重放与确认保护，以及可追溯展示和工作区适配；不宣传为原创基础视觉算法。')
    sub('证据索引')
    p('本轮事实见源码 docs/REAL_CUP_FRESH_WORKFLOW_20261102.md 及 docs/evidence/issue-46-new-photos/。旧轮次保留在原报告，未覆盖。随包 RUN_TEST_REPORT.md 记录材料集成命令、结果及失败；SOURCE_INFO.json 标明打包源码快照。')
    p('官方主表当前只填写课题与说明，身份字段由负责人补全。上传前应人工核对官方截止时刻、格式、大小、必选附件和团队信息，逐项打开解压文件；官方规则说明 PDF 不进入包。尚未完成这些核验，也尚未上传比赛平台。')
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
