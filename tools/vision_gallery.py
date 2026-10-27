"""Deterministic, offline appearance-gallery diagnostics; never instance identity.

This module does not load images or models and has no numerical-library
dependency. Embeddings must come from a separately recorded shared encoder.
The default thresholds are fixed experimental choices, not calibrated business
criteria. ``APPEARANCE_SUPPORTED`` is not production ``FOUND`` and does not prove
that two photographs show the same physical object.
"""

from collections.abc import Mapping
import math
from numbers import Real
import re


METHOD_VERSION = "shared-appearance-gallery-v1"
DEFAULT_MIN_SIMILARITY = 0.70
DEFAULT_MIN_MARGIN = 0.05
DEFAULT_MIN_SUPPORT = 2


def normalize(vector):
    """Return a finite unit vector, rejecting empty, zero or invalid vectors."""
    if isinstance(vector, (str, bytes, Mapping)):
        raise ValueError("Embedding must be a sequence of finite real numbers")
    try:
        values = list(vector)
    except TypeError as exc:
        raise ValueError("Embedding must be a sequence of finite real numbers") from exc
    if not values:
        raise ValueError("Embedding cannot be empty")
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
        raise ValueError("Embedding must contain finite real numbers")
    try:
        values = [float(value) for value in values]
    except (OverflowError, ValueError) as exc:
        raise ValueError("Embedding must contain finite real numbers") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Embedding must contain finite real numbers")
    scale = max(abs(value) for value in values)
    if scale == 0:
        raise ValueError("Zero embedding has no cosine direction")
    # Scaling first also handles very large or very small finite embeddings.
    scaled = [value / scale for value in values]
    length = math.sqrt(math.fsum(value * value for value in scaled))
    return [value / length for value in scaled]


def cosine(a, b):
    """Cosine similarity, not a probability or a physical-identity score."""
    left, right = normalize(a), normalize(b)
    if len(left) != len(right):
        raise ValueError("Embedding dimension mismatch")
    return max(-1.0, min(1.0, math.fsum(x * y for x, y in zip(left, right))))


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a nonempty, trimmed string")
    return value


def _sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("image_sha256 must be a 64-character SHA256 digest")
    return value.lower()


def _threshold(value, name, lower, upper):
    if (isinstance(value, bool) or not isinstance(value, Real)
            or not math.isfinite(float(value)) or not lower <= value <= upper):
        raise ValueError(f"{name} must be finite and in [{lower}, {upper}]")
    return float(value)


