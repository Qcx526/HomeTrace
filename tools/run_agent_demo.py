"""Run a real Agent scenario headlessly, preserving local evidence."""
import argparse
import json
from pathlib import Path
import time

from hometrace.agent_service import AgentService

parser = argparse.ArgumentParser()
parser.add_argument("--goal",required=True)
parser.add_argument("--scenario",choices=["moved","missing","replay","fair"],default="moved")
parser.add_argument("--config",type=Path)
parser.add_argument("--output-dir",type=Path,required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
if not args.output_dir.resolve().is_relative_to(root/"artifacts"):
    parser.error("Real Agent traces must remain in local artifacts/")
service = AgentService(root/"examples/recorded_images",args.output_dir,config_path=args.config)
run_id = service.start(args.goal,args.scenario)["run_id"]
while True:
    result = service.get(run_id)
    if result["status"] != "RUNNING" and not service.lock.locked():
        break
    time.sleep(0.2)
print(json.dumps({"run_id":run_id,"status":result["status"],"model_calls":result["model_calls"],"tool_calls":result["tool_calls"],"total_tokens":result["total_tokens"],"verified_result":result["verified_result"]},ensure_ascii=False))
raise SystemExit(0 if result["status"] in ("COMPLETED","CLARIFY","UNKNOWN_OBJECT") else 1)
