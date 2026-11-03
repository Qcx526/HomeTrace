"""Read-only viewer of completed tasks using the unchanged production HTML.

No model is constructed and no write API is available. Existing database and
photo bytes are read directly, never reconstructed from presentation text.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from hometrace.demo_server import make_server
from hometrace.household_locations import load_workspace_locations
from hometrace.household_memory import HouseholdMemory, APPLICATION_ID as OWNER_ID
from hometrace.photo_flow_service import PhotoFlowService, APP_ID, TABLES


class SavedDemo:
    def __init__(self, workspace, summary):
        self.root = Path(workspace).resolve(strict=True)
        self.path = self.root / 'photo-flow.sqlite3'
        self.assets_dir = self.root / 'photos'
        self.memory_path = self.root / 'owner-memory.sqlite3'
        if any(p.is_symlink() for p in (Path(workspace), self.path, self.assets_dir, self.memory_path)):
            raise ValueError('Symlinks are not allowed')
        self.allowed = {}
        for name in ('main', 'history', 'replay'):
            value = summary['runs'][name]['final']
            if value['state'] not in ('USER_CONFIRMED', 'COMPLETED', 'UNKNOWN'):
                raise ValueError('Only completed tasks may be reviewed')
            self.allowed[value['run_id']] = value
        with closing(self._connect()) as db:
            if (db.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                    or {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} != TABLES):
                raise ValueError('Unexpected photo database')
        for run_id, expected in self.allowed.items():
            if self.get(run_id) != expected:
                raise ValueError('Saved database differs from frozen execution evidence')

    def _connect(self):
        return sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)

    _public = staticmethod(PhotoFlowService._public)
    _load = staticmethod(PhotoFlowService._load)
    _asset_row = staticmethod(PhotoFlowService._asset_row)
    asset = PhotoFlowService.asset

    def get(self, run_id):
        if run_id not in self.allowed:
            raise KeyError('Task not approved for review')
        return PhotoFlowService.get(self, run_id)

    def config(self):
        with closing(sqlite3.connect(self.memory_path.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA application_id').fetchone()[0] != OWNER_ID:
                raise ValueError('Unexpected memory database')
            db.row_factory=sqlite3.Row
            catalog=[HouseholdMemory._object(r) for r in db.execute('SELECT * FROM hm_objects ORDER BY object_id')]
        places=load_workspace_locations(self.root)
        with closing(self._connect()) as db:
            refs={k:json.loads(v) for k,v in db.execute('SELECT * FROM refs')}
            scenes=[{'location_id':loc,**{k:v for k,v in self._asset_row(db,aid).items() if k!='path'}}
                    for loc,aid in db.execute('SELECT * FROM scenes')]
        for obj in catalog:
            ref=refs.get(obj['object_id']);obj['reference']={k:v for k,v in ref.items() if k!='path'} if ref else None
        return dict(enabled=True,catalog=catalog,locations=places,scenes=scenes,
                    mode='saved_task_readonly',visual_confirmed=False,
                    notice='已完成任务只读回看：当前不执行模型或写入；下方轨迹来自已保存的实际任务。')


def server_for(service, port=0):
    server=make_server(port=port,photo_flow_service=service)
    original=server.RequestHandlerClass
    class ReadOnlyHandler(original):
        def do_POST(self):
            self._reject({'error':'Saved task review is read-only'},405)
        do_PUT=do_DELETE=do_PATCH=do_POST
    server.RequestHandlerClass=ReadOnlyHandler
    return server


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--port',type=int,default=0)
    args=p.parse_args()
    service=SavedDemo(args.workspace,json.loads(args.summary.read_text(encoding='utf8')))
    with server_for(service,args.port) as server:
        print(f'HomeTrace demo: http://127.0.0.1:{server.server_port}',flush=True)
        server.serve_forever()


if __name__=='__main__':main()
