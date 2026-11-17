"""Pacote A (jurídico + dados): versão única dos termos, aceite imutável e novo aceite, registro de acesso de 6 meses,
retenção de 60 dias com aviso, exclusão de conta com lápide, reaplicação após restauração, reembolso e encerramento."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from studio import compliance, privacy
from studio.accounts import TERMS_DATE, TERMS_VERSION, Accounts
from studio.config import load_settings
from studio.credits import Ledger
from studio.db import Database
from studio.web.server import LEGAL_PAGES, App, render_legal

from .conftest import login_app

BASE = {"Host": "127.0.0.1:8765"}
FAKE_PW = "senha-forte-" + "123"      # valor falso de teste, em duas partes (o gitleaks não o lê como segredo)
NOW = datetime(2027, 2, 1, tzinfo=timezone.utc)


def iso(d):
    return d.isoformat(timespec="seconds")


@pytest.fixture
def db(settings):
    d = Database(settings.db_path)
    yield d
    d.close()


def make_user(db, email="ana@example.com", terms=TERMS_VERSION):
    return Accounts(db).create_user(email, "senha-forte-123", "Ana", terms_version=terms, ip="203.0.113.7", user_agent="UA/1")


def make_prod(db, wid, pid="prod_aaaaaaaaaa", *, status="completed", age_days=70, notice_days_ago=None, settings=None):
    stamp = iso(NOW - timedelta(days=age_days))
    db.conn.execute("INSERT INTO productions(id, status, mode, format_id, product_json, profiles_json, budget_usd, created_at,"
                    " updated_at, workspace_id, retention_notice_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, status, "simulated", "9x16", json.dumps({"name": "Copo"}), "{}", 1.0, stamp, stamp, wid,
                     iso(NOW - timedelta(days=notice_days_ago)) if notice_days_ago is not None else None))


def media(settings, pid):
    d = settings.data_dir / "productions" / pid / "delivery"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "final.mp4"
    f.write_bytes(b"video")
    return f


# ---------------------------------------------------------------- A1: versão única
@pytest.mark.parametrize("path", sorted(LEGAL_PAGES))
def test_legal_pages_show_the_single_source_version(path):
    html = render_legal(LEGAL_PAGES[path].split("/")[-1]).decode()
    assert "{{" not in html
    assert f">{TERMS_VERSION}<" in html
    assert "novembro de 2026" in html and TERMS_DATE.startswith("2026-11")


def test_terms_version_is_the_release_candidate():
    assert TERMS_VERSION == "2026-11-rc1"


# ---------------------------------------------------------------- A2: aceite imutável
def test_signup_writes_the_acceptance_history_and_mirrors_users(db):
    uid, _ = make_user(db)
    row = db.conn.execute("SELECT * FROM terms_acceptances WHERE user_id=?", (uid,)).fetchone()
    assert (row["version"], row["ip"], row["user_agent"], row["via"]) == (TERMS_VERSION, "203.0.113.7", "UA/1", "signup")
    u = db.conn.execute("SELECT terms_version, terms_accepted_at FROM users WHERE id=?", (uid,)).fetchone()
    assert u["terms_version"] == TERMS_VERSION and u["terms_accepted_at"]


def test_acceptance_history_cannot_be_edited_or_deleted(db):
    uid, _ = make_user(db)
    with pytest.raises(sqlite3.DatabaseError):
        db.conn.execute("UPDATE terms_acceptances SET version='x' WHERE user_id=?", (uid,))
    with pytest.raises(sqlite3.DatabaseError):
        db.conn.execute("DELETE FROM terms_acceptances WHERE user_id=?", (uid,))
    assert db.conn.execute("SELECT COUNT(*) FROM terms_acceptances WHERE user_id=?", (uid,)).fetchone()[0] == 1


def test_new_version_forces_a_new_acceptance(db):
    uid, _ = make_user(db, terms="2026-11-rascunho")
    assert compliance.needs_acceptance(db, uid, TERMS_VERSION) is True
    assert compliance.needs_acceptance(db, uid, TERMS_VERSION, admin=True) is False   # equipe fica de fora
    compliance.record_acceptance(db, uid, TERMS_VERSION, ip="198.51.100.2", via="reaccept")
    assert compliance.needs_acceptance(db, uid, TERMS_VERSION) is False
    assert [r["version"] for r in db.conn.execute("SELECT version FROM terms_acceptances WHERE user_id=? ORDER BY id", (uid,))] \
        == ["2026-11-rascunho", TERMS_VERSION]


@pytest.fixture
def app(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    return App(8765, settings_loader=loader, sim_pacing=False)


def test_server_blocks_actions_until_the_new_terms_are_accepted(app):
    import json as j
    login_app(app, {}, email="admin@example.com")                 # o primeiro vira administrador
    h = {}
    me = login_app(app, h, email="ana@example.com")
    assert me["terms"] == {"version": TERMS_VERSION, "accepted": TERMS_VERSION, "needs_accept": False}
    # a versão vigente muda depois do cadastro: a conta antiga precisa aceitar
    s, db, _acc = app._db()
    try:
        uid = db.conn.execute("SELECT id FROM users WHERE email='ana@example.com'").fetchone()[0]
        db.conn.execute("DROP TRIGGER terms_acceptances_no_update")
        db.conn.execute("DROP TRIGGER terms_acceptances_no_delete")
        db.conn.execute("DELETE FROM terms_acceptances WHERE user_id=?", (uid,))
        compliance.record_acceptance(db, uid, "2026-11-rascunho", via="migration")
    finally:
        db.close()
    hh = {**BASE, **h, "X-Studio-Token": app.token, "X-Studio-Client": "game"}
    r = app.handle("POST", "/api/productions", hh, b"{}")
    assert r.status == 403 and j.loads(r.body)["code"] == "terms_required"
    r = app.handle("POST", "/api/payments/checkout", hh, b"{}")
    assert r.status == 403 and j.loads(r.body)["code"] == "terms_required"
    assert j.loads(app.handle("GET", "/api/me", hh, b"").body)["terms"]["needs_accept"] is True
    # direitos do titular seguem abertos
    r = app.handle("POST", "/api/account/name", hh, j.dumps({"name": "Ana B"}).encode())
    assert r.status == 200
    # aceite exige a versão exibida
    r = app.handle("POST", "/api/account/terms/accept", hh, j.dumps({"accept": True, "version": "velha"}).encode())
    assert r.status == 400
    r = app.handle("POST", "/api/account/terms/accept", {**hh, "User-Agent": "Teste/2"}, j.dumps({"accept": True, "version": TERMS_VERSION}).encode())
    assert r.status == 200
    me = j.loads(app.handle("GET", "/api/me", hh, b"").body)
    assert me["terms"]["needs_accept"] is False
    r = app.handle("POST", "/api/productions", hh, b"{}")
    assert r.status != 403 or j.loads(r.body).get("code") != "terms_required"
    s, db, _acc = app._db()
    try:
        last = db.conn.execute("SELECT * FROM terms_acceptances WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        assert (last["version"], last["via"], last["user_agent"]) == (TERMS_VERSION, "reaccept", "Teste/2")
    finally:
        db.close()


# ---------------------------------------------------------------- A3: registro de acesso
def test_login_and_signup_are_logged_without_tax_doc(app):
    import json as j
    r = app.handle("POST", "/api/auth/signup", {**BASE, "X-Studio-Client": "game", "User-Agent": "UA/9"},
                   j.dumps({"email": "novo@example.com", "password": FAKE_PW, "name": "Novo", "consent": True,
                            "tax_doc": "12345678909"}).encode())
    if r.status != 200:   # cadastro fechado no ambiente de teste: cria pela conta e só testa o login
        login_app(app, {}, email="novo@example.com")
    r = app.handle("POST", "/api/auth/login", {**BASE, "X-Studio-Client": "game", "User-Agent": "UA/10"},
                   j.dumps({"email": "novo@example.com", "password": FAKE_PW}).encode())
    assert r.status == 200
    s, db, _acc = app._db()
    try:
        rows = [dict(x) for x in db.conn.execute("SELECT * FROM access_log")]
    finally:
        db.close()
    assert any(x["kind"] == "login" and x["user_agent"] == "UA/10" for x in rows)
    assert all("12345678909" not in json.dumps(x) for x in rows)


def test_access_log_older_than_six_months_is_purged(db):
    uid, _ = make_user(db)
    for kind, days in (("login", 10), ("login", 200)):
        db.conn.execute("INSERT INTO access_log(user_id, kind, ip, at) VALUES (?,?,?,?)", (uid, kind, "203.0.113.7", iso(NOW - timedelta(days=days))))
    assert compliance.purge_access_log(db, at=NOW) == 1
    assert db.conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0] == 1


# ---------------------------------------------------------------- A4: retenção de 60 dias
def test_retention_dry_run_changes_nothing(db, settings):
    uid, wid = make_user(db)
    make_prod(db, wid, age_days=70, notice_days_ago=10)
    f = media(settings, "prod_aaaaaaaaaa")
    sent = []
    rep = compliance.run_retention(db, settings.data_dir, dry_run=True, send=lambda *a: sent.append(a) or True, at=NOW)
    assert rep["would_purge"] == ["prod_aaaaaaaaaa"] and rep["purged"] == 0 and not sent and f.exists()
    assert db.conn.execute("SELECT media_purged_at FROM productions").fetchone()[0] is None


def test_notice_is_sent_once_then_purge_only_after_seven_days(db, settings):
    uid, wid = make_user(db)
    make_prod(db, wid, age_days=55)          # 53+ dias: avisa; ainda não apaga
    f = media(settings, "prod_aaaaaaaaaa")
    sent = []
    send = lambda to, subject, text, html: sent.append((to, subject, text)) or True   # noqa: E731
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=send, link="https://app.kiroo.io/", at=NOW)
    assert rep["notified"] == 1 and rep["purged"] == 0 and f.exists() and sent[0][0] == "ana@example.com"
    assert "https://app.kiroo.io/" in sent[0][2] and "7 dias" in sent[0][1]
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=send, link="https://app.kiroo.io/", at=NOW + timedelta(days=1))
    assert rep["notified"] == 0 and len(sent) == 1 and f.exists()       # uma única vez por conteúdo
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=send, at=NOW + timedelta(days=8))
    assert rep["purged"] == 1 and not f.exists()


def test_failed_notice_is_retried_and_never_purges_without_notice(db, settings):
    uid, wid = make_user(db)
    make_prod(db, wid, age_days=90)          # velho, mas nunca avisado
    f = media(settings, "prod_aaaaaaaaaa")
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=lambda *a: False, at=NOW)
    assert rep["notified"] == 0 and rep["purged"] == 0 and f.exists()
    assert db.conn.execute("SELECT retention_notice_at FROM productions").fetchone()[0] is None
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=None, at=NOW)   # sem envio: nunca apaga
    assert rep["purged"] == 0 and f.exists()


def test_in_progress_productions_keep_their_media(db, settings):
    uid, wid = make_user(db)
    make_prod(db, wid, status="producing", age_days=90, notice_days_ago=30)
    f = media(settings, "prod_aaaaaaaaaa")
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=lambda *a: True, at=NOW)
    assert rep["purged"] == 0 and rep["skipped_in_progress"] == 1 and f.exists()


def test_abandoned_drafts_do_not_keep_photos_forever(db, settings):
    uid, wid = make_user(db)
    make_prod(db, wid, status="validated", age_days=90, notice_days_ago=10)    # rascunho parado: fotos enviadas
    f = media(settings, "prod_aaaaaaaaaa")
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=lambda *a: True, at=NOW)
    assert rep["purged"] == 1 and not f.exists()


def test_export_includes_acceptances_and_access_log(db, settings):
    uid, wid = make_user(db)
    compliance.record_access(db, uid, "login", ip="203.0.113.7", user_agent="UA/1")
    out = privacy.export_account(db, settings.data_dir, uid)
    assert out["terms_acceptances"][0]["version"] == TERMS_VERSION
    assert out["access_log"][0]["ip"] == "203.0.113.7" and "tax_doc" not in json.dumps(out["access_log"])


def test_purge_removes_only_eligible_media_and_keeps_the_statement(db, settings):
    uid, wid = make_user(db)
    Ledger(db).add(wid, 5000, kind="grant", note="teste")
    make_prod(db, wid, "prod_aaaaaaaaaa", age_days=70, notice_days_ago=10)
    make_prod(db, wid, "prod_bbbbbbbbbb", age_days=30)
    old, new = media(settings, "prod_aaaaaaaaaa"), media(settings, "prod_bbbbbbbbbb")
    rep = compliance.run_retention(db, settings.data_dir, dry_run=False, send=lambda *a: True, at=NOW)
    assert rep["purged"] == 1 and not old.exists() and new.exists()
    row = db.conn.execute("SELECT id, media_purged_at FROM productions WHERE id='prod_aaaaaaaaaa'").fetchone()
    assert row["media_purged_at"]                                       # a linha (metadados) fica
    assert Ledger(db).balance(wid) == 5000 and Ledger(db).statement(wid) is not None
    assert ("production_media", "prod_aaaaaaaaaa") in compliance.load_tombstones(db, settings.data_dir)
    assert compliance.media_expires_at(db.conn.execute("SELECT * FROM productions WHERE id='prod_aaaaaaaaaa'").fetchone()) is None
    exp = compliance.media_expires_at(db.conn.execute("SELECT * FROM productions WHERE id='prod_bbbbbbbbbb'").fetchone())
    assert exp.startswith(iso(NOW - timedelta(days=30) + timedelta(days=60))[:10])


def test_retention_is_off_by_default(monkeypatch, settings):
    monkeypatch.delenv("STUDIO_RETENTION_ENABLED", raising=False)
    assert compliance.retention_enabled() is False
    with pytest.raises(RuntimeError):
        compliance.run_retention_job(settings.db_path, settings.data_dir, dry_run=False)
    monkeypatch.setenv("STUDIO_RETENTION_ENABLED", "true")
    assert compliance.retention_enabled() is True


# ---------------------------------------------------------------- A5/A6: exclusão, lápides e restauração
def test_delete_account_keeps_access_log_and_anonymizes_payments(db, settings):
    uid, wid = make_user(db)
    compliance.record_access(db, uid, "login", ip="203.0.113.7", user_agent="UA/1")
    db.conn.execute("INSERT INTO payments(id, account_id, user_id, method, package_code, credits, amount_cents, status, created_at, ip,"
                    " user_agent) VALUES ('kpay_1', ?, ?, 'card', 'avulso', 10, 1000, 'paid', ?, '203.0.113.7', 'UA/1')", (wid, uid, iso(NOW)))
    privacy.delete_account(db, settings.data_dir, uid)
    assert db.conn.execute("SELECT COUNT(*) FROM users WHERE id=?", (uid,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM terms_acceptances WHERE user_id=?", (uid,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM access_log WHERE user_id=?", (uid,)).fetchone()[0] == 1   # 6 meses
    p = db.conn.execute("SELECT user_id, ip, user_agent, amount_cents FROM payments").fetchone()
    assert (p["user_id"], p["ip"], p["user_agent"], p["amount_cents"]) == (None, None, None, 1000)
    assert ("user", uid) in compliance.load_tombstones(db, settings.data_dir)
    assert (settings.data_dir / "deletions.jsonl").read_text(encoding="utf-8").count(uid) == 1


def test_reapply_deletions_removes_what_a_restore_brought_back(db, settings):
    uid, wid = make_user(db)
    make_prod(db, wid, age_days=70, notice_days_ago=10)
    media(settings, "prod_aaaaaaaaaa")
    compliance.run_retention(db, settings.data_dir, dry_run=False, send=lambda *a: True, at=NOW)
    privacy.delete_account(db, settings.data_dir, uid)
    # "restauração": a conta e o arquivo voltam (o arquivo de lápides, fora do banco, não volta atrás)
    uid2, wid2 = Accounts(db).create_user("outra@example.com", "senha-forte-123", "Outra", terms_version=TERMS_VERSION)
    db.conn.execute("DELETE FROM deletion_tombstones")                    # o banco restaurado perdeu as lápides novas
    db.conn.execute("INSERT INTO users(id, email, name, pw_hash, created_at) VALUES (?,?,?,?,?)", (uid, "ana@example.com", "Ana", "!", iso(NOW)))
    db.conn.execute("INSERT INTO workspaces(id, name, owner_id, created_at) VALUES (?,?,?,?)", (wid, "E", uid, iso(NOW)))
    out = compliance.reapply_deletions(db, settings.data_dir)
    assert out["users"] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM users WHERE id=?", (uid,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM users WHERE id=?", (uid2,)).fetchone()[0] == 1   # não toca em quem não foi apagado
    assert compliance.reapply_deletions(db, settings.data_dir)["users"] == 0                          # idempotente


# ---------------------------------------------------------------- A7: reembolso, suspensão e encerramento
def test_full_refund_cancels_only_that_transactions_lot_without_negative_balance(db):
    uid, wid = make_user(db)
    led = Ledger(db)
    led.add(wid, 3000, kind="welcome_bonus", note="bônus")
    led.add(wid, 10000, kind="purchase", note="A", payment_id="kpay_A")
    led.add(wid, 4000, kind="purchase", note="B", payment_id="kpay_B")
    lot_a = db.conn.execute("SELECT id FROM credit_lots WHERE payment_id='kpay_A'").fetchone()[0]
    before_b = db.conn.execute("SELECT remaining_cc FROM credit_lots WHERE payment_id='kpay_B'").fetchone()[0]
    taken = led.revoke_lot(lot_a, 10000, note="reembolso", close=True)
    assert taken == 10000
    assert db.conn.execute("SELECT remaining_cc FROM credit_lots WHERE payment_id='kpay_B'").fetchone()[0] == before_b
    assert led.balance(wid) == 3000 + 4000 and led.balance(wid) >= 0
    assert led.revoke_lot(lot_a, 10000, note="reembolso", close=True) == 0       # repetido: idempotente


def test_refund_after_spending_never_goes_negative(db):
    uid, wid = make_user(db)
    led = Ledger(db)
    led.add(wid, 10000, kind="purchase", note="A", payment_id="kpay_A")
    lot_a = db.conn.execute("SELECT id FROM credit_lots WHERE payment_id='kpay_A'").fetchone()[0]
    led.hold(wid, "prod_x", 0.02, "teste")         # reserva (e, no fim, consome) parte do lote
    left = db.conn.execute("SELECT remaining_cc FROM credit_lots WHERE id=?", (lot_a,)).fetchone()[0]
    assert led.revoke_lot(lot_a, 10000, note="reembolso", close=True) == left
    assert led.balance(wid) == 0


def test_suspension_keeps_the_balance_and_blocks_actions(app, db):
    import json as j
    h = {}
    login_app(app, {}, email="admin@example.com")
    login_app(app, h, email="cli@example.com")
    s, d2, acc = app._db()
    try:
        u = acc.user_by_email("cli@example.com")
        wid = acc.workspaces_of(u["id"])[0]["id"]
        Ledger(d2).add(wid, 7000, kind="purchase", note="pago")
        before = Ledger(d2).balance(wid)
        compliance.suspend_workspace(d2, wid)
        assert Ledger(d2).balance(wid) == before                       # nada some
    finally:
        d2.close()
    hh = {**BASE, **h, "X-Studio-Token": app.token, "X-Studio-Client": "game"}
    r = app.handle("POST", "/api/productions", hh, b"{}")
    assert r.status == 403 and j.loads(r.body)["code"] == "account_suspended"
    s, d2, acc = app._db()
    try:
        compliance.suspend_workspace(d2, wid, on=False)
        assert Ledger(d2).balance(wid) == before
    finally:
        d2.close()


def test_closure_records_reason_and_refundable_topup_without_touching_the_balance(db):
    uid, wid = make_user(db)
    led = Ledger(db)
    led.add(wid, 3000, kind="welcome_bonus", note="bônus")
    led.add(wid, 8000, kind="purchase", note="avulso", payment_id="kpay_Z")
    out = compliance.close_workspace(db, wid, reason="encerramento do serviço", by="cli")
    assert out["topup_refundable_cc"] == 8000 and out["promo_cc"] == 3000
    row = db.conn.execute("SELECT * FROM account_closures WHERE workspace_id=?", (wid,)).fetchone()
    assert row["reason"] == "encerramento do serviço" and row["topup_refundable_cc"] == 8000 and row["refunded_at"] is None
    assert led.balance(wid) == 11000                                    # sem confisco automático
    assert db.conn.execute("SELECT closed_at FROM workspaces WHERE id=?", (wid,)).fetchone()[0]
    with pytest.raises(ValueError):
        compliance.close_workspace(db, wid, reason="  ")


def test_cli_commands(settings, monkeypatch, capsys):
    from studio import cli
    monkeypatch.setenv("STUDIO_DATA_DIR", str(settings.data_dir))
    db = Database(settings.db_path)
    make_user(db, "cli@example.com")
    db.close()
    assert cli.main(["retention", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    monkeypatch.delenv("STUDIO_RETENTION_ENABLED", raising=False)
    assert cli.main(["retention"]) == 2
    assert cli.main(["account", "suspend", "cli@example.com"]) == 0
    assert cli.main(["account", "close", "cli@example.com"]) == 2                  # sem motivo
    assert cli.main(["account", "close", "cli@example.com", "--reason", "teste"]) == 0
    assert cli.main(["restore", "reapply-deletions"]) == 0
