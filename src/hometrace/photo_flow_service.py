"""Local photo workspace: durable actions, real matching, explicit owner review.

The optional graph controls a bounded loop; SearchCore remains the authority for
image provenance and replay. An owner confirmation never becomes visual FOUND.
"""
import base64
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from threading import Lock, Thread
from time import monotonic, sleep
from typing import TypedDict
from uuid import uuid4

from .household_memory import HouseholdMemory, _text
from .household_service import HouseholdConflict, LOCATIONS, _now, _sid
from .memory import SQLiteMemory
from .models import (DataSource, DetectionResult, MemoryRecord, NavigationMode,
                     NavigationResult, Observation, RegisteredObject, Status,
                     TimestampBasis, Viewpoint, validate_reference_roi)
from .search_core import SearchCore

APP_ID = 0x48545046
MAX_BYTES = 8 * 1024 * 1024
SOURCES = {'synthetic': DataSource.SYNTHETIC_IMAGE, 'real_upload': DataSource.USER_IMAGE}
TABLES = {'assets', 'refs', 'scenes', 'runs', 'evidence'}
NOTICE = '本地规则决策 · 模拟导航 · 真实执行图像匹配 · 外观候选需主人核对 · 合成图不证明实拍识别能力'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _dimensions(data):
    """Read dimensions before allocating decoded pixels; JPEG and PNG only."""
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24 and data[12:16] == b'IHDR':
        return (*struct.unpack('>II', data[16:24]), 'png')
    if data.startswith(b'\xff\xd8'):
        i = 2
        while i + 4 <= len(data):
            if data[i] != 255:
                break
            while i < len(data) and data[i] == 255:
                i += 1
            if i >= len(data):
                break
            marker = data[i]
            i += 1
            if marker in (0xD9, 0xDA):
                break
            if marker in (0x01, *range(0xD0, 0xD9)):
                continue
            length = int.from_bytes(data[i:i+2], 'big')
            if length < 2 or i + length > len(data):
                break
            if marker in (0xC0, 0xC1, 0xC2):
                if length < 8:
                    break
                h, w = struct.unpack('>HH', data[i+3:i+7])
                return w, h, 'jpg'
            i += length
    raise ValueError('仅支持可读取的 JPEG/PNG 图片')


class _EvidenceStore:
    def __init__(self, db, obj, reference):
        self.db, self.obj, self.ref = db, obj, reference

    def get_object(self, object_id):
        if object_id != self.obj['object_id']:
            return None
        return RegisteredObject(object_id, self.obj['name'], self.ref['path'],
                                self.ref['sha256'], SOURCES[self.ref['source_kind']])

    def query_memory(self, object_id):
        rows = self.db.execute('SELECT payload FROM evidence WHERE object_id=? ORDER BY rowid', (object_id,))
        return [SQLiteMemory._decode_record(row[0]) for row in rows]

    def update_memory(self, observation, detection):
        if (detection.target_id != self.obj['object_id'] or detection.evidence_id != observation.evidence_id
                or observation.data_source != SOURCES[self.ref['source_kind']]
                or detection.data_source != observation.data_source or detection.status == Status.FOUND):
            raise ValueError('照片证据合同不一致')
        payload = _json(asdict(MemoryRecord(observation, detection)))
        previous = self.db.execute('SELECT payload FROM evidence WHERE object_id=? AND evidence_id=?',
                                   (detection.target_id, observation.evidence_id)).fetchone()
        if previous:
            if previous[0] != payload:
                raise ValueError('旧证据不可覆盖')
            return False
        self.db.execute('INSERT INTO evidence VALUES(?,?,?)', (detection.target_id, observation.evidence_id, payload))
        return True


