"""Cadastro aberto (STUDIO_SIGNUP=open), conta nova em modo REAL sem teto individual, teto GLOBAL da fal.ai e o
backfill da migração 14. Nenhuma rede e nenhum custo: a fal.ai é sempre a simulada, ou a recusa vem antes dela."""

from __future__ import annotations

import base64
import json
import re
import sqlite3

import pytest

from studio import cli, migrations, paid_gate
from studio.accounts import Accounts
from studio.config import load_settings
from studio.credits import Ledger
from studio.db import Database, now
from studio.providers.simulated import placeholder_png
from studio.ratelimit import RateLimitConfig, Rule
from studio.runtime import ServerConfig
from studio.states import ProductionStatus as PS
from studio.web.server import App

from .conftest import requires_ffmpeg

TEST_PASSWORD = "senha-forte-123"   # fictícia, só para contas descartáveis dos testes (allowlist estreita em .gitleaks.toml)
BASE = {"Host": "127.0.0.1:8765"}
CLIENT = {**BASE, "X-Studio-Client": "game"}
PNG = "data:image/png;base64," + base64.b64encode(placeholder_png("x", 540, 960)).decode()
FAL_BODY = {"scene": "home_light", "platform": "shopee_video", "client_request_id": "cliente-0001",
            "files": [{"name": "foto.png", "data": PNG}]}


def _loader(settings, tmp_path):
    return lambda: load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                                 profiles_dir=settings.profiles_dir, x264_preset="ultrafast")


def make_app(settings, tmp_path, signup="open", rate_limits=None):
    return App(8765, settings_loader=_loader(settings, tmp_path), sim_pacing=False, config=ServerConfig(signup=signup),
               rate_limits=rate_limits)


def signup(app, email, invite=None, headers=None):
    body = {"email": email, "password": TEST_PASSWORD, "consent": True}
    if invite is not None:
        body["invite"] = invite
    r = app.handle("POST", "/api/auth/signup", {**CLIENT, **(headers or {})}, json.dumps(body).encode())
    return r, json.loads(r.body)


def ws_of(settings, email):
    db = Database(settings.db_path)
    try:
        acc = Accounts(db)
        u = acc.user_by_email(email)
        return u, acc.workspaces_of(u["id"])[0], Ledger(db).balance(acc.workspaces_of(u["id"])[0]["id"])
    finally:
        db.close()


# ------------------------------------------------------------------ cadastro
def test_open_signup_needs_no_invite_and_the_account_starts_real_without_cap_and_without_credits(settings, tmp_path):
    app = make_app(settings, tmp_path)
    assert json.loads(app.handle("GET", "/api/config", BASE, b"").body)["signup"] == "open"
    r, data = signup(app, "ana@exemplo.com")
    assert r.status == 200, data
    user, ws, balance = ws_of(settings, "ana@exemplo.com")
    assert not user["is_platform_admin"]
    assert (ws["mode"], ws["allow_real"], ws["no_individual_cap"], ws["monthly_cap_usd"]) == ("real", 1, 1, 0)
    assert balance == 0                                         # bônus só depois de confirmar o e-mail
    db = Database(settings.db_path)
    try:
        assert db.conn.execute("SELECT COUNT(*) FROM welcome_bonuses").fetchone()[0] == 0
    finally:
        db.close()


def test_open_signup_still_accepts_a_body_with_an_invite_code(settings, tmp_path):
    r, data = signup(make_app(settings, tmp_path), "bia@exemplo.com", invite="KIROO-QUALQUER-0000")
    assert r.status == 200, data


def test_invite_mode_still_requires_and_accepts_a_valid_code(settings, tmp_path, monkeypatch, capsys):
    app = make_app(settings, tmp_path, signup="invite")
    assert signup(app, "sem@exemplo.com")[0].status == 403
    monkeypatch.setenv("STUDIO_DATA_DIR", str(settings.data_dir))
    assert cli.main(["admin", "create-invite", "--days", "3"]) == 0
    code = re.search(r"convite: (KIROO-[A-Z0-9-]+)", capsys.readouterr().out).group(1)
    r, data = signup(app, "com@exemplo.com", invite=code)
    assert r.status == 200, data
    assert ws_of(settings, "com@exemplo.com")[1]["mode"] == "real"


