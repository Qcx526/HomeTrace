"""Loopback-only standard-library HTTP server for the HomeTrace demo."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import mimetypes
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

from .demo_service import DemoBusyError, DemoService
from .recorded import load_recorded_scene


def make_server(service: DemoService, port: int = 8765, *, agent_service=None) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _local(self) -> bool:
            actual_port = self.server.server_port
            allowed = {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"}
            if self.headers.get("Host") not in allowed:
                self._json({"error": "Only the local demo host is accepted"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in allowed}:
                self._json({"error": "Cross-origin requests are not accepted"}, 403)
                return False
            return True

        def _send(self, content: bytes, mime: str, status: int = 200, filename: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(content)

        def _json(self, value: dict, status: int = 200):
            self._send(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def do_GET(self):
            if not self._local():
                return
            path = urlsplit(self.path).path
            if path == "/api/config":
                self._json(service.config())
                return
            if path == "/api/agent/config":
                self._json(agent_service.config() if agent_service else {"enabled":False,"error":"Start demo with --agent"})
                return
            agent_match = re.fullmatch(r"/api/agent/runs/([0-9a-f]{32})(?:/images/(reference|current-[0-9]+))?",path)
            if agent_match and agent_service:
                run_id, key = agent_match.groups()
                try:
                    if key:
                        asset = agent_service.asset(run_id,key)
                        self._send(asset.read_bytes(),mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                    else:
                        self._json(agent_service.get(run_id))
                except (KeyError,OSError,ValueError):
                    self._json({"error":"Agent run or image unavailable"},404)
                return
            static = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            static.update({"/agent.html":("agent.html","text/html"),"/agent.js":("agent.js","text/javascript"),"/agent.css":("agent.css","text/css")})
            if path in static:
                name, mime = static[path]
                self._send(files("hometrace").joinpath("web", name).read_bytes(), mime + "; charset=utf-8")
                return
            match = re.fullmatch(r"/api/runs/([0-9a-f]{32})/(images|downloads)/([a-z0-9-]+)", path)
            if match:
                run_id, kind, key = match.groups()
                try:
                    if kind == "images":
                        asset = service.asset(run_id, key)
                        self._send(asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                    else:
                        asset = service.download(run_id, key)
                        self._send(asset.read_bytes(), "application/json; charset=utf-8", filename=asset.name)
                except (KeyError, OSError):
                    self._json({"error": "Unknown or unavailable run artifact"}, 404)
                except ValueError as exc:
                    self._json({"error": str(exc)}, 409)
                return
            self._json({"error": "Not found"}, 404)

        def do_POST(self):
            if not self._local():
                return
            if self.path not in ("/api/run", "/api/agent/run"):
                self._json({"error": "Not found"}, 404)
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json({"error": "Use application/json"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= (4096 if self.path == "/api/agent/run" else 1024):
                    raise ValueError("Invalid request length")
                value = json.loads(self.rfile.read(length))
                if self.path == "/api/agent/run":
                    if agent_service is None:
                        self._json({"error":"Agent is disabled; start with --agent"},503)
                        return
                    if not isinstance(value,dict) or set(value) != {"goal","scenario"} or not all(isinstance(v,str) for v in value.values()):
                        raise ValueError("Expected goal and scenario strings only")
                    self._json(agent_service.start(value["goal"],value["scenario"]))
                    return
                if not isinstance(value, dict) or set(value) not in ({"scenario", "strategy"}, {"scenario", "strategy", "case_id"}):
                    raise ValueError("Expected scenario, strategy and optional case_id only")
                if not all(isinstance(v, str) for v in value.values()):
                    raise ValueError("Scenario and strategy must be strings")
                self._json(service.run(value["scenario"], value["strategy"], value.get("case_id", "public")))
            except DemoBusyError as exc:
                self._json({"error": str(exc)}, 409)
            except (ValueError, UnicodeError) as exc:
                self._json({"error": str(exc)}, 400)
            except (OSError, subprocess.TimeoutExpired):
                self._json({"error": "Local photo operation failed; inspect the run logs"}, 500)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HomeTrace local visual demo — simulated navigation")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p2-demo"))
    parser.add_argument("--samples-dir", type=Path, default=Path("examples/recorded_images"))
    parser.add_argument("--case-config", type=Path, action="append", default=[], help="Optional private local object configuration; repeat to add cases")
    parser.add_argument("--agent", action="store_true", help="Enable the real API Agent; requires [agent] dependencies and local .env")
    parser.add_argument("--config", type=Path, help="Optional Agent config.yaml path")
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.port <= 65535:
            raise ValueError("Port must be between 0 and 65535")
        for name in ("history.json", "moved.json", "missing.json"):
            load_recorded_scene(args.samples_dir / name)
        service = DemoService(args.samples_dir, args.output_dir, case_configs=args.case_config)
        agent_service = None
        if args.agent:
            from .agent_service import AgentService
            agent_service = AgentService(args.samples_dir,args.output_dir/"agent",config_path=args.config)
        with make_server(service, args.port, agent_service=agent_service) as server:
            print(f"HomeTrace demo: http://127.0.0.1:{server.server_port}", flush=True)
            print("Recorded photographs + simulated navigation. Real execution followed by event playback.", flush=True)
            print(f"Run evidence: {service.output_dir}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f"HomeTrace demo error: {exc}", file=sys.stderr)
        return 2
    return 0