class _PhotoEnvironment:
    def __init__(self, run, source):
        self.run, self.source, self.arrived = run, source, None

    def list_viewpoints(self):
        return [Viewpoint(x['location_id'], x['location_name']) for x in LOCATIONS]

    def navigate_to(self, viewpoint_id):
        self.arrived = viewpoint_id
        return NavigationResult(viewpoint_id, 'ARRIVED', self.source.value, True, NavigationMode.SIMULATED)

    def observe(self, viewpoint_id):
        scene = self.run['snapshot']['scenes'].get(viewpoint_id)
        if self.arrived != viewpoint_id or scene is None:
            return None
        attempt = self.run.get('agent_internal', {}).get('observation_attempt')
        suffix = f'-{attempt}' if attempt else ''
        return Observation(f"photo-{self.run['run_id']}-{viewpoint_id}{suffix}", viewpoint_id, _now(),
                           SOURCES[scene['source_kind']], image_path=scene['path'], image_hash=scene['sha256'],
                           capture_source='operator_uploaded:' + scene['source_kind'],
                           timestamp_basis=TimestampBasis.DEMO_SEQUENCE)


class _PhotoDetector:
    def __init__(self, root, run, engine_factory):
        self.root, self.run, self.engine_factory, self.result = root, run, engine_factory, None

    def detect_target(self, observation, object_id):
        engine = self.engine_factory(self.root, self.run['snapshot']['reference'],
                                     self.run['snapshot']['scenes'], object_id)
        row = self.result = engine.observe(observation.viewpoint_id)
        # Weak unlocalized matches cannot open an accept button.
        status = Status.SUSPECTED if row['appearance_candidate'] and row['bbox'] else Status.UNKNOWN
        return DetectionResult(object_id, observation.evidence_id, status,
                               matcher=row['matcher'], data_source=observation.data_source,
                               verification_kind='appearance_candidate', diagnostics=row['diagnostics'], bbox=row['bbox'])


class _GraphState(TypedDict):
    run_id: str
    again: bool


