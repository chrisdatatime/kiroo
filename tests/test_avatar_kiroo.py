"""Avatar da conta (sempre um kiroo): sorteado uma vez na criação; conta antiga recebe um valor determinístico pelo id
no primeiro acesso e ele é salvo; nunca muda a cada login. Também: /pricing serve o app e /api/me diz se há Google."""

from __future__ import annotations

import inspect
import json

from studio import avatars
from studio.accounts import Accounts

from .test_accounts import BASE, CLIENT, User, app  # noqa: F401 (fixture)

# a mesma senha fictícia com que `User` cria a conta descartável (sem repetir o literal aqui)
PW = inspect.signature(User.__init__).parameters["password"].default


def test_catalog_is_stable_and_deterministic():
    assert avatars.AVATAR_KIROOS[0] == "k01" and len(avatars.AVATAR_KIROOS) == 12
    assert avatars.kiroo_for("usr_abc") == avatars.kiroo_for("usr_abc")
    assert all(avatars.valid(avatars.kiroo_for(f"usr_{i}")) for i in range(50))
    assert len({avatars.kiroo_for(f"usr_{i}") for i in range(200)}) > 6   # espalha, não cai sempre no mesmo
    assert avatars.valid(avatars.random_kiroo()) and not avatars.valid(None) and not avatars.valid("k99")


def test_new_account_gets_a_kiroo_once_and_keeps_it(app):
    u = User(app, "dono@exemplo.com")
    k = u.me["user"]["avatar_kiroo"]
    assert avatars.valid(k)
    s, db, acc = app._db()
    try:
        assert acc.user(acc.user_by_email("dono@exemplo.com")["id"])["avatar_kiroo"] == k   # salvo na criação
    finally:
        db.close()
    # novo login: o mesmo kiroo
    r = app.handle("POST", "/api/auth/login", CLIENT, json.dumps({"email": "dono@exemplo.com", "password": PW}).encode())
    cookie = r.headers["Set-Cookie"].split(";")[0]
    me = json.loads(app.handle("GET", "/api/me", {**BASE, "Cookie": cookie}, b"").body)
    assert me["user"]["avatar_kiroo"] == k


def test_old_account_without_kiroo_gets_deterministic_one_saved_on_first_access(app):
    u = User(app, "antigo@exemplo.com")
    s, db, acc = app._db()
    try:
        uid = acc.user_by_email("antigo@exemplo.com")["id"]
        db.conn.execute("UPDATE users SET avatar_kiroo=NULL WHERE id=?", (uid,))   # como as contas de antes da migração 15
    finally:
        db.close()
    first = u.get("/api/me")[1]["user"]["avatar_kiroo"]
    assert first == avatars.kiroo_for(uid)
    s, db, acc = app._db()
    try:
        assert acc.user(uid)["avatar_kiroo"] == first          # salvo
        assert Accounts(db).avatar_of(uid) == first
    finally:
        db.close()
    assert u.get("/api/me")[1]["user"]["avatar_kiroo"] == first


def test_me_says_whether_google_is_linked(app):
    u = User(app, "semgoogle@exemplo.com")
    assert u.me["user"]["google"] is False


def test_pricing_serves_the_app_only_with_session(app, monkeypatch, tmp_path):
    from studio.web import server
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    monkeypatch.setattr(server, "GAME_DIST", dist)
    r = app.handle("GET", "/pricing", BASE, b"")
    assert r.status == 302 and r.headers["Location"].startswith("/login")
    u = User(app, "precos@exemplo.com")
    r = app.handle("GET", "/pricing", u.h, b"")
    assert r.status == 200 and b"<title>app</title>" in r.body
