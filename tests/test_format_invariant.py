"""Regressões do bug de formato/apresentação (prod_233c9227ba, prod_57491e2e40): format_id, perfis congelados, ficha,
roteiro e prompts SEMPRE derivam da apresentação gravada, por qualquer caminho, e nada pago sai inconsistente.

Os testes seguem o fluxo EXATO do app React (App.jsx): criar sem Direção → validar → (reenviar fotos) → Direção →
liberar imagens, por HTTP."""

import json

from studio.db import Database
from studio.profiles import snapshot

from .test_creative_flow import BASE, HOST, PNG, app, post, wait_idle  # noqa: F401

HANDS = "only two adult female hands"          # bloco de mãos do perfil (Somente mãos)
NO_PEOPLE = "No people, no hands"               # bloco do perfil (Produto em destaque)
CREATE_GAME = {"name": BASE["name"], "category": "", "visual_attributes": "cor: azul", "verified": "", "seller_claims": "",
               "flow": "game", "start": False, "files": [{"name": "f.png", "data": PNG, "role": "front"}],
               "autonomy": "assistido"}
DIRECTION = {"presentation": "product_only", "proposal": "details", "environment": "neutro", "tone": "natural"}


def _db(settings):
    return Database(settings.db_path)


def _row(settings, pid):
    db = _db(settings)
    try:
        return dict(db.production(pid)), [dict(e) for e in db.events(pid)], [dict(a) for a in db.attempts(pid)]
    finally:
        db.close()


def _state(app, pid):
    return json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)["production"]


def _image_prompts(attempts):
    return [a["prompt"] for a in attempts if a["kind"] == "image"]


def test_app_flow_create_refs_direction_generate_is_product_only(app, settings):
    """criar → validar → substituir fotos → Direção (Produto em destaque) → gerar: tudo no formato do produto."""
    st, r = post(app, "/api/productions", CREATE_GAME)
    assert st == 200, r
    pid = r["pid"]
    assert post(app, f"/api/productions/{pid}/validate", {})[0] == 200
    st, _ = post(app, f"/api/productions/{pid}/references",
                 {"files": [{"name": "g.png", "data": PNG, "role": "front"}], "replace": True})
    assert st == 200
    wait_idle(app, pid)
    row, events, attempts = _row(settings, pid)
    # sem Direção: nada é roteirizado nem gerado com o formato provisório (antes, gerava imagens com mãos aqui)
    assert row["status"] == "validated" and row["script_json"] is None and not attempts
    s = _state(app, pid)
    assert s["awaiting_direction"] is True and s["presentation"] is None and s["presentation_label"] == "A definir na Direção"

    st, _ = post(app, f"/api/productions/{pid}/direction", {"creative": DIRECTION})
    assert st == 200
    wait_idle(app, pid)
    post(app, f"/api/productions/{pid}/go_ahead", {"stage": "images"})
    wait_idle(app, pid)

    row, events, attempts = _row(settings, pid)
    profiles = json.loads(row["profiles_json"])
    assert row["format_id"] == "produto_3cenas_15s"
    assert profiles["format"]["id"] == "produto_3cenas_15s" and profiles["format"]["data"]["presenter_mode"] == "product_only"
    assert profiles["art_direction"]["id"] == "ambiente_neutro"   # ambiente da Direção, não o "cozinha" da criação
    types = [e["type"] for e in events]
    assert "format_changed" in types and "art_direction_changed" in types and "format_invariant" not in types
    script = json.loads(row["script_json"])
    assert script["format_id"] == "produto_3cenas_15s"
    assert all(sc["presenter_mode"] == "product_only" for sc in script["scenes"])
    prompts = _image_prompts(attempts)
    assert prompts and all(NO_PEOPLE in p and HANDS not in p for p in prompts)
    sheet = json.loads(row["sheet_json"])
    assert sheet["product"]["creative"]["presentation"] == "product_only"
    s = _state(app, pid)
    assert s["presentation"] == "product_only" and s["format_id"] == "produto_3cenas_15s"
    assert s["presentation_label"] == "Produto em destaque" and s["awaiting_direction"] is False
    created = next(e for e in events if e["type"] == "production_created")
    assert json.loads(created["data_json"])["build"]   # qual código atendeu esta produção


def test_direction_without_explicit_presentation_is_refused(app, settings):
    """Antes: Direção sem `creative` virava 'Somente mãos' em silêncio (parse_creative devolve o padrão)."""
    st, r = post(app, "/api/productions", CREATE_GAME)
    pid = r["pid"]
    post(app, f"/api/productions/{pid}/validate", {})
    for body in ({}, {"creative": {}}, {"creative": {"proposal": "details"}}, {"creative": {"presentation": "lua"}}):
        st, data = post(app, f"/api/productions/{pid}/direction", body)
        assert st == 400 and "apresentar" in data["error"], (body, st, data)
    row, events, _ = _row(settings, pid)
    assert json.loads(row["product_json"])["creative"] is None and "product_updated" not in [e["type"] for e in events]


