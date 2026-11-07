"""Endurecimento para deploy: cadastro fechado, proxy, health, cabeçalhos, cache, retomada, trava de instância."""

from __future__ import annotations

import gzip
import json
import logging
import threading

import pytest

from studio.config import load_settings
from studio.db import Database
from studio.logs import JsonFormatter
from studio.runtime import InstanceLockError, ServerConfig, acquire_instance_lock, client_ip, release_instance_lock
from studio.web import server as srv
from studio.web.server import App, make_handler

HOST = {"Host": "127.0.0.1:8765"}
CLIENT = {**HOST, "X-Studio-Client": "game"}
SIGNUP = json.dumps({"email": "novo@x.com", "password": "senha-forte-123", "consent": True}).encode()


@pytest.fixture
def loader(settings, tmp_path):
    return lambda: load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                                 profiles_dir=settings.profiles_dir, x264_preset="ultrafast", poll_interval_s=0.0)


@pytest.fixture
def app(loader):
    return App(8765, settings_loader=loader, sim_pacing=False)


def _users(app):
    s, db, _ = app._db()
    try:
        return db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        db.close()


# ------------------------------------------------------------------ cadastro e admin
def test_signup_defaults_to_closed_on_any_host_with_empty_database(app):
    assert app.signup == "closed"
    for host in ("127.0.0.1:8765", "localhost:8765"):
        assert app.handle("POST", "/api/auth/signup", {**CLIENT, "Host": host}, SIGNUP).status == 403
    assert _users(app) == 0   # banco vazio continua vazio: ninguém vira admin por chegar primeiro
    assert json.loads(app.handle("GET", "/api/config", HOST, b"").body)["signup"] == "closed"


def test_signup_closed_ignores_public_host(loader):
    a = App(8765, settings_loader=loader, sim_pacing=False, public_host="app.kiroo.app")
    assert a.handle("POST", "/api/auth/signup", {"Host": "app.kiroo.app", "X-Studio-Client": "game"}, SIGNUP).status == 403


def test_open_signup_never_creates_an_admin(loader):
    a = App(8765, settings_loader=loader, sim_pacing=False, signup="open")
    r = a.handle("POST", "/api/auth/signup", CLIENT, SIGNUP)
    assert r.status == 200 and json.loads(r.body)["admin"] is False
    cookie = r.headers["Set-Cookie"].split(";")[0]
    me = json.loads(a.handle("GET", "/api/me", {**HOST, "Cookie": cookie}, b"").body)
    assert me["admin"] is False and me["workspace"]["allow_real"] is False


def _invite(a) -> str:
    s, db, acc = a._db()
    try:
        return acc.create_invite()[0]
    finally:
        db.close()


def test_invite_mode_needs_a_valid_code(loader):
    a = App(8765, settings_loader=loader, sim_pacing=False, config=ServerConfig(signup="invite"))
    assert a.handle("POST", "/api/auth/signup", CLIENT, SIGNUP).status == 403
    body = json.dumps({"email": "novo@x.com", "password": "senha-forte-123", "invite": _invite(a), "consent": True}).encode()
    assert a.handle("POST", "/api/auth/signup", CLIENT, body).status == 200


def test_bootstrap_admin_has_no_password_and_gets_a_reset_link(loader):
    cfg = ServerConfig(bootstrap_admin_email="dono@kiroo.app", public_host="app.kiroo.app", secure_cookie=True)
    a = App(8765, settings_loader=loader, sim_pacing=False, config=cfg)
    box = []
    a.send_mail = lambda to, subject, text, html=None: box.append((to, text)) or True
    assert a.bootstrap_admin() == "created" and a.bootstrap_admin() == "exists"
    to, text = box[0]
    assert to == "dono@kiroo.app" and "https://app.kiroo.app/?reset=" in text
    s, db, acc = a._db()
    try:
        u = acc.user_by_email("dono@kiroo.app")
        assert u["is_platform_admin"] == 1
        assert not acc.workspaces_of(u["id"])[0]["mode"] == "real"
    finally:
        db.close()
    r = a.handle("POST", "/api/auth/login", {"Host": "app.kiroo.app", "X-Studio-Client": "game"},
                 b'{"email":"dono@kiroo.app","password":"!"}')
    assert r.status == 400   # sem senha até abrir o link
    token = text.split("?reset=")[1].split()[0]
    assert a.handle("POST", "/api/auth/reset", {"Host": "app.kiroo.app", "X-Studio-Client": "game"},
                    json.dumps({"token": token, "password": "senha-do-dono-1"}).encode()).status == 200
    assert a.handle("POST", "/api/auth/login", {"Host": "app.kiroo.app", "X-Studio-Client": "game"},
                    b'{"email":"dono@kiroo.app","password":"senha-do-dono-1"}').status == 200


