"""Persistent photo-flow software checks; only one test uses public ORB photos.

ScriptedEngine is an explicitly injected software double, not neural/household
recognition evidence. Upload decoding, SearchCore, SQLite and replay checks are
real in all tests. Every workspace and generated fixture stays under tmp_path.
"""

import base64
from contextlib import closing
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from hometrace.household_memory import HouseholdMemory
from hometrace.household_service import HouseholdConflict, HouseholdService
from hometrace.photo_flow_service import PhotoFlowService
import hometrace.photo_flow_service as photo_module


class ScriptedEngine:
    """Factory shared by a test to count actual detector-boundary invocations."""

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []
        self.quality_calls = 0

    def __call__(self, root, reference, scenes, object_id):
        factory = self

        class Instance:
            def quality(self):
                factory.quality_calls += 1
                return {"reference_accepted": True, "software_test_double": True,
                        "training_steps": 0, "identity_confirmed": False}

            def observe(self, location):
                factory.calls.append((location, deepcopy(scenes.get(location))))
                candidate = factory.outcomes.get(location) == "candidate"
                return {
                    "appearance_candidate": candidate,
                    "bbox": [8, 8, 48, 48] if candidate else None,
                    "matcher": "scripted_software_test_double",
                    "diagnostics": {"image_decoded": True, "reason": "test_candidate" if candidate else "test_no_match"},
                    "reason": "test_candidate" if candidate else "test_no_match",
                    "duration_ms": 0.0, "raw_match_status": "FOUND" if candidate else "UNKNOWN",
                }

        return Instance()


