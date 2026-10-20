"""Small SQLite evidence store; a historical positive is never a new finding."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import DetectionResult, MemoryRecord, Observation, RegisteredObject, Status


class MemoryStore(Protocol):
    def get_object(self, object_id: str) -> RegisteredObject | None: ...
    def query_memory(self, object_id: str) -> list[MemoryRecord]: ...
    def update_memory(
        self, observation: Observation, detection: DetectionResult
    ) -> bool: ...


class SQLiteMemory:
    def __init__(self, path: str | Path = ":memory:"):
        self.connection = sqlite3.connect(str(path))
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

    def register_object(
        self, object_id: str, sample_image_path: str | None, description: str
    ) -> RegisteredObject:
        if not object_id.strip():
            raise ValueError("object_id must not be empty")
        obj = RegisteredObject(object_id, description, sample_image_path)
        with self.connection:
            self.connection.execute(
                """INSERT INTO objects VALUES (?, ?, ?)
                ON CONFLICT(object_id) DO UPDATE SET
                    description=excluded.description,
                    sample_image_path=excluded.sample_image_path""",
                (object_id, description, sample_image_path),
            )
        return obj

    def get_object(self, object_id: str) -> RegisteredObject | None:
        row = self.connection.execute(
            "SELECT object_id, description, sample_image_path FROM objects WHERE object_id=?",
            (object_id,),
        ).fetchone()
        return RegisteredObject(*row) if row else None

    def query_memory(self, object_id: str) -> list[MemoryRecord]:
        rows = self.connection.execute(
            "SELECT payload FROM records WHERE object_id=?", (object_id,)
        ).fetchall()
        records = []
        for (payload,) in rows:
            value = json.loads(payload)
            value["detection"]["status"] = Status(value["detection"]["status"])
            records.append(
                MemoryRecord(
                    Observation(**value["observation"]),
                    DetectionResult(**value["detection"]),
                )
            )
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
        if self.get_object(detection.target_id) is None:
            raise ValueError(f"Unregistered object: {detection.target_id}")
        if datetime.fromisoformat(observation.captured_at).utcoffset() is None:
            raise ValueError("Evidence timestamp must include a timezone")
        payload = json.dumps(asdict(MemoryRecord(observation, detection)), sort_keys=True)
        previous = self.connection.execute(
            "SELECT payload FROM records WHERE evidence_id=? AND object_id=?",
            (observation.evidence_id, detection.target_id),
        ).fetchone()
        if previous:
            if previous[0] != payload:
                raise ValueError("Existing evidence cannot be rewritten")
            return False
        with self.connection:
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