def test_bootstrap_without_smtp_in_production_does_not_log_the_link(loader, caplog):
    cfg = ServerConfig(bootstrap_admin_email="dono@kiroo.app", public_host="app.kiroo.app", secure_cookie=True)
    a = App(8765, settings_loader=loader, sim_pacing=False, config=cfg)
    import os
    from studio import mailer
    os.environ["STUDIO_SECURE_COOKIE"] = "1"
    os.environ.pop("STUDIO_SMTP_HOST", None)
    try:
        with caplog.at_level(logging.DEBUG, logger="studio"):
            a.bootstrap_admin()
    finally:
        os.environ.pop("STUDIO_SECURE_COOKIE", None)
    assert not mailer.configured()
    text = caplog.text
    assert "?reset=" not in text and "dono@kiroo.app" not in text and "SMTP" in text


def test_code_is_not_logged_in_production_without_smtp(app, caplog, monkeypatch):
    monkeypatch.setenv("STUDIO_SECURE_COOKIE", "1")
    monkeypatch.delenv("STUDIO_SMTP_HOST", raising=False)
    a = App(8765, settings_loader=app.load_settings, sim_pacing=False, signup="open", secure_cookie=True)
    with caplog.at_level(logging.DEBUG, logger="studio"):
        r = a.handle("POST", "/api/auth/signup", CLIENT, SIGNUP)
    assert r.status == 200 and json.loads(r.body)["sent"] is False
    assert "novo@x.com" not in caplog.text and "código de confirmação" not in caplog.text


# ------------------------------------------------------------------ proxy / IP real
def test_client_ip_trusts_headers_only_when_enabled():
    h = {"Cf-Connecting-Ip": "1.2.3.4", "X-Forwarded-For": "5.6.7.8, 9.9.9.9"}
    assert client_ip(h, "none", "10.0.0.1") == "10.0.0.1"
    assert client_ip(h, "cloudflare", "10.0.0.1") == "1.2.3.4"
    assert client_ip(h, "forwarded", "10.0.0.1") == "5.6.7.8"
    assert client_ip({"X-Forwarded-For": "5.6.7.8"}, "cloudflare", "10.0.0.1") == "10.0.0.1"   # header errado não vale
    assert client_ip({"Cf-Connecting-Ip": "lixo"}, "cloudflare", "10.0.0.1") == "10.0.0.1"
    assert client_ip({}, "none") == "local"


def test_app_client_ip_with_case_insensitive_headers(loader):
    cf = App(8765, settings_loader=loader, trust_proxy="cloudflare")
    assert cf._client_ip({"CF-Connecting-IP": "1.2.3.4"}, "10.0.0.1") == "1.2.3.4"
    assert cf._client_ip({"x-forwarded-for": "9.9.9.9"}, "10.0.0.1") == "10.0.0.1"
    fw = App(8765, settings_loader=loader, trust_proxy="forwarded")
    assert fw._client_ip({"x-forwarded-for": "9.9.9.9, 10.1.1.1"}) == "9.9.9.9"
    assert fw._client_ip({"Cf-Connecting-Ip": "1.2.3.4"}, "10.0.0.1") == "10.0.0.1"


@pytest.mark.parametrize("mode,header", [("cloudflare", "CF-Connecting-IP"), ("forwarded", "X-Forwarded-For")])
def test_login_limit_per_ip_works_behind_the_proxy(loader, mode, header):
    a = App(8765, settings_loader=loader, sim_pacing=False, public_host="app.kiroo.app", trust_proxy=mode)
    headers = {"Host": "app.kiroo.app", "X-Studio-Client": "game", header: "1.2.3.4"}
    last = None
    for i in range(9):   # e-mails diferentes: só o limite por IP pode barrar
        last = a.handle("POST", "/api/auth/login", headers,
                        json.dumps({"email": f"x{i}@b.com", "password": "errada-errada"}).encode())
    assert "muitas tentativas" in json.loads(last.body)["error"]
    other = {**headers, header: "8.8.8.8"}   # outro IP não é afetado
    r = a.handle("POST", "/api/auth/login", other, b'{"email":"y@b.com","password":"errada-errada"}')
    assert "incorretos" in json.loads(r.body)["error"]


