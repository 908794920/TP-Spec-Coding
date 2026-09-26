# -*- coding: utf-8 -*-
"""Loopback-only HTTP adapter. Run explicitly; never initializes Runtime storage."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
import sys
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

from .service import BASE_ROOT, ReadError, SCHEMA, WorkbenchService, timestamp


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 0, *, instance_id: str | None = None):
        self.service = WorkbenchService(instance_id=instance_id or uuid.uuid4().hex)
        super().__init__(("127.0.0.1", port), WorkbenchHandler)


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer

    def log_request(self, code="-", size="-") -> None:
        # Wiki searches may contain private terms. HTTP diagnostics need the route/status,
        # not another unbounded plaintext query log outside the 90-day usage store.
        if urlsplit(self.path).path.startswith(("/api/wiki/", "/api/knowledge/")):
            self.log_message('"%s %s" %s %s', self.command, urlsplit(self.path).path, code, size)
        else:
            super().log_request(code, size)

    def _send(self, status: int, payload: dict, *, allow: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if allow:
                self.send_header("Allow", "GET")
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            pass  # Navigation may cancel a read; it never requires a retry/write.

    def do_GET(self) -> None:
        path = [unquote(part) for part in urlsplit(self.path).path.strip("/").split("/")]
        service = self.server.service
        try:
            if path == ["api", "health"]:
                result = service.health()
            elif len(path) == 3 and path[:2] == ["api", "skill-documents"]:
                parameters = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                for name in ("path", "allow_disabled"):
                    if len(parameters.get(name, [""])) != 1:
                        raise ReadError("INVALID_QUERY", f"参数不能重复：{name}", 400)
                inspect_disabled = parameters.get("allow_disabled", ["0"])[0]
                if inspect_disabled not in {"0", "1"}:
                    raise ReadError("INVALID_QUERY", "allow_disabled 必须为 0 或 1", 400)
                result = service.skill_document(
                    path[2], parameters.get("path", [""])[0], allow_disabled=inspect_disabled == "1",
                )
            elif path == ["api", "global"]:
                result = service.global_view()
            elif len(path) == 3 and path[:2] == ["api", "wiki"]:
                result = service.wiki_view(path[2], parse_qs(urlsplit(self.path).query, keep_blank_values=True))
            elif len(path) == 3 and path[:2] == ["api", "knowledge"]:
                result = service.knowledge_view(path[2], parse_qs(urlsplit(self.path).query, keep_blank_values=True))
            elif len(path) >= 3 and path[:2] == ["api", "projects"]:
                if len(path) == 3:
                    result = service.project_view(path[2])
                elif len(path) == 5 and path[3] == "tasks":
                    result = service.task_view(path[2], path[4])
                elif len(path) == 6 and path[3] == "tasks" and path[5] == "details":
                    result = service.details_view(path[2], path[4])
                elif len(path) == 6 and path[3] == "tasks" and path[5] == "closeout":
                    result = service.closeout_view(path[2], path[4])
                else:
                    raise ReadError("NOT_FOUND", "接口不存在", 404)
            else:
                raise ReadError("NOT_FOUND", "接口不存在", 404)
            self._send(200, result)
        except ReadError as exc:
            self._send(exc.status, {"schema": SCHEMA, "error": {"code": exc.code, "message": str(exc)},
                                    "failed_at": timestamp()})
        except Exception as exc:
            message = "知识读取失败，未修改索引或日志。" if path[:2] == ["api", "knowledge"] else str(exc)
            self.log_error("read failed: %s: %s", type(exc).__name__, message)
            self._send(500, {"schema": SCHEMA, "error": {"code": "READ_FAILED", "message": message},
                             "failed_at": timestamp()})

    def _read_only(self) -> None:
        self._send(405, {"schema": SCHEMA, "error": {"code": "READ_ONLY", "message": "工作台仅支持 GET 读取"}}, allow=True)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _read_only


def main() -> int:
    parser = argparse.ArgumentParser(description="TP-Spec local read-only workbench API")
    parser.add_argument("--port", type=int, default=0, help="loopback API port; 0 chooses a free port")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        server = WorkbenchServer(args.port, instance_id=os.environ.get("TP_SPEC_WORKBENCH_INSTANCE"))
    except OSError as exc:
        print(f"工作台 API 启动失败（端口 {args.port}）：{exc}", file=sys.stderr)
        return 1
    # One machine-readable readiness record; npm's launcher verifies this same instance.
    print(json.dumps({"event": "workbench-ready", "pid": os.getpid(), "port": server.server_port,
                      "source_root": str(BASE_ROOT), "instance_id": server.service.instance_id}), flush=True)

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
