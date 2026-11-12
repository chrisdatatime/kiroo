"""Aba Administrador (/api/admin/*) e camada única admin_ops (CLI + site): 404 para quem não é admin, CSRF/Origin,
reautenticação recente, limites por lançamento e por dia, teto da plataforma, idempotência, auditoria append-only,
IDOR, segredos fora do log/auditoria, ações só da CLI e métricas internas sem dados pessoais."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from studio import cli
from studio.admin_ops import CLI, Actor, AdminOps, Forbidden
from studio.config import load_settings
from studio.credits import Ledger
from studio.db import Database, now
from studio.metrics import internal_metrics
from studio.ratelimit import RateLimitConfig, Rule
from studio.web.server import App

from .conftest import FAKE_KEY, login_app

PW = "senha-forte-123"
ORIGIN = "http://127.0.0.1:8765"


class Client:
    def __init__(self, app, email, password=PW):
        self.app, self.h = app, {}
        self.me = login_app(app, self.h, email=email, password=password)
        self.token = app.token

    def get(self, path):
        r = self.app.handle("GET", path, self.h, b"")
        return r.status, (json.loads(r.body) if r.body else None), r

    def post(self, path, body=None, *, token=True, origin=ORIGIN, extra=None):
        h = {**self.h, **({"X-Studio-Token": self.token} if token else {}), **({"Origin": origin} if origin else {}),
             **(extra or {})}
        r = self.app.handle("POST", path, h, json.dumps(body if body is not None else {}).encode())
        return r.status, (json.loads(r.body) if r.body else None), r


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in ("STUDIO_ADMIN_MAX_GRANT", "STUDIO_ADMIN_DAILY_GRANT_CAP", "STUDIO_ADMIN_REAUTH_MINUTES",
              "STUDIO_MONTHLY_CAP_USD", "STUDIO_ENV"):
        monkeypatch.delenv(v, raising=False)


def make_app(settings, tmp_path, **kw):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    return App(8765, settings_loader=loader, sim_pacing=False, **kw)


@pytest.fixture
def world(settings, tmp_path):
    app = make_app(settings, tmp_path)
    admin = Client(app, "operador@exemplo.com")          # o primeiro do banco vira admin (como a CLI faria)
    ana = Client(app, "ana@exemplo.com")
    bia = Client(app, "bia@exemplo.com")
    assert admin.me["admin"] and not ana.me["admin"] and not bia.me["admin"]
    return app, admin, ana, bia


def uid_of(settings, email):
    db = Database(settings.db_path)
    try:
        return db.conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    finally:
        db.close()


def balance(settings, email):
    db = Database(settings.db_path)
    try:
        wid = db.conn.execute("SELECT w.id FROM workspaces w JOIN users u ON u.id=w.owner_id WHERE u.email=?", (email,)).fetchone()[0]
        return Ledger(db).balance(wid)
    finally:
        db.close()


def workspace(settings, email):
    db = Database(settings.db_path)
    try:
        return dict(db.conn.execute("SELECT w.* FROM workspaces w JOIN users u ON u.id=w.owner_id WHERE u.email=?", (email,)).fetchone())
    finally:
        db.close()


def audit_rows(settings):
    db = Database(settings.db_path)
    try:
        return [dict(r) for r in db.conn.execute("SELECT * FROM admin_audit ORDER BY id")]
    finally:
        db.close()


def age_session(settings, minutes):
    """Envelhece todas as sessões (login e reautenticação) para testar a exigência de login recente."""
    old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    db = Database(settings.db_path)
    try:
        db.conn.execute("UPDATE sessions SET created_at=?, reauth_at=NULL", (old,))
    finally:
        db.close()


def admin_routes(uid):
    gets = ["/api/admin/overview", "/api/admin/accounts", f"/api/admin/accounts/{uid}/statement", "/api/admin/invites",
            "/api/admin/metrics", "/api/admin/audit", "/api/admin", "/api/admin/nada"]
    posts = ["/api/admin/reauth", "/api/admin/invites", "/api/admin/invites/inv_0123456789/revoke",
             *[f"/api/admin/accounts/{uid}/{a}" for a in ("allow-real", "deny-real", "set-mode", "set-cap", "grant", "adjust",
                                                          "verify-email", "reset-link", "export", "delete", "promote")]]
    return gets, posts


# ------------------------------------------------------------------ visibilidade e 404
def test_non_admin_and_anonymous_get_404_on_every_admin_route(world, settings):
    app, admin, ana, bia = world
    uid_b = uid_of(settings, "bia@exemplo.com")
    gets, posts = admin_routes(uid_b)
    body = {"credits": 50, "reason": "x", "idempotency_key": "chave-12345678", "usd": 1, "mode": "real", "days": 3,
            "password": PW}
    for p in gets:
        assert ana.get(p)[0] == 404, p
        assert app.handle("GET", p, {"Host": "127.0.0.1:8765"}, b"").status == 404, p
    for p in posts:
        st, data, _ = ana.post(p, body)
        assert st == 404 and data == {"error": "não encontrado"}, p
        assert app.handle("POST", p, {"Host": "127.0.0.1:8765", "Origin": ORIGIN}, b"{}").status == 404, p
    # nada mudou para a Bia (IDOR pela rota de admin)
    assert balance(settings, "bia@exemplo.com") == 0
    assert workspace(settings, "bia@exemplo.com")["allow_real"] == 0
    # o front decide a aba por /api/me.admin: falso para quem não é admin
    assert ana.get("/api/me")[1]["admin"] is False and admin.get("/api/me")[1]["admin"] is True
    assert audit_rows(settings) == []   # quem não é admin nem chega à camada de serviço


def test_admin_responses_are_no_store(world):
    _app, admin, _a, _b = world
    _st, _d, r = admin.get("/api/admin/accounts")
    assert r.status == 200 and "no-store" in r.headers["Cache-Control"] and "private" in r.headers["Cache-Control"]
    assert r.headers["Pragma"] == "no-cache"
    _st, _d, r = admin.post("/api/admin/invites", {"days": 1}, token=False)   # até a recusa vem sem cache
    assert r.status == 403 and "no-store" in r.headers["Cache-Control"]


def test_admin_list_has_the_requested_columns(world, settings):
    _app, admin, _a, _b = world
    st, data, _ = admin.get("/api/admin/accounts")
    assert st == 200
    ana = next(a for a in data["accounts"] if a["email"] == "ana@exemplo.com")
    for k in ("email", "name", "workspace", "mode", "allow_real", "monthly_cap_usd", "balance", "held", "email_verified"):
        assert k in ana
    assert "pw_hash" not in json.dumps(data) and "scrypt" not in json.dumps(data)


# ------------------------------------------------------------------ CSRF / Origin
@pytest.mark.parametrize("variant", ["sem_token", "token_errado", "sem_origin", "origin_outro", "cross_site"])
def test_csrf_is_refused_and_nothing_changes(world, settings, variant):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    kw = {"sem_token": {"token": False}, "token_errado": {"extra": {"X-Studio-Token": "x" * 32}},
          "sem_origin": {"origin": None}, "origin_outro": {"origin": "https://evil.example"},
          "cross_site": {"extra": {"Sec-Fetch-Site": "cross-site"}}}[variant]
    st, data, _ = admin.post(f"/api/admin/accounts/{uid}/allow-real", {"reason": "teste"}, **kw)
    assert st == 403 and data["code"] == "csrf"
    assert workspace(settings, "ana@exemplo.com")["allow_real"] == 0


# ------------------------------------------------------------------ reautenticação
def test_sensitive_actions_require_recent_login_or_reauth(world, settings):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    age_session(settings, 30)
    st, data, _ = admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 10, "reason": "beta", "idempotency_key": "k-reauth-0001"})
    assert st == 403 and data["code"] == "reauth_required" and balance(settings, "ana@exemplo.com") == 0
    assert admin.get("/api/admin/overview")[1]["reauth"]["ok"] is False
    st, data, _ = admin.post("/api/admin/reauth", {"password": "senha-errada-99"})
    assert st == 403 and data["code"] == "reauth_failed"
    st, _d, _ = admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 10, "reason": "beta", "idempotency_key": "k-reauth-0001"})
    assert st == 403
    assert admin.post("/api/admin/reauth", {"password": PW})[0] == 200
    st, data, _ = admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 10, "reason": "beta", "idempotency_key": "k-reauth-0001"})
    assert st == 200 and balance(settings, "ana@exemplo.com") == 1000
    rows = [r for r in audit_rows(settings) if r["action"] == "reauth"]
    assert [r["result"] for r in rows] == ["refused", "ok"]
    assert all(PW not in json.dumps(r) and "senha-errada-99" not in json.dumps(r) for r in audit_rows(settings))


def test_reauth_respects_turnstile_when_enabled(world, settings, monkeypatch):
    app, admin, _a, _b = world
    age_session(settings, 30)
    app.turnstile_on, app.turnstile_secret = True, "segredo-turnstile-teste"
    called = []
    monkeypatch.setattr("studio.turnstile.verify", lambda *a, **k: called.append(1) or "invalid")
    st, data, _ = admin.post("/api/admin/reauth", {"password": PW})
    assert called and st == 400 and data["code"] == "captcha_invalido"
    assert admin.get("/api/admin/overview")[1]["reauth"]["ok"] is False


def test_google_only_admin_must_sign_in_with_google_again(world, settings):
    _app, admin, _a, _b = world
    db = Database(settings.db_path)
    db.conn.execute("UPDATE users SET pw_hash='!', google_sub='g-123' WHERE email='operador@exemplo.com'")
    db.close()
    age_session(settings, 30)
    st, data, _ = admin.post("/api/admin/reauth", {"password": PW})
    assert st == 400 and data["code"] == "google_reauth"
    ov = admin.get("/api/admin/overview")[1]
    assert ov["me"]["has_password"] is False and ov["reauth"]["ok"] is False
    # entrar de novo pelo Google cria uma sessão nova = login recente (o passo equivalente)
    db = Database(settings.db_path)
    db.conn.execute("UPDATE sessions SET created_at=?", (now(),))
    db.close()
    assert admin.get("/api/admin/overview")[1]["reauth"]["ok"] is True


# ------------------------------------------------------------------ limites
def test_grant_limit_per_operation_and_cli_bypass(world, settings, monkeypatch):
    _app, admin, _a, _b = world
    monkeypatch.setenv("STUDIO_ADMIN_MAX_GRANT", "200")
    uid = uid_of(settings, "ana@exemplo.com")
    st, data, _ = admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 200.01, "reason": "x", "idempotency_key": "k-max-00001"})
    assert st == 403 and "CLI" in data["error"] and balance(settings, "ana@exemplo.com") == 0
    st, _d, _ = admin.post(f"/api/admin/accounts/{uid}/adjust", {"credits": -250, "reason": "x", "idempotency_key": "k-max-00002",
                                                                  "confirm_email": "ana@exemplo.com"})
    assert st == 403
    assert admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 200, "reason": "x", "idempotency_key": "k-max-00003"})[0] == 200
    refused = [r for r in audit_rows(settings) if r["result"] == "refused"]
    assert len(refused) == 2 and all(r["actor_kind"] == "web" for r in refused)
    # pela CLI não há limite por lançamento
    args = argparse.Namespace(acao="grant-credits", email="ana@exemplo.com", name="", admin=False, credits=5000, note="lote",
                              days=None, id=None, yes=False, mode=None, usd=None)
    assert cli._admin(settings, args) == 0 and balance(settings, "ana@exemplo.com") == 520000


def test_daily_cap_per_admin(world, settings, monkeypatch):
    _app, admin, _a, _b = world
    monkeypatch.setenv("STUDIO_ADMIN_MAX_GRANT", "200")
    monkeypatch.setenv("STUDIO_ADMIN_DAILY_GRANT_CAP", "300")
    ana, bia = uid_of(settings, "ana@exemplo.com"), uid_of(settings, "bia@exemplo.com")
    assert admin.post(f"/api/admin/accounts/{ana}/grant", {"credits": 200, "reason": "x", "idempotency_key": "k-day-000001"})[0] == 200
    st, data, _ = admin.post(f"/api/admin/accounts/{bia}/grant", {"credits": 150, "reason": "x", "idempotency_key": "k-day-000002"})
    assert st == 403 and "diário" in data["error"] and balance(settings, "bia@exemplo.com") == 0
    # ajuste positivo conta no limite; ajuste negativo não libera limite
    assert admin.post(f"/api/admin/accounts/{ana}/adjust", {"credits": -50, "reason": "x", "idempotency_key": "k-day-000003",
                                                              "confirm_email": "ana@exemplo.com"})[0] == 200
    assert admin.post(f"/api/admin/accounts/{bia}/adjust", {"credits": 101, "reason": "x", "idempotency_key": "k-day-000004"})[0] == 403
    assert admin.post(f"/api/admin/accounts/{bia}/grant", {"credits": 100, "reason": "x", "idempotency_key": "k-day-000005"})[0] == 200
    ov = admin.get("/api/admin/overview")[1]
    assert ov["limits"]["used_today_cc"] == 30000 and ov["limits"]["left_today_cc"] == 0


def test_account_cap_never_above_platform(world, settings, monkeypatch):
    _app, admin, _a, _b = world
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    uid = uid_of(settings, "ana@exemplo.com")
    for bad in (5.01, 100, -1, "abc", None):
        st, _d, _ = admin.post(f"/api/admin/accounts/{uid}/set-cap", {"usd": bad, "reason": "x"})
        assert st == 400, bad
    assert workspace(settings, "ana@exemplo.com")["monthly_cap_usd"] == 0
    st, data, _ = admin.post(f"/api/admin/accounts/{uid}/set-cap", {"usd": 5, "reason": "x"})
    assert st == 200 and data["monthly_cap_usd"] == 5 and data["effective_cap_usd"] == 5
    assert sum(r["action"] == "set-cap" and r["result"] == "refused" for r in audit_rows(settings)) == 5


# ------------------------------------------------------------------ idempotência e confirmação
def test_grant_is_idempotent(world, settings):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    body = {"credits": 30, "reason": "beta", "idempotency_key": "duplo-clique-0001"}
    s1, d1, _ = admin.post(f"/api/admin/accounts/{uid}/grant", body)
    s2, d2, _ = admin.post(f"/api/admin/accounts/{uid}/grant", body)
    assert s1 == s2 == 200 and d1["duplicate"] is False and d2["duplicate"] is True and d1["entry_id"] == d2["entry_id"]
    assert balance(settings, "ana@exemplo.com") == 3000
    st, _d, _ = admin.post(f"/api/admin/accounts/{uid}/grant", {**body, "credits": 31})
    assert st == 409 and balance(settings, "ana@exemplo.com") == 3000
    assert admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 30, "reason": "beta"})[0] == 400   # sem chave
    assert [r["result"] for r in audit_rows(settings) if r["action"] == "grant"] == ["ok", "duplicate", "refused", "refused"]


def test_negative_adjust_requires_typing_the_target_email(world, settings):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 50, "reason": "x", "idempotency_key": "k-neg-000001"})
    for typed in ("", "bia@exemplo.com"):
        st, data, _ = admin.post(f"/api/admin/accounts/{uid}/adjust", {"credits": -20, "reason": "estorno",
                                                                        "idempotency_key": f"k-neg-{len(typed)}-000002", "confirm_email": typed})
        assert st == 400 and "e-mail" in data["error"]
    st, data, _ = admin.post(f"/api/admin/accounts/{uid}/adjust", {"credits": -20, "reason": "estorno",
                                                                    "idempotency_key": "k-neg-000003", "confirm_email": "ANA@exemplo.com"})
    assert st == 200 and balance(settings, "ana@exemplo.com") == 3000
    assert admin.post(f"/api/admin/accounts/{uid}/grant", {"credits": 5, "idempotency_key": "k-neg-000004"})[0] == 400  # motivo


# ------------------------------------------------------------------ auditoria
def test_audit_is_written_with_before_after_reason_and_ip_and_is_append_only(world, settings):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    assert admin.post(f"/api/admin/accounts/{uid}/allow-real", {"reason": "cliente beta"}, extra={"_Peer": "203.0.113.9"})[0] == 200
    row = audit_rows(settings)[-1]
    assert row["action"] == "allow-real" and row["actor_kind"] == "web" and row["actor_email"] == "operador@exemplo.com"
    assert row["target_email"] == "ana@exemplo.com" and row["reason"] == "cliente beta" and row["result"] == "ok"
    assert json.loads(row["before_json"])["allow_real"] is False and json.loads(row["after_json"])["allow_real"] is True
    assert row["at"] and row["ip"]
    db = Database(settings.db_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="somente inclusão"):
            db.conn.execute("UPDATE admin_audit SET reason='apagado'")
        with pytest.raises(sqlite3.DatabaseError, match="somente inclusão"):
            db.conn.execute("DELETE FROM admin_audit")
    finally:
        db.close()
    assert audit_rows(settings)[-1]["reason"] == "cliente beta"
    # a tela de auditoria só lê: não há rota que escreva nela
    assert admin.post("/api/admin/audit", {"id": row["id"]})[0] == 404
    entries = admin.get("/api/admin/audit")[1]["entries"]
    assert entries[0]["action"] == "allow-real" and entries[0]["before"]["allow_real"] is False


def test_cli_actions_are_audited_too(settings):
    db = Database(settings.db_path)
    try:
        from studio.accounts import Accounts
        uid, _ = Accounts(db).create_user("ze@exemplo.com", PW)
        AdminOps(db, CLI).grant(uid, 1000, "lote grande")
        row = db.conn.execute("SELECT * FROM admin_audit ORDER BY id DESC").fetchone()
        assert row["actor_kind"] == "cli" and row["action"] == "grant" and row["amount_cc"] == 100000
    finally:
        db.close()


def test_self_change_is_allowed_but_needs_reason_and_is_highlighted(world, settings, monkeypatch):
    _app, admin, _a, _b = world
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    me = uid_of(settings, "operador@exemplo.com")
    st, data, _ = admin.post(f"/api/admin/accounts/{me}/set-cap", {"usd": 5})
    assert st == 400 and "própria conta" in data["error"]
    st, data, _ = admin.post(f"/api/admin/accounts/{me}/set-cap", {"usd": 5, "reason": "teste do staging"})
    assert st == 200 and data["self_action"] is True
    ok = [r for r in audit_rows(settings) if r["action"] == "set-cap" and r["result"] == "ok"][-1]
    assert ok["self_action"] == 1 and ok["actor_user_id"] == ok["target_user_id"] == me


# ------------------------------------------------------------------ só pela CLI
def test_site_cannot_delete_accounts_or_create_admins(world, settings):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    for action in ("delete", "delete-user", "promote", "make-admin", "create-user"):
        assert admin.post(f"/api/admin/accounts/{uid}/{action}", {"confirm_email": "ana@exemplo.com", "reason": "x"})[0] == 404
    assert admin.post("/api/admin/users", {"email": "novo@exemplo.com", "admin": True})[0] == 404
    db = Database(settings.db_path)
    try:
        assert db.conn.execute("SELECT is_platform_admin FROM users WHERE id=?", (uid,)).fetchone()[0] == 0
        web = AdminOps(db, Actor("web", user_id=uid_of(settings, "operador@exemplo.com")), data_dir=settings.data_dir)
        with pytest.raises(Forbidden):
            web.delete_user(uid)
        assert db.conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone()
        assert db.conn.execute("SELECT result FROM admin_audit WHERE action='delete-user'").fetchone()[0] == "refused"
    finally:
        db.close()


# ------------------------------------------------------------------ segredos
def test_invite_code_and_reset_link_shown_once_and_never_logged(world, settings, caplog):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    with caplog.at_level(logging.DEBUG, logger="studio"):
        st, inv, _ = admin.post("/api/admin/invites", {"days": 3, "note": "beta"})
        st2, rl, _ = admin.post(f"/api/admin/accounts/{uid}/reset-link", {"reason": "pediu por telefone"})
        admin.post("/api/admin/reauth", {"password": PW})
    assert st == 200 and inv["code"].startswith("KIROO-") and st2 == 200 and "?reset=" in rl["link"]
    token = rl["link"].split("?reset=")[1]
    listed = json.dumps(admin.get("/api/admin/invites")[1])
    assert inv["code"] not in listed and inv["id"] in listed
    dump = json.dumps(audit_rows(settings)) + caplog.text + json.dumps(admin.get("/api/admin/audit")[1])
    for secret in (inv["code"], token, PW, FAKE_KEY):
        assert secret not in dump
    log_file = settings.data_dir / "logs" / "studio.log"
    if log_file.exists():
        text = log_file.read_text(encoding="utf-8")
        assert inv["code"] not in text and token not in text
    # revogar
    assert admin.post(f"/api/admin/invites/{inv['id']}/revoke", {})[0] == 200
    assert admin.post(f"/api/admin/invites/{inv['id']}/revoke", {})[0] == 404
    assert admin.post("/api/admin/invites", {"days": 31})[0] == 400


# ------------------------------------------------------------------ IDOR e alvo
def test_admin_actions_hit_only_the_account_in_the_path(world, settings):
    _app, admin, _a, _b = world
    ana = uid_of(settings, "ana@exemplo.com")
    assert admin.post("/api/admin/accounts/usr_0000000000/grant", {"credits": 1, "reason": "x", "idempotency_key": "k-idor-00001"})[0] == 404
    assert admin.post("/api/admin/accounts/../grant", {})[0] == 404
    assert admin.get("/api/admin/accounts/usr_0000000000/statement")[0] == 404
    # o corpo não escolhe o alvo: só o id do caminho vale
    st, _d, _ = admin.post(f"/api/admin/accounts/{ana}/grant", {"credits": 7, "reason": "x", "idempotency_key": "k-idor-00002",
                                                                 "email": "bia@exemplo.com", "workspace_id": "ws_x"})
    assert st == 200 and balance(settings, "ana@exemplo.com") == 700 and balance(settings, "bia@exemplo.com") == 0
    st, data, _ = admin.get(f"/api/admin/accounts/{ana}/statement")
    assert st == 200 and data["account"]["email"] == "ana@exemplo.com" and data["statement"][0]["amount_cc"] == 700


def test_verify_email_mode_and_export_through_the_panel(world, settings):
    _app, admin, _a, _b = world
    uid = uid_of(settings, "ana@exemplo.com")
    db = Database(settings.db_path)
    db.conn.execute("UPDATE users SET email_verified_at=NULL WHERE id=?", (uid,))
    db.close()
    assert admin.post(f"/api/admin/accounts/{uid}/set-mode", {"mode": "real"})[0] == 400   # sem allow-real
    assert admin.post(f"/api/admin/accounts/{uid}/allow-real", {})[0] == 200
    assert admin.post(f"/api/admin/accounts/{uid}/set-mode", {"mode": "real"})[0] == 200
    assert admin.post(f"/api/admin/accounts/{uid}/deny-real", {})[0] == 200
    assert workspace(settings, "ana@exemplo.com")["mode"] == "simulated"
    assert admin.post(f"/api/admin/accounts/{uid}/verify-email", {})[0] == 200
    acc = next(a for a in admin.get("/api/admin/accounts")[1]["accounts"] if a["id"] == uid)
    assert acc["email_verified"] is True
    st, data, r = admin.post(f"/api/admin/accounts/{uid}/export", {"reason": "pedido LGPD"})
    assert st == 200 and data["user"]["email"] == "ana@exemplo.com" and "attachment" in r.headers["Content-Disposition"]
    assert "pw_hash" not in json.dumps(data)


def test_admin_rate_limit_is_specific(settings, tmp_path):
    app = make_app(settings, tmp_path, rate_limits=RateLimitConfig(enabled=True, admin=Rule(3, 60)))
    admin = Client(app, "operador@exemplo.com")
    assert [admin.get("/api/admin/accounts")[0] for _ in range(4)] == [200, 200, 200, 429]
    assert admin.get("/api/me")[0] == 200   # o resto do app segue


# ------------------------------------------------------------------ métricas (Parte A)
def _prod(db, pid, mode="real", status="completed"):
    db.conn.execute("INSERT INTO productions(id, status, mode, format_id, product_json, profiles_json, budget_usd, created_at,"
                    " updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, status, mode, "f", json.dumps({"name": "Produto secreto da Ana"}), "{}", 1.0, now(), now()))


def _att(db, pid, scene, kind, cost, *, provider="gemini", status="succeeded", confirmed=None, simulated=0):
    import uuid
    db.conn.execute("INSERT INTO attempts(id, production_id, scene_idx, kind, attempt_no, status, provider, model, simulated,"
                    " input_hash, estimated_cost_usd, confirmed_cost_usd, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, pid, scene, kind, 1, status, provider, "m", simulated, "h", cost, confirmed, now()))


def test_internal_metrics(settings):
    db = Database(settings.db_path)
    try:
        _prod(db, "prod_aaaaaaaaaa")
        _att(db, "prod_aaaaaaaaaa", 1, "image", 0.10)
        _att(db, "prod_aaaaaaaaaa", 1, "image", 0.10, status="failed")
        _att(db, "prod_aaaaaaaaaa", 1, "video", 0.50, confirmed=0.40)
        _att(db, "prod_aaaaaaaaaa", None, "plan", 0.02, provider="anthropic")
        _prod(db, "prod_bbbbbbbbbb", status="paused")
        _att(db, "prod_bbbbbbbbbb", 1, "image", 0.10)
        db.add_event("prod_bbbbbbbbbb", "ops_alert", "ops_budget_reached: x", data={"code": "ops_budget_reached"})
        _prod(db, "prod_cccccccccc", mode="simulated")
        _att(db, "prod_cccccccccc", 1, "image", 0.05, provider="simulated", simulated=1)
        m = internal_metrics(db, days=30)
    finally:
        db.close()
    r = m["real"]
    assert r["productions"] == 2 and r["delivered"] == 1
    assert r["avg_cost_per_delivered_usd"] == pytest.approx(0.62)        # 0.10 + 0.10 + 0.40 (confirmado) + 0.02
    assert r["interrupted_by_ops_budget"] == 1 and r["interrupted_by_ops_budget_pct"] == 50.0
    assert r["avg_attempts_per_scene"] == 2.0                            # (3 na cena 1 de A + 1 na cena 1 de B) / 2
    ops = {x["key"]: x for x in r["by_operation"]}
    assert ops["image"]["calls"] == 3 and ops["image"]["failed"] == 1 and ops["video"]["usd"] == pytest.approx(0.40)
    prov = {x["key"]: x for x in r["by_provider"]}
    assert prov["gemini"]["usd"] == pytest.approx(0.70) and prov["anthropic"]["calls"] == 1
    assert m["simulated"]["productions"] == 1 and m["simulated"]["total_usd"] == pytest.approx(0.05)
    text = json.dumps(m)
    for personal in ("Produto secreto", "@", "prod_", "usr_", "ws_"):
        assert personal not in text


def test_metrics_in_panel_and_cli(world, settings, capsys):
    _app, admin, ana, _b = world
    st, data, _ = admin.get("/api/admin/metrics?days=0")
    assert st == 200 and "real" in data and data["days"] == 0
    assert ana.get("/api/admin/metrics")[0] == 404
    args = argparse.Namespace(acao="metrics", email=None, name="", admin=False, credits=None, note="", days=None, id=None,
                              yes=False, mode=None, usd=None, json=True, limit=50)
    assert cli._admin(settings, args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["days"] == 30 and "@" not in json.dumps(out)
    args.json = False
    assert cli._admin(settings, args) == 0 and "custo médio por vídeo entregue" in capsys.readouterr().out
    args.acao = "audit"
    assert cli._admin(settings, args) == 0