def test_spoofed_headers_are_ignored_without_trust(loader):
    a = App(8765, settings_loader=loader, sim_pacing=False)   # none
    last = None
    for i in range(9):   # o cliente muda o cabeçalho a cada tentativa, mas o IP do socket é o mesmo
        last = a.handle("POST", "/api/auth/login", {**CLIENT, "CF-Connecting-IP": f"9.9.9.{i}", "X-Forwarded-For": f"8.8.8.{i}"},
                        json.dumps({"email": f"x{i}@b.com", "password": "errada-errada"}).encode(), peer="203.0.113.7")
    assert "muitas tentativas" in json.loads(last.body)["error"]


def test_hosts_and_host_only_secure_cookie_for_app_and_staging(loader):
    cfg = ServerConfig(public_host="app.kiroo.app", allowed_hosts=("app.kiroo.app", "staging.kiroo.app"), secure_cookie=True)
    a = App(8765, settings_loader=loader, sim_pacing=False, config=cfg)
    s, db, acc = a._db()
    acc.create_user("a@b.com", "senha-forte-123")
    db.close()
    for host in ("app.kiroo.app", "staging.kiroo.app", "STAGING.kiroo.app"):
        r = a.handle("POST", "/api/auth/login", {"Host": host, "X-Studio-Client": "game"},
                     b'{"email":"a@b.com","password":"senha-forte-123"}')
        cookie = r.headers["Set-Cookie"]
        assert r.status == 200 and "Secure" in cookie and "HttpOnly" in cookie and "Domain" not in cookie
    assert a.handle("GET", "/api/config", {"Host": "evil.example"}, b"").status == 403


# ------------------------------------------------------------------ health
def test_healthz_does_not_touch_the_database_and_skips_host_check(app):
    r = app.handle("GET", "/healthz", {"Host": "10.0.0.5:8765"}, b"")
    assert r.status == 200 and json.loads(r.body) == {"status": "ok"}
    assert not app.settings().db_path.exists()


def test_readyz_checks_database_and_data_dir(app, loader, tmp_path):
    r = app.handle("GET", "/readyz", {"Host": "10.0.0.5:8765"}, b"")
    assert r.status == 200 and json.loads(r.body)["checks"] == {"db": True, "data_dir": True, "accepting": True}
    assert not list(app.settings().data_dir.glob(".readyz-*"))
    blocked = tmp_path / "arquivo"
    blocked.write_text("x")   # STUDIO_DATA_DIR apontando para um arquivo: não dá para escrever
    bad = App(8765, settings_loader=lambda: __import__("dataclasses").replace(loader(), data_dir=blocked))
    r = bad.handle("GET", "/readyz", HOST, b"")
    assert r.status == 503 and json.loads(r.body)["status"] == "unavailable" and "blocked" not in r.body.decode()
    app.stopping.set()   # em drenagem: tira o nó do balanceador
    assert app.handle("GET", "/readyz", HOST, b"").status == 503


