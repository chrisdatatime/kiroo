import base64
import json
import time

import pytest

from studio import creative_options as co
from studio.config import load_settings
from studio.db import Database
from studio.models import CreativeChoices
from studio.providers.simulated import placeholder_png
from studio.web.server import App

from .conftest import login_app  # noqa: E402

HOST = {"Host": "127.0.0.1:8765"}
PNG = "data:image/png;base64," + base64.b64encode(placeholder_png("x", 90, 160)).decode()
BASE = {"name": "Copo com alça", "variant": "azul-claro", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j",
        "verified": "cor: azul-claro", "budget": 5}


@pytest.fixture
def app(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    a = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(a, HOST)
    return a


def post(app, path, body):
    r = app.handle("POST", path, {**HOST, "X-Studio-Token": app.token}, json.dumps(body).encode())
    return r.status, json.loads(r.body)


def wait_idle(app, pid, timeout=30):
    end = time.time() + timeout
    while app.is_running(pid) and time.time() < end:
        time.sleep(0.05)


# ------------------------------------------------------------- sugestão por regras
def test_suggestion_for_drinkware_is_contextual_and_honest():
    out = co.ideas("Kit Garrafa Squeeze com canudo", None, presenter_available=True)
    assert out["category"] == "bebidas"
    assert out["suggested_environments"] == ["cozinha", "mesa_trabalho", "treino"]
    assert out["recommended_proposal"] == "practice" and out["proposal_reason"]
    assert "não foram analisadas" in out["basis"]
    assert len({json.dumps(i["choices"], sort_keys=True) for i in out["ideas"]}) == 3  # "outra ideia" muda de fato


def test_unknown_category_falls_back_to_safe_details():
    out = co.ideas("Produto qualquer", "", presenter_available=False)
    assert out["recommended_proposal"] == "details" and "não sugere usos" in out["proposal_reason"]


def test_incompatible_details_are_dropped_and_auto_is_resolved():
    c = co.resolve(CreativeChoices(presentation="product_only", environment="treino", proposal="auto",
                                   details=["superficie_clara", "unhas_cuidadas", "luz_natural", "luz_natural"]),
                   "copo", None)
    assert c.proposal == "practice"
    assert c.details == ["luz_natural"]  # sem duplicata, sem superfície clara no treino, sem unhas sem mãos


def test_direction_never_states_product_facts():
    for prop in ("practice", "details", "routine"):
        text = co.compose_direction(CreativeChoices(proposal=prop, details=list(co.DETAILS)))
        low = text.lower()
        for claim in ("ml", "liters", "thermal", "keeps cold", "stainless", "bpa", "certified", "leak-proof product"):
            assert claim not in low.replace("leak-proofing", "")


# ------------------------------------------------------------- prévia (sem custo)
def test_preview_reflects_choices_and_custom_environment(app):
    status, data = post(app, "/api/creative/preview", {**BASE, "creative": {
        "presentation": "hands_only", "proposal": "details", "environment": "outro",
        "environment_custom": "varanda com plantas e mesa de madeira", "tone": "leve", "details": ["luz_natural"],
        "details_text": "unhas bem cuidadas"}})
    assert status == 200
    assert data["profiles"]["format"] == "maos_3cenas_15s@v3" and data["profiles"]["art_direction"].startswith("ambiente_personalizado")
    scene1 = data["scenes"][0]["image_prompt"]
    assert "varanda com plantas" in scene1 and "visible in the reference photos" in scene1
    for s in data["scenes"]:  # formato v2 não fixa mais a cozinha
        assert "kitchen" not in (s["image_prompt"] + s["animation_prompt"]).lower()
    assert "varanda" in data["summary"] and "leve" in data["summary"]
    assert data["warnings"] == []


def test_preview_warns_when_detail_looks_like_a_product_claim(app):
    _, data = post(app, "/api/creative/preview", {**BASE, "creative": {"details_text": "mantém gelado por 12 horas"}})
    assert data["warnings"] and "característica do produto" in data["warnings"][0]


def test_manual_direction_wins_and_auto_stays_available(app):
    _, data = post(app, "/api/creative/preview", {**BASE, "creative": {"manual_direction": "CUSTOM BLOCK: slow push-in only."}})
    assert data["direction"] == "CUSTOM BLOCK: slow push-in only."
    assert "CREATIVE DIRECTION" in data["auto_direction"]
    assert data["scenes"][0]["image_prompt"].endswith("CUSTOM BLOCK: slow push-in only.")


def test_preview_works_with_incomplete_form(app):
    status, data = post(app, "/api/creative/preview", {"creative": {}})
    assert status == 200 and data["summary"]


def test_options_endpoint(app):
    r = app.handle("GET", "/api/creative/options?name=Copo%20com%20al%C3%A7a&category=", HOST, b"")
    data = json.loads(r.body)
    assert r.status == 200 and set(data["presentations"]) == {"hands_only", "product_only", "presenter"}
    assert "en" not in data["proposals"]["practice"]  # instruções técnicas não vão para a interface
    assert data["environments"]["cozinha"]["label"] == "Cozinha com luz natural"  # catálogo não é sobrescrito
    assert data["suggested_environments"][0] in data["environments"]


# ------------------------------------------------------------- escolhas → produção
@pytest.mark.parametrize("presentation, fmt, marker", [
    ("hands_only", "maos_3cenas_15s", "only two adult female hands"),
    ("product_only", "produto_3cenas_15s", "No people, no hands"),
    ("presenter", "bia_3cenas_15s", "PRESENTER: the woman from the presenter reference image"),
])
def test_choices_reach_generation_instructions(app, settings, presentation, fmt, marker):
    creative = {"presentation": presentation, "proposal": "routine", "environment": "mesa_trabalho", "tone": "sofisticado",
                "details": ["fundo_organizado"], "details_text": "Mostrar o canudo de perto."}
    status, data = post(app, "/api/productions", {**BASE, "creative": creative,
                                                  "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    assert status == 200, data
    wait_idle(app, data["pid"])
    db = Database(settings.db_path)
    try:
        row = db.production(data["pid"])
        assert row["format_id"] == fmt
        profiles = json.loads(row["profiles_json"])
        assert profiles["art_direction"]["id"] == "mesa_trabalho_clara" and profiles["presenter"]["version"] == "v2"
        script = json.loads(row["script_json"])
        p1 = script["scenes"][0]["image_prompt"]
        assert marker in p1 and "home-office desk" in p1
        assert "believable everyday moment" in p1 and "Tidy, uncluttered background." in p1
        assert "Mostrar o canudo de perto." in script["scenes"][2]["animation_prompt"]
        product = json.loads(row["product_json"])
        assert product["video_context"] == "Mostrar o canudo de perto." and product["creative"]["presentation"] == presentation
        if presentation == "presenter":
            sheet = json.loads(row["sheet_json"])
            assert "Identity reference" in sheet["presenter_assets"]["presenter_reference"]["usage_en"]
    finally:
        db.close()


def test_can_finish_without_typing_using_suggested_idea(app, settings):
    idea = co.ideas(BASE["name"], None, True)["ideas"][0]["choices"]
    status, data = post(app, "/api/productions", {**BASE, "creative": idea,
                                                  "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    assert status == 200
    wait_idle(app, data["pid"])
    state = json.loads(app.handle("GET", f"/api/state?pid={data['pid']}", HOST, b"").body)
    assert state["production"]["status"] == "producing"


def test_invalid_creative_choice_rejected(app):
    status, data = post(app, "/api/productions", {**BASE, "creative": {"environment": "lua"},
                                                  "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    assert status == 400 and "criativa" in data["error"]
