"""HTTP boundary tests with a stub service; no model capability claims."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import pytest
from hometrace.demo_server import make_server


class Demo:
    def config(self): return {}


class Agent:
    def config(self): return {"enabled":True,"scenarios":[]}
    def start(self,goal,scenario): return {"run_id":"a"*32}
    def get(self,run_id):
        if run_id!="a"*32: raise KeyError()
        return {"status":"RUNNING","trace":[]}
    def asset(self,run_id,key): raise KeyError()


@pytest.fixture
def server():
    with make_server(Demo(),0,agent_service=Agent()) as http:
        thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start()
        yield f"http://127.0.0.1:{http.server_port}"
        http.shutdown();thread.join()


def request(url,data=None,headers=None):
    req=Request(url,data=json.dumps(data).encode() if data is not None else None,headers={"Content-Type":"application/json",**(headers or {})})
    try:
        with urlopen(req,timeout=5) as result:return result.status,result.read()
    except HTTPError as exc:return exc.code,exc.read()


@pytest.mark.parametrize("path",["/agent.html","/agent.js","/agent.css","/api/agent/config"])
def test_agent_resources(server,path): assert request(server+path)[0]==200


def test_actual_poll_contract(server):
    status,body=request(server+"/api/agent/run",{"goal":"找盒子","scenario":"moved"})
    assert status==200
    run_id=json.loads(body)["run_id"]
    assert json.loads(request(server+"/api/agent/runs/"+run_id)[1])["status"]=="RUNNING"
    assert request(server+"/api/agent/runs/"+run_id+"/images/current-1")[0]==404


@pytest.mark.parametrize("headers",[{"Host":"evil.example"},{"Origin":"https://evil.example"}])
def test_external_control_rejected(server,headers):
    assert request(server+"/api/agent/run",{"goal":"找","scenario":"moved"},headers)[0]==403


@pytest.mark.parametrize("body",[{"goal":7,"scenario":"moved"},{"goal":"找","scenario":"moved","api_key":"fake"},[]])
def test_invalid_body(server,body): assert request(server+"/api/agent/run",body)[0]==400


def test_disabled():
    with make_server(Demo(),0) as http:
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        assert request(f"http://127.0.0.1:{http.server_port}/api/agent/run",{"goal":"找","scenario":"moved"})[0]==503
        http.shutdown();thread.join()