# ------------------------------------------------------------------ cabeçalhos, cache, gzip (servidor real)
@pytest.fixture
def live(loader, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html><body><div id=root></div>" + "x" * 2000 + "</body></html>")
    (dist / "assets" / "index-BO_rcp--.js").write_text("console.log('kiroo');" * 200)
    (dist / "assets" / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>" * 40)
    monkeypatch.setattr(srv, "GAME_DIST", dist)
    a = App(0, settings_loader=loader, sim_pacing=False, secure_cookie=True)
    httpd = srv.StudioHTTPServer(("127.0.0.1", 0), make_handler(a))
    port = httpd.server_address[1]
    a.allowed_hosts = {f"127.0.0.1:{port}"}
    a.port = port
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield a, port
    httpd.shutdown()
    httpd.server_close()


def _get(port, path, headers=None):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    out = (r.status, {k.lower(): v for k, v in r.getheaders()}, body)
    c.close()
    return out


def test_security_headers_on_every_response(live):
    a, port = live
    for path in ("/", "/assets/index-BO_rcp--.js", "/api/me", "/nao-existe", "/healthz"):
        st, h, _ = _get(port, path)
        assert h["x-content-type-options"] == "nosniff", path
        assert h["referrer-policy"] and h["permissions-policy"], path
        assert "frame-ancestors 'none'" in h["content-security-policy"], path
        assert h["strict-transport-security"].startswith("max-age="), path   # STUDIO_SECURE_COOKIE=1
        assert h["x-request-id"]


def test_hsts_only_with_secure_cookie(loader):
    plain = srv.security_headers(False)
    assert "Strict-Transport-Security" not in plain and "Strict-Transport-Security" in srv.security_headers(True)


def test_csp_allows_what_phaser_needs_and_nothing_inline():
    csp = srv.CSP_APP
    assert "script-src 'self';" in csp and "unsafe-eval" not in csp
    for need in ("img-src 'self' data: blob:", "worker-src 'self' blob:", "connect-src 'self' data: blob:", "media-src 'self' blob:"):
        assert need in csp


def test_game_index_and_hashed_assets_load_with_cache_policy_and_gzip(live):
    a, port = live
    st, h, body = _get(port, "/", {"Host": f"127.0.0.1:{port}", "Accept-Encoding": "gzip"})
    assert st == 200 and h["content-encoding"] == "gzip" and h["cache-control"] == "no-cache"
    assert b'<div id=root>' in gzip.decompress(body)
    st, h, body = _get(port, "/assets/index-BO_rcp--.js", {"Accept-Encoding": "gzip"})
    assert st == 200 and h["cache-control"] == "public, max-age=31536000, immutable"
    assert h["content-encoding"] == "gzip" and h["vary"] == "Accept-Encoding" and h["content-type"].startswith("text/javascript")
    assert gzip.decompress(body).startswith(b"console.log")
    st, h, body = _get(port, "/assets/index-BO_rcp--.js")   # sem Accept-Encoding: bytes crus
    assert "content-encoding" not in h and body.startswith(b"console.log")
    st, h, _ = _get(port, "/assets/logo.svg")
    assert h["cache-control"] == "no-cache"   # sem hash no nome: nunca immutable


def test_api_and_media_are_never_cached(live):
    a, port = live
    assert _get(port, "/api/config")[1]["cache-control"] == "no-store"
    assert _get(port, "/api/me")[1]["cache-control"] == "no-store"


def test_media_response_is_private_no_store(app, make_orch, product):
    from .conftest import create, login_app
    hd = {}
    login_app(app, hd)
    s, db, acc = app._db()
    wid = acc.workspaces_of(acc.user_by_email("chris@example.com")["id"])[0]["id"]
    db.close()
    orch = make_orch()
    pid = create(orch, product)
    orch.db.update_production(pid, workspace_id=wid)
    orch.db.close()
    folder = s.data_dir / "productions" / pid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "nota.txt").write_text("oi")
    r = app.handle("GET", f"/media/{pid}/nota.txt", hd, b"")
    assert r.status == 200 and r.headers["Cache-Control"] == "private, no-store"


# ------------------------------------------------------------------ logs JSON
def test_json_logs_have_no_personal_data_and_mask_secrets(live, capsys):
    a, port = live
    logger = logging.getLogger("studio")
    logger.setLevel(logging.INFO)
    records = []
    # A linha "request" é registrada pela thread do servidor DEPOIS de enviar a resposta (finally de _serve): o
    # cliente pode receber o corpo e o teste remover o handler antes dela. Espera o registro chegar, sem afrouxar nada.
    logged = threading.Event()

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(JsonFormatter(["AIzaFAKE-TEST-SECRET-0123456789"]).format(record))
            if record.getMessage() == "request":
                logged.set()

    h = Grab()
    logger.addHandler(h)
    try:
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", "/api/auth/login?token=SEGREDO", body=b'{"email":"alvo@x.com","password":"senha-secreta-1"}',
                  headers={"X-Studio-Client": "game", "Content-Type": "application/json"})
        c.getresponse().read()
        c.close()
        assert logged.wait(10), "a linha de acesso 'request' não foi registrada"
        logger.warning("chave AIzaFAKE-TEST-SECRET-0123456789 vazou")
    finally:
        logger.removeHandler(h)
    line = next(json.loads(r) for r in records if json.loads(r)["msg"] == "request")
    assert {"level", "request_id", "route", "status", "duration_ms", "method"} <= set(line)
    assert line["route"] == "/api/auth/login" and line["status"] == 400
    dump = "\n".join(records)
    for banned in ("alvo@x.com", "senha-secreta-1", "SEGREDO", "AIzaFAKE-TEST-SECRET-0123456789"):
        assert banned not in dump


