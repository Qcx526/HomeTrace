"""Synthetic vectors exercise software rules, never real household accuracy."""

import copy
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from vision_gallery import cosine, normalize, rank_candidate


def reference(number, instance="target", embedding=(1.0, 0.0)):
    return {"object_instance_id": instance, "reference_id": f"fixture-ref-{number}",
            "image_sha256": f"{number:064x}", "embedding": list(embedding)}


def query(embedding=(1.0, 0.0), number=999):
    return {"embedding": list(embedding), "image_sha256": f"{number:064x}"}


def gallery():
    return [reference(1), reference(2, embedding=(0.9, 0.1)),
            reference(3, "rival", (0.0, 1.0))]


def test_normalization_and_cosine_handle_scale_without_overflow():
    assert normalize([3, 4]) == pytest.approx([0.6, 0.8])
    assert normalize([1e308, 1e308]) == pytest.approx([2 ** -0.5] * 2)
    assert normalize([1e-300, 0]) == [1.0, 0.0]
    assert cosine([3, 4], [30, 40]) == pytest.approx(1)
    assert cosine([1, 0], [-1, 0]) == -1
    assert cosine([1, 0], [0, 1]) == 0


@pytest.mark.parametrize("vector", [[], [0, 0], [float("nan"), 1],
                                   [float("inf"), 1], [True, 1], ["1", 2],
                                   [[1], 2], "12", None, {"a": 1}])
def test_invalid_embedding_is_rejected(vector):
    with pytest.raises(ValueError):
        normalize(vector)


def test_cosine_dimension_mismatch_is_rejected():
    with pytest.raises(ValueError, match="dimension"):
        cosine([1, 0], [1, 0, 0])


def test_two_distinct_supports_and_margin_are_only_appearance_support():
    result = rank_candidate(query(), gallery(), target_instance_id="target")
    assert result["status"] == "APPEARANCE_SUPPORTED"
    assert result["identity_confirmed"] is False
    assert result["thresholds_calibrated"] is False
    assert result["thresholds"] == {"min_similarity": 0.70, "min_margin": 0.05,
                                    "min_support": 2, "aggregation": "top2_mean"}
    assert result["rival_control"] == "limited"
    assert result["limited_rival_instance_ids"] == ["rival"]
    target = result["ranking"][0]
    assert target["reference_count"] == target["support_count"] == 2
    assert target["best_reference"] == "fixture-ref-1"
    assert target["max"] == 1
    assert target["mean"] == target["top2_mean"]
    assert target["similarities"][0]["image_sha256"] == f"{1:064x}"


def test_full_rival_control_and_mean_top2_max_are_separate():
    entries = gallery() + [reference(4, embedding=(-1, 0)), reference(5, "rival", (0, -1))]
    result = rank_candidate(query(), entries, target_instance_id="target")
    target = result["ranking"][0]
    assert result["rival_control"] == "available"
    assert target["mean"] < target["top2_mean"] < target["max"]
    assert len(target["similarities"]) == 3


def test_one_perfect_reference_is_not_sufficient():
    result = rank_candidate(query(), [gallery()[0], gallery()[2]], target_instance_id="target")
    assert result["status"] == "UNKNOWN"
    assert "insufficient_distinct_reference_support" in result["reasons"]


def test_duplicate_hash_does_not_manufacture_support():
    repeated = reference(1)
    repeated["reference_id"] = "another-name-for-same-source"
    result = rank_candidate(query(), [reference(1), repeated, reference(3, "rival", (0, 1))],
                            target_instance_id="target")
    assert result["status"] == "UNKNOWN"
    assert result["ranking"][0]["support_count"] == 1
    assert len(result["duplicate_references"]) == 1


def test_original_source_hash_replay_cannot_accept_a_reference_crop():
    result = rank_candidate(query(number=1), gallery(), target_instance_id="target")
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "reference_replay"


def test_rival_reference_replay_is_also_rejected():
    result = rank_candidate(query(number=3), gallery(), target_instance_id="target")
    assert result["reason"] == "reference_replay"


def test_unknown_appearance_is_not_forced_to_nearest_instance():
    result = rank_candidate(query((-1, -1)), gallery(), target_instance_id="target")
    assert result["status"] == "UNKNOWN"
    assert result["ranking"]  # A nearest result does not authorize acceptance.


