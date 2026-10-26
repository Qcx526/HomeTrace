"""Deterministic post-inference scoring, with no label access by the detector."""

from collections import Counter
import re
from vision_r1 import box_iou

LABELS = {"positive", "negative", "uncertain", "auxiliary"}
SOURCES = {"real", "synthetic", "augmented"}
SPLITS = {"diagnostic_reused", "independent_test", "software_fixture"}


def _ratio(a, b):
    return a / b if b else None


def summarize(rows, labels):
    truth = {}
    for label in labels:
        sid = label["sample_id"]
        if not isinstance(sid, str) or not sid or sid in truth:
            raise ValueError("Duplicate or invalid evaluation sample")
        if not isinstance(label["object_instance_id"], str) or not label["object_instance_id"]:
            raise ValueError("Evaluation requires bound instance identity")
        if label["label"] not in LABELS or label["source_type"] not in SOURCES or label["split"] not in SPLITS:
            raise ValueError("Invalid evaluation provenance")
        if label["source_type"] != "real" and label["split"] == "independent_test":
            raise ValueError("Independent household acceptance requires real photographs")
        if not isinstance(label["capture_batch"], str) or not label["capture_batch"]:
            raise ValueError("Capture batch must be recorded")
        box = label["target_box"]
        if label["box_source"] not in {"none", "human"}:
            raise ValueError("Model predictions cannot be ground truth")
        if (box is not None and (label["box_source"] != "human" or box_iou(box, box) != 1 or label["label"] != "positive")
                or box is None and label["box_source"] != "none"):
            raise ValueError("Invalid human target box")
        reviews = label.get("instance_reviews", {})
        if not isinstance(reviews, dict) or any(v is not None and (not isinstance(v, dict) or
                set(v) != {"verdict", "prediction_fingerprint"} or v["verdict"] not in {"correct", "wrong"} or
                not isinstance(v["prediction_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", v["prediction_fingerprint"])) for v in reviews.values()):
            raise ValueError("Invalid method-specific identity review")
        if label.get("instance_review") is not None:
            raise ValueError("Identity review must be specific to method output")
        truth[sid] = label
    seen, methods = set(), {}
    for row in rows:
        method, sid = row["method"], row["sample_id"]
        if not isinstance(method, str) or not method or sid not in truth or (method, sid) in seen:
            raise ValueError("Unknown or duplicate result")
        seen.add((method, sid))
        if (row["status"] not in {"EXPERIMENTAL_ACCEPTED", "UNKNOWN"} or type(row["executed"]) is not bool
                or not isinstance(row["reason"], str) or not row["reason"]):
            raise ValueError("Invalid experimental result")
        if row["source_type"] != truth[sid]["source_type"]:
            raise ValueError("Cannot relabel data source after inference")
        if row["object_instance_id"] != truth[sid]["object_instance_id"]:
            raise ValueError("Cannot relabel target instance after inference")
        accepted = row["status"] == "EXPERIMENTAL_ACCEPTED"
        if not isinstance(row.get("prediction_fingerprint"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["prediction_fingerprint"]):
            raise ValueError("Result requires current prediction fingerprint")
        if accepted and (not row["executed"] or box_iou(row["bbox"], row["bbox"]) != 1):
            raise ValueError("Acceptance requires executed valid localization")
        if not accepted and row["bbox"] is not None:
            raise ValueError("Rejected result must not expose an accepted box")
        methods.setdefault(method, {})[sid] = row
    output = {}
    for method, indexed in sorted(methods.items()):
        grouped = {}
        for sid, label in truth.items():
            row = indexed.get(sid, {"status": "UNKNOWN", "reason": "missing_result", "executed": False, "bbox": None})
            key = label["source_type"] + "/" + label["split"]
            grouped.setdefault(key, []).append((row, label))
        output[method] = {}
        for key, data in sorted(grouped.items()):
            result = _group(method, data)
            objects = sorted({l["object_instance_id"] for _, l in data})
            result["per_instance"] = {oid: _group(method, [(r, l) for r, l in data if l["object_instance_id"] == oid]) for oid in objects}
            if len(objects) > 1:
                result["restricted_demo_gate"] = "BLOCKED_MIXED_INSTANCES_USE_PER_INSTANCE"
                result["gate_prerequisites_met"] = False
            output[method][key] = result
    return {"methods": output, "gate": "BLOCKED" if not output else "SEE_METHOD_GROUPS",
            "notes": ["EXPERIMENTAL_ACCEPTED is geometric support, not production FOUND",
                      "diagnostic_reused and software_fixture cannot establish real independent improvement",
                      "capture independence, reference freeze and human identity reviews require external audit"]}


def _group(method, pairs):
    planned = Counter(label["label"] for _, label in pairs)
    executed = Counter(label["label"] for row, label in pairs if row["executed"])
    accepted_count = tp = fp = fn = tn = unknown = negative_fp = 0
    presence_tp = presence_fp = 0
    scored = []
    for row, label in pairs:
        accepted = row["status"] == "EXPERIMENTAL_ACCEPTED"
        accepted_count += int(accepted)
        item = {"sample_id": label["sample_id"], "executed": row["executed"], "iou": None,
                "correct_instance_localization": None, "label": label["label"]}
        if label["label"] in {"uncertain", "auxiliary"}:
            scored.append(item)
            continue
        positive = label["label"] == "positive"
        presence_tp += int(accepted and positive)
        presence_fp += int(accepted and not positive)
        if not accepted:
            fn += int(positive)
            tn += int(not positive and row["executed"])
            item["correct_instance_localization"] = False
        elif not positive:
            fp += 1
            negative_fp += 1
            item["correct_instance_localization"] = False
        else:
            entry = label.get("instance_reviews", {}).get(method)
            review = entry["verdict"] if entry and entry["prediction_fingerprint"] == row.get("prediction_fingerprint") else None
            box = label["target_box"]
            if box is not None:
                item["iou"] = box_iou(row["bbox"], box)
            if review == "wrong":
                correct = False
            elif review == "correct" and box is not None:
                correct = item["iou"] >= .5
            else:
                correct = None
            item["correct_instance_localization"] = correct
            if correct is None:
                unknown += 1
            else:
                tp += int(correct)
                fp += int(not correct)
                fn += int(not correct)
        scored.append(item)
    precision = _ratio(tp, tp + fp) if not unknown else None
    recall = _ratio(tp, planned["positive"]) if not unknown else None
    unexecuted = sum(not r["executed"] for r, _ in pairs)
    complete_truth = all(l["label"] != "positive" or l["target_box"] is not None for _, l in pairs)
    batches = {l["capture_batch"] for _, l in pairs if l["label"] in {"positive", "negative"}}
    independent = all(l["source_type"] == "real" and l["split"] == "independent_test" for _, l in pairs)
    batch_verified = not any(x.strip().lower() in {"unknown", "unverified", "pending"} for x in batches)
    prerequisites = (independent and batch_verified and len(batches) >= 2 and planned["positive"] >= 6 and
                     planned["negative"] >= 8 and not unexecuted and complete_truth and not unknown)
    passed = prerequisites and recall is not None and recall >= 5/6 and negative_fp == 0 and precision is not None and precision >= .95
    return {"planned": dict(sorted(planned.items())), "executed": dict(sorted(executed.items())),
            "row_count": len(pairs), "unexecuted_count": unexecuted, "accepted_count": accepted_count,
            "reason_counts": dict(sorted(Counter(r["reason"] for r, _ in pairs).items())),
            "presence_proxy": {"positive_geometric_acceptances": presence_tp, "negative_false_acceptances": presence_fp},
            "instance_localization": {"status": "PARTIAL" if unknown or unexecuted else "SCORED",
                "correct": tp, "false_acceptances": fp, "misses": fn, "true_negatives": tn,
                "unverified_acceptances": unknown, "precision": precision, "recall": recall,
                "negative_false_acceptances": negative_fp, "negative_count": planned["negative"],
                "negative_false_acceptance_rate": _ratio(negative_fp, executed["negative"])},
            "localization_truth_complete": complete_truth, "samples": scored,
            "restricted_demo_gate": "PASS_PENDING_PROVENANCE_AUDIT" if passed else "BLOCKED",
            "gate_prerequisites_met": bool(prerequisites)}
