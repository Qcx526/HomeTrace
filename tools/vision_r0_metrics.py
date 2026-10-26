"""Post-inference diagnostic metrics; labels must never be detector inputs.

Image-presence scores are deliberately separate from manually verified instance
localization. A candidate on a positive image can still be the wrong object.
These summaries cannot establish improvement on reused diagnostic photographs.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping


LABELS = ("positive", "negative", "uncertain", "auxiliary")
SPLITS = ("diagnostic_reused", "independent_test")
SIGNALS = ("geometric_acceptance", "neural_candidate")


def _accepted(row):
    return row["status"] == "FOUND" or (
        row["signal_kind"] == "neural_candidate" and row.get("candidate_count", 0) > 0
    )


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _counts(rows, *, instance=False):
    tp = fp = fn = tn = 0
    for row in rows:
        accepted = _accepted(row)
        positive = row["label"] == "positive"
        correct = accepted and positive
        if instance:
            correct = correct and row["localized_target_verified"] is True
        tp += int(correct)
        fp += int(accepted and not correct)
        fn += int(positive and not correct)
        tn += int(not positive and not accepted)
    negatives = sum(row["label"] == "negative" for row in rows)
    # Wrong-instance acceptance on a positive image is an FP for precision,
    # but not a negative-image false alarm. Keep those denominators separate.
    negative_false_alarms = sum(
        row["label"] == "negative" and _accepted(row) for row in rows
    )
    return {
        "sample_count": len(rows),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "false_positive_rate": _ratio(negative_false_alarms, negatives),
        "negative_false_alarms": negative_false_alarms,
        "negative_count": negatives,
    }


def _summary(rows):
    binary = [row for row in rows if row["label"] in ("positive", "negative")]
    executed = [row for row in binary if row["executed"]]
    verified = [row for row in executed if row["localized_target_verified"] is not None]
    planned = Counter(row["label"] for row in rows)
    executed_counts = Counter(row["label"] for row in rows if row["executed"])
    return {
        "row_count": len(rows),
        "planned": {label: planned[label] for label in LABELS},
        "executed": {label: executed_counts[label] for label in LABELS},
        "unexecuted": {label: planned[label] - executed_counts[label] for label in LABELS},
        "excluded_from_binary": planned["uncertain"] + planned["auxiliary"],
        "image_presence_proxy": _counts(executed),
        "instance_localization_verified": {
            "status": "UNVERIFIED" if not verified else (
                "PARTIAL" if len(verified) != len(executed) else "VERIFIED_SUBSET"
            ),
            "verified_count": len(verified),
            "unverified_count": len(executed) - len(verified),
            "coverage": _ratio(len(verified), len(executed)),
            "metrics": _counts(verified, instance=True) if verified else None,
        },
        "accepted_signal_count": sum(_accepted(row) for row in rows if row["executed"]),
        "found_status_count": sum(row["status"] == "FOUND" for row in rows if row["executed"]),
        "reason_counts": dict(sorted(Counter(row["reason"] for row in rows).items())),
        "unexecuted_reason_counts": dict(sorted(Counter(
            row["reason"] for row in rows if not row["executed"]
        ).items())),
    }


def _validated(rows):
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Each result must be a mapping")
        required = ("method", "sample_id", "label", "status", "reason", "executed",
                    "split", "localized_target_verified", "signal_kind")
        if any(key not in row for key in required):
            raise ValueError("Result is missing required diagnostic fields")
        if any(not isinstance(row[key], str) or not row[key] for key in ("method", "sample_id")):
            raise ValueError("Method and sample ID must be nonempty strings")
        pair = (row["method"], row["sample_id"])
        if pair in seen:
            raise ValueError("Duplicate (method, sample_id) result")
        seen.add(pair)
        if row["label"] not in LABELS or row["split"] not in SPLITS or row["signal_kind"] not in SIGNALS:
            raise ValueError("Unknown label, split, or signal kind")
        if row["status"] not in ("FOUND", "SUSPECTED", "UNKNOWN", None):
            raise ValueError("Unknown result status")
        if not isinstance(row["reason"], str) or type(row["executed"]) is not bool:
            raise ValueError("Reason must be text and executed must be a bool")
        localized = row["localized_target_verified"]
        if localized is not None and type(localized) is not bool:
            raise ValueError("Localization verification must be bool or null")
        count = row.get("candidate_count", 0)
        if type(count) is not int or count < 0:
            raise ValueError("Candidate count must be a nonnegative integer")
        if row["signal_kind"] == "neural_candidate" and row["executed"] and "candidate_count" not in row:
            raise ValueError("Executed neural candidate results require candidate_count")
        if localized is True and (row["label"] != "positive" or not row["executed"] or not _accepted(row)):
            raise ValueError("Verified target localization requires an accepted executed positive")
        result.append(dict(row))
    return result


def summarize(rows):
    """Summarize post-inference rows without changing them or detector decisions.

Unexecuted registration failures never enter the confusion matrix. Uncertain
and auxiliary samples are counted but excluded from binary metrics. Neural
candidate presence is a diagnostic signal, never an instance-confirmed FOUND.

The instance column uses only explicit human localization judgments (bool).
Null means unverified and produces no instance metric. Even full coverage here
does not establish independent validation when the split is diagnostic_reused.
"""
    groups = defaultdict(list)
    for row in _validated(rows):
        groups[row["method"]].append(row)
    methods = {}
    for method, group in sorted(groups.items()):
        reused = [row for row in group if row["split"] == "diagnostic_reused"]
        independent = [row for row in group if row["split"] == "independent_test"]
        independent_executed = any(
            row["executed"] and row["label"] in ("positive", "negative") for row in independent
        )
        methods[method] = {
            "signal_kinds": sorted({row["signal_kind"] for row in group}),
            "all_rows": _summary(group),
            "diagnostic_reused": _summary(reused) if reused else None,
            "independent_test": {
                "status": "AVAILABLE" if independent_executed else "BLOCKED",
                "row_count": len(independent),
                "metrics": _summary(independent) if independent_executed else None,
            },
        }
    return {
        "schema_version": 1,
        "methods": methods,
        "warnings": [
            "image_presence_proxy is not correct-instance localization or production FOUND accuracy",
            "neural_candidate acceptance is candidate presence, not instance confirmation",
            "unexecuted rows are excluded; low execution coverage is not negative success",
            "instance metrics cover explicit human localization judgments only; partial coverage can be biased",
            "diagnostic_reused data cannot prove independent real-photo improvement",
            "AVAILABLE independent metrics do not themselves constitute acceptance or improvement",
        ],
    }
