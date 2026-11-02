"""Preserve XML attribute whitespace outside editable official-form cells."""

import xml.etree.ElementTree as ET
import zipfile

import pytest

from hometrace import official_submission as form
from test_official_submission import data, template


ATTRIBUTE_VALUE = "TEST_ONLY\nline\tcolumn\rreturn"


def template_with_attribute_whitespace(path):
    template(path)
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b"<w:p>",
        b'<w:p test-only-preserved="TEST_ONLY&#10;line&#9;column&#13;return">',
        1,
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return form.digest(path)


def preserved_attribute(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return root.find("w:body/w:p", form.NS).get("test-only-preserved")


@pytest.mark.parametrize("mode", ["formal", "draft"])
def test_fill_preserves_attribute_whitespace(tmp_path, mode):
    original = tmp_path / "TEST_ONLY-original.docx"
    output = tmp_path / ("DRAFT-TEST_ONLY.docx" if mode == "draft" else "TEST_ONLY-filled.docx")
    original_hash = template_with_attribute_whitespace(original)
    fields = data()
    assert preserved_attribute(original) == ATTRIBUTE_VALUE

    if mode == "formal":
        result = form.fill_official(original, output, original_hash, fields)
        assert result["status"] == "STRUCTURE_AND_CONTENT_VERIFIED"
        assert form.verify_filled(original, output, original_hash, fields)["preserve_only_parts_unchanged"]
    else:
        result = form.fill_draft(original, output, original_hash, fields)
        assert result["status"] == "DRAFT_IDENTITY_MISSING"
        assert not result["ready_to_submit"]

    assert preserved_attribute(output) == ATTRIBUTE_VALUE
    assert form.digest(original) == original_hash
