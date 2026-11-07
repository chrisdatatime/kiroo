"""Cadastro por convite de uso único (CLI), consentimento, páginas legais e direitos do titular (exportar e apagar)."""

from __future__ import annotations

import base64
import json
import re
import threading

import pytest

from studio import cli
from studio.accounts import TERMS_VERSION, Accounts
from studio.config import load_settings
from studio.db import Database
from studio.providers.simulated import placeholder_png
from studio.runtime import ServerConfig
from studio.web.server import App

from .conftest import login_app

BASE = {"Host": "127.0.0.1:8765"}
CLIENT = {**BASE, "X-Studio-Client": "game"}
PNG = "data:image/png;base64," + base64.b64encode(placeholder_png("x", 90, 160)).decode()
FORM = {"name": "Copo da Ana", "variant": "azul", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j", "budget": 5,
        "files": [{"name": "f.png", "data": PNG, "role": "front"}], "start": False}


@pytest.fixture
def loader(settings, tmp_path):
    return lambda: load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                                 profiles_dir=settings.profiles_dir, x264_preset="ultrafast")


@pytest.fixture
def invite_app(loader):
    return App(8765, settings_loader=loader, sim_pacing=False, config=ServerConfig(signup="invite"))


def make_invite(settings, monkeypatch, capsys, *args) -> str:
    monkeypatch.setenv("STUDIO_DATA_DIR", str(settings.data_dir))
    assert cli.main(["admin", "create-invite", *args]) == 0
    out = capsys.readouterr().out
    return re.search(r"convite: (KIROO-[A-Z0-9-]+)", out).group(1)


def signup(app, email, invite=None, consent=True, password="senha-forte-123"):
    body = {"email": email, "password": password, "consent": consent}
    if invite is not None:
        body["invite"] = invite
    r = app.handle("POST", "/api/auth/signup", CLIENT, json.dumps(body).encode())
    return r, json.loads(r.body)


# ------------------------------------------------------------------ convites
def test_invite_is_single_use_and_hashed(invite_app, settings, monkeypatch, capsys):
    code = make_invite(settings, monkeypatch, capsys, "--days", "3", "--note", "lote 1")
    assert signup(invite_app, "ana@exemplo.com", "KIROO-ERRADO-0000")[0].status == 403
    r, data = signup(invite_app, "ana@exemplo.com", code.lower().replace("-", " "))   # digitado sem capricho
    assert r.status == 200, data
    r, data = signup(invite_app, "bia@exemplo.com", code)
    assert r.status == 403 and "já usado" in data["error"]
    raw = b"".join(p.read_bytes() for p in settings.data_dir.glob("studio.sqlite3*"))
    assert code.encode() not in raw and code.replace("-", "").encode() not in raw   # no banco só o hash
    monkeypatch.setenv("STUDIO_DATA_DIR", str(settings.data_dir))
    assert cli.main(["admin", "list-invites"]) == 0
    assert "usado" in capsys.readouterr().out


def test_invite_expires(invite_app, settings, monkeypatch, capsys):
    code = make_invite(settings, monkeypatch, capsys, "--days", "1")
    db = Database(settings.db_path)
    db.conn.execute("UPDATE invites SET expires_at='2000-01-01T00:00:00+00:00'")
    db.close()
    r, data = signup(invite_app, "ana@exemplo.com", code)
    assert r.status == 403 and "expirado" in data["error"]
    monkeypatch.setenv("STUDIO_DATA_DIR", str(settings.data_dir))
    assert cli.main(["admin", "create-invite", "--days", "90"]) == 2      # validade máxima de 30 dias


def test_invite_for_a_specific_email_and_revoke(invite_app, settings, monkeypatch, capsys):
    code = make_invite(settings, monkeypatch, capsys, "--email", "Ana@Exemplo.com")
    assert signup(invite_app, "outra@exemplo.com", code)[0].status == 403
    assert signup(invite_app, "ana@exemplo.com", code)[0].status == 200
    code2 = make_invite(settings, monkeypatch, capsys)
    inv_id = [r["id"] for r in Accounts(Database(settings.db_path)).invites() if r["used_at"] is None][0]
    assert cli.main(["admin", "revoke-invite", "--id", inv_id]) == 0
    assert signup(invite_app, "caio@exemplo.com", code2)[0].status == 403


