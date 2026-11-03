"""Build the local competition report inside the retained official DOCX.

Private fields are inputs, never embedded in this public authoring tool.
The official application table and its geometry remain authoritative.  The
generic contest guidance after that table is replaced by the team's paper.
Use the bundled document-authoring Python, not the application environment.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from hometrace.official_submission import (
    FIELDS, NS, W, OfficialFormError, _clear_editable, _original_rows,
    _package, _text, digest, fill_official, validate_content,
)

REL='http://schemas.openxmlformats.org/package/2006/relationships'
IMAGE_REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'


def verify_added_images(a, b, body):
    """Permit only hash-named, internally referenced PNG/JPEG figure additions."""
    extra=set(b)-set(a)
    if set(a)-set(b):raise OfficialFormError('Original package parts removed')
    if not extra:
        for part in ('word/_rels/document.xml.rels','[Content_Types].xml'):
            if a.get(part)!=b.get(part):raise OfficialFormError('Preserved package metadata changed without figures')
        return 0
    for name in extra:
        m=re.fullmatch(r'word/media/ht-([a-f0-9]{64})\.(png|jpg)',name)
        if not m or hashlib.sha256(b[name]).hexdigest()!=m[1]:
            raise OfficialFormError('Unexpected or changed figure part')
        from hometrace.photo_flow_service import _dimensions
        try:w,h,ext=_dimensions(b[name])
        except ValueError as exc:raise OfficialFormError('Invalid figure format') from exc
        if ext!=m[2] or min(w,h)<32 or w*h>24_000_000:
            raise OfficialFormError('Invalid figure dimensions')
        # Header dimensions bound allocations, but cannot establish that the
        # picture is readable. Verify the container and decode every pixel.
        try:
            from PIL import Image
        except ImportError as exc:
            raise OfficialFormError('Pillow is required to validate report figures') from exc
        try:
            with Image.open(BytesIO(b[name])) as image:
                if image.format != {'png': 'PNG', 'jpg': 'JPEG'}[ext] or image.size != (w,h):
                    raise ValueError('Figure format or dimensions differ')
                image.verify()
            with Image.open(BytesIO(b[name])) as image:
                image.load()
        except (OSError, ValueError, SyntaxError) as exc:
            raise OfficialFormError('Figure cannot be fully decoded') from exc
    rel_name='word/_rels/document.xml.rels'
    if rel_name not in a or rel_name not in b:
        if extra:raise OfficialFormError('Figure relationships missing')
        return 0
    old,new=ET.fromstring(a[rel_name]),ET.fromstring(b[rel_name])
    old_ids={x.get('Id') for x in old};new_ids=[x.get('Id') for x in new]
    if len(new_ids)!=len(set(new_ids)):raise OfficialFormError('Duplicate relationship ID')
    added=[x for x in new if x.get('Id') not in old_ids]
    if [ET.tostring(x) for x in new if x.get('Id') in old_ids]!=[ET.tostring(x) for x in old]:
        raise OfficialFormError('Original relationships changed')
    targets=set();ids=set()
    for item in added:
        if (item.tag!='{'+REL+'}Relationship' or set(item.attrib)!={'Id','Type','Target'}
            or item.get('Type')!=IMAGE_REL or not re.fullmatch(r'htImage[0-9]+',item.get('Id',''))
            or 'word/'+item.get('Target','') not in extra):
            raise OfficialFormError('Only internal figure relationships may be added')
        targets.add('word/'+item.get('Target'));ids.add(item.get('Id'))
    embeds={x.get('{'+R+'}embed') for x in body.iter() if x.get('{'+R+'}embed')}
    if targets!=extra or not ids<=embeds:
        raise OfficialFormError('Unreferenced figure or relationship')
    if any(x.get('{'+R+'}link') for x in body.iter()):
        raise OfficialFormError('External image links are forbidden')
    old_ct,new_ct=ET.fromstring(a['[Content_Types].xml']),ET.fromstring(b['[Content_Types].xml'])
    originals=[ET.tostring(x) for x in old_ct]
    retained=[]
    for x in new_ct:
        if ET.tostring(x) in originals:retained.append(ET.tostring(x));continue
        if (x.tag!='{'+CT+'}Default' or set(x.attrib)!={'Extension','ContentType'}
            or (x.get('Extension'),x.get('ContentType')) not in {('png','image/png'),('jpg','image/jpeg')}
            or not any(p.endswith('.'+x.get('Extension')) for p in extra)):
            raise OfficialFormError('Unexpected content type addition')
    if retained!=originals:raise OfficialFormError('Original content types changed')
    return len(extra)


def confirmed_fields(fields):
    """Validate supplied identity without asserting competition-platform access."""
    if not isinstance(fields, dict):
        raise OfficialFormError("Official fields must be an object")
    result = deepcopy(fields)
    # This authoring contract accepts an owner's supplied identity, while the
    # packaging contract separately retains platform_identity_verified=false.
    result["identity_confirmed"] = True
    validate_content(result)
    return result


def verify_report_table(original, report, expected_sha256, fields):
    """Check the unmodified official table plus exact supplied field values.

    Unlike verify_filled, this explicitly permits a paper after the first
    official table.  It does not relax that function or certify an upload.
    All errors avoid exposing private field values.
    """
    values = confirmed_fields(fields)
    original, report = Path(original), Path(report)
    if original.resolve() == report.resolve():
        raise OfficialFormError("Template and report must differ")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or digest(original) != expected_sha256:
        raise OfficialFormError("Original template hash differs")
    a, b = _package(original), _package(report)
    ar, at, rows_a = _original_rows(a)
    br = ET.fromstring(b["word/document.xml"])
    body_a, body_b = ar.find("w:body", NS), br.find("w:body", NS)
    tables = body_b.findall("w:tbl", NS)
    if not tables:
        raise OfficialFormError("Report is missing official table")
    bt = tables[0]
    rows_b = bt.findall("w:tr", NS)
    count = len(values["members"])
    if len(rows_b) != 5 + count:
        raise OfficialFormError("Official member row count differs")
    expected = [values[k] for k in ("team_name", "project_name", "description")]
    actual = []
    for row in rows_b[:3]:
        cells = row.findall("w:tc", NS)
        if len(cells) != 2:
            raise OfficialFormError("Official field structure differs")
        actual.append(_text(cells[1]))
    for i, person in enumerate(values["members"]):
        expected.extend(person[k] for k in FIELDS)
        actual.extend(_text(c) for c in rows_b[4+i].findall("w:tc", NS)[1:])
    if actual != expected:
        raise OfficialFormError("Report identity or project fields differ")
    for row in rows_a[4+count:7]:
        at.remove(row)
    _clear_editable(at.findall("w:tr", NS), count)
    _clear_editable(rows_b, count)
    if ET.tostring(at) != ET.tostring(bt):
        raise OfficialFormError("Official table labels, grid or formatting changed")
    # The official heading before the table, and all opaque template parts,
    # remain unchanged. Only document XML and added paper styles are editable.
    a_before = list(body_a)[:list(body_a).index(at)]
    b_before = list(body_b)[:list(body_b).index(bt)]
    if [ET.tostring(x) for x in a_before] != [ET.tostring(x) for x in b_before]:
        raise OfficialFormError("Official heading changed")
    figures=verify_added_images(a,b,body_b)
    allowed = {"word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"}
    if any(a[k] != b[k] for k in a if k not in allowed):
        raise OfficialFormError("Preserve-only package part changed")
    old_styles = ET.fromstring(a["word/styles.xml"])
    new_styles = ET.fromstring(b["word/styles.xml"])
    old_by_id = {x.get(f"{{{W}}}styleId"): ET.tostring(x) for x in old_styles if x.tag == f"{{{W}}}style"}
    new_by_id = {x.get(f"{{{W}}}styleId"): ET.tostring(x) for x in new_styles if x.tag == f"{{{W}}}style"}
    if any(new_by_id.get(k) != v for k, v in old_by_id.items()):
        raise OfficialFormError("Existing template styles changed")
    text = "".join(br.itertext())
    return {
        "status": "OFFICIAL_TABLE_AND_PAPER_VERIFIED",
        "official_table_unchanged_except_filled_fields": True,
        "preserve_only_parts_unchanged": True,
        "template_sha256": expected_sha256,
        "report_sha256": digest(report),
        "description_characters": len(values["description"]),
        "member_count": count,
        "paper_tables": len(tables)-1,
        "embedded_figures": figures,
        "text_characters": len(text),
        "identity_source": "owner_supplied",
        "platform_identity_verified": False,
        "visual_review": "REQUIRED_SEPARATELY",
        "uploaded": False,
    }


def make_paper(figures=None):
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    for name, size, bold, after in (
        ("HTBody", 11, False, 7), ("HTTitle", 20, True, 15),
        ("HTH1", 16, True, 12), ("HTH2", 12, True, 8),
        ("HTCaption", 10, False, 7), ("HTCell", 9.5, False, 2),
        ("HTReference", 9.5, False, 8),
    ):
        style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = "Times New Roman"
        style.font.size = Pt(size)
        style.font.bold = bold
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体" if not bold else "黑体")
        pf = style.paragraph_format
        pf.line_spacing = 1.35 if name == "HTBody" else 1.2
        pf.space_after = Pt(after)
        pf.widow_control = True
        if name in {"HTTitle", "HTH1", "HTH2", "HTCaption"}:
            pf.keep_with_next = True
        if name == "HTBody":
            pf.first_line_indent = Pt(22)
    def p(text, style="HTBody"):
        return doc.add_paragraph(text, style)
    def h(text):
        return p(text, "HTH2")
    def figure(name,caption,width=14.5):
        para=p('', 'HTBody');para.paragraph_format.first_line_indent=Pt(0)
        para.paragraph_format.keep_with_next=True;para.alignment=1
        image=para.add_run().add_picture(str(Path(figures)/name),width=Cm(width))
        image._inline.docPr.set('descr',caption)
        cap=p(caption,'HTCaption');cap.alignment=1;cap.paragraph_format.keep_with_next=False
    def page(title):
        para=p(title,"HTH1")
        para.paragraph_format.page_break_before=True
    def table(caption, headers, rows, widths):
        p(caption,"HTCaption")
        t=doc.add_table(rows=1, cols=len(headers));t.autofit=False
        for c,w in zip(t.columns,widths): c.width=Cm(w)
        for c,text in zip(t.rows[0].cells,headers): c.text=text
        for row in rows:
            for c,text in zip(t.add_row().cells,row): c.text=text
        for i,row in enumerate(t.rows):
            for c,w in zip(row.cells,widths):
                c.width=Cm(w);c.vertical_alignment=1
                props=c._tc.get_or_add_tcPr()
                b=OxmlElement("w:tcBorders")
                for side in ("top","left","bottom","right"):
                    v=OxmlElement("w:"+side)
                    for k,val in {"val":"single","sz":"4","color":"D9D9D9"}.items():v.set(qn("w:"+k),val)
                    b.append(v)
                props.append(b)
                sh=OxmlElement("w:shd");sh.set(qn("w:fill"),"E6EDF4" if i==0 else "FFFFFF");props.append(sh)
                pad=OxmlElement("w:tcMar")
                for side in ("top","left","bottom","right"):
                    v=OxmlElement("w:"+side);v.set(qn("w:w"),"90");v.set(qn("w:type"),"dxa");pad.append(v)
                props.append(pad)
                for para in c.paragraphs:
                    para.style=doc.styles["HTCell"]
                    for run in para.runs:run.bold=i==0
        repeat=OxmlElement("w:tblHeader");t.rows[0]._tr.get_or_add_trPr().append(repeat)
        p("", "HTCaption")

    page("HomeTrace 作品设计与实现")
    p("基于位置记忆与反馈决策的家庭寻物 Agent", "HTTitle")
    h("摘  要")
    p("家庭寻物的困难不仅在于识别物品，也在于记住物品曾经在哪里，并在原处未见时继续寻找。本文设计并实现 HomeTrace 家庭寻物原型，将物品参考外观、带来源的位置记忆、语言模型工具决策及主人核对组织为一个可运行流程。系统以本地数据库保存登记与位置事件，以智能体读取历史并调用导航、观察、补图和确认工具；当前观察与历史记录分开处理，避免将过往位置直接回答为当前发现。")
    p("软件样例用于验证从登记到再次查询的操作过程，团队水杯实拍用于检验复杂桌面条件下的反馈决策。在实拍实验中，系统先检查历史地点，原处未见后转查另一地点，因全景信息不足请求近景，随后请求主人核对。经主人授权保存后，新进程能够恢复并查询同一条照片位置历史，旧图重复输入未造成新的确认记录。三个目标缺席场景均未产生位置写入。")
    p("现阶段完成的是主人参与确认的单物品软件演示：导航由程序模拟，场景照片由主人提供，物品身份由主人最终确认。局部特征方法在本次五张实拍图上未得到合格定位框。本文因此将评价重点放在反馈是否改变行动、证据是否可追溯和记忆是否正确保存，而不将流程完成等同于家庭通用识别能力。")
    p("关键词  家庭寻物；位置记忆；智能体；反馈决策；人机协作；证据追溯", "HTBody")
    h("报告内容")
    p("正文依次说明问题与需求、系统结构、记忆和决策方法、视觉处理、两类演示及实验结果，最后讨论实现条件与后续接入方式。主办方要求的项目与团队信息保留在前页原表中。")

    page("1 绪论")
    h("1.1 问题背景")
    p("钥匙、杯子和耳机等随身物品经常在不同桌面之间移动。主人可能记得自己曾经放下过物品，却难以回忆具体地点；即使找到上次记录，物品也可能已经被再次移动。固定地点提醒只能回答历史信息，单张图像识别则缺少下一步搜索的依据。家庭寻物需要把时间、地点、外观和后续观察联系起来。")
    p("本文关注的情景是主人愿意提供一次登记参考，并在需要时与系统配合观察。系统应在登记时清楚说明记住了什么，在寻找时说明为什么先去某个地点，遇到遮挡或模糊图像时请求更有效的观察。错误地声称已经找到，会让主人反复检查错误位置，因此保留未确认结果是交互设计的一部分。")
    h("1.2 研究目标与作品定位")
    p("HomeTrace 的目标是实现记忆驱动的主动寻物流程。本文中的 Agent 指能够根据当前状态选择并调用工具的智能体，不是只生成一段回答的聊天界面。语言模型负责选择下一项动作，工具负责返回真实执行结果，保存规则负责决定哪些信息可以进入长期记忆。")
    p("初赛原型以本地软件代替机器人主体。主人选择地点并提供照片，模拟导航表达地点之间的搜索顺序。这种实现方式使寻物决策、记忆恢复和用户确认可以先被验证，同时保留未来连接摄像头与移动底盘的接口。本文不把模拟到达作为真实移动测试。")
    h("1.3 主要工作")
    p("本作品完成了三项相互衔接的实现。首先，建立带来源的位置事件，使主人陈述与当前观察各自保留。其次，让智能体在执行后读取反馈，能够换地点、请求近景或请求核对。最后，将照片、动作和确认记录关联起来，并检验重启恢复与重复图像保护。视觉部分复用成熟方法，作品的主要贡献是面向家庭寻物的流程组织与可信记忆机制。")

    page("2 相关技术与方案选择")
    h("2.1 语言模型与工具协作")
    p("工具调用使语言模型能够从外部系统获取信息，再调整后续行动。ReAct 研究讨论了推理与行动交替执行的方式[1]。HomeTrace 采用类似的反馈组织思路，但不把模型产生的描述作为实际事件；只有工具返回的数据库记录、观察结果和确认动作才改变任务状态。")
    p("实现采用 LangGraph 管理状态和条件分支，并通过 LangChain 的模型与工具接口对接服务。该框架支持将确定性步骤与模型决策放在同一状态流程中[2]。本项目保留确定性的离线路径用于回归检查，真实模型不可用时说明原因，避免把离线结果伪装成在线执行。")
    h("2.2 参考外观与局部特征")
    p("登记时保存参考图与目标区域，不需要为每件物品启动训练。局部特征方法从图像中提取关键点与描述子，并寻找相互对应的图案。ORB 结合方向关键点和二进制描述，适合构建较轻的本地基线[3]；匹配后还需通过几何估计排除不一致的对应[4]。本项目在完整场景图上寻找候选，不以人工已知目标坐标裁剪搜索区域。")
    p("类别检测与实例确认有不同要求。检测到一只杯子，不足以证明它是主人登记的那一只；木纹背景中的重复纹理也可能产生几何对应。本项目因此保留主人核对入口，并将视觉意见视为后续行动依据，而非直接写入位置记忆的许可。")
    h("2.3 持久记忆与轻量部署")
    p("SQLite 可在本地文件中保存结构化信息，其事务机制支持一次写入整体完成或整体不生效[5]。HomeTrace 利用数据库管理物品与位置事件，并由应用层绑定会话、照片和确认状态，防止重复点击或过期确认造成重复事件。数据库选型服务于本地演示的部署便利，不能替代应用层的来源和权限校验。")

    page("3 应用场景与需求分析")
    h("3.1 主人记住一个物品")
    p("交互情景示例为：主人说“请记住，我把水杯放在这里了”；系统展示登记名称、参考外观以及当前选中的地点，再请主人核对；确认后回复已经保存该地点记录。这些句子用于说明使用情景，不是实验录音转写。当前“这里”由主人在页面中选择，系统尚不自动推断主人所处房间。")
    h("3.2 主人请求寻找")
    p("主人说“水杯找不到了，帮我找一下”。系统查询最近的位置记录，并首先检查有依据的地点。如果当前照片没有目标，它继续选择其他已配置地点；如果照片较远或目标遮挡，它可请求同地点近景。直到存在可核对对象时，界面才把参考外观与当前照片交给主人比较。")
    h("3.3 确认与再次使用")
    p("主人确认后，系统保存本次照片所对应的位置历史。下次查询应说明这是一条历史记录，而非保证物品现在仍在那里。主人拒绝候选时，系统把拒绝作为反馈继续搜索，或在已无有效观察时结束。多个物品可分别登记名称和参考，但本文实拍完成的范围仅为一件水杯。")
    table("表1 核心需求与可观察行为",["需求","实现行为","验证方式"],[
        ["有依据地寻找","先读取记录，再选择地点","检查实际地点顺序"],
        ["根据反馈调整","未见换地点，不清楚则补图","检查工具与状态变化"],
        ["确认后再记住","候选与确认分离","比较确认前后事件数"],
        ["下次仍能查询","同工作区跨进程恢复","停止服务后重新启动"],
        ["旧证据不冒充新发现","重复图片不产生新观察结论","重放输入并检查写入"],
    ],[3.1,6.3,5.1])
    p("这些需求使“没有找到”也能成为有效输出：系统可以明确已经检查的地点、需要补充的照片和停止原因，而不是用不确定的答案结束任务。")

    page("4 系统架构")
    h("4.1 分层职责")
    p("系统由交互页面、决策流程、执行工具、视觉服务与记忆存储组成。页面收集请求、地点和照片；智能体读取任务状态并选择工具；执行层检查参数与当前状态后完成调用；视觉层返回外观比较或拒识原因；记忆层只保存符合来源规则的事件。各部分通过结构化结果联系，避免页面或语言模型直接改写可信记录。")
    table("表2 软件组件及其职责",["组件","输入与输出","责任边界"],[
        ["交互页面","请求、参考图、场景图、主人选择","显示证据，接收确认"],
        ["智能体决策","历史及工具反馈 → 下一动作","不生成权威位置事实"],
        ["搜索与执行","地点及工具参数 → 执行结果","模拟导航与观察分开记录"],
        ["视觉处理","参考区域及完整场景 → 候选意见","意见不足时允许未确认"],
        ["本地记忆","确认事件 → 可查询历史","保留来源、关联与时间语义"],
    ],[3.2,6.1,5.2])
    h("4.2 一次任务的数据流")
    p("首先从登记簿解析目标；若名称不明确，要求主人选择已登记对象。随后查询位置历史并取得本次地点快照。每执行一次观察，程序保存图像标识、地点和工具返回值，再把结果交给智能体。智能体可选择继续观察、补图、核对或结束。确认保存后，查询界面从持久存储读取结果，而非复用聊天中的一句承诺。")
    h("4.3 软件与硬件边界")
    p("本次导航工具只产生模拟动作和地点切换，照片是已拍摄资料，不是机器人实时相机流。以后接入底盘时，需要由硬件适配器返回真实到达状态，并由相机服务提供当前观察时间与姿态。本轮未接入真实机器人，也未使用未经验证的机器人接口名称冒充硬件运行。")

    page("5 位置记忆与证据组织")
    h("5.1 物品登记与位置事件")
    p("物品登记保存稳定的物品标识、名称、别名和参考外观。位置事件另外保存地点与来源。这样，物品外观无需随每次寻找重新训练；地点发生变化时也无需覆盖登记记录。一次新的主人确认会形成新事件，过去的事件仍可解释系统为什么曾经优先选择某个地点。")
    table("表3 记忆信息的含义",["信息","用途","不可推断的内容"],[
        ["登记参考","描述主人要找的对象","不代表当前所在地"],
        ["主人位置陈述","提供历史搜索线索","不代表机器人曾经看见"],
        ["场景照片","提供这张照片中的可见信息","拍摄时间未知时不代表现在"],
        ["视觉建议","提出相似或未见意见","不单独证明物理身份"],
        ["主人确认记录","保存经核对的照片位置历史","不保证以后一直未移动"],
    ],[3.2,5.6,5.7])
    h("5.2 时间与来源分开处理")
    p("系统区分照片拍摄时间、输入时间和确认时间。本次新照片没有可靠拍摄时间，因此只保存可以核实的输入及确认来源，不能根据文件名或上传次序构造连续搬动过程。再次查询时，回答指出最近一次保存的记录，避免把较新的确认时间误当成较新的拍摄时间。")
    h("5.3 重启恢复与重复写入保护")
    p("待确认候选与已保存事件需要在重启后保持一致。应用将确认绑定到当前会话和候选版本，过期操作不能替代当前选择；已经保存的确认也不会再次生成相同事件。实拍实验在新服务进程中查询到相同记录，并检查事件数量未因重启发生增长。该检查验证了本次持久流程，而非数据库在全部故障条件下的性能。")

    page("6 基于反馈的寻物决策")
    h("6.1 历史提供起点 当前观察决定下一步")
    p("搜索开始时，智能体结合登记目标、最近历史与可用地点选择先检查的位置。本次实拍的地点配置将新地点列在旧地点之前，实际执行却先检查有主人历史的旧地点，说明搜索顺序在本例中受记忆影响。原有对照场景中两种策略的总步数曾经打平，因此本文只报告顺序改变，不推导普遍的效率提升。")
    h("6.2 工具反馈形成闭环")
    p("一次观察结束后，反馈包含是否有图、照片是否重复、外观意见和失败原因。原处未见时，智能体可以选择未检查地点；图像不清楚时，可以要求主人提供同地点近景；出现相似对象时，请主人核对。每项选择都要触发实际工具调用并取得返回，而不是在最终回答中补写一条从未执行过的搜索过程。")
    table("表4 反馈与实际可选动作",["当前反馈","后续动作","停止或保存条件"],[
        ["原位置未见目标","选择另一已配置地点","没有可用观察时结束"],
        ["全景不足以比较","请求同地点近景","等待主人补图"],
        ["外观相似","展示参考与当前照片","等待主人确认或拒绝"],
        ["旧图或调用失败","保留错误并说明原因","不新增位置事件"],
        ["主人明确确认","保存照片位置历史","写入后返回来源说明"],
    ],[3.5,5.5,5.5])
    h("6.3 有限执行与模型失败")
    p("程序限制调用数量、任务步骤、等待时长与资源预算，工具参数也必须属于本次登记目标和地点范围。第一次水杯流程曾因文本上下文预算不足而停止，没有保存候选。之后在新的图片授权范围内增加文本预算并复跑，才完成完整流程。这一失败说明执行约束真实生效，也表明在线服务的上下文和延迟需要在演示前预留余量。")

    page("7 视觉处理与主人核对")
    h("7.1 登记不等于逐物品训练")
    p("对家庭用户而言，每增加一件物品就采集大量图片训练一个网络并不现实。HomeTrace 的登记流程保存少量参考外观及主人认可的目标区域，供通用视觉方法比较。登记区域尽量包含目标表面并排除背景，以降低桌面纹理参与匹配的风险。多个视角可以补充外观信息，但不能仅凭参考图数量证明识别更可靠。")
    h("7.2 本地候选与视觉顾问")
    p("本地基线采用 ORB 特征、描述子匹配和几何验证，保留匹配数、内点数与拒识原因。有效几何证据不足时不显示可靠目标框。可选视觉顾问读取已批准参考区域与完整场景，给出未见、信息不足或外观相似的意见；此意见可引导换地点、补近景或人工核对，不单独授权位置保存。")
    p("视觉顾问使用现有兼容服务接口，具体响应来自本次配置的第三方服务，不能只凭接口模型名称推断底层实现。照片发送前需要明确授权；程序核验本批图片范围、目标服务和次数。缩小副本移除元数据，但场景背景仍可能含隐私，因此发布材料另外遮挡屏幕与二维码，且不改变原始实验输入。")
    h("7.3 为什么保留人工核对")
    p("相同品类、近似颜色与不同物理实例很容易混淆。对水杯而言，杯盖、图案、比例和磨损可能帮助比较，但远景与遮挡会使这些特征不可见。本次全景得到信息不足的反馈，近景得到相似意见，主人再确认身份。这是当前已完成的人机协作路径，不把局部观察改善解释为自动实例识别已经解决。")
    p("若后续要取消人工环节，需要在参数冻结后以独立照片检验正确定位和错误实例拒绝能力。已有照片用于开发，不能重新随机拆分后充当从未使用过的测试集。训练、增强和合成素材的结果也必须与真实家庭照片分开统计。")

    page("8 钥匙软件流程演示")
    h("8.1 演示用途与输入")
    p("钥匙案例用于展示从空工作区开始的完整操作：登记物品、记住位置、更换场景、发起寻找、核对候选以及再次查询。该案例使用制作的演示样例图，适合稳定检查软件流程；它不构成真实家庭钥匙识别效果的证据。视频先展示这一操作链，再展示团队水杯实拍，以区分使用方法与真实场景表现。")
    h("8.2 实际执行过程")
    p("程序从空工作区登记参考和自定义地点，保存主人位置陈述；更换当前场景后发起寻找。智能体先检查有历史的地点，再根据观察转向下一地点；本地视觉在样例中产生候选，系统进入等待确认。候选在服务重启后仍能恢复，经操作确认后保存，再次重启可以查询相同历史。")
    p("此外还执行了拒绝候选后继续寻找和旧图重复输入测试。前者检查主人反馈能否改变后续行动，后者检查旧照片不会被包装为新发现。软件样例中的操作由验收脚本或实际页面执行，导航始终模拟；真实模型调用与确定性测试分别记录。")
    table("表5 钥匙软件流程实际检查",["检查范围","执行规模","结果"],[
        ["空工作区与重启","2 个工作区，4 个服务进程","跨进程状态和记忆恢复"],
        ["任务与模型执行","6 个请求，16 次文本调用","按实际工具反馈运行"],
        ["保存与拒绝保护","确认、拒绝、旧图重放","40 项流程检查通过"],
        ["照片外发","0 次","本地样例匹配"],
    ],[4.6,5.5,4.4])
    p("上述结果来自 2026 年 11 月 1 日的实际 HTTP 验收。数量用于说明执行范围，不能转换成识别准确率。随后的浏览器演示用于让评委看到相同产品流程，不将剪辑时长作为系统响应时间。")

    if figures:
        page('8.3 实际网页操作图示')
        p('图1展示实际浏览器中的候选核对区域。左图是已登记参考，右图是当前场景；右侧框由本次匹配程序产生。用户可以确认或拒绝，结果继续进入后续记忆与搜索流程。')
        figure('keys-candidate.png','图1 钥匙软件案例的实际候选核对界面（合成演示素材）')
        p('画面取自完整浏览器操作录像。演示先登记物品并保存位置，再把旧地点更换为空场景，随后发起寻找。模型按实际工具反馈选择检查地点，页面呈现候选后等待核对。')
        p('这组图验证操作与状态衔接，并不构成真实家庭钥匙识别的实验。随附视频保留从空目录、参考登记、记住位置、寻找、核对到再次查询的原速操作。')

    page("9 水杯实拍实验设计")
    h("9.1 数据来源与实验条件")
    p("负责人提供登记水杯参考图，并审核参考区域。2026 年 11 月 2 日新增五张真实场景照片，分别用于原位置目标缺席、新位置全景、同位置近景、相似杯干扰和空场景检查。五张图均为 1706×1279 像素，输入文件按原始字节保留。照片角色依据主人说明，不由视觉模型生成标签。")
    p("场景图以完整画面进入观察，不按已知目标位置裁剪。云端比较使用去元数据、最长边 1280 像素副本，并使用同一已批准参考区域。没有人工数值真值框，因此本次不计算交并比、定位召回率或实例精确率。全景与近景来自同一物品和地点，不能作为两个独立成功案例相加。")
    h("9.2 主流程与负例控制")
    p("主流程使用前三张照片。工作区包含一条主人先前保存的旧地点历史，当前旧地点照片没有目标。系统检查旧地点后转查新地点，全景无法确认时等待同地点近景，最后把相似候选交给主人核对。相似杯和空场景分别另开控制会话，检查错误候选与意外记忆写入。")
    table("表6 五张照片的实验角色",["编号","场景角色","观察重点"],[
        ["S1","原位置无目标","是否放弃旧地点并继续寻找"],
        ["S2","新位置全景","远距离目标能否支持比较"],
        ["S3","同位置近景","补充观察后是否请求核对"],
        ["S4","相似杯负例","不同物品是否被错误保存"],
        ["S5","空场景","没有目标时是否保持未确认"],
    ],[1.7,5.2,7.6])
    p("本实验验证在真实图片条件下的寻物交互与证据处理。由于样本量有限、照片已用于开发且缺少独立采集批次，不能据此推广到所有家庭物品或全部光照、角度与遮挡条件。")

    if figures:
        page('9.3 实拍远景与补充近景')
        p('图2和图3展示同一地点的两次观察。远景中目标占画面较小，周围杂物较多；补充近景提供杯身图案、杯盖和底圈细节。两图来自同一次开发流程，不作为两个独立成功样本。')
        figure('cup-wide.jpg','图2 新地点完整远景 S2  细节不足时请求补充观察',11.2)
        figure('cup-close.jpg','图3 同地点近景 S3  外观建议交给主人核对',11.2)

    page("10 实验结果与分析")
    table("表7 水杯逐场景结果",["场景","匹配数／内点数","视觉意见","后续处理"],[
        ["S1 原位置","14／0","未见目标","转查另一地点"],
        ["S2 新位置全景","15／4","信息不足","请求同地点近景"],
        ["S3 同位置近景","18／5","外观相似","主人核对后保存"],
        ["S4 相似杯","13／4","未见目标","未确认，无位置写入"],
        ["S5 空场景","9／0","未见目标","未确认，无位置写入"],
    ],[3.5,3.3,3.0,4.7])
    p("五张图的本地几何证据均未通过可靠定位要求。前三张中的近景虽然增加了部分几何支持，仍不足以生成合格框。视觉顾问对全景保持不确定，近景才给出相似意见。因此，本次成功是补充观察与主人确认共同完成的流程，不是五张图都被自动正确识别。")
    h("10.1 完整流程的结果")
    p("第二轮实际流程完成了历史查询、旧地点观察、换地点、补近景与主人核对。负责人提前明确确认对应照片中的物品身份及位置，工程师依据该授权通过服务接口完成保存；系统恰好新增一条主人确认的照片位置记录。新服务进程能够恢复并查询同一事件，重复输入原全景照片被拒绝，未再次外发图片，也未生成第二条位置记录。")
    h("10.2 延迟与失败")
    p("第二轮三次视觉比较分别耗时约 10.7 秒、33.6 秒和 11.2 秒，反映本次网络和模型服务条件，并非稳定速度承诺。首轮因文本预算不足终止且未保存；第二轮增加文本预算后完成。模型输出与通信仍可能失败，界面需要显示等待与失败原因，并允许主人结束当前任务。")
    h("10.3 结果的适用范围")
    p("S1、S4、S5 三个目标缺席场景没有错误位置写入，说明本轮保护有效，但样本数不足以证明普遍误报率为零。全流程九项实际检查通过，验证的是这件水杯和这组观察下的行为。不能把软件检查通过数与图像识别准确率相加或互相替代。")

    if figures:
        page('10.4 任务记录与记忆恢复界面')
        p('图4是实际 HTML 页面读取已保存任务后的界面。主人的确认已作为带来源的历史保留；页面区分当前回答和过往位置，避免把照片中的地点说成此刻仍然存在的事实。')
        figure('cup-history.png','图4 服务重启后的历史查询记录  页面只读回看，无新增推理')
        p('水杯视频直接操作这一生产页面，选择登记物品、查看观察照片、滚动决策轨迹并展开历史。展示的是已经完成的真实任务记录，不通过重新点击确认制造第二条位置历史。')
        p('软件原型没有接入真实机器人。地点切换由模拟导航表达，照片由主人提供。实物照片能验证观察与反馈流程，却不能替代底盘移动、避障、全屋建图或实时相机测试。')

    page("11 软件验证与运行方法")
    h("11.1 软件质量检查")
    p("2026 年 11 月 3 日，本轮完整 Python 回归实际通过 1286 项，运行约 205.96 秒；三个前端测试文件联合通过 28 项。检查覆盖记忆读写、状态恢复、模型参数与错误处理、图片授权、确认版本、旧图保护和材料工具等。测试中保留一个已有依赖弃用提示，不影响本轮通过结果。最终源码随包附带对应测试记录。")
    p("这些离线回归使用确定性输入，保证错误分支可重复检查，不要求云端模型每次输出相同文字。真实模型和真实照片实验另行记录；没有以单元测试替代视觉效果验收。此前从解压源码建立新环境的安装与启动检查也已完成，实际在线演示仍需要用户自备有效服务配置。")
    h("11.2 安装与启动")
    p("建议使用 Windows 与 Python 3.11 或以上版本，在解压源码目录建立虚拟环境，安装项目及演示可选依赖。服务密钥写入本机环境文件，不写入公共源码或报告。启动命令如下，详细配置说明放在源码的运行说明中。")
    p("python -m venv .venv\n.venv\\Scripts\\python -m pip install -e \".[dev,vision,vision-advisor,agent]\"", "HTReference")
    p("python -m hometrace demo --photo-vision-agent --config config.photo-demo.yaml --port 8770 --household-dir artifacts/my-home", "HTReference")
    p("浏览器打开 http://127.0.0.1:8770/，先登记参考、配置地点与场景，再发送记住或寻找请求。再次使用同一工作区会恢复历史；从零演示应选择一个新目录。外发图片需要在页面核对并批准，原实验授权已经用完，不会随源码包转移。")
    h("11.3 交付内容")
    p("本次交付包括作品报告、展示文稿、带字幕的视频和相关源码。视频依次展示钥匙软件流程与水杯实拍任务，保留导航模拟和主人核对标识。代码包排除个人信息、家庭原图、服务密钥、数据库和模型权重；公开源码中的软件样例不得当作家庭实拍数据。")

    page("12 讨论与后续实现")
    h("12.1 产品创新与实际价值")
    p("本作品将家庭寻物组织为可解释的行动过程。历史让搜索有起点，当前观察让计划能够调整，主人确认使不确定的外观判断有明确归属。对评委和使用者而言，系统能够展示查过哪里、为何补图以及最后由谁确认，这比只给出一个地点名称更容易理解和核实。")
    p("新增物品以登记参考和名称为主，不要求每物训练一个网络。原创工作集中在位置记忆、反馈协作与重复证据保护；视觉算法及模型服务复用成熟技术。")
    h("12.2 当前不足")
    p("现阶段实拍验证只有一件水杯。目标较远时需要补近景，本地匹配未形成可靠定位框，云端相似意见还需要主人核对。照片由主人提供，不能展示无人值守的巡航扫描；地点来自用户选择，不能表示已经完成自动室内定位。此外，长期生活习惯的学习与排序还没有独立实验支持。")
    h("12.3 可检验的下一步")
    p("视觉方法和参数冻结后，再采集独立正负例。受限单物品验收要求六张正例中至少五张定位正确且交并比不低于 0.5，八张负例无错误接受，实例精确率不低于 0.95；零接受不能通过。在此之前保留主人核对。")
    h('12.4 语音与具身机器人接入')
    p('后续增加语音识别与语音回复，让主人直接说“钥匙放在这里了”或“帮我找水杯”。语音转写仍需确认物品和地点歧义，位置保存继续沿用现有确认流程。当前版本采用文字输入，未实现麦克风唤醒、连续识音或语音交互验收。')
    p('在具身机器人平台上，目标是先建立全屋地图，把房间、桌面与可观察位置关联起来；随后利用自身定位和导航逐点到达，以相机获取实时观察，再由本系统读取记忆、选择下一处位置并验证目标。导航失败、遮挡与无法到达也应作为反馈返回。')
    p('上述扩展需完成建图、定位、避障导航、相机与设备回执的对接，并通过家庭环境测试。当前软件提供决策与记忆基础，全屋自主搜索仍是后续目标。')

    page("13 结论")
    p("本文实现了基于位置记忆与反馈决策的 HomeTrace 家庭寻物原型。系统能够登记物品外观、保存主人位置历史，并让智能体调用工具逐步寻找。在团队水杯实拍中，旧地点未见目标后转查新地点、请求近景、主人授权保存、重启查询与旧图保护均完成实际执行。结果支持主人参与的单物品软件流程可运行，不支持自动可靠识别全部家庭物品的结论。")
    p("HomeTrace 的核心设计是让每一次回答对应可检查的信息来源，让每一次后续行动由当前反馈决定。下一步将围绕独立实例验证和真实设备观察开展接入；在此之前，保留人工核对与未确认状态，使作品在现有条件下能够清晰展示、重复运行并如实表达结果。")
    h("参考文献")
    refs=[
        "[1] YAO S, ZHAO J, YU D, et al. ReAct: Synergizing Reasoning and Acting in Language Models[C]. ICLR, 2023. https://arxiv.org/abs/2210.03629.",
        "[2] LangChain. LangGraph overview[EB/OL]. https://docs.langchain.com/oss/python/langgraph/overview. 访问日期：2026-11-03.",
        "[3] OpenCV. ORB Oriented FAST and Rotated BRIEF[EB/OL]. https://docs.opencv.org/4.13.0/d1/d89/tutorial_py_orb.html. 访问日期：2026-11-03.",
        "[4] OpenCV. Feature Matching and Homography to find Objects[EB/OL]. https://docs.opencv.org/4.13.0/d1/de0/tutorial_py_feature_homography.html. 访问日期：2026-11-03.",
        "[5] SQLite. SQLite Is Transactional[EB/OL]. https://www.sqlite.org/transactional.html. 访问日期：2026-11-03.",
    ]
    for ref in refs:p(ref,"HTReference")
    return doc


def build(original, output, fields, expected_sha256, qa_dir=None, figures=None):
    from docx.oxml.ns import qn

    original, output = Path(original), Path(output)
    if output.exists() or original.resolve() == output.resolve():
        raise OfficialFormError("Refusing to overwrite a report or template")
    values=confirmed_fields(fields)
    with tempfile.TemporaryDirectory() as directory:
        filled=Path(directory)/"filled.docx"
        fill_official(original,filled,expected_sha256,values)
        parts=_package(filled)
    # Retain the official heading and table; replace only generic guidance.
    from lxml import etree
    root=etree.fromstring(parts["word/document.xml"])
    body=root.find(qn("w:body"))
    table=body.find(qn("w:tbl"))
    index=list(body).index(table)
    last_section=deepcopy(body.find(qn("w:sectPr")))
    for item in list(body)[index+1:]:body.remove(item)
    paper=make_paper(figures)
    if figures:
        rels=etree.fromstring(parts['word/_rels/document.xml.rels'])
        types=etree.fromstring(parts['[Content_Types].xml'])
        extensions={x.get('Extension') for x in types}
        for index,(old_id,rel) in enumerate([(k,v) for k,v in paper.part.rels.items() if v.reltype==IMAGE_REL],1):
            blob=rel.target_part.blob
            ext='png' if blob.startswith(b'\x89PNG') else 'jpg'
            name='ht-'+hashlib.sha256(blob).hexdigest()+'.'+ext
            rid='htImage'+str(index)
            if any(x.get('Id')==rid for x in rels):raise OfficialFormError('Figure relationship collision')
            etree.SubElement(rels,'{'+REL+'}Relationship',Id=rid,Type=IMAGE_REL,Target='media/'+name)
            parts['word/media/'+name]=blob
            if ext not in extensions:
                etree.SubElement(types,'{'+CT+'}Default',Extension=ext,ContentType='image/png' if ext=='png' else 'image/jpeg');extensions.add(ext)
            for blip in paper.element.body.iter():
                if blip.get('{'+R+'}embed')==old_id:blip.set('{'+R+'}embed',rid)
        parts['word/_rels/document.xml.rels']=etree.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True)
        parts['[Content_Types].xml']=etree.tostring(types,xml_declaration=True,encoding='UTF-8',standalone=True)
    for item in paper.element.body:
        if item.tag != qn("w:sectPr"):body.append(deepcopy(item))
    body.append(last_section)
    parts["word/document.xml"]=etree.tostring(root,xml_declaration=True,encoding="UTF-8",standalone=True)
    styles=etree.fromstring(parts["word/styles.xml"])
    existing={s.get(qn("w:styleId")) for s in styles}
    for style in paper.styles:
        if style.style_id.startswith("HT"):
            if style.style_id in existing:raise OfficialFormError("Custom report style collides with template")
            styles.append(deepcopy(style.element))
    parts["word/styles.xml"]=etree.tostring(styles,xml_declaration=True,encoding="UTF-8",standalone=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,"x",compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in parts.items():z.writestr(name,data)
    result=verify_report_table(original,output,expected_sha256,fields)
    if qa_dir:
        qa=Path(qa_dir);qa.mkdir(parents=True,exist_ok=True)
        target=qa/"structure.json"
        if target.exists():raise OfficialFormError("Refusing to overwrite report audit")
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--template",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--qa-dir",type=Path)
    parser.add_argument("--figures",type=Path,help='Private figure directory; never uploaded with source')
    args=parser.parse_args()
    data=json.loads(args.config.read_text(encoding="utf8"))
    result=build(args.template,args.output,data.get("official_fields",data),data["official_template_sha256"],args.qa_dir,args.figures)
    print(json.dumps(result,ensure_ascii=True))


if __name__ == "__main__":
    main()
