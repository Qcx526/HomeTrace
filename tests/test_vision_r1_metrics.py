"""Synthetic scoring facts test arithmetic, never real household ability."""

import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from vision_r1_metrics import summarize


def label(sid="s", value="positive", **changes):
    return {"sample_id": sid, "object_instance_id": "test-instance", "label": value, "source_type": "real", "split": "diagnostic_reused",
            "capture_batch": "unknown", "target_box": None, "box_source": "none", "instance_reviews": {}, **changes}


def row(sid="s", accepted=False, **changes):
    return {"sample_id": sid, "object_instance_id": "test-instance", "method": "fixture_method", "source_type": "real", "reason": "fixture_reason",
            "status": "EXPERIMENTAL_ACCEPTED" if accepted else "UNKNOWN", "executed": True,
            "bbox": [10, 20, 110, 120] if accepted else None, "prediction_fingerprint": "a"*64, **changes}


def review(verdict="correct", fingerprint="a"*64):
    return {"fixture_method": {"verdict": verdict, "prediction_fingerprint": fingerprint}}


def group(rows, labels, key="real/diagnostic_reused", method="fixture_method"):
    return summarize(rows, labels)["methods"][method][key]


def test_zero_acceptance_has_undefined_precision_and_cannot_pass():
    result = group([row(), row("n")], [label(), label("n", "negative")])
    assert result["instance_localization"]["precision"] is None
    assert result["instance_localization"]["recall"] == 0
    assert result["restricted_demo_gate"] == "BLOCKED"


def test_positive_presence_is_not_correct_instance():
    result = group([row(accepted=True)], [label()])
    assert result["presence_proxy"]["positive_geometric_acceptances"] == 1
    assert result["instance_localization"]["unverified_acceptances"] == 1
    assert result["instance_localization"]["precision"] is None
    assert result["restricted_demo_gate"] == "BLOCKED"


def test_wrong_instance_on_positive_counts_false_acceptance_and_miss():
    result = group([row(accepted=True)], [label(instance_reviews=review("wrong"))])
    assert result["instance_localization"]["false_acceptances"] == 1
    assert result["instance_localization"]["misses"] == 1
    assert result["instance_localization"]["precision"] == 0
    assert result["instance_localization"]["negative_false_acceptances"] == 0


def test_label_box_is_not_enough_without_identity_review():
    result = group([row(accepted=True)], [label(target_box=[10, 20, 110, 120], box_source="human")])
    assert result["instance_localization"]["unverified_acceptances"] == 1


def test_identity_review_does_not_cross_methods():
    rows = [row(accepted=True), row(accepted=True, method="other")]
    labels = [label(target_box=[10, 20, 110, 120], box_source="human", instance_reviews=review())]
    assert group(rows, labels)["instance_localization"]["correct"] == 1
    assert group(rows, labels, method="other")["instance_localization"]["unverified_acceptances"] == 1


def test_correct_identity_with_bad_localization_fails_localization_metric():
    result = group([row(accepted=True)], [label(target_box=[300, 300, 400, 400], box_source="human", instance_reviews=review())])
    assert result["instance_localization"]["correct"] == 0
    assert result["samples"][0]["iou"] == 0


def test_unexecuted_negative_is_not_successful_negative():
    result = group([row(executed=False)], [label(value="negative")])
    assert result["unexecuted_count"] == 1
    assert result["instance_localization"]["true_negatives"] == 0
    assert result["instance_localization"]["negative_false_acceptance_rate"] is None


def test_missing_result_remains_in_denominator():
    result = group([row()], [label(), label("missing")])
    assert result["row_count"] == 2 and result["unexecuted_count"] == 1
    assert result["reason_counts"]["missing_result"] == 1
    assert result["instance_localization"]["misses"] == 2


def test_uncertain_auxiliary_retained_not_binary_success():
    result = group([row(), row("a", True)], [label(value="uncertain"), label("a", "auxiliary")])
    assert result["accepted_count"] == 1
    assert result["instance_localization"]["precision"] is None
    assert result["instance_localization"]["correct"] == 0


def test_sources_are_separate():
    rows = [row(), row("fixture", source_type="synthetic")]
    labels = [label(), label("fixture", source_type="synthetic", split="software_fixture")]
    groups = summarize(rows, labels)["methods"]["fixture_method"]
    assert set(groups) == {"real/diagnostic_reused", "synthetic/software_fixture"}


