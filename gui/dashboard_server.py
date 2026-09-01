#!/usr/bin/env python3
"""Serve the read-only workflow analytics dashboard on localhost."""

import argparse
import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse

from server import ApiError, WorkflowWorkspace, build_handler, console, default_workspace


DASHBOARD_ROOT = Path(__file__).resolve().parent / "dashboard"
ASSETS: Dict[str, str] = {
    "/tokens.css": "text/css; charset=utf-8",
    "/styles.css": "text/css; charset=utf-8",
    "/app.js": "text/javascript; charset=utf-8",
}


def read_asset(name: str) -> bytes:
    path = DASHBOARD_ROOT / name.lstrip("/")
    if not path.is_file() or path.parent != DASHBOARD_ROOT:
        raise ApiError(404, "仪表盘资源不存在")
    return path.read_bytes()


def build_dashboard_handler(app: WorkflowWorkspace):
    index_html = read_asset("index.html").decode("utf-8")
    base_handler = build_handler(app, index_html)

    class DashboardHandler(base_handler):
        server_version = "WorkflowDashboard/1.0"

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; img-src 'self' data:; "
                "font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ASSETS:
                try:
                    self._check_host()
                    self._send(200, read_asset(path), ASSETS[path])
                except ApiError as error:
                    self._json(error.status, {"error": error.message})
                except OSError:
                    self._json(500, {"error": "仪表盘资源读取失败"})
                return
            super().do_GET()

        def do_POST(self) -> None:
            """Keep the analytics surface read-only even though it reuses the management API handler."""
            try:
                self._check_host()
                self._json(405, {"error": "只读仪表盘不接受写请求"})
            except ApiError as error:
                self._json(error.status, {"error": error.message})

    return DashboardHandler


def run_self_test(workspace: Path) -> int:
    required = ("index.html", "tokens.css", "styles.css", "app.js", "README.md")
    missing = [name for name in required if not (DASHBOARD_ROOT / name).is_file()]
    if missing:
        raise RuntimeError("missing dashboard assets: " + ", ".join(missing))
    index = (DASHBOARD_ROOT / "index.html").read_text(encoding="utf-8")
    styles = (DASHBOARD_ROOT / "styles.css").read_text(encoding="utf-8")
    if 'id="overview-view"' not in index or 'id="analysis-view"' not in index:
        raise RuntimeError("dashboard views are incomplete")
    if not styles.startswith("/* Hallmark · macrostructure: Workbench"):
        raise RuntimeError("Hallmark stamp is missing")
    app = WorkflowWorkspace(workspace)
    tasks = app.list_tasks()
    print(json.dumps({"ok": True, "assets": list(required), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="工作流本地效率仪表盘")
    parser.add_argument("--workspace", default=str(default_workspace()), help="工作流根目录")
    parser.add_argument("--port", type=int, default=8766, help="本机监听端口")
    parser.add_argument("--self-test", action="store_true", help="检查资源与工作区数据入口")
    args = parser.parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    if args.self_test:
        return run_self_test(workspace)

    app = WorkflowWorkspace(workspace)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_dashboard_handler(app))
    console("Workflow dashboard: http://127.0.0.1:{}/".format(args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console("Workflow dashboard stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
