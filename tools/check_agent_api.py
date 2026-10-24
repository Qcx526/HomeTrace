"""Gate 0: real API and SQLite tool roundtrip. No offline model alternative."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from hometrace.agent_config import load_agent_config
from hometrace.agent_model import create_model, response_metrics, safe_model_error
from hometrace.memory import SQLiteMemory


def run(config, directory):
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_core.tools import tool
    directory.mkdir(parents=True, exist_ok=False)
    report = {"gate": 0, "status": "BLOCKED", "provider": "Qianwen AI compatible gateway",
              "model": config.llm.model, "raw_images_sent": False, "external_tracing": False,
              "fixture_notice": "API probe catalog only; no image, navigation or detection evidence", "calls": [], "tools": []}
    try:
        model = create_model(config)
        def invoke(client, messages):
            started = perf_counter()
            try:
                response = client.invoke(messages)
            except Exception as exc:
                report["calls"].append({"latency_ms": round((perf_counter()-started)*1000, 3), **safe_model_error(exc)})
                raise
            report["calls"].append(response_metrics(response, (perf_counter()-started)*1000))
            return response
        text = invoke(model, [HumanMessage(content="请回复 HomeTrace API OK")])
        if not text.content:
            raise ValueError("Empty model text")
        report["plain_text_returned"] = True
        with SQLiteMemory(directory / "probe.sqlite3") as memory:
            memory.register_object("api-probe", None, "协议验证专用登记条目（无图像、无历史）")

            @tool
            def list_registered_objects() -> dict:
                """读取 HomeTrace SQLite 已登记物品目录，不返回图片或路径。"""
                return {"objects": [{"object_id": o.object_id, "alias": o.description} for o in memory.list_objects()]}

            @tool
            def query_memory(object_id: str) -> dict:
                """查询已登记目标历史记录。无记录不能证明物品位置。"""
                if memory.get_object(object_id) is None:
                    return {"status": "UNKNOWN_OBJECT"}
                return {"object_id": object_id, "history_count": len(memory.query_memory(object_id)), "current_status": "UNKNOWN"}

            tools = {t.name: t for t in (list_registered_objects, query_memory)}
            client = model.bind_tools(list(tools.values()))
            messages = [SystemMessage(content="这是 HomeTrace API 能力检查。必须先调用 list_registered_objects，再依据工具返回的真实 object_id 调用 query_memory。收到记忆结果后用中文说明下一步；没有视觉证据绝不宣称找到。不要使用任何假工具结果。"), HumanMessage(content="请检查登记目录并查询其中条目的记忆。")]
            for expected in ("list_registered_objects", "query_memory"):
                response = invoke(client, messages)
                calls = response.tool_calls
                if len(calls) != 1 or calls[0]["name"] != expected or not calls[0].get("id") or not isinstance(calls[0].get("args"), dict):
                    report["capability_error"] = "MODEL_CAPABILITY_UNSUPPORTED"
                    raise ValueError("Tool protocol was not satisfied")
                call = calls[0]
                if (expected == "list_registered_objects" and call["args"] != {}) or (expected == "query_memory" and call["args"] != {"object_id": "api-probe"}):
                    raise ValueError("Unexpected tool arguments")
                result = tools[expected].invoke(call["args"])
                report["tools"].append({"name": expected, "args": call["args"], "tool_call_id": call["id"], "result": result})
                messages += [response, ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"])]
            response = invoke(client, messages)
            report["feedback_decision"] = response.content
            if not response.content or response.tool_calls:
                raise ValueError("Missing final feedback decision")
            report["status"] = "PASSED"
    except Exception as exc:
        report["error"] = safe_model_error(exc)
    (directory / "gate0.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    config = load_agent_config(args.config)
    output = args.output_dir.resolve()
    if not output.is_relative_to(config.project_root / "artifacts"):
        parser.error("Gate 0 outputs must stay in local artifacts/")
    result = run(config, output)
    print(json.dumps({"status": result["status"], "calls": len(result["calls"]), "tools": len(result["tools"]), "error": result.get("error")}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASSED" else 1)