def test_open_signup_is_limited_per_ip(settings, tmp_path):
    app = make_app(settings, tmp_path, rate_limits=RateLimitConfig(signup=Rule(2, 3600), auth=Rule(100, 60)))
    assert signup(app, "a1@exemplo.com")[0].status == 200
    assert signup(app, "a2@exemplo.com")[0].status == 200
    r, data = signup(app, "a3@exemplo.com")
    assert r.status == 429 and "Retry-After" in r.headers


def test_admin_created_by_cli_is_not_switched_to_real_by_default(settings):
    db = Database(settings.db_path)
    try:
        _, wid = Accounts(db).create_user("adm@exemplo.com", TEST_PASSWORD, admin=True)
        ws = Accounts(db).workspace(wid)
        assert (ws["mode"], ws["no_individual_cap"]) == ("simulated", 0)
    finally:
        db.close()


# ------------------------------------------------------------------ teto efetivo
def test_no_individual_cap_follows_the_platform_cap_and_fails_closed_without_it(monkeypatch):
    monkeypatch.delenv("STUDIO_MONTHLY_CAP_USD", raising=False)
    assert paid_gate.effective_cap(0, True) == 0                # sem teto da plataforma: DEMO, nunca infinito
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "300")
    assert paid_gate.effective_cap(0, True) == 300
    assert paid_gate.effective_cap(5, False) == 5


def test_real_workspace_without_cap_is_real_when_the_platform_has_a_cap(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "300")
    app = make_app(settings, tmp_path)
    signup(app, "ana@exemplo.com")
    s = app.ws_settings(app.settings(), ws_of(settings, "ana@exemplo.com")[1])
    assert (s.mode, s.allow_paid_calls, s.monthly_cap_usd) == ("real", True, 300)


# ------------------------------------------------------------------ servidor: sem crédito e teto global
@pytest.fixture
def real_fal_app(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_VIDEO_ENGINE", "fal")
    monkeypatch.setenv("FAL_KEY", "fal-FAKE-0123456789")
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "300")
    app = make_app(settings, tmp_path)
    r, _ = signup(app, "cliente@exemplo.com")
    cookie = r.headers["Set-Cookie"].split(";")[0]
    me = json.loads(app.handle("GET", "/api/me", {**BASE, "Cookie": cookie}, b"").body)
    app.h = {**BASE, "Cookie": cookie, "X-Studio-Token": me["csrf"]}
    return app


def create(app):
    r = app.handle("POST", "/api/productions", app.h, json.dumps(FAL_BODY).encode())
    return r.status, json.loads(r.body)


def productions(settings):
    db = Database(settings.db_path)
    try:
        return db.conn.execute("SELECT COUNT(*) FROM productions").fetchone()[0]
    finally:
        db.close()


def test_user_without_credits_cannot_start_a_production(real_fal_app, settings):
    code, d = create(real_fal_app)
    assert code == 402 and d.get("insufficient_credits"), d
    assert productions(settings) == 0


def test_global_fal_cap_refuses_before_reserving_or_calling_fal(real_fal_app, settings, monkeypatch):
    _, ws, _ = ws_of(settings, "cliente@exemplo.com")
    db = Database(settings.db_path)
    Ledger(db).add(ws["id"], 10_000, note="teste")
    db.close()
    monkeypatch.setenv("STUDIO_FAL_DAILY_BUDGET_USD", "0.0001")   # menor que o custo de um pacote
    code, d = create(real_fal_app)
    assert code == 409 and d["code"] == "high_demand", d
    assert d["error"] == "Estamos com alta demanda, tente mais tarde. Nada foi cobrado."
    assert productions(settings) == 0
    _, _, balance = ws_of(settings, "cliente@exemplo.com")
    assert balance == 10_000                                     # nada reservado nem debitado
    db = Database(settings.db_path)
    try:
        ev = db.conn.execute("SELECT data_json FROM platform_events WHERE type='fal_budget_refused'").fetchall()
        assert len(ev) == 1 and json.loads(ev[0][0])["window"] == "daily" and json.loads(ev[0][0])["where"] == "create"
        from studio.metrics import internal_metrics
        fb = internal_metrics(db, 30)["fal_budget"]
        assert fb["refused_today"] == 1 and fb["daily_cap_usd"] == 0.0001
    finally:
        db.close()


