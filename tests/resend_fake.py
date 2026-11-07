"""Servidor HTTP falso (só 127.0.0.1) que imita POST /emails da API do Resend: sucesso, 401, 429, redirect e travado."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silêncio
        pass

    def do_POST(self):
        srv = self.server
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with srv.lock:
            srv.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                 "ctype": self.headers.get("Content-Type"), "json": json.loads(body or b"{}")})
        if srv.mode == "hang":
            srv.release.wait(30)
            return
        status, payload = {"ok": (200, {"id": "abc"}),
                           "401": (401, {"name": "missing_api_key", "message": "chave RECUSADA ecoando re_FAKE"}),
                           "429": (429, {"name": "rate_limit_exceeded", "message": "devagar"}),
                           "redirect": (307, {})}[srv.mode]
        self.send_response(status)
        if srv.mode == "redirect":
            self.send_header("Location", f"http://127.0.0.1:{srv.server_address[1]}/outro")
        data = json.dumps(payload).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeResendAPI(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mode: str = "ok"):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = mode
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        self.release = threading.Event()
        self._t = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/emails"

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.shutdown()
        self.server_close()
