"""Reproducible CLI: each invocation starts with a fresh fixture memory."""

import argparse
import json
import sys
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

from .environment import MockAdapter
from .fixtures import load_fixture
from .memory import SQLiteMemory
from .perception import FixtureDetector
from .search_core import SearchCore


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("register", "search"):
        from .recorded_cli import main as recorded_main

        return recorded_main(argv)
    parser = argparse.ArgumentParser(description="HomeTrace P0 — Mock navigation / fixture observations")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--scenario", choices=("moved", "missing"), default="moved")
    source.add_argument("--fixture", type=Path, help="Custom fixture JSON (no real image/robot support)")
    parser.add_argument("--object-id", default="remote-control")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/demo"))
    args = parser.parse_args(argv)
    try:
        fixture_path = args.fixture or Path(str(files("hometrace").joinpath("fixture_data", f"{args.scenario}.json")))
        scenario = load_fixture(fixture_path)
        with SQLiteMemory() as memory:
            obj = scenario.object
            memory.register_object(obj.object_id, obj.sample_image_path, obj.description)
            for record in scenario.memory_records:
                memory.update_memory(record.observation, record.detection)
            environment = MockAdapter(
                scenario.viewpoints, scenario.observations, scenario.unreachable_viewpoints
            )
            core = SearchCore(memory, environment, FixtureDetector(scenario.detections))
            report = core.run(args.object_id)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "report.json").write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (args.output_dir / "events.jsonl").write_text(
                "".join(json.dumps(asdict(event), ensure_ascii=False) + "\n" for event in report.events),
                encoding="utf-8",
            )
            memory.save_snapshot(args.output_dir / "memory.sqlite3")
        print("HomeTrace P0 | Mock navigation | data_source=fixture")
        print("Synthetic annotations only; no camera, visual model or real robot execution.")
        for event in report.events:
            if event.action == "plan_next":
                print(f"[{event.seq:02}] PLAN {event.result['viewpoint_id']} reason={event.result['reason']}")
            elif event.action == "view_result":
                print(f"[{event.seq:02}] VIEW {event.input_ids[0]} -> {event.result['status'].value}")
        print(f"RESULT {report.result_status.value} location={report.location or 'null'}")
        print(f"VISITED {','.join(report.visited_viewpoints)}")
        print(f"EVIDENCE {','.join(report.evidence_ids) or 'none'}")
        print(f"REPORT {args.output_dir.as_posix()}/report.json")
        print(f"EVENTS {args.output_dir.as_posix()}/events.jsonl")
        print(f"MEMORY {args.output_dir.as_posix()}/memory.sqlite3")
        return 0
    except (OSError, ValueError) as exc:
        print(f"HomeTrace error: {exc}", file=sys.stderr)
        return 2
