"""Persistent, confirmation-driven owner memory. No model or visual claims.

Sessions are separate from production evidence. Confirmation updates the owner
event store and attached session database in one SQLite rollback-journal
transaction. No half-saved location may be reported as cancelled.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from uuid import uuid4

from .household_memory import HouseholdMemory, _text, _time

LOCATIONS = ({'location_id': 'entry-tray', 'location_name': '玄关托盘'},
             {'location_id': 'study-desk', 'location_name': '书房桌面'},
             {'location_id': 'living-table', 'location_name': '客厅茶几'})
SESSION_APPLICATION_ID = 0x48544853


class HouseholdConflict(ValueError):
    """The browser holds an old version of the persistent interaction."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _sid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise ValueError('无效会话编号')
    return value


class HouseholdService:
    def __init__(self, workspace_dir):
        path = Path(workspace_dir).expanduser()
        if path.is_symlink():
            raise ValueError('家庭工作区不得是符号链接')
        self.workspace = path.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._check_private_output()
        self.memory_path = self.workspace / 'owner-memory.sqlite3'
        self.sessions_path = self.workspace / 'sessions.sqlite3'
        if self.sessions_path.is_symlink():
            raise ValueError('会话数据库不得是符号链接')
        # Existing foreign databases must be checked before opening them writable.
        if self.sessions_path.exists():
            self._inspect_sessions()
        else:
            try:
                with self.sessions_path.open('xb'):
                    pass
            except FileExistsError as exc:
                raise ValueError('工作区正在初始化，请稍后重试') from exc
            with closing(sqlite3.connect(self.sessions_path)) as db:
                db.executescript(f'''PRAGMA application_id={SESSION_APPLICATION_ID};
                    PRAGMA user_version=1;
                    CREATE TABLE household_sessions (
                      session_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                      payload TEXT NOT NULL);''')
        with HouseholdMemory(self.memory_path):
            pass

    def _check_private_output(self):
        try:
            found = subprocess.run(['git', '-C', str(self.workspace), 'rev-parse', '--show-toplevel'],
                                   capture_output=True, text=True, encoding='utf-8', timeout=10)
            if found.returncode:
                return
            root = Path(found.stdout.strip()).resolve()
            relative = self.workspace.relative_to(root).as_posix() + '/'
            result = subprocess.run(['git', '-C', str(root), 'check-ignore', '--no-index', '-q', '--', relative],
                                    capture_output=True, timeout=10)
            if result.returncode:
                raise ValueError('仓库内的家庭工作区必须位于 Git 忽略目录，例如 artifacts/')
        except FileNotFoundError as exc:
            raise ValueError('需要 Git 校验工作区隐私路径') from exc

    def _inspect_sessions(self):
        try:
            with closing(sqlite3.connect(self.sessions_path.as_uri()+'?mode=ro', uri=True)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if (tables != {'household_sessions'} or db.execute('PRAGMA application_id').fetchone()[0] != SESSION_APPLICATION_ID
                        or db.execute('PRAGMA user_version').fetchone()[0] != 1):
                    raise ValueError('拒绝打开非家庭交互会话数据库；不会迁移或覆盖旧库')
        except sqlite3.Error as exc:
            raise ValueError('会话数据库无法只读验证，未覆盖原文件') from exc

    def config(self):
        with HouseholdMemory(self.memory_path) as memory:
            catalog = memory.catalog()
        return {'enabled': True, 'catalog': catalog, 'locations': list(LOCATIONS),
                'notice': '本地规则与确认控件 · 主人陈述记忆 · 尚未进行视觉识别或机器人动作',
                'visual_confirmed': False}

    def enroll(self, object_id, name, aliases):
        with HouseholdMemory(self.memory_path) as memory:
            memory.connection.execute('BEGIN IMMEDIATE')
            try:
                result = memory.enroll(object_id, name, aliases)
                memory.connection.commit()
            except BaseException:
                memory.connection.rollback()
                raise
        return {'object': result, 'message': '已保存物品名称档案；外观尚未登记或验证', 'visual_confirmed': False}

    @staticmethod
    def _say(session, text, role='assistant'):
        session['messages'].append({'role': role, 'text': text})

    def _resolve(self, session):
        with HouseholdMemory(self.memory_path) as memory:
            result = memory.resolve(session['query'])
        session['matches'] = result['matches']
        if result['status'] == 'UNKNOWN_OBJECT':
            session['state'] = 'UNKNOWN_OBJECT'
            self._say(session, '这个名称还没有登记。请先登记物品名称与别名，再点击“重新查询”。')
        elif result['status'] == 'CLARIFY':
            session['state'] = 'CLARIFY'
            self._say(session, '有多个匹配的物品，请选择这次要操作的那一件。')
        else:
            self._select(session, result['matches'][0])

    def _select(self, session, obj):
        session['selected_object'] = obj
        if session['intent'] == 'remember':
            session['state'] = 'CONFIRM'
            self._say(session, f"请确认：把你说的“{obj['name']}”位置记录为“{session['location']['location_name']}”。这不会成为视觉确认。")
        else:
            with HouseholdMemory(self.memory_path) as memory:
                session['history'] = memory.history(obj['object_id'])
                session['candidates'] = memory.candidates(obj['object_id'])
            session['state'] = 'COMPLETED'
            if session['candidates']:
                first = session['candidates'][0]
                self._say(session, f"最近一条主人陈述的位置是“{first['location_name']}”。这是历史线索，尚未扫描或确认当前位置。")
            else:
                self._say(session, '该物品已登记名称，但还没有位置记录，不能推断它现在在哪里。')

    def start(self, intent, query, location_id=None, reported_at=None):
        if intent not in ('remember', 'recall'):
            raise ValueError('请选择记住位置或查询历史')
        query = _text(query, '物品名称', 120)
        location = None
        time_basis = 'owner_supplied_timestamp' if reported_at is not None else 'session_creation_time'
        if intent == 'remember':
            location = next((dict(x) for x in LOCATIONS if x['location_id'] == location_id), None)
            if location is None:
                raise ValueError('请明确选择已配置地点；系统不会自动猜测“这里”')
            if reported_at is not None:
                _time(reported_at)
            else:
                reported_at = _now()
        elif location_id is not None or reported_at is not None:
            raise ValueError('查询历史不接收新的地点或时间')
        session = {'session_id': uuid4().hex, 'version': 1, 'state': 'RESOLVING',
                   'intent': intent, 'query': query, 'matches': [], 'selected_object': None,
                   'location': location, 'reported_at': reported_at,
                   'reported_at_basis': time_basis if intent == 'remember' else None,
                   'created_at': _now(), 'messages': [], 'history': [], 'candidates': [],
                   'visual_confirmed': False, 'interaction_mode': 'local_rules_and_explicit_confirmation'}
        self._say(session, f"记住“{query}”的位置：{location['location_name']}" if location else f"查询“{query}”的历史位置", 'user')
        self._resolve(session)
        with closing(sqlite3.connect(self.sessions_path)) as db, db:
            db.execute('INSERT INTO household_sessions VALUES (?, ?, ?)',
                       (session['session_id'], session['version'], json.dumps(session, ensure_ascii=False)))
        return session

    def get(self, session_id):
        _sid(session_id)
        with closing(sqlite3.connect(self.sessions_path)) as db:
            row = db.execute('SELECT payload FROM household_sessions WHERE session_id=?', (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return json.loads(row[0])

    def act(self, session_id, version, action, object_id=None):
        _sid(session_id)
        if type(version) is not int or version < 1:
            raise ValueError('无效会话版本')
        if action not in ('select', 'confirm', 'cancel', 'retry'):
            raise ValueError('未知交互操作')
        if action != 'select' and object_id is not None:
            raise ValueError('只有目标选择操作可传入物品ID')
        with HouseholdMemory(self.memory_path) as memory:
            db = memory.connection
            db.execute('ATTACH DATABASE ? AS interaction', (str(self.sessions_path),))
            # Atomic multi-file commits require on-disk rollback journals. Refuse
            # an externally changed WAL configuration rather than assume atomicity.
            if (db.execute('PRAGMA main.journal_mode').fetchone()[0] != 'delete'
                    or db.execute('PRAGMA interaction.journal_mode').fetchone()[0] != 'delete'):
                raise ValueError('家庭数据库日志模式不兼容，未写入任何记录')
            # Serializes updates across threads/processes as well as this instance.
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute('SELECT version, payload FROM interaction.household_sessions WHERE session_id=?', (session_id,)).fetchone()
                if row is None:
                    raise KeyError(session_id)
                if row[0] != version:
                    raise HouseholdConflict('会话已更新，请刷新后确认当前内容')
                session = json.loads(row[1])
                if session['state'] in ('COMPLETED', 'CANCELLED'):
                    # Retrying a successful confirmation/cancellation with the latest
                    # version is harmless; an old browser version is rejected above.
                    if ((session['state'] == 'COMPLETED' and action == 'confirm' and session['intent'] == 'remember')
                            or (session['state'] == 'CANCELLED' and action == 'cancel')):
                        db.rollback()
                        return session
                    raise ValueError('这次交互已经结束，请开始新操作')
                if action == 'cancel':
                    session['state'] = 'CANCELLED'
                    self._say(session, '取消本次操作', 'user')
                    self._say(session, '已取消，没有保存新的位置记录。')
                elif action == 'select' and session['state'] == 'CLARIFY':
                    obj = next((x for x in session['matches'] if x['object_id'] == object_id), None)
                    if obj is None:
                        raise ValueError('只能选择本轮列出的候选物品')
                    self._say(session, f"选择“{obj['name']}”（{obj['object_id']}）", 'user')
                    self._select(session, obj)
                elif action == 'retry' and session['state'] == 'UNKNOWN_OBJECT':
                    self._say(session, '登记后重新查询', 'user')
                    self._resolve(session)
                elif action == 'confirm' and session['state'] == 'CONFIRM':
                    location = session['location']
                    memory.remember(event_id='remember-'+session_id,
                                    object_id=session['selected_object']['object_id'],
                                    location_id=location['location_id'], location_name=location['location_name'],
                                    reported_at=session['reported_at'],
                                    source='local_workspace_explicit_owner_confirmation:'+session['reported_at_basis'])
                    session['history'] = memory.history(session['selected_object']['object_id'])
                    session['candidates'] = memory.candidates(session['selected_object']['object_id'])
                    session['state'] = 'COMPLETED'
                    self._say(session, '确认保存这条位置陈述', 'user')
                    self._say(session, '好的，我已记录你说的位置；尚未通过当前图像确认。')
                else:
                    raise ValueError('当前状态不能执行这个操作')
                session['version'] += 1
                db.execute('UPDATE interaction.household_sessions SET version=?, payload=? WHERE session_id=?',
                           (session['version'], json.dumps(session, ensure_ascii=False), session_id))
                db.commit()
                return session
            except BaseException:
                db.rollback()
                raise