# ------------------------------------------------------------------ trava de instância
def test_second_instance_on_same_data_dir_is_refused(tmp_path):
    first = acquire_instance_lock(tmp_path / "d")
    try:
        with pytest.raises(InstanceLockError, match="Outro processo do Kiroo"):
            acquire_instance_lock(tmp_path / "d")
    finally:
        release_instance_lock(first)
    again = acquire_instance_lock(tmp_path / "d")   # liberada: pode subir de novo
    release_instance_lock(again)


# ------------------------------------------------------------------ config de ambiente
def test_server_config_from_env():
    c = ServerConfig.from_env({})
    assert (c.host, c.port, c.signup, c.trust_proxy) == ("127.0.0.1", 8765, "closed", "none")
    c = ServerConfig.from_env({"PORT": "9000", "STUDIO_HOST": "0.0.0.0", "STUDIO_TRUST_PROXY": "cloudflare",
                               "STUDIO_ALLOWED_HOSTS": "App.kiroo.app, staging.kiroo.app", "STUDIO_SHUTDOWN_GRACE_S": "10"})
    assert (c.host, c.port, c.trust_proxy, c.shutdown_grace_s) == ("0.0.0.0", 9000, "cloudflare", 10.0)
    assert c.allowed_hosts == ("app.kiroo.app", "staging.kiroo.app")
    assert ServerConfig.from_env({"PORT": "9000", "STUDIO_PORT": "7000"}).port == 7000
    with pytest.raises(ValueError):
        ServerConfig.from_env({"STUDIO_SIGNUP": "aberto"})
    with pytest.raises(ValueError):
        ServerConfig.from_env({"STUDIO_TRUST_PROXY": "tudo"})


# ------------------------------------------------------------------ desligamento e retomada
def _simulated_production(app, make_orch, product):
    from .conftest import create
    orch = make_orch()
    pid = create(orch, product)
    return pid, orch


def _events(app, pid):
    db = Database(app.settings().db_path)
    try:
        return [(e["type"], e["message"]) for e in db.events(pid)]
    finally:
        db.close()


def test_resume_after_simulated_crash_does_not_redo_paid_work(app, make_orch, product):
    pid, orch = _simulated_production(app, make_orch, product)
    orch.db.set_run_state(pid, "running")        # o processo anterior morreu no meio da produção
    orch.db.close()
    assert app.runs == {}
    assert app.resume_pending() == [pid]
    app.runs[pid].join(timeout=60)
    db = Database(app.settings().db_path)
    try:
        status = db.production(pid)["status"]
        assert status == "producing"             # avançou até o primeiro portão humano
        n_attempts = db.conn.execute("SELECT COUNT(*) FROM attempts WHERE production_id=? AND kind='image'", (pid,)).fetchone()[0]
        state = db.conn.execute("SELECT state, resume_attempts FROM run_state WHERE production_id=?", (pid,)).fetchone()
    finally:
        db.close()
    assert n_attempts >= 1 and state["state"] == "idle" and state["resume_attempts"] == 0
    assert any(t == "resumed" for t, _ in _events(app, pid))
    assert app.resume_pending() == []            # nada a retomar: parou num portão humano
    # um segundo reinício no mesmo ponto não gera imagens novas
    db = Database(app.settings().db_path)
    db.set_run_state(pid, "interrupted")
    db.close()
    app.resume_pending()
    app.runs[pid].join(timeout=60)
    db = Database(app.settings().db_path)
    try:
        assert db.conn.execute("SELECT COUNT(*) FROM attempts WHERE production_id=? AND kind='image'", (pid,)).fetchone()[0] == n_attempts
    finally:
        db.close()


