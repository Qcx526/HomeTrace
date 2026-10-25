"""Local-only submission preflight and allowlisted, verified ZIP creation.

Automatic checks do not certify official requirements, document completeness,
image privacy, or successful competition upload.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile


PUBLIC_SAMPLES = {
    "box.png", "box_in_scene.png", "apple.jpg", "orange.jpg", "fruits.jpg",
    "history.json", "moved.json", "missing.json", "sources.json", "README.md",
    "LICENSE.opencv.txt", "COPYRIGHT.opencv.txt", "LICENSE_CHANGE_NOTICE.opencv.txt",
}
SOURCE_DOCS = {
    "PRODUCT_BRIEF.md", "ARCHITECTURE.md", "DEMO_ACCEPTANCE.md",
    "P0_IMPLEMENTATION.md", "P1_IMPLEMENTATION.md", "P1_VISION_CHOICE.md",
    "P2_DEMO.md", "P3_DELIVERY.md", "SUBMISSION_TOOL.md", "SUBMISSION_PLAN.md",
    "TEAM_PHOTO_EVALUATION.md", "SUBMISSION_READINESS.md", "REGISTRATION_ROI_EVALUATION.md",
    "OFFICIAL_SUBMISSION.md", "P4_AGENT.md",
}
CONFIRMATIONS = ("privacy_reviewed", "media_truthful", "materials_consistent")
MATERIALS = ("application", "presentation", "video", "run_report", "originality")
MANUAL_CHECKS = ("submission_formats", "archive_naming", "size_limit", "required_attachments", "deadline", "team_identity", "extracted_files_opened")
LIMITATIONS = [
    "The supplied official DOCX is required for submission. Team-authored documents are supplemental; legacy technical candidates do not satisfy the application requirement.",
    "Structural parsing and media decoding cannot determine whether narrative claims or screenshots are true.",
    "Privacy checks exclude private paths and recognizable secret formats; they cannot recognize every private photograph, QR code or personal datum embedded in documents/video.",
    "A verified ZIP is a local candidate, not proof of successful upload. The project owner must extract, open and check it before uploading.",
    "No official archive size limit is assumed; actual bytes are reported.",
]
SECRET = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,}|AKIA[0-9A-Z]{16}")
PLACEHOLDER = re.compile(r"TODO|待\s*(?:团队\s*)?(?:在\s*本地\s*)?(?:填写|补齐|补充)|PLACEHOLDER", re.I)


class SubmissionError(ValueError):
    """A redacted, user-actionable reason why preflight cannot pass."""


@dataclass(frozen=True)
class Entry:
    name: str
    path: Path
    sha256: str
    size: int


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SubmissionError("Duplicate configuration key")
        value[key] = item
    return value


def safe_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SubmissionError("Missing or invalid filename component")
    if len(value) > 80 or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in value) or value.endswith((".", " ")):
        raise SubmissionError("Unsafe filename component")
    if value in (".", "..") or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value):
        raise SubmissionError("Reserved filename component")
    return value


def _no_links(path: Path, root: Path) -> None:
    current = path
    while True:
        if current.is_symlink() or (current.exists() and getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
            raise SubmissionError("Symbolic links or Windows reparse points are not accepted")
        if current == root:
            break
        if current.parent == current:
            raise SubmissionError("Path is outside the configured input directory")
        current = current.parent


def local_file(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise SubmissionError("Provide a relative POSIX material path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise SubmissionError("Material paths cannot traverse outside the configuration directory")
    path = root.joinpath(*relative.parts)
    _no_links(path, root)
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise SubmissionError("Required material is missing or not a regular file")
    if path.stat().st_size == 0:
        raise SubmissionError("Required material is empty")
    return path


def _check_secret(content: bytes) -> None:
    if SECRET.search(content):
        raise SubmissionError("Recognizable credential/private-key material detected; review locally")


def ooxml_text(path: Path, kind: str) -> str:
    if path.suffix.lower() != (".docx" if kind == "word" else ".pptx"):
        raise SubmissionError("Wrong Office file extension")
    required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml" if kind == "word" else "ppt/presentation.xml"}
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(n.casefold() for n in names)) or not required <= set(names):
                raise SubmissionError("Office container has missing or duplicate parts")
            if sum(i.file_size for i in infos) > 128 * 1024 * 1024:
                raise SubmissionError("Office expansion exceeds the local validation safety limit (not an event rule)")
            text = []
            for item in infos:
                if item.is_dir():
                    continue
                if item.filename.startswith("/") or "\\" in item.filename or ".." in PurePosixPath(item.filename).parts:
                    raise SubmissionError("Unsafe path inside Office container")
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise SubmissionError("Encrypted or linked Office parts are not accepted")
                if "vbaproject" in item.filename.lower() or "/embeddings/" in item.filename.lower():
                    raise SubmissionError("Office macros/embedded objects require removal before packaging")
                if item.filename.endswith((".xml", ".rels")):
                    data = archive.read(item)
                    _check_secret(data)
                    element = ET.fromstring(data)
                    if kind == "word" and item.filename == "word/document.xml" or kind == "ppt" and re.fullmatch(r"ppt/slides/slide\d+\.xml", item.filename):
                        text.extend(node.text for node in element.iter() if node.tag.rsplit("}", 1)[-1] == "t" and node.text)
            if archive.testzip() is not None:
                raise SubmissionError("Office container CRC check failed")
            content = " ".join(text).strip()
            if len(content) < 20:
                raise SubmissionError("Office document has insufficient readable text")
            return content
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError) as exc:
        raise SubmissionError("Office document cannot be structurally read") from exc


def check_video(path: Path, test_only: bool) -> dict:
    if path.suffix.lower() != ".mp4":
        raise SubmissionError("Video must use MP4")
    boxes = []
    length = path.stat().st_size
    with path.open("rb") as stream:
        offset = 0
        while offset < length:
            header = stream.read(8)
            if len(header) != 8:
                raise SubmissionError("Truncated MP4 box")
            size, tag = int.from_bytes(header[:4], "big"), header[4:]
            header_size = 8
            if size == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    raise SubmissionError("Truncated extended MP4 box")
                size, header_size = int.from_bytes(extended, "big"), 16
            elif size == 0:
                size = length - offset
            if size < header_size or offset + size > length:
                raise SubmissionError("Invalid MP4 box size")
            if size > header_size:
                boxes.append(tag)
            offset += size
            stream.seek(offset)
    if not {b"ftyp", b"moov", b"mdat"} <= set(boxes):
        raise SubmissionError("MP4 must contain nonempty ftyp, moov and mdat boxes")
    if test_only:
        return {"validation": "TEST_ONLY box structure; synthetic fixture is not playable media"}
    probe, decoder = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not probe or not decoder:
        raise SubmissionError("Install ffprobe and ffmpeg for full validation of final MP4")
    try:
        result = subprocess.run([probe, "-protocol_whitelist", "file,pipe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], capture_output=True, timeout=60)
        metadata = json.loads(result.stdout)
        if result.returncode or float(metadata.get("format", {}).get("duration", 0)) <= 0 or not any(s.get("codec_type") == "video" for s in metadata.get("streams", [])):
            raise SubmissionError("MP4 has no readable video stream and positive duration")
        decoded = subprocess.run([decoder, "-protocol_whitelist", "file,pipe", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, timeout=300)
        if decoded.returncode:
            raise SubmissionError("MP4 full decoding failed")
        return {"validation": "ffprobe and full ffmpeg decode", "duration_seconds": float(metadata["format"]["duration"])}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, SubmissionError):
            raise
        raise SubmissionError("MP4 validation could not complete") from exc


def check_report(path: Path) -> None:
    if path.suffix.lower() == ".md":
        content = path.read_bytes()
        _check_secret(content)
        if len(content.decode("utf-8").strip()) < 40:
            raise SubmissionError("Markdown report is empty or too short")
    elif path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise SubmissionError("Install optional pypdf to validate PDF, or supply a UTF-8 Markdown report") from exc
        try:
            pdf = PdfReader(path, strict=True)
            if pdf.is_encrypted or len(pdf.pages) < 1:
                raise SubmissionError("PDF is encrypted or has no readable pages")
        except Exception as exc:
            raise SubmissionError("PDF cannot be read") from exc
    else:
        raise SubmissionError("Report must be UTF-8 Markdown or readable PDF")


def source_allowed(name: str) -> bool:
    path = PurePosixPath(name)
    if name == ".env.example":
        return True
    if any(part.startswith(".") or part in {"__pycache__", "local_data", "artifacts", "dist_submission", "node_modules"} for part in path.parts):
        return False
    if name in {"README.md", "AGENTS.md", "pyproject.toml", "LICENSE", "LICENSE.md", "config.yaml"}:
        return True
    if len(path.parts) == 2 and path.parts[0] == "docs" and path.name in SOURCE_DOCS:
        return True
    if path.parts[:2] == ("examples", "recorded_images") and len(path.parts) == 3:
        return path.name in PUBLIC_SAMPLES
    if name in {"examples/submission_config.example.json", "examples/demo_case.example.json"}:
        return True
    if path.parts[0] == "src" and path.suffix in {".py", ".json", ".html", ".css", ".js"}:
        return True
    return path.parts[0] in {"tests", "tools"} and path.suffix in {".py", ".cjs"}


def collect_source(root: Path, expected_commit: str | None = None) -> tuple[list[Entry], dict]:
    local_keys = []
    key = os.environ.get("HOMETRACE_LLM_API_KEY", "")
    if len(key) >= 8:
        local_keys.append(key.encode())
    env_path = root / ".env"
    if env_path.is_file() and not env_path.is_symlink():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("HOMETRACE_LLM_API_KEY="):
                key = line.split("=",1)[1].strip().strip("\"'")
                if len(key) >= 8:
                    local_keys.append(key.encode())
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
        if result.returncode:
            raise SubmissionError("Source directory must be an accessible Git repository")
        return result.stdout
    commit = git("rev-parse", "HEAD").decode().strip()
    dirty = bool(git("status", "--porcelain"))
    if expected_commit and expected_commit != commit:
        raise SubmissionError("Configured source commit differs from repository HEAD")
    candidates = {}
    for row in git("ls-files", "--stage", "-z").split(b"\0"):
        if row:
            attributes, encoded = row.split(b"\t", 1)
            name = encoded.decode("utf-8")
            mode, _, stage = attributes.decode().split()
            if source_allowed(name) and (mode not in {"100644", "100755"} or stage != "0"):
                raise SubmissionError("Source allowlist contains a link or unmerged file")
            candidates[name] = "tracked"
    for encoded in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if encoded:
            candidates[encoded.decode("utf-8")] = "untracked_working_tree"
    entries = []
    untracked = 0
    for name, origin in sorted(candidates.items()):
        if not source_allowed(name):
            continue
        path = local_file(root, name)
        if any(key in path.read_bytes() for key in local_keys):
            raise SubmissionError("Source contains a configured private API key")
        untracked += origin == "untracked_working_tree"
        if name == ".env.example" and path.read_text(encoding="utf-8-sig").strip() != "HOMETRACE_LLM_API_KEY=":
            raise SubmissionError(".env.example must contain only the empty API key example")
        if name == "config.yaml":
            text = path.read_text(encoding="utf-8-sig")
            if re.search(r"(?i)api[_-]?key|password|secret|token\s*:", text):
                raise SubmissionError("config.yaml may not contain secret fields")
        if path.suffix in {".py", ".json", ".md", ".txt", ".toml", ".html", ".js", ".cjs", ".css", ".yaml"}:
            _check_secret(path.read_bytes())
        entries.append(Entry("04_核心源代码/" + name, path, sha256(path), path.stat().st_size))
    names = {entry.name.removeprefix("04_核心源代码/") for entry in entries}
    if not {"README.md", "pyproject.toml", "src/hometrace/__main__.py"} <= names:
        raise SubmissionError("Source snapshot is missing the minimum runnable project files")
    digest = hashlib.sha256("".join(f"{e.sha256}  {e.name}\n" for e in entries).encode("utf-8")).hexdigest()
    return entries, {"commit": commit, "dirty": dirty, "snapshot": "working_tree", "snapshot_sha256": digest, "untracked_allowlisted_files": untracked, "file_count": len(entries), "source_policy": "Git tracked and nonignored working files, filtered through the source allowlist; private data, databases, caches, logs and repository metadata are excluded. File hashes describe the actual snapshot, which may differ from HEAD."}


def _entry(name: str, path: Path) -> Entry:
    return Entry(name, path, sha256(path), path.stat().st_size)


def prepare(config_path: Path, repo_root: Path) -> tuple[dict, list[Entry], str | None]:
    report = {"schema_version": 1, "status": "BLOCKED", "ready_to_submit": False, "officially_verified": False, "uploaded": False, "created_at_utc": datetime.now(timezone.utc).isoformat(), "issues": [], "warnings": [], "checks": {}, "limitations": LIMITATIONS}
    entries = []
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"), object_pairs_hook=_object)
        if not isinstance(config, dict) or type(config.get("schema_version")) is not int or config.get("schema_version") != 1 or type(config.get("test_only")) is not bool:
            raise SubmissionError("Configuration requires schema_version 1 and boolean test_only")
    except (OSError, UnicodeError, json.JSONDecodeError, SubmissionError) as exc:
        report["issues"].append({"field": "config", "reason": str(exc) if isinstance(exc, SubmissionError) else "Configuration cannot be read"})
        return report, entries, None
    test_only = config["test_only"]
    report["test_only"] = test_only
    team = config.get("team", {})
    basename = "TEST_ONLY-candidate-HomeTrace.zip" if test_only else "candidate-HomeTrace.zip"
    try:
        values = [safe_name(team.get(key)) for key in ("name", "work_name", "captain_name", "captain_phone")]
        if not re.fullmatch(r"1[3-9][0-9]{9}", values[-1]):
            raise SubmissionError("Captain phone must contain 11 mainland mobile digits")
        if any(PLACEHOLDER.search(v) or re.search(r"示例|测试|假队长", v) for v in values) or values[-1] == "13800000000" or config.get("identity_confirmed") is not True:
            raise SubmissionError("Identity is incomplete or not locally confirmed")
        if config.get("use_private_submission_name") is True and not test_only:
            basename = "实物组-" + "-".join(values) + ".zip"
        report["checks"]["identity"] = "Locally confirmed; values redacted"
    except (SubmissionError, AttributeError) as exc:
        report["warnings"].append({"field": "team", "reason": "Identity missing, placeholder or unconfirmed: neutral candidate filename used; complete and verify locally before uploading"})
    document_source = config.get("document_source", "official_template")
    if not isinstance(document_source, str) or document_source not in {"team_authored", "official_template"}:
        report["issues"].append({"field": "document_source", "reason": "Choose team_authored or official_template"})
    report["document_source"] = document_source
    report["official_application"] = "BLOCKED"
    if document_source == "team_authored":
        report["warnings"].append({"field": "official_application", "reason": "Legacy technical candidate only: team-authored DOCX is supplemental and cannot replace the mandatory official form"})
    manual = config.get("submission_page_checks", {})
    report["manual_checks"] = {key: "locally_confirmed_not_automatically_verified" if isinstance(manual, dict) and manual.get(key) is True else "PENDING" for key in MANUAL_CHECKS}
    confirmations = config.get("confirmations", {})
    report["content_review"] = {}
    for key in CONFIRMATIONS:
        report["content_review"][key] = "locally_confirmed_not_automatically_verified" if isinstance(confirmations, dict) and confirmations.get(key) is True else "PENDING"
        if not isinstance(confirmations, dict) or confirmations.get(key) is not True:
            report["warnings"].append({"field": key, "reason": "Content review pending; candidate may be built, but review is required before uploading"})
    if document_source == "official_template" and (not isinstance(config.get("official_source"), str) or not config["official_source"].strip()):
        report["issues"].append({"field": "official_source", "reason": "Record the source locally when claiming use of an official template"})
    paths, texts = {}, {}
    materials = config.get("materials", {})
    for role in MATERIALS + (("official_template",) if document_source == "official_template" else ()):
        try:
            path = local_file(config_path.resolve().parent, materials.get(role))
            if path.suffix.lower() == ".pdf" and re.search(r"规则|赛事说明|比赛说明|赛题说明|rules", path.name, re.I):
                raise SubmissionError("Competition rules PDF must not be included in the submission archive")
            paths[role] = path
            if role in {"official_template", "application"}:
                texts[role] = ooxml_text(path, "word")
            elif role == "presentation":
                texts[role] = ooxml_text(path, "ppt")
            elif role == "video":
                report["checks"]["video"] = check_video(path, test_only)
            else:
                check_report(path)
            if role != "official_template" and path.suffix.lower() in {".md", ".docx", ".pptx"}:
                content = texts.get(role, path.read_text(encoding="utf-8") if path.suffix.lower() == ".md" else "")
                if PLACEHOLDER.search(content):
                    report["warnings"].append({"field": role, "reason": "Placeholder text detected; permitted in a candidate, requires local content review before upload"})
            report["checks"].setdefault(role, {}).update({"readable": True, "bytes": path.stat().st_size, "sha256": sha256(path)})
        except (SubmissionError, OSError, UnicodeError, AttributeError) as exc:
            report["issues"].append({"field": role, "reason": str(exc) if isinstance(exc, SubmissionError) else "Required material cannot be read"})
    if "official_template" in paths:
        expected = config.get("official_template_sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(paths["official_template"]) != expected:
            report["issues"].append({"field": "official_template_sha256", "reason": "Expected official-template SHA256 is missing or differs"})
    if texts.get("application") and texts.get("application") == texts.get("official_template"):
        report["issues"].append({"field": "application", "reason": "Application text is identical to the original template; filling has not been demonstrated"})
    if document_source == "official_template" and {"official_template", "application"} <= paths.keys():
        try:
            from .official_submission import verify_filled, OfficialFormError
            report["checks"]["official_form"] = verify_filled(paths["official_template"], paths["application"], config.get("official_template_sha256"), config.get("official_fields"))
            fields = config["official_fields"]
            if not isinstance(team, dict) or any(team.get(k) != v for k, v in {"name": fields["team_name"], "work_name": fields["project_name"], "captain_name": fields["members"][0]["name"], "captain_phone": fields["members"][0]["phone"]}.items()) or config.get("identity_confirmed") is not True:
                raise OfficialFormError("Package identity and confirmed official-form fields differ")
            report["official_application"] = "CONTENT_VERIFIED_VISUAL_REVIEW_PENDING"
        except (OfficialFormError, TypeError, KeyError, IndexError) as exc:
            report["issues"].append({"field": "official_application", "reason": str(exc) if isinstance(exc, OfficialFormError) else "Official fields are missing or malformed"})
    if isinstance(materials, dict) and materials.get("technical_supplement"):
        try:
            supplement = local_file(config_path.resolve().parent, materials["technical_supplement"])
            ooxml_text(supplement, "word")
            if supplement in (paths.get("application"), paths.get("official_template")):
                raise SubmissionError("Technical supplement must be separate from original and filled official forms")
            paths["technical_supplement"] = supplement
        except (SubmissionError, OSError) as exc:
            report["issues"].append({"field": "technical_supplement", "reason": str(exc) if isinstance(exc, SubmissionError) else "Supplement cannot be read"})
    try:
        application_name = safe_name(config.get("application_filename", "01_HomeTrace官方初赛作品文档.docx"))
        if not application_name.lower().endswith(".docx"):
            raise SubmissionError("Application filename must end in .docx")
        archive_names = {
            "application": application_name, "presentation": "02_HomeTrace技术展示.pptx",
            "video": "03_HomeTrace演示视频.mp4", "originality": "06_开源技术与原创性说明" + paths.get("originality", Path("x.md")).suffix.lower(),
            "run_report": "05_运行说明与测试报告" + paths.get("run_report", Path("x.md")).suffix.lower(),
        }
        if document_source == "team_authored":
            archive_names["application"] = "07_补充技术说明书_缺少官方主表.docx"
        if "technical_supplement" in paths:
            archive_names["technical_supplement"] = "07_补充_HomeTrace作品设计与技术说明书.docx"
        if "official_template" in paths and any(paths.get(role) == paths["official_template"] or (paths.get(role) and sha256(paths[role]) == sha256(paths["official_template"])) for role in archive_names):
            raise SubmissionError("The unfilled official original cannot be packaged as any material")
        entries.extend(_entry(name, paths[role]) for role, name in archive_names.items() if role in paths)
    except SubmissionError as exc:
        report["issues"].append({"field": "application_filename", "reason": str(exc)})
    try:
        sources, source_info = collect_source(repo_root, config.get("expected_source_commit"))
        entries.extend(sources)
        report["checks"]["source"] = source_info
    except (SubmissionError, OSError) as exc:
        report["issues"].append({"field": "source", "reason": str(exc) if isinstance(exc, SubmissionError) else "Source export failed"})
    names = [entry.name.casefold() for entry in entries] + ["manifest.sha256", "source_info.json", "pre_upload_review.json", "readme_提交材料清单.txt"]
    if len(names) != len(set(names)):
        report["issues"].append({"field": "archive", "reason": "Duplicate archive filename"})
    if not report["issues"]:
        report["status"] = "TEST_ONLY_PREFLIGHT_PASSED" if test_only else "CANDIDATE_PREFLIGHT_PASSED"
        report["checks"]["entry_count"] = len(entries)
    return report, entries, basename


def build(config_path: Path, repo_root: Path, *, check_only: bool = False) -> dict:
    repo_root = repo_root.resolve()
    output = repo_root / "dist_submission"
    _no_links(output, repo_root)
    output.mkdir(exist_ok=True)
    report, entries, filename = prepare(config_path, repo_root)
    audit = output / "submission-audit.json"
    _no_links(audit, repo_root)
    _no_links(output / "archive.sha256", repo_root)
    if not report["issues"] and not check_only:
        target = output / filename
        if target.exists():
            report["issues"].append({"field": "archive", "reason": "Candidate already exists; archive the previous ZIP locally before retrying"})
            report["status"] = "BLOCKED"
        else:
            temporary = output / (".partial-" + uuid.uuid4().hex + ".zip")
            try:
                generated = {
                    "SOURCE_INFO.json": json_bytes(report["checks"]["source"]),
                    "PRE_UPLOAD_REVIEW.json": json_bytes({"candidate_only": True, "test_only": report["test_only"], "officially_verified": False, "uploaded": False, "document_source": report["document_source"], "official_application": report["official_application"], "manual_checks": report["manual_checks"], "content_review": report["content_review"], "warnings": report["warnings"], "limitations": LIMITATIONS}),
                    "README_提交材料清单.txt": ("TEST_ONLY — synthetic test archive, NOT a competition submission.\n" if report["test_only"] else "Local candidate archive. Extract, open and manually review before uploading.\n") .encode("utf-8") + "\n".join(entry.name for entry in entries).encode("utf-8") + b"\n",
                }
                expected = {entry.name: entry.sha256 for entry in entries}
                expected.update({name: hashlib.sha256(data).hexdigest() for name, data in generated.items()})
                manifest = "".join(f"{value}  {name}\n" for name, value in sorted(expected.items())).encode("utf-8")
                generated["manifest.sha256"] = manifest
                expected["manifest.sha256"] = hashlib.sha256(manifest).hexdigest()
                with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                    for entry in sorted(entries, key=lambda e: e.name):
                        _no_links(entry.path, Path(entry.path.anchor))
                        if sha256(entry.path) != entry.sha256:
                            raise SubmissionError("Material changed after validation")
                        archive.write(entry.path, entry.name)
                    for name, data in sorted(generated.items()):
                        archive.writestr(name, data)
                with zipfile.ZipFile(temporary) as archive:
                    if archive.testzip() or set(archive.namelist()) != set(expected):
                        raise SubmissionError("ZIP CRC or entry check failed")
                    for name, value in expected.items():
                        with archive.open(name) as stream:
                            actual = hashlib.file_digest(stream, "sha256").hexdigest()
                        if actual != value:
                            raise SubmissionError("ZIP SHA256 verification failed")
                temporary.rename(target)
                report.update({"status": "TEST_ONLY_VERIFIED" if report["test_only"] else "VERIFIED_CANDIDATE_REQUIRES_OWNER_REVIEW", "archive_created": True, "archive_bytes": target.stat().st_size, "archive_sha256": sha256(target), "verified_entries": len(expected), "crc_and_sha256_verified": True})
                (output / "archive.sha256").write_text(report["archive_sha256"] + "\n", encoding="ascii")
            except (OSError, SubmissionError, zipfile.BadZipFile) as exc:
                report["issues"].append({"field": "archive", "reason": str(exc) if isinstance(exc, SubmissionError) else "Archive writing or verification failed"})
                report["status"] = "BLOCKED"
            finally:
                if temporary.exists():
                    temporary.unlink()
    audit.write_bytes(json_bytes(report))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a local verified HomeTrace submission candidate, never upload it")
    parser.add_argument("--config", type=Path, required=True, help="Private local JSON; material paths are relative to its directory")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="Write a preflight audit only; do not create ZIP")
    args = parser.parse_args(argv)
    try:
        report = build(args.config, args.repo_root, check_only=args.check)
    except (OSError, SubmissionError) as exc:
        print("BLOCKED: local output/configuration could not be accessed", file=sys.stderr)
        return 2
    # Do not print identity fields, private paths, final filename or document text.
    print(report["status"])
    for issue in report["issues"]:
        print(f"- {issue['field']}: {issue['reason']}")
    for warning in report["warnings"]:
        print(f"- Pending {warning['field']}: {warning['reason']}")
    print("Submission-page review remains manual; officially_verified=false, uploaded=false.")
    print("Local audit: dist_submission/submission-audit.json")
    print("Owner must extract/open and verify the candidate; no upload was performed.")
    return 2 if report["status"] == "BLOCKED" else 0
