"""Software fixtures for owner memory; never household recognition evidence."""

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tools.household_memory import HouseholdMemory, MemoryContractError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "household_memory.py"


def statement(**changes):
    return {"event_id": "statement-01", "object_id": "keys-blue", "location_id": "entry-tray",
            "location_name": "玄关托盘", "reported_at": "2026-10-27T09:00:00+08:00",
            "source": "software_test_manual_statement", **changes}


@pytest.fixture
def memory(tmp_path):
    with HouseholdMemory(tmp_path / "household.sqlite3") as memory:
        memory.enroll("keys-blue", "蓝色钥匙", ["我的钥匙"])
        yield memory


def test_enrollment_has_no_visual_registration_and_is_stable(memory):
    original = memory.catalog()[0]
    duplicate = memory.enroll("keys-blue", "蓝色钥匙", ["我的钥匙"])
    assert duplicate["created"] is False
    assert duplicate["enrolled_at"] == original["enrolled_at"]
    assert duplicate["visual_registration"] == "NOT_REGISTERED"
    with pytest.raises(MemoryContractError, match="不可覆盖"):
        memory.enroll("keys-blue", "另一个物品")
    assert memory.catalog() == [original]


def test_same_name_requires_disambiguation_but_id_resolves(memory):
    memory.enroll("keys-red", "红色钥匙", ["我的钥匙"])
    assert memory.resolve("我的钥匙")["status"] == "CLARIFY"
    assert len(memory.resolve("我的钥匙")["matches"]) == 2
    assert memory.resolve("keys-blue")["matches"][0]["object_id"] == "keys-blue"
    assert memory.resolve("耳机")["status"] == "UNKNOWN_OBJECT"


def test_alias_normalization_and_invalid_duplicate_alias(memory):
    memory.enroll("cup-a", "SONY Mug", ["水杯"])
    assert memory.resolve("ｓｏｎｙ ｍｕｇ")["status"] == "RESOLVED"
    with pytest.raises(MemoryContractError, match="重复"):
        memory.enroll("cup-b", "Cup", ["cup"])


@pytest.mark.parametrize("value", ["", "bad", "2026-10-27", "2026-10-27T09:00:00", "2026-02-30T09:00:00+08:00"])
def test_declared_time_requires_valid_date_and_timezone(memory, value):
    with pytest.raises(MemoryContractError, match="时区"):
        memory.remember(**statement(reported_at=value))
    assert memory.history("keys-blue") == []


