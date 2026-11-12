"""Cenas fiéis ao produto (caso prod_233c9227ba, mouse gamer em "Somente mãos"): ficha técnica visual, correções
acumulativas, prompt negativo padrão, sugestão de formato, revisor com gravidade, escolha lado a lado, imagem-âncora e
métricas de tentativas. Tudo com provedores simulados ou com um cliente Gemini falso (nada de rede, nada de chave real)."""

from __future__ import annotations

import dataclasses
import json
import time
from types import SimpleNamespace

import pytest

from studio import metrics
from studio.agents import fidelity
from studio.config import load_settings
from studio.models import ProductFacts, ProductInput, ReviewDecision, ReviewResult
from studio.providers.base import FactsRequest
from studio.providers.gemini import GeminiPlanner, GeminiReviewer
from studio.providers.simulated import SimulationScript
from studio.states import SceneStatus as SS
from studio.web.server import App

from .conftest import FAKE_KEY, create, login_app

R, A = ReviewDecision.REJECTED, ReviewDecision.APPROVED

MOUSE_FACTS = {
    "summary_en": "Black ergonomic gaming mouse, right-handed shape, matte finish, RGB strip along the base.",
    "colors": ["matte black", "RGB strip"],
    "buttons": [{"name": "left click", "position": "front left", "side": "left"},
                {"name": "right click", "position": "front right", "side": "right"},
                {"name": "scroll wheel", "position": "between the clicks", "side": "center"},
                {"name": "DPI button", "position": "behind the wheel", "side": "top"},
                {"name": "side buttons (2)", "position": "thumb rest", "side": "left"}],
    "button_count": 6, "left_side": "two side buttons on the thumb rest", "right_side": "smooth, no buttons",
    "cable": "braided black cable from the front center", "logos": ["RAZE logo on the palm area"],
    "proportions": "long and low, about 2:1 length to width", "asymmetric": True, "complexity": "complex",
    "must_keep": ["side buttons only on the LEFT"], "lixo": "ignorado",
}


# ============================================================ unidade: fidelity
def test_facts_block_lists_buttons_sides_cable_logos_and_parse_is_defensive():
    facts = fidelity.parse_facts({**MOUSE_FACTS, "button_count": "seis", "complexity": "absurdo",
                                  "buttons": [*MOUSE_FACTS["buttons"], "lixo", {"side": "diagonal"}]}, source="x")
    assert facts.button_count == 6 and facts.complexity == "simple"   # contagem inválida → nº de botões válidos
    assert facts.buttons[-1].side == "unknown"
    block = fidelity.facts_block(fidelity.parse_facts(MOUSE_FACTS, source="gemini-api:test"))
    for needle in ("exactly 6", "LEFT side only: two side buttons", "RIGHT side only: smooth", "ASYMMETRIC",
                   "Cable: braided", "RAZE logo", "Proportions:", "side buttons only on the LEFT"):
        assert needle in block
    assert fidelity.facts_block(None) == "" and fidelity.facts_block(ProductFacts()) == ""


def test_corrections_are_cumulative_and_deduplicated():
    h = fidelity.add_correction([], "fix the scroll wheel position", source="auto", attempt_no=1)
    h = fidelity.add_correction(h, "remove the extra finger", source="auto", attempt_no=2)
    h = fidelity.add_correction(h, "Remove the extra finger", source="human", attempt_no=3)   # repetida: não duplica
    assert [c["text"] for c in h] == ["fix the scroll wheel position", "remove the extra finger"]
    block = fidelity.corrections_block(h)
    assert "ALREADY FIXED, KEEP IT FIXED: fix the scroll wheel position" in block
    assert "NEW, APPLY STRICTLY: remove the extra finger" in block
    assert fidelity.corrections_block([]) == ""


def test_severity_product_blocks_hands_only_warn():
    hands = ReviewResult(decision=R, checks={"produto": "ok", "maos": "problema"}, warnings=["dedo extra na mão direita"])
    out = fidelity.apply_severity(hands)
    assert out.decision == A and out.reason_codes == ["mao"] and "dedo extra na mão direita" in out.issues
    prod = ReviewResult(decision=A, critical_issues=["botões laterais do lado direito (espelhado)"])
    assert fidelity.apply_severity(prod).decision == R
    assert "produto_lado" in fidelity.apply_severity(prod).reason_codes
    implicit = ReviewResult(decision=R, checks={"produto": "problema"}, issues=["cor diferente"])
    assert fidelity.apply_severity(implicit).critical_issues == ["cor diferente"]
    legacy = ReviewResult(decision=R, issues=["algo errado"])   # formato antigo: decisão do modelo vale
    assert fidelity.apply_severity(legacy).decision == R
    tech = fidelity.apply_severity(ReviewResult(decision=A), ["proporção 1x1 diferente de 9:16"])
    assert tech.decision == R and tech.reason_codes == ["tecnico"]


