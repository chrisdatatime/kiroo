"""Contrato canonico do pacote: parser sobre o mapeamento externo, com pacote completo e com cada falha parcial."""

from __future__ import annotations

import pytest

from studio import fal_contract as fc
from studio.config import PROJECT_ROOT

from .fal_fixtures import sample_contract, sample_result

C = sample_contract()


def parse(**kw):
    return fc.parse_result(sample_result(**kw), "dark", C)


def test_complete_package():
    pkg = parse()
    assert pkg.missing() == [] and pkg.failure_kind() is None and pkg.warnings == []
    assert pkg.video.url.endswith("final.mp4") and pkg.hero.url.endswith("hero.jpg")
    assert pkg.title == "Copo azul de aco inox" and pkg.caption.startswith("Mantem")


def test_intermediate_audio_output_is_ignored():
    pkg = parse()
    assert not hasattr(pkg, "narration") and not hasattr(pkg, "music")
    assert "voz.mp3" not in repr(fc.package_to_dict(pkg))


def test_without_envelope_the_result_is_the_output():
    pkg = fc.parse_result(sample_result(envelope=False), "light", C)
    assert pkg.failure_kind() is None and pkg.nodes == {} and pkg.hero.recover is None


def test_envelope_gives_recovery_info_for_the_hero():
    assert parse().hero.recover == {"endpoint": "fal-ai/img/a", "request_id": "r-hero", "path": "image.url"}


def test_missing_video_is_technical_failure():
    pkg = parse(drop=["video"])
    assert pkg.missing() == ["video"] and pkg.failure_kind() == "technical"


def test_hero_missing_url_keeps_only_the_recovery_handle():
    pkg = parse(drop=["images.0"])
    assert pkg.hero.url is None and pkg.hero.recover is not None      # a pipeline tenta recuperar pelo no


def test_missing_hero_without_recovery_info_is_incomplete():
    pkg = fc.parse_result(sample_result(drop=["images.0"], envelope=False), "dark", C)
    assert pkg.missing() == ["hero"] and pkg.failure_kind() == "incomplete"


def test_missing_text_is_only_a_warning():
    pkg = parse(drop=["output"])
    assert pkg.failure_kind() is None and pkg.title == "" and pkg.caption == "" and pkg.warnings


@pytest.mark.parametrize("raw", ["isto nao e json {", "", "   ", "[1, 2]", "null", '{"title": "", "caption": ""}',
                                 '{"title": 3, "caption": null}'])
def test_invalid_or_empty_text_yields_no_text_and_a_warning(raw):
    pkg = parse(text=raw)
    assert (pkg.title, pkg.caption) == ("", "") and pkg.failure_kind() is None and len(pkg.warnings) == 1


def test_text_with_only_one_field_keeps_it_and_warns():
    pkg = parse(text='{"title": "Copo", "caption": ""}')
    assert (pkg.title, pkg.caption) == ("Copo", "") and "legenda" in pkg.warnings[0]
    pkg = parse(text='{"title": "", "caption": "So legenda"}')
    assert (pkg.title, pkg.caption) == ("", "So legenda") and "titulo" in pkg.warnings[0]


def test_text_in_a_code_fence_or_already_decoded_is_read():
    assert fc.parse_text_output('```json\n{"title": "A", "caption": "B"}\n```')[:2] == ("A", "B")
    assert fc.parse_text_output('Aqui vai: {"title": "A", "caption": "B"} fim')[:2] == ("A", "B")
    assert fc.parse_text_output({"title": " A ", "caption": "B"})[:2] == ("A", "B")


def test_non_url_values_are_ignored():
    r = sample_result(envelope=False)
    r["video"]["url"] = "file:///etc/passwd"
    r["images"][0]["url"] = "javascript:alert(1)"
    pkg = fc.parse_result(r, "dark", C)
    assert pkg.video is None and pkg.hero is None and pkg.missing() == ["video", "hero"]


def test_package_roundtrip_through_result_json():
    pkg = parse(text="invalido")
    again = fc.package_from_dict(fc.package_to_dict(pkg))
    assert again.video.url == pkg.video.url and again.hero.recover == pkg.hero.recover and again.warnings == pkg.warnings


def test_get_path_is_safe():
    assert fc.get_path({"a": [{"b": 1}]}, "a.0.b") == 1
    for bad in ("a.5.b", "x.y", "", "A CONFIRMAR (Fase 0)", "a.b"):
        assert fc.get_path({"a": [{"b": 1}]}, bad) is None


def test_build_input_sends_only_the_image_url():
    assert fc.build_input(C, "dark", "https://x/y.jpg") == {"image_url": "https://x/y.jpg"}


def test_real_contract_maps_the_real_outputs_and_keeps_the_open_items_pending():
    real = fc.load_contract(PROJECT_ROOT / "profiles")
    for style in fc.STYLES:
        cfg = real["styles"][style]
        assert cfg["input"] == {"image_field": "image_url", "extra": {}}                  # so image_url
        assert cfg["output"] == {"video": "video.url", "image": "images.0.url", "text": "output"}
        assert all(k not in cfg["output"] for k in ("narration", "music", "description", "narration_text"))
        assert list(cfg["recover"]) == ["hero"]
        pend = fc.placeholders(real, style)
        assert any(p.startswith("recover.hero") for p in pend) and any("indice 0" in p for p in pend)
        assert fc.build_input(real, style, "https://x/y.jpg") == {"image_url": "https://x/y.jpg"}


def test_unknown_style_is_refused():
    with pytest.raises(fc.ContractError):
        fc.parse_result({}, "neon", C)
