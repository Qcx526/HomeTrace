"""Isolated household memory prototype; statements are never visual evidence.

Only Python's standard library is needed. Store the database as an ignored
``*.sqlite3`` file, for example ``artifacts/household-memory/home.sqlite3``.
This CLI does not use an LLM, capture a camera, train a model or call SearchCore.
"""

from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata


APPLICATION_ID = 0x4854484D
SCHEMA_VERSION = 1
COMPONENT = "hometrace.household-owner-memory"
TABLES = {"hm_meta", "hm_objects", "hm_owner_events"}


class MemoryContractError(ValueError):
    """Invalid input or a database outside this isolated prototype."""


def _text(value: str, label: str, maximum: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise MemoryContractError(f"{label} 必须是 1..{maximum} 字符的文本")
    if any(ord(c) < 32 for c in value):
        raise MemoryContractError(f"{label} 不得包含控制字符")
    return value.strip()


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise MemoryContractError(f"{label} 须以小写字母开头，仅含小写字母、数字、下划线或连字符，最长 64 字符")
    return value


def _time(value: str) -> datetime:
    try:
        if not isinstance(value, str) or "T" not in value:
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise MemoryContractError("reported_at 必须是有效且含时区的 ISO 8601 日期时间，例如 2026-10-27T10:30:00+08:00") from exc


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class HouseholdMemory:
    """Append-only owner statements, stored separately from production memory."""

    def __init__(self, path: str | Path):
        original = Path(path).expanduser()
        if original.is_symlink() or original.suffix != ".sqlite3":
            raise MemoryContractError("请使用独立的本地 *.sqlite3 文件（仓库已忽略该后缀），不得使用符号链接")
        self.path = original.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._inspect_existing()
            self.connection = sqlite3.connect(self.path)
        else:
            # Never claim or initialize a pre-existing empty/production database.
            try:
                with self.path.open("xb"):
                    pass
            except FileExistsError as exc:
                raise MemoryContractError("数据库在初始化前已出现，请重新检查独立文件") from exc
            self.connection = sqlite3.connect(self.path)
            self._create_schema()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")

    def _inspect_existing(self) -> None:
        try:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as connection:
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables != TABLES:
                    raise MemoryContractError("拒绝打开非家庭记忆原型数据库；不会迁移或修改生产数据库")
                marker = dict(connection.execute("SELECT key, value FROM hm_meta"))
                application = connection.execute("PRAGMA application_id").fetchone()[0]
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if marker != {"component": COMPONENT, "schema_version": str(SCHEMA_VERSION)} or application != APPLICATION_ID or version != SCHEMA_VERSION:
                    raise MemoryContractError("家庭记忆数据库标志或版本不匹配")
        except sqlite3.Error as exc:
            raise MemoryContractError("无法只读验证家庭记忆数据库；原文件未初始化或覆盖") from exc

    def _create_schema(self) -> None:
        self.connection.executescript(f"""
            PRAGMA application_id={APPLICATION_ID};
            PRAGMA user_version={SCHEMA_VERSION};
            CREATE TABLE hm_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE hm_objects (
                object_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                aliases_json TEXT NOT NULL, enrolled_at TEXT NOT NULL
            );
            CREATE TABLE hm_owner_events (
                event_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL REFERENCES hm_objects(object_id),
                location_id TEXT NOT NULL, location_name TEXT NOT NULL,
                reported_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
                source TEXT NOT NULL,
                source_kind TEXT NOT NULL CHECK(source_kind='owner_reported'),
                visual_confirmed INTEGER NOT NULL CHECK(visual_confirmed=0)
            );
            CREATE TRIGGER hm_no_event_update BEFORE UPDATE ON hm_owner_events
                BEGIN SELECT RAISE(ABORT, 'owner events are immutable'); END;
            CREATE TRIGGER hm_no_event_delete BEFORE DELETE ON hm_owner_events
                BEGIN SELECT RAISE(ABORT, 'owner events are immutable'); END;
        """)
        self.connection.executemany("INSERT INTO hm_meta VALUES (?, ?)",
                                    [("component", COMPONENT), ("schema_version", str(SCHEMA_VERSION))])
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _object(row) -> dict:
        return {"object_id": row["object_id"], "name": row["name"],
                "aliases": json.loads(row["aliases_json"]), "enrolled_at": row["enrolled_at"],
                "visual_registration": "NOT_REGISTERED"}

    def enroll(self, object_id: str, name: str, aliases: list[str] | None = None) -> dict:
        object_id, name = _identifier(object_id, "object_id"), _text(name, "name")
        aliases = [] if aliases is None else aliases
        if not isinstance(aliases, list) or len(aliases) > 20:
            raise MemoryContractError("aliases 必须是最多 20 项的列表")
        aliases = [_text(a, "alias") for a in aliases]
        if len({_normalized(a) for a in [name, *aliases]}) != len(aliases) + 1:
            raise MemoryContractError("名称和别名不得重复")
        previous = self.connection.execute("SELECT * FROM hm_objects WHERE object_id=?", (object_id,)).fetchone()
        if previous:
            if previous["name"] != name or json.loads(previous["aliases_json"]) != aliases:
                raise MemoryContractError("既有 object_id 的登记不可覆盖；不要将它重新绑定到另一件物品")
            return {**self._object(previous), "created": False}
        with (nullcontext() if self.connection.in_transaction else self.connection):
            self.connection.execute("INSERT INTO hm_objects VALUES (?, ?, ?, ?)",
                                    (object_id, name, json.dumps(aliases, ensure_ascii=False), _utc_now()))
        return {**self._object(self.connection.execute("SELECT * FROM hm_objects WHERE object_id=?", (object_id,)).fetchone()), "created": True}

    def catalog(self) -> list[dict]:
        return [self._object(row) for row in self.connection.execute("SELECT * FROM hm_objects ORDER BY object_id")]

    def resolve(self, query: str) -> dict:
        query = _text(query, "query")
        objects = self.catalog()
        exact = [obj for obj in objects if obj["object_id"] == query]
        matches = exact or [obj for obj in objects if any(_normalized(query) == _normalized(label) for label in [obj["name"], *obj["aliases"]])]
        status = "RESOLVED" if len(matches) == 1 else "CLARIFY" if matches else "UNKNOWN_OBJECT"
        messages = {"RESOLVED": "已解析登记物品；尚无视觉身份确认", "CLARIFY": "存在同名物品，请明确指定 object_id", "UNKNOWN_OBJECT": "该物品尚未登记"}
        return {"status": status, "matches": matches, "message": messages[status]}

    def _require_object(self, object_id: str) -> None:
        _identifier(object_id, "object_id")
        if not self.connection.execute("SELECT 1 FROM hm_objects WHERE object_id=?", (object_id,)).fetchone():
            raise MemoryContractError("物品尚未登记；请先 enroll")

    @staticmethod
    def _event(row) -> dict:
        event = dict(row)
        event["visual_confirmed"] = False
        event["reported_at_basis"] = "owner_declared"
        # Preserve the old CLI contract, while making the UI's default clock
        # source explicit without migrating either memory schema.
        prefix = "local_workspace_explicit_owner_confirmation:"
        if event["source"].startswith(prefix):
            basis = event["source"][len(prefix):]
            if basis in ("session_creation_time", "owner_supplied_timestamp"):
                event["reported_at_basis"] = basis
        # These workflows save their local confirmation time, not a time the
        # owner supplied or the photograph was captured. Chat review IDs use
        # UUID hex, like photo run IDs; the associated private review records
        # the owner's explicit statement. This describes provenance, not proof
        # of an object's current location or identity. Unknown CLI sources keep
        # their legacy semantics, and stored events/timestamps remain unchanged.
        local_confirmation = (
            r"(?:photo_workspace_owner_statement|owner_chat_confirmation):"
            r"[0-9a-f]{32}:local_system_clock"
            r"|(?:photo_candidate_owner_review|visual_advisor_owner_review):"
            r"[0-9a-f]{32}:[0-9a-f]{64}"
        )
        if re.fullmatch(local_confirmation, event["source"]):
            event["reported_at_basis"] = "local_system_clock"
        event["recorded_at_basis"] = "local_system_clock"
        return event

    def remember(self, *, event_id: str, object_id: str, location_id: str,
                 location_name: str, reported_at: str, source: str) -> dict:
        self._require_object(object_id)
        event_id, location_id = _identifier(event_id, "event_id"), _identifier(location_id, "location_id")
        location_name, source = _text(location_name, "location_name"), _text(source, "source", 300)
        _time(reported_at)
        values = (event_id, object_id, location_id, location_name, reported_at, source)
        previous = self.connection.execute("SELECT * FROM hm_owner_events WHERE event_id=?", (event_id,)).fetchone()
        if previous:
            if tuple(previous[key] for key in ("event_id", "object_id", "location_id", "location_name", "reported_at", "source")) != values:
                raise MemoryContractError("旧事件不可覆盖；新陈述必须使用新的 event_id")
            return {**self._event(previous), "created": False}
        if self.connection.execute("SELECT 1 FROM hm_owner_events WHERE location_id=? AND location_name<>? LIMIT 1", (location_id, location_name)).fetchone():
            raise MemoryContractError("同一 location_id 的地点名称不一致")
        with (nullcontext() if self.connection.in_transaction else self.connection):
            self.connection.execute("INSERT INTO hm_owner_events VALUES (?, ?, ?, ?, ?, ?, ?, 'owner_reported', 0)",
                                    (*values[:5], _utc_now(), source))
        return {**self._event(self.connection.execute("SELECT * FROM hm_owner_events WHERE event_id=?", (event_id,)).fetchone()), "created": True}

    def history(self, object_id: str) -> list[dict]:
        self._require_object(object_id)
        events = [self._event(row) for row in self.connection.execute("SELECT * FROM hm_owner_events WHERE object_id=?", (object_id,))]
        return sorted(events, key=lambda event: (_time(event["reported_at"]), event["event_id"]), reverse=True)

    def candidates(self, object_id: str) -> list[dict]:
        locations = {}
        for event in self.history(object_id):
            key = event["location_id"]
            if key not in locations:
                locations[key] = {"location_id": key, "location_name": event["location_name"],
                                  "latest_reported_at": event["reported_at"], "source_kind": "owner_reported",
                                  "visual_confirmed": False, "reason": "latest_owner_reported_location",
                                  "event_ids": [], "report_count": 0}
            locations[key]["event_ids"].append(event["event_id"])
            locations[key]["report_count"] += 1
        return [{"rank": index, **location} for index, location in enumerate(locations.values(), 1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔离家庭记忆 CLI：仅记录主人陈述，不执行视觉识别或机器人动作。")
    parser.add_argument("--db", required=True, help="独立本地 *.sqlite3；仓库内此后缀受 Git 忽略")
    commands = parser.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("enroll", help="登记稳定 ID、名称及别名，不代表外观已学会")
    enroll.add_argument("--object-id", required=True)
    enroll.add_argument("--name", required=True)
    enroll.add_argument("--alias", action="append", default=[])
    commands.add_parser("catalog", help="列出物品档案")
    resolve = commands.add_parser("resolve", help="精确解析 ID/名称/别名；同名返回 CLARIFY")
    resolve.add_argument("--query", required=True)
    remember = commands.add_parser("remember", help="保存有来源的主人位置陈述")
    for argument in ("event-id", "object-id", "location-id", "location-name", "reported-at", "source"):
        remember.add_argument("--" + argument, required=True)
    for command in ("history", "candidates"):
        commands.add_parser(command).add_argument("--object-id", required=True)
    args = parser.parse_args(argv)
    try:
        with HouseholdMemory(args.db) as memory:
            if args.command == "enroll":
                data, message = memory.enroll(args.object_id, args.name, args.alias), "已登记物品档案；尚未登记图像或确认外观"
            elif args.command == "catalog":
                data, message = memory.catalog(), "物品档案目录"
            elif args.command == "resolve":
                data = memory.resolve(args.query)
                message = data["message"]
            elif args.command == "remember":
                data = memory.remember(**{key: getattr(args, key) for key in ("event_id", "object_id", "location_id", "location_name", "reported_at", "source")})
                message = "好的，我已记录你说的位置；尚未通过当前图像确认"
            elif args.command == "history":
                data, message = memory.history(args.object_id), "主人陈述的历史记录；不代表当前位置"
            else:
                data, message = memory.candidates(args.object_id), "按最近主人陈述排序的候选地点；尚未观察或确认"
        result = {"status": "OK", "command": args.command, "message": message, "data": data,
                  "scope": "isolated_owner_memory_prototype", "visual_confirmed": False}
    except (MemoryContractError, sqlite3.Error, OSError) as exc:
        # No database path, private file contents or arbitrary SQLite text in errors.
        result = {"status": "ERROR", "message": str(exc) if isinstance(exc, MemoryContractError) else "本地数据库操作失败，请检查独立文件及访问权限", "error_type": type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