def test_wrong_instance_and_similar_rival_are_rejected():
    wrong = rank_candidate(query((0, 1)), gallery(), target_instance_id="target")
    assert wrong["status"] == "UNKNOWN"
    similar = gallery()
    similar[2]["embedding"] = [1, 0]
    result = rank_candidate(query(), similar, target_instance_id="target")
    assert result["status"] == "UNKNOWN"
    assert "insufficient_rival_margin" in result["reasons"]


def test_all_rivals_are_compared_not_only_first_or_average_rival():
    entries = gallery() + [reference(4, "hard-rival", (1, 0))]
    result = rank_candidate(query(), entries, target_instance_id="target")
    assert result["best_rival_instance_id"] == "hard-rival"
    assert result["status"] == "UNKNOWN"


def test_no_rival_control_is_explicit_unknown():
    result = rank_candidate(query(), gallery()[:2], target_instance_id="target")
    assert result["status"] == "UNKNOWN"
    assert result["rival_control"] == "missing"
    assert result["margin"] is None
    assert "missing_rival_control" in result["reasons"]


def test_no_target_does_not_turn_rank_one_into_acceptance():
    result = rank_candidate(query(), gallery())
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "target_not_specified"
    assert result["best_rival_score"] is None


def test_unregistered_target_and_empty_gallery_are_explicit_unknown():
    result = rank_candidate(query(), gallery(), target_instance_id="absent-object")
    assert result["reason"] == "target_not_registered"
    empty = rank_candidate(query(), [], target_instance_id="target")
    assert empty["status"] == "UNKNOWN"
    assert empty["reason"] == "empty_gallery"
    assert empty["ranking"] == []


def test_hash_assigned_to_two_instances_is_invalid():
    entries = gallery() + [reference(1, "different-physical-instance")]
    with pytest.raises(ValueError, match="different instances"):
        rank_candidate(query(), entries, target_instance_id="target")


def test_contradictory_embedding_for_same_original_hash_is_invalid():
    entries = gallery() + [reference(1, embedding=(0, 1))]
    with pytest.raises(ValueError, match="contradictory"):
        rank_candidate(query(), entries, target_instance_id="target")


def test_reference_id_cannot_be_reused_for_different_sources():
    entries = gallery()
    entries[1]["reference_id"] = entries[0]["reference_id"]
    with pytest.raises(ValueError, match="multiple source"):
        rank_candidate(query(), entries, target_instance_id="target")


@pytest.mark.parametrize("change,match", [
    (lambda rows: rows[0].update(image_sha256="not-a-hash"), "SHA256"),
    (lambda rows: rows[0].update(embedding=[1, 0, 0]), "dimension"),
    (lambda rows: rows[0].update(embedding=[math.nan, 0]), "finite"),
    (lambda rows: rows[0].update(object_instance_id=""), "object_instance_id"),
    (lambda rows: rows[0].update(reference_id=" padded "), "reference_id"),
])
def test_gallery_metadata_and_vectors_are_validated(change, match):
    entries = gallery()
    change(entries)
    with pytest.raises(ValueError, match=match):
        rank_candidate(query(), entries, target_instance_id="target")


@pytest.mark.parametrize("options", [
    {"min_similarity": float("nan")}, {"min_similarity": 1.1},
    {"min_margin": -0.1}, {"min_margin": True}, {"min_support": 1},
    {"min_support": True}, {"min_support": 2.0},
])
def test_invalid_threshold_config_is_rejected(options):
    with pytest.raises(ValueError):
        rank_candidate(query(), gallery(), target_instance_id="target", **options)


def test_ranking_is_deterministic_under_reordering_and_does_not_mutate_inputs():
    entries = gallery() + [reference(4, "another-rival", (0, 1)), copy.deepcopy(reference(1))]
    before = copy.deepcopy(entries)
    first = rank_candidate(query(), entries, target_instance_id="target")
    second = rank_candidate(query(), list(reversed(entries)), target_instance_id="target")
    assert first == second
    assert entries == before


def test_human_label_is_not_an_input_to_appearance_decision():
    observation = query((-1, -1))
    observation["ground_truth"] = "target"
    observation["identity_confirmed"] = True
    result = rank_candidate(observation, gallery(), target_instance_id="target")
    assert result["status"] == "UNKNOWN"
    assert result["identity_confirmed"] is False
