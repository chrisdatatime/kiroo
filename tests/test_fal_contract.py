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
    assert pkg.video.url.endswith("final.mp4") and pkg.narration.kind == "narration"


def test_roles_come_from_the_mapping_not_from_list_order():
    pkg = parse()
    assert [pkg.images[r].url.rsplit("/", 1)[1] for r in fc.ROLES] == ["hero.jpg", "lifestyle.jpg", "details.jpg"]


def test_without_envelope_the_result_is_the_output():
    pkg = fc.parse_result(sample_result(envelope=False), "light", C)
    assert pkg.failure_kind() is None and pkg.nodes == {} and all(a.recover is None for a in pkg.images.values())


def test_envelope_gives_recovery_info_per_image():
    pkg = parse()
    assert pkg.images["hero"].recover == {"endpoint": "fal-ai/img/a", "request_id": "r-hero", "path": "image.url"}


def test_missing_music_is_allowed_with_warning():
    pkg = parse(drop=["audio.music"])
    assert pkg.missing() == ["music"] and pkg.failure_kind() is None and pkg.warnings


@pytest.mark.parametrize("drop,comp", [("final.video", "video"), ("audio.voice", "narration")])
def test_missing_video_or_narration_is_technical_failure(drop, comp):
    pkg = parse(drop=[drop])
    assert comp in pkg.missing() and pkg.failure_kind() == "technical"


@pytest.mark.parametrize("idx,role", [(2, "hero"), (0, "lifestyle"), (1, "details")])
def test_image_missing_url_keeps_only_the_recovery_handle(idx, role):
    pkg = parse(drop=[f"pics.{idx}"])
    # sem URL, so o recover do no segura o artefato: a pipeline tenta recuperar (nunca reexecuta o workflow)
    assert pkg.images[role].url is None and pkg.images[role].recover is not None


def test_missing_image_without_recovery_info_is_incomplete():
    pkg = fc.parse_result(sample_result(drop=["pics.1"], envelope=False), "dark", C)
    assert pkg.missing_images() == ["details"] and pkg.failure_kind() == "incomplete"


def test_two_missing_images():
    pkg = fc.parse_result(sample_result(drop=["pics.0", "pics.1"], envelope=False), "dark", C)
    assert set(pkg.missing_images()) == {"lifestyle", "details"}


def test_non_url_values_are_ignored():
    r = sample_result(envelope=False)
    r["final"]["video"]["url"] = "file:///etc/passwd"
    r["pics"][2]["url"] = "javascript:alert(1)"
    pkg = fc.parse_result(r, "dark", C)
    assert pkg.video is None and "image:hero" in pkg.missing()


def test_get_path_is_safe():
    assert fc.get_path({"a": [{"b": 1}]}, "a.0.b") == 1
    for bad in ("a.5.b", "x.y", "", "A CONFIRMAR (Fase 0)", "a.b"):
        assert fc.get_path({"a": [{"b": 1}]}, bad) is None


def test_build_input_uses_contract_field_and_extras():
    assert fc.build_input(C, "dark", "https://x/y.jpg") == {"language": "pt-BR", "photo_url": "https://x/y.jpg"}


def test_real_contract_is_entirely_placeholder_until_phase_0():
    real = fc.load_contract(PROJECT_ROOT / "profiles")
    assert real["status"].startswith("A CONFIRMAR")
    for style in fc.STYLES:
        pend = fc.placeholders(real, style)
        assert any(p.startswith("input") for p in pend) and any(p.startswith("output.images") for p in pend)
        with pytest.raises(fc.ContractError, match="A CONFIRMAR"):
            fc.build_input(real, style, "https://x/y.jpg")


def test_unknown_style_is_refused():
    with pytest.raises(fc.ContractError):
        fc.parse_result({}, "neon", C)
