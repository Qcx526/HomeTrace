"""Run P0/P1 checks and public-photo demos; keep local outputs out of Git by default."""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "examples/recorded_images"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="Must be a new directory")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    # Each validation really enrolls in new databases; no automatic database deletion.
    output.mkdir(parents=True, exist_ok=False)
    steps = []
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NO_COLOR="1")

    def run(arguments, log):
        command = [sys.executable, *map(str, arguments)]
        result = subprocess.run(command, cwd=ROOT, env=environment, text=True, encoding="utf-8",
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / log).parent.mkdir(parents=True, exist_ok=True)
        normalized = result.stdout.replace(str(ROOT), "<REPO>").replace(ROOT.as_posix(), "<REPO>")
        (output / log).write_text(normalized, encoding="utf-8")
        print(normalized, end="", flush=True)
        steps.append({"command": [value.replace(str(ROOT), "<REPO>") for value in command],
                      "exit_code": result.returncode, "output": log})
        if result.returncode:
            raise SystemExit(result.returncode)

    run(["-m", "pip", "check"], "pip-check.txt")
    run(["-m", "pytest", "-q", "--junitxml", str(output / "pytest.xml")], "pytest.txt")
    run(["-m", "pip", "freeze"], "dependencies.txt")
    for scenario in ("moved", "missing"):
        run(["-m", "hometrace", "--scenario", scenario, "--output-dir", str(output / f"p0-{scenario}")], f"p0-{scenario}/stdout.txt")
        db = output / scenario / "memory.sqlite3"
        run(["-m", "hometrace", "register", "--db", db, "--object-id", "sample-box", "--reference", "box.png",
             "--scene", SAMPLES / "history.json", "--output-dir", output / scenario / "register"], f"{scenario}/register/stdout.txt")
        run(["-m", "hometrace", "search", "--db", db, "--object-id", "sample-box",
             "--scene", SAMPLES / f"{scenario}.json", "--output-dir", output / scenario / "search"], f"{scenario}/search/stdout.txt")
    # Repeating identical inputs is an explicit replay check, not another capture.
    run(["-m", "hometrace", "search", "--db", output / "moved/memory.sqlite3", "--object-id", "sample-box",
         "--scene", SAMPLES / "moved.json", "--output-dir", output / "replay"], "replay/stdout.txt")

    from hometrace.image_matcher import ImageMatcher
    from hometrace.models import DataSource, Observation, TimestampBasis

    source_inventory = json.loads((SAMPLES / "sources.json").read_text(encoding="utf-8"))
    for row in source_inventory["files"]:
        assert hashlib.sha256((SAMPLES / row["path"]).read_bytes()).hexdigest() == row["sha256"]
    reference = SAMPLES / "box.png"
    matcher = ImageMatcher(reference, hashlib.sha256(reference.read_bytes()).hexdigest(), "sample-box", SAMPLES)
    results = []
    # Ground truth is used only to evaluate detector output, never given to it.
    for filename, expected in [("box_in_scene.png", True), ("apple.jpg", False), ("orange.jpg", False), ("fruits.jpg", False)]:
        image_hash = hashlib.sha256((SAMPLES / filename).read_bytes()).hexdigest()
        observation = Observation(
            f"benchmark-{filename}", "benchmark", "2026-10-21T12:00:00+08:00", DataSource.RECORDED_IMAGE,
            image_path=filename, image_hash=image_hash, capture_source=source_inventory["capture_source"],
            timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
        )
        detections = [matcher.detect_target(observation, "sample-box") for _ in range(10)]
        times = [row.diagnostics["elapsed_ms"] for row in detections]
        assert len({row.status for row in detections}) == 1
        results.append({
            "image": filename, "sha256": image_hash, "expected_target_visible": expected,
            "detection": asdict(detections[0]), "repetitions": 10,
            "elapsed_ms": {"min": min(times), "median": statistics.median(times), "max": max(times)},
        })
    benchmark = {
        "scope": "Four distinct public photographic test images; enrollment self-match excluded. Repetitions measure timing, not additional independent observations.",
        "timing_scope": "Actual PC wall-clock per detect_target including file hash/decode/features/geometry; excludes interpreter startup and reference feature initialization. Cached file reads may apply.",
        "platform": platform.platform(), "processor": platform.processor(), "logical_cpu_count": os.cpu_count(),
        "python": platform.python_version(), "opencv": version("opencv-python-headless"), "numpy": version("numpy"),
        "opencv_threads": 1, "seed": 0, "positive_images": 1, "negative_images": 3,
        "false_found": sum(not r["expected_target_visible"] and r["detection"]["status"] == "FOUND" for r in results),
        "missed_found": sum(r["expected_target_visible"] and r["detection"]["status"] != "FOUND" for r in results),
        "negative_suspected": sum(not r["expected_target_visible"] and r["detection"]["status"] == "SUSPECTED" for r in results),
        "edge_device_latency": None,
        "limitations": ["Not an accuracy benchmark or family-scene validation.", "No embedded board or robot was tested.", "Similar printed instances are not distinguishable."],
        "images": results,
    }
    (output / "vision-results.json").write_text(json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases = ET.parse(output / "pytest.xml").findall(".//testcase")
    original_modules = {"test_cli", "test_fixtures", "test_memory", "test_search_core"}
    p0 = [case for case in cases if case.get("classname", "").split(".")[-1] in original_modules]
    assert len(p0) == 54 and not any(list(case) for case in p0)
    sources = [ROOT / "pyproject.toml", *sorted((ROOT / "src/hometrace").rglob("*.py")),
               *sorted((ROOT / "tests").glob("*.py")), ROOT / "tools/validate_p1.py"]
    metadata = {
        "validated_at_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "python": platform.python_version(), "tests": len(cases), "p0_tests": len(p0),
        "skipped": sum(case.find("skipped") is not None for case in cases),
        "git_base": "caf693f74c298992d7266049cfc29609158b43b8",
        "log_normalization": "Workspace absolute paths replaced with <REPO> in text logs; task JSON contains relative image paths.",
        "steps": steps,
        "source_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    }
    (output / "validation.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Validation complete: {len(cases)} tests, {len(p0)} original P0; false_found={benchmark['false_found']}, negative_suspected={benchmark['negative_suspected']}")


if __name__ == "__main__":
    main()
