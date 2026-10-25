"""Joint official-form and Agent export checks use synthetic TEST_ONLY inputs."""

import hashlib
import json
import zipfile

import pytest

from hometrace import submission as sub
from test_official_submission import official_bundle
from test_submission import bundle


def add_agent_inputs(root):
    (root / "config.yaml").write_text("llm:\n  model: synthetic-test-only\n", encoding="utf-8")
    (root / ".env.example").write_text("HOMETRACE_LLM_API_KEY=\n", encoding="utf-8")


def test_official_archive_keeps_agent_config_and_excludes_private_inputs(bundle):
    root, _, config, path, _ = official_bundle(bundle)
    add_agent_inputs(root)
    private_values = {
        ".env": "HOMETRACE_LLM_API_KEY=synthetic-private-export-key",
        "model.pt": "TEST_ONLY model placeholder",
        "memory.sqlite3": "TEST_ONLY database placeholder",
        "local_data/private.jpg": "TEST_ONLY private-photo placeholder",
    }
    for name, text in private_values.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    report = sub.build(path, root)

    assert report["status"] == "TEST_ONLY_VERIFIED"
    assert report["official_application"] == "CONTENT_VERIFIED_VISUAL_REVIEW_PENDING"
    assert not report["ready_to_submit"] and not report["officially_verified"] and not report["uploaded"]
    with zipfile.ZipFile(root / "dist_submission/TEST_ONLY-candidate-HomeTrace.zip") as archive:
        assert archive.testzip() is None
        prefix = "04_核心源代码/"
        assert archive.read(prefix + "config.yaml") == (root / "config.yaml").read_bytes()
        assert archive.read(prefix + ".env.example") == (root / ".env.example").read_bytes()
        assert archive.read(prefix + ".env.example").strip() == b"HOMETRACE_LLM_API_KEY="
        assert all(prefix + name not in archive.namelist() for name in private_values)
        assert not any(hashlib.sha256(archive.read(name)).hexdigest() == config["official_template_sha256"] for name in archive.namelist())
        review = json.loads(archive.read("PRE_UPLOAD_REVIEW.json"))
        assert review["official_application"] == "CONTENT_VERIFIED_VISUAL_REVIEW_PENDING"
        assert not review["officially_verified"] and not review["uploaded"]
        assert all(b"synthetic-private-export-key" not in archive.read(name) for name in archive.namelist())


@pytest.mark.parametrize("key_source", ["local_env", "process_environment"])
def test_valid_official_form_cannot_bypass_dynamic_key_protection(bundle, monkeypatch, key_source):
    root, _, _, path, _ = official_bundle(bundle)
    add_agent_inputs(root)
    secret = "synthetic-integration-private-key"
    monkeypatch.delenv("HOMETRACE_LLM_API_KEY", raising=False)
    if key_source == "local_env":
        (root / ".env").write_text("HOMETRACE_LLM_API_KEY=" + secret, encoding="utf-8")
    else:
        monkeypatch.setenv("HOMETRACE_LLM_API_KEY", secret)
    (root / "src/hometrace/accidental.py").write_text("# accidental " + secret, encoding="utf-8")

    report = sub.build(path, root)

    assert report["official_application"] == "CONTENT_VERIFIED_VISUAL_REVIEW_PENDING"
    assert report["status"] == "BLOCKED"
    assert "source" in {issue["field"] for issue in report["issues"]}
    assert secret not in json.dumps(report)
    assert secret not in (root / "dist_submission/submission-audit.json").read_text(encoding="utf-8")
    assert not list((root / "dist_submission").glob("*.zip"))


@pytest.mark.parametrize("filename,content", [
    ("config.yaml", "llm:\n  api_key: synthetic-not-a-real-key\n"),
    (".env.example", "HOMETRACE_LLM_API_KEY=synthetic-not-a-real-key\n"),
])
def test_valid_official_form_cannot_bypass_agent_secret_field_protection(bundle, filename, content):
    root, _, _, path, _ = official_bundle(bundle)
    add_agent_inputs(root)
    (root / filename).write_text(content, encoding="utf-8")

    report = sub.build(path, root)

    assert report["official_application"] == "CONTENT_VERIFIED_VISUAL_REVIEW_PENDING"
    assert report["status"] == "BLOCKED"
    assert "source" in {issue["field"] for issue in report["issues"]}
    assert "synthetic-not-a-real-key" not in json.dumps(report)
    assert not list((root / "dist_submission").glob("*.zip"))
