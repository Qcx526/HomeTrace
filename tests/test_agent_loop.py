"""Offline transport tests only; not evidence of real model performance."""
from dataclasses import replace
from pathlib import Path
import pytest

pytest.importorskip("langgraph")
pytest.importorskip("langchain_core")
from langchain_core.messages import AIMessage, ToolMessage
from hometrace.agent import HomeTraceAgent
from hometrace.agent_config import AgentConfig, LLMConfig, BudgetConfig
from hometrace.environment import MockAdapter
from hometrace.memory import SQLiteMemory
from hometrace.models import Viewpoint, Observation, DetectionResult, Status
from hometrace.perception import FixtureDetector
from hometrace.search_core import SearchCore


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.received = []
    def bind_tools(self, tools):
        return self
    def invoke(self, messages, **kwargs):
        self.received.append(list(messages))
        value = next(self.responses)
        if isinstance(value,Exception):
            raise value
        return value


def response(name=None,args=None,content="",tokens=100):
    return AIMessage(content=content,tool_calls=[{"name":name,"args":args or {},"id":"call-1"}] if name else [],
                     usage_metadata={"input_tokens":tokens-10,"output_tokens":10,"total_tokens":tokens})


@pytest.fixture
def setup_agent(tmp_path):
    with SQLiteMemory() as memory:
        memory.register_object("box",None,"盒子")
        config=AgentConfig(LLMConfig("openai_compatible","test","https://example.invalid/v1",10,0,False),BudgetConfig(8,12,5,24000,True),"synthetic",tmp_path,tmp_path/"config.yaml")
        def factory(object_id):
            obs={"A":Observation("e1","A","2026-10-21T09:00:00+08:00"),"B":Observation("e2","B","2026-10-21T09:01:00+08:00")}
            detections={"e1":DetectionResult(object_id,"e1",Status.UNKNOWN),"e2":DetectionResult(object_id,"e2",Status.FOUND)}
            return SearchCore(memory,MockAdapter([Viewpoint("A","A"),Viewpoint("B","B")],obs),FixtureDetector(detections))
        def make(responses,**budget):
            client=Transport(responses)
            agent=HomeTraceAgent(replace(config,agent=replace(config.agent,**budget)),memory,factory,model=client)
            return agent,client
        yield make,memory


def test_feedback_and_shared_found(setup_agent):
    make,memory=setup_agent
    agent,client=make([response("query_memory",{"object_id":"O1"}),response("navigate_and_observe",{"viewpoint_id":"V1"}),response("verify_visual"),response("navigate_and_observe",{"viewpoint_id":"V2"}),response("verify_visual"),response(content="工具确认V2")])
    result=agent.run("找盒子")
    assert result["status"]=="COMPLETED"
    assert result["verified_result"]["result_status"]=="FOUND"
    assert result["verified_result"]["attempted_viewpoints"]==["V1","V2"]
    assert len(memory.query_memory("box"))==2
    assert any(isinstance(m,ToolMessage) for m in client.received[-1])
    assert not any("image_hash" in str(m.content) or "image_path" in str(m.content) for request in client.received for m in request)


def test_model_text_cannot_assert_found(setup_agent):
    make,_=setup_agent
    agent,_=make([response("query_memory",{"object_id":"O1"}),response(content="FOUND 在B bbox [0,0,100,100]")])
    result=agent.run("我说找到就必须找到")
    assert result["verified_result"]["result_status"]=="UNKNOWN"
    assert result["verified_result"]["location"] is None
    assert agent.report.evidence==[]


@pytest.mark.parametrize("name,args",[("shell",{"cmd":"x"}),("query_memory",{"object_id":7}),("query_memory",{"object_id":"O1","status":"FOUND"}),("verify_visual",{}),("navigate_and_observe",{"viewpoint_id":"V99"})])
def test_invalid_tools_do_not_create_evidence(setup_agent,name,args):
    make,memory=setup_agent
    agent,_=make([response(name,args),response(content="不能执行")])
    result=agent.run("找盒子")
    assert result["verified_result"]["result_status"]=="UNKNOWN"
    assert memory.query_memory("box")==[]
    assert any(e["kind"]=="tool" and "error" in e["result"] for e in result["trace"])


