"""Fill the supplied HEC DOCX locally; never infer identity or certify upload."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.dom.minidom as DOM
import xml.etree.ElementTree as ET
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
FIELDS = ("name", "gender", "education", "school", "major", "graduation", "email", "phone")
PLACEHOLDER = re.compile(r"TODO|PLACEHOLDER|待填写|填写示例|请与大赛|若无则|简要描述|X{3,}|202x", re.I)


class OfficialFormError(ValueError):
    """Messages contain field names, never local identity values."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_content(data):
    if not isinstance(data, dict):
        raise OfficialFormError("official_fields must be an object")
    for key, maximum in (("team_name", 80), ("project_name", 80), ("description", 300)):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or PLACEHOLDER.search(value):
            raise OfficialFormError(f"Missing, placeholder or oversized field: {key}")
        if any(ord(c) < 32 for c in value):
            raise OfficialFormError(f"Control characters are not allowed: {key}")
    members = data.get("members")
    if not isinstance(members, list) or not 1 <= len(members) <= 3:
        raise OfficialFormError("Provide one captain and at most two members")
    for person in members:
        if not isinstance(person, dict) or set(person) != set(FIELDS):
            raise OfficialFormError("Every member requires the eight official identity fields")
        for key in FIELDS:
            value = person[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 120 or PLACEHOLDER.search(value) or any(ord(c) < 32 for c in value):
                raise OfficialFormError(f"Missing, placeholder or invalid member field: {key}")
        if not re.fullmatch(r"1[3-9][0-9]{9}", person["phone"]) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", person["email"]):
            raise OfficialFormError("Member phone or email format is invalid")
    if data.get("identity_confirmed") is not True:
        raise OfficialFormError("Identity must be locally confirmed against the competition platform")
    return data


def _package(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if len(names) != len(set(names)) or z.testzip() or sum(i.file_size for i in z.infolist()) > 128 * 1024 * 1024:
                raise OfficialFormError("DOCX container is duplicate, corrupt or oversized")
            if "word/document.xml" not in names:
                raise OfficialFormError("DOCX document part is missing")
            for n in names:
                if n.startswith("/") or ".." in Path(n).parts or "\\" in n or "vbaproject" in n.lower() or "/embeddings/" in n.lower():
                    raise OfficialFormError("Unsafe DOCX package part")
            return {n: z.read(n) for n in names}
    except (OSError, zipfile.BadZipFile) as exc:
        raise OfficialFormError("DOCX cannot be opened") from exc


def _tree(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise OfficialFormError("DOCX XML cannot be parsed") from exc
    tables = root.findall(".//w:tbl", NS)
    if len(tables) != 1:
        raise OfficialFormError("Expected one official application table")
    rows = tables[0].findall("w:tr", NS)
    return root, tables[0], rows


def _text(cell):
    return "".join(t.text or "" for t in cell.findall(".//w:t", NS))


def _original_rows(parts):
    root, table, rows = _tree(parts["word/document.xml"])
    if len(rows) != 8 or [len(r.findall("w:tc", NS)) for r in rows] != [2, 2, 2, 9, 9, 9, 9, 1]:
        raise OfficialFormError("Original template table layout is unsupported")
    labels = [_text(rows[i].findall("w:tc", NS)[0]) for i in range(7)]
    if labels != ["队伍名称", "课题名称", "课题描述", "角色", "队长", "队员1", "队员2"]:
        raise OfficialFormError("Original template labels are unsupported")
    return root, table, rows


def _clear_editable(rows, count):
    slots = [rows[i].findall("w:tc", NS)[1] for i in range(3)]
    slots += [c for row in rows[4:4+count] for c in row.findall("w:tc", NS)[1:]]
    for cell in slots:
        for child in list(cell):
            if child.tag == f"{{{W}}}p":
                for run in list(child):
                    if run.tag != f"{{{W}}}pPr":
                        child.remove(run)
            elif child.tag != f"{{{W}}}tcPr":
                cell.remove(child)


def verify_filled(original, filled, expected_sha256, fields):
    validate_content(fields)
    if Path(original).resolve() == Path(filled).resolve():
        raise OfficialFormError("Original and filled DOCX must be different files")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or digest(original) != expected_sha256:
        raise OfficialFormError("Original template SHA256 is missing or differs")
    original_parts, filled_parts = _package(original), _package(filled)
    if set(original_parts) != set(filled_parts) or any(original_parts[k] != filled_parts[k] for k in original_parts if k != "word/document.xml"):
        raise OfficialFormError("Preserve-only DOCX package parts changed")
    a, at, ar = _original_rows(original_parts)
    b, bt, br = _tree(filled_parts["word/document.xml"])
    count = len(fields["members"])
    if len(br) != 5 + count:
        raise OfficialFormError("Filled table row count differs from member count")
    expected = [fields["team_name"], fields["project_name"], fields["description"]]
    actual = [_text(br[i].findall("w:tc", NS)[1]) if len(br[i].findall("w:tc", NS)) == 2 else "" for i in range(3)]
    for i, person in enumerate(fields["members"]):
        expected.extend(person[k] for k in FIELDS)
        actual.extend(_text(c) for c in br[4+i].findall("w:tc", NS)[1:])
    if actual != expected:
        raise OfficialFormError("Filled fields do not match the confirmed local input")
    for row in ar[4+count:7]:
        at.remove(row)
    _clear_editable(at.findall("w:tr", NS), count)
    _clear_editable(br, count)
    if ET.tostring(a) != ET.tostring(b):
        raise OfficialFormError("Original table grid, fixed labels, layout or other content changed")
    return {"status": "STRUCTURE_AND_CONTENT_VERIFIED", "description_characters": len(fields["description"]), "member_count": count, "original_sha256": expected_sha256, "filled_sha256": digest(filled), "preserve_only_parts_unchanged": True, "optional_member_rows_removed": 3-count, "visual_review": "PENDING", "officially_verified": False}


def _children(node, local):
    return [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE and n.namespaceURI == W and n.localName == local]


def _fill_cell(doc, cell, value):
    paragraphs = _children(cell, "p")
    if not paragraphs:
        raise OfficialFormError("Editable table cell has no paragraph")
    texts = list(cell.getElementsByTagNameNS(W, "t"))
    if not texts:
        run = doc.createElementNS(W, "w:r")
        text = doc.createElementNS(W, "w:t")
        run.appendChild(text)
        paragraphs[0].appendChild(run)
        texts = [text]
    for text in texts:
        for child in list(text.childNodes):
            text.removeChild(child)
    texts[0].appendChild(doc.createTextNode(value))
    # Only text runs are editable. Paragraph-mark defaults inside pPr must
    # remain byte-equivalent under the preserve-only structural comparison.
    for run in cell.getElementsByTagNameNS(W, "r"):
        properties = _children(run, "rPr")
        if properties:
            props = properties[0]
        else:
            props = doc.createElementNS(W, "w:rPr")
            run.insertBefore(props, run.firstChild)
        for item in list(props.childNodes):
            if item.nodeType == item.ELEMENT_NODE and item.namespaceURI == W and item.localName in {"i", "iCs", "color"}:
                props.removeChild(item)
        # Explicit false overrides italic paragraph defaults without changing
        # those defaults, including when an originally empty cell gets a run.
        for name in ("i", "iCs"):
            italic = doc.createElementNS(W, "w:" + name)
            italic.setAttributeNS(W, "w:val", "0")
            props.appendChild(italic)
        color = doc.createElementNS(W, "w:color")
        color.setAttributeNS(W, "w:val", "000000")
        props.appendChild(color)


def _serialize_document(doc):
    # minidom writes literal whitespace in attribute values; XML parsers then
    # normalize it to spaces. Preserve character references (e.g. VML gfxdata)
    # rather than weakening the untouched-content comparison in verify_filled.
    def attribute(match):
        value = match.group(1).replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")
        return '="' + value + '"'
    return re.sub(r'="([^"]*)"', attribute, doc.toxml(encoding="UTF-8").decode("utf-8")).encode("utf-8")


def fill_official(original, output, expected_sha256, fields):
    validate_content(fields)
    original, output = Path(original), Path(output)
    if original.resolve() == output.resolve() or output.exists():
        raise OfficialFormError("Refusing to overwrite original or existing output")
    if digest(original) != expected_sha256:
        raise OfficialFormError("Original template SHA256 differs")
    parts = _package(original)
    _original_rows(parts)
    doc = DOM.parseString(parts["word/document.xml"])
    table = doc.getElementsByTagNameNS(W, "tbl")[0]
    rows = _children(table, "tr")
    for i, key in enumerate(("team_name", "project_name", "description")):
        _fill_cell(doc, _children(rows[i], "tc")[1], fields[key])
    for i, person in enumerate(fields["members"]):
        for cell, key in zip(_children(rows[4+i], "tc")[1:], FIELDS):
            _fill_cell(doc, cell, person[key])
    for row in rows[4+len(fields["members"]):7]:
        table.removeChild(row)  # Original template explicitly says remove absent members.
    parts["word/document.xml"] = _serialize_document(doc)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return verify_filled(original, output, expected_sha256, fields)


def fill_draft(original, output, expected_sha256, fields):
    """Write only project content; identity stays visibly unfilled and fails preflight."""
    for key, maximum in (("project_name", 80), ("description", 300)):
        value = fields.get(key) if isinstance(fields, dict) else None
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or PLACEHOLDER.search(value) or any(ord(c) < 32 for c in value):
            raise OfficialFormError(f"Invalid draft project field: {key}")
    original, output = Path(original), Path(output)
    if original.resolve() == output.resolve() or output.exists() or "DRAFT" not in output.name:
        raise OfficialFormError("Draft requires a new output filename containing DRAFT")
    if digest(original) != expected_sha256:
        raise OfficialFormError("Original template SHA256 differs")
    parts = _package(original)
    _original_rows(parts)
    doc = DOM.parseString(parts["word/document.xml"])
    rows = _children(doc.getElementsByTagNameNS(W, "tbl")[0], "tr")
    _fill_cell(doc, _children(rows[0], "tc")[1], "DRAFT 待填写并核对平台队伍名称")
    for i, key in ((1, "project_name"), (2, "description")):
        _fill_cell(doc, _children(rows[i], "tc")[1], fields[key])
    for row in rows[4:7]:
        for cell in _children(row, "tc")[1:]:
            _fill_cell(doc, cell, "待填写")
    parts["word/document.xml"] = _serialize_document(doc)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return {"status": "DRAFT_IDENTITY_MISSING", "description_characters": len(fields["description"]), "officially_verified": False, "visual_review": "PENDING", "ready_to_submit": False}


def main(argv=None):
    from .submission import local_file, _object, _no_links, SubmissionError
    parser = argparse.ArgumentParser(description="Fill the supplied official DOCX from confirmed local identity")
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--draft", action="store_true", help="Project text only; output must contain DRAFT; never submission-ready")
    args = parser.parse_args(argv)
    try:
        root = args.config.resolve().parent
        # Identity and finished DOCX must remain in a Git ignored local input directory.
        for path in (args.config,):
            ignored = subprocess.run(["git", "check-ignore", "--quiet", str(path.resolve())], cwd=root, capture_output=True)
            if ignored.returncode:
                raise OfficialFormError("Config and output must be inside a Git ignored directory")
        config = json.loads(args.config.read_text(encoding="utf8"), object_pairs_hook=_object)
        template = local_file(root, config["materials"]["official_template"])
        output_name = config["materials"]["application"]
        # Reuse path validation on the parent before an output exists.
        if not isinstance(output_name, str) or "\\" in output_name or ":" in output_name or Path(output_name).is_absolute() or any(p in {"", ".", ".."} for p in output_name.split("/")):
            raise OfficialFormError("Filled output requires a safe relative path")
        output = root / output_name
        _no_links(output, root)
        for path in (template, output):
            if subprocess.run(["git", "check-ignore", "--quiet", str(path.resolve())], cwd=root, capture_output=True).returncode:
                raise OfficialFormError("Template and output must remain Git ignored")
        if args.draft:
            result = fill_draft(template, output, config["official_template_sha256"], config["official_fields"])
        elif args.check:
            result = verify_filled(template, local_file(root, output_name), config["official_template_sha256"], config["official_fields"])
        else:
            result = fill_official(template, output, config["official_template_sha256"], config["official_fields"])
        print(result["status"])
        print("Visual review remains PENDING; officially_verified=false; uploaded=false.")
        return 0
    except (OfficialFormError, SubmissionError, OSError, ValueError, KeyError, TypeError):
        print("BLOCKED: official input, identity, original hash or output validation failed; inspect local config.")
        return 2