def sufficient_scoring_fixture():
    rows, labels = [], []
    for i in range(14):
        positive = i < 6
        rows.append(row(str(i), accepted=i < 5))
        labels.append(label(str(i), "positive" if positive else "negative", split="independent_test",
                            capture_batch="batch_a" if i % 2 else "batch_b",
                            target_box=[10, 20, 110, 120] if positive else None,
                            box_source="human" if positive else "none",
                            instance_reviews=review() if i < 5 else {}))
    return rows, labels


def test_complete_arithmetic_fixture_only_passes_pending_provenance_audit():
    rows, labels = sufficient_scoring_fixture()
    result = group(rows, labels, "real/independent_test")
    assert result["restricted_demo_gate"] == "PASS_PENDING_PROVENANCE_AUDIT"
    assert result["instance_localization"]["recall"] == 5/6


@pytest.mark.parametrize("mutation", ["one_batch", "unknown_batch", "false_alarm", "unexecuted", "missing_truth", "miss", "reused", "wrong_identity"])
def test_any_acceptance_shortfall_stays_blocked(mutation):
    rows, labels = sufficient_scoring_fixture()
    key = "real/independent_test"
    if mutation == "one_batch":
        for l in labels: l["capture_batch"] = "one"
    elif mutation == "unknown_batch": labels[0]["capture_batch"] = "unknown"
    elif mutation == "false_alarm": rows[8] = row("8", True)
    elif mutation == "unexecuted": rows[8]["executed"] = False
    elif mutation == "missing_truth": labels[5].update(target_box=None, box_source="none")
    elif mutation == "miss": rows[0] = row("0")
    elif mutation == "wrong_identity": labels[0]["instance_reviews"] = review("wrong")
    elif mutation == "reused":
        key = "real/diagnostic_reused"
        for l in labels: l["split"] = "diagnostic_reused"
    assert group(rows, labels, key)["restricted_demo_gate"] == "BLOCKED"


@pytest.mark.parametrize("mutation", ["duplicate_label", "duplicate_row", "bad_box", "model_truth", "source", "unknown_sample", "global_review", "accept_unexecuted", "synthetic_independent", "production_found"])
def test_invalid_evidence_rejected(mutation):
    rows, labels = [row()], [label()]
    if mutation == "duplicate_label": labels *= 2
    elif mutation == "duplicate_row": rows *= 2
    elif mutation == "bad_box": rows = [row(accepted=True, bbox=[0, 0, 0, 3])]
    elif mutation == "model_truth": labels[0].update(target_box=[0, 0, 20, 30], box_source="model")
    elif mutation == "source": rows[0]["source_type"] = "synthetic"
    elif mutation == "unknown_sample": rows[0]["sample_id"] = "unplanned"
    elif mutation == "global_review": labels[0]["instance_review"] = "correct"
    elif mutation == "accept_unexecuted": rows = [row(accepted=True, executed=False)]
    elif mutation == "synthetic_independent": labels[0].update(source_type="synthetic", split="independent_test")
    elif mutation == "production_found": rows[0]["status"] = "FOUND"
    with pytest.raises(ValueError):
        summarize(rows, labels)


def test_empty_results_do_not_pass():
    assert summarize([], [label()])["gate"] == "BLOCKED"


def test_metrics_do_not_mutate_raw_evidence():
    rows, labels = sufficient_scoring_fixture()
    before = copy.deepcopy((rows, labels))
    summarize(rows, labels)
    assert (rows, labels) == before


def test_mixed_instances_cannot_combine_to_meet_single_object_gate():
    rows, labels = sufficient_scoring_fixture()
    for i, (r, l) in enumerate(zip(rows, labels)):
        r["object_instance_id"] = l["object_instance_id"] = "target-a" if i % 2 else "target-b"
    result = group(rows, labels, "real/independent_test")
    assert result["restricted_demo_gate"] == "BLOCKED_MIXED_INSTANCES_USE_PER_INSTANCE"
    assert all(s["restricted_demo_gate"] == "BLOCKED" for s in result["per_instance"].values())


def test_stale_identity_review_is_unverified():
    result = group([row(accepted=True)], [label(target_box=[10, 20, 110, 120], box_source="human", instance_reviews=review(fingerprint="b"*64))])
    assert result["instance_localization"]["unverified_acceptances"] == 1
    assert result["restricted_demo_gate"] == "BLOCKED"