class PhotoFlowService:
    def __init__(self, household_service, *, engine_factory=None, use_graph=True):
        self.household = household_service
        self.root = household_service.workspace
        self.path = self.root / 'photo-flow.sqlite3'
        self.assets_dir = self.root / 'photos'
        if self.assets_dir.is_symlink() or self.path.is_symlink():
            raise ValueError('照片库不得是符号链接')
        self.assets_dir.mkdir(exist_ok=True)
        self._workers, self._lock = {}, Lock()
        self._engine_factory = engine_factory
        if self.path.exists():
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if (tables != TABLES or db.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                        or db.execute('PRAGMA user_version').fetchone()[0] != 1):
                    raise ValueError('拒绝覆盖非照片工作区数据库')
        else:
            with self.path.open('xb'):
                pass
            with closing(self._connect()) as db:
                db.executescript(f'''PRAGMA application_id={APP_ID}; PRAGMA user_version=1;
                    CREATE TABLE assets (asset_id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
                    CREATE TABLE refs (object_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                    CREATE TABLE scenes (location_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL);
                    CREATE TABLE runs (run_id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
                    CREATE TABLE evidence (object_id TEXT NOT NULL, evidence_id TEXT NOT NULL, payload TEXT NOT NULL,
                                           PRIMARY KEY(object_id,evidence_id));''')
        self.mode, self.graph = 'deterministic_rules', None
        if use_graph:
            try:
                from langgraph.graph import END, START, StateGraph
            except ImportError:
                pass
            else:
                graph = StateGraph(_GraphState)
                graph.add_node('search_next_location', lambda state: {'again': self._step(state['run_id'])})
                graph.add_edge(START, 'search_next_location')
                graph.add_conditional_edges('search_next_location', lambda state: 'next' if state['again'] else 'end',
                                            {'next': 'search_next_location', 'end': END})
                self.graph = graph.compile()
                self.mode = 'deterministic_langgraph'

    def _engine(self, *args):
        if self._engine_factory is not None:
            return self._engine_factory(*args)
        from .photo_engine import PhotoSearchEngine
        return PhotoSearchEngine(*args)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def _trace(run, tool, inputs, result):
        run['trace'].append({'seq': len(run['trace'])+1, 'tool': tool, 'input': inputs, 'result': result, 'at': _now()})

    @staticmethod
    def _save(db, run):
        run['version'] += 1
        db.execute('INSERT INTO runs VALUES(?,?,?) ON CONFLICT(run_id) DO UPDATE SET version=excluded.version,payload=excluded.payload',
                   (run['run_id'], run['version'], _json(run)))

    @staticmethod
    def _load(db, run_id):
        row = db.execute('SELECT payload FROM runs WHERE run_id=?', (_sid(run_id),)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    @staticmethod
    def _public(run):
        return {k: v for k, v in run.items() if k not in ('snapshot', 'agent_internal')}

    def get(self, run_id):
        with closing(self._connect()) as db:
            return self._public(self._load(db, run_id))

    @staticmethod
    def _asset_row(db, asset_id):
        row = db.execute('SELECT payload FROM assets WHERE asset_id=?', (_sid(asset_id),)).fetchone()
        if row is None:
            raise ValueError('照片不存在，请先上传')
        return json.loads(row[0])

    def asset(self, asset_id):
        with closing(self._connect()) as db:
            row = self._asset_row(db, asset_id)
        path = self.root / row['path']
        if path.is_symlink() or not path.resolve().is_relative_to(self.assets_dir.resolve()):
            raise ValueError('照片路径不可用')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('照片内容校验失败')
        return data, 'image/png' if path.suffix == '.png' else 'image/jpeg'

    def upload(self, data_base64, source_kind):
        if not isinstance(source_kind, str) or source_kind not in SOURCES:
            raise ValueError('请声明合成图或用户实拍图来源')
        if not isinstance(data_base64, str) or len(data_base64) > (MAX_BYTES+2)//3*4:
            raise ValueError('图片不得超过 8 MB')
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('图片编码无效') from exc
        if not data or len(data) > MAX_BYTES:
            raise ValueError('图片为空或超过 8 MB')
        w, h, ext = _dimensions(data)
        if min(w, h) < 32 or w*h > 24_000_000:
            raise ValueError('图片边长至少 32 像素，最多 2400 万像素')
        import cv2
        import numpy as np
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if decoded is None or decoded.shape[:2] != (h, w):
            raise ValueError('图片解码失败或尺寸不一致；请导出为标准 PNG/JPEG')
        # Browser orientation and matching must share the same pixel system.
        # EXIF-rotated JPEGs are rejected rather than silently rewriting bytes.
        normal = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if normal is None or normal.shape != decoded.shape or not np.array_equal(normal, decoded):
            raise ValueError('请先按显示方向导出图片并清除 EXIF 方向，再上传')
        digest, asset_id = hashlib.sha256(data).hexdigest(), uuid4().hex
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT payload FROM assets WHERE sha256=?', (digest,)).fetchone()
            if old:
                row = json.loads(old[0])
                if row['source_kind'] != source_kind:
                    raise ValueError('同一图片的来源声明不可改写')
                return {k: v for k, v in row.items() if k != 'path'}
            row = {'asset_id': asset_id, 'sha256': digest, 'source_kind': source_kind,
                   'width': w, 'height': h, 'path': f'photos/{asset_id}.{ext}',
                   'url': f'/api/home-flow/assets/{asset_id}', 'uploaded_at': _now(), 'capture_time': 'unknown'}
            with (self.root / row['path']).open('xb') as out:
                out.write(data)
            db.execute('INSERT INTO assets VALUES(?,?,?)', (asset_id, digest, _json(row)))
        return {k: v for k, v in row.items() if k != 'path'}

    def reference(self, object_id, asset_id, roi, roi_reviewed):
        if roi_reviewed is not True:
            raise ValueError('请先人工确认目标 ROI')
        with HouseholdMemory(self.household.memory_path) as memory:
            if not any(x['object_id'] == object_id for x in memory.catalog()):
                raise ValueError('请先登记物品名称')
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._asset_row(db, asset_id)
            region = validate_reference_roi(roi, (row['width'], row['height']))
            if region is None:
                raise ValueError('请框选登记物品区域')
            old = db.execute('SELECT payload FROM refs WHERE object_id=?', (object_id,)).fetchone()
            if old:
                previous = json.loads(old[0])
                if previous['asset_id'] != asset_id or previous['roi'] != list(region):
                    raise HouseholdConflict('参考图与 ROI 已冻结；请登记新的物品编号进行另一项实验')
                return {k: v for k, v in previous.items() if k != 'path'}
            row.update(roi=list(region), roi_reviewed=True, reviewed_at=_now(), review_source='local_operator_confirmation')
            row['quality'] = self._engine(self.root, row, {}, object_id).quality()
            db.execute('INSERT INTO refs VALUES(?,?)', (object_id, _json(row)))
        return {k: v for k, v in row.items() if k != 'path'}

    def scene(self, location_id, asset_id):
        if not isinstance(location_id, str) or location_id not in {x['location_id'] for x in LOCATIONS}:
            raise ValueError('未知地点')
        with closing(self._connect()) as db, db:
            row = self._asset_row(db, asset_id)
            db.execute('INSERT INTO scenes VALUES(?,?) ON CONFLICT(location_id) DO UPDATE SET asset_id=excluded.asset_id', (location_id, asset_id))
        return {'location_id': location_id, **{k: v for k, v in row.items() if k != 'path'}}

    def config(self):
        config = self.household.config()
        with closing(self._connect()) as db:
            refs = {key: json.loads(value) for key, value in db.execute('SELECT * FROM refs')}
            scenes = [{'location_id': loc, **{k: v for k, v in self._asset_row(db, aid).items() if k != 'path'}}
                      for loc, aid in db.execute('SELECT * FROM scenes')]
        for obj in config['catalog']:
            ref = refs.get(obj['object_id'])
            obj['reference'] = {k: v for k, v in ref.items() if k != 'path'} if ref else None
        return {**config, 'scenes': scenes, 'mode': self.mode, 'notice': NOTICE}

    def _resolve(self, db, run):
        text = run['message']
        with HouseholdMemory(self.household.memory_path) as memory:
            catalog = memory.catalog()
        mentions = []
        for obj in catalog:
            for alias in [obj['object_id'], obj['name'], *obj['aliases']]:
                start = text.casefold().find(alias.casefold())
                if start >= 0:
                    mentions.append((start, start+len(alias.casefold()), obj['object_id']))
        # Ignore a generic alias contained inside an explicit longer name, but
        # never silently discard a different object mentioned elsewhere.
        ids = {oid for a, b, oid in mentions if not any(c <= a and b <= d and d-c > b-a for c, d, _ in mentions)}
        matches = [obj for obj in catalog if obj['object_id'] in ids]
        run['matches'] = matches
        self._trace(run, 'resolve_registered_object', {'message': text}, {'object_ids': [x['object_id'] for x in matches]})
        if not matches:
            run.update(state='UNKNOWN_OBJECT', reply='未找到已登记的物品名称或别名。请先登记，再重新查询。')
        elif len(matches) > 1:
            run.update(state='CLARIFY', reply='名称对应多件物品，请选择具体哪一件。')
        else:
            self._select(db, run, matches[0])

    def _select(self, db, run, obj):
        run['selected_object'] = obj
        with HouseholdMemory(self.household.memory_path) as memory:
            run['history'] = memory.history(obj['object_id'])
            locations = memory.candidates(obj['object_id'])
        self._trace(run, 'query_owner_memory', {'object_id': obj['object_id']}, {'history': run['history'], 'historical_only': True})
        if run['intent'] == 'history':
            place = locations[0]['location_name'] if locations else None
            run.update(state='COMPLETED', reply=f'最近记录的位置是{place}；这是主人陈述的历史，不代表当前位置。' if place else '尚无位置记忆。')
            return
        ref = db.execute('SELECT payload FROM refs WHERE object_id=?', (obj['object_id'],)).fetchone()
        if ref is None:
            run.update(state='NEEDS_REFERENCE', reply='名称已登记，请先上传参考照片并确认目标区域，再重试。')
            return
        if run['intent'] == 'remember':
            if not run['current_location_id']:
                run.update(state='ERROR', reply='“这里”需要你选择当前地点，然后重新发送请求。系统没有主人定位传感器。')
                return
            name = next(x['location_name'] for x in LOCATIONS if x['location_id'] == run['current_location_id'])
            run.update(state='CONFIRM_MEMORY', reply=f'请确认将{obj["name"]}的位置记录为{name}。这是一条主人陈述，不是视觉确认。')
            return
        known = {x['location_id']: x['location_name'] for x in LOCATIONS}
        order = [x['location_id'] for x in locations if x['location_id'] in known]
        run['planned_locations'] = [{'location_id': key, 'location_name': known[key],
                                    'reason': 'recent_owner_memory' if key in order else 'unvisited_fallback'}
                                   for key in order + sorted(set(known)-set(order))]
        run['snapshot'] = {'reference': json.loads(ref[0]),
                           'scenes': {loc: self._asset_row(db, aid) for loc, aid in db.execute('SELECT * FROM scenes')}}
        run.update(state='RUNNING', reply='已读取历史，开始按顺序检查配置的场景图片。导航为模拟。')
        self._trace(run, 'plan_search', {'history_event_ids': [x['event_id'] for x in run['history']]}, {'locations': run['planned_locations']})

    def start(self, message, current_location_id=None):
        message = _text(message, '请求', 1000)
        if current_location_id not in (None, '', *(x['location_id'] for x in LOCATIONS)):
            raise ValueError('未知当前地点')
        # This is an explicit deterministic language subset, not an LLM claim.
        remember = any(x in message for x in ('记住', '放这里', '放在这里', '我放'))
        history = any(x in message for x in ('历史', '上次', '最近记录', '记在哪'))
        find = any(x in message for x in ('找', '寻找', '搜索'))
        if sum((remember, history, find)) != 1:
            raise ValueError('请一次说一个意图，例如“记住钥匙放在这里”“帮我找钥匙”或“查看钥匙历史”')
        if any(x in message for x in ('不要', '别帮', '不需要', '不用', '别记', '别找', '取消')):
            raise ValueError('收到否定或取消意图，没有执行。可用当前会话的取消按钮。')
        intent = 'remember' if remember else 'history' if history else 'find'
        run = {'run_id': uuid4().hex, 'version': 0, 'state': 'RESOLVING', 'intent': intent,
               'message': message, 'current_location_id': current_location_id or None,
               'selected_object': None, 'matches': [], 'history': [], 'planned_locations': [], 'visited': [],
               'trace': [], 'observations': [], 'candidate': None, 'reply': '', 'mode': self.mode,
               'visual_confirmed': False, 'created_at': _now(), 'core_reports': []}
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._resolve(db, run)
            self._save(db, run)
        if run['state'] == 'RUNNING':
            self._launch(run['run_id'])
        return self._public(run)

    def _confirm(self, run_id, version, action):
        # Validate owner DB first, then use one attached-database transaction.
        with HouseholdMemory(self.household.memory_path) as memory:
            db = memory.connection
            db.execute('ATTACH DATABASE ? AS photo', (str(self.path),))
            if any(db.execute(f'PRAGMA {name}.journal_mode').fetchone()[0].lower() != 'delete' for name in ('main', 'photo')):
                raise ValueError('跨数据库确认要求 DELETE journal；拒绝在 WAL 下执行确认')
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute('SELECT payload FROM photo.runs WHERE run_id=?', (_sid(run_id),)).fetchone()
                if row is None:
                    raise KeyError(run_id)
                run = json.loads(row[0])
                if run['version'] != version:
                    raise HouseholdConflict('状态已更新，请读取最新结果')
                expected = 'CONFIRM_MEMORY' if action == 'confirm_memory' else 'AWAITING_REVIEW'
                if run['state'] != expected:
                    raise ValueError('当前状态不能执行此确认')
                if action == 'accept_candidate':
                    candidate = run['candidate']
                    self.asset(candidate['asset_id'])  # Content must still match the evidence hash.
                    location_id = candidate['location_id']
                    source = self._candidate_memory_source(run, candidate)
                else:
                    location_id = run['current_location_id']
                    source = f'photo_workspace_owner_statement:{run_id}:local_system_clock'
                location_name = next(x['location_name'] for x in LOCATIONS if x['location_id'] == location_id)
                event = memory.remember(event_id='photo-'+run_id, object_id=run['selected_object']['object_id'],
                                        location_id=location_id, location_name=location_name, reported_at=_now(), source=source)
                run.update(state='USER_CONFIRMED' if action == 'accept_candidate' else 'COMPLETED',
                           reply=f'好的，我记住了：{location_name}。保存为主人确认的位置，自动视觉结论仍未确认为 FOUND。',
                           owner_event=event, history=memory.history(run['selected_object']['object_id']))
                self._trace(run, 'save_owner_memory', {'action': action}, event)
                run['version'] += 1
                db.execute('UPDATE photo.runs SET version=?,payload=? WHERE run_id=?', (run['version'], _json(run), run_id))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self._public(run)

    def _candidate_memory_source(self, run, candidate):
        return f"photo_candidate_owner_review:{run['run_id']}:{candidate['image_sha256']}"

    def act(self, run_id, version, action, object_id=None):
        if type(version) is not int or version < 1:
            raise ValueError('无效版本号')
        if self.mode != 'llm_langgraph' and self.get(run_id).get('mode') == 'llm_langgraph':
            raise ValueError('此记录由真实 LLM 执行，请使用 --photo-agent 启动后继续；不能切换为规则执行')
        if action in ('confirm_memory', 'accept_candidate'):
            if object_id is not None:
                raise ValueError('确认操作不接收新的物品编号')
            return self._confirm(run_id, version, action)
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            run = self._load(db, run_id)
            if run['version'] != version:
                raise HouseholdConflict('状态已更新，请读取最新结果')
            if object_id is not None and action != 'select':
                raise ValueError('该操作不接收物品编号')
            if action == 'cancel' and run['state'] not in ('COMPLETED', 'USER_CONFIRMED', 'UNKNOWN', 'CANCELLED'):
                run.update(state='CANCELLED', reply='已取消后续操作；已经产生的历史证据保留。', candidate=None)
            elif action == 'select' and run['state'] == 'CLARIFY':
                obj = next((x for x in run['matches'] if x['object_id'] == object_id), None)
                if obj is None:
                    raise ValueError('请从本次候选物品中选择')
                self._select(db, run, obj)
            elif action == 'retry' and run['state'] in ('UNKNOWN_OBJECT', 'NEEDS_REFERENCE'):
                if run['selected_object']:
                    self._select(db, run, run['selected_object'])
                else:
                    self._resolve(db, run)
            elif action == 'retry' and run['state'] in ('RUNNING', 'ERROR') and run.get('snapshot'):
                run.update(state='RUNNING', reply='继续检查尚未完成的地点。')
            elif action == 'reject_candidate' and run['state'] == 'AWAITING_REVIEW':
                self._trace(run, 'owner_reject_candidate', {'location_id': run['candidate']['location_id']}, {'accepted': False})
                run.update(state='RUNNING', candidate=None, reply='已拒绝该候选，继续检查下一个地点。')
            else:
                raise ValueError('当前状态不支持此操作')
            self._save(db, run)
        if run['state'] == 'RUNNING':
            self._launch(run_id)
        return self._public(run)

    def _launch(self, run_id):
        with self._lock:
            previous = self._workers.get(run_id)
            if previous and previous.is_alive():
                return
            worker = Thread(target=self._work, args=(run_id,), daemon=True)
            self._workers[run_id] = worker
            worker.start()

    def _work(self, run_id):
        try:
            if self.graph is not None:
                self.graph.invoke({'run_id': run_id, 'again': True}, {'recursion_limit': getattr(self, 'graph_limit', 8)})
            else:
                while self._step(run_id):
                    pass
        except Exception as exc:
            # No paths, private image bytes, keys or arbitrary exception text in UI.
            with closing(self._connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                run = self._load(db, run_id)
                if run['state'] == 'RUNNING':
                    run.update(state='ERROR', reply='本地照片处理失败。请检查照片库和视觉依赖后重试；未确认目标。')
                    self._trace(run, 'execution_error', {}, {'error_type': type(exc).__name__})
                    self._save(db, run)
        finally:
            # A review action can arrive just as the worker returns after its
            # candidate commit. Do not lose that request to resume searching.
            with self._lock:
                self._workers.pop(run_id, None)
            if self.get(run_id)['state'] == 'RUNNING':
                self._launch(run_id)

    def wait(self, run_id, timeout=30):
        deadline = monotonic() + timeout
        while True:
            with self._lock:
                thread = self._workers.get(run_id)
            if thread:
                thread.join(max(0, deadline-monotonic()))
            run = self.get(run_id)
            if run['state'] != 'RUNNING' or monotonic() >= deadline:
                return run
            # The previous worker may have handed a concurrent reject/retry to
            # its successor. Wait on that worker, not just the first thread.
            sleep(min(.01, max(0, deadline-monotonic())))

    def _step(self, run_id, *, location_id=None, reason=None, expected_version=None, observation_attempt=None):
        # Evidence + completed location + trace commit together. A crash rolls
        # back the entire step, so resume does not consume invisible evidence.
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            run = self._load(db, run_id)
            if run['state'] != 'RUNNING':
                return False
            if expected_version is not None and run['version'] != expected_version:
                return False
            remaining = [x for x in run['planned_locations'] if x['location_id'] not in run['visited']]
            if observation_attempt is not None:
                pending = run.get('agent_internal', {}).get('new_photo_pending')
                if (not run.get('visual_advisor_enabled') or not pending or pending['attempt_id'] != observation_attempt
                        or pending['location_id'] != location_id):
                    raise ValueError('补拍观察必须绑定已批准的新照片')
                remaining = [x for x in run['planned_locations'] if x['location_id'] == location_id]
                run['agent_internal']['observation_attempt'] = observation_attempt
            chosen = None
            if location_id is not None:
                chosen = next((x for x in remaining if x['location_id'] == location_id), None)
                if chosen is None:
                    raise ValueError('模型只能选择合法且尚未访问的地点')
                chosen = {**chosen, 'reason': _text(reason, '决策理由', 240)}
            if not remaining:
                run.update(state='UNKNOWN', reply='已检查所有配置地点，仍未确认目标。UNKNOWN 不代表目标一定不在家中；请补充新的场景照片。')
                self._trace(run, 'finish_search', {}, {'status': 'UNKNOWN', 'automatic_found': False})
                self._save(db, run)
                return False
            view = chosen or remaining[0]
            loc = view['location_id']
            source = SOURCES[run['snapshot']['reference']['source_kind']]
            memory = _EvidenceStore(db, run['selected_object'], run['snapshot']['reference'])
            detector = _PhotoDetector(self.root, run, self._engine)
            core = SearchCore(memory, _PhotoEnvironment(run, source), detector,
                              data_source=source, navigation_mode=NavigationMode.SIMULATED)
            core.start_search(run['selected_object']['object_id'], f'{run_id}-{len(run["observations"])}')
            self._trace(run, 'navigate_simulated', {'location_id': loc, 'reason': view['reason']}, core.navigate_viewpoint(loc, view['reason']))
            acquired = core.observe_current()
            self._trace(run, 'observe_uploaded_image', {'location_id': loc}, acquired)
            result = core.verify_current() if core.current_phase == 'observed' else acquired
            if detector.result is not None:
                self._trace(run, 'match_reference_image', {'location_id': loc}, result)
            scene = run['snapshot']['scenes'].get(loc, {})
            raw = detector.result or {}
            row = {'location_id': loc, 'location_name': view['location_name'], 'asset_id': scene.get('asset_id'),
                   'url': scene.get('url'), 'source_kind': scene.get('source_kind'), 'image_sha256': scene.get('sha256'),
                   'width': scene.get('width'), 'height': scene.get('height'), 'status': result['status'],
                   'bbox': result.get('candidate_bbox'), 'diagnostics': raw.get('diagnostics', result.get('diagnostics', {})),
                   'reason': result.get('reason') or raw.get('reason', 'not_confirmed'),
                   'duration_ms': raw.get('duration_ms'), 'raw_match_status': raw.get('raw_match_status'),
                   'identity_confirmed': False}
            if loc not in run['visited']:
                run['visited'].append(loc)
            run['observations'].append(row)
            run['core_reports'].append(core.finish_search().to_dict())
            self._after_observation(run, row)
            if observation_attempt is not None:
                run['agent_internal'].pop('observation_attempt', None)
                run['agent_internal'].pop('new_photo_pending', None)
            self._trace(run, 'review_or_continue', {'location_id': loc}, {'state': run['state'], 'reason': row['reason']})
            self._save(db, run)
            return run['state'] == 'RUNNING'

    def _after_observation(self, run, row):
        if row['bbox'] and row['status'] == Status.SUSPECTED:
            run.update(state='AWAITING_REVIEW', candidate=row,
                       reply=f'{row["location_name"]}出现了外观候选，请核对参考图和检测框。尚不能确认是同一实体。')
        else:
            run['reply'] = f'{row["location_name"]}未获得可确认的候选，继续检查其他地点。'
