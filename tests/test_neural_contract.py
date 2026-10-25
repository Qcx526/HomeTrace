"""Deterministic boundary tests; synthetic bytes are not vision evidence."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


spec = importlib.util.spec_from_file_location("neural_contract", Path(__file__).resolve().parents[1] / "tools/neural_contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "private-image.bin"
    path.write_bytes(b"synthetic image binding, not a decoded photograph")
    return {"image_path": path, "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": 100, "height": 80}


def candidate(**changes):
    return dict({"bbox": [0, 0, 100, 80], "score": 0.99, "class_id": 0}, **changes)


def test_candidate_is_unconfirmed_and_extra_provider_claims_are_dropped(image):
    result = contract.run_candidate_provider(lambda: [candidate(identity="registered-earbud", status="FOUND")], **image)
    assert result["status"] == "SUSPECTED" and result["confirmed_identity"] is False
    assert result["reason"] == "candidate_requires_instance_verification"
    assert set(result["candidates"][0]) == {"bbox", "score", "class_id"}


def test_empty_prediction_is_unknown_and_does_not_reuse_previous_candidates(image):
    first = contract.run_candidate_provider(lambda: [candidate()], **image)
    second = contract.run_candidate_provider(lambda: [], **image)
    assert first["status"] == "SUSPECTED"
    assert second["status"] == "UNKNOWN" and second["candidates"] == []
    assert second["reason"] == "no_candidates" and first["candidates"]


@pytest.mark.parametrize("bad", [candidate(bbox=[0, 0, float("nan"), 50]),
    candidate(bbox=[0, -1, 20, 50]), candidate(bbox=[20, 0, 10, 50]),
    candidate(bbox=[0, 0, 101, 80]), candidate(score=float("inf")),
    candidate(class_id=1), candidate(class_id=True)])
def test_illegal_candidate_rejects_whole_batch(bad, image):
    result = contract.run_candidate_provider(lambda: [candidate(), bad], **image)
    assert result["status"] == "UNKNOWN" and result["reason"] == "invalid_candidates"
    assert result["candidates"] == []


def test_missing_provider_does_not_claim_execution(image):
    result = contract.run_candidate_provider(None, **image)
    assert result["status"] == "UNKNOWN" and result["reason"] == "provider_unavailable"
    assert result["provider_called"] is False


@pytest.mark.parametrize("error,reason", [(RuntimeError("PRIVATE_PATH"), "provider_error"),
    (subprocess.TimeoutExpired("PRIVATE_COMMAND", 1), "provider_timeout")])
def test_provider_failure_is_safe_and_does_not_leak_exception(image, error, reason):
    def provider():
        raise error
    result = contract.run_candidate_provider(provider, **image)
    assert result["status"] == "UNKNOWN" and result["reason"] == reason and result["provider_called"]
    assert "PRIVATE" not in json.dumps(result)


def test_wrong_hash_or_provenance_prevents_provider_execution(image):
    def forbidden():
        pytest.fail("Invalid evidence must never reach the provider")
    wrong = contract.run_candidate_provider(forbidden, **dict(image, expected_sha256="0" * 64))
    source = contract.run_candidate_provider(forbidden, source="live_robot", **image)
    assert wrong["reason"] == "image_binding_invalid" and not wrong["provider_called"]
    assert source["reason"] == "provenance_mismatch" and not source["provider_called"]


def test_image_changed_during_inference_discards_candidates(image):
    def changed():
        image["image_path"].write_bytes(b"changed evidence")
        return [candidate()]
    result = contract.run_candidate_provider(changed, **image)
    assert result["reason"] == "image_changed_during_inference" and result["candidates"] == []


def test_public_summary_separates_labels_and_excludes_private_metadata(image):
    rows = []
    for index, label in enumerate(contract.LABELS):
        result = contract.run_candidate_provider(lambda: [candidate()], **image)
        result["private_path"] = "PRIVATE_SECRET"
        rows.append({"group": "earbud", "case": f"scene_{index + 1:02}", "evaluation_label": label,
                     "result": result, "image_hash": "PRIVATE_SECRET", "reference_roi": [1, 2, 3, 4]})
    summary = contract.public_summary(rows)
    encoded = json.dumps(summary)
    assert all(summary["counts"][label]["samples"] == 1 for label in contract.LABELS)
    assert summary["counts"]["negative"]["candidate_cases"] == 1
    assert summary["confirmed_instances"] == 0
    assert all(key not in encoded for key in ("PRIVATE_SECRET", "bbox", "image_hash", "reference_roi", "private_path"))
    rows[0]["result"]["status"] = "FOUND"
    with pytest.raises(ValueError, match="confirmed identity"):
        contract.public_summary(rows)