def test_run_after_the_cap_is_reached_cancels_the_production_and_refunds(real_fal_app, settings, monkeypatch):
    _, ws, _ = ws_of(settings, "cliente@exemplo.com")
    db = Database(settings.db_path)
    Ledger(db).add(ws["id"], 10_000, note="teste")
    db.close()
    code, d = create(real_fal_app)
    assert code == 200, d
    pid = d["pid"]
    assert ws_of(settings, "cliente@exemplo.com")[2] < 10_000                 # reservado
    assert real_fal_app.handle("POST", f"/api/productions/{pid}/confirm", real_fal_app.h, b"{}").status == 200
    monkeypatch.setenv("STUDIO_FAL_DAILY_BUDGET_USD", "0.0001")
    r = real_fal_app.handle("POST", f"/api/productions/{pid}/run", real_fal_app.h, b"{}")
    body = json.loads(r.body)
    assert r.status == 409 and body["code"] == "high_demand" and body["cancelled"] is True
    assert body["error"] == "Estamos com alta demanda, tente mais tarde. Nada foi cobrado."
    assert ws_of(settings, "cliente@exemplo.com")[2] == 10_000                # devolvido inteiro
    db = Database(settings.db_path)
    try:
        assert PS(db.production(pid)["status"]) == PS.CANCELLED
    finally:
        db.close()


