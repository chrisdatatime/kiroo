"""Garantia dura de "Produto em destaque": nenhuma mão ou pessoa nos prompts de imagem e de vídeo, planejador
instruído sem "ação das mãos", roteiro validado e revisor que REPROVA mão/pessoa (não é aviso estético) antes de
qualquer tentativa de vídeo."""

import json
from pathlib import Path

import pytest

from studio.agents import craft, creative, fidelity
from studio.db import Database
from studio.models import ReviewDecision, ReviewResult
from studio.providers import gemini
from studio.providers.base import PlanningContext
from studio.providers.simulated import SimulatedReviewer

from .test_creative_flow import BASE, HOST, PNG, app, post, wait_idle  # noqa: F401

PRODUCT_ONLY = {"presentation": "product_only", "proposal": "details", "environment": "neutro", "tone": "natural"}
FILES = [{"name": "f.png", "data": PNG, "role": "front"}]
HAND_PRIMERS = ("a third hand", "and the hands inside", "hands and product move together", "HANDS:", "extra fingers",
                "only two adult female hands", "ação das mãos")


def _attempts(settings, pid, kind=None):
    db = Database(settings.db_path)
    try:
        return [dict(a) for a in db.attempts(pid, kind=kind)], [dict(e) for e in db.events(pid)]
    finally:
        db.close()


def _hand_review(*_a, **_k):
    """Revisor que viu uma mão: no formato novo ela vem como aviso estético (o modelo segue a regra geral)."""
    return ReviewResult(decision=ReviewDecision.REJECTED, checks={"produto": "ok", "maos": "problema"},
                        warnings=["mão direita aparece ajustando a pegada no canto inferior"],
                        method="teste", reviewer="simulated", simulated=True), {}


def test_generation_prompts_have_no_hand_primers_and_end_with_the_lock(app, settings):
    st, r = post(app, "/api/productions", {**BASE, "creative": PRODUCT_ONLY, "files": FILES})
    pid = r["pid"]
    wait_idle(app, pid)
    for idx in (1, 2, 3):   # aprova as imagens (revisor simulado é inconclusivo) para chegar aos vídeos
        post(app, f"/api/productions/{pid}/approve", {"scene": idx, "stage": "image"})
        wait_idle(app, pid)
    attempts, _ = _attempts(settings, pid)
    images = [a["prompt"] for a in attempts if a["kind"] == "image"]
    videos = [a["prompt"] for a in attempts if a["kind"] == "video"]
    assert len(images) >= 3 and len(videos) >= 3
    for p in images + videos:
        assert p.rstrip().endswith(fidelity.PRODUCT_ONLY_LOCK_EN)
        assert fidelity.PRODUCT_ONLY_NEGATIVE_EN in p and fidelity.DEFAULT_NEGATIVE_EN not in p
        for primer in HAND_PRIMERS:
            assert primer not in p, primer
    assert all("No people, no hands" in p for p in images)


def test_hands_only_keeps_its_hand_rules(app, settings):
    st, r = post(app, "/api/productions", {**BASE, "creative": {**PRODUCT_ONLY, "presentation": "hands_only"},
                                           "files": FILES})
    wait_idle(app, r["pid"])
    attempts, _ = _attempts(settings, r["pid"], "image")
    assert attempts and all(fidelity.DEFAULT_NEGATIVE_EN in a["prompt"] and fidelity.PRODUCT_ONLY_LOCK_EN not in a["prompt"]
                            for a in attempts)


def test_hand_in_product_only_image_is_auto_rejected_and_no_video_is_spent(app, settings, monkeypatch):
    monkeypatch.setattr(SimulatedReviewer, "review_image", _hand_review)
    st, r = post(app, "/api/productions", {**BASE, "creative": PRODUCT_ONLY, "files": FILES, "flow": "game",
                                           "autonomy": "assistido"})
    pid = r["pid"]
    wait_idle(app, pid)
    attempts, events = _attempts(settings, pid)
    images = [a for a in attempts if a["kind"] == "image" and a["scene_idx"] == 1]
    assert len(images) >= 2   # reprovou e refez sozinho até o limite do estúdio (padrão: 2)
    assert not [a for a in attempts if a["kind"] == "video"]   # nenhuma tentativa de vídeo consumida
    corrections = [e["message"] for e in events if e["type"] == "auto_correction"]
    assert corrections and all("Remove every hand" in c for c in corrections)
    assert fidelity.PEOPLE_FIX_EN in images[-1]["prompt"]   # a correção chega ao prompt da tentativa seguinte
    reasons = [json.loads(e["data_json"]) for e in events if e["type"] == "retry_reason"]
    assert reasons and all("pessoa_proibida" in r["codes"] and r["critical"] for r in reasons)
    db = Database(settings.db_path)
    try:
        assert db.scene(pid, 1)["status"] == "blocked" and not db.scene(pid, 1)["approved_image_attempt"]
        rev = [json.loads(x["result_json"]) for x in db.reviews(pid, 1)]
    finally:
        db.close()
    assert rev and all(x["decision"] == "rejected" and fidelity.PEOPLE_LABEL in x["critical_issues"] for x in rev)