def test_failed_signup_gives_the_invite_back_and_no_consent_does_not_spend_it(invite_app, settings, monkeypatch, capsys):
    code = make_invite(settings, monkeypatch, capsys)
    r, data = signup(invite_app, "ana@exemplo.com", code, consent=False)
    assert r.status == 400 and "Termos de Uso" in data["error"]
    assert signup(invite_app, "ana@exemplo.com", code, password="curta")[0].status == 400   # senha fraca
    assert signup(invite_app, "ana@exemplo.com", code)[0].status == 200                    # convite ainda valia


def test_two_signups_racing_for_one_invite(settings, monkeypatch, capsys):
    code = make_invite(settings, monkeypatch, capsys)
    wins, barrier = [], threading.Barrier(8)

    def go():
        db = Database(settings.db_path)
        try:
            barrier.wait()
            wins.append(Accounts(db).claim_invite(code, "x@exemplo.com"))
        finally:
            db.close()
    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([w for w in wins if w]) == 1


def test_legacy_env_invite_codes_no_longer_work(loader):
    app = App(8765, settings_loader=loader, sim_pacing=False,
              config=ServerConfig(signup="invite", invite_codes=("convite-antigo-1",)))
    assert signup(app, "ana@exemplo.com", "convite-antigo-1")[0].status == 403


# ------------------------------------------------------------------ consentimento e páginas
def test_consent_is_required_and_recorded(loader, settings):
    app = App(8765, settings_loader=loader, sim_pacing=False, signup="open")
    for bad in (False, None, "sim", 1):
        r, data = signup(app, "ana@exemplo.com", consent=bad)
        assert r.status == 400 and "Política de Privacidade" in data["error"]
    assert signup(app, "ana@exemplo.com")[0].status == 200
    db = Database(settings.db_path)
    u = db.conn.execute("SELECT terms_accepted_at, terms_version FROM users WHERE email='ana@exemplo.com'").fetchone()
    db.close()
    assert u["terms_accepted_at"] and u["terms_version"] == TERMS_VERSION
    assert json.loads(app.handle("GET", "/api/auth/config", BASE, b"").body)["terms_version"] == TERMS_VERSION


@pytest.mark.parametrize("path,title", [("/termos", "Termos de Uso"), ("/privacidade", "Política de Privacidade")])
def test_legal_pages_are_public_drafts(loader, path, title):
    app = App(8765, settings_loader=loader, sim_pacing=False)
    r = app.handle("GET", path, BASE, b"")
    html = r.body.decode()
    assert r.status == 200 and r.content_type.startswith("text/html")
    assert title in html and "PARA REVISÃO JURÍDICA" in html and "<script" not in html


# ------------------------------------------------------------------ exportar e apagar
@pytest.fixture
def two_users(loader):
    app = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(app, {}, email="operador@exemplo.com")   # primeiro do banco = admin
    a, b = {}, {}
    login_app(app, a, email="ana@exemplo.com")
    tok_a = app.token
    login_app(app, b, email="bia@exemplo.com")
    tok_b = app.token
    pa = json.loads(app.handle("POST", "/api/productions", {**a, "X-Studio-Token": tok_a}, json.dumps(FORM).encode()).body)["pid"]
    pb = json.loads(app.handle("POST", "/api/productions", {**b, "X-Studio-Token": tok_b},
                               json.dumps({**FORM, "name": "Copo da Bia"}).encode()).body)["pid"]
    return app, (a, tok_a, pa), (b, tok_b, pb)


