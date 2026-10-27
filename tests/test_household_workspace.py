"""Persistent conversation contracts; software fixtures, not recognition evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import sqlite3

import pytest

from hometrace.household_service import HouseholdConflict, HouseholdService


DECLARED_TIME = "2026-10-27T10:00:00+08:00"


@pytest.fixture
def service(tmp_path):
    service = HouseholdService(tmp_path / "private-household")
    service.enroll("blue-keys", "蓝色钥匙", ["我的钥匙"])
    return service


def remember(service, query="我的钥匙", location_id="entry-tray", reported_at=DECLARED_TIME):
    return service.start("remember", query, location_id=location_id, reported_at=reported_at)


def action(service, session, name, **fields):
    return service.act(session["session_id"], session["version"], name, **fields)


def history(service, query="blue-keys"):
    session = service.start("recall", query)
    assert session["state"] == "COMPLETED"
    return session["history"]


def test_statement_requires_explicit_confirmation_and_preserves_provenance(service):
    pending = remember(service)
    assert pending["state"] == "CONFIRM"
    assert pending["selected_object"]["object_id"] == "blue-keys"
    assert history(service) == []

    saved = action(service, pending, "confirm")
    assert saved["state"] == "COMPLETED"
    assert saved["version"] > pending["version"]
    assert saved["visual_confirmed"] is False
    events = history(service)
    assert len(events) == 1
    assert events[0]["object_id"] == "blue-keys"
    assert events[0]["location_id"] == "entry-tray"
    assert events[0]["reported_at"] == DECLARED_TIME
    assert events[0]["reported_at_basis"] == "owner_supplied_timestamp"
    assert events[0]["source_kind"] == "owner_reported"
    assert events[0]["visual_confirmed"] is False
    assert saved["messages"]
    assert all(set(message) >= {"role", "text"} for message in saved["messages"])
    assert "FOUND" not in json.dumps(saved, ensure_ascii=False)


def test_pending_conversation_and_memory_survive_service_restart(tmp_path):
    workspace = tmp_path / "persistent-home"
    first = HouseholdService(workspace)
    first.enroll("blue-keys", "蓝色钥匙", ["我的钥匙"])
    pending = remember(first)
    resumed = HouseholdService(workspace)
    assert resumed.get(pending["session_id"]) == pending
    saved = action(resumed, pending, "confirm")
    restarted = HouseholdService(workspace)
    assert restarted.get(saved["session_id"]) == saved
    assert len(history(restarted)) == 1


def test_clarification_retains_intent_and_cannot_select_unoffered_object(service):
    service.enroll("red-keys", "红色钥匙", ["我的钥匙"])
    service.enroll("sony-cup", "SONY 水杯", ["水杯"])
    pending = remember(service)
    assert pending["state"] == "CLARIFY"
    assert {obj["object_id"] for obj in pending["matches"]} == {"blue-keys", "red-keys"}
    with pytest.raises(ValueError):
        action(service, pending, "select", object_id="sony-cup")
    assert service.get(pending["session_id"]) == pending

    selected = action(service, pending, "select", object_id="red-keys")
    assert selected["state"] == "CONFIRM"
    assert selected["intent"] == "remember"
    assert selected["selected_object"]["object_id"] == "red-keys"
    assert history(service, "red-keys") == []
    action(service, selected, "confirm")
    assert len(history(service, "red-keys")) == 1
    assert history(service, "blue-keys") == []


def test_recall_clarification_returns_selected_history_without_creating_event(service):
    action(service, remember(service), "confirm")
    service.enroll("red-keys", "红色钥匙", ["我的钥匙"])
    pending = service.start("recall", "我的钥匙")
    assert pending["state"] == "CLARIFY"
    resolved = action(service, pending, "select", object_id="blue-keys")
    assert resolved["state"] == "COMPLETED"
    assert len(resolved["history"]) == 1
    assert len(history(service)) == 1


def test_unknown_target_can_resume_after_explicit_registration(service):
    pending = remember(service, query="我的耳机")
    assert pending["state"] == "UNKNOWN_OBJECT"
    service.enroll("earbuds", "耳机盒", ["我的耳机"])
    resumed = action(service, pending, "retry")
    assert resumed["session_id"] == pending["session_id"]
    assert resumed["state"] == "CONFIRM"
    assert resumed["selected_object"]["object_id"] == "earbuds"
    assert history(service, "earbuds") == []
    action(service, resumed, "confirm")
    assert len(history(service, "earbuds")) == 1


def test_cancel_does_not_write_a_location_event(service):
    pending = remember(service)
    cancelled = action(service, pending, "cancel")
    assert cancelled["state"] == "CANCELLED"
    assert history(service) == []
    with pytest.raises(ValueError):
        action(service, cancelled, "confirm")
    assert history(service) == []


def test_confirm_is_idempotent_at_current_version_and_stale_actions_conflict(service):
    pending = remember(service)
    saved = action(service, pending, "confirm")
    duplicate = action(service, saved, "confirm")
    assert duplicate == saved
    with pytest.raises(HouseholdConflict):
        action(service, pending, "confirm")
    assert len(history(service)) == 1


def test_two_service_instances_cannot_confirm_same_version_twice(tmp_path):
    workspace = tmp_path / "concurrent-home"
    first = HouseholdService(workspace)
    first.enroll("blue-keys", "蓝色钥匙", ["我的钥匙"])
    pending = remember(first)
    second = HouseholdService(workspace)

    def confirm(instance):
        try:
            return action(instance, pending, "confirm")["state"]
        except HouseholdConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, (first, second)))
    assert sorted(results) == ["COMPLETED", "CONFLICT"]
    assert len(history(HouseholdService(workspace))) == 1


def test_recall_orders_absolute_time_and_exposes_only_reported_candidates(service):
    action(service, remember(service, reported_at="2026-10-27T09:00:00+08:00"), "confirm")
    action(service, remember(service, location_id="study-desk", reported_at="2026-10-27T02:00:00Z"), "confirm")
    result = service.start("recall", "我的钥匙")
    assert [event["location_id"] for event in result["history"]] == ["study-desk", "entry-tray"]
    assert [candidate["location_id"] for candidate in result["candidates"]] == ["study-desk", "entry-tray"]
    assert all(candidate["source_kind"] == "owner_reported" for candidate in result["candidates"])
    assert all(candidate["visual_confirmed"] is False for candidate in result["candidates"])
    assert result["visual_confirmed"] is False


def test_new_registered_object_has_no_location_or_visual_confirmation(service):
    service.enroll("phone", "手机", [])
    result = service.start("recall", "手机")
    assert result["state"] == "COMPLETED"
    assert result["history"] == [] and result["candidates"] == []
    assert result["visual_confirmed"] is False
    assert result["selected_object"]["visual_registration"] == "NOT_REGISTERED"


@pytest.mark.parametrize("reported_at", ["2026-10-27", "2026-10-27T10:00:00", "not-a-date", "2026-02-30T10:00:00Z"])
def test_invalid_declared_time_never_creates_memory(service, reported_at):
    with pytest.raises(ValueError):
        remember(service, reported_at=reported_at)
    assert history(service) == []


@pytest.mark.parametrize("location_id", [None, "unknown-room", "../../private"])
def test_remember_requires_a_supported_explicit_location(service, location_id):
    with pytest.raises(ValueError):
        remember(service, location_id=location_id)
    assert history(service) == []


@pytest.mark.parametrize("intent", ["find", "FOUND", "", None])
def test_unsupported_intent_does_not_run_a_search(service, intent):
    with pytest.raises(ValueError):
        service.start(intent, "我的钥匙", location_id="entry-tray")


def test_generated_time_is_timezone_aware_and_stable_during_confirmation(service):
    pending = service.start("remember", "我的钥匙", location_id="entry-tray")
    assert datetime.fromisoformat(pending["reported_at"]).utcoffset() is not None
    saved = action(service, pending, "confirm")
    assert saved["reported_at"] == pending["reported_at"]
    assert history(service)[0]["reported_at"] == pending["reported_at"]
    assert history(service)[0]["reported_at_basis"] == "session_creation_time"


@pytest.mark.parametrize("session_id", ["0" * 32, "../private", "not-a-session"])
def test_unknown_or_malformed_session_cannot_read_other_files(service, session_id):
    with pytest.raises((KeyError, ValueError)):
        service.get(session_id)


def test_public_views_do_not_disclose_workspace_path(service, tmp_path):
    session = remember(service)
    serialized = json.dumps([service.config(), session, service.get(session["session_id"])], ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "HOMETRACE_LLM_API_KEY" not in serialized


def test_session_write_failure_rolls_back_the_location_event(service):
    """Fail after the event INSERT, at the actual session UPDATE boundary."""
    pending = remember(service)
    with sqlite3.connect(service.sessions_path) as db:
        db.execute("""CREATE TRIGGER fail_session_update BEFORE UPDATE ON household_sessions
                      BEGIN SELECT RAISE(ABORT, 'injected disk write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected disk write failure"):
        action(service, pending, "confirm")
    restarted = HouseholdService(service.workspace)
    assert restarted.get(pending["session_id"]) == pending
    assert history(restarted) == []
    with sqlite3.connect(service.sessions_path) as db:
        db.execute("DROP TRIGGER fail_session_update")
    action(restarted, pending, "confirm")
    assert len(history(restarted)) == 1


@pytest.mark.parametrize("database", ["memory_path", "sessions_path"])
def test_external_wal_mode_is_rejected_before_confirming(service, database):
    pending = remember(service)
    db = sqlite3.connect(getattr(service, database))
    try:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        with pytest.raises(ValueError, match="日志模式"):
            action(service, pending, "confirm")
        assert service.get(pending["session_id"]) == pending
        assert history(service) == []
    finally:
        db.close()


def test_two_services_enrolling_same_id_cannot_rebind_it(service):
    second = HouseholdService(service.workspace)

    def enroll(args):
        instance, name = args
        try:
            return instance.enroll("new-object", name, [])["object"]["name"]
        except ValueError:
            return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(enroll, ((service, "物品甲"), (second, "物品乙"))))
    assert results.count("REJECTED") == 1
    objects = [obj for obj in service.config()["catalog"] if obj["object_id"] == "new-object"]
    assert len(objects) == 1
    assert objects[0]["name"] in results
