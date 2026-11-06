"""Teste de ponta a ponta (sem mocks) de desligamento gracioso, queda brusca, retomada e trava de instância.

Sobe `python -m studio ui` de verdade com STUDIO_MODE=simulated numa pasta temporária, cria uma produção simulada pela API,
derruba o processo no meio e sobe de novo. Uso:  python scripts/e2e_shutdown.py
Sinal do desligamento gracioso: SIGTERM em POSIX; no Windows o SIGTERM vira TerminateProcess, então usa CTRL_BREAK_EVENT.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
GRACE = 20
PORT = int(os.environ.get("E2E_PORT", "8793"))
EMAIL, PASSWORD = "e2e@kiroo.test", "senha-forte-123"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FALHOU'}] {name} {detail}", flush=True)


class Client:
    def __init__(self):
        self.cookie, self.csrf = "", ""

    def call(self, method, path, body=None, timeout=15):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
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

    def login(self):
        st, _ = self.call("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
        assert st == 200, st
        self.csrf = self.call("GET", "/api/me")[1]["csrf"]


def start(data: Path, port: int = PORT) -> subprocess.Popen:
    env = {**os.environ, "STUDIO_DATA_DIR": str(data), "STUDIO_MODE": "simulated", "STUDIO_PORT": str(port),
           "STUDIO_SHUTDOWN_GRACE_S": str(GRACE), "STUDIO_POLL_INTERVAL_S": "1"}
    for k in [k for k in env if k in ("STUDIO_ALLOW_PAID_CALLS", "STUDIO_SECURE_COOKIE", "STUDIO_PUBLIC_HOST")]:
        env.pop(k)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen([sys.executable, "-m", "studio", "ui", "--no-browser"], cwd=ROOT, env=env, creationflags=flags,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")


def wait_up(proc, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
            c.request("GET", "/healthz")
            if c.getresponse().status == 200:
                return True
        except OSError:
            time.sleep(0.3)
    return False


def graceful(proc):
    if os.name == "nt":
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGTERM)


def q(data: Path, sql: str, *a):
    # Leitura do banco CONFIRMADO (o SQLite recupera o WAL sozinho). No Windows, logo após um kill, a primeira leitura pode
    # dar "disk I/O error" enquanto o -shm do processo morto é liberado: repete algumas vezes antes de desistir.
    for attempt in range(8):
        con = sqlite3.connect(data / "studio.sqlite3", timeout=10)
        con.row_factory = sqlite3.Row
        try:
            return con.execute(sql, a).fetchall()
        except sqlite3.OperationalError:
            if attempt == 7:
                raise
            time.sleep(0.4)
        finally:
            con.close()


def snapshot(data: Path, pid: str):
    att = [tuple(r) for r in q(data, "SELECT id, scene_idx, kind, attempt_no, remote_op_id FROM attempts WHERE production_id=? ORDER BY created_at", pid)]
    return att


def preserved(before, after) -> tuple[bool, list]:
    """Invariante da retomada sobre tuplas (id, cena, tipo, nº, remote_op_id): toda tentativa confirmada antes da interrupção
    mantém id/cena/tipo/nº; um remote_op_id já confirmado (não nulo) permanece igual; um nulo PODE ganhar valor na retomada
    (created -> submitted) sem trocar o id nem duplicar a operação. Tentativa desaparecida ou op trocada = violação."""
    now = {a[0]: a for a in after}
    bad = []
    for b in before:
        a = now.get(b[0])
        if a is None or a[1:4] != b[1:4] or (b[4] is not None and a[4] != b[4]):
            bad.append((b, a))
    return not bad, bad


def png() -> str:
    from studio.providers.simulated import placeholder_png
    return "data:image/png;base64," + base64.b64encode(placeholder_png("x", 90, 160)).decode()


def wait_for(fn, timeout, step=0.5):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def prod_status(data, pid):
    return q(data, "SELECT status FROM productions WHERE id=?", pid)[0][0]


def run_scenario(label: str, data: Path, abrupt: bool) -> None:
    print(f"\n=== cenário: {label} ===", flush=True)
    proc = start(data)
    assert wait_up(proc), "servidor não subiu"
    cl = Client()
    cl.login()
    st, body = cl.call("POST", "/api/productions", {
        "name": f"Copo {label}", "variant": "azul", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j", "budget": 5,
        "autonomy": "automatico", "files": [{"name": "f.png", "data": png(), "role": "front"}], "start": True})
    assert st == 200, (st, body)
    pid = body["pid"]
    got = wait_for(lambda: q(data, "SELECT COUNT(*) FROM attempts WHERE production_id=?", pid)[0][0] >= 1, 40)
    check(f"{label}: produção em andamento antes do sinal", bool(got), f"({pid}, {prod_status(data, pid)})")
    # O snapshot "antes" é tirado DEPOIS que o processo parou (abaixo): enquanto o servidor vive ele continua gravando
    # (created -> submitted com remote_op_id), então um snapshot anterior ao sinal compara com um estado que já mudou
    # legitimamente. O estado confirmado após a parada é o que a retomada precisa preservar.
    if abrupt:
        t0 = time.time()
        proc.kill()   # equivalente a kill -9 (TerminateProcess no Windows)
        proc.wait(10)
        check(f"{label}: processo morreu de repente", proc.returncode is not None)
        before = snapshot(data, pid)
        state = q(data, "SELECT state FROM run_state WHERE production_id=?", pid)
        check(f"{label}: run_state ficou 'running' (ninguém marcou)", bool(state) and state[0][0] == "running", str(state and state[0][0]))
        lock_free = True
    else:
        # lê readyz em paralelo ao desligamento
        graceful(proc)
        t0 = time.time()
        seen503 = False
        while proc.poll() is None and time.time() - t0 < GRACE + 10:
            try:
                c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=1)
                c.request("GET", "/readyz")
                seen503 = seen503 or c.getresponse().status == 503
            except OSError:
                pass
            time.sleep(0.1)
        took = time.time() - t0
        before = snapshot(data, pid)
        check(f"{label}: /readyz virou 503 durante o desligamento", seen503)
        check(f"{label}: processo saiu dentro da tolerância", proc.poll() is not None and took <= GRACE + 2, f"({took:.1f}s de {GRACE}s)")
        state = q(data, "SELECT state, resume_attempts FROM run_state WHERE production_id=?", pid)
        status = prod_status(data, pid)
        # se a produção já tinha chegado a um portão humano/final, não há o que interromper
        interrupted = bool(state) and state[0][0] == "interrupted"
        ev = [r[0] for r in q(data, "SELECT type FROM events WHERE production_id=?", pid)]
        check(f"{label}: run_state = interrupted", interrupted, f"(state={state and state[0][0]}, status={status})")
        check(f"{label}: evento 'interrupted' no log de eventos", "interrupted" in ev)
    # trava: com o processo morto o lock é solto; com outro vivo, recusa (verificado depois)
    proc2 = start(data)
    ok_up = wait_up(proc2)
    check(f"{label}: nova subida funciona (lock liberado pelo SO)", ok_up)
    if not ok_up:
        print(proc2.stdout.read() if proc2.poll() is not None else "")
        proc2.kill()
        return
    cl2 = Client()
    cl2.login()
    resumed = wait_for(lambda: "resumed" in [r[0] for r in q(data, "SELECT type FROM events WHERE production_id=?", pid)], 20)
    check(f"{label}: evento 'resumed' após subir", bool(resumed))
    done = wait_for(lambda: prod_status(data, pid) in ("awaiting_final_review", "completed", "failed", "paused")
                    and q(data, "SELECT state FROM run_state WHERE production_id=?", pid)[0][0] == "idle", 180, 1)
    final = prod_status(data, pid)
    check(f"{label}: produção retomou e terminou", bool(done) and final in ("awaiting_final_review", "completed"), f"(status={final})")
    after = snapshot(data, pid)
    kept, _bad = preserved(before, after)
    ops = [a[4] for a in after if a[4]]
    keys = [(a[1], a[2], a[3]) for a in after]
    check(f"{label}: tentativas já registradas preservadas (mesmos ids e ops remotas)", kept, f"({len(before)} antes, {len(after)} depois)")
    check(f"{label}: nenhuma etapa duplicada (cena, tipo, nº da tentativa)", len(keys) == len(set(keys)))
    check(f"{label}: nenhuma operação remota duplicada", len(ops) == len(set(ops)))
    # segunda instância na mesma pasta
    proc3 = subprocess.run([sys.executable, "-m", "studio", "ui", "--no-browser"], cwd=ROOT, text=True, encoding="utf-8",
                           errors="replace", capture_output=True, timeout=60,
                           env={**os.environ, "STUDIO_DATA_DIR": str(data), "STUDIO_PORT": str(PORT + 1)})
    msg = (proc3.stdout + proc3.stderr).strip().splitlines()[-1:] or [""]
    check(f"{label}: segunda instância recusada pelo lock", proc3.returncode != 0 and "Outro processo do Kiroo" in msg[0], msg[0][:110])
    graceful(proc2)
    try:
        proc2.wait(GRACE + 10)
    except subprocess.TimeoutExpired:
        proc2.kill()


def main() -> int:
    from studio.accounts import Accounts
    from studio.db import Database
    base = Path(tempfile.mkdtemp(prefix="kiroo-e2e-"))
    for label, abrupt in (("graceful", False), ("kill-9", True)):
        data = base / label
        data.mkdir()
        db = Database(data / "studio.sqlite3")
        acc = Accounts(db)
        uid, wid = acc.create_user(EMAIL, PASSWORD, "E2E", verified=True)
        db.close()
        try:
            run_scenario(label, data, abrupt)
        except AssertionError as exc:
            check(f"{label}: cenário abortado", False, repr(exc))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} verificações ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
