"""Nova produção sem cor/variante, link e limite: o servidor aplica o padrão de créditos (limitado pelo teto do estúdio)
e a ficha, os prompts, a legenda e a entrega não ganham placeholders vazios."""

from __future__ import annotations

import json

import pytest

from studio import billing
from studio.agents import creative
from studio.db import Database
from studio.models import ProductInput

from .conftest import create, drive_to_final, requires_ffmpeg
from .test_upload_demo_spend import png_data_url, post  # noqa: F401
from .test_upload_demo_spend import app  # noqa: F401 (fixture)

MIN_FORM = {"name": "Copo com alça", "files": [{"name": "f.png", "data": png_data_url(), "role": "front"}], "start": False}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in ("STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS", "STUDIO_MONTHLY_CAP_USD", "STUDIO_ENV", "STUDIO_ALLOW_PAID_CALLS"):
        monkeypatch.delenv(v, raising=False)


def budget_of(app, pid):
    s, db, _ = app._db()
    try:
        return db.production(pid)["budget_usd"]
    finally:
        db.close()


# ------------------------------------------------------------ padrão configurável
def test_default_cap_is_80_credits_and_configurable(monkeypatch):
    assert billing.default_production_cap_credits() == 80
    monkeypatch.setenv("STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS", "120")
    assert billing.default_production_cap_credits() == 120
    for bad in ("0", "-5", "abc", "", "nan", "inf"):
        monkeypatch.setenv("STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS", bad)
        assert billing.default_production_cap_credits() == 80, bad   # nunca fica sem limite
    pol = billing.policy()
    assert pol.credits(billing.default_production_budget_usd()) == 80


def test_default_budget_is_clamped_by_account_cap():
    assert billing.default_production_budget_usd(0) == 0.0                      # teto efetivo 0: nada cabe
    assert billing.default_production_budget_usd(1.0) == 1.0                    # teto menor que o padrão vale
    assert billing.default_production_budget_usd(1000) == pytest.approx(billing.policy().usd(80))


def test_server_applies_default_limit_when_form_has_no_limit(app):
    r = post(app, "/api/productions", MIN_FORM)
    assert r.status == 200, r.body
    pid = json.loads(r.body)["pid"]
    assert billing.policy().credits(budget_of(app, pid)) == 80


def test_server_default_respects_env_and_explicit_budget_still_works(app, monkeypatch):
    monkeypatch.setenv("STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS", "30")
    pid = json.loads(post(app, "/api/productions", MIN_FORM).body)["pid"]
    assert billing.policy().credits(budget_of(app, pid)) == 30
    pid2 = json.loads(post(app, "/api/productions", {**MIN_FORM, "budget": 5}).body)["pid"]   # clientes antigos
    assert budget_of(app, pid2) == 5


def test_real_default_limit_never_exceeds_account_cap(app, monkeypatch):
    monkeypatch.setenv("STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS", "100000")
    assert post(app, "/api/runtime", {"monthly_cap_usd": 2, "mode": "real"}).status == 200
    pid = json.loads(post(app, "/api/productions", MIN_FORM).body)["pid"]
    assert budget_of(app, pid) == pytest.approx(2.0)
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "1.5")   # plataforma menor que a conta: vale a plataforma
    pid = json.loads(post(app, "/api/productions", MIN_FORM).body)["pid"]
    assert budget_of(app, pid) == pytest.approx(1.5)


def test_account_cap_above_platform_is_refused_by_ui(app, monkeypatch):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    r = post(app, "/api/runtime", {"monthly_cap_usd": 50})
    assert r.status == 400 and "plataforma" in json.loads(r.body)["error"]
    assert post(app, "/api/runtime", {"monthly_cap_usd": 5}).status == 200


# ------------------------------------------------------------ campos ausentes
def bare(product) -> ProductInput:
    return product.model_copy(update={"variant": "", "affiliate_link": ""})


def test_model_accepts_missing_variant_and_link_but_still_validates_given_link(product):
    p = ProductInput.model_validate({"name": "Copo"})
    assert p.variant == "" and p.affiliate_link == ""
    with pytest.raises(ValueError):
        ProductInput.model_validate({"name": "Copo", "affiliate_link": "https://evil.example/x"})


def test_prompts_caption_and_script_have_no_empty_placeholders(product):
    from studio.models import ProductSheet
    sheet = ProductSheet.model_construct(product=bare(product), issues=[], unknown_fields=[], presenter_assets={},
                                         validated_at=None)
    block = creative.product_block(sheet)
    assert 'variant: ""' not in block and "variant: ;" not in block and f'listing name: "{product.name}")' in block


def test_validation_does_not_block_without_variant(app):
    pid = json.loads(post(app, "/api/productions", MIN_FORM).body)["pid"]
    r = post(app, f"/api/productions/{pid}/validate", {})
    body = json.loads(r.body)
    assert r.status == 200 and not any(i.get("code") == "variant_missing" for i in (body.get("issues") or []))
    assert body.get("ok") is True


@requires_ffmpeg
def test_full_flow_without_variant_and_link_delivers_clean_files(make_orch, product):
    orch = make_orch()
    pid = create(orch, bare(product))
    assert drive_to_final(orch, pid)
    d = orch._storage(pid).path("delivery")
    caption = (d / "caption.txt").read_text(encoding="utf-8")
    info = json.loads((d / "product.json").read_text(encoding="utf-8"))
    script = (d / "script.md").read_text(encoding="utf-8")
    assert caption.splitlines()[0] == product.name            # sem " — " pendurado
    assert "affiliate_link" not in info and "variant" not in info and "Link preservado" not in info.get("note", "")
    assert "()" not in script and "Link de afiliado" not in script
    for text in (caption, script):
        assert "None" not in text and "''" not in text
    prompts = "".join(p.read_text(encoding="utf-8") for p in orch._storage(pid).path("prompts").glob("*.txt"))
    assert 'variant: ""' not in prompts