def test_resume_gives_up_after_max_attempts_and_pauses(loader, make_orch, product):
    a = App(8765, settings_loader=loader, sim_pacing=False, config=ServerConfig(resume_max_attempts=2))
    pid, orch = _simulated_production(a, make_orch, product)
    orch.db.conn.execute("INSERT INTO run_state(production_id, state, resume_attempts, updated_at) VALUES (?,?,?,?)",
                         (pid, "interrupted", 2, "2026-01-01T00:00:00+00:00"))
    orch.db.close()
    assert a.resume_pending() == []
    db = Database(a.settings().db_path)
    try:
        assert db.production(pid)["status"] == "paused"
        assert db.conn.execute("SELECT state FROM run_state WHERE production_id=?", (pid,)).fetchone()[0] == "abandoned"
    finally:
        db.close()
    assert ("resume_abandoned" in [t for t, _ in _events(a, pid)])


def test_resume_skips_finished_or_paused_productions(app, make_orch, product):
    pid, orch = _simulated_production(app, make_orch, product)
    orch.pause(pid)
    orch.db.set_run_state(pid, "running")
    orch.db.close()
    assert app.resume_pending() == []
    db = Database(app.settings().db_path)
    try:
        assert db.conn.execute("SELECT state FROM run_state WHERE production_id=?", (pid,)).fetchone()[0] == "idle"
    finally:
        db.close()


def test_shutdown_refuses_new_jobs_and_marks_running_as_interrupted(app, make_orch, product):
    pid, orch = _simulated_production(app, make_orch, product)
    orch.db.set_run_state(pid, "running")
    orch.db.close()
    release = threading.Event()
    stuck = threading.Thread(target=release.wait, daemon=True)   # uma etapa longa que não termina dentro da tolerância
    stuck.start()
    app.runs[pid] = stuck
    left = app.shutdown(grace_s=0.2)
    release.set()
    assert left == [pid] and app.stopping.is_set()
    ev = _events(app, pid)
    assert any(t == "interrupted" for t, _ in ev)
    db = Database(app.settings().db_path)
    try:
        assert db.conn.execute("SELECT state FROM run_state WHERE production_id=?", (pid,)).fetchone()[0] == "interrupted"
    finally:
        db.close()
    assert app.start_run(pid) is False           # sem job novo durante o desligamento
    hd = {}
    from .conftest import login_app
    login_app(app, hd)
    r = app.handle("POST", "/api/demo", {**hd, "X-Studio-Token": app.token}, b"{}")
    assert r.status == 503 and r.headers["Retry-After"]


def test_running_loop_stops_between_steps_on_shutdown(loader, make_orch, product):
    a = App(8765, settings_loader=loader, sim_pacing=False)
    pid, orch = _simulated_production(a, make_orch, product)
    orch.db.close()
    a.stopping.set()
    a.stopping.clear()
    gate = threading.Event()
    real_orch_for = a.orch_for

    def slow(pid_):
        o = real_orch_for(pid_)
        original = o._step_scenes

        def step(p):
            gate.set()
            a.stopping.set()   # o SIGTERM chega durante a etapa
            return original(p)
        o._step_scenes = step
        return o

    a.orch_for = slow
    assert a.start_run(pid)
    a.runs[pid].join(timeout=60)
    assert gate.is_set()
    db = Database(a.settings().db_path)
    try:
        state = db.conn.execute("SELECT state FROM run_state WHERE production_id=?", (pid,)).fetchone()[0]
    finally:
        db.close()
    assert state == "interrupted"
    assert any(t == "interrupted" for t, _ in _events(a, pid))


def test_invite_code_is_single_use_and_guessing_is_rate_limited(loader):
    """Código procurado pelo hash (sem comparar com uma lista), uso único e tentativas erradas bloqueadas por IP."""
    a = App(8765, settings_loader=loader, sim_pacing=False, config=ServerConfig(signup="invite"))
    code = _invite(a)
    ok = json.dumps({"email": "a@x.com", "password": "senha-forte-123", "invite": code, "consent": True}).encode()
    assert a.handle("POST", "/api/auth/signup", CLIENT, ok).status == 200
    again = json.dumps({"email": "c@x.com", "password": "senha-forte-123", "invite": code, "consent": True}).encode()
    assert a.handle("POST", "/api/auth/signup", CLIENT, again).status == 403        # já usado
    bad = json.dumps({"email": "b@x.com", "password": "senha-forte-123", "invite": "errado", "consent": True}).encode()
    for _ in range(7):
        assert a.handle("POST", "/api/auth/signup", CLIENT, bad).status == 403
    r = a.handle("POST", "/api/auth/signup", CLIENT, bad)
    assert r.status == 429 and r.headers["Retry-After"]