def test_same_hand_warning_in_hands_only_still_passes_as_aesthetic(app, settings, monkeypatch):
    monkeypatch.setattr(SimulatedReviewer, "review_image", _hand_review)
    st, r = post(app, "/api/productions", {**BASE, "creative": {**PRODUCT_ONLY, "presentation": "hands_only"},
                                           "files": FILES, "flow": "game", "autonomy": "assistido"})
    wait_idle(app, r["pid"])
    attempts, events = _attempts(settings, r["pid"], "image")
    assert len([a for a in attempts if a["scene_idx"] == 1]) == 1    # aviso estético não refaz (regra do dc34e09)
    assert any(e["type"] == "review_warning" for e in events)


@pytest.mark.parametrize("text, flagged", [
    ("Nenhuma mão visível na cena", False),
    ("no hands visible, product only", False),
    ("sem pessoas em cena", False),
    ("mão direita aparece segurando o produto", True),
    ("a hand enters from the left edge", True),
    ("dedos visíveis na borda inferior", True),
    ("cor do produto levemente mais escura", False),
])
def test_people_detection_in_review_text(text, flagged):
    res = ReviewResult(decision=ReviewDecision.APPROVED, warnings=[text])
    assert bool(fidelity.people_flagged(res)) is flagged
    out = fidelity.enforce_product_only(res)
    assert (out.decision == ReviewDecision.REJECTED) is flagged


def test_people_check_flag_alone_rejects():
    res = ReviewResult(decision=ReviewDecision.APPROVED, checks={"pessoas": "problema"})
    out = fidelity.enforce_product_only(res)
    assert out.decision == ReviewDecision.REJECTED and out.reason_codes[0] == "pessoa_proibida"
    ok = ReviewResult(decision=ReviewDecision.APPROVED, checks={"pessoas": "ok", "maos": "ok"})
    assert fidelity.enforce_product_only(ok).decision == ReviewDecision.APPROVED


def _profiles_and_sheet(fmt):
    from studio.models import ProductInput, ProductSheet
    from studio.profiles import snapshot
    from studio.config import PROJECT_ROOT
    prof = snapshot(PROJECT_ROOT / "profiles", {"presenter": "bia", "art_direction": "ambiente_neutro", "format": fmt})
    product = ProductInput.model_validate({"name": "Mouse", "references": [{"path": "x.png"}]})
    return prof, ProductSheet.model_construct(product=product, issues=[], presenter_assets={})


def test_script_validation_rejects_planner_output_with_hands_in_product_only():
    prof, sheet = _profiles_and_sheet("produto_3cenas_15s")
    draft = creative.build_draft(sheet, prof)
    assert creative.validate_script(draft, prof, sheet) == []
    for scene in draft.scenes:   # nada no rascunho puxa mãos
        for primer in HAND_PRIMERS:
            assert primer not in scene.image_prompt and primer not in scene.animation_prompt, primer
    bad = draft.model_copy(update={"scenes": [
        draft.scenes[0].model_copy(update={"image_prompt": draft.scenes[0].image_prompt.replace(
            "No people, no hands, no body parts in frame. Product only.", "The right hand adjusts the grip.")}),
        *draft.scenes[1:]]})
    errors = creative.validate_script(bad, prof, sheet)
    assert any("perdeu o bloqueio" in e for e in errors) and any("instrução de mão" in e for e in errors)


def test_motion_craft_is_camera_only_for_product_only():
    po = craft.motion_craft("detail", 5, "product_only")
    assert "only the camera moves" in po and "small rotation" not in po and "extra fingers" not in po
    assert "hands and product move together" in craft.motion_craft("detail", 5, "hands_only")


class _Capture(gemini.GeminiPlanner):
    def __init__(self):   # sem cliente: só captura o pedido
        self.model, self.parts = "teste", None

    def _ask_json(self, parts):
        self.parts = parts
        return {"scenes": []}, {}


def test_planner_instructions_do_not_ask_for_hand_action_in_product_only():
    prof, sheet = _profiles_and_sheet("produto_3cenas_15s")
    draft = creative.build_draft(sheet, prof)
    for mode, expect_hands in (("product_only", False), ("hands_only", True)):
        p = _Capture()
        p.refine_script(PlanningContext(draft=draft, product_sheet_json="{}", art_direction={}, presenter_mode=mode))
        text = p.parts[0]["text"]
        assert ("ação das mãos" in text) is expect_hands
        assert ("FORMATO SÓ O PRODUTO" in text) is (not expect_hands)


def test_gemini_review_prompt_makes_people_critical_in_product_only():
    from studio.models import SceneSpec
    prof, sheet = _profiles_and_sheet("produto_3cenas_15s")
    spec = creative.build_draft(sheet, prof).scenes[0]
    assert "CRÍTICO" in gemini._people_rule(spec) and "pessoas" in gemini._people_rule(spec)
    assert gemini._people_rule(spec.model_copy(update={"presenter_mode": "hands_only"})) == ""
    assert isinstance(spec, SceneSpec) and Path  # (tipos usados no teste)
