"""Raiz x app: STUDIO_LANDING_HOST (kiroo.io) serve só a landing e as páginas legais; STUDIO_APP_URL (app.kiroo.io), o app."""

from __future__ import annotations

import json

import pytest

import studio.web.server as srv
from studio.config import load_settings
from studio.runtime import ServerConfig, parse_app_url, parse_landing_host
from studio.web.server import App

ROOT, WWW, APPH, OTHER = {"Host": "kiroo.io"}, {"Host": "www.kiroo.io"}, {"Host": "app.kiroo.io"}, {"Host": "staging.kiroo.app"}
LANDING_SRC = ('<!doctype html><html lang="pt-BR"><head><link rel="canonical" href="__LANDING_ORIGIN__/">'
               '<meta name="kiroo-login-url" content="__APP_LOGIN_URL__"><meta name="kiroo-signup" content="__SIGNUP__">'
               '<meta property="og:image" content="__LANDING_ORIGIN__/og-image.png"></head><body><div id="root"></div></body></html>')


@pytest.fixture
def dist(tmp_path, monkeypatch):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><html><body>APP</body></html>", encoding="utf-8")
    (d / "landing.html").write_text(LANDING_SRC, encoding="utf-8")
    (d / "assets" / "landing-AbCdEf12.js").write_text("console.log(1)", encoding="utf-8")
    (d / "og-image.png").write_bytes(b"\x89PNG")
    (d / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(srv, "GAME_DIST", d)
    return d


@pytest.fixture
def make(settings, tmp_path, dist):
    loader = lambda: load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                                   profiles_dir=settings.profiles_dir)

    def build(landing="kiroo.io", app_url="https://app.kiroo.io", signup="open"):
        cfg = ServerConfig(landing_host=landing, app_url=app_url, signup=signup,
                           allowed_hosts=("app.kiroo.io", "staging.kiroo.app"))
        return App(8765, settings_loader=loader, sim_pacing=False, config=cfg)
    return build


def get(app, path, host, method="GET", body=b""):
    return app.handle(method, path, dict(host), body)


# ------------------------------------------------------------------ raiz (kiroo.io)
def test_root_serves_landing_with_config(make):
    app = make()
    r = get(app, "/", ROOT)
    html = r.body.decode()
    assert r.status == 200 and r.content_type.startswith("text/html")
    assert '<link rel="canonical" href="https://kiroo.io/">' in html
    assert 'content="https://app.kiroo.io/login"' in html and 'content="open"' in html
    assert 'content="https://kiroo.io/og-image.png"' in html and "__" not in html
    assert "Set-Cookie" not in r.headers


@pytest.mark.parametrize("path", ["/termos", "/privacidade", "/legal/legal.css", "/legal/logo.svg", "/healthz",
                                  "/assets/landing-AbCdEf12.js", "/og-image.png", "/?utm_source=ig&utm_medium=bio"])
def test_root_public_paths(make, path):
    r = get(make(), path, ROOT)
    assert r.status == 200, (path, r.status, r.headers)
    assert "Set-Cookie" not in r.headers


@pytest.mark.parametrize("path", ["/login", "/login?entrar", "/api/me", "/api/auth/config", "/?reset=abc", "/?compra=ok&x=1",
                                  "/painel", "/index.html", "/manifest.webmanifest", "/media/x.png", "/qualquer/coisa?a=1"])
def test_root_redirects_everything_else_to_app(make, path):
    r = get(make(), path, ROOT)
    assert r.status == 301 and r.headers["Location"] == "https://app.kiroo.io" + path
    assert "Set-Cookie" not in r.headers


def test_root_post_keeps_method_and_never_logs_in(make):
    app = make()
    body = json.dumps({"email": "a@b.com", "password": "senha-forte-123"}).encode()
    r = get(app, "/api/auth/login", {**ROOT, "X-Studio-Client": "game"}, "POST", body)
    assert r.status == 308 and r.headers["Location"] == "https://app.kiroo.io/api/auth/login"
    assert "Set-Cookie" not in r.headers
    r = get(app, srv.WEBHOOK_PATH, ROOT, "POST", b"{}")
    assert r.status == 308 and r.headers["Location"] == "https://app.kiroo.io" + srv.WEBHOOK_PATH


@pytest.mark.parametrize("raw", ["//evil.com/x", "/\\evil.com", "//evil.com", "/%2F%2Fevil.com"])
def test_no_open_redirect(make, raw):
    for host, base in ((ROOT, "https://app.kiroo.io/"), (WWW, "https://kiroo.io/")):
        loc = get(make(), raw, host).headers["Location"]
        assert loc.startswith(base) and "://evil" not in loc, (raw, loc)


def test_robots_and_sitemap(make):
    app = make()
    r = get(app, "/robots.txt", ROOT)
    assert r.status == 200 and "Allow: /" in r.body.decode() and "Sitemap: https://kiroo.io/sitemap.xml" in r.body.decode()
    r = get(app, "/sitemap.xml", ROOT)
    body = r.body.decode()
    assert r.status == 200 and r.content_type.startswith("application/xml")
    assert body.count("<loc>") == 1 and "<loc>https://kiroo.io/</loc>" in body and "termos" not in body


