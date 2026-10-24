"""Local Agent sessions with real model calls and immutable photo snapshots."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4

from .agent_config import AgentConfigError, load_agent_config
from .demo_service import DemoBusyError, DemoService, write_json
from .image_matcher import ImageMatcher
from .memory import SQLiteMemory
from .models import DataSource, NavigationMode, SearchStrategy
from .recorded import RecordedImageAdapter, load_recorded_scene, resolve_image_path
from .search_core import SearchCore


SCENARIOS = [{"id":k,"label":v} for k,v in (("moved","公开盒子正例"),("missing","未确认负例"),("replay","旧图重放保护"),("fair","历史 C 公平对照"))]


class AgentService:
    def __init__(self, samples_dir, output_dir, *, config_path=None):
        self.samples_dir = Path(samples_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True,exist_ok=True)
        self.config_path = config_path
        self.lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.runs = {}
        self.assets = {}

    def config(self):
        return {"scenarios":SCENARIOS,"enabled":True,"notice":"真实 LLM API + 公开记录照片 + 模拟导航。家庭照片识别升级未通过，当前使用 ORB。API Key 仅在本地 .env。"}

    def start(self, goal, scenario):
        if not isinstance(goal,str) or not 1 <= len(goal.strip()) <= 500 or scenario not in {s["id"] for s in SCENARIOS}:
            raise ValueError("Invalid goal or scenario")
        if not self.lock.acquire(blocking=False):
            raise DemoBusyError("Another Agent run is active")
        run_id = uuid4().hex
        with self.state_lock:
            self.runs[run_id] = {"run_id":run_id,"status":"RUNNING","trace":[],"model_calls":0,"tool_calls":0,"total_tokens":0,
                                 "verified_result":{"result_status":"UNKNOWN","location":None,"attempted_viewpoints":[],"confirmed_evidence_ids":[]}}
        threading.Thread(target=self._execute,args=(run_id,goal,scenario),daemon=True).start()
        return {"run_id":run_id}

    def get(self, run_id):
        with self.state_lock:
            return json.loads(json.dumps(self.runs[run_id],ensure_ascii=False))

    def asset(self, run_id, key):
        with self.state_lock:
            path, digest = self.assets[(run_id,key)]
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Agent image changed after observation")
        return path

    def _execute(self, run_id, goal, scenario):
        directory = self.output_dir / run_id
        directory.mkdir()
        try:
            config = load_agent_config(self.config_path)
            # Reuse snapshot safety and the actual P1 registration process.
            helper = DemoService(self.samples_dir,directory / "snapshot")
            helper._check_private_output()
            image_root, hashes = helper._snapshot(directory, "missing" if scenario == "missing" else "moved",helper.cases["public"])
            scene_path = image_root / ("missing.json" if scenario == "missing" else "moved.json")
            if scenario == "fair":
                history = json.loads((image_root/"history.json").read_text(encoding="utf-8"))
                history["observations"][0]["viewpoint_id"] = "C"
                history["observations"][0]["evidence_id"] = "fair-history-C"
                current = json.loads(scene_path.read_text(encoding="utf-8"))
                current["observations"][1]["image_path"],current["observations"][2]["image_path"] = current["observations"][2]["image_path"],current["observations"][1]["image_path"]
                write_json(image_root/"history.json",history)
                write_json(scene_path,current)
                hashes = {name:hashlib.sha256((image_root/name).read_bytes()).hexdigest() for name in hashes}
                write_json(image_root/"input-hashes.json",hashes)
            db = directory / "memory.sqlite3"
            helper._cli(["register","--db",str(db),"--object-id","sample-box","--description","公开样例盒子","--reference","box.png","--scene",str(image_root/"history.json")],directory/"register")
            if scenario == "replay":
                helper._cli(["search","--db",str(db),"--object-id","sample-box","--scene",str(scene_path)],directory/"prior-search")
            if scenario == "fair":
                baseline_db = directory / "fixed.sqlite3"
                helper._cli(["register","--db",str(baseline_db),"--object-id","sample-box","--reference","box.png","--scene",str(image_root/"history.json")],directory/"fixed-register")
                baseline = helper._cli(["search","--db",str(baseline_db),"--object-id","sample-box","--scene",str(scene_path),"--strategy","fixed_order"],directory/"fixed-search")
                write_json(directory/"comparison.json",{"fixed_order":baseline,"same_inputs":hashes,"separate_databases":True,"note":"Controlled public replay only, no general efficiency claim"})
            scene = load_recorded_scene(scene_path)
            with SQLiteMemory(db) as memory:
                # Extra catalog entries demonstrate ambiguity only; never receive synthetic history/detections.
                memory.register_object("catalog-cup-a",None,"杯子")
                memory.register_object("catalog-cup-b",None,"杯子")
                def core_factory(object_id):
                    obj = memory.get_object(object_id)
                    if obj.data_source != DataSource.RECORDED_IMAGE:
                        raise ValueError("This catalog item has no usable image registration")
                    matcher = ImageMatcher(resolve_image_path(image_root,obj.sample_image_path),obj.sample_image_hash,object_id,image_root,reference_roi=obj.reference_roi)
                    return SearchCore(memory,RecordedImageAdapter(scene),matcher,data_source=DataSource.RECORDED_IMAGE,navigation_mode=NavigationMode.SIMULATED)
                from .agent import HomeTraceAgent
                agent = None
                def publish(snapshot):
                    snapshot = {**snapshot,"run_id":run_id,"scenario":scenario,"user_goal":goal,"core_events":[],"images":{},"bbox":None}
                    if not snapshot["trace"] or snapshot["trace"][-1]["kind"] != "state":
                        snapshot["status"] = "RUNNING"
                    if not config.agent.show_tool_trace:
                        snapshot["trace"] = []
                    if agent and agent.core:
                        report = agent.core.build_report(agent.core.state.task_id)
                        snapshot["core_events"] = [asdict(e) for e in report.events]
                        # Core report stays local; only acquired images get registered HTTP URLs.
                        observations = [e.result.get("observation") for e in report.events if e.action == "observe" and e.result.get("observation")]
                        names = {"reference":"box.png"}
                        if observations:
                            names["current"] = observations[-1]["image_path"]
                            current_id = observations[-1]["evidence_id"]
                            match = next((r for r in reversed(report.evidence) if r.observation.evidence_id == current_id),None)
                            snapshot["bbox"] = match.detection.bbox if match else None
                        for key,name in names.items():
                            asset = resolve_image_path(image_root,name)
                            asset_key = key if key == "reference" else f"current-{len(observations)}"
                            with self.state_lock:
                                self.assets[(run_id,asset_key)] = (asset,hashes[name])
                            snapshot["images"][key] = f"/api/agent/runs/{run_id}/images/{asset_key}"
                    with self.state_lock:
                        self.runs[run_id] = snapshot
                    write_json(directory/"session.private.json",snapshot)
                agent = HomeTraceAgent(config,memory,core_factory,on_update=publish)
                result = agent.run(goal)
                if agent.report:
                    write_json(directory/"report.private.json",agent.report.to_dict())
                write_json(directory/"trace.private.json",result)
                if scenario == "fair":
                    comparison = json.loads((directory/"comparison.json").read_text(encoding="utf-8"))
                    comparison["agent"] = result["verified_result"]
                    write_json(directory/"comparison.json",comparison)
            if hashes != {name:hashlib.sha256((image_root/name).read_bytes()).hexdigest() for name in hashes}:
                raise ValueError("Inputs changed during Agent run")
        except Exception as exc:
            code = exc.code if isinstance(exc,AgentConfigError) else "AGENT_FAILED"
            with self.state_lock:
                self.runs[run_id].update(status="MODEL_UNAVAILABLE" if code == "MODEL_UNAVAILABLE" else "AGENT_FAILED",error={"code":code,"error_type":type(exc).__name__})
                write_json(directory/"failure.private.json",self.runs[run_id])
        finally:
            self.lock.release()
