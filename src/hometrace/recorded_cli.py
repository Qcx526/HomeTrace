"""Separate enrollment and search processes over a user-selected SQLite store."""

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from .image_matcher import ImageMatcher
from .memory import SQLiteMemory
from .models import DataSource, NavigationMode, SearchStrategy
from .recorded import MAX_IMAGE_BYTES, RecordedImageAdapter, load_recorded_scene, resolve_image_path
from .search_core import SearchCore


def _write_report(report, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "events.jsonl").write_text(
        "".join(json.dumps(asdict(event), ensure_ascii=False) + "\n" for event in report.events),
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="HomeTrace P1 — local photos, simulated navigation")
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("register", "search"):
        command = commands.add_parser(name)
        command.add_argument("--db", type=Path, required=True, help="Persistent local SQLite database")
        command.add_argument("--object-id", required=True)
        command.add_argument("--scene", type=Path, required=True, help="Recorded-image manifest without detection labels")
        command.add_argument("--image-root", type=Path, help="Defaults to the scene manifest directory")
        command.add_argument("--output-dir", type=Path, required=True)
        if name == "register":
            command.add_argument("--reference", required=True, help="Reference image path relative to image-root")
            command.add_argument(
                "--reference-roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                help="Object-only rectangle in original reference pixels; right/bottom exclusive, never applied to scene images",
            )
            command.add_argument("--description", default="Registered textured planar object")
        else:
            command.add_argument(
                "--strategy", choices=[strategy.value for strategy in SearchStrategy],
                default=SearchStrategy.MEMORY_FIRST.value,
                help="Memory-guided planning or viewpoint-ID order; neither reads future image results",
            )
    args = parser.parse_args(argv)
    try:
        scene = load_recorded_scene(args.scene, args.image_root)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for filename in ("report.json", "events.jsonl"):
            if (args.output_dir / filename).is_dir():
                raise ValueError(f"Output path is a directory: {filename}")
        with tempfile.TemporaryFile(dir=args.output_dir):
            pass
        if str(args.db) == ":memory:":
            raise ValueError("--db must be a persistent file, not :memory:")
        # An invalid enrollment must not leave a partially registered object.
        matcher = None
        if args.operation == "register":
            reference_path = resolve_image_path(scene.image_root, args.reference)
            if reference_path.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError("Reference image exceeds 25 MiB")
            reference_hash = hashlib.sha256(reference_path.read_bytes()).hexdigest()
            matcher = ImageMatcher(reference_path, reference_hash, args.object_id, scene.image_root, reference_roi=args.reference_roi)
            args.db.parent.mkdir(parents=True, exist_ok=True)
        elif not args.db.is_file():
            raise ValueError("Database does not exist; run register first")
        with SQLiteMemory(args.db) as memory, memory.transaction():
            if args.operation == "register":
                if memory.get_object(args.object_id) is not None:
                    raise ValueError("Object already registered; use search or choose a new object_id")
                memory.register_object(
                    args.object_id, args.reference, args.description,
                    reference_hash, DataSource.RECORDED_IMAGE,
                    reference_roi=matcher.reference_roi,
                )
            else:
                registered = memory.get_object(args.object_id)
                if registered is None:
                    raise ValueError(f"Unregistered object: {args.object_id}")
                if registered.data_source != DataSource.RECORDED_IMAGE:
                    raise ValueError("P1 search requires a recorded-image object, not a fixture object")
                reference_path = resolve_image_path(scene.image_root, registered.sample_image_path)
                matcher = ImageMatcher(
                    reference_path, registered.sample_image_hash, args.object_id, scene.image_root,
                    reference_roi=registered.reference_roi,
                )
            report = SearchCore(
                memory, RecordedImageAdapter(scene), matcher,
                data_source=DataSource.RECORDED_IMAGE,
                navigation_mode=NavigationMode.SIMULATED,
                operation=args.operation,
                strategy=SearchStrategy(getattr(args, "strategy", SearchStrategy.MEMORY_FIRST)),
            ).run(args.object_id)
            _write_report(report, args.output_dir)
        print(f"HomeTrace P1 | {args.operation} | simulated_navigation | data_source=recorded_image")
        print("Actual photo matching; no live camera or real robot. Demo-sequence times are not photo capture dates.")
        print(f"HISTORY {len(report.historical_evidence)}")
        print(f"STRATEGY {report.strategy.value}")
        for event in report.events:
            if event.action == "plan_next":
                print(f"[{event.seq:02}] PLAN {event.result['viewpoint_id']} reason={event.result['reason']}")
            elif event.action == "detect_target":
                details = event.result["diagnostics"]
                print(f"[{event.seq:02}] MATCH {event.result['status'].value} reason={details.get('reason')} "
                      f"inliers={details.get('inliers', 0)} elapsed_ms={details.get('elapsed_ms', 0)}")
            elif event.action == "view_result":
                print(f"[{event.seq:02}] VIEW {event.input_ids[0]} -> {event.result['status'].value}"
                      f" reason={event.result.get('reason', 'observation_result')}")
        print(f"RESULT {report.result_status.value} location={report.location or 'null'}")
        print(f"ATTEMPTED {','.join(report.attempted_viewpoints) or 'none'}")
        print(f"ARRIVED {','.join(report.arrived_viewpoints) or 'none'}")
        print(f"OBSERVED {','.join(report.observed_viewpoints) or 'none'}")
        print(f"CONFIRMED_EVIDENCE {','.join(report.confirmed_evidence_ids) or 'none'}")
        print(f"REPORT {args.output_dir.as_posix()}/report.json")
        print(f"EVENTS {args.output_dir.as_posix()}/events.jsonl")
        print(f"DATABASE {args.db.as_posix()}")
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"HomeTrace error: {exc}", file=sys.stderr)
        return 2
