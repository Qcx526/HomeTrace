"""Input-boundary tests use synthetic bytes, not real-photo recognition evidence."""

import hashlib
import json
from dataclasses import replace

import pytest

from hometrace.models import DataSource, NavigationMode, TimestampBasis
from hometrace.recorded import RecordedImageAdapter, load_recorded_scene, resolve_image_path


def manifest_data():
    return {
        "schema_version": 1,
        "data_source": "recorded_image",
        "navigation_mode": "simulated_navigation",
        "timestamp_basis": "demo_sequence",
        "capture_source": "Synthetic bytes for input-boundary unit tests only",
        "viewpoints": [{"viewpoint_id": "A", "name": "Test A"}, {"viewpoint_id": "B", "name": "Test B"}],
        "observations": [{
            "evidence_id": "test-A", "viewpoint_id": "A", "captured_at": "2026-10-21T10:00:00+08:00",
            "image_path": "test.png", "visibility_status": "clear",
        }],
        "unreachable_viewpoints": ["B"],
    }


def write_manifest(tmp_path, data=None):
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(data if data is not None else manifest_data()), encoding="utf-8")
    return path


def test_recorded_adapter_reads_actual_bytes_only_after_simulated_arrival(tmp_path):
    path = write_manifest(tmp_path)
    content = b"synthetic bytes; decoding belongs to the matcher"
    (tmp_path / "test.png").write_bytes(content)
    scene = load_recorded_scene(path)
    assert scene.observations["A"].image_hash is None
    assert scene.observations["A"].timestamp_basis == TimestampBasis.DEMO_SEQUENCE
    adapter = RecordedImageAdapter(scene)
    assert adapter.observe("A") is None
    navigation = adapter.navigate_to("A")
    assert navigation.simulated is True
    assert navigation.adapter_kind == "recorded_image"
    assert navigation.navigation_mode == NavigationMode.SIMULATED
    observation = adapter.observe("A")
    assert observation.data_source == DataSource.RECORDED_IMAGE
    assert observation.image_hash == hashlib.sha256(content).hexdigest()
    assert observation.image_path == "test.png"
    assert observation.captured_at == "2026-10-21T10:00:00+08:00"
    assert observation.error is None
    # Hash is computed at observation time, never copied from the manifest/cache.
    (tmp_path / "test.png").write_bytes(b"different synthetic bytes")
    assert adapter.observe("A").image_hash != observation.image_hash
    assert adapter.navigate_to("B").status == "UNREACHABLE"
    assert adapter.observe("A") is None
    assert adapter.observe("B") is None


@pytest.mark.parametrize("kind,expected", [("missing", "image_missing"), ("empty", "image_empty"), ("directory", "image_not_file")])
def test_unusable_files_are_observations_with_errors_not_fake_negatives(tmp_path, kind, expected):
    if kind == "empty":
        (tmp_path / "test.png").write_bytes(b"")
    elif kind == "directory":
        (tmp_path / "test.png").mkdir()
    adapter = RecordedImageAdapter(load_recorded_scene(write_manifest(tmp_path)))
    adapter.navigate_to("A")
    observation = adapter.observe("A")
    assert observation.error == expected
    if kind != "empty":
        assert observation.image_hash is None


def test_oversized_file_is_not_read_as_image(tmp_path, monkeypatch):
    import hometrace.recorded as recorded
    monkeypatch.setattr(recorded, "MAX_IMAGE_BYTES", 8)
    (tmp_path / "test.png").write_bytes(b"123456789")
    adapter = RecordedImageAdapter(load_recorded_scene(write_manifest(tmp_path)))
    adapter.navigate_to("A")
    assert adapter.observe("A").error == "image_too_large"


@pytest.mark.parametrize("image_path", ["../outside.png", "/outside.png", "C:/outside.png", "C:outside.png", "folder\\outside.png", "folder//outside.png", "./test.png", "test.png:stream", "data.txt"])
def test_paths_cannot_escape_or_use_platform_specific_file_streams(tmp_path, image_path):
    data = manifest_data()
    data["observations"][0]["image_path"] = image_path
    with pytest.raises(ValueError, match="image_path"):
        load_recorded_scene(write_manifest(tmp_path, data))


def test_image_root_override_and_unicode_relative_path(tmp_path):
    image_root = tmp_path / "pictures"
    image_root.mkdir()
    data = manifest_data()
    data["observations"][0]["image_path"] = "实拍样例.png"
    (image_root / "实拍样例.png").write_bytes(b"synthetic bytes")
    scene = load_recorded_scene(write_manifest(tmp_path, data), image_root)
    assert scene.image_root == image_root.resolve()
    assert resolve_image_path(scene.image_root, "实拍样例.png") == image_root / "实拍样例.png"


@pytest.mark.parametrize("change,message", [
    (lambda d: d.update(data_source="real_robot"), "data_source"),
    (lambda d: d.update(navigation_mode="real_robot"), "navigation_mode"),
    (lambda d: d.update(timestamp_basis="fixture"), "timestamp_basis"),
    (lambda d: d.update(timestamp_basis="unknown"), "timestamp_basis"),
    (lambda d: d.update(capture_source=""), "capture_source"),
    (lambda d: d.update(detections=[{"status": "FOUND"}]), "unknown fields"),
    (lambda d: d["observations"][0].update(image_hash="invented-hash"), "unknown fields"),
    (lambda d: d["observations"][0].update(captured_at="2026-10-21T10:00:00"), "timezone"),
    (lambda d: d["observations"][0].update(captured_at="not-a-time"), "ISO timestamp"),
    (lambda d: d["observations"][0].update(visibility_status="invisible"), "visibility_status"),
    (lambda d: d["observations"].append(d["observations"][0].copy()), "duplicate evidence"),
    (lambda d: d["observations"].append(dict(d["observations"][0], evidence_id="another-id")), "one observation"),
    (lambda d: d["viewpoints"].append(d["viewpoints"][0].copy()), "duplicate viewpoint"),
    (lambda d: d["observations"][0].update(viewpoint_id="absent"), "unknown viewpoint"),
    (lambda d: d.update(unreachable_viewpoints=["absent"]), "known viewpoints"),
    (lambda d: d.update(schema_version=True), "schema_version"),
])
def test_manifest_rejects_ambiguous_provenance_or_target_answers(tmp_path, change, message):
    data = manifest_data()
    change(data)
    with pytest.raises(ValueError, match=message):
        load_recorded_scene(write_manifest(tmp_path, data))


def test_duplicate_json_source_fields_are_rejected(tmp_path):
    path = tmp_path / "scene.json"
    path.write_text('{"data_source":"real_robot","data_source":"recorded_image"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON field"):
        load_recorded_scene(path)


def test_adapter_cannot_promote_real_robot_observations(tmp_path):
    scene = load_recorded_scene(write_manifest(tmp_path))
    observations = {"A": replace(scene.observations["A"], data_source="real_robot")}
    with pytest.raises(ValueError, match="recorded_image observations only"):
        RecordedImageAdapter(replace(scene, observations=observations))


def test_symlink_escape_is_rejected_at_load_and_after_manifest_load(tmp_path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside bytes")
    manifest = write_manifest(image_root)
    scene = load_recorded_scene(manifest)
    adapter = RecordedImageAdapter(scene)
    try:
        (image_root / "test.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("This platform/account cannot create symlinks")
    with pytest.raises(ValueError, match="escapes"):
        load_recorded_scene(manifest)
    adapter.navigate_to("A")
    observation = adapter.observe("A")
    assert observation.error == "invalid_image_path"
    assert observation.image_hash is None
