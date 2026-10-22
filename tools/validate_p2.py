"""Save fresh tests, CLI-backed visual-demo runs and source fingerprints.

Run from an environment with HomeTrace [dev,vision] installed. Browser recording
is a separate optional Node/Playwright development tool, validate_p2_browser.cjs.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

import hometrace
from hometrace.demo_service import DemoService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": platform.python_version(),
        "installed_package": str(Path(hometrace.__file__).resolve()).replace(str(root), "<REPO>"),
        "base": "b546fe72c21cefcda816074c4e9b423a350022d3", "commands": [],
    }
    commands = [
        ("pytest.txt", [sys.executable, "-m", "pytest", "-q", "--junitxml", str(output / "pytest.xml")]),
        ("pip-check.txt", [sys.executable, "-m", "pip", "check"]),
        ("dependencies.txt", [sys.executable, "-m", "pip", "freeze"]),
    ]
    for name, command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8")
        text = (result.stdout + result.stderr).replace(str(root), "<REPO>")
        (output / name).write_text(text, encoding="utf-8")
        metadata["commands"].append({"argv": [s.replace(str(root), "<REPO>") for s in command], "exit_code": result.returncode, "output": name})
        print(name, result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(f"Validation failed; see {name}")
    junit = ET.parse(output / "pytest.xml")
    cases = junit.findall(".//testcase")
    original_p0 = {"tests.test_cli", "tests.test_fixtures", "tests.test_memory", "tests.test_search_core"}
    prior_p1 = {"tests.test_recorded", "tests.test_image_matcher", "tests.test_p1_integration", "tests.test_search_integrity"}
    metadata.update({
        "tests": len(cases), "p0_tests": sum(c.get("classname") in original_p0 for c in cases),
        "p1_tests": sum(c.get("classname") in prior_p1 for c in cases),
        "skipped": len(junit.findall(".//skipped")),
    })
    service = DemoService(root / "examples/recorded_images", output / "runs")
    metadata["scenarios"] = []
    for name in ("moved", "missing", "replay"):
        run = service.run(name, "memory_first")
        metadata["scenarios"].append({
            "scenario": name, "run_id": run["run_id"], "result_status": run["report"]["result_status"],
            "location": run["report"]["location"], "comparison": run["comparison"]["rows"],
        })
        print(name, run["report"]["result_status"], flush=True)
    sources = [root / "pyproject.toml"]
    sources.extend(p for folder in ("src", "tests", "tools") for p in (root / folder).rglob("*") if p.is_file() and p.suffix in {".py", ".html", ".css", ".js", ".cjs"} and "__pycache__" not in p.parts)
    metadata["source_sha256"] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}
    (output / "validation.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Validated {metadata['tests']} tests; {metadata['p0_tests']} original P0, {metadata['p1_tests']} prior P1", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