def test_www_goes_to_root(make):
    app = make()
    assert get(app, "/", WWW).headers["Location"] == "https://kiroo.io/"
    r = get(app, "/termos?x=1", WWW)
    assert r.status == 301 and r.headers["Location"] == "https://kiroo.io/termos?x=1"


def test_root_without_build_is_503_not_app(make, dist):
    (dist / "landing.html").unlink()
    r = get(make(), "/", ROOT)
    assert r.status == 503 and b"APP" not in r.body


# ------------------------------------------------------------------ app (app.kiroo.io)
def test_app_host(make):
    app = make()
    r = get(app, "/", APPH)
    assert r.status == 302 and r.headers["Location"] == "/login" and r.headers["X-Robots-Tag"] == "noindex, nofollow"
    r = get(app, "/login", APPH)
    assert r.status == 200 and b"APP" in r.body and r.headers["X-Robots-Tag"] == "noindex, nofollow"
    for p in ("/termos", "/privacidade"):
        r = get(app, p, APPH)
        assert r.status == 301 and r.headers["Location"] == "https://kiroo.io" + p and r.headers["X-Robots-Tag"]
    r = get(app, "/robots.txt", APPH)
    assert r.status == 200 and "Disallow: /" in r.body.decode() and r.headers["X-Robots-Tag"] == "noindex, nofollow"
    r = get(app, "/api/auth/config", APPH)
    assert r.status == 200 and r.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_app_host_session_cookie_is_host_only(make):
    app = make()
    s, db, acc = app._db()
    try:
        acc.create_user("ana@example.com", "senha-forte-123", "Ana", verified=True)
    finally:
        db.close()
    r = get(app, "/api/auth/login", {**APPH, "X-Studio-Client": "game"}, "POST",
            json.dumps({"email": "ana@example.com", "password": "senha-forte-123"}).encode())
    assert r.status == 200
    cookies = r.headers["Set-Cookie"]
    cookies = cookies if isinstance(cookies, list) else [cookies]
    assert cookies and all("domain=" not in c.lower() for c in cookies)


def test_webhook_still_reaches_app_on_app_and_other_hosts(make):
    app = make()
    for host in (APPH, OTHER):
        r = get(app, srv.WEBHOOK_PATH, host, "POST", b"{}")
        assert r.status not in (301, 308, 403), (host, r.status)


# ------------------------------------------------------------------ outros hosts e desligado
def test_other_hosts_unchanged(make):
    app = make()
    r = get(app, "/termos", OTHER)
    assert r.status == 200 and "X-Robots-Tag" not in r.headers
    r = get(app, "/", OTHER)
    assert r.status == 302 and r.headers["Location"] == "/login"
    assert get(app, "/robots.txt", OTHER).status != 200
    assert get(app, "/", {"Host": "evil.example"}).status == 403


def test_disabled_changes_nothing(make):
    app = make(landing=None, app_url=None)
    r = get(app, "/termos", APPH)
    assert r.status == 200 and "X-Robots-Tag" not in r.headers
    assert get(app, "/", ROOT).status == 403                 # kiroo.io não está na lista: continua recusado
    assert get(app, "/", APPH).headers["Location"] == "/login"


def test_config_validation(make):
    assert parse_landing_host(" Kiroo.IO ") == "kiroo.io" and parse_landing_host("") is None
    assert parse_app_url("https://app.kiroo.io/") == "https://app.kiroo.io" and parse_app_url(None) is None
    for bad in ("https://kiroo.io", "www.kiroo.io", "kiroo.io/x"):
        if bad.startswith("https"):
            continue
        with pytest.raises(ValueError):
            parse_landing_host(bad)
    for bad in ("http://app.kiroo.io", "https://app.kiroo.io/x", "https://app.kiroo.io?a=1", "javascript:alert(1)", "app.kiroo.io"):
        with pytest.raises(ValueError):
            parse_app_url(bad)
    with pytest.raises(ValueError):
        make(app_url=None)
    with pytest.raises(ValueError):
        make(app_url="https://www.kiroo.io")
    assert ServerConfig.from_env({"STUDIO_LANDING_HOST": "kiroo.io", "STUDIO_APP_URL": "https://app.kiroo.io"}).app_url \
        == "https://app.kiroo.io"


def test_public_config_exposes_landing_url(make):
    # o app descobre a landing pela config pública (sem sessão); o destino vem só do ambiente, nunca da requisição
    app = make()
    for path in ("/api/config", "/api/auth/config"):
        r = get(app, path, APPH)
        assert r.status == 200 and json.loads(r.body)["landing_url"] == "https://kiroo.io"
    r = get(app, "/api/config?landing_url=https://evil.example", {**APPH, "Referer": "https://evil.example/"})
    assert json.loads(r.body)["landing_url"] == "https://kiroo.io"
    off = make(landing=None, app_url=None)
    assert json.loads(get(off, "/api/config", APPH).body)["landing_url"] == ""
