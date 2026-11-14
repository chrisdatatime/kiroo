from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from studio.config import PROJECT_ROOT, load_settings
from studio.factory import build
from studio.models import ProductInput
from studio.providers.simulated import SimulationScript, placeholder_png

FAKE_KEY = "AIzaFAKE-TEST-SECRET-0123456789"


@pytest.fixture(autouse=True)
def _rate_limit_off_by_default(monkeypatch):
    """Os testes fazem dezenas de cadastros e consultas seguidas do mesmo "IP": o limite de requisições fica desligado,
    salvo nos testes que tratam dele (tests/test_rate_limit.py passa a configuração explicitamente)."""
    from studio import ratelimit
    monkeypatch.setattr(ratelimit, "DEFAULT_ON", False)


_FAL_BLOCKED = ("fal.run", "fal.ai", "fal.media")


def fal_host_blocked(host) -> bool:
    h = str(host or "").lower()
    return any(h == b or h.endswith("." + b) for b in _FAL_BLOCKED)


@pytest.fixture(autouse=True)
def _block_fal_network(monkeypatch):
    """Nenhum teste fala com a rede real da fal.ai (queue.fal.run, api.fal.ai, rest.alpha.fal.ai, v3.fal.media): a
    resolucao de nome e a conexao para esses dominios falham na hora. Os testes do cliente usam httpx.MockTransport."""
    import socket
    real_gai, real_cc = socket.getaddrinfo, socket.create_connection

    def gai(host, *a, **k):
        if fal_host_blocked(host):
            raise OSError(f"rede da fal.ai bloqueada nos testes: {host}")
        return real_gai(host, *a, **k)

    def cc(address, *a, **k):
        if fal_host_blocked(address[0]):
            raise OSError(f"rede da fal.ai bloqueada nos testes: {address[0]}")
        return real_cc(address, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", gai)
    monkeypatch.setattr(socket, "create_connection", cc)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in [v for v in os.environ if v.startswith("STUDIO_")]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assets = tmp_path / "assets"
    (assets / "bia").mkdir(parents=True)
    (assets / "bia" / "PERFIL BIA.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 100)
    return load_settings(env_file=tmp_path / "none.env", mode="simulated", data_dir=tmp_path / "data",
                         assets_dir=assets, profiles_dir=PROJECT_ROOT / "profiles", poll_interval_s=0.0,
                         max_image_attempts=3, max_video_attempts=2, x264_preset="ultrafast")


@pytest.fixture
def refs_dir(tmp_path) -> Path:
    d = tmp_path / "refs"
    d.mkdir()
    for role in ("front", "side", "lid"):
        (d / f"{role}.png").write_bytes(placeholder_png(role, 90, 160))
    return d


@pytest.fixture
def product(refs_dir) -> ProductInput:
    return ProductInput.model_validate({
        "name": "Copo com alça",
        "variant": "azul-claro",
        "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j",
        "references": [{"path": str(refs_dir / f"{r}.png"), "role": r} for r in ("front", "side", "lid")],
        "visual_attributes": {"cor": "azul-claro", "alça": "lateral"},
        "claims": [{"field": "cor", "text": "Cor azul-claro", "kind": "verified", "source": "fotos oficiais"}],
    })


@pytest.fixture
def make_orch(settings, tmp_path):
    def _make(script: SimulationScript | None = None, **overrides):
        s = dataclasses.replace(settings, **overrides)
        return build(s, sim_script=script or SimulationScript(video_polls_before_done=0), sleep=lambda _: None,
                     base_dir=tmp_path)
    return _make


def create(orch, product, budget=10.0):
    return orch.create_production(product, format_id="maos_3cenas_15s", art_direction="cozinha_sp_alto_padrao",
                                  presenter="bia", budget_usd=budget)


def approve_all_images(orch, pid):
    from studio.states import SceneStatus
    for s in orch.db.scenes(pid):
        if s["status"] == SceneStatus.AWAITING_IMAGE_APPROVAL:
            orch.approve(pid, s["idx"], "image")


def drive_to_final(orch, pid, max_rounds=10):
    """Roda e aprova tudo até o pacote final (operador simulado nos testes)."""
    from studio.states import ProductionStatus, SceneStatus
    for _ in range(max_rounds):
        status = orch.run(pid)
        if status != ProductionStatus.PRODUCING:
            return status
        for s in orch.db.scenes(pid):
            if s["status"] == SceneStatus.AWAITING_IMAGE_APPROVAL:
                orch.approve(pid, s["idx"], "image")
            elif s["status"] == SceneStatus.AWAITING_VIDEO_APPROVAL:
                orch.approve(pid, s["idx"], "video")
    return orch.db.production(pid)["status"]


requires_ffmpeg = pytest.mark.skipif(
    not load_settings(env_file=Path("none.env")).ffmpeg_bin, reason="FFmpeg não instalado"
)


def promote_admin(app, email: str) -> None:
    """Faz o mesmo que `studio admin create-user --admin` faz depois de criar a conta: nenhuma conta vira admin sozinha."""
    s, db, acc = app._db()
    try:
        u = acc.user_by_email(email)
        db.conn.execute("UPDATE users SET is_platform_admin=1 WHERE id=?", (u["id"],))
        wid = acc.workspaces_of(u["id"])[0]["id"]
        acc.assign_orphans(wid)
        acc.set_workspace(wid, allow_real=1, mode=s.mode, monthly_cap_usd=s.monthly_cap_usd, credits_exempt=1)
    finally:
        db.close()


def login_app(app, host_dict: dict, email: str = "chris@example.com", password: str = "senha-forte-123"):
    """Cria a conta (o primeiro usuário do banco de teste é promovido a administrador, como o operador faria pela CLI)
    e entra; atualiza host_dict com o cookie e app.token com o CSRF."""
    import json as _json
    base = {"Host": f"127.0.0.1:{app.port}"}
    s, db, acc = app._db()
    try:
        exists = acc.user_by_email(email) is not None
        first = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        if not exists:
            acc.create_user(email, password, "", admin=False)
    finally:
        db.close()
    if not exists and first:
        promote_admin(app, email)
    r = app.handle("POST", "/api/auth/login", {**base, "X-Studio-Client": "game"},
                   _json.dumps({"email": email, "password": password}).encode())
    cookie = r.headers["Set-Cookie"].split(";")[0]
    me = _json.loads(app.handle("GET", "/api/me", {**base, "Cookie": cookie}, b"").body)
    host_dict.clear()
    host_dict.update({**base, "Cookie": cookie})
    app.token = me["csrf"]
    return me