def test_export_own_data_only(two_users):
    app, (a, _, pa), (_, _, pb) = two_users
    r = app.handle("GET", "/api/account/export", a, b"")
    assert r.status == 200 and "attachment" in r.headers["Content-Disposition"]
    data = json.loads(r.body)
    text = r.body.decode()
    assert data["user"]["email"] == "ana@exemplo.com"
    assert [p["id"] for w in data["workspaces"] for p in w["productions"]] == [pa]
    assert data["workspaces"][0]["productions"][0]["product_json"]["name"] == "Copo da Ana"
    assert pb not in text and "Copo da Bia" not in text and "bia@exemplo.com" not in text
    for forbidden in ("pw_hash", "scrypt$", "token_hash", "csrf", "code_hash"):
        assert forbidden not in text


def test_delete_own_account_removes_data_and_files(two_users, settings):
    app, (a, tok_a, pa), (b, tok_b, pb) = two_users
    post = lambda body: app.handle("POST", "/api/account/delete", {**a, "X-Studio-Token": tok_a}, json.dumps(body).encode())  # noqa: E731
    assert post({"password": "senha-forte-123"}).status == 400                          # sem a palavra de confirmação
    assert post({"password": "errada-errada", "confirm": "APAGAR"}).status == 403
    db = Database(settings.db_path)
    refs = [r["path"] for r in json.loads(db.production(pa)["product_json"])["references"]]
    db.close()
    assert refs and all(__import__("pathlib").Path(p).is_file() for p in refs)
    r = post({"password": "senha-forte-123", "confirm": "apagar"})
    assert r.status == 200 and "Max-Age=0" in r.headers["Set-Cookie"]
    assert app.handle("GET", "/api/me", a, b"").status == 401
    assert not (settings.data_dir / "productions" / pa).exists()
    assert not any(__import__("pathlib").Path(p).exists() for p in refs)
    db = Database(settings.db_path)
    try:
        assert db.conn.execute("SELECT COUNT(*) FROM users WHERE email='ana@exemplo.com'").fetchone()[0] == 0
        for table in ("productions", "scenes", "attempts", "events"):
            col = "id" if table == "productions" else "production_id"
            assert db.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (pa,)).fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM productions WHERE id=?", (pb,)).fetchone()[0] == 1   # a Bia segue
    finally:
        db.close()
    assert (settings.data_dir / "productions" / pb).is_dir()
    assert app.handle("GET", f"/api/state?pid={pb}", b, b"").status == 200
    r = app.handle("POST", "/api/auth/login", CLIENT, json.dumps({"email": "ana@exemplo.com", "password": "senha-forte-123"}).encode())
    assert r.status == 400


def test_delete_refused_while_running_and_for_admin(two_users, monkeypatch, loader):
    app, (a, tok_a, pa), _ = two_users
    monkeypatch.setattr(app, "is_running", lambda pid: pid == pa)
    body = json.dumps({"password": "senha-forte-123", "confirm": "APAGAR"}).encode()
    assert app.handle("POST", "/api/account/delete", {**a, "X-Studio-Token": tok_a}, body).status == 409
    adm = {}
    login_app(app, adm, email="operador@exemplo.com")
    r = app.handle("POST", "/api/account/delete", {**adm, "X-Studio-Token": app.token}, body)
    assert r.status == 403 and "administrador" in json.loads(r.body)["error"]


def test_cli_delete_and_export_user(two_users, settings, monkeypatch, capsys):
    app, (a, _, pa), _ = two_users
    monkeypatch.setenv("STUDIO_DATA_DIR", str(settings.data_dir))
    assert cli.main(["admin", "export-user", "--email", "ana@exemplo.com"]) == 0
    assert json.loads(capsys.readouterr().out)["user"]["email"] == "ana@exemplo.com"
    assert cli.main(["admin", "delete-user", "--email", "ana@exemplo.com"]) == 2      # sem --yes
    assert cli.main(["admin", "delete-user", "--email", "ana@exemplo.com", "--yes"]) == 0
    assert app.handle("GET", "/api/me", a, b"").status == 401