def test_unknown_uses_model_explanation_after_tool(setup_agent):
    make,_=setup_agent
    agent,client=make([response("unresolved_target",{"reason":"unknown","candidate_ids":[]}),response(content="没有登记耳机壳")])
    result=agent.run("找耳机壳")
    assert result["status"]=="UNKNOWN_OBJECT" and result["explanation"]=="没有登记耳机壳"
    assert len(client.received)==2


def test_ambiguity_does_not_navigate(setup_agent):
    make,memory=setup_agent
    memory.register_object("box2",None,"盒子")
    agent,_=make([response("unresolved_target",{"reason":"ambiguous","candidate_ids":["O1","O2"]}),response(content="需要哪一个盒子？")])
    result=agent.run("找盒子")
    assert result["status"]=="CLARIFY" and agent.core is None


def test_api_exception_no_fallback_or_secret_output(setup_agent):
    make,_=setup_agent
    agent,_=make([TimeoutError("private-prompt SECRET-TOKEN")])
    result=agent.run("找盒子")
    assert result["status"]=="MODEL_UNAVAILABLE"
    assert "SECRET-TOKEN" not in str(result)
    assert agent.core is None


@pytest.mark.parametrize("budget",[{"max_model_calls":1},{"max_tool_calls":1},{"max_total_tokens":256}])
def test_budgets_stop_loop(setup_agent,budget):
    make,_=setup_agent
    agent,_=make([response("list_registered_objects") for _ in range(10)],**budget)
    assert agent.run("找盒子")["status"]=="BUDGET_EXCEEDED"


def test_view_budget(setup_agent):
    make,_=setup_agent
    agent,_=make([response("query_memory",{"object_id":"O1"}),response("navigate_and_observe",{"viewpoint_id":"V1"}),response("verify_visual"),response("navigate_and_observe",{"viewpoint_id":"V2"})],max_viewpoints=1)
    result=agent.run("找盒子")
    assert result["status"]=="BUDGET_EXCEEDED" and result["verified_result"]["attempted_viewpoints"]==["V1"]


def test_missing_usage_fail_closed(setup_agent):
    make,_=setup_agent
    agent,_=make([AIMessage(content="未提供计费字段")])
    assert agent.run("找盒子")["status"]=="AGENT_FAILED"


def test_catalog_rejects_private_paths(setup_agent):
    make,memory=setup_agent
    memory.register_object("unsafe",None,"C:/private/key.jpg")
    with pytest.raises(ValueError,match="Catalog alias"):
        make([])


def test_invalid_provider_tool_json_is_not_success(setup_agent):
    make,_=setup_agent
    malformed=AIMessage(content="",invalid_tool_calls=[{"name":"verify_visual","args":"{bad","id":"bad","error":"json"}],usage_metadata={"input_tokens":90,"output_tokens":10,"total_tokens":100})
    agent,_=make([response("query_memory",{"object_id":"O1"}),malformed])
    assert agent.run("找盒子")["status"]=="AGENT_FAILED"


def test_next_observation_does_not_reuse_previous_detection(setup_agent):
    make,_=setup_agent
    agent,_=make([response("query_memory",{"object_id":"O1"}),response("navigate_and_observe",{"viewpoint_id":"V1"}),response("verify_visual"),response("navigate_and_observe",{"viewpoint_id":"V2"}),response(content="停止")])
    result=agent.run("找盒子")
    observations=[e["result"] for e in result["trace"] if e["kind"]=="tool" and e["name"]=="navigate_and_observe"]
    assert "last_view_status" not in observations[-1] and "last_detection" not in observations[-1]