def test_complexity_heuristic():
    assert fidelity.looks_complex("Mouse Gamer Raze RGB")
    assert fidelity.looks_complex("Produto", "Periféricos", {"lado": "pegada destra"})
    assert not fidelity.looks_complex("Copo com alça", "Cozinha", {"cor": "azul"})


# ============================================================ Gemini (cliente falso, sem rede)
class FakeInteractions:
    def __init__(self, payloads):
        self.payloads, self.calls = list(payloads), []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output_text=json.dumps(self.payloads.pop(0)),
                               usage=SimpleNamespace(total_input_tokens=1200, total_output_tokens=300,
                                                     total_cached_tokens=0))


def test_gemini_describe_product_sends_photos_and_parses(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_ALLOW_PAID_CALLS", "true")
    photo = tmp_path / "front.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    planner = GeminiPlanner(FAKE_KEY, "gemini-3.5-flash-lite")
    fake = FakeInteractions([MOUSE_FACTS])
    planner._c = SimpleNamespace(interactions=fake)
    data, meta = planner.describe_product(FactsRequest(name="Mouse Gamer Raze", variant="preto",
                                                       references=[photo, photo]))
    parts = fake.calls[0]["input"]
    assert sum(1 for p in parts if p["type"] == "image") == 2
    assert "esquerdo/direito" in parts[0]["text"] and "<dados>" in parts[1]["text"]
    assert data["button_count"] == 6 and "usage" in meta
    with pytest.raises(Exception):
        planner.describe_product(FactsRequest(name="x", variant="", references=[]))


def test_gemini_reviewer_returns_graded_issues(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_ALLOW_PAID_CALLS", "true")
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    rev = GeminiReviewer(FAKE_KEY, "gemini-3.5-flash-lite")
    fake = FakeInteractions([{"decision": "rejected", "checks": {"produto": "ok"}, "critical_issues": [],
                              "aesthetic_issues": ["polegar com dois nós"], "issues": []}])
    rev._c = SimpleNamespace(interactions=fake)
    from studio.models import SceneSpec
    spec = SceneSpec(index=1, title="t", objective="o", framing="f", presenter_mode="hands_only",
                     references=["product:all"], image_prompt="p", animation_prompt="a", motion="m",
                     target_duration_s=5, approval_criteria=["CRÍTICO: exatamente 6 botões"])
    result, _ = rev.review_image(spec, img, [img])
    prompt = fake.calls[0]["input"][0]["text"]
    assert "CRÍTICO: exatamente 6 botões" in prompt and "critical_issues" in prompt
    assert result.warnings == ["polegar com dois nós"] and result.critical_issues == []
    assert fidelity.apply_severity(result).decision == A


# ============================================================ orquestrador (simulado)
class ScriptedReviewer:
    """Revisor de teste: cada chamada devolve o próximo resultado (com correções diferentes)."""

    provider, model, simulated = "simulated", "scripted", True

    def __init__(self, results):
        self.results, self.specs = list(results), []

    def review_image(self, spec, image, references):
        self.specs.append(spec)
        return (self.results.pop(0) if self.results else ReviewResult(decision=ReviewDecision.INCONCLUSIVE)), {}

    def review_video(self, spec, frames, approved_image, audio, probe):
        return ReviewResult(decision=ReviewDecision.INCONCLUSIVE), {}


def _rej(fix, issue):
    return ReviewResult(decision=R, checks={"produto": "problema"}, critical_issues=[issue], suggested_fix=fix)


@pytest.fixture
def mouse(refs_dir) -> ProductInput:
    return ProductInput.model_validate({
        "name": "Mouse Gamer Raze", "variant": "preto",
        "references": [{"path": str(refs_dir / f"{r}.png"), "role": r} for r in ("front", "side", "lid")],
        "visual_attributes": {"cor": "preto fosco", "botões laterais": "2, lado esquerdo"},
    })


def _images_only(orch, product):
    pid = create(orch, product)
    orch.set_go_ahead(pid, "images")
    return pid


def test_facts_extracted_once_injected_in_prompts_and_reviewer(make_orch, mouse):
    orch = make_orch(SimulationScript(image_reviews=[A, A, A]))
    pid = _images_only(orch, mouse)
    orch.run(pid)
    facts = orch._facts(pid)
    assert facts.simulated and facts.asymmetric and "botões laterais: 2, lado esquerdo" in facts.must_keep
    assert (orch.s.data_dir / "productions" / pid / "product_facts.json").is_file()
    assert [a["kind"] for a in orch.db.attempts(pid) if a["kind"] == "facts"] == ["facts"]
    att = orch.db.attempts(pid, 1, "image")[0]
    assert "PRODUCT SPEC SHEET" in att["prompt"] and fidelity.DEFAULT_NEGATIVE_EN in att["prompt"]
    # produto assimétrico em "Somente mãos": sugere "Produto em destaque" e avisa (sem trocar nem pausar)
    assert orch.db.production(pid)["format_advice"] == fidelity.FORMAT_ADVICE
    assert any(e["type"] == "format_advice" for e in orch.db.events(pid))
    # roteiro refeito com as mesmas fotos não paga a ficha de novo
    orch._extract_facts(pid, orch._sheet(pid))
    assert len([a for a in orch.db.attempts(pid) if a["kind"] == "facts"]) == 1


def test_retry_corrections_accumulate_and_reviewer_gets_critical_criteria(make_orch, mouse):
    orch = make_orch(max_image_attempts=3)
    orch.reviewer = ScriptedReviewer([_rej("move the scroll wheel between the clicks", "roda fora do lugar"),
                                      _rej("side buttons on the LEFT only", "botões laterais espelhados"),
                                      ReviewResult(decision=A)])
    pid = _images_only(orch, mouse)
    orch.run(pid)
    prompts = [a["prompt"] for a in orch.db.attempts(pid, 1, "image")]
    assert len(prompts) == 3
    assert "CORRECTIONS FROM PREVIOUS REVIEWS" not in prompts[0]
    assert "NEW, APPLY STRICTLY: move the scroll wheel" in prompts[1]
    assert "ALREADY FIXED, KEEP IT FIXED: move the scroll wheel" in prompts[2]   # a 1ª correção não se perde
    assert "NEW, APPLY STRICTLY: side buttons on the LEFT only" in prompts[2]
    assert any(c.startswith("CRÍTICO") for c in orch.reviewer.specs[0].approval_criteria)
    # aprovou: o histórico zera
    orch.approve(pid, 1, "image")
    assert orch.db.scene(pid, 1)["image_corrections_json"] is None


def test_hands_only_problem_is_a_warning_not_a_retry(make_orch, mouse):
    orch = make_orch(SimulationScript(image_reviews=["aesthetic"]), max_image_attempts=2)
    pid = _images_only(orch, mouse)
    orch.run(pid)
    assert len(orch.db.attempts(pid, 1, "image")) == 1
    assert orch.db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL
    review = json.loads(orch.db.reviews(pid, 1)[-1]["result_json"])
    assert review["decision"] == "approved" and review["warnings"]
    assert any(e["type"] == "review_warning" for e in orch.db.events(pid))


def test_two_attempts_then_side_by_side_choice(make_orch, mouse):
    orch = make_orch(SimulationScript(image_reviews=[R, R]), max_image_attempts=2)
    pid = _images_only(orch, mouse)
    orch.run(pid)
    assert orch.db.scene(pid, 1)["status"] == SS.BLOCKED
    last = [e for e in orch.db.events(pid) if e["type"] == "scene_status" and e["scene_idx"] == 1][-1]
    assert "lado a lado" in last["message"]
    cands = orch.candidates(pid, 1, "image")
    assert len(cands) == 2
    with pytest.raises(Exception):
        orch.choose_attempt(pid, 1, "image", "att_inexistente")
    orch.choose_attempt(pid, 1, "image", cands[0]["id"])
    row = orch.db.scene(pid, 1)
    assert row["status"] == SS.IMAGE_APPROVED and row["approved_image_attempt"] == cands[0]["id"]


def test_default_image_limit_is_two(tmp_path, monkeypatch):
    for var in ("STUDIO_MAX_IMAGE_ATTEMPTS",):
        monkeypatch.delenv(var, raising=False)
    assert load_settings(env_file=tmp_path / "none.env", mode="simulated").max_image_attempts == 2


def test_anchor_becomes_primary_reference(make_orch, mouse):
    orch = make_orch(SimulationScript(image_reviews=[A, A, A]))
    pid = _images_only(orch, mouse)
    orch.run(pid)
    first = orch.db.attempts(pid, 1, "image")[0]
    orch.approve(pid, 1, "image")
    orch.set_anchor(pid, first["id"])
    orch.run(pid)
    att2 = orch.db.attempts(pid, 2, "image")[0]
    refs = json.loads(att2["references_json"])
    assert refs[0]["key"] == "product:anchor" and refs[0]["sha256"] == first["output_sha256"]
    assert "PRIMARY PRODUCT REFERENCE" in att2["prompt"]
    with pytest.raises(Exception):
        orch.set_anchor(pid, "att_de_outra_producao")
    orch.set_anchor(pid, None)
    assert orch._anchor(pid) is None


def test_metrics_record_attempts_per_scene_and_reasons(make_orch, mouse):
    orch = make_orch(SimulationScript(image_reviews=[R, "aesthetic", A, A]), max_image_attempts=2)
    pid = _images_only(orch, mouse)
    orch.run(pid)   # cena 1: reprovada (produto) → 2ª tentativa só com aviso de mão → aguardando o operador
    assert orch.db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL
    orch.reject(pid, 1, "image", "a cor do cabo está errada")
    m = metrics.internal_metrics(orch.db, days=0)["simulated"]
    by_scene = {r["scene"]: r for r in m["scene_attempts"]["by_scene"]}
    assert by_scene[1]["avg_image"] == 2.0
    reasons = {(r["code"], r["source"], r["blocking"]): r["count"] for r in m["retry_reasons"]}
    assert reasons[("produto_outro", "auto", True)] == 1      # reprovação crítica do revisor simulado
    assert reasons[("mao", "auto", False)] == 1               # aviso de mão (não bloqueou)
    assert reasons[("produto_cor", "human", True)] == 1 and reasons[("produto_cabo", "human", True)] == 1
    text = metrics.format_text(metrics.internal_metrics(orch.db, days=0))
    assert "tentativas por cena (posição)" in text and "motivos de nova tentativa" in text
    assert "cabo está errada" not in json.dumps(m)              # nada de texto livre nas métricas


# ============================================================ web (servidor do estúdio, provedores simulados)
HOST = {"Host": "127.0.0.1:8765"}


@pytest.fixture
def app(settings, tmp_path):
    loader = lambda: dataclasses.replace(  # noqa: E731
        load_settings(env_file=tmp_path / "none.env", mode="simulated", data_dir=settings.data_dir,
                      assets_dir=settings.assets_dir, profiles_dir=settings.profiles_dir, x264_preset="ultrafast"))
    a = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(a, HOST)
    return a


def _post(app, path, body=None):
    return app.handle("POST", path, {**HOST, "X-Studio-Token": app.token}, json.dumps(body or {}).encode())


def _state(app, pid):
    return json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)["production"]


def _wait(app, pid, timeout=60):
    end = time.time() + timeout
    while app.is_running(pid) and time.time() < end:
        time.sleep(0.1)


def test_preview_suggests_product_only_for_complex_products(app):
    body = {"name": "Mouse Gamer Raze", "creative": {"presentation": "hands_only"}}
    pv = json.loads(_post(app, "/api/creative/preview", body).body)
    assert pv["format_advice"]["suggested"] == "product_only" and "Produto em destaque" in pv["warnings"][0]
    pv = json.loads(_post(app, "/api/creative/preview", {**body, "creative": {"presentation": "product_only"}}).body)
    assert pv["format_advice"] is None
    pv = json.loads(_post(app, "/api/creative/preview", {"name": "Copo com alça",
                                                         "creative": {"presentation": "hands_only"}}).body)
    assert pv["format_advice"] is None


def test_web_state_exposes_facts_candidates_and_actions(app):
    pid = json.loads(_post(app, "/api/demo", {"budget": 5}).body)["pid"]
    _wait(app, pid)
    P = _state(app, pid)
    assert P["facts"] is not None and "candidates" in P["scenes"][0]
    sc1 = P["scenes"][0]
    assert sc1["status"] == "awaiting_image_approval" and len(sc1["candidates"]["image"]) == 1
    att = sc1["candidates"]["image"][0]["id"]
    assert _post(app, f"/api/productions/{pid}/anchor", {"attempt_id": "nada"}).status == 409
    assert _post(app, f"/api/productions/{pid}/anchor", {"attempt_id": att}).status == 200
    assert _state(app, pid)["anchor"]["attempt_id"] == att
    assert _post(app, f"/api/productions/{pid}/choose", {"scene": 1, "stage": "image", "attempt_id": "x"}).status == 409
    assert _post(app, f"/api/productions/{pid}/choose", {"scene": 1, "stage": "image", "attempt_id": att}).status == 200
    _wait(app, pid)
    assert _state(app, pid)["scenes"][0]["approved_image"] == att
