"""Synthetic metric rows test accounting only, not photographic performance."""

import copy
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "vision_r0_metrics", Path(__file__).resolve().parents[1] / "tools/vision_r0_metrics.py"
)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def row(sample_id, **changes):
    return dict({
        "method": "baseline", "sample_id": sample_id, "label": "positive",
        "status": "UNKNOWN", "reason": "insufficient_support", "executed": True,
        "split": "diagnostic_reused", "localized_target_verified": None,
        "signal_kind": "geometric_acceptance",
    }, **changes)


def result(rows, method="baseline"):
    return metrics.summarize(rows)["methods"][method]


def test_no_predictions_has_null_precision_and_zero_positive_recall():
    actual = result([row("p"), row("n", label="negative")])["all_rows"]
    assert actual["image_presence_proxy"] == {
        "sample_count": 2, "true_positive": 0, "false_positive": 0,
        "false_negative": 1, "true_negative": 1, "precision": None,
        "recall": 0.0, "false_positive_rate": 0.0,
        "negative_false_alarms": 0, "negative_count": 1,
    }
    assert actual["instance_localization_verified"]["metrics"] is None


def test_registration_rejection_is_not_a_successful_negative():
    actual = result([
        row("p", executed=False, status=None, reason="registration_rejected"),
        row("n", label="negative", executed=False, status=None, reason="registration_rejected"),
    ])["all_rows"]
    assert actual["planned"]["positive"] == actual["planned"]["negative"] == 1
    assert actual["unexecuted"]["positive"] == actual["unexecuted"]["negative"] == 1
    assert actual["image_presence_proxy"]["sample_count"] == 0
    assert actual["image_presence_proxy"]["true_negative"] == 0
    assert actual["image_presence_proxy"]["false_positive_rate"] is None
    assert actual["unexecuted_reason_counts"] == {"registration_rejected": 2}


def test_all_negative_set_does_not_invent_positive_recall():
    actual = result([row("n", label="negative", status="FOUND")])["all_rows"]["image_presence_proxy"]
    assert actual["precision"] == 0.0
    assert actual["recall"] is None
    assert actual["false_positive_rate"] == 1.0


def test_wrong_instance_on_positive_image_is_only_proxy_true_positive():
    actual = result([row("p", signal_kind="neural_candidate", status="SUSPECTED",
                         candidate_count=1, localized_target_verified=False)])["all_rows"]
    assert actual["found_status_count"] == 0
    assert actual["accepted_signal_count"] == 1
    assert actual["image_presence_proxy"]["true_positive"] == 1
    verified = actual["instance_localization_verified"]["metrics"]
    assert verified["true_positive"] == 0
    assert verified["false_positive"] == verified["false_negative"] == 1
    assert verified["precision"] == verified["recall"] == 0.0
    assert verified["false_positive_rate"] is None


def test_unverified_neural_candidate_does_not_generate_instance_metrics():
    actual = result([row("p", signal_kind="neural_candidate", status="SUSPECTED",
                         candidate_count=2)])["all_rows"]
    assert actual["image_presence_proxy"]["recall"] == 1.0
    assert actual["instance_localization_verified"]["status"] == "UNVERIFIED"
    assert actual["instance_localization_verified"]["metrics"] is None


def test_uncertain_and_auxiliary_are_not_false_positives_or_negatives():
    actual = result([row("u", label="uncertain", status="FOUND"),
                     row("a", label="auxiliary")])["all_rows"]
    assert actual["row_count"] == 2
    assert actual["excluded_from_binary"] == 2
    assert actual["image_presence_proxy"]["sample_count"] == 0


def test_no_independent_photos_remains_blocked_even_with_perfect_proxy():
    actual = result([row("p", status="FOUND", localized_target_verified=True),
                     row("n", label="negative", localized_target_verified=False)])
    assert actual["diagnostic_reused"]["image_presence_proxy"]["precision"] == 1.0
    assert actual["independent_test"] == {"status": "BLOCKED", "row_count": 0, "metrics": None}


def test_independent_data_is_separated_and_unexecuted_is_still_blocked():
    actual = result([row("reused", status="FOUND"), row("fresh", split="independent_test")])
    assert actual["diagnostic_reused"]["image_presence_proxy"]["recall"] == 1.0
    assert actual["independent_test"]["metrics"]["image_presence_proxy"]["recall"] == 0.0
    assert actual["independent_test"]["status"] == "AVAILABLE"
    rejected = result([row("fresh", split="independent_test", executed=False, status=None)])
    assert rejected["independent_test"] == {"status": "BLOCKED", "row_count": 1, "metrics": None}


def test_partial_manual_localization_has_explicit_coverage():
    actual = result([row("a", status="FOUND", localized_target_verified=True),
                     row("b", status="FOUND")])["all_rows"]["instance_localization_verified"]
    assert actual["status"] == "PARTIAL"
    assert actual["coverage"] == 0.5
    assert actual["verified_count"] == actual["unverified_count"] == 1


def test_multiple_methods_are_separate_and_inputs_unchanged():
    rows = [row("same", status="FOUND"), row("same", method="candidate")]
    before = copy.deepcopy(rows)
    actual = metrics.summarize(iter(rows))
    assert set(actual["methods"]) == {"baseline", "candidate"}
    assert actual["methods"]["baseline"]["all_rows"]["image_presence_proxy"]["recall"] == 1.0
    assert actual["methods"]["candidate"]["all_rows"]["image_presence_proxy"]["recall"] == 0.0
    assert rows == before


def test_duplicate_method_sample_is_rejected_even_across_splits():
    with pytest.raises(ValueError, match="Duplicate"):
        metrics.summarize([row("same"), row("same", split="independent_test")])


@pytest.mark.parametrize("changes", [
    {"executed": 1}, {"localized_target_verified": 1}, {"candidate_count": True},
    {"candidate_count": -1}, {"status": "success"}, {"label": "maybe"},
    {"split": "train"}, {"signal_kind": "authoritative_llm"},
    {"localized_target_verified": True},
    {"signal_kind": "neural_candidate", "status": "SUSPECTED"},
])
def test_invalid_or_incomplete_rows_do_not_silently_change_metrics(changes):
    with pytest.raises(ValueError):
        metrics.summarize([row("p", **changes)])


def test_empty_results_do_not_invent_methods_or_metrics():
    assert metrics.summarize([])["methods"] == {}