def test_statement_keeps_provenance_and_is_immutable(memory):
    event = memory.remember(**statement())
    assert event["source_kind"] == "owner_reported"
    assert event["visual_confirmed"] is False
    assert event["reported_at_basis"] == "owner_declared"
    assert event["recorded_at_basis"] == "local_system_clock"
    assert event["source"] == "software_test_manual_statement"
    duplicate = memory.remember(**statement())
    assert duplicate["created"] is False
    assert duplicate["recorded_at"] == event["recorded_at"]
    with pytest.raises(MemoryContractError, match="旧事件不可覆盖"):
        memory.remember(**statement(location_name="书桌"))
    assert len(memory.history("keys-blue")) == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        memory.connection.execute("UPDATE hm_owner_events SET location_name='changed'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        memory.connection.execute("DELETE FROM hm_owner_events")


@pytest.mark.parametrize("source", [
    f"photo_workspace_owner_statement:{'a' * 32}:local_system_clock",
    f"photo_candidate_owner_review:{'a' * 32}:{'b' * 64}",
    f"visual_advisor_owner_review:{'a' * 32}:{'b' * 64}",
    f"owner_chat_confirmation:{'a' * 32}:local_system_clock",
])
def test_local_confirmation_time_semantics_survive_reopen_without_rewriting_event(tmp_path, source):
    database = tmp_path / "household.sqlite3"
    with HouseholdMemory(database) as memory:
        memory.enroll("keys-blue", "蓝色钥匙")
        event = memory.remember(**statement(source=source))
        assert event["reported_at_basis"] == "local_system_clock"
        assert event["source_kind"] == "owner_reported"
        assert event["visual_confirmed"] is False
        assert event["source"] == source
        assert event["reported_at"] == statement()["reported_at"]
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    with HouseholdMemory(database) as reopened:
        recalled = reopened.history("keys-blue")
        assert recalled == [{key: value for key, value in event.items() if key != "created"}]
        stored = reopened.connection.execute(
            "SELECT source, reported_at FROM hm_owner_events WHERE event_id=?", (event["event_id"],)
        ).fetchone()
        assert tuple(stored) == (source, statement()["reported_at"])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("source", [
    "owner_chat_confirmation:review-name:local_system_clock",
    f"owner_chat_confirmation:{'a' * 31}:local_system_clock",
    f"owner_chat_confirmation:{'A' * 32}:local_system_clock",
    f"owner_chat_confirmation:{'a' * 32}:owner_declared",
    f"owner_chat_confirmation:{'a' * 32}:local_system_clock:extra",
    f"photo_workspace_owner_statement:{'a' * 32}:unknown_clock",
    "photo_workspace_owner_statement::local_system_clock",
    f"photo_candidate_owner_review:{'a' * 32}:{'b' * 63}",
    f"photo_candidate_owner_review:{'a' * 31}:{'b' * 64}",
    f"visual_advisor_owner_review:{'a' * 32}:{'g' * 64}",
    f"visual_advisor_owner_review:{'a' * 32}:{'b' * 64}:extra",
    f"unknown_owner_review:{'a' * 32}:{'b' * 64}",
    "local_workspace_explicit_owner_confirmation:unknown_basis",
])
def test_unrecognized_or_malformed_source_preserves_legacy_time_semantics(memory, source):
    event = memory.remember(**statement(source=source))
    assert event["reported_at_basis"] == "owner_declared"
    assert event["source"] == source
    assert memory.history("keys-blue")[0]["reported_at_basis"] == "owner_declared"


@pytest.mark.parametrize("basis", ["session_creation_time", "owner_supplied_timestamp"])
def test_existing_explicit_owner_confirmation_time_semantics_are_preserved(memory, basis):
    event = memory.remember(**statement(source="local_workspace_explicit_owner_confirmation:" + basis))
    assert event["reported_at_basis"] == basis
    assert event["reported_at"] == statement()["reported_at"]


def test_history_uses_absolute_declared_time_not_insert_order(memory):
    memory.remember(**statement())  # 01:00 UTC
    memory.remember(**statement(event_id="statement-02", reported_at="2026-10-27T02:00:00Z"))
    memory.remember(**statement(event_id="statement-03", reported_at="2026-10-27T08:30:00+08:00"))
    assert [e["event_id"] for e in memory.history("keys-blue")] == ["statement-02", "statement-01", "statement-03"]


def test_candidates_are_owner_reports_not_current_visual_facts(memory):
    memory.remember(**statement())
    memory.remember(**statement(event_id="statement-02", location_id="desk", location_name="书桌", reported_at="2026-10-27T12:00:00+08:00"))
    memory.remember(**statement(event_id="statement-03", reported_at="2026-10-27T08:00:00+08:00"))
    candidates = memory.candidates("keys-blue")
    assert [c["location_id"] for c in candidates] == ["desk", "entry-tray"]
    assert [c["report_count"] for c in candidates] == [1, 2]
    assert candidates[1]["event_ids"] == ["statement-01", "statement-03"]
    assert all(c["source_kind"] == "owner_reported" and not c["visual_confirmed"] for c in candidates)
    assert "FOUND" not in json.dumps(candidates)


def test_objects_have_separate_histories(memory):
    memory.enroll("cup-a", "水杯")
    memory.remember(**statement())
    assert memory.history("cup-a") == []
    assert memory.candidates("cup-a") == []
    with pytest.raises(MemoryContractError, match="尚未登记"):
        memory.remember(**statement(object_id="unknown-object"))


def test_location_id_cannot_silently_change_meaning(memory):
    memory.remember(**statement())
    with pytest.raises(MemoryContractError, match="地点名称不一致"):
        memory.remember(**statement(event_id="statement-02", location_name="浴室"))


@pytest.mark.parametrize("kind", ["production", "empty", "invalid", "wrong-marker"])
def test_foreign_database_is_rejected_without_changing_bytes(tmp_path, kind):
    path = tmp_path / "existing.sqlite3"
    if kind == "production":
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE objects (object_id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO objects VALUES ('production-object')")
    elif kind == "wrong-marker":
        with HouseholdMemory(path):
            pass
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE hm_meta SET value='foreign' WHERE key='component'")
    else:
        path.write_bytes(b"" if kind == "empty" else b"private invalid sqlite input")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(MemoryContractError):
        HouseholdMemory(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_database_suffix_is_ignored_and_nonprivate_suffix_rejected(tmp_path):
    result = subprocess.run(["git", "check-ignore", "--quiet", "artifacts/household-memory/home.sqlite3"], cwd=ROOT)
    assert result.returncode == 0
    with pytest.raises(MemoryContractError, match="sqlite3"):
        HouseholdMemory(tmp_path / "public.json")
    assert not (tmp_path / "public.json").exists()


def _cli(database, *arguments):
    result = subprocess.run([sys.executable, str(SCRIPT), "--db", str(database), *arguments],
                            capture_output=True, encoding="utf-8", cwd=ROOT)
    return result.returncode, json.loads(result.stdout)


def test_cli_persists_across_separate_processes(tmp_path):
    database = tmp_path / "household.sqlite3"
    code, enrolled = _cli(database, "enroll", "--object-id", "keys-blue", "--name", "蓝色钥匙", "--alias", "我的钥匙")
    assert code == 0 and enrolled["data"]["created"]
    arguments = ["remember"]
    for key, value in statement().items():
        arguments.extend(["--" + key.replace("_", "-"), value])
    code, remembered = _cli(database, *arguments)
    assert code == 0 and "尚未通过当前图像确认" in remembered["message"]
    code, history = _cli(database, "history", "--object-id", "keys-blue")
    assert code == 0 and len(history["data"]) == 1
    assert history["data"][0]["event_id"] == "statement-01"
    code, candidate = _cli(database, "candidates", "--object-id", "keys-blue")
    assert code == 0 and candidate["data"][0]["location_name"] == "玄关托盘"
    assert candidate["visual_confirmed"] is False
    code, resolved = _cli(database, "resolve", "--query", "我的钥匙")
    assert code == 0 and resolved["data"]["status"] == "RESOLVED"


def test_cli_invalid_event_is_json_error_without_private_path(tmp_path):
    database = tmp_path / "private-household.sqlite3"
    code, error = _cli(database, "history", "--object-id", "unknown")
    assert code == 2 and error["status"] == "ERROR"
    assert str(database) not in json.dumps(error)
