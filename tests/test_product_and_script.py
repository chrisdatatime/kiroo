import pytest
from pydantic import ValidationError

from studio.agents import creative
from studio.claims import find_unsupported_claims
from studio.models import ProductInput, ProductSheet
from studio.states import ProductionStatus

from .conftest import create


def test_link_preserved_exactly_and_domain_checked(product):
    link = "https://s.shopee.com.br/7VHTuA2W1j?utm_source=an_123&mmp_pid=an_123"
    p = product.model_copy(update={"affiliate_link": link})
    assert ProductInput.model_validate(p.model_dump()).affiliate_link == link
    with pytest.raises(ValidationError):
        ProductInput.model_validate({**product.model_dump(), "affiliate_link": "https://evil.example.com/x"})
    with pytest.raises(ValidationError):
        ProductInput.model_validate({**product.model_dump(), "affiliate_link": "http://shopee.com.br/x"})


def test_missing_references_block_production(make_orch, product):
    orch = make_orch()
    bad = product.model_copy(update={"references": []})
    pid = create(orch, bad)
    assert orch.run(pid) == ProductionStatus.AWAITING_REFERENCES
    sheet = orch._sheet(pid)
    assert any(i.code == "no_official_images" for i in sheet.blocking_issues)
    assert orch.db.scenes(pid) == []  # nada gerado


def test_screen_recording_only_is_not_enough(make_orch, product, tmp_path):
    rec = tmp_path / "gravacao.mp4"
    rec.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    p = ProductInput.model_validate({**product.model_dump(), "references": [
        {"path": str(rec), "role": "context", "source": "screen_recording"}]})
    orch = make_orch()
    pid = create(orch, p)
    assert orch.run(pid) == ProductionStatus.AWAITING_REFERENCES
    codes = {i.code for i in orch._sheet(pid).issues}
    assert {"no_official_images", "screen_recording_context_only"} <= codes


def test_unknown_fields_are_explicit_and_not_invented(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    sheet = orch._sheet(pid)
    assert "capacidade" in sheet.unknown_fields and "material" in sheet.unknown_fields
    script = orch._script_obj(pid)
    all_prompts = " ".join(s.image_prompt + s.animation_prompt for s in script.scenes).lower()
    for invented in ("500ml", "thermal", "stainless", "bpa"):
        assert invented not in all_prompts


def test_claims_guard(product):
    sheet = ProductSheet(product=product)
    assert find_unsupported_claims("Copo térmico de 500ml, aço inox", sheet)
    assert find_unsupported_claims("Eu uso todo dia e recomendo", sheet)
    assert find_unsupported_claims("Copo com alça — azul-claro\nCor azul-claro", sheet) == []


def test_script_validation_catches_bad_overlay_and_scene_count(make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    profiles = orch._profiles(pid)
    sheet = orch._sheet(pid)
    script = orch._script_obj(pid)
    assert creative.validate_script(script, profiles, sheet) == []
    bad = script.model_copy(update={"scenes": script.scenes[:2]})
    assert any("cenas" in e for e in creative.validate_script(bad, profiles, sheet))
    from studio.models import TextOverlay
    assert script.overlays == []  # formato atual não grava aviso na tela (pedido de 28/10/2026)
    ov = TextOverlay(text="Mantém gelado por 12 horas", start_s=0, end_s=5)
    bad2 = script.model_copy(update={"overlays": [ov]})
    assert any("alegação" in e for e in creative.validate_script(bad2, profiles, sheet))


def test_profile_snapshot_is_frozen(make_orch, product, settings, tmp_path):
    import json
    import shutil

    profiles = tmp_path / "profiles"
    shutil.copytree(settings.profiles_dir, profiles)
    orch = make_orch(profiles_dir=profiles)
    pid = create(orch, product)
    art = profiles / "art_direction" / "cozinha_sp_alto_padrao" / "v1.json"
    data = json.loads(art.read_text(encoding="utf-8"))
    data["environment_en"] = "SETTING: a beach at sunset."
    art.write_text(json.dumps(data), encoding="utf-8")
    orch.run(pid)
    assert "beach" not in orch._script_obj(pid).scenes[0].image_prompt
    assert "São Paulo" in orch._script_obj(pid).scenes[0].image_prompt
