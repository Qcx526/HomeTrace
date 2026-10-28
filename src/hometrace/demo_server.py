"""Loopback-only standard-library HTTP server for the HomeTrace demo."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit

from .demo_service import DemoBusyError, DemoService
from .recorded import load_recorded_scene
from .household_service import HouseholdConflict, HouseholdService


LEGACY_WEB_FILES = (
    "index.html", "app.js", "style.css", "agent.html", "agent.js", "agent.css",
    "household.html", "household.js", "household.css",
)


def make_server(service: DemoService | None = None, port: int = 8765, *, agent_service=None,
                household_service=None, photo_flow_service=None, legacy_web_dir: Path | None = None) -> ThreadingHTTPServer:
    # Historical pages are source-checkout test fixtures, never installed runtime assets.
    if legacy_web_dir is not None:
        legacy_web_dir = legacy_web_dir.resolve()
        if any(not (legacy_web_dir / name).is_file() or (legacy_web_dir / name).is_symlink()
               for name in LEGACY_WEB_FILES):
            raise ValueError("Legacy web directory must contain the complete historical test fixtures")

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
            if path.startswith('/api/home-flow/'):
                if photo_flow_service is None:
                    self._json({'error': '照片工作区未启用'}, 503)
                    return
                try:
                    if path == '/api/home-flow/config':
                        self._json(photo_flow_service.config())
                    elif match := re.fullmatch(r'/api/home-flow/assets/([0-9a-f]{32})', path):
                        data, mime = photo_flow_service.asset(match.group(1))
                        self._send(data, mime)
                    elif match := re.fullmatch(r'/api/home-flow/runs/([0-9a-f]{32})(/report)?', path):
                        value = photo_flow_service.get(match.group(1))
                        if match.group(2):
                            self._send(json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8', filename='photo-flow-report.json')
                        else:
                            self._json(value)
                    else:
                        self._json({'error': 'Not found'}, 404)
                except (KeyError, ValueError, OSError):
                    self._json({'error': '本地照片或执行记录不可读取'}, 404)
                except sqlite3.Error:
                    self._json({'error': '照片工作区数据库暂不可读取'}, 500)
                return
            if path == '/api/household':
                if household_service is None:
                    self._json({'error': '家庭工作区未启用', 'enabled': False}, 503)
                else:
                    try:
                        self._json(household_service.config())
                    except (sqlite3.Error, OSError, ValueError):
                        self._json({'error': '家庭工作区暂时无法读取，请检查本地数据库'}, 500)
                return
            household_match = re.fullmatch(r'/api/household/sessions/([0-9a-f]{32})', path)
            if household_match:
                if household_service is None:
                    self._json({'error': '家庭工作区未启用'}, 503)
                    return
                try:
                    self._json(household_service.get(household_match.group(1)))
                except KeyError:
                    self._json({'error': '交互记录不存在'}, 404)
                except (sqlite3.Error, OSError, ValueError):
                    self._json({'error': '交互记录无法读取'}, 500)
                return
            if path == "/api/config":
                if service is None:
                    self._json({"enabled": False, "error": "Historical scenario service is disabled"}, 503)
                else:
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
            if legacy_web_dir is not None and (path == "/" or path[1:] in LEGACY_WEB_FILES):
                name = "index.html" if path == "/" else path[1:]
                mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[Path(name).suffix]
                try:
                    self._send((legacy_web_dir / name).read_bytes(), mime + "; charset=utf-8")
                except OSError:
                    self._json({"error": "Historical test fixture unavailable"}, 404)
                return
            static = {"/": ("home-flow.html", "text/html")}
            static.update({f'/home-flow.{ext}': (f'home-flow.{ext}', mime) for ext, mime in
                           [('html', 'text/html'), ('js', 'text/javascript'), ('css', 'text/css')]})
            if path in static:
                name, mime = static[path]
                self._send(files("hometrace").joinpath("web", name).read_bytes(), mime + "; charset=utf-8")
                return
            match = re.fullmatch(r"/api/runs/([0-9a-f]{32})/(images|downloads)/([a-z0-9-]+)", path)
            if match:
                if service is None:
                    self._json({"error": "Historical scenario service is disabled"}, 503)
                    return
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
            household_paths = ('/api/household/enroll', '/api/household/start', '/api/household/act')
            photo_paths = ('/api/home-flow/assets', '/api/home-flow/reference', '/api/home-flow/scene', '/api/home-flow/start', '/api/home-flow/act')
            if self.path not in ("/api/run", "/api/agent/run", *household_paths, *photo_paths):
                self._json({"error": "Not found"}, 404)
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json({"error": "Use application/json"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = (12*1024*1024 if self.path == '/api/home-flow/assets' else 8192
                         if self.path in (*household_paths, *photo_paths) else 4096 if self.path == '/api/agent/run' else 1024)
                if not 0 < length <= limit:
                    raise ValueError("Invalid request length")
                value = json.loads(self.rfile.read(length))
                if self.path in photo_paths:
                    if photo_flow_service is None:
                        self._json({'error': '照片工作区未启用'}, 503)
                        return
                    contracts = {
                        '/api/home-flow/assets': ({'data_base64', 'source_kind'}, set(), photo_flow_service.upload),
                        '/api/home-flow/reference': ({'object_id', 'asset_id', 'roi', 'roi_reviewed'}, set(), photo_flow_service.reference),
                        '/api/home-flow/scene': ({'location_id', 'asset_id'}, set(), photo_flow_service.scene),
                        '/api/home-flow/start': ({'message'}, {'current_location_id'}, photo_flow_service.start),
                        '/api/home-flow/act': ({'run_id', 'version', 'action'}, {'object_id'}, photo_flow_service.act),
                    }
                    required, optional, operation = contracts[self.path]
                    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
                        raise ValueError('照片操作字段不符合合同')
                    self._json(operation(**value))
                    return
                if self.path in household_paths:
                    if household_service is None:
                        self._json({'error': '家庭工作区未启用'}, 503)
                        return
                    if not isinstance(value, dict):
                        raise ValueError('请求必须为JSON对象')
                    if self.path.endswith('/enroll'):
                        if (set(value) != {'object_id', 'name', 'aliases'} or not isinstance(value['aliases'], list)):
                            raise ValueError('登记须提供object_id、name与aliases列表')
                        self._json(household_service.enroll(**value))
                    elif self.path.endswith('/start'):
                        if not {'intent', 'query'} <= set(value) or set(value) - {'intent', 'query', 'location_id', 'reported_at'}:
                            raise ValueError('交互须提供intent、query和可选地点、时间')
                        self._json(household_service.start(**value))
                    else:
                        if not {'session_id', 'version', 'action'} <= set(value) or set(value) - {'session_id', 'version', 'action', 'object_id'}:
                            raise ValueError('操作须提供session_id、version、action和可选object_id')
                        self._json(household_service.act(**value))
                    return
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
                if service is None:
                    self._json({"error": "Historical scenario service is disabled"}, 503)
                    return
                self._json(service.run(value["scenario"], value["strategy"], value.get("case_id", "public")))
            except (DemoBusyError, HouseholdConflict) as exc:
                self._json({"error": str(exc)}, 409)
            except (ValueError, UnicodeError) as exc:
                self._json({"error": str(exc)}, 400)
            except KeyError:
                self._json({'error': '交互记录不存在'}, 404)
            except sqlite3.Error:
                self._json({'error': '本地数据库操作失败，未确认保存成功；请重新读取当前状态'}, 500)
            except ImportError:
                self._json({'error': '照片识别依赖未安装；请安装本项目 vision 可选依赖'}, 503)
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
    parser.add_argument("--legacy-web-dir", type=Path, help="Development only: serve historical pages from tests/fixtures/legacy_web and enable public sample scenarios")
    parser.add_argument("--photo-agent", action="store_true", help="Use real LLM tool decisions in /home-flow.html; never silently falls back to rules")
    parser.add_argument("--config", type=Path, help="Optional Agent config.yaml path")
    parser.add_argument('--household-dir', type=Path, default=Path('artifacts/household'),
                        help='Persistent private household workspace; reuse across restarts')
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.port <= 65535:
            raise ValueError("Port must be between 0 and 65535")
        service = None
        if args.legacy_web_dir is not None or args.agent:
            for name in ("history.json", "moved.json", "missing.json"):
                load_recorded_scene(args.samples_dir / name)
            service = DemoService(args.samples_dir, args.output_dir, case_configs=args.case_config)
        elif args.case_config:
            raise ValueError("--case-config requires the explicit historical demo mode")
        agent_service = None
        if args.agent:
            from .agent_service import AgentService
            agent_service = AgentService(args.samples_dir,args.output_dir/"agent",config_path=args.config)
        household_service = HouseholdService(args.household_dir)
        from .photo_flow_service import PhotoFlowService
        if args.photo_agent:
            from .photo_agent_service import PhotoAgentService
            photo_flow_service = PhotoAgentService(household_service, config_path=args.config)
        else:
            photo_flow_service = PhotoFlowService(household_service)
        with make_server(service, args.port, agent_service=agent_service, household_service=household_service,
                         photo_flow_service=photo_flow_service, legacy_web_dir=args.legacy_web_dir) as server:
            print(f"HomeTrace demo: http://127.0.0.1:{server.server_port}", flush=True)
            print("Uploaded photographs + simulated navigation. Appearance candidates require owner review.", flush=True)
            if service is not None:
                print(f"Historical run evidence: {service.output_dir}", flush=True)
            if args.legacy_web_dir is not None:
                print("Development mode: historical test pages are explicitly enabled.", flush=True)
            print(f"Photo flow: http://127.0.0.1:{server.server_port}/home-flow.html (appearance candidates + owner review)", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f"HomeTrace demo error: {exc}", file=sys.stderr)
        return 2
    return 0