def rank_candidate(query, gallery_entries, *, target_instance_id=None,
                   min_similarity=DEFAULT_MIN_SIMILARITY,
                   min_margin=DEFAULT_MIN_MARGIN,
                   min_support=DEFAULT_MIN_SUPPORT):
    """Rank candidate appearance against distinct reference-image hashes.

    ``query`` requires ``embedding`` and the SHA256 of its *original source
    image* in ``image_sha256``. A crop must retain its source image's digest so
    reference-image replay cannot evade the guard by cropping.

    Each gallery entry requires ``object_instance_id``, ``reference_id``,
    ``image_sha256`` and ``embedding``. Duplicate source hashes within an
    instance contribute once. A hash assigned to different instances, or
    contradictory embeddings for the same source hash, is invalid input.

    Decision scores are the mean of the top two distinct references (one for a
    rival with only one reference). Target support requires at least two unique
    source hashes above the similarity threshold. A nonempty rival gallery is
    required; a single-reference rival is explicitly a limited control. These
    checks reduce elementary failure modes, but are not calibrated open-set
    instance recognition and must never be converted directly to FOUND.

    Omitting an explicit target produces rankings only, with UNKNOWN status.
    Invalid vectors/metadata raise ValueError; insufficient evidence and replay
    return UNKNOWN with reasons. No caller-provided labels are consumed.
    """
    min_similarity = _threshold(min_similarity, "min_similarity", -1, 1)
    min_margin = _threshold(min_margin, "min_margin", 0, 2)
    if type(min_support) is not int or min_support < 2:
        raise ValueError("min_support must be an integer of at least 2")
    if target_instance_id is not None:
        target_instance_id = _identifier(target_instance_id, "target_instance_id")
    if not isinstance(query, Mapping):
        raise ValueError("query must be an object")
    query_vector = normalize(query.get("embedding"))
    query_hash = _sha256(query.get("image_sha256"))
    if isinstance(gallery_entries, (str, bytes, Mapping)):
        raise ValueError("gallery_entries must be a sequence of objects")
    try:
        gallery_entries = list(gallery_entries)
    except TypeError as exc:
        raise ValueError("gallery_entries must be a sequence of objects") from exc

    parsed = []
    for entry in gallery_entries:
        if not isinstance(entry, Mapping):
            raise ValueError("Gallery entry must be an object")
        instance = _identifier(entry.get("object_instance_id"), "object_instance_id")
        reference = _identifier(entry.get("reference_id"), "reference_id")
        digest = _sha256(entry.get("image_sha256"))
        vector = normalize(entry.get("embedding"))
        if len(vector) != len(query_vector):
            raise ValueError("Embedding dimension mismatch")
        parsed.append((instance, reference, digest, vector))

    # A stable canonical reference survives duplicates regardless of input order.
    unique, owners, reference_ids, duplicates = {}, {}, {}, []
    for instance, reference, digest, vector in sorted(parsed):
        previous_hash = reference_ids.setdefault((instance, reference), digest)
        if previous_hash != digest:
            raise ValueError("reference_id names multiple source images")
        owner = owners.setdefault(digest, instance)
        if owner != instance:
            raise ValueError("One source image hash is assigned to different instances")
        key = (instance, digest)
        if key in unique:
            kept_reference, kept_vector = unique[key]
            if any(not math.isclose(a, b, rel_tol=0, abs_tol=1e-12)
                   for a, b in zip(kept_vector, vector)):
                raise ValueError("Duplicate source hash has contradictory embeddings")
            duplicates.append({"object_instance_id": instance, "image_sha256": digest,
                               "kept_reference_id": kept_reference,
                               "ignored_reference_id": reference})
            continue
        unique[key] = (reference, vector)

    per_instance = {}
    for (instance, digest), (reference, vector) in unique.items():
        score = max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(query_vector, vector))))
        per_instance.setdefault(instance, []).append(
            {"reference_id": reference, "image_sha256": digest, "similarity": score})
    ranking = []
    for instance, similarities in per_instance.items():
        similarities.sort(key=lambda row: (-row["similarity"], row["reference_id"], row["image_sha256"]))
        values = [row["similarity"] for row in similarities]
        top = values[:2]
        ranking.append({"object_instance_id": instance,
                        "reference_count": len(values),
                        "support_count": sum(value >= min_similarity for value in values),
                        "similarities": similarities,
                        "mean": math.fsum(values) / len(values),
                        "top2_mean": math.fsum(top) / len(top),
                        "max": values[0],
                        "best_reference": similarities[0]["reference_id"]})
    ranking.sort(key=lambda row: (-row["top2_mean"], row["object_instance_id"]))
    target = next((row for row in ranking if row["object_instance_id"] == target_instance_id), None)
    rivals = [row for row in ranking if row["object_instance_id"] != target_instance_id]
    # Without a target, the ranking is informational and no rival comparison exists.
    if target_instance_id is None:
        rivals = []
    best_rival = rivals[0] if rivals else None
    target_score = target["top2_mean"] if target else None
    rival_score = best_rival["top2_mean"] if best_rival else None
    margin = target_score - rival_score if target_score is not None and rival_score is not None else None
    reasons = []
    if query_hash in owners:
        reasons.append("reference_replay")
    if not ranking:
        reasons.append("empty_gallery")
    if target_instance_id is None:
        reasons.append("target_not_specified")
    elif target is None:
        reasons.append("target_not_registered")
    elif target["support_count"] < min_support:
        reasons.append("insufficient_distinct_reference_support")
    if target_instance_id is not None:
        if best_rival is None:
            reasons.append("missing_rival_control")
        elif margin is not None and margin < min_margin:
            reasons.append("insufficient_rival_margin")
    limited_rivals = [row["object_instance_id"] for row in rivals if row["reference_count"] < 2]
    return {"method_version": METHOD_VERSION,
            "status": "UNKNOWN" if reasons else "APPEARANCE_SUPPORTED",
            "reason": reasons[0] if reasons else "appearance_support_and_margin",
            "reasons": reasons,
            "identity_confirmed": False,
            "thresholds_calibrated": False,
            "thresholds": {"min_similarity": min_similarity, "min_margin": min_margin,
                           "min_support": min_support, "aggregation": "top2_mean"},
            "target_instance_id": target_instance_id,
            "target_score": target_score,
            "best_rival_instance_id": best_rival["object_instance_id"] if best_rival else None,
            "best_rival_score": rival_score,
            "margin": margin,
            "rival_control": "missing" if not rivals else "limited" if limited_rivals else "available",
            "limited_rival_instance_ids": limited_rivals,
            "duplicate_references": duplicates,
            "ranking": ranking}
