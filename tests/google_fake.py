"""Google OAuth falso (só 127.0.0.1): faz o papel do navegador na tela de consentimento e serve /token e /userinfo
de verdade por HTTP, conferindo client_id/secret, redirect_uri, código de uso único e PKCE (S256), como o Google faz."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

CLIENT_ID = "cid-teste.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-segredo-FALSO-nao-vazar"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silêncio
        pass

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        srv: FakeGoogle = self.server
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()).items()}
        with srv.lock:
            srv.token_requests.append(form)
            if srv.token_mode == "fail":   # o Google recusa e ainda ecoa o que recebeu (o servidor não pode repassar)
                return self._send(401, {"error": "invalid_client", "error_description": f"bad {form.get('client_secret')} {form.get('code')}"})
            grant = srv.codes.pop(form.get("code", ""), None)   # código vale uma vez
            if (form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET or not grant
                    or form.get("grant_type") != "authorization_code" or form.get("redirect_uri") != grant["redirect_uri"]):
                return self._send(400, {"error": "invalid_grant"})
            verifier = form.get("code_verifier") or ""
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if grant["method"] != "S256" or challenge != grant["challenge"]:
                return self._send(400, {"error": "invalid_grant", "error_description": "PKCE"})
            access = "ya29.FALSO-" + secrets.token_urlsafe(16)
            srv.access[access] = grant["profile"]
        return self._send(200, {"access_token": access, "token_type": "Bearer", "expires_in": 3599, "id_token": "x.y.z"})

    def do_GET(self):
        srv: FakeGoogle = self.server
        auth = self.headers.get("Authorization") or ""
        with srv.lock:
            profile = srv.access.get(auth.removeprefix("Bearer "))
        if not profile:
            return self._send(401, {"error": "invalid_token"})
        return self._send(200, profile)


class FakeGoogle(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.Lock()
        self.codes: dict[str, dict] = {}
        self.access: dict[str, dict] = {}
        self.token_requests: list[dict] = []
        self.token_mode = "ok"
        self._t = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def attach(self, app) -> None:
        app.google_client_id, app.google_client_secret = CLIENT_ID, CLIENT_SECRET
        app.google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth"   # o navegador; ver consent()
        app.google_token_url, app.google_userinfo_url = self.base + "/token", self.base + "/userinfo"

    def consent(self, location: str, profile: dict) -> str:
        """O usuário escolhe a conta no Google: devolve o caminho+query do retorno (o que o navegador abriria)."""
        u = urlparse(location)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        assert q["client_id"] == CLIENT_ID and q["response_type"] == "code"
        code = "4/0FALSO-" + secrets.token_urlsafe(16)
        with self.lock:
            self.codes[code] = {"redirect_uri": q["redirect_uri"], "challenge": q.get("code_challenge"),
                                "method": q.get("code_challenge_method"), "profile": profile}
        cb = urlparse(q["redirect_uri"])
        return f"{cb.path}?{urlencode({'state': q['state'], 'code': code, 'scope': 'openid email profile'})}"

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self.shutdown()
        self.server_close()
