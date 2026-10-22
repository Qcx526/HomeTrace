"""Run the existing photo CLI in independent processes for a local demonstration.

The browser only replays real Search Core events. It never supplies detections.
Each comparison freezes the same inputs and starts from separate fresh stores.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

from .recorded import MAX_IMAGE_BYTES, load_recorded_scene, resolve_image_path


SCENARIOS = [
    {"id": "moved", "label": "找到目标", "description": "历史 A → 当前图像不足以确认 → 继续搜索 B"},
    {"id": "missing", "label": "未确认负例", "description": "检查全部候选点，保留 SUSPECTED / UNKNOWN"},
    {"id": "replay", "label": "旧图重放保护", "description": "在已搜索的数据库中重放，旧证据不能成为新发现"},
]
STRATEGIES = [
    {"id": "memory_first", "label": "记忆优先"},
    {"id": "fixed_order", "label": "固定顺序 A → B → C"},
]


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DemoBusyError(ValueError):
    pass


class DemoService:
    def __init__(self, samples_dir: Path, output_dir: Path):
        self.samples_dir = Path(samples_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._assets: dict[str, dict[str, tuple[Path, str]]] = {}
        self._downloads: dict[str, dict[str, Path]] = {}

    def config(self) -> dict:
        return {
            "scenarios": SCENARIOS, "strategies": STRATEGIES,
            "source_notice": "离线照片驱动的软件验证 · simulated_navigation · 内置为公开实拍样例；具体来源与时间依据见证据。非现场机器人运行。",
        }

    def _snapshot(self, directory: Path, scenario: str) -> tuple[Path, dict]:
        root = directory / "inputs"
        root.mkdir()
        manifests = ["history.json", "missing.json" if scenario == "missing" else "moved.json"]
        images = {"box.png"}
        for name in manifests:
            scene = load_recorded_scene(self.samples_dir / name)
            images.update(o.image_path for o in scene.observations.values())
            (root / name).write_bytes((self.samples_dir / name).read_bytes())
        for name in sorted(images):
            source = resolve_image_path(self.samples_dir, name)
            if source.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError("Demo input image exceeds 25 MiB")
            target = resolve_image_path(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        hashes = {name: digest(root / name) for name in sorted(images | set(manifests))}
        write_json(root / "input-hashes.json", hashes)
        return root, hashes

    def _cli(self, args: list[str], directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-X", "utf8", "-m", "hometrace", *args, "--output-dir", str(directory)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60)
        log = (result.stdout + result.stderr).replace(str(self.output_dir), "<DEMO_OUTPUT>")
        (directory / "stdout.txt").write_text(log, encoding="utf-8")
        write_json(directory / "command.json", {
            "argv": [s.replace(str(self.output_dir), "<DEMO_OUTPUT>") for s in command],
            "exit_code": result.returncode,
        })
        if result.returncode:
            raise ValueError("Photo command failed; inspect this run's stdout.txt")
        return json.loads((directory / "report.json").read_text(encoding="utf-8"))

    def run(self, scenario: str, strategy: str) -> dict:
        if scenario not in {x["id"] for x in SCENARIOS} or strategy not in {x["id"] for x in STRATEGIES}:
            raise ValueError("Unknown scenario or strategy")
        if not self._lock.acquire(blocking=False):
            raise DemoBusyError("Another demonstration is running; wait for it to finish")
        try:
            return self._run(scenario, strategy)
        finally:
            self._lock.release()

    def _run(self, scenario: str, selected_strategy: str) -> dict:
        run_id = uuid4().hex
        directory = self.output_dir / run_id
        directory.mkdir()
        image_root, hashes = self._snapshot(directory, scenario)
        manifest = image_root / ("missing.json" if scenario == "missing" else "moved.json")
        scene = load_recorded_scene(manifest)
        reports, registrations, previous = {}, {}, {}
        rows = []
        for strategy in ("memory_first", "fixed_order"):
            base = directory / strategy
            db = base / "memory.sqlite3"
            common = ["--db", str(db), "--object-id", "sample-box"]
            registrations[strategy] = self._cli([
                "register", *common, "--reference", "box.png",
                "--scene", str(image_root / "history.json"),
            ], base / "register")
            # Both replay comparisons start from the same memory-first search,
            # then vary only the strategy of the replay under evaluation.
            previous[strategy] = self._cli([
                "search", *common, "--scene", str(manifest), "--strategy", "memory_first",
            ], base / "prior-search") if scenario == "replay" else None
            report = self._cli([
                "search", *common, "--scene", str(manifest), "--strategy", strategy,
            ], base / "search")
            reports[strategy] = report
            rows.append({
                "strategy": strategy, "result_status": report["result_status"],
                "location": report["location"],
                "attempted": len(report["attempted_viewpoints"]),
                "arrived": len(report["arrived_viewpoints"]),
                "observed": len(report["observed_viewpoints"]),
                "observe_calls": sum(e["action"] == "observe" for e in report["events"]),
                "attempted_viewpoints": report["attempted_viewpoints"],
                "observed_viewpoints": report["observed_viewpoints"],
            })
        if hashes != {name: digest(image_root / name) for name in hashes}:
            raise ValueError("Inputs changed during comparison")
        comparison = {
            "rows": rows,
            "fairness": {
                "same_candidates": [asdict(v) for v in scene.viewpoints],
                "input_sha256": hashes, "separate_fresh_databases": True,
                "same_enrollment": True, "same_replay_seed_strategy": "memory_first" if scenario == "replay" else None,
                "fixed_order": "viewpoint_id ascending; independent of image answers",
                "metrics": "Actual attempted/arrived/decoded-observed counts; observe_calls counted separately. No movement time is measured.",
                "conclusion": (
                    "Counts tie on this sample; this is not evidence of a search efficiency improvement."
                    if all(rows[0][key] == rows[1][key] for key in ("attempted", "arrived", "observed", "observe_calls"))
                    else "Counts differ on this sample only; inspect results, paths and temporal rejections before drawing conclusions."
                ),
            },
        }
        write_json(directory / "comparison.json", comparison)
        report = reports[selected_strategy]
        # Serve only images referenced in the selected report, never arbitrary files.
        image_names = set()
        for record in report["historical_evidence"] + report["evidence"]:
            if record["observation"]["image_path"]:
                image_names.add(record["observation"]["image_path"])
        for event in report["events"]:
            observation = event["result"].get("observation")
            if observation and observation.get("image_path"):
                image_names.add(observation["image_path"])
        images, assets = {}, {}
        for name in sorted(image_names):
            key = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
            assets[key] = (resolve_image_path(image_root, name), hashes[name])
            images[name] = f"/api/runs/{run_id}/images/{key}"
        self._assets[run_id] = assets
        selected = directory / selected_strategy
        self._downloads[run_id] = {
            "report": selected / "search" / "report.json",
            "events": selected / "search" / "events.jsonl",
            "comparison": directory / "comparison.json",
            "registration": selected / "register" / "report.json",
            "session": directory / "session.json",
        }
        payload = {
            "run_id": run_id, "scenario": scenario, "strategy": selected_strategy,
            "report": report, "registration": registrations[selected_strategy],
            "prior_search": previous[selected_strategy],
            "viewpoints": [asdict(v) for v in scene.viewpoints], "images": images,
            "comparison": comparison,
            "downloads": {name: f"/api/runs/{run_id}/downloads/{name}" for name in self._downloads[run_id]},
        }
        write_json(directory / "session.json", payload)
        return payload

    def asset(self, run_id: str, key: str) -> Path:
        path, expected = self._assets[run_id][key]
        if digest(path) != expected:
            raise ValueError("Evidence image changed after this run")
        return path

    def download(self, run_id: str, key: str) -> Path:
        return self._downloads[run_id][key]