def fixture_bytes(seed=1, width=64, height=64):
    image = np.random.default_rng(seed).integers(0, 256, (height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode('.png', image)
    assert ok
    return encoded.tobytes()


def upload(service, seed=1, source="synthetic"):
    return service.upload(base64.b64encode(fixture_bytes(seed)).decode(), source)


def create_service(tmp_path, outcomes=None):
    household = HouseholdService(tmp_path / 'home')
    engine = ScriptedEngine(outcomes)
    return household, PhotoFlowService(household, engine_factory=engine, use_graph=False), engine


def register(household, service, object_id="keys-a", name="蓝钥匙", aliases=None, seed=1, source="synthetic"):
    household.enroll(object_id, name, aliases if aliases is not None else ["钥匙"])
    asset = upload(service, seed, source)
    service.reference(object_id, asset['asset_id'], [0, 0, 64, 64], True)
    return asset


def history(household, object_id="keys-a"):
    with HouseholdMemory(household.memory_path) as memory:
        return memory.history(object_id)


def remember(household, location, at, event_id, object_id="keys-a"):
    from hometrace.household_service import LOCATIONS
    name = next(row['location_name'] for row in LOCATIONS if row['location_id'] == location)
    with HouseholdMemory(household.memory_path) as memory:
        memory.remember(event_id=event_id, object_id=object_id, location_id=location,
                        location_name=name, reported_at=at, source="explicit_software_test_owner_statement")


def evidence_count(service):
    with closing(sqlite3.connect(service.path)) as db:
        return db.execute('SELECT count(*) FROM evidence').fetchone()[0]


def test_upload_decodes_and_preserves_original_bytes_and_source(tmp_path):
    _, service, _ = create_service(tmp_path)
    data = fixture_bytes()
    asset = service.upload(base64.b64encode(data).decode(), "synthetic")
    assert asset['sha256'] == hashlib.sha256(data).hexdigest()
    assert asset['width'] == asset['height'] == 64
    assert asset['capture_time'] == 'unknown' and 'path' not in asset
    assert service.asset(asset['asset_id']) == (data, 'image/png')
    assert service.upload(base64.b64encode(data).decode(), "synthetic") == asset
    with pytest.raises(ValueError, match='来源声明不可改写'):
        service.upload(base64.b64encode(data).decode(), "real_upload")
    with closing(sqlite3.connect(service.path)) as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 1


@pytest.mark.parametrize('encoded,source', [('', 'synthetic'), ('@@@', 'synthetic'),
    (base64.b64encode(b'<svg/>').decode(), 'synthetic'), ('AAAA', 'camera_verified'),
    (None, 'synthetic')])
def test_invalid_upload_never_creates_an_asset(tmp_path, encoded, source):
    _, service, _ = create_service(tmp_path)
    with pytest.raises(ValueError):
        service.upload(encoded, source)
    assert list(service.assets_dir.iterdir()) == []
    with closing(sqlite3.connect(service.path)) as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 0


def test_upload_dimensions_and_byte_limit_are_enforced(tmp_path, monkeypatch):
    _, service, _ = create_service(tmp_path)
    with pytest.raises(ValueError, match='边长'):
        service.upload(base64.b64encode(fixture_bytes(width=31)).decode(), 'synthetic')
    monkeypatch.setattr(photo_module, 'MAX_BYTES', 32)
    with pytest.raises(ValueError, match='8 MB'):
        upload(service)
    assert list(service.assets_dir.iterdir()) == []


def test_reference_requires_review_and_is_immutable_after_quality_check(tmp_path):
    household, service, engine = create_service(tmp_path)
    household.enroll('keys-a', '蓝钥匙', ['钥匙'])
    asset = upload(service)
    with pytest.raises(ValueError, match='人工确认'):
        service.reference('keys-a', asset['asset_id'], [0, 0, 64, 64], False)
    with pytest.raises(ValueError):
        service.reference('keys-a', asset['asset_id'], [0, 0, 100, 100], True)
    original = service.reference('keys-a', asset['asset_id'], [0, 0, 64, 64], True)
    assert original['roi_reviewed'] is True and original['review_source'] == 'local_operator_confirmation'
    assert service.reference('keys-a', asset['asset_id'], [0, 0, 64, 64], True) == original
    replacement = upload(service, 2)
    with pytest.raises(HouseholdConflict):
        service.reference('keys-a', replacement['asset_id'], [0, 0, 64, 64], True)
    with pytest.raises(HouseholdConflict):
        service.reference('keys-a', asset['asset_id'], [0, 0, 32, 32], True)
    assert engine.quality_calls == 1
    assert service.config()['catalog'][0]['reference']['asset_id'] == asset['asset_id']


def test_recent_owner_history_changes_search_order_without_visual_confirmation(tmp_path):
    household, service, engine = create_service(tmp_path, {'study-desk': 'candidate'})
    register(household, service)
    remember(household, 'entry-tray', '2026-10-27T09:00:00+08:00', 'old')
    remember(household, 'study-desk', '2026-10-27T10:00:00+08:00', 'recent')
    asset = upload(service, 2)
    service.scene('study-desk', asset['asset_id'])
    run = service.wait(service.start('帮我找蓝钥匙')['run_id'])
    assert run['state'] == 'AWAITING_REVIEW'
    assert run['planned_locations'][0]['location_id'] == run['visited'][0] == 'study-desk'
    assert run['planned_locations'][0]['reason'] == 'recent_owner_memory'
    assert [call[0] for call in engine.calls] == ['study-desk']
    assert run['candidate']['bbox'] == [8, 8, 48, 48]
    assert run['visual_confirmed'] is False and run['candidate']['identity_confirmed'] is False
    assert run['core_reports'][0]['result_status'] == 'SUSPECTED'
    assert run['core_reports'][0]['location'] is None
    assert run['core_reports'][0]['confirmed_evidence_ids'] == []
    assert len(history(household)) == 2 and evidence_count(service) == 1
    assert 'snapshot' not in run


def test_accept_after_restart_saves_owner_memory_once_and_preserves_automatic_result(tmp_path):
    household, service, engine = create_service(tmp_path, {'entry-tray': 'candidate'})
    register(household, service)
    asset = upload(service, 2)
    service.scene('entry-tray', asset['asset_id'])
    run = service.wait(service.start('帮我找蓝钥匙')['run_id'])
    restarted_household = HouseholdService(household.workspace)
    restarted = PhotoFlowService(restarted_household, engine_factory=engine, use_graph=False)
    assert restarted.get(run['run_id']) == run
    confirmed = restarted.act(run['run_id'], run['version'], 'accept_candidate')
    assert confirmed['state'] == 'USER_CONFIRMED' and confirmed['visual_confirmed'] is False
    assert confirmed['core_reports'] == run['core_reports']
    rows = history(restarted_household)
    assert len(rows) == 1 and rows[0]['location_id'] == 'entry-tray'
    assert rows[0]['source_kind'] == 'owner_reported' and rows[0]['visual_confirmed'] is False
    assert run['run_id'] in rows[0]['source'] and asset['sha256'] in rows[0]['source']
    with pytest.raises(HouseholdConflict):
        restarted.act(run['run_id'], run['version'], 'accept_candidate')
    with pytest.raises(ValueError):
        restarted.act(run['run_id'], confirmed['version'], 'accept_candidate')
    assert len(history(restarted_household)) == 1


def test_reject_replans_and_cancel_does_not_write_owner_location(tmp_path):
    household, service, engine = create_service(tmp_path, {'entry-tray': 'candidate', 'living-table': 'candidate'})
    register(household, service)
    for index, location in enumerate(('entry-tray', 'living-table'), 2):
        service.scene(location, upload(service, index)['asset_id'])
    first = service.wait(service.start('帮我找蓝钥匙')['run_id'])
    service.act(first['run_id'], first['version'], 'reject_candidate')
    second = service.wait(first['run_id'])
    assert second['state'] == 'AWAITING_REVIEW' and second['candidate']['location_id'] == 'living-table'
    assert second['visited'] == ['entry-tray', 'living-table']
    assert [call[0] for call in engine.calls] == second['visited']
    assert any(row['tool'] == 'owner_reject_candidate' for row in second['trace'])
    assert not history(household)
    cancelled = service.act(second['run_id'], second['version'], 'cancel')
    assert cancelled['state'] == 'CANCELLED' and cancelled['candidate'] is None
    assert not history(household) and evidence_count(service) == 2


def test_reference_and_previous_unknown_image_replay_never_calls_detector_again(tmp_path):
    household, service, engine = create_service(tmp_path)
    reference = register(household, service)
    scene = upload(service, 2)
    service.scene('entry-tray', reference['asset_id'])
    service.scene('living-table', scene['asset_id'])
    first = service.wait(service.start('帮我找蓝钥匙')['run_id'])
    assert first['state'] == 'UNKNOWN'
    assert first['observations'][0]['reason'] == 'replayed_image_content'
    assert [call[0] for call in engine.calls] == ['living-table']
    assert evidence_count(service) == 1
    restarted = PhotoFlowService(HouseholdService(household.workspace), engine_factory=engine, use_graph=False)
    second = restarted.wait(restarted.start('帮我找蓝钥匙')['run_id'])
    assert second['state'] == 'UNKNOWN'
    assert [row['reason'] for row in second['observations'][:2]] == ['replayed_image_content'] * 2
    assert [call[0] for call in engine.calls] == ['living-table']
    assert evidence_count(restarted) == 1 and not history(household)


@pytest.mark.parametrize('reference_source,scene_source', [('synthetic', 'real_upload'), ('real_upload', 'synthetic')])
def test_cross_source_scene_is_rejected_before_matching(tmp_path, reference_source, scene_source):
    household, service, engine = create_service(tmp_path, {'entry-tray': 'candidate'})
    register(household, service, source=reference_source)
    service.scene('entry-tray', upload(service, 2, scene_source)['asset_id'])
    run = service.wait(service.start('帮我找蓝钥匙')['run_id'])
    assert run['state'] == 'UNKNOWN' and not engine.calls
    assert run['observations'][0]['reason'] == 'unsupported_evidence_source'
    assert evidence_count(service) == 0 and not history(household)


def test_unknown_and_ambiguous_objects_require_explicit_resolution(tmp_path):
    household, service, _ = create_service(tmp_path)
    unknown = service.start('帮我找钥匙')
    assert unknown['state'] == 'UNKNOWN_OBJECT'
    register(household, service)
    household.enroll('keys-b', '红钥匙', ['钥匙'])
    ambiguous = service.act(unknown['run_id'], unknown['version'], 'retry')
    assert ambiguous['state'] == 'CLARIFY' and len(ambiguous['matches']) == 2
    with pytest.raises(ValueError, match='选择'):
        service.act(ambiguous['run_id'], ambiguous['version'], 'select', object_id='invented')
    selected = service.act(ambiguous['run_id'], ambiguous['version'], 'select', object_id='keys-b')
    assert selected['state'] == 'NEEDS_REFERENCE' and selected['selected_object']['object_id'] == 'keys-b'
    assert not history(household, 'keys-b')


def test_explicit_location_is_required_and_remember_waits_for_confirmation(tmp_path):
    household, service, _ = create_service(tmp_path)
    register(household, service)
    incomplete = service.start('记住蓝钥匙放在这里')
    assert incomplete['state'] == 'ERROR' and not history(household)
    pending = service.start('记住蓝钥匙放在这里', current_location_id='study-desk')
    assert pending['state'] == 'CONFIRM_MEMORY' and not history(household)
    confirmed = service.act(pending['run_id'], pending['version'], 'confirm_memory')
    assert confirmed['state'] == 'COMPLETED' and confirmed['visual_confirmed'] is False
    assert history(household)[0]['location_id'] == 'study-desk'
    recalled = service.start('查看蓝钥匙历史')
    assert recalled['state'] == 'COMPLETED' and len(recalled['history']) == 1
    assert recalled['observations'] == [] and evidence_count(service) == 0


def test_confirmation_rolls_back_owner_event_when_run_write_fails(tmp_path):
    household, service, _ = create_service(tmp_path)
    register(household, service)
    pending = service.start('记住蓝钥匙放在这里', current_location_id='entry-tray')
    with closing(sqlite3.connect(service.path)) as db, db:
        db.execute("CREATE TRIGGER fail_run_update BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT,'test interruption'); END")
    with pytest.raises(sqlite3.DatabaseError):
        service.act(pending['run_id'], pending['version'], 'confirm_memory')
    assert not history(household)
    assert service.get(pending['run_id']) == pending


@pytest.mark.parametrize('database', ['owner', 'photo'])
def test_confirmation_refuses_wal_when_atomic_attached_commit_is_not_guaranteed(tmp_path, database):
    household, service, _ = create_service(tmp_path)
    register(household, service)
    pending = service.start('记住蓝钥匙放在这里', current_location_id='entry-tray')
    path = household.memory_path if database == 'owner' else service.path
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    with pytest.raises(ValueError, match='WAL'):
        service.act(pending['run_id'], pending['version'], 'confirm_memory')
    assert not history(household) and service.get(pending['run_id']) == pending


def test_running_snapshot_survives_restart_and_ignores_later_scene_rebinding(tmp_path, monkeypatch):
    household, service, engine = create_service(tmp_path, {'entry-tray': 'candidate'})
    register(household, service)
    original = upload(service, 2)
    service.scene('entry-tray', original['asset_id'])
    monkeypatch.setattr(service, '_launch', lambda run_id: None)
    pending = service.start('帮我找蓝钥匙')
    assert pending['state'] == 'RUNNING'
    replacement = upload(service, 3)
    service.scene('entry-tray', replacement['asset_id'])
    restarted = PhotoFlowService(HouseholdService(household.workspace), engine_factory=engine, use_graph=False)
    restarted.act(pending['run_id'], pending['version'], 'retry')
    result = restarted.wait(pending['run_id'])
    assert result['state'] == 'AWAITING_REVIEW'
    assert result['candidate']['asset_id'] == original['asset_id']
    assert engine.calls[0][1]['asset_id'] == original['asset_id']
    assert restarted.config()['scenes'][0]['asset_id'] == replacement['asset_id']


def test_altered_candidate_bytes_cannot_be_confirmed(tmp_path):
    household, service, _ = create_service(tmp_path, {'entry-tray': 'candidate'})
    register(household, service)
    asset = upload(service, 2)
    service.scene('entry-tray', asset['asset_id'])
    run = service.wait(service.start('帮我找蓝钥匙')['run_id'])
    (service.assets_dir / f"{asset['asset_id']}.png").write_bytes(fixture_bytes(3))
    with pytest.raises(ValueError, match='校验失败'):
        service.act(run['run_id'], run['version'], 'accept_candidate')
    assert service.get(run['run_id']) == run and not history(household)


@pytest.mark.parametrize('message', ['不要帮我找蓝钥匙', '记住蓝钥匙然后帮我找蓝钥匙', '你好'])
def test_unsupported_or_negated_request_does_not_create_a_run(tmp_path, message):
    _, service, _ = create_service(tmp_path)
    with pytest.raises(ValueError):
        service.start(message)
    with closing(sqlite3.connect(service.path)) as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_public_opencv_reference_actually_runs_through_service_and_core(tmp_path):
    """Actual ORB regression on public photos; not AI or private-home evidence."""
    samples = Path(__file__).resolve().parents[1] / 'examples' / 'recorded_images'
    household = HouseholdService(tmp_path / 'home')
    service = PhotoFlowService(household, use_graph=False)
    household.enroll('public-box', '公开样例盒子', ['盒子'])
    reference = service.upload(base64.b64encode((samples / 'box.png').read_bytes()).decode(), 'real_upload')
    service.reference('public-box', reference['asset_id'], [0, 0, reference['width'], reference['height']], True)
    scene = service.upload(base64.b64encode((samples / 'box_in_scene.png').read_bytes()).decode(), 'real_upload')
    service.scene('study-desk', scene['asset_id'])
    remember(household, 'study-desk', '2026-10-27T09:00:00+08:00', 'public-history', 'public-box')
    result = service.wait(service.start('帮我找公开样例盒子')['run_id'])
    assert result['state'] == 'AWAITING_REVIEW'
    candidate = result['candidate']
    assert candidate['raw_match_status'] == 'FOUND' and candidate['status'] == 'SUSPECTED'
    assert candidate['diagnostics']['image_decoded'] is True
    assert candidate['diagnostics']['inliers'] >= 10 and len(candidate['bbox']) == 4
    assert result['core_reports'][0]['data_source'] == 'user_image'
    assert result['core_reports'][0]['confirmed_evidence_ids'] == []
    assert len(history(household, 'public-box')) == 1


def test_reject_during_worker_exit_resumes_and_waits_for_successor(tmp_path, monkeypatch):
    from threading import Event
    household, service, _ = create_service(tmp_path, {'entry-tray': 'candidate', 'living-table': 'candidate'})
    register(household, service)
    service.scene('entry-tray', upload(service, 2)['asset_id'])
    service.scene('living-table', upload(service, 3)['asset_id'])
    paused, release = Event(), Event()
    original = service._step
    first = True

    def controlled(run_id):
        nonlocal first
        again = original(run_id)
        if first and not again:
            first = False
            paused.set()
            assert release.wait(5)
        return again

    monkeypatch.setattr(service, '_step', controlled)
    started = service.start('帮我找蓝钥匙')
    assert paused.wait(5)
    candidate = service.get(started['run_id'])
    try:
        service.act(candidate['run_id'], candidate['version'], 'reject_candidate')
    finally:
        release.set()
    final = service.wait(started['run_id'])
    assert final['state'] == 'AWAITING_REVIEW'
    assert final['candidate']['location_id'] == 'living-table'
    assert final['visited'] == ['entry-tray', 'living-table']


def test_two_different_explicit_names_do_not_silently_select_longer_name(tmp_path):
    household, service, _ = create_service(tmp_path)
    household.enroll('blue', '蓝钥匙', ['钥匙'])
    household.enroll('red', '红色门钥匙', ['钥匙'])
    result = service.start('帮我找蓝钥匙和红色门钥匙')
    assert result['state'] == 'CLARIFY'
    assert len(result['matches']) == 2
    assert service.start('帮我找蓝钥匙')['state'] == 'NEEDS_REFERENCE'