def test_monthly_global_cap_counts_only_real_fal_attempts(settings, monkeypatch):
    db = Database(settings.db_path)
    try:
        for i, (kind, provider, sim, usd) in enumerate([("workflow", "fal-workflow", 0, 2.0), ("workflow", "simulated", 1, 50.0),
                                                        ("image", "gemini-api", 0, 50.0)]):
            db.conn.execute("INSERT INTO attempts(id, production_id, kind, attempt_no, status, provider, model, simulated, "
                            "estimated_cost_usd, created_at, input_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (f"att_{i}", "prod_x", kind, 1, "succeeded", provider, "m", sim, usd, now(), f"h{i}"))
        monkeypatch.setenv("STUDIO_FAL_DAILY_BUDGET_USD", "0")       # 0 desliga o diário
        monkeypatch.setenv("STUDIO_FAL_MONTHLY_BUDGET_USD", "3")
        assert paid_gate.fal_budget_block(db, 0.5) is None
        assert paid_gate.fal_budget_block(db, 1.5)["window"] == "monthly"
        monkeypatch.setenv("STUDIO_FAL_MONTHLY_BUDGET_USD", "abc")   # inválido: volta ao padrão alto
        assert paid_gate.fal_monthly_budget() == 300
    finally:
        db.close()


@requires_ffmpeg
def test_global_cap_reached_mid_way_cancels_and_refunds_the_whole_reservation(settings, tmp_path, monkeypatch):
    from .test_fal_flow import funded, new
    from studio.models import ProductInput
    p = tmp_path / "foto.png"
    p.write_bytes(placeholder_png("foto", 540, 960))
    product = ProductInput.model_validate({"name": "", "references": [{"path": str(p), "role": "front"}]})
    o, wid = funded(settings, tmp_path)
    before = Ledger(o.db).balance(wid)
    pid = new(o, product, wid=wid)                                  # criado e reservado com o teto ainda livre
    assert Ledger(o.db).balance(wid) < before                       # a reserva saiu do saldo livre
    monkeypatch.setenv("STUDIO_FAL_DAILY_BUDGET_USD", "0.0001")
    assert o.run(pid) == PS.CANCELLED
    assert o.fal_gen.submit_count == 0                              # a fal.ai nunca foi chamada
    assert Ledger(o.db).balance(wid) == before                      # a reserva volta inteira
    assert Ledger(o.db).pool_state(pid)["used_cc"] == 0


def test_signup_default_limit_is_15_per_hour():
    assert RateLimitConfig.from_env({}).signup == Rule(15, 3600)
    assert RateLimitConfig.from_env({"STUDIO_RATE_SIGNUP": "3/60"}).signup == Rule(3, 60)


# ------------------------------------------------------------------ migração 14
def _legacy_db(path):
    """Banco na versão 13 com contas no DEMO padrão, admin, isenta, mexida pelo admin e já liberada."""
    conn = sqlite3.connect(path, isolation_level=None)
    migrations.migrate(conn, migrations.MIGRATIONS[:13])
    rows = [("usr_demo", "demo@ex.com", 0, "simulated", 0, 0, 0), ("usr_admin", "adm@ex.com", 1, "simulated", 0, 0, 0),
            ("usr_isento", "isento@ex.com", 0, "simulated", 0, 0, 1), ("usr_negado", "negado@ex.com", 0, "simulated", 0, 0, 0),
            ("usr_real", "real@ex.com", 0, "real", 1, 5, 0)]
    for uid, email, admin, mode, allow, cap, exempt in rows:
        conn.execute("INSERT INTO users(id, email, name, pw_hash, is_platform_admin, created_at) VALUES (?,?,?,?,?,?)",
                     (uid, email, email, "!", admin, now()))
        conn.execute("INSERT INTO workspaces(id, name, owner_id, mode, allow_real, monthly_cap_usd, credits_exempt, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", ("ws_" + uid[4:], "e", uid, mode, allow, cap, exempt, now()))
    conn.execute("INSERT INTO admin_audit(at, actor_kind, action, target_workspace_id, result) VALUES (?,?,?,?,?)",
                 (now(), "cli", "deny-real", "ws_negado", "ok"))
    return conn


def _ws(conn, wid):
    return conn.execute("SELECT mode, allow_real, monthly_cap_usd, no_individual_cap FROM workspaces WHERE id=?", (wid,)).fetchone()


def test_backfill_only_touches_default_demo_accounts_and_can_be_reverted(tmp_path):
    conn = _legacy_db(tmp_path / "v13.sqlite3")
    assert migrations.backfill_14_candidates(conn) == [("ws_demo", "demo@ex.com")]   # prévia = o que a migração faz
    assert migrations.migrate(conn)[0] == 14   # a 14 roda primeiro (as seguintes, como a 15 do avatar, vêm depois)
    assert _ws(conn, "ws_demo") == ("real", 1, 0, 1)
    assert _ws(conn, "ws_admin") == ("simulated", 0, 0, 0)          # admin: intocado
    assert _ws(conn, "ws_isento") == ("simulated", 0, 0, 0)         # isento: intocado
    assert _ws(conn, "ws_negado") == ("simulated", 0, 0, 0)         # o admin pôs no DEMO de propósito
    assert _ws(conn, "ws_real") == ("real", 1, 5, 0)                # já tinha teto: segue com ele
    ev = conn.execute("SELECT data_json FROM platform_events WHERE type=?", (migrations.BACKFILL_14_EVENT,)).fetchone()
    assert json.loads(ev[0]) == {"workspaces": ["ws_demo"]}
    assert migrations.migrate(conn) == []                           # idempotente
    assert migrations.revert_backfill_14(conn) == 1
    assert _ws(conn, "ws_demo") == ("simulated", 0, 0, 0)
    assert _ws(conn, "ws_real") == ("real", 1, 5, 0)
    conn.close()


# ------------------------------------------------------------------ admin: tirar e pôr teto
def test_admin_set_cap_and_clear_cap_toggle_the_individual_cap(settings, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "300")
    monkeypatch.setenv("STUDIO_DATA_DIR", str(settings.data_dir))
    db = Database(settings.db_path)
    Accounts(db).create_user("ana@exemplo.com", TEST_PASSWORD)
    db.close()
    assert cli.main(["admin", "set-cap", "--email", "ana@exemplo.com", "--usd", "5"]) == 0
    assert ws_of(settings, "ana@exemplo.com")[1]["no_individual_cap"] == 0
    assert cli.main(["admin", "clear-cap", "--email", "ana@exemplo.com"]) == 0
    assert ws_of(settings, "ana@exemplo.com")[1]["no_individual_cap"] == 1
    assert cli.main(["admin", "list"]) == 0
    assert "sem teto individual" in capsys.readouterr().out
