"""Sonda que roda DENTRO do contêiner descartável da verificação (montada em /probe; nunca usada no serviço real).

  python /probe/container_probe.py seed          cria usuário de teste, login, inicia uma produção simulada; imprime {"pid":...}
  python /probe/container_probe.py snapshot      contagens das tabelas, integrity_check e sha256 da mídia (JSON, determinístico)
  python /probe/container_probe.py state PID     run_state, status da produção, tentativas e eventos (JSON)
  python /probe/container_probe.py wait PID      espera a produção terminar ou pausar; imprime o estado final (JSON)
  python /probe/container_probe.py wait-attempts PID N   espera N tentativas registradas

Só stdlib + pacote studio. Usuário/senha de teste fixos e fictícios (conta existe apenas no volume descartável).
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

PORT = int(os.environ.get("STUDIO_PORT") or os.environ.get("PORT") or 8765)
DATA = Path(os.environ.get("STUDIO_DATA_DIR", "/data"))
EMAIL, PASSWORD = "verify@kiroo.test", "senha-descartavel-123"
DONE = ("awaiting_final_review", "completed", "failed", "paused")


def q(sql, *a):
    for i in range(8):
        con = sqlite3.connect(DATA / "studio.sqlite3", timeout=10)
        con.row_factory = sqlite3.Row
        try:
            return con.execute(sql, a).fetchall()
        except sqlite3.OperationalError:
            if i == 7:
                raise
            time.sleep(0.4)
        finally:
            con.close()


class Client:
    def __init__(self):
        self.cookie, self.csrf = "", ""

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
        h = {"X-Studio-Client": "game", "Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.csrf:
            h["X-Studio-Token"] = self.csrf
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0]
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data


def png() -> str:
    from studio.providers.simulated import placeholder_png
    return "data:image/png;base64," + base64.b64encode(placeholder_png("x", 90, 160)).decode()


def seed() -> dict:
    from studio.accounts import Accounts
    from studio.db import Database
    db = Database(DATA / "studio.sqlite3")
    try:
        Accounts(db).create_user(EMAIL, PASSWORD, "Verify", verified=True)
    except Exception:  # noqa: BLE001 - já existe: segue
        pass
    db.close()
    cl = Client()
    st, _ = cl.call("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    assert st == 200, f"login {st}"
    cl.csrf = cl.call("GET", "/api/me")[1]["csrf"]
    st, body = cl.call("POST", "/api/productions", {
        "name": "Copo verificacao", "variant": "azul", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j", "budget": 5,
        "autonomy": "automatico", "files": [{"name": "f.png", "data": png(), "role": "front"}], "start": True})
    assert st == 200, f"criar produção {st}"
    return {"pid": body["pid"]}


def wait_attempts(pid, n, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if q("SELECT COUNT(*) FROM attempts WHERE production_id=?", pid)[0][0] >= n:
            return True
        time.sleep(0.4)
    return False


def state(pid) -> dict:
    rs = q("SELECT state, resume_attempts FROM run_state WHERE production_id=?", pid)
    att = [tuple(r) for r in q("SELECT id, scene_idx, kind, attempt_no, remote_op_id, status FROM attempts WHERE production_id=? ORDER BY created_at, id", pid)]
    ev = [r[0] for r in q("SELECT type FROM events WHERE production_id=? ORDER BY rowid", pid)]
    return {"run_state": rs[0][0] if rs else None, "resume_attempts": rs[0][1] if rs else None,
            "status": q("SELECT status FROM productions WHERE id=?", pid)[0][0], "attempts": att,
            "events": [e for e in ev if e in ("interrupted", "resumed", "resume_abandoned")], "n_attempts": len(att)}


def wait_done(pid, timeout=240) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = state(pid)
            if s["status"] in DONE and s["run_state"] == "idle":
                return s
        except sqlite3.Error:
            pass
        time.sleep(1)
    return state(pid) | {"timeout": True}


def snapshot() -> dict:
    tables = [r[0] for r in q("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1")]
    counts = {t: q(f'select count(*) from "{t}"')[0][0] for t in tables}
    media = {}
    for root, _, files in os.walk(DATA / "productions"):
        for f in sorted(files):
            p = os.path.join(root, f)
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            media[os.path.relpath(p, DATA).replace(os.sep, "/")] = h.hexdigest()
    return {"counts": counts, "integrity_check": q("pragma integrity_check")[0][0], "media": media}


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "seed":
        out = seed()
    elif cmd == "snapshot":
        out = snapshot()
    elif cmd == "state":
        out = state(argv[2])
    elif cmd == "wait":
        out = wait_done(argv[2])
    elif cmd == "wait-attempts":
        out = {"ok": wait_attempts(argv[2], int(argv[3]))}
    else:
        print(__doc__)
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
