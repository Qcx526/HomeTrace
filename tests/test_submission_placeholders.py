"""Placeholder warnings remain pending review, never official approval."""

import pytest

from hometrace import submission as sub
from test_submission import bundle, office  # Reuse synthetic TEST_ONLY fixtures.


@pytest.mark.parametrize("text", ["待团队填写", "待团队在本地填写", "待在本地补齐"])
@pytest.mark.parametrize("role", ["application", "presentation", "run_report"])
def test_team_placeholders_in_each_document_warn_without_blocking(bundle, text, role):
    root, inputs, config, path, _ = bundle
    target = inputs / config["materials"][role]
    if role == "run_report":
        target.write_text("# TEST_ONLY\nSynthetic packaging fixture, not a competition submission. 团队信息：" + text, encoding="utf-8")
    else:
        office(target, "word" if role == "application" else "ppt", "Synthetic TEST_ONLY packaging fixture. 团队信息：" + text)
    report, _, _ = sub.prepare(path, root)
    assert report["status"] == "TEST_ONLY_PREFLIGHT_PASSED"
    assert any(w["field"] == role and "Placeholder" in w["reason"] for w in report["warnings"])
    assert not report["ready_to_submit"] and not report["officially_verified"]


@pytest.mark.parametrize("text", ["待团队填写", "待团队在本地填写", "待在本地补齐"])
def test_local_identity_confirmation_cannot_erase_placeholder_warning(bundle, text):
    root, _, config, path, save = bundle
    config["identity_confirmed"] = True
    config["team"] = {"name": text, "work_name": "HomeTrace", "captain_name": text,
                      "captain_phone": "13900000001"}  # Synthetic fixture, not a contact.
    save()
    report, _, _ = sub.prepare(path, root)
    assert "identity" not in report["checks"]
    assert any(w["field"] == "team" for w in report["warnings"])
