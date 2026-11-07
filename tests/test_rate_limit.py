"""Limite de requisições em memória: por IP e por usuário em /api/*, mais baixo em auth, chat, upload e criação;
429 com Retry-After; valores vindos da configuração."""

from __future__ import annotations

import base64
import json

import pytest

from studio.config import load_settings
from studio.providers.simulated import placeholder_png
from studio.ratelimit import RateLimitConfig, RateLimiter, Rule, classify
from studio.web.server import App

from .conftest import login_app

PNG = "data:image/png;base64," + base64.b64encode(placeholder_png("x", 90, 160)).decode()
FORM = {"name": "Copo", "variant": "azul", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j", "budget": 5,
        "files": [{"name": "f.png", "data": PNG, "role": "front"}], "start": False}
BIG = Rule(10_000, 60)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def make_app(settings, tmp_path, **rules):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    cfg = RateLimitConfig(enabled=True, **{"api_ip": BIG, "api_user": BIG, "auth": BIG, "chat": BIG, "upload": BIG,
                                           "create": BIG, **rules})
    return App(8765, settings_loader=loader, sim_pacing=False, rate_limits=cfg, trust_proxy="cloudflare")


def user(app, email):
    h = {}
    login_app(app, h, email=email)
    return h, app.token


def post(app, h, token, path, body):
    return app.handle("POST", path, {**h, "X-Studio-Token": token}, json.dumps(body).encode())


def assert_429(r):
    assert r.status == 429
    wait = int(r.headers["Retry-After"])
    assert 1 <= wait <= 600 and json.loads(r.body)["retry_after"] == wait
    return wait


# ------------------------------------------------------------------ unidade
def test_sliding_window_and_retry_after():
    clock = Clock()
    lim = RateLimiter(RateLimitConfig(enabled=True, auth=Rule(3, 10)), clock=clock)
    assert [lim.hit("auth", "1.2.3.4") for _ in range(3)] == [None, None, None]
    assert lim.hit("auth", "1.2.3.4") == 10
    assert lim.hit("auth", "5.6.7.8") is None           # outra chave, outra conta
    clock.t += 4
    assert lim.hit("auth", "1.2.3.4") == 6
    clock.t += 6.01
    assert lim.hit("auth", "1.2.3.4") is None


def test_config_from_env_and_validation(monkeypatch):
    from studio import ratelimit
    monkeypatch.setattr(ratelimit, "DEFAULT_ON", True)   # o padrão fora dos testes: ligado
    assert RateLimitConfig.from_env({}).enabled is True
    cfg = RateLimitConfig.from_env({"STUDIO_RATE_AUTH": "5/120", "STUDIO_RATE_CHAT": "0/60"})
    assert cfg.enabled and cfg.auth == Rule(5, 120) and cfg.chat.limit == 0 and cfg.api_user == RateLimitConfig().api_user
    assert RateLimitConfig.from_env({"STUDIO_RATE_LIMIT": "0"}).enabled is False
    with pytest.raises(ValueError, match="STUDIO_RATE_UPLOAD"):
        RateLimitConfig.from_env({"STUDIO_RATE_UPLOAD": "dez por minuto"})
    lim = RateLimiter(RateLimitConfig(enabled=True, chat=Rule(0, 60)))
    assert all(lim.hit("chat", "u") is None for _ in range(50))   # 0 desliga a regra


def test_defaults_are_lower_on_expensive_routes():
    d = RateLimitConfig()
    per_min = lambda r: r.limit / r.window_s * 60  # noqa: E731
    assert per_min(d.auth) < per_min(d.chat) < per_min(d.api_user) <= per_min(d.api_ip)
    assert per_min(d.create) < per_min(d.api_user) and per_min(d.upload) < per_min(d.api_user)


def test_route_classification():
    assert classify("POST", "/api/chat") == "chat"
    assert classify("POST", "/api/productions") == "create" and classify("POST", "/api/demo") == "create"
    assert classify("POST", "/api/productions/prod_0123456789/references") == "upload"
    assert classify("POST", "/api/music/upload") == "upload"
    assert classify("POST", "/api/training/iris/ref", True) == "upload"
    assert classify("POST", "/api/training/iris/ref", False) is None
    assert classify("GET", "/api/state") is None


