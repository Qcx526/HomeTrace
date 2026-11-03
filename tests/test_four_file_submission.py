"""Four-file packaging tests use only synthetic, explicitly TEST_ONLY inputs."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from hometrace import official_submission as form
from hometrace import submission as sub
from tools import build_four_file_submission as four
from test_official_submission import data, template
from test_submission import bundle


@pytest.fixture
def four_bundle(bundle):
    root, inputs, _, _, _ = bundle
    fields = data(3)
    original, report = inputs / "original.docx", inputs / "report.docx"
    expected = template(original)
    form.fill_official(original, report, expected, fields)
    with zipfile.ZipFile(report) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b"<w:sectPr/>", b"<w:p><w:r><w:t>TEST_ONLY appended paper. No experimental claim.</w:t></w:r></w:p><w:sectPr/>")
    with zipfile.ZipFile(report, "w") as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    identity = {"team": {"name": fields["team_name"], "work_name": fields["project_name"],
                          "captain_name": fields["members"][0]["name"], "captain_phone": fields["members"][0]["phone"]},
                "official_fields": fields, "official_template_sha256": expected,
                "identity_source": "TEST_ONLY synthetic fixture", "platform_identity_verified": False}
    identity_path = inputs / "team.private.json"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    config = {"schema_version": 1, "test_only": True, "identity_config": "team.private.json",
              "materials": {"official_template": "original.docx", "report": "report.docx",
                            "presentation": "slides.pptx", "video": "video.mp4",
                            "run_report": "run.md", "originality": "originality.md"}}
    config_path = inputs / "four.json"
    def save():
        config_path.write_text(json.dumps(config), encoding="utf-8")
        identity_path.write_text(json.dumps(identity), encoding="utf-8")
    save()
    return root, inputs, config, identity, config_path, save


def test_exactly_four_entries_and_nested_source_roundtrip(four_bundle):
    root, _, _, identity, config, _ = four_bundle
    result = four.build(config, root, output_subdir="TEST_ONLY-four")
    assert result["status"] == "TEST_ONLY_VERIFIED", result
    assert result["ready_to_submit"] is False and result["platform_review"] == "PENDING"
    output = root / "dist_submission/TEST_ONLY-four"
    archive_path = output / "TEST_ONLY-candidate-HomeTrace.zip"
    assert result["archive_sha256"] == sub.sha256(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == set(four.ARCHIVE_NAMES.values())
        assert len(archive.namelist()) == 4 and archive.testzip() is None
        for name, digest in result["material_hashes"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        with zipfile.ZipFile(io.BytesIO(archive.read(four.ARCHIVE_NAMES["source"]))) as code:
            assert code.testzip() is None
            assert {"README.md", "RUN_TEST_REPORT.md", "OPEN_SOURCE_AND_ORIGINALITY.md", "manifest.sha256"} <= set(code.namelist())
            assert not any("original.docx" in name or "private" in name or ".git" in name for name in code.namelist())
            for line in code.read("manifest.sha256").decode("utf-8").splitlines():
                digest, name = line.split("  ", 1)
                assert hashlib.sha256(code.read(name)).hexdigest() == digest
    audit = (output / "candidate-audit.json").read_text(encoding="utf-8")
    assert "TEST_ONLY_VERIFIED" in audit
    for person in identity["official_fields"]["members"]:
        assert all(person[key] not in audit for key in ("name", "phone", "email"))


def test_preflight_writes_audit_only_then_build_is_possible(four_bundle):
    root, _, _, _, config, _ = four_bundle
    preflight = four.build(config, root, output_subdir="TEST_ONLY-check", check_only=True)
    assert preflight["status"] == "TEST_ONLY_PREFLIGHT_PASSED", preflight
    output = root / "dist_submission/TEST_ONLY-check"
    assert list(output.glob("*.zip")) == []
    assert (output / "preflight-audit.json").exists()
    assert four.build(config, root, output_subdir="TEST_ONLY-check")["status"] == "TEST_ONLY_VERIFIED"


@pytest.mark.parametrize("role", four.MATERIAL_ROLES)
@pytest.mark.parametrize("damage", ["missing", "empty"])
def test_missing_or_empty_material_blocks(four_bundle, role, damage):
    root, inputs, config, _, path, _ = four_bundle
    item = inputs / config["materials"][role]
    item.unlink() if damage == "missing" else item.write_bytes(b"")
    result = four.build(path, root, output_subdir="TEST_ONLY-bad")
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["field"] == "materials"
    assert not list((root / "dist_submission/TEST_ONLY-bad").glob("*.zip"))


@pytest.mark.parametrize("problem", ["identity_mismatch", "template_hash", "unfilled", "bad_table", "extra_role", "traversal", "rules_pdf"])
def test_invalid_table_identity_and_input_contract_rejected(four_bundle, problem):
    root, inputs, config, identity, path, save = four_bundle
    if problem == "identity_mismatch":
        identity["team"]["name"] = "TEST_ONLY mismatched summary"
    elif problem == "template_hash":
        identity["official_template_sha256"] = "0" * 64
    elif problem == "unfilled":
        (inputs / "report.docx").write_bytes((inputs / "original.docx").read_bytes())
    elif problem == "bad_table":
        report = inputs / "report.docx"
        with zipfile.ZipFile(report) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts["word/document.xml"] = parts["word/document.xml"].replace(b'w:w="900"', b'w:w="901"')
        with zipfile.ZipFile(report, "w") as archive:
            for name, value in parts.items():
                archive.writestr(name, value)
    elif problem == "extra_role":
        config["materials"]["secret_extra"] = "team.private.json"
    elif problem == "traversal":
        config["materials"]["report"] = "../report.docx"
    else:
        config["materials"]["run_report"] = "rules.pdf"
        (inputs / "rules.pdf").write_bytes(b"%PDF TEST_ONLY")
    save()
    result = four.build(path, root, output_subdir="TEST_ONLY-invalid")
    assert result["status"] == "BLOCKED"
    expected_field = {"identity_mismatch": "identity_config", "template_hash": "official_table",
                      "unfilled": "official_table", "bad_table": "official_table",
                      "extra_role": "materials", "traversal": "materials", "rules_pdf": "run_report"}[problem]
    assert result["issues"][0]["field"] == expected_field, result
    assert not list((root / "dist_submission/TEST_ONLY-invalid").glob("*.zip"))


@pytest.mark.parametrize("where", ["source", "office_part", "notes", "video"])
def test_actual_local_key_blocked_even_without_recognizable_prefix(four_bundle, where):
    root, inputs, _, _, path, _ = four_bundle
    secret = "TEST_ONLY_LOCAL_" + "z" * 35
    (root / ".env").write_text("HOMETRACE_LLM_API_KEY=" + secret, encoding="utf-8")
    if where == "source":
        (root / "README.md").write_text(secret, encoding="utf-8")
    elif where == "office_part":
        with zipfile.ZipFile(inputs / "slides.pptx", "a") as archive:
            archive.writestr("ppt/media/synthetic-test.bin", secret.encode())
    elif where == "notes":
        (inputs / "run.md").write_text("# TEST_ONLY\n" + secret, encoding="utf-8")
    else:
        video = inputs / "video.mp4"
        value = video.read_bytes()
        # A valid extra MP4 box preserves the TEST_ONLY structural contract.
        payload = secret.encode()
        video.write_bytes(value + (len(payload) + 8).to_bytes(4, "big") + b"free" + payload)
    result = four.build(path, root, output_subdir="TEST_ONLY-key")
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["field"] == ("source" if where == "source" else "material_privacy"), result
    assert secret not in json.dumps(result)


@pytest.mark.parametrize("field", ["name", "email", "phone"])
def test_team_private_identity_is_not_exported_in_source(four_bundle, field):
    root, _, _, identity, path, _ = four_bundle
    value = identity["official_fields"]["members"][0][field]
    (root / "README.md").write_text("# TEST_ONLY\n" + value, encoding="utf-8")
    result = four.build(path, root, output_subdir="TEST_ONLY-contact")
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["field"] == "source_privacy", result
    assert value not in json.dumps(result)


@pytest.mark.parametrize("role", ["run_report", "originality"])
def test_code_bundle_notes_do_not_leak_member_identity(four_bundle, role):
    root, inputs, config, identity, path, _ = four_bundle
    value = identity["official_fields"]["members"][0]["phone"]
    (inputs / config["materials"][role]).write_text(
        "# TEST_ONLY\nSynthetic packaging test note with sufficient readable text.\n" + value,
        encoding="utf-8")
    result = four.build(path, root, output_subdir="TEST_ONLY-notes-contact")
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["field"] == "source_privacy", result
    assert value not in json.dumps(result)


def test_judging_deck_generator_is_allowlisted_and_secret_checked(four_bundle):
    root, _, _, _, path, _ = four_bundle
    tool = root / "tools/create_judging_deck.mjs"
    tool.parent.mkdir()
    tool.write_text("// TEST_ONLY reproducible deck generator\n", encoding="utf-8")
    sources, _ = sub.collect_source(root)
    assert any(e.name.endswith("/tools/create_judging_deck.mjs") for e in sources)
    tool.write_text("// ghp_" + "X" * 40, encoding="utf-8")
    result = four.build(path, root, output_subdir="TEST_ONLY-deck-secret")
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["field"] == "source", result


def test_prior_archive_and_audit_are_not_overwritten(four_bundle):
    root, _, _, _, path, _ = four_bundle
    assert four.build(path, root, output_subdir="TEST_ONLY-repeat")["status"] == "TEST_ONLY_VERIFIED"
    directory = root / "dist_submission/TEST_ONLY-repeat"
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(sub.SubmissionError):
        four.build(path, root, output_subdir="TEST_ONLY-repeat")
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


@pytest.mark.parametrize("directory", ["../escape", "C:/outside", "nested/name", "CON", ".."])
def test_output_path_escape_rejected(four_bundle, directory):
    root, _, _, _, path, _ = four_bundle
    with pytest.raises(sub.SubmissionError):
        four.build(path, root, output_subdir=directory)


def test_unignored_output_refused(four_bundle):
    root, _, _, _, path, _ = four_bundle
    (root / ".gitignore").write_text("local_data/\n", encoding="utf-8")
    with pytest.raises(sub.SubmissionError):
        four.build(path, root, output_subdir="TEST_ONLY-exposed")


def test_reference_template_and_ignored_files_never_in_source_zip(four_bundle):
    root, _, _, _, path, _ = four_bundle
    (root / ".env").write_text("HOMETRACE_LLM_API_KEY=", encoding="utf-8")
    private = root / "local_data"
    private.mkdir()
    for name in ("photo.jpg", "memory.sqlite3", "weights.pt", "rules.pdf", "identity.json"):
        (private / name).write_bytes(b"TEST_ONLY private excluded")
    (root / "unrelated.sqlite3").write_bytes(b"TEST_ONLY DB")
    result = four.build(path, root, output_subdir="TEST_ONLY-exclusions")
    assert result["status"] == "TEST_ONLY_VERIFIED", result
    with zipfile.ZipFile(root / "dist_submission/TEST_ONLY-exclusions/TEST_ONLY-candidate-HomeTrace.zip") as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read(four.ARCHIVE_NAMES["source"]))) as inner:
            assert not any(name.startswith("local_data/") or name.endswith((".pt", ".sqlite3", ".pdf", ".docx")) or name == ".env" for name in inner.namelist())


def test_input_mutation_after_prepare_blocks_publication(four_bundle, monkeypatch):
    root, inputs, _, _, path, _ = four_bundle
    original = four.prepare
    def mutate(*args):
        result = original(*args)
        assert result[0]["status"] != "BLOCKED", result[0]
        (inputs / "report.docx").write_bytes(b"TEST_ONLY changed after validation")
        return result
    monkeypatch.setattr(four, "prepare", mutate)
    result = four.build(path, root, output_subdir="TEST_ONLY-race")
    assert result["status"] == "BLOCKED"
    assert not list((root / "dist_submission/TEST_ONLY-race").glob("*.zip"))


def test_input_mutation_during_validation_blocks(four_bundle, monkeypatch):
    root, inputs, _, _, path, _ = four_bundle
    original = sub.check_video
    def mutate(*args):
        result = original(*args)
        (inputs / "run.md").write_text("# TEST_ONLY\nChanged after report validation.\n", encoding="utf-8")
        return result
    monkeypatch.setattr(sub, "check_video", mutate)
    result = four.build(path, root, output_subdir="TEST_ONLY-validation-race")
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["field"] == "input_integrity", result


@pytest.mark.parametrize("problem", ["duplicate_key", "wrong_type"])
def test_malformed_config_is_redacted_and_blocked(four_bundle, problem):
    root, _, _, _, path, _ = four_bundle
    path.write_text('{"schema_version":1,"schema_version":2}' if problem == "duplicate_key" else '[]', encoding="utf-8")
    result = four.build(path, root, output_subdir="TEST_ONLY-config")
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["field"] == "config"


def test_nested_zip_corruption_is_not_accepted():
    data, hashes = four._zip_bytes([], {"TEST_ONLY.txt": b"synthetic"})
    hashes["TEST_ONLY.txt"] = "0" * 64
    with pytest.raises(sub.SubmissionError):
        four._verify_zip(data, hashes)


def test_duplicate_source_note_names_rejected_before_archive(four_bundle):
    root, inputs, _, _, _, _ = four_bundle
    source = four._entry("04_核心源代码/RUN_TEST_REPORT.md", inputs / "run.md")
    note = four._entry("RUN_TEST_REPORT.md", inputs / "run.md")
    with pytest.raises(sub.SubmissionError):
        four._source_zip([source], [note], {"test_only": True, "checks": {"source": {"commit": "TEST_ONLY"}}})


def test_real_candidate_requires_explicit_source_revision_without_building_fake_submission(four_bundle, monkeypatch):
    root, _, config, _, path, save = four_bundle
    config["test_only"] = False
    save()
    monkeypatch.setattr(sub, "check_video", lambda *_: {"validation": "TEST_ONLY mock for preflight, never build"})
    result, entries, _, _ = four.prepare(path, root)
    assert result["status"] == "BLOCKED" and not entries
    assert result["issues"][0]["field"] == "source", result


def test_platform_flags_do_not_mark_candidate_as_submitted(four_bundle, monkeypatch):
    root, _, config, identity, path, save = four_bundle
    config["test_only"] = False
    config["expected_source_commit"] = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    identity["platform_identity_verified"] = True
    config["ready_to_submit"] = True
    config["uploaded"] = True
    save()
    monkeypatch.setattr(sub, "check_video", lambda *_: {"validation": "TEST_ONLY mock for preflight, never build"})
    # Validate state logic only. Never create a non-TEST_ONLY synthetic archive.
    result, _, _, _ = four.prepare(path, root)
    assert result["status"] == "CANDIDATE_PREFLIGHT_PLATFORM_PENDING", result
    assert result["ready_to_submit"] is False and result["uploaded"] is False
    assert result["platform_review"] == "PENDING" and result["officially_verified"] is False


def test_cli_help_documents_safe_four_file_workflow():
    import sys
    completed = subprocess.run([sys.executable, "-m", "tools.build_four_file_submission", "--help"], capture_output=True, text=True)
    assert completed.returncode == 0
    assert "--output-subdir" in completed.stdout and "--check" in completed.stdout
