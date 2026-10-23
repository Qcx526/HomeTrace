"""Explicit local object identities; manifests never supply detection answers."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from .recorded import MAX_IMAGE_BYTES, load_recorded_scene, resolve_image_path, _unique_json_object


@dataclass(frozen=True)
class DemoCase:
    case_id: str
    label: str
    object_id: str
    reference: str
    root: Path
    source_notice: str
    history_note: str
    private: bool = False

    def public_metadata(self) -> dict:
        return {key: getattr(self, key) for key in (
            "case_id", "label", "object_id", "reference", "source_notice", "history_note", "private",
        )}


def default_case(root: Path) -> DemoCase:
    return DemoCase(
        "public", "OpenCV 公开样例", "sample-box", "box.png", root.resolve(),
        "公开实拍照片驱动的软件验证 · simulated_navigation · A/B/C 与时间为演示编排，非现场机器人运行。",
        "样例历史 A 使用参考图自匹配建立，不能计作独立识别成绩。",
    )


def load_case(path: Path) -> DemoCase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
    keys = {"schema_version", "case_id", "label", "object_id", "reference", "image_root", "source_notice", "history_note"}
    if not isinstance(raw, dict) or set(raw) != keys or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("Local case requires schema_version 1 and the documented fields only")
    if any(not isinstance(raw[k], str) or not raw[k].strip() for k in keys - {"schema_version"}):
        raise ValueError("Local case metadata must contain nonempty strings")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,40}", raw["case_id"]) or raw["case_id"] == "public":
        raise ValueError("Invalid or reserved case_id")
    if raw["object_id"] == "sample-box":
        raise ValueError("Local cases require their own object_id")
    parent = Path(path).resolve().parent
    root = (parent / raw["image_root"]).resolve()
    if not root.is_relative_to(parent):
        raise ValueError("Local case image_root must stay inside the configuration directory")
    validate_case_inputs(root, raw["reference"])
    return DemoCase(raw["case_id"], raw["label"], raw["object_id"], raw["reference"], root,
                    raw["source_notice"], raw["history_note"], private=True)


def validate_case_inputs(root: Path, reference_name: str, scene_names=("history", "moved", "missing")) -> None:
    """Recheck the frozen inputs too; files may have changed after server startup."""
    reference = resolve_image_path(root, reference_name)
    if not reference.is_file():
        raise ValueError("Local case reference is missing")
    scenes = {name: load_recorded_scene(root / f"{name}.json") for name in scene_names}
    history = list(scenes["history"].observations.values())
    if not history:
        raise ValueError("Local case requires independent historical observations")
    for scene in scenes.values():
        for observed in scene.observations.values():
            image = resolve_image_path(root, observed.image_path)
            if not image.is_file() or not 0 < image.stat().st_size <= MAX_IMAGE_BYTES:
                raise ValueError("Local case image is missing, empty or exceeds 25 MiB")
    if not 0 < reference.stat().st_size <= MAX_IMAGE_BYTES:
        raise ValueError("Local case reference is empty or exceeds 25 MiB")
    reference_hash = hashlib.sha256(reference.read_bytes()).digest()
    if any(hashlib.sha256(resolve_image_path(root, o.image_path).read_bytes()).digest() == reference_hash for o in history):
        raise ValueError("Local historical evidence must be independent of the reference image")
    basis = {o.timestamp_basis for scene in scenes.values() for o in scene.observations.values()}
    if len(basis) != 1:
        raise ValueError("Local case mixes timestamp bases")
    latest = max(datetime.fromisoformat(o.captured_at) for o in history)
    for name in scenes.keys() - {"history"}:
        if any(datetime.fromisoformat(o.captured_at) <= latest for o in scenes[name].observations.values()):
            raise ValueError("Search observations must be newer than historical evidence")
