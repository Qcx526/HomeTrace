"""Offline boundary for experimental neural candidates, independent of model packages.

This module does not identify an instance, navigate, update memory, or emit FOUND.
The caller supplies a provider with its own execution timeout (for example a
subprocess timeout). Exceptions are reduced to public-safe reason codes.
"""

import hashlib
import math
from numbers import Integral, Real
from pathlib import Path
import re
import subprocess
from time import perf_counter


GROUPS = ("earbud", "panda", "keys", "tissue")
LABELS = ("positive", "negative", "uncertain", "auxiliary")
REASONS = frozenset({"candidate_requires_instance_verification", "no_candidates",
                     "provider_unavailable", "provider_error", "provider_timeout",
                     "invalid_candidates", "image_binding_invalid", "image_unavailable",
                     "image_changed_during_inference", "provenance_mismatch",
                     "invalid_dimensions"})


def _finite_number(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _dimensions(width, height):
    if any(not isinstance(value, Integral) or isinstance(value, bool) or value <= 0
           for value in (width, height)):
        raise ValueError("Image dimensions must be positive integers")


def validate_candidates(raw, width, height):
    """Return normalized full-scene XYXY candidates, or reject the whole batch.

    Only visual-prompt class 0 is registered. A valid class is not proof that a
    detection is the registered physical instance. No score threshold is applied
    here: inference configuration belongs to the separately fixed experiment.
    """
    _dimensions(width, height)
    if not isinstance(raw, list):
        raise ValueError("Candidates must be a list")
    normalized = []
    for candidate in raw:
        if not isinstance(candidate, dict):
            raise ValueError("Each candidate must be a mapping")
        bbox, score, class_id = (candidate.get(key) for key in ("bbox", "score", "class_id"))
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not all(map(_finite_number, bbox)):
            raise ValueError("Candidate bbox must contain four finite coordinates")
        x1, y1, x2, y2 = bbox
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("Candidate bbox must be ordered and inside the full image")
        if not _finite_number(score) or not 0 <= score <= 1:
            raise ValueError("Candidate score must be finite and between zero and one")
        if not isinstance(class_id, Integral) or isinstance(class_id, bool) or class_id != 0:
            raise ValueError("Only the registered visual-prompt class zero is allowed")
        normalized.append({"bbox": [float(value) for value in bbox],
                           "score": float(score), "class_id": 0})
    return normalized


def verify_image_sha256(path, expected_sha256):
    """Bind an image to the inventory without returning its private path or hash."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("Expected image SHA256 is invalid")
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("Image does not match its expected SHA256")


def run_candidate_provider(provider, *, image_path, expected_sha256, width, height,
                           source="recorded_image"):
    """Safely call a zero-argument provider and retain only unconfirmed candidates.

    The provider receives no evaluation labels. A subprocess provider must set its
    own timeout; this wrapper handles TimeoutExpired/TimeoutError, not cancellation.
    Expected bytes are checked both before and after inference. Callers separately
    validate the reference image, fixed ROI, decoded size, and model-weight hashes.
    """
    started = perf_counter()
    called = False

    def result(reason, candidates=None):
        candidates = candidates or []
        return {"status": "SUSPECTED" if candidates else "UNKNOWN", "reason": reason,
                "candidates": candidates, "confirmed_identity": False,
                "provider_called": called, "elapsed_ms": round((perf_counter() - started) * 1000, 3)}

    if source != "recorded_image":
        return result("provenance_mismatch")
    try:
        _dimensions(width, height)
    except ValueError:
        return result("invalid_dimensions")
    try:
        verify_image_sha256(image_path, expected_sha256)
    except (ValueError, TypeError):
        return result("image_binding_invalid")
    except OSError:
        return result("image_unavailable")
    if provider is None:
        return result("provider_unavailable")
    called = True
    try:
        raw = provider()
    except (subprocess.TimeoutExpired, TimeoutError):
        return result("provider_timeout")
    except Exception:
        return result("provider_error")
    try:
        verify_image_sha256(image_path, expected_sha256)
    except (OSError, ValueError, TypeError):
        return result("image_changed_during_inference")
    try:
        candidates = validate_candidates(raw, width, height)
    except (ValueError, TypeError):
        return result("invalid_candidates")
    return result("candidate_requires_instance_verification" if candidates else "no_candidates", candidates)


def public_summary(private_rows):
    """Publish allowlisted anonymous measurements, never image evidence or identity.

    Input rows have group/case/evaluation_label and a result from the wrapper.
    Labels are evaluation metadata attached after predictions. Candidate support
    on positive-labelled scenes is not verified instance recall or localization.
    """
    rows, seen = [], set()
    for row in private_rows:
        group, case, label = (row[key] for key in ("group", "case", "evaluation_label"))
        if group not in GROUPS or label not in LABELS or not isinstance(case, str) or not re.fullmatch(r"(?:scene|case)_[0-9]{2}", case):
            raise ValueError("Public reports require allowlisted groups, labels and anonymous case IDs")
        if (group, case) in seen:
            raise ValueError("Duplicate evaluation case")
        seen.add((group, case))
        result = row["result"]
        status, reason = result["status"], result["reason"]
        candidates = result["candidates"]
        elapsed, called = result["elapsed_ms"], result["provider_called"]
        if status not in {"SUSPECTED", "UNKNOWN"} or reason not in REASONS or result.get("confirmed_identity") is not False:
            raise ValueError("Neural report cannot assert confirmed identity")
        if not isinstance(candidates, list) or (status == "SUSPECTED") != bool(candidates):
            raise ValueError("Status must describe unconfirmed candidate presence")
        if not _finite_number(elapsed) or elapsed < 0 or not isinstance(called, bool):
            raise ValueError("Invalid execution measurements")
        scores = [candidate["score"] for candidate in candidates]
        if not all(_finite_number(score) and 0 <= score <= 1 for score in scores):
            raise ValueError("Invalid candidate scores")
        rows.append({"group": group, "case": case, "evaluation_label": label,
                     "status": status, "reason": reason, "candidate_count": len(candidates),
                     "scores": scores, "elapsed_ms": elapsed, "provider_called": called,
                     "confirmed_identity": False})

    def counts(selected):
        return {label: {"samples": sum(row["evaluation_label"] == label for row in selected),
                        "candidate_cases": sum(row["evaluation_label"] == label and row["status"] == "SUSPECTED" for row in selected),
                        "no_candidate_cases": sum(row["evaluation_label"] == label and row["reason"] == "no_candidates" for row in selected),
                        "failed_or_unavailable_cases": sum(row["evaluation_label"] == label and row["status"] == "UNKNOWN" and row["reason"] != "no_candidates" for row in selected)}
                for label in LABELS}

    return {"schema_version": 1, "experiment": "unconfirmed_neural_candidates",
            "candidate_semantics": "Candidate presence only; no instance confirmation or scene localization ground truth",
            "confirmed_instances": 0, "counts": counts(rows),
            "groups": {group: counts([row for row in rows if row["group"] == group]) for group in GROUPS},
            "evaluations": rows}
