import json

import pytest

from studio.web.server import App, SECURITY_HEADERS, StudioHTTPServer, serve

PUBLIC = "abc-def.trycloudflare.com"
CLIENT = {"Host": PUBLIC, "X-Studio-Client": "game"}
BODY = json.dumps({"email": "a@b.com", "password": "senha-forte-123"}).encode()


@pytest.fixture
def app(settings):
    return App(8765, settings_loader=lambda: settings, sim_pacing=False, public_host=PUBLIC, trust_proxy="cloudflare")


def _make_user(app):
    s, db, acc = app._db()
    try:
        acc.create_user("a@b.com", "senha-forte-123", "A", admin=True)
    finally:
        db.close()


def test_public_address_is_accepted_and_others_are_not(app):
    assert app.handle("POST", "/api/auth/logout", CLIENT, b"{}").status == 200
    assert app.handle("POST", "/api/auth/logout", {**CLIENT, "Host": "evil.com"}, b"{}").status == 403


def test_signup_is_closed_even_with_no_users(app):
    # sem isto, o primeiro visitante da internet viraria administrador
    assert app.handle("POST", "/api/auth/signup", CLIENT, BODY).status == 403
    assert app.handle("POST", "/api/auth/signup", {**CLIENT, "Host": "127.0.0.1:8765"}, BODY).status == 403


def test_cookie_is_secure_only_on_the_public_address(app):
    _make_user(app)
    public = app.handle("POST", "/api/auth/login", CLIENT, BODY)
    assert public.status == 200 and "Secure" in public.headers["Set-Cookie"]
    local = app.handle("POST", "/api/auth/login", {**CLIENT, "Host": "127.0.0.1:8765"}, BODY)
    assert local.status == 200 and "Secure" not in local.headers["Set-Cookie"]


def test_client_ip_comes_from_the_tunnel_and_cannot_be_spoofed(app):
    assert app._client_ip({"Host": PUBLIC, "Cf-Connecting-Ip": "1.2.3.4"}) == "1.2.3.4"  # o túnel (Go) usa esta caixa
    assert app._client_ip({"Host": PUBLIC, "X-Forwarded-For": "9.9.9.9"}) == "local"   # só o cabeçalho declarado vale
    assert app._client_ip({"Host": PUBLIC, "X-Forwarded-For": "9.9.9.9"}, "10.0.0.2") == "10.0.0.2"


def test_login_throttle_ignores_spoofed_forwarded_for(app):
    _make_user(app)
    headers = {**CLIENT, "Cf-Connecting-Ip": "1.2.3.4"}
    last = None
    for i in range(9):  # e-mails diferentes: só o limite por IP pode barrar
        wrong = json.dumps({"email": f"x{i}@b.com", "password": "errada-errada"}).encode()
        last = app.handle("POST", "/api/auth/login", {**headers, "X-Forwarded-For": f"9.9.9.{i}"}, wrong)
    assert "muitas tentativas" in json.loads(last.body)["error"]


def test_local_mode_signup_is_closed_unless_opened_explicitly(settings):
    app = App(8765, settings_loader=lambda: settings, sim_pacing=False)
    assert app.handle("POST", "/api/auth/signup", {**CLIENT, "Host": "127.0.0.1:8765"}, BODY).status == 403
    app = App(8765, settings_loader=lambda: settings, sim_pacing=False, signup="open")
    assert app.handle("POST", "/api/auth/signup", {**CLIENT, "Host": "127.0.0.1:8765"}, BODY).status == 200


def test_security_headers_are_defined():
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY" and SECURITY_HEADERS["Referrer-Policy"] == "no-referrer"
    assert "Permissions-Policy" in SECURITY_HEADERS and SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"


def test_second_server_on_the_same_port_is_refused():
    first = StudioHTTPServer(("127.0.0.1", 0), None)
    try:
        with pytest.raises(SystemExit, match="já está em uso"):
            serve(first.server_address[1], open_browser=False)
    finally:
        first.server_close()
