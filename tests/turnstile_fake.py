"""Cloudflare siteverify falso (só 127.0.0.1): confere o segredo, aceita cada token UMA vez (como a Cloudflare) e simula
falha, demora, 5xx e redirecionamento. Guarda o que recebeu para os testes conferirem secret/response/remoteip."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

SECRET = "0x4AAAAAAA-segredo-FALSO-nao-vazar"
SITE_KEY = "0x4AAAAAAA-site-key-publica"
GOOD = "tok-bom"          # qualquer token que comece com isto vale uma vez


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, payload=None, headers=None):
        data = json.dumps(payload or {}).encode()
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):   # alvo de um redirecionamento: se alguém o segue, fica registrado
        self.server.redirect_hits += 1
        self._send(200, {"success": True})

    def do_POST(self):
        srv: FakeTurnstile = self.server
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()).items()}
        with srv.lock:
            srv.requests.append(form)
            mode = srv.mode
        if mode == "slow":
            time.sleep(1.5)
        if mode == "5xx":
            return self._send(502)
        if mode == "redirect":
            return self._send(302, headers={"Location": f"http://127.0.0.1:{srv.server_address[1]}/ok"})
        if mode == "garbage":
            self.send_response(200); self.send_header("Content-Length", "5"); self.end_headers(); self.wfile.write(b"<html")
            return
        if mode == "bad-secret" or form.get("secret") != SECRET:
            return self._send(200, {"success": False, "error-codes": ["invalid-input-secret"]})
        token = form.get("response", "")
        with srv.lock:
            if not token.startswith(GOOD) or token in srv.used:
                code = "timeout-or-duplicate" if token in srv.used else "invalid-input-response"
                return self._send(200, {"success": False, "error-codes": [code]})
            srv.used.add(token)
        return self._send(200, {"success": True, "hostname": "staging.kiroo.app"})


class FakeTurnstile(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.Lock()
        self.requests: list[dict] = []
        self.used: set[str] = set()
        self.mode = "normal"
        self.redirect_hits = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/turnstile/v0/siteverify"

    def handle_error(self, request, client_address):   # o cliente desistiu (timeout simulado): não é erro do teste
        pass

    def close(self):
        self.shutdown()
        self.server_close()
