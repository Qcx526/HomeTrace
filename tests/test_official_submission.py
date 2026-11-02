"""All form identities and templates below are synthetic TEST_ONLY fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import zipfile
from xml.sax.saxutils import escape

import pytest

from hometrace import official_submission as form
from hometrace import submission as sub
from test_submission import bundle  # reuse original packaging fixture without changing it


def template(path):
    def cell(text):
        return f'<w:tc><w:tcPr><w:tcW w:w="900"/></w:tcPr><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:tc>'
    rows = [["队伍名称", "请与大赛平台报名队伍名称一致"], ["课题名称", "XXXXXX"], ["课题描述", "简要描述课题内容，300字以内"],
            ["角色", "姓名", "性别", "学历", "学校", "专业", "毕业时间", "邮箱", "电话"],
            ["队长", "填写示例", "男", "本科", "样例学校", "专业", "202x", "example@invalid.test", "13512341234"],
            ["队员1", "若无则删除此行", "", "", "", "", "", "", ""], ["队员2", "若无则删除此行", "", "", "", "", "", "", ""], ["备注：固定保留"]]
    xml = f'<w:document xmlns:w="{form.W}"><w:body><w:p><w:r><w:t>TEST_ONLY SYNTHETIC TEMPLATE</w:t></w:r></w:p><w:tbl><w:tblGrid><w:gridCol w:w="900"/></w:tblGrid>'+''.join('<w:tr>'+''.join(cell(v) for v in row)+'</w:tr>' for row in rows)+'</w:tbl><w:sectPr/></w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("word/document.xml", xml)
        z.writestr("word/styles.xml", "<styles>TEST_ONLY</styles>")
    return form.digest(path)


def data(count=1):
    return {"team_name": "TEST_ONLY TEAM", "project_name": "TEST_ONLY HomeTrace", "description": "仅用于自动化测试的合成说明，不能作为参赛材料。", "identity_confirmed": True,
            "members": [{"name": f"Synthetic Person {i}", "gender": "男", "education": "本科", "school": "TEST_ONLY School", "major": "Software", "graduation": "2030年6月", "email": f"test{i}@example.invalid", "phone": "13900000001"} for i in range(count)]}


@pytest.mark.parametrize("count", [1, 2, 3])
def test_fill_preserves_template_parts_and_verifies(tmp_path, count):
    source, output = tmp_path / "original.docx", tmp_path / "TEST_ONLY-filled.docx"
    h = template(source)
    result = form.fill_official(source, output, h, data(count))
    assert result["member_count"] == count
    assert result["preserve_only_parts_unchanged"] and result["visual_review"] == "PENDING"
    assert form.digest(source) == h
    assert not result["officially_verified"]
    assert "Synthetic Person" not in json.dumps(result)


@pytest.mark.parametrize("change", ["missing_identity", "four_members", "zero_members", "long_description", "placeholder", "phone", "missing_member_field", "control"])
def test_invalid_identity_or_description_blocks(tmp_path, change):
    original = tmp_path / "original.docx"
    h = template(original)
    fields = data()
    if change == "missing_identity": fields["identity_confirmed"] = False
    elif change == "four_members": fields["members"] *= 4
    elif change == "zero_members": fields["members"] = []
    elif change == "long_description": fields["description"] = "字" * 301
    elif change == "placeholder": fields["team_name"] = "待填写"
    elif change == "phone": fields["members"][0]["phone"] = "secret-invalid-value"
    elif change == "missing_member_field": del fields["members"][0]["school"]
    else: fields["description"] = "Bad\nline"
    with pytest.raises(form.OfficialFormError) as error:
        form.fill_official(original, tmp_path / "out.docx", h, fields)
    assert "secret-invalid-value" not in str(error.value)
    assert not (tmp_path / "out.docx").exists()


def test_300_characters_allowed(tmp_path):
    fields = data(); fields["description"] = "字" * 300
    original = tmp_path / "original.docx"
    h = template(original)
    assert form.fill_official(original, tmp_path / "out.docx", h, fields)["description_characters"] == 300


@pytest.mark.parametrize("problem", ["same_path", "hash", "exists"])
def test_never_overwrite_original_or_existing_output(tmp_path, problem):
    original, output = tmp_path / "original.docx", tmp_path / "filled.docx"
    h = template(original)
    if problem == "same_path": output = original
    elif problem == "hash": h = "0" * 64
    else: output.write_bytes(b"protected")
    before = original.read_bytes()
    with pytest.raises(form.OfficialFormError):
        form.fill_official(original, output, h, data())
    assert original.read_bytes() == before
    if problem == "exists": assert output.read_bytes() == b"protected"


@pytest.mark.parametrize("changed_part", ["word/styles.xml", "word/document.xml"])
def test_layout_or_preserve_only_part_change_rejected(tmp_path, changed_part):
    original, output = tmp_path / "original.docx", tmp_path / "filled.docx"
    h = template(original)
    form.fill_official(original, output, h, data())
    with zipfile.ZipFile(output) as z: parts = {n: z.read(n) for n in z.namelist()}
    parts[changed_part] = parts[changed_part].replace(b"900", b"901") if changed_part.endswith("document.xml") else b"<changed/>"
    with zipfile.ZipFile(output, "w") as z:
        for n, v in parts.items(): z.writestr(n, v)
    with pytest.raises(form.OfficialFormError): form.verify_filled(original, output, h, data())


def official_bundle(bundle):
    root, inputs, config, path, save = bundle
    config["document_source"] = "official_template"
    config["official_source"] = "Synthetic TEST_ONLY template"
    config["materials"]["official_template"] = "original.docx"
    config["official_template_sha256"] = template(inputs / "original.docx")
    fields = config["official_fields"] = data()
    config["team"] = {"name": fields["team_name"], "work_name": fields["project_name"], "captain_name": fields["members"][0]["name"], "captain_phone": fields["members"][0]["phone"]}
    config["identity_confirmed"] = True
    config["materials"]["application"] = "filled.docx"
    form.fill_official(inputs / "original.docx", inputs / "filled.docx", config["official_template_sha256"], fields)
    save()
    return bundle


def test_official_package_excludes_original_and_names_supplement(bundle):
    root, inputs, config, path, save = official_bundle(bundle)
    config["materials"]["technical_supplement"] = "application.docx"; save()
    report = sub.build(path, root)
    assert report["status"] == "TEST_ONLY_VERIFIED"
    assert report["official_application"] == "CONTENT_VERIFIED_VISUAL_REVIEW_PENDING"
    with zipfile.ZipFile(root / "dist_submission/TEST_ONLY-candidate-HomeTrace.zip") as z:
        assert not any("original.docx" in n or n.endswith(".pdf") for n in z.namelist())
        assert any("补充" in n for n in z.namelist())
        assert not any(hashlib.sha256(z.read(n)).hexdigest() == config["official_template_sha256"] for n in z.namelist())


@pytest.mark.parametrize("problem", ["identity_mismatch", "unfilled", "same_path", "wrong_hash", "missing_fields", "rules_pdf", "original_as_supplement"])
def test_official_packaging_rejects_invalid_inputs(bundle, problem):
    root, inputs, config, path, save = official_bundle(bundle)
    if problem == "identity_mismatch": config["team"]["name"] = "DIFFERENT"
    elif problem == "unfilled": (inputs / "filled.docx").write_bytes((inputs / "original.docx").read_bytes())
    elif problem == "same_path": config["materials"]["application"] = "original.docx"
    elif problem == "wrong_hash": config["official_template_sha256"] = "0" * 64
    elif problem == "missing_fields": del config["official_fields"]
    elif problem == "rules_pdf":
        (inputs / "比赛规则.pdf").write_bytes(b"%PDF fake")
        config["materials"]["run_report"] = "比赛规则.pdf"
    else: config["materials"]["technical_supplement"] = "original.docx"
    save()
    assert sub.build(path, root)["status"] == "BLOCKED"
    assert not list((root / "dist_submission").glob("*.zip"))


def test_legacy_team_authored_is_only_incomplete_technical_candidate(bundle):
    root, _, _, path, _ = bundle
    report, entries, _ = sub.prepare(path, root)
    assert report["official_application"] == "BLOCKED"
    assert any("缺少官方主表" in e.name for e in entries)
    assert not report["ready_to_submit"]


def test_draft_preserves_rows_and_cannot_pass_official_validation(tmp_path):
    original, output = tmp_path / "original.docx", tmp_path / "DRAFT-form.docx"
    h = template(original)
    fields = {"project_name": "HomeTrace", "description": "历史记忆与当前图像证据分离。"}
    result = form.fill_draft(original, output, h, fields)
    assert result["status"] == "DRAFT_IDENTITY_MISSING"
    assert not result["ready_to_submit"]
    assert form.digest(original) == h
    with zipfile.ZipFile(output) as z:
        _, _, rows = form._tree(z.read("word/document.xml"))
        assert len(rows) == 8
        assert "DRAFT" in form._text(rows[0])
        assert "待填写" in form._text(rows[4])
    with pytest.raises(form.OfficialFormError):
        form.verify_filled(original, output, h, data())


def test_draft_requires_explicit_draft_name_and_valid_project_text(tmp_path):
    original = tmp_path / "original.docx"
    h = template(original)
    with pytest.raises(form.OfficialFormError):
        form.fill_draft(original, tmp_path / "official.docx", h, data())
    fields = data(); fields["description"] = "字" * 301
    with pytest.raises(form.OfficialFormError):
        form.fill_draft(original, tmp_path / "DRAFT.docx", h, fields)


def test_paragraph_layout_change_rejected(tmp_path):
    original, output = tmp_path / "original.docx", tmp_path / "filled.docx"
    h = template(original)
    form.fill_official(original, output, h, data())
    with zipfile.ZipFile(output) as z: parts = {n: z.read(n) for n in z.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].replace(b"<w:p>", b'<w:p><w:pPr><w:ind w:left="9999"/></w:pPr>', 2)
    with zipfile.ZipFile(output, "w") as z:
        for n, v in parts.items(): z.writestr(n, v)
    with pytest.raises(form.OfficialFormError): form.verify_filled(original, output, h, data())