# ------------------------------------------------------------------ servidor
def test_auth_limit_per_ip_with_retry_after(settings, tmp_path):
    app = make_app(settings, tmp_path, auth=Rule(3, 60))
    base = {"Host": "127.0.0.1:8765", "X-Studio-Client": "game", "Cf-Connecting-Ip": "203.0.113.7"}
    body = json.dumps({"email": "x@exemplo.com", "password": "errada-errada"}).encode()
    for _ in range(3):
        assert app.handle("POST", "/api/auth/login", base, body).status == 400
    assert_429(app.handle("POST", "/api/auth/login", base, body))
    assert_429(app.handle("POST", "/api/auth/forgot", base, b'{"email": "x@exemplo.com"}'))
    other = {**base, "Cf-Connecting-Ip": "198.51.100.9"}
    assert app.handle("POST", "/api/auth/login", other, body).status == 400   # outro IP segue
    assert app.handle("GET", "/api/auth/config", base, b"").status == 200    # leitura da tela de acesso não conta


def test_api_limit_per_ip(settings, tmp_path):
    app = make_app(settings, tmp_path, api_ip=Rule(5, 60))
    h = {"Host": "127.0.0.1:8765", "Cf-Connecting-Ip": "203.0.113.8"}
    for _ in range(5):
        assert app.handle("GET", "/api/config", h, b"").status == 200
    assert_429(app.handle("GET", "/api/config", h, b""))
    assert app.handle("GET", "/healthz", h, b"").status == 200   # sondas e páginas fora de /api/* não contam


def test_api_limit_per_user(settings, tmp_path):
    app = make_app(settings, tmp_path, api_user=Rule(4, 60))
    a, _ = user(app, "a@exemplo.com")    # login_app já faz um GET /api/me
    b, _ = user(app, "b@exemplo.com")
    for _ in range(3):
        assert app.handle("GET", "/api/state", a, b"").status == 200
    assert_429(app.handle("GET", "/api/state", a, b""))
    assert app.handle("GET", "/api/state", b, b"").status == 200   # mesmo IP, outro usuário


def test_chat_limit_is_lower_and_separate(settings, tmp_path):
    app = make_app(settings, tmp_path, chat=Rule(2, 60))
    h, tok = user(app, "a@exemplo.com")
    for _ in range(2):
        assert post(app, h, tok, "/api/chat", {"agent": "theo", "text": "oi"}).status == 200
    assert_429(post(app, h, tok, "/api/chat", {"agent": "theo", "text": "oi"}))
    assert app.handle("GET", "/api/state", h, b"").status == 200   # o resto da API continua


def test_create_and_upload_limits(settings, tmp_path):
    app = make_app(settings, tmp_path, create=Rule(2, 300), upload=Rule(1, 60))
    h, tok = user(app, "a@exemplo.com")
    pids = []
    for _ in range(2):
        r = post(app, h, tok, "/api/productions", FORM)
        assert r.status == 200
        pids.append(json.loads(r.body)["pid"])
    assert_429(post(app, h, tok, "/api/productions", FORM))
    assert_429(post(app, h, tok, "/api/demo", {}))
    files = {"files": [{"name": "g.png", "data": PNG, "role": "side"}]}
    assert post(app, h, tok, f"/api/productions/{pids[0]}/references", files).status == 200
    assert_429(post(app, h, tok, f"/api/productions/{pids[0]}/references", files))


def test_disabled_by_config(settings, tmp_path):
    app = make_app(settings, tmp_path, api_ip=Rule(1, 60))
    app.limiter = RateLimiter(RateLimitConfig(enabled=False, api_ip=Rule(1, 60)))
    h = {"Host": "127.0.0.1:8765"}
    assert all(app.handle("GET", "/api/config", h, b"").status == 200 for _ in range(5))
