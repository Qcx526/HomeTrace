"""Small SQLite evidence store; a historical positive is never a new finding."""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import DataSource, DetectionResult, MemoryRecord, Observation, RegisteredObject, Status, TimestampBasis


class MemoryStore(Protocol):
    def get_object(self, object_id: str) -> RegisteredObject | None: ...
    def query_memory(self, object_id: str) -> list[MemoryRecord]: ...
    def update_memory(
        self, observation: Observation, detection: DetectionResult
    ) -> bool: ...


class SQLiteMemory:
    @staticmethod
    def _decode_record(payload: str) -> MemoryRecord:
        value = json.loads(payload)
        value["observation"]["data_source"] = DataSource(value["observation"]["data_source"])
        value["observation"]["timestamp_basis"] = TimestampBasis(value["observation"].get("timestamp_basis", "fixture"))
        value["detection"]["status"] = Status(value["detection"]["status"])
        if value["detection"].get("data_source") is not None:
            value["detection"]["data_source"] = DataSource(value["detection"]["data_source"])
        return MemoryRecord(Observation(**value["observation"]), DetectionResult(**value["detection"]))

    def __init__(self, path: str | Path = ":memory:"):
        self.connection = sqlite3.connect(str(path))
        self._transaction_depth = 0
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS objects (
                object_id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                sample_image_path TEXT
            );
            CREATE TABLE IF NOT EXISTS records (
                evidence_id TEXT NOT NULL,
                object_id TEXT NOT NULL REFERENCES objects(object_id),
                payload TEXT NOT NULL,
                PRIMARY KEY (evidence_id, object_id)
            );
            """
        )
        # Additive migration: P0 databases and their evidence remain readable.
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(objects)")}
        with self.connection:
            if "sample_image_hash" not in columns:
                self.connection.execute("ALTER TABLE objects ADD COLUMN sample_image_hash TEXT")
            if "data_source" not in columns:
                self.connection.execute("ALTER TABLE objects ADD COLUMN data_source TEXT NOT NULL DEFAULT 'fixture'")

    @contextmanager
    def transaction(self):
        """Group registration, evidence updates and report writing into one operation."""
        outermost = self._transaction_depth == 0
        if outermost:
            self.connection.execute("BEGIN IMMEDIATE")
        self._transaction_depth += 1
        try:
            yield
            if outermost:
                self.connection.commit()
        except BaseException:
            if outermost:
                self.connection.rollback()
            raise
        finally:
            self._transaction_depth -= 1

    def register_object(
        self, object_id: str, sample_image_path: str | None, description: str,
        sample_image_hash: str | None = None, data_source: DataSource = DataSource.FIXTURE,
    ) -> RegisteredObject:
        if not object_id.strip():
            raise ValueError("object_id must not be empty")
        source = DataSource(data_source)
        if source == DataSource.RECORDED_IMAGE and (not sample_image_path or not sample_image_hash):
            raise ValueError("Recorded-image registration requires a reference path and SHA256")
        obj = RegisteredObject(object_id, description, sample_image_path, sample_image_hash, source)
        previous = self.get_object(object_id)
        if previous and (previous.sample_image_path, previous.sample_image_hash, previous.data_source) != (
            sample_image_path, sample_image_hash, source
        ):
            raise ValueError("Existing object reference/source is immutable; register a new object_id")
        with self.transaction():
            self.connection.execute(
                """INSERT INTO objects (object_id, description, sample_image_path, sample_image_hash, data_source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(object_id) DO UPDATE SET
                    description=excluded.description""",
                (object_id, description, sample_image_path, sample_image_hash, source.value),
            )
        return obj

    def get_object(self, object_id: str) -> RegisteredObject | None:
        row = self.connection.execute(
            "SELECT object_id, description, sample_image_path, sample_image_hash, data_source FROM objects WHERE object_id=?",
            (object_id,),
        ).fetchone()
        return RegisteredObject(*row[:4], DataSource(row[4])) if row else None

    def query_memory(self, object_id: str) -> list[MemoryRecord]:
        rows = self.connection.execute(
            "SELECT payload FROM records WHERE object_id=?", (object_id,)
        ).fetchall()
        records = [self._decode_record(payload) for (payload,) in rows]
        return sorted(
            records,
            key=lambda r: (
                datetime.fromisoformat(r.observation.captured_at),
                r.observation.evidence_id,
            ),
        )

    def update_memory(
        self, observation: Observation, detection: DetectionResult
    ) -> bool:
        if observation.evidence_id != detection.evidence_id:
            raise ValueError("Detection must refer to the supplied observation")
        obj = self.get_object(detection.target_id)
        if obj is None:
            raise ValueError(f"Unregistered object: {detection.target_id}")
        if DataSource(observation.data_source) != obj.data_source:
            raise ValueError("Evidence source must match the registered object")
        if detection.data_source is not None and DataSource(detection.data_source) != obj.data_source:
            raise ValueError("Detection source must match the registered object")
        if datetime.fromisoformat(observation.captured_at).utcoffset() is None:
            raise ValueError("Evidence timestamp must include a timezone")
        payload = json.dumps(asdict(MemoryRecord(observation, detection)), sort_keys=True)
        previous = self.connection.execute(
            "SELECT payload FROM records WHERE evidence_id=? AND object_id=?",
            (observation.evidence_id, detection.target_id),
        ).fetchone()
        if previous:
            if json.dumps(asdict(self._decode_record(previous[0])), sort_keys=True) != payload:
                raise ValueError("Existing evidence cannot be rewritten")
            return False
        with self.transaction():
            self.connection.execute(
                "INSERT INTO records VALUES (?, ?, ?)",
                (observation.evidence_id, detection.target_id, payload),
            )
        return True

    def save_snapshot(self, path: Path) -> None:
        with closing(sqlite3.connect(str(path))) as destination:
            self.connection.backup(destination)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteMemory":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
