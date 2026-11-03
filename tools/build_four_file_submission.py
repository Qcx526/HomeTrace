"""Build a local candidate containing report, slides, video and one source ZIP.

The official identity table is checked against the supplied original independently
of the appended paper. This utility never uploads, certifies platform rules, or
overwrites earlier materials. The external audit is not a fifth submission item.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

from hometrace import submission as sub

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ARCHIVE_NAMES = {
    "report": "01_HomeTrace作品报告.docx",
    "presentation": "02_HomeTrace技术展示.pptx",
    "video": "03_HomeTrace演示视频.mp4",
    "source": "04_HomeTrace相关代码.zip",
}
MATERIAL_ROLES = ("official_template", "report", "presentation", "video", "run_report", "originality")


def _json(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=sub._object)
    if not isinstance(value, dict):
        raise sub.SubmissionError("Configuration must be a JSON object")
    return value


def _private_keys(root):
    values = [os.environ.get("HOMETRACE_LLM_API_KEY", "")]
    env = root / ".env"
    if env.exists():
        sub._no_links(env, root)
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("HOMETRACE_LLM_API_KEY="):
                values.append(line.split("=", 1)[1].strip().strip("\"'"))
    return tuple(value.encode("utf-8") for value in values if len(value) >= 8)


def _scan_bytes(content, keys):
    sub._check_secret(content)
    if any(key in content for key in keys):
        raise sub.SubmissionError("Configured private API key detected in a packaged file")


def _scan_file(path, keys):
    _scan_bytes(path.read_bytes(), keys)
    if path.suffix.lower() in {".docx", ".pptx"}:
        with zipfile.ZipFile(path) as archive:
            for part in archive.infolist():
                if not part.is_dir():
                    _scan_bytes(archive.read(part), keys)


def _read_unchanged(entry):
    sub._no_links(entry.path, Path(entry.path.anchor))
    data = entry.path.read_bytes()
    if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
        raise sub.SubmissionError("Input changed after validation; re-run with a new output directory")
    return data


def _entry(name, path):
    return sub.Entry(name, path, sub.sha256(path), path.stat().st_size)


def _validate_identity(identity):
    fields = identity.get("official_fields")
    team = identity.get("team")
    if not isinstance(fields, dict) or not isinstance(team, dict):
        raise sub.SubmissionError("Private identity configuration is incomplete")
    try:
        expected = {"name": fields["team_name"], "work_name": fields["project_name"],
                    "captain_name": fields["members"][0]["name"],
                    "captain_phone": fields["members"][0]["phone"]}
    except (KeyError, TypeError, IndexError) as exc:
        raise sub.SubmissionError("Private identity configuration is incomplete") from exc
    if any(team.get(name) != value for name, value in expected.items()):
        raise sub.SubmissionError("Team summary differs from the official identity fields")
    return fields


def prepare(config_path, repo_root):
    """Validate all inputs without writing archives or exposing private fields."""
    config_path, repo_root = Path(config_path).absolute(), Path(repo_root).absolute()
    sub._no_links(config_path, Path(config_path.anchor))
    sub._no_links(repo_root, Path(repo_root.anchor))
    report = {"schema_version": 1, "status": "BLOCKED", "ready_to_submit": False,
              "officially_verified": False, "uploaded": False, "platform_review": "PENDING",
              "created_at_utc": datetime.now(timezone.utc).isoformat(), "issues": [], "checks": {}}
    field = "config"
    try:
        input_guard = {config_path: sub.sha256(config_path)}
        config = _json(config_path)
        if type(config.get("schema_version")) is not int or config["schema_version"] != 1 or type(config.get("test_only")) is not bool:
            raise sub.SubmissionError("Require schema_version 1 and a boolean test_only")
        report["test_only"] = config["test_only"]
        root = config_path.parent
        field = "identity_config"
        identity_path = sub.local_file(root, config.get("identity_config"))
        input_guard[identity_path] = sub.sha256(identity_path)
        identity = _json(identity_path)
        fields = _validate_identity(identity)
        materials = config.get("materials")
        field = "materials"
        if not isinstance(materials, dict) or set(materials) != set(MATERIAL_ROLES):
            raise sub.SubmissionError("Require exactly the six supported material input roles")
        paths = {role: sub.local_file(root, materials[role]) for role in MATERIAL_ROLES}
        if len(set(paths.values())) != len(paths):
            raise sub.SubmissionError("Each material role must use a distinct input file")
        input_guard.update({path: sub.sha256(path) for path in paths.values()})
        for role in ("official_template", "report", "presentation"):
            field = role
            sub.ooxml_text(paths[role], "ppt" if role == "presentation" else "word")
        field = "official_table"
        # Import lazily so --help needs only the base project installation.
        from tools.create_judging_report import verify_report_table
        report["checks"]["official_table"] = verify_report_table(
            paths["official_template"], paths["report"],
            identity.get("official_template_sha256"), fields)
        if sub.sha256(paths["report"]) == sub.sha256(paths["official_template"]):
            raise sub.SubmissionError("The unfilled official template cannot be submitted as the report")
        for role in ("run_report", "originality"):
            field = role
            if paths[role].suffix.lower() != ".md":
                raise sub.SubmissionError("Code-bundle notes must be UTF-8 Markdown, not competition rules PDFs")
            sub.check_report(paths[role])
        field = "video"
        report["checks"]["video"] = sub.check_video(paths["video"], config["test_only"])
        field = "source"
        expected_commit = config.get("expected_source_commit")
        if not config["test_only"] and not (isinstance(expected_commit, str) and re.fullmatch(r"[0-9a-f]{40}", expected_commit)):
            raise sub.SubmissionError("A real candidate must declare the complete expected source commit")
        sources, source_info = sub.collect_source(repo_root, expected_commit)
        report["checks"]["source"] = source_info
        keys = _private_keys(repo_root)
        field = "material_privacy"
        for path in paths.values():
            _scan_file(path, keys)
        contacts = tuple(p[k].encode("utf-8") for p in fields["members"] for k in ("name", "email", "phone"))
        field = "source_privacy"
        for source in sources:
            data = _read_unchanged(source)
            _scan_bytes(data, keys)
            if any(value in data for value in contacts):
                raise sub.SubmissionError("A team contact appears in source files; remove the private field")
        for role in ("run_report", "originality"):
            if any(value in paths[role].read_bytes() for value in contacts):
                raise sub.SubmissionError("A team identity appears in source-bundle notes; keep it in the official report")
        field = "input_integrity"
        for path, digest in input_guard.items():
            sub._no_links(path, Path(path.anchor))
            if sub.sha256(path) != digest:
                raise sub.SubmissionError("Input changed during validation; retry only after inputs are stable")
        entries = {role: sub.Entry(ARCHIVE_NAMES[role], paths[role], input_guard[paths[role]], paths[role].stat().st_size)
                   for role in ("report", "presentation", "video")}
        notes = [sub.Entry("RUN_TEST_REPORT.md", paths["run_report"], input_guard[paths["run_report"]], paths["run_report"].stat().st_size),
                 sub.Entry("OPEN_SOURCE_AND_ORIGINALITY.md", paths["originality"], input_guard[paths["originality"]], paths["originality"].stat().st_size)]
        report["checks"]["materials"] = {role: {"sha256": entry.sha256, "bytes": entry.size}
                                            for role, entry in entries.items()}
        report["checks"]["identity"] = "SUPPLIED_FIELDS_AND_OFFICIAL_TABLE_MATCH"
        report["checks"]["secrets"] = "Known local API key and recognizable secret formats checked"
        report["status"] = "TEST_ONLY_PREFLIGHT_PASSED" if config["test_only"] else "CANDIDATE_PREFLIGHT_PLATFORM_PENDING"
        report["remaining_owner_checks"] = ["Confirm the team fields against the registration page",
                                            "Review report, slides and video",
                                            "Verify platform naming, attachments, size and deadline",
                                            "Extract and open all four files before upload"]
        return report, entries, sources, notes
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, ImportError) as exc:
        # Document/config contents, paths, contacts and credentials never enter the audit.
        reason = str(exc) if isinstance(exc, sub.SubmissionError) else "Validation failed; inspect this input locally"
        report["issues"].append({"field": field, "reason": reason})
        return report, {}, [], []


def _zip_bytes(entries, generated):
    expected = {e.name: e.sha256 for e in entries}
    expected.update({name: hashlib.sha256(data).hexdigest() for name, data in generated.items()})
    if len(expected) != len(entries) + len(generated) or len({n.casefold() for n in expected}) != len(expected):
        raise sub.SubmissionError("Duplicate archive member")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            archive.writestr(entry.name, _read_unchanged(entry))
        for name, data in generated.items():
            archive.writestr(name, data)
    data = stream.getvalue()
    _verify_zip(data, expected)
    return data, expected


def _verify_zip(data, expected):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() or len(archive.namelist()) != len(expected) or set(archive.namelist()) != set(expected):
            raise sub.SubmissionError("Archive member or CRC verification failed")
        for name, digest in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise sub.SubmissionError("Archive member SHA256 verification failed")


def _source_zip(sources, notes, report):
    entries = [sub.Entry(e.name.removeprefix("04_核心源代码/"), e.path, e.sha256, e.size) for e in sources] + notes
    generated = {"SOURCE_INFO.json": sub.json_bytes(report["checks"]["source"]),
                 "DELIVERY_STATUS.json": sub.json_bytes({"status": "TEST_ONLY" if report["test_only"] else "CANDIDATE_PLATFORM_PENDING",
                     "ready_to_submit": False, "officially_verified": False, "uploaded": False,
                     "source_commit": report["checks"]["source"]["commit"]})}
    hashes = {e.name: e.sha256 for e in entries}
    hashes.update({name: hashlib.sha256(data).hexdigest() for name, data in generated.items()})
    if len(hashes) != len(entries) + len(generated):
        raise sub.SubmissionError("Source archive notes conflict with a source filename")
    generated["manifest.sha256"] = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())).encode("utf-8")
    return _zip_bytes(entries, generated)


def _outputs(repo_root, output_subdir, check_only):
    output = repo_root / "dist_submission" / sub.safe_name(output_subdir)
    sub._no_links(output, repo_root)
    audit = output / ("preflight-audit.json" if check_only else "candidate-audit.json")
    for path in (output / "candidate-HomeTrace.zip", output / "TEST_ONLY-candidate-HomeTrace.zip", audit):
        sub._no_links(path, repo_root)
        result = subprocess.run(["git", "-C", str(repo_root), "check-ignore", "--quiet", "--", path.relative_to(repo_root).as_posix()], capture_output=True)
        if result.returncode:
            raise sub.SubmissionError("Candidate ZIP and audit outputs must be Git ignored")
    if audit.exists() or (not check_only and any(output.glob("*candidate-HomeTrace.zip"))):
        raise sub.SubmissionError("Output already exists; use a new output directory")
    return output, audit


def build(config_path, repo_root, *, output_subdir, check_only=False):
    repo_root = Path(repo_root).absolute()
    sub._no_links(repo_root, Path(repo_root.anchor))
    output, audit = _outputs(repo_root, output_subdir, check_only)
    report, entries, sources, notes = prepare(config_path, repo_root)
    output.mkdir(parents=True, exist_ok=True)
    if report["status"] != "BLOCKED" and not check_only:
        target = output / (("TEST_ONLY-" if report["test_only"] else "") + "candidate-HomeTrace.zip")
        try:
            source_data, source_hashes = _source_zip(sources, notes, report)
            archive_data, hashes = _zip_bytes(list(entries.values()), {ARCHIVE_NAMES["source"]: source_data})
            if set(hashes) != set(ARCHIVE_NAMES.values()) or len(hashes) != 4:
                raise sub.SubmissionError("Exactly four top-level deliverables are required")
            with tempfile.TemporaryDirectory(prefix="four-file-", dir=output) as temporary:
                partial = Path(temporary) / "candidate.partial"
                partial.write_bytes(archive_data)
                _verify_zip(partial.read_bytes(), hashes)
                # An atomic exclusive hard link publishes only the already verified file.
                # Both paths are on the same filesystem; an existing target is never replaced.
                os.link(partial, target)
            _verify_zip(target.read_bytes(), hashes)
            with zipfile.ZipFile(target) as outer:
                _verify_zip(outer.read(ARCHIVE_NAMES["source"]), source_hashes)
            report.update(status="TEST_ONLY_VERIFIED" if report["test_only"] else "CANDIDATE_PLATFORM_PENDING",
                          archive_sha256=sub.sha256(target), archive_bytes=target.stat().st_size,
                          archive_created=True, verified_entries=4, crc_and_sha256_verified=True,
                          material_hashes=hashes, source_zip_entries=len(source_hashes),
                          source_zip_crc_and_sha256_verified=True)
        except (ValueError, OSError, zipfile.BadZipFile):
            report["status"] = "BLOCKED"
            report["issues"].append({"field": "archive", "reason": "Input mutation or archive validation/write failure; use a new output directory"})
    with audit.open("xb") as stream:
        stream.write(sub.json_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Private JSON; identity_config and materials use paths relative to this JSON")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-subdir", required=True, help="New single directory name below Git ignored dist_submission")
    parser.add_argument("--check", action="store_true", help="Validate and write preflight-audit.json, without creating a ZIP")
    args = parser.parse_args(argv)
    try:
        report = build(args.config, args.repo_root, output_subdir=args.output_subdir, check_only=args.check)
    except (ValueError, OSError):
        print("BLOCKED: output paths are unsafe, not ignored, or already exist.")
        return 2
    print(report["status"])
    print("Four deliverables; platform review pending. No upload performed.")
    for issue in report["issues"]:
        print(issue["field"] + ": " + issue["reason"])
    return 2 if report["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
