"""Synthetic templates reproduce paragraph typography in the supplied form."""

import xml.etree.ElementTree as ET
import zipfile

import pytest

from hometrace import official_submission as form
from test_official_submission import data, template


def template_with_paragraph_styles(path):
    template(path)
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    paragraph_properties = (
        b'<w:pPr><w:spacing w:before="0" w:after="0" w:line="240"/>'
        b'<w:rPr><w:i/><w:iCs/><w:color w:val="808080"/>'
        b'<w:sz w:val="20"/><w:spacing w:val="0"/></w:rPr></w:pPr>'
    )
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b"<w:p>", b"<w:p>" + paragraph_properties
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return form.digest(path)


def paragraph_properties(path, member_count=None):
    with zipfile.ZipFile(path) as archive:
        root, table, rows = form._tree(archive.read("word/document.xml"))
    if member_count is not None:
        for row in rows[4 + member_count:7]:
            table.remove(row)
    return [ET.tostring(props) for props in root.findall(".//w:pPr", form.NS)]


@pytest.mark.parametrize("member_count", [1, 3])
def test_form_fill_preserves_paragraph_default_typography(tmp_path, member_count):
    original, output = tmp_path / "original.docx", tmp_path / "TEST_ONLY-filled.docx"
    original_hash = template_with_paragraph_styles(original)
    fields = data(member_count)
    expected_properties = paragraph_properties(original, member_count)

    result = form.fill_official(original, output, original_hash, fields)

    assert result["status"] == "STRUCTURE_AND_CONTENT_VERIFIED"
    assert form.verify_filled(original, output, original_hash, fields)["preserve_only_parts_unchanged"]
    assert expected_properties
    assert paragraph_properties(output) == expected_properties
    assert form.digest(original) == original_hash


def test_draft_fill_preserves_paragraph_default_typography(tmp_path):
    original, output = tmp_path / "original.docx", tmp_path / "DRAFT-TEST_ONLY.docx"
    original_hash = template_with_paragraph_styles(original)
    expected_properties = paragraph_properties(original)

    result = form.fill_draft(original, output, original_hash, data())

    assert result["status"] == "DRAFT_IDENTITY_MISSING"
    assert expected_properties
    assert paragraph_properties(output) == expected_properties
    assert form.digest(original) == original_hash
    assert not result["ready_to_submit"]