def test_switch_presentation_after_images_regenerates_without_hands(app, settings):
    """Somente mãos gerado → Direção troca para Produto em destaque: format_id, roteiro, prompts e âncora mudam."""
    st, r = post(app, "/api/productions", {**BASE, "creative": {**DIRECTION, "presentation": "hands_only"},
                                           "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    pid = r["pid"]
    wait_idle(app, pid)
    row, _, attempts = _row(settings, pid)
    assert row["format_id"] == "maos_3cenas_15s" and any(HANDS in p for p in _image_prompts(attempts))
    first = [a for a in attempts if a["kind"] == "image" and a["status"] == "succeeded"][0]
    assert post(app, f"/api/productions/{pid}/anchor", {"attempt_id": first["id"]})[0] == 200

    post(app, f"/api/productions/{pid}/direction", {"creative": DIRECTION})
    wait_idle(app, pid)
    row, events, attempts = _row(settings, pid)
    assert row["format_id"] == "produto_3cenas_15s" and row["anchor_json"] is None   # âncora era de mãos
    live = [a for a in attempts if a["kind"] == "image" and not a["superseded"]]
    assert live and all(NO_PEOPLE in a["prompt"] and HANDS not in a["prompt"] for a in live)
    assert any(e["type"] == "anchor" and "formato anterior" in e["message"] for e in events)


def test_invariant_repairs_old_inconsistent_production_before_any_generation(app, settings):
    """O estado de prod_57491e2e40: ficha com Produto em destaque, mas format_id/perfil/roteiro de mãos (código antigo
    ou rota que gravou product_json direto). A barreira recalcula ANTES de gerar e registra format_changed."""
    st, r = post(app, "/api/productions", {**BASE, "creative": {**DIRECTION, "presentation": "hands_only"}, "start": False,
                                           "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    pid = r["pid"]
    db = _db(settings)
    try:   # grava a apresentação direto no banco, sem passar por update_product (o que o código antigo deixava acontecer)
        product = json.loads(db.production(pid)["product_json"])
        product["creative"]["presentation"] = "product_only"
        db.update_production(pid, product_json=json.dumps(product))
        assert db.production(pid)["format_id"] == "maos_3cenas_15s"
    finally:
        db.close()
    assert post(app, f"/api/productions/{pid}/run", {})[0] == 200
    wait_idle(app, pid)
    row, events, attempts = _row(settings, pid)
    assert row["format_id"] == "produto_3cenas_15s"
    inv = [e for e in events if e["type"] == "format_invariant"]
    assert inv and "exige produto_3cenas_15s" in inv[0]["message"]
    changed = [json.loads(e["data_json"]) for e in events if e["type"] == "format_changed"]
    assert changed and changed[0]["source"] == "invariante"
    prompts = _image_prompts(attempts)
    assert prompts and all(NO_PEOPLE in p and HANDS not in p for p in prompts)   # nenhuma chamada paga com mãos


def test_invariant_catches_stale_script_while_producing(app, settings):
    """Produção já gerando com roteiro de mãos e a apresentação trocada por fora: nada é enviado com o roteiro velho."""
    st, r = post(app, "/api/productions", {**BASE, "creative": {**DIRECTION, "presentation": "hands_only"},
                                           "flow": "game", "autonomy": "manual",
                                           "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    pid = r["pid"]
    wait_idle(app, pid)   # manual + go_ahead none: para no portão das imagens, com roteiro de mãos
    row, _, attempts = _row(settings, pid)
    assert row["status"] == "producing" and not _image_prompts(attempts)
    db = _db(settings)
    try:
        product = json.loads(row["product_json"])
        product["creative"]["presentation"] = "product_only"
        prof = json.loads(row["profiles_json"])
        prof.update(snapshot(settings.profiles_dir, {"format": "produto_3cenas_15s"}, only=("format",)))
        # metade da troca: format_id e perfil novos, roteiro e cenas ainda de mãos
        db.update_production(pid, product_json=json.dumps(product), format_id="produto_3cenas_15s",
                             profiles_json=json.dumps(prof))
    finally:
        db.close()
    post(app, f"/api/productions/{pid}/go_ahead", {"stage": "images"})
    wait_idle(app, pid)
    row, events, attempts = _row(settings, pid)
    assert any(e["type"] == "format_invariant" and "roteiro feito para maos_3cenas_15s" in e["message"] for e in events)
    prompts = _image_prompts(attempts)
    assert prompts and all(NO_PEOPLE in p and HANDS not in p for p in prompts)


def test_invariant_blocks_with_clear_error_when_it_cannot_fix(app, settings, monkeypatch):
    from studio.orchestrator import Orchestrator
    monkeypatch.setattr(Orchestrator, "format_problems", lambda self, pid, with_script=True: ["formato de teste quebrado"])
    st, r = post(app, "/api/productions", {**BASE, "creative": DIRECTION,
                                           "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    pid = r["pid"]
    wait_idle(app, pid)
    row, events, attempts = _row(settings, pid)
    assert row["status"] == "failed" and "formato inconsistente" in row["status_reason"]
    assert not [a for a in attempts if a["kind"] in ("image", "video")]   # nada pago


def test_production_records_the_code_that_created_it(app, settings, monkeypatch):
    """Para nunca mais depender de "o código estava no ar?": cada produção guarda o commit (Docker: STUDIO_BUILD_COMMIT).
    /healthz continua só com {"status": "ok"} (nada de versão numa rota pública)."""
    from studio import buildinfo
    buildinfo.commit.cache_clear()
    monkeypatch.setenv("STUDIO_BUILD_COMMIT", "abc1234def")
    try:
        st, r = post(app, "/api/productions", CREATE_GAME)
        _, events, _ = _row(settings, r["pid"])
        created = next(e for e in events if e["type"] == "production_created")
        assert json.loads(created["data_json"])["build"] == "abc1234def" and "código=abc1234def" in created["message"]
        assert "apresentação=(a definir na Direção)" in created["message"]
        assert json.loads(app.handle("GET", "/healthz", {"Host": "127.0.0.1:8765"}, b"").body) == {"status": "ok"}
    finally:
        buildinfo.commit.cache_clear()
