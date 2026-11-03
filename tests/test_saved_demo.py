"""Completed software fixture review never calls models or mutates databases."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3
from threading import Thread
from urllib.request import Request,urlopen
from urllib.error import HTTPError

import pytest
from hometrace.household_service import HouseholdService
from hometrace.photo_flow_service import PhotoFlowService
from tools.serve_saved_demo import SavedDemo,server_for


@pytest.fixture
def saved(tmp_path):
    household=HouseholdService(tmp_path/'TEST_ONLY')
    household.enroll('fixture','软件测试物品',[])
    flow=PhotoFlowService(household,use_graph=False)
    summary={'runs':{}}
    with closing(flow._connect()) as db,db:
        for i,(name,state) in enumerate([('main','USER_CONFIRMED'),('history','COMPLETED'),('replay','UNKNOWN')],1):
            row={'run_id':f'{i:032x}','state':state,'version':1,'trace':[],
                 'visual_confirmed':False,'snapshot':{},'agent_internal':{}}
            db.execute('INSERT INTO runs VALUES(?,?,?)',(row['run_id'],1,json.dumps(row)))
            summary['runs'][name]={'final':flow._public(row)}
    return household.workspace,summary


def hashes(root):return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.sqlite3')}


def test_config_and_saved_runs_read_unchanged_database(saved):
    root,summary=saved;before=hashes(root);viewer=SavedDemo(root,summary)
    assert viewer.config()['catalog'][0]['name']=='软件测试物品'
    assert viewer.config()['mode']=='saved_task_readonly'
    for item in summary['runs'].values():assert viewer.get(item['final']['run_id'])==item['final']
    with closing(viewer._connect()) as db:
        with pytest.raises(sqlite3.OperationalError):db.execute('DELETE FROM runs')
    assert hashes(root)==before


@pytest.mark.parametrize('problem',['changed_state','changed_trace','running','unknown_run'])
def test_changed_or_unfinished_evidence_rejected(saved,problem):
    root,summary=saved;summary=deepcopy(summary);row=summary['runs']['main']['final']
    if problem=='changed_state':row['state']='COMPLETED'
    elif problem=='changed_trace':row['trace']=[{'fake':'tool'}]
    elif problem=='running':row['state']='RUNNING'
    else:row['run_id']='f'*32
    with pytest.raises((ValueError,KeyError)):SavedDemo(root,summary)


def test_real_http_serves_ui_and_refuses_write(saved):
    root,summary=saved;before=hashes(root)
    server=server_for(SavedDemo(root,summary));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base) as response:assert b'home-flow.js' in response.read()
        with urlopen(base+'/api/home-flow/runs/'+summary['runs']['main']['final']['run_id']) as response:
            assert json.load(response)['state']=='USER_CONFIRMED'
        for method in ('POST','PUT','DELETE','PATCH'):
            with pytest.raises(HTTPError) as error:urlopen(Request(base+'/api/home-flow/start',data=b'{}',method=method))
            assert error.value.code==405
        with pytest.raises(HTTPError) as error:urlopen(base+'/api/home-flow/runs/'+'f'*32)
        assert error.value.code==404
    finally:server.shutdown();thread.join(timeout=5);server.server_close()
    assert hashes(root)==before
